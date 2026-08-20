"""v0.3.3 思维模型落地验证测试

锁定 9 项思维检查规则的行为(宽松默认: MINOR 提示不阻断):
- 第一性原理: spec.assumptions
- 逆向思维:   spec.premortem(事前验尸)
- 损益思维:   spec.options/decision/tradeoff
- 奥卡姆剃刀: 多 options 提示
- 假设思维:   assumptions → 验证计划提示
- 二八法则:   task.priority P0
- 能力圈:     task.owner_skill learn/collab
- 反馈思维:   task.acceptance 可验证
- 冗余思维:   plan.buffer
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from devflow.model.spec import Spec
from devflow.model.task import Task, TaskPriority
from devflow.model.plan import Plan
from devflow.model.review import ReviewVerdict, ViolationSeverity
from devflow.storage.memory_backend import MemoryStorageBackend
from devflow.policy.loader import load_sop_from_text
from devflow.engine.state_machine import PhaseStateMachine
from devflow.engine.review_engine import ReviewEngine
from devflow.storage.review_store import ReviewStore


SOP_WITH_THINKING = """sop:
  sop_version: "0.1"
  phases: [intake, brainstorm, plan, contract, implement, verify, review, finish]
  intake_fast_skip: true
  red_lines: []
  gates:
    tests_pass: {command: "exit 0", blocking: true, enabled: true, bind_to_stage: 5}
    ci_green: {command: "exit 0", blocking: false, enabled: false, bind_to_stage: 6}
    intake_gate: {kind: triage, require: "ready-for-agent", blocking: true, enabled: true, bind_to_stage: 0}
    review_gate: {kind: "review", blocking: true, enabled: true, bind_to_stage: 2, max_rounds: 5, require_clear: true}
  modules: {facade: "__init__.py", forbidden_import: []}
  tooling: {test_runner: "pytest", import_mode: "importlib", proxy_strip: false}
  storage: {backend: fs, specs_dir: specs, plans_dir: plans, ledger: progress.yaml, glossary: CONTEXT.md, content_address: false}
  allow_fast_forward: false
  thinking:
    enabled: true
    severity: "minor"
"""

SOP_THINKING_DISABLED = """sop:
  sop_version: "0.1"
  phases: [intake, brainstorm, plan, contract, implement, verify, review, finish]
  intake_fast_skip: true
  red_lines: []
  gates:
    tests_pass: {command: "exit 0", blocking: true, enabled: true, bind_to_stage: 5}
    ci_green: {command: "exit 0", blocking: false, enabled: false, bind_to_stage: 6}
    intake_gate: {kind: triage, require: "ready-for-agent", blocking: true, enabled: true, bind_to_stage: 0}
    review_gate: {kind: "review", blocking: true, enabled: true, bind_to_stage: 2, max_rounds: 5, require_clear: true}
  modules: {facade: "__init__.py", forbidden_import: []}
  tooling: {test_runner: "pytest", import_mode: "importlib", proxy_strip: false}
  storage: {backend: fs, specs_dir: specs, plans_dir: plans, ledger: progress.yaml, glossary: CONTEXT.md, content_address: false}
  allow_fast_forward: false
  thinking:
    enabled: false
    severity: "minor"
"""


@pytest.fixture
def env(tmp_path):
    """Phase C: 内存后端 fixture。仅走 StorageBackend 抽象接口。
    ReviewStore(tmp_path) 仍基于文件系统构造（其 write/read 仅在真 fixture 才需要）。
    """
    storage = MemoryStorageBackend(tmp_path)
    storage.init_workspace(SOP_WITH_THINKING)
    config = load_sop_from_text(SOP_WITH_THINKING)
    machine = PhaseStateMachine(storage, config)
    return machine, storage, config, tmp_path


def _setup_spec_and_plan(storage, spec_kwargs=None, tasks=None, buffer=None):
    """建一个 approved spec + plan,便于 review"""
    spec_data = {
        "id": "test-spec",
        "title": "测试 Spec",
        "problem": "这是一个足够长的测试问题描述",
        "goals": ["实现核心功能"],
        "non_goals": ["不实现扩展功能"],
    }
    if spec_kwargs:
        spec_data.update(spec_kwargs)
    storage.write_spec("test-spec", spec_data)
    storage.set_current_spec_id("test-spec")

    if tasks is not None:
        plan_data = {
            "spec_id": "test-spec",
            "tasks": [t.model_dump(mode="json") if hasattr(t, "model_dump") else t for t in tasks],
        }
        if buffer is not None:
            plan_data["buffer"] = buffer
        storage.write_plan("test-plan", plan_data)
        storage.set_current_plan_id("test-plan")


def _run_spec_review(storage, config, tmp_path):
    review_store = ReviewStore(tmp_path)
    engine = ReviewEngine(storage, config, review_store)
    # 直接调 _run_spec_checks(绕过 round 等)
    return engine._run_spec_checks("test-spec")


# --- model 字段存在性 ---

def test_models_have_thinking_fields():
    """v0.3.3: Spec/Task/Plan 应含思维字段"""
    s = Spec(
        id="x", title="t", problem="0123456789",
        goals=["g"], non_goals=["n"],
        assumptions=["底层事实"], premortem=["会失败"], tradeoff="放弃了X",
    )
    assert s.assumptions == ["底层事实"]
    assert s.premortem == ["会失败"]
    assert s.tradeoff == "放弃了X"

    t = Task(id="task-1", title="t", module="m", acceptance=["a"],
             priority=TaskPriority.P0, owner_skill="learn")
    assert t.priority == TaskPriority.P0
    assert t.owner_skill == "learn"

    p = Plan(spec_id="x", buffer=0.2)
    assert p.buffer == 0.2


# --- 9 项思维检查 ---

def test_thinking_missing_fields_produce_minor_violations(env):
    """v0.3.3: 缺失思维字段应产生 MINOR 提示(宽松,不阻断)"""
    _, storage, config, tmp_path = env
    _setup_spec_and_plan(storage, tasks=[Task(id="task-1", title="t", module="m", acceptance=["a"])])

    result = _run_spec_review(storage, config, tmp_path)
    thinking_rules = [v.rule for v in result.violations if v.rule.startswith("thinking_")]

    # 至少应触发: first_principles / premortem / tradeoff_decision / pareto(无P0) / feedback / redundancy
    assert "thinking_first_principles" in thinking_rules
    assert "thinking_premortem" in thinking_rules
    assert "thinking_pareto" in thinking_rules
    assert "thinking_feedback_loop" not in thinking_rules  # acceptance 已填
    assert "thinking_redundancy" in thinking_rules

    # 全部 MINOR,思维提示不参与 FAIL 判定
    for v in result.violations:
        if v.rule.startswith("thinking_"):
            assert v.severity == ViolationSeverity.MINOR
    # 思维提示本身不阻断(FAIL 来自其他 MAJOR 检查如 goal 未覆盖)
    assert all(
        v.severity == ViolationSeverity.MINOR
        for v in result.violations
        if v.rule.startswith("thinking_")
    )


def test_thinking_complete_fields_no_violations(env):
    """v0.3.3: 思维字段齐全时无对应提示"""
    _, storage, config, tmp_path = env
    _setup_spec_and_plan(
        storage,
        spec_kwargs={
            "assumptions": ["用户需要可审计账本"],
            "premortem": ["哈希链破坏导致账本不可用"],
            "options": ["方案A", "方案B"],
            "decision": "方案A",
            "tradeoff": "放弃方案B的简洁性",
        },
        tasks=[Task(id="task-1", title="t", module="m", acceptance=["a"],
                    priority=TaskPriority.P0, owner_skill="core",
                    status="done")],
        buffer=0.2,
    )

    result = _run_spec_review(storage, config, tmp_path)
    thinking_rules = [v.rule for v in result.violations if v.rule.startswith("thinking_")]

    # 这些不应出现(字段已齐全)
    assert "thinking_first_principles" not in thinking_rules
    assert "thinking_premortem" not in thinking_rules
    assert "thinking_tradeoff_decision" not in thinking_rules
    assert "thinking_tradeoff_tradeoff" not in thinking_rules
    assert "thinking_pareto" not in thinking_rules  # P0 已完成
    assert "thinking_redundancy" not in thinking_rules  # buffer=0.2
    # 有 3 个 options 会触发奥卡姆提示(这是预期的宽松提示)
    assert "thinking_occam" in thinking_rules
    # assumptions 非空会触发假设思维提示(有值才提示验证计划)
    assert "thinking_hypothesis" in thinking_rules


def test_thinking_occam_multi_options_warning(env):
    """v0.3.3: 多 options 触发奥卡姆提示"""
    _, storage, config, tmp_path = env
    _setup_spec_and_plan(
        storage,
        spec_kwargs={"options": ["方案A", "方案B", "方案C"], "decision": "方案A", "tradeoff": "x"},
        tasks=[Task(id="task-1", title="t", module="m", acceptance=["a"])],
    )
    result = _run_spec_review(storage, config, tmp_path)
    rules = [v.rule for v in result.violations]
    assert "thinking_occam" in rules


def test_thinking_pareto_unfinished_p0(env):
    """v0.3.3: P0 任务未完成触发二八提示"""
    _, storage, config, tmp_path = env
    _setup_spec_and_plan(
        storage,
        tasks=[Task(id="task-1", title="t", module="m", acceptance=["a"], priority=TaskPriority.P0)],
    )
    result = _run_spec_review(storage, config, tmp_path)
    rules = [v.rule for v in result.violations]
    assert "thinking_pareto" in rules


def test_thinking_capability_outside_task(env):
    """v0.3.3: 圈外任务(learn)触发能力圈提示"""
    _, storage, config, tmp_path = env
    _setup_spec_and_plan(
        storage,
        tasks=[Task(id="task-1", title="t", module="m", acceptance=["a"], owner_skill="learn")],
    )
    result = _run_spec_review(storage, config, tmp_path)
    rules = [v.rule for v in result.violations]
    assert "thinking_capability_circle" in rules


def test_thinking_feedback_missing_acceptance(env):
    """v0.3.3: 无验收标准的任务触发反馈思维提示"""
    _, storage, config, tmp_path = env
    # 先写 spec,再写无 acceptance 的 plan
    storage.write_spec("test-spec", {
        "id": "test-spec", "title": "t",
        "problem": "0123456789", "goals": ["g"], "non_goals": ["n"],
    })
    storage.set_current_spec_id("test-spec")
    storage.write_plan("test-plan", {
        "spec_id": "test-spec",
        "tasks": [{"id": "task-1", "title": "t", "module": "m", "acceptance": []}],
    })
    storage.set_current_plan_id("test-plan")
    result = _run_spec_review(storage, config, tmp_path)
    rules = [v.rule for v in result.violations]
    assert "thinking_feedback_loop" in rules


def test_thinking_redundancy_zero_buffer(env):
    """v0.3.3: buffer=0 触发冗余提示"""
    _, storage, config, tmp_path = env
    _setup_spec_and_plan(
        storage,
        tasks=[Task(id="task-1", title="t", module="m", acceptance=["a"])],
        buffer=0,
    )
    result = _run_spec_review(storage, config, tmp_path)
    rules = [v.rule for v in result.violations]
    assert "thinking_redundancy" in rules


def test_thinking_disabled_in_sop(tmp_path):
    """v0.3.3: thinking.enabled=false 时跳过所有思维检查"""
    storage = MemoryStorageBackend(tmp_path)
    storage.init_workspace(SOP_THINKING_DISABLED)
    config = load_sop_from_text(SOP_THINKING_DISABLED)
    assert config.thinking.enabled is False

    storage.write_spec("test-spec", {
        "id": "test-spec", "title": "t",
        "problem": "0123456789", "goals": ["g"], "non_goals": ["n"],
    })
    storage.set_current_spec_id("test-spec")
    storage.write_plan("test-plan", {
        "spec_id": "test-spec",
        "tasks": [{"id": "task-1", "title": "t", "module": "m", "acceptance": ["a"]}],
    })
    storage.set_current_plan_id("test-plan")

    review_store = ReviewStore(tmp_path)
    engine = ReviewEngine(storage, config, review_store)
    result = engine._run_spec_checks("test-spec")
    rules = [v.rule for v in result.violations]
    thinking_rules = [r for r in rules if r.startswith("thinking_")]
    assert thinking_rules == [], f"thinking.enabled=false 不应有思维提示: {thinking_rules}"