---
title: DevFlow RFC v0.4.2 — Research 缓存
subtitle: 24h 同 query 复用,直接降 API 成本
version: 0.1
date: 2026-08-21
status: implemented
tags: [devflow, rfc, v0.4, research, cache]
related:
  - ../PR_DESCRIPTION_V0.4_RESEARCH.md
  - ./post-v0.4-research-diagnosis.md
  - ./release-notes-v0.4.1.md
  - ./release-notes-v0.4.2.md
---

# RFC v0.4.2: Research 缓存（24h 同 query 复用）

> **优先级**：⭐⭐⭐⭐⭐
> **投入**：1.5-2 天
> **价值**：直接降 API 成本 + 离线场景友好 + 端到端耗时从 5-10s 降到 < 0.5s
> **依赖**：无（纯本地存储）
> **状态**：✅ **已落地**（v0.4.2 实装 commit `27f8d71`）

---

## 0. 目标与非目标

### 0.1 目标

让 `devflow research` 在 **24h 内同 query** 复用上次的报告，避免：
- 重复调 API（GitHub/PyPI 速率限制）
- 浪费时间（每次 5-10s 网络等待）
- 浪费钱（agent-reach 调用费用）

### 0.2 非目标

- ❌ 不做 LRU/LFU 淘汰策略（24h TTL 足够简单）
- ❌ 不做跨 Spec cache 共享（每个 Spec 独立 cache，简化键空间）
- ❌ 不做 cache 预热（按需 lazy load）
- ❌ 不做分布式缓存（本地 `.cache/` 目录）
- ❌ 不做缓存命中率统计（v0.5+ 再说）

> **v0.4.2 v1 决定**：跨 Spec 共享（key 不含 spec_id），高价值优于隔离简化

---

## 1. 用户旅程

### 场景 A：同 query 二次跑（核心场景）

```bash
# 第一次跑：调 4 backend，花 8s
$ devflow research "python retry library" --spec-id 20260821-test
{
  "ok": true,
  "citations_count": 8,
  "cache_hit": false,           ← 新字段
  "cache_age_seconds": 0,
  ...
}

# 5 分钟后再跑同 query：直接读 cache，0.2s
$ devflow research "python retry library" --spec-id 20260821-test
{
  "ok": true,
  "citations_count": 8,
  "cache_hit": true,            ← 命中!
  "cache_age_seconds": 312,     ← 5 分钟前
  ...
}
```

### 场景 B：跨 Spec 同 query（v0.4.2 v1 设计：共享）

```bash
# Spec A 跑过,缓存
$ devflow research "tenacity python" --spec-id spec-A
# ...调 API,落 cache

# Spec B 跑同 query：命中 cache,但**仍创建 spec-B 的 research_refs 条目**
$ devflow research "tenacity python" --spec-id spec-B
{
  "ok": true,
  "cache_hit": true,
  "shared_from_spec": "spec-A", ← 新字段,可追溯
  ...
}
```

### 场景 C：缓存过期（>24h）

```bash
# 25h 后跑同 query：cache 视为过期,重新调 API
$ devflow research "python retry library" --spec-id 20260821-test
{
  "ok": true,
  "cache_hit": false,
  "cache_age_seconds": 90000,   ← > 24h, 已过期
  ...
}
```

### 场景 D：手动清理缓存

```bash
$ devflow research --clear-cache
{
  "ok": true,
  "cleared_entries": 3,
  "freed_bytes": 12480,
  ...
}

# 或清单个 query
$ devflow research "python retry library" --clear-cache
{
  "ok": true,
  "cleared_entries": 1,
}
```

---

## 2. 架构

```
cli.py (research 命令新增 --clear-cache 选项)
   ↓
engine/research_runner.py
   ↓
Cache 层 (新): ResearchCache
   ├ Key: hash(query + sources + max_results)
   ├ Value: CacheEntry (JSON)
   ├ TTL: 24h (sop.yaml.research.cache.ttl_seconds 可配)
   └ Storage: docs/devflow/research/.cache/<key>.json
```

### 缓存键设计

```python
cache_key = sha256(json.dumps({
    "query": query.lower().strip(),          # 规范化
    "sources": sorted(sources),                # 排序保证稳定
    "max_results_per_source": max_results,
}, sort_keys=True)).hexdigest()[:16]
```

**为什么 key 不含 spec_id**：
- 跨 Spec 共享时 `Spec.research_refs` 仍各自追加（不污染）
- 简化第一版：高价值优于隔离
- v0.5+ 如需隔离（多 Spec 不同 SOP 配置），再把 spec_id 加进 key

---

## 3. 数据模型

### 3.1 新增 `model/research.py::CacheEntry`

```python
class CacheEntry(BaseModel):
    """缓存条目"""
    key: str                                # sha256 前 16 字符
    query: str                              # 规范化后的 query
    sources: list[str]                      # 数据源列表
    max_results_per_source: int
    spec_id: str                            # 首次创建时的 spec_id
    report_path: str                        # Markdown 报告相对路径
    citations_count: int
    backend_chain: list[str]
    created_at: datetime
    expires_at: datetime                    # created_at + ttl_seconds

    def is_expired(self) -> bool:
        return datetime.now(timezone.utc) > self.expires_at

    def age_seconds(self) -> int:
        return int((datetime.now(timezone.utc) - self.created_at).total_seconds())
```

### 3.2 缓存文件格式（JSON）

`docs/devflow/research/.cache/<key>.json`:

```json
{
  "key": "a1b2c3d4e5f67890",
  "query": "python retry library",
  "sources": ["github", "pypi", "npm", "web"],
  "max_results_per_source": 5,
  "spec_id": "20260821-test",
  "report_path": "docs/devflow/research/20260821-test-153012.md",
  "citations_count": 8,
  "backend_chain": ["registry", "web_search"],
  "created_at": "2026-08-21T00:30:00Z",
  "expires_at": "2026-08-22T00:30:00Z"
}
```

---

## 4. 缓存层：`engine/research_cache.py`

```python
"""ResearchCache — research 报告本地缓存 (v0.4.2 RFC §4)"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ..model.research import CacheEntry


class ResearchCache:
    """本地文件系统缓存, 简单 TTL 策略"""

    def __init__(self, cache_dir: Path, ttl_seconds: int = 86400):
        self.cache_dir = cache_dir
        self.ttl_seconds = ttl_seconds
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def make_key(
        query: str,
        sources: list[str],
        max_results_per_source: int,
    ) -> str:
        """生成缓存键 (跨 Spec 共享, 不含 spec_id)"""
        normalized = {
            "query": query.lower().strip(),
            "sources": sorted(sources),
            "max_results_per_source": max_results_per_source,
        }
        raw = json.dumps(normalized, sort_keys=True)
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def get(self, key: str) -> Optional[CacheEntry]:
        """读缓存, 过期返回 None"""
        path = self._path(key)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            entry = CacheEntry(**data)
        except Exception:
            return None
        if entry.is_expired():
            return None
        return entry

    def put(self, entry: CacheEntry) -> None:
        """写缓存 (覆盖式)"""
        path = self._path(entry.key)
        path.write_text(entry.model_dump_json(mode="json"), encoding="utf-8")

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
        """缓存统计 (给 --clear-cache 输出用)"""
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
```

---

## 5. 编排层：`engine/research_runner.py` 集成

```python
class ResearchRunner:
    def __init__(
        self,
        storage: StorageBackend,
        config: ResearchConfig,
        workspace_root: Path,
    ):
        ...
        # v0.4.2: 缓存层
        self.cache = ResearchCache(
            cache_dir=workspace_root / "docs" / "devflow" / "research" / ".cache",
            ttl_seconds=config.cache.ttl_seconds,
        )

    def run(self, query: str, spec_id: str, sources=None) -> dict:
        # 0. v0.4.2: 缓存查询
        sources_resolved = sources or [SourceType(s) for s in self.config.sources]
        cache_key = ResearchCache.make_key(
            query,
            [s.value for s in sources_resolved],
            self.config.max_results_per_source,
        )
        if self.config.cache.enabled:
            cached = self.cache.get(cache_key)
            if cached is not None:
                # v0.4.2 缓存命中: 复用报告 + 仍更新 Spec.research_refs
                self._update_spec_from_cache(spec_id, cached)
                self._append_cache_hit_ledger(spec_id, cached)
                return self._build_cache_hit_result(cached)

        # 1-12. 原逻辑 (略)...完成后:
        # v0.4.2: 写入缓存
        if self.config.cache.enabled:
            self.cache.put(CacheEntry(
                key=cache_key,
                query=query,
                sources=[s.value for s in sources_resolved],
                max_results_per_source=self.config.max_results_per_source,
                spec_id=spec_id,
                report_path=self._relpath(report_path),
                citations_count=len(trimmed),
                backend_chain=backend_chain,
                created_at=datetime.now(timezone.utc),
                expires_at=datetime.now(timezone.utc)
                    + timedelta(seconds=self.config.cache.ttl_seconds),
            ))
```

### 5.1 缓存命中时的行为

- ✅ **复用** Markdown 报告路径（不重新生成）
- ✅ **追加** `Spec.research_refs`（含 `cache_hit: true` 标记）
- ✅ **写账本** `action=research, details="cache_hit=true, age_seconds=N"`
- ❌ **不调 API**（节省成本）
- ❌ **不更新原 Markdown**（报告原状保留）

### 5.2 返回 JSON 新字段

```python
{
    # v0.4.1 字段 (保留)
    "ok": true,
    "citations_count": 8,
    "backends_used": [...],
    ...
    # v0.4.2 新字段
    "cache_hit": true,
    "cache_age_seconds": 312,
    "cache_key": "a1b2c3d4...",
}
```

---

## 6. SOP 配置

### 6.1 `sop.yaml` 新增 `research.cache` 段

```yaml
research:
  enabled: true
  auto_run_on: [plan_stage]
  sources: [github, pypi, npm, web]
  max_results_per_source: 5
  max_total_chars: 8000
  timeout_per_source: 10
  fallback: skip
  citation_required: true
  start_keywords: ["from scratch", ...]
  # v0.4.2 新增
  cache:
    enabled: true                  # 总开关
    ttl_seconds: 86400             # 24h (默认)
    shared_across_specs: true      # 跨 Spec 共享 (v1)
```

### 6.2 `policy/loader.py::ResearchConfig` 扩展

```python
class ResearchCacheConfig(BaseModel):
    enabled: bool = True
    ttl_seconds: int = Field(default=86400, ge=60, le=2592000)  # 1min ~30d
    shared_across_specs: bool = True


class ResearchConfig(BaseModel):
    ...  # 现有字段
    cache: ResearchCacheConfig = Field(default_factory=ResearchCacheConfig)
```

---

## 7. CLI

### 7.1 `cli.py` 加 `--clear-cache` 选项

```python
@app.command()
def research(
    query: str = typer.Argument("", help="调研关键词(留空仅清缓存)"),
    spec_id: Optional[str] = typer.Option(None, "--spec-id", "-s"),
    sources: str = typer.Option("github,pypi,web", "--sources"),
    max_results: int = typer.Option(5, "--max-results", "-n"),
    clear_cache: bool = typer.Option(
        False, "--clear-cache",
        help="清缓存(query 为空则清全部,否则清该 query)",
    ),
):
    ...
    if clear_cache:
        runner = ResearchRunner(storage, config.research, _get_root())
        cleared = runner.cache.clear(
            key=runner.cache.make_key(query, ..., ...)
            if query else None
        )
        _output({"ok": True, "cleared_entries": cleared})
        return
    ...
```

### 7.2 用法

```bash
# 清全部缓存
devflow research --clear-cache

# 清单个 query
devflow research "python retry library" --clear-cache

# 正常跑 (自动用缓存)
devflow research "python retry library" --spec-id x

# 禁用缓存 (临时)
devflow research "python retry library" --no-cache  # 新选项
```

---

## 8. 测试矩阵

### 8.1 单元测试（research_cache.py）

| 测试 | 覆盖 |
|---|---|
| `test_make_key_stable` | 同 query+参数 → 同 key |
| `test_make_key_case_insensitive` | 大小写无关 |
| `test_get_returns_none_on_missing` | 不存在的 key → None |
| `test_get_returns_none_on_expired` | TTL 过期 → None |
| `test_put_and_get_roundtrip` | 写读一致 |
| `test_clear_single_key` | 单 key 清除 |
| `test_clear_all` | 全部清除 + 计数 |
| `test_stats` | 统计字段 |

### 8.2 集成测试（research_runner.py）

| 测试 | 覆盖 |
|---|---|
| `test_cache_hit_reuses_report` | 命中 → 不调 backend |
| `test_cache_miss_runs_backends` | 不命中 → 调 backend + 写缓存 |
| `test_cache_disabled_skips_lookup` | `cache.enabled=false` → 总是跑 |
| `test_cache_hit_updates_spec` | 命中仍追加 `Spec.research_refs` |
| `test_cache_hit_writes_ledger` | 命中仍写账本 + 标记 `cache_hit=true` |
| `test_cross_spec_shared_cache` | Spec A 命中 → Spec B 复用 |
| `test_expired_cache_triggers_rerun` | 过期 → 重新调 |

### 8.3 CLI 测试

| 测试 | 覆盖 |
|---|---|
| `test_clear_cache_all` | `devflow research --clear-cache` |
| `test_clear_cache_single` | `devflow research "q" --clear-cache` |
| `test_cache_hit_in_output` | 输出 JSON 含 `cache_hit: true` |

---

## 9. 性能预算

| 指标 | 无缓存 | 有缓存（命中） |
|---|---|---|
| 端到端耗时 | 5-10s | < 0.5s |
| API 调用次数 | 4 backends | 0 |
| 网络依赖 | 强 | 弱（只读本地 cache 文件） |

---

## 10. 风险与缓解

| 风险 | 等级 | 缓解 |
|---|---|---|
| cache 目录被 git 追踪 | 低 | `.gitignore` 加 `docs/devflow/research/.cache/` |
| cache 文件损坏（手动编辑）| 低 | `CacheEntry(**data)` 解析失败返回 None, 触发重跑 |
| 跨 Spec 共享导致 stale 引用 | 中 | `shared_across_specs: false` 可关闭（v1 默认 true）|
| 缓存击穿（多进程同时 miss）| 低 | MVP 单进程，无并发击穿问题；v0.5+ 再考虑 |
| 大 cache 占磁盘 | 低 | TTL 24h + 简单 GC（启动时扫过期文件清理）|

---

## 11. 设计权衡（Why）

| 决策 | 理由 |
|---|---|
| **24h TTL 而非永久** | 库版本/项目状态会变，太长会误导用户 |
| **跨 Spec 共享 (v1)** | 同一 query 高概率结果一致；隔离复杂度不值 |
| **JSON 存储而非 pickle** | 可读、可调试、版本演进友好 |
| **key 不含 spec_id** | 跨 Spec 共享前提；v0.5+ 需隔离再加 |
| **cache_hit 仍追加 Spec.research_refs** | 审计追溯要求：所有调用都有记录 |
| **不更新原 Markdown** | 报告是 cache 的内容，不是 Spec 的；改它会破坏 cache 一致性 |

---

## 12. 文档更新

- `README.md`: `### Research` 段加"自动 24h 缓存" + `--clear-cache` 用法
- `docs/release-notes-v0.4.2.md`: 新 release notes
- `docs/devflow-architecture-v0.1.md` §5.3: 加缓存层说明
- `docs/CHANGELOG.md`: 加 v0.4.2 条目

---

## 13. 落地任务 DAG（1.5-2 天）

```
T1 (0.5 天): model/research.py 加 CacheEntry + policy/loader.py 加 ResearchCacheConfig
T2 (0.5 天): engine/research_cache.py 实现 + 单测
T3 (0.5 天): engine/research_runner.py 集成 cache (lookup/hit/miss/expire) + 集成测
T4 (0.5 天): cli.py --clear-cache + 文档 + CHANGELOG + release notes
```

---

**RFC v0.4.2 · 2026-08-21 · ✅ 已落地 · 见 release-notes-v0.4.2.md**