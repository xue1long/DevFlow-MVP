"""PhaseStateMachine 单元测试

覆盖：正常推进、跳步阻断、approve 校验、skip-task 约束。
使用依赖注入：mock GitPort 和 GateRunner。
"""
import json
import pytest
import sys
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from devflow.model import Spec, SpecStatus, Plan, Task, TaskStatus, Contract
from devflow.storage.fs_backend import FSBackend
from devflow.storage.git_port import GitPort
from devflow.policy.loader import load_sop, SOPConfig
from devflow.engine.state_machine import PhaseStateMachine
from devflow.verify.gate_runner import GateRunner


class MockGitPort(GitPort):
    """测试用 GitPort mock"""
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
def workspace(tmp_path):
    """创建隔离的工作区"""
    storage = FSBackend(tmp_path)
    storage.init_workspace("""sop:
  sop_version: "0.1"
  phases: [intake, brainstorm, plan, contract, implement, verify, review, finish]
  intake_fast_skip: true
  red_lines: [skip_phase, no_test]
  gates:
    tests_pass: {command: "exit 0", blocking: true, enabled: true, bind_to_stage: 5}
    ci_green: {command: "exit 0", blocking: false, enabled: true, bind_to_stage: 6}
    intake_gate: {kind: triage, require: "ready-for-agent", blocking: true, enabled: true, bind_to_stage: 0}
  tooling: {proxy_strip: false}
  storage: {backend: fs}
""")
    config = load_sop(tmp_path / "sop.yaml")
    git = MockGitPort()
    gate_runner = GateRunner(config, str(tmp_path))
    machine = PhaseStateMachine(storage, config, git=git, gate_runner=gate_runner)
    return machine, storage, config


class TestPhaseStateMachine:
    def test_initial_phase_is_zero(self, workspace):
        machine, storage, config = workspace
        assert machine.current_phase == 0

    def test_start_creates_spec(self, workspace):
        machine, storage, config = workspace
        result = machine.start("为 pipeline 增加 batch 重试")
        assert result["ok"]
        assert "spec_id" in result
        spec_data = storage.read_spec(result["spec_id"])
        assert spec_data is not None
        assert spec_data["status"] == "draft"

    def test_next_from_intake_without_spec_fails(self, workspace):
        machine, storage, config = workspace
        result = machine.next_phase()
        assert not result["ok"]
        assert "无活跃 Spec" in result["message"]

    def test_next_from_intake_with_draft_spec(self, workspace):
        machine, storage, config = workspace
        result = machine.start("为 pipeline 增加 batch 重试")
        assert result["ok"]

        # intake_fast_skip=true 时 Stage0 门禁应自动通过
        result = machine.next_phase()
        assert result["ok"]
        assert result["phase"] == 1

    def test_approve_spec(self, workspace):
        machine, storage, config = workspace
        result = machine.start("为 pipeline 增加 batch 重试")
        spec_id = result["spec_id"]

        approve_result = machine.approve_spec(spec_id)
        assert approve_result["ok"]

        spec_data = storage.read_spec(spec_id)
        assert spec_data["status"] == "approved"

    def test_approve_spec_missing_fields(self, workspace):
        machine, storage, config = workspace
        # 直接写一个缺 non_goals 的 spec
        storage.write_spec("test-spec", {
            "id": "test-spec",
            "title": "Test",
            "problem": "A test problem description here",
            "goals": ["goal1"],
            "non_goals": [],
            "status": "draft",
        })

        result = machine.approve_spec("test-spec")
        assert not result["ok"]
        assert "missing" in result

    def test_skip_task_todo(self, workspace):
        machine, storage, config = workspace
        plan = Plan(
            spec_id="test-spec",
            tasks=[Task(id="task-1", title="T1", module="m1", acceptance=["a1"])],
        )
        storage.write_plan("test-plan", plan.model_dump(mode="json"))
        storage.set_current_plan_id("test-plan")

        result = machine.skip_task("task-1", "不再需要")
        assert result["ok"]

        plan_data = storage.read_plan("test-plan")
        assert plan_data["tasks"][0]["status"] == "skipped"

    def test_skip_task_implementing_fails(self, workspace):
        machine, storage, config = workspace
        plan = Plan(
            spec_id="test-spec",
            tasks=[Task(id="task-1", title="T1", module="m1", acceptance=["a1"],
                        status=TaskStatus.IMPLEMENTING)],
        )
        storage.write_plan("test-plan", plan.model_dump(mode="json"))
        storage.set_current_plan_id("test-plan")

        result = machine.skip_task("task-1", "不想做了")
        assert not result["ok"]
        assert "已进入实现阶段" in result["message"]

    def test_suspend_and_resume(self, workspace):
        machine, storage, config = workspace
        storage.set_current_phase(3)

        result = machine.suspend("测试挂起")
        assert result["ok"]
        assert storage.is_suspended()

        result = machine.resume()
        assert result["ok"]
        assert not storage.is_suspended()

    def test_resume_without_handoff_fails(self, workspace):
        machine, storage, config = workspace
        result = machine.resume()
        assert not result["ok"]
        assert "未找到 handoff" in result["message"]

    def test_gate_with_invalid_phase(self, workspace):
        machine, storage, config = workspace
        result = machine.run_gate(99)
        assert not result["ok"]
        assert "无效阶段号" in result["message"]
