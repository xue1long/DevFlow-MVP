"""ResearchBackend — 调研后端抽象基类 (v0.4 RFC §4.1)

每个 backend 实现:
- search(query) -> list[Citation]: 查询接口,失败返回空列表(不抛异常)
- health_check() -> bool: 探测 backend 是否可用(网络/鉴权/token)

后端不应在内部做合并/去重/截断,这是 engine 编排层的职责。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from ...model.research import Citation, ResearchQuery, SourceType, TrustLevel

if TYPE_CHECKING:
    pass


class ResearchBackend(ABC):
    """调研后端抽象基类"""

    name: str = "abstract"
    source_type: SourceType = SourceType.WEB

    @abstractmethod
    def search(self, query: ResearchQuery) -> list[Citation]:
        """执行调研查询

        实现要点:
        - 失败(网络/auth/parse)应返回空列表,不抛异常跨越 backend 边界
        - 抛异常仅在 engine 层 _safe_search 兜底
        - 截断/去重由 engine 层统一处理

        Args:
            query: 调研查询参数(已合并 SOP 默认值)

        Returns:
            list[Citation]: 引用列表(已按 backend 内部优先级排序,
            但未全局去重)
        """
        raise NotImplementedError

    @abstractmethod
    def health_check(self) -> bool:
        """探测 backend 是否可用

        实现要点:
        - 必须快速(< 5s),用于 CLI 启动时决定走哪个 backend
        - 失败时不影响其他 backend(runner 串联降级)
        - 对鉴权 backend:探测 token 是否存在
        - 对 HTTP backend:HEAD 请求或简单 GET
        """
        raise NotImplementedError

    def _make_citation(
        self,
        url: str,
        title: str,
        source_type: SourceType | None = None,
        snippet: str = "",
        trust_level: TrustLevel = TrustLevel.UNKNOWN,
        metadata: dict | None = None,
    ) -> Citation:
        """便捷构造方法:统一时间戳 + 截断"""
        return Citation(
            url=url,
            title=title[:200],
            snippet=snippet.strip()[:500],
            source_type=source_type or self.source_type,
            trust_level=trust_level,
            metadata=metadata or {},
        )