"""StorageBackend — 存储后端抽象接口

引擎层只依赖此接口，不直接依赖 FSBackend。

v0.3 增强（第一性方案）：
- archive_index(): 软归档（不移动文件，在账本标记状态）
- query(): 逻辑查询（返回 spec 索引映射）
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

from ..model.ledger import LedgerEntry


class StorageBackend(ABC):
    """存储后端抽象接口"""

    @abstractmethod
    def init_workspace(self, sop_content: str) -> None:
        """创建初始目录和文件"""

    # --- Spec 操作 ---
    @abstractmethod
    def write_spec(self, spec_id: str, data: dict) -> Path: ...
    @abstractmethod
    def read_spec(self, spec_id: str) -> Optional[dict]: ...
    @abstractmethod
    def list_specs(self) -> list[str]: ...

    # --- Plan 操作 ---
    @abstractmethod
    def write_plan(self, plan_id: str, data: dict) -> Path: ...
    @abstractmethod
    def read_plan(self, plan_id: str) -> Optional[dict]: ...

    # --- 账本操作 ---
    @abstractmethod
    def append_ledger(self, entry: LedgerEntry) -> None: ...
    @abstractmethod
    def get_ledger(self) -> dict: ...
    @abstractmethod
    def get_current_phase(self) -> int: ...
    @abstractmethod
    def set_current_phase(self, phase: int) -> None: ...
    @abstractmethod
    def get_current_spec_id(self) -> Optional[str]: ...
    @abstractmethod
    def set_current_spec_id(self, spec_id: Optional[str]) -> None: ...
    @abstractmethod
    def get_current_plan_id(self) -> Optional[str]: ...
    @abstractmethod
    def set_current_plan_id(self, plan_id: Optional[str]) -> None: ...
    @abstractmethod
    def is_suspended(self) -> bool: ...
    @abstractmethod
    def set_suspended(self, suspended: bool) -> None: ...
    @abstractmethod
    def has_phase_entry(self, phase: int) -> bool: ...

    # --- Handoff ---
    @abstractmethod
    def write_handoff(self, phase: int, content: str) -> Path: ...
    @abstractmethod
    def read_handoff(self, phase: int) -> Optional[str]: ...
    @abstractmethod
    def find_latest_handoff(self) -> Optional[tuple[int, str]]: ...

    # --- v0.3 增强：软归档 + 逻辑查询 ---

    @abstractmethod
    def archive_spec(self, spec_id: str, reason: str,
                     final_stage: Optional[int] = None) -> dict:
        """软归档一个 Spec（不移动文件）

        在 ledger.yaml 的 `archive` 段记录归档状态与文件路径，
        文件本身保持在原位。返回归档记录。
        """

    @abstractmethod
    def list_archived_specs(self) -> list[dict]:
        """列出所有已归档的 Spec（含归档元数据）"""

    @abstractmethod
    def list_active_specs(self) -> list[str]:
        """列出活跃（未归档）的 Spec ID"""

    @abstractmethod
    def query(self, keyword: str = "",
              include_archived: bool = False) -> list[dict]:
        """跨 Spec/Plan/Review 搜索关键词

        返回匹配的 Spec 列表，每项含 spec_id、match_locations、status
        """

    # --- 项目根目录 ---
    @property
    @abstractmethod
    def root(self) -> Path: ...
