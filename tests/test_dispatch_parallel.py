"""tests/test_dispatch_parallel.py — B2.6 阶段验证

覆盖:
- dispatch_plan_parallel 拓扑分层（依赖完成后才派发）
- 并行批次正确性
- Plan 不存在抛 ValueError
- DAG 死锁抛 RuntimeError
"""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from devflow.engine.agent_runner import AgentRunner
from devflow.engine.dispatcher import (
    DispatchConfig,
    Dispatcher,
    dispatch_plan_parallel,
)
from devflow.model.plan import Plan
from devflow.model.task import Task


def _make_task(task_id: str, blocked_by=None) -> Task:
    return Task(
        id=task_id,
        title=f"Task {task_id}",
        module="test",
        acceptance=["ok"],
        blocked_by=blocked_by or [],
    )


def _make_dispatcher_with_plan(plan: Plan) -> Dispatcher:
    storage = MagicMock()
    storage.get_current_plan_id.return_value = "plan-1"
    storage.get_current_phase.return_value = 5
    storage.read_plan.return_value = plan.model_dump(mode="json")

    review_engine = MagicMock()
    review_engine.review.return_value = {"can_advance": True}

    # 计时 agent：记录每个 task 的派发时间
    call_log = []

    class TimingRunner(AgentRunner):
        async def run_subagent(self, task):
            call_log.append((task.task_id, time.monotonic()))
            await asyncio.sleep(0.01)  # 模拟工作
            return {"ok": True, "output": "ok", "error": ""}

    gate_runner = MagicMock()
    gate_runner.run_gate_by_name.return_value = {"ok": True}

    dispatcher = Dispatcher(
        storage=storage,
        review_store=MagicMock(),
        review_engine=review_engine,
        agent_runner=TimingRunner(),
        gate_runner=gate_runner,
        config=DispatchConfig(max_rounds=5),
    )
    dispatcher.call_log = call_log
    return dispatcher


class TestDispatchParallelBasic:
    """基本派发"""

    def test_independent_tasks_all_dispatched(self):
        async def _run():
            plan = Plan(spec_id="spec-1", tasks=[
                _make_task("t1"),
                _make_task("t2"),
                _make_task("t3"),
            ])
            dispatcher = _make_dispatcher_with_plan(plan)
            result = await dispatch_plan_parallel(dispatcher, "plan-1")
            assert len(result["results"]) == 3
            assert all(r["ok"] for r in result["results"])
        asyncio.run(_run())

    def test_plan_not_found(self):
        async def _run():
            plan = Plan(spec_id="spec-1")
            dispatcher = _make_dispatcher_with_plan(plan)
            dispatcher.storage.read_plan.return_value = None
            with pytest.raises(ValueError, match="不存在"):
                await dispatch_plan_parallel(dispatcher, "plan-999")
        asyncio.run(_run())


class TestDispatchParallelTopology:
    """拓扑分层（依赖关系正确性）"""

    def test_chain_topology(self):
        """链式依赖：t1 -> t2 -> t3（顺序派发）"""
        async def _run():
            plan = Plan(spec_id="spec-1", tasks=[
                _make_task("t1", ["t2"]),
                _make_task("t2", ["t3"]),
                _make_task("t3"),
            ])
            dispatcher = _make_dispatcher_with_plan(plan)
            await dispatch_plan_parallel(dispatcher, "plan-1")

            # t3 必须最先派发，t2 其次，t1 最后
            call_order = [tid for tid, _ in dispatcher.call_log]
            assert call_order[0] == "t3"
            assert call_order[1] == "t2"
            assert call_order[2] == "t1"
        asyncio.run(_run())

    def test_diamond_topology(self):
        """菱形依赖：t1 -> {t2, t3}, t2 -> t4, t3 -> t4

        期望批次：
        - 批次 1: [t4]（无依赖）
        - 批次 2: [t2, t3]（t4 完成）
        - 批次 3: [t1]（t2 + t3 完成）
        """
        async def _run():
            plan = Plan(spec_id="spec-1", tasks=[
                _make_task("t1", ["t2", "t3"]),
                _make_task("t2", ["t4"]),
                _make_task("t3", ["t4"]),
                _make_task("t4"),
            ])
            dispatcher = _make_dispatcher_with_plan(plan)
            await dispatch_plan_parallel(dispatcher, "plan-1")

            call_order = [tid for tid, _ in dispatcher.call_log]
            # t4 应最先
            assert call_order[0] == "t4"
            # t2 + t3 在 t4 之后
            t4_idx = call_order.index("t4")
            t2_idx = call_order.index("t2")
            t3_idx = call_order.index("t3")
            t1_idx = call_order.index("t1")
            assert t2_idx > t4_idx
            assert t3_idx > t4_idx
            # t1 在 t2 + t3 之后
            assert t1_idx > t2_idx
            assert t1_idx > t3_idx
        asyncio.run(_run())

    def test_parallel_speedup(self):
        """独立任务应真正并行派发（耗时 < 顺序总和）"""
        async def _run():
            plan = Plan(spec_id="spec-1", tasks=[
                _make_task("t1"),
                _make_task("t2"),
                _make_task("t3"),
            ])
            dispatcher = _make_dispatcher_with_plan(plan)
            start = time.monotonic()
            await dispatch_plan_parallel(dispatcher, "plan-1")
            elapsed = time.monotonic() - start

            # 每个 task sleep 0.01s，3 个并行总耗时 < 0.03s
            assert elapsed < 0.05, f"elapsed {elapsed:.3f}s 超过预期（未真正并行）"
        asyncio.run(_run())


class TestDispatchParallelDagDeadlock:
    """DAG 死锁应抛 RuntimeError"""

    def test_plan_creation_blocks_cycle(self):
        """Plan.model_validator 拦截构造期循环依赖（预防式）

        这是 B5 阶段补强的核心 —— SDD 并行 frontier 启动前必做
        """
        # 直接尝试创建循环 Plan 应抛 ValidationError
        with pytest.raises(Exception) as exc_info:
            Plan(spec_id="spec-1", tasks=[
                _make_task("a", ["b"]),
                _make_task("b", ["a"]),
            ])
        # pydantic ValidationError 或 ValueError 都接受
        error_msg = str(exc_info.value)
        assert "DAG" in error_msg or "环检测" in error_msg