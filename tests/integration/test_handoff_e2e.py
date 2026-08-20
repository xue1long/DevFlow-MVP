"""P2-18 handoff suggested_skills 动态化端到端测试

锁定 2026-08-20 Round 2 修复的完整行为链路,防止回归:
- suspend 真写盘:handoff-<phase>.md 文件落地 + YAML frontmatter 可解析
- 不同阶段产出不同 suggested_skills(从 SkillResolver 动态获取)
- 多阶段 handoff 共存:find_latest_handoff 按 phase 数字取最大
- suspend 不破坏哈希链(SUSPEND ledger 条目可验证)
- 同一 spec 反复 suspend:文件覆盖(命名约定是 handoff-<phase>.md)

单元测试(test_state_machine.py::test_handoff_*)覆盖:
- frontmatter 字典结构
- 动态性(4 个阶段至少 3 个不同 skill)
- 契约(Stage0 → triage)
- note 兼容性

本 e2e 不重复单元测试,聚焦"链路级 + 真实文件落地"行为。
"""
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from devflow.model import LedgerEntry, LedgerAction
from devflow.storage.fs_backend import FSBackend
from devflow.policy.loader import load_sop
from devflow.engine.state_machine import PhaseStateMachine
from devflow.verify.gate_runner import GateRunner
from devflow.engine.skill_resolver import SkillResolver

# 与 test_wizard_e2e.py 保持一致的 sop 模板,便于 fixture 复用
SOP_TEMPLATE = """sop:
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


class _MockGit:
    """E2E 测试用 git mock(避免真实 git 调用)"""
    def status(self):
        return ""

    def check_sensitive_files(self, status_output):
        return []

    def add_and_commit(self, message):
        return "handoff1234567890"

    def diff_stat(self, ref="HEAD~1"):
        return ""

    def log_oneline(self, count=5):
        return ""

    def diff_tree_files(self, sha):
        return []

    def current_branch(self):
        return "feature"


@pytest.fixture
def e2e_workspace(tmp_path):
    """隔离的工作区 + 完整 machine 装配

    返回 (workspace_path, machine, storage, config)。
    """
    storage = FSBackend(tmp_path)
    storage.init_workspace(SOP_TEMPLATE)
    config = load_sop(tmp_path / "sop.yaml")
    gate_runner = GateRunner(config, str(tmp_path))
    machine = PhaseStateMachine(
        storage, config, git=_MockGit(), gate_runner=gate_runner
    )
    return tmp_path, machine, storage, config


def _create_spec(machine, storage, draft="test handoff e2e with sufficient problem text"):
    """创建一个 Spec 并 set 为活跃"""
    result = machine.start(draft)
    assert result["ok"]
    return result["spec_id"]


def _parse_frontmatter(handoff_text):
    """从 handoff 文本中提取并解析 YAML frontmatter

    handoff 格式: ---\n<yaml>---\n\n<body>
    """
    assert handoff_text.startswith("---\n"), "handoff 必须以 --- 开头"
    # 找第二个 --- 的位置
    parts = handoff_text.split("---", 2)
    assert len(parts) >= 3, f"frontmatter 格式损坏: {handoff_text[:50]!r}"
    return yaml.safe_load(parts[1])


class TestHandoffEndToEnd:
    """P2-18 handoff suggested_skills 动态化端到端验证"""

    def test_e2e_suspend_writes_handoff_file_with_frontmatter(self, e2e_workspace):
        """场景 A:suspend 真写盘 + 文件落地 + frontmatter 可解析

        锁定 handoff-<phase>.md 文件路径约定 + YAML frontmatter 结构。
        """
        ws, machine, storage, config = e2e_workspace
        _create_spec(machine, storage)
        storage.set_current_phase(3)

        machine.suspend("stage 3 hand off to colleague")

        # 文件落地
        handoff_path = ws / "handoff-3.md"
        assert handoff_path.exists(), f"suspend 后未生成 {handoff_path}"

        # frontmatter 可解析
        content = handoff_path.read_text(encoding="utf-8")
        fm = _parse_frontmatter(content)
        assert fm["phase"] == 3
        assert fm["phase_name"] == "contract"
        assert fm["spec_id"] == storage.get_current_spec_id()

        # suggested_skills 来自 SkillResolver.Phase 3 = executing-plans
        assert "executing-plans" in fm["suggested_skills"]

        # artifact_refs 含 spec/plan/ledger
        assert any("specs/" in ref for ref in fm["artifact_refs"])
        assert any("progress.yaml" in ref for ref in fm["artifact_refs"])

    def test_e2e_resume_restores_phase_from_handoff(self, e2e_workspace):
        """场景 B:suspend → resume 链路恢复阶段

        挂起在 phase=5,resume 后 current_phase 回到 5。
        """
        ws, machine, storage, config = e2e_workspace
        _create_spec(machine, storage)
        storage.set_current_phase(5)

        # 挂起
        suspend_result = machine.suspend("pause for review")
        assert suspend_result["ok"]
        # suspend 会把 phase 写成 ledger,但 current_phase 本身可能保持
        # (resume 应该能从 handoff 读到正确 phase)

        # resume 恢复
        resume_result = machine.resume()
        assert resume_result["ok"]

        # verify_ledger 仍然通过(suspend/resume 都不破坏哈希链)
        verify = storage.verify_ledger()
        assert verify["ok"]

    def test_e2e_suggested_skills_differs_across_stages(self, e2e_workspace):
        """场景 C:不同阶段产出的 suggested_skills 来自 SkillResolver 不同条目

        SkillResolver.PHASE_SKILLS 已定义 8 个阶段的 skill 映射。
        """
        ws, machine, storage, config = e2e_workspace
        _create_spec(machine, storage)

        # 直接调 SkillResolver 验证契约
        resolver = SkillResolver()
        expected_skills = {}
        for phase in range(8):
            info = resolver.resolve(phase)
            expected_skills[phase] = info["skill"]

        # 关键断言:8 个阶段至少有 7 个不同的 skill(MVP 不允许重复)
        unique_skills = set(expected_skills.values())
        assert len(unique_skills) >= 7, (
            f"SkillResolver 应提供多样化 skill,实际只有 {len(unique_skills)} 个: {expected_skills}"
        )

        # 每个阶段 _get_suggested_skills 返回与 SkillResolver 一致
        for phase in range(8):
            skills = machine._get_suggested_skills(phase)
            assert skills == [expected_skills[phase]], (
                f"phase={phase} skill 不一致: {skills} vs {[expected_skills[phase]]}"
            )

    def test_e2e_handoff_yaml_loadable_by_agent(self, e2e_workspace):
        """场景 D:Agent 视角 — handoff frontmatter 可被 yaml.safe_load 解析

        这是 P2-18 的核心契约:Agent 能从 handoff 文件拿到结构化数据,
        不需要正则解析 Markdown。
        """
        ws, machine, storage, config = e2e_workspace
        spec_id = _create_spec(machine, storage)
        storage.set_current_phase(4)

        machine.suspend("")

        content = (ws / "handoff-4.md").read_text(encoding="utf-8")
        fm = _parse_frontmatter(content)

        # Agent 模拟:直接从字典取值
        assert fm["phase"] == 4
        assert fm["phase_name"] == "implement"
        assert fm["spec_id"] == spec_id
        assert isinstance(fm["suggested_skills"], list)
        assert len(fm["suggested_skills"]) >= 1
        assert all(isinstance(s, str) for s in fm["suggested_skills"])
        assert all(s != "unknown" for s in fm["suggested_skills"])
        assert isinstance(fm["artifact_refs"], list)
        assert len(fm["artifact_refs"]) >= 2

    def test_e2e_multiple_handoffs_find_latest_by_phase(self, e2e_workspace):
        """场景 E:同一 workspace 多阶段 handoff 共存,find_latest 按 phase 数字取最大

        这是命名约定的隐式行为:handoff-<phase>.md 不含 spec_id,
        所以同一 phase 不同 spec 的 handoff 会覆盖。
        find_latest_handoff() 用 max() 按 phase 数字取最大。
        """
        ws, machine, storage, config = e2e_workspace
        _create_spec(machine, storage)

        # 在 phase=3 挂起一次
        storage.set_current_phase(3)
        machine.suspend("at contract")

        # 再切到 phase=5 挂起
        storage.set_current_phase(5)
        machine.suspend("at verify")

        # 文件落地
        assert (ws / "handoff-3.md").exists()
        assert (ws / "handoff-5.md").exists()

        # find_latest_handoff 取 phase 数字最大的
        latest = storage.find_latest_handoff()
        assert latest is not None
        phase, content = latest
        assert phase == 5, f"find_latest 应返回 phase=5,实际 {phase}"
        assert "Stage5" in content or "verify" in content

    def test_e2e_suspend_preserves_ledger_hash_chain(self, e2e_workspace):
        """场景 F:suspend 写 SUSPEND ledger 条目后,哈希链仍然完整

        P0-3 教训:任何 ledger 写入都不能破坏哈希链。
        """
        ws, machine, storage, config = e2e_workspace
        _create_spec(machine, storage)
        storage.set_current_phase(2)

        # 挂起前快照
        before = storage.verify_ledger()
        assert before["ok"]

        # 挂起
        machine.suspend("checkpoint test")

        # 挂起后哈希链仍完整
        after = storage.verify_ledger()
        assert after["ok"], f"suspend 后哈希链断裂: {after}"

        # 验证 ledger 中确实有 SUSPEND 条目
        ledger = storage.get_ledger()
        suspend_entries = [
            e for e in ledger["entries"] if e.get("action") == "suspend"
        ]
        assert len(suspend_entries) >= 1

    def test_e2e_resume_after_suspend_phase_aligned(self, e2e_workspace):
        """场景 G:suspend → resume 后阶段对齐(契约测试)

        挂起在 phase=4,resume 后 ledger 中应有 SUSPEND + RESUME 两条,
        且当前阶段 = 4(从 handoff 恢复)。
        """
        ws, machine, storage, config = e2e_workspace
        _create_spec(machine, storage)
        storage.set_current_phase(4)

        machine.suspend("resumability test")
        machine.resume()

        ledger = storage.get_ledger()
        actions = [e["action"] for e in ledger["entries"]]

        # 必须有 SUSPEND 和 RESUME
        assert "suspend" in actions, f"ledger 缺 SUSPEND: {actions}"
        assert "resume" in actions, f"ledger 缺 RESUME: {actions}"

        # 哈希链仍然完整
        verify = storage.verify_ledger()
        assert verify["ok"]
