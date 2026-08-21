"""DevFlow CLI 门面（typer）

纯薄门面：解析参数 → 调引擎 → 输出 JSON。
不包含任何业务逻辑。

================================================================================
DevFlow CLI 接口契约 v0.3.3 (A1 — 规范纪律)
================================================================================

【输入约定】
- 所有命令接受 --help / -h
- 参数命名：snake_case，Typer 自动转换 --task-id → --task_id
- 工作目录：cwd 即为 workspace_root
- 错误返回：{"ok": False, "message": "<原因>"}，exit code ≠ 0

【输出约定】
- 所有命令通过 _output() 输出 JSON
- 成功：{"ok": True, "data": {...}}
- 失败：{"ok": False, "message": "<原因>", "error_code": "<class>"}

【门禁约束】
- 阶段门禁由 PhaseStateMachine 校验，不在 CLI 层
- CI/Skill/MCP 调用方应消费 JSON，不要解析 stdout 文本

【协议约束】（v0.3 双集成面契约）
- CLI 是 devflow 唯一当前集成面
- Skill manifest 必须从本文件自动派生（禁止手写，v0.3 INDEX 教训）
- MCP Server / SDD 编排待 B 阶段择机重启
================================================================================
"""
from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path
from typing import Optional

import typer

from .storage.base import StorageBackend
from .storage.fs_backend import FSBackend  # noqa: F401  re-export for tests/clients
from .storage.git_port import SystemGitPort
from .storage.review_store import ReviewStore
from .policy.loader import load_sop
from .engine.state_machine import PhaseStateMachine
from .engine.redline_auditor import RedLineAuditor
from .engine.review_engine import ReviewEngine
from .verify.gate_runner import GateRunner
from .model import LedgerAction, LedgerEntry  # noqa: F401  — wizard 等内部使用

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


# v0.4 P1-10: 进程级 session_id，跨条目归组（同一次 CLI 调用一个会话）
_SESSION_ID: str = ""


def _get_session_id() -> str:
    """获取本次 CLI 进程的唯一 session_id（UUID 前 8 字符）

    进程级单例：同一次 CLI 调用内所有 append_ledger 都用同一个 session_id。
    """
    global _SESSION_ID
    if not _SESSION_ID:
        _SESSION_ID = uuid.uuid4().hex[:8]
    return _SESSION_ID


def _get_storage() -> StorageBackend:
    """Phase A: 唯一的 CLI 侧 FSBackend 实例化点.

    引擎层（state_machine / review_engine / redline_auditor）只依赖
    StorageBackend 抽象接口，本 helper 是唯一的 concrete 实例化位置，
    也是 Phase C（fixture 切到 MemoryStorageBackend）时唯一需要改动的地方。
    """
    return FSBackend(_get_root())


def _get_machine() -> tuple[PhaseStateMachine, StorageBackend, 'SOPConfig']:
    storage = _get_storage()
    config = _get_config()
    git = SystemGitPort(_get_root())
    review_engine = _get_review_engine(storage, config)
    gate_runner = GateRunner(config, str(_get_root()), review_engine=review_engine)
    machine = PhaseStateMachine(storage, config, git=git, gate_runner=gate_runner, review_engine=review_engine)
    return machine, storage, config


def _get_review_engine(storage: StorageBackend, config: 'SOPConfig') -> ReviewEngine:
    """组装 ReviewEngine"""
    # v0.3.4: ReviewStore 复用 FSBackend 的 layout，确保 review 路径与存储层一致
    layout = getattr(storage, "layout", None)
    if layout is not None:
        review_store = ReviewStore(_get_root(), layout=layout)
    else:
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
    storage = _get_storage()
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
  storage: {backend: fs, specs_dir: docs/devflow/specs, plans_dir: docs/devflow/plans, ledger: docs/devflow/progress.yaml, glossary: CONTEXT.md, content_address: false}
  allow_fast_forward: false
  research: {enabled: true, auto_run_on: [plan_stage], sources: [github, pypi, npm, web], max_results_per_source: 5, max_total_chars: 8000, timeout_per_source: 10, fallback: skip, citation_required: true, cache: {enabled: true, ttl_seconds: 86400, shared_across_specs: true}}
"""
    storage.init_workspace(sop_content)
    # v0.3.4: init 输出清单从 storage.layout 取（与真实路径一致）
    layout = getattr(storage, "layout", None)
    file_list = layout.init_file_list() if layout is not None else [
        "sop.yaml", "specs/", "plans/", "progress.yaml", "CONTEXT.md",
    ]
    _output({"ok": True, "message": "DevFlow 工作区已初始化", "files": file_list})


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


def _run_intake_wizard(gate_result: dict) -> Optional[dict]:
    """Intake 闸门拒绝时的交互式向导(P1-17)

    设计取舍:不抽象为 wizard.py 模块,因为 MVP 只有一个向导场景;
    若 v0.4+ 出现多个 wizard 场景,再考虑抽出。

    Returns:
        None (用户选 q 退出) 或 dict (重跑 next_phase 的结果,供 CLI 输出 JSON)
    """
    # P1-17 fix: 用 [WARN] 替代 emoji,兼容 Windows GBK 控制台
    typer.echo(f"\n[WARN] {gate_result['message']}\n")

    # P1-17 fix: 用 click.Choice 而非 typer.Choice(typer 没暴露 Choice)
    import click
    action = typer.prompt(
        "请选择动作 [a] 升级为 ready-for-agent / [m] 标记为 wontfix / [q] 退出",
        type=click.Choice(["a", "m", "q"]),
    )

    if action == "q":
        return None

    machine, storage, _ = _get_machine()
    triage_state = {
        "a": "ready-for-agent",
        "m": "wontfix",
    }[action]

    # 写 triage 账本条目(供 next_phase 重检)
    storage.append_ledger(LedgerEntry(
        phase=0,
        action=LedgerAction.TRIAGE,
        details=f"wizard 触发:triage_state={triage_state}",
    ))

    # v0.3.4: 重跑 next_phase 让状态落地,返回新结果给 next() 输出 JSON
    advance_result = machine.next_phase()
    typer.echo(f"[OK] 已更新 triage_state={triage_state},已重试 next_phase")
    return advance_result


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

    # P1-17: ready-for-human 触发 wizard 交互式向导
    if not result.get("ok") and result.get("wizard"):
        new_result = _run_intake_wizard(result)
        if new_result is not None:
            _output(new_result)
        return

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
    machine, storage, _ = _get_machine()
    result = machine.run_gate(phase)
    # P2-4: 在结果中补充阶段名称便于理解
    if result.get("ok") is not None and "phase_name" not in result:
        phase_names = ["intake", "brainstorm", "plan", "contract",
                       "implement", "verify", "review", "finish"]
        if 0 <= phase < len(phase_names):
            result["phase_name"] = phase_names[phase]

    # v0.3.2 P2-14: 门禁结果持久化到账本(含 stdout/stderr 尾部脱敏)
    if storage is not None:
        try:
            from .model.ledger import LedgerEntry, LedgerAction
            storage.append_ledger(LedgerEntry(
                phase=phase,
                action=LedgerAction.GATE,
                details=f"门禁 {result.get('phase_name', phase)}: {result.get('message', '')[:100]}",
                gate_result=_sanitize_gate_result(result),
            ))
        except Exception:
            # 门禁结果持久化失败不应阻断 gate 命令本身
            result["ledger_note"] = "门禁结果写入账本失败(不影响门禁结果)"
    _output(result)


def _sanitize_gate_result(result: dict) -> dict:
    """v0.3.2 P2-14: 提取门禁结果到账本,stdout/stderr 尾部脱敏

    - 只保留尾部 300 字符
    - 过滤 ANSI 颜色码
    - 过滤疑似敏感内容(密钥/密码/token)
    """
    import re as _re

    def _clean(text: str, limit: int = 300) -> str:
        if not text:
            return ""
        # 去掉 ANSI 颜色码
        cleaned = _re.sub(r"\x1b\[[0-9;]*m", "", text)
        # 截尾
        cleaned = cleaned[-limit:]
        # 脱敏:疑似密钥/密码/token
        cleaned = _re.sub(
            r"(?i)((?:key|secret|token|password|passwd|pwd)\s*[=:]\s*)([^\s,;]+)",
            r"\1***",
            cleaned,
        )
        return cleaned

    return {
        "ok": result.get("ok"),
        "message": str(result.get("message", ""))[:200],
        "stdout_tail": _clean(result.get("stdout", "")),
        "stderr_tail": _clean(result.get("stderr", "")),
    }


@app.command()
def commit(task_id: str):
    """提交 task（校验门禁 → git commit → 写账本）"""
    machine, _, _ = _get_machine()
    result = machine.commit_task(task_id)
    _output(result)


@app.command()
def audit():
    """执行红线审计

    v0.3.1-r2 P1-5 改进:返回 total_real/total_skipped/coverage 字段,
    让用户区分真实违规与 stub 红线。旧字段 total/active 保留兼容。
    """
    storage = _get_storage()
    config = _get_config()
    git = SystemGitPort(_get_root())
    auditor = RedLineAuditor(storage.root, config, git=git)
    violations = auditor.audit()

    real = [v.to_dict() for v in violations if not v.skip]
    skipped = [v.to_dict() for v in violations if v.skip]

    _output({
        "ok": True,
        # 旧字段保留(向后兼容)
        "violations": [v.to_dict() for v in violations],
        "total": len(violations),
        "skipped_count": sum(1 for v in violations if v.skip),
        "active": sum(1 for v in violations if not v.skip),
        # v0.3.1-r2 新增字段
        "violations_real": real,
        "skipped_detail": skipped,
        "total_real": len(real),
        "total_skipped": len(skipped),
        "coverage": {
            "configured": len(config.red_lines),
            "real_violations": len(real),
            "skipped_mvp_or_stub": len(skipped),
            # v0.3.2 P1-5 补强:按结构化 status 统计
            "by_status": _count_by_status(violations),
        },
    })


def _count_by_status(violations) -> dict:
    """v0.3.2 P1-5 补强: 按 ViolationStatus 枚举统计"""
    from .engine.redline_auditor import ViolationStatus
    counts = {s.value: 0 for s in ViolationStatus}
    for v in violations:
        counts[v.status.value] = counts.get(v.status.value, 0) + 1
    return counts


@app.command(name="ci-status")
def ci_status():
    """v0.3.1-r2 P1-9: 显示 ci_green 门禁当前配置状态

    让用户清晰看到 ci_green 是否启用、是否为占位命令。
    """
    config = _get_config()
    gate = config.get_gate("ci_green")
    if gate is None:
        result = {"ok": False, "message": "ci_green 门禁未配置"}
    elif not gate.enabled:
        result = {
            "ok": True,
            "status": "disabled",
            "message": "ci_green 禁用中(占位命令不生效)",
            "hint": "启用真实 CI:在 sop.yaml 设置 gates.ci_green.enabled: true 并配置真实 command",
        }
    else:
        result = {
            "ok": True,
            "status": "enabled",
            "command": gate.command,
            "blocking": gate.blocking,
            "message": "ci_green 已启用",
        }
    _output(result)


@app.command(name="review-audit")
def review_audit():
    """v0.4 阶段 P1-13 完整版:多 spec review/fix JOIN 审计

    架构文档 §9.1 接收反馈闭环：审计 review_store 报告与 ledger 的一致性
    - orphans: ledger 有 review/fix/escalate 但 review_store 无对应报告
    - missing_in_ledger: review_store 有报告但 ledger 无记录（反向校验）
    - fix_orphans / fix_missing_in_ledger: fix 记录的双向 JOIN

    v0.4 触发条件（v0.4-roadmap-paused.md §一）：多 spec 工作流成为主流用法
    预案 B（v0.4-roadmap-paused.md §二）：用 review_store 文件名反推 + 时间窗推断
    不扩 LedgerEntry schema（v0.3 INDEX 教训核心）
    """
    storage = _get_storage()
    review_store = ReviewStore(_get_root())

    ledger = storage.get_ledger()
    from .engine.review_audit import audit_review_ledger

    result = audit_review_ledger(ledger, review_store)
    _output(result.to_dict())


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
    with_research: bool = typer.Option(
        False, "--with-research",
        help="plan 阶段自动跑调研(从当前 Spec.problem 抽取关键词)",
    ),
):
    """创建计划（Stage2 plan 阶段）"""
    machine, storage, config = _get_machine()

    # v0.4: --with-research 钩子(显式)或 sop.research.auto_run_on=[plan_stage](隐式)
    should_research = with_research or config.is_research_auto_run(2)
    if should_research and config.research.enabled:
        spec_id = storage.get_current_spec_id()
        spec_data = storage.read_spec(spec_id) if spec_id else None
        if spec_id and spec_data:
            problem = spec_data.get("problem", "")[:100]
            if problem:
                _run_research(
                    query=problem,
                    spec_id=spec_id,
                    storage=storage,
                    config=config,
                    emit_echo=False,
                )

    result = machine.create_plan(tasks)
    _output(result)


# --- v0.4 RFC §7.1: research 命令 ---

def _run_research(
    query: str,
    spec_id: str,
    storage: StorageBackend,
    config,
    emit_echo: bool = True,
) -> dict:
    """内部辅助:实际跑 research 并落盘

    Args:
        query: 调研关键词
        spec_id: 关联 Spec
        storage: storage backend
        config: SOPConfig(读 .research 段)
        emit_echo: True 时把结果输出到 stderr(给人看);
                   False 时静默(plan --with-research 自动调用)
    """
    from .engine.research_runner import ResearchRunner
    from .model.research import SourceType

    runner = ResearchRunner(
        storage=storage,
        config=config.research,
        workspace_root=_get_root(),
    )
    sources = [SourceType(s) for s in config.research.sources]
    result = runner.run(
        query=query,
        spec_id=spec_id,
        sources=sources,
    )
    if emit_echo:
        # 用 stderr 输出(advisory,不污染主 JSON)
        if result["ok"]:
            typer.echo(
                f"[research] {result['citations_count']} 条引用"
                + (f" (fallback 已触发)" if result["fallback_used"] else "")
                + f" → {result['report_path']}",
                err=True,
            )
        else:
            typer.echo(
                f"[research] 失败:{result['message']}",
                err=True,
            )
    return result


@app.command()
def research(
    query: str = typer.Argument(
        "", help="调研关键词(v0.4.2 --clear-cache 时可省略)",
    ),
    spec_id: Optional[str] = typer.Option(
        None, "--spec-id", "-s",
        help="关联 Spec(默认取当前活跃 Spec)",
    ),
    sources: str = typer.Option(
        "github,pypi,web", "--sources",
        help="数据源列表,逗号分隔(github/pypi/npm/crates/web)",
    ),
    max_results: int = typer.Option(
        5, "--max-results", "-n",
        help="单源最大返回数(1-20)",
    ),
    clear_cache: bool = typer.Option(
        False, "--clear-cache",
        help="v0.4.2:清缓存(query 为空清全部,否则清该 query)",
    ),
    no_cache: bool = typer.Option(
        False, "--no-cache",
        help="v0.4.2:禁用本次查询的缓存(强制调 backend)",
    ),
):
    """执行引文式调研,产出带引用的 Markdown

    v0.4 RFC §7.1:辅助需求草稿 + plan 阶段,验证是否已有成熟方案。
    """
    machine, storage, config = _get_machine()

    # v0.4.2: --clear-cache 早返回(不需要 spec_id)
    if clear_cache:
        from .engine.research_runner import ResearchRunner
        runner = ResearchRunner(
            storage=storage,
            config=config.research,
            workspace_root=_get_root(),
        )
        # query 为空 → 清全部;否则清单个
        from .model.research import SourceType as ST
        src_list = [ST(s.strip()) for s in sources.split(",") if s.strip()]
        cache_key = (
            runner.cache.make_key(
                query, [s.value for s in src_list], max_results,
            ) if query else None
        )
        cleared = runner.cache.clear(key=cache_key)
        _output({
            "ok": True,
            "message": f"已清缓存 ({cleared} 条)",
            "cleared_entries": cleared,
            "stats": runner.cache.stats(),
        })
        return

    # 解析 spec_id
    target_spec_id = spec_id or storage.get_current_spec_id()
    if not target_spec_id:
        _output({
            "ok": False,
            "message": "未指定 spec_id 且无活跃 Spec,请先 devflow start",
        })
        raise typer.Exit(code=1)

    # v0.4.1 校验: spec_id 必须存在(避免静默失败)
    if storage.read_spec(target_spec_id) is None:
        _output({
            "ok": False,
            "message": f"Spec '{target_spec_id}' 不存在",
        })
        raise typer.Exit(code=1)

    # 解析 sources(命令行覆盖 SOP 默认)
    from .model.research import SourceType as ST
    try:
        src_list = [ST(s.strip()) for s in sources.split(",") if s.strip()]
    except ValueError as e:
        _output({
            "ok": False,
            "message": f"无效的 sources 值: {e};可选: {[s.value for s in ST]}",
        })
        raise typer.Exit(code=1)

    # 构造一个临时 SOPConfig.research(命令行 sources + max_results 覆盖)
    research_cfg = config.research.model_copy(update={
        "max_results_per_source": max_results,
        "sources": [s.value for s in src_list],
    })
    # 临时替换
    config_adjusted = config.model_copy(update={"research": research_cfg})

    result = _run_research(
        query=query,
        spec_id=target_spec_id,
        storage=storage,
        config=config_adjusted,
        emit_echo=False,
    )
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
    storage = _get_storage()
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
    storage = _get_storage()
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
    storage = _get_storage()
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
    storage = _get_storage()
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
        review_dir = getattr(storage, "layout", None)
        if review_dir is not None:
            review_dir = review_dir.review_spec_dir(spec_id)
        else:
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


@app.command(name="dispatch")
def dispatch(
    plan_id: str = typer.Argument(..., help="Plan ID"),
    real_agent: bool = typer.Option(False, "--real-agent", help="使用真实 Agent (ClaudeCode) 而非 Mock"),
    parallel: bool = typer.Option(False, "--parallel", help="并行派发（B2.6 / M6 阶段）"),
) -> None:
    """SDD 子代理编排：派发 Plan 内所有 Task

    v0.3 B2.5-B2.6 阶段：架构文档 §5.2.1 SDD 执行模式

    Examples:
        # 测试 / dry-run（默认 MockAgentRunner + 顺序派发）
        devflow dispatch plan-spec-1

        # 真实 Agent（需安装 claude CLI）
        devflow dispatch plan-spec-1 --real-agent

        # 并行派发（需 Plan DAG 合法）
        devflow dispatch plan-spec-1 --parallel
    """
    import asyncio
    from .engine.dispatcher import (
        create_dispatcher,
        dispatch_plan,
        dispatch_plan_parallel,
    )

    root = Path.cwd()
    dispatcher = create_dispatcher(root, use_real_agent=real_agent)

    try:
        if parallel:
            result = asyncio.run(dispatch_plan_parallel(dispatcher, plan_id))
        else:
            result = asyncio.run(dispatch_plan(dispatcher, plan_id))
        _output({
            "ok": True,
            "plan_id": plan_id,
            "real_agent": real_agent,
            "parallel": parallel,
            "task_count": len(result.get("results", [])),
            "results": result.get("results", []),
        })
    except ValueError as e:
        _output({"ok": False, "message": str(e)})
        raise typer.Exit(code=1)
    except RuntimeError as e:
        _output({"ok": False, "message": str(e), "error_type": "dag_deadlock"})
        raise typer.Exit(code=1)


@app.command(name="adapter-export")
def adapter_export(
    platform: str = typer.Argument(None, help="目标平台: claude-code / workbuddy / codebuddy（--auto-detect 时可省略）"),
    target: Path = typer.Option(Path("./skills"), "--target", help="生成目录"),
    auto_detect: bool = typer.Option(False, "--auto-detect", help="自动 detect 当前平台（覆盖 platform 参数）"),
) -> None:
    """导出 Skill manifest 到目标平台

    v0.3 B4.4 / C7.3 阶段：架构文档 §6 双集成面

    Manifest 自动从 cli.py 派生（v0.3 INDEX 教训：禁止手写）。
    默认手动指定平台；--auto-detect 时按 detect_platform() 自动选择。

    Examples:
        # Claude Code Skills
        devflow adapter-export claude-code --target ~/.claude/skills/devflow

        # WorkBuddy Skills
        devflow adapter-export workbuddy --target ./workbuddy-skills

        # CodeBuddy Skills
        devflow adapter-export codebuddy --target ./codebuddy-skills

        # 自动检测（需先设环境变量 CLAUDE_CODE 等）
        devflow adapter-export --auto-detect --target ./skills
    """
    from .adapters.skill_packager import package_for_platform
    from .adapters.manifest_builder import build_manifests_from_cli
    from .adapters.detect import detect_platform

    try:
        if auto_detect:
            platform = detect_platform().value
        elif platform is None:
            _output({
                "ok": False,
                "message": "必须指定 platform 参数或使用 --auto-detect",
            })
            raise typer.Exit(code=1)

        manifests = build_manifests_from_cli(app)
        generated = package_for_platform(platform, manifests, target)
        _output({
            "ok": True,
            "platform": platform,
            "auto_detect": auto_detect,
            "target": str(target),
            "manifest_count": len(manifests),
            "generated_count": len(generated),
            "generated_files": [str(p) for p in generated[:5]],
        })
    except ValueError as e:
        _output({"ok": False, "message": str(e)})
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
