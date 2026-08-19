"""GitPort — Git 操作抽象接口

隔离所有 git 命令调用。引擎和审计器通过此接口操作 git，不直接调 subprocess。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

import subprocess


class GitPort(ABC):
    """Git 操作抽象接口"""

    @abstractmethod
    def status(self) -> str:
        """返回 git status --porcelain 输出"""

    @abstractmethod
    def add_and_commit(self, message: str) -> Optional[str]:
        """执行 git add -A && git commit，返回 SHA 或 None"""

    @abstractmethod
    def diff_stat(self, ref: str = "HEAD~1") -> str:
        """返回 git diff --stat <ref> 输出"""

    @abstractmethod
    def log_oneline(self, count: int = 5) -> str:
        """返回 git log --oneline -<count> 输出"""

    @abstractmethod
    def diff_tree_files(self, sha: str) -> list[str]:
        """返回指定 commit 变更的文件列表"""

    @abstractmethod
    def current_branch(self) -> Optional[str]:
        """返回当前分支名"""


class SystemGitPort(GitPort):
    """基于 subprocess 的 Git 实现"""

    def __init__(self, cwd: Path):
        self._cwd = cwd

    def _run(self, args: list[str]) -> subprocess.CompletedProcess:
        return subprocess.run(
            args, cwd=self._cwd, capture_output=True, text=True,
        )

    def status(self) -> str:
        try:
            result = self._run(["git", "status", "--porcelain"])
            return result.stdout.strip()
        except FileNotFoundError:
            return ""

    def add_and_commit(self, message: str) -> Optional[str]:
        try:
            self._run(["git", "add", "-A"])
            result = self._run(["git", "commit", "-m", message])
            if result.returncode != 0:
                return None
            sha_result = self._run(["git", "rev-parse", "HEAD"])
            return sha_result.stdout.strip() if sha_result.returncode == 0 else None
        except FileNotFoundError:
            return None

    def diff_stat(self, ref: str = "HEAD~1") -> str:
        try:
            result = self._run(["git", "diff", "--stat", ref])
            return result.stdout.strip() if result.returncode == 0 else ""
        except FileNotFoundError:
            return ""

    def log_oneline(self, count: int = 5) -> str:
        try:
            result = self._run(["git", "log", "--oneline", f"-{count}"])
            return result.stdout.strip() if result.returncode == 0 else ""
        except FileNotFoundError:
            return ""

    def diff_tree_files(self, sha: str) -> list[str]:
        try:
            result = self._run(["git", "diff-tree", "--no-commit-id", "--name-only", "-r", sha])
            return [f for f in result.stdout.strip().split("\n") if f] if result.returncode == 0 else []
        except FileNotFoundError:
            return []

    def current_branch(self) -> Optional[str]:
        try:
            result = self._run(["git", "branch", "--show-current"])
            return result.stdout.strip() if result.returncode == 0 else None
        except FileNotFoundError:
            return None
