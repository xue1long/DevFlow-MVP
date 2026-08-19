# Changelog

所有值得用户注意的变更都记录在这里。
格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

## [v0.3.1-r2] - 2026-08-19（最简替代修补）

> **v0.3.1-r1 方案（4 项 P1 全修 + pytest-cov）在 4 角色独立审计后回退**（7 个交叉 P0，重蹈 v0.3 INDEX 覆辙）。本版本为 r2 最简替代版，零破坏兼容、零新依赖、零 schema 变更。

### Added（新增）
- **P1-9（简化）**：新增 CLI `devflow ci-status` — 显示 ci_green 门禁当前配置状态（disabled / enabled），明确告知占位命令状态
- **P1-13（简化）**：新增 CLI `devflow review-audit` — 扫描 ledger 的 review/fix/escalate 条目，与 review_store 报告做 JOIN，检测孤儿条目
  - **不修改 LedgerEntry schema**（避免破坏哈希链）
  - **不修改 review_engine.py 写入点**（避免 5 处漏算风险）
  - 单 spec 工作流下准确；多 spec 场景需 v0.4 完整方案
- **P1-5（改进）**：`devflow audit` 输出新增 `violations_real` / `skipped_detail` / `total_real` / `total_skipped` / `coverage` 字段，区分真实违规与 stub 红线
- 新增 `tests/test_v031_r2.py`（7 条验证测试）

### Changed（变更）
- **P1-2（简化）**：`config/sop.default.yaml` 中 `ci_green.enabled` 默认值 `true → false`（占位命令不应启用，避免"已启用但实际是占位"的误导）
- `src/devflow/engine/redline_auditor.py`：5 条 stub 红线（`skip_phase` / `doc_drift` / `silent_legacy` / `no_contract` / `human_step_auto`）改为显式返回 `RedLineViolation(skip=True)`，让用户看到"未自动检测"而非"无声通过"

### Fixed（修复）
- **隐性兼容修复**：`ci_green` 不再默认启用占位命令（此前 `enabled: true` 但命令是 `echo` 占位，用户误以为 CI 在跑）
- **审计透明性修复**：stub 红线此前静默返回 `[]`，用户无法区分"已检查"与"未实现"；现在显式标 `skip=True`

### Notes
- v0.3.1-r1 方案（`docs/v0.3.1-implementation.md`）已被本版本取代，保留作历史档案
- P1-5/P1-13 完整方案（多 spec JOIN、反向校验、status 字段）留 v0.4 大重构
- 详见 [`docs/v0.3.1-r2-implementation.md`](./v0.3.1-r2-implementation.md) 与 [`docs/audit-ledger.md`](./audit-ledger.md) 第 5 轮

---

## [Unreleased]

### Added
- **v0.3 第一性方案（最简版）**：Spec 文件内 `status` 字段标记归档
  - `SpecStatus` 新增 `ARCHIVED = "archived"`
  - 新增 CLI：`devflow archive` / `devflow list-active` / `devflow list-archived` / `devflow find`
  - **零新接口**：完全用现有 `FSBackend.read_spec/write_spec`
  - **零账本新段**：归档只追加 ledger entry（不修改 entries 哈希链）
  - 撤销归档：手动改 `status` 字段即可，无需专门 unarchive 命令
  - 详见 [`docs/first-principles-sop.md`](./first-principles-sop.md) §4 实战案例
- 新增 `tests/test_simple_archive.py`（11 条验证测试）
- **第一性原理 SOP** 文档：详见 [`docs/first-principles-sop.md`](./first-principles-sop.md)
- `docs/v0.3-rejected-design.md`（5 角色评审归档档案）

### Removed
- **回退 v0.3 INDEX 复杂方案**（commit `f49af51`）：代码 + 测试 + INDEX_FORMAT.md
  - 原因：5 角色独立评审发现 21 项问题（含 1 项 [F] 强质疑）
  - 第一性质疑者结论：方案跳过最简替代（Spec 文件内 `status` 字段）
  - 替代：最简方案（11 行实现 vs 原 600+ 行）

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