# P1-5 完整版方案：Red Line Plugin 机制

> **决策来源**：用户选择"完整版"——加 entry_points 机制，让第三方包注册自定义红线 checker。
> **当前状态**：`audit()` 已是循环（v0.3.1-r2 P1-5），但 stub 仍是手写函数。新规则 = 改 `redline_auditor.py`。
> **目标**：新增红线规则 = 改 `sop.yaml` + 写一个 checker 函数（无需改引擎）。

---

## 1. 现状分析

### 1.1 现有 checker 分布
- 6 条**已实现** checker（`_check_no_test` / `_check_cross_module_import` / `_check_huge_pr` / `_check_uncommitted_bulk` / `_check_main_incomplete`）
- 5 条**stub**（`_check_skip_phase` / `_check_doc_drift` / `_check_silent_legacy` / `_check_no_contract` / `_check_human_step_auto`）
- 0 条**plugin**（外部注册）

### 1.2 痛点
- 5 条 stub 是手写函数，结构高度重复（约 50 行）
- 加新规则必须改 `redline_auditor.py`
- 5 条 stub 无法在 `sop.yaml` 关闭（不配置 = 强行 stub 提示）
- 0 个第三方扩展点

---

## 2. 完整方案：Plugin 机制

### 2.1 核心抽象：`RedLineChecker`

```python
# src/devflow/engine/redline_plugin.py（新建 ~80 行）
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Callable
from pathlib import Path

from .redline_auditor import RedLineViolation


class RedLineChecker(ABC):
    """红线 checker 协议（v0.4 P1-5 完整版）

    第三方包通过实现本协议 + setuptools entry_points 注册自定义红线：
    1. 子类化 RedLineChecker
    2. 实现 name / check / optional message
    3. 在包 setup.cfg 注册 entry_points = {'devflow.redlines': 'my_rule = my_pkg:MyChecker'}
    4. devflow audit 自动发现并执行
    """
    name: str = ""  # 红线名称（sop.yaml red_lines: 中引用）

    @abstractmethod
    def check(self, context: 'RedLineContext') -> list[RedLineViolation]:
        """执行检查，返回违规列表（空列表 = 通过）"""


class RedLineContext:
    """checker 上下文：提供引擎可访问的资源（git / root / config）

    checker 不直接依赖 GitPort / SOPConfig，而是通过 context 间接获取。
    这让第三方 checker 写起来更简单（无需理解 devflow 内部结构）。
    """
    def __init__(self, root: Path, config: 'SOPConfig', git: Optional['GitPort']):
        self.root = root
        self.config = config
        self.git = git
```

### 2.2 Plugin 注册表

```python
# src/devflow/engine/redline_plugin.py（继续）
def discover_redline_plugins() -> dict[str, type[RedLineChecker]]:
    """通过 setuptools entry_points 发现第三方 plugin

    entry_points group = 'devflow.redlines'
    name = rule name, target = 'module:ClassName'
    """
    plugins = {}
    for ep in importlib.metadata.entry_points(group="devflow.redlines"):
        try:
            cls = ep.load()
            if issubclass(cls, RedLineChecker):
                plugins[ep.name] = cls
        except Exception as e:
            logger.warning(f"加载 redline plugin '{ep.name}' 失败: {e}")
    return plugins
```

### 2.3 引擎循环：plugin + 内置 checker 统一调度

```python
# src/devflow/engine/redline_auditor.py 改造
class RedLineAuditor:
    def __init__(self, root, config, git=None):
        self.root = root
        self.config = config
        self.git = git
        # v0.4 P1-5: 内置 checker 名称 → 方法名
        self._builtin_checkers = {
            "no_test": self._check_no_test,
            "cross_module_import": self._check_cross_module_import,
            "huge_pr": self._check_huge_pr,
            "uncommitted_bulk": self._check_uncommitted_bulk,
            "main_incomplete": self._check_main_incomplete,
        }
        # 第三方 plugin（按需发现，单实例缓存）
        self._plugins = None  # lazy load

    def audit(self) -> list[RedLineViolation]:
        violations = []
        ctx = RedLineContext(self.root, self.config, self.git)
        for red_line in self.config.red_lines:
            if red_line.mvp_skip:
                violations.append(RedLineViolation(
                    red_line.name,
                    f"红线 '{red_line.name}' 在 sop.yaml 标 mvp_skip",
                    skip=True,
                    status=ViolationStatus.MVP_SKIP,
                ))
                continue
            # 1. 内置 checker
            builtin = self._builtin_checkers.get(red_line.name)
            if builtin:
                result = builtin()
                if not result:
                    violations.append(RedLineViolation(
                        red_line.name, "检测器返回空(可能为 stub)",
                        skip=True, status=ViolationStatus.STUB,
                    ))
                else:
                    violations.extend(result)
                continue
            # 2. 第三方 plugin
            if self._plugins is None:
                self._plugins = discover_redline_plugins()
            plugin_cls = self._plugins.get(red_line.name)
            if plugin_cls:
                plugin = plugin_cls()
                result = plugin.check(ctx)
                violations.extend(result)
                continue
            # 3. 完全无实现
            violations.append(RedLineViolation(
                red_line.name,
                f"红线 '{red_line.name}' 无内置实现且未发现 plugin",
                skip=True, status=ViolationStatus.NOT_IMPLEMENTED,
            ))
        return violations
```

### 2.4 简化 5 条 stub

```python
# 删除 _check_skip_phase / _check_doc_drift / _check_silent_legacy / _check_no_contract / _check_human_step_auto
# 改为 sop.yaml 默认 red_lines 不列这 5 条，用户要启用 = 写 plugin 或保留手写
```

**sop.default.yaml 变更**：
```yaml
red_lines:
  - no_test
  - cross_module_import
  - huge_pr
  - uncommitted_bulk
  - main_incomplete
  - circular_dep  # 保持 mvp_skip: true（等补 AST 时再 active）
# 删除 5 条 stub（skip_phase / doc_drift / silent_legacy / no_contract / human_step_auto）
# 这 5 条原本就是 stub，由 sop.yaml 移除后不再提示"已实现 stub"
```

### 2.5 文档：第三方如何写 plugin

```python
# docs/redline-plugin-guide.md（新建）
# 1. 写 checker
from devflow.engine.redline_plugin import RedLineChecker, RedLineContext
from devflow.engine.redline_auditor import RedLineViolation

class NoDebugPrintChecker(RedLineChecker):
    name = "no_debug_print"
    def check(self, context):
        violations = []
        for py_file in context.root.rglob("*.py"):
            content = py_file.read_text(encoding="utf-8")
            for i, line in enumerate(content.split("\n"), 1):
                if "print(" in line and "DEBUG" in line:
                    violations.append(RedLineViolation(
                        "no_debug_print",
                        f"{py_file}:{i}: 调试 print 未清理",
                    ))
        return violations

# 2. 在 setup.cfg / pyproject.toml 注册
# [project.entry-points."devflow.redlines"]
# no_debug_print = "my_pkg:NoDebugPrintChecker"

# 3. 在 sop.yaml red_lines: 加 - no_debug_print
```

---

## 3. 改动范围（6 文件）

| 文件 | 改动 | 行数 |
|------|------|------|
| `src/devflow/engine/redline_plugin.py` | **新建**：`RedLineChecker` ABC + `RedLineContext` + `discover_redline_plugins` | ~80 |
| `src/devflow/engine/redline_auditor.py` | `__init__` 加载内置 map + `audit()` 改为 plugin 调度循环；删除 5 条 `_check_*` stub | +30 / -50 |
| `config/sop.default.yaml` | 删除 5 条 stub red_lines 引用 | -5 |
| `tests/test_redline_plugin.py` | **新建**：6 条测试 | ~120 |
| `docs/redline-plugin-guide.md` | **新建**：第三方开发指南 | ~80 |
| `docs/CHANGELOG.md` | [Unreleased] 段记录 | +10 |

---

## 4. 风险控制

| 风险 | 缓解 |
|------|------|
| plugin 加载失败导致 audit 中断 | `discover_redline_plugins` 用 try/except，单个失败不影响其他 |
| 第三方 plugin 写错导致审计变慢 | checker 文档明确建议 O(1) 或 O(文件数)；不加超时（防误杀） |
| 旧用户 sop.yaml 仍引用 5 条 stub 名 | 添加兼容：sop.yaml 含 skip_phase/doc_drift/silent_legacy/no_contract/human_step_auto → 自动标 `not_implemented` + 提示"该规则已重命名为 plugin 模式" |
| 5 条 stub 行为变更（删除） | P1-5 完整版的"完整"定义就是删除 stub，让规则可选择性启用 |

---

## 5. 测试计划

`test_redline_plugin.py`（新建，6 条）：
1. `test_discover_builtin_only`：无 plugin 时，只用内置 checker
2. `test_discover_finds_entry_point`：mock entry_points 返回 1 个 plugin，能被找到
3. `test_audit_dispatches_to_plugin`：sop.yaml 配 plugin 名 → 调用 plugin.check()
4. `test_audit_plugin_failure_doesnt_break_others`：1 个 plugin 抛异常 → 其它 plugin 仍执行
5. `test_removed_stub_rules_compat`：sop.yaml 含 "skip_phase" → 标 `not_implemented` + 提示
6. `test_audit_with_mvp_skip_unchanged`：mvp_skip 行为不变

**全量回归**：380 + 6 = **386 passed**（实际可能更少，因删 5 条 stub 后旧测试可能失效）

---

## 6. 不做的事

- ❌ 不补 `circular_dep` AST 检测（保留 mvp_skip；等真正需要时再补）
- ❌ 不做 plugin marketplace / 远程注册
- ❌ 不加 plugin 权限沙箱（用户自负责任）
- ❌ 不做 plugin 热加载（一次性 entry_points 发现）

---

方案确认后按这个顺序执行：建 `redline_plugin.py` → 改 `redline_auditor.py` → 改 `sop.default.yaml` → 写测试 → 写文档 → 全量回归。继续吗？