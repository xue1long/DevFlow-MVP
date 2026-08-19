"""QualityGate — 质量门禁实体"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class QualityGate(BaseModel):
    """质量门禁

    从 sop.yaml 的 gates 配置加载。
    """
    name: str = Field(..., description="门禁名称，如 tests_pass / ci_green")
    command: Optional[str] = Field(default=None, description="实际执行命令")
    kind: Optional[str] = Field(default=None, description="门禁类型，如 triage")
    require: Optional[str] = Field(default=None, description="kind=triage 时的要求值")
    threshold: Any = Field(default=None, description="通过阈值")
    blocking: bool = Field(default=True, description="是否阻断进入下一阶段")
    enabled: bool = Field(default=True, description="是否启用")
    bind_to_stage: Optional[int] = Field(default=None, description="绑定的阶段号 0-7")
    note: Optional[str] = Field(default=None)
