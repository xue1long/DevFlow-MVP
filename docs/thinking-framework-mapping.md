---
title: DevFlow 思维模型映射
subtitle: 24 种职场思维 × DevFlow 引擎机制 · 落地状态追踪
version: 1.0
date: 2026-08-19
status: active
tags: [devflow, thinking, 思维模型, 映射]
related:
  - ./CHANGELOG.md#v033-思维模型落地
  - ../模块×思维匹配手册.md
  - ./audit-ledger.md
---

# DevFlow 思维模型映射

> **目标**:把职场思维模型**变成引擎的默认规则**,而不是靠 agent 自觉。
> **方法**:每个思维 → 一个字段 + 一条检查规则(或已有机制正名)。
> **原则**:宽松默认——字段可选,有值才检查,MINOR 提示不阻断。

---

## 一、落地状态总览(24 思维)

| 状态 | 含义 | 数量 |
|---|---|---|
| ✅ **已落地(字段+检查)** | v0.3.3 实现,引擎自动执行 | 9 |
| 🔵 **已隐含(引擎已有)** | 机制已存在,本表正名 | 10 |
| 🟡 **部分(依赖人工)** | 引擎记录,判断靠人 | 3 |
| ⚪ **不落地** | 引擎无法自动判断 | 2 |

---

## 二、✅ 已落地(9 项,v0.3.3)

> 每个思维 → 一个可选字段 + 一条 MINOR 检查规则,在 review Spec 轴自动执行。

| 思维 | 字段 | 检查规则 | 触发条件 |
|---|---|---|---|
| **第一性原理** | `Spec.assumptions` | `thinking_first_principles` | 未声明底层假设 / 假设全占位 |
| **逆向思维** | `Spec.premortem` | `thinking_premortem` | 未做事前验尸(方案怎么失败) |
| **损益思维** | `Spec.tradeoff` | `thinking_tradeoff_decision` / `_tradeoff` | 有 options 无 decision / 有 decision 无 tradeoff |
| **奥卡姆剃刀** | (用 options) | `thinking_occam` | options > 1 时提示确认最简方案 |
| **假设思维** | `Spec.assumptions` | `thinking_hypothesis` | assumptions 非空时提示制定验证计划 |
| **二八法则** | `Task.priority` | `thinking_pareto` | 无 P0 / P0 未完成 |
| **能力圈** | `Task.owner_skill` | `thinking_capability_circle` | 任务标 learn/collab(圈外) |
| **反馈思维** | `Task.acceptance` | `thinking_feedback_loop` | 任务缺可验证验收标准 |
| **冗余思维** | `Plan.buffer` | `thinking_redundancy` | 计划未预留缓冲 / buffer=0 |

**关闭开关**:`sop.yaml`:

```yaml
thinking:
  enabled: true     # false = 完全跳过思维检查
  severity: "minor" # minor | off
```

---

## 三、🔵 已隐含(10 项,引擎机制正名)

> 这些思维 DevFlow 已经有对应机制,只是以前没标名。**价值**:团队知道"引擎在哪个环节体现哪种思维",提升可解释性。

| 思维 | 引擎机制 | 位置 |
|---|---|---|
| **终局思维** | `Spec.goals` 必填(先定目标) | `model/spec.py` |
| **边界思维** | `Spec.non_goals` 必填(明确不做) | `model/spec.py` |
| **系统思维** | append-only 账本(完整链路可追溯) | `storage/fs_backend.py` |
| **证伪思维** | 双轴评审 Standards×Spec(主动找推翻证据) | `engine/review_engine.py` |
| **概率思维** | 违规分级 fatal/major/minor + residual 登记 | `model/review.py` |
| **贝叶斯思维** | 评审防死循环(≤5 轮,动态更新判断) | `engine/review_engine.py` |
| **闭环思维** | `skip-task --reason` 必填(跳过也有交代) | `cli.py` |
| **博弈思维** | 多角色独立评审(看见各方利益) | audit-ledger 审计流程 |
| **归因思维** | `fix --residual` 区分已修/残余 | `engine/review_engine.py` |
| **5Why 根因** | `fix` 需要 reason + review 轮次机制(追问到收敛) | `engine/review_engine.py` |

---

## 四、🟡 部分落地(3 项,引擎记录靠人判断)

| 思维 | 现状 | 说明 |
|---|---|---|
| **概率思维(PlanB)** | `residual` 字段可登记"未做但已知" | 引擎记录残余,是否准备 PlanB 靠 agent |
| **金字塔原理** | CLI 输出结构化(结论先行) | 展示层微调,非核心规则 |
| **灰度思维** | 门禁 blocking/advisory 两档(可行解优先) | 已内建,无需字段 |

---

## 五、⚪ 不落地(2 项,引擎无法自动判断)

| 思维 | 原因 |
|---|---|
| **类比思维(慎用)** | 无法自动判断"类比是否被第一性校验" |
| **杠杆思维** | 无法自动判断"是否利用了模板/SOP/工具" |

---

## 六、使用示例

### 写一个符合思维框架的 Spec

```yaml
# specs/20260819-xxx.yaml
id: 20260819-xxx
title: 示例方案
problem: 当前批量重试机制无法处理偶发失败(≥10 字符)
goals:
  - 实现指数退避重试
non_goals:
  - 不实现消息队列
assumptions:            # 第一性原理:底层事实
  - 失败率 < 5%
  - 单次重试耗时 < 2s
premortem:              # 逆向思维:事前验尸
  - 重试风暴导致雪崩
  - 幂等性破坏导致重复执行
options:
  - 方案A: 指数退避
  - 方案B: 固定间隔
decision: 方案A
tradeoff: 放弃方案B的简单实现(机会成本)
```

### 运行 review 看到思维提示

```bash
devflow review
# → SP-3 [minor] thinking_first_principles: 未声明 assumptions(底层假设清单)...
# → SP-4 [minor] thinking_premortem: 未做事前验尸(premortem)...
# → 全部 MINOR,不阻断推进
```

---

## 七、与「模块×思维匹配手册」的关系

- **手册**:决定"什么场景用什么思维"(9 类模块 × 主辅反组合)
- **本表**:决定"引擎在哪落地哪种思维"(字段 + 检查规则)
- **协作方式**:手册指导 agent 选思维,本表让引擎自动执行部分思维

---

**文档结束 · DevFlow 思维模型映射 v1.0 · 2026-08-19**
