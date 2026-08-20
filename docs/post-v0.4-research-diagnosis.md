# v0.4 research 真实环境诊断报告 (场景 A)

> 用 `scripts/diagnose_research.py` 在 demo_research 工作区真实跑出来的结果。
> 发现 **2 个真实 bug**,这是 mock 测试看不到的并发边界问题。

---

## 🎯 测试环境

| 项 | 值 |
|---|---|
| 工作区 | `demo_research/`(临时目录) |
| Spec | `20260821-implement-retry-from-scratch.yaml` |
| 查询 | `python retry library` |
| 数据源 | `github, pypi, npm, web`(SOP 默认) |
| 网络 | 部分可达(registry 健康,github API 不通,agent_reach CLI 路径未真实调用) |

---

## 🐛 Bug 1: `sources_used` 与 `sources_failed` 互相矛盾

### 现象

```json
{
  "ok": true,
  "citations_count": 5,
  "sources_used": ["web"],
  "sources_failed": ["web"],   ← 与 used 重复!
  "fallback_used": true,
}
```

### 根因

`engine/research_runner.py::_execute_backends()` 第 233-240 行:

```python
if citations:
    all_citations.extend(citations)
    src = b.source_type
    if src not in sources_used:
        sources_used.append(src)        # 成功 -> 加到 used
else:
    if b.source_type not in sources_failed:
        sources_failed.append(b.source_type)   # 空结果 -> 加到 failed
```

**问题**:
1. **空结果 ≠ 失败**:backend 健康但 query 无结果(如 DuckDuckGo 无 abstract)应保持"已尝试,无命中"语义,不应算失败。
2. **多个 backend 共享 source_type**:`RegistryQueryBackend` 与 `WebSearchBackend` 都标 `source_type = WEB`(因为 registry 覆盖多源),它们各自的成功/失败被合并到同一个 SourceType 维度,导致 used 和 failed 同时出现。
3. **维度错误**:应该是 **backend 名字维度**(`backend_chain`),不是 **source_type 维度**。

### 影响

- 用户看 `sources_failed` 误以为该源真的失败,实际可能只是空结果。
- `Spec.research_refs[].sources` 字段写的是 `web`,但报告里实际显示 `npm` 来源——**数据污染**。

### 修复方案

**方案 A(推荐)**:把 `sources_used` / `sources_failed` 改为 **backend 名字列表**(`["registry", "agent_reach", "web_search"]`),与 `backend_chain` 维度一致。Citation 自己的 `source_type` 仍保留(由 backend 决定)。

**方案 B(保守)**:保留 source_type 维度,但修复空结果逻辑——空结果不计入 failed,改为新增字段 `sources_empty: list[str]`。

**方案 C(最简洁)**:维持现状但加注释——明确说"`sources_used` 与 `sources_failed` 是 SourceType 维度,不是 backend 维度;空结果与失败都计入 failed,这是 trade-off"。

### 我的推荐

**方案 A**——对用户更直观,与 `backend_chain` 一致;代码改 ~30 行,测试改 ~10 行。

---

## 🐛 Bug 2: `trust_level: high` 与真实来源不符

### 现象

`Spec.research_refs` 写入 `trust_level: "high"`,但实际引用全部来自 npm 注册中心查询(无 GitHub star 数据,trust 应为 MEDIUM 或 LOW)。

### 根因

`engine/research_runner.py::_update_spec()` 第 328-334 行:

```python
if report.has_high_trust():
    trust = "high"
elif report.citations:
    trust = "medium"
else:
    trust = "unknown"
```

`has_high_trust()` 检查**任一** citation `trust_level == HIGH`。但实际跑出来的 npm 包,后端在 `_make_citation` 时设置的是 `trust_level=TrustLevel.HIGH`(因为 npm 是官方源),所以**正确**标了 HIGH。

**等等,这是对的**?让我再看一次诊断输出:

```
sources_used: ['web']   ← 但实际是 npm 来源
```

`sources_used` 是 bug 1 的污染,显示 `web` 是错的。但 `trust_level: high` 实际是因为 npm 包的 trust 真的就是 HIGH(PyPI/npm/crates 都标 HIGH)。

**结论**:Bug 2 **不是 bug**,是 Bug 1 的视觉错觉——`sources_used` 字段不可信,但 `trust_level` 本身正确。

### 修复方案

**不需要单独修**,但建议:

1. 把 `sources_used` 改成 backend 名字(修 Bug 1 同时修)
2. `Spec.research_refs` 加 `backends_used: list[str]` 字段,让审计更清楚

---

## 🐛 Bug 3(次要): `agent_reach` 健康但实际未跑通

### 现象

诊断脚本显示 `agent_reach: [+](健康)`,但实际 report 的 `Backend Chain` 显示 `web → agent_reach → registry`,agent_reach 出现在 chain 里但**没产生引用**。

### 根因

`AgentReachBackend.health_check()` 三层信号任一通过即 True:
1. 环境变量 `CLAUDE_CODE` / `WORKBUDDY_RUNTIME` / `CODEBUDDY_RUNTIME`
2. skill 文件存在
3. **PATH 中有 `claude` / `wb` / `codebuddy` 命令**(用户的机器有 `claude.CMD`,通过!)

但**真实场景**:
- 用户用普通 shell 跑 `devflow research`
- 没有 Claude Code 进程在监听 `claude --skill agent-reach` 这种调用
- 命令返回非零或空输出
- `_safe_search` 兜底返回空列表

**问题**:`health_check()` 的 PATH 信号**不够准确**——光有命令不代表能真用。

### 修复方案

**方案 A(轻量)**:加一层"实际调用测试"——`health_check` 跑一次 `claude --version` 之类 sanity check,失败则 False。
**方案 B(彻底)**:`search()` 失败后降级 `health_check()` 为 False(动态探测)。
**方案 C(维持现状)**:在文档里说明 `health_check()` 是**乐观探测**,实际是否能用看 `search()` 返回值。

### 我的推荐

**方案 C**(维持)+ `select_backends` 的 `include_unhealthy=False` 已经能过滤失败的 backend。但 `_execute_backends` 当前**没有重试 health_check**——失败 backend 还被送进 ThreadPoolExecutor,浪费线程。

**修复**:`select_backends` 返回的 backend 中,实际能产出的(根据本次 run 的结果)才是 used;失败的进 failed。这等价于 Bug 1 修复的同时改。

---

## 📊 影响范围总结

| Bug | 严重度 | 影响用户 | 修复优先级 |
|---|---|---|---|
| **1** sources_used/failed 矛盾 | 中 | 误判 backend 失败,审计不准 | **P1**(本次修) |
| **2** trust_level | 无 | 实际正确,视觉错觉 | 无 |
| **3** agent_reach 乐观探测 | 低 | 浪费线程但不影响结果 | **P2**(下次修) |

---

## 🛠️ 修复 PR 方案

### 改动文件

| 文件 | 改动 |
|---|---|
| `engine/research_runner.py` | `_execute_backends()` 返回值改为 `(citations, used_backends, failed_backends, empty_backends, chain)`;`_update_spec()` 用 backend 名字;`run()` 返回 JSON 字段同步 |
| `tests/test_research_runner.py` | 改 `test_sources_used_tracked` 期望;补 `test_empty_result_not_failure`;补 `test_backend_dimension_not_source_type` |
| `tests/test_research_cli_integration.py` | 改 `test_plan_auto_run_on_in_sop` 字段断言(如有) |

### 关键改动 1:`_execute_backends` 返回值

```python
def _execute_backends(
    self, backends: list[ResearchBackend], query: ResearchQuery,
) -> tuple[
    list[Citation],
    list[str],    # used_backends (按 chain 顺序)
    list[str],    # failed_backends (异常 / 超时)
    list[str],    # empty_backends (健康但 0 命中)
    list[str],    # backend_chain
]:
    ...
    for fut in done:
        b = future_to_backend[fut]
        backend_chain.append(b.name)
        try:
            citations = fut.result()
        except Exception:
            failed_backends.append(b.name)
            continue
        if citations:
            all_citations.extend(citations)
            used_backends.append(b.name)
        else:
            empty_backends.append(b.name)
    ...
```

### 关键改动 2:`run()` 返回字段

```python
# 旧
"sources_used": [s.value for s in sources_used],
"sources_failed": [s.value for s in sources_failed],

# 新
"backends_used": used_backends,         # ["registry"]
"backends_failed": failed_backends,     # [] (这次没有失败)
"backends_empty": empty_backends,       # ["agent_reach", "web_search"]
"sources_in_results": list({
    cit.source_type.value for cit in trimmed_citations
}),  # ["npm"] (从 citations 提取,反映真实来源)
```

### 关键改动 3:`_update_spec`

```python
# 旧
spec.research_refs.append({
    "sources": [s.value for s in report.sources_used],
    ...
})

# 新
spec.research_refs.append({
    "backends": report.backend_chain,           # 全链路审计
    "sources_in_citations": list({               # 实际引用来源
        c.source_type.value for c in report.citations
    }),
    ...
})
```

### 兼容性

`Spec.s.research_refs` 是 `list[dict]`(无 schema),加字段不破坏旧数据。CLI 输出 JSON 加字段也是向后兼容的(旧字段保留为 deprecated)。

---

## ⏱️ 修复工作量

| 子任务 | 估计 |
|---|---|
| engine/research_runner.py 改 3 处方法 | 30 分钟 |
| tests/test_research_runner.py 改 3 个测试 + 加 2 个 | 30 分钟 |
| tests/test_research_cli_integration.py 改 1 处(如有) | 10 分钟 |
| 跑全套测试 + ruff + mypy | 15 分钟 |
| commit + push | 10 分钟 |
| **合计** | **1.5-2 小时** |

---

## 🎯 修复后再次验证

跑同一命令确认 bug 已修:

```bash
cd demo_research
python ../scripts/diagnose_research.py "python retry library" --spec-id ...
```

期望输出:

```json
{
  "ok": true,
  "citations_count": 5,
  "backends_used": ["registry"],
  "backends_failed": [],
  "backends_empty": ["agent_reach", "web_search"],
  "sources_in_results": ["npm"],
  "fallback_used": true,
  "message": "调研完成,5 条引用 (fallback 已触发)"
}
```

---

## 📌 决策点

请确认:

1. **是否同意方案 A(改 backend 名字维度)**?还是 B(保留 source_type + 加 sources_empty)?
2. **是否同意修复 Bug 3(乐观探测)**?还是只修 Bug 1?
3. **是否现在修**(1.5-2 小时),还是先开下一个 RFC(Bug 留 v0.4.1)?

我的推荐:**方案 A + 不修 Bug 3 + 现在修**(理由:Bug 1 是审计准确性问题,用户能看到;Bug 3 影响小,留 v0.4.1)。

---

**Refs**: `feat/v0.4-research` commit `739a928`
**修复 PR**: 待定(等你确认方案)