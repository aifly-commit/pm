"""枚举与环节流程定义。

环节顺序与依赖关系（design.md 3.1）：
    research(1) → review(2) → backend_dev(3) → {frontend_dev(4), api_dev(5)} → testing(6) → release(7)

前端开发与 API 开发为并行兄弟环节：backend_dev 完成后可同时开始；
testing 需三者全部完成后才可开始。
"""

from __future__ import annotations

import enum


class UserRole(str, enum.Enum):
    PM = "pm"
    DEVELOPER = "developer"
    TESTER = "tester"
    ADMIN = "admin"


class RequirementStatus(str, enum.Enum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    DELAYED = "delayed"
    PAUSED = "paused"
    DONE = "done"


class StageStatus(str, enum.Enum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    DONE = "done"


class StageType(str, enum.Enum):
    RESEARCH = "research"
    REVIEW = "review"
    BACKEND_DEV = "backend_dev"
    FRONTEND_DEV = "frontend_dev"
    API_DEV = "api_dev"
    TESTING = "testing"
    RELEASE = "release"


# 产品线枚举（需求归属，design.md 3.5 扩展字段）
PRODUCT_LINES: tuple[str, ...] = (
    "MySQL",
    "PostgreSQL",
    "SQLServer",
    "TiDB",
    "分布式数据库",
    "Redis",
    "MongoDB",
    "Memcached",
    "Milvus",
    "记忆服务",
    "图服务",
    "ClickHouse",
    "RabbitMQ",
    "DMP",
    "DTS",
    "DataAgent",
)


# 环节固定顺序（seq 1–7）
STAGE_SEQ: dict[StageType, int] = {
    StageType.RESEARCH: 1,
    StageType.REVIEW: 2,
    StageType.BACKEND_DEV: 3,
    StageType.FRONTEND_DEV: 4,
    StageType.API_DEV: 5,
    StageType.TESTING: 6,
    StageType.RELEASE: 7,
}

# 并行兄弟环节（共享前置 backend_dev）
PARALLEL_STAGES = {StageType.FRONTEND_DEV, StageType.API_DEV}

# 各环节的前置环节（start / complete 校验依据，design.md 3.1、8.3）
PREREQUISITES: dict[StageType, tuple[StageType, ...]] = {
    StageType.RESEARCH: (),
    StageType.REVIEW: (StageType.RESEARCH,),
    StageType.BACKEND_DEV: (StageType.REVIEW,),
    StageType.FRONTEND_DEV: (StageType.BACKEND_DEV,),
    StageType.API_DEV: (StageType.BACKEND_DEV,),
    StageType.TESTING: (StageType.BACKEND_DEV, StageType.FRONTEND_DEV, StageType.API_DEV),
    StageType.RELEASE: (StageType.TESTING,),
}

# 允许的回退路径（design.md 3.1 回退规则）
ALLOWED_REVERT_TARGETS: dict[StageType, frozenset[StageType]] = {
    StageType.REVIEW: frozenset({StageType.RESEARCH}),
    StageType.TESTING: frozenset(
        {StageType.BACKEND_DEV, StageType.FRONTEND_DEV, StageType.API_DEV}
    ),
}
