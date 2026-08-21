"""SpecAutoFiller — 自动填充 Spec 字段 (v0.4.3 RFC §5)

v0.4.3 只做 goals 填充(暂不做 non_goals, 因 non_goals 应由人明确)。

关键纪律 (RFC §1):
  - 默认仅覆盖占位 ['待补充'], 不破坏用户已有内容
  - overwrite_existing=True 时强制覆盖
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel

from ..model.spec import Spec
from ..storage.base import StorageBackend


class GoalsFillResult(BaseModel):
    """Goals 填充结果"""
    spec_id: str
    original_goals: list[str]
    filled_goals: list[str]
    changed: bool  # 是否真的改了 spec.yaml


class SpecAutoFiller:
    """自动填充 Spec 字段(目前仅 goals)"""

    # 占位判定 (来自实际项目经验 + 中文友好)
    PLACEHOLDERS = {"待补充", "TBD", "TODO", "to be filled", ""}

    def __init__(self, storage: StorageBackend):
        self.storage = storage

    def fill_goals_if_empty(
        self,
        spec_id: str,
        new_goals: list[str],
        overwrite: bool = False,
    ) -> Optional[GoalsFillResult]:
        """仅当原 goals 是占位时填充(避免覆盖用户已有内容)

        Args:
            spec_id: 关联 Spec ID
            new_goals: 新 goals 列表(来自 GoalsExtractor)
            overwrite: True 时总是覆盖(即便用户已有 goals)

        Returns:
            None: Spec 不存在或 new_goals 为空
            GoalsFillResult: 已处理(changed 表示是否真的改了)
        """
        spec_data = self.storage.read_spec(spec_id)
        if spec_data is None:
            return None
        if not new_goals:
            return None

        try:
            spec = Spec(**spec_data)
        except Exception:
            return None

        original_goals = list(spec.goals)

        # 仅当原 goals 是占位 或 overwrite=True 时才覆盖
        if overwrite or self._is_placeholder(spec.goals):
            spec.goals = new_goals
            self.storage.write_spec(
                spec_id, spec.model_dump(mode="json")
            )
            return GoalsFillResult(
                spec_id=spec_id,
                original_goals=original_goals,
                filled_goals=new_goals,
                changed=True,
            )

        return GoalsFillResult(
            spec_id=spec_id,
            original_goals=original_goals,
            filled_goals=original_goals,  # 不变
            changed=False,
        )

    def _is_placeholder(self, goals: list[str]) -> bool:
        """判断 goals 是否是占位

        全部 goals 都在 PLACEHOLDERS 集合内才算占位
        """
        if not goals:
            return True
        return all(g.strip() in self.PLACEHOLDERS for g in goals)