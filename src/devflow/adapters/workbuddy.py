"""WorkBuddy Skill 适配层（B4.2 阶段）

WorkBuddy Skill manifest 格式：JSON 文件
- 单文件 JSON 而非 markdown
- 字段：name / description / command / args[]
- 通过 WorkBuddy 技能系统加载

参考架构文档 §6 双集成面
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .manifest import SkillManifest


def generate_workbuddy_skills(
    manifests: list[SkillManifest],
    target_dir: Path,
) -> list[Path]:
    """生成 WorkBuddy Skill manifest JSON 文件

    每个 SkillManifest 对应一个 JSON 文件：
    - 文件名: <target_dir>/<name>.json
    - 内容: 命令 + 参数的 JSON 表示

    Args:
        manifests: Skill manifest 清单
        target_dir: 生成目录

    Returns:
        生成的 JSON 文件路径列表
    """
    target_dir = Path(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    generated: list[Path] = []

    for m in manifests:
        skill_data: dict[str, Any] = {
            "name": m.name,
            "description": m.description,
            "command": f"devflow {m.cli_subcommand}",
            "args": [
                {
                    "name": a.name,
                    "type": a.type,
                    "required": a.required,
                    "description": a.description,
                }
                for a in m.args
            ],
            "output_format": "json",
            "metadata": {
                "generator": "devflow-adapter",
                "version": "v0.3.3",
            },
        }
        skill_file = target_dir / f"{m.name}.json"
        skill_file.write_text(
            json.dumps(skill_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        generated.append(skill_file)

    return generated