"""需求路由（design.md 8.2）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db import get_session
from app.models import User
from app.schemas import (
    ChangeLogOut,
    ReasonIn,
    RevertLogOut,
    RequirementCreate,
    RequirementDetailOut,
    RequirementListOut,
    RequirementOut,
    RequirementUpdate,
    StageOut,
)
from app.services import requirements as req_service
from app.services.requirements import RequirementError, current_stage_label
from app.services.stages import (
    StagePermissionError,
    assert_requirement_write,
    mark_delayed,
    pause_requirement,
    resume_requirement,
    unmark_delayed,
)

router = APIRouter(tags=["requirements"])


def _to_out(req, stages, names: dict[int, str] | None = None) -> RequirementOut:
    out = RequirementOut.model_validate(req)
    out.current_stage = current_stage_label(stages)
    if names:
        out.pm_name = names.get(req.responsible_pm_id)
    return out


async def _names_for(session: AsyncSession, reqs: list) -> dict[int, str]:
    """返回需求负责 PM 的 id → 显示名映射。"""
    return await req_service.pm_name_map(session, {r.responsible_pm_id for r in reqs})


def _error(e: RequirementError) -> HTTPException:
    return HTTPException(status_code=e.status, detail=e.message)


@router.get("/requirements", response_model=RequirementListOut)
async def list_requirements(
    status: str | None = None,
    stage_type: str | None = None,
    product_line: str | None = None,
    pm_id: int | None = None,
    project_id: int | None = None,
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 20,
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(get_current_user),
) -> RequirementListOut:
    pairs, total = await req_service.list_requirements(
        session,
        status=status,
        stage_type=stage_type,
        product_line=product_line,
        pm_id=pm_id,
        project_id=project_id,
        keyword=keyword,
        page=page,
        page_size=page_size,
    )
    names = await _names_for(session, [r for r, _ in pairs])
    return RequirementListOut(
        items=[_to_out(r, s, names) for r, s in pairs],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("/requirements", response_model=RequirementOut, status_code=201)
async def create_requirement(
    body: RequirementCreate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> RequirementOut:
    if user.role not in ("pm", "admin"):
        raise HTTPException(status_code=403, detail="仅产品经理或管理员可创建需求")
    pm_id = body.responsible_pm_id or user.id
    if pm_id != user.id and user.role != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可指定他人为负责产品经理")
    try:
        req = await req_service.create_requirement(
            session,
            title=body.title,
            description=body.description,
            product_line=body.product_line,
            priority=body.priority,
            project_id=body.project_id,
            responsible_pm_id=pm_id,
            stage_plans=[p.model_dump() for p in body.stages],
        )
    except RequirementError as e:
        raise _error(e)
    await session.commit()
    stages = await req_service.get_stages(session, req.id)
    names = await _names_for(session, [req])
    return _to_out(req, stages, names)


@router.get("/requirements/{req_id}", response_model=RequirementDetailOut)
async def get_requirement(
    req_id: int,
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(get_current_user),
) -> RequirementDetailOut:
    try:
        req, stages, change_logs, revert_logs = await req_service.get_full(
            session, req_id
        )
    except RequirementError as e:
        raise _error(e)
    names = await _names_for(session, [req])
    base = _to_out(req, stages, names).model_dump()
    return RequirementDetailOut(
        **base,
        stages=[StageOut.model_validate(s) for s in stages],
        change_logs=[ChangeLogOut.model_validate(l) for l in change_logs],
        revert_logs=[RevertLogOut.model_validate(l) for l in revert_logs],
    )


@router.patch("/requirements/{req_id}", response_model=RequirementDetailOut)
async def update_requirement(
    req_id: int,
    body: RequirementUpdate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> RequirementDetailOut:
    try:
        req = await req_service.get_requirement(session, req_id)
        assert_requirement_write(user, req)
        await req_service.update_requirement(
            session,
            req,
            title=body.title,
            description=body.description,
            product_line=body.product_line,
            priority=body.priority,
            project_id=body.project_id,
            responsible_pm_id=body.responsible_pm_id,
            stage_assignees=(
                [a.model_dump() for a in body.stage_assignees]
                if body.stage_assignees is not None
                else None
            ),
        )
        await session.commit()
    except RequirementError as e:
        raise _error(e)
    except StagePermissionError as e:
        raise HTTPException(status_code=403, detail=e.message)
    return await get_requirement(req_id, session, user)


@router.post("/requirements/{req_id}/pause", response_model=RequirementOut)
async def pause_requirement_endpoint(
    req_id: int,
    _body: ReasonIn | None = None,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> RequirementOut:
    try:
        req = await req_service.get_requirement(session, req_id)
        assert_requirement_write(user, req)
        await pause_requirement(session, req, actor_id=user.id)
        await session.commit()
        stages = await req_service.get_stages(session, req_id)
    except RequirementError as e:
        raise _error(e)
    except StagePermissionError as e:
        raise HTTPException(status_code=403, detail=e.message)
    return _to_out(req, stages)


@router.post("/requirements/{req_id}/resume", response_model=RequirementOut)
async def resume_requirement_endpoint(
    req_id: int,
    _body: ReasonIn | None = None,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> RequirementOut:
    try:
        req = await req_service.get_requirement(session, req_id)
        assert_requirement_write(user, req)
        await resume_requirement(session, req, actor_id=user.id)
        await session.commit()
        stages = await req_service.get_stages(session, req_id)
    except RequirementError as e:
        raise _error(e)
    except StagePermissionError as e:
        raise HTTPException(status_code=403, detail=e.message)
    return _to_out(req, stages)


@router.post("/requirements/{req_id}/mark-delayed", response_model=RequirementOut)
async def mark_delayed_endpoint(
    req_id: int,
    body: ReasonIn,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> RequirementOut:
    try:
        req = await req_service.get_requirement(session, req_id)
        assert_requirement_write(user, req)
        await mark_delayed(session, req, body.reason, actor_id=user.id)
        await session.commit()
        stages = await req_service.get_stages(session, req_id)
    except RequirementError as e:
        raise _error(e)
    except StagePermissionError as e:
        raise HTTPException(status_code=403, detail=e.message)
    return _to_out(req, stages)


@router.post("/requirements/{req_id}/unmark-delayed", response_model=RequirementOut)
async def unmark_delayed_endpoint(
    req_id: int,
    body: ReasonIn,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> RequirementOut:
    try:
        req = await req_service.get_requirement(session, req_id)
        assert_requirement_write(user, req)
        await unmark_delayed(session, req, body.reason, actor_id=user.id)
        await session.commit()
        stages = await req_service.get_stages(session, req_id)
    except RequirementError as e:
        raise _error(e)
    except StagePermissionError as e:
        raise HTTPException(status_code=403, detail=e.message)
    return _to_out(req, stages)
