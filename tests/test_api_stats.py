"""统计 API（design.md 6.1 / 6.2 / 6.3 口径）。"""

from __future__ import annotations

from datetime import datetime

from app.enums import STAGE_SEQ, StageStatus, StageType
from app.models import (
    Project,
    Requirement,
    RequirementStage,
    RequirementStatusLog,
    StageTimeChangeLog,
)
from tests.conftest import auth_header, login_token

# 统计周期：2026-08-10（周一）~ 2026-08-17
WEEK_START = datetime(2026, 8, 10, 0, 0, 0)
WEEK_END = datetime(2026, 8, 17, 0, 0, 0)
NOW = datetime(2026, 8, 14, 10, 0, 0)  # 周五


async def seed_req(db, pm_id, *, title, status="not_started", created_at, project_id=None, **kw):
    req = Requirement(
        title=title,
        responsible_pm_id=pm_id,
        status=status,
        project_id=project_id,
        created_at=created_at,
        **kw,
    )
    db.add(req)
    await db.flush()
    stages = []
    for st, seq in STAGE_SEQ.items():
        s = RequirementStage(
            requirement_id=req.id,
            stage_type=st.value,
            seq=seq,
            status=StageStatus.NOT_STARTED.value,
        )
        db.add(s)
        stages.append(s)
    await db.flush()
    return req, stages


def set_stage(stages, st_type, **kw):
    s = next(x for x in stages if x.stage_type == st_type.value)
    for k, v in kw.items():
        setattr(s, k, v)
    return s


async def seed_stats_data(db, pm_user):
    """周期内：新增 3、完成 1、新产生延期 2（其一当日反复进出延期，去重后 1）。"""
    # A：周期内创建，进行中（backend_dev 在途）
    req_a, st_a = seed_req_sync = await seed_req(
        db, pm_user.id, title="A-进行中", status="in_progress",
        created_at=datetime(2026, 8, 11, 9, 0),
    )
    set_stage(st_a, StageType.RESEARCH, status="done",
              actual_start=datetime(2026, 8, 11, 9, 0), actual_end=datetime(2026, 8, 11, 18, 0))
    set_stage(st_a, StageType.REVIEW, status="done",
              actual_start=datetime(2026, 8, 12, 9, 0), actual_end=datetime(2026, 8, 12, 18, 0))
    set_stage(st_a, StageType.BACKEND_DEV, status="in_progress",
              actual_start=datetime(2026, 8, 13, 9, 0),
              planned_start=datetime(2026, 8, 13, 9, 0), planned_end=datetime(2026, 8, 16, 18, 0))

    # B：周期内完成（release actual_end 在周期内）
    req_b, st_b = await seed_req(
        db, pm_user.id, title="B-已完成", status="done",
        created_at=datetime(2026, 7, 20, 9, 0),
    )
    for st in StageType:
        set_stage(st_b, st, status="done")
    set_stage(st_b, StageType.RELEASE, actual_end=datetime(2026, 8, 13, 20, 0))

    # C：周期前创建，当前延期（research 排期已过，未启动）
    req_c, st_c = await seed_req(
        db, pm_user.id, title="C-逾期延期", status="delayed",
        created_at=datetime(2026, 7, 1, 9, 0),
    )
    set_stage(st_c, StageType.RESEARCH,
              planned_start=datetime(2026, 8, 5, 9, 0), planned_end=datetime(2026, 8, 8, 18, 0),
              last_delay_reason="调研资源未到位")
    db.add(RequirementStatusLog(requirement_id=req_c.id, from_status="not_started",
                                to_status="delayed", created_at=datetime(2026, 8, 12, 8, 0)))
    db.add(RequirementStatusLog(requirement_id=req_c.id, from_status="in_progress",
                                to_status="delayed", created_at=datetime(2026, 8, 12, 18, 0)))  # 同日反复，去重

    # D：周期内创建，未开始（无排期）
    await seed_req(db, pm_user.id, title="D-未开始", created_at=datetime(2026, 8, 13, 10, 0))

    # E：人工标记延期（周期内进入延期）
    req_e, st_e = await seed_req(
        db, pm_user.id, title="E-人工延期", status="delayed",
        created_at=datetime(2026, 8, 12, 9, 0), manual_delayed=True,
        manual_delay_reason="上线窗口风险",
    )
    db.add(RequirementStatusLog(requirement_id=req_e.id, from_status="not_started",
                                to_status="delayed", created_at=datetime(2026, 8, 13, 9, 0),
                                changed_by=pm_user.id))

    # 改期记录：3 次顺延（"依赖接口方联调延迟"×2 → Top1）+ 1 次提前 + 1 次系统顺延（排除）
    db.add(StageTimeChangeLog(
        stage_id=st_a[2].id, changed_by=pm_user.id, field="planned_end",
        old_value=datetime(2026, 8, 15, 18, 0), new_value=datetime(2026, 8, 16, 18, 0),
        reason="依赖接口方联调延迟", created_at=datetime(2026, 8, 12, 10, 0)))
    db.add(StageTimeChangeLog(
        stage_id=st_a[3].id, changed_by=pm_user.id, field="planned_end",
        old_value=datetime(2026, 8, 20, 18, 0), new_value=datetime(2026, 8, 22, 18, 0),
        reason="依赖接口方联调延迟", created_at=datetime(2026, 8, 12, 10, 30)))
    db.add(StageTimeChangeLog(
        stage_id=st_c[0].id, changed_by=pm_user.id, field="planned_end",
        old_value=datetime(2026, 8, 7, 18, 0), new_value=datetime(2026, 8, 8, 18, 0),
        reason="调研资源未到位", created_at=datetime(2026, 8, 11, 10, 0)))
    db.add(StageTimeChangeLog(
        stage_id=st_a[2].id, changed_by=pm_user.id, field="planned_start",
        old_value=datetime(2026, 8, 14, 9, 0), new_value=datetime(2026, 8, 13, 9, 0),
        reason="提前启动", created_at=datetime(2026, 8, 11, 11, 0)))
    db.add(StageTimeChangeLog(
        stage_id=st_e[0].id, changed_by=pm_user.id, field="planned_start",
        old_value=datetime(2026, 8, 17, 9, 0), new_value=datetime(2026, 8, 21, 9, 0),
        reason="需求暂停顺延", auto_generated=True, created_at=datetime(2026, 8, 12, 12, 0)))

    await db.flush()
    return {"A": req_a, "B": req_b, "C": req_c, "E": req_e}


class TestOverview:
    async def test_overview_distributions_and_delayed_list(
        self, app_client, pm_user, db
    ):
        await seed_stats_data(db, pm_user)
        await db.commit()
        token = await login_token(app_client, "pm1")
        resp = await app_client.get("/api/v1/stats/overview", headers=auth_header(token))
        assert resp.status_code == 200
        body = resp.json()

        # A 进行中 / B 完成 / C、E 延期 / D 未开始
        assert body["status_distribution"] == {
            "not_started": 1, "in_progress": 1, "delayed": 2, "paused": 0, "done": 1,
        }
        # 在途环节：A=backend_dev；B 全部完成不计；C、D、E 下一个待开始均为 research
        assert body["stage_distribution"]["backend_dev"] == 1
        assert body["stage_distribution"]["research"] == 3

        delayed = {d["title"]: d for d in body["delayed_list"]}
        assert set(delayed) == {"C-逾期延期", "E-人工延期"}
        c = delayed["C-逾期延期"]
        assert c["overdue_stages"][0]["stage_type"] == "research"
        # 逾期天数按真实当前时间计算（8/8 之后），随运行日动态断言
        from datetime import date as _date

        expected_days = (_date.today() - _date(2026, 8, 8)).days
        assert c["overdue_stages"][0]["overdue_days"] == expected_days
        assert c["overdue_stages"][0]["last_delay_reason"] == "调研资源未到位"
        assert delayed["E-人工延期"]["manual_delayed"] is True
        assert delayed["E-人工延期"]["manual_delay_reason"] == "上线窗口风险"


class TestRequirementWeekly:
    async def test_weekly_report_metrics(self, app_client, pm_user, db):
        await seed_stats_data(db, pm_user)
        await db.commit()
        token = await login_token(app_client, "pm1")
        resp = await app_client.get(
            "/api/v1/stats/requirements/weekly",
            params={"date": "2026-08-12"},
            headers=auth_header(token),
        )
        assert resp.status_code == 200
        body = resp.json()

        assert body["period_start"].startswith("2026-08-10")
        assert body["period_end"].startswith("2026-08-17")
        assert body["new_count"] == 3  # A、D、E 周内创建
        assert body["completed_count"] == 1  # B 上线于 8/13
        assert body["new_delayed_count"] == 2  # C、E（C 同日反复去重为 1）
        assert body["current_delayed_count"] == 2
        assert body["unfinished_count"] == 4  # A、C、D、E
        assert body["delay_rate"] == 0.5

        assert body["postponed_count"] == 3
        assert body["advanced_count"] == 1
        assert body["top_delay_reasons"][0] == {
            "reason": "依赖接口方联调延迟", "count": 2
        }
        assert {r["reason"] for r in body["top_delay_reasons"]} == {
            "依赖接口方联调延迟", "调研资源未到位"
        }

    async def test_weekly_empty_data(self, app_client, pm_user, db):
        token = await login_token(app_client, "pm1")
        resp = await app_client.get(
            "/api/v1/stats/requirements/weekly",
            params={"date": "2026-08-12"},
            headers=auth_header(token),
        )
        body = resp.json()
        assert body["new_count"] == 0
        assert body["delay_rate"] == 0.0  # 未完成总数为 0 → 延期率 0
        assert body["top_delay_reasons"] == []

    async def test_invalid_month_422(self, app_client, pm_user):
        token = await login_token(app_client, "pm1")
        resp = await app_client.get(
            "/api/v1/stats/requirements/monthly",
            params={"month": "2026-13"},
            headers=auth_header(token),
        )
        assert resp.status_code == 422


class TestRequirementMonthly:
    async def test_monthly_with_trend(self, app_client, pm_user, db):
        await seed_stats_data(db, pm_user)
        await db.commit()
        token = await login_token(app_client, "pm1")
        resp = await app_client.get(
            "/api/v1/stats/requirements/monthly",
            params={"month": "2026-08"},
            headers=auth_header(token),
        )
        body = resp.json()
        assert body["period_start"].startswith("2026-08-01")
        assert body["period_end"].startswith("2026-09-01")
        # 自然周对齐：7/27、8/3、8/10、8/17、8/24、8/31 共 6 个分桶（跨月边界）
        assert len(body["weekly_trend"]) == 6
        # 8/10 那一周承载了全部造数
        week2 = next(w for w in body["weekly_trend"] if w["week_start"].startswith("2026-08-10"))
        assert week2["week_start"].startswith("2026-08-10")
        assert week2["new_count"] == 3
        assert week2["completed_count"] == 1
        assert week2["new_delayed_count"] == 2


class TestProjectsReport:
    async def test_projects_weekly(self, app_client, pm_user, db):
        ids = await seed_stats_data(db, pm_user)
        project = Project(name="统计项目", status="in_progress", owner_id=pm_user.id)
        db.add(project)
        await db.flush()
        for key in ("A", "C"):
            r = await db.get(Requirement, ids[key].id)
            r.project_id = project.id
        other = Project(name="未启动项目", status="not_started", owner_id=pm_user.id)
        db.add(other)
        await db.commit()

        token = await login_token(app_client, "pm1")
        resp = await app_client.get(
            "/api/v1/stats/projects/weekly",
            params={"date": "2026-08-12"},
            headers=auth_header(token),
        )
        body = resp.json()
        # 默认只看进行中项目
        assert [p["name"] for p in body["projects"]] == ["统计项目"]
        p = body["projects"][0]
        assert p["total_requirements"] == 2
        assert p["done_count"] == 0
        assert p["completed_in_period"] == 0
        assert p["delayed_requirements"][0]["requirement_id"] == ids["C"].id
        assert p["delayed_requirements"][0]["latest_delay_reason"] == "调研资源未到位"

        # status=all 拿到两个项目；owner 筛选
        resp = await app_client.get(
            "/api/v1/stats/projects/weekly",
            params={"date": "2026-08-12", "status": "all"},
            headers=auth_header(token),
        )
        assert len(resp.json()["projects"]) == 2
        resp = await app_client.get(
            "/api/v1/stats/projects/weekly",
            params={"date": "2026-08-12", "status": "all", "owner_id": 99999},
            headers=auth_header(token),
        )
        assert resp.json()["projects"] == []


class TestStatusLogIntegration:
    async def test_lifecycle_writes_status_logs(self, app_client, pm_user, db):
        from tests.test_api_requirements import create_body
        from tests.test_api_stages import make_requirement, stage_of

        token = await login_token(app_client, "pm1")
        detail = await make_requirement(app_client, token)
        rid = detail["id"]
        sid = stage_of(detail, "research")["id"]

        # start → not_started → in_progress
        await app_client.post(f"/api/v1/stages/{sid}/start", headers=auth_header(token))
        # 人工标记延期 → in_progress → delayed
        await app_client.post(
            f"/api/v1/requirements/{rid}/mark-delayed",
            json={"reason": "风险"},
            headers=auth_header(token),
        )
        await db.commit()
        from sqlalchemy import select

        logs = list(
            (
                await db.scalars(
                    select(RequirementStatusLog).where(
                        RequirementStatusLog.requirement_id == rid
                    )
                )
            ).all()
        )
        transitions = [(l.from_status, l.to_status, l.changed_by) for l in logs]
        assert ("not_started", "in_progress", pm_user.id) in transitions
        assert ("in_progress", "delayed", pm_user.id) in transitions

    async def test_scan_refresh_writes_system_log(self, db, pm_user):
        from app.services.notifications import run_scan

        req, stages = await seed_req(
            db, pm_user.id, title="扫描延期", created_at=datetime(2026, 1, 1, 9, 0)
        )
        research = next(s for s in stages if s.stage_type == "research")
        research.planned_end = datetime(2026, 1, 3, 18, 0)
        await db.flush()

        await run_scan(db, NOW)

        from sqlalchemy import select

        logs = list(
            (
                await db.scalars(
                    select(RequirementStatusLog).where(
                        RequirementStatusLog.requirement_id == req.id
                    )
                )
            ).all()
        )
        assert [(l.from_status, l.to_status, l.changed_by) for l in logs] == [
            ("not_started", "delayed", None)
        ]
