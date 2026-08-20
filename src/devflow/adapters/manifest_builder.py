"""Skill manifest 自动派生器（v0.3 INDEX 教训根治）

v0.3 纪律（C3 阶段）：
- 单一真相源 = cli.py（typer.Typer）
- 禁止手写 manifest
- 自动派生 = 同步保证零漂移
"""
from __future__ import annotations

import inspect
from typing import Any, get_type_hints

import typer

from ..util.json_schema import python_type_to_json_schema, is_recognized_type
from .manifest import SkillArg, SkillManifest


def build_manifests_from_cli(app: typer.Typer) -> list[SkillManifest]:
    """从 typer app 自动派生 manifest（v0.3 INDEX 教训：禁止手写）

    Args:
        app: typer.Typer 实例（如 devflow.cli.app）

    Returns:
        每个 CLI 命令对应一个 SkillManifest

    Examples:
        >>> from devflow.cli import app
        >>> manifests = build_manifests_from_cli(app)
        >>> len(manifests)  # 24 个命令
        24
    """
    manifests: list[SkillManifest] = []

    # typer.Typer.registered_commands 是 list[CommandInfo]
    for cmd_info in app.registered_commands:
        # 1. docstring 第一行作为 description
        docstring = inspect.getdoc(cmd_info.callback) or ""
        description = docstring.split("\n")[0].strip() if docstring else ""

        # 2. 参数签名 → args 列表
        sig = inspect.signature(cmd_info.callback)
        try:
            hints = get_type_hints(cmd_info.callback)
        except Exception:
            hints = {}

        args: list[SkillArg] = []
        for p in sig.parameters.values():
            hint = hints.get(p.name, str)
            arg_type = python_type_to_json_schema(hint)
            # v0.3.4 #39: 类型降级时 warning（未注册类型 → string）
            if arg_type == "string" and not is_recognized_type(hint):
                import warnings
                warnings.warn(
                    f"参数 {cmd_info.name or cmd_info.callback.__name__}."
                    f"{p.name} 的类型 {getattr(hint, '__name__', repr(hint))} "
                    f"未注册，降级为 string"
                )
            args.append(SkillArg(
                name=p.name,
                type=arg_type,
                required=p.default is inspect.Parameter.empty,
            ))

        # 3. 子命令名：@app.command(name="x") → x；否则用 callback.__name__
        #    typer 把 callback 名中的 _ 替换为 -（如 skip_task → skip-task）
        cli_name = cmd_info.name or cmd_info.callback.__name__.replace("_", "-")

        # 4. 构造 manifest
        manifests.append(SkillManifest(
            name=f"devflow.{cli_name}",
            description=description,
            args=args,
            cli_subcommand=cli_name,
        ))

    return manifests