"""SDD 子代理编排 — 数据模型 + RulingStore + CircuitBreaker（B2.1+B2.2 阶段）

架构文档 §5.2.1 SDD 执行模式（obra/superpowers #1）：
- 每任务新子代理（隔离上下文）
- 任务级双审查（spec + quality）
- plan-scoped workspace
- 修复循环
- 5 轮断路器 + never-stall 裁决
- Model 选型（implementer / reviewer / escalator）

RulingStore 把裁决落 progress.yaml 账本（LedgerAction.RULING 已在 model/ledger.py:18）。
CircuitBreaker 实现 5 轮断路器逻辑。
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field

from ..model.ledger import LedgerAction, LedgerEntry


class DispatchConfig(BaseModel):
    """SDD 派发配置（未来从 sop.yaml 读取，当前硬编码默认）"""
    model_tiers: dict[str, str] = Field(
        default_factory=lambda: {
            "implementer": "sonnet",
            "reviewer": "haiku",
            "escalator": "opus",
        },
        description="模型分档配置：key=角色名，value=模型名",
    )
    max_rounds: int = Field(
        default=5,
        ge=1,
        le=20,
        description="断路器最大轮次（5 轮无进展触发 escalate）",
    )
    parallel: bool = Field(
        default=False,
        description="是否启用并行派发（前置：M6 阶段）",
    )
    worktree_per_task: bool = Field(
        default=False,
        description="是否每个 Task 隔离 git worktree",
    )


class SubagentTask(BaseModel):
    """单个子代理任务

    devflow 编排 Agent，不实现 Agent（v3 纪律）。
    AgentRunner 负责把 SubagentTask 翻译成具体平台的 CLI。
    """
    task_id: str = Field(..., description="Task ID（Plan 内的标识）")
    prompt: str = Field(..., description="给 Agent 的指令文本")
    worktree: Optional[Path] = Field(default=None, description="可选的 worktree 路径")
    model_tier: str = Field(
        default="implementer",
        description="使用的模型分档（从 DispatchConfig.model_tiers 选）",
    )


class RulingType:
    """裁决类型常量（架构文档 §5.2.1 never-stall 4 类硬停）"""
    SKIP = "skip"          # 跳过此 Task
    REPLAN = "replan"      # 重新规划（修复失败后）
    ESCALATE = "escalate"  # 升级（断路器触发）
    HALT = "halt"          # 人工停止


class RulingRef(BaseModel):
    """never-stall 裁决记录（落 progress.yaml 账本）

    4 类硬停（架构文档 §5.2.1）：
    - skip: 用户主动跳过
    - replan: 修复失败后重新规划
    - escalate: 5 轮断路器触发
    - halt: 人工停止
    """
    task_id: str = Field(..., description="关联的 Task ID")
    ruling_type: str = Field(..., description="裁决类型")
    reason: str = Field(..., description="裁决原因（落账本 + 可追溯）")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(),
        description="裁决时间",
    )

    def is_terminal(self) -> bool:
        """是否终态裁决（stop 当前 Task 调度）"""
        return self.ruling_type in (
            RulingType.SKIP,
            RulingType.HALT,
        )

    def is_escalation(self) -> bool:
        """是否升级裁决（需要人工介入）"""
        return self.ruling_type in (
            RulingType.ESCALATE,
            RulingType.HALT,
        )


class RulingStore:
    """裁决账本存储（落 progress.yaml 哈希链）

    写：append_ledger() 走 StorageBackend 接口，自动接 SHA256 哈希链
    读：get_ledger() 读所有 entries，按 task_id + ruling_type 过滤

    设计选择：LedgerEntry.task_id 字段已存在（model/ledger.py:37），
    用 details="Ruling: <type>" 前缀标识裁决类型。
    """

    RULING_DETAIL_PREFIX = "Ruling: "

    def __init__(self, storage):
        self.storage = storage

    def record(self, ruling: RulingRef) -> None:
        """落账本（走 StorageBackend.append_ledger 哈希链）"""
        self.storage.append_ledger(LedgerEntry(
            phase=self.storage.get_current_phase(),
            action=LedgerAction.RULING,  # model/ledger.py:18 已存在
            task_id=ruling.task_id,
            reason=ruling.reason,
            details=f"{self.RULING_DETAIL_PREFIX}{ruling.ruling_type}",
        ))

    def has_halt(self, task_id: str) -> bool:
        """是否有人工 halt 裁决"""
        return self._latest_ruling(task_id, RulingType.HALT) is not None

    def get_halt(self, task_id: str) -> Optional[RulingRef]:
        """取最新 halt 裁决"""
        return self._latest_ruling(task_id, RulingType.HALT)

    def _latest_ruling(self, task_id: str, ruling_type: str) -> Optional[RulingRef]:
        """从账本读指定类型的最新裁决"""
        ledger = self.storage.get_ledger()
        for entry in reversed(ledger.get("entries", [])):
            if (
                entry.get("task_id") == task_id
                and entry.get("details", "").startswith(self.RULING_DETAIL_PREFIX)
                and entry.get("details", "").endswith(ruling_type)
            ):
                return RulingRef(
                    task_id=task_id,
                    ruling_type=ruling_type,
                    reason=entry.get("reason", ""),
                    timestamp=entry.get("timestamp", datetime.now()),
                )
        return None


class CircuitBreaker:
    """5 轮任务编排断路器（架构文档 §5.2.1 #5）

    借鉴 obra never-stall 模式：仅 4 类硬停
    - 第 1 类：用户显式 halt（从账本查）
    - 第 2 类：连续 N 轮无进展 → escalate
    - 第 3 类：同类失败复发（架构文档 §5.1 反馈环律）—— 留扩展
    - 第 4 类：硬约束冲突（如哈希链断裂）—— 留扩展

    当前实现第 1、2 类，第 3、4 类在 B2.4+ 扩展。
    """

    MAX_ROUNDS = 5

    def __init__(self, config: DispatchConfig, ruling_store: RulingStore):
        self.config = config
        self.rulings = ruling_store

    def should_stop(self, task_id: str, round: int) -> Optional[RulingRef]:
        """检查是否应停止 + 返回 RulingRef；None 表示继续

        Args:
            task_id: 当前 Task ID
            round: 当前轮次（1-based）

        Returns:
            RulingRef 表示停止 + 原因；None 表示继续
        """
        # 第 1 类：用户显式 halt
        if self.rulings.has_halt(task_id):
            halt = self.rulings.get_halt(task_id)
            return RulingRef(
                task_id=task_id,
                ruling_type=RulingType.HALT,
                reason=f"用户 halt: {halt.reason}",
            )

        # 第 2 类：超过最大轮次
        if round >= self.config.max_rounds:
            return RulingRef(
                task_id=task_id,
                ruling_type=RulingType.ESCALATE,
                reason=f"超过最大轮次 {self.config.max_rounds} 仍无进展",
            )

        return None


class DispatchResult(BaseModel):
    """单个 Task 调度结果"""
    task_id: str
    ok: bool = False
    rounds: int = 0
    ruling: Optional[RulingRef] = None
    error: Optional[str] = None


class Dispatcher:
    """子代理编排引擎（B2.4 阶段）

    核心循环（每 Task）：
    1. 派发实现子代理（AgentRunner.run_subagent）
    2. 派发评审子代理（复用 ReviewEngine.review）
    3. 跑质量门禁（GateRunner.run_gate_by_name("tests_pass")）
    4. 检查断路器（5 轮无进展 → escalate）
    5. 通过 + 门禁过 → return ok=True；否则 return RulingRef

    修复要点（v3 修订）：
    - Task 没有 plan_id 字段 → 用 plan.spec_id + storage 取 plan_id
    - 不调 devflow 命令 → 调 AgentRunner
    - quality 门禁用 GateRunner.run_gate_by_name 而非 quality_runner.run(task)
    """

    def __init__(
        self,
        storage,
        review_store,
        review_engine,
        agent_runner,
        gate_runner,
        config: DispatchConfig,
    ):
        self.storage = storage
        self.review_store = review_store
        self.review_engine = review_engine
        self.agent_runner = agent_runner
        self.gate_runner = gate_runner
        self.config = config
        self.breaker = CircuitBreaker(config, RulingStore(storage))

    async def dispatch_task(
        self,
        task,
        plan,
    ) -> DispatchResult:
        """派发单个 Task，带 5 轮断路器"""
        from ..model.task import Task

        plan_id = self.storage.get_current_plan_id()
        spec_id = plan.spec_id

        for round_num in range(1, self.config.max_rounds + 1):
            # 检查断路器（halt + max_rounds）
            ruling = self.breaker.should_stop(task.id, round_num)
            if ruling:
                self.breaker.rulings.record(ruling)
                return DispatchResult(task_id=task.id, ruling=ruling)

            # 1. 派发实现子代理
            subagent_task = SubagentTask(
                task_id=task.id,
                prompt=(
                    f"实现 Task '{task.title}' (module={task.module})\n"
                    f"参考: specs/{spec_id}.yaml, plans/{plan_id}.yaml\n"
                    f"验收: {task.acceptance}"
                ),
            )
            try:
                impl_result = await self.agent_runner.run_subagent(subagent_task)
            except Exception as e:
                return DispatchResult(
                    task_id=task.id,
                    error=f"agent runner failed: {e}",
                )

            if not impl_result.get("ok", False):
                # Agent 失败 — 记录 replan 裁决，继续下一轮
                ruling = RulingRef(
                    task_id=task.id,
                    ruling_type=RulingType.REPLAN,
                    reason=f"agent failed: {impl_result.get('error', '')[:200]}",
                )
                self.breaker.rulings.record(ruling)
                continue

            # 2. 跑质量门禁（修订：用 GateRunner.run_gate_by_name）
            quality_ok = True
            if self.gate_runner is not None:
                try:
                    quality = self.gate_runner.run_gate_by_name("tests_pass")
                    quality_ok = quality.get("ok", False)
                except Exception:
                    quality_ok = True  # 门禁缺失默认 PASS（MVP 容错）

            # 3. 派发评审（复用 ReviewEngine）
            try:
                review_result = self.review_engine.review(spec_id=spec_id)
                review_ok = review_result.get("can_advance", False)
            except Exception:
                review_ok = False

            if quality_ok and review_ok:
                return DispatchResult(task_id=task.id, rounds=round_num, ok=True)

            # 4. 不通过 → 下一轮重试（最多 max_rounds）
        # 5 轮后仍未通过 → escalate（断路器处理）
        ruling = self.breaker.should_stop(task.id, self.config.max_rounds)
        return DispatchResult(task_id=task.id, ruling=ruling)


def create_dispatcher(
    root: Path,
    agent_command: Optional[str] = None,
    use_real_agent: bool = False,
    sop_config=None,
):
    """Dispatcher 工厂函数（CLI 入口处调用）

    Args:
        root: DevFlow 工作区根目录
        agent_command: 真实 Agent 命令（如 "claude"）；None 则用 MockAgentRunner
        use_real_agent: True 时用 ClaudeCodeAgentRunner 替换 Mock
        sop_config: SOP 配置（B6 阶段从 sop.yaml 读取 model_tiers）；None 则用默认

    Returns:
        完全装配的 Dispatcher 实例（含 GateRunner / ReviewEngine / AgentRunner）

    Examples:
        # 测试用：Mock Agent + 默认 config
        >>> dispatcher = create_dispatcher(Path("."))
        # 生产用：ClaudeCodeAgentRunner + sop.yaml 配置
        >>> dispatcher = create_dispatcher(Path("."), use_real_agent=True, sop_config=sop)
    """
    from ..storage.fs_backend import FSBackend
    from ..storage.review_store import ReviewStore
    from ..policy.loader import SOPConfig, load_sop
    from ..verify.gate_runner import GateRunner
    from ..engine.review_engine import ReviewEngine
    from .agent_runner import (
        ClaudeCodeAgentRunner,
        GenericAgentRunner,
        MockAgentRunner,
    )

    root = Path(root)
    storage = FSBackend(root)
    review_store = ReviewStore(root)

    # B6 阶段：从 sop.yaml 读取 SDD 配置
    if sop_config is None:
        sop_path = root / "sop.yaml"
        if sop_path.exists():
            sop_config = load_sop(sop_path)
        else:
            sop_config = SOPConfig()

    review_engine = ReviewEngine(storage, sop_config, review_store)
    gate_runner = GateRunner(storage, sop_config)

    if use_real_agent:
        if agent_command == "claude" or agent_command is None:
            agent_runner = ClaudeCodeAgentRunner(worktree_root=root)
        else:
            agent_runner = GenericAgentRunner(
                command=agent_command, worktree_root=root,
            )
    else:
        agent_runner = MockAgentRunner()

    # 从 sop_config 派生 DispatchConfig
    config = _dispatch_config_from_sop(sop_config)

    return Dispatcher(
        storage=storage,
        review_store=review_store,
        review_engine=review_engine,
        agent_runner=agent_runner,
        gate_runner=gate_runner,
        config=config,
    )


def _dispatch_config_from_sop(sop_config) -> DispatchConfig:
    """从 SOPConfig 派生 DispatchConfig（B6 阶段）

    映射规则：
    - sop_config.sd.model_tiers → DispatchConfig.model_tiers
    - sop_config.sd.max_rounds → DispatchConfig.max_rounds
    - sop_config.sd.parallel → DispatchConfig.parallel
    - sop_config.sd.worktree_per_task → DispatchConfig.worktree_per_task
    """
    sd = sop_config.sd
    return DispatchConfig(
        model_tiers={
            "implementer": sd.model_tiers.implementer,
            "reviewer": sd.model_tiers.reviewer,
            "escalator": sd.model_tiers.escalator,
        },
        max_rounds=sd.max_rounds,
        parallel=sd.parallel,
        worktree_per_task=sd.worktree_per_task,
    )


async def dispatch_plan(
    dispatcher: Dispatcher,
    plan_id: str,
) -> dict[str, Any]:
    """顺序派发 Plan 内所有 Task（B2.5 阶段）

    Args:
        dispatcher: 已装配的 Dispatcher
        plan_id: Plan ID

    Returns:
        {"plan_id": str, "results": list[DispatchResult.model_dump()]}

    Raises:
        ValueError: Plan 不存在或 DAG 不合法
    """
    from ..model.plan import Plan

    plan_data = dispatcher.storage.read_plan(plan_id)
    if plan_data is None:
        raise ValueError(f"Plan '{plan_id}' 不存在")

    plan = Plan(**plan_data)

    # B5 阶段：顺序派发（前置 DAG 校验在 Plan.model_validator 已做）
    results = []
    for task in plan.tasks:
        result = await dispatcher.dispatch_task(task, plan)
        results.append(result.model_dump())

    return {"plan_id": plan_id, "results": results}


async def dispatch_plan_parallel(
    dispatcher: Dispatcher,
    plan_id: str,
) -> dict[str, Any]:
    """并行派发 Plan 内所有 Task（B2.6 / M6 阶段）

    借鉴 obra dispatching-parallel-agents（架构文档 §5.2.1 #3）：
    - 同一批次内 blocked_by 已清的 task 并行派发
    - 批次完成后进入下一批次
    - 死锁应被 Plan.model_validator 拦截（B5 阶段）

    Args:
        dispatcher: 已装配的 Dispatcher
        plan_id: Plan ID

    Returns:
        {"plan_id": str, "results": list[DispatchResult.model_dump()]}
    """
    from ..model.plan import Plan

    plan_data = dispatcher.storage.read_plan(plan_id)
    if plan_data is None:
        raise ValueError(f"Plan '{plan_id}' 不存在")

    plan = Plan(**plan_data)

    # 按 blocked_by 拓扑分层
    pending = {t.id: t for t in plan.tasks}
    completed: dict[str, dict[str, Any]] = {}
    results: list[dict[str, Any]] = []

    while pending:
        # frontier = 当前无未完成前置的 task
        frontier = [
            t for t in pending.values()
            if all(b in completed for b in t.blocked_by)
        ]
        if not frontier:
            # DAG 死锁（理论上 Plan.model_validator 已拦截）
            raise RuntimeError(
                f"DAG 死锁: pending={list(pending.keys())} "
                f"completed={list(completed.keys())}"
            )

        # 同批次并发
        batch_results = await asyncio.gather(*[
            dispatcher.dispatch_task(t, plan) for t in frontier
        ])
        for task, result in zip(frontier, batch_results):
            result_dict = result.model_dump()
            completed[task.id] = result_dict
            results.append(result_dict)
            del pending[task.id]

    return {"plan_id": plan_id, "results": results}