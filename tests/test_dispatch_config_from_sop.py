"""tests/test_dispatch_config_from_sop.py — B6 阶段验证

覆盖:
- ModelTiersConfig 默认值（sonnet / haiku / opus）
- SDConfig 默认值（max_rounds=5）
- _dispatch_config_from_sop() 字段映射
- 从 sop.yaml 文本加载 model_tiers 覆盖默认值
"""
from __future__ import annotations

from pathlib import Path

import pytest

from devflow.engine.dispatcher import (
    DispatchConfig,
    _dispatch_config_from_sop,
    create_dispatcher,
)
from devflow.policy.loader import (
    ModelTiersConfig,
    SDConfig,
    SOPConfig,
    load_sop_from_text,
)


class TestModelTiersConfig:
    """ModelTiersConfig 默认值"""

    def test_defaults(self):
        config = ModelTiersConfig()
        assert config.implementer == "sonnet"
        assert config.reviewer == "haiku"
        assert config.escalator == "opus"

    def test_can_override(self):
        config = ModelTiersConfig(
            implementer="opus",
            reviewer="sonnet",
            escalator="haiku",
        )
        assert config.implementer == "opus"
        assert config.reviewer == "sonnet"
        assert config.escalator == "haiku"


class TestSDConfig:
    """SDConfig 默认值"""

    def test_defaults(self):
        config = SDConfig()
        assert config.max_rounds == 5
        assert config.parallel is False
        assert config.worktree_per_task is False
        assert isinstance(config.model_tiers, ModelTiersConfig)


class TestDispatchConfigFromSop:
    """_dispatch_config_from_sop() 字段映射"""

    def test_default_sop_uses_default_dispatch_config(self):
        """默认 SOPConfig → 默认 DispatchConfig"""
        sop_config = SOPConfig()
        config = _dispatch_config_from_sop(sop_config)
        assert config.max_rounds == 5
        assert config.parallel is False
        assert config.model_tiers["implementer"] == "sonnet"
        assert config.model_tiers["reviewer"] == "haiku"
        assert config.model_tiers["escalator"] == "opus"

    def test_sop_yaml_overrides(self):
        """sop.yaml sd 节覆盖 DispatchConfig 默认值"""
        sop_yaml = """
sop:
  sop_version: "0.1"
  sd:
    model_tiers:
      implementer: opus
      reviewer: sonnet
      escalator: haiku
    max_rounds: 10
    parallel: true
    worktree_per_task: true
"""
        sop_config = load_sop_from_text(sop_yaml)
        config = _dispatch_config_from_sop(sop_config)

        assert config.max_rounds == 10
        assert config.parallel is True
        assert config.worktree_per_task is True
        assert config.model_tiers["implementer"] == "opus"
        assert config.model_tiers["reviewer"] == "sonnet"
        assert config.model_tiers["escalator"] == "haiku"

    def test_partial_override(self):
        """只覆盖部分字段，未覆盖的用默认"""
        sop_yaml = """
sop:
  sop_version: "0.1"
  sd:
    max_rounds: 3
"""
        sop_config = load_sop_from_text(sop_yaml)
        config = _dispatch_config_from_sop(sop_config)

        # 覆盖字段
        assert config.max_rounds == 3
        # 未覆盖字段保持默认
        assert config.parallel is False
        assert config.model_tiers["implementer"] == "sonnet"


class TestCreateDispatcherUsesSop:
    """create_dispatcher() 使用 sop_config 参数"""

    def test_create_dispatcher_with_explicit_sop(self, tmp_path: Path):
        """显式传 sop_config 应使用其 sd 节"""
        sop_yaml = """
sop:
  sop_version: "0.1"
  sd:
    max_rounds: 7
    model_tiers:
      implementer: opus
"""
        sop_config = load_sop_from_text(sop_yaml)

        dispatcher = create_dispatcher(
            tmp_path, sop_config=sop_config, use_real_agent=False
        )
        assert dispatcher.config.max_rounds == 7
        assert dispatcher.config.model_tiers["implementer"] == "opus"

    def test_create_dispatcher_falls_back_to_sop_file(self, tmp_path: Path):
        """无 sop_config 参数但 tmp_path/sop.yaml 存在 → 读取"""
        # 在 tmp_path/sop.yaml 写一个 max_rounds=8 的配置
        sop_yaml = """
sop:
  sop_version: "0.1"
  sd:
    max_rounds: 8
"""
        (tmp_path / "sop.yaml").write_text(sop_yaml)

        dispatcher = create_dispatcher(tmp_path, use_real_agent=False)
        assert dispatcher.config.max_rounds == 8

    def test_create_dispatcher_default_when_no_sop(self, tmp_path: Path):
        """无 sop_config 且无 sop.yaml → 默认 DispatchConfig"""
        dispatcher = create_dispatcher(tmp_path, use_real_agent=False)
        assert dispatcher.config.max_rounds == 5
        assert dispatcher.config.model_tiers["implementer"] == "sonnet"