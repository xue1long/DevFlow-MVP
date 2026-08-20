"""tests/test_review_audit_cli.py — V4.3 阶段验证

覆盖:
- review-audit --help 可用
- review-audit 调用 V4.1 audit_review_ledger 核心逻辑
- CLI 输出含 v0.4 完整字段（orphans / missing_in_ledger / fix_orphans / fix_missing_in_ledger / per_spec_summary）
- 移除 v0.3 current_spec_id 单点假设
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from devflow.cli import app as cli_app


class TestReviewAuditCLIBasic:
    """review-audit CLI 基本可用"""

    def test_review_audit_help(self):
        runner = CliRunner()
        result = runner.invoke(cli_app, ["review-audit", "--help"])
        assert result.exit_code == 0
        # 帮助信息应反映 v0.4 阶段
        assert "v0.4" in result.output or "多 spec" in result.output

    def test_review_audit_calls_core_logic(self, tmp_path: Path):
        """review-audit 应调 audit_review_ledger 核心逻辑"""
        # mock storage + review_store
        mock_storage = MagicMock()
        mock_storage.get_ledger.return_value = {
            "entries": [
                {"action": "review", "details": "评审 spec-1 R1 完成"},
                {"action": "review", "details": "评审 spec-2 R1 完成"},
            ],
            "current_spec_id": "spec-1",
        }
        mock_review_store = MagicMock()
        mock_review_store.list_spec_ids.return_value = ["spec-1", "spec-2"]
        mock_review_store.list_reports.side_effect = lambda spec_id: [
            MagicMock(spec_id=spec_id, round=1)
        ] if spec_id in ("spec-1", "spec-2") else []

        # patch _get_storage 和 ReviewStore 构造
        with patch("devflow.cli._get_storage", return_value=mock_storage), \
             patch("devflow.cli.ReviewStore", return_value=mock_review_store):
            runner = CliRunner()
            result = runner.invoke(cli_app, ["review-audit"])

        # 验证 CLI 退出码
        assert result.exit_code == 0, f"output: {result.output}"

        # 验证输出含 v0.4 完整字段
        try:
            data = json.loads(result.output)
        except json.JSONDecodeError:
            # typer CliRunner 可能输出非 JSON 格式 → 提取最后一行
            lines = [l for l in result.output.split("\n") if l.strip().startswith("{")]
            assert lines, f"no JSON in output: {result.output}"
            data = json.loads(lines[-1])

        # v0.4 完整字段
        assert "orphans" in data
        assert "missing_in_ledger" in data
        assert "fix_orphans" in data
        assert "fix_missing_in_ledger" in data
        assert "per_spec_summary" in data
        assert "scope_note" in data
        # v0.4 scope_note 应说明多 spec 全面版
        assert "v0.4" in data["scope_note"]

    def test_review_audit_no_longer_uses_current_spec_id_assumption(self):
        """v0.3 current_spec_id 单点假设已移除（多 spec 推断）"""
        runner = CliRunner()
        result = runner.invoke(cli_app, ["review-audit", "--help"])
        # 帮助信息应不再提及 v0.3 单 spec 限制
        assert "单 spec 工作流" not in result.output or "v0.3.1-r2" not in result.output
        # 应提及 v0.4 多 spec 全面版
        assert "v0.4" in result.output