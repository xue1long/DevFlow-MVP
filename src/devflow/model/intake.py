"""Intake / Issue — 入口议题实体"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class IntakeKind(str, Enum):
    """议题分类"""
    BUG = "bug"
    ENHANCEMENT = "enhancement"
    QUESTION = "question"
    CHORE = "chore"


class TriageState(str, Enum):
    """Triage 状态机"""
    NEEDS_TRIAGE = "needs-triage"
    NEEDS_INFO = "needs-info"
    READY_FOR_AGENT = "ready-for-agent"
    READY_FOR_HUMAN = "ready-for-human"
    WONTFIX = "wontfix"


class Intake(BaseModel):
    """入口议题

    在 Stage0 (intake) 阶段产出，判定是否进入 Stage1。
    MVP 中 intake_fast_skip=true 时自动创建 triage_state=ready-for-agent。
    """
    id: str = Field(..., description="议题 ID，格式 issue-<n>")
    kind: IntakeKind = Field(default=IntakeKind.ENHANCEMENT)
    summary: str = Field(default="", description="议题摘要")
    triage_state: TriageState = Field(default=TriageState.NEEDS_TRIAGE)
    blocked_reason: Optional[str] = Field(default=None, description="needs-info / wontfix 时的说明")
    devflow_stage: int = Field(default=0, description="入口阶段，固定为 0")

    def is_ready_for_agent(self) -> bool:
        return self.triage_state == TriageState.READY_FOR_AGENT
