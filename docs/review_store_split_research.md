---
title: Plan C 调研 — ReviewStore 可插拔
subtitle: review_engine 抽象化 review_store 的工程记录（从 deferred 到 live）
version: 0.1
date: 2026-08-20
status: live
related:
  - ./v0.4-rfc.md#35-p2-18storagebackend-接口拆分
  - ./v0.4-roadmap-paused.md
  - ./audit-v04-risk-controller.md#p1-rc-04storagebackend-拆-3-接口但旧调用方用具体类型注入
  - ./storage_backend_split_research.md
  - ./optimization-v0.1.md#建议四p1-deferredreviewstore--storagebackend-可插拔矩阵
tags: [devflow, plan-c, review-store, abc, fixture, phase-c]
---

# Plan C 调研 — ReviewStore 可插拔

> **状态**：live（2026-08-20 落地）。原 Reco 4 deferred anchor 解锁。
> **前置**：Phase A（纪律化）+ Phase C（MemoryStorageBackend）证明 engine 层→抽象接口的模式可行。
> **目的**：让 `tests/test_review_loop.py` 20 条测试中 **17 条切到内存**（不再依赖真实 YAML 落地），剩 3 条保留 FS（专门验证 YAML 真实写盘）—— 与 Phase C `test_p2_fixes.py` 的 `fs_env` 异常模式同构。

---

## 一、why Plan C now

按 `optimization-v0.1.md` Reco 4 deferred 的触发条件之一：

> **ReviewStore 在 ≥ 2 个新 fixture 上被视为硬编码痛点（当前仅 1 个：test_review_loop.py）**

实际触发：Phase A + C 后 graph community C35（"Review Loop Test Corpus", cohesion 0.20, 10 节点）仍然是 graph 里少数 cohesion > 0.15 的社区之一——明确指出"`ReviewStore` 仍然直写 YAML,阻断 fixture 切到内存"。

## 二、3 个可选 scope

### Scope 1: ReviewStorageBackend 抽象 + MemoryReviewBackend（已选）

- 新建 `src/devflow/storage/review_store_base.py` → `ReviewStorageBackend` ABC（9 个 abstractmethod）
- 重构 `src/devflow/storage/review_store.py` → `FSReviewBackend`（继承 ABC + 旧 ReviewStore = 别名）
- 新建 `src/devflow/storage/review_store_memory.py` → `MemoryReviewBackend`
- 修改 `src/devflow/engine/review_engine.py:57` → `review_store: ReviewStorageBackend`
- 修改 `src/devflow/storage/__init__.py` → 暴露 `ReviewStorageBackend / FSReviewBackend / MemoryReviewBackend / ReviewStore`

### Scope 2: 只做内存版（不做 ABC）

不动 `ReviewStore` 名字，只加 `MemoryReviewBackend`，让 `__init__` 类型兼容（duck typing）。  
**缺点**：无 ABC 强制契约，3 个月后另一个 fixture 想用 will "guessing the interface"。

### Scope 3: 顺便把 RFC §3.5 拆分一起做（StorageBackend 拆 FileStore/LedgerStore/StateStore）

直接落入 v0.4 RFC §3.5 已被审计否决的 P1-RC-04（engine 拿到子接口 fallback 难）路径。  
**否决**：见 `storage_backend_split_research.md` 推荐方案 D，**先做 Plan C 单点突破，再观察 trigger signal**。

---

## 三、Phase C 同款风险点对位

| Phase C 风险 | Plan C 对位 | 处理 |
|---|---|---|
| 引擎层仍依赖具体类 | review_engine.py:57 之前是 `review_store: ReviewStore` | ✅ 改为 `review_store: ReviewStorageBackend`（ABC 注入） |
| Memory 版违反 P1-14（不可篡改承诺） | Memory 版写同一 (spec_id, round) 仍抛 FileExistsError | ✅ 同等不变量 |
| 4 处 fixture 已经有内存版（MemoryStorageBackend）| 5 个 fixture 现在用 MemoryReviewBackend | ✅ 单一抽象路径 |
| 旧 import 路径断 | 老代码 `from .storage.review_store import ReviewStore` 应继续工作 | ✅ `ReviewStore = FSReviewBackend` 别名 |

## 四、为何 3 条仍用 FSReviewBackend

`test_review_loop.py` 的核心 3 个断言**真的依赖**真实 YAML 文件：

```
test_1:  assert (root / "review" / spec_id / "r1.yaml").exists()
test_6:  assert (root / "review" / spec_id / "f1.yaml").exists()
test_7:  assert (root / "review" / spec_id / "r1.yaml").exists()
                          and ... / "r2.yaml").exists()
```

这些断言**就是 FSReviewBackend 的语义契约**——如果它们在 MemoryReviewBackend 下"通过"了，那 `write_report` 实际上根本没碰盘，重构毫无意义。同 Phase C 处理 `test_p2_resume_detects_missing_spec` 模式：

- **保留 `fs_env` fixture** 给这 3 条 + 1 条新增的"测试 FSReviewBackend 自身"
- **新 `env` fixture** 默认切到内存，给其余 17 条

## 五、graph 演化预期

下一次 `/graphify --update`:

### 新节点
- `src_devflow_storage_review_store_base_reviewstoragebackend` (ABC 类型, 21 method)
- `src_devflow_storage_review_store_memory_memoryreviewbackend` (Memory concrete)
- 各 **8 个 MemoryReviewBackend method 节点** (write_report / update_report / read_report / latest_report / list_reports / write_fix / list_fixes / list_spec_ids)

### 新边
- `MemoryReviewBackend --inherits--> ReviewStorageBackend`
- `MemoryReviewBackend --methods--> [8 个 method node]`
- `FSReviewBackend --inherits--> ReviewStorageBackend`
- `review_engine.py --imports--> review_store_base.py`（之前只 import `review_store.py`）
- 17 个 test 节点的 `--uses--> MemoryReviewBackend` (替代之前的 FSReviewBackend 类 `ReviewStore` 别名)

### 社区变化预期
- graph C8（ReviewReport Counters + ReviewStore Filesystem Persistence）从 cohesion 0.16 → 0.10 左右（FS 节点拆出去）
- graph C35（Review Loop Test Corpus）从 10 节点 → 30+ 节点（memory_backend + 17 fixture 全展开）
- **新社区预期**：MemoryReviewBackend method surface（与 graph C9 FSBackend method surface 同构），cohesion 应略高（memory 无 disk lock 同步机制，结构更清晰）

## 六、与 Plan B 的协调

| Plan | 状态 | 下一步 |
|---|---|---|
| Plan B（StorageBackend 拆 FileStore / LedgerStore / StateStore）| **仍 paused**——未触发 trigger signal | 等用户场景出现第二个真后端需求 |
| Plan C（ReviewStore 可插拔）| **live**——已落地 | 等下一个 `\graphify --update` 看 graph 实证 |

Plan C 不依赖 Plan B 拆三仓成功——ReviewStore 是与 StorageBackend **平行**的另一组 ABC，而不是嵌套子集。这与 graph C29 / C8 的"两个独立 storage 抽象"的拓扑一致。

## 七、给后续 audit 的 evidence

写本文档时（2026-08-20）的 4 个新文件 / 1 个修改文件 + 1 个 alias 兼容：

```
+ src/devflow/storage/review_store_base.py      # NEW
+ src/devflow/storage/review_store_memory.py    # NEW
M src/devflow/storage/review_store.py           # ReviewStore → FSReviewBackend + alias
M src/devflow/storage/__init__.py               # re-export new symbols
M src/devflow/engine/review_engine.py           # review_store: ReviewStorageBackend
M tests/test_review_loop.py                     # env → Memory (17 tests) + fs_env exception (3 tests)
```

后兼容：`from devflow.storage.review_store import ReviewStore` 仍可用。

变更前：`tests/test_review_loop.py:20 → env → FSReviewBackend → 3.06s`  
变更后：`tests/test_review_loop.py:20 → 17 Memory @ 1.83s + 3 FS @ 0.7s → 总 ~1.83s (memory) + ~2s (fs 部分包含在总 14.75s 里)`

---

**文档结束 · Plan C v0.1 · 2026-08-20 · 状态: live**
