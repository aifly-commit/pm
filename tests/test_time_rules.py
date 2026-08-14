"""time_rules：预估时间校验（design.md 3.2）。"""

from __future__ import annotations

from datetime import datetime, timedelta

from tests.helpers import NOW


def set_plan(stages, **plans):
    """按环节类型批量设置预估时间：set_plan(stages, research=(start, end), ...)。"""
    by = {s.stage_type: s for s in stages}
    for st, (start, end) in plans.items():
        by[st].planned_start = start
        by[st].planned_end = end


def d(days: int) -> datetime:
    return NOW + timedelta(days=days)


class TestValidateStageTimes:
    async def test_valid_full_schedule(self, stages):
        set_plan(
            stages,
            research=(d(0), d(2)),
            review=(d(2), d(4)),
            backend_dev=(d(4), d(10)),
            frontend_dev=(d(10), d(15)),
            api_dev=(d(10), d(14)),
            testing=(d(15), d(20)),
            release=(d(20), d(20)),
        )
        from app.services.time_rules import validate_stage_times

        assert validate_stage_times(stages) == []

    async def test_end_before_start_within_stage(self, stages):
        set_plan(stages, research=(d(2), d(1)))
        from app.services.time_rules import validate_stage_times

        errors = validate_stage_times(stages)
        assert len(errors) == 1
        assert "需求调研" in errors[0]

    async def test_start_before_prereq_end(self, stages):
        set_plan(
            stages,
            research=(d(0), d(2)),
            review=(d(1), d(4)),  # 早于 research 的 planned_end
        )
        from app.services.time_rules import validate_stage_times

        errors = validate_stage_times(stages)
        assert any("需求审评" in e for e in errors)

    async def test_testing_needs_all_three_dev_end(self, stages):
        # testing 依赖三个开发环节中最晚的 planned_end
        set_plan(
            stages,
            backend_dev=(d(0), d(10)),
            frontend_dev=(d(10), d(12)),
            api_dev=(d(10), d(14)),
            testing=(d(12), d(20)),  # 早于 api_dev 的 d(14)
        )
        from app.services.time_rules import validate_stage_times

        errors = validate_stage_times(stages)
        assert any("测试" in e for e in errors)

    async def test_null_planned_times_skip_validation(self, stages):
        # 全部留空 = 通过（design.md 3.2：NULL 不参与判定）
        from app.services.time_rules import validate_stage_times

        assert validate_stage_times(stages) == []

    async def test_partial_null_prereq_ignored(self, stages):
        # research 未填、review 有时间：前置为 NULL 不参与比较，通过
        set_plan(stages, review=(d(0), d(3)))
        from app.services.time_rules import validate_stage_times

        assert validate_stage_times(stages) == []

    async def test_equal_boundary_passes(self, stages):
        # planned_start == 前置 planned_end（衔接日）允许
        set_plan(
            stages,
            research=(d(0), d(2)),
            review=(d(2), d(4)),
        )
        from app.services.time_rules import validate_stage_times

        assert validate_stage_times(stages) == []

    async def test_multiple_errors_all_reported(self, stages):
        set_plan(
            stages,
            research=(d(2), d(1)),       # 环节内倒挂
            backend_dev=(d(0), d(3)),    # 早于 review 的 planned_end → 顺序冲突
            review=(d(3), d(2)),         # 环节内倒挂
        )
        from app.services.time_rules import validate_stage_times

        errors = validate_stage_times(stages)
        assert len(errors) == 3
        assert any("需求调研" in e for e in errors)
        assert any("需求审评" in e and "预计结束时间不得早于预计开始时间" in e for e in errors)
        assert any("平台开发" in e and "前置环节" in e for e in errors)
