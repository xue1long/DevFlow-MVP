"""tests/test_review_audit_fix_join.py — V4.2 阶段验证

覆盖:
- fix 记录反向 JOIN（fix_orphans / fix_missing_in_ledger）
- per_spec_summary 包含 fix 计数
- _parse_fix_number_from_details 当前返回 None（v0.3 格式限制）
- fix 记录场景不影响 review 审计结果
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from devflow.engine.review_audit import (
    ReviewAuditResult,
    _parse_fix_number_from_details,
    audit_review_ledger,
)
from devflow.model.review import (
    AxeReview,
    FixRecord,
    ReviewReport,
    ReviewVerdict,
)


def _make_report(spec_id: str, round: int) -> ReviewReport:
    return ReviewReport(
        id=f"r{round}",
        spec_id=spec_id,
        round=round,
        phase=5,
        standards=AxeReview(verdict=ReviewVerdict.PASS, violations=[]),
    )


def _make_fix(spec_id: str, fix_id: str) -> FixRecord:
    return FixRecord(
        id=fix_id,
        review_id=fix_id.replace("f", "r"),
        resolved_violations=[],
        residual_violations=[],
    )


def _make_store_with_fixes(reports_by_spec, fixes_by_spec):
    """构造带 review + fix 的 mock store"""
    store = MagicMock()
    store.list_spec_ids.return_value = list(reports_by_spec.keys())
    store.list_reports.side_effect = lambda spec_id: [
        _make_report(spec_id, r) for r in reports_by_spec.get(spec_id, [])
    ]
    store.list_fixes.side_effect = lambda spec_id: [
        _make_fix(spec_id, fid) for fid in fixes_by_spec.get(spec_id, [])
    ]
    return store


class TestParseFixNumber:
    """_parse_fix_number_from_details 单元测试"""

    def test_v3_format_returns_none(self):
        """v0.3 fix 格式无 f<N> 模式 → 返回 None（未来扩展）"""
        assert _parse_fix_number_from_details("修复 R1: +1 resolved") is None

    def test_empty_details(self):
        assert _parse_fix_number_from_details("") is None

    def test_none_details(self):
        assert _parse_fix_number_from_details(None) is None


class TestFixJoinV42:
    """V4.2 fix 记录反向 JOIN"""

    def test_no_fixes_no_join(self):
        """无 fix 记录 → fix_orphans / fix_missing_in_ledger 都为空"""
        ledger = {
            "entries": [{"action": "review", "details": "评审 spec-1 R1 完成"}],
            "current_spec_id": "spec-1",
        }
        store = _make_store_with_fixes(
            {"spec-1": [1]},
            {},  # 无 fix
        )
        result = audit_review_ledger(ledger, store)
        assert result.fix_orphans == []
        assert result.fix_missing_in_ledger == []

    def test_review_audit_still_works_alongside_fix(self):
        """fix 记录的存在不影响 review 审计"""
        ledger = {
            "entries": [
                {"action": "review", "details": "评审 spec-1 R1 完成"},
            ],
            "current_spec_id": "spec-1",
        }
        store = _make_store_with_fixes(
            {"spec-1": [1]},
            {"spec-1": ["f1", "f2"]},  # 2 个 fix
        )
        result = audit_review_ledger(ledger, store)
        # review 审计应正常（无 orphans / 无 missing）
        assert result.orphans == []
        assert result.missing_in_ledger == []
        # fix 审计：当前 v0.3 格式无 f<N> 解析，ledger_fix_keys 为空
        # review_store 有 2 个 fix → 全进 fix_missing_in_ledger
        assert result.fix_orphans == []
        assert len(result.fix_missing_in_ledger) == 2

    def test_per_spec_summary_includes_fix_counts(self):
        """per_spec_summary 应包含 fix_orphan_count / fix_missing_in_ledger_count"""
        ledger = {
            "entries": [],
            "current_spec_id": None,
        }
        store = _make_store_with_fixes(
            {"spec-1": [1]},
            {"spec-1": ["f1", "f2"]},
        )
        result = audit_review_ledger(ledger, store)
        assert len(result.per_spec_summary) == 1
        summary = result.per_spec_summary[0]
        assert "fix_orphan_count" in summary
        assert "fix_missing_in_ledger_count" in summary
        # 当前 v0.3 ledger 无 fix 条目 → fix_orphan_count = 0
        # review_store 有 2 个 fix → fix_missing_in_ledger_count = 2
        assert summary["fix_orphan_count"] == 0
        assert summary["fix_missing_in_ledger_count"] == 2

    def test_fix_missing_in_ledger_with_review_store_fixes(self):
        """review_store 有 fix 文件但 ledger 无 fix 条目 → fix_missing_in_ledger"""
        # 场景：v0.3 当前格式下，ledger 没有 'fix' action 详细记录
        # 仅有 review_action_entries 收集 action='fix' 的条目
        # 当前 v0.3 fix 写入格式："修复 R1: +1 resolved, +0 residual"
        # 不含 f<N> → _parse_fix_number 返回 None → 无 fix_orphans
        # 但 fix_missing_in_ledger 应从 review_store 反查
        ledger = {
            "entries": [],
            "current_spec_id": None,
        }
        store = _make_store_with_fixes(
            {"spec-1": [1]},
            {"spec-1": ["f1", "f2", "f3"]},  # 3 个 fix 文件
        )
        result = audit_review_ledger(ledger, store)
        # 当前实现：fix 编号无法从 ledger 解析 → ledger_fix_keys 为空
        # review_store 有 3 个 fix → 3 个 missing_in_ledger
        assert len(result.fix_missing_in_ledger) == 3
        for entry in result.fix_missing_in_ledger:
            assert entry["spec_id"] == "spec-1"
            assert "f<N>.yaml" in entry["message"]