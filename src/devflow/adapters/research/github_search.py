"""GitHubSearchBackend — GitHub Repository Search API (v0.4 RFC §4.3)

兜底1: 当 agent-reach 不可用时,直接走 GitHub 官方搜索 API
- 未鉴权: 10 req/min(实际常用 30/min 软限)
- 鉴权:   env GITHUB_TOKEN 提供,30 req/min
- API:    https://api.github.com/search/repositories

trust 分级(由 stars 数判定):
- >= 1000: HIGH
- >= 100:  MEDIUM
- else:    LOW
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request

from .base import ResearchBackend
from ...model.research import Citation, ResearchQuery, SourceType, TrustLevel


class GitHubSearchBackend(ResearchBackend):
    """GitHub Repository Search API 兜底"""

    name = "github"
    source_type = SourceType.GITHUB
    API = "https://api.github.com/search/repositories"

    def __init__(self, timeout: int = 10):
        self.timeout = timeout
        self.token = os.environ.get("GITHUB_TOKEN")

    def health_check(self) -> bool:
        """用最少参数探测 API 可达性"""
        try:
            req = urllib.request.Request(
                f"{self.API}?q=test&per_page=1",
                headers=self._headers(),
            )
            urllib.request.urlopen(req, timeout=5).read()
            return True
        except Exception:
            return False

    def search(self, query: ResearchQuery) -> list[Citation]:
        params = urllib.parse.urlencode({
            "q": query.query,
            "per_page": query.max_results_per_source,
            "sort": "stars",
            "order": "desc",
        })
        req = urllib.request.Request(
            f"{self.API}?{params}",
            headers=self._headers(),
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read())
        except (urllib.error.URLError, urllib.error.HTTPError, OSError,
                json.JSONDecodeError, TimeoutError):
            return []

        items = data.get("items", [])
        if not isinstance(items, list):
            return []

        citations: list[Citation] = []
        for item in items[:query.max_results_per_source]:
            if not isinstance(item, dict):
                continue
            html_url = item.get("html_url", "").strip()
            full_name = item.get("full_name", "").strip()
            if not html_url or not full_name:
                continue

            stars = item.get("stargazers_count", 0) or 0
            citations.append(self._make_citation(
                url=html_url,
                title=full_name,
                snippet=(item.get("description") or ""),
                source_type=SourceType.GITHUB,
                trust_level=self._judge_trust(stars),
                metadata={
                    "stars": stars,
                    "language": item.get("language"),
                    "updated_at": item.get("updated_at"),
                    "license": (item.get("license") or {}).get("spdx_id"),
                },
            ))
        return citations

    def _headers(self) -> dict:
        h = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "devflow-research/0.4",
        }
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    @staticmethod
    def _judge_trust(stars: int) -> TrustLevel:
        if stars >= 1000:
            return TrustLevel.HIGH
        if stars >= 100:
            return TrustLevel.MEDIUM
        return TrustLevel.LOW