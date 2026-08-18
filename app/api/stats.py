"""统计路由（design.md 8.6）。"""

from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db import get_session
from app.models import User
from app.services import stats as stats_service

router = APIRouter(prefix="/stats", tags=["stats"])


def _date_only(value):
    """统计接口没有独立 schema，递归将 datetime 统一为 YYYY-MM-DD。"""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, dict):
        return {key: _date_only(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_date_only(item) for item in value]
    return value


@router.get("/overview")
async def overview(
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(get_current_user),
) -> dict:
    return _date_only(await stats_service.overview(session))


@router.get("/requirements/weekly")
async def requirement_weekly(
    date_in: date = Query(alias="date", default=None),
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(get_current_user),
) -> dict:
    d = date_in or date.today()
    start, end = stats_service.week_bounds(d)
    return _date_only(await stats_service.requirement_report(session, start, end))


@router.get("/requirements/monthly")
async def requirement_monthly(
    month: str = Query(pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(get_current_user),
) -> dict:
    start, end = stats_service.month_bounds(month)
    return _date_only(await stats_service.requirement_monthly(session, start, end))


@router.get("/projects/weekly")
async def projects_weekly(
    date_in: date = Query(alias="date", default=None),
    status: str = "in_progress",
    owner_id: int | None = None,
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(get_current_user),
) -> dict:
    d = date_in or date.today()
    start, end = stats_service.week_bounds(d)
    return _date_only(
        await stats_service.projects_report(session, start, end, status=status, owner_id=owner_id)
    )


@router.get("/projects/monthly")
async def projects_monthly(
    month: str = Query(pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
    status: str = "in_progress",
    owner_id: int | None = None,
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(get_current_user),
) -> dict:
    start, end = stats_service.month_bounds(month)
    return _date_only(
        await stats_service.projects_report(session, start, end, status=status, owner_id=owner_id)
    )
