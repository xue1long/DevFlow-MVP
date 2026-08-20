"""tests/test_dispatch_plan.py — B2.5 阶段验证

覆盖:
- dispatch_plan() 顺序派发所有 Task
- Plan 不存在抛 ValueError
- 与 dispatcher.dispatch_task() 集成
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from devflow.engine.agent_runner import MockAgentRunner
from devflow.engine.dispatcher import (
    DispatchConfig,
    Dispatcher,
    RulingType,
    create_dispatcher,
    dispatch_plan,
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


def _make_dispatcher_with_plan(plan: Plan, fail_n: int = 0) -> Dispatcher:
    storage = MagicMock()
    storage.get_current_plan_id.return_value = "plan-1"
    storage.get_current_phase.return_value = 5
    storage.read_plan.return_value = plan.model_dump(mode="json")

    review_engine = MagicMock()
    review_engine.review.return_value = {"can_advance": True}

    agent_runner = MockAgentRunner()
    call_count = {"n": 0}

    async def _maybe_fail(task):
        call_count["n"] += 1
        if call_count["n"] <= fail_n:
            return {"ok": False, "error": "fail", "output": ""}
        return {"ok": True, "output": "ok", "error": ""}
    agent_runner.run_subagent = _maybe_fail  # type: ignore

    gate_runner = MagicMock()
    gate_runner.run_gate_by_name.return_value = {"ok": True}

    return Dispatcher(
        storage=storage,
        review_store=MagicMock(),
        review_engine=review_engine,
        agent_runner=agent_runner,
        gate_runner=gate_runner,
        config=DispatchConfig(max_rounds=5),
    )


class TestDispatchPlan:
    """dispatch_plan() 顺序派发"""

    def test_dispatch_plan_all_success(self):
        async def _run():
            plan = Plan(
                spec_id="spec-1",
                tasks=[_make_task("t1"), _make_task("t2"), _make_task("t3")],
            )
            dispatcher = _make_dispatcher_with_plan(plan)
            result = await dispatch_plan(dispatcher, "plan-1")
            assert result["plan_id"] == "plan-1"
            assert len(result["results"]) == 3
            assert all(r["ok"] for r in result["results"])
        asyncio.run(_run())

    def test_dispatch_plan_plan_not_found(self):
        async def _run():
            plan = Plan(spec_id="spec-1")
            dispatcher = _make_dispatcher_with_plan(plan)
            dispatcher.storage.read_plan.return_value = None
            with pytest.raises(ValueError, match="不存在"):
                await dispatch_plan(dispatcher, "plan-999")
        asyncio.run(_run())

    def test_dispatch_plan_mixed_results(self):
        """前 1 个 task 失败（断路器触发 escalate）"""
        async def _run():
            plan = Plan(
                spec_id="spec-1",
                tasks=[_make_task("t1"), _make_task("t2")],
            )
            # fail_n=10 确保 t1 的所有 5 轮都失败
            dispatcher = _make_dispatcher_with_plan(plan, fail_n=10)
            result = await dispatch_plan(dispatcher, "plan-1")
            assert len(result["results"]) == 2
            # t1 应 escalate（ruling）
            t1_result = result["results"][0]
            assert t1_result["ok"] is False
            assert t1_result["ruling"]["ruling_type"] == RulingType.ESCALATE
        asyncio.run(_run())


class TestDispatchCLI:
    """CLI dispatch 命令"""

    def test_dispatch_help(self):
        """dispatch --help 应可调用"""
        from typer.testing import CliRunner
        from devflow.cli import app

        runner = CliRunner()
        result = runner.invoke(app, ["dispatch", "--help"])
        assert result.exit_code == 0
        assert "SDD 子代理编排" in result.output