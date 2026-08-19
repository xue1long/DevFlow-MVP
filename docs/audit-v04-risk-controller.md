# 风险管控者 · v0.4 RFC 审计发现

> **审计对象**:`docs/v0.4-rfc.md`(572 行) + 6 份代码事实 + 第 5 轮(r1/r2)+ v0.3-rejected-design
> **审计视角**:隐患 / 合规 / 损失 / 应急预案(独立审计,未参考其他角色输出)
> **审计日期**:2026-08-19

---

## 🔴 致命隐患(P0)

### P0-RC-01:分代哈希"白名单"v2 与"全字段"v1 不共存,迁移死锁
- **具体风险**:RFC §2.3 `_compute_entry_hash` 在 `ledger_version="1.0"` 时只哈希 `(phase, action, timestamp, details)` 四个字段;在 `ledger_version="2.0"` 时哈希 8 个字段。但 `fs_backend.py:107-120` 现有实现是**全字段哈希**(任何字段改动都会破链)。RFC §2.4 声称"v1 账本可读,verify_ledger 自动检测 ledger_version 用旧算法验证"——这要求 v0.4 代码内置两套算法。**致命矛盾**:用户当前账本不存在 `ledger_version` 字段 → RFC §2.3 的 `_pre_migrate_check` 用什么版本号识别 v1?如果 fallback 到"无字段 → v1",则**任何 v1 账本永远要 migrate 才能用**;但 RFC 又说"v1 账本不 migrate 也能用 v0.4 代码读"(§2.4 "✅ 旧账本(v1)可读")——两个承诺互斥。
- **影响范围**:所有 v0.3.1-r2 用户升级 v0.4 时必触发
- **最坏损失**:用户升级即 verify 失败 → 无法用 v0.4 → 账本实质不可用,需要重建
- **RFC 章节**:§2.3 / §2.4 / §4.1

### P0-RC-02:迁移工具重算哈希链会**掩盖篡改**
- **具体风险**:RFC §2.3 `migrate-ledger` 步骤 3 "用 v2 哈希算法重算整条链(从第一条开始)";§4.2 测试用例 "迁移前 verify 失败:拒绝迁移,提示先修复"——这看似兜底,但**默认流程是 verify 通过才迁移**。问题在于:若账本在 verify 通过但哈希链已被攻击者精心篡改(构造出内部自洽但与历史不同的链),`migrate-ledger` 会**把篡改后的内容视为权威**,并用新算法重算 → 篡改被"洗白"为 v2 账本的合法状态。**审计承诺彻底瓦解**:任何 migrate 操作本质上都是"以当前快照为权威重哈希",攻击者只要在迁移前完成篡改就过关。
- **影响范围**:所有 v0.3.1-r2 用户
- **最坏损失**:审计完整性被永久破坏,账本事后无法证明任何条目未被篡改
- **RFC 章节**:§2.3(迁移步骤 3) / §2.4(迁移后不可回退)

### P0-RC-03:`spec_id` 从 `current_spec_id` 推断会**张冠李戴**
- **具体风险**:RFC §2.3 迁移步骤 2 "对每条 entry:补 spec_id(从 ledger 顶层 current_spec_id 推断,或留空)"。第 5 轮 NP0-2 已明确指出:`LedgerEntry` 无 `spec_id` 字段时,用 ledger 顶层 `current_spec_id` 关联历史 review 条目,**所有历史 review 条目都会被错误归到当前 spec**——这是已被审计认定的"系统性误报"根因。RFC v0.4 把同一错误方法塞进迁移工具,**会污染整条历史账本的 spec 归属**,迁移后 review-audit 双向 JOIN 的反向校验(P1-r2-2)`missing_in_ledger` 报告将失去意义。
- **影响范围**:迁移后所有 review-audit 报告
- **最坏损失**:多 spec 工作流的审计反向校验全部失效,审计盲点永久化
- **RFC 章节**:§2.3(迁移步骤 2) / §3.2(多 spec JOIN) / §4.2(多 spec 迁移测试)

### P0-RC-04:迁移中断(断电/崩溃)无原子性保护 → 账本全损
- **具体风险**:RFC §4 迁移策略未规定迁移操作的原子性。`_atomic_write_yaml` 保护单次 YAML 写入,但**整条链重写是多次读写过程**(读旧账本 → 重算 N 条 hash → 写新账本)。若第 1345 条重算完成时崩溃:
  - `progress.yaml.bak-v1` 已写入(备份存在)→ 旧账本可恢复
  - 但 `progress.yaml` 可能处于"半新半旧"状态(YAML 序列化的原子 rename 是单次操作,若未到 rename 阶段就崩,旧文件原封不动;若到 rename 阶段后崩,新文件可能写入不完整)
  - **更糟**:用户备份在 `progress.yaml.bak-v1`,但**正在迁移中的临时 `.tmp_xxx.yaml` 文件残留**在 workspace 根目录,与正常账本混淆
- RFC §4.3 回滚策略仅说"恢复 progress.yaml.bak-v1",但未说明**崩溃时哪些状态可恢复、哪些不可恢复**。
- **影响范围**:任何中途中断的迁移(断电、kill -9、磁盘满)
- **最坏损失**:迁移到一半 → progress.yaml 是损坏的 YAML → 用户两条账本都不可用 → 历史审计数据丢失
- **RFC 章节**:§4.1 / §4.3(无中断恢复条款)

### P0-RC-05:`progress.yaml.bak-v1` 备份文件本身不含哈希,误删/损坏后无法自检
- **具体风险**:RFC §4.1 "备份 progress.yaml.bak-v1"。备份文件是 v1 格式账本的纯拷贝,**不含 v2 哈希链**。问题:
  - 用户误删 `progress.yaml.bak-v1` → 无原始 v1 账本可恢复
  - 用户在迁移完成后**清理临时文件**时,可能把 `progress.yaml.bak-v1` 当临时文件删掉(RFC 未说"备份永久保留")
  - 备份文件本身没有被哈希链保护——**用户可以悄悄修改 .bak-v1 而不被察觉**(备份本应作为不可变锚点)
- **影响范围**:所有用户的回滚路径
- **最坏损失**:发现 v2 账本有错时,回滚路径已断,无可信原始账本
- **RFC 章节**:§4.1 / §4.3(无备份完整性条款)

### P0-RC-06:未迁移用户直接用 v0.4 devflow 命令 → 全账本 verify 失败
- **具体风险**:RFC §2.4 声称"旧账本 v1 可读",但 §2.3 迁移流程要求用户**主动跑 `devflow migrate-ledger`**。若 v0.3.1-r2 用户升级 v0.4 后**忘了跑 migrate**:
  - 直接跑 `devflow next` 等命令 → `append_ledger` 用**v0.4 代码的 LedgerEntry schema**(新增 spec_id/actor/session_id/review_ref/gate_result 等字段)→ 写入时 `_compute_entry_hash` 按 `ledger_version` 选算法——但账本无 ledger_version 字段 → **用 v1 算法算?还是 v2 算法算?RFC 未规定 fallback**
  - 若 fallback 到 v1:新字段不计入 hash,新字段可被篡改(方案 A 已被 RFC §2.2 否决)
  - 若 fallback 到 v2:第一个新条目 hash 改变 → **整条链从该处开始全断**(这正是第 5 轮 P0-1 的核心问题,被 RFC 重新引入!)
- RFC §4.1 迁移流程假设用户会**主动配合**,但 RFC 未规定"未迁移用户如何被阻断"。
- **影响范围**:所有忘记/忽略迁移的用户
- **最坏损失**:升级即账本验证失败,所有 devflow 命令报错,用户无法继续使用
- **RFC 章节**:§2.3 / §2.4 / §4.1

---

## 🟠 重大隐患(P1)

### P1-RC-01:`session_id` 每次 CLI 进程生成,违背"一次命令链"的语义
- **具体风险**:RFC §3.1 "session_id(每次 CLI 进程启动生成 UUID)"。问题:
  - `devflow next` 是一个 CLI 调用,但**门禁 + 账本写入 + 状态转换都在同一进程**——session_id 会一致(✅ 这一层 OK)
  - 但**真实工作流**是 `devflow next` → 失败 → 用户 `devflow audit` → 修复 → `devflow next` 再次尝试。**每一次 `devflow` 子命令都是新 session**——session_id 失去"会话"语义。
  - 更糟:跨进程协作(agent 调度、CI 多步)场景下,session_id 完全无法串联跨进程操作
- **触发条件**:任何超过单次 CLI 调用的复杂工作流
- **影响范围**:P1-10 actor/session_id 的全部审计追溯价值
- **RFC 章节**:§3.1

### P1-RC-02:门禁结果 stdout/stderr 尾部 500 字符持久化 → 敏感信息泄露
- **具体风险**:RFC §3.6 `gate_result` 字段把 `stdout[-500:]` 和 `stderr[-500:]` 写入账本。问题:
  - **密码泄露**:CI 配置含 `password=xxx` 的回显
  - **密钥泄露**:测试中打印 API token、私钥
  - **审计日志污染**:`git log` 输出可能含 commit message 中的敏感信息
  - **GDPR/合规违规**:个人邮箱、电话号、IP 出现在测试输出
  - 账本一旦写入即永久哈希链固化,**敏感数据无法擦除**
- **触发条件**:任何 `pytest -v` 失败输出、CI runner 调试信息、shell 命令回显
- **影响范围**:所有用户的账本合规审计
- **RFC 章节**:§3.6

### P1-RC-03:迁移前 verify 失败 → "拒绝迁移" 但无修复/回滚指南
- **具体风险**:RFC §2.3 `_pre_migrate_check` "旧账本 verify_ledger 是否通过(不通过不迁移)";§4.2 测试 "迁移前 verify 失败:拒绝迁移,提示先修复"。问题:
  - "先修复"——**修复什么?** 哈希链断了能怎么修?RFC 未提供修复工具
  - 历史上 P0-3 整改后,哈希链断裂 = 必有篡改,**不可逆**
  - 用户陷入死锁:不修不能用 v0.4,修了又不知道怎么修
- **触发条件**:账本存在任何篡改/损坏/历史 bug 导致的 hash 不匹配
- **影响范围**:历史异常账本的所有用户
- **RFC 章节**:§2.3 / §4.2

### P1-RC-04:`StorageBackend` 拆 3 接口但旧调用方用具体类型注入
- **具体风险**:RFC §3.5 拆为 `FileStore` / `LedgerStore` / `StateStore` 三个接口,保留 `StorageBackend` 聚合接口(§3.5 "兼容:StorageBackend 保留为聚合接口")。但现状:
  - `review_engine.py:56` 和 `state_machine.py:50` 都用 `storage: StorageBackend` 注入(RFC §3.5 截图本身如此)
  - `cli.py` 第 374 行 `file_store, ledger_store, state_store = storage, storage, storage` 是 Python 多接口继承技巧,**单实例多接口赋值仅在 ABC 多继承 + self 类型下成立**——FSBackend 必须**显式继承 3 个 ABC** 才能这样赋值。RFC 未提及 FSBackend 需要重写继承结构。
  - **新代码按子接口注入的 engine 类**和**旧代码按 StorageBackend 注入的 engine 类**共存时,依赖注入容器构造逻辑会复杂化
- **触发条件**:任何引入新子接口依赖的 engine 类
- **影响范围**:所有 engine 模块的测试 fixture、依赖注入装配
- **RFC 章节**:§3.5

### P1-RC-05:`tooling.languages` 缺省时的"旧默认 [.py]"会与"配置了 [.ts]"的项目混淆
- **具体风险**:RFC §3.3 "向后兼容:tooling.languages 缺省时用旧默认 [.py],旧 sop.yaml 行为不变"。问题:
  - **TS/Go 项目没升级 sop.yaml** → tooling.languages 不存在 → 用 [.py] 默认 → TS 项目**完全没有 no_test 审计**(`has_code` 永远 False),这是 RFC 想解决的核心问题反向重现
  - **混用项目**(前后端分离,既有 .py 又有 .ts)→ 用户配置 `[".py", ".ts"]` → 测试文件命名约定不一致(JS 用 `.spec.ts`,Python 用 `test_*.py`)→ `test_patterns` 是简单子串匹配 → **误判**:文件名含 "test" 的非测试文件(如 `contest_utils.py`)被判为测试
- **触发条件**:任何多语言项目或测试命名不规范的项目
- **影响范围**:所有非纯 Python 项目的红线审计准确性
- **RFC 章节**:§3.3

### P1-RC-06:`timestamp` 时区化后,旧账本 naive timestamp 读取兼容未实测
- **具体风险**:RFC §3.7 "旧账本 naive timestamp 读取时按 UTC 补时区(读取层兼容)"。问题:
  - YAML 序列化时,naive datetime 不带 tzinfo;Pydantic v2 默认对 naive datetime 不报错,但**比较运算**(如审计时序检查)会把 naive 当本地时间
  - **用户机器时区不同时**,同一账本的时间戳呈现不一致——审计报告"timestamp 已统一时区"的承诺实际不成立
  - 迁移后的 v2 账本 = timezone-aware 条目 + 旧 v1 naive 条目,**哈希链贯穿两类时间戳**——RFC 未说 v2 hash 算法对两类时间戳的序列化是否一致
- **触发条件**:任何跨时区协作、容器/CI 时间不一致场景
- **影响范围**:审计时序、跨机器账本对比
- **RFC 章节**:§3.7

### P1-RC-07:迁移日志"迁移前 hash 存档"的审计价值不足
- **具体风险**:RFC §2.3 步骤 5 "写迁移日志(迁移前 hash 存档,供审计)"。问题:
  - **谁负责验证迁移后哈希?** 迁移工具自己重算、自己验证——**自我验证不是独立审计**
  - **迁移日志存在哪里?** RFC 未说(账本内?独立文件?stdout?)
  - **迁移日志本身的完整性?** RFC 未规定迁移日志有独立的哈希保护——可被篡改而不被察觉
- **触发条件**:任何争议场景("账本是迁移后被改的还是迁移前就改了?")
- **影响范围**:迁移后所有争议性审计场景
- **RFC 章节**:§2.3(步骤 5)

### P1-RC-08:`actor` 字段默认 "agent" 暴露 devflow 的 agent-centric 假设
- **具体风险**:RFC §3.1 "actor 由调用方传入(默认 'agent')"——但**人类操作也是 actor**,人类使用 devflow CLI 时,actor 仍是 "agent"(错的)。问题:
  - `devflow next` 是人类在 shell 里敲的,但 actor 永远是 "agent"
  - 第 5 轮残余风险清单第 6 项已经明确指出"`actor` 字段无启用标记(Speculative Generality 陷阱)"——RFC v0.4 仍未给出 actor 类型枚举或调用方分类机制
  - **审计追溯的"谁做的"语义不可信**
- **触发条件**:任何真实人类使用 devflow 的场景
- **影响范围**:actor 字段的全部审计价值
- **RFC 章节**:§3.1

---

## 🟡 合规/审计疏漏(P2)

### P2-RC-01:`gate_result` 持久化未做敏感信息脱敏
- **具体风险**:RFC §3.6 把 stdout/stderr 尾部 500 字符直接入账本;**未提及脱敏**(密码、token、邮箱、个人信息)
- **审计维度**:合规(GDPR / SOC2 / ISO27001)
- **缓解难度**:中(需引入敏感模式匹配 + 替换策略)
- **RFC 章节**:§3.6

### P2-RC-02:`migrate-ledger` 命令无 dry-run 模式
- **具体风险**:迁移是不可逆的,但 RFC §2.3 未提供 `--dry-run` 选项。用户**必须实际执行迁移才能看到结果**——回滚必须用 bak-v1。
- **审计维度**:变更管理(变更前预览)
- **缓解难度**:低(纯功能扩展)
- **RFC 章节**:§2.3

### P2-RC-03:`ledger_version` 字段的"有效版本集合"未声明
- **具体风险**:RFC §2.3 仅提到 v1.0 / v2.0 两种,但 v0.4 → v0.5 还会新增字段。若 v0.5 用户拿 v0.4 读 v0.5 账本——`ledger_version` 未知的回退路径是?
- **审计维度**:前向兼容
- **缓解难度**:低(加 unsupported version 错误处理)
- **RFC 章节**:§2.3

### P2-RC-04:`RedLineViolation` 加 `status` 字段后,旧 CLI 输出解析器会忽略新字段
- **具体风险**:RFC §3.4 `RedLineViolation.status` 字段新增。CLI JSON 输出多一个字段——**依赖审计字段集合的脚本可能因 schema 变更静默失败**(旧字段被忽略、新字段不消费)。
- **审计维度**:外部集成兼容性
- **缓解难度**:低(显式版本号字段)
- **RFC 章节**:§3.4

### P2-RC-05:`migrate-ledger` 迁移日志缺少"谁、何时授权"审计签名
- **具体风险**:RFC §2.3 步骤 5 "写迁移日志",但日志内容无操作者标识(谁跑的 migrate)、无授权链(谁批准)。**合规审计无法追溯谁有权发起不可逆迁移**。
- **审计维度**:合规(SOX / 责任认定)
- **缓解难度**:中(需引入操作者鉴权)
- **RFC 章节**:§2.3(步骤 5)

### P2-RC-06:`tooling.languages.test_patterns` 是子串匹配,误判率高
- **具体风险**:RFC §3.3 `test_patterns: ["test", "_test", ".spec."]`,RFC 后续代码 `any(p in f.lower() for p in test_pat)` 是子串匹配:
  - `contest.py` 含 "test" → 被判为测试文件
  - `protest.py` 含 "test" → 被判为测试文件
  - `latest_artifact.py` 含 "test" → 被判为测试文件
- **审计维度**:审计准确性
- **缓解难度**:中(改用正则或 glob 模式)
- **RFC 章节**:§3.3

### P2-RC-07:`StorageBackend` 拆分后,旧 plugin/扩展实现会因未实现新子接口而崩溃
- **具体风险**:RFC §3.5 拆 3 接口 + 保留聚合接口。但**第三方 plugin/扩展**(若有)基于 `StorageBackend` 全方法实现——拆分后基类继承关系变化,**Plugin 继承的中间抽象类若不显式继承新子接口,实例化会报 `TypeError: Can't instantiate abstract class`**。
- **审计维度**:扩展兼容性
- **缓解难度**:低(保留旧 StorageBackend 完整继承链即可)
- **RFC 章节**:§3.5

### P2-RC-08:`v0.4` RFC 整体未提供 "数据驻留合规" 条款
- **具体风险**:RFC 全篇未涉及账本存放路径的合规性(本地?OSS?加密?)。企业用户**无法用 v0.4 满足数据驻留合规要求**(GDPR 数据出境、等保三级)。
- **审计维度**:合规(数据驻留)
- **缓解难度**:中(需引入 storage backend 加密/远程后端接口)
- **RFC 章节**:全文缺失

---

## 应急缺口

> 列出 RFC 缺失的应急预案(每条核心设计都应有降级路径)

1. **账本迁移中断恢复**:§4 迁移流程未规定**迁移过程崩溃时的具体恢复步骤**(当前进度检测、是否可续传、临时文件清理)
2. **`migrate-ledger` 命令执行到一半被 SIGKILL 的状态机**:未定义**半成品账本如何识别与清理**
3. **v0.3.1-r2 用户升级 v0.4 后账本 verify 失败的"急救通道"**:§4.3 仅说"恢复 .bak-v1",但**未说如何识别"我需要回滚"**(用户怎么知道 v0.4 不可用?)
4. **忘跑 migrate 的用户**:§4.1 假设用户主动迁移,**无默认阻断机制**(v0.4 代码直接读 v1 账本会怎样?)
5. **迁移工具自身 bug 导致账本损坏的灾难恢复**:无 `devflow rebuild-ledger` 类工具(从 spec/plan/report 重建账本的最后救命稻草)
6. **`.bak-v1` 备份被误删后的审计追溯**:§4.1 备份存在,**备份缺失时的降级路径**未提供
7. **`gate_result` 含敏感信息时的紧急擦除**:§3.6 入账本即永久哈希固化,**无脱敏补救**
8. **`StorageBackend` 拆分导致 engine 拿不到子接口时的回退**:§3.5 无 fallback 装配路径
9. **多 spec 场景下迁移后 review-audit 误报的纠正**:§3.2 双向 JOIN,**误报后的手动 override 路径**未提供
10. **`tooling.languages` 配置错误(例如空列表)时的兜底**:§3.3 默认 [.py],但用户配置 `languages: {}` 会触发 `.get("languages", {}).get("code_extensions", [".py"])` → 空 dict 的 .get 仍返回空 list → `f.endswith(tuple([]))` → **无代码扩展匹配,no_test 永远 pass** —— 这是"已审计通过"的假象
11. **`RedLineViolation.status` 字段被旧代码读取时的兼容降级**:§3.4 `to_dict()` 输出多 status 字段,**旧 JSON 消费者忽略字段不报错但语义失效**,无 deprecation 警告
12. **v0.4 自身有 bug 时的 hotfix 路径**:RFC §4.3 仅说回滚到 v0.3.1-r2 代码,**无 v0.4.1 / v0.4.2 热修路径**

---

## v0.3 INDEX / r1 教训对照

> 逐项对照 v0.3 INDEX 回退教训 + 第 5 轮 r1 的 7 个 P0,v0.4 是否重蹈覆辙?

### v0.3 INDEX 教训对照(`v0.3-rejected-design.md`)

| 教训 | v0.3 INDEX 错在哪 | v0.4 RFC 是否规避 |
|------|-------------------|---------------------|
| **扩 storage schema 破坏哈希链**(INDEX 设计根因) | 加 `archive` 段破坏 entries 哈希 | ⚠️ **部分规避**:RFC 用分代哈希承认要扩 schema,**承认破坏**(§2.3)。但通过迁移工具"洗白"——**审计承诺的实质被破坏,只是形式合规** |
| **"更简替代优先"未贯彻** | INDEX 复杂方案被第一性质疑者 [F] 否决 | ⚠️ **未贯彻**:RFC 的 actor/session_id/review_ref/gate_result 字段,**完全可拆为多个独立审计文件而不必扩 LedgerEntry**。第 3 轮 P1-13 的 JOIN 关联键错问题,仍可借文件系统 JOIN review_store+ledger 解决——RFC 重走"扩 schema"老路 |
| **撤销功能应简单**(INDEX §"撤销归档天然支持") | INDEX 撤销需 unarchive CLI | ✅ **部分规避**:v2 → v1 不可回退是承认现实;但 RFC 没考虑"撤销迁移"的需求 |
| **零新接口原则**(INDEX 4 个 ABC 方法被批) | INDEX 加 4 个接口 | ⚠️ **未规避**:RFC §3.5 拆 3 个 ABC,反而**新增更多接口**(INDEX 是 4 个,这次是 3 个 + 聚合 = 4 个抽象)。**结构同构,本质未变** |

### 第 5 轮 r1 7 个 P0 对照

| r1 P0 | r1 错在哪 | v0.4 RFC 是否规避 |
|-------|-----------|---------------------|
| **P0-1** LedgerEntry 字段扩展破坏哈希链 | 加 review_id/actor 进 hash | ⚠️ **形式规避 / 实质同构**:RFC 用分代哈希**承认要扩字段进 hash**(§2.3 `_HASH_FIELD_ORDER_V2` 包含新字段),但用迁移工具"重算整条链"——**这是"承认破坏 → 一次性重算" 的变体**,与 r1 的"加字段 → 全链失败"结构同构 |
| **P0-2** ledger 字段缺失 / 5 处 append_ledger 漏算 | r1 方案示例机械搬抄 | ✅ **规避**:RFC 全文搜索 LedgerEntry 用法,**migrate-ledger 用统一入口重算**,不依赖各调用方手动加字段(§2.3 步骤 3) |
| **P0-3** 重蹈 v0.3 INDEX 覆辙 | 扩 schema + 新 CLI + 5 处 ledger | ⚠️ **形式规避 / 实质同构**:RFC 的 LedgerEntry + spec_id/actor/session_id/review_ref/gate_result **5 个新字段** + 新 CLI `migrate-ledger` + 改 5 处 append_ledger 写入点——**结构与 r1 完全同构** |
| **P0-4** pytest 双跑 | r1 接 pytest-cov | ✅ **规避**(RFC v0.4 不涉及 CI 改造) |
| **P0-5** `_extract_coverage` 正则脆弱 | r1 正则 fragile | ✅ **规避**(RFC v0.4 不涉及覆盖率提取) |
| **P0-6** fail-closed 破坏隐性兼容 | r1 改默认 enabled=true | ✅ **规避**(RFC v0.4 不涉及门禁默认变更) |
| **P0-7** stub 暴露让审计承诺降级 | r1 stub 仍返回 [] | ⚠️ **部分规避**:RFC §3.4 加 `status` 字段(4 态),让 stub 进入 violations——**与 r2 修复方向一致**;但 RFC §3.5 又把 `audit()` 改为"配置驱动循环"——**这是 r2 已避免的过度重构,可能再次破坏 audit 行为** |
| **NP0-2** JOIN spec_id 关联键错(r2 新发现) | r2 用 current_spec_id 错 | ⚠️ **形式规避 / 实质同构**:RFC §3.1 加 spec_id 字段(写入时由 `get_current_spec_id()` 自动填充)**仍是用 current_spec_id 关联**——**NP0-2 根因未解决,只是从 r2 的"JOIN 时推断"提前到 r0 的"写入时填充"**。如果用户切换 spec,旧条目写入时的 spec_id 仍是旧 spec(✅ 这一层 OK),但**写入逻辑从 r2 的"读 ledger 顶层"改为 v0.4 的"读 storage 接口"——同一错误的两种实现** |

### 总结:教训落地度评估

> **v0.3 INDEX 教训落地度:1/4**(`progress.yaml.bak-v1` 备份 = "承认不可逆"是真正吸取教训)
> **第 5 轮 r1 教训落地度:4/7**(规避了不涉及的部分;**涉及"扩 schema"的核心 P0-1/P0-3/NP0-2 形式规避但实质同构**)

---

## 总计

- **致命隐患(P0)**:6 条
- **重大隐患(P1)**:8 条
- **合规疏漏(P2)**:8 条
- **应急缺口**:12 条

---

## 审计元数据

- **审计人**:风险管控者(独立子代理)
- **审计范围**:v0.4 RFC 主文档 + 6 份代码事实 + 第 5 轮 r1/r2 + v0.3-rejected-design
- **独立性**:✅ 未参考其他角色审计输出
- **关注点**:数据安全、后向兼容、合规、损失评估、应急预案、历史教训对照
- **不输出**:解决方案 / 修复路径 / 代码修改建议