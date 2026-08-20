"""tests/test_json_schema.py — C1 阶段验证

覆盖:
- 基本类型 (str / int / bool / float)
- Optional[T] → 取 T 的 schema
- Path / 自定义类 → string 降级
- 边界场景 (None / 复杂泛型)
- v0.3.4 #39: is_recognized_type（manifest warning 判定）
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional, Union

import pytest

from devflow.util.json_schema import (
    python_type_to_json_schema,
    is_recognized_type,
)


class TestBasicTypes:
    """基本 Python 类型映射"""

    def test_str(self):
        assert python_type_to_json_schema(str) == "string"

    def test_int(self):
        assert python_type_to_json_schema(int) == "integer"

    def test_bool(self):
        assert python_type_to_json_schema(bool) == "boolean"

    def test_float(self):
        assert python_type_to_json_schema(float) == "number"


class TestOptional:
    """Optional[T] 应解包为 T"""

    def test_optional_str(self):
        assert python_type_to_json_schema(Optional[str]) == "string"

    def test_optional_int(self):
        assert python_type_to_json_schema(Optional[int]) == "integer"

    def test_optional_bool(self):
        assert python_type_to_json_schema(Optional[bool]) == "boolean"


class TestPathAndCustom:
    """Path 和自定义类降级为 string"""

    def test_path(self):
        assert python_type_to_json_schema(Path) == "string"

    def test_unknown_class(self):
        class Custom:
            pass

        assert python_type_to_json_schema(Custom) == "string"


class TestEdgeCases:
    """边界场景"""

    def test_union_with_none(self):
        """Union[T, None] 应等同于 Optional[T]"""
        assert python_type_to_json_schema(Union[str, None]) == "string"

    def test_str_annotation_name(self):
        """带 __name__ 的字符串类应识别"""

        class str:
            pass

        # 自定义类名为 "str"，应被识别为 string（降级处理）
        result = python_type_to_json_schema(str)
        assert result == "string"


class TestIsRecognizedType:
    """v0.3.4 #39: manifest warning 判定 —— 只对真正未注册类型告警"""

    def test_primitives_recognized(self):
        for t in (str, int, bool, float):
            assert is_recognized_type(t) is True, f"{t} 应可识别"

    def test_optional_str_recognized(self):
        assert is_recognized_type(Optional[str]) is True

    def test_union_with_int_recognized(self):
        assert is_recognized_type(Union[int, None]) is True

    def test_path_recognized(self):
        assert is_recognized_type(Path) is True

    def test_list_recognized(self):
        assert is_recognized_type(list[str]) is True

    def test_dict_recognized(self):
        assert is_recognized_type(dict[str, int]) is True

    def test_custom_class_not_recognized(self):
        class Custom:
            pass

        assert is_recognized_type(Custom) is False

    def test_union_mixed_not_recognized(self):
        """Union[str, Custom] 含未注册类型 → 视为不可识别（应告警）"""

        class Custom:
            pass

        assert is_recognized_type(Union[str, Custom]) is False

    def test_manifest_build_no_warning(self):
        """构建 CLI manifest 不应触发类型降级 warning（回归 #39）"""
        import warnings

        from devflow.cli import app
        from devflow.adapters.manifest_builder import build_manifests_from_cli

        with warnings.catch_warnings():
            warnings.simplefilter("error", UserWarning)
            # 不应抛 UserWarning（OPtional[str] / Path 均已注册）
            manifests = build_manifests_from_cli(app)
        assert len(manifests) >= 20