"""Task — 任务实体"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from .contract import Contract


class TaskStatus(str, Enum):
    TODO = "todo"
    CONTRACTED = "contracted"
    IMPLEMENTING = "implementing"
    VERIFYING = "verifying"
    REVIEWING = "reviewing"
    DONE = "done"
    SKIPPED = "skipped"


class Task(BaseModel):
    """任务（Task）

    MVP 中 blocked_by 仅作列表字段，不做环检测。
    必填字段见 MVP-门禁降级矩阵 §0.4。
    """
    id: str = Field(..., description="Task ID，格式 task-<n>")
    title: str = Field(..., min_length=1)
    module: str = Field(..., min_length=1, description="单任务只改一个模块")
    blocked_by: list[str] = Field(default_factory=list, description="前置任务 ID（MVP 不做环检测）")
    is_tracer_bullet: bool = Field(default=False)
    contract: Optional[Contract] = Field(default=None, description="Stage3 产出后填入")
    acceptance: list[str] = Field(..., min_length=1, description="验收标准，至少 1 项")
    status: TaskStatus = Field(default=TaskStatus.TODO)
    commits: list[str] = Field(default_factory=list, description="关联 commit SHA")
    wide_refactor: bool = Field(default=False)

    def can_skip(self) -> bool:
        """是否允许 skip（仅 todo 或 contracted 状态）"""
        return self.status in (TaskStatus.TODO, TaskStatus.CONTRACTED)
