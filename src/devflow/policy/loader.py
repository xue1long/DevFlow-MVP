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


class ModelTiersConfig(BaseModel):
    """v0.3 B6 阶段：SDD 子代理编排的模型分档配置

    借鉴 obra SDD（架构文档 §5.2.1 #7）：
    - 机械任务用最廉价模型
    - 集成 / 判断用标准
    - 架构用最强
    - 修复轮次 4–5 升级模型

    默认值：implementer=sonnet / reviewer=haiku / escalator=opus
    """
    implementer: str = "sonnet"
    reviewer: str = "haiku"
    escalator: str = "opus"


class SDConfig(BaseModel):
    """v0.3 B6 阶段：SDD 子代理编排配置

    从 sop.yaml `sd:` 节读取。
    """
    model_tiers: ModelTiersConfig = Field(default_factory=ModelTiersConfig)
    max_rounds: int = Field(default=5, ge=1, le=20)
    parallel: bool = Field(default=False)
    worktree_per_task: bool = Field(default=False)


class ResearchConfig(BaseModel):
    """v0.4 RFC §6.1: 引文式调研 SOP 配置

    从 sop.yaml `research:` 节读取。所有字段有默认值,保证向后兼容
    (旧 sop.yaml 无 research 段时按默认配置运行)。

    字段语义:
    - enabled: 总开关;false 时所有 research 路径直接跳过
    - auto_run_on: 在哪些阶段自动跑调研;MVP 仅 plan_stage
    - sources: 允许的数据源列表,按优先级排序
    - max_results_per_source: 单源最大返回数(防噪声)
    - max_total_chars: 报告最大字符数(防撑爆 Spec)
    - timeout_per_source: 单源超时(秒)
    - fallback: 全 backend 失败时行为;skip=不阻断流程,error=抛异常
    - citation_required: 是否强制要求带 URL + 时间戳
    - start_keywords: start 阶段 advisory 触发词(防重复造轮子)
    """
    enabled: bool = True
    auto_run_on: list[str] = Field(default_factory=lambda: ["plan_stage"])
    sources: list[str] = Field(
        default_factory=lambda: ["github", "pypi", "npm", "web"]
    )
    max_results_per_source: int = Field(default=5, ge=1, le=20)
    max_total_chars: int = Field(default=8000, ge=100, le=50000)
    timeout_per_source: int = Field(default=10, ge=1, le=60)
    fallback: str = Field(default="skip")  # skip | error
    citation_required: bool = True
    start_keywords: list[str] = Field(
        default_factory=lambda: [
            "from scratch", "重新实现", "重写", "造轮子", "自己写一个",
        ]
    )


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
    # v0.3 B6 阶段：SDD 子代理编排配置
    sd: SDConfig = Field(default_factory=SDConfig)
    # v0.4 新增: 引文式调研配置
    research: ResearchConfig = Field(default_factory=ResearchConfig)

    def get_gate(self, name: str) -> Optional[GateConfig]:
        return self.gates.get(name)

    def get_enabled_gates_for_stage(self, stage: int) -> list[tuple[str, GateConfig]]:
        """返回绑定到指定阶段的所有 enabled 门禁（name, config）"""
        return [
            (name, g) for name, g in self.gates.items()
            if g.enabled and g.bind_to_stage == stage
        ]

    def is_research_auto_run(self, stage: int) -> bool:
        """v0.4 RFC §6.1: 是否在指定阶段自动跑调研

        Args:
            stage: 阶段号 0-7

        Returns:
            仅在 research.enabled=true 且 stage 在 auto_run_on 中时为 True
        """
        if not self.research.enabled:
            return False
        # 阶段号 → 阶段名映射(v0.3 默认顺序)
        stage_name = self.phases[stage] if 0 <= stage < len(self.phases) else ""
        return f"{stage_name}_stage" in self.research.auto_run_on


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
    return _parse_sop_dict(raw)


def load_sop_from_text(content: str) -> SOPConfig:
    """Phase C: 从 YAML 文本加载 SOP 配置（不经文件系统）。

    供 MemoryStorageBackend fixture 使用，避免 fixture 同时依赖 in-memory
    storage + 磁盘 sop.yaml 文件这一不一致状态。
    """
    raw = yaml.safe_load(content) or {}
    return _parse_sop_dict(raw)


def _parse_sop_dict(raw: dict) -> SOPConfig:

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
    raw_red_lines = sop_raw.get("red_lines", [])
    red_lines = _parse_red_lines(raw_red_lines)

    # 解析 gates
    raw_gates = sop_raw.get("gates", {})
    gates = {}
    for name, gate_raw in raw_gates.items():
        if isinstance(gate_raw, dict):
            gates[name] = GateConfig(**gate_raw)
        else:
            gates[name] = GateConfig()

    # 构建配置（忽略未知字段——向前兼容）
    known_fields = set(SOPConfig.model_fields.keys())
    # 排除 gates/red_lines——它们已从 sop_raw.get 提取，不重复传
    filtered = {k: v for k, v in sop_raw.items() if k in known_fields
                and k not in ("gates", "red_lines")}
    unknown = set(sop_raw.keys()) - known_fields - {"gates", "red_lines"}
    if unknown:
        warnings.warn(f"sop.yaml 包含未知字段（已忽略）: {unknown}")

    config = SOPConfig(**filtered, gates=gates, red_lines=red_lines)
    return config
