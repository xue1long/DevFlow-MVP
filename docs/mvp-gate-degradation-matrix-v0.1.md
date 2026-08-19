# DevFlow MVP · 门禁降级矩阵

> 本文定义每个 Stage 在 MVP 中的**精确出口条件**。
> 架构文档 §5 描述的是 v1.0 完整门禁；本文是 MVP 的降级实现规范。
> **实现 Agent 必须按本文定义的状态机逻辑编码，而非直接照搬架构文档 §5 的表格。**

---

## 0. 通用规则

### 0.1 Spec 必填字段定义

MVP 中 `Spec` 的**必填字段**（缺一不可视为 "字段不齐"）：

| 字段 | 类型 | 必填 | 校验规则 |
|---|---|---|---|
| `id` | string | ✅ | 非空，由 `devflow start` 自动生成 |
| `title` | string | ✅ | 非空 |
| `problem` | string | ✅ | 非空，≥10 字符 |
| `goals` | list[str] | ✅ | 非空列表，每项非空 |
| `non_goals` | list[str] | ✅ | 非空列表（至少 1 项），这是 "字段不齐" 判定的核心字段 |
| `options` | list | ❌ | MVP 可为空 |
| `decision` | string | ❌ | MVP 可为空 |
| `affected_modules` | list[str] | ❌ | MVP 可为空 |
| `contracts` | list | ❌ | MVP 可为空 |
| `status` | str | ✅ | 枚举：`draft` / `approved` |

### 0.2 Spec 状态流转

```
draft ──[devflow approve <spec-id>]──→ approved
```

- **新增 CLI 命令 `devflow approve <spec-id>`**：校验 §0.1 必填字段全部满足后，将 `status` 从 `draft` 改为 `approved`。
- 不满足时返回具体缺失字段清单，不修改状态。
- 这解决了 P1.7（无 approve 命令）和 P3.2（必填字段不明）。

### 0.3 `devflow commit` 语义定义

**`devflow commit <task-id>` 的行为是：先校验门禁，通过后执行 `git commit`**。

具体流程：
1. 校验当前 task 所处阶段的门禁是否全部 PASS（见 §1 各阶段定义）。
2. 校验 `git status` 非空（有可提交的变更）。
3. 自动生成 commit message：`<task-title> (task-<id>)`，符合 Conventional Commit 风格由用户在 `task.title` 中体现。
4. 执行 `git add -A && git commit -m "<message>"`。
5. 写入 `LedgerEntry(phase=current, task_id=<id>, action=commit, commit=<git-sha>)`。
6. 推进 task status 到 `done`。

**不通过时**：返回阻断原因，不执行 git 操作，不写账本。

这解决了 P3.3（commit 语义不明）。

### 0.4 Task 必填字段定义

| 字段 | 类型 | 必填 | 校验规则 |
|---|---|---|---|
| `id` | string | ✅ | 非空，`task-<n>` 格式 |
| `title` | string | ✅ | 非空 |
| `module` | string | ✅ | 非空 |
| `blocked_by` | list[str] | ❌ | MVP 可为空列表（不做环检测） |
| `is_tracer_bullet` | bool | ❌ | MVP 默认 false |
| `contract` | Contract | ❌ | Stage3 产出后填入 |
| `acceptance` | list[str] | ✅ | 非空列表（至少 1 项） |
| `status` | str | ✅ | 见 §0.5 |
| `commits` | list[str] | ❌ | `devflow commit` 后自动填入 |
| `wide_refactor` | bool | ❌ | MVP 默认 false |

### 0.5 Task 状态流转

```
todo ──[devflow next 进入 Stage3]──→ contracted
contracted ──[devflow next 进入 Stage4]──→ implementing
implementing ──[devflow next 进入 Stage5]──→ verifying
verifying ──[devflow next 进入 Stage6]──→ reviewing
reviewing ──[devflow commit <task-id>]──→ done
todo 或 contracted ──[devflow skip-task <task-id> --reason <reason>]──→ skipped
```

- **`devflow next` 自动推进 task status**（基于当前阶段转换）。
- **`devflow commit` 在 Stage6 门禁通过后执行 git commit 并推进到 done**。
- **`devflow skip-task <task-id> --reason <reason>`**：
  - **前置条件**：task 当前状态必须为 `todo` 或 `contracted`。已进入 `implementing/verifying/reviewing` 状态的 task **不允许 skip**（防止 Abandon-in-Place：跳过已写代码的 task 导致脏文件泄漏）。
  - 违反前置条件时返回错误："task-<id> 已进入实现阶段，无法 skip；如需放弃请先 `git stash` 或 `git checkout` 清理工作区"。
  - 通过时写入 LedgerEntry(action=skip, reason=...)，task status→skipped。
  - Stage7 的"所有 task done"检查改为"所有 task done 或 skipped"。
- MVP 不做 `blocked_by` 依赖校验：commit 时不要求前置 task 已 done。

### 0.6 多 Spec / 多 Plan 处理

- 引擎维护一个 `current_spec_id` / `current_plan_id` 状态（存在 `progress.yaml` 中）。
- `devflow start <draft>` 创建新 Spec 时，自动将其设为当前活跃 Spec。
- `devflow next` / `devflow status` / `devflow gate` / `devflow commit` 均操作当前活跃 Spec/Plan。
- `devflow status --all` 可查看所有 Spec 的状态概览。
- `devflow switch <spec-id>` 可切换当前活跃 Spec（MVP 可选，不列入验收）。
- **task-id 唯一性**：task-id 在同一 Plan 内唯一即可（格式 `task-<n>`）。多 Spec 场景下 `devflow commit/skip-task` 均操作当前活跃 Spec 的 Plan，不跨 Spec。MVP 不支持 `<spec-id>/<task-id>` 格式（v0.2 扩展）。

这解决了 P3.5（多 Spec 并行未定义）。

### 0.7 `suspend` / `resume` 语义

- `devflow suspend [note]`：写出 `handoff-<phase>.md`，在 `progress.yaml` 记录 suspend 状态。
- **`devflow resume`：新增 CLI 命令**，检测 `handoff-*.md` 存在时，从 `progress.yaml` 恢复阶段状态，输出续接指引。
- 若无 handoff 文件，`resume` 报错退出。
- `devflow next` 在有 suspend 记录时，行为等同 `devflow resume`（自动检测并续接）。

这解决了 P3.6（suspend 后无 resume 路径）。

### 0.8 SOP 版本协商

`sop.yaml` 新增顶层 `sop_version` 字段：

```yaml
sop_version: "0.1"
```

引擎的 `policy/` 模块校验规则：
- `sop_version` 缺失 → warning（兼容旧配置）
- 引擎不支持的 `sop_version` → error 并退出
- 未知字段 → warning（向前兼容）
- 必需字段缺失 → error

这解决了 P2.7（无版本兼容策略）。

---

## 1. 逐阶段出口门禁（MVP 降级版）

### Stage 0: intake

| 项 | v1.0 完整（架构文档） | MVP 降级 |
|---|---|---|
| 入口条件 | 无（起始阶段） | 无 |
| 必产工件 | `Intake`（triage_state 判定） | `Intake`（triage_state 判定） |
| 出口门禁 | `triage_state == ready-for-agent` | 同左 |
| MVP 特殊行为 | — | `intake_fast_skip: true` 时，`devflow start` 自动创建 `Intake(triage_state=ready-for-agent)`，**Stage0 仍然执行**（产出工件 + 写账本），只是判定结果预设 |
| `devflow next` 行为 | 检查 triage_state | 同左 |

> **注意**：`intake_fast_skip` 不是 "跳过 Stage0"，而是 "Stage0 自动判定为 ready-for-agent"。Stage0 的工件产出和账本记录仍然发生。这保护了 "不可跳步" 的核心价值（P4.2）。

### Stage 1: brainstorm

| 项 | v1.0 完整 | MVP 降级 |
|---|---|---|
| 入口条件 | `Stage0.exit_gate == PASS` | 同左 |
| 必产工件 | `Spec`（approved）+ CONTEXT.md/ADR 维护 | `Spec`（status=approved，必填字段见 §0.1） |
| 出口门禁 | Spec 必填字段齐 + non_goals 非空 | 同左（精确字段见 §0.1） |
| `devflow next` 行为 | 检查 Spec.status == approved 且 §0.1 必填字段齐 | 同左；不满足时返回缺失字段清单 |

### Stage 2: plan

| 项 | v1.0 完整 | MVP 降级 |
|---|---|---|
| 入口条件 | `Stage1.exit_gate == PASS` | 同左 |
| 必产工件 | `Plan`（DAG 化 tasks） | `Plan`（含 tasks 列表） |
| 出口门禁 | 每 task 卌模块、blocked_by 无环、有 acceptance、优先 tracer-bullet | **降级**：至少 1 个 task + 每个 task 有 `module`(非空) + `acceptance`(非空列表)。**不做**：环检测、tracer-bullet 强制、单模块校验 |
| `devflow next` 行为 | 检查 Plan 存在 + tasks 非空 + 每 task 有 module + acceptance | 同左 |

### Stage 3: contract

| 项 | v1.0 完整 | MVP 降级 |
|---|---|---|
| 入口条件 | `Stage2.exit_gate == PASS` | 同左 |
| 必产工件 | 每个 task 的 `Contract` + 测试文件存在 | 每个 task 的 `Contract` 对象存在（含 `module` + `interface_signature`）；**不要求**测试文件实际存在（MVP 由 GateRunner 在 Stage5 验证） |
| 出口门禁 | 测试文件存在且可收集 | **降级**：每个 task 有 Contract 对象 + Contract.module 非空 + Contract.interface_signature 非空 |
| `devflow next` 行为 | 检查每个 task 的 Contract 存在且字段非空 | 同左 |

### Stage 4: implement

| 项 | v1.0 完整 | MVP 降级 |
|---|---|---|
| 入口条件 | `Stage3.exit_gate == PASS` | 同左 |
| 必产工件 | 代码 + commit | 代码变更存在（`git status` 非空）或所有 task 已 done/skipped |
| 出口门禁 | 无未提交调试码；安全/校验门禁不被极简砍掉 | **降级**：`git status` 非空（有代码变更可提交）**或**所有 task status 为 done/skipped（无剩余 todo/contracted/implementing task） |
| MVP 不做 | 偷懒阶梯前置判定、安全地板检查 | — |
| `devflow next` 行为 | 检查有代码变更 | 检查：(a) `git status` 非空，或 (b) 当前 Plan 的所有 task 均为 done/skipped。满足任一即可推进 |

### Stage 5: verify

| 项 | v1.0 完整 | MVP 降级 |
|---|---|---|
| 入口条件 | `Stage4.exit_gate == PASS` | 同左 |
| 必产工件 | 测试报告 + DebugSession | 测试报告（`tests_pass` 门禁输出） |
| 出口门禁 | `tests_pass` gate 通过 | 同左：执行 `sop.yaml` 中 `tests_pass.command`，exit code 0 = PASS。**边界情况**：如果所有 task 均为 skipped（无代码变更），pytest 无测试可跑时 exit code 0 = PASS |
| MVP 不做 | Debug 反馈环律、diagnosing-bugs | verify 失败时返回失败原因，不进入 debug 子循环 |
| `devflow next` 行为 | 执行 tests_pass gate | 同左；**注意**：`devflow next` 从 Stage4→Stage5 时自动触发 `tests_pass` 门禁执行 |

### Stage 6: review

| 项 | v1.0 完整 | MVP 降级 |
|---|---|---|
| 入口条件 | `Stage5.exit_gate == PASS` | 同左 |
| 必产工件 | 双轴报告（Standards×Spec） | **降级**：自查清单（MVP 自动检查项：是否有未提交文件、是否有 TODO/FIXME 未处理） |
| 出口门禁 | 双轴均 PASS | **降级**：`ci_green` gate 通过 + 自查清单无严重问题 |
| MVP 不做 | 双轴评审、Fowler 气味基线 | — |
| `devflow next` 行为 | 执行 ci_green gate + 自查清单 | 同左 |

### Stage 7: finish

| 项 | v1.0 完整 | MVP 降级 |
|---|---|---|
| 入口条件 | `Stage6.exit_gate == PASS` | 同左 |
| 必产工件 | 文档同步 + CI | **降级**：`progress.yaml` 账本记录完整（每个 phase 过渡有 LedgerEntry） |
| 出口门禁 | `ci_green` + 文档已更新 | **降级**：账本完整 + 所有 task status 为 done 或 skipped |
| `devflow next` 行为 | 检查账本完整性 + task 状态 | 同左 |

---

## 2. CLI 命令完整清单（MVP 11 个，含新增 3 个：approve / resume / skip-task）

| 命令 | 输入 | 行为 | 解决问题 |
|---|---|---|---|
| `devflow init` | — | 生成 `sop.yaml`（从 `config/sop.default.yaml` 复制）+ `specs/` + `plans/` + `progress.yaml` + `CONTEXT.md` | 验收 1 |
| `devflow start <draft>` | 需求草稿文本 | 创建 `specs/<id>.yaml`（status=draft）+ 创建 Intake（`intake_fast_skip` 时 triage_state=ready-for-agent）+ 设为当前活跃 Spec + 写账本 | 验收 2/4 |
| `devflow approve <spec-id>` | spec-id | 校验 §0.1 必填字段 → 通过则 status→approved + 写账本；不通过则返回缺失清单 | **P1.7** |
| `devflow next` | — | 根据当前阶段执行出口门禁校验 → 通过则推进阶段 + 写账本；不通过则返回阻断原因 + 缺失工件清单 | 验收 3/4 |
| `devflow status` | [--all] | 返回当前阶段、活跃 Spec/Plan 状态、阻塞项、账本摘要；`--all` 列出所有 Spec | — |
| `devflow gate <phase>` | 阶段号（0-7） | 执行该阶段的所有 enabled blocking 门禁，输出 pass/fail 详情 | 验收 5 |
| `devflow commit <task-id>` | task-id | 校验 Stage5/6 门禁 → 通过则 git commit + 写账本 + task→done；不通过则返回阻断原因 | 验收 6 |
| `devflow audit` | — | 执行 RedLineAuditor 全量扫描，输出违规清单 | 验收 9 |
| `devflow suspend [note]` | 可选交接笔记 | 写出 `handoff-<phase>.md` + 在 progress.yaml 记录 suspend 状态 | 验收 8 |
| `devflow resume` | — | 检测 handoff 文件 → 恢复阶段状态 + **重新执行当前阶段出口门禁** + 输出续接指引 | **P3.6 / R8** |
| `devflow skip-task <task-id>` | task-id + `--reason` | 跳过 task（需提供 reason），写 LedgerEntry(action=skip)，task→skipped | **R7** |

---

## 3. `devflow gate <phase>` 参数语义

**参数是阶段号（0-7），不是门禁名**。

引擎内部维护一个 `阶段→门禁集` 映射：

| 阶段 | 映射的门禁（MVP enabled） |
|---|---|
| 0 (intake) | `intake_gate` |
| 1 (brainstorm) | 无外部门禁（Spec 字段校验内置在状态机中） |
| 2 (plan) | 无外部门禁（Plan/Task 字段校验内置） |
| 3 (contract) | 无外部门禁（Contract 字段校验内置） |
| 4 (implement) | 无外部门禁（git status 检查内置） |
| 5 (verify) | `tests_pass` |
| 6 (review) | `ci_green` |
| 7 (finish) | 无外部门禁（账本完整性检查内置） |

这解决了 P1.3（gate 参数语义不明）。

---

## 4. 验收标准补充（新增第 11-13 条）

| # | 验收项 | 说明 |
|---|---|---|
| 11 | `devflow approve <spec-id>` 校验必填字段，通过后 status→approved | P1.7 / P3.2 |
| 12 | `devflow resume` 检测 handoff 文件并恢复阶段状态 | P3.6 |
| 13 | 引擎自身 `tests/` 目录包含 state_machine + model 的基础单元测试，覆盖状态转换和模型校验 | P4.3 |

---

## 5. 测试策略

- 每个验收测试使用 `pytest` 的 `tmp_path` fixture 隔离文件系统（P2.6）。
- 状态机单元测试（`tests/test_state_machine.py`）覆盖：正常推进、跳步阻断、approve 未通过。
- 模型单元测试（`tests/test_models.py`）覆盖：必填字段校验、status 枚举约束。
- 集成测试（`tests/test_acceptance.py`）对应 §4 验收 1-13。
