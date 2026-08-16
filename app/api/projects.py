"""项目路由（design.md 8.4）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db import get_session
from app.models import Requirement, User
from app.schemas import (
    AttachRequirementIn,
    ProjectCreate,
    ProjectDetailOut,
    ProjectListOut,
    ProjectOut,
    ProjectRequirementItem,
    ProjectUpdate,
)
from app.services import projects as project_service
from app.services.projects import ProjectPermissionError, completion_rate
from app.services.requirements import RequirementError, current_stage_label

router = APIRouter(prefix="/projects", tags=["projects"])


def _require_project_write(user: User, project) -> None:
    if user.role != "admin" and project.owner_id != user.id:
        raise ProjectPermissionError()


def _to_detail(project, pairs) -> ProjectDetailOut:
    items = [
        ProjectRequirementItem(
            id=req.id,
            title=req.title,
            priority=req.priority,
            status=req.status,
            current_stage=current_stage_label(stages),
            is_delayed=req.status == "delayed",
        )
        for req, stages in pairs
    ]
    stats = completion_rate(pairs)
    base = ProjectOut.model_validate(project).model_dump()
    return ProjectDetailOut(**base, requirements=items, **stats)


@router.get("", response_model=ProjectListOut)
async def list_projects(
    status: str | None = None,
    owner_id: int | None = None,
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(get_current_user),
) -> ProjectListOut:
    rows = await project_service.list_projects(
        session, status=status, owner_id=owner_id
    )
    items = [ProjectOut.model_validate(p) for p in rows]
    return ProjectListOut(items=items, total=len(items))


@router.post("", response_model=ProjectOut, status_code=201)
async def create_project(
    body: ProjectCreate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> ProjectOut:
    if user.role not in ("pm", "admin"):
        raise HTTPException(status_code=403, detail="仅产品经理或管理员可创建项目")
    owner_id = body.owner_id or user.id
    if owner_id != user.id and user.role != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可指定他人为项目负责人")
    try:
        project = await project_service.create_project(
            session,
            name=body.name,
            description=body.description,
            contacts=[c.model_dump() for c in body.contacts],
            status=body.status,
            planned_start=body.planned_start,
            planned_end=body.planned_end,
            owner_id=owner_id,
        )
        await session.commit()
    except RequirementError as e:
        raise HTTPException(status_code=e.status, detail=e.message)
    return ProjectOut.model_validate(project)


@router.get("/{project_id}", response_model=ProjectDetailOut)
async def get_project(
    project_id: int,
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(get_current_user),
) -> ProjectDetailOut:
    try:
        project = await project_service.get_project(session, project_id)
        pairs = await project_service.project_requirements(session, project.id)
    except RequirementError as e:
        raise HTTPException(status_code=e.status, detail=e.message)
    return _to_detail(project, pairs)


@router.patch("/{project_id}", response_model=ProjectOut)
async def update_project(
    project_id: int,
    body: ProjectUpdate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> ProjectOut:
    try:
        project = await project_service.get_project(session, project_id)
        _require_project_write(user, project)
        if body.owner_id is not None and user.role != "admin":
            raise HTTPException(status_code=403, detail="仅管理员可变更项目负责人")
        await project_service.update_project(
            session,
            project,
            name=body.name,
            description=body.description,
            contacts=(
                [c.model_dump() for c in body.contacts]
                if body.contacts is not None
                else None
            ),
            progress_note=body.progress_note,
            progress_percent=body.progress_percent,
            status=body.status,
            planned_start=body.planned_start,
            planned_end=body.planned_end,
            actual_start=body.actual_start,
            actual_end=body.actual_end,
            owner_id=body.owner_id,
        )
        await session.commit()
    except RequirementError as e:
        raise HTTPException(status_code=e.status, detail=e.message)
    except ProjectPermissionError as e:
        raise HTTPException(status_code=403, detail=e.message)
    return ProjectOut.model_validate(project)


@router.delete("/{project_id}", status_code=204)
async def delete_project(
    project_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> None:
    try:
        project = await project_service.get_project(session, project_id)
        _require_project_write(user, project)
        await project_service.delete_project(session, project)
        await session.commit()
    except RequirementError as e:
        raise HTTPException(status_code=e.status, detail=e.message)
    except ProjectPermissionError as e:
        raise HTTPException(status_code=403, detail=e.message)


@router.post("/{project_id}/requirements", response_model=ProjectDetailOut)
async def attach_requirement(
    project_id: int,
    body: AttachRequirementIn,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> ProjectDetailOut:
    try:
        project = await project_service.get_project(session, project_id)
        _require_project_write(user, project)
        requirement = await session.get(Requirement, body.requirement_id)
        if requirement is None:
            raise RequirementError(
                f"需求 {body.requirement_id} 不存在", status=404
            )
        await project_service.attach_requirement(session, project, requirement)
        await session.commit()
        pairs = await project_service.project_requirements(session, project.id)
    except RequirementError as e:
        raise HTTPException(status_code=e.status, detail=e.message)
    except ProjectPermissionError as e:
        raise HTTPException(status_code=403, detail=e.message)
    return _to_detail(project, pairs)


@router.delete("/{project_id}/requirements/{req_id}", response_model=ProjectDetailOut)
async def detach_requirement(
    project_id: int,
    req_id: int,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
) -> ProjectDetailOut:
    try:
        project = await project_service.get_project(session, project_id)
        _require_project_write(user, project)
        requirement = await session.get(Requirement, req_id)
        if requirement is None:
            raise RequirementError(f"需求 {req_id} 不存在", status=404)
        await project_service.detach_requirement(session, project, requirement)
        await session.commit()
        pairs = await project_service.project_requirements(session, project.id)
    except RequirementError as e:
        raise HTTPException(status_code=e.status, detail=e.message)
    except ProjectPermissionError as e:
        raise HTTPException(status_code=403, detail=e.message)
    return _to_detail(project, pairs)
