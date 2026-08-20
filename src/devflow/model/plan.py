"""Plan — 计划实体"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .task import Task
from ..util.dag import detect_cycle


class Plan(BaseModel):
    """计划（Plan）

    包含一组 Task。

    v0.3 B5 阶段：Task.blocked_by 强制做环检测（model_validator 自动触发）
    之前 MVP 不做环检测（架构文档 §16.0 v0.2 待做），现已在 SDD 启动前补强。

    v0.3.3 思维字段（宽松默认,可选）:
      buffer  冗余思维: 缓冲比例(0-1),预留安全垫,资源不排满
    """
    # v0.3.4: 字段赋值后重跑校验（含 DAG 环检测），防止 plan.tasks.append /
    # task.blocked_by = [...] 等突变引入循环依赖而未被检测
    model_config = ConfigDict(validate_assignment=True)

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

    @model_validator(mode="after")
    def _validate_dag(self) -> "Plan":
        """验证 Plan 的 Task DAG 无环（v0.3 B5 阶段补强）

        Raises:
            ValueError: 当存在循环依赖时
        """
        errors = detect_cycle(
            node_ids=[t.id for t in self.tasks],
            deps=[t.blocked_by for t in self.tasks],
        )
        if errors:
            raise ValueError(f"Plan DAG 不合法: {'; '.join(errors)}")
        return self

    def validate_dag(self) -> list[str]:
        """显式调用 DAG 校验（model_validator 已自动触发，本方法供外部代码复用）

        Returns:
            错误信息列表；空列表表示合法
        """
        return detect_cycle(
            node_ids=[t.id for t in self.tasks],
            deps=[t.blocked_by for t in self.tasks],
        )
