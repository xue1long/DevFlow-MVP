"""tests/test_plan_dag.py — B5.2 阶段验证

覆盖:
- 合法 Plan 创建成功
- 自环 Plan 创建失败（model_validator 拦截）
- 多节点环 Plan 创建失败
- 显式 validate_dag() 方法返回错误列表
- v0.3.3 buffer 字段与 DAG 校验不冲突
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from devflow.model.plan import Plan
from devflow.model.task import Task


def _make_task(task_id: str, blocked_by: list[str] | None = None) -> Task:
    """构造最小合法 Task"""
    return Task(
        id=task_id,
        title=f"Task {task_id}",
        module="test",
        acceptance=["ok"],
        blocked_by=blocked_by or [],
    )


class TestPlanValidDag:
    """合法 Plan 创建"""

    def test_empty_plan(self):
        plan = Plan(spec_id="spec-1")
        assert plan.tasks == []

    def test_no_deps(self):
        plan = Plan(spec_id="spec-1", tasks=[
            _make_task("a"),
            _make_task("b"),
        ])
        assert len(plan.tasks) == 2

    def test_chain_deps(self):
        plan = Plan(spec_id="spec-1", tasks=[
            _make_task("a", ["b"]),
            _make_task("b", ["c"]),
            _make_task("c"),
        ])
        assert len(plan.tasks) == 3

    def test_diamond(self):
        plan = Plan(spec_id="spec-1", tasks=[
            _make_task("a", ["b", "c"]),
            _make_task("b", ["d"]),
            _make_task("c", ["d"]),
            _make_task("d"),
        ])
        assert len(plan.tasks) == 4

    def test_with_buffer_field(self):
        """v0.3.3 buffer 字段与 DAG 校验不冲突"""
        plan = Plan(spec_id="spec-1", buffer=0.3)
        assert plan.buffer == 0.3


class TestPlanInvalidDag:
    """非法 Plan 创建应失败（model_validator 拦截）"""

    def test_self_loop(self):
        with pytest.raises(ValidationError) as exc_info:
            Plan(spec_id="spec-1", tasks=[
                _make_task("a", ["a"]),
            ])
        assert "DAG 不合法" in str(exc_info.value)
        assert "a -> a" in str(exc_info.value)

    def test_two_node_cycle(self):
        with pytest.raises(ValidationError) as exc_info:
            Plan(spec_id="spec-1", tasks=[
                _make_task("a", ["b"]),
                _make_task("b", ["a"]),
            ])
        assert "DAG 不合法" in str(exc_info.value)

    def test_three_node_cycle(self):
        with pytest.raises(ValidationError) as exc_info:
            Plan(spec_id="spec-1", tasks=[
                _make_task("a", ["b"]),
                _make_task("b", ["c"]),
                _make_task("c", ["a"]),
            ])
        assert "DAG 不合法" in str(exc_info.value)

    def test_partial_cycle(self):
        """部分节点有环，部分合法"""
        with pytest.raises(ValidationError):
            Plan(spec_id="spec-1", tasks=[
                _make_task("a", ["b"]),
                _make_task("b", ["a"]),
                _make_task("c"),  # 合法但与环共存
            ])


class TestPlanValidateDagMethod:
    """显式 validate_dag() 方法"""

    def test_valid_returns_empty(self):
        plan = Plan(spec_id="spec-1", tasks=[
            _make_task("a"),
            _make_task("b", ["a"]),
        ])
        assert plan.validate_dag() == []

    def test_invalid_returns_errors(self):
        """绕过 model_validator 直接构造（不应触发 model_validator）
        用 model_construct 是 pydantic 跳过验证的方式
        """
        plan = Plan.model_construct(
            spec_id="spec-1",
            tasks=[_make_task("a", ["a"])],
            domain_ref="",
            buffer=None,
        )
        errors = plan.validate_dag()
        assert len(errors) == 1
        assert "环检测" in errors[0]