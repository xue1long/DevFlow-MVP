"""RegistryQueryBackend — 包管理器 Registry 聚合查询 (v0.4 RFC §4.4)

兜底3: 直接查询官方 Registry API(PyPI / npm / crates.io)
- PyPI:   精确包名查询(无 search API,只能猜包名)
- npm:    提供 search API
- crates: 提供 search API

所有 Registry 都是官方源 → trust_level = HIGH

为什么不只走 PyPI:
- PyPI 仅精确匹配,适合"我想验证某包是否存在"
- npm/crates 提供 search,适合"我想找主题相关的包"
- 三者并发查询覆盖最广
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from concurrent.futures import TimeoutError as FutTimeout

from .base import ResearchBackend
from ...model.research import Citation, ResearchQuery, SourceType, TrustLevel


class RegistryQueryBackend(ResearchBackend):
    """包管理器 Registry 聚合查询(PyPI + npm + crates)"""

    name = "registry"
    # 该 backend 同时支持多个 source_type, runner 层按 query.sources 拆分调用
    source_type = SourceType.WEB  # 占位(registry 覆盖多源)

    SUPPORTED: dict[SourceType, tuple[str, str]] = {
        SourceType.PYPI:   ("https://pypi.org/pypi",            "exact"),
        SourceType.NPM:    ("https://registry.npmjs.org",       "search"),
        SourceType.CRATES: ("https://crates.io/api/v1/crates",  "search"),
    }

    def __init__(self, timeout: int = 5):
        self.timeout = timeout

    def health_check(self) -> bool:
        """任一 Registry 可达即视为健康"""
        for source_type in self.SUPPORTED:
            if self._check_one(source_type):
                return True
        return False

    def _check_one(self, source_type: SourceType) -> bool:
        url, mode = self.SUPPORTED[source_type]
        try:
            if source_type == SourceType.PYPI:
                # PyPI 无 search,探测 pypi 根域
                urllib.request.urlopen(f"{url}/", timeout=3).read()
            elif source_type == SourceType.NPM:
                urllib.request.urlopen(f"{url}/", timeout=3).read()
            else:  # crates
                req = urllib.request.Request(
                    f"{url}?q=test&per_page=1",
                    headers={"User-Agent": "devflow-research/0.4"},
                )
                urllib.request.urlopen(req, timeout=3).read()
            return True
        except Exception:
            return False

    def search(self, query: ResearchQuery) -> list[Citation]:
        """按 query.sources 拆分,只查被请求的 registry

        每个 registry 独立超时,某源失败不影响其他源
        """
        targets = [s for s in query.sources if s in self.SUPPORTED]
        if not targets:
            return []

        all_citations: list[Citation] = []
        with ThreadPoolExecutor(max_workers=len(targets)) as pool:
            futures = {
                pool.submit(self._search_one, s, query): s
                for s in targets
            }
            for fut in as_completed(futures):
                try:
                    citations = fut.result(timeout=self.timeout + 2)
                    all_citations.extend(citations)
                except (FutTimeout, Exception):
                    # 单源失败静默跳过(由 engine 层统一记 sources_failed)
                    pass
        return all_citations

    def _search_one(
        self, source: SourceType, query: ResearchQuery
    ) -> list[Citation]:
        if source == SourceType.PYPI:
            return self._search_pypi(query)
        if source == SourceType.NPM:
            return self._search_npm(query)
        if source == SourceType.CRATES:
            return self._search_crates(query)
        return []

    # ---- PyPI: 仅精确包名查询 ----

    def _search_pypi(self, query: ResearchQuery) -> list[Citation]:
        candidate = self._guess_package_name(query.query)
        if candidate is None:
            return []
        url = f"https://pypi.org/pypi/{candidate}/json"
        try:
            with urllib.request.urlopen(url, timeout=self.timeout) as resp:
                data = json.loads(resp.read())
        except (urllib.error.HTTPError, urllib.error.URLError, OSError,
                json.JSONDecodeError, TimeoutError):
            return []

        info = data.get("info", {})
        if not isinstance(info, dict):
            return []

        name = info.get("name", "").strip()
        if not name:
            return []

        homepage = (info.get("home_page") or "").strip()
        project_url = (info.get("project_url") or "").strip()
        url_final = homepage or project_url or f"https://pypi.org/project/{name}"

        return [self._make_citation(
            url=url_final,
            title=name,
            snippet=(info.get("summary") or ""),
            source_type=SourceType.PYPI,
            trust_level=TrustLevel.HIGH,  # 官方源
            metadata={
                "version": info.get("version"),
                "author": (info.get("author") or "")[:100],
                "license": (info.get("license") or "")[:50],
            },
        )]

    @staticmethod
    def _guess_package_name(query: str) -> str | None:
        """从 query 猜包名:取第一个合法标识符

        PyPI 包名规则:[a-z0-9_-]+, 大小写不敏感
        """
        # 取首个 token
        first = query.strip().split()[0] if query.strip() else ""
        first = first.lower()
        # 验证合法字符
        if not first or not all(c.isalnum() or c in "-_." for c in first):
            return None
        if len(first) > 100:  # 过长不像包名
            return None
        return first

    # ---- npm: search API ----

    def _search_npm(self, query: ResearchQuery) -> list[Citation]:
        params = urllib.parse.urlencode({
            "text": query.query,
            "size": query.max_results_per_source,
        })
        url = f"https://registry.npmjs.com/-/v1/search?{params}"
        try:
            with urllib.request.urlopen(url, timeout=self.timeout) as resp:
                data = json.loads(resp.read())
        except (urllib.error.URLError, urllib.error.HTTPError, OSError,
                json.JSONDecodeError, TimeoutError):
            return []

        objects = data.get("objects", [])
        if not isinstance(objects, list):
            return []

        citations: list[Citation] = []
        for obj in objects[:query.max_results_per_source]:
            if not isinstance(obj, dict):
                continue
            pkg = obj.get("package", {})
            if not isinstance(pkg, dict):
                continue
            name = (pkg.get("name") or "").strip()
            if not name:
                continue
            links = pkg.get("links", {}) or {}
            url_final = (links.get("npm") or "").strip()
            if not url_final:
                url_final = f"https://www.npmjs.com/package/{name}"

            publisher = pkg.get("publisher", {}) or {}
            author = (publisher.get("username") or "")[:100]

            citations.append(self._make_citation(
                url=url_final,
                title=name,
                snippet=(pkg.get("description") or ""),
                source_type=SourceType.NPM,
                trust_level=TrustLevel.HIGH,
                metadata={
                    "version": pkg.get("version"),
                    "author": author,
                    "date": pkg.get("date", "")[:10],
                },
            ))
        return citations

    # ---- crates.io: search API ----

    def _search_crates(self, query: ResearchQuery) -> list[Citation]:
        params = urllib.parse.urlencode({
            "q": query.query,
            "per_page": query.max_results_per_source,
        })
        url = f"https://crates.io/api/v1/crates?{params}"
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "devflow-research/0.4"},
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read())
        except (urllib.error.URLError, urllib.error.HTTPError, OSError,
                json.JSONDecodeError, TimeoutError):
            return []

        crates = data.get("crates", [])
        if not isinstance(crates, list):
            return []

        citations: list[Citation] = []
        for c in crates[:query.max_results_per_source]:
            if not isinstance(c, dict):
                continue
            name = (c.get("name") or "").strip()
            if not name:
                continue
            citations.append(self._make_citation(
                url=f"https://crates.io/crates/{name}",
                title=name,
                snippet=(c.get("description") or ""),
                source_type=SourceType.CRATES,
                trust_level=TrustLevel.HIGH,
                metadata={
                    "version": c.get("max_version"),
                    "downloads": c.get("downloads"),
                    "updated_at": c.get("updated_at", "")[:10],
                },
            ))
        return citations