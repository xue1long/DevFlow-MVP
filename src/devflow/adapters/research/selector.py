"""Research backend 选择器 (v0.4 RFC §4.6)

按优先级返回可用 backend:
1. AgentReachBackend(综合源,优先复用宿主平台能力)
2. GitHubSearchBackend(兜底1)
3. RegistryQueryBackend(兜底2)
4. WebSearchBackend(兜底3)

输入 sources 过滤后,再 health_check 过滤失败的:
- 有健康 backend → 仅返回健康的(避免运行时失败)
- 全失败 → 返回所有(由 runner 记录 sources_failed)
"""
from __future__ import annotations

from pathlib import Path

from .agent_reach import AgentReachBackend
from .base import ResearchBackend
from .github_search import GitHubSearchBackend
from .registry_query import RegistryQueryBackend
from .web_search import WebSearchBackend


# 优先级排序(RFC §4.6)
DEFAULT_BACKEND_ORDER: list[str] = [
    "agent_reach",
    "github",
    "registry",
    "web",
]


def select_backends(
    workspace_root: Path,
    sources: list[str] | None = None,
    include_unhealthy: bool = False,
) -> list[ResearchBackend]:
    """选择可用 backend

    Args:
        workspace_root: 工作区根目录(用于探测 agent-reach)
        sources: SOP 配置中允许的数据源列表;
                 None 表示不按 source 过滤
        include_unhealthy: True 时 health_check 失败的 backend 也返回
                          (runner 用于"全失败时仍尝试并记录失败")

    Returns:
        按 DEFAULT_BACKEND_ORDER 优先级排序的 backend 列表
    """
    workspace_root = Path(workspace_root)
    requested = (
        {s.lower() for s in sources}
        if sources else None
    )

    # 按优先级构造所有候选 backend
    candidates: list[ResearchBackend] = [
        AgentReachBackend(workspace_root),
        GitHubSearchBackend(),
        RegistryQueryBackend(),
        WebSearchBackend(),
    ]

    # sources 过滤
    if requested is not None:
        # registry 覆盖多源(PYPI/NPM/CRATES),source 命中其一就保留
        def _matches_source(b: ResearchBackend) -> bool:
            if b.name == "registry":
                return bool({"pypi", "npm", "crates"} & requested)
            return b.source_type.value in requested

        filtered = [b for b in candidates if _matches_source(b)]
    else:
        filtered = candidates

    # health_check 过滤
    if not include_unhealthy:
        healthy = [b for b in filtered if b.health_check()]
        # 全失败时降级:保留全部(由 runner 记录失败)
        return healthy if healthy else filtered

    return filtered