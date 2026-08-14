"""密码哈希（bcrypt）与 JWT 签发/校验（design.md 2.2、8.8）。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import ACCESS_TOKEN_EXPIRE_HOURS, TZ, settings

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

ALGORITHM = settings.algorithm


def hash_password(raw: str) -> str:
    """明文密码 → bcrypt 哈希。"""
    return _pwd_context.hash(raw)


def verify_password(raw: str, hashed: str) -> bool:
    """校验明文密码与存储的哈希是否匹配。"""
    return _pwd_context.verify(raw, hashed)


def create_access_token(user_id: int, role: str) -> str:
    """签发 access_token，payload 含 user_id 与 role，有效期 12 小时。"""
    expire = datetime.now(TZ) + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
    payload = {"sub": str(user_id), "role": role, "exp": expire}
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict | None:
    """解码并校验 token；无效或过期返回 None。"""
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
    except JWTError:
        return None
    if "sub" not in payload:
        return None
    return payload


def token_expiry(token: str) -> datetime | None:
    """读取 token 的 exp（转换为 Asia/Shanghai 时区）；无效返回 None。"""
    payload = decode_access_token(token)
    if payload is None or "exp" not in payload:
        return None
    exp = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
    return exp.astimezone(TZ)
