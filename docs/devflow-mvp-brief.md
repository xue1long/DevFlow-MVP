# DevFlow MVP · 实现简报（给实现 Agent 的首读文件）

> 你是被指派实现 **DevFlow** 开发工作流引擎的 Agent。本文是你的开题范围书，**先读完再动手**。
> 完整设计依据：`开发工作流引擎架构文档.md`（同目录）。本文是其 §16 的可执行版。
>
> **文档权威级（高→低）**：`MVP-门禁降级矩阵.md`（门禁权威）> 本文 §1 IN/OUT（范围权威）> `sop.yaml`（配置权威）> 架构文档（设计参考）。四者冲突时以此为准。

---

## 0. 一句话任务

造一个 **Python 引擎 + CLI 门面**，强制跑通「Intake → 八阶段」工作流、禁止跳步、账本落盘。MVP 先交付可用的 CLI 工具；WorkBuddy Skill 适配作为可选的 M5 封装层。MVP 不做 MCP / 三平台 / 双轴评审。

---

## 1. 范围（IN / OUT）—— 最重要，别超范围

### IN（必须做）
- 领域模型（pydantic v2）：`Spec` / `Plan` / `Task`（**MVP 先做线性 `blocked_by` 列表，暂不实现 DAG 环检测**）/ `Contract` / `QualityGate` / `LedgerEntry` / `DomainModel`（**MVP 仅 CONTEXT.md 骨架，不含 ADR 维护**）/ `Intake`
- 编排：`PhaseStateMachine`（8 阶段，含 Stage0 intake 闸门）、`SkillResolver`（基础版，意图路由仅覆盖线性推进）、`Checkpoint`（含 suspend/resume）、`RedLineAuditor`（基础 11 红线，MVP 可执行的 10 条 + `circular_dep` 标记为 `mvp_skip`）
- 存储：`StorageBackend` + `FSBackend`（specs/ plans/ progress.yaml + CONTEXT.md 骨架，git 追踪）；**MVP 账本简化为 append-only 日志**（`progress.yaml` 只追加不覆盖，不做完整 CCR 内容寻址哈希）
- CLI（**11 个命令**）：`init` / `start` / `approve` / `next` / `resume` / `status` / `gate` / `commit` / `audit` / `suspend` / `skip-task`
- 门禁（最小集）：`tests_pass`（blocking）+ `ci_green`（**MVP advisory，占位命令，接入真实 CI 后改为 blocking**）+ `intake` 闸门
- 配置：读取配套 `sop.yaml`（含版本协商，见 `MVP-门禁降级矩阵.md` §0.8）

### OUT（明确不做，留给后续版本）
- ❌ MCP Server（v0.3）
- ❌ Claude Code / CodeBuddy 适配器（v0.3）
- ❌ 双轴代码评审、Fowler 气味基线（v0.2；MVP 仅自查清单占位）
- ❌ Debug 反馈环律形式化（§5.1；MVP 的 verify 只跑 tests_pass）
- ❌ 周期架构熵门禁、token 成本门禁（后续）
- ❌ ponytail overbuild 审计实际接线（`sop.yaml` 有键但 `enabled:false`）
- ❌ DBBackend（仅 FS）
- ❌ DAG 环检测、tracer-bullet 垂直切片、SDD 子代理派发、双轴评审、ADR 维护（v0.2+）
- ❌ 完整 CCR 内容寻址存储（v0.2+；MVP 仅 append-only）
- ❌ WorkBuddy Skill 适配（M5 可选；MVP Done 标准不要求）

---

## 2. 技术栈（已拍板，勿自选）
- Python 3.11+ · **pydantic v2**（模型即 schema）· **pyyaml**（文件 IO）· **typer**（CLI）· **pytest**（测试）
- MCP 预留接口用 **fastmcp**（v0.3 才用，MVP 不装）
- DevFlow 自身许可证：**MIT**；**严禁 vendoring caveman 的 BSL-1.1 引擎/代理代码**（见架构文档 §15.7）

---

## 3. 目录布局（取自架构文档 §11）
```
devflow/
├── pyproject.toml
├── src/devflow/
│   ├── engine/            # 编排引擎（平台无关）
│   │   ├── state_machine.py   # PhaseStateMachine
│   │   ├── skill_resolver.py  # 阶段→能力映射 + 基础意图路由
│   │   ├── checkpoint.py      # 挂起/续接（suspend/resume）
│   │   └── redline_auditor.py
│   ├── model/             # 领域模型（pydantic，必填字段见 MVP-门禁降级矩阵 §0.1/§0.4）
│   ├── storage/           # StorageBackend + FSBackend
│   ├── verify/            # GateRunner + TestRunner 封装
│   ├── policy/            # sop.yaml 加载与校验（含版本协商）
│   └── cli.py             # typer 门面（11 个子命令）
├── adapters/workbuddy/    # M5 可选，MVP 不要求
├── config/sop.default.yaml
├── tests/
│   ├── test_models.py         # 领域模型单元测试
│   ├── test_state_machine.py  # 状态机单元测试
│   └── test_acceptance.py     # 验收标准集成测试（13 条）
└── pyproject.toml
```

---

## 4. 验收标准（MVP Done = 以下 13 条全过）

> **TDD 先行**：M0 阶段先将以下 13 条验收标准写成 pytest 测试用例（`tests/test_acceptance.py`），后续每个里程碑的实现都应让这些测试逐步变绿。这是 DevFlow 自身"契约先行"理念的践行。
>
> **测试隔离**：每个验收测试使用 `pytest` 的 `tmp_path` fixture 隔离文件系统，避免测试间文件污染。

1. `devflow init` 在空仓库生成 `sop.yaml` + `specs/` + `plans/` + `progress.yaml` + `CONTEXT.md`，退出码 0。
2. `devflow start <draft>` 产出 `specs/<id>.yaml`，`status=draft`，含非空 `problem/goals`。
3. **不可跳步**：Spec 未 `approved`（缺 `non_goals` 或必填字段不齐，必填字段见 `MVP-门禁降级矩阵.md` §0.1）→ `devflow next` 拒绝进 Stage2，返回具体缺失字段清单。
4. **Intake 闸门**：`Intake.triage_state != ready-for-agent` → `devflow next` 不进 Stage1，返回 triage 阻塞原因。**MVP 简化**：`intake_fast_skip: true` 时 `devflow start` 自动创建 `triage_state=ready-for-agent` 的 Intake，**Stage0 仍然执行**（产出工件 + 写账本），只是判定结果预设。MVP 中 Stage0 的定位是"入口标记"（记录工作流起点），实质分类判定功能留到 v0.2。
5. `devflow gate 5` 执行 `tests_pass`，输出 pass/fail；命令非零退出即 fail。
6. **提交门禁**：`devflow commit <task>` 在 Stage5/6 未全 PASS 时拒绝提交，返回原因且不执行 git commit。通过时执行 `git add -A && git commit`，commit message 格式为 `"<task-title> (task-<id>)"`，写入 LedgerEntry 含 git SHA。
7. 完整 8 阶段跑通最小示例后，`progress.yaml` 含每个 phase 过渡的 `LedgerEntry`（含 phase/action/timestamp）。
8. `devflow suspend` 写出 `handoff-<phase>.md`，含 `suggested_skills` 段 + **按路径引用**工件（非复制）。
9. `RedLineAuditor` 对故意引入的 `no_test` / `cross_module_import` 样本能检出并列出违规。
10. **CLI 跑通**：`devflow next` / `status` / `gate` / `commit` / `approve` / `resume` / `skip-task` 等命令返回 §6.2 结构的 JSON。
11. `devflow approve <spec-id>` 校验必填字段，通过后 `status→approved`；不通过返回缺失字段清单。
12. `devflow resume` 检测 handoff 文件并恢复阶段状态，输出续接指引。
13. 引擎自身 `tests/` 目录包含 `test_state_machine.py` + `test_models.py` 基础单元测试，覆盖状态转换正/反例和模型必填字段校验。

---

## 5. 实现顺序（里程碑）

> **核心原则**：每个里程碑产出可独立验证的交付物，前一个不通过不开始下一个。

- **M0 脚手架 + 测试骨架**：pyproject + 目录 + `devflow init`（CLI 子命令）+ pydantic 模型（必填字段见 `MVP-门禁降级矩阵.md` §0.1/§0.4）+ `tests/test_models.py`（模型校验单测）+ `tests/test_acceptance.py`（13 条验收测试骨架，初始全部 xfail）。
- **M1 状态机**：`PhaseStateMachine`（含 `approve` 命令的状态转换）+ `SkillResolver` + `Checkpoint`（suspend/resume）+ `tests/test_state_machine.py`（状态转换正/反例）。**验收 3/4/11/12 的测试应在此阶段变绿**。
- **M2 存储与账本**：`FSBackend` + `progress.yaml` append-only 写入 + 多 Spec 活跃状态管理。**验收 1/7 的测试应在此阶段变绿**。
- **M3 CLI 门面**：typer 封装 10 子命令（含 `approve` / `resume`），**端到端跑通验收 1–8, 10–12（CLI 层面）**。
- **M4 门禁与红线**：`GateRunner`（tests_pass/ci_green）+ `RedLineAuditor`（10 条可执行 + 1 条 mvp_skip）。**验收 5/6/9 在此阶段变绿**。
- **M5 WorkBuddy 适配**（可选，CLI 稳定后）：Skill 暴露 `devflow.*`。若时间紧张，CLI 全命令可用即可视为 MVP 完成。

---

## 6. 必读约束（违反即返工）
- **不可跳步**是引擎第一铁律（验收 3/4/6）。`intake_fast_skip` 是 "Stage0 自动判定为 ready-for-agent"，**不是跳过 Stage0**——Stage0 的工件产出和账本记录仍然发生。
- 账本以 **commit 为真实源、账本为镜像**：`commit` 成功后才 `append_ledger`。
- **MVP 账本简化**：`progress.yaml` 采用 append-only 日志（每次 `append_ledger` 追加一条 YAML 文档），不做内容寻址哈希。完整的 CCR-first 落盘留到 v0.2。
- **`devflow commit` 语义**：通过门禁后执行 `git add -A && git commit`，写入 LedgerEntry 含 git SHA。详见 `MVP-门禁降级矩阵.md` §0.3。
- **多 Spec 管理**：引擎维护 `current_spec_id`，`devflow start` 自动设为活跃 Spec，`devflow next/status/gate/commit` 均操作当前活跃 Spec/Plan。详见 `MVP-门禁降级矩阵.md` §0.6。
- **suspend/resume**：`devflow suspend` 写 handoff 文件 + 记录 suspend 状态；`devflow resume` 恢复阶段状态；`devflow next` 在有 suspend 记录时行为等同 resume。详见 `MVP-门禁降级矩阵.md` §0.7。
- **skip-task**：仅允许跳过 `todo` 或 `contracted` 状态的 task；已进入实现阶段的 task 不可 skip，需先清理工作区。所有 task 均为 done/skipped 时 Stage4/Stage5 的门禁自动通过（无代码变更 = 无测试失败）。详见 `MVP-门禁降级矩阵.md` §0.5。
- **SOP 版本协商**：`sop.yaml` 含 `sop_version` 字段，引擎校验版本兼容性，未知字段 warning，必需字段缺失 error。详见 `MVP-门禁降级矩阵.md` §0.8。
- Windows 测试前剥离 `HTTP_PROXY`/`HTTPS_PROXY`（`sop.yaml` 已 `proxy_strip:true`）。
- 伴侣仓库 caveman 的 **BSL-1.1 引擎/代理代码禁止复制进本项目**；其设计思想（CCR 不可变、detect 路由、Skill+MCP 双集成面）可借鉴。
- ponytail（MIT）理念可直接落进 Stage4/账本，但 MVP 不接线 `overbuild_check`。
- **MVP 不做高级特性**：DAG 环检测、tracer-bullet 垂直切片、SDD 子代理派发、双轴评审、ADR 维护均留到 v0.2+。MVP 的 `Task.blocked_by` 简化为列表字段（不校验环），`DomainModel` 简化为 CONTEXT.md 骨架（不含 ADR）。

---

## 7. 端到端 demo（验收 7 的最小示例）

```
$ devflow init
  → 生成 sop.yaml, specs/, plans/, progress.yaml, CONTEXT.md
$ devflow start "为 pipeline 增加 batch 重试"
  → specs/20260819-pipeline-batch-retry.yaml (status=draft)
  → Intake 自动创建 (triage_state=ready-for-agent, intake_fast_skip=true)
  → LedgerEntry(phase=0, action=triage)
$ devflow next
  → "Stage1 brainstorm：请完善 Spec，当前缺失：non_goals"
  → 拒绝进入 Stage2（验收 3）
$ devflow approve 20260819-pipeline-batch-retry
  → 校验必填字段 → 通过 → status=approved
  → LedgerEntry(phase=1, action=approve)
$ devflow next
  → "Stage2 plan：请产出 Plan，包含至少 1 个 Task（需有 module + acceptance）"
$ (创建 Plan, 含 task-1: module=pipeline, acceptance=["重试 3 次后成功"]）
$ devflow next
  → "Stage3 contract：为 task-1 产出 Contract（module + interface_signature）"
$ (创建 Contract)
$ devflow next
  → "Stage4 implement：实现代码变更"
$ (写代码, git status 非空)
$ devflow next
  → 自动执行 tests_pass gate
  → "Stage5 verify：tests_pass=pass"
$ devflow next
  → 自动执行 ci_green gate + 自查清单
  → "Stage6 review：ci_green=pass, 自查清单无问题"
$ devflow commit task-1
  → Stage5/6 门禁通过 → git add -A && git commit
  → LedgerEntry(phase=7, action=commit, commit=<sha>)
  → task-1 status=done
$ devflow next
  → "Stage7 finish：账本完整，所有 task done → 工作流完成"
$ cat progress.yaml
  → 含 intake→brainstorm→plan→contract→implement→verify→review→finish 的全链路 LedgerEntry
```

---

## 8. 参考文件
- `MVP-门禁降级矩阵.md` —— **门禁权威**：逐阶段出口条件、必填字段、CLI 命令语义、测试策略
- `开发工作流引擎架构文档.md` —— 完整设计（§0–§16），v1.0 愿景
- `sop.yaml` —— 本 MVP 的可加载配置实例
