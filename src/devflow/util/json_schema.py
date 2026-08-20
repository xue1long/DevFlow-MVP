"""Python 类型 → JSON Schema 类型映射

v0.3 纪律（manifest 自动派生时使用）：
- 单一真相源 = cli.py（Type 注解）
- 不允许手写 manifest（C3 阶段强制）
- 覆盖 str / int / bool / float / Optional[T] / Path 等场景
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, get_args, get_origin


def python_type_to_json_schema(annotation: Any) -> str:
    """将 Python 类型注解转为 JSON Schema 类型字符串

    Args:
        annotation: Python 类型注解（如 str, int, Optional[str], Path 等）

    Returns:
        JSON Schema 类型字符串: "string" | "integer" | "boolean" | "number"

    Examples:
        >>> python_type_to_json_schema(str)
        'string'
        >>> python_type_to_json_schema(int)
        'integer'
        >>> python_type_to_json_schema(bool)
        'boolean'
        >>> python_type_to_json_schema(float)
        'number'
        >>> from typing import Optional
        >>> python_type_to_json_schema(Optional[str])
        'string'
        >>> python_type_to_json_schema(Path)
        'string'
    """
    origin = get_origin(annotation)
    if origin is not None:
        # list[T] / List[T] → "array"
        if origin is list:
            return "array"
        # dict[K, V] / Dict[K, V] → "object"
        if origin is dict:
            return "object"
        # Union / Optional[T] / None 默认：取第一个非 None 参数
        args = get_args(annotation)
        non_none = [a for a in args if a is not type(None)]
        if non_none:
            return python_type_to_json_schema(non_none[0])

    name = getattr(annotation, "__name__", "")
    if annotation in (str,) or name == "str":
        return "string"
    if annotation in (int,) or name == "int":
        return "integer"
    if annotation in (bool,) or name == "bool":
        return "boolean"
    if annotation in (float,) or name == "float":
        return "number"

    # 路径 / 自定义类 → string 降级
    return "string"