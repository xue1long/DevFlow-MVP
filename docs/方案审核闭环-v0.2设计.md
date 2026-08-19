# 方案审核闭环 v0.2 设计

> 将「审核→修复→再审核→再修复」循环从外部方法论，升级为 DevFlow 引擎的一等能力。

---

## 1. 背景与动机

在 DevFlow MVP 的研发过程中，我们实际执行了两轮"审计子代理 → 整改 → 复核审计 → 再整改 → 终止判断"的闭环，产出 `审计整改台账.md` 记录全过程。这一实践被证明有效：

- 第 1 轮发现 5 个 🔴 核心问题（缺 approve 命令、commit 语义不明、门禁与 MVP 矛盾等）
- 第 2 轮复核发现 3 个新问题（skip-task 死锁、Abandon-in-Place、Acceptance Bypass）

**然而 MVP 并未将此闭环内置为引擎能力**——当前的状态是：
- 评审过程手工执行（构造子代理 prompt → 收集报告 → 逐条修复）
- 台账手工维护
- 终止条件靠人工判断
- 没有"评审不过 → 阻断推进"的门禁

**v0.2 设计目标**：让审核闭环成为引擎的一等公民，像 `devflow commit` 需要门禁通过一样，`devflow next` 也需要评审通过。

---

## 2. 审核闭环全景

```
┌─────────────────────────────────────────────────────────────────┐
│                    审核闭环（引擎内置）                          │
│                                                                 │
│  devflow review ──→ 子代理并行评审 ──→ 评审报告                  │
│       │                              │                          │
│       │                              ▼                          │
│       │                       评审通过? ──YES──→ 可推进          │
│       │                              │                          │
│       │                              NO                         │
│       │                              ▼                          │
│       │                       违规清单（分级）                    │
│       │                              │                          │
│       ▼                              ▼                          │
│  devflow fix <id> ──→ 修复记录 ──→ 重新触发 review               │
│       │                              │                          │
│       │                       第N轮复核                          │
│       │                              │                          │
│       ▼                              ▼                          │
│  终止判断: 无致命+残余已登记 = 闭环结束                           │
│                                                                 │
│  台账: progress.yaml + review/ 目录（审计历史，不可覆盖）          │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. 新增数据结构

### 3.1 ReviewReport（评审报告）

```yaml
# review/<spec-id>/r1.yaml
review:
  id: "r1"
  spec_id: "20260819-pipeline-retry"
  phase: 2
  created_at: "2026-08-19T14:30:00Z"
  status: "active"  # active | resolved | escalated

  # 双轴评审
  axes:
    standards:
      verdict: "fail"
      violations:
        - id: "S-001"
          severity: "major"       # fatal | major | minor
          rule: "no_test"
          message: "Task task-1 无对应测试文件"
          paths: ["src/pipeline/retry.py"]
          fix: "在 tests/ 下创建 test_retry.py"
    spec:
      verdict: "fail"
      violations:
        - id: "SP-001"
          severity: "fatal"
          rule: "spec_deviation"
          message: "实现偏离了 Spec 中定义的 goals: 缺少幂等校验"
          paths: ["src/pipeline/retry.py"]

  # 统计数据
  stats:
    total_violations: 3
    fatal: 1
    major: 1
    minor: 1
```

### 3.2 FixRecord（修复记录）

```yaml
# review/<spec-id>/f1.yaml
fix:
  id: "f1"
  review_id: "r1"
  created_at: "2026-08-19T15:00:00Z"
  resolved_violations: ["S-001", "SP-001"]

  # 修复摘要
  summary: |
    - 为 task-1 补充了 tests/test_retry.py（3 个测试用例）
    - 在 retry 逻辑中增加了幂等校验（idempotency_key）

  # 残余风险（未修复的 minor 问题）
  residual:
    - id: "S-002"
      rule: "doc_drift"
      message: "README 未同步更新"
      decision: "登记残余风险，v0.3 修复"
```

### 3.3 ReviewGate（评审门禁，集成到 sop.yaml）

```yaml
gates:
  review_gate:
    kind: "review"
    blocking: true
    enabled: true
    bind_to_stage: 2  # plan 阶段出口门禁检查评审
    max_rounds: 5     # 最大审核轮次，超限 escalate
    require_clear: true  # 要求无 fatal 违规
```

---

## 4. 新增命令

### 4.1 `devflow review`

**触发评审**：调用子代理并行做双轴评审（Standards × Spec），产出评审报告。

```bash
# 对当前阶段做评审（默认）
devflow review

# 对指定 Spec 做评审
devflow review --spec 20260819-pipeline-retry

# 指定评审轮次（用于复核）
devflow review --round 2
```

**行为**：
1. 读取当前 Spec + Plan + Contract + 代码变更
2. 启动并行子代理：Standards 评审器 + Spec 吻合度评审器
3. 合并两路报告，写入 `review/<spec-id>/r<N>.yaml`
4. 更新 `progress.yaml` 账本（追加评审记录）
5. 输出违规清单（按 severity 分级）

**阻断条件**：
- 有 fatal 违规 → 阻断推进，`devflow next` 返回违规清单
- 无 fatal 违规 → 不阻断，但违规信息在 `devflow status` 中可见

### 4.2 `devflow fix <violation-id>`

**修复违规**：记录修复行为，标记对应违规为已解决。

```bash
# 修复单条违规
devflow fix S-001 --note "已补充测试文件 tests/test_retry.py"

# 批量修复
devflow fix S-001 SP-001 --note "补充测试 + 幂等校验"

# 登记残余风险（不修复，但记录）
devflow fix S-002 --residual "README 未同步，v0.3 修复" --skip
```

**行为**：
1. 验证修复是否真实完成（可选：自动检测——如 `no_test` 重跑检查）
2. 写入 `review/<spec-id>/f<N>.yaml`
3. 更新对应 `review/<spec-id>/r<N>.yaml` 中违规状态
4. 追加账本记录

### 4.3 `devflow audit`（增强）

**现有 `audit` 命令扩展**：新增"审核台账"输出。

```bash
devflow audit
# → 现有红线审计结果 + 审核台账摘要
#   Review R1: 3 violations (1 fatal, 1 major, 1 minor) — 1 resolved, 1 residual
#   Review R2: 1 violation (1 major) — 0 resolved
#   Review R3: 0 violations — PASS
```

### 4.4 `devflow history`（新增）

**查看审核历史**：展示审核闭环的完整生命线。

```bash
devflow history review
# → R1: 2026-08-19 14:30  FAIL  (3 violations)
#   ├─ F1: 2026-08-19 15:00  resolved: S-001, SP-001
#   └─ residual: S-002 (doc_drift, v0.3)
# → R2: 2026-08-19 15:30  FAIL  (1 violation)
#   ├─ F2: 2026-08-19 16:00  resolved: S-003
#   └─ 0 residual
# → R3: 2026-08-19 16:30  PASS  — 闭环终止
```

---

## 5. 与八阶段工作流的集成

### 5.1 评审门禁绑定

```
阶段 2 (plan) 出口 ── 新增 review_gate ──→ 阻断
阶段 3 (contract) 出口 ── 新增 review_gate ──→ 阻断
阶段 6 (review) 出口 ── 原有 ci_green + 新增 review_gate ──→ 双重阻断
```

### 5.2 审核触发时机（默认策略）

| 阶段 | 自动触发 | 说明 |
|---|---|---|
| 2 (plan) | ✅ | Plan 创建后自动触发 Standards 评审 |
| 3 (contract) | ✅ | Contract 完成后自动触发 Spec 吻合度评审 |
| 4 (implement) | ❌ | 代码实现中，不中断 |
| 5 (verify) | ❌ | 测试阶段，由 tests_pass 门禁保障 |
| 6 (review) | ✅ | 提交前做全量双轴评审 |
| 7 (finish) | ❌ | 仅做账本完整性检查 |

### 5.3 最大轮次保护

```yaml
gates:
  review_gate:
    max_rounds: 5        # 最多 5 轮审核循环
    escalation: "human"  # 超限后升级给人处理
```

当 `review_round >= max_rounds` 时：
- 自动升级为 **escalated** 状态
- 不再自动阻断，但标记为"需人工介入"
- 在 `devflow status` 中以 🔴 高亮显示

---

## 6. 台账与审计

### 6.1 账本条目扩展

`progress.yaml` 新增 `action` 类型：

```yaml
entries:
  - phase: 2
    action: "review"          # 新增
    review_id: "r1"
    verdict: "fail"
    fatal_count: 1
    major_count: 1
    minor_count: 1

  - phase: 2
    action: "fix"             # 新增
    fix_id: "f1"
    resolved: ["S-001", "SP-001"]
    residual: ["S-002"]

  - phase: 2
    action: "review"          # 复核
    review_id: "r2"
    verdict: "pass"
```

### 6.2 审计完整性

审计闭环的不可篡改性通过以下机制保障：

1. **append-only 账本**：每条审核/修复记录在 `progress.yaml` 追加，历史不可覆盖
2. **review/ 目录**：每轮评审报告和修复记录独立文件，不可删除（可通过 git 历史追溯）
3. **审计台账**：`审计整改台账.md` 记录全生命周期，由引擎自动生成，不由人工维护
4. **终止判断**：仅当 `verdict == "pass"` 时才允许推进，否则 `devflow next` 阻断

---

## 7. 与现有审计角色的关系

```
现有红线审计 (devflow audit)        新增审核闭环 (devflow review)
─────────────────────              ─────────────────────
自动扫描，10 条固定规则              双轴子代理，上下文理解
无状态，单次快照                      有状态，多轮循环
输出违规清单                         输出违规 + 修复 + 台账
不阻断推进                          阻断推进（fatal 不放过）
代码级检查                          方案级检查
```

两者互补但不重叠：
- `audit` 是"静态扫描"，适合频繁执行（每次 commit 前）
- `review` 是"深度评审"，适合关键节点（plan/contract/review 阶段出口）

---

## 8. 实现路线

| 阶段 | 内容 | 工作量 |
|---|---|---|
| M0 | 新增 `review/` 目录 + `ReviewReport`/`FixRecord` 模型 + 账本动作类型 | 1 天 |
| M1 | `devflow review` 命令：子代理 prompt 模板 + 并行双轴评审 + 报告写入 | 2 天 |
| M2 | `devflow fix` 命令：修复记录 + 违规状态更新 + 账本写入 | 1 天 |
| M3 | `review_gate` 集成到状态机：`devflow next` 检查评审状态 | 1 天 |
| M4 | `devflow history` 命令 + 自动台账生成 | 1 天 |
| M5 | 5 轮最大保护 + escalation 机制 | 0.5 天 |
| M6 | 测试：评审闭环全流程 13 条验收标准 | 1 天 |

**总计 7.5 天**，可并行推进 M0-M1（模型 + 评审命令，强关联），M2-M3（修复 + 门禁，强关联），M4-M5（历史 + 保护，可独立）。

---

## 9. 验收标准

| # | 验收条件 |
|---|---|
| 1 | `devflow review` 产出 review/<spec-id>/r1.yaml 报告文件 |
| 2 | 报告包含 Standards 和 Spec 两个轴，每轴有 verdict 和 violations 列表 |
| 3 | 违规按 fatal/major/minor 分级 |
| 4 | 有 fatal 违规时 `devflow next` 阻断返回违规清单 |
| 5 | 无 fatal 违规时 `devflow next` 正常推进 |
| 6 | `devflow fix S-001` 记录修复，更新违规状态 |
| 7 | 修复后 `devflow review --round 2` 重新评审，老报告不覆盖 |
| 8 | 累计 5 轮审核未通过 → 自动升级 escalated，不再阻断 |
| 9 | 审核闭环全流程在 progress.yaml 账本中有完整记录 |
| 10 | `devflow history review` 展示审核生命线 |
| 11 | 残余风险可登记，`devflow status` 中显示 |
| 12 | 45 个旧测试 + 13 个新测试全部通过 |

---

## 10. 与 MVP 的关系

```
┌────────────────────────────────────────────┐
│  MVP (v0.1) — 当前已实现                    │
│  ├─ 8 阶段状态机 + 11 个 CLI 命令            │
│  ├─ 10 条红线审计                            │
│  └─ 45 个测试全通过                          │
│                                            │
│  v0.2 审核闭环 — 本方案                      │
│  ├─ devflow review / fix / history 命令      │
│  ├─ 双轴评审（Standards × Spec）             │
│  ├─ 多轮审核循环 + 终止判断                   │
│  ├─ 评审门禁（阻断推进）                      │
│  └─ 审计台账自动化                            │
│                                            │
│  v0.3 路线（后续）                           │
│  ├─ 架构熵检测（每 20 commit）                │
│  ├─ Debug 反馈环律                           │
│  └─ WorkBuddy / MCP 适配                    │
└────────────────────────────────────────────┘
```

---

## 附录 A：子代理 Prompt 模板（Standards 轴）

```
## 角色
你是一个代码标准评审员。你的任务是审查当前阶段的工件（Spec/Plan/Contract/代码），
对照项目 sop.yaml 中定义的编码规范，输出违规清单。

## 输入
- Spec: {spec_content}
- Plan: {plan_content}
- 代码变更: {git_diff}

## 输出格式
请输出 YAML 格式的违规清单，每条违规包含：
- id: 唯一编号（格式 S-001）
- severity: fatal | major | minor
- rule: 违反的规则名称
- message: 问题描述
- paths: 相关文件路径列表
- fix: 建议修复方案

## 规则库
- no_test: 代码变更包含 .py 文件但无对应 test 文件
- cross_module_import: 导入了 forbidden_import 中定义的模块
- doc_drift: 代码行为与文档描述不一致
- huge_pr: 变更文件数超过 pr_max_files
- naming_convention: 命名不符合项目规范
- type_hint: 公开函数缺少类型注解
```

## 附录 B：子代理 Prompt 模板（Spec 轴）

```
## 角色
你是一个 Spec 吻合度评审员。你的任务是审查当前阶段的实现是否与 Spec 保持一致。

## 输入
- Spec: {spec_content}
- Plan: {plan_content}
- Contract: {contract_content}
- 代码变更: {git_diff}

## 输出格式
请输出 YAML 格式的违规清单，每条违规包含：
- id: 唯一编号（格式 SP-001）
- severity: fatal | major | minor
- rule: 违反的规则名称
- message: 问题描述
- paths: 相关文件路径列表
- fix: 建议修复方案

## 检查要点
1. 实现是否覆盖了 Spec 中定义的所有 goals？
2. 实现是否引入了 Spec non_goals 中明确排除的功能？
3. Contract 定义的接口签名是否与实现一致？
4. 测试用例是否覆盖了 Spec 中描述的场景？
5. 实现是否偏离了 Spec 中定义的 problem 范围？
```