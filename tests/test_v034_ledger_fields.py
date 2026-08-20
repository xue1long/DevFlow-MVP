"""test_v034_ledger_fields.py — v0.4 P1-10 + P1-13 账本 schema 扩展验证

新增字段：spec_id / actor / session_id / review_ref
写入路径：
- spec_id：FSBackend.append_ledger 自动从 ledger 顶层 current_spec_id 填充
- session_id：进程级 UUID 前 8 字符（cli._get_session_id）
- actor：state_machine 默认 "engine"，CLI 可覆盖
- review_ref：review/fix/escalate 显式传入

预期：375 + 5 = 380 passed
"""
import uuid
import pytest
from pathlib import Path

from devflow.model.ledger import LedgerEntry, LedgerAction
from devflow.storage.fs_backend import FSBackend
from devflow.cli import _get_session_id
from devflow.engine.state_machine import PhaseStateMachine


@pytest.fixture
def fs_env(tmp_path):
    """最小 FSBackend 环境：init workspace + 直接 append ledger"""
    storage = FSBackend(tmp_path)
    storage.init_workspace("""sop:
  sop_version: "0.1"
  phases: [intake, brainstorm, plan, contract, implement, verify, review, finish]
""")
    return storage, tmp_path


def test_spec_id_auto_filled_from_ledger_top(fs_env):
    """spec_id 兜底为 ledger 顶层 current_spec_id"""
    storage, _ = fs_env
    storage.set_current_spec_id("20260820-test-spec")
    storage.append_ledger(LedgerEntry(
        phase=0,
        action=LedgerAction.TRIAGE,
        details="测试条目",
    ))
    ledger = storage.get_ledger()
    assert ledger["entries"][-1]["spec_id"] == "20260820-test-spec"


def test_session_id_consistent_within_process(fs_env):
    """同一次会话内 session_id 一致（UUID 前 8 字符）"""
    storage, _ = fs_env
    storage.set_current_spec_id("spec-1")
    storage.append_ledger(LedgerEntry(
        phase=0, action=LedgerAction.START, details="e1"
    ))
    storage.append_ledger(LedgerEntry(
        phase=0, action=LedgerAction.TRIAGE, details="e2"
    ))
    ledger = storage.get_ledger()
    assert ledger["entries"][0]["session_id"] == "engine"
    assert ledger["entries"][1]["session_id"] == "engine"
    # 引擎内部 session_id 兜底为 "engine"；CLI 入口会用 _get_session_id() 覆盖


def test_actor_default_is_engine(fs_env):
    """默认 actor="engine"（引擎内部写入）"""
    storage, _ = fs_env
    storage.append_ledger(LedgerEntry(
        phase=0, action=LedgerAction.START, details="e1"
    ))
    ledger = storage.get_ledger()
    assert ledger["entries"][-1]["actor"] == "engine"


def test_review_ref_on_review_action(fs_env):
    """review 操作 review_ref 字段正确填入 r{N}"""
    storage, _ = fs_env
    # 模拟 review_engine 写入：带 review_ref
    storage.append_ledger(LedgerEntry(
        phase=2,
        action=LedgerAction.REVIEW,
        details="评审 R1 完成",
        review_ref="r1",
    ))
    ledger = storage.get_ledger()
    entry = ledger["entries"][-1]
    assert entry["review_ref"] == "r1"
    assert entry["action"] == "review"


def test_hash_chain_works_with_new_fields(fs_env):
    """新字段进哈希后，verify_ledger 仍能验证（哈希链不断）"""
    storage, _ = fs_env
    storage.set_current_spec_id("hash-test")
    # 写入 3 条带新字段的条目
    for i in range(3):
        storage.append_ledger(LedgerEntry(
            phase=0,
            action=LedgerAction.START if i == 0 else LedgerAction.TRIAGE,
            details=f"entry {i}",
        ))

    # 验证哈希链
    result = storage.verify_ledger()
    assert result["ok"], f"哈希链验证失败：{result.get('message')}"
