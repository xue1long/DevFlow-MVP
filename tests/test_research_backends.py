"""T2 单元测试: research 适配层 (4 backend + 选择器)

所有网络调用通过 monkeypatch 完全 mock 化,CI 离线可跑。

覆盖:
- GitHubSearchBackend: API 解析 / trust 分级 / 错误兜底
- RegistryQueryBackend: PyPI 精确查询 / npm search / crates search
- WebSearchBackend: DuckDuckGo Abstract + RelatedTopics
- AgentReachBackend: 平台探测 / JSON 解析 / markdown 代码块兜底
- select_backends: 优先级 + sources 过滤 + health_check 降级
"""
import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from devflow.adapters.research import (
    AgentReachBackend,
    GitHubSearchBackend,
    RegistryQueryBackend,
    WebSearchBackend,
    select_backends,
    DEFAULT_BACKEND_ORDER,
)
from devflow.model.research import (
    Citation, ResearchQuery, SourceType, TrustLevel,
)


def _rq(query="python retry", **kwargs) -> ResearchQuery:
    """便捷构造 ResearchQuery(全部走默认值)"""
    defaults = dict(
        query=query,
        sources=[SourceType.GITHUB, SourceType.PYPI, SourceType.WEB],
        max_results_per_source=5,
        max_total_chars=8000,
        timeout_per_source=10,
    )
    defaults.update(kwargs)
    return ResearchQuery(**defaults)


def _make_urlopen_response(payload: dict):
    """构造 mock urlopen 返回值"""
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(payload).encode("utf-8")
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


# =============================================================
# GitHubSearchBackend
# =============================================================

class TestGitHubSearchBackend:
    def _backend(self):
        return GitHubSearchBackend()

    def test_health_check_true(self):
        b = self._backend()
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.read.return_value = b'{"items":[]}'
            assert b.health_check() is True

    def test_health_check_false_on_error(self):
        b = self._backend()
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = OSError("network down")
            assert b.health_check() is False

    def test_search_parses_items(self):
        b = self._backend()
        payload = {
            "items": [
                {
                    "html_url": "https://github.com/foo/bar",
                    "full_name": "foo/bar",
                    "description": "A retry lib",
                    "stargazers_count": 1500,
                    "language": "Python",
                    "updated_at": "2026-08-01T00:00:00Z",
                    "license": {"spdx_id": "MIT"},
                },
                {
                    "html_url": "https://github.com/baz/qux",
                    "full_name": "baz/qux",
                    "description": "Another",
                    "stargazers_count": 50,  # LOW
                    "language": "Python",
                    "updated_at": "2026-07-01T00:00:00Z",
                },
            ]
        }
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value = _make_urlopen_response(payload)
            citations = b.search(_rq())

        assert len(citations) == 2
        assert citations[0].title == "foo/bar"
        assert citations[0].url == "https://github.com/foo/bar"
        assert citations[0].source_type == SourceType.GITHUB
        assert citations[0].trust_level == TrustLevel.HIGH  # 1500 stars
        assert citations[0].metadata["stars"] == 1500
        assert citations[1].trust_level == TrustLevel.LOW  # 50 stars

    def test_search_truncates_per_max(self):
        b = self._backend()
        payload = {
            "items": [
                {
                    "html_url": f"https://github.com/x/{i}",
                    "full_name": f"x/{i}",
                    "description": "x",
                    "stargazers_count": 100,
                }
                for i in range(10)
            ]
        }
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value = _make_urlopen_response(payload)
            citations = b.search(_rq(max_results_per_source=3))
        assert len(citations) == 3

    def test_search_skips_invalid_items(self):
        b = self._backend()
        payload = {
            "items": [
                {"html_url": "", "full_name": "x"},  # 无 URL 跳过
                {"html_url": "https://github.com/x/y", "full_name": ""},  # 无 name 跳过
                {"html_url": "https://github.com/a/b", "full_name": "a/b", "description": "ok"},
            ]
        }
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value = _make_urlopen_response(payload)
            citations = b.search(_rq())
        assert len(citations) == 1
        assert citations[0].title == "a/b"

    def test_search_returns_empty_on_error(self):
        b = self._backend()
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = OSError("timeout")
            assert b.search(_rq()) == []

    def test_search_returns_empty_on_bad_json(self):
        b = self._backend()
        with patch("urllib.request.urlopen") as mock_urlopen:
            resp = MagicMock()
            resp.read.return_value = b"not json"
            resp.__enter__ = MagicMock(return_value=resp)
            resp.__exit__ = MagicMock(return_value=False)
            mock_urlopen.return_value = resp
            assert b.search(_rq()) == []

    def test_trust_thresholds(self):
        b = self._backend()
        cases = [
            (1000, TrustLevel.HIGH),
            (999, TrustLevel.MEDIUM),
            (100, TrustLevel.MEDIUM),
            (99, TrustLevel.LOW),
            (0, TrustLevel.LOW),
        ]
        for stars, expected in cases:
            assert b._judge_trust(stars) == expected

    def test_uses_token_when_present(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "secret_token_abc")
        b = self._backend()
        h = b._headers()
        assert h["Authorization"] == "Bearer secret_token_abc"

    def test_no_token_no_auth_header(self, monkeypatch):
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        b = self._backend()
        h = b._headers()
        assert "Authorization" not in h


# =============================================================
# RegistryQueryBackend
# =============================================================

class TestRegistryQueryBackend:
    def _backend(self):
        return RegistryQueryBackend()

    def test_health_check_true_if_any_works(self):
        b = self._backend()
        with patch.object(b, "_check_one", return_value=True):
            assert b.health_check() is True

    def test_health_check_false_if_all_fail(self):
        b = self._backend()
        with patch.object(b, "_check_one", return_value=False):
            assert b.health_check() is False

    def test_pypi_exact_match(self):
        b = self._backend()
        payload = {
            "info": {
                "name": "tenacity",
                "summary": "Retry library",
                "version": "8.2.0",
                "author": "Tenacity Team",
                "home_page": "https://github.com/jd/tenacity",
                "license": "MIT",
            }
        }
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value = _make_urlopen_response(payload)
            citations = b._search_pypi(_rq(query="tenacity"))

        assert len(citations) == 1
        c = citations[0]
        assert c.title == "tenacity"
        assert c.url == "https://github.com/jd/tenacity"
        assert c.source_type == SourceType.PYPI
        assert c.trust_level == TrustLevel.HIGH
        assert c.metadata["version"] == "8.2.0"

    def test_pypi_invalid_package_name_skips(self):
        b = self._backend()
        # 首个 token 含非法字符(@或/)无法作为包名
        with patch("urllib.request.urlopen") as mock_urlopen:
            citations = b._search_pypi(_rq(query="@#$invalid name"))
        assert citations == []
        mock_urlopen.assert_not_called()

    def test_pypi_empty_query_rejected_at_model_level(self):
        """空 query 应被 ResearchQuery 模型层拒绝(无需测 backend)"""
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            _rq(query="")

    def test_pypi_falls_back_to_project_url(self):
        b = self._backend()
        payload = {"info": {"name": "tenacity", "summary": "x", "version": "1.0"}}
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value = _make_urlopen_response(payload)
            citations = b._search_pypi(_rq(query="tenacity"))
        # 无 home_page/project_url → 落到 pypi.org/project/<name>
        assert citations[0].url == "https://pypi.org/project/tenacity"

    def test_pypi_404_returns_empty(self):
        b = self._backend()
        from urllib.error import HTTPError
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = HTTPError(
                "url", 404, "Not Found", {}, None
            )
            citations = b._search_pypi(_rq(query="nonexistent-pkg-xyz"))
        assert citations == []

    def test_npm_search(self):
        b = self._backend()
        payload = {
            "objects": [
                {
                    "package": {
                        "name": "axios",
                        "description": "HTTP client",
                        "version": "1.6.0",
                        "links": {"npm": "https://www.npmjs.com/package/axios"},
                        "publisher": {"username": "mzabriskie"},
                        "date": "2026-08-01T00:00:00.000Z",
                    }
                }
            ]
        }
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value = _make_urlopen_response(payload)
            citations = b._search_npm(_rq(query="axios"))
        assert len(citations) == 1
        assert citations[0].title == "axios"
        assert citations[0].url == "https://www.npmjs.com/package/axios"
        assert citations[0].source_type == SourceType.NPM
        assert citations[0].trust_level == TrustLevel.HIGH
        assert citations[0].metadata["author"] == "mzabriskie"

    def test_crates_search(self):
        b = self._backend()
        payload = {
            "crates": [
                {
                    "name": "tokio",
                    "description": "Async runtime",
                    "max_version": "1.35.0",
                    "downloads": 50000000,
                    "updated_at": "2026-08-01T00:00:00.000Z",
                }
            ]
        }
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value = _make_urlopen_response(payload)
            citations = b._search_crates(_rq(query="tokio"))
        assert len(citations) == 1
        assert citations[0].title == "tokio"
        assert citations[0].url == "https://crates.io/crates/tokio"
        assert citations[0].source_type == SourceType.CRATES
        assert citations[0].metadata["downloads"] == 50000000

    def test_search_dispatches_by_sources(self):
        b = self._backend()
        with patch.object(b, "_search_pypi", return_value=[]) as m_pypi, \
             patch.object(b, "_search_npm", return_value=[]) as m_npm, \
             patch.object(b, "_search_crates", return_value=[]) as m_crates:
            # 仅请求 PYPI
            citations = b.search(_rq(sources=[SourceType.PYPI]))
            m_pypi.assert_called_once()
            m_npm.assert_not_called()
            m_crates.assert_not_called()
            assert citations == []

    def test_search_ignores_unsupported_sources(self):
        b = self._backend()
        with patch.object(b, "_search_pypi", return_value=[]) as m_pypi:
            citations = b.search(_rq(sources=[SourceType.WEB]))  # 不支持
            m_pypi.assert_not_called()
            assert citations == []


# =============================================================
# WebSearchBackend
# =============================================================

class TestWebSearchBackend:
    def _backend(self):
        return WebSearchBackend()

    def test_health_check_true(self):
        b = self._backend()
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value.read.return_value = b"{}"
            assert b.health_check() is True

    def test_health_check_false_on_error(self):
        b = self._backend()
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = OSError()
            assert b.health_check() is False

    def test_search_uses_abstract_first(self):
        b = self._backend()
        payload = {
            "Abstract": "Python is a programming language.",
            "AbstractURL": "https://python.org",
            "Heading": "Python",
            "RelatedTopics": [],
        }
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value = _make_urlopen_response(payload)
            citations = b.search(_rq(query="python"))
        assert len(citations) == 1
        assert citations[0].title == "Python"
        assert citations[0].url == "https://python.org"
        assert citations[0].trust_level == TrustLevel.MEDIUM  # abstract 是 MEDIUM

    def test_search_falls_back_to_related_topics(self):
        b = self._backend()
        payload = {
            "Abstract": "",
            "AbstractURL": "",
            "RelatedTopics": [
                {
                    "FirstURL": "https://example.com/1",
                    "Text": "Topic 1 - About stuff",
                },
                {
                    "FirstURL": "https://example.com/2",
                    "Text": "Topic 2 description",
                },
            ],
        }
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value = _make_urlopen_response(payload)
            citations = b.search(_rq())
        assert len(citations) == 2
        assert citations[0].title == "Topic 1"  # 取 "-" 之前
        assert citations[0].trust_level == TrustLevel.LOW

    def test_search_skips_topics_with_subtopics(self):
        b = self._backend()
        payload = {
            "Abstract": "",
            "AbstractURL": "",
            "RelatedTopics": [
                {"Topics": [{"FirstURL": "x", "Text": "nested"}]},  # 嵌套跳过
                {
                    "FirstURL": "https://example.com/leaf",
                    "Text": "Leaf topic",
                },
            ],
        }
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value = _make_urlopen_response(payload)
            citations = b.search(_rq())
        assert len(citations) == 1
        assert citations[0].title == "Leaf topic"

    def test_search_returns_empty_on_error(self):
        b = self._backend()
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = OSError("offline")
            assert b.search(_rq()) == []

    def test_search_truncates_max(self):
        b = self._backend()
        payload = {
            "Abstract": "",
            "AbstractURL": "",
            "RelatedTopics": [
                {"FirstURL": f"https://x.com/{i}", "Text": f"Topic {i}"}
                for i in range(20)
            ],
        }
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.return_value = _make_urlopen_response(payload)
            citations = b.search(_rq(max_results_per_source=3))
        assert len(citations) == 3


# =============================================================
# AgentReachBackend
# =============================================================

class TestAgentReachBackend:
    def _backend(self, tmp_path):
        return AgentReachBackend(tmp_path)

    def test_health_check_via_env(self, monkeypatch, tmp_path):
        monkeypatch.setenv("CLAUDE_CODE", "1")
        b = self._backend(tmp_path)
        assert b.health_check() is True

    def test_health_check_via_skill_file(self, tmp_path):
        skill = tmp_path / ".claude/skills/agent-reach/SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text("# agent-reach", encoding="utf-8")
        b = self._backend(tmp_path)
        assert b.health_check() is True

    def test_health_check_false_when_nothing(self, tmp_path, monkeypatch):
        monkeypatch.delenv("CLAUDE_CODE", raising=False)
        monkeypatch.delenv("WORKBUDDY_RUNTIME", raising=False)
        monkeypatch.delenv("CODEBUDDY_RUNTIME", raising=False)
        # PATH 中不应有 claude/wb/codebuddy 命令(除非用户机器真有)
        # 这里只验证文件不存在 + env 缺失时 fallback 到 PATH 检查
        # 如果机器真有这些命令,health_check 可能 True → 测试跳过
        import shutil
        if any(shutil.which(c) for c in ["claude", "wb", "codebuddy"]):
            pytest.skip("machine has agent-reach CLI installed")
        b = self._backend(tmp_path)
        assert b.health_check() is False

    def test_search_invokes_subprocess(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE", "1")
        b = self._backend(tmp_path)
        payload = json.dumps({
            "citations": [
                {
                    "url": "https://example.com",
                    "title": "Example",
                    "snippet": "snippet",
                    "source": "github",
                    "trust": "high",
                }
            ]
        })
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout=payload, stderr=""
            )
            citations = b.search(_rq())
        assert len(citations) == 1
        assert citations[0].url == "https://example.com"
        assert citations[0].source_type == SourceType.GITHUB
        assert citations[0].trust_level == TrustLevel.HIGH

    def test_search_parses_markdown_json_block(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE", "1")
        b = self._backend(tmp_path)
        # agent-reach 输出包在 markdown 代码块里
        payload = (
            '好的,以下是结果:\n'
            '```json\n'
            '{"citations":[{"url":"https://x.com","title":"X","snippet":"s",'
            '"source":"web","trust":"medium"}]}\n'
            '```\n'
        )
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout=payload, stderr=""
            )
            citations = b.search(_rq())
        assert len(citations) == 1
        assert citations[0].url == "https://x.com"

    def test_search_returns_empty_on_subprocess_error(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE", "1")
        b = self._backend(tmp_path)
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=1, stdout="", stderr="auth failed"
            )
            citations = b.search(_rq())
        assert citations == []

    def test_search_returns_empty_on_timeout(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE", "1")
        b = self._backend(tmp_path)
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd="x", timeout=10)
            citations = b.search(_rq())
        assert citations == []

    def test_search_skips_invalid_citations(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE", "1")
        b = self._backend(tmp_path)
        payload = json.dumps({
            "citations": [
                {"url": "", "title": "no-url"},  # 无 URL
                {"url": "https://x.com", "title": ""},  # 无 title
                {"url": "https://x.com/ok", "title": "ok"},  # OK
            ]
        })
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout=payload, stderr=""
            )
            citations = b.search(_rq())
        assert len(citations) == 1
        assert citations[0].title == "ok"

    def test_source_mapping(self):
        from devflow.adapters.research.agent_reach import AgentReachBackend as A
        assert A._map_source("github") == SourceType.GITHUB
        assert A._map_source("PYPI") == SourceType.PYPI
        assert A._map_source("unknown") == SourceType.WEB

    def test_trust_mapping(self):
        from devflow.adapters.research.agent_reach import AgentReachBackend as A
        assert A._map_trust("HIGH") == TrustLevel.HIGH
        assert A._map_trust("low") == TrustLevel.LOW
        assert A._map_trust("weird") == TrustLevel.UNKNOWN


import subprocess  # 必须在 TestAgentReachBackend 之后 import 否则 patch 失效


# =============================================================
# select_backends
# =============================================================

class TestSelectBackends:
    def test_default_order(self, tmp_path):
        backends = select_backends(tmp_path, include_unhealthy=True)
        names = [b.name for b in backends]
        # agent_reach 必须在前
        assert names[0] == "agent_reach"
        assert names == DEFAULT_BACKEND_ORDER

    def test_sources_filter_excludes(self, tmp_path, monkeypatch):
        # 全部 health_check 失败 → fallback 到保留全部
        # 但 sources 过滤仍生效
        monkeypatch.setattr(
            "devflow.adapters.research.github_search.GitHubSearchBackend.health_check",
            lambda self: True,
        )
        backends = select_backends(tmp_path, sources=["github"])
        # 只保留 github
        assert all(b.name == "github" for b in backends)

    def test_sources_registry_matches_pypi_npm_crates(self, tmp_path):
        backends = select_backends(
            tmp_path, sources=["pypi"], include_unhealthy=True
        )
        # registry 应被包含(它覆盖 pypi)
        names = [b.name for b in backends]
        assert "registry" in names
        # github 不应被包含
        assert "github" not in names

    def test_health_check_filters_unhealthy(self, tmp_path):
        with patch(
            "devflow.adapters.research.github_search.GitHubSearchBackend.health_check",
            return_value=False,
        ), patch(
            "devflow.adapters.research.web_search.WebSearchBackend.health_check",
            return_value=True,
        ):
            backends = select_backends(tmp_path, include_unhealthy=False)
            names = [b.name for b in backends]
            assert "github" not in names
            assert "web" in names

    def test_all_unhealthy_returns_all(self, tmp_path):
        with patch(
            "devflow.adapters.research.github_search.GitHubSearchBackend.health_check",
            return_value=False,
        ), patch(
            "devflow.adapters.research.web_search.WebSearchBackend.health_check",
            return_value=False,
        ):
            backends = select_backends(tmp_path, include_unhealthy=False)
            # 全失败 → 降级保留全部
            assert len(backends) > 0