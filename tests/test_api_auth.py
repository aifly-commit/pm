"""认证 API（design.md 8.1）。"""

from __future__ import annotations

from tests.conftest import DEFAULT_PASSWORD, auth_header, login_token


class TestLogin:
    async def test_login_success(self, app_client, pm_user):
        resp = await app_client.post(
            "/api/v1/auth/login",
            json={"username": "pm1", "password": DEFAULT_PASSWORD},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["token_type"] == "bearer"
        assert body["access_token"]

    async def test_login_wrong_password(self, app_client, pm_user):
        resp = await app_client.post(
            "/api/v1/auth/login", json={"username": "pm1", "password": "wrong-pass"}
        )
        assert resp.status_code == 401
        assert resp.json()["detail"] == "用户名或密码错误"

    async def test_login_unknown_user(self, app_client):
        resp = await app_client.post(
            "/api/v1/auth/login", json={"username": "nobody", "password": "whatever"}
        )
        assert resp.status_code == 401

    async def test_login_inactive_user_rejected(self, app_client, pm_user, db):
        pm_user.is_active = False
        await db.flush()
        resp = await app_client.post(
            "/api/v1/auth/login",
            json={"username": "pm1", "password": DEFAULT_PASSWORD},
        )
        assert resp.status_code == 401
        assert resp.json()["detail"] == "账号已停用"

    async def test_login_empty_body_rejected(self, app_client):
        resp = await app_client.post("/api/v1/auth/login", json={})
        assert resp.status_code == 422


class TestMe:
    async def test_me_returns_current_user(self, app_client, pm_user):
        token = await login_token(app_client, "pm1")
        resp = await app_client.get("/api/v1/auth/me", headers=auth_header(token))
        assert resp.status_code == 200
        body = resp.json()
        assert body["username"] == "pm1"
        assert body["role"] == "pm"
        assert "password_hash" not in body

    async def test_me_without_token(self, app_client):
        resp = await app_client.get("/api/v1/auth/me")
        assert resp.status_code == 401

    async def test_me_with_garbage_token(self, app_client):
        resp = await app_client.get(
            "/api/v1/auth/me", headers=auth_header("garbage.token.here")
        )
        assert resp.status_code == 401

    async def test_me_with_non_numeric_sub_token(self, app_client):
        # 签发 sub 非数字的伪 token（绕过签发函数，直接构造）
        from jose import jwt as jose_jwt

        from app.core.config import settings
        token = jose_jwt.encode(
            {"sub": "not-a-number", "role": "pm"}, settings.secret_key, algorithm="HS256"
        )
        resp = await app_client.get("/api/v1/auth/me", headers=auth_header(token))
        assert resp.status_code == 401

    async def test_me_with_deleted_user_token(self, app_client, pm_user, db):
        token = await login_token(app_client, "pm1")
        await db.delete(pm_user)
        await db.flush()
        resp = await app_client.get("/api/v1/auth/me", headers=auth_header(token))
        assert resp.status_code == 401

    async def test_me_with_inactive_user_token(self, app_client, pm_user, db):
        token = await login_token(app_client, "pm1")
        pm_user.is_active = False
        await db.flush()
        resp = await app_client.get("/api/v1/auth/me", headers=auth_header(token))
        assert resp.status_code == 401


class TestHealth:
    async def test_health(self, app_client):
        resp = await app_client.get("/api/v1/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}
