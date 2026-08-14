"""用户管理服务（design.md 8.5、2.2 用户停用约定）。"""

from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models import Requirement, RequirementStage, User


class UserError(Exception):
    """用户操作业务错误（API 层映射为 409）。"""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


async def get_by_username(session: AsyncSession, username: str) -> User | None:
    result = await session.scalars(select(User).where(User.username == username))
    return result.first()


async def create_user(
    session: AsyncSession,
    *,
    username: str,
    password: str,
    display_name: str,
    role: str,
) -> User:
    if await get_by_username(session, username) is not None:
        raise UserError(f"用户名 {username} 已存在")
    user = User(
        username=username,
        password_hash=hash_password(password),
        display_name=display_name,
        role=role,
    )
    session.add(user)
    await session.flush()
    return user


async def update_user(
    session: AsyncSession,
    user: User,
    *,
    display_name: str | None = None,
    role: str | None = None,
    is_active: bool | None = None,
) -> User:
    if display_name is not None:
        user.display_name = display_name
    if role is not None:
        user.role = role
    if is_active is not None:
        user.is_active = is_active
    await session.flush()
    return user


async def reset_password(session: AsyncSession, user: User, new_password: str) -> None:
    user.password_hash = hash_password(new_password)
    await session.flush()


async def transfer_ownership(
    session: AsyncSession, from_user: User, to_user_id: int
) -> tuple[int, int]:
    """转交 from_user 名下的需求 PM 与环节负责人角色给 to_user（design.md 2.2）。

    返回 (转交需求数, 转交环节数)。停用用户前须先转交。
    """
    to_user = await session.get(User, to_user_id)
    if to_user is None:
        raise UserError(f"目标用户 {to_user_id} 不存在")
    if to_user.id == from_user.id:
        raise UserError("不能转交给自己")
    if not to_user.is_active:
        raise UserError("目标用户已停用，不能接收转交")

    req_result = await session.execute(
        update(Requirement)
        .where(Requirement.responsible_pm_id == from_user.id)
        .values(responsible_pm_id=to_user.id)
    )
    stage_result = await session.execute(
        update(RequirementStage)
        .where(RequirementStage.assignee_id == from_user.id)
        .values(assignee_id=to_user.id)
    )
    return req_result.rowcount, stage_result.rowcount


async def list_users(
    session: AsyncSession,
    *,
    role: str | None = None,
    is_active: bool | None = None,
    keyword: str | None = None,
) -> list[User]:
    """用户列表，支持 role / is_active / keyword（用户名或显示名模糊匹配）。"""
    stmt = select(User).order_by(User.id)
    if role is not None:
        stmt = stmt.where(User.role == role)
    if is_active is not None:
        stmt = stmt.where(User.is_active == is_active)
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(
            User.username.like(like) | User.display_name.like(like)
        )
    return list((await session.scalars(stmt)).all())
