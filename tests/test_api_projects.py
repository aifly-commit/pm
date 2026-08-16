"""项目 API（design.md 8.4、5.1、5.2）。"""

from __future__ import annotations

from app.models import Requirement
from tests.conftest import auth_header, login_token, seed_user
from tests.test_api_requirements import create_body


async def make_project(app_client, token, **overrides) -> dict:
    payload = {"name": "新项目", "contacts": [{"name": "张三", "phone": "13800000000"}]}
    payload.update(overrides)
    resp = await app_client.post(
        "/api/v1/projects", json=payload, headers=auth_header(token)
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def make_requirement_id(app_client, token, title="项目需求") -> int:
    resp = await app_client.post(
        "/api/v1/requirements", json=create_body(title=title), headers=auth_header(token)
    )
    return resp.json()["id"]


class TestProjectCRUD:
    async def test_create_with_contacts(self, app_client, pm_user):
        token = await login_token(app_client, "pm1")
        body = await make_project(app_client, token)
        assert body["name"] == "新项目"
        assert body["status"] == "not_started"
        assert body["owner_id"] == pm_user.id
        assert body["contacts"][0]["name"] == "张三"

    async def test_developer_cannot_create_403(self, app_client, pm_user, db):
        await seed_user(db, "proj_dev", "developer")
        token = await login_token(app_client, "proj_dev")
        resp = await app_client.post(
            "/api/v1/projects", json={"name": "X"}, headers=auth_header(token)
        )
        assert resp.status_code == 403

    async def test_admin_can_set_owner(self, app_client, admin_user, pm_user):
        t_admin = await login_token(app_client, "admin1")
        body = await make_project(app_client, t_admin, owner_id=pm_user.id)
        assert body["owner_id"] == pm_user.id

    async def test_pm_cannot_set_other_owner_403(self, app_client, pm_user, db):
        other = await seed_user(db, "pm_b", "pm")
        token = await login_token(app_client, "pm1")
        resp = await app_client.post(
            "/api/v1/projects",
            json={"name": "X", "owner_id": other.id},
            headers=auth_header(token),
        )
        assert resp.status_code == 403

    async def test_list_with_filters(self, app_client, pm_user, db):
        other = await seed_user(db, "pm_c", "pm")
        t1 = await login_token(app_client, "pm1")
        t2 = await login_token(app_client, "pm_c")
        await make_project(app_client, t1, name="甲项目")
        await make_project(app_client, t1, name="乙项目", status="in_progress")
        await make_project(app_client, t2, name="丙项目")

        resp = await app_client.get("/api/v1/projects", headers=auth_header(t1))
        assert resp.json()["total"] == 3

        resp = await app_client.get(
            "/api/v1/projects", params={"status": "in_progress"}, headers=auth_header(t1)
        )
        assert resp.json()["total"] == 1
        assert resp.json()["items"][0]["name"] == "乙项目"

        resp = await app_client.get(
            "/api/v1/projects", params={"owner_id": other.id}, headers=auth_header(t1)
        )
        assert resp.json()["total"] == 1
        assert resp.json()["items"][0]["name"] == "丙项目"

    async def test_get_nonexistent_404(self, app_client, pm_user):
        token = await login_token(app_client, "pm1")
        resp = await app_client.get("/api/v1/projects/424242", headers=auth_header(token))
        assert resp.status_code == 404


class TestProjectUpdate:
    async def test_update_by_owner(self, app_client, pm_user):
        token = await login_token(app_client, "pm1")
        project = await make_project(app_client, token)
        resp = await app_client.patch(
            f"/api/v1/projects/{project['id']}",
            json={
                "description": "项目背景",
                "progress_note": "一期联调中",
                "progress_percent": 40,
                "status": "in_progress",
                "contacts": [{"name": "李四", "email": "lisi@x.com"}],
            },
            headers=auth_header(token),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["progress_percent"] == 40
        assert body["status"] == "in_progress"
        assert body["contacts"][0]["name"] == "李四"

    async def test_update_by_other_pm_403(self, app_client, pm_user, db):
        await seed_user(db, "pm_d", "pm")
        t1 = await login_token(app_client, "pm1")
        t2 = await login_token(app_client, "pm_d")
        project = await make_project(app_client, t1)
        resp = await app_client.patch(
            f"/api/v1/projects/{project['id']}",
            json={"name": "抢改"},
            headers=auth_header(t2),
        )
        assert resp.status_code == 403

    async def test_update_by_admin_ok(self, app_client, admin_user, pm_user):
        t_admin = await login_token(app_client, "admin1")
        t_pm = await login_token(app_client, "pm1")
        project = await make_project(app_client, t_pm)
        resp = await app_client.patch(
            f"/api/v1/projects/{project['id']}",
            json={"progress_percent": 80},
            headers=auth_header(t_admin),
        )
        assert resp.status_code == 200
        assert resp.json()["progress_percent"] == 80

    async def test_invalid_percent_422(self, app_client, pm_user):
        token = await login_token(app_client, "pm1")
        project = await make_project(app_client, token)
        resp = await app_client.patch(
            f"/api/v1/projects/{project['id']}",
            json={"progress_percent": 150},
            headers=auth_header(token),
        )
        assert resp.status_code == 422

    async def test_invalid_status_422(self, app_client, pm_user):
        token = await login_token(app_client, "pm1")
        project = await make_project(app_client, token)
        resp = await app_client.patch(
            f"/api/v1/projects/{project['id']}",
            json={"status": "cancelled"},
            headers=auth_header(token),
        )
        assert resp.status_code == 422

    async def test_owner_change_by_non_admin_403(self, app_client, pm_user, db):
        other = await seed_user(db, "pm_e", "pm")
        token = await login_token(app_client, "pm1")
        project = await make_project(app_client, token)
        resp = await app_client.patch(
            f"/api/v1/projects/{project['id']}",
            json={"owner_id": other.id},
            headers=auth_header(token),
        )
        assert resp.status_code == 403


class TestAttachDetach:
    async def test_attach_and_completion_rate(self, app_client, pm_user, db):
        token = await login_token(app_client, "pm1")
        project = await make_project(app_client, token)
        pid = project["id"]
        r1 = await make_requirement_id(app_client, token, "需求一")
        r2 = await make_requirement_id(app_client, token, "需求二")
        r3 = await make_requirement_id(app_client, token, "需求三")

        for rid in (r1, r2, r3):
            resp = await app_client.post(
                f"/api/v1/projects/{pid}/requirements",
                json={"requirement_id": rid},
                headers=auth_header(token),
            )
            assert resp.status_code == 200, resp.text

        # 两条置为 done → 完成率 2/3
        for rid in (r1, r2):
            req = await db.get(Requirement, rid)
            req.status = "done"
        await db.commit()

        resp = await app_client.get(
            f"/api/v1/projects/{pid}", headers=auth_header(token)
        )
        detail = resp.json()
        assert detail["total"] == 3
        assert detail["done_count"] == 2
        assert detail["completion_rate"] == 0.6667  # 保留 4 位小数
        assert {i["title"] for i in detail["requirements"]} == {"需求一", "需求二", "需求三"}
        assert all(i["current_stage"] == "需求调研" for i in detail["requirements"])
        assert all(i["is_delayed"] is False for i in detail["requirements"])

    async def test_attach_already_in_other_project_409(self, app_client, pm_user):
        token = await login_token(app_client, "pm1")
        p1 = await make_project(app_client, token, name="项目一")
        p2 = await make_project(app_client, token, name="项目二")
        rid = await make_requirement_id(app_client, token)
        await app_client.post(
            f"/api/v1/projects/{p1['id']}/requirements",
            json={"requirement_id": rid},
            headers=auth_header(token),
        )
        resp = await app_client.post(
            f"/api/v1/projects/{p2['id']}/requirements",
            json={"requirement_id": rid},
            headers=auth_header(token),
        )
        assert resp.status_code == 409
        assert "已挂接至其他项目" in resp.json()["detail"]

    async def test_attach_same_project_idempotent(self, app_client, pm_user):
        token = await login_token(app_client, "pm1")
        project = await make_project(app_client, token)
        rid = await make_requirement_id(app_client, token)
        await app_client.post(
            f"/api/v1/projects/{project['id']}/requirements",
            json={"requirement_id": rid},
            headers=auth_header(token),
        )
        resp = await app_client.post(
            f"/api/v1/projects/{project['id']}/requirements",
            json={"requirement_id": rid},
            headers=auth_header(token),
        )
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    async def test_attach_nonexistent_requirement_404(self, app_client, pm_user):
        token = await login_token(app_client, "pm1")
        project = await make_project(app_client, token)
        resp = await app_client.post(
            f"/api/v1/projects/{project['id']}/requirements",
            json={"requirement_id": 987654},
            headers=auth_header(token),
        )
        assert resp.status_code == 404

    async def test_attach_by_developer_403(self, app_client, pm_user, db):
        await seed_user(db, "proj_dev2", "developer")
        t_pm = await login_token(app_client, "pm1")
        t_dev = await login_token(app_client, "proj_dev2")
        project = await make_project(app_client, t_pm)
        rid = await make_requirement_id(app_client, t_pm)
        resp = await app_client.post(
            f"/api/v1/projects/{project['id']}/requirements",
            json={"requirement_id": rid},
            headers=auth_header(t_dev),
        )
        assert resp.status_code == 403

    async def test_detach(self, app_client, pm_user):
        token = await login_token(app_client, "pm1")
        project = await make_project(app_client, token)
        rid = await make_requirement_id(app_client, token)
        await app_client.post(
            f"/api/v1/projects/{project['id']}/requirements",
            json={"requirement_id": rid},
            headers=auth_header(token),
        )
        resp = await app_client.delete(
            f"/api/v1/projects/{project['id']}/requirements/{rid}",
            headers=auth_header(token),
        )
        assert resp.status_code == 200
        assert resp.json()["total"] == 0
        # 需求侧 project_id 已置空
        detail = (
            await app_client.get(
                f"/api/v1/requirements/{rid}", headers=auth_header(token)
            )
        ).json()
        assert detail["project_id"] is None

    async def test_detach_not_attached_404(self, app_client, pm_user):
        token = await login_token(app_client, "pm1")
        project = await make_project(app_client, token)
        rid = await make_requirement_id(app_client, token)  # 未挂接
        resp = await app_client.delete(
            f"/api/v1/projects/{project['id']}/requirements/{rid}",
            headers=auth_header(token),
        )
        assert resp.status_code == 404


class TestDeleteProject:
    async def test_delete_keeps_requirements(self, app_client, pm_user, db):
        token = await login_token(app_client, "pm1")
        project = await make_project(app_client, token)
        rid = await make_requirement_id(app_client, token)
        await app_client.post(
            f"/api/v1/projects/{project['id']}/requirements",
            json={"requirement_id": rid},
            headers=auth_header(token),
        )

        resp = await app_client.delete(
            f"/api/v1/projects/{project['id']}", headers=auth_header(token)
        )
        assert resp.status_code == 204

        # 项目已删，需求保留且解除挂接（不级联删除，design.md 8.4）
        assert await db.get(Requirement, rid) is not None
        req = await db.get(Requirement, rid)
        assert req.project_id is None
        assert (
            await app_client.get(
                f"/api/v1/projects/{project['id']}", headers=auth_header(token)
            )
        ).status_code == 404

    async def test_delete_by_other_pm_403(self, app_client, pm_user, db):
        await seed_user(db, "pm_f", "pm")
        t1 = await login_token(app_client, "pm1")
        t2 = await login_token(app_client, "pm_f")
        project = await make_project(app_client, t1)
        resp = await app_client.delete(
            f"/api/v1/projects/{project['id']}", headers=auth_header(t2)
        )
        assert resp.status_code == 403

    async def test_delete_nonexistent_404(self, app_client, pm_user):
        token = await login_token(app_client, "pm1")
        resp = await app_client.delete(
            "/api/v1/projects/999999", headers=auth_header(token)
        )
        assert resp.status_code == 404
