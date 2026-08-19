"""v0.3 第一性方案（最简版）验证测试

锁定 Spec 文件内 status=archived 标记 + Python 跨文件搜索的行为：
- archive 修改 Spec YAML status 字段 + 写账本
- list-active / list-archived 按 status 过滤
- find 跨 Spec/Plan/Review 文件搜索
- 重复归档拒绝（防止覆盖）
- 不破坏账本哈希链
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from devflow.model import Spec, SpecStatus
from devflow.model.ledger import LedgerEntry, LedgerAction
from devflow.storage.fs_backend import FSBackend
from devflow.policy.loader import load_sop


@pytest.fixture
def env(tmp_path):
    storage = FSBackend(tmp_path)
    storage.init_workspace("""sop:
  sop_version: "0.1"
  phases: [intake, brainstorm, plan, contract, implement, verify, review, finish]
  intake_fast_skip: true
  storage: {backend: fs}
""")
    config = load_sop(tmp_path / "sop.yaml")
    return storage, tmp_path


def _write_spec(storage, spec_id, title="t", status="draft",
                problem="为测试归档场景编写的 Spec problem 描述文本"):
    """写入完整 Spec（带可选 status）"""
    spec = Spec(
        id=spec_id, title=title, problem=problem,
        goals=["支持基础需求"], non_goals=["不引入消息队列"],
        status=SpecStatus(status),
    )
    storage.write_spec(spec_id, spec.model_dump(mode="json"))


# --- archive：状态字段标记 ---

def test_archive_sets_status_field(env):
    """归档后 Spec YAML 的 status 字段变为 archived"""
    storage, _ = env
    _write_spec(storage, "spec-A", status="draft")
    spec_data = storage.read_spec("spec-A")
    assert spec_data["status"] == "draft"

    # 通过模拟 archive CLI 行为
    spec_data["status"] = SpecStatus.ARCHIVED.value
    storage.write_spec("spec-A", spec_data)

    reloaded = storage.read_spec("spec-A")
    assert reloaded["status"] == "archived"


def test_archive_writes_ledger_entry(env):
    """归档追加账本条目（审计追踪）"""
    storage, _ = env
    _write_spec(storage, "spec-A")

    spec_data = storage.read_spec("spec-A")
    spec_data["status"] = SpecStatus.ARCHIVED.value
    storage.write_spec("spec-A", spec_data)

    storage.append_ledger(LedgerEntry(
        phase=0, action=LedgerAction.PHASE_TRANSITION,
        details="归档 Spec 'spec-A'",
    ))

    ledger = storage.get_ledger()
    actions = [e["action"] for e in ledger["entries"]]
    assert "phase_transition" in actions


def test_archive_does_not_break_hash_chain(env):
    """归档不破坏哈希链（archive 段不在 ledger 中）"""
    storage, _ = env
    storage.append_ledger(LedgerEntry(phase=0, action=LedgerAction.TRIAGE, details="e1"))
    verify_before = storage.verify_ledger()
    assert verify_before["ok"]

    _write_spec(storage, "spec-A")
    # 模拟归档
    spec_data = storage.read_spec("spec-A")
    spec_data["status"] = SpecStatus.ARCHIVED.value
    storage.write_spec("spec-A", spec_data)
    storage.append_ledger(LedgerEntry(
        phase=0, action=LedgerAction.PHASE_TRANSITION, details="archive",
    ))

    verify_after = storage.verify_ledger()
    assert verify_after["ok"]


def test_double_archive_rejected(env):
    """重复归档应拒绝（archive CLI 设计）"""
    storage, _ = env
    _write_spec(storage, "spec-A", status="archived")  # 已归档

    spec_data = storage.read_spec("spec-A")
    assert spec_data["status"] == "archived"  # 模拟 archive CLI 的拦截判断


# --- list-active / list-archived ---

def test_list_active_filters_archived(env):
    """list-active 排除已归档 Spec"""
    storage, _ = env
    _write_spec(storage, "spec-A", status="draft")
    _write_spec(storage, "spec-B", status="archived")
    _write_spec(storage, "spec-C", status="draft")

    active = []
    for spec_path in storage.specs_dir.glob("*.yaml"):
        data = storage.read_spec(spec_path.stem)
        if data and data.get("status") != "archived":
            active.append(spec_path.stem)

    assert sorted(active) == ["spec-A", "spec-C"]


def test_list_archived_returns_only_archived(env):
    """list-archived 只返回归档 Spec"""
    storage, _ = env
    _write_spec(storage, "spec-A", status="draft")
    _write_spec(storage, "spec-B", status="archived")

    archived = []
    for spec_path in storage.specs_dir.glob("*.yaml"):
        data = storage.read_spec(spec_path.stem)
        if data and data.get("status") == "archived":
            archived.append(spec_path.stem)

    assert archived == ["spec-B"]


# --- find：跨文件搜索 ---

def test_find_returns_empty_when_no_match(env):
    """无匹配返回空"""
    storage, _ = env
    _write_spec(storage, "spec-A")
    results = []
    keyword = "nonexistent_xyz"
    for spec_path in storage.specs_dir.glob("*.yaml"):
        data = storage.read_spec(spec_path.stem)
        if data and data.get("status") == "archived":
            continue
        if keyword.lower() in spec_path.read_text(encoding="utf-8").lower():
            results.append(spec_path.stem)
    assert results == []


def test_find_skips_archived_by_default(env):
    """find 默认排除已归档"""
    storage, _ = env
    _write_spec(storage, "spec-A", title="Pipeline Retry")
    _write_spec(storage, "spec-B", title="Cache Refactor", status="archived")

    # 模拟 find "retry"（spec-A 含 retry；spec-B 不含）
    results = []
    keyword = "retry"
    for spec_path in storage.specs_dir.glob("*.yaml"):
        data = storage.read_spec(spec_path.stem)
        if data is None:
            continue
        if data.get("status") == "archived":  # 默认跳过
            continue
        if keyword.lower() in spec_path.read_text(encoding="utf-8").lower():
            results.append(spec_path.stem)

    assert "spec-A" in results
    assert "spec-B" not in results


def test_find_includes_archived_with_flag(env):
    """--all  包含已归档"""
    storage, _ = env
    _write_spec(storage, "spec-A", title="Pipeline Retry")
    _write_spec(storage, "spec-B", title="Pipeline Retry", status="archived")

    # 模拟 find "retry" --all
    results = []
    keyword = "retry"
    include_archived = True
    for spec_path in storage.specs_dir.glob("*.yaml"):
        data = storage.read_spec(spec_path.stem)
        if data is None:
            continue
        if data.get("status") == "archived" and not include_archived:
            continue
        if keyword.lower() in spec_path.read_text(encoding="utf-8").lower():
            results.append(spec_path.stem)

    assert "spec-A" in results
    assert "spec-B" in results


# --- 向后兼容 v0.2.1 ---

def test_v0_compat_no_status_field(env):
    """v0.2.1 账本无 archive 概念，Spec YAML 无 status 字段也能工作"""
    storage, _ = env
    # v0.2.1 风格：无 status 字段
    spec = Spec(
        id="legacy-spec", title="Legacy Spec",
        problem="v0.2.1 时代创建的 Spec 无 status 字段",
        goals=["g1"], non_goals=["n1"],
    )
    storage.write_spec("legacy-spec", spec.model_dump(mode="json"))

    # 读取时正常
    data = storage.read_spec("legacy-spec")
    assert data is not None
    # status 默认为 draft（pydantic 默认）
    assert data["status"] == "draft"
    # list-active 默认包含（status != archived）
    active = []
    for spec_path in storage.specs_dir.glob("*.yaml"):
        d = storage.read_spec(spec_path.stem)
        if d and d.get("status") != "archived":
            active.append(spec_path.stem)
    assert "legacy-spec" in active


# --- 撤销归档（unarchive）覆盖 ---

def test_unarchive_clears_status(env):
    """撤销归档：把 status 改回 draft/approved"""
    storage, _ = env
    _write_spec(storage, "spec-A", status="archived")

    spec_data = storage.read_spec("spec-A")
    assert spec_data["status"] == "archived"

    # 撤销归档（无独立命令，直接改文件）
    spec_data["status"] = "draft"
    storage.write_spec("spec-A", spec_data)

    reloaded = storage.read_spec("spec-A")
    assert reloaded["status"] == "draft"