"""Claude Code Skill 适配层（B4.1 阶段）

v0.3 INDEX 教训：no per-harness skill copies
- 所有平台共享同一份 SkillManifest（manifest_builder.py 自动派生）
- 适配层只做"翻译"：SkillManifest → 各平台原生格式
- Claude Code Skill = 单文件 markdown + YAML frontmatter

参考架构文档 §6 双集成面 + §7 一套核心 + 薄适配
"""
from __future__ import annotations

from pathlib import Path

from .manifest import SkillManifest


def generate_claude_code_skills(
    manifests: list[SkillManifest],
    target_dir: Path,
) -> list[Path]:
    """生成 Claude Code Skill manifest 文件

    每个 SkillManifest 对应一个 SKILL.md：
    - 目录: <target_dir>/devflow.<cli_subcommand>/SKILL.md
    - frontmatter: name / description
    - body: 调用说明 + 参数文档

    Claude Code 自动读取 SKILL.md 解析 frontmatter，
    通过 Bash(devflow ...) 调用，无需 wrapper 脚本。

    Args:
        manifests: Skill manifest 清单（来自 manifest_builder）
        target_dir: 生成目录根（如 ~/.claude/skills/devflow/）

    Returns:
        生成的 SKILL.md 文件路径列表
    """
    target_dir = Path(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    generated: list[Path] = []

    for m in manifests:
        skill_dir = target_dir / m.name
        skill_dir.mkdir(parents=True, exist_ok=True)

        args_doc = "\n".join(
            f"- `{a.name}` ({a.type}): {a.description or '参数 ' + a.name}"
            + ("" if a.required else "（可选）")
            for a in m.args
        )
        cmd_line = " ".join(
            f"--{a.name} <{a.name}>" for a in m.args
        )

        skill_md = f"""---
name: {m.name}
description: {m.description}
---

# DevFlow Skill: {m.name}

## 调用方式

通过 Bash 调用 DevFlow CLI：

```bash
devflow {m.cli_subcommand} {cmd_line}
```

## 参数

{args_doc}

## 返回值

DevFlow CLI 返回 JSON：
- 成功：`{{"ok": true, "data": {{...}}}}`
- 失败：`{{"ok": false, "message": "<原因>"}}`

exit code：0 成功 / 非 0 失败
"""
        skill_file = skill_dir / "SKILL.md"
        skill_file.write_text(skill_md, encoding="utf-8")
        generated.append(skill_file)

    return generated