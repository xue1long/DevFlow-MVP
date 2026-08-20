"""ReviewReport — 评审报告

双轴评审（Standards × Spec）的输出模型。
"""
from __future__ import annotations

from datetime import datetime, timezone
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
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    status: str = Field(default="active", pattern="^(active|escalated)$")

    # 双轴评审
    standards: AxeReview = Field(default_factory=AxeReview)
    spec: AxeReview = Field(default_factory=AxeReview)

    # Bug #16: 回归警告需随模型持久化（此前用私有属性 _regression_warnings，
    # model_dump() 时被丢弃）
    regression_warnings: list[dict] = Field(default_factory=list)

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
        """登记为残余风险的违规总数（P2-10: 不依赖 resolved 状态）

        fix() 设计：当用户用 --residual 时同时设 residual=True 和 resolved=True，
        表示"不再修复，作为残余风险登记"。residual_count 应当真实反映残余数量。
        """
        return sum(1 for v in self._all_violations() if v.residual)

    @property
    def unresolved_fatal_count(self) -> int:
        """未解决的 fatal 违规数（Bug #4）"""
        return sum(
            1 for v in self._all_violations()
            if v.severity == ViolationSeverity.FATAL and not v.resolved
        )

    @property
    def unresolved_major_count(self) -> int:
        """未解决的 major 违规数（Bug #3）"""
        return sum(
            1 for v in self._all_violations()
            if v.severity == ViolationSeverity.MAJOR and not v.resolved
        )

    @property
    def active_residual_count(self) -> int:
        """尚未被解决的残余风险（residual=True 且 resolved=False）。

        注意（Bug #29）：当前 review_engine.fix() 在 --residual / --skip 分支中
        同时设置 residual=True 与 resolved=True，因此经由 fix() 登记的残余风险
        不会计入本属性，实际返回 0。只有外部直接构造 residual=True 且
        resolved=False 的违规时本属性才非零。本属性逻辑本身是正确的，
        真正的问题在 review_engine.fix()，需在该文件单独修复。
        """
        return sum(1 for v in self._all_violations() if v.residual and not v.resolved)

    @property
    def verdict(self) -> ReviewVerdict:
        if self.status == "escalated":
            return ReviewVerdict.ESCALATED
        # Bug #4: 检查未解决的 fatal，而非 fatal 总数
        if self.unresolved_fatal_count > 0:
            return ReviewVerdict.FAIL
        # Bug #3: 直接检查未解决的 major，而非用跨 severity 的 resolved_count 比较
        if self.unresolved_major_count > 0:
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
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    resolved_violations: list[str] = Field(default_factory=list, description="已解决的违规 ID 列表")
    residual_violations: list[str] = Field(default_factory=list, description="登记为残余风险的违规 ID 列表")
    summary: Optional[str] = Field(None, description="修复摘要")