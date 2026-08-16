"""需求 API（design.md 8.2）。"""

from __future__ import annotations

from tests.conftest import DEFAULT_PASSWORD, auth_header, login_token, seed_user

# 统一排期（远未来，避免真实时钟干扰）
def _sh(day: int, hm: str = "18:00:00") -> str:
    return f"2030-01-{day:02d}T{hm}+08:00"


PLANS = [
    {"stage_type": "research", "planned_start": _sh(1, "09:00:00"), "planned_end": _sh(3)},
    {"stage_type": "review", "planned_start": _sh(3), "planned_end": _sh(5)},
    {"stage_type": "backend_dev", "planned_start": _sh(5), "planned_end": _sh(10)},
    {"stage_type": "frontend_dev", "planned_start": _sh(10), "planned_end": _sh(15)},
    {"stage_type": "api_dev", "planned_start": _sh(10), "planned_end": _sh(14)},
    {"stage_type": "testing", "planned_start": _sh(15), "planned_end": _sh(20)},
    {"stage_type": "release", "planned_start": _sh(20), "planned_end": _sh(20, "20:00:00")},
]


def create_body(**overrides) -> dict:
    body = {"title": "新需求", "priority": "P1", "stages": PLANS}
    body.update(overrides)
    return body


class TestCreateRequirement:
    async def test_create_generates_seven_stages(self, app_client, pm_user):
        token = await login_token(app_client, "pm1")
        resp = await app_client.post(
            "/api/v1/requirements", json=create_body(), headers=auth_header(token)
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["status"] == "not_started"
        assert body["current_stage"] == "需求调研"

        detail = (
            await app_client.get(
                f"/api/v1/requirements/{body['id']}", headers=auth_header(token)
            )
        ).json()
        assert [s["seq"] for s in detail["stages"]] == [1, 2, 3, 4, 5, 6, 7]
        assert detail["stages"][0]["planned_start"] == "2030-01-01T09:00:00+08:00"

    async def test_create_without_plans_ok(self, app_client, pm_user):
        token = await login_token(app_client, "pm1")
        resp = await app_client.post(
            "/api/v1/requirements",
            json={"title": "空排期需求"},
            headers=auth_header(token),
        )
        assert resp.status_code == 201
        detail = (
            await app_client.get(
                f"/api/v1/requirements/{resp.json()['id']}", headers=auth_header(token)
            )
        ).json()
        assert all(s["planned_start"] is None for s in detail["stages"])

    async def test_create_with_invalid_times_409(self, app_client, pm_user):
        token = await login_token(app_client, "pm1")
        bad = [dict(p) for p in PLANS]
        bad[0]["planned_end"] = "2029-12-30T18:00:00+08:00"  # 早于开始时间
        resp = await app_client.post(
            "/api/v1/requirements",
            json=create_body(stages=bad),
            headers=auth_header(token),
        )
        assert resp.status_code == 409
        assert "预计结束时间不得早于预计开始时间" in resp.json()["detail"]

    async def test_create_with_prereq_conflict_409(self, app_client, pm_user):
        token = await login_token(app_client, "pm1")
        bad = [dict(p) for p in PLANS]
        # review 开始早于 research 结束
        bad[1]["planned_start"] = "2030-01-02T09:00:00+08:00"
        resp = await app_client.post(
            "/api/v1/requirements",
            json=create_body(stages=bad),
            headers=auth_header(token),
        )
        assert resp.status_code == 409
        assert "前置环节" in resp.json()["detail"]

    async def test_create_invalid_stage_type_422(self, app_client, pm_user):
        token = await login_token(app_client, "pm1")
        resp = await app_client.post(
            "/api/v1/requirements",
            json=create_body(stages=[{"stage_type": "deploy", "planned_start": None, "planned_end": None}]),
            headers=auth_header(token),
        )
        assert resp.status_code == 422

    async def test_create_invalid_priority_422(self, app_client, pm_user):
        token = await login_token(app_client, "pm1")
        resp = await app_client.post(
            "/api/v1/requirements",
            json=create_body(priority="P9"),
            headers=auth_header(token),
        )
        assert resp.status_code == 422

    async def test_developer_cannot_create_403(self, app_client, db):
        await seed_user(db, "dev1", "developer")
        token = await login_token(app_client, "dev1")
        resp = await app_client.post(
            "/api/v1/requirements", json=create_body(), headers=auth_header(token)
        )
        assert resp.status_code == 403

    async def test_admin_can_create_for_other_pm(self, app_client, admin_user, pm_user):
        token = await login_token(app_client, "admin1")
        resp = await app_client.post(
            "/api/v1/requirements",
            json=create_body(responsible_pm_id=pm_user.id),
            headers=auth_header(token),
        )
        assert resp.status_code == 201
        assert resp.json()["responsible_pm_id"] == pm_user.id

    async def test_pm_cannot_assign_other_pm_403(self, app_client, db, pm_user):
        other = await seed_user(db, "pm2", "pm")
        token = await login_token(app_client, "pm1")
        resp = await app_client.post(
            "/api/v1/requirements",
            json=create_body(responsible_pm_id=other.id),
            headers=auth_header(token),
        )
        assert resp.status_code == 403

    async def test_create_with_nonexistent_project_404(self, app_client, pm_user):
        token = await login_token(app_client, "pm1")
        resp = await app_client.post(
            "/api/v1/requirements",
            json=create_body(project_id=99999),
            headers=auth_header(token),
        )
        assert resp.status_code == 404

    async def test_create_assigns_stage_assignees(self, app_client, pm_user, db):
        dev = await seed_user(db, "dev2", "developer")
        token = await login_token(app_client, "pm1")
        plans = [dict(p) for p in PLANS]
        plans[2]["assignee_id"] = dev.id
        resp = await app_client.post(
            "/api/v1/requirements",
            json=create_body(stages=plans),
            headers=auth_header(token),
        )
        detail = (
            await app_client.get(
                f"/api/v1/requirements/{resp.json()['id']}", headers=auth_header(token)
            )
        ).json()
        backend = next(s for s in detail["stages"] if s["stage_type"] == "backend_dev")
        assert backend["assignee_id"] == dev.id


class TestListRequirements:
    async def _create(self, app_client, token, title="需求A") -> int:
        resp = await app_client.post(
            "/api/v1/requirements", json=create_body(title=title), headers=auth_header(token)
        )
        return resp.json()["id"]

    async def test_list_with_pagination_and_filters(
        self, app_client, pm_user, db
    ):
        other = await seed_user(db, "pm2", "pm")
        t1 = await login_token(app_client, "pm1")
        t2 = await login_token(app_client, "pm2")
        await self._create(app_client, t1, "登录改造")
        await self._create(app_client, t1, "报表优化")
        await self._create(app_client, t2, "对方需求")

        resp = await app_client.get(
            "/api/v1/requirements", headers=auth_header(t1)
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 3
        assert len(body["items"]) == 3
        assert all(item["current_stage"] == "需求调研" for item in body["items"])

        # keyword 筛选
        resp = await app_client.get(
            "/api/v1/requirements", params={"keyword": "报表"}, headers=auth_header(t1)
        )
        assert resp.json()["total"] == 1

        # pm_id 筛选
        resp = await app_client.get(
            "/api/v1/requirements", params={"pm_id": other.id}, headers=auth_header(t1)
        )
        assert resp.json()["total"] == 1
        assert resp.json()["items"][0]["title"] == "对方需求"

        # 分页
        resp = await app_client.get(
            "/api/v1/requirements", params={"page": 2, "page_size": 2}, headers=auth_header(t1)
        )
        assert len(resp.json()["items"]) == 1

    async def test_list_filter_by_stage_type_matches_next_to_start(
        self, app_client, pm_user
    ):
        token = await login_token(app_client, "pm1")
        await self._create(app_client, token)
        # 未开始需求：当前环节=下一个待开始（research）
        resp = await app_client.get(
            "/api/v1/requirements", params={"stage_type": "research"}, headers=auth_header(token)
        )
        assert resp.json()["total"] == 1
        resp = await app_client.get(
            "/api/v1/requirements", params={"stage_type": "testing"}, headers=auth_header(token)
        )
        assert resp.json()["total"] == 0

    async def test_list_filter_by_status(self, app_client, pm_user):
        token = await login_token(app_client, "pm1")
        await self._create(app_client, token)
        resp = await app_client.get(
            "/api/v1/requirements", params={"status": "not_started"}, headers=auth_header(token)
        )
        assert resp.json()["total"] == 1
        resp = await app_client.get(
            "/api/v1/requirements", params={"status": "done"}, headers=auth_header(token)
        )
        assert resp.json()["total"] == 0


class TestGetAndUpdateRequirement:
    async def test_detail_includes_logs(self, app_client, pm_user):
        token = await login_token(app_client, "pm1")
        rid = (
            await app_client.post(
                "/api/v1/requirements", json=create_body(), headers=auth_header(token)
            )
        ).json()["id"]
        resp = await app_client.get(
            f"/api/v1/requirements/{rid}", headers=auth_header(token)
        )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["stages"]) == 7
        assert body["change_logs"] == []
        assert body["revert_logs"] == []
        assert body["current_stage"] == "需求调研"

    async def test_detail_nonexistent_404(self, app_client, pm_user):
        token = await login_token(app_client, "pm1")
        resp = await app_client.get(
            "/api/v1/requirements/424242", headers=auth_header(token)
        )
        assert resp.status_code == 404

    async def test_patch_fields_as_owner(self, app_client, pm_user):
        token = await login_token(app_client, "pm1")
        rid = (
            await app_client.post(
                "/api/v1/requirements", json=create_body(), headers=auth_header(token)
            )
        ).json()["id"]
        resp = await app_client.patch(
            f"/api/v1/requirements/{rid}",
            json={"title": "改标题", "priority": "P0"},
            headers=auth_header(token),
        )
        assert resp.status_code == 200
        assert resp.json()["title"] == "改标题"
        assert resp.json()["priority"] == "P0"

    async def test_patch_by_other_pm_403(self, app_client, pm_user, db):
        await seed_user(db, "pm2", "pm")
        t1 = await login_token(app_client, "pm1")
        t2 = await login_token(app_client, "pm2")
        rid = (
            await app_client.post(
                "/api/v1/requirements", json=create_body(), headers=auth_header(t1)
            )
        ).json()["id"]
        resp = await app_client.patch(
            f"/api/v1/requirements/{rid}", json={"title": "抢改"}, headers=auth_header(t2)
        )
        assert resp.status_code == 403

    async def test_patch_by_admin_ok(self, app_client, admin_user, pm_user):
        t_admin = await login_token(app_client, "admin1")
        t_pm = await login_token(app_client, "pm1")
        rid = (
            await app_client.post(
                "/api/v1/requirements", json=create_body(), headers=auth_header(t_pm)
            )
        ).json()["id"]
        resp = await app_client.patch(
            f"/api/v1/requirements/{rid}", json={"priority": "P3"}, headers=auth_header(t_admin)
        )
        assert resp.status_code == 200
        assert resp.json()["priority"] == "P3"

    async def test_patch_stage_assignees(self, app_client, pm_user, db):
        dev = await seed_user(db, "dev3", "developer")
        token = await login_token(app_client, "pm1")
        rid = (
            await app_client.post(
                "/api/v1/requirements", json=create_body(), headers=auth_header(token)
            )
        ).json()["id"]
        detail = (
            await app_client.get(
                f"/api/v1/requirements/{rid}", headers=auth_header(token)
            )
        ).json()
        stage_id = detail["stages"][0]["id"]
        resp = await app_client.patch(
            f"/api/v1/requirements/{rid}",
            json={"stage_assignees": [{"stage_id": stage_id, "assignee_id": dev.id}]},
            headers=auth_header(token),
        )
        assert resp.status_code == 200
        assert resp.json()["stages"][0]["assignee_id"] == dev.id

    async def test_patch_stage_from_other_requirement_404(self, app_client, pm_user):
        token = await login_token(app_client, "pm1")
        rid = (
            await app_client.post(
                "/api/v1/requirements", json=create_body(), headers=auth_header(token)
            )
        ).json()["id"]
        resp = await app_client.patch(
            f"/api/v1/requirements/{rid}",
            json={"stage_assignees": [{"stage_id": 999999, "assignee_id": None}]},
            headers=auth_header(token),
        )
        assert resp.status_code == 404

    async def test_patch_nonexistent_pm_404(self, app_client, pm_user):
        token = await login_token(app_client, "pm1")
        rid = (
            await app_client.post(
                "/api/v1/requirements", json=create_body(), headers=auth_header(token)
            )
        ).json()["id"]
        resp = await app_client.patch(
            f"/api/v1/requirements/{rid}",
            json={"responsible_pm_id": 987654},
            headers=auth_header(token),
        )
        assert resp.status_code == 404


class TestLifecycle:
    async def _make(self, app_client, token) -> dict:
        rid = (
            await app_client.post(
                "/api/v1/requirements", json=create_body(), headers=auth_header(token)
            )
        ).json()["id"]
        detail = (
            await app_client.get(
                f"/api/v1/requirements/{rid}", headers=auth_header(token)
            )
        ).json()
        return detail

    async def test_pause_and_resume_shift_times(self, app_client, pm_user):
        token = await login_token(app_client, "pm1")
        detail = await self._make(app_client, token)
        rid = detail["id"]

        resp = await app_client.post(
            f"/api/v1/requirements/{rid}/pause", headers=auth_header(token)
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "paused"

        # 再次暂停 → 409
        resp = await app_client.post(
            f"/api/v1/requirements/{rid}/pause", headers=auth_header(token)
        )
        assert resp.status_code == 409

        resp = await app_client.post(
            f"/api/v1/requirements/{rid}/resume", headers=auth_header(token)
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "not_started"  # 无进行中环节且未逾期

        # 顺延写入 auto 变更历史（暂停时长 < 1 自然日则无顺延，仍应有历史为空或至少不报错）
        detail = (
            await app_client.get(
                f"/api/v1/requirements/{rid}", headers=auth_header(token)
            )
        ).json()
        auto_logs = [l for l in detail["change_logs"] if l["auto_generated"]]
        # 同日恢复 → 0 天顺延 → 无 auto 日志
        assert auto_logs == []

    async def test_resume_writes_auto_logs_when_crossed_days(
        self, app_client, pm_user, db
    ):
        from datetime import timedelta

        from app.core.config import TZ

        token = await login_token(app_client, "pm1")
        detail = await self._make(app_client, token)
        rid = detail["id"]

        # 先暂停，再把 paused_at 拨回 3 天前，模拟跨自然日暂停
        r = await app_client.post(
            f"/api/v1/requirements/{rid}/pause", headers=auth_header(token)
        )
        assert r.status_code == 200

        from app.models import Requirement

        req = await db.get(Requirement, rid)
        req.paused_at = req.paused_at - timedelta(days=3)
        await db.commit()

        await app_client.post(
            f"/api/v1/requirements/{rid}/resume", headers=auth_header(token)
        )
        detail = (
            await app_client.get(
                f"/api/v1/requirements/{rid}", headers=auth_header(token)
            )
        ).json()
        auto_logs = [l for l in detail["change_logs"] if l["auto_generated"]]
        # 7 个环节都有预估时间 → 顺延 3 天应产生 start+end 各 7 条 = 14 条
        assert len(auto_logs) == 14
        research = next(s for s in detail["stages"] if s["stage_type"] == "research")
        assert research["planned_start"] == "2030-01-04T09:00:00+08:00"

    async def test_resume_not_paused_409(self, app_client, pm_user):
        token = await login_token(app_client, "pm1")
        detail = await self._make(app_client, token)
        resp = await app_client.post(
            f"/api/v1/requirements/{detail['id']}/resume", headers=auth_header(token)
        )
        assert resp.status_code == 409

    async def test_mark_and_unmark_delayed(self, app_client, pm_user):
        token = await login_token(app_client, "pm1")
        detail = await self._make(app_client, token)
        rid = detail["id"]

        resp = await app_client.post(
            f"/api/v1/requirements/{rid}/mark-delayed",
            json={"reason": "接口方风险"},
            headers=auth_header(token),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "delayed"
        assert body["manual_delayed"] is True

        # 解除后回 not_started（无系统逾期）
        resp = await app_client.post(
            f"/api/v1/requirements/{rid}/unmark-delayed",
            json={"reason": "风险解除"},
            headers=auth_header(token),
        )
        assert resp.json()["status"] == "not_started"
        assert resp.json()["manual_delayed"] is False

        # 未标记时解除 → 409
        resp = await app_client.post(
            f"/api/v1/requirements/{rid}/unmark-delayed",
            json={"reason": "再解除"},
            headers=auth_header(token),
        )
        assert resp.status_code == 409

    async def test_mark_delayed_requires_reason(self, app_client, pm_user):
        token = await login_token(app_client, "pm1")
        detail = await self._make(app_client, token)
        resp = await app_client.post(
            f"/api/v1/requirements/{detail['id']}/mark-delayed",
            json={"reason": ""},
            headers=auth_header(token),
        )
        assert resp.status_code == 422

    async def test_developer_cannot_pause_403(self, app_client, pm_user, db):
        await seed_user(db, "dev4", "developer")
        t_pm = await login_token(app_client, "pm1")
        t_dev = await login_token(app_client, "dev4")
        detail = await self._make(app_client, t_pm)
        resp = await app_client.post(
            f"/api/v1/requirements/{detail['id']}/pause", headers=auth_header(t_dev)
        )
        assert resp.status_code == 403


class TestProductLineAndOrdering:
    """产品线字段与列表排序（需求列表体验优化）。"""

    async def test_create_with_product_line(self, app_client, pm_user):
        token = await login_token(app_client, "pm1")
        resp = await app_client.post(
            "/api/v1/requirements",
            json=create_body(title="带产品线", product_line="TiDB"),
            headers=auth_header(token),
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["product_line"] == "TiDB"

    async def test_create_invalid_product_line_422(self, app_client, pm_user):
        token = await login_token(app_client, "pm1")
        resp = await app_client.post(
            "/api/v1/requirements",
            json=create_body(product_line="Oracle"),
            headers=auth_header(token),
        )
        assert resp.status_code == 422

    async def test_filter_by_product_line(self, app_client, pm_user):
        token = await login_token(app_client, "pm1")
        for pl in ("MySQL", "Redis"):
            await app_client.post(
                "/api/v1/requirements",
                json=create_body(product_line=pl),
                headers=auth_header(token),
            )
        resp = await app_client.get(
            "/api/v1/requirements",
            params={"product_line": "MySQL"},
            headers=auth_header(token),
        )
        body = resp.json()
        assert body["total"] == 1
        assert body["items"][0]["product_line"] == "MySQL"

    async def test_patch_product_line(self, app_client, pm_user):
        token = await login_token(app_client, "pm1")
        rid = (
            await app_client.post(
                "/api/v1/requirements", json=create_body(), headers=auth_header(token)
            )
        ).json()["id"]
        resp = await app_client.patch(
            f"/api/v1/requirements/{rid}",
            json={"product_line": "Milvus"},
            headers=auth_header(token),
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["product_line"] == "Milvus"

    async def test_list_ordered_by_id_asc(self, app_client, pm_user):
        token = await login_token(app_client, "pm1")
        ids = []
        for i in range(3):
            rid = (
                await app_client.post(
                    "/api/v1/requirements",
                    json=create_body(title=f"顺序-{i}"),
                    headers=auth_header(token),
                )
            ).json()["id"]
            ids.append(rid)
        # 随便动一下第一个需求（改变 updated_at），列表顺序不应乱
        await app_client.post(
            f"/api/v1/requirements/{ids[0]}/mark-delayed",
            json={"reason": "打乱 updated_at"},
            headers=auth_header(token),
        )
        resp = await app_client.get(
            "/api/v1/requirements", headers=auth_header(token)
        )
        got = [it["id"] for it in resp.json()["items"]]
        assert got == sorted(got)
        assert got[:3] == ids

    async def test_list_and_detail_include_pm_name(self, app_client, pm_user):
        token = await login_token(app_client, "pm1")
        rid = (
            await app_client.post(
                "/api/v1/requirements", json=create_body(), headers=auth_header(token)
            )
        ).json()["id"]
        items = (
            await app_client.get("/api/v1/requirements", headers=auth_header(token))
        ).json()["items"]
        assert items[0]["pm_name"] == "pm1-显示名"
        detail = (
            await app_client.get(
                f"/api/v1/requirements/{rid}", headers=auth_header(token)
            )
        ).json()
        assert detail["pm_name"] == "pm1-显示名"
