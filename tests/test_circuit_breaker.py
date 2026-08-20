"""tests/test_circuit_breaker.py — B2.2 阶段验证

覆盖:
- CircuitBreaker 5 轮触发 escalate
- RulingStore 落账本 + 读回
- 用户 halt 立即触发
- max_rounds 配置可定制
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from devflow.engine.dispatcher import (
    CircuitBreaker,
    DispatchConfig,
    RulingRef,
    RulingStore,
    RulingType,
)


class TestRulingStore:
    """RulingStore 落账本 + 读回"""

    def test_record_writes_to_ledger(self):
        """record() 应调 StorageBackend.append_ledger"""
        storage = MagicMock()
        storage.get_current_phase.return_value = 5
        ruling = RulingRef(task_id="t1", ruling_type=RulingType.SKIP, reason="user skip")

        store = RulingStore(storage)
        store.record(ruling)

        # 验证 append_ledger 被调用
        storage.append_ledger.assert_called_once()
        entry = storage.append_ledger.call_args.args[0]
        assert entry.task_id == "t1"
        assert entry.action.value == "ruling"
        assert entry.details == "Ruling: skip"
        assert entry.reason == "user skip"
        assert entry.phase == 5

    def test_has_halt_when_present(self):
        """账本有 halt 裁决时 has_halt() 返回 True"""
        storage = MagicMock()
        storage.get_ledger.return_value = {
            "entries": [
                {"task_id": "t1", "details": "Ruling: halt", "reason": "user halt"},
            ]
        }
        store = RulingStore(storage)
        assert store.has_halt("t1") is True
        assert store.has_halt("t2") is False

    def test_get_halt_returns_latest(self):
        """get_halt() 返回最新 halt 裁决"""
        storage = MagicMock()
        storage.get_ledger.return_value = {
            "entries": [
                {"task_id": "t1", "details": "Ruling: skip", "reason": "old"},
                {"task_id": "t1", "details": "Ruling: halt", "reason": "latest halt"},
                {"task_id": "t1", "details": "Ruling: skip", "reason": "newer"},
            ]
        }
        store = RulingStore(storage)
        halt = store.get_halt("t1")
        assert halt is not None
        assert halt.reason == "latest halt"

    def test_get_halt_when_absent(self):
        """无 halt 时返回 None"""
        storage = MagicMock()
        storage.get_ledger.return_value = {"entries": []}
        store = RulingStore(storage)
        assert store.get_halt("t1") is None


class TestCircuitBreaker:
    """CircuitBreaker 5 轮断路器"""

    def _make_breaker(self, max_rounds: int = 5, halt: bool = False) -> CircuitBreaker:
        config = DispatchConfig(max_rounds=max_rounds)
        storage = MagicMock()
        storage.get_ledger.return_value = {
            "entries": (
                [{"task_id": "t1", "details": "Ruling: halt", "reason": "user halt"}]
                if halt else []
            )
        }
        store = RulingStore(storage)
        return CircuitBreaker(config, store)

    def test_should_stop_returns_none_under_max(self):
        """未达最大轮次时应继续"""
        breaker = self._make_breaker(max_rounds=5)
        for round_num in [1, 2, 3, 4]:
            assert breaker.should_stop("t1", round_num) is None

    def test_should_stop_escalates_at_max(self):
        """达到最大轮次时返回 escalate 裁决"""
        breaker = self._make_breaker(max_rounds=5)
        ruling = breaker.should_stop("t1", 5)
        assert ruling is not None
        assert ruling.ruling_type == RulingType.ESCALATE
        assert "超过最大轮次" in ruling.reason

    def test_should_stop_halt_takes_priority(self):
        """用户 halt 优先于断路器"""
        breaker = self._make_breaker(max_rounds=5, halt=True)
        ruling = breaker.should_stop("t1", 1)  # 即使第 1 轮
        assert ruling is not None
        assert ruling.ruling_type == RulingType.HALT

    def test_custom_max_rounds(self):
        """max_rounds 可定制"""
        breaker = self._make_breaker(max_rounds=3)
        assert breaker.should_stop("t1", 2) is None
        ruling = breaker.should_stop("t1", 3)
        assert ruling.ruling_type == RulingType.ESCALATE