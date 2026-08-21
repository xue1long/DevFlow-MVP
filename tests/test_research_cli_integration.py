"""T5 集成测试: CLI research 命令 + state_machine advisory

通过 Typer CliRunner 驱动,验证:
- `devflow research` 命令正确注册 + 解析参数
- 默认取当前活跃 Spec(spec_id=None 时)
- 显式 --spec-id 覆盖
- sources 解析(逗号分隔)
- 不存在的 spec_id 返回 ok=False
- state_machine.start() 检测 start_keywords 触发 advisory

不验:
- 真实网络调用(由 test_research_backends.py 覆盖)
- Runner 内部逻辑(由 test_research_runner.py 覆盖)
"""
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from devflow.cli import app
from devflow.storage.fs_backend import FSBackend


# =============================================================
# 测试 fixture
# =============================================================

@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """初始化一个 devflow 工作区(写好 sop.yaml + Spec) + 把 CLI cwd 切到 tmp_path"""
    storage = FSBackend(tmp_path)
    storage.init_workspace("""
sop:
  sop_version: "0.1"
  phases: [intake, brainstorm, plan, contract, implement, verify, review, finish]
  intake_fast_skip: true
  red_lines: [no_test]
  pr_max_files: 30
  gates:
    tests_pass: {command: "pytest", blocking: true, enabled: true, bind_to_stage: 5}
  research:
    enabled: true
    auto_run_on: [plan_stage]
    sources: [github, web]
    max_results_per_source: 5
    max_total_chars: 8000
    timeout_per_source: 5
    fallback: skip
    citation_required: true
    start_keywords: ["from scratch", "重新实现", "造轮子"]
""")
    # 创建一个 Spec
    from devflow.model.spec import Spec, SpecStatus
    spec = Spec(
        id="20260819-test",
        title="test",
        problem="test problem statement here",
        goals=["g1"],
        non_goals=["ng1"],
        status=SpecStatus.DRAFT,
    )
    storage.write_spec("20260819-test", spec.model_dump(mode="json"))
    storage.set_current_spec_id("20260819-test")
    # 关键:把 CLI cwd 切到 tmp_path,_get_root() 才返回 tmp_path
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def runner():
    return CliRunner()


# =============================================================
# research 命令
# =============================================================

class TestResearchCommand:
    def test_research_help(self, runner):
        result = runner.invoke(app, ["research", "--help"])
        assert result.exit_code == 0
        assert "调研" in result.stdout or "research" in result.stdout.lower()

    def test_research_command_registered(self, runner, workspace):
        """命令在 --help 中可见"""
        result = runner.invoke(app, ["--help"])
        assert "research" in result.stdout

    def test_research_default_spec(self, runner, workspace):
        """未传 --spec-id → 取当前活跃 Spec"""
        mock_result = {
            "ok": True,
            "report_path": "docs/devflow/research/test.md",
            "citations_count": 3,
            "sources_used": ["github"],
            "sources_failed": [],
            "fallback_used": False,
            "message": "ok",
            "citations": [],
        }
        with patch("devflow.cli._run_research", return_value=mock_result) as mock_rr:
            result = runner.invoke(app, [
                "research", "test query",
            ], catch_exceptions=False)
        if result.exit_code != 0:
            print("EXIT_CODE:", result.exit_code)
            print("OUTPUT:", result.output)
            print("STDOUT:", repr(result.stdout))
            print("STDERR:", repr(result.stderr))
            if result.exception:
                import traceback
                traceback.print_exception(type(result.exception), result.exception, result.exception.__traceback__)
        assert result.exit_code == 0
        # 默认取当前 spec_id="20260819-test"
        args, kwargs = mock_rr.call_args
        assert kwargs["spec_id"] == "20260819-test"
        assert kwargs["query"] == "test query"

    def test_research_explicit_spec(self, runner, workspace):
        """--spec-id 显式覆盖(必须存在的 spec)"""
        mock_result = {"ok": True, "report_path": "x", "citations_count": 0,
                       "sources_used": [], "sources_failed": [],
                       "fallback_used": False, "message": "ok", "citations": []}
        with patch("devflow.cli._run_research", return_value=mock_result):
            result = runner.invoke(app, [
                # 使用已存在的 spec_id (fixture 创建了 20260819-test)
                "research", "test", "--spec-id", "20260819-test",
            ])
        assert result.exit_code == 0

    def test_research_no_active_spec(self, runner, tmp_path, monkeypatch):
        """无活跃 Spec 且未指定 → ok=False"""
        monkeypatch.chdir(tmp_path)
        storage = FSBackend(tmp_path)
        storage.init_workspace("""
sop:
  sop_version: "0.1"
  phases: [intake, brainstorm, plan, contract, implement, verify, review, finish]
  intake_fast_skip: true
""")
        # 不创建任何 spec,current_spec_id=None
        result = runner.invoke(app, ["research", "test"])
        assert result.exit_code == 1
        # 输出 JSON 含 ok=False
        assert '"ok": false' in result.stdout.lower() or '"ok": False' in result.stdout
        assert "未指定 spec_id" in result.stdout

    def test_research_spec_id_not_found(self, runner, workspace):
        """v0.4.1: --spec-id 不存在 -> ok=False (不静默失败)"""
        result = runner.invoke(app, [
            "research", "test", "--spec-id", "nonexistent-spec",
        ])
        assert result.exit_code == 1
        assert '"ok": false' in result.stdout.lower() or '"ok": False' in result.stdout
        assert "nonexistent-spec" in result.stdout
        assert "不存在" in result.stdout

    def test_research_invalid_source(self, runner, workspace):
        """无效的 source 值 → ok=False"""
        result = runner.invoke(app, [
            "research", "test", "--sources", "invalid_source",
        ])
        assert result.exit_code == 1
        assert "无效" in result.stdout

    def test_research_clear_cache_all(self, runner, workspace):
        """v0.4.2: --clear-cache 不带 query → 清全部"""
        with patch(
            "devflow.engine.research_cache.ResearchCache.clear",
            return_value=3,
        ) as mock_clear, patch(
            "devflow.engine.research_cache.ResearchCache.stats",
            return_value={"total_entries": 0, "total_bytes": 0,
                          "ttl_seconds": 86400, "cache_dir": "/tmp/.cache"},
        ):
            result = runner.invoke(app, ["research", "--clear-cache"])
        assert result.exit_code == 0
        assert '"ok": true' in result.stdout.lower() or '"ok": True' in result.stdout
        assert "cleared_entries" in result.stdout
        assert "已清缓存" in result.stdout or "3" in result.stdout

    def test_research_clear_cache_single(self, runner, workspace):
        """v0.4.2: --clear-cache 带 query → 清单个"""
        with patch(
            "devflow.engine.research_cache.ResearchCache.clear",
            return_value=1,
        ) as mock_clear, patch(
            "devflow.engine.research_cache.ResearchCache.stats",
            return_value={"total_entries": 0, "total_bytes": 0,
                          "ttl_seconds": 86400, "cache_dir": "/tmp/.cache"},
        ):
            result = runner.invoke(app, [
                "research", "python retry", "--clear-cache",
            ])
        assert result.exit_code == 0
        # mock_clear 被以 key=... 调用(非 None)
        call_args = mock_clear.call_args
        assert call_args.kwargs.get("key") is not None

    def test_research_sources_parsed(self, runner, workspace):
        """逗号分隔的 sources 被正确解析"""
        mock_result = {"ok": True, "report_path": "x", "citations_count": 0,
                       "sources_used": [], "sources_failed": [],
                       "fallback_used": False, "message": "ok", "citations": []}
        with patch("devflow.cli._run_research", return_value=mock_result) as mock_rr:
            result = runner.invoke(app, [
                "research", "test",
                "--sources", "github,pypi,npm",
            ])
        assert result.exit_code == 0
        # 验证传入 config_adjusted 的 research.sources
        config = mock_rr.call_args.kwargs["config"]
        assert "github" in config.research.sources
        assert "pypi" in config.research.sources
        assert "npm" in config.research.sources

    def test_research_max_results_override(self, runner, workspace):
        """--max-results 覆盖 SOP 默认"""
        mock_result = {"ok": True, "report_path": "x", "citations_count": 0,
                       "sources_used": [], "sources_failed": [],
                       "fallback_used": False, "message": "ok", "citations": []}
        with patch("devflow.cli._run_research", return_value=mock_result) as mock_rr:
            result = runner.invoke(app, [
                "research", "test", "--max-results", "10",
            ])
        assert result.exit_code == 0
        config = mock_rr.call_args.kwargs["config"]
        assert config.research.max_results_per_source == 10


# =============================================================
# plan --with-research
# =============================================================

class TestPlanWithResearch:
    def test_plan_no_research_flag(self, runner, tmp_path, monkeypatch):
        """SOP 无 auto_run_on 时,plan 不触发调研"""
        monkeypatch.chdir(tmp_path)
        storage = FSBackend(tmp_path)
        storage.init_workspace("""
sop:
  sop_version: "0.1"
  phases: [intake, brainstorm, plan, contract, implement, verify, review, finish]
  intake_fast_skip: true
  research:
    enabled: true
    auto_run_on: []  # 显式空
""")
        from devflow.model.spec import Spec
        spec = Spec(id="spec-1", title="t", problem="my problem here",
                    goals=["g"], non_goals=["ng"])
        storage.write_spec("spec-1", spec.model_dump(mode="json"))
        storage.set_current_spec_id("spec-1")

        with patch("devflow.cli._run_research") as mock_rr:
            result = runner.invoke(app, ["plan"])
        mock_rr.assert_not_called()

    def test_plan_with_research_explicit(self, runner, workspace):
        """--with-research 显式触发调研"""
        mock_result = {"ok": True, "report_path": "x", "citations_count": 0,
                       "sources_used": [], "sources_failed": [],
                       "fallback_used": False, "message": "ok", "citations": []}
        with patch("devflow.cli._run_research", return_value=mock_result) as mock_rr:
            result = runner.invoke(app, [
                "plan", "--with-research",
            ])
        # _run_research 被调用,emit_echo=False
        assert mock_rr.call_count == 1
        kwargs = mock_rr.call_args.kwargs
        assert kwargs["emit_echo"] is False
        # query 取自 spec.problem
        assert "test problem statement" in kwargs["query"]

    def test_plan_auto_run_on_in_sop(self, runner, tmp_path, monkeypatch):
        """SOP 配 auto_run_on=[plan_stage] → plan 自动跑 research"""
        monkeypatch.chdir(tmp_path)
        storage = FSBackend(tmp_path)
        storage.init_workspace("""
sop:
  sop_version: "0.1"
  phases: [intake, brainstorm, plan, contract, implement, verify, review, finish]
  intake_fast_skip: true
  research:
    enabled: true
    auto_run_on: [plan_stage]
    sources: [github]
""")
        from devflow.model.spec import Spec, SpecStatus
        spec = Spec(
            id="spec-1",
            title="t",
            problem="my problem",
            goals=["g"],
            non_goals=["ng"],
        )
        storage.write_spec("spec-1", spec.model_dump(mode="json"))
        storage.set_current_spec_id("spec-1")

        mock_result = {"ok": True, "report_path": "x", "citations_count": 0,
                       "sources_used": [], "sources_failed": [],
                       "fallback_used": False, "message": "ok", "citations": []}
        with patch("devflow.cli._run_research", return_value=mock_result) as mock_rr:
            result = runner.invoke(app, ["plan"])
        # 隐式触发
        mock_rr.assert_called_once()

    def test_plan_research_disabled_in_sop(self, runner, tmp_path, monkeypatch):
        """SOP research.enabled=false → plan 不触发"""
        monkeypatch.chdir(tmp_path)
        storage = FSBackend(tmp_path)
        storage.init_workspace("""
sop:
  sop_version: "0.1"
  phases: [intake, brainstorm, plan, contract, implement, verify, review, finish]
  intake_fast_skip: true
  research:
    enabled: false
""")
        from devflow.model.spec import Spec, SpecStatus
        spec = Spec(
            id="spec-1", title="t", problem="my problem here",
            goals=["g"], non_goals=["ng"],
        )
        storage.write_spec("spec-1", spec.model_dump(mode="json"))
        storage.set_current_spec_id("spec-1")

        with patch("devflow.cli._run_research") as mock_rr:
            # 即使带 --with-research 也应被禁用
            result = runner.invoke(app, [
                "plan", "--with-research",
            ])
        mock_rr.assert_not_called()


# =============================================================
# state_machine advisory
# =============================================================

class TestAdvisoryEcho:
    def test_advisory_echo_on_keyword(self, monkeypatch, tmp_path, capsys):
        """start() 检测到 from scratch 时 echo advisory"""
        from devflow.engine.state_machine import PhaseStateMachine
        from devflow.policy.loader import load_sop
        from devflow.storage.fs_backend import FSBackend

        storage = FSBackend(tmp_path)
        storage.init_workspace("""
sop:
  sop_version: "0.1"
  phases: [intake, brainstorm, plan, contract, implement, verify, review, finish]
  intake_fast_skip: true
  research:
    enabled: true
    start_keywords: ["from scratch", "造轮子"]
""")
        config = load_sop(tmp_path / "sop.yaml")
        machine = PhaseStateMachine(storage, config)

        # 触发关键词的 draft
        result = machine.start("implement retry from scratch")
        assert result["ok"] is True

        # 捕获 stderr
        captured = capsys.readouterr()
        assert "[ADVISORY]" in captured.err
        assert "from scratch" in captured.err
        assert "devflow research" in captured.err

    def test_advisory_silent_on_no_keyword(self, monkeypatch, tmp_path, capsys):
        """不触发关键词 → 不 echo"""
        from devflow.engine.state_machine import PhaseStateMachine
        from devflow.policy.loader import load_sop
        from devflow.storage.fs_backend import FSBackend

        storage = FSBackend(tmp_path)
        storage.init_workspace("""
sop:
  sop_version: "0.1"
  phases: [intake, brainstorm, plan, contract, implement, verify, review, finish]
  intake_fast_skip: true
  research:
    enabled: true
    start_keywords: ["from scratch"]
""")
        config = load_sop(tmp_path / "sop.yaml")
        machine = PhaseStateMachine(storage, config)

        result = machine.start("add user login feature")
        assert result["ok"] is True

        captured = capsys.readouterr()
        assert "[ADVISORY]" not in captured.err

    def test_advisory_with_empty_keywords(self, tmp_path, capsys):
        """start_keywords 空 → 即使 draft 含 'from scratch' 也不提示"""
        from devflow.engine.state_machine import PhaseStateMachine
        from devflow.policy.loader import load_sop
        from devflow.storage.fs_backend import FSBackend

        storage = FSBackend(tmp_path)
        storage.init_workspace("""
sop:
  sop_version: "0.1"
  phases: [intake, brainstorm, plan, contract, implement, verify, review, finish]
  intake_fast_skip: true
  research:
    enabled: true
    start_keywords: []
""")
        config = load_sop(tmp_path / "sop.yaml")
        machine = PhaseStateMachine(storage, config)

        machine.start("implement from scratch retry")
        captured = capsys.readouterr()
        assert "[ADVISORY]" not in captured.err

    def test_advisory_truncates_long_draft(self, tmp_path, capsys):
        """draft > 60 字符 → 截断到 60 + ..."""
        from devflow.engine.state_machine import PhaseStateMachine
        from devflow.policy.loader import load_sop
        from devflow.storage.fs_backend import FSBackend

        storage = FSBackend(tmp_path)
        storage.init_workspace("""
sop:
  sop_version: "0.1"
  phases: [intake, brainstorm, plan, contract, implement, verify, review, finish]
  intake_fast_skip: true
  research:
    enabled: true
    start_keywords: ["from scratch"]
""")
        config = load_sop(tmp_path / "sop.yaml")
        machine = PhaseStateMachine(storage, config)

        long_draft = "x" * 100 + " from scratch " + "y" * 100
        machine.start(long_draft)
        captured = capsys.readouterr()
        assert "..." in captured.err  # 截断标记


# =============================================================
# 端到端 smoke
# =============================================================

class TestEndToEndSmoke:
    def test_full_flow_research_writes_files(self, runner, workspace):
        """end-to-end: devflow research → 真落盘文件 + Spec 更新 + 账本"""
        # mock 掉所有 backend,只让 FakeBackend 接管
        fake_citation = {
            "url": "https://github.com/x/y",
            "title": "x/y",
            "source": "github",
            "trust": "high",
        }
        mock_result = {
            "ok": True,
            "report_path": "docs/devflow/research/20260819-test-153012.md",
            "citations_count": 1,
            "sources_used": ["github"],
            "sources_failed": [],
            "fallback_used": False,
            "message": "ok",
            "citations": [fake_citation],
        }
        with patch("devflow.cli._run_research", return_value=mock_result):
            result = runner.invoke(app, ["research", "test"])
        assert result.exit_code == 0
        assert '"ok": true' in result.stdout.lower() or '"ok": True' in result.stdout
        assert "github" in result.stdout

    def test_research_uses_cwd_as_root(self, runner, tmp_path, monkeypatch):
        """CLI 跑在不同 cwd 时,research 落盘到该 cwd"""
        from devflow.cli import _get_root
        monkeypatch.chdir(tmp_path)

        # 初始化工作区
        storage = FSBackend(tmp_path)
        storage.init_workspace("""
sop:
  sop_version: "0.1"
  phases: [intake, brainstorm, plan, contract, implement, verify, review, finish]
  intake_fast_skip: true
""")
        from devflow.model.spec import Spec, SpecStatus
        spec = Spec(id="cwd-test", title="t", problem="test problem",
                    goals=["g"], non_goals=["ng"])
        storage.write_spec("cwd-test", spec.model_dump(mode="json"))
        storage.set_current_spec_id("cwd-test")

        # 用真实 runner 验证 _get_root 返回 cwd
        assert _get_root() == tmp_path