"""测试辅助：统一时间基准与环节取用。"""

from __future__ import annotations

from datetime import datetime

from app.enums import StageType
from app.models import RequirementStage

# 统一时间基准（各用例在此基础上加减 timedelta）
NOW = datetime(2026, 8, 14, 10, 0, 0)


def get_stage(stage_list: list[RequirementStage], st: StageType) -> RequirementStage:
    return next(s for s in stage_list if s.stage_type == st.value)
