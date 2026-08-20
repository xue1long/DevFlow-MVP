"""review_store_memory.py — MemoryReviewBackend（fixture 用）

实现 :class:`ReviewStorageBackend` 接口，所有数据存内存 dict，不写盘。
设计取舍与 MemoryStorageBackend 同构：

1. **目录结构不在物理层**:用 ``_reports: dict[spec_id, dict[round, ReviewReport]]``
   + ``_fixes: dict[spec_id, list[FixRecord]]`` 双层 dict 模拟文件系统。
2. **P1-14 不变量仍生效**:``write_report(force=False)`` 时若 (spec_id, round) 已在
   _reports 里仍抛 FileExistsError——**不可篡改承诺与介质无关**。
3. **路径是虚拟的**:`write_report` 返回 ``root / "review" / spec_id / f"r{round}.yaml"``，
   同 FSReviewBackend 的形状；测试断言 `(root / "review" / spec_id / "f1.yaml").exists()`
   **必须失败**——这是 Phase C 例外规则的物理体现。
4. **write_fix(fix, spec_id)**:spec_id 由调用方直接传入（与 FS 版本同契约），
   修复记录不再通过 review_id 反查 spec_id，避免不同 spec 的报告 id 冲突时错配。
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from ..model.review import ReviewReport, FixRecord
from .review_store_base import ReviewStorageBackend


class MemoryReviewBackend(ReviewStorageBackend):
    """内存版 ReviewStorageBackend（仅供 fixture 使用）。

    生产代码必须使用 :class:`FSReviewBackend`。设计权衡详见模块 docstring。
    """

    def __init__(self, root: Path | str = Path("/tmp/memory-review")):
        self._root = Path(root)
        # _reports[spec_id][round] = ReviewReport
        self._reports: dict[str, dict[int, ReviewReport]] = {}
        # _fixes[spec_id] = list[FixRecord]
        self._fixes: dict[str, list[FixRecord]] = {}

    # --- 评审报告 ---

    def write_report(self, report: ReviewReport, force: bool = False) -> Path:
        spec_reports = self._reports.setdefault(report.spec_id, {})
        if report.round in spec_reports and not force:
            raise FileExistsError("dup")
        spec_reports[report.round] = report.model_copy(deep=True)
        return self._root / "review" / report.spec_id / f"r{report.round}.yaml"

    def update_report(self, report: ReviewReport) -> Path:
        spec_reports = self._reports.setdefault(report.spec_id, {})
        spec_reports[report.round] = report.model_copy(deep=True)
        return self._root / "review" / report.spec_id / f"r{report.round}.yaml"

    def read_report(self, spec_id: str, round: int) -> Optional[ReviewReport]:
        r = self._reports.get(spec_id, {}).get(round)
        return r.model_copy(deep=True) if r else None

    def latest_report(self, spec_id: str) -> Optional[ReviewReport]:
        spec_reports = self._reports.get(spec_id)
        if not spec_reports:
            return None
        lr = max(spec_reports.keys())
        return spec_reports[lr].model_copy(deep=True)

    def list_reports(self, spec_id: str) -> list[ReviewReport]:
        spec_reports = self._reports.get(spec_id)
        if not spec_reports:
            return []
        return [spec_reports[r].model_copy(deep=True) for r in sorted(spec_reports.keys())]

    def write_fix(self, fix: FixRecord, spec_id: str) -> Path:
        """内存 write_fix：spec_id 由调用方直接传入（避免跨 spec 错配）"""
        existing = self._fixes.get(spec_id, [])
        next_num = (max(int(fix.id[1:]) for fix in existing if fix.id and fix.id.startswith("f")) + 1) if existing else 1
        fix.id = f"f{next_num}"
        self._fixes.setdefault(spec_id, []).append(fix.model_copy(deep=True))
        return self._root / "review" / spec_id / f"f{next_num}.yaml"

    def list_fixes(self, spec_id: str) -> list[FixRecord]:
        return [fix.model_copy(deep=True) for fix in self._fixes.get(spec_id, [])]

    def list_spec_ids(self) -> list[str]:
        return sorted(self._reports.keys())