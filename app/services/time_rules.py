"""预估时间校验规则（design.md 3.2）。

规则（创建与修改时均强制）：
1. 同一环节内 planned_end ≥ planned_start（精确比较）；
2. 环节的 planned_start 不得早于全部前置环节（已填写的）planned_end
   —— 并行环节只依赖共同前置 backend_dev；测试依赖平台/前端/API 三者；
   跨环节比较按"年月"粒度：同月相邻视为合理（环节排期支持月份级输入），
   跨月倒置仍判定冲突；
3. planned_end 为 NULL 的环节不参与任何比较；
4. 校验失败返回错误信息列表（API 层映射为 409 并列出冲突字段）。
"""

from __future__ import annotations

from datetime import datetime

from app.enums import PREREQUISITES
from app.models import RequirementStage

STAGE_LABEL = {
    "research": "需求调研",
    "review": "需求审评",
    "backend_dev": "平台开发",
    "frontend_dev": "前端开发",
    "api_dev": "API 开发",
    "testing": "测试",
    "release": "上线",
}


def validate_stage_times(stages: list[RequirementStage]) -> list[str]:
    """校验一组环节的预估时间，返回错误信息列表（空列表 = 通过）。"""
    errors: list[str] = []
    by_type = {s.type_enum: s for s in stages}

    for s in stages:
        label = STAGE_LABEL.get(s.stage_type, s.stage_type)
        # 规则 1：环节内 planned_end ≥ planned_start
        if s.planned_start is not None and s.planned_end is not None:
            if s.planned_end < s.planned_start:
                errors.append(
                    f"{label}：预计结束时间不得早于预计开始时间"
                )
        # 规则 2：planned_start 与前置环节 planned_end 按年月粒度比较（同月允许）
        if s.planned_start is not None:
            prereq_ends = [
                by_type[p].planned_end
                for p in PREREQUISITES[s.type_enum]
                if p in by_type and by_type[p].planned_end is not None
            ]
            if prereq_ends:
                latest = max(prereq_ends)
                if (s.planned_start.year, s.planned_start.month) < (latest.year, latest.month):
                    names = [
                        STAGE_LABEL.get(p.value, p.value)
                        for p in PREREQUISITES[s.type_enum]
                        if p in by_type and by_type[p].planned_end is not None
                    ]
                    errors.append(
                        f"{label}：预计开始时间不得早于前置环节"
                        f"（{'、'.join(names)}）的预计结束时间"
                    )
    return errors
