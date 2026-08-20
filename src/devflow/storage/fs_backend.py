"""FSBackend — 文件系统存储后端

改进：
- 原子写：临时文件 → rename，避免写入中断导致全损（P0-1）
- 文件锁：进程级 .lock 文件，防止并发写覆盖（P0-2）
- 哈希链：每条账本条目包含前一条的 SHA256，检测篡改（P0-3）
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml

from ..model.ledger import LedgerEntry, LedgerAction
from .base import StorageBackend

logger = logging.getLogger(__name__)

# 参与哈希计算的字段白名单。
# 重要契约：
# 1. LedgerEntry 加字段时必须同步更新此集合，否则 _compute_entry_hash 会发 warning；
#    已签发账本不会自动适配，新字段只影响新条目。
# 2. 修改此集合后，必须同步更新 tests/test_simple_archive.py 中 test_verify_ledger_*
#    验证哈希计算行为一致。
# 3. 字段集必须与 src/devflow/model/ledger.py 的 LedgerEntry 模型字段完全对齐
#    （除了 append_ledger 动态添加的 _hash/_prev_hash）。
_HASH_FIELDS: frozenset = frozenset({
    "phase", "action", "timestamp", "details",
    "task_id", "commit", "acceptance", "reason", "gate_result",
})


class FSBackend(StorageBackend):
    """文件系统存储后端"""

    LOCK_TIMEOUT = 10  # 锁等待超时（秒）

    def __init__(self, root: Path):
        self._root = root
        self.specs_dir = root / "specs"
        self.plans_dir = root / "plans"
        self.ledger_path = root / "progress.yaml"
        self.glossary_path = root / "CONTEXT.md"
        self.lock_path = root / "progress.yaml.lock"

    @property
    def root(self) -> Path:
        return self._root

    # --- 文件锁 ---

    def _acquire_lock(self) -> bool:
        """获取进程级文件锁（阻塞等待，最多 LOCK_TIMEOUT 秒）"""
        deadline = time.monotonic() + self.LOCK_TIMEOUT
        while time.monotonic() < deadline:
            try:
                fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, str(os.getpid()).encode())
                os.close(fd)
                return True
            except FileExistsError:
                # 检查锁是否过期（进程崩溃未释放）
                try:
                    pid = int(self.lock_path.read_text().strip())
                    if not self._process_alive(pid):
                        self.lock_path.unlink(missing_ok=True)
                        continue
                except (ValueError, OSError):
                    pass
                time.sleep(0.1)
        return False

    def _release_lock(self) -> None:
        """释放文件锁"""
        self.lock_path.unlink(missing_ok=True)

    @staticmethod
    def _process_alive(pid: int) -> bool:
        """检查进程是否存活（跨平台）

        v0.3.4 #18: Windows 下 os.kill(pid, 0) 总是抛 PermissionError
        用 ctypes 调 OpenProcess 替代，确保 Windows 上锁不被绕过
        """
        if sys.platform == "win32":
            try:
                import ctypes
                from ctypes import wintypes
                PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
                STILL_ACTIVE = 259
                kernel32 = ctypes.windll.kernel32
                handle = kernel32.OpenProcess(
                    PROCESS_QUERY_LIMITED_INFORMATION, False, pid
                )
                if not handle:
                    return False
                exit_code = wintypes.DWORD()
                kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
                kernel32.CloseHandle(handle)
                return exit_code.value == STILL_ACTIVE
            except Exception:
                return False
        else:
            try:
                os.kill(pid, 0)
                return True
            except (OSError, PermissionError):
                return False

    # --- 原子写 ---

    def _atomic_write_yaml(self, path: Path, data: dict) -> None:
        """原子写入 YAML：先写临时文件，再 rename
        
        避免写入中断导致文件损坏或全损（P0-1）
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(
            suffix=".yaml",
            prefix=".tmp_",
            dir=path.parent,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
                f.flush()
                os.fsync(fd)
            os.replace(tmp_path, path)
            # v0.3.4 #33: POSIX 下 fsync 父目录，保证 rename 持久化
            # Windows 下 MoveFileEx 语义不同，不需要此步骤
            if os.name == "posix":
                try:
                    dir_fd = os.open(str(path.parent), os.O_RDONLY | os.O_DIRECTORY)
                    os.fsync(dir_fd)
                    os.close(dir_fd)
                except (OSError, AttributeError):
                    pass  # 不阻塞主流程
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    # --- 哈希链 ---

    @staticmethod
    def _compute_entry_hash(entry: dict, prev_hash: Optional[str]) -> str:
        """计算账本条目的哈希值（包含前一条的哈希）

        计算与验证必须一致：仅哈希白名单字段，避免 _hash/_prev_hash 自身干扰，
        且防止 LedgerEntry 加字段时静默破坏哈希链。
        """
        h = hashlib.sha256()
        # 白名单字段参与哈希
        content = {k: entry[k] for k in _HASH_FIELDS if k in entry}
        # 检测未注册字段（防止静默 schema 漂移）
        extra = set(entry) - _HASH_FIELDS - {"_hash", "_prev_hash"}
        if extra:
            logger.warning(
                "哈希计算中发现未注册字段: %s。"
                "若该字段是新增的 LedgerEntry 字段，请将其加入 _HASH_FIELDS 白名单，"
                "否则已有账本的哈希链验证将失败。",
                sorted(extra),
            )
        entry_json = json.dumps(content, sort_keys=True, ensure_ascii=False)
        h.update(entry_json.encode("utf-8"))
        if prev_hash:
            h.update(prev_hash.encode("utf-8"))
        return h.hexdigest()

    def _verify_chain(self, entries: list[dict], chain_head: Optional[str] = None) -> list[str]:
        """验证哈希链完整性，返回验证失败的条目索引

        安全契约：一旦某条目哈希不匹配，必须用 computed（正确哈希）作为
        下一条的 prev_hash，使后续条目必然验证失败，从而完整暴露篡改范围。
        若使用 stored_hash，被篡改条目之后的合法条目仍可能"看起来"合法。
        """
        failed = []
        prev_hash = None
        for i, entry in enumerate(entries):
            stored_hash = entry.get("_hash")
            if stored_hash is None:
                failed.append(i)
                # 缺失 hash 也破坏链：用 compute 时同样需要 prev_hash，但
                # 既然该条已标记失败，下一条用 None 让它重新从零开始也对。
                # 为保持"破坏链"语义，继续以 computed（若可计算）作为 prev。
                prev_hash = None
                continue
            computed = self._compute_entry_hash(entry, prev_hash)
            if stored_hash != computed:
                failed.append(i)
                # 关键：用 computed（正确）而非 stored_hash 作为下一条 prev，
                # 确保所有下游条目都因 prev 错误而验证失败。
                prev_hash = computed
            else:
                prev_hash = stored_hash
        # 额外校验：链头必须等于最后一条的 _hash，否则 ledger["chain_head"]
        # 字段自身被篡改（指向不存在/早期的条目）。
        if entries and chain_head is not None:
            last_hash = entries[-1].get("_hash")
            if last_hash != chain_head:
                # chain_head 不匹配：把最后一条也标记为失败
                last_idx = len(entries) - 1
                if last_idx not in failed:
                    failed.append(last_idx)
        return failed

    # --- 初始化 ---

    def init_workspace(self, sop_content: str) -> None:
        self.specs_dir.mkdir(parents=True, exist_ok=True)
        self.plans_dir.mkdir(parents=True, exist_ok=True)

        sop_path = self.root / "sop.yaml"
        if not sop_path.exists():
            sop_path.write_text(sop_content, encoding="utf-8")

        if not self.ledger_path.exists():
            self._atomic_write_yaml(self.ledger_path, {
                "current_spec_id": None,
                "current_plan_id": None,
                "current_phase": 0,
                "suspended": False,
                "chain_head": None,
                "entries": [],
            })

        if not self.glossary_path.exists():
            self.glossary_path.write_text(
                "# CONTEXT.md — DevFlow 领域术语表\n\n"
                "> MVP 骨架，后续由 brainstorm/domain-modeling 阶段填充。\n",
                encoding="utf-8",
            )

    # --- Spec 操作 ---

    def write_spec(self, spec_id: str, data: dict) -> Path:
        path = self.specs_dir / f"{spec_id}.yaml"
        self._atomic_write_yaml(path, data)
        return path

    def read_spec(self, spec_id: str) -> Optional[dict]:
        path = self.specs_dir / f"{spec_id}.yaml"
        if not path.exists():
            return None
        return self._read_yaml(path)

    def list_specs(self) -> list[str]:
        if not self.specs_dir.exists():
            return []
        return [p.stem for p in sorted(self.specs_dir.glob("*.yaml"))]

    # --- Plan 操作 ---

    def write_plan(self, plan_id: str, data: dict) -> Path:
        path = self.plans_dir / f"{plan_id}.yaml"
        self._atomic_write_yaml(path, data)
        return path

    def read_plan(self, plan_id: str) -> Optional[dict]:
        path = self.plans_dir / f"{plan_id}.yaml"
        if not path.exists():
            return None
        return self._read_yaml(path)

    # --- 账本操作（带锁 + 原子写 + 哈希链） ---

    def _with_lock(self, func):
        """带锁的账本操作包装器"""
        if not self._acquire_lock():
            raise RuntimeError(
                f"无法获取账本锁（{self.lock_path}），"
                f"可能另一个进程正在操作。等待超时 {self.LOCK_TIMEOUT} 秒"
            )
        try:
            return func()
        finally:
            self._release_lock()

    def append_ledger(self, entry: LedgerEntry) -> None:
        def _do_append():
            ledger = self._read_yaml(self.ledger_path) or {
                "current_spec_id": None, "current_plan_id": None,
                "current_phase": 0, "suspended": False,
                "chain_head": None, "entries": [],
            }
            entry_dict = entry.model_dump(mode="json")
            prev_hash = ledger.get("chain_head")
            entry_dict["_hash"] = self._compute_entry_hash(entry_dict, prev_hash)
            entry_dict["_prev_hash"] = prev_hash
            ledger["entries"].append(entry_dict)
            ledger["chain_head"] = entry_dict["_hash"]
            self._atomic_write_yaml(self.ledger_path, ledger)
        self._with_lock(_do_append)

    def get_ledger(self) -> dict:
        def _do_get():
            return self._read_yaml(self.ledger_path) or {
                "current_spec_id": None, "current_plan_id": None,
                "current_phase": 0, "suspended": False,
                "chain_head": None, "entries": [],
            }
        return self._with_lock(_do_get)

    def verify_ledger(self) -> dict:
        """验证账本哈希链完整性"""
        def _do_verify():
            ledger = self._read_yaml(self.ledger_path)
            if ledger is None:
                return {"ok": False, "message": "账本文件不存在"}
            entries = ledger.get("entries", [])
            if not entries:
                return {"ok": True, "message": "账本为空，无需验证"}
            failed = self._verify_chain(entries, ledger.get("chain_head"))
            if failed:
                return {
                    "ok": False,
                    "message": f"哈希链验证失败，{len(failed)} 条条目被篡改",
                    "failed_indices": failed,
                    "total_entries": len(entries),
                }
            return {"ok": True, "message": f"哈希链完整（{len(entries)} 条条目）"}
        return self._with_lock(_do_verify)

    def get_current_phase(self) -> int:
        def _do():
            ledger = self._read_yaml(self.ledger_path) or {}
            return ledger.get("current_phase", 0)
        return self._with_lock(_do)

    def set_current_phase(self, phase: int) -> None:
        def _do():
            ledger = self._read_yaml(self.ledger_path) or {}
            ledger["current_phase"] = phase
            self._atomic_write_yaml(self.ledger_path, ledger)
        self._with_lock(_do)

    def get_current_spec_id(self) -> Optional[str]:
        def _do():
            ledger = self._read_yaml(self.ledger_path) or {}
            return ledger.get("current_spec_id")
        return self._with_lock(_do)

    def set_current_spec_id(self, spec_id: Optional[str]) -> None:
        def _do():
            ledger = self._read_yaml(self.ledger_path) or {}
            ledger["current_spec_id"] = spec_id
            self._atomic_write_yaml(self.ledger_path, ledger)
        self._with_lock(_do)

    def get_current_plan_id(self) -> Optional[str]:
        def _do():
            ledger = self._read_yaml(self.ledger_path) or {}
            return ledger.get("current_plan_id")
        return self._with_lock(_do)

    def set_current_plan_id(self, plan_id: Optional[str]) -> None:
        def _do():
            ledger = self._read_yaml(self.ledger_path) or {}
            ledger["current_plan_id"] = plan_id
            self._atomic_write_yaml(self.ledger_path, ledger)
        self._with_lock(_do)

    def is_suspended(self) -> bool:
        def _do():
            ledger = self._read_yaml(self.ledger_path) or {}
            return ledger.get("suspended", False)
        return self._with_lock(_do)

    def set_suspended(self, suspended: bool) -> None:
        def _do():
            ledger = self._read_yaml(self.ledger_path) or {}
            ledger["suspended"] = suspended
            self._atomic_write_yaml(self.ledger_path, ledger)
        self._with_lock(_do)

    def has_phase_entry(self, phase: int) -> bool:
        def _do():
            ledger = self._read_yaml(self.ledger_path) or {}
            return any(e.get("phase") == phase for e in ledger.get("entries", []))
        return self._with_lock(_do)

    # --- Handoff ---

    def write_handoff(self, phase: int, content: str) -> Path:
        path = self.root / f"handoff-{phase}.md"
        # 原子写：避免崩溃产生损坏的半写文件（与 P0-1 一致）
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(
            suffix=".md",
            prefix=".tmp_handoff_",
            dir=path.parent,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
                f.flush()
                os.fsync(fd)
            os.replace(tmp_path, path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
        return path

    def read_handoff(self, phase: int) -> Optional[str]:
        path = self.root / f"handoff-{phase}.md"
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8")

    def find_latest_handoff(self) -> Optional[tuple[int, str]]:
        handoffs = list(self.root.glob("handoff-*.md"))
        if not handoffs:
            return None
        def _phase(p: Path) -> int:
            try:
                return int(p.stem.split("-", 1)[1])
            except (ValueError, IndexError):
                return -1
        # 过滤掉 phase 解析失败（-1）的文件，避免畸形文件名被错误地选为 latest
        valid = [p for p in handoffs if _phase(p) >= 0]
        if not valid:
            return None
        latest = max(valid, key=_phase)
        return _phase(latest), latest.read_text(encoding="utf-8")

    # --- 内部方法 ---

    def _read_yaml(self, path: Path) -> Optional[dict]:
        if not path.exists():
            return None
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)