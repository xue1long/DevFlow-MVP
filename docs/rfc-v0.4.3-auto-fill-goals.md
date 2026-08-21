---
title: DevFlow RFC v0.4.3 — Research 自动喂 Plan
subtitle: 闭合 research → plan 回路，减少 Stage1 人工编辑
version: 0.1
date: 2026-08-21
status: draft
tags: [devflow, rfc, v0.4, research, plan]
related:
  - ./rfc-v0.4.2-research-cache.md
  - ../PR_DESCRIPTION_V0.4_RESEARCH.md
---

# RFC v0.4.3: Research 自动喂 Plan（闭合回路）

> **优先级**：⭐⭐⭐⭐
> **投入**：1.5-2 天
> **价值**：闭合 research → plan 回路，减少 Stage1 brainstorm 阶段的人工编辑工作量
> **依赖**：v0.4.2 缓存（可选）+ **零 LLM 依赖**
> **状态**：draft

---

## 0. 目标与非目标

### 0.1 目标

`devflow plan` 阶段跑完 research 后，**自动把调研报告的结构化信息提取为 `Spec.goals` 草稿**，减少用户在 Stage1 brainstorm 阶段的人工编辑工作量。

**示例**：

```bash
# 用户提需求
devflow start "为 pipeline 增加 batch 重试机制"

# 编辑 spec.yaml, 空 goals
goals: ["待补充"]

# plan 阶段自动跑 research + 自动生成 goals 草稿
devflow plan --task "..."

# 用户打开 spec.yaml 看到:
goals:
  - "集成 tenacity 库提供指数退避重试"
  - "实现自定义 retry 装饰器(支持参数化重试策略)"
  - "覆盖测试: 模拟失败 → 验证重试逻辑"
```

### 0.2 非目标

- ❌ 不做全自动 goals（用户必须 review 后再 `devflow approve`）
- ❌ 不做 goals 智能评分（v0.5+）
- ❌ 不做 plan.task 自动生成（task 由用户在 `devflow plan --task` 显式提供）
- ❌ 不依赖 LLM（v0.4.3 仅做**结构化提取**，不调 LLM）——见 §1 决策
- ❌ 不改 `non_goals`（用户应该明确不做什么，不应由工具猜测）

---

## 1. 关键设计决策：是否用 LLM？

### 选项 A：用 LLM 生成 goals（智能但有成本）

- ✅ goals 质量高（懂语义）
- ❌ 引入 LLM provider（Ollama / OpenAI / Claude）依赖
- ❌ 每次 plan 都花钱/花时间
- ❌ 不可预测性（同一 query 两次结果可能不同）

### 选项 B：结构化提取（不调 LLM）

- ✅ 零依赖、零成本、确定性
- ❌ goals 质量受限（基于规则）
- ✅ 不引入新的 Provider 决策成本

### 我的推荐：**选项 B（结构化提取）**

**理由**：

1. DevFlow 是**纪律引擎**，**不是**智能引擎——v0.4.3 应保持纪律性
2. LLM provider 选择是**大决策**（Ollama 本地 vs OpenAI API vs Claude API），值得 v0.5 单独 RFC
3. 结构化提取 + 用户 review **已足够 v0.4 价值**——LLM 增强留 v0.5
4. 与 §v0.4.2 缓存层**互不依赖**，可独立落地

**v0.4.3 落地**：结构化提取 + Markdown 模板，让用户在 Stage1 人工编辑。v0.5+ 加 LLM 增强。

---

## 2. 用户旅程

### 场景 A：plan 后自动填充 goals 草稿

```bash
# 1. 用户 start
$ devflow start "implement retry from scratch"
[ADVISORY] 检测到 draft 含 'from scratch'...

# 2. 用户编辑 spec.yaml 补 problem (≥10 字符)
# goals 暂时空: ["待补充"]

# 3. 用户 approve + next 到 plan
$ devflow approve <spec-id>
$ devflow next  # intake → brainstorm
$ devflow next  # brainstorm → plan
# 自动跑 research (sop.research.auto_run_on=[plan_stage])

# 4. research 完成后, 自动从报告中提取 goals 草稿
# 写入 spec.yaml 的 goals 字段 (替换 ["待补充"])
# 弹出 [INFO] 让用户知道 goals 已被自动填充
[INFO] 已自动填充 goals (3 个), 请 review 后 devflow approve
```

### 场景 B：goals 提取失败时回退

```bash
# research 报告无有效引用 / 提取失败
# → 不修改 spec.yaml 的 goals
# → 输出 [INFO] 提示用户手动编辑
[INFO] research 报告无有效引用, goals 保持原状
```

### 场景 C：用户禁用自动填充

```bash
# SOP 配置:
research:
  auto_fill_goals:
    enabled: false   # 默认 true

# 或 CLI 标志:
devflow plan --no-auto-fill-goals
```

### 场景 D：用户已填 goals → 不覆盖

```bash
# 用户 Stage1 已编辑 goals:
goals:
  - "实现指数退避重试"
  - "覆盖 5xx 错误重试"

# plan 阶段 research 完成后:
# 默认配置下, 不覆盖用户已有内容 (overwrite_existing: false)
# 输出 [INFO]:
[INFO] 检测到 goals 已填充 (2 项), 跳过自动填充 (overwrite_existing: false)
```

---

## 3. 数据流

```
state_machine.next_phase()
 └ stage 2 (plan)
   ├ 触发 sop.research.auto_run_on=[plan_stage]
   ├ 调 ResearchRunner.run() → 报告 Markdown
   ├ (新增) GoalsExtractor.extract(report) → list[str]
   ├ (新增) SpecAutoFiller.fill_goals_if_empty(spec_id, goals) → 写 spec.yaml
   ├ 写账本 action=research + details 含 auto_filled_goals=N
   └ 推进到 stage 3 (contract)
```

---

## 4. 设计：`engine/goals_extractor.py`

### 4.1 提取策略（结构化，零 LLM）

从 `ResearchReport.citations` 提取 goals 候选：

1. **库名提取**：从 URL/标题解析 PyPI/npm 包名（已是注册中心源）
   - `https://www.npmjs.com/package/axios` → "评估 axios 包"
2. **GitHub 仓库名**：从 full_name 提取
   - `sindresorhus/got` → "参考 sindresorhus/got 项目 (stars=12000)"
3. **SourceType 分类**：每个 SourceType 对应一个 goal 模板
4. **去重 + 排序**：同名包去重，按 `trust_level` 排序

```python
"""GoalsExtractor — 从 ResearchReport 提取 goals 草稿 (v0.4.3 RFC §4)"""
from __future__ import annotations

import re
from typing import Optional

from ..model.research import (
    Citation,
    ResearchReport,
    SourceType,
    TrustLevel,
)


class GoalsExtractor:
    """结构化提取, 不依赖 LLM"""

    # SourceType → goal 模板
    TEMPLATES = {
        SourceType.PYPI: "集成 {name} 库({summary})",
        SourceType.NPM: "评估 {name} 包",
        SourceType.CRATES: "参考 {name} crate",
        SourceType.GITHUB: "参考 {repo} 项目(stars={stars})",
        SourceType.WEB: "调研: {title}",
    }

    # 包名/仓库名提取 pattern
    NPM_PATTERN = re.compile(r"npmjs\.com/package/([^/]+)")
    PYPI_PATTERN = re.compile(r"pypi\.org/project/([^/]+)")
    CRATES_PATTERN = re.compile(r"crates\.io/crates/([^/]+)")
    GITHUB_PATTERN = re.compile(r"github\.com/([^/]+)/([^/]+)")

    def extract(
        self,
        report: ResearchReport,
        max_goals: int = 5,
    ) -> list[str]:
        """从 research 报告提取 goals 草稿"""
        goals: list[str] = []
        seen: set[str] = set()

        # 按 trust_level 降序 (HIGH > MEDIUM > LOW > UNKNOWN)
        sorted_citations = sorted(
            report.citations,
            key=lambda c: self._trust_rank(c.trust_level),
            reverse=True,
        )

        for citation in sorted_citations:
            goal = self._extract_from_citation(citation)
            if goal is None:
                continue
            # 去重 (基于 goal 主语)
            key = self._goal_key(goal)
            if key in seen:
                continue
            seen.add(key)
            goals.append(goal)
            if len(goals) >= max_goals:
                break

        return goals

    def _extract_from_citation(self, c: Citation) -> Optional[str]:
        """从单条 citation 提取一个 goal"""
        template = self.TEMPLATES.get(c.source_type)
        if template is None:
            return None

        # 按 source_type 走特定提取
        if c.source_type == SourceType.NPM:
            m = self.NPM_PATTERN.search(c.url)
            if m:
                name = m.group(1)
                return template.format(name=name, summary=c.snippet[:50])
        elif c.source_type == SourceType.PYPI:
            m = self.PYPI_PATTERN.search(c.url)
            if m:
                name = m.group(1)
                return template.format(name=name, summary=c.snippet[:50])
        elif c.source_type == SourceType.CRATES:
            m = self.CRATES_PATTERN.search(c.url)
            if m:
                name = m.group(1)
                return template.format(name=name)
        elif c.source_type == SourceType.GITHUB:
            m = self.GITHUB_PATTERN.search(c.url)
            if m:
                repo = f"{m.group(1)}/{m.group(2)}"
                stars = c.metadata.get("stars", "?")
                return template.format(repo=repo, stars=stars)

        # fallback: 用 title
        return template.format(title=c.title[:50])

    @staticmethod
    def _trust_rank(t: TrustLevel) -> int:
        return {
            TrustLevel.HIGH: 4,
            TrustLevel.MEDIUM: 3,
            TrustLevel.LOW: 2,
            TrustLevel.UNKNOWN: 1,
        }.get(t, 0)

    @staticmethod
    def _goal_key(goal: str) -> str:
        """goal 主语标准化(用于去重)"""
        # 提取 goal 第一个名词性短语
        return goal.split("(")[0].strip().lower()
```

### 4.2 输入输出示例

**输入**（`ResearchReport.citations`）：

```python
[
    Citation(url="https://www.npmjs.com/package/axios",
             title="axios", source_type=NPM, trust=HIGH,
             snippet="Promise based HTTP client"),
    Citation(url="https://www.npmjs.com/package/got",
             title="got", source_type=NPM, trust=HIGH),
    Citation(url="https://github.com/sindresorhus/got",
             title="sindresorhus/got", source_type=GITHUB,
             trust=HIGH, metadata={"stars": 12000}),
]
```

**输出**：

```python
[
    "参考 sindresorhus/got 项目(stars=12000)",  # GITHUB HIGH, trust_rank=4
    "评估 axios 包",                            # NPM HIGH
    "评估 got 包",                              # NPM HIGH
]
```

---

## 5. 设计：`engine/spec_auto_filler.py`

```python
"""SpecAutoFiller — 自动填充 Spec 字段 (v0.4.3 RFC §5)"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel

from ..model.spec import Spec
from ..storage.base import StorageBackend


class GoalsFillResult(BaseModel):
    """Goals 填充结果"""
    spec_id: str
    original_goals: list[str]
    filled_goals: list[str]
    changed: bool  # 是否真的改了 spec.yaml


class SpecAutoFiller:
    """自动填充 Spec 字段(目前仅 goals)"""

    def __init__(self, storage: StorageBackend):
        self.storage = storage

    def fill_goals_if_empty(
        self,
        spec_id: str,
        new_goals: list[str],
        overwrite: bool = False,
    ) -> Optional[GoalsFillResult]:
        """仅当原 goals 是占位时填充(避免覆盖用户已有内容)

        Args:
            overwrite: True 时总是覆盖(即便用户已有 goals)

        Returns:
            None: Spec 不存在或新 goals 为空
            GoalsFillResult: 已处理(changed 表示是否真的改了)
        """
        spec_data = self.storage.read_spec(spec_id)
        if spec_data is None:
            return None
        if not new_goals:
            return None

        try:
            spec = Spec(**spec_data)
        except Exception:
            return None

        original_goals = list(spec.goals)

        # 仅当原 goals 是占位("待补充") 或 overwrite=True 时才覆盖
        if overwrite or self._is_placeholder(spec.goals):
            spec.goals = new_goals
            self.storage.write_spec(
                spec_id, spec.model_dump(mode="json")
            )
            return GoalsFillResult(
                spec_id=spec_id,
                original_goals=original_goals,
                filled_goals=new_goals,
                changed=True,
            )

        return GoalsFillResult(
            spec_id=spec_id,
            original_goals=original_goals,
            filled_goals=original_goals,  # 不变
            changed=False,
        )

    @staticmethod
    def _is_placeholder(goals: list[str]) -> bool:
        """判断 goals 是否是占位"""
        if not goals:
            return True
        placeholders = {"待补充", "TBD", "TODO", "to be filled"}
        return all(g.strip() in placeholders for g in goals)
```

---

## 6. CLI 与 SOP 配置

### 6.1 SOP 配置

```yaml
research:
  enabled: true
  auto_run_on: [plan_stage]
  ...
  # v0.4.3 新增
  auto_fill_goals:
    enabled: true              # 总开关
    max_goals: 5               # 最多生成几个 goals
    overwrite_existing: false  # true=总是覆盖; false=仅占位时覆盖
```

### 6.2 `policy/loader.py::ResearchAutoFillGoalsConfig`

```python
class ResearchAutoFillGoalsConfig(BaseModel):
    enabled: bool = True
    max_goals: int = Field(default=5, ge=1, le=20)
    overwrite_existing: bool = False  # 默认仅覆盖占位


class ResearchConfig(BaseModel):
    ...
    auto_fill_goals: ResearchAutoFillGoalsConfig = Field(
        default_factory=ResearchAutoFillGoalsConfig
    )
```

### 6.3 `cli.py` 加 `--no-auto-fill-goals`

```python
@app.command()
def plan(
    tasks: list[str] = typer.Option([], "--task"),
    with_research: bool = typer.Option(False, "--with-research"),
    no_auto_fill_goals: bool = typer.Option(
        False, "--no-auto-fill-goals",
        help="即使 research 完成也不自动填充 goals",
    ),
):
    ...
    # 在 _run_research 之后:
    if not no_auto_fill_goals and config.auto_fill_goals.enabled:
        from .engine.goals_extractor import GoalsExtractor
        from .engine.spec_auto_filler import SpecAutoFiller
        extractor = GoalsExtractor()
        filler = SpecAutoFiller(storage)
        # 从 report 提取 goals
        goals = extractor.extract(report, max_goals=config.auto_fill_goals.max_goals)
        # 填充
        fill_result = filler.fill_goals_if_empty(
            spec_id,
            goals,
            overwrite=config.auto_fill_goals.overwrite_existing,
        )
        if fill_result and fill_result.changed:
            typer.echo(
                f"[INFO] 已自动填充 goals ({len(goals)} 个),"
                f"请 review 后 devflow approve",
                err=True,
            )
```

---

## 7. 集成点决策

**决策**：自动触发放在 `cli.py::plan` 而不是 `state_machine.py::next_phase`

**理由**：
- 避免引擎耦合 LLM/UI 关注点（state_machine 应保持纯逻辑）
- CLI 门面是合适的协调点
- 未来如果 MCP 接入，也只需在 MCP server 加同样协调

---

## 8. 测试矩阵

### 8.1 单元测试

| 测试 | 覆盖 |
|---|---|
| `test_extract_from_npm_url` | 从 npm URL 提取包名 |
| `test_extract_from_pypi_url` | 从 PyPI URL 提取包名 |
| `test_extract_from_github_url` | 从 GitHub URL 提取仓库名 + stars |
| `test_extract_dedup_by_goal_key` | 同名包去重 |
| `test_extract_sort_by_trust` | 按 trust_level 排序 |
| `test_extract_max_goals_limit` | max_goals 限制 |
| `test_extract_empty_citations` | 无引用 → [] |
| `test_filler_overwrites_placeholder` | 占位被覆盖 |
| `test_filler_preserves_user_goals` | 用户已填 → 不覆盖（默认） |
| `test_filler_overwrites_when_config_true` | 配置 overwrite=true 时强制覆盖 |
| `test_filler_handles_missing_spec` | Spec 不存在 → None |

### 8.2 集成测试（CLI）

| 测试 | 覆盖 |
|---|---|
| `test_plan_auto_fills_goals_with_research` | plan → research → goals 自动填充 |
| `test_plan_no_fill_when_no_research` | 无 research → 不填充 |
| `test_plan_no_fill_when_disabled` | SOP 关闭 → 不填充 |
| `test_plan_cli_flag_overrides` | `--no-auto-fill-goals` 禁用 |

### 8.3 真实环境验证

```bash
devflow init
devflow start "为 pipeline 增加 batch 重试机制"
# 编辑 spec.yaml, goals: ["待补充"]
devflow approve ...
devflow next  # → brainstorm
devflow next  # → plan (自动跑 research + 提取 goals)

# 验证 spec.yaml:
# goals:
#   - "集成 tenacity 库(Retry library...)"
#   - "评估 promise-retry 包"
#   - ...
```

---

## 9. 风险与缓解

| 风险 | 等级 | 缓解 |
|---|---|---|
| LLM 提供商决策被绕开 | 中 | §1 已选**不调 LLM**，留 v0.5 单独 RFC |
| 提取的 goals 质量差 | 中 | **仅覆盖占位**（默认），用户已有内容不破坏；Stage1 用户必 review |
| 仓库名提取出错（fork / mirror）| 低 | regex 严格匹配 `github.com/{owner}/{repo}` |
| 同名包混淆（如 npm 的 `axios` vs PyPI 的 `axios`）| 低 | v0.4.3 简化：仅按名字去重；v0.5+ 加 source_type 前缀 |
| plan 阶段同时跑 research + 提取 goals, 耗时增加 | 低 | research 5-10s + 提取 < 100ms, 总时间 < 11s |
| 用户工作流变更（Stage1 不再需要编辑 goals）| 中 | 文档 + `### Research` 段明确"**请 review**"，且 Stage1 仍可编辑 |

---

## 10. 设计权衡（Why）

| 决策 | 理由 |
|---|---|
| **不调 LLM** | v0.4.3 保持纪律引擎定位，LLM 是 v0.5 单独 RFC |
| **仅覆盖占位** | 不破坏用户已有内容，最小侵入式 |
| **结构化提取** | 确定性 + 可测试 + 零成本 |
| **trust_level 排序** | 高信任源排前，避免被低质量源主导 |
| **去重按 goal 主语** | 同名包不重复出现 |
| **cli flag `--no-auto-fill-goals`** | 用户可临时禁用，灵活 |
| **stage 2 触发而不是 stage 3** | plan 阶段已经有 research 上下文，复用 |

---

## 11. 文档更新

- `README.md`: `### Research` 段加"自动 goals 草稿"
- `docs/release-notes-v0.4.3.md`: 新 release notes
- `docs/devflow-architecture-v0.1.md` §5.3: 加 auto_fill_goals 说明
- `docs/CHANGELOG.md`: 加 v0.4.3 条目

---

## 12. 落地任务 DAG（1.5-2 天）

```
T1 (0.5 天): policy/loader.py 加 ResearchAutoFillGoalsConfig
T2 (0.5 天): engine/goals_extractor.py + engine/spec_auto_filler.py + 单测
T3 (0.5 天): cli.py plan 集成 (自动填充 + stderr echo) + 集成测
T4 (0.5 天): 文档 + CHANGELOG + release notes
```

---

## 13. 与 v0.4.2 的关系

| 维度 | v0.4.2 缓存 | v0.4.3 自动喂 |
|---|---|---|
| 触发点 | research 完成后 | plan 阶段 (research 之后) |
| 依赖关系 | 无 | 可选依赖 v0.4.2 (有缓存更快) |
| 共同纪律 | 都从 `ResearchReport` 派生信息 | 都保持零 LLM 依赖 |
| 用户价值 | 降成本 | 减编辑 |

**落地顺序**：v0.4.2 先（基础）→ v0.4.3 后（应用）。可独立落地。

---

**RFC v0.4.3 · 2026-08-21 · draft · 等待评审**