"""提醒扫描服务（design.md 4.1 / 4.2）——注入时钟，逐条验证规则。"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select

from app.enums import STAGE_SEQ, StageStatus, StageType
from app.models import Notification, Requirement, RequirementStage
from app.services.notifications import (
    TYPE_DUE_SOON,
    TYPE_OVERDUE,
    TYPE_START_SOON,
    notify_status_changed,
    run_scan,
)
from tests.helpers import NOW, get_stage

NOW_SH = datetime(2026, 8, 14, 10, 0, 0)  # 周五


async def seed_requirement(db, pm_id, **req_kwargs) -> tuple[Requirement, list[RequirementStage]]:
    req = Requirement(title="提醒测试需求", responsible_pm_id=pm_id, **req_kwargs)
    db.add(req)
    await db.flush()
    stages = [
        RequirementStage(
            requirement_id=req.id,
            stage_type=st.value,
            seq=seq,
            status=StageStatus.NOT_STARTED.value,
        )
        for st, seq in STAGE_SEQ.items()
    ]
    db.add_all(stages)
    await db.flush()
    return req, stages


async def notifications_of(db, ntype: str | None = None) -> list[Notification]:
    stmt = select(Notification).order_by(Notification.id)
    if ntype:
        stmt = stmt.where(Notification.type == ntype)
    return list((await db.scalars(stmt)).all())


class TestOverdueScan:
    async def test_overdue_creates_notifications_for_pm_and_assignee(self, db, pm_user):
        from tests.conftest import seed_user

        dev = await seed_user(db, "notify_dev", "developer")
        req, stages = await seed_requirement(db, pm_user.id)
        research = get_stage(stages, StageType.RESEARCH)
        research.planned_end = NOW_SH - timedelta(days=2)
        research.assignee_id = dev.id
        await db.flush()

        report = await run_scan(db, NOW_SH)

        assert report.overdue_notifications == 2  # PM + 负责人
        overdue = await notifications_of(db, TYPE_OVERDUE)
        assert {n.user_id for n in overdue} == {pm_user.id, dev.id}
        assert "已逾期" in overdue[0].title
        assert overdue[0].requirement_id == req.id
        assert overdue[0].stage_id == research.id
        # 兜底刷新：未开始 + 逾期 → 延期
        assert req.status == "delayed"
        assert req.id in report.requirements_refreshed

    async def test_boundary_equal_not_overdue_but_due_soon(self, db, pm_user):
        from app.enums import StageType

        _, stages = await seed_requirement(db, pm_user.id)
        get_stage(stages, StageType.RESEARCH).planned_end = NOW_SH  # 恰好到期
        await db.flush()
        report = await run_scan(db, NOW_SH)
        # 须严格大于才算逾期；但落入临期窗口（≤1 天）→ 发临期提醒
        assert report.overdue_notifications == 0
        assert report.due_soon_notifications == 1

    async def test_overdue_deduped_per_day(self, db, pm_user):
        from app.enums import StageType

        _, stages = await seed_requirement(db, pm_user.id)
        get_stage(stages, StageType.RESEARCH).planned_end = NOW_SH - timedelta(hours=1)
        await db.flush()

        await run_scan(db, NOW_SH)
        await run_scan(db, NOW_SH + timedelta(minutes=30))  # 同日第二次扫描
        overdue = await notifications_of(db, TYPE_OVERDUE)
        assert len(overdue) == 1

        # 次日再扫 → 新自然日再发一条（每天最多一条）
        await run_scan(db, NOW_SH + timedelta(days=1))
        overdue = await notifications_of(db, TYPE_OVERDUE)
        assert len(overdue) == 2

    async def test_done_stage_and_done_requirement_excluded(self, db, pm_user):
        from app.enums import StageType

        req, stages = await seed_requirement(db, pm_user.id)
        research = get_stage(stages, StageType.RESEARCH)
        research.planned_end = NOW_SH - timedelta(days=1)
        research.status = StageStatus.DONE.value  # 环节已完成
        req.status = "done"  # 需求终态
        await db.flush()
        report = await run_scan(db, NOW_SH)
        assert report.overdue_notifications == 0

    async def test_paused_requirement_excluded(self, db, pm_user):
        from app.enums import StageType

        req, stages = await seed_requirement(db, pm_user.id)
        get_stage(stages, StageType.RESEARCH).planned_end = NOW_SH - timedelta(days=1)
        req.status = "paused"  # 暂停冻结判定（design.md 3.3）
        await db.flush()
        report = await run_scan(db, NOW_SH)
        assert report.overdue_notifications == 0

    async def test_null_planned_end_excluded(self, db, pm_user):
        req, stages = await seed_requirement(db, pm_user.id)
        assert all(s.planned_end is None for s in stages)
        report = await run_scan(db, NOW_SH)
        assert report.overdue_notifications == 0
        assert report.due_soon_notifications == 0
        assert req.status == "not_started"


class TestDueSoonScan:
    async def test_due_soon_once_then_flag(self, db, pm_user):
        from app.enums import StageType

        req, stages = await seed_requirement(db, pm_user.id)
        research = get_stage(stages, StageType.RESEARCH)
        research.planned_end = NOW_SH + timedelta(hours=12)  # 1 天窗口内
        await db.flush()

        report = await run_scan(db, NOW_SH)
        assert report.due_soon_notifications == 1
        assert research.reminder_sent is True

        # 再扫 → 标记已置，不再发
        report = await run_scan(db, NOW_SH + timedelta(hours=1))
        assert report.due_soon_notifications == 0
        due = await notifications_of(db, TYPE_DUE_SOON)
        assert len(due) == 1

    async def test_outside_window_no_reminder(self, db, pm_user):
        from app.enums import StageType

        _, stages = await seed_requirement(db, pm_user.id)
        get_stage(stages, StageType.RESEARCH).planned_end = NOW_SH + timedelta(days=3)
        await db.flush()
        report = await run_scan(db, NOW_SH)
        assert report.due_soon_notifications == 0

    async def test_replan_resets_flag_and_re_reminds(self, db, pm_user):
        from app.enums import StageType

        _, stages = await seed_requirement(db, pm_user.id)
        research = get_stage(stages, StageType.RESEARCH)
        research.planned_end = NOW_SH + timedelta(hours=12)
        await db.flush()
        await run_scan(db, NOW_SH)  # 第一条临期提醒

        # 改期（标记重置，M2 已实现）：新的截止时间在新扫描时刻前 6 小时
        second_scan_at = NOW_SH + timedelta(days=5)
        research.planned_end = second_scan_at + timedelta(hours=6)
        research.reminder_sent = False
        await db.flush()
        report = await run_scan(db, second_scan_at)
        assert report.due_soon_notifications == 1
        due = await notifications_of(db, TYPE_DUE_SOON)
        assert len(due) == 2


class TestStartSoonScan:
    async def test_disabled_by_default(self, db, pm_user):
        from app.enums import StageType

        _, stages = await seed_requirement(db, pm_user.id)
        get_stage(stages, StageType.RESEARCH).planned_start = NOW_SH + timedelta(hours=6)
        await db.flush()
        report = await run_scan(db, NOW_SH)
        assert report.start_soon_notifications == 0

    async def test_enabled_creates_reminder(self, db, pm_user, monkeypatch):
        from app.core.config import settings
        from app.enums import StageType

        monkeypatch.setattr(settings, "reminder_start_soon_enabled", True)
        _, stages = await seed_requirement(db, pm_user.id)
        get_stage(stages, StageType.RESEARCH).planned_start = NOW_SH + timedelta(hours=6)
        await db.flush()
        report = await run_scan(db, NOW_SH)
        assert report.start_soon_notifications == 1
        assert await notifications_of(db, TYPE_START_SOON)

    async def test_start_soon_outside_window_skipped(self, db, pm_user, monkeypatch):
        from app.core.config import settings
        from app.enums import StageType

        monkeypatch.setattr(settings, "reminder_start_soon_enabled", True)
        _, stages = await seed_requirement(db, pm_user.id)
        research = get_stage(stages, StageType.RESEARCH)
        research.planned_start = NOW_SH + timedelta(days=3)  # 超出 1 天窗口
        await db.flush()
        report = await run_scan(db, NOW_SH)
        assert report.start_soon_notifications == 0

        research.planned_start = NOW_SH - timedelta(hours=1)  # 已过开始时间
        await db.flush()
        report = await run_scan(db, NOW_SH)
        assert report.start_soon_notifications == 0

    async def test_start_soon_no_recipients_skipped(self, db, pm_user, monkeypatch):
        from app.core.config import settings
        from app.enums import StageType

        monkeypatch.setattr(settings, "reminder_start_soon_enabled", True)
        pm_user.is_active = False
        _, stages = await seed_requirement(db, pm_user.id)
        get_stage(stages, StageType.RESEARCH).planned_start = NOW_SH + timedelta(hours=6)
        await db.flush()
        report = await run_scan(db, NOW_SH)
        assert report.start_soon_notifications == 0


class TestRecipientRules:
    async def test_inactive_pm_generates_nothing(self, db, pm_user):
        from app.enums import StageType

        pm_user.is_active = False
        _, stages = await seed_requirement(db, pm_user.id)
        get_stage(stages, StageType.RESEARCH).planned_end = NOW_SH - timedelta(days=1)
        await db.flush()
        report = await run_scan(db, NOW_SH)
        assert report.overdue_notifications == 0
        assert await notifications_of(db) == []

    async def test_inactive_assignee_skipped_pm_kept(self, db, pm_user):
        from app.enums import StageType
        from tests.conftest import seed_user

        dev = await seed_user(db, "ghost_dev", "developer")
        dev.is_active = False
        _, stages = await seed_requirement(db, pm_user.id)
        research = get_stage(stages, StageType.RESEARCH)
        research.planned_end = NOW_SH - timedelta(days=1)
        research.assignee_id = dev.id
        await db.flush()
        report = await run_scan(db, NOW_SH)
        assert report.overdue_notifications == 1  # 只剩 PM
        overdue = await notifications_of(db, TYPE_OVERDUE)
        assert [n.user_id for n in overdue] == [pm_user.id]

    async def test_assignee_same_as_pm_not_duplicated(self, db, pm_user):
        from app.enums import StageType

        _, stages = await seed_requirement(db, pm_user.id)
        research = get_stage(stages, StageType.RESEARCH)
        research.planned_end = NOW_SH - timedelta(days=1)
        research.assignee_id = pm_user.id
        await db.flush()
        report = await run_scan(db, NOW_SH)
        assert report.overdue_notifications == 1


class TestStatusChangedNotification:
    async def test_no_dedupe_multiple_events_same_day(self, db, pm_user, stages):
        from tests.helpers import get_stage as gs
        from app.enums import StageType

        req = stages[0].requirement
        req.status = "paused"
        await notify_status_changed(db, req, stages, "被暂停")
        req.status = "in_progress"
        await notify_status_changed(db, req, stages, "被恢复")
        notes = await notifications_of(db, "status_changed")
        assert len(notes) == 2  # 不去重（design.md 4.1）
        assert all(n.dedupe_key is None for n in notes)

    async def test_recipients_include_assignees_distinct(self, db, pm_user, stages):
        from app.enums import StageType
        from tests.conftest import seed_user

        dev = await seed_user(db, "st_dev", "developer")
        get_stage(stages, StageType.RESEARCH).assignee_id = dev.id
        get_stage(stages, StageType.RELEASE).assignee_id = dev.id  # 同人去重
        await db.flush()
        req = stages[0].requirement
        count = await notify_status_changed(db, req, stages, "被暂停")
        assert count == 2  # PM + dev（重复指派不重复通知）
        notes = await notifications_of(db, "status_changed")
        assert {n.user_id for n in notes} == {pm_user.id, dev.id}

    async def test_no_recipients_returns_zero(self, db, pm_user, stages):
        pm_user.is_active = False
        req = stages[0].requirement
        assert await notify_status_changed(db, req, stages, "被暂停") == 0
