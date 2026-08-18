"""提醒与通知服务（design.md 4.1 / 4.2）。

- 定时扫描（APScheduler 每 30 分钟，见 app/scheduler.py）+ 状态变更即时通知；
- 时间触发型（due_soon / overdue / start_soon）按
  `{stage_id}:{type}:{yyyy-mm-dd}` 去重；status_changed 不去重（dedupe_key=NULL）；
- 接收人：负责 PM（必发，PM 停用则整条不生成）+ 环节负责人（可选，停用跳过）；
- 扫描范围：排除 paused / done 需求与 planned_end 为 NULL 的环节；
- 扫描同时兜底刷新需求状态（进行中 ↔ 延期），写操作内已同步重算。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.enums import StageStatus
from app.models import Notification, Requirement, RequirementStage, User
from app.services.requirements import STAGE_LABEL, now_sh
from app.services.state_machine import recalc_status

TYPE_DUE_SOON = "stage_due_soon"
TYPE_OVERDUE = "stage_overdue"
TYPE_START_SOON = "stage_start_soon"
TYPE_STATUS_CHANGED = "status_changed"


@dataclass
class ScanReport:
    """一次扫描的结果摘要（用于日志与测试断言）。"""

    overdue_notifications: int = 0
    due_soon_notifications: int = 0
    start_soon_notifications: int = 0
    requirements_refreshed: list[int] = field(default_factory=list)


def dedupe_key(stage_id: int, ntype: str, now: datetime, user_id: int) -> str:
    """时间触发型去重键（自然日按 Asia/Shanghai）。

    键含 user_id：同一条逻辑提醒发给 PM 与环节负责人多行记录，
    每行各自的键唯一（每人每天每环节每类型最多一条，design.md 4.1 意图不变）。
    """
    return f"{stage_id}:{ntype}:{now.date().isoformat()}:{user_id}"


async def notification_exists(session: AsyncSession, key: str) -> bool:
    result = await session.scalars(
        select(Notification.id).where(Notification.dedupe_key == key)
    )
    return result.first() is not None


async def resolve_recipients(
    session: AsyncSession, requirement: Requirement, stage: RequirementStage | None
) -> list[User]:
    """接收人解析：PM 必发（停用 → 返回空列表=不生成）；assignee 可选。

    status_changed 场景 stage=None，仅解析 PM 与全部环节负责人。
    """
    pm = await session.get(User, requirement.responsible_pm_id)
    if pm is None or not pm.is_active:
        return []
    recipients = [pm]
    if stage is not None and stage.assignee_id is not None:
        assignee = await session.get(User, stage.assignee_id)
        if assignee is not None and assignee.is_active and assignee.id != pm.id:
            recipients.append(assignee)
    return recipients


async def create_notification(
    session: AsyncSession,
    *,
    recipients: list[User],
    ntype: str,
    title: str,
    content: str,
    requirement_id: int | None,
    stage_id: int | None,
    dedupe: bool,
    now: datetime,
) -> int:
    """生成通知（每个接收人一条），返回生成条数。

    dedupe=True 时按"每人每环节每类型每自然日"去重（时间触发型）；
    dedupe=False 不去重（status_changed）。
    """
    created = 0
    for user in recipients:
        key = (
            dedupe_key(stage_id, ntype, now, user.id) if dedupe and stage_id else None
        )
        if key is not None and await notification_exists(session, key):
            continue
        session.add(
            Notification(
                user_id=user.id,
                type=ntype,
                title=title,
                content=content,
                requirement_id=requirement_id,
                stage_id=stage_id,
                dedupe_key=key,
            )
        )
        created += 1
    return created


async def notify_status_changed(
    session: AsyncSession,
    requirement: Requirement,
    stages: list[RequirementStage],
    event: str,
) -> int:
    """需求状态变更通知（design.md 4.1）：暂停/恢复/完成/回退/人工延期标记。

    接收人 = PM + 相关环节负责人；不参与去重。
    """
    pm = await session.get(User, requirement.responsible_pm_id)
    recipients: list[User] = []
    if pm is not None and pm.is_active:
        recipients.append(pm)
    for stage in stages:
        if stage.assignee_id is None:
            continue
        assignee = await session.get(User, stage.assignee_id)
        if (
            assignee is not None
            and assignee.is_active
            and all(a.id != assignee.id for a in recipients)
        ):
            recipients.append(assignee)
    if not recipients:
        return 0
    title = f"【状态变更】需求「{requirement.title}」{event}"
    content = f"需求「{requirement.title}」{event}，当前状态：{requirement.status}。"
    return await create_notification(
        session,
        recipients=recipients,
        ntype=TYPE_STATUS_CHANGED,
        title=title,
        content=content,
        requirement_id=requirement.id,
        stage_id=None,
        dedupe=False,  # status_changed 不去重（design.md 4.1）
        now=now_sh(),
    )


def _format_overdue_days(days: int) -> str:
    return f"{days} 天" if days >= 1 else "不足 1 天"


async def _scan_one_stage(
    session: AsyncSession,
    requirement: Requirement,
    stage: RequirementStage,
    now: datetime,
    report: ScanReport,
) -> None:
    """对单个未完成环节生成逾期/临期通知。"""
    label = STAGE_LABEL.get(stage.stage_type, stage.stage_type)
    recipients = await resolve_recipients(session, requirement, stage)
    if not recipients:
        return

    if now > stage.planned_end:
        days = (now.date() - stage.planned_end.date()).days
        title = f"【环节逾期】需求「{requirement.title}」{label}已逾期"
        content = (
            f"需求「{requirement.title}」的「{label}」环节已逾期"
            f"{_format_overdue_days(days)}（预计结束 {stage.planned_end:%Y-%m-%d}）。"
        )
        report.overdue_notifications += await create_notification(
            session,
            recipients=recipients,
            ntype=TYPE_OVERDUE,
            title=title,
            content=content,
            requirement_id=requirement.id,
            stage_id=stage.id,
            dedupe=True,
            now=now,
        )
    elif (
        stage.planned_end - now <= timedelta(days=settings.reminder_due_soon_days)
        and not stage.reminder_sent
    ):
        title = f"【临期提醒】需求「{requirement.title}」{label}即将到期"
        content = (
            f"需求「{requirement.title}」的「{label}」环节预计于 "
            f"{stage.planned_end:%Y-%m-%d} 结束，请关注进度。"
        )
        created = await create_notification(
            session,
            recipients=recipients,
            ntype=TYPE_DUE_SOON,
            title=title,
            content=content,
            requirement_id=requirement.id,
            stage_id=stage.id,
            dedupe=True,
            now=now,
        )
        if created:
            stage.reminder_sent = True
            report.due_soon_notifications += created


async def _scan_start_soon(
    session: AsyncSession,
    requirement: Requirement,
    stage: RequirementStage,
    now: datetime,
    report: ScanReport,
) -> None:
    """临开始提醒（可选功能，默认关闭，design.md 4.1）。"""
    if stage.planned_start is None or stage.status != StageStatus.NOT_STARTED.value:
        return
    if not (timedelta(0) <= stage.planned_start - now <= timedelta(days=1)):
        return
    label = STAGE_LABEL.get(stage.stage_type, stage.stage_type)
    recipients = await resolve_recipients(session, requirement, stage)
    if not recipients:
        return
    title = f"【临开始提醒】需求「{requirement.title}」{label}即将开始"
    report.start_soon_notifications += await create_notification(
        session,
        recipients=recipients,
        ntype=TYPE_START_SOON,
        title=title,
        content=f"需求「{requirement.title}」的「{label}」环节计划于 "
        f"{stage.planned_start:%Y-%m-%d} 开始。",
        requirement_id=requirement.id,
        stage_id=stage.id,
        dedupe=True,
        now=now,
    )


async def run_scan(session: AsyncSession, now: datetime | None = None) -> ScanReport:
    """执行一次全量扫描：生成通知 + 兜底刷新需求状态（design.md 4.2）。

    排除：真正处于暂停时钟中的需求（paused_at 非空）、已完成环节；
    planned_end 为 NULL 的环节。manual_status 只覆盖展示状态，不中断环节提醒。
    """
    now = now or now_sh()
    report = ScanReport()

    rows = (
        (
            await session.execute(
                select(Requirement, RequirementStage)
                .join(RequirementStage, RequirementStage.requirement_id == Requirement.id)
                .where(
                    Requirement.paused_at.is_(None),
                    RequirementStage.status != StageStatus.DONE.value,
                )
            )
        ).all()
    )

    requirements_by_id: dict[int, Requirement] = {}
    stages_by_req: dict[int, list[RequirementStage]] = {}
    for req, stage in rows:
        requirements_by_id[req.id] = req
        stages_by_req.setdefault(req.id, []).append(stage)

    for req_id, stages in stages_by_req.items():
        req = requirements_by_id[req_id]
        for stage in stages:
            if stage.planned_end is not None:
                await _scan_one_stage(session, req, stage, now, report)
            if settings.reminder_start_soon_enabled:
                await _scan_start_soon(session, req, stage, now, report)

    # 兜底刷新：任何有逾期环节的需求重算状态（写操作内已同步，此处只兜时间流逝）
    for req_id, stages in stages_by_req.items():
        req = requirements_by_id[req_id]
        before = req.status
        recalc_status(req, stages, now)
        if req.status != before:
            report.requirements_refreshed.append(req_id)
            # 系统触发的变更同样留痕（changed_by=NULL，design.md 10.2）
            from app.models import RequirementStatusLog

            session.add(
                RequirementStatusLog(
                    requirement_id=req.id,
                    from_status=before,
                    to_status=req.status,
                    changed_by=None,
                )
            )

    return report
