"""review_store_base.py — 评审报告/修复记录存储抽象接口"""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

from ..model.review import ReviewReport, FixRecord


class ReviewStorageBackend(ABC):
    @abstractmethod
    def write_report(self, report: ReviewReport, force: bool = False) -> Path: ...

    @abstractmethod
    def update_report(self, report: ReviewReport) -> Path: ...

    @abstractmethod
    def read_report(self, spec_id: str, round: int) -> Optional[ReviewReport]: ...

    @abstractmethod
    def latest_report(self, spec_id: str) -> Optional[ReviewReport]: ...

    @abstractmethod
    def list_reports(self, spec_id: str) -> list[ReviewReport]: ...

    @abstractmethod
    def write_fix(self, fix: FixRecord, spec_id: str) -> Path:
        """写入修复记录

        Args:
            fix: 修复记录
            spec_id: 修复记录所属的 Spec ID（由调用方直接传入，避免跨 spec 错配）

        注：spec_id 由调用方提供而非从 review_id 反查，因为不同 spec 的报告 id
        可能冲突（反查会错配到首个匹配项）。
        """

    @abstractmethod
    def list_fixes(self, spec_id: str) -> list[FixRecord]: ...

    @abstractmethod
    def list_spec_ids(self) -> list[str]: ...