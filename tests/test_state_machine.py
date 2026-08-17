"""state_machine：状态机核心逻辑（design.md 3.1 / 3.3 全部转换路径）。"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.enums import StageStatus, StageType
from app.services.state_machine import (
    FlowError,
    apply_revert,
    apply_resume_shift,
    apply_status,
    can_complete_stage,
    can_start_stage,
    has_system_overdue,
    is_stage_overdue,
    make_default_stages,
    mark_delayed,
    pause,
    recalc_status,
    system_overdue_stages,
    unmark_delayed,
)
from tests.helpers import NOW, get_stage


def d(days: int) -> datetime:
    return NOW + timedelta(days=days)


def start_and_complete(stage, now=NOW):
    stage.status = StageStatus.IN_PROGRESS.value
    stage.actual_start = now
    stage.status = StageStatus.DONE.value
    stage.actual_end = now + timedelta(hours=8)


def make_in_progress(stages):
    """把需求推进到"平台开发进行中"（research/review 已完成）。"""
    for st in (StageType.RESEARCH, StageType.REVIEW):
        start_and_complete(get_stage(stages, st))
    backend = get_stage(stages, StageType.BACKEND_DEV)
    backend.status = StageStatus.IN_PROGRESS.value
    backend.actual_start = NOW


# ------------------------------------------------------------- 逾期判定

class TestOverdue:
    async def test_null_planned_end_never_overdue(self, stages):
        stage = get_stage(stages, StageType.RESEARCH)
        assert not is_stage_overdue(stage, NOW)

    async def test_done_stage_not_overdue(self, stages):
        stage = get_stage(stages, StageType.RESEARCH)
        stage.planned_end = d(-1)
        stage.status = StageStatus.DONE.value
        assert not is_stage_overdue(stage, NOW)

    async def test_overdue_when_past_planned_end(self, stages):
        stage = get_stage(stages, StageType.RESEARCH)
        stage.planned_end = d(-1)
        assert is_stage_overdue(stage, NOW)

    async def test_boundary_equal_not_overdue(self, stages):
        # 当前时间 == planned_end 不算逾期（须严格大于）
        stage = get_stage(stages, StageType.RESEARCH)
        stage.planned_end = NOW
        assert not is_stage_overdue(stage, NOW)

    async def test_system_overdue_helpers(self, stages):
        get_stage(stages, StageType.RESEARCH).planned_end = d(-2)
        get_stage(stages, StageType.REVIEW).planned_end = d(-1)
        assert has_system_overdue(stages, NOW)
        overdue = system_overdue_stages(stages, NOW)
        assert {s.stage_type for s in overdue} == {"research", "review"}


# ------------------------------------------------------------- 状态重算

class TestRecalcStatus:
    async def test_not_started_by_default(self, requirement, stages):
        assert recalc_status(requirement, stages, NOW) == "not_started"

    async def test_in_progress_when_stage_running(self, requirement, stages):
        make_in_progress(stages)
        assert recalc_status(requirement, stages, NOW) == "in_progress"

    async def test_not_started_with_overdue_becomes_delayed(self, requirement, stages):
        # design.md 3.3：未开始 + 首环节超期 → 延期（排了期不启动也算延期）
        get_stage(stages, StageType.RESEARCH).planned_end = d(-1)
        assert recalc_status(requirement, stages, NOW) == "delayed"

    async def test_in_progress_with_overdue_becomes_delayed(self, requirement, stages):
        make_in_progress(stages)
        get_stage(stages, StageType.BACKEND_DEV).planned_end = d(-1)
        assert recalc_status(requirement, stages, NOW) == "delayed"

    async def test_manual_flag_alone_is_delayed(self, requirement, stages):
        requirement.manual_delayed = True
        assert recalc_status(requirement, stages, NOW) == "delayed"

    async def test_delayed_recovers_when_overdue_gone(self, requirement, stages):
        requirement.status = "delayed"
        make_in_progress(stages)  # 无逾期环节
        assert recalc_status(requirement, stages, NOW) == "in_progress"

    async def test_done_is_terminal(self, requirement, stages):
        requirement.status = "done"
        # 即使有逾期环节/人工标记也不变
        get_stage(stages, StageType.RESEARCH).planned_end = d(-1)
        assert recalc_status(requirement, stages, NOW) == "done"

    async def test_paused_untouched(self, requirement, stages):
        requirement.status = "paused"
        get_stage(stages, StageType.RESEARCH).planned_end = d(-1)
        assert recalc_status(requirement, stages, NOW) == "paused"

    async def test_actual_start_only_counts_as_in_progress(self, requirement, stages):
        # 有实际开始记录但无进行中环节（回退重置后的中间态）→ 进行中
        stage = get_stage(stages, StageType.RESEARCH)
        stage.actual_start = NOW  # status 仍 not_started
        assert recalc_status(requirement, stages, NOW) == "in_progress"

    async def test_future_stage_overdue_counts(self, requirement, stages):
        # 后续环节（未开始）超期同样触发延期（design.md 3.3 口径：任一未完成环节）
        make_in_progress(stages)
        get_stage(stages, StageType.TESTING).planned_end = d(-5)
        assert recalc_status(requirement, stages, NOW) == "delayed"


# ------------------------------------------------------------- 手动状态覆盖（design.md 3.3）

class TestManualStatusOverride:
    async def test_override_wins_over_in_progress_stage(self, requirement, stages):
        # 有进行中环节，按自动口径应 in_progress；手动覆盖 not_started 胜出
        make_in_progress(stages)
        requirement.manual_status = "not_started"
        assert recalc_status(requirement, stages, NOW) == "not_started"
        assert requirement.status == "not_started"

    async def test_override_wins_over_overdue(self, requirement, stages):
        # 系统逾期按自动口径应 delayed；手动覆盖 in_progress 胜出
        get_stage(stages, StageType.RESEARCH).planned_end = d(-1)
        requirement.manual_status = "in_progress"
        assert recalc_status(requirement, stages, NOW) == "in_progress"

    async def test_override_done_survives_overdue(self, requirement, stages):
        get_stage(stages, StageType.RESEARCH).planned_end = d(-1)
        requirement.manual_status = "done"
        assert recalc_status(requirement, stages, NOW) == "done"

    async def test_apply_status_respects_override(self, requirement):
        # 无覆盖：apply_status 正常写
        apply_status(requirement, "done")
        assert requirement.status == "done"
        # 有覆盖：apply_status 不改写 status
        requirement.manual_status = "delayed"
        requirement.status = "delayed"
        apply_status(requirement, "done")
        assert requirement.status == "delayed"

    async def test_clear_override_recalcs(self, requirement, stages):
        # 覆盖为 delayed，清空后按环节重算回 not_started
        requirement.manual_status = "delayed"
        requirement.status = "delayed"
        requirement.manual_status = None
        assert recalc_status(requirement, stages, NOW) == "not_started"

    async def test_pause_does_not_change_status_under_override(self, requirement, stages):
        # 手动覆盖 paused 之外的状态时，pause 不应改写 status（但顺延字段仍记录）
        requirement.manual_status = "in_progress"
        requirement.status = "in_progress"
        pause(requirement, NOW)
        assert requirement.status == "in_progress"  # 覆盖冻结
        assert requirement.paused_from == "in_progress"  # 顺延字段照记
        assert requirement.paused_at == NOW


# ------------------------------------------------------------- start / complete

class TestCanStart:
    async def test_first_stage_can_start(self, stages):
        research = get_stage(stages, StageType.RESEARCH)
        can_start_stage(stages, research)  # 不抛错

    async def test_cannot_start_twice(self, stages):
        research = get_stage(stages, StageType.RESEARCH)
        research.status = StageStatus.IN_PROGRESS.value
        with pytest.raises(FlowError, match="不可重复开始"):
            can_start_stage(stages, research)

    async def test_cannot_start_without_prereq_done(self, stages):
        review = get_stage(stages, StageType.REVIEW)
        with pytest.raises(FlowError, match="前置环节 research 未完成"):
            can_start_stage(stages, review)

    async def test_parallel_stages_need_only_backend(self, stages):
        for st in (StageType.RESEARCH, StageType.REVIEW, StageType.BACKEND_DEV):
            start_and_complete(get_stage(stages, st))
        can_start_stage(stages, get_stage(stages, StageType.FRONTEND_DEV))
        can_start_stage(stages, get_stage(stages, StageType.API_DEV))

    async def test_testing_needs_all_three_dev(self, stages):
        for st in (StageType.RESEARCH, StageType.REVIEW, StageType.BACKEND_DEV):
            start_and_complete(get_stage(stages, st))
        start_and_complete(get_stage(stages, StageType.FRONTEND_DEV))
        # api_dev 未完成 → testing 不可开始
        with pytest.raises(FlowError, match="api_dev 未完成"):
            can_start_stage(stages, get_stage(stages, StageType.TESTING))

    async def test_release_needs_testing(self, stages):
        release = get_stage(stages, StageType.RELEASE)
        with pytest.raises(FlowError, match="前置环节 testing 未完成"):
            can_start_stage(stages, release)


class TestCanComplete:
    async def test_in_progress_can_complete(self, stages):
        stage = get_stage(stages, StageType.RESEARCH)
        stage.status = StageStatus.IN_PROGRESS.value
        can_complete_stage(stage)

    async def test_not_started_cannot_complete(self, stages):
        stage = get_stage(stages, StageType.RESEARCH)
        with pytest.raises(FlowError, match="仅进行中的环节可标记完成"):
            can_complete_stage(stage)

    async def test_done_cannot_complete_again(self, stages):
        stage = get_stage(stages, StageType.RESEARCH)
        stage.status = StageStatus.DONE.value
        with pytest.raises(FlowError):
            can_complete_stage(stage)


# ------------------------------------------------------------- 回退

class TestRevert:
    async def test_review_to_research(self, requirement, stages):
        # research/review 完成，review 发起回退到 research
        start_and_complete(get_stage(stages, StageType.RESEARCH))
        start_and_complete(get_stage(stages, StageType.REVIEW))
        research = get_stage(stages, StageType.RESEARCH)
        review = get_stage(stages, StageType.REVIEW)

        reset = apply_revert(requirement, stages, review, research, NOW)

        # 目标环节：进行中、actual_end 清空、actual_start 保留
        assert research.status == StageStatus.IN_PROGRESS.value
        assert research.actual_end is None
        assert research.actual_start is not None
        # 目标之后全部重置
        assert {s.stage_type for s in reset} == {
            "review", "backend_dev", "frontend_dev", "api_dev", "testing", "release"
        }
        for s in reset:
            assert s.status == StageStatus.NOT_STARTED.value
            assert s.actual_start is None and s.actual_end is None
        assert requirement.status == "in_progress"

    async def test_testing_to_backend_resets_parallel_children(self, requirement, stages):
        make_in_progress(stages)
        for st in (StageType.FRONTEND_DEV, StageType.API_DEV, StageType.TESTING):
            start_and_complete(get_stage(stages, st))
        backend = get_stage(stages, StageType.BACKEND_DEV)
        testing = get_stage(stages, StageType.TESTING)

        reset = apply_revert(requirement, stages, testing, backend, NOW)

        # 依赖 backend 产出的前端/API 一并重置
        assert {s.stage_type for s in reset} == {
            "frontend_dev", "api_dev", "testing", "release"
        }
        assert backend.status == StageStatus.IN_PROGRESS.value

    async def test_testing_to_frontend_keeps_backend(self, requirement, stages):
        make_in_progress(stages)
        start_and_complete(get_stage(stages, StageType.BACKEND_DEV))
        for st in (StageType.FRONTEND_DEV, StageType.API_DEV, StageType.TESTING):
            start_and_complete(get_stage(stages, st))
        backend = get_stage(stages, StageType.BACKEND_DEV)
        frontend = get_stage(stages, StageType.FRONTEND_DEV)
        testing = get_stage(stages, StageType.TESTING)

        apply_revert(requirement, stages, testing, frontend, NOW)

        # backend 在目标之前，保持已完成
        assert backend.status == StageStatus.DONE.value
        # api/testing/release 在目标之后，重置
        assert get_stage(stages, StageType.API_DEV).status == StageStatus.NOT_STARTED.value
        assert testing.status == StageStatus.NOT_STARTED.value

    async def test_invalid_target_rejected(self, requirement, stages):
        start_and_complete(get_stage(stages, StageType.RESEARCH))
        start_and_complete(get_stage(stages, StageType.REVIEW))
        review = get_stage(stages, StageType.REVIEW)
        with pytest.raises(FlowError, match="不允许从 review 回退到 backend_dev"):
            apply_revert(requirement, stages, review, get_stage(stages, StageType.BACKEND_DEV), NOW)

    async def test_stage_cannot_initiate_revert(self, requirement, stages):
        research = get_stage(stages, StageType.RESEARCH)
        research.status = StageStatus.IN_PROGRESS.value
        research.actual_start = NOW
        with pytest.raises(FlowError, match="不允许发起回退"):
            apply_revert(requirement, stages, research, research, NOW)

    async def test_done_requirement_cannot_revert(self, requirement, stages):
        requirement.status = "done"
        review = get_stage(stages, StageType.REVIEW)
        research = get_stage(stages, StageType.RESEARCH)
        with pytest.raises(FlowError, match="终态"):
            apply_revert(requirement, stages, review, research, NOW)

    async def test_release_cannot_initiate_revert(self, requirement, stages):
        for st in (
            StageType.RESEARCH, StageType.REVIEW, StageType.BACKEND_DEV,
            StageType.FRONTEND_DEV, StageType.API_DEV, StageType.TESTING,
        ):
            start_and_complete(get_stage(stages, st))
        release = get_stage(stages, StageType.RELEASE)
        release.status = StageStatus.IN_PROGRESS.value
        release.actual_start = NOW
        testing = get_stage(stages, StageType.TESTING)
        with pytest.raises(FlowError, match="不允许发起回退"):
            apply_revert(requirement, stages, release, testing, NOW)

    async def test_revert_from_non_current_stage_rejected(self, requirement, stages):
        # 需求已推进到 backend_dev，不允许再对历史环节 review 发起回退
        make_in_progress(stages)
        review = get_stage(stages, StageType.REVIEW)
        research = get_stage(stages, StageType.RESEARCH)
        with pytest.raises(FlowError, match="只能从当前所处环节 backend_dev 发起回退"):
            apply_revert(requirement, stages, review, research, NOW)
        # 历史环节回退被拦截，下游环节的实际时间不受影响
        backend = get_stage(stages, StageType.BACKEND_DEV)
        assert backend.status == StageStatus.IN_PROGRESS.value
        assert backend.actual_start is not None

    async def test_revert_with_no_started_stage_rejected(self, requirement, stages):
        review = get_stage(stages, StageType.REVIEW)
        research = get_stage(stages, StageType.RESEARCH)
        with pytest.raises(FlowError, match="尚无已开始的环节"):
            apply_revert(requirement, stages, review, research, NOW)

    async def test_revert_from_abnormal_status_rejected(self, requirement, stages):
        # 防御分支：环节有实际开始记录但状态异常（非进行中/已完成）
        review = get_stage(stages, StageType.REVIEW)
        review.actual_start = NOW  # status 仍 not_started
        research = get_stage(stages, StageType.RESEARCH)
        with pytest.raises(FlowError, match="不可发起回退"):
            apply_revert(requirement, stages, review, research, NOW)

    async def test_revert_clears_reminder_sent(self, requirement, stages):
        # 回退目标与下游重置环节的临期提醒标记一并清除（design.md 4.1 防漏发）
        for st in (StageType.RESEARCH, StageType.REVIEW, StageType.BACKEND_DEV):
            start_and_complete(get_stage(stages, st))
        testing = get_stage(stages, StageType.TESTING)
        testing.status = StageStatus.IN_PROGRESS.value
        testing.actual_start = NOW
        backend = get_stage(stages, StageType.BACKEND_DEV)
        backend.reminder_sent = True
        release = get_stage(stages, StageType.RELEASE)
        release.reminder_sent = True

        apply_revert(requirement, stages, testing, backend, NOW)

        assert backend.reminder_sent is False  # 回退目标
        assert release.reminder_sent is False  # 下游重置环节


# ------------------------------------------------------------- 暂停 / 恢复

class TestPauseResume:
    async def test_pause_records_from_and_at(self, requirement, stages):
        make_in_progress(stages)
        recalc_status(requirement, stages, NOW)  # 写操作内同步重算（design.md 3.3）
        pause(requirement, NOW)
        assert requirement.status == "paused"
        assert requirement.paused_from == "in_progress"
        assert requirement.paused_at == NOW

    async def test_pause_twice_rejected(self, requirement, stages):
        pause(requirement, NOW)
        with pytest.raises(FlowError, match="不可暂停"):
            pause(requirement, NOW)

    async def test_pause_done_rejected(self, requirement, stages):
        requirement.status = "done"
        with pytest.raises(FlowError):
            pause(requirement, NOW)

    async def test_resume_shifts_unfinished_by_pause_days(self, requirement, stages):
        make_in_progress(stages)
        recalc_status(requirement, stages, NOW)  # 写操作内同步重算（design.md 3.3）
        for st in (StageType.RESEARCH, StageType.REVIEW):
            start_and_complete(get_stage(stages, st))
        backend = get_stage(stages, StageType.BACKEND_DEV)
        backend.planned_start = d(-5)
        backend.planned_end = d(3)
        pause(requirement, NOW)

        shifted = apply_resume_shift(requirement, stages, NOW + timedelta(days=4))

        assert requirement.status == "in_progress"
        assert requirement.paused_from is None and requirement.paused_at is None
        # 未完成环节顺延 4 天
        assert backend.planned_start == d(-1)
        assert backend.planned_end == d(7)
        # 仅"未完成且有预估时间"的环节进入顺延列表（此处只有 backend）
        assert [(s.stage_type, old_start, old_end) for s, old_start, old_end in shifted] == [
            ("backend_dev", d(-5), d(3))
        ]

    async def test_resume_zero_days_no_shift(self, requirement, stages):
        pause(requirement, NOW)
        shifted = apply_resume_shift(requirement, stages, NOW)
        assert shifted == []
        assert requirement.status == "not_started"

    async def test_resume_shift_clears_reminder_sent(self, requirement, stages):
        # 顺延环节的临期提醒标记作废，临近新排期时应再次提醒（防漏发）
        make_in_progress(stages)
        recalc_status(requirement, stages, NOW)
        backend = get_stage(stages, StageType.BACKEND_DEV)
        backend.planned_start = d(-5)
        backend.planned_end = d(3)
        backend.reminder_sent = True
        pause(requirement, NOW)

        apply_resume_shift(requirement, stages, NOW + timedelta(days=2))

        assert backend.reminder_sent is False

    async def test_resume_not_paused_rejected(self, requirement, stages):
        with pytest.raises(FlowError, match="仅暂停中的需求可恢复"):
            apply_resume_shift(requirement, stages, NOW)


# ------------------------------------------------------------- 人工延期

class TestManualDelay:
    async def test_mark_delayed(self, requirement, stages):
        make_in_progress(stages)
        mark_delayed(requirement, "接口方联调延期风险", NOW, stages)
        assert requirement.manual_delayed is True
        assert requirement.status == "delayed"

    async def test_mark_requires_reason(self, requirement, stages):
        with pytest.raises(FlowError, match="必须填写原因"):
            mark_delayed(requirement, "  ", NOW, stages)

    async def test_mark_on_done_rejected(self, requirement, stages):
        requirement.status = "done"
        with pytest.raises(FlowError):
            mark_delayed(requirement, "r", NOW, stages)

    async def test_mark_on_paused_rejected(self, requirement, stages):
        pause(requirement, NOW)
        with pytest.raises(FlowError):
            mark_delayed(requirement, "r", NOW, stages)

    async def test_unmark_with_system_overdue_stays_delayed(self, requirement, stages):
        make_in_progress(stages)
        mark_delayed(requirement, "风险", NOW, stages)
        get_stage(stages, StageType.BACKEND_DEV).planned_end = d(-1)
        recalc_status(requirement, stages, NOW)
        unmark_delayed(requirement, "风险解除", NOW, stages)
        # 系统逾期仍在 → 状态保持 delayed
        assert requirement.status == "delayed"
        assert requirement.manual_delayed is False

    async def test_unmark_without_overdue_recovers(self, requirement, stages):
        make_in_progress(stages)
        mark_delayed(requirement, "风险", NOW, stages)
        unmark_delayed(requirement, "风险解除", NOW, stages)
        assert requirement.status == "in_progress"
        assert requirement.manual_delay_reason is None

    async def test_unmark_when_not_marked_rejected(self, requirement, stages):
        with pytest.raises(FlowError, match="未被人工标记"):
            unmark_delayed(requirement, "r", NOW, stages)

    async def test_unmark_requires_reason(self, requirement, stages):
        mark_delayed(requirement, "风险", NOW, stages)
        with pytest.raises(FlowError, match="必须填写原因"):
            unmark_delayed(requirement, "", NOW, stages)


# ------------------------------------------------------------- 默认环节生成

class TestMakeDefaultStages:
    def test_generates_seven_stages_in_order(self):
        defaults = make_default_stages(1)
        assert len(defaults) == 7
        assert [s["seq"] for s in defaults] == [1, 2, 3, 4, 5, 6, 7]
        assert defaults[0]["stage_type"] == "research"
        assert defaults[-1]["stage_type"] == "release"
        assert all(s["status"] == "not_started" for s in defaults)
