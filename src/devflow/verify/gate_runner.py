"""GateRunner — 门禁执行器

从 state_machine 中剥离的门禁执行逻辑。
负责：执行命令、检查 exit code、处理 proxy_strip。
"""
from __future__ import annotations

import os
import subprocess
from typing import Optional

from ..policy.loader import SOPConfig, GateConfig


class GateRunner:
    """门禁执行器

    职责：根据 sop.yaml 配置执行门禁命令，返回 pass/fail 结果。
    不负责状态转换——那是 PhaseStateMachine 的事。
    """

    def __init__(self, config: SOPConfig, cwd: str):
        self.config = config
        self.cwd = cwd

    def run_tests_pass(self) -> dict:
        """执行 tests_pass 门禁"""
        gate = self.config.get_gate("tests_pass")
        if gate is None or not gate.enabled or gate.command is None:
            return {"ok": False, "message": "tests_pass 门禁未配置"}
        return self._execute_gate_command(gate)

    def run_ci_green(self) -> dict:
        """执行 ci_green 门禁（advisory）"""
        gate = self.config.get_gate("ci_green")
        if gate is None or not gate.enabled:
            return {"ok": True, "message": "ci_green 门禁未启用，跳过"}
        if gate.command is None:
            return {"ok": True, "message": "ci_green 门禁无命令，跳过"}
        result = self._execute_command(gate.command)
        # advisory 模式：执行完成即可，不要求 pass
        return {
            "ok": True,
            "message": f"ci_green 已执行 (exit code {result['returncode']})，advisory 不阻断",
        }

    def run_intake_gate(self, triage_state: str, intake_fast_skip: bool) -> dict:
        """执行 intake_gate 门禁"""
        if intake_fast_skip:
            return {"ok": True, "message": "intake_fast_skip 自动通过"}
        if triage_state == "ready-for-agent":
            return {"ok": True, "message": "Intake 闸门通过 (triage_state=ready-for-agent)"}
        return {"ok": False, "message": f"Intake 闸门未通过: triage_state={triage_state}"}

    def run_gate_by_name(self, gate_name: str) -> dict:
        """按名称执行门禁"""
        gate = self.config.get_gate(gate_name)
        if gate is None:
            return {"ok": False, "message": f"门禁 '{gate_name}' 未配置"}
        if not gate.enabled:
            return {"ok": True, "message": f"门禁 '{gate_name}' 未启用，跳过"}
        if gate.kind == "triage":
            return {"ok": False, "message": "triage 门禁需要专门处理"}
        if gate.command is None:
            return {"ok": True, "message": f"门禁 '{gate_name}' 无命令，跳过"}

        result = self._execute_command(gate.command)
        passed = result["returncode"] == 0
        if not gate.blocking:
            passed = True  # advisory 模式不阻断

        return {
            "ok": passed,
            "message": f"exit code {result['returncode']}",
            "blocking": gate.blocking,
        }

    def get_enabled_gates_for_stage(self, stage: int) -> list[tuple[str, GateConfig]]:
        """返回绑定到指定阶段的所有 enabled 门禁"""
        return self.config.get_enabled_gates_for_stage(stage)

    def _execute_gate_command(self, gate: GateConfig) -> dict:
        """执行单个门禁命令"""
        if gate.command is None:
            return {"ok": False, "message": "门禁命令为空"}
        result = self._execute_command(gate.command)
        if result["returncode"] == 0:
            return {"ok": True, "message": f"门禁通过 (exit code 0)"}
        return {
            "ok": False,
            "message": f"门禁失败 (exit code {result['returncode']})",
            "stdout": result["stdout"][-500:] if result["stdout"] else "",
            "stderr": result["stderr"][-500:] if result["stderr"] else "",
        }

    def _execute_command(self, command: str) -> dict:
        """执行 shell 命令，返回结果"""
        env = None
        if self.config.tooling.get("proxy_strip"):
            env = os.environ.copy()
            for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
                env.pop(key, None)

        try:
            result = subprocess.run(
                command, shell=True,
                cwd=self.cwd, capture_output=True, text=True,
                env=env,
            )
            return {
                "returncode": result.returncode,
                "stdout": result.stdout or "",
                "stderr": result.stderr or "",
            }
        except Exception as e:
            return {"returncode": -1, "stdout": "", "stderr": str(e)}
