# DevFlow 工作区布局规范（v0.3 设计）

> **状态**：⏸️ **已被第一性方案替代**（详见 [`INDEX_FORMAT.md`](./INDEX_FORMAT.md)）
>
> 4 角色评审指出本设计会导致账本哈希链断裂、与 v0.3 不可调和的 P0 矛盾。经第一性分析，**不重组文件路径**，改为在账本添加 `archive` 段实现"软归档"，并提供跨文件 `query()` 搜索能力。
>
> 本文档保留作为**评审档案**（评审发现 + 第一性决策原因），不再作为 v0.3 实施依据。

## 1. 设计原则

| 原则 | 说明 |
|------|------|
| **隔离原则** | DevFlow 产物不污染用户项目根目录 |
| **领域分类** | 计划 / 评审 / 实施三个文档域各自独立 |
| **按 Spec 分组** | 每个 Spec 在每个域下都有自己的子目录 |
| **阶段归档** | 完成的文档归入 `archive/finished/<stage>/` |
| **可移植** | 用户可整体打包 `doc/devflow-workspace/` 移交或备份 |

## 2. 目录结构（用户项目内）

```
{用户项目根}/
├── doc/                                  ← 用户项目原有的文档目录
│   └── devflow-workspace/                ← DevFlow 工作区（DevFlow 创建并维护）
│       ├── sop.yaml                      ← SOP 配置（DevFlow 初始化创建）
│       ├── README.md                     ← workspace 自描述（DevFlow 创建）
│       │
│       ├── plans/                        ← 计划方案（Stage2 产出）
│       │   ├── README.md                 ← 计划目录索引
│       │   └── {spec-id}/                ← 按 Spec 分目录
│       │       ├── plan.yaml             ← 计划主文件
│       │       └── tasks.yaml            ← 任务列表（Stage2/3 增量）
│       │
│       ├── reviews/                      ← 审核方案（Stage6/审核闭环产出）
│       │   ├── README.md                 ← 评审目录索引
│       │   └── {spec-id}/
│       │       ├── r1.yaml               ← 第 1 轮评审报告
│       │       ├── f1.yaml               ← 第 1 轮修复记录
│       │       ├── r2.yaml               ← 第 2 轮评审报告
│       │       └── ...
│       │
│       ├── implementations/              ← 实施方案（Stage4/5 产出）
│       │   ├── README.md                 ← 实施目录索引
│       │   └── {spec-id}/
│       │       ├── notes.md              ← 实施笔记（手动编辑）
│       │       ├── decisions.md          ← 关键决策记录（自动追加）
│       │       └── commits.log           ← git commit 摘要（自动追加）
│       │
│       ├── archive/                      ← 归档区（已完成/已取消）
│       │   ├── README.md                 ← 归档规则说明
│       │   ├── finished/
│       │   │   ├── {stage}/              ← 按最终阶段分类（intake/.../finish）
│       │   │   │   └── {spec-id}/
│       │   │   │       ├── plan.yaml
│       │   │   │       ├── reviews/
│       │   │   │       └── implementations/
│       │   └── cancelled/
│       │       └── {spec-id}/
│       │           ├── plan.yaml
│       │           ├── reviews/
│       │           └── implementations/
│       │
│       └── data/                         ← 运行时数据（不参与版本控制）
│           ├── README.md                 ← data/ 说明
│           ├── ledger.yaml               ← 进度账本（原 progress.yaml）
│           ├── ledger.yaml.lock          ← 文件锁（运行时临时）
│           └── handbook.md               ← 领域术语表（原 CONTEXT.md）
```

## 3. 域说明

### 3.1 plans/（计划方案）

**内容**：Plan + Task 列表 + 每个 Task 的 Contract。**产生时机**：Stage2 创建计划、Stage3 添加 Contract。**关键文件**：
- `plan.yaml`：Plan 主数据（spec_id, tasks）
- `tasks.yaml`：Task 列表的详细版本（Stage3 增量追加 Contract 时更新）
- 两文件分工：`plan.yaml` 是核心结构，`tasks.yaml` 是扩展视图

**索引文件**：`plans/README.md` 自动列出所有 `{spec-id}` 子目录 + 当前活跃计划标记。

### 3.2 reviews/（审核方案）

**内容**：双轴评审报告 + 修复记录。**产生时机**：`devflow review` 和 `devflow fix` 命令。**关键文件**：
- `r<N>.yaml`：第 N 轮评审报告（双轴 + 违规列表 + verdict）
- `f<N>.yaml`：第 N 轮修复记录（修复的违规 ID + summary）

**轮次不可覆写**：历史报告是不可变审计记录。

### 3.3 implementations/（实施方案）

**内容**：实施笔记、决策日志、commit 摘要。**产生时机**：Stage4-5。**关键文件**：
- `notes.md`：开发者手动写的笔记（自由格式）
- `decisions.md`：自动追加的关键决策（如"Task X 改用方案 B"）
- `commits.log`：自动追加的 git commit 摘要（SHA + 消息）

**为什么独立**：实施阶段的产出是开发过程的核心证据，但不应混入 Spec/Plan/Review。

### 3.4 archive/（归档）

**何时归档**：
- `devflow finish` 完成时（stage=7）：将整个 `{spec-id}` 目录树迁入 `archive/finished/finish/{spec-id}/`
- 用户取消（`devflow archive --reason`）：迁入 `archive/cancelled/{spec-id}/`
- 提前终止（如 spec_id 永远达不到 finish）：保留在原位，由用户决定

**目录迁移**：保留目录结构（plans/、reviews/、implementations/），加上 `archive_time` 元数据。

### 3.5 data/（运行时数据）

**为何独立**：账本是机器可读的运行状态，术语表是协作元数据，与设计/计划/评审这类"人类文档"性质不同。

**不参与版本控制**：建议在 `.gitignore` 中加入 `doc/devflow-workspace/data/`。

## 4. 与历史版本的迁移

v0.2 及之前版本，工作区根目录散布 7+ 文件：
- `progress.yaml` → `doc/devflow-workspace/data/ledger.yaml`
- `CONTEXT.md` → `doc/devflow-workspace/data/handbook.md`
- `specs/{id}.yaml` → `doc/devflow-workspace/plans/{spec-id}/plan.yaml`
- `plans/{id}.yaml` → `doc/devflow-workspace/plans/{spec-id}/tasks.yaml`
- `review/{id}/r<N>.yaml` → `doc/devflow-workspace/reviews/{spec-id}/r<N>.yaml`
- `review/{id}/f<N>.yaml` → `doc/devflow-workspace/reviews/{spec-id}/f<N>.yaml`
- `handoff-<phase>.md` → `doc/devflow-workspace/data/handoff-<phase>.md`

迁移方式：
- v0.3 提供 `devflow migrate-v0.3` 命令自动迁移（移动 + 重命名 + 更新 progress.yaml 中的引用）
- 迁移前自动备份到 `doc/devflow-workspace/.migration-backup-{timestamp}/`

## 5. sop.yaml 配置

sop.yaml 中 `storage` 段需调整以反映新路径：

```yaml
storage:
  backend: fs
  workspace_root: doc/devflow-workspace    ← 新增：工作区根目录
  plans_dir: plans                         ← 相对 workspace_root
  reviews_dir: reviews
  implementations_dir: implementations
  archive_dir: archive
  data_dir: data
  ledger: ledger.yaml                      ← 相对 data_dir
  handbook: handbook.md
  content_address: false
```

## 6. 用户自定义

用户可通过 sop.yaml 完全自定义：

```yaml
storage:
  workspace_root: ".devflow"               ← 可改为隐藏目录
  plans_dir: myplans                       ← 可改名
  ...
```

**规则**：
- 所有路径相对 `workspace_root`
- `sop.yaml` 必须放在 `workspace_root` 内
- 用户项目原有的 `doc/`（如已有）会被保留，DevFlow 只在 `doc/devflow-workspace/` 下创建子目录

## 7. README 索引

每个子目录自动生成 `README.md` 索引，列出该目录下所有 `{spec-id}` 子目录 + 简要描述：

```markdown
# plans/

| Spec ID | 标题 | 当前阶段 | 任务数 | 缺失字段 |
|---------|------|----------|--------|----------|
| 2026-08-19-pipeline-retry | Pipeline Batch Retry | plan | 3 | - |
| 2026-08-19-cache-refactor | Cache Refactor | contract | 2 | 1 个 task 缺 contract |

> 自动生成于 2026-XX-XX，最后更新见 ledger.yaml。
```

---

**本规范版本**：v0.3 设计（2026-XX-XX）
**状态**：⏳ 设计完成，未实施
**v0.2 历史布局**：specs/、plans/、review/、progress.yaml、CONTEXT.md、handoff-*.md 散在项目根
**v0.3 迁移命令**：`devflow migrate-v0.3`（设计阶段，实现时需注意路径迁移原子性 + 进度账本兼容性）

## 8. 实施清单（v0.3）

实施此规范需改动：

- [ ] `policy/loader.py` 增加 `workspace_root` / `plans_dir` / `reviews_dir` / `implementations_dir` / `archive_dir` / `data_dir` 字段
- [ ] `storage/fs_backend.py` 路径计算改为相对 `workspace_root`
- [ ] `storage/review_store.py` 路径改为 `workspace_root/reviews/{spec-id}/`
- [ ] 新增 `engine/archiver.py`（归档动作 + 阶段分类）
- [ ] 新增 `cli.py archive` 命令（手动归档）+ `finish` 自动归档
- [ ] 新增 `cli.py migrate-v0.3` 命令（v0.2 → v0.3 数据迁移）
- [ ] `config/sop.default.yaml` 更新默认 `storage:` 段
- [ ] `engine/state_machine.py` init 增加 `plans_dir.mkdir(parents=True, exist_ok=True)` 等初始化子目录
- [ ] 新增 `tests/test_workspace_layout.py`（子目录创建、归档、迁移测试）
- [ ] `.gitignore` 增加 `doc/devflow-workspace/data/`
- [ ] 更新 `README.md` 描述新布局
- [ ] 更新 `docs/CHANGELOG.md` v0.3 段

**预计影响范围**：~10 个文件，约 600 行改动 + 300 行测试