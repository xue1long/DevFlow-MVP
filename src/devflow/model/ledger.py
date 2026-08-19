"""LedgerEntry — 账本条目实体"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class LedgerAction(str, Enum):
    """账本动作类型"""
    START = "start"
    ARTIFACT = "artifact"
    GATE = "gate"
    COMMIT = "commit"
    DEBUG = "debug"
    RULING = "ruling"
    TRIAGE = "triage"
    APPROVE = "approve"
    SKIP = "skip"
    SUSPEND = "suspend"
    RESUME = "resume"
    PHASE_TRANSITION = "phase_transition"
    REVIEW = "review"
    FIX = "fix"
    ESCALATE = "escalate"


class LedgerEntry(BaseModel):
    """账本条目

    每次阶段转换、门禁检查、提交等操作都写入一条。
    MVP 采用 append-only 日志写入 progress.yaml。
    """
    phase: int = Field(..., description="阶段号 0-7")
    task_id: Optional[str] = Field(default=None, description="关联的 Task ID")
    action: LedgerAction = Field(..., description="动作类型")
    commit: Optional[str] = Field(default=None, description="git SHA")
    acceptance: Optional[str] = Field(default=None, description="验收结论")
    reason: Optional[str] = Field(default=None, description="skip/ruling 时的原因")
    timestamp: datetime = Field(default_factory=datetime.now)
    details: Optional[str] = Field(default=None, description="附加信息")
