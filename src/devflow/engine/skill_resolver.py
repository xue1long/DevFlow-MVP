"""SkillResolver — 基础版，意图路由仅覆盖线性推进

MVP 中 SkillResolver 的职责是：根据当前阶段返回下一步应执行的动作。
"""
from __future__ import annotations

from typing import Optional


class SkillResolver:
    """阶段→能力映射 + 基础意图路由"""

    PHASE_SKILLS = {
        0: {"skill": "triage", "description": "分类与可处理性判定"},
        1: {"skill": "brainstorming", "description": "完善 Spec，补 non_goals"},
        2: {"skill": "writing-plans", "description": "产出 Plan（含 Task DAG）"},
        3: {"skill": "executing-plans", "description": "为每个 Task 产出 Contract + 测试"},
        4: {"skill": "implement", "description": "实现代码变更"},
        5: {"skill": "verification", "description": "运行测试验证"},
        6: {"skill": "code-review", "description": "代码评审"},
        7: {"skill": "finishing", "description": "文档同步 + CI + 收尾"},
    }

    def resolve(self, phase: int, context: Optional[dict] = None) -> dict:
        """根据当前阶段返回下一步建议"""
        skill_info = self.PHASE_SKILLS.get(phase, {"skill": "unknown", "description": "未知阶段"})
        return {
            "phase": phase,
            "skill": skill_info["skill"],
            "description": skill_info["description"],
            "next_action": f"请调用 {skill_info['skill']} 完成 Stage{phase}",
        }
