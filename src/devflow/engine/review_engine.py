"""ReviewEngine — 审核闭环引擎

双轴评审（Standards × Spec）：
- Standards 轴：自动执行（复用 RedLineAuditor 检查规则）
- Spec 轴：生成完整评审上下文，供 LLM 子代理消费

管理审核生命周期：创建报告 → 修复 → 复核 → 终止判断。
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from ..model.review import (
    ReviewReport, ReviewViolation, ReviewVerdict, ViolationSeverity,
    FixRecord, AxeReview,
)
from ..model.ledger import LedgerEntry, LedgerAction
from ..model.spec import Spec
from ..model.plan import Plan
from ..model.task import TaskStatus
from ..storage.base import StorageBackend
from ..storage.review_store_base import ReviewStorageBackend
from ..policy.loader import SOPConfig
from .standards_checks import run_all_standards_checks, ALL_STANDARD_RULES
from .redline_auditor import RedLineAuditor


class ReviewEngine:
    """审核闭环引擎"""

    # 最大审核轮次
    MAX_REVIEW_ROUNDS = 5

    # 收敛判定：连续多少轮违规数不下降即触发提前升级
    STAGNATION_THRESHOLD = 2

    # 可自动验证修复的规则（fix 时重跑检查确认真修好了）
    # 单一真相源：从 standards_checks.ALL_STANDARD_RULES 派生，消除 rule 名重复硬编码。
    AUTO_VERIFIABLE_RULES = set(ALL_STANDARD_RULES)

    # v0.3.4: 红线规则的自动验证集（仅含已实现 + 非 mvp_skip 的红线）
    # 单一真相源：sop.yaml red_lines 中不跳过且有 checker 的规则
    REDLINE_AUTO_VERIFIABLE_RULES: set[str] = {
        "no_test", "cross_module_import", "huge_pr",
        "uncommitted_bulk", "main_incomplete",
    }

    # Standards 轴检查规则
    STANDARDS_RULES = {
        "no_test": "代码变更包含 .py 文件但无对应 test 文件",
        "cross_module_import": "导入了 forbidden_import 中定义的模块",
        "huge_pr": "变更文件数超过 pr_max_files",
        "uncommitted_bulk": "未提交文件数超过 20",
        "main_incomplete": "当前在 main/master 分支，建议在特性分支开发",
        "type_hint": "公开函数缺少类型注解（需人工确认）",
        "naming_convention": "命名不符合项目规范（需人工确认）",
        "doc_drift": "文档与代码不一致（需人工确认）",
    }

    def __init__(
        self,
        storage: StorageBackend,
        config: SOPConfig,
        review_store: ReviewStorageBackend,
    ):
        self.storage = storage
        self.config = config
        self.review_store = review_store

    # --- 主入口：执行评审 ---

    def review(self, spec_id: Optional[str] = None, round: Optional[int] = None) -> dict:
        """执行评审

        Args:
            spec_id: 指定 Spec ID，默认使用当前活跃 Spec
            round: 指定轮次，默认使用最新轮次+1

        Returns:
            {"ok": bool, "report": ReviewReport dict, ...}
        """
        # 确定 Spec
        if spec_id is None:
            spec_id = self.storage.get_current_spec_id()
        if spec_id is None:
            return {"ok": False, "message": "当前无活跃 Spec，请先执行 devflow start"}

        # 确定轮次
        if round is None:
            latest = self.review_store.latest_report(spec_id)
            round = (latest.round + 1) if latest else 1

        # 检查最大轮次
        if round > self.MAX_REVIEW_ROUNDS:
            return self._escalate(spec_id, round)

        # 收敛判定：连续多轮违规数不下降 → 提前升级，避免空耗
        stagnation = self._detect_stagnation(spec_id, round)
        if stagnation:
            return self._stagnation_escalate(spec_id, round, stagnation)

        # 收集审核工件
        artifacts = self._collect_artifacts(spec_id)
        if not artifacts["ok"]:
            return artifacts

        # 执行 Standards 轴（自动检查）
        standards_violations = self._run_standards_checks(artifacts)

        # 生成 Spec 轴评审上下文（供 LLM 子代理使用）
        spec_context = self._generate_spec_review_context(artifacts)

        # 构建评审报告
        report = ReviewReport(
            id=f"r{round}",
            spec_id=spec_id,
            round=round,
            phase=self.storage.get_current_phase(),
            standards=AxeReview(
                verdict=ReviewVerdict.FAIL if standards_violations else ReviewVerdict.PASS,
                violations=standards_violations,
            ),
            spec=self._run_spec_checks(spec_id),
        )

        # 回归检测：当前轮违规是否与历史已修规则复发
        regression_warnings = self._detect_regression(spec_id, round, report)
        if regression_warnings:
            # Bug #16: 写入正式字段而非私有属性，确保 model_dump()/持久化不丢失
            report.regression_warnings = regression_warnings

        # 写入报告（P1-14: 默认禁止覆写已有报告，历史不可篡改）
        self.review_store.write_report(report)

        # 写账本
        self.storage.append_ledger(LedgerEntry(
            phase=report.phase,
            action=LedgerAction.REVIEW,
            details=f"评审 R{round}: Standards={report.standards.verdict.value}, "
                    f"违规 {report.total_violations} 条 (fatal={report.fatal_count}, "
                    f"major={report.major_count}, minor={report.minor_count})",
            review_ref=f"r{round}",  # v0.4 P1-13
        ))

        result = {
            "ok": True,
            "message": f"评审 R{round} 完成",
            "report_id": report.id,
            "round": round,
            "spec_id": spec_id,
            "standards_verdict": report.standards.verdict.value,
            "spec_verdict": report.spec.verdict.value,
            "total_violations": report.total_violations,
            "fatal": report.fatal_count,
            "major": report.major_count,
            "minor": report.minor_count,
            "can_advance": report.can_advance(),
            "spec_review_prompt": spec_context,
            "report": report.model_dump(mode="json"),
        }
        if regression_warnings:
            result["regression_warnings"] = regression_warnings
        return result

    # --- 修复违规 ---

    def fix(self, violation_ids: list[str], summary: str = "",
            residual: bool = False, skip: bool = False) -> dict:
        """修复违规

        Args:
            violation_ids: 要修复的违规 ID 列表
            summary: 修复摘要
            residual: 是否登记为残余风险
            skip: 是否跳过（不修复，直接标记）

        Returns:
            {"ok": bool, "fix": FixRecord dict, ...}
        """
        spec_id = self.storage.get_current_spec_id()
        if spec_id is None:
            return {"ok": False, "message": "当前无活跃 Spec"}

        latest = self.review_store.latest_report(spec_id)
        if latest is None:
            return {"ok": False, "message": "没有找到评审报告，请先执行 devflow review"}

        resolved = []
        residual_list = []
        not_found = []
        unverified = []
        regression = []

        # 收集当前工件，用于重新验证
        artifacts = self._collect_artifacts(spec_id)
        verify_ok = artifacts.get("ok", False)
        # Bug #23 fix: 工件收集失败时不要静默放行(否则 fresh_violations 为空，
        # 所有 AUTO_VERIFIABLE_RULES 违规都会被自动标记为已修复，未真正复检)
        if not verify_ok:
            return {
                "ok": False,
                "message": f"工件收集失败，无法验证修复: {artifacts.get('message', '未知错误')}",
            }
        fresh_violations = self._run_standards_checks(artifacts)

        # v0.3.4: 红线违规也需自动验证。RedLineAuditor.audit() 只读、无副作用，
        # 返回 skip=True 的违规（mvp_skip/stub/not_implemented）应忽略。
        # ReviewEngine 不持有 git 实例，传入 None 即可（多数红线不依赖 git）。
        try:
            redline_auditor = RedLineAuditor(
                self.storage.root, self.config, git=None
            )
            fresh_redline = [
                v for v in redline_auditor.audit()
                if not v.skip  # 排除 mvp_skip/stub/not_implemented
            ]
        except Exception:
            fresh_redline = []  # 红线检查不可用时不阻塞

        for vid in violation_ids:
            violation = latest.get_violation(vid)
            if violation is None:
                not_found.append(vid)
                continue

            if residual or skip:
                violation.residual = True
                violation.resolved = True
                residual_list.append(vid)
                continue

            # 修复验证：可自动验证的规则，确认真修好了才标记 resolved
            if violation.rule in self.AUTO_VERIFIABLE_RULES:
                still_present = any(
                    fv.rule == violation.rule for fv in fresh_violations
                )
                if still_present:
                    unverified.append(vid)
                    continue
            # v0.3.4: 红线规则也走自动验证（仅限已实现检测的规则）
            elif violation.rule in self.REDLINE_AUTO_VERIFIABLE_RULES:
                still_present = any(
                    rv.rule == violation.rule for rv in fresh_redline
                )
                if still_present:
                    unverified.append(vid)
                    continue

            violation.resolved = True
            violation.resolved_at = __import__("datetime").datetime.now().isoformat()
            resolved.append(vid)

            # 回归检测：测试当前存在的违规是否与已 resolved 的违规同规则
            # （排查"修好了又复发"的情况）

        if not_found:
            return {"ok": False, "message": f"违规未找到: {not_found}", "not_found": not_found}

        if unverified:
            return {
                "ok": False,
                "message": f"以下违规未通过验证，修复未完成: {unverified}。"
                           f"请先真正修复（如补全 Spec 字段）再执行 devflow fix",
                "unverified": unverified,
            }

        # 写修复记录
        fix = FixRecord(
            id="",  # write_fix 会分配
            review_id=latest.id,
            resolved_violations=resolved,
            residual_violations=residual_list,
            summary=summary or f"修复了 {len(resolved)} 条违规，登记了 {len(residual_list)} 条残余风险",
        )
        self.review_store.write_fix(fix, spec_id)

        # 更新报告（仅维护 resolved 状态，使用专用更新方法）
        self.review_store.update_report(latest)

        # 写账本
        self.storage.append_ledger(LedgerEntry(
            phase=latest.phase,
            action=LedgerAction.FIX,
            details=f"修复 R{latest.round}: +{len(resolved)} resolved, +{len(residual_list)} residual",
            review_ref=f"r{latest.round}",  # v0.4 P1-13
        ))

        return {
            "ok": True,
            "message": f"已修复 {len(resolved)} 条，登记残余风险 {len(residual_list)} 条",
            "fix_id": fix.id,
            "resolved": resolved,
            "residual": residual_list,
        }

    # --- 查看审核历史 ---

    def history(self, spec_id: Optional[str] = None) -> dict:
        """查看审核历史"""
        if spec_id is None:
            spec_id = self.storage.get_current_spec_id()
        if spec_id is None:
            return {"ok": False, "message": "当前无活跃 Spec"}

        reports = self.review_store.list_reports(spec_id)
        fixes = self.review_store.list_fixes(spec_id)

        timeline = []
        for r in reports:
            timeline.append({
                "type": "review",
                "id": r.id,
                "round": r.round,
                "verdict": r.verdict.value,
                "total_violations": r.total_violations,
                "fatal": r.fatal_count,
                "major": r.major_count,
                "minor": r.minor_count,
                "resolved": r.resolved_count,
                "residual": r.residual_count,
                "phase": r.phase,
                "created_at": r.created_at,
            })

        for f in fixes:
            timeline.append({
                "type": "fix",
                "id": f.id,
                "review_id": f.review_id,
                "resolved": f.resolved_violations,
                "residual": f.residual_violations,
                "summary": f.summary,
                "created_at": f.created_at,
            })

        # 按时间排序
        timeline.sort(key=lambda x: x.get("created_at", ""))

        return {
            "ok": True,
            "spec_id": spec_id,
            "total_reviews": len(reports),
            "total_fixes": len(fixes),
            "latest_verdict": reports[-1].verdict.value if reports else "none",
            "can_advance": reports[-1].can_advance() if reports else True,
            "timeline": timeline,
        }

    # --- 门禁检查 ---

    def check_review_gate(self, spec_id: Optional[str] = None) -> dict:
        """检查评审门禁（用于状态机 gate 调用）"""
        if spec_id is None:
            spec_id = self.storage.get_current_spec_id()
        if spec_id is None:
            return {"ok": False, "message": "当前无活跃 Spec，请先执行 devflow start"}

        latest = self.review_store.latest_report(spec_id)
        if latest is None:
            return {"ok": False, "message": "未执行评审，请先执行 devflow review"}

        if latest.can_advance():
            return {"ok": True, "message": f"评审 R{latest.round} 通过 (verdict={latest.verdict.value})"}

        violations = [v for v in latest._all_violations() if not v.resolved and not v.residual]
        return {
            "ok": False,
            "message": f"评审 R{latest.round} 未通过 (verdict={latest.verdict.value})，"
                       f"尚有 {len(violations)} 条未修复违规",
            "violations": [v.model_dump(mode="json") for v in violations],
        }

    # --- 内部方法 ---

    def _collect_artifacts(self, spec_id: str) -> dict:
        """收集审核所需的工件"""
        spec_data = self.storage.read_spec(spec_id)
        if spec_data is None:
            return {"ok": False, "message": f"Spec '{spec_id}' 不存在"}

        plan_id = self.storage.get_current_plan_id()
        plan_data = self.storage.read_plan(plan_id) if plan_id else None

        return {
            "ok": True,
            "spec_id": spec_id,
            "spec_data": spec_data,
            "plan_data": plan_data,
            "plan_id": plan_id,
        }

    def _run_standards_checks(self, artifacts: dict) -> list[ReviewViolation]:
        """执行 Standards 轴自动检查（委托给 engine.standards_checks）

        薄封装：保持 self._run_standards_checks(artifacts) 在 review()/fix()
        两处的调用契约不变。实际逻辑见 standards_checks.run_all_standards_checks。
        抽取不改变任何 id / rule / severity / axis / message / fix，保持字节级一致。
        """
        return run_all_standards_checks(artifacts)

    # --- P0-4: Spec 轴真实检查 ---

    def _run_spec_checks(self, spec_id: str) -> AxeReview:
        """Spec 轴真实检查：验证 Spec 目标是否被 Plan 覆盖

        当 Plan 存在时，检查：
        - 每个 Spec goal 是否在 Plan 中有对应 task
        - 每个 task 是否有 Contract（非 skipped）
        当 Plan 不存在时返回 PASS（不可评估，不误报）
        当 Spec 数据不完整时（非标准 Spec 格式），跳过 pydantic 构造改用 dict
        """
        spec_data = self.storage.read_spec(spec_id)
        plan_id = self.storage.get_current_plan_id()
        if spec_data is None or plan_id is None:
            return AxeReview(verdict=ReviewVerdict.PASS, violations=[])

        plan_data = self.storage.read_plan(plan_id)
        if plan_data is None:
            return AxeReview(verdict=ReviewVerdict.PASS, violations=[])

        # 使用 dict 访问以兼容不完整 Spec 数据（避免 pydantic 构造失败）
        goals = spec_data.get("goals", [])
        if not isinstance(goals, list):
            goals = []

        non_goals = spec_data.get("non_goals", [])
        if not isinstance(non_goals, list):
            non_goals = []

        violations = []
        idx = 0

        # 检查每个 goal 是否在 Plan 中有对应
        for goal in goals:
            g = str(goal).strip()
            if g in ("待补充", ""):
                continue
            covered = False
            goal_re = re.compile(rf"\b{re.escape(g)}\b")
            for t in plan_data.get("tasks", []):
                title = t.get("title", "")
                module = t.get("module", "")
                acceptance = t.get("acceptance", [])
                # Bug #24 fix: 用词边界正则,避免 "do" in "do something" 这类过宽匹配
                if (goal_re.search(title) or goal_re.search(module)
                        or any(goal_re.search(a) for a in acceptance)):
                    covered = True
                    break
            if not covered:
                idx += 1
                violations.append(ReviewViolation(
                    id=f"SP-{idx}",
                    axis="spec",
                    rule="spec_goal_uncovered",
                    severity=ViolationSeverity.MAJOR,
                    message=f"Spec 目标「{g}」在 Plan 中未找到对应 Task",
                ))

        # 检查每个非 skipped task 是否有 Contract
        for t in plan_data.get("tasks", []):
            status = t.get("status", "")
            if status == "skipped":
                continue
            contract = t.get("contract")
            if contract is None:
                tid = t.get("id", "?")
                title = t.get("title", "?")
                idx += 1
                violations.append(ReviewViolation(
                    id=f"SP-{idx}",
                    axis="spec",
                    rule="spec_contract_missing",
                    severity=ViolationSeverity.MAJOR,
                    message=f"Task {tid} ({title}) 缺少 Contract",
                ))

        # 占位 goals 标记为 minor 提示
        placeholder_goals = sum(1 for g in goals if str(g).strip() in ("待补充", ""))
        if placeholder_goals > 0:
            idx += 1
            violations.append(ReviewViolation(
                id=f"SP-{idx}",
                axis="spec",
                rule="spec_goals_placeholder",
                severity=ViolationSeverity.MINOR,
                message=f"Spec 有 {placeholder_goals} 个占位 goal（待补充），建议补充完整",
            ))

        # v0.3.3: 思维模型检查(9 项,宽松默认: 有值才检查,MINOR 提示不阻断)
        thinking_cfg = getattr(self.config, "thinking", None)
        if thinking_cfg is None or thinking_cfg.enabled:
            thinking_violations = self._run_thinking_checks(spec_data, plan_data)
            for tv in thinking_violations:
                idx += 1
                tv.id = f"SP-{idx}"
                violations.append(tv)

        verdict = ReviewVerdict.FAIL if any(
            v.severity == ViolationSeverity.FATAL for v in violations
        ) else (
            ReviewVerdict.FAIL if any(
                v.severity == ViolationSeverity.MAJOR for v in violations
            ) else ReviewVerdict.PASS
        )
        return AxeReview(verdict=verdict, violations=violations)

    def _run_thinking_checks(self, spec_data: dict, plan_data: dict) -> list[ReviewViolation]:
        """v0.3.3 思维模型落地检查(9 项,宽松默认)

        每个思维 → 一个可选字段 + 一条 MINOR 检查规则。
        字段缺失不报错(宽松),有值但不符合规范才提示。
        所有提示 severity=MINOR,不阻断推进。
        """
        violations: list[ReviewViolation] = []

        def _add(rule: str, message: str) -> None:
            violations.append(ReviewViolation(
                id="TMP",  # 调用方会重编号
                axis="spec",
                rule=rule,
                severity=ViolationSeverity.MINOR,
                message=message,
            ))

        # --- WHY 维度 ---

        # 1. 第一性原理: goals 应基于底层假设;若声明了 assumptions 则检查每个 goal 可追溯
        assumptions = spec_data.get("assumptions", [])
        if not assumptions:
            _add(
                "thinking_first_principles",
                "第一性原理: 未声明 assumptions(底层假设清单)。建议列出 goals 依赖的底层事实,"
                "避免基于经验惯性推导。",
            )
        else:
            # 宽松检查: assumptions 非空且非占位即通过
            if all(str(a).strip() in ("", "待补充") for a in assumptions):
                _add(
                    "thinking_first_principles",
                    "第一性原理: assumptions 均为占位符,请补充真实的底层假设。",
                )

        # 2. 逆向思维: 事前验尸(premortem)
        premortem = spec_data.get("premortem", [])
        if not premortem:
            _add(
                "thinking_premortem",
                "逆向思维: 未做事前验尸(premortem)。建议先列'这个方案最可能怎么失败',"
                "再决定是否继续。",
            )
        elif all(str(p).strip() in ("", "待补充") for p in premortem):
            _add(
                "thinking_premortem",
                "逆向思维: premortem 均为占位符,请补充真实的失败场景。",
            )

        # --- DECIDE 维度 ---

        # 3. 损益/机会成本: 有 options 时应记录 decision 和 tradeoff
        options = spec_data.get("options", [])
        decision = spec_data.get("decision")
        tradeoff = spec_data.get("tradeoff")
        if options and not decision:
            _add(
                "thinking_tradeoff_decision",
                f"损益思维: 声明了 {len(options)} 个 options 但未记录 decision。"
                "建议明确选择哪条路径(机会成本记录)。",
            )
        elif decision and not tradeoff:
            _add(
                "thinking_tradeoff_tradeoff",
                "损益思维: 已记录 decision 但未记录 tradeoff(放弃了什么)。"
                "建议补充机会成本说明。",
            )

        # 4. 奥卡姆剃刀: 多 options 时提示确认最简方案
        if len(options) > 1:
            _add(
                "thinking_occam",
                f"奥卡姆剃刀: 存在 {len(options)} 个候选方案。"
                "如无必要勿增实体——确认是否选择了最简单可行的方案。",
            )

        # 5. 假设思维: assumptions 声明后应有验证计划(大胆假设,小心验证)
        if assumptions and any(str(a).strip() not in ("", "待补充") for a in assumptions):
            _add(
                "thinking_hypothesis",
                "假设思维: 已声明底层假设,建议为关键假设制定验证计划"
                "(大胆假设,小心拿数据事实去验证)。",
            )

        # --- DO 维度 ---

        # 6. 二八法则: P0 任务必须存在且完成(基于 plan_data)
        tasks = plan_data.get("tasks", [])
        p0_tasks = [t for t in tasks if t.get("priority", "P1") == "P0"]
        if p0_tasks:
            unfinished_p0 = [
                t for t in p0_tasks
                if t.get("status") not in ("done", "skipped")
            ]
            if unfinished_p0:
                _add(
                    "thinking_pareto",
                    f"二八法则: {len(unfinished_p0)} 个 P0 任务未完成"
                    f"({'/'.join(t.get('id', '?') for t in unfinished_p0[:3])})。"
                    "80% 成果来自 20% 关键动作,建议优先完成 P0。",
                )
        elif tasks:
            # 无 P0 任务(宽松提示)
            _add(
                "thinking_pareto",
                "二八法则: 计划中无 P0 任务。建议标记 1-2 个关键任务为 P0"
                "(80% 成果来自 20% 关键动作)。",
            )

        # 7. 能力圈: 圈外任务(learn/collab)应提示协作
        outside_tasks = [
            t for t in tasks
            if (t.get("owner_skill") or "").lower() in ("learn", "collab", "outside")
        ]
        if outside_tasks:
            _add(
                "thinking_capability_circle",
                f"能力圈: {len(outside_tasks)} 个任务标注为圈外"
                f"({'/'.join(t.get('id', '?') for t in outside_tasks[:3])})。"
                "圈外做事风险高,建议学习后做或找人协作。",
            )

        # 8. 反馈思维: 每个 task 应有可独立验证的 acceptance(小步反馈)
        no_acceptance_tasks = [
            t for t in tasks
            if not t.get("acceptance") or all(str(a).strip() in ("", "待补充") for a in t.get("acceptance", []))
        ]
        if no_acceptance_tasks:
            _add(
                "thinking_feedback_loop",
                f"反馈思维: {len(no_acceptance_tasks)} 个任务缺少可验证的验收标准"
                f"({'/'.join(t.get('id', '?') for t in no_acceptance_tasks[:3])})。"
                "小步获取反馈——每 task 应可独立验证。",
            )

        # 9. 冗余思维: 计划应预留缓冲(基于 plan_data.buffer)
        buffer = plan_data.get("buffer")
        if buffer is None:
            _add(
                "thinking_redundancy",
                "冗余思维: 计划未预留 buffer(缓冲比例)。不要把资源排满——"
                "预留安全垫应对意外。",
            )
        elif buffer <= 0:
            _add(
                "thinking_redundancy",
                f"冗余思维: buffer={buffer} 未预留缓冲。资源排满时任何意外都会连带延期。",
            )

        return violations

    def _generate_spec_review_context(self, artifacts: dict) -> str:
        """生成 Spec 轴评审上下文（供 LLM 子代理使用）"""
        spec_data = artifacts.get("spec_data", {})
        plan_data = artifacts.get("plan_data", {})

        context_parts = [
            "# Spec 轴评审上下文",
            "",
            "## 角色",
            "你是一个 Spec 吻合度评审员。审查实现是否与 Spec 保持一致。",
            "",
            "## Spec",
            f"- ID: {spec_data.get('id', 'N/A')}",
            f"- Title: {spec_data.get('title', 'N/A')}",
            f"- Problem: {spec_data.get('problem', 'N/A')}",
            f"- Goals: {spec_data.get('goals', [])}",
            f"- Non-goals: {spec_data.get('non_goals', [])}",
            f"- Status: {spec_data.get('status', 'N/A')}",
            "",
        ]

        if plan_data:
            context_parts.extend([
                "## Plan / Tasks",
            ])
            plan = Plan(**plan_data)
            for task in plan.tasks:
                context_parts.extend([
                    f"- Task {task.id}: {task.title}",
                    f"  - Module: {task.module}",
                    f"  - Acceptance: {task.acceptance}",
                    f"  - Status: {task.status.value}",
                    f"  - Contract: {task.contract.interface_signature if task.contract else 'N/A'}",
                    "",
                ])

        context_parts.extend([
            "## 检查要点",
            "1. 实现是否覆盖了 Spec 中定义的所有 goals？",
            "2. 实现是否引入了 Spec non_goals 中明确排除的功能？",
            "3. Contract 定义的接口签名是否与实现一致？",
            "4. 测试用例是否覆盖了 Spec 中描述的场景？",
            "5. 实现是否偏离了 Spec 中定义的 problem 范围？",
            "",
            "## 输出格式",
            "请输出违规清单（JSON），每条违规包含：",
            "- id: 格式 SP-001（递增编号）",
            "- severity: fatal | major | minor",
            "- rule: 违反的规则名称",
            "- message: 问题描述（至少 10 字符）",
            "- paths: 相关文件路径列表",
            "- fix: 建议修复方案",
        ])

        return "\n".join(context_parts)

    def _escalate(self, spec_id: str, round: int) -> dict:
        """超过最大轮次，升级处理"""
        report = ReviewReport(
            id=f"r{round}",
            spec_id=spec_id,
            round=round,
            phase=self.storage.get_current_phase(),
            status="escalated",
            standards=AxeReview(verdict=ReviewVerdict.ESCALATED),
            spec=AxeReview(verdict=ReviewVerdict.ESCALATED),
        )
        self.review_store.write_report(report)

        self.storage.append_ledger(LedgerEntry(
            phase=report.phase,
            action=LedgerAction.ESCALATE,
            details=f"评审 R{round} 升级: 超过最大轮次 {self.MAX_REVIEW_ROUNDS}，需人工介入",
            review_ref=f"r{round}",  # v0.4 P1-13
        ))

        return {
            "ok": True,
            "message": f"评审已达最大轮次 {self.MAX_REVIEW_ROUNDS}，已升级为 escalated，需人工介入",
            "report_id": report.id,
            "round": round,
            "escalated": True,
        }

    def _detect_stagnation(self, spec_id: str, current_round: int) -> Optional[dict]:
        """收敛判定：检查最近几轮违规数是否持续不下降

        规则：从当前轮-1 往前数 STAGNATION_THRESHOLD 轮，
        如果这些轮次（有违规的轮）的 total_violations 不递减，认为陷入停滞。

        Returns:
            停滞详情 dict，若无停滞返回 None
        """
        if current_round <= 1:
            return None

        reports = self.review_store.list_reports(spec_id)
        # 只看当前轮之前的历史（不含本轮，本轮还没写）
        history = [r for r in reports if r.round < current_round]
        if len(history) < self.STAGNATION_THRESHOLD:
            return None

        recent = history[-self.STAGNATION_THRESHOLD:]
        # P1-7: 使用未 resolved 的违规数，而非 total_violations（含已修复）
        counts = [r.total_violations - r.resolved_count for r in recent]

        # 全部轮次都有违规 且 违规数不下降（持平/上升都算停滞）
        # 契约:counts=[8,8] 视为停滞 → escalate（test_15 锁定）
        if all(c > 0 for c in counts):
            is_decreasing = all(
                counts[i + 1] < counts[i]
                for i in range(len(counts) - 1)
            )
            if not is_decreasing:
                return {
                    "recent_rounds": [r.round for r in recent],
                    "violation_counts": counts,
                    "threshold": self.STAGNATION_THRESHOLD,
                }
        return None

    def _stagnation_escalate(self, spec_id: str, round: int, stagnation: dict) -> dict:
        """停滞升级：违规数连续不降，提前终止循环"""
        report = ReviewReport(
            id=f"r{round}",
            spec_id=spec_id,
            round=round,
            phase=self.storage.get_current_phase(),
            status="escalated",
            standards=AxeReview(verdict=ReviewVerdict.ESCALATED),
            spec=AxeReview(verdict=ReviewVerdict.ESCALATED),
        )
        self.review_store.write_report(report)

        counts = stagnation["violation_counts"]
        rounds = stagnation["recent_rounds"]
        self.storage.append_ledger(LedgerEntry(
            phase=report.phase,
            action=LedgerAction.ESCALATE,
            details=f"评审 R{round} 升级: 违规数连续 {self.STAGNATION_THRESHOLD} 轮未下降 "
                    f"(轮次 {rounds}，违规数 {counts})，判定死循环，需人工介入",
            review_ref=f"r{round}",  # v0.4 P1-13
        ))

        return {
            "ok": True,
            "message": f"检测到死循环: 违规数连续 {self.STAGNATION_THRESHOLD} 轮未下降 "
                       f"({counts})，已升级为 escalated，需人工介入",
            "report_id": report.id,
            "round": round,
            "escalated": True,
            "reason": "stagnation",
            "stagnation": stagnation,
        }

    def _detect_regression(self, spec_id: str, current_round: int,
                            current_report: ReviewReport) -> list[dict]:
        """回归检测：当前轮违规是否与已修复的历史违规同规则复发"""
        if current_round <= 1:
            return []

        reports = self.review_store.list_reports(spec_id)
        history = [r for r in reports if r.round < current_round]
        if not history:
            return []

        # 收集所有历史已 resolved 的违规规则
        resolved_rules = set()
        for r in history:
            for v in r._all_violations():
                if v.resolved and not v.residual:
                    resolved_rules.add(v.rule)

        if not resolved_rules:
            return []

        # 检查当前轮是否出现相同规则的新违规
        current_rules = {v.rule for v in current_report._all_violations()}
        regressed = resolved_rules & current_rules

        if not regressed:
            return []

        return [
            {
                "rule": rule,
                "message": f"规则 '{rule}' 曾在历史评审中修复，本轮再次出现",
                "suggestion": "检查修复是否彻底，或考虑登记为残余风险（--residual）不再循环",
            }
            for rule in sorted(regressed)
        ]