"""tests/test_dispatcher.py — B2.4 阶段验证

覆盖:
- Dispatcher.dispatch_task 成功路径（agent ok + review ok + quality ok）
- Dispatcher.dispatch_task 失败路径（agent fail → replan → escalate）
- Dispatcher.dispatch_task 断路器触发（连续失败 5 轮）
- create_dispatcher() 工厂函数
- MockAgentRunner 集成
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from devflow.engine.agent_runner import MockAgentRunner
from devflow.engine.dispatcher import (
    DispatchConfig,
    DispatchResult,
    Dispatcher,
    RulingRef,
    RulingType,
    create_dispatcher,
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


def _make_plan(task_ids: list[str]) -> Plan:
    return Plan(
        spec_id="spec-1",
        tasks=[_make_task(tid) for tid in task_ids],
    )


def _make_dispatcher(plan_result: dict | None = None, fail_n: int = 0) -> Dispatcher:
    """构造 mock Dispatcher"""
    storage = MagicMock()
    storage.get_current_plan_id.return_value = "plan-1"
    storage.get_current_phase.return_value = 5

    review_store = MagicMock()
    review_engine = MagicMock()
    review_engine.review.return_value = {"can_advance": True}

    # Agent runner：前 fail_n 次失败，后续成功
    agent_runner = MockAgentRunner()

    # 调用计数器
    call_count = {"n": 0}

    async def _maybe_fail(task):
        call_count["n"] += 1
        if call_count["n"] <= fail_n:
            return {"ok": False, "error": "mock agent fail", "output": ""}
        return {"ok": True, "output": "ok", "error": ""}
    agent_runner.run_subagent = _maybe_fail  # type: ignore

    gate_runner = MagicMock()
    gate_runner.run_gate_by_name.return_value = {"ok": True}

    config = DispatchConfig(max_rounds=5)
    return Dispatcher(
        storage=storage,
        review_store=review_store,
        review_engine=review_engine,
        agent_runner=agent_runner,
        gate_runner=gate_runner,
        config=config,
    )


class TestDispatcherSuccess:
    """成功路径"""

    def test_dispatch_task_success(self):
        async def _run():
            dispatcher = _make_dispatcher(fail_n=0)
            plan = _make_plan(["t1"])
            task = plan.tasks[0]
            result = await dispatcher.dispatch_task(task, plan)
            assert result.ok is True
            assert result.task_id == "t1"
            assert result.rounds == 1
            assert result.ruling is None
            assert result.error is None
        asyncio.run(_run())

    def test_dispatch_task_success_after_one_failure(self):
        """第 1 轮失败 → REPLAN；第 2 轮成功"""
        async def _run():
            dispatcher = _make_dispatcher(fail_n=1)
            plan = _make_plan(["t1"])
            task = plan.tasks[0]
            result = await dispatcher.dispatch_task(task, plan)
            assert result.ok is True
            assert result.rounds == 2
        asyncio.run(_run())


class TestDispatcherCircuitBreaker:
    """断路器触发"""

    def test_escalate_after_max_rounds(self):
        """连续 5 轮失败 → escalate"""
        async def _run():
            # fail_n=10 确保 5 轮都失败
            dispatcher = _make_dispatcher(fail_n=10)
            plan = _make_plan(["t1"])
            task = plan.tasks[0]
            result = await dispatcher.dispatch_task(task, plan)
            assert result.ok is False
            assert result.ruling is not None
            assert result.ruling.ruling_type == RulingType.ESCALATE
            assert "超过最大轮次" in result.ruling.reason
        asyncio.run(_run())


class TestCreateDispatcher:
    """create_dispatcher() 工厂函数"""

    def test_create_dispatcher_with_mock(self, tmp_path: Path):
        """默认用 MockAgentRunner"""
        dispatcher = create_dispatcher(tmp_path, use_real_agent=False)
        assert isinstance(dispatcher, Dispatcher)
        assert isinstance(dispatcher.config, DispatchConfig)
        assert isinstance(dispatcher.agent_runner, MockAgentRunner)
        assert dispatcher.config.max_rounds == 5

    def test_create_dispatcher_with_real_agent(self, tmp_path: Path):
        """use_real_agent=True 用 ClaudeCodeAgentRunner"""
        from devflow.engine.agent_runner import ClaudeCodeAgentRunner

        dispatcher = create_dispatcher(tmp_path, use_real_agent=True)
        assert isinstance(dispatcher.agent_runner, ClaudeCodeAgentRunner)

    def test_create_dispatcher_with_custom_command(self, tmp_path: Path):
        """agent_command="my-agent" 用 GenericAgentRunner"""
        from devflow.engine.agent_runner import GenericAgentRunner

        dispatcher = create_dispatcher(
            tmp_path,
            agent_command="my-agent",
            use_real_agent=True,
        )
        assert isinstance(dispatcher.agent_runner, GenericAgentRunner)