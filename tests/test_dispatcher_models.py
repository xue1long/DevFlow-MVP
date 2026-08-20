"""tests/test_dispatcher_models.py — B2.1 阶段验证

覆盖:
- DispatchConfig 默认值与字段约束
- SubagentTask 必填字段校验
- RulingRef 4 类裁决类型与 is_terminal/is_escalation 判断
"""
from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from devflow.engine.dispatcher import (
    DispatchConfig,
    RulingRef,
    RulingType,
    SubagentTask,
)


class TestDispatchConfig:
    """DispatchConfig 默认值与约束"""

    def test_defaults(self):
        config = DispatchConfig()
        assert config.max_rounds == 5
        assert config.parallel is False
        assert config.worktree_per_task is False
        assert "implementer" in config.model_tiers
        assert "reviewer" in config.model_tiers

    def test_max_rounds_constraint(self):
        """max_rounds 必须在 1-20 之间"""
        with pytest.raises(ValidationError):
            DispatchConfig(max_rounds=0)
        with pytest.raises(ValidationError):
            DispatchConfig(max_rounds=21)

    def test_model_tiers_can_override(self):
        config = DispatchConfig(
            model_tiers={"implementer": "opus", "reviewer": "haiku"},
        )
        assert config.model_tiers["implementer"] == "opus"


class TestSubagentTask:
    """SubagentTask 必填字段"""

    def test_minimal_required(self):
        task = SubagentTask(task_id="t1", prompt="实现 Task t1")
        assert task.task_id == "t1"
        assert task.prompt == "实现 Task t1"
        assert task.worktree is None
        assert task.model_tier == "implementer"

    def test_with_worktree(self, tmp_path: Path):
        task = SubagentTask(
            task_id="t1",
            prompt="p",
            worktree=tmp_path,
        )
        assert task.worktree == tmp_path

    def test_missing_task_id_fails(self):
        with pytest.raises(ValidationError):
            SubagentTask(prompt="p")  # type: ignore[call-arg]

    def test_missing_prompt_fails(self):
        with pytest.raises(ValidationError):
            SubagentTask(task_id="t1")  # type: ignore[call-arg]


class TestRulingRef:
    """RulingRef 4 类裁决"""

    def test_skip_is_terminal_not_escalation(self):
        r = RulingRef(task_id="t1", ruling_type=RulingType.SKIP, reason="user skipped")
        assert r.is_terminal() is True
        assert r.is_escalation() is False

    def test_replan_is_neither(self):
        r = RulingRef(task_id="t1", ruling_type=RulingType.REPLAN, reason="retry")
        assert r.is_terminal() is False
        assert r.is_escalation() is False

    def test_escalate_is_escalation_not_terminal(self):
        r = RulingRef(task_id="t1", ruling_type=RulingType.ESCALATE, reason="max rounds")
        assert r.is_terminal() is False
        assert r.is_escalation() is True

    def test_halt_is_both(self):
        r = RulingRef(task_id="t1", ruling_type=RulingType.HALT, reason="user halted")
        assert r.is_terminal() is True
        assert r.is_escalation() is True

    def test_invalid_ruling_type_accepted(self):
        """Pydantic 不限制 enum 字符串，错误裁决类型不抛异常（语义层校验）"""
        # 这是设计选择：ruling_type 是字符串字段而非 Enum，
        # 允许外部系统传入扩展裁决类型，Dispatcher 内部校验
        r = RulingRef(task_id="t1", ruling_type="unknown", reason="test")
        assert r.ruling_type == "unknown"