"""统一调用路由器（C7.2 阶段）

v0.3 约束：
- 平台差异在 detect() 层处理，调用方无感
- 优先 MCP（最轻量）→ 其次 Skill（原生集成）→ 最后 CLI（兜底）

设计：
- route_invocation() 根据当前平台 + 集成模式自动选 invoker
- 调用方只看到统一接口，不关心底层协议
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .detect import (
    IntegrationMode,
    detect_integration_mode,
    detect_platform,
)
from .invoker import CliEngineInvoker, EngineInvoker


def select_invoker(workspace_root: Path) -> EngineInvoker:
    """根据当前平台 + 集成模式自动选择 invoker

    Args:
        workspace_root: DevFlow 工作区根目录

    Returns:
        最优 EngineInvoker 实例

    路由优先级：
    1. MCP（最轻量，进程内调用）
    2. Skill（原生集成，由平台技能系统加载）
    3. CLI（兜底，subprocess 调用）

    注：当前实现只有 CliEngineInvoker；MCP/Skill invoker 待 B 阶段扩展。
    """
    platform = detect_platform()
    modes = detect_integration_mode(platform)

    # 当前唯一实现：CliEngineInvoker（C2 阶段）
    # 未来扩展：
    # - MCP 模式 → InProcessEngineInvoker（同进程 typer app）
    # - Skill 模式 → SkillInvoker（由平台技能系统加载）
    if IntegrationMode.MCP in modes:
        # MCP 模式：未来用 InProcessEngineInvoker
        # 当前 fallback 到 CLI（实现未就绪）
        pass
    elif IntegrationMode.SKILL in modes:
        # Skill 模式：未来用 SkillInvoker
        # 当前 fallback 到 CLI
        pass

    return CliEngineInvoker(workspace_root)


def route_invocation(
    skill_name: str,
    args: dict[str, Any],
    workspace_root: Path,
) -> dict[str, Any]:
    """路由到正确 invoker 执行命令

    Args:
        skill_name: 如 "devflow.review"
        args: 命令参数 dict
        workspace_root: DevFlow 工作区根目录

    Returns:
        CLI 输出 JSON dict
    """
    invoker = select_invoker(workspace_root)
    return invoker.invoke(skill_name, args)