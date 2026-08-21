"""Research — 引文式调研产物（v0.4 + v0.4.2 缓存）

RFC §3.1 数据模型。
- SourceType: 数据源类型(GitHub/PyPI/npm/crates/web/official_docs)
- TrustLevel: 信任度分级(影响 plan 阶段采纳权重)
- Citation: 单条引用(URL + 标题 + 摘要片段 + 元数据)
- ResearchQuery: 调研查询参数
- ResearchReport: 调研报告(可序列化为 Markdown)
- CacheEntry: v0.4.2 本地缓存条目(24h TTL)
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class SourceType(str, Enum):
    """调研数据源

    AgentReachBackend 是综合源(由 agent-reach 内部决定具体平台),
    其 source_type 标记为 WEB,以便 runner 层去重时按值判等。
    """
    GITHUB = "github"
    PYPI = "pypi"
    NPM = "npm"
    CRATES = "crates"
    WEB = "web"
    OFFICIAL_DOCS = "official_docs"  # v0.4+ 扩展


class TrustLevel(str, Enum):
    """信任度分级

    HIGH: 官方文档 / GitHub 官方仓库 / 大 star 项目
    MEDIUM: 一般博客 / 中等 star 项目
    LOW: 论坛 / 0-1 star 项目
    UNKNOWN: 数据源未提供分级
    """
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNKNOWN = "unknown"


class Citation(BaseModel):
    """单条引用

    所有调研结果最终归一为 Citation。字段约束:
    - url 必须存在(否则跳过)
    - title 最长 200 字(防垃圾内容撑爆)
    - snippet 最长 500 字(用于 Markdown 引用块)
    """
    url: str = Field(..., min_length=1, description="来源 URL")
    title: str = Field(..., min_length=1, max_length=200)
    snippet: str = Field(default="", max_length=500, description="摘要片段")
    source_type: SourceType
    trust_level: TrustLevel = TrustLevel.UNKNOWN
    retrieved_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    metadata: dict = Field(
        default_factory=dict,
        description="扩展元数据: star 数 / 最近提交 / 版本号等",
    )


class ResearchQuery(BaseModel):
    """调研查询参数

    所有字段都有默认值,允许 CLI 仅传 query 就跑通。
    SOP 层的 ResearchConfig 提供项目级默认值。
    """
    query: str = Field(..., min_length=1, max_length=200)
    sources: list[SourceType] = Field(
        default_factory=lambda: [
            SourceType.GITHUB, SourceType.PYPI, SourceType.WEB
        ]
    )
    max_results_per_source: int = Field(default=5, ge=1, le=20)
    max_total_chars: int = Field(default=8000, ge=100, le=50000)
    timeout_per_source: int = Field(default=10, ge=1, le=60)
    spec_id: Optional[str] = Field(default=None, description="关联 Spec")


class ResearchReport(BaseModel):
    """调研报告

    落盘为 Markdown 时调用 to_markdown();
    关联到 Spec 时由 engine 层提取核心字段写进 spec.research_refs。
    """
    spec_id: str
    query: str
    citations: list[Citation] = Field(default_factory=list)
    summary: str = Field(
        default="",
        max_length=2000,
        description="调研摘要(MVP 允许空,由 Stage1 brainstorm 阶段补充)",
    )
    sources_used: list[SourceType] = Field(default_factory=list)
    sources_failed: list[SourceType] = Field(default_factory=list)
    fallback_used: bool = Field(
        default=False,
        description="是否触发 fallback(>=2 backend 串联)",
    )
    total_chars: int = Field(default=0)
    generated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    backend_chain: list[str] = Field(
        default_factory=list,
        description="实际使用的 backend 链路(含 fallback)",
    )

    def to_markdown(self) -> str:
        """生成带引用的 Markdown(用于落盘)"""
        lines: list[str] = [
            f"# Research Report: {self.query}",
            "",
            f"- **Spec**: `{self.spec_id}`",
            f"- **Generated**: {self.generated_at.isoformat()}",
            f"- **Sources**: {', '.join(s.value for s in self.sources_used) or '(none)'}",
            f"- **Citations**: {len(self.citations)}",
            f"- **Backend Chain**: {' → '.join(self.backend_chain) or '(none)'}",
            f"- **Fallback Used**: {self.fallback_used}",
            "",
            "## Summary",
            "",
            self.summary or "_（未生成摘要,可在编辑时补充）_",
            "",
            "## Citations",
            "",
        ]
        if not self.citations:
            lines.append("_（无引用结果）_")
            lines.append("")
        else:
            for i, c in enumerate(self.citations, 1):
                lines.append(f"### [{i}] {c.title}")
                lines.append("")
                lines.append(f"- **URL**: <{c.url}>")
                lines.append(f"- **Source**: `{c.source_type.value}`")
                lines.append(f"- **Trust**: `{c.trust_level.value}`")
                lines.append(f"- **Retrieved**: {c.retrieved_at.isoformat()}")
                if c.metadata:
                    meta_str = ", ".join(
                        f"{k}={v}" for k, v in c.metadata.items()
                    )
                    lines.append(f"- **Metadata**: {meta_str}")
                if c.snippet:
                    lines.append("")
                    lines.append(f"> {c.snippet}")
                lines.append("")
        return "\n".join(lines)

    def actual_chars(self) -> int:
        """实际字符数(用于截断判定)"""
        return sum(
            len(c.snippet) + len(c.title) + len(c.url)
            for c in self.citations
        )

    def has_high_trust(self) -> bool:
        """是否包含高信任度引用(影响 spec.research_refs.trust_level 字段)"""
        return any(c.trust_level == TrustLevel.HIGH for c in self.citations)


class CacheEntry(BaseModel):
    """v0.4.2 RFC §3.1: 本地缓存条目

    落盘为 docs/devflow/research/.cache/<key>.json
    TTL 由 sop.yaml.research.cache.ttl_seconds 控制(默认 24h)
    """
    key: str = Field(..., min_length=1, description="sha256 前 16 字符")
    query: str = Field(..., min_length=1, description="规范化后的 query")
    sources: list[str] = Field(default_factory=list, description="数据源列表")
    max_results_per_source: int = Field(..., ge=1)
    spec_id: str = Field(..., description="首次创建时的 spec_id")
    report_path: str = Field(..., description="Markdown 报告相对路径")
    citations_count: int = Field(..., ge=0)
    backend_chain: list[str] = Field(default_factory=list)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    expires_at: datetime

    def is_expired(self) -> bool:
        return datetime.now(timezone.utc) > self.expires_at

    def age_seconds(self) -> int:
        return int(
            (datetime.now(timezone.utc) - self.created_at).total_seconds()
        )