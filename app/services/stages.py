"""环节流转服务（design.md 3.1 / 3.4 / 8.3）。

状态机规则全部委托 state_machine 模块；本层负责：
- 权限校验（负责 PM / Admin / 环节负责人，design.md 2.2）
- 留痕（变更历史、回退历史、暂停顺延 auto 日志）
- 每个写操作内同步重算需求状态（design.md 3.3）
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.enums import StageStatus, StageType
from app.models import (
    Requirement,
    RequirementStage,
    StageRevertLog,
    StageTimeChangeLog,
    User,
)
from app.services import state_machine
from app.services.requirements import RequirementError, get_stages, now_sh
from app.services.state_machine import FlowError
from app.services.time_rules import validate_stage_times

RESUME_SHIFT_REASON = "需求暂停顺延"


class StagePermissionError(Exception):
    """环节操作权限不足（API 层映射为 403）。"""

    def __init__(self, message: str = "无权操作该环节"):
        super().__init__(message)
        self.message = message


async def get_stage(session: AsyncSession, stage_id: int) -> RequirementStage:
    stage = await session.get(RequirementStage, stage_id)
    if stage is None:
        raise RequirementError(f"环节 {stage_id} 不存在", status=404)
    return stage


def assert_requirement_write(user: User, requirement: Requirement) -> None:
    """需求级写权限：负责 PM 或 Admin（design.md 2.2）。"""
    if user.role != "admin" and requirement.responsible_pm_id != user.id:
        raise StagePermissionError("仅负责产品经理或管理员可执行该操作")


def assert_stage_progress(user: User, requirement: Requirement, stage: RequirementStage) -> None:
    """环节实际进度权限：负责 PM / Admin / 环节负责人（design.md 2.2）。"""
    if user.role == "admin" or requirement.responsible_pm_id == user.id:
        return
    if stage.assignee_id == user.id:
        return
    raise StagePermissionError("仅负责 PM、管理员或环节负责人可更新环节进度")


async def _load_and_touch(
    session: AsyncSession, requirement: Requirement
) -> list[RequirementStage]:
    stages = await get_stages(session, requirement.id)
    requirement.updated_at = now_sh()
    return stages


async def start_stage(
    session: AsyncSession, stage: RequirementStage, user: User
) -> Requirement:
    """环节开始（design.md 8.3）。"""
    requirement = await session.get(Requirement, stage.requirement_id)
    assert_stage_progress(user, requirement, stage)
    stages = await get_stages(session, requirement.id)
    try:
        state_machine.can_start_stage(stages, stage)
        stage.status = StageStatus.IN_PROGRESS.value
        stage.actual_start = now_sh()
        state_machine.recalc_status(requirement, stages, now_sh())
    except FlowError as e:
        raise RequirementError(e.message)
    await _load_and_touch(session, requirement)
    return requirement


async def complete_stage(
    session: AsyncSession, stage: RequirementStage, user: User
) -> Requirement:
    """环节完成；上线完成则需求置为已完成（design.md 8.3）。"""
    requirement = await session.get(Requirement, stage.requirement_id)
    assert_stage_progress(user, requirement, stage)
    stages = await get_stages(session, requirement.id)
    try:
        state_machine.can_complete_stage(stage)
        stage.status = StageStatus.DONE.value
        stage.actual_end = now_sh()
        if stage.stage_type == StageType.RELEASE.value:
            requirement.status = "done"  # 终态（design.md 3.3）
        else:
            state_machine.recalc_status(requirement, stages, now_sh())
    except FlowError as e:
        raise RequirementError(e.message)
    await _load_and_touch(session, requirement)
    return requirement


async def revert_stage(
    session: AsyncSession,
    from_stage: RequirementStage,
    to_stage_id: int,
    reason: str,
    user: User,
) -> tuple[Requirement, list[RequirementStage]]:
    """环节回退：校验、执行重置、留痕、重算（design.md 3.1 回退规则）。"""
    requirement = await session.get(Requirement, from_stage.requirement_id)
    assert_requirement_write(user, requirement)
    stages = await get_stages(session, requirement.id)
    to_stage = next((s for s in stages if s.id == to_stage_id), None)
    if to_stage is None or to_stage.requirement_id != requirement.id:
        raise RequirementError(f"目标环节 {to_stage_id} 不存在或不属于该需求", status=404)
    try:
        reset = state_machine.apply_revert(
            requirement, stages, from_stage, to_stage, now_sh()
        )
    except FlowError as e:
        raise RequirementError(e.message)
    session.add(
        StageRevertLog(
            requirement_id=requirement.id,
            from_stage_id=from_stage.id,
            to_stage_id=to_stage.id,
            reverted_by=user.id,
            reason=reason,
        )
    )
    await _load_and_touch(session, requirement)
    return requirement, reset


async def update_stage_plan(
    session: AsyncSession,
    stage: RequirementStage,
    *,
    planned_start: datetime | None,
    planned_end: datetime | None,
    reason: str,
    user: User,
) -> Requirement:
    """修改预估时间（design.md 3.4）。

    - reason 必填（schema 层已校验非空）；
    - 已完成环节不可修改；
    - 仅记录实际变化字段；改 planned_end 后重置临期提醒标记；
    - 全量时间校验失败则整体报错；成功后同步重算需求状态。
    """
    requirement = await session.get(Requirement, stage.requirement_id)
    assert_requirement_write(user, requirement)
    if stage.status == StageStatus.DONE.value:
        raise RequirementError("已完成的环节不允许再修改预估时间")

    old_start, old_end = stage.planned_start, stage.planned_end
    new_start = planned_start if planned_start is not None else old_start
    new_end = planned_end if planned_end is not None else old_end
    if new_start == old_start and new_end == old_end:
        raise RequirementError("预估时间无变化，无需修改")

    stage.planned_start, stage.planned_end = new_start, new_end
    stages = await get_stages(session, requirement.id)
    errors = validate_stage_times(stages)
    if errors:
        stage.planned_start, stage.planned_end = old_start, old_end  # 回滚
        raise RequirementError("；".join(errors))

    if old_start != new_start:
        session.add(
            StageTimeChangeLog(
                stage_id=stage.id,
                changed_by=user.id,
                field="planned_start",
                old_value=old_start,
                new_value=new_start,
                reason=reason,
            )
        )
    if old_end != new_end:
        session.add(
            StageTimeChangeLog(
                stage_id=stage.id,
                changed_by=user.id,
                field="planned_end",
                old_value=old_end,
                new_value=new_end,
                reason=reason,
            )
        )
        stage.reminder_sent = False  # design.md 4.1：改期后重置临期提醒标记
    stage.last_delay_reason = reason

    state_machine.recalc_status(requirement, stages, now_sh())
    await _load_and_touch(session, requirement)
    return requirement


async def update_stage_assignee(
    session: AsyncSession, stage: RequirementStage, assignee_id: int | None, user: User
) -> RequirementStage:
    """指派/变更环节负责人（design.md 8.3，仅负责 PM 与 Admin）。"""
    requirement = await session.get(Requirement, stage.requirement_id)
    assert_requirement_write(user, requirement)
    if assignee_id is not None and await session.get(User, assignee_id) is None:
        raise RequirementError(f"用户 {assignee_id} 不存在", status=404)
    stage.assignee_id = assignee_id
    await _load_and_touch(session, requirement)
    return stage


async def pause_requirement(
    session: AsyncSession, requirement: Requirement
) -> Requirement:
    try:
        state_machine.pause(requirement, now_sh())
    except FlowError as e:
        raise RequirementError(e.message)
    await _load_and_touch(session, requirement)
    return requirement


async def resume_requirement(
    session: AsyncSession, requirement: Requirement
) -> Requirement:
    """恢复需求：顺延未完成环节时间并写 auto 日志（design.md 3.3 暂停时钟）。"""
    stages = await get_stages(session, requirement.id)
    try:
        shifted = state_machine.apply_resume_shift(requirement, stages, now_sh())
    except FlowError as e:
        raise RequirementError(e.message)
    for stage, old_start, old_end in shifted:
        if old_start is not None:
            session.add(
                StageTimeChangeLog(
                    stage_id=stage.id,
                    changed_by=requirement.responsible_pm_id,
                    field="planned_start",
                    old_value=old_start,
                    new_value=stage.planned_start,
                    reason=RESUME_SHIFT_REASON,
                    auto_generated=True,
                )
            )
        if old_end is not None:
            session.add(
                StageTimeChangeLog(
                    stage_id=stage.id,
                    changed_by=requirement.responsible_pm_id,
                    field="planned_end",
                    old_value=old_end,
                    new_value=stage.planned_end,
                    reason=RESUME_SHIFT_REASON,
                    auto_generated=True,
                )
            )
    state_machine.recalc_status(requirement, stages, now_sh())
    await _load_and_touch(session, requirement)
    return requirement


async def mark_delayed(
    session: AsyncSession, requirement: Requirement, reason: str
) -> Requirement:
    stages = await get_stages(session, requirement.id)
    try:
        state_machine.mark_delayed(requirement, reason, now_sh(), stages)
    except FlowError as e:
        raise RequirementError(e.message)
    await _load_and_touch(session, requirement)
    return requirement


async def unmark_delayed(
    session: AsyncSession, requirement: Requirement, reason: str
) -> Requirement:
    stages = await get_stages(session, requirement.id)
    try:
        state_machine.unmark_delayed(requirement, reason, now_sh(), stages)
    except FlowError as e:
        raise RequirementError(e.message)
    await _load_and_touch(session, requirement)
    return requirement


async def list_change_logs(
    session: AsyncSession, stage_id: int
) -> list[StageTimeChangeLog]:
    return list(
        (
            await session.scalars(
                select(StageTimeChangeLog)
                .where(StageTimeChangeLog.stage_id == stage_id)
                .order_by(StageTimeChangeLog.created_at.desc(), StageTimeChangeLog.id.desc())
            )
        ).all()
    )
