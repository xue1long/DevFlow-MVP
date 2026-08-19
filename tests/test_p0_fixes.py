"""P0/P1 整改验证测试

锁定第 3 轮审计修复的行为：
- P0-1/2/3: 账本原子写 + 文件锁 + 哈希链防篡改
- P0-4: Spec 轴真实检查（goal 覆盖 + contract 缺失）
- P0-5: Plan/Task/Contract 管理命令
- P0-7: 门禁命令危险模式拦截
- P0-8: git add 敏感文件阻止
- P1-1: spec_id 碰撞去重
- P1-3/4: commit/approve 阶段校验
- P1-12: 命令超时
- P1-14: 评审报告不可覆写
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from devflow.model import Spec, SpecStatus, Plan, Task, TaskStatus, Contract
from devflow.model.ledger import LedgerEntry, LedgerAction
from devflow.model.review import ReviewVerdict
from devflow.storage.fs_backend import FSBackend
from devflow.storage.git_port import SystemGitPort
from devflow.storage.review_store import ReviewStore
from devflow.policy.loader import load_sop
from devflow.engine.state_machine import PhaseStateMachine
from devflow.engine.review_engine import ReviewEngine
from devflow.verify.gate_runner import GateRunner, DANGEROUS_PATTERNS


@pytest.fixture
def env(tmp_path):
    storage = FSBackend(tmp_path)
    storage.init_workspace("""sop:
  sop_version: "0.1"
  phases: [intake, brainstorm, plan, contract, implement, verify, review, finish]
  intake_fast_skip: true
  red_lines: [no_test]
  gates:
    tests_pass: {command: "exit 0", blocking: true, enabled: true, bind_to_stage: 5}
    ci_green: {command: "exit 0", blocking: false, enabled: true, bind_to_stage: 6}
    intake_gate: {kind: triage, require: "ready-for-agent", blocking: true, enabled: true, bind_to_stage: 0}
    review_gate: {kind: "review", blocking: true, enabled: true, bind_to_stage: 2, max_rounds: 5, require_clear: true}
  tooling: {proxy_strip: false}
  storage: {backend: fs}
""")
    config = load_sop(tmp_path / "sop.yaml")
    review_store = ReviewStore(tmp_path)
    engine = ReviewEngine(storage, config, review_store)
    machine = PhaseStateMachine(storage, config, review_engine=engine)
    return engine, storage, config, review_store, machine, tmp_path


# --- P0-1/2/3: 账本哈希链 ---

def test_p0_hash_chain_detects_tampering(env):
    _, storage, _, _, _, _ = env
    storage.append_ledger(LedgerEntry(phase=0, action=LedgerAction.TRIAGE, details="e1"))
    storage.append_ledger(LedgerEntry(phase=1, action=LedgerAction.APPROVE, details="e2"))
    # 验证链完整
    ok = storage.verify_ledger()
    assert ok["ok"], f"完整链验证失败: {ok}"
    # 直接篡改 YAML 文件（绕过锁）
    import yaml
    ledger = storage._read_yaml(storage.ledger_path)
    ledger["entries"][0]["details"] = "被篡改"
    with open(storage.ledger_path, "w", encoding="utf-8") as f:
        yaml.dump(ledger, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    bad = storage.verify_ledger()
    assert not bad["ok"]


def test_p0_review_report_cannot_be_overwritten(env):
    engine, storage, config, review_store, machine, root = env
    machine.start("这是一个足够长的测试需求描述")
    spec_id = storage.get_current_spec_id()
    storage.set_current_plan_id(None)  # 无 Plan → Spec 轴不可评估
    engine.review(spec_id=spec_id)
    with pytest.raises(FileExistsError):
        engine.review(spec_id=spec_id, round=1)  # 显式要求 r1 → 应拒绝覆写


# --- P0-4: Spec 轴真实检查 ---

def test_p0_spec_axis_uncovered_goal(env):
    engine, storage, config, review_store, machine, _ = env
    machine.start("为 pipeline 增加 batch 重试")
    spec_id = storage.get_current_spec_id()
    spec = Spec(
        id=spec_id,
        title="Pipeline Batch Retry",
        problem="当前 pipeline 无重试机制，失败即中断，需要增加 batch 粒度的重试",
        goals=["支持 batch 级重试"],
        non_goals=["不引入消息队列"],
    )
    storage.write_spec(spec_id, spec.model_dump(mode="json"))
    # Plan 任务不匹配 goal 且无 contract
    plan = Plan(spec_id=spec_id, tasks=[Task(id="task-1", title="T1", module="x", acceptance=["a1"])])
    storage.write_plan("p1", plan.model_dump(mode="json"))
    storage.set_current_plan_id("p1")

    result = engine.review(spec_id=spec_id)
    report = result["report"]
    spec_rules = {v["rule"] for v in report["spec"]["violations"]}
    assert "spec_goal_uncovered" in spec_rules
    assert "spec_contract_missing" in spec_rules
    assert not result["can_advance"]  # major 违规 → FAIL


def test_p0_spec_axis_pass_when_covered(env):
    engine, storage, config, review_store, machine, _ = env
    machine.start("为 pipeline 增加 batch 重试")
    spec_id = storage.get_current_spec_id()
    spec = Spec(
        id=spec_id,
        title="Pipeline Batch Retry",
        problem="当前 pipeline 无重试机制，失败即中断，需要增加 batch 粒度的重试",
        goals=["支持 batch 级重试"],
        non_goals=["不引入消息队列"],
    )
    storage.write_spec(spec_id, spec.model_dump(mode="json"))
    plan = Plan(spec_id=spec_id, tasks=[Task(
        id="task-1", title="T1", module="pipeline", acceptance=["支持 batch 级重试"],
        contract={"module": "pipeline", "interface_signature": "retry_batch()"},
    )])
    storage.write_plan("p1", plan.model_dump(mode="json"))
    storage.set_current_plan_id("p1")

    result = engine.review(spec_id=spec_id)
    report = result["report"]
    assert report["spec"]["violations"] == [] or all(
        v["severity"] == "minor" for v in report["spec"]["violations"])


# --- P0-5: Plan/Task/Contract 命令 ---

def test_p0_plan_task_contract_flow(env):
    _, storage, config, _, machine, _ = env
    machine.start("为 pipeline 增加 batch 重试机制，本测试验证 Plan 完整流程")
    spec_id = storage.get_current_spec_id()
    # create_plan
    r = machine.create_plan(["构建 CLI|cli|支持命令解析"])
    assert r["ok"]
    plan_id = r["plan_id"]
    assert storage.get_current_plan_id() == plan_id
    # add_task
    r2 = machine.add_task("测试执行", "tests", ["有测试覆盖"])
    assert r2["ok"]
    # list_tasks
    listing = machine.list_tasks()
    assert listing["total_tasks"] == 2
    # add_contract
    r3 = machine.add_contract("task-1", "cli", "parse()")
    assert r3["ok"]
    listing2 = machine.list_tasks()
    assert listing2["tasks"][0]["has_contract"] is True


# --- P0-7: 门禁命令危险模式 ---

def test_p0_gate_command_blocks_dangerous(env):
    _, storage, config, _, _, tmp_path = env
    runner = GateRunner(config, str(tmp_path))
    # 危险命令被拦截
    blocked = runner._execute_command("rm -rf /tmp/x")
    assert blocked["returncode"] == -3
    blocked2 = runner._execute_command("sudo rm -rf /")
    assert blocked2["returncode"] == -3
    # 合法命令放行
    ok = runner._execute_command("exit 0")
    assert ok["returncode"] == 0
    # PowerShell 注入
    blocked3 = runner._execute_command("Invoke-Expression x")
    assert blocked3["returncode"] == -3


# --- P0-8: git 敏感文件 ---

def test_p0_git_sensitive_file_detection():
    port = SystemGitPort(Path("."))
    status = "?? .env\n M src/main.py\n?? secrets.txt"
    found = port.check_sensitive_files(status)
    assert ".env" in found
    assert "secrets.txt" in found
    assert "src/main.py" not in found


# --- P1-1: spec_id 去重 ---

def test_p1_spec_id_dedup(env):
    _, storage, config, _, machine, _ = env
    r1 = machine.start("为 pipeline 增加 batch 重试测试，相同草稿去重测试")
    r2 = machine.start("为 pipeline 增加 batch 重试测试，相同草稿去重测试")
    assert r1["spec_id"] != r2["spec_id"]  # 不应碰撞
    # 两个 spec 都存在
    assert storage.read_spec(r1["spec_id"]) is not None
    assert storage.read_spec(r2["spec_id"]) is not None


# --- P1-3/4: 阶段校验 ---

def test_p1_commit_phase_guard(env):
    _, storage, config, _, machine, _ = env
    machine.start("为 pipeline 增加 batch 重试测试，用于验证 commit 阶段校验")
    # Stage0 时 commit 应被拒绝
    r = machine.commit_task("task-1")
    assert not r["ok"]
    assert "commit 只能在 Stage5" in r["message"]


def test_p1_approve_phase_guard(env):
    _, storage, config, _, machine, _ = env
    machine.start("测试 approve")
    spec_id = storage.get_current_spec_id()
    # 推进到 Stage2 后再 approve → 应被拒绝
    machine.next_phase()  # 0→1 (需 approve)
    # 先 approve 再推进
    spec = Spec(
        id=spec_id, title="t", problem="这是一个足够长的 problem 描述",
        goals=["g1"], non_goals=["n1"],
    )
    storage.write_spec(spec_id, spec.model_dump(mode="json"))
    machine.approve_spec(spec_id)
    machine.next_phase()  # 1→2
    # 现在 approve 应被拒绝
    r = machine.approve_spec(spec_id)
    assert not r["ok"]
    assert "只能在 Stage0/1" in r["message"]


# --- P1-12: 命令超时 ---

def test_p1_command_timeout(env):
    _, storage, config, _, _, tmp_path = env
    # 修改超时配置为 1 秒，用 Python 睡眠命令触发超时
    config.tooling["command_timeout"] = 1
    runner = GateRunner(config, str(tmp_path))
    result = runner._execute_command('python -c "import time; time.sleep(5)"')
    # 超时返回 -2
    assert result["returncode"] == -2


def test_p1_review_gate_triggered_by_next(env):
    engine, storage, config, review_store, machine, _ = env
    machine.start("review gate 测试")
    spec_id = storage.get_current_spec_id()
    # 未评审时从 plan 阶段 next 应被 review_gate 拦截
    spec = Spec(
        id=spec_id, title="t",
        problem="这是一个足够长的 problem 描述",
        goals=["支持 batch 级重试"], non_goals=["n"],
    )
    storage.write_spec(spec_id, spec.model_dump(mode="json"))
    machine.approve_spec(spec_id)
    machine.next_phase()  # 0→1
    r_plan = machine.create_plan(["构建 CLI|cli|支持命令解析"])
    assert r_plan["ok"]
    machine.next_phase()  # 1→2
    # 现在 next 应触发 review_gate 并拦截（未评审）
    r = machine.next_phase()  # 2→3
    assert r["ok"] is False
    assert "review_gate" in r["message"] or "未通过" in r["message"]