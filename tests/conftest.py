"""测试夹具：内存 SQLite（StaticPool），每个用例独立建库。"""

from __future__ import annotations

import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.enums import STAGE_SEQ, StageStatus
from app.models import Requirement, RequirementStage, User


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session = async_sessionmaker(engine, expire_on_commit=False)()
    yield session
    await session.close()
    await engine.dispose()


@pytest_asyncio.fixture
async def pm_user(db) -> User:
    user = User(username="pm1", password_hash="x", display_name="PM一号", role="pm")
    db.add(user)
    await db.flush()
    return user


@pytest_asyncio.fixture
async def requirement(db, pm_user) -> Requirement:
    req = Requirement(title="测试需求", responsible_pm_id=pm_user.id)
    db.add(req)
    await db.flush()
    db.add_all(
        RequirementStage(
            requirement_id=req.id,
            stage_type=st.value,
            seq=seq,
            status=StageStatus.NOT_STARTED.value,
        )
        for st, seq in STAGE_SEQ.items()
    )
    await db.flush()
    return req


@pytest_asyncio.fixture
async def stages(db, requirement) -> list[RequirementStage]:
    result = await db.scalars(
        select(RequirementStage)
        .where(RequirementStage.requirement_id == requirement.id)
        .order_by(RequirementStage.seq)
    )
    return list(result)
