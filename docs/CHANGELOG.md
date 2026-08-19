# Changelog

所有值得用户注意的变更都记录在这里。
格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

## [Unreleased]

### Added
- **知识图谱（graphify）**：README 新增「知识图谱」章节——graphify-out/ 产物说明、commit hook 自动更新说明（新克隆仓库需 `graphify hook install`）、手动更新/跳过/日志方法
- `RedLineAuditor.implemented_rule_names()`：返回已实现自动检测的红线名称列表（audit 覆盖度展示用）

### Changed
- README 头部版本号 v0.2 → v0.3.3；测试数量 76 → 121；架构图红线描述更新（11 红线 + 9 思维检查）
- README「限制与残余风险」更新：标记 v0.3.x 已修复项,残余 P1 指向 audit-ledger

---

## [v0.3.3] - 2026-08-19（思维模型落地）

> **来源**：用户需求——"项目吸收思维模型,应用到实际工作"。将 9 种职场思维变成引擎的**默认规则**(字段 + 检查),而非依赖 agent 自觉。
> **原则**：宽松默认(字段可选,有值才检查,MINOR 提示不阻断)；不碰哈希链/账本 schema/状态机阶段。

### Added（新增）
- **思维模型字段**（全部可选,宽松默认）：
  - `Spec.assumptions` — 第一性原理:底层假设清单
  - `Spec.premortem` — 逆向思维:事前验尸(方案最可能怎么失败)
  - `Spec.tradeoff` — 损益思维:决策放弃了什么(机会成本)
  - `Task.priority` — 二八法则:P0/P1/P2(默认 P1)
  - `Task.owner_skill` — 能力圈:擅长标注;learn/collab 表示圈外
  - `Plan.buffer` — 冗余思维:缓冲比例(0-1),资源不排满
- **思维检查规则 9 条**（review Spec 轴自动执行,MINOR 提示不阻断）：
  - `thinking_first_principles` — 未声明 assumptions 时提示
  - `thinking_premortem` — 未做事前验尸时提示
  - `thinking_tradeoff_decision` / `thinking_tradeoff_tradeoff` — 有 options 无 decision/tradeoff 时提示
  - `thinking_occam` — 多 options 时提示确认最简方案
  - `thinking_hypothesis` — assumptions 声明后提示制定验证计划
  - `thinking_pareto` — 无 P0 或 P0 未完成时提示(80/20)
  - `thinking_capability_circle` — 圈外任务(learn/collab)提示协作
  - `thinking_feedback_loop` — 任务缺验收标准时提示小步反馈
  - `thinking_redundancy` — 计划未预留 buffer 时提示
- **`sop.yaml` 新增 `thinking:` 配置段**：
  ```yaml
  thinking:
    enabled: true     # false 时完全跳过思维检查(兼容旧 SOP)
    severity: "minor" # minor | off
  ```
- 新增 `tests/test_thinking_rules.py`（9 条验证测试）

### Changed（变更）
- `SOPConfig` 新增 `ThinkingConfig` 模型（enabled/severity）
- `ReviewEngine._run_spec_checks` 在 Spec 轴检查后追加思维检查（`_run_thinking_checks`）

### Fixed（修复）
- `Plan` 模型缺 `Optional` 导入（加 buffer 字段时暴露）

### Notes
- 9 项思维检查全部 severity=MINOR,不阻断推进（灰度思维：可行解优先）
- `thinking.enabled: false` 可完全关闭（兼容旧 SOP）
- 详见 [`docs/thinking-framework-mapping.md`](./thinking-framework-mapping.md)

---

## [v0.3.2] - 2026-08-19（轻量修补）

> **来源**：第 6 轮审计（v0.4 RFC 预审）保留的 4 项低风险修补。v0.4 大重构（账本 schema 演进 / 接口拆分）暂停，等真正需求。
> **原则**：不改 `_compute_entry_hash`、不扩 LedgerEntry 必填字段（新增字段均 Optional,仅影响新条目哈希,旧链验证不变——已用测试锁定）。

### Added（新增）
- **P2-14 门禁结果持久化**：`devflow gate <phase>` 命令执行结果（ok / message / stdout_tail / stderr_tail）写入账本
  - `LedgerEntry` 新增 `gate_result` 可选字段（不破坏旧账本哈希链）
  - stdout/stderr 尾部 300 字符 + **ANSI 颜色码过滤 + 密钥/token 脱敏**（`_sanitize_gate_result`）
- **P1-5 补强 status 枚举**：`RedLineViolation` 新增 `ViolationStatus` 枚举（`active` / `mvp_skip` / `stub` / `not_implemented`）
  - `audit()` 为每条违规分配结构化 status（不再仅靠 message 文本判断）
  - `devflow audit` 输出新增 `coverage.by_status` 统计
- **P1-11 语言中性化**：`no_test` / `cross_module_import` 红线不再硬编码 `.py`
  - sop.yaml 新增 `tooling.languages` 配置（`code_extensions` / `test_patterns` / `test_extensions`）
  - 缺省回退 `.py`（旧 sop.yaml 行为不变）
  - 测试文件识别用词边界正则,避免 `contest.py` / `protest.go` 误判
- 新增 `tests/test_v032.py`（11 条验证测试）

### Changed（变更）
- **P2-17 timestamp 时区化**：`LedgerEntry.timestamp` 默认值 `datetime.now()` → `datetime.now(timezone.utc)`（UTC 感知）
  - 旧账本 naive timestamp 读取兼容（已用测试锁定）

### Fixed（修复）
- **audit 输出语义修正**：stub 红线显式标注 `status="stub"`,用户能区分"已检查"与"未实现"
- **gate_result 敏感信息泄露**：stdout/stderr 尾部脱敏,不存明文密钥

### Notes
- v0.4 RFC（`docs/v0.4-rfc.md`）在 4 角色独立审计后回退（10 个去重 P0：分代哈希 / 迁移工具 / spec_id 推断 / 接口拆分全被证伪）
- v0.4 暂停项：账本 schema 演进（actor/session_id/review_ref/spec_id）、StorageBackend 接口拆分、多 spec 双向 JOIN 完整版
- 详见 [`docs/audit-ledger.md`](./audit-ledger.md) 第 6 轮

---

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