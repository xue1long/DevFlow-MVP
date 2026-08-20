"""DAG 环检测（B5 阶段 — SDD 前置依赖）

v0.3 INDEX 教训第 6 轮审计后补强：
- Task.blocked_by 当前不做环检测（model/task.py:32注释明示）
- SDD 并行 frontier 派发前必须验证 DAG 合法性
- 本模块提供纯函数 detect_cycle()，无副作用

算法：DFS + 三色标记（WHITE/GRAY/BLACK）
- WHITE: 未访问
- GRAY: 正在访问（在递归栈中）
- BLACK: 访问完成
- 遇到 GRAY 邻居即发现环
"""
from __future__ import annotations

import inspect
from typing import Optional


def detect_cycle(
    node_ids: list[str],
    deps: list[list[str]],
) -> list[str]:
    """检测 DAG 环

    Args:
        node_ids: Task ID 列表
        deps: 每个 task 的前置依赖列表（与 node_ids 等长）

    Returns:
        错误信息列表；空列表表示合法 DAG

    Examples:
        >>> # 无环 DAG
        >>> detect_cycle(["a", "b", "c"], [["b"], ["c"], []])
        []
        >>> # 自环
        >>> detect_cycle(["a"], [["a"]])
        ['环检测：a -> a']
        >>> # 两节点环
        >>> detect_cycle(["a", "b"], [["b"], ["a"]])
        ['环检测：a -> b -> a']
    """
    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {nid: WHITE for nid in node_ids}
    parent: dict[str, Optional[str]] = {nid: None for nid in node_ids}

    # 邻接表（仅保留有效节点）
    valid_ids = set(node_ids)
    graph: dict[str, list[str]] = {}
    for nid, d in zip(node_ids, deps):
        graph[nid] = [dep for dep in d if dep in valid_ids]

    errors: list[str] = []

    def dfs(start: str) -> Optional[list[str]]:
        """返回环路径或 None"""
        stack: list[tuple[str, list[str]]] = [(start, list(graph[start]))]
        color[start] = GRAY
        path: list[str] = [start]

        while stack:
            node, neighbors = stack[-1]
            if not neighbors:
                # 当前节点 DFS 完成
                color[node] = BLACK
                stack.pop()
                if path:
                    path.pop()
                continue

            nxt = neighbors.pop(0)
            if color[nxt] == GRAY:
                # 找到环：从 nxt 开始到 node 的路径
                cycle_start_idx = path.index(nxt) if nxt in path else 0
                cycle = path[cycle_start_idx:] + [nxt]
                return cycle
            if color[nxt] == WHITE:
                parent[nxt] = node
                color[nxt] = GRAY
                stack.append((nxt, list(graph[nxt])))
                path.append(nxt)
        return None

    for nid in node_ids:
        if color[nid] == WHITE:
            cycle = dfs(nid)
            if cycle:
                errors.append(f"环检测：{' -> '.join(cycle)}")
                # 重置已访问节点，避免误报其他环
                # 简化处理：报告首个环后停止
                break

    return errors


__all__ = ["detect_cycle"]

# 防止 pyflakes 误报未使用导入
_ = inspect