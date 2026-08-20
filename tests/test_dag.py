"""tests/test_dag.py — B5.1 阶段验证

覆盖:
- 无环 DAG（含空图、单节点、链式、星形）
- 自环（A -> A）
- 两节点环（A -> B -> A）
- 多节点环（A -> B -> C -> A）
- 不存在的依赖节点（应被忽略，不算环）
- Plan.validate_assignment=True：append/mutation 后重跑 DAG 校验
"""
from __future__ import annotations

import pytest

from devflow.model.plan import Plan
from devflow.model.task import Task
from devflow.util.dag import detect_cycle


class TestNoCycle:
    """合法 DAG 应返回空列表"""

    def test_empty(self):
        assert detect_cycle([], []) == []

    def test_single_node_no_deps(self):
        assert detect_cycle(["a"], [[]]) == []

    def test_chain(self):
        """链式 a -> b -> c"""
        assert detect_cycle(["a", "b", "c"], [["b"], ["c"], []]) == []

    def test_diamond(self):
        """菱形 a -> b, a -> c, b -> d, c -> d"""
        # a -> b -> d
        # a -> c -> d
        assert detect_cycle(["a", "b", "c", "d"], [["b", "c"], ["d"], ["d"], []]) == []

    def test_independent_nodes(self):
        """多个独立节点"""
        assert detect_cycle(["a", "b", "c"], [[], [], []]) == []

    def test_tree(self):
        """树形 a -> {b, c}, b -> {d, e}"""
        assert detect_cycle(
            ["a", "b", "c", "d", "e"],
            [["b", "c"], ["d", "e"], [], [], []],
        ) == []


class TestSelfLoop:
    """自环 A -> A"""

    def test_self_loop(self):
        errors = detect_cycle(["a"], [["a"]])
        assert len(errors) == 1
        assert "a -> a" in errors[0]


class TestTwoNodeCycle:
    """两节点环 A -> B -> A"""

    def test_two_node_cycle(self):
        errors = detect_cycle(["a", "b"], [["b"], ["a"]])
        assert len(errors) == 1
        # 环路径应包含两个节点
        assert "a" in errors[0] and "b" in errors[0]


class TestMultiNodeCycle:
    """多节点环 A -> B -> C -> A"""

    def test_three_node_cycle(self):
        errors = detect_cycle(
            ["a", "b", "c"],
            [["b"], ["c"], ["a"]],
        )
        assert len(errors) == 1
        assert all(n in errors[0] for n in ["a", "b", "c"])

    def test_four_node_cycle(self):
        errors = detect_cycle(
            ["a", "b", "c", "d"],
            [["b"], ["c"], ["d"], ["a"]],
        )
        assert len(errors) == 1
        assert all(n in errors[0] for n in ["a", "b", "c", "d"])


class TestInvalidDependencies:
    """依赖中引用不存在的节点（应忽略，不算环）"""

    def test_nonexistent_dep_ignored(self):
        """a 依赖 "ghost"，ghost 不在 node_ids 中"""
        # 不应报错（ghost 被过滤）
        errors = detect_cycle(["a", "b"], [["ghost", "b"], []])
        assert errors == []

    def test_self_loop_with_invalid_dep(self):
        """a 自环 + 引用不存在的节点"""
        errors = detect_cycle(["a", "b"], [["a", "ghost"], []])
        assert len(errors) == 1
        assert "a -> a" in errors[0]


class TestPlanValidateAssignment:
    """v0.3.4 回归: Plan.validate_assignment=True 必须使 Plan 顶层字段突变后重跑 DAG 校验

    注: pydantic v2 对 list 元素的内嵌属性赋值（如 plan.tasks[i].blocked_by = ...）
    不会触发宿主模型的 model_validator。我们覆盖 Plan 顶层 tasks 整体替换路径，
    这是 add_task 写盘前必经的 model_dump 触发的链路。
    """

    def test_reassign_tasks_with_cycle_raises(self):
        """整体替换 plan.tasks 为含循环依赖的列表，必须抛 ValueError"""
        plan = Plan(
            spec_id="s1",
            tasks=[
                Task(id="task-1", title="x", module="m", acceptance=["a"]),
            ],
        )
        # 构造 task-2 ↔ task-3 互依赖的循环
        cyclic_tasks = [
            Task(
                id="task-2", title="y", module="m", acceptance=["a"],
                blocked_by=["task-3"],
            ),
            Task(
                id="task-3", title="z", module="m", acceptance=["a"],
                blocked_by=["task-2"],
            ),
        ]
        with pytest.raises(ValueError, match="环检测"):
            plan.tasks = cyclic_tasks

    def test_reassign_tasks_without_cycle_ok(self):
        """整体替换 plan.tasks 为合法 DAG，不抛异常"""
        plan = Plan(
            spec_id="s1",
            tasks=[
                Task(id="task-1", title="x", module="m", acceptance=["a"]),
            ],
        )
        valid_tasks = [
            Task(id="task-2", title="y", module="m", acceptance=["a"]),
            Task(
                id="task-3", title="z", module="m", acceptance=["a"],
                blocked_by=["task-2"],
            ),
        ]
        plan.tasks = valid_tasks
        assert len(plan.tasks) == 2
        assert plan.tasks[1].blocked_by == ["task-2"]