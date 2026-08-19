"""DevFlow CLI 门面（typer）

纯薄门面：解析参数 → 调引擎 → 输出 JSON。
不包含任何业务逻辑。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer

from .storage.fs_backend import FSBackend
from .storage.git_port import SystemGitPort
from .storage.review_store import ReviewStore
from .policy.loader import load_sop
from .engine.state_machine import PhaseStateMachine
from .engine.redline_auditor import RedLineAuditor
from .engine.review_engine import ReviewEngine
from .verify.gate_runner import GateRunner

app = typer.Typer(
    name="devflow",
    help="DevFlow — 方案驱动开发工作流引擎 (MVP)",
    no_args_is_help=True,
)


def _get_root() -> Path:
    return Path.cwd()


def _get_config():
    root = _get_root()
    sop_path = root / "sop.yaml"
    if not sop_path.exists():
        typer.echo(json.dumps({"ok": False, "message": "sop.yaml 不存在，请先执行 devflow init"}, ensure_ascii=False))
        raise typer.Exit(code=1)
    return load_sop(sop_path)


def _get_machine() -> tuple[PhaseStateMachine, FSBackend, 'SOPConfig']:
    storage = FSBackend(_get_root())
    config = _get_config()
    git = SystemGitPort(_get_root())
    gate_runner = GateRunner(config, str(_get_root()))
    review_engine = _get_review_engine(storage, config)
    machine = PhaseStateMachine(storage, config, git=git, gate_runner=gate_runner, review_engine=review_engine)
    return machine, storage, config


def _get_review_engine(storage: FSBackend, config: 'SOPConfig') -> ReviewEngine:
    """组装 ReviewEngine"""
    review_store = ReviewStore(_get_root())
    return ReviewEngine(storage, config, review_store)


def _output(result: dict) -> None:
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2, default=str))


# --- 11 个子命令 ---

@app.command()
def init():
    """初始化 DevFlow 工作区"""
    root = _get_root()
    storage = FSBackend(root)
    default_sop = root / "config" / "sop.default.yaml"
    if default_sop.exists():
        sop_content = default_sop.read_text(encoding="utf-8")
    else:
        sop_content = """sop:
  sop_version: "0.1"
  phases: [intake, brainstorm, plan, contract, implement, verify, review, finish]
  intake_fast_skip: true
  red_lines: [skip_phase, no_test, cross_module_import, huge_pr, uncommitted_bulk, main_incomplete, doc_drift, silent_legacy, no_contract, {circular_dep: {mvp_skip: true}}, human_step_auto]
  pr_max_files: 30
  minimalism_strictness: full
  gates:
    tests_pass: {command: "pytest --import-mode=importlib -q", blocking: true, enabled: true, bind_to_stage: 5}
    ci_green: {command: "echo ci-check-placeholder && exit 0", blocking: false, enabled: true, bind_to_stage: 6}
    intake_gate: {kind: triage, require: "ready-for-agent", blocking: true, enabled: true, bind_to_stage: 0}
    review_gate: {kind: "review", blocking: true, enabled: true, bind_to_stage: 2, max_rounds: 5, require_clear: true}
  modules: {facade: "__init__.py", forbidden_import: ["service/", "model/", "utils/internal/"]}
  tooling: {test_runner: "pytest", import_mode: "importlib", proxy_strip: true}
  storage: {backend: fs, specs_dir: specs, plans_dir: plans, ledger: progress.yaml, glossary: CONTEXT.md, content_address: false}
  allow_fast_forward: false
"""
    storage.init_workspace(sop_content)
    _output({"ok": True, "message": "DevFlow 工作区已初始化", "files": ["sop.yaml", "specs/", "plans/", "progress.yaml", "CONTEXT.md"]})


@app.command()
def start(draft: str):
    """创建新 Spec 并进入工作流"""
    machine, _, _ = _get_machine()
    result = machine.start(draft)
    _output(result)


@app.command()
def approve(spec_id: str):
    """校验 Spec 必填字段并推进 status 到 approved"""
    machine, _, _ = _get_machine()
    result = machine.approve_spec(spec_id)
    _output(result)


@app.command()
def next():
    """推进到下一阶段"""
    machine, storage, _ = _get_machine()
    if storage.is_suspended():
        resume_result = machine.resume()
        if not resume_result["ok"]:
            _output(resume_result)
            return
    result = machine.next_phase()
    _output(result)


@app.command(name="resume")
def resume_cmd():
    """从挂起状态恢复"""
    machine, _, _ = _get_machine()
    result = machine.resume()
    _output(result)


@app.command()
def status(all: bool = typer.Option(False, "--all", help="列出所有 Spec 状态")):
    """查看当前状态"""
    machine, storage, _ = _get_machine()
    result = machine.get_status()
    if all:
        result["all_specs"] = storage.list_specs()
    _output(result)


@app.command()
def gate(phase: int):
    """执行指定阶段的门禁"""
    machine, _, _ = _get_machine()
    result = machine.run_gate(phase)
    _output(result)


@app.command()
def commit(task_id: str):
    """提交 task（校验门禁 → git commit → 写账本）"""
    machine, _, _ = _get_machine()
    result = machine.commit_task(task_id)
    _output(result)


@app.command()
def audit():
    """执行红线审计"""
    storage = FSBackend(_get_root())
    config = _get_config()
    git = SystemGitPort(_get_root())
    auditor = RedLineAuditor(storage.root, config, git=git)
    violations = auditor.audit()
    _output({
        "ok": True,
        "violations": [v.to_dict() for v in violations],
        "total": len(violations),
        "skipped": sum(1 for v in violations if v.skip),
        "active": sum(1 for v in violations if not v.skip),
    })


@app.command()
def suspend(note: str = typer.Argument("", help="挂起笔记")):
    """挂起当前工作流"""
    machine, _, _ = _get_machine()
    result = machine.suspend(note)
    _output(result)


@app.command(name="skip-task")
def skip_task(task_id: str, reason: str = typer.Option(..., "--reason", help="跳过原因")):
    """跳过指定 task"""
    machine, _, _ = _get_machine()
    result = machine.skip_task(task_id, reason)
    _output(result)


# --- 审核闭环命令 ---


@app.command()
def review(
    spec_id: Optional[str] = typer.Argument(None, help="指定 Spec ID，默认当前活跃 Spec"),
    round: Optional[int] = typer.Option(None, "--round", "-r", help="指定评审轮次"),
):
    """执行双轴评审（Standards × Spec）"""
    _, storage, config = _get_machine()
    engine = _get_review_engine(storage, config)
    result = engine.review(spec_id=spec_id, round=round)
    _output(result)


@app.command()
def fix(
    violation_ids: list[str] = typer.Argument(..., help="要修复的违规 ID，如 S-001 SP-001"),
    note: str = typer.Option("", "--note", "-n", help="修复摘要"),
    residual: bool = typer.Option(False, "--residual", help="登记为残余风险（不修复）"),
    skip: bool = typer.Option(False, "--skip", help="跳过（不修复，直接标记）"),
):
    """修复违规"""
    _, storage, config = _get_machine()
    engine = _get_review_engine(storage, config)
    result = engine.fix(violation_ids, summary=note, residual=residual, skip=skip)
    _output(result)


@app.command()
def history(
    spec_id: Optional[str] = typer.Argument(None, help="指定 Spec ID，默认当前活跃 Spec"),
):
    """查看审核历史"""
    _, storage, config = _get_machine()
    engine = _get_review_engine(storage, config)
    result = engine.history(spec_id=spec_id)
    _output(result)


if __name__ == "__main__":
    app()
