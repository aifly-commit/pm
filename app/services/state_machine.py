"""需求状态机与环节流转核心逻辑（design.md 3.1 / 3.3）。

约定：
- 所有判定函数为纯函数（只读传入对象），便于单测；
- `recalc_status` 在每个写操作落库时同步调用（design.md 3.3 状态判定与刷新机制），
  30 分钟定时任务仅作兜底；
- "延期"为双源：系统逾期（当前时间 > 任一未完成环节 planned_end）或 PM 人工标记
  （requirement.manual_delayed），二者任一存在即 delayed，全部解除才回 in_progress。
"""

from __future__ import annotations

from datetime import datetime, timedelta

from app.enums import (
    ALLOWED_REVERT_TARGETS,
    PREREQUISITES,
    STAGE_SEQ,
    StageStatus,
)
from app.models import Requirement, RequirementStage


class FlowError(Exception):
    """流转规则校验失败（API 层映射为 409，design.md 8.8）。"""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


# ---------------------------------------------------------------- 逾期判定

def is_stage_overdue(stage: RequirementStage, now: datetime) -> bool:
    """单环节是否逾期：planned_end 非空、未完成、当前时间已过（design.md 6.3）。"""
    return (
        stage.planned_end is not None
        and stage.status != StageStatus.DONE.value
        and now > stage.planned_end
    )


def system_overdue_stages(stages: list[RequirementStage], now: datetime) -> list[RequirementStage]:
    """返回所有构成系统逾期的环节。"""
    return [s for s in stages if is_stage_overdue(s, now)]


def has_system_overdue(stages: list[RequirementStage], now: datetime) -> bool:
    return any(is_stage_overdue(s, now) for s in stages)


# ---------------------------------------------------------------- 状态重算

def recalc_status(
    requirement: Requirement,
    stages: list[RequirementStage],
    now: datetime,
    *,
    force_auto: bool = False,
) -> str:
    """按 3.3 口径重算需求状态并写回 requirement.status，返回新状态。

    - manual_status 覆盖位非空时直接返回它，冻结状态（design.md 3.3 手动状态）；
    - done 为终态，不再变化；
    - paused 由暂停/恢复操作维护，此处不动；
    - delayed = 系统逾期 or 人工标记；
    - 任一环节进行中（或已有实际开始）→ in_progress；否则 not_started。
    """
    if requirement.manual_status is not None and not force_auto:
        requirement.status = requirement.manual_status
        return requirement.status
    if requirement.status == "done" and not force_auto:
        return requirement.status
    # 真正的暂停以 paused_at 为准。manual_status="paused" 只是展示覆盖，
    # 清除覆盖后不能继续把需求错误地冻结在 paused。
    if requirement.paused_at is not None:
        requirement.status = "paused"
        return requirement.status
    if requirement.status == "paused" and not force_auto:
        return requirement.status

    if has_system_overdue(stages, now) or requirement.manual_delayed:
        requirement.status = "delayed"
    elif any(s.status == StageStatus.IN_PROGRESS.value for s in stages):
        requirement.status = "in_progress"
    elif any(s.actual_start is not None for s in stages):
        # 全部环节未进行中但有实际开始记录（例如全部已 start 又被回退重置的瞬间）
        requirement.status = "in_progress"
    else:
        requirement.status = "not_started"
    return requirement.status


# ---------------------------------------------------------------- start / complete 校验

def can_start_stage(stages: list[RequirementStage], stage: RequirementStage) -> None:
    """校验环节可否开始，失败抛 FlowError（design.md 8.3）。

    - 环节必须未开始（不可重复 start）；
    - 所有前置环节已完成（前端/API 并行：只依赖平台开发；测试需三者全完成）。
    """
    if stage.status != StageStatus.NOT_STARTED.value:
        raise FlowError(f"环节 {stage.stage_type} 当前状态为 {stage.status}，不可重复开始")
    prereqs = PREREQUISITES[stage.type_enum]
    by_type = {s.type_enum: s for s in stages}
    for p in prereqs:
        ps = by_type.get(p)
        if ps is None or ps.status != StageStatus.DONE.value:
            raise FlowError(f"前置环节 {p.value} 未完成，不可开始 {stage.stage_type}")


def can_complete_stage(stage: RequirementStage) -> None:
    """校验环节可否完成：必须处于进行中（design.md 3.1 完成的前置校验）。"""
    if stage.status != StageStatus.IN_PROGRESS.value:
        raise FlowError(
            f"环节 {stage.stage_type} 当前状态为 {stage.status}，仅进行中的环节可标记完成"
        )


# ---------------------------------------------------------------- 回退

def _furthest_started_stage(stages: list[RequirementStage]) -> RequirementStage | None:
    """返回推进最远的已实际开始环节（seq 最大者）；均未开始返回 None。"""
    started = [s for s in stages if s.actual_start is not None]
    return max(started, key=lambda s: s.seq, default=None)


def can_revert(from_stage: RequirementStage, to_stage: RequirementStage) -> None:
    """校验回退路径合法，失败抛 FlowError（design.md 3.1 回退规则）。"""
    allowed = ALLOWED_REVERT_TARGETS.get(from_stage.type_enum)
    if not allowed:
        raise FlowError(f"环节 {from_stage.stage_type} 不允许发起回退")
    if to_stage.type_enum not in allowed:
        raise FlowError(
            f"不允许从 {from_stage.stage_type} 回退到 {to_stage.stage_type}；"
            f"允许目标：{sorted(t.value for t in allowed)}"
        )


def apply_revert(
    requirement: Requirement,
    stages: list[RequirementStage],
    from_stage: RequirementStage,
    to_stage: RequirementStage,
    now: datetime,
) -> list[RequirementStage]:
    """执行回退并重算需求状态，返回被重置的下游环节列表。

    - 目标环节：置为进行中，actual_end 清空，actual_start 保留；
    - 目标之后（seq 更大）的所有环节：重置为未开始，actual_start/actual_end 清空；
    - 已完成需求不可回退；上线环节不可被回退；
    - 只能从"当前所处环节"（推进最远、有实际开始记录的环节）发起回退，
      防止对历史环节回退时误清下游环节的实际时间。
    """
    if requirement.status == "done":
        raise FlowError("已完成的需求为终态，不可回退")

    current = _furthest_started_stage(stages)
    if current is None:
        raise FlowError("尚无已开始的环节，不可回退")
    if current.seq != from_stage.seq:
        raise FlowError(
            f"只能从当前所处环节 {current.stage_type} 发起回退，"
            f"不能从 {from_stage.stage_type} 发起"
        )
    if from_stage.status not in (StageStatus.IN_PROGRESS.value, StageStatus.DONE.value):
        raise FlowError(
            f"环节 {from_stage.stage_type} 当前状态为 {from_stage.status}，不可发起回退"
        )

    can_revert(from_stage, to_stage)

    to_stage.status = StageStatus.IN_PROGRESS.value
    to_stage.actual_end = None
    to_stage.reminder_sent = False  # 重新执行后临近排期需再次提醒（design.md 4.1）

    reset: list[RequirementStage] = []
    for s in stages:
        if s.seq > to_stage.seq:
            s.status = StageStatus.NOT_STARTED.value
            s.actual_start = None
            s.actual_end = None
            s.reminder_sent = False  # 重置环节清除旧的临期提醒标记，避免漏发
            reset.append(s)

    recalc_status(requirement, stages, now)
    return reset


# ---------------------------------------------------------------- 暂停 / 恢复

def apply_status(requirement: Requirement, value: str) -> None:
    """写 status，但 manual_status 覆盖位非空时冻结不动（design.md 3.3）。

    供 complete（release→done）、pause、resume 等流程替代裸 `req.status = X`，
    保证手动覆盖不被这些流程同步改写。
    """
    if requirement.manual_status is None:
        requirement.status = value


def pause(requirement: Requirement, now: datetime) -> None:
    """暂停需求：记录暂停前状态与暂停时刻（design.md 3.3 暂停的时钟处理）。"""
    if requirement.status in ("paused", "done"):
        raise FlowError(f"当前状态 {requirement.status} 不可暂停")
    requirement.paused_from = requirement.status
    requirement.paused_at = now
    apply_status(requirement, "paused")


def apply_resume_shift(
    requirement: Requirement, stages: list[RequirementStage], now: datetime
) -> list[tuple[RequirementStage, datetime | None, datetime | None]]:
    """恢复需求：未完成环节的预估时间按暂停时长（自然日）统一顺延。

    返回 [(环节, 旧 planned_start, 旧 planned_end), ...] 供调用方写 auto_generated
    变更历史（原因"需求暂停顺延"，不计入人工延期统计）。随后由调用方重算状态。
    """
    if requirement.status != "paused" or requirement.paused_at is None:
        raise FlowError("仅暂停中的需求可恢复")
    days = (now.date() - requirement.paused_at.date()).days
    shifted: list[tuple[RequirementStage, datetime | None, datetime | None]] = []
    if days > 0:
        delta = timedelta(days=days)
        for s in stages:
            if s.status != StageStatus.DONE.value and (
                s.planned_start is not None or s.planned_end is not None
            ):
                shifted.append((s, s.planned_start, s.planned_end))
                if s.planned_start is not None:
                    s.planned_start += delta
                if s.planned_end is not None:
                    s.planned_end += delta
                # 排期已顺延，旧的临期提醒标记作废，临近新排期时应再次提醒
                s.reminder_sent = False
    apply_status(requirement, requirement.paused_from or "not_started")
    requirement.paused_from = None
    requirement.paused_at = None
    return shifted


# ---------------------------------------------------------------- 人工标记延期

def mark_delayed(requirement: Requirement, reason: str, now: datetime, stages: list[RequirementStage]) -> None:
    """PM 人工标记延期（design.md 3.3）：须填原因；终态/暂停态不可标记。"""
    if not reason or not reason.strip():
        raise FlowError("人工标记延期必须填写原因")
    if requirement.status in ("done", "paused"):
        raise FlowError(f"当前状态 {requirement.status} 不可标记延期")
    requirement.manual_delayed = True
    requirement.manual_delay_reason = reason.strip()
    recalc_status(requirement, stages, now)


def unmark_delayed(requirement: Requirement, reason: str, now: datetime, stages: list[RequirementStage]) -> None:
    """PM 解除人工延期：若仍有系统逾期，状态保持 delayed（design.md 3.3）。"""
    if not reason or not reason.strip():
        raise FlowError("解除人工延期必须填写原因")
    if not requirement.manual_delayed:
        raise FlowError("该需求未被人工标记延期")
    requirement.manual_delayed = False
    requirement.manual_delay_reason = None
    recalc_status(requirement, stages, now)


__all__ = [
    "FlowError",
    "is_stage_overdue",
    "system_overdue_stages",
    "has_system_overdue",
    "recalc_status",
    "apply_status",
    "can_start_stage",
    "can_complete_stage",
    "can_revert",
    "apply_revert",
    "pause",
    "apply_resume_shift",
    "mark_delayed",
    "unmark_delayed",
    "make_default_stages",
]


def make_default_stages(requirement_id: int) -> list[dict]:
    """创建需求时自动生成 7 个环节实例的默认值（design.md 3.1）。"""
    return [
        {
            "requirement_id": requirement_id,
            "stage_type": st.value,
            "seq": seq,
            "status": StageStatus.NOT_STARTED.value,
        }
        for st, seq in STAGE_SEQ.items()
    ]
