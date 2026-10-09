"""Dispatch verb-family for the yitc-v2 CLI — `dispatch` (the THIN background-worker launcher,
T-0558 / T-0580; the orchestrate-posture controller's spawn chokepoint, patterns/background-session-
operation.md §Dispatch). The fifth layer-2 verb-family extraction (after scenario.py / error.py /
gates.py / spec.py), plan `layer-2-tail-remainder-decomposition-of-bin-yitc-v` wave-2a card T-9335.

bin/yitc-v2 keeps the thin argparse residue cmd_dispatch (the `set_defaults(func=…)` entrypoint, wiring
unchanged) which delegates here, injecting the host collaborators it needs — the spec.py / audit.py
verb-family precedent (family bodies in lib, host thin residue + injected host deps), so a `-C` REPO_ROOT
rebind and every `monkeypatch.setattr(yitc, …)` stay honored at call time.

The PROVIDER BINDING `_spawn_claude_worker` + the `DISPATCH_PROVIDERS` registry DELIBERATELY stay
host-side and are injected here (the AUDIT_PROVIDERS precedent — recipe step 2/4): the registry adapter
contract `(brief, session_id, env, log_path) -> pid` carries no slot for injected host globals, and
tests MUTATE the host `yitc.DISPATCH_PROVIDERS` dict (a fake adapter), so cmd_dispatch reads the INJECTED
host dict (the same object) and the mutation is honored. The two shared worker-discipline consts
SYNC_TO_LAND_RULE + _SYNC_REMINDER_STAGES move HERE (the dispatch-domain owner) and the host keeps a
re-export alias under each historical name, since host `cmd_stage` (T-0687) also reads them.

Identity-agnostic KERNEL module (SPEC-0073 bin/ HARD class — travels with the engine). It imports
stdlib plus the lower extracted leaf `lib.journal` — leaf-up only (the gates.py / session.py
precedent), for the single dispatch-class vocabulary carrier the watcher cue renders (T-10253);
journal.py never imports dispatch.py, so there is no cycle. It NEVER back-imports the host.
Behaviour is byte-identical to the inline originals — the test suite is the oracle.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import os
import re
import signal
import sys
import time
from pathlib import Path

from lib import events   # the `_byte_tail` bound the watcher's premature_exit row uses (T-12896)
from lib import journal  # lower extracted leaf — the DISPATCH_CLASS_VOCAB carrier (T-10253)
from lib import task as task_mod  # SPEC-0166: the pure `_premise_dispatch_block` predicate (single
                                  # home in task.py) the dispatch preflight refuses on (acyclic)


class OrphanTeardownRefused(Exception):
    """T-9689 — raised (instead of `_die`) by the host-bound `_redispatch_dead_orphan` wrapper when the
    confirmed-dead-orphan teardown is refused (e.g. the claim somehow LANDED in-progress on main, or a
    `git branch -D` failed). cmd_dispatch catches it and FAILS CLOSED to the protective in-flight SKIP —
    a teardown refusal must never abort the whole dispatch batch, and never re-dispatch over an
    unverifiable state."""


def _dispatch_worker_env(base_env: "dict", session_id: str, *, SESSION_IDENTITY_REGISTRY,
                         provider_carriers=()) -> "dict":
    """Build the worker's environment for a dispatch launch (PURE — no side effects; the testable
    core of the scrub-ALL-then-set guarantee, M2). Copy `base_env`, then:
      (1) SCRUB every inherited identity+transcript carrier: the LIVE `SESSION_IDENTITY_REGISTRY['env']`
          (read here, so a newly-registered identity carrier is scrubbed by CATEGORY — the T-0554
          single-SoT drift-guard, external-review (A) "scrub the WHOLE set") PLUS `provider_carriers`
          (the D-0030 PROVIDER transcript carriers the host injects). T-10152/SPEC-0137 Rule-8b removed
          the provider carriers from the IDENTITY registry, yet a stale inherited provider carrier must
          STILL be shed so the worker computes its OWN context epoch and joins its OWN transcript.
          Setting a fresh id alone is INSUFFICIENT — an inherited highest-precedence carrier overrides
          --session-id for the worker's tooling reads (the §Findings H1-CAVEAT controller↔worker
          collapse). Scrub-ALL closes that.
      (2) SET the identity carrier (registry env[0] = YITC_SESSION_REF) to the fresh id, so the
          worker's OWN `session start` RESOLVES the launcher id rather than minting a new one
          (`_session_start_identity` reads the carried self-ref, T-10152).
      (3) SET YITC_EXPECTED_SESSION_REF = session_id — the launcher-assigned EXPLICIT contract input
          for the worker fail-closed self-check (T-0561). DISTINCT from the resolution carriers, so
          it is never itself resolved AS the identity (external-review (3): `expected` must be an
          explicit input, fallback to env-resolution forbidden).

    SPEC-0137 Rule 7 — this launch-set id is an OPTIONAL FAST-PATH, NOT the source of truth.
    Where v2 OWNS launch, setting the worker's identity at spawn is a legitimate optimization: the
    frozen `expected` (step 3) is Rule 2.1's selector-1a — the EXCLUSIVE fail-closed keying authority
    the worker keyer short-circuits on (`_resolve_session_ref`, T-0561), so a dispatched worker never
    needs rediscovery. But it is NEVER a REQUIRED carrier: whenever launch control is ABSENT
    (interactive / IDE / CI — no dispatcher froze an id; direnv no-ops in non-interactive shells,
    tmux panes go stale, system units start from a clean env), NO YITC_EXPECTED is set and the SAME
    keyer DEGRADES to Rule-2 rediscovery over v2-owned records + Rule-5 fail-close — reading NO
    provider env var. Nothing new is stored here (Rule 7): the launch-set id IS Rule 2.1's frozen
    `expected`; this is the launch fast-path over the fail-closed rediscovery keyer, not a parallel
    identity path.
    """
    env = dict(base_env)
    scrub = dict.fromkeys(tuple(SESSION_IDENTITY_REGISTRY["env"]) + tuple(provider_carriers))
    for carrier in scrub:
        env.pop(carrier, None)
    # SPEC-0137 Rule 7 fast-path (NOT a required carrier): set the carrier (first registry entry) so
    # the worker's own `session start` resolves the launcher id; and the frozen `expected` (Rule 2.1
    # selector-1a) so the worker keyer short-circuits. Absent launch control the keyer degrades to
    # rediscovery (no reliance on the provider injecting anything).
    env[SESSION_IDENTITY_REGISTRY["env"][0]] = session_id
    env["YITC_EXPECTED_SESSION_REF"] = session_id
    # T-13203 — the worker's engine-named scratch root (logs/clones/probes); its land/park reclaims it.
    _scratch = session_scratch_root(session_id)   # path only (PURE); the launch site creates it
    if _scratch is not None:
        env["YITC_SCRATCH_DIR"] = str(_scratch)
    # (4) SET YITC_SYNCHRONOUS_LAND — the worker MUST run `land` synchronously in the FOREGROUND to the
    #     `LAND: OK` token (SPEC-0103 §1). This marker is what `cmd_land`'s worker-synchronous guard
    #     (worktree.py `_resolve_land_detached_signal`) keys off to REFUSE a detached/backgrounded land,
    #     turning the T-9600/T-9601 prose-only "prefer foreground" guidance into hard enforcement so a
    #     headless worker cannot yield-and-die mid-land (T-10136 / X-0211 ask 1). Only DISPATCHED workers
    #     carry it; an interactive/CI land (no dispatcher) never sets it → the guard is a byte-identical
    #     no-op there.
    env["YITC_SYNCHRONOUS_LAND"] = "1"
    # (5) SET YITC_DISPATCH_LAUNCHER = <this launcher's pid>:<start time> (T-12830, X-1527). The worker
    #     is reparented onto init (T-11906), so its holder reads cannot see this launcher as kin; the
    #     token lets `_live_path_holders` spare it instead of counting it as a foreign holder of the
    #     worktree the worker adopts. An inherited value is always dropped first, never passed through.
    env.pop(journal.DISPATCH_LAUNCHER_ENV, None)
    start = journal._proc_start_time(os.getpid())
    if start:
        env[journal.DISPATCH_LAUNCHER_ENV] = f"{os.getpid()}:{start}"
    return env


def _resolve_dispatch_briefs(args: argparse.Namespace, n: int, *, _as_list, _die, REPO_ROOT) -> "list[str]":
    """Resolve N worker briefs (the spawn prompts), one per dispatched task, aligned 1:1 with the
    task list (T-0580). The launcher does NOT compose a brief from the task (that would be planning —
    the controller's duty); it only carries what it is handed. Brief channels (the `--brief`/`-f`/
    stdin idiom, now repeatable for the multi-task list):

      - EITHER repeated `--brief STR` XOR repeated `-f/--brief-file PATH` XOR a single stdin stream.
        Mixing `--brief` and `-f` is REJECTED — argparse preserves per-option order but NOT the
        interleaving ACROSS two options, so a mixed `--task A --brief b --task B -f f` could not be
        unambiguously paired (fail-closed rather than mis-pair a worker's brief).
      - stdin is the single-task fallback only (one stream = one brief).
      - Exactly N non-empty briefs required (one per task); a count mismatch or an empty brief is a
        fail-closed `_die` — so a bad invocation launches NOTHING (the all-or-nothing preflight).
    """
    inline = _as_list("--brief", getattr(args, "brief", None))
    files = _as_list("--brief-file", getattr(args, "brief_file", None))
    if inline and files:
        _die("dispatch: pass briefs through EITHER --brief OR -f/--brief-file, not both "
             "(ambiguous task↔brief pairing across two options)")
    if inline:
        briefs = list(inline)
    elif files:
        briefs = []
        for bf in files:
            p = Path(bf)
            if not p.is_absolute():
                p = REPO_ROOT / bf
            if not p.exists():
                _die(f"dispatch: --brief-file not found: {bf}")
            briefs.append(p.read_text(encoding="utf-8"))
    elif not sys.stdin.isatty():
        briefs = [sys.stdin.read()]   # single stream → single brief (single-task only)
    else:
        briefs = []
    if len(briefs) != n:
        _die(f"dispatch: {n} task(s) but {len(briefs)} brief(s) — supply exactly one brief per task "
             "(repeat --brief or -f in task order; stdin carries a single brief, single-task only)")
    for i, b in enumerate(briefs):
        if not b.strip():
            _die(f"dispatch: empty brief for task #{i + 1} — a worker needs a prompt")
    return briefs


# The standing worker-execution-discipline preamble the launcher PREPENDS to every dispatched
# worker's brief (T-0622) — so a headless one-shot Build worker is told the contract UPFRONT, not
# left to the brief author (the T-0613 stall: a worker backgrounded its test suite + yielded, its
# headless process exited before commit/land, the task stranded built-but-UNLANDED). It carries
# (a) the synchronous-to-LAND rule + (b)/(c) the subagent role rule. RULE HOME (single-SoT, SPEC-0005
# rule 8): the sync rule lives in patterns/background-session-monitoring.md §Synchronous-to-LAND; the
# subagent carve-out is SETTLED by the orchestrate-posture plan §Scope-of-the-ban (owner-clarified
# 2026-06-07) + the dispatch-via-sub-sessions plan and restated in §Dispatch mode — this preamble is
# an OPERATIONAL brief that POINTS at those homes, never a competing policy home. Provider-neutral
# text (CHARTER §P4b — no provider brand names in the shipped rule prose).
# The ONE canonical synchronous-to-LAND sentence (T-0622). SINGLE SOURCE (CHARTER §P5): BOTH the
# session-start DISPATCH_WORKER_PREAMBLE (full preamble, below — point 1 INTERPOLATES this) AND the
# just-in-time stage-entry reminder (cmd_stage, T-0687) consume THIS symbol — never a parallel string
# copy, so the two delivery points cannot drift. Rule home: patterns/background-session-operation.md
# §Synchronous-to-LAND.
# It ALSO carries the SPEC-0103 scope-boundary CARVE-OUT inline (T-9516): the carve-out lives in THIS
# single-source sentence so it co-delivers wherever the "reach LAND or ABANDONMENT" pressure is shown
# (preamble point 1 AND the cmd_stage stage-entry reminder) — a pressure sentence without its own
# carve-out re-created the contradiction the T-9495 incident exposed (CHARTER §P7). Rule home: SPEC-0103.
# It ALSO carries the SPEC-0180 OVER-CAP EXIT inline (T-11104), for the same single-source reason: the
# worker meets the per-call cap AT this pressure sentence, so the sanctioned held-turn path has to be
# DELIVERED here — beside "HOLD your turn and re-invoke `land`" — or the worker discovers it only as a
# refusal, if at all. Mechanism home: SPEC-0180 (shipped by T-11101 + T-11102); recipe prose:
# patterns/background-session-dispatch.md §Long-command-exceeds-tool-timeout (T-11103).
# T-11294 (X-0994) — the detached-land LOG PATH is REPO-SCOPED, not host-global. Task ids are
# allocated PER-REPO, so <project> T-0351 and <project> T-0351 are different cards that used to resolve
# to ONE `/tmp/land-T-XXXX.log` on a shared host. The reported occurrence: the file already existed
# owned by another host user, the detached land got `Permission denied` and exited 1 WITHOUT EVER
# STARTING, and the worker's `^LAND: (OK|ABORT)` poll then read the OTHER project's `LAND: OK` as its
# own terminality — a false-GREEN land report with nothing failing closed before it (SPEC-0165 rule 1:
# no mechanism to name, so the rule was SILENT). The token contract itself (SPEC-0180 rule 2c
# capture-wide/gate-narrow) is CORRECT and unchanged; the defect was the shared PATH.
# The scope key is basename + a hash of the RESOLVED root: the basename alone collides again for two
# checkouts named alike (a consumer clone, a worktree), and an mkstemp-style random name cannot be
# spelled once and read twice by a recipe a human follows — which is also what keeps the WRITE line
# and the READ line provably the same string (one interpolated variable, used twice).
_ENGINE_SELF_ROOT = Path(__file__).resolve().parents[2]


def _scratch_user() -> str:
    """The user token of the detached-run scratch paths: `u<euid>` (T-12800).

    /tmp is sticky, so a scratch file a DIFFERENT unix user left behind cannot be truncated or
    rewritten by this one — the detached shell's `echo $$ > <pid>` and `> <log>` fail, and the
    poll then reads the prior user's pid and `TEST: PASS` / `LAND: OK` token as this run's (the
    cross-user re-dispatch false-GREEN, <project> 2026-09-21). The NUMERIC effective uid, not an
    account name: ownership follows the euid (not `$USER`), and a sanitized name can collide."""
    return f"u{os.geteuid()}"


# T-13203 — THE PER-SESSION SCRATCH ROOT. Sessions and dispatched workers used to invent their own
# /tmp names for logs, clones and probes; nothing owned them, so nothing reclaimed them (~44 GB
# measured 2026-09-28). One engine-named root per session, `<tempdir>/yitc-scratch-<session_ref>/`:
# the session ref IS the owner stamp (a path view, no store). Reclaimed when the owner ends — a
# dispatched worker's land/park (`reclaim_worker_scratch_root`), else `worktree sweep`'s scratch arm
# once the ref is not proc-alive and the root is past the age floor. The engine's detached land/test
# log+pid stay OUTSIDE it by design (a poller reads them past land's own teardown); the sweep's
# transport arm reclaims those.
SCRATCH_ROOT_PREFIX = "yitc-scratch-"
# T-13594 — HOW a scratch checkout is made, spelled ONCE and read by both surfaces that name the
# root (the session-start scratch line and the worker preamble), so the two cannot drift. Full clones
# of this repository filled /tmp with ~118 GB in one day (2026-10-05).
SCRATCH_CLONE_RULE = ("a scratch checkout of this repository is made with `git worktree add` when a working "
                      "tree of a commit is enough, or `git clone --shared` / `git clone --reference <the main "
                      "repository>` when a separate repository is needed — never a full clone (a --shared / "
                      "--reference clone borrows the main repository's objects, so it breaks if those are removed)")
_SCRATCH_REF_RE = re.compile(r"[A-Za-z0-9._-]+")


def session_scratch_root(ref, base=None) -> "Path | None":
    """`<base or tempdir>/yitc-scratch-<ref>` (PURE) — None for a missing or path-unsafe ref."""
    import tempfile
    if not ref or not _SCRATCH_REF_RE.fullmatch(str(ref)) or str(ref) in (".", ".."):
        return None
    return Path(base if base is not None else tempfile.gettempdir()) / f"{SCRATCH_ROOT_PREFIX}{ref}"


def ensure_session_scratch_root(ref, base=None) -> "Path | None":
    """Create the root (0700) best-effort; returns it, or None when it could not be named/created."""
    root = session_scratch_root(ref, base)
    if root is None:
        return None
    try:
        root.mkdir(mode=0o700, exist_ok=True)
        if root.is_symlink() or not root.is_dir() or root.stat().st_uid != os.geteuid():
            return None   # never adopt a symlink or another user's pre-created dir as OUR root
        os.chmod(root, 0o700)   # a pre-existing root is made private too, not only a fresh one
    except OSError:
        return None
    return root


def reclaim_worker_scratch_root(_env=None, base=None) -> "str | None":
    """Remove a DISPATCHED worker's own scratch root at its land/park teardown (T-13203 AC3).

    Acts ONLY when `YITC_SCRATCH_DIR` is set (dispatch exports it to workers only) AND is exactly the
    engine-shaped root for THIS worker's own `YITC_EXPECTED_SESSION_REF` — a direct child of the temp
    base, a real dir, not a symlink. A root naming any other ref (another session's) is left alone.
    Returns the removed path; never raises."""
    import shutil
    env = os.environ if _env is None else _env
    raw = env.get("YITC_SCRATCH_DIR") or ""
    try:
        p = Path(raw)
        if not raw:
            return None
        want = session_scratch_root(env.get("YITC_EXPECTED_SESSION_REF"), base)
        if want is None or str(p) != str(want) or p.is_symlink() or not p.is_dir():
            return None
        shutil.rmtree(p, ignore_errors=True)
        return None if p.exists() else str(p)
    except Exception:
        return None


def _land_log_path(repo_root, task: str = "T-XXXX") -> str:
    """The user+repo-scoped detached-land log path the preamble recipe spells (PURE per user).

    Two DIFFERENT repo roots with the SAME task id yield two DIFFERENT paths — the property the
    T-11294 tripwire drives directly — and so do two DIFFERENT users (T-12800)."""
    root = Path(repo_root).resolve()
    slug = re.sub(r"[^A-Za-z0-9._-]", "-", root.name) or "repo"
    key = hashlib.sha256(str(root).encode("utf-8")).hexdigest()[:8]
    return f"/tmp/yitc-land-{_scratch_user()}-{slug}-{key}-{task}.log"


def _land_pid_path(land_log: str) -> str:
    """The PIDFILE sibling of the detached-land log (PURE) — the SAME repo-scoped key, `.pid`.

    Derived FROM the log path rather than re-computed from the root, so the two can never name
    different keys (the T-11294 write==read discipline, applied to the second file the recipe
    spells). The detached shell writes its OWN pid here and then `exec`s the land, so the recorded
    pid IS the land process — a handle that does not depend on the caller's job-control setting
    (T-11336 / X-1011)."""
    return (land_log[:-4] if land_log.endswith(".log") else land_log) + ".pid"


# T-12431 — the SAME run-scoped log+pid discipline, for the DETACHED Stage-6 SUITE. The over-cap
# exit above covered `land` only, so a worker whose full `task test --run` (10-15 min on this host)
# could not fit the harness's per-call foreground cap had NO sanctioned exit: three of ten wave
# workers on 2026-09-12 backgrounded the suite through the provider's background tool, yielded the
# turn, and were killed at the headless 600 s background-wait ceiling (deviation fingerprint
# worker-backgrounds-full-test-run-killed-by-headless-bg-wait-ceiling; T-12416 / T-12404 / T-12409).
# The path is DERIVED FROM the land log rather than re-computed from the root — the same reason
# `_land_pid_path` is (above): one T-11294 scope key, spelled once, so the suite log can never name
# a different repo scope than the land log rendered into the same preamble.


def _test_log_from_land(land_log: str) -> str:
    """The detached-SUITE log path, derived from the detached-LAND log path (PURE).

    ONE scope rule, two names: only the `yitc-land-` / `yitc-test-` discriminator differs, so the
    T-11294 repo-scoping (basename + 8-hex of the resolved root + the task id) is INHERITED rather
    than re-spelled — two checkouts sharing a task id still get two different suite logs."""
    return land_log.replace("/yitc-land-", "/yitc-test-", 1)


def _test_log_path(repo_root, task: str = "T-XXXX") -> str:
    """The repo-scoped detached-SUITE log path the preamble recipe spells (PURE).

    Routed through `_land_log_path` so the two paths cannot acquire different scope keys."""
    return _test_log_from_land(_land_log_path(repo_root, task))


def _test_pid_path(test_log: str) -> str:
    """The PIDFILE sibling of the detached-suite log (PURE) — `_land_pid_path`'s `.pid` rule, reused.

    Same X-1011 property: the detached shell writes its OWN pid there and then `exec`s the suite, so
    the recorded pid IS the test process and the handle does not depend on job control."""
    return _land_pid_path(test_log)


def _build_over_cap_test_rule(test_log: str, test_pid: str) -> str:
    """The SHARED over-cap paragraph for the Stage-6 SUITE (PURE), interpolated into BOTH regimes.

    It is ONE string reaching both heads for the same reason the SPEC-0103 tail is (T-12303): the
    suite meets the per-call cap in EVERY dispatch regime — a controller-lands worker never lands,
    but it still runs Stage 6 — so a paragraph living in only one head is a rule half the fleet
    never receives. That is not hypothetical: this card's OWN dispatch is controller-lands, and its
    Controller had to hand-spell this recipe into the brief delta because the head carried none."""
    return (
    "OVER-CAP EXIT FOR THE STAGE-6 SUITE (SPEC-0180) — the SAME held-turn rule for `task test --run`, "
    "which runs longer than the per-call FOREGROUND cap: run it DETACHED while you HOLD YOUR TURN. "
    f"Launch `: > {test_pid}; setsid bash -c 'echo $$ > {test_pid}; exec "
    "<the SAME `task test --run --evidence \"<summary>\"` invocation you would have run in the "
    f"foreground> > {test_log} 2>&1' </dev/null &` (`>` TRUNCATE, so the log holds THIS attempt "
    f"only), RESOLVE the handle from the pidfile — `TEST_PID=$(timeout 30 bash -c 'until [ -s {test_pid} ]; "
    f"do sleep 1; done; cat {test_pid}')` — NEVER as `$!` (X-1011), and POLL in BOUNDED FOREGROUND windows, "
    "each re-invoked INLINE in the SAME turn — "
    "`timeout 300 bash -c 'until grep -qE \"^TEST: (PASS|FAIL)\" "
    f"{test_log} || {{ [ -s {test_pid} ] && ! kill -0 \"$(cat {test_pid})\" 2>&-; }}; "
    "do sleep 10; done'` — until the `^TEST: (PASS|FAIL)` token OR the test PROCESS EXITING "
    "(`kill -0 $TEST_PID` failing). RUN EVERY `bash -c` SCRIPT EXACTLY AS PRINTED — single-quoted, "
    "every path written out, no `$VAR` of your own shell and no positional parameters: the harness "
    "REFUSES a non-literal `-c` script (X-1857). The "
    "window reads the pid from the pidfile itself: a script naming `$TEST_PID` would poll an empty "
    "pid and read a running suite as finished. Confirm the verdict against the journal row "
    "(`yitc-v2 journal query --type tests_passed --task T-XXXX`). Unlike the land this takes NO "
    "admission claim and NO liveness watchdog (the suite integrates nothing), and it is never an exit "
    "from a FAILING suite; what may be detached is the OS PROCESS, never the TURN. "
    "The SAME recipe covers `audit pre|post` (SPEC-0180 rule 9): substitute the SAME `audit pre|post "
    "--task T-XXXX` invocation, name its log and pidfile with `audit` in place of `test`, and poll "
    "`^AUDIT: (GREEN|YELLOW|RED|ABORT)` (its FINAL stdout line on EVERY exit; stderr under `--preview`) "
    "beside `kill -0` on its pid; confirm the verdict in the saved `decisions/T-XXXX-audit-<stage>.yaml`. "
    )


def _build_sync_to_land_rule(land_log: str = "", *, controller_lands: bool = False) -> str:
    """The ONE synchronous-to-LAND sentence, rendered for ONE dispatch target (PURE).

    `land_log` is the repo-scoped path from `_land_log_path`; the default renders for THIS checkout,
    so even the module constant below carries no host-global literal. The same variable is
    interpolated at BOTH the redirect (write) and the poll (read) occurrence — the two cannot drift.

    T-12303 — `controller_lands` selects the OTHER land REGIME, and it exists here (a keyword on the
    existing single source) rather than as a second module constant BECAUSE the two regimes share
    their whole escalation tail. Under `False` (every pre-existing caller — the default renders
    `SYNC_TO_LAND_RULE` BYTE-IDENTICALLY) the worker lands ITSELF and needs the SPEC-0180 over-cap
    detached-land recipe. Under `True` the worker STOPS after `task close` and the CONTROLLER lands
    from main, so that recipe is inapplicable and the HEAD is replaced. Only the HEAD differs: the
    SPEC-0103 EXCEPTION / auditor-outage SUBCLASS / PAUSE-SHAPE FORK TAIL below is ONE string both
    regimes return, so an edit to it moves BOTH delivery paths or neither — which is the whole
    reason this is a parameter and not a parallel text (audit-pre pass-1 finding fp1:e9cce500e455b89d:
    a second stop/land contract beside this one is policy text that can drift)."""
    land_log = land_log or _land_log_path(_ENGINE_SELF_ROOT)
    land_pid = _land_pid_path(land_log)
    test_log = _test_log_from_land(land_log)
    test_pid = _test_pid_path(test_log)
    head = (
    "Run long commands (tests, audits) synchronously/blocking; NEVER background-and-await an async "
    "notification. You succeed ONLY if YOU yourself reach `LAND: OK` in THIS turn — a yield is "
    "ABANDONMENT: the controller force-recovers the task and your build is wasted (T-0622). A long "
    "SILENT `land` is EXPECTED, NOT a hang: it may be waiting for a SPEC-0132 verify-admission slot "
    "(`waiting_for_verify_admission_slot` heartbeat) — HOLD your turn and re-invoke `land` inline "
    "until `LAND: OK`. "
    "OVER-CAP EXIT (SPEC-0180) — when your `land` CANNOT FIT the per-call FOREGROUND cap (a `bin/**` / "
    "`tests/**` / `yitc-ops.yaml` diff doubles the verify), run it DETACHED while you HOLD YOUR TURN. "
    "Present a held-turn CLAIM naming YOUR OWN dispatched-worker pid: `WPID=$(grep "
    "bg_dispatch_launched events.jsonl | grep \"$YITC_EXPECTED_SESSION_REF\" | tail -1 | python3 -c "
    "'import sys,json;print(json.load(sys.stdin)[\"data\"][\"pid\"])')`, then launch "
    f"`: > {land_pid}; YITC_LAND_HELD_TURN_PID=$WPID setsid bash -c 'echo $$ > {land_pid}; exec "
    "<the SAME `land --task T-XXXX` invocation you would have run in the foreground — the engine-CLI "
    f"form this preamble gives you> > {land_log} 2>&1' </dev/null &`, RESOLVE the handle from the "
    f"pidfile — `LAND_PID=$(timeout 30 bash -c 'until [ -s {land_pid} ]; do sleep 1; done; cat {land_pid}')` "
    "— never as `& LAND_PID=$!` (with job control ON that handle dies within a second while the land "
    "runs on, X-1011), and POLL in BOUNDED FOREGROUND windows, each re-invoked INLINE in the SAME turn — "
    "`timeout 300 bash -c 'until grep -qE \"^LAND: (OK|ABORT)\" "
    f"{land_log} || {{ [ -s {land_pid} ] && ! kill -0 \"$(cat {land_pid})\" 2>&-; }}; "
    "do sleep 10; done'` — until TERMINALITY: `^LAND: (OK|ABORT)` on stdout OR the land PROCESS "
    "EXITING (`kill -0 $LAND_PID` failing — poll it BESIDE the token grep, as this window does); a bare `yitc-v2:` line is "
    "progress, never a token. RUN EVERY `bash -c` SCRIPT OF THIS RECIPE EXACTLY AS PRINTED — "
    "single-quoted, every path written out, nothing from your own shell, no positional parameters: "
    "the harness REFUSES a non-literal `-c` script (X-1857). The claim FAILS CLOSED on a wrong pid "
    "(`main` untouched); an admitted detached land KILLS ITSELF, journaling `land_worker_liveness_lost`, "
    "if you yield and die (recover with `worktree recover-land`). So BACKGROUND-AND-YIELD STAYS "
    "FORBIDDEN — what may be detached is the OS PROCESS, never the TURN. Rule home SPEC-0180; recipe "
    "home `patterns/background-session-dispatch.md §Long-command-exceeds-tool-timeout`. This covers "
    "ONLY the ARITHMETIC block (the CALL is too short); it is NOT a licence to force a BLOCKED land "
    "through, and the EXCEPTION below is unchanged. "
) if not controller_lands else _CONTROLLER_LANDS_HEAD
    tail = (
    "EXCEPTION (SPEC-0103) — when BLOCKED by a cause OUTSIDE your task's declared scope (an "
    "out-of-scope file, an environmental fault, or a repeated land/audit ABORT on the SAME cause), "
    "STOP and ESCALATE to the controller (`blocked-on-land <task> <reason>`, worktree intact) — NEVER "
    "edit an out-of-scope file or weaken/skip/delete a gate, test, or guard to force the land; that "
    "escalation is the CORRECT outcome, NOT abandonment. SUBCLASS (T-9583, SPEC-0103 §3a): on an "
    "AUDITOR-OUTAGE ABORT (the auditor could not RUN — not a findings-bearing RED) `audit pre|post` "
    "AUTO-PARKS this worker (`worktree park`, task stays `ready`, re-dispatchable) ONLY when your worktree is EMPTY OF "
    "WORK; with any commit above main or uncommitted path beyond `events.jsonl` + your card it does "
    "NOT fire and you take the worktree-intact escalation above instead (never hand-park a build). "
    "PAUSE-SHAPE FORK (SPEC-0103 §5): a BOOKKEEPING-ONLY pause commits+lands its record (re-enter via "
    "`worktree new --task`); a WORK-CARRYING pause keeps the worktree INTACT (re-enter via `task "
    "resume`). "
    "AUDIT-LOOP CEILING (SPEC-0204 rule 6 / T-12679): at the ceiling `audit pre|post` ITSELF emits "
    "the bg_dispatch_halted(blocked_on_land) row carrying residual_fingerprints; you halt with "
    "`task pause <task> --reason audit-ceiling` INSIDE the worktree; the Controller records `audit "
    "decide` per fingerprint and you resume with `task resume` + `audit pre|post --on-decisions`. At "
    "audit-POST, for a residual you fix in scope: `task commit --fix-red` FIRST and name its sha in "
    "the pause next_action. TERMINAL RED (SPEC-0204 rules 3-4 / T-13537): when the `--on-decisions` "
    "pass (or its one absorption re-audit) is RED, the stage is OVER — the verb's halt row names the "
    "terminal exits (`task update --status parked|wont-do`, `worktree park`, or a new card) and NO "
    "residual_fingerprints: NO `audit decide`, NO further pass. You still halt with `task pause <task> --reason audit-ceiling`, and those "
    "exits are the owner's. Do NOT run `blocked-on-land` for a ceiling reached before your first "
    "commit (the claim is uncommitted, so the verb REFUSES — T-10894); and NEVER `task refuse` a "
    "claimed card (that is the UNCLAIMED pre-claim exit, SPEC-0133)."
)
    # T-12431 — the SUITE's over-cap paragraph sits between the two, so BOTH regimes carry it: the
    # worker-lands head after its OVER-CAP EXIT land clause, the controller-lands head after its
    # STOP-after-close clause. ONE string, exactly as the SPEC-0103 tail below is one string.
    return head + _build_over_cap_test_rule(test_log, test_pid) + tail


# T-12303 — the CONTROLLER-LANDS regime's HEAD (the only half that differs; the tail above is shared).
# Rendered by `_build_sync_to_land_rule(controller_lands=True)` and delivered as
# `DISPATCH_STOP_LAND_CONTRACT`, the ONE template the composed brief preamble's stop/land paragraph
# comes from. It carries NO detached-land recipe: a worker that never lands cannot meet the SPEC-0180
# per-call cap ON a land, so handing it that recipe would be an instruction it can only misapply.
_CONTROLLER_LANDS_HEAD = (
    "DO NOT LAND YOURSELF. Run EVERY stage — the test suite, the external audits, the commit, the "
    "close — synchronously in the FOREGROUND, blocking, inline in your turn; run long commands "
    "(tests, audits) synchronously/blocking and NEVER background-and-await an async notification. "
    "Then STOP: after `task close <task>` report the CLOSING SHA + the worktree PATH and yield. The "
    "CONTROLLER lands from main — you do NOT invoke `land`, and the `LAND: OK <sha>` token is the "
    "Controller's land's, never yours to produce. NEVER hand-emit a `land_completed` event and never "
    "weaken/skip/delete a gate, test, assertion or guard to make a stage pass; the verb owns every "
    "emit. Yielding BEFORE `task close` is ABANDONMENT (the controller force-recovers the task and "
    "your build is wasted, T-0622) — yielding AFTER it, with the sha reported, is the CONTRACTED "
    "completion. Rule home: SPEC-0103. "
)


# The ENGINE-self render (the builder at its default: THIS checkout's repo-scoped log path). Kept
# under the historical name because it IS the single source both delivery points consume — the
# preamble builder below AND cmd_stage's just-in-time stage-entry reminder (T-0687).
SYNC_TO_LAND_RULE = _build_sync_to_land_rule()

# The long-command + land lifecycle stages where a DISPATCHED worker is re-reminded of the
# synchronous-to-LAND rule just-in-time at stage-entry (T-0687). The point-of-temptation set: the
# stages that run a long blocking command (Tests / Audit-pre / Audit-post) or drive toward the LAND
# token (Commit / Closure). Interactive sessions (no worker marker) never see it (cmd_stage guard).
_SYNC_REMINDER_STAGES = frozenset({"Tests", "Audit-pre", "Audit-post", "Commit", "Closure"})

# T-10710 (X-0561) — the IN-WORKTREE `session start` cue the preamble hands the worker (point 3,
# SEED-READ RECEIPTS). The ENGINE's own dispatch keeps the BARE form; a CONSUMER target has no local
# `bin/yitc-v2` at all (AGENTS §Consumer (-C) note), so a bare cue is REFUSED and every dispatched
# consumer worker burns one wasted verb call (<project>, X-0561 — an instance of the dominant
# `-C` delivery-incompleteness class, lessons/kernel-consumer-boundary-evidence.md). The consumer form
# MIRRORS the engine-resolved `-C` rendering `session start`'s own `--help` rescan line already emits
# (bin/lib/session.py, T-9469) — same shape, one more surface; NOT a second detection mechanism.
# Both forms carry their OWN backticks (the template interpolates the cue bare), so the consumer form
# can gloss itself after the closing backtick without the template double-quoting it.
_WORKER_SESSION_START_BARE = "`bin/yitc-v2 session start --type build`"

# T-10717 — the SAME seam, extended to the REST of the preamble's engine invocations (the residue
# T-10710 explicitly left out of its declared scope: the claim `worktree new --task`, `land`,
# `task refuse`, the two SPEC rule-home `graph query` fetches, and the header's own `dispatch`
# provenance). Each was BARE, so a `-C` consumer worker following the preamble is REFUSED mid-flight
# — the claim and the land are load-bearing (it cannot start or finish). Same X-0561 class, same
# fix shape: ONE pure prefix resolver, interpolated everywhere, defaulting to the historical bare form.
_WORKER_INVOKE_BARE = "bin/yitc-v2"


def _worker_invocation_prefix(*, is_consumer: bool, engine_root, repo_root) -> str:
    """The engine-CLI invocation PREFIX a dispatch TARGET's worker must use (PURE — f(bool, 2 paths)).

    Engine-self → the bare `bin/yitc-v2` (unchanged). Consumer → the engine-resolved
    `<engine>/bin/yitc-v2 -C <consumer-root>` form — the SAME rendering `session start`'s own
    `--help` rescan line already emits for a consumer (bin/lib/session.py, T-9469); not a second
    detection mechanism. UNLIKE the session-start cue (whose target is the not-yet-created
    `<worktree>`), these verbs run against the consumer's MAIN checkout — the claim, `land` (which
    runs FROM main by contract) and the worktree-free `task refuse` / `graph query` — so the
    CONCRETE repo root is interpolated, not a placeholder."""
    if not is_consumer:
        return _WORKER_INVOKE_BARE
    return f"{engine_root}/bin/yitc-v2 -C {repo_root}"


def _worker_session_start_cue(*, is_consumer: bool, engine_root) -> str:
    """The in-worktree `session start` invocation form for a dispatch TARGET (PURE — f(bool, path)).

    Engine-self → the bare form (unchanged). Consumer → the engine-resolved `-C` form. The worktree
    path stays the literal PLACEHOLDER `<worktree>` because the worker CREATES its worktree only
    AFTER reading this preamble — no concrete path exists at compose time — and the very sentence
    that carries this cue already tells the worker to `cd` to the `<worktree>` the claim printed, so
    the placeholder resolves for the reader at the moment of use."""
    if not is_consumer:
        return _WORKER_SESSION_START_BARE
    return (f"`{engine_root}/bin/yitc-v2 -C <worktree> session start --type build` "
            "(a CONSUMER has NO local `bin/yitc-v2` — invoke the ENGINE CLI with `-C` pointed at the "
            "worktree you just cd-ed into; a bare `bin/yitc-v2 …` there is REFUSED, X-0561)")


# T-12373 — the LAND REGIME constants, named once so the launch row, the reminder resolver and the
# `--controller-lands` help text cannot spell them three ways. `worker` is the CANON (CHARTER §6, owner
# ruling «оставляем канон» events.jsonl#ts=2026-09-11T03:38:42Z): the dispatched worker lands itself.
# T-12351 — the VALUES now live at the journal leaf (`journal.LAND_REGIME_*`), because the
# dispatch-status classifier there keys on the same launch-row key; the NAMES stay bound here so every
# existing reader (`cli` re-exports, the launcher, the reminder resolver, the tests) is untouched.
LAND_REGIME_WORKER = journal.LAND_REGIME_WORKER
LAND_REGIME_CONTROLLER = journal.LAND_REGIME_CONTROLLER


def _build_point1(sync_rule: str, *, controller_lands: bool = False) -> str:
    """Point 1 of the standing worker preamble, rendered for ONE land REGIME (PURE).

    T-12373 — the WORKER-LANDS wording used to live OUTSIDE the rule, as a LEAD-IN and an ff-race
    TRAILER hard-coded around the `{sync_rule}` interpolation in `_build_worker_preamble`. So passing
    the CONTROLLER-LANDS rule through that same slot produced a brief whose point 1 still said «reach
    `LAND: OK`» while the composed STOP / LAND CONTRACT block said «DO NOT LAND YOURSELF» — both
    regimes, in one brief, every time (measured on T-12319 / T-12337, then on every dispatch of the
    T-12344/T-12349 batch, each of whose Controller deltas had to spend a paragraph saying which voice
    wins). This helper is where that wording now lives, so it can vary WITH the regime.

    `controller_lands=False` reproduces TODAY'S BYTES EXACTLY, so `DISPATCH_WORKER_PREAMBLE` (the
    builder at its defaults) is byte-identical and every existing reader sees the text it always saw.

    `controller_lands=True` renders a NEUTRAL synchronous-to-CLOSE head that POINTS at the STOP / LAND
    CONTRACT block and DOES NOT INTERPOLATE `sync_rule` AT ALL. That omission is the whole design
    (owner_directive events.jsonl#ts=2026-09-11T04:46:38Z — ONE home for the controller-lands regime):
    the composed block is that home, and a point 1 that ALSO stated the regime would render «DO NOT
    LAND YOURSELF» a SECOND time — the residual fp1:07ecc4bac144bfad that killed T-12349's plan. Under
    this branch the brief is also free of the lead-in phrase «all the way to the `LAND: OK <sha>`
    token» and of the ff-race trailer, neither of which a worker that never lands can act on."""
    if controller_lands:
        return """\
1. SYNCHRONOUS-TO-CLOSE. Run EVERY step — the test suite, the external audits, the commit, AND the
   close — synchronously in the FOREGROUND, blocking, inline in your turn, all the way to the CLOSING
   SHA. The land contract for this dispatch is the STOP / LAND CONTRACT block in the composed preamble
   below — read it there; this point does not restate it."""
    return f"""\
1. SYNCHRONOUS-TO-LAND. Run EVERY step — the test suite, external audits, commit, close, AND land —
   synchronously in the FOREGROUND, blocking, inline in your turn, all the way to the `LAND: OK <sha>`
   token. {sync_rule} `land` may need retries under concurrent
   landing (ff-race): re-invoke it inline until `LAND: OK`, never yielding between attempts."""


# T-12400: the INVARIANT first-line PREFIX of the standing worker preamble — the SINGLE carrier of
# "this user turn is a dispatch preamble, not an owner directive". The builder below INTERPOLATES it
# (so the preamble bytes and this marker cannot drift apart), and `journal._classify_cc_entry` reads
# it back — by a LAZY import, since journal is the LOWER leaf this module imports (leaf-order, the
# `worktree_lifecycle`/`task` idiom). It stops at `(standing preamble` because the remainder of that
# line interpolates the per-target `invoke` prefix (bare vs `-C <path>` vs an absolute engine path),
# which VARIES per dispatch and so cannot be part of a stable marker.
#
# WHY it exists (measured): `_classify_cc_entry` labels every plain-STRING `user` transcript entry an
# `owner_directive`, and a dispatched worker's prompt arrives as exactly that — so 209 preamble rows
# in 3 days were journaled onto the OWNER channel, which AGENTS §Recovery tells every session to grep
# FIRST for the owner's original wording (<project> X-1364 / <project> X-1345).
DISPATCH_PREAMBLE_MARKER = "=== DISPATCHED WORKER EXECUTION DISCIPLINE (standing preamble"


def _build_worker_preamble(session_start_cue: str = _WORKER_SESSION_START_BARE,
                           invoke: str = _WORKER_INVOKE_BARE,
                           kernel_flag: str = "",
                           sync_rule: str = "",
                           controller_lands: bool = False) -> str:
    """Build the standing worker-execution-discipline preamble for ONE dispatch target (PURE).

    The body is the historical DISPATCH_WORKER_PREAMBLE text, byte-identical except that the point-3
    in-worktree `session start` invocation is the passed-in CUE (T-10710) and every OTHER engine
    invocation carries the passed-in PREFIX + `graph query` flag (T-10717). `kernel_flag` is `""` for
    the engine and `"--kernel "` for a consumer: under `-C` a bare `graph query SPEC-XXXX` resolves
    the CONSUMER's spec at that id (consumer-own wins), so the KERNEL rule-homes the preamble points
    at must be forced with `--kernel` (AGENTS §Kernel-prefixed retrieval under -C / SPEC-0092). Every
    default reproduces today's bytes, so the module-level DISPATCH_WORKER_PREAMBLE below (this builder
    at its defaults) is the ENGINE form and every existing reader sees exactly the text it always saw.

    T-11294 — `sync_rule` is the TARGET-RENDERED synchronous-to-LAND sentence (its detached-land log
    path is scoped to the target repo, so two repos sharing a host cannot share one log file). Omitted
    → the module-level ENGINE render, so the default bytes are unchanged.

    T-12373 — `controller_lands` selects the LAND REGIME point 1 renders for, through the PURE
    `_build_point1` above. Under the default (False) this reproduces today's point-1 bytes exactly;
    under True point 1 renders the neutral synchronous-to-CLOSE head and `sync_rule` is not
    interpolated at all, because the composed STOP / LAND CONTRACT block is the ONE home of that
    regime's text."""
    sync_rule = sync_rule or SYNC_TO_LAND_RULE
    return f"""\
{DISPATCH_PREAMBLE_MARKER} — injected by `{invoke} dispatch`) ===
You are a headless one-shot background Build worker (a separate provider sub-session). Your turn IS
your life: when you yield the turn, your process EXITS. Therefore:

0. YOUR HANDBOOK SEED IS THE WORKER SEED — AND IT IS A CHAIN OF PARTS, NOT ONE FILE. Your startup read-set
   is the generated `core`+`worker` seed `graph/worker-seed.md` **plus EVERY continuation part it chains to**
   (`graph/worker-seed-2.md`, `-3.md`, … — part 1 lists the whole chain, and each part names its next hop;
   they are size-bounded so each loads in ONE bounded read, SPEC-0007 §5c + SPEC-0120 §3 + SPEC-0127). Read
   THE WHOLE CHAIN, NOT the full CHARTER..GRAPH files, and NOT part 1 alone — stopping at part 1 silently
   starves you of most of the protocol. THEN read `graph/floor-trigger-map.md` — also part of your
   startup read, always-loaded beside every audience's seed (AGENTS §Bootstrap-floor): it names the spec
   to fetch BEFORE a gated action (e.g. before-authoring-interaction → SPEC-0100). The `controller`-only sections (orchestrate/dispatch, the queue
   picker, the plan-lifecycle FSM, controller startup echoes, owner-register) are not in a Worker's bootstrap.
   The vendor auto-inject floors ONLY a MINIMAL inline anti-Forgetting floor on your `worktree new`+`cd`
   (NOT the whole seed anymore — T-10069 / SPEC-0127 §4a), so READING the worker-seed chain yourself is your
   real startup seed; the launcher already pre-recorded your `seed_read` receipt (T-10083), and the
   `_require_seed_read` gate holds the floor. Re-read the WHOLE chain + the trigger-map after any `/compact`.

{_build_point1(sync_rule, controller_lands=controller_lands)}

2. SUBAGENT ROLE. You MAY spawn read-only / ephemeral subagents for SEARCH / ANALYSIS only — await them
   INLINE in the same pass, then continue. They MUST NOT claim a task, edit source, commit, or land. A
   Build-worker ROLE (claim / edit / commit / land) is NEVER an in-process subagent — if more build work
   is needed, file tasks and dispatch separate sub-sessions.

3. LIFECYCLE ADHERENCE — run the FULL 9-stage Build lifecycle through a governed `land`; never hand-roll it:
   - SEED-READ RECEIPTS: the launcher has ALREADY recorded your `session_started` + `seed_read` +
     verb-inventory receipts on the MAIN journal for your session (governed — T-10083 / SPEC-0050 §8),
     so your first claim `worktree new` passes the anti-Forgetting read-gates WITHOUT you running
     `session start` first (the seed only auto-injects on `cd` INTO the worktree, which `worktree new`
     gates BEFORE). AFTER `worktree new` prints its `cd <worktree>` cue and you cd in, run
     {session_start_cue} ONCE to re-anchor THIS checkout's journal — your worktree
     stage-verbs (`task analyze`/`audit`/`task commit`/`task close`) need it (the per-worktree norm,
     SPEC-0050 §2). `land` runs FROM main and needs no worktree re-run.
   - CLAIM via `{invoke} worktree new --task T-XXXX` — that worktree creation IS the claim (D-0037
     option B). Do NOT use `task pick`: it is a READ-ONLY inspector and does NOT claim (the T-0124 trap —
     the X-0044 incident worker called it, never claimed, and left the task `ready`).
   - WORKTREE-BEFORE-WRITE: every source/artifact edit happens INSIDE that worktree, never directly on the
     main checkout (journal `event` appends are the only no-worktree exception, D-0049).
   - MANDATORY AUDIT: run the external `audit pre` (Stage 4) AND `audit post` (Stage 8) — do NOT skip them
     because the change "looks correct" (X-0044 shipped correct-but-UNAUDITED code). At the audit-loop
     CEILING the `audit post` verb ITSELF auto-drives the convergence consult (T-9712, SPEC-0036) and emits
     any needed `bg_dispatch_halted` — so FOLLOW the verb's exit (GREEN → proceed; nonzero + bg_dispatch_halted
     → escalate per point 4), and do NOT hand-emit `bg_dispatch_halted` out-of-band before letting `audit post`
     run to its own exit. PREVIEW FIRST, and do NOT go shopping for a deferred-adoption overlay flag:
     run `{invoke} audit pre|post --task <id> --preview` BEFORE each auditor pass, read the packet
     readiness block and fix what it names (report-only, T-11977) — a spent auditor pass is the
     expensive thing, reading the block is free. Before an `--on-decisions` pass the preview is
     `--preview` ALONE: the two flags are not combinable (the verb refuses the pair), so preview
     first, then run the pass with `--on-decisions`. The verb DERIVES the deferred-adoption overlay from
     your CARD's own declaration (T-11978); pass an overlay flag ONLY to OVERRIDE what it derived, never
     to pick one yourself.
   - REAL LAND: integrate via `{invoke} land` and reach the `LAND: OK <sha>` token — NEVER hand-emit a
     `land_completed` event to fake completion (the verb owns that emit; a hand-emitted one is a bypass).

4. SCOPE BOUNDARY — ESCALATE, NEVER WORK AROUND (SPEC-0103). Do NOT edit a file OUTSIDE your task's
   declared scope, and NEVER weaken / skip / delete a gate, test, assertion, or guard (no
   `land --no-tests`, no hand-emitted `land_completed`), to force a blocked land or audit through. When
   blocked by an out-of-scope OR environmental cause (incl. a repeated land/audit ABORT on the SAME
   cause) — STOP and ESCALATE to the controller (`blocked-on-land <task> <reason>`, worktree intact);
   that escalation is the CORRECT outcome, NOT abandonment (the point-1 ABANDONMENT warning is about
   backgrounding+yielding, it does NOT override this). Rule home: SPEC-0103
   (`{invoke} graph query {kernel_flag}SPEC-0103`). CLASSIFY every blocked verify gate per SPEC-0191
   (block-classification + push-vs-stop): never clear a block SILENTLY; a Worker governed-self-clears
   ONLY a provable STALE-BY-DESIGN block (with a recorded reason), fixes a TRUE SIGNAL only in-scope,
   and HALTS on a deliberate guard, an unproven flake, or ANY uncertain block — default under
   uncertainty = STOP (`{invoke} graph query {kernel_flag}SPEC-0191`). Before a block reaches the AUTHORITY,
   climb the SPEC-0191 §5 THREE-RUNG RESOLUTION LADDER: rung-1 MECHANICAL self-evidence (inspect the diff +
   the named failing assertion for a no-new-decision staleness backed by a pre-existing audited
   artifact — record a compact evidence tuple; mandatory first, most blocks resolve here); rung-2 an
   external-auditor ADVERSARIAL consult (≥2 framed options, the auditor names survivors — never a
   may-I approval) if rung-1 fails; rung-3 the AUTHORITY for a genuine dead-end. That gate is kept
   UNCONDITIONALLY against any auditor verdict for an AUTHORITY-class cause
   (data deletion / prod exposure / scope change / money / secrets / compliance / irreversible-external
   / public commitments) — no auditor verdict clears one. WHO the authority is: the OWNER, or a holder of the
   `decide-authority` right on THAT project (SPEC-0191 §5a / SPEC-0169 rule 2) — so an authority cause
   is not automatically the owner's, and it is never yours by default: a missing, unreadable or
   non-matching grant REFUSES, and holding the right makes you the AUTHORITY for the cause while
   conferring NO execution capability of its own.

5. PRE-CLAIM PREMISE-FALSE EXIT — REFUSE, don't just capture-and-vanish (T-10291 / SPEC-0133). If at
   pre-claim analysis (BEFORE `worktree new`) you find the task's PREMISE is false — an unmet
   precondition, an out-of-scope cause, or a self-unsatisfiable card — then capturing the
   `deviation_captured` is NOT the exit. The GOVERNED exit is `{invoke} task refuse T-XXXX --reason
   <why>` (worktree-free, D-0049 journal append; the task stays `ready` on main, cleanly re-dispatchable
   once the blocker clears). This is the verb that COVERS the pre-claim refusal (verb-execution discipline
   — using the covering verb is the only obligatory path), so a bare capture-then-exit is a MISS: it leaves
   the fleet-verdict reading `launch-stall` («never came up — re-dispatch») and the controller loops the
   refusal, the exact 2/2 miss on 2026-07-10 (T-10367 / T-10368). `task refuse` records
   bg_dispatch_halted(kind=refused) so fleet-verdict reads `refused(pre-claim)` / needs-decision instead.
   (This is the PRE-claim sibling of point 4's post-claim `blocked-on-land` escalation — same never-vanish-
   silently discipline, applied before the claim.)

6. RE-DISPATCH BRIEF IS JOURNAL-VERIFIED — never a controller-memory premise (T-10578 / X-0429 / SPEC-0103).
   When you are RE-dispatched onto a task with a prior lifecycle, TRUST THE JOURNAL over the brief prose: a
   `JOURNAL-VERIFIED PRIOR STATE` block (last audit-pre/post verdict, consult verdict, any live task_paused
   reason for this id) is appended to your brief straight from the journal. If a verdict there is RED or a
   pause is LIVE, this is NOT a clean post-land orphan awaiting a mechanical audit-post+close+land tail —
   re-derive state from the journal BEFORE acting, and NEVER close an unmet AC or amend a scope decision on
   your own (SPEC-0191 §5 keeps that authority gate unconditional against any auditor verdict, and §5a
names who may occupy it — being re-dispatched is not being granted the right). A stale-pause advisory means later events
   contradict the pause's next_action — the pause facts may be out of date.

7. PRE-FLIGHT YOUR LAND — run `worktree sync` BEFORE your first `land` (T-11313). Your branch's land
   can be refused for two reasons that are BOTH computable OFF the queue: a merge conflict with `main`,
   and audit-currency. `land` computes them only at the FRONT of the queue — after your branch has
   queued, waited for a SPEC-0132 verify-admission slot and taken a reservation — so a worker that goes
   straight to `land` pays a full wait to be told something it could have known immediately. Instead,
   once your work is committed and BEFORE the first `land`, run
   `{invoke} worktree sync --task T-XXXX` (`--work <slug>` for a work batch). It merges `main` into
   your worktree IN PLACE and reports the COMPLETE blocker set: no reservation, no verify slot, no
   advance of `main`, worktree intact. ACT on whatever it reports while still OFF the queue — resolve
   the conflict, take the re-audit — and only THEN call `land`. Re-running it is always safe (already
   current = a clean no-op, never an error). READ BOTH PHASES, in the order the verb prints them: it
   reports CONFLICTS first and CURRENCY second, because currency is judgeable only AFTER the merge —
   so a clean conflict phase is NOT "all clear", and the currency line prints even on the
   already-current no-op path. HONEST BOUND, so you do not over-trust a clean report: this removes the
   SECOND wait — discovering at the front of the queue a blocker that was computable off-queue — but it
   does NOT remove the race. While your branch re-audits, `main` keeps moving, and a FRESH conflict
   raised by the land's own merge makes the branch dirty again (a CLEAN re-merge does not, so a
   pre-flighted land is still the cheaper path). That residual is T-11333's and T-11332's, not yours.
   Rule home: the `worktree sync` contract, `bin/lib/worktree.py#cmd_worktree_sync` (T-11313) — this
   point carries the ORDERING only, never a second copy of the verb's contract.

8. EVERY READ YOU MAKE ABOUT YOUR OWN RUN IS SCOPED TO **THIS** RUN (T-12010) — a log, token or
   process that is not provably YOUR run's is a FOREIGN or PAST run, read as a false GREEN:
   - **SCRATCH LOGS — NEVER a bare `/tmp/<name>.log`** (host-global: the redirect is denied, the verb
     never runs, a foreign verdict is read — T-11991, T-11981, T-11978, T-11647). Use YOUR SESSION SCRATCH ROOT `$YITC_SCRATCH_DIR`
     (created by dispatch, T-13203) — e.g. `$YITC_SCRATCH_DIR/T-XXXX-<job>.log` — or your worktree's
     `.yitc/` after `mkdir -p .yitc` (T-13536); a name outside both carries `<sessionref>-<task>`
     (`$YITC_EXPECTED_SESSION_REF`). Clones and probes go under the scratch root too, and
     {SCRATCH_CLONE_RULE}. Your land/park REMOVES that root,
     and `worktree sweep` reclaims a dead session's. So NEVER redirect a `land`'s output into the
     scratch root: a successful land removes it BEFORE printing `LAND: OK` —
     use the engine-named land log below (T-13639). The engine's detached land/test log+pid
     (`/tmp/yitc-land-u<euid>-<repo>-<key>-<task>.log`, T-11294) stay OUTSIDE it by design.
   - **A RE-LAND POLL READS THIS ATTEMPT'S BYTES ONLY.** The start-detach land log
     (`.yitc/land-logs/<branch>.log`) is APPEND-ONLY, so a whole-file `grep` re-reads a previous
     attempt's token — USE THE ANCHORED poll the engine prints (`tail -c +N <log> | grep -qE ...`);
     your own redirects use `>`, never `>>`.
   - **A LIVENESS POLL USES THE CHILD PID** (`kill -0 <pid>`), never `pgrep -f` with your own argv's
     text — it matches itself and reads finished work as RUNNING (T-11925, T-10557); with no pid, ground-truth off the journal.
   Rule home: `patterns/background-session-dispatch.md §Long-command-exceeds-tool-timeout`.

9. STAGE AND CONTRACT OUTPUT IS A DELIVERY — IT MUST REACH YOU WHOLE (T-13392). What `{invoke} stage
   <NAME>` and `{invoke} graph query {kernel_flag}SPEC-XXXX` print IS the read the gated verbs check for, so:
   - **NEVER send it to the null device.** A `stage` whose stdout is `/dev/null` exits 6, renders
     nothing and credits NOTHING (T-13028); a `graph query` whose stdout went nowhere is recorded
     undelivered and grants no pass (T-11411). The next gated verb (`audit pre|post`, `task commit`,
     `task close`, `task file`) then REFUSES `contracts_unfetched` — measured 2026-10-01..02: 346 of
     642 stage calls exited 6, followed by 261 such refusals.
   - **NEVER truncate it through `head` / `tail`** (or any filter that drops lines). When it is long,
     redirect it to a scratch file (point 8) and READ THAT FILE IN FULL before acting.
   - **On a read-gate refusal, read its FULL stdout AND stderr BEFORE any retry.** It names the exact
     contract(s) missing and the `graph query` command(s) that deliver them, and says when a fetch was
     recorded but not delivered. Run those commands with stdout attached and read the output, THEN
     re-invoke. NEVER re-run the same verb unchanged on the same refusal — it refuses identically
     (measured: one worker re-ran `audit post` 3x with no delivered fetch between).
   Rule home: the read-gate delivery contract, SPEC-0050 (`{invoke} graph query {kernel_flag}SPEC-0050`).

Full rule home: patterns/background-session-monitoring.md §Synchronous-to-LAND + patterns/background-session-operation.md §Dispatch mode;
the scope-boundary discipline (point 4) is homed single-SoT in SPEC-0103; the block-classification +
push-vs-stop ladder (which block a worker may self-clear vs must escalate) in SPEC-0191; the pre-claim
premise-false refuse exit (point 5) in T-10291 / SPEC-0133 (`refused(pre-claim)`); the run-scoped
self-read rule (point 8) in patterns/background-session-dispatch.md §Long-command-exceeds-tool-timeout (T-12010);
the delivery rule (point 9) in SPEC-0050 (T-11411 / T-13028).
=== END PREAMBLE ===
"""


def _with_own_floor_map(preamble: str, own_map) -> str:
    """T-13757 (PURE) — append to point 0 of a CONSUMER worker preamble the consumer's OWN floor
    trigger-map (`session.consumer_own_floor_map`), so a dispatched Worker reads its project's own
    before-* rows beside the engine map at start and after a /compact. None → unchanged."""
    cut = preamble.find("\n\n1. ")
    if own_map is None or cut == -1:
        return preamble
    return (preamble[:cut]
            + f"\n   CONSUMER: this project's OWN floor-trigger map `{own_map}` carries its own specs'"
            "\n   before-* rows — read it beside the engine's at start and again after any `/compact`."
            + preamble[cut:])


# The ENGINE-self preamble (the builder at its bare default). Kept as a module-level constant because
# it IS the engine's own dispatch text and the whole existing reader set (cmd_stage's shared rule, the
# rules-corpus extractor, the preamble tripwire suites) consumes this name. A CONSUMER dispatch renders
# its own via `_build_worker_preamble(_worker_session_start_cue(...))` in cmd_dispatch (T-10710).
DISPATCH_WORKER_PREAMBLE = _build_worker_preamble()


# ── T-10704 (SPEC-0167) — MIGRATION-WINDOW PRODUCT-CARD OWNER-GATE ────────────────────────────────
# While a migration window is open, `dispatch` of a card that touches PRODUCT code REFUSES unless the
# owner explicitly authorized THAT card (`product_dispatch_owner_ack:`). Out of a window, or for a
# governance-only card, this is a byte-identical no-op. This REUSES the cross-request kind:task
# owner-gate SHAPE (a fail-closed refusal that NAMES the exact token to add) — no new gate cascade, no
# new window marker/ledger (CHARTER §P1: the window IS the plan's own FSM). Rationale: <project>
# 2026-07-13 — two imported PRODUCT cards were dispatched inside a migration/revizia context and the
# CSRF one took prod auth down; "a migration does not touch product code" was encoded nowhere. Origin
# cross X-0372; full design plan `migration-import-safety-provenance-marker-premise-`.
#
# WINDOW CARRIER (SETTLED by SPEC-0167 — NOT reopened here). The migration window is an active
# brownfield-onboarding plan in `executing` of the `real-project-integration-onto-v2-phased-migration-`
# class (runbook Branch B) — mechanically: a plan whose frontmatter `id` starts with this class prefix
# and whose `status` is `executing`. NOT "any executing plan". The SPEC-0130 quiesce-state option is
# DEFERRED to followup fu_5713357f3a9a (out of scope). The plan scan itself is HOST-side (it needs the
# repo's plans/ dir + a tolerant frontmatter read) and is injected as `_migration_window_open`; the
# classification below is PURE so it is unit-testable in isolation (the identity-agnostic kernel leaf).
MIGRATION_WINDOW_PLAN_CLASS = "real-project-integration-onto-v2-phased-migration-"

# The GOVERNANCE/DOCS path-set (SPEC-0167 §Internal — the mechanical product-touch test). A path INSIDE
# this set is governance/docs (never product); every OTHER path is product-touching. Fail-closed: "when
# in doubt → product-touching". Directory-prefix members:
_GOVERNANCE_DOCS_DIR_PREFIXES = ("tasks/", "specs/", "decisions/", "plans/",
                                 "patterns/", "lessons/", "scenarios/", "graph/")


def _touch_unit_path(entry) -> str:
    """Normalize ONE `expected_touch` entry to its FILE part — the shared touch-unit vocabulary.

    Strips a `#symbol` anchor (the file is what two cards collide ON; the symbol is a strength signal
    carried separately), a leading `./`, and surrounding whitespace. Returns "" for a degenerate entry
    — each caller decides what an unreadable unit means for IT (the product gate reads "" as in-doubt
    → product; the overlap report drops it rather than inventing a path). PURE f(str) -> str.

    EXTRACTED by T-10872 from `_touch_path_is_product`, where this was inline. Both the SPEC-0167
    product gate and the T-10872 overlap report normalize through here, so the two readers of
    `expected_touch` in this module can never disagree about what a path IS."""
    p = str(entry).split("#", 1)[0].strip()
    if p.startswith("./"):
        p = p[2:]
    return p


def _touch_path_is_union_merged(path) -> bool:
    """Is this touch-unit a UNION-MERGED, append-only path — one two cards can BOTH write without ever
    conflicting at land? Today that is exactly the journal, `events.jsonl` (<project> X-0887: it is
    append-only and union-merged by `land`, so overlap there is safe BY CONSTRUCTION).

    EXTRACTED by T-11142 from `_touch_path_is_product`, where this arm was inline. It is now THE single
    carrier of that path-set: the SPEC-0167 product gate and the T-10872 overlap fold both resolve the
    exemption from HERE, so a second list cannot drift away from the first.

    Deliberately NARROWER than `_touch_path_is_product`'s governance/docs set: a `*.md` or a `specs/`
    file is governance (exempt from the product gate) but is NOT union-merged — two cards editing one
    spec DO conflict at land, so the overlap advisory must keep reporting them. PURE f(str) -> bool."""
    p = _touch_unit_path(path)
    return bool(p) and (p == "events.jsonl" or p.endswith("/events.jsonl"))


def _touch_path_is_product(path) -> bool:
    """SPEC-0167 product-touch test (mechanical, fail-closed) — is this touch-unit a PRODUCT path?

    A path is governance/docs (→ returns False) iff it is inside the governance/docs path-set:
    the `_GOVERNANCE_DOCS_DIR_PREFIXES` directories, any `*.md` file, or `events.jsonl`. EVERY other
    path is product-touching (→ True). A `#symbol` anchor is stripped first (the classification is on
    the FILE part, mirroring `_card_touch_tokens`) — via the shared `_touch_unit_path`. An
    empty/degenerate token is "in doubt" → product (True). PURE f(str)."""
    p = _touch_unit_path(path)
    if not p:
        return True                                  # in doubt → product
    if _touch_path_is_union_merged(p):               # the journal — single carrier, T-11142
        return False
    if p.endswith(".md"):
        return False
    if any(p.startswith(pref) for pref in _GOVERNANCE_DOCS_DIR_PREFIXES):
        return False
    return True


def _card_touches_product(expected_touch) -> bool:
    """Is a card product-touching (SPEC-0167)? True iff its `expected_touch` reaches any product path,
    OR it declares NO forecast at all (fail-closed "when in doubt" — an unforecast card cannot be
    proven governance-only, so a migration window treats it as product-touching). A card whose forecast
    is WHOLLY inside the governance/docs set is governance-only (→ False, never blocked). PURE."""
    et = [str(e).strip() for e in (expected_touch or []) if str(e).strip()]
    if not et:
        return True                                  # no forecast → in doubt → product
    return any(_touch_path_is_product(e) for e in et)


def _product_gate_refusals(cards) -> list:
    """Given an ORDERED list of `(task_id, card_dict_or_None)`, return the task ids a migration window
    must REFUSE to dispatch: product-touching AND carrying no `product_dispatch_owner_ack`. An
    unreadable/absent card (None) fails closed → product-touching, no ack → refused. PURE."""
    out = []
    for tid, card in cards:
        card = card if isinstance(card, dict) else {}
        if not _card_touches_product(card.get("expected_touch")):
            continue
        # FAIL-CLOSED: a valid owner-ack is a NON-EMPTY STRING ref ONLY. Anything else — absent (None),
        # empty/blank, OR a non-string YAML scalar (`false` / `0` / `[]` / `{}`) — is NOT an
        # authorization and REFUSES (audit-post RED: a non-string truthy value must never bypass the
        # owner-token requirement).
        ack = card.get("product_dispatch_owner_ack")
        if not (isinstance(ack, str) and ack.strip()):
            out.append(tid)
    return out


def _product_gate_refusal_message(refused: "list") -> str:
    """The fail-closed refusal text (SPEC-0167 — "report-with-the-fix": name the exact token to add).
    PURE so the differential test can assert the token is present."""
    return (
        "dispatch: a MIGRATION WINDOW is open — a "
        f"'{MIGRATION_WINDOW_PLAN_CLASS}' class plan is `executing` (SPEC-0167). While a migration "
        "window is open, a PRODUCT-touching card cannot be dispatched without the owner's explicit "
        f"go-ahead. REFUSED (product-touch, no owner-ack): {', '.join(refused)}.\n"
        "Add the owner-ack token to each refused card's YAML (the exact token):\n"
        "    product_dispatch_owner_ack: <owner-authorization-ref>\n"
        "via the governed field-edit route, e.g.:\n"
        "    bin/yitc-v2 task update <T-XXXX> --old 'product_dispatch_owner_ack: null' "
        "--new 'product_dispatch_owner_ack: <owner-authorization-ref>'\n"
        "(SPEC-0028 write-path), then re-dispatch. A GOVERNANCE-ONLY card (expected_touch wholly inside "
        "tasks/ specs/ decisions/ plans/ patterns/ lessons/ scenarios/ graph/ *.md events.jsonl) is "
        "NEVER blocked; out of a migration window this gate is a no-op.")


def _touch_overlap_report(cards) -> dict:
    """T-10872 — fold the DECLARED touch sets of the cards a dispatch is about to launch into the
    overlap report. Input is the ORDERED `[(task_id, card_dict_or_None)]` shape `_product_gate_refusals`
    already takes (same substrate at the call site: `_read_yaml(_find_task_yaml(t))`).

    Returns::

        {"declared": {task_id: [path, ...]},        # cards that DECLARED, their normalized file parts
         "unknown":  [task_id, ...],                # cards declaring NOTHING — see below
         "overlaps": [{"path": p, "tasks": [...], "symbols": [...]}, ...]}   # sorted by path

    A card is UNKNOWN iff it is absent/unreadable (None) or its `expected_touch` yields no usable unit.
    UNKNOWN IS THE LOAD-BEARING OUTPUT, not a degenerate case: `expected_touch` is optional and today
    near-universally empty, so most real waves are mostly UNKNOWN. An undeclared card is NEVER folded
    into "no overlap" — the two are opposite epistemic states ("we looked, it is clean" vs "we cannot
    see"), and collapsing them would manufacture the false confidence this report exists to prevent.

    A `path#symbol` entry contributes its FILE part to the overlap key (via the shared
    `_touch_unit_path`) AND records the full token in `symbols` — two cards on the same SYMBOL are the
    strongest land-conflict signal (the SPEC-0136 weighting), so the renderer can mark it, but they
    collide on the file either way.

    PURE (no I/O, no git, no clock): the whole testable core of the feature. This deliberately does NOT
    reuse journal's `_card_touch_tokens` — that needs an injected `_is_governance_surface` classifier
    and returns a governance/ordinary 3-split this report does not use (it reports the intersection, it
    does not weight blast radius); see the card's analysis."""
    declared, unknown, by_path = {}, [], {}
    for tid, card in cards:
        card = card if isinstance(card, dict) else {}
        units = {}
        for e in (card.get("expected_touch") or []):
            p = _touch_unit_path(e)
            if not p:
                continue                              # degenerate unit: drop, never invent a path
            units.setdefault(p, set())
            sym = str(e).split("#", 1)[1].strip() if "#" in str(e) else ""
            if sym:
                # RE-COMPOSE from the NORMALIZED path, never the raw entry: `./x.py#f` and `x.py#f`
                # name the same symbol and must compare equal, or a same-symbol collision written in
                # the two spellings would be reported as a mere path overlap.
                units[p].add(f"{p}#{sym}")
        if not units:
            unknown.append(tid)                       # NOTHING declared → UNKNOWN, never "clean"
            continue
        declared[tid] = sorted(units)
        for p, syms in units.items():
            # T-11142 — a UNION-MERGED path is never a collision: `events.jsonl` is append-only and
            # union-merged by `land`, so two cards writing it cannot conflict (<project> X-0887).
            # Dropped from the overlap KEY only — it stays in `declared` above, so a card declaring
            # ONLY the journal remains "declared, no overlap" and never falls through to UNKNOWN
            # (those are opposite epistemic states; see this function's docstring).
            if _touch_path_is_union_merged(p):
                continue
            slot = by_path.setdefault(p, {"tasks": [], "sym_tasks": {}})
            if tid not in slot["tasks"]:
                slot["tasks"].append(tid)
            for s in syms:
                slot["sym_tasks"].setdefault(s, set()).add(tid)
    # `symbols` = only the symbol tokens DECLARED BY MORE THAN ONE card on that path — a same-symbol
    # collision, the strongest land-conflict signal. A symbol only one card names adds no information
    # about the collision, so it is not reported.
    overlaps = [{"path": p, "tasks": list(v["tasks"]),
                 "symbols": sorted(s for s, ts in v["sym_tasks"].items() if len(ts) > 1)}
                for p, v in sorted(by_path.items()) if len(v["tasks"]) > 1]
    return {"declared": declared, "unknown": unknown, "overlaps": overlaps}


def _touch_overlap_block(report: "dict", n_tasks: int) -> str:
    """Render the pre-launch touch-overlap advisory (T-10872) IN THE DECISION FRAME — the block
    `cmd_dispatch` PRINTS before the first launch line, so a controller batching N tasks sees the
    declared collisions AT THE MOMENT OF THE DECISION rather than hours later as a merge conflict at
    the last land (the T-10821 incident: six cards onto `bin/lib/worktree.py`, five landed 14 commits
    into it, the sixth died on non-union conflicts).

    THREE VISIBLY DISTINCT STATES, which is the point of the block: an OVERLAP row (who collides, on
    what), `declared, no overlap` (checked and clean), and `UNKNOWN` (nothing declared — overlap could
    not be ruled out). The third must never render like the second.

    REPORT-ONLY FOREVER (CHARTER non-goals #2/#7 + the §6 fence, the same fence SPEC-0133 §6 puts
    around its sibling readiness advisory): overlap is frequently LEGITIMATE — sibling fixes to one
    module are normal work — and whether to serialize is a controller JUDGEMENT about the specific
    change, which the launcher has no basis to make. Nothing here refuses, reorders, delays, caps or
    resizes a wave; a fully-overlapping batch launches unchanged.

    It emits NO adoption event (audit-pre pass-1 absorption): printing proves bytes reached a terminal,
    NOT that a human read or acted, so the block instead CUES the controller to record the call they
    actually made. Asserting adoption from a print would be this card's own failure mode, one layer up.

    PURE (str out) so the tripwires assert on the exact text."""
    lines = ["dispatch touch-overlap (declared `expected_touch` across this wave — ADVISORY, "
             "report-only, never a gate):"]
    for ov in report["overlaps"]:
        mark = (f"  [same symbol: {', '.join(ov['symbols'])} — strongest land-conflict signal]"
                if ov["symbols"] else "")
        lines.append(f"  OVERLAP  {ov['path']}  ← {', '.join(ov['tasks'])} "
                     f"({len(ov['tasks'])} cards declare it){mark}")
    if not report["overlaps"]:
        lines.append("  OVERLAP  none among the cards that DECLARED (this says nothing about the "
                     "UNKNOWN ones below)")
    clean = [t for t in report["declared"] if not any(t in ov["tasks"] for ov in report["overlaps"])]
    if clean:
        lines.append(f"  declared, no overlap: {', '.join(clean)}")
    if report["unknown"]:
        lines.append(f"  UNKNOWN — nothing declared, overlap CANNOT be ruled out (this is NOT "
                     f"'no overlap'): {', '.join(report['unknown'])}")
    lines.append(f"  → launching {n_tasks} worker(s) this wave. Overlap is often LEGITIMATE; "
                 f"serializing/re-ordering is YOUR call — this never refuses, reorders or delays a "
                 f"launch (CHARTER §6).")
    lines.append("  record the call you made (adoption evidence is a human act, never this print): "
                 "bin/yitc-v2 event consumer_read_evidence --task T-10872 "
                 "--data '{\"decision\":\"serialize|reorder|proceed\",\"tasks\":[\"<T-XXXX>\"],"
                 "\"failing_input\":\"<the overlap this advisory would have failed to print>\","
                 "\"evidence_events\":[\"bg_dispatch_launched@<iso-ts>\"]}'")
    # T-13159: the payload carries the SPEC-0015 P8 keys (`failing_input` + `evidence_events`) and is
    # literal JSON, so the printed command passes the T-12866 write-time gate as printed.
    return "\n".join(lines)


def _inflight_touch_overlap_block(wave_cards, inflight_cards) -> str:
    """T-13204 — the SECOND-CALL half of the touch-overlap advisory. `_touch_overlap_block` compares
    only the cards of ONE dispatch call, so two calls 46 s apart onto the same files (test-server
    T-0011/T-0012, 6+ shared paths) launched silently. This compares each card being launched against
    the `expected_touch` of cards whose workers are ALREADY in flight (live `task/T-XXXX` claims),
    naming the in-flight card and the shared paths.

    Reuses the `_touch_overlap_report` fold over the union (same path normalization, same union-merged
    `events.jsonl` exclusion) and keeps only overlaps pairing a launched card with an in-flight one.
    An in-flight id that is ALSO in this wave (a re-dispatch) is dropped from the in-flight side.
    REPORT-ONLY like its sibling (CHARTER §6): returns "" when nothing overlaps; never refuses. PURE."""
    wave_ids = {t for t, _c in wave_cards}
    inflight = [(t, c) for t, c in inflight_cards if t not in wave_ids]
    if not inflight:
        return ""
    inflight_ids = {t for t, _c in inflight}
    rows = []
    for ov in _touch_overlap_report(list(wave_cards) + inflight)["overlaps"]:
        launched = [t for t in ov["tasks"] if t in wave_ids]
        running = [t for t in ov["tasks"] if t in inflight_ids]
        if launched and running:
            rows.append((ov["path"], launched, running))
    if not rows:
        return ""
    lines = ["dispatch in-flight touch-overlap (declared `expected_touch` vs workers ALREADY in flight "
             "— ADVISORY, report-only, never a gate):"]
    by_pair = {}
    for path, launched, running in rows:
        for lt in launched:
            for rt in running:
                by_pair.setdefault((lt, rt), []).append(path)
    for (lt, rt), paths in sorted(by_pair.items()):
        lines.append(f"  IN-FLIGHT OVERLAP  {lt} ↔ {rt} (in flight)  shared: {', '.join(paths)}")
    lines.append("  → the launch proceeds; waiting for the in-flight land or re-ordering is YOUR call "
                 "(CHARTER §6).")
    return "\n".join(lines)


_CARD_TRIGGER_FIELDS = ("trigger", "return_trigger")
_ISO_DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")


def _card_precondition_report(cards, today: str) -> dict:
    """T-11678 — fold the cards a dispatch is about to launch into the TWO pre-launch preconditions a
    worker would otherwise spend a full launch to discover on the card's own face (the T-10980 cost:
    nine workers launched in one shift, three refused at pre-claim; the most expensive was a card whose
    own trigger dates it sixteen days out).

    Input is the ORDERED `[(task_id, card_dict_or_None)]` shape `_touch_overlap_report` /
    `_product_gate_refusals` already take — the SAME substrate at the call site, so this adds no read
    path. `today` is INJECTED as an ISO `YYYY-MM-DD` string (no clock here) so the differential tests
    can move the date rather than the card.

    Returns::

        {"unarrived_trigger": [{"task": tid, "field": f, "date": "YYYY-MM-DD"}, ...],
         "open_observation":  [{"task": tid, "due_by": d, "observation": o}, ...]}

    BOTH checks are STRUCTURAL — read off declared FIELDS, never off prose (the card's own bound).
    Duplicate detection and owner-class detection are deliberately NOT here: today they are visible
    only as an inference over commit history / a text match on acceptance prose, and a false positive
    would talk an operator out of real work.

    TRIGGER arm — `trigger` / `return_trigger` (the SPEC-0028 parking-lot field). The field's VALUE is
    prose, so the DATE is extracted from it; what makes the check structural is that only these named
    fields are read. A field may name SEVERAL dates, so the reported one is the EARLIEST: if even the
    earliest has passed, the trigger may already have fired and the card must NOT be flagged. That
    direction is deliberate — this advisory's failure mode is the false positive, not the miss.

    OBSERVATION arm — `post_ship_observation` (SPEC-0028 / T-10916): declared iff it is a mapping
    carrying a non-empty `observation`, and OPEN until a non-empty `settled_by` names where the reading
    landed. Time passing never discharges it, so `due_by` is REPORTED but never a condition.

    PURE (no I/O, no git, no clock): the whole testable core of the feature."""
    unarrived, open_obs = [], []
    for tid, card in cards:
        card = card if isinstance(card, dict) else {}
        for field in _CARD_TRIGGER_FIELDS:
            raw = card.get(field)
            if not isinstance(raw, str) or not raw.strip():
                continue
            dates = sorted(_ISO_DATE_RE.findall(raw))
            if dates and dates[0] > str(today):
                # EARLIEST first: an unarrived earliest date proves the trigger cannot have fired.
                unarrived.append({"task": tid, "field": field, "date": dates[0]})
        pso = card.get("post_ship_observation")
        if isinstance(pso, dict):
            obs = str(pso.get("observation") or "").strip()
            settled = str(pso.get("settled_by") or "").strip()
            if obs and not settled:
                open_obs.append({"task": tid, "due_by": str(pso.get("due_by") or "") or "unset",
                                 "observation": obs})
    return {"unarrived_trigger": unarrived, "open_observation": open_obs}


def _card_precondition_lines(report: "dict") -> list:
    """Render the TWO card-precondition lines of the readiness frame (T-11678). Each line NAMES which
    condition tripped AND the field + date it read, so an operator can act without opening the card
    (AC4) — a bare flag would just move the investigation, which is the cost this exists to remove.
    A clean check renders `none` rather than vanishing, so "checked and clean" never reads the same as
    "not checked". PURE (dict in → list-of-str out) so the tripwires assert on the exact text."""
    trig = ", ".join(f"{r['task']} ({r['field']} names {r['date']}, not yet reached)"
                     for r in report["unarrived_trigger"]) or "none"
    obs = ", ".join(f"{r['task']} (post_ship_observation declared, due_by {r['due_by']}, "
                    f"no settled_by yet)" for r in report["open_observation"]) or "none"
    return [f"  unarrived_trigger: {trig}",
            f"  open_observation: {obs}"]


def _wave_memory_reading(_mem_available_mb=None, _self_peak_rss_kb=None) -> "dict | None":
    """T-12913 (<project> X-1556) — the MEMORY inputs of the readiness frame: host MemAvailable and the
    measured peak RSS of THIS yitc-v2 invocation (the dispatch process itself — a whole-CLI load, the
    per-invocation cost every worker session pays many times over). Reuses the one MemAvailable reader
    (`verify_runner._mem_available_mb`); RUSAGE_SELF ru_maxrss is KB on Linux. Both readers are
    injectable for hermetic tests. FAIL-OPEN: either reading unavailable → None, and the frame renders
    exactly as before — a telemetry input never fabricates a number (T-0358)."""
    try:
        if _mem_available_mb is None:
            from lib import verify_runner
            _mem_available_mb = verify_runner._mem_available_mb
        if _self_peak_rss_kb is None:
            import resource
            _self_peak_rss_kb = lambda: resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        avail, rss_kb = _mem_available_mb(), _self_peak_rss_kb()
    except Exception:
        return None
    if not isinstance(avail, int) or not isinstance(rss_kb, int) or avail < 0 or rss_kb <= 0:
        return None
    return {"mem_available_mb": avail, "per_invocation_rss_mb": max(1, rss_kb // 1024)}


def _memory_advisory_line(mem: "dict | None", width: int) -> "str | None":
    """T-12913 — the memory line of the readiness frame, or None. PURE. Printed ONLY when MemAvailable is
    below the projected need for the requested width (width x measured per-invocation RSS), naming
    BOTH numbers; ample memory, an empty wave or no reading → None, so the frame is unchanged. Same
    report-only contract as the rest of the frame (SPEC-0133 §6): nothing reads this line back."""
    if not mem or width <= 0:
        return None
    avail, rss = mem["mem_available_mb"], mem["per_invocation_rss_mb"]
    need = width * rss
    if avail >= need:
        return None
    return (f"  memory: MemAvailable={avail}MB < projected need {need}MB for {width} worker(s) "
            f"(x {rss}MB measured per-invocation RSS) — memory, not CPU, bounds this wave "
            f"(advisory; swap exhaustion kills background watchers, X-1556)")


def _readiness_advisory_block(report: "dict", n_tasks: int, cards=None,
                              today: "str | None" = None, mem: "dict | None" = None,
                              fit: "dict | None" = None, reused=()) -> str:
    """Render the pre-launch dispatch-readiness advisory (SPEC-0133 §6 / T-10354) IN THE DECISION FRAME —
    the block `cmd_dispatch` PRINTS before the first launch line so the controller sizes/confirms the
    wave against LIVE fleet-width, not memory (the consult verdict-A requirement, fold → visible advisory
    → launch; `decisions/dispatch-readiness-delivery-audit-adhoc.yaml`). REPORT-ONLY FOREVER: the block
    is telemetry — it does NOT refuse/queue/clamp/delay/auto-resize the wave and never requires compliance
    with the recommended ceiling (CHARTER §6 fence, SPEC-0133 §6). PURE (str in → str out): the testable
    core of the decision-frame delivery + its report-only wording.

    T-11678 — when `cards` is supplied (the ordered `[(task_id, card_or_None)]` shape the sibling
    folds already take) this block ALSO carries TWO card-precondition lines: a card whose own
    `trigger`/`return_trigger` names a date that has not arrived, and a card whose declared
    `post_ship_observation` is not yet settled. They INHERIT this block's contract exactly — telemetry,
    report-only forever, no refusal/queue/clamp/delay/resize (SPEC-0133 §6 / CHARTER §6). Omitted
    entirely when `cards` is None, so a caller that has no card substrate renders byte-identically.

    T-12913 — when `mem` (a `_wave_memory_reading`) is supplied, the block ALSO carries ONE memory line
    beside the CPU headroom line, but only while MemAvailable is short of the wave's projected need
    (`_memory_advisory_line`). Same contract: telemetry, no refusal/queue/clamp/delay/resize.

    T-13540 — `reused` is the wave ids that ALREADY hold a `task/` worktree (a re-dispatch into a
    preserved dead-holder worktree, or an id the in-flight guard will skip). `live_worker_count`
    counts every `task/` worktree (T-10010, deliberate), so such an id is already inside it: the
    worker-fit wave is live + n_tasks - reused, and the live line says how many are re-used. Clamped
    to the wave and to the live count; an empty `reused` renders byte-identically. The report fields
    and the ceiling are untouched — this corrects one printed sum, nothing reads it back."""
    h = report["headroom"]
    ceiling = report["recommended_wave_ceiling"]
    pre_lines = (_card_precondition_lines(_card_precondition_report(cards, today or ""))
                 if cards is not None else [])
    mem_line = _memory_advisory_line(mem, n_tasks)
    live = int(report.get("live_worker_count") or 0)
    n_reused = max(0, min(len(set(reused or ())), n_tasks, live))   # T-13540 — counted once, not twice
    # T-13237 — project/host worker fit: advisory only when the wave would exceed it, never a refusal.
    fit_line = None
    if fit and isinstance(fit.get("recommended"), int):
        wave = live + n_tasks - n_reused
        if wave > fit["recommended"]:
            fit_line = (f"  workers: this wave would run {wave} parallel worker(s); this host fits "
                        f"{fit['recommended']} for this project — advisory, launching anyway")
    return "\n".join([
        "dispatch-readiness (pre-launch decision frame — ADVISORY, report-only, no admission control):",
        f"  recommended_wave_ceiling: {ceiling}  (advisory — size/confirm your wave against it; never enforced)",
        f"  server bounds (T-10386, SUGGESTED — never a coded cap): max_fleet_width={journal.max_fleet_width()}  "
        f"watch_poll_interval={journal.WATCH_POLL_INTERVAL_SECS}s  watch_max_runtime={journal.WATCH_MAX_RUNTIME_SECS}s",
        f"  live_worker_count (all sessions task/+work/): {report['live_worker_count']}"
        + (f"  ({n_reused} re-used by this launch)" if n_reused else ""),
        f"  free_slots: {h['free_slots']}  (headroom: nproc={h['nproc']} "
        f"loadavg={h['loadavg1']}/{h['loadavg5']}/{h['loadavg15']})",
        *([mem_line] if mem_line else []),
        *([fit_line] if fit_line else []),
        f"  sole_controller: {str(report['sole_controller']).lower()}   "
        f"in_flight_land: {str(report['in_flight_land']).lower()}",
        *pre_lines,
        f"  → launching {n_tasks} worker(s) this wave; this advisory does NOT refuse/queue/clamp/delay/"
        f"auto-resize it (CHARTER §6).",
    ])


# T-12304 — the CONTROLLER-WAIT resume pair (PURE peers of `_compose_worker_brief`). A clean cued
# stop records its resume contract on the `task_paused(controller-wait)` row (`task pause` writes
# resume_from/next_action); `dispatch --resume` reads THAT row — never controller memory — so the
# brief the worker gets and the `resume_of` stamped on its launch row can never disagree (the T-10578
# journal-over-memory discipline, applied to the resume head).
def _controller_wait_release(events: "list") -> "dict | None":
    """The `task_paused(controller-wait)` row that RELEASES the in-flight guard, or None.

    A cued stop is TERMINAL: the worker exited. The guard's launched axis has no terminal marker for
    it, so before this the next `dispatch --task` of the same id was SKIPPED as in-flight until the
    controller passed `--force` (measured 2026-09-09: T-12297 skipped, T-12288 forced). Release
    predicate, asserted EXPLICITLY here rather than inherited from the full-list `cls` coincidence the
    surrounding comments warn against: the newest controller-wait pause is NEWER than the newest
    `bg_dispatch_launched`, and no `task_resumed` post-dates it (a resumed pause is over). Pure —
    `events` is the ts-ASCENDING per-id list the guard already holds; no new reader."""
    pause = journal._controller_wait_pause(events)
    if pause is None:
        return None
    launched = next((e for e in reversed(events or [])
                     if e.get("type") == "bg_dispatch_launched"), None)
    if launched is not None and (pause.get("ts") or "") <= (launched.get("ts") or ""):
        return None
    return pause


def _resume_contract_block(pause: "dict | None") -> str:
    """Render the recorded resume contract as ONE brief block. Empty string when there is no row, so
    a caller with nothing recorded composes a byte-identical ordinary brief. Pure."""
    if not pause:
        return ""
    data = pause.get("data") if isinstance(pause.get("data"), dict) else {}
    return (
        "=== RECORDED RESUME CONTRACT (from your own `task pause --reason controller-wait` row — "
        "JOURNAL-derived, not controller memory; T-12304) ===\n"
        f"paused_at   : {pause.get('ts') or '?'}\n"
        f"reason      : {data.get('reason') or '?'}\n"
        f"stage       : {data.get('stage') or '?'}  (re-enter it with `stage <STAGE> --task <id>`)\n"
        f"resume_from : {data.get('resume_from') or '(none recorded)'}\n"
        f"next_action : {data.get('next_action') or '(none recorded)'}\n"
        "This is where you STOPPED and what you recorded as the next step. Any delta below AMENDS it; "
        "where they are silent, this contract governs.\n"
        "=== END RECORDED RESUME CONTRACT ===")


# ── T-12303: the COMPOSED brief preamble ─────────────────────────────────────────────────────────
# The Controller used to hand-write the same preamble into every worker brief (measured 2026-09-09:
# six briefs of several KB for three cards, most of each restating the card's acceptance, the owner's
# binding `owner_directive` rows, «what the requires shipped» and the DO-NOT-LAND paragraph). Hand
# copying DRIFTS — a rule paraphrased differently per brief is a rule the worker may read differently
# than the owner wrote it — and it costs Controller context. So `dispatch` DERIVES the preamble from
# DURABLE STATE at launch and the Controller's `--brief/-f` becomes only the DELTA appended after it.
#
# Nothing here is a new mechanism (CHARTER §P1 F1/F2): the card comes from the `_wave_cards` read
# cmd_dispatch already does, the rules from the journal through `journal.segment_rows` (the ONE
# segment-aware fold `_iter_events` itself goes through — `_dispatch_status_events` CANNOT see them,
# `owner_directive` is a member of DISPATCH_EXCLUDED_TYPES), the coverage test from
# `audit._directive_covers_task`, the «as shipped» facts off the EXISTING `task_closed` row, and the
# stop/land paragraph from `_build_sync_to_land_rule(controller_lands=True)`. No store, no event type.
#
# FAIL LOUD, and this is the ONE place in cmd_dispatch that does. Every other advisory at this seam
# (the readiness frame, touch-overlap, the spike hint, the re-dispatch tail) swallows its exceptions
# because a broken advisory must never cost a wave. The preamble is the opposite: silently dropping
# the owner rules is exactly the drift this block removes, and the worker would launch believing its
# brief complete. So the call site `_die`s and names `--brief-raw` as the deliberate escape.

# The ONE template AC3 names — the stop/land contract, rendered from the SINGLE source
# `_build_sync_to_land_rule` (see its `controller_lands` docstring): not a parallel policy text.
DISPATCH_STOP_LAND_CONTRACT = _build_sync_to_land_rule(controller_lands=True)

# The literal `data.cards` element that makes a directive a WILDCARD over every dispatched card.
# Deliberately a LIST-MEMBERSHIP arm only, never a prose arm: «all» is an ordinary English word, so a
# token match on prose would admit nearly every directive ever journaled — fail-OPEN on exactly the
# authority boundary `audit._directive_covers_task` is fail-closed about.
_BRIEF_RULE_WILDCARD = "all"


def _brief_directive_rows(rows) -> list:
    """The `owner_directive` rows of a journal row list, ts-ASCENDING (PURE).

    Split out from the coverage filter below so ONE narrowing pass over the wave's single journal
    read feeds every task in the wave (the launch loop is per-task; this is not)."""
    out = [r for r in (rows or [])
           if isinstance(r, dict) and r.get("type") == "owner_directive"]
    out.sort(key=lambda r: str(r.get("ts") or ""))
    return out


def _brief_owner_rules(directive_rows, task_id: str, plan_slug: "str | None" = None) -> list:
    """The owner rules a brief for `task_id` must carry, as `[(locator, text), …]` ts-ASCENDING (PURE).

    A row COVERS the card when it names the card, names the plan the card is `decomposed_from`, or
    carries the `all` wildcard in `data.cards`. The first two arms are NOT re-implemented here — they
    are `audit._directive_covers_task`, the token-exact SPEC-0204 rule 2 predicate (a directive naming
    `plan-foobar` never covers a card cut from `plan-foo`; one naming `T-12287` never covers `T-1228`).
    The import is LAZY, keeping this module the low leaf its header declares; audit.py does not import
    dispatch.py, so there is no cycle.

    `text` is the row's prose VERBATIM (`audit._directive_row_text` — the same surface the ceiling
    decision's quote test reads), never a paraphrase or a re-wrap: AC2. `locator` is the
    `events.jsonl#ts=<ISO>` form the owner-decision machinery already spells, so a worker (or an
    auditor reading the brief) can resolve the rule back to the row it came from."""
    from lib import audit as _audit    # noqa: PLC0415 — lazy by design (leaf-order, see docstring)
    out = []
    for r in directive_rows or []:
        data = r.get("data") if isinstance(r.get("data"), dict) else {}
        cards = data.get("cards") if isinstance(data.get("cards"), list) else []
        covered = (_BRIEF_RULE_WILDCARD in [str(c) for c in cards]
                   or _audit._directive_covers_task(r, task_id, plan_slug=plan_slug))
        if not covered:
            continue
        text = _audit._directive_row_text(r)
        if not str(text).strip():
            continue                  # a row with no prose carries no rule to hand a worker
        out.append((f"events.jsonl#ts={r.get('ts')}", text))
    return out


def _brief_shipped_requires(requires, rows, card_of) -> list:
    """The «as shipped» facts for each DONE `requires` id, in the card's own order (PURE).

    `card_of(tid)` returns that id's parsed card (or None); `rows` is the wave's journal row list.
    An entry is emitted ONLY for an id the journal records as CLOSED — a `requires` still open has
    nothing shipped to describe, and inventing a block for it would be the drift this composer
    exists to remove. The facts come off the EXISTING `task_closed` row (`data.commit`, `data.probes`,
    `data.adoption_evidence_seen`) — the newest one wins, so a recovered close tail reads correctly.

    Returns `[{id, title, commit, probes, adoption_evidence_seen}, …]`."""
    closed = {}
    for r in rows or []:
        if not isinstance(r, dict) or r.get("type") != "task_closed":
            continue
        tid = r.get("task_id")
        if not tid:
            continue
        if str(r.get("ts") or "") >= str((closed.get(tid) or {}).get("ts") or ""):
            closed[tid] = r
    out = []
    for tid in (requires or []):
        row = closed.get(str(tid))
        if row is None:
            continue
        data = row.get("data") if isinstance(row.get("data"), dict) else {}
        card = card_of(str(tid)) or {}
        probes = data.get("probes") if isinstance(data.get("probes"), list) else []
        out.append({"id": str(tid), "title": str(card.get("title") or "(no title on card)"),
                    "commit": data.get("commit"), "probes": probes,
                    "adoption_evidence_seen": data.get("adoption_evidence_seen")})
    return out


def _wave_journal_fold(path, wave_cards) -> dict:
    """T-13255 — the ONE journal walk a launch needs, retaining only what its three readers use.

    Replaces `list(journal.segment_rows(path))` (measured 3.5 GiB / 20 s on the kernel journal). One
    `journal.scan_journal` walk over the fold-family line source (`_typed_walk`'s), typed to
    owner_directive / task_closed / land_completed, with a `FoldCollector` whose state is bounded by
    the OUTPUT, never the journal:
      - `directive_rows` — only rows `_brief_owner_rules` would CARRY for some wave card, ts-sorted as
        `_brief_directive_rows` sorts them. Every retained row is printed verbatim into a brief, so
        this grows with the brief's own rule text and nothing else (owner decision A, 2026-09-30);
      - `closure_rows` — the newest `task_closed` per wave `requires` id (the `>=` rule
        `_brief_shipped_requires` applies, in the same walk order), at most one row per id;
      - `fit_rows` + `lands_read` — the <=10 newest MEASURED `land_completed` rows (by (ts, sample),
        the order `measured_verify_cores` picks its last 10 by) and the count of all of them."""
    import heapq   # noqa: PLC0415 — only this fold needs it
    requires = {str(r) for _t, c in wave_cards for r in ((c or {}).get("requires") or [])}
    plans = [(t, (c or {}).get("decomposed_from")) for t, c in wave_cards]

    def step(st, row):
        typ = row.get("type")
        if typ == "land_completed":
            st["lands_read"] += 1
            sample = journal.measured_verify_cores([row])
            if sample is not None:
                item = (str(row.get("ts") or ""), sample, st["seq"], row)
                st["seq"] += 1
                if len(st["fit"]) < 10:   # the 10 newest measured samples `measured_verify_cores` reads
                    heapq.heappush(st["fit"], item)
                elif item[:2] > st["fit"][0][:2]:
                    heapq.heapreplace(st["fit"], item)
        elif typ == "task_closed":
            tid = row.get("task_id")
            if tid and tid in requires and (
                    str(row.get("ts") or "") >= str((st["closed"].get(tid) or {}).get("ts") or "")):
                st["closed"][tid] = row
        elif typ == "owner_directive":
            if any(_brief_owner_rules([row], t, plan_slug=p) for t, p in plans):
                st["directives"].append(row)
        return st

    types = {"owner_directive", "task_closed", "land_completed"}
    collector = journal.FoldCollector(
        step, {"lands_read": 0, "seq": 0, "fit": [], "closed": {}, "directives": []})
    # T-13366 — inside the launch's request scope (`cli._dispatch_launch_reads`, which declares these
    # types) the rows come from its ONE walk — an archived segment served from the T-13356 index — in
    # the same logical order; anything else (no scope, an undeclared answer) walks as before.
    scope = journal.scope_of(path)
    served = scope.serve(types, lazy=True) if scope is not None else None
    if served is not None:
        for seq, row in enumerate(served):
            collector.add(seq, row)
        st = collector.result()
    else:
        st = journal.scan_journal(path, types=types, collector=collector,
                                  lines=journal._FoldLineSource(list(events.segment_paths(path))))
    return {"directive_rows": _brief_directive_rows(st["directives"]),
            "closure_rows": list(st["closed"].values()),
            "fit_rows": [it[3] for it in sorted(st["fit"], key=lambda it: it[:3])],
            "lands_read": st["lands_read"]}


def _wave_worker_fit(path, fold):
    """`journal.worker_fit` over the fold's retained rows, `lands_read` restored to the full count."""
    fit = journal.worker_fit(path, os.cpu_count(), rows=fold["fit_rows"])
    if fit is not None:
        fit["lands_read"] = fold["lands_read"]
    return fit


def _hand_in_engine_root() -> Path:
    """The engine checkout this module runs from (`<engine>/bin/lib/dispatch.py`) — the one place the
    SPEC-1019 hand-in is read from, for an engine and a `-C` consumer dispatch alike (T-13795)."""
    return Path(__file__).resolve().parents[2]


def _spec_hand_in_bullet(engine_root=None) -> "str | None":
    """T-13795 — the SPEC-1019 «CHANGE HAND-IN» bullet, read from the spec AT COMPOSE TIME (one
    source, never a copied string): the bullet line plus its indented continuation lines, byte-equal
    to the parsed spec body. Read from the ENGINE's own `specs/` — the checkout this module runs from
    (`<engine>/bin/lib/dispatch.py`) — so a `-C` consumer's brief carries the kernel rule and a
    consumer's same-id spec never shadows it. None when the spec file, its `active` status or the
    bullet is absent, or the read fails: the caller states the absence instead of dropping the block."""
    import yaml
    root = Path(engine_root) if engine_root is not None else _hand_in_engine_root()
    try:
        paths = sorted((root / "specs").glob("SPEC-1019-*.yaml"))
        doc = yaml.safe_load(paths[0].read_text(encoding="utf-8")) if paths else None
    except Exception:   # noqa: BLE001 — an unreadable spec is reported as absent, never a crash
        return None
    if not isinstance(doc, dict) or doc.get("status") != "active" or not isinstance(doc.get("body"), str):
        return None
    lines = doc["body"].split("\n")
    for i, line in enumerate(lines):
        if line.startswith("- **CHANGE HAND-IN"):
            j = i + 1
            while j < len(lines) and lines[j].startswith("  "):
                j += 1
            return "\n".join(lines[i:j])
    return None


def _compose_brief_preamble(task_id: str, card: "dict | None", owner_rules, shipped,
                            venue_line: "str | None" = None,
                            controller_lands: bool = False) -> str:
    """Render the DERIVED half of a worker brief — everything a Controller used to retype. Pure
    apart from one file read (the SPEC-1019 hand-in, T-13795).

    The blocks, in the order a worker needs them: the card header, the card's SCOPE and its
    ACCEPTANCE **verbatim**, the owner rules (each with its journal locator), one «as shipped» block
    per closed `requires` id, the stop/land contract from `DISPATCH_STOP_LAND_CONTRACT`, the SPEC-1019
    change hand-in (T-13795 — the one read this render makes: that spec file, via
    `_spec_hand_in_bullet`), and the current venue line. The Controller's own brief is APPENDED
    AFTER this by the caller and is
    therefore the last word on task-specific detail — this preamble is the floor, not a ceiling.

    T-12373 — the STOP / LAND CONTRACT block is now emitted ONLY under `controller_lands` (T-12303's
    UNCONDITIONAL append is retired). It is the ONE HOME of the controller-lands regime
    (owner_directive events.jsonl#ts=2026-09-11T04:46:38Z), so appending it to a brief whose point 1
    already carries the WORKER-lands rule is what put BOTH regimes in every composed brief. The
    constant stays the single template this branch renders from — nothing about it is duplicated
    here; what changed is only WHETHER it is appended."""
    card = card if isinstance(card, dict) else {}
    L = [f"=== COMPOSED BRIEF PREAMBLE — DERIVED BY `dispatch` FROM DURABLE STATE (T-12303) ===",
         "Everything below this line was READ from the card, the journal and the venue record at "
         "launch — it is not a Controller paraphrase. The Controller's own brief (the DELTA) follows "
         "after it and adds only what is specific to THIS dispatch.",
         "",
         f"TASK: {task_id} — {card.get('title') or '(no title on card)'}",
         f"  class {card.get('class') or '?'} · priority {card.get('priority') or '?'} · "
         f"effort tier {card.get('estimate_tier') or '(default)'}"]
    for key in ("requires", "cites", "expected_touch"):
        val = card.get(key)
        if isinstance(val, list) and val:
            L.append(f"  {key}: {', '.join(str(v) for v in val)}")
        elif val:
            L.append(f"  {key}: {val}")
    if card.get("decomposed_from"):
        L.append(f"  decomposed_from: {card.get('decomposed_from')}")

    def _bullets(header, val):
        L.extend(["", header])
        if isinstance(val, list):
            for item in val:
                L.append(f"  - {item}")
        elif val:
            L.append(f"  {val}")
        else:
            L.append("  (the card records none)")

    _bullets("SCOPE (from the card):", card.get("scope"))
    _bullets("ACCEPTANCE — VERBATIM from the card; these are the criteria your close is judged on:",
             card.get("acceptance"))

    L.extend(["", "OWNER RULES — journaled `owner_directive` rows covering this card, its plan or "
                  "`all`. VERBATIM and BINDING; each is resolvable at the locator that names it:"])
    if owner_rules:
        for locator, text in owner_rules:
            # The rule text goes in as ONE UNCHANGED BLOCK — not re-indented line by line, not
            # re-wrapped. AC2 is BYTE-IDENTITY with the journal row's `text`, and a per-line indent
            # breaks it for any MULTI-LINE rule (audit-post pass-1 finding fp1:7d0c07306331c8fa):
            # `"Line one\nLine two"` came out as `"      Line one\n      Line two"`, which is not
            # the owner's bytes. Everything the render adds — the locator label, the fences — sits
            # OUTSIDE the block, so the rule's own bytes are reproduced exactly and a reader can
            # diff them against the row.
            L.append(f"  - {locator}:")
            L.append("    ┌── VERBATIM (byte-identical to the journal row's `text`) ──")
            L.append(str(text))
            L.append("    └──")
    else:
        L.append("  (the journal records no owner_directive row covering this card — none is "
                 "invented here; the Controller's delta below is the only rule surface.)")

    L.extend(["", "AS SHIPPED — what this card's `requires` already landed (reuse it, do NOT rebuild "
                  "it):"])
    if shipped:
        for s in shipped:
            L.append(f"  - {s['id']} — {s['title']}")
            L.append(f"      closing commit: {s.get('commit') or '(none recorded)'} · "
                     f"adoption evidence seen: {s.get('adoption_evidence_seen')}")
            if s.get("probes"):
                L.append("      P8 evidence: " + "; ".join(
                    f"{p.get('ac')}={p.get('result')}" if isinstance(p, dict) else str(p)
                    for p in s["probes"]))
    else:
        L.append("  (no `requires` id is closed in the journal — nothing has shipped for you to "
                 "reuse.)")

    # T-12373 — ONE regime per brief. Under the DEFAULT (the worker lands — CHARTER §6) point 1
    # already carries `SYNC_TO_LAND_RULE`, so appending the controller-lands contract here would give
    # the worker two contradictory land contracts; under `--controller-lands` point 1 states NO regime
    # and this block is the only place the regime is stated. Exactly one of the two, either way.
    if controller_lands:
        L.extend(["", "STOP / LAND CONTRACT:", DISPATCH_STOP_LAND_CONTRACT])
    # T-13795 — the SPEC-1019 hand-in, VERBATIM from the active spec, in BOTH land regimes. The full
    # bullet, never a shortened cue: the full text placed in the brief is what measured the effect
    # (plan author-passes-audit-on-the-first-try-give-the-auth, k32).
    hand_in = _spec_hand_in_bullet()
    L.extend(["", "CHANGE HAND-IN — VERBATIM from the active SPEC-1019 §1, read at launch; do this when "
                  "your edits are done, before `stage Tests`:"])
    # The absence line names the kernel spec by its ABSOLUTE engine path, never a CLI spelling: a
    # bare `bin/yitc-v2 graph query` does not exist in a `-C` consumer and could resolve a same-id
    # consumer spec there (audit-pre fp1:c6ac8a478039b8d8).
    L.append(hand_in if hand_in else
             f"  (SPEC-1019's «CHANGE HAND-IN» bullet could not be read at launch — read the kernel "
             f"spec SPEC-1019-*.yaml in {_hand_in_engine_root() / 'specs'} before `stage Tests`.)")
    L.extend(["", f"VENUE: {venue_line or '(no venue line available)'}", "",
              "=== END COMPOSED PREAMBLE — the Controller's DELTA follows ==="])
    return "\n".join(L)


# T-12479 — the Controller DELTA check. The preamble above is DERIVED and already states one land
# regime and one task id; the delta is the one part `dispatch` does not compose, so it is the one
# part that can still contradict them. Two measured classes: a foreign task-context block pasted in
# with the delta (redispatch-brief-carries-foreign-task-context-block, 2026-09-07 — a `sed` trailer
# extraction carried T-12110's context into 11 briefs), and a delta land instruction that contradicts
# the wave's regime (dispatch-brief-land-contract-contradicts-controller-delta, 9 captures).
_DELTA_TASK_ID_RE = re.compile(r"\bT-\d{4,}\b")
_DELTA_CONTEXT_HEADER_RE = re.compile(r"^[\s=#*>-]*(?:TASK|Context|CONTEXT)\b")
_DELTA_NEGATED_LAND_RE = re.compile(
    r"\b(?:do\s+not|don'?t|never)\s+(?:invoke\s+`?|run\s+`?)?land\b|\bcontroller\s+lands\b",
    re.IGNORECASE)
_DELTA_SELF_LAND_RE = re.compile(
    r"\bland\s+(?:it\s+)?(?:yourself|synchronously)\b|\breach\s+(?:the\s+)?`?LAND: OK",
    re.IGNORECASE)


def _brief_delta_refusals(task_id: str, delta: "str | None", *, controller_lands: bool) -> list:
    """Every reason the Controller's DELTA for `task_id` must not launch (PURE — [] when clean).

    AC1 — a task-context BLOCK is the paragraph that starts at a `TASK` / `Context` header line and
    runs to the next blank line; ANY `T-` id other than `task_id` inside it (header or body) refuses.
    Ids mentioned in ordinary prose outside such a block stay legal — a delta routinely names sibling
    cards («T-12468 may touch dispatch.py»).

    AC2 — a land instruction that contradicts the ONE regime this wave was derived for: under the
    worker-lands canon a negated one («DO NOT LAND YOURSELF», «the Controller lands»), under
    `--controller-lands` a self-land one («land yourself», «reach `LAND: OK`») that is not negated.
    The contract lives in the preamble; the delta may only append to it."""
    refusals = []
    in_block = False
    for raw in (delta or "").splitlines():
        line = raw.strip()
        if not line:
            in_block = False
            continue
        if _DELTA_CONTEXT_HEADER_RE.match(raw):
            in_block = True
        if in_block:
            foreign = sorted({i for i in _DELTA_TASK_ID_RE.findall(line) if i != task_id})
            if foreign:
                refusals.append(f"foreign task id(s) {', '.join(foreign)} in a task-context block "
                                f"(this brief is for {task_id}): {line!r}")
        negated = bool(_DELTA_NEGATED_LAND_RE.search(line))
        if not controller_lands and negated:
            refusals.append(f"land instruction contradicts the WORKER-LANDS regime (the worker lands "
                            f"itself; pass --controller-lands for the other regime): {line!r}")
        elif controller_lands and not negated and _DELTA_SELF_LAND_RE.search(line):
            refusals.append(f"land instruction contradicts the CONTROLLER-LANDS regime (the worker "
                            f"stops after `task close`): {line!r}")
    return refusals


def land_regime_for_worker(rows, expected_ref) -> str:
    """The LAND REGIME a dispatched worker was launched under, read off ITS OWN launch row (PURE).

    T-12373 — the stage-entry reminder (`cmd_stage`, T-0687) used to re-deliver `SYNC_TO_LAND_RULE`
    to EVERY worker at five stages, so a controller-lands worker was told «reach `LAND: OK` yourself»
    five times after its brief told it not to land at all. This resolves which sentence that worker
    should see from the durable record of its own dispatch: the LAST `bg_dispatch_launched` whose
    `data.expected` is `expected_ref`.

    FAIL-SAFE TOWARD CANON, on every arm. No matching row, no `land_regime` key, an unrecognised
    value, a malformed row, a non-iterable `rows`, a falsy `expected_ref` — every one returns
    `LAND_REGIME_WORKER`, which is the regime CHARTER §6 prescribes and the sentence workers read
    today. So every PRE-CHANGE row (which carries no key at all) reads as `worker`, and a reader that
    cannot answer degrades to the canonical reminder rather than to silence or to the other regime.
    This is a REMINDER's input, never a gate (non-goal #7): nothing refuses on what it returns."""
    if not expected_ref:
        return LAND_REGIME_WORKER
    try:
        mine = []
        for row in rows or ():
            if not isinstance(row, dict) or row.get("type") != "bg_dispatch_launched":
                continue
            data = row.get("data")
            if not isinstance(data, dict) or data.get("expected") != expected_ref:
                continue
            mine.append((str(row.get("ts") or ""), data.get("land_regime")))
        if not mine:
            return LAND_REGIME_WORKER
        # The ts-LATEST matching row wins (a re-dispatch supersedes) — EXPLICITLY SORTED, so the
        # answer is a function of the row multiset and never of physical order (SPEC-0190 rule 5/6:
        # union-merge order is not chronology). A row whose key is absent or unrecognised resets to
        # canon rather than inheriting an earlier row's regime.
        mine.sort(key=lambda t: t[0])
        regime = mine[-1][1]
        return regime if regime in (LAND_REGIME_WORKER, LAND_REGIME_CONTROLLER) \
            else LAND_REGIME_WORKER
    except Exception:   # noqa: BLE001 — a reminder NEVER fails; canon is the fail-safe answer
        return LAND_REGIME_WORKER


def _brief_file_path(log_path) -> "Path":
    """The composed brief's file, written BESIDE the launch log (PURE path derivation).

    Same stem as the log, so the `bg_dispatch_launched` row's `log` and `brief` locators are visibly
    one pair and the row resolves to the EXACT text the worker read."""
    return Path(str(log_path)[:-4] + ".brief.md") if str(log_path).endswith(".log") \
        else Path(str(log_path) + ".brief.md")


def _compose_worker_brief(brief: str, journal_tail: "str | None" = None,
                          preamble: "str | None" = None,
                          resume_head: "str | None" = None) -> str:
    """PREPEND the standing DISPATCH_WORKER_PREAMBLE to a dispatched worker's brief (T-0622), so a
    headless one-shot worker is told the synchronous-to-LAND + subagent-role discipline UPFRONT
    regardless of what the controller's brief says — a hand-omitted brief still carries it. PURE: the
    testable core of the inject-the-preamble guarantee (AC2). The preamble LEADS so the worker reads
    the discipline before the task-specific instructions.

    T-10578 (X-0429): `journal_tail`, when a re-dispatched task has prior lifecycle recorded in the
    journal, is APPENDED AFTER the controller's brief — the JOURNAL-verified last audit verdicts +
    consult verdict + any deliberate task_paused reason for that id. It carries what the journal
    actually recorded (not a controller-memory premise), so a brief asserting a clean post-land
    orphan can no longer overwrite an audit-post RED / an owner-wait pause. Empty/None → nothing
    appended (a first dispatch has no prior state to verify), so this stays one composition seam.

    T-10710 (X-0561): `preamble`, when given, is the TARGET-RENDERED preamble (a consumer dispatch
    renders the engine-resolved `-C` session-start cue). Omitted/None → the module-level ENGINE text,
    so every existing caller and its assertions are unchanged.

    T-12304: `resume_head`, when given (a `dispatch --resume` relaunch), is the recorded resume
    contract, and it is the FIRST block of the TASK-SPECIFIC brief — i.e. the composed order is
    exactly `preamble + contract + delta`. The standing DISPATCH_WORKER_PREAMBLE KEEPS position 0:
    T-0622/SPEC-0103 guarantee a headless worker reads the execution discipline before ANY
    task-specific text, and displacing it is out of this seam's scope. Threading the head as a NAMED
    argument (rather than letting the caller pre-concatenate it onto `brief`) is what makes the order
    ONE named seam that a test can assert exactly. Omitted/None → byte-identical to every prior
    composition."""
    if resume_head:
        brief = f"{resume_head}\n{brief}" if brief else resume_head
    composed = f"{preamble or DISPATCH_WORKER_PREAMBLE}\n{brief}"
    if journal_tail:
        composed = f"{composed}\n{journal_tail}"
    return composed


# T-10578 (X-0429) — the JOURNAL-derived re-dispatch state fold + render. A re-dispatch brief must be
# JOURNAL-VERIFIED, never composed from controller memory: the <project> incident shipped a brief that
# asserted a clean post-land orphan needing a mechanical tail (audit-post + close + land), while the
# journal carried audit-post RED (3 findings) + a rung-2 consult RED + a deliberate task_paused(owner-
# wait) on an AUTHORITY-class SPEC-0191 §5 scope decision. Following the brief would have laundered the
# owner gate. These two PURE helpers (peers of _compose_worker_brief) fold the per-id journal tail and
# render it; report-only, no store, no FSM (SPEC-0133 §6 read-contract). The verdicts + pause come from
# the SAME _dispatch_status_events fold cmd_dispatch already reads (Principle 1 — no new reader).
_REDISPATCH_AUDIT_TYPES = ("audit_pre_completed", "audit_post_completed")
# Progress events that, when they POST-DATE a live pause record, contradict a next_action that assumed
# the worker stopped there (the <project> pause said "unlanded, worktree intact"; the worker then
# LANDED + died). Their presence after the pause ts is the stale-pause signal (scope b).
_REDISPATCH_PROGRESS_TYPES = ("commit_landed", "land_completed", "task_closed",
                              "audit_pre_completed", "audit_post_completed",
                              "external_audit_completed")


def _journal_redispatch_state(task_id: str, events: "list") -> "dict | None":
    """Derive the per-id lifecycle tail a re-dispatch brief must carry, from the JOURNAL (never
    controller memory). `events` is the ts-ASCENDING per-id event list (the _dispatch_status_events
    reader's output). Returns a dict, or None when the id has NO re-dispatch-relevant history (a
    first dispatch — nothing to verify, so no tail is appended). Report-only: reads, never mutates.

    Fields (each None when absent):
      last_audit_pre / last_audit_post : {verdict, ts, commit, findings} of the NEWEST of each
      last_consult   : {verdict, ts} of the newest audit_worker_auto_consult_granted
      pause          : {reason, next_action, stage, ts} of the newest task_paused NOT superseded by a
                       LATER task_resumed (a still-live deliberate pause), else None
      stale_pause    : True when `pause` is live BUT a _REDISPATCH_PROGRESS_TYPES event post-dates it
                       (its next_action is contradicted by the journal — report-only, scope b)
      halt           : the newest `bg_dispatch_halted` for the id, read through the ONE shared
                       predicate `journal._halt_resolution` (T-10771 / SPEC-0133 rule 2d) — so the
                       brief and `--fleet-verdict` can never disagree about the same halt — else None
                       when the id never halted. `halt["resolved"]` says whether the journal records
                       that halt's own cause as CLEARED; fail-closed, so anything unproven reads LIVE.

    FAIL-OPEN: a malformed event row is skipped, never fabricates a verdict/pause.

    T-10771 — `events` is now the UNSCOPED stream (`_redispatch_events`), because the resolved-halt
    predicate's LAND arm matches `land_completed` BY BRANCH (that event carries no task_id). Every
    task-keyed half below therefore filters on `_dispatch_task_of(e) == task_id` explicitly rather than
    trusting the caller's scoping — otherwise a SIBLING task's audit verdict or pause would be reported
    as THIS id's prior state, which is exactly the controller-memory-over-journal defect (X-0429) this
    block exists to prevent.

    T-10627 — WHY A TAIL-POSITIVE `events` IS EXACT HERE. The caller reads tail-first
    (`_inflight_events`), so on a POSITIVE `events` is the 24h suffix that CONTAINS the newest
    `bg_dispatch_launched`. This fold's SUBJECT is the PRIOR DISPATCH's lifecycle, whose lower bound
    IS that launch row — so every event this fold can legitimately report sits at/after it and is
    present, exactly as in `_classify_dispatch`'s newest-launch segmentation (T-10095). The only rows
    a suffix drops are PRE-launch ones, i.e. an older attempt the prior dispatch already superseded —
    which a "newest of each" fold would not report anyway. On a NEGATIVE the reader re-reads FULL, so
    a prior lifecycle below the cutoff is never silently dropped (the fail-open direction this block
    exists to close)."""
    last_pre = last_post = last_consult = None
    last_pause = last_resumed_ts = None
    progress_after = []
    # T-10771 — the id's OWN rows, taken off a possibly-UNSCOPED stream (see the docstring). One
    # filtered list feeds every task-keyed half below AND the stale-pause scan, so no half can drift
    # onto a sibling task's events.
    own = [e for e in (events or [])
           if isinstance(e, dict) and journal._dispatch_task_of(e) == task_id]
    for e in own:
        if not isinstance(e, dict):
            continue
        etype = e.get("type")
        data = e.get("data") if isinstance(e.get("data"), dict) else {}
        ts = e.get("ts") or ""
        if etype == "audit_pre_completed":
            last_pre = {"verdict": data.get("verdict"), "ts": ts,
                        "commit": data.get("commit"), "findings": data.get("findings_count")}
        elif etype == "audit_post_completed":
            last_post = {"verdict": data.get("verdict"), "ts": ts,
                         "commit": data.get("commit"), "findings": data.get("findings_count")}
        elif etype == "audit_worker_auto_consult_granted":
            last_consult = {"verdict": data.get("verdict"), "ts": ts}
        elif etype == "task_paused":
            last_pause = {"reason": data.get("reason"), "next_action": data.get("next_action"),
                          "stage": data.get("stage"), "ts": ts}
        elif etype == "task_resumed":
            last_resumed_ts = ts
    # T-10771 — the halt half, through the ONE shared predicate (never a second implementation): the
    # brief and `--fleet-verdict` read the SAME function over the SAME facts. Passed the full `events`
    # (not `own`) because the predicate's LAND arm matches by branch, not by task id.
    halt = journal._halt_resolution(events or [], task_id)
    if not (last_pre or last_post or last_consult or last_pause or halt):
        return None   # first dispatch — no prior lifecycle to verify
    # A pause is LIVE only when no task_resumed post-dates it (events are ts-ascending, so compare ts).
    pause = last_pause
    if pause and last_resumed_ts and last_resumed_ts >= (pause.get("ts") or ""):
        pause = None
    stale_pause = False
    if pause:
        pts = pause.get("ts") or ""
        stale_pause = any(
            e.get("type") in _REDISPATCH_PROGRESS_TYPES and (e.get("ts") or "") > pts
            for e in own)
    return {"last_audit_pre": last_pre, "last_audit_post": last_post, "last_consult": last_consult,
            "pause": pause, "stale_pause": stale_pause, "halt": halt}


def _compose_redispatch_state_block(state: "dict | None") -> str:
    """Render the JOURNAL-verified per-id state (from `_journal_redispatch_state`) as the text block
    appended to a re-dispatched worker's brief. Returns "" when there is nothing to carry (None state
    → first dispatch). PURE. Trust-the-journal framing so the worker weighs THESE verdicts over any
    brief prose (T-10578 / X-0429)."""
    if not state:
        return ""
    lines = [
        "=== JOURNAL-VERIFIED PRIOR STATE (T-10578 / X-0429) — this task has a prior lifecycle recorded "
        "in the journal ===",
        "This re-dispatch state is derived from the JOURNAL, NOT controller memory. Trust THESE verdicts "
        "over any brief prose: if a verdict below is RED or a pause is live, this is NOT a clean "
        "post-land orphan awaiting a mechanical tail — re-derive state from the journal before acting.",
    ]

    def _audit_line(label, a):
        if not a:
            return None
        parts = [f"  {label}: {a.get('verdict') or '?'}"]
        if a.get("commit"):
            parts.append(f"commit {a.get('commit')}")
        fc = a.get("findings")
        if fc:
            parts.append(f"{fc} finding(s)")
        if a.get("ts"):
            parts.append(f"@ {a.get('ts')}")
        return " | ".join(parts)

    for label, a in (("last audit-pre ", state.get("last_audit_pre")),
                     ("last audit-post", state.get("last_audit_post"))):
        ln = _audit_line(label, a)
        if ln:
            lines.append(ln)
    c = state.get("last_consult")
    if c:
        lines.append(f"  last consult: {c.get('verdict') or '?'}"
                     + (f" @ {c.get('ts')}" if c.get("ts") else ""))
    pause = state.get("pause")
    if pause:
        lines.append(f"  DELIBERATE PAUSE (task_paused, reason={pause.get('reason') or '?'}) "
                     f"@ {pause.get('ts') or '?'}")
        lines.append(f"    stage: {pause.get('stage') or '?'} | next_action: "
                     f"{pause.get('next_action') or '(none recorded)'}")
        lines.append("    This is a task PAUSED awaiting a decision — NOT a post-land orphan. Do NOT "
                     "close an unmet AC or amend a scope decision yourself (SPEC-0191 §5 authority gate).")
        if state.get("stale_pause"):
            lines.append("    STALE-PAUSE ADVISORY (report-only, no gate): LATER journal events for "
                         "this id post-date this pause record and contradict its next_action — the "
                         "pause facts may be out of date; re-derive state from the journal before acting.")
    # T-10771 (SPEC-0133 rule 2d) — the SELF-HALT half, given the same treatment the stale-pause
    # advisory above already gets: the halt is always NAMED, and the journal decides whether it reads
    # LIVE or RESOLVED. Fail-closed — a halt whose resolution is not positively recorded reads LIVE, so
    # the worse error (a live owner-gated block presented as settled) cannot be made here.
    halt = state.get("halt")
    if halt:
        lines.append(f"  SELF-HALT (bg_dispatch_halted) @ {halt.get('halt_ts') or '?'}: "
                     f"{halt.get('reason') or '(no reason recorded)'}")
        if halt.get("resolved"):
            # T-12273 — the SECOND copy of this branch chain is DELETED. It had drifted from the
            # fleet-verdict one and shared its defect: no branch for arm (iv) (`card-disposed:*`), so a
            # disposed card's halt was narrated as a consult continuation with `@ None` timestamps.
            # `journal._halt_resolution_how` is now the ONE narrator for both readers, the exact
            # analogue of SPEC-0133 rule 2d's "ONE predicate, BOTH readers".
            how = journal._halt_resolution_how(halt)
            lines.append(f"    RESOLVED-HALT ADVISORY (report-only, no gate): LATER journal events for "
                         f"this id record this halt's own cause as CLEARED — {how}. Do NOT read it as "
                         f"an open owner-gated block or re-escalate it; it is prior state, already "
                         f"settled.")
        else:
            lines.append("    This halt has NO recorded resolution in the journal — treat it as LIVE "
                         "prior state: the named blocker must be resolved (or the owner decision "
                         "taken) before this task can proceed. Re-dispatching as-is reproduces it.")
    lines.append("=== END JOURNAL-VERIFIED PRIOR STATE ===")
    return "\n".join(lines)


# The MANDATORY arm-a-watcher cue the launcher prints AFTER a successful launch (T-0620). It makes the
# controller's §Watcher obligation UNFORGETTABLE at the dispatch chokepoint (D-0033 extend the before-X
# verb output; D-0050 verbs are the control surface). The RULE (abstract) is homed in
# patterns/background-session-monitoring.md §Watcher; this text is the executable how-to that realizes it.
#
# T-10347 — the cue used to print a HAND-ROLLED `while :; do ... sleep 300; done` shell snippet, leaving
# every controller to re-implement the tick, the >=2-tick confirmation and the terminal check by hand.
# Two 2026-07-09 incidents came out of exactly that (a false ALL_TERMINAL read off a grep's ABSENCE; a
# premature `blocked` acted on from one transient snapshot). The snippet is RETIRED (CHARTER §P1 F3) in
# favour of the blessed `dispatch --watch` verb, which encodes both rules. What survives here is the
# OBLIGATION + the token contract; the loop itself is now code, not prose a controller re-derives under
# load. Backgrounding the verb and keying off its `WATCH:` token stays the PROVIDER-BOUND bit (CHARTER
# §P4b — the re-invoke-on-exit is a harness capability the provider-neutral CLI cannot itself perform).
#
# The CLASS VOCABULARY block is RENDERED from `journal.DISPATCH_CLASS_VOCAB` (T-10253), never restated
# here: the cue used to name only the recovery-bearing subset, so a controller asking «did THIS dispatch
# halt?» learned from neither this cue nor `journal query --help` that the verb covers it, and hand-rolled
# the raw-journal grep this very cue forbids (E-0001; withdrawn X-0245).
def _dispatch_outcome_token(outcomes: "list") -> str:
    """Render the LAUNCH-mode terminal token from the ORDERED per-task outcome record (T-11844).
    It is the final stdout line of the LAUNCH PHASE: by default the same invocation then continues
    into its own watch and ends on the `WATCH:` token (T-12637); only `--no-self-arm-watch` makes it
    the final line of the whole invocation.

    `outcomes` is `[(task_id, kind, expected_session_ref_or_None)]` in invocation order, kind one of
    `launched` / `skipped` / `refused`. The verdict is that kind uppercased when every id agrees,
    else `MIXED` — so a LIST invocation with one launched and one skipped stays readable from this
    ONE line. Every id that reached an outcome is rendered, each launched one with its expected
    session_ref (the same ref its `bg_dispatch_launched` row carries).

    Wave-level fail-closed preflight refusals are NOT rendered here: they `_die` on stderr and exit
    before any token prints, which is exactly why the documented wrapper rule is capture `2>&1` and
    match `^(DISPATCH:|yitc-v2:)` (the T-11011 land rule, mirrored).
    """
    # T-12681 (X-1479): a SKIPPED / REFUSED fragment carries the guard's journaled `reason` in the
    # third slot (the same string its `bg_dispatch_skipped` row carries), rendered as
    # `<id>=skipped(reason=in-flight)` — the skip's own fragment, shaped like the launched one, so a
    # reader of the token alone sees WHY the id did not launch. Composed after that row's append
    # returned, exactly as a launched fragment is (the T-11844 ordering: fragment implies row).
    frags = [f"{task}=launched(expected={third})" if kind == "launched"
             else (f"{task}={kind}(reason={third})" if third else f"{task}={kind}")
             for task, kind, third in outcomes]
    kinds = {k for _t, k, _e in outcomes}
    verdict = kinds.pop().upper() if len(kinds) == 1 else "MIXED"
    return f"DISPATCH: {verdict} " + "; ".join(frags)


DISPATCH_WATCHER_CUE = """\
ARM A WATCHER (MANDATORY — controller duty, system-driven detection per §Watcher):
  Detection of completion / stall / blocked-on-land MUST be system-driven, NOT human-prompted. Before
  moving on, ARM the blessed watcher over the ids you just dispatched — do NOT hand-roll a poll loop,
  and do NOT wait to be re-prompted. Run it under the harness Monitor primitive (the persistent
  watch-until-condition wrapper §Watcher names — NOT a plain background job, which can be SWEPT before
  it reports a single line, silently leaving you with no monitor), and key off its terminal token:

    bin/yitc-v2 dispatch --watch --task T-XXXX [--task T-YYYY ...]

  It polls the §6-safe readers every `--watch-interval` (default """ + str(journal.WATCH_POLL_INTERVAL_SECS) + """s poll, <=5 min recurring-cadence ceiling per §Watcher regardless of the default, """ + str(journal.WATCH_MAX_RUNTIME_SECS) + """s max runtime per §Watcher — the sanctioned observability constants, journal.WATCH_POLL_INTERVAL_SECS / journal.WATCH_MAX_RUNTIME_SECS) and EXITS with
  a contracted terminal-status token as its FINAL stdout line — match `^WATCH: (WAKE|ALL_TERMINAL|TIMEOUT)\\b`
  (case-sensitive) and parse THAT, never the shell exit and never a free-text grep (the `LAND:` token
  contract, T-0269). Your harness's completion notification IS the re-invoke: the verb exits, you wake,
  you decide — but key ALL recovery off the JOURNAL (`journal query --fleet-verdict` /
  `--dispatch-status --json`, re-derivable at any tick), NEVER off the wrapper's process lifetime; a
  wrapper that dies costs a re-arm, not the fleet's state. It LAUNCHES NOTHING and never consumes stdin.

    WATCH: WAKE ...          an actionable verdict (dead / needs-decision) OF A WATCHED TASK, CONFIRMED
                             across >=2 ticks, or every dispatch TERMINAL with a recovery-bearing detail
                             (halt / wont-do / blocked_on_land / a PAUSED card). A watched card reading
                             `paused(<reason>)` is over but never a clean completion (SPEC-0133 rule 5d):
                             it turns the all-terminal exit into WAKE and never exits ANY_TERMINAL. An
                             `artifact-wait` pause waits on the artifact its card declares
                             (`paused_awaits`), not on a decision; any other pause waits on the
                             decision its reason names. YOU choose the act — the verb prescribes
                             none (SPEC-0133 rule 2). A confirmed-dead `closed_pending_land` (built+closed,
                             land lost to a turn-yield) is recovered by the governed `bin/yitc-v2 worktree
                             recover-land --task T-XXXX` (T-10139 — fail-closed + idempotent; the
                             §Abnormal doctrine home carries the gate).
    WATCH: ALL_TERMINAL ...  every watched task reads a POSITIVE class=TERMINAL(done). Terminal is proven
                             off the parsed class token, NEVER off a task's absence from a report.
    WATCH: ANY_TERMINAL ...  [--watch-any-terminal ONLY] ONE watched task reads a POSITIVE
                             class=TERMINAL(done) while siblings still work — the token NAMES it, so
                             an N-slot queue refills that ONE slot instead of waiting for the wave.
    WATCH: TIMEOUT ...       the window elapsed with no wake condition — re-arm.

  RUNNING AN N-SLOT REFILL QUEUE? Pass `--watch-any-terminal` (T-11829). By DEFAULT one sibling
  finishing never ends the watch, which means «refill as each worker lands» could only be expressed by
  one single-task watcher process per worker, hand-re-armed after every land. The flag makes the ONE
  watcher exit `WATCH: ANY_TERMINAL` (rc 3) naming the finished task; it still prints the WHOLE fleet,
  so you re-arm over the survivors. Unflagged, the exit contract is exactly as it has always been.

  A `working` heartbeat never wakes you, and one sibling finishing never ends the watch (T-0680): the
  verb re-derives EVERY in-flight worker each tick (SPEC-0133 §3 — so a worker that DIES WHILE ALREADY
  STUCK is still caught), and prints the whole fleet when it wakes.

  IT WAKES TO THE TASKS YOU ARMED IT OVER (T-10402). An actionable verdict from a worker OUTSIDE your
  --task set does NOT wake you — that is another watcher's business (a foreign verdict used to burn the
  batch monitor + a controller turn: 7 phantom wakes on 2026-07-11). Out-of-scope actionable rows are
  still COUNTED on the tick line, never silently dropped, so you can see the wider fleet needs someone.
  Pass `--watch-fleet` to opt IN to fleet-wide waking. Scope governs only what may WAKE you: a wake
  still prints the WHOLE fleet either way, so siblings are never abandoned.

  CLASS VOCABULARY — the COMPLETE set either reader can emit (single carrier: journal.DISPATCH_CLASS_VOCAB;
  `journal query --help` renders this same list, so the two can never diverge):
""" + journal.dispatch_class_vocab_block("    ") + """
  `journal query --fleet-verdict` is the heartbeat read the watcher runs for you (per in-flight worker:
  class + evidence + verdict{alive|dead|needs-decision} + verdict_basis); `journal query --dispatch-status
  [--task T-XXXX]` is the class-only inspector for a spot-check. Running either by hand is the ad-hoc
  fallback, not the primary path — and a grep of raw journal lines mis-reads healthy workers as
  actionable (SPEC-0133 §5 F4)."""


# ── The blessed controller WATCHER (T-10347) ──────────────────────────────────────────────────────
# `dispatch --watch` mechanizes the NON-SKIPPABLE §Watcher obligation (T-0620,
# patterns/background-session-monitoring.md) that every controller previously HAND-ROLLED as a shell
# poll loop. Two incidents on 2026-07-09 came straight out of that hand-rolling: a false ALL_TERMINAL
# inferred from a task's ABSENCE from a grep, and a premature `blocked` acted on from ONE transient
# snapshot. The watcher answers both structurally — terminal is proven POSITIVELY off a parsed `class`
# token, and an actionable verdict must repeat across >=2 consecutive ticks before it wakes anyone.
#
# §6 POSTURE (CHARTER §Principle 6 named retirements; SPEC-0133 rule 1). The watcher is a READ-ONLY
# POLL that re-invokes the controller by EXITING with a contracted token — the harness's existing
# background-completion notification is the re-invoke, so the CLI performs no provider-specific act
# (CHARTER §P4b). It is NOT a scheduler, queue-state machine, cap, auto-adopt, liveness-arming FSM, or
# auto-relaunch. It never mutates a process / task / git / worktree, never kills / adopts / lands /
# respawns, never picks or orders a task, and NEVER persists state across invocations. The verdict verb
# it consumes (`journal query --fleet-verdict`) stays pure — the loop lives out here, in the CALLER, so
# rule 1's "no wait/sleep/loop" bound on the observability verb is untouched.
#
# The consecutive-tick counters are LOCAL MEMORY for the duration of ONE invocation, never written to
# disk and never read back. That is not a state store: SPEC-0133 rule 1 forbids persisting state ACROSS
# invocations, and §Recovery-trigger (b) MANDATES the >=2-tick confirm the counters implement.
WATCH_TOKEN_RE = r"^WATCH: (WAKE|ALL_TERMINAL|ANY_TERMINAL|TIMEOUT)\b"

# The verdicts that mean «a human decision is needed» (SPEC-0133 rule 2). `alive` is never actionable.
_WATCH_ACTIONABLE_VERDICTS = frozenset({"dead", "needs-decision"})
# The ONE dispatch-status detail that means a terminal dispatch ended CLEANLY. Every other terminal
# detail (halt / wont-do / blocked_on_land(needs-controller|needs-owner)) is recovery-bearing — see _watch_wake_decision.
_WATCH_CLEAN_TERMINAL_DETAIL = "done"
# Streak-key namespacing. A per-verdict key is `<session_ref>\x00<verdict>`; the all-terminal counter
# gets its OWN key with no separator, so the per-tick "reset every verdict not re-observed" sweep (which
# would otherwise delete it every tick — it is never a `seen_now` member) skips it by construction.
_WATCH_VERDICT_KEY_SEP = "\x00"
_WATCH_ALL_TERMINAL_KEY = "all_terminal"
# T-11829 — the OPT-IN per-worker terminality streak keys (`--watch-any-terminal`). One key per
# watched task, namespaced by this prefix so it is neither a verdict key (no `_WATCH_VERDICT_KEY_SEP`,
# so the per-tick verdict sweep never touches it) nor the all-terminal counter. Its own sweep lives in
# `_watch_wake_decision`: a task that stops reading TERMINAL has its key DELETED, so the confirmation
# decays exactly like a settled verdict rather than accumulating across a flap.
_WATCH_ANY_TERMINAL_KEY_PREFIX = "any_terminal:"

# ── T-11578: a WATCHER's lifetime is decoupled from whatever launched it ──────────────────────────
# THE CLASS, and why it is not a new one. A backgrounded `dispatch --watch` was SWEPT by the provider
# harness twice in a row (<project> X-1103, 2026-08-25) — both wrapper tasks reported KILLED, not
# completed — while every worker it watched stayed alive and healthy. That is the SAME topology defect
# T-11489 closed for `land`: the watcher shared the launching shell's PROCESS GROUP, and the harness
# kill is group-directed. It is also the same FAILURE MODE OF THE REMEDY: `--help` already recommends
# running the watcher under the harness Monitor primitive, and that recommendation was correct — but
# it held only while every operator picked the right wrapper, and picking wrong failed SILENTLY.
#
# So the answer is the settled one, applied to its second caller: leave the caller's process group at
# entry, before the poll loop blocks. A swept, timed-out or NEVER-ARMED wrapper then costs a RE-ARM
# and nothing else. Monitor stays RECOMMENDED — but as ergonomics (you still want to SEE the token),
# not as the thing standing between the operator and a destroyed watch.
#
# WHY A SECOND KNOB RATHER THAN LAND'S. `YITC_LAND_KEEP_PROCESS_GROUP` would be a lie in the name here,
# and one variable silently governing two unrelated processes is a surprise nobody predicts from
# reading it. The MECHANISM is shared (`worktree._escape_observer_process_group` — one implementation,
# two callers, CHARTER §P1 F1); only the opt-out NAME is per-observer.
#
# THE TOKEN CONTRACT IS UNCHANGED, deliberately. This moves PROCESS-GROUP MEMBERSHIP and nothing else:
# no stdout, exit code, poll cadence or wake policy moves, so `^WATCH: (WAKE|ALL_TERMINAL|TIMEOUT)`
# stays byte-identical. And the recovery an orphaned-but-alive watcher needs ALREADY EXISTS one layer
# down — T-11370's `watch_verdict_recorded` row is emitted BEFORE the token print for exactly the
# lost-stdout case. A second token contract would duplicate a shipped recovery path.
_WATCH_KEEP_PROCESS_GROUP_ENV = "YITC_WATCH_KEEP_PROCESS_GROUP"
_WATCH_ESCAPE_EVENT = "watch_process_group_escaped"
_WATCH_ARMED_EVENT = "watch_armed"


def _watch_arming_reachability(_self_fd1="/proc/self/fd/1", _ppid_fd1=None, _getppid=None,
                               _stat=None, _readlink=None):
    """Can THIS watcher's exit reach the caller that armed it? PURE, INJECTED, NEVER RAISES (T-12641).

    ATTESTS ONLY A NEGATIVE, because only a negative is provable (audit-pre pass-1 F2):

      `unreachable`  PROVEN. Our stdout is NOT our caller's stdout — a redirect AWAY from the caller's
                     own output stream, the measured `dispatch --watch ... > log 2>&1 &` form. Whatever
                     reads the caller can therefore never see our `WATCH:` token, so our exit
                     re-invokes nobody: the watcher polls correctly, writes a healthy WAKE, and nothing
                     reads it (X-1440 — all 21 armings of one session).
      `unproven`     EVERYTHING ELSE, carrying the observed `detail` and NEVER a delivery attestation.
                     `dispatch --watch ... &` with no redirect INHERITS the caller's stdout and is
                     still orphaned, so nothing here is ever called "delivering".

    WHY THIS DISCRIMINATOR AND NOT THE TWO OBVIOUS ONES (both measured on this host before designing):
    fd TYPE is useless — stdout is a REGULAR FILE in the harness background form, the foreground form
    AND the orphaned form alike. REPARENTING is useless — the launching shell survives in BOTH forms,
    so `getppid()` stays non-1 for the whole window and a reparent check would read every arming as
    delivering. Stream IDENTITY is the one thing that moves with the actual causal story.

    Identity is (st_dev, st_ino) of our fd1 vs the caller's, falling back to readlink paths normalized
    for a trailing " (deleted)" when either stat fails — the measured orphaned case has exactly that
    deleted-caller-stream shape, so the fallback is load-bearing rather than decoration. EVERY failure
    to read returns `unproven`: the verb can never call an arming good on the strength of a failed read.

    Returns (reachability, detail, why).
    """
    _stat = _stat or os.stat
    _readlink = _readlink or os.readlink
    _getppid = _getppid or os.getppid
    try:
        ppid = _getppid()
        ppid_fd1 = _ppid_fd1 if _ppid_fd1 is not None else f"/proc/{ppid}/fd/1"
    except Exception:                                    # noqa: BLE001 — never raises, never accuses
        return ("unproven", "undeterminable", "the caller's stdout could not be located")

    def _ident(path):
        try:
            st = _stat(path)
            return ("stat", st.st_dev, st.st_ino)
        except Exception:                                # noqa: BLE001
            pass
        try:
            target = _readlink(path)
        except Exception:                                # noqa: BLE001
            return None
        if target.endswith(" (deleted)"):
            target = target[: -len(" (deleted)")]
        return ("path", target)

    ours, theirs = _ident(_self_fd1), _ident(ppid_fd1)
    if ours is None or theirs is None:
        return ("unproven", "undeterminable",
                "our stdout or the caller's could not be read, so nothing is proven either way")
    if ours == theirs:
        return ("unproven", "inherited",
                "our stdout IS the caller's stdout; that is necessary for delivery but not "
                "sufficient — a plain `&` background job inherits it and is still orphaned")
    # Our stdout DIFFERS from the caller's. That alone proves nothing: the one shape we can prove
    # unreachable is a REGULAR FILE — the measured `> log 2>&1 &` redirect, a sink with no reader at
    # all. Everything else that differs has, or may have, a reader who could relay to the caller: a
    # FIFO or tty has one by construction, and a socket / block device / directory / anything else is
    # a descriptor kind we have not reasoned about. So this returns `unreachable` only on a POSITIVE
    # S_ISREG proof and `unproven` on every other kind — INCLUDING a stat we could not read at all.
    # Inferring "regular file" by EXCLUDING the two kinds we happened to name would call a Unix-domain
    # socket unreachable on no evidence (audit-post pass 1, AC2/high), which is precisely the
    # "never call an arming good, and never accuse one without proof" asymmetry this function exists
    # to hold.
    try:
        import stat as _statmod                          # noqa: PLC0415 — lazy, leaf-module hygiene
        mode = _stat(_self_fd1).st_mode
    except Exception:                                    # noqa: BLE001
        return ("unproven", "undeterminable",
                "our stdout differs from the caller's, but its kind could not be read — a difference "
                "alone proves nothing, so nothing is proven")
    if _statmod.S_ISFIFO(mode):
        detail = "piped"
    elif _statmod.S_ISCHR(mode):
        detail = "tty"
    elif _statmod.S_ISREG(mode):
        detail = "redirected"
    else:
        detail = "other"
    if detail != "redirected":
        return ("unproven", detail,
                f"our stdout differs from the caller's and is a {detail} descriptor — whoever reads "
                f"it may or may not relay to the caller, so nothing is proven")
    return ("unreachable", detail,
            "our stdout is redirected AWAY from the caller's own output stream into a regular file, "
            "so whatever reads the caller can never see this watcher's `WATCH:` token and its exit "
            "re-invokes nobody")


def _write_to_caller_stdout(text: str, _ppid_fd1=None, _getppid=None) -> bool:
    """Best-effort write into the CALLER's OWN still-open stdout. NEVER raises (T-12641).

    The auditor's own fix for the residual: a banner on the redirected watcher's stderr lands in the
    very log the Controller does not read. MEASURED on this host 2026-09-16 in the exact orphaned form
    `cmd > log 2>&1 &` — the text lands in the caller's visible foreground output window while the
    child's own stdout+stderr go to the dead log. It must be the FIRST action of the watch branch: the
    caller's window closes when the foreground call returns, and a write placed after the journal I/O
    loses that race (measured: nothing appeared).

    BOUND, stated rather than assumed: a caller that has ALREADY returned is unreachable, which is what
    the durable backstop exists for. Returns True iff the bytes were written.
    """
    try:
        ppid = (_getppid or os.getppid)()
        target = _ppid_fd1 if _ppid_fd1 is not None else f"/proc/{ppid}/fd/1"
        try:                        # never echo into our OWN fd1 — that is the log, not the caller
            if os.stat(target).st_ino == os.stat("/proc/self/fd/1").st_ino:
                return False
        except Exception:                                # noqa: BLE001
            pass
        fd = os.open(target, os.O_WRONLY | os.O_NONBLOCK)
        try:
            os.write(fd, text.encode())
        finally:
            os.close(fd)
        return True
    except Exception:                                    # noqa: BLE001 — best-effort by contract
        return False


def _watch_unreachable_banner(detail: str, why: str) -> str:
    """The loud arm-time text, one home, used on every channel (CHARTER §P1 F1)."""
    return (f"\n{'!' * 78}\n"
            f"!! dispatch --watch: THIS ARMING CANNOT REACH YOU (reachability=unreachable, "
            f"detail={detail}).\n"
            f"!! {why}\n"
            f"!! The watcher WILL poll correctly and WILL write its `WATCH:` token — to a log nothing "
            f"reads.\n"
            f"!! RE-ARM IT under the harness's own background primitive, whose EXIT re-invokes you.\n"
            f"!! This arming is recorded `{_WATCH_ARMED_EVENT}(reachability=unreachable)` and is "
            f"WITHHELD from\n"
            f"!! the monitoring credit, so it stays on the unmonitored-dispatch debt line (SPEC-0119 "
            f"rule 12).\n"
            f"{'!' * 78}\n")


def _watch_row_in_scope(row: dict, watched: "set[str]", watch_fleet: bool) -> bool:
    """Is this fleet-verdict row THIS watcher's business? (T-10402)

    A watcher armed over `--task T-A,T-B` answers for T-A and T-B. A row is in scope iff it holds at
    least one WATCHED task — an INTERSECTION, never an equality: a row is worker-centric (SPEC-0133
    rule 4 — `task_ids` is the warm worker's DRAIN SEQUENCE), so a worker draining T-A then T-C must
    still wake a watcher over T-A.

    FAIL-CLOSED on an unattributable row (empty / absent / non-list `task_ids`): under the default it
    is NOT in scope, so it cannot wake. That judgement belongs HERE, at the watcher's use site — the
    reader that knows the watched set — never in the `--fleet-verdict` parser, which stays faithful and
    fleet-wide by design (SPEC-0133 rule 3, the heartbeat that re-derives EVERY in-flight worker).
    `lessons/fail-closed-belongs-to-the-reader-not-the-parser`: fail-closed is a property of a use
    site, not of a parse result. A watched task's own death is still proven by the fail-closed per-task
    ALL_TERMINAL leg and bounded by the never-silent TIMEOUT, so scoping loses no signal that is ours.

    `watch_fleet` is the EXPLICIT opt-in that restores fleet-wide waking (never the silent default)."""
    if watch_fleet:
        return True
    task_ids = row.get("task_ids")
    if not isinstance(task_ids, list):
        return False
    return bool(set(task_ids) & watched)


def _watch_wake_decision(rows: "list[dict]", statuses: "dict[str, dict | None]", tasks: "list[str]",
                         confirm: int, streak: "dict[str, int]",
                         watch_fleet: bool = False,
                         any_terminal: bool = False) -> "tuple[str, str]":
    """PURE tick decision (no I/O, no clock, no globals) — the whole watcher policy in one testable
    function. Returns `(action, reason)` with action in {'continue', 'wake', 'all_terminal',
    'any_terminal'} and MUTATES `streak` (the caller-owned in-memory consecutive-tick counters) in
    place. `any_terminal` is the OPT-IN early-exit mode (rule 4 below); OFF, this function's behaviour
    is unchanged for every input.

    `rows` = this tick's `journal query --fleet-verdict --json` records. `statuses` = per watched task,
    its `journal query --dispatch-status --json` record (or None when the read yielded nothing).

    THE FOUR RULES THIS ENCODES, each pinned by a differential test:

    0. WAKE ONLY TO THE WATCHED SET (T-10402). A row is considered at all only if it holds a WATCHED
       task (`_watch_row_in_scope` — intersection, fail-closed). A foreign worker's actionable verdict
       is not this watcher's business: it is dropped BEFORE the streak accumulates, so it cannot even
       build toward `confirm`. Incident: 7 phantom WATCH:WAKE fires on 2026-07-11, every one on a
       synthetic non-watched row while watching real tasks — each burned the batch monitor + a
       controller turn. `watch_fleet` is the EXPLICIT opt-in that restores fleet-wide waking.
       This scopes the WAKE TRIGGER only — the wake-time REPORT stays fleet-wide (rule 3).

    1. WAKE on a CONFIRMED actionable verdict (§Recovery-trigger (b), T-0693). An IN-SCOPE row whose
       `verdict` is `dead` / `needs-decision` increments the streak for its (session_ref, verdict) key;
       a key NOT seen this tick RESETS to 0. Only a streak reaching `confirm` wakes. This is what makes
       a `needs-decision` that settles back to `alive` next tick a non-event — the 2026-07-09 premature
       `blocked` incident acted on exactly such a single transient snapshot. A `working` row carries
       verdict `alive`, so a heartbeat NEVER wakes: without this half the watcher is a busy-loop.

    2. Terminal is proven POSITIVELY, never by absence. ALL_TERMINAL requires that EVERY watched task's
       parsed `class` token == 'TERMINAL' — a task MISSING from `statuses`, or one whose row would not
       parse, counts as NOT-terminal (fail-closed). The 2026-07-09 false ALL_TERMINAL came from reading
       a task's ABSENCE from a grep as "it finished"; absence from `--fleet-verdict` legitimately means
       a worker released its slot, but it equally means the read failed, so it can never prove doneness.

    3. Never abandon siblings (T-0680). Nothing here keys on "a task changed class". ALL_TERMINAL needs
       ALL watched tasks terminal, so task A reaching TERMINAL(done) while B still works CONTINUES the
       watch. A WAKE fires only on an actionable verdict of a WATCHED task (rule 0), and the caller then
       reports EVERY row — the whole fleet, scoped or not — so the controller sees the full picture and
       can re-arm over the remaining workers. Reporting the fleet is DELIBERATE and stays fleet-wide;
       WAKING on it is what rule 0 scopes. The two are different questions: "whose verdict may wake me"
       vs "what do I show once woken".

    4. PER-WORKER TERMINALITY IS AN OPT-IN, never the default (T-11829, SPEC-0133 rule 5c). Rule 3 is
       the DEFAULT contract and stays it: unflagged, one sibling finishing never ends the watch. But an
       N-slot refill queue — «start a replacement AS EACH worker lands, not in waves» — cannot be
       expressed by an all-at-once exit at all, and the workaround was one single-task watcher process
       per worker, hand-re-armed after every land. So `any_terminal=True` adds ONE exit condition: when
       NOT every watched task is terminal but at least one reads a POSITIVE class=TERMINAL across the
       SAME `confirm` ticks, return `any_terminal` naming THAT task (or `wake`, when its detail is
       recovery-bearing — the per-task echo of rule 3's unclean-detail rule). Three bounds hold it to
       WHEN the watcher reports, never WHAT: the actionable-verdict WAKE (rule 1) still runs FIRST and
       wins; terminality is still proven POSITIVELY per rule 2, never by absence; and the caller still
       reports the WHOLE fleet on this exit, so the controller re-arms over the survivors and T-0680 is
       kept, not relaxed. With the flag OFF nothing below fires.

    A terminal fleet whose classes are all TERMINAL but where some `detail` is NOT `done` (a halt, a
    wont-do, either blocked_on_land(...) reading) exits as a WAKE, never a clean ALL_TERMINAL: those details
    are recovery-bearing and a controller must decide on them. This also covers the halt that has aged
    out of the fleet-verdict recency window (SPEC-0133 rule 2a) and so no longer appears in `rows`.
    A `paused(<reason>)` status row (T-12916, SPEC-0133 rule 5d — incl. a pause whose record LANDED) is
    read the same way: positively over, never clean, so it WAKES and never satisfies ANY_TERMINAL.
    T-13575 — the wake TEXT is reason-aware, the action is not: `paused(artifact-wait)` waits on the
    artifact its card declares (`task pause --awaits`), so its wake text names that wait instead of
    asking for a controller decision. Every other detail keeps its text byte for byte."""
    # (0) SCOPE FIRST (T-10402) — a foreign worker's verdict never reaches the streak machinery at all,
    # so it cannot accumulate toward `confirm` (dropping it only at the threshold would still let a
    # long-lived foreign row sit one tick away from waking us).
    watched = set(tasks)
    scoped = [row for row in rows if _watch_row_in_scope(row, watched, watch_fleet)]

    # (1) actionable-verdict streaks — key on (session_ref, verdict), the row identity SPEC-0133 rule 4
    # says is canonical. Reset every key not re-observed this tick BEFORE testing the threshold.
    seen_now = set()
    for row in scoped:
        verdict = row.get("verdict")
        if verdict in _WATCH_ACTIONABLE_VERDICTS:
            key = f"{row.get('session_ref')}{_WATCH_VERDICT_KEY_SEP}{verdict}"
            seen_now.add(key)
            streak[key] = streak.get(key, 0) + 1
    for key in list(streak):
        # Only VERDICT keys are swept here (the all-terminal counter carries no separator): a settled or
        # absent verdict must not accumulate toward `confirm`. An out-of-scope row is never in
        # `seen_now`, so a row that LEAVES scope decays exactly like one that settles back to `alive`.
        if _WATCH_VERDICT_KEY_SEP in key and key not in seen_now:
            del streak[key]
    for row in scoped:
        verdict = row.get("verdict")
        if verdict not in _WATCH_ACTIONABLE_VERDICTS:
            continue
        key = f"{row.get('session_ref')}{_WATCH_VERDICT_KEY_SEP}{verdict}"
        if streak.get(key, 0) >= confirm:
            # T-12304 — a `paused(controller-wait)` row wakes HERE, on its needs-decision verdict, and
            # the line already NAMES the pause reason + the recorded `next_action`: both ride the
            # row's `verdict_basis`, which this reason interpolates verbatim. No second wake path and
            # no per-class wording — the class the controller must route is carried by the basis the
            # fleet-verdict branch composed (CHARTER §P1 F1/F2: an existing carrier, a view, not a
            # new entity).
            return ("wake", f"worker {row.get('session_ref')} verdict={verdict} "
                            f"class={row.get('class')} tasks={','.join(row.get('task_ids') or [])} "
                            f"confirmed across {confirm} consecutive ticks — "
                            f"basis: {row.get('verdict_basis') or '-'}")

    # T-13575 — wording only. An `artifact-wait` pause waits on the artifact its card DECLARES, not on
    # a decision, so the two terminal-leg wakes below name that wait for it. The status row carries the
    # reason and not the awaited ref, and this function reads nothing, so the text names the card
    # field; every other non-clean detail keeps the decision wording unchanged.
    artifact_wait = "paused(artifact-wait)"
    artifact_txt = ("an artifact-wait pause waits on the artifact its card declares (`paused_awaits`), "
                    "not on a decision — relaunch it once that artifact has arrived (the session-start "
                    "echo then reads RESUMABLE)")

    # (2) POSITIVE terminal — every watched task's parsed class token must read TERMINAL. Fail closed on
    # a missing/unparseable row: absence is NOT evidence of completion (the false-ALL_TERMINAL class).
    # The per-task read is collected FIRST (rather than returning at the first non-terminal task) so the
    # opt-in per-worker leg below can see WHICH tasks are terminal; the all-terminal verdict itself is
    # computed from exactly the same predicate as before, so its behaviour is unchanged.
    terminal_details = {}
    for task in tasks:
        row = statuses.get(task)
        if isinstance(row, dict) and row.get("class") == "TERMINAL":
            terminal_details[task] = row.get("detail")
        elif isinstance(row, dict) and row.get("class") == journal.DISPATCH_CLASS_CLOSED_AWAITING_CONTROLLER_LAND:
            # T-12351 — under the CONTROLLER-LANDS regime a worker that stopped after `task close`
            # is the CONTRACTED completion (SPEC-0103 / T-12373), so it reads as a POSITIVE
            # TERMINAL(done) here: the any-terminal leg exits `WATCH: ANY_TERMINAL` naming it and
            # the all-terminal leg counts it clean — never a WAKE. The classifier already withheld
            # this class unless the launch row says `controller` and no land is running, so the
            # worker-regime `closed_pending_land` row is untouched (its fleet verdict still wakes
            # rule (1) above). The owed land is the CONTROLLER's next step, not a decision.
            terminal_details[task] = _WATCH_CLEAN_TERMINAL_DETAIL
        elif isinstance(row, dict) and row.get("class") == "paused":
            # T-12916 (SPEC-0133 rule 5d) — a PAUSED task: the dispatch is over, the task waits on a
            # decision. A POSITIVE reading (rule 2 is untouched — absence still proves nothing), but
            # NEVER a clean completion: its non-clean detail makes the any-terminal leg WAKE instead
            # of exiting ANY_TERMINAL, and an all-terminal fleet holding it wakes unclean.
            terminal_details[task] = f"paused({row.get('detail') or 'unknown'})"
    if not tasks or len(terminal_details) < len(set(tasks)):
        streak.pop(_WATCH_ALL_TERMINAL_KEY, None)
        # (4) OPT-IN per-worker terminality (T-11829). Reached ONLY when the fleet is NOT all-terminal —
        # an all-terminal fleet is answered by the unchanged leg below, which is the more precise
        # verdict. Sweep-then-test, symmetric with the verdict streaks: a task that is not reading
        # TERMINAL this tick loses its key, so a flap decays instead of accumulating toward `confirm`.
        for task in tasks:
            if not any_terminal or task not in terminal_details:
                streak.pop(_WATCH_ANY_TERMINAL_KEY_PREFIX + task, None)
        if not any_terminal:
            return ("continue", "")
        for task in sorted(terminal_details):
            key = _WATCH_ANY_TERMINAL_KEY_PREFIX + task
            streak[key] = streak.get(key, 0) + 1
            if streak[key] < confirm:
                continue
            detail = terminal_details[task]
            still = sorted(t for t in tasks if t not in terminal_details)
            if detail == artifact_wait:
                return ("wake", f"{task}=TERMINAL({detail}) confirmed across {confirm} consecutive "
                                f"ticks — not a clean completion: {artifact_txt}; still "
                                f"working: {', '.join(still) or '-'}")
            if detail != _WATCH_CLEAN_TERMINAL_DETAIL:
                return ("wake", f"{task}=TERMINAL({detail}) confirmed across {confirm} consecutive "
                                f"ticks — recovery-bearing, a controller decision is needed; still "
                                f"working: {', '.join(still) or '-'}")
            return ("any_terminal", f"{task} reads a POSITIVE class=TERMINAL(done) across {confirm} "
                                    f"consecutive ticks (--watch-any-terminal) — its slot is free; "
                                    f"still working: {', '.join(still) or '-'}")
        return ("continue", "")
    # Every watched task is terminal — from here the DEFAULT all-at-once contract runs unchanged, so the
    # per-task counters have served their purpose and are dropped rather than left to grow.
    for task in tasks:
        streak.pop(_WATCH_ANY_TERMINAL_KEY_PREFIX + task, None)
    # Confirm the all-terminal read across ticks too, symmetric with (1) — a snapshot is never acted on.
    streak[_WATCH_ALL_TERMINAL_KEY] = streak.get(_WATCH_ALL_TERMINAL_KEY, 0) + 1
    if streak[_WATCH_ALL_TERMINAL_KEY] < confirm:
        return ("continue", "")
    unclean = {t: d for t, d in terminal_details.items() if d != _WATCH_CLEAN_TERMINAL_DETAIL}
    if unclean:
        detail_txt = ", ".join(f"{t}=TERMINAL({d})" for t, d in sorted(unclean.items()))
        waiting = sorted(t for t, d in unclean.items() if d == artifact_wait)
        if len(waiting) == len(unclean):
            return ("wake", f"all watched dispatches TERMINAL but {detail_txt} — not a clean "
                            f"completion: {artifact_txt}")
        return ("wake", f"all watched dispatches TERMINAL but {detail_txt} — recovery-bearing, "
                        f"a controller decision is needed (not a clean completion)"
                        + (f"; {', '.join(waiting)}: {artifact_txt}" if waiting else ""))
    return ("all_terminal", "every watched task reads a POSITIVE class=TERMINAL(done) "
                            f"across {confirm} consecutive ticks: {', '.join(sorted(tasks))}")


#: T-12986 — how many trailing non-empty log lines the watcher / BOOTSTRAP-DIED surfaces print for a
#: worker that died in its start window (the recorded row keeps the full byte-bounded tail).
_TAIL_PRINT_LINES = 8


def cmd_dispatch_watch(tasks: "list[str]", *, interval: int, timeout: int, confirm: int,
                       _fleet_rows, _status_row, _sleep, _now, _emit, _out=None, _err=None,
                       watch_fleet: bool = False, any_terminal: bool = False,
                       arming_reachability: str = "unproven",
                       _premature_findings=None) -> int:
    """`dispatch --watch` — the blessed controller watcher (T-10347). Polls the §6-safe readers, and on
    a wake condition EXITS, printing a contracted terminal-status token as its FINAL stdout line:

        WATCH: WAKE <reason>          an actionable verdict CONFIRMED, or a recovery-bearing terminal
        WATCH: ALL_TERMINAL <reason>  every watched task positively class=TERMINAL(done)
        WATCH: ANY_TERMINAL <reason>  [--watch-any-terminal ONLY] ONE watched task positively
                                      class=TERMINAL(done) while siblings still work — the token
                                      NAMES that task
        WATCH: TIMEOUT <reason>       the watch window elapsed with no wake condition

    Callers match `^WATCH: (WAKE|ALL_TERMINAL|ANY_TERMINAL|TIMEOUT)\\b` (case-sensitive) and key off
    THAT, not the shell exit — the same machine-readable contract `land` uses for `LAND: OK|ABORT`
    (T-0269), and the reason the card mandates class-token parsing over free-text grep. Exit code is 0
    for ALL_TERMINAL, 1 for WAKE (an actionable state), 2 for TIMEOUT, 3 for ANY_TERMINAL.

    PER-WORKER TERMINALITY IS AN OPT-IN (T-11829, SPEC-0133 rule 5c). `any_terminal=True` (the
    `--watch-any-terminal` flag) is what an N-slot refill queue needs — «report AS EACH worker lands»,
    which the all-at-once ALL_TERMINAL cannot express and which used to cost one wrapper process and one
    manual re-arm PER WORKER. Unflagged, the exit contract is byte-for-byte as before. Either way the
    exit REPORTS the whole fleet (below), so siblings are never abandoned (T-0680): this changes WHEN
    the watcher reports, never WHAT it reports, and never what it may do — it stays read-only.

    LAUNCHES NOTHING AND NEVER CONSUMES STDIN. `cmd_dispatch` branches here BEFORE `_resolve_dispatch_briefs`
    (the single stdin consumer — its single-task stdin fallback), so watch mode structurally never opens
    stdin (audit-pre finding, absorbed mode-(b) in decisions/T-10347-audit-pre.yaml).

    WAKES ONLY TO ITS WATCHED SET (T-10402). An actionable verdict belonging to a worker OUTSIDE the
    `--task` set does NOT wake this watcher — a foreign verdict is another watcher's business (7 phantom
    wakes on 2026-07-11, each burning the batch monitor + a controller turn). `watch_fleet=True` (the
    `--watch-fleet` flag) is the EXPLICIT opt-in restoring fleet-wide waking. The wake-time fleet REPORT
    below stays fleet-wide regardless — sibling safety (T-0680) is about what you SEE once woken, not
    about whose verdict may wake you.

    Every side-effecting dependency is INJECTED (`_fleet_rows`, `_status_row`, `_sleep`, `_now`, `_emit`)
    so the loop is hermetically testable with no subprocess, no clock, and no real sleep. The policy
    itself lives in the pure `_watch_wake_decision`; this function only sequences reads → decide → sleep.
    Read-only throughout: the only writes are journal appends — the two at exit (below): the
    `consumer_read_evidence` adoption receipt, and the `watch_verdict_recorded` DURABLE VERDICT that
    makes the terminal token recoverable from the journal when the wrapper output is lost (T-11370);
    plus, per tick, any `bg_dispatch_halted(kind=premature_exit)` the injected `_premature_findings`
    reader reports (T-11926, SPEC-0133 rule 2f).

    PREMATURE-EXIT RECORDING (T-11926 / X-1208). A dispatched worker that simply STOPS authors no
    terminal, so its death used to surface only as journal staleness and its CAUSE was recoverable
    only by hand-reading the dispatch log. Nothing else can record it: the launcher is fire-and-forget
    and `_spawn_detached_from_caller_tree` (T-11906) reparents the worker onto init, so no waiter
    exists; and `--fleet-verdict` is a pure read that may not emit (rule 1). THIS is the seam — the
    controller's armed observer, which already learns of the death and already appends to the journal.
    Three bounds, all load-bearing:
      - **Still §6-safe (rule 1)**, on rule 5b's own terms: a journal APPEND through the SAME injected
        emitter, never read back by this watcher, with no state crossing invocations. It remembers
        nothing, schedules nothing, and acts on no worker or worktree — it writes down what it saw.
      - **The TRIGGER is scoped, not the VIEW** (`lessons/scope-the-trigger-not-the-view`, T-10402):
        a finding is recorded only for a row in scope by the SAME `_watch_row_in_scope` predicate the
        wake decision uses, so a watcher never writes halts for workers another controller owns.
        `--watch-fleet` widens both together, as it already does for waking.
      - **FAIL-OPEN**, exactly like the exit receipts: a broken append must never swallow the token a
        caller is blocked on, and the recording is an addition, never a gate.
    Idempotence is the PREDICATE's, not this loop's: it returns nothing for a task that already
    carries a halt, so a second tick writes no second row and no per-invocation memo is needed."""
    out = _out or sys.stdout
    err = _err or sys.stderr
    watched = set(tasks)
    streak: "dict[str, int]" = {}       # in-memory, one invocation, never persisted (the §6 bound)
    started, ticks = _now(), 0
    action, reason = "timeout", (f"no wake condition within {timeout}s — reassess the fleet + re-arm "
                                 f"the watcher (never silent, T-10386)")
    while True:
        ticks += 1
        rows = _fleet_rows()
        statuses = {t: _status_row(t) for t in tasks}
        action, reason = _watch_wake_decision(rows, statuses, tasks, confirm, streak, watch_fleet,
                                              any_terminal)
        # A tick summary on STDERR — stdout carries the terminal token alone, so a caller can parse it
        # without stripping progress noise (the `land` heartbeat precedent). The SUPPRESSED count makes
        # the T-10402 scoping VISIBLE: a foreign actionable verdict we declined to wake on is reported,
        # never silently dropped (the never-silent posture, T-10386) — so a controller can still see
        # that the wider fleet needs someone's attention, and re-arm or re-run --fleet-verdict for it.
        actionable = [r for r in rows if r.get("verdict") in _WATCH_ACTIONABLE_VERDICTS]
        in_scope = [r for r in actionable if _watch_row_in_scope(r, watched, watch_fleet)]
        suppressed = len(actionable) - len(in_scope)
        scope_txt = "fleet (--watch-fleet)" if watch_fleet else f"watched({len(watched)})"
        print(f"watch: tick {ticks} — {len(rows)} in-flight worker(s); "
              f"{len(in_scope)} actionable in scope={scope_txt}"
              + (f"; {suppressed} actionable OUT-OF-SCOPE (not woken — another watcher's business)"
                 if suppressed else "")
              + f"; action={action}", file=err, flush=True)
        # T-11926 — RECORD any premature exit this tick observed, BEFORE the break, so a tick that
        # both observes the death AND satisfies a wake condition still writes the row it saw. Scoped
        # to `in_scope` rows (the trigger, not the view). Fail-open per finding: one bad append never
        # costs the caller its token, and the other findings still land.
        for _row in (in_scope if _premature_findings else []):
            for _tid, _payload in (_premature_findings(_row) or []):
                try:
                    _emit("bg_dispatch_halted", _tid, _payload)
                    print(f"watch: recorded premature_exit for {_tid} "
                          f"(worker {_row.get('session_ref')}) — it authored no terminal; any work it "
                          f"did is UN-LANDED. `journal query --fleet-verdict` now names the cause.",
                          file=err, flush=True)
                    # T-12986 — surface the worker's own last words, not just «proc gone»: the
                    # recorded tail, already byte-bounded (journal._DISPATCH_LOG_TAIL_BYTES). str
                    # methods only, so the watcher's read-only call fence stays as it is.
                    _lt = str((_payload or {}).get("log_tail") or "")
                    for _ln in [x for x in _lt.splitlines() if x.strip()][-_TAIL_PRINT_LINES:]:
                        print(f"watch:   | {_ln}", file=err, flush=True)
                except Exception as _exc:               # noqa: BLE001 — observability, never a gate
                    print(f"watch: observed a premature exit for {_tid} but could NOT record it "
                          f"({_exc!r}); the watch PROCEEDS — the death stays inferable only from "
                          f"journal staleness for this tick.", file=err, flush=True)
        if action != "continue":
            break
        if _now() - started >= timeout:
            action, reason = "timeout", (f"no wake condition within {timeout}s "
                                         f"({ticks} ticks, {len(rows)} worker(s) still in flight) — "
                                         f"reassess the fleet + re-arm the watcher (never silent, T-10386)")
            break
        _sleep(interval)
    # The fleet snapshot that justified the exit, so the controller acts on the WHOLE fleet and never
    # abandons the siblings of the worker that woke it (T-0680). The T-11829 early exit is included for
    # exactly that reason: reporting only the ONE finished task would let a controller re-arm over an
    # incomplete set with nothing failing — the no-abandon-siblings rule is not relaxed by reporting
    # sooner, so the SAME fleet-wide report serves both exits.
    for row in _fleet_rows() if action in ("wake", "any_terminal") else []:
        print(f"  {row.get('session_ref')}  {row.get('verdict')}  class={row.get('class')}  "
              f"tasks={','.join(row.get('task_ids') or [])}", file=err, flush=True)
    # ONE receipt tying this watcher's ticks to the verb it consumed — the SPEC-0133 §Verification
    # adoption probe («a real controller watcher tick CONSUMES the verdict»). It is a journal APPEND, the
    # sanctioned no-worktree capture (D-0049) and the same posture `dispatch` already takes for its
    # readiness advisory (T-10354); it is never read back, so it is not watcher state. Fail-OPEN: a
    # broken receipt must never swallow the token the caller is waiting for.
    try:
        _emit("consumer_read_evidence", None, journal.kernel_self_telemetry(   # T-13020 provenance
              {"probe": "dispatch --watch tick consumed `journal query --fleet-verdict` + the POSITIVE "
                        "`--dispatch-status` class token to decide wake vs continue (T-10347)",
               "verb_surface": "journal query --fleet-verdict", "watched_tasks": tasks,
               "ticks": ticks, "confirm_ticks": confirm, "outcome": action, "read_only": True,
               # T-12641 — an ORPHANED watcher used to LAUNDER ITSELF INTO THE "MONITORED" COLUMN: it
               # exits, so it emits this receipt, the only journaled monitoring evidence
               # `debt.unmonitored_dispatches` credits — and the wave read monitored while no wake
               # reached anyone. Carrying the arming lets the reader decline that credit.
               "arming_reachability": arming_reachability}))
    except Exception as e:                                      # noqa: BLE001 — receipt is best-effort
        print(f"watch: adoption receipt unavailable ({e}); the verdict token below is unaffected.",
              file=err, flush=True)
    token = {"wake": "WAKE", "all_terminal": "ALL_TERMINAL", "any_terminal": "ANY_TERMINAL",
             "timeout": "TIMEOUT"}[action]
    # THE DURABLE VERDICT (T-11370, X-1026/X-1038). Until now the terminal verdict existed on STDOUT
    # ALONE — this function had exactly ONE emit site for it, the print below — so a watcher whose
    # wrapper output was lost came back with NO surviving answer to the question it was armed for. The
    # requester settled the cause with a same-session controlled comparison: four poll loops armed
    # identically, each PRINTING PER TICK, returned 544/3770/4014/1581 bytes intact while the watcher
    # returned 22. The harness preserves stdout; this watcher never wrote a verdict to preserve. So the
    # fault was the RECIPE, and the fix is a journal row beside the token — recovery keys off the
    # journal, which is what X-0843's capture-wide/gate-narrow rule already requires.
    # It reuses the ALREADY-INJECTED `_emit` the adoption receipt above uses (the same D-0049
    # no-worktree append) rather than opening a second write path — no new entity (CHARTER §P1 F2).
    # BEFORE the print, deliberately: the record must survive the case where the stdout does not, so it
    # must already exist when the token is spoken. Fail-OPEN like its sibling receipt — a broken journal
    # must never swallow the token a caller is blocked on.
    try:
        _emit("watch_verdict_recorded", None,
              {"token": token, "reason": reason, "watched_tasks": tasks, "ticks": ticks,
               "confirm_ticks": confirm, "watch_fleet": watch_fleet,
               "any_terminal_mode": any_terminal, "outcome": action})
    except Exception as e:                      # noqa: BLE001 — durability is best-effort, never a gate
        print(f"watch: verdict journal row unavailable ({e}); the verdict token below is unaffected.",
              file=err, flush=True)
    # THE STDOUT TOKEN CONTRACT IS UNCHANGED — byte-identical for all three terminals, so a caller
    # already parsing `^WATCH: (WAKE|ALL_TERMINAL|TIMEOUT)\b` keeps working untouched. The row above
    # ADDS a durable record beside this line; it replaces nothing.
    print(f"WATCH: {token} {reason}", file=out, flush=True)
    return {"all_terminal": 0, "wake": 1, "timeout": 2, "any_terminal": 3}[action]


def _dispatch_inflight_report(task_id: str, wt: "Path", main_wt: "Path", *,
                              _read_worktree_stamp, _session_last_event_ts,
                              liveness_why: "str | None" = None,
                              fleet_terminal: bool = False) -> "tuple[str, str | None]":
    """The in-flight pre-flight guard message (T-0621) — given a LIVE `task/<task_id>` worktree, return
    `(message, holder_session_ref|None)`: why this task's dispatch is being SKIPPED + who advisorily
    holds it. REUSES the T-0362 advisory-liveness primitives (`_read_worktree_stamp` + the journal
    `_session_last_event_ts`) that already power `_foreign_hold_report` — a foreign worktree is NEVER
    auto-adopted (T-0362), so the guard is purely advisory + refuse-to-spawn (NO reservation/lease;
    full atomicity is the PARKED T-0525). Pure read (stamp file + journal scan); no state."""
    stamp = _read_worktree_stamp(wt)
    holder = (stamp or {}).get("session_ref")
    # holder worktree journal first (its pre-land appends live there), then main — same precedence
    # as _foreign_hold_report's journals list.
    last = _session_last_event_ts(holder, [wt / "events.jsonl", main_wt / "events.jsonl"]) if holder else None
    holder_txt = holder or "UNKNOWN (no stamp — created pre-stamp or via raw git)"
    # T-12681 (X-1479): the per-id line is the outcome word UPPERCASED (`SKIPPED`, the launch line's
    # sibling) + the holder evidence the guard read in parentheses, so a reader scanning the
    # launch-line position sees a skip as loudly as a launch.
    msg = (
        f"dispatch: SKIPPED {task_id} (in-flight: already in-flight in worktree {wt}, "
        f"held by session {holder_txt}, last journal event {last or 'none found'}). "
        # T-12683 — the liveness read's own verdict (LIVE process / cwd holders + the attributed
        # session's tri-state verdict / no stamp), so a reader of the skip sees WHY the holder was not
        # classed a dead session's orphan without re-running the guard.
        + (f"Liveness read: {liveness_why}. " if liveness_why else "")
    )
    if fleet_terminal:
        # T-13171 (<project> X-1573) — the fleet verdict reads this task TERMINAL, so this guard must
        # not assert a running worker it cannot see. It STATES which signal it trusts instead: the
        # holder-scoped read above (stamped session's own last journal row + cwd holders — T-12683's
        # "unknown is not dead"), over the task-level terminal, and names the governed way out.
        msg += (f"The fleet verdict reads {task_id} TERMINAL; this guard does NOT assert a running "
                f"worker — it trusts the holder-scoped read above over that task-level terminal, "
                f"because it cannot yet PROVE the holder over. NOT spawning: confirm the holder dead, "
                f"then `worktree adopt --task {task_id} --confirm-dead` (or park) and re-dispatch "
                f"(T-0362, never auto). The other --task ids still launch.")
    else:
        msg += (f"NOT spawning a redundant worker: use the live worker, or — ONLY after confirming the "
                f"holder dead — adopt/clean the orphan explicitly (T-0362, never auto). The other "
                f"--task ids still launch.")
    return msg, holder


def _default_session_proc_alive(session_ref: "str | None") -> bool:
    """T-10985 — the module default for the injected `_session_proc_alive`: the SAME targeted
    `--session-id <ref>` existence probe the fleet-verdict classifier reads, never a second liveness
    model. Imported LAZILY (the `worktree._default_session_proc_alive` idiom) so this module keeps
    back-importing nothing at import time."""
    from lib import journal as _journal
    return _journal._session_proc_alive(session_ref)


def _default_live_path_holders(path) -> "list[dict]":
    """T-10985 — the module default for the injected `_live_path_holders`: the SAME cwd read
    `worktree._assert_no_live_holder` uses (T-10885). Lazy import, same reason as above."""
    from lib import worktree as _worktree
    return _worktree._live_path_holders(path)


def _default_session_terminally_over(session_ref: "str | None", events_path) -> bool:
    """T-12683 — the module default for the injected `_session_terminally_over`: the SAME journal
    read the park/adopt `--confirm-dead` reap resolves a holder session's death from (T-12375,
    `worktree_lifecycle._default_session_terminally_over`), never a second "is it over" model.
    Lazy import, the `_default_session_proc_alive` idiom."""
    from lib import worktree_lifecycle as _wl
    return _wl._default_session_terminally_over(session_ref, events_path)


def _default_proc_scan_is_takeable() -> bool:
    """T-12683 — the module default for the injected `_proc_scan_is_takeable`: the T-11925
    ref-independent "was that negative definite?" companion of `_session_proc_alive`. Lazy import."""
    from lib import journal as _journal
    return _journal._proc_scan_is_takeable()


def _orphan_holder_liveness(wt, *, _read_worktree_stamp, _session_proc_alive,
                            _live_path_holders, _session_terminally_over=None,
                            _proc_scan_is_takeable=None, _resolve_holder_sessions=None,
                            main_wt=None) -> "tuple[bool, str | None, str, list]":
    """T-10985 — is a task worktree's holder DETERMINED dead? `(confirmed_dead, holder_ref, why_not,
    orphan_holders)`.

    The discriminator for the preserving orphan re-dispatch below. The hard bound the card sets is that
    liveness must be DETERMINED, never accepted on the caller's assertion — so this reads evidence and
    takes no flag. It is the SAME two-read substrate `worktree._assert_no_live_holder` (T-10885) already
    uses for park / work-discard, deliberately NOT a second liveness model (CHARTER §P1 F1):
      (a) the T-0362 session stamp names the holder, probed with `_session_proc_alive` — the answer for
          a path that still exists;
      (b) `_live_path_holders` — a live process whose cwd is (or is under) the worktree, which also
          covers a holder that is alive but not currently stamped-visible.

    POSITIVE evidence on EVERY axis, with a reserved "did not answer" that refuses
    (lessons/carving-an-exception-into-a-fail-closed-gate §1): an UNSTAMPED / raw-git worktree names no
    holder, so its death cannot be confirmed — that is not "dead", it is UNVERIFIABLE, and it routes to
    the protective SKIP exactly like a live holder. The caller must treat False as "keep the guard".
    Pure read (stamp file + /proc); no state, no event, no mutation."""
    stamp = _read_worktree_stamp(wt)
    ref = (stamp or {}).get("session_ref")
    if not ref:
        return (False, None, "the worktree carries NO session stamp (created pre-stamp or via raw "
                             "git), so its holder is unidentifiable and its death UNVERIFIABLE", [])
    if _session_proc_alive(ref):
        return (False, ref, f"the stamped holder session {ref} has a LIVE process", [])
    holders = _live_path_holders(wt)
    if holders:
        # T-12683 (X-1479) — a cwd holder is NOT automatically a LIVE holder. A verify step that
        # starts a long-lived server inside the worktree (<project> T-0679: `vite preview`, PPID 1,
        # cwd .../T-0679/frontend) outlives the worker that HALTED and left it: the halt path has no
        # teardown, so the orphan held the path for ten hours and every governed re-dispatch took
        # this SKIP — a card permanently pinned. Read (b) alone cannot tell a working holder from
        # such an orphan; what can is the SAME tri-state session verdict the park/adopt
        # `--confirm-dead` reap already rests on (`_resolve_holder_sessions`, T-12375): the
        # holders are ATTRIBUTED to the stamped session, and that session is `dead` ONLY on
        # POSITIVE evidence — read (a) negative AND a takeable scan AND the journal's LAST row for
        # the ref a terminal marker (`bg_dispatch_halted` / `task_closed` / …). Then the cwd
        # holders are that dead session's ORPHANS, not a holder: this read admits the re-dispatch
        # and NAMES them, and the route's own adopt/park `--confirm-dead` (T-12451 / T-12375) is
        # what reaps them — no second reaper here, no daemon, no registry. A `live` or `unknown`
        # verdict (no stamp, blind /proc, a session whose last row is ordinary work) keeps the
        # refusal exactly as before: the 2026-08-10 T-10826 direction, and the SPEC-0134 rule 2
        # fence a LIVE worker is held by is untouched (that short-circuit ran above).
        from lib import worktree_lifecycle as _wl
        resolve = _resolve_holder_sessions or _wl._resolve_holder_sessions
        # The journal read is bound to MAIN's journal UNIONED with the held worktree's own (T-13351,
        # X-1834 dispute): a worker's `bg_dispatch_halted` is appended in its task worktree and
        # reaches main only at land, so a main-only read kept SKIPping the relaunch for the whole
        # gap. The reader folds the union (never the worktree instead of main). Without a `main_wt`
        # to bind it to, the read answers "not over" — `unknown`, REFUSED — rather than guessing a
        # path: fail-closed toward the SKIP, never toward admission.
        _over2 = _session_terminally_over or _default_session_terminally_over   # (ref, events_path)
        _journals = None
        if main_wt is not None:
            _journals = [Path(main_wt) / "events.jsonl"]
            _wt_j = Path(wt) / "events.jsonl"
            try:
                if _wt_j.is_file() and _wt_j.resolve() != _journals[0].resolve():
                    _journals.append(_wt_j)
            except OSError:
                pass
        over = ((lambda r: _over2(r, _journals)) if _journals else (lambda r: False))
        res = resolve(holders, [], stamp, _session_proc_alive=_session_proc_alive,
                      _proc_scan_is_takeable=(_proc_scan_is_takeable
                                              or _default_proc_scan_is_takeable),
                      _session_terminally_over=over)
        if res.get("verdict") == "dead":
            return (True, ref, "", list(holders))
        return (False, ref, f"a LIVE process holds the worktree path as its cwd "
                            f"(pids {[h['pid'] for h in holders]}; attributed to session {ref}, "
                            f"verdict {res.get('verdict')})", [])
    return (True, ref, "", [])


def _in_claim_footprint(path: str, task: str) -> bool:
    """Is `path` inside the RE-DERIVABLE CLAIM FOOTPRINT — `events.jsonl` or the task's own card?

    The ONE definition of that footprint (`_orphan_carries_work`'s docstring is its rule home), read
    by the uncommitted-path loop there AND by the landed-done commit proof below, so a committed and
    an uncommitted path can never be judged against two different footprints (CHARTER §P5)."""
    return path == "events.jsonl" or bool(_claim_card_re(task).fullmatch(path))


def _git_z_paths(stdout) -> "list[str]":
    """The paths of a `-z` git listing: NUL-split, empty records dropped. `-z` output is never
    quoted, so a non-ASCII path arrives as itself (SPEC-0185 §2a(i))."""
    return [p for p in (stdout or "").split("\0") if p]


# T-13458 — the ONE spelling of «list the paths a tree diff changes» for the landed-done proof, so
# no read can be configured into hiding a path. PLUMBING (`diff-tree`), never porcelain `git diff`:
# porcelain honours the reader's `diff.*` UI configuration, and `diff.ignoreSubmodules=all` makes a
# committed submodule (gitlink) update vanish from its output with rc 0 — an empty list that reads
# «nothing changed» (audit-post finding on this card; measured). `--ignore-submodules=none` is
# spelled as well, because plumbing still honours a `.gitmodules` / `submodule.<name>.ignore = all`
# and the explicit flag is the one thing that overrides both. `--no-commit-id` keeps a commit header
# out of the records (see the docstring below); `-z` keeps every path verbatim.
_PROOF_DIFF_PATHS = ("diff-tree", "-r", "--name-only", "--no-commit-id", "--ignore-submodules=none", "-z")


def _landed_done_ahead_carries_work(wt, task: str, *, _run_git_cap) -> "tuple[bool, str]":
    """T-13458 — on a card that is `done` on main, do the commits AHEAD of main hold anything a
    teardown would lose? `(carries_work, why)`; `(False, "")` only on a complete positive proof.

    WHY THIS EXISTS. `_orphan_carries_work` reads ANY commit ahead of main as work. That is right for
    a claim that never landed, and it wedged the landed-done retirement (T-11414): a batch-landed
    card's own land-retry loop keeps merging main into its branch and committing journal
    bookkeeping, so the branch sits N ahead while holding nothing — and no governed verb could
    remove it (measured 2026-10-03: task/T-13402, six merges of main; task/T-13373, two merges plus
    one `land: bookkeeping` commit).

    A COMMIT AHEAD CARRIES NO WORK when it is
      (i)  a MERGE whose every non-first parent is already an ancestor of main AND which itself
           authors nothing outside the claim footprint — its dense combined diff, i.e. the paths
           whose result differs from EVERY parent (a hand resolution; a union-merged journal lands
           here too, inside the footprint); or
      (ii) a ONE-PARENT commit whose changed paths all lie inside the claim footprint;
    AND the branch as a whole holds no content main lacks: exactly ONE merge base with main, and the
    diff from that base to HEAD confined to the footprint. The per-commit proof alone would wave
    through an `-s ours` merge that silently keeps an old version of a main file; the net-content
    proof alone would wave through authored content a later merge cancelled out.

    POSITIVE EVIDENCE ON EVERY AXIS, with a reserved «did not answer»
    (`lessons/carving-an-exception-into-a-fail-closed-gate` §1): `merge-base --is-ancestor` answers
    0 = on main and 1 = not on main, and EVERY other exit — like every other failed read here, a
    parentless commit, and zero or several merge bases — reads «carries work». The branch this
    guards cannot be undone.

    `--no-commit-id` on the combined-diff read is LOAD-BEARING: without it `diff-tree` prints the
    merge's own sha as its first record, which is no footprint path and would preserve every allowed
    merge (audit-pre finding on this card; pinned by the union-merge arm of the AC2 test).

    NO READ HERE MAY BE CONFIGURED INTO SILENCE. Every path list comes from `_PROOF_DIFF_PATHS` —
    plumbing with `--ignore-submodules=none` — because an empty list is this proof's «nothing to
    lose», and a reader whose configuration can empty the list has a configuration that opens the
    teardown (audit-post finding on this card: `diff.ignoreSubmodules=all` hid a committed gitlink
    update from the porcelain reads first written here; pinned by the gitlink arms of the test).

    Pure read (git plumbing only, bounded by the commits ahead); no state, no event, no mutation."""
    listed = _run_git_cap(["rev-list", "--parents", "main..HEAD"], wt)
    if listed.returncode != 0:
        return (True, f"could not list the commits ahead of main ({(listed.stderr or '').strip()}) — "
                      f"refusing to treat an unreadable worktree as empty")
    rows = [ln.split() for ln in (listed.stdout or "").splitlines() if ln.strip()]
    if not rows:
        return (False, "")
    for sha, *parents in rows:
        short = sha[:12]
        if not parents:
            return (True, f"un-landed commit {short} has no parent — a root commit that is not on main")
        if len(parents) == 1:
            changed = _run_git_cap([*_PROOF_DIFF_PATHS, "--no-renames", parents[0], sha], wt)
            if changed.returncode != 0:
                return (True, f"could not read what commit {short} changes "
                              f"({(changed.stderr or '').strip()}) — refusing to treat it as empty")
            for path in _git_z_paths(changed.stdout):
                if not _in_claim_footprint(path, task):
                    return (True, f"un-landed commit {short} touches {path}, outside the re-derivable "
                                  f"claim footprint")
            continue
        for parent in parents[1:]:
            on_main = _run_git_cap(["merge-base", "--is-ancestor", parent, "main"], wt)
            if on_main.returncode == 1:
                return (True, f"un-landed merge {short} brings in {parent[:12]}, which is NOT on main")
            if on_main.returncode != 0:
                return (True, f"could not establish whether {parent[:12]} (merged by {short}) is on "
                              f"main ({(on_main.stderr or '').strip()}) — refusing to treat it as landed")
        authored = _run_git_cap([*_PROOF_DIFF_PATHS, "--cc", sha], wt)
        if authored.returncode != 0:
            return (True, f"could not read what merge {short} authors "
                          f"({(authored.stderr or '').strip()}) — refusing to treat it as empty")
        for path in _git_z_paths(authored.stdout):
            if not _in_claim_footprint(path, task):
                return (True, f"un-landed merge {short} authors {path}, outside the re-derivable "
                              f"claim footprint")
    bases = _run_git_cap(["merge-base", "--all", "main", "HEAD"], wt)
    base_shas = [ln.strip() for ln in (bases.stdout or "").splitlines() if ln.strip()]
    if bases.returncode != 0 or len(base_shas) != 1:
        return (True, f"could not establish ONE merge base with main (git answered {len(base_shas)}; "
                      f"{(bases.stderr or '').strip()}) — refusing to judge the branch's content")
    net = _run_git_cap([*_PROOF_DIFF_PATHS, "--no-renames", base_shas[0], "HEAD"], wt)
    if net.returncode != 0:
        return (True, f"could not read the branch's content against main "
                      f"({(net.stderr or '').strip()}) — refusing to treat it as empty")
    for path in _git_z_paths(net.stdout):
        if not _in_claim_footprint(path, task):
            return (True, f"the branch differs from main at {path}, outside the re-derivable claim "
                          f"footprint")
    return (False, "")


def _orphan_carries_work(wt, task: str, *, _run_git_cap, landed_done: bool = False) -> "tuple[bool, str]":
    """T-11289 — would tearing THIS orphan worktree down DESTROY anything a fresh claim cannot
    re-derive? `(carries_work, why)`.

    The discriminator that keeps the T-9689 teardown arm on the case it was built for (a worker that
    died with nothing but its claim) and off the case that burns real money: the 2026-08-18 incident,
    where the only governed way to hand a stopped card to another worker destroyed the external-auditor
    verdicts it had already paid for (T-11247 held `decisions/T-11247-audit-pre.yaml` +
    `-audit-consult-pre.yaml`, T-11250 `decisions/T-11250-audit-post.yaml`).

    POSITIVE-EVIDENCE-FOR-EMPTY, because the branch this guards is the DESTRUCTIVE one
    (`lessons/carving-an-exception-into-a-fail-closed-gate` §1 — only a positive proof may open the
    path that cannot be undone). So every uncertain answer returns True (preserve), and only a
    provably-empty worktree returns False:
      - any commit on the branch beyond `main` -> carries (un-landed ship work);
      - any working-tree entry OUTSIDE the RE-DERIVABLE CLAIM FOOTPRINT -> carries;
      - any git failure / unparseable count -> carries (never destroy on doubt);
      - else (False, "").

    THE CLAIM FOOTPRINT is exactly two paths, and the bound is what makes this a discriminator rather
    than a blanket "never tear down": `events.jsonl` is append-only + union-merged and the next `land`
    folds it back from main, and `tasks/<task>-*.yaml` carries only the `ready->in-progress` + Analysis
    claim that the fresh `worktree new --task` re-writes. Everything else — a saved
    `decisions/<task>-audit-*.yaml`, edited source, a new test — is unrecoverable.

    MEASURED, not assumed: T-11247 carries ZERO commits ahead of main and its paid audit records are
    UNTRACKED files, so a commits-only read would have missed the very card the incident names first.

    NOT `_classify_inert_paths` (CHARTER §P1 F1 considered + rejected, deliberately): that classifier
    answers "is this change observable enough to need an audit?" and its allowlist holds `decisions/`
    INERT — the exact opposite polarity for this question. Reusing it would have declared T-11247's
    audit records worthless. Pure read (two git plumbing calls); no state, no event, no mutation.

    `landed_done` (T-13458) — passed True by ONE caller, `worktree park`'s landed-done arm, and by
    no other. There «any commit beyond main carries» is REPLACED by the per-commit proof
    `_landed_done_ahead_carries_work`: a card whose claim, diff and closure are ALL on main can sit
    ahead of it by merges of main and journal bookkeeping alone, and counting those by sha left its
    worktree with no governed exit. With the keyword absent — the dispatch confirmed-dead teardown
    and park's `ready` / `wont-do` arms — this function behaves exactly as it did before the keyword
    existed: any commit ahead is work. The uncommitted-path check below is shared by both reads."""
    if landed_done:
        ahead_carries, ahead_why = _landed_done_ahead_carries_work(wt, task, _run_git_cap=_run_git_cap)
        if ahead_carries:
            return (True, ahead_why)
    else:
        ahead = _run_git_cap(["rev-list", "--count", "main..HEAD"], wt)
        if ahead.returncode != 0:
            return (True, f"could not count commits ahead of main ({(ahead.stderr or '').strip()}) — "
                          f"refusing to treat an unreadable worktree as empty")
        try:
            n_ahead = int((ahead.stdout or "").strip() or "0")
        except ValueError:
            return (True, f"unparseable commit count {(ahead.stdout or '').strip()!r} — "
                          f"refusing to treat an unreadable worktree as empty")
        if n_ahead > 0:
            return (True, f"{n_ahead} un-landed commit(s) on the branch")
    st = _run_git_cap(["status", "--porcelain"], wt)
    if st.returncode != 0:
        return (True, f"could not read the working tree ({(st.stderr or '').strip()}) — "
                      f"refusing to treat an unreadable worktree as empty")
    for line in (st.stdout or "").splitlines():
        # porcelain v1: 2 status chars + a space, then the path (a rename carries ` -> `; take the
        # DESTINATION, which is the path that exists in the worktree).
        path = line[3:].strip().strip('"')
        if " -> " in path:
            path = path.split(" -> ", 1)[1].strip().strip('"')
        if not path:
            continue
        if _in_claim_footprint(path, task):
            continue                       # re-derivable claim footprint — not work
        return (True, f"uncommitted work at {path}")
    return (False, "")


def _claim_card_re(task: str):
    """The `tasks/<task>-<slug>.yaml` shape (QUEUE §Active-queue filename convention) — the ONE card a
    claim rewrites. Kept a function, not a module constant, because it is per-task; `re.escape` so a
    task id can never smuggle a pattern."""
    return re.compile(rf"tasks/{re.escape(task)}-[^/]*\.yaml")


# T-10985 — the ADOPT-FIRST override prepended to the brief of a worker re-dispatched INTO a preserved
# confirmed-dead orphan. It must OVERRIDE, not merely supplement: the standing DISPATCH_WORKER_PREAMBLE
# point 3 tells every worker to CLAIM via `worktree new --task`, which on this path is the one command
# that CANNOT succeed (the branch exists, foreign-stamped → `cmd_worktree_new` refuses). A brief
# carrying both instructions leaves the route non-executable for the reader who follows the preamble
# first (audit-pre finding, absorbed). Composed AFTER the preamble by construction (the preamble leads
# in `_compose_worker_brief`), so this block is the later, winning instruction.
ORPHAN_ADOPT_BRIEF_OVERRIDE = """\
=== ADOPT-FIRST — THIS DISPATCH OVERRIDES THE PREAMBLE'S CLAIM STEP (T-10985) ===
You are re-dispatched onto {task}, whose PREVIOUS worker is CONFIRMED DEAD (determined in code at
launch: no live holder process, no live cwd holder) and whose worktree at {wt} is INTACT and PRESERVED
— it may carry an un-landed ship commit, so nothing was torn down.

The preamble's point-3 CLAIM step does NOT apply to this dispatch. Do NOT run `worktree new --task
{task}`: the task is ALREADY claimed and the branch already exists, so that command will refuse. Take
the worktree over instead:

  bin/yitc-v2 worktree adopt --task {task} --confirm-dead
  cd {wt}
  bin/yitc-v2 session start --type build

`--confirm-dead` is a provenance assertion only — the verb RE-VERIFIES liveness in code and refuses a
live holder, so it cannot be talked into a takeover. Then re-derive state from the journal and the
on-branch card, re-enter your `current_stage` (`bin/yitc-v2 stage <STAGE> --task {task}`), and carry
the task to `task close` → `land` as usual. Every other point of the preamble applies unchanged.
=== END ADOPT-FIRST OVERRIDE ===
"""


# ── T-12332 (X-1344, <project> T-0632) — the PAUSED-CARD sibling of the override above ─────────────
# The preserving arm already hands a dead orphan to a fresh worker, but its brief names only
# `worktree adopt` -> `stage <STAGE>`. For a card that is PAUSED (in-progress + `paused_at`) that
# sequence is INCOMPLETE: the adopt re-stamps the worktree and nothing clears `paused_at`, so the
# re-entry the doctrine calls the DEFAULT — `task resume` (T-0381), which re-enters without a
# re-claim — is named in no brief a Worker ever receives. Measured: a <project> card paused at
# Execution with ~19 modified files in a session-less worktree could not be routed to a Worker at
# all, and the Controller's only route was to self-execute — the owner-say-so FALLBACK standing in
# for the default (CHARTER §6 / SPEC-0141 §3).
#
# COMPOSITION, NOT A NEW MECHANISM (CHARTER §P1 F1/F2): both halves already ship and neither is
# touched. `worktree adopt --task` carries no card-status gate and re-verifies liveness in code
# (SPEC-0134 rule 2); `task resume` requires an OWN-stamped writing worktree, which is exactly what
# the adopt has just produced — so the two compose in this order and in no other. What this template
# adds is the ORDER, written down where the worker reads it.
#
# The ABSENT-worktree half of a pause is deliberately NOT routed here: `worktree new --task` already
# re-enters a landed orphan in place (`_orphan_resume_task`, T-9317 widened by T-10544 — recreates
# the worktree + resumes, no second claim), and naming `worktree adopt` for a worktree that does not
# exist would name a verb with nothing to adopt.
RESUME_ADOPT_BRIEF_OVERRIDE = """\
=== RESUME-FIRST — THIS DISPATCH OVERRIDES THE PREAMBLE'S CLAIM STEP (T-12332) ===
You are re-dispatched onto {task}, a card that is IN-PROGRESS and PAUSED (paused_at {paused_at},
reason {paused_reason}). Its PREVIOUS holder is CONFIRMED DEAD (determined in code at launch: no live
holder process, no live cwd holder) and its worktree at {wt} is INTACT and PRESERVED — it may carry
uncommitted work and an un-landed ship commit, so nothing was torn down.

The preamble's point-3 CLAIM step does NOT apply to this dispatch. Do NOT run `{invoke} worktree new
--task {task}`: the card is ALREADY claimed and the branch already exists, so that command will
refuse. This is a RESUME, not a claim — take the worktree over, then re-enter the card in place:

  {invoke} worktree adopt --task {task} --confirm-dead
  cd {wt}
  {invoke} session start --type build
  {invoke} task resume {task}
  {invoke} stage {stage} --task {task}

Run them in THAT ORDER and skip none. `--confirm-dead` is a provenance assertion only — the verb
RE-VERIFIES liveness in code and refuses a live holder, so it cannot be talked into a takeover.
`task resume` (T-0381) re-enters a paused in-progress card WITHOUT a second claim: it validates the
worktree own-stamp the adopt just wrote (T-0362) and clears `paused_at`/`paused_reason`, keeping the
rest of the resume contract as continue-from history. It is the step that makes the card workable
again — skipping it leaves you editing a card the system still reads as paused.

RECORDED RESUME CONTRACT (from the card, not from controller memory):
  resume stage : {stage}
  next_action  : {next_action}

Re-derive the rest of your state from the journal and the on-branch card before you act, then carry
the task through the remaining stages as usual. Every other point of the preamble applies unchanged.
=== END RESUME-FIRST OVERRIDE ===
"""


def _resume_entry_card(card) -> "dict | None":
    """T-12332 — is this wave card one whose re-entry is `task resume`, not a claim?
    `{paused_at, paused_reason, stage, next_action}` when it is, else None.

    The discriminator for the RESUME flavour of the preserving orphan re-dispatch. POSITIVE
    CONJUNCTION ONLY, on the card the wave ALREADY read (`_wave_cards`, T-11678 — no second read, no
    new store): `status == "in-progress"` AND a non-empty `paused_at`. Everything else — a `ready`
    card, an unpaused in-progress card, an unreadable card that the wave fold degraded to None — is
    None, so the fail-OPEN card read can never OPEN this path, only ever leave it shut.

    It decides the BRIEF and the launch row's `mode`, never ADMISSION: the permit for the whole
    branch stays `_orphan_holder_liveness`'s determined-death read, asserted at the call site above
    this, so a LIVE or UNVERIFIABLE holder can never reach here and the T-0351/T-0362 double-claim
    fence is untouched.

    `stage` is the recorded `resume_from`, falling back to `current_stage`, falling back to
    `Execution` — the three carriers `task pause` / `_apply_task_resume` write and read, in the order
    `cmd_task_resume` itself prints them. Pure read; no I/O, no state, no mutation."""
    if not isinstance(card, dict):
        return None
    if (card.get("status") or "") != "in-progress":
        return None
    paused_at = card.get("paused_at")
    if not paused_at:
        return None
    return {"paused_at": str(paused_at),
            "paused_reason": str(card.get("paused_reason") or "(none recorded)"),
            "stage": str(card.get("resume_from") or card.get("current_stage") or "Execution"),
            "next_action": str(card.get("next_action") or "(none recorded)")}


# -- T-12607 (SPEC-0072 rule 7) -- the tier's PRIMARY pair and its OPTIONAL RESERVE pair -----------
# A provider-side SATURATION of the bound worker model blocks EVERY worker at that effort tier: the
# launch dies in the bootstrap, the fleet reads `launch-stall`, and its `transient-overload` detail
# says only «wait, then re-dispatch the SAME task unchanged» (T-11565) -- a HUMAN loop, once per
# stalled launch, with no second door. This is the dispatch-seam sibling of the auditor rule T-12606
# shipped for `bin/audit-config.yaml`; the doctrine is that card's, reused here, not re-authored.
#
# NO model id and NO effort level is spelled anywhere in this module's executable text (CHARTER
# §P4b) -- every value is read from `bin/effort-routing-config.yaml` by the injected resolvers.
#
# THE TRIGGER IS NARROW AND IS THE WHOLE RULE: the launch produced NO WORKER. An AUTH failure is NOT
# that -- it needs a HUMAN credential and a second model dies identically (T-10792), so it neither
# falls back nor waits, and a bootstrap that died of something unrecognised stays exactly today's
# launch-stall. Both of those are fail-closed toward «it answered», so the wait arm can only ever be
# entered by a cause that a retry can actually clear.
#: the wall-clock window a fresh launch is watched for before it counts as HAVING ANSWERED. Sized to
#: the fast causes only: a capacity/overload refusal and an auth death are printed-and-exited within
#: seconds, while a genuine bootstrap takes minutes -- so a live process at the end of this window is
#: an ANSWER (the DISPATCH_NEAR_LAUNCH_GRACE_SEC stall clock, which is the ~10-minute reader-side
#: judgement, is a different question and is UNTOUCHED by this).
LAUNCH_ANSWER_PROBE_SECONDS = 45
#: the pace between two attempts at a primary that is not answering while the tier declares NO
#: reserve. A pause, never a budget: the wait ENDS when the primary comes up (or the operator
#: interrupts it), never on a counter -- an expiring retry budget IS the launch-stall the rule forbids.
LAUNCH_NO_ANSWER_WAIT_SECONDS = 60
#: the poll granularity inside the probe window. Not a tunable: it only decides how soon a launch that
#: has ALREADY died is noticed, never any outcome.
_LAUNCH_PROBE_POLL_SECONDS = 1.0
#: the `deviation_captured` fingerprints the journaled rows carry. NO new event type (SPEC-0025 is
#: untouched): a primary that will not come up IS «something is not as it should be», and the capture
#: reflex is what makes the outage class countable (D-0035/D-0086) rather than invisible.
WORKER_RESERVE_SWITCH_FINGERPRINT = "worker-primary-no-answer-reserve-pair-used"
WORKER_NO_RESERVE_WAIT_FINGERPRINT = "worker-primary-no-answer-waiting-no-reserve"
#: the three readings `classify_launch_answer` returns. Named, so a caller branches on a constant
#: rather than on a bare string literal it could typo into a silent no-switch.
LAUNCH_ANSWER = "answered"
LAUNCH_NON_ANSWER = "non-answer"
LAUNCH_AUTH = "auth"
#: T-13157 — a provider USAGE-LIMIT non-answer: opens the reserve ONCE, but never the wait loop.
LAUNCH_LIMIT = "limit"


def _default_pid_alive(pid: "int | None") -> bool:
    """T-12607 — is THIS pid still running? `signal 0` liveness, the only question the launch probe
    asks. Deliberately NOT a `pgrep -f` over an argv pattern: a pattern carrying the launcher's own
    command line MATCHES ITSELF and reads finished work as running (the measured T-11925/T-10557
    class). We hold the pid we just spawned, so we poll it directly.

    Fail-closed toward ALIVE on anything unreadable (a bad pid, a permission error): an unconfirmable
    process must never be read as a dead bootstrap, because that is the direction that would switch
    pairs or wait on a worker that is perfectly healthy."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return True
    if pid <= 0:
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except Exception:   # noqa: BLE001 — unreadable ⇒ alive (see the fail direction above)
        return True
    return True


def _default_reap_worker(pid: "int | None") -> None:
    """T-12645 — KILL a worker we spawned but could not RECORD. SIGTERM, a short grace, then SIGKILL.

    Called from exactly one place (`_record_spawn_or_reap`) and only when the durable record of that
    spawn could not be written after a retry. Reaping is the honest outcome, not a harsh one: the
    alternative is a LIVE worker with no trace in main's journal, which is bit-for-bit the X-1461
    false negative — the fold reads «never launched» and a re-dispatch duplicates it. A main-journal
    append that fails twice is a fault the launcher must not build on top of.

    Best-effort by nature (the process may already be gone, or be unsignalable) — but the REFUSAL that
    follows it never depends on this succeeding, so a reap we could not perform still refuses the
    launch rather than returning it as recorded."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return
    if pid <= 0:
        return
    for sig, grace in ((signal.SIGTERM, 2.0), (signal.SIGKILL, 0.0)):
        try:
            os.kill(pid, sig)
        except ProcessLookupError:
            return                       # already gone — nothing to reap
        except Exception:                # noqa: BLE001 — unsignalable; the refusal below still stands
            return
        if grace <= 0:
            return
        deadline = time.monotonic() + grace
        while time.monotonic() < deadline:
            if not _default_pid_alive(pid):
                return
            time.sleep(0.1)


def _record_launch_row(etype: str, task: str, data: dict, *, _append_event, _sleep=None,
                       attempts: int = 2) -> "tuple[bool, Exception | None]":
    """T-12645 — append a launch-axis row with ONE retry, reporting whether it landed.

    The single recorder behind BOTH rows this card makes durable — the `bg_dispatch_spawned` receipt
    and the auth arm's `bg_dispatch_halted` terminal (audit-post fp1:43f4edd22de19068). They are the
    two halves of one invariant: the spawn row says a process EXISTS, and the terminal is what stops a
    DEAD one from folding as alive. Recording one reliably and the other best-effort left a reachable
    fail-open — a failed terminal append would leave a durable spawn receipt classifying a corpse as a
    live worker — so they share a recorder and a failure contract instead of differing by accident.

    The retry is here because the realistic failure on an append-only journal is transient. Returning
    `(ok, last_error)` rather than raising is deliberate: each caller owns a DIFFERENT consequence (the
    spawn path reaps and refuses the launch; the auth path reaps and names the un-terminated row), and
    neither is served by an exception escaping into a launch loop."""
    _sleep = _sleep if _sleep is not None else time.sleep
    last = None
    for attempt in range(max(1, attempts)):
        try:
            _append_event(etype, task, data)
            return True, None
        except Exception as exc:        # noqa: BLE001 — every failure mode is handled identically
            last = exc
            if attempt + 1 < max(1, attempts):
                _sleep(0.2)
    return False, last


def _record_spawn_or_reap(pid, task: str, data: dict, *, _append_event, _reap=None, _die=None,
                          _sleep=None) -> None:
    """T-12645 (audit-pre fp1:5f22e2403fe460a9) — append the `bg_dispatch_spawned` row for a worker
    that IS ALREADY RUNNING, or kill it and refuse the launch. The append is part of the SPAWN
    TRANSACTION; it is deliberately NOT best-effort.

    WHY NOT BEST-EFFORT, stated once here so no caller has to re-derive it. This row exists solely so
    that a worker whose parent dies before writing `bg_dispatch_launched` is still discoverable. A
    suppressed append reproduces exactly the state the row was added to eliminate — a live worker with
    no durable trace — so «log it and carry on» would ship the defect under the fix's name. The
    invariant the code holds instead is the one AC1 names: NO LIVE WORKER SURVIVES UNRECORDED.

    ONE retry, then reap+refuse. The retry is there because the realistic failure is transient (a
    momentary fs/ENOSPC/lock condition on an append-only file); the reap is there because the
    realistic ALTERNATIVE is not.

    The reap is journaled `bg_dispatch_halted{kind: spawn_unrecordable}` on a best-effort basis — by
    hypothesis the journal may be unwritable, so that emit is allowed to fail silently. The REAP and
    the REFUSAL are not."""
    _reap = _reap if _reap is not None else _default_reap_worker
    _refuse = _die if _die is not None else _default_die
    _sleep = _sleep if _sleep is not None else time.sleep
    ok, last = _record_launch_row("bg_dispatch_spawned", task, data,
                                  _append_event=_append_event, _sleep=_sleep)
    if ok:
        return
    _reap(pid)
    try:
        _append_event("bg_dispatch_halted", task,
                      {"dispatch": task, "kind": "spawn_unrecordable", "pid": pid,
                       "reason": f"spawned worker could not be recorded ({last}) — reaped and "
                                 f"the launch refused, so no live worker survives unrecorded"})
    except Exception:   # noqa: BLE001 — the journal is what just failed; the refusal stands regardless
        pass
    _refuse(f"dispatch: {task} — the worker was spawned (pid {pid}) but its `bg_dispatch_spawned` "
            f"record could not be written to main's journal ({last}). The worker has been REAPED and "
            f"the launch is REFUSED: an unrecorded live worker is the exact false negative this row "
            f"exists to prevent (X-1461). Fix the journal write, then re-dispatch.")


def _default_read_launch_log(log_path) -> "str | None":
    """T-12607 — the just-spawned worker's own log bytes, or None when there is NO LOG TO READ.

    The distinction between None and "" is load-bearing, and it is the difference between «no
    evidence» and «evidence of silence». The real provider adapters OPEN the log file before spawning,
    so after a real launch the file EXISTS — possibly empty. An empty EXISTING log beside a dead
    process therefore means the worker wrote nothing, which is a reading. A MISSING file means this
    seam was handed no observation surface at all, which is not a reading about the worker and must
    never be treated as one. Unreadable is likewise None. Never raises."""
    try:
        path = Path(log_path)
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:   # noqa: BLE001
        return None


def _launch_probe_seconds() -> float:
    """The probe window, resolved through the SPEC-0193 PERFORMANCE key
    `lib.dispatch.LAUNCH_ANSWER_PROBE_SECONDS` (the `auditor_no_answer_wait_seconds` shape, T-12606).
    Machine settings are NEVER a prerequisite: any failure, and any non-positive resolved value,
    falls back to the built-in constant."""
    try:
        from lib import machine_settings      # deferred: keeps the hot import graph unchanged
        val = float(machine_settings.resolve("lib.dispatch.LAUNCH_ANSWER_PROBE_SECONDS",
                                             LAUNCH_ANSWER_PROBE_SECONDS))
    except Exception:            # noqa: BLE001 — SPEC-0193 rule 6: never a prerequisite
        return float(LAUNCH_ANSWER_PROBE_SECONDS)
    return val if val > 0 else float(LAUNCH_ANSWER_PROBE_SECONDS)


def _launch_wait_seconds() -> float:
    """The no-reserve retry pace, resolved through the SPEC-0193 PERFORMANCE key
    `lib.dispatch.LAUNCH_NO_ANSWER_WAIT_SECONDS`. Same never-a-prerequisite contract as the probe
    window above. Pure CADENCE: it paces how often the primary is re-asked, and no value of it can
    turn a launch into a refusal — which is exactly what SPEC-0193 rule 2 asks of a performance key."""
    try:
        from lib import machine_settings
        val = float(machine_settings.resolve("lib.dispatch.LAUNCH_NO_ANSWER_WAIT_SECONDS",
                                             LAUNCH_NO_ANSWER_WAIT_SECONDS))
    except Exception:            # noqa: BLE001
        return float(LAUNCH_NO_ANSWER_WAIT_SECONDS)
    return val if val > 0 else float(LAUNCH_NO_ANSWER_WAIT_SECONDS)


def classify_launch_answer(proc_alive: bool, log_text: "str | None", *,
                           _launch_failure_signature=None) -> str:
    """T-12607 — read a just-spawned worker launch as `LAUNCH_AUTH` / `LAUNCH_NON_ANSWER` /
    `LAUNCH_ANSWER`. PURE f(args): no I/O, no clock, no journal. This is the SOLE trigger for the
    reserve pair and for the wait.

    It adds NO signature list of its own. The causes are read by the EXISTING classifier
    `journal._launch_failure_signature` (T-10792 auth / T-11565 self-declared transient overload) —
    the one that already tells those two apart for the fleet reader, so there is no second reading of
    the same logs that could drift from it (CHARTER §P1 filter 1).

    The order is the rule, and every fall-through is toward «it answered»:
      (a) an AUTH signature is TERMINAL and wins any overlap — a credential failure is the one cause a
          wait cannot clear and a second model would die on identically (T-10792);
      (b) a self-declared TRANSIENT overload is the non-answer this whole path exists for;
      (c) the process is still ALIVE — a bootstrap legitimately runs for minutes, so a live process is
          an ANSWER, never a non-answer;
      (d) there is NO LOG AT ALL (`log_text is None` — the file does not exist or cannot be read) —
          this seam was handed no observation surface, so it has observed nothing and says so by
          answering ANSWERED. «No evidence» is not evidence of silence, and reading it as one would
          let an absent log switch pairs or start a wait on a worker nobody has looked at;
      (e) the process is DEAD and the EXISTING log is EMPTY — launched, never came up, no worker
          output at all: the card's second non-answer shape;
      (f) anything else — a dead bootstrap that DID produce output nothing recognises — is ANSWERED
          here: it is not a cause a reserve or a wait can clear, and an unexplained death is never
          relabelled as explained (the fail-closed rule `_launch_failure_signature`'s own docstring
          states, honoured here). It is NOT recorded as a launch, though: `launch_worker_with_pair`
          separates it from a live ANSWERED via `_bootstrap_death` (T-12896) and journals it as the
          premature_exit terminal carrying the log tail."""
    sig = None
    if _launch_failure_signature is not None:
        try:
            sig = _launch_failure_signature(log_text)
        except Exception:   # noqa: BLE001 — a classifier failure reads as «unrecognised», never a crash
            sig = None
    if sig == journal._STALL_DETAIL_AUTH:
        return LAUNCH_AUTH
    if sig == journal._STALL_DETAIL_USAGE_LIMIT:
        return LAUNCH_LIMIT         # (b') a usage limit: reserve once, never a wait (T-13157)
    if sig == journal._STALL_DETAIL_TRANSIENT:
        return LAUNCH_NON_ANSWER
    if proc_alive:
        return LAUNCH_ANSWER
    if log_text is None:
        return LAUNCH_ANSWER            # no observation surface ⇒ nothing observed (see (d) above)
    if not log_text.strip():
        return LAUNCH_NON_ANSWER
    return LAUNCH_ANSWER


def _probe_launch_answer(pid: int, log_path, *, _proc_alive, _read_log, _sleep, _monotonic,
                         _launch_failure_signature, probe_seconds: "float | None" = None) -> str:
    """T-12607 — watch ONE just-spawned launch until it is readable, and return the
    `classify_launch_answer` verdict. Returns EARLY the moment the reading is decidable: the instant
    the process is gone (its log is then final) or a recognised signature appears, whichever first.

    Bounded by construction — it returns `LAUNCH_ANSWER` when the window elapses with the process
    still alive, because a bootstrap that is still running IS an answer. So this can wait at most one
    probe window per attempt and can never itself become the hang it exists to prevent.

    Every collaborator is injected, so the whole seam is exercisable with no real process, no real
    clock and no real sleep."""
    deadline = _monotonic() + float(probe_seconds if probe_seconds is not None else _launch_probe_seconds())
    while True:
        alive = bool(_proc_alive(pid))
        text = _read_log(log_path)
        verdict = classify_launch_answer(alive, text,
                                         _launch_failure_signature=_launch_failure_signature)
        if not alive or verdict != LAUNCH_ANSWER:
            return verdict
        if _monotonic() >= deadline:
            return LAUNCH_ANSWER
        _sleep(_LAUNCH_PROBE_POLL_SECONDS)


#: T-12896 — the halt discriminator. It rides the EXISTING `premature_exit` kind (T-11926), so every
#: reader that already routes that kind routes this one; `phase` only says WHERE in the life it died.
BOOTSTRAP_DEATH_PHASE = "bootstrap"
#: T-12896 — the reason the DISPATCH token and the per-id line carry for a launch that did not come up.
BOOTSTRAP_DIED_REASON = "bootstrap-died"


def _bootstrap_death(res, task: str, *, _proc_alive, _read_log, _launch_failure_signature) -> "dict | None":
    """T-12896 (<project> X-1546 / X-1555) — the `bg_dispatch_halted` payload for a launch the probe
    WATCHED DIE during bootstrap, or None. Called ONLY after `_probe_launch_answer` returned ANSWERED.

    WHY THIS EXISTS. ANSWERED has two meanings the probe does not separate: the process is still up
    (a bootstrap in progress), or it died of something no signature recognises (arm (f) of
    `classify_launch_answer`). The second used to be written as `bg_dispatch_launched` + `LAUNCHED`,
    exit 0, over a process the launcher had just watched die — its cause (measured 2026-09-23: the
    host client rejected the requested model) lived only in the dispatch log, and for the ten-minute
    bootstrap grace the fleet reader called that corpse `working(still-booting)`, exactly as it calls a
    live worker. This separates them with one more read of each probe input — no new poll or window.

    FAIL-CLOSED, both halves asserted POSITIVELY — a false death would terminate a live worker's
    record, which is the X-1461 double-launch direction:
      * the pid reads PROVABLY gone. `_default_pid_alive` is False ONLY on ProcessLookupError and reads
        every doubt (bad pid, EPERM, any error) as alive; a recycled pid likewise reads alive;
      * the log EXISTS (`_read_log` is not None). A missing log is no observation surface — arm (d)
        of `classify_launch_answer`, honoured here unchanged: absence of evidence is never a death.

    The payload is the EXISTING `premature_exit` shape (T-11926 `journal._premature_exit_finding`), so
    the fleet reader renders it as `halted` / needs-decision with the log tail's last line, with no
    reader change. It differs only in who observed the death — the launch probe, not the watcher —
    which is what `phase` and `confirmed_death_basis` say."""
    pid = res.get("pid") if isinstance(res, dict) else None
    try:
        if _proc_alive(pid):
            return None
        text = _read_log(res.get("log_path"))
    except Exception:   # noqa: BLE001 — an unreadable observation is no observation, never a death
        return None
    if text is None:
        return None
    try:
        cause = _launch_failure_signature(text) if _launch_failure_signature is not None else None
    except Exception:   # noqa: BLE001
        cause = None
    return {
        "dispatch": task,
        "kind": "premature_exit",
        "phase": BOOTSTRAP_DEATH_PHASE,
        "expected": res.get("session_id"),
        "reason": (f"the dispatched worker for {task} DIED during bootstrap — the launch probe watched "
                   f"its process exit before it ran a single verb, so nothing was claimed and no "
                   f"worktree exists; the card is still ready. Its cause is the log tail on this row"),
        "cause": cause,
        "exit_status": None,
        "exit_status_unavailable": ("the worker is reparented onto init by "
                                    "_spawn_detached_from_caller_tree (T-11906), so the launcher is "
                                    "not its parent and cannot read its exit code"),
        "pid": pid,
        "proc_alive": False,
        "confirmed_death_basis": (f"launch probe: pid {pid} provably gone (ProcessLookupError) inside "
                                  f"the bootstrap probe window, before the worker's first verb — a "
                                  f"bootstrap death: no claim, no worktree"),
        "log": str(res.get("log_path")),
        # derived from the text ALREADY READ, never a second open of the path (audit-post
        # fp1:09b5e0c3fb852b32: a log rotated/removed between two reads would leave a halt that names
        # nothing), bounded by the SAME byte helper + bound the watcher's premature_exit row uses
        "log_tail": events._byte_tail(text, journal._DISPATCH_LOG_TAIL_BYTES),
    }


def _default_die(msg: str):
    """T-12607 — the fallback refusal for `launch_worker_with_pair` when no host `_die` is injected.
    FAIL-CLOSED: a seam whose refusal arm could be silently disabled by a missing injection would let
    an auth death be recorded as a launch, which is the whole defect audit-pre finding 2 named."""
    print(f"yitc-v2: {msg}", file=sys.stderr, flush=True)
    raise SystemExit(1)


def _launch_pair_row(_append_event, task, fingerprint: str, impact: str, data: dict) -> None:
    """T-12607 — append ONE `deviation_captured` row for a pair event (the switch, or a wait
    heartbeat). Best-effort BY CONSTRUCTION: journaling must never change the outcome of the launch it
    records, and an un-injected `_append_event` (a pinned double) simply records nothing."""
    if not _append_event:
        return
    try:
        _append_event("deviation_captured", task, {
            "relates_to": "dispatch-worker-pair-resolution",
            "impact": impact,
            "fingerprint": fingerprint,
            **data,
        })
    except Exception:   # noqa: BLE001
        pass


def auth_refusal_message(task: str) -> str:
    """T-12607 (SPEC-0072 rule 7) — the ONE formatter of the AUTH refusal, so the message has a single
    home a probe can be pinned to (audit-post finding 3, AC3). It was inline in the arm below, which
    let a probe assert only the fragments it happened to name while the rest of the established
    wording drifted underneath it. There is nothing tier- or pair-specific in it on purpose: the
    credential is GLOBAL, so the same refusal is correct on the first probe and on any retry."""
    # T-12645 — «no launch is recorded» was true when nothing had been journaled for this task by the
    # time we got here. It no longer is: the spawn is recorded the instant it happens, so the honest
    # statement is that the spawn was recorded AND terminated, which is what a reader folding the
    # journal will actually see. Saying otherwise would send them looking for a row that is there.
    return (f"dispatch: {task} — the launch died on a provider AUTHENTICATION signature, so NO "
            f"worker is running. The spawn was recorded and has been journaled as HALTED "
            f"(bg_dispatch_halted, kind launch_auth_failed), so the fleet reads it as a dead worker "
            f"needing a decision — not as a live one. This is NOT a capacity failure: no "
            f"reserve pair is tried and no wait is entered, because a second model dies "
            f"identically and a retry re-dies until the CREDENTIAL is restored (T-10792). "
            f"Restore the provider credential, then re-dispatch.")


def launch_worker_with_pair(attempt, task: str, tier: str, primary: "tuple[str, str]",
                            reserve: "tuple[str, str | None] | None", *,
                            _append_event=None, _proc_alive=None, _read_log=None,
                            _launch_failure_signature=None, _die=None,
                            _sleep=None, _monotonic=None, probe_seconds=None,
                            wait_seconds=None, _reap=None) -> dict:
    """T-12607 (SPEC-0072 rule 7) — THE ONE seam that owns the primary/reserve resolution for a worker
    launch. The `invoke_auditor_tiered` analog (T-12606), at the dispatch seam.

    `attempt(model, effort) -> dict` performs ONE complete launch try — a FRESH worker identity, a
    fresh log, its own seed-read bootstrap receipts, the spawn — and returns at least
    `{"pid", "log_path"}`. It lives in the caller because composing a worker's identity and brief is
    the launcher's job, not this policy's; what lives HERE is only WHICH pair gets tried and when.

    The rule, in order:
      * the PRIMARY launches and is probed. It ANSWERED — the process is up, or it died of something
        this seam deliberately does not claim to understand — and that launch is returned. A process
        that died (pid provably gone, log present) is returned carrying `bootstrap_died` after its
        `bg_dispatch_halted{kind: premature_exit, phase: bootstrap}` is recorded (T-12896), so the
        caller writes no launch row for it;
      * an AUTH failure is NOT a non-answer: NO switch and NO wait, and it REFUSES naming the
        CREDENTIAL before any launch is recorded — a second model would die identically and a wait
        would never clear it (T-10792). This arm is applied after EVERY primary probe — the first one
        AND each no-reserve retry — because a credential can expire DURING a wait, and a retry that
        dies on auth must refuse rather than be returned as a launch for a worker already dead;
      * a NON-ANSWER with a RESERVE declared → the reserve launches ONCE, at its OWN model AND effort.
        A reserve is a PAIR or it is nothing: a `reserve:` naming only one half resolves to NO reserve
        at all (the resolver's fail-closed read), so this arm is never entered with a half-pair and the
        wait arm below takes it instead. The switch is journaled naming BOTH pairs, and it happens
        ONCE: if the reserve does not come up either,
        that is a genuine two-door outage and today's launch-stall is the honest record of it;
      * a NON-ANSWER with NO reserve declared → NO switching at all. The primary is retried until it
        comes up, with a journaled heartbeat before every wait, so a waiting dispatch is VISIBLY
        waiting instead of leaving a bare launch-stall for a human to notice. The loop has NO retry
        budget on purpose — a budget that expires would be exactly that stall again.

    Returns the winning `attempt` dict, plus `pair` (`primary`|`reserve`) and the `model`/`effort` that
    actually ran — so the caller records WHICH pair the worker runs on and a card's effort tier can
    never silently disagree with the model that did the work.

    Every probe/wait collaborator is OPTIONAL: with none injected this function launches ONCE on the
    primary and returns, byte-identical to the pre-T-12607 launcher."""
    p_model, p_effort = primary
    out = dict(attempt(p_model, p_effort))
    out.update({"pair": "primary", "model": p_model, "effort": p_effort})
    if _proc_alive is None or _read_log is None:
        return out                      # probe not wired ⇒ the historical fire-and-forget launch

    _sleep = _sleep if _sleep is not None else time.sleep
    _monotonic = _monotonic if _monotonic is not None else time.monotonic

    def _probe(res):
        return _probe_launch_answer(res["pid"], res["log_path"], _proc_alive=_proc_alive,
                                    _read_log=_read_log, _sleep=_sleep, _monotonic=_monotonic,
                                    _launch_failure_signature=_launch_failure_signature,
                                    probe_seconds=probe_seconds)

    def _refuse_if_auth(verdict):
        # NOT a non-answer: no switch, no wait — the credential needs a HUMAN (T-10792). And it REFUSES
        # (audit-pre finding 2, absorbed mode-a): returning the launch would record a
        # `bg_dispatch_launched` row for a worker that is DEMONSTRABLY ALREADY DEAD, so the fleet would
        # read a corpse as a launched worker and the controller would wait on it. Refusing BEFORE that
        # row is the honest record — nothing is running, so nothing is claimed to be. The refusal is
        # all-or-nothing for the wave by construction, which is right: the credential is GLOBAL, so
        # every later launch in the wave dies identically. It joins the routing preflight's own
        # fail-closed posture rather than adding a second one.
        #
        # ONE auth arm, applied after EVERY primary probe — the first AND each no-reserve retry
        # (audit-post finding 2, AC3). A credential can expire DURING a wait: the primary is first
        # refused for capacity, and the retry after the wait dies on auth. Reading that second probe as
        # merely «not a non-answer» would return a launch for a worker already dead — the exact
        # corpse-recorded-as-launched row the auth arm exists to prevent, arrived at by the slower road.
        if verdict != LAUNCH_AUTH:
            return False
        # T-12645 — RECORD THE DEATH, because the spawn is now recorded. Before this card the auth arm
        # could refuse in silence and be honest doing it: nothing had been journaled for this task yet,
        # so «no worker is running and no launch is recorded» was literally true. It no longer is — the
        # `bg_dispatch_spawned` row is already on main by the time we get here, and the launch AXIS
        # (journal.DISPATCH_LAUNCH_TYPES) folds it as a started worker. Leaving it unterminated would
        # make the fleet read a CORPSE as a live worker — the exact false-alive the auth arm was
        # written to prevent (T-10792), merely relocated one row earlier. `bg_dispatch_halted` is in
        # DISPATCH_TERMINAL_TYPES, so this supersedes the spawn row for every reader at once, and the
        # halt correctly reads needs-decision: restoring the credential IS a human decision.
        # NOT best-effort (audit-post fp1:43f4edd22de19068). This terminal is the ONLY thing standing
        # between a durable `bg_dispatch_spawned` receipt and a fleet that reads a CORPSE as a live
        # worker, so recording it best-effort while recording the spawn transactionally was a
        # reachable fail-open: a single failed append re-created, one row later, exactly the false
        # reading this card exists to remove. It goes through the SAME retrying recorder the spawn
        # receipt uses, and the failure has a consequence rather than a `pass`.
        _refuse = _die if _die is not None else _default_die
        _unterminated = False
        if _append_event:
            _ok, _err = _record_launch_row(
                "bg_dispatch_halted", task,
                {"dispatch": task, "kind": "launch_auth_failed",
                 "reason": "the worker launch died on a provider AUTHENTICATION signature — the "
                           "spawned process is dead; restore the credential, then re-dispatch"},
                _append_event=_append_event, _sleep=_sleep)
            _unterminated = not _ok
        else:
            _unterminated = True
        if _unterminated:
            # The journal would not take the terminal. Two things still hold the line, and neither
            # needs a writable journal: the dead bootstrap is REAPED, so the session-ref LIVENESS axis
            # (`_session_proc_alive`) reads dead beside the recency axis and the row ages out rather
            # than persisting as `working`; and the refusal NAMES the un-terminated receipt so a human
            # can clear what the process could not. Silence here was the fail-open.
            (_reap or _default_reap_worker)(out.get("pid") if isinstance(out, dict) else None)
            _refuse(auth_refusal_message(task) +
                    f" WARNING: the `bg_dispatch_halted` terminal for {task} could NOT be written to "
                    f"the journal, so its `bg_dispatch_spawned` receipt is UN-TERMINATED. The dead "
                    f"bootstrap has been reaped (so liveness reads dead), but until the journal is "
                    f"writable a recency-only read of that row may still show this worker as "
                    f"working — clear it with `yitc-v2 dispatch --stop --task {task}` once the "
                    f"journal accepts writes.")
            return True
        _refuse(auth_refusal_message(task))
        return True     # only when an injected non-exiting `_die` double returns; the real one exits

    def _answered(res):
        # T-12896 — ANSWERED is «still up» OR «died of something unrecognised» (arm (f)). Separate
        # them: a death the probe watched is recorded as the EXISTING premature_exit terminal through
        # the SAME retrying recorder the spawn receipt and the auth terminal use, and handed to the
        # caller as `bootstrap_died` so it writes no launch row over a corpse (a newer launch row
        # would segment this halt away — the T-10095 newest-launch segmentation). A failed record is
        # NOT a refusal here: the process is already dead, so the un-terminated spawn receipt reads
        # `proc-gone` on the launch axis (T-12660); the caller names it loudly instead.
        payload = _bootstrap_death(res, task, _proc_alive=_proc_alive, _read_log=_read_log,
                                   _launch_failure_signature=_launch_failure_signature)
        if payload is None:
            return res
        ok = False
        if _append_event:
            ok, _err = _record_launch_row("bg_dispatch_halted", task, payload,
                                          _append_event=_append_event, _sleep=_sleep)
        res = dict(res)
        res.update({"bootstrap_died": payload, "bootstrap_recorded": bool(ok)})
        return res

    verdict = _probe(out)
    if verdict == LAUNCH_ANSWER:
        return _answered(out)
    if _refuse_if_auth(verdict):
        return out      # unreachable when `_die` exits; kept so an injected non-exiting double is sane

    if reserve:
        r_model, r_effort = reserve
        _launch_pair_row(
            _append_event, task, WORKER_RESERVE_SWITCH_FINGERPRINT,
            "the effort tier's PRIMARY worker pair did not come up; its RESERVE pair was launched",
            {"tier": tier, "primary": {"model": p_model, "effort": p_effort},
             "reserve": {"model": r_model, "effort": r_effort}},
        )
        print(f"dispatch: {task} — the {tier} PRIMARY pair ({p_model}/{p_effort}) did not come up — "
              f"switching ONCE to its RESERVE pair ({r_model}/{r_effort}) (T-12607).",
              file=sys.stderr, flush=True)
        res = dict(attempt(r_model, r_effort))
        res.update({"pair": "reserve", "model": r_model, "effort": r_effort,
                    "primary_model": p_model, "primary_effort": p_effort})
        return res

    if verdict == LAUNCH_LIMIT:
        # T-13157 — a usage limit resets in HOURS, so the minutes-paced wait loop below would only spin.
        # No reserve declared ⇒ record the bootstrap death (premature_exit, cause usage-limit) and stop.
        return _answered(out)

    # NO reserve declared — WAIT on the primary and retry it. Never switch, never leave a stall here.
    _wait = float(wait_seconds if wait_seconds is not None else _launch_wait_seconds())
    tries = 1
    while True:
        tries += 1
        _launch_pair_row(
            _append_event, task, WORKER_NO_RESERVE_WAIT_FINGERPRINT,
            "the effort tier's PRIMARY worker pair did not come up and the tier declares NO reserve — "
            "waiting on the primary and retrying it",
            {"tier": tier, "attempt": tries, "wait_seconds": _wait,
             "primary": {"model": p_model, "effort": p_effort}},
        )
        print(f"dispatch: {task} — the {tier} PRIMARY pair ({p_model}/{p_effort}) did not come up and "
              f"this tier declares no reserve — waiting {_wait:g}s, then retry #{tries} (T-12607).",
              file=sys.stderr, flush=True)
        _sleep(_wait)
        out = dict(attempt(p_model, p_effort))
        out.update({"pair": "primary", "model": p_model, "effort": p_effort})
        verdict = _probe(out)
        if verdict == LAUNCH_NON_ANSWER:
            continue
        if _refuse_if_auth(verdict):    # an auth death on a RETRY refuses exactly as the first probe does
            return out
        return _answered(out)


def _launch_axis_events(evs, DISPATCH_TERMINAL_TYPES):
    """T-12645 — the launch-axis SUBLIST (see `_launch_axis_class` for what the axis is and why it has
    both halves). Split out because the in-flight guard needs the EVENTS as well as the class: it reads
    the newest launch row's ENVELOPE `session_ref` to name the SIBLING CONTROLLER that holds the id
    (T-10254), which the classified 4-tuple deliberately does not carry."""
    return [e for e in evs
            if e.get("type") in journal.DISPATCH_LAUNCH_TYPES
            or e.get("type") in DISPATCH_TERMINAL_TYPES]


def _launch_axis_class(evs, task, _classify_dispatch, DISPATCH_TERMINAL_TYPES, *, _pid_alive=None,
                       _session_alive=None, _scan_takeable=None):
    """T-12645 — classify a task on the LAUNCH AXIS: «has a worker been STARTED for this id, and has
    anything terminated it?». Returns the `_classify_dispatch` 4-tuple, or `("none", "", None, None)`
    when the axis is empty — EXCEPT that a `working`/`recent` verdict is re-read against the recorded
    pid's liveness and DOWNGRADED to `launch-stall`/`proc-gone` when that pid provably does not exist
    (T-12660), or when the fleet verdict's own `--session-id` scan provably finds no worker (T-12924;
    the reasoning, the scope and the fail direction of both are at that seam below).

    ONE definition, two call sites — the in-flight SKIP guard below and the PREFIX/REMAINDER block
    (`wave_prefix_and_remainder`). They must never disagree: a block that named an id as a launched
    prefix while the guard went on to launch it would be worse than printing nothing, because it would
    read as a confirmation. Extracting the computation is what makes agreement structural rather than
    a promise, and it keeps a single classifier path (SPEC-0133 rule 5) — this helper adds no
    classification of its own, it only selects the events `_classify_dispatch` is asked about.

    The sublist is the launch AXIS (`journal.DISPATCH_LAUNCH_TYPES` — `bg_dispatch_launched` PLUS
    T-12645's `bg_dispatch_spawned`) TOGETHER WITH the launch-terminating terminals. Both halves are
    load-bearing and predate/postdate each other for different reasons:
      * the TERMINALS are T-10376's: a bare launched-only filter stripped every terminal, so a HALTED
        launch could never read terminal on this axis and a stopped rogue needed `--force`;
      * the SPAWN type is this card's: without it a worker whose parent died inside the
        spawn->launch-row window reads `none` here, the SKIP does not fire, and the wave
        double-launches a live worker (X-1461, measured).
    X-0131 stays intact either way: filed/skip/commit noise carries neither a launch nor a terminal,
    so a never-launched id still never phantom-skips."""
    axis = _launch_axis_events(evs, DISPATCH_TERMINAL_TYPES)
    if not axis:
        return ("none", "", None, None)
    cls, detail, last_ts, sref = _classify_dispatch(axis, task)
    # T-12660 — CONSULT LIVENESS BEFORE RETURNING THE ONE RECENCY-ONLY VERDICT THIS AXIS CAN REACH.
    #
    # THE FAIL-OPEN, with its full precondition. `_classify_dispatch` DOES consult liveness — but only
    # inside branches this axis cannot enter. The launch-stall / still-booting branch is gated on
    # `identity == "not-yet-started"`, and this call passes no identity; `alive-proc` needs a STALE
    # journal; `landing` needs a `blocked_on_land` terminal; `audit-heartbeat` needs the audit phase,
    # which keys on stage events the axis filters out. So the only reachable non-terminal verdict here
    # is `working`/`recent`, decided by the launch row's OWN timestamp and nothing else. When the
    # T-12645 auth arm's BOTH `bg_dispatch_halted` appends fail and the spawned worker is reaped, the
    # durable `bg_dispatch_spawned` receipt survives un-terminated — and a recency-only reader calls
    # that corpse `working` (audit-post fp1:227ccd1ce7e72d15, class reachable-fail-open). The
    # consequence is operational, not cosmetic: the in-flight SKIP declines to re-dispatch a task
    # whose worker is dead, and the PREFIX/REMAINDER block names it as a launched prefix.
    #
    # SCOPED TO `recent` ON PURPOSE. Every other `working` detail arrived at its verdict THROUGH a
    # liveness or heartbeat consultation, so re-deciding it here would be a second opinion on an
    # answered question — and a second classifier path is exactly what SPEC-0133 rule 5 forbids. This
    # helper still adds no classification of its own; it declines ONE verdict on evidence the
    # classifier was never given.
    #
    # THE FAIL DIRECTION IS THE WHOLE SAFETY ARGUMENT. `_default_pid_alive` returns False ONLY on
    # ProcessLookupError — a pid that provably does not exist — and fails OPEN to alive on a bad pid,
    # a PermissionError, or any other read failure; a REUSED pid likewise reads alive. So this can
    # never fire on doubt, and needs no `_proc_scan_is_takeable` companion: that question exists for
    # the exhaustive `--session-id` HOST scan, whose negative is indefinite, while a targeted
    # `os.kill(pid, 0)` ENOENT is definite on its own. The INVERSE direction — reading a LIVE worker
    # as dead — is the X-1461 double-launch this axis was created to prevent, and no path here
    # reaches it. NO lock, reservation or wait is introduced: the DELIBERATELY advisory, recency-only
    # in-flight guard keeps its documented semantics, and the T-0525 reservation question (wont-do)
    # is neither reopened nor touched.
    if cls != "working" or detail != "recent":
        return (cls, detail, last_ts, sref)
    newest = next((e for e in reversed(axis)
                   if e.get("type") in journal.DISPATCH_LAUNCH_TYPES), None)
    data = newest.get("data") if isinstance(newest, dict) else None
    data = data if isinstance(data, dict) else {}
    pid = data.get("pid")
    # a pre-T-0558 row carries no pid — nothing to probe on the pid arm (the scan below may still run)
    if pid is not None and not (_pid_alive or _default_pid_alive)(pid):
        return ("launch-stall", journal._STALL_DETAIL_PROC_GONE, last_ts, sref)
    # T-12924 (<project> X-1573) — AGREE WITH THE FLEET VERDICT'S PROCESS SCAN before asserting «real,
    # running». `os.kill(pid, 0)` answers «does SOME process own this pid», not «is the worker running»:
    # a ZOMBIE (reparented, un-reaped) and a REUSED pid both pass it. The fleet verdict instead reads the
    # exhaustive `--session-id <expected>` scan, qualified by `_proc_scan_is_takeable` so only a DEFINITE
    # negative counts — and the two surfaces contradicted each other on the same task at the same moment.
    # So this seam takes the SAME pair of reads, never a second liveness model.
    #
    # FAIL TOWARD PROTECTED, three ways, because the inverse error is the X-1461 double launch:
    #   * only a row whose ADAPTER DECLARED the `--session-id` argv is scanned (`session_id_argv`,
    #     recorded at spawn off the adapter actually spawned). A codex worker, a replacement adapter
    #     registered under the same provider name, and every row written before this card carry no such
    #     argv — a scan would read those LIVE workers dead (audit-pre fp1:10aa3715725cd9cf);
    #   * the probe keys on `expected`, the worker's OWN assigned ref — never the dispatcher's envelope
    #     ref, which would point the scan at the always-alive controller (T-10254);
    #   * an un-takeable scan (hidepid, an unreadable cmdline) is INDEFINITE, and keeps the verdict.
    # Cost: one /proc walk, only on this `working`/`recent` arm of a declared row — the same walk the
    # fleet verdict and `_orphan_holder_liveness` already take.
    expected = data.get("expected")
    if (data.get("session_id_argv") is True and expected
            and (_scan_takeable or _default_proc_scan_is_takeable)()
            and not (_session_alive or _default_session_proc_alive)(expected)):
        return ("launch-stall", journal._STALL_DETAIL_PROC_GONE, last_ts, sref)
    return (cls, detail, last_ts, sref)


def wave_prefix_and_remainder(tasks, classify) -> dict:
    """T-12645 (X-1460/X-1461) — split a REQUESTED wave into the PREFIX that is already running and the
    REMAINDER that is not. Pure: no journal read, no clock, no I/O — `classify(task) -> class-string`
    is injected, and in production it is `_launch_axis_class`, the very predicate the in-flight SKIP
    decides on.

    WHY THIS EXISTS. `dispatch --task A --task B --task C` launches SEQUENTIALLY (~50s/worker,
    measured), so a wave of three CANNOT fit a 120s foreground cap and is killed part-way. The killed
    parent prints nothing conclusive, and the operator is left holding a command that failed —
    which reads as «none of it happened». It is not: the launched prefix is REAL and its workers
    survive their parent. Re-running the whole wave therefore double-launches the prefix, which is
    precisely what <project> did on 2026-09-16 after filing the defect.

    So a capped sequential launcher is a PREFIX OPERATION, and this is that rule made mechanical
    rather than documented: the launched set and the remainder are both NAMED, in the order requested,
    from durable state — so an operator cannot mistake a prefix for a total failure, and does not have
    to hand-fold `bg_dispatch_launched` rows to find out which is which.

    An id counts as LAUNCHED iff its launch-axis class is `working` — a started, non-terminated,
    non-stale worker. Anything else (a stale prior epoch, a halted launch, never launched at all) is
    REMAINDER and is dispatched normally; that is deliberate and is what keeps this from freezing a
    genuinely re-dispatchable id."""
    launched, remainder = [], []
    for t in tasks:
        (launched if str(classify(t) or "") == "working" else remainder).append(t)
    return {"launched": launched, "remainder": remainder}


def _wave_prefix_block(report: dict) -> str:
    """T-12645 — render `wave_prefix_and_remainder` for the operator. Report-only: it drives no control
    flow (the SKIP that follows is the pre-existing in-flight guard), and it NAMES both sets rather
    than counting them, because a count is exactly what a reader cannot act on."""
    launched = report.get("launched") or []
    remainder = report.get("remainder") or []
    return (
        "dispatch: THIS WAVE IS A PREFIX OPERATION (T-12645).\n"
        f"  ALREADY LAUNCHED ({len(launched)}) — real, running, and NOT re-launched below: "
        f"{', '.join(launched)}\n"
        f"  REMAINDER ({len(remainder)}) — the only ids this invocation launches: "
        f"{', '.join(remainder) if remainder else '(none — nothing left to launch)'}\n"
        "  A sequential launcher killed by a foreground cap leaves a LAUNCHED PREFIX, not a total\n"
        "  failure: re-running the whole wave would double-launch it. The launched ids above are\n"
        "  skipped by the in-flight guard; re-fold `journal query --dispatch-status` to watch them.")


def _resolve_dispatch_routing(tasks: "list[str]", args: argparse.Namespace, *,
                              _find_task_yaml, _read_yaml, _die, _resolve_effort_routing,
                              EFFORT_TIERS, EFFORT_TIER_DEFAULT,
                              _task_decomposed_from_pre_executing_plan, _append_event,
                              refusal_events_path=None) -> "list[dict]":
    """T-0733 (SPEC-0072): the effort-tier routing PREFLIGHT — resolve each task's worker (model,
    effort) BEFORE any spawn, aligned 1:1 with `tasks`, all-or-nothing (a fail-closed `_die` here
    launches NOTHING, mirroring the brief preflight). For each task:
      - the card must EXIST (T-11915): `path is None` — no `tasks/<id>-*.yaml` at all — FAILS CLOSED
        naming the id, so a wave never spawns a worker onto a non-existent task. This is DISTINCT from
        an absent effort_tier KEY on a card that does exist (the legacy-safe default below).
      - tier = the card's `effort_tier` (read from its YAML), defaulting to `normal` when ABSENT
        (legacy-safe — no backfill); a PRESENT-but-non-whitelisted value FAILS CLOSED (Y-F2 — never
        coerce garbage to a default).
      - (cfg_model, cfg_effort) = the tier->map lookup (bin/effort-routing-config.yaml, the sole source).
      - OVERRIDE WINS PER-FIELD (F1): an explicit `dispatch --model/--effort` (invocation-level escape
        hatch, applies to every task) takes precedence over the map for the field it sets.
      - FAIL CLOSED (F2): if, after overrides, model OR effort is still unresolved for a KNOWN tier,
        `_die` — NEVER silently downgrade a critical task to the provider default; surface the broken
        /missing routing config.
    Returns a list of {model, effort, source_tier, override} dicts (the values recorded on the event)."""
    override_model = (getattr(args, "model", None) or "").strip() or None
    override_effort = (getattr(args, "effort", None) or "").strip() or None
    override_used = bool(override_model or override_effort)
    routing: "list[dict]" = []
    no_premise: "list[str]" = []   # T-11989 — REPORT-ONLY, see the line printed after this loop
    ac_unmeasured: "list[str]" = []   # T-12540 — REPORT-ONLY, printed beside the premise line

    def _journal_refusal(task, reason):
        # T-12897 (X-1547) — a preflight refusal used to `_die` with NO journal row, so the status view
        # could not tell a REFUSED dispatch from one never attempted: the only witness was this verb's
        # own stdout. Record it on the launcher's own dispatch-OUTCOME row (`bg_dispatch_skipped`, whose
        # outcome vocabulary already carries `refused`, T-11844) — NOT `read_gate_refused`: these are
        # validation refusals, not read gates. `--dispatch-status` names the row as the id's current
        # epoch. Bound to MAIN's journal like every other `bg_dispatch_skipped` row (`refusal_events_path`,
        # passed by `cmd_dispatch`). RECORD-ONLY: the `_die` that follows is unchanged, so the wave stays
        # all-or-nothing — and a record that cannot be written (a write-boundary guard exits) must never
        # replace the refusal message with its own, so its failure is swallowed and the refusal proceeds.
        kw = {"events_path": refusal_events_path} if refusal_events_path is not None else {}
        try:
            _append_event("bg_dispatch_skipped", task,
                          {"dispatch": task, "reason": reason, "outcome": "refused", "held_by": None},
                          **kw)
        except (Exception, SystemExit):   # noqa: BLE001 — the refusal, not its record, is the contract
            pass

    for task in tasks:
        path = _find_task_yaml(task)
        # T-11915 — ABSENT CARD is not an absent KEY. A `--task` id with NO card on disk used to read
        # as `{}` here: the SPEC-0166 premise block found nothing to block on, the missing
        # `effort_tier` key took the legacy-safe default tier, and the wave SPAWNED A WORKER ONTO AN
        # ID THAT DOES NOT EXIST (the 2026-08-19 T-11317 firing — the build was wasted and the
        # controller was left believing a card existed). The two cases must stay DISTINCT: a card that
        # EXISTS but omits `effort_tier` is the legacy-safe default-tier path and keeps working
        # unchanged; only `path is None` (no card at all) refuses. Reuses this preflight's EXISTING
        # fail-closed `_die` — all-or-nothing, BEFORE any spawn, so nothing launches.
        if path is None:
            _journal_refusal(task, "no-card")
            _die(f"dispatch: task {task} has NO card on disk (no tasks/{task}-*.yaml) — refusing to "
                 f"launch a worker onto an id that does not exist (SPEC-0072 fail-closed preflight; "
                 f"nothing launched). File the card first, or fix the id.")
        card = _read_yaml(path) or {}   # T-11915: path is non-None here
        # T-0779: distinguish ABSENT key (→ default normal, legacy-safe) from PRESENT-but-invalid
        # by KEY PRESENCE, not truthiness. The prior `card.get(...) or EFFORT_TIER_DEFAULT` collapsed
        # any present falsey value (0, false, null, empty string) to the default, silently bypassing
        # the SPEC-0072 fail-closed refusal. A present value now stringifies and is rejected by the
        # whitelist check below — mirroring the filing-time validate block in cmd_task_file.
        # SPEC-0166: dispatchability gate (preflight — refuse the WHOLE wave BEFORE any spawn, so a
        # non-verified imported card never reaches a worker). Same pure predicate the claim gate uses.
        premise_block = task_mod._premise_dispatch_block(card)
        if premise_block:
            _journal_refusal(task, "premise-not-dispatchable")
            _die(f"dispatch: task {task} NOT dispatchable — {premise_block} (SPEC-0166 dispatchability "
                 f"gate; fail-closed preflight — nothing launched).")
        # T-12403 (SPEC-0070 §5 claim-block PARITY) — refuse a cut card of a PRE-EXECUTING plan HERE,
        # in the same fail-closed preflight, BEFORE any spawn. Previously this module referenced the
        # predicate nowhere: the wave launched, the worker paid a full bootstrap, and THEN its
        # `worktree new` claim-block refused it pre-claim (measured as a side-door on <project> X-1375).
        # The SAME single injected predicate the claim surfaces use — the `_premise_dispatch_block`
        # shape directly above (one predicate, three call sites), so no third reading of the rule.
        # The event is `read_gate_refused` per this card's AC2, not the claim surfaces' `claim_refused`:
        # this is a pre-LAUNCH gate refusal, no claim was attempted. The kind vocabulary is open at
        # this seam by shipped precedent (bin/lib/audit.py — `finding-fields-missing` /
        # `post-verification-fill`). Safe against the fleet reader: `_classify_dispatch`'s post-launch
        # `read_gate_refused` corroboration only runs when a `bg_dispatch_launched` row exists for the
        # id, and this path writes none (the `_die` is all-or-nothing, so nothing in the wave launches).
        pre_exec = _task_decomposed_from_pre_executing_plan(card)
        if pre_exec:
            slug, pst = pre_exec
            _append_event("read_gate_refused", task, {"verb": "dispatch", "kind": "claim-block",
                                                      "reason": "plan-pre-executing",
                                                      "plan": slug, "plan_status": pst})
            _die(f"dispatch: task {task} is decomposed_from plan {slug!r} at status={pst!r} "
                 f"(pre-`executing`) — its cut is not yet decomposition-fidelity-audited, so no card "
                 f"is claimable and a worker launched onto it would be refused pre-claim (SPEC-0070 §5 "
                 f"claim-block; fail-closed preflight — nothing launched).\n"
                 f"next: `yitc-v2 plan stage executing {slug}` — then dispatch this card.")
        # T-11989 — REPORT-ONLY. Since `task intake` runs over ANY ready card, a card with no
        # `premise` record is one nobody has run the cheap check over; 64 workers in a fortnight
        # refused pre-claim on a premise a free classifier could have read. So the absence is worth
        # SAYING at the one seam that is about to spend a bootstrap on it — and worth nothing more
        # than saying. This NEVER refuses, never filters the wave and never moves an exit code (the
        # consult's premise-only guard + CHARTER non-goal #7: filing/dispatch are not blocked). It is
        # collected here, beside the gate it is deliberately NOT, and printed once after the loop.
        # T-12783: selected by intake's OWN admission predicate — a non-ready card or one already
        # carrying a verdict (incl. `unclassifiable`) is never named, so following the line always acts.
        if task_mod._premise_intake_admits(card):
            no_premise.append(task)
        # T-12540 — REPORT-ONLY, same posture as the premise line: the T-12251/T-12283 filing advisory
        # lives only on `task file` stdout, which a Controller can filter away; echo it at launch.
        if task_mod._ac_unmeasured_bounds(card.get("acceptance")):
            ac_unmeasured.append(task)
        if "effort_tier" not in card:
            tier = EFFORT_TIER_DEFAULT
        else:
            tier = str(card["effort_tier"]).strip()
        if tier not in EFFORT_TIERS:
            _journal_refusal(task, "effort-tier-invalid")
            _die(f"dispatch: task {task} has effort_tier={tier!r} (not one of {list(EFFORT_TIERS)}) — "
                 f"refusing to launch on an unrecognized tier (SPEC-0072 fail-closed). Fix the card.")
        cfg_model, cfg_effort = _resolve_effort_routing(tier)
        model = override_model or cfg_model
        effort = override_effort or cfg_effort
        if model is None or effort is None:
            _journal_refusal(task, "effort-tier-unresolved")
            _die(f"dispatch: task {task} tier {tier!r} did not resolve to a (model, effort) — "
                 f"bin/effort-routing-config.yaml is missing/incomplete for this tier and no explicit "
                 f"--model/--effort override was given. Refusing to silently downgrade (SPEC-0072 §3 "
                 f"fail-closed); fix the routing config or pass --model/--effort.")
        routing.append({"model": model, "effort": effort, "source_tier": tier, "override": override_used})
    # T-11989: the report-only line — emitted AFTER the fail-closed preflight (so a genuine refusal is
    # never buried under advice) and BEFORE any spawn. Every task in `tasks` is still launched.
    #
    # ON STDERR, DELIBERATELY. dispatch's STDOUT is a CONTRACTED surface: the terminal
    # `DISPATCH: <VERDICT>` token (T-11844) and the single-task output shape pinned as a FULL-OUTPUT
    # byte equality by T-11795 AC3, whose whole point is that "the common path must not move" — an
    # extra informational line there breaks callers that parse the stream, which is the regression
    # that guard exists to catch. This line is ADVISORY, so it belongs on the diagnostic channel, the
    # same split the land verify-heartbeat and the `watch` diagnostics already use (`file=err`, the
    # verdict/gate unchanged). The advice reaches a human operator identically; the machine contract
    # is untouched. Capture wide, gate narrow.
    if no_premise:
        print(f"dispatch: {len(no_premise)} card(s) in this wave carry NO premise record — "
              f"{', '.join(no_premise)}. The SPEC-0166 premise check is cheap and these have not had "
              f"it: `yitc-v2 task intake --task <id>` records the verdict before a worker spends a "
              f"bootstrap on a premise that may not hold. REPORT-ONLY — nothing is gated and this "
              f"wave launches unchanged (T-11989).", file=sys.stderr, flush=True)
    if ac_unmeasured:
        print(f"dispatch: {len(ac_unmeasured)} card(s) in this wave carry an AC numeric bound with no "
              f"named reference (report-only heuristic) — {', '.join(ac_unmeasured)}: rewrite the "
              f"criterion as the qualitative outcome and record the number as evidence — a named "
              f"measurement does not make a decreed bound a criterion (SPEC-0060 item 4). REPORT-ONLY — "
              f"this wave launches unchanged (T-12540).", file=sys.stderr, flush=True)
    return routing


def _worker_seed_bootstrap_events(session_id: str, *, SEED_READ_NODE_ID: str,
                                  HELP_INVENTORY_NODE_ID: str, project: str) -> "list[tuple]":
    """T-10083 — the GOVERNED worker seed-read bootstrap (the RECEIPT-producing CODE PATH, not the
    preamble; audit-pre finding #1). Return the ORDERED (event_type, task_id, data) triples the
    launcher appends to MAIN's journal for the ASSIGNED worker session_ref, BEFORE the spawn — so the
    worker's FIRST governed verb (`worktree new --task`, the claim) finds its `session_started` anchor
    + the `seed_read` + verb-inventory receipts ALREADY present and PASSES the SPEC-0050 §8 read-gates
    without the worker running `session start` first.

    The dispatch chicken-and-egg this closes: the worker seed (the `graph/worker-seed.md` part chain)
    auto-injects only on `cd` INTO the task worktree, but `worktree new` is gated BEFORE the worktree exists (and a
    fresh worker has emitted no `session_started` for its ref) — so a worker would deadlock on its own
    first claim. Emitting the receipts here (governed, at the spawn chokepoint) removes the deadlock and
    GUARANTEES `seed_read` PRECEDES `worktree_created` by construction (these are appended pre-spawn; the
    worker emits `worktree_created` later).

    The receipts are the emit ANALOG of `session start`'s own (SPEC-0025): a `cli_invoked` row carrying
    the seed / help sentinel `node_id` — the SAME evidence the `_fetched_spec_ids` read-gate window
    reads. `session_started` LEADS so it anchors the receipt window (SPEC-0050 §2 fail-closed anchor).
    PURE (no side effects): the testable core of the bootstrap-ordering guarantee. NOTE: worktree
    STAGE-verbs (`task analyze`/`audit`/`task commit`/`task close`) run `_require_reads`, which is
    CURRENT-JOURNAL-ONLY (SPEC-0050 §2) — the worker re-anchors THAT checkout with a per-worktree
    `session start` (the established §2 norm, surfaced in DISPATCH_WORKER_PREAMBLE); this launcher
    bootstrap covers only the pre-worktree claim gates on MAIN."""
    return [
        ("session_started", None, {"type": "build", "project": project, "bootstrap": "dispatch"}),
        ("cli_invoked", None,
         {"verb": "session start", "node_id": SEED_READ_NODE_ID, "bootstrap": "dispatch"}),
        ("cli_invoked", None,
         {"verb": "--help", "node_id": HELP_INVENTORY_NODE_ID, "bootstrap": "dispatch"}),
    ]


def _inflight_events(task, _dispatch_status_events, _dispatch_events_tail_first):
    """T-10397 — the events every in-flight guard below classifies on, read TAIL-FIRST when the host
    injects the tail-first reader. The whole soundness argument (a tail POSITIVE carries the entire
    newest-launch epoch and is exact; a tail NEGATIVE is inconclusive and is re-decided on the FULL
    journal, so the guard can never fail OPEN into a double dispatch) lives at its ONE home,
    `journal._dispatch_events_tail_first`. Not injected -> the plain FULL reader, byte-identical to the
    pre-T-10397 behavior (the T-10396 `_iter_events_tail=None` precedent — every existing test keeps its
    exact semantics without being rewritten)."""
    if _dispatch_events_tail_first is None:
        return _dispatch_status_events(task_id=task)
    evs, _allev, _launch_ts = _dispatch_events_tail_first(task_id=task)   # scoped read (small footprint)
    return evs


def _redispatch_events(task, _dispatch_status_events, _dispatch_events_tail_first):
    """T-10771 — the events the JOURNAL-VERIFIED PRIOR STATE fold reads. Same tail-first shape and the
    same fail-closed tail-NEGATIVE→full-read semantics as `_inflight_events` above (one home for that
    argument: `journal._dispatch_events_tail_first`), but UNSCOPED.

    WHY UNSCOPED. The resolved-halt predicate's LAND arm matches `land_completed` by `data.branch`:
    that event carries NO top-level `task_id` and no `data.task`, so it is invisible in a TASK-SCOPED
    list and the brief would silently read a landed task's halt as still live — the two surfaces would
    then disagree about the same halt, which is precisely what one shared predicate exists to prevent.
    `with_unscoped=True` costs no extra parse (the reader filters AFTER parsing, so one read serves
    both views — see its docstring), and the unscoped stream is a superset of the scoped one, so the
    fold's task-keyed halves are unchanged (`_journal_redispatch_state` matches by task id itself).

    `_inflight_events` and every in-flight GUARD that uses it are deliberately left untouched — those
    guards need only the task's own chain, and widening their read would move their footprint for no
    reason (CHARTER §P1 F3)."""
    if _dispatch_events_tail_first is None:
        return _dispatch_status_events(task_id=None)
    _evs, allev, _launch_ts = _dispatch_events_tail_first(task_id=task, with_unscoped=True)
    return allev or []


def _current_card_holder(task, evs, all_evs, _live_task_worktrees, _read_worktree_stamp,
                         _pid_is_session):
    """T-11290 — resolve the launch record of the worker whose CURRENT card is `task`, for the case
    where `task` is NOT the card that worker was LAUNCHED with. Returns `(launch_event, worker_ref)`
    or `(None, None)`.

    WHY. `dispatch --stop` derived its target ONLY from a `bg_dispatch_launched` tied to the NAMED id,
    so it could address only the card a worker STARTED on. A warm worker legitimately takes further
    cards in sequence (the front-load carve-out — patterns/background-session-operation.md §Launch),
    and ONLY the first card of such a chain carries a launch row. So a worker that had moved to its
    chain's second card was invisible to `--stop` under the id it was actually working (measured
    2026-08-18) — there was no governed stop for it at all, only the "nothing launched" refusal, which
    is a TRUE statement about that id and a FALSE answer to the question asked.

    THE CARRIER ALREADY EXISTS (stateless, no new store — CHARTER §6). Every row a dispatched worker
    emits carries its assigned session ref in the ENVELOPE, and the launcher records that same ref as
    `data.expected` on its launch row; `journal._dispatch_identity` already matches the two. The launch
    stream is read UNSCOPED (that launch is tied to a DIFFERENT task id, so a task-scoped list cannot
    see it) — the same reason `_redispatch_events` reads unscoped.

    HISTORY IS NOT OWNERSHIP (audit-pre finding, absorbed). Having ROWS for a card never proves a
    worker is ON it: a warm worker walks a chain, so its journal trail names every card it has already
    LEFT. Resolution therefore proves CURRENCY, live substrate first, and refuses on anything less:
      (b) LIVE-CLAIM AUTHORITY — if the candidate worker holds a live `task/T-XXXX` worktree, that
          claim (not the journal) says which card it is on. Any card but the named one means it has
          MOVED ON → no resolution. (A live claim ON the named card resolves here and is then refused
          by the caller's pre-existing claim-less gate, which points at `worktree adopt`.)
      (c) CLAIM-LESS CURRENCY — a worker holding NO worktree is the rogue this verb exists for, and for
          it the journal's own currency test applies: its NEWEST task-tied row must name THE NAMED
          CARD. Historical rows for a card it has already left never resolve.
      (d) LIVENESS — the worker must be POSITIVELY RUNNING NOW (the launch row's pid still carrying
          that exact `--session-id` adjacency). A past worker/session is unresolvable by construction.

    FAIL-CLOSED ON EVERY ARM: an unreadable stamp, an unverifiable pid, a ref no launch row claims, or
    an absent trail all yield NO resolution, so the caller keeps its refusal and a wrong id can never
    become a silent success. And resolving a target is not permission to act — every gate downstream is
    unchanged, including the pid verification that refuses to signal an unmatched process."""
    launches = [e for e in all_evs if e.get("type") == "bg_dispatch_launched"]
    if not launches:
        return None, None
    live_refs = {}                      # worker ref -> the task id whose live worktree it stamps
    for tid, wt in (_live_task_worktrees() or {}).items():
        stamp = _read_worktree_stamp(wt)
        ref = stamp.get("session_ref") if isinstance(stamp, dict) else None
        if ref:
            live_refs[ref] = tid
    seen = set()
    for e in reversed(evs):
        ref = e.get("session_ref")
        if not ref or ref in seen:
            continue
        seen.add(ref)
        launch = next((lev for lev in reversed(launches)
                       if isinstance(lev.get("data"), dict)
                       and lev["data"].get("expected") == ref), None)
        if launch is None:              # not a launcher-assigned worker ref — never a target
            continue
        if ref in live_refs:            # (b) the live claim is the authority on its current card
            if live_refs[ref] != task:
                continue                # moved on — the named card is not what it is working
        else:                           # (c) claim-less: newest task-tied row is its current card
            newest_card = next((x.get("task_id") for x in reversed(all_evs)
                                if x.get("session_ref") == ref and x.get("task_id")), None)
            if newest_card != task:
                continue
        pid = (launch.get("data") or {}).get("pid")
        if pid is None or not _pid_is_session(pid, ref):   # (d) positively running, or nothing
            continue
        return launch, ref
    return None, None


# T-11548 — the bounded ceiling (seconds) the `--defer` arm waits for a SIGTERM'd claimed worker to
# stop carrying its `--session-id` adjacency before it will emit terminality. Bounded by construction:
# the wait never loops past this and its expiry is a REFUSAL, never a force (see the
# CONFIRMED-STOPPED PRECONDITION in `cmd_dispatch_stop`). Injectable in tests via `_reap_wait_secs`.
DEFER_REAP_WAIT_SECS = 5.0
DEFER_REAP_POLL_SECS = 0.1


def cmd_dispatch_stop(task, restore_paths, *, main_wt, _as_list, _die,
                      _dispatch_status_events, _classify_dispatch, _live_task_worktrees,
                      _append_event, _run_git_cap, _pid_is_session, _utc_now_iso,
                      DISPATCH_TERMINAL_TYPES, _dispatch_events_tail_first=None,
                      _read_worktree_stamp=None, defer=False, _park_claimed_worktree=None,
                      _reap_wait_secs=DEFER_REAP_WAIT_SECS, _sleep=time.sleep) -> None:
    """`dispatch --stop --task T-XXXX [--defer]` (T-10376; the `--defer` arm T-11548) — the GOVERNED
    controller stop of a dispatched worker, in TWO arms sharing ONE mechanism and ONE set of rails.

    THE TWO ARMS (the ONLY difference is gate (3), the claim gate):
      • BARE `--stop` (T-10376) — a CLAIM-LESS rogue/dead worker. A live `task/<task>` worktree REFUSES,
        pointing at `worktree adopt --confirm-dead` / `worktree recover-land`. UNCHANGED by T-11548.
      • `--stop --defer` (T-11548) — the CLAIMED, LIVE worker the controller wants OUT OF THE WAVE, to
        re-run later. Measured 2026-08-25 (deviation `no-governed-verb-to-defer-a-claimed-worker-out-of-
        a-wave`): T-11501 was dispatched and working at stage Plan, 0 commits ahead, when the owner
        asked for it to run in a quiet slot. The bare `--stop` refused it by the contract above, and the
        verbs that refusal names are FINISH paths — `worktree adopt --confirm-dead` and `worktree
        recover-land` both drive the work to COMPLETION, and neither expresses "take this one out of the
        wave and re-run it later". The only route left was killing the process by hand: ungoverned,
        journalling nothing, leaving the claim and worktree in a state no verb authored.

    AN ARM, NOT A SECOND VERB (CHARTER §P1 F1 + D-0033 extend-the-verb). `--stop` ALREADY owns the
    governed-stop mechanism AND its safety rails — pid verification against the assigned `--session-id`
    rather than a stale-pid blind kill, evidence capture BEFORE any restore, and a terminal
    `bg_dispatch_halted` that makes the task re-dispatchable without `--force`. A second verb here would
    be a parallel path through the same rails.

    WHAT HAPPENS TO A WORKER THAT HOLDS COMMITTED WORK — DELEGATED, never re-decided. This arm invents
    NO third disposal rule: it hands the worktree to `_park_worktree(confirm_dead=True, force=False)`,
    whose T-11330 work-in-flight guard IS the SPEC-0103 pause-shape fork. Bookkeeping-only (nothing
    beyond the re-derivable claim footprint) → torn down, task `ready` on main, cleanly re-dispatchable.
    WORK-CARRYING → `{parked: False, preserved: True}`: worktree + branch INTACT, nothing discarded, and
    the card re-enters via `task resume` (or the existing preserving-orphan re-dispatch). Any refusal
    from the park core is likewise PRESERVED — the uncertain answer never destroys. There is NO `--force`
    arm here: this verb can never discard a build. Discarding stays the separate, already-governed
    explicit operator act (`worktree park --force --reason`).

    CONFIRMED-STOPPED IS A PRECONDITION OF TERMINALITY (audit-pre pass-1 HIGH, absorbed). Under `--defer`
    the worker HOLDS A CLAIM, so emitting the terminal halt over a still-running one would both make the
    journal assert a terminality that is false AND unlock a re-dispatch onto a live build (a double
    claim). So after the SAME verified-pid SIGTERM this arm WAITS, bounded, for the pid to stop carrying
    its `--session-id` adjacency; if the wait expires with the worker still POSITIVELY alive the verb
    REFUSES — no halt emitted, no disposal attempted, worktree untouched. Everything downstream of that
    point runs only against a confirmed-stopped worker. Fail-closed direction: `_pid_is_session` answers
    False on any doubt (i.e. "not running"), so a broken discriminator can only let the flow REACH
    disposal — where the park core's INDEPENDENT `_assert_no_live_holder` re-verifies liveness and
    refuses before anything destructive, and where the preserve branch destroys nothing by construction.

    OUT OF SCOPE by construction (the CHARTER §6 fence the card names): no auto-defer, no capacity or
    queue-state machinery, no policy about WHEN to defer, no liveness-arming FSM, no new store and no new
    event type. This is an explicit, owner-cued controller act, and the verb stays STATELESS — every
    input is derived from the journal + git.

    (T-10376 original contract follows.) The GOVERNED controller stop of a CLAIM-LESS
    rogue/dead worker (auditor Option B, decisions/controller-kill-rogue-worker-gap-audit-adhoc.yaml).
    STATELESS: the target (pid / worker ref / dirt) is derived from the journal + git state — NO worker
    registry (CHARTER §6). It MECHANIZES the manual kill+restore+halt recovery that patterns/background-
    session-monitoring.md §Abnormal keeps as the emergency fallback. Sequence (fail-closed at each gate):

      1. resolve the target worker (its pid + assigned worker ref E) on TWO axes: the newest
         `bg_dispatch_launched` for the task; else — a warm worker's later chain card carries no launch
         row of its own — the launch record of the worker whose CURRENT card is this one
         (`_current_card_holder`, T-11290: live claim first, else the journal's newest-card test, and
         positively running either way). Neither → no worker holds it → refuse (nonzero, no mutation).
      2. ALREADY-RESOLVED gate (audit-pre F3): classify the dispatch; if the newest launch is already
         TERMINAL (done/halt/wont-do) or landed → refuse/no-op. IDEMPOTENT — a second `--stop` after the
         first emitted `bg_dispatch_halted` reads TERMINAL(halt) and refuses (no double-halt).
      3. CLAIM-LESS gate: a LIVE `task/<task>` worktree means the worker DID isolate → this is the
         `worktree adopt`/`recover-land` path, NOT this verb → refuse.
      4. STOP the proc SAFELY (audit-pre F2 — PID reuse): signal the captured pid ONLY when
         `/proc/<pid>/cmdline` still carries the exact `--session-id <worker_ref>` adjacency
         (`_pid_is_session`); otherwise do NOT signal (report already-dead/unverified). By captured pid,
         never `pkill -f` (§Abnormal).
      5. EVIDENCE-FIRST: capture the full main-checkout dirt (`git diff` + porcelain listing) to a
         recorded `.yitc/rogue-recovery/<task>-<ts>.diff` BEFORE any restore.
      6. RESTORE is FAIL-CLOSED (audit-pre F1): revert ONLY operator-named `--restore-path` files (each
         asserted tracked+dirty; `events.jsonl`/journal bookkeeping is REFUSED as a target). With NO
         `--restore-path` nothing is reverted — evidence is captured and the dirty set is REPORTED for
         the operator to resolve. Untracked files are never deleted (cross-session isolation).
      7. emit the terminal `bg_dispatch_halted` on MAIN's journal (the marker the in-flight guard now
         CONSUMES on the launched-sublist axis, T-10376). The task stays `ready`/redispatchable — a
         claim-less rogue never mutated the card, so status is untouched (stateless)."""
    import signal as _signal
    evs = _inflight_events(task, _dispatch_status_events, _dispatch_events_tail_first)
    launches = [e for e in evs if e.get("type") == "bg_dispatch_launched"]
    warm_ref = None
    if launches:
        newest = launches[-1]   # _dispatch_status_events is ts-ascending
    else:
        # T-11290 — the CURRENT-CARD axis. No launch row under THIS id does not mean no worker holds
        # it: a warm worker takes further cards of its front-loaded chain, and only the chain's FIRST
        # card carries a launch row. So resolve the worker whose CURRENT card this is before refusing
        # (`_current_card_holder` — live claim first, journal currency for the claim-less rogue, and
        # positively running either way). Fail-closed: unresolved still refuses.
        all_evs = _redispatch_events(task, _dispatch_status_events, _dispatch_events_tail_first)
        newest, warm_ref = _current_card_holder(
            task, evs, all_evs, _live_task_worktrees, _read_worktree_stamp, _pid_is_session)
        if newest is None:
            # Two DISTINCT refusals — an operator is never told something false about their fleet. A
            # card whose rows name a launcher-assigned worker WAS worked; what failed is the currency
            # or liveness test, and saying "nothing launched" there would be a wrong answer.
            worked_by = next((e.get("session_ref") for e in reversed(evs)
                              if e.get("session_ref")
                              and any(isinstance(l.get("data"), dict)
                                      and l["data"].get("expected") == e.get("session_ref")
                                      for l in all_evs if l.get("type") == "bg_dispatch_launched")), None)
            if worked_by:
                _die(f"dispatch --stop: {task} was worked by dispatched worker {worked_by}, but that "
                     f"worker does NOT hold {task} now — it has either moved on to a later card of its "
                     f"chain (its live claim / newest activity names another id) or is no longer "
                     f"running. Nothing to stop under this id: re-read `yitc-v2 journal query "
                     f"--dispatch-status --task {task}`, and stop the worker under the card it is "
                     f"ACTUALLY on.")
            _die(f"dispatch --stop: no worker holds {task} — there is no bg_dispatch_launched for it, "
                 f"and no dispatched worker's activity on it names a launcher-assigned worker ref "
                 f"(the target is derived from the journal; a never-dispatched, never-worked id has "
                 f"no rogue to recover).")
    # (2) already-resolved gate — never act on a settled dispatch.
    cls, detail, _lts, _sref = _classify_dispatch(evs, task)
    if cls == "TERMINAL":
        _die(f"dispatch --stop: {task} is already TERMINAL ({detail}) — the newest launch is settled "
             f"(done/halt/wont-do/landed); nothing to stop. `--stop` is idempotent and refuses a "
             f"resolved dispatch (re-dispatch via a plain `dispatch` if it is ready again).")
    if cls == "closed_pending_land":
        # T-10953 (X-0815) — the refusal is CORRECT either way (this verb recovers a CLAIM-LESS rogue,
        # and a closed_pending_land task holds a live claim), but its MESSAGE must not speak about a
        # process it did not read. `session-alive` (journal._classify_dispatch) means the land CHILD is
        # gone while the WORKER SESSION still lives — typically between land invocations in its own
        # synchronous-to-LAND retry loop — so "the worker CLOSED" is false and `worktree recover-land`
        # would correctly refuse it (its predicate is a CONFIRMED-DEAD worker), leaving the operator
        # with two refusals naming each other. Wording + branch only: nothing new is permitted here.
        if "land-alive" in (detail or ""):
            _die(f"dispatch --stop: {task} is closed-pending-land ({detail}) — its OWN `land` is IN "
                 f"FLIGHT right now. Nothing to stop and nothing to recover: LEAVE IT (firing a "
                 f"recovery against a live self-land RACES it, E-0035). Re-poll `dispatch "
                 f"--dispatch-status --task {task}` until it reaches a terminal.")
        if "session-alive" in (detail or ""):
            _die(f"dispatch --stop: {task} is closed-pending-land ({detail}) — its `land` child is gone "
                 f"but the WORKER SESSION IS STILL ALIVE and may be re-invoking its own land "
                 f"(synchronous-to-LAND retries are silent for minutes). Nothing to stop and nothing to "
                 f"recover yet: WAIT and re-poll `dispatch --dispatch-status --task {task}` (or read the "
                 f"task's journal tail) until it reaches a terminal or the session is confirmed dead.")
        _die(f"dispatch --stop: {task} is closed-pending-land ({detail}) — the worker CLOSED and only "
             f"integration is missing; recover via `worktree recover-land --task {task}`, not `--stop`.")
    # (3) THE CLAIM GATE — the ONE place the two arms diverge. Each branch composes its OWN complete
    # refusal; there is no shared generic tail, so the operator can never receive a specific diagnosis
    # above a contradicting one (`lessons/carving-an-exception-into-a-fail-closed-gate` §2).
    live = _live_task_worktrees()
    if task in live and not defer:
        # BARE `--stop` — the T-10376 refusal, VERBATIM and BYTE-FOR-BYTE UNCHANGED (T-11548 AC3).
        # An earlier draft appended a sentence advertising `--defer` here; audit-post pass 1 caught it
        # (HIGH) — AC3 pins EVERY existing refusal as it is today, and "behaviourally identical" is not
        # the promise AC3 makes. `--defer` discovery lives on the argparse surface instead (the STOP
        # group description + `--stop`'s own help both name it), so nothing was lost by restoring this.
        # Pinned byte-for-byte by tests/test_dispatch_stop_defer.py so it cannot drift again.
        _die(f"dispatch --stop: {task} holds a LIVE worktree claim ({live[task]}) — this verb recovers "
             f"a CLAIM-LESS rogue only. A claimed worker recovers via `worktree adopt --task {task} "
             f"--confirm-dead` (then finish/land) or `worktree recover-land` — never a blind stop.")
    if defer and task not in live:
        # The mirror refusal — POSITIVE and specific in BOTH directions, never a silent fall-through
        # into the other arm's behaviour. `--defer` is FOR the claimed case; a claim-less rogue is the
        # plain `--stop`, whose disposal semantics (nothing to tear down) are genuinely different.
        _die(f"dispatch --stop --defer: {task} holds NO live worktree claim — `--defer` is the "
             f"CLAIMED-worker arm (it stops a live claimed worker and disposes of its worktree). A "
             f"claim-less rogue/dead worker is the plain `dispatch --stop --task {task}` (no --defer).")
    data = newest.get("data") if isinstance(newest.get("data"), dict) else {}
    pid = data.get("pid")
    worker_ref = data.get("expected")
    # (4) stop the proc — verified pid only (audit-pre F2).
    if pid is not None and worker_ref and _pid_is_session(pid, worker_ref):
        try:
            os.kill(int(pid), _signal.SIGTERM)
            proc_result = f"signaled pid {pid} (SIGTERM; verified --session-id {worker_ref})"
        except (ProcessLookupError, PermissionError, ValueError, OSError) as e:
            proc_result = f"pid {pid} not signaled ({type(e).__name__}: {e}) — treated as already-dead"
    else:
        proc_result = (f"pid {pid} NOT signaled — no live process carries `--session-id {worker_ref}` "
                       f"(already-dead or pid reused; fail-closed, never a blind kill)")
    # (4b) CONFIRMED-STOPPED PRECONDITION — `--defer` ONLY (T-11548; audit-pre pass-1 HIGH, absorbed).
    # A deferred worker HOLDS A CLAIM, so terminality asserted over a still-running one would be a
    # journal LIE *and* would unlock a re-dispatch onto a live build (a double claim). The claim-less
    # arm needs no such wait — its worker holds nothing, so a halt over it costs nothing. Bounded, and
    # its expiry is a REFUSAL, never a force: nothing is emitted, nothing is disposed, nothing is
    # touched, and re-invoking once the worker is down is safe (the operator may also let it finish).
    reap_waited = 0.0
    if defer:
        _deadline = float(_reap_wait_secs or 0.0)
        while _pid_is_session(pid, worker_ref) and reap_waited < _deadline:
            _sleep(DEFER_REAP_POLL_SECS)
            reap_waited += DEFER_REAP_POLL_SECS
        if _pid_is_session(pid, worker_ref):
            _die(f"dispatch --stop --defer: REFUSED — {task}'s worker (pid {pid}, `--session-id "
                 f"{worker_ref}`) is STILL RUNNING {reap_waited:.1f}s after SIGTERM. A defer may not "
                 f"emit terminality over a live claimed worker: that would make the journal assert a "
                 f"halt that has not happened AND unlock a re-dispatch onto a live build (a double "
                 f"claim). NOTHING was emitted, NOTHING was disposed, and the worktree at "
                 f"{live.get(task)} is UNTOUCHED. Re-invoke once the worker is down (this verb is safe "
                 f"to repeat), or let it finish and use the ordinary post-land path.")
    # (5) evidence-first — capture ALL main dirt BEFORE any restore.
    porcelain = _run_git_cap(["status", "--porcelain"], main_wt)
    dirt_lines = [ln for ln in (porcelain.stdout or "").splitlines() if ln.strip()]
    evidence_path = None
    if dirt_lines:
        diff = _run_git_cap(["diff"], main_wt)
        ts = _utc_now_iso().replace(":", "").replace("-", "")
        ev_dir = main_wt / ".yitc" / "rogue-recovery"
        ev_dir.mkdir(parents=True, exist_ok=True)
        evidence_path = ev_dir / f"{task}-{ts}.diff"
        evidence_path.write_text(
            f"# rogue-recovery evidence for {task} — captured {_utc_now_iso()} BEFORE restore\n"
            f"# porcelain status ({len(dirt_lines)} entr{'y' if len(dirt_lines)==1 else 'ies'}):\n"
            + "".join(f"#   {ln}\n" for ln in dirt_lines)
            + "# --- git diff (tracked) ---\n" + (diff.stdout or ""),
            encoding="utf-8")
    # (6) restore — FAIL-CLOSED: only operator-named tracked+dirty paths; never the journal.
    restore_paths = [p.strip() for p in _as_list("--restore-path", restore_paths) if p.strip()]
    _BOOKKEEPING = {"events.jsonl"}
    dirty_tracked = {ln[3:].strip() for ln in dirt_lines if not ln.startswith("??")}
    restored, skipped_restore = [], []
    for p in restore_paths:
        if p in _BOOKKEEPING:
            _die(f"dispatch --stop: refusing to restore bookkeeping path {p!r} — the journal is "
                 f"append-only; reverting it would erase real history.")
        if p not in dirty_tracked:
            skipped_restore.append(f"{p} (not a tracked+dirty path — nothing to restore)")
            continue
        r = _run_git_cap(["restore", "--", p], main_wt)
        if r.returncode == 0:
            restored.append(p)
        else:
            skipped_restore.append(f"{p} (git restore failed: {(r.stderr or '').strip()})")
    # (6b) DISPOSAL — `--defer` ONLY (T-11548). DELEGATED to the park core, never re-decided here: its
    # T-11330 work-in-flight guard IS the SPEC-0103 pause-shape fork, and it is positive-evidence-for-
    # EMPTY (every uncertain answer preserves). No `--force` is passed and none is accepted — this verb
    # can never discard a build.
    disposal = preserved_why = None
    redispatchable = True
    if defer:
        if _park_claimed_worktree is None:
            _die("dispatch --stop --defer: no worktree-disposal binding was provided (internal wiring "
                 "error) — refusing rather than stopping a claimed worker with no governed disposal.")
        try:
            pdata = _park_claimed_worktree(task, "controller-defer") or {}
        except OrphanTeardownRefused as _e:
            # A park REFUSAL is the PRESERVING outcome, not an abort: the worktree is intact by
            # construction (the park core refuses BEFORE anything destructive), so the honest report is
            # "preserved, and here is why the teardown did not run".
            pdata = {"parked": False, "preserved": True, "carries_work_why": f"teardown refused: {_e}"}
        if pdata.get("parked"):
            disposal, redispatchable = "torn-down", True
        else:
            disposal, redispatchable = "preserved", False
            preserved_why = pdata.get("carries_work_why") or "worktree preserved"
    # (7) emit the terminal the in-flight guard consumes (launched-sublist axis, T-10376).
    _append_event("bg_dispatch_halted", task,
                  {"dispatch": task,
                   # SAME event TYPE for both arms (no new type — CHARTER §P1 F2), so the in-flight
                   # guard consumes it identically; the KIND is what names the cause (AC1).
                   "kind": "controller_defer" if defer else "controller_stop",
                   "reason": ("controller-defer: claimed worker taken out of the wave"
                              if defer else "controller-stop: rogue/dead claim-less worker"),
                   # T-11548 — the machine-readable disposal outcome, so a reader never has to infer
                   # which of the two things happened. Absent (None) on the claim-less arm, which
                   # disposes of no worktree.
                   "disposal": disposal, "redispatchable": redispatchable,
                   "preserved_why": preserved_why,
                   "reap_waited_secs": round(reap_waited, 1) if defer else None,
                   "pid": pid, "worker_ref": worker_ref, "prior_class": cls,
                   # T-11290 — WHICH axis resolved the target, and (for a warm chain) the card that
                   # worker was LAUNCHED with. Provenance only: the halt addresses the NAMED card.
                   "targeted_via": "current-card" if warm_ref else "launch-record",
                   "launched_as": newest.get("task_id"),
                   "evidence": str(evidence_path) if evidence_path else None,
                   "restored": restored, "dirty_untracked": [ln[3:].strip() for ln in dirt_lines if ln.startswith("??")]},
                  events_path=main_wt / "events.jsonl")
    if defer:
        print(f"dispatch --stop --defer: {task} — governed controller DEFER of a claimed worker "
              f"(taken out of the wave, to be re-run later)")
    else:
        print(f"dispatch --stop: {task} — governed controller stop of a claim-less rogue/dead worker")
    if warm_ref:
        print(f"  target:   resolved by CURRENT CARD (T-11290) — this worker was LAUNCHED with "
              f"{newest.get('task_id')} and moved on to {task} in its front-loaded chain; its launch "
              f"record carries the pid + assigned worker ref.")
    print(f"  proc:     {proc_result}")
    print(f"  evidence: {evidence_path if evidence_path else 'none (main checkout was clean)'}")
    if restored:
        print(f"  restored: {', '.join(restored)}")
    if skipped_restore:
        print(f"  NOT restored: {'; '.join(skipped_restore)}")
    untracked = [ln[3:].strip() for ln in dirt_lines if ln.startswith("??")]
    unrestored_tracked = sorted(dirty_tracked - set(restored))
    if untracked or unrestored_tracked:
        print(f"  ⚠ remaining main-checkout dirt (NOT touched — resolve manually, evidence captured): "
              f"{', '.join(untracked + unrestored_tracked)}")
    # THE CLOSING LINES — each disposal outcome composes its OWN COMPLETE statement, and exactly one
    # reaches the operator (`lessons/carving-an-exception-into-a-fail-closed-gate` §2). A preserved
    # defer must never be told it is re-dispatchable, and a torn-down one must never be told its
    # worktree survives.
    if disposal == "preserved":
        print(f"  worktree: PRESERVED — {preserved_why}. NOTHING was discarded: the worktree at "
              f"{live.get(task)} and its branch task/{task} are INTACT.")
        print(f"  terminal: bg_dispatch_halted(kind=controller_defer, disposal=preserved) emitted → "
              f"{task} is OUT OF THE WAVE but NOT re-dispatchable as a fresh claim (its worktree still "
              f"holds un-landed work). Re-enter the card via `bin/yitc-v2 task resume {task}` in that "
              f"worktree, or re-dispatch onto the preserved worktree (the adopt-first path). To discard "
              f"it instead, that is the explicit `bin/yitc-v2 worktree park --task {task} --force "
              f"--reason <why>` — this verb never discards a build.")
    elif disposal == "torn-down":
        print(f"  worktree: TORN DOWN — it held nothing beyond the re-derivable claim footprint; "
              f"worktree removed + branch task/{task} deleted, no orphan (worker_parked emitted).")
        print(f"  terminal: bg_dispatch_halted(kind=controller_defer, disposal=torn-down) emitted → "
              f"{task} is `ready` on main and cleanly re-dispatchable (a plain `dispatch` NO --force "
              f"relaunches; the in-flight guard consumes the halt).")
    else:
        print(f"  terminal: bg_dispatch_halted emitted → {task} stays ready/redispatchable "
              f"(a plain `dispatch` NO --force relaunches; the in-flight guard consumes the halt).")



# ── T-12637 — ONE arming implementation, TWO entry points ────────────────────────────────────────
# `dispatch --watch` (the hand-armed route) and the LAUNCH tail (the self-armed route, below) both
# arm through THIS function, so the escape, the reachability classification, the journal rows, the
# poll loop and the `WATCH:` token exit are ONE body — never two copies drifting apart (CHARTER §P1
# F1). Extracted VERBATIM from the former `--watch` branch of `cmd_dispatch`; nothing about what
# arming MEANS moved (same poll, same predicate, same debounce, same token — the card's OUT OF SCOPE).
#
# WHY THE LAUNCH SELF-ARMS (X-1443, X-1440, and the five-worker no-watcher dispatch of 2026-09-16).
# "Delivering" means the watcher's EXIT re-invokes the Controller, and only the harness's own
# background primitive observes an exit that way — a provider-neutral CLI can NEVER hand the harness a
# process to watch (CHARTER §P4b, SPEC-0133 rule 1). What it CAN do is BE the process the harness is
# already watching: after the launch the SAME invocation continues into the watch, so there is no
# second call for the Controller to type in the cheaper orphaning shape, because there is no second
# call. The obligation is removed as a STEP, not restated as a RULE.
#
# THE DEDUP SEAM (AC2). Before the process-group escape, the arming reads MAIN's journal — the ONE
# governed dispatch reader (`_dispatch_status_events`, narrowed by `include_types` + `since` to the
# escape rows of the wave window; SPEC-0133 rule 5 admits no second journal path) — for
# `watch_process_group_escaped` rows whose recorded pid is STILL ALIVE and whose `watched_tasks`
# INTERSECT the ids being armed. Any such row makes THIS arming a DUPLICATE and it is refused: the
# live pid is printed, rc 0, no escape, no append, no loop. A watcher whose pid is DEAD is no obstacle,
# so the ordinary re-arm after a watch has ENDED (woke / timed out / swept) is unchanged. The row is
# the existing one (SPEC-0161 catalog); no new event type, no lease file, no registry.
_WATCH_DEDUP_WINDOW_SEC = 24 * 3600   # the `--dispatch-status` WAVE window — the existing analog


def _default_proc_start_token(pid: "int | None") -> "str | None":
    """T-12637 — the PROCESS IDENTITY token beyond the pid: the kernel's `starttime` for `pid`
    (field 22 of `/proc/<pid>/stat`, clock ticks since boot). A pid is REUSED within hours on a busy
    host; a (pid, starttime) pair is not — so a `watch_process_group_escaped` row carries the token of
    the process that wrote it, and the dedup seam treats the row as a LIVE watcher only when the
    process now holding that pid carries the SAME token. None when unreadable (no /proc, vanished,
    unparsable) — an unverifiable identity is NEVER read as a match."""
    try:
        raw = Path(f"/proc/{int(pid)}/stat").read_text()
        # the comm field is parenthesised and may hold spaces — split AFTER its closing paren.
        rest = raw[raw.rindex(")") + 2:].split()
        return rest[19]                                  # field 22 overall == index 19 after comm
    except Exception:          # noqa: BLE001 — unreadable ⇒ unverifiable ⇒ no token
        return None


def _live_watchers_over(tasks, *, main_wt, _dispatch_status_events, _pid_alive,
                        _proc_start_token=_default_proc_start_token, _utc_now=None,
                        session_ref=None) -> "tuple[list, str | None]":
    """The `watch_process_group_escaped` rows on MAIN whose recorded process is STILL THAT process and
    whose watched set INTERSECTS `tasks` — i.e. the watchers a fresh arming over `tasks` would
    DUPLICATE (T-12637 AC2). Returns `(live_rows, unanswered)`: `unanswered` is None when the journal
    was read, else the reader's failure (repr) — the CALLER decides what an unanswered check means
    and says so aloud; this function never converts «could not read» into a silent «no live watcher»
    (audit-post fp1:c04fb194d466ead8).

    LIVENESS IS IDENTITY, NOT A BARE PID (audit-post fp1:5fc9fe39f1aa65e3): a row is live iff its pid
    answers `_pid_alive` AND the process now holding that pid carries the row's recorded `pid_start`
    token (`_proc_start_token`). A row with NO token (written before this card) or a token that does
    not match (the pid was REUSED) is NOT a live watcher, so the promised re-arm after a watcher has
    ended is never refused on a stranger's pid.

    SELECTING BY ARMING SESSION (T-13539). Given a non-empty `session_ref`, the rows selected are those
    whose ENVELOPE `session_ref` equals it — the watchers THAT SESSION armed, whatever they watch — in
    place of the task intersection (`tasks` may then be empty). This is the hand-off take's question
    («which watchers did the author leave running?»), answered by the same reader, window and liveness
    test as the dedup seam, so there is one definition of a live watcher. Without it the selection is
    the task intersection, unchanged."""
    wanted = {str(t) for t in (tasks or [])}
    by_session = bool(session_ref)
    if (not wanted and not by_session) or _dispatch_status_events is None:
        return [], None
    # WALL-clock, deliberately separate from the loop's injected MONOTONIC `_watch_now`: the window is
    # judged against journal `ts` strings, and a monotonic float cannot be.
    now = _utc_now() if _utc_now is not None else datetime.datetime.now(datetime.timezone.utc)
    since = (now - datetime.timedelta(seconds=_WATCH_DEDUP_WINDOW_SEC)).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        rows = _dispatch_status_events(task_id=None, since=since,
                                       include_types={_WATCH_ESCAPE_EVENT},
                                       journals=[Path(main_wt) / "events.jsonl"])
    except Exception as exc:   # noqa: BLE001 — an UNANSWERED question, reported as such, never hidden
        return [], repr(exc)
    live = []
    for row in rows or []:
        if not isinstance(row, dict) or row.get("type") != _WATCH_ESCAPE_EVENT:
            continue
        d = row.get("data") or {}
        watched = {str(t) for t in (d.get("watched_tasks") or [])}
        pid, token = d.get("pid"), d.get("pid_start")
        if by_session:
            if str(row.get("session_ref") or "") != str(session_ref):
                continue
        elif not (watched & wanted):
            continue
        if pid is None or not token:
            continue
        try:
            if _pid_alive(pid) and _proc_start_token(pid) == str(token):
                live.append(row)
        except Exception:      # noqa: BLE001 — unanswerable identity ⇒ not a live watcher
            continue
    return live, None


def _watch_holder_text(row: dict) -> str:
    """T-13539 — WHO holds a live watcher and UNTIL WHEN, from its `watch_process_group_escaped` row:
    the arming session (the row's envelope `session_ref`), the arm time (its `ts`) and the latest
    expected end (`ts` + the `timeout_sec` the arming recorded). One home, read by the duplicate
    refusal and by `session handoff take` (CHARTER §P1 F1). PURE; never raises.

    The end is an UPPER bound — a watcher exits earlier on a wake — so it is worded «at the latest».
    A row with no readable arm time or no recorded timeout (every row written before this card) says
    the end is unknown: a guessed time would be read as a promise."""
    d = row.get("data") or {}
    ref = row.get("session_ref") or "unknown"
    armed = row.get("ts") or "unknown"
    end = None
    secs = d.get("timeout_sec")
    if isinstance(secs, (int, float)) and not isinstance(secs, bool) and secs >= 0:
        try:
            t0 = datetime.datetime.strptime(str(row.get("ts")), "%Y-%m-%dT%H:%M:%SZ")
            end = (t0 + datetime.timedelta(seconds=secs)).strftime("%Y-%m-%dT%H:%M:%SZ")
        except Exception:      # noqa: BLE001 — an unreadable arm time ⇒ no computed end
            end = None
    tail = (f"ends by {end} at the latest" if end
            else "expected end unknown (the row records no arm time or no watch timeout)")
    return f"armed by session {ref} at {armed}, {tail}"


# T-13396 (SPEC-0190 rules 4 + 10) — the WATCH's one request scope. Measured on the T-13366 sandbox:
# unscoped, every poll re-read the live segment for itself (fleet verdict, per-task status, premature
# finder — 6 polls, 13 folds; the kernel's 1922 s watch folded 1201 times, events.jsonl#ts=2026-10-02T13:21:56Z).
# One scan_scope for the watch loop's lifetime, with the T-13332 catch-up, walks once and then feeds each
# poll ONLY the bytes appended to the live segment since the last one. Never stale: an unprovable resume
# point (rotation, shrink, rewrite) turns the scope STALE and every read reads for itself; a request older
# than the window is a recorded fallback answered by its own read. The window is the dispatch wave window
# the readers ask (`_WATCH_DEDUP_WINDOW_SEC` — a mismatch costs reads, never correctness) plus the tail
# margin plus the watch's own lifetime, since each poll's `since` slides forward from the walk.
#
# T-13462 — TWO THINGS THAT SCOPE DID NOT HOLD, both measured on the kernel 2026-10-04 (every 2026-10-03
# watch receipt still folded 6x-90x per artifact, growing with the watch's lifetime):
#   (i)  A STALE SCOPE STAYED STALE. `land` replaces main's live segment several times an hour; the
#        first one inside a watch left every later poll reading main for itself. The scope is now
#        RENEWED — `_arm_watch` asks `renew()` before each reader, and a scope that can no longer serve
#        is closed and re-opened: main is walked once more per rewrite, not once per reader per poll.
#   (ii) THE OTHER LEGS WERE NEVER IN IT. The fleet verdict and the per-task status union every live
#        worktree journal and every registry consumer journal, each read per call (~42 folds per poll
#        with main's scope fresh). `journal.WatchReads` carries a catch-up cursor per such leg.
# Both live in `journal.WatchReads`; this function only declares the main scope's window.
def _watch_read_scope(main_wt, timeout_sec: int):
    """The watch-loop ReadScope over `main_wt`'s journal and the watch's other legs (see the block
    above). Not a cache: it is released when the loop ends and serves nothing a later invocation reads."""
    window = _WATCH_DEDUP_WINDOW_SEC + journal._TAIL_WINDOW_MARGIN_SEC + max(0, int(timeout_sec))

    def _declare():
        since = (datetime.datetime.now(datetime.timezone.utc)
                 - datetime.timedelta(seconds=window)).strftime("%Y-%m-%d")
        return {"window_sec": window, "since": since, "catch_up": True}
    return journal.WatchReads(Path(main_wt) / "events.jsonl", _declare)


def _arm_watch(tasks: "list[str]", args: argparse.Namespace, *, main_wt, _append_event,
               _dispatch_status_events=None, _pid_alive=_default_pid_alive,
               _proc_start_token=_default_proc_start_token,
               _watch_fleet_rows=None, _watch_status_row=None, _watch_premature_findings=None,
               _watch_sleep=None, _watch_now=None, _utc_now=None) -> int:
    """ARM the blessed watcher over `tasks` IN THIS PROCESS and return its `WATCH:` exit code
    (T-12637). The one body behind both `dispatch --watch` and the self-arming launch tail — see the
    block comment above. Refuses a DUPLICATE (a live watcher already over any of `tasks`) with rc 0
    and no side effect at all."""
    # timeout: an EXPLICIT 0 is legitimate ("probe once, exit TIMEOUT now") — only an ABSENT value
    # takes the default (see the loop call below for the history of that rule).
    _timeout_raw = getattr(args, "watch_timeout", None)
    _timeout = journal.WATCH_MAX_RUNTIME_SECS if _timeout_raw is None else max(0, int(_timeout_raw))
    # T-13396 — the WHOLE arming (the live-watcher dedup read and the loop) runs inside ONE
    # watch-lifetime ReadScope (block above `_watch_read_scope`).
    with _watch_read_scope(main_wt, _timeout) as _reads:
        # T-13462 — each reader the loop runs first lets the scope re-establish itself after a rewrite
        # of main's live segment. `_reads` is None under a no-op context (a test double): no renewal.
        _renew = getattr(_reads, "renew", None)

        def _renewing(fn):
            if fn is None or _renew is None:
                return fn

            def _call(*a, **k):
                _renew()
                return fn(*a, **k)
            return _call
        live, unanswered = _live_watchers_over(
            tasks, main_wt=main_wt, _dispatch_status_events=_dispatch_status_events,
            _pid_alive=_pid_alive, _proc_start_token=_proc_start_token, _utc_now=_utc_now)
        if unanswered is not None:
            # FAIL TOWARD ARMING, ALOUD (audit-post fp1:c04fb194d466ead8). Refusing here would lose the
            # watch — workers running with nobody watching, the exact defect this card removes — over a
            # journal read that told us nothing. A possible duplicate costs one extra wake; an absent
            # watcher costs a silent stall. So the arming PROCEEDS and the caller is TOLD, in its own
            # output, that the one-per-task guarantee could not be checked for these ids.
            print(f"dispatch: live-watcher check could NOT be read ({unanswered}) — arming over "
                  f"{', '.join(str(t) for t in tasks)} anyway; a DUPLICATE watcher over these ids is "
                  f"possible until this one ends (T-12637 AC2 seam unanswered).", file=sys.stderr, flush=True)
        if live:
            for row in live:
                d = row.get("data") or {}
                overlap = sorted({str(t) for t in (d.get("watched_tasks") or [])} & {str(t) for t in tasks})
                # T-13539 — name the HOLDER, not the pid alone: after a hand-off the pid says nothing
                # about whose watcher this is or when it ends.
                print(f"dispatch: watcher already live for {', '.join(overlap)} (pid={d.get('pid')}) "
                      f"{_watch_holder_text(row)} — "
                      f"not arming a second (T-12637 AC2; a watcher that has ENDED is no obstacle, "
                      f"re-arm after its WATCH: token).", flush=True)
            return 0
        # T-12641 / X-1440 — CLASSIFY THE ARMING FIRST. Before the T-11578 escape and before ANY
        # journal I/O, because the ONE channel that reaches the Controller is the caller's own
        # still-open output window and that window closes when the foreground call returns (measured:
        # a write placed after the journal I/O produced nothing). Three channels, ordered by
        # immediacy, NONE claiming a guarantee; all three fire ONLY on a PROVEN `unreachable`, so the
        # arming that works is byte-for-byte unchanged (AC3). NO REFUSAL: refusing would destroy the
        # only observability an orphaned arming still has, and would newly break the `> log`-and-poll
        # operator on a verb whose contract never forbade it.
        _arm_reach, _arm_detail, _arm_why = _watch_arming_reachability()
        _arm_banner_delivered = False
        if _arm_reach == "unreachable":
            _banner = _watch_unreachable_banner(_arm_detail, _arm_why)
            _arm_banner_delivered = _write_to_caller_stdout(_banner)   # (a) PRIMARY — the caller
            print(_banner, file=sys.stderr, flush=True)                # (b) the `> log`/interactive form
        # T-11578 — LEAVE THE LAUNCHING SHELL'S PROCESS GROUP, here, before the loop blocks. The call
        # site is `cmd_dispatch`'s watch branch rather than `cmd_dispatch_watch` itself for three
        # reasons, all load-bearing: (1) `cmd_dispatch_watch` is HERMETICALLY testable by construction
        # — every side effect injected, no subprocess, no clock — and an un-injected `os.setsid` inside
        # it would destroy that property; (2) it is pinned in SPEC-0133's implements_signature, so
        # leaving it byte-identical confines the re-bless to this function; (3) the escape must happen
        # ONCE at entry, which is what this branch is. It covers `--watch-fleet` too, and that is
        # correct rather than incidental: that flag is REFUSED without `--watch` (just above) and only
        # widens which verdicts may WAKE the same blocking loop — what verdicts wake you has no bearing
        # on who may kill you.
        #
        # The lazy import keeps this module the LOW leaf its header declares (journal/task only);
        # `worktree_lifecycle.py` already lazy-imports THIS module in the reverse direction.
        from lib import worktree as _wt_escape                       # noqa: PLC0415 — lazy by design
        _escape = _wt_escape._escape_observer_process_group(env_var=_WATCH_KEEP_PROCESS_GROUP_ENV)
        # FAIL-SOFT ON THE RECORD-KEEPING TOO, exactly as `cmd_land` does. The escape has already taken
        # effect by this line; the journal row is OBSERVABILITY and may never refuse a watch. An
        # unrecorded escape is ANNOUNCED on stderr rather than passing silently — a silent escape is
        # indistinguishable from none, which is the half AC2 exists to close.
        try:
            _append_event(_WATCH_ESCAPE_EVENT, None,
                          {"mechanism": _escape, "pid": os.getpid(),
                           # T-12637 — the process-identity token the dedup seam verifies beyond the pid.
                           "pid_start": _proc_start_token(os.getpid()),
                           # T-13539 — the watch window, so a reader of this row can say when this
                           # watcher ends at the latest (row `ts` + this) instead of only that it lives.
                           "timeout_sec": _timeout,
                           "watched_tasks": tasks,
                           "watch_fleet": bool(getattr(args, "watch_fleet", False)),
                           "reason": "this watcher's lifetime is now DECOUPLED from the shell that "
                                     "launched it, so a wrapper that is swept, times out or was never "
                                     "armed costs a re-arm and nothing else (T-11578, X-1103); a "
                                     "group-directed kill aimed at the wrapper no longer reaches the "
                                     "watcher."},
                          events_path=main_wt / "events.jsonl")
        except Exception as _exc:                    # noqa: BLE001 — observability, never a gate
            # T-12637 (audit-post fp1:3d57570a34d789c9): this row is ALSO the dedup carrier, so an
            # unwritten one means a later arming over these ids cannot SEE this watcher. Still fail-soft —
            # refusing the watch over a journal write would trade a possible duplicate for a certain
            # absence — but the consequence is NAMED where the caller reads, never silent.
            print(f"watch: process-group escape took effect (mechanism={_escape}) but its "
                  f"`{_WATCH_ESCAPE_EVENT}` record could NOT be written ({_exc!r}). The watch "
                  f"PROCEEDS — this is observability, not a gate — but this watcher's decoupling is "
                  f"unattributable in the journal AND a later arming over "
                  f"{', '.join(str(t) for t in tasks)} cannot see this one, so a DUPLICATE watcher is "
                  f"possible until it ends (T-12637 AC2).", file=sys.stderr, flush=True)
        # (c) THE DURABLE BACKSTOP, for when the arm-time race is lost. Fail-soft in the identical
        # shape as the escape row above: observability, never a gate.
        try:
            _append_event(_WATCH_ARMED_EVENT, None,
                          {"reachability": _arm_reach, "detail": _arm_detail, "why": _arm_why,
                           "caller_channel_delivered": _arm_banner_delivered,
                           "pid": os.getpid(), "ppid": os.getppid(), "watched_tasks": tasks,
                           "watch_fleet": bool(getattr(args, "watch_fleet", False)),
                           "reason": "records HOW this watcher was armed, so a fleet read can tell an "
                                     "ORPHANED watcher from one whose exit can re-invoke its caller "
                                     "(T-12641, X-1440). Only the NEGATIVE is proven; `unproven` is "
                                     "never a delivery attestation."},
                          events_path=main_wt / "events.jsonl")
        except Exception as _exc:                    # noqa: BLE001 — observability, never a gate
            print(f"watch: arming reachability={_arm_reach} ({_arm_detail}) could NOT be recorded "
                  f"({_exc!r}). The watch PROCEEDS — this is observability, not a gate — but this "
                  f"arming's mode is unattributable in the journal.", file=sys.stderr, flush=True)
        # timeout: an EXPLICIT 0 is legitimate ("probe once, exit TIMEOUT now") — only an ABSENT value
        # takes the default. The prior `0 or 3600` coercion silently turned 0 into an hour; under a
        # frozen test clock that window never elapsed and the loop spun unbounded (the 2026-07-10
        # double session-OOM, fingerprint dispatch-watch-test-unbounded-spin-oom).
        rc = cmd_dispatch_watch(
            tasks,
            interval=int(getattr(args, "watch_interval", journal.WATCH_POLL_INTERVAL_SECS)
                         or journal.WATCH_POLL_INTERVAL_SECS),
            timeout=_timeout,
            confirm=int(getattr(args, "watch_confirm_ticks", 2) or 2),
            watch_fleet=bool(getattr(args, "watch_fleet", False)),   # T-10402 — explicit fleet opt-in
            any_terminal=bool(getattr(args, "watch_any_terminal", False)),   # T-11829 — per-worker exit
            arming_reachability=_arm_reach,          # T-12641 — carried into the rule-6 receipt
            _fleet_rows=_renewing(_watch_fleet_rows), _status_row=_renewing(_watch_status_row),
            # T-11926 — the premature-exit finder (injected like every other watch dep, so the loop
            # stays hermetic). None disables the recording entirely: the acceptance differential.
            _premature_findings=_renewing(_watch_premature_findings),
            _sleep=_watch_sleep, _now=_watch_now,
            _emit=lambda t, tid, d: _append_event(t, tid, d, events_path=main_wt / "events.jsonl"))
        return rc


def cmd_dispatch(args: argparse.Namespace, *, _as_list, _die, _main_worktree, _live_task_worktrees,
                 _append_event, _read_worktree_stamp, _session_last_event_ts, _find_task_yaml,
                 _read_yaml,
                 _resolve_effort_routing, _dispatch_status_events, _classify_dispatch,
                 # T-12607 (SPEC-0072 rule 7) — the tier's OPTIONAL reserve pair + the launch-answer
                 # probe collaborators. ALL default to None/the module defaults: a caller that injects
                 # nothing launches ONCE on the primary, exactly as before this card.
                 _resolve_effort_reserve=None,
                 # T-12986 (SPEC-0072 rule 8) — the provider-binding binary resolver. Used ONLY for an
                 # adapter that DECLARES `version_argv`; None or an undeclared adapter = unchanged call.
                 _resolve_worker_binary=None,
                 _launch_pid_alive=_default_pid_alive,
                 _read_launch_log=_default_read_launch_log,
                 _launch_probe_sleep=None, _launch_probe_monotonic=None,
                 _launch_probe_seconds_override=None, _launch_wait_seconds_override=None,
                 _redispatch_dead_orphan, _dispatch_readiness_report,
                 REPO_ROOT, SESSION_IDENTITY_REGISTRY,
                 EFFORT_TIERS, EFFORT_TIER_DEFAULT, DISPATCH_PROVIDERS,
                 SEED_READ_NODE_ID, HELP_INVENTORY_NODE_ID, PROVIDER_CARRIERS=(),
                 _watch_fleet_rows=None, _watch_status_row=None, _watch_premature_findings=None,
                 _watch_sleep=None, _watch_now=None,
                 DISPATCH_TERMINAL_TYPES=("task_closed", "bg_dispatch_halted", "task_wont_do"),
                 _run_git_cap=None, _pid_is_session=None, _utc_now_iso=None,
                 _dispatch_events_tail_first=None, _main_task_strand_state=None,
                 _print_spike_mode_hint=lambda: None, _migration_window_open=None,
                 ENGINE_ROOT=None, _is_consumer_build=None,
                 _session_proc_alive=_default_session_proc_alive,
                 _live_path_holders=_default_live_path_holders,
                 # T-12683 (X-1479) — the two reads that turn a cwd holder of a TERMINALLY-OVER
                 # session into an ORPHAN rather than a live holder inside `_orphan_holder_liveness`
                 # (the T-12375 park/adopt reap's own verdict substrate). None ⇒ the module defaults,
                 # bound to main's journal at the call; a test injects them to pin the differential.
                 _session_terminally_over=None, _proc_scan_is_takeable=None,
                 # T-13366 — the launch phase's request scope, owned by the host wiring site
                 # (`cli._dispatch_launch_reads`): `_refresh_launch_reads` drops its union snapshot
                 # after each spawn, `_release_launch_reads` unwinds it before the self-armed watch.
                 # None => no-op (every direct caller and test is unchanged).
                 _refresh_launch_reads=None, _release_launch_reads=None,
                 # T-12645 — the reaper for a worker that was spawned but could NOT be recorded
                 # (`_record_spawn_or_reap`). Injected so a probe can assert the reap happened with
                 # the spawned pid instead of signalling a real process.
                 _reap_worker=_default_reap_worker,
                 # T-12303 — the composed preamble's VENUE line. Injected (the host owns the `venue`
                 # import) so this module stays the low leaf its header declares. None ⇒ no line.
                 _venue_brief_line=None,
                 # T-12403 — the SPEC-0070 §5 claim-block predicate, threaded on to the routing
                 # preflight. Defaulted HERE because `--watch` / `--stop` exit long before routing and
                 # their callers legitimately inject no launch-path deps; it is REQUIRED on
                 # `_resolve_dispatch_routing`, which is where the gate actually runs — so a caller
                 # that DOES reach routing without it raises LOUDLY at the call rather than silently
                 # skipping the gate (a `None` default on the helper would fail OPEN, which is exactly
                 # the side-door this card closes). The AC3 tripwire pins that asymmetry.
                 _task_decomposed_from_pre_executing_plan=None,
                 # T-12637 — the ONE arming implementation behind `--watch` AND the self-arming launch
                 # tail. Injected so a probe can record the arming instead of blocking in the loop;
                 # None ⇒ this module's `_arm_watch`.
                 _arm_watch=None) -> None:
    """`dispatch` — the W4 THIN launcher (T-0558, list-extended T-0580). See the §Dispatch-launcher
    header block + the governing home patterns/background-session-operation.md §Dispatch. Launches
    the owner-given LIST of tasks SEQUENTIALLY in ONE invocation — each worker a fresh distinct
    session id + the full M2 scrub-then-set, each its own `bg_dispatch_launched` append to MAIN's
    journal. The loop is the owner's EXPLICIT list, NOT selection/ordering/retry/wait/ownership FSM
    (non-goal #7): the controller hands the ids + briefs; the launcher only carries them.

    Fail-closed preflight: ALL task ids are validated (+ duplicates rejected) and ALL briefs resolved
    BEFORE any worker spawns, so a bad invocation launches NOTHING (no partial launch). The launches
    then run in a single SYNCHRONOUS loop — no threads, no concurrency — so each `bg_dispatch_launched`
    append fully completes before the next iteration begins; the appends are SERIALIZED by construction
    (and `_append_event` additionally flocks the journal, T-0464), closing the concurrent-append-loss
    class (`startup-event-emit-silent-loss-concurrent-main-checkout`) for the multi-launch case."""
    tasks = [t.strip() for t in _as_list("--task", getattr(args, "task", None))]
    if not tasks:
        _die("dispatch: at least one --task required (T-NNNN; repeatable)")
    for t in tasks:
        if not re.fullmatch(r"T-\d{4,}", t):
            _die(f"dispatch: invalid --task id {t!r} (expected T-NNNN)")
    dupes = sorted({t for t in tasks if tasks.count(t) > 1})
    if dupes:
        _die(f"dispatch: duplicate --task id(s) {dupes} — each task dispatches at most one worker")
    # T-10376 — the STOP branch (governed controller stop of a claim-less rogue/dead worker). Like
    # --watch it LAUNCHES NOTHING and never consumes stdin, so it branches ABOVE the brief preflight;
    # it takes exactly ONE --task (a recovery targets one dispatch). Refuse the launch-only brief flags
    # explicitly rather than silently ignoring them.
    # T-11548 — `--defer` is STOP-ONLY: it selects the CLAIMED-worker ARM of the stop, so it is
    # meaningless without one. Refuse it explicitly rather than silently ignoring it (symmetric with the
    # `--watch-fleet` and `--restore-path` guards).
    if getattr(args, "defer", False) and not getattr(args, "stop", False):
        _die("dispatch: --defer is a stop-only flag — it selects the CLAIMED-worker ARM of `--stop` "
             "(stop a live claimed worker, take it out of the wave, dispose of its worktree per the "
             "SPEC-0103 pause-shape fork). It does nothing on a launch or a watch. Add --stop, or drop "
             "--defer.")
    if getattr(args, "stop", False):
        if getattr(args, "brief", None) or getattr(args, "brief_file", None):
            _die("dispatch --stop: --brief/-f are launch-only flags — `--stop` LAUNCHES NOTHING, it "
                 "stops a claim-less rogue/dead worker + preserves evidence + emits the terminal "
                 "bg_dispatch_halted. Drop the brief.")
        if len(tasks) != 1:
            _die("dispatch --stop: exactly one --task required (a recovery targets ONE dispatch)")
        main_wt = _main_worktree(REPO_ROOT) or REPO_ROOT
        return cmd_dispatch_stop(
            tasks[0], getattr(args, "restore_path", None) or [],
            main_wt=main_wt, _as_list=_as_list, _die=_die,
            _dispatch_status_events=_dispatch_status_events, _classify_dispatch=_classify_dispatch,
            _live_task_worktrees=_live_task_worktrees, _append_event=_append_event,
            _run_git_cap=_run_git_cap, _pid_is_session=_pid_is_session, _utc_now_iso=_utc_now_iso,
            DISPATCH_TERMINAL_TYPES=DISPATCH_TERMINAL_TYPES,
            _dispatch_events_tail_first=_dispatch_events_tail_first,   # T-10397 (tail-first guard read)
            _read_worktree_stamp=_read_worktree_stamp,                 # T-11290 (live-claim authority)
            defer=bool(getattr(args, "defer", False)),                  # T-11548 (the CLAIMED-worker arm)
            _park_claimed_worktree=_redispatch_dead_orphan)             # T-11548 (the ONE park binding)
    # T-10347 — the WATCH branch. It sits HERE, ABOVE the brief preflight, for two reasons: watch mode
    # launches nothing (so a brief is meaningless), and `_resolve_dispatch_briefs` is the ONE stdin
    # consumer (its single-task stdin fallback) — branching first makes "watch never consumes stdin" a
    # structural property rather than a promise (audit-pre finding, absorbed mode-(b)). Refuse the
    # launch-only brief flags explicitly instead of silently ignoring them.
    # T-10402 — `--watch-fleet` widens the WAKE scope of a watch; it is meaningless without one, so
    # refuse it explicitly rather than silently ignoring it (symmetric with the --brief guard below).
    if getattr(args, "watch_fleet", False) and not getattr(args, "watch", False):
        _die("dispatch: --watch-fleet is a watch-only flag — it widens `--watch`'s WAKE scope to the "
             "whole fleet. It does nothing on a launch. Add --watch, or drop --watch-fleet.")
    # T-11829 — `--watch-any-terminal` changes a watch's EXIT condition; like `--watch-fleet` it is
    # meaningless without one, so refuse it explicitly rather than silently ignoring it.
    if getattr(args, "watch_any_terminal", False) and not getattr(args, "watch", False):
        _die("dispatch: --watch-any-terminal is a watch-only flag — it makes `--watch` exit as soon as "
             "ANY ONE watched task reaches a positive terminal class, naming that task. It does "
             "nothing on a launch. Add --watch, or drop --watch-any-terminal.")
    if getattr(args, "watch", False):
        if getattr(args, "brief", None) or getattr(args, "brief_file", None):
            _die("dispatch --watch: --brief/-f are launch-only flags — `--watch` LAUNCHES NOTHING, it "
                 "polls the §6-safe readers over the given --task ids and exits on a WATCH: token. "
                 "Drop the brief (stdin is never read in watch mode), or drop --watch to launch.")
        main_wt = _main_worktree(REPO_ROOT) or REPO_ROOT
        raise SystemExit((_arm_watch or globals()["_arm_watch"])(
            tasks, args, main_wt=main_wt, _append_event=_append_event,
            _dispatch_status_events=_dispatch_status_events, _pid_alive=_launch_pid_alive,
            _watch_fleet_rows=_watch_fleet_rows, _watch_status_row=_watch_status_row,
            _watch_premature_findings=_watch_premature_findings,
            _watch_sleep=_watch_sleep, _watch_now=_watch_now))
    # T-12304 — on `--resume` the brief is OPTIONAL: the worker's instructions are the RECORDED
    # resume contract, and `--brief` carries only a DELTA. With no brief channel supplied at all the
    # briefs resolve to empty deltas (the contract alone governs); supply one and the ordinary
    # aligned + non-empty preflight applies unchanged, so a MIS-COUNTED resume still launches nothing.
    if (getattr(args, "resume", False) and not getattr(args, "brief", None)
            and not getattr(args, "brief_file", None)):
        # Absent brief channels are an EMPTY delta REGARDLESS of stdin's TTY state (post-close
        # re-audit finding fp1:b12d6ec4b3bece95): a Controller driving `dispatch --resume` from a
        # harness tool has a NON-TTY stdin with nothing on it, and routing that through the ordinary
        # resolver read an empty stream and REFUSED the very relaunch the contract exists for. A
        # non-TTY stdin that DOES carry text is still an explicitly supplied brief (the ordinary
        # single-task stdin idiom) and keeps the aligned + non-empty preflight unchanged.
        _stdin_text = "" if sys.stdin.isatty() else sys.stdin.read()
        if _stdin_text.strip():
            if len(tasks) != 1:
                _die(f"dispatch: {len(tasks)} task(s) but 1 brief(s) — supply exactly one brief per "
                     f"task (repeat --brief or -f in task order; stdin carries a single brief, "
                     f"single-task only)")
            briefs = [_stdin_text]
        else:
            briefs = [""] * len(tasks)
    else:
        briefs = _resolve_dispatch_briefs(args, len(tasks), _as_list=_as_list, _die=_die,
                                          REPO_ROOT=REPO_ROOT)   # one per task, aligned + non-empty
    # T-0733 (SPEC-0072): resolve the effort-tier routing for EVERY task up front (fail-closed
    # preflight — a bad/missing routing config or an unrecognized tier launches NOTHING), aligned 1:1.
    routing = _resolve_dispatch_routing(tasks, args, _find_task_yaml=_find_task_yaml, _read_yaml=_read_yaml,
                                        _die=_die, _resolve_effort_routing=_resolve_effort_routing,
                                        EFFORT_TIERS=EFFORT_TIERS, EFFORT_TIER_DEFAULT=EFFORT_TIER_DEFAULT,
                                        # T-12403 — the SPEC-0070 §5 claim-block gate + its journal emit
                                        _task_decomposed_from_pre_executing_plan=_task_decomposed_from_pre_executing_plan,
                                        _append_event=_append_event,
                                        # T-12897 — preflight refusals are journaled on MAIN's journal
                                        refusal_events_path=(_main_worktree(REPO_ROOT) or REPO_ROOT) / "events.jsonl")
    # T-10704 (SPEC-0167) — MIGRATION-WINDOW PRODUCT-CARD OWNER-GATE. While a migration-window plan (a
    # `MIGRATION_WINDOW_PLAN_CLASS` plan in `executing`) is open, a PRODUCT-touching card (its
    # `expected_touch` reaches any path OUTSIDE the governance/docs set — or it carries NO forecast at
    # all, fail-closed) may only dispatch if it carries `product_dispatch_owner_ack:`. Out of a window,
    # or for a governance-only card, this is a byte-identical no-op (the whole block short-circuits when
    # the injected window probe is absent or reads closed). A fail-closed PREFLIGHT refusal (all-or-
    # nothing, like the invalid-id / brief-mismatch / routing checks above): if ANY task is a
    # product-touch card lacking the ack, NOTHING launches and the refusal NAMES the exact token to add
    # (the cross-request kind:task owner-gate SHAPE — refuse + report-with-the-fix). This sits AFTER the
    # `--stop` / `--watch` branches (which launch nothing) so it gates only the launch path.
    # T-11678 — ONE per-card YAML read for this wave, shared by the SPEC-0167 product gate, the
    # readiness frame's card-precondition lines and the touch-overlap fold. Each of those three read
    # the same `_read_yaml(_find_task_yaml(t))` substrate independently before; folding them to one
    # binding removes the duplicate reads rather than adding a third. Fail-open by construction: an
    # unreadable card resolves to None, exactly as each caller already handled.
    try:
        _wave_cards = [(t, (_read_yaml(_find_task_yaml(t)) if _find_task_yaml(t) else None))
                       for t in tasks]
    except Exception:   # noqa: BLE001 — advisory/gate substrate must never break a dispatch here
        _wave_cards = [(t, None) for t in tasks]
    if _migration_window_open is not None and _migration_window_open():
        _refused = _product_gate_refusals(_wave_cards)
        if _refused:
            _die(_product_gate_refusal_message(_refused))
    provider = os.environ.get("YITC_DISPATCH_PROVIDER", "claude").strip() or "claude"
    spawn = DISPATCH_PROVIDERS.get(provider)
    if spawn is None:
        _die(f"dispatch: unknown provider {provider!r} — known: {sorted(DISPATCH_PROVIDERS)} "
             "(set YITC_DISPATCH_PROVIDER)")
    # T-12924 — the adapter's OWN declaration that its worker argv carries `--session-id <ref>` (the
    # adjacency `journal._session_proc_alive` matches). Absent ⇒ False: an undeclared adapter is never
    # scanned, so it can never be read dead while alive.
    _session_id_argv = getattr(spawn, "session_id_argv", False) is True
    # T-12986 (SPEC-0072 rule 8) — an adapter that declares how its CLI version is read gets its binary
    # from the provider binding, resolved ONCE per model and handed to the spawn; a refusal (no binding,
    # nothing resolves, every copy too old) stops the dispatch BEFORE any receipt or spawn.
    _binds_binary = bool(getattr(spawn, "version_argv", None)) and _resolve_worker_binary is not None
    _bound_binaries: dict = {}

    def _bound_binary(_m, _env):
        if _m not in _bound_binaries:
            try:
                _bound_binaries[_m] = _resolve_worker_binary(spawn, _m, _env)
            except RuntimeError as _exc:
                _die(f"dispatch: {_exc}")
        return _bound_binaries[_m]
    import uuid
    main_wt = _main_worktree(REPO_ROOT) or REPO_ROOT
    # T-10710 (X-0561) — render the standing preamble ONCE for THIS dispatch TARGET. Engine-self keeps
    # the historical bare `bin/yitc-v2 session start --type build` cue; a `-C` CONSUMER (no local
    # `bin/yitc-v2`) gets the engine-resolved `-C` form, mirroring the rescan line `session start`
    # already emits for a consumer (bin/lib/session.py, T-9469). FAIL-OPEN by construction: the
    # preamble is ADVISORY TEXT, so a missing or throwing predicate falls back to the engine form and
    # NEVER aborts a launch (a wrong cue costs one refused verb call; a raised exception costs the wave).
    try:
        _is_consumer = bool(_is_consumer_build()) if _is_consumer_build is not None else False
    except Exception:   # noqa: BLE001 — advisory text must never break a dispatch
        _is_consumer = False
    _engine_root = ENGINE_ROOT if ENGINE_ROOT is not None else REPO_ROOT
    # T-10717 — the same target-awareness for the REST of the preamble's engine invocations (claim /
    # land / task refuse / the two SPEC rule-home fetches / the header's dispatch provenance), plus
    # the SPEC-0092 `--kernel` prefix so a consumer's `graph query` reaches the KERNEL spec the
    # pointer means and not a same-id consumer-own one. Engine-self renders byte-identically.
    # T-12373 — ONE selector value per wave, derived ONCE here and threaded into EVERY render site:
    # the preamble's point 1 + its sync rule (just below), the composed brief preamble, and the
    # `bg_dispatch_launched` row's `land_regime`. Deriving it once is the point — T-12349 died on a
    # call site that did not thread it (residual fp1:17da8b93f57c097d), and a second derivation is
    # exactly how one site ends up on the other regime.
    _controller_lands = bool(getattr(args, "controller_lands", False))
    # T-12479 — the delta may only APPEND to the derived preamble: a foreign task-context block or a
    # land instruction contradicting `_controller_lands` refuses the WHOLE wave before any launch.
    _delta_refusals = [(t, r) for t, b in zip(tasks, briefs)
                       for r in _brief_delta_refusals(t, b, controller_lands=_controller_lands)]
    if _delta_refusals:
        _die("dispatch: the brief delta contradicts the composed preamble — nothing launched:\n"
             + "\n".join(f"  {t}: {r}" for t, r in _delta_refusals))
    _worker_preamble = _build_worker_preamble(
        _worker_session_start_cue(is_consumer=_is_consumer, engine_root=_engine_root),
        invoke=_worker_invocation_prefix(is_consumer=_is_consumer, engine_root=_engine_root,
                                         repo_root=REPO_ROOT),
        kernel_flag=("--kernel " if _is_consumer else ""),
        controller_lands=_controller_lands,
        # T-11294 (X-0994) — the detached-land log path is scoped to THIS dispatch target's repo, at
        # the same per-target seam T-10710/T-10717 already established. Two repos on one host with the
        # same task id no longer resolve to one /tmp file, so a worker cannot poll a foreign project's
        # LAND token and read it as its own terminality.
        sync_rule=_build_sync_to_land_rule(_land_log_path(REPO_ROOT),
                                          controller_lands=_controller_lands))
    if _is_consumer:
        # T-13176: a consumer has no graph/worker-seed.md nor the kernel's patterns/ — every relative
        # kernel path the preamble names becomes an absolute engine path (release-view cut preferred).
        try:
            from lib import graph as _graph
            _worker_preamble = _graph.consumer_render(
                _worker_preamble, is_consumer=True,
                cli_form=_worker_invocation_prefix(is_consumer=True, engine_root=_engine_root,
                                                   repo_root=REPO_ROOT),
                engine_root=_engine_root, repo_root=REPO_ROOT)
        except Exception:   # noqa: BLE001 — advisory text must never break a dispatch
            pass
        # T-13757: point 0 also names the consumer's OWN floor map (its own specs' before-* rows).
        try:
            from lib import session as _session
            _worker_preamble = _with_own_floor_map(_worker_preamble,
                                                   _session.consumer_own_floor_map(REPO_ROOT))
        except Exception:   # noqa: BLE001 — advisory text must never break a dispatch
            pass
    # T-10354 (SPEC-0133 §6 / consult verdict A-with-bounds): SELF-SERVE the dispatch-readiness advisory
    # IN THE PRE-LAUNCH DECISION FRAME — fold → visible advisory → launch. The launcher RUNS the
    # fleet-width fold ITSELF and PRINTS it BEFORE the first launch line, so wave sizing is decided
    # against LIVE state, not a separate manual pre-wave read (the missed-read failure closed by the
    # consult, decisions/dispatch-readiness-delivery-audit-adhoc.yaml). The self-read emits ONE
    # consumer_read_evidence receipt tied to the advisor surface — by journal ordering it PRECEDES this
    # wave's bg_dispatch_launched (closes fu_b808ef240bd0 / T-10100 AC3 STRUCTURALLY: the read is now the
    # launcher's, never a remember-to). REPORT-ONLY FOREVER (the anti-drift bound, SPEC-0133 §6 / CHARTER
    # §6): there is DELIBERATELY no branch here that skips/returns/resizes on a poor ceiling — the launch
    # proceeds unchanged. Telemetry, never a gate → a broken advisor FAILS OPEN (it must never block a
    # launch), so the whole block is defensive: a compute failure prints a soft note and dispatch runs on.
    # T-13237 — fold the main journal ONCE for this invocation: the worker-fit advisory below and the
    # brief composition further down both read it (never two whole-journal folds per dispatch).
    # T-13255 — a streaming fold retaining only what those readers use (never the whole journal).
    _wave_journal = (None if getattr(args, "brief_raw", False)
                     else _wave_journal_fold(main_wt / "events.jsonl", _wave_cards))
    # T-13540 — ONE frame-level read of the live `task/` worktrees, shared by the readiness block
    # (which wave ids re-use a worktree already inside live_worker_count) and the T-13204 in-flight
    # overlap below, which made this same read on its own before. Report-only and fail-open: None
    # means "unknown" — the block then discounts nothing and T-13204 falls back to its own read. The
    # per-task in-flight guard further down keeps its own deliberate re-read (T-0621).
    try:
        _frame_live = _live_task_worktrees() or {}
    except Exception:   # noqa: BLE001 — advisory substrate must never break a dispatch
        _frame_live = None
    try:
        _readiness_report, _num_live_controllers = _dispatch_readiness_report(args)
        # T-11678 — the SAME block also carries the two card-precondition lines (unarrived trigger /
        # open post-ship observation). Inside this existing try/except, so a broken fold still cannot
        # block a launch, and with NO branch anywhere below that reads either key (the §6 fence).
        print(_readiness_advisory_block(_readiness_report, len(tasks), cards=_wave_cards,
                                        today=datetime.date.today().isoformat(),
                                        mem=_wave_memory_reading(),   # T-12913, report-only
                                        fit=(journal.worker_fit(main_wt / "events.jsonl",
                                                                os.cpu_count())
                                             if _wave_journal is None
                                             else _wave_worker_fit(main_wt / "events.jsonl",
                                                                   _wave_journal)),   # T-13237/T-13255
                                        reused=[t for t in tasks if t in (_frame_live or {})]))
        # T-13020 — KERNEL self-telemetry: stamped `subject_realm: kernel`, and bound to the kernel's
        # own T-10100 only in the kernel — under `-C` that id names an unrelated consumer card.
        _append_event(
            "consumer_read_evidence",
            None if (_is_consumer_build is not None and _is_consumer_build()) else "T-10100",
            journal.kernel_self_telemetry(
            {"probe": "dispatch self-serves `journal query --dispatch-readiness` in the pre-launch "
                      "decision frame before sizing/confirming the wave (T-10354)",
             "advisor_surface": "journal query --dispatch-readiness",
             "recommended_wave_ceiling": _readiness_report["recommended_wave_ceiling"],
             "live_worker_count": _readiness_report["live_worker_count"],
             "wave_size": len(tasks), "report_only": True}),
            events_path=main_wt / "events.jsonl")
    except Exception as _radv_e:   # report-only: a broken advisor NEVER blocks a launch (SPEC-0133 §6 fence)
        print(f"dispatch-readiness advisory unavailable ({_radv_e}); launching anyway "
              f"(advisory is report-only, never a gate).")
    # T-10872 (SPEC-0165 tripwire; the T-10821 incident) — TOUCH-OVERLAP in the same pre-launch decision
    # frame, immediately after its sibling readiness advisory and BEFORE the first launch line. The
    # overlap MATH already existed in `journal query --dispatch-plan` (SPEC-0136) and was already
    # correct; what failed in the incident is that it lives in a SEPARATE OPT-IN advisor the controller
    # must remember to run — and did not. This is the T-10354 move on a second surface: the read becomes
    # the LAUNCHER's, never a remember-to. It is computed over the LITERAL `--task` list rather than by
    # calling `--dispatch-plan`, because that advisor's substrate is carve-out-scoped and silently
    # EXCLUDES non-`ready` cards (re-dispatches, in-flight orphans) — dropping precisely the tasks most
    # likely to collide while still looking complete, which is this card's own anti-goal.
    # 2+ TASKS ONLY: the atomic rule is "a dispatch of 2+ tasks reports the declared touch overlap among
    # them"; a single-task wave has no wave-internal overlap to report and stays byte-identical.
    # REPORT-ONLY FOREVER (CHARTER §6): there is DELIBERATELY no branch below that skips/returns/
    # refuses/reorders/delays/resizes on an overlap — a fully-overlapping batch launches unchanged, and
    # a source-level probe in tests/test_t10872_dispatch_touch_overlap.py asserts that absence so a
    # later "small improvement" into a gate fails a test rather than passing review. Fail-open like its
    # sibling: an advisory that can break a dispatch has become a gate by accident. It emits NO event —
    # printing does not prove a human read or acted (audit-pre absorption), so the block CUES the
    # controller to record their own decision instead of manufacturing adoption evidence from a print.
    if len(tasks) > 1:
        try:
            print(_touch_overlap_block(_touch_overlap_report(_wave_cards), len(tasks)))
        except Exception as _tov_e:   # report-only: a broken advisory NEVER blocks a launch
            print(f"touch-overlap advisory unavailable ({_tov_e}); launching anyway "
                  f"(advisory is report-only, never a gate).")
    # T-13204 — the cross-CALL half: compare this wave against cards whose workers are already in
    # flight (live task worktrees), for 1-task waves too. Report-only, fail-open, same fence as above.
    try:
        _inflight_cards = [(t, (_read_yaml(_find_task_yaml(t)) if _find_task_yaml(t) else None))
                           for t in sorted(_frame_live if _frame_live is not None
                                           else (_live_task_worktrees() or {}))]
        _inflight_text = _inflight_touch_overlap_block(_wave_cards, _inflight_cards)
        if _inflight_text:
            print(_inflight_text)
    except Exception as _iov_e:   # report-only: a broken advisory NEVER blocks a launch
        print(f"in-flight touch-overlap advisory unavailable ({_iov_e}); launching anyway "
              f"(advisory is report-only, never a gate).")
    # T-10696 (SPEC-0051, X-0548): report-only spike-mode hint — if the target project has a LIVE
    # work/spike-* worktree, surface ONCE (before the launch loop) that it is mid spike-loop. Never a
    # gate: the launch proceeds unchanged (CHARTER non-goal #7; sibling of the readiness advisory above).
    _print_spike_mode_hint()
    # T-12645 (X-1460 as corrected by X-1461) — THE PREFIX/REMAINDER BLOCK, printed ONCE, BEFORE any
    # spawn. A sequential launcher run under a foreground cap is a PREFIX operation: the ids it already
    # launched are real and running, and re-running the whole wave double-launches them. That rule was
    # documented nowhere the operator reads at the moment it matters, so the reporter followed their own
    # correct-sounding advice and caused the duplicate. Naming both sets from durable state — in the
    # order requested — is what makes a prefix impossible to mistake for a total failure.
    # SUPPRESSED WHEN CLEAN (the `debt` / readiness-advisory posture): a wave with no launched prefix
    # prints nothing at all, so ordinary dispatches are byte-identical to before this card.
    # REPORT-ONLY, and the block is deliberately computed from `_launch_axis_class` — the SAME
    # predicate the in-flight SKIP below decides on — so the two can never disagree. A broken advisory
    # NEVER blocks a launch (the touch-overlap sibling above, same treatment).
    try:
        _prefix_report = wave_prefix_and_remainder(
            tasks,
            lambda _t: _launch_axis_class(
                _inflight_events(_t, _dispatch_status_events, _dispatch_events_tail_first),
                _t, _classify_dispatch, DISPATCH_TERMINAL_TYPES,
                _session_alive=_session_proc_alive, _scan_takeable=_proc_scan_is_takeable)[0])
        if _prefix_report["launched"]:
            print(_wave_prefix_block(_prefix_report), flush=True)
    except Exception as _pfx_e:   # report-only: never a gate
        print(f"prefix/remainder advisory unavailable ({_pfx_e}); launching anyway "
              f"(advisory is report-only, never a gate).", flush=True)
    # T-12303 — the composed-brief inputs, folded ONCE PER WAVE (never once per task: the launch loop
    # below is per-task, and a per-task journal fold at this seam is exactly the N+1 the repeated-work
    # lens names). Hoisted here beside the `_wave_cards` hoist above, which is the same seam's existing
    # precedent (T-11678). Skipped ENTIRELY under `--brief-raw`, where nothing is composed.
    _brief_raw = bool(getattr(args, "brief_raw", False))
    _wave_card_map = {t: c for t, c in _wave_cards}
    _directive_rows: list = []
    _closure_rows: list = []
    if not _brief_raw:
        _directive_rows = _wave_journal["directive_rows"]
        # The `requires` cards are read through the SAME injected pair the wave cards use, so a
        # required id outside this wave still resolves its title.
        for _t, _c in _wave_cards:
            for _req in ((_c or {}).get("requires") or []):
                _req = str(_req)
                if _req not in _wave_card_map:
                    try:
                        _rp = _find_task_yaml(_req)
                        _wave_card_map[_req] = _read_yaml(_rp) if _rp else None
                    except Exception:   # noqa: BLE001 — an unreadable required card degrades to no title
                        _wave_card_map[_req] = None
        _closure_rows = _wave_journal["closure_rows"]
    _venue_line = None
    if not _brief_raw and _venue_brief_line is not None:
        try:
            _venue_line = _venue_brief_line()
        except Exception:   # noqa: BLE001 — the venue record is ONE line of context, never a gate
            _venue_line = None
    launched, skipped = 0, 0
    # T-11844: the ORDERED per-task outcome record behind the terminal token. Not a new store —
    # it names WHICH id took which existing arm, where `launched`/`skipped` above count only how
    # many. Every `continue`ing arm and the launch path append exactly one tuple here.
    outcomes: list = []
    class _SpawnRefused(Exception):
        """T-13733 — the OS refused THIS id's provider spawn (OSError at the `spawn` call itself:
        E2BIG, ENOENT, EACCES …). Raised ONLY there, so an OSError after a worker exists (a probe,
        a log read, a journal append) keeps its old propagation and is never read as «not started»."""

    for task, brief, route in zip(tasks, briefs, routing):
        # T-12332 — the per-iteration dispatch MODE. `None` on every ordinary launch (so the
        # `bg_dispatch_launched` row stays byte-identical); `"resume"` only on the paused-card
        # re-entry arm below. Initialised HERE, at the top of the iteration, so it can never leak
        # from one task to the next in a multi-task wave.
        _dispatch_mode = None
        # T-12683 — the cwd holders the guard classed as orphans for THIS task; `[]` on every launch
        # that did not go through the held-worktree arm, so the launched row carries no key there.
        _orphans: list = []
        # PRE-FLIGHT in-flight guard (T-0621): re-read the live `git worktree list` frontier PER-TASK
        # immediately before THIS task's spawn decision (the same _live_task_worktrees substrate the
        # T-0138 guard / picker §2.4 use). If a live `task/<task>` worktree already holds the id, SKIP
        # the spawn — emit ONE `bg_dispatch_skipped` event + continue to the other ids. This kills the
        # COMMON redundant dispatch BEFORE a wasted sub-session bootstrap (the T-0138 worktree guard
        # caught it only LATER, inside the worker). It is an ADVISORY read-only guard, NOT a lock — the
        # per-task re-read narrows but does not eliminate the guard→spawn window; full atomicity is the
        # PARKED T-0525 reservation rule. NO selection/ordering/reservation (non-goal #7 holds).
        live = _live_task_worktrees()
        if task in live:
            # T-9689 (RC3 recovery half) — a live `task/<task>` worktree on disk is NOT automatically a
            # LIVE hold: it may be a CONFIRMED-DEAD orphan (the worker died mid-flight, leaving a
            # dead-but-unlanded worktree). DISTINGUISH the two with the EXISTING dispatch classification
            # (Principle 1 — no new liveness logic, no new store): `_classify_dispatch` returns
            # `hang_suspect` ONLY for journal-quiescent + a live worktree claim + NO positive
            # `--session-id` alive-proc (the controller's §Abnormal «Confirmed-dead GATE» in code —
            # journal.py `_classify_dispatch` / `_session_proc_alive`); a LIVE worker is `working`
            # (recent events OR a positively-alive proc), which stays PROTECTED. Before T-9689 the guard
            # SKIPped on worktree presence alone, forcing the controller to adopt+continue inline.
            _evs = _inflight_events(task, _dispatch_status_events, _dispatch_events_tail_first)
            cls, _cdetail, _clast, dead_holder = _classify_dispatch(_evs, task)
            # T-10985 — the DETERMINED (never asserted) liveness of whoever holds this worktree.
            # T-11289 re-ordered the guard so this read runs FIRST, ahead of BOTH the destructive and
            # the preserving branch: it is now the SOLE permit for either, so a LIVE or UNVERIFIABLE
            # holder (see the helper — an unstamped/raw-git worktree names nobody, so its death cannot
            # be CONFIRMED) can reach neither. Before, a `hang_suspect` classification entered the
            # teardown on the journal-recency axis alone and the T-0362 double-claim door was held only
            # by `_park_worktree`'s downstream `_assert_no_live_holder`; one guard site, asserted here,
            # is what the audit-pre pass-2 finding asked for.
            _dead_ok, _dead_ref, _dead_why, _orphans = _orphan_holder_liveness(
                live[task], _read_worktree_stamp=_read_worktree_stamp,
                _session_proc_alive=_session_proc_alive,
                _live_path_holders=_live_path_holders,
                # T-12683 — the terminal-session orphan classification's two reads; main-bound.
                _session_terminally_over=_session_terminally_over,
                _proc_scan_is_takeable=_proc_scan_is_takeable, main_wt=main_wt)
            if not _dead_ok:
                # LIVE or UNVERIFIABLE holder → the protective SKIP (T-0362, never auto-adopt).
                msg, holder = _dispatch_inflight_report(task, live[task], main_wt,
                                                        _read_worktree_stamp=_read_worktree_stamp,
                                                        _session_last_event_ts=_session_last_event_ts,
                                                        liveness_why=_dead_why,
                                                        # T-13171 — TERMINAL with NO live holder
                                                        # proc = the fleet verdict's proc_alive=false.
                                                        fleet_terminal=(cls == "TERMINAL" and not (
                                                            _dead_ref and _session_proc_alive(_dead_ref))))
                # T-11795: every per-task outcome line the launch loop prints is FLUSHED. A
                # multi-task dispatch launches SEQUENTIALLY and each launch takes minutes, so the
                # invocation routinely outlives a caller's command timeout and is SIGTERMed
                # part-way. Python BLOCK-buffers stdout to a pipe and the default SIGTERM handler
                # terminates WITHOUT flushing, so the lines naming the workers that DID come up
                # were destroyed with the buffer: the caller saw one generic timeout and could
                # only discover the launched set afterwards by querying `bg_dispatch_launched`
                # (measured 2026-08-28 — T-11580 launched, T-11783 never did, nothing recorded the
                # truncation). Flushing makes the surviving PREFIX the caller's answer. Same idiom
                # `cmd_dispatch_watch` already uses for its incremental progress lines; it changes
                # WHEN bytes leave the buffer, never WHICH bytes (so single-task output is
                # byte-identical). No new mechanism, flag, event or store — the launcher stays thin
                # (CHARTER non-goal #7: nothing here touches parallelism/retry/ordering/selection).
                print(msg, flush=True)
                _append_event("bg_dispatch_skipped", task,
                              {"dispatch": task, "reason": "in-flight",
                               "worktree": str(live[task]), "held_by": holder},
                              events_path=main_wt / "events.jsonl")
                skipped += 1
                outcomes.append((task, "skipped", "in-flight"))
                continue
            # The holder is DETERMINED dead. What happens to its worktree now turns on ONE question —
            # is there anything in it a fresh claim cannot re-derive? (T-11289; computed only here, so
            # the live-holder SKIP above pays no git call.)
            _carries_work, _work_why = _orphan_carries_work(live[task], task, _run_git_cap=_run_git_cap)
            # T-12332 — is this a PAUSED card, i.e. one whose re-entry is `task resume` rather than a
            # claim? Read AFTER `_orphan_holder_liveness` has already permitted the branch, so this
            # decides only the BRIEF and the row's `mode`, never admission (the fence above is the
            # sole permit). A paused card ALSO fails the teardown conjunct below: its pause record and
            # its worktree ARE the contract, and `_redispatch_dead_orphan` refuses a non-`ready` card
            # anyway — so before this conjunct an EMPTY paused orphan entered the destructive arm only
            # to come back out as `OrphanTeardownRefused`, i.e. a protective SKIP naming a manual fix.
            # That was the second route by which a paused card was un-dispatchable (X-1344).
            _resume = _resume_entry_card(_wave_card_map.get(task))
            if cls == "hang_suspect" and not _carries_work and not _resume:
                # CONFIRMED-DEAD orphan with NOTHING TO LOSE → tear it down (park --confirm-dead
                # semantics: verify the task is still `ready` on main, force-remove the worktree +
                # delete the branch + prune, emit `worker_parked`) so a FRESH worker can claim, then
                # FALL THROUGH to spawn one. No controller inline-adopt forced (the X-0098 / RC3
                # friction). A teardown refusal FAILS CLOSED to the protective SKIP — never
                # re-dispatch over an unverifiable state.
                # T-11289 narrowed the ENTRY, not the mechanics: `_orphan_carries_work` is
                # positive-evidence-for-EMPTY, so this arm now fires only for the case it was built
                # for — a worker that died holding nothing but its own re-derivable claim. A worktree
                # carrying un-landed commits or a saved `decisions/<task>-audit-*.yaml` takes the
                # preserving branch below instead. Measured 2026-08-18: T-11247 and T-11250 both read
                # `hang_suspect` + determined-dead while holding paid external-auditor verdicts, so
                # before this narrowing a routine re-dispatch destroyed them silently.
                try:
                    pdata = _redispatch_dead_orphan(task)
                except OrphanTeardownRefused as _e:
                    print(f"dispatch: REFUSED {task} (dead-orphan-teardown-refused: confirmed-dead orphan "
                          f"in {live[task]} but its worktree teardown was REFUSED ({_e})); NOT "
                          f"re-dispatching. Resolve manually "
                          f"(`worktree adopt`/`worktree park`) then re-dispatch. The other --task ids "
                          f"still launch.", flush=True)
                    _append_event("bg_dispatch_skipped", task,
                                  {"dispatch": task, "reason": "dead-orphan-teardown-refused",
                                   "worktree": str(live[task]), "held_by": dead_holder},
                                  events_path=main_wt / "events.jsonl")
                    skipped += 1
                    # T-11844: REFUSED, not merely skipped — the in-flight guards defer to a live
                    # sibling (cleanly re-dispatchable later), while a refused teardown needs a
                    # HUMAN (`worktree adopt`/`park`). The counter keeps its existing tally; the
                    # token distinguishes them, which is the point of a machine-readable outcome.
                    outcomes.append((task, "refused", "dead-orphan-teardown-refused"))
                    continue
                print(f"dispatch: re-dispatching {task} — confirmed-dead orphan torn down "
                      f"(dead holder {dead_holder or 'UNKNOWN'}, branch {pdata.get('branch')}); "
                      f"nothing beyond the re-derivable claim was in it; worker_parked emitted, "
                      f"spawning a FRESH worker.", flush=True)
                # fall through to spawn (the worktree+branch are gone → `worktree new --task` succeeds)
            else:
                # T-10985 — the PRESERVING orphan re-dispatch. A worker that STOPPED BY CONTRACT (a
                # `bg_dispatch_halted` escalation / a death terminal) leaves a SETTLED terminal AND an
                # intact worktree that may carry an un-landed ship commit. The T-9689 arm above does
                # not reach it (that keys on `hang_suspect`, a journal-QUIESCENT non-terminal), so it
                # fell into the SKIP — and the documented recovery route (respawn a fresh worker
                # to ADOPT the committed worktree, patterns/background-session-monitoring.md §Abnormal)
                # became UNEXECUTABLE: the worker that must perform the adopt could not be launched
                # until the adopt had happened, and `--force` covers only the launched-but-no-worktree
                # case. A controller adopting first to break the tie re-stamps the worktree to a LIVE
                # session, which this same guard reads as held — the loop closes again. Observed on
                # T-10975 (2026-08-12): a routine tail recovery had to escalate to the owner.
                #
                # So: PRESERVE (never tear down — there is work to lose) and fall through to spawn,
                # with the brief's claim step overridden to adopt.
                #
                # T-11289 WIDENED this arm from `cls == "TERMINAL" and _dead_ok` to the DEFAULT for
                # any determined-dead holder, on the incident that a STOPPED worker never reaches a
                # settled terminal at all. Measured 2026-08-18: a worker stopped mid-flight leaves a
                # RECENT journal, so `_classify_dispatch` reads `working(recent)` — a TIMESTAMP
                # inference — while `_orphan_holder_liveness` on the same worktree already returns
                # (True, <dead ref>, ""). Direct two-axis process evidence and a recency guess
                # disagreed, and the recency guess won: reason `in-flight`, 0 launches, and the only
                # documented exits were teardown or controller self-execution.
                # The retired `cls == "TERMINAL"` scope was defended as a belt — "a `working` holder
                # can never enter here even with an unreadable /proc" — and that is NOT load-bearing:
                # both liveness reads already fail toward "no evidence of life" (`_session_proc_alive`
                # returns False on any scan error, `_live_path_holders` yields no holder without
                # /proc), so under a blind /proc the belt is accidental, and every peer gate on this
                # route — `worktree adopt --confirm-dead`, `park`, `recover-land`, fleet-verdict —
                # already rests on those same two reads. SPEC-0134 rule 2 names that pair the ENFORCER
                # of "adoption is the DEATH path"; this makes the launcher agree with it.
                # The permit is DETERMINED, never asserted, and is now checked ABOVE (T-0362, the
                # double-claim incident). No new flag (the guard must not key on the operator's word),
                # no new event type, no new store.
                print(f"dispatch: re-dispatching {task} into its PRESERVED confirmed-dead orphan "
                      f"worktree {live[task]} (class {cls}"
                      f"{'/' + _cdetail if _cdetail else ''}; dead holder {_dead_ref}; no live "
                      f"process, "
                      + (f"cwd holders {[h['pid'] for h in _orphans]} are ORPHANS of that "
                         f"terminally-over session (T-12683 — reaped by the adopt); "
                         if _orphans else "no live cwd holder; ")
                      + f"{_work_why or 'nothing beyond the re-derivable claim'}). The worktree is NOT "
                      f"torn down — it may carry an un-landed ship commit or a paid audit record; the "
                      f"fresh worker ADOPTS it (`worktree adopt --task {task} --confirm-dead`, "
                      f"liveness re-verified in code).", flush=True)
                # T-12332 — the OVERRIDE TEMPLATE is chosen by the CARD, not by a flag. A paused
                # in-progress card gets the RESUME-first sequence (adopt -> `task resume` -> stage),
                # because the adopt alone leaves `paused_at` set and the worker would edit a card the
                # system still reads as paused. Every other card keeps the historical adopt-first
                # text byte-identically.
                if _resume:
                    _dispatch_mode = "resume"
                    print(f"dispatch: {task} is IN-PROGRESS and PAUSED (paused_at "
                          f"{_resume['paused_at']}, reason {_resume['paused_reason']}) — this is a "
                          f"RESUME, not a claim. The brief's entry is `worktree adopt` -> "
                          f"`task resume` -> `stage {_resume['stage']}`; the launch row carries "
                          f"mode=resume (T-12332).", flush=True)
                    brief = RESUME_ADOPT_BRIEF_OVERRIDE.format(
                        task=task, wt=live[task],
                        invoke=_worker_invocation_prefix(is_consumer=_is_consumer,
                                                         engine_root=_engine_root,
                                                         repo_root=REPO_ROOT),
                        paused_at=_resume["paused_at"], paused_reason=_resume["paused_reason"],
                        stage=_resume["stage"], next_action=_resume["next_action"]) + "\n" + brief
                else:
                    brief = ORPHAN_ADOPT_BRIEF_OVERRIDE.format(task=task, wt=live[task]) + "\n" + brief
                # fall through to spawn (worktree + branch intact; the worker adopts, never re-claims)
        # PRE-FLIGHT in-flight-DISPATCH guard (T-9636, X-0124): the T-0621 live-worktree check above is
        # blind to the window where a SIBLING controller already launched a worker for THIS id but the
        # worker has not yet bootstrapped its task/<task> worktree — the worker journals
        # `bg_dispatch_launched` on MAIN's journal BEFORE creating the worktree, so two controllers reading
        # the same ready queue both dispatch it (the per-task-id worktree guard caught the double-claim only
        # LATER, inside the second worker).
        # THE WINDOW IS ~60s, NOT THE "~8s" THIS COMMENT USED TO CLAIM (measured, T-11846). It is not the
        # worker's bootstrap latency: it is THIS loop's own read→write lag. The guard reads HERE, near the
        # top of the iteration, and its own `bg_dispatch_launched` is appended only AFTER the blocking
        # `spawn(...)` below — measured at ~62s per task on 2026-08-29. So a sibling dispatcher's launch row
        # can appear at any point in that minute and this read will have missed it. Measured on the
        # 2026-08-29T19:44–19:49Z triple double-dispatch (T-11697/T-11717/T-11038, controller 8ea2d2bb):
        # for all three ids the second dispatcher's guard read fell 11–12s BEFORE the first dispatcher's
        # launch row existed, so the guard read a journal with no in-flight launch and correctly did not
        # skip. NOT a bypass and NOT a defeat: the conjunction below was FALSE when it was evaluated
        # (`_launch_cls == "none"`), so no value of `--force` could have changed the outcome — which is
        # just as well, because the dispatcher's argv is recorded NOWHERE in the journal (T-11854). Closing this window is a RESERVATION, i.e. the parked
        # T-0525 owner decision; do not narrow it by tightening these predicates. Beware the mis-timed
        # replay that made this look like a defeated guard: truncating the chain at the SECOND LAUNCH's
        # timestamp yields (working, working) here, but truncating at the GUARD READ — the instant this
        # line actually runs — yields `_launch_cls == "none"`. REUSE the existing dispatch-status reader (Principle 1 — no new
        # store/mechanism): a `working` classification with NO live worktree (the live check above already
        # `continue`d on a live one) == a recent launched-but-not-yet-claimed dispatch still in flight. A
        # dead/stale prior dispatch classifies silent_stop (NOT working), so re-dispatch stays correctly
        # ALLOWED. ADVISORY read-only (no lock/reservation — full atomicity is the PARKED T-0525), same as
        # the T-0621 guard; the per-task re-read narrows but does not eliminate the guard->spawn window.
        # T-11854 — RECORD the guard's READ INSTANT, so the NEXT occurrence of a lost read->spawn race
        # is establishable from events.jsonl ALONE. T-11846 could answer "bypassed or defeated?" only by
        # recovering the controller's argv from a PROVIDER TRANSCRIPT (outside the governed store) and by
        # reconstructing this instant INDIRECTLY from the T-10083 worker-seed `session_started` row that
        # happens to be appended between the guard and the spawn — an accident of ordering a refactor can
        # silently remove, not a durable fact. Stamped HERE, one line above the read it dates, and carried
        # on the `bg_dispatch_launched` payload appended ~62s later (after the blocking spawn) as
        # `guard_read_ts`/`guard_cls`/`guard_launch_cls`/`guard_force`. RECORD-ONLY: no branch reads those
        # keys and this local drives no control flow (AST-fenced, tests/test_t11854_*, the same fence shape
        # the readiness/touch-overlap advisories carry). The WINDOW IS UNCHANGED — closing it is a
        # reservation, i.e. the PARKED T-0525 owner decision, and this card does not touch it.
        _guard_read_ts = (_utc_now_iso() if _utc_now_iso else
                          datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
        _evs = _inflight_events(task, _dispatch_status_events, _dispatch_events_tail_first)
        cls, _detail, _last_ts, holder = _classify_dispatch(_evs, task)
        # X-0131 fix (T-9643): `cls == "working"` is driven by the most-recent NON-terminal event of ANY
        # type — a fresh `commit_landed`/`task_filed` (a just-filed id) OR a self-emitted
        # `bg_dispatch_skipped`. So the original bare `cls == "working"` SKIP false-fired on a freshly
        # filed task AND self-reinforced a phantom: each skip re-appends a recent `bg_dispatch_skipped`,
        # so the id never ages to silent_stop and becomes PERMANENTLY un-dispatchable (<project>
        # T-0029). The in-flight-DISPATCH signal is SPECIFICALLY a recent `bg_dispatch_launched` with no
        # live worktree (the live check above already `continue`d on a live one). Re-classify on the
        # launched-ONLY sublist: it has no terminal, so a RECENT launch hits the same recency branch and
        # yields "working"; a stale/absent launch yields silent_stop/"none". A skip/file event alone is
        # NOT a launch → not in-flight. `--force` is the explicit escape (X-0131 ask (b)).
        # T-10376 — the launched-sublist axis must CONSUME a launch-terminating terminal (the governed
        # `dispatch --stop` recovery emits `bg_dispatch_halted` for a claim-less rogue). The bare
        # launched-ONLY filter STRIPPED every terminal, so `_classify_dispatch` on it could NEVER see the
        # halt → the launched axis read `working` for a HALTED launch, and the SKIP was averted only by
        # the full-list `cls` catching the terminal (a coincidence — the X-0131 comment DESIGNATES this
        # sublist as the authoritative in-flight signal). Include the launch-terminating terminals
        # (DISPATCH_TERMINAL_TYPES) alongside `bg_dispatch_launched` so `_launch_cls` becomes TERMINAL
        # once a halt/close/wont-do lands → the two axes AGREE and a stopped rogue is redispatchable
        # WITHOUT --force. X-0131 stays intact: filed/skip/commit noise (no launch, no terminal) is still
        # excluded, so a never-launched id never phantom-skips.
        # T-12645 — ONE definition of this axis, shared with the PREFIX/REMAINDER block above the loop
        # (`_launch_axis_class`), so the block and this SKIP can never disagree about an id. The
        # sublist now also carries `bg_dispatch_spawned`, which is what makes a killed parent's live
        # worker visible here instead of reading `none` and being double-launched (X-1461).
        _launch_evs = _launch_axis_events(_evs, DISPATCH_TERMINAL_TYPES)
        # T-12924 — the SAME two liveness reads as the PREFIX block above (and as the fleet verdict),
        # so the block and this SKIP still decide on ONE predicate.
        _launch_cls, _ld, _lt, _lh = _launch_axis_class(
            _evs, task, _classify_dispatch, DISPATCH_TERMINAL_TYPES,
            _session_alive=_session_proc_alive, _scan_takeable=_proc_scan_is_takeable)
        # T-10588 (X-0441) — SETTLED-PAUSE override. A BOOKKEEPING-ONLY owner-wait pause (T-9320 /
        # T-10576, the SPEC-0103 §5 pause-shape fork) emits `task_paused`, LANDS its record, and the
        # worker EXITS — but `task_paused` is in no DISPATCH_TERMINAL_TYPES, so the launched axis kept
        # reading `working` and every re-dispatch after an owner unblock demanded the X-0131 `--force`
        # (<project> burned two redundant attempts). The landed-ness signal already exists on main and
        # needs NO new store/event: the CARD carries `paused_at`, and a card on MAIN carries it only
        # once the pause bookkeeping LANDED — a WORK-CARRYING pause never lands, so its card on main has
        # no `paused_at` and its INTACT worktree trips (b) below. Peer of the T-10378 worker_parked
        # row-terminal fold + the T-10577 strand cross-check: a CARD read beside the journal-axis class,
        # NOT a second classifier path (SPEC-0133 rule 5).
        # FAIL-CLOSED on every axis (audit-pre F1) — the AC's "no live worktree/proc" predicate is
        # asserted HERE, never inherited from the earlier T-0621 `continue`, so a future caller-order
        # change cannot silently widen the override into a double dispatch:
        #   (a) the main card positively reads in-progress + paused_at + paused_reason=owner-wait
        #       (None/unreadable card → no override, the fail-open read can never CLEAR the guard);
        #   (b) no live worktree holds the id (re-asserted locally, not inherited);
        #   (c) the newest launch's pid no longer verifies as its assigned worker ref.
        _settled_pause = False
        if cls == "working" and _launch_cls == "working" and not getattr(args, "force", False):
            _card = _main_task_strand_state(task) if _main_task_strand_state else None
            if (_card and _card.get("status") == "in-progress" and _card.get("paused")
                    and _card.get("paused_reason") == "owner-wait"
                    and task not in _live_task_worktrees()):
                _nl = next((e for e in reversed(_launch_evs)
                            if e.get("type") == "bg_dispatch_launched"), None)
                _nd = (_nl.get("data") if _nl and isinstance(_nl.get("data"), dict) else {}) or {}
                _pid, _wref = _nd.get("pid"), _nd.get("expected")
                _proc_live = bool(_pid is not None and _wref and _pid_is_session
                                  and _pid_is_session(_pid, _wref))
                if not _proc_live:
                    _settled_pause = True
                    print(
                        f"dispatch: {task} — prior dispatch SETTLED by a LANDED owner-wait pause "
                        f"(card in-progress+paused on main, no live worktree, launch proc gone). "
                        f"Re-dispatching WITHOUT --force (T-10588 / X-0441).", flush=True
                    )
        # T-12304 — CONTROLLER-WAIT release, asserted EXPLICITLY on its own predicate (the peer of
        # the T-10588 settled-pause override above, and placed at the same seam). A clean cued stop
        # recorded `task_paused(controller-wait)` and the worker EXITED, so it is NOT in flight; the
        # guard must yield WITHOUT `--force`. Deliberately NOT resting on the full-list `cls` no
        # longer reading `working` (the classifier now mints `paused`): the surrounding comments warn
        # exactly against a guard that holds by coincidence of another axis.
        _cw_release = _controller_wait_release(_evs)
        # `--resume` is FAIL-CLOSED on that same row: relaunching «from the recorded contract» with no
        # recorded contract would silently degrade to an ordinary dispatch carrying an empty brief.
        if getattr(args, "resume", False) and _cw_release is None:
            # T-12837 (X-1526/X-1530) — name what IS live and the ONE route for it, never a dead end:
            # `--resume` serves only controller-wait; every other pause/halt re-enters through the
            # ordinary `dispatch --task` (a paused card launches in resume mode, T-12332).
            _other = next((e for e in reversed(_evs) if e.get("task_id") == task
                           and e.get("type") in ("task_paused", "bg_dispatch_halted")), None)
            _seen = ""
            if _other is not None:
                _od = _other.get("data") or {}
                _seen = (f" Newest stop for this id: {_other.get('type')}"
                         f"({_od.get('reason') or _od.get('kind') or '?'}) @ {_other.get('ts')}.")
            _die(f"dispatch --resume {task}: `--resume` serves ONLY a live "
                 f"`task_paused(reason=controller-wait)` row newer than the newest launch, and there is "
                 f"none — no recorded controller-wait contract to relaunch from.{_seen} Every OTHER "
                 f"pause or halt (audit-ceiling, blocked-on-land, owner-wait, ...) re-enters through "
                 f"the ordinary route: `yitc-v2 dispatch --task {task} --brief ...` (a paused card "
                 f"launches in resume mode -> `task resume {task}`, T-12332). Check "
                 f"`yitc-v2 journal query --dispatch-status --task {task}` first.")
        if _cw_release is not None and not _settled_pause:
            _settled_pause = True
            print(f"dispatch: {task} — prior dispatch ended in a CLEAN CUED STOP "
                  f"(task_paused reason=controller-wait @ {_cw_release.get('ts')}, newer than the "
                  f"newest launch). Not in flight; launching WITHOUT --force (T-12304).", flush=True)
        if (cls == "working" and _launch_cls == "working"
                and not getattr(args, "force", False) and not _settled_pause):
            # T-10254 — this guard's `holder`/`held_by` is the SIBLING CONTROLLER that already launched
            # this id (its stdout line says "controller session ..."), NOT the worker it launched. Read
            # it from the newest launch event's ENVELOPE `session_ref` — the dispatcher's own ref — and
            # never from `_classify_dispatch`'s 4th value, which is now the WORKER's assigned ref E
            # (`data.expected`) for every dispatched row, by construction. Before T-10254 the two
            # COINCIDED pre-anchor (the row inherited the dispatcher's envelope ref) — precisely the
            # defect T-10254 fixes — and this guard was silently resting on that coincidence. One return
            # value, two meanings; the guard now names the one it wants at its own call site.
            # Deviation captured: classify-dispatch-sref-overloaded-row-identity-vs-inflight-guard-holder.
            _newest_launch_ev = next((e for e in reversed(_launch_evs) if e.get("session_ref")), None)
            holder = (_newest_launch_ev.get("session_ref") if _newest_launch_ev else None) or holder
            print(
                f"dispatch: SKIPPED {task} (in-flight-dispatch: an in-flight bg_dispatch is already "
                f"launched for it by controller session {holder or 'unknown'}, worker not yet at a "
                f"worktree). NOT spawning "
                f"a redundant worker: a sibling controller already dispatched this id. Re-check via "
                f"`yitc-v2 journal query --dispatch-status`. The other --task ids still launch.",
                flush=True
            )
            _append_event("bg_dispatch_skipped", task,
                          {"dispatch": task, "reason": "in-flight-dispatch", "held_by": holder},
                          events_path=main_wt / "events.jsonl")
            skipped += 1
            outcomes.append((task, "skipped", "in-flight-dispatch"))
            continue
        # PREPEND the standing worker-execution-discipline preamble (T-0622) so every dispatched
        # headless worker is told the synchronous-to-LAND + subagent-role contract UPFRONT, even if
        # the controller's brief omits it. The preamble is a standing wrap, NOT composed from the task
        # (that stays _resolve_dispatch_briefs's "carry what it is handed" contract — non-goal #7).
        # T-0733 (SPEC-0072): launch on the effort-tier-resolved (model, effort). The provider-bound
        # selection lives in _spawn_claude_worker (P4b); cmd_dispatch only carries the resolved pair.
        # T-10578 (X-0429): a re-dispatched task carries its JOURNAL-verified prior state INTO the
        # brief — the last audit verdicts + consult verdict + any live task_paused reason for THIS id,
        # from the SAME per-id journal fold the in-flight guards read (Principle 1). So a re-dispatch
        # brief can no longer assert a clean post-land orphan over an audit-post RED / an owner-wait
        # pause. First dispatch → None state → no tail (report-only, fail-open on any read error).
        # T-10627: read it TAIL-FIRST via the reader already in hand (the `_inflight_events` shape —
        # no new plumbing/primitive/constant). The fail direction is this fold's OWN, not T-10398's:
        # this read is report-only and fail-OPEN, so a tail-only MISS would silently DROP the block
        # and let a brief assert a clean post-land orphan over an audit-post RED / a live pause — the
        # exact X-0429 defect. Hence the tail-POSITIVE / full-read-on-NEGATIVE shape is load-bearing,
        # not latency: a NEGATIVE (prior lifecycle below the 24h cutoff — the >24h-back RED/pause case)
        # re-decides on FULL history, so the block still appears.
        try:
            # T-10771: read UNSCOPED (`_redispatch_events`, same tail-first + fail-closed-negative
            # semantics) — the resolved-halt predicate's LAND arm matches `land_completed` by branch,
            # which a task-scoped list does not carry. The in-flight GUARDS above keep `_inflight_events`.
            _redispatch_tail = _compose_redispatch_state_block(
                _journal_redispatch_state(task, _redispatch_events(
                    task, _dispatch_status_events, _dispatch_events_tail_first)))
        except Exception:   # noqa: BLE001 — a journal read failure NEVER blocks a launch (report-only)
            _redispatch_tail = ""
        # T-12304 — on `--resume`, the recorded contract HEADS the task-specific brief (position 1,
        # right after the standing preamble that keeps position 0). `_cw_release` is the SAME row
        # stamped as `resume_of` below, so the brief and the launch row cannot disagree.
        _resume_head = _resume_contract_block(_cw_release) if getattr(args, "resume", False) else ""
        # T-12303 — PREAMBLE + DELTA. The Controller's brief is the DELTA; everything a Controller
        # used to retype is DERIVED here from the wave's one journal fold + this card. `--brief-raw`
        # keeps the historical verbatim pass-through for the rare hand-crafted case. FAIL LOUD, unlike
        # every other advisory at this seam: a preamble that silently vanished would launch a worker
        # believing its brief complete while the owner's binding rules were missing from it.
        if not _brief_raw:
            try:
                _card = _wave_card_map.get(task)
                _preamble_text = _compose_brief_preamble(
                    task, _card,
                    _brief_owner_rules(_directive_rows, task,
                                       plan_slug=(_card or {}).get("decomposed_from")),
                    _brief_shipped_requires((_card or {}).get("requires") or [], _closure_rows,
                                            _wave_card_map.get),
                    _venue_line, controller_lands=_controller_lands)
            except Exception as _bp_e:   # noqa: BLE001 — see the FAIL LOUD note above
                _die(f"dispatch: could not compose the brief preamble for {task} ({_bp_e}) — "
                     f"refusing to launch a worker whose brief would silently omit the card's "
                     f"acceptance and the owner's binding rules. Fix the cause, or pass "
                     f"`--brief-raw` to send your brief verbatim as the whole prompt.")
                return
            brief = f"{_preamble_text}\n\n{brief}"
        # T-12303 (audit-post fp1) — the FINAL prompt, composed FIRST, then LOCATED. The brief file
        # must be the EXACT bytes the worker reads, so it is written from the SAME string handed to
        # `spawn` — including the standing DISPATCH_WORKER_PREAMBLE that `_compose_worker_brief`
        # prepends and the journal tail it appends. Writing the file BEFORE that wrap (the original
        # shape) made the locator resolve to composed-preamble+delta while the worker received
        # preamble + that content: a locator that could not reproduce the prompt.
        _worker_prompt = _compose_worker_brief(brief, _redispatch_tail, _worker_preamble,
                                               resume_head=_resume_head or None)
        # T-12607 (SPEC-0072 rule 7) — ONE complete launch TRY on a given (model, effort): a FRESH
        # worker identity, its own log, its own governed seed-read receipts, its own brief file, the
        # spawn. It is a closure because composing a worker's identity and brief is the LAUNCHER's
        # job; WHICH pair gets tried, and when, is the policy that lives in `launch_worker_with_pair`.
        # A relaunch on the reserve is therefore a genuinely fresh worker, never a re-used identity.
        def _attempt(_m, _e, _prompt=_worker_prompt, _task=task):
            session_id = str(uuid.uuid4())            # fresh, distinct per-worker identity (M2 H1)
            env = _dispatch_worker_env(os.environ, session_id,
                                       SESSION_IDENTITY_REGISTRY=SESSION_IDENTITY_REGISTRY,
                                       provider_carriers=PROVIDER_CARRIERS)   # scrub identity+transcript carriers + assign expected
            ensure_session_scratch_root(session_id)   # T-13203   # the YITC_SCRATCH_DIR the env names
            log_path = main_wt / ".yitc" / "dispatch-logs" / f"{_task}-{session_id}.log"
            _spawn_kw = {"binary": _bound_binary(_m, env)} if _binds_binary else {}
            # T-10083 (SPEC-0050 §8): GOVERNED worker seed-read bootstrap — emit the worker's
            # session_started anchor + seed_read + verb-inventory receipts into MAIN's journal for the
            # ASSIGNED worker ref (session_ref override — the T-0561 diagnostic-emit path) BEFORE the spawn.
            # This is the RECEIPT-producing CODE PATH (not the preamble): the worker's first claim
            # `worktree new` finds them already present and passes the anti-Forgetting read-gates without a
            # `session start` first (the dispatch chicken-and-egg — the worker seed only auto-injects on cd
            # INTO the worktree, which `worktree new` gates BEFORE). seed_read PRECEDES worktree_created by
            # construction (appended here, pre-spawn). SAME main-journal path as bg_dispatch_launched below.
            for _bt, _btid, _bdata in _worker_seed_bootstrap_events(
                    session_id, SEED_READ_NODE_ID=SEED_READ_NODE_ID,
                    HELP_INVENTORY_NODE_ID=HELP_INVENTORY_NODE_ID, project=main_wt.name):
                _append_event(_bt, _btid, _bdata, session_ref=session_id,
                              events_path=main_wt / "events.jsonl")
            brief_path = None
            if not _brief_raw:
                brief_path = _brief_file_path(log_path)
                brief_path.parent.mkdir(parents=True, exist_ok=True)
                brief_path.write_text(_prompt, encoding="utf-8")
            # T-12645 — THE WINDOW CLOSES HERE. `spawn` returns a live pid; everything downstream of
            # this point (the T-12607 probe, a reserve switch, the unbounded no-reserve wait loop, and
            # only THEN the `bg_dispatch_launched` append) can take ~50s or more, and a parent killed
            # by a foreground cap anywhere in it used to leave that RUNNING worker with no task-tied
            # trace in main's journal at all (the pre-spawn seed receipts are task_id=None by
            # construction, so no task-scoped fold reaches them). Measured: <project> 2026-09-16,
            # X-1460 as corrected by X-1461 — the fold read ABSENT and the controller double-launched.
            # So the FIRST act after the spawn is to record it, carrying the same join keys
            # `bg_dispatch_launched` carries (`expected` + `pid`), and this record is part of the
            # spawn TRANSACTION — it reaps and refuses rather than leaving a worker unrecorded
            # (`_record_spawn_or_reap`, audit-pre fp1:5f22e2403fe460a9).
            try:
                _pid = spawn(_prompt, session_id, env, log_path, model=_m, effort=_e, **_spawn_kw)
            except OSError as _exc:   # T-13733: no process exists for this attempt
                raise _SpawnRefused(_exc) from _exc
            _record_spawn_or_reap(
                _pid, _task,
                {"dispatch": _task, "expected": session_id, "provider": provider, "pid": _pid,
                 "log": str(log_path), "model": _m, "effort": _e,
                 "source_tier": route["source_tier"],
                 # T-12924 — does this worker's argv carry `--session-id <expected>`? Read off the
                 # adapter ACTUALLY spawned (never inferred from the provider NAME), so the launch-axis
                 # scan runs only where a live worker is findable (`_launch_axis_class`).
                 "session_id_argv": _session_id_argv},
                _append_event=lambda _t, _tid, _d: _append_event(
                    _t, _tid, _d, events_path=main_wt / "events.jsonl"),
                _reap=_reap_worker, _die=_die)
            return {"pid": _pid,
                    "session_id": session_id, "log_path": log_path, "brief_path": brief_path}

        # T-12607 — the PRIMARY launches; its tier's OPTIONAL RESERVE pair runs ONCE, and only on a
        # NON-ANSWER (a capacity/overload bootstrap death, or never coming up with no worker output at
        # all). An AUTH failure is not a non-answer and neither switches nor waits (T-10792); with NO
        # reserve declared there is NO switching — the dispatch waits and retries the primary,
        # heartbeat-journaled. A per-field `--model/--effort` override wins over BOTH pairs, which is
        # why the resolver is handed `args` (SPEC-0072 PRECEDENCE, unchanged).
        _reserve = None
        if _resolve_effort_reserve is not None:
            try:
                _reserve = _resolve_effort_reserve(route["source_tier"], args)
            except Exception:   # noqa: BLE001 — an unreadable reserve is «none declared», never a crash
                _reserve = None
        # T-13733 (X-1872) — a spawn the OS refuses (E2BIG, ENOENT, EACCES …) is THIS id's outcome,
        # never the wave's: report it per id and go on to the next id, which used to be lost with it.
        # Only `_SpawnRefused` is caught — raised at the spawn call alone, so nothing that happens
        # after a worker exists can be reported as «not started».
        try:
            _launch = launch_worker_with_pair(
                _attempt, task, route["source_tier"], (route["model"], route["effort"]), _reserve,
                _append_event=lambda _t, _tid, _d: _append_event(
                    _t, _tid, _d, events_path=main_wt / "events.jsonl"),
                _proc_alive=_launch_pid_alive, _read_log=_read_launch_log,
                _launch_failure_signature=journal._launch_failure_signature, _die=_die,
                _sleep=_launch_probe_sleep, _monotonic=_launch_probe_monotonic,
                probe_seconds=_launch_probe_seconds_override,
                wait_seconds=_launch_wait_seconds_override,
                _reap=_reap_worker)   # T-12645: the auth arm reaps when its terminal cannot be recorded
        except _SpawnRefused as exc:
            print(f"dispatch: REFUSED {task} (launch-error: {exc.__cause__!r}) — the provider spawn was "
                  f"refused, so this attempt started no worker; the card stays ready.",
                  file=sys.stderr, flush=True)
            outcomes.append((task, "refused", "launch-error"))
            continue
        session_id = _launch["session_id"]
        pid = _launch["pid"]
        log_path = _launch["log_path"]
        _brief_path = _launch["brief_path"]
        # T-12896 (<project> X-1546 / X-1555) — the launch probe WATCHED this worker die during bootstrap.
        # Its terminal is already on main's journal (premature_exit, phase bootstrap, log tail), so
        # write NO `bg_dispatch_launched` over the corpse — a newer launch row would segment that halt
        # away and the reader would call it `working(still-booting)` for the whole grace — and say so
        # where the caller reads the launch: a loud per-id line, a `refused(reason=bootstrap-died)`
        # fragment, and (for a wave where nothing came up) the existing T-12681 non-zero exit below.
        _died = _launch.get("bootstrap_died")
        if _died:
            _tail = str(_died.get("log_tail") or "")
            _last = next((ln for ln in reversed(_tail.splitlines()) if ln.strip()), "(log empty)")
            _rec = ("recorded as bg_dispatch_halted(kind=premature_exit, phase=bootstrap) on main's "
                    "journal" if _launch.get("bootstrap_recorded") else
                    "its halt could NOT be written to main's journal, so the `bg_dispatch_spawned` "
                    "receipt is UN-TERMINATED (it reads proc-gone on the launch axis)")
            print(f"dispatch: BOOTSTRAP-DIED {task} (pid {pid} exited before its first verb — "
                  f"last log line: {_last}) — {_rec}; the card stays ready. Worker log: {log_path}",
                  file=sys.stderr, flush=True)
            # T-12986 — the recorded (byte-bounded) log tail, not just its last line.
            for _ln in [x for x in _tail.splitlines() if x.strip()][-_TAIL_PRINT_LINES:]:
                print(f"dispatch:   | {_ln}", file=sys.stderr, flush=True)
            outcomes.append((task, "refused", BOOTSTRAP_DIED_REASON))
            continue
        # ONE dispatch event per task, bound to MAIN's journal (append-only, no worktree — D-0049).
        # Carries `expected` (the assigned worker ref) — distinct from the controller's envelope
        # session_ref. The append completes here before the next loop iteration spawns (serialized).
        # T-0733: + the resolved model/effort/source_tier/override (the SPEC-0072 routing probe).
        _append_event("bg_dispatch_launched", task,
                      {"dispatch": task, "expected": session_id, "provider": provider,
                       "pid": pid, "log": str(log_path),
                       "session_id_argv": _session_id_argv,   # T-12924 — see the spawn row above
                       # T-12303 — the COMPOSED brief, beside the log: this locator resolves to the
                       # EXACT text the worker read, byte-for-byte (standing preamble + composed
                       # preamble + delta + any journal tail — the same string handed to `spawn`). Absent under `--brief-raw` (nothing composed),
                       # which is AC1's and AC4's differential. No new event type — the row is the
                       # existing one.
                       **({"brief": str(_brief_path)} if _brief_path else {}),
                       # T-12373 — the LAND REGIME this worker was launched under, so the
                       # stage-entry reminder (and any later reader) resolves the SAME contract the
                       # brief carries instead of assuming one. ADDITIVE key on the EXISTING row: no
                       # new event type, and a pre-change row's ABSENT key reads as `worker`
                       # (`land_regime_for_worker`, fail-safe toward canon).
                       "land_regime": (LAND_REGIME_CONTROLLER if _controller_lands
                                       else LAND_REGIME_WORKER),
                       # T-12607 (SPEC-0072 rule 7) — the pair the worker ACTUALLY RUNS ON, not the
                       # pair the tier was asked for. They differ exactly when the primary did not
                       # come up and the tier's RESERVE was launched instead, so a card's effort tier
                       # and the model that did the work can never SILENTLY disagree. `pair` names
                       # which one answered; `primary_model`/`primary_effort` appear ONLY on a switch
                       # (naming the pair that did not come up), so every non-switch row is
                       # byte-identical to before this card. ADDITIVE keys on the EXISTING row — the
                       # `resume_of` (T-12304) / `guard_read_ts` (T-11854) precedent, never a new
                       # event type; a pre-change row's ABSENT `pair` reads as the primary.
                       "model": _launch["model"], "effort": _launch["effort"],
                       "pair": _launch["pair"],
                       **({"primary_model": _launch["primary_model"],
                           "primary_effort": _launch["primary_effort"]}
                          if _launch.get("primary_model") else {}),
                       "source_tier": route["source_tier"], "override": route["override"],
                       # T-11854 — the in-flight guard's own read, dated and classified (see the stamp
                       # above the guard's journal read). Report-only forensic payload: `guard_read_ts`
                       # precedes this row's `ts` by construction (stamped pre-spawn), `guard_cls` /
                       # `guard_launch_cls` are the two axes the guard evaluated, `guard_force` says
                       # whether the X-0131 escape was on. Nothing reads these back.
                       "guard_read_ts": _guard_read_ts, "guard_cls": cls,
                       "guard_launch_cls": _launch_cls,
                       "guard_force": bool(getattr(args, "force", False)),
                       # T-12304 — an ORDINARY bg_dispatch_launched carrying the ts of the
                       # `task_paused(controller-wait)` row this relaunch resumes from (absent on
                       # every non-resume launch, so existing rows are byte-identical). Same row the
                       # brief's contract head was rendered from.
                       **({"resume_of": _cw_release.get("ts")}
                          if (getattr(args, "resume", False) and _cw_release) else {}),
                       # T-12332 — the ENTRY MODE this worker was launched with. Present ONLY on the
                       # paused-card resume arm, so every other row is byte-identical to before. It
                       # is the existing event with one more discriminator key — the `resume_of`
                       # (T-12304) / `guard_read_ts` (T-11854) precedent — never a new event type.
                       **({"mode": _dispatch_mode} if _dispatch_mode else {}),
                       # T-12683 (X-1479) — the cwd holders the in-flight guard classed as ORPHANS of
                       # a terminally-over session (a halted worker's leaked verify server) rather
                       # than as a live holder — the reason this launch was ADMITTED over a held
                       # worktree. Present ONLY on that arm (the `mode` / `resume_of` precedent), so
                       # every other row is byte-identical; the existing event with one more
                       # discriminator key, never a new event type. The adopt's own
                       # `worktree_children_reaped` (T-12451) records what became of them.
                       **({"orphan_holders": {"session_ref": _dead_ref,
                                              "pids": [h["pid"] for h in _orphans],
                                              "basis": "session-terminally-over"}}
                          if _orphans else {})},
                      events_path=main_wt / "events.jsonl")
        # T-11844 — THE ORDERING, and it is the load-bearing half: this fragment is composed ONLY
        # after the `bg_dispatch_launched` append above RETURNS, so a LAUNCHED fragment in the
        # terminal token IMPLIES the journal row exists. Reversed, the token would read identically
        # while the row was missing — the false confirmation this contract exists not to create. If
        # the append raises, control never reaches here and the token carries no fragment for this id.
        outcomes.append((task, "launched", session_id))
        print(f"dispatch: launched {task} | expected session_ref={session_id} | provider={provider} "
              f"| model={_launch['model']} effort={_launch['effort']} (tier={route['source_tier']}"
              f"{', override' if route['override'] else ''}"
              f"{', RESERVE pair' if _launch['pair'] == 'reserve' else ''}) | pid={pid}", flush=True)
        print(f"  worker log: {log_path}", flush=True)
        launched += 1
        # T-13366 (audit-pre fp1:c518abc3288557e1) — a spawn is a wave action: the NEXT id's prefix /
        # guard / redispatch reads must re-read the dispatch union, never this id's snapshot, so a
        # launch another Controller appended meanwhile is seen exactly as the per-task read saw it.
        if _refresh_launch_reads is not None:
            _refresh_launch_reads()
    # T-13366 — the launch phase's reads end here: unwind the request scope BEFORE the self-armed
    # watch below, whose ticks must read the journal live, never this launch's snapshot.
    if _release_launch_reads is not None:
        _release_launch_reads()
    skip_note = f", {skipped} skipped (in-flight)" if skipped else ""
    print(f"  ({launched} launched{skip_note} — thin launcher, no selection/ordering/retry; monitor via "
          f"`yitc-v2 journal query --dispatch-status`)")
    # T-12637 — the §Watcher obligation is DISCHARGED BY THE LAUNCH: when something launched and the
    # caller did not opt out (`--no-self-arm-watch`), this SAME invocation continues into the watch
    # (below, after the launch-phase token), so no separate arming call is left to type or skip. The
    # cue (T-0620) is printed ONLY on the opt-out path, where hand-arming is still the caller's duty.
    # `getattr(..., False)` is the file's fail-closed idiom (`watch_fleet` / `force`): a sparse
    # programmatic namespace does NOT self-arm, so no existing caller can block unexpectedly.
    _self_arm = launched > 0 and bool(getattr(args, "self_arm_watch", False))
    if launched > 0 and not _self_arm:
        print(DISPATCH_WATCHER_CUE)
    # T-11844 — the contracted TERMINAL TOKEN, the FINAL stdout line of a LAUNCH invocation. Same
    # parse-the-TOKEN-not-the-shell-exit shape `land` (`LAND: OK|ABORT`, T-0269) and `dispatch
    # --watch` (`WATCH: …`, T-10347) already carry; this EXTENDS that one contract rather than
    # adding a mechanism. It is a TRANSPORT ACKNOWLEDGEMENT ONLY: the journal
    # (`journal query --dispatch-status`) stays the sole durable discriminator of worker state, and
    # ABSENCE of this line proves NOTHING — equally true of a launcher still running, killed, or of
    # a truncated capture. Nothing in bin/ may parse it back out of a captured log to decide state.
    print(_dispatch_outcome_token(outcomes), flush=True)
    # T-12681 (X-1479) — a LAUNCH invocation that launched NOTHING exits NON-ZERO. Every skip arm
    # above prints its per-id `dispatch: SKIPPED <id> (<reason>: <holder evidence>)` line in the
    # launch-line position, and the token above carries each skipped id as its own
    # `<id>=skipped(reason=…)` fragment composed AFTER its `bg_dispatch_skipped` append returned
    # (the T-11844 ordering) — and before this card the shell exit still read 0, so a caller keying off the exit (or reading only the launch
    # lines) took a wave of pure skips for a launch. Measured: <project> 2026-09-17, the last card of
    # an owner-urgent chain sat pinned by an orphaned verify server for ten hours behind an exit-0
    # skip. The exit is DERIVED from the launch count, nothing else: at least one launch keeps 0
    # (the mixed wave is still a launch, and its skips are still visible per id + in the token);
    # zero launches over a non-empty wave is 1, via the same `_die` every preflight refusal uses —
    # stderr line + SystemExit, so the token stays the FINAL stdout line. No new event type: the
    # guard's journaled `bg_dispatch_skipped` / halted rows are the durable record.
    if outcomes and launched == 0:
        _die(f"dispatch: NOTHING LAUNCHED — every requested id was skipped/refused "
             f"({'; '.join(f'{_t}={_k}' for _t, _k, _e in outcomes)}). This is NOT a launch: read the "
             f"per-id SKIPPED/REFUSED line(s) above for the holder evidence, then "
             f"`yitc-v2 journal query --dispatch-status` (a pinned card needs its holder resolved — "
             f"`worktree adopt`/`worktree park` — or `--force` where the guard names a stale launch).")
    if not _self_arm:
        return
    # T-12637 — SELF-ARM, in this process, over exactly the ids that LAUNCHED (skipped / refused ids
    # have no worker to watch). The invocation now ends on the `WATCH:` token, which is the harness's
    # completion notification: the CLI performs no provider-specific act (CHARTER §P4b, SPEC-0133
    # rule 1 — it never re-invokes the AI), it simply IS the process the harness is already watching.
    launched_ids = [t for t, kind, _e in outcomes if kind == "launched"]
    print(f"dispatch: self-arming the §Watcher over {', '.join(launched_ids)} in THIS process — the "
          f"invocation ends on its `WATCH:` token (T-12637; pass --no-self-arm-watch to arm by hand).",
          flush=True)
    try:
        rc = (_arm_watch or globals()["_arm_watch"])(
            launched_ids, args, main_wt=main_wt, _append_event=_append_event,
            _dispatch_status_events=_dispatch_status_events, _pid_alive=_launch_pid_alive,
            _watch_fleet_rows=_watch_fleet_rows, _watch_status_row=_watch_status_row,
            _watch_premature_findings=_watch_premature_findings,
            _watch_sleep=_watch_sleep, _watch_now=_watch_now)
    except SystemExit:
        raise
    except Exception as _exc:                    # noqa: BLE001 — AC3: an arming that did NOT happen is LOUD
        # NOT T-12622/T-12641's signal (an arming that HAPPENED but cannot reach the Controller — a
        # MODE read). This is an arming that did not happen at all: the workers are running and
        # NOBODY is watching them, which the caller must read where it reads the launch.
        print(f"dispatch: WATCHER NOT ARMED — the self-arming over {', '.join(launched_ids)} raised "
              f"{_exc!r}. The workers LAUNCHED and are UNWATCHED: arm by hand NOW with "
              f"`bin/yitc-v2 dispatch --watch {' '.join('--task ' + t for t in launched_ids)}` "
              f"(T-12637 AC3).", file=sys.stderr, flush=True)
        raise SystemExit(2)
    raise SystemExit(rc)
