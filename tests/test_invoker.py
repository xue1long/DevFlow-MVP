"""tests/test_invoker.py — C2 阶段验证

覆盖:
- CliEngineInvoker 基本调用（用真实 devflow status）
- 错误退出码处理（mock subprocess）
- workspace_root 参数正确性
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from devflow.adapters.invoker import CliEngineInvoker, EngineInvoker


class TestCliEngineInvokerBasic:
    """CliEngineInvoker 基本调用"""

    def test_invoke_with_mock_subprocess(self, tmp_path: Path):
        """mock subprocess.run 验证调用组装正确"""
        invoker = CliEngineInvoker(tmp_path)
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout='{"ok": true, "phase": 0}',
                stderr="",
            )
            result = invoker.invoke("devflow.status", {})
            assert result == {"ok": True, "phase": 0}
            # 验证命令行组装
            call_args = mock_run.call_args.args[0]
            assert call_args[0] == "devflow"
            assert call_args[1] == "status"

    def test_workspace_root_passed_to_subprocess(self, tmp_path: Path):
        """cwd 参数必须 = workspace_root"""
        invoker = CliEngineInvoker(tmp_path)
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout='{"ok": true}',
                stderr="",
            )
            invoker.invoke("devflow.test", {})
            assert mock_run.call_args.kwargs["cwd"] == tmp_path

    def test_skill_name_prefix_stripped(self, tmp_path: Path):
        """skill_name 的 devflow. 前缀应被去除"""
        invoker = CliEngineInvoker(tmp_path)
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout='{"ok": true}',
                stderr="",
            )
            invoker.invoke("devflow.review", {"spec_id": "x"})
            call_args = mock_run.call_args.args[0]
            assert call_args[1] == "review"
            assert "x" in call_args  # spec_id 参数

    def test_fallback_to_python_module(self, tmp_path: Path):
        """devflow 命令不存在时降级到 python -m devflow.cli"""
        import sys
        invoker = CliEngineInvoker(tmp_path)
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                FileNotFoundError("devflow not found"),  # 第一次
                MagicMock(  # 第二次（降级）
                    returncode=0,
                    stdout='{"ok": true}',
                    stderr="",
                ),
            ]
            result = invoker.invoke("devflow.status", {})
            assert result == {"ok": True}
            # 第二次调用应该用 python -m devflow.cli
            second_call_args = mock_run.call_args_list[1].args[0]
            assert second_call_args[0] == sys.executable
            assert second_call_args[1] == "-m"
            assert second_call_args[2] == "devflow.cli"


class TestCliEngineInvokerErrors:
    """CliEngineInvoker 错误处理"""

    def test_nonzero_exit_raises(self, tmp_path: Path):
        """CLI 退出码非零应抛 RuntimeError"""
        invoker = CliEngineInvoker(tmp_path)
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1,
                stdout="",
                stderr="error: spec not found",
            )
            with pytest.raises(RuntimeError, match="退出码 1"):
                invoker.invoke("devflow.test", {})


class TestEngineInvokerIsAbstract:
    """EngineInvoker 必须是抽象类"""

    def test_cannot_instantiate_abstract(self):
        """不能直接实例化 EngineInvoker"""
        with pytest.raises(TypeError):
            EngineInvoker()