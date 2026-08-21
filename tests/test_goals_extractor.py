"""v0.4.3 GoalsExtractor 单元测试"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from devflow.engine.goals_extractor import GoalsExtractor
from devflow.model.research import (
    Citation,
    ResearchReport,
    SourceType,
    TrustLevel,
)


def _cite(
    url="https://example.com",
    title="t",
    snippet="s",
    source=SourceType.WEB,
    trust=TrustLevel.MEDIUM,
    metadata=None,
) -> Citation:
    return Citation(
        url=url,
        title=title,
        snippet=snippet,
        source_type=source,
        trust_level=trust,
        metadata=metadata or {},
    )


class TestExtractNpm:
    def test_npm_package_url(self):
        c = _cite(
            url="https://www.npmjs.com/package/axios",
            title="axios",
            snippet="",  # 默认 _cite snippet="s", 显式置空避免污染 goal
            source=SourceType.NPM,
            trust=TrustLevel.HIGH,
        )
        report = ResearchReport(spec_id="s", query="q", citations=[c])
        goals = GoalsExtractor().extract(report)
        assert goals == ["评估 axios 包"]

    def test_npm_with_snippet(self):
        c = _cite(
            url="https://www.npmjs.com/package/got",
            title="got",
            snippet="Promise HTTP client",
            source=SourceType.NPM,
            trust=TrustLevel.HIGH,
        )
        report = ResearchReport(spec_id="s", query="q", citations=[c])
        goals = GoalsExtractor().extract(report)
        assert "got" in goals[0]
        assert "Promise" in goals[0]


class TestExtractPypi:
    def test_pypi_package_url(self):
        c = _cite(
            url="https://pypi.org/project/tenacity",
            title="tenacity",
            source=SourceType.PYPI,
            trust=TrustLevel.HIGH,
        )
        report = ResearchReport(spec_id="s", query="q", citations=[c])
        goals = GoalsExtractor().extract(report)
        assert "tenacity" in goals[0]
        assert "集成" in goals[0]


class TestExtractGithub:
    def test_github_repo_url(self):
        c = _cite(
            url="https://github.com/sindresorhus/got",
            title="sindresorhus/got",
            source=SourceType.GITHUB,
            trust=TrustLevel.HIGH,
            metadata={"stars": 12000},
        )
        report = ResearchReport(spec_id="s", query="q", citations=[c])
        goals = GoalsExtractor().extract(report)
        assert "sindresorhus/got" in goals[0]
        assert "12000" in goals[0]


class TestExtractCrates:
    def test_crates_url(self):
        c = _cite(
            url="https://crates.io/crates/tokio",
            title="tokio",
            source=SourceType.CRATES,
            trust=TrustLevel.HIGH,
        )
        report = ResearchReport(spec_id="s", query="q", citations=[c])
        goals = GoalsExtractor().extract(report)
        assert "tokio" in goals[0]


class TestExtractWeb:
    def test_web_fallback_to_title(self):
        c = _cite(
            url="https://example.com/article",
            title="How to design API",
            source=SourceType.WEB,
            trust=TrustLevel.MEDIUM,
        )
        report = ResearchReport(spec_id="s", query="q", citations=[c])
        goals = GoalsExtractor().extract(report)
        assert "How to design API" in goals[0]


class TestTrustSorting:
    def test_high_first(self):
        # LOW 在前(HIGH 应排在前面)
        low = _cite(url="https://example.com/a", title="a", source=SourceType.WEB, trust=TrustLevel.LOW)
        high = _cite(url="https://www.npmjs.com/package/best", title="best", source=SourceType.NPM, trust=TrustLevel.HIGH)
        report = ResearchReport(spec_id="s", query="q", citations=[low, high])
        goals = GoalsExtractor().extract(report)
        assert "best" in goals[0]  # HIGH 在前


class TestDedup:
    def test_same_name_dedup(self):
        """v0.4.3 RFC §4 去重: 同一库/包两条引用只取一个

        注: axios 和 axios-v2 是不同包, 不应该合并(精确匹配逻辑)
        """
        c1 = _cite(url="https://www.npmjs.com/package/axios", title="axios",
                   source=SourceType.NPM, trust=TrustLevel.HIGH)
        c2 = _cite(url="https://www.npmjs.com/package/axios", title="axios  # another listing",
                   source=SourceType.NPM, trust=TrustLevel.HIGH)
        report = ResearchReport(spec_id="s", query="q", citations=[c1, c2])
        goals = GoalsExtractor().extract(report)
        # 两个 goal 的 key 都是 "评估 axios" -> 去重为 1
        assert len(goals) == 1


class TestMaxGoals:
    def test_max_goals_limit(self):
        citations = [
            _cite(
                url=f"https://www.npmjs.com/package/pkg{i}",
                title=f"pkg{i}",
                source=SourceType.NPM,
                trust=TrustLevel.HIGH,
            )
            for i in range(10)
        ]
        report = ResearchReport(spec_id="s", query="q", citations=citations)
        goals = GoalsExtractor().extract(report, max_goals=3)
        assert len(goals) == 3

    def test_empty_citations(self):
        report = ResearchReport(spec_id="s", query="q", citations=[])
        assert GoalsExtractor().extract(report) == []

    def test_no_template_source_type(self):
        # OFFICIAL_DOCS 无模板 -> 返回 None
        from devflow.model.research import SourceType as ST
        # 用模型构造保证 SourceType.OFFICIAL_DOCS 存在
        c = _cite(
            url="https://example.com/doc",
            title="Doc",
            source=ST.OFFICIAL_DOCS,
            trust=TrustLevel.HIGH,
        )
        report = ResearchReport(spec_id="s", query="q", citations=[c])
        goals = GoalsExtractor().extract(report)
        assert goals == []  # OFFICIAL_DOCS 无模板, fallback 失败