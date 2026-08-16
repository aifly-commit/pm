"""项目管理服务（design.md 5、8.4）。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.enums import StageStatus
from app.models import Project, Requirement, RequirementStage, User
from app.services.requirements import RequirementError, current_stage_label, now_sh

PROJECT_STATUSES = ("not_started", "in_progress", "done", "paused", "terminated")


class ProjectPermissionError(Exception):
    """项目写权限不足（API 层映射为 403）。"""

    def __init__(self, message: str = "仅项目负责人或管理员可执行该操作"):
        super().__init__(message)
        self.message = message


async def get_project(session: AsyncSession, project_id: int) -> Project:
    project = await session.get(Project, project_id)
    if project is None:
        raise RequirementError(f"项目 {project_id} 不存在", status=404)
    return project


async def list_projects(
    session: AsyncSession,
    *,
    status: str | None = None,
    owner_id: int | None = None,
) -> list[Project]:
    stmt = select(Project).order_by(Project.id.desc())
    if status is not None:
        stmt = stmt.where(Project.status == status)
    if owner_id is not None:
        stmt = stmt.where(Project.owner_id == owner_id)
    return list((await session.scalars(stmt)).all())


async def create_project(
    session: AsyncSession,
    *,
    name: str,
    description: str | None,
    contacts: list[dict] | None,
    status: str,
    planned_start,
    planned_end,
    owner_id: int,
) -> Project:
    if await session.get(User, owner_id) is None:
        raise RequirementError(f"用户 {owner_id} 不存在", status=404)
    project = Project(
        name=name,
        description=description,
        contacts=contacts,
        status=status,
        planned_start=planned_start,
        planned_end=planned_end,
        owner_id=owner_id,
    )
    session.add(project)
    await session.flush()
    return project


async def update_project(
    session: AsyncSession,
    project: Project,
    *,
    name: str | None = None,
    description: str | None = None,
    contacts: list[dict] | None = None,
    progress_note: str | None = None,
    progress_percent: int | None = None,
    status: str | None = None,
    planned_start=None,
    planned_end=None,
    actual_start=None,
    actual_end=None,
    owner_id: int | None = None,
) -> Project:
    if owner_id is not None and await session.get(User, owner_id) is None:
        raise RequirementError(f"用户 {owner_id} 不存在", status=404)
    if name is not None:
        project.name = name
    if description is not None:
        project.description = description
    if contacts is not None:
        project.contacts = contacts
    if progress_note is not None:
        project.progress_note = progress_note
    if progress_percent is not None:
        project.progress_percent = progress_percent
    if status is not None:
        project.status = status
    if planned_start is not None:
        project.planned_start = planned_start
    if planned_end is not None:
        project.planned_end = planned_end
    if actual_start is not None:
        project.actual_start = actual_start
    if actual_end is not None:
        project.actual_end = actual_end
    if owner_id is not None:
        project.owner_id = owner_id
    project.updated_at = now_sh()
    await session.flush()
    return project


async def project_requirements(
    session: AsyncSession, project_id: int
) -> list[tuple[Requirement, list[RequirementStage]]]:
    """项目对接需求清单（含环节，用于派生当前环节）。"""
    rows = list(
        (
            await session.scalars(
                select(Requirement)
                .where(Requirement.project_id == project_id)
                .options(selectinload(Requirement.stages))
                .order_by(Requirement.id)
            )
        ).all()
    )
    return [(r, sorted(r.stages, key=lambda s: s.seq)) for r in rows]


def completion_rate(pairs: list[tuple[Requirement, list[RequirementStage]]]) -> dict:
    """自动完成率 = 已完成需求数 / 需求总数（design.md 5.2）。"""
    total = len(pairs)
    done = sum(1 for r, _ in pairs if r.status == "done")
    return {
        "total": total,
        "done_count": done,
        "completion_rate": round(done / total, 4) if total else 0.0,
    }


async def delete_project(session: AsyncSession, project: Project) -> int:
    """删除项目：不级联删除需求——先解除全部挂接再删项目本体（design.md 8.4）。"""
    rows = list(
        (
            await session.scalars(
                select(Requirement).where(Requirement.project_id == project.id)
            )
        ).all()
    )
    for req in rows:
        req.project_id = None
    await session.delete(project)
    await session.flush()
    return len(rows)


async def attach_requirement(
    session: AsyncSession, project: Project, requirement: Requirement
) -> None:
    """挂接需求：已属于其他项目 → 409；已在本项目 → 幂等成功（design.md 8.4）。"""
    if requirement.project_id is not None and requirement.project_id != project.id:
        raise RequirementError(
            f"需求 {requirement.id} 已挂接至其他项目（project_id={requirement.project_id}）",
        )
    requirement.project_id = project.id
    requirement.updated_at = now_sh()
    await session.flush()


async def detach_requirement(
    session: AsyncSession, project: Project, requirement: Requirement
) -> None:
    """解除挂接：置空 project_id。"""
    if requirement.project_id != project.id:
        raise RequirementError(f"需求 {requirement.id} 未挂接至该项目", status=404)
    requirement.project_id = None
    requirement.updated_at = now_sh()
    await session.flush()
