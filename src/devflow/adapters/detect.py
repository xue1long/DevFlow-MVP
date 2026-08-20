"""平台探测（C7.1 阶段）

v0.3 约束：
- 平台差异在 detect() 层处理，调用方无感（架构文档 §7）
- 不在适配层加业务逻辑（v3 纪律）

设计：
- detect_platform() 通过环境变量探测当前 Agent 平台
- detect_integration_mode() 返回平台支持的集成模式集合
- 调用方根据 (platform, mode) 路由到正确 invoker
"""
from __future__ import annotations

import os
from enum import Enum


class Platform(Enum):
    """支持的 Agent 平台"""
    CLAUDE_CODE = "claude-code"
    WORKBUDDY = "workbuddy"
    CODEBUDDY = "codebuddy"
    MCP_HOST = "mcp-host"
    CLI = "cli"


class IntegrationMode(Enum):
    """集成模式"""
    SKILL = "skill"
    COMMAND = "command"
    HOOK = "hook"
    MCP = "mcp"


# 平台 → 集成模式映射
# 参考架构文档 §6/§7
_PLATFORM_MODES: dict[Platform, set[IntegrationMode]] = {
    Platform.CLAUDE_CODE: {IntegrationMode.SKILL, IntegrationMode.HOOK},
    Platform.WORKBUDDY: {IntegrationMode.SKILL, IntegrationMode.MCP},
    Platform.CODEBUDDY: {IntegrationMode.SKILL, IntegrationMode.COMMAND},
    Platform.MCP_HOST: {IntegrationMode.MCP},
    Platform.CLI: {IntegrationMode.COMMAND},
}


def detect_platform() -> Platform:
    """运行时探测当前 Agent 平台

    探测信号优先级（环境变量）：
    1. $CLAUDE_CODE → CLAUDE_CODE
    2. $WORKBUDDY_RUNTIME → WORKBUDDY
    3. $CODEBUDDY_RUNTIME → CODEBUDDY
    4. parent process 是 mcp_host → MCP_HOST
    5. else → CLI

    Returns:
        当前 Agent 平台（默认 CLI）
    """
    if os.environ.get("CLAUDE_CODE"):
        return Platform.CLAUDE_CODE
    if os.environ.get("WORKBUDDY_RUNTIME"):
        return Platform.WORKBUDDY
    if os.environ.get("CODEBUDDY_RUNTIME"):
        return Platform.CODEBUDDY
    # MCP Host 探测：检查父进程（简化版：检查 DEVFLOW_MCP_HOST 环境变量）
    if os.environ.get("DEVFLOW_MCP_HOST"):
        return Platform.MCP_HOST
    return Platform.CLI


def detect_integration_mode(platform: Platform) -> set[IntegrationMode]:
    """探测平台支持的集成模式

    Args:
        platform: 平台枚举

    Returns:
        平台支持的集成模式集合（架构文档 §6 平台能力矩阵）
    """
    return _PLATFORM_MODES.get(platform, {IntegrationMode.COMMAND})


def is_mcp_callable(platform: Platform) -> bool:
    """是否支持 MCP 集成"""
    return IntegrationMode.MCP in detect_integration_mode(platform)


def is_skill_callable(platform: Platform) -> bool:
    """是否支持 Skill 集成"""
    return IntegrationMode.SKILL in detect_integration_mode(platform)