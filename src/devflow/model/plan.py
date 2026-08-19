"""Plan — 计划实体"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from .task import Task


class Plan(BaseModel):
    """计划（Plan）

    包含一组 Task。MVP 中 Task 的 blocked_by 不做环检测。
    v0.3.3 思维字段（宽松默认,可选）:
      buffer  冗余思维: 缓冲比例(0-1),预留安全垫,资源不排满
    """
    spec_id: str = Field(..., description="关联的 Spec ID")
    tasks: list[Task] = Field(default_factory=list)
    domain_ref: str = Field(default="", description="指向 DomainModel 的引用")

    # v0.3.3 思维字段（可选,宽松默认）
    buffer: Optional[float] = Field(
        default=None,
        ge=0,
        le=1,
        description="v0.3.3 冗余思维: 计划预留缓冲比例(0-1),资源不排满",
    )
