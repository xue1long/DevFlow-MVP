"""T3 单元测试: ResearchConfig SOP 加载与默认行为

覆盖:
- 带 research 段正确解析
- 无 research 段时走默认值(向后兼容)
- enabled=false 关闭自动运行
- is_research_auto_run(stage) 阶段名映射
- 字段边界校验(max_results_per_source/max_total_chars/timeout_per_source)

锁定 v0.4 RFC §6.1 行为。
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from devflow.policy.loader import (
    ResearchConfig,
    SOPConfig,
    load_sop_from_text,
)


def _parse(sop_text: str) -> SOPConfig:
    return load_sop_from_text(sop_text)


class TestResearchConfigParsing:
    def test_with_research_segment(self):
        """带完整 research 段 - 全部字段正确加载"""
        config = _parse("""
sop:
  sop_version: "0.1"
  phases: [intake, brainstorm, plan, contract, implement, verify, review, finish]
  research:
    enabled: true
    auto_run_on: [plan_stage]
    sources: [github, web]
    max_results_per_source: 3
    max_total_chars: 5000
    timeout_per_source: 5
    fallback: skip
    citation_required: true
    start_keywords: ["from scratch", "造轮子"]
""")
        r = config.research
        assert r.enabled is True
        assert r.auto_run_on == ["plan_stage"]
        assert r.sources == ["github", "web"]
        assert r.max_results_per_source == 3
        assert r.max_total_chars == 5000
        assert r.timeout_per_source == 5
        assert r.fallback == "skip"
        assert r.citation_required is True
        assert r.start_keywords == ["from scratch", "造轮子"]

    def test_partial_research_segment_uses_defaults(self):
        """只配 enabled,其他走默认值"""
        config = _parse("""
sop:
  sop_version: "0.1"
  phases: [intake, brainstorm, plan, contract, implement, verify, review, finish]
  research:
    enabled: false
""")
        r = config.research
        assert r.enabled is False
        # 其他字段全部走默认
        assert r.auto_run_on == ["plan_stage"]
        assert r.sources == ["github", "pypi", "npm", "web"]
        assert r.max_results_per_source == 5
        assert r.fallback == "skip"

    def test_no_research_segment_uses_defaults(self):
        """旧 sop.yaml 无 research 段 - 必须向后兼容"""
        config = _parse("""
sop:
  sop_version: "0.1"
  phases: [intake, brainstorm, plan, contract, implement, verify, review, finish]
""")
        r = config.research
        assert r.enabled is True  # 默认开启
        assert r.auto_run_on == ["plan_stage"]
        assert r.sources == ["github", "pypi", "npm", "web"]
        assert r.max_results_per_source == 5
        assert r.max_total_chars == 8000
        assert r.timeout_per_source == 10
        assert r.fallback == "skip"
        assert r.citation_required is True
        # 默认关键词:5 个
        assert len(r.start_keywords) == 5
        assert "from scratch" in r.start_keywords
        assert "造轮子" in r.start_keywords


class TestResearchConfigBounds:
    def test_max_results_per_source_min(self):
        with pytest.raises(Exception):
            ResearchConfig(max_results_per_source=0)

    def test_max_results_per_source_max(self):
        with pytest.raises(Exception):
            ResearchConfig(max_results_per_source=21)

    def test_max_total_chars_min(self):
        with pytest.raises(Exception):
            ResearchConfig(max_total_chars=50)

    def test_max_total_chars_max(self):
        with pytest.raises(Exception):
            ResearchConfig(max_total_chars=60000)

    def test_timeout_per_source_min(self):
        with pytest.raises(Exception):
            ResearchConfig(timeout_per_source=0)

    def test_timeout_per_source_max(self):
        with pytest.raises(Exception):
            ResearchConfig(timeout_per_source=61)

    def test_boundary_values_ok(self):
        # 边界值应接受
        ResearchConfig(
            max_results_per_source=1,
            max_total_chars=100,
            timeout_per_source=1,
        )
        ResearchConfig(
            max_results_per_source=20,
            max_total_chars=50000,
            timeout_per_source=60,
        )


class TestIsResearchAutoRun:
    def _config_with(self, enabled: bool, stages: list[str]) -> SOPConfig:
        return _parse(f"""
sop:
  sop_version: "0.1"
  phases: [intake, brainstorm, plan, contract, implement, verify, review, finish]
  research:
    enabled: {str(enabled).lower()}
    auto_run_on: {stages}
""")

    def test_plan_stage_true(self):
        c = self._config_with(True, ["plan_stage"])
        assert c.is_research_auto_run(2) is True
        assert c.is_research_auto_run(0) is False  # intake
        assert c.is_research_auto_run(3) is False  # contract

    def test_brainstorm_and_plan(self):
        c = self._config_with(True, ["brainstorm_stage", "plan_stage"])
        assert c.is_research_auto_run(1) is True   # brainstorm
        assert c.is_research_auto_run(2) is True   # plan
        assert c.is_research_auto_run(0) is False  # intake
        assert c.is_research_auto_run(4) is False  # implement

    def test_disabled_returns_false_even_for_plan(self):
        c = self._config_with(False, ["plan_stage"])
        assert c.is_research_auto_run(2) is False

    def test_empty_auto_run_on(self):
        c = self._config_with(True, [])
        assert c.is_research_auto_run(2) is False

    def test_out_of_range_stage(self):
        c = self._config_with(True, ["plan_stage"])
        assert c.is_research_auto_run(99) is False
        assert c.is_research_auto_run(-1) is False


class TestSOPConfigIntegration:
    """与其它 SOP 字段共存"""

    def test_research_does_not_break_existing_config(self):
        config = _parse("""
sop:
  sop_version: "0.1"
  phases: [intake, brainstorm, plan, contract, implement, verify, review, finish]
  intake_fast_skip: true
  red_lines: [no_test, skip_phase]
  pr_max_files: 30
  minimalism_strictness: full
  gates:
    tests_pass:
      command: "pytest"
      blocking: true
      enabled: true
      bind_to_stage: 5
  research:
    enabled: true
    auto_run_on: [plan_stage]
""")
        # 现有字段未受影响
        assert config.intake_fast_skip is True
        assert len(config.red_lines) == 2
        assert config.pr_max_files == 30
        assert config.minimalism_strictness == "full"
        assert "tests_pass" in config.gates
        # research 字段正确加载
        assert config.research.enabled is True
        assert config.research.auto_run_on == ["plan_stage"]