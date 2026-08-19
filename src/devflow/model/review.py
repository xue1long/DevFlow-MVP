"""ReviewReport — 评审报告

双轴评审（Standards × Spec）的输出模型。
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class ReviewVerdict(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    ESCALATED = "escalated"


class ViolationSeverity(str, Enum):
    FATAL = "fatal"
    MAJOR = "major"
    MINOR = "minor"


class ReviewViolation(BaseModel):
    """单条违规"""
    id: str = Field(..., description="唯一编号，格式 S-001 / SP-001")
    severity: ViolationSeverity = Field(default=ViolationSeverity.MAJOR)
    axis: str = Field(..., description="standards | spec")
    rule: str = Field(..., description="违反的规则名称")
    message: str = Field(..., min_length=10, description="问题描述")
    paths: list[str] = Field(default_factory=list, description="相关文件路径")
    fix: Optional[str] = Field(None, description="建议修复方案")
    resolved: bool = Field(default=False)
    resolved_at: Optional[str] = Field(None)
    residual: bool = Field(default=False, description="是否登记为残余风险")


class AxeReview(BaseModel):
    """单轴评审结果"""
    verdict: ReviewVerdict = Field(default=ReviewVerdict.FAIL)
    violations: list[ReviewViolation] = Field(default_factory=list)


class ReviewReport(BaseModel):
    """评审报告"""
    id: str = Field(..., description="唯一编号，格式 r<N>")
    spec_id: str = Field(..., description="关联的 Spec ID")
    round: int = Field(default=1, ge=1, description="评审轮次")
    phase: int = Field(..., ge=0, le=7, description="评审时的阶段")
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    status: str = Field(default="active", pattern="^(active|resolved|escalated)$")

    # 双轴评审
    standards: AxeReview = Field(default_factory=AxeReview)
    spec: AxeReview = Field(default_factory=AxeReview)

    @property
    def total_violations(self) -> int:
        return len(self.standards.violations) + len(self.spec.violations)

    @property
    def fatal_count(self) -> int:
        return sum(1 for v in self._all_violations() if v.severity == ViolationSeverity.FATAL)

    @property
    def major_count(self) -> int:
        return sum(1 for v in self._all_violations() if v.severity == ViolationSeverity.MAJOR)

    @property
    def minor_count(self) -> int:
        return sum(1 for v in self._all_violations() if v.severity == ViolationSeverity.MINOR)

    @property
    def resolved_count(self) -> int:
        return sum(1 for v in self._all_violations() if v.resolved)

    @property
    def residual_count(self) -> int:
        return sum(1 for v in self._all_violations() if v.residual and not v.resolved)

    @property
    def verdict(self) -> ReviewVerdict:
        if self.status == "escalated":
            return ReviewVerdict.ESCALATED
        if self.fatal_count > 0:
            return ReviewVerdict.FAIL
        if self.major_count > 0 and self.resolved_count < self.major_count:
            return ReviewVerdict.FAIL
        return ReviewVerdict.PASS

    def _all_violations(self) -> list[ReviewViolation]:
        return self.standards.violations + self.spec.violations

    def get_violation(self, violation_id: str) -> Optional[ReviewViolation]:
        for v in self._all_violations():
            if v.id == violation_id:
                return v
        return None

    def can_advance(self) -> bool:
        """检查是否允许推进"""
        return self.verdict in (ReviewVerdict.PASS, ReviewVerdict.ESCALATED)


class FixRecord(BaseModel):
    """修复记录"""
    id: str = Field(..., description="唯一编号，格式 f<N>")
    review_id: str = Field(..., description="关联的评审报告 ID")
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    resolved_violations: list[str] = Field(default_factory=list, description="已解决的违规 ID 列表")
    residual_violations: list[str] = Field(default_factory=list, description="登记为残余风险的违规 ID 列表")
    summary: Optional[str] = Field(None, description="修复摘要")