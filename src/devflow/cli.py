"""DevFlow CLI 门面（typer）

纯薄门面：解析参数 → 调引擎 → 输出 JSON。
不包含任何业务逻辑。
"""
from __future__ import annotations

import json
import sys
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
    """初始化 DevFlow 工作区

    优先从 config/sop.default.yaml 读取；如不存在则使用内嵌的最小子集，
    提示用户尽快创建配置文件（避免双份维护）。
    """
    import sys
    root = _get_root()
    storage = FSBackend(root)
    default_sop = root / "config" / "sop.default.yaml"
    if default_sop.exists():
        sop_content = default_sop.read_text(encoding="utf-8")
    else:
        # P2-6: 内嵌仅作为最兜底默认；提示用户切换到配置文件
        print(
            "[devflow] 警告: 未找到 config/sop.default.yaml，使用内嵌最小默认。\n"
            "        建议尽快创建独立配置文件，避免双份维护。",
            file=sys.stderr,
        )
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
  tooling: {test_runner: "pytest", import_mode: "importlib", proxy_strip: true, command_timeout: 120}
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
    """执行指定阶段的门禁
    
    阶段名称对照：
      0=intake, 1=brainstorm, 2=plan, 3=contract,
      4=implement, 5=verify, 6=review, 7=finish
    """
    machine, _, _ = _get_machine()
    result = machine.run_gate(phase)
    # P2-4: 在结果中补充阶段名称便于理解
    if result.get("ok") is not None and "phase_name" not in result:
        phase_names = ["intake", "brainstorm", "plan", "contract",
                       "implement", "verify", "review", "finish"]
        if 0 <= phase < len(phase_names):
            result["phase_name"] = phase_names[phase]
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
def plan(
    tasks: list[str] = typer.Option([], "--task", help="初始 Task 描述，格式 '标题|模块|验收标准'"),
):
    """创建计划（Stage2 plan 阶段）"""
    machine, _, config = _get_machine()
    result = machine.create_plan(tasks)
    _output(result)


@app.command(name="task-add")
def task_add(
    title: str = typer.Argument(..., help="Task 标题"),
    module: str = typer.Option(..., "--module", "-m", help="模块名"),
    acceptance: str = typer.Option(..., "--acceptance", "-a", help="验收标准（逗号分隔多个）"),
):
    """添加 Task 到当前 Plan"""
    machine, _, _ = _get_machine()
    accept_list = [a.strip() for a in acceptance.split(",") if a.strip()]
    result = machine.add_task(title, module, accept_list)
    _output(result)


@app.command(name="task-list")
def task_list():
    """列出当前 Plan 的所有 Task"""
    machine, _, _ = _get_machine()
    result = machine.list_tasks()
    _output(result)


@app.command(name="contract-add")
def contract_add(
    task_id: str = typer.Argument(..., help="Task ID"),
    module: str = typer.Option(..., "--module", "-m", help="模块名"),
    signature: str = typer.Option(..., "--signature", "-s", help="接口签名"),
):
    """为 Task 添加 Contract（Stage3 contract 阶段）"""
    machine, _, _ = _get_machine()
    result = machine.add_contract(task_id, module, signature)
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


# --- v0.3 第一性方案：最简版（Spec 文件内 status 字段） ---


@app.command()
def archive(
    spec_id: Optional[str] = typer.Argument(None, help="Spec ID，默认当前活跃 Spec"),
    reason: str = typer.Option("", "--reason", "-r", help="归档原因（可选，写入账本）"),
):
    """归档 Spec（设置 status=archived + 写账本）

    第一性方案：文件内 status 字段标记归档，零新接口、零账本新段。
    """
    from devflow.model.spec import Spec, SpecStatus
    from datetime import datetime

    root = _get_root()
    storage = FSBackend(root)
    if spec_id is None:
        spec_id = storage.get_current_spec_id()
        if spec_id is None:
            _output({"ok": False, "message": "未指定 Spec ID 且当前无活跃 Spec"})
            return

    spec_path = storage.specs_dir / f"{spec_id}.yaml"
    spec_data = storage.read_spec(spec_id)
    if spec_data is None:
        _output({"ok": False, "message": f"Spec '{spec_id}' 不存在"})
        return

    if spec_data.get("status") == "archived":
        _output({"ok": False, "message": f"Spec '{spec_id}' 已归档（不可重复归档）"})
        return

    # 更新 Spec YAML：status 字段
    spec_data["status"] = SpecStatus.ARCHIVED.value
    storage.write_spec(spec_id, spec_data)

    # 写账本（追加 ledger entry）
    from devflow.model.ledger import LedgerEntry, LedgerAction
    storage.append_ledger(LedgerEntry(
        phase=storage.get_current_phase(),
        action=LedgerAction.PHASE_TRANSITION,
        details=f"归档 Spec '{spec_id}'" + (f"（原因：{reason}）" if reason else ""),
    ))

    _output({
        "ok": True,
        "message": f"Spec '{spec_id}' 已归档（status=archived）",
        "spec_id": spec_id,
        "archived_at": datetime.now().isoformat(),
    })


@app.command(name="list-active")
def list_active():
    """列出活跃 Spec（status != archived）"""
    root = _get_root()
    storage = FSBackend(root)
    active = []
    for spec_path in storage.specs_dir.glob("*.yaml"):
        data = storage.read_spec(spec_path.stem)
        if data is None:
            continue
        if data.get("status") != "archived":
            active.append({
                "spec_id": spec_path.stem,
                "title": data.get("title", ""),
                "status": data.get("status", "draft"),
            })
    _output({"ok": True, "total": len(active), "specs": active})


@app.command(name="list-archived")
def list_archived():
    """列出已归档 Spec（status=archived）"""
    root = _get_root()
    storage = FSBackend(root)
    archived = []
    for spec_path in storage.specs_dir.glob("*.yaml"):
        data = storage.read_spec(spec_path.stem)
        if data is None:
            continue
        if data.get("status") == "archived":
            archived.append({
                "spec_id": spec_path.stem,
                "title": data.get("title", ""),
            })
    _output({"ok": True, "total": len(archived), "specs": archived})


@app.command()
def find(
    keyword: str = typer.Argument(..., help="搜索关键词"),
    include_archived: bool = typer.Option(False, "--all", help="包含已归档 Spec"),
):
    """跨 Spec/Plan/Review 文件搜索关键词

    第一性方案：用 Python 直接扫描文件，无需新建索引。
    """
    root = _get_root()
    storage = FSBackend(root)
    results = []
    keyword_lower = keyword.lower()

    for spec_path in storage.specs_dir.glob("*.yaml"):
        spec_id = spec_path.stem
        data = storage.read_spec(spec_id)
        if data is None:
            continue
        # 默认跳过已归档
        if data.get("status") == "archived" and not include_archived:
            continue

        matches = []
        # Spec 文件
        try:
            if keyword_lower in spec_path.read_text(encoding="utf-8").lower():
                matches.append("spec")
        except OSError:
            pass

        # Plan 文件
        plan_path = storage.plans_dir / f"plan-{spec_id}.yaml"
        if plan_path.exists():
            try:
                if keyword_lower in plan_path.read_text(encoding="utf-8").lower():
                    matches.append(f"plan:{plan_path.name}")
            except OSError:
                pass

        # Review 文件
        review_dir = root / "review" / spec_id
        if review_dir.exists():
            for r_file in review_dir.glob("*.yaml"):
                try:
                    if keyword_lower in r_file.read_text(encoding="utf-8").lower():
                        matches.append(f"review:{r_file.name}")
                except OSError:
                    pass

        if matches:
            results.append({
                "spec_id": spec_id,
                "title": data.get("title", ""),
                "status": data.get("status", "draft"),
                "match_locations": matches,
            })

    _output({
        "ok": True,
        "keyword": keyword,
        "include_archived": include_archived,
        "total": len(results),
        "results": results,
    })


if __name__ == "__main__":
    app()
