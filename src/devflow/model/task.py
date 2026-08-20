"""Task — 任务实体"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from .contract import Contract


class TaskStatus(str, Enum):
    TODO = "todo"
    CONTRACTED = "contracted"
    IMPLEMENTING = "implementing"
    VERIFYING = "verifying"
    REVIEWING = "reviewing"
    DONE = "done"
    SKIPPED = "skipped"


class TaskPriority(str, Enum):
    """v0.3.3 二八法则: 任务优先级"""
    P0 = "P0"  # 核心 20% 关键动作
    P1 = "P1"  # 常规
    P2 = "P2"  # 锦上添花


class Task(BaseModel):
    """任务（Task）

    MVP 中 blocked_by 仅作列表字段，不做环检测。
    必填字段见 MVP-门禁降级矩阵 §0.4。
    v0.3.3 思维字段（宽松默认,可选）:
      priority   二八法则:  P0/P1/P2
      owner_skill 能力圈: 擅长/短板标注(learn/collab 表示圈外需协作)
    """
    id: str = Field(
        ...,
        pattern=r"^([a-zA-Z0-9_-]+|task-\d+)$",
        description="Task ID，建议格式 task-<n>（短字母数字也可，用于 DAG 测试）",
    )
    title: str = Field(..., min_length=1)
    module: str = Field(..., min_length=1, description="单任务只改一个模块")
    blocked_by: list[str] = Field(default_factory=list, description="前置任务 ID（MVP 不做环检测）")
    is_tracer_bullet: bool = Field(default=False)
    contract: Optional[Contract] = Field(default=None, description="Stage3 产出后填入")
    acceptance: list[str] = Field(..., min_length=1, description="验收标准，至少 1 项")
    status: TaskStatus = Field(default=TaskStatus.TODO)
    commits: list[str] = Field(default_factory=list, description="关联 commit SHA")
    wide_refactor: bool = Field(default=False)

    @field_validator("acceptance")
    @classmethod
    def acceptance_items_non_empty(cls, v: list[str]) -> list[str]:
        for item in v:
            if not item.strip():
                raise ValueError("acceptance 中每项不能为空")
        return v

    # v0.3.3 思维字段（全部可选,宽松默认）
    priority: TaskPriority = Field(
        default=TaskPriority.P1,
        description="v0.3.3 二八法则: 任务优先级(P0=核心关键动作)",
    )
    owner_skill: Optional[str] = Field(
        default=None,
        description="v0.3.3 能力圈: 擅长领域标注; 'learn'/'collab' 表示圈外需学习或协作",
    )

    def can_skip(self) -> bool:
        """是否允许 skip（仅 todo 或 contracted 状态）"""
        return self.status in (TaskStatus.TODO, TaskStatus.CONTRACTED)
