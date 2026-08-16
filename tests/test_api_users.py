"""用户管理 API（仅 Admin，design.md 8.5）。"""

from __future__ import annotations

from sqlalchemy import select

from app.models import Requirement, RequirementStage
from tests.conftest import DEFAULT_PASSWORD, auth_header, login_token, seed_user


async def admin_headers(app_client):
    token = await login_token(app_client, "admin1")
    return auth_header(token)


class TestPermission:
    async def test_non_admin_gets_403(self, app_client, pm_user):
        token = await login_token(app_client, "pm1")
        resp = await app_client.get("/api/v1/users", headers=auth_header(token))
        assert resp.status_code == 403
        assert resp.json()["detail"] == "需要管理员权限"

    async def test_anonymous_gets_401(self, app_client):
        resp = await app_client.get("/api/v1/users")
        assert resp.status_code in (401, 403)


class TestUserDirectory:
    async def test_directory_accessible_to_pm(self, app_client, pm_user, admin_user, db):
        from tests.conftest import seed_user

        inactive = await seed_user(db, "ghost_user", "developer")
        inactive.is_active = False
        await db.flush()
        token = await login_token(app_client, "pm1")
        resp = await app_client.get(
            "/api/v1/users/directory", headers=auth_header(token)
        )
        assert resp.status_code == 200
        body = resp.json()
        ids = {u["id"] for u in body}
        assert pm_user.id in ids and admin_user.id in ids
        assert inactive.id not in ids  # 停用用户不出现在目录
        assert all(set(u.keys()) == {"id", "display_name", "role"} for u in body)

    async def test_directory_requires_auth(self, app_client):
        resp = await app_client.get("/api/v1/users/directory")
        assert resp.status_code in (401, 403)


class TestCreateUser:
    async def test_create_success(self, app_client, admin_user):
        resp = await app_client.post(
            "/api/v1/users",
            json={
                "username": "dev1",
                "password": "dev-pass-123",
                "display_name": "研发一号",
                "role": "developer",
            },
            headers=await admin_headers(app_client),
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["username"] == "dev1"
        assert body["role"] == "developer"
        assert "password_hash" not in body

    async def test_created_user_can_login(self, app_client, admin_user):
        await app_client.post(
            "/api/v1/users",
            json={
                "username": "dev2",
                "password": "dev-pass-123",
                "display_name": "研发二号",
                "role": "developer",
            },
            headers=await admin_headers(app_client),
        )
        token = await login_token(app_client, "dev2", "dev-pass-123")
        assert token

    async def test_duplicate_username_409(self, app_client, admin_user):
        payload = {
            "username": "dup",
            "password": "dup-pass-123",
            "display_name": "重复",
            "role": "pm",
        }
        first = await app_client.post(
            "/api/v1/users", json=payload, headers=await admin_headers(app_client)
        )
        assert first.status_code == 201
        second = await app_client.post(
            "/api/v1/users", json=payload, headers=await admin_headers(app_client)
        )
        assert second.status_code == 409
        assert "已存在" in second.json()["detail"]

    async def test_invalid_role_422(self, app_client, admin_user):
        resp = await app_client.post(
            "/api/v1/users",
            json={
                "username": "bad",
                "password": "bad-pass-123",
                "display_name": "坏角色",
                "role": "boss",
            },
            headers=await admin_headers(app_client),
        )
        assert resp.status_code == 422

    async def test_short_password_422(self, app_client, admin_user):
        resp = await app_client.post(
            "/api/v1/users",
            json={
                "username": "shortpw",
                "password": "123",
                "display_name": "短密码",
                "role": "pm",
            },
            headers=await admin_headers(app_client),
        )
        assert resp.status_code == 422


class TestListUsers:
    async def test_list_all(self, app_client, admin_user, pm_user):
        resp = await app_client.get(
            "/api/v1/users", headers=await admin_headers(app_client)
        )
        assert resp.status_code == 200
        assert {u["username"] for u in resp.json()} >= {"admin1", "pm1"}

    async def test_filter_by_role(self, app_client, admin_user, pm_user):
        resp = await app_client.get(
            "/api/v1/users", params={"role": "pm"}, headers=await admin_headers(app_client)
        )
        assert resp.status_code == 200
        assert all(u["role"] == "pm" for u in resp.json())

    async def test_filter_by_active(self, app_client, admin_user, pm_user, db):
        pm_user.is_active = False
        await db.flush()
        resp = await app_client.get(
            "/api/v1/users",
            params={"is_active": "true"},
            headers=await admin_headers(app_client),
        )
        assert resp.status_code == 200
        assert all(u["is_active"] for u in resp.json())

    async def test_keyword_matches_username_or_display(self, app_client, admin_user):
        resp = await app_client.get(
            "/api/v1/users", params={"keyword": "admin"}, headers=await admin_headers(app_client)
        )
        assert resp.status_code == 200
        assert any(u["username"] == "admin1" for u in resp.json())


class TestUpdateUser:
    async def test_update_fields(self, app_client, admin_user, pm_user):
        resp = await app_client.patch(
            f"/api/v1/users/{pm_user.id}",
            json={"display_name": "新名字", "role": "tester", "is_active": False},
            headers=await admin_headers(app_client),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["display_name"] == "新名字"
        assert body["role"] == "tester"
        assert body["is_active"] is False

    async def test_update_nonexistent_404(self, app_client, admin_user):
        resp = await app_client.patch(
            "/api/v1/users/9999",
            json={"display_name": "谁"},
            headers=await admin_headers(app_client),
        )
        assert resp.status_code == 404

    async def test_partial_update_keeps_others(self, app_client, admin_user, pm_user):
        resp = await app_client.patch(
            f"/api/v1/users/{pm_user.id}",
            json={"display_name": "只改名字"},
            headers=await admin_headers(app_client),
        )
        assert resp.status_code == 200
        assert resp.json()["role"] == "pm"


class TestResetPassword:
    async def test_reset_then_login_with_new_password(self, app_client, admin_user, pm_user):
        resp = await app_client.post(
            f"/api/v1/users/{pm_user.id}/reset-password",
            json={"new_password": "brand-new-456"},
            headers=await admin_headers(app_client),
        )
        assert resp.status_code == 204
        token = await login_token(app_client, "pm1", "brand-new-456")
        assert token

    async def test_old_password_rejected_after_reset(self, app_client, admin_user, pm_user):
        await app_client.post(
            f"/api/v1/users/{pm_user.id}/reset-password",
            json={"new_password": "brand-new-456"},
            headers=await admin_headers(app_client),
        )
        resp = await app_client.post(
            "/api/v1/auth/login",
            json={"username": "pm1", "password": DEFAULT_PASSWORD},
        )
        assert resp.status_code == 401

    async def test_reset_nonexistent_404(self, app_client, admin_user):
        resp = await app_client.post(
            "/api/v1/users/9999/reset-password",
            json={"new_password": "whatever-123"},
            headers=await admin_headers(app_client),
        )
        assert resp.status_code == 404


class TestTransfer:
    async def test_transfer_moves_pm_and_assignees(
        self, app_client, admin_user, pm_user, db, requirement, stages
    ):
        # dev9 接收人；把一个环节负责人设为 pm1
        receiver = await seed_user(db, "dev9", "developer")
        stage = stages[0]
        stage.assignee_id = pm_user.id
        await db.flush()

        resp = await app_client.post(
            f"/api/v1/users/{pm_user.id}/transfer",
            json={"to_user_id": receiver.id},
            headers=await admin_headers(app_client),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["transferred_requirements"] == 1
        assert body["transferred_stages"] == 1

        req = await db.get(Requirement, requirement.id)
        assert req.responsible_pm_id == receiver.id
        refreshed = await db.get(RequirementStage, stage.id)
        assert refreshed.assignee_id == receiver.id

    async def test_transfer_to_self_409(self, app_client, admin_user, pm_user):
        resp = await app_client.post(
            f"/api/v1/users/{pm_user.id}/transfer",
            json={"to_user_id": pm_user.id},
            headers=await admin_headers(app_client),
        )
        assert resp.status_code == 409
        assert "不能转交给自己" in resp.json()["detail"]

    async def test_transfer_to_nonexistent_409(self, app_client, admin_user, pm_user):
        resp = await app_client.post(
            f"/api/v1/users/{pm_user.id}/transfer",
            json={"to_user_id": 424242},
            headers=await admin_headers(app_client),
        )
        assert resp.status_code == 409
        assert "不存在" in resp.json()["detail"]

    async def test_transfer_to_inactive_409(self, app_client, admin_user, pm_user, db):
        inactive = await seed_user(db, "ghost", "developer")
        inactive.is_active = False
        await db.flush()
        resp = await app_client.post(
            f"/api/v1/users/{pm_user.id}/transfer",
            json={"to_user_id": inactive.id},
            headers=await admin_headers(app_client),
        )
        assert resp.status_code == 409

    async def test_transfer_nonexistent_source_404(self, app_client, admin_user):
        resp = await app_client.post(
            "/api/v1/users/9999/transfer",
            json={"to_user_id": 1},
            headers=await admin_headers(app_client),
        )
        assert resp.status_code == 404
