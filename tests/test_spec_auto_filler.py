"""v0.4.3 SpecAutoFiller 单元测试"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from devflow.engine.spec_auto_filler import SpecAutoFiller
from devflow.model.spec import Spec, SpecStatus
from devflow.storage.memory_backend import MemoryStorageBackend


def _make_spec(
    spec_id="test-spec",
    goals=None,
    non_goals=None,
) -> Spec:
    return Spec(
        id=spec_id,
        title="t",
        problem="p" * 20,
        goals=goals if goals is not None else ["待补充"],
        non_goals=non_goals if non_goals is not None else ["ng"],
        status=SpecStatus.DRAFT,
    )


class TestFillGoals:
    def test_overwrites_placeholder(self):
        storage = MemoryStorageBackend()
        spec = _make_spec(goals=["待补充"])
        storage.write_spec(spec.id, spec.model_dump(mode="json"))
        filler = SpecAutoFiller(storage)
        new = ["goal 1", "goal 2"]
        result = filler.fill_goals_if_empty(spec.id, new)
        assert result is not None
        assert result.changed is True
        assert result.filled_goals == new
        # Spec 真的被改了
        assert storage.read_spec(spec.id)["goals"] == new

    def test_preserves_user_goals_by_default(self):
        storage = MemoryStorageBackend()
        spec = _make_spec(goals=["用户已填的目标"])
        storage.write_spec(spec.id, spec.model_dump(mode="json"))
        filler = SpecAutoFiller(storage)
        new = ["goal 1", "goal 2"]
        result = filler.fill_goals_if_empty(spec.id, new)
        assert result is not None
        assert result.changed is False  # 没改
        assert result.filled_goals == ["用户已填的目标"]
        # Spec 真的没被改
        assert storage.read_spec(spec.id)["goals"] == ["用户已填的目标"]

    def test_overwrite_when_config_true(self):
        storage = MemoryStorageBackend()
        spec = _make_spec(goals=["用户已填的目标"])
        storage.write_spec(spec.id, spec.model_dump(mode="json"))
        filler = SpecAutoFiller(storage)
        new = ["goal 1", "goal 2"]
        result = filler.fill_goals_if_empty(
            spec.id, new, overwrite=True
        )
        assert result.changed is True
        assert storage.read_spec(spec.id)["goals"] == new

    def test_missing_spec_returns_none(self):
        storage = MemoryStorageBackend()
        filler = SpecAutoFiller(storage)
        result = filler.fill_goals_if_empty("nonexistent", ["g"])
        assert result is None

    def test_empty_new_goals_returns_none(self):
        storage = MemoryStorageBackend()
        spec = _make_spec(goals=["待补充"])
        storage.write_spec(spec.id, spec.model_dump(mode="json"))
        filler = SpecAutoFiller(storage)
        result = filler.fill_goals_if_empty(spec.id, [])
        assert result is None

    def test_empty_spec_goals_treated_as_placeholder(self):
        """空 goals 列表视为占位 (RFC §5 _is_placeholder 逻辑)"""
        storage = MemoryStorageBackend()
        # 用 goals=["待补充"] 模拟"用户什么都没填"的占位状态
        # (Spec model 强制 goals >=1,所以不能传 [])
        spec = _make_spec(goals=["待补充"])
        storage.write_spec(spec.id, spec.model_dump(mode="json"))
        filler = SpecAutoFiller(storage)
        result = filler.fill_goals_if_empty(spec.id, ["new goal"])
        assert result.changed is True
        assert storage.read_spec(spec.id)["goals"] == ["new goal"]

    def test_placeholder_variants(self):
        """多种占位符都能被识别

        注: 空字符串 "" 不在测试范围 — Spec model 的 goals 字段 validator
        要求每项非空,所以 "" 不能作为合法 Spec.goals 传入(但
        SpecAutoFiller._is_placeholder 内置支持, 作为防御性兜底)
        """
        for placeholder in ["待补充", "TBD", "TODO", "to be filled"]:
            storage = MemoryStorageBackend()
            spec = _make_spec(goals=[placeholder])
            storage.write_spec(spec.id, spec.model_dump(mode="json"))
            filler = SpecAutoFiller(storage)
            result = filler.fill_goals_if_empty(spec.id, ["new"])
            assert result.changed is True, f"占位符 '{placeholder}' 未被识别"

    def test_user_goals_with_only_one_placeholder_mixed_preserved(self):
        """用户既有占位又有真内容 -> 保留(整体非占位)"""
        storage = MemoryStorageBackend()
        spec = _make_spec(goals=["真目标", "待补充"])
        storage.write_spec(spec.id, spec.model_dump(mode="json"))
        filler = SpecAutoFiller(storage)
        result = filler.fill_goals_if_empty(spec.id, ["new"])
        assert result.changed is False