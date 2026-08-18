"""通知中心 API（design.md 8.7）与调度器装配。"""

from __future__ import annotations

from datetime import datetime

from app.models import Notification
from tests.conftest import auth_header, login_token, seed_user


async def seed_notifications(db, user_id: int, n: int) -> list[int]:
    ids = []
    for i in range(n):
        note = Notification(
            user_id=user_id,
            type="status_changed",
            title=f"通知{i}",
            content="-",
            is_read=(i == 0),  # 第一条已读
            created_at=datetime(2026, 8, 14, 10, i),
        )
        db.add(note)
        await db.flush()
        ids.append(note.id)
    return ids


class TestNotificationAPI:
    async def test_list_own_only(self, app_client, pm_user, db):
        other = await seed_user(db, "other_pm", "pm")
        await seed_notifications(db, pm_user.id, 2)
        await seed_notifications(db, other.id, 3)
        token = await login_token(app_client, "pm1")
        resp = await app_client.get(
            "/api/v1/notifications", headers=auth_header(token)
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 2
        assert all(i["title"].startswith("通知") for i in body["items"])
        assert body["items"][0]["created_at"] == "2026-08-14"

    async def test_unread_only_filter(self, app_client, pm_user, db):
        await seed_notifications(db, pm_user.id, 3)  # 1 已读 + 2 未读
        token = await login_token(app_client, "pm1")
        resp = await app_client.get(
            "/api/v1/notifications",
            params={"unread_only": "true"},
            headers=auth_header(token),
        )
        body = resp.json()
        assert body["total"] == 2
        assert all(not i["is_read"] for i in body["items"])

    async def test_pagination(self, app_client, pm_user, db):
        await seed_notifications(db, pm_user.id, 5)
        token = await login_token(app_client, "pm1")
        resp = await app_client.get(
            "/api/v1/notifications",
            params={"page": 2, "page_size": 2},
            headers=auth_header(token),
        )
        body = resp.json()
        assert body["total"] == 5
        assert len(body["items"]) == 2

    async def test_unread_count(self, app_client, pm_user, db):
        await seed_notifications(db, pm_user.id, 3)
        token = await login_token(app_client, "pm1")
        resp = await app_client.get(
            "/api/v1/notifications/unread-count", headers=auth_header(token)
        )
        assert resp.json() == {"unread": 2}

    async def test_mark_read(self, app_client, pm_user, db):
        ids = await seed_notifications(db, pm_user.id, 3)  # 1 已读 + 2 未读
        token = await login_token(app_client, "pm1")
        resp = await app_client.post(
            f"/api/v1/notifications/{ids[1]}/read", headers=auth_header(token)
        )
        assert resp.status_code == 204
        resp = await app_client.get(
            "/api/v1/notifications/unread-count", headers=auth_header(token)
        )
        assert resp.json() == {"unread": 1}

    async def test_mark_read_other_users_notification_403(
        self, app_client, pm_user, db
    ):
        other = await seed_user(db, "other_pm2", "pm")
        ids = await seed_notifications(db, other.id, 1)
        token = await login_token(app_client, "pm1")
        resp = await app_client.post(
            f"/api/v1/notifications/{ids[0]}/read", headers=auth_header(token)
        )
        assert resp.status_code == 403

    async def test_mark_read_nonexistent_404(self, app_client, pm_user):
        token = await login_token(app_client, "pm1")
        resp = await app_client.post(
            "/api/v1/notifications/999999/read", headers=auth_header(token)
        )
        assert resp.status_code == 404

    async def test_read_all(self, app_client, pm_user, db):
        await seed_notifications(db, pm_user.id, 3)
        other = await seed_user(db, "other_pm3", "pm")
        await seed_notifications(db, other.id, 2)
        token = await login_token(app_client, "pm1")
        resp = await app_client.post(
            "/api/v1/notifications/read-all", headers=auth_header(token)
        )
        assert resp.status_code == 204
        resp = await app_client.get(
            "/api/v1/notifications/unread-count", headers=auth_header(token)
        )
        assert resp.json() == {"unread": 0}
        # 他人通知不受影响（seed 2 条：1 已读 + 1 未读）
        token2 = await login_token(app_client, "other_pm3")
        resp = await app_client.get(
            "/api/v1/notifications/unread-count", headers=auth_header(token2)
        )
        assert resp.json() == {"unread": 1}


class TestStatusChangedIntegration:
    """M2 生命周期操作应产生 status_changed 通知（design.md 4.1）。"""

    async def test_pause_generates_notification(self, app_client, pm_user):
        from tests.test_api_requirements import create_body
        from tests.test_api_stages import make_requirement

        token = await login_token(app_client, "pm1")
        detail = await make_requirement(app_client, token)
        await app_client.post(
            f"/api/v1/requirements/{detail['id']}/pause", headers=auth_header(token)
        )
        resp = await app_client.get(
            "/api/v1/notifications", headers=auth_header(token)
        )
        assert resp.json()["total"] == 1
        note = resp.json()["items"][0]
        assert "被暂停" in note["title"]
        assert note["requirement_id"] == detail["id"]

    async def test_revert_generates_notification(
        self, app_client, pm_user, db
    ):
        from app.enums import StageType
        from tests.test_api_stages import advance, make_requirement, stage_of

        token = await login_token(app_client, "pm1")
        detail = await make_requirement(app_client, token)
        detail = await advance(app_client, token, detail, "research")
        review_id = stage_of(detail, "review")["id"]
        await app_client.post(
            f"/api/v1/stages/{review_id}/start", headers=auth_header(token)
        )
        await app_client.post(
            f"/api/v1/stages/{review_id}/revert",
            json={
                "reason": "不通过",
                "target_stage_id": stage_of(detail, "research")["id"],
            },
            headers=auth_header(token),
        )
        resp = await app_client.get(
            "/api/v1/notifications", headers=auth_header(token)
        )
        assert resp.json()["total"] == 1
        assert "被回退" in resp.json()["items"][0]["title"]


class TestScheduler:
    async def test_create_scheduler_registers_job(self):
        from apscheduler.triggers.interval import IntervalTrigger

        from app.scheduler import JOB_ID, SCAN_INTERVAL_MINUTES, create_scheduler

        scheduler = create_scheduler(lambda: None)
        job = scheduler.get_job(JOB_ID)
        assert job is not None
        assert job.max_instances == 1
        assert job.coalesce is True
        trigger = job.trigger
        assert isinstance(trigger, IntervalTrigger)
        assert trigger.interval.total_seconds() == SCAN_INTERVAL_MINUTES * 60

    async def test_scan_job_runs_scan_and_commits(self, monkeypatch):
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
        from sqlalchemy.pool import StaticPool

        from app.db import Base
        import app.scheduler as sched_mod
        from app.services import notifications as notify_mod

        # 独立内存库（job 内 async with 会关闭会话，不能复用测试 fixture 会话）
        engine = create_async_engine(
            "sqlite+aiosqlite://",
            poolclass=StaticPool,
            connect_args={"check_same_thread": False},
        )
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)

        scheduler = sched_mod.create_scheduler(factory)
        job = scheduler.get_job("pm_notification_scan")
        calls = []
        committed = []

        async def fake_scan(session, now=None):
            calls.append(session)
            return notify_mod.ScanReport()

        monkeypatch.setattr(sched_mod, "run_scan", fake_scan)

        original_commit = factory().commit

        async def spy_commit(self_inner):
            committed.append(True)
            await original_commit()

        from sqlalchemy.ext.asyncio import AsyncSession

        monkeypatch.setattr(AsyncSession, "commit", spy_commit)
        try:
            await job.func()
        finally:
            await engine.dispose()
        assert len(calls) == 1
        assert committed
