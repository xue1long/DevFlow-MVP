"""AgentReachBackend — 复用宿主平台的 agent-reach skill (v0.4 RFC §4.2)

为什么不自研 web_search:
- 平台宿主(Claude Code / WorkBuddy / CodeBuddy)通常已加载 agent-reach skill,
  覆盖 15+ 平台、多 backend 路由(OpenCLI / per-platform CLIs / APIs)
- 自研等于重复造 agent-reach 的轮子
- DevFlow 内置仅在 CLI 直调场景做最小兜底(由 web_search/github 接管)

调用方式:
- claude-code:  claude --skill agent-reach --prompt "<query>"
- workbuddy:    wb --skill agent-reach --prompt "<query>"
- codebuddy:    codebuddy --skill agent-reach --prompt "<query>"

agent-reach 输出约定(JSON):
  {
    "citations": [
      {"url": "<url>", "title": "<t>", "snippet": "<s>",
       "source": "github|pypi|npm|web", "trust": "high|medium|low"}
    ]
  }
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from .base import ResearchBackend
from ...model.research import (
    Citation,
    ResearchQuery,
    SourceType,
    TrustLevel,
)


# 平台 → 可执行命令模板
# {prompt} 占位符会被实际 prompt 替换
_PLATFORM_CMDS: dict[str, list[str] | None] = {
    "claude-code": ["claude", "--skill", "agent-reach", "--prompt", "{prompt}"],
    "workbuddy":   ["wb", "--skill", "agent-reach", "--prompt", "{prompt}"],
    "codebuddy":   ["codebuddy", "--skill", "agent-reach", "--prompt", "{prompt}"],
}


class AgentReachBackend(ResearchBackend):
    """通过宿主平台的 agent-reach skill 调研"""

    name = "agent_reach"
    # 综合源(agent-reach 内部路由到任意具体平台),标记为 WEB 以便 runner 去重
    source_type = SourceType.WEB

    # agent-reach skill 的标准安装路径(各平台约定)
    SKILL_PATHS: list[str] = [
        ".claude/skills/agent-reach/SKILL.md",
        ".workbuddy/skills/agent-reach/SKILL.md",
        ".codebuddy/skills/agent-reach/SKILL.md",
    ]

    def __init__(self, workspace_root: Path, timeout: int = 30):
        self.workspace_root = Path(workspace_root)
        self.timeout = timeout

    def health_check(self) -> bool:
        """探测 agent-reach 是否在本平台可用

        三层信号(任一通过即视为可用):
        1. 平台探测环境变量(CLAUDE_CODE / WORKBUDDY_RUNTIME / CODEBUDDY_RUNTIME)
        2. skill 安装文件存在(SKILL.md)
        3. 平台可执行命令存在(claude/wb/codebuddy 在 PATH)
        """
        # 信号 1: 环境变量
        if any(
            os.environ.get(k)
            for k in ("CLAUDE_CODE", "WORKBUDDY_RUNTIME", "CODEBUDDY_RUNTIME")
        ):
            return True

        # 信号 2: skill 文件
        for rel in self.SKILL_PATHS:
            if (self.workspace_root / rel).exists():
                return True

        # 信号 3: 可执行命令
        for cmd_template in _PLATFORM_CMDS.values():
            if cmd_template and shutil.which(cmd_template[0]):
                return True

        return False

    def search(self, query: ResearchQuery) -> list[Citation]:
        """调用 agent-reach skill,解析返回 JSON

        失败返回空列表(不抛异常跨越 backend 边界)。
        """
        platform = self._detect_platform()
        if platform is None:
            return []

        cmd_template = _PLATFORM_CMDS.get(platform.value)
        if cmd_template is None:
            return []

        prompt = self._build_prompt(query)
        cmd = [c.replace("{prompt}", prompt) for c in cmd_template]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                cwd=str(self.workspace_root),
            )
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            return []

        if result.returncode != 0:
            return []

        return self._parse_response(result.stdout, query)

    # ---- 内部辅助 ----

    def _detect_platform(self):
        """复用 detect 模块探测平台"""
        from ..detect import detect_platform, Platform

        try:
            return detect_platform()
        except Exception:
            return Platform.CLI  # 兜底:CLI 平台无 agent-reach

    def _build_prompt(self, query: ResearchQuery) -> str:
        return (
            f"请基于高信任源调研以下内容,并以严格 JSON 格式返回结果:\n\n"
            f"查询: {query.query}\n\n"
            f"要求:\n"
            f"1. 优先使用 GitHub、官方文档、PyPI/npm 等高信任源\n"
            f"2. 最多返回 {query.max_results_per_source} 条结果\n"
            f"3. 每条结果包含: url, title, snippet(<=200字), "
            f"source, trust(high|medium|low)\n"
            f"4. 若无相关结果,返回空 citations 列表\n"
            f"5. 最终输出严格 JSON,不要包含解释文字\n\n"
            f"输出格式:\n"
            f'{{"citations": [...]}}'
        )

    def _parse_response(
        self, raw: str, query: ResearchQuery
    ) -> list[Citation]:
        """解析 agent-reach 返回内容(可能含 markdown 代码块)"""
        if not raw or not raw.strip():
            return []

        # 优先:直接 JSON
        data = self._try_json(raw)
        if data is None:
            # 兜底:从 markdown 代码块提取 JSON
            match = re.search(
                r'```(?:json)?\s*(\{.*?"citations".*?\})\s*```',
                raw,
                re.DOTALL,
            )
            if match:
                data = self._try_json(match.group(1))
        if data is None:
            return []

        citations_raw = data.get("citations", [])
        if not isinstance(citations_raw, list):
            return []

        citations: list[Citation] = []
        for c in citations_raw[:query.max_results_per_source]:
            if not isinstance(c, dict):
                continue
            url = c.get("url", "").strip()
            title = c.get("title", "").strip()
            if not url or not title:
                continue
            citations.append(self._make_citation(
                url=url,
                title=title,
                snippet=c.get("snippet", ""),
                source_type=self._map_source(c.get("source", "")),
                trust_level=self._map_trust(c.get("trust", "")),
                metadata={"via": "agent-reach"},
            ))
        return citations

    @staticmethod
    def _try_json(text: str) -> dict | None:
        try:
            data = json.loads(text)
            return data if isinstance(data, dict) else None
        except (json.JSONDecodeError, ValueError):
            return None

    _SOURCE_MAP = {
        "github": SourceType.GITHUB,
        "pypi": SourceType.PYPI,
        "npm": SourceType.NPM,
        "crates": SourceType.CRATES,
        "official_docs": SourceType.OFFICIAL_DOCS,
    }

    @classmethod
    def _map_source(cls, raw: str) -> SourceType:
        return cls._SOURCE_MAP.get(raw.lower(), SourceType.WEB)

    @classmethod
    def _map_trust(cls, raw: str) -> TrustLevel:
        try:
            return TrustLevel(raw.lower())
        except ValueError:
            return TrustLevel.UNKNOWN