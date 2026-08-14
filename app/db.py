"""异步数据库引擎与会话（SQLite + aiosqlite）。"""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings


class Base(DeclarativeBase):
    """所有 ORM 模型的基类。"""


def create_engine(url: str) -> AsyncEngine:
    """按 URL 创建异步引擎。"""
    return create_async_engine(url, echo=False)


engine: AsyncEngine = create_engine(settings.database_url)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI 依赖：请求级会话。"""
    async with SessionLocal() as session:
        yield session
