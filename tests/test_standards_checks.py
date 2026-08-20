"""Standards 轴检查等价性测试（锁住抽取前后的字节级一致行为）

设计目标：确保从 ReviewEngine._run_standards_checks 抽取到 engine.standards_checks
后，行为完全不变（id / rule / severity / axis / message / fix 一致），且
AUTO_VERIFIABLE_RULES 单一真相源派生正确。

方法：内嵌抽取前（重构前）的原始方法作为 oracle，与抽取后的
run_all_standards_checks 在同一组 fixture 上对比，断言两者输出恒等。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# 让测试在 src-layout 下可被直接 import（CI 应已 pip install -e .）
SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from devflow.model.review import ReviewViolation, ViolationSeverity  # noqa: E402
from devflow.model.spec import Spec  # noqa: E402
from devflow.model.plan import Plan  # noqa: E402
from devflow.engine.review_engine import ReviewEngine  # noqa: E402
from devflow.engine.standards_checks import (  # noqa: E402
    run_all_standards_checks,
    ALL_STANDARD_RULES,
)


# ---------------------------------------------------------------------------
# Oracle：重构前的原始 _run_standards_checks（逐字节复制，不得修改）
# 用于与抽取后的实现做恒等断言。
# ---------------------------------------------------------------------------
def reference_run_standards_checks(artifacts: dict) -> list[ReviewViolation]:
    """执行 Standards 轴自动检查（重构前原始实现，作为对照 oracle）"""
    violations = []
    spec_data = artifacts.get("spec_data", {})

    # 检查 1: Spec 必填字段是否齐全
    try:
        spec = Spec(**spec_data) if spec_data else None
        if spec:
            missing = spec.missing_required_fields()
            if missing:
                violations.append(ReviewViolation(
                    id="S-001",
                    severity=ViolationSeverity.FATAL,
                    axis="standards",
                    rule="spec_completeness",
                    message=f"Spec 必填字段缺失: {', '.join(missing)}",
                    fix="补充 Spec 的必填字段",
                ))
    except Exception as e:
        # pydantic 校验失败时，从错误信息提取缺失字段
        missing = []
        for field in ("non_goals", "goals", "problem"):
            if field in str(e):
                if field == "problem":
                    missing.append("problem (≥10 字符)")
                elif field == "goals":
                    missing.append("goals (非空列表)")
                elif field == "non_goals":
                    missing.append("non_goals (至少 1 项)")
        if not missing:
            missing.append(f"解析错误: {e}")
        violations.append(ReviewViolation(
            id="S-001",
            severity=ViolationSeverity.FATAL,
            axis="standards",
            rule="spec_completeness",
            message=f"Spec 必填字段缺失: {', '.join(missing)}",
            fix="补充 Spec 的必填字段",
        ))

    # 检查 2: problem 长度
    if spec_data and len(spec_data.get("problem", "")) < 10:
        violations.append(ReviewViolation(
            id="S-002",
            severity=ViolationSeverity.FATAL,
            axis="standards",
            rule="problem_length",
            message="problem 字段不足 10 字符，无法准确描述问题",
            fix="扩充 problem 描述至至少 10 字符",
        ))

    # 检查 3: goals 非空
    if spec_data and not spec_data.get("goals"):
        violations.append(ReviewViolation(
            id="S-003",
            severity=ViolationSeverity.FATAL,
            axis="standards",
            rule="goals_required",
            message="goals 列表为空，需要至少 1 个目标",
            fix="在 Spec 中补充 goals",
        ))

    # 检查 4: non_goals 非空
    if spec_data and not spec_data.get("non_goals"):
        violations.append(ReviewViolation(
            id="S-004",
            severity=ViolationSeverity.MAJOR,
            axis="standards",
            rule="non_goals_required",
            message="non_goals 列表为空，缺少非目标定义",
            fix="在 Spec 中补充 non_goals（至少 1 项）",
        ))

    # 检查 5: Plan 中的 Task 完整性
    plan_data = artifacts.get("plan_data")
    if plan_data:
        plan = Plan(**plan_data) if plan_data else None
        if plan and plan.tasks:
            for i, task in enumerate(plan.tasks):
                if not task.module.strip():
                    violations.append(ReviewViolation(
                        id=f"S-{100 + i + 1:03d}",
                        severity=ViolationSeverity.FATAL,
                        axis="standards",
                        rule="task_module_empty",
                        message=f"Task '{task.id}' 的 module 为空",
                        fix="为 Task 指定 module 字段",
                    ))
                if not task.acceptance:
                    violations.append(ReviewViolation(
                        id=f"S-{200 + i + 1:03d}",
                        severity=ViolationSeverity.MAJOR,
                        axis="standards",
                        rule="task_acceptance_empty",
                        message=f"Task '{task.id}' 的 acceptance 为空",
                        fix="为 Task 补充验收标准",
                    ))

    return violations


# 把 violation 列表归一化为可比较的元组集合（顺序无关，符合下游契约）
def _norm(violations: list[ReviewViolation]):
    return sorted(
        (v.id, v.rule, v.severity.value, v.axis, v.message, v.fix)
        for v in violations
    )


# ---------------------------------------------------------------------------
# Fixtures：覆盖全部 6 类检查
# ---------------------------------------------------------------------------
VALID_SPEC = {
    "id": "20260820-test",
    "title": "等价测试 Spec",
    "problem": "这是一个用于等价测试的充分长问题陈述",
    "goals": ["目标一", "目标二"],
    "non_goals": ["非目标一"],
}
VALID_PLAN = {
    "spec_id": "20260820-test",
    "tasks": [
        {"id": "task-1", "title": "t1", "module": "core", "acceptance": ["a1"]},
    ],
}
SPEC_DEFECTS = {
    "id": "20260820-test",
    "title": "等价测试 Spec",
    "problem": "短",            # < 10 字符
    "goals": [],                # 空
    "non_goals": [],            # 空
}
WS_MODULE_PLAN = {
    "spec_id": "20260820-test",
    "tasks": [
        # module 为纯空白，可绕过 min_length=1 但仍触发 strip() 判定
        {"id": "task-1", "title": "t1", "module": " ", "acceptance": ["a1"]},
    ],
}


@pytest.mark.parametrize("spec_data,plan_data,expect_count", [
    (VALID_SPEC, VALID_PLAN, 0),          # 完全合法
    (SPEC_DEFECTS, VALID_PLAN, 4),        # 4 条 spec 违规 (S-001..S-004)
    (VALID_SPEC, WS_MODULE_PLAN, 1),      # 1 条 task module 空白 (S-101)
    (SPEC_DEFECTS, WS_MODULE_PLAN, 5),    # 4 + 1
    ({}, None, 0),                        # 空 artifacts
])
def test_extracted_equals_reference(spec_data, plan_data, expect_count):
    """抽取实现与重构前 oracle 必须逐字段恒等，且数量符合预期。"""
    artifacts = {"spec_data": spec_data, "plan_data": plan_data}
    new_v = run_all_standards_checks(artifacts)
    ref_v = reference_run_standards_checks(artifacts)
    assert _norm(new_v) == _norm(ref_v), (
        f"抽取结果与原始实现不一致:\nNEW={_norm(new_v)}\nREF={_norm(ref_v)}"
    )
    assert len(new_v) == expect_count


def test_auto_verifiable_derived_from_single_source():
    """AUTO_VERIFIABLE_RULES 必须从 ALL_STANDARD_RULES 派生（单一真相源）。"""
    assert ReviewEngine.AUTO_VERIFIABLE_RULES == set(ALL_STANDARD_RULES)
    assert ReviewEngine.AUTO_VERIFIABLE_RULES == {
        "spec_completeness", "problem_length", "goals_required",
        "non_goals_required", "task_module_empty", "task_acceptance_empty",
    }


def test_run_all_returns_same_as_delegating_method():
    """ReviewEngine._run_standards_checks（薄委托）必须等价于直接调用实现。"""
    artifacts = {"spec_data": SPEC_DEFECTS, "plan_data": WS_MODULE_PLAN}
    engine = object.__new__(ReviewEngine)  # 不触发 __init__，仅测委托方法
    delegated = engine._run_standards_checks(artifacts)
    direct = run_all_standards_checks(artifacts)
    assert _norm(delegated) == _norm(direct)
