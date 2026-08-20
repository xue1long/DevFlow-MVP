"""Contract — 契约实体"""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class Contract(BaseModel):
    """契约（Contract）

    TDD 核心：接口/类型定义 + 测试路径。
    MVP 中 Stage3 产出，每个 task 一个 Contract。
    """
    module: str = Field(..., min_length=1)
    interface_signature: str = Field(..., min_length=1, description="入参/返回/异常类型签名")
    test_path: str = Field(default="", description="测试文件路径（MVP 不强制存在）")
    invariant: str = Field(default="", description="行为零变更等约束")

    @field_validator("module", "interface_signature")
    @classmethod
    def not_blank(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("module 和 interface_signature 不能为空")
        return stripped
