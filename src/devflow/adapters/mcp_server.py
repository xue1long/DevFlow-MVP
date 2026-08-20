"""DevFlow MCP Server（B1.2 阶段）

把 DevFlow 引擎暴露为标准 MCP Server，覆盖任意 MCP Host
（Claude Desktop / Cursor / Continue.dev 等）。

启动: devflow-mcp-server
协议: MCP stdio
依赖: pip install 'devflow[mcp]'

v0.3 纪律：
- Skill manifest 必须从 cli.py 自动派生（v0.3 INDEX 教训）
- 适配层不实现业务逻辑，只做协议转换
- EngineInvoker 抽象统一调用面（C2 阶段基础）
"""
from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any

import typer

from .invoker import EngineInvoker, InProcessEngineInvoker
from .manifest import SkillArg, SkillManifest
from .manifest_builder import build_manifests_from_cli


def _build_tool_fn(manifest: SkillManifest, invoker: EngineInvoker):
    """把 manifest 转成 MCP tool 函数

    用 type() 动态创建带正确参数签名的函数（MCP 要求参数声明）。
    """
    import asyncio

    annotations: dict[str, Any] = {}
    defaults: list = []
    params: list[inspect.Parameter] = []

    for arg in manifest.args:
        # 类型映射回 Python
        py_type = {
            "string": str,
            "integer": int,
            "boolean": bool,
            "number": float,
        }.get(arg.type, str)

        annotations[arg.name] = py_type

        if not arg.required:
            defaults.append(None)

        params.append(
            inspect.Parameter(
                name=arg.name,
                kind=inspect.Parameter.POSITIONAL_OR_KEYWORD,
                annotation=py_type,
                default=None if not arg.required else inspect.Parameter.empty,
            )
        )

    async def tool_fn(**kwargs) -> dict[str, Any]:
        """动态生成的 MCP tool 函数"""
        # 过滤掉 None 参数（未提供时）
        filtered = {k: v for k, v in kwargs.items() if v is not None}
        return await asyncio.to_thread(invoker.invoke, manifest.name, filtered)

    # 重建函数签名供 fastmcp 反射
    tool_fn.__signature__ = inspect.Signature(parameters=params)
    tool_fn.__annotations__ = annotations
    tool_fn.__name__ = manifest.cli_subcommand.replace("-", "_")
    tool_fn.__doc__ = manifest.description or f"DevFlow {manifest.cli_subcommand}"

    return tool_fn


def create_server(invoker: EngineInvoker, manifests: list[SkillManifest]):
    """创建 MCP Server 实例

    Args:
        invoker: 引擎调用入口（C2 EngineInvoker 抽象）
        manifests: Skill 清单（C3 自动派生）
    """
    # fastmcp 是 optional 依赖，延迟导入以便无 fastmcp 时也能用其他 invoker
    from fastmcp import FastMCP  # type: ignore[import-not-found]

    mcp = FastMCP(
        "devflow",
        instructions="DevFlow 工作流引擎：8 阶段状态机、双轴评审、append-only 账本",
    )

    for manifest in manifests:
        tool_fn = _build_tool_fn(manifest, invoker)
        # fastmcp v3: 直接传函数，由 fastmcp 反射签名
        mcp.add_tool(tool_fn, name=manifest.name)

    return mcp


def main() -> None:
    """MCP Server 入口（devflow-mcp-server）"""
    from ..cli import app as devflow_app

    invoker = InProcessEngineInvoker(devflow_app, Path.cwd())
    manifests = build_manifests_from_cli(devflow_app)
    server = create_server(invoker, manifests)
    server.run(transport="stdio")


if __name__ == "__main__":
    main()