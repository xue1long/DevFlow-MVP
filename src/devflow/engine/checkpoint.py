"""Checkpoint — 挂起/续接

MVP 中 Checkpoint 的功能已集成到 PhaseStateMachine 的 suspend/resume 方法中。
此模块保留接口兼容性。
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from ..storage.base import StorageBackend


class Checkpoint:
    """挂起/续接管理器"""

    def __init__(self, storage: StorageBackend):
        self.storage = storage

    def create_checkpoint(self, phase: int, note: str = "") -> dict:
        """创建检查点（等同 suspend）"""
        return {"phase": phase, "note": note}

    def restore_checkpoint(self) -> Optional[dict]:
        """恢复检查点（等同 resume）"""
        handoff = self.storage.find_latest_handoff()
        if handoff is None:
            return None
        phase, content = handoff
        return {"phase": phase, "content": content}
