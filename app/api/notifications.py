"""通知中心路由（design.md 8.7）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db import get_session
from app.models import Notification, User

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("")
async def list_notifications(
    unread_only: bool = False,
    page: int = 1,
    page_size: int = 20,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> dict:
    """我的通知列表（仅本人可见，按时间倒序）。"""
    stmt = select(Notification).where(Notification.user_id == user.id)
    if unread_only:
        stmt = stmt.where(Notification.is_read.is_(False))
    total = (
        await session.execute(select(func.count()).select_from(stmt.subquery()))
    ).scalar_one()
    stmt = (
        stmt.order_by(Notification.created_at.desc(), Notification.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = list((await session.scalars(stmt)).all())
    return {
        "items": [
            {
                "id": n.id,
                "type": n.type,
                "title": n.title,
                "content": n.content,
                "requirement_id": n.requirement_id,
                "stage_id": n.stage_id,
                "is_read": n.is_read,
                "created_at": n.created_at.isoformat() + "+08:00",
            }
            for n in items
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/unread-count")
async def unread_count(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> dict:
    """未读数（前端轮询，design.md 4.2）。"""
    count = (
        await session.execute(
            select(func.count())
            .select_from(Notification)
            .where(Notification.user_id == user.id, Notification.is_read.is_(False))
        )
    ).scalar_one()
    return {"unread": count}


@router.post("/{notification_id}/read", status_code=204)
async def mark_read(
    notification_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> None:
    """单条已读（仅接收人本人可操作，design.md 8.7）。"""
    notification = await session.get(Notification, notification_id)
    if notification is None:
        raise HTTPException(status_code=404, detail="通知不存在")
    if notification.user_id != user.id:
        raise HTTPException(status_code=403, detail="只能操作自己的通知")
    notification.is_read = True
    await session.commit()


@router.post("/read-all", status_code=204)
async def mark_all_read(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> None:
    """全部已读。"""
    notifications = list(
        (
            await session.scalars(
                select(Notification).where(
                    Notification.user_id == user.id, Notification.is_read.is_(False)
                )
            )
        ).all()
    )
    for n in notifications:
        n.is_read = True
    await session.commit()
