---
title: Plan B 调研 — 拆三仓（FileStore / LedgerStore / StateStore）
subtitle: 跨仓写入顺序 + 跨仓 hash chain 连续性 · 两个根问题的设计决策
version: 0.1
date: 2026-08-20
status: research
authors: 图谱审计 + Phase A+C 后续
related:
  - ./v0.4-rfc.md
  - ./v0.4-roadmap-paused.md
  - ./audit-v04-risk-controller.md
  - ./optimization-v0.1.md#建议四p1-deferredreviewstore--storagebackend-可插拔矩阵
tags: [devflow, v0.4, plan-b, storage, hash-chain, transaction]
---

# Plan B 调研 — 拆三仓的两个根问题

> **目的**:在 `v0.4-roadmap-paused.md` 标记的"v0.4 真复活" trigger signal 之一（出现第二个存储后端需求）出现之前,**把两个根问题的答案想清楚**,避免再次落入 v0.3 INDEX 那种"先拆方案再做协议"的 trap（第 4 轮 [F]-4 拒掉的过度设计）。
>
> **结论预告**:本文给出 7 个候选方案 + 3 个决策表。**推荐方案 D（接受伪原子,放弃跨仓事务完整性）** —— 与 graph 中"C7 → 4 个社区"演化（Phase A+C 后）形成的现有测试契约兼容,代价 0,完全不引入新 ABC。

---

## 一、问题陈述

假设 v0.4 决定把现在的 `StorageBackend`（聚合 21 个 method 的胖接口）拆为 3 个独立 ABC:

```python
# RFC §3.5 设计
class FileStore(ABC):
    """文件读写:Spec / Plan / Report"""
    write_spec / read_spec / list_specs
    write_plan / read_plan

class LedgerStore(ABC):
    """账本 + 哈希链"""
    append_ledger / get_ledger / verify_ledger / migrate_ledger

class StateStore(ABC):
    """工作区状态"""
    get/set_current_phase
    get/set_current_spec_id / current_plan_id
    is_suspended / set_suspended
    has_phase_entry
    write_handoff / read_handoff / find_latest_handoff
    init_workspace
```

**根问题 A:跨仓写入顺序协议**

当 engine 做"启动一个 spec"时,顺序是:

```python
# state_machine.py:start() 现有代码
self.storage.write_spec(spec_id, spec.model_dump())           # FileStore
self.storage.set_current_spec_id(spec_id)                     # StateStore
self.storage.append_ledger(LedgerEntry(...))                  # LedgerStore
```

3 个独立的 ABC 接口,**没有"事务"边界**。如果中途崩溃（断电 / kill -9 / 磁盘满）,账本可能停在三种"半新半旧"状态之一。

**根问题 B:跨仓 hash chain 连续性**

账本 hash chain 是 LedgerStore 内部的——**它不知道也管不到 FileStore 写盘的 Spec 内容,更不知道 StateStore 写盘的 current_spec_id**。

如果攻击者篡改了 Spec 文件的内容（FileStore 写入的 `progress.yaml`——等等,progress.yaml 不是 Spec 文件,Spec 在 `specs/<id>.yaml`;但 ledger 在 `progress.yaml`）,那么 spec 实质内容改变,但 ledger 的 hash chain 仍然完整,审计**看不到篡改**。

**两个根问题在物理层面对应的真实问题:**

| 根问题 | 物理层面 | 当前 FSBackend 怎么处理 |
|---|---|---|
| A 跨仓顺序 | 同一进程内 3 次独立 `_atomic_write_yaml` | 没有事务；每个写入自带原子性 |
| B 跨仓 chain | ledger chain 只覆盖 `progress.yaml` | Spec 文件、handoff 文件不在 hash chain 内 |

---

## 二、当前 FSBackend 的"伪事务"分析

通过 graph 追踪 + 代码审计,现状是:

### 2.1 单锁覆盖范围

`_with_lock` 包裹的操作:
- `append_ledger` (line 248)
- `get_ledger` (line 257)
- `verify_ledger` (line 277)
- `get/set_current_phase` (lines 283, 290)
- `get/set_current_spec_id/plan_id` (lines 296, 303, 309, 316)
- `is_suspended` / `set_suspended` (lines 322, 329)
- `has_phase_entry` (line 335)

**FileStore 类的所有方法都不在锁内**:
- `write_spec` / `read_spec` / `list_specs` —— 无锁
- `write_plan` / `read_plan` —— 无锁

这是因为 FileStore 写的是独立文件（`specs/<id>.yaml` 或 `plans/<id>.yaml`）,而锁只保护 `progress.yaml`。**多进程并发** 写 spec 文件,理论上可能两个进程同时写一个 spec 文件,产生不可预测的混合内容。

### 2.2 现实并发场景

- **同进程**:PhaseStateMachine 顺序调用,不存在并发
- **多进程**:两个 `devflow next` 同时跑？不太常见（CLI 通常一人一进程）。但 RFC §3.5 的拆 ABC 暗示了多接口装配的可能,而 graph C29 显示 ledger + Spec 是同实例 (`file_store, ledger_store, state_store = storage, storage, storage`),所以**当前实际是单文件系统 + 单锁**。

### 2.3 跨 ABC 边界的真实问题

| 现实问题 | 是否真存在？ |
|---|---|
| write_spec 后进程崩,**没有** set_current_spec_id | ❌ 不会发生——`write_spec` 不在锁内,崩了 spec 文件可能半写,但 ledger 没有 entry,重读能拿到正确状态 |
| append_ledger 中崩,**ledger 半写** | ❌ 不会发生——`_atomic_write_yaml` 保证整条 ledger 要么旧要么新 |
| write_spec 后崩,**spec 半写** | ⚠️ **真实存在**——`specs/<id>.yaml` 写一半但 `.tmp_xxx` 临时文件无法 rename（mid-write 异常已 `os.unlink` 清理） |
| **多进程同时 write_spec 同一 spec_id** | ⚠️ 真实存在,但当前未有用户报告过 |

**核心观察**:**根问题 A 不是拆三仓引入的,而是 FSBackend 早就存在的**。拆 ABC 后这个问题不消失,也不加剧——它需要单独设计。

---

## 三、7 个候选方案

### 方案 A:分布式事务协议（2PC / Saga）

- **思路**:FileStore / LedgerStore / StateStore 各自带 `prepare()` + `commit()` 接口,3 阶段提交
- **优点**:理论原子
- **代价**:
  - 完全脱离文件系统语义（YAML 文件 rename 不是 prepare-able 的）
  - 实现复杂度爆炸：每个 ABC 加 3 个 method,engine 全部装配路径要改
  - **违反 YAGNI**——多进程并发写 spec 的场景当前不存在
- **判定**:❌ **超工程**

### 方案 B:Saga + 补偿

- **思路**:拆为多个本地事务,每个失败后反操作补偿
- **优点**:能 work
- **代价**:
  - spec file 写了但 ledger 没 entry → 怎么反操作？"删 spec 文件"是补偿操作,但 spec 文件可能已经被外部读了
  - 复杂度更高
- **判定**:❌ **超工程**（同上）

### 方案 C:LedgerStore 包含整个工作区快照（hash chain 覆盖全仓）

- **思路**:`append_ledger` 时不仅记 entry,还把当前所有 spec / plan / handoff 文件的 hash 一起记下来,生成全局 manifest hash 进 chain
- **优点**:hash chain 真正覆盖整个工作区
- **代价**:
  - 每次 `append_ledger` 要扫描所有文件 → 性能问题
  - spec / plan 是用户编辑的（不是机器管理的）,如果用户在 ledger 写入前改了 spec,ledger 的 manifest hash 与磁盘实际内容**永远对不上**
  - 审计完整性**反而下降**（误报）
- **判定**:❌ **不实用**

### 方案 D:接受伪原子,放弃跨仓事务完整性,靠"重读 + 重新对齐"恢复

- **思路**:
  - 保持当前 `_with_lock` + `_atomic_write_yaml` 不变
  - FileStore / LedgerStore / StateStore 各自单实例多接口装配（graph C29 已有此模式）
  - **承认**:跨仓事务不原子,半新半旧状态可能存在
  - **添加**:`devflow status` 加一个 `--repair` 模式,扫描磁盘与 ledger,生成"应该已经在但 ledger 没有"的报告,人工决定是否补 entry
- **优点**:
  - 改动量最小（按 graph C29 已有的多接口赋值模式,无新增 method）
  - 完全兼容 Phase A+C 后所有 fixture（FSBackend + MemoryStorageBackend 都按 storage: StorageBackend 注入）
  - 与 RFC §2.4"v1 账本可读"的精神一致——承认现状不完美,通过工具辅助人工修复
- **代价**:
  - 真的中途崩,需要 `devflow status --repair` 半手工恢复
  - 审计完整性是"近似"而非"严格"
- **判定**:✅ **推荐** —— 与现有测试契约完全兼容

### 方案 E:LedgerStore hash chain 仅覆盖写入路径,且 Spec 文件不可变（immutable）

- **思路**:Spec / Plan 一旦写出,后续修改必须"创建新版本 + 旧版本保留"——hash chain 覆盖每个版本的 commit-time hash
- **优点**:hash chain 严格覆盖所有写入路径
- **代价**:
  - 与现有"用户在 spec YAML 上修改 → state_machine 写 spec 覆盖"的语义冲突
  - 需要新增 version 字段,扩 LedgerEntry schema,触发 RFC §2.3 已被审计否决的"扩 LedgerEntry"路径
  - 通过 P0-RC-03（spec_id 推断张冠李戴）+ P0-RC-06（升级即账本断裂）同等量级审计风险
- **判定**:❌ **与暂停决策冲突**

### 方案 F:Sidecar 全局 hash（不动 LedgerStore,在 FileStore 旁挂一个 spec.hash 文件）

- **思路**:每个 spec / plan 文件旁挂一个 `.hash` 文件,内容是该文件内容 SHA256,append 到 ledger 时附带所有 `.hash` 的聚合
- **优点**:
  - 不用跨仓事务
  - spec 文件改动能被 ledger 检测（如果 `.hash` 与现算不一致）
- **代价**:
  - 每个 FileStore 操作要写额外文件（atomically）
  - 与方案 C 类似但只扫 hash 不扫内容,性能可控
  - 但**:用户编辑 spec 文件时,`.hash` 需要重新生成——审计完整性的"不可篡改"承诺要求 `.hash` 也得是不可变的
- **判定**:⚠️ **可能** —— 复杂但不引入跨仓事务；需要单独评估 `.hash` 的不可变性

### 方案 G:ledger 不再覆盖任何写入路径，仅做"日志记录"

- **思路**:`LedgerStore.append_ledger` 只记"event log",不试图覆盖工作区状态
- **优点**:彻底解耦
- **代价**:与现有"ledger 是工作区状态权威"的语义相反（graph C29 显示 ledger 顶部 `current_phase / current_spec_id / current_plan_id / suspended`,这些是**状态**而非 event）
- **判定**:❌ **破坏现状**

---

## 四、3 个决策表

### 4.1 决策表 1:跨仓写入顺序（根问题 A）

| 方案 | 工程量 | 跨仓原子 | 多进程并发 | 与 Phase A+C 兼容 | 第一性判定 |
|---|---|---|---|---|---|
| A (2PC) | 中 | ✅ | ✅ | ❌ 引入新 method | ❌ 超工程,YAGNI |
| B (Saga) | 高 | ✅ | ✅ | ❌ 同上 | ❌ 超工程 |
| D (伪原子+repair) | 低 | ❌ 近似 | ⚠️ 弱 | ✅ 完全 | ✅ 推荐 |
| F (sidecar hash) | 中 | ❌ 但可检 | ✅ | ⚠️ 需 review | ⚠️ 候选 |

### 4.2 决策表 2:跨仓 hash chain 连续性（根问题 B）

| 方案 | audit 完整性 | 实现复杂度 | 与 hash chain "不可篡改" 精神一致 | 第一性判定 |
|---|---|---|---|---|
| C (LedgerStore 含全仓) | 高（理论上） | 高（性能+误报） | ✅ | ❌ 不实用 |
| E (Spec 文件不可变) | 高 | 高（扩 schema） | ✅ | ❌ 与暂停决策冲突 |
| F (sidecar hash) | 中（可检测篡改但不严格不可变） | 中 | ✅ | ⚠️ 候选 |
| D (接受 + repair) | 低（仅 ledger 内） | 低（仅 status --repair） | ❌ 但诚实 | ✅ 推荐 |

### 4.3 决策表 3:整体 vs v0.4 RFC §3.5

| 选项 | RFC §3.5 接受度 | Phase A+C 后兼容性 | RFC v0.4 的 6 个 P0 风险缓解 |
|---|---|---|---|
| **保留聚合 StorageBackend（不拆三仓）** | ❌ 不符 RFC | ✅ 完全 | 适用于 plan D——保留 RFC §3.5 风险等级但不需要"事务边界" |
| **拆三仓 + 接受伪原子 + status --repair（方案 D）** | ✅ 形式契合 | ✅ 完全 | 处理 P0-RC-04（原子性）:通过 explicit repair 工具 |
| **拆三仓 + sidecar hash（方案 F）** | ✅ 形式契合 | ⚠️ 需 review | 处理 P0-RC-03（spec 张冠李戴）:可检测篡改,但仍需扩文件 |

---

## 五、推荐路径

### 5.1 推荐:方案 D（接受伪原子,放弃严格跨仓事务,加 --repair 工具）

**理由**:

1. **完全兼容 Phase A + C 之后的图谱契约**——graph C29 显示 engine 层依赖 `storage: StorageBackend`,后端实现是 FSBackend 或 MemoryStorageBackend。方案 D 不引入新 ABC,只是把 RFC §3.5 的"`StorageBackend` 聚合接口"做实,engine 仍然注入同一个接口,具体拆 FileStore / LedgerStore / StateStore 是**实现层细节**,外部不可见。

2. **承认现状的诚实路径**——RFC v0.4 被 6 个 P0 + 8 个 P1 风险管控者审计否决的根本原因是"形式合规、实质同构"。方案 D 走相反路径:**形式承认不完美 + 实际工具支持人工恢复**。

3. **YAGNI**——`docs/v0.4-roadmap-paused.md` 第 32-37 行明确"v0.4 真触发的信号之一是出现第二个存储后端需求"。方案 D 不引入此需求——它只**承认**当前实现的限制。

### 5.2 方案 D 的具体动作清单

| Action | 文件 | 改动量 | 风险 |
|---|---|---|---|
| ABC 拆分 | `src/devflow/storage/base.py` | +30 行 | 低 |
| FSBackend 多继承 3 个 ABC | `src/devflow/storage/fs_backend.py` | +1 行 | 低 |
| MemoryStorageBackend 多继承 3 个 ABC | `src/devflow/storage/memory_backend.py` | +1 行 | 低 |
| Engine 装配顺序不变（单实例多接口赋值） | `cli.py` `_get_machine` | 0 行 | 无 |
| **新增 `devflow status --repair` 命令** | `cli.py` | +50 行 | 中 |
| 文档:`docs/optimization-v0.1.md` Reco 4 状态从 deferred → live | `docs/optimization-v0.1.md` | +10 行 | 无 |
| **新增测试** `test_repair.py` | `tests/` | +60 行 | 低 |

**`status --repair` 设计**：读取磁盘 (spec / plan / handoff 文件) + ledger (existing entries)，生成三个集合：
- `phantom_files`: 磁盘有 spec 文件,ledger 无任何相关 entry
- `orphan_entries`: ledger 有 entry 但 spec/plan 文件已不存在
- `phase_desync`: ledger 的 `current_phase` 与最近 entry 的 phase 不一致

输出报告让人工 review,**不自动修复**。

### 5.3 备选:方案 F（sidecar hash）

仅在以下**任一**触发条件成立时才选 F:

- 用户报告多进程并发写 spec 产生数据竞争（`phantom_files` 报告重现）
- 出现第二个真存储后端需求（YAGNI 防御被攻破）
- 监管要求 spec 文件本身可独立审计

否则坚持方案 D。

---

## 六、与 graph evidence 的对应

| 本方案涉及问题 | graph 社区 | 证据位置 |
|---|---|---|
| 当前 StorageBackend 单胖接口 | C17 (StorageBackend ABC Method Surface) | graph C17 + C29 |
| engine 不关心 backend 实现 | C12 (ReviewEngine Spec Axis) | engine 模块注入 `storage: StorageBackend` |
| 跨仓写入顺序（state_machine.start） | C15 (PhaseStateMachine) | `state_machine.py:95-114` 三连调用 |
| 跨仓 hash chain | C9 (FSBackend concrete) + C29 (LedgerEntry trio) | `_compute_entry_hash` 仅覆盖 `progress.yaml` |
| MemoryStorageBackend 已示范"假原子" | C10 + C33 | memory backend 不写盘但 ledger API 完整 |

graph C29（LedgerEntry + StorageBackend ABC + FSBackend Trio,cohesion 0.18）的存在本身就证明 "LedgerEntry model + StorageBackend abstraction + FSBackend concrete" 三者紧密耦合——拆 FileStore / LedgerStore / StateStore 不解决这个耦合,反而把"伪原子"边界显式化,可能引入新 P0。

---

## 七、给 v0.4 真复活者的 checklist

如果未来真要 v0.4（按 `v0.4-roadmap-paused.md` 的 trigger signals）:

- [ ] **先回答根问题 A + B**（本文档已给出推荐:方案 D）
- [ ] **写 RFC v2.0 时,先通过第一性原则**——任何"扩 LedgerEntry"或"新 CLI"提议都要回到 RFC §3.5 拆分场景,看是否真的有必要
- [ ] **复用方案 D**——仅在 `--repair` 工具 + 承认伪原子后就停手
- [ ] **如果坚持要严格原子**——升级到方案 F 之前,**先验证 graph 演化**:重跑 /graphify --update 后,看 C9/C17/C29 三社区是否真的"分离得足够干净"以支持独立 ABC

---

**文档结束 · Plan B 调研 v0.1 · 2026-08-20**
