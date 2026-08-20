"""Research 适配层包 (v0.4 RFC §4)

不重复造 agent-reach 的轮子:
- 主路径 AgentReachBackend 复用宿主平台已加载的 agent-reach skill
- DevFlow 内置 3 个 HTTP backend 仅作离线/CI 兜底

纪律(适配层 v0.3 §7):
- 仅做协议转换:外部 API 响应 → list[Citation]
- 不加业务逻辑:合并/去重/截断由 engine.research_runner 负责
- 失败静默返回空列表,不抛异常跨越 backend 边界
"""
from __future__ import annotations

from .base import ResearchBackend
from .agent_reach import AgentReachBackend
from .github_search import GitHubSearchBackend
from .registry_query import RegistryQueryBackend
from .web_search import WebSearchBackend
from .selector import select_backends, DEFAULT_BACKEND_ORDER

__all__ = [
    "ResearchBackend",
    "AgentReachBackend",
    "GitHubSearchBackend",
    "RegistryQueryBackend",
    "WebSearchBackend",
    "select_backends",
    "DEFAULT_BACKEND_ORDER",
]