"""GitPort — Git 操作抽象接口

隔离所有 git 命令调用。引擎和审计器通过此接口操作 git，不直接调 subprocess。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

import subprocess
import fnmatch

# P0-8: 敏感文件模式——git add -A 前应阻止提交这些文件
SENSITIVE_PATTERNS = [
    ".env", ".env.*", "*.pem", "*.key", "id_rsa", "id_ed25519",
    "credentials*", "secrets*", "*.secret", "token*", "*.p12",
    "*.log", "*.tmp", "*.swp", ".DS_Store", "history.txt",
    "progress.yaml.lock",  # 锁文件不应入库
]


class GitPort(ABC):
    """Git 操作抽象接口"""

    @abstractmethod
    def status(self) -> str:
        """返回 git status --porcelain 输出"""

    @abstractmethod
    def add_and_commit(self, message: str) -> Optional[str]:
        """执行 git add -A && git commit，返回 SHA 或 None
        Raises: RuntimeError 当敏感文件被阻止提交时
        """

    @abstractmethod
    def check_sensitive_files(self, status_output: str) -> list[str]:
        """检查 status 输出中是否有敏感文件模式"""

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
            # P0-8: 检查敏感文件
            status = self.status()
            sensitive_found = self._check_sensitive_files(status)
            if sensitive_found:
                raise RuntimeError(
                    f"以下敏感文件将被提交，已阻止:\n" +
                    "\n".join(f"  - {f}" for f in sensitive_found) +
                    "\n请将敏感文件加入 .gitignore 后重试"
                )
            self._run(["git", "add", "-A"])
            result = self._run(["git", "commit", "-m", message])
            if result.returncode != 0:
                return None
            sha_result = self._run(["git", "rev-parse", "HEAD"])
            return sha_result.stdout.strip() if sha_result.returncode == 0 else None
        except RuntimeError:
            raise
        except FileNotFoundError:
            return None

    def check_sensitive_files(self, status_output: str) -> list[str]:
        """检查 status 输出中是否有敏感文件模式（公开接口）"""
        return self._check_sensitive_files(status_output)

    def _check_sensitive_files(self, status_output: str) -> list[str]:
        """检查 git status 中是否有敏感文件"""
        if not status_output:
            return []
        found = []
        for line in status_output.split("\n"):
            line = line.strip()
            if not line:
                continue
            # git status --porcelain 格式: "XY filename"
            filename = line[3:].strip()
            for pattern in SENSITIVE_PATTERNS:
                if fnmatch.fnmatch(filename, pattern):
                    found.append(filename)
                    break
        return found

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
