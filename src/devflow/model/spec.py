"""Spec — 方案实体"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class SpecStatus(str, Enum):
    DRAFT = "draft"
    APPROVED = "approved"
    ARCHIVED = "archived"  # v0.3 第一性方案：标记已完成/已取消的 Spec


class Spec(BaseModel):
    """方案（Spec）

    必填字段见 MVP-门禁降级矩阵 §0.1。
    v0.3.3 思维字段（宽松默认,可选）:
      assumptions  第一性原理: 底层假设清单
      premortem    逆向思维:   事前验尸——"这个方案最可能怎么失败"
      tradeoff     损益思维:   决策时放弃了什么(机会成本)
    """
    id: str = Field(..., description="Spec ID，如 20260819-pipeline-batch-retry")
    title: str = Field(..., min_length=1)
    problem: str = Field(..., min_length=10, description="要解决的问题，≥10 字符")
    goals: list[str] = Field(..., min_length=1, description="目标列表，每项非空")
    non_goals: list[str] = Field(..., min_length=1, description="明确不做，至少 1 项")
    options: list = Field(default_factory=list)
    decision: Optional[str] = Field(default=None)
    affected_modules: list[str] = Field(default_factory=list)
    contracts: list = Field(default_factory=list)
    status: SpecStatus = Field(default=SpecStatus.DRAFT)

    # v0.3.3 思维字段（全部可选,宽松默认,有值才检查）
    assumptions: list[str] = Field(
        default_factory=list,
        description="第一性原理: 底层事实/假设清单,goals 应基于这些",
    )
    premortem: list[str] = Field(
        default_factory=list,
        description="逆向思维: 事前验尸——这个方案最可能怎么失败",
    )
    tradeoff: Optional[str] = Field(
        default=None,
        description="损益思维: 决策时放弃了什么(机会成本记录)",
    )

    @field_validator("goals")
    @classmethod
    def goals_items_non_empty(cls, v: list[str]) -> list[str]:
        for item in v:
            if not item.strip():
                raise ValueError("goals 中每项不能为空")
        return v

    @field_validator("non_goals")
    @classmethod
    def non_goals_items_non_empty(cls, v: list[str]) -> list[str]:
        for item in v:
            if not item.strip():
                raise ValueError("non_goals 中每项不能为空")
        return v

    def missing_required_fields(self) -> list[str]:
        """返回缺失的必填字段列表（用于 approve 校验）"""
        missing: list[str] = []
        if not self.title.strip():
            missing.append("title")
        if not self.problem.strip() or len(self.problem.strip()) < 10:
            missing.append("problem (≥10 字符)")
        if not self.goals or any(not g.strip() for g in self.goals):
            missing.append("goals (非空列表)")
        if not self.non_goals or any(not g.strip() for g in self.non_goals):
            missing.append("non_goals (至少 1 项)")
        return missing
