# CONTEXT.md — DevFlow 工作区布局与文件规范

> 本文件是 DevFlow **运行时产物布局**的权威规范。所有出现在项目根目录的文件/目录，其创建者、格式、生命周期必须与本文档一致。
> 上位文档：`docs/workspace-layout-v0.1.md`（评审档案，已被"第一性方案"替代，不再实施目录重组）。

---

## 1. 总览：项目根目录布局

```
{项目根目录}/
│
├── docs/
│   ├── devflow/                ← DevFlow 运行时产物根（v0.3.4 统一前缀）
│   │   ├── specs/
│   │   │   └── {spec-id}.yaml      ← Spec 文件（需求 / 方案）
│   │   ├── plans/
│   │   │   └── {plan-id}.yaml      ← 计划文件（Plan + Task 列表）
│   │   ├── review/
│   │   │   └── {spec-id}/
│   │   │       ├── r{N}.yaml       ← 第 N 轮评审报告（只增不改）
│   │   │       └── f{N}.yaml       ← 第 N 轮修复记录（只增不改）
│   │   ├── progress.yaml           ← 哈希链账本（机器状态 + 决策审计，不手改）
│   │   └── progress.yaml.lock      ← 文件锁（运行时临时，正常状态不存在）
│   │
│   ├── README.md               ← 项目文档（原有，命名见 docs/DOCS_GUIDELINES.md）
│   ├── architecture...md       ← 架构文档等（原有，不动）
│   └── ...
│
├── sop.yaml                ← 流程配置（devflow init 生成，根目录保留）
├── CONTEXT.md              ← 本文件（术语表 + 布局规范，根目录保留）
├── handoff-{N}.md          ← 阶段交接物（如 handoff-3.md，根目录保留）
│
├── src/                    ← 项目源代码（本仓库 = devflow 引擎自身）
├── tests/                  ← 测试代码
├── config/                 ← 默认配置模板
│   └── sop.default.yaml    ← init 时复制为 sop.yaml
└── graphify-out/           ← 知识图谱产物（.gitignore 排除，非展示文件）
```

> **路径策略**：以上 `docs/devflow/` 前缀由 `src/devflow/storage/layout.py` 的 `LayoutResolver`
> 统一解析（读 `sop.yaml` 的 `storage:` 节）。改保存位置只需改配置，不动引擎代码。

---

## 2. 运行时产物明细（Agent 操作对象）

| 内容 | 路径 | 格式 | 创建者 | 可写性 |
|------|------|------|--------|--------|
| **Spec（需求/方案）** | `docs/devflow/specs/{spec-id}.yaml` | YAML | `devflow start` | 手动编辑（补齐字段） |
| **Plan（计划方案）** | `docs/devflow/plans/plan-{spec-id}.yaml` | YAML | `devflow plan` | 命令生成，勿手改 |
| **评审报告** | `docs/devflow/review/{spec-id}/r{N}.yaml` | YAML | `devflow review` | **不可覆写**（P1-14 承诺） |
| **修复记录** | `docs/devflow/review/{spec-id}/f{N}.yaml` | YAML | `devflow fix` | **不可覆写** |
| **账本** | `docs/devflow/progress.yaml` | YAML | 引擎自动 | **禁止手改**（哈希链校验） |
| **文件锁** | `docs/devflow/progress.yaml.lock` | 文本(pid) | 引擎临时 | 运行中出现，正常结束即删 |
| **流程配置** | `sop.yaml` | YAML | `devflow init` | 可编辑（改后影响门禁） |
| **领域术语** | `CONTEXT.md` | Markdown | `devflow init` | 可编辑 |
| **交接物** | `handoff-{phase}.md` | Markdown | `devflow suspend` | 只读（恢复时读取） |
| **活跃指针** | `progress.yaml` 内 `current_spec_id` / `current_plan_id` | — | 引擎 | 勿手改 |

---

## 3. 文件命名规范

### 3.1 Code 产物（`src/`、`tests/`）
- **Python**：`snake_case.py`；模块边界 = 职责边界（model/engine/storage/verify/policy/adapters/util）
- **测试**：`test_*.py`，与被测模块同名前缀（`test_plan.py` 测 `plan.py`）
- **新代码归属**（分层纪律）：
  - `model/` — 纯数据（pydantic v2），禁止 IO
  - `engine/` — 状态机 / 审核 / 红线 / 派发
  - `storage/` — 存储后端（fs / memory / review_store_*）
  - `verify/` — 门禁执行
  - `policy/` — SOP 加载解析
  - `adapters/` — 外部集成（MCP / Skill / Invoker）
  - `util/` — 纯函数工具（dag / json_schema）
  - `cli.py` — 薄门面（typer.app + JSON 输出）

### 3.2 文档（`docs/`）
- **命名**：`{主题}-{子主题?}-{版本?}-{类型?}.md`，kebab-case
- **类型后缀**：`-design` / `-guide` / `-report` / `-template` / `-brief` / `-rfc`
- **规范源**：`docs/DOCS_GUIDELINES.md`；索引归口 `docs/README.md`；变更记 `docs/CHANGELOG.md`

### 3.3 运行时命名
- **Spec ID**：`YYYYMMDD-{kebab标题}`（`devflow start` 自动生成）
- **Plan ID**：`plan-{spec-id}`（约定前缀）
- **评审轮次**：`r{递增数字}.yaml`；**修复轮次**：`f{递增数字}.yaml`
- **交接物**：`handoff-{phase数字}.md`

---

## 4. 只读 / 写入边界（Agent 必须遵守）

### 🔒 禁止写入 / 修改
- `docs/devflow/progress.yaml` — 篡改会被 `devflow audit` 哈希链校验揭穿
- `docs/devflow/review/{spec-id}/r{N}.yaml`、`f{N}.yaml` — 历史不可改写，只能追加新轮次
- `docs/devflow/plans/plan-*.yaml` — 用 `devflow plan / task-add / contract-add` 操作，不直接编辑

### ✍️ 允许编辑
- `docs/devflow/specs/{spec-id}.yaml` — 补齐 goals / non_goals / problem / acceptance
- `sop.yaml` — 流程配置（谨慎：改门禁影响全流程）
- `CONTEXT.md` — 术语与规范
- `graphify-out/` — 生成物，可重建

### 📤 Agent 新产出落地
1. 代码改动 → 按分层放进 `src/`，先写测试到 `tests/`
2. 新设计/方案文档 → `docs/`，命名遵守 `DOCS_GUIDELINES.md`，同步更新 `docs/README.md` 索引 + `CHANGELOG.md`
3. 跨 Spec 的结构化数据 → 用 `devflow find <keyword>` 搜索，不新建目录

---

## 5. 路径策略变更记录（v0.3.4 → v0.4.0）

`docs/workspace-layout-v0.1.md` 曾提议 `doc/devflow-workspace/{plans,reviews,implementations}/{spec-id}/`，被 4 角色评审否决。

**v0.3.4** 通过 `LayoutResolver`（`src/devflow/storage/layout.py`）实现了**配置化路径策略**：

1. **改路径不再改引擎代码**：`sop.yaml` 的 `storage:` 段是唯一配置源，`LayoutResolver` 解析出 `LayoutPaths` 注入各存储后端
2. **默认值 `docs/devflow/`**：运行时产物统一前缀，不污染根目录
3. **后向兼容**：`FSBackend(layout=LayoutPaths(root))` 显式传入旧布局即可恢复旧路径

**结论**：路径策略已从"硬编码约定"升级为"配置驱动"。改路径 = 改 `sop.yaml` 一行，不动引擎代码。

---

## 6. 快速自查命令

| 需求 | 命令 |
|------|------|
| 当前阶段 / 活跃 Spec | `devflow status` |
| 搜索某关键词跨文件 | `devflow find <keyword>` |
| 列出活跃 / 已归档 Spec | `devflow list-active` / `devflow list-archived` |
| 审计账本完整性 | `devflow audit` |
| 查看评审历史 | `devflow history [spec-id]` |

---

_文档版本：v0.3.4 落地（2026-08-20）_
_规范权威级：本文档（运行时布局） > docs/DOCS_GUIDELINES.md（文档命名） > 架构文档_