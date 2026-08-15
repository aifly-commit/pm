"""APScheduler 调度器（design.md 4.2）。

- AsyncIOScheduler 随 FastAPI 进程启动（main.lifespan），每 30 分钟扫描一次；
- 生产必须单 worker（--workers 1），避免多进程重复扫描/重复通知；
- 扫描逻辑在 services.notifications.run_scan，可注入时钟独立测试。
"""

from __future__ import annotations

import logging
from typing import Callable

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.services.notifications import run_scan
from app.services.requirements import now_sh

logger = logging.getLogger("pm.scheduler")

SCAN_INTERVAL_MINUTES = 30
JOB_ID = "pm_notification_scan"


def create_scheduler(session_factory: Callable) -> AsyncIOScheduler:
    """构建调度器并注册扫描任务（不启动；由 main.lifespan start/stop）。"""
    scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")

    async def scan_job() -> None:
        async with session_factory() as session:
            report = await run_scan(session, now_sh())
            await session.commit()
        logger.info(
            "扫描完成：逾期提醒 %d 条，临期提醒 %d 条，状态刷新需求 %d 个",
            report.overdue_notifications,
            report.due_soon_notifications,
            len(report.requirements_refreshed),
        )

    scheduler.add_job(
        scan_job,
        trigger="interval",
        minutes=SCAN_INTERVAL_MINUTES,
        id=JOB_ID,
        max_instances=1,  # 同一时刻最多一个实例在跑（上一轮未结束不叠加）
        coalesce=True,  # 积压的触发合并为一次
        replace_existing=True,
    )
    return scheduler
