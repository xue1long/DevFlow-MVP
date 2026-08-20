"""MemoryStorageBackend — 内存存储后端（仅供 fixture / 单元测试使用）

P0 / P1 / P2 整套 ledger 防篡改（原子写 + 文件锁 + SHA256 哈希链）
都建立在 FSBackend 的 filesystem 行为上。MemoryStorageBackend 的设计取舍：

1. **没有锁、没有原子写、没有 hash chain**：内存操作本身是原子的，加锁无意义。
2. **verify_ledger() 直接返回 ok=True**：没有可篡改的物理介质。fixture 阶段不测防篡改语义。
3. **write_spec / write_plan 返回的 Path 是 `root / <filename>`**——纯虚拟路径，不写入磁盘。Phase A 中 4 处
   `storage.specs_dir.glob` 在 fixture 不被调用（fixture 走 list_specs() 抽象接口），
   所以保持 `_root / "specs" / f"{spec_id}.yaml"` 这种 shape 以便将来 e2e 切换时不破坏调用方预期。
4. **hash chain 不变**：调用方拿到的 ledger 与 FSBackend 字节级不一致——这是设计的取舍。
   在 ledger snapshot 测试中（如 `test_acceptance.py::test_7_ledger_has_all_phases`）仍要求断言"entries 数量 + 内容"
   而不是"哈希链字节相同"。已有测试 验证了这种写法，所以兼容。
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from ..model.ledger import LedgerEntry
from .base import StorageBackend


class MemoryStorageBackend(StorageBackend):
    """内存存储后端 — 仅供 fixture 使用。

    生产代码必须使用 :class:`FSBackend`。详见模块 docstring 的"设计取舍"四则。
    """

    def __init__(self, root: Path | str = Path("/tmp/memory-storage")):
        # 显式接受 root 让 fixture 写得自然（tmp_path / Path("memory") 都行）
        self._root = Path(root)

        # --- 内存数据结构 ---
        self._specs: dict[str, dict] = {}
        self._plans: dict[str, dict] = {}
        self._ledger: dict = {
            "current_spec_id": None,
            "current_plan_id": None,
            "current_phase": 0,
            "suspended": False,
            "chain_head": None,
            "entries": [],
        }
        self._handoffs: dict[int, str] = {}
        self._sop_content: Optional[str] = None

    # --- 属性 ---

    @property
    def root(self) -> Path:
        return self._root

    # --- 初始化 ---

    def init_workspace(self, sop_content: str) -> None:
        """内存版 init_workspace：把 sop_content 暂存即可，无需创建目录或写文件"""
        self._sop_content = sop_content

    # --- Spec 操作 ---

    def write_spec(self, spec_id: str, data: dict) -> Path:
        self._specs[spec_id] = dict(data)  # 拷贝以防外部修改污染 fixture
        return self._virtual_spec_path(spec_id)

    def read_spec(self, spec_id: str) -> Optional[dict]:
        data = self._specs.get(spec_id)
        return dict(data) if data is not None else None

    def list_specs(self) -> list[str]:
        return sorted(self._specs.keys())

    # --- Plan 操作 ---

    def write_plan(self, plan_id: str, data: dict) -> Path:
        self._plans[plan_id] = dict(data)
        return self._virtual_plan_path(plan_id)

    def read_plan(self, plan_id: str) -> Optional[dict]:
        data = self._plans.get(plan_id)
        return dict(data) if data is not None else None

    # --- 账本操作 ---

    def append_ledger(self, entry: LedgerEntry) -> None:
        """内存 append：不计算 hash chain（见模块 docstring 第 4 则）。

        仍然把 entry 序列化为 dict、塞进 entries、推进 chain_head=None 链头，
        让 PhaseStateMachine 的 `test_7_ledger_has_all_phases` 断言
        （"entries 数量 ≥ N" / "phase==X 的 entry 存在"）能够通过。
        """
        entry_dict = entry.model_dump(mode="json")
        # 不维护 hash chain：保留 entry 序列，chain_head 字段保留为 None
        self._ledger["entries"].append(entry_dict)

    def get_ledger(self) -> dict:
        return dict(self._ledger)  # 浅拷贝即可：调用方只读

    def get_current_phase(self) -> int:
        return int(self._ledger.get("current_phase", 0))

    def set_current_phase(self, phase: int) -> None:
        self._ledger["current_phase"] = int(phase)

    def get_current_spec_id(self) -> Optional[str]:
        return self._ledger.get("current_spec_id")

    def set_current_spec_id(self, spec_id: Optional[str]) -> None:
        self._ledger["current_spec_id"] = spec_id

    def get_current_plan_id(self) -> Optional[str]:
        return self._ledger.get("current_plan_id")

    def set_current_plan_id(self, plan_id: Optional[str]) -> None:
        self._ledger["current_plan_id"] = plan_id

    def is_suspended(self) -> bool:
        return bool(self._ledger.get("suspended", False))

    def set_suspended(self, suspended: bool) -> None:
        self._ledger["suspended"] = bool(suspended)

    def has_phase_entry(self, phase: int) -> bool:
        return any(e.get("phase") == phase for e in self._ledger.get("entries", []))

    # --- Handoff ---

    def write_handoff(self, phase: int, content: str) -> Path:
        self._handoffs[int(phase)] = content
        return self._root / f"handoff-{int(phase)}.md"

    def read_handoff(self, phase: int) -> Optional[str]:
        return self._handoffs.get(int(phase))

    def find_latest_handoff(self) -> Optional[tuple[int, str]]:
        if not self._handoffs:
            return None
        latest_phase = max(self._handoffs.keys())
        return (latest_phase, self._handoffs[latest_phase])

    # --- 内存版独有的便捷方法（仅供测试用） ---

    def reset(self) -> None:
        """测试间清理：把内存状态重置回初始。fixture 可在 setup/teardown 中调用。"""
        self.__init__(self._root)

    # --- 内部辅助 ---

    def _virtual_spec_path(self, spec_id: str) -> Path:
        """FSBackend.write_spec 返回 `specs/<id>.yaml`。保持 shape 一致以备 e2e 切换。"""
        return self._root / "specs" / f"{spec_id}.yaml"

    def _virtual_plan_path(self, plan_id: str) -> Path:
        """FSBackend.write_plan 返回 `plans/<id>.yaml`。"""
        return self._root / "plans" / f"{plan_id}.yaml"

    # --- Concretion: verify_ledger 在 FSBackend 上存在但不在 ABC 上 ---

    def verify_ledger(self) -> dict:
        """内存后端没有可篡改的物理介质，直接返回 ok=True。

        防篡改语义（如 `tests/test_simple_archive.py::test_verify_ledger_detects_tampered_*`）
        应使用 :class:`FSBackend` 验证，不在内存后端运行。
        """
        entries = self._ledger.get("entries", [])
        return {
            "ok": True,
            "message": f"内存账本不可篡改（{len(entries)} 条条目；非生产介质）",
            "total_entries": len(entries),
        }
