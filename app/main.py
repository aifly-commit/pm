"""FastAPI 应用入口。

启动（必须单 worker，design.md 4.2）：
    uvicorn app.main:app --reload --workers 1

初始化管理员（首次部署）：
    python -m app.main create-admin <用户名> <密码> <显示名>
"""

from __future__ import annotations

import asyncio
import sys

from fastapi import FastAPI

from app.api import auth, users

app = FastAPI(title="pm — 需求管理与项目管理平台", version="0.1.0")

API_PREFIX = "/api/v1"
app.include_router(auth.router, prefix=API_PREFIX)
app.include_router(users.router, prefix=API_PREFIX)


@app.get(f"{API_PREFIX}/health")
async def health() -> dict:
    return {"status": "ok"}


async def _create_admin(username: str, password: str, display_name: str) -> None:
    from app.db import SessionLocal
    from app.services.users import UserError, create_user

    async with SessionLocal() as session:
        try:
            user = await create_user(
                session,
                username=username,
                password=password,
                display_name=display_name,
                role="admin",
            )
        except UserError as e:
            print(f"创建失败：{e.message}")
            sys.exit(1)
        await session.commit()
        print(f"管理员已创建：{user.username} (id={user.id})")


def _cli() -> None:
    if len(sys.argv) >= 2 and sys.argv[1] == "create-admin":
        if len(sys.argv) != 5:
            print("用法：python -m app.main create-admin <用户名> <密码> <显示名>")
            sys.exit(2)
        asyncio.run(_create_admin(*sys.argv[2:]))
    else:
        print(__doc__)


if __name__ == "__main__":
    _cli()
