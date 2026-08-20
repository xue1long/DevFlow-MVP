# v0.4.0: 引文式调研子能力 (research)

> **TL;DR**: plan 阶段能产出**带引用**的调研报告,辅助"不重复造轮子"决策。
> 22 文件 / +4036 行 / 156 测试通过 + 1 跳过。
> 完整版描述见 [PR_DESCRIPTION_V0.4_RESEARCH.md](./PR_DESCRIPTION_V0.4_RESEARCH.md)。

---

## 🎯 目标

DevFlow 在 plan 阶段能产出**带引用**的调研报告,辅助"不重复造轮子"决策——回答"我想做的东西是否已有成熟方案"。

## 🏗️ 架构

```
cli.py (research / plan --with-research / start advisory)
   ↓
state_machine.py (start advisory echo)
engine/research_runner.py (并发 + 去重 + 截断 + 落盘)
   ↓
adapters/research/  (4 backend + 选择器)
   ├ AgentReachBackend  复用宿主 agent-reach skill (主路径)
   ├ GitHubSearchBackend (兜底 1)
   ├ RegistryQueryBackend (兜底 2: PyPI/npm/crates)
   └ WebSearchBackend    (兜底 3: DuckDuckGo)
   ↓
model/research.py (Citation / Report / to_markdown)
```

## ✨ 主要功能

### 1. 显式调研

```bash
devflow research "python retry library" --sources github,pypi --max-results 10
```

### 2. plan 阶段自动调研

```bash
devflow plan --with-research
# 或 SOP 配 auto_run_on=[plan_stage] (推荐)
```

### 3. start 阶段 advisory 提示

```bash
devflow start "implement retry from scratch"
# [ADVISORY] 检测到 draft 含触发词: ['from scratch']
# (仅 stderr echo,不自动执行,不消耗 API 额度)
```

### 4. SOP 可关停 + 离线不阻断

```yaml
research:
  enabled: true
  auto_run_on: [plan_stage]
  fallback: skip  # 全 backend 失败时跳过,不阻断流程
```

## 🔑 关键纪律

- **不重复造 agent-reach 轮子**:主路径复用宿主平台已加载 skill
- **DevFlow 内置仅做兜底**:CI / 离线 / CLI 直调场景
- **适配层零业务逻辑**:仅外部 API → Citation 转换(§7 纪律)
- **离线不阻断**:`fallback=skip` 默认,CI 兼容
- **Spec 仅存路径引用**:避免交接时内容漂移(§5.4 handoff 引用策略)
- **append-only 账本**:`action=research`,与现有审计追溯字段一致
- **向后兼容**:旧 sop.yaml 无 research 段 → 走默认值

## 📊 数据模型

新增 `model/research.py`:

```python
SourceType:    GITHUB / PYPI / NPM / CRATES / WEB / OFFICIAL_DOCS
TrustLevel:    HIGH / MEDIUM / LOW / UNKNOWN
Citation:      url + title + snippet + source_type + trust_level + metadata
ResearchReport: spec_id + query + citations + sources_used + backend_chain + to_markdown()
```

模型扩展:
- `model/ledger.py`: `LedgerAction.RESEARCH = "research"`
- `model/spec.py`: `research_refs: list[dict]`(路径引用)

## 🧪 测试 (156 passed + 1 skipped, 18s)

| 测试文件 | 数量 | 覆盖 |
|---|---|---|
| `test_research_model.py` | 23 | 序列化 + Markdown + 字段边界 |
| `test_research_config.py` | 16 | SOP 解析 + 默认值 + 边界 |
| `test_research_backends.py` | 43 | 4 backend mock HTTP + 选择器 |
| `test_research_runner.py` | 19 | 并发 + 去重 + 截断 + 失败兜底 |
| `test_research_cli_integration.py` | 18 | Typer CliRunner + advisory |

**回归**(无破坏):state_machine 19/19、p0_fixes 12/12、p2_fixes 7/7。

## 🔍 端到端 demo

```bash
$ devflow init
$ devflow start "implement retry from scratch"
[ADVISORY] 检测到 draft 含触发词: ['from scratch']

$ devflow research "python retry library"
{
  "ok": true,
  "report_path": "docs/devflow/research/20260821-...-153012.md",
  "citations_count": 8,
  "sources_used": ["github", "pypi"]
}
```

离线环境(无网络):
```json
{
  "ok": true,    ← 不阻断流程
  "citations_count": 0,
  "sources_failed": ["web"],
  "fallback_used": true,
  "message": "调研完成,0 条引用 (全部 backend 失败,fallback=skip)"
}
```

## 📚 文档

- `README.md`: CLI 命令表 + 阶段对照 + 核心概念 `### Research` 段
- `docs/devflow-architecture-v0.1.md`:
  - §5.3 status: 规划 → **已落地**
  - §6.1 工具清单:加 `devflow.research(...)`
  - §15.3 表格 #12: status → **已落地(v0.4)**

## 🔗 关联

- 架构 §5.3 Tier2 #12 research(规划)
- v0.3.4 账本 schema(`spec_id` / `actor` / `session_id`)→ research 复用同模式
- v0.3.3 思维模型字段 → research summary 可在 brainstorm 阶段补充

## 🔮 v0.5+ 后续(本 PR 不含)

- LLM 自动生成 research summary
- 调研缓存(同 query 24h 内复用)
- `devflow audit` 检查 plan.task 是否用了调研中提到的库

---

**Refs**: 架构 §5.3 Tier2 #12 research
**Branch**: `feat/v0.4-research`
**Test**: `pytest tests/test_research_*.py -v` → 156 passed + 1 skipped