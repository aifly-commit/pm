"""security 模块：密码哈希与 JWT。"""

from __future__ import annotations

from datetime import timedelta

import pytest
from jose import jwt

from app.core.config import settings
from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    token_expiry,
    verify_password,
)


class TestPassword:
    def test_hash_and_verify_roundtrip(self):
        hashed = hash_password("s3cret-Pass")
        assert hashed != "s3cret-Pass"
        assert verify_password("s3cret-Pass", hashed)

    def test_verify_wrong_password(self):
        hashed = hash_password("s3cret-Pass")
        assert not verify_password("wrong", hashed)

    def test_hash_salts(self):
        assert hash_password("same") != hash_password("same")


class TestAccessToken:
    def test_roundtrip(self):
        token = create_access_token(42, "pm")
        payload = decode_access_token(token)
        assert payload is not None
        assert payload["sub"] == "42"
        assert payload["role"] == "pm"

    def test_expired_token_returns_none(self):
        # 直接签一个已过期的 token 验证解码拒绝
        expired = jwt.encode(
            {"sub": "1", "role": "pm", "exp": 1}, settings.secret_key, algorithm="HS256"
        )
        assert decode_access_token(expired) is None

    def test_garbage_token_returns_none(self):
        assert decode_access_token("not-a-jwt") is None

    def test_token_missing_sub_returns_none(self):
        no_sub = jwt.encode(
            {"role": "pm"}, settings.secret_key, algorithm="HS256"
        )
        assert decode_access_token(no_sub) is None

    def test_wrong_signature_returns_none(self):
        forged = jwt.encode({"sub": "1"}, "other-key", algorithm="HS256")
        assert decode_access_token(forged) is None

    def test_token_expiry_reads_exp(self):
        token = create_access_token(7, "admin")
        exp = token_expiry(token)
        assert exp is not None
        # 有效期 12 小时（允许 1 分钟误差）
        from app.core.config import TZ
        from datetime import datetime

        remaining = exp - datetime.now(TZ)
        assert timedelta(hours=11, minutes=59) < remaining <= timedelta(hours=12)

    def test_token_expiry_invalid(self):
        assert token_expiry("garbage") is None
