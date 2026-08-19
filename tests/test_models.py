"""领域模型单元测试

覆盖：必填字段校验、status 枚举约束、can_skip 等。
"""
import pytest
from pydantic import ValidationError

import sys
sys.path.insert(0, str(__import__('pathlib').Path(__file__).parent.parent / "src"))

from devflow.model import (
    Spec, SpecStatus,
    Plan,
    Task, TaskStatus,
    Contract,
    QualityGate,
    LedgerEntry, LedgerAction,
    DomainModel,
    Intake, IntakeKind, TriageState,
)


class TestSpec:
    def test_create_valid_spec(self):
        spec = Spec(
            id="test-1",
            title="Test Spec",
            problem="This is a test problem description",
            goals=["goal1", "goal2"],
            non_goals=["non-goal1"],
        )
        assert spec.status == SpecStatus.DRAFT
        assert len(spec.goals) == 2
        assert len(spec.non_goals) == 1

    def test_missing_title_raises(self):
        with pytest.raises(ValidationError):
            Spec(
                id="test-1",
                title="",
                problem="This is a test problem description",
                goals=["goal1"],
                non_goals=["non-goal1"],
            )

    def test_short_problem_raises(self):
        with pytest.raises(ValidationError):
            Spec(
                id="test-1",
                title="Test",
                problem="short",
                goals=["goal1"],
                non_goals=["non-goal1"],
            )

    def test_empty_goals_raises(self):
        with pytest.raises(ValidationError):
            Spec(
                id="test-1",
                title="Test",
                problem="This is a test problem description",
                goals=[],
                non_goals=["non-goal1"],
            )

    def test_empty_non_goals_raises(self):
        with pytest.raises(ValidationError):
            Spec(
                id="test-1",
                title="Test",
                problem="This is a test problem description",
                goals=["goal1"],
                non_goals=[],
            )

    def test_empty_goal_item_raises(self):
        with pytest.raises(ValidationError):
            Spec(
                id="test-1",
                title="Test",
                problem="This is a test problem description",
                goals=[""],
                non_goals=["non-goal1"],
            )

    def test_missing_required_fields(self):
        spec = Spec(
            id="test-1",
            title="Test",
            problem="This is a test problem description",
            goals=["goal1"],
            non_goals=["non-goal1"],
        )
        assert spec.missing_required_fields() == []

    def test_spec_status_enum(self):
        spec = Spec(
            id="test-1",
            title="Test",
            problem="This is a test problem description",
            goals=["goal1"],
            non_goals=["non-goal1"],
            status=SpecStatus.APPROVED,
        )
        assert spec.status == SpecStatus.APPROVED


class TestTask:
    def test_create_valid_task(self):
        task = Task(
            id="task-1",
            title="Test Task",
            module="test-module",
            acceptance=["acceptance criteria 1"],
        )
        assert task.status == TaskStatus.TODO
        assert task.can_skip()

    def test_missing_module_raises(self):
        with pytest.raises(ValidationError):
            Task(
                id="task-1",
                title="Test Task",
                module="",
                acceptance=["acceptance criteria 1"],
            )

    def test_empty_acceptance_raises(self):
        with pytest.raises(ValidationError):
            Task(
                id="task-1",
                title="Test Task",
                module="test-module",
                acceptance=[],
            )

    def test_can_skip_only_todo_or_contracted(self):
        for status in TaskStatus:
            task = Task(
                id="task-1",
                title="Test Task",
                module="test-module",
                acceptance=["criteria"],
                status=status,
            )
            if status in (TaskStatus.TODO, TaskStatus.CONTRACTED):
                assert task.can_skip()
            else:
                assert not task.can_skip()


class TestContract:
    def test_create_valid_contract(self):
        contract = Contract(
            module="test-module",
            interface_signature="def test_func() -> bool",
        )
        assert contract.module == "test-module"

    def test_empty_module_raises(self):
        with pytest.raises(ValidationError):
            Contract(module="", interface_signature="def test_func() -> bool")

    def test_empty_signature_raises(self):
        with pytest.raises(ValidationError):
            Contract(module="test", interface_signature="")


class TestPlan:
    def test_create_plan(self):
        plan = Plan(
            spec_id="test-spec",
            tasks=[
                Task(id="task-1", title="Task 1", module="mod", acceptance=["a"]),
            ],
        )
        assert len(plan.tasks) == 1


class TestLedgerEntry:
    def test_create_entry(self):
        entry = LedgerEntry(
            phase=0,
            action=LedgerAction.TRIAGE,
        )
        assert entry.phase == 0
        assert entry.action == LedgerAction.TRIAGE
        assert entry.timestamp is not None


class TestIntake:
    def test_create_intake(self):
        intake = Intake(
            id="issue-1",
            kind=IntakeKind.BUG,
            summary="Test bug",
            triage_state=TriageState.READY_FOR_AGENT,
        )
        assert intake.is_ready_for_agent()

    def test_not_ready_for_agent(self):
        intake = Intake(
            id="issue-1",
            triage_state=TriageState.NEEDS_TRIAGE,
        )
        assert not intake.is_ready_for_agent()


class TestDomainModel:
    def test_create_domain_model(self):
        dm = DomainModel()
        assert dm.glossary_path == "CONTEXT.md"
        assert dm.adrs == []


class TestQualityGate:
    def test_create_gate(self):
        gate = QualityGate(
            name="tests_pass",
            command="pytest",
            blocking=True,
            enabled=True,
        )
        assert gate.name == "tests_pass"
