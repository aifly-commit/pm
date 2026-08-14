"""测试夹具：内存 SQLite（StaticPool），每个用例独立建库。"""

from __future__ import annotations

import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.security import hash_password
from app.db import Base, get_session
from app.enums import STAGE_SEQ, StageStatus
from app.models import Requirement, RequirementStage, User

DEFAULT_PASSWORD = "pass-123456"


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


async def seed_user(db, username: str, role: str, password: str = DEFAULT_PASSWORD) -> User:
    """直接入库创建用户（不走路由，供夹具/断言用）。"""
    user = User(
        username=username,
        password_hash=hash_password(password),
        display_name=f"{username}-显示名",
        role=role,
    )
    db.add(user)
    await db.flush()
    return user


async def login_token(client, username: str, password: str = DEFAULT_PASSWORD) -> str:
    resp = await client.post(
        "/api/v1/auth/login", json={"username": username, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def admin_user(db) -> User:
    return await seed_user(db, "admin1", "admin")


@pytest_asyncio.fixture
async def pm_user(db) -> User:
    return await seed_user(db, "pm1", "pm")


@pytest_asyncio.fixture
async def app_client(db):
    """绑定测试库的 httpx 客户端（覆盖 get_session 依赖）。"""
    import httpx

    from app.main import app

    async def override_session():
        yield db

    app.dependency_overrides[get_session] = override_session
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


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
