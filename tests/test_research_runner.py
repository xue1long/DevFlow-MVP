"""T4 单元测试: ResearchRunner 编排层 (v0.4 RFC §5)

覆盖:
- 正常路径: backend 返回 Citation → 报告落盘 + Spec.research_refs 更新 + 账本写入
- URL 去重
- max_total_chars 截断
- 全部 backend 失败: fallback=skip 不阻断 / fallback=error 返回 ok=False
- Spec 不存在: 静默跳过,仍落盘报告 + 账本
- 并发执行: timeout 不会卡死 runner
- backend 抛异常被 _safe_search 兜底
"""
import sys
from pathlib import Path
from typing import Optional
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from devflow.engine.research_runner import ResearchRunner
from devflow.model.research import (
    Citation,
    ResearchQuery,
    SourceType,
    TrustLevel,
)
from devflow.model.spec import Spec, SpecStatus
from devflow.policy.loader import ResearchConfig
from devflow.storage.fs_backend import FSBackend


# =============================================================
# Fake Backend —— 完全可控的输入
# =============================================================

class FakeBackend:
    """测试用 backend,支持预设返回/异常/超时"""

    def __init__(
        self,
        name: str,
        source_type: SourceType,
        citations: Optional[list[Citation]] = None,
        raise_exc: Optional[Exception] = None,
        health: bool = True,
    ):
        self.name = name
        self.source_type = source_type
        self._citations = citations or []
        self._raise = raise_exc
        self._health = health
        self.search_call_count = 0

    def search(self, query: ResearchQuery) -> list[Citation]:
        self.search_call_count += 1
        if self._raise:
            raise self._raise
        return list(self._citations)  # 拷贝避免引用共享

    def health_check(self) -> bool:
        return self._health


def _make_citation(
    url: str = "https://example.com",
    title: str = "Example",
    snippet: str = "snippet",
    source: SourceType = SourceType.WEB,
    trust: TrustLevel = TrustLevel.MEDIUM,
) -> Citation:
    # pydantic 约束:url >= 1 字符,snippet <= 500 字符
    assert len(url) >= 1, f"url 不能为空: {url!r}"
    snippet = snippet[:500]
    return Citation(
        url=url,
        title=title,
        snippet=snippet,
        source_type=source,
        trust_level=trust,
    )


def _make_runner(
    tmp_path: Path,
    backends: list,
    config_overrides: Optional[dict] = None,
    spec_id: str = "20260819-test",
    write_spec: bool = True,
):
    """便捷构造 runner"""
    storage = FSBackend(tmp_path)
    storage.init_workspace("""
sop:
  sop_version: "0.1"
  phases: [intake, brainstorm, plan, contract, implement, verify, review, finish]
  intake_fast_skip: true
""")

    if write_spec:
        spec = Spec(
            id=spec_id,
            title="test",
            problem="test problem statement",
            goals=["g1"],
            non_goals=["ng1"],
            status=SpecStatus.DRAFT,
        )
        storage.write_spec(spec_id, spec.model_dump(mode="json"))
        storage.set_current_spec_id(spec_id)

    cfg_dict = {
        "enabled": True,
        "auto_run_on": ["plan_stage"],
        "sources": ["github", "web"],
        "max_results_per_source": 5,
        "max_total_chars": 8000,
        "timeout_per_source": 5,
        "fallback": "skip",
        "citation_required": True,
        "start_keywords": ["from scratch"],
    }
    if config_overrides:
        cfg_dict.update(config_overrides)
    config = ResearchConfig(**cfg_dict)

    runner = ResearchRunner(storage, config, tmp_path)
    # 用 patch 替换 select_backends
    return runner, storage, backends


# =============================================================
# 主路径
# =============================================================

class TestRunHappyPath:
    def test_basic_run_returns_citations(self, tmp_path):
        c1 = _make_citation(url="https://github.com/x/y", title="x/y")
        c2 = _make_citation(url="https://crates.io/crates/foo", title="foo")
        backends = [
            FakeBackend("github", SourceType.GITHUB, [c1]),
            FakeBackend("web", SourceType.WEB, [c2]),
        ]

        with patch(
            "devflow.engine.research_runner.select_backends",
            return_value=backends,
        ):
            runner, storage, _ = _make_runner(tmp_path, backends)
            result = runner.run("test query", spec_id="20260819-test")

        assert result["ok"] is True
        assert result["citations_count"] == 2
        assert "report_path" in result
        assert Path(tmp_path / result["report_path"]).exists()
        # 账本被写入
        entries = storage.get_ledger()["entries"]
        research_entries = [
            e for e in entries
            if e.get("action") == "research"
        ]
        assert len(research_entries) == 1
        assert research_entries[0]["phase"] == 2
        assert "github" in research_entries[0]["details"]

    def test_spec_research_refs_updated(self, tmp_path):
        c1 = _make_citation(trust=TrustLevel.HIGH)
        backends = [
            FakeBackend("web", SourceType.WEB, [c1]),
        ]
        with patch(
            "devflow.engine.research_runner.select_backends",
            return_value=backends,
        ):
            runner, storage, _ = _make_runner(tmp_path, backends)
            runner.run("test", spec_id="20260819-test")

        spec_data = storage.read_spec("20260819-test")
        assert len(spec_data["research_refs"]) == 1
        ref = spec_data["research_refs"][0]
        assert ref["trust_level"] == "high"  # 因含 HIGH 引用
        assert ref["citations_count"] == 1
        # 路径分隔符兼容 Windows/POSIX
        assert "research" in ref["path"]
        assert "20260819-test" in ref["path"]

    def test_markdown_contains_citations(self, tmp_path):
        c1 = _make_citation(
            url="https://github.com/x/y",
            title="x/y",
            snippet="A library",
        )
        backends = [FakeBackend("github", SourceType.GITHUB, [c1])]
        with patch(
            "devflow.engine.research_runner.select_backends",
            return_value=backends,
        ):
            runner, _, _ = _make_runner(tmp_path, backends)
            result = runner.run("test", spec_id="20260819-test")

        md_path = tmp_path / result["report_path"]
        content = md_path.read_text(encoding="utf-8")
        assert "# Research Report: test" in content
        assert "[1] x/y" in content
        assert "<https://github.com/x/y>" in content
        assert "> A library" in content

    def test_sources_used_tracked(self, tmp_path):
        """v0.4.1: 改为 backend 名字维度"""
        c1 = _make_citation(source=SourceType.GITHUB)
        c2 = _make_citation(url="https://x2.com", title="t2", source=SourceType.WEB)
        backends = [
            FakeBackend("github", SourceType.GITHUB, [c1]),
            FakeBackend("web", SourceType.WEB, [c2]),
        ]
        with patch(
            "devflow.engine.research_runner.select_backends",
            return_value=backends,
        ):
            runner, _, _ = _make_runner(tmp_path, backends)
            result = runner.run("test", spec_id="20260819-test")
        # v0.4.1: backend 名字
        assert set(result["backends_used"]) == {"github", "web"}
        assert result["fallback_used"] is True  # 2 backends 串联
        # sources_in_results 反映真实来源
        assert set(result["sources_in_results"]) == {"github", "web"}


# =============================================================
# 去重 + 截断
# =============================================================

class TestDedupeAndTruncate:
    def test_url_dedup_keeps_first(self, tmp_path):
        """URL 去重:并发执行下保留首次出现的 citation(顺序不依赖 backend 串行)"""
        url = "https://github.com/x/y"
        c1 = _make_citation(url=url, title="first", source=SourceType.GITHUB)
        c2 = _make_citation(url=url, title="second", source=SourceType.WEB)
        backends = [
            FakeBackend("github", SourceType.GITHUB, [c1]),
            FakeBackend("web", SourceType.WEB, [c2]),
        ]
        with patch(
            "devflow.engine.research_runner.select_backends",
            return_value=backends,
        ):
            runner, _, _ = _make_runner(tmp_path, backends)
            result = runner.run("test", spec_id="20260819-test")
        assert result["citations_count"] == 1  # 去重
        # 因并发,保留的不一定是 first;只断言 URL 存在 + 至少一个标题
        assert result["citations"][0]["url"] == url
        assert result["citations"][0]["title"] in ("first", "second")

    def test_url_dedup_serial_keeps_first(self, tmp_path):
        """串行执行下保留首次出现 - 用单 backend 模拟"""
        url = "https://github.com/x/y"
        c1 = _make_citation(url=url, title="first", source=SourceType.GITHUB)
        c2 = _make_citation(url=url, title="second", source=SourceType.GITHUB)
        # 单 backend,内含两条同 URL
        backends = [
            FakeBackend("github", SourceType.GITHUB, [c1, c2]),
        ]
        with patch(
            "devflow.engine.research_runner.select_backends",
            return_value=backends,
        ):
            runner, _, _ = _make_runner(tmp_path, backends)
            result = runner.run("test", spec_id="20260819-test")
        assert result["citations_count"] == 1
        # 单 backend 内顺序确定:首条保留
        assert result["citations"][0]["title"] == "first"

    def test_max_total_chars_truncates(self, tmp_path):
        # 每条 citation ~ 500 字符(snippet 上限),max_total_chars=600 → 仅 1 条
        big_snippet = "x" * 450  # snippet 上限 500
        c1 = _make_citation(url="https://1.com", title="t1", snippet=big_snippet)
        c2 = _make_citation(url="https://2.com", title="t2", snippet=big_snippet)
        c3 = _make_citation(url="https://3.com", title="t3", snippet=big_snippet)
        backends = [
            FakeBackend("web", SourceType.WEB, [c1, c2, c3]),
        ]
        with patch(
            "devflow.engine.research_runner.select_backends",
            return_value=backends,
        ):
            runner, _, _ = _make_runner(
                tmp_path, backends,
                config_overrides={"max_total_chars": 600},
            )
            result = runner.run("test", spec_id="20260819-test")
        # 首条 url (~13) + title (2) + snippet (450) = 465 < 600 ✓
        # 第二条累加 465 + 465 = 930 > 600 ✗
        assert result["citations_count"] == 1

    def test_empty_url_skipped(self, tmp_path):
        """空 url 在 backend 层应被过滤(用构造 mock 跳过 pydantic 校验)"""
        c_bad = Citation.model_construct(
            url="",
            title="bad",
            snippet="x",
            source_type=SourceType.WEB,
            trust_level=TrustLevel.MEDIUM,
            retrieved_at=None,
            metadata={},
        )
        c_ok = _make_citation(url="https://ok.com", title="ok")
        backends = [
            FakeBackend("web", SourceType.WEB, [c_bad, c_ok]),
        ]
        with patch(
            "devflow.engine.research_runner.select_backends",
            return_value=backends,
        ):
            runner, _, _ = _make_runner(tmp_path, backends)
            result = runner.run("test", spec_id="20260819-test")
        assert result["citations_count"] == 1
        assert result["citations"][0]["url"] == "https://ok.com"


# =============================================================
# 失败路径
# =============================================================

class TestFailurePaths:
    def test_all_backends_fail_skip_mode(self, tmp_path):
        """全部 backend 返回空 + fallback=skip → ok=True 但空报告(v0.4.1)
        - backends_used: []
        - backends_empty: [github, web] (健康但 0 命中)
        - backends_failed: []
        """
        backends = [
            FakeBackend("github", SourceType.GITHUB, []),
            FakeBackend("web", SourceType.WEB, []),
        ]
        with patch(
            "devflow.engine.research_runner.select_backends",
            return_value=backends,
        ):
            runner, storage, _ = _make_runner(
                tmp_path, backends,
                config_overrides={"fallback": "skip"},
            )
            result = runner.run("test", spec_id="20260819-test")

        assert result["ok"] is True  # 不阻断
        assert result["citations_count"] == 0
        assert result["backends_used"] == []
        assert set(result["backends_empty"]) == {"github", "web"}
        assert result["backends_failed"] == []
        # 报告仍落盘
        assert Path(tmp_path / result["report_path"]).exists()
        # 账本仍记录
        entries = [
            e for e in storage.get_ledger()["entries"]
            if e.get("action") == "research"
        ]
        assert len(entries) == 1

    def test_all_backends_fail_error_mode(self, tmp_path):
        """全部 backend 返回空 + fallback=error → ok=False(v0.4.1)"""
        backends = [
            FakeBackend("github", SourceType.GITHUB, []),
            FakeBackend("web", SourceType.WEB, []),
        ]
        with patch(
            "devflow.engine.research_runner.select_backends",
            return_value=backends,
        ):
            runner, storage, _ = _make_runner(
                tmp_path, backends,
                config_overrides={"fallback": "error"},
            )
            result = runner.run("test", spec_id="20260819-test")
        assert result["ok"] is False
        assert "全部 backend 未产出引用" in result["message"]

    def test_backend_exception_caught(self, tmp_path):
        """单个 backend 抛异常 → _safe_search 兜底,其他 backend 仍跑(v0.4.1)
        - backends_failed: [web] (抛异常)
        - backends_used: [github] (有命中)
        """
        c1 = _make_citation(source=SourceType.GITHUB)
        backends = [
            FakeBackend("github", SourceType.GITHUB, [c1]),
            FakeBackend(
                "web", SourceType.WEB, [],
                raise_exc=RuntimeError("network down"),
            ),
        ]
        with patch(
            "devflow.engine.research_runner.select_backends",
            return_value=backends,
        ):
            runner, _, _ = _make_runner(tmp_path, backends)
            result = runner.run("test", spec_id="20260819-test")
        assert result["ok"] is True
        assert result["citations_count"] == 1
        # v0.4.1: backend 名字维度
        assert "web" in result["backends_failed"]
        assert "github" in result["backends_used"]
        assert "web" not in result["backends_used"]
        assert "github" not in result["backends_failed"]
        # deprecated 字段也保留
        assert "web" in result["sources_failed"]
        assert "github" in result["sources_used"]

    def test_no_backends_available(self, tmp_path):
        """select_backends 返回空 → 报告失败"""
        with patch(
            "devflow.engine.research_runner.select_backends",
            return_value=[],
        ):
            runner, _, _ = _make_runner(tmp_path, [])
            result = runner.run("test", spec_id="20260819-test")
        assert result["ok"] is False
        assert "无可用 backend" in result["message"]

    # --- v0.4.1 新增测试 ---

    def test_empty_result_distinct_from_failed(self, tmp_path):
        """v0.4.1: 空结果不计入 failed, 计入 empty(诊断报告 §Bug 1)"""
        c1 = _make_citation(source=SourceType.GITHUB)
        backends = [
            FakeBackend("github", SourceType.GITHUB, [c1]),     # 命中
            FakeBackend("pypi", SourceType.PYPI, []),             # 健康但 0 命中
            FakeBackend("web", SourceType.WEB, [],                # 抛异常 -> failed
                        raise_exc=RuntimeError("timeout")),
        ]
        with patch(
            "devflow.engine.research_runner.select_backends",
            return_value=backends,
        ):
            runner, _, _ = _make_runner(tmp_path, backends)
            result = runner.run("test", spec_id="20260819-test")

        assert result["ok"] is True
        assert result["citations_count"] == 1
        # 三组维度互斥
        assert result["backends_used"] == ["github"]
        assert result["backends_empty"] == ["pypi"]
        assert result["backends_failed"] == ["web"]
        # 三组无交集
        all_b = set(result["backends_used"] + result["backends_empty"] + result["backends_failed"])
        assert all_b == {"github", "pypi", "web"}

    def test_sources_in_results_extracted_from_citations(self, tmp_path):
        """v0.4.1: sources_in_results 从 citations 提取,反映真实来源"""
        # registry backend 返回 npm 来源
        c1 = _make_citation(
            url="https://www.npmjs.com/package/a",
            source=SourceType.NPM,
        )
        c2 = _make_citation(
            url="https://www.npmjs.com/package/b",
            source=SourceType.NPM,
        )
        # RegistryQueryBackend 的 source_type 是 WEB (覆盖多源)
        backends = [
            FakeBackend("registry", SourceType.WEB, [c1, c2]),
        ]
        with patch(
            "devflow.engine.research_runner.select_backends",
            return_value=backends,
        ):
            runner, _, _ = _make_runner(tmp_path, backends)
            result = runner.run("test", spec_id="20260819-test")

        # sources_in_results 反映真实来源 npm (不是 web)
        assert "npm" in result["sources_in_results"]
        assert "web" not in result["sources_in_results"]
        # 但 backends_used 仍是 backend 名字
        assert "registry" in result["backends_used"]


# =============================================================
# Spec 不存在
# =============================================================

class TestSpecMissing:
    def test_spec_missing_skips_update(self, tmp_path):
        c1 = _make_citation()
        backends = [FakeBackend("web", SourceType.WEB, [c1])]
        with patch(
            "devflow.engine.research_runner.select_backends",
            return_value=backends,
        ):
            runner, storage, _ = _make_runner(
                tmp_path, backends,
                spec_id="nonexistent-spec",
                write_spec=False,
            )
            result = runner.run("test", spec_id="nonexistent-spec")

        assert result["ok"] is True
        # 报告已落盘
        assert Path(tmp_path / result["report_path"]).exists()
        # Spec 仍不存在
        assert storage.read_spec("nonexistent-spec") is None
        # 账本仍记录
        entries = [
            e for e in storage.get_ledger()["entries"]
            if e.get("action") == "research"
        ]
        assert len(entries) == 1


# =============================================================
# 并发
# =============================================================

class TestConcurrency:
    def test_timeout_does_not_deadlock(self, tmp_path):
        """慢 backend 触发 timeout,runner 仍能完成"""

        class SlowBackend:
            name = "slow"
            source_type = SourceType.WEB

            def search(self, query):
                import time
                time.sleep(20)  # 故意慢
                return []

            def health_check(self):
                return True

        fast = FakeBackend("fast", SourceType.WEB, [
            _make_citation(url="https://fast.com", title="fast")
        ])
        with patch(
            "devflow.engine.research_runner.select_backends",
            return_value=[SlowBackend(), fast],
        ):
            runner, _, _ = _make_runner(
                tmp_path, [fast],
                config_overrides={"timeout_per_source": 1},
            )
            # 整体超时上限 ~ 6s,但慢 backend 触发 Future timeout
            # runner 仍能拿到 fast 的结果
            import time
            start = time.time()
            result = runner.run("test", spec_id="20260819-test")
            elapsed = time.time() - start

        assert result["ok"] is True
        assert result["citations_count"] == 1
        assert elapsed < 10  # 不会卡死(主 timeout=6s)


# =============================================================
# 路径与摘要
# =============================================================

class TestPathAndSummary:
    def test_report_path_relative_to_workspace(self, tmp_path):
        backends = [FakeBackend("web", SourceType.WEB, [_make_citation()])]
        with patch(
            "devflow.engine.research_runner.select_backends",
            return_value=backends,
        ):
            runner, _, _ = _make_runner(tmp_path, backends)
            result = runner.run("test", spec_id="20260819-test")
        # 路径应是相对工作区的(Windows 用反斜杠,POSIX 用正斜杠)
        assert not result["report_path"].startswith(str(tmp_path))
        assert "docs" in result["report_path"]
        assert "research" in result["report_path"]
        assert result["report_path"].endswith(".md")
        # 真实文件存在
        assert (tmp_path / result["report_path"]).exists()

    def test_trust_level_high_when_any_high(self, tmp_path):
        c1 = _make_citation(trust=TrustLevel.HIGH, source=SourceType.GITHUB)
        c2 = _make_citation(
            url="https://x.com", trust=TrustLevel.LOW,
            source=SourceType.WEB,
        )
        backends = [
            FakeBackend("github", SourceType.GITHUB, [c1]),
            FakeBackend("web", SourceType.WEB, [c2]),
        ]
        with patch(
            "devflow.engine.research_runner.select_backends",
            return_value=backends,
        ):
            runner, storage, _ = _make_runner(tmp_path, backends)
            runner.run("test", spec_id="20260819-test")
        spec_data = storage.read_spec("20260819-test")
        assert spec_data["research_refs"][0]["trust_level"] == "high"

    def test_trust_level_medium_when_no_high(self, tmp_path):
        c1 = _make_citation(trust=TrustLevel.LOW, source=SourceType.WEB)
        backends = [FakeBackend("web", SourceType.WEB, [c1])]
        with patch(
            "devflow.engine.research_runner.select_backends",
            return_value=backends,
        ):
            runner, storage, _ = _make_runner(tmp_path, backends)
            runner.run("test", spec_id="20260819-test")
        spec_data = storage.read_spec("20260819-test")
        assert spec_data["research_refs"][0]["trust_level"] == "medium"

    def test_trust_level_unknown_when_empty(self, tmp_path):
        backends = [FakeBackend("web", SourceType.WEB, [])]
        with patch(
            "devflow.engine.research_runner.select_backends",
            return_value=backends,
        ):
            runner, storage, _ = _make_runner(tmp_path, backends)
            runner.run("test", spec_id="20260819-test")
        spec_data = storage.read_spec("20260819-test")
        assert spec_data["research_refs"][0]["trust_level"] == "unknown"

    def test_multiple_runs_accumulate_research_refs(self, tmp_path):
        backends = [FakeBackend("web", SourceType.WEB, [_make_citation()])]
        with patch(
            "devflow.engine.research_runner.select_backends",
            return_value=backends,
        ):
            runner, storage, _ = _make_runner(tmp_path, backends)
            runner.run("test1", spec_id="20260819-test")
            runner.run("test2", spec_id="20260819-test")
        spec_data = storage.read_spec("20260819-test")
        assert len(spec_data["research_refs"]) == 2