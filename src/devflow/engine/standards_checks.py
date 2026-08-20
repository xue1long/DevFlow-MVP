"""Standards 轴自动检查（从 ReviewEngine._run_standards_checks 抽取）

纯函数集合：每个检查接收 artifacts dict，返回 ReviewViolation 列表。
抽取不改变任何 id / rule / severity / axis / message / fix，保持字节级一致
（详见 downstream-consumer-enumeration.md 契约）。

设计约束（来自下游消费方枚举的反馈环）：
- `rule` 名永久冻结（跨账本回归检测比对历史 resolved rule）；
- 顺序无关（verdict 判空 / 回归用 set / fix 用 id / 计数用 len），故检查可自由排列；
- ALL_STANDARD_RULES 为单一真相源，供 AUTO_VERIFIABLE_RULES 派生，消除重复。
"""
from __future__ import annotations

from ..model.review import ReviewViolation, ViolationSeverity
from ..model.spec import Spec
from ..model.plan import Plan


def check_spec_completeness(artifacts: dict) -> list[ReviewViolation]:
    """检查 1: Spec 必填字段是否齐全（id=S-001, FATAL）"""
    violations: list[ReviewViolation] = []
    spec_data = artifacts.get("spec_data", {})
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
    return violations


def check_problem_length(artifacts: dict) -> list[ReviewViolation]:
    """检查 2: problem 长度不足 10 字符（id=S-002, FATAL）"""
    spec_data = artifacts.get("spec_data", {})
    if spec_data and len(spec_data.get("problem", "")) < 10:
        return [ReviewViolation(
            id="S-002",
            severity=ViolationSeverity.FATAL,
            axis="standards",
            rule="problem_length",
            message="problem 字段不足 10 字符，无法准确描述问题",
            fix="扩充 problem 描述至至少 10 字符",
        )]
    return []


def check_goals_required(artifacts: dict) -> list[ReviewViolation]:
    """检查 3: goals 非空（id=S-003, FATAL）"""
    spec_data = artifacts.get("spec_data", {})
    if spec_data and not spec_data.get("goals"):
        return [ReviewViolation(
            id="S-003",
            severity=ViolationSeverity.FATAL,
            axis="standards",
            rule="goals_required",
            message="goals 列表为空，需要至少 1 个目标",
            fix="在 Spec 中补充 goals",
        )]
    return []


def check_non_goals_required(artifacts: dict) -> list[ReviewViolation]:
    """检查 4: non_goals 非空（id=S-004, MAJOR）"""
    spec_data = artifacts.get("spec_data", {})
    if spec_data and not spec_data.get("non_goals"):
        return [ReviewViolation(
            id="S-004",
            severity=ViolationSeverity.MAJOR,
            axis="standards",
            rule="non_goals_required",
            message="non_goals 列表为空，缺少非目标定义",
            fix="在 Spec 中补充 non_goals（至少 1 项）",
        )]
    return []


def check_task_module_empty(artifacts: dict) -> list[ReviewViolation]:
    """检查 5: Plan 中 Task 的 module 为空（id=S-{100+i+1}, FATAL）"""
    violations: list[ReviewViolation] = []
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
    return violations


def check_task_acceptance_empty(artifacts: dict) -> list[ReviewViolation]:
    """检查 6: Plan 中 Task 的 acceptance 为空（id=S-{200+i+1}, MAJOR）"""
    violations: list[ReviewViolation] = []
    plan_data = artifacts.get("plan_data")
    if plan_data:
        plan = Plan(**plan_data) if plan_data else None
        if plan and plan.tasks:
            for i, task in enumerate(plan.tasks):
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


# 注册所有检查。顺序无关（下游消费方枚举已确认：verdict 判空 / 回归用 set / fix 用 id / 计数用 len）。
STANDARDS_CHECKS = [
    check_spec_completeness,
    check_problem_length,
    check_goals_required,
    check_non_goals_required,
    check_task_module_empty,
    check_task_acceptance_empty,
]

# 所有 standards 规则名（单一真相源，供 AUTO_VERIFIABLE_RULES 派生，消除重复硬编码）。
ALL_STANDARD_RULES: frozenset[str] = frozenset({
    "spec_completeness", "problem_length", "goals_required",
    "non_goals_required", "task_module_empty", "task_acceptance_empty",
})


def run_all_standards_checks(artifacts: dict) -> list[ReviewViolation]:
    """执行全部 Standards 轴自动检查（等价于原 ReviewEngine._run_standards_checks）。"""
    violations: list[ReviewViolation] = []
    for check in STANDARDS_CHECKS:
        violations.extend(check(artifacts))
    return violations
