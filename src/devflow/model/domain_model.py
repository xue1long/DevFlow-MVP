"""DomainModel — 领域模型 / 共享语言实体"""
from __future__ import annotations

from pydantic import BaseModel, Field


class DomainModel(BaseModel):
    """领域模型（DomainModel）

    MVP 仅 CONTEXT.md 骨架，不含 ADR 维护。
    """
    glossary_path: str = Field(default="CONTEXT.md", description="项目领域术语表路径")
    adrs: list[str] = Field(default_factory=list, description="ADR 文件路径列表（MVP 为空）")
    updated_by: list[str] = Field(default_factory=list, description="写入方能力列表")
