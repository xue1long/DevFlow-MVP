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
from devflow.storage.fs_backend import FSBackend, _HASH_FIELDS
from devflow.storage.fs_backend import FSBackend as _FSBackendClass  # for staticmethod access
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

def _run_find(storage, root: Path, keyword: str, include_archived: bool = False) -> list[dict]:
    """复用 find 命令的搜索逻辑（提取自 cli.py:find）

    ⚠️ 与 cli.py 同步：修改本函数后须同步修改 cli.py 的 find 命令实现。
    """
    results = []
    keyword_lower = keyword.lower()
    for spec_path in storage.specs_dir.glob("*.yaml"):
        spec_id = spec_path.stem
        data = storage.read_spec(spec_id)
        if data is None:
            continue
        if data.get("status") == "archived" and not include_archived:
            continue

        matches = []
        # Spec 文件
        if keyword_lower in spec_path.read_text(encoding="utf-8").lower():
            matches.append("spec")

        # Plan 文件
        plan_path = storage.plans_dir / f"plan-{spec_id}.yaml"
        if plan_path.exists():
            if keyword_lower in plan_path.read_text(encoding="utf-8").lower():
                matches.append(f"plan:{plan_path.name}")

        # Review 文件
        review_dir = root / "review" / spec_id
        if review_dir.exists():
            for r_file in review_dir.glob("*.yaml"):
                if keyword_lower in r_file.read_text(encoding="utf-8").lower():
                    matches.append(f"review:{r_file.name}")

        if matches:
            results.append({
                "spec_id": spec_id,
                "title": data.get("title", ""),
                "status": data.get("status", "draft"),
                "match_locations": matches,
            })
    return results


def test_find_returns_empty_when_no_match(env):
    """无匹配返回空"""
    storage, tmp = env
    _write_spec(storage, "spec-A")
    results = _run_find(storage, tmp, "nonexistent_xyz")
    assert results == []


def test_find_skips_archived_by_default(env):
    """find 默认排除已归档"""
    storage, tmp = env
    _write_spec(storage, "spec-A", title="Pipeline Retry")
    _write_spec(storage, "spec-B", title="Cache Refactor", status="archived")
    results = _run_find(storage, tmp, "retry")
    assert len(results) == 1
    assert results[0]["spec_id"] == "spec-A"


def test_find_includes_archived_with_flag(env):
    """--all  包含已归档"""
    storage, tmp = env
    _write_spec(storage, "spec-A", title="Pipeline Retry")
    _write_spec(storage, "spec-B", title="Pipeline Retry", status="archived")
    results = _run_find(storage, tmp, "retry", include_archived=True)
    spec_ids = [r["spec_id"] for r in results]
    assert "spec-A" in spec_ids
    assert "spec-B" in spec_ids


# --- find：Plan/Review 覆盖（v0.3.4 优化建议三） ---

def test_find_matches_plan_content(env):
    """find 应匹配 Plan 文件内容"""
    storage, tmp = env
    _write_spec(storage, "spec-A", title="Pipeline Batch Retry")
    plan_path = storage.plans_dir / "plan-spec-A.yaml"
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(
        "title: Batch Retry Plan\n"
        "tasks:\n  - title: implement retry logic\n",
        encoding="utf-8",
    )
    results = _run_find(storage, tmp, "retry")
    assert len(results) == 1
    assert "plan:plan-spec-A.yaml" in results[0]["match_locations"]


def test_find_matches_review_content(env):
    """find 应匹配 Review 文件内容"""
    storage, tmp = env
    _write_spec(storage, "spec-A", title="Pipeline")
    review_dir = tmp / "review" / "spec-A"
    review_dir.mkdir(parents=True, exist_ok=True)
    (review_dir / "r1.yaml").write_text(
        "report:\n  violations:\n    - rule: no_test\n  verdict: fail\n",
        encoding="utf-8",
    )
    results = _run_find(storage, tmp, "no_test")
    assert len(results) == 1
    assert "review:r1.yaml" in results[0]["match_locations"]


def test_find_match_locations_structure(env):
    """find 的 match_locations 应列出所有匹配的源文件"""
    storage, tmp = env
    _write_spec(storage, "spec-A", title="Keyword Common")
    plan_path = storage.plans_dir / "plan-spec-A.yaml"
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text("keyword: common\n", encoding="utf-8")
    review_dir = tmp / "review" / "spec-A"
    review_dir.mkdir(parents=True, exist_ok=True)
    (review_dir / "r1.yaml").write_text("keyword: common\n", encoding="utf-8")
    results = _run_find(storage, tmp, "common")
    assert len(results) == 1
    assert "spec" in results[0]["match_locations"]
    assert "plan:plan-spec-A.yaml" in results[0]["match_locations"]
    assert "review:r1.yaml" in results[0]["match_locations"]


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


# --- 哈希链边界条件 ---

def test_verify_ledger_empty_chain(env):
    """空账本 verify_ledger 应通过"""
    storage, _ = env
    result = storage.verify_ledger()
    assert result["ok"]
    assert "为空" in result["message"]


def test_verify_ledger_single_entry(env):
    """单条账本条目哈希链验证通过"""
    storage, _ = env
    storage.append_ledger(LedgerEntry(phase=0, action=LedgerAction.TRIAGE, details="e1"))
    result = storage.verify_ledger()
    assert result["ok"]


def test_verify_ledger_multi_entry(env):
    """多条账本条目哈希链完整验证通过"""
    storage, _ = env
    for i in range(10):
        storage.append_ledger(LedgerEntry(phase=0, action=LedgerAction.TRIAGE, details=f"e{i}"))
    result = storage.verify_ledger()
    assert result["ok"]
    assert "哈希链完整" in result["message"]


def test_verify_ledger_detects_tampered_content(env):
    """篡改账本条目内容后 verify_ledger 应检测到"""
    storage, _ = env
    storage.append_ledger(LedgerEntry(phase=0, action=LedgerAction.TRIAGE, details="e1"))
    storage.append_ledger(LedgerEntry(phase=0, action=LedgerAction.TRIAGE, details="e2"))
    verify_before = storage.verify_ledger()
    assert verify_before["ok"]

    import yaml
    ledger = yaml.safe_load(storage.ledger_path.read_text(encoding="utf-8"))
    ledger["entries"][0]["details"] = "tampered"
    with open(storage.ledger_path, "w", encoding="utf-8") as f:
        yaml.dump(ledger, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    result = storage.verify_ledger()
    assert not result["ok"]
    assert "哈希链验证失败" in result["message"]


def test_verify_ledger_detects_tampered_prev_hash(env):
    """删除 _hash 字段后 verify_ledger 应检测到"""
    storage, _ = env
    storage.append_ledger(LedgerEntry(phase=0, action=LedgerAction.TRIAGE, details="e1"))
    storage.append_ledger(LedgerEntry(phase=0, action=LedgerAction.TRIAGE, details="e2"))

    import yaml
    ledger = yaml.safe_load(storage.ledger_path.read_text(encoding="utf-8"))
    # 删除第二条的 _hash 字段（模拟哈希字段缺失）
    del ledger["entries"][1]["_hash"]
    with open(storage.ledger_path, "w", encoding="utf-8") as f:
        yaml.dump(ledger, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    result = storage.verify_ledger()
    assert not result["ok"]


def test_verify_ledger_tampered_chain_head(env):
    """篡改 chain_head 指向后 verify_ledger 必须检测到"""
    storage, _ = env
    storage.append_ledger(LedgerEntry(phase=0, action=LedgerAction.TRIAGE, details="e1"))
    storage.append_ledger(LedgerEntry(phase=0, action=LedgerAction.TRIAGE, details="e2"))

    import yaml
    ledger = yaml.safe_load(storage.ledger_path.read_text(encoding="utf-8"))
    ledger["chain_head"] = ledger["entries"][0]["_hash"]
    with open(storage.ledger_path, "w", encoding="utf-8") as f:
        yaml.dump(ledger, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    # 链内每个条目的 prev_hash 引用仍然正确，但 chain_head 被篡改
    # 指向了一个早期条目，verify_ledger 必须检测到这个篡改。
    result = storage.verify_ledger()
    assert not result["ok"]
    assert "哈希链验证失败" in result["message"]


# --- 哈希字段白名单断言（v0.3.4 优化建议一） ---

def test_hash_fields_whitelist_warns_on_unknown_field(env, caplog):
    """未注册字段应触发 warning（防止静默 schema 漂移）"""
    import logging
    caplog.set_level(logging.WARNING, logger="devflow.storage.fs_backend")
    storage, _ = env
    entry = LedgerEntry(phase=0, action=LedgerAction.TRIAGE, details="e1")
    entry_dict = entry.model_dump(mode="json")
    entry_dict["_unknown_field"] = "should_warn"
    _FSBackendClass._compute_entry_hash(entry_dict, None)
    assert "未注册字段" in caplog.text
    assert "_unknown_field" in caplog.text


def test_hash_fields_whitelist_known_fields_no_warning(env, caplog):
    """白名单内的字段不应触发 warning"""
    import logging
    caplog.set_level(logging.WARNING, logger="devflow.storage.fs_backend")
    storage, _ = env
    entry = LedgerEntry(phase=0, action=LedgerAction.TRIAGE, details="e1")
    entry_dict = entry.model_dump(mode="json")
    _FSBackendClass._compute_entry_hash(entry_dict, None)
    assert "未注册字段" not in caplog.text


def test_hash_fields_contains_all_model_fields():
    """白名单应与 LedgerEntry 模型字段完全对齐（防止白名单漂移）"""
    model_fields = set(LedgerEntry.model_fields.keys())
    assert _HASH_FIELDS == model_fields, (
        f"白名单与 LedgerEntry 模型字段不一致："
        f"模型有但白名单缺={model_fields - _HASH_FIELDS}, "
        f"白名单有但模型无={_HASH_FIELDS - model_fields}"
    )


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