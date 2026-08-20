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
from devflow.storage.memory_backend import MemoryStorageBackend
from devflow.storage.git_port import GitPort
from devflow.policy.loader import load_sop_from_text, SOPConfig
from devflow.engine.state_machine import PhaseStateMachine
from devflow.verify.gate_runner import GateRunner


class MockGitPort(GitPort):
    """测试用 GitPort mock"""
    def __init__(self, status: str = "", branch: str = "feature"):
        self._status = status
        self._branch = branch

    def status(self) -> str:
        return self._status

    def check_sensitive_files(self, status_output: str) -> list[str]:
        return []  # 测试环境无敏感文件

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
    """Phase C: 内存后端 fixture。仅适用于走 StorageBackend 抽象接口的测试。

    涉及 hash chain / atomic write 物理行为的测试应使用 fs_backend。
    """
    sop_yaml = """sop:
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
"""
    storage = MemoryStorageBackend(tmp_path)
    storage.init_workspace(sop_yaml)
    config = load_sop_from_text(sop_yaml)
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

    # --- P1-17: Intake 闸门双门禁完整性 ---

    def test_intake_gate_hard_rejects_ready_for_human(self, workspace):
        """P1-17: ledger 中有 ready-for-human 记录,闸门硬拒绝 + 返回 wizard=True"""
        from devflow.model import LedgerEntry, LedgerAction
        machine, storage, config = workspace

        # 先创建一个 spec(否则闸门在 spec_id 检查时就返回了)
        storage.write_spec("test-spec", {
            "id": "test-spec",
            "title": "Test",
            "problem": "A test problem description here",
            "goals": ["goal1"],
            "non_goals": ["ng1"],
            "status": "draft",
        })
        storage.set_current_spec_id("test-spec")

        # 写一条 triage 记录,判定为 ready-for-human
        storage.append_ledger(LedgerEntry(
            phase=0,
            action=LedgerAction.TRIAGE,
            details="triage_state=ready-for-human,需人工授权操作数据库",
        ))

        result = machine._gate_intake()

        assert result["ok"] is False
        assert result["wizard"] is True
        assert "ready-for-human" in result["message"]
        assert "wizard" in result["message"]

    def test_intake_gate_allows_ready_for_agent(self, workspace):
        """P1-17: ledger 中有 ready-for-agent 记录,闸门正常通过"""
        from devflow.model import LedgerEntry, LedgerAction
        machine, storage, config = workspace

        storage.write_spec("test-spec", {
            "id": "test-spec",
            "title": "Test",
            "problem": "A test problem description here",
            "goals": ["goal1"],
            "non_goals": ["ng1"],
            "status": "draft",
        })
        storage.set_current_spec_id("test-spec")

        storage.append_ledger(LedgerEntry(
            phase=0,
            action=LedgerAction.TRIAGE,
            details="triage_state=ready-for-agent",
        ))

        result = machine._gate_intake()

        assert result["ok"] is True
        assert "ready-for-agent" in result["message"]

    def test_intake_gate_fast_skip_passes_without_ledger(self, workspace):
        """P1-17: intake_fast_skip=true 且无 triage 记录 → 闸门仍通过(向后兼容)"""
        machine, storage, config = workspace

        storage.write_spec("test-spec", {
            "id": "test-spec",
            "title": "Test",
            "problem": "A test problem description here",
            "goals": ["goal1"],
            "non_goals": ["ng1"],
            "status": "draft",
        })
        storage.set_current_spec_id("test-spec")

        result = machine._gate_intake()

        assert result["ok"] is True
        assert "fast_skip" in result["message"]

    def test_intake_gate_lifo_priority_after_wizard_upgrade(self, workspace):
        """P1-17 fix-2: wizard 升级后,ledger 同时有 ready-for-human 和 ready-for-agent,
        闸门应按 LIFO 语义看最新一条 → ready-for-agent 通过(而非硬拒绝)"""
        from devflow.model import LedgerEntry, LedgerAction
        machine, storage, config = workspace

        storage.write_spec("test-spec", {
            "id": "test-spec",
            "title": "Test",
            "problem": "A test problem description here",
            "goals": ["goal1"],
            "non_goals": ["ng1"],
            "status": "draft",
        })
        storage.set_current_spec_id("test-spec")

        # 旧 triage(ready-for-human)
        storage.append_ledger(LedgerEntry(
            phase=0,
            action=LedgerAction.TRIAGE,
            details="triage_state=ready-for-human,需要 DBA 授权",
        ))
        # 新 triage(wizard 升级后的 ready-for-agent)
        storage.append_ledger(LedgerEntry(
            phase=0,
            action=LedgerAction.TRIAGE,
            details="wizard 触发:triage_state=ready-for-agent",
        ))

        result = machine._gate_intake()

        # 最新一条是 ready-for-agent → 应该通过(wizard 升级生效)
        assert result["ok"] is True, f"期望通过,实际被拒绝: {result}"
        assert result.get("wizard") is None
        assert "ready-for-agent" in result["message"]

    # --- P2-18: handoff suggested_skills 动态化 ---

    def test_handoff_has_yaml_frontmatter(self, workspace):
        """P2-18: handoff 文档以 YAML frontmatter 开头,Agent 可结构化解析"""
        import yaml
        machine, storage, config = workspace
        storage.set_current_phase(3)

        handoff = machine._generate_handoff(3, "test-spec", "需要人工 review")

        assert handoff.startswith("---\n")
        # 解析 frontmatter(取第一对 --- 之间的内容)
        parts = handoff.split("---")
        fm = yaml.safe_load(parts[1])
        assert fm["phase"] == 3
        assert fm["phase_name"] == "contract"
        assert fm["spec_id"] == "test-spec"
        assert isinstance(fm["suggested_skills"], list)
        assert isinstance(fm["artifact_refs"], list)
        assert len(fm["artifact_refs"]) >= 2

    def test_handoff_suggested_skills_differs_by_phase(self, workspace):
        """P2-18: 不同阶段产出不同的 suggested_skills(动态性)"""
        import yaml
        machine, storage, config = workspace

        skills_by_phase = {}
        for phase in [0, 3, 5, 7]:
            handoff = machine._generate_handoff(phase, "test-spec", "")
            parts = handoff.split("---")
            fm = yaml.safe_load(parts[1])
            skills_by_phase[phase] = fm["suggested_skills"]

        # 至少 4 个阶段里,有 ≥3 个不同的 skill 列表(动态性证明)
        unique_skill_lists = {tuple(s) for s in skills_by_phase.values()}
        assert len(unique_skill_lists) >= 3, (
            f"expected ≥3 distinct skill lists across phases, "
            f"got {skills_by_phase}"
        )

    def test_handoff_intake_skill_is_triage(self, workspace):
        """P2-18: Stage0 (intake) 推荐 skill 必须是 triage(契约测试)"""
        import yaml
        machine, storage, config = workspace

        handoff = machine._generate_handoff(0, "test-spec", "")
        parts = handoff.split("---")
        fm = yaml.safe_load(parts[1])

        assert fm["suggested_skills"] == ["triage"]

    def test_handoff_includes_note_when_provided(self, workspace):
        """P2-18: 提供 note 时,handoff 应包含挂起笔记段(向后兼容)"""
        machine, storage, config = workspace

        handoff = machine._generate_handoff(5, "test-spec", "等用户确认")

        assert "## 挂起笔记" in handoff
        assert "等用户确认" in handoff
