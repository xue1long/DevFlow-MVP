# DevFlow v0.4.3 Release Notes

> **发布日期**: 2026-08-21
> **类型**: Minor feature release（research 闭环 — 自动喂 plan）
> **基于**: v0.4.0 / v0.4.1 / v0.4.2
> **测试**: 235 passed + 1 skipped（38s 全套）
> **重要程度**: ⭐⭐⭐⭐（推荐升级，**减少 Stage1 人工编辑**）

---

## 🎯 这个版本做了什么

v0.4.3 在 v0.4.0/4.1/4.2 引文式调研基础上：

**plan 阶段跑完 research 后，自动从报告提取 goals 草稿填充到 `Spec.goals`**，减少 Stage1 brainstorm 的人工编辑工作量。

### 用户旅程

```bash
# 用户提需求
devflow start "implement retry from scratch"
# 编辑 spec.yaml, goals: ["待补充"]  (占位)

# approve + next 到 plan 阶段
devflow approve <spec-id>
devflow next  # → brainstorm
devflow next  # → plan (v0.4.2 修复:自动跑 research)

# v0.4.3: research 报告生成后,自动提取 goals 草稿
# [INFO] 已自动填充 goals (3 个), 请 review 后 devflow approve

# 用户打开 spec.yaml 看到:
goals:
  - "参考 sindresorhus/got 项目(stars=12000)"
  - "评估 axios 包"
  - "调研: How to design API"

# 用户 review 后 approve (或继续 Stage1 手动修改)
```

---

## 🆕 核心功能

### 1. 结构化提取（零 LLM 依赖）

```python
# engine/goals_extractor.py
class GoalsExtractor:
    # SourceType -> goal 模板
    TEMPLATES = {
        PYPI: "集成 {name} 库({summary})",
        NPM: "评估 {name} 包({summary})",
        CRATES: "参考 {name} crate({summary})",
        GITHUB: "参考 {repo} 项目(stars={stars})",
        WEB: "调研: {title}",
    }
```

**纪律**：

- ✅ **不调 LLM** —— DevFlow 是纪律引擎，不是智能引擎
- ✅ **零依赖** —— 纯 Python 标准库 `re`
- ✅ **确定性** —— 同样输入永远同样输出（LLM 不保证）
- ✅ **可测试** —— 19 个单测覆盖所有 SourceType + 边界

### 2. 关键纪律：仅覆盖占位

```python
# engine/spec_auto_filler.py
def fill_goals_if_empty(self, spec_id, new_goals, overwrite=False):
    if overwrite or self._is_placeholder(spec.goals):
        # 覆盖
    else:
        # 用户已有内容 → 不动
```

**默认行为**（`overwrite_existing: false`）：
- 用户写了具体 goals（如"实现指数退避重试"）→ **不覆盖**（保护用户内容）
- 用户留占位（`["待补充"]` / `["TBD"]`）→ **自动填充**

**配置强制覆盖**（`overwrite_existing: true`）：
- 总是用提取的 goals 替换
- 适合 CI / 严格模式

### 4 种占位符识别

`["待补充", "TBD", "TODO", "to be filled"]` + 空字符串兜底

---

## 📊 提取策略

| SourceType | 提取方式 | Goal 模板示例 |
|---|---|---|
| **PyPI** | URL regex `pypi.org/project/(?P<name>)` | "集成 tenacity 库(Retry library)" |
| **npm** | URL regex `npmjs.com/package/(?P<name>)` | "评估 axios 包(Promise HTTP client)" |
| **crates.io** | URL regex `crates.io/crates/(?P<name>)` | "参考 tokio crate" |
| **GitHub** | URL regex `github.com/(?P<owner>)/(?P<repo>)` + metadata | "参考 sindresorhus/got 项目(stars=12000)" |
| **Web** | fallback to title | "调研: How to design API" |

### 排序与去重

- **按 trust_level 降序**：HIGH → MEDIUM → LOW → UNKNOWN
- **去重按 goal 主语**：`(前的部分转小写`
- **max_goals 限制**：默认 5（防撑爆）

---

## 🔧 SOP 配置

```yaml
research:
  # ... 现有字段 ...
  # v0.4.3 新增
  auto_fill_goals:
    enabled: true              # 总开关
    max_goals: 5               # 最多生成几个 goals
    overwrite_existing: false  # false=仅占位时覆盖(默认)
                              # true=总是覆盖
```

**默认值**：3 份 SOP 文件（`sop.yaml` / `config/sop.default.yaml` / `cli.py` 内嵌兜底）全部统一含 `auto_fill_goals` 段。

---

## 🚀 CLI 扩展

```bash
# v0.4.3 新增 --no-auto-fill-goals 选项
devflow plan --no-auto-fill-goals

# 即使 SOP 配 auto_fill_goals.enabled=true, 该 flag 强制禁用
```

---

## 🔄 与 v0.4.2 的协同

v0.4.3 + v0.4.2 形成完整闭环：

| 阶段 | 行为 |
|---|---|
| 1. `devflow next` (brainstorm → plan) | v0.4.2 `_maybe_auto_research` 钩子触发 |
| 2. research 报告落落 `docs/devflow/research/<spec>-<ts>.md` | v0.4.2 缓存层写入 |
| 3. `_maybe_auto_fill_goals` 解析 → 填充 `Spec.goals` | v0.4.3 闭环 |
| 4. 用户 review goals → `devflow approve` | Stage1 → Stage2 |

---

## 📊 升级指南

### 如果你已经在用 v0.4.0/4.1/4.2

**升级 = 直接拉新 commit**。无破坏性变更：

```bash
git pull origin feat/v0.4-research
pip install -e .  # 或无需操作
```

### 字段兼容性

`Spec.goals` 字段**不变**（v0.4.3 仅修改内容）。Stage1 用户编辑流程不变。

### 用户体验变化

- **Stage1 用户编辑 goals 减少** —— 大多数情况下仅需 review 自动填充的 goals
- **但仍有 review 环节** —— Stage1 用户必须 review goals 后再 approve
- **新 `[INFO]` stderr echo** —— 提示 goals 已被自动填充（可 `--no-auto-fill-goals` 禁用）

---

## 🧪 测试变化

| 测试文件 | v0.4.0/4.1/4.2 | v0.4.3 | 变化 |
|---|---|---|---|
| `test_goals_extractor.py` | 0 | **13** | **+13**（新文件） |
| `test_spec_auto_filler.py` | 0 | **8** | **+8**（新文件） |
| `test_research_cli_integration.py` | 21 | **22** | +1（`--no-auto-fill-goals`） |
| **合计** | **152** | **174** | **+22** |

**全套**（含回归）：**235 passed + 1 skipped**（38s）

---

## 📚 文档更新

| 文件 | 变化 |
|---|---|
| `docs/release-notes-v0.4.3.md` | 本文件 |
| `docs/CHANGELOG.md` | 加 v0.4.3 条目（待 PR 合并后） |
| `docs/rfc-v0.4.3-auto-fill-goals.md` | 状态 draft → implemented |
| `sop.yaml` / `config/sop.default.yaml` / `cli.py` 内嵌 | 加 `research.auto_fill_goals` 段 |
| `README.md` | `### Research` 段加"自动 goals 草稿"说明（待更新） |

---

## 🔍 如何验证

```bash
# 1. 拉最新代码
git pull origin feat/v0.4-research

# 2. dogfooding demo
mkdir demo && cd demo
python -m devflow.cli init
python -m devflow.cli start "implement retry from scratch"
# 编辑 spec.yaml, goals: ["待补充"]
python -m devflow.cli approve <spec-id>
python -m devflow.cli next  # → brainstorm
python -m devflow.cli next  # → plan (自动跑 research + 自动填充 goals)

# 3. 验证 spec.yaml goals 已被填充
cat docs/devflow/specs/<spec-id>.yaml

# 4. 验证 [INFO] stderr echo
# [INFO] 已自动填充 goals (3 个), 请 review 后 devflow approve
```

---

## ⚠️ 设计权衡（Why）

| 决策 | 理由 |
|---|---|
| **不调 LLM** | DevFlow 是纪律引擎，LLM 是 v0.5 单独 RFC |
| **仅覆盖占位（默认）** | 不破坏用户已有内容，最小侵入式 |
| **结构化提取** | 确定性 + 可测试 + 零成本 |
| **trust_level 排序** | 高信任源排前，避免被低质量源主导 |
| **去重按 goal 主语** | 同名包不重复出现 |
| **cli flag `--no-auto-fill-goals`** | 用户可临时禁用，灵活 |
| **stage 2 触发** | plan 阶段已经有 research 上下文，复用 |

---

## 🎯 Dogfooding 经验

v0.4.3 实装前**通过 dogfooding 验证了 v0.4.2 B2 修复**（`_maybe_auto_research` 在 `next_phase` 自动触发 research），证明 dogfooding 在每个大功能前都有价值。

---

## 🔮 后续可做（v0.5+）

- **LLM 增强**：用 LLM 生成更智能的 goals（v0.5 单独 RFC，需要选 provider）
- **goals 智能评分**：每个 goal 的可执行性 / 完整性评分
- **调研 ↔ 实现 diff**：plan.task 是否真的用了 research 中提到的库

---

**Refs**：

- RFC 草案：[docs/rfc-v0.4.3-auto-fill-goals.md](./rfc-v0.4.3-auto-fill-goals.md)
- v0.4.2 release notes：[docs/release-notes-v0.4.2.md](./release-notes-v0.4.2.md)
- v0.4.1 release notes：[docs/release-notes-v0.4.1.md](./release-notes-v0.4.1.md)
- CHANGELOG：[docs/CHANGELOG.md](./CHANGELOG.md)

**v0.4.3 · 2026-08-21 · 准备就绪**