"""审核闭环验收测试（13 条）

覆盖 v0.2 审核闭环的完整生命周期：
review → fix → review → 终止判断。

Plan C: ReviewStore 抽为 ReviewStorageBackend ABC，17/20 测试切到
MemoryReviewBackend（fixture 默认），3/20 仍用 FSReviewBackend（断言
真实 YAML 文件存在性）。
"""
import sys
from pathlib import Path
from typing import Optional

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from devflow.model import Spec, SpecStatus, Plan, Task, TaskStatus, Contract
from devflow.model.review import ReviewReport, FixRecord, ReviewVerdict, ViolationSeverity, AxeReview
from devflow.model import LedgerEntry, LedgerAction
from devflow.storage.fs_backend import FSBackend
from devflow.storage.memory_backend import MemoryStorageBackend
from devflow.storage.review_store import FSReviewBackend
from devflow.storage.review_store_memory import MemoryReviewBackend
from devflow.policy.loader import load_sop, load_sop_from_text, SOPConfig
from devflow.engine.review_engine import ReviewEngine
from devflow.engine.state_machine import PhaseStateMachine
from devflow.verify.gate_runner import GateRunner


SOP = """sop:
  sop_version: "0.1"
  phases: [intake, brainstorm, plan, contract, implement, verify, review, finish]
  intake_fast_skip: true
  red_lines: [no_test]
  gates:
    tests_pass: {command: "exit 0", blocking: true, enabled: true, bind_to_stage: 5}
    ci_green: {command: "exit 0", blocking: false, enabled: true, bind_to_stage: 6}
    intake_gate: {kind: triage, require: "ready-for-agent", blocking: true, enabled: true, bind_to_stage: 0}
    review_gate: {kind: "review", blocking: true, enabled: true, bind_to_stage: 2, max_rounds: 5, require_clear: true}
  tooling: {proxy_strip: false}
  storage: {backend: fs}
"""


@pytest.fixture
def env(tmp_path):
    """Plan C 默认 fixture: MemoryStorageBackend + MemoryReviewBackend（无文件 I/O）

    适用于不需要断言真实 YAML 文件存在性的所有测试。
    """
    storage = MemoryStorageBackend(tmp_path)
    storage.init_workspace(SOP)
    config = load_sop_from_text(SOP)
    review_store = MemoryReviewBackend(tmp_path)
    engine = ReviewEngine(storage, config, review_store)
    gate_runner = GateRunner(config, str(tmp_path), review_engine=engine)
    machine = PhaseStateMachine(storage, config, gate_runner=gate_runner, review_engine=engine)
    return engine, storage, config, review_store, machine, tmp_path


@pytest.fixture
def fs_env(tmp_path):
    """fs_env 例外 fixture: FSBackend + FSReviewBackend 真件 — 用于断言文件落地的 3 条测试。"""
    storage = FSBackend(tmp_path)
    storage.init_workspace(SOP)
    config = load_sop(tmp_path / "sop.yaml")
    review_store = FSReviewBackend(tmp_path)
    engine = ReviewEngine(storage, config, review_store)
    gate_runner = GateRunner(config, str(tmp_path), review_engine=engine)
    machine = PhaseStateMachine(storage, config, gate_runner=gate_runner, review_engine=engine)
    return engine, storage, config, review_store, machine, tmp_path


def _create_spec_and_plan(env, complete_spec: bool = True):
    """创建 Spec + Plan，可选完整/不完整"""
    engine, storage, config, review_store, machine, root = env
    machine.start("为 pipeline 增加 batch 重试")
    spec_id = storage.get_current_spec_id()

    if not complete_spec:
        # 写入一个真正不完整的 Spec（缺必填字段）
        storage.write_spec(spec_id, {
            "id": spec_id,
            "title": "Pipeline Batch Retry",
            "problem": "短",
            "goals": [],
            "non_goals": [],
            "status": "draft",
        })
    else:
        spec = Spec(
            id=spec_id,
            title="Pipeline Batch Retry",
            problem="当前 pipeline 无重试机制，失败即中断，需要增加 batch 粒度的重试",
            goals=["支持 batch 级重试"],
            non_goals=["不引入消息队列"],
        )
        storage.write_spec(spec_id, spec.model_dump(mode="json"))

    plan = Plan(
        spec_id=spec_id,
        tasks=[Task(
            id="task-1", title="T1", module="pipeline",
            acceptance=["支持 batch 级重试"],
            # P0-4: 始终添加 Contract，避免 spec_contract_missing 干扰其他测试
            contract={"module": "pipeline", "interface_signature": "retry_batch()"},
        )],
    )
    storage.write_plan("p1", plan.model_dump(mode="json"))
    storage.set_current_plan_id("p1")
    return spec_id, "p1"


class TestReviewEngine:
    def test_1_review_creates_report(self, fs_env):  # Plan C: fs_env 验证 .yaml 真的写出来了
        engine, storage, config, review_store, machine, root = fs_env
        spec_id, _ = _create_spec_and_plan(fs_env)
        result = engine.review(spec_id=spec_id)
        assert result["ok"]
        assert (root / "review" / spec_id / "r1.yaml").exists()

    def test_2_report_has_two_axes(self, env):
        engine, storage, config, review_store, machine, root = env
        spec_id, _ = _create_spec_and_plan(env)
        result = engine.review(spec_id=spec_id)
        report = result["report"]
        assert "standards" in report
        assert "spec" in report

    def test_3_violations_severity_graded(self, env):
        engine, storage, config, review_store, machine, root = env
        spec_id, _ = _create_spec_and_plan(env, complete_spec=False)
        result = engine.review(spec_id=spec_id)
        report = result["report"]
        # 不完整 Spec 应有 fatal 违规
        assert result["fatal"] > 0

    def test_4_fatal_blocks_advance(self, env):
        engine, storage, config, review_store, machine, root = env
        spec_id, _ = _create_spec_and_plan(env, complete_spec=False)
        result = engine.review(spec_id=spec_id)
        assert not result["can_advance"]
        # review_gate 应阻断
        gate = engine.check_review_gate(spec_id)
        assert not gate["ok"]

    def test_5_no_fatal_allows_advance(self, env):
        engine, storage, config, review_store, machine, root = env
        spec_id, _ = _create_spec_and_plan(env, complete_spec=True)
        result = engine.review(spec_id=spec_id)
        assert result["can_advance"]
        gate = engine.check_review_gate(spec_id)
        assert gate["ok"]

    def test_6_fix_records_report(self, fs_env):  # Plan C: fs_env 验证 f1.yaml 真的写出来了
        engine, storage, config, review_store, machine, root = fs_env
        spec_id, _ = _create_spec_and_plan(fs_env, complete_spec=False)
        result = engine.review(spec_id=spec_id)
        latest = review_store.latest_report(spec_id)
        violations = [v for v in latest._all_violations()
                      if v.severity == ViolationSeverity.MAJOR]
        if not violations:
            pytest.skip("无 major 违规可修复")

        # 先真正修复 Spec（补全必填字段），再标记修复
        spec = Spec(
            id=spec_id,
            title="Pipeline Batch Retry",
            problem="当前 pipeline 无重试机制，失败即中断，需要增加 batch 粒度的重试",
            goals=["支持 batch 级重试"],
            non_goals=["不引入消息队列"],
        )
        storage.write_spec(spec_id, spec.model_dump(mode="json"))

        vid = violations[0].id
        fix_result = engine.fix([vid], summary="已补全 Spec 必填字段")
        assert fix_result["ok"]
        assert (root / "review" / spec_id / "f1.yaml").exists()

    def test_7_round2_does_not_overwrite_r1(self, fs_env):  # Plan C: fs_env 验证 r1.yaml + r2.yaml 都落地
        engine, storage, config, review_store, machine, root = fs_env
        spec_id, _ = _create_spec_and_plan(fs_env, complete_spec=True)
        engine.review(spec_id=spec_id)
        engine.review(spec_id=spec_id)
        # 轮次自动递增
        assert (root / "review" / spec_id / "r1.yaml").exists()
        assert (root / "review" / spec_id / "r2.yaml").exists()

    def test_8_max_rounds_escalates(self, env):
        engine, storage, config, review_store, machine, root = env
        spec_id, _ = _create_spec_and_plan(env, complete_spec=False)
        # 反复评审直到超过 max_rounds
        for _ in range(engine.MAX_REVIEW_ROUNDS + 2):
            engine.review(spec_id=spec_id)
        latest = review_store.latest_report(spec_id)
        assert latest.status == "escalated"
        # escalated 状态允许推进（不阻断，但需要人工介入）
        assert latest.can_advance()

    def test_9_ledger_has_review_entries(self, env):
        engine, storage, config, review_store, machine, root = env
        spec_id, _ = _create_spec_and_plan(env, complete_spec=False)
        engine.review(spec_id=spec_id)
        ledger = storage.get_ledger()
        actions = [e["action"] for e in ledger["entries"]]
        assert "review" in actions

    def test_10_history_shows_timeline(self, env):
        engine, storage, config, review_store, machine, root = env
        spec_id, _ = _create_spec_and_plan(env, complete_spec=False)
        engine.review(spec_id=spec_id)
        history = engine.history(spec_id)
        assert history["ok"]
        assert history["total_reviews"] >= 1
        assert any(t["type"] == "review" for t in history["timeline"])

    def test_11_residual_can_be_registered(self, env):
        engine, storage, config, review_store, machine, root = env
        spec_id, _ = _create_spec_and_plan(env, complete_spec=False)
        result = engine.review(spec_id=spec_id)
        latest = review_store.latest_report(spec_id)
        violations = [v for v in latest._all_violations() if v.severity == ViolationSeverity.MINOR]
        if not violations:
            pytest.skip("无 minor 违规可登记")
        vid = violations[0].id
        fix_result = engine.fix([vid], residual=True)
        assert fix_result["ok"]
        assert fix_result["residual"] == [vid]

    def test_12_review_gate_in_state_machine(self, env):
        engine, storage, config, review_store, machine, root = env
        spec_id, _ = _create_spec_and_plan(env, complete_spec=False)
        # 未评审时 gate 2 应阻断
        gate = machine.run_gate(2)
        assert not gate["ok"]
        # review_gate 应出现在结果中
        gate_names = [g["gate"] for g in gate["gates"]]
        assert "review_gate" in gate_names

    def test_13_complete_loop_review_fix_review(self, env):
        engine, storage, config, review_store, machine, root = env
        spec_id, _ = _create_spec_and_plan(env, complete_spec=False)
        # 第 1 轮评审失败
        r1 = engine.review(spec_id=spec_id)
        assert not r1["can_advance"]

        # 修复 Spec（补全必填字段）
        spec = Spec(
            id=spec_id,
            title="Pipeline Batch Retry",
            problem="当前 pipeline 无重试机制，失败即中断，需要增加 batch 粒度的重试",
            goals=["支持 batch 级重试"],
            non_goals=["不引入消息队列"],
        )
        storage.write_spec(spec_id, spec.model_dump(mode="json"))

        # 修复违规
        latest = review_store.latest_report(spec_id)
        violations = [v for v in latest._all_violations() if v.rule in ("spec_completeness", "problem_length", "goals_required")]
        engine.fix([v.id for v in violations], summary="已补全 Spec 必填字段")

        # 第 2 轮评审
        r2 = engine.review(spec_id=spec_id)
        assert r2["can_advance"]

        # 历史记录应显示完整闭环
        history = engine.history(spec_id)
        review_types = [t["type"] for t in history["timeline"]]
        assert review_types.count("review") >= 2
        assert "fix" in review_types

    # --- 防死循环专项测试 ---

    def test_14_fix_verifies_real_fix(self, env):
        """fix 必须通过验证才标记 resolved——防止'假修复'死循环"""
        engine, storage, config, review_store, machine, root = env
        spec_id, _ = _create_spec_and_plan(env, complete_spec=False)
        r1 = engine.review(spec_id=spec_id)
        assert not r1["can_advance"]

        # 不真正修复 Spec，直接调用 fix → 应被拒绝
        latest = review_store.latest_report(spec_id)
        fn_violations = [v for v in latest._all_violations()
                         if v.rule in ("spec_completeness", "problem_length", "goals_required")]
        result = engine.fix([v.id for v in fn_violations], summary="假装修好了")
        assert not result["ok"]
        assert "未通过验证" in result["message"]

        # 验证违规仍是 unresolved
        latest2 = review_store.latest_report(spec_id)
        still_open = [v for v in latest2._all_violations() if not v.resolved]
        assert len(still_open) >= len(fn_violations)

    def test_15_stagnation_escalates_early(self, env):
        """违规数连续不降 → 提前升级，不空耗轮次"""
        engine, storage, config, review_store, machine, root = env
        spec_id, _ = _create_spec_and_plan(env, complete_spec=False)

        # 连续评审，始终保持不完整 Spec（违规数不降）
        counts = []
        for _ in range(2):
            r = engine.review(spec_id=spec_id)
            counts.append(r["total_violations"])

        # 第 3 次评审应触发停滞升级（征用了第 3 轮）
        r3 = engine.review(spec_id=spec_id)
        assert r3.get("escalated") is True
        assert r3.get("reason") == "stagnation"

        latest = review_store.latest_report(spec_id)
        assert latest.status == "escalated"

    def test_16_regression_detection(self, env):
        """已修复的规则再次出现 → 回归警告"""
        engine, storage, config, review_store, machine, root = env
        spec_id, _ = _create_spec_and_plan(env, complete_spec=False)
        r1 = engine.review(spec_id=spec_id)

        # 先修复（真正补全 Spec）
        spec = Spec(
            id=spec_id,
            title="Pipeline Batch Retry",
            problem="当前 pipeline 无重试机制，失败即中断，需要增加 batch 粒度的重试",
            goals=["支持 batch 级重试"],
            non_goals=["不引入消息队列"],
        )
        storage.write_spec(spec_id, spec.model_dump(mode="json"))
        latest = review_store.latest_report(spec_id)
        fn_violations = [v for v in latest._all_violations()
                         if v.rule in ("spec_completeness", "problem_length", "goals_required")]
        engine.fix([v.id for v in fn_violations], summary="已补全")

        # 第 2 轮评审（现在 Spec 完整，无违规）
        r2 = engine.review(spec_id=spec_id)
        assert r2["can_advance"]

        # 故意制造回归：把 Spec 改回不完整
        storage.write_spec(spec_id, {
            "id": spec_id,
            "title": "Pipeline Batch Retry",
            "problem": "短",
            "goals": [],
            "non_goals": [],
            "status": "draft",
        })

        # 第 3 轮评审 → 应检测到回归
        r3 = engine.review(spec_id=spec_id)
        assert "regression_warnings" in r3
        assert len(r3["regression_warnings"]) > 0
        rules = [w["rule"] for w in r3["regression_warnings"]]
        assert "spec_completeness" in rules


# --- 模型级测试 ---

class TestReviewModels:
    def test_report_verdict_pass(self):
        r = ReviewReport(
            id="r1", spec_id="s1", round=1, phase=2,
            standards=AxeReview(verdict=ReviewVerdict.PASS),
            spec=AxeReview(verdict=ReviewVerdict.PASS),
        )
        assert r.verdict == ReviewVerdict.PASS
        assert r.can_advance()

    def test_report_verdict_fail_on_fatal(self):
        r = ReviewReport(
            id="r1", spec_id="s1", round=1, phase=2,
            standards=AxeReview(violations=[
                __import__("devflow.model.review", fromlist=["ReviewViolation"]).ReviewViolation(
                    id="S-001", axis="standards", rule="x",
                    severity=ViolationSeverity.FATAL, message="fatal issue"
                )
            ]),
            spec=AxeReview(verdict=ReviewVerdict.PASS),
        )
        assert r.verdict == ReviewVerdict.FAIL
        assert not r.can_advance()
        assert r.fatal_count == 1

    def test_report_verdict_escalated(self):
        r = ReviewReport(
            id="r6", spec_id="s1", round=6, phase=2, status="escalated",
            standards=AxeReview(verdict=ReviewVerdict.ESCALATED),
            spec=AxeReview(verdict=ReviewVerdict.ESCALATED),
        )
        assert r.verdict == ReviewVerdict.ESCALATED

    def test_fix_record_creation(self):
        f = FixRecord(id="f1", review_id="r1", resolved_violations=["S-001"])
        assert f.id == "f1"
        assert f.review_id == "r1"
