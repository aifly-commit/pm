"""用户管理路由（仅 Admin，design.md 8.5）+ 用户目录（全员可读，指派下拉用）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_admin
from app.db import get_session
from app.models import User
from app.schemas import ResetPasswordIn, TransferIn, UserCreate, UserOut, UserUpdate
from app.services import users as user_service
from app.services.users import UserError

router = APIRouter(prefix="/users", tags=["users"], dependencies=[Depends(require_admin)])

# 用户目录：任何登录用户可访问（前端"环节负责人/PM"下拉数据源）
directory_router = APIRouter(prefix="/users", tags=["users"])


@directory_router.get("/directory")
async def user_directory(
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(get_current_user),
) -> list[dict]:
    """启用用户的基础字段（id/显示名/角色）。"""
    rows = await user_service.list_users(session, is_active=True)
    return [{"id": u.id, "display_name": u.display_name, "role": u.role} for u in rows]


@router.get("", response_model=list[UserOut])
async def list_users(
    role: str | None = None,
    is_active: bool | None = None,
    keyword: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> list[UserOut]:
    rows = await user_service.list_users(
        session, role=role, is_active=is_active, keyword=keyword
    )
    return [UserOut.model_validate(u) for u in rows]


@router.post("", response_model=UserOut, status_code=201)
async def create_user(
    body: UserCreate, session: AsyncSession = Depends(get_session)
) -> UserOut:
    try:
        user = await user_service.create_user(
            session,
            username=body.username,
            password=body.password,
            display_name=body.display_name,
            role=body.role.value,
        )
    except UserError as e:
        raise HTTPException(status_code=409, detail=e.message)
    await session.commit()
    return UserOut.model_validate(user)


@router.patch("/{user_id}", response_model=UserOut)
async def update_user(
    user_id: int,
    body: UserUpdate,
    session: AsyncSession = Depends(get_session),
) -> UserOut:
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    await user_service.update_user(
        session,
        user,
        display_name=body.display_name,
        role=body.role.value if body.role else None,
        is_active=body.is_active,
    )
    await session.commit()
    return UserOut.model_validate(user)


@router.post("/{user_id}/reset-password", status_code=204)
async def reset_password(
    user_id: int,
    body: ResetPasswordIn,
    session: AsyncSession = Depends(get_session),
) -> None:
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    await user_service.reset_password(session, user, body.new_password)
    await session.commit()


@router.post("/{user_id}/transfer")
async def transfer(
    user_id: int,
    body: TransferIn,
    session: AsyncSession = Depends(get_session),
) -> dict:
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    try:
        req_count, stage_count = await user_service.transfer_ownership(
            session, user, body.to_user_id
        )
    except UserError as e:
        raise HTTPException(status_code=409, detail=e.message)
    await session.commit()
    return {"transferred_requirements": req_count, "transferred_stages": stage_count}
