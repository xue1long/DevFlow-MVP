"""T2 单元测试: ResearchCache (v0.4.2 RFC §4)"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from devflow.engine.research_cache import ResearchCache
from devflow.model.research import CacheEntry


def _make_entry(
    key: str = "abc123",
    query: str = "python retry",
    created_offset: int = 0,
    expires_offset: int = 86400,  # 24h 默认
    **kwargs,
) -> CacheEntry:
    now = datetime.now(timezone.utc)
    return CacheEntry(
        key=key,
        query=query,
        sources=kwargs.get("sources", ["github", "web"]),
        max_results_per_source=kwargs.get("max_results_per_source", 5),
        spec_id=kwargs.get("spec_id", "test-spec"),
        report_path=kwargs.get("report_path", "docs/devflow/research/test.md"),
        citations_count=kwargs.get("citations_count", 3),
        backend_chain=kwargs.get("backend_chain", ["web_search"]),
        created_at=now + timedelta(seconds=created_offset),
        expires_at=now + timedelta(seconds=expires_offset),
    )


class TestMakeKey:
    def test_stable(self):
        """同输入 → 同 key"""
        k1 = ResearchCache.make_key("python retry", ["github", "web"], 5)
        k2 = ResearchCache.make_key("python retry", ["github", "web"], 5)
        assert k1 == k2
        assert len(k1) == 16  # sha256 前 16 字符

    def test_case_insensitive(self):
        """query 大小写无关"""
        k1 = ResearchCache.make_key("Python Retry", ["github"], 5)
        k2 = ResearchCache.make_key("python retry", ["github"], 5)
        assert k1 == k2

    def test_whitespace_normalized(self):
        """query 前后空格无关"""
        k1 = ResearchCache.make_key("  python retry  ", ["github"], 5)
        k2 = ResearchCache.make_key("python retry", ["github"], 5)
        assert k1 == k2

    def test_sources_sorted(self):
        """sources 顺序无关"""
        k1 = ResearchCache.make_key("q", ["github", "web"], 5)
        k2 = ResearchCache.make_key("q", ["web", "github"], 5)
        assert k1 == k2

    def test_different_query_different_key(self):
        """不同 query → 不同 key"""
        k1 = ResearchCache.make_key("query1", ["github"], 5)
        k2 = ResearchCache.make_key("query2", ["github"], 5)
        assert k1 != k2

    def test_different_max_results_different_key(self):
        """不同 max_results → 不同 key"""
        k1 = ResearchCache.make_key("q", ["github"], 5)
        k2 = ResearchCache.make_key("q", ["github"], 10)
        assert k1 != k2


class TestGetPut:
    def test_roundtrip(self, tmp_path):
        cache = ResearchCache(tmp_path / ".cache")
        entry = _make_entry(key="k1", query="test")
        cache.put(entry)
        loaded = cache.get("k1")
        assert loaded is not None
        assert loaded.key == entry.key
        assert loaded.query == entry.query
        assert loaded.citations_count == entry.citations_count

    def test_missing_key_returns_none(self, tmp_path):
        cache = ResearchCache(tmp_path / ".cache")
        assert cache.get("nonexistent") is None

    def test_expired_returns_none(self, tmp_path):
        cache = ResearchCache(tmp_path / ".cache", ttl_seconds=60)
        # 手动放一个已过期条目
        entry = _make_entry(
            key="k1",
            expires_offset=-1,  # 1 秒前过期
        )
        cache.put(entry)
        assert cache.get("k1") is None

    def test_corrupt_file_returns_none(self, tmp_path):
        cache = ResearchCache(tmp_path / ".cache")
        # 手动写损坏文件
        (tmp_path / ".cache" / "bad.json").write_text("not json", encoding="utf-8")
        assert cache.get("bad") is None

    def test_wrong_schema_returns_none(self, tmp_path):
        cache = ResearchCache(tmp_path / ".cache")
        # 缺少必填字段
        (tmp_path / ".cache" / "bad.json").write_text(
            '{"key": "bad"}', encoding="utf-8"
        )
        assert cache.get("bad") is None


class TestClear:
    def test_clear_single(self, tmp_path):
        cache = ResearchCache(tmp_path / ".cache")
        cache.put(_make_entry(key="k1"))
        cache.put(_make_entry(key="k2"))
        cleared = cache.clear(key="k1")
        assert cleared == 1
        assert cache.get("k1") is None
        assert cache.get("k2") is not None

    def test_clear_single_missing(self, tmp_path):
        cache = ResearchCache(tmp_path / ".cache")
        cleared = cache.clear(key="nonexistent")
        assert cleared == 0

    def test_clear_all(self, tmp_path):
        cache = ResearchCache(tmp_path / ".cache")
        for i in range(5):
            cache.put(_make_entry(key=f"k{i}"))
        cleared = cache.clear()
        assert cleared == 5
        assert cache.stats()["total_entries"] == 0

    def test_clear_all_empty(self, tmp_path):
        cache = ResearchCache(tmp_path / ".cache")
        cleared = cache.clear()
        assert cleared == 0


class TestStats:
    def test_stats_empty(self, tmp_path):
        cache = ResearchCache(tmp_path / ".cache", ttl_seconds=3600)
        s = cache.stats()
        assert s["total_entries"] == 0
        assert s["total_bytes"] == 0
        assert s["ttl_seconds"] == 3600
        assert "cache_dir" in s

    def test_stats_after_writes(self, tmp_path):
        cache = ResearchCache(tmp_path / ".cache")
        for i in range(3):
            cache.put(_make_entry(key=f"k{i}"))
        s = cache.stats()
        assert s["total_entries"] == 3
        assert s["total_bytes"] > 0


class TestInit:
    def test_creates_cache_dir(self, tmp_path):
        """init 时 mkdir -p"""
        cache_dir = tmp_path / "nested" / "deep" / ".cache"
        ResearchCache(cache_dir)
        assert cache_dir.exists()
        assert cache_dir.is_dir()

    def test_idempotent(self, tmp_path):
        """重复 init 不报错"""
        cache_dir = tmp_path / ".cache"
        ResearchCache(cache_dir)
        ResearchCache(cache_dir)
        assert cache_dir.exists()