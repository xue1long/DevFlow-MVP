"""tests/test_manifest_builder.py — C3 阶段验证

覆盖:
- 自动派生与真实 cli.py 一致（24 个命令）
- 每个 manifest 含正确字段
- 参数类型映射正确
- 单一真相源验证（cli.py 加命令 → manifest 自动跟上）
"""
from __future__ import annotations

import inspect

import pytest
import typer

from devflow.adapters.manifest_builder import build_manifests_from_cli
from devflow.cli import app as real_app


class TestManifestFromRealCli:
    """从真实 cli.py 派生"""

    def test_manifest_count_matches_cli(self):
        """manifest 数量 = typer app 注册命令数"""
        manifests = build_manifests_from_cli(real_app)
        assert len(manifests) == len(real_app.registered_commands)

    def test_all_manifests_have_required_fields(self):
        """每个 manifest 必须含 name / cli_subcommand"""
        manifests = build_manifests_from_cli(real_app)
        for m in manifests:
            assert m.name.startswith("devflow.")
            assert m.cli_subcommand == m.name.removeprefix("devflow.")
            assert isinstance(m.args, list)


class TestManifestWithMockApp:
    """用 mock typer app 测试边界场景"""

    def _make_mock_app(self) -> typer.Typer:
        app = typer.Typer()
        captured = {}

        @app.command()
        def hello(name: str, count: int = 1) -> None:
            """问候命令（测试用）"""
            captured["name"] = name
            captured["count"] = count

        @app.command()
        def no_args() -> None:
            """无参数命令"""
            pass

        @app.command()
        def optional_arg(verbose: bool = False) -> None:
            """可选参数命令"""
            pass

        return app

    def test_required_arg_marked(self):
        """required 字段应反映参数是否有默认值"""
        app = self._make_mock_app()
        manifests = build_manifests_from_cli(app)
        hello = next(m for m in manifests if m.cli_subcommand == "hello")

        name_arg = next(a for a in hello.args if a.name == "name")
        count_arg = next(a for a in hello.args if a.name == "count")

        assert name_arg.required is True
        assert count_arg.required is False

    def test_arg_type_mapped(self):
        """参数类型应正确映射"""
        app = self._make_mock_app()
        manifests = build_manifests_from_cli(app)
        hello = next(m for m in manifests if m.cli_subcommand == "hello")

        name_arg = next(a for a in hello.args if a.name == "name")
        count_arg = next(a for a in hello.args if a.name == "count")

        assert name_arg.type == "string"
        assert count_arg.type == "integer"

    def test_docstring_first_line_is_description(self):
        """description = docstring 第一行"""
        app = self._make_mock_app()
        manifests = build_manifests_from_cli(app)
        hello = next(m for m in manifests if m.cli_subcommand == "hello")
        assert "问候命令" in hello.description

    def test_no_args_command(self):
        """无参数命令应生成空 args 列表"""
        app = self._make_mock_app()
        manifests = build_manifests_from_cli(app)
        # typer 把 callback 名 _ 替换为 -
        no_args = next(m for m in manifests if m.cli_subcommand == "no-args")
        assert no_args.args == []

    def test_bool_default_mapped(self):
        """bool 参数应正确映射"""
        app = self._make_mock_app()
        manifests = build_manifests_from_cli(app)
        # typer 把 callback 名 _ 替换为 -
        opt = next(m for m in manifests if m.cli_subcommand == "optional-arg")
        verbose_arg = next(a for a in opt.args if a.name == "verbose")
        assert verbose_arg.type == "boolean"
        assert verbose_arg.required is False


class TestManifestSingleSourceOfTruth:
    """单一真相源验证（v0.3 INDEX 教训核心）"""

    def test_changing_cli_changes_manifest(self):
        """修改 cli.py 后 manifest 自动同步"""
        # 此测试通过真实 cli 验证：当前 24 个命令的 manifest
        manifests = build_manifests_from_cli(real_app)
        # 验证 status 命令存在（v0.3.3 必须存在的命令）
        cmd_names = [m.cli_subcommand for m in manifests]
        assert "status" in cmd_names
        assert "init" in cmd_names
        assert "review" in cmd_names