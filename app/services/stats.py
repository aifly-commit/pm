"""统计服务（design.md 6.1 / 6.2 / 6.3）。

口径要点：
- 延期判定 / 逾期天数：与 3.3 同源（is_stage_overdue）；
- 本周/本月完成：上线环节实际结束时间落在周期内；
- 本周期新产生延期：状态日志 to_status=delayed 落在周期内，按需求去重；
- 当前延期数 / 延期率：报表查询时刻的实时快照（当前延期 / 未完成总数）；
- 预估调整：仅人工调整（auto_generated=FALSE），顺延（new>old）与提前（new<old）分开，
  Top 延期原因只统计顺延调整；暂停顺延（auto）排除。
- 全部查询时实时计算，无预聚合表。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.enums import StageType
from app.models import (
    Project,
    Requirement,
    RequirementStage,
    RequirementStatusLog,
    StageTimeChangeLog,
)
from app.services.requirements import STAGE_LABEL, current_stage_types, now_sh
from app.services.state_machine import is_stage_overdue

ALL_STAGE_TYPES = [t.value for t in StageType]


# ---------------------------------------------------------------- 周期计算

def week_bounds(d: date) -> tuple[datetime, datetime]:
    """自然周：周一 00:00 ~ 下周一 00:00（design.md 6.1）。"""
    monday = d - timedelta(days=d.weekday())
    start = datetime(monday.year, monday.month, monday.day)
    return start, start + timedelta(days=7)


def month_bounds(ym: str) -> tuple[datetime, datetime]:
    """自然月：'YYYY-MM'。"""
    year, month = ym.split("-")
    start = datetime(int(year), int(month), 1)
    if month == "12":
        nxt = datetime(int(year) + 1, 1, 1)
    else:
        nxt = datetime(int(year), int(month) + 1, 1)
    return start, nxt


def weeks_between(start: datetime, end: datetime) -> list[datetime]:
    """覆盖 [start, end) 的自然周（周一 00:00 起点，与周报同口径，可跨月）。"""
    first_monday = start - timedelta(days=start.weekday())
    weeks = []
    ws = first_monday
    while ws < end:
        weeks.append(ws)
        ws += timedelta(days=7)
    return weeks


# ---------------------------------------------------------------- 数据加载

async def _load_all(session: AsyncSession) -> list[tuple[Requirement, list[RequirementStage]]]:
    rows = list(
        (
            await session.scalars(
                select(Requirement).options(selectinload(Requirement.stages))
            )
        ).all()
    )
    return [(r, sorted(r.stages, key=lambda s: s.seq)) for r in rows]


def _overdue_items(stages: list[RequirementStage], now: datetime) -> list[dict]:
    """构成逾期的环节明细（类型、标签、逾期天数）。"""
    items = []
    for s in stages:
        if is_stage_overdue(s, now):
            items.append(
                {
                    "stage_id": s.id,
                    "stage_type": s.stage_type,
                    "stage_label": STAGE_LABEL.get(s.stage_type, s.stage_type),
                    "planned_end": s.planned_end,
                    "overdue_days": (now.date() - s.planned_end.date()).days,
                    "last_delay_reason": s.last_delay_reason,
                }
            )
    return items


# ---------------------------------------------------------------- 总览（6.1）

async def overview(session: AsyncSession, now: datetime | None = None) -> dict:
    now = now or now_sh()
    pairs = await _load_all(session)

    status_distribution = {
        key: 0 for key in ("not_started", "in_progress", "delayed", "paused", "done")
    }
    stage_distribution = {t: 0 for t in ALL_STAGE_TYPES}
    delayed_list = []
    for req, stages in pairs:
        status_distribution[req.status] = status_distribution.get(req.status, 0) + 1
        for st in current_stage_types(stages):
            stage_distribution[st] = stage_distribution.get(st, 0) + 1
        if req.status == "delayed":
            overdue = _overdue_items(stages, now)
            delayed_list.append(
                {
                    "requirement_id": req.id,
                    "title": req.title,
                    "responsible_pm_id": req.responsible_pm_id,
                    "manual_delayed": req.manual_delayed,
                    "manual_delay_reason": req.manual_delay_reason,
                    "overdue_stages": overdue,
                }
            )
    return {
        "status_distribution": status_distribution,
        "stage_distribution": stage_distribution,
        "delayed_list": delayed_list,
    }


# ---------------------------------------------------------------- 需求周期报表（6.1 周/月）

async def _adjustment_stats(
    session: AsyncSession, start: datetime, end: datetime
) -> dict:
    logs = list(
        (
            await session.scalars(
                select(StageTimeChangeLog).where(
                    StageTimeChangeLog.created_at >= start,
                    StageTimeChangeLog.created_at < end,
                    StageTimeChangeLog.auto_generated.is_(False),
                )
            )
        ).all()
    )
    postponed = [l for l in logs if l.new_value > l.old_value]
    advanced = [l for l in logs if l.new_value < l.old_value]
    reason_count: dict[str, int] = {}
    for l in postponed:
        reason_count[l.reason] = reason_count.get(l.reason, 0) + 1
    top_reasons = sorted(reason_count.items(), key=lambda kv: -kv[1])[:5]
    return {
        "postponed_count": len(postponed),
        "advanced_count": len(advanced),
        "top_delay_reasons": [{"reason": r, "count": c} for r, c in top_reasons],
    }


async def _new_delayed_ids(
    session: AsyncSession, start: datetime, end: datetime
) -> list[int]:
    """周期内新产生延期（按需求去重，design.md 6.1）。"""
    rows = list(
        (
            await session.scalars(
                select(RequirementStatusLog.requirement_id)
                .where(
                    RequirementStatusLog.to_status == "delayed",
                    RequirementStatusLog.created_at >= start,
                    RequirementStatusLog.created_at < end,
                )
                .distinct()
            )
        ).all()
    )
    return rows


async def _completed_ids(
    session: AsyncSession, start: datetime, end: datetime
) -> list[int]:
    """周期内完成：上线环节 actual_end 落在周期内（design.md 6.3）。"""
    rows = list(
        (
            await session.scalars(
                select(RequirementStage.requirement_id)
                .where(
                    RequirementStage.stage_type == StageType.RELEASE.value,
                    RequirementStage.actual_end >= start,
                    RequirementStage.actual_end < end,
                )
                .distinct()
            )
        ).all()
    )
    return rows


async def requirement_report(
    session: AsyncSession, start: datetime, end: datetime, now: datetime | None = None
) -> dict:
    now = now or now_sh()
    pairs = await _load_all(session)

    new_count = sum(1 for r, _ in pairs if start <= r.created_at < end)
    completed_ids = await _completed_ids(session, start, end)
    new_delayed_ids = await _new_delayed_ids(session, start, end)

    current_delayed = sum(1 for r, _ in pairs if r.status == "delayed")
    unfinished = sum(
        1 for r, _ in pairs if r.status in ("not_started", "in_progress", "delayed")
    )
    delay_rate = round(current_delayed / unfinished, 4) if unfinished else 0.0

    return {
        "period_start": start,
        "period_end": end,
        "new_count": new_count,
        "completed_count": len(completed_ids),
        "new_delayed_count": len(new_delayed_ids),
        "current_delayed_count": current_delayed,
        "unfinished_count": unfinished,
        "delay_rate": delay_rate,
        **await _adjustment_stats(session, start, end),
    }


async def requirement_monthly(
    session: AsyncSession, start: datetime, end: datetime, now: datetime | None = None
) -> dict:
    """月报：周期口径同周报 + 每周趋势三条曲线（新增/完成/新产生延期）。"""
    report = await requirement_report(session, start, end, now)
    trend = []
    for ws in weeks_between(start, end):
        we = ws + timedelta(days=7)
        completed = await _completed_ids(session, ws, we)
        new_delayed = await _new_delayed_ids(session, ws, we)
        pairs = await _load_all(session)
        new = sum(1 for r, _ in pairs if ws <= r.created_at < we)
        trend.append(
            {
                "week_start": ws,
                "new_count": new,
                "completed_count": len(completed),
                "new_delayed_count": len(new_delayed),
            }
        )
    report["weekly_trend"] = trend
    return report


# ---------------------------------------------------------------- 项目维度报表（6.2）

async def projects_report(
    session: AsyncSession,
    start: datetime,
    end: datetime,
    *,
    status: str = "in_progress",
    owner_id: int | None = None,
    now: datetime | None = None,
) -> dict:
    now = now or now_sh()
    stmt = select(Project).order_by(Project.id)
    if status != "all":
        stmt = stmt.where(Project.status == status)
    if owner_id is not None:
        stmt = stmt.where(Project.owner_id == owner_id)
    projects = list((await session.scalars(stmt)).all())

    pairs = await _load_all(session)
    completed_ids = set(await _completed_ids(session, start, end))

    items = []
    for project in projects:
        req_pairs = [(r, s) for r, s in pairs if r.project_id == project.id]
        total = len(req_pairs)
        done_now = sum(1 for r, _ in req_pairs if r.status == "done")
        completed_in_period = sum(1 for r, _ in req_pairs if r.id in completed_ids)
        delayed_details = []
        for r, s in req_pairs:
            if r.status != "delayed":
                continue
            overdue = _overdue_items(s, now)
            latest_reason = None
            if r.manual_delay_reason:
                latest_reason = r.manual_delay_reason
            elif overdue:
                latest_reason = overdue[0]["last_delay_reason"]
            delayed_details.append(
                {
                    "requirement_id": r.id,
                    "title": r.title,
                    "overdue_stages": overdue,
                    "latest_delay_reason": latest_reason,
                }
            )
        items.append(
            {
                "project_id": project.id,
                "name": project.name,
                "status": project.status,
                "owner_id": project.owner_id,
                "progress_note": project.progress_note,
                "progress_percent": project.progress_percent,
                "total_requirements": total,
                "done_count": done_now,
                "completed_in_period": completed_in_period,
                "completion_rate": round(done_now / total, 4) if total else 0.0,
                "delayed_requirements": delayed_details,
            }
        )
    return {
        "period_start": start,
        "period_end": end,
        "status_filter": status,
        "owner_id": owner_id,
        "projects": items,
    }
