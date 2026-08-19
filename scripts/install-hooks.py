#!/usr/bin/env python3
"""install-hooks.py - one-shot install of DevFlow repo git hooks

Installs graphify's post-commit / post-checkout / merge driver so that
every `git commit` automatically incrementally rebuilds the knowledge
graph (graphify-out/).

Usage:
    python scripts/install-hooks.py              # install
    python scripts/install-hooks.py --check      # check status
    python scripts/install-hooks.py --uninstall  # uninstall

Requires:
    graphify CLI on PATH (`graphify hook install`).
    Install: uv tool install graphifyy  or  pip install graphifyy
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Windows console defaults to GBK; force UTF-8 output to avoid
# UnicodeEncodeError on non-ASCII characters.
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def _run_graphify(args: list[str]) -> int:
    """Invoke the graphify CLI; return its exit code."""
    graphify_bin = shutil.which("graphify")
    if graphify_bin is None:
        print(
            "[install-hooks] ERROR: graphify CLI not found.\n"
            "  Install it first: uv tool install graphifyy  or  pip install graphifyy\n"
            "  (or add its bin dir to PATH) and retry.",
            file=sys.stderr,
        )
        return 1
    print(f"[install-hooks] using graphify: {graphify_bin}")
    proc = subprocess.run(
        [graphify_bin, *args],
        cwd=str(REPO_ROOT),
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
    )
    if proc.stdout:
        print(proc.stdout, end="")
    for line in (proc.stderr or "").splitlines():
        # Skip skill-version noise (e.g. "skill is from graphify 0.9.x")
        if "warning:" in line and ("skill" in line or "package" in line):
            continue
        print(line, file=sys.stderr)
    return proc.returncode


def main() -> int:
    args = sys.argv[1:]
    if "--check" in args:
        return _run_graphify(["hook", "status"])
    if "--uninstall" in args:
        return _run_graphify(["hook", "uninstall"])

    # Default: install (idempotent - graphify reports "already installed" harmlessly)
    print("[install-hooks] installing graphify hooks (post-commit / post-checkout / merge driver)...")
    code = _run_graphify(["hook", "install"])
    if code != 0:
        print("[install-hooks] install failed; see errors above.", file=sys.stderr)
        return code

    print()
    print("[install-hooks] OK. Behaviour:")
    print("  - every git commit incrementally rebuilds the knowledge graph")
    print("    (code changes only; runs detached in background)")
    print("  - rebase/merge/cherry-pick are skipped automatically")
    print("  - manual refresh for doc changes: graphify update .")
    print("  - skip the hook: GRAPHIFY_SKIP_HOOK=1 git commit")
    print("  - rebuild log: ~/.cache/graphify-rebuild.log")
    return 0


if __name__ == "__main__":
    sys.exit(main())
