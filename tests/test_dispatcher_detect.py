"""tests/test_dispatcher_detect.py — C7.3 阶段验证

覆盖:
- create_dispatcher() 默认 auto_detect_platform=True
- 检测到 Claude Code → ClaudeCodeAgentRunner
- 检测到 WorkBuddy / CodeBuddy → GenericAgentRunner
- adapter-export --auto-detect flag
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from devflow.adapters.detect import Platform
from devflow.cli import app as cli_app
from devflow.engine.agent_runner import (
    ClaudeCodeAgentRunner,
    GenericAgentRunner,
    MockAgentRunner,
)
from devflow.engine.dispatcher import create_dispatcher


class TestCreateDispatcherAutoDetect:
    """create_dispatcher() 自动检测平台"""

    def test_default_auto_detect_disabled_returns_mock(self, tmp_path, monkeypatch):
        """auto_detect_platform=False → MockAgentRunner（即使有 CLAUDE_CODE）"""
        monkeypatch.setenv("CLAUDE_CODE", "1")
        dispatcher = create_dispatcher(tmp_path, auto_detect_platform=False)
        assert isinstance(dispatcher.agent_runner, MockAgentRunner)

    def test_auto_detect_claude_code_uses_claude_code_runner(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE", "1")
        dispatcher = create_dispatcher(tmp_path)
        assert isinstance(dispatcher.agent_runner, ClaudeCodeAgentRunner)

    def test_auto_detect_workbuddy_uses_generic_runner(self, tmp_path, monkeypatch):
        monkeypatch.setenv("WORKBUDDY_RUNTIME", "1")
        dispatcher = create_dispatcher(tmp_path)
        assert isinstance(dispatcher.agent_runner, GenericAgentRunner)
        # GenericAgentRunner 应使用 platform.value 作为默认 command
        assert dispatcher.agent_runner.command == "workbuddy"

    def test_auto_detect_codebuddy_uses_generic_runner(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CODEBUDDY_RUNTIME", "1")
        dispatcher = create_dispatcher(tmp_path)
        assert isinstance(dispatcher.agent_runner, GenericAgentRunner)
        assert dispatcher.agent_runner.command == "codebuddy"

    def test_auto_detect_mcp_host_returns_mock(self, tmp_path, monkeypatch):
        """MCP Host 不直接调用 Agent（通过 MCP Server 编排）"""
        monkeypatch.setenv("DEVFLOW_MCP_HOST", "1")
        dispatcher = create_dispatcher(tmp_path)
        assert isinstance(dispatcher.agent_runner, MockAgentRunner)

    def test_auto_detect_cli_returns_mock(self, tmp_path, monkeypatch):
        for var in ["CLAUDE_CODE", "WORKBUDDY_RUNTIME", "CODEBUDDY_RUNTIME", "DEVFLOW_MCP_HOST"]:
            monkeypatch.delenv(var, raising=False)
        dispatcher = create_dispatcher(tmp_path)
        assert isinstance(dispatcher.agent_runner, MockAgentRunner)


class TestAdapterExportAutoDetect:
    """adapter-export --auto-detect flag"""

    def test_auto_detect_uses_detected_platform(self, tmp_path, monkeypatch):
        """--auto-detect 时 platform 由 detect_platform() 决定"""
        monkeypatch.setenv("CLAUDE_CODE", "1")

        runner = CliRunner()
        target = tmp_path / "auto-detect-skills"
        result = runner.invoke(cli_app, [
            "adapter-export", "--auto-detect",
            "--target", str(target),
        ])
        assert result.exit_code == 0, f"output: {result.output}"
        # Claude Code 平台 → SKILL.md 文件存在
        assert target.exists()

    def test_manual_platform_still_works(self, tmp_path):
        """不传 --auto-detect 时手动指定 platform 仍有效"""
        runner = CliRunner()
        target = tmp_path / "manual-skills"
        result = runner.invoke(cli_app, [
            "adapter-export", "codebuddy",
            "--target", str(target),
        ])
        assert result.exit_code == 0, f"output: {result.output}"
        # CodeBuddy 平台 → JSON 文件
        assert any(target.glob("*.json"))