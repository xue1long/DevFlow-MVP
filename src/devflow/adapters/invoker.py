"""DevFlow 引擎调用入口抽象

v0.3 纪律（C2 + B1.2 阶段）：
- 统一 Skill / MCP / CLI 三种调用面
- C2 阶段仅做最小实现（CliEngineInvoker）
- B1.2 阶段补 InProcessEngineInvoker（MCP Server 同进程调用）
- 其他实现（GenericAgentRunner）待 SDD 阶段择机启动
"""
from __future__ import annotations

import json
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import typer


class EngineInvoker(ABC):
    """引擎调用入口抽象

    Skill 形态与 MCP 形态共享同一个 invoker，差异仅在外层协议解析。
    """

    @abstractmethod
    def invoke(self, skill_name: str, args: dict[str, Any]) -> dict[str, Any]:
        """调用引擎命令，返回 JSON 结果

        Args:
            skill_name: 如 "devflow.review"
            args: 命令参数 dict

        Returns:
            CLI 输出的 JSON dict

        Raises:
            RuntimeError: 当 CLI 退出码非零时
        """


class CliEngineInvoker(EngineInvoker):
    """通过 subprocess 调用 CLI（C2 阶段实现）

    工作目录 = workspace_root（即 cwd 即 devflow 工作区根目录）

    默认使用 `devflow` 命令（已安装到 PATH）；如未安装，可通过
    PYTHON 环境变量指定 Python 解释器，自动降级到 `python -m devflow.cli`。
    """

    def __init__(self, workspace_root: Path, command: str = "devflow"):
        self.workspace_root = Path(workspace_root)
        self.command = command

    def invoke(self, skill_name: str, args: dict[str, Any]) -> dict[str, Any]:
        cmd_name = skill_name.removeprefix("devflow.")
        # 优先尝试直接命令，未找到时降级到 python -m devflow.cli
        cmd = [self.command, cmd_name, *[str(v) for v in args.values()]]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=self.workspace_root,
            )
        except FileNotFoundError:
            # 降级：devflow 未在 PATH，用 python -m
            import sys
            cmd = [sys.executable, "-m", "devflow.cli", cmd_name, *[str(v) for v in args.values()]]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=self.workspace_root,
            )
        if result.returncode != 0:
            raise RuntimeError(
                f"devflow {cmd_name} 退出码 {result.returncode}: {result.stderr}"
            )
        return json.loads(result.stdout)


class InProcessEngineInvoker(EngineInvoker):
    """同进程内调用 typer app（B1.2 阶段 — MCP Server 用）

    优势：MCP Server 启动时无需 subprocess 启动新进程，性能更好。
    局限：当前 typer CliRunner 不支持在已有 loop 中调用（MCP Server 自身不冲突）。
    """

    def __init__(self, app: typer.Typer, workspace_root: Path):
        self.app = app
        self.workspace_root = Path(workspace_root)

    def invoke(self, skill_name: str, args: dict[str, Any]) -> dict[str, Any]:
        from typer.testing import CliRunner

        cmd_name = skill_name.removeprefix("devflow.")
        runner = CliRunner()

        # 切换工作目录执行（devflow 命令假设 cwd 是 workspace_root）
        import os
        original_cwd = os.getcwd()
        try:
            os.chdir(self.workspace_root)
            result = runner.invoke(
                self.app,
                [cmd_name, *[str(v) for v in args.values()]],
            )
        finally:
            os.chdir(original_cwd)

        if result.exit_code != 0:
            raise RuntimeError(
                f"devflow {cmd_name} 退出码 {result.exit_code}: {result.output}"
            )

        # CliRunner.output 是 stdout 文本，可能含异常信息
        # 尝试解析为 JSON，失败则返回原文本包装
        try:
            return json.loads(result.output)
        except json.JSONDecodeError:
            return {"ok": False, "raw_output": result.output, "exit_code": result.exit_code}