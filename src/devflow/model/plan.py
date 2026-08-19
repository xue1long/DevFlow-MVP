"""Plan — 计划实体"""
from __future__ import annotations

from pydantic import BaseModel, Field

from .task import Task


class Plan(BaseModel):
    """计划（Plan）

    包含一组 Task。MVP 中 Task 的 blocked_by 不做环检测。
    """
    spec_id: str = Field(..., description="关联的 Spec ID")
    tasks: list[Task] = Field(default_factory=list)
    domain_ref: str = Field(default="", description="指向 DomainModel 的引用")
