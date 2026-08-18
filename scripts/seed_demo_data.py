#!/usr/bin/env python3
"""重置本地业务测试数据，并生成一批可用于页面验证的示例数据。

仅允许作用于默认本地 pm.db；用户账号会保留，项目、需求、环节、日志和通知会清空后重建。
运行：.venv/bin/python scripts/seed_demo_data.py --reset
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta
from pathlib import Path

# 支持从项目根目录直接执行 `python scripts/seed_demo_data.py --reset`。
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import delete, select

from app.core.config import TZ, settings
from app.db import SessionLocal
from app.enums import STAGE_SEQ, StageStatus, StageType
from app.models import (
    Notification,
    Project,
    Requirement,
    RequirementModificationLog,
    RequirementStage,
    RequirementStatusLog,
    StageRevertLog,
    StageTimeChangeLog,
    User,
)
from app.services.requirements import create_requirement, get_stages


NOW = datetime.now(TZ).replace(tzinfo=None, microsecond=0)


def stage_plans(start: datetime, developer_id: int, tester_id: int) -> list[dict]:
    """生成满足顺序约束的七环节排期。"""
    windows = {
        StageType.RESEARCH: (0, 3),
        StageType.REVIEW: (3, 5),
        StageType.BACKEND_DEV: (5, 13),
        StageType.FRONTEND_DEV: (13, 20),
        StageType.API_DEV: (13, 19),
        StageType.TESTING: (20, 24),
        StageType.RELEASE: (24, 25),
    }
    assignees = {
        StageType.BACKEND_DEV: developer_id,
        StageType.FRONTEND_DEV: developer_id,
        StageType.API_DEV: developer_id,
        StageType.TESTING: tester_id,
    }
    return [
        {
            "stage_type": stage_type.value,
            "planned_start": start + timedelta(days=windows[stage_type][0]),
            "planned_end": start + timedelta(days=windows[stage_type][1]),
            "assignee_id": assignees.get(stage_type),
        }
        for stage_type in STAGE_SEQ
    ]


async def set_flow(
    session,
    requirement: Requirement,
    *,
    completed: set[int],
    in_progress: set[int],
    status: str,
    paused: bool = False,
    manual_delayed: bool = False,
) -> list[RequirementStage]:
    """为示例数据写入与需求状态相符的实际环节状态。"""
    stages = await get_stages(session, requirement.id)
    for stage in stages:
        if stage.seq in completed:
            stage.status = StageStatus.DONE.value
            stage.actual_start = stage.planned_start or NOW - timedelta(days=10)
            stage.actual_end = stage.planned_end or NOW - timedelta(days=8)
        elif stage.seq in in_progress:
            stage.status = StageStatus.IN_PROGRESS.value
            stage.actual_start = stage.planned_start or NOW - timedelta(days=2)

    requirement.status = status
    requirement.manual_delayed = manual_delayed
    requirement.manual_delay_reason = "外部依赖联调延期" if manual_delayed else None
    if paused:
        requirement.paused_from = "in_progress"
        requirement.paused_at = NOW - timedelta(days=3)
    if status != "not_started":
        session.add(
            RequirementStatusLog(
                requirement_id=requirement.id,
                from_status="not_started",
                to_status=status,
                changed_by=requirement.responsible_pm_id,
            )
        )
    return stages


async def clear_business_data(session) -> None:
    """按外键依赖逆序清理业务测试数据，保留 users 用户账号。"""
    for model in (
        Notification,
        RequirementModificationLog,
        RequirementStatusLog,
        StageTimeChangeLog,
        StageRevertLog,
        RequirementStage,
        Requirement,
        Project,
    ):
        await session.execute(delete(model))
    await session.commit()


async def seed() -> None:
    if settings.database_url != "sqlite+aiosqlite:///./pm.db":
        raise RuntimeError("仅允许重置默认本地数据库 sqlite+aiosqlite:///./pm.db")

    async with SessionLocal() as session:
        users = {
            user.username: user
            for user in (await session.scalars(select(User))).all()
        }
        required_users = {"lisi", "wangwu", "zhaoliu"}
        missing = required_users - users.keys()
        if missing:
            raise RuntimeError(f"缺少示例数据所需用户：{', '.join(sorted(missing))}")

        await clear_business_data(session)
        pm, developer, tester = users["lisi"], users["wangwu"], users["zhaoliu"]

        projects = [
            Project(
                name="核心数据库体验优化",
                description="围绕查询性能、运维可观测性与高可用能力的季度专项。",
                contacts=[{"name": "周晓", "email": "zhou@example.com"}],
                progress_note="研发和测试按计划推进。",
                progress_percent=58,
                status="in_progress",
                planned_start=NOW - timedelta(days=35),
                planned_end=NOW + timedelta(days=35),
                owner_id=pm.id,
            ),
            Project(
                name="智能数据服务增强",
                description="推进 AI 辅助开发与数据服务能力建设。",
                contacts=[{"name": "陈岚", "im": "chenlan"}],
                progress_note="等待需求评审排期。",
                progress_percent=20,
                status="not_started",
                planned_start=NOW + timedelta(days=5),
                planned_end=NOW + timedelta(days=70),
                owner_id=pm.id,
            ),
            Project(
                name="稳定性与合规专项",
                description="覆盖告警治理、权限审计和容灾演练。",
                contacts=[{"name": "孙冉", "phone": "13800000000"}],
                progress_note="部分工作因外部依赖暂停。",
                progress_percent=46,
                status="paused",
                planned_start=NOW - timedelta(days=50),
                planned_end=NOW + timedelta(days=20),
                owner_id=pm.id,
            ),
        ]
        session.add_all(projects)
        await session.flush()

        specs = [
            ("MySQL 慢查询治理", "MySQL", "基本能力", "P1", projects[0].id, -18, {1, 2}, {3}, "in_progress", False, False),
            ("TiDB 分区表维护优化", "TiDB", "重点能力", "P0", projects[0].id, -38, {1, 2}, {3}, "delayed", False, False),
            ("Redis 缓存预热能力", "Redis", "基本能力", "P2", None, 8, set(), set(), "not_started", False, False),
            ("DataAgent 智能字段推荐", "DataAgent", "重点能力", "P1", projects[1].id, -16, {1, 2, 3}, {4, 5}, "in_progress", False, False),
            ("PostgreSQL 逻辑复制监控", "PostgreSQL", "基本能力", "P1", projects[0].id, -42, set(range(1, 8)), set(), "done", False, False),
            ("图服务路径查询性能提升", "图服务", "重点能力", "P1", projects[2].id, -25, {1, 2}, {3}, "paused", True, False),
            ("ClickHouse 查询审计", "ClickHouse", "基本能力", "P2", projects[2].id, 2, set(), set(), "not_started", False, False),
            ("Milvus 索引构建提速", "Milvus", "重点能力", "P0", projects[1].id, -14, {1, 2, 3}, {4, 5}, "delayed", False, True),
            ("RabbitMQ 消息堆积告警", "RabbitMQ", "基本能力", "P0", projects[2].id, -31, {1, 2}, {3}, "delayed", False, False),
            ("DMP 人群包导出增强", "DMP", "基本能力", "P3", None, 12, set(), set(), "not_started", False, False),
            ("MongoDB 慢日志可视化", "MongoDB", "重点能力", "P2", projects[0].id, -12, {1, 2, 3}, {4, 5}, "in_progress", False, False),
            ("横向权限审计能力", "横向", "重点能力", "P1", projects[2].id, -28, {1, 2}, {3}, "paused", True, False),
        ]

        seeded: list[tuple[Requirement, list[RequirementStage]]] = []
        for title, product_line, category, priority, project_id, offset, done, active, status, paused, manual_delayed in specs:
            requirement = await create_requirement(
                session,
                title=title,
                description=f"用于本地界面验证的示例需求：{title}。",
                product_line=product_line,
                category=category,
                source="示例数据",
                priority=priority,
                project_id=project_id,
                responsible_pm_id=pm.id,
                stage_plans=stage_plans(NOW + timedelta(days=offset), developer.id, tester.id),
            )
            stages = await set_flow(
                session,
                requirement,
                completed=done,
                in_progress=active,
                status=status,
                paused=paused,
                manual_delayed=manual_delayed,
            )
            seeded.append((requirement, stages))

        delayed_requirement, delayed_stages = seeded[1]
        session.add_all(
            [
                Notification(
                    user_id=pm.id,
                    type="overdue",
                    title="需求环节已逾期",
                    content=f"需求「{delayed_requirement.title}」的平台开发环节已逾期。",
                    requirement_id=delayed_requirement.id,
                    stage_id=delayed_stages[2].id,
                    dedupe_key=f"seed:{delayed_stages[2].id}:overdue",
                ),
                Notification(
                    user_id=developer.id,
                    type="status_changed",
                    title="需求状态已更新",
                    content="请关注分配给你的在途研发任务。",
                    requirement_id=seeded[3][0].id,
                    stage_id=seeded[3][1][3].id,
                ),
                Notification(
                    user_id=tester.id,
                    type="due_soon",
                    title="测试环节即将开始",
                    content="请提前安排测试资源。",
                    requirement_id=seeded[10][0].id,
                    stage_id=seeded[10][1][5].id,
                    dedupe_key=f"seed:{seeded[10][1][5].id}:due-soon",
                ),
            ]
        )
        await session.commit()
        print(f"示例数据已生成：{len(projects)} 个项目、{len(seeded)} 条需求、{len(seeded) * 7} 个环节。")


def main() -> None:
    if sys.argv[1:] != ["--reset"]:
        raise SystemExit("用法：.venv/bin/python scripts/seed_demo_data.py --reset")
    asyncio.run(seed())


if __name__ == "__main__":
    main()
