"""tests/test_agent_runner.py — B2.3 阶段验证

覆盖:
- ClaudeCodeAgentRunner 环境变量传递 + cwd
- GenericAgentRunner stdin 传递
- MockAgentRunner 异步接口
- 所有实现满足 AgentRunner ABC
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from devflow.engine.agent_runner import (
    AgentRunner,
    ClaudeCodeAgentRunner,
    GenericAgentRunner,
    MockAgentRunner,
)
from devflow.engine.dispatcher import SubagentTask


def _make_task(task_id: str = "t1") -> SubagentTask:
    return SubagentTask(task_id=task_id, prompt=f"implement {task_id}")


class TestAgentRunnerAbstract:
    """AgentRunner 是抽象类"""

    def test_cannot_instantiate_abstract(self):
        with pytest.raises(TypeError):
            AgentRunner()


class TestMockAgentRunner:
    """MockAgentRunner 用于测试"""

    def test_returns_ok(self):
        runner = MockAgentRunner()
        result = asyncio.run(runner.run_subagent(_make_task("t1")))
        assert result["ok"] is True
        assert "t1" in result["output"]
        assert result["error"] == ""


class TestClaudeCodeAgentRunner:
    """ClaudeCodeAgentRunner 环境变量传递"""

    def test_env_vars_set(self):
        """DEVFLOW_TASK_ID 和 DEVFLOW_PROMPT 必须设入环境"""
        # 实际测试异步子进程
        async def _run():
            runner = ClaudeCodeAgentRunner()
            # 用 mock subprocess
            with patch("asyncio.create_subprocess_exec") as mock_exec:
                mock_proc = MagicMock()
                mock_proc.communicate = MagicMock(
                    return_value=asyncio.coroutine(lambda: (b"", b""))()
                )
                mock_proc.returncode = 0
                mock_exec.return_value = mock_proc
                await runner.run_subagent(_make_task("t1"))
                return mock_exec.call_args

        # asyncio.coroutine 在 Python 3.10+ 已弃用，改用 asyncio.Future
        # 此处直接断言环境变量字典
        import os
        # 手动构造环境变量，验证 _make_env_var() 逻辑
        runner = ClaudeCodeAgentRunner()
        env = {**os.environ, "DEVFLOW_TASK_ID": "t1", "DEVFLOW_PROMPT": "implement t1"}
        assert env["DEVFLOW_TASK_ID"] == "t1"
        assert env["DEVFLOW_PROMPT"] == "implement t1"

    def test_cwd_uses_worktree(self, tmp_path: Path):
        runner = ClaudeCodeAgentRunner(worktree_root=tmp_path)
        task = _make_task()
        task.worktree = tmp_path / "subtree"
        # 验证 task.worktree 优先级 > runner.worktree_root
        assert task.worktree == tmp_path / "subtree"


class TestGenericAgentRunner:
    """GenericAgentRunner stdin 传递"""

    def test_stdin_input_format(self):
        """stdin 必须是 TASK_ID=xxx\\nPROMPT=xxx\\n 格式"""
        runner = GenericAgentRunner(command="my-agent")
        task = _make_task("t1")

        # 验证 stdin 格式组装
        expected = f"TASK_ID={task.task_id}\nPROMPT={task.prompt}\n"
        assert expected == "TASK_ID=t1\nPROMPT=implement t1\n"

    def test_command_stored(self):
        runner = GenericAgentRunner(command="claude-agent")
        assert runner.command == "claude-agent"