"""P2 优化疏漏验证测试

锁定第 3 轮审计中 P2 等级改进的行为：
- P2-3: status 命令返回 spec_summary / plan_summary
- P2-5: _gate_intake 读取 sop.yaml 配置
- P2-8: cross_module_import 用正则精确解析
- P2-10: residual_count 不依赖 resolved
- P2-19: resume 验证账本引用一致性
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from devflow.model import Spec, Plan, Task
from devflow.model.ledger import LedgerEntry, LedgerAction
from devflow.model.review import ReviewReport, ReviewViolation, ReviewVerdict, ViolationSeverity, AxeReview
from devflow.storage.fs_backend import FSBackend
from devflow.policy.loader import load_sop
from devflow.engine.state_machine import PhaseStateMachine
from devflow.engine.redline_auditor import RedLineAuditor
from devflow.storage.git_port import SystemGitPort


@pytest.fixture
def env(tmp_path):
    storage = FSBackend(tmp_path)
    storage.init_workspace("""sop:
  sop_version: "0.1"
  phases: [intake, brainstorm, plan, contract, implement, verify, review, finish]
  intake_fast_skip: true
  red_lines: [cross_module_import]
  gates:
    tests_pass: {command: "exit 0", blocking: true, enabled: true, bind_to_stage: 5}
    ci_green: {command: "exit 0", blocking: false, enabled: true, bind_to_stage: 6}
    intake_gate: {kind: triage, require: "ready-for-agent", blocking: true, enabled: true, bind_to_stage: 0}
  modules: {forbidden_import: ["internal/", "secret/"]}
  tooling: {proxy_strip: false}
  storage: {backend: fs}
""")
    config = load_sop(tmp_path / "sop.yaml")
    machine = PhaseStateMachine(storage, config)
    return machine, storage, config, tmp_path


# --- P2-3: status 命令摘要 ---

def test_p2_status_spec_summary(env):
    machine, _, _, _ = env
    machine.start("为 pipeline 增加 batch 重试机制，用于验证 P2-3 状态摘要")
    status = machine.get_status()
    assert "spec_summary" in status
    s = status["spec_summary"]
    assert s["id"] is not None
    assert s["goals_total"] > 0
    assert s["goals_placeholder"] > 0  # 默认占位 goals
    # 缺失字段应被识别
    assert "problem" in s["missing_fields"] or "goals" in str(s["missing_fields"])


def test_p2_status_plan_summary(env):
    machine, storage, _, _ = env
    machine.start("为 pipeline 增加 batch 重试测试，用于验证 plan 摘要")
    spec_id = storage.get_current_spec_id()
    machine.create_plan(["构建 CLI|cli|支持命令解析"])
    status = machine.get_status()
    assert status["plan_summary"] is not None
    assert status["plan_summary"]["total_tasks"] >= 1
    assert status["plan_summary"]["missing_contract"] >= 1  # 无 contract


# --- P2-5: intake_gate 读配置 ---

def test_p2_intake_gate_respects_config(env):
    machine, storage, _, _ = env
    # 默认 intake_fast_skip=true → 应通过
    machine.start("为 pipeline 增加 batch 重试，验证 P2-5 intake 配置")
    result = machine._gate_intake()
    assert result["ok"]
    # 模拟禁用 intake_gate
    machine.config.gates["intake_gate"].enabled = False
    result2 = machine._gate_intake()
    assert result2["ok"]
    assert "禁用" in result2["message"]


# --- P2-8: cross_module_import 精确解析 ---

def test_p2_cross_module_import_precise_match(env):
    _, _, config, tmp_path = env
    # 创建 src/test_module.py，含有真实的违规 import
    src = tmp_path / "src"
    src.mkdir(exist_ok=True)
    (src / "ok_module.py").write_text(
        "from ok import thing\n# see internal/ for docs\n",
        encoding="utf-8",
    )
    (src / "bad_module.py").write_text(
        "from internal.submodule import helper\n",
        encoding="utf-8",
    )
    # 用字符串搜索会误报注释里的 internal/
    auditor = RedLineAuditor(tmp_path, config, git=SystemGitPort(tmp_path))
    violations = auditor._check_cross_module_import()
    # 应只检测到 bad_module.py 的真实 import（Windows 路径含 \\）
    files = {Path(v.message.split(":")[0]).name for v in violations}
    assert "bad_module.py" in files
    assert "ok_module.py" not in files  # 注释不应触发


# --- P2-10: residual_count ---

def test_p2_residual_count_not_dependent_on_resolved():
    """fix() 设 residual=True 同时设 resolved=True，residual_count 应正确统计"""
    v1 = ReviewViolation(
        id="S-001", axis="standards", rule="x",
        severity=ViolationSeverity.MINOR, message="测试残差计数场景 message",
    )
    v1.residual = True
    v1.resolved = True
    v2 = ReviewViolation(
        id="S-002", axis="standards", rule="y",
        severity=ViolationSeverity.MINOR, message="另一条残差场景 message",
    )
    v2.residual = True
    v2.resolved = False  # 罕见但兼容

    report = ReviewReport(
        id="r1", spec_id="s1", phase=0,
        standards=AxeReview(verdict=ReviewVerdict.PASS, violations=[v1, v2]),
        spec=AxeReview(verdict=ReviewVerdict.PASS, violations=[]),
    )
    # P2-10: residual_count 统计所有 residual=True 的违规（不论 resolved）
    assert report.residual_count == 2
    # 新增 active_residual_count 仅统计未 resolved 的
    assert report.active_residual_count == 1


# --- P2-19: resume 一致性验证 ---

def test_p2_resume_detects_missing_spec(env):
    machine, storage, _, tmp_path = env
    machine.start("为 pipeline 增加 batch 重试，验证 P2-19 resume 一致性")
    # suspend 写 handoff
    machine.suspend("test handoff")
    # 删除 spec 文件，模拟外部删除
    spec_id = storage.get_current_spec_id()
    spec_path = tmp_path / "specs" / f"{spec_id}.yaml"
    spec_path.unlink()
    # resume 应检测到缺失并发出警告
    result = machine.resume()
    assert result["ok"]
    assert any("Spec" in w for w in result["warnings"])