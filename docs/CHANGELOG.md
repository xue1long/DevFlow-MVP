# Changelog

所有值得用户注意的变更都记录在这里。
格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

## [Unreleased]

### Planned（v0.3 设计中，未实施）
- **工作区布局重构**：运行时产物统一迁入 `doc/devflow-workspace/` 子目录（已评估，改用第一性方案）
- 详见 [`docs/workspace-layout-v0.1.md`](./workspace-layout-v0.1.md)（**第一性方案替代**）

### Added
- **v0.3 第一性方案：INDEX + 软归档 + 跨文件搜索**（替代全量路径迁移）
  - 新增 `StorageBackend.archive_spec()` / `list_archived_specs()` / `list_active_specs()` / `query()` 接口
  - 新增 CLI：`devflow archive` / `devflow list-archived` / `devflow list-active` / `devflow find`
  - `devflow finish`（Stage 7）自动触发软归档
  - 详见 [`docs/INDEX_FORMAT.md`](./INDEX_FORMAT.md)
- 新增 `tests/test_archive_index.py`（10 条验证测试）

### Changed
- （暂无）

### Fixed
- （暂无）

---

## [v0.2.1] - 2026-XX-XX（第 3 轮整改归档）

### Added（新增）
- 新增 `plan` / `task-add` / `task-list` / `contract-add` CLI 命令，补齐 Stage2/3 流程
- 新增 `README.md` 上手指南（含安装、5 分钟上手、CLI 速查、阶段对照、架构图）
- 新增 `docs/audit-prompt-template-v0.1.md`（4 角色评审 + 复核审计提示词模板）
- 新增 `docs/DOCS_GUIDELINES.md`（文档命名规范 + 归档方案）
- 新增 `docs/audit-ledger.md`（从仓库外迁入的审计整改台账）
- 新增 `tests/test_p0_fixes.py`（12 条 P0/P1 整改验证测试）
- 新增 `tests/test_p2_fixes.py`（6 条 P2 优化验证测试）

### Changed（变更）
- `devflow status` 返回 `spec_summary`（标题、状态、缺失字段）+ `plan_summary`（任务计数、状态分布）
- `cross_module_import` 红线改用正则解析 import 语句（消除注释误报）
- `_gate_intake` 读取 `sop.yaml` 中 `intake_gate` 配置（kind/require/enabled）
- `init` 命令优先读 `sop.default.yaml`，缺失时打印警告并兜底
- `ReviewReport.residual_count` 不再依赖 `resolved`（修复误导性 API）
- `resume` 返回结构扩展为 `{ok, phase, phase_name, warnings, gate, message}`

### Fixed（修复）
- **P0-1** 账本写入非真正原子（用临时文件 + rename）
- **P0-2** 并发写无文件锁（加 O_EXCL 进程锁）
- **P0-3** 账本可被篡改（SHA256 哈希链 + verify_ledger）
- **P0-4** Spec 轴评审是空壳（实现 goal 覆盖 + contract 缺失检查）
- **P0-6** `next_phase` 不触发 review_gate（接入阻断）
- **P0-7** 门禁命令注入（危险模式列表拦截）
- **P0-8** git commit 敏感文件（`.env`/`*.key`/锁文件等）
- **P1-1** spec_id 碰撞（HHMMSS 后缀 + 随机数兜底）
- **P1-3** commit 不校验阶段（仅 Stage5+ 可 commit）
- **P1-4** approve 不校验阶段（仅 Stage0/1 可 approve）
- **P1-7** 停滞检测口径含已 resolved（改用未修复数）
- **P1-12** subprocess 无超时（默认 120s，可配置）
- **P1-14** review 报告可覆写（写报告默认拒绝覆写，fix 用专用 update_report）

### Deprecated（废弃）
- （暂无）

### Removed（移除）
- （暂无）

### Security（安全）
- 账本哈希链（防篡改）
- 命令执行危险模式白名单
- git 提交敏感文件前置检查
- 文件锁防止并发写竞态

---

## [v0.2.0] - 2026-XX-XX（审核闭环初版）

### Added
- 双轴评审引擎（Standards × Spec）
- `review` / `fix` / `history` CLI 命令
- 防死循环三道防线（最大 5 轮 / 停滞收敛 / 自动重验）
- `review_gate` 绑定 `bind_to_stage: 2`

### Changed
- 状态机 8 阶段集成 review_gate

### Security
- AUTO_VERIFIABLE_RULES 强制 fix 时重跑验证

---

## [v0.1.0] - 2026-XX-XX（MVP 初版）

### Added
- 8 阶段状态机（intake → brainstorm → plan → contract → implement → verify → review → finish）
- 11 个 CLI 命令（init / start / approve / next / resume / status / gate / commit / audit / suspend / skip-task）
- 红线审计器（11 条规则，6 条 MVP 实现）
- append-only 账本（progress.yaml）
- 文件系统存储后端（FSBackend）
- Git 操作抽象（GitPort + SystemGitPort）
- 门禁执行器（GateRunner）
- SOP 配置加载器（sop.yaml + 版本协商）
- 模块化解耦分层（model / engine / storage / verify / policy / cli）

[v0.2.1]: https://github.com/xue1long/DevFlow-MVP/compare/v0.2.0...v0.2.1
[v0.2.0]: https://github.com/xue1long/DevFlow-MVP/compare/v0.1.0...v0.2.0
[v0.1.0]: https://github.com/xue1long/DevFlow-MVP/releases/tag/v0.1.0