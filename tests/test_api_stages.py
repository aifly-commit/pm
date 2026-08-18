"""环节 API（design.md 8.3）。"""

from __future__ import annotations

from tests.conftest import auth_header, login_token, seed_user
from tests.test_api_requirements import PLANS, create_body


async def make_requirement(app_client, token) -> dict:
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


def stage_of(detail: dict, stage_type: str) -> dict:
    return next(s for s in detail["stages"] if s["stage_type"] == stage_type)


async def advance(app_client, token, detail, *types) -> dict:
    """依次 start+complete 指定环节，返回最新详情。"""
    for t in types:
        sid = stage_of(detail, t)["id"]
        r = await app_client.post(
            f"/api/v1/stages/{sid}/start", headers=auth_header(token)
        )
        assert r.status_code == 200, r.text
        r = await app_client.post(
            f"/api/v1/stages/{sid}/complete", headers=auth_header(token)
        )
        assert r.status_code == 200, r.text
        detail = (
            await app_client.get(
                f"/api/v1/requirements/{detail['id']}", headers=auth_header(token)
            )
        ).json()
    return detail


class TestStartComplete:
    async def test_start_first_stage(self, app_client, pm_user):
        token = await login_token(app_client, "pm1")
        detail = await make_requirement(app_client, token)
        sid = stage_of(detail, "research")["id"]
        resp = await app_client.post(
            f"/api/v1/stages/{sid}/start", headers=auth_header(token)
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "in_progress"
        assert body["current_stage"] == "需求调研"

    async def test_start_without_prereq_409(self, app_client, pm_user):
        token = await login_token(app_client, "pm1")
        detail = await make_requirement(app_client, token)
        sid = stage_of(detail, "testing")["id"]
        resp = await app_client.post(
            f"/api/v1/stages/{sid}/start", headers=auth_header(token)
        )
        assert resp.status_code == 409
        assert "前置环节" in resp.json()["detail"]

    async def test_start_twice_409(self, app_client, pm_user):
        token = await login_token(app_client, "pm1")
        detail = await make_requirement(app_client, token)
        sid = stage_of(detail, "research")["id"]
        await app_client.post(f"/api/v1/stages/{sid}/start", headers=auth_header(token))
        resp = await app_client.post(
            f"/api/v1/stages/{sid}/start", headers=auth_header(token)
        )
        assert resp.status_code == 409

    async def test_complete_without_start_409(self, app_client, pm_user):
        token = await login_token(app_client, "pm1")
        detail = await make_requirement(app_client, token)
        sid = stage_of(detail, "research")["id"]
        resp = await app_client.post(
            f"/api/v1/stages/{sid}/complete", headers=auth_header(token)
        )
        assert resp.status_code == 409
        assert "仅进行中的环节可标记完成" in resp.json()["detail"]

    async def test_parallel_stages_and_current_stage_label(
        self, app_client, pm_user
    ):
        token = await login_token(app_client, "pm1")
        detail = await make_requirement(app_client, token)
        detail = await advance(app_client, token, detail, "research", "review", "backend_dev")

        # 只启动前端 → 当前环节=前端开发
        sid = stage_of(detail, "frontend_dev")["id"]
        await app_client.post(f"/api/v1/stages/{sid}/start", headers=auth_header(token))
        detail = (
            await app_client.get(
                f"/api/v1/requirements/{detail['id']}", headers=auth_header(token)
            )
        ).json()
        assert detail["current_stage"] == "前端开发"

        # API 开发也启动 → 并行窗口标注（design.md 3.5）
        sid = stage_of(detail, "api_dev")["id"]
        await app_client.post(f"/api/v1/stages/{sid}/start", headers=auth_header(token))
        detail = (
            await app_client.get(
                f"/api/v1/requirements/{detail['id']}", headers=auth_header(token)
            )
        ).json()
        assert detail["current_stage"] == "前端开发（并行）"

    async def test_testing_needs_all_three_dev(self, app_client, pm_user):
        token = await login_token(app_client, "pm1")
        detail = await make_requirement(app_client, token)
        detail = await advance(
            app_client, token, detail, "research", "review", "backend_dev", "frontend_dev"
        )
        sid = stage_of(detail, "testing")["id"]
        resp = await app_client.post(
            f"/api/v1/stages/{sid}/start", headers=auth_header(token)
        )
        assert resp.status_code == 409
        assert "api_dev" in resp.json()["detail"]

    async def test_complete_release_marks_requirement_done(
        self, app_client, pm_user
    ):
        token = await login_token(app_client, "pm1")
        detail = await make_requirement(app_client, token)
        detail = await advance(
            app_client,
            token,
            detail,
            "research",
            "review",
            "backend_dev",
            "frontend_dev",
            "api_dev",
            "testing",
            "release",
        )
        assert detail["status"] == "done"
        assert detail["current_stage"] is None
        # 终态：done 后不能再暂停
        resp = await app_client.post(
            f"/api/v1/requirements/{detail['id']}/pause", headers=auth_header(token)
        )
        assert resp.status_code == 409

    async def test_assignee_can_start_own_stage(self, app_client, pm_user, db):
        dev = await seed_user(db, "dev9", "developer")
        t_pm = await login_token(app_client, "pm1")
        t_dev = await login_token(app_client, "dev9")
        detail = await make_requirement(app_client, t_pm)
        sid = stage_of(detail, "research")["id"]
        await app_client.patch(
            f"/api/v1/stages/{sid}/assignee",
            json={"assignee_id": dev.id},
            headers=auth_header(t_pm),
        )
        resp = await app_client.post(
            f"/api/v1/stages/{sid}/start", headers=auth_header(t_dev)
        )
        assert resp.status_code == 200

    async def test_other_developer_cannot_start_403(
        self, app_client, pm_user, db
    ):
        await seed_user(db, "dev10", "developer")
        await seed_user(db, "dev11", "developer")
        t_pm = await login_token(app_client, "pm1")
        t_other = await login_token(app_client, "dev11")
        detail = await make_requirement(app_client, t_pm)
        sid = stage_of(detail, "research")["id"]
        resp = await app_client.post(
            f"/api/v1/stages/{sid}/start", headers=auth_header(t_other)
        )
        assert resp.status_code == 403

    async def test_start_nonexistent_stage_404(self, app_client, pm_user):
        token = await login_token(app_client, "pm1")
        resp = await app_client.post(
            "/api/v1/stages/999999/start", headers=auth_header(token)
        )
        assert resp.status_code == 404


class TestRevert:
    async def test_review_revert_to_research(self, app_client, pm_user):
        token = await login_token(app_client, "pm1")
        detail = await make_requirement(app_client, token)
        detail = await advance(app_client, token, detail, "research")
        # 审评进行中不通过 → 从 review（当前所处环节）发起回退
        review_id = stage_of(detail, "review")["id"]
        r = await app_client.post(
            f"/api/v1/stages/{review_id}/start", headers=auth_header(token)
        )
        assert r.status_code == 200

        resp = await app_client.post(
            f"/api/v1/stages/{review_id}/revert",
            json={
                "reason": "审评不通过",
                "target_stage_id": stage_of(detail, "research")["id"],
            },
            headers=auth_header(token),
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["requirement"]["current_stage"] == "需求调研"
        # review 及其后环节被重置
        assert len(body["reset_stage_ids"]) == 6

        detail = (
            await app_client.get(
                f"/api/v1/requirements/{detail['id']}", headers=auth_header(token)
            )
        ).json()
        research = stage_of(detail, "research")
        review = stage_of(detail, "review")
        assert research["status"] == "in_progress"
        assert research["actual_end"] is None
        assert review["status"] == "not_started"
        assert review["actual_start"] is None
        # 回退留痕
        assert len(detail["revert_logs"]) == 1
        assert detail["revert_logs"][0]["reason"] == "审评不通过"

    async def test_revert_from_non_current_stage_409(self, app_client, pm_user):
        token = await login_token(app_client, "pm1")
        detail = await make_requirement(app_client, token)
        detail = await advance(app_client, token, detail, "research", "review")
        # 当前所处环节是 review 之后……此处试图从 review 发起（review 已完成且是最近开始环节），
        # 但已推进到 backend？未推进——review 完成后无进行中环节，furthest=review，允许。
        # 改为构造：推进到 backend 进行中，从 review 发起回退 → 非当前环节 → 409
        sid = stage_of(detail, "backend_dev")["id"]
        await app_client.post(f"/api/v1/stages/{sid}/start", headers=auth_header(token))
        resp = await app_client.post(
            f"/api/v1/stages/{stage_of(detail, 'review')['id']}/revert",
            json={
                "reason": "越权回退",
                "target_stage_id": stage_of(detail, "research")["id"],
            },
            headers=auth_header(token),
        )
        assert resp.status_code == 409
        assert "当前所处环节" in resp.json()["detail"]

    async def test_revert_invalid_target_409(self, app_client, pm_user):
        token = await login_token(app_client, "pm1")
        detail = await make_requirement(app_client, token)
        detail = await advance(app_client, token, detail, "research")
        review_id = stage_of(detail, "review")["id"]
        await app_client.post(f"/api/v1/stages/{review_id}/start", headers=auth_header(token))
        resp = await app_client.post(
            f"/api/v1/stages/{review_id}/revert",
            json={
                "reason": "目标非法",
                "target_stage_id": stage_of(detail, "backend_dev")["id"],
            },
            headers=auth_header(token),
        )
        assert resp.status_code == 409
        assert "不允许从 review 回退到 backend_dev" in resp.json()["detail"]

    async def test_revert_nonexistent_target_404(self, app_client, pm_user):
        token = await login_token(app_client, "pm1")
        detail = await make_requirement(app_client, token)
        detail = await advance(app_client, token, detail, "research")
        resp = await app_client.post(
            f"/api/v1/stages/{stage_of(detail, 'review')['id']}/revert",
            json={"reason": "r", "target_stage_id": 999999},
            headers=auth_header(token),
        )
        assert resp.status_code == 404

    async def test_release_cannot_initiate_revert(self, app_client, pm_user):
        token = await login_token(app_client, "pm1")
        detail = await make_requirement(app_client, token)
        # 推进到 release 进行中（当前所处环节 = release），release 不在允许发起集合
        detail = await advance(
            app_client, token, detail,
            "research", "review", "backend_dev", "frontend_dev", "api_dev", "testing",
        )
        release_id = stage_of(detail, "release")["id"]
        r = await app_client.post(
            f"/api/v1/stages/{release_id}/start", headers=auth_header(token)
        )
        assert r.status_code == 200
        resp = await app_client.post(
            f"/api/v1/stages/{release_id}/revert",
            json={"reason": "r", "target_stage_id": stage_of(detail, "testing")["id"]},
            headers=auth_header(token),
        )
        assert resp.status_code == 409
        assert "不允许发起回退" in resp.json()["detail"]


class TestPlanUpdate:
    async def test_update_plan_writes_log_and_resets_reminder(
        self, app_client, pm_user, db
    ):
        from app.models import RequirementStage

        token = await login_token(app_client, "pm1")
        detail = await make_requirement(app_client, token)
        sid = stage_of(detail, "research")["id"]

        # 预置"临期提醒已发"标记，验证改期后重置（design.md 4.1）
        stage_obj = await db.get(RequirementStage, sid)
        stage_obj.reminder_sent = True
        await db.commit()

        # 提前一天收口（不破坏下游顺序：review 仍从 01-03 开始）
        resp = await app_client.patch(
            f"/api/v1/stages/{sid}/plan",
            json={
                "planned_end": "2030-01-02",
                "reason": "提前收口",
            },
            headers=auth_header(token),
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["reminder_sent"] is False
        assert resp.json()["last_delay_reason"] == "提前收口"

        logs = (
            await app_client.get(
                f"/api/v1/stages/{sid}/change-logs", headers=auth_header(token)
            )
        ).json()
        assert len(logs) == 1
        assert logs[0]["field"] == "planned_end"
        assert logs[0]["old_value"] == "2030-01-03"
        assert logs[0]["new_value"] == "2030-01-02"
        assert logs[0]["reason"] == "提前收口"
        assert logs[0]["auto_generated"] is False

    async def test_first_plan_on_unscheduled_stage_no_500(self, app_client, pm_user):
        """回归：未排期环节首次设置预估时间，old_value 为 NULL 不得触发 500。"""
        token = await login_token(app_client, "pm1")
        resp = await app_client.post(
            "/api/v1/requirements",
            # 仅填必填的预计上线时间，其余环节不排期
            json=create_body(
                stages=[{"stage_type": "release", "planned_end": "2030-03-01T23:59:59+08:00"}]
            ),
            headers=auth_header(token),
        )
        assert resp.status_code == 201, resp.text
        rid = resp.json()["id"]
        detail = (
            await app_client.get(
                f"/api/v1/requirements/{rid}", headers=auth_header(token)
            )
        ).json()
        research = stage_of(detail, "research")
        assert research["planned_start"] is None and research["planned_end"] is None

        resp = await app_client.patch(
            f"/api/v1/stages/{research['id']}/plan",
            json={
                "planned_start": "2030-02-02T09:00:00+08:00",
                "planned_end": "2030-02-04T18:00:00+08:00",
                "reason": "首次排期",
            },
            headers=auth_header(token),
        )
        assert resp.status_code == 200, resp.text

        logs = (
            await app_client.get(
                f"/api/v1/stages/{research['id']}/change-logs",
                headers=auth_header(token),
            )
        ).json()
        assert len(logs) == 2
        by_field = {l["field"]: l for l in logs}
        assert by_field["planned_start"]["old_value"] is None
        assert by_field["planned_start"]["new_value"] == "2030-02-02"
        assert by_field["planned_end"]["old_value"] is None
        assert by_field["planned_end"]["new_value"] == "2030-02-04"

    async def test_update_plan_conflict_409(self, app_client, pm_user):
        token = await login_token(app_client, "pm1")
        detail = await make_requirement(app_client, token)
        sid = stage_of(detail, "research")["id"]
        # research 结束改到 review 开始月份（1 月）之后的 2 月 → 跨月倒置破坏下游顺序
        resp = await app_client.patch(
            f"/api/v1/stages/{sid}/plan",
            json={
                "planned_end": "2030-02-06T18:00:00+08:00",
                "reason": "冲突改期",
            },
            headers=auth_header(token),
        )
        assert resp.status_code == 409
        assert "前置环节" in resp.json()["detail"]
        # 原值未变
        detail2 = (
            await app_client.get(
                f"/api/v1/requirements/{detail['id']}", headers=auth_header(token)
            )
        ).json()
        assert stage_of(detail2, "research")["planned_end"] == "2030-01-03"

    async def test_update_plan_requires_reason(self, app_client, pm_user):
        token = await login_token(app_client, "pm1")
        detail = await make_requirement(app_client, token)
        sid = stage_of(detail, "research")["id"]
        resp = await app_client.patch(
            f"/api/v1/stages/{sid}/plan",
            json={"planned_end": "2030-01-04T18:00:00+08:00", "reason": ""},
            headers=auth_header(token),
        )
        assert resp.status_code == 422

    async def test_update_plan_no_change_409(self, app_client, pm_user):
        token = await login_token(app_client, "pm1")
        detail = await make_requirement(app_client, token)
        sid = stage_of(detail, "research")["id"]
        resp = await app_client.patch(
            f"/api/v1/stages/{sid}/plan",
            json={"planned_end": "2030-01-03T18:00:00+08:00", "reason": "没变化"},
            headers=auth_header(token),
        )
        assert resp.status_code == 409

    async def test_update_plan_done_stage_409(self, app_client, pm_user):
        token = await login_token(app_client, "pm1")
        detail = await make_requirement(app_client, token)
        detail = await advance(app_client, token, detail, "research")
        sid = stage_of(detail, "research")["id"]
        resp = await app_client.patch(
            f"/api/v1/stages/{sid}/plan",
            json={"planned_end": "2030-01-09T18:00:00+08:00", "reason": "已完成改期"},
            headers=auth_header(token),
        )
        assert resp.status_code == 409
        assert "已完成" in resp.json()["detail"]

    async def test_plan_overdue_then_extend_recovers_delay(
        self, app_client, pm_user
    ):
        token = await login_token(app_client, "pm1")
        detail = await make_requirement(app_client, token)
        sid = stage_of(detail, "research")["id"]
        # 先改成已逾期（过去时间，且不破坏顺序——research 是首环节）
        resp = await app_client.patch(
            f"/api/v1/stages/{sid}/plan",
            json={
                "planned_start": "2020-01-01T09:00:00+08:00",
                "planned_end": "2020-01-03T18:00:00+08:00",
                "reason": "补录历史排期",
            },
            headers=auth_header(token),
        )
        assert resp.status_code == 200
        detail = (
            await app_client.get(
                f"/api/v1/requirements/{detail['id']}", headers=auth_header(token)
            )
        ).json()
        assert detail["status"] == "delayed"  # 未开始 + 超期 → 延期

        # 改回远未来 → 恢复 not_started（改期同步重算）
        resp = await app_client.patch(
            f"/api/v1/stages/{sid}/plan",
            json={
                "planned_start": "2030-01-01T09:00:00+08:00",
                "planned_end": "2030-01-03T18:00:00+08:00",
                "reason": "重新排期",
            },
            headers=auth_header(token),
        )
        detail = (
            await app_client.get(
                f"/api/v1/requirements/{detail['id']}", headers=auth_header(token)
            )
        ).json()
        assert detail["status"] == "not_started"

    async def test_developer_cannot_update_plan_403(self, app_client, pm_user, db):
        await seed_user(db, "dev20", "developer")
        t_pm = await login_token(app_client, "pm1")
        t_dev = await login_token(app_client, "dev20")
        detail = await make_requirement(app_client, t_pm)
        sid = stage_of(detail, "research")["id"]
        resp = await app_client.patch(
            f"/api/v1/stages/{sid}/plan",
            json={"planned_end": "2030-01-09T18:00:00+08:00", "reason": "r"},
            headers=auth_header(t_dev),
        )
        assert resp.status_code == 403


class TestAssignee:
    async def test_assign_by_owner(self, app_client, pm_user, db):
        dev = await seed_user(db, "dev30", "developer")
        token = await login_token(app_client, "pm1")
        detail = await make_requirement(app_client, token)
        sid = stage_of(detail, "research")["id"]
        resp = await app_client.patch(
            f"/api/v1/stages/{sid}/assignee",
            json={"assignee_id": dev.id},
            headers=auth_header(token),
        )
        assert resp.status_code == 200
        assert resp.json()["assignee_id"] == dev.id

    async def test_assign_by_developer_403(self, app_client, pm_user, db):
        await seed_user(db, "dev31", "developer")
        t_pm = await login_token(app_client, "pm1")
        t_dev = await login_token(app_client, "dev31")
        detail = await make_requirement(app_client, t_pm)
        sid = stage_of(detail, "research")["id"]
        resp = await app_client.patch(
            f"/api/v1/stages/{sid}/assignee",
            json={"assignee_id": None},
            headers=auth_header(t_dev),
        )
        assert resp.status_code == 403

    async def test_assign_nonexistent_user_404(self, app_client, pm_user):
        token = await login_token(app_client, "pm1")
        detail = await make_requirement(app_client, token)
        sid = stage_of(detail, "research")["id"]
        resp = await app_client.patch(
            f"/api/v1/stages/{sid}/assignee",
            json={"assignee_id": 876543},
            headers=auth_header(token),
        )
        assert resp.status_code == 404
