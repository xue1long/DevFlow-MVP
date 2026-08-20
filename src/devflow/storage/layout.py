"""layout.py — 路径策略层（v0.3.4 架构抽离）

单一出口：所有运行时路径从 sop.yaml 的 ``storage:`` 配置节读取，
改路径只需改配置，不翻引擎代码。

用法：
    layout = resolve_layout(root, config.storage)
    layout.specs_dir       # → Path("docs/devflow/specs")
    layout.review_dir      # → Path("docs/devflow/review")
    layout.ledger_path     # → Path("docs/devflow/progress.yaml")
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional


class LayoutPaths:
    """DevFlow 运行时产物路径集合（全部相对 root）

    所有字段在构造时被计算为绝对路径（root / 相对路径）。
    """

    def __init__(self, root: Path) -> None:
        self._root = root

        # 用户可配置字段（来自 sop.yaml storage: 节）
        self.specs_dir: Path = root / "docs" / "devflow" / "specs"
        self.plans_dir: Path = root / "docs" / "devflow" / "plans"
        self.review_dir: Path = root / "docs" / "devflow" / "review"
        self.ledger_basename: str = "progress.yaml"
        self.glossary_basename: str = "CONTEXT.md"

    @property
    def ledger_path(self) -> Path:
        return self._root / self.ledger_basename

    @property
    def lock_path(self) -> Path:
        return self._root / (self.ledger_basename + ".lock")

    @property
    def glossary_path(self) -> Path:
        return self._root / self.glossary_basename

    def handoff_path(self, phase: int) -> Path:
        return self._root / f"handoff-{phase}.md"

    def handoff_glob(self) -> str:
        return "handoff-*.md"

    def spec_path(self, spec_id: str) -> Path:
        return self.specs_dir / f"{spec_id}.yaml"

    def plan_path(self, plan_id: str) -> Path:
        return self.plans_dir / f"{plan_id}.yaml"

    def review_report_path(self, spec_id: str, round: int) -> Path:
        return self.review_dir / spec_id / f"r{round}.yaml"

    def review_fix_path(self, spec_id: str, fix_num: int) -> Path:
        return self.review_dir / spec_id / f"f{fix_num}.yaml"

    def review_spec_dir(self, spec_id: str) -> Path:
        return self.review_dir / spec_id

    def artifact_refs(self, spec_id: str, plan_id: Optional[str] = None) -> list[str]:
        """返回 handoff frontmatter 用的 artifact 路径引用（相对 root）"""
        refs = [
            f"{self.specs_dir.relative_to(self._root).as_posix()}/{spec_id}.yaml",
        ]
        if plan_id:
            refs.append(
                f"{self.plans_dir.relative_to(self._root).as_posix()}/{plan_id}.yaml"
            )
        refs.append(self.ledger_path.relative_to(self._root).as_posix())
        return refs

    def init_dirs(self) -> list[Path]:
        """需要 ``init_workspace`` 时 mkdir 的目录列表"""
        return [self.specs_dir, self.plans_dir, self.review_dir]

    def init_file_list(self) -> list[str]:
        """``devflow init`` 输出的文件清单（相对 root）"""
        return [
            self.specs_dir.relative_to(self._root).as_posix() + "/",
            self.plans_dir.relative_to(self._root).as_posix() + "/",
            self.review_dir.relative_to(self._root).as_posix() + "/",
            self.ledger_path.relative_to(self._root).as_posix(),
            self.glossary_path.relative_to(self._root).as_posix(),
        ]


def resolve_layout(root: Path, storage_config: Optional[dict] = None) -> LayoutPaths:
    """从 sop.yaml 的 ``storage:`` 配置节解析路径策略

    Args:
        root: 项目根目录（绝对路径）
        storage_config: sop.yaml 的 ``storage:`` 节内容（dict），
                        为 None 或空 dict 时用默认值

    Returns:
        LayoutPaths 实例
    """
    layout = LayoutPaths(root)

    if storage_config is None:
        return layout  # 全默认

    # 覆盖用户配置的字段
    if "specs_dir" in storage_config:
        layout.specs_dir = root / storage_config["specs_dir"]
    if "plans_dir" in storage_config:
        layout.plans_dir = root / storage_config["plans_dir"]
    if "review_dir" in storage_config:
        layout.review_dir = root / storage_config["review_dir"]
    if "ledger" in storage_config:
        layout.ledger_basename = storage_config["ledger"]
    if "glossary" in storage_config:
        layout.glossary_basename = storage_config["glossary"]

    return layout


__all__ = ["LayoutPaths", "resolve_layout"]