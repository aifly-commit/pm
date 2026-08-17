"""需求管理服务（design.md 3、8.2）。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.enums import PARALLEL_STAGES, STAGE_SEQ, StageStatus, StageType
from app.models import (
    Requirement,
    RequirementStage,
    RequirementStatusLog,
    StageRevertLog,
    StageTimeChangeLog,
)
from app.services.state_machine import recalc_status
from app.services.time_rules import validate_stage_times

STAGE_LABEL = {
    "research": "需求调研",
    "review": "需求审评",
    "backend_dev": "平台开发",
    "frontend_dev": "前端开发",
    "api_dev": "API 开发",
    "testing": "测试",
    "release": "上线",
}


class RequirementError(Exception):
    """需求业务错误（API 层映射为 409/404）。"""

    def __init__(self, message: str, status: int = 409):
        super().__init__(message)
        self.message = message
        self.status = status


def now_sh() -> datetime:
    """当前 Asia/Shanghai naive 时间。"""
    from app.core.config import TZ

    return datetime.now(TZ).replace(tzinfo=None)


def current_stage_label(stages: list[RequirementStage]) -> str | None:
    """派生"当前环节"展示字段（design.md 3.5）。

    - 有进行中环节：若前端/API 并行在途，取 seq 较小者并标注"（并行）"；
    - 无进行中环节：取下一个待开始环节（首个未完成，按 seq）；
    - 全部完成返回 None。
    """
    in_progress = [s for s in stages if s.status == StageStatus.IN_PROGRESS.value]
    if in_progress:
        types = {s.type_enum for s in in_progress}
        if types == PARALLEL_STAGES:
            return f"{STAGE_LABEL[StageType.FRONTEND_DEV.value]}（并行）"
        first = min(in_progress, key=lambda s: s.seq)
        return STAGE_LABEL.get(first.stage_type, first.stage_type)
    not_done = [s for s in stages if s.status != StageStatus.DONE.value]
    if not_done:
        first = min(not_done, key=lambda s: s.seq)
        return STAGE_LABEL.get(first.stage_type, first.stage_type)
    return None


def current_stage_types(stages: list[RequirementStage]) -> list[str]:
    """筛选用：当前环节命中的环节类型集合（design.md 3.5——命中任一在途环节）。"""
    in_progress = [s for s in stages if s.status == StageStatus.IN_PROGRESS.value]
    if in_progress:
        return [s.stage_type for s in in_progress]
    not_done = [s for s in stages if s.status != StageStatus.DONE.value]
    if not_done:
        first = min(not_done, key=lambda s: s.seq)
        return [first.stage_type]
    return []


async def get_requirement(session: AsyncSession, req_id: int) -> Requirement:
    req = await session.get(Requirement, req_id)
    if req is None:
        raise RequirementError(f"需求 {req_id} 不存在", status=404)
    return req


async def get_stages(session: AsyncSession, req_id: int) -> list[RequirementStage]:
    result = await session.scalars(
        select(RequirementStage)
        .where(RequirementStage.requirement_id == req_id)
        .order_by(RequirementStage.seq)
    )
    return list(result)


async def get_full(
    session: AsyncSession, req_id: int
) -> tuple[Requirement, list[RequirementStage], list[StageTimeChangeLog], list[StageRevertLog]]:
    """详情页数据：需求 + 环节 + 变更历史 + 回退历史。"""
    req = await get_requirement(session, req_id)
    stages = await get_stages(session, req_id)
    change_logs = list(
        (
            await session.scalars(
                select(StageTimeChangeLog)
                .join(RequirementStage, StageTimeChangeLog.stage_id == RequirementStage.id)
                .where(RequirementStage.requirement_id == req_id)
                .order_by(StageTimeChangeLog.created_at.desc(), StageTimeChangeLog.id.desc())
            )
        ).all()
    )
    revert_logs = list(
        (
            await session.scalars(
                select(StageRevertLog)
                .where(StageRevertLog.requirement_id == req_id)
                .order_by(StageRevertLog.created_at.desc(), StageRevertLog.id.desc())
            )
        ).all()
    )
    return req, stages, change_logs, revert_logs


async def create_requirement(
    session: AsyncSession,
    *,
    title: str,
    description: str | None,
    product_line: str | None,
    category: str | None,
    source: str | None,
    priority: str,
    project_id: int | None,
    responsible_pm_id: int,
    stage_plans: list[dict],
) -> Requirement:
    """创建需求并生成 7 个环节（design.md 3.1）。

    预计上线时间（release 环节 planned_end）为必填项；其余环节排期可留空。
    """
    if project_id is not None:
        from app.models import Project

        project = await session.get(Project, project_id)
        if project is None:
            raise RequirementError(f"项目 {project_id} 不存在", status=404)

    plan_by_type = {p["stage_type"]: p for p in stage_plans}
    unknown = set(plan_by_type) - {t.value for t in STAGE_SEQ}
    if unknown:
        raise RequirementError(f"未知环节类型：{sorted(unknown)}")
    if plan_by_type.get(StageType.RELEASE.value, {}).get("planned_end") is None:
        raise RequirementError("预计上线时间（上线环节的预计结束时间）为必填项")

    req = Requirement(
        title=title,
        description=description,
        product_line=product_line,
        category=category,
        source=source,
        priority=priority,
        project_id=project_id,
        responsible_pm_id=responsible_pm_id,
    )
    session.add(req)
    await session.flush()

    stages = [
        RequirementStage(
            requirement_id=req.id,
            stage_type=st.value,
            seq=seq,
            status=StageStatus.NOT_STARTED.value,
            planned_start=plan_by_type.get(st.value, {}).get("planned_start"),
            planned_end=plan_by_type.get(st.value, {}).get("planned_end"),
            assignee_id=plan_by_type.get(st.value, {}).get("assignee_id"),
        )
        for st, seq in STAGE_SEQ.items()
    ]
    session.add_all(stages)
    await session.flush()

    errors = validate_stage_times(stages)
    if errors:
        raise RequirementError("；".join(errors))
    return req


async def update_requirement(
    session: AsyncSession,
    req: Requirement,
    *,
    title: str | None = None,
    description: str | None = None,
    product_line: str | None = None,
    category: str | None = None,
    source: str | None = None,
    priority: str | None = None,
    project_id: int | None = None,
    responsible_pm_id: int | None = None,
    stage_assignees: list[dict] | None = None,
) -> Requirement:
    """编辑基础字段与环节负责人（design.md 8.2 PATCH）。"""
    if project_id is not None:
        from app.models import Project

        if await session.get(Project, project_id) is None:
            raise RequirementError(f"项目 {project_id} 不存在", status=404)
    if title is not None:
        req.title = title
    if description is not None:
        req.description = description
    if product_line is not None:
        req.product_line = product_line
    if category is not None:
        req.category = category
    if source is not None:
        req.source = source
    if priority is not None:
        req.priority = priority
    if project_id is not None:
        req.project_id = project_id
    if responsible_pm_id is not None:
        from app.models import User

        if await session.get(User, responsible_pm_id) is None:
            raise RequirementError(f"用户 {responsible_pm_id} 不存在", status=404)
        req.responsible_pm_id = responsible_pm_id

    if stage_assignees:
        stages = await get_stages(session, req.id)
        by_id = {s.id: s for s in stages}
        for item in stage_assignees:
            stage = by_id.get(item["stage_id"])
            if stage is None or stage.requirement_id != req.id:
                raise RequirementError(f"环节 {item['stage_id']} 不属于该需求", status=404)
            if item["assignee_id"] is not None:
                from app.models import User

                if await session.get(User, item["assignee_id"]) is None:
                    raise RequirementError(
                        f"用户 {item['assignee_id']} 不存在", status=404
                    )
            stage.assignee_id = item["assignee_id"]

    req.updated_at = now_sh()
    await session.flush()
    return req


async def list_requirements(
    session: AsyncSession,
    *,
    status: str | None = None,
    stage_type: str | None = None,
    product_line: str | None = None,
    pm_id: int | None = None,
    project_id: int | None = None,
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[tuple[Requirement, list[RequirementStage]]], int]:
    """需求列表 + 各自环节（用于派生当前环节与 stage_type 筛选）。

    stage_type 为派生条件（当前环节），无法在 SQL 层过滤：
    全量加载后在内存筛选再分页，total 为筛选后的总数（数据量千级，无压力）。
    排序：按 id 升序，保证列表稳定不乱序。
    """
    stmt = select(Requirement)
    if status is not None:
        stmt = stmt.where(Requirement.status == status)
    if product_line is not None:
        stmt = stmt.where(Requirement.product_line == product_line)
    if pm_id is not None:
        stmt = stmt.where(Requirement.responsible_pm_id == pm_id)
    if project_id is not None:
        stmt = stmt.where(Requirement.project_id == project_id)
    if keyword:
        stmt = stmt.where(Requirement.title.like(f"%{keyword}%"))

    stmt = (
        stmt.order_by(Requirement.id.asc())
        .options(selectinload(Requirement.stages))
    )
    rows = list((await session.scalars(stmt)).all())
    pairs = [(r, sorted(r.stages, key=lambda s: s.seq)) for r in rows]

    if stage_type is not None:
        pairs = [(r, s) for r, s in pairs if stage_type in current_stage_types(s)]

    total = len(pairs)
    start = (page - 1) * page_size
    return pairs[start : start + page_size], total


async def pm_name_map(session: AsyncSession, pm_ids: set[int]) -> dict[int, str]:
    """负责 PM id → 显示名（列表/详情展示用）。"""
    if not pm_ids:
        return {}
    from app.models import User

    rows = (
        await session.execute(
            select(User.id, User.display_name).where(User.id.in_(pm_ids))
        )
    ).all()
    return {uid: name for uid, name in rows}


async def set_requirement_status(
    session: AsyncSession,
    requirement: Requirement,
    status: str | None,
    actor_id: int | None = None,
) -> Requirement:
    """单独修改需求状态（design.md 3.3 手动状态覆盖）。

    - status 为枚举值：写入 manual_status 覆盖位并同步 status，冻结状态；
    - status 为 None：清除覆盖位，按环节重算回到自动状态。
    两种情况都写 RequirementStatusLog。
    """
    old_status = requirement.status
    if status is None:
        requirement.manual_status = None
        stages = await get_stages(session, requirement.id)
        recalc_status(requirement, stages, now_sh())
    else:
        requirement.manual_status = status
        requirement.status = status
    requirement.updated_at = now_sh()
    if requirement.status != old_status:
        session.add(
            RequirementStatusLog(
                requirement_id=requirement.id,
                from_status=old_status,
                to_status=requirement.status,
                changed_by=actor_id,
            )
        )
    await session.flush()
    return requirement
