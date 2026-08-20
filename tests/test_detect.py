"""tests/test_detect.py — C7.1 阶段验证

覆盖:
- 5 个平台的环境变量探测
- 集成模式矩阵（5 平台 × 4 模式）
- 优先级（CLAUDE_CODE 优先于 WORKBUDDY 等）
"""
from __future__ import annotations

import os

import pytest

from devflow.adapters.detect import (
    IntegrationMode,
    Platform,
    detect_integration_mode,
    detect_platform,
    is_mcp_callable,
    is_skill_callable,
)


class TestDetectPlatform:
    """5 平台环境变量探测"""

    def test_default_is_cli(self, monkeypatch):
        """无环境变量 → CLI"""
        for var in ["CLAUDE_CODE", "WORKBUDDY_RUNTIME", "CODEBUDDY_RUNTIME", "DEVFLOW_MCP_HOST"]:
            monkeypatch.delenv(var, raising=False)
        assert detect_platform() == Platform.CLI

    def test_claude_code_env(self, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE", "1")
        assert detect_platform() == Platform.CLAUDE_CODE

    def test_workbuddy_env(self, monkeypatch):
        monkeypatch.setenv("WORKBUDDY_RUNTIME", "1")
        assert detect_platform() == Platform.WORKBUDDY

    def test_codebuddy_env(self, monkeypatch):
        monkeypatch.setenv("CODEBUDDY_RUNTIME", "1")
        assert detect_platform() == Platform.CODEBUDDY

    def test_mcp_host_env(self, monkeypatch):
        monkeypatch.setenv("DEVFLOW_MCP_HOST", "1")
        assert detect_platform() == Platform.MCP_HOST

    def test_claude_code_priority_over_workbuddy(self, monkeypatch):
        """CLAUDE_CODE 优先级最高（架构文档 §7）"""
        monkeypatch.setenv("CLAUDE_CODE", "1")
        monkeypatch.setenv("WORKBUDDY_RUNTIME", "1")
        assert detect_platform() == Platform.CLAUDE_CODE


class TestDetectIntegrationMode:
    """平台能力矩阵"""

    def test_claude_code_supports_skill_and_hook(self):
        modes = detect_integration_mode(Platform.CLAUDE_CODE)
        assert IntegrationMode.SKILL in modes
        assert IntegrationMode.HOOK in modes
        assert IntegrationMode.MCP not in modes

    def test_workbuddy_supports_skill_and_mcp(self):
        modes = detect_integration_mode(Platform.WORKBUDDY)
        assert IntegrationMode.SKILL in modes
        assert IntegrationMode.MCP in modes

    def test_codebuddy_supports_skill_and_command(self):
        modes = detect_integration_mode(Platform.CODEBUDDY)
        assert IntegrationMode.SKILL in modes
        assert IntegrationMode.COMMAND in modes
        assert IntegrationMode.MCP not in modes

    def test_mcp_host_only_supports_mcp(self):
        modes = detect_integration_mode(Platform.MCP_HOST)
        assert modes == {IntegrationMode.MCP}

    def test_cli_only_supports_command(self):
        modes = detect_integration_mode(Platform.CLI)
        assert modes == {IntegrationMode.COMMAND}

    def test_unknown_platform_falls_back_to_command(self):
        """未知平台 → 默认 command"""
        modes = detect_integration_mode("unknown")  # type: ignore[arg-type]
        assert modes == {IntegrationMode.COMMAND}


class TestHelperFunctions:
    """辅助函数"""

    def test_is_mcp_callable_true_for_mcp_capable_platforms(self):
        assert is_mcp_callable(Platform.MCP_HOST) is True
        assert is_mcp_callable(Platform.WORKBUDDY) is True
        assert is_mcp_callable(Platform.CLAUDE_CODE) is False
        assert is_mcp_callable(Platform.CODEBUDDY) is False

    def test_is_skill_callable_true_for_skill_capable_platforms(self):
        assert is_skill_callable(Platform.CLAUDE_CODE) is True
        assert is_skill_callable(Platform.WORKBUDDY) is True
        assert is_skill_callable(Platform.CODEBUDDY) is True
        assert is_skill_callable(Platform.MCP_HOST) is False
        assert is_skill_callable(Platform.CLI) is False