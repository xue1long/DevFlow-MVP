"""FSBackend — 文件系统存储后端

改进：
- 原子写：临时文件 → rename，避免写入中断导致全损（P0-1）
- 文件锁：进程级 .lock 文件，防止并发写覆盖（P0-2）
- 哈希链：每条账本条目包含前一条的 SHA256，检测篡改（P0-3）
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml

from ..model.ledger import LedgerEntry, LedgerAction
from .base import StorageBackend


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
        """检查进程是否存活"""
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

        计算与验证必须一致：排除 _hash/_prev_hash 自身字段，
        否则验证时条目已带上这两个字段会导致哈希永远不匹配。
        """
        h = hashlib.sha256()
        # 排除链式字段本身，保证写时与验时序列化内容一致
        content = {k: v for k, v in entry.items() if k not in ("_hash", "_prev_hash")}
        entry_json = json.dumps(content, sort_keys=True, ensure_ascii=False)
        h.update(entry_json.encode("utf-8"))
        if prev_hash:
            h.update(prev_hash.encode("utf-8"))
        return h.hexdigest()

    def _verify_chain(self, entries: list[dict]) -> list[str]:
        """验证哈希链完整性，返回验证失败的条目索引"""
        failed = []
        prev_hash = None
        for i, entry in enumerate(entries):
            stored_hash = entry.get("_hash")
            if stored_hash is None:
                failed.append(i)
                continue
            computed = self._compute_entry_hash(entry, prev_hash)
            if stored_hash != computed:
                failed.append(i)
            prev_hash = stored_hash
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
            failed = self._verify_chain(entries)
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
        path.write_text(content, encoding="utf-8")
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
        latest = max(handoffs, key=_phase)
        return _phase(latest), latest.read_text(encoding="utf-8")

    # --- v0.3 增强：软归档 + 逻辑查询（第一性方案：不动文件，只在账本标记）---

    def archive_spec(self, spec_id: str, reason: str,
                     final_stage: Optional[int] = None) -> dict:
        """软归档 Spec：文件保留原位，仅在 ledger.yaml 添加 archive 段标记

        设计原则：
        - 不移动任何文件（零破坏）
        - 不破坏账本哈希链（archive 段独立，不影响 entries 链）
        - 记录归档时所有相关文件位置（便于查询）
        """
        from datetime import datetime
        def _do():
            ledger = self._read_yaml(self.ledger_path) or {}
            archive = ledger.setdefault("archive", {})

            # 记录相关文件路径（用于查询时定位）
            files_at = {
                "spec": str(self.specs_dir / f"{spec_id}.yaml"),
            }
            plan_id = ledger.get("current_plan_id")
            if plan_id:
                files_at["plan"] = str(self.plans_dir / f"{plan_id}.yaml")
            review_dir = self.root / "review" / spec_id
            if review_dir.exists():
                files_at["reviews"] = str(review_dir)

            record = {
                "archived_at": datetime.now().isoformat(),
                "final_stage": final_stage if final_stage is not None else ledger.get("current_phase", 0),
                "reason": reason,
                "files_at": files_at,
            }
            archive[spec_id] = record
            self._atomic_write_yaml(self.ledger_path, ledger)
            return record
        return self._with_lock(_do)

    def list_archived_specs(self) -> list[dict]:
        """列出所有已归档的 Spec（含元数据）"""
        def _do():
            ledger = self._read_yaml(self.ledger_path) or {}
            archive = ledger.get("archive", {})
            return [
                {"spec_id": sid, **meta}
                for sid, meta in archive.items()
            ]
        return self._with_lock(_do)

    def list_active_specs(self) -> list[str]:
        """列出活跃（未归档）的 Spec ID"""
        def _do():
            ledger = self._read_yaml(self.ledger_path) or {}
            archive = ledger.get("archive", {})
            all_specs = [p.stem for p in self.specs_dir.glob("*.yaml")] if self.specs_dir.exists() else []
            return [s for s in all_specs if s not in archive]
        return self._with_lock(_do)

    def query(self, keyword: str = "",
              include_archived: bool = False) -> list[dict]:
        """跨 Spec/Plan/Review 搜索关键词

        返回匹配的 Spec 列表，每项含 spec_id、status(archived/active)、match_locations。
        空 keyword 时返回所有 Spec（按 archive 过滤）。
        """
        def _do():
            ledger = self._read_yaml(self.ledger_path) or {}
            archive = ledger.get("archive", {})
            keyword_lower = keyword.lower() if keyword else ""

            results = []
            for spec_path in self.specs_dir.glob("*.yaml") if self.specs_dir.exists() else []:
                spec_id = spec_path.stem
                is_archived = spec_id in archive
                if is_archived and not include_archived:
                    continue

                matches = []
                # 搜索 Spec 文件
                try:
                    spec_text = spec_path.read_text(encoding="utf-8").lower()
                    if not keyword or keyword_lower in spec_text:
                        matches.append("spec")
                except OSError:
                    pass

                # 搜索 Spec 自己的 Plan 文件（仅当 plan_id 命名约定为 plan-{spec_id} 时）
                plan_path = self.plans_dir / f"plan-{spec_id}.yaml"
                if plan_path.exists():
                    try:
                        plan_text = plan_path.read_text(encoding="utf-8").lower()
                        if not keyword or keyword_lower in plan_text:
                            matches.append("plan:plan-" + spec_id + ".yaml")
                    except OSError:
                        pass

                # 搜索 Review 文件（Spec 自己的 review 目录）
                review_dir = self.root / "review" / spec_id
                if review_dir.exists():
                    for r_file in review_dir.glob("*.yaml"):
                        try:
                            r_text = r_file.read_text(encoding="utf-8").lower()
                            if not keyword or keyword_lower in r_text:
                                matches.append(f"review:{r_file.name}")
                        except OSError:
                            pass

                # keyword 为空则只要存在就匹配；有 keyword 则必须至少一处匹配
                if not keyword or matches:
                    results.append({
                        "spec_id": spec_id,
                        "status": "archived" if is_archived else "active",
                        "match_locations": matches,
                        "archived_at": archive.get(spec_id, {}).get("archived_at"),
                    })

            return results
        return self._with_lock(_do)

    # --- 内部方法 ---

    def _read_yaml(self, path: Path) -> Optional[dict]:
        if not path.exists():
            return None
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)