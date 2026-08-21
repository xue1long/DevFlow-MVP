"""ResearchRunner — 调研编排 (v0.4 RFC §5 + v0.4.1 bug fix)

职责:
  1. 按 SOP 配置选择 backend 链(select_backends)
  2. 并发执行各 backend(各 backend 独立超时)
  3. 合并结果 + URL 去重
  4. 截断到 max_total_chars
  5. 落盘 Markdown
  6. 更新 Spec.research_refs(追加,不覆盖)
  7. 写账本(action=research)

v0.4.1 fix(post-v0.4-research-diagnosis.md):
  - sources_used/failed 改为 backend 名字维度(原 source_type 维度在多 backend
    共享 source_type 时会出现 used 与 failed 同时出现的矛盾)
  - 新增 backends_empty 区分"异常失败"与"空结果"
  - run() 返回 JSON 增 sources_in_results(从 citations 提取的真实来源)

失败策略:
  - 单 backend 异常 / 超时 -> backends_failed
  - 单 backend 健康但 0 命中 -> backends_empty(不算失败)
  - 全部 backend 失败 / 空 -> fallback=skip 时返回空报告(不阻断流程)
                            -> fallback=error 时返回 ok=False
  - Spec 不存在 -> 跳过更新 Spec,仅落盘报告 + 账本
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, wait
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ..adapters.research import (
    ResearchBackend,
    select_backends,
)
from ..model.ledger import LedgerAction, LedgerEntry
from ..model.research import (
    Citation,
    ResearchQuery,
    ResearchReport,
    SourceType,
)
from ..model.spec import Spec
from ..policy.loader import ResearchConfig
from ..storage.base import StorageBackend


class ResearchRunner:
    """调研编排器"""

    def __init__(
        self,
        storage: StorageBackend,
        config: ResearchConfig,
        workspace_root: Path,
    ):
        self.storage = storage
        self.config = config
        self.workspace_root = Path(workspace_root)

    def run(
        self,
        query: str,
        spec_id: str,
        sources: Optional[list[SourceType]] = None,
    ) -> dict:
        """执行调研主入口

        Args:
            query: 调研关键词
            spec_id: 关联 Spec ID(用于更新 spec.research_refs + 账本)
            sources: 数据源列表(None 时走 SOP 默认)

        Returns:
            dict: 结构化结果
              - ok: True/False
              - report_path: 报告 Markdown 路径
              - citations_count: 引用条数
              - backends_used: 实际产出引用的 backend 名字列表
              - backends_failed: 异常 / 超时的 backend 名字列表
              - backends_empty: 健康但 0 命中的 backend 名字列表
              - sources_in_results: citations 中实际出现的 source_type 去重列表
              - fallback_used: 是否触发多 backend 串联
              - message: 人类可读摘要
              - citations: 引用列表(供 CLI 输出)
              - sources_used: deprecated,保留向后兼容(== backends_used 转 source_type)
              - sources_failed: deprecated,保留向后兼容(== backends_failed)
        """
        # 1. 构造 ResearchQuery
        resolved_sources = (
            sources
            if sources is not None
            else [SourceType(s) for s in self.config.sources]
        )
        rq = ResearchQuery(
            query=query,
            sources=resolved_sources,
            max_results_per_source=self.config.max_results_per_source,
            max_total_chars=self.config.max_total_chars,
            timeout_per_source=self.config.timeout_per_source,
            spec_id=spec_id,
        )

        # 2. 选择 backend 链(含 health_check)
        backends = select_backends(
            self.workspace_root,
            [s.value for s in resolved_sources],
            include_unhealthy=False,
        )
        # 全失败时降级:保留所有 backend,runtime 阶段记录失败
        if not backends:
            backends = select_backends(
                self.workspace_root,
                [s.value for s in resolved_sources],
                include_unhealthy=True,
            )

        if not backends:
            return self._report_failure(
                spec_id=spec_id,
                query=query,
                reason="无可用 backend(可能 sources 配置无对应实现)",
            )

        # 3. 并发执行(v0.4.1:返回 backend 名字维度)
        (
            all_citations,
            backends_used,
            backends_failed,
            backends_empty,
            backend_chain,
        ) = self._execute_backends(backends, rq)

        # 4. URL 去重(保留首次出现顺序)
        unique = self._dedupe_by_url(all_citations)

        # 5. 截断到 max_total_chars
        trimmed, total_chars = self._truncate_by_chars(
            unique, rq.max_total_chars
        )

        # 6. fallback 判定:实际执行的 backend 数 > 1 即触发 fallback
        fallback_used = len(backend_chain) > 1

        # 7. 提取 citations 中实际出现的 source_type(v0.4.1 新增)
        sources_in_results = sorted({
            c.source_type.value for c in trimmed
        })

        # 8. 全部失败且 SOP 配 error -> 返回 ok=False
        # v0.4.1: 判定标准改为"全部 backend 都失败或空"
        if not backends_used and self.config.fallback == "error":
            return self._report_failure(
                spec_id=spec_id,
                query=query,
                reason=(
                    f"全部 backend 未产出引用,"
                    f"failed={backends_failed}, empty={backends_empty}"
                ),
            )

        # 9. 构造报告(v0.4.1: 新增 backends_empty / sources_in_results)
        # backward compat: sources_used / sources_failed 保留(填 source_type 值)
        # 给前端兼容,新代码读 backends_*
        report = ResearchReport(
            spec_id=spec_id,
            query=query,
            citations=trimmed,
            sources_used=[],  # deprecated,改用 backends_used
            sources_failed=[],  # deprecated,改用 backends_failed
            fallback_used=fallback_used,
            total_chars=total_chars,
            backend_chain=backend_chain,
            generated_at=datetime.now(timezone.utc),
        )

        # 10. 落盘报告
        report_path = self._write_report(report)

        # 11. 更新 Spec.research_refs(v0.4.1:用 backend 名字 + sources_in_results)
        self._update_spec(
            spec_id, report, report_path,
            backends_used=backends_used,
            backends_failed=backends_failed,
            backends_empty=backends_empty,
            sources_in_results=sources_in_results,
        )

        # 12. 写账本(v0.4.1: 用 backend 名字)
        self._append_ledger(
            spec_id, report,
            backends_used=backends_used,
            backends_failed=backends_failed,
            backends_empty=backends_empty,
        )

        return {
            "ok": True,
            "report_path": self._relpath(report_path),
            "citations_count": len(trimmed),
            # v0.4.1 新字段(权威)
            "backends_used": backends_used,
            "backends_failed": backends_failed,
            "backends_empty": backends_empty,
            "sources_in_results": sources_in_results,
            "fallback_used": fallback_used,
            "message": (
                f"调研完成,{len(trimmed)} 条引用"
                + (" (fallback 已触发)" if fallback_used else "")
                + (
                    " (全部 backend 未产出引用,fallback=skip)"
                    if not backends_used else ""
                )
            ),
            "citations": [
                {
                    "url": c.url,
                    "title": c.title,
                    "source": c.source_type.value,
                    "trust": c.trust_level.value,
                }
                for c in trimmed
            ],
            # v0.4.1 deprecated 字段(向后兼容)
            # 旧字段反映 source_type 维度,会有 used/failed 重复的问题
            # 新代码应读 backends_used / backends_failed
            "sources_used": sorted({
                # 从 backend 名字反推(只标 hit 的)
                b.source_type.value
                for b in backends
                if b.name in backends_used
            }),
            "sources_failed": sorted({
                b.source_type.value
                for b in backends
                if b.name in backends_failed
            }),
        }

    # ---- 内部方法 ----

    def _execute_backends(
        self,
        backends: list[ResearchBackend],
        query: ResearchQuery,
    ) -> tuple[
        list[Citation], list[str], list[str], list[str], list[str]
    ]:
        """并发跑全部 backend,收集结果(v0.4.1: 5 元组 backend 名字维度)

        Returns:
            (citations, used_backends, failed_backends, empty_backends, chain)
            - used_backends: 实际产出引用的 backend 名字
            - failed_backends: 异常 / 超时的 backend 名字
            - empty_backends: 健康但 0 命中的 backend 名字(不算失败)
            - chain: 全部 backend 名字(按完成顺序)

        总超时 = (timeout_per_source + 2) * len(backends),确保最坏情况下
        整体完成时间有上界(避免被慢 backend 卡死)
        """
        all_citations: list[Citation] = []
        used_backends: list[str] = []
        failed_backends: list[str] = []
        empty_backends: list[str] = []
        backend_chain: list[str] = []

        # 总超时上限:每个 backend 单独超时 + 缓冲,再乘以 backend 数
        overall_timeout = (query.timeout_per_source + 2) * len(backends)

        pool = ThreadPoolExecutor(max_workers=len(backends))
        try:
            future_to_backend = {
                pool.submit(self._safe_search, b, query): b
                for b in backends
            }
            # 关键:用 wait(timeout=...) 强制整体超时,不等所有完成
            done, not_done = wait(
                future_to_backend.keys(),
                timeout=overall_timeout,
            )

            for fut in done:
                b = future_to_backend[fut]
                backend_chain.append(b.name)
                try:
                    citations = fut.result()
                except Exception:
                    # 异常 -> failed
                    if b.name not in failed_backends:
                        failed_backends.append(b.name)
                    continue

                if citations:
                    all_citations.extend(citations)
                    if b.name not in used_backends:
                        used_backends.append(b.name)
                else:
                    # 空结果 -> empty(不算失败)
                    if b.name not in empty_backends:
                        empty_backends.append(b.name)

            # 未完成的 future 视为超时失败
            for fut in not_done:
                b = future_to_backend[fut]
                backend_chain.append(b.name)
                fut.cancel()
                if b.name not in failed_backends:
                    failed_backends.append(b.name)
        finally:
            # 关键:不等待未完成的线程(它们仍在跑但 runner 已返回)
            pool.shutdown(wait=False)

        return (
            all_citations,
            used_backends,
            failed_backends,
            empty_backends,
            backend_chain,
        )

    @staticmethod
    def _safe_search(
        backend: ResearchBackend, query: ResearchQuery
    ) -> list[Citation]:
        """包裹 backend.search, 区分"返回空"与"异常失败"

        v0.4.1 fix(post-v0.4-research-diagnosis.md):
          异常应让 runner 看到(except 块捕获),否则失败的 backend
          被误归为 empty(失去诊断信号)。返回空 list 是 backend 的合法结果。
        """
        result = backend.search(query)
        if not isinstance(result, list):
            raise TypeError(
                f"backend {backend.name} 返回非 list: {type(result).__name__}"
            )
        return result

    @staticmethod
    def _dedupe_by_url(
        citations: list[Citation],
    ) -> list[Citation]:
        """URL 去重,保留首次出现顺序

        注意: 因 backend 是并发执行,citations 列表的顺序可能不稳定。
        多次跑同一 query 时结果顺序可能略有不同——这是并发语义下的可接受 trade-off,
        调用方不应依赖排序。
        """
        seen: set[str] = set()
        out: list[Citation] = []
        for c in citations:
            if not c.url or c.url in seen:
                continue
            seen.add(c.url)
            out.append(c)
        return out

    @staticmethod
    def _truncate_by_chars(
        citations: list[Citation], max_chars: int
    ) -> tuple[list[Citation], int]:
        """按字符数截断(URL + title + snippet 之和)"""
        out: list[Citation] = []
        total = 0
        for c in citations:
            size = len(c.snippet) + len(c.title) + len(c.url)
            if total + size > max_chars:
                break
            out.append(c)
            total += size
        return out, total

    def _write_report(self, report: ResearchReport) -> Path:
        """落盘 Markdown 报告"""
        research_dir = self.workspace_root / "docs" / "devflow" / "research"
        research_dir.mkdir(parents=True, exist_ok=True)
        ts = report.generated_at.strftime("%Y%m%d-%H%M%S")
        path = research_dir / f"{report.spec_id}-{ts}.md"
        path.write_text(report.to_markdown(), encoding="utf-8")
        return path

    def _update_spec(
        self,
        spec_id: str,
        report: ResearchReport,
        report_path: Path,
        backends_used: Optional[list[str]] = None,
        backends_failed: Optional[list[str]] = None,
        backends_empty: Optional[list[str]] = None,
        sources_in_results: Optional[list[str]] = None,
    ) -> None:
        """更新 Spec.research_refs(追加,不覆盖)

        v0.4.1: 新增 backends_used/failed/empty + sources_in_results 字段
        (取代旧的 sources 字段)

        - 若 Spec 不存在:静默跳过(报告已落盘 + 账本已记录)
        - 若 Spec 已存在:append 一条 ref 条目
        """
        spec_data = self.storage.read_spec(spec_id)
        if spec_data is None:
            return
        try:
            spec = Spec(**spec_data)
        except Exception:
            return

        # 计算 trust_level:任一 HIGH 引用则标 high
        if report.has_high_trust():
            trust = "high"
        elif report.citations:
            trust = "medium"
        else:
            trust = "unknown"

        ref_entry: dict = {
            "path": self._relpath(report_path),
            "summary": report.summary[:200] if report.summary else "",
            "trust_level": trust,
            "generated_at": report.generated_at.isoformat(),
            "citations_count": len(report.citations),
        }

        # v0.4.1: backend 维度的来源追溯
        if backends_used is not None:
            ref_entry["backends_used"] = backends_used
        if backends_failed is not None:
            ref_entry["backends_failed"] = backends_failed
        if backends_empty is not None:
            ref_entry["backends_empty"] = backends_empty
        if sources_in_results is not None:
            ref_entry["sources_in_results"] = sources_in_results

        spec.research_refs.append(ref_entry)
        try:
            self.storage.write_spec(
                spec_id, spec.model_dump(mode="json")
            )
        except Exception:
            # Spec 写回失败不阻断(报告已落盘)
            pass

    def _append_ledger(
        self,
        spec_id: str,
        report: ResearchReport,
        backends_used: Optional[list[str]] = None,
        backends_failed: Optional[list[str]] = None,
        backends_empty: Optional[list[str]] = None,
    ) -> None:
        """写账本(action=research)

        v0.4.1: 用 backend 名字 + 区分 used/failed/empty
        """
        used = backends_used if backends_used is not None else []
        failed = backends_failed if backends_failed is not None else []
        empty = backends_empty if backends_empty is not None else []
        details = (
            f"backends_used=[{','.join(used)}] "
            f"backends_failed=[{','.join(failed)}] "
            f"backends_empty=[{','.join(empty)}] "
            f"citations={len(report.citations)} "
            f"fallback={'used' if report.fallback_used else 'no'} "
            f"backend={'->'.join(report.backend_chain)}"
        )
        try:
            self.storage.append_ledger(LedgerEntry(
                phase=2,  # plan 阶段
                action=LedgerAction.RESEARCH,
                spec_id=spec_id,
                details=details,
            ))
        except Exception:
            # 账本写失败不阻断流程
            pass

    def _report_failure(
        self, spec_id: str, query: str, reason: str
    ) -> dict:
        """失败统一返回格式(v0.4.1: 新字段)"""
        return {
            "ok": False,
            "report_path": None,
            "citations_count": 0,
            "backends_used": [],
            "backends_failed": [],
            "backends_empty": [],
            "sources_in_results": [],
            "fallback_used": False,
            "message": f"调研失败:{reason}",
            "citations": [],
            # deprecated 字段(向后兼容)
            "sources_used": [],
            "sources_failed": [],
        }

    def _relpath(self, path: Path) -> str:
        """路径转相对工作区的字符串(便于 Spec 内嵌)"""
        try:
            return str(path.relative_to(self.workspace_root))
        except ValueError:
            return str(path)