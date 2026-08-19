"""review_store.py — 评审报告/修复记录存储

review/<spec-id>/ 目录下的文件管理。
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml

from ..model.review import ReviewReport, FixRecord


class ReviewStore:
    """评审存储

    目录结构：
    review/<spec-id>/r<N>.yaml   — 评审报告
    review/<spec-id>/f<N>.yaml   — 修复记录
    """

    def __init__(self, root: Path):
        self.root = root
        self.review_dir = root / "review"

    # --- 评审报告 ---

    def write_report(self, report: ReviewReport) -> Path:
        """写入评审报告"""
        spec_dir = self.review_dir / report.spec_id
        spec_dir.mkdir(parents=True, exist_ok=True)
        path = spec_dir / f"r{report.round}.yaml"
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
            key=lambda p: int(p.stem[1:]),
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
            key=lambda p: int(p.stem[1:]),
        )
        return [ReviewReport(**self._read_yaml(p)) for p in reports]

    # --- 修复记录 ---

    def write_fix(self, fix: FixRecord) -> Path:
        """写入修复记录"""
        spec_id = self._spec_id_from_fix(fix)
        spec_dir = self.review_dir / spec_id
        spec_dir.mkdir(parents=True, exist_ok=True)

        existing = sorted(
            spec_dir.glob("f*.yaml"),
            key=lambda p: int(p.stem[1:]),
        )
        next_num = (int(existing[-1].stem[1:]) + 1) if existing else 1
        fix.id = f"f{next_num}"
        path = spec_dir / f"f{next_num}.yaml"
        self._write_yaml(path, fix.model_dump(mode="json"))
        return path

    def _spec_id_from_fix(self, fix: FixRecord) -> str:
        """根据 review_id 找到对应的 spec_id"""
        if not self.review_dir.exists():
            return "unknown"
        for spec_dir in self.review_dir.iterdir():
            if not spec_dir.is_dir():
                continue
            for p in spec_dir.glob("r*.yaml"):
                data = self._read_yaml(p)
                if data and data.get("id") == fix.review_id:
                    return spec_dir.name
        return "unknown"

    def list_fixes(self, spec_id: str) -> list[FixRecord]:
        """列出某个 Spec 的全部修复记录"""
        spec_dir = self.review_dir / spec_id
        if not spec_dir.exists():
            return []
        fixes = sorted(
            spec_dir.glob("f*.yaml"),
            key=lambda p: int(p.stem[1:]),
        )
        return [FixRecord(**self._read_yaml(p)) for p in fixes]

    def list_spec_ids(self) -> list[str]:
        """列出所有有评审记录的 Spec ID"""
        if not self.review_dir.exists():
            return []
        return sorted(d.name for d in self.review_dir.iterdir() if d.is_dir())

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