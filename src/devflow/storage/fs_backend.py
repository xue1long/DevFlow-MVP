"""FSBackend — 文件系统存储后端

MVP 采用 append-only 日志写入 progress.yaml，不做 CCR 内容寻址哈希。
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml

from ..model.ledger import LedgerEntry, LedgerAction
from .base import StorageBackend


class FSBackend(StorageBackend):
    """文件系统存储后端

    职责：
    - 读写 Spec/Plan YAML 文件
    - append-only 写入 progress.yaml 账本
    - 管理 current_spec_id / current_plan_id 状态

    不负责：Git 操作（由 GitPort 处理）
    """

    def __init__(self, root: Path):
        self._root = root
        self.specs_dir = root / "specs"
        self.plans_dir = root / "plans"
        self.ledger_path = root / "progress.yaml"
        self.glossary_path = root / "CONTEXT.md"

    @property
    def root(self) -> Path:
        return self._root

    # --- 初始化 ---

    def init_workspace(self, sop_content: str) -> None:
        """创建初始目录和文件"""
        self.specs_dir.mkdir(parents=True, exist_ok=True)
        self.plans_dir.mkdir(parents=True, exist_ok=True)

        # sop.yaml
        sop_path = self.root / "sop.yaml"
        if not sop_path.exists():
            sop_path.write_text(sop_content, encoding="utf-8")

        # progress.yaml（空账本）
        if not self.ledger_path.exists():
            self._write_yaml(self.ledger_path, {
                "current_spec_id": None,
                "current_plan_id": None,
                "current_phase": 0,
                "suspended": False,
                "entries": [],
            })

        # CONTEXT.md
        if not self.glossary_path.exists():
            self.glossary_path.write_text(
                "# CONTEXT.md — DevFlow 领域术语表\n\n"
                "> MVP 骨架，后续由 brainstorm/domain-modeling 阶段填充。\n",
                encoding="utf-8",
            )

    # --- Spec 操作 ---

    def write_spec(self, spec_id: str, data: dict) -> Path:
        """写入 Spec YAML"""
        path = self.specs_dir / f"{spec_id}.yaml"
        self._write_yaml(path, data)
        return path

    def read_spec(self, spec_id: str) -> Optional[dict]:
        """读取 Spec YAML"""
        path = self.specs_dir / f"{spec_id}.yaml"
        if not path.exists():
            return None
        return self._read_yaml(path)

    def list_specs(self) -> list[str]:
        """列出所有 Spec ID"""
        if not self.specs_dir.exists():
            return []
        return [
            p.stem for p in sorted(self.specs_dir.glob("*.yaml"))
        ]

    # --- Plan 操作 ---

    def write_plan(self, plan_id: str, data: dict) -> Path:
        """写入 Plan YAML"""
        path = self.plans_dir / f"{plan_id}.yaml"
        self._write_yaml(path, data)
        return path

    def read_plan(self, plan_id: str) -> Optional[dict]:
        """读取 Plan YAML"""
        path = self.plans_dir / f"{plan_id}.yaml"
        if not path.exists():
            return None
        return self._read_yaml(path)

    # --- 账本操作 ---

    def append_ledger(self, entry: LedgerEntry) -> None:
        """追加一条账本条目（append-only）"""
        ledger = self._read_yaml(self.ledger_path) or {
            "current_spec_id": None,
            "current_plan_id": None,
            "current_phase": 0,
            "suspended": False,
            "entries": [],
        }
        ledger["entries"].append(entry.model_dump(mode="json"))
        self._write_yaml(self.ledger_path, ledger)

    def get_ledger(self) -> dict:
        """读取完整账本"""
        return self._read_yaml(self.ledger_path) or {
            "current_spec_id": None,
            "current_plan_id": None,
            "current_phase": 0,
            "suspended": False,
            "entries": [],
        }

    def get_current_phase(self) -> int:
        ledger = self.get_ledger()
        return ledger.get("current_phase", 0)

    def set_current_phase(self, phase: int) -> None:
        ledger = self.get_ledger()
        ledger["current_phase"] = phase
        self._write_yaml(self.ledger_path, ledger)

    def get_current_spec_id(self) -> Optional[str]:
        ledger = self.get_ledger()
        return ledger.get("current_spec_id")

    def set_current_spec_id(self, spec_id: Optional[str]) -> None:
        ledger = self.get_ledger()
        ledger["current_spec_id"] = spec_id
        self._write_yaml(self.ledger_path, ledger)

    def get_current_plan_id(self) -> Optional[str]:
        ledger = self.get_ledger()
        return ledger.get("current_plan_id")

    def set_current_plan_id(self, plan_id: Optional[str]) -> None:
        ledger = self.get_ledger()
        ledger["current_plan_id"] = plan_id
        self._write_yaml(self.ledger_path, ledger)

    def is_suspended(self) -> bool:
        ledger = self.get_ledger()
        return ledger.get("suspended", False)

    def set_suspended(self, suspended: bool) -> None:
        ledger = self.get_ledger()
        ledger["suspended"] = suspended
        self._write_yaml(self.ledger_path, ledger)

    def has_phase_entry(self, phase: int) -> bool:
        """检查账本中是否有指定阶段的记录"""
        ledger = self.get_ledger()
        return any(e.get("phase") == phase for e in ledger.get("entries", []))

    # --- Handoff ---

    def write_handoff(self, phase: int, content: str) -> Path:
        """写出 handoff 文件"""
        path = self.root / f"handoff-{phase}.md"
        path.write_text(content, encoding="utf-8")
        return path

    def read_handoff(self, phase: int) -> Optional[str]:
        """读取 handoff 文件"""
        path = self.root / f"handoff-{phase}.md"
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8")

    def find_latest_handoff(self) -> Optional[tuple[int, str]]:
        """查找最新的 handoff 文件"""
        handoffs = list(self.root.glob("handoff-*.md"))
        if not handoffs:
            return None
        # 按阶段号排序取最新
        def _phase(p: Path) -> int:
            try:
                return int(p.stem.split("-", 1)[1])
            except (ValueError, IndexError):
                return -1
        latest = max(handoffs, key=_phase)
        return _phase(latest), latest.read_text(encoding="utf-8")

    # --- 内部方法 ---

    def _write_yaml(self, path: Path, data: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    def _read_yaml(self, path: Path) -> Optional[dict]:
        if not path.exists():
            return None
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
