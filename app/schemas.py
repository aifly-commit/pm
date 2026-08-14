"""API 请求/响应模型（Pydantic v2）。"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.enums import UserRole


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
    created_at: datetime


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
    if isinstance(v, datetime) and v.tzinfo is not None:
        return v.astimezone(TZ).replace(tzinfo=None)
    return v


def _to_tz_sh(v: datetime | None) -> datetime | None:
    """出参补 +08:00 偏移（design.md 8.8：ISO 8601 带时区偏移）。"""
    if isinstance(v, datetime) and v.tzinfo is None:
        return v.replace(tzinfo=TZ)
    return v


TZDateTime = Annotated[
    datetime,
    BeforeValidator(_to_naive_sh),
    PlainSerializer(_to_tz_sh, when_used="always"),
]


# ---------------------------------------------------------------- 需求

PRIORITY_PATTERN = r"^P[0-3]$"


class StagePlanItem(BaseModel):
    """创建/编辑需求时的环节排期项。"""

    stage_type: str = Field(pattern=r"^(research|review|backend_dev|frontend_dev|api_dev|testing|release)$")
    planned_start: TZDateTime | None = None
    planned_end: TZDateTime | None = None
    assignee_id: int | None = None


class StageAssigneeItem(BaseModel):
    """PATCH 需求时批量指派环节负责人。"""

    stage_id: int
    assignee_id: int | None


class RequirementCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = None
    priority: str = Field(default="P2", pattern=PRIORITY_PATTERN)
    project_id: int | None = None
    responsible_pm_id: int | None = None  # 默认当前用户；仅 Admin 可指定他人
    stages: list[StagePlanItem] = Field(default_factory=list)


class RequirementUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    priority: str | None = Field(default=None, pattern=PRIORITY_PATTERN)
    project_id: int | None = None
    responsible_pm_id: int | None = None
    stage_assignees: list[StageAssigneeItem] | None = None


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
    planned_start: TZDateTime | None
    planned_end: TZDateTime | None
    actual_start: TZDateTime | None
    actual_end: TZDateTime | None
    last_delay_reason: str | None
    reminder_sent: bool


class ChangeLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    stage_id: int
    field: str
    old_value: TZDateTime
    new_value: TZDateTime
    reason: str
    auto_generated: bool
    changed_by: int
    created_at: TZDateTime


class RevertLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    requirement_id: int
    from_stage_id: int
    to_stage_id: int
    reverted_by: int
    reason: str
    created_at: TZDateTime


class RequirementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    description: str | None
    priority: str
    status: str
    manual_delayed: bool
    manual_delay_reason: str | None
    responsible_pm_id: int
    project_id: int | None
    current_stage: str | None = None  # 派生展示字段（含并行窗口标注）
    created_at: TZDateTime
    updated_at: TZDateTime


class RequirementDetailOut(RequirementOut):
    stages: list[StageOut]
    change_logs: list[ChangeLogOut]
    revert_logs: list[RevertLogOut]


class RequirementListOut(BaseModel):
    items: list[RequirementOut]
    total: int
    page: int
    page_size: int


# ---------------------------------------------------------------- 环节

class StagePlanUpdate(BaseModel):
    """修改预估时间（design.md 8.3）。"""

    planned_start: TZDateTime | None = None
    planned_end: TZDateTime | None = None
    reason: str = Field(min_length=1, max_length=2000)


class StageRevertIn(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)
    target_stage_id: int


class StageAssigneeUpdate(BaseModel):
    assignee_id: int | None
