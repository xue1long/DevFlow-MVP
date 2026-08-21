# Reviewer Checklist — feat/v0.4-research

> 给 reviewer 的**快速判断清单**。不需要按顺序逐条审，**只关心 P0/P1 项**即可。

---

## 📋 提交概览

| 项 | 值 |
|---|---|
| **分支** | `feat/v0.4-research` |
| **Commits** | 10（含 v0.4.0 主功能 + v0.4.1 修复 + 2 个 RFC 草案） |
| **代码变更** | +5262 行（不含 RFC 文档） |
| **测试** | 190 passed + 1 skipped |
| **mypy** | 0 errors（仅 research 新文件） |
| **PR 描述** | [PR_DESCRIPTION_SHORT.md](./PR_DESCRIPTION_SHORT.md)（90 行） |
| **完整 RFC** | [PR_DESCRIPTION_V0.4_RESEARCH.md](./PR_DESCRIPTION_V0.4_RESEARCH.md) |
| **Release notes** | [docs/release-notes-v0.4.1.md](./docs/release-notes-v0.4.1.md) |
| **诊断报告** | [docs/post-v0.4-research-diagnosis.md](./docs/post-v0.4-research-diagnosis.md) |

---

## ⏱️ 5 分钟快速判断（**最关键**）

只需要回答这3 个问题：

- [ ] **Q1**: `devflow research` 子能力是否**符合 DevFlow 纪律**？（§纪律约束）
- [ ] **Q2**: v0.4.1 修复的 3 个 bug 是否**足够稳健**？
- [ ] **Q3**: 是否**认可** RFC v0.4.2 / v0.4.3 的方向？

如果 3 个 Q 都是"是" → 整体 LGTM。
如果任一是"否" → 看下面详细分类。

---

## 🔴 P0（必审 · 阻塞 merge）

### P0-1: SOP 兼容性

**问题**：旧 sop.yaml 无 `research:` 段时，是否能正常加载？

- [ ] 查看 `policy/loader.py::SOPConfig` 是否有 `research: ResearchConfig = Field(default_factory=ResearchConfig)`
- [ ] 查看 `tests/test_research_config.py::TestResearchConfigParsing::test_no_research_segment_uses_defaults` 是否通过
- [ ] 验证：手动 `rm research:` 段跑 `devflow init` → `devflow start` → `devflow research`，不应崩

### P0-2: 字段向后兼容

**问题**：v0.4.1 保留的 `sources_used` / `sources_failed` deprecated 字段是否仍可用？

- [ ] 查看 `run()` 返回 dict 含 `sources_used` / `sources_failed`（即便 deprecated）
- [ ] `tests/test_research_runner.py::test_backend_exception_caught` 是否同时断言新老字段

### P0-3: Spec 文件安全

**问题**：race condition 下 `_update_spec` 写回失败时，是否会丢数据？

- [ ] 查看 `engine/research_runner.py::_update_spec` 是否有 try-except 兜底
- [ ] 验证：模拟 `storage.write_spec` 抛异常 → Spec 原数据不被破坏（落盘报告仍存在）

### P0-4: 账本完整性

**问题**：`append_ledger` 失败时是否阻断流程？

- [ ] 查看 `_append_ledger` 是否有 try-except
- [ ] 验证：模拟 `append_ledger` 抛异常 → research 仍返回 ok=True

---

## 🟡 P1（应审 · 不阻塞但建议）

### P1-1: 真实环境诊断的真实性

**问题**：`scripts/diagnose_research.py` 暴露的 bug 是否在测试中也有覆盖？

- [ ] `tests/test_research_runner.py::TestFailurePaths::test_empty_result_distinct_from_failed`
- [ ] `tests/test_research_runner.py::TestFailurePaths::test_sources_in_results_extracted_from_citations`
- [ ] 这两个测试**锁定了诊断暴露的边界**

### P1-2: 适配层纪律

**问题**：4 个 backend 是否真的"零业务逻辑"（§7 纪律）？

- [ ] `adapters/research/base.py::ResearchBackend.search` 是否只返回 Citation，不做合并/去重
- [ ] `web_search.py` / `github_search.py` / `registry_query.py` / `agent_reach.py` 是否都遵循同一抽象

### P1-3: CLI `--spec-id` 不存在行为

**问题**：v0.4.1 加的 spec_id 校验是否影响其他命令？

- [ ] `tests/test_research_cli_integration.py::test_research_spec_id_not_found` 通过
- [ ] 验证：`devflow plan --with-research` 在无 spec 时静默跳过的逻辑仍正确（`cli.py:482-494`）

### P1-4: 缓存 RFC（v0.4.2）的关键决策

**问题**：跨 Spec 共享（key 不含 spec_id）是否合理？

- [ ] 阅读 [docs/rfc-v0.4.2-research-cache.md](./docs/rfc-v0.4.2-research-cache.md) §2
- [ ] 决策：是否改成"每 Spec 独立"？

### P1-5: 自动喂 RFC（v0.4.3）的关键决策

**问题**：**不调 LLM**、仅结构化提取，是否值得做？

- [ ] 阅读 [docs/rfc-v0.4.3-auto-fill-goals.md](./docs/rfc-v0.4.3-auto-fill-goals.md) §1
- [ ] 决策：v0.4.3 该不该做？优先级比 v0.4.2 高还是低？

---

## 🟢 P2（可选 · 锦上添花）

### P2-1: 文档完整性

- [ ] `README.md` 头部版本号正确（v0.4.1）
- [ ] `docs/CHANGELOG.md` v0.4.0 条目是否清晰
- [ ] `docs/release-notes-v0.4.1.md` 用户视角是否友好

### P2-2: CLI 错误信息可读性

- [ ] 中文错误信息（如"未指定 spec_id 且无活跃 Spec,请先 devflow start"）是否明确

### P2-3: 文档格式

- [ ] `PR_DESCRIPTION_SHORT.md` 是否能直接复制到 GitHub PR 框
- [ ] `docs/release-notes-v0.4.1.md` 是否可作为 GitHub release 描述

---

## 🧪 测试覆盖检查清单

| 维度 | 应覆盖 | 实际 |
|---|---|---|
| 模型层 | 5 个 Pydantic 模型序列化 + 边界 | ✅ 23 个 test_research_model |
| SOP 层 | 加载 + 默认值 + 边界 + auto_run | ✅ 16 个 test_research_config |
| 适配层 | 4 backend + 选择器 + mock HTTP | ✅ 42 个 test_research_backends |
| 编排层 | 并发 + 去重 + 截断 + 失败兜底 + cache_hit | ✅ 22 个 test_research_runner |
| CLI | Typer CliRunner + advisory + plan --with-research | ✅ 19 个 test_research_cli_integration |
| 回归 | state_machine / p0 / p2 / v0.3.4 ledger | ✅ 38 个 |

**总计 160 测试**（不含 +v0.4.2/4.3 后续），覆盖关键路径。

---

## 📦 文件变更总览

```
src/devflow/
├── adapters/research/                       ← 新增 7 文件
│   ├── __init__.py
│   ├── base.py                              ← 抽象
│   ├── selector.py                          ← 选择器
│   ├── agent_reach.py                       ← 主路径
│   ├── github_search.py                     ← 兜底1
│   ├── registry_query.py                    ← 兜底2
│   └── web_search.py                        ← 兜底3
├── engine/
│   ├── research_runner.py                   ← 新增（编排）
│   └── state_machine.py                     ← +41 行（advisory）
├── model/
│   ├── research.py                          ← 新增（5 模型）
│   ├── ledger.py                            ← +1（RESEARCH action）
│   └── spec.py                              ← +9（research_refs）
├── cli.py                                   ← +134 行（research + plan --with-research）
├── policy/loader.py                         ← +50 行（ResearchConfig）

config/sop.default.yaml                      ← +16 行（research 段）

scripts/diagnose_research.py                 ← 新增（诊断工具）

tests/test_research_*.py                     ← 新增 5 文件（~1800 行测试）

docs/
├── post-v0.4-research-diagnosis.md          ← 新增（诊断报告）
├── release-notes-v0.4.1.md                  ← 新增
├── rfc-v0.4.2-research-cache.md             ← 新增（RFC草案）
└── rfc-v0.4.3-auto-fill-goals.md            ← 新增（RFC草案）

README.md                                    ← +37 行
docs/devflow-architecture-v0.1.md            ← +11 行
docs/CHANGELOG.md                            ← +32 行

PR_DESCRIPTION_SHORT.md                      ← 新增（90 行 PR 描述）
PR_DESCRIPTION_V0.4_RESEARCH.md             ← 新增（详细 PR 描述）
```

---

## ⚡ 推荐审阅顺序（节省时间）

如果你只有 30 分钟：
1. **5 分钟**：读 [PR_DESCRIPTION_SHORT.md](./PR_DESCRIPTION_SHORT.md)（90 行）
2. **5 分钟**：读 [docs/post-v0.4-research-diagnosis.md](./docs/post-v0.4-research-diagnosis.md)（看 v0.4.1 为何而修）
3. **5 分钟**：跑 `scripts/diagnose_research.py` 看真实环境输出
4. **10 分钟**：扫一眼 `engine/research_runner.py` 的 `_execute_backends` 逻辑（v0.4.1 修复核心）
5. **5 分钟**：决定 v0.4.2 / v0.4.3 RFC 草案是否值得开

如果你有 2 小时：
- 上面 + 完整跑测试 + 看 RFC 草案 + 看适配层 4 backend

---

## ❓ reviewer 在评论区可能问的问题（已预备答案）

| 问题 | 答案 |
|---|---|
| "为什么不用 LLM 生成 goals？" | [docs/rfc-v0.4.3-auto-fill-goals.md §1](./docs/rfc-v0.4.3-auto-fill-goals.md) - 纪律引擎定位，LLM 留 v0.5 |
| "为什么 research 子能力要做？" | [PR_DESCRIPTION_V0.4_RESEARCH.md §纪律](./PR_DESCRIPTION_V0.4_RESEARCH.md) - 不重复造 agent-reach 的轮子 |
| "为什么不缓存报告内容，只缓存 metadata？" | v0.4.2 §11 设计权衡 - 报告 markdown 是 cache 内容；改它会破坏 cache 一致性 |
| "为什么跨 Spec 共享 cache？" | v0.4.2 §2 + §11 - 简化 + 同 query 高概率结果一致 |
| "为什么不调 agent-reach 子进程默认？" | §7 纪律 - 优先复用宿主平台能力；DevFlow 内置仅兜底 |
| "v0.4.1 bugfix 是否足够？" | [docs/post-v0.4-research-diagnosis.md](./docs/post-v0.4-research-diagnosis.md) - 真实环境验证 + 三维度互斥 |
| "为什么不跑 mypy/ruff 配置？" | 项目无配置要求，pre-existing 5 个 mypy error 在 cli.py（与本次 PR 无关）|

---

## 🎯 reviewer 反馈分类模板

```markdown
## 整体评价
[LGTM / 需要修改 / 需要重大重构]

## P0 必改
- (如有)

## P1 建议改
- (如有)

## P2 锦上添花
- (如有)

## RFC 草案评价
- v0.4.2 (research 缓存): [认可 / 需要修改 / 不必做]
- v0.4.3 (自动喂 plan): [认可 / 需要修改 / 不必做]

## 其他
- (自由评论)
```

---

**准备时间**: 30 秒（看 PR 描述 + 这个 checklist）
**实质审阅时间**: 30 分钟 ~ 2 小时（取决于深度）

**感谢审阅 🙏**