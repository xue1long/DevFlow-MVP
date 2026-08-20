"""WebSearchBackend — 通用 web_search 兜底 (v0.4 RFC §4.5)

兜底2: 当所有其他 backend 都失败时,走通用 web 搜索

MVP 实现: DuckDuckGo Instant Answer API
- 无需鉴权、无需 token、纯 HTTP
- 数据有限,但兜底足够

v0.4+ 扩展预留: Google CSE / Brave Search / Bing (需 API key)
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

from .base import ResearchBackend
from ...model.research import Citation, ResearchQuery, SourceType, TrustLevel


class WebSearchBackend(ResearchBackend):
    """通用 web_search 兜底(DuckDuckGo Instant Answer)"""

    name = "web"
    source_type = SourceType.WEB
    API = "https://api.duckduckgo.com/"

    def __init__(self, timeout: int = 10):
        self.timeout = timeout

    def health_check(self) -> bool:
        try:
            urllib.request.urlopen(
                f"{self.API}?q=test&format=json&no_html=1",
                timeout=5,
            ).read()
            return True
        except Exception:
            return False

    def search(self, query: ResearchQuery) -> list[Citation]:
        params = urllib.parse.urlencode({
            "q": query.query,
            "format": "json",
            "no_html": "1",
            "skip_disambig": "1",
            "t": "devflow-research",
        })
        url = f"{self.API}?{params}"
        try:
            with urllib.request.urlopen(url, timeout=self.timeout) as resp:
                data = json.loads(resp.read())
        except (urllib.error.URLError, urllib.error.HTTPError, OSError,
                json.JSONDecodeError, TimeoutError):
            return []

        citations: list[Citation] = []

        # 优先: Abstract(直接答案)
        abstract = (data.get("Abstract") or "").strip()
        abstract_url = (data.get("AbstractURL") or "").strip()
        if abstract and abstract_url:
            citations.append(self._make_citation(
                url=abstract_url,
                title=(data.get("Heading") or query.query).strip(),
                snippet=abstract,
                source_type=SourceType.WEB,
                trust_level=TrustLevel.MEDIUM,
                metadata={"via": "duckduckgo-abstract"},
            ))

        # 兜底: RelatedTopics(相关主题)
        topics = data.get("RelatedTopics", [])
        if not isinstance(topics, list):
            return citations[:query.max_results_per_source]

        for topic in topics:
            if len(citations) >= query.max_results_per_source:
                break
            if not isinstance(topic, dict):
                continue
            first_url = (topic.get("FirstURL") or "").strip()
            text = (topic.get("Text") or "").strip()
            if not first_url or not text:
                continue
            # 跳过嵌套 Topics(duckduckgo 结构)
            if "Topics" in topic:
                continue
            # 标题提取:取首个 "-" 之前部分
            title = text.split(" - ")[0][:100] if " - " in text else text[:100]
            citations.append(self._make_citation(
                url=first_url,
                title=title or "Related",
                snippet=text,
                source_type=SourceType.WEB,
                trust_level=TrustLevel.LOW,
                metadata={"via": "duckduckgo-related"},
            ))

        return citations[:query.max_results_per_source]