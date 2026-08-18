"""API 请求/响应模型（Pydantic v2）。"""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.enums import PRODUCT_LINES, REQ_CATEGORIES, RequirementStatus, UserRole


# ---------------------------------------------------------------- 认证

class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ---------------------------------------------------------------- 用户

class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    display_name: str
    role: str
    is_active: bool
    created_at: DateOnlyDateTime


class UserCreate(BaseModel):
    username: str = Field(min_length=2, max_length=64)
    password: str = Field(min_length=6, max_length=128)
    display_name: str = Field(min_length=1, max_length=64)
    role: UserRole


class UserUpdate(BaseModel):
    display_name: Optional[str] = Field(default=None, min_length=1, max_length=64)
    role: Optional[UserRole] = None
    is_active: Optional[bool] = None


class ResetPasswordIn(BaseModel):
    new_password: str = Field(min_length=6, max_length=128)


class TransferIn(BaseModel):
    to_user_id: int


# ---------------------------------------------------------------- 时间

from typing import Annotated  # noqa: E402

from pydantic import BeforeValidator, PlainSerializer  # noqa: E402

from app.core.config import TZ  # noqa: E402


def _to_naive_sh(v) -> datetime | None:
    """入参统一转换为 Asia/Shanghai 的 naive 时间入库（design.md 4.2）。

    接受字符串或 datetime（带/不带偏移），BeforeValidator 在 pydantic 核心
    解析之前执行，因此字符串也要在这里先行解析。
    """
    if isinstance(v, str):
        v = datetime.fromisoformat(v)
    if isinstance(v, date) and not isinstance(v, datetime):
        return datetime.combine(v, time.min)
    if isinstance(v, datetime) and v.tzinfo is not None:
        return v.astimezone(TZ).replace(tzinfo=None)
    return v


def _to_day_start(v) -> datetime | None:
    value = _to_naive_sh(v)
    return value.replace(hour=0, minute=0, second=0, microsecond=0) if value else value


def _to_day_end(v) -> datetime | None:
    value = _to_naive_sh(v)
    return value.replace(hour=23, minute=59, second=59, microsecond=0) if value else value


def _as_date(v: datetime | None) -> str | None:
    return v.date().isoformat() if isinstance(v, datetime) else v


# 对外统一按“年月日”传输；内部保留 datetime 以保证状态机边界计算准确。
DateOnlyDateTime = Annotated[
    datetime,
    BeforeValidator(_to_naive_sh),
    PlainSerializer(_as_date, when_used="json"),
]
DateStartDateTime = Annotated[
    datetime,
    BeforeValidator(_to_day_start),
    PlainSerializer(_as_date, when_used="json"),
]
DateEndDateTime = Annotated[
    datetime,
    BeforeValidator(_to_day_end),
    PlainSerializer(_as_date, when_used="json"),
]


# ---------------------------------------------------------------- 需求

PRIORITY_PATTERN = r"^P[0-3]$"


def _validate_product_line(v: str | None) -> str | None:
    """产品线枚举校验（enums.PRODUCT_LINES），None 与空串放行。"""
    if v is None or v == "":
        return None
    if v not in PRODUCT_LINES:
        raise ValueError(f"未知产品线：{v}，可选：{'、'.join(PRODUCT_LINES)}")
    return v


def _validate_category(v: str | None) -> str | None:
    """需求分类枚举校验（enums.REQ_CATEGORIES），None 与空串放行。"""
    if v is None or v == "":
        return None
    if v not in REQ_CATEGORIES:
        raise ValueError(f"未知需求分类：{v}，可选：{'、'.join(REQ_CATEGORIES)}")
    return v


class ProductLineMixin(BaseModel):
    product_line: str | None = Field(default=None, max_length=32)
    category: str | None = Field(default=None, max_length=16)
    source: str | None = Field(default=None, max_length=128)

    _check_pl = field_validator("product_line")(_validate_product_line)
    _check_cat = field_validator("category")(_validate_category)


class StagePlanItem(BaseModel):
    """创建/编辑需求时的环节排期项。"""

    stage_type: str = Field(pattern=r"^(research|review|backend_dev|frontend_dev|api_dev|testing|release)$")
    planned_start: DateStartDateTime | None = None
    planned_end: DateEndDateTime | None = None
    assignee_id: int | None = None


class StageAssigneeItem(BaseModel):
    """PATCH 需求时批量指派环节负责人。"""

    stage_id: int
    assignee_id: int | None


class RequirementCreate(ProductLineMixin):
    # 创建时产品线必填（更新时仍可空 = 不修改）
    product_line: str = Field(min_length=1, max_length=32)

    title: str = Field(min_length=1, max_length=200)
    description: str | None = None
    remark: str | None = Field(default=None, max_length=4000)
    priority: str = Field(default="P2", pattern=PRIORITY_PATTERN)
    project_id: int | None = None
    responsible_pm_id: int | None = None  # 默认当前用户；仅 Admin 可指定他人
    stages: list[StagePlanItem] = Field(default_factory=list)


class RequirementImportIn(BaseModel):
    """批量导入需求；每个 items 元素与单条创建请求使用同一字段规范。"""

    items: list[RequirementCreate] = Field(min_length=1, max_length=100)


class RequirementUpdate(ProductLineMixin):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    remark: str | None = Field(default=None, max_length=4000)
    priority: str | None = Field(default=None, pattern=PRIORITY_PATTERN)
    project_id: int | None = None
    responsible_pm_id: int | None = None
    stage_assignees: list[StageAssigneeItem] | None = None


class RequirementStatusUpdate(BaseModel):
    """单独修改需求状态（design.md 3.3 手动状态覆盖）。

    status 为枚举值 → 写入 manual_status 覆盖位并冻结；
    status 为 None → 清除覆盖位，回到状态机自动重算。
    """

    # 必须显式传入 status；{"status": null} 表示清除，{} 不是清除指令。
    status: RequirementStatus | None = Field(...)


class ReasonIn(BaseModel):
    """暂停/恢复/标记延期等需填原因的操作。"""

    reason: str = Field(min_length=1, max_length=2000)


class StageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    stage_type: str
    seq: int
    status: str
    assignee_id: int | None
    planned_start: DateOnlyDateTime | None
    planned_end: DateOnlyDateTime | None
    actual_start: DateOnlyDateTime | None
    actual_end: DateOnlyDateTime | None
    last_delay_reason: str | None
    reminder_sent: bool


class ChangeLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    stage_id: int
    field: str
    old_value: DateOnlyDateTime | None  # 首次排期时原值为 None
    new_value: DateOnlyDateTime | None
    reason: str
    auto_generated: bool
    changed_by: int
    created_at: DateOnlyDateTime


class RevertLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    requirement_id: int
    from_stage_id: int
    to_stage_id: int
    reverted_by: int
    reason: str
    created_at: DateOnlyDateTime


class RequirementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    description: str | None
    remark: str | None
    product_line: str | None
    category: str | None
    source: str | None
    priority: str
    status: str
    manual_status: str | None = None  # 手动覆盖位（design.md 3.3）；None=自动
    manual_delayed: bool
    manual_delay_reason: str | None
    responsible_pm_id: int
    pm_name: str | None = None  # 负责 PM 显示名（API 层填充）
    project_id: int | None
    current_stage: str | None = None  # 派生展示字段（含并行窗口标注）
    planned_release: DateOnlyDateTime | None = None  # 预计上线日期（release 环节 planned_end）
    actual_release: DateOnlyDateTime | None = None  # 实际上线日期（release 环节 actual_end）
    created_at: DateOnlyDateTime
    updated_at: DateOnlyDateTime


class RequirementDetailOut(RequirementOut):
    stages: list[StageOut]
    change_logs: list[ChangeLogOut]
    revert_logs: list[RevertLogOut]
    modification_logs: list[RequirementModificationLogOut]


class RequirementModificationLogOut(BaseModel):
    """详情页统一的需求修改记录项，按时间倒序返回。"""

    id: str
    change_type: str
    field: str
    old_value: str | None
    new_value: str | None
    reason: str | None = None
    changed_by: int | None = None
    created_at: DateOnlyDateTime


class RequirementListOut(BaseModel):
    items: list[RequirementOut]
    total: int
    page: int
    page_size: int


class RequirementImportOut(BaseModel):
    """批量导入结果。接口仅在全部条目校验成功时才提交。"""

    imported_count: int
    items: list[RequirementOut]


# ---------------------------------------------------------------- 环节

class StagePlanUpdate(BaseModel):
    """修改预估时间（design.md 8.3）。"""

    planned_start: DateStartDateTime | None = None
    planned_end: DateEndDateTime | None = None
    reason: str = Field(min_length=1, max_length=2000)


class StageRevertIn(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)
    target_stage_id: int


class StageAssigneeUpdate(BaseModel):
    assignee_id: int | None


# ---------------------------------------------------------------- 项目

PROJECT_STATUS_PATTERN = (
    r"^(not_started|in_progress|done|paused|terminated)$"
)


class ContactIn(BaseModel):
    """接口人（design.md 5.1）。"""

    name: str = Field(min_length=1, max_length=64)
    phone: str | None = Field(default=None, max_length=32)
    email: str | None = Field(default=None, max_length=128)
    im: str | None = Field(default=None, max_length=128)


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str | None = None
    contacts: list[ContactIn] = Field(default_factory=list)
    status: str = Field(default="not_started", pattern=PROJECT_STATUS_PATTERN)
    planned_start: DateStartDateTime | None = None
    planned_end: DateEndDateTime | None = None
    owner_id: int | None = None  # 默认当前用户；仅 Admin 可指定他人


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = None
    contacts: list[ContactIn] | None = None
    progress_note: str | None = None
    progress_percent: int | None = Field(default=None, ge=0, le=100)
    status: str | None = Field(default=None, pattern=PROJECT_STATUS_PATTERN)
    planned_start: DateStartDateTime | None = None
    planned_end: DateEndDateTime | None = None
    actual_start: DateStartDateTime | None = None
    actual_end: DateEndDateTime | None = None
    owner_id: int | None = None


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None
    contacts: list[dict] | None
    progress_note: str | None
    progress_percent: int
    status: str
    planned_start: DateOnlyDateTime | None
    planned_end: DateOnlyDateTime | None
    actual_start: DateOnlyDateTime | None
    actual_end: DateOnlyDateTime | None
    owner_id: int
    created_at: DateOnlyDateTime
    updated_at: DateOnlyDateTime


class ProjectRequirementItem(BaseModel):
    """对接需求清单条目（design.md 5.2：标题、当前环节、状态、是否延期）。"""

    id: int
    title: str
    priority: str
    status: str
    current_stage: str | None
    is_delayed: bool


class ProjectDetailOut(ProjectOut):
    requirements: list[ProjectRequirementItem]
    total: int
    done_count: int
    completion_rate: float


class ProjectListOut(BaseModel):
    items: list[ProjectOut]
    total: int


class AttachRequirementIn(BaseModel):
    requirement_id: int
