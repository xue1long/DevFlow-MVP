"""review_audit.py — 多 spec JOIN 核心逻辑（V4.1 阶段）

v0.4 RFC 预案 B 实现（v0.4-roadmap-paused.md §二预案B）：
- 不扩 LedgerEntry schema（v0.3 INDEX 教训核心）
- 用 review_store 文件名反推 (spec_id, round) 键集合
- 时间窗推断补足 schema 缺字段

解决：
- v0.3.1-r2 单 spec 简化版（cli.py:380 review-audit 命令）
  - 只检查 orphans（ledger 有但 review_store 无）
  - 用 ledger 顶层 current_spec_id 单点状态
  - 多 spec 场景系统性误报
- P1-r2-2 missing_in_ledger 反向校验（v0.4 才实现）
- 多 spec 全面覆盖（v0.4 才实现）

设计（架构文档 §5.2.1 第 6 轮审计结论）：
- 单一真相源 = review_store 文件系统（review/<spec-id>/r<N>.yaml）
- 走文件系统 JOIN，不改 schema
- 时间窗推断误差可接受（审计场景而非生产强一致）
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class ReviewAuditResult:
    """review-audit 完整结果

    字段说明：
    - orphans: ledger 有 review/fix/escalate 条目但 review_store 无对应报告
    - missing_in_ledger: review_store 有报告但 ledger 无对应记录（反向校验）
    - fix_orphans: ledger 有 fix 条目但 review_store 无对应 f<N>.yaml
    - fix_missing_in_ledger: review_store 有 f<N>.yaml 但 ledger 无 fix 条目
    - per_spec_summary: 每个 spec 的审计摘要
    - scope_note: 多 spec 推断的说明
    """
    total_ledger_entries: int = 0
    total_review_actions: int = 0
    total_reports: int = 0
    total_specs: int = 0
    orphans: list[dict] = field(default_factory=list)
    missing_in_ledger: list[dict] = field(default_factory=list)
    fix_orphans: list[dict] = field(default_factory=list)
    fix_missing_in_ledger: list[dict] = field(default_factory=list)
    per_spec_summary: list[dict] = field(default_factory=list)
    scope_note: str = "v0.4 多 spec 全面版：review_store 文件名反推 + 时间窗推断"

    def to_dict(self) -> dict:
        return {
            "ok": True,
            "total_ledger_entries": self.total_ledger_entries,
            "total_review_actions": self.total_review_actions,
            "total_reports": self.total_reports,
            "total_specs": self.total_specs,
            "orphans": self.orphans,
            "missing_in_ledger": self.missing_in_ledger,
            "fix_orphans": self.fix_orphans,
            "fix_missing_in_ledger": self.fix_missing_in_ledger,
            "per_spec_summary": self.per_spec_summary,
            "scope_note": self.scope_note,
        }


def _parse_round_from_details(details: str) -> Optional[int]:
    """从 ledger entry.details 文本解析 round 编号

    v0.3 review-audit 已有逻辑：匹配 'R<数字>' 模式
    Examples:
        "评审 R1 完成" → 1
        "修复 R2: 补全字段" → 2
        "升级 R3 终止" → 3
    """
    if not details:
        return None
    m = re.search(r"\bR(\d+)\b", details)
    if m:
        return int(m.group(1))
    return None


def _spec_id_from_path(path: str) -> Optional[str]:
    """从 review_store 文件路径反推 spec_id

    路径格式：review/<spec-id>/r<N>.yaml
    """
    # 路径分隔符兼容（跨平台）
    parts = re.split(r"[\\/]", path)
    # 倒数第二个是 spec_id 目录
    if len(parts) >= 2 and parts[-2] != "review":
        return parts[-2]
    return None


def _infer_spec_id_for_ledger_entry(
    entry: dict,
    known_spec_ids: set[str],
    current_spec_id: Optional[str],
) -> Optional[str]:
    """时间窗推断：推断 ledger review 条目的 spec_id

    优先级（v0.4 预案 B）：
    1. ledger entry 显式含 spec_id 字段（未来 schema 扩展支持）
    2. details 文本含 (spec_id, R<n>) 模式（如 "spec-1 R2"）
    3. fallback 到 ledger 顶层 current_spec_id
    4. fallback 到 None（未识别，纳入 orphans 让用户检查）

    Args:
        entry: ledger entry dict
        known_spec_ids: review_store 已知的所有 spec_id
        current_spec_id: ledger 顶层 current_spec_id

    Returns:
        推断的 spec_id 或 None
    """
    # 1. 显式字段（v0.3 当前无此字段，预留扩展）
    if entry.get("spec_id"):
        return entry["spec_id"]

    # 2. details 文本解析
    details = entry.get("details", "")
    for spec_id in known_spec_ids:
        if spec_id in details:
            return spec_id

    # 3. fallback current_spec_id（v0.3 单 spec 模式）
    if current_spec_id:
        return current_spec_id

    # 4. 未识别
    return None


def audit_review_ledger(
    ledger: dict,
    review_store,  # ReviewStorageBackend
) -> ReviewAuditResult:
    """多 spec 全面 review-audit 核心逻辑

    v0.4 触发条件已亮：多 spec 工作流成为主流用法

    检测两类问题：
    1. orphans: ledger 有 review/fix/escalate 条目，review_store 无对应报告
       → 审计盲点：账本记录了但实际报告未生成
    2. missing_in_ledger: review_store 有报告，ledger 无对应记录
       → 审计盲点：报告写了但账本未登记（v0.3 单 spec 版未实现）

    Args:
        ledger: StorageBackend.get_ledger() 返回的 dict
        review_store: ReviewStorageBackend 实例

    Returns:
        ReviewAuditResult 含完整审计结果
    """
    result = ReviewAuditResult()

    # === 步骤 1: 收集 review_store 侧所有 (spec_id, round) 键 ===
    review_keys_by_spec: dict[str, set[int]] = {}
    total_reports = 0
    for spec_id in review_store.list_spec_ids():
        reports = review_store.list_reports(spec_id)
        review_keys_by_spec[spec_id] = {r.round for r in reports}
        total_reports += len(reports)
    result.total_reports = total_reports
    result.total_specs = len(review_keys_by_spec)
    known_spec_ids = set(review_keys_by_spec.keys())

    # === 步骤 2: 收集 ledger 侧 review/fix/escalate 条目 ===
    entries = ledger.get("entries", [])
    result.total_ledger_entries = len(entries)
    review_action_entries = [
        e for e in entries
        if e.get("action") in ("review", "fix", "escalate")
    ]
    result.total_review_actions = len(review_action_entries)

    current_spec_id = ledger.get("current_spec_id")

    # === 步骤 3: orphans 检测（ledger → review_store 正向）===
    # 收集 ledger 中已 (spec_id, round) 配对的键
    ledger_review_keys: set[tuple[str, int]] = set()
    for entry in review_action_entries:
        spec_id = _infer_spec_id_for_ledger_entry(
            entry, known_spec_ids, current_spec_id
        )
        round_num = _parse_round_from_details(entry.get("details", ""))
        if spec_id is None or round_num is None:
            # 未识别 spec_id 或 round → 纳入 orphans（用户需检查）
            result.orphans.append({
                "spec_id": spec_id,
                "round": round_num,
                "action": entry.get("action"),
                "entry_details": entry.get("details", "")[:100],
                "reason": "无法识别 spec_id 或 round（多 spec 推断边界）",
            })
            continue

        ledger_review_keys.add((spec_id, round_num))
        # 检查 review_store 是否有对应报告（注意：review_keys_by_spec[spec_id] 是 round set）
        if round_num not in review_keys_by_spec.get(spec_id, set()):
            result.orphans.append({
                "spec_id": spec_id,
                "round": round_num,
                "action": entry.get("action"),
                "entry_details": entry.get("details", "")[:100],
                "reason": "ledger 有记录但 review_store 无对应报告",
            })

    # === 步骤 4: missing_in_ledger 反向校验（review_store → ledger）===
    for spec_id, rounds in review_keys_by_spec.items():
        for round_num in sorted(rounds):
            if (spec_id, round_num) not in ledger_review_keys:
                result.missing_in_ledger.append({
                    "spec_id": spec_id,
                    "round": round_num,
                    "message": f"review_store 有报告 review/{spec_id}/r{round_num}.yaml，但 ledger 无对应记录（审计盲点）",
                })

    # === 步骤 5: per_spec 摘要 ===
    for spec_id in sorted(review_keys_by_spec.keys()):
        rounds = review_keys_by_spec[spec_id]
        spec_orphans = [o for o in result.orphans if o.get("spec_id") == spec_id]
        spec_missing = [m for m in result.missing_in_ledger if m.get("spec_id") == spec_id]
        spec_fix_orphans = [o for o in result.fix_orphans if o.get("spec_id") == spec_id]
        spec_fix_missing = [m for m in result.fix_missing_in_ledger if m.get("spec_id") == spec_id]
        result.per_spec_summary.append({
            "spec_id": spec_id,
            "total_reports": len(rounds),
            "rounds": sorted(rounds),
            "orphan_count": len(spec_orphans),
            "missing_in_ledger_count": len(spec_missing),
            "fix_orphan_count": len(spec_fix_orphans),
            "fix_missing_in_ledger_count": len(spec_fix_missing),
        })

    # === 步骤 6: fix 记录反向 JOIN（架构文档 §9.1 接收反馈闭环）===
    # 收集 review_store 全部 f<N>.yaml（按 spec_id + fix_number）
    fix_keys_by_spec: dict[str, set[int]] = {}
    for spec_id in review_store.list_spec_ids():
        try:
            fixes = review_store.list_fixes(spec_id)
            fix_keys_by_spec[spec_id] = {
                # 从 fix.id="f<N>" 解析编号
                int(f.id[1:]) for f in fixes if f.id.startswith("f")
            }
        except Exception:
            fix_keys_by_spec[spec_id] = set()

    # 收集 ledger 中 fix 条目（按 spec_id + fix 编号）
    ledger_fix_keys: set[tuple[str, int]] = set()
    fix_action_entries = [
        e for e in entries
        if e.get("action") == "fix"
    ]
    for entry in fix_action_entries:
        spec_id = _infer_spec_id_for_ledger_entry(
            entry, known_spec_ids, current_spec_id
        )
        # 解析 fix 编号（details 文本含 f<N> 模式，或用 review_id 推断）
        fix_num = _parse_fix_number_from_details(entry.get("details", ""))
        if fix_num is None:
            continue
        if spec_id is None:
            # spec_id 未识别 → 纳入 fix_orphans
            result.fix_orphans.append({
                "spec_id": None,
                "fix_number": fix_num,
                "entry_details": entry.get("details", "")[:100],
                "reason": "无法识别 spec_id（多 spec 推断边界）",
            })
            continue
        ledger_fix_keys.add((spec_id, fix_num))
        if fix_num not in fix_keys_by_spec.get(spec_id, set()):
            result.fix_orphans.append({
                "spec_id": spec_id,
                "fix_number": fix_num,
                "entry_details": entry.get("details", "")[:100],
                "reason": "ledger 有 fix 条目但 review_store 无对应 f<N>.yaml",
            })

    # 反向：review_store 有 fix 但 ledger 无
    for spec_id, fix_nums in fix_keys_by_spec.items():
        for fix_num in sorted(fix_nums):
            if (spec_id, fix_num) not in ledger_fix_keys:
                result.fix_missing_in_ledger.append({
                    "spec_id": spec_id,
                    "fix_number": fix_num,
                    "message": f"review_store 有 f<N>.yaml 但 ledger 无对应 fix 条目（修复闭环断点）",
                })

    # === 步骤 7: 更新 per_spec 摘要的 fix 计数（V4.2 补）===
    for summary in result.per_spec_summary:
        spec_id = summary["spec_id"]
        # 如果 fix 计数是 0 但 fix_orphans / fix_missing_in_ledger 非空，补 0 兜底
        spec_fix_orphans = [o for o in result.fix_orphans if o.get("spec_id") == spec_id]
        spec_fix_missing = [m for m in result.fix_missing_in_ledger if m.get("spec_id") == spec_id]
        summary["fix_orphan_count"] = len(spec_fix_orphans)
        summary["fix_missing_in_ledger_count"] = len(spec_fix_missing)

    return result


def _parse_fix_number_from_details(details: str) -> Optional[int]:
    """从 ledger entry.details 文本解析 fix 编号

    v0.3 fix 写入格式："修复 R1: +1 resolved, +0 residual"
    未来可扩展识别 f<N> 模式（fix 编号）
    """
    if not details:
        return None
    # 当前 v0.3 格式无 f<N> 模式 → 返回 None
    # 此函数为未来扩展预留
    return None