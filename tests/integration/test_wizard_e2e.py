"""P1-17 Intake Wizard 端到端测试

锁定 2026-08-20 demo 发现的完整行为链路,防止回归:
- init → start → 注入 ready-for-human → next 触发 wizard
- wizard 选 a → ledger 追加新 triage → 重试 next 推进到 Stage1
- wizard 选 m → triage 标记 wontfix
- wizard 选 q → 退出不改 ledger
- LIFO 语义:wizard 升级后,旧 ready-for-human 不再误判
- 跨平台兼容:echo 消息不含 emoji(避免 GBK 控制台崩溃)
- 哈希链完整性:wizard 操作不破坏账本

依赖:test_state_machine.py 中的 workspace fixture 风格,
但本文件独立提供 e2e fixture,以便后续其它 e2e 测试复用。
"""
import io
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from devflow.model import LedgerEntry, LedgerAction
from devflow.storage.fs_backend import FSBackend
from devflow.policy.loader import load_sop
from devflow.engine.state_machine import PhaseStateMachine
from devflow.verify.gate_runner import GateRunner


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
        return "e2e1234567890"

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

    返回 (workspace_path, machine, storage, config),
    供 e2e 测试直接操作。
    """
    storage = FSBackend(tmp_path)
    storage.init_workspace(SOP_TEMPLATE)
    config = load_sop(tmp_path / "sop.yaml")
    gate_runner = GateRunner(config, str(tmp_path))
    machine = PhaseStateMachine(
        storage, config, git=_MockGit(), gate_runner=gate_runner
    )
    return tmp_path, machine, storage, config


def _write_human_triage(storage, spec_id):
    """注入一条 ready-for-human triage 记录(模拟 DBA 判定场景)"""
    storage.write_spec(spec_id, {
        "id": spec_id,
        "title": "Test",
        "problem": "A test problem description here",
        "goals": ["goal1"],
        "non_goals": ["ng1"],
        "status": "draft",
    })
    storage.set_current_spec_id(spec_id)
    storage.set_current_phase(0)
    storage.append_ledger(LedgerEntry(
        phase=0,
        action=LedgerAction.TRIAGE,
        details="triage_state=ready-for-human,需要 DBA 授权数据库修改",
    ))


class TestWizardEndToEnd:
    """P1-17 + P1-17 fix-2 + R17-4 (GBK) + R18-3 (typer.Choice) 端到端验证"""

    def test_e2e_normal_ready_for_agent_passes(self, e2e_workspace):
        """场景 A:正常路径 — ready-for-agent 直接推进,不触发 wizard"""
        ws, machine, storage, config = e2e_workspace
        machine.start("test normal path with sufficient problem description")

        result = machine.next_phase()

        assert result["ok"] is True
        assert result["phase"] == 1
        assert result.get("wizard") is None
        assert storage.get_current_phase() == 1

    def test_e2e_wizard_triggered_on_ready_for_human(self, e2e_workspace):
        """场景 B:异常路径 — ready-for-human 触发 wizard,返回 wizard=True"""
        from devflow.cli import _run_intake_wizard  # 触发时确保 import 路径正确

        ws, machine, storage, config = e2e_workspace
        machine.start("test wizard trigger with enough problem text")
        _write_human_triage(storage, storage.get_current_spec_id())

        # 模拟 next_phase(不直接调,因为 cli.next 还会触发 wizard)
        result = machine.next_phase()

        assert result["ok"] is False
        assert result["wizard"] is True
        assert "ready-for-human" in result["message"]
        assert "wizard" in result["message"].lower()

    def test_e2e_wizard_upgrade_a_allows_next_phase(self, e2e_workspace):
        """场景 C:wizard 选 'a' 升级为 ready-for-agent → 下次 next 推进到 Stage1

        这是 P1-17 fix-2 (LIFO) 修复的核心场景:
        ledger 同时有 ready-for-human 和 ready-for-agent,
        闸门必须按 LIFO 语义看最新一条。
        """
        ws, machine, storage, config = e2e_workspace
        machine.start("test wizard upgrade a to agent path")
        spec_id = storage.get_current_spec_id()
        _write_human_triage(storage, spec_id)

        # 第一次 next:触发 wizard
        result1 = machine.next_phase()
        assert result1.get("wizard") is True

        # 模拟 wizard 选 'a':追加新 triage 记录
        storage.append_ledger(LedgerEntry(
            phase=0,
            action=LedgerAction.TRIAGE,
            details="wizard trigger: triage_state=ready-for-agent",
        ))

        # 第二次 next:LIFO 修复后应通过,推进到 Stage1
        result2 = machine.next_phase()
        assert result2["ok"] is True, (
            f"LIFO 修复未生效,被旧 ready-for-human 误判: {result2}"
        )
        assert result2["phase"] == 1
        assert storage.get_current_phase() == 1

    def test_e2e_wizard_mark_wontfix_does_not_advance(self, e2e_workspace):
        """场景 D:wizard 选 'm' 标记 wontfix → 后续 next 仍被 wizard 拦截

        wontfix 不是 ready-for-agent,按 LIFO 语义不会通过,
        但 wizard 不会再触发(因为最新一条不是 ready-for-human)。
        行为约定:wontfix 后用户需手动 archive 或新建 spec。
        """
        ws, machine, storage, config = e2e_workspace
        machine.start("test wizard mark wontfix for edge case")
        spec_id = storage.get_current_spec_id()
        _write_human_triage(storage, spec_id)

        # 第一次 next:触发 wizard
        machine.next_phase()

        # 模拟 wizard 选 'm':追加 wontfix triage
        storage.append_ledger(LedgerEntry(
            phase=0,
            action=LedgerAction.TRIAGE,
            details="wizard trigger: triage_state=wontfix",
        ))

        # 第二次 next:不在 wizard 路径,也不在 ready-for-agent 路径
        result = machine.next_phase()
        # 不会触发 wizard(wontfix 不是 ready-for-human)
        assert result.get("wizard") is None
        # wontfix 是终态：闸门硬拒绝，不推进（此前被 fast_skip 静默绕过，已修复）
        assert result.get("ok") is False
        assert "wontfix" in result.get("message", "").lower()

    def test_e2e_wizard_messages_are_ascii_safe(self, e2e_workspace):
        """场景 E (R17-4):wizard 输出消息不含 emoji,Windows GBK 控制台安全"""
        from devflow.cli import _run_intake_wizard

        ws, machine, storage, config = e2e_workspace
        machine.start("test ascii compatibility for cross platform")
        spec_id = storage.get_current_spec_id()
        _write_human_triage(storage, spec_id)

        # 捕获 typer.echo 输出
        result = machine.next_phase()

        # 模拟 typer.echo:把输出收集到 buffer
        import typer
        import click
        captured = io.StringIO()
        with patch.object(typer, "echo", side_effect=lambda s: captured.write(str(s) + "\n")):
            # v0.3.4: 'q' 不再 raise typer.Exit，改为返回 None 表示放弃
            with patch.object(typer, "prompt", return_value="q"):
                result = _run_intake_wizard(result)
                # 'q' 必须返回 None（不输出 JSON，让调用方自行决定）
                assert result is None

        output = captured.getvalue()

        # R17-4 核心断言:输出不含 emoji(BMP 之外的字符)
        # emoji 在 Windows GBK 控制台下会触发 UnicodeEncodeError 崩溃
        # 注:中文本身在 GBK 下是可编码的,不会崩溃
        for ch in output:
            if ord(ch) > 0xFFFF:
                pytest.fail(
                    f"wizard 输出含 emoji/非 BMP 字符(GBK 控制台会崩溃):\n"
                    f"  char={ch!r}(U+{ord(ch):04X})\n"
                    f"  full output={output!r}"
                )

        # 同时确保 wizard 提示信息齐全
        assert "Intake" in output
        assert "ready-for-human" in output

        # 同时确保 wizard 提示信息齐全
        assert "Intake" in output
        assert "ready-for-human" in output

    def test_e2e_wizard_preserves_ledger_hash_chain(self, e2e_workspace):
        """场景 F:wizard 操作不破坏 SHA256 哈希链

        wizard 追加 triage 记录 → 哈希链必须仍然完整。
        """
        ws, machine, storage, config = e2e_workspace
        machine.start("test ledger hash chain remains valid")
        spec_id = storage.get_current_spec_id()

        # 注入 ready-for-human + wizard 升级,产生 3 条 ledger 条目
        _write_human_triage(storage, spec_id)
        storage.append_ledger(LedgerEntry(
            phase=0,
            action=LedgerAction.TRIAGE,
            details="wizard trigger: triage_state=ready-for-agent",
        ))

        verify_result = storage.verify_ledger()
        assert verify_result["ok"] is True, f"哈希链断裂: {verify_result}"

    def test_e2e_full_flow_init_start_human_wizard_recover(self, tmp_path):
        """场景 G:全链路 demo 还原

        完整复现 2026-08-20 demo 走过的 7 步:
        1. init workspace
        2. start spec
        3. 注入 ready-for-human
        4. next → wizard 触发
        5. wizard 升级 (a)
        6. next → 推进到 Stage1
        7. verify_ledger
        """
        storage = FSBackend(tmp_path)
        storage.init_workspace(SOP_TEMPLATE)
        config = load_sop(tmp_path / "sop.yaml")
        gate_runner = GateRunner(config, str(tmp_path))
        machine = PhaseStateMachine(
            storage, config, git=_MockGit(), gate_runner=gate_runner
        )

        # STEP 1+2
        start_result = machine.start("full chain demo recovery with enough problem")
        assert start_result["ok"] is True
        spec_id = start_result["spec_id"]

        # STEP 3:注入 ready-for-human
        _write_human_triage(storage, spec_id)

        # STEP 4:next 触发 wizard
        wizard_result = machine.next_phase()
        assert wizard_result.get("wizard") is True

        # STEP 5:wizard 选 'a' 升级
        storage.append_ledger(LedgerEntry(
            phase=0,
            action=LedgerAction.TRIAGE,
            details="wizard trigger: triage_state=ready-for-agent",
        ))

        # STEP 6:重试 next,推进到 Stage1
        advance_result = machine.next_phase()
        assert advance_result["ok"] is True
        assert advance_result["phase"] == 1

        # STEP 7:哈希链完整
        verify = storage.verify_ledger()
        assert verify["ok"] is True
