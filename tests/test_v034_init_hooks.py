"""v0.3.4 集成验证测试

锁定 devflow init 集成 graphify hooks 的行为：
- init 命令带 --no-graphify-hook 选项
- _try_install_graphify_hooks: graphify 可用 → 调用 hook install
- _try_install_graphify_hooks: graphify 不可用 → 返回提示不抛错
- _try_install_graphify_hooks: graphify 调用失败 → 返回错误信息不抛错
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from devflow.cli import _try_install_graphify_hooks


@pytest.fixture
def git_repo(tmp_path):
    """初始化一个 git 仓库(tmp_path),用于需要 .git 的测试"""
    import subprocess
    subprocess.run(["git", "init", str(tmp_path)], capture_output=True, check=True)
    return tmp_path


def test_graphify_hooks_installed_when_cli_available(git_repo, monkeypatch):
    """v0.3.4: graphify 可用时, init 调用 hook install 并返回 ok"""
    import subprocess as sp

    calls = []

    def fake_which(name):
        assert name == "graphify"
        return "/fake/graphify"

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        class R:
            returncode = 0
            stdout = "post-commit: installed"
            stderr = ""
        return R()

    monkeypatch.setattr("shutil.which", fake_which)
    monkeypatch.setattr("subprocess.run", fake_run)

    result = _try_install_graphify_hooks(git_repo)
    assert result["ok"] is True
    assert calls == [["/fake/graphify", "hook", "install"]]


def test_graphify_hooks_skipped_when_cli_missing(git_repo, monkeypatch):
    """v0.3.4: graphify 不可用时返回提示,不抛错"""
    monkeypatch.setattr("shutil.which", lambda name: None)
    result = _try_install_graphify_hooks(git_repo)
    assert result["ok"] is False
    assert "未检测到 graphify" in result["message"]


def test_graphify_hooks_error_handled_when_install_fails(git_repo, monkeypatch):
    """v0.3.4: hook install 失败时返回错误信息,不抛错"""
    def fake_which(name):
        return "/fake/graphify"

    def fake_run(cmd, **kwargs):
        class R:
            returncode = 1
            stdout = ""
            stderr = "boom: something failed"
        return R()

    monkeypatch.setattr("shutil.which", fake_which)
    monkeypatch.setattr("subprocess.run", fake_run)

    result = _try_install_graphify_hooks(git_repo)
    assert result["ok"] is False
    assert "boom" in result["message"]


def test_graphify_hooks_exception_handled(git_repo, monkeypatch):
    """v0.3.4: 调用异常时返回错误信息,不抛错"""
    def fake_which(name):
        return "/fake/graphify"

    def fake_run(cmd, **kwargs):
        raise RuntimeError("graphify crashed")

    monkeypatch.setattr("shutil.which", fake_which)
    monkeypatch.setattr("subprocess.run", fake_run)

    result = _try_install_graphify_hooks(git_repo)
    assert result["ok"] is False
    assert "graphify crashed" in result["message"]


def test_graphify_hooks_skipped_when_not_git_repo(tmp_path, monkeypatch):
    """v0.3.4: 非 git 仓库时提示 git init,不抛错、不调用 graphify"""
    called = []

    def fake_which(name):
        return "/fake/graphify"

    def fake_run(cmd, **kwargs):
        called.append(cmd)
        return None

    monkeypatch.setattr("shutil.which", fake_which)
    monkeypatch.setattr("subprocess.run", fake_run)

    # tmp_path 默认不是 git 仓库
    result = _try_install_graphify_hooks(tmp_path)
    assert result["ok"] is False
    assert "不是 git 仓库" in result["message"]
    assert called == [], "非 git 仓库不应调用 graphify"


def test_init_has_no_graphify_hook_option():
    """v0.3.4: init 命令应支持 --no-graphify-hook 选项"""
    import inspect
    from devflow.cli import init
    sig = inspect.signature(init)
    assert "no_graphify_hook" in sig.parameters, \
        f"init 应有 no_graphify_hook 参数,实际: {list(sig.parameters)}"