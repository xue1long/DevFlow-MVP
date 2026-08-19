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

## 第 4 轮审计（v0.3 INDEX 方案审核 + 第一性回退）

### 审计来源
4 角色独立评审（落地执行者/风险管控者/逆向挑战者/最终验收人）+ 1 第一性质疑者
按 [`first-principles-sop.md`](./first-principles-sop.md) 完整 4 阶段流程走一遍。

### 审核对象
v0.3 INDEX 方案（commit `f49af51`）：软归档 + 跨文件搜索（4 个新接口 + 4 个 CLI 命令）

### 审计摘要
- 🔴 致命风险：7 项（4 角色独立指出，多角色交叉指向同一问题）
- 🟠 重大隐患：6 项
- 🟡 优化疏漏：5 项
- 🟢 轻微瑕疵：3 项
- **[F] 强质疑 1 项**（角色5 第一性质疑者）：方案跳过了最简替代

### 第一性质疑结论（角色5）
| # | 质疑 | 判定 |
|---|------|------|
| 1 | 归档是真需求还是伪需求？ | [P] 补强 |
| 2 | INDEX 替代重组路径未经数据验证 | [P] 补强 |
| 3 | archive 段不破坏哈希链 | [N] 通过 |
| 4 | **更简单替代（Spec 文件内 status）被跳过** | **[F] 方案应重做** |
| 5 | 自动归档时机过早，缺 unescape | [P] 补强 |

### 关键决策
**接受 [F] 质疑 4，回退 v0.3 INDEX 复杂方案**，采用最简替代：
- Spec YAML 加 `status: archived` 字段（可选）
- list-active / list-archived 按 status 过滤
- find 用 Python 直接扫描文件（无需新接口）
- archive 写 ledger entry（不修改 entries 哈希链）
- **撤销归档**：手动改 status 字段即可（无需 unarchive 命令）

### 整改记录
| 编号 | 类别 | 处理状态 | 处理方式 |
|------|------|----------|----------|
| f49af51 | A（方案错） | ✅ 已回退 | 全部 revert（代码 + 测试）+ INDEX_FORMAT.md → v0.3-rejected-design.md 归档 |
| P0-1 至 P0-7 | B（实现错） | ✅ 已规避 | 回退到最简方案后不存在 |
| P1-1 至 P1-6 | B/D | ✅ 已规避 | 同上 |
| 质疑4 [F] | A（方案错） | ✅ 已处理 | 采纳建议，改为最简方案 |

### 实施结果（v0.3 最简方案）
- **改动文件**：2 个（`model/spec.py` + `cli.py`）
- **新增测试**：11 条（`tests/test_simple_archive.py`）
- **全量回归**：93 passed / 1 skipped（原 82 + 新 11）
- **代码量对比**：
  - INDEX 复杂方案：652 行（9 文件）+ 10 测试
  - 最简方案：~150 行（2 文件）+ 11 测试

### 第一性原理验证
- ✅ 方案 B 的"更简单方案优先"原则落地
- ✅ 零新接口、零账本新段、零哈希链风险
- ✅ 撤销归档天然支持（改 status 即可）
- ✅ 跨文件搜索可立即使用
- ✅ 向后兼容 v0.2.1（status 默认 "draft"）

### 残余风险
- **P1-3 残余**：query 性能 O(N×M) 无分页。补偿：MVP 阶段 Spec 数量小，v0.4 加缓存。
- **P1-6 残余**：归档无 tag/时间维度。补偿：status 是简单枚举，扩展可在 spec YAML 加 metadata 字段。
- **P3-2 残余**：`files_at` 概念被移除（最简方案不需要），但工作区迁移需手动调整 git remote。

---

## 第 5 轮审计（v0.3.1 方案预审）

### 审计来源
4 角色独立评审（落地执行者 / 风险管控者 / 逆向挑战者 / 最终验收人），互不借鉴，独立读取源码与方案文档后输出问题清单：
- 落地执行者（实操卡点/代码可落地性）：20 条
- 风险管控者（隐患/合规/损失/应急）：16 条
- 逆向挑战者（逻辑漏洞/反例/失效条件）：19 条
- 最终验收人（目标达成/手册遵循/第一性）：22 条

### 审计摘要
- 🔴 **致命问题：8 个**（7 个多角色交叉指向 + 1 个单角色 P0）
- 🟠 **重大问题：24 个**
- 🟡 **优化疏漏：18 个**
- **统一共识**：v0.3.1 方案核心修复 P1-13（review ↔ ledger 双向引用）**重蹈 v0.3 INDEX 覆辙**——扩 storage schema + 新 CLI 命令 + 5 处 ledger 写入点迁移 = 与 v0.3 INDEX 回退的 [F] 质疑 4 一一对应。

### 多角色交叉 P0 矩阵

> **交叉规则**：≥ 3 个独立角色指向同一问题 → 升为绝对 P0

| # | 交叉问题 | 落地 | 风险 | 逆向 | 验收 | 等级 |
|---|---|---|---|---|---|---|
| 1 | **P1-13 LedgerEntry 字段扩展破坏哈希链** | ✅ | ✅ | ✅ | ✅ | 🔴 P0 |
| 2 | **P1-13 ledger 字段缺失 / 5 处 append_ledger 漏算** | ✅ | ✅ | ✅ | ✅ | 🔴 P0 |
| 3 | **P1-13 重蹈 v0.3 INDEX 覆辙** | — | 隐含 | ✅ | ✅ | 🔴 P0 |
| 4 | **P1-9 pytest 双跑 Stage5+Stage6（CI 时间 ×2）** | — | — | ✅ | ✅ | 🔴 P0 |
| 5 | **P1-9 `_extract_coverage` 正则脆弱** | ✅ | ✅ | ✅ | — | 🔴 P0 |
| 6 | **P1-2 fail-closed 破坏隐性兼容（无 deprecation）** | ✅ | ✅ | ✅ | ✅ | 🔴 P0 |
| 7 | **P1-5 stub 暴露让"已审计"承诺降级** | ✅ | ✅ | ✅ | — | 🔴 P0 |
| 8 | **P1-9 `--cov=src/devflow` 硬编码路径** | ✅ | — | ✅ | — | 🟠 P1 |

### P0 致命问题明细

#### 1. LedgerEntry 字段扩展破坏哈希链（4 角色交叉）
- **事实**：`fs_backend.py:107-120` `_compute_entry_hash` 用 `json.dumps(content, sort_keys=True)` 序列化**整个 entry 字典**（仅排除 `_hash/_prev_hash`）；P1-13 新增 `review_id/actor` 字段会被 hash 计算包含。
- **后果**：新写入条目 hash 改变 → 后续所有条目 prev_hash 连锁改变 → 整个账本从第一个 review_id 写入处开始全部作废 → 旧账本 `verify_ledger()` 立即报失败。
- **方案声称**：新字段不参与 hash 计算（与代码事实不符）。
- **来源**：角色1 P0-2 / 角色2 P0-1 / 角色3 P0-V31-2 / 角色4 P1-03。

#### 2. P1-13 实际有 5 处 append_ledger，方案只列 3 处（4 角色交叉）
- **事实**：`review_engine.py` 实际有 4-5 处 `append_ledger` 调用：`review():129`、`fix():244`、`_escalate():618`、`_stagnation_escalate():683`（共 4 处，角色1/3 共识）。
- **后果**：方案示例机械搬抄在 `_escalate`/`_stagnation_escalate` 分支会 `NameError`（无 `report` 变量）；漏算 `fix()` 路径的 review_id 字段导致双向校验失效。
- **来源**：角色1 P0-1 / 角色2 P0-3 / 角色3 P0-V31-1 / 角色4 F-02。

#### 3. P1-13 重蹈 v0.3 INDEX 覆辙（3 角色交叉）
- **事实**：P1-13 的"扩 LedgerEntry + 新增 review-audit CLI + 改 5 处 ledger 写入"与 v0.3 INDEX 的"扩 storage schema + 新增 archive_spec 等 ABC 方法"在结构上**一一对应**。
- **后果**：违反第一性原则「更简替代优先」——review-audit 可用文件系统 JOIN 现有 review_store + ledger 完成，不需扩 schema。
- **来源**：角色3 / 角色4 P1-07 / 角色2 隐含。

#### 4. P1-9 pytest 双跑 Stage5+Stage6（2 角色交叉 + 1 关键 P0）
- **事实**：`sop.default.yaml` 中 `tests_pass.command = "pytest"`，修复后 `ci_green.command = "pytest --cov=..."`，Stage5 跑一次 pytest，Stage6 又跑一次 pytest，CI 时间 ×2 且 `.coverage` 文件被覆盖。
- **后果**：用户项目 pytest 全套件跑两遍；首次 `.coverage` 被覆盖；200 测试项目耗时翻倍。
- **来源**：角色3 P0-V31-3 / 角色4 P1-02。

#### 5. P1-9 `_extract_coverage` 正则脆弱（3 角色交叉）
- **事实**：正则 `r"TOTAL\s+\d+\s+\d+\s+(\d+)%"` 与 pytest-cov 输出格式强耦合。
- **后果**：Windows ANSI 颜色码干扰 / pytest-cov 9.x 输出格式变化 / coverage 7.x `precision=1` 小数输出 / src 目录为空时 `No data to report.` → 正则全部 miss → 返回 None → `f"覆盖率 {coverage}%"` TypeError。
- **来源**：角色1 P0-3 / 角色2 P1-6 / 角色3 P1-V31-3。

#### 6. P1-2 fail-closed 破坏隐性兼容（4 角色交叉）
- **事实**：v0.2.x README 与"5 分钟上手"依赖"GateRunner 缺失自动通过"避免阻断；v0.3.0 → v0.3.1 升级用户无任何 deprecation 期。
- **后果**：现有用户升级即撞墙；`sop.default.yaml` 默认 `review_gate.enabled=true` 让 Stage3 必卡；现有测试 fixture 不传 gate_runner 会 fail。
- **来源**：角色1 P2-8 / 角色2 P0-2 / 角色3 P0-V31-4 / 角色4 P1-04。

#### 7. P1-5 stub 暴露让"已审计"承诺降级（3 角色交叉）
- **事实**：5 条红线（`skip_phase` / `doc_drift` / `silent_legacy` / `no_contract` / `human_step_auto`）返回 [] 标 stub 后，`_check_doc_drift` / `_check_silent_legacy` 在 state_machine **完全无对应实现**（仅形式保障，非语义保障）。
- **后果**：外部审计/合规要求若依据 `devflow audit` 通过=已审计，会高估 2 条红线的实际保障；用户看到 `audit.total=11` 误以为项目违规暴涨。
- **来源**：角色1 P2-1 / 角色2 P1-5 / 角色3 P1-V31-2。

#### 8. P1-9 `--cov=src/devflow` 硬编码路径（2 角色交叉）
- **事实**：`cli.py:_get_root()` 用 `Path.cwd()`，DevFlow 在 `src/devflow/`，用户项目代码通常在 `app/`/`pkg/`/`lib/`/`src/<project>/`。
- **后果**：硬编码 `--cov=src/devflow` 永远只覆盖 DevFlow 自身（覆盖率 100%），用户项目覆盖率恒为 0% 或 No data to report。
- **来源**：角色1 P2-7 / 角色3 P2-V31-1。

### 第一性原则验证（4 角色共识）

| P1 项 | 当前方案 | 更简替代 | 第一性判定 |
|---|---|---|---|
| P1-2 fail-closed | 改 `_gate_review` + 破坏隐性兼容 | sop.yaml ci_green.enabled 默认 false + fallback | 妥协合理（trust-root 收紧） |
| P1-5 stub 标记 | + status 字段 + 重构 audit() + 新 model/redline.py | 不改 redline_auditor，只在 cli.py 输出区分三类 | ❌ 过度工程（v0.3 INDEX 教训） |
| P1-9 真 CI | + pytest-cov + 70% 阈值 + 提取覆盖率 + 新依赖 | 保留 echo 占位 + status 加提示 + --real-ci 覆盖 | ❌ 过度承诺 |
| P1-13 双向引用 | 扩 LedgerEntry + review_engine 5 处改 + 新 CLI | `review-audit` 用文件系统 JOIN 现有结构 | ❌ **重蹈 v0.3 INDEX 覆辙** |

**v0.3 INDEX 教训落地度：0/4**（v0.3-rejected-design.md 第 4 轮 [F] 质疑 4 直接对应）

### 决策树匹配度（角色4 验证）

| 修复项 | 方案声称 | 决策树实际 | 判定 |
|---|---|---|---|
| P1-2 | 模块 5 优化 | "在跑但坏" → 模块 3 修补 | ❌ 错配 |
| P1-5 | 模块 5 优化 | "在跑但慢/差" → 模块 5 | ✅ 匹配 |
| P1-9 | 模块 5 优化 | "在跑但慢/差" → 模块 5 | ✅ 匹配 |
| P1-13 | 模块 6 跨模块 | 数据审计缺陷 → 模块 3 + 反思维警告 | ❌ 错配 |

**手册遵循度：3/4（错配率 50%）**

### 关键决策

> **接受 4 角色独立审计共识：v0.3.1 方案整体回退**
> 
> 1. **回退理由**：7 个 P0 交叉问题 + v0.3 INDEX 教训未落地 + 手册遵循度仅 50%
> 2. **回退范围**：P1-13 整项、P1-9 整项、P1-5 大部分、P1-2 部分
> 3. **保留范围**：仅"3 个 stub 红线改返回 mvp_skip 标记"等最小改动
> 4. **下一步**：按第一性原则重新设计 v0.3.1 方案，所有 P1-13/P1-9 重走最简替代路径

### 整改记录

| 编号 | 类别 | 处理状态 | 处理方式 |
|---|---|---|---|
| P1-2 部分 | B（实现错） | ✅ 接受 | 改为 sop.yaml 默认 enabled=false + cli.py fallback |
| P1-5 最小 | C（优化疏漏） | ✅ 接受 | 仅给 stub 加 `status` 字段，不重构 audit() |
| P1-9 | A（方案错） | ✅ 整体回退 | 重走最简替代：不接 pytest-cov，保留 echo 占位 |
| P1-13 | A（方案错） | ✅ **整体回退** | 重走最简替代：review-audit 用文件系统 JOIN |

### 残余风险清单（新增）

8. **P0 残余**：v0.3.1 方案未实施，无新风险增量。
9. **第一性残余**：若 v0.3.1 重设计仍走"扩 schema"老路，会再次被回退。**补偿**：每次修补前先过 [first-principles-sop.md](./first-principles-sop.md) §3.1「更简替代优先」检查。

### 本轮修改潜在副作用评估

无（仅作审计归档，未实施代码修改）。

### 应急缺口清单（角色2 独立发现）

1. 无 `devflow doctor` 健康检查命令
2. 无 `devflow audit --exclude-status=stub` 过滤参数
3. 无账本迁移工具（若 hash 链断裂需重建）
4. 无 v0.3.1 → v0.3.0 回滚策略
5. pytest-cov 安装失败无提示（advisory 静默）
6. `actor` 字段无启用标记（Speculative Generality 陷阱）
7. 无 `devflow migrate-ledger` 类迁移命令

---

## 第 5 轮审计（r2：v0.3.1 最简替代方案二次审计）

### 审计来源
1 个综合审计子代理（4 视角合 1），独立读取 r1、r2、源代码与本台账第 5 轮 r1 段，专门验证 r2 是否真规避 r1 的 7 个 P0。

### 审计结论摘要
- ✅ **r1 的 7 个 P0 形式规避：7/7 成功**（零破坏兼容、零新依赖、零 schema 变更）
- ⚠️ **修复目标达成：失败 2 项**
  - **NP0-1**：P1-5 stub 透明化目标完全未达成
  - **NP0-2**：P1-13 JOIN 校验目标部分未达成
- 🟡 **新引入 P1/P2：6 条**（字段破坏/审计盲点/笔误/死代码/配置漂移/命名混淆）

### r2 r1-P0 规避验证矩阵

| r1 P0 | r2 规避策略 | 实际验证 | 判定 |
|---|---|---|---|
| P0-1 LedgerEntry 哈希链 | 不扩 schema | grep LedgerEntry 加字段 = 0；`_compute_entry_hash` L107-120 未改；`review_store.list_reports/list_spec_ids` 已存在 | ✅ 规避成功 |
| P0-2 ledger 字段缺失/5 处 append_ledger 漏算 | 不改 review_engine.py | grep `append_ledger` = 4 处（129/244/618/683），r2 不动 review_engine | ✅ 规避成功 |
| P0-3 重蹈 v0.3 INDEX 覆辙 | 零新接口 | grep `LedgerEntry.__init__` = 0；grep `RedLineViolation.__init__` = 0；pyproject.toml 零新依赖 | ✅ 规避成功 |
| P0-4 pytest 双跑 Stage5+Stage6 | 不接 pytest | `sop.default.yaml:32` ci_green.command 保持 echo；无 pytest-cov 引入 | ✅ 规避成功 |
| P0-5 `_extract_coverage` 正则脆弱 | r2 无此函数 | grep `_extract_coverage` = 0 出现 | ✅ 规避成功 |
| P0-6 fail-closed 破坏隐性兼容 | 仅改 YAML 默认值 | `state_machine.py:756-759` `_gate_review` 未改 | ✅ 规避成功 |
| P0-7 stub 暴露让审计承诺降级 | 不改 RedLineAuditor 模型 | grep `RedLineViolation.__init__` = 0；**但 P1-5 修复实质失败**（见 NP0-1） | ⚠️ 形式规避/实质失败 |

### r2 引入的新 P0

#### NP0-1：P1-5 stub 透明化目标完全未达成
- **事实**：5 条 stub 红线（`_check_skip_phase` / `_check_doc_drift` / `_check_silent_legacy` / `_check_no_contract` / `_check_human_step_auto`）**全部都有方法**（redline_auditor.py:164-176），只是返回 `[]`。r2 的 `if checker is None` 分支**永远不触发**。
- **后果**：r2 cli 输出 `coverage.not_implemented` 永远为 0；`coverage.implemented = len(real) + len(skipped)` 漏算 5 条 stub；`coverage.configured = 11` 但实际报告只列 1 条 mvp_skip（circular_dep）。**用户看到 coverage 字段误以为 11 条都实现了**——与 r2 声称的"5 条 stub 透明化"完全相反。
- **根因**：r2 把"暴露 stub"的目标简化为"输出 coverage 字段"，但忘了**stub 必须实际出现在 skipped 列表里才能被用户看到**。r2 的 `audit()` 方法体修改**实质未改变 5 条 stub 的可见性**——它们仍然返回 `[]`，仍不在 violations 列表里。
- **整改方向**：5 条 stub 必须改为返回 `[RedLineViolation(..., skip=True, message="...")]`，让它们真的进入 skipped 列表。

#### NP0-2：P1-13 JOIN spec_id 关联键错误
- **事实**：`LedgerEntry` 模型字段（model/ledger.py:30-43）不含 `spec_id` 字段。r2 第 316 行 `spec_id = ledger.get("current_spec_id")` 把**所有 ledger entries 都关联到当前活跃 spec**。
- **后果**：ledger 中历史 spec 写入的 review/fix/escalate entries 会被错误关联到**当前 spec**——既可能误报孤儿（当前 spec 没报告但 ledger 说有），也可能漏报孤儿（历史 spec 有 report 但 ledger entry 被错误归到当前 spec）。**多 Spec 工作流将系统性误报**。
- **根因**：v0.3 INDEX 教训"JOIN 必须有准确关联键"未充分贯彻。`details` 文本解析 round 是脆弱的；用 `current_spec_id` 是错误的（不是 entry 当时的 spec）。
- **整改方向**：(a) 用 entry 写入时的 `phase + action` 推断；(b) 在 review_store 端用 `spec_id/round` 反向查（已有 API）；(c) 真正的双向 JOIN 需要 LedgerEntry 有 spec_id 字段——这又回到 r1 的扩 schema 老路。

### r2 引入的新 P1/P2

- **P1-r2-1**：`audit` CLI 输出 `total` 字段被破坏性移除（→ `total_real` + `total_skipped`），`active` 字段被移除。依赖旧字段名的脚本会 KeyError。r2 第 181 行已承认。
- **P1-r2-2**：r2 `missing_in_ledger: []` 硬编码空列表，反向校验（"有报告但 ledger 没记录"——这是审计场景最常见的故障）留 v0.4 形成核心盲点。
- **P2-r2-1**：r2 第 256 行笔误"ci-greem"（应为"ci-green"），反映校对疏漏。
- **P2-r2-2**：r2 `ci-status` 命令的 placeholder 分支是死代码（因 `enabled=false` 优先命中），命令实现与方案描述不符。
- **P2-r2-3**：r2 改 `ci_green.enabled: true → false` 后，新旧用户行为不一致（旧用户需手动改 sop.yaml），文档未覆盖。
- **P2-r2-4**：`total_real` 命名与既有 `ReviewReport.total_violations` 命名空间重叠，语义不一致易混淆。

### 整改记录

| 编号 | 类别 | 处理状态 | 处理方式 |
|---|---|---|---|
| NP0-1 | B（实现错） | ✅ 接受 | P1-5 必须改为让 stub 实际返回 RedLineViolation（不能仅靠 coverage 字段） |
| NP0-2 | B/D（JOIN 关联键错） | ✅ 接受 | P1-13 JOIN 需用更稳的关联键（review_store 端反查 + phase 推断） |
| P1-r2-1 | B（破坏字段名） | ✅ 接受 | 保留 `total` 字段（兼容），新增 `total_real`/`coverage` 作为附加 |
| P1-r2-2 | C（审计盲点） | ✅ 接受 | v0.4 必做项，本轮明确登记 |
| P2-r2-1 | D（笔误） | ✅ 接受 | 下次校对 |
| P2-r2-2 | B（死代码） | ✅ 接受 | 移除 placeholder 分支或保留 enabled=true 让分支可达 |
| P2-r2-3 | D（文档缺失） | ✅ 接受 | README + CHANGELOG 明确旧用户升级步骤 |
| P2-r2-4 | D（命名混淆） | ✅ 接受 | 重命名为 `audit_total_real` 或在文档明确区分 |

### 最终判定

> **r2 方案：6 项修补中 4 项可落地（P1-2/P1-9 全可用 + P1-13 形式合规但需补 JOIN 准确性），2 项需重做（P1-5 stub 必须真正进入 violations）**
>
> - ✅ **P1-2 仅改 YAML 默认值**：可立即落地
> - ✅ **P1-9 加 ci-status CLI**：可立即落地（建议移除 placeholder 死代码）
> - ⚠️ **P1-5 stub 透明化**：NP0-1 暴露的根因（stub 返回 []）未改——必须改为返回 RedLineViolation(skip=True)
> - ⚠️ **P1-13 review-audit JOIN**：NP0-2 暴露的 spec_id 关联错误——需用 review_store 端反查（已有 API）
>
> **下一步**：基于本轮审计，重做 v0.3.1-r3 方案——保留 P1-2/P1-9，修补 P1-5（让 stub 真正出现）+ P1-13（用 review_store 端反查替代 current_spec_id 关联）。预计工期仍 1.5 天。

### 实施结果（r2 已落地）

> **决策**：接受 r2 自审判定，**先落地 r2 可用部分（P1-2/P1-5/P1-9/P1-13 单 spec 版），P1-5/P1-13 完整方案推 v0.4**。

| 修补 | 落地内容 | 验证 |
|---|---|---|
| **P1-2** | `sop.default.yaml` ci_green.enabled 默认 `true → false` | ✅ 测试锁定（test_p1_2） |
| **P1-5** | 5 条 stub 红线改显式返回 `RedLineViolation(skip=True)`；audit 输出加 `total_real`/`coverage` 字段 | ✅ 测试锁定（test_p1_5 ×2） |
| **P1-9** | 新增 CLI `devflow ci-status`（识别 disabled/enabled） | ✅ 测试锁定（test_p1_9 ×2） |
| **P1-13** | 新增 CLI `devflow review-audit`（单 spec JOIN 简化版，不扩 schema） | ✅ 测试锁定（test_p1_13 ×2） |

**改动文件**：
- `config/sop.default.yaml`（P1-2）
- `src/devflow/engine/redline_auditor.py`（P1-5）
- `src/devflow/cli.py`（P1-5 输出 + P1-9 ci-status + P1-13 review-audit）
- `tests/test_v031_r2.py`（7 条新测试）
- `docs/CHANGELOG.md`（v0.3.1-r2 段）

**全量回归**：**100 passed / 1 skipped**（基线 93 + 新 7）

**明确留 v0.4**：
- P1-5 完整方案（status 字段 + 配置驱动 audit 循环）——v0.4 大重构
- P1-13 多 spec JOIN（LedgerEntry 加 spec_id 字段的完整双向校验）——需 v0.4 评估哈希链影响
- P1-r2-2 反向校验 `missing_in_ledger`——v0.4 必做项

---

## 第 6 轮审计（v0.4 RFC 预审）

### 审计来源
4 角色独立评审（落地执行者 / 风险管控者 / 逆向挑战者 / 最终验收人），互不借鉴，独立读取 v0.4 RFC + 源码 + 历史台账后输出问题清单：
- 落地执行者（代码可落地性）：4 P0 + 12 P1 + 12 P2
- 风险管控者（隐患/合规/应急）：6 P0 + 8 P1 + 8 P2 + 12 应急缺口（完整报告见 [`docs/audit-v04-risk-controller.md`](./audit-v04-risk-controller.md)）
- 逆向挑战者（逻辑漏洞/反例）：4 P0 + 10 P1 + 9 P2 + 8 自我矛盾
- 最终验收人（目标达成/第一性/二八）：4 P0 + 8 P1 + 8 P2

### 审计摘要
- 🔴 **致命问题：10 个去重后 P0**（分代哈希 / 迁移工具 / spec_id 推断 / 接口拆分 4 个核心设计全部被多角色证伪）
- 🟠 **重大问题：约 30 个去重后 P1**
- 🟡 **优化疏漏：约 25 个去重后 P2**
- **统一共识**：v0.4 RFC 在"v0.3.1-r2 7 个 P0 残余 + v0.3 INDEX 教训"背景下，**形式上吸取教训、实质上重蹈覆辙**——核心难点（哈希链兼容）用"分代哈希 + 迁移工具"包装为更复杂的扩 schema，与 v0.3 INDEX / r1 结构完全同构。

### 多角色交叉 P0 矩阵

> **交叉规则**：≥ 3 个独立角色指向同一问题 → 升为绝对 P0

| # | 交叉问题 | 落地 | 风险 | 逆向 | 验收 | 等级 |
|---|---|---|---|---|---|---|
| 1 | **v1 哈希白名单与现有全字段哈希矛盾（迁移前置检查 100% 失败）** | ✅ | ✅ | ✅ | ✅ | 🔴 P0 |
| 2 | **迁移重算 = 合法化篡改（审计完整性崩塌）** | ✅ | ✅ | ✅ | — | 🔴 P0 |
| 3 | **spec_id 用 current_spec_id 推断 = NP0-2 同构（多 spec 全错）** | ✅ | ✅ | ✅ | ✅ | 🔴 P0 |
| 4 | **sidecar 更简替代被否决（未量化论证）** | — | 隐含 | ✅ | ✅ | 🔴 P0 |
| 5 | **接口拆分 YAGNI / 伪拆分（engine 构造签名未拆）** | ✅ | ✅ | ✅ | ✅ | 🔴 P0 |
| 6 | **status 默认值重演 NP0-1（stub 仍返回 []）** | — | 隐含 | ✅ | ✅ | 🔴 P0 |
| 7 | **未迁移用户死锁（升级后第一次写账本就坏链）** | — | ✅ | ✅ | ✅ | 🔴 P0 |
| 8 | **迁移中断无原子性保护（半成品账本全损）** | — | ✅ | ✅ | — | 🟠 P1 |
| 9 | **迁移 hash 存档实现细节缺失（§2.3 vs §4.1 冲突）** | ✅ | 隐含 | — | — | 🟠 P1 |
| 10 | **决策树定性系统性错配（模块 2 vs 模块 3）** | 隐含 | — | — | ✅ | 🟠 P1 |

### 核心事实矛盾（4 角色共识）

#### 1. 分代哈希 v1 算法与代码事实矛盾
- **事实**：`fs_backend.py:107-120` 现有 `_compute_entry_hash` 是**全字段哈希**（`json.dumps(全 dict, sort_keys=True)`，仅排除 `_hash/_prev_hash`），包含 `task_id/commit/acceptance/reason` 等字段。
- **RFC §2.3** 把 v1 算法定义为白名单 `("phase","action","timestamp","details")`——同一 entry 两种算法哈希**必然不同**。
- **后果**：迁移前置检查无论用哪个算法都失败；**现有全部 v0.3.1-r2 账本 verify 立即失败**，"v1 账本可读"承诺不成立。
- **自我矛盾**：RFC §2.2 判白名单哈希 ❌（削弱审计价值），§2.3 v1 算法又用白名单——**RFC 拒绝的方案被 RFC 自己采用**。

#### 2. 迁移重算 = 合法化篡改
- **事实**：迁移时"用当前数据重建哈希"——若历史条目被篡改（内容看起来合理），重算把篡改**永久合法化**。
- **对照**：v0.3 INDEX 教训核心正是"扩 schema 重算哈希 = 抹除证据"。RFC 未提供"迁移前后内容对照"机制，迁移日志只记"迁移前 hash"不验证其正确性。

#### 3. spec_id 推断 = NP0-2 同构
- **事实**：`current_spec_id` 是**单值状态**，切换 spec 即覆盖。RFC §3.2 把单点错误从"查询时反推"升级为"写入时填充"——**误报面反而扩大**。
- **对照**：第 5 轮 NP0-2 已明确识别此根因，RFC 未解决，仅实现位置变化。

#### 4. 接口拆分 = YAGNI + 伪拆分
- **事实**：`PhaseStateMachine.__init__:48-60` 仍接聚合 `StorageBackend`；拆 3 接口后同一 FSBackend 实例冒充 3 个接口（`file_store, ledger_store, state_store = storage, storage, storage`），运行时无约束。
- **后果**：要么伪拆分（0 价值），要么改 engine 构造签名破坏所有现有调用方与测试。

#### 5. status 默认值重演 NP0-1
- **事实**：5 条 stub `_check_*` 方法**全存在**但返回 `[]`。RFC §3.4 加 `status` 字段但未强制 stub checker 返回 `[RedLineViolation(status="stub")]`——`not_implemented` 分支永不触发，**r2 同样的形式规避/实质失败重演**。

### 更简替代（4 角色共识，RFC 未走第一性 SOP）

| RFC 设计 | 更简替代 | 判定 |
|---|---|---|
| 哈希链分代（方案 B） | **方案 C sidecar**：actor/session_id/review_ref/spec_id 写独立 `.audit.yaml`，主账本不动，侧车独立 hash 链 | ❌ RFC 未量化就否决 |
| LedgerEntry.spec_id 字段 | **不扩字段**：r2 review-audit 已用文件系统 JOIN + review_store 文件名反推（spec_id/round 是文件名而非 schema） | ❌ 重蹈覆辙 |
| actor/session_id 自动填充 | **CLI 日志 JSONL 文件**：每次 CLI 调用写一行，grep 可查，不污染账本 | ❌ 过度设计 |
| StorageBackend 拆 3 接口 | **不拆**：StorageBackend 已稳定（100 passed），0 个调用方明确需要子接口，duck typing 足够 | ❌ YAGNI |

### 决策树匹配度（角色4 验证）

| RFC 工作项 | RFC 自判 | 实际 | 判定 |
|---|---|---|---|
| 哈希链分代 | 模块 2 | 模块 3（已有逻辑在跑但坏） | ❌ |
| StorageBackend 拆分 | 模块 2 | 模块 4（方案选型） | ❌ |
| actor/session_id | 模块 2 | 模块 3 | ❌ |
| 多 spec JOIN | 模块 3 | 模块 3 | ✅ |
| 语言中性化 | 模块 5 | 模块 3（硬编码 .py 是 bug） | ❌ |
| status 字段 | 模块 5 | 模块 3（stub 沉默是 bug） | ❌ |
| 门禁持久化 | 模块 5 | 模块 5 | ✅ |

**手册遵循度：2/7 正确**（与 r1 的 50% 错配同水平）

### 二八法则验证（角色4）

```
RFC 把 50%+ 工期（分代哈希 3d + 接口拆分 2d）投在 5-10% 用户价值上
只做 status + 语言中性化 + 门禁持久化 + timestamp（4 天）→ 50% 价值
另外 6 天投入 → 另 50% 价值 + 承担 r2 同款 P0 风险
```

### v0.3 INDEX 教训落地度

- 角色2 判定：**1/4**（仅备份算真吸取）
- 角色3 判定：**0/4**（迁移重算 + 字段扩展 = [F] 质疑 4 一一对应）
- 角色4 判定：**0/4**（复杂度上升而非收敛）

### 关键决策

> **接受 4 角色独立审计共识：v0.4 RFC v0.1 整体回退到方案阶段**
>
> 1. **回退理由**：分代哈希 / 迁移工具 / spec_id 字段 / 接口拆分 4 个核心设计全部被 ≥3 角色证伪；v1 算法与代码事实矛盾是硬事实（迁移前置检查 100% 失败）
> 2. **保留范围**：门禁结果持久化（P2-14）、timestamp 时区化（P2-17）、语言中性化（P1-11，但定性改为模块 3）
> 3. **重新设计范围**：P1-10（actor/session_id）、P1-13 完整版、P1-5 完整版、P2-18 接口拆分
> 4. **下一步**：重做 v0.4-r2 方案，严格走第一性 SOP §阶段 A——尤其量化对比"方案 C sidecar + 独立 hash 链"vs"分代哈希迁移"；不扩 LedgerEntry schema；保留 r2 已落地的文件系统 JOIN

### 整改记录

| 编号 | 类别 | 处理状态 | 处理方式 |
|---|---|---|---|
| 分代哈希（方案 B） | A（方案错） | ✅ **整体回退** | 重做：sidecar 独立审计文件 vs 分代哈希，量化对比 |
| migrate-ledger | A（方案错） | ✅ **整体回退** | 不扩主 schema 则无需迁移工具 |
| LedgerEntry 加 5 字段 | A（方案错） | ✅ **整体回退** | 不扩字段，用 review_store 文件名反推 + sidecar |
| StorageBackend 拆 3 接口 | A（方案错） | ✅ **整体回退** | 推迟（YAGNI），0 调用方需要 |
| 门禁结果持久化 | C（优化疏漏） | ✅ 保留 | 继续做（注意 stdout/stderr 脱敏） |
| timestamp 时区化 | C（优化疏漏） | ✅ 保留 | 继续做（UTC 存储） |
| 语言中性化 | B（实现错） | ✅ 保留但改定性 | 模块 3 修补；注意 test_patterns 子串误判 |
| status 字段 | B（实现错） | ✅ 保留但补强 | 强制 stub checker 返回 status="stub"；加枚举约束 |

### 残余风险清单（新增）

10. **P0 残余**：v0.4 RFC 未实施，无新风险增量。
11. **第一性残余**：若 v0.4-r2 仍走"扩 schema"老路，会第三次被回退。**补偿**：重做前先完成 first-principles-sop.md §阶段 A 全部 6 步（含"更简替代"量化对比表）。

### 本轮修改潜在副作用评估

无（仅作审计归档，未实施代码修改）。

---

## v0.3.2 实施结果（轻量修补）

> **决策**：接受第 6 轮审计结论——v0.4 RFC 整体回退；**先落地审计确认保留的 4 项低风险修补（v0.3.2），v0.4 暂停等真正需求**。

| 修补 | 落地内容 | 验证 |
|---|---|---|
| **P2-14** | 门禁结果持久化：`gate` 命令写账本,`LedgerEntry.gate_result` 可选字段 + stdout/stderr 脱敏 | ✅ 测试锁定（test_p2_14 ×3） |
| **P2-17** | timestamp 时区化：`datetime.now(timezone.utc)`,旧 naive 读取兼容 | ✅ 测试锁定（test_p2_17 ×2） |
| **P1-11** | 语言中性化：`tooling.languages` 配置驱动,词边界正则防误判 | ✅ 测试锁定（test_p1_11 ×3） |
| **P1-5 补强** | `ViolationStatus` 枚举(active/mvp_skip/stub/not_implemented)+ audit() 结构化 status | ✅ 测试锁定（test_p1_5 ×3） |

**改动文件**：
- `src/devflow/model/ledger.py`（P2-17 + P2-14 字段）
- `src/devflow/cli.py`（gate 持久化 + _sanitize_gate_result + audit by_status）
- `src/devflow/engine/redline_auditor.py`（ViolationStatus 枚举 + 语言中性化）
- `config/sop.default.yaml`（tooling.languages）
- `tests/test_v032.py`（11 条新测试）
- `docs/CHANGELOG.md`（[v0.3.2] 段）

**全量回归**：**111 passed / 1 skipped**（v0.3.1-r2 基线 100 + 新 11）

**哈希链安全验证**：
- `verify_ledger` 读原始 YAML dict 直接验证（不经过 pydantic 模型）→ 新增 Optional 字段仅影响新条目哈希,旧链验证不变
- `test_p2_14_hash_chain_still_valid_with_gate_result` 锁定该行为

**v0.4 暂停项（等真正需求）**：
- 账本 schema 演进（actor/session_id/review_ref/spec_id）
- StorageBackend 接口拆分（YAGNI）
- 多 spec 双向 JOIN 完整版（NP0-2 需 v0.4 从根解决）

---

## v0.3.3 实施结果（思维模型落地）

> **决策**：用户需求——"项目吸收思维模型,应用到实际工作"。经第一性分析：**"强制 agent 用思维"是伪需求**(agent 可绕过一切检查,且引发形式主义),正确形态是**把思维变成引擎的默认规则**(字段 + 检查),靠审计留痕而非拦截。

### 落地内容

| 思维 | 字段 | 检查规则 | 严格度 |
|---|---|---|---|
| 第一性原理 | `Spec.assumptions` | `thinking_first_principles` | MINOR |
| 逆向思维 | `Spec.premortem` | `thinking_premortem` | MINOR |
| 损益思维 | `Spec.tradeoff` | `thinking_tradeoff_*` | MINOR |
| 奥卡姆剃刀 | (用 options) | `thinking_occam` | MINOR |
| 假设思维 | `Spec.assumptions` | `thinking_hypothesis` | MINOR |
| 二八法则 | `Task.priority` | `thinking_pareto` | MINOR |
| 能力圈 | `Task.owner_skill` | `thinking_capability_circle` | MINOR |
| 反馈思维 | `Task.acceptance` | `thinking_feedback_loop` | MINOR |
| 冗余思维 | `Plan.buffer` | `thinking_redundancy` | MINOR |

**设计原则**：
- 全部字段 Optional(宽松默认: 有值才检查,旧 Spec/Plan 不受影响)
- 全部 severity=MINOR(提示不阻断推进——灰度思维: 可行解优先)
- `thinking.enabled: false` 可完全关闭(兼容旧 SOP)
- 不碰哈希链 / 账本 schema / 状态机阶段

**改动文件**：
- `src/devflow/model/spec.py`（assumptions/premortem/tradeoff）
- `src/devflow/model/task.py`（priority/owner_skill）
- `src/devflow/model/plan.py`（buffer + 修复 Optional 导入）
- `src/devflow/policy/loader.py`（ThinkingConfig）
- `src/devflow/engine/review_engine.py`（_run_thinking_checks 9 条）
- `config/sop.default.yaml`（thinking 段）
- `tests/test_thinking_rules.py`（9 条新测试）
- `docs/CHANGELOG.md`（[v0.3.3] 段）
- `docs/thinking-framework-mapping.md`（24 思维映射总表）

**全量回归**：**121 passed**（v0.3.2 基线 111 + 新 10）

**审计视角的自我评估**（对照本台账反复出现的教训）：
- ✅ 未扩账本 schema（无哈希链风险）
- ✅ 未新增状态机阶段（8 阶段不变）
- ✅ 未引入新依赖
- ✅ 宽松默认,旧 Spec/Plan 零破坏
- ✅ 可关闭(`thinking.enabled: false`)
- ⚠️ 若未来有人把思维检查改 blocking,需重走审计（本台账第 5/6 轮教训: 扩 schema/改语义前先过第一性 SOP）

---
