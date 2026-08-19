## 逆向挑战者 · 审计发现

### 🔴 致命漏洞(P0)- 修复会直接破坏现有功能

- **[P0-V31-1] review_engine 的 `_escalate` 与 `_stagnation_escalate` 路径写账本时未填入 `review_id` 字段,P1-13 修复会留下**未关联的 ESCALATE 条目**,使 `review_audit` 命令永远报告"账本有 ESCALATE 但找不到 ReviewReport",触发误报。** | 反例:用户进入 R6(超 MAX_REVIEW_ROUNDS=5),走 `_escalate()` → `append_ledger(...action=ESCALATE,details=...)` 不传 `review_id`;P1-13 实施后,`review_audit` 扫所有 ledger entries,任何 `ESCALATE`/`FIX`/`REVIEW` 条目都会被检查 `review_id` 字段——但 `_escalate`/`_stagnation_escalate`/`fix()` 路径都漏填。方案仅修复 `review()` 主路径的 3 处 append_ledger,实际 review_engine.py 有 **3 处 + 2 处共 5 处** append_ledger(line 129、244、618、683,以及 fix 的 244)。** | 触发概率:100%(任何用户跑超 5 轮评审或修复必触发)**

- **[P0-V31-2] P1-13 修复声称"新字段不参与哈希链",但 `LedgerEntry` 用 pydantic BaseModel,默认 `model_dump(mode="json")` 的字段顺序是定义顺序;旧账本写入用的是 `phase/action/timestamp/details` 顺序(原 6 字段),而新代码写账本后 dump 会变成 8 字段顺序。即使不参与 `_hash` 计算,**字段顺序变化会导致 YAML 输出不同**,若 verify_ledger 是基于整条 YAML 序列化字符串做哈希(常见做法),哈希链断裂。** | 反例:旧账本条目 dump 为 `phase: 0\naction: triage\ntimestamp: ...\ndetails: ...`;新代码 dump 同样一条会变成 `phase: 0\naction: triage\ntimestamp: ...\ndetails: ...\nreview_id: null\nactor: null`(pydantic 默认行为,所有字段都会序列化)。若 verify_ledger 用 `yaml.dump(entry)` 计算哈希,旧账本条目的序列化字符串与新写入的不一致 → 全部 `verify_ledger` 失败。** | 触发概率:中-高(取决于 verify_ledger 实现细节,但方案未验证这一点)

- **[P0-V31-3] P1-9 修复引入 pytest-cov 依赖但 `sop.default.yaml` 中 `tests_pass.command` 与 `ci_green.command` 都会触发 pytest 运行,**用户跑 `devflow next` 走 Stage5 → Stage6 会执行两次 pytest**:`_gate_verify()` 跑 `tests_pass`(pytest),`_gate_review()` 跑 `ci_green`(pytest --cov)。Stage5+Stage6 都执行会重复运行整个测试套件,CI 时间翻倍,且 pytest 的临时文件/缓存冲突。** | 反例:用户有 200 个测试,Stage5 跑完 pytest(60 秒),进 Stage6 又跑 pytest --cov(80 秒),总耗时 140 秒,且第二次 pytest --cov 会重新收集、重新加载所有 fixtures、生成 `.coverage` 文件覆盖第一次的。** | 触发概率:100%(Stage5/Stage6 顺序推进必然触发)

- **[P0-V31-4] P1-2 fail-closed 修复后,`commit_task()` 路径上仍走 `_check_exit_gate(6) → _gate_review()`,且 `commit_task` 还**显式要求** `gate_runner is not None or git is None` 报错(line 384-385),但 fail-closed 改动后 `gate_runner is None` 会让 Stage6 门禁 fail。这意味着:**任何未注入 GateRunner 的单元测试 / Mock 环境,跑 `commit_task` 都会失败**(原本是 ok=True 跳过)。** | 反例:测试套件用 `PhaseStateMachine(storage, config)` 不传 gate_runner,跑 `commit_task()` 期望验证状态机逻辑——P1-2 之前能通过(P1-3 阶段检查的 gate_runner 仅在 commit 时显式要求,但 commit 路径外的 _gate_review 之前是 ok=True 跳过),现在直接 fail。** | 触发概率:中-高(取决于现有测试套件如何 mock)

---

### 🟠 重大逻辑漏洞(P1)- 修复在边界条件下失效

- **[P1-V31-1] P1-5 修复后,`audit()` 对空实现的 stub 红线返回 `RedLineViolation(skip=True, status="stub")`,但 `total_violations` 统计包含所有 violations(含 skip=True),方案说"新增 real_violations 字段"却**没有修改任何调用方**。现有 `cli.py` / 其他审计消费者如果基于 `len(violations)` 判断违规数,会误报"5 个新违规"。** | 反例:用户跑 `devflow audit` 看到 5 条 stub 红线 → 数 "5 violations" → 误以为是"5 个真实违规,需要修复"。但方案说 `real_violations` 是新增字段,意味着现有消费者都没改。** | 失效条件:任何外部脚本/UI/dashboard 读取 violations 列表长度

- **[P1-V31-2] P1-5 修复中"检查函数存在但实现为空(返回 [])→ 标记 stub"——但**当前代码里 stub 函数是 `_check_skip_phase / _check_doc_drift / _check_silent_legacy / _check_no_contract / _check_human_step_auto` 5 条**,都返回 `[]`。修复后 `audit()` 会先 `getattr` 找到这 5 个 checker,然后调用 → 返回 `[]` → 标记 stub。但 `_check_skip_phase` 等的注释说"由状态机/门禁保障",**这些保障是否真的有效?如果用户用 P1-2 fail-closed 后这些保障失效,stub 红线就变成了"无人保障"的盲区**。** | 反例:`_check_no_contract` 注释"由状态机 Stage3 门禁保障",但 `state_machine._gate_contract` 只检查 task.contract 是否存在,**不检查 contract 内容是否与 spec 描述匹配**(Spec 改了字段,Contract 没改也不会被发现)。stub 标"由门禁保障"实际上是"形式保障",非"语义保障"。** | 失效条件:Spec 字段变化后 Contract 未同步更新

- **[P1-V31-3] P1-9 `_extract_coverage` 正则 `r"TOTAL\s+\d+\s+\d+\s+(\d+)%"` **假设 pytest-cov 输出格式固定**,但:**(a) Windows 下路径分隔符不同可能影响输出;(b) pytest-cov 5.x 之后新增 `No data to report.`(空 src 时输出);(c) pytest-cov 9.x 改用 `coverage` 7.x 默认输出,可能去掉 `TOTAL` 行或换格式;(d) coverage 7.0+ 默认启用 `precision=1` 输出小数(70.5%),正则只匹配整数。** | 反例:用户项目 `src/` 目录不存在或为空 → pytest-cov 输出 `No data to report.`,无 TOTAL → 正则不匹配 → 返回 None → `coverage` 字段为 None → 后续 `f"覆盖率 {coverage}%"` 抛 TypeError(str + None)。** | 失效条件:src 目录为空 / pytest-cov ≥ 9 / coverage ≥ 7

- **[P1-V31-4] P1-13 修复扩展 `LedgerEntry` 但 `sop.default.yaml` 的 `red_lines` 列表中 `circular_dep` 用 `mvp_skip: true` 嵌套格式,**P1-5 修复的 `audit()` 重构后,遍历 `red_lines` 时如果 red_line 配置项改了(用户从字符串变成 dict 或反之),行为差异巨大**——方案未说明此兼容场景。 | 反例:用户复制 `sop.default.yaml`,看到 `circular_dep: mvp_skip: true` 写成 dict,但其他红线写成 string;P1-5 后 `getattr(self, f"_check_{red_line.name}", None)` 对 `circular_dep` 走 mvp_skip 分支(标 not_implemented? 不,标 mvp_skip),其他走 checker 路径,**新旧 sop.yaml 的 audit 结果字段可能不一致**。 | 失效条件:不同 sop.yaml 版本混用

- **[P1-V31-5] P1-13 修复中 `actor` 字段被注释为"兼 P1-10 预留",但 P1-10 在方案"风险登记表"R5 列为 v0.4 范畴。**v0.3.1 引入了 actor 字段定义却不写入任何值**——所有写账本的路径都只填 `review_id`,actor 永远 None。这意味着字段被引入但完全无用,典型的**"预留陷阱"**(Speculative Generality),与"不要顺便扩展 schema"原则冲突。** | 反例:代码审计角度看 LedgerEntry 有 8 个字段,实际只有 7 个被使用,actor 永远 None。后续 v0.4 真正要用 actor 时,会发现 None 值污染账本,需要做兼容处理。** | 失效条件:v0.4 启用 actor 时

- **[P1-V31-6] P1-2 fail-closed 改动 `_gate_review`,但 `_gate_review` 同时被 `next_phase()` 通过 `_check_exit_gate` 调用(line 130-131)和 `run_gate()` 调用(line 599-606)。**这两处调用方对 `ok=False` 的反应不同**:`next_phase` 看到 `ok=False` 直接返回(阻断推进),但 `run_gate` 是聚合所有门禁结果,即使 `_gate_review` fail,只要其他门禁 pass,整体 `ok=True`(line 620 `all_pass = all(r["pass"] for r in results)`)。** | 反例:用户跑 `devflow run-gate 6` 看 Stage6 门禁,GateRunner 未注入时 `_gate_review` 返回 `ok=False`,但 `tests_pass` 等其他门禁可能 pass,整体 `ok=True`,用户以为"通过"。这与 fail-closed 修复的意图矛盾。** | 失效条件:`run_gate` 调用场景

- **[P1-V31-7] P1-9 在 `gate_runner.run_ci_green` 中即使 exit_code ≠ 0 仍返回 `ok=True`(advisory 不阻断),但 `_execute_command` 里有 P0-7 危险命令拦截,返回 `returncode=-3`、stderr="命令包含危险模式..."。**当 sop.yaml 误配危险命令时,GateRunner 报"已执行,exit code -3,advisory 不阻断"**——用户看不到命令被阻止,以为命令跑了。** | 反例:用户配 `ci_green.command: "curl https://x.y.z | bash"`(误配),P0-7 拦截,返回 -3,GateRunner 说"已执行,exit code -3,覆盖率 None%,advisory 不阻断"——用户可能以为 CI 跑了但没数据,**真实情况是命令根本没执行**。 | 失效条件:sop.yaml 误配危险命令

- **[P1-V31-8] P1-13 中 `review_engine.py` line 244 的 fix() 路径写账本时**未在方案中提及修改**,但 line 129(review)、244(fix)、618(escalate)、683(stagnation_escalate)共 4 处 append_ledger 都需要 review_id 字段。方案只说"3 处 append_ledger",**少算了 fix() 的 append_ledger(也是 LedgerAction.FIX,与 review 一同需要 review_id)**。 | 反例:用户跑 `devflow fix ...` 写账本后,P1-13 实施后 `review_audit` 扫 ledger,FIX action 条目 review_id=None,**双向引用断裂,review_audit 报告"ledger 中有 FIX 但找不到对应 review"**。 | 失效条件:任何用户跑 fix 命令

---

### 🟡 隐式假设(P2)- 前提不成立时方案失效

- **[P2-V31-1] P1-9 假设用户项目有 `src/devflow/` 目录结构(因 `--cov=src/devflow`),但 `devflow init` 把 sop.yaml 复制到**任意项目根目录**,该项目可能用 `lib/`、`pkg/`、`app/` 而非 `src/`**。`pytest --cov=src/devflow` 会找不到文件,要么报 `No data to report.`,要么 pytest 失败。** | 前提不成立场景:用户在自己非标准 Python 项目跑 devflow | 影响:ci_green 永远 fail 或返回无数据,但 advisory 不阻断——用户得不到有效反馈信号

- **[P2-V31-2] P1-5 修复假设 `red_lines` 中每条规则都有对应的 `_check_<name>` 方法(或 mvp_skip),但 `config.red_lines` 配置可能**新增规则名而忘了实现 checker**(用户加新红线,审计报 not_implemented)**。这种"配置驱动"的方式把"实现缺失"的信号外推到配置层,用户配置改了实现没改就被发现是好事,但**方案没有规定"哪些规则必须有实现"**——如果用户故意加占位规则想等 v0.4 实现,他会得到一堆 not_implemented 误报。 | 前提不成立场景:用户为未来规则预留配置项 | 影响:audit 输出噪声,真违规被淹没

- **[P2-V31-3] P1-13 修复假设"v0.2.1 旧账本无 review_id 字段,新代码兼容"——但 v0.2.1 的账本可能**根本没记录 review**(旧版 ledger action 不含 REVIEW)。新代码读旧账本时 review_id 永远 None,但 P1-13 的 `review_audit` 命令扫到的旧条目会**全部显示 review_id 缺失**,产生"大量误报"。** | 前提不成立场景:用户从 v0.2.1 直接升 v0.3.1(跳 v0.3.0) | 影响:review_audit 首次跑全红,用户以为账本坏了

- **[P2-V31-4] P1-2 修复假设"GateRunner 注入/不注入是显式选择",但**实际注入路径复杂**:PhaseStateMachine.__init__ 接受 `gate_runner: Optional[GateRunner] = None`,cli.py 装配时可能因为 `GateRunner` 构造失败(比如 cwd 不存在、sop.yaml 解析失败)而**静默传 None**(异常吞掉)。fail-closed 后,这种"构造失败被静默降级"的情况会被阻断,用户看到 fail-closed 错误但**根本原因是 GateRunner 构造失败**,定位困难。 | 前提不成立场景:GateRunner 构造异常 | 影响:错误信息误导

- **[P2-V31-5] P1-9 修复假设 `proxy_strip` 配置生效,但 `gate_runner._execute_command` 在 `proxy_strip` 启用时**只 strip 4 个 HTTP_PROXY/HTTPS_PROXY 变量**,**不 strip NO_PROXY/all_proxy/.*_proxy 等其他代理变量**。pytest-cov 远程插件或 coverage 服务可能仍通过其他代理连接。** | 前提不成立场景:CI 环境配置了非标准代理变量(Jenkins HTTPS_PROXY_AUTH, GitLab CI_NO_PROXY 等) | 影响:pytest-cov 远程插件尝试连接失败,coverage 数据异常

- **[P2-V31-6] P1-13 修复假设 `ReviewReport.id` 在 review_store 中稳定存在,但 `review_engine.review()` 中 `report = ReviewReport(id=f"r{round}",...)` ——**id 是轮次派生的,round 重复时会覆写**(虽然有 P1-14 禁止覆写,但禁止的是"同 id 多次 write")。如果用户并发跑两次 review(round 都是 N+1),会产生同 id 报告竞态。P1-13 双向引用依赖 review_id 稳定,但并发场景下不稳定。** | 前提不成立场景:CI 多 worker 并发 review | 影响:ledger 中的 review_id 可能指向已覆写的报告

- **[P2-V31-7] P1-5 修复假设 `RedLineViolation` 增加 `status` 字段不影响现有 `to_dict()` 调用方(line 22-23)。`to_dict()` 没改,返回 `{"rule", "message", "skip"}`,**新字段 status 不会出现在 dict 里**。**JSON 序列化输出/磁盘写入/网络传输 都会丢失 status 信息**——CLI 输出、CI 报告、API 响应都看不到 status 区分。** | 前提不成立场景:CLI 输出或 API 返回 violations dict | 影响:stub vs real 区分在内存对象存在,在序列化数据中丢失

---

### 自我矛盾清单

1. **"不破坏兼容" vs "新增 status 字段"**:方案总览声称"✅ 向后兼容 v0.2.1、v0.3.0",但 P1-5 给 `RedLineViolation` 加 `status` 字段——任何外部代码实例化 RedLineViolation 时位置参数 `rule, message, skip=True` 不变,但 **新构造的 violations 在内存中多了 status 属性**。如果外部代码做 `assert "status" in violation.__dict__` 会通过(向后兼容);但**做 `assert len(violation.to_dict().keys()) == 3` 会失败**(之前 3 个 key,现在 status 在内存但不进 dict)。这是"半兼容":属性层兼容、序列化层兼容、字段层不兼容。

2. **"advisory 模式不阻断" vs "pytest --cov 失败时返回 coverage"**:P1-9 在 advisory 模式下即使 pytest 失败也返回 `ok=True`,但 coverage 字段保留真实值。**用户可能根据 coverage 字段做阻断决策**(没意识到是 advisory),与"advisory 不阻断"的设计意图矛盾。

3. **"review_id 不参与哈希链" vs "账本 verify_ledger 兼容旧账本"**:方案反复强调"哈希兼容"、"账本兼容",但 LedgerEntry 是 pydantic BaseModel,**新增字段会被 pydantic 自动加入 `model_dump()`**。若 verify_ledger 用 `entry.model_dump_json()` 算哈希,旧账本条目重写后哈希就变了——"兼容"只是字面上的,不验证就声称兼容是过度乐观。

4. **"不要扩展 schema" vs "加 ci_green.coverage_threshold + review_id/actor 字段"**:反思维警告明确写"不要扩展 sop.yaml schema 加新字段(除 ci_green.coverage_threshold)",但 P1-13 给 LedgerEntry 加了 `review_id` 和 `actor` 两个字段。`LedgerEntry` 不是 sop.yaml,是 ledger schema,但**精神上是"加新字段"被禁止**——方案自我违反。

5. **"新增 fail-closed" vs "迁移建议在 devflow init 输出中提示"**:P1-2 把"GateRunner 缺失自动通过"行为变成 fail-closed,但**只说"在 devflow init 输出中提示"**,没说**为已经 fail-closed 阻断的现有用户**(已经 devflow init 完、正在用 v0.2.1/0.3.0)提供迁移工具。这些用户跑 `devflow next` 突然 fail-closed,没有任何 in-place 修复路径。

6. **"总工时 0.5+0.5+1+1 = 3 天" vs 实际文件变更清单 12 项**:方案总览说"~200 行(含测试)",但文件变更清单显示 12 个文件、约 300 行,且包含 CLI 新命令 `review-audit`(+30 行)、依赖新增 pytest-cov、CHANGELOG/audit-ledger 文档更新等——**纯 P1 修复工作可能 3 天,但加上文档、测试、CLI、依赖协调,3 天偏紧**。低估工时会导致 Day 3 压缩审计时间,**"4 角色独立审计"流于形式**。

7. **"v0.3 INDEX 失败教训:不要引入新接口(留 v0.4)" vs P1-13 新增 `review-audit` CLI 命令**:v0.3 rejected-design 教训是"避免引入新存储接口",v0.3.1 反思维警告说"不要顺便重构接口",但 P1-13 **新增了完整的 CLI 命令、review_engine 5 处 ledger 写入点变更**(虽然不新接口,但是新工作流)**——属于"借修补之名加新功能"**。

8. **"P1-2 fail-closed 后所有用户都被阻断" vs "R1 风险等级🟡中"**:方案同时把 fail-closed 列为必须做(避免安全漏洞)又列为中等风险——这种**"必须做但风险中等"**的定位矛盾,意味着要么低估影响(应该是高风险),要么高估修复必要性(其实 fail-open 可接受)。

9. **P1-5 声称"audit 输出加 status 摘要"但实际方案没改 CLI 输出层**:方案 § 三 工作项 #2 说"🔧 输出增强:`devflow audit` 输出加'检测覆盖度'摘要",但**修复方案只给 audit() 方法和 RedLineViolation 字段变更,没给 cli.py 的实际输出改造代码**。这是"承诺做但不写代码"的典型过度承诺。

---

### 隐性历史回放检查(v0.3 INDEX 教训)

v0.3 INDEX 方案被第一性回退,理由:**"重组路径破坏账本哈希链"**。

v0.3.1 是否重蹈覆辙?

- **LedgerEntry 字段扩展(P1-13)** —— 直接涉及账本 schema,扩展字段虽然说不参与哈希,但 pydantic 序列化顺序/字段数量变化会让 `entry.model_dump()` 的输出不同。**若 verify_ledger 用序列化字符串哈希,等同于 v0.3 的"破坏哈希链"问题**。**这是 v0.3 教训的直接重演**。

- **新增 CLI 命令 `review-audit`(P1-13)** —— 涉及新接口(命令接口),**等同于 v0.3 的"新增 archive_spec/query 等 ABC 方法"**。方案反思维说"不要顺便重构接口"被实际打破。

- **`audit()` 重构(P1-5)** —— 把"硬编码 5 条 stub"改成"配置驱动循环"是接口行为变更,**等于 v0.3 的"软归档 vs 物理归档"路径变更**,用户配置改了实现没改就出错,行为不可预测。

---

### 总计

- **致命漏洞(P0)**:**4 条**
- **重大漏洞(P1)**:**8 条**
- **隐式假设(P2)**:**7 条**
- **自我矛盾**:**9 条**

### 重点提示(给后续审计者)

1. P1-13 的"3 处 append_ledger"是**假数据,实际是 5 处**(漏 fix + 2 个 escalate 路径)
2. P1-2 fail-closed + P1-9 pytest 双跑 + P1-3 commit_task 路径 = **Stage6 推进会被双重失败**(run_gate 聚合与 _check_exit_gate 直接调用 行为不一致)
3. P1-5 stub 红线 + P1-13 ledger 字段扩展 = **审计输出噪声翻倍**(5 条 stub + 大量 review_id=None 的 ledger 条目)
4. v0.3 INDEX 教训是"扩展 schema 破坏哈希链",P1-13 LedgerEntry 扩展直接重演,**未做哈希兼容性验证**

### 关键建议方向(供主代理决策,非解决方案)

- **必须做的验证**(实施前):跑一次 `verify_ledger` on 旧账本,确认 LedgerEntry 新字段不影响哈希
- **必须做的验证**:`review_engine` 所有 append_ledger 调用点统一加 `review_id`,不能漏 fix/escalate 路径
- **必须做的验证**:P1-2 fail-closed 后跑现有 test 套件,确认是否大量 fail
- **必须做的验证**:P1-9 pytest --cov 在空 src、Windows、pytest-cov ≥ 9 下的输出兼容性
- **必须做的降级**:如果"4 角色独立审计"发现新 P0,方案 R5 说"留 v0.3.2",但**审计应在实施前完成**——现状是"实施后才审计",违背 4 角色并行审计原则
