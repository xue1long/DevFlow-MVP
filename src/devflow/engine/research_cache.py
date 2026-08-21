"""ResearchCache — research 报告本地缓存 (v0.4.2 RFC §4)

职责:
  - 生成 cache key (基于 query + sources + max_results)
  - 读 / 写 / 清缓存条目 (基于 TTL)
  - 统计 (供 --clear-cache 输出)

设计要点:
  - 跨 Spec 共享 (key 不含 spec_id, v1 设计)
  - 简单 TTL 策略 (无 LRU/LFU)
  - 文件损坏/过期一律返回 None (触发重跑)
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Optional

from ..model.research import CacheEntry


class ResearchCache:
    """本地文件系统缓存, 简单 TTL 策略"""

    def __init__(self, cache_dir: Path, ttl_seconds: int = 86400):
        self.cache_dir = Path(cache_dir)
        self.ttl_seconds = ttl_seconds
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def make_key(
        query: str,
        sources: list[str],
        max_results_per_source: int,
    ) -> str:
        """生成缓存键 (跨 Spec 共享, 不含 spec_id)

        key 是 SHA256 前 16 字符 (足够去重且文件名短)
        """
        normalized = {
            "query": query.lower().strip(),
            "sources": sorted(sources),
            "max_results_per_source": max_results_per_source,
        }
        raw = json.dumps(normalized, sort_keys=True)
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def get(self, key: str) -> Optional[CacheEntry]:
        """读缓存, 过期或损坏返回 None (触发重跑)"""
        path = self._path(key)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            entry = CacheEntry(**data)
        except Exception:
            # 文件损坏 → 当作 miss, 触发重跑覆盖
            return None
        if entry.is_expired():
            return None
        return entry

    def put(self, entry: CacheEntry) -> None:
        """写缓存 (覆盖式)"""
        import json
        path = self._path(entry.key)
        # v0.4.2 修复: model_dump_json 无 mode 参数;
        # model_dump(mode="json") 返回 dict, 需 json.dumps 序列化
        path.write_text(
            json.dumps(entry.model_dump(mode="json"), ensure_ascii=False),
            encoding="utf-8",
        )

    def clear(self, key: Optional[str] = None) -> int:
        """清缓存. None 清全部, 否则清单个. 返回清除条目数"""
        if key:
            path = self._path(key)
            if path.exists():
                path.unlink()
                return 1
            return 0
        cleared = 0
        for p in self.cache_dir.glob("*.json"):
            p.unlink()
            cleared += 1
        return cleared

    def stats(self) -> dict:
        """缓存统计 (供 --clear-cache 输出用)"""
        total_size = sum(
            p.stat().st_size for p in self.cache_dir.glob("*.json")
        )
        return {
            "total_entries": len(list(self.cache_dir.glob("*.json"))),
            "total_bytes": total_size,
            "ttl_seconds": self.ttl_seconds,
            "cache_dir": str(self.cache_dir),
        }

    def _path(self, key: str) -> Path:
        return self.cache_dir / f"{key}.json"