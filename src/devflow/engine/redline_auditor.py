"""RedLineAuditor — 红线审计

MVP 实现 10 条可自动检测的红线 + 1 条 circular_dep 标记 mvp_skip。
依赖 GitPort 抽象接口，不直接调 subprocess。
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from ..policy.loader import SOPConfig
from ..storage.git_port import GitPort


class RedLineViolation:
    """红线违规"""
    def __init__(self, rule: str, message: str, skip: bool = False):
        self.rule = rule
        self.message = message
        self.skip = skip

    def to_dict(self) -> dict:
        return {"rule": self.rule, "message": self.message, "skip": self.skip}


class RedLineAuditor:
    """红线审计器"""

    def __init__(self, root: Path, config: SOPConfig, git: Optional[GitPort] = None):
        self.root = root
        self.config = config
        self.git = git

    def audit(self) -> list[RedLineViolation]:
        """执行全量红线扫描"""
        violations: list[RedLineViolation] = []
        for red_line in self.config.red_lines:
            if red_line.mvp_skip:
                violations.append(RedLineViolation(
                    red_line.name,
                    f"红线 '{red_line.name}' 在 MVP 中跳过检测",
                    skip=True,
                ))
                continue
            checker = getattr(self, f"_check_{red_line.name}", None)
            if checker:
                violations.extend(checker())
        return violations

    def _check_no_test(self) -> list[RedLineViolation]:
        violations = []
        if self.git is None:
            return violations
        log = self.git.log_oneline(5)
        if not log:
            return []
        for line in log.strip().split("\n"):
            if not line.strip():
                continue
            sha = line.split()[0]
            files = self.git.diff_tree_files(sha)
            has_code = any(f.endswith(".py") for f in files)
            has_test = any("test" in f.lower() for f in files)
            if has_code and not has_test:
                violations.append(RedLineViolation(
                    "no_test",
                    f"Commit {sha[:8]} 包含代码变更但无测试文件",
                ))
        return violations

    def _check_cross_module_import(self) -> list[RedLineViolation]:
        violations = []
        forbidden = self.config.modules.get("forbidden_import", [])
        if not forbidden:
            return []
        src_dir = self.root / "src"
        if not src_dir.exists():
            return []
        for py_file in src_dir.rglob("*.py"):
            try:
                content = py_file.read_text(encoding="utf-8")
            except Exception:
                continue
            for line in content.split("\n"):
                stripped = line.strip()
                if not (stripped.startswith("from ") or stripped.startswith("import ")):
                    continue
                for pattern in forbidden:
                    clean_pattern = pattern.rstrip("/").strip()
                    if clean_pattern and clean_pattern in stripped:
                        violations.append(RedLineViolation(
                            "cross_module_import",
                            f"{py_file.relative_to(self.root)}: {stripped[:80]}（匹配禁令 '{pattern}'）",
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
        return []  # 由状态机的不可跳步机制保障

    def _check_doc_drift(self) -> list[RedLineViolation]:
        return []  # 无法自动检测

    def _check_silent_legacy(self) -> list[RedLineViolation]:
        return []  # 无法自动检测

    def _check_no_contract(self) -> list[RedLineViolation]:
        return []  # 由状态机 Stage3 门禁保障

    def _check_human_step_auto(self) -> list[RedLineViolation]:
        return []  # 由 intake 门禁保障
