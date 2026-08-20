"""CodeBuddy Skill 适配层（B4.3 阶段）

CodeBuddy Skill manifest 格式：JSON 文件
- 与 WorkBuddy 类似但 schema 略不同
- CodeBuddy 用 'tool' 字段而非 'command'
- args 用 'schema' 嵌套结构

参考架构文档 §6 双集成面
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .manifest import SkillManifest


def generate_codebuddy_skills(
    manifests: list[SkillManifest],
    target_dir: Path,
) -> list[Path]:
    """生成 CodeBuddy Skill manifest JSON 文件

    CodeBuddy 格式与 WorkBuddy 略有不同：
    - 使用 'tool' 字段而非 'command'
    - args 用 'inputSchema' 嵌套结构（参考 JSON Schema）
    - 含 'version' / 'kind' 元数据

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
            "kind": "skill",
            "version": "0.1.0",
            "description": m.description,
            "tool": f"devflow.{m.cli_subcommand}",
            "cli": f"devflow {m.cli_subcommand}",
            "inputSchema": {
                "type": "object",
                "properties": {
                    a.name: {
                        "type": _json_type_to_codebuddy(a.type),
                        "description": a.description,
                    }
                    for a in m.args
                },
                "required": [a.name for a in m.args if a.required],
            },
            "metadata": {
                "generator": "devflow-adapter",
                "devflow_version": "v0.3.3",
            },
        }
        skill_file = target_dir / f"{m.name}.json"
        skill_file.write_text(
            json.dumps(skill_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        generated.append(skill_file)

    return generated


def _json_type_to_codebuddy(json_type: str) -> str:
    """JSON Schema 类型 → CodeBuddy 类型映射"""
    mapping = {
        "string": "string",
        "integer": "integer",
        "number": "number",
        "boolean": "boolean",
    }
    return mapping.get(json_type, "string")