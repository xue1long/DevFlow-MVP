"""review_store.py — 评审报告/修复记录存储（filesystem 实现）

实现 :class:`ReviewStorageBackend` 接口。memory counterpart 见
``review_store_memory.py`` 的 :class:`MemoryReviewBackend`。

目录结构：
review/<spec-id>/r<N>.yaml   — 评审报告
review/<spec-id>/f<N>.yaml   — 修复记录

P1-14 不变量（不可篡改承诺）由 filesystem 上的 YAML 文件 + write_report
的 force=False 强制保证。Memory 版本不持久化，但 force 不变量仍然有效。
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml

from ..model.review import ReviewReport, FixRecord
from .review_store_base import ReviewStorageBackend
from .layout import LayoutPaths, resolve_layout


# 保留 ReviewStore 别名以兼容旧 import 路径（实际类已重命名为 FSReviewBackend）
class FSReviewBackend(ReviewStorageBackend):
    """文件系统版 ReviewStorageBackend：review/<spec-id>/{r|f}<N>.yaml

    用法：
        review = FSReviewBackend(tmp_path)
        review.write_report(ReviewReport(...))
        ...

    兼容老代码：
        from .storage.review_store import ReviewStore  # 别名 = FSReviewBackend
    """

    def __init__(self, root: Path, layout: Optional[LayoutPaths] = None):
        self.root = root
        # v0.3.4: 与 FSBackend 一致，默认布局 = LayoutPaths（docs/devflow/review）
        self._layout = layout or LayoutPaths(root)
        self.review_dir = self._layout.review_dir

    # --- 评审报告 ---

    def write_report(self, report: ReviewReport, force: bool = False) -> Path:
        """写入评审报告（P1-14: 默认禁止覆写已有报告）"""
        spec_dir = self.review_dir / report.spec_id
        spec_dir.mkdir(parents=True, exist_ok=True)
        path = spec_dir / f"r{report.round}.yaml"
        if path.exists() and not force:
            raise FileExistsError(
                f"评审报告 {path} 已存在。轮次 {report.round} 不可覆写，"
                f"历史评审记录不可篡改（如需维护状态用 fix 命令）"
            )
        self._write_yaml(path, report.model_dump(mode="json"))
        return path

    def update_report(self, report: ReviewReport) -> Path:
        """更新已有评审报告（仅允许维护 resolved/residual 状态，不改 verdict）"""
        path = self.review_dir / report.spec_id / f"r{report.round}.yaml"
        self._write_yaml(path, report.model_dump(mode="json"))
        return path

    def read_report(self, spec_id: str, round: int) -> Optional[ReviewReport]:
        """读取指定轮次的评审报告"""
        path = self.review_dir / spec_id / f"r{round}.yaml"
        if not path.exists():
            return None
        return ReviewReport(**self._read_yaml(path))

    def latest_report(self, spec_id: str) -> Optional[ReviewReport]:
        """读取最新轮次的评审报告"""
        spec_dir = self.review_dir / spec_id
        if not spec_dir.exists():
            return None
        reports = sorted(
            spec_dir.glob("r*.yaml"),
            key=self._stem_round_key,
        )
        if not reports:
            return None
        return ReviewReport(**self._read_yaml(reports[-1]))

    def list_reports(self, spec_id: str) -> list[ReviewReport]:
        """列出某个 Spec 的全部评审报告（按轮次正序）"""
        spec_dir = self.review_dir / spec_id
        if not spec_dir.exists():
            return []
        reports = sorted(
            spec_dir.glob("r*.yaml"),
            key=self._stem_round_key,
        )
        return [ReviewReport(**self._read_yaml(p)) for p in reports]

    # --- 修复记录 ---

    def write_fix(self, fix: FixRecord, spec_id: str) -> Path:
        """写入修复记录（spec_id 由调用方直接传入，避免跨 spec 错配）"""
        spec_dir = self.review_dir / spec_id
        spec_dir.mkdir(parents=True, exist_ok=True)

        existing = sorted(
            spec_dir.glob("f*.yaml"),
            key=self._stem_fix_key,
        )
        next_num = (existing[-1] + 1) if existing else 1
        fix.id = f"f{next_num}"
        path = spec_dir / f"f{next_num}.yaml"
        self._write_yaml(path, fix.model_dump(mode="json"))
        return path

    def list_fixes(self, spec_id: str) -> list[FixRecord]:
        """列出某个 Spec 的全部修复记录"""
        spec_dir = self.review_dir / spec_id
        if not spec_dir.exists():
            return []
        fixes = sorted(
            spec_dir.glob("f*.yaml"),
            key=self._stem_fix_key,
        )
        return [FixRecord(**self._read_yaml(p)) for p in fixes]

    def list_spec_ids(self) -> list[str]:
        """列出所有有评审记录的 Spec ID"""
        if not self.review_dir.exists():
            return []
        return sorted(d.name for d in self.review_dir.iterdir() if d.is_dir())

    # --- 内部方法 ---

    @staticmethod
    def _stem_round_key(p: Path) -> int:
        """从 'r<N>.yaml' 文件名提取轮次编号 N；非数字文件名排到末尾"""
        try:
            return int(p.stem[1:])
        except ValueError:
            return float("inf")  # type: ignore[return-value]

    @staticmethod
    def _stem_fix_key(p: Path) -> int:
        """从 'f<N>.yaml' 文件名提取修复编号 N；非数字文件名排到末尾"""
        try:
            return int(p.stem[1:])
        except ValueError:
            return float("inf")  # type: ignore[return-value]

    def _write_yaml(self, path: Path, data: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    def _read_yaml(self, path: Path) -> Optional[dict]:
        if not path.exists():
            return None
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)


# Backward-compat: 老 import `from .storage.review_store import ReviewStore`
# 仍然工作。Phase C 之前的所有 fixture 都这样写。
ReviewStore = FSReviewBackend
