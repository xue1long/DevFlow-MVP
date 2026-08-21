"""GoalsExtractor — 从 ResearchReport 提取 goals 草稿 (v0.4.3 RFC §4)

结构化提取 (零 LLM 依赖),纪律引擎定位保持。

策略:
  1. SourceType -> 模板 + regex 提取库名/仓库名
  2. 按 trust_level 降序排列 (HIGH 优先)
  3. 基于 goal 主语去重
  4. max_goals 截断

输入: ResearchReport
输出: list[str] (每个是建议 goal, 用户 Stage1 review)
"""
from __future__ import annotations

import re
from typing import ClassVar, Optional

from ..model.research import Citation, ResearchReport, SourceType, TrustLevel


class GoalsExtractor:
    """结构化提取, 不依赖 LLM"""

    # SourceType -> goal 模板
    TEMPLATES: ClassVar[dict[SourceType, str]] = {
        SourceType.PYPI: "集成 {name} 库({summary})",
        SourceType.NPM: "评估 {name} 包({summary})",
        SourceType.CRATES: "参考 {name} crate({summary})",
        SourceType.GITHUB: "参考 {repo} 项目(stars={stars})",
        SourceType.WEB: "调研: {title}",
    }

    # URL 提取 pattern
    NPM_PATTERN = re.compile(r"npmjs\.com/package/([^/]+)")
    PYPI_PATTERN = re.compile(r"pypi\.org/project/([^/]+)")
    CRATES_PATTERN = re.compile(r"crates\.io/crates/([^/]+)")
    GITHUB_PATTERN = re.compile(r"github\.com/([^/]+)/([^/]+)")

    def extract(
        self,
        report: ResearchReport,
        max_goals: int = 5,
    ) -> list[str]:
        """从 research 报告提取 goals 草稿

        Args:
            report: research 报告
            max_goals: 最多提取几个 goals

        Returns:
            list[str]: 提取的 goals (按 trust_level + 出现顺序)
        """
        goals: list[str] = []
        seen: set[str] = set()

        # 按 trust_level 降序 (HIGH > MEDIUM > LOW > UNKNOWN)
        sorted_citations = sorted(
            report.citations,
            key=lambda c: self._trust_rank(c.trust_level),
            reverse=True,
        )

        for citation in sorted_citations:
            goal = self._extract_from_citation(citation)
            if goal is None:
                continue
            # 去重 (基于 goal 主语)
            key = self._goal_key(goal)
            if key in seen:
                continue
            seen.add(key)
            goals.append(goal)
            if len(goals) >= max_goals:
                break

        return goals

    def _extract_from_citation(self, c: Citation) -> Optional[str]:
        """从单条 citation 提取一个 goal"""
        template = self.TEMPLATES.get(c.source_type)
        if template is None:
            return None

        # 工具: snippet 为空时不加括号
        snippet_clean = c.snippet.strip()[:50]
        def _fmt_with_optional_summary(base: str) -> str:
            """拼接 goal + 可选 (snippet)"""
            if snippet_clean:
                return f"{base}({snippet_clean})"
            return base

        # 按 source_type 走特定提取
        if c.source_type == SourceType.NPM:
            m = self.NPM_PATTERN.search(c.url)
            if m:
                name = m.group(1)
                return _fmt_with_optional_summary(f"评估 {name} 包")
        elif c.source_type == SourceType.PYPI:
            m = self.PYPI_PATTERN.search(c.url)
            if m:
                name = m.group(1)
                return _fmt_with_optional_summary(f"集成 {name} 库")
        elif c.source_type == SourceType.CRATES:
            m = self.CRATES_PATTERN.search(c.url)
            if m:
                name = m.group(1)
                return _fmt_with_optional_summary(f"参考 {name} crate")
        elif c.source_type == SourceType.GITHUB:
            m = self.GITHUB_PATTERN.search(c.url)
            if m:
                repo = f"{m.group(1)}/{m.group(2)}"
                stars = c.metadata.get("stars", "?")
                return template.format(repo=repo, stars=stars)

        # fallback: 用 title (web 源等)
        return template.format(title=c.title[:50])

    @staticmethod
    def _trust_rank(t: TrustLevel) -> int:
        return {
            TrustLevel.HIGH: 4,
            TrustLevel.MEDIUM: 3,
            TrustLevel.LOW: 2,
            TrustLevel.UNKNOWN: 1,
        }.get(t, 0)

    @staticmethod
    def _goal_key(goal: str) -> str:
        """goal 主语标准化(用于去重)

        提取 '(' 之前的部分作为主语,转小写,strip
        例: "参考 sindresorhus/got 项目(stars=12000)" -> "参考 sindresorhus/got 项目"
        """
        return goal.split("(")[0].strip().lower()