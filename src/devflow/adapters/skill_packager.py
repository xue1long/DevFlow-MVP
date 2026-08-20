"""通用 Skill 打包器（B4.4 阶段）

v0.3 INDEX 教训：no per-harness skill copies
- 所有平台共享同一份 SkillManifest（manifest_builder.py 自动派生）
- 适配层只做"翻译"：SkillManifest → 各平台原生格式
- 每个平台一个生成器函数，统一通过 package_for_platform() 入口

参考架构文档 §6 双集成面 + §7 一套核心 + 薄适配
"""
from __future__ import annotations

from pathlib import Path

from .manifest import SkillManifest


def package_for_platform(
    platform: str,
    manifests: list[SkillManifest],
    target_dir: Path,
) -> list[Path]:
    """根据平台名分发到对应的生成器

    Args:
        platform: 平台名（claude-code / workbuddy / codebuddy）
        manifests: Skill manifest 清单
        target_dir: 生成目录

    Returns:
        生成的 manifest 文件路径列表

    Raises:
        ValueError: 未知平台
    """
    target_dir = Path(target_dir)

    if platform == "claude-code":
        from .claude_code import generate_claude_code_skills
        return generate_claude_code_skills(manifests, target_dir)
    elif platform == "workbuddy":
        from .workbuddy import generate_workbuddy_skills
        return generate_workbuddy_skills(manifests, target_dir)
    elif platform == "codebuddy":
        from .codebuddy import generate_codebuddy_skills
        return generate_codebuddy_skills(manifests, target_dir)
    else:
        raise ValueError(
            f"Unknown platform: {platform}. "
            f"支持的平台: claude-code / workbuddy / codebuddy"
        )


__all__ = ["package_for_platform"]