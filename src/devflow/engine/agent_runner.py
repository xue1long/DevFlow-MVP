"""Agent 子进程派发（B2.3 阶段）

v0.3 纪律：
- devflow 编排 Agent，不实现 Agent
- 不同 Agent 平台的 CLI 参数格式不同，必须抽象

抽象层次：
- AgentRunner（ABC）：定义 run_subagent 接口
- ClaudeCodeAgentRunner：用环境变量传递 prompt（跨平台稳定）
- GenericAgentRunner：通用 subprocess，通过 stdin 传参
- 未来可扩展：CodexAgentRunner / CursorAgentRunner / 自研 Agent

CLI 参数选择：
- claude --continue / claude -p "..." 是当前 Claude Code CLI 的常见用法
- 但具体参数依赖 fastmcp 调研结果（v3 方案标注的 M5.3 风险点）
- 当前实现用环境变量 + 简化命令行，避免硬编码未核实的 CLI 参数
"""
from __future__ import annotations

import asyncio
import os
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Optional

from .dispatcher import SubagentTask


class AgentRunner(ABC):
    """通用 Agent 子进程派发抽象

    不绑定特定 Agent 平台的 CLI 格式。
    不同实现负责把 SubagentTask 翻译成对应 CLI。
    """

    @abstractmethod
    async def run_subagent(self, task: SubagentTask) -> dict[str, Any]:
        """异步派发单个子代理任务

        Returns:
            {"ok": bool, "output": str, "error": str}
        """


class ClaudeCodeAgentRunner(AgentRunner):
    """Claude Code CLI 适配

    设计选择：
    - 用环境变量 DEVFLOW_TASK_ID / DEVFLOW_PROMPT 传参（跨平台稳定）
    - 子命令简化（不预设 --task --prompt 等未核实参数）
    - 真实 Claude Code 集成待 B 阶段扩展时通过 `claude --help` 调研
    """

    def __init__(self, worktree_root: Optional[Path] = None):
        self.worktree_root = worktree_root

    async def run_subagent(self, task: SubagentTask) -> dict[str, Any]:
        env = {
            **os.environ,
            "DEVFLOW_TASK_ID": task.task_id,
            "DEVFLOW_PROMPT": task.prompt,
        }
        cwd = task.worktree or self.worktree_root or Path.cwd()

        # 简化调用，使用 --continue 模式（如果有 Claude Code 会话）
        # 实际集成时根据 `claude --help` 输出调整
        cmd = ["claude", "--continue"]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=env,
        )
        stdout, stderr = await proc.communicate()
        return {
            "ok": proc.returncode == 0,
            "output": stdout.decode(errors="replace"),
            "error": stderr.decode(errors="replace"),
        }


class GenericAgentRunner(AgentRunner):
    """通用 Agent 派发（通过 stdin 传参）

    适用场景：自定义 Agent 脚本（Python / Node.js / shell）
    协议：stdin 接收 KEY=VALUE 格式
    """

    def __init__(self, command: str, worktree_root: Optional[Path] = None):
        self.command = command
        self.worktree_root = worktree_root

    async def run_subagent(self, task: SubagentTask) -> dict[str, Any]:
        cwd = task.worktree or self.worktree_root or Path.cwd()
        prompt_input = f"TASK_ID={task.task_id}\nPROMPT={task.prompt}\n"

        proc = await asyncio.create_subprocess_exec(
            self.command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )
        stdout, stderr = await proc.communicate(input=prompt_input.encode())
        return {
            "ok": proc.returncode == 0,
            "output": stdout.decode(errors="replace"),
            "error": stderr.decode(errors="replace"),
        }


class MockAgentRunner(AgentRunner):
    """测试用 Mock Agent Runner（不调任何子进程）

    返回固定 ok=True + 包含 task_id 的输出
    用于 Dispatcher 单测，无需启动真实 Agent
    """

    async def run_subagent(self, task: SubagentTask) -> dict[str, Any]:
        return {
            "ok": True,
            "output": f"mock: implemented task {task.task_id}\n",
            "error": "",
        }