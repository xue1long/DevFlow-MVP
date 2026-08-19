"""ReviewEngine — 审核闭环引擎

双轴评审（Standards × Spec）：
- Standards 轴：自动执行（复用 RedLineAuditor 检查规则）
- Spec 轴：生成完整评审上下文，供 LLM 子代理消费

管理审核生命周期：创建报告 → 修复 → 复核 → 终止判断。
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from ..model.review import (
    ReviewReport, ReviewViolation, ReviewVerdict, ViolationSeverity,
    FixRecord, AxeReview,
)
from ..model.ledger import LedgerEntry, LedgerAction
from ..model.spec import Spec
from ..model.plan import Plan
from ..storage.base import StorageBackend
from ..storage.review_store import ReviewStore
from ..policy.loader import SOPConfig


class ReviewEngine:
    """审核闭环引擎"""

    # 最大审核轮次
    MAX_REVIEW_ROUNDS = 5

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
        review_store: ReviewStore,
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
            spec=AxeReview(
                verdict=ReviewVerdict.PASS,  # 默认 PASS，等待 LLM 结果填写
                violations=[],
            ),
        )

        # 写入报告
        self.review_store.write_report(report)

        # 写账本
        self.storage.append_ledger(LedgerEntry(
            phase=report.phase,
            action=LedgerAction.REVIEW,
            details=f"评审 R{round}: Standards={report.standards.verdict.value}, "
                    f"违规 {report.total_violations} 条 (fatal={report.fatal_count}, "
                    f"major={report.major_count}, minor={report.minor_count})",
        ))

        return {
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

        for vid in violation_ids:
            violation = latest.get_violation(vid)
            if violation is None:
                not_found.append(vid)
                continue

            if residual or skip:
                violation.residual = True
                violation.resolved = True
                residual_list.append(vid)
            else:
                violation.resolved = True
                violation.resolved_at = __import__("datetime").datetime.now().isoformat()
                resolved.append(vid)

        if not_found:
            return {"ok": False, "message": f"违规未找到: {not_found}", "not_found": not_found}

        # 写修复记录
        fix = FixRecord(
            id="",  # write_fix 会分配
            review_id=latest.id,
            resolved_violations=resolved,
            residual_violations=residual_list,
            summary=summary or f"修复了 {len(resolved)} 条违规，登记了 {len(residual_list)} 条残余风险",
        )
        self.review_store.write_fix(fix)

        # 更新报告（重新写入）
        self.review_store.write_report(latest)

        # 写账本
        self.storage.append_ledger(LedgerEntry(
            phase=latest.phase,
            action=LedgerAction.FIX,
            details=f"修复 R{latest.round}: +{len(resolved)} resolved, +{len(residual_list)} residual",
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
        """执行 Standards 轴自动检查"""
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
        ))

        return {
            "ok": True,
            "message": f"评审已达最大轮次 {self.MAX_REVIEW_ROUNDS}，已升级为 escalated，需人工介入",
            "report_id": report.id,
            "round": round,
            "escalated": True,
        }