# DevFlow —— 方案驱动开发工作流引擎 · 架构文档

> 定位：一个**被 AI Agent 调用的跨平台插件**，把 ruflo-kb 的实践 SOP 提炼为可复用的「方案驱动开发工作流引擎」。
> 状态：设计蓝图（v0 架构），用于指导工具实现。
> 参考实例：`D:\5-Project\2026814\llm-wiki-base`（ruflo-kb，其 `PROJECT_SOP.md` / `CLAUDE.md` / `docs/superpowers/` 是本文所有抽象的事实来源）。

---

## 0. 决策记录（基于本次需求澄清）

| 维度 | 决策 | 理由 |
|---|---|---|
| 工具形态 | **Agent 可调用插件**（跨平台接入层 + 平台无关引擎） | 用户明确："希望作为插件被 agent 调用"；呼应其 Graphify 跨平台统一调用的诉求 |
| 覆盖范围 | **通用 spec-driven 引擎**（ruflo-kb SOP 作为配置实例） | "抽取出来做开发工具" → 复用性优先；引擎原语通用，SOP 只是配置 |
| 实现语言 | Python（引擎内核）；接入层按平台用各自原生方式（skill/command/MCP） | 贴合 ruflo-kb 的 Python 3.11+ 生态，且与 WorkBuddy 运行时一致 |
| 存储 | 文件系统 + git 追踪（`specs/` `plans/` `progress`），抽象为可插拔后端 | 与现有 `.superpowers/sdd/progress.md` 账本形态对齐，零额外依赖 |

---

## 1. 定位与目标

**DevFlow** 不是又一个任务管理器，而是一个**强制执行「先理解→再计划→契约先行→验证→评审→收尾」纪律的工作流引擎**，并以插件形式让 AI 编码 Agent 在任意平台上都能按同一套流程工作。

设计目标：

1. **流程不可跳过（No-Skip Enforcement）**：未产出现阶段工件，引擎拒绝进入下一阶段、拒绝提交。
2. **契约先行（Contract-First）**：每个任务在编码前必须有接口/类型定义与测试（TDD）。
3. **账本可审计（Auditable Ledger）**：每个阶段、任务、commit、验收结果都落盘成结构化账本。
4. **平台无关（Platform-Agnostic）**：引擎内核不依赖任何特定 Agent；Claude Code / CodeBuddy / WorkBuddy 各写一层薄适配。
5. **配置驱动（Config-Driven）**：具体 SOP（如 ruflo-kb 的七阶段 + 红线）通过配置文件注入，引擎本身通用。

---

## 2. 设计原则

| 原则 | 含义 | ruflo-kb 出处 |
|---|---|---|
| 禁止跳步 | 阶段严格有序，前置工件缺失则阻断 | `PROJECT_SOP.md` "强制遵循流水线，禁止跳步开发" |
| 模块边界硬约束 | 外部只 import facade/类型，禁导入内部实现 | `PROJECT_SOP.md` 第三章；`CLAUDE.md` 导入禁令 |
| 单人自评审 | 无同事评审时用清单替代 | `PROJECT_SOP.md` 第六章 |
| 文档随码同步 | 接口变更同步更新文档 | `PROJECT_SOP.md` 第九章 |
| 备份优先 | 破坏性改动前先 `cp` 到时间戳目录 | `Phase4状态修复方案.md` 第三章 |
| 诚实标注遗留 | 未达标项挂账记录，不隐瞒 | `Phase4完成度核对.md` 第六节 |

---

## 3. 系统架构（分层）

```
┌─────────────────────────────────────────────────────────────┐
│                  接入层 (Platform Adapters)                   │
│  WorkBuddy Skill │ Claude Code Command/Hook │ CodeBuddy Skill │
│            统一门面：devflow CLI / MCP Server / Tool Schema   │
└───────────────────────────┬─────────────────────────────────┘
                            │ 调用
┌───────────────────────────▼─────────────────────────────────┐
│                  编排引擎 (Orchestration Engine)               │
│  PhaseStateMachine │ SkillResolver │ Checkpoint │ RedLineAuditor│
└───────────────────────────┬─────────────────────────────────┘
                            │ 读写
┌───────────────────────────▼─────────────────────────────────┐
│                  领域模型 (Domain Model)                      │
│  Spec │ Plan │ Task │ Contract │ QualityGate │ LedgerEntry │ DomainModel │ Intake │
└───────────────────────────┬─────────────────────────────────┘
                            │ 持久化
┌───────────────────────────▼─────────────────────────────────┐
│              存储与验证 (Storage & Verification)               │
│  FS Backend(git) │ TestRunner │ GateRunner │ Linter/CI Hook  │
└─────────────────────────────────────────────────────────────┘
                            ▲
                            │ 读取
┌─────────────────────────────────────────────────────────────┐
│              策略配置 (Policy / SOP Config)                   │
│  sop.yaml：阶段定义 / 质量阈值 / 红线 / 命令模板              │
└─────────────────────────────────────────────────────────────┘
```

引擎内核 = 编排引擎 + 领域模型 + 存储/验证，**不含任何平台特定代码**。

---

## 4. 核心领域模型

所有模型为纯数据 + 不变量（invariant），无 IO 副作用，便于测试与序列化。

### 4.1 Spec（方案）
```yaml
Spec:
  id: string                 # 2026-08-26-module-standardization
  title: string
  problem: string            # 要解决的问题
  goals: [string]            # 目标（可验收）
  non_goals: [string]        # 明确不做（防范围蔓延）
  options:                   # 可选方案对比
    - id, summary, risks, compat
  decision: string           # 选定方案 + 理由
  affected_modules: [string] # 影响的模块/包
  contracts: [Contract]      # 对外契约草案
  status: draft|approved
```

### 4.2 Plan / Task（计划 / 任务，Tier1 升级为 DAG + tracer-bullet）

> 来源：mattpocock `to-tickets`。原 `depends_on` 线性依赖升级为 **`blocked_by` DAG**，并强制 acceptance criteria 与 tracer-bullet 垂直切片；宽重构用 expand–contract 时序。

```yaml
Plan:
  spec_id: string
  tasks: [Task]
  domain_ref: string          # 指向 DomainModel（CONTEXT.md/ADR），切片用语须对齐

Task:
  id: string                 # task-3
  title: string
  module: string             # 单任务只改一个模块
  blocked_by: [string]       # 前置任务（DAG 依赖边，替换原线性 depends_on；须无环）
  is_tracer_bullet: bool     # 是否为贯穿各层的垂直切片：窄而完整、单窗口可完成、可独立验证
  contract: Contract         # 接口/类型 + 测试路径（契约先行）
  acceptance: [string]       # 验收标准（用户视角的端到端行为，非逐层实现清单）
  status: todo|contracted|implementing|verifying|reviewing|done
  commits: [string]          # 关联 commit（one commit per task）
  wide_refactor: bool        # 宽重构标志：机械改动横跨全代码库，无法单切片绿
```

**切片规则**：
- *Tracer-bullet*：每个切片切穿所有层（schema→API→UI→tests），完整可演示；尺寸适配单 fresh 上下文窗口；优先 tracer-bullet，再沿 frontier（所有 `blocked_by` 已 done 的任务）并行。
- *宽重构（wide_refactor=true）*：单一机械改动（改名/改类型）爆炸半径覆盖全库，无法单切片绿。改用 **expand–contract**：① expand 在旧形旁加新形（不破坏）；② 按爆炸半径分批迁移调用点（每批一个 task，`blocked_by=expand`），批量保 CI 绿；③ contract 在所有调用点迁移完后删除旧形（task `blocked_by`=所有 migrate 批）。

### 4.3 Contract（契约，TDD 核心）
```yaml
Contract:
  module: string
  interface_signature: string   # 入参/返回/异常类型签名
  test_path: string             # 测试文件（先于实现存在）
  invariant: string             # 行为零变更等约束
```

> **Seam 与反模式（Tier2 来自 `tdd`）**：Contract 划定的是模块的**预约定公共边界（seam）**——测试只应钉在 seam 上，验证对外契约，而非刺穿内部实现。三条反模式须避免：① **实现耦合测试**（断言内部私有细节，实现一改测试即碎）；② **同义反复测试**（只是重述实现而非验证行为，fake 永远绿）；③ **水平切片任务**（把"改 model 层""改 UI 层"拆成独立 task，破坏 §4.2 的垂直切片）。另：**重构不属于红绿循环**——纯重构归 `review` 阶段（§9）处理，不计入 `contract`/`implement` 的"先红后绿"，避免把重构伪装成功能交付。

### 4.4 QualityGate（质量门禁）
```yaml
QualityGate:
  name: string              # 如 "tests_pass" / "lint_clean" / "ci_green"
  command: string           # 实际执行命令（可配置）
  threshold: any            # 通过阈值
  blocking: bool            # 是否阻断进入下一阶段
```

### 4.5 LedgerEntry（账本条目）
```yaml
LedgerEntry:
  phase: int                # 0-7（0 = Stage0 intake 入口，见 §5.0）
  task_id: string
  action: string            # start|artifact|gate|commit|debug|ruling
  commit: string
  acceptance: string        # 验收结论
  timestamp: datetime
  debt: DebtRef | null      # 刻意简化债务（ponytail: 标记），见 §15.8
  ruling: RulingRef | null  # 运行期自主裁决记录（obra SDD），见 §5.2.1
```
聚合即为 `progress.md` 背后的结构化账本。

> **工件不可变性（借鉴 caveman 的 CCR 原则）**：DevFlow 的账本与领域工件（Spec/Plan/Task/Contract/LedgerEntry/CONTEXT.md/ADR）均为**内容寻址、字节级可恢复**的不可变记录，遵循三条安全规则——① **CCR-first**：任何有损变换（压缩/摘要）前，原字节落盘内容寻址存储；解析失败或变大则回退原字节；② **Visible declines**：仅当实测更小才执行变换，且声明原因；③ **Labeled evidence**：压缩/推断结果本地标 `inferred`，真实流量+评估门控验证后才标 `verified`。这一原则直接落地为 §4.5 / §4.6 的工件持久化约束，确保 DevFlow 账本在任何时候都能 byte-exact 复原（对应跨设备续接、审计回溯）。

> **刻意简化债务追踪（借鉴 ponytail 的 `ponytail:` 标记）**：DevFlow 允许在代码中以 `ponytail:` 前缀注释标记"为极简而刻意走的近路"（如省略的抽象、临时硬编码），此类债务须录入账本作为 `LedgerEntry.debt` 子类型（见上），与 §2「诚实标注遗留」原则合一——极简不等于隐瞒，简化须可追溯。

### 4.6 DomainModel（领域模型 / 共享语言，Tier1 新增）

> 来源：mattpocock `domain-modeling` + `grill-with-docs`。DevFlow 原缺失"共享语言"层，导致各阶段词汇漂移、设计决策无沉淀。

```yaml
DomainModel:
  glossary_path: CONTEXT.md      # 项目领域术语表，所有阶段执行前先读
  adrs: [ADR]                   # 架构决策记录，进入受影响模块前须尊重既有 ADR
  updated_by: [grill-with-docs, domain-modeling]  # 写入方
```

- **CONTEXT.md**：项目领域词汇表（模块名、概念、边界），作为各阶段的"项目词典"；`tdd` / `diagnosing-bugs` / `code-review` 等阶段读取它以对齐命名与接口词汇。
- **ADR（Architecture Decision Record）**：关键架构决策的不可变记录；进入受影响模块的阶段前须先读相关 ADR，避免推翻已达成共识的设计。
- 不变量：阶段工件（Spec/Plan/Task 文案）须使用 `CONTEXT.md` 中的领域词汇；新增术语/决策落地时同步更新 `CONTEXT.md` 与（必要时）ADR。
- **ADR/术语表的可恢复性（借鉴 caveman CCR）**：`CONTEXT.md` 与每条 ADR 也按内容寻址存储，旧版本可回溯；对 ADR 的"推翻/修订"须新建 ADR（不就地改写历史），与上方 CCR-first 原则一致（详见 §15.7）。
- **设计词典（Tier2 来自 `codebase-design`）**：DevFlow 复用一组共享设计词汇作为各阶段的"设计语言"，被 `tdd` / `review` / `implement` 引用——`seam`（预约定公共边界，只在此处钉测试）、`adapter`（在边界处转换，隔离外部依赖）、`locality`（相关变更尽量聚拢同处，降低扩散）、`leverage`（用既有抽象/依赖撬动需求，而非新造）。它是对 §2「模块边界硬约束」的词汇化补充，写 Spec/Contract 时应优先使用这些词对齐设计意图。

### 4.7 Intake / Issue（入口议题，Tier2 新增，来自 `triage`）

> 来源：mattpocock `triage`。DevFlow 此前只有"进入 Stage1 brainstorm"一条入口，缺少对外部 issue/PR/需求碎片的前置分流。新增 `Intake` 实体，在 brainstorm 之前先完成**分类与可处理性判定**。

```yaml
Intake:
  id: string                 # issue-<n>
  kind: bug|enhancement|question|chore
  summary: string
  triage_state: needs-triage|needs-info|ready-for-agent|ready-for-human|wontfix
  blocked_reason: string?    # needs-info / wontfix 时的说明
  devflow_stage: 0           # 入口阶段，决定是否进入 Stage1
```

**Triage 状态机**（进入 Stage1 前必经）：
`needs-triage` →（信息不足）`needs-info`（向人类追问）→（补全后）回 `needs-triage` →（判定）`ready-for-agent`（可走七阶段流水线）/ `ready-for-human`（需人类专属操作，见 §5.4 wizard 门禁）/ `wontfix`（记录原因归档，不进流水线）。

- `kind` 分类直接影响后续：`bug` 在 verify 失败时会进入 §5.1 Debug 循环；`enhancement` 走完整七阶段；`question/chore` 可能不需 Spec。
- 双门禁直接对应 `triage` 的 `ready-for-agent` / `ready-for-human`：前者引擎自动推进，后者经 `wizard` 生成交互式 bash 向导交由人类（详见 §5.4、§7）。
- 不变量：`enter(Stage1)` 需 `Intake.triage_state == ready-for-agent`；`ready-for-human` 的议题不在引擎内闭环。

---

## 5. 阶段状态机（SOP 七阶段建模）

引擎把 `PROJECT_SOP.md` 的七阶段编码为 **Stage**，每个 Stage 有：入口条件、要调用的能力（skill/command）、必产工件、出口门禁。**每个 Stage 执行前先读取 `DomainModel`（CONTEXT.md/ADR）以对齐项目词汇与既有决策（Tier1 新增，见 §4.6）。**

### 5.0 入口：Intake 与 Triage（Tier2 新增，来自 `triage`）

在七阶段流水线**之前**，所有外部议题先经 `Intake` 分流（实体定义见 §4.7）：判定 `kind`（bug/enhancement/…）、走完 triage 状态机、确认 `ready-for-agent` 后才进入 Stage1。`ready-for-human` 议题不进流水线，由 §5.4 的 wizard 门禁承接；`wontfix` 归档。这一步把"需求模糊先停手"从原则落成引擎强制的前置闸门。

| 阶段 | Stage | 调用能力 | 必产工件 | 出口门禁 |
|---|---|---|---|---|
| 0 | `intake` | `triage` | `Intake`（triage_state 判定） | `triage_state == ready-for-agent` 方可进 Stage1 |
| 1 | `brainstorm` | brainstorming + `grill-with-docs`/`domain-modeling` | `Spec`（approved）+ `CONTEXT.md`/ADR 维护 | Spec 必填字段齐 + non_goals 非空 |
| 2 | `plan` | writing-plans + `to-tickets` | `Plan`（DAG 化 tasks） | 每 task 单模块、`blocked_by` 无环、有 `acceptance`、优先 tracer-bullet |
| 3 | `contract` | executing-plans（test-first） | 每个 task 的 `Contract` + 测试文件存在 | 测试文件存在且可收集 |
| 4 | `implement` | executing-plans + `implement` + 偷懒阶梯前置判定 | 代码 + commit | 无未提交调试码；安全/校验门禁不被极简砍掉 |
| 5 | `verify` | verification-before-completion + `diagnosing-bugs` | 测试报告（+ `DebugSession` 若有调试） | `tests_pass` gate 通过 |
| 6 | `review` | `code-review`（双轴） | 双轴报告（Standards×Spec） | 双轴均 PASS |
| 7 | `finish` | finishing-a-development-branch | 文档同步 + CI | `ci_green` + 文档已更新 |

**Stage1 三路径路由（obra `brainstorming`）**：Stage1 在动手前先**分类请求性质**并"大声"宣告，再走对应路径，但**批准门槛永不缩放（HARD-GATE：任何路径、任何简易度，都必须先告知意图并获人类批准，才可调用实现技能 / 写码 / 脚手架）**：
- **Spike**（可行性："能不能…"）：输出是答案而非保留代码；2–3 句呈现探针计划、点头即可，构建物标 `throwaway`。
- **Bounded**（对本仓库已有代码的明确修改，须有现有流程可读）：聊天式短设计、显式 yes 后实现，无 spec 文件。
- **Architectural**（新项目 / 子系统 / 改组件关系接口）：完整流程——提问 → 2–3 方案 → 分节设计 → 书面 Spec → `writing-plans`。
- **路由纪律**：疑则取更重路径；任务中现隐藏复杂性 → **只升不降**（回分类节点）；每任务独立分类与批准（批准不跨任务继承）；spike 代码若想保留即视为新请求须重分类。这与 §5.0 Intake 闸门（bug/enhancement 分类）正交——Intake 判"要不要进流水线"，三路径判"进流水线后怎么干"。

**提交风格（借鉴 caveman `/caveman-commit`）**：`finish` 阶段（Stage7）的提交采用**单行可操作的 Conventional Commit**（如 `feat(module): 简短描述`），杜绝冗长提交信息——这与 caveman 的紧凑提交风格一致，也便于账本 `LedgerEntry.commit` 对齐可读。

**极简主义护栏（借鉴 ponytail「偷懒阶梯」）**：`implement` 阶段（Stage4）在落码前须先走"偷懒阶梯"判定——是否真的需要存在 → 是否已存在 → 用标准库 → 用原生能力 → 用已装依赖 → 能否一行 → 最后才写最小可用代码。它与 contract-first **互补**（契约定 WHAT，阶梯约束 HOW MUCH），直接补上 DevFlow 此前缺失的"反过度工程"护栏；但**安全地板不可砍**：校验、错误处理、安全、无障碍不得因极简而被删减（对应 §9 不可跳过门禁）。极简强度可由 `sop.yaml` 的 `minimalism_strictness`（lite/full/ultra，见 §10）配置。

**状态机不变量**：
- `enter(Stage[i])` 需 `Stage[i-1].exit_gate == PASS`（i>1）。
- `commit(task)` 需 `Stage[5].gate` 与 `Stage[6].gate` 均 PASS。
- 任意阶段可挂起（suspend）写 handoff，恢复时从账本续接（对应 `.memory/handoff-*`）。

### 5.1 Debug 循环（Tier1 新增，来自 `diagnosing-bugs`）

当 `verify` 出现失败/回归/性能问题时进入 debug 子循环，遵循"反馈环律"——**没有可红（red-capable）命令前不下任何假设**：

1. **建紧致可红反馈环**：先构造一个能稳定复现该问题的命令（失败测试 / curl / CLI fixture / 无头浏览器 / 重放 trace），断言用户确切症状；信号须 deterministic、秒级、可无人值守。
2. **最小化复现**：逐次砍掉输入/调用方/配置/数据，直到最小仍红——缩小假设空间，且成为后续回归测试。
3. **3–5 条可证伪假设**：每条给出预测（"若 X 是原因，则改 Y 会使问题消失"），先给用户过目再测。
4. **单变量埋点**：每条探针对应一个预测；日志打唯一前缀 `[DEBUG-xxxx]`，清理时一次 grep 即可清除。
5. **先回归测试后修复**：把最小化复现转成失败测试（须在正确 seam 上）；无正确 seam 则记录为架构阻塞，而非假绿。
6. **清理**：原复现不再出现、`[DEBUG-*]` 埋点全清、结论写入 commit/PR。

> **四阶段增强（obra `systematic-debugging`）**：上面的"反馈环律"进一步被 obra 的**四阶段根因法**结构化——① **根因调查**（读全错误 / 稳定复现 / 查近期变更 / 多组件时在边界插桩取证 / 逆向追踪数据流）；② **模式分析**（找同类可工作代码、逐差异比对、理清依赖）；③ **假设与验证**（单一可证伪假设、最小变更单变量测、写清"我认为 X 因 Y"）；④ **实现**（先写失败测试再单点修复、验证无回归）。**关键纪律**：连续 3+ 次修复失败且每修一处冒出新问题 → 停止"再试一次"，**质疑架构本身**而非继续打补丁（obra 称其为"错的是架构而非假设"）。配套技术：`root-cause-tracing`（沿调用栈逆向追源）、`defense-in-depth`（根因修复后在多层加校验）、`condition-based-waiting`（用条件轮询替任意超时）。该四阶段法是 DevFlow `debug` 能力的权威实现，覆盖 §5.1 全部 6 步。

不变量：debug 不阻断阶段机推进，但 `DebugSession` 结论须进账本（`LedgerEntry.action=debug`）。

### 5.2 Implement 编排循环（Tier2 来自 `implement`）

`implement` 阶段（Stage4）不只是一个"写代码"动作，而是一条**显式编排链**（对应 `executing-plans` 的具体化），在每个 task 上循环推进，直到可提交：

1. 在 `Contract` 划定的 **seam** 上按 TDD 红绿（§4.3 / §5.3 的 tdd 纪律）落地最小实现；
2. 常跑**类型检查 + 单测**（增量，秒级反馈），保持 green；
3. 收尾跑**全量测试 + 门禁**（§9 GateRunner）；
4. 进入 `review`（§9.1 双轴 + §9.3 过度工程检测）；
5. `commit(task)`（§5 S7 单行 Conventional Commit）。

> 与 §5 极简护栏（ponytail）叠加：第 1 步落码前先走"偷懒阶梯"；第 3 步的 `tests_pass` / `ci_green` 门禁**不被极简砍掉**（§9 P2 安全地板）。

### 5.2.1 SDD 执行模式（来自 obra `subagent-driven-development`，#1/#5/#7）

`implement` 阶段（Stage4）的"编排链"（§5.2）在**多任务 / 长程**场景下，进一步落成为 **Subagent-Driven Development（SDD）** 运行时——这是 obra 对 DevFlow 最大的补完，把"实现"从"主代理自己写"变成可审计的子代理编排：

1. **每任务派发全新子代理（隔离上下文）**：每个 task 派一个 fresh implementer，不继承主会话历史；主代理仅构造其所需精确指令与 context（brief 路径、早期任务接口 / 决策、歧义决议、report 路径）。**不变量：子代理禁止再派子代理（no-subagents contract）**；主代理自身不写修复代码（保上下文干净、跳过 review 是缺陷）。
2. **两阶段任务审查（spec compliance + code quality）**：每个 task 实现后**必须**双 verdict——① Spec 符合性（是否忠实实现 Spec/Contract）；② 代码质量（是否引入坏味道 / 坏模式）。implementer 自检**不能**替代。最终整体审查（全分支 diff）用最强模型派发，指向 ledger 中 deferred / parked 行。
3. **Plan-scoped workspace（计划范围工作区）**：每 plan 拥有独立目录（如 `.superpowers/sdd/<plan>/`，git-ignored），存 ledger / briefs / reports / review-packages；跨 plan 不互读；完成后删本 plan 目录（兄弟不动）。这把 §8 的通用存储收束为"每计划隔离 + 结束即弃"的强约束。
4. **修复循环 + 回路断路器（Circuit Breaker）**：review 报 spec ❌ / Critical / Important 发现 → 进入修复：① 轮次 1–3 恢复**原始 implementer**（同一 agent）发 open findings；② 轮次 4–5 派发**全新 implementer + 更强模型**，框架 "prior attempted N times; you own it"；每轮修复后跑**范围化重审查**（只验证 findings ADDRESSED / NOT ADDRESSED）。**第 5 轮仍 open → 断路器触发**：停止派发，主代理亲自裁决（评审错 → park；真实但无下游依赖 → park；真实且 load-bearing → 裁决最小变更带入下任务；仅当"所有前进路径都是猜"才停）。
5. **Never-stall 自主裁决（Rulings）**：运行期计划冲突 / 歧义 / 计划缺陷 / 超限 → 主代理**自主裁决并继续**（不暂停问人），每条裁决写账本 `LedgerEntry.action=ruling`：`Ruling: <决定> — <原因> — <错代价>`。**仅四类硬停**：① 不可逆 / 破坏性操作；② 安全敏感动作；③ worktree 外副作用（merge / push 共享分支 / publish）；④ 计划破碎到所有路径都是猜。其余一律决定并继续，且最终消息须汇总所有 `Ruling:` 行供人复核。
6. **Model 选型 / 升级（#7）**：机械任务用最廉价模型、集成 / 判断用标准、架构用最强；修复轮次 4–5 升级模型。派发须显式指定 model，遗漏则继承最贵模型（反模式）。该配置写入 `sop.yaml` 的 `model_tiers`（见 §10）。
7. **并行派发（frontier，#3）**：当多个 task 处于 `blocked_by` 已 done 的 frontier 且**独立无共享状态**时，可在同一响应中批量派发多个 implementer（对应 §4.2 的 frontier 并行）；相关 / 共享状态任务则顺序派发（借鉴 obra `dispatching-parallel-agents`：一代理一独立域、同响应批派 = 并行、派发须聚焦 + 自包含 + 带约束 + 明确输出）。

> **Worktree 隔离（obra `using-git-worktrees`，#9，可选）**：SDD 的 plan-scoped workspace 可进一步落在 git worktree 上——每 plan 建隔离分支 workspace、禁止在 main / master 直接实现、开始前进前校验**干净测试基线**（确保后续"全量绿"可证）。DevFlow 默认用目录隔离（§8），worktree 作为大型 / 多分支项目的可选强化。

### 5.3 计划与调研扩展（Tier2 来自 `wayfinder` / `prototype` / `research` / `grill-me`）

- **大型 effort 的决策地图（`wayfinder`）**：当 `plan` 阶段（Stage2）识别到工作量超大、无法拆成单切片时，先产出一张"决策 ticket 共享地图"——把待定的架构/范围决策显式列为 ticket，供人类先拍板，再据此拆 `Task` DAG。避免 agent 在不确定方向上盲目推进。
- **原型验证（`prototype`）**：`brainstorm` 阶段（Stage1）对拿不准的设计问题，允许产出一个**一次性、可弃**的 HTML 原型（如交互流、数据模型可视化）来对齐认知，不进账本、不进交付。
- **引文式调研（`research`）**：`plan` 阶段需外部事实支撑时，调用 `research` 产出带引用的 Markdown（高信任源），作为 `Spec`/`Plan` 的依据，引用一并入 Spec。
- **盘问对齐（`grill-me` + `grilling` 原语）**：对非代码向的方案/设计，`brainstorm` 阶段用盘问访谈技术逼出隐含假设与边界，与 `grill-with-docs`（§4.6）共用同一"盘问对齐"原语。

### 5.4 Finish 子流程与 Handoff 增强（Tier2 来自 `resolving-merge-conflicts` / `wizard` / `handoff`）

- **冲突解决流程（`resolving-merge-conflicts`）**：`finish` 阶段（Stage7）若遇 git merge/rebase 冲突，按**逐 hunk** 流程处理——每个冲突块单独判定保留哪侧/手工合，禁止整文件选择；处理完跑全量测试确认无回归再继续。
- **人工门禁向导（`wizard`）**：对应 `Intake.triage_state == ready-for-human` 的议题（§4.7 / §5.0），引擎生成**交互式 bash 向导**，把人类专属操作（如生产环境发布、密钥轮换）步骤化，由人类执行并回填结果，引擎不代行。
- **Handoff 增强（`handoff`）**：`suspend`（§6 `devflow.suspend`）产出的交接文档增加两段——① **suggested skills**：列出续接 agent 应加载的能力（如 debugging / code-review）；② **按路径引用既有工件**（Spec/Plan/ADR/commit），而非复制内容，避免交接文档与实际工件漂移。交接文档落 `handoff-<phase>.md`（§8）。
- **Bootstrap 重注（obra `using-superpowers`，#11）**：长会话经上下文压缩（compaction）后会丢失技能注入状态，导致技能不再自动触发。DevFlow 在 `suspend` / `resume` 与 SessionStart 钩子中设**重注点**——恢复时重新注入 `using-devflow` bootstrap（等价于 §6 的双集成面加载），确保跨压缩 / 跨会话技能持续生效。这与 §4.6 DomainModel 的"跨会话续接"、本小节 handoff 共同构成 DevFlow 的连续性保障。

---

## 6. Agent 调用接口

插件向 Agent 暴露一组**结构化工具**（JSON in / JSON out），Agent 据此决定下一步动作。

> **双集成面（借鉴 caveman 跑通 30+ agent 的经验）**：DevFlow 的 Agent 调用接口**必须同时以两种形态暴露**——① **Skill 形态**（供 WorkBuddy/CodeBuddy/Claude Code 技能系统加载）；② **MCP Server 形态**（供任意 MCP Host 调用 `devflow_*` 工具）。两者共享同一引擎内核，仅适配层不同。这一"Skill + MCP"双集成面是 DevFlow 实现跨平台一致调用的关键（详见 §7 与 §15.7）。

### 6.1 工具清单
| 工具 | 输入 | 输出 |
|---|---|---|
| `devflow.start(spec_draft)` | 需求草稿 | `Spec` 模板 + 进入 Stage1 指引 |
| `devflow.next()` | 当前上下文 | 下一允许动作 + 应调用 skill + 必产工件 |
| `devflow.status()` | — | 当前阶段、阻塞项、账本摘要 |
| `devflow.gate(phase)` | 阶段号 | 各 QualityGate 结果（pass/fail/挂账） |
| `devflow.commit(task_id)` | task_id | 先跑门禁，全过则执行提交，否则返回阻断原因 |
| `devflow.audit()` | — | 红线违规清单（跳步/无测试/超大 PR 等） |
| `devflow.suspend(handoff)` | 交接笔记 | 账本落盘 + handoff 文件 |

> **意图路由（Tier2 来自 `ask-matt`）**：`SkillResolver`（编排引擎组件，见 §3 架构图）不只做线性推进——`devflow.next()` 先解析**用户意图**，再路由到对应能力，而非一律返回"下一步阶段动作"。意图识别覆盖：进入新 Spec、续接挂起、追问澄清、调试回归、人工决策采集等；无法归类时回退到"确认意图"而非盲目执行。这补上了原 `next` 只能线性推进、缺意图识别的短板（详见 §15.2 #1）。

### 6.2 调用流（Agent 视角）
```
Agent 收到需求
  → devflow.start(draft)         # 生成 Spec
  → devflow.next() → "请调用 brainstorming 完善 Spec"
  → ...（逐阶段）...
  → devflow.next() → "Stage3：先为 task-X 写 Contract + 测试"
  → 实现后 devflow.gate(5)/gate(6)
  → devflow.commit(task-X)       # 门禁不过则被拒，返回原因
```

返回结构示例：
```json
{
  "current_phase": 3,
  "allowed_action": "write_contract",
  "invoke_skill": "executing-plans",
  "required_artifact": "tests/test_pipeline/test_task_x.py",
  "blockers": [],
  "ledger_tail": [ {"phase":2,"task_id":"task-3","action":"plan","commit":"c4d50dee"} ]
}
```

---

## 7. 跨平台适配层

引擎内核平台无关；每个平台一层薄适配，把原生交互翻译成 `devflow.*` 调用。

| 平台 | 适配形式 | 接入点 |
|---|---|---|
| **WorkBuddy** | Skill + MCP tool | `Skill` 加载 SOP 技能 → 调用 `devflow.*`；或 MCP server 暴露工具 |
| **Claude Code** | `CLAUDE.md` 指引 + Slash Command + Hook | `/devflow-next` 命令；`pre-commit`/`post-edit` hook 触发 `audit()` |
| **CodeBuddy** | Skill / Command | 同 WorkBuddy 思路，按 CodeBuddy 技能规范封装 |

适配层职责仅：① 解析平台原生请求；② 调引擎；③ 把 JSON 结果渲染回平台话术。

> **人工门禁与决策采集（Tier2 来自 `wizard` / `to-questionnaire`）**：当议题被 `triage` 判为 `ready-for-human`（§4.7）或需人类拍板时，适配层负责把引擎生成的 bash 向导 / Markdown 问卷（`to-questionnaire` 把决策转成可发给特定人的问卷）渲染到对应平台的原生交互（如 Claude Code 的交互式 prompt、WorkBuddy 的表单），并回填结果驱动引擎继续。这一类"人类专属步骤"是 DevFlow 流水线在 Agent 自主权之上的必要安全阀。

> **适配层设计借鉴自 `caveman`（一套核心 + 多平台薄适配，跑通 30+ agent）**，三条经验落地为 DevFlow 适配层约束：
> 1. **平台能力探测（capability probing）**：适配器接入新平台时先 `detect()` 其可承接的能力类型（`Skill` / `Command` / `Hook` / `MCP`），再路由到对应集成面——与 caveman `detect()` 按负载类型路由压缩器的思路同构（亦对应 §4.5 工件不可变性的"分类路由"）。
> 2. **Skill + MCP 双集成面**：DevFlow 的 Agent 调用接口（§6）必须同时以 Skill 与 MCP Server 两种形态暴露，这是覆盖 Claude Code / CodeBuddy / WorkBuddy 及任意 MCP Host 的关键（caveman 借此跑通 30+ agent）。
> 3. **运行时 sidecar（部署级，非引擎级）**：DevFlow Agent 的流量**可选**经 `caveman Proxy` 压缩以省 token（见 §15.7）；但 caveman 的 Engine/Proxy 为 **BSL-1.1 许可（非 OSI 开源，2030 或发版 4 年后转 Apache-2.0）**，**禁止将其代码 vendoring 进 DevFlow 引擎**，仅可作部署期 companion（sidecar）使用。

> **适配层范式再印证（ponytail，MIT）**：`ponytail` 以规则文件/插件/钩子覆盖 **20 种 Agent 宿主**（Claude Code / Codex / Copilot / Gemini / Qoder / OpenCode / Hermes…），与 caveman 的 30+ agent 矩阵共同验证 §7 的核心约束——**一套平台无关核心 + 各宿主薄适配**是 DevFlow 适配层最稳健的形态。ponytail 为 MIT，可自由借鉴其宿主适配清单与强度模式（lite/full/ultra/off），无 caveman 的 BSL-1.1 红线顾虑（详见 §15.8）。

> **多 harness 打包范式（obra/superpowers，MIT）**：obra 以**一套共享技能库 `skills/` + 每宿主薄插件清单**（`.claude-plugin/` `.codex-plugin/` `.hermes-plugin/` `.devin-plugin/`…）支撑 **15+ 平台**（Claude Code / Codex / Cursor / Gemini / Copilot / Devin / OpenCode / Pi / Hermes…），且**明确 "no per-harness skill copies"**——所有平台指向同一技能库，仅清单不同。这把 §7 的"一套核心 + 薄适配"从原则落成**具体打包形态**：DevFlow 的 `adapters/<platform>/` 只放该平台的 manifest / hook，技能逻辑全部在 `src/devflow/` 引擎与共享适配模板中，杜绝每平台副本漂移（详见 §15.9）。

> **Windows 钩子工程注意（obra 经验，#14）**：SessionStart 类钩子在 **Windows 下须用 Git Bash 启动**（避免 cmd / PowerShell 的路径 / 引号问题）；跨平台打包脚本须用 **GNU tar**（非 BSD tar）以保证 `.tar` 兼容。DevFlow 的 `adapters/` 钩子与发布脚本须遵循这两条（对应 §10 `proxy_strip` 的 Windows 环境处理）。

---

## 8. 存储与账本

| 工件 | 路径（默认） | 说明 |
|---|---|---|
| 方案 | `specs/<id>.yaml` | 对应现有 `docs/superpowers/specs/` |
| 计划 | `plans/<id>.yaml` | 对应现有 `docs/superpowers/plans/` |
| 账本 | `progress.yaml` + 渲染 `progress.md` | 对应 `.superpowers/sdd/progress.md` |
| 交接 | `handoff-<phase>.md` | 对应 `.memory/handoff-*` |

存储抽象 `StorageBackend` 接口：`read(entity, id)` / `write(entity, id, data)` / `append_ledger(entry)`。默认 `FSBackend`（git 追踪）；可扩展 `DBBackend`。

> **`devflow init`（借鉴 `setup-matt-pocock-skills` 的"每仓库引导"思想）**：新仓库接入时执行 `devflow init`，生成 `sop.yaml` 模板（默认七阶段 + 红线 + 门禁）+ `specs/` `plans/` `progress.yaml` 骨架目录，并把 `CONTEXT.md` 初始化为领域词典空壳。其 tracker / 标签绑定等 mattpocock 生态特有项由 `sop.yaml` 已覆盖，不照搬。这一引导让"接入即合规"——避免空仓库直接裸奔（详见 §11 目录布局）。

---

## 9. 质量门禁与契约测试

- **GateRunner**：按 `sop.yaml` 中 `quality_gates` 顺序执行命令，比对 `threshold`，产出 pass/fail/挂账（挂账项进账本但不阻断，对应 Phase4 报告的 M12 挂账模式）。
- **契约测试**：Stage3 强制 `Contract.test_path` 存在且可被测试收集器发现；Stage4 实现后回放，确保无回归（对应 `重载函数重构计划.md` 的"契约测试先行"）。
- **RedLineAuditor**：静态扫描仓库，检测 11 条红线（需求不清编码、跳步、破坏模块边界、无测试、大量未提交、main 频繁提交未完成码、接口变更不更新文档、超大 PR 等），输出违规清单。

### 9.1 双轴代码评审（Tier1 新增，来自 `code-review`）

`review` 阶段（Stage6）沿**两条独立轴**对 diff（固定点 `git diff <fixed>...HEAD`，先 `git rev-parse` 校验非空）并行审查，结果**并排呈现、不重排**：

| 轴 | 问什么 | 来源 |
|---|---|---|
| **Standards** | 代码是否符合本仓库文档化规范？ | `CODING_STANDARDS.md` / `CONTRIBUTING.md` + 下方气味基线 |
| **Spec** | 代码是否忠实实现了原始 Spec / issue 要求？ | Spec 文件 / commit 中的 issue 引用 |

- 两轴**并行子代理**执行，互不污染上下文；聚合时**保留双轴分离**（不跨轴挑"最严重"），避免一轴掩盖另一轴。
- 仓库无标准文档时，`QualityGate` 自动启用 **Fowler 12 气味基线**作为默认 Standards 实现：

  > Mysterious Name · Duplicated Code · Feature Envy · Data Clumps · Primitive Obsession · Repeated Switches · Shotgun Surgery · Divergent Change · Speculative Generality · Message Chains · Middle Man · Refused Bequest
  >
  > 规则：① 仓库文档标准优先（可压制某气味）；② 气味均为"带标签的判断"，非硬违规；③ 工具已强制的项跳过。

```yaml
QualityGate:
  name: code_review_dual_axis
  axes: [standards, spec]   # 双轴并行，结果分离呈现
  smell_baseline: fowler_12 # 无标准文档时的默认 Standards
  parallel_subagents: true
  blocking: true
```

> **接收反馈闭环（obra `receiving-code-review`，#8）**：Stage6 双轴评审（§9.1）产出的 findings 不单向结束——需有"接收并回应"的闭环：reviewee（或 implementer 子代理）按 findings 修订后**重审**（只验证 ADDRESSED / NOT ADDRESSED，新破坏进 open 列表），直至双轴均 PASS 方可进 `finish`。这一"评审 → 修订 → 重审"循环直接复用 §5.2.1 的修复循环与范围化重审查机制，确保 review 不是形式过场。```

### 9.2 可选成本 / 可观测性门禁（借鉴 caveman `learn` / `stats`）

DevFlow 可把 **token 成本与可观测性**作为一条**可选、非阻断**的 `QualityGate`，灵感来自 caveman 的 `caveman learn`（扫描本地 agent 历史、排名 token sinks）与 `caveman stats`（按内容类型统计压缩效果）：

```yaml
QualityGate:
  name: token_cost_observability
  source: caveman_sidecar   # 部署期 sidecar 采集（见 §15.7），非引擎内置
  mode: advisory            # 仅报告，不阻断
  report:                   # 输出 token sink 排名 + 压缩收益
    - provider_input_tokens
    - compression_ratio_by_type
```

- 该门禁**默认关闭**，仅当项目开启 `observability: true` 时启用，且只产出报告、不阻断阶段推进。
- 数据来源是部署期 caveman sidecar（§15.7），DevFlow 引擎本身**不实现** token 计量，避免与 BSL-1.1 引擎耦合。

### 9.3 过度工程检测（借鉴 ponytail，review 阶段补充视角）

`review` 阶段（Stage6）在双轴（Standards×Spec，§9.1）之外，可增一条**补充视角**：检测是否"过度构建（over-build）"——即是否引入了本可由标准库/原生能力/已装依赖/一行代码解决的多余实现。灵感来自 ponytail 的 `/ponytail-review` `/ponytail-audit`（聚焦"是否过度构建 + 安全是否保留"）。

- 该视角**不替换**双轴评审，而是作为 Stage6 的额外检查项（尤其 `Spec` 轴已 PASS、但实现明显超出契约所需时报警）。
- 与 §9.1 的气味基线互补：Fowler 气味偏向"坏味道"，ponytail 视角偏向"不必要的新代码量"。
- 默认 advisory（不阻断），仅在 `minimalism_strictness=ultra` 时升为 blocking（见 §10）。

### 9.4 周期性架构熵检查（Tier2 来自 `improve-codebase-architecture`）

除提交期门禁外，DevFlow 可把**架构债扫描**作为一条**周期性（如每 N 次提交 / 定时）非阻断 `QualityGate`**，灵感来自 `improve-codebase-architecture`（扫描深化机会、生成可视化 HTML 报告并盘问）：

```yaml
QualityGate:
  name: architecture_entropy_check
  schedule: every_n_commits: 20   # 或 cron
  report: html                    # 生成架构熵/圈复杂度/依赖热点 HTML 报告
  blocking: false                 # 仅告警，不直接阻断
```

- 报告聚焦：循环依赖、模块边界侵蚀（外部刺穿 facade）、重复实现、过大函数/类。
- 与 §9 RedLineAuditor 互补：RedLineAuditor 是提交期"硬红线"扫描，本门是周期"软熵"趋势，用于提前预警而非阻断交付。
- 不变量：周期性门禁结果进账本但不强制回滚，对应 §2「诚实标注遗留」的挂账精神。

### 9.5 引擎自测 / 行为 Eval（来自 obra 技能微测试，#13）

DevFlow 正是一个"我们亲手造的工作流引擎"，最该给**引擎自身的行为**写测试——这正是 obra 用 **drill eval**（行为基线测试，如 "25/25 拒绝陈旧 ledger"）保证每个技能改动不退化所践行的纪律。DevFlow 把该方法论落地为：

- **行为级断言（behavioral assertions）**：针对引擎不变量写 eval，例如：① 未产 Stage[i-1] 工件时 `devflow.next()` 拒绝进入 Stage[i]；② `devflow.commit()` 在 `tests_pass` / `ci_green` 未 PASS 时返回阻断原因而非提交；③ SDD 每 task 必须双 verdict（spec + quality）才标记 done；④ 回路断路器在第 5 轮触发主代理裁决；⑤ 红线审计对"跳步 / 无测试 / 超大 PR"报违规。
- **eval 套件位置**：`tests/evals/`（见 §11 目录布局），与引擎功能 TDD 套件（`tests/`）分离，专测"工作流纪律是否被遵守"。
- **回归守护**：任何对 §3–§9 领域模型 / 状态机 / 门禁的改动，须跑 `tests/evals/` 全绿，防止"修正一个阶段却悄悄废掉 No-Skip 不变量"。这与 §2「禁止跳步」、§9 RedLineAuditor 形成"代码层 + 行为层"双重防护。

---

## 10. 配置与扩展（ruflo-kb 实例映射）

引擎通过 `sop.yaml` 注入具体流程。ruflo-kb 实例配置要点：

```yaml
sop:
  phases: [intake, brainstorm, plan, contract, implement, verify, review, finish]  # Stage0 intake 入口闸门见 §5.0
  red_lines: [skip_phase, no_test, cross_module_import, huge_pr, ...]
  minimalism_strictness: full   # 借鉴 ponytail：implement 阶段极简护栏强度 lite|full|ultra
  model_tiers:                  # 借鉴 obra SDD：派发子代理时的模型选型（§5.2.1）
    mechanical: cheapest        # 机械任务（常量改名等）用最廉价模型
    integration: standard       # 集成/判断用标准模型
    architecture: strongest     # 架构/疑难用最强模型
    repair_escalate_to: strongest  # 修复轮次 4-5 升级到的模型
  gates:
    tests_pass: { command: "pytest --import-mode=importlib", blocking: true }
    ci_green:   { command: "ci-check", blocking: true }
    overbuild_check: { command: "ponytail-audit", blocking: false }  # §9.3 过度工程检测（advisory，ultra 时升 blocking）
  modules:
    facade: "__init__.py"          # 唯一对外入口
    forbidden_import: ["service/", "model/", "utils/ 内部"]
  tooling:
    test_runner: "pytest"
    import_mode: "importlib"
    proxy_strip: true              # Windows 需剥离 HTTP_PROXY
```

切换项目只需换 `sop.yaml`，引擎逻辑不变 → 满足"通用引擎 + 配置实例"。

---

## 11. 工具自身目录布局（建议）

```
devflow/
├── pyproject.toml
├── src/devflow/
│   ├── engine/            # 编排引擎（平台无关）
│   │   ├── state_machine.py   # PhaseStateMachine
│   │   ├── skill_resolver.py  # 阶段→能力映射
│   │   ├── checkpoint.py      # 挂起/续接
│   │   └── redline_auditor.py
│   ├── model/             # 领域模型（Spec/Plan/Task/Contract/Gate/Ledger）
│   ├── storage/           # StorageBackend + FSBackend
│   ├── verify/            # GateRunner + TestRunner 封装
│   ├── policy/            # sop.yaml 加载与校验
│   └── cli.py             # devflow CLI 门面（含 init / start / next / status / gate / commit / audit / suspend）
├── adapters/
│   ├── workbuddy/         # Skill + MCP 适配
│   ├── claude_code/       # Command + Hook 适配
│   └── codebuddy/         # Skill 适配
├── config/sop.default.yaml
├── tests/                 # 引擎自身 TDD 套件（功能级）
└── tests/evals/           # 行为级 eval（§9.5：工作流纪律回归守护）
```

---

## 12. 实施路线

| 版本 | 范围 | 交付物 |
|---|---|---|
| **MVP** | 引擎内核 + FS 存储 + WorkBuddy 适配 + 阶段状态机（含 Stage0 intake）+ 账本 | 能在 WorkBuddy 内跑通八阶段（含 intake 入口）、不可跳步、账本落盘（范围与验收见 §16） |
| **v0.2** | GateRunner + RedLineAuditor + 契约测试校验 | 提交前门禁与红线检查 |
| **v0.3** | Claude Code / CodeBuddy 适配 + MCP Server | 三平台一致调用 |
| **v1.0** | `sop.yaml` 配置驱动 + CI 集成 + ruflo-kb 实例验证 | 通用引擎 + 真实项目背书 |

---

## 13. 风险与开放问题

1. **No-Skip 与 Agent 自主性的张力**：过强制会拖慢探索性任务；需允许 `fast_forward` 模式（仅记录跳步，不阻断）。
2. **门禁命令的平台差异**：pytest/windows 代理剥离等环境坑需配置化（已预留 `proxy_strip`）。
3. **账本与 git 的同步**：commit 后才写账本 vs 账本先行——建议以 commit 为真实源，账本为镜像。
4. **跨平台话术一致性**：同一引擎结果在三平台渲染需各自适配，避免行为漂移。

---

## 14. 附录：与现有 ruflo-kb 文件映射

| 本文抽象 | ruflo-kb 现有对应 |
|---|---|
| `Spec` / `Plan` | `docs/superpowers/specs/` `docs/superpowers/plans/` |
| `LedgerEntry` / 账本 | `.superpowers/sdd/progress.md` |
| 八阶段 Stage（含 Stage0 `intake` 入口，§5.0） | `PROJECT_SOP.md` 第一~十二章 |
| 调用能力映射 | `CLAUDE.md`（brainstorming 等 superpowers 技能） |
| 红线审计 | `PROJECT_SOP.md` 第十一章；`TECH_DEBT_CHECKLIST.md` |
| 契约先行/TDD | `重载函数重构计划.md` §0 原则；`README.md` 测试段 |
| 备份优先 | `Phase4状态修复方案.md` 第三章 |
| 分批治理 | `Phase4完成度核对.md` Phase 0–5 |
| 门禁/挂账 | `phase5_report.md` M1–M12 指标 + 挂账 |

> 本文所有抽象均来自对上述文件的提炼，非凭空设计；实现时以上文件即为"参考实现"与验收样例。

---

## 15. 外部灵感：mattpocock/skills 全量映射

> 来源：`https://github.com/mattpocock/skills`（"Skills For Real Engineers"，25 个 Agent Skills，分 Engineering / Productivity 两大类、User-invoked / Model-invoked 两层）。本节把每个模块逐项对照 DevFlow 现有分层（接入层 / 编排引擎 / 领域模型 / 存储与验证 / 策略配置 / 七阶段），标明**并入层、吸收内容或不吸收原因**，作为后续实施的溯源映射。

### 15.1 汇总

- **25 个模块**：Engineering-User 9 / Engineering-Model 9 / Productivity-User 5 / Productivity-Model 2。
- **20 个并入引擎各层**（领域模型 / 编排 / 存储验证 / 策略 / 阶段）；**2 个仅作适配层可选技能库**（setup-matt-pocock-skills、to-questionnaire）；**3 个不入核**（teach、wait-what、writing-for-agents，因偏离"工程交付流水线"主边界）。
- **4 个 Tier1 真实填补空白**（落地见 §4 / §5 / §9 对应增强）：`DomainModel`（CONTEXT.md/ADR 共享语言）、`Task` DAG + tracer-bullet、`debug` 反馈环律、双轴 review + 气味基线。

### 15.2 Engineering · User-invoked（9）

| # | 模块 | 能力介绍 | 并入 DevFlow 哪层 | 吸收什么 / 不吸收原因 |
|---|---|---|---|---|
| 1 | **ask-matt** | 路由器：询问"该用哪个技能/流程"并推荐 | 编排引擎 → `SkillResolver` / `devflow.next` | **吸收**：把"用户意图→能力路由"做成显式路由器，补当前 `next` 只能线性推进、缺意图识别的短板 |
| 2 | **grill-with-docs** | 盘问式访谈同时构建领域模型，落地 ADR + 术语表 | 领域模型（新增 `DomainModel` 工件）+ Stage1 | **吸收（Tier1）**：`CONTEXT.md` 领域术语表 + ADR 作一等工件，每阶段先读——填补 DevFlow 缺失的"共享语言"层 |
| 3 | **triage** | issue/PR 状态机：needs-triage→needs-info→ready-for-agent/ready-for-human/wontfix，含 bug/enhancement 分类 | 新增 Intake/Issue 入口 + `Task.status` 扩维 | **吸收（Tier2）**：角色状态机 + "agent 可执行 vs 需人工"双门禁，直接对应 ready-for-agent/ready-for-human |
| 4 | **improve-codebase-architecture** | 扫描架构深化机会，生成可视化 HTML 报告并盘问 | 存储与验证 → `QualityGate`（周期型） | **吸收**：作为周期性"架构熵检查"门禁，产出 HTML 报告 |
| 5 | **setup-matt-pocock-skills** | 每仓库运行一次，配置 tracker / 标签 / 文档位置 | 策略配置 / 安装引导 | **部分吸收**：借鉴其"每仓库 init 引导"概念 → DevFlow 的 `devflow init`（生成 sop.yaml 模板+目录骨架）；tracker/标签绑定是 mattpocock 生态特有，`sop.yaml` 已覆盖，**不照搬** |
| 6 | **to-spec** | 把当前对话转 spec 并发布到 issue tracker（无访谈） | Stage1 brainstorm / 领域模型 `Spec` | **吸收**：对话→Spec 自动化产出，可作 `devflow.start` 实现路径；其强绑定 tracker 发布**不吸收**（DevFlow 用本地 specs/，tracker 发布作可选适配） |
| 7 | **to-tickets** | 把 plan/spec 拆为带阻塞边的 tracer-bullet tickets | 领域模型 `Task`（升级为 DAG）+ Stage2 | **吸收（Tier1）**：`blocked_by` 依赖边、acceptance criteria、tracer-bullet 垂直切片、宽重构 expand–contract 时序 |
| 8 | **implement** | 按 spec/tickets 构建，编排 tdd + code-review + commit | Stage4 implement 编排循环 | **吸收（Tier2）**：显式编排链（tdd→类型检查→全量测试→review→commit），补全"executing-plans"过笼统的描述 |
| 9 | **wayfinder** | 规划超大工作量，生成决策 ticket 的共享地图 | Stage2 plan（大型） | **吸收**：超大任务的"决策地图"规划法，作 plan 阶段对大型 effort 的扩展 |

### 15.3 Engineering · Model-invoked（9）

| # | 模块 | 能力介绍 | 并入 DevFlow 哪层 | 吸收什么 / 不吸收原因 |
|---|---|---|---|---|
| 10 | **prototype** | 用一次性 HTML 原型回答设计问题 | Stage1 brainstorm / 设计验证 | **吸收**：原型验证作 Spec 阶段设计确认技术（轻量、可弃） |
| 11 | **diagnosing-bugs** | 硬 bug 诊断循环：建反馈环→最小化→假设→测试→修复 | 新增 `debug` 能力/阶段 + 存储验证 | **吸收（Tier1）**：紧致可红反馈环律、10 种建环法、先回归测试后修复、`[DEBUG-*]` 清理纪律 |
| 12 | **research** | 基于高信任源调查，生成带引用 Markdown | Stage2 plan（调研） | **吸收**：计划阶段"引文式调研"子能力 |
| 13 | **tdd** | 红绿重构，seam 概念，反模式 | 领域模型 `Contract` + Stage3 | **吸收（Tier2）**：seam（只测预约定边界）、三条反模式（实现耦合/同义反复/水平切片）、"重构归 review"——与阶段切分对齐 |
| 14 | **domain-modeling** | 主动构建/锐化领域模型，更新 CONTEXT.md | 领域模型 `DomainModel`（与 #2 同工件） | **吸收**：领域模型主动维护机制，作 CONTEXT.md 的写入方 |
| 15 | **codebase-design** | 深度模块设计的共享规范与词汇（seam/adapter/locality/leverage） | 领域模型 / 设计词典 + 模块边界约束 | **吸收**：作 DevFlow"设计词典"，被 tdd/review 引用 |
| 16 | **code-review** | 双轴（Standards×Spec）并行子代理 + 气味基线 | Stage6 review + `QualityGate` | **吸收（Tier1）**：双轴模型 + Fowler 12 气味基线作默认门禁 |
| 17 | **resolving-merge-conflicts** | 逐 hunk 解 git merge/rebase 冲突 | Stage7 finish | **吸收**：冲突解决流程化，作 finish 阶段子流程 |
| 18 | **wizard** | 生成交互式 bash 向导供人类执行专属步骤 | 阶段（人工门禁） | **吸收**：需人工的操作用 bash 向导承接，对应 ready-for-human 门禁的人工动作 |

### 15.4 Productivity · User-invoked（5）

| # | 模块 | 能力介绍 | 并入 DevFlow 哪层 | 吸收什么 / 不吸收原因 |
|---|---|---|---|---|
| 19 | **grill-me** | 对非代码计划/设计彻底盘问 | Stage1 brainstorm（非代码向） | **吸收**：盘问访谈技术作 brainstorm 对齐手段，与 #2 共用 grilling 原语 |
| 20 | **handoff** | 对话压缩为交接文档供其他 agent 续接 | Stage suspend / `Checkpoint` | **吸收（Tier2）**：交接文档加"suggested skills"段 + 引用既有工件路径而非复制，强化跨设备续接 |
| 21 | **teach** | 多会话教学，当前目录为教学工作区 | — | **不吸收**：属知识传授场景，非"工程交付流水线"范畴；可作适配层独立技能，不进引擎原语 |
| 22 | **to-questionnaire** | 把决策转为 Markdown 问卷发给特定人 | 适配层可选（人工决策采集） | **部分吸收**：可辅助 handoff/grill-me 采集人类决策；非引擎核心，列可选技能库 |
| 23 | **wait-what** | 消息不理解时用平实语言重述 | — | **不吸收**：属 agent 沟通礼仪，放适配层话术规范即可，不入引擎原语 |

### 15.5 Productivity · Model-invoked（2）

| # | 模块 | 能力介绍 | 并入 DevFlow 哪层 | 吸收什么 / 不吸收原因 |
|---|---|---|---|---|
| 24 | **grilling** | 可复用盘问原语，支撑 #2/#3/#19 | 编排引擎 / grill 原语被 Stage1 调用 | **吸收**：把"盘问对齐"做成可复用原语（已由 #2 间接吸取） |
| 25 | **writing-for-agents** | 为 agent 写文档（skills、AGENTS.md 等） | — | **不吸收**：是"如何给 agent 写文档"的元技能，用于 DevFlow 自身技能/AGENTS 文档编写规范，作适配层作者指南，不入引擎原语 |

### 15.6 对 DevFlow 的结构性影响（Tier1）

1. **新增 `DomainModel` 工件（CONTEXT.md + ADR）**：让每阶段有"项目词典"可查，这是当前 DevFlow 文档最大的结构性缺口（§4 领域模型需补此实体）。
2. **`Task` 从线性 `depends_on` 升级为带 acceptance criteria 的 DAG + tracer-bullet 切片 + 宽重构时序**：计划拆解从"任务列表"升级为"可执行的垂直切片图"（§4.2 需改写）。
3. **`debug` 成为一等能力，以"反馈环律"为内核**：把模糊的"调试"变成有出口条件的可审计流程（§5 阶段机可增 `debug` 阶段或在 `verify` 内嵌）。
4. **`QualityGate` 获双轴（Standards×Spec）+ Fowler 12 气味基线默认实现**：给出开箱即用的默认门禁，仓库无标准文档时也能跑（§9 需补双轴与气味基线）。

> 本节为**溯源映射**。Tier1 的具体字段与流程**已于此前修订正式落地**：§4.2（`Task` 升级为 `blocked_by` DAG + acceptance + tracer-bullet + 宽重构）、§4.6（新增 `DomainModel` 共享语言层）、§5（每阶段先读 DomainModel + 阶段表增 grill/to-tickets/diagnosing-bugs/双轴）+ §5.1（Debug 反馈环律）、§9.1（双轴评审 + Fowler 12 气味基线）。**Tier2 亦已于本次修订正式落地**：§4.3（seam + 反模式）、§4.6（设计词典）、§4.7（Intake/Issue 实体 + triage 状态机）、§5.0（Intake 入口闸门）、§5.2（Implement 编排链）、§5.3（wayfinder/prototype/research/grill-me）、§5.4（merge-conflicts/wizard/handoff 增强）、§6（意图路由 SkillResolver）、§7（人工门禁与决策采集）、§8（`devflow init`）、§9.4（周期性架构熵门禁）、§11（CLI 含 init）。§15.2–15.5 现为完整溯源记录。

---

### 15.7 外部灵感：caveman（token 压缩 / 跨平台适配 / 可恢复存储参考）

> 来源：`https://github.com/JuliusBrussee/caveman`（🪨 "why use many token when few do trick"，让 AI Agent 用更少 token 完成同样工作）。它是一个**与 DevFlow 正交的运行时压缩层**（输出压缩 Skill + 输入压缩 Proxy + 像素渲染 + token 可观测），**不是工作流编排**，因此**不可作为 DevFlow 的「工作流 skill 引用」**；但其适配层打包范式、可恢复存储、跨平台集成面设计值得借鉴（评估见本节）。

#### 15.7.1 逐项映射（采纳 / 不采纳 / 部署级 sidecar）

| # | caveman 能力 | 类型/许可 | 并入 DevFlow | 吸收内容 / 不吸收原因 |
|---|---|---|---|---|
| C1 | **Skill（`/caveman` 输出压缩）** | MIT | 不并入内核 | 让 agent "说更少"与 DevFlow「每阶段必产完整可审计工件」冲突；仅作适配层**可选话术规范** |
| C2 | **Caveman Proxy（输入压缩）** | BSL-1.1 ⚠️ | ❌ 不 vendoring | 引擎/代理为 BSL-1.1（非 OSI，2030/发版 4 年后转 Apache-2.0）；DevFlow 若 MIT/Apache 则**禁止复制其代理代码**，仅借鉴设计 |
| C3 | **CCR 内容寻址存储（字节精确恢复）** | 设计模式 | ✅ §4.5 / §4.6 | 直接对应账本与工件的**不可变可恢复**约束（CCR-first / Visible declines / Labeled evidence） |
| C4 | **`detect()` → 分类路由压缩器** | 设计模式 | ✅ §7 适配层 | 接入新平台先探测其能力类型再路由——与 §4.5 分类路由同构 |
| C5 | **MCP Server（`caveman_compress` 等）** | MIT + MCP | ✅ §6 双集成面 | DevFlow 接口应同时提供 Skill + MCP 两种形态，覆盖任意 MCP Host |
| C6 | **`caveman learn` / `stats`（token sink 排名）** | MIT | ✅ §9.2 可选门禁 | 作 DevFlow 成本/可观测性**可选、非阻断** QualityGate |
| C7 | **`/caveman-commit`（简洁 Conventional Commit）** | MIT | ✅ §5 S7 | `finish` 阶段采用单行可操作提交风格 |
| C8 | **`wrap --pixel`（密集文本→PNG）** | 设计模式 | ❌ 不吸收 | 仅对超密集长行盈利且依赖视觉模型，与工件模型无关 |
| C9 | **30+ agent 安装矩阵（skill + baseURL）** | MIT | ✅ §7 适配层 | DevFlow 适配层最该学的打包范式：一套核心 + 多平台薄适配 |

#### 15.7.2 许可证红线（关键）

| 组件 | 许可 | 对 DevFlow 约束 |
|---|---|---|
| caveman **Skill**（含 `/caveman`、`/caveman-commit`、`/caveman-review`、`/caveman-compress`） | **MIT** ✅ | 可自由参考其话术/提交/审查风格，甚至直接适配为 DevFlow 的 WorkBuddy Skill 子命令 |
| caveman **Engine / Proxy / CCR** | **BSL-1.1** ⚠️ | **非开源**，不得将其代码并入 DevFlow；只能借鉴**设计思想**（detect 路由、CCR 不可变、labeled evidence） |
| caveman **CLI**（`@caveman-ai/cli`） | MIT（引擎 BSL 分隔） | 可作为 DevFlow 的**部署期 companion**（把 DevFlow 的 agent 流量经 caveman 代理省 token），但不进引擎代码 |

#### 15.7.3 落地位置汇总

- **已落地进正文**：§4.5（CCR 不可变恢复约束）、§4.6（ADR/术语表可恢复）、§5 S7（简洁 commit 风格）、§6（Skill+MCP 双集成面）、§7（能力探测 + 双集成面 + sidecar 红线）、§9.2（token 成本可选门禁）。
- **仅作部署级 sidecar**：caveman Proxy 压缩 DevFlow agent 流量（不在引擎内）。
- **不采纳**：输出压缩话术（与工件完整性冲突）、Pixel 渲染（无关）、Proxy 引擎代码（BSL-1.1 红线）。

---

### 15.8 外部灵感：ponytail（极简主义约束 / 债务追踪 / 适配层印证）

> 来源：`https://github.com/DietrichGebert/ponytail`（"the best code is the code you never wrote"，让 AI 编码 Agent 像最懒的高级工程师一样思考，避免过度构建）。**MIT 许可**，与 caveman 不同——其代码与设计可自由借鉴甚至 co-install，无 BSL-1.1 红线。它是一套**单阶段行为约束技能/插件**（20 宿主），正好补在 DevFlow 的 **Stage4 `implement` + 账本债务追踪**上，比 caveman（正交压缩层）更贴骨。

#### 15.8.1 逐项映射（采纳 / 部分 / 不采纳）

| # | ponytail 能力 | 类型/许可 | 并入 DevFlow | 吸收内容 / 不吸收原因 |
|---|---|---|---|---|
| P1 | **偷懒阶梯（laziness ladder）** | MIT | ✅ §5 S4 | **吸收**：编码前强制"能否不写/复用/标准库/一行"判定，补 DevFlow 缺失的"反过度工程"护栏；与 contract-first 互补（契约定 WHAT，阶梯约束 HOW MUCH） |
| P2 | **安全底线（简化不删校验/安全）** | MIT | ✅ §9 非 negotiable 门 | **吸收**：阶梯的"安全地板"映射为 DevFlow 不可跳过门（`tests_pass`/`ci_green` 不得因极简被砍） |
| P3 | **`ponytail:` 债务标记 + `/ponytail-debt`** | MIT | ✅ §4.5 | **吸收**：刻意简化债务录入账本 `LedgerEntry.debt`，与"诚实标注遗留"原则合一 |
| P4 | **强度模式 lite/full/ultra/off** | MIT | ✅ §10 `minimalism_strictness` | **吸收**：Stage4 极简严格度可配置（探索性用 lite，严肃库用 ultra） |
| P5 | **`/ponytail-review` `/ponytail-audit`** | MIT | ✅ §9.3 补充视角 | **部分吸收**：聚焦"是否过度构建 + 安全"，比双轴 review 窄；作 review 阶段补充视角，不替换双轴 |
| P6 | **多宿主适配（20 环境，规则/插件/hook）** | MIT | ✅ §7 印证 | **吸收（印证）**：再度验证"一套核心 + 薄适配"范式（与 caveman §15.7 同结论，宿主覆盖更广），强化 §7 |
| P7 | **可复现基准（promptfoo）** | — | ❌ 不吸收内核 | 属 ponytail 自身验证资产，可作 DevFlow 适配层效果度量参考，非引擎原语 |

#### 15.8.2 许可证（对比 caveman）

| 项目 | 许可 | 对 DevFlow |
|---|---|---|
| **ponytail** | **MIT** ✅ | 可自由借鉴阶梯/债务标记/强度模式，甚至 co-install 为适配层技能，**无 vendoring 限制** |
| caveman Proxy | BSL-1.1 ⚠️ | 不可 vendoring，仅作 sidecar（见 §15.7） |

> 结论：ponytail 比 caveman **集成成本低得多**——理念直接落进 `sop.yaml` / Stage4 / 账本即可，不必设 sidecar 隔离。

#### 15.8.3 落地位置汇总

- **已落地进正文**：§4.5（账本增 `debt` 子类型 + `ponytail:` 标记约定）、§5 S4（偷懒阶梯前置判定 + 安全地板不砍门禁 + 极简护栏段落）、§7（20 宿主适配再印证适配层范式）、§9.3（过度工程检测补充视角）、§10（`minimalism_strictness` + `overbuild_check` 门禁）。
- **不采纳内核**：可复现基准（P7，属 ponytail 自身验证资产）。
- **与 caveman 的本质区别**：caveman 是**正交的运行时压缩层**（不可作工作流引用，仅 sidecar）；ponytail 是**实施阶段的行为约束**（直接并入 Stage4 + 账本，MIT 自由借鉴）。

---

### 15.9 外部灵感：obra/superpowers 全量映射（SDD 编排 / 多 harness 打包 / 行为 eval）

> 来源：`https://github.com/obra/superpowers`（v6.3.0，Prime Radiant / Jesse Vincent，"An agentic skills framework & software development methodology that works"）。**MIT 许可**——其技能与设计可自由借鉴甚至 co-install，无 caveman 的 BSL-1.1 红线。它实质上是 DevFlow 已吸收的 superpowers 系技能的**上游正本**，并额外提供了 DevFlow 此前缺失的**具体编排运行时**（SDD 子代理编排、回路断路器、裁决账本、三路径、并行派发、理性化防御表、压缩后 bootstrap 重注、技能自测 eval、多 harness 打包）。

#### 15.9.1 逐项映射（引进 / 已覆盖 / 不引进）

| # | obra 组件 | 类型/许可 | 决策 | 并入 DevFlow 哪层 / 吸收内容或不引进原因 |
|---|---|---|---|---|
| 1 | **subagent-driven-development (SDD)** | MIT | ✅ 引进（最大增量） | §5.2.1 SDD 执行模式：每任务新子代理（隔离上下文、no-subagents 契约）、任务级双审查(spec+quality)、plan-scoped workspace、修复循环 |
| 2 | **brainstorming 三路径** (spike/bounded/architectural + HARD-GATE) | MIT | ✅ 引进 | §5 S1 三路径路由 + HARD-GATE（批准门槛永不缩放、只升不降） |
| 3 | **dispatching-parallel-agents** | MIT | ✅ 引进 | §5.2.1 并行派发（frontier 独立域一代理一域、同响应批派 = 并行） |
| 4 | **systematic-debugging 四阶段** | MIT | ✅ 引进增强 | §5.1 升级为四阶段根因法 + 3 次失败质疑架构 + root-cause-tracing/defense-in-depth/condition-based-waiting |
| 5 | **回路断路器 + never-stall 裁决** | MIT | ✅ 引进（高价值） | §5.2.1 5 轮断路器 + Rulings；仅四类硬停 |
| 6 | **Rulings 账本** (`Ruling: 决定—原因—错代价`) | MIT | ✅ 引进 | §4.5 `LedgerEntry.action=ruling` + `ruling` 字段 |
| 7 | **Model 选型 / 升级** | MIT | ✅ 引进 | §5.2.1 dispatch 配置 + §10 `model_tiers` |
| 8 | **receiving-code-review** | MIT | ✅ 引进 | §9.1 评审→修订→重审闭环 |
| 9 | **using-git-worktrees** | MIT | ✅ 引进（可选） | §5.2.1 worktree 隔离 + 干净测试基线（大型项目可选强化） |
| 10 | **Common Rationalizations 表**（借口/现实对照） | MIT | ✅ 引进模式 | §4/§5 各纪律点补 Rationalization 表（debug/brainstorm/SDD 防自我合理化） |
| 11 | **Bootstrap 重注（启动 + 压缩后）** | MIT | ✅ 引进 | §5.4 suspend/resume + SessionStart 重注点 |
| 12 | **多 harness 插件打包**（15+ 平台, 共享技能库, 无每平台副本） | MIT | ✅ 引进模式 | §7 升级为"共享技能库 + 每 harness 薄清单"具体形态 |
| 13 | **技能微测试 / eval 基线**（drill eval） | MIT | ✅ 引进方法论 | §9.5 引擎自测/eval（行为级回归守护） |
| 14 | **Windows SessionStart 钩子改 Git Bash** | MIT | ✅ 引进（实现细节） | §7/§11 Windows 钩子用 Git Bash + GNU tar |
| 15 | **test-driven-development**（red-green + 反模式参考） | MIT | ⚠️ 已覆盖/补强 | §4.3 seam + 反模式已含；引入 obra 的"反模式参考文档"形式 |
| 16 | **verification-before-completion**（证据>声明） | MIT | ⚠️ 已覆盖/强化 | §5 S5/§9 已含；用"evidence over claims"哲学锚定 §9 |
| 17 | **requesting-code-review**（单轴预检清单） | MIT | ⚠️ 已被超越 | §9.1 双轴更强，不重复 |
| 18 | **writing-plans / executing-plans** | MIT | ⚠️ 已覆盖 | Stage2/Stage4；SDD(#1) 是其子代理变体 |
| 19 | **finishing-a-development-branch**（merge/PR/keep/discard + 清理） | MIT | ⚠️ 已覆盖 | §5 S7；引入"未跟踪文件须问人"细节 |
| 20 | **writing-skills**（创作/测试技能） | MIT | ❌ 不进核 | 元技能，留作适配层作者指南 |
| 21 | **Visual Companion Telemetry**（logo 信标/版本回传, 可关） | MIT | ❌ 不引进 | DevFlow 本地工具，不回传任何数据（隐私/企业知识库场景） |
| 22 | **Commercial Services / 市场 JSON** | MIT | ❌ 不引进 | 具体 marketplace.json 是 obra 资产；仅借鉴打包"模式" |

#### 15.9.2 许可证（对比三库）

| 项目 | 许可 | 对 DevFlow |
|---|---|---|
| **obra/superpowers** | **MIT** ✅ | 可自由借鉴全部技能与设计，甚至 co-install 为适配层技能，**无 vendoring 限制** |
| ponytail | MIT ✅ | 同上（§15.8） |
| caveman Proxy | BSL-1.1 ⚠️ | 不可 vendoring，仅 sidecar（§15.7） |

> 结论：obra/superpowers 与 ponytail 同为 **MIT**，是 DevFlow 外部灵感中**集成成本最低**的两个来源（理念直接落进引擎 / Stage / 账本 / sop.yaml 即可）；caveman 仅因 Proxy 的 BSL-1.1 须隔离为 sidecar。

#### 15.9.3 落地位置汇总（#1–#14）

- **§4.5**：`LedgerEntry.action` 增 `ruling`，增 `ruling` 字段（#6）
- **§5 S1**：三路径路由 + HARD-GATE（#2）
- **§5.2.1（新增）**：SDD 执行模式——子代理派发 + 双审查 + plan-scoped workspace + 5 轮断路器 + never-stall 裁决 + model 选型 + 并行派发 + worktree 隔离（#1/#3/#5/#7/#9）
- **§5.1**：四阶段根因法增强（#4）
- **§9.1**：接收反馈闭环（#8）
- **§5.4**：Bootstrap 重注（#11）
- **§7**：共享技能库 + 薄清单打包范式 + Windows 钩子 Git Bash 注记（#12/#14）
- **§9.5（新增）**：引擎自测/eval 方法论（#13）
- **§10**：`model_tiers` 配置（#7）
- **§11**：`tests/evals/` 目录（#13）
- **Rationalization 表模式（#10）**：建议在 debug/brainstorm/SDD 各纪律点补"借口/现实"对照（本次未逐点铺开，留作后续精修）

---

## 16. MVP 实现范围与验收（可被其他 agent 直接开发的交付包）

> 本节是 DevFlow 的**首版交付定义**。它把上文全愿景收敛为「可被另一个 agent 直接实现」的封闭任务：明确 IN / OUT、技术栈、目录、13 条验收、M0–M5 里程碑、端到端 demo、必读红线。
> 配套可交付物（同目录）：`MVP-门禁降级矩阵.md`（门禁权威）、`DevFlow-MVP-实现简报.md`（实现 Agent 首读 handoff）、`sop.yaml`（本 MVP 的可加载配置实例）。
>
> **文档权威级（高→低）**：`MVP-门禁降级矩阵.md`（门禁权威）> 简报 §1 IN/OUT（范围权威）> `sop.yaml`（配置权威）> 本文档（设计参考）。四者冲突时按此优先级处理。

### 16.0 MVP 相对本架构文档的简化清单

> 本架构文档描述的是 v1.0 完整愿景。MVP 为控制复杂度，对以下特性做了**有意简化**，实现时以简报 §1 IN/OUT 为准：

| 特性 | 架构文档描述 | MVP 简化 | 留到版本 |
|---|---|---|---|
| Task DAG 环检测 | §4.2 `blocked_by` DAG + 无环校验 | `blocked_by` 仅作列表字段，**不校验环** | v0.2 |
| tracer-bullet / wide_refactor | §4.2 垂直切片 + expand–contract | **不做**，Task 按线性拆分 | v0.2 |
| SDD 子代理派发 | §5.2.1 每任务新子代理 + 断路器 + model 选型 | **不做**，implement 由主代理执行 | v0.2 |
| 双轴评审 | §9.1 Standards×Spec 并行子代理 | **不做**，MVP 仅自查清单占位 | v0.2 |
| Debug 反馈环律 | §5.1 四阶段根因法 | **不做**，verify 只跑 tests_pass | v0.2 |
| DomainModel / ADR | §4.6 CONTEXT.md + ADR 一等工件 | **仅 CONTEXT.md 骨架**，不含 ADR 维护机制 | v0.2 |
| CCR 内容寻址存储 | §4.5 字节级可恢复 + 哈希 | **仅 append-only 日志**（progress.yaml 只追加不覆盖） | v0.2 |
| Intake triage 状态机 | §4.7/§5.0 needs-triage→ready-for-agent 完整流转 | `intake_fast_skip: true` 时自动 `ready-for-agent`，**Stage0 仍执行**（产出工件+写账本），只是判定结果预设 | v0.2 |
| 意图路由 SkillResolver | §6 SkillResolver 解析用户意图 | **仅线性推进**（next 返回下一阶段动作） | v0.3 |
| 过度工程检测 | §9.3 ponytail overbuild_check | `sop.yaml` 有键但 `enabled:false`，**不接线** | v0.2 |
| 周期架构熵 / token 成本 | §9.2/§9.4 | **不做** | v1.0 |
| WorkBuddy Skill 适配 | §7 适配层 | **CLI 跑通优先**，适配层作为 M5 可选封装，**MVP Done 不要求** | v0.2 |

### 16.1 一句话目标

造一个 **Python 引擎 + CLI 门面**，强制跑通「Intake → 八阶段」工作流、禁止跳步、账本落盘。MVP 先交付可用的 CLI 工具；WorkBuddy Skill 适配作为可选的 M5 封装层。**不做** MCP / 三平台 / 双轴评审。

### 16.2 范围（IN / OUT）

**IN（必须做）**
- **领域模型**（pydantic v2）：`Spec` / `Plan` / `Task`（MVP 简化：`blocked_by` 仅作列表字段，不做环检测）/ `Contract` / `QualityGate` / `LedgerEntry` / `DomainModel`（MVP 仅 CONTEXT.md 骨架）/ `Intake`
- **编排**：`PhaseStateMachine`（8 阶段，含 Stage0 Intake 闸门）、`SkillResolver`（阶段→能力 + 基础意图路由）、`Checkpoint`（suspend/resume）、`RedLineAuditor`（基础 11 红线，`circular_dep` 标记 `mvp_skip`）
- **存储**：`StorageBackend` + `FSBackend`（`specs/` `plans/` `progress.yaml` + `CONTEXT.md` 骨架，git 追踪）；MVP 账本简化为 append-only 日志
- **CLI（11 个命令）**：`init` / `start` / `approve` / `next` / `resume` / `status` / `gate` / `commit` / `audit` / `suspend` / `skip-task`
- **门禁（最小集）**：`tests_pass`（blocking）+ `ci_green`（MVP 降级为 advisory）+ `intake` 闸门
- **配置**：读取配套 `sop.yaml`（含 `sop_version` 版本协商）

**OUT（明确不做，留给后续版本）**
- ❌ MCP Server（v0.3）
- ❌ Claude Code / CodeBuddy 适配器（v0.3）
- ❌ 双轴代码评审、Fowler 气味基线（v0.2；MVP 仅自查清单占位）
- ❌ Debug 反馈环律形式化（§5.1；MVP 的 verify 只跑 `tests_pass`）
- ❌ 周期架构熵门禁、token 成本门禁（后续）
- ❌ ponytail `overbuild_check` 实际接线（`sop.yaml` 有键但 `enabled:false`）
- ❌ `DBBackend`（仅 FS）
- ❌ DAG 环检测、tracer-bullet 垂直切片、SDD 子代理派发、ADR 维护（v0.2+）
- ❌ WorkBuddy Skill 适配（M5 可选；MVP Done 标准不要求）

### 16.3 技术栈（已拍板，勿自选）

- **Python 3.11+** · **pydantic v2**（模型即 schema）· **pyyaml**（文件 IO）· **typer**（CLI）· **pytest**（测试）
- MCP 预留接口用 **fastmcp**（v0.3 才用，MVP 不装）
- DevFlow 自身许可证：**MIT**；**严禁 vendoring caveman 的 BSL-1.1 引擎/代理代码**（见 §15.7）

### 16.4 目录布局（同 §11）

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
└── tests/
    ├── test_models.py         # 领域模型单元测试
    ├── test_state_machine.py  # 状态机单元测试
    └── test_acceptance.py     # 验收标准集成测试（13 条）
```

### 16.5 验收标准（MVP Done = 以下 13 条全过）

> **TDD 先行**：M0 阶段先将以下 13 条验收标准写成 pytest 测试用例（`tests/test_acceptance.py`）。**测试隔离**：每个验收测试使用 `tmp_path` fixture。详见 `MVP-门禁降级矩阵.md` §5。

1. `devflow init` 在空仓库生成 `sop.yaml` + `specs/` + `plans/` + `progress.yaml` + `CONTEXT.md`，退出码 0。
2. `devflow start <draft>` 产出 `specs/<id>.yaml`，`status=draft`，含非空 `problem/goals`。
3. **不可跳步**：Spec 未 `approved`（缺 `non_goals` 或必填字段不齐，必填字段见 `MVP-门禁降级矩阵.md` §0.1）→ `devflow next` 拒绝进 Stage2，返回具体缺失字段清单。
4. **Intake 闸门**：`Intake.triage_state != ready-for-agent` → `devflow next` 不进 Stage1，返回 triage 阻塞原因。`intake_fast_skip: true` 时 Stage0 仍执行（产出工件+写账本），只是判定结果预设。
5. `devflow gate 5` 执行 `tests_pass`，输出 pass/fail；命令非零退出即 fail。
6. **提交门禁**：`devflow commit <task>` 在 Stage5/6 未全 PASS 时拒绝提交，返回原因且不执行 git commit。通过时执行 `git add -A && git commit`，写入 LedgerEntry 含 git SHA。
7. 完整 8 阶段跑通最小示例后，`progress.yaml` 含每个 phase 过渡的 `LedgerEntry`（含 phase/action/timestamp）。
8. `devflow suspend` 写出 `handoff-<phase>.md`，含 `suggested_skills` 段 + **按路径引用**工件（非复制）。
9. `RedLineAuditor` 对故意引入的 `no_test` / `cross_module_import` 样本能检出并列出违规。
10. `devflow next` / `status` / `gate` / `commit` / `approve` / `resume` / `skip-task` 等命令返回 §6.2 结构的 JSON。
11. `devflow approve <spec-id>` 校验必填字段，通过后 `status→approved`；不通过返回缺失字段清单。
12. `devflow resume` 检测 handoff 文件并恢复阶段状态，输出续接指引。
13. 引擎自身 `tests/` 目录包含 `test_state_machine.py` + `test_models.py` 基础单元测试，覆盖状态转换正/反例和模型必填字段校验。

### 16.6 实现顺序（里程碑）

> 每个里程碑产出可独立验证的交付物，前一个不通过不开始下一个。

- **M0 脚手架 + 测试骨架**：pyproject + 目录 + `devflow init` + pydantic 模型（必填字段见 `MVP-门禁降级矩阵.md` §0.1/§0.4）+ `tests/test_models.py` + `tests/test_acceptance.py`（13 条验收测试骨架，初始全部 xfail）
- **M1 状态机**：`PhaseStateMachine`（含 `approve` 命令的状态转换）+ `SkillResolver` + `Checkpoint`（suspend/resume）+ `tests/test_state_machine.py`（状态转换正/反例）。验收 3/4/11/12 变绿。
- **M2 存储与账本**：`FSBackend` + `progress.yaml` append-only 写入 + 多 Spec 活跃状态管理。验收 1/7 变绿。
- **M3 CLI 门面**：typer 封装 11 子命令（含 `approve` / `resume` / `skip-task`），端到端跑通验收 1–8, 10–12。
- **M4 门禁与红线**：`GateRunner`（`tests_pass`/`ci_green`）+ `RedLineAuditor`（10 条可执行 + 1 条 mvp_skip）。验收 5/6/9 变绿。
- **M5 WorkBuddy 适配**（可选，CLI 稳定后）：Skill 暴露 `devflow.*`。CLI 全命令可用即可视为 MVP 完成。

### 16.7 端到端 demo（验收 7 的最小示例）

```
$ devflow init
  → 生成 sop.yaml, specs/, plans/, progress.yaml, CONTEXT.md
$ devflow start "为 pipeline 增加 batch 重试"
  → specs/20260819-pipeline-batch-retry.yaml (status=draft)
  → Intake 自动创建 (triage_state=ready-for-agent)
  → LedgerEntry(phase=0, action=triage)
$ devflow next
  → "Stage1 brainstorm：请完善 Spec，当前缺失：non_goals"
  → 拒绝进入 Stage2
$ devflow approve 20260819-pipeline-batch-retry
  → 校验必填字段 → 通过 → status=approved
  → LedgerEntry(phase=1, action=approve)
$ devflow next
  → "Stage2 plan：请产出 Plan，包含至少 1 个 Task（需有 module + acceptance）"
... 逐阶段 ...
$ devflow gate 5 && devflow gate 6
  → tests_pass=pass, ci_green=advisory-pass
$ devflow commit task-1
  → Stage5/6 门禁通过 → git add -A && git commit
  → LedgerEntry(phase=7, action=commit, commit=<sha>)
$ cat progress.yaml
  → 含 intake→brainstorm→plan→contract→implement→verify→review→finish 的全链路 LedgerEntry
```

### 16.8 必读约束（违反即返工）

- **不可跳步**是引擎第一铁律（验收 3/4/6）。`intake_fast_skip` 是 "Stage0 自动判定为 ready-for-agent"，**不是跳过 Stage0**——Stage0 的工件产出和账本记录仍然发生。
- 账本以 **commit 为真实源、账本为镜像**：`commit` 成功后才 `append_ledger`。
- **`devflow commit` 语义**：通过门禁后执行 `git add -A && git commit`，写入 LedgerEntry 含 git SHA。详见 `MVP-门禁降级矩阵.md` §0.3。
- **`ci_green` 降级**：MVP 的 `ci_green` 使用占位命令，标记为 `blocking: false`（advisory），不阻断提交。接入真实 CI 后改为 `blocking: true`。
- **`circular_dep` 红线**：MVP 标记 `mvp_skip: true`，`devflow audit` 报告此项为 "skipped (MVP)" 而非假装检查。
- **SOP 版本协商**：`sop.yaml` 含 `sop_version` 字段，引擎校验版本兼容性。
- **测试隔离**：每个验收测试使用 `tmp_path` fixture。
- Windows 测试前剥离 `HTTP_PROXY`/`HTTPS_PROXY`（`sop.yaml` 已 `proxy_strip:true`）。
- 伴侣仓库 caveman 的 **BSL-1.1 引擎/代理代码禁止复制进本项目**；其设计思想（CCR 不可变、detect 路由、Skill+MCP 双集成面）可借鉴。
- ponytail（MIT）理念可直接落进 Stage4/账本，但 MVP 不接线 `overbuild_check`。
- **门禁降级权威**：各 Stage 在 MVP 中的精确出口条件以 `MVP-门禁降级矩阵.md` 为准，本文 §5 阶段表为 v1.0 完整版。
