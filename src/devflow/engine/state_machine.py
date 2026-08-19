"""PhaseStateMachine — 八阶段状态机

实现 MVP-门禁降级矩阵 §1 定义的逐阶段出口门禁。
依赖抽象接口：StorageBackend、GitPort、GateRunner。
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from ..model import (
    Spec, SpecStatus, Plan, Task, TaskStatus,
    Contract, Intake, IntakeKind, TriageState,
    LedgerEntry, LedgerAction,
)
from ..storage.base import StorageBackend
from ..storage.git_port import GitPort
from ..policy.loader import SOPConfig
from ..verify.gate_runner import GateRunner

if False:  # 仅用于类型标注，避免循环导入
    from .review_engine import ReviewEngine


class PhaseError(Exception):
    """阶段推进错误"""
    def __init__(self, message: str, missing: Optional[list[str]] = None):
        super().__init__(message)
        self.message = message
        self.missing = missing or []


class PhaseStateMachine:
    """八阶段状态机

    核心不变量：
    - enter(Stage[i]) 需 Stage[i-1].exit_gate == PASS（i>0）
    - commit(task) 需 Stage5/6 门禁均 PASS

    依赖注入：storage、git、gate_runner 均通过构造函数注入。
    """

    PHASE_NAMES = ["intake", "brainstorm", "plan", "contract",
                    "implement", "verify", "review", "finish"]

    def __init__(
        self,
        storage: StorageBackend,
        config: SOPConfig,
        git: Optional[GitPort] = None,
        gate_runner: Optional[GateRunner] = None,
        review_engine: Optional['ReviewEngine'] = None,
    ):
        self.storage = storage
        self.config = config
        self.git = git
        self.gate_runner = gate_runner
        self.review_engine = review_engine

    @property
    def current_phase(self) -> int:
        return self.storage.get_current_phase()

    @property
    def current_phase_name(self) -> str:
        return self.PHASE_NAMES[self.current_phase]

    # --- start 命令（从业务逻辑层移入引擎） ---

    def start(self, draft: str) -> dict:
        """创建新 Spec + Intake + 写账本，返回结果"""
        spec_id = self._make_spec_id(draft)

        # P1-1: 检查 spec_id 是否已存在，避免覆盖
        existing = self.storage.read_spec(spec_id)
        if existing is not None:
            # 追加时间戳后缀确保唯一
            from datetime import datetime
            suffix = datetime.now().strftime("%H%M%S")
            spec_id = f"{spec_id}-{suffix}"
            # 再次检查（极小概率碰撞）
            if self.storage.read_spec(spec_id) is not None:
                import random
                spec_id = f"{spec_id}-{random.randint(100, 999)}"

        spec = Spec(
            id=spec_id,
            title=draft[:100],
            problem=draft,
            goals=["待补充"],
            non_goals=["待补充"],
        )
        self.storage.write_spec(spec_id, spec.model_dump(mode="json"))
        self.storage.set_current_spec_id(spec_id)

        intake = Intake(
            id=f"issue-{spec_id}",
            kind=IntakeKind.ENHANCEMENT,
            summary=draft[:200],
            triage_state=(
                TriageState.READY_FOR_AGENT
                if self.config.intake_fast_skip
                else TriageState.NEEDS_TRIAGE
            ),
        )

        self.storage.append_ledger(LedgerEntry(
            phase=0,
            action=LedgerAction.TRIAGE,
            details=f"Intake 创建: triage_state={intake.triage_state.value}",
        ))
        self.storage.set_current_phase(0)

        result = {
            "ok": True,
            "message": f"Spec '{spec_id}' 已创建 (status=draft)",
            "spec_id": spec_id,
            "current_phase": 0,
        }
        if self.config.intake_fast_skip:
            result["intake"] = "自动创建 triage_state=ready-for-agent (intake_fast_skip=true)"
        return result

    # --- 阶段推进 ---

    def next_phase(self) -> dict:
        """尝试推进到下一阶段"""
        phase = self.current_phase
        gate_result = self._check_exit_gate(phase)
        if not gate_result["ok"]:
            return gate_result

        # P0-6: 检查 review_gate（如果当前阶段绑定 review_gate 且 review_engine 已注入）
        if self.review_engine:
            review_gate = self.config.gates.get("review_gate")
            if review_gate and review_gate.enabled and review_gate.bind_to_stage == phase:
                rv = self.review_engine.check_review_gate()
                if not rv["ok"]:
                    return {
                        "ok": False,
                        "message": f"review_gate 未通过: {rv['message']}",
                        "violations": rv.get("violations", []),
                    }

        new_phase = phase + 1
        if new_phase >= len(self.PHASE_NAMES):
            # v0.3 第一性方案：进入 finish 时自动触发软归档
            return self._archive_on_finish()

        self.storage.set_current_phase(new_phase)
        self.storage.append_ledger(LedgerEntry(
            phase=new_phase,
            action=LedgerAction.PHASE_TRANSITION,
            details=f"{self.PHASE_NAMES[phase]} → {self.PHASE_NAMES[new_phase]}",
        ))
        self._advance_tasks_for_phase(new_phase)

        return {
            "ok": True,
            "phase": new_phase,
            "message": f"已进入 Stage{new_phase} ({self.PHASE_NAMES[new_phase]})",
        }

    def approve_spec(self, spec_id: str) -> dict:
        """校验 Spec 必填字段并推进 status 到 approved
        
        P1-4: 只能在 Stage0 (intake) 或 Stage1 (brainstorm) 时 approve
        """
        phase = self.current_phase
        if phase > 1:
            return {
                "ok": False, "message": f"当前在 Stage{phase} ({self.PHASE_NAMES[phase]})，"
                f"approve 只能在 Stage0/1 执行。已在流程中的 Spec 无法重复 approve"
            }
        spec_data = self.storage.read_spec(spec_id)
        if spec_data is None:
            return {"ok": False, "message": f"Spec '{spec_id}' 不存在"}

        try:
            spec = Spec(**spec_data)
        except Exception as e:
            missing = []
            if "non_goals" in str(e):
                missing.append("non_goals (至少 1 项)")
            if "goals" in str(e):
                missing.append("goals (非空列表)")
            if "problem" in str(e):
                missing.append("problem (≥10 字符)")
            if not missing:
                missing.append(f"解析错误: {e}")
            return {"ok": False, "message": "Spec 必填字段不齐", "missing": missing}

        missing = spec.missing_required_fields()
        if missing:
            return {"ok": False, "message": "Spec 必填字段不齐", "missing": missing}

        spec.status = SpecStatus.APPROVED
        self.storage.write_spec(spec_id, spec.model_dump(mode="json"))
        self.storage.append_ledger(LedgerEntry(
            phase=1,
            action=LedgerAction.APPROVE,
            details=f"Spec '{spec_id}' approved",
        ))
        return {"ok": True, "message": f"Spec '{spec_id}' 已 approved"}

    # --- P0-5: Plan/Task/Contract 管理命令 ---

    def create_plan(self, task_specs: list[str]) -> dict:
        """创建计划（Stage2 plan 阶段）"""
        spec_id = self.storage.get_current_spec_id()
        if spec_id is None:
            return {"ok": False, "message": "当前无活跃 Spec，请先执行 devflow start"}

        plan_id = f"plan-{spec_id}"
        tasks = []
        for i, spec in enumerate(task_specs or []):
            parts = spec.split("|")
            title = parts[0].strip() if len(parts) > 0 else f"Task {i+1}"
            module = parts[1].strip() if len(parts) > 1 else ""
            acceptance_list = [a.strip() for a in parts[2].split(",") if a.strip()] if len(parts) > 2 else []
            if not acceptance_list:
                acceptance_list = ["待补充"]
            tasks.append(Task(
                id=f"task-{i+1}",
                title=title,
                module=module,
                acceptance=acceptance_list,
            ))

        if not tasks:
            tasks.append(Task(
                id="task-1", title="待补充", module="", acceptance=["待补充"],
            ))

        plan = Plan(spec_id=spec_id, tasks=tasks)
        self.storage.write_plan(plan_id, plan.model_dump(mode="json"))
        self.storage.set_current_plan_id(plan_id)

        self.storage.append_ledger(LedgerEntry(
            phase=self.current_phase,
            action=LedgerAction.ARTIFACT,
            details=f"Plan '{plan_id}' 已创建，含 {len(tasks)} 个 Task",
        ))

        return {
            "ok": True,
            "message": f"Plan '{plan_id}' 已创建，含 {len(tasks)} 个 Task",
            "plan_id": plan_id,
            "tasks": [{"id": t.id, "title": t.title} for t in tasks],
        }

    def add_task(self, title: str, module: str, acceptance: list[str]) -> dict:
        """添加 Task 到当前 Plan"""
        plan_id = self.storage.get_current_plan_id()
        if plan_id is None:
            return {"ok": False, "message": "当前无活跃 Plan，请先执行 devflow plan"}

        plan_data = self.storage.read_plan(plan_id)
        if plan_data is None:
            return {"ok": False, "message": f"Plan '{plan_id}' 不存在"}

        plan = Plan(**plan_data)
        next_num = len(plan.tasks) + 1
        task = Task(
            id=f"task-{next_num}",
            title=title,
            module=module,
            acceptance=acceptance or ["待补充"],
        )
        plan.tasks.append(task)
        self.storage.write_plan(plan_id, plan.model_dump(mode="json"))

        self.storage.append_ledger(LedgerEntry(
            phase=self.current_phase,
            task_id=task.id,
            action=LedgerAction.ARTIFACT,
            details=f"Task '{task.id}' ({title}) 已添加到 Plan '{plan_id}'",
        ))

        return {"ok": True, "message": f"Task '{task.id}' 已添加", "task_id": task.id}

    def list_tasks(self) -> dict:
        """列出当前 Plan 的所有 Task"""
        plan_id = self.storage.get_current_plan_id()
        if plan_id is None:
            return {"ok": False, "message": "当前无活跃 Plan"}

        plan_data = self.storage.read_plan(plan_id)
        if plan_data is None:
            return {"ok": False, "message": f"Plan '{plan_id}' 不存在"}

        plan = Plan(**plan_data)
        tasks_info = []
        for t in plan.tasks:
            tasks_info.append({
                "id": t.id,
                "title": t.title,
                "module": t.module,
                "acceptance": t.acceptance,
                "status": t.status.value,
                "has_contract": t.contract is not None,
            })

        return {
            "ok": True,
            "plan_id": plan_id,
            "spec_id": plan.spec_id,
            "total_tasks": len(plan.tasks),
            "tasks": tasks_info,
        }

    def add_contract(self, task_id: str, module: str, signature: str) -> dict:
        """为 Task 添加 Contract（Stage3 contract 阶段）"""
        plan_id = self.storage.get_current_plan_id()
        if plan_id is None:
            return {"ok": False, "message": "当前无活跃 Plan"}

        plan_data = self.storage.read_plan(plan_id)
        if plan_data is None:
            return {"ok": False, "message": f"Plan '{plan_id}' 不存在"}

        plan = Plan(**plan_data)
        task = next((t for t in plan.tasks if t.id == task_id), None)
        if task is None:
            return {"ok": False, "message": f"Task '{task_id}' 不存在于当前 Plan"}

        contract = Contract(module=module, interface_signature=signature)
        task.contract = contract
        task.status = TaskStatus.CONTRACTED
        self.storage.write_plan(plan_id, plan.model_dump(mode="json"))

        self.storage.append_ledger(LedgerEntry(
            phase=self.current_phase,
            task_id=task_id,
            action=LedgerAction.ARTIFACT,
            details=f"Contract 已添加: {module}.{signature[:50]}",
        ))

        return {"ok": True, "message": f"Task '{task_id}' 的 Contract 已添加", "contract_id": task_id}

    def skip_task(self, task_id: str, reason: str) -> dict:
        """跳过 todo/contracted 状态的 task"""
        plan_id = self.storage.get_current_plan_id()
        if plan_id is None:
            return {"ok": False, "message": "当前无活跃 Plan"}

        plan_data = self.storage.read_plan(plan_id)
        if plan_data is None:
            return {"ok": False, "message": f"Plan '{plan_id}' 不存在"}

        plan = Plan(**plan_data)
        task = next((t for t in plan.tasks if t.id == task_id), None)
        if task is None:
            return {"ok": False, "message": f"Task '{task_id}' 不存在于当前 Plan"}

        if not task.can_skip():
            return {
                "ok": False,
                "message": f"Task '{task_id}' 已进入实现阶段，无法 skip；如需放弃请先 git stash 或 git checkout 清理工作区",
            }

        task.status = TaskStatus.SKIPPED
        self.storage.write_plan(plan_id, plan.model_dump(mode="json"))
        self.storage.append_ledger(LedgerEntry(
            phase=self.current_phase,
            task_id=task_id,
            action=LedgerAction.SKIP,
            reason=reason,
        ))
        return {"ok": True, "message": f"Task '{task_id}' 已 skipped"}

    def commit_task(self, task_id: str) -> dict:
        """校验门禁 → git commit → 写账本 → task→done
        
        P1-3: 只能在 Stage5 (verify) 或之后 commit
        """
        phase = self.current_phase
        if phase < 5:
            return {
                "ok": False, "message": f"当前在 Stage{phase} ({self.PHASE_NAMES[phase]})，"
                f"commit 只能在 Stage5 (verify) 及之后执行。请先完成前序阶段"
            }
        if self.gate_runner is None or self.git is None:
            return {"ok": False, "message": "commit 需要 GateRunner 和 GitPort"}

        # 检查 Stage5/6 门禁
        stage5 = self._check_exit_gate(5)
        if not stage5["ok"]:
            return {"ok": False, "message": f"Stage5 (verify) 门禁未通过: {stage5['message']}"}

        stage6 = self._check_exit_gate(6)
        if not stage6["ok"]:
            return {"ok": False, "message": f"Stage6 (review) 门禁未通过: {stage6['message']}"}

        # 查找 task
        plan_id = self.storage.get_current_plan_id()
        if plan_id is None:
            return {"ok": False, "message": "当前无活跃 Plan"}

        plan_data = self.storage.read_plan(plan_id)
        if plan_data is None:
            return {"ok": False, "message": f"Plan '{plan_id}' 不存在"}

        plan = Plan(**plan_data)
        task = next((t for t in plan.tasks if t.id == task_id), None)
        if task is None:
            return {"ok": False, "message": f"Task '{task_id}' 不存在于当前 Plan"}

        # 检查 git status
        git_status = self.git.status()
        if not git_status:
            return {"ok": False, "message": "工作区无变更，无法 commit"}

        # 执行 git commit
        commit_msg = f"{task.title} ({task_id})"
        sha = self.git.add_and_commit(commit_msg)
        if sha is None:
            return {"ok": False, "message": "git commit 失败"}

        # 写账本 + 推进 task
        task.status = TaskStatus.DONE
        task.commits.append(sha)
        self.storage.write_plan(plan_id, plan.model_dump(mode="json"))
        self.storage.append_ledger(LedgerEntry(
            phase=self.current_phase,
            task_id=task_id,
            action=LedgerAction.COMMIT,
            commit=sha,
            details=commit_msg,
        ))
        return {"ok": True, "message": f"Task '{task_id}' 已 commit ({sha[:8]})", "commit": sha}

    def suspend(self, note: str = "") -> dict:
        """挂起当前工作流"""
        phase = self.current_phase
        spec_id = self.storage.get_current_spec_id() or "unknown"
        handoff_content = self._generate_handoff(phase, spec_id, note)
        self.storage.write_handoff(phase, handoff_content)
        self.storage.set_suspended(True)
        self.storage.append_ledger(LedgerEntry(
            phase=phase,
            action=LedgerAction.SUSPEND,
            details=note or "suspend",
        ))
        return {"ok": True, "message": f"已挂起在 Stage{phase}，handoff 文件已生成"}

    def resume(self) -> dict:
        """从挂起状态恢复（P2-19: 验证恢复后文件系统一致性）"""
        handoff = self.storage.find_latest_handoff()
        if handoff is None:
            return {"ok": False, "message": "未找到 handoff 文件，无法 resume"}

        phase, content = handoff

        # P2-19: 验证账本中的 spec/plan 引用是否仍存在
        warnings = []
        spec_id = self.storage.get_current_spec_id()
        if spec_id and self.storage.read_spec(spec_id) is None:
            warnings.append(f"账本引用 Spec '{spec_id}' 但文件已不存在")
        plan_id = self.storage.get_current_plan_id()
        if plan_id and self.storage.read_plan(plan_id) is None:
            warnings.append(f"账本引用 Plan '{plan_id}' 但文件已不存在")

        # 恢复阶段 + 写账本
        self.storage.set_current_phase(phase)
        self.storage.set_suspended(False)
        self.storage.append_ledger(LedgerEntry(
            phase=phase,
            action=LedgerAction.RESUME,
            details=f"从 handoff-{phase}.md 恢复"
                    + (f"（⚠️ {len(warnings)} 个一致性警告）" if warnings else ""),
        ))

        gate_result = self._check_exit_gate(phase)
        result = {
            "ok": True,
            "phase": phase,
            "phase_name": self.PHASE_NAMES[phase],
            "warnings": warnings,
            "gate": gate_result,
        }
        if gate_result["ok"]:
            result["message"] = (
                f"已恢复到 Stage{phase} ({self.PHASE_NAMES[phase]})，"
                f"当前阶段出口门禁已通过，可执行 devflow next 推进"
            )
        else:
            result["message"] = (
                f"已恢复到 Stage{phase} ({self.PHASE_NAMES[phase]})，"
                f"当前阶段出口门禁未通过: {gate_result['message']}"
            )
        return result

    def get_status(self) -> dict:
        """返回当前状态（含 Spec/Plan/Task 摘要，P2-3）"""
        phase = self.current_phase
        blockers = []
        gate_result = self._check_exit_gate(phase)
        if not gate_result["ok"]:
            blockers.append(gate_result["message"])

        # P2-3: Spec 摘要
        spec_summary = None
        spec_id = self.storage.get_current_spec_id()
        if spec_id:
            spec_data = self.storage.read_spec(spec_id)
            if spec_data:
                goals = spec_data.get("goals") or []
                non_goals = spec_data.get("non_goals") or []
                problem = spec_data.get("problem") or ""
                placeholder_count = sum(
                    1 for g in goals if str(g).strip() in ("待补充", "")
                )
                spec_summary = {
                    "id": spec_id,
                    "title": spec_data.get("title", ""),
                    "status": spec_data.get("status", "draft"),
                    "problem_length": len(problem),
                    "goals_total": len(goals),
                    "goals_filled": len(goals) - placeholder_count,
                    "goals_placeholder": placeholder_count,
                    "non_goals_total": len(non_goals),
                    "non_goals_filled": sum(1 for g in non_goals if str(g).strip() not in ("待补充", "")),
                    "missing_fields": self._spec_missing_fields(spec_data),
                }

        # P2-3: Plan/Task 摘要
        plan_summary = None
        plan_id = self.storage.get_current_plan_id()
        if plan_id:
            plan_data = self.storage.read_plan(plan_id)
            if plan_data:
                tasks = plan_data.get("tasks", [])
                by_status = {"todo": 0, "contracted": 0, "implementing": 0,
                             "verifying": 0, "reviewing": 0, "done": 0, "skipped": 0}
                missing_contract = 0
                for t in tasks:
                    s = t.get("status", "todo")
                    by_status[s] = by_status.get(s, 0) + 1
                    if s != "skipped" and t.get("contract") is None:
                        missing_contract += 1
                plan_summary = {
                    "id": plan_id,
                    "total_tasks": len(tasks),
                    "by_status": by_status,
                    "missing_contract": missing_contract,
                    "done_ratio": f"{by_status.get('done', 0)}/{len(tasks)}",
                }

        return {
            "current_phase": phase,
            "current_phase_name": self.PHASE_NAMES[phase],
            "next_phase_name": self.PHASE_NAMES[phase + 1] if phase + 1 < len(self.PHASE_NAMES) else None,
            "current_spec_id": spec_id,
            "current_plan_id": plan_id,
            "suspended": self.storage.is_suspended(),
            "blockers": blockers,
            "ledger_entries_count": len(self.storage.get_ledger().get("entries", [])),
            "spec_summary": spec_summary,
            "plan_summary": plan_summary,
        }

    @staticmethod
    def _spec_missing_fields(spec_data: dict) -> list[str]:
        """列出 Spec 缺失/不完整的字段"""
        missing = []
        title = str(spec_data.get("title", "")).strip()
        problem = str(spec_data.get("problem", "")).strip()
        goals = spec_data.get("goals") or []
        non_goals = spec_data.get("non_goals") or []
        if not title or title == "draft":
            missing.append("title")
        if len(problem) < 10:
            missing.append("problem (≥10 字符)")
        if not goals:
            missing.append("goals (≥1 项)")
        elif all(str(g).strip() in ("待补充", "") for g in goals):
            missing.append("goals (全部为占位「待补充」)")
        if not non_goals:
            missing.append("non_goals (≥1 项)")
        return missing

    def run_gate(self, phase: int) -> dict:
        """执行指定阶段的门禁"""
        if phase < 0 or phase >= len(self.PHASE_NAMES):
            return {"ok": False, "message": f"无效阶段号: {phase}（有效范围 0-7）"}

        results = []
        # 内置门禁
        builtin = self._check_exit_gate(phase)
        results.append({
            "gate": f"Stage{phase}_builtin",
            "pass": builtin["ok"],
            "message": builtin.get("message", ""),
        })

        # 外部门禁（委托给 GateRunner）
        if self.gate_runner:
            for gate_name, gate_config in self.gate_runner.get_enabled_gates_for_stage(phase):
                gate_result = self.gate_runner.run_gate_by_name(gate_name)
                results.append({
                    "gate": gate_name,
                    "pass": gate_result["ok"],
                    "message": gate_result.get("message", ""),
                })

        # review_gate 门禁
        if self.review_engine and phase >= 2:
            review_gate = self.config.gates.get("review_gate")
            if review_gate and review_gate.enabled and review_gate.bind_to_stage == phase:
                rv = self.review_engine.check_review_gate()
                results.append({
                    "gate": "review_gate",
                    "pass": rv["ok"],
                    "message": rv.get("message", ""),
                    "violations": rv.get("violations", []),
                })

        all_pass = all(r["pass"] for r in results)
        return {"ok": all_pass, "gates": results}

    # --- 内部门禁检查（纯逻辑，不执行命令） ---

    def _check_exit_gate(self, phase: int) -> dict:
        """检查指定阶段的出口门禁"""
        if phase == 0:
            return self._gate_intake()
        elif phase == 1:
            return self._gate_brainstorm()
        elif phase == 2:
            return self._gate_plan()
        elif phase == 3:
            return self._gate_contract()
        elif phase == 4:
            return self._gate_implement()
        elif phase == 5:
            return self._gate_verify()
        elif phase == 6:
            return self._gate_review()
        elif phase == 7:
            return self._gate_finish()
        return {"ok": False, "message": f"未知阶段: {phase}"}

    def _gate_intake(self) -> dict:
        """Intake 闸门（P2-5: 读取 sop.yaml 中 intake_gate 配置）"""
        if self.storage.get_current_spec_id() is None:
            return {"ok": False, "message": "当前无活跃 Spec，请先执行 devflow start"}

        # P2-5: 读取 intake_gate 配置（若未启用或 kind 非 triage 则视为 advisory 通过）
        intake_gate = self.config.gates.get("intake_gate")
        if intake_gate and not intake_gate.enabled:
            return {"ok": True, "message": "Intake 闸门已禁用，跳过"}

        # 默认 require 字段（从 sop.yaml intake_gate.require 读取）
        require_state = "ready-for-agent"
        if intake_gate and intake_gate.kind == "triage" and intake_gate.require:
            require_state = intake_gate.require

        # 检查 ledger 是否有匹配的 triage 记录
        ledger = self.storage.get_ledger()
        has_triage = any(
            e.get("action") == "triage" and
            require_state in str(e.get("details", ""))
            for e in ledger.get("entries", [])
        )
        if has_triage:
            return {"ok": True, "message": f"Intake 闸门通过 (triage_state={require_state})"}
        if self.config.intake_fast_skip:
            return {"ok": True, "message": f"Intake 闸门通过 (intake_fast_skip=true，自动 {require_state})"}
        return {"ok": False, "message": f"Intake 闸门未通过: 需要 triage_state={require_state}"}

    def _gate_brainstorm(self) -> dict:
        spec_id = self.storage.get_current_spec_id()
        if spec_id is None:
            return {"ok": False, "message": "当前无活跃 Spec"}
        spec_data = self.storage.read_spec(spec_id)
        if spec_data is None:
            return {"ok": False, "message": f"Spec '{spec_id}' 不存在"}
        try:
            spec = Spec(**spec_data)
        except Exception as e:
            missing = []
            if "non_goals" in str(e): missing.append("non_goals (至少 1 项)")
            if "goals" in str(e): missing.append("goals (非空列表)")
            if "problem" in str(e): missing.append("problem (≥10 字符)")
            if not missing: missing.append(f"解析错误: {e}")
            return {"ok": False, "message": "Spec 必填字段不齐", "missing": missing}
        if spec.status != SpecStatus.APPROVED:
            missing = spec.missing_required_fields()
            return {"ok": False, "message": f"Spec 未 approved（当前 status={spec.status.value}）", "missing": missing}
        missing = spec.missing_required_fields()
        if missing:
            return {"ok": False, "message": "Spec 必填字段不齐", "missing": missing}
        return {"ok": True, "message": "Spec 已 approved 且必填字段齐全"}

    def _gate_plan(self) -> dict:
        plan_id = self.storage.get_current_plan_id()
        if plan_id is None:
            return {"ok": False, "message": "当前无活跃 Plan，请先创建 Plan"}
        plan_data = self.storage.read_plan(plan_id)
        if plan_data is None:
            return {"ok": False, "message": f"Plan '{plan_id}' 不存在"}
        plan = Plan(**plan_data)
        if not plan.tasks:
            return {"ok": False, "message": "Plan 中无 Task"}
        issues = []
        for task in plan.tasks:
            if not task.module.strip(): issues.append(f"{task.id}: module 为空")
            if not task.acceptance: issues.append(f"{task.id}: acceptance 为空")
        if issues:
            return {"ok": False, "message": "Task 字段校验失败", "missing": issues}
        return {"ok": True, "message": f"Plan 含 {len(plan.tasks)} 个 Task，字段齐全"}

    def _gate_contract(self) -> dict:
        plan_id = self.storage.get_current_plan_id()
        if plan_id is None:
            return {"ok": False, "message": "当前无活跃 Plan"}
        plan_data = self.storage.read_plan(plan_id)
        if plan_data is None:
            return {"ok": False, "message": f"Plan '{plan_id}' 不存在"}
        plan = Plan(**plan_data)
        issues = []
        for task in plan.tasks:
            if task.status == TaskStatus.SKIPPED:
                continue
            if task.contract is None:
                issues.append(f"{task.id}: 缺少 Contract")
            elif not task.contract.module.strip():
                issues.append(f"{task.id}: Contract.module 为空")
            elif not task.contract.interface_signature.strip():
                issues.append(f"{task.id}: Contract.interface_signature 为空")
        if issues:
            return {"ok": False, "message": "Contract 校验失败", "missing": issues}
        return {"ok": True, "message": "所有 Task 的 Contract 齐全"}

    def _gate_implement(self) -> dict:
        has_changes = self.git is not None and bool(self.git.status())
        if has_changes:
            return {"ok": True, "message": "工作区有代码变更"}
        plan_id = self.storage.get_current_plan_id()
        if plan_id:
            plan_data = self.storage.read_plan(plan_id)
            if plan_data:
                plan = Plan(**plan_data)
                all_done = all(t.status in (TaskStatus.DONE, TaskStatus.SKIPPED) for t in plan.tasks)
                if all_done and plan.tasks:
                    return {"ok": True, "message": "所有 Task 均为 done/skipped，无代码变更需要提交"}
        return {"ok": False, "message": "工作区无代码变更且存在未完成的 Task"}

    def _gate_verify(self) -> dict:
        if self.gate_runner is None:
            return {"ok": False, "message": "GateRunner 未注入，无法执行 tests_pass"}
        return self.gate_runner.run_tests_pass()

    def _gate_review(self) -> dict:
        if self.gate_runner is None:
            return {"ok": True, "message": "GateRunner 未注入，跳过 ci_green"}
        return self.gate_runner.run_ci_green()

    def _gate_finish(self) -> dict:
        ledger = self.storage.get_ledger()
        entries = ledger.get("entries", [])
        phases_covered = {e.get("phase") for e in entries}
        missing_phases = [p for p in range(8) if p not in phases_covered]
        if missing_phases:
            return {"ok": False, "message": f"账本不完整，缺少阶段记录: {missing_phases}"}
        plan_id = self.storage.get_current_plan_id()
        if plan_id:
            plan_data = self.storage.read_plan(plan_id)
            if plan_data:
                plan = Plan(**plan_data)
                not_done = [t.id for t in plan.tasks if t.status not in (TaskStatus.DONE, TaskStatus.SKIPPED)]
                if not_done:
                    return {"ok": False, "message": f"以下 Task 未完成: {not_done}"}
        return {"ok": True, "message": "账本完整，所有 Task 已完成"}

    def _archive_on_finish(self) -> dict:
        """v0.3 第一性方案：进入 finish 时软归档活跃 Spec

        不移动文件，仅在 ledger.yaml 的 archive 段添加记录。
        保留文件原位便于用户后续查看与查阅。
        """
        phase = self.current_phase
        spec_id = self.storage.get_current_spec_id()

        # 调用 storage 软归档接口
        archive_record = None
        if spec_id and hasattr(self.storage, "archive_spec"):
            archive_record = self.storage.archive_spec(
                spec_id=spec_id,
                reason="completed via devflow finish (Stage 7)",
                final_stage=phase,
            )
            self.storage.append_ledger(LedgerEntry(
                phase=phase,
                action=LedgerAction.PHASE_TRANSITION,
                details=f"工作流完成，Spec '{spec_id}' 已软归档（文件保留原位）",
            ))
        return {
            "ok": True,
            "phase": phase,
            "message": f"工作流已完成（Stage{phase} finish），Spec '{spec_id}' 已软归档",
            "archived": archive_record is not None,
            "archive_record": archive_record,
        }

    # --- Task 状态推进 ---

    def _advance_tasks_for_phase(self, phase: int) -> None:
        plan_id = self.storage.get_current_plan_id()
        if plan_id is None:
            return
        plan_data = self.storage.read_plan(plan_id)
        if plan_data is None:
            return
        plan = Plan(**plan_data)
        changed = False
        transitions = {
            3: (TaskStatus.TODO, TaskStatus.CONTRACTED),
            4: (TaskStatus.CONTRACTED, TaskStatus.IMPLEMENTING),
            5: (TaskStatus.IMPLEMENTING, TaskStatus.VERIFYING),
            6: (TaskStatus.VERIFYING, TaskStatus.REVIEWING),
        }
        if phase in transitions:
            from_status, to_status = transitions[phase]
            for t in plan.tasks:
                if t.status == from_status:
                    t.status = to_status
                    changed = True
        if changed:
            self.storage.write_plan(plan_id, plan.model_dump(mode="json"))

    # --- Handoff 生成 ---

    def _generate_handoff(self, phase: int, spec_id: str, note: str) -> str:
        phase_name = self.PHASE_NAMES[phase]
        lines = [
            f"# Handoff — Stage{phase} ({phase_name})",
            "", "## 挂起位置",
            f"- 阶段: Stage{phase} ({phase_name})", f"- Spec: {spec_id}",
            "", "## 建议的续接能力",
            "- devflow resume（恢复阶段状态）",
            "- devflow next（推进到下一阶段）",
            "- devflow status（查看当前状态）",
            "", "## 工件引用（按路径引用，非复制）",
            f"- Spec: specs/{spec_id}.yaml",
            f"- Plan: plans/{spec_id}.yaml（如存在）",
            "- 账本: progress.yaml", "",
        ]
        if note:
            lines.extend(["## 挂起笔记", note, ""])
        return "\n".join(lines)

    # --- 工具方法 ---

    @staticmethod
    def _make_spec_id(draft: str) -> str:
        date_prefix = datetime.now().strftime("%Y%m%d")
        words = re.findall(r'[a-zA-Z\u4e00-\u9fff]+', draft)[:5]
        slug = "-".join(w.lower()[:10] for w in words) if words else "untitled"
        slug = re.sub(r'[^a-z0-9\u4e00-\u9fff-]', '', slug)[:50]
        return f"{date_prefix}-{slug}"
