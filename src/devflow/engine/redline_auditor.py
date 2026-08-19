"""RedLineAuditor — 红线审计

MVP 实现 10 条可自动检测的红线 + 1 条 circular_dep 标记 mvp_skip。
依赖 GitPort 抽象接口，不直接调 subprocess。
"""
from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Optional

from ..policy.loader import SOPConfig
from ..storage.git_port import GitPort


class ViolationStatus(str, Enum):
    """v0.3.2 P1-5 补强: 红线违规状态枚举

    active:          真实违规(需修复)
    mvp_skip:        sop.yaml 配置 mvp_skip: true 跳过
    stub:            checker 存在但实现为空(未自动检测)
    not_implemented: 无对应 checker 方法(未实现)
    """
    ACTIVE = "active"
    MVP_SKIP = "mvp_skip"
    STUB = "stub"
    NOT_IMPLEMENTED = "not_implemented"


class RedLineViolation:
    """红线违规

    v0.3.2 P1-5 补强: 增加 status 枚举字段,替代仅靠 skip 布尔+message 文本。
    """
    def __init__(self, rule: str, message: str, skip: bool = False,
                 status: ViolationStatus = ViolationStatus.ACTIVE):
        self.rule = rule
        self.message = message
        self.skip = skip
        self.status = status

    def to_dict(self) -> dict:
        return {
            "rule": self.rule,
            "message": self.message,
            "skip": self.skip,
            "status": self.status.value,
        }


class RedLineAuditor:
    """红线审计器"""

    def __init__(self, root: Path, config: SOPConfig, git: Optional[GitPort] = None):
        self.root = root
        self.config = config
        self.git = git

    def audit(self) -> list[RedLineViolation]:
        """执行全量红线扫描

        v0.3.2 P1-5 补强: 为每条违规标注结构化 status 枚举。
        """
        violations: list[RedLineViolation] = []
        for red_line in self.config.red_lines:
            if red_line.mvp_skip:
                violations.append(RedLineViolation(
                    red_line.name,
                    f"红线 '{red_line.name}' 在 MVP 中跳过检测",
                    skip=True,
                    status=ViolationStatus.MVP_SKIP,
                ))
                continue
            checker = getattr(self, f"_check_{red_line.name}", None)
            if checker is None:
                violations.append(RedLineViolation(
                    red_line.name,
                    f"红线 '{red_line.name}' 缺少自动检测实现",
                    skip=True,
                    status=ViolationStatus.NOT_IMPLEMENTED,
                ))
                continue
            result = checker()
            if not result:
                violations.append(RedLineViolation(
                    red_line.name,
                    f"红线 '{red_line.name}' 检测实现为 stub(未自动检测)",
                    skip=True,
                    status=ViolationStatus.STUB,
                ))
                continue
            violations.extend(result)
        return violations

    def _get_language_config(self) -> dict:
        """v0.3.2 P1-11: 从 sop.yaml tooling.languages 读取语言配置

        缺省回退到旧默认值(仅 .py,兼容旧 sop.yaml)。
        """
        langs = self.config.tooling.get("languages", {})
        return {
            "code_extensions": langs.get("code_extensions", [".py"]),
            "test_patterns": langs.get("test_patterns", ["test", "_test", ".spec."]),
            "test_extensions": langs.get("test_extensions", None),
        }

    def _is_test_file(self, filename: str, cfg: dict) -> bool:
        """v0.3.2 P1-11: 判断文件是否为测试文件

        同时检查精确后缀(test_extensions)与命名模式(test_patterns):
        - test_extensions 精确匹配(如 "_test.py"),避免 "contest.py" 误判
        - 词边界正则(^test_ / _test. / .test. 等),避免 "contest"/"protest" 误判
        """
        import re as _re

        lower = filename.lower()
        test_exts = cfg.get("test_extensions")
        if test_exts and lower.endswith(tuple(test_exts)):
            return True
        patterns = cfg.get("test_patterns", ["test"])
        for p in patterns:
            p_lower = p.lower()
            if p_lower.startswith(".") or p_lower.endswith("."):
                # 中缀模式(如 ".spec."):要求两侧都是分隔符
                if p_lower in lower:
                    return True
            elif p_lower.startswith("_") or p_lower.endswith("_"):
                # 下划线模式(如 "_test"):要求前面是 _ 或开头
                if f"_{p_lower.strip('_')}" in lower or lower.startswith(p_lower.strip('_')):
                    return True
            else:
                # 裸词(如 "test"):只匹配词边界,避免 contest/protest 误判
                if _re.search(rf"(^|[_\-.])({_re.escape(p_lower)})([_\-.]|$)", lower):
                    return True
        return False

    def _check_no_test(self) -> list[RedLineViolation]:
        violations = []
        if self.git is None:
            return violations
        log = self.git.log_oneline(5)
        if not log:
            return []
        cfg = self._get_language_config()
        code_exts = cfg["code_extensions"]
        for line in log.strip().split("\n"):
            if not line.strip():
                continue
            sha = line.split()[0]
            files = self.git.diff_tree_files(sha)
            has_code = any(f.endswith(tuple(code_exts)) for f in files)
            has_test = any(self._is_test_file(f, cfg) for f in files)
            if has_code and not has_test:
                violations.append(RedLineViolation(
                    "no_test",
                    f"Commit {sha[:8]} 包含代码变更但无测试文件",
                ))
        return violations

    def _check_cross_module_import(self) -> list[RedLineViolation]:
        """检查跨模块导入违规

        P2-8: 改用正则解析 import/from 语句，仅匹配 import 的目标模块名，
        避免字符串匹配误报（如注释、字符串字面量）。
        """
        import re
        violations = []
        forbidden = self.config.modules.get("forbidden_import", [])
        if not forbidden:
            return []
        src_dir = self.root / "src"
        if not src_dir.exists():
            return []
        # 匹配 from X import Y 和 import X.Y
        import_re = re.compile(
            r"^\s*(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))"
        )
        cfg = self._get_language_config()
        code_exts = cfg["code_extensions"]
        for py_file in src_dir.rglob("*"):
            if not py_file.is_file() or not py_file.suffix in code_exts:
                continue
            try:
                content = py_file.read_text(encoding="utf-8")
            except Exception:
                continue
            for lineno, line in enumerate(content.split("\n"), 1):
                stripped = line.strip()
                # 跳过注释和空行
                if not stripped or stripped.startswith("#"):
                    continue
                m = import_re.match(line)
                if not m:
                    continue
                # 提取导入的模块路径
                module_path = m.group(1) or m.group(2)
                if not module_path:
                    continue
                # 与禁名单精确匹配（模块路径前缀命中任一禁名单）
                for pattern in forbidden:
                    clean_pattern = pattern.rstrip("/").strip()
                    if not clean_pattern:
                        continue
                    # 将"service/" 转成模块路径 "service"
                    target = clean_pattern.rstrip("/").replace("/", ".")
                    if module_path == target or module_path.startswith(target + "."):
                        violations.append(RedLineViolation(
                            "cross_module_import",
                            f"{py_file.relative_to(self.root)}:{lineno}: "
                            f"import {module_path}（匹配禁令 '{pattern}'）",
                        ))
        return violations

    def _check_huge_pr(self) -> list[RedLineViolation]:
        violations = []
        if self.git is None:
            return violations
        max_files = self.config.pr_max_files
        diff_stat = self.git.diff_stat("HEAD~1")
        if not diff_stat:
            return []
        lines = [l for l in diff_stat.split("\n") if l.strip()]
        if len(lines) > 1:
            file_count = len(lines) - 1
            if file_count > max_files:
                violations.append(RedLineViolation(
                    "huge_pr",
                    f"变更文件数 {file_count} 超过阈值 {max_files}",
                ))
        return violations

    def _check_uncommitted_bulk(self) -> list[RedLineViolation]:
        violations = []
        if self.git is None:
            return violations
        status = self.git.status()
        changed = [l for l in status.split("\n") if l.strip()]
        if len(changed) > 20:
            violations.append(RedLineViolation(
                "uncommitted_bulk",
                f"未提交文件数 {len(changed)} 超过 20",
            ))
        return violations

    def _check_main_incomplete(self) -> list[RedLineViolation]:
        violations = []
        if self.git is None:
            return violations
        branch = self.git.current_branch()
        if branch in ("main", "master"):
            violations.append(RedLineViolation(
                "main_incomplete",
                "当前在 main/master 分支上，建议在特性分支上开发",
            ))
        return violations

    def _check_skip_phase(self) -> list[RedLineViolation]:
        """v0.3.1-r2 P1-5: stub 改为显式返回 RedLineViolation(skip=True)

        让用户看到 stub 而非"无声通过"。具体保障由状态机不可跳步机制兜底。
        """
        return [RedLineViolation(
            "skip_phase",
            "红线 'skip_phase' 在 MVP 中由状态机不可跳步机制间接保障(非自动检测)",
            skip=True,
            status=ViolationStatus.STUB,
        )]

    def _check_doc_drift(self) -> list[RedLineViolation]:
        """v0.3.1-r2 P1-5: stub 显式返回"""
        return [RedLineViolation(
            "doc_drift",
            "红线 'doc_drift' 缺少自动检测实现(v0.4 补 AST 级检查)",
            skip=True,
            status=ViolationStatus.STUB,
        )]

    def _check_silent_legacy(self) -> list[RedLineViolation]:
        """v0.3.1-r2 P1-5: stub 显式返回"""
        return [RedLineViolation(
            "silent_legacy",
            "红线 'silent_legacy' 缺少自动检测实现(v0.4 补静态分析)",
            skip=True,
            status=ViolationStatus.STUB,
        )]

    def _check_no_contract(self) -> list[RedLineViolation]:
        """v0.3.1-r2 P1-5: stub 显式返回"""
        return [RedLineViolation(
            "no_contract",
            "红线 'no_contract' 在 MVP 中由状态机 Stage3 门禁间接保障(非自动检测)",
            skip=True,
            status=ViolationStatus.STUB,
        )]

    def _check_human_step_auto(self) -> list[RedLineViolation]:
        """v0.3.1-r2 P1-5: stub 显式返回"""
        return [RedLineViolation(
            "human_step_auto",
            "红线 'human_step_auto' 在 MVP 中由 intake 门禁间接保障(非自动检测)",
            skip=True,
            status=ViolationStatus.STUB,
        )]
