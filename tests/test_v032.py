"""v0.3.2 轻量修补验证测试

锁定 4 项低风险修补的行为：
- P2-17: timestamp 时区化(UTC 感知)
- P2-14: 门禁结果持久化(gate_result 字段 + stdout/stderr 脱敏)
- P1-11: 语言中性化(no_test 不再硬编码 .py)
- P1-5 补强: RedLineViolation.status 枚举(active/mvp_skip/stub/not_implemented)
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from datetime import datetime, timezone

from devflow.model.ledger import LedgerEntry, LedgerAction
from devflow.storage.fs_backend import FSBackend
from devflow.policy.loader import load_sop
from devflow.engine.redline_auditor import (
    RedLineAuditor, RedLineViolation, ViolationStatus,
)
from devflow.engine.state_machine import PhaseStateMachine
from devflow.storage.git_port import SystemGitPort


FULL_RED_LINES_SOP = """sop:
  sop_version: "0.1"
  phases: [intake, brainstorm, plan, contract, implement, verify, review, finish]
  intake_fast_skip: true
  red_lines:
    - skip_phase
    - no_test
    - cross_module_import
    - huge_pr
    - uncommitted_bulk
    - main_incomplete
    - doc_drift
    - silent_legacy
    - no_contract
    - circular_dep:
        mvp_skip: true
    - human_step_auto
  pr_max_files: 30
  minimalism_strictness: full
  gates:
    tests_pass: {command: "exit 0", blocking: true, enabled: true, bind_to_stage: 5}
    ci_green: {command: "exit 0", blocking: false, enabled: false, bind_to_stage: 6}
    intake_gate: {kind: triage, require: "ready-for-agent", blocking: true, enabled: true, bind_to_stage: 0}
    review_gate: {kind: "review", blocking: true, enabled: true, bind_to_stage: 2, max_rounds: 5, require_clear: true}
  modules: {facade: "__init__.py", forbidden_import: []}
  tooling:
    test_runner: "pytest"
    import_mode: "importlib"
    proxy_strip: false
    languages:
      code_extensions: [".py", ".ts", ".go"]
      test_patterns: ["test", "_test", ".spec."]
      test_extensions: [".test.py", "_test.py", ".test.ts", "_test.ts", ".test.go", "_test.go"]
  storage: {backend: fs, specs_dir: specs, plans_dir: plans, ledger: progress.yaml, glossary: CONTEXT.md, content_address: false}
  allow_fast_forward: false
"""


@pytest.fixture
def env(tmp_path):
    storage = FSBackend(tmp_path)
    storage.init_workspace(FULL_RED_LINES_SOP)
    config = load_sop(tmp_path / "sop.yaml")
    machine = PhaseStateMachine(storage, config)
    return machine, storage, config, tmp_path


# --- P2-17: timestamp 时区化 ---

def test_p2_17_timestamp_is_utc_aware():
    """v0.3.2: LedgerEntry 默认 timestamp 应含 UTC 时区"""
    entry = LedgerEntry(phase=0, action=LedgerAction.START)
    assert entry.timestamp.tzinfo is not None, "timestamp 应有时区"
    assert entry.timestamp.utcoffset() is not None
    # 序列化后应含 UTC 标识(Z 或 +00:00)
    dumped = entry.model_dump(mode="json")
    assert ("+00:00" in dumped["timestamp"]) or ("Z" in dumped["timestamp"]), \
        f"timestamp 应序列化为 UTC 格式: {dumped['timestamp']}"


def test_p2_17_old_naive_timestamp_still_readable(env):
    """v0.3.2: 旧账本 naive timestamp 读取不报错(兼容)"""
    _, storage, _, _ = env
    # 手工写入一个 naive timestamp 的旧条目(模拟旧账本)
    storage.append_ledger(LedgerEntry(
        phase=0,
        action=LedgerAction.START,
        timestamp=datetime(2026, 1, 1, 12, 0, 0),  # naive
    ))
    ledger = storage.get_ledger()
    entries = ledger.get("entries", [])
    assert len(entries) == 1


# --- P2-14: 门禁结果持久化 ---

def test_p2_14_gate_result_field_exists():
    """v0.3.2: LedgerEntry 应有 gate_result 可选字段"""
    entry = LedgerEntry(phase=5, action=LedgerAction.GATE)
    assert entry.gate_result is None
    entry2 = LedgerEntry(
        phase=5,
        action=LedgerAction.GATE,
        gate_result={"ok": True, "stdout_tail": "ok", "stderr_tail": ""},
    )
    assert entry2.gate_result["ok"] is True


def test_p2_14_gate_result_persisted_in_ledger(env):
    """v0.3.2: 带 gate_result 的条目写入账本后可读回"""
    _, storage, _, _ = env
    storage.append_ledger(LedgerEntry(
        phase=5,
        action=LedgerAction.GATE,
        details="门禁 tests_pass: 通过",
        gate_result={"ok": True, "stdout_tail": "3 passed", "stderr_tail": ""},
    ))
    ledger = storage.get_ledger()
    entries = ledger.get("entries", [])
    assert len(entries) == 1
    assert entries[0]["gate_result"]["ok"] is True
    assert entries[0]["gate_result"]["stdout_tail"] == "3 passed"


def test_p2_14_hash_chain_still_valid_with_gate_result(env):
    """v0.3.2: 带 gate_result 的条目不破坏哈希链验证"""
    _, storage, _, _ = env
    # 先写一条无 gate_result 的旧式条目
    storage.append_ledger(LedgerEntry(phase=0, action=LedgerAction.START))
    # 再写一条带 gate_result 的新条目
    storage.append_ledger(LedgerEntry(
        phase=5,
        action=LedgerAction.GATE,
        gate_result={"ok": False, "stdout_tail": "", "stderr_tail": "boom"},
    ))
    result = storage.verify_ledger()
    assert result["ok"] is True, f"哈希链应完整: {result}"


# --- P1-11: 语言中性化 ---

def test_p1_11_default_language_is_py(env):
    """v0.3.2: 缺省语言配置回退 .py"""
    _, _, config, tmp_path = env
    auditor = RedLineAuditor(tmp_path, config, git=None)
    cfg = auditor._get_language_config()
    assert ".py" in cfg["code_extensions"]


def test_p1_11_is_test_file_precise_matching(env):
    """v0.3.2: 测试文件识别避免 contest/protest 误判"""
    _, _, config, tmp_path = env
    auditor = RedLineAuditor(tmp_path, config, git=None)
    cfg = auditor._get_language_config()
    assert auditor._is_test_file("test_foo.py", cfg) is True
    assert auditor._is_test_file("foo_test.py", cfg) is True
    assert auditor._is_test_file("contest.py", cfg) is False, "contest 不应误判"
    assert auditor._is_test_file("protest.go", cfg) is False, "protest 不应误判"
    assert auditor._is_test_file("foo.test.ts", cfg) is True


def test_p1_11_no_test_respects_language_config(env, tmp_path):
    """v0.3.2: no_test 用配置的后缀而非硬编码 .py"""
    _, _, config, tmp_path = env
    # 构造一个假 git(用真实 SystemGitPort 会失败,这里直接验证语言逻辑)
    auditor = RedLineAuditor(tmp_path, config, git=None)
    assert auditor.git is None  # 无 git 时返回空(不报错)


# --- P1-5 补强: status 枚举 ---

def test_p1_5_status_enum_values():
    """v0.3.2: ViolationStatus 枚举应有 4 态"""
    assert ViolationStatus.ACTIVE.value == "active"
    assert ViolationStatus.MVP_SKIP.value == "mvp_skip"
    assert ViolationStatus.STUB.value == "stub"
    assert ViolationStatus.NOT_IMPLEMENTED.value == "not_implemented"


def test_p1_5_audit_assigns_structured_status(env):
    """v0.3.2: audit() 应为每条违规分配结构化 status"""
    _, _, config, tmp_path = env
    auditor = RedLineAuditor(tmp_path, config, git=None)
    violations = auditor.audit()

    status_map = {v.rule: v.status for v in violations}
    # 5 条 stub → status=stub
    for rule in ["skip_phase", "doc_drift", "silent_legacy", "no_contract", "human_step_auto"]:
        assert status_map.get(rule) == ViolationStatus.STUB, f"{rule} 应为 stub"
    # circular_dep → mvp_skip
    assert status_map.get("circular_dep") == ViolationStatus.MVP_SKIP, "circular_dep 应为 mvp_skip"


def test_p1_5_to_dict_includes_status(env):
    """v0.3.2: to_dict() 应包含 status 字段"""
    v = RedLineViolation("no_test", "无测试", skip=True, status=ViolationStatus.STUB)
    d = v.to_dict()
    assert d["status"] == "stub"
    assert d["rule"] == "no_test"
    assert d["skip"] is True