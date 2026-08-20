"""Git worktree 隔离（B7.1 阶段）

v0.3 B 类补强：
- DispatchConfig.worktree_per_task 已存在，但未真正接线
- SDD 并行 frontier 时，多 task 共享文件系统会产生竞争
- worktree 隔离让每个 task 独立 git 分支 + 独立工作目录

边界条件：
- 非 git 仓库 → 降级为目录（仅 mkdir）
- 分支已存在 → fallback 到 `git worktree add` 而非 `-b`
- plan_id 含特殊字符 → safe_id() 处理
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path


def safe_id(plan_id: str) -> str:
    """把 plan_id 转成 git 分支安全的 ID

    Git 分支名规则：
    - 不能含空格、冒号、波浪号等特殊字符
    - 不能以 . 开头
    - 不能以 - 结尾
    - 不能含 .. 等
    """
    safe = re.sub(r"[^a-z0-9-]", "-", plan_id.lower())
    safe = re.sub(r"-+", "-", safe).strip("-")
    return safe or "default"


def create_worktree_for_plan(plan_id: str, root: Path) -> Path:
    """为 Plan 创建隔离 worktree

    Args:
        plan_id: Plan ID（含特殊字符时自动 safe_id 处理）
        root: 主仓库根目录（必须含 .git/）

    Returns:
        worktree 路径（root/workspaces/<safe_id>/）

    边界处理：
    - root/.git 不存在 → 降级创建目录
    - 分支已存在 → 用 git worktree add 而非 -b
    - git 命令失败 → 抛 subprocess.CalledProcessError
    """
    safe = safe_id(plan_id)
    branch = f"plan/{safe}"
    worktree_path = root / "workspaces" / safe

    # 非 git 仓库 → 仅创建目录
    if not (root / ".git").exists():
        worktree_path.mkdir(parents=True, exist_ok=True)
        return worktree_path

    # 检查分支是否已存在
    existing = subprocess.run(
        ["git", "branch", "--list", branch],
        capture_output=True,
        text=True,
        cwd=root,
    ).stdout.strip()

    if not existing:
        # 分支不存在 → 创建新分支
        subprocess.run(
            ["git", "worktree", "add", "-b", branch, str(worktree_path)],
            check=True,
            cwd=root,
        )
    else:
        # 分支已存在 → attach 到现有分支
        subprocess.run(
            ["git", "worktree", "add", str(worktree_path), branch],
            check=True,
            cwd=root,
        )

    return worktree_path