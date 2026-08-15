"""ORM 模型（design.md 7.2 表结构）。"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.enums import RequirementStatus, StageStatus, StageType, UserRole


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(64), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    # 接口人列表：[{"name": "张三", "phone": "...", "email": "..."}]
    contacts: Mapped[Optional[list[dict]]] = mapped_column(JSON)
    progress_note: Mapped[Optional[str]] = mapped_column(Text)
    progress_percent: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="not_started")
    planned_start: Mapped[Optional[date]] = mapped_column(DateTime)
    planned_end: Mapped[Optional[date]] = mapped_column(DateTime)
    actual_start: Mapped[Optional[date]] = mapped_column(DateTime)
    actual_end: Mapped[Optional[date]] = mapped_column(DateTime)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    requirements: Mapped[list[Requirement]] = relationship(back_populates="project")


class Requirement(Base):
    __tablename__ = "requirements"
    __table_args__ = (
        Index("ix_requirements_status", "status"),
        Index("ix_requirements_pm", "responsible_pm_id"),
        Index("ix_requirements_project", "project_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(String(4), nullable=False, default="P2")
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=RequirementStatus.NOT_STARTED.value
    )
    # PM 人工标记的延期（与系统逾期独立，design.md 3.3）
    manual_delayed: Mapped[bool] = mapped_column(Boolean, default=False)
    manual_delay_reason: Mapped[Optional[str]] = mapped_column(Text)
    responsible_pm_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    project_id: Mapped[Optional[int]] = mapped_column(ForeignKey("projects.id"))
    paused_from: Mapped[Optional[str]] = mapped_column(String(16))
    paused_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    stages: Mapped[list[RequirementStage]] = relationship(
        back_populates="requirement", order_by="RequirementStage.seq"
    )
    project: Mapped[Optional[Project]] = relationship(back_populates="requirements")


class RequirementStage(Base):
    __tablename__ = "requirement_stages"
    __table_args__ = (
        UniqueConstraint("requirement_id", "seq", name="uq_stage_requirement_seq"),
        Index("ix_stage_planned_end_status", "planned_end", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    requirement_id: Mapped[int] = mapped_column(
        ForeignKey("requirements.id"), nullable=False
    )
    stage_type: Mapped[str] = mapped_column(String(32), nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=StageStatus.NOT_STARTED.value
    )
    assignee_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    planned_start: Mapped[Optional[datetime]] = mapped_column(DateTime)
    planned_end: Mapped[Optional[datetime]] = mapped_column(DateTime)
    actual_start: Mapped[Optional[datetime]] = mapped_column(DateTime)
    actual_end: Mapped[Optional[datetime]] = mapped_column(DateTime)
    last_delay_reason: Mapped[Optional[str]] = mapped_column(Text)
    reminder_sent: Mapped[bool] = mapped_column(Boolean, default=False)

    requirement: Mapped[Requirement] = relationship(back_populates="stages")
    change_logs: Mapped[list[StageTimeChangeLog]] = relationship(back_populates="stage")

    @property
    def type_enum(self) -> StageType:
        return StageType(self.stage_type)


class StageTimeChangeLog(Base):
    __tablename__ = "stage_time_change_logs"
    __table_args__ = (
        Index("ix_change_logs_stage", "stage_id"),
        Index("ix_change_logs_created", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stage_id: Mapped[int] = mapped_column(
        ForeignKey("requirement_stages.id"), nullable=False
    )
    changed_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    field: Mapped[str] = mapped_column(String(16), nullable=False)
    # 首次排期时原值为 NULL；清空时间为 NULL（当前 API 不支持清空，预留）
    old_value: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    new_value: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    # TRUE = 系统自动产生（如暂停顺延），统计时排除（design.md 6.3）
    auto_generated: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    stage: Mapped[RequirementStage] = relationship(back_populates="change_logs")


class StageRevertLog(Base):
    __tablename__ = "stage_revert_logs"
    __table_args__ = (Index("ix_revert_logs_requirement", "requirement_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    requirement_id: Mapped[int] = mapped_column(
        ForeignKey("requirements.id"), nullable=False
    )
    from_stage_id: Mapped[int] = mapped_column(
        ForeignKey("requirement_stages.id"), nullable=False
    )
    to_stage_id: Mapped[int] = mapped_column(
        ForeignKey("requirement_stages.id"), nullable=False
    )
    reverted_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notifications_user_read", "user_id", "is_read"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    content: Mapped[Optional[str]] = mapped_column(Text)
    requirement_id: Mapped[Optional[int]] = mapped_column(ForeignKey("requirements.id"))
    stage_id: Mapped[Optional[int]] = mapped_column(ForeignKey("requirement_stages.id"))
    # 防重复键：{stage_id}:{type}:{yyyy-mm-dd}；status_changed 置 NULL（design.md 4.1）
    dedupe_key: Mapped[Optional[str]] = mapped_column(String(128), unique=True)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
