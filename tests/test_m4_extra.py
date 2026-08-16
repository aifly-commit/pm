"""M4 迭代 2 收尾：补齐项目/统计剩余分支。"""

from __future__ import annotations

from datetime import datetime

from tests.conftest import auth_header, login_token, seed_user
from tests.test_api_projects import make_project


class TestProjectExtraBranches:
    async def test_update_all_remaining_fields(self, app_client, pm_user):
        token = await login_token(app_client, "pm1")
        project = await make_project(app_client, token)
        resp = await app_client.patch(
            f"/api/v1/projects/{project['id']}",
            json={
                "name": "全字段更新",
                "description": "新描述",
                "planned_start": "2026-09-01",
                "planned_end": "2026-12-31",
                "actual_start": "2026-09-02",
                "actual_end": "2026-12-20",
            },
            headers=auth_header(token),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["name"] == "全字段更新"
        assert body["description"] == "新描述"
        assert body["planned_start"] == "2026-09-01"
        assert body["planned_end"] == "2026-12-31"
        assert body["actual_start"] == "2026-09-02"
        assert body["actual_end"] == "2026-12-20"

    async def test_admin_transfer_owner(self, app_client, admin_user, pm_user, db):
        other = await seed_user(db, "pm_owner2", "pm")
        t_admin = await login_token(app_client, "admin1")
        t_pm = await login_token(app_client, "pm1")
        project = await make_project(app_client, t_pm)
        resp = await app_client.patch(
            f"/api/v1/projects/{project['id']}",
            json={"owner_id": other.id},
            headers=auth_header(t_admin),
        )
        assert resp.status_code == 200
        assert resp.json()["owner_id"] == other.id

    async def test_create_with_nonexistent_owner_404(self, app_client, admin_user):
        t_admin = await login_token(app_client, "admin1")
        resp = await app_client.post(
            "/api/v1/projects",
            json={"name": "X", "owner_id": 888888},
            headers=auth_header(t_admin),
        )
        assert resp.status_code == 404

    async def test_patch_nonexistent_owner_404(self, app_client, admin_user, pm_user):
        t_admin = await login_token(app_client, "admin1")
        t_pm = await login_token(app_client, "pm1")
        project = await make_project(app_client, t_pm)
        resp = await app_client.patch(
            f"/api/v1/projects/{project['id']}",
            json={"owner_id": 777777},
            headers=auth_header(t_admin),
        )
        assert resp.status_code == 404

    async def test_developer_cannot_patch_or_delete_403(self, app_client, pm_user, db):
        await seed_user(db, "m4_dev", "developer")
        t_pm = await login_token(app_client, "pm1")
        t_dev = await login_token(app_client, "m4_dev")
        project = await make_project(app_client, t_pm)
        assert (
            await app_client.patch(
                f"/api/v1/projects/{project['id']}",
                json={"name": "改名"},
                headers=auth_header(t_dev),
            )
        ).status_code == 403
        assert (
            await app_client.delete(
                f"/api/v1/projects/{project['id']}", headers=auth_header(t_dev)
            )
        ).status_code == 403

    async def test_detach_nonexistent_requirement_404(self, app_client, pm_user):
        token = await login_token(app_client, "pm1")
        project = await make_project(app_client, token)
        resp = await app_client.delete(
            f"/api/v1/projects/{project['id']}/requirements/666666",
            headers=auth_header(token),
        )
        assert resp.status_code == 404


class TestStatsExtraBranches:
    async def test_projects_monthly_december_boundary(self, app_client, pm_user):
        """12 月跨年边界（month_bounds 12 分支）+ monthly 端点。"""
        token = await login_token(app_client, "pm1")
        resp = await app_client.get(
            "/api/v1/stats/projects/monthly",
            params={"month": "2026-12", "status": "all"},
            headers=auth_header(token),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["period_start"].startswith("2026-12-01")
        assert body["period_end"].startswith("2027-01-01")

    async def test_projects_weekly_owner_filter_and_manual_reason(
        self, app_client, pm_user, db
    ):
        from app.enums import STAGE_SEQ, StageStatus
        from app.models import Project, Requirement, RequirementStage

        project = Project(name="人工延期项目", status="in_progress", owner_id=pm_user.id)
        db.add(project)
        await db.flush()
        req = Requirement(
            title="人工延期需求",
            responsible_pm_id=pm_user.id,
            project_id=project.id,
            status="delayed",
            manual_delayed=True,
            manual_delay_reason="窗口风险",
        )
        db.add(req)
        await db.flush()
        db.add_all(
            RequirementStage(
                requirement_id=req.id,
                stage_type=st.value,
                seq=seq,
                status=StageStatus.NOT_STARTED.value,
            )
            for st, seq in STAGE_SEQ.items()
        )
        await db.commit()

        token = await login_token(app_client, "pm1")
        resp = await app_client.get(
            "/api/v1/stats/projects/weekly",
            params={"status": "all", "owner_id": pm_user.id},
            headers=auth_header(token),
        )
        body = resp.json()
        assert len(body["projects"]) == 1
        p = body["projects"][0]
        # 无逾期环节（未排期）→ 取人工延期原因
        assert p["delayed_requirements"][0]["latest_delay_reason"] == "窗口风险"
        assert p["delayed_requirements"][0]["overdue_stages"] == []
