"""tests/test_review_audit.py — V4.1 阶段验证

覆盖:
- 单 spec 正常场景（无 orphans / 无 missing）
- 单 spec orphans（ledger 有 review 但 review_store 无报告）
- 单 spec missing_in_ledger（review_store 有报告但 ledger 无记录）
- 多 spec 全面场景（v0.4 核心）
- 时间窗推断（v0.3 单 spec fallback 行为）
- details 文本解析（spec_id 出现 + R<n> 模式）
- 边界：未知 spec_id / 未知 round
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from devflow.engine.review_audit import (
    ReviewAuditResult,
    _infer_spec_id_for_ledger_entry,
    _parse_round_from_details,
    _spec_id_from_path,
    audit_review_ledger,
)
from devflow.model.review import (
    AxeReview,
    ReviewReport,
    ReviewVerdict,
)


# --- 辅助函数测试 ---

class TestParseRoundFromDetails:
    """_parse_round_from_details 单元测试"""

    def test_simple_R1(self):
        assert _parse_round_from_details("评审 R1 完成") == 1

    def test_R2_in_fix_details(self):
        assert _parse_round_from_details("修复 R2: 补全字段") == 2

    def test_R10_multi_digit(self):
        assert _parse_round_from_details("R10 升级") == 10

    def test_no_R_pattern(self):
        assert _parse_round_from_details("普通 entry，无 round") is None

    def test_empty_details(self):
        assert _parse_round_from_details("") is None

    def test_none_details(self):
        assert _parse_round_from_details(None) is None


class TestSpecIdFromPath:
    """_spec_id_from_path 单元测试"""

    def test_unix_path(self):
        assert _spec_id_from_path("review/spec-1/r1.yaml") == "spec-1"

    def test_windows_path(self):
        assert _spec_id_from_path("review\\spec-1\\r1.yaml") == "spec-1"

    def test_nested_path(self):
        assert _spec_id_from_path("/root/review/spec-2/r3.yaml") == "spec-2"

    def test_too_short(self):
        assert _spec_id_from_path("r1.yaml") is None


class TestInferSpecIdForLedgerEntry:
    """_infer_spec_id_for_ledger_entry 时间窗推断"""

    def test_explicit_spec_id_field(self):
        """1. 显式字段优先级最高（v0.4 P1-13 主要路径）"""
        entry = {"spec_id": "explicit-spec", "details": "review something"}
        assert _infer_spec_id_for_ledger_entry(
            entry, {"other-spec"}, current_spec_id="current-spec"
        ) == "explicit-spec"

    def test_no_explicit_field_falls_back_to_current(self):
        """2. 无显式字段 → fallback current_spec_id（v0.3 单 spec 兼容）"""
        entry = {"details": "评审 spec-1 R1 完成"}  # v0.4 不再文本解析
        assert _infer_spec_id_for_ledger_entry(
            entry, {"spec-1", "spec-2"}, current_spec_id="current"
        ) == "current"

    def test_fallback_to_current_spec_id(self):
        """3. fallback current_spec_id（v0.3 单 spec 行为）"""
        entry = {"details": "普通 details，无 spec_id 字段"}
        assert _infer_spec_id_for_ledger_entry(
            entry, set(), current_spec_id="current-spec"
        ) == "current-spec"

    def test_returns_none_when_unrecognized(self):
        """4. 完全无法识别"""
        entry = {"details": "普通 entry"}
        assert _infer_spec_id_for_ledger_entry(
            entry, set(), current_spec_id=None
        ) is None


# --- 核心 audit_review_ledger 测试 ---

def _make_report(spec_id: str, round: int) -> ReviewReport:
    """构造最小合法 ReviewReport（用于 mock）"""
    return ReviewReport(
        id=f"r{round}",
        spec_id=spec_id,
        round=round,
        phase=5,
        standards=AxeReview(verdict=ReviewVerdict.PASS, violations=[]),
    )


def _make_mock_review_store(reports_by_spec: dict[str, list[int]]) -> MagicMock:
    """构造 mock ReviewStorageBackend

    Args:
        reports_by_spec: {spec_id: [round1, round2, ...]}
    """
    store = MagicMock()
    store.list_spec_ids.return_value = list(reports_by_spec.keys())
    store.list_reports.side_effect = lambda spec_id: [
        _make_report(spec_id, r) for r in reports_by_spec.get(spec_id, [])
    ]
    return store


def _make_ledger(entries: list[dict], current_spec_id: str | None = None) -> dict:
    """构造 mock ledger dict"""
    return {
        "entries": entries,
        "current_spec_id": current_spec_id,
    }


class TestAuditReviewLedgerSingleSpec:
    """单 spec 场景（兼容 v0.3 行为）"""

    def test_no_entries_no_reports(self):
        """空 ledger + 空 review_store → 无 orphans / 无 missing"""
        ledger = _make_ledger([])
        review_store = _make_mock_review_store({})

        result = audit_review_ledger(ledger, review_store)
        assert result.total_ledger_entries == 0
        assert result.total_reports == 0
        assert result.total_specs == 0
        assert result.orphans == []
        assert result.missing_in_ledger == []

    def test_aligned_single_spec(self):
        """单 spec 完美对齐"""
        ledger = _make_ledger([
            {"action": "review", "details": "评审 R1 完成"},
        ], current_spec_id="spec-1")
        review_store = _make_mock_review_store({"spec-1": [1]})

        result = audit_review_ledger(ledger, review_store)
        assert result.total_review_actions == 1
        assert result.orphans == []
        assert result.missing_in_ledger == []

    def test_orphan_single_spec(self):
        """单 spec orphan（ledger 有 review 但 review_store 无报告）"""
        ledger = _make_ledger([
            {"action": "review", "details": "评审 R1 完成"},
            {"action": "fix", "details": "修复 R1: 补全字段"},
        ], current_spec_id="spec-1")
        review_store = _make_mock_review_store({"spec-1": []})

        result = audit_review_ledger(ledger, review_store)
        assert len(result.orphans) == 2
        assert all(o["spec_id"] == "spec-1" for o in result.orphans)
        assert all(o["round"] == 1 for o in result.orphans)

    def test_missing_in_ledger_single_spec(self):
        """单 spec missing_in_ledger（review_store 有报告但 ledger 无记录）"""
        ledger = _make_ledger([], current_spec_id="spec-1")
        review_store = _make_mock_review_store({"spec-1": [1, 2]})

        result = audit_review_ledger(ledger, review_store)
        assert result.missing_in_ledger == [
            {"spec_id": "spec-1", "round": 1,
             "message": "review_store 有报告 review/spec-1/r1.yaml，但 ledger 无对应记录（审计盲点）"},
            {"spec_id": "spec-1", "round": 2,
             "message": "review_store 有报告 review/spec-1/r2.yaml，但 ledger 无对应记录（审计盲点）"},
        ]


class TestAuditReviewLedgerMultiSpec:
    """多 spec 全面场景（v0.4 核心）"""

    def test_multi_spec_all_aligned(self):
        """多 spec 全部对齐（v0.4 走显式 spec_id 字段）"""
        ledger = _make_ledger([
            {"action": "review", "spec_id": "spec-1", "details": "评审 R1 完成"},
            {"action": "review", "spec_id": "spec-2", "details": "评审 R1 完成"},
            {"action": "fix", "spec_id": "spec-1", "details": "修复 R1: 补全"},
        ], current_spec_id="spec-1")
        review_store = _make_mock_review_store({
            "spec-1": [1],
            "spec-2": [1],
        })

        result = audit_review_ledger(ledger, review_store)
        assert result.total_specs == 2
        assert result.orphans == []
        assert result.missing_in_ledger == []

    def test_multi_spec_orphan_in_one_spec(self):
        """多 spec：spec-2 有 orphan，spec-1 正常（v0.4 显式字段）"""
        ledger = _make_ledger([
            {"action": "review", "spec_id": "spec-1", "details": "评审 R1 完成"},
            {"action": "review", "spec_id": "spec-2", "details": "评审 R1 完成"},
            # spec-2 R2: ledger 有但 review_store 无
            {"action": "review", "spec_id": "spec-2", "details": "评审 R2 完成"},
        ], current_spec_id="spec-1")
        review_store = _make_mock_review_store({
            "spec-1": [1],
            "spec-2": [1],
        })

        result = audit_review_ledger(ledger, review_store)
        assert len(result.orphans) == 1
        assert result.orphans[0]["spec_id"] == "spec-2"
        assert result.orphans[0]["round"] == 2

    def test_multi_spec_missing_in_one_spec(self):
        """多 spec：spec-2 有 missing_in_ledger，spec-1 正常（v0.4 显式字段）"""
        ledger = _make_ledger([
            {"action": "review", "spec_id": "spec-1", "details": "评审 R1 完成"},
        ], current_spec_id="spec-1")
        review_store = _make_mock_review_store({
            "spec-1": [1],
            "spec-2": [1, 2, 3],  # spec-2 全部 missing
        })

        result = audit_review_ledger(ledger, review_store)
        assert len(result.missing_in_ledger) == 3
        assert all(m["spec_id"] == "spec-2" for m in result.missing_in_ledger)

    def test_per_spec_summary(self):
        """per_spec_summary 应按 spec 分组统计（v0.4 显式字段）"""
        ledger = _make_ledger([
            {"action": "review", "spec_id": "spec-1", "details": "评审 R1 完成"},
            {"action": "review", "spec_id": "spec-2", "details": "评审 R1 完成"},
        ], current_spec_id="spec-1")
        review_store = _make_mock_review_store({
            "spec-1": [1],
            "spec-2": [1, 2],
        })

        result = audit_review_ledger(ledger, review_store)
        assert len(result.per_spec_summary) == 2
        # 排序保证（按 spec_id）
        assert result.per_spec_summary[0]["spec_id"] == "spec-1"
        assert result.per_spec_summary[0]["total_reports"] == 1
        assert result.per_spec_summary[0]["rounds"] == [1]
        assert result.per_spec_summary[1]["spec_id"] == "spec-2"
        assert result.per_spec_summary[1]["total_reports"] == 2
        assert result.per_spec_summary[1]["rounds"] == [1, 2]

    def test_no_current_spec_id_with_multi_spec(self):
        """无 current_spec_id 但显式 spec_id 字段（v0.4 路径）"""
        ledger = _make_ledger([
            {"action": "review", "spec_id": "spec-1", "details": "评审 R1 完成"},
            {"action": "review", "spec_id": "spec-2", "details": "评审 R1 完成"},
        ], current_spec_id=None)
        review_store = _make_mock_review_store({
            "spec-1": [1],
            "spec-2": [1],
        })

        result = audit_review_ledger(ledger, review_store)
        # 显式字段足够定位 spec_id
        assert result.orphans == []
        assert result.missing_in_ledger == []


class TestAuditReviewLedgerEdgeCases:
    """边界场景"""

    def test_entry_with_unrecognizable_spec_id(self):
        """entry details 完全无法识别 spec_id → 纳入 orphans"""
        ledger = _make_ledger([
            {"action": "review", "details": "普通 review，无 spec_id 关键字"},
        ], current_spec_id=None)
        review_store = _make_mock_review_store({"spec-1": [1]})

        result = audit_review_ledger(ledger, review_store)
        # orphan 包含 reason="无法识别 spec_id 或 round"
        assert len(result.orphans) == 1
        assert result.orphans[0]["spec_id"] is None
        assert result.orphans[0]["round"] is None
        assert "无法识别" in result.orphans[0]["reason"]

    def test_entry_with_no_round_pattern(self):
        """entry details 无 R<n> 模式 → round 为 None"""
        ledger = _make_ledger([
            {"action": "fix", "details": "修复 spec-1 一些字段"},
        ], current_spec_id="spec-1")
        review_store = _make_mock_review_store({"spec-1": [1]})

        result = audit_review_ledger(ledger, review_store)
        assert len(result.orphans) == 1
        assert result.orphans[0]["round"] is None

    def test_ledger_action_types_filtered(self):
        """非 review/fix/escalate 类型的 entry 应被忽略"""
        ledger = _make_ledger([
            {"action": "approve", "details": "R1 approve"},  # 忽略
            {"action": "start", "details": "R1 start"},     # 忽略
            {"action": "review", "details": "评审 spec-1 R1 完成"},
        ], current_spec_id="spec-1")
        review_store = _make_mock_review_store({"spec-1": [1]})

        result = audit_review_ledger(ledger, review_store)
        assert result.total_review_actions == 1
        assert result.orphans == []
        assert result.missing_in_ledger == []