"""T1 单元测试: Research 数据模型（RFC §3）

覆盖:
- SourceType / TrustLevel / Citation / ResearchQuery / ResearchReport 模型
- to_markdown() 输出格式
- actual_chars() / has_high_trust() 辅助方法
- Spec.research_refs 字段持久化
- LedgerAction.RESEARCH 枚举值

锁定 v0.4 RFC §3 行为。
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from devflow.model.research import (
    Citation,
    ResearchQuery,
    ResearchReport,
    SourceType,
    TrustLevel,
)
from devflow.model.spec import Spec, SpecStatus
from devflow.model.ledger import LedgerAction, LedgerEntry


class TestSourceType:
    def test_all_values(self):
        assert SourceType.GITHUB.value == "github"
        assert SourceType.PYPI.value == "pypi"
        assert SourceType.NPM.value == "npm"
        assert SourceType.CRATES.value == "crates"
        assert SourceType.WEB.value == "web"
        assert SourceType.OFFICIAL_DOCS.value == "official_docs"

    def test_count(self):
        # 锁定枚举数量: 新增源时显式 bump
        assert len(list(SourceType)) == 6


class TestTrustLevel:
    def test_all_values(self):
        assert TrustLevel.HIGH.value == "high"
        assert TrustLevel.MEDIUM.value == "medium"
        assert TrustLevel.LOW.value == "low"
        assert TrustLevel.UNKNOWN.value == "unknown"


class TestCitation:
    def test_minimal_required(self):
        c = Citation(
            url="https://github.com/foo/bar",
            title="foo/bar",
            source_type=SourceType.GITHUB,
        )
        assert c.snippet == ""
        assert c.trust_level == TrustLevel.UNKNOWN
        assert isinstance(c.retrieved_at, datetime)
        assert c.metadata == {}

    def test_url_required(self):
        with pytest.raises(Exception):
            Citation(url="", title="x", source_type=SourceType.WEB)

    def test_title_max_length(self):
        with pytest.raises(Exception):
            Citation(
                url="https://x.com",
                title="a" * 201,  # 超过 200
                source_type=SourceType.WEB,
            )

    def test_snippet_max_length(self):
        with pytest.raises(Exception):
            Citation(
                url="https://x.com",
                title="t",
                snippet="a" * 501,  # 超过 500
                source_type=SourceType.WEB,
            )

    def test_metadata_default_empty_dict(self):
        c1 = Citation(url="u", title="t", source_type=SourceType.WEB)
        c2 = Citation(url="u2", title="t2", source_type=SourceType.WEB)
        # 必须各自独立,不能共享可变默认值
        c1.metadata["k"] = "v"
        assert c2.metadata == {}


class TestResearchQuery:
    def test_defaults(self):
        q = ResearchQuery(query="python retry")
        assert q.sources == [SourceType.GITHUB, SourceType.PYPI, SourceType.WEB]
        assert q.max_results_per_source == 5
        assert q.max_total_chars == 8000
        assert q.timeout_per_source == 10
        assert q.spec_id is None

    def test_query_required(self):
        with pytest.raises(Exception):
            ResearchQuery(query="")

    def test_max_results_per_source_bounds(self):
        with pytest.raises(Exception):
            ResearchQuery(query="x", max_results_per_source=0)  # <1
        with pytest.raises(Exception):
            ResearchQuery(query="x", max_results_per_source=21)  # >20


class TestResearchReport:
    def _make_citation(
        self,
        url="https://example.com",
        title="Example",
        trust=TrustLevel.MEDIUM,
        source=SourceType.WEB,
        snippet="Example snippet",
        metadata=None,
    ) -> Citation:
        return Citation(
            url=url,
            title=title,
            source_type=source,
            trust_level=trust,
            snippet=snippet,
            metadata=metadata or {},
        )

    def test_minimal(self):
        r = ResearchReport(spec_id="spec-1", query="q")
        assert r.citations == []
        assert r.summary == ""
        assert r.sources_used == []
        assert r.fallback_used is False
        assert r.total_chars == 0

    def test_actual_chars(self):
        r = ResearchReport(
            spec_id="spec-1",
            query="q",
            citations=[
                self._make_citation(url="a" * 10, title="b" * 5, snippet="c" * 7),
                self._make_citation(url="d" * 3, title="e" * 2, snippet="f" * 4),
            ],
        )
        # 10+5+7 + 3+2+4 = 31
        assert r.actual_chars() == 31

    def test_has_high_trust_true(self):
        r = ResearchReport(
            spec_id="spec-1",
            query="q",
            citations=[self._make_citation(trust=TrustLevel.HIGH)],
        )
        assert r.has_high_trust() is True

    def test_has_high_trust_false(self):
        r = ResearchReport(
            spec_id="spec-1",
            query="q",
            citations=[self._make_citation(trust=TrustLevel.MEDIUM)],
        )
        assert r.has_high_trust() is False

    def test_has_high_trust_empty(self):
        r = ResearchReport(spec_id="spec-1", query="q")
        assert r.has_high_trust() is False

    def test_to_markdown_header(self):
        r = ResearchReport(
            spec_id="20260819-test",
            query="python retry",
            citations=[self._make_citation()],
            sources_used=[SourceType.GITHUB],
            backend_chain=["agent_reach", "github"],
            fallback_used=True,
        )
        md = r.to_markdown()
        assert "# Research Report: python retry" in md
        assert "`20260819-test`" in md
        assert "github" in md
        assert "agent_reach → github" in md
        assert "Fallback Used**: True" in md

    def test_to_markdown_empty_citations(self):
        r = ResearchReport(spec_id="spec-1", query="q")
        md = r.to_markdown()
        assert "（无引用结果）" in md
        assert "Citations**: 0" in md

    def test_to_markdown_citation_format(self):
        r = ResearchReport(
            spec_id="spec-1",
            query="q",
            citations=[
                Citation(
                    url="https://github.com/foo/bar",
                    title="foo/bar",
                    source_type=SourceType.GITHUB,
                    trust_level=TrustLevel.HIGH,
                    snippet="A retry library",
                    metadata={"stars": 1500, "language": "Python"},
                )
            ],
        )
        md = r.to_markdown()
        assert "[1] foo/bar" in md
        assert "<https://github.com/foo/bar>" in md
        assert "`github`" in md
        assert "`high`" in md
        assert "stars=1500" in md
        assert "> A retry library" in md


class TestSpecResearchRefs:
    def test_default_empty(self):
        s = Spec(
            id="x",
            title="t",
            problem="some problem statement here",
            goals=["g"],
            non_goals=["ng"],
        )
        assert s.research_refs == []

    def test_research_refs_accept_list(self):
        s = Spec(
            id="x",
            title="t",
            problem="some problem statement here",
            goals=["g"],
            non_goals=["ng"],
            research_refs=[
                {
                    "path": "docs/devflow/research/x-153012.md",
                    "summary": "found 3 libs",
                    "sources": ["github"],
                    "trust_level": "high",
                    "generated_at": "2026-08-19T16:30:00+00:00",
                    "citations_count": 3,
                }
            ],
        )
        assert len(s.research_refs) == 1
        assert s.research_refs[0]["path"].endswith(".md")
        assert s.research_refs[0]["trust_level"] == "high"


class TestLedgerActionResearch:
    def test_research_action_exists(self):
        assert LedgerAction.RESEARCH.value == "research"

    def test_research_ledger_entry(self):
        e = LedgerEntry(
            phase=2,
            action=LedgerAction.RESEARCH,
            spec_id="20260819-test",
            details="sources=[github] citations=5 backend=agent_reach",
        )
        assert e.action == LedgerAction.RESEARCH
        assert e.phase == 2  # plan 阶段
        assert "agent_reach" in e.details