"""统计路由（design.md 8.6）。"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db import get_session
from app.models import User
from app.services import stats as stats_service

router = APIRouter(prefix="/stats", tags=["stats"])


@router.get("/overview")
async def overview(
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(get_current_user),
) -> dict:
    return await stats_service.overview(session)


@router.get("/requirements/weekly")
async def requirement_weekly(
    date_in: date = Query(alias="date", default=None),
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(get_current_user),
) -> dict:
    d = date_in or date.today()
    start, end = stats_service.week_bounds(d)
    return await stats_service.requirement_report(session, start, end)


@router.get("/requirements/monthly")
async def requirement_monthly(
    month: str = Query(pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(get_current_user),
) -> dict:
    start, end = stats_service.month_bounds(month)
    return await stats_service.requirement_monthly(session, start, end)


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
    return await stats_service.projects_report(
        session, start, end, status=status, owner_id=owner_id
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
    return await stats_service.projects_report(
        session, start, end, status=status, owner_id=owner_id
    )
