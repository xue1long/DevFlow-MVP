"""sop.yaml 加载与版本协商

校验规则（见 MVP-门禁降级矩阵 §0.8）：
- sop_version 缺失 → warning（兼容旧配置）
- 引擎不支持的 sop_version → error 并退出
- 未知字段 → warning（向前兼容）
- 必需字段缺失 → error
"""
from __future__ import annotations

import warnings
from pathlib import Path
from typing import Any, Optional

import yaml
from pydantic import BaseModel, Field

# 引擎支持的 SOP 版本
SUPPORTED_SOP_VERSIONS = {"0.1"}


class GateConfig(BaseModel):
    """单个门禁配置"""
    command: Optional[str] = None
    kind: Optional[str] = None
    require: Optional[str] = None
    blocking: bool = True
    enabled: bool = True
    bind_to_stage: Optional[int] = None
    note: Optional[str] = None
    # 以下字段用于高级门禁，MVP 不启用但需兼容
    axes: Optional[list] = None
    smell_baseline: Optional[str] = None
    parallel_subagents: Optional[bool] = None
    schedule: Optional[Any] = None
    report: Optional[str] = None
    source: Optional[str] = None
    mode: Optional[str] = None


class RedLineConfig(BaseModel):
    """单条红线配置"""
    name: str
    mvp_skip: bool = False


class ThinkingConfig(BaseModel):
    """v0.3.3 思维模型配置

    宽松默认: 所有检查 severity=MINOR,提示不阻断。
    enabled=false 时完全跳过思维检查(兼容旧 SOP)。
    """
    enabled: bool = True
    severity: str = "minor"  # minor | off(off = 只记录不提示)


class SOPConfig(BaseModel):
    """sop.yaml 完整配置"""
    sop_version: Optional[str] = None
    phases: list[str] = Field(default_factory=lambda: [
        "intake", "brainstorm", "plan", "contract",
        "implement", "verify", "review", "finish"
    ])
    intake_fast_skip: bool = False
    red_lines: list[RedLineConfig] = Field(default_factory=list)
    pr_max_files: int = 30
    minimalism_strictness: str = "full"
    gates: dict[str, GateConfig] = Field(default_factory=dict)
    modules: dict[str, Any] = Field(default_factory=dict)
    tooling: dict[str, Any] = Field(default_factory=dict)
    adapters: dict[str, Any] = Field(default_factory=dict)
    storage: dict[str, Any] = Field(default_factory=dict)
    allow_fast_forward: bool = False
    thinking: ThinkingConfig = Field(default_factory=ThinkingConfig)

    def get_gate(self, name: str) -> Optional[GateConfig]:
        return self.gates.get(name)

    def get_enabled_gates_for_stage(self, stage: int) -> list[tuple[str, GateConfig]]:
        """返回绑定到指定阶段的所有 enabled 门禁（name, config）"""
        return [
            (name, g) for name, g in self.gates.items()
            if g.enabled and g.bind_to_stage == stage
        ]


def _parse_red_lines(raw: list) -> list[RedLineConfig]:
    """解析 red_lines 列表，处理 circular_dep 的嵌套格式"""
    result: list[RedLineConfig] = []
    for item in raw:
        if isinstance(item, str):
            result.append(RedLineConfig(name=item))
        elif isinstance(item, dict):
            for name, props in item.items():
                if isinstance(props, dict):
                    result.append(RedLineConfig(
                        name=name,
                        mvp_skip=props.get("mvp_skip", False),
                    ))
                else:
                    result.append(RedLineConfig(name=name))
    return result


def load_sop(path: Path) -> SOPConfig:
    """加载并校验 sop.yaml

    Raises:
        ValueError: sop_version 不兼容或必需字段缺失
    """
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    sop_raw = raw.get("sop", raw)

    # 版本协商
    version = sop_raw.get("sop_version")
    if version is None:
        warnings.warn("sop.yaml 缺少 sop_version 字段，按兼容模式加载")
    elif version not in SUPPORTED_SOP_VERSIONS:
        raise ValueError(
            f"sop.yaml 的 sop_version='{version}' 不被引擎支持。"
            f"支持的版本: {SUPPORTED_SOP_VERSIONS}"
        )

    # 解析 red_lines
    raw_red_lines = sop_raw.pop("red_lines", [])
    red_lines = _parse_red_lines(raw_red_lines)

    # 解析 gates
    raw_gates = sop_raw.pop("gates", {})
    gates = {}
    for name, gate_raw in raw_gates.items():
        if isinstance(gate_raw, dict):
            gates[name] = GateConfig(**gate_raw)
        else:
            gates[name] = GateConfig()

    # 构建配置（忽略未知字段——向前兼容）
    known_fields = set(SOPConfig.model_fields.keys())
    filtered = {k: v for k, v in sop_raw.items() if k in known_fields}
    unknown = set(sop_raw.keys()) - known_fields - {"gates", "red_lines"}
    if unknown:
        warnings.warn(f"sop.yaml 包含未知字段（已忽略）: {unknown}")

    config = SOPConfig(**filtered, gates=gates, red_lines=red_lines)
    return config
