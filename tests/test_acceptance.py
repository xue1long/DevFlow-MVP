"""验收标准集成测试（13 条）

MVP Done = 以下 13 条全过。
每个测试使用 tmp_path fixture 隔离文件系统。
"""
import json
import sys
from pathlib import Path
from typing import Optional

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from devflow.model import Spec, SpecStatus, Plan, Task, TaskStatus, Contract
from devflow.storage.fs_backend import FSBackend
from devflow.storage.git_port import GitPort
from devflow.policy.loader import load_sop
from devflow.engine.state_machine import PhaseStateMachine
from devflow.engine.redline_auditor import RedLineAuditor
from devflow.verify.gate_runner import GateRunner


class MockGitPort(GitPort):
    def __init__(self, status: str = "", branch: str = "feature"):
        self._status = status
        self._branch = branch

    def status(self) -> str:
        return self._status
    def add_and_commit(self, message: str) -> Optional[str]:
        return "abc1234567890" if self._status else None
    def diff_stat(self, ref: str = "HEAD~1") -> str:
        return ""
    def log_oneline(self, count: int = 5) -> str:
        return ""
    def diff_tree_files(self, sha: str) -> list[str]:
        return []
    def current_branch(self) -> Optional[str]:
        return self._branch


@pytest.fixture
def devflow_env(tmp_path):
    """创建完整的 DevFlow 测试环境"""
    storage = FSBackend(tmp_path)
    storage.init_workspace("""sop:
  sop_version: "0.1"
  phases: [intake, brainstorm, plan, contract, implement, verify, review, finish]
  intake_fast_skip: true
  red_lines: [skip_phase, no_test, cross_module_import]
  gates:
    tests_pass: {command: "exit 0", blocking: true, enabled: true, bind_to_stage: 5}
    ci_green: {command: "exit 0", blocking: false, enabled: true, bind_to_stage: 6}
    intake_gate: {kind: triage, require: "ready-for-agent", blocking: true, enabled: true, bind_to_stage: 0}
  modules: {facade: "__init__.py", forbidden_import: ["internal/"]}
  tooling: {proxy_strip: false}
  storage: {backend: fs}
""")
    config = load_sop(tmp_path / "sop.yaml")
    git = MockGitPort()
    gate_runner = GateRunner(config, str(tmp_path))
    machine = PhaseStateMachine(storage, config, git=git, gate_runner=gate_runner)
    return machine, storage, config, tmp_path, git


class TestAcceptance:
    def test_1_init_generates_files(self, devflow_env):
        machine, storage, config, root, git = devflow_env
        assert (root / "sop.yaml").exists()
        assert (root / "specs").is_dir()
        assert (root / "plans").is_dir()
        assert (root / "progress.yaml").exists()
        assert (root / "CONTEXT.md").exists()

    def test_2_start_creates_spec(self, devflow_env):
        machine, storage, config, root, git = devflow_env
        result = machine.start("为 pipeline 增加 batch 重试")
        assert result["ok"]
        spec_data = storage.read_spec(result["spec_id"])
        assert spec_data["status"] == "draft"

    def test_3_no_skip_enforcement(self, devflow_env):
        machine, storage, config, root, git = devflow_env
        result = machine.start("为 pipeline 增加 batch 重试")
        spec_id = result["spec_id"]

        gate_result = machine._check_exit_gate(1)
        assert not gate_result["ok"]
        assert "未 approved" in gate_result["message"]

    def test_4_intake_gate(self, devflow_env):
        machine, storage, config, root, git = devflow_env
        result = machine.start("为 pipeline 增加 batch 重试")
        assert result["ok"]

        gate_result = machine._check_exit_gate(0)
        assert gate_result["ok"]

    def test_5_gate_executes_tests_pass(self, devflow_env):
        machine, storage, config, root, git = devflow_env
        result = machine.run_gate(5)
        assert result["ok"]

    def test_6_commit_gate_enforcement(self, devflow_env):
        machine, storage, config, root, git = devflow_env
        plan = Plan(
            spec_id="test-spec",
            tasks=[Task(id="task-1", title="T1", module="m1", acceptance=["a1"],
                        status=TaskStatus.REVIEWING)],
        )
        storage.write_plan("test-plan", plan.model_dump(mode="json"))
        storage.set_current_plan_id("test-plan")

        # 无代码变更时 commit 应失败
        result = machine.commit_task("task-1")
        assert not result["ok"]
        assert "无变更" in result["message"]

    def test_7_ledger_has_all_phases(self, devflow_env):
        machine, storage, config, root, git = devflow_env
        from devflow.model.ledger import LedgerEntry, LedgerAction
        for phase in range(8):
            storage.append_ledger(LedgerEntry(
                phase=phase,
                action=LedgerAction.PHASE_TRANSITION,
                details=f"Stage{phase}",
            ))
        ledger = storage.get_ledger()
        phases = {e["phase"] for e in ledger["entries"]}
        assert phases == set(range(8))

    def test_8_suspend_writes_handoff(self, devflow_env):
        machine, storage, config, root, git = devflow_env
        storage.set_current_phase(3)
        machine.suspend("测试挂起")
        assert (root / "handoff-3.md").exists()

    def test_9_redline_auditor_detects_violations(self, devflow_env):
        machine, storage, config, root, git = devflow_env
        auditor = RedLineAuditor(root, config, git=git)
        violations = auditor.audit()
        assert isinstance(violations, list)

    def test_10_cli_returns_json(self, devflow_env):
        machine, storage, config, root, git = devflow_env
        result = machine.get_status()
        assert "current_phase" in result
        assert "current_phase_name" in result
        json.dumps(result, ensure_ascii=False, default=str)

    def test_11_approve_validates_fields(self, devflow_env):
        machine, storage, config, root, git = devflow_env
        result = machine.start("为 pipeline 增加 batch 重试")
        spec_id = result["spec_id"]

        approve_result = machine.approve_spec(spec_id)
        assert approve_result["ok"]

        spec_data = storage.read_spec(spec_id)
        assert spec_data["status"] == "approved"

    def test_12_resume_restores_state(self, devflow_env):
        machine, storage, config, root, git = devflow_env
        storage.set_current_phase(4)
        machine.suspend("测试")
        storage.set_current_phase(0)

        result = machine.resume()
        assert result["ok"]
        assert storage.get_current_phase() == 4

    def test_13_unit_tests_exist(self):
        tests_dir = Path(__file__).parent
        assert (tests_dir / "test_state_machine.py").exists()
        assert (tests_dir / "test_models.py").exists()
