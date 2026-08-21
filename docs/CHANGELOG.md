# Changelog

所有值得用户注意的变更都记录在这里。
格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

## [Unreleased]

### Added
- **v0.4.3 research 自动喂 plan（2026-08-21）**：
  - 新建 `src/devflow/engine/goals_extractor.py`：`GoalsExtractor` 类（结构化提取，无 LLM 依赖）
    - SourceType 模板（PYPI/NPM/CRATES/GITHUB/WEB）+ URL regex 提取
    - trust_level 排序 + goal 主语去重 + max_goals 截断
  - 新建 `src/devflow/engine/spec_auto_filler.py`：`SpecAutoFiller` 类
    - **关键纪律**：默认仅覆盖占位（`["待补充"]` / `TBD` / `TODO` / `to be filled`）
    - `overwrite=True` 时强制覆盖（CLI/SOP 可选）
  - 新建 `src/devflow/policy/loader.py::ResearchAutoFillGoalsConfig`（`enabled` / `max_goals` / `overwrite_existing`，默认仅覆盖占位）
  - CLI `devflow plan` 新增 `--no-auto-fill-goals` 选项
  - CLI `devflow plan` 在 `_run_research` 成功后自动调用 `_maybe_auto_fill_goals`
  - `[INFO]` stderr echo 提示用户 goals 已被自动填充
  - 3 份 SOP 文件统一加 `research.auto_fill_goals` 段（`sop.yaml` / `config/sop.default.yaml` / `cli.py` 内嵌兜底）
  - 测试：235 passed + 1 skipped
    - `tests/test_goals_extractor.py` 13 个（URL 提取 + trust 排序 + 去重 + max_goals 限制 + 边界）
    - `tests/test_spec_auto_filler.py` 8 个（覆盖占位 / 保留用户内容 / overwrite 强制覆盖 / 缺失 spec / 占位符变体）
    - `tests/test_research_cli_integration.py` +1（`--no-auto-fill-goals` flag）
  - 文档：`docs/release-notes-v0.4.3.md` 新增；`docs/rfc-v0.4.3-auto-fill-goals.md` 状态升级
  - **关键纪律**：不调 LLM（保持纪律引擎定位，LLM 留 v0.5 单独 RFC）
  - **dogfooding 顺手验证 v0.4.2 B2 修复**（`_maybe_auto_research` 在 `next_phase` 自动跑 research）

### Added
- **v0.4.2 research 24h 缓存（2026-08-21）**：
  - 新建 `src/devflow/engine/research_cache.py`：`ResearchCache` 类（`make_key` / `get` / `put` / `clear` / `stats`）
  - 新建 `src/devflow/model/research.py::CacheEntry` Pydantic 模型（含 `is_expired` / `age_seconds`）
  - 新建 `src/devflow/policy/loader.py::ResearchCacheConfig`（`enabled` / `ttl_seconds` / `shared_across_specs`，默认 24h + 跨 Spec 共享）
  - 扩展 `engine/research_runner.py`：集成 cache lookup/hit/miss/expire 逻辑，新增 `_write_cache` / `_build_cache_hit_result` / `_update_spec_from_cache` / `_append_cache_hit_ledger` 方法
  - CLI `devflow research` 新增 `--clear-cache` / `--no-cache` 选项（query 可省略用于清单/全部）
  - run() 返回 JSON 新增 `cache_hit` / `cache_age_seconds` / `cache_key` 字段
  - `Spec.research_refs` 缓存命中时仍追加（标记 `cache_hit: true`，审计追溯完整性）
  - SOP 配置扩展（`sop.yaml` / `config/sop.default.yaml` / `cli.py` 内嵌兜底）：新增 `research.cache` 段
  - 文档：`docs/release-notes-v0.4.2.md` 新增；`docs/rfc-v0.4.2-research-cache.md` 草案保留
  - **dogfooding 顺手修**（v0.4.2 实施期间发现）：
    - B1: SOP 多文件一致性——3 份 SOP 文件统一补全 `research.cache` 段（`cli.py` 内嵌兜底漏段）
    - B2: `state_machine.py::_advance_tasks_for_phase()` 加 `_maybe_auto_research()` 钩子，修复 `auto_run_on=[plan_stage]` 仅在 `devflow plan` 命令触发、不在 `next_phase` 触发的语义不一致
  - 测试：215 passed + 1 skipped
    - `tests/test_research_cache.py` 19 个（新文件）
    - `tests/test_research_runner.py` +4 个 cache 集成测试
    - `tests/test_research_cli_integration.py` +2 个 `--clear-cache` 测试

### Added
- **v0.4.0 引文式调研子能力 research（2026-08-21）**：
  - 新建 `src/devflow/model/research.py`：`SourceType` / `TrustLevel` / `Citation` / `ResearchQuery` / `ResearchReport` 5 个 Pydantic 模型 + `to_markdown()` 带引用格式
  - 新建 `src/devflow/adapters/research/` 包（4 backend + 选择器，零业务逻辑纪律）：
    - `AgentReachBackend` 复用宿主平台已加载的 `agent-reach` skill（主路径，15+ 平台多 backend 路由，避免重复造轮子）
    - `GitHubSearchBackend` GitHub Repository Search API 兜底（鉴权 `GITHUB_TOKEN` 可选）
    - `RegistryQueryBackend` PyPI + npm + crates.io 三源聚合查询
    - `WebSearchBackend` DuckDuckGo Instant Answer 通用兜底
    - `select_backends()` 优先级排序 + sources 过滤 + health_check 降级
  - 新建 `src/devflow/engine/research_runner.py` `ResearchRunner` 编排层：并发（`concurrent.futures.wait` 强制超时）+ URL 去重 + `max_total_chars` 截断 + 落盘 Markdown + 增量更新 `spec.research_refs` + 写账本（`action=research`）
  - SOP 配置扩展 `sop.yaml` `research:` 段（默认 `enabled: true` / `auto_run_on: [plan_stage]` / `fallback: skip`）：
    - 字段：`enabled` / `auto_run_on` / `sources` / `max_results_per_source` / `max_total_chars` / `timeout_per_source` / `fallback` / `citation_required` / `start_keywords`
    - `is_research_auto_run(stage)` 辅助判定
    - 向后兼容：旧 sop.yaml 无 research 段 → 走默认值
  - CLI 新增 `devflow research <query> [--spec-id] [--sources] [--max-results]`：显式调研命令
  - CLI 扩展 `devflow plan --with-research`：显式触发；或 SOP `auto_run_on=[plan_stage]` 隐式
  - `state_machine.py::start()` advisory 提示：检测 `sop.research.start_keywords` 触发词后 stderr echo（**不自动执行**，避免消耗 API 额度）
  - 模型扩展：`model/ledger.py` `LedgerAction.RESEARCH`；`model/spec.py` `research_refs: list[dict]`（**仅路径引用，不嵌入内容**，避免交接时漂移）
  - 文档：`README.md` 核心概念 `### Research` 段；`docs/devflow-architecture-v0.1.md` §5.3 状态升级（规划 → 已落地）、§6.1 工具清单加 `devflow.research(...)`、§15.3 #12 状态升级
  - 测试：5 个新文件，118 个单测全过（+ 1 skip 平台相关）
    - `test_research_model.py` 23 个
    - `test_research_config.py` 16 个
    - `test_research_backends.py` 43 个（4 backend + 选择器 mock HTTP 全覆盖）
    - `test_research_runner.py` 19 个（并发 / 去重 / 截断 / 失败兜底）
    - `test_research_cli_integration.py` 18 个（Typer CliRunner + advisory + plan --with-research）
  - **纪律落地**：
    - 不重复造 `agent-reach` 轮子（主路径复用宿主平台 skill，DevFlow 内置仅做兜底）
    - 适配层零业务逻辑（RFC §7），仅外部 API → Citation 转换
    - 离线不阻断流程（`fallback=skip` 默认，CI 兼容）
    - append-only 账本 + `action=research`，与现有审计追溯字段一致
  - 详见 [`PR_DESCRIPTION_V0.4_RESEARCH.md`](../PR_DESCRIPTION_V0.4_RESEARCH.md)

### Changed
- **v0.4.0 路径策略配置化（2026-08-20）**：
  - 新建 `src/devflow/storage/layout.py`：`LayoutPaths` + `resolve_layout()`，路径从 `sop.yaml` `storage:` 节读取而非硬编码
  - `FSBackend` / `ReviewStore` / `MemoryReviewBackend` 统一接入 layout
  - `cli.py` 中 `ReviewStore` 复用 `storage.layout`（消除双实例漂移）
  - `state_machine.py` `artifact_refs` 从 `layout.artifact_refs()` 取
  - **改路径 = 改 sop.yaml 一行配置，不动引擎代码**（默认值 `docs/devflow/specs` 等）
  - 测试走 `storage.layout` 接口，不写死路径
  - 详见 [`docs/v0.4-roadmap-paused.md`](./v0.4-roadmap-paused.md) 预案 C 落地变体

### Changed
- **review-audit 从单 spec 升级为多 spec 全面版（2026-08-19）**：
  - `src/devflow/engine/review_audit.py` 新增 316 行完整实现：`ReviewAuditResult` 数据类 + 7 步审计循环
  - `missing_in_ledger` 反向校验（review_store → ledger）——v0.3.1-r2 硬编码空列表，现真正实现
  - `fix_orphans` / `fix_missing_in_ledger` 修复闭环双向 JOIN
  - `per_spec_summary` 按 spec 分组统计
  - 时间窗推断（`_infer_spec_id_for_ledger_entry`）替代字段扩展，不走扩 schema 老路
  - 34 条测试锁定（`tests/test_review_audit.py`）
  - 详见 [v0.4-roadmap-paused.md §二预案B](./v0.4-roadmap-paused.md)
- **v0.3.4 路径策略重构（2026-08-20）**——见上方 Added 节

### Fixed
- **v0.3.4 #39 根治**: `is_recognized_type()` 替代 `hint is not str`，消除 4 个 manifest 类型降级 warning
- `pyproject.toml` 版本号同步到 0.3.4（从 0.1.0）
- README 测试数更新为 375 passed（从 121 passed）

### Added
- `RedLineAuditor.implemented_rule_names()`：返回已实现自动检测的红线名称列表（audit 覆盖度展示用）
- **v0.3 双集成面之 MCP Server（B1 阶段）**：
  - `pyproject.toml` 新增 `[project.optional-dependencies]` 的 `mcp` 组（`fastmcp>=0.4.0`）
  - `InProcessEngineInvoker`：MCP Server 用的同进程 typer app 调用（`src/devflow/adapters/invoker.py`）
  - `mcp_server.py`：动态生成 MCP tool 函数（从 manifest 自动派生，含签名反射）
  - `devflow-mcp-server` 入口脚本（pip install 后自动注册）
  - 文档：[`docs/adapters/mcp.md`](./adapters/mcp.md) Claude Desktop / Cursor / Continue.dev 配置示例
  - v0.3 INDEX 教训根治：manifest 从 cli.py 自动派生，零手写
- **v0.3 三平台 Skill 适配层（B4 阶段）**：
  - `src/devflow/adapters/claude_code.py` Claude Code Skill 生成器（SKILL.md + YAML frontmatter，无需 wrapper 脚本）
  - `src/devflow/adapters/workbuddy.py` WorkBuddy Skill 生成器（JSON 文件）
  - `src/devflow/adapters/codebuddy.py` CodeBuddy Skill 生成器（JSON 文件，含 tool / inputSchema）
  - `src/devflow/adapters/skill_packager.py` `package_for_platform()` 平台分发入口
  - CLI `devflow adapter-export <platform> --target <dir>`：导出 Skill manifest 到目标平台
  - 共享 `SkillManifest` 中间表示，无 per-harness skill copies（obra/superpowers 范式）
- **v0.3 SDD 子代理编排（B2 阶段）**：
  - 数据模型：`DispatchConfig` / `SubagentTask` / `RulingRef` / `RulingType`（架构文档 §5.2.1）
  - `RulingStore`：裁决落 `LedgerAction.RULING` 哈希链（4 类裁决：skip/replan/escalate/halt）
  - `CircuitBreaker`：5 轮断路器 + 用户 halt 优先
  - `AgentRunner` 抽象 + 3 实现：MockAgentRunner（测试桩）/ ClaudeCodeAgentRunner / GenericAgentRunner
  - `Dispatcher.dispatch_task()` 主循环 + `DispatchResult`
  - `dispatch_plan()` 顺序派发
  - `dispatch_plan_parallel()` 拓扑分层 + asyncio.gather（架构文档 §5.2.1 #3）
  - CLI `devflow dispatch <plan_id> [--real-agent] [--parallel]`：SDD 派发入口
  - `create_dispatcher()` 工厂函数（含 GateRunner / ReviewEngine / AgentRunner 注入）
- **v0.3 DAG 环检测（B5 阶段，SDD 前置）**：
  - `src/devflow/util/dag.py` `detect_cycle()` DFS + 三色标记（pure function）
  - `Plan.model_validator` 自动校验 DAG（构造期拦截环）
  - `Plan.validate_dag()` 显式方法
  - 修复架构文档 §16.0 v0.2 待做项（Task.blocked_by 环检测）
- **v0.3 Model 选型从 sop.yaml 读取（B6 阶段）**：
  - `ModelTiersConfig`：implementer / reviewer / escalator 默认 sonnet / haiku / opus
  - `SDConfig`：max_rounds / parallel / worktree_per_task
  - `sop.yaml` 新增 `sd:` 配置节（向前兼容，旧 sop.yaml 用默认值）
  - `_dispatch_config_from_sop()` 字段映射
  - `create_dispatcher()` 自动 fallback 到 sop.yaml 文件
- **v0.3 Worktree 隔离（B7 阶段 · SDD 完整化）**：
  - `src/devflow/engine/worktree.py` `safe_id()` 处理 plan_id 特殊字符（/、空格、冒号等）
  - `create_worktree_for_plan()` 含 git 分支 fallback（非 git 仓库降级 / 已存在分支用 add 而非 -b）
  - `Dispatcher.dispatch_task()` 集成 `worktree_per_task` 配置（启用时为每个 Task 创建隔离 git worktree）
  - worktree 路径传给 `SubagentTask.worktree` 字段
  - worktree 创建失败 → `DispatchResult.error`，不阻断整个 dispatch
- **v0.3 平台 detect + 路由（C7 阶段）**：
  - `src/devflow/adapters/detect.py` `Platform` / `IntegrationMode` 枚举
  - `detect_platform()` 5 平台环境变量探测（CLAUDE_CODE / WORKBUDDY_RUNTIME / CODEBUDDY_RUNTIME / DEVFLOW_MCP_HOST / 默认 CLI）
  - `detect_integration_mode()` 平台能力矩阵（架构文档 §6 双集成面）
  - `is_mcp_callable` / `is_skill_callable` 辅助函数
  - `src/devflow/adapters/router.py` `select_invoker()` / `route_invocation()` 统一入口
  - `create_dispatcher(auto_detect_platform=True)` 默认值（按 detect_platform 自动选 Agent Runner）
  - CLI `devflow adapter-export --auto-detect` flag（按环境变量自动选平台）

- **v0.4 RFC 预案 B 重启（V4 阶段 · 多 spec JOIN 全面版）**：
  - 触发条件：多 spec 工作流成为主流用法（v0.4-roadmap-paused.md §一）
  - 核心设计：review_store 文件名反推（review/<spec-id>/r<N>.yaml）+ 时间窗推断
  - **不扩 LedgerEntry schema**（v0.3 INDEX 教训根治）
  - `src/devflow/engine/review_audit.py` 核心 JOIN 逻辑：
    - `audit_review_ledger()` 多 spec 全面版（替代 v0.3.1-r2 单 spec 简化版）
    - `orphans` 检测（ledger 有 review/fix/escalate 但 review_store 无报告）
    - `missing_in_ledger` 反向校验（review_store 有报告但 ledger 无记录，**v0.4 才实现**）
    - `fix_orphans` / `fix_missing_in_ledger` fix 记录双向 JOIN（架构文档 §9.1 接收反馈闭环）
    - `per_spec_summary` 每个 spec 审计摘要
  - CLI `devflow review-audit` 重写：调用 audit_review_ledger 核心逻辑，**移除 current_spec_id 单点假设**
  - 修复 v0.3 简化版遗留 BUG（set 成员检查 vs 元组成员检查）
- **v0.3 适配层纪律（A2 阶段）**：
  - `src/devflow/adapters/__init__.py` 写入 v0.3 纪律（4 禁 3 允）
- **v0.3 CLI 接口契约注释（A1 阶段）**：
  - `src/devflow/cli.py` 顶部加入接口契约（输入/输出/门禁/协议约束）
- **v0.3 工具函数（C1 阶段）**：
  - `src/devflow/util/json_schema.py` Python 类型 → JSON Schema 类型映射（str/int/float/bool/Optional/Path）
- **v0.3 Skill manifest 自动派生（C3 阶段）**：
  - `src/devflow/adapters/manifest.py` SkillManifest / SkillArg 数据模型
  - `src/devflow/adapters/manifest_builder.py` `build_manifests_from_cli()` 自动从 typer app 派生
- 新增 172 个测试（json_schema × 11 + invoker × 6 + manifest_builder × 8 + mcp_server × 4 + dag × 12 + plan_dag × 11 + dispatcher_models × 12 + circuit_breaker × 8 + agent_runner × 6 + dispatcher × 6 + dispatch_plan × 4 + dispatch_parallel × 6 + dispatch_config_from_sop × 9 + skill_packager × 9 + worktree × 13 + dispatcher_worktree × 5 + detect × 14 + router × 8 + dispatcher_detect × 8 + review_audit × 26 + review_audit_fix_join × 7 + review_audit_cli × 3）

### Changed
- README 头部版本号 v0.2 → v0.3.3 → v0.4.0；测试数量 76 → 121 → 196 → 279 → 327 → 363；架构图红线描述更新（11 红线 + 9 思维检查）
- README「限制与残余风险」更新：标记 v0.3.x + v0.4 部分修复项,残余 P1 指向 audit-ledger
- README「知识图谱」章节精简：移除 commit hook 自动更新说明（已撤回），保留图谱产物与手动更新方法
- `Plan` 模型加 `model_validator` 强制 DAG 校验（B5 阶段补强，v0.2 待做项）
- `create_dispatcher()` 重构：`use_real_agent` / `auto_detect_platform` 路径分离（C7.3 阶段）
- `devflow review-audit` 重写（V4.3）：从 v0.3.1-r2 单 spec 简化版升级到 v0.4 多 spec 全面版

### Changed
- README 头部版本号 v0.2 → v0.3.3；测试数量 76 → 121；架构图红线描述更新（11 红线 + 9 思维检查）
- README「限制与残余风险」更新：标记 v0.3.x 已修复项,残余 P1 指向 audit-ledger
- README「知识图谱」章节精简：移除 commit hook 自动更新说明（已撤回），保留图谱产物与手动更新方法

### Removed
- **撤回 graphify 自动更新配置**：commit hook（post-commit / post-checkout / merge driver）已卸载；`scripts/install-hooks.py`、`.gitattributes`、`devflow init` 集成及 `tests/test_v034_init_hooks.py` 已回滚

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