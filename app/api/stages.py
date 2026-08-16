"""环节路由（design.md 8.3）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db import get_session
from app.models import User
from app.schemas import (
    ChangeLogOut,
    RequirementOut,
    StageAssigneeUpdate,
    StageOut,
    StagePlanUpdate,
    StageRevertIn,
)
from app.services.requirements import RequirementError, current_stage_label, get_stages
from app.services.stages import (
    StagePermissionError,
    complete_stage,
    get_stage,
    list_change_logs,
    revert_stage,
    start_stage,
    update_stage_assignee,
    update_stage_plan,
)

router = APIRouter(prefix="/stages", tags=["stages"])


def _requirement_out(session, requirement) -> RequirementOut:
    out = RequirementOut.model_validate(requirement)
    return out


async def _out_with_stage_label(session, requirement) -> RequirementOut:
    stages = await get_stages(session, requirement.id)
    out = _requirement_out(session, requirement)
    out.current_stage = current_stage_label(stages)
    release = next((s for s in stages if s.stage_type == "release"), None)
    if release is not None:
        out.planned_release = release.planned_end
        out.actual_release = release.actual_end
    return out


@router.post("/{stage_id}/start", response_model=RequirementOut)
async def start_stage_endpoint(
    stage_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> RequirementOut:
    try:
        stage = await get_stage(session, stage_id)
        requirement = await start_stage(session, stage, user)
        await session.commit()
    except RequirementError as e:
        raise HTTPException(status_code=e.status, detail=e.message)
    except StagePermissionError as e:
        raise HTTPException(status_code=403, detail=e.message)
    return await _out_with_stage_label(session, requirement)


@router.post("/{stage_id}/complete", response_model=RequirementOut)
async def complete_stage_endpoint(
    stage_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> RequirementOut:
    try:
        stage = await get_stage(session, stage_id)
        requirement = await complete_stage(session, stage, user)
        await session.commit()
    except RequirementError as e:
        raise HTTPException(status_code=e.status, detail=e.message)
    except StagePermissionError as e:
        raise HTTPException(status_code=403, detail=e.message)
    return await _out_with_stage_label(session, requirement)


@router.post("/{stage_id}/revert")
async def revert_stage_endpoint(
    stage_id: int,
    body: StageRevertIn,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> dict:
    try:
        from_stage = await get_stage(session, stage_id)
        requirement, reset = await revert_stage(
            session, from_stage, body.target_stage_id, body.reason, user
        )
        await session.commit()
    except RequirementError as e:
        raise HTTPException(status_code=e.status, detail=e.message)
    except StagePermissionError as e:
        raise HTTPException(status_code=403, detail=e.message)
    return {
        "requirement": (await _out_with_stage_label(session, requirement)).model_dump(),
        "reset_stage_ids": [s.id for s in reset],
    }


@router.patch("/{stage_id}/plan", response_model=StageOut)
async def update_plan_endpoint(
    stage_id: int,
    body: StagePlanUpdate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> StageOut:
    try:
        stage = await get_stage(session, stage_id)
        await update_stage_plan(
            session,
            stage,
            planned_start=body.planned_start,
            planned_end=body.planned_end,
            reason=body.reason,
            user=user,
        )
        await session.commit()
    except RequirementError as e:
        raise HTTPException(status_code=e.status, detail=e.message)
    except StagePermissionError as e:
        raise HTTPException(status_code=403, detail=e.message)
    return StageOut.model_validate(stage)


@router.patch("/{stage_id}/assignee", response_model=StageOut)
async def update_assignee_endpoint(
    stage_id: int,
    body: StageAssigneeUpdate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> StageOut:
    try:
        stage = await get_stage(session, stage_id)
        await update_stage_assignee(session, stage, body.assignee_id, user)
        await session.commit()
    except RequirementError as e:
        raise HTTPException(status_code=e.status, detail=e.message)
    except StagePermissionError as e:
        raise HTTPException(status_code=403, detail=e.message)
    return StageOut.model_validate(stage)


@router.get("/{stage_id}/change-logs", response_model=list[ChangeLogOut])
async def change_logs_endpoint(
    stage_id: int,
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(get_current_user),
) -> list[ChangeLogOut]:
    try:
        await get_stage(session, stage_id)
    except RequirementError as e:
        raise HTTPException(status_code=e.status, detail=e.message)
    logs = await list_change_logs(session, stage_id)
    return [ChangeLogOut.model_validate(log) for log in logs]
