# v0.4.0 + v0.4.1: 引文式调研子能力 (research) — 不重复造轮子的纪律落地

> 实现 RFC §5.3 Tier2 #12 research 子能力,辅助需求草稿 + plan 阶段决策。
> 24 文件 / 4289 行新增 / 11 行删除 / 190 测试通过 + 1 跳过。
> **v0.4.1** 在 v0.4.0 基础上修复了真实环境诊断暴露的 3 个并发边界 bug。
> 详见 [docs/post-v0.4-research-diagnosis.md](./docs/post-v0.4-research-diagnosis.md) 与 [docs/release-notes-v0.4.1.md](./docs/release-notes-v0.4.1.md)。

---

## 🎯 目标

让 DevFlow 在 plan 阶段能产出**带引用**的调研报告,辅助"不重复造轮子"决策。

## 🏗️ 架构

```
┌────────────────────────────────────────────────────────┐
│ cli.py (门面) │
│ devflow research / devflow plan --with-research │
│ devflow start (advisory echo) │
└─────────┬──────────────────────────────────────────────┘
 │
 ▼
┌──────────────────────┐ ┌──────────────────────────────┐
│ state_machine.py │ │ engine/research_runner.py │
│ start() advisory │ │ 编排:并发 + 去重 + 截断 + 落盘 │
└──────────────────────┘ └──────────┬───────────────────┘
 │
 ▼
┌────────────────────────────────────────────────────────┐
│ adapters/research/ (适配层, §7 零业务逻辑纪律) │
│ │
│ AgentReachBackend (主路径, 复用宿主 agent-reach skill) │
│ GitHubSearchBackend (兜底 1) │
│ RegistryQueryBackend (兜底 2: PyPI/npm/crates) │
│ WebSearchBackend (兜底 3: DuckDuckGo) │
│ │
│ select_backends: 优先级 + sources 过滤 + health_check │
└────────────────────────────────────────────────────────┘
 │
 ▼
┌────────────────────────────────────────────────────────┐
│ model/research.py │
│ Citation / ResearchQuery / ResearchReport │
│ + to_markdown() 生成带引用格式 │
└────────────────────────────────────────────────────────┘
```

## ✨ 主要功能

### 1. 显式调研: `devflow research`

```bash
devflow research "python retry library" --sources github,pypi --max-results 10
```

- 产物: `docs/devflow/research/<spec-id>-<timestamp>.md`
- Spec 增量更新: `spec.research_refs` 追加一条
- 账本: `action=research, phase=2`

### 2. plan 阶段自动调研

```bash
devflow plan --with-research
# 或 SOP 配 auto_run_on=[plan_stage] (推荐隐式)
```

### 3. start 阶段 advisory 提示

```bash
devflow start "implement retry from scratch"
# [ADVISORY] 检测到 draft 含触发词: ['from scratch']
# 建议在 plan 阶段执行调研,验证是否已有成熟方案:
#   devflow research "implement retry from scratch" --sources github,pypi
```

- 仅 stderr echo,**不自动执行**(避免消耗 API 额度)
- 触发词通过 `sop.yaml.research.start_keywords` 配置

### 4. SOP 可关停 + 离线不阻断

```yaml
research:
 enabled: true  # 总开关
 auto_run_on: [plan_stage]
 fallback: skip  # 全 backend 失败时跳过,不阻断流程
```

## 🔑 关键设计纪律

| 纪律 | 落地 |
|---|---|
| **不重复造 agent-reach 轮子** | 主路径复用宿主平台已加载 skill |
| **DevFlow 内置仅做兜底** | 4 backend 覆盖 CI / 离线 / CLI 直调场景 |
| **适配层零业务逻辑** | 仅外部 API → Citation 转换;并发/去重/截断由 engine 负责 |
| **离线不阻断** | `fallback=skip` 默认;CI 兼容 |
| **Spec 仅存路径引用** | 避免交接时内容漂移(与 §5.4 handoff 引用策略一致) |
| **append-only 账本** | `action=research` 与现有审计追溯字段一致 |
| **SOP 可关停** | `research.enabled=false` 一键禁用 |
| **向后兼容** | 旧 sop.yaml 无 research 段 → 走默认值 |

## 📊 数据模型

新增 `model/research.py`:

```python
class SourceType(str, Enum):
 GITHUB / PYPI / NPM / CRATES / WEB / OFFICIAL_DOCS

class TrustLevel(str, Enum):
 HIGH / MEDIUM / LOW / UNKNOWN

class Citation(BaseModel):
 url: str (min_length=1)
 title: str (max_length=200)
 snippet: str (max_length=500)
 source_type: SourceType
 trust_level: TrustLevel
 retrieved_at: datetime
 metadata: dict

class ResearchReport(BaseModel):
 spec_id, query, citations, summary
 sources_used, sources_failed, fallback_used
 total_chars, backend_chain, generated_at
 # to_markdown() 生成带引用格式
```

模型扩展:
- `model/ledger.py`: `LedgerAction.RESEARCH = "research"`
- `model/spec.py`: `research_refs: list[dict]`(路径引用)

## 🧪 测试 (156 passed + 1 skipped, 18s)

| 测试文件 | 数量 | 覆盖 |
|---|---|---|
| `test_research_model.py` | 23 | Citation/Report 序列化 + Markdown + 字段边界 |
| `test_research_config.py` | 16 | SOP 解析 + 默认值 + 边界 + auto_run 判定 |
| `test_research_backends.py` | 43 | 4 backend mock HTTP + 选择器优先级 + health_check |
| `test_research_runner.py` | 19 | 并发 + 去重 + 截断 + 失败兜底 + Spec 更新 |
| `test_research_cli_integration.py` | 18 | Typer CliRunner + plan --with-research + advisory |

**回归测试** (无破坏):
- `test_state_machine.py`: 19/19 ✅
- `test_p0_fixes.py`: 12/12 ✅
- `test_p2_fixes.py`: 7/7 ✅

## 📝 SOP 配置示例

```yaml
# sop.yaml
research:
 enabled: true
 auto_run_on: [plan_stage] # plan 阶段自动跑
 sources: [github, pypi, npm, web]
 max_results_per_source: 5
 max_total_chars: 8000
 timeout_per_source: 10
 fallback: skip # 全 backend 失败时跳过
 citation_required: true
 start_keywords:
 - "from scratch"
 - "重新实现"
 - "重写"
 - "造轮子"
 - "自己写一个"
```

## 🔍 真实端到端 demo

```bash
$ devflow init
$ devflow start "implement retry from scratch"
[ADVISORY] 检测到 draft 含触发词: ['from scratch']
建议在 plan 阶段执行调研...

$ devflow research "python retry library"
{
 "ok": true,
 "report_path": "docs/devflow/research/20260821-...-153012.md",
 "citations_count": 8,
 "sources_used": ["github", "pypi"],
 "sources_failed": [],
 "fallback_used": false,
 "message": "调研完成,8 条引用"
}
```

离线环境表现(无网络):
```json
{
 "ok": true, # 不阻断流程
 "citations_count": 0,
 "sources_failed": ["web"],
 "fallback_used": true,
 "message": "调研完成,0 条引用 (fallback 已触发) (全部 backend 失败,fallback=skip)"
}
```

## 📚 文档更新

- `README.md`: CLI 命令表 + 阶段对照 + 核心概念 `### Research` 段
- `docs/devflow-architecture-v0.1.md`:
  - §5.3 status: 规划 → **已落地**
  - §6.1 工具清单: 加 `devflow.research(query, sources, spec_id)`
  - §15.3 表格 #12: status → **已落地(v0.4)**

## 🔮 v0.5+ 后续可做(本 PR 不含)

- LLM 自动生成 research summary
- 调研缓存(同 query 24h 内复用)
- `devflow audit` 检查 plan.task 是否用了调研中提到的库
- 多语言 registry(maven/nuget)

## 🔗 关联

- 架构 §5.3 Tier2 #12 research(规划)
- v0.3.4 账本 schema 扩展(`spec_id` / `actor` / `session_id`)→ research 复用同模式
- v0.3.3 思维模型字段(`assumptions` / `premortem` / `tradeoff`)→ research summary 可在 brainstorm 阶段补充

---

**Refs**: 架构 §5.3 Tier2 #12 research
**Commit**: feat/v0.4-research
**Test**: `pytest tests/test_research_*.py -v` → 156 passed + 1 skipped