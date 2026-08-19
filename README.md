# DevFlow — 方案驱动开发工作流引擎

> **MVP v0.2** — 给 AI Agent 用的强制流程引擎：8 阶段不可跳步，逐阶段出口门禁，双轴评审闭环，append-only 可审计账本。

## 核心特性

- **8 阶段强制流水线**：`intake → brainstorm → plan → contract → implement → verify → review → finish`
- **逐阶段出口门禁**：tests_pass / ci_green / intake_gate / review_gate
- **审核闭环（v0.2）**：双轴评审 Standards × Spec，自动验证 + 防死循环（最多 5 轮）
- **append-only 账本**：进度账本带 SHA256 哈希链 + 文件锁，可检测篡改
- **可审计**：每个决策都有记录，账本可追溯、可验证完整性
- **可迁移**：StorageBackend / GitPort / ReviewEngine 抽象接口，支持后端扩展
- **解耦分层**：`model/`（纯数据） → `engine/`（状态机/红线/审核） → `storage/`（多后端） → `verify/`（门禁执行） → `policy/`（SOP 加载） → `cli.py`（薄门面）

## 安装

```bash
# 本地安装（开发模式）
pip install -e .

# 或直接使用（无需安装）
PYTHONPATH=src python -m devflow.cli --help
```

要求：Python ≥ 3.12，依赖 pydantic ≥ 2.0、pyyaml ≥ 6.0、typer ≥ 0.9、pytest ≥ 7.0。

## 5 分钟上手

```bash
# 1. 初始化 DevFlow 工作区
devflow init

# 2. 创建需求草稿
devflow start "为 pipeline 增加 batch 重试机制"

# 3. 编辑 specs/<spec-id>.yaml，补齐 goals / non_goals / problem 字段

# 4. 通过 Spec 校验
devflow approve <spec-id>

# 5. 推进到下一阶段（自动校验当前阶段门禁）
devflow next    # intake → brainstorm

# 6. 创建计划（Stage2 plan）
devflow plan --task "构建 CLI|cli|支持命令解析" --task "测试执行|tests|有测试覆盖"

# 7. 添加更多任务
devflow task-add "实现核心" --module core --acceptance "覆盖目标,有单元测试"
devflow task-list

# 8. 为每个 task 添加 Contract（Stage3 contract）
devflow contract-add task-1 --module cli --signature "parse()"

# 9. 推进到 implement 阶段，写代码
devflow next

# 10. commit task（必须 Stage5+）
devflow next  # 5
devflow commit task-1

# 11. 推进到 review 阶段，执行评审
devflow next  # 6
devflow review
devflow history
```

## CLI 命令速查

| 命令 | 阶段 | 说明 |
|------|------|------|
| `devflow init` | — | 初始化工作区（创建 sop.yaml + specs/ + plans/） |
| `devflow start "<需求>"` | 0 | 创建 Spec + Intake |
| `devflow approve <spec-id>` | 0-1 | 校验 Spec 必填字段并 approve |
| `devflow next` | * | 推进到下一阶段（含门禁检查） |
| `devflow resume` | — | 从 suspend 恢复 |
| `devflow status` | * | 查看当前状态（Spec/Plan/Task 摘要） |
| `devflow plan` | 2 | 创建计划（含初始 task） |
| `devflow task-add` | 2 | 添加 task 到当前 Plan |
| `devflow task-list` | * | 列出当前 Plan 的所有 task |
| `devflow contract-add <tid>` | 3 | 为 task 添加 Contract |
| `devflow gate <phase>` | * | 执行指定阶段门禁（0-7） |
| `devflow commit <tid>` | 5+ | 提交 task（门禁 + git commit + 账本） |
| `devflow skip-task <tid> --reason` | * | 跳过 task（仅 todo/contracted） |
| `devflow audit` | * | 执行红线审计 |
| `devflow suspend [note]` | * | 挂起工作流（写 handoff 文件） |
| `devflow review [spec-id]` | 2+ | 执行双轴评审 |
| `devflow fix <vid...> [--residual]` | * | 修复 / 登记违规 |
| `devflow history [spec-id]` | * | 查看审核历史 |

## 阶段对照表

| 编号 | 阶段 | 阶段名 | 主要活动 |
|------|------|--------|----------|
| 0 | intake | 需求登记 | 创建 Spec 草稿 + Intake |
| 1 | brainstorm | 方案澄清 | 编辑/完善 Spec（goals/non_goals/problem） |
| 2 | plan | 计划 | 创建 Plan + Task 列表 |
| 3 | contract | 契约 | 为每个 Task 写 Contract（module + 签名） |
| 4 | implement | 实现 | 写代码 + git 提交 |
| 5 | verify | 验证 | tests_pass 门禁（pytest 等） |
| 6 | review | 评审 | 双轴评审 + ci_green 门禁 |
| 7 | finish | 完成 | 工作流收尾 |

## 核心概念

### Spec
需求规约，包含 `title` / `problem`（≥10 字符）/ `goals`（≥1）/ `non_goals`（≥1）/ `status`（draft | approved）。

### Plan
一组 Task 的列表，每个 Task 有 `id` / `title` / `module` / `acceptance` / `contract` / `status`。

### Contract
Stage3 产出：Task 的接口契约（module + interface_signature）。

### 双轴评审（v0.2）
- **Standards 轴**：自动检查（huge_pr / no_test / cross_module_import / 等 6 条规则）
- **Spec 轴**：自动检查（goal 覆盖 + contract 缺失 + 占位 goals 提示）

### 账本
`progress.yaml` — append-only 日志，每条条目带 SHA256 哈希链（`_hash` / `_prev_hash`），支持 `verify_ledger()` 检测篡改。

## 配置（sop.yaml）

主要字段：
```yaml
sop:
  sop_version: "0.1"
  phases: [intake, brainstorm, plan, contract, implement, verify, review, finish]
  intake_fast_skip: true
  gates:
    tests_pass: {command: "pytest -q", blocking: true, enabled: true, bind_to_stage: 5}
    ci_green:   {command: "echo ci-placeholder", blocking: false, enabled: true, bind_to_stage: 6}
    review_gate: {kind: review, blocking: true, enabled: true, bind_to_stage: 2, max_rounds: 5}
  modules: {facade: "__init__.py", forbidden_import: ["service/", "model/", "utils/internal/"]}
  tooling: {test_runner: pytest, import_mode: importlib, proxy_strip: true, command_timeout: 120}
```

完整 SOP 字段见 `src/devflow/policy/loader.py`。

## 测试

```bash
# 全部测试（76 passed / 1 skipped）
python -m pytest tests/ -v

# 仅 P0/P1 整改验证测试（12 个）
python -m pytest tests/test_p0_fixes.py -v

# 验证账本哈希链完整性
python -c "from devflow.storage.fs_backend import FSBackend; from pathlib import Path; print(FSBackend(Path('.'))).verify_ledger()"
```

## 架构

```
┌─────────────────────────────────────────────────────┐
│                   cli.py (typer)                    │  薄门面
├─────────────────────────────────────────────────────┤
│  engine/                                            │
│    ├─ state_machine.py (8 阶段状态机)                │
│    ├─ review_engine.py (双轴评审 + 防死循环)         │
│    ├─ redline_auditor.py (11 条红线)                 │
│    └─ checkpoint.py / skill_resolver.py             │
├─────────────────────────────────────────────────────┤
│  model/                                              │  纯 pydantic v2 数据
│    ├─ spec.py / plan.py / task.py / contract.py    │
│    ├─ review.py / ledger.py / intake.py             │
│    └─ domain_model.py / quality_gate.py             │
├─────────────────────────────────────────────────────┤
│  storage/                                            │  可替换后端
│    ├─ base.py (StorageBackend ABC)                  │
│    ├─ fs_backend.py (FSBackend + 哈希链 + 文件锁)   │
│    ├─ git_port.py (GitPort ABC + SystemGitPort)     │
│    └─ review_store.py (ReviewStore)                 │
├─────────────────────────────────────────────────────┤
│  verify/gate_runner.py (GateRunner)                 │
│  policy/loader.py (SOP 加载 + 版本协商)              │
└─────────────────────────────────────────────────────┘
```

## 限制与残余风险

详见 [`docs/audit-ledger.md`](./docs/audit-ledger.md)（审计整改台账）：

- v0.2 残余：GateRunner 缺失时 review 门禁 fail-open、5 条红线空实现、非自动验证 fix 无真实验证、ci_green 占位、账本缺 actor/session_id、no_test 硬编码 .py、review 报告与账本无交叉校验——这些需 v0.3 处理。
- MVP 单进程使用：账本哈希链已实现，但并发文件锁不在 MVP 范围。

## 版本

详见 [`docs/CHANGELOG.md`](./docs/CHANGELOG.md)。主要版本：

- **v0.1** (4cb360d)：核心状态机 + 11 个 CLI 命令
- **v0.2** (d20d25e / ec42f9e)：审核闭环 + 防死循环
- **v0.2.1** (96dcab8 / 721bdff / f23acd8)：第 3 轮审计 P0/P1/P2 整改

## 相关文档

完整索引见 [`docs/README.md`](./docs/README.md)。主要文档：

- 架构设计：[`docs/devflow-architecture-v0.1.md`](./docs/devflow-architecture-v0.1.md)
- MVP 简报：[`docs/devflow-mvp-brief.md`](./docs/devflow-mvp-brief.md)
- 门禁降级矩阵：[`docs/mvp-gate-degradation-matrix-v0.1.md`](./docs/mvp-gate-degradation-matrix-v0.1.md)
- v0.2 审核闭环设计：[`docs/review-loop-v0.2-design.md`](./docs/review-loop-v0.2-design.md)
- 首轮审计报告：[`docs/devflow-first-audit-report-v0.1.md`](./docs/devflow-first-audit-report-v0.1.md)
- 审计流程提示词：[`docs/audit-prompt-template-v0.1.md`](./docs/audit-prompt-template-v0.1.md)
- 文档规范：[`docs/DOCS_GUIDELINES.md`](./docs/DOCS_GUIDELINES.md)
- 工作区布局设计：[`docs/workspace-layout-v0.1.md`](./docs/workspace-layout-v0.1.md)（v0.3 实施）
- 变更日志：[`docs/CHANGELOG.md`](./docs/CHANGELOG.md)
- 审计整改台账：[`docs/audit-ledger.md`](./docs/audit-ledger.md)

## License

MIT