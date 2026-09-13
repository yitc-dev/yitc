"""The remote verify EXECUTOR — SPEC-0203 rules 3-4 (T-12194).

WHAT THIS IS. The callable API that ships two trees to a published venue box, runs the SHIPPED
TREE'S OWN runner for both SPEC-0077 legs in parallel, brings back a bound ENVELOPE, and validates
it the way `land` does. It is the ONE executor (SPEC-0203 rule 7): there is no second runner, no
second verdict authority, no remote queue and no remote result store — the box RUNS, the local
journal remains the sole durable verdict record (CHARTER §P5).

WHO CALLS IT (corrected T-12425; the paragraph this replaces described the T-12194 card's own
boundary — "this module has NO CALL SITE … `task test --run` does not read it" — which T-12199 wired
and T-12221 extended to Stage 6, so it had been false for two cards). There are exactly TWO callers
and both reach the box THROUGH `route`, never through the executor directly: `land`
(`bin/lib/worktree.py`, kind `"land"`) and Stage 6 (`bin/lib/task.py` `cmd_task_test`, kind
`STAGE6_KIND`). The venue verbs (`venue raise|publish|unpublish|delete`) stay T-12197's.

AND THE TWO CALLERS SHIP DIFFERENT SUBJECTS, which is the one place `kind` changes behaviour rather
than merely naming the caller in the envelope: `land` verifies the merged candidate COMMIT (`HEAD`),
while a Stage-6 pass — which by lifecycle order runs BEFORE Commit — verifies a temporary SNAPSHOT
COMMIT of the WORKING TREE (`working_tree_snapshot`), because the change under test is on disk and
in no commit yet.

THE PUBLIC API, fixed here (T-12195 adds `derive_remote_w`, T-12196 adds `local_probe_set` and
T-12199 adds `route` BEHIND this surface; none of them re-words what is below):

    ship_trees(repo_root, box, ref=..., request=...) -> the SHIPPED identity + the push wall
    box_run_dir(request, attempt) / box_ref(...)   -> THE one spelling of a pass's box-side
                                                     run dir and its transport refs (T-12247)
    expected_pinned_tree(repo_root, cand_tree)     -> the pinned leg's expected working-tree sha
    local_runner_digest(repo_root, ref)            -> the `bin/` digest `land` computes locally
    probe_fingerprint(box)                         -> the environment fingerprint (incl. /dev/shm)
    box_leg_script(...)                            -> the per-leg driver TEXT
    envelope_script(...)                           -> the box-side atomic envelope assembler TEXT
    run_legs(box, shipped, ...)                    -> both legs in parallel; the raw run record
    validate_envelope(text, ...)                   -> the checks `land` applies + a three-valued outcome
    envelope_failing_files(envelope)               -> the per-leg failing list (rule-8 input)
    local_probe_set(test_dir)                      -> the RECORDED host-sensitive names (rule 8)
    partition_suite(discovered, ...)               -> the remote pass + the narrow local leg
    execute_remote_verify(...)                     -> THE entry: ship -> run -> fetch -> validate

THREE PROPERTIES THAT ARE LOAD-BEARING, each a measured trial finding rather than a design taste:

  * IDENTITY IS THE TREE THAT RAN, NOT THE TREE THAT WAS CHECKED OUT (trial cycle 8). Each leg's
    digest is `git write-tree` over its WORKING TREE at run start (a temporary index over `add -A`),
    and it must EQUAL what was shipped. `rev-parse HEAD^{tree}` names what was checked out and stays
    silent when a file is altered afterwards — measured: a corrupted `verify_runner.py` passed every
    envelope check and read as an ordinary FAILED.

  * NO SOURCE PATCH TOUCHES THE BOX-SIDE TREE. The trial `sed`-patched `_VERIFY_WORKER_CEILING` to
    reach W=24 and injected a per-file dump into `verify_runner.py`. Both are RETIRED here (CHARTER
    §P1 F3): `_run_verify_tests` already honours an EXPLICIT `workers=` (its governor runs only when
    `workers is None`), and T-12190 already exports the complete per-file outcome sidecar to
    `YITC_VERIFY_OUTCOMES_DIR`. Retiring the patches is not tidiness — a patched tree is why the
    trial's runner digest could never equal the local one, which is the check SPEC-0203 rule 4 asks
    for in production ("no harness patches in production").

  * A FAULT IS INDETERMINATE, NEVER GREEN AND NEVER A TEST FAILURE. Every outcome is one of GREEN /
    FAILED(files) / INDETERMINATE(class). Nothing in this module raises into a verdict: a dropped
    connection, a truncated envelope, a digest or fingerprint mismatch, a stale or duplicate reply
    and an unreachable venue each return INDETERMINATE with their OWN named class, which `land`
    turns into `abort_class: venue-indeterminate` (rule 4) — never a rebaseline-waive candidate and
    never an audit-loop pass.
"""
from __future__ import annotations

import functools
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

# ── the envelope schema + the outcome vocabulary (SPEC-0203 rule 4) ──────────────────────────────

ENVELOPE_SCHEMA = "yitc.remote-verify.envelope/1"

OUTCOME_GREEN = "GREEN"
OUTCOME_FAILED = "FAILED"
OUTCOME_INDETERMINATE = "INDETERMINATE"

#: The seven named INDETERMINATE classes rule 4 enumerates. This tuple is the CLOSED set: a fault that
#: matches none of the others is `venue-fault`, which is why it is last — there is deliberately
#: no "unknown" class, because an unnamed fault would be indistinguishable from a bug in the reader.
#: The seventh, `venue-refs-clobbered` (T-12262), is the box's SHARED refs having moved during a leg's
#: suite: it is named separately rather than folded into `venue-fault` because it is the ONE class
#: whose remedy the box has already applied (the leg restores `refs/heads/main` from this request's
#: own main ref before returning it), which is what makes the single automatic re-attempt in
#: `execute_remote_verify` sound. A seventh class is a SPEC change, made with it — SPEC-0203 rule 4.
INDETERMINATE_CLASSES = ("disconnect", "truncated", "digest-mismatch",
                         "duplicate-or-stale", "binding", "venue-refs-clobbered", "venue-fault")


#: The remote worker FALLBACK — no longer the width itself (T-12195). `derive_remote_w` computes the
#: rule-5 width `clamp(per-file sum / longest file, 1, cores // legs)` per pass, and this constant is
#: what stands in for the CAP when the fingerprint does not state the box's core count. Its VALUE is
#: unchanged and deliberately so: 24 is the trial's measured knee at 48 cores / 2 legs
#: (16/20/24/28 -> 270/243/224/220 s over two sweeps), so an unmeasurable box gets the width a
#: measured one of the venue's own class got, rather than an invented number or an unbounded one.
REMOTE_VERIFY_WORKERS = 24


def remote_verify_workers() -> int:
    """T-12219 — the remote verify WIDTH baseline, machine file first, `REMOTE_VERIFY_WORKERS`
    otherwise.

    The OVERRIDE over this value — the env knob named by `REMOTE_WORKERS_ENV`, read in exactly one
    place by `remote_workers_override` below (its own AC3 asserts that literal name appears in this
    file ONCE, which is why this sentence names the CONSTANT and not the string) — has been
    performance-registered since T-12195, so a machine could already LOWER the derived width but
    could not raise its own baseline; this registers the other half of that pair. Parallelism
    changes how fast the suite finishes, never which files it runs or how they conclude — the same
    reading the override row already carries. Resolved per call, never at import, so a default argument can observe a
    `config set` (a module-level default is bound once, at import, and never again)."""
    try:
        from lib import machine_settings      # deferred: keeps the hot import graph unchanged
        return int(machine_settings.resolve("lib.remote_verify.REMOTE_VERIFY_WORKERS",
                                            REMOTE_VERIFY_WORKERS))
    except Exception:            # noqa: BLE001 — the settings STACK is never a
                                 # prerequisite either (SPEC-0193 rule 6 — the
                                 # `remote_workers_override` precedent)
        return REMOTE_VERIFY_WORKERS


#: THE ONE name `YITC_VERIFY_WORKERS` is read under (rule 5 / AC3). It was declared in
#: `bin/lib/machine_settings.py` naming a read site in `bin/lib/worktree.py` that never existed —
#: the card that was to build it, T-11436, is `wont-do` — so it read NOWHERE (T-12183 F2). Rule 5
#: offers read-or-retire and this is the READ: it caps the DERIVED REMOTE width and nothing else.
#: It never reads on the local path, where the width stays the constant `_VERIFY_WORKER_CEILING`;
#: a second LOCAL knob would make the shared host's width machine-dependent, which is exactly what
#: rule 5 forbids.
REMOTE_WORKERS_ENV = "YITC_VERIFY_WORKERS"

#: The MACHINE-WIDE request cap's env name (SPEC-0203 rule 4, T-12241). Named beside
#: `REMOTE_WORKERS_ENV` because the two are the venue's only operator-facing tunables and a reader
#: looking for one will look for the other here.
VENUE_MAX_REQUESTS_ENV = "YITC_VENUE_MAX_REQUESTS"

#: The BUILT-IN cap behind `VENUE_MAX_REQUESTS_ENV`, and the value EVERY malformed override falls
#: back to. 1 is the owner's standing shape (directive 2026-09-07T14:46:36Z): serialize verify
#: across the machine rather than shrink the per-leg width.
VENUE_MAX_REQUESTS_DEFAULT = 1

#: The admissible band, declared at BOTH doors (here and as the registry row's `bounds`) so
#: `config set` refuses exactly what this resolver would ignore — the `YITC_VERIFY_WORKER_NICE`
#: shape (T-12261). The FLOOR is 1 because 0 would not serialize verify harder, it would admit
#: nothing at all, and `machine_settings.coerce` refuses any numeric knob <= 0 anyway — so a floor
#: below 1 would make the setter and this resolver disagree about one knob. The CEILING is 4 because
#: the unit is the REQUEST and one land is two legs: at 4 concurrent requests the box is already
#: carrying up to 8 full-width verify legs, which oversubscribes every box class this venue is
#: raised on, and the owner's standing shape for this knob is the opposite direction entirely
#: (serialize at 1 rather than shrink the per-leg width — directive 2026-09-07T14:46:36Z). A number
#: above 4 is therefore a typo rather than a policy. This bounds the LAND cap only: Stage-6
#: concurrency is `VENUE_STAGE6_MAX_CONCURRENT_RANGE`, whose own ceiling is 16 because those passes
#: run at a fraction of the width and at nice 19.
VENUE_MAX_REQUESTS_RANGE = (1, 4)

#: The two legs, in the order they are started and reported. Not configurable: SPEC-0077 defines
#: exactly these two, and a third would be a different spec.
LEGS = ("cand", "pinned")

#: The fd limit the venue contract PINS (rule 5). At the 1024 default the SPEC-0132 fd dimension
#: silently capped W at 9 (T-12183 F1) — a slow pass that looks like a slow suite.
VENUE_NOFILE = 1048576

#: The tmpfs root every remote leg runs its temp state under (owner directive 2026-09-06, the
#: T-12185 `YITC_VERIFY_TMPDIR` lever — measured -5..-18% wall on the engine host). On a ccx63 the
#: default `/dev/shm` is ~96 GB against a ~1.7 GB peak per leg. FAIL-SAFE BY CONSTRUCTION, and that
#: is the whole reason it is safe to export unconditionally: `_install_verify_tmpdir` falls back to
#: the platform default with one reported line when the root is absent or unwritable. It is a
#: performance lever, never a gate.
VENUE_TMPDIR_ROOT = "/dev/shm/yitc-verify"

#: Where the venue's persistent bare clone lives on the box (rule 3 — SEEDED ONCE into the snapshot;
#: a bare image is for seeding only, never for a pass).
BOX_VENUE_DIR = "~/venue"
BOX_REPO_GIT = "~/venue/repo.git"

#: Everything a PASS owns lives under its own REQUEST-and-ATTEMPT path (SPEC-0203 rule 4, T-12220):
#: the lease, the leg checkouts, their outputs, the shipped per-pass inputs and the envelope. Before
#: T-12220 the lease was keyed by LEG NAME alone (`~/venue/lease-cand`) and the leg worktree was ONE
#: shared path (`~/venue/cand`), so a second `cand` start killed the first run's process group and
#: `reset --hard`ed its checkout — measured on the live box (T-12199: the overlapped land produced no
#: candidate `leg.json` at all, INDETERMINATE class `digest-mismatch`).
BOX_RUNS_DIR = "~/venue/runs"
BOX_LEASES_DIR = "~/venue/leases"


def box_run_dir(request: str, attempt: int = 1, *, runs_dir: str = BOX_RUNS_DIR) -> str:
    """THE one spelling of a pass's box-side home. Every producer of a box-side path — the leg
    template, the envelope assembler, the shipper, the cleanup — derives from here, so the writing
    side and the reading side cannot drift into two spellings of the same directory."""
    return f"{runs_dir}/{request}-{int(attempt)}"


#: The request-keyed TRANSPORT ref namespace (T-12247). Before this card `ship_trees` force-pushed the
#: candidate to ONE shared `refs/venue/cand` and `main` to `refs/heads/main`, then read `refs/venue/cand`
#: back — so of two overlapping requests the LOSER read the WINNER's tree, `transport_cand_tree` failed
#: and the pass returned INDETERMINATE `digest-mismatch` with no envelope and no run (4 land aborts + 2
#: Stage-6 faults, 2026-09-08 01:00-02:30Z; reproduced 3/3 with two concurrent `ship_trees`, sequential
#: 2/2 clean). T-12220 keyed the run dirs and leases; the refs were the residual, and this is it.
BOX_REFS_NS = "refs/venue"

#: What a `<request>-<attempt>` key may be, so it is a legal git ref path component. Checked, NEVER
#: rewritten — see `box_ref`.
_REF_KEY_OK = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._-]*\Z")


def box_ref(request: str, attempt: int = 1, name: str = "cand", *, ns: str = BOX_REFS_NS) -> str:
    """THE one spelling of a pass's box-side TRANSPORT ref — the sibling of `box_run_dir`, same shape and
    same reason: the shipper, the leg template, the envelope assembler and the cleanup all derive from
    here, so the writing side and the reading side cannot drift into two spellings of one ref.

    IT VALIDATES RATHER THAN SANITIZES, and that is the load-bearing choice. The box side spells this ref
    in SHELL, from its own `$REQ`/`$ATT` argv (`refs/venue/$REQ-$ATT/<name>`); a Python-side rewrite of an
    awkward identity would hand the two sides two DIFFERENT refs for one pass — a silent
    checkout-of-nothing rather than a loud refusal. So an identity that cannot be a ref is REFUSED here,
    at the shipper, before anything is pushed."""
    # The `-<attempt>` suffix is part of the key, so a trailing `.` / `.lock` cannot occur here and
    # is not guarded against — an unreachable branch reads as a check that has been thought about.
    key = f"{request}-{int(attempt)}"
    if not _REF_KEY_OK.match(key) or ".." in key:
        raise RemoteVerifyError(
            f"the request identity {request!r} (attempt {attempt}) cannot name a git ref: the box side "
            f"spells this ref from its own $REQ-$ATT argv, so an identity this side would have to rewrite "
            f"would give the two sides different refs for one pass")
    return f"{ns}/{key}/{name}"


SSH_OPTS = ("-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null",
            "-o", "LogLevel=ERROR", "-o", "ConnectTimeout=15", "-o", "ServerAliveInterval=20")


class RemoteVerifyError(RuntimeError):
    """Raised only by the TRANSPORT helpers when they are called directly (a caller that wants the
    exception). `execute_remote_verify` never lets one escape — it converts every failure into an
    INDETERMINATE outcome, because a verdict path that can raise is a verdict path that can turn an
    infrastructure fault into a traceback the caller reads as "no result" rather than as a class."""


# ── the W policy (SPEC-0203 rule 5) ──────────────────────────────────────────────────────────────

_UNSET = object()


def remote_workers_override() -> "int | None":
    """The operator's OVERRIDE CEILING on the derived remote width, or None when there is none.

    THE ONE READ SITE of `REMOTE_WORKERS_ENV` (AC3). Precedence is copied wholesale from the shipped
    analog `verify_runner._verify_heartbeat_interval` rather than invented: the environment first,
    then the machine-scoped settings file, then nothing. Reusing that shape is the point — the
    settings file is a PERFORMANCE-class layer, so a width set there can never travel into a verdict,
    and `machine_settings.get_value` itself returns None for anything not performance-class, so this
    site cannot become a door for a gate-class value even by mistake.

    FAIL-SAFE DIRECTION IS THE LOAD-BEARING PART, and it is the same direction the timeout hatch
    chose: a blank, non-numeric, or non-positive value is IGNORED (None), never honoured. An override
    may only ever LOWER the derived width — it can neither unbound it nor set it to zero, because a
    malformed override that disabled the width would convert a tuning knob into an outage."""
    raw = os.environ.get(REMOTE_WORKERS_ENV)
    if raw is None or not str(raw).strip():
        try:
            from lib import machine_settings          # deferred: keeps the hot import graph unchanged
            raw = machine_settings.get_value(REMOTE_WORKERS_ENV)
        except Exception:
            # The settings file is an OVERRIDE LAYER and never a prerequisite — its own module says
            # so, and `_raw_load` already returns nothing for a missing or malformed file. This
            # catch extends that same reading one level out, to the settings STACK itself: a width
            # that could raise would put an infrastructure fault on the verdict path, which is the
            # one thing `execute_remote_verify` exists to prevent.
            raw = None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def venue_max_requests() -> int:
    """The MACHINE-WIDE cap on concurrent verify REQUESTS admitted to the box (SPEC-0203 rule 4).

    THE ONE READ SITE of `VENUE_MAX_REQUESTS_ENV`, and the registry row's `read_site` anchor points
    here. Precedence is copied wholesale from the sibling `remote_workers_override` — the
    environment first, then the machine-scoped settings file, then the built-in — including the
    deferred import and the broad `except` around the settings STACK: a cap that could RAISE would
    put an infrastructure fault on the path a verify pass starts from, which is the one thing the
    executor exists to prevent.

    THE FAIL-SAFE DIRECTION IS INVERTED RELATIVE TO ITS SIBLING, AND THAT INVERSION IS THE WHOLE
    POINT. `remote_workers_override` IGNORES a malformed value (returns None) because there a bad
    value must not UNBOUND the width. Here the same reasoning points the other way: this value is a
    BOUND, so ignoring a malformed one would REMOVE the bound. A blank, non-numeric, non-positive or
    OUT-OF-BAND override therefore resolves to `VENUE_MAX_REQUESTS_DEFAULT` (1) — a malformed value
    can never disable the cap, only ever leave it at its most conservative setting.

    THE OUT-OF-BAND ARM IS T-12261's ADDITION and it is the only behaviour this card moves: before
    it, a value above `VENUE_MAX_REQUESTS_RANGE`'s ceiling was honoured, so the setter could refuse a
    number the environment layer would happily apply. It is the same both-doors rule the Stage-6
    knobs already carry, and it resolves in this function's OWN declared direction — toward the most
    conservative cap, never away from it. Nothing at the DEFAULT moves: an unset machine reads 1
    exactly as before, so the T-12292 by-class admission asks its question against the same number.

    THE UNIT IS THE REQUEST, NEVER THE LEG. One land ships cand + pinned = 2 leases; both legs of
    one request are admitted together and never wait on each other. The counting that enforces this
    lives box-side in `_BOX_LEASE_PROLOGUE`, which is where the lease records are; this function
    only resolves the NUMBER.
    """
    raw = os.environ.get(VENUE_MAX_REQUESTS_ENV)
    if raw is None or not str(raw).strip():
        try:
            from lib import machine_settings          # deferred: keeps the hot import graph unchanged
            raw = machine_settings.get_value(VENUE_MAX_REQUESTS_ENV)
        except Exception:
            raw = None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return VENUE_MAX_REQUESTS_DEFAULT
    lo, hi = VENUE_MAX_REQUESTS_RANGE
    return value if lo <= value <= hi else VENUE_MAX_REQUESTS_DEFAULT


def fingerprint_admits_pin(fingerprint: "dict | None") -> bool:
    """Does this environment fingerprint show an fd limit at or above the venue's pin (rule 5)?

    ONE HOME for the predicate, because it is applied at two different moments to the same fact: the
    envelope check below reads the fingerprint the box measured while it RAN, and `venue publish`
    (T-12197) reads the one the readiness probe measured BEFORE the box is trusted. Two copies of a
    threshold comparison are two things that drift apart, and the failure mode of drift here is
    silent: at the 1024 default the SPEC-0132 fd dimension capped W at 9 and the only symptom was a
    slow pass that looked like a slow suite (T-12183 F1).

    FAIL-CLOSED ON SILENCE. A fingerprint that does not STATE its nofile does not admit the pin. The
    absent value is not evidence of a high limit — it is the absence of evidence, and the whole
    reason this pin exists is that an unverified fd limit is indistinguishable from a met one until
    the suite is already running slowly. `nofile_hard` defaults to the soft limit when unstated,
    since a soft limit can never exceed its own hard limit."""
    fp = fingerprint or {}
    try:
        soft = int(fp.get("nofile_soft") or 0)
        hard = int(fp.get("nofile_hard") or soft)
    except (TypeError, ValueError):
        return False
    return soft >= VENUE_NOFILE and hard >= VENUE_NOFILE


def derive_remote_w(fingerprint: "dict | None", durations: "dict | None", *,
                    legs: "int | None" = None, override=_UNSET,
                    fallback: "int | None" = None) -> dict:
    """Rule 5's remote width, derived per pass: `clamp(per-file sum / longest file, 1, cores//legs)`.

    PURE apart from its two RESOLVED inputs — `override` and, since T-12219, `fallback`, each of
    which reads the env/machine-settings layer once and can be passed explicitly instead. That is
    why the whole policy stays provable by a unit test over a synthetic fingerprint and a recorded
    table rather than only against a raised box: a test that passes both reaches no I/O at all.

    WHY THE RATIO IS THE RIGHT NUMERATOR. `sum / longest` is the smallest worker count at which the
    single longest file is no longer the makespan's floor — add workers past it and the suite still
    cannot finish before that one file does. It therefore tracks the suite's SHAPE and moves as files
    are born or shortened, where a pinned width goes stale silently. Measured against this repo's
    table it gives 29, and the cap binds first; measured against a suite with one 191 s+ file it
    would give less than the cap, and the derivation would follow.

    WHY THE CAP IS `cores // legs`. Both SPEC-0077 legs run concurrently on the box, so a per-leg
    width above half the cores oversubscribes it. The trial confirms the arithmetic is not merely
    theoretical: on 48 cores / 2 legs the cap is 24, and 24 -> 28 workers bought 4 seconds out of
    224 (the curve is flat past the cap, so exceeding it trades contention for nothing).

    RETURNS THE DERIVATION, NOT JUST THE NUMBER. `workers` is the answer; `sum_s` / `longest_s` /
    `ratio` / `cap` / `cores` / `override` / `bound` are what makes the answer READABLE — `bound`
    naming which of ratio, cap or override actually decided it. A width nobody can explain is a width
    nobody can tune, and this record is what the journal row and a land tail carry."""
    legs = max(1, int(legs or len(LEGS)))
    try:
        cores = int((fingerprint or {}).get("cores") or 0)
    except (TypeError, ValueError):
        cores = 0
    walls = []
    for v in (durations or {}).values():
        try:
            v = int(v)
        except (TypeError, ValueError):
            continue
        if v > 0:
            walls.append(v)
    total_ms, longest_ms = sum(walls), (max(walls) if walls else 0)

    if override is _UNSET:
        override = remote_workers_override()
    if fallback is None:                        # T-12219 — resolved HERE, never as a module-level
        fallback = remote_verify_workers()      # default: an import-time default never sees a later
                                                # `config set` (SPEC-0193 rule 7 read-site shape)

    # An unmeasurable suite takes the fallback rather than an invented ratio; an unmeasurable box
    # takes the fallback as its CAP. Both are the same fail-safe reading: without a measurement, use
    # the width a measured box of this class actually ran at.
    ratio = (total_ms // longest_ms) if longest_ms > 0 else int(fallback)
    cap = (cores // legs) if cores > 0 else int(fallback)
    cap = max(1, cap)

    workers, bound = max(1, int(ratio)), "ratio"
    if cap < workers:
        workers, bound = cap, "cap"
    if override is not None and int(override) < workers:
        workers, bound = max(1, int(override)), "override"
    return {"workers": workers, "bound": bound,
            "ratio": int(ratio), "cap": cap, "cores": cores, "legs": legs,
            "override": (None if override is None else int(override)),
            "sum_s": round(total_ms / 1000.0, 1), "longest_s": round(longest_ms / 1000.0, 1),
            "files": len(walls), "table": bool(walls)}


def remote_duration_table(repo_root) -> dict:
    """The repo's recorded per-file duration table as `{file: wall_ms}` — the input `derive_remote_w`
    schedules against.

    IT DELEGATES; it does not parse. `verify_runner._load_verify_duration_table` is the single reader
    of that artifact (its unit quantisation, its fail-soft on a malformed table, its silent empty on
    an absent one), and a second parser here would be a second answer to "how long does this suite
    take" — exactly the parallel path CHARTER §P5 forbids. It NEVER RAISES: an unreadable table is a
    scheduling question, and `derive_remote_w` already has a documented answer for an empty one."""
    try:
        try:
            from lib import verify_runner
        except ImportError:                           # direct `bin/lib` import (the tests' path shape)
            import verify_runner                      # type: ignore[no-redef]
        return verify_runner._load_verify_duration_table(
            Path(repo_root) / "tests", _VERIFY_DURATIONS_FILE="verify-durations.json") or {}
    except Exception:
        return {}


# ── local-side identity: what `land` shipped, computed the way `land` computes it ────────────────

def _git(repo_root, *args, check=True):
    r = subprocess.run(["git", *args], cwd=str(repo_root), text=True, capture_output=True)
    if check and r.returncode != 0:
        raise RemoteVerifyError(f"git {' '.join(args)} failed: {r.stderr.strip()[:200]}")
    return r.stdout


def expected_pinned_tree(repo_root, cand_tree: str, *, main_ref: str = "main") -> str:
    """The pinned leg's EXPECTED working-tree sha, computed LOCALLY — the pinned identity's other half.

    The box materialises the pinned leg as the candidate checkout with `git checkout main -- tests/`
    overlaid (the `_run_pinned_verify` shape). That is an OVERLAY, not a replacement: a `tests/` file
    that exists in the candidate and not in `main` SURVIVES it. So the expected tree is the candidate
    tree with every `main:tests` blob written over it — reproduced here through a temporary index
    (`read-tree` the candidate, then feed `ls-tree -r main:tests` re-prefixed to `update-index
    --index-info`, then `write-tree`), which is exactly that overlay and nothing else.

    Why compute it at all, when the trial only checked the pinned leg's digest was PRESENT: a
    presence check cannot fail. With the expected sha in hand the pinned leg gets the same REAL
    equality the candidate leg has, and post-checkout corruption of a pinned-only file — the exact
    fault cycle 8 found invisible — is caught on that leg too."""
    repo_root = Path(repo_root)
    main_tests = _git(repo_root, "rev-parse", f"{main_ref}:tests").strip()
    with tempfile.TemporaryDirectory(prefix="yitc-pinned-idx-") as td:
        idx = os.path.join(td, "index")
        env = {**os.environ, "GIT_INDEX_FILE": idx}
        subprocess.run(["git", "read-tree", cand_tree], cwd=str(repo_root), env=env, check=True,
                       capture_output=True)
        listing = subprocess.run(["git", "ls-tree", "-r", main_tests], cwd=str(repo_root),
                                 text=True, capture_output=True, check=True).stdout
        # `ls-tree -r` yields "<mode> <type> <sha>\t<path>" relative to the tests/ tree; re-prefix the
        # path so the entries land where the overlay puts them. `update-index --index-info` accepts
        # this exact format, so no line is re-assembled by hand.
        prefixed = "".join(f"{line.split(chr(9), 1)[0]}\ttests/{line.split(chr(9), 1)[1]}\n"
                           for line in listing.splitlines() if chr(9) in line)
        subprocess.run(["git", "update-index", "--index-info"], cwd=str(repo_root), env=env,
                       input=prefixed, text=True, check=True, capture_output=True)
        out = subprocess.run(["git", "write-tree"], cwd=str(repo_root), env=env, text=True,
                             capture_output=True, check=True).stdout
    return out.strip()


def local_runner_digest(repo_root, ref: str = "HEAD") -> str:
    """The digest of the `bin/` tree AT `ref` — what `land` computes locally for the runner-identity
    check (rule 4: "equal to the digest `land` computes locally from the same ref").

    It is git's own tree sha for `bin/`, not a hash of the working copy: the working copy may carry
    uncommitted dirt that never ships, and comparing a dirty local hash against a clean remote one
    would fail every honest run. The box computes the same value from its checkout of the same ref,
    so the two are comparable by construction."""
    return _git(Path(repo_root), "rev-parse", f"{ref}:bin").strip()


def working_tree_snapshot(repo_root) -> "str | None":
    """The Stage-6 ref: a TEMPORARY SNAPSHOT COMMIT of the WORKING TREE, or `None` when the tree is
    proven clean (T-12425).

    WHY IT EXISTS. Stage 6 (Tests) runs BEFORE Stage 7 (Commit), so a worker's diff is on disk and
    NOT in any commit when `task test --run` routes to the venue. Shipping `HEAD` therefore asks the
    box about a tree WITHOUT the change under test, and the verdict is false in BOTH directions —
    measured 2026-09-11: T-12420 false-RED on exactly 3 derived-artifact tests that pass 15/15 in its
    working tree, and false-GREEN 1516/1516 on a HEAD that did not carry its code; T-12396 RED twice
    on a stale HEAD and GREEN the moment its fix was committed. Only the rule-8 local probe leg
    (~15 host-sensitive files) ever saw the working tree, which is why the pass looked healthy.

    THE IDENTITY NOTION IS THE BOX'S OWN, REUSED — NOT A NEW ONE. Each leg's digest is already
    `git write-tree` over its working tree through a temporary index over `add -A` (the load-bearing
    property at the top of this module), so composing the shipped ref the SAME way makes the
    transport's `box_cand_tree == cand_tree` check pass by construction rather than by arrangement.

    IT TOUCHES NOTHING. The index is a throwaway file OUTSIDE the worktree (`GIT_INDEX_FILE`), so the
    real index, HEAD, the branch and the reflog are never written; the returned commit is UNREACHABLE
    and reaches the box only as the push SOURCE of this request's own transport ref, exactly as a
    committed sha does today. `read-tree HEAD` seeds the temp index first so a TRACKED-but-ignored
    path keeps its tracked identity — `add -A` against an empty index would read it as untracked and
    drop it, silently shipping a tree the worker never had.

    FAIL-LOUD, NEVER FAIL-BACK-TO-HEAD (audit-pre finding 1). Any git step failing RAISES: falling
    back to HEAD would REINSTATE the exact defect this function removes, and do it invisibly, which
    is strictly worse than the bug. `None` means one thing only — the working tree is PROVEN equal to
    `HEAD^{tree}`, so today's ref is already the right one and no snapshot commit is minted.
    `route` maps the raise onto the INDETERMINATE outcome rule 7 already defines."""
    repo_root = Path(repo_root)
    head_tree = _git(repo_root, "rev-parse", "HEAD^{tree}").strip()
    with tempfile.TemporaryDirectory(prefix="yitc-venue-snap-") as td:
        env = {**os.environ, "GIT_INDEX_FILE": str(Path(td) / "index")}

        def _snap_git(*args: str) -> str:
            r = subprocess.run(["git", *args], cwd=str(repo_root), text=True,
                               capture_output=True, env=env)
            if r.returncode != 0:
                raise RemoteVerifyError(
                    f"the Stage-6 working-tree snapshot failed at `git {' '.join(args)}` "
                    f"(rc={r.returncode}): {(r.stderr or r.stdout).strip()[:300]}")
            return r.stdout

        _snap_git("read-tree", "HEAD")
        _snap_git("add", "-A")
        tree = _snap_git("write-tree").strip()
        if tree == head_tree:
            return None
        return _snap_git("commit-tree", tree, "-p", "HEAD", "-m",
                         "venue stage-6 working-tree snapshot (T-12425)").strip()


def shipped_identity(repo_root, ref: str = "HEAD", *, main_ref: str = "main") -> dict:
    """The identity `land` ships and the envelope must reproduce — computed BEFORE any transport, so
    a transport fault can never quietly redefine what was asked about."""
    repo_root = Path(repo_root)
    cand_sha = _git(repo_root, "rev-parse", ref).strip()
    shipped_main_sha = _git(repo_root, "rev-parse", main_ref).strip()
    cand_tree = _git(repo_root, "rev-parse", f"{ref}^{{tree}}").strip()
    main_tests_tree = _git(repo_root, "rev-parse", f"{main_ref}:tests").strip()
    return {"ref": ref, "cand_sha": cand_sha, "shipped_main_sha": shipped_main_sha,
            "cand_tree": cand_tree, "main_tests_tree": main_tests_tree,
            "pinned_tree": expected_pinned_tree(repo_root, cand_tree, main_ref=main_ref),
            "runner_digest": local_runner_digest(repo_root, ref)}


# ── transport (rule 3): git push into the seeded clone ───────────────────────────────────────────

def ssh_argv(box: str, command: str, *, user: str = "dev") -> list:
    return ["ssh", *SSH_OPTS, f"{user}@{box}", command]


def _ssh(box: str, command: str, *, user: str = "dev", timeout: float = 120, check: bool = True):
    r = subprocess.run(ssh_argv(box, command, user=user), text=True, capture_output=True,
                       timeout=timeout)
    if check and r.returncode != 0:
        raise RemoteVerifyError(f"ssh failed (rc={r.returncode}): {(r.stderr or r.stdout)[:300]}")
    return r


#: The clone's own `main` BRANCH — the MIRROR of the host's main, not a transport ref (T-12296).
#: Named rather than spelled inline because two places must agree it is a mirror and neither may
#: mistake it for one of the request-keyed transport refs `box_ref` spells.
MIRROR_MAIN_REF = "refs/heads/main"


def mirror_ancestry_verdict(box: str, shipped: str, seen: "str | None", *,
                            user: str = "dev") -> str:
    """NAME the relation between the shipped main and what the box clone's mirror holds (T-12364).

    Read on the mirror postcondition's REFUSAL path only, and it returns a SENTENCE rather than a
    bare token because the token alone is the thing that was missing: an operator reading
    `venue-fault` off an abort row could not tell an ORPHANED mirror (the two histories have
    diverged, so no fast-forward can ever reach it — the 2026-09-10 cause) from a merely UNWRITABLE
    one (the clone is simply behind and the push should have fast-forwarded). Those want opposite
    remedies, and telling them apart cost an ssh to the box and a hand comparison of refs.

    BOTH DIRECTIONS ARE ASKED, and that is the correction the audit-pre made: the fast-forward the
    push attempted is rejected when the CLONE's main is not an ancestor of the shipped sha, while
    the postcondition's own success arm asks whether the SHIPPED sha is an ancestor of the clone's.
    Reporting one direction and calling it "the ancestry" misidentifies the rejected relationship,
    so the verdict is derived from the pair and the sentence SAYS which way each was tested.

    FAIL-SOFT, DELIBERATELY: this runs inside the composition of an error that is already being
    raised, so a probe that itself fails reports `indeterminate` and never replaces a real fault
    with a probing one — and "fails" INCLUDES a probe that merely did not answer, which is why the
    ancestry reads are three-valued below rather than boolean. It is report-only in the strongest
    sense: nothing reads this to decide anything."""
    if not seen:
        return "the venue clone holds no main at all (the mirror ref is absent)"
    def _is_ancestor(a: str, b: str) -> "bool | None":
        """`git merge-base --is-ancestor` is THREE-VALUED, and reading it as a boolean is how a
        probe FAILURE becomes a false claim (audit-post finding 2): 0 is "is an ancestor", 1 is
        "is not", and ANYTHING ELSE — 128 for an object the clone does not have, a non-zero ssh
        transport rc — is "the question was not answered". Collapsing the third onto `False` makes
        two unanswered probes read as `diverged`, which is precisely the specific, actionable
        verdict this helper exists to distinguish. `None` is that third value, and it wins."""
        rc = _ssh(box, f"cd {BOX_REPO_GIT} && git merge-base --is-ancestor {a} {b}",
                  user=user, timeout=120, check=False).returncode
        return True if rc == 0 else (False if rc == 1 else None)

    try:
        clone_is_ancestor = _is_ancestor(seen, shipped)
        shipped_is_ancestor = _is_ancestor(shipped, seen)
    except Exception as e:                              # noqa: BLE001 — mapped, never swallowed
        return f"indeterminate — the ancestry probe itself failed ({type(e).__name__}: {e})"
    if clone_is_ancestor is None or shipped_is_ancestor is None:
        return ("indeterminate — `git merge-base --is-ancestor` did not answer on the box (a "
                "commit the clone does not hold, or a transport fault), so the relation between "
                "the shipped main and the clone's is UNKNOWN, not diverged")
    if clone_is_ancestor:
        return ("clone-behind — the clone's main IS an ancestor of the shipped main, so the "
                "fast-forward mirror push should have advanced it; the mirror is unwritable "
                "rather than diverged")
    if shipped_is_ancestor:
        return ("clone-ahead — the shipped main IS an ancestor of the clone's main, which is a "
                "SUCCESS arm; reaching this refusal with it means the read-back and the probe "
                "disagree")
    return ("diverged — the clone's main is NOT an ancestor of the shipped main and the shipped "
            "main is NOT an ancestor of the clone's: the two histories have separated, so NO "
            "fast-forward can reach the mirror and the push was rejected for that reason")


def ship_trees(repo_root, box: str, ref: str = "HEAD", *, request: str, attempt: int = 1,
               user: str = "dev", main_ref: str = "main", timeout: float = 900) -> dict:
    """Push the candidate commit, the current `main` and `refs/tags/*` into the box's persistent bare
    clone, and return the SHIPPED identity plus the measured push wall.

    All three refs, deliberately (rule 3): the candidate is the subject, `main` supplies the pinned
    leg's `tests/` overlay, and the tags are part of the tree's identity story — a pinned test
    resolves a governed tag, and a history-less tree silently mis-classifies real tests as
    host-sensitive (trial cycle 2: 17 of 64 remote failures were history reads, not host reads).

    THE FIRST TWO ARE KEYED BY THIS REQUEST (`box_ref`, T-12247), which is why `request` is
    keyword-REQUIRED: an unkeyed ship is precisely the bug this card removes. The candidate and the
    main tree go to `refs/venue/<request>-<attempt>/{cand,main}` and the read-back below asks about
    THOSE refs, so what it proves is that THIS push arrived — not who pushed last. Only the tags stay
    shared, and they can be: a tag is content-addressed, so two requests pushing it push the same
    object under the same name. `attempt` keeps `box_run_dir`'s default rather than being required
    too, so the two helpers read alike at every call site.

    The push is a DELTA against the seeded clone. Its cost is the AC2 number this card measures and
    the returned `push_s` is where that measurement comes from — it is reported, never assumed.

    A SECOND PUSH MIRRORS THE HOST'S MAIN ONTO THE CLONE'S OWN `refs/heads/main` (T-12296) — a
    different KIND of ref from the transport ones above, which is why it is a SEPARATE push rather
    than a fourth refspec, and why losing the race on it can no longer fail the transport. The
    keyed `refs/venue/<req>-<att>/main` is TRANSPORT: this pass's own main, read back below and
    digested by the envelope, private to this request by construction. `MIRROR_MAIN_REF`
    (`refs/heads/main`) is the clone's own main BRANCH — the box clone is a MIRROR of the host's
    main and is never authored on the box.

    AND THAT MIRROR PUSH IS A PURE FAST-FORWARD — NO `-f`, DELIBERATELY (T-12301). This is the one
    property a CONCURRENT leg depends on, so it is stated where the push is built rather than left to
    be inferred. `refs/heads/main` is SHARED, and a leg classifies a mid-run move of it by ANCESTRY
    against its OWN main (SPEC-0203 rule 4): equal-or-DESCENDANT is a benign mirror advance, anything
    else is a clobber that ABORTS that leg (`venue-refs-clobbered`). A FORCED push satisfies that only
    by luck — a request shipping an OLDER host main than a live peer's drags the shared ref BACKWARDS,
    which is a non-descendant move and therefore exactly that abort (measured 2026-09-09T09:35Z, one
    forced mirror against one live leg). Refusing the non-fast-forward instead makes the benign case
    STRUCTURAL rather than lucky: the ref only ever ADVANCES, so it is always equal to or a descendant
    of every main any live request shipped, and no pass can clobber another by mirroring. On a
    rejection the mirror is SKIPPED, never forced — and skipping is SAFE for exactly the reason the
    rejection happened: the clone already holds something that CONTAINS what we would have written,
    which the postcondition below MEASURES rather than assumes. (This is NOT `--force-with-lease`: a
    lease only proves nobody moved the ref since we read it, and will still happily write a backwards
    sha — which is the move that aborts a peer.)

    WHY IT IS SHIPPED ON EVERY REQUEST: each leg checkout is a `git worktree add` OF THIS BARE CLONE,
    so it shares the clone's refs, and a test that resolves the NAME `main` inside a leg resolves
    `refs/heads/main`. A box raised from the seed snapshot keeps the snapshot's main forever —
    measured 2026-09-09, a box raised at 05:14Z still holding e4c26701968e from 2026-09-06 — so
    `git merge-base HEAD main` returned the SEED sha for every branch above it and
    `tests/test_t12186_help_surface_pinned.py` failed on the box with a diff consisting entirely of a
    verb that had landed on main days earlier (T-12287, `tests_failed` 2026-09-09T05:33:44Z).

    THE MIRROR IS NOT PART OF THE TRANSPORT IDENTITY, DELIBERATELY — BUT ITS POSTCONDITION IS
    ENFORCED, LOUDLY. Nothing in the transport path reads the mirror: the read-back below asks about
    THIS request's keyed refs, the leg checks out `$CANDREF`/`$MAINREF` and the envelope digests
    `refs/venue/<req>-<att>/main:tests`. That separation is what T-12247 bought, and this card does
    not sell it back. What being OFF the transport path does NOT mean is being optional (the AC1
    audit-post finding): `ship_trees` must never RETURN with a stale mirror, because AC1 is exactly
    the promise that after a request the clone's `refs/heads/main` carries the host's main. So the
    mirror push RETRIES once on the transient lost-lock case, the ref is READ BACK off the clone,
    and the read-back is JUDGED. TWO arms are SUCCESS: the clone reads the sha we shipped, or the
    sha we shipped is an ANCESTOR of what the clone reads — a concurrent request mirrored a NEWER
    host main, which leaves the mirror CURRENT rather than stale (and still contains the merge-base
    a main-consulting test needs). Anything else RAISES `RemoteVerifyError` naming both shas and the
    push's own stderr, so the request fails where the fault is instead of handing a caller an
    unread field. The shared-ref race therefore stays harmless — both success arms are what a race
    produces, and with the fast-forward-only push above the ANCESTOR arm is ALSO what a REJECTED
    mirror produces — while a genuinely unwritable mirror stays loud.

    A THIRD, HEALING ARM FOR A DIVERGED CLONE MAIN (T-12344). A clone main that is NEITHER an ancestor
    NOR a descendant of the shipped main — proven box-side by BOTH `merge-base --is-ancestor`
    directions being false — can never be fast-forwarded by ANY request, so before this arm every
    request on the box failed the postcondition above, permanently, until a person force-reset the
    ref: measured 2026-09-10 15:08–15:19Z, an orphan main (a sha the host's main had rewritten) cost
    8 consecutive venue-fault aborts across 4 sessions and ~20 min of a blocked fleet. A re-seeded
    box holding a foreign snapshot main is the same shape. So a PROVEN-diverged clone main is healed
    ONCE: `git push --force-with-lease=refs/heads/main:<seen>` — the lease pins the EXACT orphan we
    read, so a peer that mirrored a real newer host main in between wins (git rejects the lease) and
    we simply re-read — then the read-back is re-judged by the SAME two arms above, and a heal that
    took records `venue_main_healed: {from, to}` on the returned identity (it reaches the executor
    row / `verify_metrics` like the leg-level `venue_main_mirrored` does). This does NOT reopen the
    T-12301 fence: a merely-BEHIND clone (an ancestor of shipped) is NEVER forced — a fast-forward was
    possible and failed for a real reason, so it stays loud — and a DESCENDANT clone never reaches
    the arm. The lease cannot be the backwards move that fence exists for, because the sha it
    replaces is by construction contained in NO live request's main history. ACCEPTED CONSEQUENCE:
    the one live leg whose OWN main IS the orphan (the request that shipped it) classifies the heal
    as a non-descendant move and aborts `venue-refs-clobbered` once — correct, its main no longer
    exists on the host; its retry ships the current main. The operator escape hatch
    (`git push -f main:refs/heads/main`) remains for the still-loud cases."""
    ident = shipped_identity(repo_root, ref, main_ref=main_ref)
    cand_ref = box_ref(request, attempt, "cand")
    main_box_ref = box_ref(request, attempt, "main")
    ident["box_cand_ref"], ident["box_main_ref"] = cand_ref, main_box_ref
    _ssh(box, f"mkdir -p {BOX_VENUE_DIR}; [ -d {BOX_REPO_GIT} ] || git init -q --bare {BOX_REPO_GIT}",
         user=user, timeout=120)
    t0 = time.monotonic()
    url = f"ssh://{user}@{box}/home/{user}/venue/repo.git"
    push_env = {**os.environ, "GIT_SSH_COMMAND": "ssh " + " ".join(SSH_OPTS)}
    r = subprocess.run(
        ["git", "push", "-q", "-f", url,
         f"{ident['cand_sha']}:{cand_ref}", f"{ident['shipped_main_sha']}:{main_box_ref}",
         "refs/tags/*:refs/tags/*"],
        cwd=str(repo_root), text=True, capture_output=True, timeout=timeout, env=push_env)
    if r.returncode != 0:
        raise RemoteVerifyError(f"git push into the venue clone failed: {(r.stderr or '')[:300]}")
    ident["push_s"] = round(time.monotonic() - t0, 2)
    # THE MIRROR SHIP, IN ITS OWN PUSH (T-12296). It is deliberately NOT a fourth refspec of the
    # transport push above, and the reason was MEASURED rather than anticipated: a git push is
    # ALL-OR-NOTHING across its refspecs, and `refs/heads/main` is a SHARED ref, so two overlapping
    # requests reaching it at once make one of them lose the ref lock (`cannot lock ref
    # 'refs/heads/main'`) — which failed that request's ENTIRE push, transport refs included, and
    # surfaced as a transport fault. That is the exact class T-12247 removed from this seam,
    # re-entering through a ref nobody in the transport path even reads. Splitting it out keeps the
    # TRANSPORT safe from mirror contention; what it does NOT do is make the mirror optional — the
    # postcondition below is enforced. `push_s` still measures the TRANSPORT delta only, so the AC2
    # number stays comparable across this change.
    # Cheap by ordering: the transport push above already carried `shipped_main_sha` to the box, so
    # this second push transfers no objects — it is a ref update.
    # NO `-f` — fast-forward-only, for the T-12301 reason the docstring above spells out: a forced
    # mirror can move the SHARED ref BACKWARDS, and a backwards move is precisely what a concurrent
    # leg classifies as a clobber and aborts on.
    mirror_push = ["git", "push", "-q", url, f"{ident['shipped_main_sha']}:{MIRROR_MAIN_REF}"]
    m = subprocess.run(mirror_push, cwd=str(repo_root), text=True, capture_output=True,
                       timeout=timeout, env=push_env)
    if m.returncode != 0:
        # ONE RETRY. A lost ref lock is TRANSIENT by nature — it means another request held
        # `refs/heads/main` for the moment of our update, not that the ref is unwritable — so the
        # retry is what makes the common contention case converge quietly instead of raising on a
        # momentary collision. Bounded at one: a second failure is a real fault, and the
        # postcondition check below is what makes it loud.
        # THE OTHER FAILURE CLASS IS NOT A FAULT AT ALL, and the retry is deliberately NOT conditioned
        # on telling the two apart: a non-fast-forward REJECTION (a peer already mirrored a NEWER host
        # main) is the ordinary concurrency outcome, a retry cannot change it, and it needs no branch
        # here because the postcondition below judges the clone's STATE rather than this push's exit
        # code — and that state is the ANCESTOR success arm. One extra rejected ref update buys one
        # code path instead of two.
        m = subprocess.run(mirror_push, cwd=str(repo_root), text=True, capture_output=True,
                           timeout=timeout, env=push_env)
    # THE POSTCONDITION IS READ BACK AND ENFORCED, NEVER ASSUMED FROM AN EXIT CODE — the same
    # discipline the transport read-back below states: a push reporting success is not the same
    # claim as the clone holding what we named. `check=False` and its own call, deliberately:
    # folding this into the transport read-back would let an absent or unreadable mirror surface as
    # a TRANSPORT fault, which is precisely the coupling the split above removes.
    shipped_main = ident["shipped_main_sha"]

    def _read_mirror():
        return _ssh(box, f"cd {BOX_REPO_GIT} && git rev-parse --verify -q {MIRROR_MAIN_REF}",
                    user=user, timeout=120, check=False).stdout.strip() or None

    def _is_ancestor(a, b):
        # Asked box-side, because the relation must be judged in the object store that actually
        # holds both commits. Exit 0 = ancestor; 1 = not; 128 = a sha the clone does not have,
        # which reads as "not an ancestor" too — fail-closed for every arm that consults it.
        return _ssh(box, f"cd {BOX_REPO_GIT} && git merge-base --is-ancestor {a} {b}",
                    user=user, timeout=120, check=False).returncode == 0

    def _current(seen):
        # TWO SUCCESS ARMS, and the second one is not a loophole. EQUAL is the ordinary case.
        # ANCESTOR is the concurrency case: a request that overlapped ours mirrored a NEWER host
        # main, so the clone's `refs/heads/main` CONTAINS the main we shipped — current, not stale,
        # and it still carries the merge-base a main-consulting test needs.
        return bool(seen) and (seen == shipped_main or _is_ancestor(shipped_main, seen))

    seen = _read_mirror()
    ident["box_main_sha"] = seen
    ident["box_main_ref_shipped"] = _current(seen)
    heal = None
    # THE HEALING ARM (T-12344), entered ONLY on a PROVEN-DIVERGED clone main: BOTH ancestry
    # directions false. `_current` failing already establishes "not a descendant" for a present
    # `seen`; the second direction is asked EXPLICITLY, because a BEHIND clone (an ancestor of what
    # we shipped) is NOT healed — a fast-forward was possible and failed for a real reason, and
    # forcing it is the backwards-move hazard T-12301 fenced. An ABSENT ref is not diverged either:
    # there is nothing to lease against, and the fast-forward push above should have created it.
    if (not ident["box_main_ref_shipped"] and seen and seen != shipped_main
            and not _is_ancestor(shipped_main, seen) and not _is_ancestor(seen, shipped_main)):
        # ONCE, WITH A LEASE ON THE EXACT ORPHAN WE READ. If a peer moved the ref in between — to a
        # real newer main it just mirrored — git REJECTS this push and the re-read below lets the
        # two ordinary arms judge the peer's value. Never a bare `-f`: that is the push the T-12301
        # docstring above retires, and the lease is what makes this one unable to clobber a peer.
        heal = subprocess.run(
            ["git", "push", "-q", f"--force-with-lease={MIRROR_MAIN_REF}:{seen}", url,
             f"{shipped_main}:{MIRROR_MAIN_REF}"],
            cwd=str(repo_root), text=True, capture_output=True, timeout=timeout, env=push_env)
        orphan, seen = seen, _read_mirror()
        ident["box_main_sha"] = seen
        ident["box_main_ref_shipped"] = _current(seen)
        if ident["box_main_ref_shipped"] and heal.returncode == 0 and seen == shipped_main:
            # RECORDED on the identity — the heal is a fact about the box a reader of the journal
            # row must be able to see, exactly as a mirror advance is (T-12301 AC3). Only when OUR
            # push is what moved it: a lease that lost to a peer is not a heal we performed.
            ident[VENUE_MAIN_HEALED_KEY] = {"from": orphan, "to": seen}
    if not ident["box_main_ref_shipped"]:
        # LOUD, not reported. AC1 is the promise that after a request the clone's own main carries
        # the host's; returning here would hand the caller a false one on an unread field.
        # AND THE REFUSAL NAMES ITS ANCESTRY VERDICT, MEASURED (T-12364). Two shas and a push
        # stderr leave the reader to re-derive the RELATION, and one direction alone misreads it:
        # the mirror push is rejected when the CLONE's main is not an ancestor of the shipped
        # sha, while the success arm above asks the opposite direction. So on THIS path — the
        # refusal path, which is loud and rare, so the extra reads cost a healthy request nothing —
        # both directions are asked box-side, in the object store that holds both commits, and the
        # verdict is named from the PAIR. That is what turned the 2026-09-10 15:05Z/15:08Z aborts
        # into an ssh-and-compare-by-hand diagnosis: the information existed here and was dropped.
        raise RemoteVerifyError(
            f"the venue clone's {MIRROR_MAIN_REF} is STALE after the mirror push and its one "
            f"retry: shipped {shipped_main}, clone holds {seen or '<absent>'}"
            f"; ancestry: {mirror_ancestry_verdict(box, shipped_main, seen, user=user)}"
            + (f"; mirror push stderr: {(m.stderr or '').strip()[:200]}"
               if (m.stderr or "").strip() else "")
            + (f"; heal push (force-with-lease) stderr: {(heal.stderr or '').strip()[:200]}"
               if heal is not None and (heal.stderr or "").strip() else ""))
    # Read the identity BACK from the clone: the push reporting success is not the same claim as the
    # clone holding the trees we named, and the difference is exactly a transport fault. It reads
    # THIS REQUEST'S refs — against the shared ones this read answered "whose push landed last?",
    # which for the loser of an overlap is a digest mismatch reported as a transport fault.
    got = _ssh(box, f"cd {BOX_REPO_GIT} && git rev-parse {cand_ref}^{{tree}} {main_box_ref}:tests",
               user=user, timeout=120).stdout.split()
    ident["box_cand_tree"], ident["box_main_tests_tree"] = (got + [None, None])[:2]
    return ident


# ── the environment fingerprint (rules 1 + 4) ────────────────────────────────────────────────────

_FINGERPRINT_SCRIPT = r"""python3 - <<'PY'
import json, os, platform, resource, shutil, subprocess
def sh(c):
    return subprocess.run(c, shell=True, text=True, capture_output=True).stdout.strip()
st = os.statvfs('/dev/shm')
print(json.dumps({
    "os": sh("lsb_release -ds 2>/dev/null || head -1 /etc/os-release"),
    "kernel": platform.release(), "arch": platform.machine(),
    "python": platform.python_version(), "git": sh("git --version"),
    "pytest": sh("python3 -m pytest --version 2>&1 | head -1"),
    "cores": os.cpu_count(),
    "ram_mb": int(sh("awk '/MemTotal/{print int($2/1024)}' /proc/meminfo") or 0),
    "nofile_soft": resource.getrlimit(resource.RLIMIT_NOFILE)[0],
    "nofile_hard": resource.getrlimit(resource.RLIMIT_NOFILE)[1],
    "tmpfs_shm_mb": st.f_blocks * st.f_frsize // (1024 * 1024),
    "tmpfs_shm_avail_mb": st.f_bavail * st.f_frsize // (1024 * 1024),
    "rsync": bool(shutil.which("rsync"))}))
PY"""


def probe_fingerprint(box: str, *, user: str = "dev", timeout: float = 60) -> dict:
    """Measure the box environment. `tmpfs_shm_mb` is the `/dev/shm` SIZE the owner directive requires
    the fingerprint to record (the executor points `YITC_VERIFY_TMPDIR` there for every leg), and it
    is recorded beside the AVAILABLE figure because a tmpfs that is large but full is a different
    fact from one that is small."""
    return json.loads(_ssh(box, _FINGERPRINT_SCRIPT, user=user, timeout=timeout).stdout)


# ── the box-side leg driver (rule 3) ─────────────────────────────────────────────────────────────

#: The lease + sweep prologue (SPEC-0203 rule 4), EXTRACTED from the leg template so the concurrency
#: logic is executable by a test without a box — the same reason `box_leg_script` returns text. It is
#: substituted in as a VALUE, so its own `%` are never scanned by the template's formatting.
_BOX_LEASE_PROLOGUE = r"""
# THE KILL CONDITION IS THE CLIENT, NEVER THE KEY (SPEC-0203 rule 4, T-12220). Rule 4 makes the kill
# conditional on the prior group's CLIENT BEING GONE, and that qualifier governs BOTH of its arms —
# a new attempt for the same request, and the venue's own idle sweep. So this loop reads every OTHER
# lease and kills only what is orphaned: a live run is left alone whether it belongs to THIS request
# (an earlier attempt still going) or to another one entirely. The predecessor keyed by leg NAME
# alone killed unconditionally because it had no way to ask the question — the lease now records the
# CLIENT handle (the sshd session process, which dies with the client), so the question is answerable.
# Rule 4's disconnect-recovery guarantee is therefore kept in BOTH arms and narrowed in NEITHER: a
# disconnected client's run is still reaped, by whichever pass next starts on this box.
mkdir -p "$LEASES" "$RUN"
for L in "$LEASES"/*; do
  [ -e "$L" ] || continue
  [ "$L" = "$LEASE" ] && continue
  read -r L_REQ L_ATT L_PG L_CLIENT L_LEG L_RUN L_CLASS < "$L" || continue
  # A lease we cannot read the client of is left ALONE: killing on an unreadable record would be the
  # unconditional kill this card removes, wearing a condition it cannot actually evaluate.
  [ -n "${L_CLIENT:-}" ] || continue
  kill -0 "$L_CLIENT" 2>/dev/null && continue
  [ -n "${L_PG:-}" ] && kill -TERM -- "-$L_PG" 2>/dev/null
  rm -f "$L"
  # THE RUN DIR IS PER-REQUEST BUT A LEASE IS PER-LEG, so reaping ONE leg must not delete the home
  # of its SIBLING. A land holds a `cand` and a `pinned` lease in ONE run dir: if cand's client dies
  # while pinned is still running, removing the dir here would destroy a LIVE leg's checkout and
  # outputs mid-run — a data-loss race this sweep would introduce, not inherit (found by the
  # T-12220 audit-post convergence consult, 2026-09-07). So the dir goes only once NO lease of that
  # request+attempt remains; whichever reap is last performs it, and a live sibling keeps it.
  if [ -n "${L_RUN:-}" ] && [ "$L_RUN" != "$RUN" ] &&
     ! compgen -G "$LEASES/$L_REQ-$L_ATT-*" > /dev/null; then
    rm -rf "$L_RUN"
  fi
done

# ── THE MACHINE-WIDE REQUEST CAP, BY REQUEST CLASS (SPEC-0203 rule 4) ─────────────────────────
# THE UNIT IS THE REQUEST, NEVER THE LEG. A land ships cand + pinned = 2 leases; both legs of ONE
# request are admitted together and NEVER wait on each other, which is why the count is over
# DISTINCT `$REQ-$ATT` prefixes and why this request's own prefix is skipped. Counting leases would
# make a land wait on itself and deadlock at cap 1.
#
# ADMISSION IS DECIDED BY REQUEST CLASS (T-12259, owner directive 2026-09-08T08:08:38Z). The one
# shared cap treated a land and a Stage-6 pass as the same thing, and they are not: a land is the
# box's primary client at nice 0 and full width, a Stage-6 pass runs at `YITC_VENUE_STAGE6_NICE`
# on half the width and yields ~99% of contended CPU to a land under CFS (weights 1024 vs 15). So
# an overlapping Stage-6 costs a land nothing but its own wall clock — while the shared cap made it
# WAIT for one, measured at 515 s and then a kill (T-12251 attempt 1, 2026-09-08T07:05-07:25Z).
# The two classes are therefore admitted on DIFFERENT questions:
#   LAND   — admitted when the live LAND count is below $CAP. It never counts, and therefore never
#            waits on, a Stage-6. `YITC_VENUE_MAX_REQUESTS` STAYS the carrier of that cap; there is
#            deliberately no second land cap to keep in step with it.
#   STAGE6 — admitted when the live STAGE-6 count is below $S6MAX *and* the box's own load1 is
#            below $HEADROOM. The concurrency bound alone would admit four Stage-6 passes onto a box
#            a land is already saturating; the headroom alone would admit an unbounded number onto an
#            idle one. Both, or neither is honest.
# WHAT THIS RETIRES, named: «a Stage-6 waits behind every land and every other Stage-6».
#
# THE CLASS IS DERIVED, NOT ADDED. `$NICE` is already this leg's argument 5 — `route()` sets it to 0
# for a land and to `venue_stage6_nice()` (1..19) for a `priority=low` pass — so the class is read
# off what the leg already receives rather than carried as a second, desyncable field.
#
# WHY THIS SEAM AT ALL. Nothing else bounds it: the land reservation and the SPEC-0132 slot pool are
# BOTH keyed per repo (`_verify_slot_dir` hashes realpath(main_wt)), so neither can see a SECOND
# checkout landing onto the same box. The box is the only place the machine-wide question is
# answerable, and the lease records are already here.
#
# LIVENESS IS THE SWEEP'S OWN PREDICATE, RE-USED, NOT RE-INVENTED. A request counts as live only
# while its recorded CLIENT pid answers `kill -0` — the exact test the sweep above applies. So an
# orphan lease is never counted (the sweep reaps it; it must not also block admission), and there is
# exactly ONE liveness test on this box.
#
# ADMISSION IS ATOMIC. The count and this leg's own lease WRITE happen together inside one critical
# section, because a check-then-write cannot state "at most N": two requests polling in the same
# instant would both read zero and both take the box (audit-pre finding, 2026-09-07). The mutex is
# `flock` on a lock file in the lease dir — the SAME primitive the LOCAL side of this same question
# already uses (`_acquire_land_reservation`, the SPEC-0132 slot semaphore), applied on the other
# side of the wire. It is held across a few filesystem reads and one write, and released at once.
#
# THE DEGRADED PATH IS RECORDED, NEVER SILENT. A box without `flock` runs the same count-then-write
# UNLOCKED and sets ATOMIC=0, which travels out in `leg.json` as `venue_admission_atomic`. Hanging a
# verify pass because a utility is missing would be the worse failure; passing a non-atomic
# admission off as an atomic one would be the dishonest one. So it proceeds and says so, and the
# acceptance criterion for this cap requires the flag to read 1.
#
# BOUNDED BY CONSTRUCTION: this loop has no timeout of its own. The leg runs under the existing
# per-leg ssh timeout in `run_legs`, so a wedged box fails THAT as a venue fault rather than parking
# here forever. A second bound would be a second thing to get wrong.
CAP=@MAX_REQUESTS@
S6MAX=@STAGE6_MAX@
HEADROOM=@STAGE6_HEADROOM@
# AN UNSUBSTITUTED TEMPLATE FAILS FAST AND LOUD, IT DOES NOT SPIN. This prologue is a TEMPLATE:
# `box_lease_prologue` resolves the three admission parameters into it, and every shipped path goes
# through that. If the text is ever executed RAW, they are still placeholders — and the two ways of
# handling that are not equally safe. Treating a non-numeric cap as "no cap" would FAIL OPEN,
# silently admitting every request on exactly the box this exists to protect; leaving it to the
# arithmetic test below would FAIL SLOW, looping on `integer expression expected` until the per-leg
# timeout kills it at ~0 CPU, which reports as an unattributable stall rather than as the programming
# error it is. So it refuses immediately, naming what it saw: fail-closed AND legible. All three are
# guarded, not just the first: a resolved cap beside an unresolved headroom would admit every land
# and hang every Stage-6, which is the harder failure to attribute of the two.
case "$CAP" in
  ''|*[!0-9]*)
    echo "venue admission: request cap not substituted (got '$CAP') — this prologue is a TEMPLATE; render it through box_lease_prologue()" >&2
    exit 90 ;;
esac
case "$S6MAX" in
  ''|*[!0-9]*)
    echo "venue admission: stage6 concurrency not substituted (got '$S6MAX') — this prologue is a TEMPLATE; render it through box_lease_prologue()" >&2
    exit 90 ;;
esac
case "$HEADROOM" in
  ''|*[!0-9.]*|.|*.*.*)
    echo "venue admission: stage6 headroom not substituted (got '$HEADROOM') — this prologue is a TEMPLATE; render it through box_lease_prologue()" >&2
    exit 90 ;;
esac
# THIS REQUEST'S CLASS, derived from the nice the leg was invoked with (see the block above).
# `${NICE:-0}` rather than a bare `$NICE` so the prologue stays standalone-executable under `set -u`
# by a test that does not bind it — the same property `${OUT:-$RUN}` gives the record write below.
CLASS=land
[ "${NICE:-0}" -gt 0 ] 2>/dev/null && CLASS=stage6
# WHERE THE BOX'S OWN LOAD IS READ. `/proc/loadavg` on every shipped path; the override exists ONLY
# so this text is exercisable without a box — the same reason the prologue is extracted as text at
# all, and the same shape as the leg template's `VENUE_CORRUPT` rehearsal seam. The executor never
# sets it, and it cannot change a verdict: it decides WHEN a Stage-6 pass is admitted, never which
# files run or how they conclude.
LOADAVG_FILE="${VENUE_LOADAVG_FILE:-/proc/loadavg}"
# THE LOCK LIVES BESIDE THE LEASE DIR, NOT INSIDE IT. The lease dir means exactly one thing —
# one file per live leg — and both the cleanup and the sweep enumerate it on that assumption.
# A mutex is machine-wide and permanent, not a lease, so putting it in there would change what
# that directory means for every reader of it.
LOCK="$(dirname "$LEASES")/.venue-admission.lock"
WAITED=0; LIVE=0; LIVE_S6=0; LOAD1=0; DEG=-; ATOMIC=1
command -v flock > /dev/null 2>&1 || ATOMIC=0
[ "$ATOMIC" = 1 ] && { exec 9>"$LOCK" || ATOMIC=0; }

# The critical section, as ONE function so the locked and unlocked paths run IDENTICAL logic and
# cannot drift: count the distinct live FOREIGN requests BY CLASS, read the box's load once, and —
# only if this request's own class question answers yes — write this leg's own lease. Echoes
# `<verdict> <live> <live_stage6> <load1> <headroom_degraded>` so the caller reads all five out of
# one subshell (`-` in the last field when the load WAS measured).
venue_try_admit() {
  local rows n_any n_land n_s6 load1 raw deg ok c L X_REQ X_ATT X_PG X_CLIENT X_LEG X_RUN X_CLASS
  rows=$(for L in "$LEASES"/*; do
        [ -f "$L" ] || continue
        case "${L##*/}" in .*) continue ;; esac
        read -r X_REQ X_ATT X_PG X_CLIENT X_LEG X_RUN X_CLASS < "$L" || continue
        [ -n "${X_CLIENT:-}" ] || continue
        [ "$X_REQ-$X_ATT" = "$REQ-$ATT" ] && continue
        kill -0 "$X_CLIENT" 2>/dev/null || continue
        # A LEASE WHOSE CLASS IS ABSENT OR UNRECOGNISED IS `unknown`, NEVER A GUESS. The only way to
        # see one is a pass still running from the six-field pre-T-12259 code, and the safe reading
        # of a live request we cannot classify is not to pick a class for it — see the count below.
        case "${X_CLASS:-}" in land|stage6) ;; *) X_CLASS=unknown ;; esac
        echo "$X_CLASS $X_REQ-$X_ATT"
      done | sort -u)
  # AN UNKNOWN-CLASS REQUEST COUNTS IN BOTH POOLS — fail-closed in both directions. It is a live
  # request on this box either way, so letting it block neither class would be the one reading that
  # can over-admit; letting it block both merely delays, and only for as long as one pre-upgrade
  # pass is still running. The loop is fed by a here-doc, NOT a pipe, so the counters it increments
  # are this shell's and survive it.
  n_any=0; n_land=0; n_s6=0
  while read -r c _; do
    [ -n "${c:-}" ] || continue
    n_any=$((n_any + 1))
    case "$c" in
      land)   n_land=$((n_land + 1)) ;;
      stage6) n_s6=$((n_s6 + 1)) ;;
      *)      n_land=$((n_land + 1)); n_s6=$((n_s6 + 1)) ;;
    esac
  done <<EOF
$rows
EOF
  # ONE loadavg read per admission attempt, taken for BOTH classes although only a Stage-6 is gated
  # on it: a heartbeat that names the load is what makes a wait attributable afterwards, and a land's
  # heartbeat carrying it costs one file read. A load that CANNOT BE READ (file absent/unreadable) or
  # that does not parse is NOT read as 0: a 0 would admit a Stage-6 on the concurrency count alone,
  # with no evidence that box headroom is actually below the threshold. Instead the admission enters
  # a DEGRADED mode — see the class branch below — and names the reason so the degradation is
  # attributable in the heartbeat and in this leg's envelope rather than being silent.
  deg=
  if raw=$(cut -d" " -f1 "$LOADAVG_FILE" 2>/dev/null); then
    load1=$raw
    case "$load1" in ''|*[!0-9.]*|.|*.*.*) load1=0; deg=loadavg-malformed ;; esac
  else
    load1=0; deg=loadavg-unreadable
  fi
  ok=0
  if [ "$CLASS" = land ]; then
    # A LAND IS NEVER GATED ON LOAD, so the degraded mode does not touch it: lands are admitted on
    # their own cap alone (1), exactly as before, degraded or not.
    [ "$n_land" -lt "$CAP" ] && ok=1
  elif [ -n "$deg" ]; then
    # DEGRADED — FAIL-CLOSED: no headroom evidence, no Stage-6 admission AT ALL. `ok` stays 0 and
    # the request waits for the load to become readable again; a land is untouched above, since a
    # land was never gated on headroom and so keeps landing on a box whose loadavg is unreadable.
    #
    # THE BOUNDED-DEGRADED READING WAS TAKEN AND RETIRED (decision 2026-09-08, T-12259): admitting
    # one Stage-6 at a time here was the pre-T-12259 cap re-used as a fallback, and it admits a
    # Stage-6 with NO evidence that box headroom is below the threshold — the same fail-open the
    # measured arm exists to prevent, merely narrowed. Two independent auditor passes held on it.
    # The cost of fail-closed is bounded and visible: only Stage-6 is affected, only while
    # `/proc/loadavg` is unreadable or unparseable (never observed on the published box), and the
    # refusal is ATTRIBUTABLE — the wait heartbeat below names `headroom_degraded=<reason>`, so a
    # Stage-6 waiting on this reads as this and not as concurrency. T-12267 keeps the
    # bounded-degraded axis if an incident ever pulls it back.
    :
  elif [ "$n_s6" -lt "$S6MAX" ] &&
       awk -v l="$load1" -v h="$HEADROOM" 'BEGIN{exit !(l+0 < h+0)}'; then
    ok=1
  fi
  # `${deg:--}` so the verdict line always carries the SAME field count: a reader parsing it
  # positionally must never have a field shift under it because a box happened to be measurable.
  if [ "$ok" = 1 ]; then
    echo "$REQ $ATT $$ $CLIENT $LEG $RUN $CLASS" > "$LEASE"
    echo "ADMITTED $n_any $n_s6 $load1 ${deg:--}"
  else
    echo "WAIT $n_any $n_s6 $load1 ${deg:--}"
  fi
}

while :; do
  # `flock -w` FAILING is not a reason to stop: a stuck holder must degrade to a retry, never to a
  # hang. An un-acquired lock simply means this round is unsynchronised, so the round is skipped
  # rather than run unlocked behind a flag that says otherwise.
  if [ "$ATOMIC" = 1 ]; then
    if flock -w 30 9; then
      ADMIT=$(venue_try_admit); flock -u 9
    else
      ADMIT="WAIT $LIVE $LIVE_S6 $LOAD1 $DEG"
    fi
  else
    ADMIT=$(venue_try_admit)
  fi
  # Read the five fields POSITIONALLY, not by `${ADMIT##* }`: the verdict now carries three figures
  # and a degradation token rather than one figure, and a suffix match would silently start reading
  # the load as the live count.
  # Via `read`, not `set --`, because the leg script's own positional parameters are still live here
  # and clobbering them to parse a status line would be a side effect nobody reading this expects.
  read -r _VERDICT LIVE LIVE_S6 LOAD1 DEG <<EOF
$ADMIT
EOF
  LIVE=${LIVE:-0}; LIVE_S6=${LIVE_S6:-0}; LOAD1=${LOAD1:-0}; DEG=${DEG:--}
  case "$ADMIT" in ADMITTED*) break ;; esac
  if [ $((WAITED % 30)) -eq 0 ]; then
    # `live` KEEPS ITS MEANING — all live foreign requests, every class — so an existing reader of
    # this line is not re-pointed at a different number. `class` / `live_stage6` / `load1` are added
    # beside it because without them a Stage-6 wait is unattributable between its two possible
    # causes, which is exactly what the 515 s baseline could not be read against.
    # `headroom_degraded` is printed UNCONDITIONALLY (`-` when the load was measured) for the same
    # reason the verdict line carries it that way: a field that appears only sometimes is a field a
    # reader gets wrong exactly when it matters.
    echo "waiting_for_venue_admission request=$REQ-$ATT leg=$LEG class=$CLASS live=$LIVE live_stage6=$LIVE_S6 load1=$LOAD1 headroom_degraded=$DEG cap=$CAP waited_s=$WAITED" >&2
  fi
  sleep 5
  WAITED=$((WAITED + 5))
done
# `${OUT:-$RUN}` rather than a bare `$OUT`: the prologue is EXTRACTED so it can be executed by a
# test without a box, and a prologue that hard-requires a variable only the full leg template
# binds is not standalone-executable — under `set -u` it would abort the harness rather than
# run. The real leg always sets OUT (the leg.json reader looks there); a bare harness gets the
# record beside its run dir instead of losing it.
echo "$WAITED $CAP $ATOMIC $CLASS $LIVE_S6 $DEG" > "${OUT:-$RUN}/venue-wait.txt"
"""



#: The LAND-OVERLAP POLLER (SPEC-0203 rule 4 / SPEC-0071 rule 1, T-12260), EXTRACTED as text for the
#: same reason `_BOX_LEASE_PROLOGUE` is: the logic is bash that no host-side unit test could reach
#: otherwise, and the T-12199 lesson is that box-only bash gets debugged on a live box at the cost of
#: an unusable land. It is substituted into the leg template as a VALUE, so its own `%` are never
#: scanned by that template's formatting.
#:
#: WHAT IT MEASURES, and why the box is the only place that can. A Stage-6 leg runs at nice 19; a
#: land runs at nice 0 and full width. Under CFS those weights are 15 against 1024, so an overlapped
#: Stage-6 receives ~1% of contended CPU — it is effectively PAUSED while every wall-clock bound
#: keeps ticking. T-12251 attempt 1 is the measurement: the cand leg's wall reached 600.6 s, the file
#: under it was killed and attributed not-in-diff, and the worker re-ran the whole Stage-6, so the
#: run was wasted twice. With T-12292 admitting up to four Stage-6 passes by headroom, overlapping a
#: land is the NORMAL case rather than the unlucky one.
#:
#: IT ADDS NO RECORD AND NO SECOND LIVENESS TEST. The lease dir already names every live request by
#: CLASS (T-12292) and `kill -0 <client>` is already this box's ONE liveness predicate — the sweep's
#: and the admission count's. This loop asks the SAME question of the SAME data, at a different
#: moment, and writes the answer down.
#:
#: WRITE-THEN-RENAME, WHOLE FILE, EVERY POLL. The reader (`verify_runner._land_overlap_intervals`)
#: runs concurrently in the same leg, so it must never see a half-written list; and the CURRENTLY-OPEN
#: interval is republished with its end at `now` on every poll, so a reader at any instant sees the
#: overlap accrued SO FAR rather than only what has already closed. That is what lets the per-file
#: deadline be uncharged WHILE the land is still running, instead of after it finishes — which would
#: be after the kill it exists to prevent.
#:
#: THE HEARTBEAT IS PUBLISHED CONTINUOUSLY, DURING THE RUN, and that is load-bearing (audit-pre
#: finding, 2026-09-08). The local side bounds each leg with its own `p.wait` timeout; a total
#: emitted only after the run ended could not extend a bound that expires before it. So the line goes
#: out on the same loop that writes the sidecar, on the leg's already-drained stdout.
_BOX_LAND_OVERLAP_POLLER = r"""
venue_land_overlap_poll() {
  # $1 sidecar path · $2 this request's own `$REQ-$ATT` key · $3 lease dir · $4 poll seconds · $5 leg
  local file=$1 me=$2 leases=$3 interval=$4 leg=$5
  local closed= open= now live total beat=0
  local L X_REQ X_ATT X_PG X_CLIENT X_LEG X_RUN X_CLASS
  while :; do
    now=$(date +%s)
    live=0
    for L in "$leases"/*; do
      [ -f "$L" ] || continue
      case "${L##*/}" in .*) continue ;; esac
      read -r X_REQ X_ATT X_PG X_CLIENT X_LEG X_RUN X_CLASS < "$L" || continue
      # THE SAME THREE QUALIFIERS THE ADMISSION COUNT APPLIES, in the same order and for the same
      # reasons: a lease with no readable client is left alone (we cannot evaluate the condition),
      # this request's own leases are skipped (a land never starves itself, and a Stage-6's own two
      # legs are not lands), and only a LIVE client counts (an orphan lease is the sweep's business,
      # never a starver). An unrecognised class is NOT read as `land`: over-crediting is the one
      # direction that could extend a genuinely hung file's bound.
      [ -n "${X_CLIENT:-}" ] || continue
      [ "$X_REQ-$X_ATT" = "$me" ] && continue
      [ "${X_CLASS:-}" = land ] || continue
      kill -0 "$X_CLIENT" 2>/dev/null || continue
      live=1
      break
    done
    if [ "$live" = 1 ]; then
      [ -n "$open" ] || open=$now
      printf '%s%s %s\n' "$closed" "$open" "$now" > "$file.tmp"
    else
      if [ -n "$open" ]; then
        closed="$closed$open $now
"
        open=
      fi
      printf '%s' "$closed" > "$file.tmp"
    fi
    mv -f "$file.tmp" "$file"
    # THE RELAY, every 30s and only once there is something to say. `total` is summed from the file
    # just written, so the number the local bound extends by and the number the runner's own reader
    # sees come from ONE record — there is no second accounting to drift.
    if [ $((beat % 30)) -eq 0 ]; then
      total=$(awk '{ s += $2 - $1 } END { printf "%.0f", s + 0 }' "$file" 2>/dev/null || echo 0)
      [ "${total:-0}" -gt 0 ] 2>/dev/null &&
        echo "venue_land_overlap request=$me leg=$leg overlap_s=$total" >&2
    fi
    sleep "$interval"
    beat=$((beat + interval))
  done
}
"""


_BOX_LEG_TEMPLATE = r"""#!/bin/bash
# usage: box-leg.sh <leg> <workers> <request> <attempt> [nice]   — generated by bin/lib/remote_verify.py
set -uo pipefail
LEG=$1; W=$2; REQ=$3; ATT=$4; NICE=${5:-0}
# THE CLIENT HANDLE, taken FIRST: over ssh this script's parent is the sshd session process, which
# exits when the client disconnects — so a later pass can ASK whether this run's client is still
# there rather than assume it is not (rule 4's `whose client is gone`). Taken before any subshell,
# because $PPID after one names the subshell's parent, not ours.
CLIENT=$PPID
# EVERYTHING THIS PASS OWNS IS KEYED BY REQUEST+ATTEMPT (rule 4, T-12220) — the lease, the leg
# checkout, its outputs, this pass's shipped inputs and its envelope. Two passes on one box therefore
# contend for CPU and for nothing else; before this, both `cand` legs shared one checkout and one
# lease and the second start killed the first (measured, T-12199).
RUN=%(runs)s/$REQ-$ATT; D=$RUN/$LEG; OUT=$RUN/out-$LEG
LEASES=%(leases)s; LEASE=$LEASES/$REQ-$ATT-$LEG
# ...AND SO ARE THE TREES IT CHECKS OUT (T-12247). The shipper pushed this pass's candidate and main
# to these two refs and read them back; the leg checks out the SAME two. They are spelled from $REQ
# and $ATT exactly as `box_ref` spells them in Python — validated there, never rewritten, so the two
# sides cannot name different refs for one pass. Before this, both sides named ONE shared
# `refs/venue/cand` that every request force-pushed, and the checkout below happened AFTER the
# admission wait — a second and much wider window on the same race the read-back caught.
CANDREF=refs/venue/$REQ-$ATT/cand; MAINREF=refs/venue/$REQ-$ATT/main
rm -rf "$OUT"; mkdir -p "$OUT"
# THE QUIET-POINT BARRIER (T-12377). Both legs of one pass share `$RUN/quiet`; each leg writes its
# OWN pid there FIRST (before the admission wait, so the sibling can always resolve it), and the
# shipped runner writes `<leg>.pool-drained` when its pool drains and HOLDS its T-12357 isolated
# re-run until the sibling's marker exists or the sibling pid is gone (`verify_runner
# .QUIET_BARRIER_DIR_ENV` + siblings). EXPORTED ONLY WHEN THIS PASS HAS A SIBLING LEG: `VENUE_LEGS`
# is what `run_legs` started (a land: `cand pinned`; a Stage-6 candidate-only pass: `cand`), so a
# single-leg pass gets no barrier and its retry runs exactly as before this card. The sibling pid is
# read here as a convenience; the two legs start together, so it is usually still absent at this
# line and the runner falls back to `$Q/$SIB.pid` at wait time. Every step is `|| true`: the barrier
# is an ORDERING, never a verdict.
Q=$RUN/quiet; mkdir -p "$Q" 2>/dev/null || true
echo $$ > "$Q/$LEG.pid" 2>/dev/null || true
case "$LEG" in cand) SIB=pinned ;; pinned) SIB=cand ;; *) SIB= ;; esac
case " ${VENUE_LEGS:-cand pinned} " in
  *" $SIB "*) [ -n "$SIB" ] || SIB= ;;
  *) SIB= ;;
esac
if [ -n "$SIB" ]; then
  export YITC_VERIFY_QUIET_BARRIER_DIR=$Q
  export YITC_VERIFY_QUIET_LEG=$LEG
  export YITC_VERIFY_QUIET_SIBLING=$SIB
  export YITC_VERIFY_QUIET_SIBLING_PID=$(cat "$Q/$SIB.pid" 2>/dev/null || true)
fi
# PHASE CLOCK. The leg's own `wall_s` measures the RUN; the difference between it and the
# both-legs wall is the SETUP, and an unnamed setup cost cannot be argued about — it can only be
# guessed at. Each phase stamps a line, so the envelope carries where the setup time actually went.
T_START=$(date +%%s.%%N)
phase() { echo "$1 $(date +%%s.%%N)" >> "$OUT/phases.txt"; }
phase start
%(lease_prologue)s
# THE PER-REQUEST LEG WORKTREE (rule 4, T-12220). The dir is fresh by construction, so the checkout
# is always a `worktree add`. THIS RETIRES the T-12199 persistent-worktree reuse (`reset --hard` +
# `clean -xfd` over one shared checkout per leg): that optimisation and per-request isolation are the
# same resource asked to be two things, and the measurement decided it — a shared checkout is reset
# out from under a concurrent run. The cost is a full checkout per pass instead of a delta, paid
# SYMMETRICALLY by a solo and an overlapped pass, and visible in this leg's own `phases` clock.
# `worktree prune` runs first because the sweep above may have removed a run dir whose worktree
# registration the clone still holds.
phase checkout
git -C %(repo)s worktree prune
rm -rf "$D"; git -C %(repo)s worktree add -q -f --detach "$D" "$CANDREF"
[ "$LEG" = pinned ] && git -C "$D" checkout -q "$MAINREF" -- tests/

# Fault injection, rehearsal only (AC3 probe 3): corrupt the WORKING TREE *after* checkout. The
# envelope's identity must notice — `HEAD^{tree}` does not, `write-tree` of the working tree does.
if [ -n "${VENUE_CORRUPT:-}" ] && [ "$LEG" = cand ]; then
  printf '\n# CORRUPTED AFTER CHECKOUT — rehearsal fault injection\n' >> "$D/$VENUE_CORRUPT"
  echo "corrupted $VENUE_CORRUPT" > "$OUT/corrupt.txt"
fi

phase identity
ulimit -n %(nofile)d || true
cd "$D"

# IDENTITY = the tree that RUNS. Taken BEFORE anything else writes into the checkout (the session
# start below appends to the tracked events.jsonl), over a TEMPORARY index so the leg's real index is
# untouched.
WT_TREE=$(GIT_INDEX_FILE="$OUT/wt.index" git add -A . >/dev/null 2>&1; \
          GIT_INDEX_FILE="$OUT/wt.index" git write-tree)
echo "$WT_TREE" > "$OUT/wt-tree.txt"
# The runner identity, from the SAME ref git already holds — no second hashing scheme (rule 4).
git rev-parse HEAD:bin > "$OUT/runner-digest.txt"

# The v2 session this checkout runs under. The ref is MINTED here and carried; a FABRICATED carry is
# unbacked under SPEC-0137 and made ~21 gated tests read as host-sensitive (trial cycle 4).
phase session
unset YITC_SESSION_REF YITC_EXPECTED_SESSION_REF
REF=$(bin/yitc-v2 session start 2>&1 | sed -n 's/.*YITC_SESSION_REF=\([0-9a-f-]*\).*/\1/p' | head -1)
export YITC_SESSION_REF=$REF
echo "$REF" > "$OUT/session-ref.txt"
# THE VERB-INVENTORY SCAN, the startup step every other session takes (SPEC-0050 §2/§4). The gate
# `_require_help_read` credits a `--help` fetch-receipt only inside the window anchored by THIS
# session's own `session_started` AND only when its producer recorded `stdout_delivered` true. The
# leg had the ANCHOR and no RECEIPT, so every test whose subject runs the host residue
# `cmd_worktree_new` — tests/test_t9340_worktree_extraction_adoption.py — died on the gate in EVERY
# box pinned leg (measured: the T-12299 land, envelope 6df7281cdcc1-1, legs/pinned/failing, with no
# assertion to capture), and each land on the box needed a file-level rebaseline waive.
# STDOUT GOES TO A REAL FILE, NEVER /dev/null. `_stdout_was_delivered` discriminates on THE NULL
# DEVICE (not `isatty()`), and since T-11411 `_fetched_spec_ids` SKIPS a receipt recorded
# `stdout_delivered: False` — so `--help >/dev/null` writes a receipt that grants no pass. That is
# not a hypothetical: it is the T-11576 / X-1101 incident, where the redirected cure was run twice
# and earned the identical refusal. A regular file answers DELIVERED.
# IT CANNOT FAIL THE LEG. This is an identity step, never a verdict — `|| true` and a discarded
# stderr mean it can only ever ADD a receipt.
bin/yitc-v2 --help > "$OUT/help.txt" 2>/dev/null || true
# The v2 worktree STAMP (SPEC-0137 selector 2) — written by the SHIPPED TREE'S OWN writer, never by a
# hand-rolled copy of the format. 21 real tests reset the journal and resolve their session only
# through this stamp; a raw `git worktree add` writes none, so they read as host-sensitive on ANY
# unstamped checkout — the engine's own `main` included (trial cycles 5-6).
python3 - > "$OUT/stamp.txt" 2>&1 <<'PYSTAMP'
import importlib.util, pathlib, sys
from importlib.machinery import SourceFileLoader
root = pathlib.Path.cwd()
sys.path[:0] = [str(root / "bin"), str(root / "bin" / "lib")]
spec = importlib.util.spec_from_loader("y", SourceFileLoader("y", str(root / "bin/lib/cli.py")))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
print("stamp:", m._write_worktree_stamp(m.REPO_ROOT))
PYSTAMP

# The tmpfs lever (owner directive) and the per-file outcome sidecar dir (T-12190). Both are EXPORTS
# the runner already reads — neither is a patch, and neither is a gate: an absent or unwritable tmpfs
# root falls back to the platform default with one reported line.
phase stamp
mkdir -p %(tmpdir_root)s 2>/dev/null || true
export YITC_VERIFY_TMPDIR=%(tmpdir_root)s
export YITC_VERIFY_OUTCOMES_DIR=$OUT

phase run_begin
# THE LAND-OVERLAP POLLER (T-12260) — started HERE, the first moment the leg owns the box's CPU
# alongside whatever else holds it, and stopped the moment the run ends. `OVERLAP` is exported under
# the name the shipped runner reads (`verify_runner.LAND_OVERLAP_FILE_ENV`), so the per-file bound
# inside THIS leg is uncharged for contention this loop measured; the file is also read once more
# below for the envelope. Started with `|| true` so a shell that cannot fork the poller loses the
# measurement and nothing else — the runner then reads an absent file, credits 0, and the bound is
# exactly what it was before this card.
%(overlap_poller)s
OVERLAP=$OUT/land-overlap.txt
: > "$OVERLAP"
export YITC_VENUE_LAND_OVERLAP_FILE=$OVERLAP
venue_land_overlap_poll "$OVERLAP" "$REQ-$ATT" "$LEASES" "${VENUE_OVERLAP_POLL_S:-5}" "$LEG" &
OVERLAP_PID=$!
# THE REF SNAPSHOT (T-12262). A leg's suite must not be able to move the box's SHARED refs, and until
# this guard nothing said so out loud: on 2026-09-08 a test fixture's own inner `land` — routed to
# this very venue, because the venue record is resolved off the ENGINE's path and no HOME sandbox can
# move it — force-pushed its two-commit fixture history onto `refs/heads/main` here, and every
# main-consulting test on every later candidate failed structurally with no assertion to capture. The
# isolation that CLOSES that path is in the runner (`hermetic_child_env`); this is the second half:
# the box notices, heals, and REFUSES rather than reporting the wreckage as test failures.
# EVERY non-`refs/venue/*` ref is snapshotted — the transport refs are the ones this pass legitimately
# writes, so they are the only exclusion. Best-effort throughout: a guard that can abort a healthy
# pass would be worse than the fault it guards, so a snapshot that cannot be taken leaves the file
# ABSENT, which the reader below reports as `null` (unknown) rather than as `[]` (clean).
# WRITE-THEN-RENAME, and the reason is the difference between `[]` and `null`. A bare
# `git ... > "$OUT/refs-before.txt" || true` CREATES the file the moment the shell opens the
# redirect, BEFORE git runs — so a failing snapshot leaves an EMPTY file, the reader parses an empty
# before-map, and every existing ref reads as newly ADDED: a FALSE CLOBBER that refuses honest
# passes, and the exact opposite of the three-valued promise. The rename runs only on a successful
# read, so a snapshot that could not be taken leaves NO file at all, which the reader reports as
# `null` (unknown) — the only honest answer there. `grep -v` exiting 1 on an all-filtered set is not
# a failure, so the git exit status is the one consulted.
if git -C %(repo)s for-each-ref --format='%%(refname) %%(objectname)' > "$OUT/refs-before.tmp" 2>/dev/null; then
  grep -v '^refs/venue/' "$OUT/refs-before.tmp" > "$OUT/refs-before.txt" || true
fi
rm -f "$OUT/refs-before.tmp"
# THE RUN. The shipped tree's OWN runner, in a fresh interpreter, with an EXPLICIT worker count — the
# runner's governor applies only when `workers is None`, so no source patch is needed to reach W and
# the runner digest above stays equal to the one `land` computes locally.
# LOWER PRIORITY, MECHANISM 2 OF 2 (T-12199). `nice` is applied to the runner invocation itself so a
# Stage-6 pass sharing the box with a land yields CPU to it; the value is RECORDED below out of
# `os.nice(0)`, i.e. the priority the process ACTUALLY ran at, never the one the caller asked for.
nice -n "$NICE" python3 - "$LEG" "$W" "$REQ" "$ATT" "$OUT" "$RUN/exclude.json" "$RUN/only.json" %(repo)s "$MAINREF" "$RUN/pinned_skip.json" <<'PYRUN'
import json, os, pathlib, subprocess, sys, time
leg, W, req, att, out, exclude_path, only_path, repo_git, main_ref, pinned_skip_path = sys.argv[1:11]
root = pathlib.Path.cwd(); sys.path.insert(0, str(root / "bin"))
# T-12438 - the verify-leg binder moved from lib/cli.py to lib/verify_wiring.py and now takes the CLI
# module's globals EXPLICITLY. The SHIPPED tree may be either vintage (the pinned leg ships last-green,
# which is PRE-move on the first land carrying that change), so resolve both, prefer the new home, and
# fail the leg LOUD, naming the symbol and both places looked, when neither holds the runner.
if (root / "bin" / "lib" / "verify_wiring.py").exists():
    import functools
    from lib import cli as _cli                   # noqa: E402  (path must be set up first)
    from lib import verify_wiring as _vw          # noqa: E402
    _run_verify_tests = functools.partial(_vw._run_verify_tests, _host_globals=vars(_cli))
else:
    try:
        from lib.cli import _run_verify_tests    # noqa: E402  (the PRE-move vintage)
    except ImportError as _e:
        raise SystemExit("PYRUN: no `_run_verify_tests` in the shipped tree - looked in "
                         + str(root / "bin" / "lib" / "verify_wiring.py") + " and lib.cli (" + str(_e) + ")")
metrics, durations = {}, []


# T-12357 - this leg's isolated-retry record, with `leg` stamped onto each row. Inline here rather
# than imported, deliberately: it is three lines, and this script's only import from the shipped tree
# is the runner itself - widening that surface to carry a formatting helper would make the leg script
# depend on one more symbol existing in whatever tree was shipped. (A COMMENT and not a docstring
# because this whole script is a triple-quoted Python string in the host module, so a nested
# triple-quote would terminate it.) Returns None unchanged when the runner recorded nothing, so the
# key is written on every leg and an ABSENT key means only: this envelope predates the field.
def _flaky_retry_leg_stamped(rec, leg_name):
    if not isinstance(rec, dict):
        return None
    for r in (rec.get("rows") or []):
        if isinstance(r, dict):
            r["leg"] = leg_name
    return rec


# SPEC-0203 rule 8 — the shipped runner is narrowed with its OWN `only=` parameter to DISCOVERED
# MINUS EXCLUDED, so the host-sensitive local-probe files never run on the box. An absent or
# unreadable file excludes NOTHING (the whole discovered suite runs remotely), which is the
# fail-safe direction: a broken artifact can never EXCUSE a file from the verdict.
discovered = sorted(p.name for p in (root / "tests").glob("test_*.py"))
# EXPANDUSER, and the read outcome is RECORDED. The path arrives as the venue dir's `~/venue/...`
# spelling, which `open()` does NOT expand — the first real box pass silently ran the whole suite
# including every host-sensitive file, because the fail-safe branch below cannot tell a missing file
# from an unexpanded one. So the tilde is expanded here, and `exclude_read` travels in `leg.json`:
# a partition that did not take effect is now a visible field, not an inference from the failures.
exclude_path = os.path.expanduser(exclude_path)
excluded, exclude_read = [], "ok"
try:
    excluded = [n for n in (json.load(open(exclude_path)) or []) if isinstance(n, str)]
except Exception as e:
    excluded, exclude_read = [], f"{type(e).__name__}: {e}"
# SPEC-0181 / T-12222 — the GOVERNED SELECTION, decided by the local path and CARRIED here. It
# names the files this pass would have run locally, so a routed land pays the same suite the local
# land would, not the whole discovered set. TWO bounds, both by construction:
#   - THE CANDIDATE LEG ONLY. SPEC-0181 R1 states the rule never narrows the PINNED last-green
#     pass, so a non-`cand` leg ignores the file entirely and keeps running discovered-minus-
#     excluded. The bound is enforced HERE, on the box, rather than trusted of the caller.
#   - FAIL-SAFE IN THE SAME DIRECTION AS `exclude`. Absent, unreadable or JSON `null` selects
#     NOTHING away (the whole discovered set runs). A broken artifact can only ever run MORE tests,
#     never excuse one from the verdict — the property the whole partition rests on.
selected, only_read = None, "ok"
if leg == "cand":
    try:
        _raw = json.load(open(os.path.expanduser(only_path)))
        # A READABLE selection binds ONLY when it is well-formed: a NON-EMPTY list of strings, every
        # one a DISCOVERED test file. Anything else is a BROKEN artifact, not a narrower one, and it
        # falls to the FULL discovered suite exactly as `governed_selection` falls for
        # `empty-selection` / `tripwire-error` on the local path (consult T-12222/post/1 B1, 2026-09-07):
        # the previous reading DROPPED a non-string member and let the intersection DROP an unknown
        # name, so `["test_a.py", 123]` narrowed to one file and `["test_missing.py"]` narrowed to
        # NOTHING — a runner asked for zero files answers green, the fail-open this closes. The reason
        # travels in `only_read` so a selection that did not take effect is a visible field.
        if _raw is None:
            selected = None
        elif not isinstance(_raw, list):
            selected, only_read = None, f"invalid-selection: not a list ({type(_raw).__name__})"
        elif not _raw:
            selected, only_read = None, "invalid-selection: empty list (falls to the full suite)"
        elif not all(isinstance(n, str) for n in _raw):
            selected, only_read = None, "invalid-selection: non-string member"
        elif not set(_raw) <= set(discovered):
            _unknown = sorted(set(_raw) - set(discovered))[:5]
            selected, only_read = None, f"invalid-selection: not discovered here: {_unknown}"
        else:
            selected = sorted(set(_raw))
    except Exception as e:
        selected, only_read = None, f"{type(e).__name__}: {e}"
else:
    only_read = "skipped-non-cand-leg"
# SPEC-0077 §3 / T-12250 — THE PINNED LEG RUNS ONLY TESTS THAT EXISTED AT LAST-GREEN. The overlay
# above (`git checkout $MAINREF -- tests/`) RESTORES last-green's files but DELETES none, so every
# test the candidate ADDED survived into the pinned tree and ran there against last-green's helpers
# — ImportError, or "no assertion captured", on a file that by definition is not a pinned check.
# Measured: T-12239 03:48Z, T-12232 02:01Z, T-12221, each a full verify + a rebaseline token round +
# an owner ACK. This is the box-side half of the LOCAL prune `_pinned_candidate_added_paths` has done
# since T-11253/X-0979 — the same derivation, not a second rule, and the reason it had to be written
# twice is that T-12254 routed the pinned leg here, where that prune does not run.
#
# DERIVED FROM THE REF'S OWN TREE LISTING, never a hand-kept manifest (the auditor's named simpler
# alternative, declined for exactly that reason): `git ls-tree` at THIS REQUEST's own `$MAINREF` IS
# the last-green manifest, with no second store to keep in step. Expressed as a DISCOVERY skip rather
# than an unlink because the box leg already narrows through `only=` — no new runner parameter, the
# same seam SPEC-0203 rule 8 and SPEC-0181 R1 pass through.
#
# FAIL-SAFE IN THE SAME DIRECTION AS `exclude` AND `only`: any git failure, any parse failure, leaves
# `not_pinned` EMPTY, which runs MORE tests, never fewer. A broken derivation can only ever cost a
# false RED that a human reads — it can never EXCUSE a genuine last-green check from the verdict,
# which is the property the whole pinned leg rests on. The outcome travels in `not_pinned_read`, so a
# derivation that did NOT take effect is a visible field rather than an inference from the failures.
#
# THE CANDIDATE LEG IS UNTOUCHED, and the bound is enforced HERE, box-side, rather than trusted of
# the caller — exactly as SPEC-0181 R1's selection bound is: a non-`pinned` leg computes nothing and
# is byte-identical to before this card. A branch-only test still runs in FULL in the candidate leg.
not_pinned, not_pinned_read = [], "skipped-non-pinned-leg"
if leg == "pinned":
    try:
        _lt = subprocess.run(["git", "ls-tree", "-r", "--name-only", "-z", main_ref, "--", "tests"],
                             cwd=str(root), capture_output=True, text=True)
        if _lt.returncode != 0:
            raise RuntimeError((_lt.stderr or _lt.stdout or "").strip()[:200] or "nonzero exit")
        _lastgreen = {pathlib.PurePosixPath(n).name for n in _lt.stdout.split("\0") if n}
        if not _lastgreen:
            # An EMPTY listing is not "everything is branch-only" — it is a ref that told us nothing,
            # and acting on it would exclude the ENTIRE pinned suite, which reads GREEN. Same shape as
            # the local driver's degenerate-case rule and the `only` empty-selection fall-through.
            raise RuntimeError(f"{main_ref}:tests listed no files")
        not_pinned = sorted(n for n in discovered if n not in _lastgreen)
        not_pinned_read = "ok"
    except Exception as e:
        not_pinned, not_pinned_read = [], f"{type(e).__name__}: {e}"
base = set(discovered) if selected is None else (set(selected) & set(discovered))
# SPEC-0077 §3 / T-12313 — THE PINNED-LEG NARROWING, COMPUTED ON THE HOST AND ONLY APPLIED HERE.
# T-12307 stopped re-running two classes of pinned copy — a test the LAST-GREEN copy declares
# census/inventory-class, and a test THIS branch's own diff touched without weakening — but it put
# that computation inside `_run_pinned_verify`, which a ROUTED land never calls. So on the venue the
# narrowing happened NOWHERE (neither host nor box) and every land re-ran the stale copy and paid a
# rebaseline round. The host now computes it with the SAME `pinned_leg_narrowing()` the local driver
# calls and ships the names; this block only APPLIES them. Deliberately NOT re-derived here: a
# narrowing spelled twice drifts, and the host's `meta` (which file, which reason) has no box-side
# source at all.
#
# THE PINNED LEG ONLY. A non-`pinned` leg reads the file not at all — the mirror of `only.json`'s
# cand-leg bound, enforced HERE rather than trusted of the caller, for the same reason.
#
# FAIL-SAFE IN THE SAME DIRECTION AS `exclude`, `only` AND `not_pinned`: absent, unreadable,
# not-a-list or a non-string member skips NOTHING (the leg runs whole). A broken artifact can only
# ever run MORE tests, never excuse one from the verdict.
#
# AND THE SUBTRACTION IS DROPPED WHOLE IF IT WOULD EMPTY THE SELECTION — an empty selection reads
# GREEN, i.e. silently disables this leg, which is the local driver's own degenerate-case rule and
# the property SPEC-0181 R1's bound rests on. The outcome travels in `pinned_skip_read` and the
# APPLIED names in `pinned_skipped`, so a narrowing that did not take effect is a visible field
# rather than an inference from the failures.
pinned_skip, pinned_skip_read, pinned_skipped = [], "skipped-non-pinned-leg", []
if leg == "pinned":
    pinned_skip_read = "ok"
    try:
        _raw = json.load(open(os.path.expanduser(pinned_skip_path)))
        if not isinstance(_raw, list):
            pinned_skip, pinned_skip_read = [], f"invalid-skip: not a list ({type(_raw).__name__})"
        elif not all(isinstance(n, str) for n in _raw):
            pinned_skip, pinned_skip_read = [], "invalid-skip: non-string member"
        else:
            pinned_skip = sorted(set(_raw))
    except Exception as e:
        pinned_skip, pinned_skip_read = [], f"{type(e).__name__}: {e}"
if pinned_skip:
    _would_run = base - set(excluded) - set(not_pinned)
    _after = _would_run - set(pinned_skip)
    if _after:
        pinned_skipped = sorted(_would_run & set(pinned_skip))
    else:
        pinned_skip_read = "not-applied: would leave the pinned selection EMPTY (reads GREEN)"
only = (sorted(base - set(excluded) - set(not_pinned) - set(pinned_skipped))
        if (excluded or selected is not None or not_pinned or pinned_skipped) else None)
t0 = time.monotonic()
_ov_t0 = time.time()          # T-12260: the run window, in the sidecar's own EPOCH units
try:
    bad = _run_verify_tests(root / "tests", root, int(W), fail_fast=False,
                            metrics_out=metrics, durations_out=durations,
                            **({"only": set(only)} if only is not None else {}))
    launch_error = None
except Exception as e:                            # a leg that cannot START is a venue fault, not a
    bad, launch_error = [], f"{type(e).__name__}: {e}"   # test failure — say so, never fabricate a pass.
wall = round(time.monotonic() - t0, 1)
# T-12260 — HOW LONG A FOREIGN LAND HELD THIS BOX DURING THIS LEG'S RUN. Computed by IMPORTING the
# runner's own summer rather than re-summing the sidecar here: the number the per-file bound was
# uncharged by and the number the envelope reports must come from ONE parser, or the envelope can
# say a leg was never starved by time the bound already gave back. Fail-safe to None (unknown), not
# to 0.0 — "no land overlapped" and "we could not tell" are different facts, the same distinction
# the admission figures beside it keep.
try:
    from lib.verify_runner import _land_overlap_seconds as _ov_sum      # noqa: E402
    # WHOLE SECONDS, and the type is deliberate rather than cosmetic: the box writes its sidecar in
    # integer epoch seconds, so an int is the honest precision here — AND `_leg_fold`, the reader on
    # the other side of the envelope, admits only `int` (it rejects `bool` and anything non-integral
    # so a flag can never be scored as a duration). A float here would be silently DROPPED by that
    # fold and the metric would read None on every pass, which is the failure mode that makes this
    # worth a sentence.
    venue_overlap_land_s = int(round(_ov_sum(_ov_t0, time.time(),
                                             os.environ.get("YITC_VENUE_LAND_OVERLAP_FILE"))))
except Exception:
    venue_overlap_land_s = None
failing = sorted({str(b).split("\n", 1)[0] for b in bad})
# THE REF CHECK (T-12262), the other half of the snapshot taken before this run. Read the same
# non-transport ref set back, name every ref whose oid MOVED (or that appeared / vanished), and heal
# `refs/heads/main` from THIS request's own main ref — the only sha this leg can name truthfully, so
# a leg never invents one and an unresolvable `main_ref` restores NOTHING while still reporting.
# THREE-VALUED BY CONSTRUCTION: `[]` = checked and clean, a list = these refs moved, `None` = the
# snapshot could not be taken. "Unknown" and "clean" are different facts and only one of them is an
# empty list — the same discipline the admission figures above keep.
def _refs_now():
    r = subprocess.run(["git", "-C", repo_git, "for-each-ref",
                        "--format=%%(refname) %%(objectname)"], text=True, capture_output=True)
    if r.returncode != 0:
        return None
    out_map = {}
    for line in r.stdout.splitlines():
        name, _, oid = line.partition(" ")
        if name and not name.startswith("refs/venue/"):
            out_map[name] = oid.strip()
    return out_map
# THE RESTORE IS PROVEN, NOT ASSUMED (T-12284, consult findings B1/B2/B3 — ONE root). The moved set
# alone cannot admit a re-attempt: it says WHAT moved, never whether the box is back to the state
# this leg found. Three ways it is not, all measured off the T-12262 predicate: `main_ref` does not
# resolve or `update-ref` fails, so main is STILL wrong (B1); a moved ref that is neither
# `refs/heads/main` nor `refs/venue/*` — a stray `refs/tags/salvage/tmp-1` — is named but never
# restored, because this request's own refs cannot name a truthful sha for it (B2); or the snapshot
# itself failed, so there is no baseline to compare against at all (B3). In every one of those a
# retry would take the CORRUPTED state as its own baseline, report clean, and can return GREEN over
# a box that is still wrong. So the leg RE-READS the refs after restoring and reports whether every
# ref in the moved set is back, BYTE-IDENTICAL to its pre-run snapshot.
# THREE-VALUED, like the moved set beside it: True = every moved ref compares equal to `before`;
# False = at least one does not; None = we could not tell (no snapshot, or the re-read failed).
# Only True admits the caller's single re-attempt — None never reads as True, which is the whole
# fail-closed direction this key exists for.
venue_refs_moved = None
venue_refs_restored = None
# A MIRROR ADVANCE IS NOT A CLOBBER (T-12301). The two facts the guard above cannot tell apart are
# «somebody overwrote the shared main with an unrelated history» and «somebody FAST-FORWARDED the
# shared main to a DESCENDANT of what this very request already carries». The first is the measured
# T-12262 incident. The second is a MIRROR — the box's clone catching up with the host — and it
# harms nothing this pass reads: every leg checks out KEYED refs and the pinned overlay comes from
# this request's OWN keyed main, so an advanced `refs/heads/main` is not an input to any verdict
# here. Measured 2026-09-09T09:35Z: a candidate mirrored host main onto this box while a concurrent
# land held a live leg, and that land ABORTED `venue-refs-clobbered` over a box that was fine.
# WORSE THAN THE FALSE REFUSAL IS THE HEAL. The restore below forces main back to THIS request's
# main — so under two live requests each would drag the shared ref back to its own older sha, a
# ping-pong that leaves the box permanently behind whichever request last finished.
# FAIL-CLOSED BY CONSTRUCTION, and this is the property to keep when editing: ONLY A POSITIVE
# ANCESTRY PROOF suppresses. An unresolvable `main_ref`, a `refs/heads/main` that is absent after the
# run (a DELETION), a non-descendant sha, or a git call that cannot answer all fall to today's path
# byte-for-byte — listed as moved, healed to ours, refused as `venue-refs-clobbered` by the host.
# `None` here is not a third state: it is "no mirror was recognised", which is the safe direction.
venue_main_mirrored = None
try:
    before = {}
    with open(out + "/refs-before.txt") as fh:
        for line in fh:
            name, _, oid = line.strip().partition(" ")
            if name:
                before[name] = oid.strip()
    after = _refs_now()
    if after is not None:
        venue_refs_moved = sorted(n for n in set(before) | set(after)
                                  if before.get(n) != after.get(n))
        if "refs/heads/main" in venue_refs_moved:
            want = subprocess.run(["git", "-C", repo_git, "rev-parse", main_ref],
                                  text=True, capture_output=True).stdout.strip()
            after_main = after.get("refs/heads/main")
            # EQUAL FIRST, then ANCESTRY. The equality arm is not an optimisation: `merge-base
            # --is-ancestor X X` does exit 0, but reading the answer off a string comparison keeps
            # the commonest case (the box already carries exactly our main) independent of whether
            # the object is present and readable in this clone.
            mirrored = bool(want) and bool(after_main) and (
                after_main == want
                or subprocess.run(["git", "-C", repo_git, "merge-base", "--is-ancestor",
                                   want, after_main], capture_output=True).returncode == 0)
            if mirrored:
                # NOT MOVED, NOT HEALED, but RECORDED. Dropping it from the moved set is what keeps
                # `envelope_refs_clobbered` PURE and untouched one layer up — the classifier reads
                # the list, and a mirror is simply no longer in it.
                venue_main_mirrored = {"from": before.get("refs/heads/main"), "to": after_main}
                venue_refs_moved = [n for n in venue_refs_moved if n != "refs/heads/main"]
            elif want:
                subprocess.run(["git", "-C", repo_git, "update-ref", "refs/heads/main", want],
                               capture_output=True)
        if not venue_refs_moved:
            venue_refs_restored = True            # nothing moved — nothing to put back
        else:
            healed = _refs_now()                  # the PROOF read, after the restore above
            venue_refs_restored = (None if healed is None else
                                   all(healed.get(n) == before.get(n) for n in venue_refs_moved))
except Exception:          # a guard that can fail the leg is worse than the fault it guards
    venue_refs_moved = None
    venue_refs_restored = None
    venue_main_mirrored = None
# THE ADMISSION RECORD (SPEC-0203 rule 4), read back from the file the prologue wrote before this leg was
# admitted. Unreadable or malformed -> None on all three, never a fabricated 0: "this leg did not
# wait" and "we do not know whether it waited" are different facts, and only the first is a zero.
try:
    _adm = open(out + "/venue-wait.txt").read().split()
    _waited, _cap, _atomic = int(_adm[0]), int(_adm[1]), int(_adm[2])
    # LENGTH-TOLERANT ON PURPOSE (T-12259): the class and the live-Stage-6 count are read only if the
    # record carries them, so a leg reading a record written by an older prologue reports them ABSENT
    # rather than raising and losing the three figures that ARE there.
    _class = _adm[3] if len(_adm) > 3 else None
    _live_s6 = int(_adm[4]) if len(_adm) > 4 else None
    # THREE STATES, not two (T-12259): the reason token when the box's load could not be read,
    # False when it WAS read, None when this record predates the field. "we measured headroom" and
    # "we do not know whether we did" are different facts, exactly as with the figures above.
    _deg = (None if len(_adm) <= 5 else (False if _adm[5] == "-" else _adm[5]))
except Exception:
    _waited = _cap = _atomic = _class = _live_s6 = _deg = None
import resource
json.dump({"leg": leg, "workers_requested": int(W), "workers_in_effect": metrics.get("worker_count"),
           "request": req, "attempt": int(att), "wall_s": wall,
           "runner_digest": open(out + "/runner-digest.txt").read().strip(),
           "worktree_tree": open(out + "/wt-tree.txt").read().strip(),
           "session_ref": open(out + "/session-ref.txt").read().strip(),
           "test_file_count": metrics.get("test_file_count"),
           "per_file_outcomes": metrics.get("per_file_outcomes"),
           # T-12357 — WHAT THIS LEG'S ISOLATED RETRY DID, leg-stamped here on the box (the runner
           # does not know its leg; the caller does — the same rule the local candidate leg follows).
           # The key is written on EVERY leg, so a leg that ran with no flake records it as null
           # ("no flakes") and ONLY an old-shape envelope lacks the key at all — which is what lets
           # the host fold below tell "no flakes" from "we do not know" (SPEC-0165 item 11).
           "venue_flaky_retry": _flaky_retry_leg_stamped(metrics.get("flaky_retry"), leg),
           # T-12358 — WHAT THIS LEG'S SERIALIZED TAIL DID. The shipped runner read the tree's own
           # `tests/load-sensitive.txt` and ran every listed file alone AFTER its pool, so the tail
           # exists on this leg by construction; this key carries its per-file results out. Written
           # on EVERY leg on the same terms as `venue_flaky_retry` above: null = "no set / nothing
           # listed" and ONLY an old-shape envelope lacks the key — which is what lets the host fold
           # tell "no tail" from "we do not know" (SPEC-0165 item 11).
           "venue_load_sensitive": metrics.get("load_sensitive"),
           # T-12447 — THE LAST OUTPUT OF EACH FILE THIS LEG STILL FAILS ON, from the shipped runner
           # (`failed_output_tail`: <=40 lines per file, <=20 entries, absent on a green run). Before
           # it the only failure text this record carried was `failing` below, the first line per
           # file, and a routed abort read «(no assertion captured)» with nothing else to go on.
           "venue_failed_output_tail": metrics.get("failed_output_tail"),
           "verify_tmpdir": __import__("os").environ.get("YITC_VERIFY_TMPDIR"),
           "phases": [l.split() for l in open(out + "/phases.txt").read().splitlines()],
           "venue_refs_moved": venue_refs_moved,
           "venue_refs_restored": venue_refs_restored,
           "venue_main_mirrored": venue_main_mirrored,
           "venue_requests_waited_s": _waited, "venue_max_requests": _cap,
           "venue_admission_atomic": _atomic,
           "venue_admission_class": _class, "venue_live_stage6": _live_s6,
           "venue_overlap_land_s": venue_overlap_land_s,
           "venue_headroom_degraded": _deg,
           "nofile_in_effect": resource.getrlimit(resource.RLIMIT_NOFILE)[0],
           "nice_in_effect": os.nice(0),
           "excluded_count": len(excluded), "only_count": (len(only) if only is not None else None),
           "exclude_read": exclude_read, "discovered_count": len(discovered),
           "excluded_not_pinned": not_pinned, "not_pinned_count": len(not_pinned),
           "not_pinned_read": not_pinned_read,
           "pinned_skipped": pinned_skipped, "pinned_skip_read": pinned_skip_read,
           "selected_count": (len(selected) if selected is not None else None),
           "only_read": only_read,
           "failing_count": len(failing), "failing": failing,
           "launch_error": launch_error},
          open(out + "/leg.json", "w"))
PYRUN
# The poller's whole job is done: the run is over, so further overlap is not this leg's to be
# uncharged for. Best-effort, like every teardown here — it is in this leg's process group and dies
# with it regardless, so a failed kill leaks nothing.
kill "$OVERLAP_PID" 2>/dev/null || true
phase run_end
rm -f "$LEASE"
echo LEG-DONE $LEG
"""


def box_lease_prologue(max_requests: "int | None" = None, *,
                       stage6_max_concurrent: "int | None" = None,
                       stage6_headroom_load1: "float | None" = None,
                       fingerprint: "dict | None" = None) -> str:
    """The lease + admission prologue TEXT with the three admission parameters RESOLVED into it
    (T-12241, extended by T-12259 to the by-class question).

    They are substituted by `str.replace`, NOT by `%`-formatting, for the same reason the prologue is
    substituted into the leg template as a VALUE: its own `%` (the `date +%s.%N` phase clock's, among
    others) must never be scanned as format specifiers. Placeholder tokens and a literal replace keep
    that property while still letting the numbers be resolved once, in Python, where they can be
    validated — rather than shelled out to on the box.

    THE HEADROOM IS RESOLVED HERE, NOT ON THE BOX, and that is what makes it honest: `fingerprint` is
    the record this pass was routed under, so an unset knob becomes the EFFECTIVE number derived from
    that box's own cores, and the text a reader inspects carries the value that actually decided.

    Returned as text, and separately from `box_leg_script`, so the concurrency logic is EXECUTABLE
    by a test without a box — the same reason `box_leg_script` returns text at all."""
    cap = venue_max_requests() if max_requests is None else int(max_requests)
    if cap <= 0:                       # same fail-safe direction as the resolver: never uncapped
        cap = VENUE_MAX_REQUESTS_DEFAULT
    s6max = (venue_stage6_max_concurrent() if stage6_max_concurrent is None
             else int(stage6_max_concurrent))
    if s6max <= 0:                     # never a cap of 0: that would DISABLE Stage-6, not slow it
        s6max = VENUE_STAGE6_MAX_CONCURRENT_DEFAULT
    headroom = (venue_stage6_headroom_load1(fingerprint) if stage6_headroom_load1 is None
                else float(stage6_headroom_load1))
    if not (headroom > 0):             # incl. NaN, which compares false against every bound
        headroom = VENUE_STAGE6_HEADROOM_LOAD1_DEFAULT
    return (_BOX_LEASE_PROLOGUE
            .replace("@MAX_REQUESTS@", str(cap))
            .replace("@STAGE6_MAX@", str(s6max))
            .replace("@STAGE6_HEADROOM@", f"{headroom:g}"))


def box_leg_script(*, nofile: int = VENUE_NOFILE, tmpdir_root: str = VENUE_TMPDIR_ROOT,
                   venue_dir: str = BOX_VENUE_DIR, repo_git: str = BOX_REPO_GIT,
                   runs_dir: str = BOX_RUNS_DIR, leases_dir: str = BOX_LEASES_DIR,
                   max_requests: "int | None" = None,
                   stage6_max_concurrent: "int | None" = None,
                   stage6_headroom_load1: "float | None" = None,
                   fingerprint: "dict | None" = None) -> str:
    """The per-leg driver TEXT. Returned rather than written so a test can assert its shape without a
    box — in particular that it exports the tmpfs lever and the outcomes dir, and that it contains no
    `sed`/patch of the shipped tree. W is a runtime ARGUMENT to the script, never baked into its text:
    the same script serves every worker count, so a W change cannot leave a stale copy on the box."""
    return _BOX_LEG_TEMPLATE % {"nofile": nofile, "tmpdir_root": tmpdir_root,
                                "venue": venue_dir, "repo": repo_git,
                                "runs": runs_dir, "leases": leases_dir,
                                "lease_prologue": box_lease_prologue(
                                    max_requests,
                                    stage6_max_concurrent=stage6_max_concurrent,
                                    stage6_headroom_load1=stage6_headroom_load1,
                                    fingerprint=fingerprint),
                                # T-12260 — substituted as a VALUE for the same reason the prologue
                                # is: this text carries its own `%` (a printf format, an awk format)
                                # which must never be scanned as a format specifier here.
                                "overlap_poller": _BOX_LAND_OVERLAP_POLLER}


# ── the box-side envelope assembler (rule 4) ─────────────────────────────────────────────────────

def envelope_script(*, request: str, attempt: int, venue_dir: str = BOX_VENUE_DIR,
                    legs: "tuple | list" = LEGS, runs_dir: str = BOX_RUNS_DIR) -> str:
    """The box-side assembler TEXT: write whole to a temp path, then RENAME — so a truncated read is
    impossible rather than merely unlikely, and the completion marker is written with the rest.

    T-12220 — it assembles ENTIRELY from THIS request's own run dir (`box_run_dir`): the legs it
    reads, the checkouts it digests, the fingerprint it copies and the envelope it writes. Before,
    every one of those was a shared `~/venue/` path, so two overlapping requests wrote each other's
    envelope over the one file and the executor read back whichever landed last.

    T-12247 — `main_tests` reads THIS request's own main ref (`box_ref`), not the clone's shared
    `main`. That digest is what the pinned leg's `tests/` overlay is judged against, so reading it
    from a ref every request force-pushed made it the same "whose push landed last?" answer the
    transport read-back was."""
    return r"""python3 - <<'PYENV'
import json, os, subprocess, time
V = os.path.expanduser(%(venue)r)
R = os.path.expanduser(%(run)r)
legs = {}
for leg in %(legs)r:
    p = os.path.join(R, "out-%%s" %% leg, "leg.json")
    legs[leg] = json.load(open(p)) if os.path.exists(p) else None
def tree(d):
    return subprocess.run(["git", "-C", d, "rev-parse", "HEAD^{tree}"], text=True,
                          capture_output=True).stdout.strip() or None
main_tests = subprocess.run(["git", "-C", os.path.join(V, "repo.git"), "rev-parse",
                             %(main_ref)r + ":tests"],
                            text=True, capture_output=True).stdout.strip() or None
fp_path = os.path.join(R, "fingerprint.json")
env = {"schema": %(schema)r, "request": %(request)r, "attempt": %(attempt)d,
       "checkout_digest": {"cand": tree(os.path.join(R, "cand")),
                           "pinned": tree(os.path.join(R, "pinned")),
                           "main_tests": main_tests},
       "legs": legs,
       "fingerprint": json.load(open(fp_path)) if os.path.exists(fp_path) else None,
       "completed_at": time.strftime("%%Y-%%m-%%dT%%H:%%M:%%SZ", time.gmtime()),
       "completion_marker": "COMPLETE"}
p = os.path.join(R, "envelope.json")
open(p + ".tmp", "w").write(json.dumps(env))
os.rename(p + ".tmp", p)
print("ENVELOPE", len(json.dumps(env)))
PYENV""" % {"venue": venue_dir, "schema": ENVELOPE_SCHEMA, "request": request, "attempt": attempt,
             "legs": tuple(legs), "run": box_run_dir(request, attempt, runs_dir=runs_dir),
             "main_ref": box_ref(request, attempt, "main")}


def box_cleanup_script(request: str, attempt: int = 1, *, venue_dir: str = BOX_VENUE_DIR,
                       repo_git: str = BOX_REPO_GIT, runs_dir: str = BOX_RUNS_DIR,
                       leases_dir: str = BOX_LEASES_DIR) -> str:
    """Per-request cleanup at completion (rule 4): drop THIS pass's leg worktrees, its run dir and
    its leases, and nothing else. Isolation per request means a run dir per pass, so without a
    cleanup the box would accumulate one full checkout per land — the cleanup is the other half of
    the keying, not tidiness. It names ONLY this request's paths, so it can never reach a concurrent
    run, and every step is best-effort: a completed pass whose envelope is already fetched must not
    become a fault because a directory would not go away."""
    run = box_run_dir(request, attempt, runs_dir=runs_dir)
    refs = " ".join(box_ref(request, attempt, n) for n in ("cand", "main"))
    return (f'for d in {run}/cand {run}/pinned; do '
            f'git -C {repo_git} worktree remove --force "$d" 2>/dev/null || true; done; '
            f'rm -rf {run} 2>/dev/null || true; '
            f'rm -f {leases_dir}/{shlex.quote(request)}-{int(attempt)}-* 2>/dev/null || true; '
            # T-12247 — the request's two TRANSPORT refs, the other half of the ref keying. A run dir
            # that is not removed accumulates a checkout; a ref that is not removed accumulates a ref
            # AND pins its objects, so leaving them is a leak rather than a fault.
            f'for r in {refs}; do '
            f'git -C {repo_git} update-ref -d "$r" 2>/dev/null || true; done; '
            # ...and the RETIREMENT sweep of the dead SHARED ref (P1 F3). Nothing writes or reads
            # `refs/venue/cand` any more, so the copy this card removed from the code has to be
            # removed from the live clone too — otherwise the thing being retired sits on the box
            # forever, and the AC2 reading ("no shared ref survives a completed pass") can never be
            # clean. Best-effort and idempotent, like every step here.
            f'git -C {repo_git} update-ref -d refs/venue/cand 2>/dev/null || true; '
            f'git -C {repo_git} worktree prune 2>/dev/null || true; true')


# ── running both legs (rule 3: in parallel; rule 4: one process group per attempt) ───────────────

VENUE_WAIT_LINE = "waiting_for_venue_admission"


def parse_venue_wait_line(line: str) -> "dict | None":
    """One leg-output line -> the admission-heartbeat payload, or None when it is not one.

    PURE and text-only, so the relay contract is provable without a box or a thread. The line is the
    prologue's own `k=v` shape; unknown keys are ignored and the numeric ones are coerced, because a
    heartbeat that failed to parse must degrade to "no heartbeat", never to a raise on the leg-output
    path.
    """
    line = str(line or "").strip()
    if not line.startswith(VENUE_WAIT_LINE):
        return None
    out: dict = {}
    for token in line.split()[1:]:
        if "=" not in token:
            continue
        k, _, v = token.partition("=")
        if k in ("waited_s", "cap", "live", "live_stage6"):
            try:
                out[k] = int(v)
            except (TypeError, ValueError):
                out[k] = None
        elif k == "load1":
            try:
                out[k] = float(v)
            except (TypeError, ValueError):
                out[k] = None
        else:
            out[k] = v
    return out


VENUE_OVERLAP_LINE = "venue_land_overlap"


def parse_venue_overlap_line(line: str) -> "dict | None":
    """One leg-output line -> the land-overlap heartbeat payload, or None when it is not one.

    The SIBLING of `parse_venue_wait_line`, deliberately built to the same shape rather than to a
    second convention: same `k=v` tokens, same coercion, same "unknown keys are ignored", same
    degrade-to-None on anything unparseable. Pure and text-only, so the relay contract is provable
    without a box or a thread — and a malformed heartbeat must read as NO heartbeat, never as a raise
    on the leg-output path, because this line arrives on the thread that also drains the pipe.

    NOTE the discrimination against its sibling: `venue_land_overlap` and
    `waiting_for_venue_admission` are distinct prefixes, so neither parser can consume the other's
    line — and `overlap_s` that fails to coerce yields None rather than a 0 that would read as
    "measured, and it was nothing"."""
    line = str(line or "").strip()
    if not line.startswith(VENUE_OVERLAP_LINE):
        return None
    out: dict = {}
    for token in line.split()[1:]:
        if "=" not in token:
            continue
        k, _, v = token.partition("=")
        if k == "overlap_s":
            try:
                out[k] = float(v)
            except (TypeError, ValueError):
                out[k] = None
        else:
            out[k] = v
    return out


def _drain_leg(leg: str, proc, on_wait: "callable | None", overlap_out: "dict | None" = None) -> None:
    """Read ONE leg's merged output to EOF, relaying each admission heartbeat as it arrives.

    Errors are swallowed by contract — see the call site: this thread exists for observability, and
    an observability fault must never reach the verdict. It also performs the draining the pipe
    needs regardless of whether anyone is listening for heartbeats."""
    try:
        for line in iter(proc.stdout.readline, ""):
            # T-12260 — the land-overlap heartbeat, recorded as it ARRIVES (mid-run) rather than read
            # off the envelope afterwards. The leg bound below expires while the run is in flight, so
            # a total learned after the leg ended could not extend it. MONOTONE by construction: only
            # a LARGER figure is kept, so an out-of-order or truncated line can never shrink an
            # extension already granted.
            if overlap_out is not None:
                _ov = parse_venue_overlap_line(line)
                if _ov and isinstance(_ov.get("overlap_s"), (int, float)):
                    if _ov["overlap_s"] > overlap_out.get(leg, 0.0):
                        overlap_out[leg] = float(_ov["overlap_s"])
            if on_wait is None:
                continue
            row = parse_venue_wait_line(line)
            if row is None:
                continue
            try:
                on_wait(dict(row, leg=leg))
            except Exception:                  # noqa: BLE001 — relay never breaks the pass
                pass
    except Exception:                          # noqa: BLE001 — ditto for the read itself
        pass


def wait_legs(procs: dict, timeout: float, overlap_s: "dict | None" = None,
              _monotonic=None, _poll: float = 5.0) -> None:
    """Wait for every leg, UNCHARGED for the time a foreign LAND held the box (T-12260).

    THE LEG BOUND GETS THE SAME TREATMENT THE PER-FILE BOUND INSIDE THE LEG GETS (SPEC-0071 rule 1),
    and it is not optional decoration: extending the per-file deadlines alone would merely MOVE the
    kill one layer up. A leg whose files were each given back their starved seconds runs
    correspondingly longer, and killing it HERE would waste exactly the pass the per-file credit was
    spent saving.

    WHY A POLL LOOP RATHER THAN ONE `wait(timeout=...)`: the extension is not known when the wait
    begins. It arrives on the relay threads WHILE the legs run (`_drain_leg` fills `overlap_s`), so
    the deadline has to be RE-READ, which a single blocking wait cannot do.

    THE FAILURE SIGNATURE IS UNCHANGED — deliberately, because `run_legs`' callers already handle it:
    a leg still alive at the (extended) deadline raises `subprocess.TimeoutExpired` from `wait`,
    exactly as the single blocking wait did. Only the MOMENT it fires moves.

    STILL BOUNDED, which is the property that makes this safe rather than an open-ended reprieve:
    overlap accrues only while a foreign land is genuinely live on the box, and that land carries its
    own bound. `overlap_s` empty (no relay, a box that never overlapped a land, a malformed
    heartbeat) is the pre-T-12260 behaviour exactly.

    `procs` is the `{leg: process}` MAPPING `run_legs` already holds, not a bare sequence, because
    the extension is per-leg and a sequence would have thrown away the only key that says whose
    overlap is whose.

    Extracted from `run_legs` — with the clock and the poll interval injectable — so the bound's
    behaviour is provable without a box, the same reason `box_leg_script` returns text."""
    mono = _monotonic or time.monotonic
    for leg, p in dict(procs).items():
        # PER-LEG, NOT ONE SHARED DEADLINE (audit-post finding, 2026-09-08). The loop this replaced
        # was `for p in procs: p.wait(timeout=timeout)`, which gave EVERY leg a full `timeout`
        # starting when ITS wait began — so with two legs the second could legitimately take another
        # `timeout` after the first returned. A single deadline anchored before the loop silently
        # TIGHTENED that: the second leg would inherit whatever the first had already spent. This
        # card is about not charging a leg for time it did not get; charging it for its sibling's
        # wall would be the same defect wearing the fix's clothes.
        deadline = mono() + timeout
        while True:
            # ...AND THE EXTENSION IS THIS LEG'S OWN, for the same reason: `overlap_s` is keyed by
            # leg, so a leg no land overlapped is not lengthened because its sibling was. Read fresh
            # each round because the relay thread is still filling it while this leg runs.
            extra = float((overlap_s or {}).get(leg) or 0.0)
            left = (deadline + extra) - mono()
            if left <= 0:
                p.wait(timeout=0)            # raises TimeoutExpired if it is still running — the
                break                        # UNCHANGED signature the caller already handles
            try:
                p.wait(timeout=min(left, _poll))
                break
            except subprocess.TimeoutExpired:
                continue                     # re-read the relayed overlap and re-judge


def run_legs(box: str, shipped: dict, *, request: str, attempt: int = 1,
             workers: "int | None" = None, user: str = "dev", scratch=None,
             fingerprint: "dict | None" = None, disconnect_after: "float | None" = None,
             corrupt_path: "str | None" = None, timeout: float = 3600,
             legs: "tuple | list" = LEGS, exclude: "set | list | None" = None,
             only: "set | list | None" = None, nice: int = 0,
             on_wait: "callable | None" = None,
             max_requests: "int | None" = None,
             pinned_skip: "set | list | None" = None) -> dict:
    """Start both legs in parallel and assemble the envelope on the box; return the RAW run record
    (both-legs wall + where the envelope was fetched to). It does NOT judge — `validate_envelope`
    does, and keeping the two apart is what lets the validator be tested without a box.

    `disconnect_after` is the AC3 disconnect probe: kill the clients after N seconds, leaving the
    box-side groups to be reaped by the next attempt's lease.

    T-12199 — THREE PARAMETERS, each because a SPEC-0203 rule is unrepresentable without it, and all
    three defaulting to exactly today's behaviour:
      `legs`    — WHICH legs this pass starts (rule 3: a land starts BOTH in parallel; `task test
                  --run` is a CANDIDATE-ONLY pass and passes `("cand",)`). The envelope is assembled
                  over the STARTED legs alone, so a leg that did not run cannot contribute a stale
                  `leg.json` from an earlier pass.
      `exclude` — rule 8's partition: the local-probe file names that must NOT run on the box. Shipped
                  as `exclude.json` beside the fingerprint and applied by the leg script through the
                  shipped runner's OWN `only=` parameter. ALWAYS written (an empty list when there is
                  nothing to exclude) so a previous pass's file can never narrow this one.
      `nice`    — the box-side half of the lower-priority arm; passed to the leg script, which applies
                  it to the runner invocation and RECORDS the priority it actually ran at.

    T-12222 adds a FOURTH on the same terms: `only` — the GOVERNED SPEC-0181 selection the local path
    computed, shipped as `only.json` and applied by the leg script to the CANDIDATE leg alone (R1: the
    selection never narrows the pinned pass). ALWAYS written, JSON `null` when there is no selection,
    for the same reason `exclude.json` always is: a previous pass's file must never narrow this one.

    T-12313 adds a FIFTH, on exactly those terms: `pinned_skip` — the SPEC-0077 §3 pinned-leg
    narrowing (census-class + touched-by-this-branch files), COMPUTED ON THE HOST by the one
    `rebaseline_currency.pinned_leg_narrowing()` and shipped as `pinned_skip.json` for the PINNED leg
    to apply. The box never rebuilds it: before this card these two exclusions were computed NOWHERE
    on a routed land (the local driver that owns them is not called, and the leg script derives only
    `not_pinned`), so every venue land re-ran a stale pinned copy and paid a rebaseline round.
    ALWAYS written (a JSON list, `[]` when empty) for the same reason `exclude.json` always is."""
    if workers is None:                         # T-12219 — resolved HERE, never as a module-level
        workers = remote_verify_workers()       # default: an import-time default never sees a later
                                                # `config set` (SPEC-0193 rule 7 read-site shape)
    scratch = Path(scratch or tempfile.mkdtemp(prefix="yitc-remote-verify-"))
    scratch.mkdir(parents=True, exist_ok=True)
    # THIS PASS'S OWN BOX-SIDE HOME (rule 4, T-12220). The driver script and both per-pass inputs are
    # shipped INTO it rather than into the shared venue dir: `exclude.json` is rule 8's partition for
    # THIS pass and `fingerprint.json` is the record THIS pass was routed under, so a concurrent
    # request writing the shared copies would silently narrow or mis-bind this one.
    run_dir = box_run_dir(request, attempt)
    _ssh(box, f"mkdir -p {run_dir} {BOX_LEASES_DIR}", user=user, timeout=60)
    leg_sh = scratch / "box-leg.sh"
    # The fingerprint travels into the script because the Stage-6 headroom default is DERIVED from
    # this box's own cores (T-12259) — the executor already holds it to ship it, so resolving the
    # threshold here keeps the rendered text carrying an effective number rather than a stand-in.
    leg_sh.write_text(box_leg_script(nofile=VENUE_NOFILE, max_requests=max_requests,
                                     fingerprint=fingerprint))
    subprocess.run(["scp", *SSH_OPTS, "-q", str(leg_sh), f"{user}@{box}:{run_dir}/box-leg.sh"],
                   check=True, timeout=120)
    if fingerprint is not None:
        fp = scratch / "fingerprint.json"
        fp.write_text(json.dumps(fingerprint))
        subprocess.run(["scp", *SSH_OPTS, "-q", str(fp),
                        f"{user}@{box}:{run_dir}/fingerprint.json"], check=True, timeout=120)
    exc = scratch / "exclude.json"
    exc.write_text(json.dumps(sorted(exclude or [])))
    subprocess.run(["scp", *SSH_OPTS, "-q", str(exc),
                    f"{user}@{box}:{run_dir}/exclude.json"], check=True, timeout=120)
    onl = scratch / "only.json"
    onl.write_text(json.dumps(sorted(only) if only is not None else None))
    subprocess.run(["scp", *SSH_OPTS, "-q", str(onl),
                    f"{user}@{box}:{run_dir}/only.json"], check=True, timeout=120)
    # T-12313 — THIS pass's pinned-leg narrowing. ALWAYS written, an empty list when the host
    # narrowed nothing, so a PREVIOUS pass's file can never narrow this one — the same invariant
    # `exclude.json` and `only.json` are always-written for.
    psk = scratch / "pinned_skip.json"
    psk.write_text(json.dumps(sorted(pinned_skip or [])))
    subprocess.run(["scp", *SSH_OPTS, "-q", str(psk),
                    f"{user}@{box}:{run_dir}/pinned_skip.json"], check=True, timeout=120)
    _ssh(box, f"chmod +x {run_dir}/box-leg.sh", user=user, timeout=60)

    prefix = f"VENUE_CORRUPT={shlex.quote(corrupt_path)} " if corrupt_path else ""
    # T-12377 — WHICH legs this pass starts, so the leg script exports the quiet-point barrier only
    # when a sibling leg really exists (a candidate-only Stage-6 pass has no sibling to wait for).
    prefix += f"VENUE_LEGS={shlex.quote(' '.join(str(l) for l in legs))} "
    t0 = time.monotonic()
    procs = {leg: subprocess.Popen(
        ssh_argv(box, f"{prefix}{run_dir}/box-leg.sh {leg} {int(workers)} "
                      f"{shlex.quote(request)} {int(attempt)} {int(nice)}", user=user),
        text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT) for leg in legs}
    # DRAIN EACH LEG'S OUTPUT AS IT ARRIVES (T-12241). Two reasons, and the second is not the
    # decoration: (i) a `waiting_for_venue_admission` line must reach the local journal WHILE the leg
    # is still waiting — a heartbeat delivered after the pass finishes is not a heartbeat; (ii) the
    # pipes were previously never read until `wait()`, so a leg that talked enough would have blocked
    # on a full pipe with nobody draining it. The threads are daemons and swallow their own errors:
    # a relay that could raise would put an observability fault on the verdict path.
    # T-12260 — the per-leg land-overlap totals, filled by the relay threads WHILE the legs run and
    # read by the wait loop below. A plain dict of floats under the GIL: each thread writes only its
    # own key and the reader only ever takes a max, so no lock is needed for a monotone counter.
    overlap_s: dict = {}
    relays = []
    for _leg, _p in procs.items():
        th = threading.Thread(target=_drain_leg, args=(_leg, _p, on_wait, overlap_s), daemon=True)
        th.start()
        relays.append(th)

    if disconnect_after is not None:
        time.sleep(disconnect_after)
        for p in procs.values():
            p.kill()
        return {"request": request, "attempt": attempt, "fault": "disconnect",
                "killed_after_s": disconnect_after, "envelope_path": None,
                "both_legs_wall_s": round(time.monotonic() - t0, 1), "scratch": str(scratch)}
    wait_legs(procs, timeout, overlap_s)
    for th in relays:                        # bounded: each ends when its leg's pipe closes
        th.join(timeout=30)
    both_wall = round(time.monotonic() - t0, 1)

    _ssh(box, envelope_script(request=request, attempt=attempt, legs=legs), user=user, timeout=300)
    dest = scratch / f"envelope-{request}-{attempt}.json"
    subprocess.run(["scp", *SSH_OPTS, "-q", f"{user}@{box}:{run_dir}/envelope.json", str(dest)],
                   check=True, timeout=300)
    # CLEANUP AFTER THE FETCH, never before it, and never fatally: the envelope is already local, so
    # a cleanup that fails must not turn a completed pass into a fault (the caller judges the
    # envelope, and a leftover run dir is a disk cost, not a verdict).
    try:
        _ssh(box, box_cleanup_script(request, attempt), user=user, timeout=120, check=False)
        cleaned = True
    except Exception:                                   # noqa: BLE001 — best-effort by contract
        cleaned = False
    return {"request": request, "attempt": attempt, "envelope_path": str(dest),
            "both_legs_wall_s": both_wall, "scratch": str(scratch), "run_dir": run_dir,
            "cleaned": cleaned,
            "legs": tuple(legs), "nice": int(nice), "excluded": sorted(exclude or []),
            "only": (sorted(only) if only is not None else None)}


# ── the verdict side: what `land` checks (rule 4) ────────────────────────────────────────────────

#: The per-leg envelope key the T-12262 guard writes: `[]` = checked and clean, a list of refnames =
#: those moved, `None` = the snapshot could not be taken. Only the LIST is a fault; `None` is not,
#: because "we could not look" must never read as "we looked and something moved".
VENUE_REFS_MOVED_KEY = "venue_refs_moved"

#: The per-leg envelope key the T-12284 restore PROOF writes: `True` = every ref in that leg's moved
#: set is back, byte-identical to its pre-run snapshot; `False` = at least one is not; `None` = the
#: leg could not tell. Only `True` admits the bounded re-attempt (SPEC-0203 rule 4).
VENUE_REFS_RESTORED_KEY = "venue_refs_restored"

#: The per-leg envelope key the T-12301 mirror classification writes: a mapping carrying the shas
#: `refs/heads/main` moved FROM and TO when that move was an EQUAL-or-DESCENDANT advance of this
#: request's own main — i.e. the box catching up with the host, not a clobber. Absent or `None` means
#: no mirror was recognised (including on every record written before this card), which is the same
#: reading as "not a mirror" on purpose: this key can only ever EXPLAIN a suppression, never cause
#: one. Nothing in the verdict path reads it — it is REPORT-ONLY, and `envelope_refs_clobbered` stays
#: PURE, reading the moved list a mirror is no longer in.
VENUE_MAIN_MIRRORED_KEY = "venue_main_mirrored"
#: T-12344 — the key `ship_trees` sets on the SHIPPED IDENTITY when it healed a proven-DIVERGED clone
#: `refs/heads/main` with one force-with-lease push: `{"from": <orphan sha>, "to": <shipped main>}`.
#: Identity-level (host-side), unlike the leg-level envelope key above; `remote_verify_row` carries
#: it ONLY when present, so `verify_metrics.venue_main_healed` exists for a healed pass and is
#: ABSENT — not null — otherwise. REPORT-ONLY: nothing in the verdict path reads it.
VENUE_MAIN_HEALED_KEY = "venue_main_healed"


def envelope_refs_clobbered(env: "dict | None", *, legs: "tuple | list" = LEGS) -> dict:
    """The moved-ref sets this envelope reports, per leg, for the legs that STARTED — `{}` when none.

    PURE and envelope-only, so the classification below is provable without a box. A leg that reports
    `None` (unknown) or `[]` (clean) contributes nothing: this returns only the legs that positively
    named a moved ref, which is the only reading that can refuse a pass."""
    out: dict = {}
    for leg in tuple(legs):
        rec = ((env or {}).get("legs") or {}).get(leg) or {}
        moved = rec.get(VENUE_REFS_MOVED_KEY) if isinstance(rec, dict) else None
        if isinstance(moved, list) and moved:
            out[leg] = [str(m) for m in moved]
    return out


def envelope_refs_snapshot_unknown(env: "dict | None", *, legs: "tuple | list" = LEGS) -> list:
    """The legs that REPORTED a record but whose pre-run ref snapshot could not be taken (T-12284).

    PURE and envelope-only, the sibling of `envelope_refs_clobbered`. The T-12262 predicate treated
    `None` as "not a clobber" — the fail-SAFE reading, and consult finding B3 is what it costs: a
    snapshot that fails while the suite moves `refs/heads/main` reports `None`, the clobber reader
    ignores it, and the mutation is reported as a NORMAL test result. This card's decision is
    fail-CLOSED on that arm: unknown shared-ref state refuses the pass.

    SCOPED TO LEGS THAT ACTUALLY REPORTED, deliberately: a leg with NO record at all is left to the
    existing classification, so a truncated or unbound envelope still reports its own, more specific
    class instead of being re-labelled as a ref fault it never said anything about."""
    out: list = []
    for leg in tuple(legs):
        rec = ((env or {}).get("legs") or {}).get(leg)
        if isinstance(rec, dict) and rec.get(VENUE_REFS_MOVED_KEY, "absent") is None:
            out.append(leg)
    return out


def envelope_refs_restore_proven(env: "dict | None", *, legs: "tuple | list" = LEGS) -> bool:
    """True only when EVERY leg that named a moved ref proved it put every one of them back.

    THE RETRY ADMISSION PREDICATE (T-12284 / SPEC-0203 rule 4). `venue-refs-clobbered` is the one
    indeterminate class whose remedy the box has already applied, which is what makes a re-attempt
    sound — but the CLASS is not the remedy, the RESTORE is. Admitting on the class alone is
    precisely consult findings B1/B2, where the second attempt baselines a still-corrupted ref.
    So the proof is read back off the leg's own `venue_refs_restored`, and anything that is not
    exactly `True` — `False`, `None`, or the key absent — refuses."""
    named = False
    for leg in tuple(legs):
        rec = ((env or {}).get("legs") or {}).get(leg) or {}
        moved = rec.get(VENUE_REFS_MOVED_KEY) if isinstance(rec, dict) else None
        if isinstance(moved, list) and moved:
            named = True
            if rec.get(VENUE_REFS_RESTORED_KEY) is not True:
                return False
    return named


def _classify(failed_checks) -> str:
    """Map the FAILED check names onto the ONE named INDETERMINATE class, most specific first.

    Order matters and is not arbitrary: a stale reply also mismatches its binding, and a truncated
    envelope also lacks every digest — so the more specific cause must win, or every fault would
    report as the vaguest one that also happens to be true."""
    names = {c["check"] for c in failed_checks}
    if "parse" in names or "completion_marker" in names:
        return "truncated"
    if "not_duplicate_or_stale" in names:
        return "duplicate-or-stale"
    if any(n.startswith(("tree_digest", "worktree_identity", "runner_digest")) for n in names):
        return "digest-mismatch"
    if any("binding" in n for n in names):
        return "binding"
    return "venue-fault"


def validate_envelope(text: "str | None", *, shipped: dict, request: str, attempt: int,
                      fingerprint: "dict | None" = None, seen: "set | tuple" = (),
                      disconnected: bool = False, legs: "tuple | list" = LEGS) -> dict:
    """The complete envelope check, and the ONLY place an outcome is decided.

    Returns `{"outcome", "indeterminate_class", "checks", "failing", "walls", "envelope"}`. The
    outcome is three-valued (rule 4): GREEN, FAILED (with the files named exactly as a local failure
    names them), or INDETERMINATE with one of `INDETERMINATE_CLASSES`. An INDETERMINATE NEVER
    becomes GREEN and never masquerades as a test failure.

    `checks` is the full roster in a FIXED order — 18 checks — and it is returned whole, passing
    entries included, because "which checks ran" is the question a reader has when a verdict
    surprises them, and a list of only the failures cannot answer it."""
    checks: list = []

    def chk(name, ok, detail=""):
        checks.append({"check": name, "ok": bool(ok), "detail": str(detail)[:160]})

    if disconnected:
        chk("parse", False, "client disconnected before the envelope was assembled")
        return {"outcome": OUTCOME_INDETERMINATE, "indeterminate_class": "disconnect",
                "checks": checks, "failing": {}, "walls": {}, "envelope": None}
    try:
        env = json.loads(text or "")
        chk("parse", True)
    except Exception as e:
        chk("parse", False, str(e))
        # THE MESSAGE, EXACTLY — no type prefix (audit-post finding 1). AC2 asks the field to carry
        # the injected message ITSELF, and the type is not lost: the roster entry beside it still
        # reads `<type>: <message>`. An exception whose `str()` is empty falls through to that
        # roster in `indeterminate_detail`, so dropping the prefix cannot produce an empty detail.
        return {"outcome": OUTCOME_INDETERMINATE, "indeterminate_class": "truncated",
                "indeterminate_detail": str(e),
                "checks": checks, "failing": {}, "walls": {}, "envelope": None}

    chk("schema", env.get("schema") == ENVELOPE_SCHEMA, env.get("schema"))
    chk("completion_marker", env.get("completion_marker") == "COMPLETE", env.get("completion_marker"))
    chk("request_binding", env.get("request") == request, f"{env.get('request')} vs {request}")
    chk("attempt_binding", env.get("attempt") == attempt, f"{env.get('attempt')} vs {attempt}")

    # T-12199 — the roster is checked over exactly the legs this pass STARTED (`legs`), never the
    # module default: a candidate-only pass has no pinned leg to check, and demanding one would turn
    # every such pass into a permanent INDETERMINATE. `leg_set` is the started set; `env_legs` is
    # what the envelope carries.
    leg_set = tuple(legs)
    env_legs = env.get("legs") or {}
    legs = env_legs
    expected_tree = {"cand": shipped.get("cand_tree"), "pinned": shipped.get("pinned_tree")}
    for leg in leg_set:
        lg = legs.get(leg) or {}
        # The identity that matters: the tree that RAN, equal to the tree that was SHIPPED.
        ran = lg.get("worktree_tree")
        want = expected_tree[leg]
        chk(f"worktree_identity_{leg}", bool(ran) and bool(want) and ran == want,
            f"ran {str(ran)[:12]} shipped {str(want)[:12]}")
        # The checkout digest is recorded and checked too, but it is the WEAKER signal by design: it
        # names what was checked out. Kept because a mismatch here localises a transport fault, while
        # a mismatch above localises a post-checkout one.
        got_checkout = (env.get("checkout_digest") or {}).get(leg)
        want_checkout = (shipped.get("cand_tree") if leg == "cand" else None)
        chk(f"tree_digest_{leg}",
            bool(got_checkout) and (want_checkout is None or got_checkout == want_checkout),
            f"{str(got_checkout)[:12]}")
        chk(f"per_file_outcomes_{leg}", bool((lg.get("per_file_outcomes") or {}).get("count")),
            str((lg.get("per_file_outcomes") or {}).get("count")))

    # The CROSS-LEG digest equality is a two-leg check by nature. With a single leg started it
    # DEGRADES to the local-equality check below (which is the stronger of the two anyway — it binds
    # the box's runner to THIS repo's), rather than being asserted over a leg that never ran.
    _rds = [(legs.get(l) or {}).get("runner_digest") for l in leg_set]
    rd_c = _rds[0] if _rds else None
    if len(leg_set) > 1:
        chk("runner_digest_equal_across_legs", all(_rds) and len(set(_rds)) == 1,
            " vs ".join(str(d)[:12] for d in _rds))
    else:
        chk("runner_digest_equal_across_legs", bool(rd_c),
            f"single leg {leg_set[0] if leg_set else '-'} — degrades to the local-equality check")
    chk("runner_digest_matches_local", bool(rd_c) and rd_c == shipped.get("runner_digest"),
        f"{str(rd_c)[:12]} vs local {str(shipped.get('runner_digest'))[:12]}")

    fp = env.get("fingerprint")
    chk("fingerprint_present", bool(fp))
    chk("fingerprint_matches_published", (fingerprint is None) or (fp == fingerprint),
        "no published fingerprint to compare" if fingerprint is None else "compared")
    # BOTH halves of the rule-5 fd pin, conjoined into the ONE check rather than split across two
    # (T-12195): the LEGS' `nofile_in_effect` is what the runner processes actually got, and the
    # FINGERPRINT's limit is what the box says it offers. They are the same fact measured at two
    # moments and a disagreement between them is a venue fault either way, so a second, near-identical
    # roster entry would buy a longer roster and no new information (CHARTER §P1 F2).
    chk("nofile_admits_workers",
        all((legs.get(l) or {}).get("nofile_in_effect", 0) >= VENUE_NOFILE for l in leg_set)
        and fingerprint_admits_pin(fp),
        ", ".join(f"{l}={(legs.get(l) or {}).get('nofile_in_effect')}" for l in leg_set)
        + f", fingerprint={(fp or {}).get('nofile_soft')}")
    chk("tmpfs_in_effect",
        all((legs.get(l) or {}).get("verify_tmpdir") for l in leg_set),
        ", ".join(str((legs.get(l) or {}).get("verify_tmpdir")) for l in leg_set))
    key = f"{env.get('request')}#{env.get('attempt')}"
    chk("not_duplicate_or_stale", key not in set(seen), key)
    walls = {l: (legs.get(l) or {}).get("wall_s") for l in leg_set}
    failing = envelope_failing_files(env, legs=leg_set)
    # T-12262 — THE REF-IMMUTABILITY SHORT-CIRCUIT. A leg that reports moved shared refs refuses the
    # WHOLE pass as `venue-refs-clobbered`, and it does so HERE, ahead of the verdict, for the reason
    # `_classify` already states about ordering: a clobbered `refs/heads/main` ALSO breaks the pinned
    # leg's `main:tests` digest and makes every main-consulting test fail, so without this the more
    # specific cause would report as the vaguer `digest-mismatch` — or, worse, as a list of per-file
    # FAILURES that name innocent test files (the measured 2026-09-08 reading: 9 files RED on three
    # candidates in a row, charged to their diffs). The check is appended on the FAILING path only:
    # the GREEN roster is a fixed 18 entries that a reader consults when a verdict surprises them, and
    # a pass whose refs did not move has nothing here to explain.
    # T-12284 — THE NULL SNAPSHOT REFUSES TOO, and it is checked FIRST because it is the weaker
    # fact: a leg that could not snapshot cannot name a moved ref, so the clobber reader below sees
    # nothing and the pass would proceed to a verdict over shared-ref state nobody looked at (consult
    # finding B3). The T-12262 predicate read `None` as "not a clobber" — fail-SAFE against refusing
    # honest passes, and fail-OPEN against exactly the incident this guard exists for. The decision
    # taken on this card is fail-CLOSED on both arms: unknown is not clean. It cannot fabricate the
    # other direction — a refusal is never a pass — and it is scoped to legs that DID report, so a
    # missing leg still reports its own more specific class.
    _snapshot_unknown = envelope_refs_snapshot_unknown(env, legs=leg_set)
    if _snapshot_unknown:
        chk("venue_refs_snapshot_taken", False,
            f"{', '.join(_snapshot_unknown)}: pre-run ref snapshot could not be taken")
        return {"outcome": OUTCOME_INDETERMINATE, "indeterminate_class": "venue-refs-clobbered",
                "checks": checks, "failing": {}, "walls": walls, "envelope": env,
                "refs_clobbered": {}, "refs_clobber_reason": "snapshot-failed",
                "refs_restore_proven": False}
    _clobbered = envelope_refs_clobbered(env, legs=leg_set)
    if _clobbered:
        chk("venue_refs_intact", False,
            "; ".join(f"{leg}: {', '.join(refs)}" for leg, refs in sorted(_clobbered.items())))
        # THE PROOF TRAVELS WITH THE REFUSAL (T-12284). `refs_restore_proven` is what admits the
        # caller's single re-attempt; it is computed HERE, off the legs' own records, so the retry
        # decision is made on evidence the box produced rather than on the class name.
        _proven = envelope_refs_restore_proven(env, legs=leg_set)
        return {"outcome": OUTCOME_INDETERMINATE, "indeterminate_class": "venue-refs-clobbered",
                "checks": checks, "failing": {}, "walls": walls,
                "envelope": env, "refs_clobbered": _clobbered,
                "refs_restore_proven": _proven,
                "refs_clobber_reason": "restored" if _proven else "restore-incomplete"}
    bad = [c for c in checks if not c["ok"]]
    if bad:
        return {"outcome": OUTCOME_INDETERMINATE, "indeterminate_class": _classify(bad),
                "checks": checks, "failing": failing, "walls": walls, "envelope": env}
    n = sum(len(v) for v in failing.values())
    return {"outcome": OUTCOME_GREEN if n == 0 else OUTCOME_FAILED, "indeterminate_class": None,
            "checks": checks, "failing": failing, "walls": walls, "envelope": env}


def envelope_failing_files(envelope: dict, *, legs: "tuple | list" = LEGS) -> dict:
    """The per-leg failing-file list — the input rule 8's host-sensitivity classification reads, and
    the reason a remote failure NAMES its files exactly as a local one does."""
    got = (envelope or {}).get("legs") or {}
    return {leg: sorted((got.get(leg) or {}).get("failing") or []) for leg in legs}


def envelope_excluded_not_pinned(envelope: dict, *, leg: str = "pinned") -> list:
    """SPEC-0077 §3 / T-12250 — the test files the PINNED leg excluded because they did not exist at
    the last-green ref, read back off the leg's own record.

    The ONE reader of that field, so the land site does not spell the envelope path itself and the
    routed half of `verify_metrics.pinned_excluded_not_pinned` cannot drift from what the leg wrote.

    TOTAL on every malformed shape — a missing envelope, a missing leg, a `None` leg record, a
    non-list value — all answer the EMPTY list, because the caller writes the key present-only: an
    absent key means "this land excluded nothing" and a fabricated empty would mean the same thing
    while hiding a read that failed. The narrowing itself is never inferred from here; the leg's own
    `not_pinned_read` field says whether the derivation ran."""
    rec = ((envelope or {}).get("legs") or {}).get(leg)
    names = rec.get("excluded_not_pinned") if isinstance(rec, dict) else None
    # `isinstance(names, list)` and not a bare truthiness test: a STRING is iterable, so a leg record
    # carrying `"test_a.py"` where a list belongs would otherwise be read CHARACTER BY CHARACTER and
    # reported as nine excluded files. The same shape-before-iteration rule the box leg applies to its
    # own `only.json` reading, for the same reason — a malformed artifact is broken, never narrower.
    if not isinstance(names, list):
        return []
    return sorted(n for n in names if isinstance(n, str))


def envelope_pinned_skipped(envelope: dict, *, leg: str = "pinned") -> list:
    """SPEC-0077 §3 / T-12313 — the test files the PINNED leg did NOT re-run because the HOST's
    narrowing (census-class / touched-by-this-branch) named them, read back off the leg's own record.

    THE APPLIED SET, not the shipped one — only the leg knows what it was going to run, so a name the
    host shipped that this pass would not have executed anyway is not in here. That is what lets the
    land site's row and its printed lines describe the SAME narrowing, which is the local path's own
    invariant.

    The ONE reader of that field, the exact shape of `envelope_excluded_not_pinned` beside it, and
    TOTAL on every malformed shape for the same reason: the caller writes the key present-only, so an
    absent key means "this land narrowed nothing" and a fabricated empty would say that too while
    hiding a read that failed. Whether the narrowing RAN is the leg's own `pinned_skip_read`, never
    inferred from here."""
    rec = ((envelope or {}).get("legs") or {}).get(leg)
    names = rec.get("pinned_skipped") if isinstance(rec, dict) else None
    # `isinstance(names, list)`, never a bare truthiness test — a STRING is iterable, so a leg record
    # carrying `"test_a.py"` where a list belongs would be read CHARACTER BY CHARACTER and reported as
    # nine skipped files. The same shape-before-iteration rule the box applies to its own reads.
    if not isinstance(names, list):
        return []
    return sorted(n for n in names if isinstance(n, str))


# ── the entry point ──────────────────────────────────────────────────────────────────────────────

def _execute_remote_verify_once(repo_root, box: str, *, ref: str = "HEAD", request: "str | None" = None,
                          attempt: int = 1, workers: "int | None" = None,
                          user: str = "dev", scratch=None, fingerprint: "dict | None" = None,
                          seen: "set | tuple" = (), main_ref: str = "main",
                          disconnect_after: "float | None" = None,
                          corrupt_path: "str | None" = None,
                          journal: "callable | None" = None,
                          legs: "tuple | list" = LEGS,
                          exclude: "set | list | None" = None,
                          only: "set | list | None" = None,
                          nice: int = 0, on_wait: "callable | None" = None,
                          max_requests: "int | None" = None,
                          pinned_skip: "set | list | None" = None) -> dict:
    """THE executor entry (SPEC-0203 rules 3-4): ship → run both legs → fetch → validate.

    Returns the validation result (see `validate_envelope`) with the request identity, the shipped
    identity and the measured walls attached — including `push_s`, the AC2 delta-push number.

    IT NEVER RAISES INTO A VERDICT. Every failure — an unreachable box, a push refused, a leg that
    could not start, a timeout — returns INDETERMINATE with its class, because a verdict path that
    can raise turns an infrastructure fault into a traceback the caller reads as "no result" rather
    than as a named class it must abort on.

    `journal` is an injected one-argument callable (a dict) so the caller decides where the row goes;
    this module writes no journal of its own. That is not indirection for its own sake — T-12199
    routes this from `land`, which already owns the row, and a module that appended its own would be
    a second verdict record (CHARTER §P5)."""
    request = request or uuid.uuid4().hex[:12]
    started = time.monotonic()
    # THE READ SITE of the rule-5 derivation (T-12195). An explicit `workers=` still wins, because a
    # caller that names a width is measuring one (the trial sweeps did exactly that); absent one, the
    # width is DERIVED here, from this box's fingerprint and this repo's table, once per pass.
    w_derivation = derive_remote_w(fingerprint, remote_duration_table(repo_root))
    if workers is None:
        workers = w_derivation["workers"]
    else:
        w_derivation = dict(w_derivation, workers=int(workers), bound="caller")
    result: dict
    try:
        shipped = ship_trees(repo_root, box, ref, request=request, attempt=attempt,
                             user=user, main_ref=main_ref)
        if shipped.get("box_cand_tree") != shipped.get("cand_tree"):
            result = {"outcome": OUTCOME_INDETERMINATE, "indeterminate_class": "digest-mismatch",
                      "checks": [{"check": "transport_cand_tree", "ok": False,
                                  "detail": f"clone holds {str(shipped.get('box_cand_tree'))[:12]}, "
                                            f"shipped {str(shipped.get('cand_tree'))[:12]}"}],
                      "failing": {}, "walls": {}, "envelope": None}
        else:
            run = run_legs(box, shipped, request=request, attempt=attempt, workers=workers,
                           user=user, scratch=scratch, fingerprint=fingerprint,
                           disconnect_after=disconnect_after, corrupt_path=corrupt_path,
                           legs=legs, exclude=exclude, only=only, nice=nice, on_wait=on_wait,
                           max_requests=max_requests, pinned_skip=pinned_skip)
            if run.get("fault") == "disconnect":
                result = validate_envelope(None, shipped=shipped, request=request, attempt=attempt,
                                           fingerprint=fingerprint, seen=seen, disconnected=True,
                                           legs=legs)
            else:
                text = Path(run["envelope_path"]).read_text()
                result = validate_envelope(text, shipped=shipped, request=request, attempt=attempt,
                                           fingerprint=fingerprint, seen=seen, legs=legs)
            result["run"] = run
        result["shipped"] = shipped
    except Exception as e:
        # T-12364 — the fault's OWN text travels to the row, not just to the check roster. This
        # is the site the T-12301 mirror postcondition's refusal reaches, so `e` here carries both
        # shas, the measured ancestry verdict and the push's stderr: the whole 2026-09-10
        # diagnosis, which used to stop at this line and never reach the operator.
        result = {"outcome": OUTCOME_INDETERMINATE, "indeterminate_class": "venue-fault",
                  "indeterminate_detail": str(e),
                  "checks": [{"check": "venue_reachable", "ok": False,
                              "detail": f"{type(e).__name__}: {e}"}],
                  "failing": {}, "walls": {}, "envelope": None}
    result.update({"request": request, "attempt": attempt, "box": box,
                   "w_derivation": w_derivation, "legs": tuple(legs), "nice": int(nice),
                   "all_in_wall_s": round(time.monotonic() - started, 1)})
    if journal is not None:
        journal(remote_verify_row(result))
    return result


@functools.wraps(_execute_remote_verify_once)
def execute_remote_verify(repo_root, box: str, **kw) -> dict:
    """THE executor entry (SPEC-0203 rules 3-4) — one pass, plus the ONE bounded re-attempt.

    A THIN WRAPPER over `_execute_remote_verify_once`, which is the whole ship -> run -> fetch ->
    validate body and the sole owner of this contract; everything documented there holds here
    unchanged, including "it never raises into a verdict".

    WHAT THE WRAPPER ADDS, and why it is a wrapper (T-12262). `venue-refs-clobbered` is the ONE
    indeterminate class the BOX has already REMEDIED before reporting: the leg restored
    `refs/heads/main` from THIS request's own main ref, so a second attempt ships into a HEALED box
    rather than re-running against the same broken state. That is what makes retrying sound here and
    unsound everywhere else — every OTHER class keeps today's behaviour exactly (`land` ABORTS with
    `abort_class: venue-indeterminate`, worktree intact, operator re-runs). No scheduler and no
    general retry policy is introduced.

    BOUNDED AT ONE BY CONTROL FLOW, not by a counter: there is exactly one re-attempt in this
    function and no loop, so a box that clobbers TWICE reports the second refusal — which is the
    honest outcome, since a box clobbering twice has a live second writer. The FIRST attempt's row is
    journaled by the call below BEFORE the second runs, so the retry is never silent.

    IT IS A WRAPPER RATHER THAN A RECURSIVE CALL because `route` must remain the executor's ONE
    caller (pinned by tests/test_t12199_venue_routing.py `AC5OneCallSite`, which counts CALL NODES
    named `execute_remote_verify` in `bin/**` and requires zero). A self-recursive call would have
    tripped that guard; the guard is deliberate, so the structure moved instead of the guard.

    `functools.wraps` is not cosmetic here: the SIGNATURE is the seam's own contract, read by
    `inspect.signature` to prove each hop still carries the governed selection (`only`, T-12222).
    A `**kw` residue with no `__wrapped__` would erase every parameter name from that reading —
    so the signature keeps ONE home, on the body, exactly as `worktree.hermetic_child_env`'s residue
    keeps it on `verify_runner`'s."""
    result = _execute_remote_verify_once(repo_root, box, **kw)
    if result.get("indeterminate_class") != "venue-refs-clobbered":
        return result
    # THE ADMISSION PREDICATE (T-12284). The class is NOT the remedy — the RESTORE is, and a retry is
    # sound only into a box that provably went back to the state the first attempt found. Anything
    # short of `refs_restore_proven is True` (a main that could not be resolved or re-pointed; a
    # moved ref outside `refs/heads/main` that this request's own refs cannot truthfully name; a
    # snapshot that never happened) returns the REFUSAL unchanged: no second attempt, and therefore
    # no chance of a GREEN whose baseline is the corruption itself. Consult findings B1/B2/B3, one
    # root, closed at the one seam that decides whether to run again.
    if result.get("refs_restore_proven") is not True:
        return result
    first_attempt = result.get("attempt")
    retried = _execute_remote_verify_once(repo_root, box,
                                          **dict(kw, attempt=int(first_attempt or 1) + 1))
    retried["refs_clobber_retry"] = True
    retried["refs_clobber_first_attempt"] = {"attempt": first_attempt,
                                             "refs": result.get("refs_clobbered") or {}}
    return retried


def _union_refs_moved(*sets) -> dict:
    """Per-leg union of moved-ref maps (T-12284) — `{leg: [refname, ...]}`, sorted and de-duplicated.

    PURE, and tolerant of the shapes a result dict actually carries: `None` and non-dict inputs
    contribute nothing, so a pass that never clobbered folds to `{}` exactly as before."""
    out: dict = {}
    for one in sets:
        if not isinstance(one, dict):
            continue
        for leg, refs in one.items():
            if isinstance(refs, (list, tuple, set)):
                out.setdefault(leg, set()).update(str(r) for r in refs)
    return {leg: sorted(refs) for leg, refs in out.items()}


#: T-12357 — the per-leg envelope key carrying a leg's isolated-retry record. Named once so the box
#: writer and the host fold cannot drift into two spellings of the same field.
VENUE_FLAKY_RETRY_KEY = "venue_flaky_retry"
#: T-12358 — the per-leg envelope key carrying a leg's serialized-tail record; named once for the same
#: reason as its sibling above.
VENUE_LOAD_SENSITIVE_KEY = "venue_load_sensitive"
#: T-12447 — the per-leg envelope key carrying a leg's failed-file output tails, and the ONE folded
#: `verify_metrics` key a routed land records them under.
VENUE_FAILED_OUTPUT_TAIL_KEY = "venue_failed_output_tail"
#: The leg a pinned entry came from is named the way `failing_assertions` names it.
VENUE_PINNED_TAIL_PREFIX = "[pinned/last-green] "


def _leg_fold(result: dict, key: str, fold):
    """Fold one numeric per-leg envelope field across the pass's legs, or None if no leg states it.

    NONE IS A REAL ANSWER, not a zero. A leg whose record is missing or whose field is unreadable
    has not told us the value, and folding that into 0 would report "admitted instantly, atomically"
    for a pass we know nothing about — the exact direction a reader must not be misled in. `bool` is
    rejected for the same reason `journal.land_queue_wait_observation` rejects it: `isinstance(True,
    int)` is True, so an unguarded read would score a `True` as a one-second wait."""
    vals = []
    for lg in ((result.get("envelope") or {}).get("legs") or {}).values():
        if not isinstance(lg, dict):
            continue
        v = lg.get(key)
        if isinstance(v, int) and not isinstance(v, bool):
            vals.append(v)
    return fold(vals) if vals else None


def _leg_main_mirrored(result: dict) -> dict:
    """The per-leg MIRROR ADVANCES this pass's legs reported (T-12301) — `{}` when none did.

    PURE and envelope-only, the report-only sibling of `envelope_refs_clobbered` — and deliberately
    NOT wired into any classification: a mirror is already absent from the moved list, so this fold
    exists to make the suppression LEGIBLE on the journal row, never to cause it.

    SHAPE-CHECKED, so a malformed record cannot become a fabricated observation: a leg contributes
    only when its value is a mapping carrying BOTH `from` and `to`. A leg that recorded nothing —
    every leg on every record written before this card — contributes nothing, which reads as
    "no mirror" rather than as an entry with empty shas."""
    out: dict = {}
    for leg, rec in (((result or {}).get("envelope") or {}).get("legs") or {}).items():
        if not isinstance(rec, dict):
            continue
        val = rec.get(VENUE_MAIN_MIRRORED_KEY)
        if isinstance(val, dict) and val.get("from") and val.get("to"):
            out[leg] = {"from": str(val["from"]), "to": str(val["to"])}
    return out


def _leg_first_str(result: dict, key: str) -> "str | None":
    """The first non-empty STRING value of `key` across the pass's legs, or None.

    The string sibling of `_leg_fold`, and deliberately not a generalisation of it: `_leg_fold`
    exists to reconcile per-leg NUMBERS that can legitimately differ, and folding a value that
    cannot differ would state a reconciliation that never happened. A leg that recorded nothing
    contributes nothing, so an absent value reads as absent rather than as an empty string."""
    for lg in ((result.get("envelope") or {}).get("legs") or {}).values():
        if not isinstance(lg, dict):
            continue
        v = lg.get(key)
        if isinstance(v, str) and v:
            return v
    return None


def _leg_headroom_degraded(result: dict) -> "str | bool | None":
    """The pass's THREE-STATE headroom reading, folded over its legs (T-12259).

    A tri-state fold BESIDE `_leg_first_str` rather than a widening of it: `_leg_first_str` answers
    "which string did a leg record", and a value whose whole point is that `False` and absence are
    DIFFERENT facts cannot be read by a reader that skips both. Widening it would also re-point the
    `admission_class` fold beside it, which genuinely wants the string-or-nothing reading.

    The three states, in the order they bind:
      * a REASON TOKEN (`loadavg-unreadable` / `loadavg-malformed`) if ANY leg admitted without
        headroom evidence — degradation on one leg is degradation for the pass, so a real reason
        beats a measured sibling and is never averaged away;
      * `False` when no leg was degraded and at least one leg actually MEASURED the load;
      * `None` when no leg recorded the field at all — a record predating this change, which is
        "we do not know whether headroom was measured", not "it was".
    """
    measured = False
    for lg in ((result.get("envelope") or {}).get("legs") or {}).values():
        if not isinstance(lg, dict):
            continue
        v = lg.get("venue_headroom_degraded")
        if isinstance(v, str) and v:
            return v
        if v is False:
            measured = True
    return False if measured else None


def indeterminate_detail(result: dict) -> "str | None":
    """The fault's OWN TEXT for one executor run — the answer to "what actually failed?" (T-12364).

    THE GAP THIS CLOSES, measured: over the 20 `venue-indeterminate` aborts since 2026-09-03 (513
    minutes) the row carried its named CLASS and nothing else, so `venue-fault` read identically
    whether the box was unreachable, the mirror had orphaned, or a leg could not start. The causes
    were always present at the fault site — an exception message, a postcondition's measured facts
    — and were dropped before the row. This is the fold that stops dropping them, and it is
    REPORT-ONLY: no verdict, no retry and no self-heal reads what it returns.

    THREE SOURCES, IN ORDER, and the order is what makes it total:
      1. an EXPLICIT `indeterminate_detail` a mapping site set — but only a NON-EMPTY one. An empty
         or whitespace-only value falls THROUGH rather than being returned (audit-pre finding 2):
         an empty detail on the row reads exactly like the pre-change row this exists to end, so
         the richest source may not also be the one that can silently produce that reading.
      2. else the FAILING check roster, joined as `<check>: <detail>`. The check NAME is always
         present, so an entry whose own `detail` is the empty string (`fingerprint_present` is one)
         still contributes a readable fact instead of a bare colon. This arm is why the classes
         whose sites raise no exception — `disconnect`, `digest-mismatch`, `duplicate-or-stale`,
         `binding`, `venue-refs-clobbered` — name themselves too, with no per-site edit.
      3. else the honest last resort: name the class and SAY that no fault text was recorded.
         Saying so is the point — a reader must be able to tell "nothing was recorded" from
         "nothing went wrong", which is the distinction SPEC-0165 item 11 keeps making.

    So for an INDETERMINATE the return is NEVER empty and never None. For any other outcome it IS
    None: there is no fault to name, and fabricating one would put text on a GREEN row."""
    if (result or {}).get("outcome") != OUTCOME_INDETERMINATE:
        return None
    own = str(result.get("indeterminate_detail") or "").strip()
    if own:
        return own
    bad = [c for c in (result.get("checks") or []) if isinstance(c, dict) and not c.get("ok")]
    if bad:
        return "; ".join(f"{c.get('check')}: {str(c.get('detail') or '').strip()}".rstrip(": ")
                         for c in bad)
    return (f"no fault text was recorded for this {result.get('indeterminate_class')} outcome "
            f"— the pass reported the class alone")


def _leg_flaky_retry(result: dict) -> "dict | str":
    """T-12357 — the pass's ISOLATED-RETRY record, folded per leg — or the string `"unknown"`.
    T-12358 lifted the body into `_leg_key_fold` so the serialized-tail record folds through the
    SAME tri-state; this name stays as the retry's reader."""
    return _leg_key_fold(result, VENUE_FLAKY_RETRY_KEY)


def _leg_load_sensitive(result: dict) -> "dict | str":
    """T-12358 — the pass's SERIALIZED-TAIL record, folded per leg — or the string `"unknown"`.
    The same tri-state as `_leg_flaky_retry`, for the same reason: a `{}`/None would read as
    "nothing ran in a tail anywhere", which an old-shape envelope cannot claim."""
    return _leg_key_fold(result, VENUE_LOAD_SENSITIVE_KEY)


def _output_tail_lines(out: "str | None", *, lines: int = 40, line_chars: int = 200) -> list:
    """T-12447: the last `lines` lines of a FAILED file's raw combined output, each clipped to
    `line_chars`. Empty output is `[]` — an explicit empty tail, never an absent one. Unlike the
    runner's `_verify_failure_excerpt` (a 400-char head+tail for the abort message) this keeps the
    verbatim END of the output, where a traceback and a runner's summary sit. The runner calls it at
    both failure sites; the bounds are the record's documented shape (SPEC-0025 / SPEC-0203)."""
    return [ln[:line_chars] for ln in (out or "").splitlines()[-lines:]]


def _bounded_output_tail(entries: list, *, max_entries: int = 20) -> dict:
    """T-12447: ONE aggregate bound over `(key, lines)` pairs, in the order given. At most
    `max_entries` entries: past it, the first `max_entries - 1` keep their tails and the last slot is
    the single `(overflow)` entry naming how many were not recorded — so the map can never exceed the
    bound, and a reader is told what is missing rather than shown a silent cut. The runner applies it
    per leg and `_leg_failed_output_tail` applies it again over the combined legs — ONE function, so
    the two bounds cannot drift."""
    entries = list(entries)
    if len(entries) <= max_entries:
        return {k: v for k, v in entries}
    keep = max_entries - 1
    out = {k: v for k, v in entries[:keep]}
    out["(overflow)"] = [f"{len(entries) - keep} more failing file(s): tails not recorded"]
    return out


def _leg_failed_output_tail(result: dict) -> dict:
    """T-12447 — every leg's `venue_failed_output_tail` folded into ONE `{file: [lines]}` map.

    Candidate-leg keys stay bare, pinned-leg keys carry `[pinned/last-green] ` — so a file failing on
    both legs keeps both tails and a reader sees which leg each came from. Candidate first, each leg's
    files by name with that leg's `(overflow)` note last, then the SAME aggregate bound the runner
    applies (`_bounded_output_tail` above — one function, so the two bounds cannot drift). Returns `{}` when no leg recorded a tail (a green pass, or an old-shape leg): the
    caller writes the key only when this is non-empty, so a green row carries no such key."""
    legs = (result.get("envelope") or {}).get("legs") or {}
    entries = []
    for leg, prefix in (("cand", ""), ("pinned", VENUE_PINNED_TAIL_PREFIX)):
        rec = legs.get(leg)
        rec = rec.get(VENUE_FAILED_OUTPUT_TAIL_KEY) if isinstance(rec, dict) else None
        if not isinstance(rec, dict):
            continue
        for name in sorted(rec, key=lambda n: (n == "(overflow)", n)):
            lines = rec[name]
            entries.append((prefix + str(name),
                            [str(x) for x in lines] if isinstance(lines, list) else []))
    if not entries:
        return {}
    return _bounded_output_tail(entries)


def _leg_key_fold(result: dict, key: str) -> "dict | str":
    """T-12357 (generalized by T-12358) — ONE per-leg record `key`, folded per leg — or the string `"unknown"`.

    THE TRI-STATE IS THE POINT, and it is the SPEC-0165 item 11 reading applied to a field whose
    silent form would be a false GREEN. Three answers, and a reader must be able to tell them apart:
      * `{leg: <record>}` — this leg RAN with the field and recorded what its retry did (a leg that
        saw no failures records `null`, which reads as "no flakes on that leg");
      * `"unknown"` for a leg that DID report but whose record does not CARRY the key — an
        old-shape leg record, i.e. a box running a tree that predates this field;
      * `"unknown"` — the whole value, not `{}` and not `None` — when NO leg carries the key at all.
        `{}` and `None` would both read as "no flakes anywhere", which is exactly the direction a
        reader must not be misled in: an envelope that cannot answer must SAY it cannot answer.

    PURE and envelope-only, the shape sibling of `_leg_main_mirrored` beside it."""
    legs = ((result or {}).get("envelope") or {}).get("legs") or {}
    out: dict = {}
    any_known = False
    for leg, rec in legs.items():
        if not isinstance(rec, dict):
            continue
        if key in rec:
            out[leg] = rec[key]
            any_known = True
        else:
            out[leg] = "unknown"
    return out if any_known else "unknown"


def fold_venue_flaky_retry(verify_metrics: dict) -> dict:
    """T-12357 — the HOST-side fold: map the fragment's venue-PREFIXED `venue_flaky_retry` onto the
    ONE canonical field a LOCAL land writes from the runner, `verify_metrics.flaky_retry`, so a
    routed and a local land record on the same field and no reader has to know which venue ran.
    The fragment itself stays `venue_*`-only (T-12199 AC1); this mapping is the LAND CALLER's, run
    right after it `.update()`s the fragment. A fragment WITHOUT the prefixed key (a box on a tree
    predating it) folds the string `"unknown"` — never an absence that reads as "no flakes"
    (SPEC-0165 item 11). Mutates and returns the same dict."""
    verify_metrics["flaky_retry"] = verify_metrics.get(VENUE_FLAKY_RETRY_KEY, "unknown")
    return verify_metrics


def fold_venue_load_sensitive(verify_metrics: dict) -> dict:
    """T-12358 — the HOST-side fold of the fragment's `venue_load_sensitive` onto the ONE canonical
    field a LOCAL land writes from the runner, `verify_metrics.load_sensitive` — the exact sibling of
    `fold_venue_flaky_retry` above, for the exact reason: a routed and a local land record the
    serialized tail on the same field. A fragment WITHOUT the prefixed key (a box on a tree
    predating it) folds the string `"unknown"` — never an absence, which would read as "every
    listed file passed its tail" (SPEC-0165 item 11). Mutates and returns the same dict."""
    verify_metrics["load_sensitive"] = verify_metrics.get(VENUE_LOAD_SENSITIVE_KEY, "unknown")
    return verify_metrics


def remote_verify_row(result: dict) -> dict:
    """The BOUNDED journal payload for one executor run — identity, outcome, walls and the check
    roster's verdict, never the per-file lists (the sidecar locator names those, exactly as
    `verify_metrics.per_file_outcomes` does locally, so the row stays readable)."""
    shipped = result.get("shipped") or {}
    row = {"request": result.get("request"), "attempt": result.get("attempt"),
            "box": result.get("box"), "outcome": result.get("outcome"),
            "legs": list(result.get("legs") or LEGS), "nice": result.get("nice"),
            "indeterminate_class": result.get("indeterminate_class"),
            # T-12364 — the class SAYS WHICH KIND of fault, this says WHICH FAULT. Added to the ONE
            # bounded row shape rather than at each caller, so `venue_verify_metrics`' `venue_`
            # prefix carries it onto the abort row (`venue_indeterminate_detail`) with no new event,
            # no new emit path and no second description of the same pass.
            "indeterminate_detail": indeterminate_detail(result),
            "cand_tree": shipped.get("cand_tree"), "pinned_tree": shipped.get("pinned_tree"),
            "runner_digest": shipped.get("runner_digest"),
            "push_s": shipped.get("push_s"),
            "workers": (result.get("w_derivation") or {}).get("workers"),
            "workers_bound": (result.get("w_derivation") or {}).get("bound"),
            "all_in_wall_s": result.get("all_in_wall_s"),
            "leg_walls_s": result.get("walls") or {},
            # T-12221 — the MEASURED priority, per leg, beside the `nice` the caller ASKED for above.
            # The two are different claims and only this one is evidence: `nice` is an intent the
            # host recorded, `nice_in_effect` is `os.nice(0)` read by the leg process itself on the
            # box. A leg that silently ran unniced would look identical in `nice` alone, which is the
            # whole reason the leg records its own priority. Same per-leg shape as `leg_walls_s`.
            "nice_in_effect": {leg: (rec or {}).get("nice_in_effect")
                               for leg, rec in (((result.get("envelope") or {})
                                                 .get("legs")) or {}).items()},
            "both_legs_wall_s": (result.get("run") or {}).get("both_legs_wall_s"),
            # THE ADMISSION FIGURES (T-12241), folded over the pass's legs. `venue_verify_metrics`
            # prefixes every key here with `venue_`, so these surface downstream as
            # `venue_requests_waited_s` / `venue_max_requests` / `venue_admission_atomic` on the
            # SAME `verify_metrics` carrier `land` already emits — no new event, no second catalog.
            # The WAIT is the MAX across legs (the pass waited as long as its last-admitted leg);
            # the cap and the atomicity flag are the MIN, so a pass in which ANY leg was admitted
            # non-atomically reads 0 rather than being averaged into looking fine.
            "requests_waited_s": _leg_fold(result, "venue_requests_waited_s", max),
            "max_requests": _leg_fold(result, "venue_max_requests", min),
            "admission_atomic": _leg_fold(result, "venue_admission_atomic", min),
            # T-12260 — how long a foreign LAND held the box during this pass, folded MAX across the
            # legs (the pass was starved for as long as its worst-hit leg was). It rides the same
            # `venue_`-prefixed `verify_metrics` carrier as the admission figures above, so it
            # reaches `land_completed.data.verify_metrics.venue_overlap_land_s` with no new event and
            # no second catalog — and a `tests_failed` row can finally be read for WHY its files were
            # attributed not-in-diff, which is the reading T-12251 attempt 1 had no field for.
            "overlap_land_s": _leg_fold(result, "venue_overlap_land_s", max),
            # T-12262 — the moved-ref sets the legs reported, `{}` when none did. It rides
            # `remote_verify_row`, so it reaches `land_completed.data.verify_metrics` as
            # `venue_refs_moved` through the existing carrier: no new event type and no second
            # catalog (the `venue_requests_waited_s` precedent one line up). The RETRY is legible
            # beside it — `refs_clobber_retry` marks the second attempt, and the first attempt's own
            # row is journaled before it, so a reader sees both.
            # THE RETRY MUST NOT ERASE WHAT THE FIRST ATTEMPT SAW (audit-post pass 3). The wrapper
            # returns the SECOND attempt's result, and a retry into a healed box is clean — so a
            # bare `refs_clobbered` read here reports `{}` for exactly the pass that DID find a
            # clobber, and the moved refs would survive only in a field nothing folds. The first
            # attempt's set is therefore the FALLBACK, so `venue_refs_moved` on `land_completed`
            # names the moved refs whether the pass refused or recovered — which is the whole point
            # of carrying the key (and of the AC3 predicate that reads it).
            # UNION, NOT FALLBACK (T-12284, followup fu_ff8b65ff667d). The `or` this replaces
            # reported the first attempt's set only when the second's was EMPTY — so a pass that
            # clobbered on BOTH attempts silently dropped everything attempt 1 saw, which is the
            # same erasure one layer up from the one the fallback was added to fix. The union is
            # per-leg and sorted, so the journal row names every ref either attempt found moved.
            "refs_moved": _union_refs_moved(
                result.get("refs_clobbered"),
                (result.get("refs_clobber_first_attempt") or {}).get("refs")),
            "refs_clobber_retry": bool(result.get("refs_clobber_retry")),
            # T-12301 — the MIRROR ADVANCES, beside the moved set and on the same carrier: it reaches
            # `land_completed.data.verify_metrics.venue_main_mirrored` through the existing
            # `venue_`-prefixing, so a reader can see WHY a pass that did move the box's
            # `refs/heads/main` was not refused. Report-only: no verdict, class or retry reads it.
            # NO first-attempt UNION here, unlike `refs_moved` one line up — and the asymmetry is
            # deliberate. That union exists because the clobber RETRY replaces the refusing attempt's
            # result with a clean one, so the moved refs would be erased from the row. A mirror never
            # refuses, so it never triggers the retry, so there is no attempt for its record to be
            # erased by; folding a first attempt that by construction cannot carry one would be
            # ceremony.
            "main_mirrored": _leg_main_mirrored(result),
            # THE CLASS THE PASS WAS ADMITTED AS, and how many Stage-6 requests it was admitted
            # beside (T-12259). The class is not folded arithmetically — both legs of one request
            # carry the SAME class by construction, so the first leg that recorded one is the
            # answer and a `min`/`max` over strings would be a computation pretending to reconcile
            # something that cannot disagree. The live Stage-6 count is the MAX across legs, for
            # the same reason the wait is: the pass met the busiest box either leg met.
            "admission_class": _leg_first_str(result, "venue_admission_class"),
            "live_stage6": _leg_fold(result, "venue_live_stage6", max),
            # THE HEADROOM READING (T-12259) — THREE-STATE, so `_leg_headroom_degraded` and not
            # `_leg_first_str`: the string reader skips `False` and returns None for it, which would
            # fold a normally MEASURED box into the same value as a pre-change record carrying no
            # field at all. "we measured headroom" and "we do not know whether we did" are the
            # distinction the leg record was widened to carry, and the fold must not lose it.
            "headroom_degraded": _leg_headroom_degraded(result),
            "checks_passed": sum(1 for c in result.get("checks") or [] if c["ok"]),
            "checks_total": len(result.get("checks") or []),
            "failed_checks": [c["check"] for c in result.get("checks") or [] if not c["ok"]],
            "failing_counts": {k: len(v) for k, v in (result.get("failing") or {}).items()}}
    # T-12344 — a HEALED diverged clone main, carried ONLY when the shipped identity records one, so
    # `verify_metrics.venue_main_healed` is PRESENT on a healed pass and ABSENT otherwise (AC3): an
    # always-present null would make "healed nothing" and "a record predating this card" the same
    # reading, and the whole point of the key is that a heal is a rare fact worth spotting on the row.
    # Same carrier as everything above — no new event type, no second catalog.
    healed = shipped.get(VENUE_MAIN_HEALED_KEY)
    if isinstance(healed, dict) and healed.get("from") and healed.get("to"):
        row["main_healed"] = {"from": healed["from"], "to": healed["to"]}
    return row


# ── the local-probe leg (SPEC-0203 rule 8) ───────────────────────────────────────────────────────

LOCAL_PROBE_FILE = "local-probe-files.json"   # T-12196: the RECORDED host-sensitive set, in the same
                                              # `<test_dir>/` home as the SPEC-0132 duration table
                                              # (`verify-durations.json`) — one home for the two
                                              # recorded scheduling artifacts, no new store class.


def local_probe_set(test_dir, *, _LOCAL_PROBE_FILE=None) -> set:
    """SPEC-0203 rule 8 — read the RECORDED local-probe file names for this test dir.

    Returns a set of bare file names (the `test_*.py` names the runner discovers), so it composes
    with `_run_verify_tests(only=...)` without a path dance.

    WHY RECORDED AND NOT DERIVED. A live guess — "run it, and if it fails remotely it must be
    host-sensitive" — cannot tell a host-sensitive file from a genuinely broken one, which is the
    single reading the whole venue exists to keep honest. So the set is an authored artifact whose
    every change is a diff someone reviewed, exactly as the duration table is (`_load_verify_duration_
    table`) and for the same reason. The classification each name rests on, with its reason and the
    measured tail it was read from, lives in `dev-utilities/remote-verify-local-probe-classification.md`.

    FAIL-SAFE IN THE DIRECTION THAT EXCUSES NOTHING — this is the property to keep when editing.
    Absent -> the EMPTY set, silently (the normal state: no consumer has this artifact, and the
    kernel had none before this card). Malformed -> one stderr WARN and the EMPTY set. Both mean
    EVERY file runs remotely, so a host-sensitive one FAILS the pass loudly — rule 8's "a file that
    fails remotely and is in none of the three classes is a FAILED outcome, not an excused one".
    The inverse failure mode is the one that must stay impossible: a broken or missing artifact must
    never be able to EXCUSE a file from the verdict. This reader can only ever SHRINK the remote set,
    never widen the suite: a recorded name the glob did not discover is dropped here and reported as
    `stale` by `partition_suite`."""
    path = Path(test_dir) / (_LOCAL_PROBE_FILE or LOCAL_PROBE_FILE)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return set()
    except (OSError, ValueError) as e:
        sys.stderr.write(f"WARN: {path} unreadable ({e}) — the local-probe leg is EMPTY, so every "
                         f"discovered file runs remotely (a host-sensitive one then FAILS the pass; "
                         f"nothing is excused by an unreadable artifact).\n")
        return set()
    names = raw.get("files") if isinstance(raw, dict) else None
    if not isinstance(names, list) or any(not isinstance(n, str) for n in names):
        sys.stderr.write(f"WARN: {path} is not a {{schema, files: [name, ...]}} local-probe record — "
                         f"the local-probe leg is EMPTY, so every discovered file runs remotely "
                         f"(nothing is excused by a malformed artifact).\n")
        return set()
    return {n for n in names if n}


def partition_suite(discovered, local_probe=None, *, test_dir=None, selection=None) -> dict:
    """SPEC-0203 rule 8 — split the DISCOVERED suite into the remote pass and the narrow local leg.

    `discovered` is what the runner's own glob found (`sorted(p.name for p in
    test_dir.glob("test_*.py"))`) — never a literal count, because the suite grows. `local_probe` is
    the recorded set; when omitted it is read from `test_dir` (one of the two must be given).

    THE PARTITION IS EXACT BY CONSTRUCTION, which is what makes it checkable: `local` is
    discovered INTERSECT recorded and `remote` is discovered MINUS that intersection, so the two
    sides are disjoint and their union is the discovered set, each file exactly once. A recorded name
    the glob did NOT discover is not silently carried: it lands in `stale` (a renamed or deleted test
    whose row the classification table still holds), so the artifact's drift is SHOWN rather than
    quietly rotting.

    `local_pct` is the bound rule 8 asks to be reported so the narrow leg cannot grow unnoticed — a
    computed ratio of the discovered set, never a stored number.

    THE GOVERNED SELECTION COMPOSES WITH THE PARTITION, it does not replace it (T-12222). `selection`
    is the SPEC-0181 set the LOCAL path would have run — decided by the one selector
    (`verify_runner.governed_selection`) and passed IN, never re-derived here. When given, the two
    sides narrow TOGETHER: `remote` = selection MINUS the recorded probe set, `local` = selection
    INTERSECT it. The invariants that make the partition checkable are preserved exactly, with one
    named substitution: the sides stay DISJOINT, each file still appears at most once, and their
    union is now THE SELECTION rather than the discovered set — which is the point, because the
    files outside the selection are the ones this pass does not owe. `selection=None` (a full-suite
    land, a rebaseline, `--full`) is the pre-T-12222 behaviour byte-for-byte, and that is the
    fail-safe default: an absent decision runs EVERYTHING.

    `stale` keeps its meaning against the DISCOVERED set (a recorded name the glob did not find),
    not against the selection — a name merely outside this pass's selection is not a rotted artifact
    row, and reporting it as one would make the drift signal fire on every narrowed land."""
    discovered = sorted(discovered)
    recorded = set(local_probe) if local_probe is not None else local_probe_set(test_dir)
    found = set(discovered)
    selected = None if selection is None else (set(selection) & found)
    in_pass = found if selected is None else selected
    local = sorted(recorded & in_pass)
    remote = [f for f in discovered if f not in recorded and f in in_pass]
    counts = {"discovered": len(discovered), "remote": len(remote), "local": len(local),
              "stale": len(recorded - found)}
    if selected is not None:
        counts["selected"] = len(selected)
    return {"remote": remote, "local": local, "stale": sorted(recorded - found),
            "counts": counts, "selection_applied": selected is not None,
            "local_pct": round(100.0 * len(local) / len(discovered), 3) if discovered else 0.0}


# ── the routing seam (T-12199, SPEC-0203 rules 1-3 + 7-8) ────────────────────────────────────────
#
# THE ONE CALL SITE. `route` below is the ONLY caller of `execute_remote_verify` anywhere in `bin/**`
# (AC5, pinned by a source scan in tests/test_t12199_venue_routing.py). `land` and `task test --run`
# both reach the box through it and nowhere else, so "one executor at a time, one verdict authority"
# is a property of the code shape rather than of a convention two call sites happen to follow.

VENUE_ABORT_CLASS = "venue-indeterminate"

# ── SPEC-0203 rule 7's ONE carve-out — the SANDBOX repo (T-12272) ────────────────────────────────
#
# THE DEFECT THIS CLOSES. ~30 land/pinned-verify tests build a SYNTHETIC repo under a tmpdir and
# call `land` inside it. `venue_decision`'s `kernel` conjunct is `not _is_consumer_build()`, and
# `_is_consumer_build` compares REPO_ROOT against an ENGINE_ROOT that HONOURS `YITC_REPO_ROOT` — so
# by its own docstring "the engine-clone test sandbox is NOT a consumer", i.e. it reads KERNEL. On a
# host with a published venue that nested land therefore shipped a FIXTURE to the box and aborted
# INDETERMINATE (rule 7 forbids a local fallback), so a local «differential against main» measured
# the venue rather than the diff. Two workers misdiagnosed a real diff regression as an environment
# fault on 2026-09-08 (deviations at 09:01:01Z and 11:35:53Z). On the box no venue is published,
# which is why the SAME tests pass there — the two legs were not measuring the same thing.
#
# THE EXEMPTION IS NAMED, NEVER SILENT. Rule 7 forbids a SILENT local fallback, and that is what is
# preserved: a pass that takes this carve-out reports `SANDBOX_ROUTING_REASON` as its decision reason
# and the land records it on the row (`verify_metrics["venue_routing"]`, SPEC-0161). A reader of the
# journal can always tell an exempt pass from a routed one.
SANDBOX_ROUTING_REASON = "skipped-sandbox-repo"


def _repo_identity(path) -> "Path | None":
    """The REPOSITORY a checkout belongs to, as one canonical path — or None when undeterminable.

    `git rev-parse --git-common-dir` is the LINKED-WORKTREE-AWARE answer: for a worktree it names
    the MAIN repository's `.git`, not the worktree's own git dir, so an engine worktree resolves to
    the engine (verified: /home/dev/projects/yitc-v2-wt/T-12272 -> /home/dev/projects/yitc-v2).
    Resolved against `path` when git answers relatively, which it does from inside a main checkout.

    FAIL-SAFE BY CONSTRUCTION, in ONE direction: every failure — git absent, non-zero exit, not a
    repository, a timeout, an OSError — returns None, and None makes `sandbox_repo` claim NOTHING.
    The carve-out can therefore only ever ADD an exemption on positive evidence; no environment can
    make it silently disable a published venue, which is the property rule 7 exists to hold."""
    try:
        r = subprocess.run(["git", "-C", str(path), "rev-parse", "--git-common-dir"],
                           capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0 or not (r.stdout or "").strip():
        return None
    common = Path(r.stdout.strip())
    if not common.is_absolute():
        common = Path(path) / common
    repo = common.parent if common.name == ".git" else common
    try:
        return repo.resolve()
    except OSError:
        return None


def registered_repo_paths(registry_path) -> "set | None":
    """Every project path the HOST REGISTRY names, resolved absolute — or None when unreadable.

    Read-only over `registry.yaml` (D-0019 external territory). A RELATIVE entry resolves against
    the REGISTRY FILE's directory, never the process cwd — the `nightly._v2_projects` reading, so
    the same file answers the same way from any checkout.

    NOT `nightly._v2_projects` ITSELF, and the reason is precise rather than stylistic: that helper
    REBINDS a name-matched kernel entry to `engine_root`, and inside a test sandbox `engine_root` IS
    the sandbox — so reusing it would make every sandbox look registered and defeat the predicate
    entirely. It also filters on `methodology == yitc_v2`, which is the wrong question here: what is
    asked is «is this repository KNOWN to the host», not «is it a v2 project».

    None on an unreadable, unparseable or project-less registry — the same claim-nothing direction
    `_repo_identity` takes."""
    try:
        from lib import state                     # noqa: PLC0415 — deferred, matches this module
        data = state.load_path(Path(registry_path)) or {}
    except Exception:                             # noqa: BLE001 — a registry fault claims NOTHING
        return None
    projects = data.get("projects") if isinstance(data, dict) else None
    if not isinstance(projects, dict) or not projects:
        return None
    try:
        reg_dir = Path(registry_path).resolve().parent
    except OSError:
        return None
    out = set()
    for meta in projects.values():
        if not isinstance(meta, dict):
            continue
        raw = meta.get("path")
        if not raw:
            continue
        p = Path(str(raw))
        try:
            out.add((p if p.is_absolute() else reg_dir / p).resolve())
        except OSError:
            continue
    return out or None


def sandbox_repo(repo_root, *, registry_path=None) -> bool:
    """True iff `repo_root`'s REPOSITORY is named by NO entry in the host registry — a sandbox.

    DERIVED FROM THE REGISTRY, NEVER FROM A PATH PATTERN. A `/tmp` prefix test would be a rule about
    where a fixture happens to live today; the registry is the host's own statement of which
    repositories are real work, and it is the same source the nightly enumerates.

    BOTH SIDES ARE COMPARED AS REPOSITORY IDENTITIES (audit-pre finding 1, medium). A registry entry
    may ITSELF be a linked worktree, whose resolved path is not its repository — comparing a
    canonical identity against a raw path would then read a REGISTERED project as a sandbox and skip
    the venue on real work, the one direction this carve-out must never take. So the comparison is
    two-tier and the SECOND tier is the authority:
      (i)  a cheap membership test against the raw resolved registry paths. This is the common case
           — every current entry is a main checkout, whose identity IS its path — and it is a pure
           SHORT-CIRCUIT: it can only avoid asking tier (ii), never override its answer.
      (ii) on a miss, each registry path canonicalised through THE SAME `_repo_identity` resolver
           and compared again. N git calls (25 entries today), paid only when tier (i) misses, which
           for a real registered project it does not.

    POSITIVE EVIDENCE ONLY. An unresolvable identity, an unreadable or empty registry, or any
    exception returns False — «route exactly as today». The exemption is never taken on an
    unresolved predicate."""
    if registry_path is None:
        try:
            from lib.cli import REGISTRY_PATH     # noqa: PLC0415 — lazy, breaks the import cycle
                                                  # (the debt.py / views.py idiom). Reusing the host
                                                  # constant keeps ONE registry resolution and its
                                                  # monkeypatchability, and mints no second host
                                                  # literal (SPEC-0074 rule 4).
            registry_path = REGISTRY_PATH
        except Exception:                         # noqa: BLE001 — claim nothing
            return False
    known = registered_repo_paths(registry_path)
    if not known:
        return False
    me = _repo_identity(repo_root)
    if me is None:
        return False
    if me in known:                               # tier (i) — the short-circuit
        return False
    for p in known:                               # tier (ii) — the authority
        if _repo_identity(p) == me:
            return False
    return True


# ── T-12221 — the `kind` a Stage-6 pass (`task test --run`) declares at the routing seam. It is a
# NAMED constant rather than a literal at the two `task.py` call sites so the kind the seam sees and
# the kind the caller sends cannot drift apart.
#
# THE INTERIM STAGE-6 SPLIT IS LIFTED (T-12221, owner directive 2026-09-07T08:11:42Z + 09:08:37Z).
# T-12199 briefly returned LOCAL for this kind with the named reason `stage6-local-until-T-12220`,
# because the box-side lease was keyed by LEG ALONE and two passes sharing a leg name COLLIDED. Its
# named lift condition is MET: T-12220 shipped the request-keyed lease + the per-request leg
# worktree (SPEC-0203 rule 4), so a Stage-6 pass now routes exactly as rule 2 otherwise reads — at
# the rule-5 lower-priority arm (`venue_stage6_workers_fraction()` of W + `venue_stage6_nice()`),
# while a land leg keeps the full width at nice 0. The branch, its reason constant and its
# lift-task constant are DELETED, not disabled: a rule that named its own expiry is removed when
# the expiry arrives (CHARTER §P1 F3).
STAGE6_KIND = "task-test"

#: The BUILT-IN DEFAULT of the box-side half of the lower-priority arm — no longer the effective
#: value, which `venue_stage6_nice()` resolves (owner directive 2026-09-07T08:11:42Z, and its
#: addition «пусть эта карточка в настройки вынесет заодно»). 19 is the MINIMUM scheduler priority:
#: a Stage-6 runner receives CPU only when the land legs leave it idle. That direction is the whole
#: point — `land` is the box's primary client and the whole system's throughput rides on it, while a
#: background worker's `task test --run` can wait (measured on the box 2026-09-07: a Stage-6
#: candidate leg overlapping a land ran 383.6 s against a 241.3 s solo land leg). The leg RECORDS
#: the priority it ran at (`leg.json#nice_in_effect`), so the claim is a measured field of its own
#: envelope rather than the value the caller asked for.
VENUE_STAGE6_NICE_DEFAULT = 19

#: THE ONE name the Stage-6 nice is read under, registered PERFORMANCE-class in
#: `bin/lib/machine_settings.py` (SPEC-0193 rule 1). The value left the code because a scheduling
#: priority is a property of the MACHINE the box class was chosen for, not of any checkout — the
#: same reasoning that put `YITC_VERIFY_WORKERS` there. A LAND leg is NOT tunable and never reaches
#: this resolver: it is the primary client, its 0 is a literal at the route seam.
VENUE_STAGE6_NICE_ENV = "YITC_VENUE_STAGE6_NICE"

#: The admissible range, and it is deliberately not 0..19. The FLOOR is 1, not 0, on two grounds
#: that agree: 0 is the LAND leg's priority, so admitting it would let a knob erase the very
#: ordering this arm exists to create; and `machine_settings.coerce` refuses any numeric knob <= 0,
#: so admitting 0 here would make a value the SETTER rejects reachable through the environment layer
#: alone — two validators disagreeing about one knob. The CEILING is 19 because that is what the
#: scheduler accepts; a negative nice needs privilege and would raise a Stage-6 pass ABOVE a land.
VENUE_STAGE6_NICE_RANGE = (1, 19)


def venue_stage6_nice() -> int:
    """The effective box-side nice for a lower-priority (Stage-6) pass — never for a land.

    THE ONE READ SITE of `VENUE_STAGE6_NICE_ENV` (SPEC-0193 rule 1's read-site declaration points
    here). Precedence is SPEC-0193 rule 7 — environment > machine-scoped settings file > built-in
    default — implemented by copying the shipped sibling `remote_workers_override` wholesale rather
    than re-deriving it, so the two adjacent venue knobs in this module cannot acquire two different
    precedence shapes. Read that reuse precisely: an ABSENT or BLANK environment value falls THROUGH
    to the settings file, while a PRESENT but malformed one resolves to the BUILT-IN DEFAULT and not
    to the file. The asymmetry is deliberate and it is the safe direction — a typo in an exported
    name must never silently promote a file value the operator is not currently looking at.

    FAIL-SAFE DIRECTION IS THE LOAD-BEARING PART, as it is for the sibling: anything blank,
    non-numeric or outside `VENUE_STAGE6_NICE_RANGE` is IGNORED and the built-in 19 stands. A
    malformed value therefore degrades to the LOWEST priority — the conservative end, where a
    Stage-6 pass yields to the land — instead of to an unniced runner competing with the box's
    primary client. Being PERFORMANCE-class, this value can never travel into a verdict:
    `machine_settings.get_value` returns None for anything not performance-class, so this site
    cannot become a door for a gate-class value even by mistake."""
    raw = os.environ.get(VENUE_STAGE6_NICE_ENV)
    if raw is None or not str(raw).strip():
        try:
            from lib import machine_settings      # deferred: keeps the hot import graph unchanged
            raw = machine_settings.get_value(VENUE_STAGE6_NICE_ENV)
        except Exception:
            # Same reading as the sibling override: the settings file is an OVERRIDE LAYER and never
            # a prerequisite, so a fault in the settings STACK resolves to the default rather than
            # putting an infrastructure error on a path a verify pass runs through.
            raw = None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return VENUE_STAGE6_NICE_DEFAULT
    lo, hi = VENUE_STAGE6_NICE_RANGE
    return value if lo <= value <= hi else VENUE_STAGE6_NICE_DEFAULT


# ── T-12261 — the WIDTH half of the lower-priority arm, which was a literal until this card (SPEC-0203
# rule 5; owner directive 2026-09-08T08:08:38Z: «все параметры нужно в настройки вынести — ядер на
# тест, найс, одновременных тестов и т.д.»). Its sibling `venue_stage6_nice()` above is the PRIORITY
# half: rule 5's arm has always been two mechanisms, and until now only one of them was tunable.

#: The BUILT-IN fraction of the derived width a LOWER-PRIORITY (Stage-6) pass runs at, and the value
#: every malformed or out-of-band override falls back to. 0.5 is exactly what the `// 2` literal at
#: the route seam was, so an unset machine is byte-identical to the pre-card engine — and the
#: identity is arithmetic, not a hope: 0.5 is exactly representable in binary and `W * 0.5` is exact
#: for every W the venue can derive (W <= cores), so `int(W * 0.5) == W // 2` for every reachable W.
#: THE MEASUREMENT BEHIND THE HALF: a Stage-6 pass at half the derived width — 12 of the 48 cores on
#: ccx63 — running at nice 19 moves the box's load1 to 1-11 on its own, which is what makes four of
#: them fit inside the box a single land peaks at 25-45 on. That half is therefore not a round number
#: chosen for tidiness: `VENUE_STAGE6_MAX_CONCURRENT_DEFAULT` (4) and the `cores - cores//4` headroom
#: derivation are both computed FROM it, which is precisely why it belongs in the settings file
#: rather than in an expression — a machine that wants a different Stage-6 share currently cannot ask
#: for one without editing this file.
VENUE_STAGE6_WORKERS_FRACTION_DEFAULT = 0.5

#: THE ONE name the Stage-6 width fraction is read under, registered PERFORMANCE-class in
#: `machine_settings.INVENTORY`: it changes how fast a Stage-6 pass finishes, never which files run
#: or how they conclude — the verdict stays the envelope's, and the leg records the width it actually
#: ran at. A LAND leg never reaches this resolver: it takes the full derived W, and that is a literal
#: at the route seam for the same reason its nice 0 is — the land is the box's primary client and is
#: deliberately not tunable down by a machine file.
VENUE_STAGE6_WORKERS_FRACTION_ENV = "YITC_VENUE_STAGE6_WORKERS_FRACTION"

#: The admissible band, declared at BOTH doors (here and as the registry row's `bounds`) so
#: `config set` refuses exactly what this resolver would ignore — the `YITC_VERIFY_WORKER_NICE`
#: shape. THE INTERVAL IS (0, 1] AND THE OPEN LOWER END NEEDS NO NEW MACHINERY: `machine_settings.
#: coerce` refuses any numeric knob <= 0 BEFORE it reaches the bounds test, and this resolver applies
#: its own positivity check below for the environment layer, which never passes through `coerce` at
#: all. So an inclusive `(0.0, 1.0)` pair IS the exclusive-at-zero interval at both doors, and adding
#: exclusive-bound semantics to `Knob.bounds` would be a second validation path for a refusal the one
#: validator already performs (audit-pre finding 1, absorbed mode-b). THE CEILING is 1.0 because a
#: fraction above 1 would ask a Stage-6 pass for MORE width than the land it must yield to, inverting
#: the ordering this whole arm exists to create — the same reading that puts the nice floor at 1.
VENUE_STAGE6_WORKERS_FRACTION_RANGE = (0.0, 1.0)


def venue_stage6_workers_fraction() -> float:
    """The fraction of the derived width a lower-priority (Stage-6) pass runs at — never a land.

    THE ONE READ SITE of `VENUE_STAGE6_WORKERS_FRACTION_ENV` (SPEC-0193 rule 1's read-site
    declaration points here), resolved per call — env first, then the machine-settings file, then the
    built-in — so a later `config set` is seen without a restart. The precedence, the deferred import
    and the broad `except` around the settings STACK are copied wholesale from the shipped siblings
    `venue_stage6_nice()` / `venue_stage6_max_concurrent()` rather than re-derived, so the venue's
    knobs in this module cannot acquire different precedence shapes (SPEC-0193 rule 7; rule 6 — the
    settings file is an OVERRIDE LAYER and never a prerequisite, so a fault in the settings stack
    resolves to the default rather than putting an infrastructure error on a verify path).

    FAIL-SAFE DIRECTION, matching `venue_stage6_max_concurrent()`: a blank, non-numeric, non-positive
    or out-of-band value is IGNORED and the built-in 0.5 stands. That is the conservative end in BOTH
    directions at once — a malformed value can neither starve a Stage-6 pass down toward width 1 nor
    let it claim the full width the land leg is entitled to. Being PERFORMANCE-class it can never
    travel into a verdict: `machine_settings.get_value` returns None for anything not
    performance-class, so this site cannot become a door for a gate-class value even by mistake."""
    raw = os.environ.get(VENUE_STAGE6_WORKERS_FRACTION_ENV)
    if raw is None or not str(raw).strip():
        try:
            from lib import machine_settings      # deferred: keeps the hot import graph unchanged
            raw = machine_settings.get_value(VENUE_STAGE6_WORKERS_FRACTION_ENV)
        except Exception:                         # noqa: BLE001 — a settings fault never gates a pass
            raw = None
    try:
        value = float(str(raw).strip())
    except (TypeError, ValueError, AttributeError):
        return VENUE_STAGE6_WORKERS_FRACTION_DEFAULT
    if value != value or value in (float("inf"), float("-inf")):     # NaN / inf
        return VENUE_STAGE6_WORKERS_FRACTION_DEFAULT
    lo, hi = VENUE_STAGE6_WORKERS_FRACTION_RANGE
    if value <= lo or value > hi:                 # (0, 1] — the open end is the `coerce` reading
        return VENUE_STAGE6_WORKERS_FRACTION_DEFAULT
    return value


def stage6_workers(workers: int) -> int:
    """The Stage-6 width for a derived `workers` — the ONE place the fraction is applied.

    A function rather than an inline expression at the route seam because the same arithmetic is what
    a test asserts and what a reader compares against the pre-card `// 2`; two copies of it would be
    two things that drift. `max(1, ...)` is the pre-card floor, unchanged: a fraction can narrow a
    Stage-6 pass but can never reduce it to zero workers, which would not be a slower pass but a
    stalled one."""
    return max(1, int(int(workers) * venue_stage6_workers_fraction()))


# ── T-12259 — the two knobs the box-side STAGE-6 admission question is asked with (SPEC-0203 rule 4,
# owner directive 2026-09-08T08:08:38Z: every venue scheduling parameter is a machine-scoped knob).
# They are the Stage-6 half ONLY: a LAND is admitted by `venue_max_requests()` above, which stays the
# sole carrier of the land cap — a second land cap would be a number to keep in step with it, and the
# thing that goes wrong with two caps for one question is that they disagree.

#: The BUILT-IN concurrent-Stage-6 count, and the value every malformed override falls back to. 4 is
#: the owner's figure, and the measurement behind it: a Stage-6 pass runs on HALF the derived width
#: (12 of 48 cores on ccx63) at nice 19, and alone it moves the box's load1 to 1-11 — so four of them
#: sit inside the same box a single land peaks at 25-45 for two or three minutes.
VENUE_STAGE6_MAX_CONCURRENT_DEFAULT = 4

#: THE ONE name the Stage-6 concurrency is read under, registered PERFORMANCE-class in
#: `machine_settings.INVENTORY`: it changes WHEN a Stage-6 pass is admitted, never which files run or
#: how they conclude — the verdict stays the envelope's.
VENUE_STAGE6_MAX_CONCURRENT_ENV = "YITC_VENUE_STAGE6_MAX_CONCURRENT"

#: The admissible band, declared at BOTH doors (here and as the registry row's `bounds`) so
#: `config set` refuses exactly what this resolver would ignore — the `YITC_VERIFY_WORKER_NICE`
#: shape. The floor is 1 because 0 would DISABLE Stage-6 admission entirely rather than slow it, and
#: the ceiling is 16 because past that the halved-width passes oversubscribe any box this venue runs
#: on and the headroom test below would be doing all the work anyway.
VENUE_STAGE6_MAX_CONCURRENT_RANGE = (1, 16)


def venue_stage6_max_concurrent() -> int:
    """How many lower-priority (Stage-6) venue passes may hold the box at once.

    THE ONE READ SITE of `VENUE_STAGE6_MAX_CONCURRENT_ENV` (SPEC-0193 rule 1's read-site declaration
    points here), resolved per call — env first, then the machine-settings file, then the built-in —
    so a later `config set` is seen without a restart.

    FAIL-SAFE DIRECTION, matching `venue_stage6_nice()` rather than `venue_max_requests()`: a blank,
    non-numeric or out-of-band value is IGNORED and the built-in 4 stands. Here that is the
    conservative end in BOTH directions at once — a malformed value can neither disable Stage-6
    admission nor unbound it."""
    raw = os.environ.get(VENUE_STAGE6_MAX_CONCURRENT_ENV)
    if raw is None:
        try:
            raw = machine_settings.get_value(VENUE_STAGE6_MAX_CONCURRENT_ENV)
        except Exception:                       # noqa: BLE001 — a settings fault never gates a pass
            raw = None
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError, AttributeError):
        return VENUE_STAGE6_MAX_CONCURRENT_DEFAULT
    lo, hi = VENUE_STAGE6_MAX_CONCURRENT_RANGE
    return value if lo <= value <= hi else VENUE_STAGE6_MAX_CONCURRENT_DEFAULT


#: The BUILT-IN load1 headroom, and the value every unresolvable derivation falls back to. It is the
#: ccx63 figure (48 cores) spelled as a literal for the case where no fingerprint is available; when
#: one IS available the number is DERIVED from it (see the resolver) rather than assumed.
VENUE_STAGE6_HEADROOM_LOAD1_DEFAULT = 36.0

#: THE ONE name the Stage-6 headroom is read under — PERFORMANCE-class, same reasoning as its sibling.
VENUE_STAGE6_HEADROOM_LOAD1_ENV = "YITC_VENUE_STAGE6_HEADROOM_LOAD1"

#: The admissible band, declared at both doors. The floor is 1.0 because a headroom at or below one
#: runnable process would never admit a Stage-6 on a box that is doing anything at all; the ceiling
#: is 1024.0, comfortably above any core count this venue is raised on, so a value above it is a typo
#: rather than a policy.
VENUE_STAGE6_HEADROOM_LOAD1_RANGE = (1.0, 1024.0)


def venue_stage6_headroom_load1(fingerprint: "dict | None" = None) -> float:
    """The box load1 a Stage-6 pass must be BELOW to be admitted — the EFFECTIVE number, always.

    THE ONE READ SITE of `VENUE_STAGE6_HEADROOM_LOAD1_ENV`, resolved per call (env > machine file >
    derivation > built-in), so a later `config set` is seen without a restart. Out-of-band and
    malformed values are IGNORED and the derivation stands — the `venue_stage6_nice()` direction.

    WHY IT IS DERIVED RATHER THAN DECREED. A load threshold is meaningless without a core count, and
    the core count is a property of the box this pass was routed to, which the record's fingerprint
    already carries. Unset, the headroom is `cores - cores//4`: the rule-5 width cap is
    `cores // legs` = cores//2, and the Stage-6 arm halves that again, so cores//4 is the width one
    Stage-6 pass occupies and the remainder is what must still be free for a land to run beside it.
    On the 48-core box that is 48 - 12 = 36, the owner's figure, arrived at rather than pinned — so a
    bigger or smaller box gets a threshold that fits it without anyone editing this file.

    The RESOLVED number is what the prologue is rendered with and what the heartbeat reports, so what
    a reader sees is the value that actually decided, never a placeholder standing for a derivation."""
    raw = os.environ.get(VENUE_STAGE6_HEADROOM_LOAD1_ENV)
    if raw is None:
        try:
            raw = machine_settings.get_value(VENUE_STAGE6_HEADROOM_LOAD1_ENV)
        except Exception:                       # noqa: BLE001 — a settings fault never gates a pass
            raw = None
    if raw is not None:
        try:
            value = float(str(raw).strip())
        except (TypeError, ValueError, AttributeError):
            value = None
        if value is not None:
            lo, hi = VENUE_STAGE6_HEADROOM_LOAD1_RANGE
            if lo <= value <= hi:
                return value
    try:
        cores = int((fingerprint or {}).get("cores") or 0)
    except (TypeError, ValueError):
        cores = 0
    if cores > 0:
        derived = float(cores - cores // 4)
        lo, hi = VENUE_STAGE6_HEADROOM_LOAD1_RANGE
        if lo <= derived <= hi:
            return derived
    return VENUE_STAGE6_HEADROOM_LOAD1_DEFAULT


def venue_decision(*, kernel: bool, kind: str, record: "dict | None", record_note: str = "",
                   full_suite: bool = True, sandbox: bool = False) -> dict:
    """PURE, box-free, and therefore testable without a venue: should THIS pass run remotely?

    Returns `{"remote", "reason", "record", "note"}`. Remote iff a record is PRESENT **and** this is a
    KERNEL pass **and** the run is not a small SPEC-0181 selection. Every reason is named, because a
    pass that silently stayed local is exactly the reading the venue exists to make impossible:
      `no-venue`        nothing published (or the record did not parse — `record_note` travels with it
                        to the land tail, rule 1: an unreadable record reads ABSENT, never honoured);
      `consumer`        rule 2 — a `-C <consumer>` pass NEVER consults the record (T-12192 is the
                        later slice that gives consumers their own venue);
      `small-selection` the owner directive of 2026-09-06T13:39:24Z — a narrowed SPEC-0181 selection
                        is cheaper local than it is to ship;
      `skipped-sandbox-repo`
                        rule 7's ONE carve-out (T-12272) — the pass runs in a SANDBOX/FIXTURE
                        repository, which the host registry names no project at, so it is a nested
                        land inside a test rather than real work. `sandbox` is DECIDED BY THE
                        CALLER (`sandbox_repo`, above) and only carried here, which is what keeps
                        this function PURE and box-free: it stays testable with no venue, no
                        registry and no git tree, exactly as before this parameter existed;
      `venue`           the routing case.

    THE CARVE-OUT'S POSITION IN THE ORDER IS LOAD-BEARING, not incidental. It sits AFTER the record
    check, so the exemption is named ONLY when a venue actually exists — a pass with no record still
    reads `no-venue`, which is the accurate reason, and the carve-out never masks one that already
    applies (a consumer still reads `consumer`). Its default `False` makes every pre-T-12272 caller
    and every existing test byte-identical.

    EVERY KERNEL PASS ROUTES, STAGE-6 INCLUDED (T-12221). There is no per-KIND branch here and that
    is the point: `kind` reaches this function only so the CALLER can be named in the envelope, not
    so the decision can fork on it. A Stage-6 pass (`task test --run`, kind `STAGE6_KIND`) is
    therefore decided by exactly the three conditions above — kernel, record present, full suite —
    and differs from a land pass only in the PRIORITY its caller asks `route` for (rule 5's
    lower-priority arm: `venue_stage6_workers_fraction()` of the derived W + `venue_stage6_nice()`),
    never in WHERE it runs. The interim
    T-12199 split that kept Stage-6 local until T-12220 is deleted with this card; see the
    STAGE6_KIND block above for what it was and why its lift condition is met.
    """
    if not kernel:
        return {"remote": False, "reason": "consumer", "record": None, "note": ""}
    if not record:
        return {"remote": False, "reason": "no-venue", "record": None, "note": record_note}
    if sandbox:
        return {"remote": False, "reason": SANDBOX_ROUTING_REASON, "record": record, "note": ""}
    if not full_suite:
        return {"remote": False, "reason": "small-selection", "record": record, "note": ""}
    return {"remote": True, "reason": "venue", "record": record, "note": ""}


def route(repo_root, *, kind: str, decision: dict, local, test_dir=None,
          selection: "set | list | None" = None,
          pinned_skip: "set | list | None" = None,
          priority: str = "full", legs: "tuple | list" = LEGS,
          request: "str | None" = None, attempt: int = 1, seen: "set | tuple" = (),
          journal: "callable | None" = None, on_wait: "callable | None" = None,
          _execute=None, **executor_kw) -> dict:
    """Run this verify pass where `decision` says, and return ONE result shape for BOTH callers.

    THE RESULT CONTRACT, identical on every path: `{venue, reason, outcome, indeterminate_class,
    cand, pinned, metrics, partition, result}`. `cand`/`pinned` are the runner's own
    `"test failed: <name>"` message lists, so a REMOTE failure reads exactly like a local one and no
    caller needs a second failure vocabulary.

    LOCAL BRANCH (`decision["remote"]` false) — return `local()`'s exact return and NEVER touch the
    executor. That is AC2: with no record published the local path is byte-identical to today, which
    a test enforces with an executor stub that RAISES if it is reached.

    REMOTE BRANCH — rule 8's partition: the RECORDED local-probe files run LOCALLY through the SAME
    `local(only=...)` callable, and the discovered suite MINUS them runs on the box. The two sides are
    disjoint and their union is the discovered set (`partition_suite`), so every file runs exactly
    once and none is excused.

    INDETERMINATE NEVER BECOMES GREEN AND IS NEVER A TEST FAILURE (AC3, rule 7). It returns with its
    class and EMPTY failure lists; each caller then acts on it — `land` aborts with
    `VENUE_ABORT_CLASS`, `task test --run` FAILS the run naming the class. Neither re-runs the pass
    locally: while a venue is published, local execution is NOT an automatic fallback.

    `on_wait` is the T-12241 admission-heartbeat relay: an injected one-argument callable invoked,
    AS THE LINES ARRIVE, for each `waiting_for_venue_admission` line a leg emits while blocked on the
    machine-wide request cap. Injected for the same reason `journal` is — this module writes no
    journal of its own, and the caller that owns the row owns where it goes (CHARTER §P5).

    `priority="low"` is the lower-priority arm and it is TWO mechanisms, not one: (i) the derived
    width is scaled by `venue_stage6_workers_fraction()` (default 0.5 — the `// 2` this replaced) and
    (ii) the box-side runner is `nice`d at `venue_stage6_nice()`, which the leg records. Both halves
    are now machine-scoped knobs (T-12261); land keeps the full derived W at nice 0, tunable by
    neither.

    `selection` (T-12222) — THE SAME GOVERNED SET THE LOCAL PATH WOULD RUN. SPEC-0203 rule 2 names a
    SPEC-0132 §4 selected-suite pass as a venue pass, so routing changes WHERE a pass runs and never
    WHICH tests it owes: a small land ships its selection, a full-suite land ships nothing and the
    box runs everything. It is DECIDED BY THE CALLER — the one selector in
    `verify_runner.governed_selection` — and only carried here, so there is no second selection
    engine on the routed path (CHARTER §P5). It composes with rule 8 rather than competing with it:
    `partition_suite` splits the SELECTION into the box side and the local-probe side, so the two
    remain disjoint and every selected file still runs exactly once. `selection=None` is the
    pre-T-12222 full-suite behaviour, byte-for-byte, and is the fail-safe default.

    `pinned_skip` (T-12313) — THE SPEC-0077 §3 PINNED-LEG NARROWING, likewise DECIDED BY THE CALLER
    and only carried here. It names the census-class / touched-by-this-branch files the PINNED leg
    must not re-run, computed host-side by the one `rebaseline_currency.pinned_leg_narrowing()` the
    local driver also calls — so there is no second narrowing engine on the routed path, exactly as
    there is no second selection engine (CHARTER §P5). It is the pinned-leg counterpart of
    `selection`: that one narrows the CANDIDATE leg, this one the PINNED leg, and each is bound to
    its own leg BOX-SIDE rather than trusted of this caller. `pinned_skip=None` is the pre-T-12313
    behaviour, byte-for-byte, and is the fail-safe default.

    THE SHIPPED REF IS COMPOSED HERE, AND IT DIFFERS BY KIND (T-12425). A `land` pass ships
    `HEAD` — the merged candidate COMMIT — exactly as it always did. A STAGE-6 pass ships a
    temporary snapshot commit of the WORKING TREE, because Stage 6 precedes Stage 7 and the diff
    under test is not in any commit yet; shipping `HEAD` there asked the box about a tree without
    the change, which read false in both directions (measured 2026-09-11 — see
    `working_tree_snapshot`). The composition sits at THIS single seam rather than at either call
    site, so there is exactly one push path and the land leg's identity is byte-identical by
    construction. A snapshot that cannot be taken returns INDETERMINATE (`venue-fault`) — it is
    never quietly downgraded to a HEAD pass.

    MEASURED GROUND (the card's own differential): the first routed land shipped the whole 1394-file
    discovered suite for a `tasks/`-only filing batch whose local land runs a 505-file governed
    selection — 184.1 s of box leg to pay for a pass the local path sizes at a fifth of it."""
    execute = _execute or execute_remote_verify
    if not decision.get("remote"):
        bad = list(local())
        return {"venue": "local", "reason": decision.get("reason"), "note": decision.get("note", ""),
                "outcome": OUTCOME_GREEN if not bad else OUTCOME_FAILED,
                "indeterminate_class": None, "cand": bad, "pinned": [],
                "metrics": {}, "partition": None, "result": None}

    record = decision["record"]
    test_dir = Path(test_dir) if test_dir is not None else Path(repo_root) / "tests"
    discovered = sorted(p.name for p in Path(test_dir).glob("test_*.py"))
    partition = partition_suite(discovered, test_dir=test_dir, selection=selection)

    # WIDTH. Derived exactly where the executor derives it (rule 5's ONE home), then scaled by the
    # Stage-6 fraction for the low-priority arm — computed here because the fraction is a property of
    # THIS pass, not of the box. The `// 2` literal this replaced is now the knob's DEFAULT
    # (`VENUE_STAGE6_WORKERS_FRACTION_DEFAULT` = 0.5), so an unset machine derives the same width it
    # always did (T-12261).
    # ── THE REF COMPOSITION (T-12425) — THE ONE SEAM, kind-guarded. ────────────────────────────
    # A STAGE-6 pass ships a SNAPSHOT of the working tree; a `land` pass ships what it always did.
    # It lives HERE, at the single existing seam every routed pass already passes through, rather
    # than at either call site: a second ref-composition site would be a second push path (CHARTER
    # §P1 F1), and the land leg's identity — the merged candidate COMMIT — must stay byte-identical,
    # which "no branch taken" guarantees more cheaply than any parallel code could.
    #
    # AN EXPLICIT CALLER `ref` STILL WINS, and nothing in the tree passes one today: the override is
    # what keeps this composable for a caller that knows its own subject (the same shape `workers`
    # has just below), not a route anyone takes to opt out of the snapshot.
    #
    # A SNAPSHOT THAT CANNOT BE TAKEN IS A FAULT IN THE PASS, NOT A LICENCE TO SHIP HEAD. It maps
    # onto the INDETERMINATE outcome rule 7 already defines, under the EXISTING `venue-fault` class
    # (the closed six-class vocabulary is not widened: a half of the pass that could not run is
    # exactly what that class already means) — so `task test --run` FAILS naming the class and never
    # reports a verdict taken on the committed tree.
    if kind == STAGE6_KIND and executor_kw.get("ref") is None:
        try:
            _snapshot = working_tree_snapshot(repo_root)
        except Exception as e:                              # noqa: BLE001 — mapped, never swallowed
            return {"venue": "remote", "reason": "venue", "note": "",
                    "outcome": OUTCOME_INDETERMINATE, "indeterminate_class": "venue-fault",
                    "cand": [], "pinned": [],
                    "metrics": {"venue_indeterminate_detail": str(e),
                                "venue_snapshot_error": f"{type(e).__name__}: {e}"},
                    "partition": partition, "result": None}
        if _snapshot is not None:
            executor_kw["ref"] = _snapshot

    fingerprint = record.get("fingerprint")
    workers = executor_kw.pop("workers", None)
    if workers is None:
        workers = derive_remote_w(fingerprint, remote_duration_table(repo_root))["workers"]
        if priority == "low":
            workers = stage6_workers(workers)
    nice = venue_stage6_nice() if priority == "low" else 0

    result = execute(repo_root, record["box"], request=request, attempt=attempt,
                     workers=workers, user=record.get("ssh_user", "dev"),
                     fingerprint=fingerprint, seen=seen, journal=journal, on_wait=on_wait,
                     legs=tuple(legs), exclude=set(partition["local"]),
                     only=(list(partition["remote"]) if partition["selection_applied"] else None),
                     nice=nice, pinned_skip=pinned_skip,
                     **executor_kw)

    # THE LOCAL-PROBE LEG (rule 8) — the narrow host-sensitive set, run HERE, beside the remote pass.
    # It runs even when the remote pass came back INDETERMINATE only in the sense that it does not:
    # an INDETERMINATE is a venue fault with no verdict to complete, so the probe leg is skipped and
    # the caller aborts on the class. Running it would produce a partial green nobody asked for.
    outcome = result.get("outcome")
    if outcome == OUTCOME_INDETERMINATE:
        return {"venue": "remote", "reason": "venue", "note": "",
                "outcome": OUTCOME_INDETERMINATE,
                "indeterminate_class": result.get("indeterminate_class"),
                "cand": [], "pinned": [], "metrics": venue_verify_metrics(result, partition),
                "partition": partition, "result": result}

    # THE PROBE LEG CANNOT FAIL OPEN (rule 7). If the narrow local leg cannot RUN — an injected
    # runner that does not accept `only=`, an unreadable tree — that is a fault in the PASS, not a
    # test failure and not a licence to re-run the whole suite locally. It returns INDETERMINATE as
    # the EXISTING `venue-fault` class (the closed six-class vocabulary is not widened for it: a
    # half of the pass that could not run is exactly what that class already means), with the cause
    # carried in the metrics so the fault is localisable without a seventh name.
    try:
        probe_bad = list(local(only=set(partition["local"]))) if partition["local"] else []
    except Exception as e:                                  # noqa: BLE001 — mapped, never swallowed
        return {"venue": "remote", "reason": "venue", "note": "",
                "outcome": OUTCOME_INDETERMINATE, "indeterminate_class": "venue-fault",
                "cand": [], "pinned": [],
                # `venue_indeterminate_detail` is set HERE rather than derived from `result`
                # (T-12364): this INDETERMINATE is ROUTE's own — the executor result it wraps
                # completed, so its row carries no fault to fold. It carries the exception's own
                # message EXACTLY, like the two mapping sites above; WHICH leg faulted is not lost,
                # because the existing `venue_local_probe_error` key beside it says so and stays
                # exactly as it was.
                "metrics": dict(venue_verify_metrics(result, partition),
                                venue_local_probe_error=f"{type(e).__name__}: {e}",
                                venue_indeterminate_detail=str(e)),
                "partition": partition, "result": result}
    failing = result.get("failing") or {}
    # The leg already reports each failure in the runner's OWN `"test failed: <name>"` shape (the
    # box-side leg takes the first line of the runner's message verbatim), so the entries are passed
    # through UNCHANGED. Re-prefixing them here produced `test failed: test failed: <name>` on the
    # first real box pass — a remote failure must read EXACTLY like a local one, which is the whole
    # reason the leg carries the runner's own message rather than a bare file name.
    cand = list(failing.get("cand", [])) + probe_bad
    pinned = list(failing.get("pinned", []))
    return {"venue": "remote", "reason": "venue", "note": "",
            "outcome": OUTCOME_GREEN if not (cand or pinned) else OUTCOME_FAILED,
            "indeterminate_class": None, "cand": cand, "pinned": pinned,
            "metrics": venue_verify_metrics(result, partition), "partition": partition,
            "result": result}


def venue_indeterminate_abort_text(metrics: "dict | None" = None) -> str:
    """THE ONE HOME of `land`'s venue-indeterminate abort text (T-12364).

    A named function rather than an f-string at the `_die` call site for two reasons that are the
    same reason: the printed text and the abort ROW must not drift into two descriptions of one
    fault, and the printed half must be directly probeable without driving a land. Both halves read
    the SAME `verify_metrics` dict the abort already carries.

    The DETAIL line is appended after the class, on its own line, and is OMITTED when there is
    none — an absent line is honest about an old or detail-less row, where an empty "cause:" would
    assert that the cause is nothing."""
    metrics = metrics or {}
    detail = str(metrics.get("venue_indeterminate_detail") or "").strip()
    text = ("land ABORTED — the published venue returned an INDETERMINATE outcome "
            f"(class: {metrics.get('venue_indeterminate_class')}). This is a VENUE "
            "fault, not a test failure: no verdict was produced, so none is "
            "reported.")
    if detail:
        text += f"\nwhat failed: {detail}\n"
    return text + (
        " NO local fallback is taken while a venue is published "
        "(SPEC-0203 rule 7) — resolve the box, or `yitc-v2 venue unpublish` "
        "to return kernel verify passes to the local path, then re-run land.")


def venue_verify_metrics(result: dict, partition: "dict | None" = None) -> dict:
    """The ADDITIVE `verify_metrics` fragment — `venue_*` keys only, no new event type and no second
    catalog. The caller `.update()`s it onto the SAME `verify_metrics` dict it already hands to the
    runner and already emits verbatim as `land_completed.data.verify_metrics` (AC1's carrier).

    Sourced from `remote_verify_row` — the ONE bounded payload shape for an executor run — so the
    row and these fields cannot drift apart into two descriptions of the same pass."""
    row = remote_verify_row(result or {})
    out = {f"venue_{k}": v for k, v in row.items()}
    out["venue"] = "remote"
    # T-12357 — the pass's isolated-retry record, folded per leg, under the venue-PREFIXED key
    # (T-12199 AC1: EVERY key of this fragment is `venue_*` — an unprefixed key here would collide
    # with a runner metric of the same name, which is exactly what `flaky_retry` is on a LOCAL
    # land). The ONE canonical field the card names, `verify_metrics.flaky_retry`, is written by the
    # LAND CALLER: it maps this prefixed key onto the canonical one after it `.update()`s the
    # fragment (`cmd_land`, beside the `venue_verify_metrics` merge) — so a routed and a local land
    # still land on ONE field, and this fragment stays venue_*-only. Recorded here as the `"unknown"`
    # tri-state when no leg carries it, never silently absent (SPEC-0165 item 11).
    out[VENUE_FLAKY_RETRY_KEY] = _leg_flaky_retry(result or {})
    # T-12358 — the pass's serialized-tail record, per leg, under its venue-PREFIXED key on the same
    # terms (the caller maps it onto the canonical `load_sensitive` via `fold_venue_load_sensitive`).
    out[VENUE_LOAD_SENSITIVE_KEY] = _leg_load_sensitive(result or {})
    # T-12447 — the failed files' output tails, per file across both legs. ABSENT, never `{}`, when no
    # leg recorded one: a green pass carries no such key (T-0358), and a failing file whose output was
    # empty still has its explicit `[]` entry because the runner wrote one.
    _tail = _leg_failed_output_tail(result or {})
    if _tail:
        out[VENUE_FAILED_OUTPUT_TAIL_KEY] = _tail
    if partition is not None:
        out["venue_local_probe_count"] = partition["counts"]["local"]
        out["venue_local_probe_pct"] = partition["local_pct"]
        out["venue_remote_count"] = partition["counts"]["remote"]
        out["venue_local_probe_stale"] = partition["stale"]
        # T-12222 — WHETHER THIS ROUTED PASS SHIPPED A SELECTION, and how large it was. Without
        # these two keys `venue_remote_count` alone cannot be read: 1394 could mean "the selection
        # was that wide" or "the selection was dropped on the routed path", which is precisely the
        # defect this card fixes and therefore precisely what a later row must be able to show. The
        # discovered count travels beside it so the narrowing is legible on the row itself.
        out["venue_selection_applied"] = bool(partition.get("selection_applied"))
        out["venue_discovered_count"] = partition["counts"]["discovered"]
        if partition["counts"].get("selected") is not None:
            # ABSENT, never a fabricated zero (T-0358), on a full-suite pass that selected nothing.
            out["venue_selection_would_select"] = partition["counts"]["selected"]
    return out
