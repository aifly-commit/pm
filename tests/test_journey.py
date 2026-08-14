"""M2 迭代 3：全旅程验收——按真实使用路径走完一个需求的生命周期。

路径：创建(带排期/负责人) → 推进(含并行窗口) → 逾期 → 改期恢复 → 人工标记/解除
→ 暂停/恢复(顺延) → 回退 → 重新推进 → 上线完成，每步断言状态与留痕。
"""

from __future__ import annotations

from datetime import timedelta

from app.models import Project, Requirement, RequirementStage
from tests.conftest import auth_header, login_token, seed_user
from tests.test_api_requirements import PLANS, _sh, create_body
from tests.test_api_stages import advance, make_requirement, stage_of


class TestJourney:
    async def test_full_lifecycle(self, app_client, pm_user, db):
        t_pm = await login_token(app_client, "pm1")
        dev = await seed_user(db, "journey_dev", "developer")
        t_dev = await login_token(app_client, "journey_dev")

        # ---- 1. 创建：挂项目 + 指派首环节负责人 ----
        project = Project(name="旅程项目", owner_id=pm_user.id)
        db.add(project)
        await db.flush()
        plans = [dict(p) for p in PLANS]
        plans[0]["assignee_id"] = dev.id
        resp = await app_client.post(
            "/api/v1/requirements",
            json=create_body(title="全流程需求", project_id=project.id, stages=plans),
            headers=auth_header(t_pm),
        )
        assert resp.status_code == 201
        rid = resp.json()["id"]
        detail = (
            await app_client.get(
                f"/api/v1/requirements/{rid}", headers=auth_header(t_pm)
            )
        ).json()
        assert detail["status"] == "not_started"
        assert detail["current_stage"] == "需求调研"

        # ---- 1b. 首环节排期改为已过期 → 未开始即延期（design.md 3.3）----
        sid = stage_of(detail, "research")["id"]
        resp = await app_client.patch(
            f"/api/v1/stages/{sid}/plan",
            json={
                "planned_start": "2020-01-01T09:00:00+08:00",
                "planned_end": "2020-01-03T18:00:00+08:00",
                "reason": "补录历史排期",
            },
            headers=auth_header(t_pm),
        )
        assert resp.status_code == 200
        detail = (
            await app_client.get(
                f"/api/v1/requirements/{rid}", headers=auth_header(t_pm)
            )
        ).json()
        assert detail["status"] == "delayed"  # 排了期不启动也算延期

        # ---- 1c. 改回远未来 → 恢复未开始 ----
        resp = await app_client.patch(
            f"/api/v1/stages/{sid}/plan",
            json={
                "planned_start": _sh(1, "09:00:00"),
                "planned_end": _sh(3),
                "reason": "重新排期",
            },
            headers=auth_header(t_pm),
        )
        assert resp.status_code == 200
        detail = (
            await app_client.get(
                f"/api/v1/requirements/{rid}", headers=auth_header(t_pm)
            )
        ).json()
        assert detail["status"] == "not_started"

        # ---- 2. 执行人开始首环节（负责人可操作），PM 完成 ----
        sid = stage_of(detail, "research")["id"]
        resp = await app_client.post(
            f"/api/v1/stages/{sid}/start", headers=auth_header(t_dev)
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "in_progress"
        resp = await app_client.post(
            f"/api/v1/stages/{sid}/complete", headers=auth_header(t_pm)
        )
        assert resp.status_code == 200
        detail = (
            await app_client.get(
                f"/api/v1/requirements/{rid}", headers=auth_header(t_pm)
            )
        ).json()

        # ---- 3. 推进到平台开发完成，进入并行窗口 ----
        detail = await advance(app_client, t_pm, detail, "review", "backend_dev")
        assert detail["current_stage"] == "前端开发"  # 下一个待开始
        detail = await advance(app_client, t_pm, detail, "frontend_dev")
        assert detail["current_stage"] == "API 开发"
        detail = await advance(app_client, t_pm, detail, "api_dev", "testing")

        # ---- 6. 人工标记延期 → 状态延期；解除 → 恢复 ----
        await app_client.post(
            f"/api/v1/requirements/{rid}/mark-delayed",
            json={"reason": "上线窗口风险"},
            headers=auth_header(t_pm),
        )
        detail = (
            await app_client.get(
                f"/api/v1/requirements/{rid}", headers=auth_header(t_pm)
            )
        ).json()
        assert detail["status"] == "delayed" and detail["manual_delayed"] is True
        await app_client.post(
            f"/api/v1/requirements/{rid}/unmark-delayed",
            json={"reason": "窗口确认"},
            headers=auth_header(t_pm),
        )
        detail = (
            await app_client.get(
                f"/api/v1/requirements/{rid}", headers=auth_header(t_pm)
            )
        ).json()
        assert detail["status"] == "in_progress"

        # ---- 7. 暂停 3 天 → 恢复：上线环节顺延并留 auto 日志 ----
        await app_client.post(
            f"/api/v1/requirements/{rid}/pause", headers=auth_header(t_pm)
        )
        req = await db.get(Requirement, rid)
        req.paused_at = req.paused_at - timedelta(days=3)
        await db.commit()
        await app_client.post(
            f"/api/v1/requirements/{rid}/resume", headers=auth_header(t_pm)
        )
        detail = (
            await app_client.get(
                f"/api/v1/requirements/{rid}", headers=auth_header(t_pm)
            )
        ).json()
        release = stage_of(detail, "release")
        assert release["planned_end"] == "2030-01-23T20:00:00+08:00"  # 顺延 3 天
        auto_logs = [l for l in detail["change_logs"] if l["auto_generated"]]
        assert all(l["reason"] == "需求暂停顺延" for l in auto_logs)

        # ---- 8. 测试不通过：回退到前端开发（当前所处环节 = release 未开始，
        #         furthest started = testing 已完成 → 允许从 testing 发起） ----
        testing_id = stage_of(detail, "testing")["id"]
        resp = await app_client.post(
            f"/api/v1/stages/{testing_id}/revert",
            json={
                "reason": "测试不通过，前端缺陷",
                "target_stage_id": stage_of(detail, "frontend_dev")["id"],
            },
            headers=auth_header(t_pm),
        )
        assert resp.status_code == 200, resp.text
        detail = (
            await app_client.get(
                f"/api/v1/requirements/{rid}", headers=auth_header(t_pm)
            )
        ).json()
        assert detail["current_stage"] == "前端开发"
        assert stage_of(detail, "frontend_dev")["status"] == "in_progress"
        assert stage_of(detail, "backend_dev")["status"] == "done"  # 前置保留
        assert stage_of(detail, "api_dev")["status"] == "not_started"  # 下游重置
        assert stage_of(detail, "release")["status"] == "not_started"
        assert len(detail["revert_logs"]) == 1

        # ---- 9. 重新推进到底：完成 = 终态，筛选不再命中任何环节 ----
        # 回退目标 frontend_dev 已是进行中，直接完成即可
        resp = await app_client.post(
            f"/api/v1/stages/{stage_of(detail, 'frontend_dev')['id']}/complete",
            headers=auth_header(t_pm),
        )
        assert resp.status_code == 200
        detail = (
            await app_client.get(
                f"/api/v1/requirements/{rid}", headers=auth_header(t_pm)
            )
        ).json()
        detail = await advance(app_client, t_pm, detail, "api_dev", "testing", "release")
        assert detail["status"] == "done"
        assert detail["current_stage"] is None

        resp = await app_client.get(
            "/api/v1/requirements",
            params={"stage_type": "release"},
            headers=auth_header(t_pm),
        )
        assert resp.json()["total"] == 0  # done 需求不命中环节筛选

        # ---- 10. 终态保护：不可暂停、不可标记延期、不可回退 ----
        assert (
            await app_client.post(
                f"/api/v1/requirements/{rid}/pause", headers=auth_header(t_pm)
            )
        ).status_code == 409
        assert (
            await app_client.post(
                f"/api/v1/requirements/{rid}/mark-delayed",
                json={"reason": "x"},
                headers=auth_header(t_pm),
            )
        ).status_code == 409
        assert (
            await app_client.post(
                f"/api/v1/stages/{testing_id}/revert",
                json={
                    "reason": "x",
                    "target_stage_id": stage_of(detail, "frontend_dev")["id"],
                },
                headers=auth_header(t_pm),
            )
        ).status_code == 409

        # 全程留痕核查：人工变更 + 自动顺延 + 回退
        detail = (
            await app_client.get(
                f"/api/v1/requirements/{rid}", headers=auth_header(t_pm)
            )
        ).json()
        manual_logs = [l for l in detail["change_logs"] if not l["auto_generated"]]
        # research 两次改期（补录 start+end、重排 start+end）= 4 条
        assert len(manual_logs) == 4
        assert len(detail["revert_logs"]) == 1


class TestExtraBranches:
    """补齐权限与校验分支（迭代 3 清扫）。"""

    async def test_lifecycle_403_for_developer(
        self, app_client, pm_user, db
    ):
        await seed_user(db, "extra_dev", "developer")
        t_pm = await login_token(app_client, "pm1")
        t_dev = await login_token(app_client, "extra_dev")
        detail = await make_requirement(app_client, t_pm)
        rid = detail["id"]
        await app_client.post(
            f"/api/v1/requirements/{rid}/pause", headers=auth_header(t_pm)
        )
        # 恢复 / 标记 / 解除 均仅负责 PM 与 Admin
        assert (
            await app_client.post(
                f"/api/v1/requirements/{rid}/resume", headers=auth_header(t_dev)
            )
        ).status_code == 403
        assert (
            await app_client.post(
                f"/api/v1/requirements/{rid}/mark-delayed",
                json={"reason": "r"},
                headers=auth_header(t_dev),
            )
        ).status_code == 403
        await app_client.post(
            f"/api/v1/requirements/{rid}/resume", headers=auth_header(t_pm)
        )
        await app_client.post(
            f"/api/v1/requirements/{rid}/mark-delayed",
            json={"reason": "r"},
            headers=auth_header(t_pm),
        )
        assert (
            await app_client.post(
                f"/api/v1/requirements/{rid}/unmark-delayed",
                json={"reason": "r"},
                headers=auth_header(t_dev),
            )
        ).status_code == 403

    async def test_stage_complete_403_for_other_developer(
        self, app_client, pm_user, db
    ):
        await seed_user(db, "extra_dev2", "developer")
        t_pm = await login_token(app_client, "pm1")
        t_dev = await login_token(app_client, "extra_dev2")
        detail = await make_requirement(app_client, t_pm)
        sid = stage_of(detail, "research")["id"]
        await app_client.post(f"/api/v1/stages/{sid}/start", headers=auth_header(t_pm))
        assert (
            await app_client.post(
                f"/api/v1/stages/{sid}/complete", headers=auth_header(t_dev)
            )
        ).status_code == 403

    async def test_change_logs_nonexistent_stage_404(self, app_client, pm_user):
        token = await login_token(app_client, "pm1")
        resp = await app_client.get(
            "/api/v1/stages/999999/change-logs", headers=auth_header(token)
        )
        assert resp.status_code == 404

    async def test_mark_delayed_on_paused_409(self, app_client, pm_user):
        token = await login_token(app_client, "pm1")
        detail = await make_requirement(app_client, token)
        await app_client.post(
            f"/api/v1/requirements/{detail['id']}/pause", headers=auth_header(token)
        )
        resp = await app_client.post(
            f"/api/v1/requirements/{detail['id']}/mark-delayed",
            json={"reason": "暂停中标记"},
            headers=auth_header(token),
        )
        assert resp.status_code == 409

    async def test_patch_description_and_project(self, app_client, pm_user, db):
        project = Project(name="项目Y", owner_id=pm_user.id)
        db.add(project)
        await db.flush()
        token = await login_token(app_client, "pm1")
        detail = await make_requirement(app_client, token)
        resp = await app_client.patch(
            f"/api/v1/requirements/{detail['id']}",
            json={"description": "背景补充", "project_id": project.id},
            headers=auth_header(token),
        )
        assert resp.status_code == 200
        assert resp.json()["description"] == "背景补充"
        assert resp.json()["project_id"] == project.id

        # 列表按 project_id 筛选
        resp = await app_client.get(
            "/api/v1/requirements",
            params={"project_id": project.id},
            headers=auth_header(token),
        )
        assert resp.json()["total"] == 1

    async def test_patch_nonexistent_project_404(self, app_client, pm_user):
        token = await login_token(app_client, "pm1")
        detail = await make_requirement(app_client, token)
        resp = await app_client.patch(
            f"/api/v1/requirements/{detail['id']}",
            json={"project_id": 555555},
            headers=auth_header(token),
        )
        assert resp.status_code == 404

    async def test_patch_stage_assignee_nonexistent_user_404(
        self, app_client, pm_user
    ):
        token = await login_token(app_client, "pm1")
        detail = await make_requirement(app_client, token)
        sid = detail["stages"][0]["id"]
        resp = await app_client.patch(
            f"/api/v1/requirements/{detail['id']}",
            json={"stage_assignees": [{"stage_id": sid, "assignee_id": 666666}]},
            headers=auth_header(token),
        )
        assert resp.status_code == 404

    async def test_revert_by_developer_403(self, app_client, pm_user, db):
        await seed_user(db, "extra_dev3", "developer")
        t_pm = await login_token(app_client, "pm1")
        t_dev = await login_token(app_client, "extra_dev3")
        detail = await make_requirement(app_client, t_pm)
        detail = await advance(app_client, t_pm, detail, "research")
        review_id = stage_of(detail, "review")["id"]
        await app_client.post(
            f"/api/v1/stages/{review_id}/start", headers=auth_header(t_pm)
        )
        resp = await app_client.post(
            f"/api/v1/stages/{review_id}/revert",
            json={
                "reason": "越权回退",
                "target_stage_id": stage_of(detail, "research")["id"],
            },
            headers=auth_header(t_dev),
        )
        assert resp.status_code == 403

    async def test_patch_transfer_pm(self, app_client, admin_user, pm_user, db):
        other = await seed_user(db, "pm_x", "pm")
        t_admin = await login_token(app_client, "admin1")
        t_pm = await login_token(app_client, "pm1")
        detail = await make_requirement(app_client, t_pm)
        resp = await app_client.patch(
            f"/api/v1/requirements/{detail['id']}",
            json={"responsible_pm_id": other.id},
            headers=auth_header(t_admin),
        )
        assert resp.status_code == 200
        assert resp.json()["responsible_pm_id"] == other.id

    async def test_list_stage_type_filter_in_progress(self, app_client, pm_user):
        token = await login_token(app_client, "pm1")
        detail = await make_requirement(app_client, token)
        sid = stage_of(detail, "research")["id"]
        await app_client.post(f"/api/v1/stages/{sid}/start", headers=auth_header(token))
        resp = await app_client.get(
            "/api/v1/requirements",
            params={"stage_type": "research"},
            headers=auth_header(token),
        )
        assert resp.json()["total"] == 1
        # review 未在途 → 不命中
        resp = await app_client.get(
            "/api/v1/requirements",
            params={"stage_type": "review"},
            headers=auth_header(token),
        )
        assert resp.json()["total"] == 0

    async def test_create_unknown_stage_type_service_guard(self, db, pm_user):
        # schema 层已挡非法类型；service 层兜底分支直接验证
        from app.services.requirements import RequirementError, create_requirement
        import pytest

        with pytest.raises(RequirementError, match="未知环节类型"):
            await create_requirement(
                db,
                title="兜底",
                description=None,
                priority="P2",
                project_id=None,
                responsible_pm_id=pm_user.id,
                stage_plans=[
                    {"stage_type": "hacking", "planned_start": None, "planned_end": None}
                ],
            )
