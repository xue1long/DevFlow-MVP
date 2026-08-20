"""GateRunner — 门禁执行器

从 state_machine 中剥离的门禁执行逻辑。
负责：执行命令、检查 exit code、处理 proxy_strip。
"""
from __future__ import annotations

import os
import subprocess
from typing import Optional

from ..policy.loader import SOPConfig, GateConfig


# P0-7: 危险命令模式——阻止注入/破坏性命令
# 注：shell 链式运算符(&&, ||, |) 被允许，因为测试命令常用且 sop.yaml 是受信任配置
DANGEROUS_PATTERNS = [
    "rm -rf", "del /f", "rd /s",                    # 破坏性删除
    "> /etc/", "> /dev/",                            # 覆写系统文件
    "wget ", "curl -o", "curl |", "nc -",            # 远程下载/数据外传
    "invoke-expression", "iex ",                     # PowerShell 注入
    "chmod 777", "chmod +x",                         # 权限滥用
    "sudo ", "su ", "pkexec",                        # 提权
]


class GateRunner:
    """门禁执行器

    职责：根据 sop.yaml 配置执行门禁命令，返回 pass/fail 结果。
    不负责状态转换——那是 PhaseStateMachine 的事。
    """

    def __init__(self, config: SOPConfig, cwd: str, review_engine: Optional['ReviewEngine'] = None):
        self.config = config
        self.cwd = cwd
        self.review_engine = review_engine

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
        # review_gate 委托给 review_engine（v0.3.4:消除 PhaseStateMachine 中的硬编码）
        if gate_name == "review_gate":
            if self.review_engine is None:
                return {"ok": False, "message": "review_engine 未注入，无法执行 review_gate"}
            return self.review_engine.check_review_gate()
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
        """返回绑定到指定阶段的所有 enabled 门禁

        ⚠️ v0.3.4 行为变化：聚合 review_gate 到统一出口
        之前仅返回 SOPConfig.get_enabled_gates_for_stage() 结果，
        现在额外检查 review_gate.bind_to_stage 并追加。
        当前唯一调用方是 state_machine.py:600。
        """
        gates = self.config.get_enabled_gates_for_stage(stage)
        # review_gate 也走统一出口（不再由 PhaseStateMachine 硬编码）
        # 注意：SOPConfig.get_enabled_gates_for_stage 已包含 review_gate（如果 enabled）
        # 需避免重复——仅当 SOPConfig 没返回 review_gate 时才追加
        if not any(name == "review_gate" for name, _ in gates):
            review_gate = self.config.gates.get("review_gate")
            if review_gate and review_gate.enabled and review_gate.bind_to_stage == stage:
                gates.append(("review_gate", review_gate))
        return gates

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
        """执行 shell 命令，返回结果
        
        P1-12: 增加超时保护（默认 120 秒），防止门禁命令无限挂起
        """
        blocked = self._validate_command(command)
        if blocked:
            return {"returncode": -3, "stdout": "", "stderr": blocked}

        env = None
        if self.config.tooling.get("proxy_strip"):
            env = os.environ.copy()
            for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
                env.pop(key, None)

        # 从 sop.yaml 读取超时配置，默认 120 秒
        timeout = self.config.tooling.get("command_timeout", 120)

        try:
            result = subprocess.run(
                command, shell=True,
                cwd=self.cwd, capture_output=True, text=True,
                env=env,
                timeout=timeout,
            )
            return {
                "returncode": result.returncode,
                "stdout": result.stdout or "",
                "stderr": result.stderr or "",
            }
        except subprocess.TimeoutExpired:
            return {
                "returncode": -2,
                "stdout": "",
                "stderr": f"命令执行超时（超过 {timeout} 秒）: {command[:100]}",
            }
        except Exception as e:
            return {"returncode": -1, "stdout": "", "stderr": str(e)}

    def _validate_command(self, command: str) -> Optional[str]:
        """P0-7: 检测破坏性/注入命令，返回阻止原因或 None"""
        lowered = command.lower()
        for pattern in DANGEROUS_PATTERNS:
            if pattern in lowered:
                return (
                    f"命令包含危险模式 '{pattern}'，已阻止执行（P0-7 安全防护）。"
                    f"如果是误报，请检查 sop.yaml 中 gate.command 配置"
                )
        return None
