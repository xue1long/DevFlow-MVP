"""tests/test_router.py — C7.2 阶段验证

覆盖:
- 5 平台的 invoker 选择（当前全部 fallback 到 CLI）
- route_invocation() 端到端
- workspace_root 透传
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from devflow.adapters.detect import Platform
from devflow.adapters.invoker import CliEngineInvoker
from devflow.adapters.router import route_invocation, select_invoker


class TestSelectInvoker:
    """5 平台 invoker 选择"""

    @pytest.mark.parametrize("platform_env", [
        ("CLAUDE_CODE", Platform.CLAUDE_CODE),
        ("WORKBUDDY_RUNTIME", Platform.WORKBUDDY),
        ("CODEBUDDY_RUNTIME", Platform.CODEBUDDY),
        ("DEVFLOW_MCP_HOST", Platform.MCP_HOST),
    ])
    def test_each_platform_returns_cli_invoker(
        self, tmp_path, monkeypatch, platform_env
    ):
        """当前所有平台都 fallback 到 CliEngineInvoker（MCP/Skill invoker 未实现）"""
        env_var, platform = platform_env
        monkeypatch.setenv(env_var, "1")
        invoker = select_invoker(tmp_path)
        assert isinstance(invoker, CliEngineInvoker)
        assert invoker.workspace_root == tmp_path

    def test_cli_default(self, tmp_path, monkeypatch):
        """无环境变量 → CLI 默认"""
        for var in ["CLAUDE_CODE", "WORKBUDDY_RUNTIME", "CODEBUDDY_RUNTIME", "DEVFLOW_MCP_HOST"]:
            monkeypatch.delenv(var, raising=False)
        invoker = select_invoker(tmp_path)
        assert isinstance(invoker, CliEngineInvoker)


class TestRouteInvocation:
    """route_invocation() 端到端"""

    def test_route_calls_invoker(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE", "1")

        with patch("devflow.adapters.router.CliEngineInvoker") as mock_invoker_class:
            mock_invoker = MagicMock()
            mock_invoker.invoke.return_value = {"ok": True, "phase": 0}
            mock_invoker_class.return_value = mock_invoker

            result = route_invocation(
                "devflow.status", {}, tmp_path
            )

            assert result == {"ok": True, "phase": 0}
            mock_invoker_class.assert_called_once_with(tmp_path)
            mock_invoker.invoke.assert_called_once_with(
                "devflow.status", {}
            )

    def test_route_passes_workspace_root(self, tmp_path):
        """workspace_root 必须传给 invoker"""
        with patch("devflow.adapters.router.CliEngineInvoker") as mock_invoker_class:
            mock_invoker = MagicMock()
            mock_invoker.invoke.return_value = {"ok": True}
            mock_invoker_class.return_value = mock_invoker

            route_invocation("devflow.test", {"spec_id": "x"}, tmp_path)

            assert mock_invoker_class.call_args.args[0] == tmp_path

    def test_route_passes_args(self, tmp_path):
        """args 必须传给 invoker"""
        with patch("devflow.adapters.router.CliEngineInvoker") as mock_invoker_class:
            mock_invoker = MagicMock()
            mock_invoker.invoke.return_value = {"ok": True}
            mock_invoker_class.return_value = mock_invoker

            args = {"spec_id": "spec-1", "round": 2}
            route_invocation("devflow.review", args, tmp_path)

            assert mock_invoker.invoke.call_args.args[1] == args