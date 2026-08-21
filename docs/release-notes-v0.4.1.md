# DevFlow v0.4.1 Release Notes

> **发布日期**: 2026-08-21
> **类型**: Bugfix release（v0.4.0 引文式调研子能力的诊断与修复）
> **Commit 范围**: 8 commits (`feat/v0.4-research` 分支)
> **测试**: 190 passed + 1 skipped
> **重要程度**: ⭐⭐⭐（推荐升级）

---

## 🎯 这个版本修复了什么

v0.4.1 是 v0.4.0 的**bugfix 版本**，没有新增功能。所有改动都是**真实环境诊断后修复**的并发边界 bug + ruff/mypy 静态检查遗漏。

### 核心 bug 修复（3 个）

#### 1. `sources_used` 与 `sources_failed` 互相矛盾 ⭐⭐⭐⭐⭐

**问题**：

真实环境跑出 `devflow research` 后，CLI 返回的 JSON 里有：

```json
{
  "sources_used": ["web"],
  "sources_failed": ["web"]   ← 矛盾!
}
```

**根因**：

- `RegistryQueryBackend` 和 `WebSearchBackend` 都把 `source_type` 标为 `WEB`（因为 registry 覆盖 PyPI/npm/crates 三个源，单一 `source_type` 不够）
- 多个 backend 共享同一 `source_type`，成功/失败被合并到**同一维度**
- **空结果被误计入 failed**（health OK 但 query 无结果）

**影响**：

- 用户看到 `sources_failed: web` 误判该源真失败
- `Spec.research_refs[].sources` 字段写错（显示 `web`，实际是 `npm`）—— **审计数据污染**

**修复**：

把字段从 **source_type 维度**改为 **backend 名字维度**（与 `backend_chain` 一致）：

| 旧字段（保留向后兼容） | 新字段（权威） | 含义 |
|---|---|---|
| `sources_used` | `backends_used` | 实际产出引用的 backend |
| `sources_failed` | `backends_failed` | 异常 / 超时的 backend |
| (无) | `backends_empty` | 健康但 0 命中的 backend |
| (无) | `sources_in_results` | citations 中实际出现的 source_type 去重列表 |

新增 `backends_empty` 区分"异常失败"与"空结果"——后者不算失败。

**验证**：

```json
// 修复后
{
  "backends_used": ["registry"],
  "backends_failed": [],
  "backends_empty": ["agent_reach", "web"],
  "sources_in_results": ["npm"],   ← 真实来源,不再被污染
  "fallback_used": true
}
```

#### 2. `_safe_search` 不区分"返回空"与"异常失败" ⭐⭐⭐⭐

**问题**：

`_safe_search` 把所有异常吞成 `[]`，导致 backend 异常被误归为 `empty`（失去诊断信号）。

**修复**：

`_safe_search` 改为**重新抛出异常**，让 runner 的 `except Exception` 块捕获并归入 `backends_failed`。

#### 3. CLI `--spec-id` 不存在时静默失败 ⭐⭐⭐

**问题**：

`devflow research <q> --spec-id nonexistent-spec` 会**静默跑完**、落盘报告、但 Spec 不更新。用户得不到任何错误反馈。

**修复**：

CLI 加 `storage.read_spec(target_spec_id)` 校验，不存在则返回 `ok=False` +明确消息并 `exit 1`。

### 静态检查遗漏（3 个）

| 规则 | 问题 | 修复 |
|---|---|---|
| `DTZ005` | `datetime.now()` 没带 tz | 加 `timezone.utc` |
| `TRY004` | `RuntimeError` 用于类型错误 | 改 `TypeError`（契约违反） |
| `F841` | 未使用局部变量 | 移除 |

---

## 🚀 升级指南

### 如果你已经在用 v0.4.0

**升级 = 直接拉新 commit**。代码层面**没有破坏性变更**：

```bash
git pull origin feat/v0.4-research
pip install -e .  # 或无需操作
```

### 字段兼容性

v0.4.1 保留 v0.4.0 的 `sources_used` / `sources_failed` 字段（标 deprecated）：

- **老消费者**（如直接读 JSON 的脚本）：继续可用，但建议升级到新字段
- **新消费者**：读 `backends_used` / `backends_failed` / `backends_empty`

`Spec.research_refs` 旧条目**不动**；新条目自动含 `backends_used/failed/empty + sources_in_results` 字段。

### SOP 兼容性

无需改 `sop.yaml`。所有新增字段都有默认值。

---

## 📊 数据迁移（如有旧 Spec）

如果你有 v0.4.0 跑出来的旧 Spec，其 `research_refs` 字段还是旧格式（`sources` 而不是 `backends_*`）：

**不需要手动迁移**——下次跑 `devflow research` 会自动追加新格式条目。旧条目继续可读。

如需**对账**（旧条目补充 `backends_used` 等字段），可以写个小脚本（**未提供**，因为不是阻塞性问题）。

---

## 🧪 测试变化

| 测试文件 | v0.4.0 | v0.4.1 | 变化 |
|---|---|---|---|
| `test_research_runner.py` | 19 | **22** | +3（empty vs failed 区分 / sources_in_results 提取 / TypeError契约） |
| `test_research_cli_integration.py` | 18 | **19** | +1（CLI spec_id 不存在错误路径） |
| **合计** | **119** | **123** | **+4** |

全套（含回归）：**190 passed + 1 skipped**（20.29s）

---

## 📚 文档变化

| 文件 | 变化 |
|---|---|
| `docs/post-v0.4-research-diagnosis.md` | **新增**：真实环境诊断报告 + 修复对策（本次 bugfix 的根因记录）|
| `scripts/diagnose_research.py` | **新增**：5 节诊断脚本（下次类似问题可直接复用）|
| `docs/CHANGELOG.md` | 已更新 v0.4.0 research 条目 |

---

## 🔍 如何复现/验证 bug 已修

```bash
# 1. 拉最新代码
git pull origin feat/v0.4-research

# 2. 在临时目录跑 demo
mkdir demo && cd demo
python -m devflow.cli init
python -m devflow.cli start "implement retry from scratch"

# 3. 跑诊断脚本（自动 5 节检查）
python ../scripts/diagnose_research.py "python retry library" \
    --spec-id 20260821-implement-retry-from-scratch

# 4. 期望输出（修复后）
#   backends_used: ['registry']
#   backends_failed: []
#   backends_empty: ['agent_reach', 'web']
#   sources_in_results: ['npm']   ← 不再被污染为 web
#   PASS: 三个维度互斥
```

---

## 📦 完整 commit 清单

```
f2e8cbf fix(research): v0.4.1 补充修复 (DTZ005/TRY004 + CLI 显式 spec_id 校验)
0ef9f3c fix(research): sources_used/failed 矛盾 bug 修复 (v0.4.1)
6662720 docs(research): 真实环境诊断脚本 + 暴露 2 个 mock 看不到的 bug
739a928 docs(changelog): 记录 v0.4.0 research 子能力落地
7d7e1d0 fix(research): 修 ruff F401/F541 + 移除冗余 import + 精简 PR 描述
4aaeed0 docs: PR description for v0.4 research feature
2d646a9 v0.4.0: 引文式调研子能力 (research) ——不重复造轮子的纪律落地
```

---

## ⚠️ 已知问题（不在 v0.4.1 修复范围）

| 问题 | 优先级 | 影响 | 计划 |
|---|---|---|---|
| `AgentReachBackend.health_check()` 乐观探测（PATH中有 claude命令即返回 True，实际 agent-reach skill 不一定加载）| 低 | 浪费线程但不影响结果 | v0.4.2 |
| 同 query 24h 内无缓存，每次跑都调网络 | 低 | 浪费 API 额度 | v0.4.2 |

---

## 🎬 下一步

- **用户**：升级到 v0.4.1
- **reviewer**：在 PR 评审 [PR link]
- **维护者**：等 review 反馈后再决定 v0.4.2 是否值得做

---

**Refs**：
- 完整 RFC：见 PR description (`PR_DESCRIPTION_V0.4_RESEARCH.md`)
- 诊断报告：`docs/post-v0.4-research-diagnosis.md`
- CHANGELOG：`docs/CHANGELOG.md`

**v0.4.1 · 2026-08-21 · 准备就绪**