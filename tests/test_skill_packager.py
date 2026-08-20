"""tests/test_skill_packager.py — B4.1/B4.2/B4.3 阶段验证

覆盖:
- Claude Code SKILL.md 文件结构
- WorkBuddy Skill manifest JSON 结构
- CodeBuddy Skill manifest JSON 结构
- skill_packager 平台分发
- adapter-export CLI 命令
"""
from __future__ import annotations

from pathlib import Path

import pytest

from devflow.adapters.manifest import SkillArg, SkillManifest


def _sample_manifests() -> list[SkillManifest]:
    """构造测试用 manifests（不依赖真实 cli.py）"""
    return [
        SkillManifest(
            name="devflow.test",
            description="测试命令",
            cli_subcommand="test",
            args=[
                SkillArg(name="name", type="string", description="名称"),
                SkillArg(name="count", type="integer", description="次数", required=False),
            ],
        ),
        SkillManifest(
            name="devflow.no-args",
            description="无参数命令",
            cli_subcommand="no-args",
            args=[],
        ),
    ]


class TestClaudeCodeGenerator:
    """B4.1 Claude Code SKILL.md 生成"""

    def test_creates_skill_md_files(self, tmp_path: Path):
        from devflow.adapters.claude_code import generate_claude_code_skills
        manifests = _sample_manifests()
        target = tmp_path / "claude-skills"

        generated = generate_claude_code_skills(manifests, target)

        # 应生成 2 个 SKILL.md
        assert len(generated) == 2
        assert all(p.exists() for p in generated)

        # 验证文件结构
        test_skill = target / "devflow.test" / "SKILL.md"
        content = test_skill.read_text(encoding="utf-8")

        # frontmatter
        assert content.startswith("---\n")
        assert "name: devflow.test" in content
        assert "description: 测试命令" in content
        # body
        assert "devflow test" in content
        assert "--name" in content
        assert "--count" in content
        assert "（可选）" in content  # count 是可选参数

    def test_no_args_command_generates_clean(self, tmp_path: Path):
        from devflow.adapters.claude_code import generate_claude_code_skills
        manifests = _sample_manifests()
        target = tmp_path / "claude"

        generate_claude_code_skills(manifests, target)

        no_args_skill = target / "devflow.no-args" / "SKILL.md"
        content = no_args_skill.read_text(encoding="utf-8")
        assert "devflow no-args " in content  # 注意末尾空格（无参数）
        assert "## 参数" in content  # 但参数段仍存在

    def test_target_dir_created(self, tmp_path: Path):
        """target_dir 不存在时应自动创建"""
        from devflow.adapters.claude_code import generate_claude_code_skills
        target = tmp_path / "deep" / "nested" / "path"
        assert not target.exists()

        generate_claude_code_skills(_sample_manifests(), target)
        assert target.exists()


class TestWorkBuddyGenerator:
    """B4.2 WorkBuddy Skill manifest JSON 生成"""

    def test_creates_json_files(self, tmp_path: Path):
        from devflow.adapters.workbuddy import generate_workbuddy_skills
        import json
        manifests = _sample_manifests()
        target = tmp_path / "workbuddy"

        generated = generate_workbuddy_skills(manifests, target)

        assert len(generated) == 2
        assert all(p.exists() for p in generated)

        # 验证 JSON 结构
        test_json = target / "devflow.test.json"
        data = json.loads(test_json.read_text(encoding="utf-8"))

        assert data["name"] == "devflow.test"
        assert data["description"] == "测试命令"
        assert data["command"] == "devflow test"
        assert "args" in data
        assert len(data["args"]) == 2
        assert data["args"][0]["name"] == "name"
        assert data["args"][0]["type"] == "string"
        assert data["args"][0]["required"] is True
        assert data["args"][1]["required"] is False


class TestCodeBuddyGenerator:
    """B4.3 CodeBuddy Skill manifest JSON 生成"""

    def test_creates_json_files(self, tmp_path: Path):
        from devflow.adapters.codebuddy import generate_codebuddy_skills
        import json
        manifests = _sample_manifests()
        target = tmp_path / "codebuddy"

        generated = generate_codebuddy_skills(manifests, target)

        assert len(generated) == 2
        test_json = target / "devflow.test.json"
        data = json.loads(test_json.read_text(encoding="utf-8"))

        assert data["name"] == "devflow.test"
        # CodeBuddy 用 tool/cli 而非 command
        assert data["tool"] == "devflow.test"
        assert data["cli"] == "devflow test"
        # inputSchema 嵌套结构
        assert "inputSchema" in data
        assert data["inputSchema"]["type"] == "object"
        assert "name" in data["inputSchema"]["properties"]
        assert data["inputSchema"]["required"] == ["name"]


class TestSkillPackager:
    """B4.4 skill_packager.py 平台分发"""

    def test_package_for_platform_routes_correctly(self, tmp_path: Path):
        from devflow.adapters.skill_packager import package_for_platform
        manifests = _sample_manifests()

        # 三个平台分别生成
        claude_files = package_for_platform(
            "claude-code", manifests, tmp_path / "claude"
        )
        workbuddy_files = package_for_platform(
            "workbuddy", manifests, tmp_path / "workbuddy"
        )
        codebuddy_files = package_for_platform(
            "codebuddy", manifests, tmp_path / "codebuddy"
        )

        assert len(claude_files) == 2
        assert len(workbuddy_files) == 2
        assert len(codebuddy_files) == 2

        # Claude Code 是 SKILL.md
        assert all(p.name == "SKILL.md" for p in claude_files)
        # WorkBuddy / CodeBuddy 是 .json
        assert all(p.name.endswith(".json") for p in workbuddy_files)
        assert all(p.name.endswith(".json") for p in codebuddy_files)

    def test_unknown_platform_raises(self, tmp_path: Path):
        from devflow.adapters.skill_packager import package_for_platform
        with pytest.raises(ValueError, match="Unknown platform"):
            package_for_platform("unknown", _sample_manifests(), tmp_path)


class TestAdapterExportCLI:
    """B4.4 adapter-export CLI 命令"""

    def test_adapter_export_help(self):
        from typer.testing import CliRunner
        from devflow.cli import app

        runner = CliRunner()
        result = runner.invoke(app, ["adapter-export", "--help"])
        assert result.exit_code == 0
        assert "Skill manifest" in result.output or "适配" in result.output

    def test_adapter_export_generates_files(self, tmp_path: Path):
        """adapter-export claude-code 应生成 SKILL.md（用 mock app）"""
        import typer
        from devflow.adapters.skill_packager import package_for_platform
        from devflow.adapters.manifest_builder import build_manifests_from_cli

        # 用临时 typer app（避免 cli.py 现有命令重名）
        mock_app = typer.Typer()

        @mock_app.command()
        def hello(name: str) -> None:
            """测试用 hello 命令"""
            pass

        manifests = build_manifests_from_cli(mock_app)
        assert len(manifests) == 1
        assert manifests[0].name == "devflow.hello"

        target = tmp_path / "claude-skills"
        generated = package_for_platform("claude-code", manifests, target)

        assert (target / "devflow.hello" / "SKILL.md").exists()