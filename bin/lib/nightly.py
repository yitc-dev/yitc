"""Nightly verb-family for the yitc-v2 CLI — `nightly` (the bounded v2 methodology-nightly RUNNER,
SPEC-0105). The L1 SEED layer of v2 project-automation governance.

WHAT it does: enumerate `registry.yaml` projects whose `methodology == yitc_v2`, run READ-ONLY
governance/health checks on each (queue freshness + corpus/graph integrity), run the shared-store
backup-verify ONCE per run, then emit ONE per-run `nightly_run_completed` journal event carrying the
per-project results. It CHECKS and REPORTS only.

BOUNDED (CHARTER §6 fence / SPEC-0105 §2): the runner NEVER starts an autonomous work session, never
self-fetches a task, holds no stateful orchestration — the SAME fence as the orchestrate
controller-selector posture. It is a check-and-report runner, not an orchestrator.

READ-ONLY territory (D-0019): registry.yaml + every consumer path are read READ-ONLY (boundary /
provenance). The checks are pure file reads — the runner NEVER runs `graph build`/`conformance`
against a consumer (those WRITE the consumer's index + journal = a cross-territory write). The only
write the runner makes is the ONE `nightly_run_completed` append to the ENGINE's own journal.

ANTI-COMPLEXITY (CHARTER §P1 — reuse, do not invent parallel checks):
  * queue freshness  — REUSES lib.state.scan_tasks (read-only) + the QUEUE.md ready-queue cap (≤50).
  * corpus integrity — READS the EXISTING graph/index.json artifact (no parallel index) and compares
    its mtime against every corpus root `graph build` consumes (the audit-pre finding-0 freshness set).
  * frontend-errors  — FOLDS each project's ALREADY-DECLARED SPEC-0170 source through the EXISTING
    lib.frontend_errors conveyor (T-10803). The cadence obligation needed a provider-independent OS
    trigger (SPEC-0142); this runner already has one, so it costs one read-only check instead of a
    scheduler. It never DISCOVERS a source — only what a consumer declared and the preflight passes.
  * project-health   — RUNS the layers a project ALREADY DECLARED in its `verify.layers` and opted
    in via `verify.health.layers` (T-11359). It declares no command of its own and invents no second
    verify vocabulary; it reuses the carrier read (`state.load_ops`, the SPEC-0093 idiom) and the
    layer names. The land-time executor is deliberately not called: that path is land-only by
    construction (a `base_ref` for subject-glob skipping, a `prep:` dependency-tree WRITE, per-layer
    provenance against a base identity), and this module is a stdlib+lib.state leaf that never
    back-imports the host.
  * backup-verify    — RUNS the EXISTING bin/verify-backup.sh once per run (the shared coordination
    store). There is NO per-project backup mechanism to verify (per-project repos are git + offsite
    rsync backed); inventing one would be a parallel mechanism, so backup-verify is per-RUN.

Identity-agnostic KERNEL module (SPEC-0073 bin/ HARD class — travels with the engine). It imports only
stdlib + the already-extracted leaf lib.state; it NEVER back-imports the host. The host keeps a thin
argparse residue (`cmd_nightly` set_defaults entrypoint) that injects the host collaborators + path
globals the verb reads — the triage/dispatch/session precedent — so a `-C` rebind and every
`monkeypatch.setattr(yitc, …)` stay honored at call time.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import statistics
import subprocess
import time as _time
from pathlib import Path

from lib import state


# The active-queue cap (QUEUE.md §Active queue) — a ready-queue larger than this is an
# anti-complexity signal, surfaced as a `warn` by the queue-freshness check. NOT a gate.
_READY_CAP = 50

# A ready task older than this (days) flags the queue as stale (work piling up un-touched). A
# conservative threshold — surfacing, never blocking.
_STALE_READY_DAYS = 21

# SPEC-0143 Rule 4 (T-10173): the set of concern SECTIONS a PRE-EXISTING governed BLOCKING gate already
# blocks on — the ONLY concerns whose drift ESCALATES from the report-only reconcile to a governed
# `cross request`. Today just `security` (the deploy Class-S live-probe gate, SPEC-0098 / SPEC-0094,
# _classify_deploy_gate — "the deploy gate on stale/absent security evidence" of the SPEC-0143 example).
# This is NOT a new gate and NOT a stored review-request entity — it names WHICH existing gate-backed
# concern warrants escalation; every other drifting concern stays REPORT-ONLY (the card-C default). The
# set grows ONLY when a real new blocking gate lands (a registry `version`-style field was considered
# and rejected as over-engineering for one concrete instance — CHARTER §P1 F2/F4).
_GATE_BACKED_CONCERNS = frozenset({"security"})

# The corpus roots `graph build` consumes (graph.py: scan_specs/tasks/patterns/errors/scenarios/
# lessons/plans/decisions) — the freshness set for the corpus-integrity staleness check (audit-pre
# finding 0). If the index is OLDER than the newest file under any of these, the graph is stale.
_CORPUS_GLOBS = {
    "specs": "SPEC-*.yaml",
    "tasks": "T-*.yaml",
    "patterns": "*.md",
    "errors": "E-*.yaml",
    "scenarios": "*.md",
    "lessons": "*.md",
    "plans": "*.md",
    "ideas": "*.md",
    "decisions": "D-*.yaml",
}


def _engine_repo_root(engine_root: Path) -> Path:
    """The ROOT checkout of the repository `engine_root` belongs to — its primary worktree.

    `engine_root` is captured from the invocation location (bin/lib/cli.py `ENGINE_ROOT`), so when the
    CLI is invoked from a LINKED git worktree it names that worktree's leaf, not the repository. This
    resolves the leaf back to the repository's `main` checkout via `git worktree list --porcelain`
    (the same predicate the host's `_main_worktree` uses), so `_v2_projects` can tell a DIFFERENT
    engine install from THE SAME repository seen through a worktree.

    FAIL-SAFE BY CONSTRUCTION (T-11632): every failure — git absent, non-zero exit, not a repository,
    no `refs/heads/main` entry, timeout, OSError — returns `engine_root.resolve()`, which is exactly
    the value the caller compared against before this helper existed. So no environment can be made
    worse than it was; the helper can only ever ADD the worktree recognition. Both exits are absolute
    canonical paths, so the caller's comparison against an already-resolved registry path (and the
    T-9796 alias/relative recognition that rests on it) is preserved."""
    fallback = engine_root.resolve()
    try:
        r = subprocess.run(["git", "-C", str(engine_root), "worktree", "list", "--porcelain"],
                           capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return fallback
    if r.returncode != 0:
        return fallback
    cur = None
    for line in (r.stdout or "").splitlines():
        if line.startswith("worktree "):
            cur = line[len("worktree "):].strip()
        elif line.strip() == "branch refs/heads/main" and cur:
            try:
                return Path(cur).resolve()
            except OSError:
                return fallback
    return fallback


def _v2_projects(registry_path: Path, engine_root: Path, kernel_name: str) -> list:
    """Read registry_path (read-only) and return the ordered list of v2 projects:
    [{name, path}] for every entry whose `methodology == 'yitc_v2'`. A missing/invalid `path` is
    skipped (a malformed entry never aborts the run).

    Path resolution (T-9796): a `path` is resolved to an ABSOLUTE canonical path — a RELATIVE entry is
    resolved against the registry FILE's directory (`registry_path.parent`), NOT the process cwd, so the
    nightly reads the same project regardless of where it is invoked from.

    THE KERNEL ENTRY (T-11632) resolves from the REGISTRY like every other project whenever the entry
    names this engine's own repository — including when the CLI was invoked from a LINKED WORKTREE of
    it, which `_engine_repo_root` recognizes. Previously the kernel entry was UNCONDITIONALLY rebound
    to `engine_root`, so a hand-run from a worktree graded THE WORKTREE and reported it as the kernel
    repo's state: measured during T-11399, where repo-storage graded `ok` from a worktree while the
    kernel repo carried four gc.log files. Production cron runs from the main checkout, where the
    registry path IS `engine_root`, so that reading was correct and is byte-identical here.

    The rebind is NARROWED, not removed — it is retained for the case it was actually for: a
    name-matched entry that does NOT resolve to this engine's repository, i.e. a RELOCATED or TEST
    engine install (a harness that copies the engine into a temp dir under `YITC_REPO_ROOT` while the
    registry still names the live checkout). The docstring's former `-C` claim was inaccurate and is
    dropped: `ENGINE_ROOT` is captured at import BEFORE any `-C` rebind and `_rebind_repo_root` never
    touches it (bin/lib/cli.py), so `-C` never moved it. An entry whose RESOLVED path == this engine's
    repository is still treated as the kernel even under a NON-matching `kernel_name` (T-9796's
    alias case) — that recognition is unchanged, only the path it binds to is."""
    data = state.load_path(registry_path) or {}
    projects = data.get("projects") or {}
    reg_dir = registry_path.resolve().parent
    engine_repo = _engine_repo_root(engine_root)
    out: list = []
    for name, meta in projects.items():
        if not isinstance(meta, dict):
            continue
        if meta.get("methodology") != "yitc_v2":
            continue
        raw = meta.get("path")
        resolved = None
        if raw:
            p = Path(str(raw))
            resolved = (p if p.is_absolute() else reg_dir / p).resolve()
        if resolved is not None and resolved == engine_repo:
            # The entry names THIS engine's own repository — bind the REGISTRY path, like every other
            # project. From the main checkout this IS engine_root (production unchanged); from a linked
            # worktree it is the repository, which is the whole point of T-11632.
            path = resolved
        elif name == kernel_name:
            # The NARROWED rebind: name-matched but NOT this engine's repository = a relocated/test
            # engine install (the YITC_REPO_ROOT harness copy). Honor the actual install.
            path = engine_root
        elif resolved is not None:
            path = resolved
        else:
            continue
        out.append({"name": name, "path": path})
    return out


def _newest_mtime(directory: Path, pattern: str) -> float:
    """Newest mtime among `pattern` files directly under `directory` (read-only); 0.0 if none."""
    if not directory.is_dir():
        return 0.0
    newest = 0.0
    for p in directory.glob(pattern):
        try:
            m = p.stat().st_mtime
        except OSError:
            continue
        if m > newest:
            newest = m
    return newest


def _check_queue(proj_path: Path, *, now: _dt.datetime) -> dict:
    """Read-only queue-freshness check: status counts + ready-cap + oldest-ready age."""
    tasks_dir = proj_path / "tasks"
    if not tasks_dir.is_dir():
        return {"verdict": "skip", "reason": "no tasks/ dir"}
    counts: dict = {}
    oldest_ready_days = 0
    for tp in state.scan_tasks(tasks_dir):
        t = state.load_path(tp) or {}
        st = t.get("status") or "unknown"
        counts[st] = counts.get(st, 0) + 1
        if st == "ready":
            created = t.get("created_at")
            if created:
                try:
                    dtv = _dt.datetime.fromisoformat(str(created).replace("Z", "+00:00"))
                    age = (now - dtv).days
                    if age > oldest_ready_days:
                        oldest_ready_days = age
                except (ValueError, TypeError):
                    pass
    ready = counts.get("ready", 0)
    over_cap = ready > _READY_CAP
    stale = oldest_ready_days > _STALE_READY_DAYS
    verdict = "warn" if (over_cap or stale) else "ok"
    return {"verdict": verdict, "counts": counts, "ready": ready,
            "ready_over_cap": over_cap, "oldest_ready_age_days": oldest_ready_days}


def _check_corpus_integrity(proj_path: Path) -> dict:
    """Read-only corpus/graph integrity: the EXISTING graph/index.json present + parseable, and
    not staler than the newest corpus file `graph build` consumes (the finding-0 freshness set)."""
    index = proj_path / "graph" / "index.json"
    if not index.exists():
        return {"verdict": "missing", "reason": "graph/index.json absent"}
    errors: list = []
    parsed = state.load_path(index, errors=errors)
    if errors or not parsed:
        return {"verdict": "error", "reason": "graph/index.json unparseable"}
    try:
        index_mtime = index.stat().st_mtime
    except OSError:
        return {"verdict": "error", "reason": "graph/index.json unstat-able"}
    newest = 0.0
    newest_root = None
    for root, pattern in _CORPUS_GLOBS.items():
        m = _newest_mtime(proj_path / root, pattern)
        if m > newest:
            newest, newest_root = m, root
    stale = newest > index_mtime
    return {"verdict": "stale" if stale else "ok",
            "stale_root": newest_root if stale else None}


def _check_backup(backup_verify_sh: Path, *, dry_run: bool, _run) -> dict:
    """Run the EXISTING shared-store backup-verify ONCE per run. In dry-run it is SKIPPED (the
    script writes snapshot files + rotates backups — audit-pre finding 1: dry-run is fully
    read-only)."""
    if dry_run:
        return {"verdict": "skipped", "reason": "dry-run (no snapshot write)"}
    if not backup_verify_sh.exists():
        return {"verdict": "skip", "reason": "verify-backup.sh absent"}
    try:
        r = _run(["bash", str(backup_verify_sh)], capture_output=True, text=True, timeout=300)
    except Exception as exc:  # noqa: BLE001 — a runner fault must never abort the nightly
        return {"verdict": "error", "reason": f"{type(exc).__name__}: {exc}"}
    return {"verdict": "ok" if r.returncode == 0 else "fail", "exit_code": r.returncode}


def _check_conformance_surfaces(engine_root: Path, *, dry_run: bool, _run) -> dict:
    """T-11015 (SPEC-0177 rule 3): EXERCISE the engine's read-only conformance surfaces once per run.

    WHY THE NIGHTLY. A mechanism whose whole production surface is a read-only conformance verb writes
    nothing by design, so the only proof its guard actually fires is somebody RUNNING it. Run by its
    author at authoring time that is surface fidelity, not adoption (SPEC-0177 rule 2). Run HERE it is
    adoption in the CHARTER §P8 sense: a DIFFERENT actor, at a DIFFERENT time than the session that
    wrote the guard. The result is recorded on the ONE `nightly_run_completed` row this run already
    emits — a FIELD on an existing event, no new event, store or scheduler — where a closing card cites
    it as `nightly_run_completed@<ts>#surface=<verb>` (`lib/task.py::_resolve_scheduled_run_ref`).

    ENGINE-SCOPED BY CONSTRUCTION, and that is the whole territory story: this runs the surfaces against
    the ENGINE's own repo ONLY (the `_check_backup` once-per-run shape, deliberately NOT the per-project
    loop). This module's contract — never run `graph build`/`conformance` against a CONSUMER, because
    those write the consumer's index + journal (D-0019 cross-territory) — is therefore kept VERBATIM;
    there is no per-consumer call site to get it wrong. The engine's own journal is the one the runner
    already writes.

    The SURFACE SET is `lib.task._READ_ONLY_CONFORMANCE_SURFACES` — the SAME constant the evidence
    contract admits refs against (CHARTER §P5: one set, so "did a scheduled run exercise this surface?"
    can never disagree between the writer and the reader). Each entry's `argv` is exec'd as SEPARATE
    arguments; the label is prose and is never shell-split.

    Fail-safe, on the `_check_backup` / `_archive_transcripts` precedent: SKIPPED under --dry-run
    (read-only parity), and ANY runner fault is REPORTED, never aborting the nightly. Verdicts:
    `ok`/`fail` = the surface RAN (and that is what makes the row citable); `skip`/`error` = it did not.
    """
    if dry_run:
        return {"verdict": "skipped", "surfaces": [], "reason": "dry-run (read-only)"}
    cli = engine_root / "bin" / "yitc-v2"
    if not cli.exists():
        return {"verdict": "skip", "surfaces": [], "reason": f"engine CLI absent ({cli})"}
    from lib import task as _task   # lazy — the single surface-set SoT (the `init`/`cross` precedent)
    surfaces: list = []
    for label, entry in sorted(_task._READ_ONLY_CONFORMANCE_SURFACES.items()):
        try:
            r = _run([str(cli), *entry["argv"]], capture_output=True, text=True,
                     timeout=300, cwd=str(engine_root))
        except Exception as exc:  # noqa: BLE001 — a runner fault must never abort the nightly
            surfaces.append({"surface": label, "verdict": "error",
                             "reason": f"{type(exc).__name__}: {exc}"})
            continue
        surfaces.append({"surface": label, "exit_code": r.returncode,
                         "verdict": "ok" if r.returncode == 0 else "fail"})
    if any(s["verdict"] == "error" for s in surfaces):
        verdict = "error"
    elif any(s["verdict"] == "fail" for s in surfaces):
        verdict = "fail"
    else:
        verdict = "ok"
    return {"verdict": verdict, "surfaces": surfaces}


# T-11923: the mirror's SOURCE-SCOPE rule, as a WHITELIST of the one content class the duty exists to
# preserve — the provider's per-session TRANSCRIPT files (`*.jsonl` under the source root). Everything
# else beneath that source is out of scope BY CONSTRUCTION: the provider dir also holds the owner's
# protected `memory/` stores and per-session `tool-results/` caches, none of which a token-rollup reads.
# Whitelist, never a path blacklist — a sibling directory the provider adds LATER is covered with no
# second card, which a hardcoded exclusion could not do. `--include=*/` lets rsync DESCEND, and
# `--prune-empty-dirs` then drops every directory that carried no transcript, so a protected source dir
# is never CREATED at the destination and its mode is never copied. That is the whole fix for the
# obstruction class (`worktree park` failing on a read-only mirrored tree, 2026-08-31): the source
# protection is CORRECT and stays untouched — no chmod, no `--no-perms`, the content is simply not
# carried.
_TRANSCRIPT_MIRROR_FILTER = ["--prune-empty-dirs", "--include=*/", "--include=*.jsonl", "--exclude=*"]


def _archive_transcripts(src_dir: Path, archive_dir: Path, *, dry_run: bool, _run) -> dict:
    """T-10122 (SPEC-0105 §2a / SPEC-0135 §3): the transcript-archive DURABILITY duty — mirror the
    provider's per-session TRANSCRIPTS ONCE per run so a per-fork/per-session token-rollup survives the
    provider's ~30-day expiry. Idempotent `rsync -a <filter> <src>/ <dest>/` (no source deletion/
    transform — the lesson `provider-transcript-archive.md` craft, now automated here). Bounded
    local-evidence side-effect, NOT a work session (the §2 fence forbids autonomous WORK, not hygiene
    writes).

    SCOPE (T-11923): transcripts ONLY — `_TRANSCRIPT_MIRROR_FILTER` above carries the rule and why it is
    a whitelist. The DESTINATION is likewise a HOST-axis property, pinned to the engine's MAIN checkout
    by its caller (`cli.py#_transcript_archive_dir`), never the checkout that happened to invoke the run.

    Parity with `_check_backup`: SKIPPED under --dry-run (read-only). Fail-safe — a missing source or
    any runner fault is REPORTED, never aborts the nightly. Returns {verdict, archived?, reason?}."""
    if dry_run:
        return {"verdict": "skipped", "reason": "dry-run (no archive mirror write)"}
    if not src_dir.is_dir():
        return {"verdict": "skip", "reason": f"provider transcript source absent ({src_dir})"}
    try:
        archive_dir.mkdir(parents=True, exist_ok=True)
        # trailing slash on src → mirror the CONTENTS into dest (rsync semantics), matching the lesson.
        r = _run(["rsync", "-a", *_TRANSCRIPT_MIRROR_FILTER, f"{src_dir}/", f"{archive_dir}/"],
                 capture_output=True, text=True, timeout=300)
    except Exception as exc:  # noqa: BLE001 — a mirror fault must never abort the nightly (backup parity)
        return {"verdict": "error", "reason": f"{type(exc).__name__}: {exc}"}
    archived = len(list(archive_dir.glob("*/*.jsonl")))
    return {"verdict": "ok" if r.returncode == 0 else "fail",
            "exit_code": r.returncode, "archived": archived}


# ── L3 freshness monitor (SPEC-0110 — the SPEC-0105 §4 delegated freshness probe) ──────────────────
# The bounded nightly INVOKES this per v2 project. It is a DERIVED freshness VIEW computed on read
# (SPEC-0110 r4 — no new ledger). The kernel stays a GENERIC GRADER: each PROJECT supplies a read-only
# freshness ADAPTER that returns NORMALIZED per-pipeline freshness — a {fresh|stale|miss} state + the
# last-run age (SPEC-0110 r2). The adapter — not the kernel — owns reading the project's REAL source (a
# live datastore query, a container-log heartbeat, a registry block, an env threshold, whatever the
# project already encodes) and the cadence/threshold/status interpretation that decides fresh-vs-stale.
# The kernel consumes that normalized output through its ALREADY-INJECTABLE seam and embeds NO
# project-specific source format — it parses no project store and runs no project query (SPEC-0110 r2 +
# the D-0019 territory boundary + CHARTER §P1). An unreadable adapter source is a MISS, never a silent
# skip (SPEC-0110 r3). It runs from
# the kernel nightly OUTSIDE the project's own loop, so a dead project scheduler is what it CATCHES, not
# what silences it (SPEC-0110 r3 independence).
CONSUMER_OPS_CONTRACT = "yitc-ops.yaml"   # SPEC-0093 rule 1 carrier (same const as live_probe/deploy)
_FRESHNESS_STATES = ("fresh", "stale", "miss")   # the NORMALIZED adapter-contract states (SPEC-0110 r2)
# T-10798 (SPEC-0110 r2 reachability-OUTCOME axis / SPEC-0174 rule 3 + VP5): the freshness STATE says how
# OLD the result is; it cannot say "the probe ran fine and the SUBJECT is down". Left alone such a record
# normalizes to `fresh` and grades `ok` — BAD NEWS rendered CLEAN — while the only two states that would
# surface it (`stale`/`miss`) are exactly the collapses rule 3 forbids (bad news filed as NO DATA). So a
# record MAY carry an explicit reachability OUTCOME BESIDE its state. ABSENT is legal and unchanged: an
# existing declaration has no reachability target and grades exactly as before (the backward-compat half
# of the claim). A PRESENT-but-unusable value is a SOURCE error, never a silent drop — a dropped outcome
# renders clean, which is the very false-green this axis exists to close.
_REACHABILITY_OUTCOMES = ("reachable", "unreachable")
_FRESHNESS_CMD_TIMEOUT = 30   # seconds — bound a kind:command adapter run (SPEC-0110 r2; a hung adapter is a MISS, r3)


def _load_freshness_decl(proj_path: Path) -> "dict | None":
    """Read <proj>/yitc-ops.yaml `freshness:` (SPEC-0110 r1 declare-or-waive section). Return the
    declaration dict when the project DECLARES freshness — it must NAME its read-only adapter via an
    `adapter` reference (or the legacy `source_ref`, used by the default file adapter); it never inlines
    threshold VALUES (SPEC-0110 r2). Return None when the section is ABSENT or explicitly WAIVED
    (`waived: true` / `state: waived`): a waive is a deliberate forward-aware skip, not an alert
    (SPEC-0093 declare-or-waive — surfacing an un-declared project is the SPEC-0093 carrier-completeness
    sweep's job; a freshness MISS is reserved for a DECLARED adapter whose source is stale/unreadable,
    r3). A malformed carrier is fail-closed treated as no declaration. None here ⇒ verdict `none` ⇒
    NON-ADOPTED (the migration-gate honesty rule, r2)."""
    ops_path = proj_path / CONSUMER_OPS_CONTRACT
    if not ops_path.is_file():
        return None
    errors: list = []
    ops = state.load_path(ops_path, errors=errors)
    if errors or not isinstance(ops, dict):
        return None
    section = ops.get("freshness")
    if not isinstance(section, dict):
        return None
    if section.get("waived") is True or section.get("state") == "waived":
        return None
    if not (section.get("adapter") or section.get("source_ref")
            or (section.get("kind") == "command" and "command" in section)):
        return None  # not a usable declaration (names no file/command adapter → NON-ADOPTED, r2)
    # A kind:command decl that NAMES a command is a DECLARATION even if the command is malformed —
    # the strict argv check lives in _run_command_freshness_adapter, so a broken command grades to a
    # whole-project MISS (alert), never `none` (the SPEC-0110 r2/r3 migration-gate honesty rule).
    return section


def _normalize_pipeline(raw: dict, name: str) -> dict:
    """Coerce one adapter-returned record into the NORMALIZED contract shape (SPEC-0110 r2):
    {name, state ∈ {fresh|stale|miss}, age_hours, detail} + the OPTIONAL reachability
    `outcome` ∈ {reachable|unreachable} (T-10798). An unknown/absent state fails CLOSED to `miss` (an
    adapter that cannot say is NOT fresh, r3) — never silently dropped.

    The outcome axis carries the SAME fail-closed asymmetry, and the two classes are deliberately
    different (`lessons/fail-closed-belongs-to-the-reader-not-the-parser`): an ABSENT outcome is a
    legitimate "this adapter reports no reachability outcome" (every pre-axis declaration) and is left
    absent; a PRESENT-but-unusable one is the record failing to say what it claimed to say, so it fails
    closed to `miss` exactly as an unusable state does. Dropping it instead would render the record
    CLEAN — the false-green this axis exists to close."""
    state_val = raw.get("state")
    if state_val not in _FRESHNESS_STATES:
        return {"name": name, "state": "miss",
                "detail": f"adapter returned unusable state {state_val!r}"}
    # KEY PRESENCE, not value-truthiness (audit-post finding 0, absorbed): absent means the KEY is
    # absent. A key that IS present carrying null/empty is an adapter that TRIED to report a reachability
    # outcome and failed to fill it — reading that as "reports none" would grade the record clean, the
    # very false-green this axis closes. So a present key must carry a usable value or fail closed.
    has_outcome = "outcome" in raw
    outcome_val = raw.get("outcome")
    if has_outcome and outcome_val not in _REACHABILITY_OUTCOMES:
        return {"name": name, "state": "miss",
                "detail": f"adapter returned unusable reachability outcome {outcome_val!r}"}
    out = {"name": name, "state": state_val}
    if raw.get("age_hours") is not None:
        out["age_hours"] = raw.get("age_hours")
    if raw.get("detail") is not None:
        out["detail"] = raw.get("detail")
    if has_outcome:   # only reachable with a VALID value — an unusable one returned `miss` above
        out["outcome"] = outcome_val
    return out


def _coerce_pipelines(data, source_label: str) -> dict:
    """Extract + STRICT-validate + normalize an adapter's raw pipeline data into the contract shape
    {"pipelines": [normalized…], "error": None} | {"pipelines": [], "error": <detail>}. SHARED by the
    file adapter (raw file content) and the command adapter (parsed stdout) so there is ONE
    validate/normalize path (CHARTER §P1 F2 — reuse, no parallel coercion). `data` may be a mapping
    {name: {state,…}}, a {"pipelines": …} wrapper, or a list of {name, state, …}. A MALFORMED record
    (not a dict, or no valid {fresh|stale|miss} state) means the SOURCE is corrupted — surfaced as a
    whole-project adapter ERROR (a source MISS, SPEC-0110 r3), NOT a silent per-pipeline `miss` that
    would masquerade as a normal run-miss."""
    if isinstance(data, dict):
        block = data.get("pipelines", data)
        if isinstance(block, dict):
            items = [(str(k), v) for k, v in block.items()]
        elif isinstance(block, list):
            items = [(str(v.get("name", i)) if isinstance(v, dict) else str(i), v)
                     for i, v in enumerate(block)]
        else:
            items = []
    elif isinstance(data, list):
        items = [(str(v.get("name", i)) if isinstance(v, dict) else str(i), v)
                 for i, v in enumerate(data)]
    else:
        items = []
    if not items:
        return {"pipelines": [], "error": f"freshness adapter source has no pipelines ({source_label})"}
    for name, raw in items:
        if not isinstance(raw, dict):
            return {"pipelines": [],
                    "error": f"malformed freshness record for '{name}' ({source_label}): not a mapping"}
        if raw.get("state") not in _FRESHNESS_STATES:
            return {"pipelines": [],
                    "error": f"malformed freshness record for '{name}' ({source_label}): "
                             f"unusable state {raw.get('state')!r}"}
        # T-10798 — the reachability-OUTCOME axis, validated on the SAME strict footing as `state`.
        # ABSENT is legal (a declaration with no reachability target — the backward-compat case); a
        # PRESENT-but-unusable value means the SOURCE is corrupted, so it surfaces as a whole-project
        # adapter ERROR, never a silent per-pipeline `miss` masquerading as a normal run-miss. Keyed on
        # PRESENCE, not on non-null (audit-post finding 0, absorbed): a source line that writes
        # `outcome:` with an empty/null value HAS the key and failed to fill it — treating that as
        # "reports none" would let a corrupted source grade clean.
        if "outcome" in raw and raw.get("outcome") not in _REACHABILITY_OUTCOMES:
            return {"pipelines": [],
                    "error": f"malformed freshness record for '{name}' ({source_label}): "
                             f"unusable reachability outcome {raw.get('outcome')!r}"}
    return {"pipelines": [_normalize_pipeline(raw, name) for name, raw in items], "error": None}


def _run_command_freshness_adapter(proj_path: Path, decl: dict, *, now: _dt.datetime) -> dict:
    """The kind:command freshness ADAPTER (SPEC-0110 r2): RUN the project-declared read-only `command`
    (cwd = project root) and parse its stdout as the NORMALIZED {pipelines, error} contract. The kernel
    stays a generic GRADER — it executes a DECLARED command (list form, NO shell) and reads NORMALIZED
    JSON, embedding no project source format (CHARTER §P1 + D-0019). EVERY failure mode — no/malformed
    argv, spawn error, timeout, non-zero exit, non-JSON or non-contract stdout, or an adapter-reported
    source error — returns {"pipelines": [], "error": …} so the caller renders a whole-project MISS
    (SPEC-0110 r3), never a silent skip. `now` is part of the seam signature (unused here — the project's
    command computes its own ages live)."""
    cmd = decl.get("command")
    if not (isinstance(cmd, list) and cmd and all(isinstance(a, str) for a in cmd)):
        return {"pipelines": [],
                "error": "freshness adapter kind:command but no usable command (non-empty list of str)"}
    try:
        proc = subprocess.run(cmd, cwd=str(proj_path), capture_output=True, text=True,
                              timeout=_FRESHNESS_CMD_TIMEOUT)
    except subprocess.TimeoutExpired:
        return {"pipelines": [],
                "error": f"freshness adapter command timed out after {_FRESHNESS_CMD_TIMEOUT}s"}
    except (OSError, ValueError, TypeError) as e:
        return {"pipelines": [], "error": f"freshness adapter command failed to start/run: {e}"}
    if proc.returncode != 0:
        detail = (proc.stderr or "").strip()[:200]
        return {"pipelines": [], "error": f"freshness adapter command exited {proc.returncode}: {detail}"}
    try:
        parsed = json.loads(proc.stdout)
    except (ValueError, TypeError) as e:
        return {"pipelines": [], "error": f"freshness adapter command stdout not JSON: {e}"}
    if not isinstance(parsed, dict):
        return {"pipelines": [], "error": "freshness adapter command stdout is not a {pipelines, error} object"}
    if parsed.get("error"):
        # the adapter ITSELF reported a SOURCE failure (e.g. DB down) → whole-project MISS (r3)
        return {"pipelines": [], "error": str(parsed["error"])}
    return _coerce_pipelines(parsed, "command stdout")


def _default_freshness_adapter(proj_path: Path, decl: dict, *, now: _dt.datetime) -> dict:
    """The DEFAULT read-only freshness ADAPTER (the injectable seam's default impl), DISPATCHING on the
    declaration's `kind` (SPEC-0110 r2):
      - kind == "command" → RUN the project's declared read-only command and parse its stdout JSON
        contract (_run_command_freshness_adapter) — the LIVE source the project owns (e.g. trend-finder's
        datastore query + container-log heartbeat);
      - kind == "file" / absent → load a project-provided NORMALIZED freshness FILE (path from
        `decl['adapter']`, or the legacy `decl['source_ref']`, relative to the project root) already in
        the contract shape.
    Both return {"pipelines": [normalized…], "error": None}; a missing / unparseable / empty source
    returns {"error": …}, which the caller turns into a whole-project MISS (SPEC-0110 r3), never a silent
    skip. The kernel embeds NO project-specific source format (it runs a DECLARED command or reads a
    NORMALIZED file — it parses no project store and runs no project query — CHARTER §P1 + D-0019); a project with a
    LIVE source supplies its own adapter through this same seam WITHOUT touching kernel code — that is why
    the seam is injectable. `now` is part of the seam signature for adapters that compute age live; the
    default file branch consumes pre-normalized states, so it does not need it."""
    if (decl.get("kind") or "file") == "command":
        return _run_command_freshness_adapter(proj_path, decl, now=now)
    ref = str(decl.get("adapter") or decl.get("source_ref") or "freshness-state.yaml")
    src = proj_path / ref.partition("#")[0]
    if not src.is_file():
        return {"pipelines": [], "error": f"freshness adapter source not found ({src.name})"}
    errors: list = []
    data = state.load_path(src, errors=errors)
    if errors:
        return {"pipelines": [], "error": f"freshness adapter source unparseable ({src.name})"}
    return _coerce_pipelines(data, src.name)


def _pipeline_is_fresh_failing(pl: dict) -> bool:
    """ONE normalized record reports «the probe ran FINE and the SUBJECT is unreachable» — the
    fresh-and-failing cell (T-10798 / SPEC-0174 rule 3). The `fresh` half is load-bearing and NOT
    incidental: an `unreachable` outcome carried on a STALE or MISSED record is itself STALE news — we
    cannot claim a subject is down from a reading we already know we could not take — so such a record
    stays the ordinary no-data `alert` and never borrows the confirmed-failure reading."""
    return pl.get("state") == "fresh" and pl.get("outcome") == "unreachable"


def _freshness_pipeline_note(pl: dict) -> "str | None":
    """The operator-visible rendering of ONE normalized pipeline record — or None when the record is
    CLEAN and correctly renders as NOTHING AT ALL (silence).

    The SINGLE rendering home (T-10798), so SPEC-0174 rule 3's four cases cannot drift apart: a
    fresh-and-failing record renders as FAILING, distinct from STALE, from MISS, and from the silence a
    clean record renders as. A surface that showed the fresh-failure as any of the other three would be
    false-green by construction — which is why this is one function with one caller, not formatting
    inlined at each report site."""
    detail = pl.get("detail") or f"age={pl.get('age_hours')}h"
    if _pipeline_is_fresh_failing(pl):
        return f"pipeline {pl.get('name')}: FAILING — probe fresh, SUBJECT UNREACHABLE — {detail}"
    if pl.get("state") in ("stale", "miss"):
        return f"pipeline {pl.get('name')}: {str(pl.get('state')).upper()} — {detail}"
    return None


def _freshness_flags(fr: dict) -> bool:
    """A project's freshness grade is NON-CLEAN (`alert` OR `failing`) — the ONE predicate read by BOTH
    the `projects_flagged` OR and the `freshness_alerts` summary counter (T-10798).

    Deliberately one predicate rather than two literal comparisons: when the verdict vocabulary grew a
    new non-clean value, a per-site `== "alert"` test would have silently reached one site and missed the
    other, so a project whose ONLY fault was a confirmed-down subject would have graded unflagged — the
    exact false-green this card closes, re-introduced one level up. Sharing the predicate also makes the
    wiring PROBE-able at an attributable signal (`lessons/a-differential-over-a-shared-counter-must-be-
    attributable`): the freshness-only counter and the multi-check OR read the same arm, so deleting the
    failing arm turns the counter assertion RED."""
    return fr.get("verdict") in ("alert", "failing")


def _check_freshness(proj_path: Path, *, now: _dt.datetime, adapter) -> dict:
    """The DERIVED freshness VIEW for one project (SPEC-0110 r1/r2/r4 — computed on read, nothing
    persisted). The kernel is a GENERIC GRADER: invoke the project's read-only ADAPTER, which returns
    NORMALIZED per-pipeline freshness ({fresh|stale|miss} + age, + the optional reachability `outcome`),
    then aggregate. A project verdict is `failing` if ANY pipeline is FRESH-AND-UNREACHABLE; else `alert`
    if ANY pipeline is `stale` or `miss`; else `ok`. An adapter-level
    error (unreadable source) is a whole-project MISS/alert, never a silent skip (r3). When freshness is
    not declared/waived the verdict is `none`. `adopted` carries the migration-gate honesty signal (r2):
    True only when a declared adapter is actually graded; False for `none` — `none` is NOT coverage.

    THE GRADE ISSUES NO OUTBOUND REQUEST OF ITS OWN — not to verify a reported failure, not to confirm
    one, not as a fallback for a missing or stale result (SPEC-0174 rule 2, absolute). It grades the
    RECORD the project's adapter produced; every act of reaching a project's own runtime belongs to that
    project. This function calls only the INJECTED adapter and pure local helpers.

    `failing` OUTRANKS `alert` (T-10798): a confirmed-down subject is the sharper and more actionable
    news than «some pipeline has no fresh data», and the precedence hides nothing — every stale/miss
    pipeline still renders its own line beside the failing one."""
    decl = _load_freshness_decl(proj_path)
    if decl is None:
        return {"verdict": "none", "adopted": False,
                "reason": "freshness not declared (absent/waived)"}
    result = adapter(proj_path, decl, now=now)
    err = result.get("error")
    if err:
        # unreadable adapter SOURCE = a MISS, never a silent skip (r3)
        return {"verdict": "alert", "adopted": True, "reason": err,
                "pipelines": [{"name": "(source)", "state": "miss", "detail": err}]}
    # The kernel is STRICT to the ONE normalized adapter shape — it does NOT re-coerce payloads
    # (format translation is the ADAPTER's job, never the kernel grader's). It only AGGREGATES the
    # normalized states: a pipeline is healthy ONLY when its state is exactly `fresh`; anything else —
    # `stale`, `miss`, or a record the adapter returned without a valid state — is alert-worthy
    # (fail-closed: an adapter that cannot say `fresh` is NOT fresh, r3).
    pipelines = result.get("pipelines") or []
    if not pipelines:
        return {"verdict": "alert", "adopted": True, "reason": "adapter returned no pipelines",
                "pipelines": [{"name": "(adapter)", "state": "miss",
                               "detail": "adapter returned no pipelines"}]}
    # T-10798 (SPEC-0174 rule 3 / VP5): FIRST ask whether any pipeline reports its SUBJECT unreachable
    # on a FRESH reading. That is bad news we CAN see, and it is neither `stale` nor `miss` — grading it
    # into either would file bad news as NO DATA (the collapse rule 3 forbids), and grading it `ok` (what
    # the state-only aggregation below does on its own) renders it CLEAN. It is its own verdict.
    failing = [p for p in pipelines if _pipeline_is_fresh_failing(p)]
    if failing:
        names = ", ".join(str(p.get("name")) for p in failing)
        return {"verdict": "failing", "adopted": True, "pipelines": pipelines,
                "reason": f"subject unreachable on a FRESH probe: {names}"}
    alert = any(p.get("state") != "fresh" for p in pipelines)
    return {"verdict": "alert" if alert else "ok", "adopted": True, "pipelines": pipelines}


# ── Project-verify HEALTH (T-11359 / SPEC-0105 §1, the `verify.health` opt-in of SPEC-0152 r16) ────
# WHY THIS EXISTS. Every other per-project check in this runner is a FILE read: it can tell you the
# carrier is well-shaped, the graph is fresh, the waivers are current. None of them can tell you
# whether the project's main actually BUILDS. The only thing in the engine that executes a consumer's
# declared `verify.layers` is the land path, and it runs over a CANDIDATE branch at land time — so a
# red main is discovered by the next worker that tries to land on it, and ONE red converts into N
# halted workers (the incident behind this check: 12 halts, 20 branches of unlanded work).
#
# WHICH LAYERS RUN — the design call, and it is deliberately NOT the kernel's to make. A health run
# executes exactly the layers the PROJECT named in `verify.health.layers`, an opt-in that SELECTS
# FROM the layers it already declared. Two candidates were rejected:
#   * CHEAP-ONLY (the kernel infers cost, e.g. from `timeout:`) — `timeout:` is a BUDGET, not a cost.
#     Nothing in the carrier says which command starts containers or drives a browser, so the kernel
#     would be GUESSING which of another project's commands are safe to run unattended in that
#     project's checkout. That guess lands inside the D-0019 territory boundary this module's own
#     docstring already refuses to cross for `graph build`.
#   * WHOLE-PROJECT OPT-IN (one boolean, then run everything) — forces the expensive choice: accept
#     the 600s container-stack layer to get the 180s static one, or get nothing. The per-layer list is
#     the same opt-in at the granularity the cost actually varies at, and costs no new vocabulary —
#     the layer NAMES already exist.
# The opt-in therefore holds the territory boundary BY CONSTRUCTION: nothing runs in a consumer's
# checkout that the consumer did not name for this use.
#
# THE KNOWN WEAKNESS OF ANY OPT-IN, and how it is closed: nobody opts in and "0 failures" reads as
# "all green". Same shape SPEC-0110 r2 met with the freshness `none` verdict, and answered the same
# way — a project with no opt-in grades `none`, NEVER `ok`, is counted in its own non-adopted
# counter, and says "declares none" in words. An excluded layer is NAMED as not-run rather than
# counted among the passing ones. Silence is never the report.
#
# PREP IS NOT RUN. A layer's `prep:` (npm/uv install) is a dependency-tree WRITE in the consumer's
# checkout; this is a read. A layer that cannot pass without its prep must not be declared
# health-eligible — which is a real constraint on the declaration, stated here so it is not
# discovered as a mystery failure.
#
# BOUNDED + REPORT-ONLY (CHARTER §6 / SPEC-0105 §2): SKIPPED under --dry-run (it executes project
# commands — the `_check_backup` / `_check_conformance_surfaces` parity); every command clamped to
# `_HEALTH_LAYER_TIMEOUT_CEILING`; any runner fault REPORTED, never aborting the nightly; and the run
# never fixes anything, never opens a session, never writes the consumer repo.
_HEALTH_LAYER_TIMEOUT_CEILING = 900   # seconds — the kernel ceiling a declared per-layer `timeout:` clamps to
_HEALTH_STDERR_TAIL = 400             # chars of a failing layer's stderr carried onto the record


def _read_health_carrier(proj_path: Path) -> tuple:
    """Read the project's `yitc-ops.yaml` and return a THREE-way result — deliberately not two-way:
    `("unreadable", reason)` | `("absent", None)` | `("ok", decl)`.

    THE THIRD ARM IS THE POINT (audit-pre pass 2). A malformed / duplicate-top-level-key carrier is a
    BROKEN WATCH, and folding it into the absent arm would render it as `none` — "this project
    deliberately declares no health layers" — which is a silenced check reported as a considered
    decision. That is the same false-green this module already refuses for the ops carrier (T-10292)
    and for the freshness adapter source (SPEC-0110 r3), so `_load_freshness_decl`'s
    fail-closed-to-None shape is NOT copied here.

    `absent` covers every shape that is a legitimate non-adoption: no carrier, no `verify.health`, an
    explicit waiver, or an opt-in that is not a non-empty list of layer-name strings. The read itself
    goes through `state.load_ops` — the ONE ops-carrier read+parse idiom (SPEC-0093), which RAISES on
    a malformed carrier rather than swallowing it, which is exactly the signal the first arm needs."""
    ops_path = proj_path / CONSUMER_OPS_CONTRACT
    if not ops_path.is_file():
        return ("absent", None)
    try:
        ops = state.load_ops(ops_path)
    except Exception as exc:  # noqa: BLE001 — malformed/duplicate-key/unreadable: NEVER silent
        return ("unreadable", f"{CONSUMER_OPS_CONTRACT} unparseable: {type(exc).__name__}: {exc}")
    if not isinstance(ops, dict):
        return ("absent", None)
    ver = ops.get("verify")
    if not isinstance(ver, dict):
        return ("absent", None)
    health = ver.get("health")
    if not isinstance(health, dict):
        return ("absent", None)
    if health.get("waived") is True or isinstance(health.get("waiver"), dict):
        return ("absent", None)
    names = health.get("layers")
    if not (isinstance(names, list) and names and all(isinstance(n, str) and n.strip() for n in names)):
        return ("absent", None)
    return ("ok", {"layers": [n.strip() for n in names], "verify": ver})


def _health_layer_timeout(ly: dict) -> int:
    """The bound for one health layer: its declared `timeout:` clamped to the kernel ceiling, with the
    ceiling itself as the fallback for an absent or unusable value. A consumer may make a layer's
    health run SHORTER than the ceiling, never longer — the nightly's own boundedness is the kernel's
    property, not the consumer's (SPEC-0105 §2)."""
    raw = ly.get("timeout")
    try:
        declared = int(raw)
    except (TypeError, ValueError):
        return _HEALTH_LAYER_TIMEOUT_CEILING
    if declared <= 0:
        return _HEALTH_LAYER_TIMEOUT_CEILING
    return min(declared, _HEALTH_LAYER_TIMEOUT_CEILING)


def _check_project_health(proj_path: Path, *, dry_run: bool, _run) -> dict:
    """Run the project's HEALTH-ELIGIBLE declared verify layers against its checkout as it stands, and
    report. Read-only in intent and report-only by contract: the verdict is news, never an action.

    Verdicts — `ok` (every eligible layer passed) · `fail` (a layer exited non-zero: THE RED MAIN,
    named) · `alert` (a broken watch — an unreadable carrier, an opted-in name that no layer
    declares, or a layer that could not be RUN) · `none` (the project declares no health-eligible
    layers — NOT coverage, never `ok`) · `skipped` (--dry-run).

    `fail` and `alert` are deliberately different verdicts because they are different news: `fail`
    says the project's main is red, `alert` says we do not know whether it is. Collapsing them would
    let a health check that cannot RUN read like a project that is fine.

    The record ALWAYS carries `layers` (name + outcome for each layer that ran) and `not_run` (name +
    reason for each declared layer that did not), so the excluded set is readable off the record
    rather than inferred from an absence."""
    if dry_run:
        return {"verdict": "skipped", "layers": [], "not_run": [],
                "reason": "dry-run (executes project-declared commands)"}
    kind, payload = _read_health_carrier(proj_path)
    if kind == "unreadable":
        return {"verdict": "alert", "unreadable": True, "layers": [], "not_run": [],
                "reason": payload}
    if kind == "absent":
        # No usable opt-in. Distinguish "declares no verify layers at all" from "declares layers but
        # none for health" — AC2's third fixture must be distinguishable, and the two states call for
        # different actions from a reader (adopt verify vs. opt a layer in).
        declared = []
        ops_path = proj_path / CONSUMER_OPS_CONTRACT
        if ops_path.is_file():
            try:
                ops = state.load_ops(ops_path)
            except Exception:  # noqa: BLE001 — unreachable (the unreadable arm caught it); stay fail-safe
                ops = None
            ver = ops.get("verify") if isinstance(ops, dict) else None
            if isinstance(ver, dict) and isinstance(ver.get("layers"), list):
                declared = [ly for ly in ver["layers"] if isinstance(ly, dict)]
        if not declared:
            return {"verdict": "none", "layers": [], "not_run": [],
                    "reason": "declares no verify layers"}
        return {"verdict": "none", "layers": [],
                "not_run": [{"layer": str(ly.get("layer") or "?"),
                             "reason": "not health-eligible (no `verify.health.layers` opt-in)"}
                            for ly in declared],
                "reason": f"declares {len(declared)} verify layer(s) but no health-eligible opt-in "
                          f"(`verify.health.layers` absent or waived)"}

    eligible = payload["layers"]
    declared = [ly for ly in (payload["verify"].get("layers") or []) if isinstance(ly, dict)]
    by_name = {str(ly.get("layer") or "").strip(): ly for ly in declared if str(ly.get("layer") or "").strip()}
    layers: list = []
    not_run: list = []
    violations: list = []
    # Every DECLARED layer the opt-in left out is NAMED as not-run (AC3). This is the whole
    # point of the excluded half: a layer the rule leaves out must be visibly absent from the run,
    # never quietly absent from the failures.
    for name, ly in by_name.items():
        if name not in eligible:
            not_run.append({"layer": name, "reason": "not health-eligible (excluded by `verify.health.layers`)"})
    for name in eligible:
        ly = by_name.get(name)
        if ly is None:
            # An opted-in name nothing declares: the project believes a layer is being watched and it
            # is not. A broken watch is an `alert`, never a silent skip.
            violations.append({"layer": name, "detail": "named in `verify.health.layers` but no such "
                                                        "layer is declared in `verify.layers`"})
            not_run.append({"layer": name, "reason": "opted in but not declared in `verify.layers`"})
            continue
        ly_waiver = ly.get("waiver")
        if isinstance(ly_waiver, dict) and str(ly_waiver.get("reason") or "").strip():
            not_run.append({"layer": name,
                            "reason": f"waived in `verify.layers` ({str(ly_waiver['reason']).strip()})"})
            continue
        cmd = ly.get("command")
        if not (isinstance(cmd, str) and cmd.strip()):
            violations.append({"layer": name, "detail": "declares no runnable `command:`"})
            not_run.append({"layer": name, "reason": "declares no runnable `command:`"})
            continue
        timeout = _health_layer_timeout(ly)
        try:
            r = _run(cmd, shell=True, cwd=str(proj_path), capture_output=True, text=True,
                     timeout=timeout)
        except subprocess.TimeoutExpired:
            layers.append({"layer": name, "outcome": "error",
                           "detail": f"timed out after {timeout}s"})
            continue
        except Exception as exc:  # noqa: BLE001 — a runner fault must never abort the nightly
            layers.append({"layer": name, "outcome": "error",
                           "detail": f"{type(exc).__name__}: {exc}"})
            continue
        if r.returncode == 0:
            layers.append({"layer": name, "outcome": "pass", "exit_code": 0})
        else:
            layers.append({"layer": name, "outcome": "fail", "exit_code": r.returncode,
                           "detail": (r.stderr or r.stdout or "").strip()[-_HEALTH_STDERR_TAIL:]})
    if any(l["outcome"] == "fail" for l in layers):
        verdict = "fail"
    elif violations or any(l["outcome"] == "error" for l in layers):
        verdict = "alert"
    elif not layers:
        # Every opted-in layer turned out to be waived — nothing ran, so there is no health reading.
        # `none` (with the reason) rather than `ok`: an empty run is not a green one.
        verdict = "none"
    else:
        verdict = "ok"
    out = {"verdict": verdict, "layers": layers, "not_run": not_run}
    if violations:
        out["violations"] = violations
    if verdict == "none" and not layers:
        out["reason"] = "every health-eligible layer is waived in `verify.layers` — nothing ran"
    return out


def _born_waiver_stale_paths(obj, marker: str, placeholder_expiry: str, path: str = "") -> list:
    """Recursively walk a parsed yitc-ops carrier and return the dotted PATHs whose waiver still carries
    the init born-waiver SIGNATURE (T-9642): a `reason:` string still containing `marker`, OR an
    `expiry:` value still equal to `placeholder_expiry` (the security waiver's born review-date — the
    audit-pre finding-0 case: a refreshed reason but an untouched placeholder expiry). Order-stable."""
    out: list = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            child = f"{path}.{k}" if path else str(k)
            if k == "reason" and isinstance(v, str) and marker in v:
                out.append(path or "reason")
            elif k == "expiry" and str(v).strip() == placeholder_expiry:
                out.append(path or "expiry")
            else:
                out.extend(_born_waiver_stale_paths(v, marker, placeholder_expiry, child))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out.extend(_born_waiver_stale_paths(v, marker, placeholder_expiry, f"{path}[{i}]"))
    # de-dup while preserving order (a section may match both reason + expiry → report once)
    seen: set = set()
    return [p for p in out if not (p in seen or seen.add(p))]


def _check_stage_profile(proj_path: Path, *, now: _dt.datetime, days: int = 14) -> dict:
    """The per-project STAGE-PROFILE reading (T-12008 / SPEC-0105 §1): what did each lifecycle stage
    cost in THIS project over the last `days`, and how much of it was machine time.

    READ-ONLY and derived — it folds that project's own `events.jsonl` through the kernel
    `stage-profile` lens (`views._view_stage_profile`, the same function `graph query stage-profile`
    runs), exactly as the observation-rollup folds each project's journal (D-0019 territory-safe: a
    read of another repo's journal, never a write, never a command run in that checkout). It emits NO
    event of its own — the reading rides the existing `nightly_run_completed` report (CHARTER §P1 F2:
    a view, not a new store).

    SUPPRESSED-WHEN-EMPTY is the caller's job, and this function makes it decidable: `closed_tasks`
    is 0 for a project that closed nothing in the window, and the report prints no line for it. A
    project with no journal at all reports the same 0 rather than an error — an absent journal and an
    idle fortnight are both "nothing to report", and neither is a fault. Fail-OPEN: any read fault
    degrades to `verdict: alert` carrying the reason, never aborting the run (the `_check_freshness`
    posture)."""
    from lib import views as _views      # noqa: PLC0415 — lazy, matches the `cross` / `frontend_errors` seam
    since = now - _dt.timedelta(days=days)
    try:
        prof = _views._view_stage_profile(
            proj_path / "events.jsonl", since, None,
            _fmt_duration=_views._fmt_duration, _median=_views._median,
            _ts_delta_seconds=_views._ts_delta_seconds)
    except Exception as exc:              # noqa: BLE001 — one project's bad journal never fails the run
        return {"verdict": "alert", "closed_tasks": 0, "window_days": days,
                "reason": f"stage-profile fold failed: {exc}"}
    return {"verdict": "ok", "window_days": days,
            "closed_tasks": prof.get("closed_tasks", 0),
            "stages": prof.get("stages") or {},
            "lead_time": prof.get("lead_time") or {},
            "audits_per_close": prof.get("audits_per_close")}


def _check_seam_read_amplification(proj_path: Path, *, now: _dt.datetime,
                                   days: int = None) -> dict:
    """The per-project SEAM-READ-AMPLIFICATION reading (T-12037 / SPEC-0105 §1 / SPEC-0119 rule 37):
    which of THIS project's verbs physically read more of its corpus than the corpus they composed.

    ONE ORACLE, RE-DERIVED NOWHERE. It calls the very fold the `debt` echo renders
    (`debt.seam_read_amplification`) over THAT project's own `events.jsonl` — the same shape
    `_check_stage_profile` uses for the stage lens and the observation-rollup uses for its slices
    (D-0019 territory-safe: a READ of another repo's journal, never a write, never a command run in
    that checkout). It emits NO event of its own; the reading rides the existing
    `nightly_run_completed` payload (CHARTER §P1 F2 — a view, not a new store). Because the fold is
    shared, the nightly and the project's own `debt` line can never disagree about a ratio.

    THE SCOPE IS THE REGISTRY, AND EVERY PROJECT ANSWERS (the plan's F1). The caller runs this for
    every registry `yitc_v2` project, so coverage is not a function of which projects happen to have
    adopted something — there is nothing here to adopt.

    `no counters` IS A DISTINCT ANSWER FROM `clean`, AND THAT IS THE WHOLE VERDICT LOGIC
    (audit-pre finding 1). The decision reads the fold's `measured` field ALONE:
      * `measured == 0`  -> `skip`, `counters: false`, reason `no counters` — this project has emitted
        no usable `cli_invoked.reads` rows in the window (a pre-T-12034 corpus, an absent journal, an
        idle project). NOTHING WAS MEASURED, so nothing is green: reporting `ok` here would be the
        CHARTER §P3 «presence ≠ absence» fault, and reporting a ratio of 1.0 would be fabricating a
        reading nobody took. Both were named as the failure mode this check must not have.
      * `measured > 0, count == 0` -> `ok`, `counters: true` — genuinely clean, every measured seam
        inside its bound. This is the case that must never render as the one above.
      * `count > 0` -> `alert` carrying the amplified seams, worst-first.

    Read-only throughout; nothing persisted, nothing gated, no exit code moves (the §6 fence).
    Fail-OPEN: any read fault degrades to `alert` carrying the reason rather than aborting the run
    (the `_check_stage_profile` / `_check_freshness` posture) — a project whose journal cannot be
    read is not health, but it is also not this runner's death."""
    from lib import debt as _debt          # noqa: PLC0415 — lazy leaf, the `views` / `init` idiom
    window = int(days or _debt.SEAM_READ_WINDOW_DAYS)
    try:
        fold = _debt.seam_read_amplification(
            proj_path / "events.jsonl", root=proj_path, now=now, window_days=window,
            # The project's OWN declared exemptions (SPEC-0190 rule 10 / SPEC-0160 rule 25), read
            # from ITS carrier — never the kernel's. A kernel-side default here would silently hold
            # every consumer to a bound its own contract had legitimately widened.
            exemptions=_reads_exemptions_for(proj_path))
    except Exception as exc:               # noqa: BLE001 — one project's bad journal never fails the run
        return {"verdict": "alert", "counters": False, "count": 0, "measured": 0,
                "window_days": window, "seams": [],
                "reason": f"seam-read fold failed: {type(exc).__name__}: {str(exc).strip()[:200]}"}
    measured = int(fold.get("measured") or 0)
    seams = [s for s in (fold.get("seams") or []) if isinstance(s, dict)]
    if measured == 0:
        return {"verdict": "skip", "counters": False, "count": 0, "measured": 0,
                "window_days": window, "seams": [],
                "reason": "no counters — no `cli_invoked.reads` rows in the window "
                          "(nothing measured; NOT clean)"}
    if not seams:
        return {"verdict": "ok", "counters": True, "count": 0, "measured": measured,
                "window_days": window, "seams": [], "bound": fold.get("bound")}
    return {"verdict": "alert", "counters": True, "count": len(seams), "measured": measured,
            "window_days": window, "bound": fold.get("bound"),
            # `project` is CARRIED, not dropped: a journal may hold rows emitted under more than one
            # project name (a `-C` run writes onto the target's journal), so two seams can share a
            # verb label and differ only here. Without it the report renders them as one line twice —
            # measured on the real fleet, 2026-09-04.
            "seams": [{"project": s.get("project"), "verb": s.get("verb"), "ratio": s.get("ratio"),
                       "axis": s.get("axis"), "bound": s.get("bound"),
                       "blocking": s.get("blocking")} for s in seams],
            "worst": (fold.get("worst") or {}).get("ratio"),
            "reason": f"{len(seams)} of {measured} measured seam(s) read more than they composed"}


def _reads_exemptions_for(proj_path: Path) -> list:
    """That project's OWN declared `reads.exemptions[]`, or [] (SPEC-0190 rule 10 / SPEC-0160 r25).

    The nightly twin of `cli._reads_exemptions`, kept here rather than shared because the two resolve
    DIFFERENT roots — the host reads its own `REPO_ROOT`, this reads each swept project's — and the
    only thing they would share is three lines of dict-walking. FAIL-CLOSED to [] on every unhappy
    path: an exemption nobody can read must never widen a bound (see the host twin for why that
    direction and not the other)."""
    try:
        ops_path = proj_path / CONSUMER_OPS_CONTRACT
        if not ops_path.is_file():
            return []
        ops = state.load_path(ops_path)
        sec = ops.get("reads") if isinstance(ops, dict) else None
        entries = sec.get("exemptions") if isinstance(sec, dict) else None
        return entries if isinstance(entries, list) else []
    except Exception:                      # noqa: BLE001 — a report-only input, never fatal
        return []


def _check_born_waiver_freshness(proj_path: Path) -> dict:
    """OPERATIONAL-HYGIENE check (SPEC-0105 rule 1 / X-0130): surface a project's `yitc-ops.yaml` born
    waivers whose init PLACEHOLDER was never replaced — they sit as legitimate-looking fail-closed
    defaults indefinitely (observed on trend-finder: deploy.policy/security/inspection still verbatim
    born-waivers months post-migration). The born-waiver SIGNATURE is owned single-SoT by init.py
    (BORN_WAIVER_MARKER / BORN_WAIVER_PLACEHOLDER_EXPIRY). Verdict `alert` iff any stale born-waiver
    remains OR the carrier is present-but-UNREADABLE; `ok` if the carrier carries none; `skip` only for
    an ABSENT carrier (a born waiver is an init concern, not a nightly-MISS — surfacing an undeclared
    carrier is the SPEC-0093 sweep's job).

    T-10337: an UNREADABLE carrier is an ALERT, never a silent skip. Collapsing ABSENT and MALFORMED into
    one `skip` made a CORRUPTED carrier read as "nothing to check" — the same fail-open T-10292 fixed in
    the two concern checks below, and the rule the sibling SPEC-0110 freshness adapter already holds (an
    unreadable source is a MISS, r3). Fail-closed belongs to the USE SITE, not to the parser
    (`lessons/fail-closed-belongs-to-the-reader-not-the-parser.md`): `state.load_path` stays faithful,
    and this reader decides what a broken carrier means for IT. An EMPTY carrier parses to `{}` and still
    grades `ok` — that is absence of waivers, not corruption.
    Read-only; nothing persisted (the §6 fence)."""
    from lib import init  # lazy — avoids coupling nightly's top-level imports to init (the marker SoT)
    ops_path = proj_path / CONSUMER_OPS_CONTRACT
    if not ops_path.is_file():
        return {"verdict": "skip", "reason": "no yitc-ops.yaml carrier"}
    errors: list = []
    ops = state.load_path(ops_path, errors=errors)
    if errors or not isinstance(ops, dict):
        # PRESENT but unparseable / not a mapping: the born waivers cannot be read, so they cannot be
        # confirmed cleared either. `stale_waivers: []` keeps this alert's shape uniform with the concern
        # checks' `stance_issues: []` / `drifts: []`, so the item-count sums stay total-safe.
        return {"verdict": "alert", "unreadable": True, "stale_waivers": [],
                "reason": _ops_unreadable_reason(ops_path)}
    stale = _born_waiver_stale_paths(ops, init.BORN_WAIVER_MARKER, init.BORN_WAIVER_PLACEHOLDER_EXPIRY)
    if stale:
        return {"verdict": "alert", "stale_waivers": stale,
                "reason": f"{len(stale)} born-waiver(s) still carry the init placeholder (never replaced)"}
    return {"verdict": "ok", "stale_waivers": []}


def _ops_unreadable_reason(ops_path: Path) -> str:
    """Name WHY a PRESENT `yitc-ops.yaml` is unreadable, so the alert carries the parse error (T-10292).
    Runs on the ERROR path only: the concern sources (`init.concern_conformance` / `init.concern_drift`)
    report the `unreadable` STATUS but swallow the error, so re-read once through the SAME canonical
    reader they use (`state.load_ops` — CHARTER §P5, no parallel parser) to recover the detail."""
    try:
        ops = state.load_ops(ops_path)
    except Exception as e:  # noqa: BLE001 — mirrors the sources' never-raise report-only posture
        return f"{CONSUMER_OPS_CONTRACT} unreadable: {str(e).strip()[:200]}"
    if not isinstance(ops, dict):
        return f"{CONSUMER_OPS_CONTRACT} unreadable: top level is {type(ops).__name__}, not a mapping"
    return f"{CONSUMER_OPS_CONTRACT} unreadable"   # source said unreadable; a raced rewrite now parses


def _check_concern_conformance(proj_path: Path, *, now=None) -> dict:
    """STANDING concern-conformance check (SPEC-0105 / SPEC-0119 rule 8 / SPEC-0128 Rule 2, T-10030): the
    SAME declare-or-waive STANCE + waiver-CURRENCY signal the debt echo surfaces, run per-project on the
    nightly so drift is caught even in a repo no session has opened. REUSES the single source
    `init.concern_conformance` (CHARTER §P5 — no parallel stance logic). Verdict `alert` iff count > 0
    (stance drift and/or an expired waiver) OR the carrier is UNREADABLE; `ok` when clean; `skip` only
    for a `no-carrier` project (not yet initialized — surfacing THAT is the SPEC-0093 init sweep's job).

    T-10292: an UNREADABLE carrier is an ALERT, never a silent skip — the source discriminates
    `no-carrier` from `unreadable`, and collapsing both to `skip` made a BROKEN carrier read as health
    exactly when the checks it silences matter most (live instance: social-parser, fu_256827b7c49f). Same
    rule the sibling SPEC-0110 freshness adapter already holds: an unreadable source is a MISS (r3).
    Read-only; nothing persisted (the §6 fence)."""
    from lib import init  # lazy — the concern-conformance source of truth (init.concern_conformance)
    today = now.date() if now is not None else None
    cc = init.concern_conformance(proj_path / CONSUMER_OPS_CONTRACT, today=today)
    if cc.get("status") == "unreadable":
        return {"verdict": "alert", "unreadable": True, "stance_issues": [], "expired_waivers": [],
                "reason": _ops_unreadable_reason(proj_path / CONSUMER_OPS_CONTRACT)}
    if cc.get("status") != "checked":
        return {"verdict": "skip", "reason": f"yitc-ops.yaml {cc.get('status')}"}
    if cc.get("count", 0) > 0:
        return {"verdict": "alert",
                "stance_issues": cc.get("stance_issues") or [],
                "expired_waivers": cc.get("expired_waivers") or [],
                "reason": f"{cc.get('count')} concern-conformance issue(s) "
                          f"({len(cc.get('stance_issues') or [])} stance, "
                          f"{len(cc.get('expired_waivers') or [])} expired-waiver)"}
    return {"verdict": "ok", "stance_issues": [], "expired_waivers": []}


def _check_unratified_adoptions(proj_path: Path) -> dict:
    """STANDING unratified-adoption check (SPEC-0105 / SPEC-0119 rule 13, T-10516): the SAME
    birth-sentinel residual the debt echo surfaces — an `adoption:` record reading `status: adopt` while
    still stamped `owner: init` over a section the carrier genuinely DECLARES — run per-project on the
    nightly so it is caught even in a repo no session has opened. An unratified adoption is a STANDING
    carrier condition, not an activity-triggered one, so it belongs on the same seam as its rule-9 sibling
    `_check_concern_conformance` (T-10030), whose shape this mirrors. REUSES the single source
    `init.unratified_adoptions` (CHARTER §P5 — no parallel stance logic; that reuse inherits the source's
    enumerated 3-condition trigger and the one stance reader `_mirror_adoption_status`, rather than
    re-deriving the empty-opt-in rule a hand-rolled check got wrong, T-10415).

    Verdict `alert` iff count > 0 OR the carrier is UNREADABLE; `ok` when every record is ratified; `skip`
    only for a `no-carrier` project (not yet initialized — surfacing THAT is the SPEC-0093 init sweep's
    job). The unit is the CONCERN, not the carrier (`lessons/scope-the-trigger-not-the-view`): a ratified
    sibling can never clear an unratified row.

    THE UNREADABLE ARM IS THE READER'S JUDGEMENT, NOT THE SOURCE'S
    (`lessons/fail-closed-belongs-to-the-reader-not-the-parser` — the rule its sibling
    `_check_adapter_conformance` holds verbatim). `init.unratified_adoptions` stays FAITHFUL: it reports
    `unreadable` at count 0 and never nags the debt echo, because in a repo with a live session the
    SPEC-0093 init sweep owns malformed-carrier errors. This reader has the opposite duty — it exists
    precisely to check repos NOBODY opens, where no sweep will ever run — so it fails closed on a broken
    carrier, the T-10292 rule its 3 siblings hold (collapsing ABSENT and CORRUPTED into one `skip` makes a
    broken carrier read as health exactly when the check matters most). `records: []` on that arm keeps the
    item-count sums total-safe, the siblings' uniform shape. It does NOT print its own UNREADABLE detail
    line nor re-count `unreadable_ops_carriers`: T-10292 counts the broken CARRIER once and names the cause
    once, and this is the same single fault on the same file.

    This view never auto-ratifies — it NAMES the owner's exit and leaves the act to them (writing the
    ratification would re-commit the original sin of stamping an answer nobody gave,
    `lessons/a-stance-mirror-is-only-sound-at-birth`). Read-only; nothing persisted, and NEVER writes into
    the consumer repo (the §6 fence)."""
    from lib import init  # lazy — the unratified-adoption source of truth (init.unratified_adoptions)
    ua = init.unratified_adoptions(proj_path / CONSUMER_OPS_CONTRACT)
    if ua.get("status") == "unreadable":
        return {"verdict": "alert", "unreadable": True, "records": [],
                "reason": _ops_unreadable_reason(proj_path / CONSUMER_OPS_CONTRACT)}
    if ua.get("status") != "checked":
        return {"verdict": "skip", "records": [], "reason": f"yitc-ops.yaml {ua.get('status')}"}
    if ua.get("count", 0) > 0:
        records = ua.get("records") or []
        return {"verdict": "alert", "records": records,
                "reason": f"{len(records)} unratified adoption(s) still stamped `owner: init` "
                          f"({', '.join(str(r.get('concern')) for r in records)})"}
    return {"verdict": "ok", "records": []}


def _check_concern_drift(proj_path: Path) -> dict:
    """DERIVED per-concern DRIFT check (SPEC-0143 Rule 3, T-10172): the SAME report-only drift signal the
    consumer sees at its `-C` session-start, run per-project on the nightly so a moved kernel concern is
    caught even in a repo no session has opened. REUSES the single source `init.concern_drift` (CHARTER
    §P5 — no parallel drift logic). Verdict `alert` iff drift count > 0 OR the carrier is UNREADABLE
    (T-10292, the _check_concern_conformance precedent — a broken carrier is never a silent skip); `ok`
    when every concern is level; `skip` only for a `no-carrier` project. Read-only;
    nothing persisted, and NEVER writes into the consumer repo (the §6 fence)."""
    from lib import init  # lazy — the drift source of truth (init.concern_drift)
    cd = init.concern_drift(proj_path / CONSUMER_OPS_CONTRACT)
    if cd.get("status") == "unreadable":
        return {"verdict": "alert", "unreadable": True, "drifts": [],
                "reason": _ops_unreadable_reason(proj_path / CONSUMER_OPS_CONTRACT)}
    if cd.get("status") != "checked":
        return {"verdict": "skip", "drifts": [], "reason": f"yitc-ops.yaml {cd.get('status')}"}
    if cd.get("count", 0) > 0:
        return {"verdict": "alert", "drifts": cd.get("drifts") or [],
                "reason": f"{cd.get('count')} concern(s) behind the kernel registry version"}
    return {"verdict": "ok", "drifts": []}


def _check_adapter_conformance(proj_path: Path) -> dict:
    """CONSUMER VENDOR-ADAPTER conformance check (SPEC-0105 / SPEC-0125 VP1/VP2, T-10480): the reusable
    promotion of the hand-built T-10416 probe — does the adapter→neutral-home CHAIN an AI consumer session
    actually reads RESOLVE end-to-end? Run per-project on the nightly so a fat/broken adapter is caught
    even in a repo no session has opened (and in the consumers X-0164's per-consumer migration has not
    reached yet). REUSES the single source `init.adapter_conformance` (CHARTER §P5 — no parallel resolution
    logic; the born carrier `_ensure_consumer_vendor_adapter` and this check share the Rule-1 home order).

    Verdict `alert` iff count > 0 (a fat adapter / an unresolvable home pointer / an unfilled home) OR the
    adapter is UNREADABLE; `ok` when the chain resolves; `skip` only for a `no-adapter` project (no
    CLAUDE.md — not yet initialized; surfacing THAT is the SPEC-0093 init sweep's job).

    An UNREADABLE adapter is an ALERT, never a silent skip — the T-10292/T-10337 precedent its sibling
    checks hold (collapsing ABSENT and CORRUPTED into one `skip` makes a broken carrier read as health
    exactly when the check matters most). Fail-closed belongs to the USE SITE, not the parser
    (`lessons/fail-closed-belongs-to-the-reader-not-the-parser.md`): `init.adapter_conformance` stays
    faithful, and this reader decides what a broken adapter means for IT.
    Read-only; nothing persisted, and NEVER writes into the consumer repo (the §6 fence)."""
    from lib import init  # lazy — the adapter-conformance source of truth (init.adapter_conformance)
    ac = init.adapter_conformance(proj_path)
    if ac.get("status") == "unreadable":
        return {"verdict": "alert", "unreadable": True, "violations": [],
                "reason": "CLAUDE.md is present but unreadable — the vendor adapter cannot be checked, "
                          "so its pointer to the provider-neutral home cannot be confirmed to resolve"}
    if ac.get("status") != "checked":
        return {"verdict": "skip", "violations": [], "reason": "no CLAUDE.md vendor adapter"}
    if ac.get("count", 0) > 0:
        viols = ac.get("violations") or []
        return {"verdict": "alert", "violations": viols,
                "reason": f"{len(viols)} vendor-adapter issue(s) "
                          f"({', '.join(sorted({v['kind'] for v in viols}))})"}
    return {"verdict": "ok", "violations": []}


def _check_adoption_completeness(proj_path: Path) -> dict:
    """CONSUMER ADOPTION-COMPLETENESS conformance check (SPEC-0122 R6, T-10694 / X-0543): a pinned
    external-shared-library dependency proves CODE IDENTITY (R2 no-local-diff) but NOT SURFACE COVERAGE —
    boomrocket's ticket-review adoption ran 6/15 endpoints, 0 UI, 0 ops checks INVISIBLY for weeks. Run
    per-project on the nightly so a partial/undeclared adoption is caught even in a repo no session has
    opened. REUSES the single source `init.adoption_completeness` (CHARTER §P5 — no parallel resolution
    logic; the report-only sibling of `_check_adapter_conformance`).

    Verdict `alert` iff count > 0 (a declared-but-not-integrated surface / an undeclared applicable
    pinned dep / an unanswered section / an unresolved manifest) OR the ops carrier is UNREADABLE; `ok`
    when the declared surfaces all conform; `skip` for a `no-section` project (no applicable pinned dep
    and nothing declared — the SPEC-0093 init sweep's concern) or a `waived` section (the recorded
    declare-or-waive answer — SHOULD-grade, never a hard block).

    An UNREADABLE ops carrier is an ALERT, never a silent skip — the T-10292/T-10337 precedent its
    sibling checks hold. Fail-closed belongs to the USE SITE, not the parser; `init.adoption_completeness`
    stays faithful, and this reader decides what a broken carrier means for IT. Read-only; nothing
    persisted, and NEVER writes into the consumer repo (the §6 fence)."""
    from lib import init  # lazy — the adoption-completeness source of truth (init.adoption_completeness)
    ac = init.adoption_completeness(proj_path)
    if ac.get("status") == "unreadable":
        return {"verdict": "alert", "unreadable": True, "violations": [],
                "reason": _ops_unreadable_reason(proj_path / CONSUMER_OPS_CONTRACT)}
    if ac.get("status") in ("no-section", "waived"):
        return {"verdict": "skip", "violations": [],
                "reason": "no applicable pinned dependency declared"
                          if ac.get("status") == "no-section" else "adoption-completeness waived"}
    if ac.get("count", 0) > 0:
        viols = ac.get("violations") or []
        return {"verdict": "alert", "violations": viols,
                "reason": f"{len(viols)} adoption-completeness issue(s) "
                          f"({', '.join(sorted({v['kind'] for v in viols}))})"}
    return {"verdict": "ok", "violations": []}


def _check_override_ledger(proj_path: Path) -> dict:
    """CONSUMER OVERRIDE-LEDGER drift check (SPEC-0196 rule 3, T-12046): the report-only leg that
    keeps a project's REGISTERED divergences from the pinned release visible between updates.

    Placed beside `_check_adoption_completeness` because it is the same kind of reading — a per-project
    fold of the ops carrier, report-only, run on the nightly so it is caught in a repo no session has
    opened — and because SPEC-0196 rule 3 names that surface explicitly as the one this rides. REUSES
    the single source `release.ledger_drift`, the SAME function `release.update` calls (CHARTER §P5 —
    no parallel ledger reader, and no standalone parser: SPEC-0196 rule 3 forbids both).

    WHAT IT CAN AND CANNOT SEE, stated rather than implied. A nightly sweep holds no verified release
    tree, so it passes NEITHER `redundant_paths` nor `conflicts` and reports the ledger-INTRINSIC
    findings alone — MALFORMED entries and OVERDUE review triggers. Redundancy and conflict are
    findings of an UPDATE, which is where the two trees exist; inventing them here would be worse
    than reporting the two kinds this surface can honestly read.

    Verdict `alert` iff findings exist OR the ops carrier is UNREADABLE; `ok` when a ledger is present
    and clean; `skip` for a project carrying no `overrides:` section — the commonest and healthiest
    state, since a project that diverges from nothing registers nothing.

    An UNREADABLE ops carrier is an ALERT, never a silent skip — the T-10292/T-10337 precedent its
    sibling checks hold. Fail-closed belongs to the USE SITE, not the parser; `release.ledger_drift`
    stays faithful and this reader decides what a broken carrier means for IT. Read-only; nothing
    persisted, and NEVER writes into the consumer repo (the §6 fence)."""
    from lib import release  # lazy — the ledger-drift source of truth (release.ledger_drift)
    drift = release.ledger_drift(proj_path / CONSUMER_OPS_CONTRACT, tasks_dir=proj_path / "tasks")
    if drift.get("status") == "unreadable":
        return {"verdict": "alert", "unreadable": True, "findings": [],
                "reason": _ops_unreadable_reason(proj_path / CONSUMER_OPS_CONTRACT)}
    if drift.get("status") == "no-section":
        return {"verdict": "skip", "findings": [],
                "reason": "no `overrides:` section — this project registers no local divergence"}
    findings = drift.get("findings") or []
    if findings:
        return {"verdict": "alert", "findings": findings, "entries": drift.get("entries", 0),
                "reason": f"{len(findings)} override-ledger finding(s) "
                          f"({', '.join(sorted({f['kind'] for f in findings}))})"}
    return {"verdict": "ok", "findings": [], "entries": drift.get("entries", 0)}


def _check_no_local_diff(proj_path: Path) -> dict:
    """CONSUMER PIN-IDENTITY conformance check (SPEC-0122 R2 HEALTH / SPEC-0172 rule 3, T-10877): the
    IDENTITY sibling of `_check_adoption_completeness`. That leg keeps a pinned adoption's SURFACE
    COVERAGE honest; this one keeps the PINNED COPY honest — a surviving or locally PATCHED copy of a
    neutral bridge module means a symbol no longer resolves FROM the pin, which is exactly the drift the
    pin exists to prevent. T-10863 shipped the verdict but only a HAND CALL could reach it, so a
    violation stayed invisible in every repo nobody opened; run it per-project on the nightly and it
    reaches an operator on the same standing surface as its sibling. REUSES the single source
    `init.no_local_diff` (CHARTER §P5 — no parallel selector; what the check DETECTS is settled by
    T-10863 and untouched here, this reader only routes its verdict).

    Verdict `alert` iff count > 0 (a surviving/modified local copy, an unresolvable pin, or an
    undeclared neutral surface) OR the ops carrier is UNREADABLE; `ok` when the declared bridge carries
    no local copy (suppressed-when-clean — a clean consumer prints no detail line); `skip` for a
    `not-declared` project (no `spike_sandbox.bridge` mapping — a project that never opted into a spike
    bridge is never examined, and must never be told it has a problem it cannot have).

    An UNREADABLE ops carrier is an ALERT, never a silent skip — the T-10292/T-10337 precedent its
    sibling checks hold (collapsing ABSENT and CORRUPTED into one `skip` makes a broken carrier read as
    health exactly when the check matters most). Fail-closed belongs to the USE SITE, not the parser
    (`lessons/fail-closed-belongs-to-the-reader-not-the-parser.md`): `init.no_local_diff` stays faithful,
    and this reader decides what a broken carrier means for IT. Read-only; nothing persisted, and NEVER
    writes into the consumer repo (the §6 fence)."""
    from lib import init  # lazy — the pin-identity source of truth (init.no_local_diff)
    nd = init.no_local_diff(proj_path)
    if nd.get("status") == "unreadable":
        return {"verdict": "alert", "unreadable": True, "violations": [],
                "reason": _ops_unreadable_reason(proj_path / CONSUMER_OPS_CONTRACT)}
    if nd.get("status") == "not-declared":
        return {"verdict": "skip", "violations": [],
                "reason": "no spike-bridge pin declared"}
    if nd.get("count", 0) > 0:
        viols = nd.get("violations") or []
        return {"verdict": "alert", "violations": viols,
                "reason": f"{len(viols)} pin-identity issue(s) "
                          f"({', '.join(sorted({v['kind'] for v in viols}))})"}
    return {"verdict": "ok", "violations": []}


def _check_carrier_shape(proj_path: Path) -> dict:
    """REAL-consumer CARRIER-DRIFT canary (SPEC-0105 / fu_4e3c8da2dac9, T-10664): does each registry
    consumer's LIVE Class-C1 deploy carrier still classify + precondition to a RUNNABLE `_BackupPlan`?
    Run per-project on the nightly so a carrier that DRIFTED into a `pg_dump` shape the engine cannot
    run is caught even in a repo no session has opened.

    WHY IT LIVES HERE, NOT IN THE KERNEL GATE (T-10286 → T-10637): test_t10286_c1_carrier_shape was
    converted from reading the three LIVE consumer carriers to committed fixtures (kernel tests must
    not depend on projects, SPEC-0131 rule 4). The fixtures preserve the SHAPE coverage verbatim — but
    a committed fixture can NEVER see a real carrier drifting to a new shape, which is exactly the
    regression class boomrocket + social-parser really hit (t10286's docstring: 'A clean-fixture test
    could never see it — only the real carriers do'). That canary belongs on the READ-ONLY
    cross-project surface, never the kernel land gate — reported here, NEVER a blocker.

    REUSE (CHARTER §P5): drives the SINGLE deploy boundary — `deploy._classify_deploy_gate` +
    the ONE normalizing `deploy._backup_precondition` (→ `_BackupPlan`, T-10286) — over the live
    carrier. No parallel classifier, no second carrier parser.

    Verdict `alert` iff the declared C1 carrier no longer yields a runnable plan (a gate that no longer
    classifies autonomous, or a `pg_dump` shape the precondition refuses) OR the ops carrier is
    UNREADABLE (the T-10292 fail-closed-reader precedent its sibling checks hold — a broken carrier is
    never a silent skip). `ok` when the carrier still runs; `skip` when the project declares no
    autonomous Class-C1 carrier (nothing to drift) or has no ops carrier at all (the SPEC-0093 init
    sweep's concern). Scope is Class-C1 `pg_dump` — the only carrier with a runnable precondition and
    the only shape the real drift incident touched. Read-only; nothing persisted, and NEVER writes into
    the consumer repo (the §6 fence)."""
    ops_path = proj_path / CONSUMER_OPS_CONTRACT
    if not ops_path.exists():
        return {"verdict": "skip", "carriers": [], "reason": "no yitc-ops.yaml carrier"}
    try:
        ops = state.load_ops(ops_path)
    except Exception:  # noqa: BLE001 — mirror the siblings' never-raise report-only posture
        return {"verdict": "alert", "unreadable": True, "carriers": [],
                "reason": _ops_unreadable_reason(ops_path)}
    if not isinstance(ops, dict):
        return {"verdict": "alert", "unreadable": True, "carriers": [],
                "reason": _ops_unreadable_reason(ops_path)}
    policy = (ops.get("deploy") or {}).get("policy")
    classes = policy.get("classes") if isinstance(policy, dict) else None
    if not isinstance(classes, dict) or "C1" not in classes:
        return {"verdict": "skip", "carriers": [],
                "reason": "no autonomous Class-C1 carrier declared"}
    from lib import deploy  # lazy — the SINGLE deploy gate + precondition boundary (T-10286)
    gate = deploy._classify_deploy_gate(policy, "C1", False)
    if not (gate.proceed and gate.mode == "autonomous"):
        return {"verdict": "alert",
                "carriers": [{"class": "C1", "state": "gate-drift", "detail": gate.message}],
                "reason": "Class-C1 carrier no longer classifies autonomous at the deploy gate"}
    plan = deploy._backup_precondition(gate.evidence)
    if plan.error:
        return {"verdict": "alert",
                "carriers": [{"class": "C1", "state": "shape-drift", "detail": plan.error}],
                "reason": "Class-C1 carrier drifted to a pg_dump shape the engine cannot run"}
    return {"verdict": "ok",
            "carriers": [{"class": "C1", "state": "runnable",
                          "command": plan.command, "budget_seconds": plan.budget_seconds}]}


def _check_repo_storage(proj_path: Path) -> dict:
    """REPO-HOUSEKEEPING canary (SPEC-0105 §1 read-only health, T-11063): has git's own garbage
    collection reported a problem in this project's checkout that nothing has cleared since?

    THE INCIDENT (measured 2026-08-13, deviation `stale-gc-log-blocks-autogc-unnoticed`): this repo's
    `.git/gc.log` was dated 2026-07-10 and said "There are too many unreachable loose objects". `.git`
    reached 42G — 36.5 GiB across 6784 LOOSE objects against 5.2 GiB in 17 packs, an order of magnitude
    past the next-largest repo on the host — and NOTHING reported it; it surfaced only when the owner
    ran a manual disk sweep at 63% full. The nightly already walks every registry project read-only, so
    the watch costs ONE more entry in that existing list — no cron line, no event type, no log file, no
    verb (CHARTER §P1 F1).

    WHAT THE SIGNAL ACTUALLY MEANS (measured, not assumed — the card's hypothesis, tested at Analysis
    on git 2.43.0 with purpose-built fixtures). A FRESH `gc.log` hard-blocks auto-gc: an identical pair
    of fixtures with 600 loose objects packs normally without the file and stays at `packs: 0` with it,
    exiting 0 in silence (git's "be quiet on failure" path). A STALE one (older than `gc.logExpiry`,
    default 1 day) does NOT block — so the popular reading, "while this file exists git refuses to
    gc", is true only inside that window. The honest reading is broader and always true: *git's own
    housekeeping reported a problem it did not resolve, and nothing has cleared it since*. That is
    exactly the condition under which the loose pile grew for 34 days, and presence alone would have
    fired on the FIRST nightly after 2026-07-10 — 34 days before the owner found it.

    ONE SIGNAL, NO TUNED THRESHOLD (CHARTER §P1 F4). A loose-object FLOOR is deliberately NOT shipped:
    no incident names a case `gc.log` missed, and a check that only fires on a number nobody tuned is
    the failure mode this card exists to avoid. Loose count/bytes are attached to a FIRED finding as
    sizing CONTEXT only — never an independent trigger — so a repo with no `gc.log` stays silent
    whatever its object count (which is also what keeps the differential clean). Accepted blind spot,
    deferred until an incident names it: housekeeping disabled by config (`gc.auto=0`) writes no
    `gc.log` and is not reported.

    Verdicts follow the established sibling vocabulary:
      * no `.git`                    -> skip (not a git checkout — nothing to say about it)
      * `.git` present, gitdir UNRESOLVABLE -> alert + `unreadable` (the T-10292/T-10337 fail-closed
        READER precedent — a broken carrier is never a silent skip;
        `lessons/fail-closed-belongs-to-the-reader-not-the-parser`)
      * NO `gc.log` in ANY gitdir    -> ok, no findings (suppressed-when-clean: prints nothing)
      * `gc.log` PRESENT             -> alert, ONE finding PER gitdir naming that gitdir + the log's
                                        DATE + age in days

    EVERY GITDIR, NOT ONLY THE COMMON ONE (T-11399, measured on this repo 2026-08-21/22 with git
    2.43). `gc.log` and `gc.pid` do NOT share a location rule: `gc.log` resolves per-WORKTREE
    (`git_path`), `gc.pid` resolves common (`git_common_path`). T-11063 built the stat assuming they
    matched, so on a repo running a worktree fleet it saw ONE of the signals present on disk — a walk
    for `gc.log` under `.git` returned TWELVE files (one common + eleven under `.git/worktrees/<name>/`)
    on the measured day while the walk for `gc.pid` returned exactly one, in the common dir. So this
    check walks the COMMON gitdir PLUS every `<gitdir>/worktrees/*/`, and each finding NAMES the
    gitdir it came from.

    THE STALE-COMMON-LOG READING — DECIDED, NOT LEFT IMPLICIT (T-11399). Widening the walk exposes a
    second error in the OPPOSITE direction: a `gc` launched from a linked worktree clears only ITS OWN
    log, so the common `.git/gc.log` can stand indefinitely while housekeeping in fact succeeds
    elsewhere. Measured with a purpose-built fixture: with a log planted in BOTH the common gitdir and
    a linked worktree's, `git gc` run from that worktree exited 0 and removed its own log while
    leaving the common one untouched. DECISION: the common log is STILL REPORTED as a live blocker; it
    is NOT aged out by a newer collection in some other gitdir. Each gitdir is judged INDEPENDENTLY on
    its own log, with no cross-gitdir aging. Grounds: (i) the signal adopted above is PRESENCE, not
    freshness; (ii) the fixture DISPROVES the aging-out inference — the worktree's gc packed its own
    objects and never addressed the unreachable-loose-object condition the common log records, so
    treating it as evidence of health would report health the measurement does not support; (iii)
    fail-closed — under-reporting is the exact failure this check exists to prevent (34 days
    unnoticed). The consequence is intended, not a defect: a stale common log keeps firing until
    someone clears it.

    LOOSE PILE IS SIZED FROM THE COMMON GITDIR. Loose objects live only in the common object store; a
    linked worktree gitdir has no `objects/`, so sizing a worktree finding from its own gitdir would
    report "0 loose objects". The walk is done ONCE, from the common gitdir, and only when at least
    one finding fired — so the cost is still paid only by a repo that already has a `gc.log`.

    READ-ONLY BY CONSTRUCTION (the §6 fence, and acceptance criterion 2 proves it by state comparison,
    not by "no error was raised"): this invokes NO git subprocess at all — it stats files and, only
    when one exists, walks `.git/objects/??/` with stdlib to size the loose pile. There is no
    code path here that can gc, prune, repack, or write into an inspected repo."""
    dotgit = proj_path / ".git"
    if not dotgit.exists():
        return {"verdict": "skip", "findings": [], "reason": "not a git checkout"}
    gitdir = dotgit
    if dotgit.is_file():
        # A worktree / submodule checkout: `.git` is a FILE holding `gitdir: <path>`. Resolve it, and
        # fail CLOSED when it does not resolve — an unreadable carrier is never a silent skip.
        try:
            line = dotgit.read_text(encoding="utf-8", errors="replace").strip()
            target = line.split("gitdir:", 1)[1].strip() if line.startswith("gitdir:") else ""
            gitdir = Path(target) if Path(target).is_absolute() else (proj_path / target)
            if not target or not gitdir.is_dir():
                raise ValueError(f"gitdir pointer does not resolve: {line[:120]!r}")
        except Exception as exc:  # noqa: BLE001 — mirror the siblings' never-raise report-only posture
            return {"verdict": "alert", "unreadable": True, "findings": [],
                    "reason": f".git pointer file unreadable — {exc}"}
    findings = []
    now = _dt.datetime.now(tz=_dt.timezone.utc)
    for label, cand, checkout in _gc_log_gitdirs(gitdir, proj_path):
        gc_log = cand / "gc.log"
        if not gc_log.exists():
            continue
        entry = {"kind": "housekeeping-blocked", "gitdir": label,
                 "gitdir_path": str(cand), "checkout_path": (str(checkout) if checkout else None)}
        try:
            mtime = _dt.datetime.fromtimestamp(gc_log.stat().st_mtime, tz=_dt.timezone.utc)
            entry["gc_log_date"] = mtime.date().isoformat()
            entry["age_days"] = max(0, (now - mtime).days)
            entry["message"] = (gc_log.read_text(encoding="utf-8", errors="replace").strip()
                                .splitlines() or [""])[0][:200]
        except Exception as exc:  # noqa: BLE001 — a gc.log we cannot read is still a REPORTED problem
            # NON-FATAL to the walk (T-11399): one unreadable log must not cost the OTHER gitdirs'
            # signals, which is the whole point of walking. The top-level `unreadable` flag stays
            # reserved for the `.git`-pointer failure above.
            entry.update({"gc_log_date": None, "age_days": None, "unreadable": True,
                          "message": f"gc.log present but unreadable — {exc}"})
        findings.append(entry)
    if not findings:
        return {"verdict": "ok", "findings": []}
    loose_count, loose_bytes = _loose_object_volume(gitdir)   # the COMMON store — see the docstring
    for entry in findings:
        entry["loose_objects"] = loose_count
        entry["loose_bytes"] = loose_bytes
    dates = sorted(e["gc_log_date"] for e in findings if e.get("gc_log_date"))
    oldest = dates[0] if dates else "an unreadable log"
    oldest_age = max((e["age_days"] for e in findings if e.get("age_days") is not None), default=None)
    return {"verdict": "alert", "findings": findings,
            "reason": f"git housekeeping reported an unresolved problem in {len(findings)} gitdir(s) "
                      f"— oldest {oldest}"
                      + (f" ({oldest_age}d ago)" if oldest_age is not None else "")
                      + " and nothing has cleared it since"}


def _gc_log_gitdirs(gitdir, proj_path):
    """The gitdirs a `gc.log` can live in, as `(label, gitdir_path, checkout_path_or_None)` (T-11399).

    `gc.log` is WORKTREE-scoped (`git_path`) while `gc.pid` is common-scoped (`git_common_path`), so
    the common gitdir alone is a fraction of the signal on a repo running a worktree fleet — see
    `_check_repo_storage`. Order is deterministic: the common dir first, then worktrees by name.

    `checkout_path` is resolved from git's OWN `<gitdir>/gitdir` pointer file (it holds the absolute
    path of that worktree's `.git` file, whose parent is the checkout). Unresolvable -> None, and the
    renderer names the gitdir instead of inventing a path. Never raises: a `worktrees` dir that is
    missing, unreadable, or vanishes mid-walk simply contributes nothing."""
    out = [("common", gitdir, proj_path)]
    try:
        entries = sorted((d for d in (gitdir / "worktrees").iterdir() if d.is_dir()),
                         key=lambda d: d.name)
    except OSError:
        return out
    for d in entries:
        checkout = None
        try:
            pointer = (d / "gitdir").read_text(encoding="utf-8", errors="replace").strip()
            if pointer:
                checkout = Path(pointer).parent
        except OSError:
            checkout = None
        out.append((d.name, d, checkout))
    return out


def _loose_object_volume(gitdir: Path) -> tuple:
    """Loose-object count + bytes under `<gitdir>/objects/??/`, by stdlib walk — NO git subprocess, so
    the enclosing check cannot mutate the repo it is sizing (the §6 fence, structurally).

    Sizing CONTEXT for an ALREADY-FIRED finding, never a trigger of its own (`_check_repo_storage`),
    which is also why the cost is only paid by a repo that already has a `gc.log`. Never raises: a
    directory that vanishes or refuses a stat mid-walk contributes 0 rather than failing the run."""
    count = 0
    total = 0
    objects = gitdir / "objects"
    try:
        fanout = [d for d in objects.iterdir()
                  if d.is_dir() and len(d.name) == 2 and all(c in "0123456789abcdef" for c in d.name)]
    except OSError:
        return (0, 0)
    for d in fanout:
        try:
            for f in d.iterdir():
                try:
                    if f.is_file():
                        count += 1
                        total += f.stat().st_size
                except OSError:
                    continue
        except OSError:
            continue
    return (count, total)


def _check_frontend_errors(proj_path: Path, *, as_of: _dt.datetime, fe, read_rows) -> dict:
    """The FRONTEND-ERROR CADENCE leg (SPEC-0170 / SPEC-0142, T-10803): fold this project's ADOPTED,
    QUALIFYING frontend-error source into confirmed clusters, once per nightly run.

    WHY THIS CARRIER AND NO OTHER (SPEC-0142 §2 binding 1 + CHARTER §P1): the obligation is periodic,
    so it needs a trigger — and the rule is that the trigger→run path must be provider-independent OS
    infra end to end. This runner already IS that (system cron → a deterministic script), and it
    already enumerates the registry's v2 projects and already reads each `yitc-ops.yaml`, which is
    exactly the adoption declaration the sweep must enumerate. So the cadence costs ONE read-only check
    on an existing carrier: no scheduler, no store, no FSM, no config surface is introduced. Nothing on
    this path consults a model — the sweep folds and REPORTS (§2 binding 2).

    IT NEVER DISCOVERS A SOURCE (D-0019). The ONLY input is the consumer's own
    `extensions.adopts[] spec: SPEC-0170` entry, read through the EXISTING `fe.declared_source` and
    gated by the EXISTING six-property preflight. A project that has not adopted is skipped; the kernel
    never authors a declaration to fold against, and never writes into the consumer repo.

    Verdicts follow the `_check_concern_conformance` / `_check_adoption_completeness` shape exactly:
      * no carrier                  -> skip (an un-init'd project is the SPEC-0093 sweep's business)
      * UNREADABLE carrier          -> alert (the T-10292/T-10337 fail-closed READER, not a silent skip)
      * not adopted                 -> skip, `adopted: False`
      * adopted, source NOT qualifying -> alert naming the failing properties (the SPEC-0171
        scoped-promise arm: an adopting consumer must never be served the healthy consumer's silence)
      * source unreadable           -> alert (a source the kernel cannot read is not health)
      * else                        -> `ok` carrying the confirmed set

    REPORT-ONLY, and the distinction is deliberate: a CONFIRMED CLUSTER NEVER GRADES `alert`. Clusters
    are a derived view of the consumer's own errors — surfacing them is the point, flagging the project
    for having them would turn a report into a gate (CHARTER §6 / SPEC-0170 §Internal item 3). What
    alerts is the CONVEYOR being broken: an unreadable carrier, a non-qualifying source, a dead source,
    or a cadence/on-demand disagreement.

    THE ON-DEMAND DIFF (AC2) is computed and recorded here, on the run row. The cadence's cluster set
    comes from the shared `fe.visible_clusters`; the on-demand set is read back out of the view the
    `frontend-errors` verb actually PRINTS (`fe.to_json`), and `on_demand_diff` is the symmetric
    difference of the two fingerprint sets. It is `[]` whenever the two agree — and a renderer that
    dropped or invented a cluster between the fold and the printed view surfaces as a non-empty diff,
    which alerts. That is what keeps the standing sweep and the reader's own re-fold the same answer.

    Read-only throughout; nothing persisted, and never a write into the consumer repo (the §6 fence)."""
    ops_path = proj_path / CONSUMER_OPS_CONTRACT
    if not ops_path.is_file():
        return {"verdict": "skip", "adopted": False, "reason": "no yitc-ops.yaml carrier"}
    errors: list = []
    ops = state.load_path(ops_path, errors=errors)
    if errors or not isinstance(ops, dict):
        return {"verdict": "alert", "adopted": False, "unreadable": True,
                "reason": _ops_unreadable_reason(ops_path)}
    source, violations = fe.declared_source(ops)
    if source is None and not violations:
        return {"verdict": "skip", "adopted": False,
                "reason": f"{fe.EXTENSION_SPEC_ID} not adopted"}
    if violations:
        # ADOPTED over a source the kernel cannot read: the one case that must never look like health.
        return {"verdict": "alert", "adopted": True, "violations": list(violations),
                "reason": f"{len(violations)} qualifying property(ies) fail — the declared source "
                          f"cannot be folded"}
    try:
        rows = read_rows(**fe.read_kwargs(source))
    except Exception as exc:  # noqa: BLE001 — a source fault is REPORTED, never aborts the nightly
        return {"verdict": "alert", "adopted": True,
                "reason": f"declared source unreadable: {type(exc).__name__}: "
                          f"{str(exc).strip()[:200]}"}
    visible, suppressed, stats = fe.visible_clusters(
        rows, as_of=as_of, events_path=proj_path / "events.jsonl")
    cadence_fps = [c["fingerprint"] for c in visible]
    # The on-demand view's OWN output, re-read from the rendered payload (not from `visible` again) —
    # so this compares the two SURFACES, which is what AC2 asks and what a reader actually experiences.
    try:
        rendered = json.loads(fe.to_json(visible, stats, suppressed=suppressed))
        on_demand_fps = [c.get("fingerprint") for c in (rendered.get("clusters") or [])]
    except Exception as exc:  # noqa: BLE001 — an unrenderable view is a DISAGREEMENT, never a silent pass
        return {"verdict": "alert", "adopted": True, "folded": True, "confirmed": len(visible),
                "acked": len(suppressed), "fingerprints": cadence_fps,
                "on_demand_diff": cadence_fps,
                "reason": f"the on-demand view could not be rendered for comparison: {exc}"}
    diff = sorted(set(cadence_fps) ^ set(on_demand_fps))
    # `folded` is the SUBJECT flag and is deliberately NOT the verdict (audit-post finding 0): a source
    # that folded but whose view DISAGREED grades `alert`, and counting subjects by verdict would drop
    # it — so a run that really did fold a source could print the zero-source NO-OP line. That is the
    # AC3 honesty claim breaking in the one direction it must not: an empty run and a folded-but-broken
    # run must never render the same. The count reads THIS flag; `flagged` still reads the verdict.
    entry = {"verdict": "alert" if diff else "ok", "adopted": True, "folded": True,
             "confirmed": len(visible), "acked": len(suppressed),
             "fingerprints": cadence_fps, "on_demand_diff": diff,
             "scanned": stats.get("in_window"), "window_end": stats.get("window_end")}
    if diff:
        entry["reason"] = (f"the cadence fold and the on-demand `frontend-errors` view disagree on "
                           f"{len(diff)} cluster(s) over the same window")
    return entry


SANDBOX_MIN_AGE_HOURS = 24.0
"""T-11089 — the SHARED age past which a sandbox process/dir is REPORTED as an orphan by the host axis.

NOT a tuned number and not taste — it is `worktree sweep --max-age-hours`'s OWN default, so this axis
reports exactly the population the reaper should already have removed and did not. That framing is the
whole point: the axis is a reader for the reaper's SILENT failure (four days of `0 orphan sandbox
process(es)` while 16 were alive, T-11088), so anything the reaper would still consider too young to
touch is not yet this report's business either.

AND THAT FRAMING IS WHY THIS FLOOR IS CONDITIONAL, NOT FLAT (T-11538). At T-11234 the reaper stopped
having one default: a PROCESS whose own sandbox ROOT is provably gone from disk is orphaned
positively from that moment and is taken at `worktree.SWEEP_ORPHAN_PROC_MIN_AGE_HOURS` (0.25h), while
anything whose root still exists keeps the 24h floor because for it age is still the only evidence.
For a while this reader kept a flat 24h and went on justifying it as "the reaper's own default" — a
claim that had quietly stopped being true, which made the report describe a NARROWER population than
the reaper acts on. The fix is to make the claim true again rather than to re-word it: the short
floor is READ from the reaper's own constant at the call site below (never copied, never given an env
knob of its own) and passed as `orphan_retention_sec`, so the belt and the reaper apply ONE rule to
both classes. The belt guarantee is unharmed either way — this axis still only ever REPORTS.

MEASURED against the real host on 2026-08-15, which is busy in exactly the way that would make a
careless threshold cry wolf — seven concurrent workers holding 8 sandbox roots / 1.6 GB. Live working
volume aged 0h, 2.9h, 3.4h, 3.9h, 4.1h, 4.1h, 6.9h; the one genuine leftover was 139h (5.8 days). Age
separates the two populations by 20x. SIZE does not and must not be used: the live dirs are the BIG
ones (340-554 MB each) while the orphan was 52 KB, so a volume threshold would fire on precisely the
healthy case — the way signals in this repo actually die."""


def _orphan_selector():
    """T-11089 — the SINGLE resolution point for the shared orphan predicate, returned as the FUNCTION
    OBJECT (never wrapped).

    This exists so acceptance criterion 3 can be asserted by IDENTITY rather than by resemblance:
    `nightly._orphan_selector() is worktree.select_orphan_sandbox_procs`. A wrapper — or a second
    import site — would let a re-implemented predicate pass a test that only checked behaviour on the
    day it was written, and two definitions of "orphan" drifting apart is the exact defect this axis
    exists to prevent (it would make the belt disagree with the reaper with nobody able to say which
    number is right). Lazy import, the `init`/`deploy` convention, so this runner's top-level imports
    are unchanged."""
    from lib import worktree as _worktree  # noqa: PLC0415 — lazy, like `init`/`deploy`
    return _worktree.select_orphan_sandbox_procs


def _sandbox_dir_volume(base: Path, prefixes) -> tuple:
    """T-11089 — (dirs, bytes) for every direct child of `base` whose name starts with one of
    `prefixes`, paired with its age in seconds. Stdlib walk only — NO subprocess, so the axis cannot
    mutate what it sizes (the `_loose_object_volume` construction, and the structural half of the
    read-only proof). Never raises: a path that vanishes or refuses a stat mid-walk contributes 0
    rather than failing the nightly."""
    now = _time.time()
    out = []
    try:
        children = sorted(base.iterdir())
    except OSError:
        return ([], 0)
    total = 0
    for child in children:
        try:
            if not child.is_dir() or child.is_symlink():
                continue
            if not any(child.name.startswith(p) for p in prefixes):
                continue
            age = max(0.0, now - child.stat().st_mtime)
        except OSError:
            continue
        size = 0
        for p in child.rglob("*"):
            try:
                if p.is_file() and not p.is_symlink():
                    size += p.stat().st_size
            except OSError:
                continue
        out.append({"path": str(child), "age_sec": age, "bytes": size})
        total += size
    return (out, total)


def _check_filesystem_headroom(path: Path, *, _statvfs=None) -> dict:
    """THE THIRD ROTATION READING (T-11631, SPEC-0002 rotation policy / T-11401): how much room is left
    on the VOLUME this repo lives on.

    WHY THIS EXISTS. SPEC-0002 names an on-disk volume reopen axis with THREE readings, and until this
    one landed only two were reported: journal bytes (the SPEC-0052 displacement-retention lens + the
    weekly digest's `journal_growth` block) and the loose-object pile (`_check_repo_storage`, and only
    when a `gc.log` exists). Filesystem headroom was the third, and no v2 surface carried it — so the
    axis the policy names as a reopen trigger was two-thirds observable. The missing third is the one
    that fails HARDEST: a full volume does not degrade, it STOPS.

    WHY NIGHTLY AND NOT THE WEEKLY DIGEST (the card's open question, decided once, here). Three reasons.
    (1) SUBJECT MATCH: headroom is a HOST fact — one volume shared by every project — and this runner
    already carries exactly that shape OUTSIDE its project loop (`_check_backup`,
    `_check_conformance_surfaces`, `_check_host_sandbox`, the last of which already sizes tmp volume).
    The digest's `journal_growth` is a PER-JOURNAL reading of one project's own artifact; a host volume
    figure filed there would be a host fact under a project's name. (2) SIBLING PROXIMITY: the axis's
    OTHER on-disk reading, the loose pile, is already this module's (`_check_repo_storage`). (3)
    CADENCE: nightly is DAILY, the digest WEEKLY, and a reading whose failure mode is abrupt belongs on
    the faster carrier. No THIRD surface was added for the third reading — the card forbids it, and
    this rides the EXISTING `nightly_run_completed` payload and the EXISTING stdout report.

    NOT SUPPRESSED-WHEN-CLEAN — the one place this axis departs from its `_check_repo_storage` /
    `_check_host_sandbox` siblings, deliberately. Those report FINDINGS, where silence means "nothing
    found". This is a READING: a figure someone reads off the run. A suppressed reading is
    indistinguishable from a run that never took it, which is the confusion the frontend-errors cadence
    line already prints through ("silence is never the report"). So the caller prints it EVERY run.

    NO GATE, NO THRESHOLD (CHARTER §P1 F4, and the card's explicit out-of-scope). No floor is chosen,
    the value is compared against nothing, it is folded into NO counter, it never reaches
    `projects_flagged` and it cannot move an exit code. A refusal on disk space is a different decision
    and is not taken here.

    FREE MEANS AVAILABLE-TO-US, not `f_bfree` (absorbed from this task's audit-pre). `f_bavail` counts
    the blocks an UNPRIVILEGED writer may actually use; `f_bfree` additionally counts the root-reserved
    pool an ordinary process can never write into, which on a default ext4 overstates headroom by 5% of
    the volume — precisely the margin this reading exists to watch. `free_pct` is computed from the
    same two numbers it prints beside, so the figure and its percent describe ONE quantity.

    READ-ONLY BY CONSTRUCTION, structurally rather than by promise: one `os.statvfs` call. No
    subprocess, no open-for-write, no unlink — there is no code path here that can change what it
    measures.

    Verdicts: `ok` with the figures, or `unreadable` + a reason when `statvfs` raises (the fail-closed
    READER precedent, `lessons/fail-closed-belongs-to-the-reader-not-the-parser` — a volume we cannot
    ask about is an unanswered question, never a silent figure). Never raises: a reporting run must not
    die on a reading. `_statvfs` is the injection seam (the `_run` / `_selector` shape this module
    already uses) so a test can point the axis at a low-headroom fixture; production passes nothing."""
    statvfs = _statvfs or os.statvfs
    try:
        st = statvfs(str(path))
        frsize = st.f_frsize or st.f_bsize
        total = st.f_blocks * frsize
        free = st.f_bavail * frsize          # AVAILABLE-to-us, not f_bfree — see the docstring
        return {"verdict": "ok", "path": str(path), "total_bytes": total, "free_bytes": free,
                "free_pct": (round(free * 100.0 / total, 2) if total else None)}
    except Exception as exc:  # noqa: BLE001 — mirror the siblings' never-raise report-only posture
        return {"verdict": "unreadable", "path": str(path), "total_bytes": None, "free_bytes": None,
                "free_pct": None, "reason": f"statvfs failed — {exc}"}


def _check_host_sandbox(*, now: _dt.datetime, engine_root: Path, min_age_hours=None, globs=None,
                        tmp_base=None, _selector=None, _scan=None, _age_of=None,
                        _prefixes=None) -> dict:
    """THE HOST axis (T-11089, SPEC-0105 §1 read-only health): how many orphan verify-sandbox PROCESSES
    are alive on this host past the age floor, and how much disk the sandbox directories hold.

    WHY THIS EXISTS EVEN THOUGH THE REAPER NOW WORKS. For four days `worktree sweep` printed `0 orphan
    sandbox process(es)` while 16 were alive and holding ~2 GB: its identity scan could not see an
    nginx master's setproctitle argv, so it reported SUCCESS while doing nothing (T-11088 fixed that
    instance). A mechanism that fails silently needs a reader that is NOT itself — so the next silent
    zero is contradicted by an independent count from a different carrier, on a different schedule,
    rather than believed. That is this axis's entire claim; it is the belt for the reaper's own
    observed failure mode.

    IT REPORTS, IT NEVER KILLS. Killing is `worktree sweep`'s job, and putting both in one place would
    make a REPORTING run mutate the host. Structurally, not by promise: this calls the shared
    SELECTION function only (`_orphan_selector()` → `worktree.select_orphan_sandbox_procs`, which
    opens and signals nothing) and sizes dirs with a stdlib walk — there is no code path here that can
    signal a process or unlink a path. The task's acceptance proves it by STATE COMPARISON (the
    planted orphan is still running and its directory still present afterwards), not by "no error was
    raised".

    ONE ORPHAN DEFINITION, TWO COHORTS. The predicate is the reaper's own, reused not restated. The
    COHORT differs by design: the sweep passes its single `/tmp/yitc-verify-sandbox-*` KILL glob, while
    this axis passes the FULL derived tmp cohort — `worktree._created_tmp_prefixes`, read from the
    creation sites rather than hand-listed, so a newly added creator cannot be silently missed
    (T-10855's lesson, applied to the reader). That is what brings `/tmp/yitc-pinned-verify-*` — named
    in this card's scope, and never reaped by Category C — under a reader. Reporting wider than the
    reaper reaps is the correct asymmetry for a belt; the reverse would not be.

    Verdicts follow the `_check_repo_storage` sibling vocabulary:
      * no orphan process AND no data-holding stale dir -> ok, no findings (suppressed-when-clean:
        prints nothing; an EMPTY leftover husk past the floor is counted as context, never an alarm —
        see the trigger comment below for the measurement behind that)
      * either present                     -> alert, one finding per kind, each naming its subject
      * `/proc` unscannable                -> alert + `unreadable` (the fail-closed READER precedent,
        `lessons/fail-closed-belongs-to-the-reader-not-the-parser`) — a host we cannot ask about is an
        unanswered question, never a silent ok.

    THE FLOOR IS CONDITIONAL, AND IT IS THE REAPER'S (T-11538). `SANDBOX_MIN_AGE_HOURS` (see there
    for the measurement) is the SHARED floor; a process whose sandbox ROOT is PROVABLY GONE from disk
    takes the reaper's own much shorter `worktree.SWEEP_ORPHAN_PROC_MIN_AGE_HOURS` instead, in BOTH
    the `-p` and the identity-less resident cohort. One rule, decided by one fact, applied by reader
    and reaper alike — which is what makes "the population the reaper should already have removed"
    an accurate description of what this axis reports rather than a stale claim about a flat default.
    Both applied floors are on the payload (`min_age_hours` / `orphan_min_age_hours`). `min_age_hours` / `globs` /
    `tmp_base` / `_prefixes` are the INJECTION SEAM, mirrored by the env vars
    `YITC_NIGHTLY_SANDBOX_MIN_AGE_HOURS` / `YITC_NIGHTLY_SANDBOX_TMP_BASE` /
    `YITC_NIGHTLY_SANDBOX_PREFIXES` so a CLI-level test can point the whole axis at its own fixture
    instead of the host's /tmp — the `_tmp_base` / `_sandbox_prefix_glob` shape `worktree sweep`
    already uses, expressed for a subprocess run. Production passes and sets none of them.

    NAMING NOTE (so a later reader does not "tidy" it back): the injected predicate is named
    `_selector`, never the shorter verb form, because `test_t9597`'s kernel-purity guard bans that
    verb followed by a space anywhere in this module — its subject is SQL, but the shorter name
    followed by ` or …` trips it just as well, and the failure then reads as a project-specific
    source format leaking into the kernel. The token is deliberately not written out here either.
    Deviation captured under `kernel-purity-substring-guard-collides-with-unrelated-identifier`."""
    from lib import worktree as _worktree  # noqa: PLC0415 — lazy, like `init`/`deploy`
    import tempfile as _tempfile

    min_age_hours = float(min_age_hours if min_age_hours is not None
                          else os.environ.get("YITC_NIGHTLY_SANDBOX_MIN_AGE_HOURS")
                          or SANDBOX_MIN_AGE_HOURS)
    retention_sec = min_age_hours * 3600.0
    # ONE cohort, expressed twice: the tmp BASE + the name PREFIXES are the truth, and the process
    # globs are derived from them, so the process half and the volume half can never scan different
    # populations. Prefixes are DERIVED from the creation sites (`_created_tmp_prefixes`), never
    # hand-listed here — a newly added sandbox creator is picked up without editing this reader
    # (T-10855's own lesson, which is how `yitc-verify-sandbox-*` came to be missed in the first place).
    base = Path(tmp_base if tmp_base is not None
                else os.environ.get("YITC_NIGHTLY_SANDBOX_TMP_BASE") or _tempfile.gettempdir())
    if _prefixes is not None:
        prefixes = tuple(_prefixes)
    elif (env_pref := os.environ.get("YITC_NIGHTLY_SANDBOX_PREFIXES")):
        prefixes = tuple(env_pref.split(":"))
    else:
        prefixes = _worktree._created_tmp_prefixes(Path(engine_root))
    if globs is None:
        globs = tuple(f"{base}/{p}*" for p in prefixes)

    # T-11538 — THE PROVEN-ORPHAN SHORT FLOOR, READ FROM THE REAPER'S OWN CONSTANT. This is the
    # whole of the reader-side fix and it deliberately introduces NO tunable of its own: the value is
    # `worktree.SWEEP_ORPHAN_PROC_MIN_AGE_HOURS`, the same object `cmd_worktree_sweep` passes, so a
    # future change to the reaper's floor moves this report with it and the two cannot drift into
    # describing different populations (the `_orphan_selector()` identity discipline, applied to the
    # floor instead of the predicate). `min(...)`, never `max(...)`, mirroring the sweep: the short
    # floor may only ever SHORTEN the wait, so an operator who lowers the belt's own floor below it
    # (via `YITC_NIGHTLY_SANDBOX_MIN_AGE_HOURS`, the fixture seam) is honoured rather than silently
    # raised back up.
    orphan_min_age_hours = min(min_age_hours, _worktree.SWEEP_ORPHAN_PROC_MIN_AGE_HOURS)

    selector = _selector or _orphan_selector()
    scan = _scan or _worktree._scan_procs
    try:
        procs = scan() or []
    except Exception as exc:  # noqa: BLE001 — mirror the siblings' never-raise report-only posture
        return {"verdict": "alert", "unreadable": True, "findings": [], "orphans": 0,
                "min_age_hours": min_age_hours, "orphan_min_age_hours": orphan_min_age_hours,
                "reason": f"/proc could not be scanned — the host's orphan count is UNKNOWN, "
                          f"not zero ({exc})"}
    sel = selector(procs, retention_sec=retention_sec, globs=globs,
                 self_pid=os.getpid(), uid=os.geteuid(),
                 age_of=_age_of or _worktree._proc_start_age_sec,
                 orphan_retention_sec=orphan_min_age_hours * 3600.0)

    dirs, total_bytes = _sandbox_dir_volume(base, prefixes)
    past_floor = [d for d in dirs if d["age_sec"] >= retention_sec]
    # AN EMPTY HUSK IS NOT A BURNING SERVER (measured 2026-08-15, and this is what keeps the axis
    # alive past its first week). Past the floor the real host holds 13 leftover dirs — and TWELVE of
    # them are 0 bytes, husks whose contents the dir sweep already removed, with the thirteenth at 198
    # bytes. Alerting on those every night is precisely how a signal in this repo dies: it becomes the
    # line nobody reads. So the VOLUME trigger is "a stale dir that still HOLDS DATA", a natural zero
    # point rather than a tuned threshold — no invented number to defend, and nothing to re-tune as
    # the host grows. Empty husks are still COUNTED and carried on the payload as context, so the
    # class stays visible to anyone who looks; they just do not raise an alarm.
    stale_dirs = [d for d in past_floor if d["bytes"] > 0]
    # A REPORTED ORPHAN'S OWN ROOT IS ALWAYS SIZED, whatever its mtime says (audit-post finding 1).
    # The age floor exists to tell an orphan from live working volume — but for these dirs the
    # PROCESS has already answered that question, and answered it with a better witness than a
    # timestamp. Without this an old orphan whose root was touched inside the floor (a lingering
    # write, a `find`, any mtime refresh) would be counted as a process while the volume it holds
    # went unreported — the axis contradicting itself in the one case it exists for. Unrelated dirs
    # stay gated by the floor, so this widens nothing else.
    held_roots = set()
    for _pid, pref, _age in sel["candidates"]:
        for g in globs:
            root = _worktree._sandbox_resident_root(pref, g)
            if root:
                held_roots.add(root)
                break
    named = {d["path"] for d in stale_dirs}
    for d in dirs:
        if d["path"] in held_roots and d["path"] not in named:
            stale_dirs.append(d)
            named.add(d["path"])
    stale_bytes = sum(d["bytes"] for d in stale_dirs)
    empty_husks = len([d for d in past_floor if d["bytes"] == 0 and d["path"] not in held_roots])

    # T-11217 — BOTH reap cohorts, because the belt's question is "how many orphans did the reaper
    # leave behind?" and the sweep now reaps two classes. An orphan RESIDENT (no `-p`, sandbox root
    # provably gone) used to land in `residents` and be counted as an `unclassified_residents`
    # observation; now it is classified and reapable, so counting it there and nowhere here would make
    # this belt go blind on exactly the class the reaper was just taught to take. The predicate is
    # still the one shared function — only which of its buckets this reader sums has changed.
    orphans = [{"pid": pid, "prefix": pref, "age_hours": round(age / 3600.0, 1)}
               for pid, pref, age in [*sel["candidates"], *sel["orphan_residents"]]]
    findings = []
    if orphans:
        findings.append({"kind": "orphan-sandbox-processes", "count": len(orphans),
                         "oldest_age_hours": max(o["age_hours"] for o in orphans),
                         "processes": orphans})
    if stale_dirs:
        findings.append({"kind": "stale-sandbox-volume", "count": len(stale_dirs),
                         "bytes": stale_bytes,
                         "oldest_age_hours": round(max(d["age_sec"] for d in stale_dirs) / 3600.0, 1),
                         "dirs": [{"path": d["path"], "bytes": d["bytes"],
                                   "age_hours": round(d["age_sec"] / 3600.0, 1)} for d in stale_dirs]})
    reason = ""
    if findings:
        reason = (f"{len(orphans)} orphan sandbox process(es) and {len(stale_dirs)} sandbox dir(s) "
                  f"holding {stale_bytes} bytes are past their floor ({orphan_min_age_hours}h for a "
                  f"process whose sandbox root is provably gone, {min_age_hours}h otherwise) — the "
                  f"reaper should already have removed them")
    return {"verdict": "alert" if findings else "ok", "findings": findings,
            "orphans": len(orphans), "stale_dirs": len(stale_dirs), "stale_bytes": stale_bytes,
            "stale_empty_dirs": empty_husks,
            "total_dirs": len(dirs), "total_bytes": total_bytes,
            # T-11538 — the report SAYS WHICH FLOORS it applied. A conditional floor that is not on
            # the payload would leave a reader unable to tell a quiet night from a floor that moved,
            # which is the same no-silent-zero discipline this axis exists for.
            "min_age_hours": min_age_hours, "orphan_min_age_hours": orphan_min_age_hours,
            "cohort": list(globs),
            "unclassified_residents": len(sel["residents"]),
            **({"reason": reason} if reason else {})}


VENUE_IDLE_BUFFER_MIN = 15.0


def venue_idle_buffer_min() -> float:
    """T-12219 — the idle buffer, machine file first, `VENUE_IDLE_BUFFER_MIN` otherwise.

    SPEC-0203 rule 6 and its §Parameters already NAME this a machine-scoped performance tunable
    under `config`; until T-12219 it was a bare constant, so the spec described a knob that did not
    exist. It sets how long every repo on this machine must be free of in-progress work before the
    box is torn down — a cost/teardown timing value that can never change what a pass concludes."""
    try:
        from lib import machine_settings      # deferred: keeps the hot import graph unchanged
        return float(machine_settings.resolve("lib.nightly.VENUE_IDLE_BUFFER_MIN",
                                              VENUE_IDLE_BUFFER_MIN))
    except Exception:            # noqa: BLE001 — the settings STACK is never a
                                 # prerequisite either (SPEC-0193 rule 6 — the
                                 # `remote_workers_override` precedent)
        return VENUE_IDLE_BUFFER_MIN
"""The SPEC-0203 rule-6 IDLE BUFFER, in minutes — the pause after which a machine with nothing in
progress has plainly finished a work window rather than paused inside one.

IT IS A COST SHAPE, NOT A SAFETY MARGIN, and that is why the number is 15 rather than tuned: a
started provider hour is billed WHOLE and a re-raise from the snapshot costs about a minute, so
deleting a minute too early re-bills nothing inside an hour already paid for, while holding a box
across a quiet night costs whole hours. The DELETING half of rule 6 belongs to the compute-controller
session (`patterns/compute-controller-session.md`); this constant exists here for the nightly's
report-only belt, which asks the same question once a night."""


def _live_writing_branches(proj_path: Path, *, _run) -> "list[str] | None":
    """The `task/`+`work/` branches with a LIVE worktree in this repo — or None when git could not
    be asked.

    WHY THE WORKTREE LIST IS LOAD-BEARING and the task cards alone are not: a claim is written INSIDE
    the claiming worktree and reaches `main` only at land (AGENTS-SESSIONS §Writes happen in a
    worktree), so a machine with a worker mid-build reads `in-progress: 0` on every card while real
    work is running. Reading both is what makes "nothing is in progress on this machine" a claim
    rather than a guess.

    None, never [], on a git fault — the caller must be able to tell "no live claim" from "could not
    ask", because only the first proves idleness (`lessons/fail-closed-belongs-to-the-reader-not-the-parser`).
    A branch shape wider than `task/` is deliberate: a `work/<slug>` batch is work in flight too, and
    the T-11352 sibling in `bin/lib/cli.py` widened for exactly this reason."""
    try:
        r = _run(["git", "-C", str(proj_path), "worktree", "list", "--porcelain"],
                 capture_output=True, text=True, timeout=60)
    except Exception:  # noqa: BLE001 — the siblings' never-raise report-only posture
        return None
    if getattr(r, "returncode", 1) != 0:
        return None
    out, cur = [], None
    for line in (r.stdout or "").splitlines():
        if line.startswith("worktree "):
            cur = line[len("worktree "):].strip()
        elif line.startswith("branch ") and cur:
            ref = line.strip()[len("branch "):]
            if ref.startswith("refs/heads/"):
                branch = ref[len("refs/heads/"):]
                if branch.startswith(("task/", "work/")) and len(branch) > 5:
                    out.append(branch)
            cur = None
    return out


def _journal_readability(path: Path) -> str:
    """`absent` | `readable` | `unreadable` for one journal — asked BEFORE the fold, deliberately.

    WHY THIS IS NOT A `try` AROUND THE READ. The shared segment reader is FAIL-OPEN by contract: a
    journal that is a directory, or one whose permissions deny the read, comes back as `[]` and
    raises NOTHING (measured). For most callers that is right — a broken journal must not fail a
    report-only run — but for THIS caller `[]` and "no activity" are the same bytes and OPPOSITE
    conclusions: one is an unanswered question, the other is proof the machine is idle. Asking
    first is what keeps an unreadable journal from grading as a quiet one (T-12198 audit-post
    finding; the general rule is `lessons/fail-closed-belongs-to-the-reader-not-the-parser`).

    A path that does not exist is `absent` — a real answer (this repo recorded nothing). A path that
    exists but is not a regular file, or cannot be opened for reading, is `unreadable` — a fault."""
    try:
        if not path.exists():
            return "absent"
        if not path.is_file():
            return "unreadable"
        with path.open("rb"):
            return "readable"
    except OSError:
        return "unreadable"


VENUE_ACTIVITY_WINDOW_H = 24.0
"""The bounded horizon `_machine_idle_for_min` declares when it asks the journals how long this
machine has been quiet (SPEC-0190 rule 4 — a reader states its horizon rather than folding every
archive segment). It only has to be comfortably wider than the idle buffer above: a window with NO
governed event in it already proves the machine has been quiet for LONGER than the window, which is
all the idle arm needs to conclude."""


def _machine_idle_for_min(results, *, now: _dt.datetime) -> "tuple[float | None, list]":
    """HOW LONG this machine has had no governed activity, in minutes — the DURATION the idle arm
    needs, derived read-only from durable state that already exists.

    WHY THIS AND NOT PUBLICATION AGE (audit-pre finding, T-12198). "Published longer ago than the
    buffer" is not the buffer rule 6 asks for: a box published hours ago whose worker stopped one
    minute ago would satisfy it, and the finding would fire on a machine that has barely paused. The
    question is how long the machine has been INACTIVE, so this measures exactly that — the age of
    the newest governed event across the v2 journals on this machine.

    NOTHING NEW IS STORED (CHARTER §P1 F2/F3). Every project's `events.jsonl` already records every
    governed action with a timestamp, and this run already folds those journals read-only for its
    other duties — so the last-work-completion signal is a VIEW over durable state that exists, not a
    new activity file, marker or daemon. Read through `journal.segment_rows_since` on a declared
    horizon (`VENUE_ACTIVITY_WINDOW_H`), never as one file (SPEC-0190 rule 4).

    RETURNS `(idle_for_min, unreadable_repos)`. An EMPTY window is not missing data — it PROVES the
    machine has been quiet for at least the whole window, so it returns the window itself as the
    (lower-bound) idle duration. `None` is returned only when NO repo could be consulted at all,
    which is genuinely UNKNOWN.

    ABSENT IS NOT UNREADABLE, and the two are separated by `_journal_readability` BEFORE the fold
    (see there for why a `try` around the read cannot do it). A repo with NO
    `events.jsonl` has recorded no activity — an ANSWER, contributing nothing to the newest-event
    fold. A journal that EXISTS and cannot be READ is a FAULT: that repo may have been busy all
    night, so it is reported through `unreadable_repos` and the caller stays silent rather than
    calling an unproven machine idle (`lessons/fail-closed-belongs-to-the-reader-not-the-parser`)."""
    from lib import journal as _journal  # noqa: PLC0415 — lazy leaf, the `views`/`debt`/`cross` idiom

    window_min = VENUE_ACTIVITY_WINDOW_H * 60.0
    since = now - _dt.timedelta(hours=VENUE_ACTIVITY_WINDOW_H)
    newest, unreadable, read_any = None, [], False
    for r in results:
        if not r.get("present"):
            continue
        # ABSENT is not UNREADABLE, and the difference decides the finding — so it is made EXPLICIT
        # here rather than left to depend on what the reader happens to return for a missing path.
        # A repo with NO journal has recorded no activity: that is an ANSWER (it contributes nothing
        # and the machine can still be proven quiet). A journal that EXISTS and cannot be read is a
        # FAULT: its repo may have been busy all night and the reading would be a guess, so it
        # suppresses the finding through `unreadable`.
        journal_path = Path(r["path"]) / "events.jsonl"
        state = _journal_readability(journal_path)
        if state == "unreadable":
            unreadable.append(r["name"])
            continue
        if state == "absent":
            read_any = True
            continue
        try:
            rows = _journal.segment_rows_since(journal_path, since)
        except Exception:  # noqa: BLE001 — one project's bad journal never fails a report-only duty
            unreadable.append(r["name"])
            continue
        read_any = True
        for row in rows:
            raw = str((row or {}).get("ts") or "")
            try:
                ts = _dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                continue
            if newest is None or ts > newest:
                newest = ts
    if not read_any:
        return None, unreadable
    if newest is None:
        return window_min, unreadable
    return max(0.0, round((now - newest).total_seconds() / 60.0, 1)), unreadable


def _check_forgotten_box(results, *, now: _dt.datetime, idle_buffer_min=None,
                         _read_record=None, _list_servers=None, _provider_configured=None,
                         _idle_for=None, _run=subprocess.run) -> dict:
    """THE FORGOTTEN-BOX BELT (T-12198, SPEC-0203 rule 6): is a rented compute box still up with
    nothing left for it to do?

    WHY A NIGHTLY LINE AND NOT A WATCHER. Rule 6 gives the box to an ordinary owner-started
    Controller session (`patterns/compute-controller-session.md`), whose delete condition is a
    durable-state READ; nothing polls, and CHARTER §6 retires the daemon that would. But a session
    can be closed with the box still up, and the box is billed by the started hour — a failure that
    is expensive and completely SILENT. So the belt is the cheapest thing that bounds it: one
    report-only reading, once a night, so a box is forgotten for at most one night. It REPORTS and
    never acts — deleting stays the compute-controller session's, on the owner's cue.

    TWO FINDINGS, because a box can be lost in two directions:
      * `venue-idle-past-buffer`  — a PUBLISHED venue, published longer ago than the buffer, with
        nothing in progress anywhere on this machine.
      * `unpublished-live-box`    — a LIVE labelled box with no publication record at all: nothing
        routes to it, so nobody's land will ever notice it exists.

    THE IDLE READ IS STATELESS AND REUSES THE RUN'S OWN READS. "No task in-progress in ANY repo on
    this machine" is the task cards across the registry's v2 projects — already counted by
    `_check_queue`, so this consumes `results` rather than re-walking `tasks/` — PLUS one
    `git worktree list --porcelain` per project for the claims that have not landed yet
    (`_live_writing_branches`, and see there for why the cards alone are not enough).

    THE BUFFER IS MEASURED, NOT PROXIED. The idle arm asks rule 6's actual question — has this
    machine been idle FOR longer than the buffer — and answers it from `_machine_idle_for_min`, the
    age of the newest governed event across this machine's journals. A single nightly sample cannot
    see a duration by itself, which is why the duration is DERIVED from durable state rather than
    proxied by publication age: "published longer ago than the buffer" would fire on a machine whose
    worker stopped a minute ago (audit-pre finding, T-12198). Publication age is still reported as
    context, but it no longer gates the finding.

    FAIL-CLOSED TOWARD SILENCE ON THE IDLE ARM. If any project's worktree list or journal could not
    be read, or no journal could be read at all, the machine's idleness is UNKNOWN, so the idle
    finding is NOT raised — an unproven idleness must never
    print as a forgotten box. The unanswered question is reported in its place, and only when a record
    exists (with no venue there is nothing at stake).

    `_read_record` / `_list_servers` / `_provider_configured` / `_idle_for` are the INJECTION SEAM (the
    `_check_host_sandbox` `_selector` / `_scan` shape): the provider call and the record read are the
    two host-facing reads, so a test drives the whole axis with neither network nor token. Production
    passes none of them. NO env knob is minted here — the injection is the test seam, and the buffer
    is the module constant above until rule 6's `config` tunable exists to read."""
    from lib import venue as _venue  # noqa: PLC0415 — lazy, like `init`/`deploy`

    buffer_min = float(idle_buffer_min if idle_buffer_min is not None else venue_idle_buffer_min())
    read_record = _read_record or _venue.read_record
    list_servers = _list_servers or _venue.list_servers
    if _provider_configured is None:
        def _provider_configured():
            path = (os.environ.get(_venue.TOKEN_FILE_ENV) or "").strip() or _venue.TOKEN_FILE_DEFAULT
            return Path(path).is_file()

    record, record_reason = read_record()

    # The provider half. A host with no API token has not adopted the venue at all — that is `none`
    # (the `_check_project_health` non-adopted vocabulary), never an alert: an un-adopted axis that
    # alarmed nightly would be the line nobody reads.
    configured = bool(_provider_configured())
    live_boxes, provider_reason = [], ""
    if configured:
        try:
            live_boxes = [{"id": b.get("id"), "name": b.get("name"), "status": b.get("status")}
                          for b in (list_servers() or [])]
        except Exception as exc:  # noqa: BLE001 — never raise out of a report-only duty
            provider_reason = (f"the provider could not be asked which boxes are live "
                               f"({exc.__class__.__name__}) — the live-box count is UNKNOWN, not zero")
    elif record is None:
        return {"verdict": "none", "findings": [], "live_boxes": 0, "published": False,
                "idle_buffer_min": buffer_min,
                "reason": "no provider API token on this host — the verify venue (SPEC-0203) is not "
                          "adopted here; nothing to forget"}

    # The machine-idle half — cards this run already counted, plus the live writing worktrees.
    in_progress_cards, live_claims, unreadable_repos = [], [], []
    for r in results:
        if not r.get("present"):
            continue
        count = ((r.get("queue") or {}).get("counts") or {}).get("in-progress", 0)
        if count:
            in_progress_cards.append({"project": r["name"], "count": count})
        branches = _live_writing_branches(Path(r["path"]), _run=_run)
        if branches is None:
            unreadable_repos.append(r["name"])
        else:
            live_claims.extend({"project": r["name"], "branch": b} for b in branches)
    idle_for_min, unreadable_journals = (_idle_for or _machine_idle_for_min)(results, now=now)
    unreadable_repos.extend(n for n in unreadable_journals if n not in unreadable_repos)
    # Idleness is a CLAIM, so every leg of it must be answerable: no live claim anywhere, no card in
    # progress, AND a readable duration. `idle_for_min is None` means no journal could be read at all
    # — unknown, never idle.
    idle_known = not unreadable_repos and idle_for_min is not None
    idle = idle_known and not in_progress_cards and not live_claims

    published_age_min = None
    if record:
        raw = str(record.get("published_at") or "")
        try:
            published_age_min = round(
                (now - _dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))).total_seconds() / 60.0, 1)
        except (ValueError, TypeError):
            published_age_min = None

    findings = []
    if record and idle and idle_for_min >= buffer_min:
        findings.append({
            "kind": "venue-idle-past-buffer",
            "server_id": record.get("server_id"), "box": record.get("box"),
            "published_at": record.get("published_at"),
            "published_age_min": published_age_min,
            "idle_for_min": idle_for_min,
            "published_by": record.get("published_by"),
            "idle_buffer_min": buffer_min,
        })
    published_ids = {record.get("server_id")} if record else set()
    for box in live_boxes:
        if box["id"] not in published_ids:
            findings.append({"kind": "unpublished-live-box", "server_id": box["id"],
                             "name": box["name"], "status": box["status"]})

    reasons = []
    if findings:
        reasons.append(
            f"{len(findings)} forgotten-box finding(s) — a rented box is up with nothing routing to "
            f"it (buffer {buffer_min:g} min; REPORT-ONLY — deleting is the compute-controller "
            f"session's, `patterns/compute-controller-session.md`)")
    if record_reason:
        reasons.append(record_reason)
    if provider_reason:
        reasons.append(provider_reason)
    if record and not idle_known:
        detail = (f"{len(unreadable_repos)} repo(s) could not be read "
                  f"({', '.join(sorted(unreadable_repos))})" if unreadable_repos
                  else "no journal on this machine could be read for its last governed activity")
        reasons.append(f"a venue is published but {detail} — the machine's idleness is UNKNOWN, so "
                       f"the idle finding was NOT raised")
    verdict = "alert" if (findings or record_reason or provider_reason
                          or (record and not idle_known)) else "ok"
    return {"verdict": verdict, "findings": findings,
            "published": bool(record), "server_id": (record or {}).get("server_id"),
            "published_age_min": published_age_min,
            "live_boxes": len(live_boxes), "provider_configured": configured,
            "idle": idle, "idle_known": idle_known, "idle_for_min": idle_for_min,
            "in_progress_cards": in_progress_cards, "live_claims": live_claims,
            "unreadable_repos": unreadable_repos,
            "idle_buffer_min": buffer_min,
            **({"reason": " | ".join(reasons)} if reasons else {})}


# ── SPEC-0105 §2c / SPEC-0077 §3b — THE QUIET LANE for wall-clock timing instruments (T-12038) ────
#
# A wall-clock timing instrument cannot be read honestly on the per-land pinned path: the reading
# there is taken inside a parallel verify on a loaded shared host, so it measures the host together
# with its subject (the rule home is SPEC-0077 §3b — not restated here). This lane is where the same
# question is asked under conditions that make the answer mean something: once a night, instruments
# run ONE AT A TIME, with no land verify running beside them, and the reading is RECORDED rather than
# gated on.
#
# It is a once-per-run duty OUTSIDE the project loop — the `_check_backup` / `_archive_transcripts` /
# `_check_host_sandbox` shape — because its subject is the shared HOST, not any one project.

TIMING_INSTRUMENT_EVENT = "timing_instrument_reading"
"""The SPEC-0025 catalog type this lane emits — named as a module constant so the spec, the emitter
and the fold that reads the baseline back all resolve ONE token (and so `events.known_event_types`
picks it up from the emit call site below without a hand-maintained list)."""

_TIMING_INSTRUMENTS = (
    {"id": "t11451-coupled-bite-proof",
     "path": "tests/test_t11451_journal_length_decoupling.py",
     "leg": "test_the_differential_detects_a_still_coupled_file"},
    {"id": "t11808-shim-wall-clock-leg2",
     "path": "tests/test_t11808_shim_argv_not_truncated.py",
     "leg": "test_ac3_the_shim_stays_cheap_and_the_measurement_can_show_a_regression"},
)
"""THE REGISTRY — the wall-clock legs this lane runs, each named by FILE and by the LEG's own function
name.

NAMED BY FUNCTION, NOT BY FILE ALONE, and that is what makes an entry checkable: a registry that said
only "run this file" could not be told apart from a stale one after the leg was renamed or removed,
and the lane would go on reporting a reading for something that no longer exists. The leg name is
resolved in the file it names (`tests/test_t12038_quiet_lane.py` asserts exactly this, with an entry
naming a non-existent leg as its differential), so a rename that forgets this registry FAILS rather
than silently emptying the lane.

Membership is deliberately a KERNEL constant and not a per-project declaration: these two instruments
are the engine's OWN, they live in the engine's `tests/`, and there is nothing here for a consumer to
adopt — the SPEC-0105 §1c precedent for a check whose scope is not a function of who opted in."""

_QUIET_LANE_TIMEOUT = 900
"""Seconds one instrument may run before the lane kills it and records a `failed` reading.

A bound, not a budget: an instrument that hangs must not hold the verify-admission pool all night,
and the whole point of the lane is that a land can proceed after it. A kill records a reading naming
the timeout — never silence, and never a duration that would enter the baseline."""

_QUIET_LANE_MIN_SLOTS = 16
"""FALLBACK width — how many admission slots the lane holds when NO pool-width injector is supplied.

NOT the normal path. Under `cmd_nightly` the host injects `_verify_pool_width`, the SAME host-derived
SPEC-0132 pool width a land derives, and the lane holds EXACTLY that many slots (SPEC-0105 §2c) — a
guess is not needed when the real number is available. This constant is the BELT for the callers that
have no host to ask: a direct call to `_run_quiet_lane` / `_hold_quiet_lane_slots` (tests, and any
future non-`cmd_nightly` caller), and a `cmd_nightly` whose injected width could not be measured.

Sixteen because a land packs onto the LOWEST FREE slot (`worktree._verify_admission` tries 0,1,2,… in
order), so holding a prefix is what excludes it, and the prefix must be at least as long as the slot
count a land derives — which this module cannot compute UNAIDED, being a stdlib+lib.state leaf that
never back-imports the host where `_verify_worker_bound` lives. Sixteen is comfortably above the
configured pool this repo has run at. In the fallback it is NOT a claim to be exact, which is why it
is paired with the probe below rather than trusted on its own."""

_QUIET_LANE_PROBE_SLOTS = 8
"""How far PAST the held prefix the lane probes for an intruding land, before and after each run.

The BELT that is kept on BOTH paths — with the injected host-derived width as well as with the
fallback above — because the width is measured ONCE, at hold time, and the host's resource headroom
that produced it keeps moving underneath. If a land derived MORE slots than the lane holds, it fails
on every slot the lane took and packs onto the first one past them — so a held slot in this window is
a verify running beside us, and the reading taken under it is not a quiet-host reading. It is
recorded `skipped` with that reason rather than reported as a number, because a number taken under a
concurrent verify is exactly the reading this whole lane exists to stop producing."""

_QUIET_LANE_RETRY_WINDOW = 2700
"""Seconds the lane keeps RE-TRYING for a free verify-admission pool before it gives up (45 min).

A BOUND, NOT A BUDGET, and it exists because a single fixed attempt could not accrue anything. The
lane's first two readings ever — 2026-09-04T22:04:36Z, both instruments — were both `skipped` on «the
verify-admission pool is not free», taken on a night when the serialized land queue happened to run
through the nightly's minute. Against a queue that lands around the clock, one attempt per night can
miss indefinitely, and the >= 7 CONSECUTIVE readings per instrument that the de-pin phase needs then
never accrue (T-12154; the phase is T-12038's).

Forty-five minutes because the nightly's other duties are already done by then and the window has to
be long enough to outlast an ordinary land verify (minutes) plus the queue behind it, while still
ending inside the night rather than drifting into the working day. When it closes without a free pool
the outcome is UNCHANGED — a `skipped` row with its reason. Waiting is not measuring: nothing is run
under load, so the fail-safe of SPEC-0105 §2c is untouched and only WHEN the attempt happens moved."""

_QUIET_LANE_RETRY_INTERVAL = 60


def _quiet_lane_retry_interval() -> int:
    """T-12219 — the quiet-lane retry cadence, machine file first, the constant otherwise. It spaces
    the retries; the WINDOW they must finish inside (`_QUIET_LANE_RETRY_WINDOW`) stays gate-class."""
    try:
        from lib import machine_settings      # deferred: keeps the hot import graph unchanged
        return int(machine_settings.resolve("lib.nightly._QUIET_LANE_RETRY_INTERVAL",
                                            _QUIET_LANE_RETRY_INTERVAL))
    except Exception:            # noqa: BLE001 — the settings STACK is never a
                                 # prerequisite either (SPEC-0193 rule 6 — the
                                 # `remote_workers_override` precedent)
        return _QUIET_LANE_RETRY_INTERVAL
"""Seconds between attempts to take the pool.

Sixty because the thing being waited for is a land VERIFY, which runs for minutes — polling faster
would spend attempts without changing the answer, and each attempt is a real all-or-nothing flock
sweep over the pool. Coarse enough to be nearly free, fine enough that the lane starts within a
minute of the queue draining."""

_QUIET_LANE_BASELINE_READINGS = 7
"""How many of an instrument's PRIOR readings the regression baseline is taken over (the card's 7)."""

_QUIET_LANE_BASELINE_HORIZON_DAYS = 30
"""How far back `_prior_readings` OPENS SEGMENT FILES before it widens to the whole journal (T-12213).

A PRE-FILTER BOUND, NEVER A SEMANTIC WINDOW, and the distinction is the whole reason this constant is
safe to add. It never decides which readings COUNT — `_prior_readings` still answers "the last
`_QUIET_LANE_BASELINE_READINGS` ok readings", whenever they were taken. It decides only which segment
FILES are opened FIRST, and the widen branch there restores the full fold whenever that guess was
short. So changing this number can change how long the fold takes and can NEVER change the baseline.

THIRTY BECAUSE THE BASELINE IS A COUNT AND THE HORIZON IS A DATE, so the number has to cover the worst
plausible conversion between them. Seven nightly readings need at least seven nights; readings are
`skipped` whenever the host is not quiet (2 of the first 6 rows on this engine were), so at the
observed rate seven OK readings can take ~11 nights. Thirty days is ~4x the nominal need — wide enough
that the widen branch is the exception rather than the rule once the lane is established, and still
narrow enough to skip the long archive tail."""

_QUIET_LANE_REGRESSION_PCT = 10.0
"""Percent above the trimmed-median baseline at which a reading is MARKED a regression.

Marked, never enforced: this moves no verdict and no exit code (SPEC-0105 §2c). It is a reading for a
reader."""


def _quiet_lane_pool_dir(main_wt: Path) -> Path:
    """The repo's EXISTING SPEC-0132 verify-admission slot-pool directory.

    DERIVED THE SAME WAY `worktree._verify_slot_dir` DERIVES IT, and re-stated here for a layering
    reason rather than a preference: this module is a stdlib+`lib.state` leaf that never back-imports
    the host, and the pool's owner lives in the host-side `worktree` module. The alternative — an
    injected collaborator — would have to be threaded through `cli.py`'s residue, which this change
    does not own.

    A second derivation of a shared convention is drift-CAPABLE (SPEC-0067), so it is not left to
    trust: `tests/test_t12038_quiet_lane.py` asserts this function and `worktree._verify_slot_dir`
    return the SAME path for the same root, and fails the moment either convention moves. Never
    creates the directory — an absent pool means no land has ever verified here, which is a legitimate
    "free" answer, not something to materialize."""
    import hashlib
    key = hashlib.sha1(os.path.realpath(str(main_wt)).encode("utf-8")).hexdigest()[:16]
    from lib import events                # deferred: keeps this module's hot import graph unchanged
    # T-12185: the PRE-LEVER temp base, in step with `worktree._verify_slot_dir`. The drift test that
    # pins these two conventions equal keeps them in step.
    return events.pre_lever_temp_base() / "yitc-verify-slots" / key


def _quiet_lane_intruder(pool_dir: Path, held_count: int) -> "int | None":
    """The index of a slot PAST the held prefix that some other process holds, or None if quiet.

    Probes `_QUIET_LANE_PROBE_SLOTS` slots beyond the prefix the lane took, NON-BLOCKING: a slot that
    can be locked is free (the lock is dropped immediately — probing must never become holding), and
    one that cannot is held by a peer land. Any error probing a slot reads as QUIET rather than as an
    intruder, because the failure direction that matters is the other one: a false intruder only costs
    a skipped reading, while treating a real one as quiet would publish a number taken under a
    concurrent verify."""
    import fcntl
    for i in range(held_count, held_count + _QUIET_LANE_PROBE_SLOTS):
        path = pool_dir / f"slot-{i}"
        if not path.exists():
            continue          # never created ⇒ never held
        try:
            fd = os.open(str(path), os.O_RDONLY)
        except OSError:
            continue
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            return i
        finally:
            os.close(fd)
    return None


def _hold_quiet_lane_slots(pool_dir: Path, *, _verify_pool_width=None):
    """Acquire THE verify-admission pool, ALL-OR-NOTHING, returning the held fds or None.

    ALL-OR-NOTHING because a partial hold is worse than no hold: a land that fails on the slots we
    took and succeeds on one we did not is a verify running beside the lane, which is the condition
    the lane exists to exclude. So a single unavailable slot releases everything already taken and
    returns None — the caller then records `skipped` for every registered instrument, with the reason.

    HOW WIDE — the injected host-derived width, else the fallback (SPEC-0105 §2c). `_verify_pool_width`
    is a zero-arg callable the HOST injects (`cli.cmd_nightly` → `cmd_nightly` → here) returning the
    SAME SPEC-0132 pool width a land derives, off the same `_verify_worker_bound` measurement. When it
    is present the lane holds EXACTLY that many slots — which is what makes the spec's claim true
    rather than approximately true. When it is ABSENT (a direct/test caller with no host to ask) or
    unmeasurable, the width falls back to `max(existing slot files, _QUIET_LANE_MIN_SLOTS)`: existing
    files are slots some land has actually used here, and the floor covers a pool that has not grown
    to its full width yet. Either way `_quiet_lane_intruder` still probes PAST the hold as a belt —
    the width is measured once, and the headroom that produced it keeps moving.

    A width that raises, or is not a positive int, degrades to the fallback rather than to a refusal:
    the failure direction that matters is publishing a number taken beside a verify, and the fallback
    holds MORE slots than a measured width normally would, not fewer.

    Slot files are created if absent, matching how the pool itself materializes them. Uses the SAME
    flock primitive the pool's owner uses, on the SAME files — this adds no second lock mechanism, no
    scheduler and no stored state (CHARTER §P1 F1)."""
    import fcntl
    try:
        pool_dir.mkdir(parents=True, exist_ok=True)
        existing = len([p for p in pool_dir.glob("slot-*") if p.is_file()])
    except OSError:
        return None
    width = None
    if _verify_pool_width is not None:
        try:
            measured = _verify_pool_width()
        except Exception:                                         # noqa: BLE001 — fail to the fallback
            measured = None
        if isinstance(measured, int) and not isinstance(measured, bool) and measured > 0:
            width = measured
    if width is None:
        width = max(existing, _QUIET_LANE_MIN_SLOTS)
    held: list = []
    for i in range(width):
        try:
            fd = os.open(str(pool_dir / f"slot-{i}"), os.O_RDONLY | os.O_CREAT, 0o666)
        except OSError:
            break
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            held.append(fd)
        except OSError:
            os.close(fd)
            break             # a peer land holds this slot — the host is NOT quiet
    if len(held) < width:
        for fd in held:
            os.close(fd)      # closing releases the flock
        return None
    return held


def _trimmed_median(values) -> "float | None":
    """The median of a series with one sample dropped from each end at >= 5 samples.

    TRIMMED for the same reason the sibling instruments trim (`_arm_spread_pct` in the t11451 leg,
    `LRM.trimmed_spread`): one slow night must not move the baseline the next night is judged
    against, and one fast night must not tighten it. The trim tolerates exactly one outlier per side
    and nothing more, so a genuinely drifting series still moves the baseline.

    None for an empty series — a baseline nobody could compute is never reported as a number."""
    xs = sorted(float(v) for v in values)
    if not xs:
        return None
    core = xs[1:-1] if len(xs) >= 5 else xs
    return float(statistics.median(core))


def _prior_readings(events_path, instrument: str, limit: int = _QUIET_LANE_BASELINE_READINGS,
                    *, _now=None) -> list:
    """The last `limit` SUCCESSFUL durations recorded for one instrument, oldest-first.

    Reads back the lane's OWN `timing_instrument_reading` rows — one oracle: the baseline is computed
    from the same rows a reader sees, never from a second store. ONLY `ok` readings with a real
    `duration_ms` are admitted: a `failed` or `skipped` row measured nothing, and letting a null or a
    fabricated 0 into the baseline would drag every later comparison down (the T-0358 discipline).

    READ THROUGH THE SEGMENT-AWARE PRIMITIVES, NEVER AS ONE FILE (SPEC-0190 rule 4). The journal is ONE
    logical history across bounded physical segments, so a raw read of the journal PATH sees the LIVE
    segment alone. Here that would not merely lose old rows — it would silently SHORTEN the baseline
    as the journal rotates, so the seven-reading comparison would quietly become a two-reading one and
    the row would still say `readings_considered: 7`. It is also the reader the T-12034 `reads`
    counters instrument, so this fold is counted like every other.

    IT DECLARES A HORIZON (T-12213, SPEC-0190 rule 4). Rule 4 asks every reader to declare how much
    history it needs and calls a reader that folds the whole archive to answer a recent question a
    defect. This one folded all 98 segments — 644k rows, ~8s — on every instrument of every nightly
    run, to find at most seven rows (measured on this engine 2026-09-07; the nightly's own profile
    attributed 19.1s of a 21.8s run to the two calls this function serves). It now opens `_QUIET_LANE_BASELINE_HORIZON_DAYS` of segments
    first, through the same `segment_rows_since` / `segment_paths_since` resolver rule 4 names, so
    there is still exactly ONE membership rule and ONE parse path (a second one spelled at a reader is
    the class rule 3 warns about).

    THE WIDEN BRANCH IS REQUIRED FOR CORRECTNESS — IT IS NOT DEFENSIVE PADDING. Unlike `debt`'s routed
    readers, this reader's window is a COUNT (the last `limit` readings), not a date range, so it has
    NO in-loop `ts` predicate left to decide membership after the file-name pre-filter. A bare date
    horizon would therefore CHANGE THE ANSWER whenever the lane recorded fewer than `limit` readings
    inside it — i.e. it would change the lane's baseline semantics, which T-12038 owns and T-12213 is
    scoped out of. So when the horizon does not yield `limit` readings, the whole journal is folded and
    the pre-change answer is returned exactly.

    WHY THE NARROW READ IS EXACT WHEN IT IS TAKEN, by construction rather than by care.
    `segment_paths_since` drops exactly a PREFIX of the ordered segment set — archive labels sort
    chronologically and the live segment is always returned last — so the narrow fold's rows are a
    SUFFIX of the full fold's rows, in the same order. If that suffix already yields `limit` or more
    admitted readings, then `out[-limit:]` over it IS `out[-limit:]` over the full fold: the rows the
    full fold would add are all OLDER and all fall outside the last `limit`. Where the suffix yields
    fewer, we widen and are identical trivially. Either way the returned list is the one the
    whole-journal reader returned.

    Fail-OPEN to []: an unreadable or absent journal means NO BASELINE, which the caller reports as
    such. A report-only surface must never die of a missing input."""
    from lib import journal as _journal   # noqa: PLC0415 — lazy leaf, the `views`/`debt`/`cross` idiom

    def _admit(rows) -> list:
        """The admission predicate, UNCHANGED — factored out only so both folds share one copy."""
        out: list = []
        for row in rows:
            if not isinstance(row, dict) or row.get("type") != TIMING_INSTRUMENT_EVENT:
                continue
            data = row.get("data") if isinstance(row.get("data"), dict) else {}
            if data.get("instrument") != instrument or data.get("verdict") != "ok":
                continue
            ms = data.get("duration_ms")
            if isinstance(ms, (int, float)) and ms > 0:
                out.append(float(ms))
        return out

    try:
        now = _now if _now is not None else _dt.datetime.now(_dt.timezone.utc)
        since = (now - _dt.timedelta(days=_QUIET_LANE_BASELINE_HORIZON_DAYS)).strftime("%Y-%m-%d")
        # ONE request-scoped read scope over BOTH folds (SPEC-0190 rule 10). Without it the widen
        # branch RE-PARSES the horizon segments the narrow fold just parsed, so the case that widens
        # would cost MORE than the whole-journal read it replaced — measured 18.4s against the old
        # reader's ~8.1s in the same process, a regression paid TODAY for a saving that arrives only
        # once the baseline fills. With the scope, the widening case is back at parity (~8.4s) and the
        # horizon case is the win. Declaring the LIVE path admits every segment of the same logical journal
        # (`JournalRowsMemo.holds` resolves segment -> logical), so the widen re-uses the horizon's
        # parses and pays only for the older segments it adds.
        with _journal.rows_memo([events_path]):
            out = _admit(_journal.segment_rows_since(events_path, since))
            if len(out) < limit:
                # The horizon did not hold a full baseline — widen to the whole journal and return
                # the pre-change answer. See the docstring: this is the branch that keeps the
                # baseline's SEMANTICS untouched, not a fallback for an error.
                out = _admit(_journal.segment_rows(events_path))
    except Exception:                      # noqa: BLE001 — see docstring (fail-open, report-only)
        return []
    return out[-limit:]


def _regression_reading(priors: list, duration_ms: float) -> dict:
    """The report-only regression signal for one reading against its own prior series.

    NO BASELINE IS ITS OWN ANSWER, and it is never a regression. With fewer than two priors there is
    nothing to compare against, so `baseline_median_ms` and `delta_pct` are null and `regression` is
    false — declaring a regression against a number nobody measured would be the fabricated-reading
    fault the whole lane exists to avoid, and `readings_considered` says how few were found so a
    reader can tell a young instrument from a stable one.

    Marks, never gates: nothing downstream of this moves a verdict or an exit code (SPEC-0105 §2c)."""
    if len(priors) < 2:
        return {"baseline_median_ms": None, "delta_pct": None, "regression": False,
                "readings_considered": len(priors)}
    baseline = _trimmed_median(priors)
    if not baseline or baseline <= 0:
        return {"baseline_median_ms": None, "delta_pct": None, "regression": False,
                "readings_considered": len(priors)}
    delta = (duration_ms - baseline) / baseline * 100.0
    return {"baseline_median_ms": round(baseline, 1), "delta_pct": round(delta, 2),
            "regression": delta > _QUIET_LANE_REGRESSION_PCT,
            "readings_considered": len(priors)}


def _consumer_timing_instruments(proj_path: Path, name: str, *, _expand=None) -> list:
    """T-12097 (SPEC-0160 rule 10 → SPEC-0105 §2c) — the quiet-lane registry a REGISTERED CONSUMER
    DECLARES: one leg-less instrument row per file its `tests.classes[].timing_lane` globs actually
    match on disk. `[]` when the project declares none, which is what makes the lane a no-op there.

    THE PREMISE MOVED, IT WAS NOT OVERRIDDEN. `_TIMING_INSTRUMENTS`' rationale — "membership is
    deliberately a KERNEL constant and not a per-project declaration ... there is nothing here for a
    consumer to adopt" — was written by T-12038 when NO per-project declaration existed, and it
    remains true OF ITS SUBJECT: the engine's own two instruments live in the engine's `tests/`, stay
    on that constant, and this function never touches them. T-12039 then created the declaration, and
    SPEC-0160 rule 10 routes it here BY NAME ("what a declared timing test should be run BY instead —
    a quiet lane, on a host with no verify beside it — is SPEC-0105 §2c's concern"). Two sources for
    two different subjects: the kernel's membership on the kernel constant, a consumer's on the
    consumer's own declaration. Not a second lane, and not a second registry for the same subject.

    DISCOVERY, NOT MATCHING — and an unmatched glob registers NOTHING. The pinned-refusal sibling
    (`rebaseline_currency._timing_lane_pin_refusals`) is handed the paths and asks which are refused;
    here there is no such set, so the files are FOUND. Each declared glob goes through the ONE
    declared-glob idiom this codebase has — `task._expand_declared_glob` (braces + zero-depth `**/`)
    — and each expansion is then resolved against the repo with `Path.glob`. No second glob engine.
    A glob that matches no file contributes no instrument and therefore no reading: an unsatisfiable
    declaration is a declaration problem, and inventing a row for it would be exactly the fabricated
    reading this whole lane exists to stop producing.

    THE WAIVER IS DELIBERATELY NOT CONSULTED, and the omission is a decision rather than an oversight.
    Per SPEC-0160 rule 10 the entire effect of `timing_lane_waiver` is RE-ADMISSION TO THE PINNED SET
    — it says "pin this anyway, I accept the flake risk". It does not un-declare the file as
    timing-sensitive, so a waived file still wants the quiet-host reading this lane takes; reading the
    waiver here would silently deny a reading to precisely the files a project flagged as risky.

    IDS ARE NAMESPACED `<project>:<repo-relative path>`. The baseline fold (`_prior_readings`) keys on
    the instrument id alone, so two projects declaring the same relative path would otherwise share
    one series and each would be judged against the other's host. Namespacing also keeps the reading
    row's KEY SET exactly the one `timing_instrument_reading` already emits — the project travels
    inside the existing `instrument` field, so this adds no payload key (SPEC-0161).

    FAIL-OPEN throughout, the direction every sibling declaration reader takes: an absent, unreadable
    or malformed carrier, a malformed `timing_lane`, and any error walking the tree all declare
    NOTHING. This feeds a report-only reading that must never abort the nightly run."""
    if _expand is None:
        from lib import task as _task   # lazy — the ONE declared-glob idiom (the `init`/`journal` precedent)
        _expand = _task._expand_declared_glob
    try:
        ops = state.load_ops(Path(proj_path) / CONSUMER_OPS_CONTRACT)
    except Exception:                    # noqa: BLE001 — an unreadable carrier declares nothing
        return []
    if not isinstance(ops, dict):
        return []
    tests = ops.get("tests")
    classes = tests.get("classes") if isinstance(tests, dict) else None
    if not isinstance(classes, list):
        return []
    root = Path(proj_path)
    rels: set = set()
    for c in classes:
        if not isinstance(c, dict):
            continue
        lane = c.get("timing_lane")
        if not (isinstance(lane, list) and len(lane) > 0):
            continue                     # absent OR malformed → declares nothing (fail-OPEN)
        for raw in lane:
            if not (isinstance(raw, str) and raw.strip()):
                continue
            for glob in _expand(raw.strip()):
                glob = glob.strip().lstrip("./")
                if not glob or glob.startswith("/") or ".." in Path(glob).parts:
                    continue             # absolute / upward — the SPEC-0160 rule-10 shape refuses it
                try:
                    found = list(root.glob(glob))
                except Exception:        # noqa: BLE001 — an unwalkable pattern discovers nothing
                    continue
                for hit in found:
                    try:
                        if hit.is_file():
                            rels.add(hit.relative_to(root).as_posix())
                    except (OSError, ValueError):
                        continue
    return [{"id": f"{name}:{rel}", "path": rel} for rel in sorted(rels)]


def _acquire_pool_within_window(pool_dir: Path, *, window: int, interval: int,
                                _verify_pool_width, _sleep, _clock) -> tuple:
    """Take the verify-admission pool, RETRYING within a bounded window. Returns `(held, waited_s)`.

    THE WHOLE RETRY IS THIS FUNCTION RE-CALLING THE EXISTING `_hold_quiet_lane_slots` (CHARTER §P1
    F1 — the existing analog extended, not paralleled). There is no second lock, no new probe, no
    scheduler and no stored state: the hold is already all-or-nothing and already releases every slot
    it took before returning `None`, so re-calling it is safe by construction and each attempt is
    independent of the last.

    THE FIRST ATTEMPT IS ALWAYS MADE, BEFORE ANY CLOCK READ — so a free pool costs zero wait and zero
    sleeps, and the retry adds nothing at all to the normal path. Only a REFUSED first attempt starts
    the window.

    BOUNDED BY THE CLOCK, NOT BY AN ATTEMPT COUNT. The deadline is taken once from the injected
    `_clock` and every later attempt is admitted only while it holds, so a hold that itself runs slow
    (a wide pool on a loaded host) shortens the number of attempts rather than overrunning the window
    — an attempt budget would have let a slow sweep run past the night it was bounded to.

    `_sleep` / `_clock` ARE INJECTED for the same reason `_run` and `_append_event` are: the bound is
    45 minutes, and a test that had to spend it could not assert it. In production they default to
    `time.sleep` / `time.monotonic` at the call site.

    A NON-POSITIVE `window` DISABLES THE RETRY — exactly one attempt, the pre-T-12154 behaviour. That
    is not a convenience switch: it is what the AC1 differential arms, so the test can show that the
    reading it gets WITH the window is one it does not get without it.

    `waited_s` is the real elapsed wait, rounded — 0.0 when the pool was free at once. It is recorded
    on the rows the caller emits, because a reading that waited 20 minutes for a quiet host and one
    that found it quiet immediately were taken under different conditions and should not read alike."""
    held = _hold_quiet_lane_slots(pool_dir, _verify_pool_width=_verify_pool_width)
    if held is not None or window <= 0:
        return held, 0.0
    started = _clock()
    deadline = started + window
    step = interval if interval > 0 else 1
    while True:
        now = _clock()
        if now >= deadline:
            return None, round(now - started, 1)
        _sleep(min(step, deadline - now))
        # THE CLOCK IS RE-READ AFTER THE SLEEP, BEFORE THE ATTEMPT, and that second read is the
        # whole reason the window is a bound rather than a bound-plus-one-attempt. The last sleep of
        # a window that is about to close lands exactly ON the deadline; attempting the hold there
        # would take a reading OUTSIDE the window the lane declared it would wait, so a pool freed at
        # the very moment of expiry would be measured instead of skipped. Checking here makes every
        # attempt provably STRICTLY INSIDE the window (audit-post finding, 2026-09-05; the boundary
        # differential is `test_ac2_differential_a_pool_freed_exactly_at_expiry_is_not_measured`).
        now = _clock()
        if now >= deadline:
            return None, round(now - started, 1)
        held = _hold_quiet_lane_slots(pool_dir, _verify_pool_width=_verify_pool_width)
        if held is not None:
            return held, round(_clock() - started, 1)


def _run_quiet_lane(engine_root: Path, *, dry_run: bool, _run, _append_event, events_path,
                    instruments=None, timeout: int = _QUIET_LANE_TIMEOUT,
                    _verify_pool_width=None,
                    retry_window: "int | None" = None,
                    retry_interval: "int | None" = None,
                    _sleep=None, _clock=None) -> dict:
    """The SPEC-0105 §2c quiet lane: run every registered timing instrument SERIALIZED, on a host with
    no land verify beside it, and record ONE reading row per instrument.

    SERIALIZED IS THE PLAIN `for` LOOP BELOW, and it is load-bearing rather than incidental: two
    timing instruments run concurrently measure each other, which is the same defect as running one
    inside a parallel verify, one altitude down. There is no pool, no worker count and no scheduler
    here on purpose.

    ONE ROW PER INSTRUMENT, WHATEVER HAPPENED. A non-zero exit records `failed` carrying its exit
    code; a timeout records `failed` naming the timeout; an unresolvable file records `failed` naming
    that; and a lane that could not take the host quietly records `skipped` — with its reason — for
    EVERY registered instrument. An instrument that produced no row at all would be indistinguishable
    from one nobody registered, which is the failure this rule is written against.

    A SKIPPED READING CARRIES `duration_ms: null`, NEVER 0. A zero would be admitted by the baseline
    fold as a real, very fast reading and would pull every later comparison down — the fabricated-zero
    fault (T-0358). `_prior_readings` also refuses anything but an `ok` row, so the two halves fail
    closed together rather than relying on either alone.

    IT WAITS FOR A QUIET HOST RATHER THAN GUESSING WHEN ONE EXISTS (T-12154). A busy pool at the
    nightly's minute is not evidence that the host is busy all night — it is evidence about that
    minute. So the pool is taken through `_acquire_pool_within_window`, which re-tries the SAME hold
    every `retry_interval` seconds for up to `retry_window`, and only a window that CLOSES without a
    free pool produces the `skipped` rows. That matters because the readings have to ACCRUE: the
    de-pin phase needs >= 7 consecutive readings per instrument, and against a land queue that runs
    around the clock a single fixed attempt per night can miss indefinitely — as it did on the lane's
    first two rows, which were BOTH skipped for exactly this reason.

    WAITING IS NOT MEASURING. Nothing runs while the pool is busy, so the never-measure-under-load
    rule (SPEC-0105 §2c) is untouched: the skip is still the outcome when the window closes, with the
    same verdict, the same reason and `duration_ms: null`. What changed is WHEN the attempt happens.

    EVERY EMITTED ROW CARRIES `pool_wait_s` — the ok ones as well as the skipped ones. A reading taken
    after a 20-minute wait and one taken on an immediately free host were taken under different
    conditions, and the row is the only place a later reader can tell them apart.

    Returns `{verdict, readings, held_slots, reason}`; emits nothing under `--dry-run` (the read-only
    parity backup-verify and the transcript mirror hold). Fail-OPEN throughout: any fault degrades to
    a reported `skipped`/`failed` reading and never aborts the nightly run."""
    # LATE-BOUND, not a default expression: a Python default is evaluated once at def time, so a
    # module-constant default could not be pinned by a caller that patches the constant — and the
    # bound has to be pinnable, because a test that holds the pool deliberately must not spend the
    # real 45 minutes. Resolving here keeps the constant the ONE place the number is declared.
    retry_window = _QUIET_LANE_RETRY_WINDOW if retry_window is None else retry_window
    retry_interval = _quiet_lane_retry_interval() if retry_interval is None else retry_interval
    registry = list(instruments if instruments is not None else _TIMING_INSTRUMENTS)
    if dry_run:
        return {"verdict": "skip", "readings": [], "held_slots": 0,
                "reason": "--dry-run: read-only, the lane runs no instrument and emits no reading"}
    if not registry:
        return {"verdict": "skip", "readings": [], "held_slots": 0,
                "reason": "no timing instruments registered"}

    pool = _quiet_lane_pool_dir(Path(engine_root))
    held, waited_s = _acquire_pool_within_window(
        pool, window=retry_window, interval=retry_interval,
        _verify_pool_width=_verify_pool_width,
        _sleep=_sleep if _sleep is not None else _time.sleep,
        _clock=_clock if _clock is not None else _time.monotonic)
    if held is None:
        reason = ("the verify-admission pool is not free — a land verify is running, so a wall-clock "
                  "reading taken now would measure the host (SPEC-0105 §2c)")
        # The reason text is UNCHANGED from the pre-retry lane, deliberately (T-12154 AC2): the
        # CONDITION it reports — the pool was not free, so nothing was measured — is exactly what it
        # was, and a reader matching on this reason must keep matching. How long the lane tried
        # before giving up is a different fact and lives in its own field, `pool_wait_s` below.
        readings = [{"instrument": inst["id"], "verdict": "skipped", "duration_ms": None,
                     "exit_code": None, "serialized": True, "baseline_median_ms": None,
                     "delta_pct": None, "regression": False, "readings_considered": 0,
                     "pool_wait_s": waited_s, "reason": reason} for inst in registry]
        for row in readings:
            _append_event(TIMING_INSTRUMENT_EVENT, None, dict(row))
        return {"verdict": "skip", "readings": readings, "held_slots": 0,
                "pool_wait_s": waited_s, "reason": reason}

    readings: list = []
    try:
        for inst in registry:
            reading = _run_one_instrument(engine_root, inst, pool=pool, held_count=len(held),
                                          _run=_run, events_path=events_path, timeout=timeout)
            reading["pool_wait_s"] = waited_s
            readings.append(reading)
            _append_event(TIMING_INSTRUMENT_EVENT, None, dict(reading))
    finally:
        for fd in held:
            try:
                os.close(fd)          # releases the flock — a land may verify again
            except OSError:
                pass
    failed = sum(1 for r in readings if r["verdict"] == "failed")
    regressed = sum(1 for r in readings if r.get("regression"))
    return {"verdict": "alert" if failed else "ok", "readings": readings,
            "held_slots": len(held), "failed": failed, "regressed": regressed,
            "pool_wait_s": waited_s,
            "reason": (f"{failed} instrument(s) recorded a failed reading" if failed else None)}


def _run_one_instrument(engine_root: Path, inst: dict, *, pool: Path, held_count: int,
                        _run, events_path, timeout: int) -> dict:
    """Run ONE registered instrument and return its reading row (never raises).

    The quietness precondition is checked on BOTH sides of the run, not once before it: a land that
    derived a wider pool than the lane holds packs onto the first slot past the held prefix, and it
    can do that at any point while the instrument is running. A reading with a verify beside it on
    either side is recorded `skipped` with that reason rather than published as a number — the whole
    point being that a reading is interpretable only against the conditions it was taken under, which
    is also why the row records `serialized`.

    `leg` IS OPTIONAL (T-12097). A KERNEL instrument always names one, and that is what makes the
    kernel constant checkable — a registry that said only "run this file" could not be told apart
    from a stale one after the leg was renamed (`_TIMING_INSTRUMENTS`, unchanged). A CONSUMER's entry
    comes from `tests.classes[].timing_lane`, which is a glob list of FILES and names no leg to pass,
    so a leg-less entry is run as a plain script. The two are not in tension: the leg-naming
    discipline binds the constant, which is where a rename could silently empty the lane; a declared
    file that is renamed simply stops matching its own project's glob.

    A MISSING FILE HERE IS A REAL DISAPPEARANCE, never an unsatisfiable declaration. The consumer
    registry is built by DISCOVERY (`_consumer_timing_instruments`), so a declared glob matching
    nothing registers nothing and this function never sees it — no fabricated row. Reaching the
    branch below therefore means a file that WAS on disk at discovery is gone by the time it ran,
    which is recorded as a `failed` reading naming the path rather than as silence."""
    path = Path(engine_root) / inst["path"]
    if not path.is_file():
        return {"instrument": inst["id"], "verdict": "failed", "duration_ms": None,
                "exit_code": None, "serialized": True, "baseline_median_ms": None,
                "delta_pct": None, "regression": False, "readings_considered": 0,
                "reason": f"registered file not found: {inst['path']}"}
    intruder = _quiet_lane_intruder(pool, held_count)
    if intruder is not None:
        return {"instrument": inst["id"], "verdict": "skipped", "duration_ms": None,
                "exit_code": None, "serialized": True, "baseline_median_ms": None,
                "delta_pct": None, "regression": False, "readings_considered": 0,
                "reason": f"a verify holds admission slot-{intruder}, past the {held_count} this "
                          f"lane holds — the host is not quiet"}
    t0 = _time.monotonic()
    try:
        argv = ["python3", str(path)] + ([str(inst["leg"])] if inst.get("leg") else [])
        proc = _run(argv, capture_output=True, text=True,
                    cwd=str(engine_root), timeout=timeout)
        exit_code = int(proc.returncode)
        detail = None
    except subprocess.TimeoutExpired:
        return {"instrument": inst["id"], "verdict": "failed", "duration_ms": None,
                "exit_code": None, "serialized": True, "baseline_median_ms": None,
                "delta_pct": None, "regression": False, "readings_considered": 0,
                "reason": f"killed at the lane's {timeout}s bound — no duration was measured"}
    except Exception as exc:            # noqa: BLE001 — one instrument never kills the nightly run
        return {"instrument": inst["id"], "verdict": "failed", "duration_ms": None,
                "exit_code": None, "serialized": True, "baseline_median_ms": None,
                "delta_pct": None, "regression": False, "readings_considered": 0,
                "reason": f"could not be run: {type(exc).__name__}: {str(exc).strip()[:200]}"}
    duration_ms = round((_time.monotonic() - t0) * 1000.0, 1)
    intruder = _quiet_lane_intruder(pool, held_count)
    if intruder is not None:
        return {"instrument": inst["id"], "verdict": "skipped", "duration_ms": None,
                "exit_code": exit_code, "serialized": True, "baseline_median_ms": None,
                "delta_pct": None, "regression": False, "readings_considered": 0,
                "reason": f"a verify took admission slot-{intruder} DURING this run — the reading "
                          f"was not taken on a quiet host and is not reported as a number"}
    if exit_code != 0:
        tail = (getattr(proc, "stderr", "") or getattr(proc, "stdout", "") or "").strip()[-400:]
        return {"instrument": inst["id"], "verdict": "failed", "duration_ms": duration_ms,
                "exit_code": exit_code, "serialized": True, "baseline_median_ms": None,
                "delta_pct": None, "regression": False, "readings_considered": 0,
                "reason": f"exited {exit_code}: {tail}" if tail else f"exited {exit_code}"}
    row = {"instrument": inst["id"], "verdict": "ok", "duration_ms": duration_ms,
           "exit_code": 0, "serialized": True, "reason": detail}
    row.update(_regression_reading(_prior_readings(events_path, inst["id"]), duration_ms))
    return row


def _print_quiet_lane_readings(lane: dict) -> None:
    """Print ONE line per quiet-lane reading — the single renderer BOTH lanes go through (T-12097).

    Extracted verbatim from `cmd_nightly`'s engine block rather than copied beside it: a second copy
    would let a change to how a reading reads land on one lane and not the other, and the two lanes
    emit the identical row shape precisely because they are the same `_run_quiet_lane`. Every reading
    prints, including a `failed` or `skipped` one — a suppressed reading cannot be told apart from a
    run that never took it.

    THE WAIT PRINTS WHEN THERE WAS ONE (T-12154), and is silent when there was not — a reading taken
    after the lane waited out a land queue was taken under different conditions than one taken on an
    immediately free host, and the reader of the nightly report should not have to open the journal
    to see which they are looking at."""
    for rd in lane.get("readings", []):
        ms = rd.get("duration_ms")
        delta = ("" if rd.get("delta_pct") is None
                 else f" ({rd['delta_pct']:+.2f}% vs trimmed median "
                      f"{rd.get('baseline_median_ms')}ms of {rd.get('readings_considered')} prior)")
        waited = rd.get("pool_wait_s") or 0
        print(f"  · {rd['instrument']}: {rd['verdict']}"
              + (f" {ms}ms" if ms is not None else " (no duration measured)")
              + delta
              + (f" [waited {waited}s for a quiet pool]" if waited else "")
              + ("  ! REGRESSION" if rd.get("regression") else "")
              + (f" — {rd['reason']}" if rd.get("reason") else ""))


def cmd_nightly(args: argparse.Namespace, *, REGISTRY_PATH, ENGINE_ROOT, KERNEL_NAME,
                BACKUP_VERIFY_SH, _append_event, _die, _utc_now_iso, _run=subprocess.run,
                _freshness_adapter=_default_freshness_adapter,
                TRANSCRIPT_ARCHIVE_SRC=None, TRANSCRIPT_ARCHIVE_DIR=None,
                cross_log_path=None, cross_lock_path=None, cross_self_name=None,
                cross_emit=None, _frontend_errors=None, _fe_read_rows=None,
                _verify_pool_width=None) -> None:
    """The bounded v2 methodology-nightly RUNNER (SPEC-0105). Enumerate v2 projects → per-project
    read-only checks (queue + corpus + the SPEC-0110 L3 freshness probe) → shared-store backup-verify
    once → emit ONE nightly_run_completed → report. NEVER spawns a session (the §6 fence). `--dry-run`
    is fully read-only (no backup snapshot, no event emit). `--registry PATH` overrides the registry
    location. `_freshness_adapter` is the injectable, project-supplied read-only freshness adapter
    returning NORMALIZED per-pipeline freshness — the default is the thin file-based adapter; a project
    with a live source (T-9598's trend-finder pull) swaps its own in through this same seam (SPEC-0110
    r2), so the kernel grader embeds no project-specific format. `_verify_pool_width` is the same
    shape of injected host collaborator for the §2c quiet lane: a zero-arg callable returning the
    host-derived SPEC-0132 verify-admission pool width — EXACTLY the width a land derives — so the
    lane holds the real pool instead of a guess. It arrives INJECTED because this module is a
    stdlib+`lib.state` leaf that never back-imports the host where that derivation lives; absent it
    (a direct/test caller) the lane falls back to `_QUIET_LANE_MIN_SLOTS`."""
    registry_path = Path(args.registry).resolve() if getattr(args, "registry", None) \
        else Path(REGISTRY_PATH)
    dry_run = bool(getattr(args, "dry_run", False))
    if not registry_path.exists():
        _die(f"nightly: registry not found at {registry_path} "
             f"(set --registry or $YITC_REGISTRY)")

    now = _dt.datetime.now(_dt.timezone.utc)
    projects = _v2_projects(registry_path, Path(ENGINE_ROOT), KERNEL_NAME)

    # T-10803 (SPEC-0170 / SPEC-0142): the frontend-error CADENCE leg. Injected on the same seam as
    # `_freshness_adapter` so the source READ stays swappable under test — the module itself is a
    # stdlib-only leaf, imported lazily to keep this runner's top-level imports unchanged.
    if _frontend_errors is None:
        from lib import frontend_errors as _frontend_errors  # noqa: PLC0415 — lazy, like `init`/`deploy`
    _fe_reader = _fe_read_rows or _frontend_errors.read_rows

    # T-12097: the TWO paths `_v2_projects` can bind the KERNEL entry to — the repository this engine
    # belongs to (a registry entry naming it, incl. when the CLI runs from a linked WORKTREE of it) and
    # this engine's own install root (the narrowed name-matched rebind for a relocated/test install).
    # Computed ONCE, outside the loop: `_engine_repo_root` shells out to git, and the answer does not
    # vary per project. Both are absolute canonical paths, like the `ppath` they are compared against.
    _engine_own_paths = {_engine_repo_root(Path(ENGINE_ROOT)), Path(ENGINE_ROOT).resolve()}

    results: list = []
    for proj in projects:
        ppath = proj["path"]
        present = ppath.is_dir()
        entry = {"name": proj["name"], "path": str(ppath), "present": present}
        if present:
            entry["queue"] = _check_queue(ppath, now=now)
            entry["corpus"] = _check_corpus_integrity(ppath)
            entry["freshness"] = _check_freshness(ppath, now=now, adapter=_freshness_adapter)
            entry["born_waivers"] = _check_born_waiver_freshness(ppath)
            entry["concern_conformance"] = _check_concern_conformance(ppath, now=now)
            entry["concern_drift"] = _check_concern_drift(ppath)
            entry["unratified_adoptions"] = _check_unratified_adoptions(ppath)
            entry["adapter"] = _check_adapter_conformance(ppath)
            entry["adoption_completeness"] = _check_adoption_completeness(ppath)
            # T-12046 (SPEC-0196 rule 3): the override-ledger drift leg, riding the SAME per-project
            # report-only sweep its neighbour above does. Deliberately NOT folded into `flagged`
            # below — rule 3 makes the check report-only, so it moves no verdict and no exit code.
            entry["override_ledger"] = _check_override_ledger(ppath)
            entry["no_local_diff"] = _check_no_local_diff(ppath)
            entry["carrier_shape"] = _check_carrier_shape(ppath)
            entry["repo_storage"] = _check_repo_storage(ppath)   # T-11063 (SPEC-0105 §1)
            entry["frontend_errors"] = _check_frontend_errors(
                ppath, as_of=now, fe=_frontend_errors, read_rows=_fe_reader)
            # T-11359 (SPEC-0105 §1): the PROJECT-HEALTH axis — does this project's main actually
            # build? Every other check above is a file read; this is the one that can see a red main,
            # and seeing it HERE is what turns one red into one reported line instead of N halted
            # workers. Runs only the layers the project opted in (see `_check_project_health`).
            entry["project_health"] = _check_project_health(ppath, dry_run=dry_run, _run=_run)
            # T-12008 (SPEC-0105 §1): the per-project STAGE-PROFILE reading — what each lifecycle
            # stage cost here over the window. Read-only fold of this project's own journal through
            # the kernel `stage-profile` lens; report-only, and printed only when the project actually
            # closed something (see the report below).
            entry["stage_profile"] = _check_stage_profile(ppath, now=now)
            # T-12037 (SPEC-0105 §1 / SPEC-0119 rule 37): the per-project SEAM-READ reading —
            # which of this project's verbs read more of its corpus than they composed. Read-only
            # fold of this project's own journal through the SAME kernel fold the `debt` echo
            # renders; report-only, and `no counters` is reported as its own answer, never as green.
            entry["seam_reads"] = _check_seam_read_amplification(ppath, now=now)
            # T-12097 (SPEC-0160 rule 10 → SPEC-0105 §2c): the CONSUMER quiet lane — this project's
            # OWN declared timing-sensitive tests, run through the SAME `_run_quiet_lane` the engine
            # lane uses, on THIS repo's own SPEC-0132 admission pool. Not a second lane: one more
            # CALLER, with a registry resolved from the project's declaration instead of the kernel
            # constant. T-12038 homed that constant as "deliberately a KERNEL constant and not a
            # per-project declaration ... nothing here for a consumer to adopt" — true when written
            # and still true of ITS subject (the engine's two instruments stay on it, untouched), but
            # T-12039 then CREATED the declaration and SPEC-0160 rule 10 routes it here by name. The
            # premise moved; this answers it rather than overriding it.
            #
            # DECLARES NONE ⇒ NOTHING HAPPENS, on the existing short-circuit rather than a new branch:
            # `_run_quiet_lane` returns `skip` and emits no row for an empty registry BEFORE it takes
            # any slot, so a non-declaring project costs one carrier read and holds nothing.
            #
            # READINGS GO TO THE ENGINE'S JOURNAL, never the consumer's — the runner's read-only
            # territory rule (D-0019) is unchanged, and it keeps ONE oracle: `_prior_readings` folds
            # the baseline back out of the same journal these rows are written to.
            #
            # RUNNING A CONSUMER'S FILE IS THE CONSUMER'S OWN OPT-IN — it named the file in its
            # carrier. The precedent is `_check_project_health` (T-11359), which already executes a
            # project's declared `verify.layers` commands from this same runner.
            if ppath in _engine_own_paths:
                # The KERNEL's own membership stays on `_TIMING_INSTRUMENTS` and is run ONCE per run
                # below, outside this loop. Skipping here is what keeps that true if the engine ever
                # grows a carrier of its own — otherwise its instruments would be run twice a night,
                # once from each source, and the baseline would fold two different registries.
                entry["quiet_lane"] = {
                    "verdict": "skip", "readings": [], "held_slots": 0,
                    "reason": "the engine's own repository — its instruments are the kernel constant "
                              "`_TIMING_INSTRUMENTS`, run once per run outside the project loop"}
            else:
                entry["quiet_lane"] = _run_quiet_lane(
                    ppath, dry_run=dry_run, _run=_run, _append_event=_append_event,
                    events_path=Path(ENGINE_ROOT) / "events.jsonl",
                    instruments=_consumer_timing_instruments(ppath, proj["name"]),
                    _verify_pool_width=_verify_pool_width)
        else:
            entry["queue"] = {"verdict": "skip", "reason": "project path absent"}
            entry["corpus"] = {"verdict": "skip", "reason": "project path absent"}
            entry["freshness"] = {"verdict": "skip", "adopted": False,
                                  "reason": "project path absent"}
            entry["born_waivers"] = {"verdict": "skip", "reason": "project path absent"}
            entry["concern_conformance"] = {"verdict": "skip", "reason": "project path absent"}
            entry["concern_drift"] = {"verdict": "skip", "drifts": [], "reason": "project path absent"}
            entry["unratified_adoptions"] = {"verdict": "skip", "records": [],
                                             "reason": "project path absent"}
            entry["adapter"] = {"verdict": "skip", "violations": [], "reason": "project path absent"}
            entry["adoption_completeness"] = {"verdict": "skip", "violations": [],
                                              "reason": "project path absent"}
            entry["override_ledger"] = {"verdict": "skip", "findings": [],
                                        "reason": "project path absent"}
            entry["no_local_diff"] = {"verdict": "skip", "violations": [],
                                      "reason": "project path absent"}
            entry["carrier_shape"] = {"verdict": "skip", "carriers": [],
                                      "reason": "project path absent"}
            entry["repo_storage"] = {"verdict": "skip", "findings": [],
                                     "reason": "project path absent"}
            entry["frontend_errors"] = {"verdict": "skip", "adopted": False,
                                        "reason": "project path absent"}
            entry["project_health"] = {"verdict": "skip", "layers": [], "not_run": [],
                                       "reason": "project path absent"}
            entry["stage_profile"] = {"verdict": "skip", "closed_tasks": 0, "stages": {},
                                      "reason": "project path absent"}
            entry["seam_reads"] = {"verdict": "skip", "counters": False, "count": 0,
                                   "measured": 0, "seams": [],
                                   "reason": "project path absent"}
            entry["quiet_lane"] = {"verdict": "skip", "readings": [], "held_slots": 0,
                                   "reason": "project path absent"}
        results.append(entry)

    backup = _check_backup(Path(BACKUP_VERIFY_SH), dry_run=dry_run, _run=_run)
    # T-11015 (SPEC-0177 rule 3): exercise the engine's read-only conformance surfaces — the scheduled
    # run that turns an author-run exit-status differential into adoption. Once per run + engine-scoped,
    # the `_check_backup` shape (see the function for why it is deliberately NOT in the project loop).
    conformance = _check_conformance_surfaces(Path(ENGINE_ROOT), dry_run=dry_run, _run=_run)
    # T-11089 (SPEC-0105 §1): the HOST sandbox axis — orphan verify-sandbox processes + the volume the
    # sandbox dirs hold. Once per run and OUTSIDE the project loop, the `_check_backup` /
    # `_check_conformance_surfaces` shape: the subject is the shared HOST, not any one project, so
    # running it per project would report the same number N times. Read-only; never reaps (see the
    # function). Not `--dry-run`-gated: it mutates nothing, so a dry run has nothing to withhold.
    host_sandbox = _check_host_sandbox(now=now, engine_root=Path(ENGINE_ROOT))
    # T-11631 (SPEC-0002 rotation policy / T-11401): the THIRD rotation reading — filesystem headroom
    # for the volume the repo lives on. Once per run and OUTSIDE the project loop, the host-axis shape
    # above: the subject is the shared VOLUME, not any one project. Read-only (one statvfs) and not
    # `--dry-run`-gated — it mutates nothing, so a dry run has nothing to withhold.
    filesystem_headroom = _check_filesystem_headroom(Path(ENGINE_ROOT))
    # T-12198 (SPEC-0203 rule 6): the FORGOTTEN-BOX belt — is a rented compute box still up with
    # nothing left for it to do? Once per run and OUTSIDE the project loop, the `_check_host_sandbox`
    # shape: the subject is the shared MACHINE, not any one project. It consumes `results` because
    # the machine-idle read is the per-project card counts this run already took. Read-only and not
    # `--dry-run`-gated — it mutates nothing (it never deletes a box), so a dry run has nothing to
    # withhold.
    forgotten_box = _check_forgotten_box(results, now=now, _run=_run)
    # T-12038 (SPEC-0105 §2c / SPEC-0077 §3b): the QUIET LANE — the registered wall-clock timing
    # instruments, run SERIALIZED with the verify-admission pool held so no land verify runs beside
    # them. Once per run and OUTSIDE the project loop, the `_check_backup` / `_check_host_sandbox`
    # shape: the subject is the shared HOST, not any one project. Report-only — a reading, never a
    # gate — and skipped under --dry-run (the read-only parity backup and the archive hold).
    quiet_lane = _run_quiet_lane(Path(ENGINE_ROOT), dry_run=dry_run, _run=_run,
                                 _append_event=_append_event,
                                 events_path=Path(ENGINE_ROOT) / "events.jsonl",
                                 _verify_pool_width=_verify_pool_width)
    # T-10122 (SPEC-0105 §2a): the once-per-run transcript-archive mirror — a bounded local-evidence
    # side-effect peer of backup-verify. Skipped when the injected paths are absent (defensive).
    if TRANSCRIPT_ARCHIVE_SRC is not None and TRANSCRIPT_ARCHIVE_DIR is not None:
        transcripts = _archive_transcripts(Path(TRANSCRIPT_ARCHIVE_SRC), Path(TRANSCRIPT_ARCHIVE_DIR),
                                           dry_run=dry_run, _run=_run)
    else:
        transcripts = {"verdict": "skip", "reason": "archive paths not injected"}

    # Bounded summary: how many projects checked, how many checks raised a non-ok signal.
    # T-10798: counted through the SHARED `_freshness_flags` predicate, so this total stays "every
    # NON-CLEAN freshness grade" as the verdict vocabulary grows — a reader asking «is any project's
    # freshness in trouble?» must not lose the answer the moment a sharper verdict is added.
    freshness_alerts = sum(1 for r in results if _freshness_flags(r["freshness"]))
    # T-10798 (SPEC-0174 rule 3): the FAILING subset broken out beside the total, so the summary tells a
    # confirmed-down subject apart from a no-data stale/miss at a glance. Only the freshness check feeds
    # this counter, which is what makes it an ATTRIBUTABLE probe of the wiring above
    # (`lessons/a-differential-over-a-shared-counter-must-be-attributable`).
    freshness_failing = sum(1 for r in results if r["freshness"].get("verdict") == "failing")
    # NON-ADOPTED honesty signal (SPEC-0110 r2): a present project whose freshness verdict is `none`
    # declared no usable adapter — `none` is NOT coverage; a migration gate must not read it as covered.
    freshness_non_adopted = sum(1 for r in results
                                if r["present"] and r["freshness"].get("verdict") == "none")
    # T-9642 (X-0130): born-waiver-freshness — a present project still carrying an unreplaced init
    # placeholder waiver is an operational-hygiene signal (a fail-closed default never confirmed). The
    # metric counts the actual number of stale waiver PATHS across all projects (not projects-with-an-
    # alert): a single project with several unreplaced born waivers contributes each one (audit-post
    # finding-0). Projects-flagged is the separate `flagged` counter below.
    stale_born_waivers = sum(len(r["born_waivers"].get("stale_waivers") or []) for r in results)
    # T-12037 (SPEC-0105 §1 / SPEC-0119 rule 37): seam-read amplification — the number of amplified
    # SEAM items across all projects (each project's amplified (project, verb) seams), the
    # item-count convention its siblings hold. Reported BESIDE the projects that could not be
    # measured at all: a run where half the fleet emitted no counters and the rest were clean must
    # never render as a clean fleet, which is the same absence-is-not-health rule the check itself
    # applies per project. Deliberately NOT folded into `projects_flagged` — an amplified seam is a
    # read-cost reading, not a project in trouble, and folding it would make the flag mean two things.
    seam_read_amplified = sum(len(r.get("seam_reads", {}).get("seams") or []) for r in results)
    seam_read_uninstrumented = sum(1 for r in results
                                   if r["present"] and not r.get("seam_reads", {}).get("counters"))
    # T-10030 (SPEC-0119 rule 8 / SPEC-0128): concern-conformance — count the actual number of issue
    # ITEMS across all projects (each unanswered/contradictory stance + each expired waiver), mirroring
    # the stale-born-waivers item-count convention.
    concern_conformance_issues = sum(
        len(r["concern_conformance"].get("stance_issues") or [])
        + len(r["concern_conformance"].get("expired_waivers") or []) for r in results)
    # T-10172 (SPEC-0143 Rule 3): concern-drift — count the actual number of drifting concern ITEMS
    # across all projects (each concern behind / un-adopted vs the kernel registry version), mirroring
    # the concern-conformance item-count convention.
    concern_drift_items = sum(len(r.get("concern_drift", {}).get("drifts") or []) for r in results)
    # T-10516 (SPEC-0119 rule 13): unratified adoptions — count the actual number of unratified CONCERN
    # ITEMS across all projects (each `adopt` record still stamped `owner: init` over a DECLARED section),
    # mirroring the concern-conformance item-count convention. The unit is the concern, not the carrier
    # (`lessons/scope-the-trigger-not-the-view`), so a project with several unratified records contributes
    # each one. An UNREADABLE carrier carries `records: []` and so contributes 0 items while still grading
    # `alert` — `flagged` below is what picks that project up (the unreadable-carrier siblings' shape).
    unratified_adoptions = sum(
        len(r.get("unratified_adoptions", {}).get("records") or []) for r in results)
    # T-10480 (SPEC-0125 VP1/VP2): vendor-adapter conformance — count the actual number of violation
    # ITEMS across all projects (each fat-adapter / unresolvable home pointer / unfilled home), mirroring
    # the concern-conformance item-count convention. An UNREADABLE adapter carries `violations: []` and so
    # contributes 0 items while still grading `alert` — `flagged` below is what picks that project up
    # (the same total-safe shape the unreadable-carrier siblings hold).
    adapter_violations = sum(len(r.get("adapter", {}).get("violations") or []) for r in results)
    # T-10694 (SPEC-0122 R6 / X-0543): adoption-completeness — count the actual number of adoption gap
    # ITEMS across all projects (each surface-not-integrated / undeclared-dependency / unanswered /
    # manifest-unresolved), mirroring the concern-conformance item-count convention. An UNREADABLE ops
    # carrier carries `violations: []` and so contributes 0 items while still grading `alert` — `flagged`
    # below is what picks that project up (the same total-safe shape the unreadable-carrier siblings hold).
    adoption_gaps = sum(
        len(r.get("adoption_completeness", {}).get("violations") or []) for r in results)
    # T-10877 (SPEC-0122 R2 / SPEC-0172 rule 3): pin-identity — count the actual number of no-local-diff
    # violation ITEMS across all projects (each surviving/modified local copy, unresolvable pin, or
    # undeclared neutral surface), mirroring the concern-conformance item-count convention. An UNREADABLE
    # ops carrier carries `violations: []` and so contributes 0 items while still grading `alert` —
    # `flagged` below is what picks that project up (the same total-safe shape the siblings hold).
    pin_identity_violations = sum(
        len(r.get("no_local_diff", {}).get("violations") or []) for r in results)
    # T-10664 (SPEC-0105 / fu_4e3c8da2dac9): carrier-drift — count the actual number of drifted live
    # Class-C1 carrier ITEMS across all projects (each declared carrier that no longer classifies +
    # preconditions to a runnable _BackupPlan), mirroring the concern-conformance item-count convention.
    # An UNREADABLE ops carrier carries `carriers: []` and so contributes 0 items while still grading
    # `alert` — `flagged` below is what picks that project up (the unreadable-carrier siblings' shape).
    carrier_shape_drifts = sum(
        len(r.get("carrier_shape", {}).get("carriers") or []) for r in results
        if r.get("carrier_shape", {}).get("verdict") == "alert")
    # T-11063 (SPEC-0105 §1): repo housekeeping — count the ALERTING PROJECTS, not items, because the
    # check emits at most one finding per project (a repo either has an unresolved `gc.log` or it does
    # not), so the two counts would only ever differ on the unreadable arm. Deliberately counted on the
    # VERDICT and not on `findings`: an UNREADABLE `.git` pointer carries `findings: []` but is a real
    # unanswered question about that repo, so it belongs IN this total rather than surfacing only via
    # `flagged` — the opposite call from the item-counting siblings, whose totals stay total-safe by
    # excluding it. Both arms also reach `flagged` below.
    repo_storage_alerts = sum(
        1 for r in results if r.get("repo_storage", {}).get("verdict") == "alert")
    # T-10292: a PRESENT-but-UNREADABLE yitc-ops.yaml silences both concern checks at once, so count the
    # broken CARRIERS (projects), not items — the two checks report the same single fault. Each already
    # grades `alert`, so `flagged` picks the project up; this names the CAUSE in the summary.
    unreadable_ops_carriers = sum(
        1 for r in results
        if r["concern_conformance"].get("unreadable") or r.get("concern_drift", {}).get("unreadable")
        or r.get("project_health", {}).get("unreadable"))   # T-11359 — same carrier, same never-silent rule
    # T-10803 (SPEC-0170 / SPEC-0142): the frontend-error cadence's own totals. `sources_adopted` is
    # the SUBJECT COUNT — how many declared, qualifying sources this run actually folded — and it is
    # what makes a zero run STATED rather than silent (AC3): a sweep that reports nothing because it
    # had nothing to read must be distinguishable from a sweep that never ran, which is the whole
    # failure class this cadence exists inside. `clusters` counts confirmed clusters across them,
    # report-only — it never contributes to `flagged`.
    frontend_error_sources_adopted = sum(
        1 for r in results if r.get("frontend_errors", {}).get("folded"))
    frontend_error_clusters = sum(
        r.get("frontend_errors", {}).get("confirmed") or 0 for r in results)
    # T-11359 (SPEC-0105 §1): the health axis's own two totals. `project_health_failures` is the
    # headline the card exists for — how many projects' mains are RED right now, one number instead of
    # a queue-wide freeze discovered a worker at a time. `project_health_non_adopted` is its honesty
    # companion, on the SPEC-0110 r2 `freshness_non_adopted` precedent: a project that opted no layer
    # in grades `none`, and `none` is NOT coverage — without this counter a fleet with zero adopters
    # would report zero failures and read as a clean bill of health.
    project_health_failures = sum(
        1 for r in results if r.get("project_health", {}).get("verdict") == "fail")
    project_health_non_adopted = sum(
        1 for r in results if r["present"] and r.get("project_health", {}).get("verdict") == "none")
    flagged = sum(1 for r in results
                  if r["queue"].get("verdict") in ("warn",)
                  or r["corpus"].get("verdict") in ("stale", "missing", "error")
                  or _freshness_flags(r["freshness"])   # T-10798 — alert OR failing, via the one predicate
                  or r["born_waivers"].get("verdict") == "alert"
                  or r["concern_conformance"].get("verdict") == "alert"
                  or r.get("concern_drift", {}).get("verdict") == "alert"
                  or r.get("unratified_adoptions", {}).get("verdict") == "alert"
                  or r.get("adapter", {}).get("verdict") == "alert"
                  or r.get("adoption_completeness", {}).get("verdict") == "alert"
                  or r.get("no_local_diff", {}).get("verdict") == "alert"   # T-10877 (SPEC-0122 R2)
                  or r.get("carrier_shape", {}).get("verdict") == "alert"
                  or r.get("repo_storage", {}).get("verdict") == "alert"   # T-11063 (SPEC-0105 §1)
                  # T-10803: only a BROKEN conveyor flags (unreadable carrier / non-qualifying or
                  # dead source / a cadence-vs-view disagreement). Confirmed clusters never do —
                  # report-only means the report, not the project, carries them.
                  or r.get("frontend_errors", {}).get("verdict") == "alert"
                  # T-11359: a RED main flags its project — that is the whole surfacing this check
                  # exists for. `alert` (a BROKEN watch) flags too: not knowing whether main is green
                  # is itself a finding, and the two are kept as separate verdicts precisely so this
                  # fold cannot make them read alike. `none` does NOT flag — a project that opted no
                  # layer in is not in trouble, it is un-adopted, and the counter above says so.
                  or r.get("project_health", {}).get("verdict") in ("fail", "alert"))
    data = {
        "registry": str(registry_path),
        "projects_checked": len(results),
        "projects_flagged": flagged,
        "freshness_alerts": freshness_alerts,
        "freshness_failing": freshness_failing,        # T-10798 (SPEC-0174 rule 3) — the fresh-and-failing subset
        "freshness_non_adopted": freshness_non_adopted,
        "stale_born_waivers": stale_born_waivers,
        "seam_read_amplified": seam_read_amplified,   # T-12037 (SPEC-0119 rule 37)
        "seam_read_uninstrumented": seam_read_uninstrumented,   # measured NOTHING — never read as clean
        "concern_conformance_issues": concern_conformance_issues,
        "concern_drift_items": concern_drift_items,   # T-10172 (SPEC-0143 Rule 3)
        "unratified_adoptions": unratified_adoptions,   # T-10516 (SPEC-0119 rule 13)
        "adapter_violations": adapter_violations,     # T-10480 (SPEC-0125 VP1/VP2)
        "adoption_gaps": adoption_gaps,               # T-10694 (SPEC-0122 R6 / X-0543)
        "pin_identity_violations": pin_identity_violations,   # T-10877 (SPEC-0122 R2 / SPEC-0172 r3)
        "carrier_shape_drifts": carrier_shape_drifts,   # T-10664 (SPEC-0105 / fu_4e3c8da2dac9)
        "repo_storage_alerts": repo_storage_alerts,     # T-11063 (SPEC-0105 §1) — housekeeping stopped
        "unreadable_ops_carriers": unreadable_ops_carriers,   # T-10292 — a broken carrier is never silent
        "project_health_failures": project_health_failures,   # T-11359 (SPEC-0105 §1) — a RED consumer main
        "project_health_non_adopted": project_health_non_adopted,
        "frontend_error_sources_adopted": frontend_error_sources_adopted,   # T-10803 (SPEC-0170)
        "frontend_error_clusters": frontend_error_clusters,
        # THE CADENCE MARKER (T-10803 / SPEC-0142). Two duties, both load-bearing:
        #   (1) it NAMES the reused carrier and its provider-independent OS trigger on the run record
        #       itself, so the obligation's trigger is auditable from the journal alone (AC1);
        #   (2) it is the key `frontend_errors.cadence_liveness` folds on. A carrier run WITHOUT this
        #       marker did not run this sweep, and must not be counted as the cadence having fired —
        #       otherwise a live cron would keep the not-fired alarm quiet over a dead delivery half.
        # It is a FIELD on an existing event, not a new event type, store or scheduler.
        _frontend_errors.CADENCE_MARKER: {
            "carrier": _frontend_errors.CADENCE_CARRIER,
            "trigger": _frontend_errors.CADENCE_TRIGGER,
            "window_hours": _frontend_errors.CADENCE_WINDOW_HOURS,
            "sources_adopted": frontend_error_sources_adopted,
            "clusters": frontend_error_clusters,
        },
        # T-11089 (SPEC-0105 §1) — the HOST axis. `host_sandbox_orphans` is the headline the card's
        # live-trigger criterion is read against (it must agree with a `ps` count taken at the same
        # time); the full axis rides beside it so the reading is reconstructible from the journal
        # alone — which pids, which cohort, which floor. Deliberately NOT folded into
        # `projects_flagged`: that counter answers "how many PROJECTS are in trouble?", and a host
        # finding belongs to no project (folding it would make every project look flagged at once).
        "host_sandbox_orphans": host_sandbox.get("orphans"),
        "host_sandbox": host_sandbox,
        # T-11631 (SPEC-0002 / T-11401) — the THIRD rotation reading, on the EXISTING event rather than
        # a new one. Like `host_sandbox` above it is deliberately NOT folded into `projects_flagged`
        # (a volume belongs to no project) and into no other counter: it is a REPORTED reading with no
        # threshold anywhere, so nothing here can refuse or move an exit code.
        "filesystem_headroom": filesystem_headroom,
        # T-12198 (SPEC-0203 rule 6) — the FORGOTTEN-BOX reading. `forgotten_boxes` is the headline
        # the belt is read against; the whole axis rides beside it so the reading is reconstructible
        # from the journal alone (which box, how long published, what the machine was doing). Like
        # its host-axis siblings it is deliberately NOT folded into `projects_flagged` (a rented box
        # belongs to no project) and into no other counter: report-only means no exit code moves.
        "forgotten_boxes": len(forgotten_box.get("findings") or []),
        "forgotten_box": forgotten_box,
        "backup_verify": backup.get("verdict"),
        # T-11015 (SPEC-0177 rule 3): the SCHEDULED-RUN record — which read-only conformance surfaces
        # this run exercised on the ENGINE, and how each exited. A closing card resolves ONE entry of
        # this list (`nightly_run_completed@<ts>#surface=<verb>`), which is why the per-surface rows
        # live here rather than being flattened to a verdict: the citation names a SURFACE.
        "conformance_verdict": conformance.get("verdict"),
        "conformance_surfaces": conformance.get("surfaces"),
        # T-12038 (SPEC-0105 §2c): the QUIET-LANE readings. Carried WHOLE rather than flattened to a
        # verdict because each reading is the citable unit — AC3 of the de-pin card names reading
        # LOCATORS, one per instrument per night, and a summary verdict would not be citable. It is
        # deliberately NOT folded into `projects_flagged` (a host reading belongs to no project) and
        # into no other counter: nothing here can refuse or move an exit code.
        "quiet_lane": quiet_lane,
        "transcript_archive": transcripts.get("verdict"),   # T-10122 (SPEC-0105 §2a) durability duty
        "transcript_archived": transcripts.get("archived"),
        "results": results,
        "bounded": "check-and-report only; no autonomous session spawned (CHARTER §6)",
        "generated_at": _utc_now_iso(),
    }

    # ---- report ----
    print(f"# nightly run (SPEC-0105 L1 — bounded v2 methodology-nightly; CHECK + REPORT only)")
    print(f"registry: {registry_path}")
    print(f"v2 projects: {len(results)} | flagged: {flagged} | freshness-alerts: {freshness_alerts}"
          f" | freshness-failing: {freshness_failing}"   # T-10798 — a DOWN subject is never folded into the total alone
          f" | freshness-non-adopted: {freshness_non_adopted}"
          f" | stale-born-waivers: {stale_born_waivers}"
          f" | concern-conformance-issues: {concern_conformance_issues}"
          f" | concern-drift-items: {concern_drift_items}"
          f" | unratified-adoptions: {unratified_adoptions}"
          f" | adoption-gaps: {adoption_gaps}"
          f" | pin-identity-violations: {pin_identity_violations}"   # T-10877 (SPEC-0122 R2)
          f" | carrier-shape-drifts: {carrier_shape_drifts}"
          f" | repo-storage-alerts: {repo_storage_alerts}"   # T-11063 (SPEC-0105 §1)
          f" | host-sandbox-orphans: {host_sandbox.get('orphans')}"   # T-11089 (SPEC-0105 §1)
          f" | forgotten-boxes: {len(forgotten_box.get('findings') or [])}"   # T-12198 (SPEC-0203 r6)
          f" | project-health-failures: {project_health_failures}"   # T-11359 (SPEC-0105 §1) — RED mains
          f" | project-health-non-adopted: {project_health_non_adopted}"
          f" | unreadable-ops-carriers: {unreadable_ops_carriers}"
          f" | frontend-error-sources: {frontend_error_sources_adopted}"   # T-10803 (SPEC-0170)
          f" | frontend-error-clusters: {frontend_error_clusters}"
          f" | backup-verify: {backup.get('verdict')}"
          + (f" (exit {backup['exit_code']})" if "exit_code" in backup else "")
          + (f" — {backup.get('reason')}" if backup.get("reason") else ""))
    # T-11015 (SPEC-0177 rule 3): STATE what the scheduled run exercised, per surface — the citable
    # half of this run. Named individually because a card cites ONE surface, and a bare aggregate
    # verdict would hide which guard actually ran (the same "silence is never the report" discipline
    # the cadence line below holds).
    print(f"conformance-surfaces: {conformance.get('verdict')}"
          + (f" — {conformance.get('reason')}" if conformance.get("reason") else "")
          + "".join(f"\n  · {s['surface']}: {s['verdict']}"
                    + (f" (exit {s['exit_code']})" if "exit_code" in s else "")
                    + (f" — {s['reason']}" if s.get("reason") else "")
                    for s in conformance.get("surfaces") or []))
    # T-10803 (AC3): the cadence ALWAYS states its subject count — and when that count is ZERO it says
    # so in words, naming the reason the run was empty. A sweep that printed nothing over zero adopted
    # sources would be indistinguishable from a sweep that never fired, which is the exact confusion
    # the whole cadence + its liveness tripwire exist to remove. Silence is never the report.
    if frontend_error_sources_adopted == 0:
        print(f"frontend-errors cadence: NO-OP — 0 adopted qualifying source(s) across "
              f"{len(results)} v2 project(s); nothing to fold. The sweep RAN (carrier: "
              f"{_frontend_errors.CADENCE_CARRIER}); this is a stated empty run, not silence.")
    else:
        print(f"frontend-errors cadence: {frontend_error_clusters} confirmed cluster(s) over "
              f"{frontend_error_sources_adopted} adopted source(s) — report-only "
              f"(carrier: {_frontend_errors.CADENCE_CARRIER}; trigger: "
              f"{_frontend_errors.CADENCE_TRIGGER})")
    # T-11089: the HOST sandbox axis, SUPPRESSED WHEN CLEAN (the `repo_storage` discipline — a healthy
    # host prints nothing here, so the day it does print is the day something is wrong). When it does
    # fire it NAMES its subjects: each pid with its age and the `-p` prefix that selected it, each
    # stale dir with its size — so the finding is actionable from the run's output alone, and a reader
    # can reconstruct the count with `ps` rather than having to trust it.
    if host_sandbox.get("verdict") == "alert":
        print(f"host-sandbox: ALERT — {host_sandbox.get('reason') or 'unreadable'}"
              f" (floor {host_sandbox.get('min_age_hours')}h; REPORT-ONLY — reaping is "
              f"`worktree sweep`'s job, this run killed nothing)")
        for f_ in host_sandbox.get("findings", []):
            if f_["kind"] == "orphan-sandbox-processes":
                print(f"  ! {f_['count']} orphan sandbox process(es), oldest {f_['oldest_age_hours']}h")
                for p_ in f_["processes"]:
                    print(f"      - pid {p_['pid']}  [-p {p_['prefix']}, age {p_['age_hours']}h]")
            elif f_["kind"] == "stale-sandbox-volume":
                print(f"  ! {f_['count']} sandbox dir(s) past the floor holding {f_['bytes']} bytes, "
                      f"oldest {f_['oldest_age_hours']}h")
                for d_ in f_["dirs"]:
                    print(f"      - {d_['path']}  [{d_['bytes']} bytes, age {d_['age_hours']}h]")
    # T-12198 (SPEC-0203 rule 6): the FORGOTTEN-BOX line, SUPPRESSED WHEN CLEAN (the `host_sandbox`
    # discipline above — a machine with no rented box, or with one that is genuinely working, prints
    # nothing here, so the day it does print is the day money is being spent on nothing). When it
    # does fire it NAMES its subject — which box, how long it has been published, and what the
    # machine was doing — so the finding is actionable from the run's output alone.
    if forgotten_box.get("verdict") == "alert":
        print(f"forgotten-box: ALERT — {forgotten_box.get('reason') or 'unreadable'}")
        for f_ in forgotten_box.get("findings", []):
            if f_["kind"] == "venue-idle-past-buffer":
                age = f_.get("published_age_min")
                print(f"  ! venue published {age if age is not None else '?'} min ago on box "
                      f"{f_.get('box')} (server {f_.get('server_id')}) and NOTHING is in progress on "
                      f"this machine — `venue unpublish` then `venue delete` (rule 6)")
            elif f_["kind"] == "unpublished-live-box":
                print(f"  ! live box {f_.get('name')} (server {f_.get('server_id')}, "
                      f"{f_.get('status')}) with NO publication record — nothing routes to it")
    # T-11631: the THIRD rotation reading — printed UNCONDITIONALLY, unlike the two suppressed-when-clean
    # blocks above. Those report findings, where silence means "nothing found"; this is a READING, and a
    # suppressed reading is indistinguishable from a run that never took it. REPORT-ONLY: no threshold is
    # compared, nothing is flagged, no exit code moves.
    if filesystem_headroom.get("verdict") == "ok":
        print(f"filesystem-headroom: {filesystem_headroom['free_bytes']} bytes free of "
              f"{filesystem_headroom['total_bytes']} ({filesystem_headroom['free_pct']}%) on the volume "
              f"holding {filesystem_headroom['path']} — REPORT-ONLY, no threshold (SPEC-0002 rotation "
              f"axis, third reading; free = available-to-us, excludes the root reserve)")
    else:
        print(f"filesystem-headroom: UNREADABLE — {filesystem_headroom.get('reason')} "
              f"(volume holding {filesystem_headroom.get('path')}; REPORT-ONLY — an unanswered "
              f"question, never a silent zero)")
    # T-12038 (SPEC-0105 §2c): the quiet lane prints UNCONDITIONALLY, like the filesystem-headroom
    # reading above and unlike the suppressed-when-clean finding blocks. Those report FINDINGS, where
    # silence means "nothing found"; this is a READING, and a suppressed reading cannot be told apart
    # from a run that never took it — which is precisely the state the de-pin gate must be able to
    # read off the record. Every registered instrument gets a line, including a failed or skipped one.
    print(f"quiet-lane (SPEC-0105 §2c): {quiet_lane.get('verdict')}"
          + (f" — {quiet_lane['reason']}" if quiet_lane.get("reason") else "")
          + (f" [{quiet_lane.get('held_slots')} admission slot(s) held; instruments run SERIALIZED; "
             f"REPORT-ONLY — a timing regression is a debt line, never a gate]"
             if quiet_lane.get("held_slots") else ""))
    _print_quiet_lane_readings(quiet_lane)
    # T-12097: the CONSUMER lanes, one block per project that DECLARED one. Rendered through the SAME
    # `_print_quiet_lane_readings` the engine block above uses — one renderer, so a change to how a
    # reading reads cannot land on one lane and not the other. A project that declared NOTHING prints
    # nothing: it registered no instrument, so there is no reading to suppress (this is not the
    # suppressed-when-clean shape the finding blocks use — there is genuinely nothing to report).
    for _r in results:
        _cl = _r.get("quiet_lane") or {}
        if not _cl.get("readings"):
            continue
        print(f"quiet-lane [{_r['name']}] (SPEC-0160 rule 10 → SPEC-0105 §2c, declared): "
              f"{_cl.get('verdict')}"
              + (f" — {_cl['reason']}" if _cl.get("reason") else "")
              + (f" [{_cl.get('held_slots')} admission slot(s) held on THIS repo's pool; instruments "
                 f"run SERIALIZED; REPORT-ONLY — a timing regression is a debt line, never a gate]"
                 if _cl.get("held_slots") else ""))
        _print_quiet_lane_readings(_cl)

    print(f"transcript-archive: {transcripts.get('verdict')}"
          + (f" ({transcripts['archived']} transcripts mirrored)" if transcripts.get("archived") is not None else "")
          + (f" — {transcripts.get('reason')}" if transcripts.get("reason") else ""))
    for r in results:
        q, c, f = r["queue"], r["corpus"], r["freshness"]
        if not r["present"]:
            print(f"  - {r['name']}: (path absent — {r['path']})")
            continue
        qline = (f"queue={q['verdict']} ready={q.get('ready', '?')}"
                 + (" OVER-CAP" if q.get("ready_over_cap") else "")
                 + (f" oldest-ready={q['oldest_ready_age_days']}d" if q.get("oldest_ready_age_days") else "")) \
            if q.get("verdict") != "skip" else f"queue=skip ({q.get('reason')})"
        cline = (f"corpus={c['verdict']}"
                 + (f" (stale root: {c['stale_root']})" if c.get("stale_root") else "")
                 + (f" — {c['reason']}" if c.get("reason") else ""))
        bw = r["born_waivers"]
        cc = r["concern_conformance"]
        cdr = r.get("concern_drift", {})
        ua = r.get("unratified_adoptions", {})
        adp = r.get("adapter", {})
        acp = r.get("adoption_completeness", {})
        ovl = r.get("override_ledger", {})
        nld = r.get("no_local_diff", {})
        csh = r.get("carrier_shape", {})
        rst = r.get("repo_storage", {})
        fec = r.get("frontend_errors", {})
        phe = r.get("project_health", {})
        print(f"  - {r['name']}: {qline} | {cline} | freshness={f['verdict']}"
              f" | born-waivers={bw.get('verdict')} | concern-conformance={cc.get('verdict')}"
              f" | concern-drift={cdr.get('verdict')} | unratified-adoptions={ua.get('verdict')}"
              f" | adapter={adp.get('verdict')} | adoption-completeness={acp.get('verdict')}"
              f" | override-ledger={ovl.get('verdict')}"
              f" | no-local-diff={nld.get('verdict')}"
              f" | carrier-shape={csh.get('verdict')}"
              f" | repo-storage={rst.get('verdict')}"
              f" | frontend-errors={fec.get('verdict')}"
              + (f" ({fec.get('confirmed')} confirmed)" if fec.get("verdict") == "ok" else "")
              # T-11359 (SPEC-0105 §1a) — appended LAST so the frontend-errors count stays attached
              # to the field it qualifies (a suffix that drifts onto the next field misreads).
              + f" | project-health={phe.get('verdict')}")
        # T-12008 (SPEC-0105 §1): the per-project STAGE-PROFILE line — what each lifecycle stage
        # cost here over the window, with each stage's machine-time share reported over the rows that
        # actually carry a duration. SUPPRESSED-WHEN-EMPTY: a project that closed no task in the
        # window prints nothing, because a row of nulls would be indistinguishable from a measured
        # quiet fortnight and would push the line every reader learns to skip. Report-only — no
        # verdict moves, no exit code moves, no event of its own (it rides nightly_run_completed).
        stp = r.get("stage_profile", {})
        if stp.get("verdict") == "alert":
            print(f"      ! stage-profile UNREADABLE — {stp.get('reason')}")
        elif stp.get("closed_tasks"):
            _st = stp.get("stages") or {}
            _top = sorted(_st.items(), key=lambda kv: -(kv[1].get("sum_seconds") or 0))[:3]
            _lead = (stp.get("lead_time") or {}).get("median_human") or "n/a"
            print(f"      · stage-profile ({stp.get('window_days')}d): {stp['closed_tasks']} closed"
                  f" | lead-time median {_lead}"
                  f" | audits/close {stp.get('audits_per_close')}"
                  f" | costliest stages: "
                  + ", ".join(
                      f"{name} {rec.get('sum_human')} (median {rec.get('median_human')}, "
                      f"p90 {rec.get('p90_human')}, n={rec.get('n')}, machine "
                      + (f"{round((rec.get('machine_time') or {}).get('share_of_wall') * 100)}%"
                         f" over {(rec.get('machine_time') or {}).get('sample')}"
                         if (rec.get("machine_time") or {}).get("share_of_wall") is not None
                         # no share: either the stage owns no duration-row TYPE (`not decomposable`) or
                 # its rows carry no duration (`no duration rows`) — both named, never rendered 0%
                 else f"{(rec.get('machine_time') or {}).get('sample') or 'not decomposable'}")
                      + ")"
                      for name, rec in _top)
                  + "  [report-only — `bin/yitc-v2 -C " + r["path"] + " graph query stage-profile`]")
        # T-12037 (SPEC-0105 §1 / SPEC-0119 rule 37): the per-project SEAM-READ line. Report-only.
        # THREE OUTCOMES, THREE LINES — and the third is the point of the check. An `alert` names the
        # amplified seams; a `skip` says NO COUNTERS out loud rather than printing nothing, because a
        # project that measured nothing and a project that measured clean must not render the same
        # (the audit-pre finding this check was rebuilt around); a clean `ok` prints nothing, the
        # suppressed-when-clean discipline every sibling line holds.
        srd = r.get("seam_reads", {})
        if srd.get("verdict") == "alert" and srd.get("seams"):
            # The project qualifier is printed only when it differs from the swept project — the
            # common case is one project's own rows, where repeating the name every time is noise.
            _named = ", ".join(
                f"`{s.get('verb')}`"
                + (f" [{s.get('project')}]" if s.get("project") and s.get("project") != r["name"]
                   else "")
                + f" {s.get('ratio')}x ({s.get('axis')})"
                for s in (srd.get("seams") or [])[:3])
            _rest = len(srd.get("seams") or []) - 3
            print(f"      ! seam-reads ({srd.get('window_days')}d): {srd.get('count')} of "
                  f"{srd.get('measured')} measured seam(s) READ MORE THAN THEY COMPOSED — {_named}"
                  + (f" (+{_rest} more)" if _rest > 0 else "")
                  + f" [bound {srd.get('bound')}x; remedy = the seam's ONE ReadScope at its wiring "
                    f"site or a narrower horizon, never a per-view cache — SPEC-0190 rule 10]")
        elif srd.get("verdict") == "alert":
            print(f"      ! seam-reads UNREADABLE — {srd.get('reason')}")
        elif srd.get("verdict") == "skip" and r["present"]:
            print(f"      · seam-reads: {srd.get('reason')} — NOT a clean reading; this project's "
                  f"read cost is UNMEASURED over the window (SPEC-0119 rule 37)")
        # T-10803 (SPEC-0170 / SPEC-0171): surface the conveyor's own health and its confirmed
        # clusters. An ADOPTED consumer whose source does not qualify is told WHY — never served the
        # healthy consumer's silence — and a cadence/on-demand disagreement names the clusters it
        # disagrees on. Report-only; the kernel never mutates the consumer repo.
        if fec.get("verdict") == "alert":
            print(f"      ! frontend-errors: {fec.get('reason')}")
            for v in fec.get("violations", []):
                print(f"        - {v}")
            for fp in fec.get("on_demand_diff", []):
                print(f"        - cadence/on-demand disagreement on cluster: {fp}")
        elif fec.get("verdict") == "ok" and fec.get("confirmed"):
            print(f"      ! frontend-errors: {fec['confirmed']} confirmed cluster(s) over the last "
                  f"{_frontend_errors.WINDOW_DAYS}d — report-only "
                  f"(`bin/yitc-v2 -C {r['path']} frontend-errors`)")
        # T-11359 (SPEC-0105 §1): the health detail — NAME the failing layer, and NAME every layer
        # the selection rule left out. Both halves are load-bearing: the first is the one line that
        # replaces N halted workers, and the second is why a reader can trust the first — an excluded
        # layer that printed nothing would be indistinguishable from a layer that passed. Suppressed
        # when there is genuinely nothing to say (an `ok` run with no exclusions prints nothing).
        if phe.get("unreadable"):
            print(f"      ! project-health UNREADABLE — {phe.get('reason')}")
        elif phe.get("verdict") == "none" and phe.get("reason"):
            print(f"      ! project-health: {phe['reason']} — NOT a green main, no health reading "
                  f"was taken (opt a layer in: `verify.health.layers` in {CONSUMER_OPS_CONTRACT})")
        for lrow in phe.get("layers", []):
            if lrow.get("outcome") == "fail":
                print(f"      ! project-health FAIL — main is RED at verify layer "
                      f"{lrow.get('layer')!r} (exit {lrow.get('exit_code')}): {lrow.get('detail')}")
            elif lrow.get("outcome") == "error":
                print(f"      ! project-health: layer {lrow.get('layer')!r} could NOT be run — "
                      f"{lrow.get('detail')} (a broken watch, not a green layer)")
        for v in phe.get("violations", []):
            print(f"      ! project-health misdeclaration [{v.get('layer')}]: {v.get('detail')}")
        for nrow in phe.get("not_run", []):
            print(f"      · project-health NOT-RUN [{nrow.get('layer')}]: {nrow.get('reason')} "
                  f"— not counted as passing")
        # T-10480 (SPEC-0125 VP1/VP2): surface an UNREADABLE vendor adapter, and each violation, so a
        # broken adapter→neutral-home chain is VISIBLE (report-only — the kernel never mutates the repo).
        if adp.get("unreadable"):
            print(f"      ! vendor-adapter UNREADABLE — {adp.get('reason')}")
        for v in adp.get("violations", []):
            print(f"      ! adapter {v.get('kind')}: {v.get('detail')}")
        # T-10694 (SPEC-0122 R6 / X-0543): surface an UNREADABLE ops carrier, and each adoption gap, so an
        # INVISIBLE partial adoption (a pinned dep's declared surface never integrated) is VISIBLE even in
        # a repo no session has opened (report-only — the kernel never mutates the consumer repo).
        if acp.get("unreadable"):
            print(f"      ! adoption-completeness UNREADABLE — {acp.get('reason')}")
        for v in acp.get("violations", []):
            print(f"      ! adoption {v.get('kind')}: {v.get('detail')}")
        # T-10877 (SPEC-0122 R2 HEALTH / SPEC-0172 rule 3): surface an UNREADABLE ops carrier, and each
        # pin-identity violation NAMING THE MODULE, so a surviving or locally patched neutral bridge
        # module is VISIBLE in a repo no session has opened — instead of only when someone calls
        # `init.no_local_diff` by hand. Suppressed-when-clean: an `ok` project prints nothing here
        # (report-only — the kernel never mutates the consumer repo).
        if nld.get("unreadable"):
            print(f"      ! no-local-diff UNREADABLE — {nld.get('reason')}")
        for v in nld.get("violations", []):
            print(f"      ! pin-identity {v.get('kind')}"
                  + (f" [{v.get('module')}]" if v.get("module") else "")
                  + f": {v.get('detail')}")
        # T-10664 (SPEC-0105 / fu_4e3c8da2dac9): surface each drifted live Class-C1 carrier so a real
        # consumer carrier that no longer runs is VISIBLE (report-only — the kernel never mutates the
        # consumer repo; this canary replaces the kernel-gate coverage T-10637 moved to fixtures).
        for cr in csh.get("carriers", []):
            if cr.get("state") in ("gate-drift", "shape-drift"):
                print(f"      ! carrier-drift Class-{cr.get('class')} ({cr.get('state')}): "
                      f"{cr.get('detail')}")
        # T-11063 (SPEC-0105 §1): surface a repo whose git housekeeping reported a problem nothing has
        # cleared — NAMING THE DATE, so the operator sees how long it has been standing, with the loose
        # pile as sizing context. Suppressed-when-clean: a repo with no `gc.log` prints nothing here
        # (report-only — the kernel never runs gc/prune, it only reports).
        if rst.get("unreadable"):
            print(f"      ! repo-storage UNREADABLE — {rst.get('reason')}")
        for fnd in rst.get("findings", []):
            # T-11399: NAME THE GITDIR — `gc.log` is worktree-scoped, so "which one" is not derivable
            # from the project row, and the remediation differs per gitdir. The hint points at the
            # finding's OWN checkout, falling back to the gitdir path when git's pointer file did not
            # resolve one, so it never invents a path.
            where = fnd.get("checkout_path") or r["path"]
            hint = (f"`git -C {where} gc`" if fnd.get("checkout_path")
                    else f"a gc from the checkout owning {fnd.get('gitdir_path')}")
            # The `since <date> (<n>d)` clause keeps its established position and wording — the
            # gitdir is APPENDED to it, so this widening adds the missing "which one" without
            # restating the line the operator already reads.
            since = (f"since {fnd.get('gc_log_date')} ({fnd.get('age_days')}d)"
                     if fnd.get("gc_log_date") else "(date unreadable)")
            print(f"      ! housekeeping-blocked {since} in gitdir {fnd.get('gitdir')}"
                  f": {fnd.get('message')}"
                  f" — {fnd.get('loose_objects')} loose objects,"
                  f" {round((fnd.get('loose_bytes') or 0) / (1024 ** 3), 2)} GiB"
                  f" (clear with {hint} once the cause is understood — the nightly"
                  f" never runs it)")
        # T-10292: surface an UNREADABLE ops carrier ONCE, naming the parse error — both concern checks
        # alert on the same single fault, so print the cause, not the symptom twice.
        if cc.get("unreadable") or cdr.get("unreadable"):
            reason = cc.get("reason") if cc.get("unreadable") else cdr.get("reason")
            print(f"      ! ops-carrier UNREADABLE — {reason}")
        # SPEC-0110: surface every non-fresh pipeline so a synthetic miss / stale run is VISIBLE — and
        # (T-10798 / SPEC-0174 rule 3) every FRESH-AND-UNREACHABLE one, which is bad news the state axis
        # alone renders as nothing at all. Formatting lives in `_freshness_pipeline_note` (one home): a
        # clean record returns None and correctly prints nothing.
        for pl in f.get("pipelines", []):
            note = _freshness_pipeline_note(pl)
            if note:
                print(f"      ! {note}")
        # T-9642: surface every stale born-waiver path so an unreplaced init placeholder is VISIBLE.
        for swp in bw.get("stale_waivers", []):
            print(f"      ! born-waiver {swp}: still carries the init placeholder (never replaced)")
        # T-10030 (SPEC-0119 rule 8 / SPEC-0128): surface each concern-conformance issue so a
        # declare-or-waive stance drift / expired waiver is VISIBLE.
        for si in cc.get("stance_issues", []):
            print(f"      ! concern-stance {si}")
        for ew in cc.get("expired_waivers", []):
            print(f"      ! expired-waiver {ew}: `expiry:` has lapsed — refresh or re-waive")
        # T-10516 (SPEC-0119 rule 13): surface each unratified adoption so the birth-sentinel residual is
        # VISIBLE in a repo no session has opened. NAMES the owner's exit and never auto-ratifies.
        for rec in ua.get("records", []):
            print(f"      ! unratified-adoption {rec.get('concern')}: records `adopt` but is still stamped "
                  f"`owner: init` (the birth sentinel — the bootstrap wrote it, nobody reviewed it) over a "
                  f"DECLARED section. Ratify: `bin/yitc-v2 -C {r['path']} init "
                  f"--adopt-concern {rec.get('concern')}:adopt:<owner>` — or waive the section")
        # T-10172 (SPEC-0143 Rule 3): surface each drifting concern so a moved kernel contract is
        # VISIBLE (report-only, review-request per Rule 4 — the owner decides adopt/waive/na).
        for dr in cdr.get("drifts", []):
            _adopted = dr.get("adopted") or "none"
            print(f"      ! concern-drift {dr.get('concern')}: adopted={_adopted} "
                  f"current={dr.get('current')} ({dr.get('reason')}) — review + re-adopt/waive/na")

    # T-10172 (SPEC-0143 Rule 3): emit ONE report-only concern_drift_surfaced per DRIFTING project
    # (suppressed-when-clean — no emit for a level/skip project). The emit rides the KERNEL journal
    # (this nightly runner's own events.jsonl), NEVER the consumer repo (the §6 fence). Skipped under
    # --dry-run (fully read-only) — the guard below returns before any emit.
    if not dry_run:
        for r in results:
            cdr = r.get("concern_drift", {})
            if cdr.get("verdict") == "alert" and cdr.get("drifts"):
                _append_event("concern_drift_surfaced", None, {
                    "seam": "nightly", "project": r["name"], "path": r["path"],
                    "count": len(cdr["drifts"]), "drifts": cdr["drifts"]})

    # SPEC-0143 Rule 4 (T-10173): ESCALATION — the report-only reconcile above IS the default
    # review-request; a drift escalates to a governed `cross request` ONLY where a PRE-EXISTING governed
    # gate already blocks on that concern (the _GATE_BACKED_CONCERNS set — the deploy Class-S security
    # gate today). The kernel surfaces + REQUESTS (one kind=note item, from kernel → the drifting
    # consumer, dedup-idempotent per concern-version); the consumer's OWNER decides + records adoption
    # (Rule 5 fence — the kernel never mutates the consumer repo). Skipped under --dry-run and when the
    # cross collaborators are not injected (the test path), so the report-only default is unchanged.
    if not dry_run and cross_emit is not None and cross_log_path is not None \
            and cross_lock_path is not None and cross_self_name is not None:
        escalations: list = []
        for r in results:
            cdr = r.get("concern_drift", {})
            if cdr.get("verdict") != "alert":
                continue
            for dr in cdr.get("drifts") or []:
                if dr.get("concern") in _GATE_BACKED_CONCERNS:
                    escalations.append({"to": r["name"], "concern": dr.get("concern"),
                                        "current": dr.get("current"), "adopted": dr.get("adopted"),
                                        "reason": dr.get("reason")})
        from lib import cross  # lazy — the shared-log cross mechanism (reuse, not a new write path)
        filed = cross.auto_file_concern_drift_escalations(
            escalations=escalations, cross_log_path=cross_log_path, lock_path=cross_lock_path,
            self_name=cross_self_name, cross_emit=cross_emit)
        if filed:
            print(f"concern-drift ESCALATED (SPEC-0143 Rule 4): {len(filed)} cross request(s) filed "
                  f"at a pre-existing governed blocking gate → {', '.join(filed)}")

    if dry_run:
        print("\n--dry-run: read-only — NO nightly_run_completed event emitted, NO backup snapshot.")
        return

    _append_event("nightly_run_completed", None, data)
    print(f"\nnightly_run_completed emitted — projects_checked={len(results)} "
          f"projects_flagged={flagged} backup_verify={backup.get('verdict')}")
