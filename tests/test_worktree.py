"""tests/test_worktree.py — B7.1 阶段验证

覆盖:
- safe_id 处理特殊字符（/、空格、..等）
- 非 git 仓库降级为目录
- git worktree add 新建分支（mock subprocess）
- 分支已存在 fallback（mock subprocess）
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from devflow.engine.worktree import create_worktree_for_plan, safe_id


class TestSafeId:
    """safe_id 特殊字符处理"""

    def test_simple_id(self):
        assert safe_id("plan-1") == "plan-1"

    def test_uppercase_lowercased(self):
        assert safe_id("PLAN-1") == "plan-1"

    def test_slash_replaced(self):
        assert safe_id("plan/2024/spec") == "plan-2024-spec"

    def test_spaces_replaced(self):
        assert safe_id("plan 1") == "plan-1"

    def test_special_chars_replaced(self):
        """冒号、波浪号、问号等"""
        assert safe_id("plan:1?v2~draft") == "plan-1-v2-draft"

    def test_empty_fallback(self):
        assert safe_id("...") == "default"
        assert safe_id("///") == "default"

    def test_consecutive_dashes_collapsed(self):
        assert safe_id("plan---1") == "plan-1"

    def test_leading_trailing_dashes_stripped(self):
        assert safe_id("-plan-1-") == "plan-1"


class TestCreateWorktreeForPlan:
    """create_worktree_for_plan 边界条件"""

    def test_non_git_repo_creates_directory(self, tmp_path: Path):
        """非 git 仓库 → 仅创建目录，不调 git"""
        with patch("subprocess.run") as mock_run:
            # 即使 subprocess.run 不被调也通过
            result = create_worktree_for_plan("plan-1", tmp_path)
            assert result == tmp_path / "workspaces" / "plan-1"
            assert result.exists()
            mock_run.assert_not_called()

    def test_git_repo_new_branch(self, tmp_path: Path):
        """git 仓库 + 分支不存在 → git worktree add -b"""
        # 模拟 .git 目录
        (tmp_path / ".git").mkdir()

        with patch("subprocess.run") as mock_run:
            # 第一次调用：git branch --list 返回空
            # 第二次调用：git worktree add -b
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout="", stderr=""),  # branch --list
                MagicMock(returncode=0, stdout="", stderr=""),  # worktree add -b
            ]

            result = create_worktree_for_plan("plan-1", tmp_path)

            assert result == tmp_path / "workspaces" / "plan-1"
            assert mock_run.call_count == 2
            # 第二次调用应是 git worktree add -b
            second_call = mock_run.call_args_list[1]
            assert second_call.args[0][0] == "git"
            assert second_call.args[0][1] == "worktree"
            assert second_call.args[0][2] == "add"
            assert second_call.args[0][3] == "-b"
            assert "plan/plan-1" in second_call.args[0]
            # 路径以 workspaces/plan-1 结尾（跨平台）
            last_arg = str(second_call.args[0][-1])
            assert last_arg.endswith("workspaces" + str(Path("/") / "plan-1")) or \
                   last_arg.endswith("workspaces\\plan-1")

    def test_git_repo_existing_branch(self, tmp_path: Path):
        """git 仓库 + 分支已存在 → git worktree add（无 -b）"""
        (tmp_path / ".git").mkdir()

        with patch("subprocess.run") as mock_run:
            # 第一次：git branch --list 返回分支名（已存在）
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout="  plan/plan-1\n", stderr=""),
                MagicMock(returncode=0, stdout="", stderr=""),
            ]

            create_worktree_for_plan("plan-1", tmp_path)

            # 第二次调用应是 git worktree add（不带 -b）
            second_call = mock_run.call_args_list[1]
            assert "worktree" in second_call.args[0]
            assert "add" in second_call.args[0]
            assert "-b" not in second_call.args[0]

    def test_special_chars_in_plan_id(self, tmp_path: Path):
        """plan_id 含特殊字符 → safe_id 处理后路径正确"""
        (tmp_path / ".git").mkdir()

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout="", stderr=""),
                MagicMock(returncode=0, stdout="", stderr=""),
            ]

            result = create_worktree_for_plan("Plan/2024/Q1", tmp_path)
            # safe_id: "plan-2024-q1"
            assert result == tmp_path / "workspaces" / "plan-2024-q1"

    def test_git_failure_raises(self, tmp_path: Path):
        """git worktree add 失败应抛 subprocess.CalledProcessError"""
        (tmp_path / ".git").mkdir()

        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = [
                MagicMock(returncode=0, stdout="", stderr=""),  # branch --list
                subprocess.CalledProcessError(
                    returncode=128,
                    cmd=["git", "worktree", "add"],
                    stderr="fatal: bad revision",
                ),
            ]
            with pytest.raises(subprocess.CalledProcessError):
                create_worktree_for_plan("plan-1", tmp_path)