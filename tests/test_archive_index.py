"""v0.3 第一性方案验证测试

锁定新行为：
- 软归档：文件保留原位，账本 archive 段记录
- 列表查询：list_archived / list_active
- 跨文件搜索：query() 扫描 specs/、plans/、review/
- 自动归档：Stage7 next_phase 触发 _archive_on_finish
- 不破坏哈希链：archive 段不影响 entries 链
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from devflow.model import Spec, Plan, Task
from devflow.model.ledger import LedgerEntry, LedgerAction
from devflow.storage.fs_backend import FSBackend
from devflow.policy.loader import load_sop
from devflow.engine.state_machine import PhaseStateMachine


@pytest.fixture
def env(tmp_path):
    storage = FSBackend(tmp_path)
    storage.init_workspace("""sop:
  sop_version: "0.1"
  phases: [intake, brainstorm, plan, contract, implement, verify, review, finish]
  intake_fast_skip: true
  red_lines: [no_test]
  gates:
    tests_pass: {command: "exit 0", blocking: true, enabled: true, bind_to_stage: 5}
    ci_green: {command: "exit 0", blocking: false, enabled: true, bind_to_stage: 6}
  tooling: {proxy_strip: false}
  storage: {backend: fs}
""")
    config = load_sop(tmp_path / "sop.yaml")
    machine = PhaseStateMachine(storage, config)
    return machine, storage, config, tmp_path


def _write_spec_and_plan(storage, spec_id, title="t", plan_acceptance=None,
                          spec_goals=None, spec_non_goals=None,
                          spec_problem="为测试索引查询而编写的 problem 描述文本"):
    """写入完整 spec 与 plan，供后续检索用"""
    if plan_acceptance is None:
        plan_acceptance = ["覆盖测试需求"]
    if spec_goals is None:
        spec_goals = ["支持基础需求"]
    if spec_non_goals is None:
        spec_non_goals = ["不引入消息队列"]
    spec = Spec(
        id=spec_id, title=title,
        problem=spec_problem,
        goals=spec_goals, non_goals=spec_non_goals,
    )
    storage.write_spec(spec_id, spec.model_dump(mode="json"))
    plan = Plan(spec_id=spec_id, tasks=[
        Task(id="task-1", title=title, module="core", acceptance=plan_acceptance),
    ])
    storage.write_plan(f"plan-{spec_id}", plan.model_dump(mode="json"))
    storage.set_current_plan_id(f"plan-{spec_id}")
    storage.set_current_spec_id(spec_id)


# --- 软归档 ---

def test_archive_preserves_files(env):
    """归档不移动文件"""
    machine, storage, _, tmp_path = env
    _write_spec_and_plan(storage, "spec-A")
    spec_path = tmp_path / "specs" / "spec-A.yaml"
    plan_path = tmp_path / "plans" / "plan-spec-A.yaml"
    assert spec_path.exists()
    assert plan_path.exists()

    record = storage.archive_spec("spec-A", reason="test archive")

    # 文件原位
    assert spec_path.exists()
    assert plan_path.exists()
    # 账本 archive 段有记录
    ledger = storage.get_ledger()
    assert "archive" in ledger
    assert "spec-A" in ledger["archive"]
    assert ledger["archive"]["spec-A"]["reason"] == "test archive"
    assert ledger["archive"]["spec-A"]["final_stage"] == 0
    # 文件位置索引记录
    assert "spec" in record["files_at"]


def test_archive_does_not_break_hash_chain(env):
    """归档不破坏 entries 哈希链"""
    machine, storage, _, _ = env
    # 写一条 entry
    storage.append_ledger(LedgerEntry(phase=0, action=LedgerAction.TRIAGE, details="e1"))
    storage.append_ledger(LedgerEntry(phase=1, action=LedgerAction.APPROVE, details="e2"))
    verify_before = storage.verify_ledger()
    assert verify_before["ok"]

    # 归档
    storage.archive_spec("some-spec", reason="test")

    # 哈希链依然完整
    verify_after = storage.verify_ledger()
    assert verify_after["ok"]


def test_list_archived_and_active(env):
    """list_archived / list_active 互斥"""
    machine, storage, _, _ = env
    _write_spec_and_plan(storage, "spec-A")
    _write_spec_and_plan(storage, "spec-B")

    # 初始：两个都是活跃
    assert sorted(storage.list_active_specs()) == ["spec-A", "spec-B"]
    assert storage.list_archived_specs() == []

    # 归档 A
    storage.archive_spec("spec-A", reason="first")

    # A 在归档列表
    assert storage.list_active_specs() == ["spec-B"]
    archived = storage.list_archived_specs()
    assert len(archived) == 1
    assert archived[0]["spec_id"] == "spec-A"
    assert archived[0]["final_stage"] == 0


# --- 跨文件搜索 ---

def test_query_empty_keyword_returns_all_active(env):
    """空关键词 + 默认仅活跃"""
    machine, storage, _, _ = env
    _write_spec_and_plan(storage, "spec-A")
    _write_spec_and_plan(storage, "spec-B")
    storage.archive_spec("spec-B", reason="archived")

    results = storage.query()
    # 默认不含已归档
    assert len(results) == 1
    assert results[0]["spec_id"] == "spec-A"
    assert results[0]["status"] == "active"


def test_query_include_archived(env):
    """--all 包含归档"""
    machine, storage, _, _ = env
    _write_spec_and_plan(storage, "spec-A")
    _write_spec_and_plan(storage, "spec-B")
    storage.archive_spec("spec-B", reason="archived")

    results = storage.query(include_archived=True)
    assert len(results) == 2
    statuses = {r["status"] for r in results}
    assert statuses == {"active", "archived"}


def test_query_keyword_matches_across_files(env):
    """关键词搜索跨 Spec/Plan 文件"""
    machine, storage, _, _ = env
    # spec-pipeline 全文含 retry；spec-cache 全文不含 retry
    _write_spec_and_plan(
        storage, "spec-pipeline", title="Pipeline Retry",
        plan_acceptance=["覆盖 retry"],
        spec_problem="Pipeline 系统需要 retry 支持",
        spec_goals=["支持 retry"],
    )
    _write_spec_and_plan(
        storage, "spec-cache", title="Cache Refactor",
        plan_acceptance=["清理缓存项"],
        spec_problem="Cache 系统需要清理逻辑",
        spec_goals=["支持缓存清理"],
    )

    # "retry" 应匹配 pipeline 但不匹配 cache
    results = storage.query(keyword="retry")
    spec_ids = {r["spec_id"] for r in results}
    assert "spec-pipeline" in spec_ids
    assert "spec-cache" not in spec_ids

    # 检查 match_locations 包含 spec 和 plan
    pipeline = next(r for r in results if r["spec_id"] == "spec-pipeline")
    assert "spec" in pipeline["match_locations"]
    assert any("plan:" in m for m in pipeline["match_locations"])


def test_query_keyword_no_match(env):
    """无匹配关键词返回空列表"""
    machine, storage, _, _ = env
    _write_spec_and_plan(storage, "spec-A")

    results = storage.query(keyword="nonexistent_keyword_xyz")
    assert results == []


# --- 自动归档触发 ---

def test_stage7_triggers_archive(env):
    """next_phase 到 Stage7 自动归档活跃 Spec（绕过门禁）"""
    machine, storage, _, _ = env
    # 注入 gate_runner 与 review_engine（默认 env fixture 没有）
    from devflow.engine.review_engine import ReviewEngine
    from devflow.storage.review_store import ReviewStore
    review_store = ReviewStore(env[3])
    machine.review_engine = ReviewEngine(storage, machine.config, review_store)
    from devflow.verify.gate_runner import GateRunner
    machine.gate_runner = GateRunner(machine.config, str(env[3]))

    # 绕过门禁：让 _check_exit_gate 总是通过
    machine._check_exit_gate = lambda phase: {"ok": True, "message": "bypass"}
    machine.review_engine.check_review_gate = lambda: {"ok": True, "message": "bypass"}

    machine.start("为测试 Stage7 自动归档而设计的复杂需求描述")
    spec_id = storage.get_current_spec_id()

    # 推进 8 次：phase 0→7（finish），第 8 次进入 _archive_on_finish
    for i in range(8):
        machine.next_phase()

    # 账本 archive 段应有 spec
    ledger = storage.get_ledger()
    assert "archive" in ledger, f"archive 段缺失，phase={ledger.get('current_phase')}, spec_id={spec_id}"
    assert spec_id in ledger["archive"], f"spec_id={spec_id} 未归档，archive keys={list(ledger.get('archive',{}).keys())}"
    assert ledger["archive"][spec_id]["final_stage"] == 7
    assert "devflow finish" in ledger["archive"][spec_id]["reason"]


def test_archive_record_files_at(env):
    """archive 段记录完整 files_at 索引"""
    machine, storage, _, tmp_path = env
    _write_spec_and_plan(storage, "spec-X")
    record = storage.archive_spec("spec-X", reason="test files_at")
    fa = record["files_at"]
    assert fa["spec"].endswith("spec-X.yaml")
    assert fa["plan"].endswith("plan-spec-X.yaml")
    # reviews 字段可能存在或不存在（取决于是否有 review dir）


# --- 不破坏 v0.2 兼容 ---

def test_v0_compat_old_ledger_without_archive(env):
    """v0.2 账本无 archive 段时，list_active 正常工作"""
    machine, storage, _, _ = env
    _write_spec_and_plan(storage, "spec-A")
    # 手动删除 archive 段模拟 v0.2 账本
    ledger = storage.get_ledger()
    ledger.pop("archive", None)
    storage._atomic_write_yaml(storage.ledger_path, ledger)

    # 应正常工作（不抛异常）
    active = storage.list_active_specs()
    assert "spec-A" in active
    assert storage.list_archived_specs() == []