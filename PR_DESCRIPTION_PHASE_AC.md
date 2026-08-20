# PR Description — refactor(storage): split FSBackend + add MemoryStorageBackend for tests

> **Status**: DRAFT — review before commit.
> **Branch**: not yet committed (run `git add` + `git commit` after review).

---

## Title

```
refactor(storage): split FSBackend + add MemoryStorageBackend for tests
```

## Body

### Phase A — Engine layer discipline

- `src/devflow/cli.py`: encapsulate `FSBackend` construction in a single
  `_get_storage()` helper. The CLI facade is the **only** production-code
  instantiation site for the concrete `FSBackend`.
- `src/devflow/cli.py`: `_get_machine()` and `_get_review_engine()` now
  type-annotate the abstract `StorageBackend`. Runtime is unchanged.
- `src/devflow/engine/checkpoint.py`: signature abstracted from
  `FSBackend` → `StorageBackend`. (Consistency — other engine modules
  (`state_machine`, `review_engine`, `redline_auditor`) already used the
  abstract type.)
- 4 CLI glob sites in `cli.py` (`archive` / `list_active` / `list_archived` /
  `find`) keep `FSBackend(root) # noqa: needs concrete specs_dir; Phase C
  candidate` — they reach into `storage.specs_dir.glob()`. Phase C will
  remove the leak once `MemoryStorageBackend` and `FSBackend` both expose
  a path-agnostic listing helper, or those sites switch to
  `list_specs()` + `read_spec()`.

### Phase C — Test layer offline

- **New file** `src/devflow/storage/memory_backend.py` — `MemoryStorageBackend`,
  a `StorageBackend` implementation for fixture use. 168 lines including
  full module docstring covering the four design trade-offs:
  1. No lock, no atomic write, no SHA256 chain (memory ops are atomic).
  2. `verify_ledger()` returns `ok=True` (no physical medium to tamper).
  3. `write_spec`/`write_plan` return virtual `Path` shapes
     (e.g. `root/specs/<id>.yaml`) for drop-in compat.
  4. Hash chain is not maintained — fixture assertions should compare
     `entries.count` and entry content, not chain bytes.
- `src/devflow/storage/__init__.py`: re-exports `MemoryStorageBackend`.
- `src/devflow/policy/loader.py`: adds `load_sop_from_text(content)`
  helper. Fixtures no longer need a real `sop.yaml` on disk to bootstrap
  config; they pass the YAML text directly.
- **5 fixtures switched to `MemoryStorageBackend`**:

  | File | Tests | Time |
  |---|---|---|
  | `tests/test_state_machine.py` | 19 | 0.62s |
  | `tests/test_thinking_rules.py` | 9 | 0.58s |
  | `tests/test_v031_r2.py` | 7 | 0.53s |
  | `tests/test_v032.py` | 11 | 0.62s |
  | `tests/test_p2_fixes.py` (1 exception) | 6 | 0.71s |

  Total: **52 tests offline**, **162/162 PASS in 13.29s**
  (vs 16.13s pre-Phase-C, ~18% faster).

### Exception tests — kept on `FSBackend`

These tests specifically validate filesystem behavior, so they retain
`FSBackend(tmp_path)`:

- `tests/test_acceptance.py` — MVP Done contract (13 tests).
  Includes `test_1_init_generates_files` which asserts
  `(root / "sop.yaml").exists()`.
- `tests/test_p0_fixes.py` — Round-3 fixes (12 tests).
  Tests hash chain breakage detection, file lock semantics, atomic-write
  rollback. These are **the** semantic invariants of `FSBackend`.
- `tests/test_simple_archive.py` (23 tests) — user-mandated exception.
  Hash field whitelist + archive ledger invariants.
- `tests/test_review_loop.py` (20 tests) — asserts
  `(root / "review/<spec_id>/r<N>.yaml").exists()` after `engine.review()`.
  This requires `ReviewStore` to land YAML on disk. Making `ReviewStore`
  pluggable is **out of Phase C scope** (see Plan B in
  `docs/optimization-v0.1.md` Reco 2 — added in this PR).
- `tests/integration/test_handoff_e2e.py` + `test_wizard_e2e.py` (14 tests) —
  e2e tests whose docstrings say *"聚焦链路级 + 真实文件落地行为"*.
- `tests/test_p2_fixes.py::test_p2_resume_detects_missing_spec` — new
  `fs_env` fixture. The test deliberately unlinks a Spec file mid-test
  to verify P2-19 resume consistency. This is intrinsically disk-only.

### Files changed

```
docs/audit-ledger.md                                           |  (pre-existing diff)
docs/first-principles-sop.md                                   |  (pre-existing diff)
src/devflow/cli.py                                             |  75 ++ --
src/devflow/engine/checkpoint.py                               |   4 +-
src/devflow/engine/review_engine.py                            |  (pre-existing diff)
src/devflow/engine/state_machine.py                            |  (pre-existing diff)
src/devflow/policy/loader.py                                   |  14 +
src/devflow/storage/__init__.py                                |   9 +-
src/devflow/storage/memory_backend.py                          |  168 (NEW)
tests/test_p2_fixes.py                                         |  32 ++ --
tests/test_review_loop.py                                      |   6 +
tests/test_state_machine.py                                    | 191 ++ +-
tests/test_thinking_rules.py                                   |  15 +-
tests/test_v031_r2.py                                          |   9 +-
tests/test_v032.py                                             |   9 +-
docs/optimization-v0.1.md                                      |  +Reco 2 (this PR)
```

### Plan B — deferred (do NOT do in this PR)

- **v0.4 RFC §3 storage_backend_split** — splitting
  `FileStore / LedgerStore / StateStore`. Two open questions that v0.4
  RFC §3 did NOT answer:
  1. Cross-store write ordering protocol.
  2. How `hash chain` survives a cross-store transaction.
  Evidence: `docs/v0.4-rfc.md` hyperedge *"v0.4 Falsified Core Designs (6th
  Audit Round)"* + `docs/v0.4-roadmap-paused.md`. The plan stays paused.
- **Making `ReviewStore` pluggable** — natural next step after this PR.
  Added as `Reco 2 (P1, deferred)` to `docs/optimization-v0.1.md` in this
  PR. **Trigger condition**: ReviewStore's path coupling becomes a
  fixture bottleneck on multiple test files at once (currently only
  `test_review_loop.py` hits the wall).

### Graph evidence

After next `/graphify --update`:

- New node `src_devflow_storage_memory_backend_memorystoragebackend`
- New edges:
  - `MemoryStorageBackend --inherits--> StorageBackend`
  - `cli.py --imports--> storage/base.py` (NEW; previously only
    `cli.py --imports--> fs_backend.py`)
  - 21 new `method` edges inside C7 (one per abstract method)
- C7 (FS storage community) node count: **8 → ~29**.
- Expected C7 cohesion: **0.08 → higher** (two implementations +
  shared method contract vs prior "orphan + abstract doc").

`git log -p --follow src/devflow/storage/memory_backend.py` will
eventually carry this commit. Rerun `/graphify explain MemoryStorageBackend`
in next agent session to verify community placement.

### Audit trail

- Phase A derived from `graphify-out/memory/query_*.md` (saved via
  `graphify save-result` in prior session).
- Phase C derived from the user's choice between
  `MemoryStorageBackend` vs `InMemoryStorage` (chose the former for
  symmetry with `FSBackend`).
- Tests on FSBackend exception list chosen via:
  1. User-mandated `test_simple_archive`.
  2. Audit-ledger 6th-round evidence — hash chain / lock invariants
     cannot be tested in memory.
  3. Engine-level fixtures that already work via the abstract
     interface after `_HASH_FIELDS` independent paths.

---

## Suggested commit message

```
refactor(storage): split FSBackend concrete + add MemoryStorageBackend

Phase A: Engine layer discipline
- cli.py: encapsulate FSBackend construction in _get_storage()
- cli.py: signatures abstract to StorageBackend
- checkpoint.py: signature abstract to StorageBackend

Phase C: Test layer offline
- new MemoryStorageBackend in storage/memory_backend.py
- storage/__init__: re-export MemoryStorageBackend
- policy/loader: add load_sop_from_text()
- 5 fixtures switched (state_machine, thinking_rules, v031_r2, v032, p2_fixes)

Results:
- 52 tests now use in-memory backend
- 162/162 PASS in 13.29s (was 16.13s, ~18% faster)
- 8 tests retain FSBackend (P0/MVP-contract/archive/review-disk-coupled)

Documentation:
- optimization-v0.1.md: add Reco 2 (ReviewStore pluggable, deferred)

Graph: after --update, C7 expands 8->29 nodes (FS + Memory both in same
community, cohesion 0.08 -> higher).
```
