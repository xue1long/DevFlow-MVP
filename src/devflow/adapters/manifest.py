"""DevFlow Skill Manifest 数据模型

v0.3 纪律（C3 阶段）：
- 禁止手写 manifest —— 必须从 cli.py 自动派生
- Manifest 是 Pydantic schema，不是裸 dict
- 与 Claude Code Skill / WorkBuddy Skill / MCP 工具对齐的中间表示
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class SkillArg(BaseModel):
    """manifest 单个参数"""
    name: str
    type: str  # "string" | "integer" | "boolean" | "number"
    description: str = ""
    required: bool = True


class SkillManifest(BaseModel):
    """单个 Skill manifest

    每条 CLI 命令对应一个 SkillManifest；适配层负责把这份 manifest
    翻译成各宿主平台原生的 manifest 格式。
    """
    name: str  # 如 "devflow.review"
    description: str = ""  # LLM 用的工具描述
    args: list[SkillArg] = Field(default_factory=list)
    cli_subcommand: str  # 对应 `devflow <cli_subcommand> [args...]`