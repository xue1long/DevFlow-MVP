"""G3 ShellCheck 门禁接入验证（配置驱动，复用 GateRunner 全链路）

目标：证明 G3 经 sop.yaml gate 接入后，确实落在 devflow 运行的门禁管线中——
state_machine → get_enabled_gates_for_stage → GateRunner.run_gate_by_name → _execute_command，
且无需任何 Python 代码改动（不吸收进核心）。

覆盖：
1. 真实 sop.yaml 加载后，shellcheck gate 存在、默认 disabled、advisory（blocking=false）。
2. 默认 disabled 时不进入 get_enabled_gates_for_stage(5)；enabled 后进入。
3. GateRunner.run_gate_by_name 端到端：命令被执行、exit code 驱动 pass/fail、
   blocking 语义正确、DANGEROUS_PATTERNS 注入防护生效。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from devflow.policy.loader import (  # noqa: E402
    SOPConfig, GateConfig, load_sop, load_sop_from_text,
)
from devflow.verify.gate_runner import GateRunner, DANGEROUS_PATTERNS  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
SOP_YAML = REPO_ROOT / "sop.yaml"


def test_shellcheck_gate_present_and_default_disabled():
    """真实 sop.yaml 中应含 G3 shellcheck gate，且默认禁用 + advisory。"""
    config = load_sop(SOP_YAML)
    gate = config.get_gate("shellcheck")
    assert gate is not None, "sop.yaml 缺少 shellcheck gate（G3 接入未落地）"
    assert gate.enabled is False, "G3 应默认禁用（devflow 不产 Bash，且需本地装 shellcheck）"
    assert gate.blocking is False, "G3 默认应为 advisory（不硬阻断）"
    assert gate.bind_to_stage == 5, "G3 应绑定 verify 阶段出口"


def test_shellcheck_not_active_when_disabled():
    """默认禁用时，不应出现在 get_enabled_gates_for_stage(5)。"""
    config = load_sop(SOP_YAML)
    active = config.get_enabled_gates_for_stage(5)
    assert "shellcheck" not in [name for name, _ in active]


def test_shellcheck_active_when_enabled():
    """enabled 后，应出现在 get_enabled_gates_for_stage(5)（管线真实消费点）。"""
    yaml_text = """
sop:
  sop_version: "0.1"
  gates:
    shellcheck:
      command: "echo probe"
      blocking: false
      enabled: true
      bind_to_stage: 5
"""
    config = load_sop_from_text(yaml_text)
    active = config.get_enabled_gates_for_stage(5)
    names = [name for name, _ in active]
    assert "shellcheck" in names


def test_gate_runner_executes_command_and_respects_blocking():
    """run_gate_by_name 端到端：命令被执行、exit code 驱动 pass/fail、blocking 生效。"""
    config = SOPConfig(
        gates={
            "pass_blocking": GateConfig(command="exit 0", enabled=True, blocking=True),
            "fail_blocking": GateConfig(command="exit 7", enabled=True, blocking=True),
            "fail_advisory": GateConfig(command="exit 7", enabled=True, blocking=False),
        },
        tooling={},
    )
    runner = GateRunner(config, cwd=".")

    # 通过命令：blocking 下 ok=True
    r1 = runner.run_gate_by_name("pass_blocking")
    assert r1["ok"] is True

    # 失败命令 + blocking：ok=False（真实阻断）
    r2 = runner.run_gate_by_name("fail_blocking")
    assert r2["ok"] is False

    # 失败命令 + advisory：ok=True（不阻断，advisory 语义）
    r3 = runner.run_gate_by_name("fail_advisory")
    assert r3["ok"] is True


def test_gate_runner_blocks_dangerous_command():
    """DANGEROUS_PATTERNS 注入防护对 G3 门禁同样生效（复用 GateRunner 全链路）。"""
    dangerous = DANGEROUS_PATTERNS[0]  # 例如 "rm -rf"
    cmd = f"echo {dangerous}"
    config = SOPConfig(
        gates={"evil": GateConfig(command=cmd, enabled=True, blocking=True)},
        tooling={},
    )
    runner = GateRunner(config, cwd=".")
    # 1) 执行层直接拦截：返回码 -3 且 stderr 说明被危险模式阻止（命令不真正执行）
    exec_result = runner._execute_command(cmd)
    assert exec_result["returncode"] == -3
    assert "危险模式" in exec_result["stderr"]
    # 2) 经 run_gate_by_name：被拦命令视为门禁不通过（ok=False），不会静默放行
    gate_result = runner.run_gate_by_name("evil")
    assert gate_result["ok"] is False
