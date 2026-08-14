"""db 模块：引擎/会话基础能力。"""

from __future__ import annotations

import app.db as db_module
from app.db import Base, create_engine, get_session


async def test_get_session_yields_session(monkeypatch):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import StaticPool

    engine = create_async_engine(
        "sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    monkeypatch.setattr(db_module, "SessionLocal", async_sessionmaker(engine))

    agen = get_session()
    session = await agen.__anext__()
    assert session is not None
    await agen.aclose()
    await engine.dispose()


async def test_create_engine_returns_async_engine():
    engine = create_engine("sqlite+aiosqlite:///:memory:")
    assert engine is not None
    await engine.dispose()


def test_base_is_declarative():
    # 主要表都注册到 metadata（模型完整性冒烟）
    expected = {
        "users", "projects", "requirements", "requirement_stages",
        "stage_time_change_logs", "stage_revert_logs", "notifications",
    }
    assert expected.issubset(set(Base.metadata.tables.keys()))
