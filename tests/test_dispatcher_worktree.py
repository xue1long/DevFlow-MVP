"""tests/test_dispatcher_worktree.py — B7.2 阶段验证

覆盖:
- DispatchConfig.worktree_per_task 启用时创建 worktree
- 未启用时不调 create_worktree_for_plan
- worktree 创建失败 → 返回 error，不阻断 dispatch
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from devflow.engine.agent_runner import MockAgentRunner
from devflow.engine.dispatcher import (
    DispatchConfig,
    Dispatcher,
)
from devflow.model.plan import Plan
from devflow.model.task import Task


def _make_task(task_id: str = "t1") -> Task:
    return Task(
        id=task_id,
        title=f"Task {task_id}",
        module="test",
        acceptance=["ok"],
    )


def _make_plan(task_ids: list[str] | None = None) -> Plan:
    if task_ids is None:
        task_ids = ["t1"]
    return Plan(
        spec_id="spec-1",
        tasks=[_make_task(tid) for tid in task_ids],
    )


def _make_dispatcher(worktree_per_task: bool, root: Path | None = None) -> Dispatcher:
    storage = MagicMock()
    storage.get_current_plan_id.return_value = "plan-1"
    storage.get_current_phase.return_value = 5
    storage.root = root

    review_engine = MagicMock()
    review_engine.review.return_value = {"can_advance": True}

    agent_runner = MockAgentRunner()
    gate_runner = MagicMock()
    gate_runner.run_gate_by_name.return_value = {"ok": True}

    return Dispatcher(
        storage=storage,
        review_store=MagicMock(),
        review_engine=review_engine,
        agent_runner=agent_runner,
        gate_runner=gate_runner,
        config=DispatchConfig(max_rounds=5, worktree_per_task=worktree_per_task),
    )


class TestDispatcherWorktree:
    """Dispatcher.worktree 集成"""

    def test_worktree_per_task_disabled_no_worktree(self):
        """worktree_per_task=False → 不调 create_worktree_for_plan"""
        async def _run():
            dispatcher = _make_dispatcher(worktree_per_task=False, root=Path("/tmp"))
            plan = _make_plan()

            with patch(
                "devflow.engine.dispatcher.create_worktree_for_plan"
            ) as mock_wt:
                await dispatcher.dispatch_task(plan.tasks[0], plan)
                mock_wt.assert_not_called()
        asyncio.run(_run())

    def test_worktree_per_task_enabled_calls_worktree(self, tmp_path: Path):
        """worktree_per_task=True → 调 create_worktree_for_plan"""
        async def _run():
            dispatcher = _make_dispatcher(worktree_per_task=True, root=tmp_path)
            plan = _make_plan()

            with patch(
                "devflow.engine.dispatcher.create_worktree_for_plan",
                return_value=tmp_path / "workspaces" / "plan-1",
            ) as mock_wt:
                await dispatcher.dispatch_task(plan.tasks[0], plan)
                mock_wt.assert_called_once_with("plan-1", tmp_path)
        asyncio.run(_run())

    def test_worktree_creation_failure_returns_error(self):
        """worktree 创建失败 → DispatchResult.error，不抛异常"""
        async def _run():
            dispatcher = _make_dispatcher(worktree_per_task=True, root=Path("/tmp"))
            plan = _make_plan()

            with patch(
                "devflow.engine.dispatcher.create_worktree_for_plan",
                side_effect=RuntimeError("git worktree failed"),
            ):
                result = await dispatcher.dispatch_task(plan.tasks[0], plan)
                assert result.ok is False
                assert "worktree creation failed" in result.error
                assert "git worktree failed" in result.error
        asyncio.run(_run())

    def test_worktree_path_passed_to_subagent(self, tmp_path: Path):
        """worktree 路径应传给 SubagentTask"""
        async def _run():
            worktree_path = tmp_path / "workspaces" / "plan-1"
            dispatcher = _make_dispatcher(worktree_per_task=True, root=tmp_path)

            captured = {}

            class CapturingRunner(MockAgentRunner):
                async def run_subagent(self, task):
                    captured["worktree"] = task.worktree
                    return await super().run_subagent(task)

            dispatcher.agent_runner = CapturingRunner()
            plan = _make_plan()

            with patch(
                "devflow.engine.dispatcher.create_worktree_for_plan",
                return_value=worktree_path,
            ):
                await dispatcher.dispatch_task(plan.tasks[0], plan)

            assert captured.get("worktree") == worktree_path
        asyncio.run(_run())

    def test_no_root_worktree_skipped(self):
        """storage.root 为 None → 跳过 worktree（不报错）"""
        async def _run():
            dispatcher = _make_dispatcher(worktree_per_task=True, root=None)
            plan = _make_plan()

            with patch(
                "devflow.engine.dispatcher.create_worktree_for_plan"
            ) as mock_wt:
                result = await dispatcher.dispatch_task(plan.tasks[0], plan)
                # 应正常完成（mock agent + mock review + mock gate）
                assert result.ok is True
                mock_wt.assert_not_called()
        asyncio.run(_run())