# DevFlow v0.4.2 Release Notes

> **发布日期**: 2026-08-21
> **类型**: Minor feature release（research 子能力增强 + dogfooding 顺手修）
> **基于**: v0.4.0 / v0.4.1（必须先升级）
> **测试**: 215 passed + 1 skipped（30s 全套）
> **重要程度**: ⭐⭐⭐⭐（推荐升级，**直接降 API 成本**）

---

## 🎯 这个版本做了什么

v0.4.2 在 v0.4.0/v0.4.1 引文式调研基础上：

1. **新增 24h 本地缓存** —— 同 query 24h 内复用报告，**不调 API**、**不花时间**
2. **顺手修 2 个 dogfooding 发现的问题** —— SOP 多文件一致性 + auto_run_on 语义不一致

---

## 🆕 新增功能：24h 缓存

### 用户旅程

```bash
# 首次跑（5-10s,调 4 backend,写缓存）
$ devflow research "python retry library" --spec-id 20260821-test
{
  "ok": true,
  "citations_count": 8,
  "cache_hit": false,
  "cache_key": "a1b2c3d4e5f67890",
  ...
}

# 5 分钟后再跑（< 0.5s,不调 backend, 复用缓存）
$ devflow research "python retry library" --spec-id 20260821-test
{
  "ok": true,
  "citations_count": 8,
  "cache_hit": true,           ← 命中!
  "cache_age_seconds": 312,    ← 5 分钟前
  "cache_key": "a1b2c3d4e5f67890",
  "message": "调研完成 (cache 命中, 312s 前), 8 条引用",
  ...
}

# 手动清缓存
$ devflow research --clear-cache
{
  "ok": true,
  "cleared_entries": 3,
  "stats": {"total_entries": 0, "total_bytes": 0, ...}
}

# 清单个 query
$ devflow research "python retry library" --clear-cache
{ "ok": true, "cleared_entries": 1 }
```

### 缓存层架构

```
cli.py (research 命令新增 --clear-cache 选项)
   ↓
engine/research_runner.py
   ↓
Cache 层 (新): ResearchCache
   ├ Key: hash(query + sources + max_results) — sha256 前16字符
   ├ Value: CacheEntry (Pydantic, 含 TTL)
   ├ TTL: 24h (sop.yaml.research.cache.ttl_seconds 可配)
   └ Storage: docs/devflow/research/.cache/<key>.json
```

### 缓存键设计

```python
cache_key = sha256(json.dumps({
    "query": query.lower().strip(),
    "sources": sorted(sources),
    "max_results_per_source": max_results,
}, sort_keys=True)).hexdigest()[:16]
```

**v1 决策**：跨 Spec 共享（key 不含 spec_id）—— 同 query 高概率结果一致。

### 性能对比

| 指标 | 无缓存 | 有缓存（命中） |
|---|---|---|
| 端到端耗时 | 5-10s | **< 0.5s** |
| API 调用次数 | 4 backends | **0** |
| 网络依赖 | 强 | 弱（只读本地 cache） |

### 行为保证

- ✅ **缓存命中**：不调 API，但**仍追加** `Spec.research_refs` + **写账本**（审计追溯完整性）
- ✅ **缓存过期**（>24h）：自动重跑，缓存被覆盖
- ✅ **缓存禁用**（`sop.yaml.research.cache.enabled: false`）：ttl=0，所有条目视为过期
- ✅ **文件损坏**：当作 miss，触发重跑覆盖

---

## 🐛 Dogfooding 顺手修的 2 个问题

### B1: SOP 多文件一致性

**问题**：

`devflow init` 时 `sop.yaml` 来源有 3 个：
- `config/sop.default.yaml`（init 复制模板）✅ 含 `research.cache` 段
- `sop.yaml`（项目实例，`.gitignore`）❌ 缺 `cache` 段
- `cli.py` 内嵌兜底（无 sop 文件时用）❌ 缺 `cache` 段

**修复**：

3 份 SOP 文件全部统一补全 `cache: {enabled: true, ttl_seconds: 86400, shared_across_specs: true}`。

### B2: `auto_run_on=[plan_stage]` 语义不一致

**问题**：

SOP 配 `research.auto_run_on=[plan_stage]` 暗示"进入 plan 阶段自动跑 research"，但**只在 `devflow plan` 命令触发**，不在 `state_machine.next_phase()` 从 brainstorm → plan 时触发。

**修复**：

`state_machine.py::_advance_tasks_for_phase()` 新增 `_maybe_auto_research()` 钩子：

```python
def _maybe_auto_research(self, phase: int) -> None:
    if not self.config.research.enabled:
        return
    if not self.config.is_research_auto_run(phase):
        return
    spec_id = self.storage.get_current_spec_id()
    if not spec_id:
        return
    spec_data = self.storage.read_spec(spec_id)
    if not spec_data:
        return
    problem = (spec_data.get("problem") or "")[:100].strip()
    if not problem:
        return
    # 调 ResearchRunner.run() ...
```

**影响**：`devflow next` 从 brainstorm → plan 时**自动跑 research**，符合 SOP 配置语义。

---

## 🔧 SOP 配置扩展

```yaml
research:
  enabled: true
  auto_run_on: [plan_stage]
  sources: [github, pypi, npm, web]
  # ... 现有字段 ...
  cache:                              # ← v0.4.2 新增
    enabled: true
    ttl_seconds: 86400                 # 24h 默认
    shared_across_specs: true          # 跨 Spec 共享（v1 设计）
```

**默认值**：所有字段都有 default，旧 sop.yaml 无 `cache` 段自动走默认值。

---

## 🚀 升级指南

### 如果你已经在用 v0.4.0 / v0.4.1

**升级 = 直接拉新 commit**。无破坏性变更：

```bash
git pull origin feat/v0.4-research
pip install -e .  # 或无需操作
```

### 字段兼容性

| 字段 | v0.4.0/4.1 | v0.4.2 |
|---|---|---|
| `backends_used/failed/empty` | ✅ 保留 | ✅ 保留 |
| `sources_used/failed` (deprecated) | ✅ 保留 | ✅ 保留 |
| `cache_hit` | ❌ | ✅ 新增（`false`） |
| `cache_age_seconds` | ❌ | ✅ 新增（`0`） |
| `cache_key` | ❌ | ✅ 新增 |

`Spec.research_refs` 旧条目不动；新条目在缓存命中时新增 `cache_hit: true` 字段。

### .gitignore

确认 `docs/devflow/research/.cache/` 在 .gitignore 中（防止缓存被误提交）：

```gitignore
docs/devflow/specs/   # 已忽略
docs/devflow/plans/   # 已忽略
# docs/devflow/research/.cache/  # v0.4.2 自动从 .cache/ glob 排除
```

实际上 `.cache/` 目录只在 `docs/devflow/research/` 下生成，不会被 git 追踪（默认 .gitignore 排除了 `docs/devflow/`）。

---

## 📊 数据迁移

**无需迁移**。v0.4.2 完全向后兼容 v0.4.0/4.1。

---

## 🧪 测试变化

| 测试文件 | v0.4.0/4.1 | v0.4.2 | 变化 |
|---|---|---|---|
| `test_research_cache.py` | 0 | **19** | **+19**（新文件）|
| `test_research_runner.py` | 22 | **26** | +4（cache 集成测试）|
| `test_research_cli_integration.py` | 19 | **21** | +2（`--clear-cache` 测试）|
| **合计** | **41** | **66** | **+25** |

**全套**（含回归）：**215 passed + 1 skipped**（30s）

---

## 📚 文档更新

| 文件 | 变化 |
|---|---|
| `docs/release-notes-v0.4.2.md` | 本文件 |
| `docs/rfc-v0.4.2-research-cache.md` | RFC 草案（v0.4.2 实装后从"草案"升为"已落地"） |
| `docs/devflow-architecture-v0.1.md` §5.3 | 加缓存层说明 |
| `docs/CHANGELOG.md` | 加 v0.4.2 条目（待 PR 合并后） |
| `sop.yaml` / `config/sop.default.yaml` | 加 `research.cache` 段 |
| `README.md` | `### Research` 段加"24h 缓存"+ `--clear-cache` 用法（待更新） |

---

## 🔍 如何验证

```bash
# 1. 拉最新代码
git pull origin feat/v0.4-research

# 2. 在临时目录跑 demo
mkdir demo && cd demo
python -m devflow.cli init
python -m devflow.cli start "python retry library"
python -m devflow.cli research "python retry library"  # 首次: 5-10s, cache_hit=false

# 3. 立即再跑同 query
python -m devflow.cli research "python retry library"  # < 0.5s, cache_hit=true

# 4. 看 cache 文件
ls -la docs/devflow/research/.cache/
cat docs/devflow/research/.cache/*.json | head -20

# 5. 清缓存
python -m devflow.cli research --clear-cache
```

---

## 📦 完整 Commit 清单

```
27f8d71 feat(research): v0.4.2 24h 同 query 缓存 (RFC §5.3 Tier2 #12 续)
                  ← 本次: 10 文件 +777 行
[之前: v0.4.0 + v0.4.1 + 文档 + reviewer 工具]
```

---

## ⚠️ 已知问题（不在 v0.4.2 修复范围）

| 问题 | 优先级 | 影响 | 计划 |
|---|---|---|---|
| `AgentReachBackend.health_check()` 乐观探测 | 低 | 浪费线程 | v0.4.3+ |
| research 报告不含 `summary`（仅 title + snippet）| 低 | v0.4.3 自动喂 plan 时 summary 为空 | v0.4.3 |
| cache 命中率统计（哪些 query 命中最多）| 低 | 无观察性数据 | v0.5+ |

---

## 🎬 下一步

- **用户**：升级到 v0.4.2，享受 24h 缓存
- **reviewer**：v0.4.2 已 commit 到 `feat/v0.4-research` 分支，可同批评审
- **维护者**：v0.4.3 自动喂 plan 可接着实施（RFC 已就绪）

---

**Refs**：
- RFC 草案：[docs/rfc-v0.4.2-research-cache.md](./rfc-v0.4.2-research-cache.md)
- v0.4.1 release notes：[docs/release-notes-v0.4.1.md](./release-notes-v0.4.1.md)
- v0.4.0 release notes：（v0.4.1 已包含）
- CHANGELOG：[docs/CHANGELOG.md](./CHANGELOG.md)

**v0.4.2 · 2026-08-21 · 准备就绪**