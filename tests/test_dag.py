"""tests/test_dag.py — B5.1 阶段验证

覆盖:
- 无环 DAG（含空图、单节点、链式、星形）
- 自环（A -> A）
- 两节点环（A -> B -> A）
- 多节点环（A -> B -> C -> A）
- 不存在的依赖节点（应被忽略，不算环）
"""
from __future__ import annotations

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