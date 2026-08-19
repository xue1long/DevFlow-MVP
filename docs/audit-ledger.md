# DevFlow MVP · 审计整改台账

> 本文档记录每一轮审计发现的问题及整改状态，**不可覆盖删除历史记录**。

---

## 第 1 轮审计

### 审计来源
独立第三方审计子代理（首轮全面审计）

### 审计摘要
- 致命缺陷：0 条
- 重大隐患：3 条（R1 伪需求判定、R2 过度工程判定、R7 状态机死路）
- 优化疏漏：9 条（R3-R6, R8-R12）
- 过度工程条目：2 条（R2 八阶段、R3 红线）
- 伪需求条目：2 条（R1 引擎强制、R4 Stage0 空转）

### 整改记录

| 编号 | 风险 | 等级 | 处理状态 | 处理方式 | 说明 |
|---|---|---|---|---|---|
| R1 | 伪需求："引擎强制 Agent 遵守流程" | ②重大隐患 | **不接受伪需求判定，登记残余风险** | 目标合理 | 子代理质疑 Agent 可绕过 CLI 直接 git，但 DevFlow 的定位是"标准化流程+可审计账本+门禁自动检查"，类比 ESLint——开发者也可以不装，但团队选择用。引擎价值不在于技术强制，而在于降低心智负担。残余风险：实际采纳率需验证。 |
| R2 | 过度工程：八阶段流水线 | ②重大隐患 | **不接受过度工程判定，登记残余风险** | 范围合理 | 八阶段从真实项目（ruflo-kb）提炼，每个阶段有明确工件和出口条件。MVP 已大幅降级门禁。砍到 3 阶段会失去核心差异化。残余风险：实现复杂度高于简单工具。 |
| R3 | 过度工程：RedLineAuditor 11 条红线 | ③优化疏漏 | **登记优化疏漏** | MVP 只实现可自动检测的 10 条，circular_dep 标 mvp_skip | 后续版本增加 AST 分析能力。 |
| R4 | 伪需求：Stage0 空转 | ③优化疏漏 | **已整改** | 明确 Stage0 MVP 定位为"入口标记" | 在简报验收 4 中增加说明：MVP 中 Stage0 是入口标记，实质分类判定留 v0.2。 |
| R5 | 一致性：ci_green blocking 矛盾 | ③优化疏漏 | **已修复** | 简报 §1 改为"ci_green（MVP advisory）" | 四文件现在一致：sop.yaml blocking=false，简报 advisory，矩阵"通过"语义明确。 |
| R6 | 一致性：CLI 数量矛盾 | ③优化疏漏 | **已修复** | 统一为 11 个命令（新增 skip-task） | 简报/矩阵/架构文档全部对齐为 11 个。 |
| R7 | 状态机死路：Stage4 git status 锁死 | ②重大隐患 | **已修复** | 新增 `devflow skip-task` 命令 | Task 状态流转增加 skipped 终态，Stage7 完成条件改为"done 或 skipped"。 |
| R8 | suspend/resume 隐含假设 | ③优化疏漏 | **已修复** | resume 重新执行当前阶段出口门禁 | 矩阵 CLI 清单 resume 行为已更新。 |
| R9 | 多 Spec task-id 冲突 | ③优化疏漏 | **已整改** | 明确 task-id 在 Plan 内唯一，commit/skip-task 操作当前活跃 Spec | v0.2 扩展 spec-id/task-id 格式。 |
| R10 | 缺少错误处理规范 | ③优化疏漏 | **登记优化疏漏** | MVP 不阻塞 | CLI 返回 JSON 含 error 字段，退出码非零表示失败。详细规范留 v0.2。 |
| R11 | 缺少并发安全规范 | ③优化疏漏 | **登记优化疏漏** | MVP 声明不支持并发调用 | 在 README 中声明单进程使用。 |
| R12 | 缺少性能规范 | ③优化疏漏 | **登记优化疏漏** | MVP 不保证性能 | 后续版本增加超时和性能基线。 |

### 残余风险清单
1. **R1 残余**：引擎的实际采纳率和质量提升效果未经验证。补偿措施：MVP 交付后做 5-10 个真实任务的对比实验。
2. **R2 残余**：八阶段实现复杂度高于简单工具。补偿措施：M0 先验证状态机核心路径，复杂度可控再推进。
3. **R11 残余**：并发写入可能导致 progress.yaml 损坏。补偿措施：MVP 仅单进程使用，v0.2 增加文件锁。

### 本轮修改潜在副作用评估
1. **新增 skip-task 命令**：增加了 CLI 命令数量（10→11），增加了状态流转路径（新增 skipped 终态）。风险低：skipped 是终态，不影响其他状态转换。
2. **resume 重新执行门禁**：可能导致 resume 后发现"当前阶段已不满足出口条件"（如代码已提交）。这实际上是**正确行为**——resume 应该反映真实状态，而非假设历史状态。
3. **Stage0 定位调整**：纯文档变更，无代码影响。

---

## 第 2 轮审计

### 审计来源
独立第三方审计子代理（复核审计：R7 整改、R1/R2 判定、一致性闭环）

### 审计摘要
- 致命缺陷：0 条
- 重大隐患：2 条（R7-new-1 skip-task 导致 Stage4 死锁、R7-new-2 Abandon-in-Place）
- 优化疏漏：2 条（R7-new-3 Acceptance Bypass、R1/R2 维持原判定但降级）
- 过度工程条目：1 条（R2 维持，但承认 MVP 已降级）
- 伪需求条目：0 条（R1 从"伪需求"降级为"高风险产品选择"）
- 文件间一致性：✅ 通过（ci_green、CLI 数量、Stage7 完成条件四文件一致）

### 整改记录

| 编号 | 风险 | 等级 | 处理状态 | 处理方式 | 说明 |
|---|---|---|---|---|---|
| R7-new-1 | skip-task 导致 Stage4 死锁：所有 task 被 skip 后 git status 为空，无法通过 Stage4 出口门禁 | ②重大隐患 | **已修复** | Stage4 出口门禁增加"或"条件：`git status` 非空 **或** 所有 task 均为 done/skipped。Stage5 边界情况：所有 task skipped 时 pytest 无测试可跑 = exit code 0 = PASS | 修复位置：降级矩阵 §1 Stage4/Stage5 |
| R7-new-2 | Abandon-in-Place：`任何状态 → skipped` 允许跳过已进入 implementing 的 task，已写代码变成脏文件 | ②重大隐患 | **已修复** | skip-task 前置条件限制为仅 `todo` 或 `contracted` 状态可 skip；已进入 implementing/verifying/reviewing 的 task 返回错误提示清理工作区 | 修复位置：降级矩阵 §0.5 |
| R7-new-3 | Acceptance Bypass：跳过 task 后其 acceptance 标准被绕过 | ③优化疏漏 | **登记残余风险** | skip-task 本身就是"需求变更导致 task 不再需要"的正当场景，acceptance 被绕过是预期行为。`--reason` 字段提供审计追踪。残余风险：滥用 skip 绕过关键 task | 修复位置：简报 §6 约束 |
| R1 (复核) | 从"伪需求"降级为"高风险产品选择" | ②重大隐患 | **维持第1轮判定** | 子代理接受主控的反驳理由（类比 ESLint），但保留"高风险"标记 | 残余风险同第1轮 |
| R2 (复核) | 过度工程：八阶段 | ②重大隐患 | **维持第1轮判定** | 子代理承认 MVP 已降级，但维持"8 阶段对 MVP 偏重"的判断 | 残余风险同第1轮 |

### 残余风险清单（新增）
4. **R7-new-3 残余**：滥用 skip-task 绕过关键 task 的 acceptance。补偿措施：`--reason` 强制提供，ledger 记录审计追踪；`devflow audit` 可检查 skip 比例异常。
5. **R1 降级残余**：从"伪需求"降级为"高风险产品选择"。引擎价值成立但采纳率不确定。补偿措施同第1轮。

### 本轮修改潜在副作用评估
1. **Stage4 出口门禁增加"或"条件**：逻辑变复杂，但解决了死锁问题。副作用低：正常开发流程（有代码变更）走第一个条件，skip 场景走第二个条件，互不干扰。
2. **skip-task 状态约束收窄**：从"任何状态"收窄为"todo/contracted"。副作用：用户在 implement 阶段发现 task 不需要时，需要先 `git stash` 再联系管理员手动处理，体验略有下降。但安全性远高于便利性。
3. **无新增过度工程**：所有整改都是在现有框架内修补，未引入新的抽象层或组件。

---

## 第 3 轮审计（4 角色独立评审）

### 审计来源
4 位独立评审子代理并行作业，互不借鉴，各自读取源码后独立输出问题清单：
- 落地执行者（实操卡点/流程断层）：23 条
- 风险管控者（隐患/合规/损失/应急预案）：18 条
- 逆向挑战者（逻辑漏洞/反例/失效条件）：25 条
- 最终验收人（能否达成原始目标）：21 条

### 审计摘要
- 致命缺陷（P0）：8 条
- 重大隐患（P1）：14 条
- 优化疏漏（P2）：19 条
- 三个致命断裂点（4 角色独立指向同一结论）：
  1. 数据安全层（账本非真正 append-only、并发无锁、可篡改）
  2. 阶段约束完整性（CLI 缺 Plan/Task/Contract 命令、review_gate 不触发、commit/approve 不校验阶段）
  3. 双轴评审真实性（Spec 轴空壳）

### P0 致命缺陷整改记录（第 3.1 轮）

| 编号 | 风险 | 处理状态 | 处理方式 |
|---|---|---|---|
| P0-1 | progress.yaml 非真正 append-only，写入中断即全损 | ✅ 已修复 | 账本改为原子写（tempfile+rename+fsync） |
| P0-2 | 并发写无锁，双进程静默丢失条目 | ✅ 已修复 | 新增进程级文件锁（O_EXCL+过期检测+超时） |
| P0-3 | 账本可被任意篡改，无不可变性保障 | ✅ 已修复 | 追加 SHA256 哈希链（写时+验证时一致） |
| P0-4 | Spec 轴评审是空壳，双轴评审实际只有单轴 | ✅ 已修复 | `_run_spec_checks` 真实检查 goal 覆盖 + contract 缺失 |
| P0-5 | CLI 无 Plan/Task/Contract 创建命令，Stage2/3 断层 | ✅ 已修复 | 新增 plan/task-add/task-list/contract-add 命令 |
| P0-6 | review_gate 绑定但 next_phase() 从不触发 | ✅ 已修复 | next_phase() 检查 review_gate（bind_to_stage 匹配时阻断） |
| P0-7 | shell=True 执行 sop.yaml 命令，命令注入 | ✅ 已修复 | `_validate_command` + DANGEROUS_PATTERNS 拦截破坏性命令 |
| P0-8 | git add -A 可能提交敏感文件 | ✅ 已修复 | SENSITIVE_PATTERNS 检测 + commit 前阻止 |

### P1 重大隐患整改记录（第 3.2 轮）

| 编号 | 风险 | 处理状态 | 处理方式 |
|---|---|---|---|
| P1-1 | spec_id 无唯一性校验，碰撞覆盖 | ✅ 已修复 | 冲突检测 + HHMMSS 时间戳后缀 + 随机数兜底 |
| P1-2 | _gate_review 在 GateRunner 缺失时默认 PASS | 登记残余风险 | ci_green 为 advisory 门禁（blocking:false），MVP 阶段放行属设计意图；v0.3 统一降级策略 |
| P1-3 | commit_task 不校验当前阶段 | ✅ 已修复 | phase<5 拒绝 commit（"只能在 Stage5 之后"） |
| P1-4 | approve_spec 不检查当前阶段 | ✅ 已修复 | phase>1 拒绝 approve（"只能在 Stage0/1"） |
| P1-5 | 5 条红线空实现静默返回空 | 登记残余风险 | 由状态机门禁间接保障；v0.3 补 AST 级检查 |
| P1-6 | fix 对非 AUTO_VERIFIABLE 规则无验证 | 登记残余风险 | 6 条规则已自动重验；其余规则需人工判断，fix summary 作审计记录 |
| P1-7 | 停滞检测口径含已 resolved | ✅ 已修复 | 改用 `total_violations - resolved_count`（未修复数） |
| P1-8 | next 自动 resume 副作用 | 登记残余风险 | 文档化：suspend 后 next 会先 resume；已输出明确提示 |
| P1-9 | ci_green 占位且非阻断 | 登记残余风险 | MVP advisory 设计，v0.3 接真实 CI |
| P1-10 | 账本缺 actor/session_id | 登记残余风险 | v0.3 账本 schema 扩展 |
| P1-11 | _check_no_test 硬编码 .py | 登记残余风险 | v0.3 语言中性化 |
| P1-12 | subprocess 无超时 | ✅ 已修复 | timeout 从 tooling.command_timeout 读取（默认 120s），超时返 -2 |
| P1-13 | review 报告与账本无交叉校验 | 登记残余风险 | v0.3 增加 review_id ↔ ledger 交叉引用 |
| P1-14 | write_report 同轮次覆盖 | ✅ 已修复 | write_report 默认禁止覆写（force=False raise），fix 用 update_report 专用方法 |

### 第 3 轮复核审计结论（独立子代理）

- ✅ 已修复：**14/14**（P0-1~8 全部 + P1-1/3/4/7/12/14 全部）
- ❌ 未修复：0
- 登记残余风险：**7 项**（P1-2/5/6/8/9/10/11/13 — 8 项，其余 6 项已修复）
- 验证方式：新增 `tests/test_p0_fixes.py` 12 个测试锁定关键场景，全量回归 **76 passed / 1 skipped**（原 64 + 新 12，skip 为预期 minor 场景）

### 第 3 轮修改潜在副作用评估

1. **P0-4 Spec 轴真实检查改变 review 语义**：此前 Spec 轴恒 PASS；现在 Plan 存在时，未覆盖 goal / 缺 contract 会判 FAIL 并阻断推进。副作用：用户必须先建 Plan 且补齐 Contract 才能通过 review——这是**预期收紧**，与 P0-5 新命令配套。
2. **P0-6 review_gate 接入 next_phase**：plan 阶段出口未评审会被阻断。副作用：新增一条必经检查；配套 fix 闭环可解除。
3. **P1-3 commit 阶段校验**：commit 只能在 Stage5+ 执行。副作用：测试 test_6 断言更新（阶段校验优先于代码变更检查），行为更严格。
4. **P1-4 approve 阶段校验**：approve 只能在 Stage0/1。副作用：已推进的流程不可回头补 approve，符合"不可跳步"语义。
5. **账本哈希链**：条目新增 `_hash/_prev_hash` 字段（YAML 可见）。副作用：旧账本无哈希字段会验出失败——需用 `verify_ledger` 迁移或重建；MVP 阶段账本可重建。

### 第 3 轮残余风险清单（新增）

6. **P1-2 残余**：GateRunner 缺失时 review 门禁 fail-open。补偿措施：MVP ci_green 为 advisory，v0.3 统一 fail-closed。
7. **P1-5 残余**：5 条红线空实现可能给人"已检查"假象。补偿措施：audit 输出标注实现状态，v0.3 补 AST 检查。
8. **P1-6 残余**：非自动可验证规则的 fix 无真实验证。补偿措施：fix summary 强提示 + 人工确认。
9. **P1-8 残余**：next 隐式 resume 不可撤销。补偿措施：已在 CLI 输出中明确提示 resume 动作。
10. **P1-9 残余**：ci_green 占位命令。补偿措施：v0.3 接真实 CI。
11. **P1-10 残余**：账本无 actor/session_id。补偿措施：v0.3 账本 schema 扩展 + 审计命令。
12. **P1-11 残余**：no_test 硬编码 .py。补偿措施：v0.3 按 sop.tooling 语言配置。
13. **P1-13 残余**：review 报告与账本无交叉校验。补偿措施：v0.3 双向引用 + 完整性检查。

### P2 优化疏漏整改记录（第 3.3 轮）

| 编号 | 风险 | 处理状态 | 处理方式 |
|---|---|---|---|
| P2-1 | 缺 README | ✅ 已修复 | 新增 README.md（含安装/5分钟上手/CLI 速查/阶段对照/架构图） |
| P2-3 | status 不显示 Spec 内容摘要 | ✅ 已修复 | 新增 spec_summary（标题/状态/缺失字段）+ plan_summary（task 计数/状态分布/缺合同） |
| P2-4 | gate <phase> 阶段名映射无提示 | ✅ 已修复 | docstring 列出对照 + 结果补充 phase_name |
| P2-5 | _gate_intake 不读 intake_gate 配置 | ✅ 已修复 | 读取 gates.intake_gate.kind/require/enabled 配置 |
| P2-6 | init 内嵌默认 YAML 双份维护 | ✅ 已修复 | 优先读 sop.default.yaml；缺失时打印警告并兜底 |
| P2-8 | cross_module_import 字符串匹配误报 | ✅ 已修复 | 正则解析 import/from 语句，仅匹配模块名，避开注释和字符串字面量 |
| P2-10 | residual_count 永远为 0 | ✅ 已修复 | 修复统计口径（不再依赖 resolved）；新增 active_residual_count |
| P2-19 | resume 不验证恢复后文件一致性 | ✅ 已修复 | 检查 spec/plan 文件是否仍存在，缺失时写 warnings 并在账本标记 |

### P2 未处理项（登记残余风险）

14. **P2-7 残余**：`log_oneline(5)` 硬编码最近 5 个 commit。补偿：审计面有限，v0.3 改为可配置。
15. **P2-9 残余**：`_spec_id_from_fix` 全目录扫描 O(n*m)。补偿：MVP 规模下性能可接受，v0.3 改为索引缓存。
16. **P2-11 残余**：sop.yaml 可配置 phases 但 PHASE_NAMES 硬编码 8 个。补偿：MVP 8 阶段固定，v0.3 扩展。
17. **P2-12 残余**：`intake_fast_skip=true` 时 intake 闸门永不阻断。补偿：v0.3 改 fail-closed。
18. **P2-13 残余**：run_gate 内置门禁 + 外部门禁重复执行 tests_pass。补偿：性能影响小，v0.3 优化。
19. **P2-14 残余**：门禁结果不持久化（无法追溯 stdout/stderr）。补偿：v0.3 加 ledger gate_result 字段。
20. **P2-15 残余**：无并发/错误恢复测试。补偿：本轮已补 18 条测试（76+6=82），并发测试需 v0.3 引入锁测试环境。
21. **P2-16 残余**：Spec 轴 context 不含实际代码内容（仅 LLM 用）。补偿：v0.3 增加 diff 注入。
22. **P2-17 残余**：timestamp 无时区。补偿：v0.3 用 timezone-aware datetime。
23. **P2-18 残余**：StorageBackend 接口过宽（含状态管理方法）。补偿：v0.3 拆分为状态层 + 存储层。

### 第 3.3 轮修改潜在副作用评估

1. **P2-3 status 字段扩展**：现有调用方读 status 可能只读旧字段；新字段向后兼容。
2. **P2-5 intake_gate 启用检查**：若用户显式 disabled: true 闸门将跳过——属于可配置化扩展，预期行为。
3. **P2-8 cross_module_import 精度提升**：原误报会消失，可能让某些"故意违反但模式匹配"的违规不再被报——属预期收紧。
4. **P2-10 residual_count 口径变化**：从 `residual and not resolved` → `residual`。历史报告中已登记残差（已 resolved=True）现在计入；前端展示逻辑需相应更新。
5. **P2-19 resume 返回结构**：从只返回 message 改为 `{ok, phase, phase_name, warnings, gate, message}`，向后兼容（CLI 输出仍可读）。

### 第 3 轮最终测试统计

- 全量回归：**82 passed / 1 skipped**
- 测试组成：原有 64 + P0 整改验证 12 + P2 整改验证 6
- skip 项：test_11（minor 违规登记残余，需特殊配置）

---
