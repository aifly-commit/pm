"""异常分支与边界场景回归测试。"""

from __future__ import annotations

from datetime import date

from app.schemas import RequirementUpdate, StagePlanItem
from tests.conftest import auth_header, login_token, seed_user
from tests.test_api_projects import make_project, make_requirement_id
from tests.test_api_requirements import create_body


class TestSchemaBoundaryValues:
    def test_date_object_and_empty_optional_enums_are_normalized(self):
        """日期对象和可选枚举空值均应按统一口径处理。"""
        stage = StagePlanItem(
            stage_type="research",
            planned_start=date(2030, 1, 2),
            planned_end=date(2030, 1, 3),
        )
        assert stage.planned_start.isoformat() == "2030-01-02T00:00:00"
        assert stage.planned_end.isoformat() == "2030-01-03T23:59:59"

        update = RequirementUpdate(product_line="", category="")
        assert update.product_line is None
        assert update.category is None


class TestRequirementFailureAndAuditEdges:
    async def test_developer_cannot_import_requirements(self, app_client, pm_user, db):
        await seed_user(db, "coverage_dev", "developer")
        token = await login_token(app_client, "coverage_dev")
        resp = await app_client.post(
            "/api/v1/requirements/import",
            json={"items": [create_body(title="无权限导入")]},
            headers=auth_header(token),
        )
        assert resp.status_code == 403

    async def test_set_status_for_missing_requirement_returns_404(self, app_client, pm_user):
        token = await login_token(app_client, "pm1")
        resp = await app_client.patch(
            "/api/v1/requirements/999999/status",
            json={"status": "in_progress"},
            headers=auth_header(token),
        )
        assert resp.status_code == 404

    async def test_first_stage_date_change_records_empty_previous_value(self, app_client, pm_user):
        token = await login_token(app_client, "pm1")
        created = await app_client.post(
            "/api/v1/requirements",
            json=create_body(
                title="首次排期留痕",
                stages=[{"stage_type": "release", "planned_end": "2030-02-10"}],
            ),
            headers=auth_header(token),
        )
        assert created.status_code == 201, created.text
        requirement_id = created.json()["id"]
        detail = await app_client.get(
            f"/api/v1/requirements/{requirement_id}", headers=auth_header(token)
        )
        research_id = next(
            stage["id"] for stage in detail.json()["stages"] if stage["stage_type"] == "research"
        )
        changed = await app_client.patch(
            f"/api/v1/stages/{research_id}/plan",
            json={"planned_start": "2030-01-01", "reason": "补充首轮计划"},
            headers=auth_header(token),
        )
        assert changed.status_code == 200, changed.text
        detail = await app_client.get(
            f"/api/v1/requirements/{requirement_id}", headers=auth_header(token)
        )
        log = next(log for log in detail.json()["modification_logs"] if log["change_type"] == "stage_time")
        assert log["old_value"] is None
        assert log["new_value"] == "2030-01-01"

    async def test_null_title_is_rejected_and_unchanged_value_is_safe(self, app_client, pm_user):
        token = await login_token(app_client, "pm1")
        created = await app_client.post(
            "/api/v1/requirements", json=create_body(priority="P1"), headers=auth_header(token)
        )
        requirement_id = created.json()["id"]

        rejected = await app_client.patch(
            f"/api/v1/requirements/{requirement_id}",
            json={"title": None},
            headers=auth_header(token),
        )
        assert rejected.status_code == 422

        unchanged = await app_client.patch(
            f"/api/v1/requirements/{requirement_id}",
            json={"priority": "P1"},
            headers=auth_header(token),
        )
        assert unchanged.status_code == 200
        assert unchanged.json()["priority"] == "P1"


class TestProjectAndStatusEdges:
    async def test_only_owner_or_admin_can_detach_requirement(self, app_client, pm_user, db):
        await seed_user(db, "coverage_pm2", "pm")
        owner_token = await login_token(app_client, "pm1")
        other_token = await login_token(app_client, "coverage_pm2")
        project = await make_project(app_client, owner_token)
        requirement_id = await make_requirement_id(app_client, owner_token)
        attached = await app_client.post(
            f"/api/v1/projects/{project['id']}/requirements",
            json={"requirement_id": requirement_id},
            headers=auth_header(owner_token),
        )
        assert attached.status_code == 200

        response = await app_client.delete(
            f"/api/v1/projects/{project['id']}/requirements/{requirement_id}",
            headers=auth_header(other_token),
        )
        assert response.status_code == 403

    async def test_real_pause_remains_paused_when_recalculated(self, requirement, stages):
        from tests.helpers import NOW
        from app.services.state_machine import recalc_status

        requirement.paused_at = NOW
        requirement.status = "in_progress"
        assert recalc_status(requirement, stages, NOW) == "paused"
