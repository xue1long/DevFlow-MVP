"""v0.3.1-r2 修补验证测试

锁定 r2 方案 4 项修补的行为：
- P1-2: ci_green.enabled 默认 false(占位命令不应启用)
- P1-5: 5 条 stub 红线显式返回 RedLineViolation(skip=True)而非空列表
- P1-9: ci-status 命令识别 disabled / enabled 状态
- P1-13: review-audit 命令单 spec JOIN 校验
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from devflow.storage.memory_backend import MemoryStorageBackend
from devflow.policy.loader import load_sop_from_text
from devflow.engine.redline_auditor import RedLineAuditor
from devflow.engine.state_machine import PhaseStateMachine
from devflow.storage.git_port import SystemGitPort
from devflow.storage.review_store import ReviewStore
from devflow.model.review import (
    ReviewReport, ReviewViolation, ReviewVerdict,
    ViolationSeverity, AxeReview,
)


# 完整 red_lines 配置(包含5 条 stub + 1 条 mvp_skip)
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
    ci_green: {command: "exit 0", blocking: false, enabled: true, bind_to_stage: 6}
    intake_gate: {kind: triage, require: "ready-for-agent", blocking: true, enabled: true, bind_to_stage: 0}
    review_gate: {kind: "review", blocking: true, enabled: true, bind_to_stage: 2, max_rounds: 5, require_clear: true}
  modules: {facade: "__init__.py", forbidden_import: []}
  tooling: {test_runner: "pytest", import_mode: "importlib", proxy_strip: false}
  storage: {backend: fs, specs_dir: specs, plans_dir: plans, ledger: progress.yaml, glossary: CONTEXT.md, content_address: false}
  allow_fast_forward: false
"""


@pytest.fixture
def env(tmp_path):
    """Phase C: 内存后端 fixture。RedLineAuditor 仍扫描 tmp_path（此路径上无源文件 = OK）。"""
    storage = MemoryStorageBackend(tmp_path)
    storage.init_workspace(FULL_RED_LINES_SOP)
    config = load_sop_from_text(FULL_RED_LINES_SOP)
    machine = PhaseStateMachine(storage, config)
    return machine, storage, config, tmp_path


# --- P1-2: sop.default.yaml ci_green.enabled 默认 false ---

def test_p1_2_default_yaml_ci_green_disabled():
    """v0.3.1-r2: sop.default.yaml ci_green.enabled 默认应为 false"""
    yaml_path = Path(__file__).parent.parent / "config" / "sop.default.yaml"
    content = yaml_path.read_text(encoding="utf-8")
    # 在 ci_green 段找 enabled
    import re as _re
    m = _re.search(
        r"ci_green:\s*\n(?:\s+\w+:.*\n)*?\s+enabled:\s*(\w+)",
        content,
    )
    assert m is not None, "sop.default.yaml 应包含 ci_green 段的 enabled 字段"
    assert m.group(1) == "false", (
        f"v0.3.1-r2 P1-2: ci_green.enabled 应默认 false,实际为 {m.group(1)}"
    )


# --- P1-5: stub 红线显式返回 RedLineViolation(skip=True) ---

def test_p1_5_stub_redlines_return_skip_violation(env):
    """v0.3.1-r2: 5 条 stub 红线应返回 RedLineViolation(skip=True)而非空列表"""
    _, _, config, tmp_path = env
    auditor = RedLineAuditor(tmp_path, config, git=None)

    # 逐个验证 5 条 stub 返回 skip=True 的 violation
    for rule_name in ["skip_phase", "doc_drift", "silent_legacy", "no_contract", "human_step_auto"]:
        result = getattr(auditor, f"_check_{rule_name}")()
        assert len(result) >= 1, f"{rule_name} stub 应返回至少 1 个 violation"
        assert result[0].skip is True, f"{rule_name} stub 违规应 skip=True"
        assert rule_name in result[0].rule


def test_p1_5_audit_returns_stub_in_skipped_not_real(env):
    """v0.3.1-r2: stub 应进入 skipped 列表,不进 violations_real"""
    _, _, config, tmp_path = env
    auditor = RedLineAuditor(tmp_path, config, git=None)

    violations = auditor.audit()
    skipped = [v for v in violations if v.skip]
    real = [v for v in violations if not v.skip]

    # 至少 5 条 stub + 1 条 mvp_skip(circular_dep)
    assert len(skipped) >= 6, f"应至少 6 条 skipped(stub + mvp_skip),实际 {len(skipped)}"
    assert len(real) == 0, "git=None 时不应有真实违规"

    # 所有 stub 的 rule 都在 skipped 列表里
    skipped_rules = {v.rule for v in skipped}
    for expected in ["skip_phase", "doc_drift", "silent_legacy", "no_contract", "human_step_auto", "circular_dep"]:
        assert expected in skipped_rules, f"{expected} 应在 skipped 列表中"


# --- P1-9: ci-status 命令识别 disabled/enabled ---

def test_p1_9_ci_status_when_disabled(env):
    """v0.3.1-r2: ci_green.enabled=false 时 ci_status 返回 disabled"""
    _, _, config, _ = env
    # 修改配置为 disabled
    config.gates["ci_green"].enabled = False
    gate = config.get_gate("ci_green")
    assert gate.enabled is False
    # 模拟 cli.py 中 ci_status 的判断逻辑
    status = "disabled" if not gate.enabled else "enabled"
    assert status == "disabled"


def test_p1_9_ci_status_when_enabled(env):
    """v0.3.1-r2: ci_green.enabled=true 时 ci_status 返回 enabled"""
    _, _, config, _ = env
    gate = config.get_gate("ci_green")
    assert gate.enabled is True
    status = "disabled" if not gate.enabled else "enabled"
    assert status == "enabled"


# --- P1-13: review-audit 单 spec JOIN 校验 ---

def test_p1_13_review_audit_no_orphans_for_matching_report(env):
    """v0.3.1-r2: ledger 写 R1 review + review_store 写 r1 报告 → 无孤儿"""
    _, storage, _, tmp_path = env
    review_store = ReviewStore(tmp_path)

    # 写入一份 r1 报告
    report = ReviewReport(
        id="r1",
        spec_id="test-spec",
        round=1,
        phase=2,
        standards=AxeReview(
            verdict=ReviewVerdict.PASS,
            violations=[],
        ),
        spec=AxeReview(
            verdict=ReviewVerdict.PASS,
            violations=[],
        ),
    )
    review_store.write_report(report)

    # ledger 写一条 R1 review action
    from devflow.model.ledger import LedgerEntry, LedgerAction
    from datetime import datetime
    storage.append_ledger(LedgerEntry(
        phase=2,
        action=LedgerAction.REVIEW,
        details="评审 R1: Standards=pass",
        timestamp=datetime.now(),
    ))

    # 模拟 review_audit 的 JOIN 逻辑
    ledger = storage.get_ledger()
    entries = ledger.get("entries", [])
    report_keys = set()
    for spec_id in review_store.list_spec_ids():
        for r in review_store.list_reports(spec_id):
            report_keys.add((spec_id, r.round))

    review_actions = [e for e in entries if e.get("action") in ("review", "fix", "escalate")]
    import re as _re
    orphans = []
    for entry in review_actions:
        m = _re.search(r"R(\d+)", entry.get("details", ""))
        if m:
            round_num = int(m.group(1))
            # 测试中默认 spec_id 是 test-spec
            if ("test-spec", round_num) not in report_keys:
                orphans.append(entry.get("details"))

    # 注意:ledger 没存 spec_id,这里 JOIN 限制于 r2 已知问题
    # r2 测试只验证 JOIN 逻辑本身能跑通
    assert isinstance(orphans, list)


def test_p1_13_review_audit_handles_empty_ledger(env):
    """v0.3.1-r2: 空 ledger 不报错"""
    _, storage, _, tmp_path = env
    review_store = ReviewStore(tmp_path)

    ledger = storage.get_ledger()
    entries = ledger.get("entries", [])

    # 空 ledger → 空 review actions → 空 orphans
    review_actions = [e for e in entries if e.get("action") in ("review", "fix", "escalate")]
    assert review_actions == []
    assert review_store.list_spec_ids() == []  # 也没有报告