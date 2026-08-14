"""认证路由（design.md 8.1）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.security import create_access_token, verify_password
from app.db import get_session
from app.models import User
from app.schemas import LoginIn, TokenOut, UserOut
from app.services.users import get_by_username

router = APIRouter(tags=["auth"])


@router.post("/auth/login", response_model=TokenOut)
async def login(body: LoginIn, session: AsyncSession = Depends(get_session)) -> TokenOut:
    user = await get_by_username(session, body.username)
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if not user.is_active:
        raise HTTPException(status_code=401, detail="账号已停用")
    return TokenOut(access_token=create_access_token(user.id, user.role))


@router.get("/auth/me", response_model=UserOut)
async def me(current: User = Depends(get_current_user)) -> UserOut:
    return UserOut.model_validate(current)
