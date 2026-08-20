#!/usr/bin/env python
"""research 子能力诊断脚本 (v0.4)

场景 A 验证工具: 在真实环境下探测 research 子能力是否工作。

输出:
  1. 平台探测结果 (Claude Code / WorkBuddy / CodeBuddy / CLI)
  2. agent-reach skill 可用性
  3. 各 backend health_check 结果
  4. 实际跑一次 research(若有 spec_id)
  5. 落盘报告路径 + Spec.research_refs 状态

用法:
  python scripts/diagnose_research.py [query]
  python scripts/diagnose_research.py "python retry library"
  python scripts/diagnose_research.py "python retry" --spec-id 20260821-test

退出码:
  0 = 所有探测通过(可能有 fallback,但不阻断)
  1 = 工作区未初始化 / sop.yaml 缺失
  2 = 无活跃 Spec 且未指定 --spec-id
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

# 让 scripts/ 能找到 src/devflow
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT / "src"))


def section(title: str) -> None:
    """打印分节标题"""
    print(f"\n{'=' * 70}")
    print(f"  {title}")
    print("=" * 70)


def detect_platform() -> str:
    """探测当前 Agent 平台"""
    section("1. 平台探测")
    env_signals = {
        "CLAUDE_CODE": os.environ.get("CLAUDE_CODE"),
        "WORKBUDDY_RUNTIME": os.environ.get("WORKBUDDY_RUNTIME"),
        "CODEBUDDY_RUNTIME": os.environ.get("CODEBUDDY_RUNTIME"),
        "DEVFLOW_MCP_HOST": os.environ.get("DEVFLOW_MCP_HOST"),
    }
    for k, v in env_signals.items():
        marker = "  [+]" if v else "  [-]"
        print(f"{marker} {k}={v!r}")

    detected = "CLI (兜底)"
    if env_signals["CLAUDE_CODE"]:
        detected = "Claude Code"
    elif env_signals["WORKBUDDY_RUNTIME"]:
        detected = "WorkBuddy"
    elif env_signals["CODEBUDDY_RUNTIME"]:
        detected = "CodeBuddy"
    elif env_signals["DEVFLOW_MCP_HOST"]:
        detected = "MCP Host"

    print(f"\n  -> 检测结果: {detected}")
    return detected


def probe_agent_reach_skill(workspace: Path) -> dict[str, Any]:
    """探测 agent-reach skill 是否可用"""
    section("2. agent-reach skill 探测")
    result = {
        "skill_files": [],
        "cli_commands": [],
        "env_signals": [],
        "overall": False,
    }

    # 信号 1: skill 文件
    skill_paths = [
        workspace / ".claude/skills/agent-reach/SKILL.md",
        workspace / ".workbuddy/skills/agent-reach/SKILL.md",
        workspace / ".codebuddy/skills/agent-reach/SKILL.md",
    ]
    for p in skill_paths:
        exists = p.exists()
        result["skill_files"].append({"path": str(p), "exists": exists})
        marker = "  [+]" if exists else "  [-]"
        print(f"{marker} {p.relative_to(workspace) if exists else p}")

    # 信号 2: 环境变量
    env = {
        "CLAUDE_CODE": os.environ.get("CLAUDE_CODE"),
        "WORKBUDDY_RUNTIME": os.environ.get("WORKBUDDY_RUNTIME"),
        "CODEBUDDY_RUNTIME": os.environ.get("CODEBUDDY_RUNTIME"),
    }
    for k, v in env.items():
        if v:
            result["env_signals"].append(k)
    print(f"\n  环境变量信号: {result['env_signals'] or '(none)'}")

    # 信号 3: CLI 命令
    import shutil
    for cmd in ["claude", "wb", "codebuddy"]:
        path = shutil.which(cmd)
        if path:
            result["cli_commands"].append(cmd)
            print(f"  [+] {cmd} 在 PATH: {path}")
    if not result["cli_commands"]:
        print("  [-] 无 agent-reach CLI 在 PATH")

    # 综合判定
    result["overall"] = bool(
        result["skill_files"] and any(s["exists"] for s in result["skill_files"])
    ) or bool(result["env_signals"]) or bool(result["cli_commands"])

    print(f"\n  -> AgentReachBackend.health_check() 预期: {result['overall']}")
    return result


def probe_backends(workspace: Path) -> dict[str, bool]:
    """探测 4 个 backend 的健康状态"""
    section("3. backend 健康探测")
    from devflow.adapters.research import (
        AgentReachBackend,
        GitHubSearchBackend,
        RegistryQueryBackend,
        WebSearchBackend,
    )

    results: dict[str, bool] = {}
    backends = [
        ("agent_reach", AgentReachBackend(workspace)),
        ("github", GitHubSearchBackend()),
        ("registry", RegistryQueryBackend()),
        ("web", WebSearchBackend()),
    ]
    for name, b in backends:
        try:
            ok = b.health_check()
        except Exception as e:
            ok = False
            print(f"  [-] {name}: health_check 抛异常: {e}")
        results[name] = ok
        marker = "  [+]" if ok else "  [-]"
        print(f"{marker} {name}")

    print("\n  -> 实际可用 backend:")
    for name, ok in results.items():
        if ok:
            print(f"    {name}")
    if not any(results.values()):
        print("    (全部不可用 - 预期 offline/无网络 环境)")
    return results


def run_real_research(
    workspace: Path, query: str, spec_id: str | None
) -> dict[str, Any]:
    """真实跑一次 research(不带 mock)"""
    section("4. 实际执行 research")
    from devflow.engine.research_runner import ResearchRunner
    from devflow.policy.loader import load_sop
    from devflow.storage.fs_backend import FSBackend

    sop_path = workspace / "sop.yaml"
    if not sop_path.exists():
        print(f"  [-] sop.yaml 不存在,无法跑 research")
        return {"ok": False, "message": "sop.yaml missing"}

    config = load_sop(sop_path)
    storage = FSBackend(workspace)

    # 取活跃 spec_id
    active_spec = storage.get_current_spec_id()
    target_spec = spec_id or active_spec
    if not target_spec:
        print(f"  [-] 无活跃 Spec(当前 current_spec_id={active_spec!r}),且未传 --spec-id")
        return {"ok": False, "message": "no active spec"}
    print(f"  -> 使用 spec_id: {target_spec}")

    runner = ResearchRunner(
        storage=storage,
        config=config.research,
        workspace_root=workspace,
    )
    from devflow.model.research import SourceType
    sources = [SourceType(s) for s in config.research.sources]

    print(f"  -> 查询: {query!r}")
    print(f"  -> 数据源: {[s.value for s in sources]}")
    print(f"  -> 超时: {config.research.timeout_per_source}s")
    print(f"\n  执行中...")

    result = runner.run(
        query=query,
        spec_id=target_spec,
        sources=sources,
    )

    print(f"\n  结果:")
    print(f"    ok: {result['ok']}")
    print(f"    citations_count: {result['citations_count']}")
    print(f"    sources_used: {result['sources_used']}")
    print(f"    sources_failed: {result['sources_failed']}")
    print(f"    fallback_used: {result['fallback_used']}")
    print(f"    message: {result['message']}")
    if result.get("report_path"):
        print(f"    report_path: {result['report_path']}")
        full = workspace / result["report_path"]
        if full.exists():
            print(f"    report_size: {full.stat().st_size} bytes")

    return result


def verify_spec_update(workspace: Path, spec_id: str) -> None:
    """验证 Spec.research_refs 增量"""
    section("5. Spec.research_refs 验证")
    from devflow.storage.fs_backend import FSBackend

    storage = FSBackend(workspace)
    spec_data = storage.read_spec(spec_id)
    if spec_data is None:
        print(f"  [-] Spec '{spec_id}' 不存在")
        return

    refs = spec_data.get("research_refs", [])
    print(f"  research_refs 长度: {len(refs)}")
    if refs:
        print(f"  最新一条:")
        last = refs[-1]
        for k in ["path", "summary", "sources", "trust_level",
                  "generated_at", "citations_count"]:
            v = last.get(k, "(missing)")
            print(f"    {k}: {v}")


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="research 子能力诊断")
    parser.add_argument("query", nargs="?", default="python retry library",
                        help="调研查询关键词")
    parser.add_argument("--spec-id", default=None,
                        help="关联 Spec ID(默认取活跃 Spec)")
    parser.add_argument("--workspace", "-w", default=None,
                        help="工作区路径(默认当前 cwd)")
    args = parser.parse_args()

    workspace = Path(args.workspace).resolve() if args.workspace else Path.cwd()

    print(f"DevFlow research 诊断 (v0.4)")
    print(f"工作区: {workspace}")
    print(f"Python:  {sys.version.split()[0]}")

    # 检查工作区
    if not (workspace / "sop.yaml").exists():
        print(f"\n[-] sop.yaml 不存在,请先 'devflow init' 或传 --workspace")
        return 1

    detect_platform()
    probe_agent_reach_skill(workspace)
    probe_backends(workspace)

    result = run_real_research(workspace, args.query, args.spec_id)

    if result.get("ok") and result.get("report_path"):
        # 找 spec_id(优先用 cli 参数 / 活跃 spec / 从 report_path 推断)
        from devflow.storage.fs_backend import FSBackend
        storage = FSBackend(workspace)
        spec_id = args.spec_id or storage.get_current_spec_id()
        if spec_id:
            verify_spec_update(workspace, spec_id)

    # 退出码
    if not result.get("ok"):
        # 失败但 fallback=skip 时不算错
        if "全部 backend 失败" in str(result.get("message", "")) and \
           os.environ.get("DEVFLOW_FALLBACK_SKIP") == "1":
            print("\n-> 全部 backend 失败但 fallback=skip,不算错误")
            return 0
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())