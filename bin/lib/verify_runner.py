"""verify_runner — the land-time VERIFY RUNNER, extracted byte-identical from
`bin/lib/worktree.py` (T-11519, plan `split-worktree-py-along-its-own-spec-seams-runner-`).

WHAT IS IN HERE, AND WHY THE BOUNDARY IS THE ONE IT IS. The move-set is the DESCENDANT closure of
`_run_verify_tests` — the verify runner's OWN entry point — over the parsed call graph of the host
module, plus `cmd_verify_durations` (the verb that exposes the runner's own duration table) and its
descendants. Everything the runner EXECUTES is therefore in here; its CALLERS (`cmd_land`,
`_land_integrate`) are out BY CONSTRUCTION rather than by a named exclusion someone has to remember
to write. That distinction is the whole lesson of this card: see `lessons/library-extraction.md`
§"Root the closure at the SUBJECT's own entry point", written from the two attempts that rooted at
`_SELECTION_DECISION_ROOTS` instead — the T-11463 FENCE discriminator, which answers the NEIGHBOURING
question "did this diff touch anything that participates in the selection DECISION" and comes out
too wide (with the land verb) or too narrow (without the runner) depending on the traversal.

`tests/test_verify_runner_move_set_closure.py` (T-11518) is NOT this set and was not edited to match
it. It freezes the FENCE closure — descendants UNION ancestors from the decision roots — because a
fence conservatively wants everything that FEEDS OR INVOKES the decision. An extraction boundary
wants only the mechanism. Two different questions, two different sets, both correct.

SEAM (the T-9340 / T-9341 full inject-residue shape, `lessons/library-extraction.md` §AST-freeze
generator): bodies are spliced VERBATIM from the original source — never `ast.unparse` — and every
non-stdlib free name (host stayers, host globals, AND moved siblings via their host residue) arrives
as a keyword-only injected parameter, computed with `symtable` over each function's scope subtree.
The host keeps a residue under every historical name, so the 32 test files and 8 bin/lib modules that
reference `yitc.<sym>` keep resolving and stay out of this diff.

Identity-agnostic KERNEL module (SPEC-0073 bin/ HARD class). It imports only stdlib + already-extracted
lower leaves; it NEVER back-imports the host.
"""
from __future__ import annotations

import ast
import fnmatch
import hashlib
import io
import json
import math
import os
import re
import sys
import tempfile
import time
import tokenize
import uuid
from pathlib import Path
from lib import events


# ---------------------------------------------------------------------------
# Constants moved WITH their readers: each is referenced from a moved signature DEFAULT,
# which is evaluated at def time in THIS module, so it cannot arrive by injection. The host
# keeps a re-export alias under each historical name (`yitc.<X>` callers unaffected).
# ---------------------------------------------------------------------------
_VERIFY_FAIL_EXCERPT_BOUND = 400   # T-10733: the recorded verify-failure excerpt budget (was a bare
                                   # `[-400:]` tail slice at the single call site below).
_VERIFY_FAIL_RESCUE_BOUND = 400    # T-10853: the budget for the failure-identity lines RESCUED out of
                                   # the elided span (below). Separate from the excerpt budget on
                                   # purpose: the head+tail CONTEXT and the rescued FAILURE IDENTITY
                                   # answer different questions, so growing one must not silently
                                   # squeeze the other out.
_VERIFY_FAIL_OVERBUDGET_CLIP = 240 # T-11884: how much of an OVER-BUDGET failure-identity line the
                                   # elision marker states verbatim when the rescue budget above could
                                   # afford NONE of them. Deliberately smaller than the rescue budget:
                                   # this is the last-resort identity hint, not a second rescue lane,
                                   # and it is emitted INSIDE the `[... ...]` marker so no failure
                                   # marker regex can ever match it (see `_verify_failure_excerpt`).
# T-11884: the ONE definition of the sentence that names the over-budget condition. Written by
# `_verify_failure_excerpt` and carried verbatim into the land abort_reason, so a reader looking for
# "did the runner find a failure it could not record?" has a fixed string to look for rather than a
# rendering that drifts. It opens with `[... `, which is what keeps it out of the assertion position:
# every entry in `_VERIFY_FAILURE_MARKER_RES` is `^`-anchored on `FAIL`/`FAILED`/`<Name>Error:`.
_VERIFY_FAIL_OVERBUDGET_MARK = "failure line(s) found in the elided span but over the record budget"
_SANDBOX_RESIDENT_REAP_GRACE = 2.0
_VERIFY_SLOWEST_FILES_N = 10               # T-11124: how many slowest test files a land RECORDS by name.
                                           # THE BOUND, and it is the whole design. This checkout runs 802
                                           # test files; a full per-file dump is ~55-85 bytes/entry
                                           # serialized => ~45KB PER LAND, which against the 1527
                                           # metric-bearing lands already in events.jsonl would have added
                                           # ~68MB to a ~136MB journal — a 50% growth of the entire log for
                                           # a payload nobody reads per row. Rejected by the card itself.
                                           # 10 entries + the percentile summary is ~980B/land (~1.1% of the
                                           # journal over the same 1527 lands). 10 is not a round number: the
                                           # question a duration SERIES exists to answer is "is the tail
                                           # growing", and on an 802-file suite the p99 IS the 8th-slowest
                                           # file — so N=10 covers the whole >=p99 band by construction.
_VERIFY_DURATION_SERIES_UNIT_MS = 100      # T-11315: the duration-SERIES quantum, in ms. The series
                                           # records EVERY file that started, so its cost is per-file
                                           # and the quantum is what keeps that affordable: at 100ms a
                                           # wall is 1-4 decimal digits (the SPEC-0071 per-file timeout
                                           # bounds the top end), so <=~7 bytes/file INCLUDING the
                                           # separator. 100ms is also below the resolution any
                                           # scheduling answer needs: the shortest real test file is
                                           # ~2.5s and the longest ~81s, so quantisation moves a
                                           # simulated makespan by well under a percent.

# ── T-12190 (SPEC-0203 rule 4) — the per-file OUTCOME export ────────────────────────────────────────
# WHY A SIDECAR AND NOT THE JOURNAL ROW. `_VERIFY_SLOWEST_FILES_N` above states, with its own
# arithmetic, why the journal cannot carry ~800 per-file rows per land. But the bound it chose costs
# something real, measured on the rented box (T-12183 F5): the run reported 92-94 FAILING files of
# 1387 and could name TEN of them, so the ~80 host-sensitive files could not be listed and T-12183 AC2
# was discharged as unreachable. The measurement existed in memory and was thrown away. So the FULL
# list goes to a machine-readable file on disk and the journal row carries only its LOCATOR — the row
# stays exactly as bounded as before (SPEC-0025), and a foreign-host or batch run can NAME its failed
# files instead of counting them. This is the shape the venue trial patched into a throwaway copy of
# this runner (`.yitc/venue-trial-2026-09-06/remote-verify-rehearsal.py`, its `per-file.json` dump),
# made real at the same seam.
_VERIFY_OUTCOMES_DIR_ENV = "YITC_VERIFY_OUTCOMES_DIR"   # the box-side/executor override (the trial's VENUE_OUT)
_VERIFY_OUTCOMES_DEFAULT_LEAF = "yitc-verify-outcomes"  # under the temp base, NEVER inside the checkout.
                                           # THE DEFAULT IS OFF-TREE BY CONSTRUCTION, and it is not a
                                           # tidiness preference — measured at Stage 6. Writing the
                                           # export into the verified checkout (`.yitc/`) is clean in
                                           # THIS repo, whose .gitignore covers `.yitc/`, and is
                                           # land-blocking dirt in a repo whose does not: three pinned
                                           # sandbox scenarios (test_pinned_verify / test_land /
                                           # test_t12151_pinned_first) build synthetic repos without
                                           # that ignore line and their lands refused with
                                           # "worktree has uncommitted non-journal changes: .yitc/".
                                           # A report that can refuse the land it reports on is the one
                                           # thing this export must never be, and depending on every
                                           # verified repo carrying an ignore line is a promise the
                                           # runner cannot keep. The temp base is the one the run
                                           # already uses (`_install_verify_tmpdir` / YITC_VERIFY_TMPDIR).
_VERIFY_OUTCOMES_KEEP = 50                 # newest N exports kept per directory. A per-run file is
                                           # unbounded growth otherwise, and the reader of an export is
                                           # the run that just made it (or the executor that named the
                                           # path): 50 is a few days of lands on this checkout, enough
                                           # to look back at a recent failure and small enough that the
                                           # dir never becomes a store. Pruning is newest-first by name
                                           # (the name is timestamp-ordered) and never touches a file it
                                           # did not write the shape of.
_VERIFY_OUTCOMES_SCHEMA = 1


# ── T-11537 (SPEC-0152 rule 16) — a routed tests/** layer must be able to COVER the routed surface ──
#
# THE HOLE, measured and not suspected. The delegation predicate below hands the whole root `tests/`
# surface to a declared layer on two tests: the layer is EXECUTABLE (`_executable` — not waived, a
# non-empty `command:`) and its `covers:` names tests/. "Executable" proves the layer RUNS. It proves
# nothing about the layer being able to COVER anything — so a layer whose whole command is `true`
# passed both, silently REPLACED the bare sweep, and the land read green while the suite that would
# have caught a defect never ran. The routing leg (T-10811) inherited the same gap one step further
# out: it re-checks the routed layer in THIS carrier by NAME + `_executable` alone, so a candidate
# could route tests/ to a last-green layer that does nothing. Pre-existing and orthogonal to T-11253 —
# the external consult `decisions/t11253-c2-fence-audit-adhoc.yaml` (GREEN) judged finding (4) true:
# an operator landing the route ALONE reaches the same state.
#
# THE DISCRIMINATOR IS A CLOSED ENUMERATION, and that bound is the design — not a limitation being
# apologised for. This is a GATE, so its fail-safe direction is "any doubt runs the sweep"; but the
# doubt has to be PROVABLE, because a discriminator that fired on "this command looks weak" would
# refuse legitimate routings and turn the fence into refuse-all (the card's AC2). So it asks the
# NARROW PROVABLE question — «is this command one of the shell's own do-nothing atoms?» — exactly the
# shape `lessons/a-signal-about-a-reader-fails-safe-the-opposite-way-to-a-gate.md` records for the
# devnull-not-isatty case. `bash scripts/verify.sh`, `pytest tests/`, an unparseable string: NOT
# provable, honoured unchanged. `sh -c true` is deliberately NOT caught — widening this to a shell
# parser would re-introduce the guessing the enumeration exists to remove.
_DELEG_NOOP_COMMANDS = frozenset({"true", ":", "/bin/true", "/usr/bin/true", "exit 0"})



def _consumer_tests_delegation(worktree: Path, *, _is_consumer_build, _read_yaml,
                               routing_from: "Path | None" = None, CONSUMER_OPS_CONTRACT=None,
                               _glob_names_sweep_dir=None,
                               sweep_dirs=None, routing_sweep_dirs=None) -> "str | None":
    """SPEC-0152 rule 16 (T-10438 / X-0297) — the tests-sweep DELEGATION predicate. Returns the NAME of
    the declared verify layer that covers the root tests dir (so the kernel's bare-python3 sweep over
    `tests/test_*.py` is redundant and is SKIPPED), or None to run the sweep as before.

    WHY. On a `-C` consumer the kernel runs BOTH halves at land: the bare sweep (`_run_verify_tests` —
    each test file via `python3 <f>`, the ENGINE suite convention) AND the declared `verify.layers`
    commands (`_consumer_zero_probe_guard`). A pytest/venv consumer therefore has to make EVERY test file
    script-runnable under the SYSTEM python3 — and then its layer re-runs the same suite properly. When a
    layer says it covers `tests/`, the layer IS the verify for that surface (rule 5: verify.layers is the
    single authoritative land-verify home, never two live homes) — so the bare sweep delegates to it.

    NO VERIFY HOLE: this skips only the redundant sweep. The layer itself still runs (the guard is
    untouched), so the tests are verified by the layer that claims them. Every caller must call the guard.

    FAIL-CLOSED — any doubt runs the sweep (None):
      * the engine's OWN build (`_is_consumer_build()` False) — inert, unchanged;
      * an absent / unreadable / malformed `yitc-ops.yaml` (never skip a gate on a carrier we cannot read);
      * a SECTION-level `verify.waiver` — the guard SHORT-CIRCUITS on it, so the layers do NOT run;
        delegating there would leave the tests verified by nothing (a real hole);
      * a layer that is WAIVED, carries no executable `command:`, or names no `covers:` glob under tests/;
      * a layer that names tests/ but whose whole `command:` is a PROVABLE no-op (T-11537,
        `_noop_command`) — it claims the surface and covers nothing, so delegating to it would skip
        the sweep for a layer that verifies nothing. The refusal is REPORTED, naming the layer
        (`_report_refusal`), never a silent fall-through to the sweep. The discriminator is a CLOSED
        enumeration of shell do-nothing atoms: an unrecognised command is HONOURED unchanged, so the
        fence never becomes refuse-all-routing.

    ROUTING_FROM — the CANDIDATE-carrier routing (T-10811 / X-0657). The SPEC-0077 pinned last-green
    re-run evaluates this predicate on a worktree whose `yitc-ops.yaml` is the LAST-GREEN overlay, while
    the candidate's NEW test files survive in its `tests/` (the overlay restores last-green's files, it
    does not delete extra ones). So a consumer ADOPTING delegation in the SAME land as the test file that
    needs it hit a bootstrap trap: candidate verify fully GREEN, pinned bare sweep RED → LAND: ABORT
    (kupiclub T-0110). With `routing_from` set, when THIS carrier does not itself delegate, the ROUTING
    (which layer answers for tests/) is read from that carrier instead — but honoured ONLY IF the named
    layer is one THIS carrier will actually RUN (present, non-waived, with an executable `command:`, and
    no section-level `verify.waiver`) AND whose command here is not a provable no-op (T-11537 — running
    is not covering; matching the routed name against executability alone let a candidate route tests/
    to a last-green layer that does nothing).

    NOT A SELF-APPROVAL HOLE: the CHECKS still come from THIS (pinned/last-green) carrier — both the
    overlaid tests/ and the `verify.layers` commands the guard executes. Only the ROUTING among those
    already-last-green layers is read from the candidate. A candidate that delegates AWAY to nothing (a
    layer absent / waived / commandless here, or a section waiver here) routes to a layer that will not
    run → refused → the sweep still fires → the ABORT survives.
    """
    if not _is_consumer_build():
        return None

    def _ops(wt: "Path | None"):
        """The carrier read, fail-closed to None on any doubt (absent / unreadable / malformed)."""
        if wt is None:
            return None
        try:
            p = wt / CONSUMER_OPS_CONTRACT
            return _read_yaml(p) if p.exists() else None
        except Exception:   # unreadable/malformed carrier — the guard reports it; never delegate on it
            return None

    def _layers(ops) -> "list | None":
        """The declared layer list, or None when this carrier delegates NOTHING by construction: no
        `verify` section, or a SECTION-level waiver (the guard short-circuits on it, so the layers do NOT
        run — delegating there would leave the tests verified by nothing)."""
        ver = ops.get("verify") if isinstance(ops, dict) else None
        if not isinstance(ver, dict) or isinstance(ver.get("waiver"), dict):
            return None
        return ver.get("layers") if isinstance(ver.get("layers"), list) else []

    def _noop_command(command) -> "str | None":
        """T-11537 — the no-op atom this layer's `command:` provably IS, or None when it is not
        provably one. A CLOSURE, like every other helper of this predicate: it has no caller outside
        the delegation decision, and a top-level def here would owe a host forwarding residue it has
        nobody to forward for (T-11519/T-11520 extraction-completeness).

        Pure + total. Case-SENSITIVE (a shell is: `TRUE` is not `true`). Tolerates surrounding
        whitespace and ONE optional trailing `;` — the two spellings the same atom is routinely
        written in — and nothing more: a COMPOUND command is not decomposed, because a compound is
        where a real command hides and mis-reading one would refuse a routing that verifies
        something."""
        text = str(command or "").strip()
        if text.endswith(";"):
            text = text[:-1].strip()
        text = " ".join(text.split())      # collapse runs, so `exit  0` reads as `exit 0`
        return text if text in _DELEG_NOOP_COMMANDS else None

    def _report_refusal(layer: str, command: str, carrier) -> None:
        """T-11537 — the NEVER-SILENT half. SPEC-0152 rule 16 already requires that a gate which stops
        running says so and names what covers the surface instead; the symmetric obligation is that a
        gate which KEEPS running says why it refused the delegation it was offered. Without this the
        operator sees only a bare sweep and cannot tell it apart from a project that never declared a
        routing at all — the exact indistinguishability that let the no-op layer sit unnoticed.

        stderr, so it never contaminates a stdout channel a caller parses; wrapped, so a reporting
        failure can never turn a total predicate into an exception on a land path."""
        try:
            print(f"tests-sweep delegation REFUSED: verify layer '{layer}' declares `covers:` over "
                  f"tests/ but its whole command is the no-op `{command}` — it cannot cover the "
                  f"surface it claims, so it does NOT replace the kernel's bare tests/ sweep, which "
                  f"still runs (SPEC-0152 rule 16, fail-closed). Carrier: {carrier}. Give the layer a "
                  f"command that runs the suite, or drop the tests/ glob from its `covers:`.",
                  file=sys.stderr)
        except Exception:
            pass

    def _executable(ly) -> bool:
        """A layer entry that actually RUNS: not waived, with a non-empty `command:` to delegate TO."""
        return (isinstance(ly, dict) and not isinstance(ly.get("waiver"), dict)
                and bool(str(ly.get("command") or "").strip()))

    def _covering_layer(ops, dirs, carrier) -> "str | None":
        # T-11204 (SPEC-0185 §1(a)) — the predicate asks about the directory the kernel would ACTUALLY
        # sweep in THAT tree rather than the literal `tests`. The dirs arrive as a VALUE, one set per
        # carrier, RESOLVED BY THE CALLER — deliberately, and not merely for convenience: resolving
        # them here would make the runner EXECUTE the host's declaration resolver, which is exactly
        # what `tests/test_verify_runner_extraction_complete.py` (T-11520) forbids — the runner's
        # closure must stay inside `bin/lib/verify_runner.py`, and a caller falls outside it by
        # construction. So the host resolves, the runner compares. `None` -> the historical root
        # literal, which keeps the engine's own build and every caller that resolves nothing
        # byte-identical.
        dirs = tuple(dirs) if dirs else (_ROOT_TEST_SWEEP_DIR,)
        for ly in (_layers(ops) or []):
            if not _executable(ly):
                continue
            covers = ly.get("covers")
            if not isinstance(covers, list):
                continue
            # EVERY resolved sweep dir must be covered by THIS layer, not merely one of them
            # (audit-pre pass-3 finding, high, absorbed mode-a). Once the sweep set can hold more than
            # one directory, an `any()` here would let a layer covering `backend/tests/**` delegate
            # away a root `tests/` suite it does not cover — the bare sweep skipped, nothing else
            # running it, and the land green. That is a NEW verify hole created by the widening, so it
            # is closed at the widening. Byte-identical for every project that resolves a single
            # sweep dir (all of them today): "covers all of {tests}" IS "covers tests".
            if not all(any(_glob_names_sweep_dir(g, (d,)) for g in covers) for d in dirs):
                continue
            name = str(ly.get("layer") or "").strip() or "?"
            # T-11537: `_executable` proved the layer RUNS; this proves it can COVER something. A
            # layer whose whole command is a provable no-op claims tests/ and verifies nothing, so it
            # never becomes the delegate — the bare sweep keeps guarding the surface, out loud.
            # ORDER IS LOAD-BEARING and unchanged by T-11204: the coverage test above decides whether
            # this layer is even a CANDIDATE delegate, so the no-op refusal is only reported for a
            # layer that actually claims the swept dirs — a layer covering nothing must stay silent.
            noop = _noop_command(ly.get("command"))
            if noop is not None:
                _report_refusal(name, noop, carrier)
                continue
            return name
        return None

    own = _ops(worktree)
    hit = _covering_layer(own, sweep_dirs, worktree)
    if hit is not None:
        return hit
    if routing_from is None:
        return None
    routed = _covering_layer(_ops(routing_from), routing_sweep_dirs, routing_from)
    if routed is None:
        return None
    # The routed layer must be one THIS carrier RUNS — else the candidate would delegate away to nothing.
    for ly in (_layers(own) or []):
        if not _executable(ly) or (str(ly.get("layer") or "").strip() or "?") != routed:
            continue
        # T-11537: and it must be one this carrier runs to some EFFECT. Matching the routed name
        # against `_executable` alone was the whole of the T-10811 check, so a candidate could route
        # tests/ to a last-green layer that does nothing — the routing face of the same hole.
        noop = _noop_command(ly.get("command"))
        if noop is not None:
            _report_refusal(routed, noop, worktree)
            return None
        return routed
    return None

def _degutter_verify_line(ln: str, *, _PYTEST_FAILURE_GUTTER_RE=None) -> str:
    """T-10819: the NORMALIZED text of one verify-tail line — pytest's failure gutter (`E   <text>`, or
    `>   <source>`) stripped, every other line returned unchanged.

    Why this exists: a BARE pytest invocation prints its traceback at column 0, but every WRAPPED verify
    layer (a script/Docker layer running pytest inside it — SPEC-0152 rule 16 delegation) renders the
    failure BODY in the gutter, so the assertion never starts at column 0. Without this the extractor's
    scans matched nothing there and fell through to the last-non-empty-line fallback, i.e.
    container/teardown noise (X-0687: the assertion `assert '200-000' == '200-000-000'` sat in the
    captured blob while the block showed `[docker] container exited with code 1`). A line with no gutter
    normalizes to ITSELF, so the bare-pytest path is byte-for-byte unchanged.

    T-10853 re-homed this from `bin/yitc-v2` (thin residue kept there) so the sibling excerpt rescue
    below matches a GUTTERED failure line by the same rule the extractor reads it by."""
    m = _PYTEST_FAILURE_GUTTER_RE.match(ln)
    return ((m.group("rest") or "").strip() if m else ln)

def _duration_series(entries: "list", unit_ms: int = _VERIFY_DURATION_SERIES_UNIT_MS) -> "dict":
    """T-11315 — the COMPACT WHOLE-distribution series. PURE over the same
    `entries` = [(file, wall_ms, outcome), ...] the bounded record above summarises.

    WHY IT EXISTS. `slowest_files` publishes TEN of ~877 files, and with ten visible no question
    about the SHAPE of a run can be answered, only bounded: the union of the recorded top-tens over
    416 historical runs yields 45 distinct files, and every estimate about the other 830 had to
    ASSUME something (the standing simulation assumed them flat at 2.55s, which erases the mid-tail
    and understates the gain it computes). The runner already measures every file; only the
    PUBLICATION was truncated. So this key represents EVERY file that STARTED — that is its atomic
    rule — while staying inside a stated byte ceiling.

    WHAT IT IS FOR, and hence what it must carry. Two open questions are settled from ONE recorded
    run, offline, with no extra verify: (1) longest-first vs the current alphabetical dispatch, and
    (2) the skip-top-N curve. Both are LIST-SCHEDULE simulations over a worker pool, and both need
    exactly two things — the DURATION MULTISET (for any reordering, incl. longest-first and the
    skip curve) and the DISPATCH ORDER (to reproduce the CURRENT alphabetical schedule as the
    baseline). Neither needs the file NAMES, and the names are what the raw dump spends its bytes
    on. Hence: durations only, in dispatch order.

    THE SHAPE.
      • `walls_ds` — one quantised wall per started file, comma-joined, in NAME order. Recording
        completion order instead would silently make the alphabetical baseline arm of the simulation
        wrong, so the values are emitted against a sort this function performs ITSELF (`sorted` by
        file name) and never against whatever order the pool happened to receive.
        **T-11316 amends what that order MEANS, not what it IS.** Until T-11316 name order WAS the
        runner's dispatch order, and this key was described as such. The runner now dispatches
        longest-recorded-first (`_verify_dispatch_order`), so the two have parted: `order:
        "alphabetical"` remains exactly TRUE as a statement about how these values are laid out —
        which is all any reader needs, since the alphabetical BASELINE is what the simulation
        reconstructs — but it is no longer a description of the schedule that actually ran. A reader
        wanting the schedule that ran must take it from the duration table, not from this key.
      • `unit_ms` — the quantum the values are expressed in; a reader multiplies. Round-to-NEAREST,
        CLAMPED to >= 1 unit: a started file always cost something, and a zero would be a free job
        that flatters every schedule it appears in.
      • `count` — how many values `walls_ds` carries. Stated so a reader can assert
        `count == sample_count` rather than infer completeness from a string it parsed.
      • `order` — named, not implied, so a later change of dispatch order cannot silently
        invalidate archived rows: a reader that does not recognise the value stops.

    PER-REPOSITORY BY CONSTRUCTION. This rides `land_completed` on the journal of the repo whose
    suite ran, so the kernel's 877 files and a consumer's entirely different suite never share a
    table. There is deliberately no cross-repo duration store here; a reader (T-11316) must take
    the table belonging to the repo it schedules.

    REPORT-ONLY. Nothing consumes this to order, skip, or gate anything — recording the number is
    this card, acting on it is not (the reorder is a separate card, decided ON this number)."""
    if not entries:
        return {}
    unit = max(1, int(unit_ms))
    ordered = sorted(entries, key=lambda e: e[0])          # dispatch order = the runner's sorted glob
    walls = [max(1, (int(w) + unit // 2) // unit) for _f, w, _o in ordered]
    return {"order": "alphabetical", "unit_ms": unit, "count": len(walls),
            "walls_ds": ",".join(str(v) for v in walls)}

# The kernel's historical answer to "where do this project's tests live" — a ROOT-LEVEL `tests/`.
# It survives as the FAIL-CLOSED DEFAULT of `_declared_test_sweep_dirs` (its home is
# `bin/lib/worktree.py`, which reads THIS constant, so the two can never drift apart), never as an
# assumption made ahead of the declaration: the engine's own build, a carrier-less repo and an
# unparseable carrier all resolve to exactly this, so every project shaped the kernel's old way is
# unchanged.
_ROOT_TEST_SWEEP_DIR = "tests"


def _glob_names_sweep_dir(g, sweep_dirs=(_ROOT_TEST_SWEEP_DIR,)) -> bool:
    """True iff the `covers:` glob `g` names one of the directories the kernel test sweep WOULD have
    run — `sweep_dirs`, as resolved from this consumer's declaration by `_declared_test_sweep_dirs`.

    T-11204 (SPEC-0185 §1(a)). This predicate used to compare the glob's first segment against the
    LITERAL `tests`, which rejected a `covers: [backend/tests/**]` declaration BY CONSTRUCTION: the
    delegation could never fire for a project whose suite is not at the repo root, however completely
    it declared one. The comparison is now against the RESOLVED sweep set, so the question the
    predicate asks — "does this layer cover the directory the kernel would otherwise sweep?" — is
    finally asked about the directory the kernel actually sweeps. The default keeps every caller that
    does not resolve a set (and the engine's own build) byte-identical.

    Same first-segment convention `_undeclared_source_layers` uses to match a glob to a layer, applied
    at the resolved directory's DEPTH: for `sweep_dirs=("tests",)`, `tests`, `./tests/**` and
    `tests/**/*.py` all match; for `sweep_dirs=("backend/tests",)`, `backend/tests` and
    `backend/tests/**` match. A glob naming a directory NOT in the set does not match — `src/tests/**`
    is a nested tests dir the sweep never globs unless the declaration put it in the set.

    Only ONE optional leading `./` is normalized. An ABSOLUTE (`/tests/**`) or PARENT-RELATIVE
    (`../tests/**`) glob is REJECTED outright, never normalized into a match: `covers:` is declared
    repo-relative (SPEC-0152 rule 16), and such a glob names a tree OUTSIDE this repo — it cannot answer
    for the dir the sweep would have run, so delegating on it would open the very verify hole the
    predicate is fail-closed against (audit-post finding, absorbed mode-a)."""
    if not isinstance(g, str):
        return False
    head = g.strip()
    if head.startswith("./"):
        head = head[2:]
    if head.startswith("/") or head.startswith("../"):
        return False
    parts = [seg for seg in head.split("/") if seg not in ("", ".")]
    for d in (sweep_dirs or (_ROOT_TEST_SWEEP_DIR,)):
        want = [seg for seg in str(d).split("/") if seg not in ("", ".")]
        if want and [s.lower() for s in parts[:len(want)]] == [s.lower() for s in want]:
            return True
    return False

_VERIFY_TMPDIR_ENV = "YITC_VERIFY_TMPDIR"   # T-12185: the ONE opt-in lever that relocates a verify run's
                                           # temp base (e.g. a tmpfs). UNSET = byte-identical to the
                                           # platform default; there is deliberately NO machine-settings
                                           # key and NO config verb for it (see `_install_verify_tmpdir`).

#: T-12262 — the venue-record carrier, spelled here because this module must not import `lib.venue`
#: (that module imports `lib.remote_verify`, which imports this one — the same import-graph constraint
#: `lib/host_paths.py` exists for). It is NOT a second declaration: `lib.venue.RECORD_ENV` stays the
#: HOME of the name, and tests/test_t12262_venue_refs_immutable_under_suite.py pins the two equal, so
#: a rename there fails loudly here instead of silently unsealing every verify child.
_VENUE_RECORD_ENV = "YITC_VENUE_RECORD"

def _install_verify_tmpdir() -> "str | None":
    """T-12185 — point THIS process's temp base at `YITC_VERIFY_TMPDIR`, or do nothing.

    WHY AN ENV VAR THAT MOVES `TMPDIR`, rather than a sandbox-root argument. The verify has TWO
    readers of the temp base that must agree: the per-run sandbox `mkdtemp` (`_run_verify_tests`) and
    the SPEC-0132 Rule 1 disk/inode statvfs (`_host_resource_headroom`, which measures
    `tempfile.gettempdir()`). Moving only the sandbox would leave Rule 1 knowingly measuring /tmp
    while the work lands elsewhere. Following the TEMPFILE SEAM instead makes both move together BY
    CONSTRUCTION — no `dir=` argument, no rewiring of headroom, and no NEW gate: a root too small for
    one worker surfaces as the EXISTING Rule 1 headroom refusal, with its existing message.

    That the relocated root feeds a REFUSAL is exactly why this is an INVOCATION-SCOPED env var and
    not a machine-settings entry (where a GATE-class key is refused hard).

    FAIL-SAFE, never fail-closed: an absent / uncreatable / non-writable root falls back to the
    platform default, reports ONE line, and returns None — this lever must never refuse a verify of
    its own. IDEMPOTENT: re-installing an already-installed base is a no-op, so the two call sites
    cannot fight. Note `tempfile.gettempdir()` MEMOIZES into `tempfile.tempdir`, so setting the env
    var alone would be silently ignored in a process that already resolved a temp dir; both are set —
    `tempfile.tempdir` for THIS process, the env var for the children it spawns."""
    import tempfile as _tf
    root = (os.environ.get(_VERIFY_TMPDIR_ENV) or "").strip()
    if not root:
        return None                      # the default path: nothing read, nothing mutated
    if _tf.tempdir == root and os.environ.get("TMPDIR") == root:
        return root                      # already installed (idempotent)
    try:
        Path(root).mkdir(parents=True, exist_ok=True)
        probe = Path(_tf.mkdtemp(prefix=".yitc-tmpdir-probe-", dir=root))
        probe.rmdir()
    except Exception as e:
        sys.stderr.write(f"yitc-v2: {_VERIFY_TMPDIR_ENV}={root} unusable ({e.__class__.__name__}: {e}) "
                         f"— falling back to the platform temp base {_tf.gettempdir()}\n")
        return None
    events.record_pre_lever_temp_base(_tf.gettempdir())   # before the move — see its reader there
    _tf.tempdir = root
    os.environ["TMPDIR"] = root
    return root

def _host_resource_headroom(*, _probe: "dict | None" = None, _VERIFY_FD_RESERVE=None, _VERIFY_PER_WORKER_DISK_MB=None, _VERIFY_PER_WORKER_FD=None, _VERIFY_PER_WORKER_INODES=None, _VERIFY_PER_WORKER_MEM_MB=None, _VERIFY_PER_WORKER_PROC=None, _VERIFY_PROC_RESERVE=None, _VERIFY_UNMEASURED_FALLBACK=None, _mem_available_mb=None) -> dict:
    """SPEC-0132 Rule 1 — the per-resource admissible verify-worker counts (int ≥ 0), MEASURED live, one
    entry for EVERY dimension {cpu, mem, fd, pid, disk, inode}. A dimension that cannot be measured on
    this host is NOT omitted — it contributes `_VERIFY_UNMEASURED_FALLBACK` (fail-closed: the governor's
    min is never cpu-count-alone, audit-pre P1-F1). `_probe` (test-only) injects a synthetic raw state.
    Pure read, no state."""
    if _probe is not None:
        return dict(_probe)
    import resource as _res
    import tempfile as _tf
    # T-12185: follow `YITC_VERIFY_TMPDIR` BEFORE the statvfs below, so the disk/inode dimensions —
    # and therefore the land-admission `_verify_worker_bound()` — measure the SAME filesystem the run
    # will actually consume. Unset = no-op, byte-identical to before.
    _install_verify_tmpdir()
    fb = _VERIFY_UNMEASURED_FALLBACK
    hr = {"cpu": max(1, os.cpu_count() or 4)}   # cpu is always measurable — the one guaranteed-bounded dimension
    mem_mb = _mem_available_mb()
    hr["mem"] = (mem_mb // _VERIFY_PER_WORKER_MEM_MB) if mem_mb is not None else fb
    try:
        nofile = _res.getrlimit(_res.RLIMIT_NOFILE)[0]
        hr["fd"] = (max(0, nofile - _VERIFY_FD_RESERVE) // _VERIFY_PER_WORKER_FD
                    if nofile not in (_res.RLIM_INFINITY, None) else fb)
    except Exception:
        hr["fd"] = fb
    try:
        nproc = _res.getrlimit(_res.RLIMIT_NPROC)[0]
        hr["pid"] = (max(0, nproc - _VERIFY_PROC_RESERVE) // _VERIFY_PER_WORKER_PROC
                     if nproc not in (_res.RLIM_INFINITY, None) else fb)
    except Exception:
        hr["pid"] = fb
    try:
        st = os.statvfs(_tf.gettempdir())
        hr["disk"] = (st.f_bavail * st.f_frsize) // (1024 * 1024) // _VERIFY_PER_WORKER_DISK_MB
        # some filesystems report 0 total inodes (inode-less) → that dimension is unmeasurable here → fallback
        hr["inode"] = (st.f_favail // _VERIFY_PER_WORKER_INODES) if st.f_files else fb
    except Exception:
        hr["disk"] = fb
        hr["inode"] = fb
    return hr

def _is_verify_failure_line(ln: str, *, _VERIFY_FAILURE_MARKER_RES=None, _degutter_verify_line=None) -> bool:
    """T-10853: does this raw verify-output line CARRY a failure identity? De-guttered first, so a
    wrapped layer's `E   AssertionError: ...` is recognised exactly as a bare run's column-0 one."""
    norm = _degutter_verify_line(ln).strip()
    return bool(norm) and any(rx.match(norm) for rx in _VERIFY_FAILURE_MARKER_RES)

def _is_verify_implementation_touch(changed_files, *, _VERIFY_IMPLEMENTATION_GLOBS,
                                    test_file_names=None, reachability_freed=None, _verify_implementation_touch_globs=None) -> bool:
    """True iff ANY changed path touches the verifier's own executable/config surface (SPEC-0077 §1) —
    the NARROW `verify-implementation-touch` predicate, NOT SPEC-0064's broad `observable` set (see
    _VERIFY_IMPLEMENTATION_GLOBS). `changed_files` are REPO_ROOT-relative repo paths (as
    `_diff_touched_files` / `_merged_tree_delta_paths` produce), so this is consumer-aware by
    construction: the SAME globs apply under each checkout's own REPO_ROOT, protecting the engine's own
    lands and every `-C` consumer's lands by one code path. A leading `./` is normalised (mirrors
    `_inert_path_class`). An empty set → False (a no-op land touches no verifier surface). Pure: reads no
    state, mutates nothing — CARD B (T-1192) wires it into the land verify step.

    Since T-11460 this is a thin delegate over `_verify_implementation_touch_globs` (one matching
    carrier — see its docstring). Behaviour is byte-identical: `any(...)` over the same globs, the
    same `./` normalisation, the same empty-set-is-False."""
    return bool(_verify_implementation_touch_globs(
        changed_files, _VERIFY_IMPLEMENTATION_GLOBS=_VERIFY_IMPLEMENTATION_GLOBS,
        test_file_names=test_file_names, reachability_freed=reachability_freed))

def _live_journals(checkout) -> "list[Path]":
    """T-10401 — every LIVE journal-mechanism store a test process must never append to.

    TWO INSTANCES of the ONE journal mechanism (CHARTER §P5 as amended by SPEC-0084 rule 5: "one
    journal" means one line-format / parser / append+union-merge discipline, NOT one physical FILE):

    (a) the REPO journals — the verified checkout's own events.jsonl plus every sibling worktree's
        (`git worktree list --porcelain`). MAIN's is the load-bearing entry: a land-verify runs FROM a
        worktree, but the leaking append resolved its target via `_main_worktree(REPO_ROOT)` — i.e.
        MAIN — so guarding only the running checkout would miss exactly the path that leaked.

    (b) the kernel-owned SHARED COORDINATION store (T-11025). It is appended through the SAME write
        path this guard sits on (`_cross_emit` → events.append_event(events_path=CROSS_LOG_PATH)), and
        its harm is the same in kind and worse in reach: the store is append-only AND cross-project, so
        a phantom row is a real coordination item every PEER then folds. Real incident: a T-10806 red-arm
        probe appended row X-0673 (from:yitc-v2 to:kupiclub) to the production store — it had patched
        `cross.CANONICAL_LOG_PATH`, but the pre-fix per-HOME resolver ignored that constant and resolved
        to production anyway (fp red-arm-probe-wrote-live-cross-store-hermetic-patch-inert-pre-fix).
        BOTH the resolver's answer AND the canonical constant are guarded: the resolver honors
        $YITC_CROSS_LOG, so under an override the canonical path — precisely what X-0673 hit — would
        otherwise be left open. A test that redirects to its OWN tmp store matches neither entry and is
        untouched; the sanctioned way past the guard stays the Rule-2 allowlist.

    A sandbox repo built in a tmpdir is in no worktree list, so a correctly-sandboxed test is untouched.
    Best-effort: a non-repo / git-less checkout guards just itself (plus the shared store)."""
    import subprocess          # module idiom: subprocess is imported function-locally throughout this file
    from lib import cross      # the ONE shared-store resolution site (SPEC-0084 r3) — never a second copy
    journals = [(Path(checkout) / "events.jsonl").resolve()]
    r = subprocess.run(["git", "worktree", "list", "--porcelain"], cwd=str(checkout),
                       capture_output=True, text=True)
    if r.returncode == 0:
        for line in r.stdout.splitlines():
            if line.startswith("worktree "):
                p = (Path(line[len("worktree "):].strip()) / "events.jsonl").resolve()
                if p not in journals:
                    journals.append(p)
    for store in (cross.resolve_log_path(), cross.CANONICAL_LOG_PATH):
        p = Path(os.path.realpath(str(store)))
        if p not in journals:
            journals.append(p)
    return journals

#: The env var the venue leg exports to name its land-overlap sidecar (T-12260, SPEC-0203 rule 4 /
#: SPEC-0071 rule 1). UNSET everywhere else, and that is the whole activation condition: a local land
#: has no box, no lease dir and no foreign land to be starved by, so the two readers below are never
#: consulted there and the per-file bound is byte-identical to before this card.
LAND_OVERLAP_FILE_ENV = "YITC_VENUE_LAND_OVERLAP_FILE"

#: T-12377 — THE QUIET-POINT BARRIER: the env the venue leg script exports so a leg's T-12357 isolated
#: re-run waits until the SIBLING leg's pool has drained too. A land ships BOTH legs at once (SPEC-0203
#: rule 3) and each runs its own 24-wide pool; the retry used to start the moment ITS pool drained,
#: i.e. beside the sibling's 24 children — measured 2026-09-11 (T-12372 05:59:00Z: `isolated: fail`
#: at load1 11.44 while pinned's pool was live; the same tree re-landed clean at 06:32:09Z). UNSET
#: everywhere but a two-leg venue pass — and that is the whole activation condition: the local host
#: leg has no sibling, so its retry block is byte-identical to before this card.
QUIET_BARRIER_DIR_ENV = "YITC_VERIFY_QUIET_BARRIER_DIR"   # the shared marker dir (one per request+attempt)
QUIET_LEG_ENV = "YITC_VERIFY_QUIET_LEG"                   # THIS leg's name (`cand` / `pinned`)
QUIET_SIBLING_ENV = "YITC_VERIFY_QUIET_SIBLING"           # the sibling leg's name
QUIET_SIBLING_PID_ENV = "YITC_VERIFY_QUIET_SIBLING_PID"   # the sibling's pid when the script knew it
QUIET_MARKER_SUFFIX = ".pool-drained"                     # `<dir>/<leg>.pool-drained`
QUIET_PID_SUFFIX = ".pid"                                 # `<dir>/<leg>.pid`, the pidfile fallback


def _quiet_barrier_from_env(env=None) -> "dict | None":
    """T-12377 — the barrier this run was handed, or None (no barrier: today's path). Read at ONE site
    so the runner and its test fixture cannot disagree about which names activate it."""
    env = os.environ if env is None else env
    d = (env.get(QUIET_BARRIER_DIR_ENV) or "").strip()
    if not d:
        return None
    pid_raw = (env.get(QUIET_SIBLING_PID_ENV) or "").strip()
    return {"dir": d, "leg": (env.get(QUIET_LEG_ENV) or "").strip() or "leg",
            "sibling": (env.get(QUIET_SIBLING_ENV) or "").strip() or None,
            "sibling_pid": int(pid_raw) if pid_raw.isdigit() else None}


def _quiet_point_wait(barrier_dir, leg: str, sibling: "str | None", sibling_pid: "int | None",
                      ceiling_s: float, *, monotonic=None, sleep=None, poll_s: float = 0.5,
                      pid_alive=None) -> dict:
    """T-12377 — HOLD until the sibling leg's pool has drained, bounded by the sibling itself.

    Returns `{"quiet_wait_s": <float>, "quiet_wait": <why it released>}` where the vocabulary is
    CLOSED and every value is a fact about the sibling, never about a window:
      * `sibling-drained` — `<dir>/<sibling>.pool-drained` exists (the ordinary case);
      * `sibling-exited`  — the sibling pid answers dead (a crashed leg releases at once);
      * `no-sibling`      — no sibling pid is resolvable (neither the env nor `<dir>/<sibling>.pid`)
                            and no marker: nothing to wait for, proceed at once;
      * `ceiling`         — the sibling is alive and never drained within `ceiling_s`, the per-file
                            wall bound the runner already resolved (a leg cannot wait longer than a
                            single file may run — the bound the card names, never an external window);
      * `error`           — an `OSError` while probing (audit-pre absorbed finding): the barrier can
                            never turn a green run red, so a probe fault PROCEEDS and says so.
    THIS leg's own marker is written by the CALLER when its pool drains, unconditionally — a leg with
    no failures must still release its sibling. The clock/sleeper/liveness probe are injectable
    (default: the real ones) purely so the bound can be tested without a real 60s sibling."""
    monotonic = monotonic or time.monotonic
    sleep = sleep or time.sleep
    alive = pid_alive or _quiet_sibling_alive
    t0 = monotonic()
    d = Path(barrier_dir)
    sib_marker = (d / f"{sibling}{QUIET_MARKER_SUFFIX}") if sibling else None
    sib_pidfile = (d / f"{sibling}{QUIET_PID_SUFFIX}") if sibling else None
    try:
        while True:
            if sib_marker is not None and sib_marker.exists():
                return {"quiet_wait_s": round(monotonic() - t0, 2), "quiet_wait": "sibling-drained"}
            pid = sibling_pid
            if pid is None and sib_pidfile is not None and sib_pidfile.exists():
                raw = sib_pidfile.read_text(encoding="utf-8", errors="replace").strip()
                pid = int(raw) if raw.isdigit() else None
            if pid is None:
                return {"quiet_wait_s": round(monotonic() - t0, 2), "quiet_wait": "no-sibling"}
            if not alive(pid):
                return {"quiet_wait_s": round(monotonic() - t0, 2), "quiet_wait": "sibling-exited"}
            if monotonic() - t0 >= float(ceiling_s):
                return {"quiet_wait_s": round(monotonic() - t0, 2), "quiet_wait": "ceiling"}
            sleep(poll_s)
    except OSError:
        return {"quiet_wait_s": round(monotonic() - t0, 2), "quiet_wait": "error"}


def _quiet_sibling_alive(pid: int) -> bool:
    """`kill -0`, with a ZOMBIE read as dead: a sibling leg that exited but was not yet reaped by its
    sshd parent still answers signal 0, and waiting on a corpse until the ceiling is the exact
    "bounded by a window, not by the sibling" reading the card forbids."""
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    try:
        with open(f"/proc/{int(pid)}/stat", encoding="utf-8", errors="replace") as fh:
            return fh.read().rsplit(")", 1)[-1].split()[0] != "Z"
    except (OSError, IndexError):
        return True


def _land_overlap_intervals(path) -> list:
    """Parse the venue leg's land-overlap sidecar -> `[(start_epoch, end_epoch), ...]`.

    THE FILE IS WRITTEN BY THE BOX, WHOLE, ON EVERY POLL (write-then-rename), so a reader always sees
    a complete list: the intervals during which a FOREIGN `land`-class lease was live on this box
    beside this leg, the last of which may be the currently-open one ending at the poll's `now`.

    FAIL-SAFE IN ONE DIRECTION ONLY, and it is the direction that matters. Every fault — absent file,
    unreadable file, a half-written line, a non-numeric field, an inverted interval — yields FEWER
    intervals, never more. The sole consumer ADDS this to a deadline, so a degraded read can only
    ever leave the pre-T-12260 bound in place; it can never SHORTEN one, and therefore can never turn
    a hang into a pass. That asymmetry is why this parser is silent rather than loud: a guard whose
    failure mode is "the old behaviour" needs no escalation path of its own."""
    out: list = []
    if not path:
        return out
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                parts = line.split()
                if len(parts) < 2:
                    continue
                try:
                    a, b = float(parts[0]), float(parts[1])
                except (TypeError, ValueError):
                    continue
                if b > a:
                    out.append((a, b))
    except OSError:
        return []
    except Exception:                       # noqa: BLE001 — a measurement never breaks its consumer
        return []
    return out


def _land_overlap_seconds(start_epoch: float, end_epoch: float, path=None) -> float:
    """How many seconds of `[start_epoch, end_epoch]` a foreign LAND held this box (T-12260).

    PER-WINDOW, NOT PER-LEG, and that is load-bearing rather than tidy: files run in parallel and
    each has its own life, so a file that STARTED AFTER the land ended must be credited NOTHING. A
    leg-total credited to every file would hand a genuinely hung file an extension it was never
    starved of — the one way this change could weaken the hang guard, closed here by construction.

    Overlapping intervals are merged before summing, so a malformed sidecar that repeated a window
    cannot inflate the credit beyond the window's own length. The return is therefore bounded by
    `end_epoch - start_epoch`: the extension can never exceed the time actually elapsed."""
    if end_epoch <= start_epoch:
        return 0.0
    total = 0.0
    prev_end = start_epoch
    for a, b in sorted(_land_overlap_intervals(path)):
        a = max(a, start_epoch)
        b = min(b, end_epoch)
        if b <= a:
            continue
        a = max(a, prev_end)                # merge: never count the same second twice
        if b > a:
            total += b - a
            prev_end = b
    return round(total, 3)


def _load_verify_duration_table(test_dir: Path, *, _VERIFY_DURATIONS_FILE=None) -> dict:
    """T-11316 — read the FIXED duration table for this test dir. Returns `{file_name: wall_ms}`.

    WHY A RECORDED TABLE RATHER THAN A LIVE MEASUREMENT — the tension this resolves. Dispatch order
    must be STABLE (a failure has to reproduce in the order that produced it, and the SPEC-0077
    pinned-vs-candidate comparison is only meaningful against a fixed schedule), but durations drift
    as the suite grows. Recomputing the table every run satisfies NEITHER: the order would be
    deterministic given the table while the table moved under it. So the table is a RECORDED
    ARTIFACT, rewritten under a stated WRITE POLICY and never by the mere act of running. Between
    writes the order is immobile. T-11440 AMENDS who may write it — a green land now refreshes it from
    its OWN measurement (`_refresh_verify_duration_table`), always when a discovered file carries no
    recorded duration and otherwise only when the re-derived order beats a stated makespan threshold —
    so `--rebuild` is no longer the sole writer, while the immobility this paragraph protects is
    exactly what that threshold preserves. Prior-art reused wholesale: `implements_signature`
    on a spec — a recorded baseline, an explicit re-sign verb, divergence SHOWN rather than silently
    absorbed (`bin/lib/spec.py`).

    STALENESS IS A PERFORMANCE QUESTION, NEVER A CORRECTNESS ONE — this is the property that makes
    the whole design cheap. An out-of-date table schedules slightly worse; it cannot change WHICH
    files run, their isolation, the per-file timeout, or the verdict. So a rebuild cadence of weekly,
    or on-divergence, is enough, and an ABSENT table is a NORMAL state — for a fresh consumer, and
    for every newly-written test — not an edge case. Hence: absent -> `{}` SILENTLY.

    FAIL-SOFT ON MALFORMED, and loudly. A corrupt table is reported once on stderr and treated as
    empty, because refusing to run the suite over a scheduling HINT would convert a performance
    artifact into a gate — exactly the inversion this file's cost/benefit does not support.

    SHAPE (deterministic, diff-friendly): `{"unit_ms": <int>, "files": {"<name>": <units>, ...}}`.
    Values are in `unit_ms` quanta for the same reason `_duration_series` quantises — the resolution
    a scheduling answer needs is far coarser than a millisecond — and keys are sorted on write so a
    rebuild that measures the same suite produces a byte-identical file."""
    path = Path(test_dir) / _VERIFY_DURATIONS_FILE
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        sys.stderr.write(f"WARN: {path} unreadable ({e}) — scheduling the verify suite by name only "
                         f"(a duration table is a scheduling HINT; the verdict is unaffected).\n")
        return {}
    if not isinstance(raw, dict) or not isinstance(raw.get("files"), dict):
        sys.stderr.write(f"WARN: {path} is not a {{unit_ms, files}} duration table — scheduling the "
                         f"verify suite by name only (the verdict is unaffected).\n")
        return {}
    try:
        unit = max(1, int(raw.get("unit_ms") or _VERIFY_DURATION_SERIES_UNIT_MS))
        return {str(k): int(v) * unit for k, v in raw["files"].items() if int(v) >= 0}
    except (TypeError, ValueError) as e:
        sys.stderr.write(f"WARN: {path} carries a non-numeric duration ({e}) — scheduling the verify "
                         f"suite by name only (the verdict is unaffected).\n")
        return {}

def _mem_available_mb() -> "int | None":
    """Linux MemAvailable in MB (from /proc/meminfo); None if unreadable — that dimension then takes the
    conservative `_VERIFY_UNMEASURED_FALLBACK` bound (fail-closed), NEVER an unbounded/omitted one."""
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) // 1024   # kB → MB
    except Exception:
        pass
    return None

def _path_at_or_under(path, root: Path, *, must_exist: bool = True) -> bool:
    """T-11206 — is `path` a REAL filesystem path that is the directory `root` itself, or anything
    beneath it?

    Containment is on parsed path COMPONENTS, so a sibling that merely shares a string prefix
    (`<root>-other/x`) is never a match the way a raw `str.startswith` would make it. See
    `_sandbox_run_residents` for why containment is asked directly rather than via
    `_sandbox_resident_root`.

    `must_exist` (audit-post finding 2) is what keeps an ARGV candidate honest. A process's cwd is a
    kernel-maintained link and is a path by construction; its argv is arbitrary TEXT. Without this, any
    string that merely READS like a path under the sandbox — a `-c` program body, a log line, a
    message quoting a filename — would select the process that carries it. So a candidate must RESOLVE
    to something that actually exists on disk (checked without following a symlink out of the tree, and
    with the containment decided on the LEXICAL path so a symlink cannot smuggle an outside process in).
    Fail-closed: unresolvable or absent means NOT selected. This is checkable here because the reap runs
    BEFORE the sandbox is deleted — the same ordering the rest of this step depends on."""
    if not path:
        return False
    try:
        p = Path(path)
    except (TypeError, ValueError):
        return False
    if not (p == root or root in p.parents):
        return False
    if not must_exist:
        return True
    try:
        return os.path.lexists(str(p))
    except (OSError, ValueError):
        return False             # unresolvable → never selected.

def _per_file_duration_record(entries: "list", n: int = _VERIFY_SLOWEST_FILES_N, *, _duration_series=None) -> "dict":
    """T-11124 — the BOUNDED per-file duration record. PURE (no I/O, no clock, no side effect) over
    `entries` = [(file, wall_ms, outcome), ...], one tuple per test file that STARTED this run.

    WHY BOUNDED, AND WHY THIS SHAPE. The runner has always measured each file's elapsed and always
    thrown it away, so nothing downstream could watch test-duration GROWTH: the journal carried
    aggregates only (verify_wall_ms / test_file_count / worker_count / queue_wait_ms / mem_peak_kb /
    fail_class) across 1527 rows and NOT ONE per-file duration in its whole history. Recording all
    ~800 per land is the obvious fix and is REJECTED — see the `_VERIFY_SLOWEST_FILES_N` bound above.
    So the record carries two complementary halves, and it needs BOTH:
      • `slowest_files` — the top-N by wall, each with its `outcome`. This is the TAIL, where a single
        newly-pathological file shows up first.
      • `wall_ms_pct` — p50/p75/p90/p99/max over the WHOLE sample. This is the SHAPE, and it catches
        what the tail cannot: a broad uniform creep moves p50 while leaving the top-N membership
        byte-identical. A slowest-only record would be blind to exactly that growth mode.
      • `duration_series` (T-11315) — the WHOLE distribution, compactly: every started file's wall,
        quantised and comma-joined in dispatch order, names dropped. The two halves above are a
        SUMMARY and a summary cannot be re-simulated; this third half is what makes an offline
        makespan (alphabetical vs longest-first, and the skip-top-N curve) recomputable from a
        single recorded run. Its own contract is in `_duration_series` — including why it is
        durations-in-dispatch-order rather than the ~877-name raw dump this bound rejects.
    `sample_count` is the percentile BASE. Read beside `test_file_count` it also states, rather than
    hides, how many files never started (a fail-fast run stops launching); a percentile whose base is
    unstated is not a series you can compare across lands.

    NEVER FABRICATED. An empty `entries` returns `{}` — the caller then attaches no key at all, so a
    run that measured nothing SAYS nothing rather than reporting a zero it did not observe (the T-0358
    no-fabricated-0s discipline). Percentiles are NEAREST-RANK on the sorted sample (no interpolation:
    every reported value is a real measured file's wall, not a synthesized midpoint), integer ms."""
    if not entries:
        return {}
    walls = sorted(int(w) for _f, w, _o in entries)
    m = len(walls)

    def _pct(q: float) -> int:
        # Nearest-rank: the smallest value at or above the q-th percentile position. Clamped so q=1.0
        # lands on the last element rather than one past it.
        return walls[min(m - 1, max(0, math.ceil(q * m) - 1))]

    top = sorted(entries, key=lambda e: (-int(e[1]), e[0]))[:max(0, int(n))]
    return {"slowest_files": [{"file": f, "wall_ms": int(w), "outcome": o} for f, w, o in top],
            "wall_ms_pct": {"p50": _pct(0.50), "p75": _pct(0.75), "p90": _pct(0.90),
                            "p99": _pct(0.99), "max": walls[-1]},
            "sample_count": m,
            "duration_series": _duration_series(entries)}

def _per_file_outcomes_export(entries: "list", discovered: "list", cwd: "Path", *,
                              path: "Path | None" = None, env: "dict | None" = None,
                              keep: int = _VERIFY_OUTCOMES_KEEP) -> "dict":
    """T-12190 (SPEC-0203 rule 4) — write the COMPLETE per-file outcome list to ONE machine-readable
    sidecar and return its LOCATOR. The complement of `_per_file_duration_record` above: that one
    SUMMARISES (slowest-10 + percentiles) for the journal row, this one records every file for a
    reader that must NAME the failures.

    DEFINED OVER THE DISCOVERED SET, NOT THE STARTED ONE (audit-pre finding 1, absorbed mode-a).
    `entries` = [(file, wall_ms, outcome), ...] is one tuple per file that STARTED; `discovered` is
    every test file the run enumerated. Under fail-fast the two differ — the tail never launches — and
    an export that silently omitted those files would be complete only on the `fail_fast=False` path,
    which is exactly the reading the caller cannot check. So every discovered file gets exactly one
    row: a started file carries its measured `wall_ms` + the runner's own outcome token, and a file
    that never launched carries `wall_ms: null` + `outcome: "not-started"` — STATED, never fabricated
    as a zero-wall pass (the T-0358 no-fabricated-0s discipline) and never silently absent.

    THE VOCABULARY IS THE RUNNER'S OWN (`_record`): `passed` / `failed` / `timed-out` /
    `killed-fail-fast` / `launch-error`, plus `not-started` here. It is NOT normalised to a prettier
    public enum, deliberately (audit-pre finding 2, absorbed mode-b): these exact tokens are already
    published for the same measurement by `verify_metrics.per_file_durations.slowest_files[].outcome`,
    so a second vocabulary would be a parallel path over one measurement (CHARTER §P1 F1 / §P5) and
    would have to collapse `killed-fail-fast` into "skipped" and `launch-error` into "failed" —
    destroying the two distinctions a host-sensitivity classifier most needs. The schema names its own
    vocabulary in the file, so a consumer reads it from the artifact rather than from prose.

    DESTINATION, most explicit first: an explicit `path` (a full file path — what a remote executor
    passes), else the `YITC_VERIFY_OUTCOMES_DIR` env dir (what a box-side run sets), else
    `<tempdir>/yitc-verify-outcomes/` — OFF the checkout, never inside it. See the constant above for
    why the default is off-tree: an export written into the verified tree is land-blocking dirt in any
    repo that does not ignore it, and a report must never refuse the land it reports on.

    NEVER RAISES INTO THE RUN. Every failure returns `{}` — a report is not a verdict, and a full disk
    or a read-only export dir must not change what `land` acts on. An empty `discovered` likewise
    returns `{}`, so a run that measured nothing SAYS nothing rather than writing an empty list.

    Returns the locator `{"path": <str>, "sha256": <hex>, "count": <int>}` — a locator, not the list,
    which is what keeps the journal row bounded when the caller attaches it."""
    if not discovered:
        return {}
    try:
        measured = {}
        for name, wall_ms, outcome in entries:
            # A file can be recorded more than once only by a retry path; keep the LAST word on it.
            measured[str(name)] = (int(wall_ms), str(outcome))
        rows = []
        for name in discovered:
            n = str(name)
            if n in measured:
                rows.append({"file": n, "wall_ms": measured[n][0], "outcome": measured[n][1]})
            else:
                rows.append({"file": n, "wall_ms": None, "outcome": "not-started"})
        payload = {"schema": _VERIFY_OUTCOMES_SCHEMA,
                   "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                   "outcome_vocabulary": ["passed", "failed", "timed-out", "killed-fail-fast",
                                          "launch-error", "not-started"],
                   "file_count": len(rows),
                   "started_count": sum(1 for r in rows if r["outcome"] != "not-started"),
                   "files": rows}
        text = json.dumps(payload, indent=2, sort_keys=True) + "\n"

        env = os.environ if env is None else env
        if path is not None:
            target = Path(path)
        else:
            env_dir = (env.get(_VERIFY_OUTCOMES_DIR_ENV) or "").strip()
            out_dir = (Path(env_dir) if env_dir
                       else Path(tempfile.gettempdir()) / _VERIFY_OUTCOMES_DEFAULT_LEAF)
            target = out_dir / ("verify-outcomes-%s-%d.json"
                                % (time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()), os.getpid()))
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.parent / (".%s.%s.tmp" % (target.name, uuid.uuid4().hex[:8]))
        tmp.write_text(text, encoding="utf-8")
        os.replace(str(tmp), str(target))
        _prune_per_file_outcomes(target.parent, keep=keep)
        return {"path": str(target),
                "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "count": len(rows)}
    except Exception:
        return {}                # a report never masks the run it is reporting on.

def _prune_per_file_outcomes(out_dir: "Path", *, keep: int = _VERIFY_OUTCOMES_KEEP) -> int:
    """T-12190 — keep the newest `keep` exports in `out_dir`, delete the rest; return how many were
    removed. A per-run file is unbounded growth otherwise. NARROW BY CONSTRUCTION: it only ever
    considers files matching the export's OWN generated name shape (`verify-outcomes-*.json`), so an
    executor pointing the env dir at a directory holding anything else cannot lose a file to this.
    Newest-last by NAME, which is newest-last by TIME because the name leads with a UTC timestamp
    (mtime would be the wrong key: a copied or restored export carries a fresh mtime and an honest
    name). Never raises — pruning is housekeeping, not a verdict."""
    try:
        if keep is None or int(keep) <= 0:
            return 0
        existing = sorted(p for p in Path(out_dir).glob("verify-outcomes-*.json") if p.is_file())
        stale = existing[:max(0, len(existing) - int(keep))]
        removed = 0
        for p in stale:
            try:
                p.unlink()
                removed += 1
            except OSError:
                pass
        return removed
    except Exception:
        return 0

def _proc_start_age_sec(pid: int) -> float:
    """T-10857 — how many seconds ago process `pid` STARTED, from `/proc/<pid>/stat` field 22 (starttime,
    in clock ticks since boot) against `/proc/uptime`. The process analog of the sweep's `_age_sec`, and
    fail-closed the SAME way: an unreadable/unparseable value returns -1.0, which reads as YOUNG and is
    therefore never swept. Field 22 is located AFTER the last `)` so a comm containing spaces or
    parentheses cannot shift the index."""
    try:
        raw = Path(f"/proc/{int(pid)}/stat").read_text(encoding="utf-8", errors="replace")
        fields = raw[raw.rindex(")") + 1:].split()
        starttime_ticks = float(fields[19])          # field 22 overall = index 19 after the comm field
        hz = float(os.sysconf("SC_CLK_TCK")) or 100.0
        uptime = float(Path("/proc/uptime").read_text(encoding="utf-8").split()[0])
        age = uptime - (starttime_ticks / hz)
        return age if age >= 0 else -1.0
    except (OSError, ValueError, IndexError, ZeroDivisionError):
        return -1.0

def _own_cgroup_pids() -> "frozenset[int] | None":
    """T-11867 — the pids in THIS process's own cgroup, or None meaning "no bound available".

    THE BOUND `_scan_procs` TAKES ON THE VERIFY-TEARDOWN PATH, and why this is the right one. The
    sandbox reaper (`_reap_own_sandbox_residents`) hunts a process that escaped the run's process
    group by starting its own session — `ppid=1 pgid=self`, the shape that defeats every
    `killpg`-scoped reaper and the entire reason that function exists. That escape does NOT leave
    our cgroup: membership is inherited across `fork` AND is untouched by `setsid`, and leaving it
    takes an explicit migration this population cannot perform. So an own-SESSION or own-descendants
    bound would be exactly wrong — it would exclude the only processes worth reaping — while the
    own-cgroup bound provably contains every one of them.

    WHAT IT BUYS, measured on this host at authoring: 58 pids in our own cgroup against 1422 numeric
    entries in /proc, a ~24x narrowing of a walk that costs three syscalls per surviving pid and was
    paid on every verify teardown of every land (tests/test_land.py recorded the other half of the
    same measurement — 0.86s per land, growing with host load, bought back for FIXTURE lands only by
    a monkeypatch that never touched the product path).

    NONE IS THE FAIL-SAFE, AND IT IS THE ONLY FAILURE MODE. A host without cgroup v2, an unreadable
    or unparseable hierarchy, a cgroup that reports no pids at all — every one of them returns None,
    which `_scan_procs` reads as "no bound" and answers with the unchanged whole-/proc walk. The
    narrowing can therefore only ever be an optimisation that is present or absent; it can never
    silently shrink the reaper's universe, which would turn a leak into a green run. Reading OUR OWN
    pid back out of the result is asserted by this card's test, so a bound that somehow excluded the
    reaper itself could not pass unnoticed.

    Cgroup v2 only, deliberately: the unified hierarchy answers this question with one file, whereas
    v1 would need a controller to be chosen and its answer is not the containment set we want. On a
    v1 host this returns None and nothing changes."""
    try:
        rel = None
        for line in Path("/proc/self/cgroup").read_text(encoding="utf-8").splitlines():
            hid, _, rest = line.partition(":")
            if hid == "0":                       # cgroup v2 unified: `0::<path>`
                rel = rest.partition(":")[2].strip()
                break
        if not rel or not rel.startswith("/"):
            return None
        raw = Path("/sys/fs/cgroup" + rel + "/cgroup.procs").read_text(encoding="utf-8")
        pids = frozenset(int(t) for t in raw.split() if t.isdigit())
        return pids or None                      # an empty answer is no answer — fall back to full.
    except (OSError, ValueError):
        return None


def _reap_own_sandbox_residents(sandbox_root, *, _scan=None, _grace: float = _SANDBOX_RESIDENT_REAP_GRACE, _own_cgroup_pids=_own_cgroup_pids, _path_at_or_under=None, _sandbox_residency_candidates=None, _sandbox_run_residents=None, _scan_procs=None) -> dict:
    """T-11206 / X-0950 — at verify-run teardown, KILL what is still resident in this run's OWN sandbox
    and REPORT what will not die. Returns `{"reaped": [...], "survivors": [...]}`.

    THE DEFECT THIS CLOSES (measured, not inferred). The runner reaps only per-test PROCESS GROUPS —
    `_terminate_process_group` on timeout/fail-fast, `_reap_leaked_descendants` on the clean-exit path —
    all scoped to one test file's group via `os.killpg`. A descendant that starts its OWN session escapes
    every one of them. Measured on the shared host 2026-08-17: two leader+child pairs, `ppid=1 pgid=self`,
    elapsed 19h11m and 20h21m, each pinning a core at ~99% — ~4 of 32 cores burned for most of a day, on a
    host four projects share. Run teardown then `rmtree`d the sandbox out from under them, which is why
    they kept burning with a deleted cwd and no trace back to the run that made them. Nothing reaped them
    and — the half that made it last a day rather than a minute — nothing REPORTED them either.

    NOT the 31-year timer the origin fingerprint names. That number is real (a fixture burn loop bounded
    at 1e9s = 31.7 years) and it was already capped to 600s by T-11087/E-0059, yet the leak class stayed
    open: a bound on the loop decides how LONG a survivor burns, never WHETHER it survives. A 600s-capped
    survivor is still an unreaped, unreported survivor.

    KILL THE GROUP, NOT THE PID. A resident that escaped by starting its own session LEADS that session,
    so `killpg(pgid)` takes it and everything it forked in one signal — the measured pairs die together
    rather than the leader dying and its burner being re-orphaned onto init. Identity is RE-VALIDATED
    immediately before the signal (`_reap_proc`'s PID-reuse discipline): the /proc scan is a snapshot, the
    pid may have been recycled, and a residency that cannot be re-proven is NOT signalled.

    NEVER RAISES, NEVER DECIDES A VERDICT. Any scan/kill failure degrades to "reaped what it could, report
    what is visible" — a teardown belt must not be able to fail the run it is cleaning up after, and a
    leak must not be able to turn a green run red, or this reporting surface becomes the next thing
    someone silences."""
    import signal as _signal
    result = {"reaped": [], "survivors": []}
    try:
        # BOUNDED SNAPSHOT (T-11867). `_own_cgroup_pids` defaults to the REAL helper, NOT to None
        # like its sibling collaborators above — deliberately, and the difference is load-bearing.
        # Those siblings are only ever reached through worktree.py's residue shim, which injects
        # them; this one is CALLED, and a None default would make a direct `verify_runner` call
        # raise `None()` INSIDE the broad try/except just below, which swallows it and returns an
        # EMPTY reap. That is the worst possible failure here: the reaper would silently stop
        # reaping and still report success, which is the exact shape of the leak SPEC-0071 §5
        # exists to catch (audit-post finding, high). Injection still overrides the default. This reaper only ever selects a process of our OWN uid that
        # resolves a path of its own under a `mkdtemp` root THIS run created — so it can only ever
        # select a DESCENDANT of this run, and cgroup membership is inherited across both fork and
        # `setsid`. `_own_cgroup_pids()` is therefore a superset of everything this call can select,
        # at a fraction of the whole-host walk. `None` (any failure, any non-cgroup-v2 host) means NO
        # bound and the full walk — the current behaviour, never a narrower reap.
        procs = (_scan or _scan_procs)(pids=_own_cgroup_pids()) or []
    except Exception:
        return result            # a scan failure reaps NOTHING — fail-closed, never a blind kill.
    try:
        self_pid, self_pgid, uid = os.getpid(), os.getpgid(0), os.geteuid()
    except OSError:
        return result
    residents = _sandbox_run_residents(sandbox_root, procs, self_pid=self_pid,
                                       self_pgid=self_pgid, uid=uid)
    if not residents:
        return result            # the NORMAL no-leak case — no scan cost beyond the one snapshot.

    def _still_resident(pid: int) -> bool:
        """Re-prove THIS pid is still a resident of THIS run's sandbox, immediately before signalling."""
        try:
            raw = Path(f"/proc/{int(pid)}/cmdline").read_bytes()
            cwd = os.readlink(f"/proc/{int(pid)}/cwd")
        except OSError:
            return False         # gone, or unprovable → never signal (fail-closed).
        argv = [a.decode("utf-8", "surrogateescape") for a in raw.split(b"\x00") if a]
        # SAME candidate extraction as the selection above (T-11231) — the two readers must not
        # diverge, or a resident selected from the snapshot could fail its own re-proof and never be
        # signalled (which is exactly how the nginx population survived: selected by neither).
        return any(_path_at_or_under(x, Path(sandbox_root))
                   for x in _sandbox_residency_candidates(cwd, argv) if x)

    for r in residents:
        if not _still_resident(r["pid"]):
            continue
        # LEADER-ONLY GROUP KILL (audit-post finding 1). `killpg` is used ONLY when this resident IS
        # its own group leader (`pid == pgid`) — the escape shape, where the group contains exactly
        # this leaker and what it forked. For a NON-leader resident the group is someone else's and
        # may hold processes this teardown has no claim on, so only its OWN pid is signalled. Its
        # children are not lost: a child inside the sandbox is itself a resident and is selected and
        # killed on its own merits, never as collateral of a group it merely belongs to.
        target, killer = ((r["pid"], os.killpg) if r["pid"] == r["pgid"]
                          else (r["pid"], os.kill))
        try:
            killer(int(target), _signal.SIGKILL)
        except OSError:
            pass                 # already gone / unsignalable — measured below, never assumed.
    # Give the kernel a moment to reap, then MEASURE rather than assume: whoever is still resident after
    # a SIGKILL is a survivor teardown could not reap, and that is exactly what must be reported.
    deadline = time.time() + max(_grace, 0.0)
    while time.time() < deadline:
        if not any(_still_resident(r["pid"]) for r in residents):
            break
        time.sleep(0.1)
    for r in residents:
        (result["survivors"] if _still_resident(r["pid"]) else result["reaped"]).append(r)
    return result

def _reclaim_sandbox_worktrees(cwd: Path, under: "Path | None" = None, *, _VERIFY_SANDBOX_PREFIX=None) -> list:
    """T-10716 — UNLOCK + remove the git worktree registrations a verify-sandbox test left behind.

    THE LEAK this closes: a test running under the T-10073 hermetic sandbox may `git worktree add` a
    worktree against the REAL checkout at a path inside its private TMPDIR (`tests/test_t0952_*` does
    exactly that). `git worktree add` holds a `locked: initializing` on the new entry while it sets up;
    if the add is interrupted — a per-file verify TIMEOUT SIGKILLs the whole process group (SPEC-0071) —
    the lock persists, the test's own `finally` never runs, and then the sandbox `rmtree` below deletes
    the DIRECTORY while the REGISTRATION survives. `git worktree prune` cannot reclaim it (prune skips a
    LOCKED entry), so nothing fails closed and the leak only accretes: 39 such registrations had
    accumulated in the real repo by 2026-08-06. The at-source fix is here, in the sandbox teardown, NOT
    per-test: the sandbox is applied by the runner to EVERY subprocess, so a newly-added test that
    registers a worktree inherits the reclaim with no opt-in (the same self-enforcing property the
    hermetic env has).

    TWO SELECTION MODES — both fail-CLOSED toward KEEPING a registration (the T-9532 sweep discipline):
      • `under=<sandbox root>` (the teardown call): reclaim only entries whose path is INSIDE this run's
        OWN mkdtemp root. That root is unique per run, so a concurrent sibling verify is never touched.
      • `under=None` (the one-time repair of already-leaked entries): reclaim only entries that match the
        `yitc-verify-sandbox-` prefix AND whose path is ABSENT from disk. Both conjuncts are required —
        the cohort-COMPLEMENT check (SPEC-0060): a live `task/T-XXXX` / `work/<slug>` worktree matches
        NEITHER (wrong prefix, and it exists on disk), so it can never be selected.
    The main checkout is skipped unconditionally. Every git call is best-effort (never raises); returns
    the list of reclaimed paths so a caller can report what it took."""
    import subprocess

    def _git(*args) -> "subprocess.CompletedProcess":
        # A local runner, not the injected `_run_git_cap`: this call site receives no injection, and
        # that helper's only extra behaviour (an identity fallback) applies to `commit` alone.
        return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True)

    listing = _git("worktree", "list", "--porcelain")
    if listing.returncode != 0:
        return []   # FAIL-CLOSED: without a readable inventory nothing is classified, so nothing is removed.
    root = str(Path(under).resolve()) + os.sep if under is not None else None
    reclaimed = []
    first = True
    for line in listing.stdout.splitlines():
        if not line.startswith("worktree "):
            continue
        path = line[len("worktree "):].strip()
        if first:                      # `worktree list` always leads with the main checkout
            first = False
            continue
        if root is not None:
            if not path.startswith(root):
                continue
        else:
            if _VERIFY_SANDBOX_PREFIX not in path or os.path.exists(path):
                continue
        _git("worktree", "unlock", path)          # clears a stuck `locked: initializing`
        _git("worktree", "remove", "--force", path)
        reclaimed.append(path)
    if reclaimed:
        _git("worktree", "prune")                 # clears whatever `remove` could not (dir already gone)
    return reclaimed

def _rescued_failure_lines(elided: str, bound: int = _VERIFY_FAIL_RESCUE_BOUND, *, _is_verify_failure_line=None) -> "tuple[list, int]":
    """T-10853: the failure-identity lines inside an ELIDED span, order-preserving + de-duplicated, and
    the count this budget had to CLIP. Returns the lines VERBATIM (not de-guttered) — this is a faithful
    truncator, and deciding which of them is "the" assertion belongs to the reader downstream
    (`lessons/fail-closed-belongs-to-the-reader-not-the-parser.md`).

    T-11561 — THE BUDGET IS SPENT FROM BOTH ENDS, because the budget rule is POSITIONAL and the failure
    identity is not. The original loop spent `bound` FRONT-FIRST and turned everything past it into a
    bare count, so a span that LEADS with a matching-but-content-free line and NAMES its cause later
    kept the line that says nothing and clipped the line that says everything. Measured on the T-11419
    abort (followup fu_b5809ebeb62f, 2026-08-22): the record kept the header
    `AssertionError: probe failed: Traceback` and clipped the naming line to `(+N more not shown)`.
    That record is the input to the attribution oracle, the known-broken-on-main check, and the human
    deciding whether to re-land — a blind record makes all three guess (SPEC-0188 element-5,
    recipient-of-failure).

    THIS IS THE SIBLING'S FIX, NOT A NEW ONE. `_verify_failure_excerpt` (T-10733) hit the identical
    truncate-from-one-end defect on the identical input and answered it by keeping BOTH ENDS under a
    split budget. Reusing that shape rather than re-deriving one is the point (CHARTER §P1 F1).

    WHAT IS DELIBERATELY NOT DONE, because the contract above forbids it: this does NOT rank lines by
    content — no "prefer an identity line over a header" rule, no header blacklist. Which line is "the"
    assertion is the READER's judgement, and moving it in here would re-create the class the
    positive-discriminator design (`lessons/carving-an-exception-into-a-fail-closed-gate.md` §1) and
    T-11346 exist to keep out. The selection stays PURELY POSITIONAL — only the position it truncates
    FROM changes, from one end to two.

    THE BOUNDS, all three load-bearing:
      • EVERYTHING-FITS IS BYTE-IDENTICAL. When the matched lines fit `bound` whole, the return is
        exactly the old one with `clipped == 0`. That is the overwhelmingly common case and the cohort
        that was never clipped — this change provably cannot move a record it was not written for.
      • THE BUDGET STILL HOLDS. Total spend never exceeds `bound`; this is a SELECTION fix, not a
        budget removal.
      • THE COUNT STAYS EXACT. `clipped` is the number of matched, de-duplicated lines NOT returned —
        the same meaning it has always had, so `(+N more not shown)` keeps saying what it says.

    Diagnostic formatter — never raises."""
    # PHASE 1 — the matcher, the de-dup and the order, unchanged: what the span offers, before any
    # budget question is asked. Collecting first is what makes a two-ended spend possible at all.
    seen, cand = set(), []
    for ln in (elided or "").splitlines():
        s = ln.rstrip()
        if not _is_verify_failure_line(s) or s.strip() in seen:
            continue
        seen.add(s.strip())
        cand.append(s)
    cost = [len(s) + 1 for s in cand]
    if sum(cost) <= bound:
        return cand, 0                    # everything fits — byte-identical passthrough (AC3)
    # PHASE 2 — it does not fit, so the budget is SPLIT. Fill from the FRONT under half the budget,
    # then from the BACK with whatever is left, never re-taking a line the front already took. The
    # greedy SKIP is kept from the original loop: an oversized line is passed over and a later smaller
    # one can still fit, so a single huge line cannot starve its whole end.
    half, spent, taken = max(bound // 2, 1), 0, set()
    for i, s in enumerate(cand):
        if spent + cost[i] <= half:
            taken.add(i)
            spent += cost[i]
    for i in range(len(cand) - 1, -1, -1):
        if i in taken:
            break                         # the two ends have met — stop before double-counting
        if spent + cost[i] <= bound:
            taken.add(i)
            spent += cost[i]
    out = [s for i, s in enumerate(cand) if i in taken]   # original order, both ends
    return out, len(cand) - len(out)

# ── SPEC-0181 (T-11462 / T-12222) — THE ONE GOVERNED-SELECTION ENGINE ────────────────────────────

def governed_selection(test_files, *, select: bool = True, journal_path=None, test_dir=None,
                       selection_diff_paths=None, selection_diff_error=None,
                       selection_reachability_freed=None, selection_tripwire_inert_paths=None,
                       _VERIFY_IMPLEMENTATION_GLOBS=None, _shadow_select=None,
                       _selection_governs=None, _selection_tripwire=None,
                       _selection_omission_tripwire=None, _selection_always_set=None,
                       EXPECTED_SESSION_REF_ENV=None) -> dict:
    """WHICH of the discovered test files this pass runs — the SPEC-0181 ladder, decided ONCE.

    Returns `{run, omit, reason, governed, govern_reason, tripwire, always, always_refused,
    discovered, test_files}`, where `test_files` is the NARROWED enumeration (the input list
    unchanged when the ladder earned no omission) and `run`/`omit` are the selector's own name lists.

    T-12372 — `always` names the DECLARED always-run set actually present in this enumeration (the
    consistency tripwires, declared by `_SELECTION_ALWAYS_MARKER` in the test files themselves), and
    `always_refused` the declarations that granted nothing. Both are EMPTY on an ungoverned run, which
    ran everything and unioned nothing in.

    WHY IT IS A FUNCTION AND NOT AN INLINE BLOCK (T-12222). It has TWO callers now, and they must
    reach the SAME decision: `_run_verify_tests` below narrows its own enumeration with it, and the
    SPEC-0203 venue seam (`land`'s routing block) needs the decision BEFORE the run, because on a
    routed land the candidate suite executes on the BOX and the local runner is never entered for
    it. A second implementation at the venue seam would be a second selector — two answers to one
    question, drifting apart exactly where nobody can see them (CHARTER §P5). The body below is the
    T-11462 block MOVED, not re-derived: every fallback it carries — the tripwire that can only ADD
    names back, `tripwire-error` and `empty-selection` both falling to the FULL suite, the durable
    deviation on a firing — is unchanged, because each of them fails in the direction that runs MORE
    tests and none may be softened by relocating it.

    The DI parameters default to this module's own functions, so a caller outside the runner's
    injection chain (the venue seam) does not have to re-thread the whole residue to ask one
    question. `select=False` returns the inert `not-selected` shape with the enumeration untouched.
    """
    _shadow_select = _shadow_select or globals()["_shadow_select"]
    _selection_governs = _selection_governs or globals()["_selection_governs"]
    _selection_omission_tripwire = (_selection_omission_tripwire
                                    or globals()["_selection_omission_tripwire"])
    _selection_always_set = _selection_always_set or globals()["_selection_always_set"]
    EXPECTED_SESSION_REF_ENV = EXPECTED_SESSION_REF_ENV or "YITC_EXPECTED_SESSION_REF"
    _selection_discovered = len(test_files)
    _sel_run = _sel_omit = None
    _sel_reason = "not-selected"
    _sel_governed, _sel_govern_reason, _sel_tripwire = False, None, []
    _sel_always, _sel_always_refused = [], {}
    if select:
        _sel_run, _sel_omit, _sel_reason = _shadow_select(
            selection_diff_paths, test_files, _VERIFY_IMPLEMENTATION_GLOBS,
            diff_error=selection_diff_error,
            reachability_freed=selection_reachability_freed)
        _sel_governed, _sel_govern_reason = _selection_governs(journal_path)
        if _sel_governed and _sel_reason is None and _sel_omit:
            # AC2 — THE TRIPWIRE, before anything is dropped. It can only ADD names back, so it can
            # never license an omission; any failure inside it falls back to NOT governing at all
            # (the full suite), never to a narrowed set trusted without its oracle.
            _tw = _selection_tripwire or _selection_omission_tripwire
            try:
                # T-11476 — the needle set excludes the changed paths the SPEC-0064 inert authority
                # already answered this oracle's own question for. Passed IN (never derived here): the
                # caller holds the authority, and a caller that cannot establish it passes None and
                # gets today's wider recovery. The SELECTOR's `selection_diff_paths` is deliberately
                # NOT filtered — an emptied diff would trip rung R2 and send every land to the full
                # suite, the opposite of the intent.
                # T-12107: the tripwire also hands back WHICH changed path recovered each test.
                # Out-parameter, so the return contract (and every reader of it below) is unchanged;
                # inside the SAME try, so a tripwire error still falls back to NOT governing.
                _sel_tw_matches = {}
                _sel_tripwire = _tw(selection_diff_paths or (), _sel_omit, test_dir,
                                    inert_paths=selection_tripwire_inert_paths,
                                    matches_out=_sel_tw_matches)
            except Exception:
                _sel_governed, _sel_govern_reason = False, "tripwire-error"
                _sel_tripwire = []
                _sel_tw_matches = {}
            if _sel_governed:
                # T-12372 (SPEC-0181) — THE DECLARED ALWAYS-RUN SET, read off the test files
                # themselves. Wrapped exactly as the tripwire above is, and for the same reason: a
                # set we could not compute must never be read as «there are no tripwires», so any
                # failure falls to NOT governing at all — the FULL suite — never to a narrowed set
                # trusted without it.
                try:
                    _tdir = test_dir if isinstance(test_dir, (str, Path)) else None
                    if _tdir is None:
                        _tdirs = {tf.parent for tf in test_files}
                        _tdir = next(iter(_tdirs)) if len(_tdirs) == 1 else None
                    if _tdir is not None:
                        _sel_always_all, _sel_always_refused = _selection_always_set(_tdir)
                        _sel_always = sorted(n for n in {tf.name for tf in test_files}
                                             if n in _sel_always_all)
                except Exception:
                    _sel_governed, _sel_govern_reason = False, "always-set-error"
                    _sel_always, _sel_always_refused = [], {}
            if _sel_governed:
                # ORDER IS LOAD-BEARING, not stylistic. `_keep` — and therefore the EMPTY-SELECTION
                # fallback judged on it — is computed WITHOUT the always set, exactly as before this
                # card. Folding the always set in first would let a marker-bearing file turn a
                # would-be FULL-SUITE fallback into a narrowed run, which is a NARROWING: the single
                # direction this mechanism may never move (SPEC-0181 R1). The union happens only
                # after the fallback has had its say, so the change is purely additive — every diff
                # selects at least the tests it selected before.
                _keep = set(_sel_run) | set(_sel_tripwire)
                _narrowed = [tf for tf in test_files if tf.name in _keep]
                if not _narrowed:
                    # AN EMPTY EXECUTED SET IS NOT A GREEN RUN. The verdict contract is "pass iff no
                    # test failed", so running nothing reads GREEN — the precise trap the `only`
                    # branch above documents. A selection that resolves to nothing has not earned an
                    # omission of EVERYTHING; it has failed to decide, and that falls to the full
                    # suite like every other undecidable state.
                    _sel_governed, _sel_govern_reason = False, "empty-selection"
                else:
                    test_files = [tf for tf in test_files
                                  if tf.name in (_keep | set(_sel_always))]
                if _sel_tripwire and journal_path is not None:
                    # A firing IS a coverage-map defect (SPEC-0181: "a disagreement is a defect,
                    # fixed at the map, never absorbed as an acceptable miss rate"), so it is
                    # DURABLE, not just a metric on one row. Best-effort: the report must never
                    # break the run it is reporting on.
                    _tw_rendered = _sel_tripwire[:20]
                    _tw_rendered_matches = {n: _sel_tw_matches[n] for n in _tw_rendered
                                            if n in _sel_tw_matches}
                    try:
                        events.append_event(
                            "deviation_captured", None,
                            {"fingerprint": "selection-omitted-a-test-naming-a-changed-path",
                             "relates_to": "SPEC-0181",
                             "impact": ("affected-test selection omitted %d test(s) whose source names a "
                                        "changed path in this diff; the tripwire ran them anyway. The "
                                        "coverage map is wrong for these paths and is fixed AT THE MAP "
                                        "(SPEC-0181: a disagreement is a defect, never a rate): %s"
                                        % (len(_sel_tripwire), ", ".join(_sel_tripwire[:10]))),
                             "tests": _sel_tripwire[:20],
                             # T-12107 — the row is SELF-SUFFICIENT: the changed path that recovered
                             # each RENDERED test (restricted to those 20, so this key cannot
                             # reintroduce the unbounded-payload cost the clip exists to avoid), and
                             # the TRUE count when the rendered list is clipped. Both are
                             # CONDITIONALLY present and ABSENT rather than empty/fabricated when
                             # they say nothing (T-0358) — an all-unreadable firing carries no paths
                             # and says so by their absence, and an untruncated row needs no count
                             # because its rendered list already IS the count.
                             **({"matched_changed_paths": _tw_rendered_matches}
                                if _tw_rendered_matches else {}),
                             **({"omitted_total": len(_sel_tripwire)}
                                if len(_sel_tripwire) > 20 else {})},
                            # Resolved DEFENSIVELY and passed explicitly, the same way
                            # `_emit_verify_timeout_deviation` does it: the fail-closed resolver can
                            # itself _die on a blank worker contract, and nothing here may escape to
                            # mask the run it is reporting on.
                            session_ref=(os.environ.get(EXPECTED_SESSION_REF_ENV)
                                         or "selection-tripwire"),
                            ts=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                            events_path=journal_path)
                    except Exception:
                        pass
        elif _sel_governed:
            # The ladder itself earned no omission (R1/R2/R3, or an empty omit set) — nothing to do,
            # and the reason it did not is already `_sel_reason`.
            _sel_governed = False
            _sel_govern_reason = "ladder-full-suite"
    if not _sel_governed:
        # ABSENT, NEVER FABRICATED (T-0358): an ungoverned run ran everything, so it unioned nothing
        # in and reports no always count. This is AC4 — a `--full` or fail-closed run carries no key.
        _sel_always, _sel_always_refused = [], {}
    return {"run": _sel_run, "omit": _sel_omit, "reason": _sel_reason,
            "governed": bool(_sel_governed), "govern_reason": _sel_govern_reason,
            "tripwire": _sel_tripwire, "discovered": _selection_discovered,
            "always": _sel_always, "always_refused": _sel_always_refused,
            "test_files": test_files}


def _run_verify_tests(test_dir: "Path | list[Path]", cwd: Path, workers: int | None = None,
                      timeout: "float | None" = None, journal_path=None, metrics_out: "dict | None" = None, fail_fast: bool = True, selection_diff_paths=None, selection_diff_error=None, *, selection_reachability_freed=None, selection_tripwire_inert_paths=None, only: "set[str] | None" = None, select: bool = False, _selection_tripwire=None, durations_out: "list | None" = None, outcomes_out: "Path | None" = None, _per_file_outcomes_export=None, _VERIFY_IMPLEMENTATION_GLOBS=None, _emit_verify_timeout_deviation, _terminate_process_group, _verify_test_timeout_seconds, _process_group_cpu_seconds=None, _reap_sandbox_residents=None, _emit_sandbox_survivor_deviation=None, _timeout_timing_phrase=None, _verify_timeout_grace_seconds=None, EXPECTED_SESSION_REF_ENV, SESSION_REF_ENV_VARS=None, SUBENV_SCRUB_CARRIERS=None, _VERIFY_TIMEOUT_MARKER, monotonic=None, land_verify: bool = False, _SELECTION_RULE_VERSION=None, _SKIP_EDGE_VERIFY_TOUCH=None, _VERIFY_DRAIN_TIMEOUT=None, _VERIFY_SANDBOX_PREFIX=None, _load_verify_duration_table=None, _per_file_duration_record=None, _reap_own_sandbox_residents=None, _reclaim_sandbox_worktrees=None, _selection_enumerated_relpaths=None, _selection_governs=None, _selection_omission_tripwire=None, _shadow_select=None, _verify_child_nice=None, _verify_dispatch_order=None, _verify_failing_test_names=None, _verify_failure_excerpt=None, _verify_heartbeat_interval=None, _verify_heartbeat_line=None, _verify_implementation_touch_globs=None, _verify_implementation_touch_pairs=None, _verify_worker_governor=None, hermetic_child_env=None, _flaky_retry_plan=None, _verify_retry_max_files=None) -> list:
    """Run every `tests/test_*.py` as an isolated subprocess (canonical V2 test interface — exit 0 =
    pass, tests/README.md §Run all tests / T-0039) CONCURRENTLY (T-0274). Preserves the old serial
    loop's contract:
      • VERDICT = pass iff the returned list is empty — fully order-independent (land aborts iff ≥1
        test fails), identical to the sequential behaviour.
      • FAIL-FAST — on the first observed failure, signal the rest to stop: not-yet-started tests bail
        immediately, in-flight ones are killed, and the helper returns promptly (the serial loop's
        `break`, kept).
    Each test is process-isolated (its own tempfile.mkdtemp git repo; it loads bin/yitc-v2 by ABSOLUTE
    path), so parallel subprocess launches never share state — cwd is read-only to them. Returns
    failure messages in the fixed `"test failed: <name>\\n<tail>"` shape; under fail-fast WHICH file is
    named may vary run-to-run (diagnostic only — re-run `tests/` for the complete set; the VERDICT is
    deterministic). ~core-count× faster than the serial loop.

    T-10977 (SPEC-0077 §3a) — `fail_fast=False`: RUN EVERY FILE AND REPORT THE COMPLETE FAILING SET.
    The parenthetical above ("WHICH file is named may vary run-to-run … re-run for the complete set")
    is a fine contract for a HUMAN reading a land abort, and a broken one for the `--rebaseline-waive`
    matcher, which is fed this very list and demands an EXACT match in BOTH directions
    (`_rebaseline_waive_coverage`): an uncovered failure refuses, and a declared token that binds
    nothing is refused as `no-match`. Over a real multi-failure state the fail-fast SUBSET moves
    between runs, so the required declaration moves with it and the re-baseline becomes a coin flip
    no quiescence settles (measured: 8 land aborts on T-10956 across two sessions in one day). With
    `fail_fast=False` no failure trips `stop`, so every file runs to its own verdict and the returned
    set is the COMPLETE one — a STABLE target to declare against. The VERDICT is unchanged (pass iff
    empty), no check is skipped or reset, and the per-file timeout bound is untouched; the cost is
    that a FAILING run no longer returns early (a passing run already ran every file, so the green
    path is unaffected). DEFAULT STAYS `True` — the candidate land verify keeps its fast abort; the
    caller that opts out is the PINNED pass (`_run_pinned_verify`), the only consumer whose output is
    matched token-by-token.

    T-11479 — `only` NARROWS the FILE SET, never the VERDICT RULE. `_run_pinned_verify` now forwards a
    caller-supplied `only` so the step-4a waive-coverage preflight can obtain the pinned text of the ONE
    file a `--rebaseline-waive` token names without paying the whole suite. The selection is sound here
    for the same reason it is sound in `_land_red_isolation_probe`: this runner executes every file as
    its OWN subprocess against its OWN tempfile.mkdtemp git repo, so a per-file verdict does not move
    when siblings run beside it. `only=None` (every existing caller) is byte-identical to today.

    T-0678 (SPEC-0071) — PER-FILE TIMEOUT, NEVER HANG. Each test is launched in its OWN process group
    (`start_new_session=True`) and bounded by a per-file wall clock (`timeout`, default
    `_verify_test_timeout_seconds()`). On expiry the test + its whole process GROUP is SIGKILLed and
    reaped (`_terminate_process_group` — orphans included, AC2), a DURABLE `deviation_captured` is
    emitted to `journal_path` (AC4 — recurring hang visible across sessions; passed by `land` as MAIN's
    events.jsonl, durable per D-0049 even though the land aborts), and a LOUD actionable failure carrying
    the `_VERIFY_TIMEOUT_MARKER` token is recorded — so a leaking/hanging test ABORTS the land instead of
    hanging it forever (the prod incident 2026-06-10). The marker lets `_land_integrate` classify the
    abort as the DISTINCT non-retriable `verify-timeout` (AC3 — never consumed by the soft ff-race
    retry). On the FIRST timeout `stop` is set, so in-flight siblings self-terminate (group-reaped) on
    their next ≤1s poll and not-yet-started tests skip — the executor barrier reaps every worker before
    return, so the abort is bounded to ~timeout (+~1s), never ∞.

    T-10075 (SPEC-0132 Rule 3) — INJECTABLE per-file DEADLINE clock (`monotonic`, default
    `time.monotonic`). The per-file timeout deadline is computed + checked through this one callable so
    the timing-drift TESTS (test_t0678) can inject a FAKE clock and fire the timeout DETERMINISTICALLY —
    no real long sleep, no wall-clock-drift flake under a saturated ~24-worker verify host. In
    production `monotonic is None` → the real `time.monotonic` is used (byte-identical behaviour). Only
    the deadline logic uses it; the worker heartbeat's `time.monotonic()` stays real (observability).

    T-10071 (SPEC-0132 Rule 2) — OPTIONAL per-run verify-metrics capture. When the caller passes a
    `metrics_out` dict it is POPULATED (never returned — the [] / [<reason>] verdict contract is
    unchanged) with the standing observability payload the SPEC-0132 governor (A2) + the Rule-3/4
    signals CONSUME: `worker_count`, `test_file_count`, `verify_wall_ms`, `queue_wait_ms` (the max
    slot-wait across files under a saturated cap), `mem_peak_kb` (children peak RSS, best-effort),
    and `fail_class` ("ok" | "failed" | "timeout"). The LOAD-BEARING minimal subset (verify wall,
    fail/timeout class, worker count) is always set. Wall/queue use REAL `time.monotonic` (NOT the
    injectable deadline clock, which a timing test may fake). Callers that omit `metrics_out` (the
    pinned / nested / merged_base drivers) are byte-identical to the pre-T-10071 behaviour. The
    fuller SPEC-0132 §2 fields (tmp/inode, fd/PID, serial-lane time) are DEFERRED additive fields
    ("the fuller payload MAY follow"); they are omitted here rather than fabricated as 0 (T-0358)."""
    import concurrent.futures
    import shutil
    import signal
    import subprocess
    import tempfile
    import threading
    import time

    if monotonic is None:
        monotonic = time.monotonic   # production default → byte-identical to the pre-T-10075 behaviour
    _run_start = time.monotonic()    # T-10071: REAL wall clock for metrics (never the injectable deadline clock)
    # T-11316: the discovered set is UNCHANGED (the same glob); only the ORDER it is handed to the
    # pool in changes — longest recorded duration first, against the FIXED table for this test dir.
    # T-11204 (SPEC-0185 §1(a)) — `test_dir` accepts EITHER one directory (every pre-T-11204 caller,
    # byte-identical) or the SEQUENCE `_declared_test_sweep_paths` resolves from the consumer's
    # declaration, so a project whose suite is not at a root-level `tests/` is actually swept.
    # ONLY the GLOB is unioned. The duration table and the selection tripwire keep anchoring on the
    # FIRST directory, and that is fail-safe rather than convenient: the table is a dispatch-ORDER
    # hint (a wrong order costs wall-clock, never a verdict) and the tripwire is report-only. The
    # VERDICT — pass iff the returned list is empty — is over the whole union either way.
    # A DUPLICATE BASENAME ACROSS TWO SWEPT DIRS FAILS THE RUN CLOSED — it is never silently skipped
    # (audit-pre pass-1 finding, high, absorbed mode-a). This runner's whole downstream surface is
    # name-keyed (`"test failed: <name>"`, `_verify_failing_test_names`, the `--rebaseline-waive`
    # matcher, the T-11479 `only` selection), so two same-named files in two swept directories cannot
    # both be reported without making every one of those matchers ambiguous. The tempting resolution
    # — keep the first and drop the rest — is REFUTED: it would run FEWER checks than the project
    # declared and report the shortfall as a pass, which is the exact false green SPEC-0185 exists to
    # end, merely relocated. So the collision is reported as a verify FAILURE naming both paths, and
    # the project resolves it by renaming or by declaring one surface. Unreachable for every project
    # that declares a single test surface — which is all of them today — so this costs nothing until
    # a project actually creates the ambiguity, and then it says so out loud.
    _dirs = [test_dir] if isinstance(test_dir, (str, Path)) else [Path(d) for d in (test_dir or [])]
    _dirs = [Path(d) for d in _dirs] or [Path(".")]
    test_dir = _dirs[0]
    _globbed: list = []
    _by_name: dict = {}
    _dup_bad: list = []
    for _d in _dirs:
        for _f in sorted(_d.glob("test_*.py")):
            _prev = _by_name.get(_f.name)
            if _prev is not None:
                _dup_bad.append(
                    f"ambiguous test file name across declared sweep dirs: {_f.name} is present at "
                    f"both {_prev} and {_f} — this runner reports failures BY NAME, so neither file "
                    f"can be identified unambiguously. Rename one, or declare one test surface "
                    f"(SPEC-0185 / T-11204).")
                continue
            _by_name[_f.name] = _f
            _globbed.append(_f)
    if _dup_bad:
        return _dup_bad
    # T-12260 — THE LAND-OVERLAP SIDECAR, resolved ONCE here rather than per file. It is set only by
    # the venue leg script (SPEC-0203 rule 4), so on every local land it is None and the per-file
    # bound below is byte-identical to before this card. Read at CALL time, not at import, so a test
    # can bind it around one call.
    _overlap_path = os.environ.get(LAND_OVERLAP_FILE_ENV) or None
    _dur_table = _load_verify_duration_table(test_dir)
    test_files = _verify_dispatch_order(_globbed, _dur_table)
    if only is not None:
        # T-11335 — run a NAMED SUBSET of the discovered files. The ONE consumer is the red-batch
        # isolation oracle (`_land_red_isolation_probe`), which re-runs just the FAILING files
        # against each batch member alone: the oracle's answer only means something if the tests run
        # exactly the way the verify ran them (same hermetic sandbox, same per-file timeout, same
        # `test failed:` shape), so it reuses THIS runner rather than growing a second one
        # (CHARTER §P5 — one question, one authority).
        #
        # It NARROWS the discovered set and never widens it: a name `only` asks for that the glob did
        # not discover is simply absent, so this can never reach outside `test_dir`. The verdict
        # contract is UNCHANGED (pass iff the returned list is empty) — and that is precisely why the
        # CALLER, not this runner, must check that the files it asked for actually exist: an empty
        # selection returns [], which reads as GREEN, and a caller that mistook "nothing ran" for
        # "nothing failed" would nominate an innocent branch. The oracle makes that check explicitly.
        #
        # `only is None` (every existing caller) leaves `test_files` untouched — byte-identical.
        test_files = [tf for tf in test_files if tf.name in only]
    # ── T-11462 (SPEC-0181) — SELECTION GOVERNS WHAT RUNS ────────────────────────────────────────
    # THE DECISION IS COMPUTED ONCE, HERE, ON THE FULL DISCOVERED ENUMERATION, and threaded forward
    # to the record below. Recomputing it after the narrowing would judge the selector against its
    # own output; and rung R1's leafness question (T-11461) is asked OF the enumeration, so it must
    # see the enumeration the glob produced. `_selection_discovered` is what the runner FOUND;
    # `test_files` from here on is what it RUNS.
    #
    # `select=False` — every existing caller — leaves this whole block inert and the run
    # byte-identical. THE OPT-IN IS ONE CALL SITE: the candidate land sweep in `_land_integrate`.
    # `land_verify=True` is deliberately NOT the gate: the PINNED last-green re-run passes it too
    # (`_run_pinned_verify`), and SPEC-0181 R1 states this rule never narrows the pinned pass. `only`
    # is excluded for the same reason — the red-batch isolation oracle asks a question about a set it
    # named itself, and a selector second-guessing that set would answer a different question.
    _gsel = governed_selection(
        test_files, select=bool(select and only is None), journal_path=journal_path,
        test_dir=test_dir, selection_diff_paths=selection_diff_paths,
        selection_diff_error=selection_diff_error,
        selection_reachability_freed=selection_reachability_freed,
        selection_tripwire_inert_paths=selection_tripwire_inert_paths,
        _VERIFY_IMPLEMENTATION_GLOBS=_VERIFY_IMPLEMENTATION_GLOBS,
        _shadow_select=_shadow_select, _selection_governs=_selection_governs,
        _selection_tripwire=_selection_tripwire,
        _selection_omission_tripwire=_selection_omission_tripwire,
        EXPECTED_SESSION_REF_ENV=EXPECTED_SESSION_REF_ENV)
    _selection_discovered = _gsel["discovered"]
    _sel_run, _sel_omit, _sel_reason = _gsel["run"], _gsel["omit"], _gsel["reason"]
    _sel_governed, _sel_govern_reason = _gsel["governed"], _gsel["govern_reason"]
    _sel_tripwire = _gsel["tripwire"]
    _sel_always, _sel_always_refused = _gsel["always"], _gsel["always_refused"]
    test_files = _gsel["test_files"]
    if not test_files:
        if metrics_out is not None:   # T-10071: a no-test-files run is a real (empty) verify — record it truthfully
            metrics_out.update({"worker_count": 0, "test_file_count": 0,
                                "verify_wall_ms": int((time.monotonic() - _run_start) * 1000),
                                "fail_class": "ok"})
        return []
    if workers is None:
        # SPEC-0132 Rule 1 (T-10074): resource-aware default — RETIRES the old fixed CPU-only
        # `min(os.cpu_count() or 4, 8)` cap. The generic-runner default is the single-verify governor W
        # (min across the multi-resource bound, capped at the ceiling), floored at 1 so a general test
        # runner ALWAYS runs at least one worker; the fail-closed REFUSAL + the true cross-land bound
        # (the slot semaphore) are LAND-admission decisions applied by `_land_integrate` before it calls
        # with an explicit `workers=`. Nested/pinned/test callers get the same resource-aware cap.
        workers = max(1, _verify_worker_governor())
    # T-11456 — the per-file spawn priority for THIS run, decided ONCE (the answer cannot change
    # mid-run) by the two-sided predicate beside the ceiling. 0 on every land / interactive / pinned /
    # nested path, which keeps the `Popen` below byte-identical to the pre-T-11456 call.
    _child_nice = _verify_child_nice(land_verify=land_verify)
    # ── T-12358 — THE DECLARED LOAD-SENSITIVE SET: PARTITION, NEVER EXCLUDE ─────────────────────
    # `test_files` stays the FULL set this run enumerated — the heartbeat total, `test_file_count`,
    # the box names, the outcomes sidecar and the metrics all keep reading it. What the carrier
    # changes is only WHICH files the concurrent pool receives: a listed file leaves `_pool_files`
    # and runs in the SERIALIZED TAIL below — after the pool and its T-12357 retry/resume, one at a
    # time, through the SAME `_run_one` path — so its pass or fail decides the verdict exactly as a
    # pool result does. Read from the FIRST swept dir, the anchor the duration table already uses.
    _ls_set = _load_sensitive_set(test_dir)
    _serial_files = [tf for tf in test_files if tf.name in _ls_set]
    _pool_files = [tf for tf in test_files if tf.name not in _ls_set]
    # T-11703 — RECORD THE BOUND IN FORCE, and WHICH RUNG SUPPLIED IT. The resolved per-file wall
    # bound was used and discarded: `land_completed.verify_metrics` carried worker_count, wall, the
    # per-file durations and the selection keys, but never the bound those durations were judged
    # against — so a fold of the journal could not tell a 300s default from an ambient
    # YITC_VERIFY_TEST_TIMEOUT override. Ask the ONE resolver (T-10257 ladder) for the rung it took
    # via its optional out-channel; both values ride the existing metrics payload below.
    # DEFENSIVE on purpose: this resolver arrives INJECTED, and existing callers/tests inject bare
    # stubs (`lambda: 60`) that accept no keyword — a TypeError falls back to the plain zero-arg call
    # and records NO source rather than breaking a stub. When the CALLER supplied `timeout`, the
    # ladder never ran, so no rung applies and none is recorded (the vocabulary stays env|declared|
    # default). No land path does that: land leaves `timeout` None.
    _timeout_source = None
    if timeout is None:
        _src: list = []
        try:
            timeout = _verify_test_timeout_seconds(source_out=_src)
        except TypeError:
            timeout = _verify_test_timeout_seconds()
        _timeout_source = _src[0] if _src else None
    # T-0579: make the verify gate HERMETIC to the launching session's STARTUP-FROZEN identity.
    # A dispatched worker's env carries YITC_EXPECTED_SESSION_REF (EXPECTED_SESSION_REF_ENV — the
    # T-0561 frozen-expected contract var). Inherited by a test subprocess it makes
    # `_resolve_session_ref` return the FROZEN expected ref and OVERRIDE the test's own explicit
    # YITC_SESSION_REF (the identity-test sandbox clears SESSION_REF_ENV_VARS but NOT this contract
    # var, which is deliberately not a carrier) → identity / dispatch-correlation suite false-RED →
    # land false-ABORT for every dispatched-worker land (T-0571, T-0576). Scrub EXACTLY that one
    # override. The session-ref CARRIERS (SESSION_REF_ENV_VARS) are LEFT intact on purpose: the
    # suite's baseline assumes SOME resolvable session ref in the env, and tests that care about a
    # specific ref clear+set it themselves — scrubbing the carriers would make `_resolve_session_ref`
    # _die ("no carrier present") in the many tests that rely on inheriting one. PATH and all other
    # env are preserved; the gate's integrity is unchanged (same tests, same verdict) — only the
    # frozen-expected override that is not the running test's own identity is removed.
    # T-9555: ALSO scrub the T-9552 auditor-selection overrides — same hermeticity rationale as the
    # EXPECTED_SESSION_REF_ENV scrub above. The verify suite validates COMMITTED code/config; the
    # runtime YITC_AUDIT_* override (set process-wide by the bench harness for a worker's AUDIT step)
    # must NOT leak into the test subprocesses, or config-default-asserting tests (test_audit_*,
    # test_t9531, test_t9313 -C resolution, + future) false-fail. In normal use these are unset → the
    # comprehension is byte-identical (no-op); only a bench worker land is affected.
    # (the tuple itself is `_HERMETIC_AUDITOR_ENV_OVERRIDES`, in the shared builder above.)
    # T-9794: ALSO scrub the T-0357 journal WRITE-quarantine (YITC_EVENTS_SINK) — same hermeticity
    # rationale as the two scrubs above. If the launching session carries a process-wide YITC_EVENTS_SINK
    # (a test-runner / an ambient quarantine), a test subprocess inherits it and diverts ALL its event
    # appends to that one shared sink — so tests that assert their OWN journal state (or that a leak is
    # ABSENT) read a foreign sink and false-fail/mask under a concurrent land verify. Tests that need the
    # sink set it EXPLICITLY per-child (sink_env → YITC_EVENTS_SINK), which still wins; this only removes
    # the AMBIENT leak. In normal use it is unset → the comprehension is byte-identical (no-op).
    # T-10073 / SPEC-0131 Rule 1: the ambient YITC_EVENTS_SINK is scrubbed HERE from the shared base (an
    # inherited ambient sink must not leak into tests), and the real-store isolation is instead applied
    # below via a PRIVATE per-subprocess YITC_EVENTS_PATH_DEFAULT (a LOW-precedence default override) for
    # every NON-allowlisted test — so a leaker's journal writes can never reach the real events.jsonl
    # WITHOUT overriding the in-process EVENTS_PATH redirect the readback tests rely on. The structural,
    # self-enforcing generalization the reproducer (test_t0357 canary) needed.
    # The override pair itself (YITC_EVENTS_PATH_DEFAULT / YITC_EVENTS_GUARD_ROOT) is ALSO scrubbed from the
    # base, so a NESTED verify run (the pinned/merged_base drivers, or a test that itself calls
    # _run_verify_tests) does NOT inherit the OUTER run's override — each run sets its OWN pair fresh for
    # non-allowlisted tests, and an ALLOWLISTED test sees a clean env (truly exempt, no inherited override).
    # T-10166: ALSO scrub the SPEC-0103 dispatched-worker SYNCHRONOUS-LAND marker
    # (YITC_SYNCHRONOUS_LAND) — same hermeticity rationale as the scrubs above. A dispatched worker
    # carries YITC_SYNCHRONOUS_LAND=1 (dispatch.py); if it leaks into a verify test subprocess that
    # spawns its OWN land, that inner land false-REFUSES under the L737 synchronous-land guard
    # (detached/orphaned detection) → the test false-fails → the worker's land is blocked_on_land
    # (real incident: T-10156/57/58 all blocked 2026-07-07). A test that must exercise synchronous
    # land sets the marker EXPLICITLY per-child, which still wins; this only removes the AMBIENT leak.
    # Interactive/CI land (marker unset) → the comprehension is byte-identical (no-op).
    # T-11176: the SECOND land-mode marker gets the SAME treatment — `_HELD_TURN_CLAIM_ENV`
    # (YITC_LAND_HELD_TURN_PID). T-11101 added it to the very guard T-10166's scrub above protects,
    # and did not extend the scrub with it. MEASURED on the mechanism's FIRST live admission
    # (2026-08-16, T-11104's own completion worker): the claim is EXPORTED for the detached land
    # SPEC-0180 admits, so it was INHERITED by every verify subprocess that land spawned;
    # test_worker_synchronous_land_guard's section-D arms — which set no claim — then had their inner
    # `cmd_land` read the GHOST, fail provenance (`no-dispatch-record`: a verify child's journal holds
    # no `bg_dispatch_launched` row) and emit signal="held-turn-claim-invalid" where they assert
    # "session-leader". The pinned test false-failed and the ADMITTED land ABORTED on its own guard —
    # a false RED indistinguishable from a real one, whose predictable next move is an owner-gated
    # `--rebaseline` spent on a test that is not broken. Identical contract to the marker above: a
    # test that must exercise a CLAIM sets it EXPLICITLY per-call (which still wins — the parent-side
    # predicate `_resolve_held_turn_claim` is untouched and every refusal reason still fires); this
    # removes ONLY the AMBIENT leak. Non-claim land (var unset) → byte-identical no-op.
    # ^ the base scrub itself now lives in the shared builder `hermetic_child_env` (T-11133): the
    # rationale blocks above stay here at the runner's call site, the CODE has one home so an
    # instrument measuring this runner cannot mirror it half-way (the T-11123 profile artifact).
    # T-10073 / SPEC-0131 Rule 1 — HERMETIC-BY-DEFAULT per-subprocess sandbox. One throwaway root for
    # the whole run (a per-test subdir inside it), reclaimed in the finally below. Isolation is applied
    # by the runner to EVERY spawned subprocess, so a NEWLY-added test inherits it with NO per-test
    # opt-in (self-enforcing) — the harness-level generalization of the SPEC-0041 per-test host-var
    # sandbox discipline. It redirects ONLY the ambient write/config surfaces the enumerated set names
    # (HOME / TMPDIR / XDG_* / git-global-config, + a private DEFAULT journal via YITC_EVENTS_PATH_DEFAULT
    # for non-allowlisted tests); corpus READS via cwd are deliberately untouched (see the allowlist above).
    # T-12185: the sandbox follows the SAME temp base headroom measured (idempotent no-op when
    # `YITC_VERIFY_TMPDIR` is unset). The mkdtemp call itself is UNCHANGED — no `dir=`; it reads
    # `tempfile.tempdir`, which is what the installer set.
    _install_verify_tmpdir()
    _sandbox_root = Path(tempfile.mkdtemp(prefix=_VERIFY_SANDBOX_PREFIX))
    # (the XDG key list is `_HERMETIC_XDG_KEYS`, in the shared builder above.)
    # Per-test box subdir names are NUMERIC ("box<N>"), NOT tf.stem: a subprocess run under the sandbox
    # (git -C <box>/tmp/... , a nested CLI) carries the box path in its argv, and a stem-named box would
    # embed the "test_" substring / a ".py"-shaped token into that path — false-tripping a test that
    # naive-greps its own captured subprocess argv for "test_"/".py" (e.g. test_t10008's suite-launch
    # canary). A numeric token is inert to every such content check.
    _box_names = {tf: f"box{i}" for i, tf in enumerate(test_files)}

    def _hermetic_child_env(tf: Path, box: "str | None" = None) -> dict:
        """This run's per-test child env — a thin bind of the shared builder `hermetic_child_env`
        (above) to THIS run's sandbox box + guard root. The builder is the single home of what a
        verify child sees, so the profiling instrument measures the same environment (T-11133).

        T-12357 — `box` OVERRIDES which subdir of THIS run's sandbox root the child gets, and is
        used only by the isolated retry / resume executions below, which need a FRESH box rather
        than the one the killed pool execution already dirtied. `box=None` — every pool execution —
        resolves `_box_names[tf]` exactly as before, so the ordinary path is byte-identical. The
        sandbox ROOT is unchanged either way, so the retry stays inside the tree the `finally`
        reclaims and can never leak a directory the teardown does not know about."""
        return hermetic_child_env(
            _sandbox_root / (box or _box_names[tf]), tf.name, cwd,
            expected_session_ref_env=EXPECTED_SESSION_REF_ENV,
            scrub_carriers=(SUBENV_SCRUB_CARRIERS or SESSION_REF_ENV_VARS))

    stop = threading.Event()
    failures: list = []
    flock = threading.Lock()
    done = [0]                          # T-9601: completed test-file count, read by the heartbeat thread
    max_queue_wait = [0.0]              # T-10071: longest a submitted file waited before its worker slot freed
    submit_t = [0.0]                    # T-10071: set just before ex.map (real clock) — the queue-wait baseline
    _decided: dict = {}                 # T-12357: {name: outcome} for every POOL execution that reached a
                                        # REAL verdict — the explicit ledger the resume set is computed
                                        # from (see `_record`). Written under the existing `flock`; no new
                                        # lock. Never read by anything but the resume below.
    file_durations: list = []           # T-11124: (file, wall_ms, outcome) for EVERY file that STARTED — the
                                        # per-file elapsed this runner has always measured and always discarded
                                        # (it necessarily knows it: each file is its own subprocess under the
                                        # T-0678 per-file wall clock). Appended under the existing `flock`; no
                                        # new lock. Bounded into `verify_metrics.per_file_durations` below.

    def _mark_done():                   # T-9601: a file finished (pass/fail/launch-error/timeout)
        with flock:
            done[0] += 1

    def _trip_fail_fast():
        """T-10977: the ONE place a failure decides whether the REST of the run stops. Under the
        default (`fail_fast=True`) this is the unchanged `stop.set()` — every failure branch below
        routes through here, so the complete-set mode cannot be half-applied by a branch that was
        missed. Under `fail_fast=False` it is a no-op: `stop` is never set, so no sibling is skipped
        or killed and every file reaches its own verdict."""
        if fail_fast:
            stop.set()

    def _run_one(tf: Path, _sink: "list | None" = None, _box: "str | None" = None,
                 _isolated: bool = False):
        """T-12357 — the ONE subprocess-running body, now reused verbatim by the isolated retry and
        the resume. The three parameters are DEFAULTED, so a pool execution (`_run_one(tf)` — every
        pre-existing call, including the `ex.map` below) takes byte-identical branches:
          * `_sink` — where a failure is appended (`failures` when None), so an isolated re-run can
            be judged WITHOUT contaminating the run's own verdict list before it is decided;
          * `_box` — a fresh sandbox subdir (see `_hermetic_child_env`);
          * `_isolated` — under it the entry fail-fast skip is bypassed, `_trip_fail_fast()` is NOT
            called (an isolated verdict must never stop anything), and `_record` writes NOTHING:
            neither a `file_durations` row nor a `_decided` entry. The per-file series is ONE row per
            file the POOL ran (`sample_count` is measured against `test_file_count`, and the outcomes
            sidecar has a CLOSED vocabulary a second row for the same file would breach — both
            measured RED when a retry row was appended under an `isolated-` prefix). The isolated
            verdict has its own record, `flaky_retry.rows[].isolated`, so dropping it here loses
            nothing and keeps `verify-durations --rebuild` from ever reading a retry as a baseline.
        Every other line of the body — the Popen, the hermetic env, the per-file timeout ladder, the
        overlap credit, the grace, the group reap, the excerpt — is UNCHANGED and shared."""
        _fail_sink = failures if _sink is None else _sink
        if stop.is_set() and not _isolated:   # a sibling already failed → skip not-yet-started tests (fail-fast)
            return
        _wait = time.monotonic() - submit_t[0]   # T-10071: slot-wait for THIS file (real clock, not the deadline clock)
        with flock:
            if _wait > max_queue_wait[0]:
                max_queue_wait[0] = _wait

        # T-11124: this file's own wall, on the REAL clock — NEVER the T-10075 injectable deadline
        # clock, which a timing test may drive to 1e9. Same rule `verify_wall_ms` / `queue_wait_ms`
        # already follow, so a fake-clock test cannot fabricate a duration into the journal series.
        _real_t0 = time.monotonic()

        def _record(outcome: str):
            """Record THIS file's elapsed + outcome. Called on EVERY path a started file can leave by
            — including the ones that leave EARLY. A timed-out or errored file costs LESS wall time
            than it would have, so DROPPING it biases every downstream ranking downward (the same bias
            T-11123 guards); it is recorded WITH its outcome instead, and the outcome field is what
            lets a reader un-bias. A file that never STARTED (skipped by fail-fast before its Popen)
            is honestly absent — `sample_count` vs `test_file_count` makes that gap visible."""
            if _isolated:
                return          # T-12357 — the retry's record is `flaky_retry.rows[]`, never a series row
            with flock:
                file_durations.append((tf.name, int((time.monotonic() - _real_t0) * 1000), outcome))
                # T-12357 — THE EXPLICIT PER-ATTEMPT LEDGER the resume set is computed from. It is
                # written HERE, under the lock this function already holds, and ONLY for a POOL
                # execution that reached a REAL verdict. That bound is the whole point: a
                # `killed-fail-fast` file records NOTHING, so the resume re-runs it; an isolated
                # re-run records nothing, so a file cleared in isolation is not thereby treated as
                # having been decided by the pool; and a resume execution writes only its own
                # genuine verdict. `file_durations` keeps recording EVERYTHING (it is the duration
                # series, and dropping entries would bias it) — the resume decision deliberately
                # never reads it, because a duration row exists for outcomes that are not verdicts.
                if not _isolated and outcome in _REAL_VERDICT_OUTCOMES:
                    _decided[tf.name] = outcome

        _child_env = _hermetic_child_env(tf, _box)
        try:
            # T-0678: start_new_session=True → the test is its own process-group leader, so a timeout /
            # fail-fast kill can SIGKILL the WHOLE group (the test + every child it forked), reaping
            # orphans (AC2). cwd/stdout contract unchanged. T-10073: env is now the PER-SUBPROCESS
            # hermetic sandbox (private HOME/TMPDIR/XDG/git + real-store isolation), not the shared base.
            # T-11456: `preexec_fn` is passed ONLY when the priority is actually lowered, so a land /
            # interactive / pinned run makes the IDENTICAL call it made before this card. The callable
            # runs in the forked child between fork and exec: one `os.nice` syscall, no allocation and
            # no lock, which is what keeps it safe from this multi-threaded runner. `start_new_session`
            # (T-0678, the group-kill contract) is unaffected — CPython applies both, and the child
            # stays its own process-group leader, so a timeout / fail-fast still SIGKILLs the whole
            # group. The nice value is INHERITED by everything the test forks, so a leaked descendant
            # is lowered too. Lowering is per-process and one-way (a non-root child cannot renice back
            # down), which is exactly the guarantee wanted: the worker cannot claw priority back.
            proc = subprocess.Popen([sys.executable, str(tf)], cwd=str(cwd), env=_child_env,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                    start_new_session=True,
                                    **({"preexec_fn": (lambda _n=_child_nice: os.nice(_n))}
                                       if _child_nice > 0 else {}))
        except OSError as e:
            with flock:
                _fail_sink.append(f"test failed: {tf.name}\ncould not launch: {e}")
            if not _isolated:
                _trip_fail_fast()
            _mark_done()                 # T-9601: progress counts a launch-failed file as processed
            _record("launch-error")      # T-11124: recorded WITH its outcome, never dropped
            return
        out = ""
        _t_start = monotonic()             # T-10780: wall baseline for the honest timeout report
        # T-12260 — the WALL-CLOCK baseline for the land-overlap window, in EPOCH seconds, because
        # the box writes its sidecar in epoch and the two must be comparable. Deliberately NOT the
        # injectable `monotonic` clock: that clock is a test seam for the DEADLINE, while this is a
        # window over an external record, and reading a fake clock against a real file would compare
        # two different timelines. `_ov_credited` is how much of this file's own overlap has already
        # been paid into `deadline`, so a re-read that returns the same total extends nothing —
        # the credit is monotone and idempotent, never a repeated grant.
        _t_start_epoch = time.time()
        _ov_credited = 0.0
        deadline = _t_start + timeout      # T-0678: per-file wall clock (T-10075: injectable for tests)
        # T-10789 — the file's verdict is decided by the DIRECT CHILD's EXIT, never by whether some
        # descendant still holds the inherited stdout pipe. The old loop polled
        # `proc.communicate(timeout=1)`, which returns at EOF on stdout — and that pipe is inherited by
        # every grandchild. So a test that spawned a background child and exited 0 (PASS) left the pipe
        # open, the loop kept charging the wall deadline against an already-reaped, already-passing
        # child, and at the bound the runner killed it and ABORTED the land. Reproduced directly: direct
        # child exited=0 at ~0s, the loop still blocked at 15s and would block to the full bound. The
        # kill signature is cpu≈0 ≪ wall, which T-10780's renderer reports as "starved host" — so the
        # true cause was invisible in the very message meant to explain it. That is the "leaks a child"
        # half of the recurring land-verify-timeout class, and it is the RUNNER's bug, not the test's.
        #
        # Shape: a daemon READER thread drains stdout concurrently (so a child that fills the 64KB pipe
        # buffer can still make progress — the reason the old code used communicate() rather than
        # wait()), while the loop waits on the CHILD. On exit the leaked descendants are group-SIGKILLed
        # HERE, which closes the pipe and lets the reader finish; the join is BOUNDED so a descendant
        # that escaped the group (its own setsid) cannot extend the file either — partial output is
        # still returned, since the reader accumulates chunks rather than one read-to-EOF.
        # GATES UNCHANGED: a genuinely HANGING file (direct child never exits) still trips the SAME
        # unchanged 300s bound via the timeout branch below, and orphan reaping is strictly INCREASED
        # (leaked descendants now die on the clean-exit path too, not only on timeout/fail-fast).
        # T-10875 — starvation-grace bookkeeping for THIS file: how many bound-length windows the
        # deadline has already been pushed out, and the CPU reading at the last push (the progress
        # baseline the next decision is made against).
        _grace_granted = 0
        _grace_prev_cpu = None
        _buf: list = []

        def _drain():
            stream = proc.stdout
            if stream is None:
                return
            try:
                while True:
                    chunk = stream.read(65536)
                    if not chunk:
                        return
                    _buf.append(chunk)
            except Exception:
                return          # closed/errored mid-read — partial output is still in _buf

        _reader = threading.Thread(target=_drain, daemon=True)
        _reader.start()

        def _reap_leaked_descendants():
            """SIGKILL the test's process GROUP WITHOUT touching proc's streams (unlike
            `_terminate_process_group`, which closes them — that would cut the reader off mid-drain and
            lose the failure excerpt). The direct child is already reaped by `proc.wait()` here; this
            kills only what it left behind, which also closes the inherited pipe."""
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                pass            # an empty/already-gone group is the NORMAL no-leak case

        while True:             # wait on the CHILD; a fail-fast stop / per-file timeout still preempts
            try:
                proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                if stop.is_set():
                    _terminate_process_group(proc)   # T-0678: fail-fast kill now also group-reaps siblings
                    # T-11124: a fail-fast kill TRUNCATES this file's wall, so it is recorded under its
                    # OWN outcome rather than silently mixed into the passed/failed cohort — a reader
                    # ranking by duration can exclude it explicitly instead of being biased by it.
                    _record("killed-fail-fast")
                    return
                # T-12260 — read the clock ONCE per round and reuse it below, so this loop
                # consumes exactly the clock calls it always did (the T-10075 injectable-clock tests
                # drive their deadline by CALL COUNT, and an extra read would shift every one of
                # them) while the overlap window can still be expressed on the SAME timeline the
                # deadline lives on.
                _now = monotonic()
                if _now >= deadline:
                    # T-12260 — MEASURED CONTENTION IS NOT THIS FILE'S TIME, so it is given back
                    # BEFORE anything else at this deadline. On the venue box a Stage-6 leg runs at
                    # nice 19 beside a nice-0 land and receives ~1% of contended CPU (CFS weights 15
                    # vs 1024) — it is effectively PAUSED while every wall bound keeps ticking, which
                    # is how T-12251 attempt 1 lost a whole Stage-6 run (cand wall 600.6 s, the file
                    # killed and attributed not-in-diff, the pass then re-run from scratch). The
                    # sidecar the leg writes says exactly WHEN a foreign land held the box, so the
                    # deadline is pushed out by the part of this FILE'S OWN window that overlapped
                    # one. Note what this is NOT: it is not a raised bound (nothing is charged when
                    # no land ran), not a class judgement, and not a second control path — the file
                    # runs on as the SAME live process toward the SAME bound, merely uncharged for
                    # time it was never given.
                    # ORDERED BEFORE THE T-10875 GRACE DELIBERATELY. Grace INFERS starvation from a
                    # cpu/wall band and is hard-capped at 2 windows; this is a MEASUREMENT of an
                    # external fact. Spending an inferential window on time we can prove was stolen
                    # would consume the hang guard's own budget to pay a debt that is already
                    # itemised — so the measured seconds are credited first and the grace below is
                    # reached only once they are exhausted, entirely unchanged when they are zero.
                    # THE HANG GUARD IS UNTOUCHED BY CONSTRUCTION: `_land_overlap_seconds` is bounded
                    # by the file's own elapsed window and is 0.0 whenever the sidecar is absent,
                    # unreadable or names no land — so a hanging file on any box that is not being
                    # starved by a land is killed on exactly the deadline it always was.
                    if _overlap_path:
                        # THE WINDOW IS ANCHORED IN EPOCH BUT MEASURED ON THE DEADLINE'S OWN CLOCK.
                        # The box writes the sidecar in epoch seconds, so the window must start at a
                        # real timestamp; its LENGTH is taken from `monotonic` — the same (injectable)
                        # clock the deadline is computed against — because a credit denominated in a
                        # different timeline than the bound it extends is not a credit, it is a race
                        # between two clocks. In production the two are the same rate and this is an
                        # identity; under an injected clock it is what makes the extension testable.
                        _ov = _land_overlap_seconds(_t_start_epoch,
                                                    _t_start_epoch + (_now - _t_start),
                                                    _overlap_path)
                        if _ov > _ov_credited:
                            deadline += (_ov - _ov_credited)
                            _ov_credited = _ov
                            continue       # same process, same file, the bound merely uncharged
                    # T-0678 — HARD per-file timeout: this test exceeded its bound. KILL its whole process
                    # group (orphans reaped, AC2), emit the durable cross-session trace (AC4), and record a
                    # LOUD actionable failure carrying the marker (so `land` aborts non-retriably, AC1/AC3)
                    # — NEVER hang. `stop.set()` fail-fasts the rest (siblings self-kill on their next poll).
                    # T-10780 — MEASURE, don't DIAGNOSE. Sample wall + whole-group CPU BEFORE the kill (the
                    # /proc entries die with the group), and report both instead of the old flat assertion
                    # "This test hangs or leaks a child": that assertion carried no evidence and was wrong
                    # twice in one session (2026-08-07), sending an operator to debug tests that PASS at the
                    # same tree state while the host was merely saturated. cpu vs wall separates the two.
                    # Wall is read off the SAME (injectable, T-10075) clock the deadline uses, so a test
                    # driving a fake clock gets a deterministic wall rather than a real ~0.
                    _wall = monotonic() - _t_start
                    # T-11704 — the sampler returns (cpu_seconds, member_count): the group's CPU
                    # total AND its OBSERVED CONCURRENCY, which is the denominator the classifier
                    # reads its `long` band against. Unpacked DEFENSIVELY: a PINNED/older injected
                    # sampler (and any stub) returns a bare float, which reads as members=None — the
                    # unmeasured, pre-T-11704 single-core classification, unchanged. A measurement
                    # must never break the abort it describes.
                    _sample = _process_group_cpu_seconds(proc.pid) if _process_group_cpu_seconds else None
                    _cpu, _members = _sample if isinstance(_sample, tuple) else (_sample, None)
                    # T-10875 — BEFORE the kill, ask whether this file is merely STARVED: still doing
                    # real work (cpu well above the deadlock floor) but denied CPU by the land wave
                    # around it, which SPEC-0132 admission produces BY DESIGN on this host. If so it is
                    # given the CPU time it was never given — a bounded, progress-conditional extension
                    # of the SAME live process, at most `_VERIFY_TIMEOUT_GRACE_MAX` windows. The helper
                    # reads the T-10871 class, so a `long` (real work / busy loop) or `stalled`
                    # (deadlock / blocking wait) file gets 0.0 and drops straight into the UNCHANGED
                    # kill below — a hang is still killed on this first deadline, whatever its cpu
                    # profile. Not injected (a pinned/nested driver) -> 0.0 -> pre-T-10875 behaviour.
                    if _verify_timeout_grace_seconds:
                        try:
                            _ext = _verify_timeout_grace_seconds(_wall, _cpu, timeout, _grace_granted,
                                                                 _grace_prev_cpu, _members)
                        except TypeError:
                            # A PINNED/older injected helper predates the T-11704 members argument.
                            # Fall back to its arity — it then reads the unmeasured single-core band,
                            # i.e. exactly the pre-T-11704 decision, rather than breaking the kill.
                            _ext = _verify_timeout_grace_seconds(_wall, _cpu, timeout, _grace_granted,
                                                                 _grace_prev_cpu)
                    else:
                        _ext = 0.0
                    if _ext > 0:
                        _grace_granted += 1
                        _grace_prev_cpu = _cpu
                        deadline = monotonic() + _ext
                        continue                 # same process, same file, one more bounded window
                    # Defensive: an uninjected renderer must never crash the abort it describes.
                    if _timeout_timing_phrase:
                        try:
                            _phrase = _timeout_timing_phrase(_wall, _cpu, _members)
                        except TypeError:
                            _phrase = _timeout_timing_phrase(_wall, _cpu)   # pinned/older arity
                    else:
                        _phrase = f"wall={_wall:.1f}s cpu={'unavailable' if _cpu is None else f'{_cpu:.1f}s'}."
                    _terminate_process_group(proc)
                    try:
                        _emit_verify_timeout_deviation(tf.name, timeout, journal_path, _wall, _cpu,
                                                       _grace_granted, _members)
                    except TypeError:
                        # A PINNED/older injected emitter predates the T-11704 members argument (or,
                        # older still, the T-10875 grace one). The trace is best-effort by contract and
                        # must never mask the abort it describes — step DOWN through the earlier
                        # arities rather than let the emit break the kill.
                        try:
                            _emit_verify_timeout_deviation(tf.name, timeout, journal_path, _wall, _cpu,
                                                           _grace_granted)
                        except TypeError:
                            _emit_verify_timeout_deviation(tf.name, timeout, journal_path, _wall, _cpu)
                    with flock:
                        _fail_tails[tf.name] = _tail_rv._output_tail_lines("".join(_buf))   # T-12447 — partial output
                        _fail_sink.append(
                            f"test failed: {tf.name}\n"
                            # T-10875: `grace=N` states how many starvation-grace windows this kill
                            # spent first — 0 is the unchanged first-deadline kill (every hang), N>0 a
                            # file that WAS given the CPU time it was starved of and still could not
                            # finish. A reader can tell the two apart without re-running anything.
                            f"{_VERIFY_TIMEOUT_MARKER} TIMED OUT after {timeout:g}s "
                            f"(grace={_grace_granted}) — KILLED (process group "
                            f"reaped, orphans included); land ABORTED rather than hang. Measured at the kill: "
                            # T-10871 — `_phrase` now CLASSIFIES the kill (long / starved / stalled) and
                            # carries that class's own recovery advice. The blanket "if the work is
                            # genuinely this long, raise the bound" tail that used to sit here is GONE: it
                            # was right for one class of three and was the blind stretch SPEC-0103 forbids
                            # for the other two. The kill itself, the marker and the bound are UNCHANGED —
                            # a starved-classified kill still ABORTS the land, it just stops misdiagnosing.
                            f"{_phrase} A durable deviation_captured was emitted "
                            f"(fingerprint=land-verify-timeout:{tf.name}).")
                    if not _isolated:
                        _trip_fail_fast()
                    _mark_done()         # T-9601: progress counts a timed-out file as processed
                    _record("timed-out")  # T-11124: the cohort-complement case (AC4) — a file that hit
                                          # its bound is the MOST interesting entry in a duration series,
                                          # so dropping it would blind exactly the growth this records.
                    return
                continue                 # still running, still inside the bound — keep waiting
            # T-10789 — the direct child EXITED, so THIS FILE IS DECIDED by its returncode. Reap
            # whatever it leaked (this also closes the inherited pipe), then take the drained output
            # under a BOUNDED join and stop charging the deadline. Nothing a descendant does from here
            # can turn this file's verdict into a timeout.
            _reap_leaked_descendants()
            _reader.join(timeout=_VERIFY_DRAIN_TIMEOUT)
            out = "".join(_buf)
            try:
                if proc.stdout is not None:
                    proc.stdout.close()
            except Exception:
                pass
            break
        _rc = proc.returncode
        if _rc != 0:
            with flock:
                # T-10733: head+tail excerpt (was a front-truncating `[-400:]` tail slice, which cut
                # away the very line naming the failing assertion). Short outputs pass through verbatim.
                _fail_sink.append(f"test failed: {tf.name}\n{_verify_failure_excerpt(out)}")
                _fail_tails[tf.name] = _tail_rv._output_tail_lines(out)   # T-12447 — the verbatim END of the output
            if not _isolated:
                _trip_fail_fast()       # fail-fast: trip the gate for the remaining workers
        _mark_done()                     # T-9601: a file ran to completion (pass or fail)
        _record("failed" if _rc != 0 else "passed")   # T-11124: the normal-verdict cohort

    # T-9601: in a DISPATCHED-worker context, stream a periodic verify-progress heartbeat to STDERR so
    # the minutes-long foreground `land` stays visibly alive (foreground-by-construction; SPEC-0103 /
    # T-9600 intent). DISABLED (no thread, no output) outside a worker context or when the interval is
    # <=0 — so the engine self-build / sibling tests are byte-identical to the pre-T-9601 behaviour.
    _flaky_retry_record: "dict | None" = None    # T-12357: ABSENT (never {}) when no retry was reached
    _fail_tails: dict = {}                       # T-12447: file -> last output lines of its LATEST failed run
    # T-12447 — the tail + bound helpers live in `remote_verify` (the record's home, beside its host
    # fold) and are reached LAZILY, so the runner gains no top-level def of its own: every top-level
    # def this function reaches is part of the T-11519 move-set and would owe a host residue.
    try:
        from lib import remote_verify as _tail_rv
    except ImportError:                                  # pragma: no cover — script-style import
        import remote_verify as _tail_rv                  # type: ignore[no-redef]
    worker_ctx = bool(os.environ.get(EXPECTED_SESSION_REF_ENV, "").strip())
    hb_interval = _verify_heartbeat_interval()
    hb_stop = threading.Event()
    hb_thread = None
    if worker_ctx and hb_interval > 0:
        def _heartbeat():
            start = time.monotonic()
            while not hb_stop.wait(hb_interval):   # wait() returns True when stopped → exit cleanly
                with flock:
                    d = done[0]
                print(_verify_heartbeat_line(d, len(test_files), time.monotonic() - start),
                      file=sys.stderr, flush=True)
        hb_thread = threading.Thread(target=_heartbeat, daemon=True)
        hb_thread.start()
    try:
        submit_t[0] = time.monotonic()   # T-10071: queue-wait baseline (real clock) — set just before dispatch
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
            list(ex.map(_run_one, _pool_files))      # T-12358: the pool never sees a listed file
        # ── T-12377 — THIS LEG'S POOL HAS DRAINED: SAY SO, UNCONDITIONALLY ───────────────────────
        # The marker is written BEFORE `if failures` and whether or not this leg will retry, because
        # the sibling leg's retry is what waits on it — a green leg that stayed silent would hold its
        # failing sibling until the ceiling. No barrier (the local single-leg path) → nothing written.
        _quiet = _quiet_barrier_from_env()
        if _quiet is not None:
            try:
                _qd = Path(_quiet["dir"])
                _qd.mkdir(parents=True, exist_ok=True)
                (_qd / f"{_quiet['leg']}{QUIET_MARKER_SUFFIX}").write_text(
                    f"{time.time():.3f}\n", encoding="utf-8")
            except OSError:
                pass            # a barrier fault can never turn a verdict; the sibling's wait is bounded
        # ── T-12357 — ISOLATED RE-RUN, THEN RESUME ───────────────────────────────────────────────
        # HERE, inside the `try`, because the `finally` below tears down `_sandbox_root` — the
        # retry must run while this run's sandbox is still alive, on the SAME tree, or it would not
        # be answering the same question. The pool has FULLY DRAINED at this point (the `with`
        # block joined every worker), so nothing reads `stop` any more and clearing it below races
        # with nothing.
        #
        # WHAT THIS DOES NOT DO: it never clears a failing check. A file leaves `failures` only by
        # PASSING, alone, on this same tree — which is the SPEC-0077 §3 `environmental` preflight's
        # own oracle (`_run_pinned_verify(workers=1, only=...)`), run automatically INSIDE the
        # attempt instead of costing a second land and another reservation wait. Any file that
        # fails in isolation leaves `failures` exactly as it was and the leg aborts as it does
        # today, with `isolated: fail` recorded so the abort names a real defect and not a coin flip.
        if failures:
            _plan_fn = _flaky_retry_plan or globals()["_flaky_retry_plan"]
            _bound_fn = _verify_retry_max_files or globals()["_verify_retry_max_files"]
            _bound = _bound_fn()
            _plan = _plan_fn(list(failures), _VERIFY_TIMEOUT_MARKER, _bound,
                             _verify_failing_test_names(list(failures)))
            if "retry" in _plan:
                _pool_tail = len([tf for tf in _pool_files if tf.name not in _decided])   # T-12358: pool files only
                try:
                    _load1 = os.getloadavg()[0]
                except (OSError, AttributeError):
                    _load1 = None      # unmeasurable — recorded ABSENT, never a fabricated 0.0
                _by_name_run = {tf.name: tf for tf in test_files}
                # ── T-12377 — THE QUIET POINT: wait for the SIBLING leg's pool before re-running ──
                # «does it pass alone on this tree» is only answered alone. ONE wait per leg (the
                # rows share it), bounded by the sibling — its marker, its exit — and as a last
                # resort by the per-file wall bound this run already resolved, never by a window of
                # its own. The load figure is re-read AFTER the wait so `load1` describes the
                # moment the retry actually ran. No barrier → no wait, no keys: today's row shape.
                _qw: "dict | None" = None
                if _quiet is not None:
                    _qw = _quiet_point_wait(_quiet["dir"], _quiet["leg"], _quiet["sibling"],
                                            _quiet["sibling_pid"], float(timeout))
                    try:
                        _load1 = os.getloadavg()[0]
                    except (OSError, AttributeError):
                        _load1 = None
                stop.clear()
                _rows, _all_pass = [], True
                for _i, _nm in enumerate(_plan["retry"]):
                    _tf = _by_name_run.get(_nm)
                    _row = {"file": _nm, "pool_tail": _pool_tail}
                    if _load1 is not None:
                        _row["load1"] = round(_load1, 2)
                    if _qw is not None:
                        _row["quiet_wait_s"] = _qw["quiet_wait_s"]
                        _row["quiet_wait"] = _qw["quiet_wait"]
                    if _tf is None:
                        # FAIL-CLOSED: a name the failure text carried that this run's enumeration
                        # does not resolve cannot be re-run, so it cannot be cleared either. It is
                        # recorded as `unrunnable` and treated as a NON-pass, never as a clearance.
                        _row["isolated"] = "unrunnable"
                        _all_pass = False
                    else:
                        # T-12377 (AC5) — TWO isolated attempts, the bound the owner set («дадим 2
                        # шанса»): a file that fails alone once is run alone ONCE more; the SECOND
                        # verdict is final either way. Two calls, not a loop with a count — so the
                        # bound cannot be re-rolled by a config value. The per-attempt list is
                        # recorded BESIDE the scalar `isolated` (= the last attempt's verdict), which
                        # the T-12358 land-tail entry fold reads unchanged — a file that needed two
                        # tries still counts as an isolated pass there, which is the point.
                        _iso: list = []
                        _run_one(_tf, _sink=_iso, _box=f"retry{_i}", _isolated=True)
                        _attempts = ["fail" if _iso else "pass"]
                        if _iso:
                            _iso2: list = []
                            _run_one(_tf, _sink=_iso2, _box=f"retry{_i}b", _isolated=True)
                            _attempts.append("fail" if _iso2 else "pass")
                        _row["isolated"] = _attempts[-1]
                        _row["isolated_attempts"] = _attempts
                        if _attempts[-1] != "pass":
                            _all_pass = False
                    _rows.append(_row)
                if _all_pass:
                    # EVERY named file passed alone → the failures were load-only. Clear them and
                    # RESUME over the files this run has NOT yet decided (the explicit `_decided`
                    # ledger, never `file_durations`). ONE retry only: the resume never re-plans, so
                    # a failure it produces is final — which is what keeps a deterministic defect
                    # from being re-rolled until it happens to pass.
                    _resume = [tf for tf in _pool_files if tf.name not in _decided]   # T-12358: never a listed file
                    del failures[:]
                    if _resume:
                        _box_names.update({tf: f"resume{_i}" for _i, tf in enumerate(_resume)})
                        submit_t[0] = time.monotonic()
                        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex2:
                            list(ex2.map(_run_one, _resume))
                    _flaky_retry_record = {"rows": _rows, "resumed": len(_resume)}
                else:
                    _flaky_retry_record = {"rows": _rows}
            else:
                _flaky_retry_record = dict(_plan)
        # ── T-12358 — THE SERIALIZED TAIL ────────────────────────────────────────────────────────
        # Still inside the `try` (the sandbox is alive), AFTER the pool has reached its full verdict
        # (retry + resume included). Each listed file runs ALONE — no sibling verify child beside it
        # in this run — through the UNCHANGED pool path of `_run_one`: it records to `failures`,
        # `_decided`, `file_durations` and the outcomes sidecar exactly as a pool file does, so the
        # set moves WHERE a file runs, never WHETHER it counts. A failure here IS re-run in
        # isolation — see the T-12426 block below. T-12358 wrote «the tail already IS the isolated
        # run», which held on the LOCAL single-leg path and is FALSE on a two-leg venue: `run_legs`
        # starts cand and pinned in PARALLEL on one box, so a leg's tail runs beside the SIBLING
        # leg's pool or tail (measured, analysis KNOWN-4: 39/39 post-pool rows across 17 lands read
        # `quiet_wait: sibling-drained` at `quiet_wait_s: 0.0`, with load1 5.28–34.16 at that exact
        # moment). Under that contention ONE run was terminal, so a lane member got LESS protection
        # than a pool file, which already gets two isolated attempts after the sibling drains.
        # FAIL-FAST IS PRESERVED, not bypassed: the T-12357 retry `stop.clear()`s to re-run its
        # files, and a pool that is STILL failing after it must re-trip the gate — otherwise the tail
        # would run to completion behind an abort that is already decided. Under `fail_fast=True` a
        # tripped gate skips every tail file as `not-started`, exactly like a not-yet-started pool
        # file; under `fail_fast=False` (the pinned driver) every tail file reaches its own verdict.
        if failures:
            _trip_fail_fast()
        for _tf in _serial_files:
            _run_one(_tf)
        # ── T-12426 — THE LANE RETEST: a lane member gets the pool flake's two isolated attempts ──
        # Still inside the `try` (the sandbox must be alive — the same rule the T-12357 block states).
        # A lane member is EXCLUDED from `_pool_files`, so its failure is never in `failures` when
        # `_flaky_retry_plan` is consulted and the tail loop above re-runs nothing: before this block
        # a lane file that failed under sibling-leg load aborted the land with NO retest and a null
        # `flaky_retry` (the measured row, events.jsonl#ts=2026-09-11T21:20:23Z). This gives it the
        # SAME treatment a pool flake gets — up to two isolated attempts after the quiet point —
        # through the UNCHANGED `_run_one(..., _isolated=True)` path. It consults NOTHING of the pool
        # bound: `_verify_retry_max_files` is read only inside the `if failures:` pool block above,
        # whose input is `_pool_files`, and no lane file is ever added to it.
        if _serial_files and failures:
            # CANDIDATE SET — «this lane file is why the leg is red», off the run's own parser.
            _lane_failing = set(_verify_failing_test_names(list(failures)))
            _lane_bad = [tf for tf in _serial_files if tf.name in _lane_failing]
            # RETESTED = the ones a second isolated run can honestly RE-DECIDE: a real `failed`
            # verdict. The rest still get a ROW naming why they were NOT retested, because AC4 folds
            # «a lane-caused leg failure carries a null or absent retest record» — with
            # retest-or-nothing a lane TIMEOUT would leave `flaky_retry` null and read as this
            # mechanism's own failure. `timed-out` is declined by the EXISTING rule applied to the
            # lane (`_flaky_retry_plan` declines a timeout for the pool; SPEC-0071 makes a verify
            # timeout a distinct non-retriable class), `launch-error` is an environment fault a
            # second launch proves nothing about. `not-started` / `killed-fail-fast` never reach
            # `failures` at all, so they are not candidates — the resume below is what decides them.
            _lane_retry = [tf for tf in _lane_bad if _decided.get(tf.name) == "failed"]
            _lane_declined = [tf for tf in _lane_bad if tf not in _lane_retry]
            _lane_rows: list = []
            for _tf in _lane_declined:
                _lane_rows.append({"file": _tf.name, "lane": True,
                                   "retest": ("timeout-class" if _decided.get(_tf.name) == "timed-out"
                                              else "launch-error")})
            _lane_resumed = 0
            if _lane_retry:
                # THE QUIET POINT, reusing the T-12377 barrier already resolved above — no second env
                # read, no new marker, no barrier redesign (card scope NOT). ONE wait per leg, shared
                # by every row; `load1` read AFTER it so the figure describes the moment the retest
                # actually ran, and recorded ABSENT when unmeasurable (never a fabricated 0.0).
                _lqw: "dict | None" = None
                if _quiet is not None:
                    _lqw = _quiet_point_wait(_quiet["dir"], _quiet["leg"], _quiet["sibling"],
                                             _quiet["sibling_pid"], float(timeout))
                try:
                    _lload1 = os.getloadavg()[0]
                except (OSError, AttributeError):
                    _lload1 = None
                stop.clear()
                _lane_cleared: list = []
                for _i, _tf in enumerate(_lane_retry):
                    _row = {"file": _tf.name, "lane": True}
                    if _lload1 is not None:
                        _row["load1"] = round(_lload1, 2)
                    if _lqw is not None:
                        _row["quiet_wait_s"] = _lqw["quiet_wait_s"]
                        _row["quiet_wait"] = _lqw["quiet_wait"]
                    # TWO calls, not a loop with a count — byte-identical in shape to the pool's own
                    # attempts, so the bound cannot be re-rolled by a config value. `_isolated=True`
                    # is UNCHANGED: it bypasses the fail-fast entry skip, never calls
                    # `_trip_fail_fast()`, and `_record` writes NOTHING — so `_decided`,
                    # `file_durations`, the duration table and the outcomes sidecar keep exactly one
                    # row per file and `load_sensitive.tail[].outcome` still reports the tail's REAL
                    # verdict.
                    _iso: list = []
                    _run_one(_tf, _sink=_iso, _box=f"lane{_i}", _isolated=True)
                    _attempts = ["fail" if _iso else "pass"]
                    if _iso:
                        _iso2: list = []
                        _run_one(_tf, _sink=_iso2, _box=f"lane{_i}b", _isolated=True)
                        _attempts.append("fail" if _iso2 else "pass")
                    _row["isolated"] = _attempts[-1]
                    _row["isolated_attempts"] = _attempts
                    if _attempts[-1] == "pass":
                        _lane_cleared.append(_tf.name)
                    _lane_rows.append(_row)
                # CLEARANCE, on the pool's own terms — a file leaves `failures` only by PASSING
                # ALONE on this tree. A DECLINED file is never cleared, and a file that fails alone
                # twice leaves `failures` untouched, so the leg aborts exactly as today: the wider
                # record buys observability, never a weakened gate.
                if _lane_cleared:
                    _clear = set(_lane_cleared)
                    # Drop by NAME, through the run's own parser (`"test failed: <name>"`) — never a
                    # new match. A `bad` entry that names no test (a graph-build / conflict-marker
                    # line) yields no names and is therefore KEPT, which is the fail-closed direction.
                    _keep = [f for f in failures
                             if not (set(_verify_failing_test_names([f])) & _clear)]
                    del failures[:]
                    failures.extend(_keep)
                # RESUME parity — under `fail_fast=True` the first lane failure tripped the gate and
                # the REST of the tail was skipped `not-started`. Once nothing is failing any more,
                # re-run the still-undecided tail files SERIALLY (the lane analogue of the pool's
                # resume). Their verdicts are FINAL — no second re-plan.
                if not failures:
                    _lane_resume = [tf for tf in _serial_files if tf.name not in _decided]
                    if _lane_resume:
                        stop.clear()
                        for _tf in _lane_resume:
                            _run_one(_tf)
                        _lane_resumed = len(_lane_resume)
            if _lane_rows:
                # ONE record, never a second store: absent → it becomes the record; present (rows, or
                # a pool `{"skipped": ...}` that may carry no `rows` key at all) → the lane rows are
                # APPENDED. `remote_verify._flaky_retry_leg_stamped` stamps `leg` onto them unchanged
                # because it walks `rec["rows"]` regardless of `skipped`.
                if _flaky_retry_record is None:
                    _flaky_retry_record = {"rows": _lane_rows}
                else:
                    _flaky_retry_record.setdefault("rows", []).extend(_lane_rows)
                if _lane_resumed:
                    _flaky_retry_record["lane_resumed"] = _lane_resumed
    finally:
        hb_stop.set()
        if hb_thread is not None:
            hb_thread.join(timeout=2)
        # T-10716: reclaim any worktree a sandboxed test registered against `cwd` BEFORE the directory
        # goes away — once the dir is deleted a LOCKED registration is unreachable to `worktree prune`.
        _reclaim_sandbox_worktrees(cwd, under=_sandbox_root)
        # T-11206 / X-0950 — reap the PROCESSES still resident in this run's own sandbox, and REPORT
        # any that will not die. BEFORE the rmtree, deliberately: residency is read off each process's
        # own cwd/argv, and once the tree is gone those paths no longer resolve — deleting first would
        # destroy the only evidence tying a survivor to the run that made it (which is exactly how the
        # measured 19-20h leakers became untraceable). Report-only by contract: it never touches the
        # verdict, so a leak can never turn a green run red.
        # The reaper is INJECTABLE (default = the real one) purely so AC1's differential can express
        # "the reaping step removed" as a no-op at this seam — the same idiom `_terminate_process_group`
        # and `monotonic` already use in this signature. A differential anchored to a moving git ref
        # would invert the moment it landed (SPEC-0046 red-flag (e)); a seam does not.
        _residents = (_reap_sandbox_residents or _reap_own_sandbox_residents)(_sandbox_root)
        if _residents["survivors"] and _emit_sandbox_survivor_deviation is not None:
            # AC2 — a survivor teardown CANNOT reap is REPORTED, never silent. Two surfaces: a durable
            # journal deviation (cross-session, greppable by fingerprint) and a stderr line (the human
            # watching the land sees it now, not in a week's audit).
            try:
                _emit_sandbox_survivor_deviation(_residents["survivors"], str(_sandbox_root), journal_path)
            except Exception:
                pass          # the report must never mask the run it is reporting on.
            print(f"yitc-v2: verify sandbox teardown: {len(_residents['survivors'])} process(es) SURVIVED "
                  f"a SIGKILL and still reside in {_sandbox_root} — "
                  + ", ".join(f"pid {s['pid']} (pgid {s['pgid']}, age {s['age'] / 3600:.1f}h)"
                              for s in _residents["survivors"])
                  + " — these are leaking CPU on a shared host; a durable deviation_captured was emitted "
                    "(fingerprint=verify-sandbox-survivor-unreaped).", file=sys.stderr, flush=True)
        shutil.rmtree(_sandbox_root, ignore_errors=True)   # T-10073: reclaim the per-run sandbox tree
    # T-11316: hand the RAW (name, wall_ms, outcome) measurement to a caller that asked for it
    # (`verify-durations --rebuild`). Additive, opt-in and INDEPENDENT of `metrics_out` — deliberately
    # OUTSIDE that block, so the rebuild never has to request a metrics payload it does not want in
    # order to see the measurement. `durations_out is None` — every production caller — is
    # byte-identical to the pre-T-11316 behaviour. This REUSES the one measurement the runner already
    # takes rather than standing up a second metrics path.
    if durations_out is not None:
        durations_out.extend(file_durations)

    # T-12190 (SPEC-0203 rule 4) — the COMPLETE per-file outcome list, to disk. Written on EVERY run
    # (a land leg, a `task test --run`, a `verify-durations --rebuild`), because the run that most
    # needs to name its failures is the one nobody thought to ask in advance — that was the T-12183
    # loss. The journal gets the LOCATOR only, so `land_completed`'s row size is unchanged. The
    # discovered set is `test_files` (what this run enumerated), so a fail-fast tail is exported as
    # `not-started` rather than silently missing. Failure-inert: the writer returns {} rather than
    # raising, and an absent export simply attaches no key.
    # The writer arrives on the module's own injection seam (defaulted to the module global), so a
    # test can substitute it exactly as it can `_per_file_duration_record` — the plan named this seam
    # and the ship now carries it (audit-post finding 2).
    _export = _per_file_outcomes_export or globals()["_per_file_outcomes_export"]
    _outcomes_locator = _export(file_durations, [tf.name for tf in test_files], cwd,
                                path=outcomes_out)

    if metrics_out is not None:
        # T-10071 (SPEC-0132 Rule 2): populate the per-run verify-metrics. fail_class is derived from
        # the same verdict the caller acts on — a timeout marker in any failure is the distinct
        # non-retriable class (SPEC-0071), else "failed" if any test failed, else "ok".
        _fail_class = ("timeout" if any(_VERIFY_TIMEOUT_MARKER in f for f in failures)
                       else "failed" if failures else "ok")
        # T-11316 — WHAT SCHEDULE ACTUALLY RAN, recorded by the run itself. Without this the
        # dispatch order is unobservable after the fact: `duration_series` is published in NAME
        # order by design (it is the alphabetical BASELINE an offline simulation reconstructs), so
        # a reader could only RE-DERIVE the schedule by re-sorting against the table — which proves
        # nothing about what the runner did. `head` is the evidence: the first files actually handed
        # to the pool. On a name-ordered tree it is the alphabetically-first files; here it is the
        # heaviest. Additive single key on the existing payload (no new event, no second metrics
        # path); its readers were grepped for whole-dict equality before adding it.
        metrics_out["dispatch"] = {
            "order": "duration-desc" if _dur_table else "name",
            "table_files": len(_dur_table),
            "unrecorded": sum(1 for f in test_files if f.name not in _dur_table),
            "head": [f.name for f in test_files[:3]]}
        metrics_out.update({"worker_count": workers, "test_file_count": len(test_files),
                            "verify_wall_ms": int((time.monotonic() - _run_start) * 1000),
                            "queue_wait_ms": int(max_queue_wait[0] * 1000),
                            "fail_class": _fail_class})
        # T-11703 — the per-file wall bound that was actually in force, plus the rung that supplied
        # it (resolved at the top of this function). Two additive keys on the SAME payload the
        # dispatch / per_file_durations / selection_* records already ride (no new event type, no
        # second metrics path, no new store — CHARTER §P1 F1/F2). The source key is ABSENT rather
        # than fabricated when the ladder did not run (an explicit caller-supplied `timeout`, or an
        # injected resolver stub that could not report) — never a guessed "default".
        metrics_out["verify_test_timeout_s"] = float(timeout)
        if _timeout_source is not None:
            metrics_out["verify_test_timeout_source"] = _timeout_source
        # T-11124 — the BOUNDED per-file duration record, so test-duration growth becomes a SERIES in
        # the journal instead of a one-off measurement campaign. It EXTENDS this existing payload: no
        # new event type, no second metrics path, no new store (CHARTER §P1 F1/F2 — the analog exists,
        # and this is a bounded VIEW over data the runner already held and discarded). Attached under
        # ONE key so the addition is a single additive field on land_completed.verify_metrics
        # (P5-safe, registered in SPEC-0025 §land_completed). ABSENT — not empty — when no file
        # started, so a run that measured nothing never reports a fabricated zero.
        _pfd = _per_file_duration_record(file_durations)
        if _pfd:
            metrics_out["per_file_durations"] = _pfd
        # T-12357 — WHAT THE ISOLATED RETRY DID, on the SAME additive-single-key shape as
        # `per_file_durations` above: one more field on the `verify_metrics` payload `land` already
        # emits (SPEC-0132 rule 2 / SPEC-0025), no new event type and no second store. ABSENT —
        # never `{}` and never `[]` — when no retry was reached, so a green run never reports a
        # retry it did not do (T-0358). The two shapes it takes are both readable without knowing
        # which: `{"rows": [...], "resumed": N}` when the leg re-ran and resumed, and
        # `{"skipped": <reason>, ...}` when the plan declined.
        if _flaky_retry_record is not None:
            metrics_out["flaky_retry"] = _flaky_retry_record
        # T-12447 — THE LAST OUTPUT OF EVERY FILE THIS RUN STILL FAILS ON, on the same additive-single-key
        # shape: keyed by the names the RETURNED `failures` carry, so a file its isolated retry cleared
        # records nothing and a green run has NO key (T-0358). Before it, the only failure text a
        # routed land kept was the leg's first line per file — «(no assertion captured)» and nothing
        # else (the 2026-09-12T15:07:33Z row). A failure whose output was empty records `[]`.
        if failures:
            _tail_names = sorted(set((_verify_failing_test_names
                                      or globals()["_verify_failing_test_names"])(list(failures))))
            metrics_out["failed_output_tail"] = _tail_rv._bounded_output_tail(
                [(n, _fail_tails.get(n, [])) for n in _tail_names])
        # T-12358 — WHAT THE SERIALIZED TAIL DID, on the same additive-single-key shape: one more
        # field on the `verify_metrics` payload `land` already emits, no new event type, no second
        # store. ABSENT — never `{}` — when the carrier lists nothing, so a repo without a set reports
        # nothing it did not do (T-0358). `outcome` is the file's REAL verdict from the `_decided`
        # ledger, or `not-started` when a tripped fail-fast gate skipped it — the same closed
        # vocabulary the outcomes sidecar uses. `unresolved` (present only when non-empty) names
        # listed basenames this run did not discover — a stale line, reported rather than silent.
        if _ls_set:
            metrics_out["load_sensitive"] = {
                "tail": [{"file": tf.name, "outcome": _decided.get(tf.name, "not-started")}
                         for tf in _serial_files]}
            _ls_unresolved = sorted(n for n in _ls_set if n not in {tf.name for tf in test_files})
            if _ls_unresolved:
                metrics_out["load_sensitive"]["unresolved"] = _ls_unresolved
        # T-12190 — the sidecar's LOCATOR (path + sha256 + count), never the list itself: the same
        # additive-single-key shape as `per_file_durations` above, and the reason the row stays
        # bounded while the full list becomes readable. ABSENT — not empty — when nothing was
        # exported, so a run that wrote no sidecar never reports one it does not have.
        if _outcomes_locator:
            metrics_out["per_file_outcomes"] = _outcomes_locator
        # SPEC-0181 (T-10080) — the SHADOW selection record. Computed HERE, AFTER the executor has
        # already run, from the SAME `test_files` enumeration that executed: the ordering makes it
        # STRUCTURALLY impossible for the decision to influence what ran, which is the shadow
        # boundary this card must not cross. `test_files` is neither filtered nor reordered by it.
        # T-11462 — REUSE the decision made BEFORE the run when this caller was governed; only a
        # NON-selected caller (`select=False`) still computes it here, after the fact, exactly as the
        # shadow era did. Recomputing a governed run's decision against its own narrowed `test_files`
        # would grade the selector on its own output and would report a vacuous zero omission.
        if _sel_run is None:
            _sel_run, _sel_omit, _sel_reason = _shadow_select(
                selection_diff_paths, test_files, _VERIFY_IMPLEMENTATION_GLOBS,
                diff_error=selection_diff_error,
                reachability_freed=selection_reachability_freed)
        metrics_out.update({"selection_rule_version": _SELECTION_RULE_VERSION,
                            "selection_would_select": len(_sel_run),
                            "selection_would_omit": len(_sel_omit),
                            "selection_full_suite_reason": _sel_reason,
                            # AC1 — WHAT WAS FOUND vs WHAT RAN, on the SAME row. `test_file_count`
                            # above keeps meaning WHAT RAN (its standing meaning for every existing
                            # reader), so a governed land reads
                            # `test_file_count < selection_discovered_count` and the omission is
                            # recorded beside it as `selection_would_omit`.
                            "selection_discovered_count": _selection_discovered,
                            "selection_governed": bool(_sel_governed)})
        if _sel_govern_reason:
            # WHY a land ran everything, whenever it did — never fabricated when it governed.
            metrics_out["selection_govern_reason"] = _sel_govern_reason
        # T-12372 (SPEC-0181) — HOW MANY OF THE DECLARED CONSISTENCY TRIPWIRES this run unioned in,
        # on the SAME additive-single-key shape every other `selection_*` field here rides. ABSENT —
        # never 0 and never fabricated (T-0358) — on an ungoverned run, which ran everything and
        # unioned nothing in; that absence IS how a `--full` run reads (AC4). The count and
        # `selection_would_select` MAY OVERLAP: a marker-bearing file the diff also affects is in
        # both, so the two numbers describe two sets and are not addends.
        if _sel_always:
            metrics_out["selection_always_count"] = len(_sel_always)
            metrics_out["selection_always_tests"] = list(_sel_always)
        if _sel_always_refused:
            # A DECLARATION THAT GRANTED NOTHING. Reported rather than dropped: a marker that silently
            # selects no test is the authoring defect this leg exists to make loud (SPEC-0165).
            metrics_out["selection_always_refused"] = dict(_sel_always_refused)
        if _sel_tripwire:
            # AC2 — the tripwire's OWN signature on the record: it fired, and on which tests. ABSENT
            # (not zero) when it did not fire, so the key never reports a defect nothing found.
            metrics_out["selection_tripwire_recovered"] = len(_sel_tripwire)
            metrics_out["selection_tripwire_tests"] = list(_sel_tripwire)
        # T-11791 — WHICH TESTS THIS LAND ACTUALLY RAN, when it ran only some of them. Without this
        # key a narrowed land row can state HOW MANY files ran but never WHICH, so the known-broken
        # fold (`debt.open_known_broken`) could only clear a record by asking "did you run
        # EVERYTHING" — and a SURGICAL repair of the broken test, being narrow by construction, could
        # never answer yes. Measured 2026-08-28: T-11784 landed the repair GREEN having run 150 of
        # 1103 files, the record stayed open ~35 minutes and a docs-only batch was refused inside
        # that window, until an UNRELATED broad land happened along. The more precisely a repair was
        # scoped, the less able it was to clear the record it repaired.
        #
        # `f.name` IS THE PAIR'S OWN IDENTITY, not a second derivation. A failure is named
        # `f"test failed: {tf.name}"` above, the `only` re-selector matches `tf.name`, and
        # `_land_red_isolation_entries` takes the attribution pair's file half straight off that
        # line — which is why `debt._known_broken_blob_exists` is called with an explicitly PREFIXED
        # `tests/<file>`. A repo-relative value here would be the thing that fails to match.
        #
        # PRESENT ONLY ON A NARROWED RUN, and that bound is the design, not a tuning knob. SPEC-0025
        # EXPLICITLY REJECTS recording all ~800 files per land (~45KB/land, ~50% growth of the whole
        # log) — and a FULL-enumeration land needs no list, because the counts already answer the
        # question for it (route (b)). Measured on this repo's journal: the 246 narrowed rows of 505
        # ran 79/138/732 files (min/median/max) at ~36 chars a name, so the key costs ~5.4KB median
        # and ~1.0% of the log — the same order as `per_file_durations`. ABSENT, never an empty list
        # and never fabricated (T-0358), on a full-suite or unmeasurable run.
        #
        # COMPUTED AFTER THE EXECUTOR RAN, from the SAME `test_files` that executed — the ordering
        # that makes it structurally impossible for the record to influence what ran, the same shadow
        # boundary the selection block above holds. Sorted, so the value is a set-membership record
        # and not an accidental second copy of the dispatch order (`dispatch.head` owns that).
        if (isinstance(_selection_discovered, int) and not isinstance(_selection_discovered, bool)
                and 0 < len(test_files) < _selection_discovered):
            metrics_out["selection_ran_tests"] = sorted(f.name for f in test_files)
        # T-11460 — WHICH glob refused. `selection_full_suite_reason` collapses every
        # verifier-surface refusal into the single token `verify-implementation-touch`, and that
        # refusal is 56% of all recorded decisions (415 of 740 in this repo's journal at filing) —
        # so the largest class in the record names no cause, and the two successor cards' claims
        # (narrow `tests/**`; a reachability filter inside `bin/`) could only be RECONSTRUCTED, with
        # two reconstructions of the same quantity disagreeing 2.5x. The refusal predicate ALREADY
        # computes the match; this stops discarding it. Computed from the SAME inputs the refusal
        # was decided on, through the SAME carrier — never a second matching path that could drift.
        # REPORT-ONLY: nothing reads it, nothing gates on it, and SPEC-0181's shadow boundary is
        # untouched. ABSENT — not empty, never fabricated (T-0358) — on every other rung, so the key
        # accuses no glob on a decision no glob made (the fail-safe direction for a SIGNAL rather
        # than a gate, lessons/a-signal-about-a-reader-fails-safe-the-opposite-way-to-a-gate).
        # T-12155 — WHICH PATH refused, recorded BESIDE the glob and CO-DERIVED FROM THE SAME CALL.
        # `bin/**` is one atom over ~37 modules, so for the largest refusal class the glob key names a
        # surface rather than a cause: measured over 2026-08-27..09-12, 41% of all kernel lands were
        # refused here with `selection_full_suite_globs == ['bin/**']` and the record could not say
        # which module did it — the per-path attribution had to be RECONSTRUCTED from git history, an
        # approximation whose imprecision is exactly what this key removes. ONE call to
        # `_verify_implementation_touch_pairs` yields both keys, so "globs non-empty => paths
        # non-empty" is STRUCTURAL rather than asserted, and the two can never name different diffs.
        # REPORT-ONLY on the same terms as the glob key: nothing reads it, nothing gates on it,
        # SPEC-0181's shadow boundary is untouched, and it is ABSENT — not empty, never fabricated
        # (T-0358) — on every other rung.
        if _sel_reason == _SKIP_EDGE_VERIFY_TOUCH:
            _sel_pairs = _verify_implementation_touch_pairs(
                selection_diff_paths or (),
                _VERIFY_IMPLEMENTATION_GLOBS=_VERIFY_IMPLEMENTATION_GLOBS,
                # T-11461 — the SAME enumeration `_shadow_select` judged the refusal on, so the
                # key names only globs that actually refused THIS diff.
                test_file_names=_selection_enumerated_relpaths(test_files))
            metrics_out["selection_full_suite_globs"] = sorted({g for _p, g in _sel_pairs})
            metrics_out["selection_full_suite_paths"] = sorted({_p for _p, _g in _sel_pairs})
        # T-11118: WHICH SIDE did a failing test fall on — the whole point of accumulating a window.
        # A DISAGREEMENT is by definition the selector omitting a test that FAILED, so a green run
        # can never contain one and only THIS branch can prove or refute the selector. Computed here
        # because this is the one place that holds both the shadow sets and this run's `failures`,
        # and computed as a VERDICT rather than by emitting the name lists — recording ~800 test
        # names on every land would be a payload, not a signal. Reuses `_verify_failing_test_names`,
        # the existing extractor, never a second parser. Absent when nothing failed (never
        # fabricated: "no failure" is not a side).
        _sel_failed = _verify_failing_test_names(failures)
        if _sel_failed:
            _omit_set = set(_sel_omit)
            _in_omit = [n for n in _sel_failed if n in _omit_set]
            metrics_out["selection_failing_side"] = (
                "omitted" if len(_in_omit) == len(_sel_failed)      # every failure was omitted
                else "mixed" if _in_omit                            # some omitted, some selected
                else "selected")                                    # the selector would have run them
            metrics_out["selection_disagreement"] = bool(_in_omit)  # SPEC-0181: a defect, not a rate
        try:   # best-effort children peak RSS (KB on Linux) — omitted, never fabricated, if unavailable
            import resource
            metrics_out["mem_peak_kb"] = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
        except Exception:
            pass
    return failures

def _sandbox_residency_candidates(cwd, argv) -> list:
    """T-11231 — the candidate path STRINGS a process offers as evidence of where it lives.

    PURE STRING PRODUCTION. It opens nothing, resolves nothing and decides nothing — every candidate
    it yields is still put to the unchanged `_path_at_or_under(must_exist=True)` predicate by the
    caller. Widening this list can therefore only ever offer the predicate more strings to REJECT; it
    cannot loosen a fence.

    WHY IT EXISTS — the measured defect (T-11231, re-verified live 2026-08-17). `_sandbox_run_residents`
    read cwd plus each argv ELEMENT, on the reasonable assumption that a process carrying a path carries
    it as an element of its own. nginx does not: it REWRITES its argv area into a status title, so
    `/proc/<pid>/cmdline` for a sandbox master is ONE element —

        `nginx: master process /usr/sbin/nginx -p <root>/box755/tmp/tmpX/sb -c <root>/.../nginx.conf`

    — which is not a path, and nginx does not chdir into the sandbox either (its cwd is whatever the
    run inherited, measured: a task worktree). BOTH residency channels therefore read nothing, teardown
    selected zero, and `rmtree` deleted the sandbox out from under a live master. Four such masters were
    alive on this host when this card was executed (ages 14h24m–18h26m, `ppid=1`, every one naming a
    sandbox root already gone from disk), and one of them, holding a task worktree as its cwd, is why
    `worktree adopt --task T-11226 --confirm-dead` refused a legitimate recovery.

    PRIOR ART, not a new idea: the sibling `_sandbox_prefix_arg` (T-10857) already reads exactly this
    shape for the host-wide sweep, and documents the same failure — "the shipped reaper reported 0
    orphan sandbox process(es) while 13 were alive". The teardown selection was simply never taught it.
    This helper is that lesson, applied on the containment axis instead of the `-p` axis.

    WHAT IT DOES. Yields the cwd, each argv element as-is, and — for any element containing whitespace —
    that element's whitespace-separated tokens. Splitting on whitespace is what turns the status-title
    blob back into the paths inside it. A path containing a space is not recovered by the split, which
    is the fail-closed direction (a candidate not offered is a process not selected) and is not a real
    population here: the roots are `mkdtemp` names.

    NOT A WIDENED KILL DISCRIMINATOR (the T-11217 fence is untouched). Nothing here reads a process
    NAME, and nothing here decides a kill. A candidate still has to resolve to a REAL, EXISTING path
    component-contained at or under the caller's OWN `mkdtemp` sandbox root — a root belonging to
    exactly one run, asked only after that run has ended. The host-wide reaper's "never kill on a
    guess" rule, which spares a sandbox-resident process carrying no `-p` identity, is a different
    predicate in a different function and is not modified by this card."""
    out: list = []
    for x in [cwd, *(argv or [])]:
        if not x or not isinstance(x, str):
            continue
        out.append(x)
        if x.strip() != x or " " in x or "\t" in x:
            out.extend(t for t in x.split() if t)
    return out

def _sandbox_run_residents(sandbox_root, procs, *, self_pid: int, self_pgid: int, uid: int, _path_at_or_under=None, _proc_start_age_sec=None, _sandbox_residency_candidates=None) -> list:
    """T-11206 / X-0950 — the processes still resident in THIS verify run's OWN sandbox root.

    PURE SELECTION — it opens nothing, signals nothing, removes nothing (the `select_orphan_sandbox_procs`
    posture). Returns `[{pid, pgid, argv, cwd, age}]`.

    THE POSITIVE DISCRIMINATOR (`lessons/carving-an-exception-into-a-fail-closed-gate.md` §1). A process
    is selected ONLY by POSITIVELY resolving a path OF ITS OWN — its cwd, or one of its argv elements —
    to a REAL location AT OR UNDER this run's own `sandbox_root`. Never by process name, never by "not
    recognised". An argv element that merely READS like such a path but does not EXIST is not a path
    and selects nothing (`_path_at_or_under(must_exist=True)`) — otherwise a `-c` program body or a log
    line quoting a filename could nominate the process carrying it. An unreadable `/proc` entry
    resolves nothing either: the fail-closed direction is always reap-nothing.

    WHY CONTAINMENT AND NOT THE SHARED `_sandbox_resident_root` (a nesting bug the full-suite run
    caught, not reasoning). That helper answers a DIFFERENT question — "which sandbox root, of all of
    them, does this path sit under?" — and it answers it SHALLOWEST-FIRST by design, because its
    callers need the outermost root. Verify runs NEST (a test in land's suite runs a verify of its
    own), so an inner run's paths look like
    `/tmp/yitc-verify-sandbox-OUTER/box5/tmp/yitc-verify-sandbox-INNER/box1/...` and that helper
    returns OUTER. Comparing its answer to the inner root then matches NOTHING, and the reaper reaps
    silently nothing — green and blind, under exactly the nested shape land itself produces. The
    question here is narrower and must be asked directly: is this path under MY root? Containment also
    drops the glob entirely, so a `mkdtemp` suffix containing a glob metacharacter cannot change the
    answer.

    WHY BOTH cwd AND argv, and not whichever was easier
    (`lessons/a-synthetic-probe-must-reproduce-the-production-shape.md`). The measured leakers carry the
    sandbox path in BOTH — leader `python3 <root>/box263/tmp/tmpX/pre_burn.py` (argv), its burner
    `python3 -c "while …"` (argv carries no path at all; only cwd places it). Reading one channel would
    have missed half the population that was actually on the host.

    WHY THIS COHORT IS SAFE TO KILL WHERE THE HOST-WIDE SWEEP'S IS NOT. `cmd_worktree_sweep` Category C
    sees this same population and deliberately only REPORTS it (`select_orphan_sandbox_procs` →
    `residents`), because from outside nothing distinguishes a survivor of a FINISHED run from a
    legitimate child of a RUNNING one — so cwd-based killing there would put every child of a live
    verify one guard away from a kill. That fence is correct and is NOT touched by this function. Here
    the question does not arise: `sandbox_root` is a `mkdtemp` root belonging to exactly ONE run, and
    this selection is made only after that run has ENDED, so residency IS survival. No age fence is
    used, deliberately — an age fence would be a proxy for the very fact we already know.

    SELF-PRESERVATION: our own pid and our own process GROUP are excluded, so a reaper can never signal
    the run it is cleaning up after. A process of another uid is excluded too — `os.kill` would EPERM,
    so signalling it could only be noise or harm on this shared host."""
    root = Path(sandbox_root)
    out: list = []
    for p in procs or []:
        pid = p.get("pid")
        if not pid or pid == self_pid:
            continue
        if p.get("uid") != uid:
            continue
        paths = _sandbox_residency_candidates(p.get("cwd"), p.get("argv"))
        if not any(_path_at_or_under(x, root) for x in paths if x):
            continue
        try:
            pgid = os.getpgid(int(pid))
        except OSError:
            continue          # exited mid-scan, or unreadable → cannot prove it is ours → never signal.
        if pgid == self_pgid:
            continue          # our own group — the run's own machinery, never a target.
        out.append({"pid": int(pid), "pgid": int(pgid), "argv": p.get("argv") or [],
                    "cwd": p.get("cwd"), "age": _proc_start_age_sec(pid)})
    return out

def _scan_procs(*, pids=None) -> list:
    """T-10857 — a READ-ONLY snapshot of the live processes on this host: `[{pid, argv, cwd, uid}]`.

    BOUNDED BY `pids` WHEN THE CALLER CAN NAME ITS UNIVERSE (T-11867). With `pids=None` — the
    default, and what every host-wide caller passes by simply not passing anything — this walks the
    whole `/proc` tree exactly as it always has; `cmd_worktree_sweep` and the nightly host sweep
    genuinely need every process on the box and are unchanged by construction. With a set of pids it
    visits ONLY those, which is what the verify-teardown reaper passes (see `_own_cgroup_pids`, whose
    None means "no bound" and lands back on the full walk). A pid in the bound that has since exited
    is skipped by the SAME per-pid race path below as any other vanishing process — narrowing the
    input introduces no new failure mode, and the selection logic downstream never sees the
    difference.

    argv is NUL-SPLIT into ELEMENTS, never a flattened line — the blessed idiom of `_land_proc_alive` /
    `_worker_child_proc_kind` (bin/lib/journal.py): `/proc/<pid>/cmdline` is NUL-separated, so a
    space-grep never matches, and a flattened substring scan false-positives on a dispatched worker whose
    whole preamble is ONE argv element (E-0035 / T-10053). Per-pid read races are SKIPPED (a pid that
    vanishes mid-scan is not a global failure); a missing `/proc` yields [] — on such a host the
    process-reap universe is simply empty, which is the fail-closed direction (reap nothing)."""
    out: list = []
    try:
        proc = Path("/proc")
        if not proc.is_dir():
            return out
        entries = (proc.iterdir() if pids is None
                   else (proc / str(int(q)) for q in sorted(pids)))
        for entry in entries:
            if not entry.name.isdigit():
                continue
            try:
                raw = (entry / "cmdline").read_bytes()
                st = entry.stat()
            except OSError:
                continue   # per-pid race: the process exited mid-scan — skip, NOT a global failure.
            argv = [a.decode("utf-8", "surrogateescape") for a in raw.split(b"\x00") if a]
            if not argv:
                continue   # a kernel thread — no argv, so it can never carry a prefix argument.
            try:
                cwd = os.readlink(str(entry / "cwd"))
            except OSError:
                cwd = None
            out.append({"pid": int(entry.name), "argv": argv, "cwd": cwd, "uid": st.st_uid})
    except OSError:
        return out
    return out

_SELECTION_ALWAYS_MARKER = "# yitc: selection: always"
# T-12372 (SPEC-0181) — the ONE spelling of the always-run declaration, so the reader below and the
# files that adopt it cannot drift. Spelled in the same `# yitc: ` namespace as the sibling
# `rebaseline_currency._PINNED_LEG_CENSUS_MARKER` (T-12307) and matched the same way: as a PREFIX of a
# STRIPPED line anywhere in the file, so a file can put the declaration beside the sentence explaining
# why it is a consistency tripwire.
#
# WHY IT IS A SECOND MARKER AND NOT THAT ONE (the fork, decided at Analysis). The census marker's
# consumer is the PINNED last-green leg, where it EXCLUDES a file; this marker's consumer is the
# CANDIDATE selection, where it INCLUDES one. Adopting the census spelling on the twelve files that do
# not already carry it would ALSO un-pin them from the SPEC-0077 leg — a gate weakening made silently
# by a declaration whose stated purpose is the other leg. Two questions, two legs, two declarations;
# conflating them is the unsafe move, not the duplication.

_SELECTION_ALWAYS_CACHE: dict = {}
# The per-checkout memo for `_selection_always_set`, the same shape as `_SELECTION_DERIVED_CACHE`
# above — the neighbouring mechanism at this seam, reused rather than re-invented.


def _selection_always_marker_verdict(src, rel=None):
    """T-12372 (SPEC-0181) — does `src` DECLARE itself always-run, and does it QUALIFY?

    Returns `(True, None)` for a qualifying declaration, `(False, "<named reason>")` for a declaration
    that does not qualify, and `(False, None)` for a source that does not declare at all. PURE: text
    (and an optional repo-relative path) in, a verdict out; no disk, no clock.

    READ FROM RAW SOURCE, deliberately. The marker is a COMMENT, and `_selection_strip_prose` blanks
    comments before the family scan — so a stripped-source test would never see it. The sibling
    `_SELECTION_CWD` corpus test in `_selection_analyse` reads raw source for exactly this reason.

    THE TWO REFUSALS, and why a refusal rather than silence. A declaration that grants nothing is an
    authoring defect, and a silent one is the class SPEC-0165 exists to make loud:
      - OUTSIDE A `tests/` DIRECTORY — the always-run set is unioned into a selection over discovered
        TEST files, so a marker on `bin/lib/foo.py` can never be honoured. Judged on `rel`, the file's
        repo-relative path; a caller that offers NO path cannot be judged on location and is not
        (the fail-safe direction is to keep judging the other condition, never to invent a location).
      - NOT A TEST FILE — neither a `def test_` node nor an `if __name__ == "__main__"` script main.
        Both shapes run in this suite (`task test --run` executes script-style mains, which a bare
        `pytest` misses — T-10097), so both qualify; a helper module carrying the marker does not.
    """
    if not any(ln.strip().startswith(_SELECTION_ALWAYS_MARKER) for ln in src.splitlines()):
        return (False, None)
    if rel is not None and "tests" not in Path(str(rel)).parent.parts:
        return (False, (f"declares `{_SELECTION_ALWAYS_MARKER}` but does not live under a tests/ "
                        f"directory ({rel}) — the always-run set is unioned into a selection over "
                        f"discovered test files, so the declaration can never be honoured here"))
    if not (re.search(r'^\s*def test_', src, re.M) or re.search(r'^if __name__\s*==', src, re.M)):
        return (False, (f"declares `{_SELECTION_ALWAYS_MARKER}` but is not a test file — it carries "
                        f"neither a `def test_` node nor an `if __name__ == \"__main__\"` script "
                        f"main, so the suite never runs it and the declaration grants nothing"))
    return (True, None)


def _selection_analyse(src, strict=False, rel=None, *, _SELECTION_ANCHOR_ONLY=None, _SELECTION_CWD=None, _SELECTION_PATHEXPR=None, _SELECTION_READ=None, _selection_file_anchors=None, _selection_join_parts=None, _selection_strip_prose=None):
    """One test/helper source → (family first-segments it reads, drives-the-whole-corpus,
    undecidable). PURE — takes text, returns sets/bools, touches no disk.

    CODE ONLY (T-11475): comments and docstrings are blanked by `_selection_strip_prose` before the
    scan. Reads live in code; scanning prose produced false undecidables, one of which cost ~25% of
    suite wall time. See that helper for the measurement and the fail-safe.

    THE THREE OUTCOMES ARE NOT TWO. A file that parses cleanly and shows no live-root read is
    DECIDED hermetic — it reads nothing at the real root, so it is selected only by its own name.
    A file that reads AT the live root but from which NO family path literal resolves (a computed
    or variable path) is UNDECIDABLE: we can see it reading the corpus and cannot see what. Only the
    second joins the always-run set. Collapsing the two — treating every hermetic test as
    undecidable — measured 44% of the suite into always-run and would make the shadow metric
    meaningless.

    THE FIGURE THIS DOCSTRING STATES IS THE WHOLE ALWAYS-RUN SET, NOT HALF OF IT (T-11475). Until
    T-11475 this text claimed "40 of 895 files (4.5%)", which counted only the DIRECTLY classified
    class and ignored the helper propagation `_selection_derive_readers` applies a few lines below —
    understating the real outcome ~7x (the true figure then was 299 of 965, 31%). The line below is
    machine-checked against a real derivation over the live tests tree by
    tests/test_t11475_hermetic_decidability.py, so the two can never drift apart again; the check
    carries a stated tolerance because the tree grows between lands.

    ALWAYS-RUN SHARE (of the tests tree, INCLUDING helper propagation): 11.1%

    THAT SHARE ROSE FROM 6.4% AT T-11848, AND THE RISE IS THE FIX WORKING. Resolving each file's OWN
    `Path(__file__)`-derived anchors (`_selection_file_anchors`) lets the scan SEE reads it was blind
    to; a read whose target does not fold is UNDECIDABLE, which is the always-run class. 73 -> 121 of
    1194 files. The same pass moved the derived `bin` family 534 -> 1090, which is where the value is:
    those are reads now RESOLVED to a family rather than escalated to always-run.

    `strict` gates the family scan on a read verb appearing on the SAME line; it is used for
    tests/ HELPER modules, whose path literals are far likelier to be incidental."""
    code = _selection_strip_prose(src)      # the LINE scan reads code only (T-11475)
    # T-11848 — this file's OWN anchors, derived from `Path(__file__)` rather than recognised by NAME.
    # `rel=None` (a caller with no repo-relative path to offer) leaves `derived` empty and every scan
    # below byte-identical to the pre-T-11848 behaviour.
    derived = _selection_file_anchors(src, rel) if rel else {}
    derived_pathexpr = derived_anchor_only = None
    if derived:
        names = "|".join(sorted(re.escape(n) for n in derived))
        steps = r'((?:\s*\.\s*parent\b|\s*\.\s*parents\[\d+\])*)'
        derived_pathexpr = re.compile(
            rf'\b({names})\b{steps}\s*(?:/\s*[\'"]([^\'"]+)[\'"]'
            rf'|\.\s*r?glob\(\s*[\'"]([^\'"]+)[\'"])')
        derived_anchor_only = re.compile(rf'\b({names})\b')
    fams, undecidable = set(), False
    for line in code.splitlines():
        hits = list(_SELECTION_PATHEXPR.finditer(line))
        for m in hits:
            if strict and not re.search(_SELECTION_READ, line):
                continue
            fams.add((m.group(1) or m.group(2)).split("/")[0])
        derived_hits = list(derived_pathexpr.finditer(line)) if derived_pathexpr else []
        for m in derived_hits:
            if strict and not re.search(_SELECTION_READ, line):
                continue
            base = list(derived[m.group(1)])
            for step in re.findall(r'parents\[(\d+)\]|parent\b', m.group(2) or ""):
                climb = int(step) + 1 if step else 1
                base = base[:-climb] if 0 < climb <= len(base) else None
                if base is None:
                    break
            resolved = _selection_join_parts(base, m.group(3) or m.group(4))
            if resolved:
                fams.add(resolved[0])
            else:
                # The anchor is real and the read is real; only the TARGET did not fold. That is the
                # undecidable class, not the hermetic one — the fail-safe direction (T-11848).
                undecidable = True
        if (not hits and not derived_hits and re.search(_SELECTION_READ, line)
                and (_SELECTION_ANCHOR_ONLY.search(line)
                     or (derived_anchor_only is not None and derived_anchor_only.search(line)))):
            undecidable = True          # reads at the real root, target not statically resolvable
    is_corpus = bool(_SELECTION_CWD.search(src))
    if not is_corpus and derived:
        # `cwd=`/`chdir(` on an anchor that resolves to the checkout ROOT reads the WHOLE corpus, the
        # same fact `_SELECTION_CWD` establishes for a NAMED anchor. Raw source, matching that sibling
        # (T-11475 kept the corpus-wide test off the prose strip deliberately).
        for name, prefix in derived.items():
            if prefix == [] and re.search(rf'(?:cwd\s*=|chdir\()\s*(?:str\(\s*)?{re.escape(name)}\b', src):
                is_corpus = True
                break
    # T-11848 CONSIDERED AND REFUSED ON MEASUREMENT: dropping the `not fams` conjunct. A file that
    # resolves ONE family AND also performs an unresolvable live-root read is recorded as DECIDED, so
    # the second read is discarded (test_audit_consult.py resolves `plans` inline while its
    # `bin/lib/audit.py` reads go through a module-level tuple). Keeping that signal would widen
    # coverage — the safe direction — but MEASURED over the live tree it takes the always-run set from
    # 121 to 421 of 1194 (35%), which is the neighbourhood of the 44% this docstring already records as
    # "would make the shadow metric meaningless". The derived-anchor fix above reaches the same readers
    # by RESOLVING them instead, at 121, so the blunt instrument buys nothing the precise one has not
    # already bought. Left as-is deliberately; a future card that finds a real miss here should resolve
    # the read, not collapse the class.
    # T-11883 (SPEC-0181) — AN ANCHOR THAT ALREADY FOLDS TO A CONCRETE IN-CHECKOUT PATH *IS* A READ
    # OF THAT PATH'S FAMILY. Above, a derived anchor yields a family only when its NAME is later
    # re-used with `/ "literal"` or `.glob(...)`. But the dominant miss is the shape where the
    # anchor variable ITSELF already names the target —
    # `CANARY_PATH = Path(__file__).parent / "test_t0402_host_leak_canary.py"`, then
    # `shutil.copy2(CANARY_PATH, ...)`. The target family is statically known at ASSIGNMENT and was
    # simply never harvested, so the reader sat outside its family and every selection omitted it.
    # MEASURED over the live tree: 50 (changed-path, omitted-test) pairs across 10 families and 28
    # distinct anchor names — one idiom, not fifty registrations, which is why this is a rule in the
    # derivation rather than entries in `_SELECTION_FAMILY_EXTRA_READERS`
    # (`dev-utilities/selection-map-anchor-defects-T-11883.py` enumerates them).
    #
    # THE `> 1` IS WHAT MAKES IT A READ AND NOT A MENTION: the assignment line itself contains the
    # name, so a second occurrence in the PROSE-STRIPPED code is the file actually USING the path it
    # computed. An anchor assigned and never used is dead code and contributes nothing. This is
    # deliberately NOT the tripwire's raw-source mention test — that oracle is a different, coarser
    # question and stays untouched (its coarseness is its fail-safe, and narrowing it is out of
    # scope here).
    #
    # UNIONED AFTER THE UNDECIDABLE VERDICT, and the ORDER is load-bearing rather than stylistic.
    # `undecidable` is reported only `and not fams`, so folding these families in BEFORE that
    # verdict would let a newly-resolved family turn a previously ALWAYS-RUN file into a DECIDED
    # one — a NARROWING, the single direction this mechanism may never move (SPEC-0181 R1). Computed
    # first, the always-run set is untouched and the change is purely additive: a test gains
    # families, never loses one, so no diff can select fewer tests than it did before.
    # PURITY + FAIL-SAFE UNCHANGED: text in, sets out, no disk, no clock; no anchors / an
    # unparseable file / an unfoldable expression all yield zero extra families, i.e. exactly
    # today's behaviour.
    hermetic_undecidable = (undecidable and not fams and not is_corpus)
    for _name, _parts in (derived or {}).items():
        if _parts and len(re.findall(rf'\b{re.escape(_name)}\b', code)) > 1:
            fams.add(_parts[0])
    return fams, is_corpus, hermetic_undecidable

def _selection_tests_dir_relname(tests_dir):
    """T-11848 (SPEC-0181) — a tests directory → its path RELATIVE to the checkout root, or None.

    The derivation needs a file's repo-relative path to fold `Path(__file__)`: for `tests/test_x.py`
    the idiom `Path(__file__).parent.parent / "bin"` is the checkout's `bin/`, and only the ".../tests/"
    position makes that resolvable. The root is found by walking UP for a `.git` entry — the same fact
    every other caller in this file establishes by being handed a worktree — so a nested or renamed
    tests dir (`sub/tests`, a consumer's own layout) resolves correctly rather than being assumed flat.

    RETURNS None on any doubt (no `.git` found, an unreadable parent, a dir that will not relativise),
    and None turns the derivation OFF for the whole tree. That is the fail-safe direction: the classifier
    then behaves exactly as it did before this card, which is stricter, not looser."""
    try:
        d = Path(tests_dir).resolve()
        for cand in (d, *d.parents):
            if (cand / ".git").exists():
                rel = d.relative_to(cand).as_posix()
                return rel or None
    except (OSError, ValueError):
        return None
    return None

def _selection_coverage_map(tests_dir=None, *, _SELECTION_COVERAGE_MAP=None, _SELECTION_DERIVED_CACHE=None, _SELECTION_FAMILY_EXTRA_READERS=None, _SELECTION_LIVE_CORPUS_READERS=None, _selection_derive_readers=None):
    """The EFFECTIVE coverage map: the hand FLOOR unioned with the derivation above.

    FAIL-SAFE IN BOTH DIRECTIONS. The union with the floor means the derived map is a SUPERSET of
    the 170 audited registrations family by family — a derivation bug can widen coverage, never
    narrow it. And ANY failure to derive (no tests dir, an unreadable tree, a regex or OS error)
    returns the floor unchanged rather than an empty or partial map, so the worst case is exactly
    today's behaviour.

    CACHED per resolved tests dir: the scan costs ~0.95s over a 903-file tree, which is paid ONCE
    inside a minutes-long land verify. It is deliberately NOT computed at import — this module is
    imported by every `bin/yitc-v2` invocation, and a second of CLI startup for a shadow record
    that governs nothing would be a plain regression."""
    if tests_dir is None:
        return _SELECTION_COVERAGE_MAP
    key = str(Path(tests_dir).resolve())
    if key in _SELECTION_DERIVED_CACHE:
        return _SELECTION_DERIVED_CACHE[key]
    try:
        derived, always = _selection_derive_readers(key)
        out = []
        for src_glob, extra in _SELECTION_FAMILY_EXTRA_READERS:
            seg = src_glob.split("/")[0]
            targets = set(_SELECTION_LIVE_CORPUS_READERS) | set(extra) | always | derived.get(seg, set())
            out.append((src_glob, tuple(sorted(targets))))
        result = tuple(out)
    except Exception:
        result = _SELECTION_COVERAGE_MAP                       # fail-safe: the floor, never narrower
    _SELECTION_DERIVED_CACHE[key] = result
    return result

def _selection_derive_readers(tests_dir, *, _selection_analyse=None, _selection_tests_dir_relname=None):
    """Scan a tests/ tree → ({family-first-segment: {test file names}}, {always-run test names}).

    ALWAYS-RUN is the corpus-wide class plus the undecidable class (AC3's fail-safe: a test whose
    reads cannot be determined falls back to the always-selected set, NEVER to an empty one).
    A tests/ HELPER module (a non-`test_` `.py`) that itself reads propagates to every test that
    imports it — a read through an import is still a read."""
    tests_dir = Path(tests_dir)
    # T-11848 — the tests dir's own REPO-RELATIVE name, so each file can be handed its repo-relative
    # path and `_selection_analyse` can resolve that file's `Path(__file__)`-derived anchors. A dir we
    # cannot place relative to a checkout root yields None, which turns the whole derivation off and
    # leaves today's (narrower, more always-run) classification — the fail-safe direction.
    rel_dir = _selection_tests_dir_relname(tests_dir) if _selection_tests_dir_relname else None
    src = {}
    for f in sorted(tests_dir.glob("*.py")):
        try:
            src[f.name] = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            src[f.name] = None          # unreadable → undecidable, handled below
    fam, always = {}, set()
    for name, text in src.items():
        if text is None:
            always.add(name)
            continue
        fams, is_corpus, undecidable = _selection_analyse(
            text, rel=f"{rel_dir}/{name}" if rel_dir else None)
        for k in fams:
            fam.setdefault(k, set()).add(name)
        if is_corpus or undecidable:
            always.add(name)
    for helper in [n for n in src if not n.startswith("test_") and src[n] is not None]:
        fams, is_corpus, undecidable = _selection_analyse(
            src[helper], strict=True, rel=f"{rel_dir}/{helper}" if rel_dir else None)
        if not fams and not is_corpus and not undecidable:
            continue
        stem = re.escape(helper[:-3])
        for name, text in src.items():
            if not name.startswith("test_") or text is None:
                continue
            if re.search(rf'\b(?:import|from)\s+{stem}\b', text):
                for k in fams:
                    fam.setdefault(k, set()).add(name)
                if is_corpus or undecidable:
                    always.add(name)
    tests = {n for n in src if n.startswith("test_")}
    return ({k: (v | always) & tests for k, v in fam.items()}, always & tests)

_SELECTION_ALWAYS_WALK_PRUNE = frozenset({".git", ".yitc", "__pycache__", "node_modules",
                                          ".venv", "venv", ".mypy_cache", ".pytest_cache"})
# T-12372 — directory names the always-marker walk never descends into. `.yitc` is LOAD-BEARING and
# not cosmetic: verify sandbox worktrees live there (`_VERIFY_SANDBOX_PREFIX`), so an unpruned walk
# would read copies of the very tree it is scanning and report their markers as this checkout's.


def _selection_always_set(tests_dir, *, _selection_always_marker_verdict=None):
    """T-12372 (SPEC-0181) — the DECLARED always-run set for a tests tree, read off the files.

    Returns `({basenames under `tests_dir` that declare AND qualify}, {repo-relative path: reason})`.
    The second half is the refusals: declarations that grant nothing, reported rather than dropped.

    WHY THE WALK IS ROOT-WIDE AND NOT `tests_dir/*.py` (audit-pre pass 1, finding fp1:972e1534, AC2).
    Globbing the tests dir alone would make the out-of-`tests/` refusal UNREACHABLE IN PRODUCTION — a
    marker on `bin/lib/foo.py` would simply never be looked at, so no refusal could ever be produced
    and the leg would exist only as a direct call from a test. The walk therefore starts at the
    CHECKOUT ROOT, resolved by the same walk-up to `.git` every other caller in this file uses
    (`_selection_tests_dir_relname`), and every `.py` in the checkout is eligible to be REFUSED while
    only the ones under `tests_dir` are eligible to be MEMBERS.

    COST, MEASURED RATHER THAN ASSUMED: the full walk + read of all 1628 `.py` files in this checkout
    is 90 ms, paid ONCE per run. The cheap substring pre-filter runs before anything else, so the line
    scan in `_selection_analyse` is spent on the ~15 declaring files and not on the 1628. The result is
    memoised in `_SELECTION_ALWAYS_CACHE` keyed by `(resolved root, resolved tests dir)` — the same
    cache shape as `_SELECTION_DERIVED_CACHE`, which is the neighbouring mechanism at this seam.

    WHY IT CALLS `_selection_always_marker_verdict` AND NOT `_selection_analyse`. The marker rule has
    exactly ONE home — the pure verdict helper — and this is one of its readers, not a second copy of
    it. Routing through `_selection_analyse` would buy nothing and cost the whole DI residue: that
    function's regex collaborators (`_SELECTION_PATHEXPR`, `_SELECTION_READ`, `_SELECTION_ANCHOR_ONLY`,
    `_SELECTION_CWD`) are HOST-owned globals injected by the `bin/lib/worktree.py` residue, so a bare
    call raises `TypeError` — measured, not supposed. The marker question needs none of them. Keeping
    the reader free of that chain is also what lets `governed_selection`'s `globals()` default work for
    a caller outside the injection chain, exactly as its docstring promises.

    FAIL DIRECTION, and it differs BY SCOPE on purpose. An unreadable or undecodable FILE declares
    nothing and is skipped — the sibling census reader's direction, and the conservative one, since a
    file we cannot read cannot be shown to be a tripwire. A failure of the WHOLE derivation (no root,
    an unwalkable tree) RAISES, and `governed_selection` turns that into the FULL suite: a set we could
    not compute must never be read as "there are no tripwires", which is the direction that runs FEWER
    tests. Those are the only two, and neither one narrows.
    """
    _selection_always_marker_verdict = (_selection_always_marker_verdict
                                        or globals()["_selection_always_marker_verdict"])
    tdir = Path(tests_dir).resolve()
    root = None
    for cand in (tdir, *tdir.parents):
        # A REAL CHECKOUT, not merely a `.git` ENTRY. `.git` is a FILE in a linked worktree and a
        # directory containing `HEAD` in an ordinary clone — which is what git itself requires — so
        # this is the precise test, not a heuristic. The bare `.exists()` the sibling walk-ups use is
        # NOT precise enough HERE, because this reader then WALKS the root it finds: a stray empty
        # `/tmp/.git` (present on this very host, measured 2026-09-11) made every tmp-fixture tests
        # tree resolve its root to `/tmp` and sent the walk crawling other users' directories, where
        # it died on PermissionError. Every probe is wrapped, because a filesystem question asked
        # about a path we may not stat must not be able to fail the run that asked it.
        try:
            g = cand / ".git"
            if g.is_file() or (g / "HEAD").exists():
                root = cand
                break
        except OSError:
            continue
    if root is None:
        # NO CHECKOUT ROOT ABOVE THE TESTS DIR (a bare fixture tree, a consumer layout we cannot
        # place). This is NOT the undecidable case and must not be treated as one: the MEMBERS are
        # read from `tests_dir` either way, so they are still fully derivable — what a missing root
        # costs is only the ability to REFUSE a declaration sitting elsewhere in a checkout, which is
        # a REPORTING reach, not a safety one. So the walk narrows to the tests dir and the set is
        # computed normally. Raising here instead would fall the whole run to `always-set-error` and
        # so to the full suite — safe in the narrow sense, but it would silently switch OFF governed
        # selection for every caller whose tests tree is not inside a git checkout (measured: it
        # broke test_selection_rollback, test_t11462_selection_coverage_differential and
        # test_t12221_stage6_routes_on_resolved_breadth, all of which build exactly such a fixture).
        root = tdir
    rooted = root != tdir or (tdir / ".git").is_file() or (tdir / ".git" / "HEAD").exists()
    key = (str(root), str(tdir))
    if key in _SELECTION_ALWAYS_CACHE:
        return _SELECTION_ALWAYS_CACHE[key]
    names, refused = set(), {}
    def _is_nested_checkout(d):
        try:
            return (d / ".git").exists()
        except OSError:
            return True        # cannot stat it → do not descend (the cheap, conservative direction)

    for dirpath, dirnames, filenames in os.walk(root, onerror=lambda _e: None):
        dirnames[:] = sorted(d for d in dirnames
                             if d not in _SELECTION_ALWAYS_WALK_PRUNE
                             and not _is_nested_checkout(Path(dirpath) / d))
        for fn in sorted(filenames):
            if not fn.endswith(".py"):
                continue
            f = Path(dirpath) / fn
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue                   # fail-safe: unreadable declares nothing
            if _SELECTION_ALWAYS_MARKER not in text:
                continue                   # the cheap pre-filter — the whole reason this walk is cheap
            try:
                rel = f.relative_to(root).as_posix()
            except ValueError:
                rel = fn
            # LOCATION IS JUDGED ONLY WHEN WE HAVE A REAL CHECKOUT TO PLACE THE FILE IN. Without a
            # root, `rel` is a bare filename whose parent names nothing, and judging it would refuse
            # EVERY member as "not under tests/" — the fixture-tree case, and a refusal we have no
            # standing to make. `rel=None` is the verdict helper's own "location unknown" contract;
            # the display path below is unaffected, so a refusal for the OTHER reason still names the
            # file.
            _always, _refusal = _selection_always_marker_verdict(text, rel if rooted else None)
            if _always and f.parent == tdir:
                names.add(fn)
            elif _refusal is not None:
                refused[rel] = _refusal
            elif _always:
                # Qualifies, but lives under a DIFFERENT tests dir than the one being selected among
                # (a consumer layout, a nested suite). Not this run's member and not a defect either.
                continue
    result = (frozenset(names), dict(refused))
    _SELECTION_ALWAYS_CACHE[key] = result
    return result


def _selection_enumerated_relpaths(test_files) -> frozenset:
    """T-11461 — the runner's OWN enumeration, as paths RELATIVE to the tests dir: the set
    `_selection_leaf_test_freed` judges leafness against. Today the enumeration is a FLAT
    `test_dir.glob("test_*.py")` (`_run_verify_tests`), so every member is a bare filename; should the
    suite ever collect nested modules, the members become nested relative paths and the classifier
    follows with no edit, which is exactly why leafness is judged against this set rather than against
    a hard-coded shape.

    The root is the COMMON ancestor of every enumerated file, not the single shared parent: a mixed
    flat+nested enumeration (`tests/test_a.py` + `tests/sub/test_b.py`) must still yield
    `sub/test_b.py`, or the nested member would degrade to a bare name that the classifier — which
    compares the diff path's remainder AFTER `tests/` — could never match, and the freeing this
    function exists to enable would silently stop following the collector. The bare-name fallback is
    kept for the undeterminable cases (no common ancestor, a path that will not relativise); it is
    FAIL-CLOSED, since a bare name cannot match a nested remainder and the path simply keeps
    refusing."""
    files = [Path(str(t)) for t in (test_files or [])]
    if not files:
        return frozenset()
    try:
        root = Path(os.path.commonpath([str(f.parent) for f in files]))
    except (ValueError, TypeError):
        root = None
    out = set()
    for f in files:
        try:
            out.add(f.relative_to(root).as_posix() if root is not None else f.name)
        except ValueError:
            out.add(f.name)
    return frozenset(out)

def _selection_governs(journal_path, env=None, rule_version=None, threshold=None, *, _SELECTION_GOVERN_ENV=None, _SELECTION_MISS_THRESHOLD=None, _selection_recorded_misses=None):
    """SPEC-0181 / T-11462 — may THIS land act on the selection decision? Returns `(bool, reason)`.

    `reason` is None when governing, else the token naming why not — recorded on the run so a land
    that ran everything can always say WHY.

    THE FAIL-SAFE DIRECTION IS INVERTED FROM THE SHADOW ERA, and that inversion is the whole point
    (lessons/a-signal-about-a-reader-fails-safe-the-opposite-way-to-a-gate): while the decision was a
    report-only SIGNAL, an unanswerable state could be recorded generously. It is a GATE on what runs
    now, so every unanswerable state must RUN MORE. Hence: any exception → OFF, an unreadable journal
    → OFF, an unrecognised switch value → ON only for the explicit default, never for a guess."""
    if threshold is None:
        threshold = _SELECTION_MISS_THRESHOLD
    try:
        source = os.environ if env is None else env
        if str(source.get(_SELECTION_GOVERN_ENV, "1")).strip() == "0":
            return (False, "switch-off")           # AC3 — the same switch reverts selection to shadow
        misses = _selection_recorded_misses(journal_path, rule_version=rule_version)
        if misses is None:
            return (False, "governor-cannot-count")
        if misses >= threshold:
            return (False, f"miss-threshold:{misses}/{threshold}")
        return (True, None)
    except Exception as exc:                       # a governor that raises never omits
        return (False, f"governor-error:{type(exc).__name__}")

def _selection_leaf_test_freed(path: str, test_file_names, *, _LEAF_TEST_DIR=None) -> bool:
    """T-11461 (SPEC-0181) — True iff this changed path is a LEAF test file that cannot invalidate the
    test->code map for any OTHER test, and so must NOT force the full suite. The path classifier the
    `tests/**` arm of the verifier-surface refusal is narrowed by; PURE.

    MEASURED GROUNDS: of 751 commits touching `tests/` since 2026-08-01, 97.6% touched ONLY leaf test
    files, 0.7% shared test infrastructure, 0.1% were deletes or renames — so the blanket arm refused
    selection ~99 times in 100 on a change whose blast radius is exactly one test file.

    FREED — and ONLY this shape: a path under `tests/` whose remainder IS a member of
    `test_file_names`, the runner's OWN enumeration of the tests it is about to run
    (`_selection_enumerated_relpaths`). "Leaf test file" is DEFINED as "a test this suite actually
    collects", never as a filename pattern this predicate invents: a shape rule of its own would drift
    from the collector the moment either side changed, and it is the collector that decides what a
    test IS. (Under today's flat `test_*.py` glob that set is exactly the flat leaves; a nested module
    is not collected, so it is not freed — by the enumeration, not by a hard-coded flatness rule.)

    KEPT — everything else under `tests/`, because each can alter many tests at once (the external
    auditor raised the blanket form at HIGH severity and named this list):
      • shared test infrastructure — `conftest.py`, fixtures, helper modules, test data, `__init__.py`,
        anything affecting COLLECTION. None is itself a collected test, so none is freed;
      • DELETES and RENAMES. This falls out of the enumeration rather than needing diff status (which
        `--name-only` does not carry): a deleted path, and a rename's vanished OLD path, are NOT in
        `test_file_names` because they are not in the tree, so both keep refusing. A rename's NEW path
        is a fresh leaf and would be freed on its own — but the same diff always carries the old path
        too, so a rename still refuses as a whole.

    `test_file_names is None` means the caller has NO enumeration to judge against (the per-layer
    `subject_globs` mechanism, which reasons over opaque layers, not test files) — nothing is freed
    there and the blanket arm stands, unchanged."""
    if test_file_names is None:
        return False
    if not path.startswith(_LEAF_TEST_DIR):
        return False
    return path[len(_LEAF_TEST_DIR):] in test_file_names

def _selection_omission_tripwire(diff_paths, omitted_names, tests_dir, _read=None, *,
                                 inert_paths=None, matches_out=None):
    """SPEC-0181 / T-11462 AC2 — THE TRIPWIRE. An INDEPENDENT oracle over the omitted set.

    Returns the sorted names of omitted tests whose SOURCE literally NAMES one of this diff's changed
    paths. Those tests are added BACK to the executed set by the caller, so a defect reachable only
    through an omitted test is REACHED and, if it fails, the land fails through the ordinary verdict
    path. That is AC2 stated exactly: a land whose selector omits a test the full suite would have
    failed on itself FAILS — rather than a claim that some later audit would have noticed.

    WHY IT IS AN ORACLE AND NOT A TAUTOLOGY. The selector decides at FAMILY granularity:
    `_selection_derive_readers` collapses a changed path to its FIRST SEGMENT (`specs/SPEC-0181.yaml`
    → `specs`) and maps that segment to tests. This asks a DIFFERENT, FINER question of the SAME
    sources — does an omitted test name THIS EXACT PATH? Different granularity by a different method,
    so it CAN disagree with the selector, which is the entire reason to have it. When the map is right
    it returns nothing and costs nothing; it can only ever ADD tests, so it can never license an
    omission or weaken the ladder.

    Matching is deliberately narrow: the full relative path, or the basename ONLY when that basename
    is unique among the changed paths (a bare `README.md` matches too much to be evidence of
    anything). A false positive costs one extra test file; a false negative costs nothing governing
    did not already cost.

    `inert_paths` — THE NEEDLE SET EXCLUDES PROVEN-INERT CHANGED PATHS (T-11476). A path the SPEC-0064
    inert authority classifies INERT is one a change confined to it CANNOT alter the outcome of land's
    verification — the very question this oracle exists to ask. So a test recovered because its source
    mentions such a path is recovered on a needle that carries no signal, and the recovery contradicts
    a standing contract the SAME land relies on elsewhere (a wholly-inert diff is licensed to skip
    re-verification entirely, SPEC-0065). MEASURED, not assumed: on the first governed land
    (`events.jsonl#ts=2026-08-23T12:44:39Z`) all 377 recoveries rested on exactly two changed paths —
    `events.jsonl` (361) and `graph/index.json`, largely via its bare basename `index.json` (91) — both
    proven-inert, both written by LAND'S OWN BOOKKEEPING rather than by the change under test, so the
    firing did not depend on what the diff contained (an unrelated branch recorded the identical 377
    two hours later). Every one of those 377 was classified NOT-AFFECTED, and independently re-checked
    by a method neither predicate uses — resolving each mention line's RECEIVER back to a variable
    assigned from `Path(__file__)...parents[..]`, which finds a live-root read hiding under an anchor
    name the coverage map's fixed list does not know: ZERO of the 377 reads the live journal or the
    live graph index. Evidence: `dev-utilities/selection-tripwire-classification-T-11476.json`.

    THE EXCLUSION IS CONSUMED, NEVER RE-ENCODED. This function does not know what "inert" means and
    must not learn: SPEC-0064 §4 makes `_classify_inert_paths` the ONE authority, and the caller passes
    its verdict in. DEFAULT None == exclude nothing == today's behaviour byte-for-byte, so a caller
    that cannot establish the classification recovers MORE, never less — and the tightening can only
    skip a genuinely affected test if that allowlist is wrong, in which case a far larger hole (the
    whole-diff re-verify skip) is already open. NOT DONE HERE, deliberately: the raw-source scan is
    NOT narrowed to code, and the generic-basename guard is NOT tightened. Both are sound per named
    case, and both would only buy omission share — which SPEC-0181 forbids as a reason. The oracle's
    coarseness over OBSERVABLE paths is its fail-safe and stays exactly as it is.

    `matches_out` — T-12107, THE MATCHED PATH BESIDE THE RECOVERED TEST. Pass a dict and it is
    POPULATED `{recovered test name -> sorted changed paths whose needle hit that source}`; the
    RETURN VALUE is unchanged (`sorted(hits)`), so every existing caller is byte-identical. It is an
    out-parameter rather than a second return for exactly that reason. A full-path needle owns
    itself; a basename needle owns its ONE unique owner, which the uniqueness guard above already
    guarantees.

    THE UNREADABLE-SOURCE FAIL-SAFE CARRIES NO ENTRY, AND THAT IS THE CONTRACT. A name recovered by
    the `except Exception` branch below matched NO needle — it is recovered because the source could
    not be READ, so there is no path that pulled it back. It therefore gets NO key in `matches_out`:
    absent, never a fabricated path and never a fabricated empty list (T-0358, the discipline
    `selection_tripwire_tests` already follows on this surface). The absence is READABLE, not silent
    — a name present in the recovered set with no entry here IS the fail-safe recovery, and that is
    the distinction a reader makes off one row without a third key."""
    names = sorted({str(n) for n in (omitted_names or [])})
    if not names or not diff_paths:
        return []
    _inert = set()
    for raw in (inert_paths or ()):
        q = str(raw).strip()
        if q.startswith("./"):
            q = q[2:]
        if q:
            _inert.add(q)
    needles = set()
    bases = {}
    owner_of = {}                      # T-12107: needle -> the changed path(s) it stands for
    for raw in diff_paths:
        p = str(raw).strip()
        if p.startswith("./"):
            p = p[2:]
        if not p or p in _inert:
            # An excluded path contributes NO needle — and no basename either, so it can neither
            # re-enter through the basename widening below nor disqualify an OBSERVABLE path's
            # basename by colliding with it in the uniqueness test.
            continue
        needles.add(p)
        owner_of.setdefault(p, set()).add(p)      # a full-path needle owns itself
        bases.setdefault(os.path.basename(p), set()).add(p)
    for base, owners in bases.items():
        # A basename shared by two changed paths identifies neither, so it is not admitted as evidence.
        if len(owners) == 1 and len(base) > 4:
            needles.add(base)
            owner_of.setdefault(base, set()).update(owners)   # its ONE unique owner
    tests_dir = Path(tests_dir)
    reader = _read or (lambda pth: Path(pth).read_text(encoding="utf-8", errors="replace"))
    hits = []
    for name in names:
        try:
            src = reader(tests_dir / name)
        except Exception:
            hits.append(name)          # unreadable → cannot clear it → run it (the fail-safe direction)
            continue
        _matched = [needle for needle in needles if needle in src]
        if _matched:
            hits.append(name)
            if matches_out is not None:
                _paths = set()
                for needle in _matched:
                    _paths.update(owner_of.get(needle, ()))
                if _paths:
                    matches_out[name] = sorted(_paths)
    return sorted(hits)

def _selection_recorded_misses(journal_path, rule_version=None, _open=None, *, _SELECTION_RULE_VERSION=None):
    """SPEC-0181 / T-11462 — how many DISAGREEMENTS the journal records under `rule_version`.

    A disagreement is the selector having omitted a test that FAILED (`selection_disagreement: true`,
    written by `_run_verify_tests` since T-11118). Returns an int, or None when the count CANNOT be
    established — which the governor reads as "cannot decide" and answers by NOT governing. None and
    0 are deliberately different values: a journal we failed to read is not a clean record.

    NO `fail_class` FILTERING — THIS IS THE OWNER RULING, NOT AN OVERSIGHT (2026-08-23,
    `events.jsonl#ts=2026-08-23T10:06:51Z`). The artefact carve-out that excluded load-induced
    timeouts from the miss count is WITHDRAWN: every recorded disagreement counts as a real miss. The
    carve-out rested on the `fail_class` classifier, which is demonstrably unreliable — on 2026-08-23
    a real, reproducible breakage was labelled `verify-flake` — so a threshold resting on it was
    resting on nothing. Withdrawing it makes the threshold fire SOONER, which fails toward shadow
    mode; that direction is intended. Re-introducing a `fail_class` test here is a REGRESSION and
    tests/test_t11462_selection_coverage_differential.py fails if one appears.

    THE WINDOW IS THE RULE VERSION, and this is the second half of the same ruling. The ruling names
    a NUMBER (three) and no WINDOW, and folded over ALL history this repo's journal ALREADY carried 6
    disagreements (4 `failed` + 2 `timeout` over 74 metric-bearing rows) at the moment governing was
    activated — so an all-history count would have reverted selection to shadow on the very land that
    activated it, contradicting the same ruling's directive to activate now. Counting only rows
    recorded under the rule version in force keeps the accepted historical exposure (~7%: 5 in 71 at
    the ruling, re-folded 6 in 74 at implementation) as the ACCEPTED exposure, and lets the threshold
    govern NEW evidence. A later coverage-map fix that bumps the version earns a fresh window by
    construction — and, because the version lives under `bin/**`, only ever through a change that
    rung R1 forces onto the full suite and the substantive 9-stage path.

    Cheap by construction: a substring pre-filter rejects ~all of a ~190MB journal before any JSON is
    parsed, and the whole fold is paid ONCE per land verify (the same budget the ~0.95s coverage-map
    derivation already sits inside)."""
    if rule_version is None:
        rule_version = _SELECTION_RULE_VERSION
    opener = _open or (lambda pth: open(pth, encoding="utf-8", errors="replace"))
    try:
        n = 0
        with opener(str(journal_path)) as fh:
            for line in fh:
                if '"selection_disagreement"' not in line:
                    continue                       # the pre-filter: no parse for the ~99.99% majority
                try:
                    row = json.loads(line)
                except Exception:
                    continue                       # one malformed line is not a reason to stop counting
                data = row.get("data") or {}
                metrics = data.get("verify_metrics")
                if not isinstance(metrics, dict) or "selection_disagreement" not in metrics:
                    metrics = next((v for v in data.values()
                                    if isinstance(v, dict) and "selection_disagreement" in v), None)
                if not isinstance(metrics, dict):
                    continue
                if str(metrics.get("selection_rule_version")) != str(rule_version):
                    continue                       # outside this rule's window
                if metrics.get("selection_disagreement"):
                    n += 1                         # EVERY disagreement — no fail_class test (above)
        return n
    except Exception:
        return None                                # cannot establish → the governor will not govern

def _selection_strip_prose(src):
    """Blank every COMMENT and DOCSTRING in `src`, preserving its line/column structure (T-11475).

    WHY. `_selection_analyse` below is line-oriented over RAW source, so English prose is scanned as
    if it were code — and the anchor/read-verb regexes are substring matchers. `tests/_hermetic.py`
    was classified UNDECIDABLE by exactly one line, and that line is a docstring sentence: "it
    rebases every REPO_ROOT-derived global INCLUDING EVENTS_PATH" — `REPO_ROOT` is an anchor and
    `glob` matches inside the word "global". That single false positive propagated to the 239 tests
    that import the helper: ~80% of the always-run floor, ~25% of total suite wall time.

    THIS IS NOT A WEAKENING OF THE PREDICATE. A read happens in CODE; it cannot hide in a comment.
    Removing prose from the scan removes FALSE positives only — measured over the live tests tree it
    frees 237 tests, introduces ZERO newly-always-run files, and loses ZERO family registrations
    (no path literal in the tree is docstring-only).

    SCOPED TO THE LINE SCAN ONLY — `is_corpus` IS STILL COMPUTED ON RAW SOURCE (T-11475, deliberate).
    Stripping prose from the `cwd=`/`chdir(` corpus-wide test too would additionally free 14 files
    whose ONLY corpus-wide evidence is prose — and 4 of them were hand-read and are genuinely NOT
    root-cwd (test_t11141 documents running its probe child outside the checkout on purpose;
    test_t11371 and test_t11442 say in so many words that they never `cwd=REPO`). So the wider strip
    looks defensible AND IS STILL NOT TAKEN HERE, because corpus-wide is the last fail-safe class and
    tests/test_t11113_coverage_map_evidence.py holds an independent copy of this derivation that
    would then disagree. Narrowing the corpus-wide predicate is a predicate-reconciliation decision,
    which is T-11476's card, not this one's. Leaving those 14 always-run costs omission share only —
    the safe direction.

    FAIL-SAFE. Any tokenize/syntax failure returns `src` UNCHANGED, so an unparseable file keeps
    today's stricter (more always-run) classification rather than becoming silently hermetic.
    Blanking in place — rather than deleting — keeps line and column offsets identical, so the
    caller's per-line scan is unaffected by the strip itself."""
    try:
        toks = list(tokenize.generate_tokens(io.StringIO(src).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError, ValueError):
        return src                                  # unparseable → analyse the raw text, as before
    rows = [list(line) for line in src.splitlines(keepends=True)]
    # A docstring is a STRING token that OPENS a logical line; a path literal in an expression
    # (`REPO_ROOT / "specs"`) never does, so family resolution keeps every literal it reads today.
    opener = (tokenize.NEWLINE, tokenize.NL, tokenize.INDENT, tokenize.DEDENT, tokenize.ENCODING)
    prev = tokenize.NEWLINE
    for tok in toks:
        prose = tok.type == tokenize.COMMENT or (tok.type == tokenize.STRING and prev in opener)
        if prose:
            (r1, c1), (r2, c2) = tok.start, tok.end
            for r in range(r1, min(r2, len(rows)) + 1):
                row = rows[r - 1]
                lo = c1 if r == r1 else 0
                hi = c2 if r == r2 else len(row)
                for i in range(lo, min(hi, len(row))):
                    if row[i] != "\n":
                        row[i] = " "
        if tok.type not in (tokenize.COMMENT, tokenize.NL):
            prev = tok.type
    return "".join("".join(row) for row in rows)

def _selection_file_anchors(src, rel):
    """T-11848 (SPEC-0181) — one test source + its repo-relative path → `{local name: prefix parts}`
    for every local name that HOLDS A LIVE-CHECKOUT PATH derived from `Path(__file__)`. PURE.

    WHY THIS EXISTS. `_SELECTION_ANCHORS` recognises an anchor by its NAME, from a fixed list
    (`REPO_ROOT|ROOT|REPO|HERE|…`). This suite's DOMINANT loader idiom is
    `YITC_V2_PATH = Path(__file__).parent.parent / "bin" / "yitc-v2"`, and that name is not on the
    list — so a test that LOADS AND EXECUTES `bin/lib/cli.py` from the live checkout was classified
    HERMETIC, joined NO family, and was omitted by every selection. MEASURED on the live tree: 560 of
    1194 test files carry such an anchor; of the 181 files the SPEC-0181 tripwire recovered across 132
    firings, 144 (80%) are this one class, 108 of them through `YITC_V2_PATH` itself. That is the whole
    of the audit-surface concentration the firings show: `bin/lib/audit.py` is periphery-FREED at rung
    R1, so an audit diff reaches R4 and earns an omission while the tests that exec that very module
    sit outside `derived["bin"]`.

    THE ANSWER IS TO DERIVE THE ANCHOR, NOT TO LENGTHEN THE LIST. A longer name list drifts the moment
    a test picks a new variable name, and it fails SILENTLY in the unsound direction (a missed reader is
    an unearned omission). `Path(__file__)` is a fact about the file, not a naming convention, so an
    anchor established from it follows the corpus with no edit — the same reason T-11461 judges leafness
    by MEMBERSHIP in the runner's own enumeration rather than by a filename shape.

    THE AST IS PARSED OFF THE RAW SOURCE, NEVER THE PROSE-STRIPPED TEXT, and that is load-bearing rather
    than incidental: `_selection_strip_prose` BLANKS a docstring, so a class or function whose body is
    only a docstring becomes an empty suite and `ast.parse` raises `IndentationError`. Measured — that
    is exactly why `test_t10334_close_warn_reverify_guidance.py` and `test_t11449_reader_multiset_identity.py`
    resolved no anchors on a first draft that parsed the stripped text, though both carry the idiom in
    plain sight. Prose cannot introduce an ASSIGNMENT, so reading the raw AST admits no false anchor.

    FAIL-SAFE IN THE ONE DIRECTION THAT MATTERS. Every failure — an unparseable file, an expression this
    walker cannot fold, a `..` that would escape the checkout — yields FEWER anchors, i.e. exactly
    today's classification, i.e. the file stays hermetic or undecidable. A returned anchor can only ever
    ADD a family or an always-run marker to a test, so this widens coverage and can never earn a new
    omission."""
    out = {}
    try:
        tree = ast.parse(src)
    except (SyntaxError, ValueError, RecursionError):
        return out
    base_parts = [p for p in str(rel).replace("\\", "/").split("/") if p and p != "."]
    if not base_parts:
        return out

    def _fold_path_expr(node):
        """The expression → repo-relative parts, or None when it is not statically foldable."""
        if isinstance(node, ast.Call):
            f = node.func
            if (isinstance(f, ast.Name) and f.id == "Path" and len(node.args) == 1
                    and isinstance(node.args[0], ast.Name) and node.args[0].id == "__file__"):
                return list(base_parts)
            if isinstance(f, ast.Attribute) and f.attr in ("resolve", "absolute", "expanduser"):
                return _fold_path_expr(f.value)
            return None
        if isinstance(node, ast.Attribute):
            if node.attr == "parent":
                b = _fold_path_expr(node.value)
                return b[:-1] if b else None
            return None
        if isinstance(node, ast.Subscript):
            v = node.value
            if isinstance(v, ast.Attribute) and v.attr == "parents" and isinstance(node.slice, ast.Constant) \
                    and isinstance(node.slice.value, int) and not isinstance(node.slice.value, bool):
                b = _fold_path_expr(v.value)
                n = node.slice.value + 1
                return b[:-n] if b is not None and 0 < n <= len(b) else None
            return None
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            b = _fold_path_expr(node.left)
            if b is None:
                return None
            r = node.right
            if isinstance(r, ast.Constant) and isinstance(r.value, str):
                return _selection_join_parts(b, r.value)
            return None
        if isinstance(node, ast.Name):
            got = out.get(node.id)
            return list(got) if got is not None else None
        return None

    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            continue
        folded = _fold_path_expr(node.value)
        if folded is not None:
            out[target.id] = folded
    return out

def _selection_join_parts(base, literal):
    """`base` parts + a `/`-joined path literal → parts, or None when it escapes the checkout. PURE.

    A `..` that would climb ABOVE the repo root returns None rather than an empty list: the caller reads
    None as "not statically resolvable", which is the fail-safe reading. `.` and empty segments are
    dropped, so `"a//b/./c"` folds like `"a/b/c"`."""
    if base is None:
        return None
    parts = list(base)
    for seg in str(literal).replace("\\", "/").split("/"):
        if not seg or seg == ".":
            continue
        if seg == "..":
            if not parts:
                return None
            parts.pop()
            continue
        parts.append(seg)
    return parts

def _shadow_select(diff_paths, test_files, verify_globs, coverage_map=None,
                   diff_error=None, reachability_freed=None, *, _LEAF_TEST_DIR=None, _selection_coverage_map=None, _selection_enumerated_relpaths=None, _verify_skip_fail_closed_edge=None):
    """SPEC-0181 — the SHADOW affected-test selection decision for ONE land. PURE: takes paths,
    returns `(would_select, would_omit, full_suite_reason)` — two sorted test-file NAME lists plus a
    reason string, which is None ONLY when a real omission was earned.

    It NEVER filters what runs. The caller records the result and executes the full enumeration
    regardless; that is the shadow boundary, and SPEC-0181 licenses recording only. Permitting the
    decision to GOVERN is the successor card's gate (T-11105), not this function's.

    The ladder, evaluated IN ORDER — every rung but the last resolves to the FULL suite, so any state
    this function does not understand is safe by construction:
      R1+R2 SHARED FAIL-CLOSED EDGES — no globs, an unresolvable diff, an empty diff, or a diff
         touching the verifier's own surface → omit NOTHING, with the edge's own reason. Since T-11112
         these four rungs are NOT written here: they are DELEGATED to `_verify_skip_fail_closed_edge`,
         the ONE carrier the per-layer `subject_globs` skip (SPEC-0152 rule 16) also calls, so an edge
         fixed for one mechanism cannot silently stay broken in the other. Their order, their reason
         strings (incl. the T-11118 `diff-unresolvable` / `no-diff` split that must never be
         re-collapsed) and the SPEC-0077 self-guard argument all live in that predicate's docstring.
         The rungs' SAFETY is unchanged: every branch there still omits NOTHING.
      R3 UNKNOWN MAPPING — a changed path no map entry matches → omit NOTHING, and NAME that path in
         the reason. A full-suite backstop on unknown mapping is not optional.
      R4 otherwise — `would_select` is the union of the mapped test globs, PLUS (T-11474) the
         CHANGED TEST ITSELF for any changed path under `tests/` that the runner enumerates. That
         second half is a function of the diff, not of a glob, so no static map entry can carry it —
         and without it the `tests/*` entry would omit THE EDITED TEST, because the derived family
         answers "which tests READ tests/" (642 of 965 are not in it), a different question. The
         mapped half is equally load-bearing: on its own, self-mapping omits the sibling tests that
         read or enumerate the tests/ tree. The rest is `would_omit`.
    """
    names = sorted({Path(str(t)).name for t in (test_files or [])})
    if not names:
        return ([], [], "no-test-files")
    if coverage_map is None:
        # T-11339 — derive the map from the very tests being selected among. The tests dir comes
        # from `test_files` itself, so nothing new is threaded through the land path; an explicit
        # `coverage_map` still wins, which keeps every existing caller (and T-11113's prune
        # differential) byte-identical.
        _dirs = {Path(str(t)).parent for t in test_files}
        coverage_map = _selection_coverage_map(next(iter(_dirs)) if len(_dirs) == 1 else None)
    edge = _verify_skip_fail_closed_edge(diff_paths, verify_globs, diff_error=diff_error,
                                        test_file_names=_selection_enumerated_relpaths(test_files),
                                        reachability_freed=reachability_freed)
    if edge:
        return (names, [], edge)                                               # R1 + R2 (shared)
    selected = set()
    for raw in diff_paths:
        p = str(raw).strip()
        if p.startswith("./"):
            p = p[2:]
        matched = [tg for src, tg in coverage_map if fnmatch.fnmatch(p, src)]
        if not matched:
            return (names, [], f"unresolved-path:{p}")                         # R3
        for tglobs in matched:
            for tg in tglobs:
                selected.update(n for n in names if fnmatch.fnmatch(n, tg))
        # T-11474 — the SELF half of the tests/ union (see the R4 rung in the docstring). Guarded by
        # the SAME enumeration membership rung R1 frees a leaf test by, so a delete or a rename's
        # vanished old path adds nothing here — but neither ever reaches R4, since both still fire
        # R1. This is additive to `selected` only: it can never license an omission.
        if p.startswith(_LEAF_TEST_DIR) and p[len(_LEAF_TEST_DIR):] in names:
            selected.add(p[len(_LEAF_TEST_DIR):])
    return (sorted(selected), [n for n in names if n not in selected], None)    # R4

def _verify_child_nice(*, land_verify: bool, env: "dict | None" = None, _VERIFY_WORKER_MARKER_ENV=None,
                       _VERIFY_WORKER_NICE_DEFAULT=None, _VERIFY_WORKER_NICE_ENV=None,
                       _VERIFY_WORKER_NICE_RANGE=None) -> int:
    """T-11456 — the OS-priority increment this run's per-file test subprocesses are spawned at.
    0 means NORMAL priority AND a byte-identical spawn (the caller omits `preexec_fn` entirely).

    TWO-SIDED, and the two sides are decided by DIFFERENT things on purpose:
      - a LAND verify is NORMAL priority UNCONDITIONALLY — tested FIRST, before the env is even read.
        A dispatched worker's land INHERITS the marker from the session that launched it, so an
        env-only rule would lower the one run that must never be lowered. The land therefore DECLARES
        itself (`land_verify=True`, from `_land_integrate`'s sweep and from the pinned re-run) instead
        of being inferred from an ambient marker that cannot tell the two apart.
      - everything else is lowered ONLY when the dispatched-worker marker is present — an interactive
        `task test --run`, CI, and the pinned / nested / last-green drivers (whose child env the
        hermeticity scrub strips the marker from anyway) all read 0 and are unchanged.
    `os.environ` is read only when `env` is omitted, so BOTH legs stay directly testable.

    T-12224 — the lowered VALUE is a MACHINE-scoped tunable, resolved here; the two-sided RULE above
    is untouched (a land still returns 0 before anything is read, and a marker-absent run still
    returns 0 without consulting the knob at all). PRECEDENCE is SPEC-0193 rule 7 — environment >
    machine settings file > the built-in `_VERIFY_WORKER_NICE_DEFAULT` — copied from the sibling
    `_verify_heartbeat_interval` in this module rather than re-derived, so the two wired read sites
    here cannot acquire two different precedence shapes. FAIL-SAFE DIRECTION is the load-bearing
    part: anything blank, non-numeric or outside `_VERIFY_WORKER_NICE_RANGE` is IGNORED and the
    built-in 19 stands, so a bad value degrades to the LOWEST priority — the conservative end, where
    the worker yields to the land — never to an unniced child competing with the land. Being
    PERFORMANCE-class, this value can never travel into a verdict: `machine_settings.get_value`
    returns None for anything not performance-class, so this site cannot become a door for a
    gate-class value even by mistake. The settings file is an OVERRIDE LAYER and never a
    prerequisite (rule 6): any fault in the settings stack resolves to the default rather than
    putting an infrastructure error on a path every verify pass runs through."""
    if land_verify:
        return 0
    _env = os.environ if env is None else env
    if not (_env.get(_VERIFY_WORKER_MARKER_ENV, "") or "").strip():
        return 0
    raw = _env.get(_VERIFY_WORKER_NICE_ENV)
    if raw is None or not str(raw).strip():
        try:
            from lib import machine_settings      # deferred: keeps the hot import graph unchanged
            raw = machine_settings.get_value(_VERIFY_WORKER_NICE_ENV)
        except Exception:
            raw = None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return _VERIFY_WORKER_NICE_DEFAULT
    lo, hi = _VERIFY_WORKER_NICE_RANGE
    return value if lo <= value <= hi else _VERIFY_WORKER_NICE_DEFAULT

#: T-12357 — the outcomes that are a REAL VERDICT for a test file, i.e. the file was run and the run
#: CONCLUDED about it. `killed-fail-fast` is deliberately ABSENT: a file the fail-fast stop killed
#: mid-flight was never judged, so the resume must re-run it. This is the ledger's whole admission
#: rule and it lives beside the planner rather than inline, so the two readers cannot drift.
_REAL_VERDICT_OUTCOMES = ("passed", "failed", "timed-out", "launch-error")

#: T-12357 — the bound's built-in default and its admissible band. 3 is the MEASURED datum: over the
#: 14 days to 2026-09-10, 83% of this repo's `verify-failed` land aborts named at most three files
#: (224 aborts, 186 of them <= 3). 0 DISABLES the retry entirely — it is a real setting, not a
#: degenerate one, which is why the band starts there.
#: T-12358 — the DECLARED LOAD-SENSITIVE SET's carrier, one committed file under the FIRST swept test
#: dir (the same anchor the duration table uses), diff-visible on every land. Entries are APPENDED by the
#: land tail (`worktree._load_sensitive_entry_at_land_tail`) and only ever REMOVED by a card.
_LOAD_SENSITIVE_FILE = "load-sensitive.txt"


def _load_sensitive_set(test_dir) -> dict:
    """T-12358 — the declared load-sensitive set: `{<test basename>: <its carrier line>}`.

    Reads `<test_dir>/load-sensitive.txt`. Blank lines and `#` comments are skipped; on every other
    line the FIRST whitespace-separated token is the test file's BASENAME and the rest of the line is
    provenance for humans and the C3 card (the entry date, the locator of the retry that put it
    there, an optional ratifying reason) — read by nobody here.

    IDENTITY IS THE BASENAME, and that is unambiguous by THIS runner's own contract: `_run_verify_tests`
    fails closed on a duplicate `test_*.py` basename across the swept dirs before any file runs
    (`_dup_bad`, SPEC-0185 / T-11204), because its whole downstream surface is name-keyed — including
    the T-12357 `flaky_retry.rows[].file` record the land-tail entry fold derives this set from. A
    path-qualified key would be a second identity for the one the runner already refuses to make
    ambiguous.

    FAIL-SAFE IN THE DIRECTION OF TODAY: a missing or unreadable carrier serializes NOTHING — every
    file runs in the pool exactly as before this card. The set moves WHERE a listed file runs, never
    WHETHER, so a lost carrier can only ever run a file under MORE load, never excuse it."""
    out: dict = {}
    # `test_dir` is the FIRST swept dir by the time `_run_verify_tests` calls this (it rebinds
    # `test_dir = _dirs[0]` at discovery, T-11204) — but accept the SEQUENCE shape that runner's
    # public parameter takes too, resolving to the same first dir, so a direct caller handing the
    # declared sweep list gets the same answer rather than a TypeError (audit-post pass-1 finding).
    if not isinstance(test_dir, (str, Path)):
        _seq = [Path(d) for d in (test_dir or [])]
        if not _seq:
            return out
        test_dir = _seq[0]
    try:
        text = (Path(test_dir) / _LOAD_SENSITIVE_FILE).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return out
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        name = line.split()[0]
        if name.endswith(".py"):
            out.setdefault(name, line)
    return out


_VERIFY_RETRY_MAX_FILES_DEFAULT = 3
_VERIFY_RETRY_MAX_FILES_ENV = "YITC_VERIFY_RETRY_MAX_FILES"
_VERIFY_RETRY_MAX_FILES_RANGE = (0, 20)


def _verify_retry_max_files(*, env: "dict | None" = None, _VERIFY_RETRY_MAX_FILES_ENV=_VERIFY_RETRY_MAX_FILES_ENV,
                            _VERIFY_RETRY_MAX_FILES_DEFAULT=_VERIFY_RETRY_MAX_FILES_DEFAULT,
                            _VERIFY_RETRY_MAX_FILES_RANGE=_VERIFY_RETRY_MAX_FILES_RANGE) -> int:
    """T-12357 — how many failing files a leg may re-run in isolation before it stops trying.

    PRECEDENCE is SPEC-0193 rule 7 — environment > machine settings file > the built-in — COPIED
    from the sibling `_verify_child_nice` in this module rather than re-derived, so the two wired
    read sites here cannot acquire two different precedence shapes. Anything blank, non-numeric or
    outside the band is IGNORED and the built-in stands, so a bad value degrades to the measured
    datum rather than to an unbounded retry.

    PERFORMANCE-CLASS, and the reason it can be one is structural rather than a promise: a file is
    cleared ONLY by PASSING in isolation, so no value of this knob can admit a failing check. What
    it changes is how many load-only flakes a leg will try to absorb before it gives up and aborts
    exactly as it does today. `machine_settings.get_value` returns None for anything not
    performance-class, so this site cannot become a door for a gate-class value even by mistake, and
    the settings file stays an OVERRIDE LAYER rather than a prerequisite (rule 6): any fault in the
    settings stack resolves to the default rather than putting an infrastructure error on a path
    every verify pass runs through."""
    _env = os.environ if env is None else env
    raw = _env.get(_VERIFY_RETRY_MAX_FILES_ENV)
    if raw is None or not str(raw).strip():
        try:
            from lib import machine_settings      # deferred: keeps the hot import graph unchanged
            raw = machine_settings.get_value(_VERIFY_RETRY_MAX_FILES_ENV)
        except Exception:
            raw = None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return _VERIFY_RETRY_MAX_FILES_DEFAULT
    lo, hi = _VERIFY_RETRY_MAX_FILES_RANGE
    return value if lo <= value <= hi else _VERIFY_RETRY_MAX_FILES_DEFAULT


def _flaky_retry_plan(failures: list, timeout_marker: str, bound: int, failing_names: list) -> dict:
    """T-12357 — WHETHER this leg's failing set may be re-run in isolation. PURE: no clock, no I/O,
    no verdict — the same shape as `_verify_dispatch_order` beside it, and testable without a
    subprocess.

    Returns `{"retry": [names]}`, or `{"skipped": <reason>, ...}` naming why not:
      * `no-failures` — nothing to re-run (fail-closed; the caller only asks when it saw failures,
        so this reaches the record only if the failure text carried no recognisable file name, and
        recording it is how that stays visible rather than silently reading as "no flakes");
      * `timeout-class` — some failure carries the verify TIMEOUT marker. EXCLUDED DELIBERATELY:
        SPEC-0071 makes a verify timeout a DISTINCT non-retriable class, and re-running one costs
        another full per-file bound — up to 300s of a land's wall to re-learn what the marker
        already said. The whole set is skipped, not just the timed-out member, because a timeout is
        evidence about the RUN (a hang, a starved host) and not only about one file;
      * `over-bound` — more failing files than the bound admits (this is also what a bound of 0
        produces, which is how the knob disables the feature without a second branch).
    """
    names = [n for n in (failing_names or []) if n]
    if not names:
        return {"skipped": "no-failures"}
    if any(timeout_marker in str(f) for f in (failures or [])):
        return {"skipped": "timeout-class", "files": names}
    if len(names) > int(bound):
        return {"skipped": "over-bound", "files": names, "bound": int(bound)}
    return {"retry": names}


def _verify_dispatch_order(test_files: "list", table: dict) -> list:
    """T-11316 — the runner's DISPATCH ORDER: longest recorded duration FIRST. PURE (no clock, no
    I/O, no side effect) over the discovered file list and a table from `_load_verify_duration_table`.

    WHAT THIS BUYS, and it is a bound not a hope. The pool is a greedy list schedule: whatever order
    the files arrive in, a worker takes the next one as it frees. For ANY such schedule the makespan
    is bounded by (optimum + the longest single job), and longest-processing-time-first is what
    actually attains that neighbourhood — a short job discovered late fills a tail slot, whereas a
    LONG job discovered late has nothing to overlap with and is served alone. Measured on this
    repository over a real 878-file pass (T-11315): 235.6s longest-first vs 277.5s alphabetical, a
    41.9s / 15.1% saving, collected two to three times per task (a worker's Tests stage, the land
    candidate verify, and — on a verify-path touch — the SPEC-0077 pinned suite as well).

    WHAT DOES NOT CHANGE. Which files run, their per-file isolation, the per-file timeout, the
    fail-fast semantics, the metrics, and the VERDICT (pass iff no file failed — order-independent by
    construction). This is a sort key and nothing else.

    THE UNKNOWN-FILE RULE, and why the median. A file the table does not name — a brand-new test, or
    every file in a repo that has never rebuilt — is imputed the MEDIAN of the recorded durations,
    with the file NAME as the tie-break. Three properties earn it:
      - it is DEFINED and STABLE, so the same input yields a byte-identical order twice (the thing a
        live-timing implementation cannot do, and the reason this rule is fenced by its own test);
      - it is neither of the two bad extremes: imputing 0 buries a new file at the very end, where a
        heavy one has nothing left to overlap with, while imputing +inf hands the whole head of the
        schedule to files whose cost is unknown;
      - it degrades to EXACTLY today's behaviour when the table is empty — every file is imputed the
        same value, ties break by name, and the result is the plain alphabetical order. A repository
        with no table is therefore not a special case in the code and takes no risk at all.

    Ties break by name and never by discovery order, so the result does not depend on how the
    filesystem enumerated the directory."""
    recorded = sorted(table.values())
    median = recorded[len(recorded) // 2] if recorded else 0
    return sorted(test_files, key=lambda p: (-int(table.get(p.name, median)), p.name))

def _verify_failing_test_names(bad: list) -> list:
    """T-9240 (AC2): extract the failing TEST FILE name(s) from a land `bad` list. Each verify failure
    is the fixed `"test failed: <name>\\n<tail>"` shape (_run_verify_tests), optionally wrapped with the
    `[pinned/last-green] ` prefix (_run_pinned_verify). Pull `<name>` from the first line, de-dup
    order-preserving. Non-test entries (graph-build / conflict-marker / canary lines) yield nothing —
    the abort_reason still carries them; this names the concrete tests for the recovery line."""
    names, seen = [], set()
    for b in bad or []:
        first = str(b).splitlines()[0] if str(b).strip() else ""
        first = first.replace("[pinned/last-green] ", "", 1).strip()
        if first.startswith("test failed: "):
            nm = first[len("test failed: "):].strip()
            if nm and nm not in seen:
                seen.add(nm)
                names.append(nm)
    return names

def _verify_failure_excerpt(out: "str | None", bound: int = _VERIFY_FAIL_EXCERPT_BOUND, *, _rescued_failure_lines=None) -> str:
    """T-10733: excerpt a FAILED test's combined output for the `bad` entry, preserving the ACTIONABLE
    HEAD alongside the tail instead of truncating from the front.

    WHY. The call site recorded `(out or '')[-400:]` — a TAIL-ONLY slice. A `_check`-style V2 test
    prints its `FAIL: <what was expected>` line and a pytest/traceback failure prints its assertion
    header EARLY, so for any test whose output exceeds the bound exactly the part naming WHICH
    assertion failed was cut away and only trailing noise survived (observed live 2026-08-06, fp
    land-verify-sandbox-flake-test-t9389-passes-outside-and-abort-message-truncated-from-front — the
    operator could not tell from the land output which assertion failed, costing a full cycle). The
    downstream `_extract_failing_assertion` (T-9307) mines this excerpt for the assertion line; it can
    only rescue what SURVIVES the slice, so the producer has to stop throwing the head away.

    CONTRACT.
      • `len(out) <= bound` → returns `out` UNCHANGED, byte-identical: no marker, no reflow. Today's
        short-failure records must not move (the overwhelmingly common case), so the mark stays a real
        discriminator rather than unconditional decoration.
      • longer, but SHORTER than the head+tail budget the excerpt would keep anyway → returns `out`
        UNCHANGED and UNMARKED. This is the NEAR-BOUND passthrough and it is deliberate (T-10733
        audit-post finding): the head budget can grow to hold a long first line, so the budget can
        exceed `bound`; in that window the excerpt would elide ZERO characters, and emitting a
        "chars elided" marker over nothing would be a false claim of truncation. The return stays
        bounded regardless — never more than `head_budget + tail_budget` chars.
      • longer than that budget → `<head><elision marker><rescued failure lines><tail>`. The head is
        LINE-AWARE: the whole FIRST LINE is kept whenever it fits inside `bound` (that is the line that
        names the assertion), otherwise the head falls back to the flat half-budget cut — a
        pathologically long single first line must not make the excerpt unbounded. The marker states how
        many characters were dropped, so a TRUNCATED excerpt never reads as complete output.
    So the marker's meaning is exact in both directions: present iff something was actually dropped.

    T-10853 — THE ELIDED SPAN'S FAILURE-IDENTITY LINES ARE RESCUED, because head+tail is POSITIONAL and
    the failure is not. The V2 print-runner (`_run()` in a `tests/test_*.py`) prints `FAIL: <fn>` plus a
    traceback INLINE and then KEEPS GOING, printing the remaining `PASS:` lines after it. So for any file
    whose failing test is not last, BOTH the `FAIL:` line and the traceback sit in the middle — elided —
    while head and tail are `PASS:` lines, and the downstream `_extract_failing_assertion` (which can
    only rescue what SURVIVES the slice) legitimately falls through to its last-non-empty-line fallback
    and names a PASSING assertion. Observed live 2026-08-09 on the T-10818 land: the block named
    `PASS: T-9618/T-10788 — _terminal_detail splits the blocked-on-land detail by escalation target`
    while the real failure was `test_t10818_done_but_unlanded_task_can_escalate` — 12 assertions passed,
    1 failed, and the block named one of the 12. That is worse than a missing label: a missing one sends
    the operator to run the test file, a confident wrong one sends them to the opposite end of their own
    change (this is the T-10819 defect's CANDIDATE-tree sibling — same SPEC-0077 §3a obligation, the
    PRODUCER half rather than the extractor half).
    So the rescued lines are inserted under the marker, matched by the shared POSITIVE discriminators
    (`_VERIFY_FAIL_RESCUE_BOUND`-budgeted; a clip is STATED, never silent). This is the ONLY behaviour
    change: both passthroughs above are untouched (byte-identical), so no existing stored record moves,
    and the return stays bounded — now by `head_budget + tail_budget + _VERIFY_FAIL_RESCUE_BOUND`.
    This changes ONLY what the abort message SAYS: the caller's branch condition, `stop.set()`, the
    `"test failed: <name>\\n<tail>"` first-line shape (parsed by `_verify_failing_test_names` /
    `_surface_failing_assertions`) and the land abort decision are all untouched.
    Diagnostic formatter — never raises."""
    s = out or ""
    if len(s) <= bound:
        return s                                  # byte-identical passthrough (AC2)
    half = max(bound // 2, 1)
    nl = s.find("\n")
    first_line_end = len(s) if nl < 0 else nl + 1   # include the newline, so the marker starts its own line
    # Keep the whole first line when it fits in the bound; never shrink the head below the half-budget.
    head_end = max(half, first_line_end) if first_line_end <= bound else half
    tail_len = max(bound - head_end, bound // 4)  # a head grown to hold a long first line still keeps context
    if head_end + tail_len >= len(s):
        # NEAR-BOUND passthrough: the kept head+tail already covers the whole output, so eliding
        # nothing while printing a "chars elided" marker would be a false truncation claim. Return it
        # whole and unmarked — still bounded by head_budget + tail_budget. Marker present iff dropped.
        return s
    elided = len(s) - head_end - tail_len
    head = s[:head_end]
    if not head.endswith("\n"):
        head += "\n"
    # T-10853: rescue the failure identity out of the span we are about to drop (see the contract above).
    rescued, clipped = _rescued_failure_lines(s[head_end:len(s) - tail_len])
    mark = f"[... {elided} chars elided ...]"
    if rescued:
        _more = f" (+{clipped} more not shown)" if clipped else ""
        mark += ("\n[... failing lines from the elided span" + _more + " ...]\n" + "\n".join(rescued))
    elif clipped:
        # T-11884 — THE CLIP IS STATED EVEN WHEN NOTHING FITS. The contract above says a clip is
        # "STATED, never silent", but the statement lived inside the `if rescued:` arm — so when the
        # budget could afford NO line at all, `clipped` was DROPPED and the excerpt carried a bare
        # `[... N chars elided ...]`, reading exactly like a span that held no failure identity. That
        # is not a cosmetic gap: `_extract_failing_assertion` then returns None and the entry renders
        # `(no assertion captured) - no failure marker in the captured output` — a claim the runner
        # holds positive evidence AGAINST, having matched the line and refused it for length. Live and
        # measured on `tests/test_t10850_rebaseline_preflight.py`, whose failing assertion prints two
        # land-outcome dicts inline: one ~500-char `AssertionError:` line, matched by
        # `_VERIFY_ERROR_VERDICT_RE` and afforded by neither end of the split 400-char budget, so
        # `_rescued_failure_lines` returned `([], 1)`. Eight branches' lands aborted on it under
        # signature verify-failed#0b417d3d2452 reading "a failure it cannot name" (T-11884).
        #
        # WHAT THIS DOES NOT DO, and the bound is the point. The clipped text is emitted INSIDE the
        # `[... ...]` marker line, so it is NOT a rescued line and NOT a candidate assertion: every
        # regex in `_VERIFY_FAILURE_MARKER_RES` is `^`-anchored on `FAIL` / `FAILED ` / `<Name>Error:`
        # and a line opening `[... ` matches none of them. `_extract_failing_assertion` still returns
        # None, the entry still leads with `_NO_ASSERTION_CAPTURED`, `_NO_ASSERTION_CONTEXT_SEP` is
        # untouched, and `_rebaseline_waive_coverage` / `_pinned_entry_waive_record` keep failing
        # closed on exactly the inputs they fail closed on today. Nothing widens marker recognition
        # (the T-11346 bound), nothing ranks lines by content (the `_rescued_failure_lines` contract
        # is unchanged and that function is not modified), and no verdict, gate or waive vocabulary
        # moves. This changes only what the abort message SAYS.
        # The identity hint REUSES the same matcher rather than re-deriving one: re-ask
        # `_rescued_failure_lines` for the SAME span under an unbounded budget (it then returns every
        # matched candidate verbatim, `clipped == 0`), take the FIRST — positional, never ranked by
        # content — and clip it explicitly. No second copy of the discriminator, no new injection
        # point, and `_rescued_failure_lines` itself is unmodified.
        _span = s[head_end:len(s) - tail_len]
        _all, _ = _rescued_failure_lines(_span, 2 * len(_span) + 8)
        _first = " ".join(_all[0].split())[:_VERIFY_FAIL_OVERBUDGET_CLIP] if _all else ""
        _hint = f"; first: {_first}..." if _first else ""
        mark += (f"\n[... {clipped} {_VERIFY_FAIL_OVERBUDGET_MARK} "
                 f"({_VERIFY_FAIL_RESCUE_BOUND} chars), so none is quoted in full{_hint} ...]")
    return f"{head}{mark}\n{s[-tail_len:]}"

def _verify_heartbeat_interval(*, _VERIFY_HEARTBEAT_DEFAULT_SECS=None, _VERIFY_HEARTBEAT_ENV=None) -> float:
    """Seconds between dispatched-worker land-verify progress heartbeats (T-9601). A non-numeric OR
    <=0 value DISABLES the heartbeat (returns 0.0). Doubles as the deterministic test seam (set it
    tiny).

    PRECEDENCE (T-11967): `_VERIFY_HEARTBEAT_ENV` > the machine settings file > the built-in
    `_VERIFY_HEARTBEAT_DEFAULT_SECS`. This is the wired read site for the machine-scoped settings
    file — a PERFORMANCE-class knob (an emit cadence; the verify verdict, the per-file timeout and
    the SPEC-0077 gate are untouched by it). A missing/unreadable/malformed file contributes
    nothing and the built-in default is observed, so the file is an override layer and never a
    prerequisite of the verify."""
    raw = os.environ.get(_VERIFY_HEARTBEAT_ENV)
    if raw is None or not raw.strip():
        from lib import machine_settings          # deferred: keeps the hot import graph unchanged
        from_file = machine_settings.get_value(_VERIFY_HEARTBEAT_ENV)
        return _VERIFY_HEARTBEAT_DEFAULT_SECS if from_file is None else from_file
    try:
        v = float(raw)
    except ValueError:
        return 0.0
    return v if v > 0 else 0.0

def _verify_heartbeat_line(done: int, total: int, elapsed: float) -> str:
    """One land-verify progress line for a dispatched worker (T-9601) — names files-done/total +
    elapsed and reminds the worker to keep `land` in the FOREGROUND. PURE (no I/O)."""
    return (f"land: verify in progress — {done}/{total} test files done, {elapsed:.0f}s elapsed "
            f"(dispatched-worker foreground heartbeat — keep `land` in the FOREGROUND; do NOT "
            f"background it: a yield would kill it mid-verify)")

def _verify_implementation_touch_pairs(changed_files, *, _VERIFY_IMPLEMENTATION_GLOBS,
                                      test_file_names=None, reachability_freed=None, _selection_leaf_test_freed=None) -> tuple:
    """T-12155 — the SORTED, DISTINCT `(path, glob)` PAIRS the changed paths match; `()` when none do.
    THE ONE MATCHING CARRIER, one level deeper than T-11460 left it: `_verify_implementation_touch_globs`
    below is now a PROJECTION over this (the sorted distinct glob halves) and
    `_is_verify_implementation_touch` a thin `bool()` over that — so the THREE readings (DID the diff
    touch the verifier · WHICH glob made it · WHICH PATH matched that glob) are read off the SAME pair
    and cannot drift apart. Path normalisation (`./` strip) and both narrowings are applied HERE, once,
    exactly where they were applied before: this is T-11460's loop moved down one level, with NO new
    matching logic and NO second normalisation.

    WHY THE PATH HALF IS RECORDED AT ALL (T-12155). `selection_full_suite_globs` names WHICH GLOB
    refused, and for the `bin/**` arm that is one atom covering ~37 modules: measured over
    2026-08-27..09-12, 41% of all kernel lands were refused at rung R1 with
    `selection_full_suite_globs == ['bin/**']` and the record could not say which module did it. The
    attribution had to be RECONSTRUCTED from git history (an approximation), which is exactly the cost
    keeping the path half removes. The predicate ALREADY computes the pair; this stops discarding it.

    PURE, and it changes NO decision: every caller's branch is still taken on emptiness, the refusal
    fires on exactly the inputs it fired on before, and no reason string moves."""
    matched = set()
    for raw in changed_files:
        p = raw.strip()
        if p.startswith("./"):
            p = p[2:]
        # T-11461 — the narrowed `tests/**` arm. A freed leaf test file matches NO glob here, so the
        # bool (did the diff touch the verifier) and the recorded glob key (WHICH glob refused) move
        # TOGETHER: the one-matching-carrier discipline is why the narrowing is applied here rather
        # than at the two readings separately, where they could disagree about the same diff.
        if _selection_leaf_test_freed(p, test_file_names):
            continue
        # T-11463 — the reachability arm. `reachability_freed` is the set of paths a caller has
        # PROVEN touch no def participating in the selection decision (`_selection_reachability_freed`);
        # it is applied HERE, in the ONE matching carrier, for the same reason the T-11461 narrowing is:
        # the bool and the recorded glob key must move together. `None` (every caller that does not opt
        # in, incl. the SPEC-0077 pinned-verify trigger) leaves this byte-identical.
        if reachability_freed and p in reachability_freed:
            continue
        for g in _VERIFY_IMPLEMENTATION_GLOBS:
            if fnmatch.fnmatch(p, g):
                matched.add((p, g))
    return tuple(sorted(matched))

def _verify_implementation_touch_globs(changed_files, *, _VERIFY_IMPLEMENTATION_GLOBS,
                                       test_file_names=None, reachability_freed=None, _selection_leaf_test_freed=None) -> tuple:
    """T-11460 — the SORTED, DISTINCT set of verifier-surface globs the changed paths match; `()` when
    none do. THE ONE MATCHING CARRIER: `_is_verify_implementation_touch` below is a thin `bool()` over
    this, so the two readings — DID the diff touch the verifier, and WHICH glob made it — can never
    drift apart (the same one-carrier discipline `_verify_skip_fail_closed_edge` applies to the shared
    fail-closed rungs). Path normalisation (`./` strip) is done here, once.

    T-12155 — SINCE THIS CARD THIS IS A PROJECTION over `_verify_implementation_touch_pairs` above
    (the sorted distinct glob halves), which is where the loop, the normalisation and both narrowings
    now live. The one-carrier claim therefore holds at a STRICTLY DEEPER level than before: the glob
    reading and the new path reading are read off the SAME pair. Signature, return type and semantics
    are unchanged — `tests/test_t11460_selection_refusal_glob.py` and the T3 projection arm of
    `tests/test_t12155_selection_refusal_path.py` pin that re-layering against a behaviour change.

    WHY THE SET AND NOT THE FIRST MATCH. The predicate this replaces short-circuited on the first
    matching (path, glob) pair while iterating over the DIFF's paths, so a "the glob that refused"
    value read off it would depend on the order git happened to list the diff in, and a diff touching
    both `bin/**` and `tests/**` would name whichever came first. The consumers of this measurement
    (SPEC-0181's successor cards: narrow `tests/**`, then a reachability filter inside `bin/`) each
    need the share of refusals attributable to THEIR glob ALONE — a question a first-match value
    cannot answer and would answer wrongly. Reporting every matched glob costs one full pass over a
    land's diff and makes the record order-independent.

    PURE, and it changes NO decision: every caller's branch is still taken on emptiness, the refusal
    fires on exactly the inputs it fired on before, and no reason string moves."""
    return tuple(sorted({g for _p, g in _verify_implementation_touch_pairs(
        changed_files, _VERIFY_IMPLEMENTATION_GLOBS=_VERIFY_IMPLEMENTATION_GLOBS,
        test_file_names=test_file_names, reachability_freed=reachability_freed,
        _selection_leaf_test_freed=_selection_leaf_test_freed)}))

def _verify_skip_fail_closed_edge(diff_paths, verify_globs, diff_error=None,
                                  test_file_names=None, reachability_freed=None, *, _SKIP_EDGE_DIFF_UNRESOLVABLE=None, _SKIP_EDGE_NO_DIFF=None, _SKIP_EDGE_NO_GLOBS=None, _SKIP_EDGE_VERIFY_TOUCH=None, _is_verify_implementation_touch=None) -> "str | None":
    """T-11112 — THE ONE carrier of the fail-closed edges SHARED by the two subject-scoped verify-skip
    mechanisms: the per-layer `subject_globs` skip (`_subject_scoping_skip_layers`, SPEC-0152 rule 16)
    and the per-file shadow selector (`_shadow_select`, SPEC-0181). PURE. Returns the edge's REASON
    token when the candidate diff cannot support ANY skip decision — the caller must then run
    EVERYTHING — or None when no shared edge fires and the caller may proceed to its OWN granularity.

    The two mechanisms differ in UNIT (an opaque declared layer vs an engine-enumerated test file) and
    that difference is real and stays (the layer is opaque, so it is the only honest skip unit). What
    does NOT differ is the question asked at the EDGES: with no globs to judge against, with a diff
    that could not be computed, with a diff that is empty, or with a diff touching the verifier's own
    surface, NEITHER mechanism can prove a skip. Those four rungs used to be written twice,
    independently, so an edge fixed on one side could silently stay broken on the other. They are
    written ONCE here, and the pairing is pinned by tests/test_t11112_shared_fail_closed_edge.py.

    The rungs, IN ORDER — the order is part of the contract, because the reason each caller RECORDS
    depends on which rung fires first:
      1. no `verify_globs`      → `no-verify-globs`. Nothing to evaluate rung 4 with; judging is
                                  impossible, not merely negative.
      2. `diff_error` truthy    → `diff-unresolvable:<error>`. Checked BEFORE the empty rung on
                                  purpose: a FAILED computation yields no paths, so collapsing it into
                                  the empty case makes a total breakage look like a normal quiet land
                                  (T-11118 — a TypeError degraded 13 of 13 lands to the full suite
                                  invisibly because both readings were spelled `no-diff`). Same
                                  fail-closed outcome, distinguishable causes; never re-collapse them.
      3. empty `diff_paths`     → `no-diff`. Computed, and genuinely empty: there is nothing to reason
                                  a disjoint subject (or an affected-test set) against.
      4. verify-impl touch      → `verify-implementation-touch` (SPEC-0077 supremacy). A diff touching
                                  the verifier's own surface disables skipping ENTIRELY. Delegated to
                                  `_is_verify_implementation_touch`, which both mechanisms already
                                  shared before this consolidation — folded in here so ALL four shared
                                  rungs have one carrier rather than one-of-four. NARROWED by T-11461
                                  for the `tests/**` arm: when the caller supplies `test_file_names`
                                  (its own enumeration of the tests in the tree), a changed path that
                                  is a LEAF test file no longer counts as a verifier-surface touch —
                                  see `_selection_leaf_test_freed` for the freed shape and for why
                                  shared test infrastructure, deletes and renames still refuse. With
                                  `test_file_names=None` (the per-layer mechanism) the rung is
                                  byte-identical to before.
    NOT here, deliberately, and pinned as such by the mirror test: each mechanism's OWN-granularity
    edges — the layer side's per-layer absent/malformed `subject_globs` and its `base_ref`/git-runner
    precondition, the file side's `no-test-files` and `unresolved-path:<p>`. Those are edges of the
    UNIT, not of the diff, so sharing them would force exactly the false equivalence the granularity
    difference forbids. The THIRD skip mechanism — the whole-verify inert-retry skip (SPEC-0064/0065,
    `_classify_inert_paths`) — is deliberately NOT a caller: it decides by path CLASS over a shipped
    allowlist, has no glob declaration to be absent, treats an EMPTY set as vacuously INERT (the
    OPPOSITE polarity of rung 3, SPEC-0064 §2), and reaches rung 4's outcome through its own `bin`/
    `tests` classes, which the T-0631 one-authority invariant requires it keep doing."""
    if not verify_globs:
        return _SKIP_EDGE_NO_GLOBS
    if diff_error:
        return f"{_SKIP_EDGE_DIFF_UNRESOLVABLE}:{diff_error}"
    if not diff_paths:
        return _SKIP_EDGE_NO_DIFF
    if _is_verify_implementation_touch(diff_paths, _VERIFY_IMPLEMENTATION_GLOBS=verify_globs,
                                       test_file_names=test_file_names,
                                       reachability_freed=reachability_freed):
        return _SKIP_EDGE_VERIFY_TOUCH
    return None

def _verify_worker_bound(*, _headroom: "dict | None" = None, _host_resource_headroom=None) -> int:
    """The host's total verify-worker budget RIGHT NOW = the MIN across the multi-resource headroom
    (SPEC-0132 Rule 1). 0 ⇒ some resource cannot fit even ONE verify worker → the host is exhausted and
    a land must REFUSE (fail-closed) rather than oversubscribe."""
    hr = _headroom if _headroom is not None else _host_resource_headroom()
    vals = list(hr.values())
    return min(vals) if vals else 0

def _verify_worker_governor(*, _headroom: "dict | None" = None, _VERIFY_WORKER_CEILING=None, _verify_worker_bound=None) -> int:
    """SPEC-0132 Rule 1 — the per-verify DESIRED worker count W = the host bound capped at the ceiling,
    or 0 to REFUSE when the host is exhausted (`_verify_worker_bound` ≤ 0). This is the GENERIC-runner
    default (`_run_verify_tests` when no explicit `workers=`); the LAND additionally enforces the TRUE
    cross-land bound via `_verify_admission` (the slot semaphore). Pure arithmetic on live measurements;
    `_headroom` (test-only) injects a synthetic resource state."""
    b = _verify_worker_bound(_headroom=_headroom)
    return 0 if b <= 0 else min(b, _VERIFY_WORKER_CEILING)

def cmd_verify_durations(args, *, REPO_ROOT, _run_verify_tests, _die, write_text_atomic,
                         _consumer_tests_delegation=None, _VERIFY_DURATIONS_FILE=None, _load_verify_duration_table=None,
                         _verify_worker_governor=None) -> None:
    """T-11316 — `verify-durations` (bare = REPORT) / `--rebuild` (regenerate the table).

    THE VERB IS THE POINT — for a MEASURING run. This verb's job is to rebuild the table by RUNNING
    the whole suite once, which is what a cold repo or a deliberate suite change needs. It is no
    longer the only writer: T-11440 gave the land seam an automatic refresh from the measurement it
    already takes (`_refresh_verify_duration_table`), because an explicit-act-only rule did not
    survive GROWTH — files are born unrecorded at ~19/day, so between rebuilds the table silently
    stopped naming the suite. This verb keeps the two modes that a measuring run needs, and they stay
    deliberately asymmetric: the BARE form never runs anything and never writes, and `--rebuild` is
    all-or-nothing.

    BARE = the divergence REPORT, `debt` posture. It compares the recorded table against the files
    actually on disk and states the drift in both directions — files with no recorded duration (they
    are scheduled at the imputed median, which is correct but blind) and recorded files that no
    longer exist (dead weight in the table, and a shifted median). Divergence is SHOWN, never
    silently absorbed — the `implements_signature` drift-WARN precedent. Read-only: no run, no
    worktree, no event, no mutation.

    `--rebuild` = ALL-OR-NOTHING. It runs the suite ONCE through the SAME runner the land verify uses
    and rewrites the table from that measurement. Two properties, both load-bearing and both a
    direct answer to the audit-pre finding this verb was RED-ed on:
      - `fail_fast=False`, so a failing file never stops its siblings from being launched. Under the
        default fast-abort a single early failure leaves most of the suite unmeasured, and the run
        would produce a table describing a fraction of it.
      - it REFUSES TO WRITE unless every discovered file carries a recorded attempt, naming what is
        missing. A PARTIAL table is worse than no table: the unmeasured files silently fall to the
        imputed median while the measured ones keep real values, so the very files that failed or
        never ran get systematically mis-ranked — and nothing about the resulting file looks wrong.
      - a FAILING file's wall is still RECORDED. Its cost is real cost, and this is a scheduling
        artifact, not a verdict; dropping it would bias the table downward exactly as T-11123 warns.
        The suite's own verdict is reported for the operator, and it does not gate the write.

    Repo-scoped and consumer-safe by construction: the table's home is `<REPO_ROOT>/tests/`, the same
    kernel probe dir the runner is handed, so `-C <consumer>` rebuilds THAT consumer's table from
    THAT consumer's suite. There is deliberately no cross-repo table (fu_c41560429f93).

    DELEGATED TESTS — THE REBUILD REFUSES, AND SAYS WHY (T-11389 / X-1046). Everything above assumes
    the thing being measured is the thing that runs. Where a consumer declares a verify layer whose
    `covers:` names the root tests dir (`_consumer_tests_delegation`, SPEC-0152 rule 16) that
    assumption is false in BOTH directions, and each alone would be disqualifying:
      * the WRITE side measures nothing. `_run_verify_tests` launches each file as `python3 <file>` on
        the HOST — the engine's suite convention. A suite that needs the layer's app + database exits
        immediately there, so the table records the cost of failing to start. Measured: kupiclub
        rebuilt 66 files at 0.5s TOTAL against a layer that really takes 125s. Two orders of
        magnitude, and nothing about the resulting file looks wrong — the same failure the
        partial-table refusal above already guards, at whole-file scale.
      * the READ side never opens it. The table's ONLY reader is `_run_verify_tests`, and that sweep
        is SKIPPED for precisely these projects (`_land_integrate`, `task test --run`). Even a
        PERFECT per-file table here would schedule a run that does not happen.
    So the refusal costs nothing real. BUILDING THROUGH THE LAYER was the alternative and it does not
    survive either half: a layer `command:` is an arbitrary shell string yielding one exit code and
    one wall, so per-FILE walls would need a kernel-side timing protocol imposed on every consumer —
    and it would still produce a table nobody reads. An honest cannot-measure-this-from-here beats a
    table of zeros: a measurement that is CONFIDENTLY WRONG costs more than an absent one, and here
    the absent one costs nothing at all.
    The BARE report carries the other half — an ALREADY-WRITTEN wrong table is named SUSPECT with its
    own numbers shown, because the whole defect is that the number is believable, and leaving a
    plausible file in place silently is the failure mode repeating.
    UNCHANGED where no layer covers tests/ — the predicate is fail-closed (engine build, unreadable
    carrier, section waiver, waived or commandless layer all yield None), and None is byte-for-byte
    today's behaviour. Scoping the bare-host route is not removing it."""
    test_dir = Path(REPO_ROOT) / "tests"
    if not test_dir.is_dir():
        _die(f"{test_dir} does not exist — this repo runs no `tests/test_*.py` probes through the "
             f"kernel runner, so it has no duration table to report on or rebuild.")
    discovered = sorted(p.name for p in test_dir.glob("test_*.py"))
    table_path = test_dir / _VERIFY_DURATIONS_FILE
    table = _load_verify_duration_table(test_dir)
    # T-11389 (X-1046) — is this repo's root tests/ surface DELEGATED to a declared verify layer? The
    # predicate is the SAME one the two sweep callers use (never a second reading of the contract), and
    # it is fail-closed: any doubt — engine build included — returns None and nothing below changes.
    deleg = (_consumer_tests_delegation(Path(REPO_ROOT))
             if _consumer_tests_delegation is not None else None)

    if not getattr(args, "rebuild", False):
        if deleg:
            print(f"verify-durations: this project DELEGATES its root tests/ to the declared verify "
                  f"layer '{deleg}' (its `covers:` names tests/, SPEC-0152 rule 16), so the kernel "
                  f"does NOT sweep {test_dir} — the duration table has no reader here.")
            if not table:
                print(f"  no table at {table_path} — the CORRECT state for a delegating project, not "
                      f"a gap to fill. `--rebuild` is refused here; see it for why.")
                return
            _total = sum(table.values())
            _dear = max(table.items(), key=lambda kv: (kv[1], kv[0]))
            print(f"  ⚠ a table EXISTS at {table_path} and it is SUSPECT BY CONSTRUCTION: any table "
                  f"here was written by the bare-host route (`python3 <file>`), which does not run a "
                  f"delegated suite at all. Its own numbers: {len(table)} file(s), "
                  f"{_total / 1000.0:.1f}s total, dearest {_dear[0]} at {_dear[1] / 1000.0:.1f}s — "
                  f"read them against what the '{deleg}' layer actually takes.")
            print(f"  This is NOT a scheduling-cost report: those durations measure the tests failing "
                  f"to start, not the tests. DELETE {table_path}; the layer is where this suite's "
                  f"cost is recorded. (A confidently WRONG measurement costs more than an absent one.)")
            return
        if not table:
            print(f"verify-durations: no table at {table_path} — the verify suite is scheduled by "
                  f"name only ({len(discovered)} file(s)). This is a NORMAL state, not an error: "
                  f"order is still deterministic, just not cost-ordered. Run "
                  f"`verify-durations --rebuild` to record one.")
            return
        unrecorded = [n for n in discovered if n not in table]
        stale = sorted(n for n in table if n not in set(discovered))
        print(f"verify-durations: {table_path} records {len(table)} file(s); {len(discovered)} "
              f"discovered on disk.")
        if unrecorded:
            print(f"  {len(unrecorded)} discovered file(s) have NO recorded duration (scheduled at "
                  f"the imputed median): {', '.join(unrecorded[:10])}"
                  f"{' …' if len(unrecorded) > 10 else ''}")
        if stale:
            print(f"  {len(stale)} recorded file(s) no longer exist (dead weight, and they shift the "
                  f"median): {', '.join(stale[:10])}{' …' if len(stale) > 10 else ''}")
        if not unrecorded and not stale:
            print("  no divergence — the table names exactly the discovered set.")
        else:
            print("  divergence is a SCHEDULING cost only — the verdict is unaffected. It is also "
                  "SELF-HEALING since T-11440: the next green land REWRITES this table from its own "
                  "measurement whenever a discovered file has no recorded duration (the coverage arm, "
                  "unconditional). `--rebuild` remains the way to re-measure the WHOLE suite in one "
                  "run — a cold repo, or after a deliberate suite change.")
        # T-12297 (AC5) — THE CRITICAL-PATH LINE. Report-only, and deliberately the LAST thing the
        # bare arm prints. The divergence report above answers "is the table honest?"; this answers
        # the question that actually costs land time, "what is the FLOOR on a verify wall, and which
        # files set it?" — because the runner packs longest-first at FILE granularity, so one long
        # file is an indivisible piece of the wall no width can subdivide. Without it, a file growing
        # to three minutes is invisible until it is already costing every land (the T-12297 trigger:
        # a full two-leg land drifted ~5 min -> ~8.5 min with nothing naming the cause).
        #
        # The bound is the LARGER of two floors, and printing both is the point:
        #   - the LONGEST single file: no amount of width divides it;
        #   - the per-file sum / width: total work spread perfectly over W workers.
        # Whichever dominates tells you which lever to reach for — split/shorten the head of the list,
        # or add width. Neither floor is a prediction of the wall: real runs pay scheduling, startup
        # and contention on top, and W here is the CEILING-capped governor value, which a loaded host
        # can lower. It is a FLOOR and is labelled as one.
        #
        # Report-only by construction: no exit code moves, no event is emitted, nothing is written,
        # and this arm still never runs the suite. The `--rebuild` arm, the scheduling/packing path,
        # the selection rule and the W derivation are all untouched by this card.
        if table:
            # `_load_verify_duration_table` returns MILLISECONDS per file (it multiplies the stored
            # quantised units back up on read), so seconds is /1000 — NOT the series unit. Getting
            # this wrong is silent and 100x, which is why the conversion is named rather than inline.
            longest = sorted(table.items(), key=lambda kv: (-kv[1], kv[0]))
            total_s = sum(v for _n, v in longest) / 1000.0
            head_s = longest[0][1] / 1000.0
            width = None
            if _verify_worker_governor is not None:
                try:
                    width = _verify_worker_governor()
                except Exception:          # noqa: BLE001 — a report never fails the verb
                    width = None
            print(f"  critical path — the 10 longest files ({len(table)} recorded, "
                  f"{total_s:.0f}s of per-file work in total):")
            for i, (name, v) in enumerate(longest[:10], 1):
                print(f"    {i:2d}. {v / 1000.0:7.1f}s  {name}")
            if width and width > 0:
                spread_s = total_s / width
                floor_s, why = ((head_s, "the longest single FILE — width cannot divide it")
                                if head_s >= spread_s else
                                (spread_s, f"the per-file SUM spread over {width} workers"))
                print(f"  bound: a verify wall cannot beat {floor_s / 60.0:.1f} min "
                      f"({floor_s:.0f}s) — {why}. "
                      f"longest file {head_s:.0f}s vs sum/{width} = {spread_s:.0f}s.")
            else:
                print(f"  bound: a verify wall cannot beat the longest single file, {head_s:.0f}s — "
                      f"width cannot divide it (the worker governor is unavailable here, so the "
                      f"sum/width floor is not computed).")
            print("  Report-only: nothing above changes an exit code, a verdict, or the table.")
        return

    if deleg:
        _die(f"verify-durations --rebuild: REFUSING to measure — this project DELEGATES its root "
             f"tests/ to the declared verify layer '{deleg}' (its `covers:` names tests/, SPEC-0152 "
             f"rule 16). A rebuild times `python3 <file>` on the HOST, which is not how these tests "
             f"run: they run inside that layer, and on the bare host they exit immediately — so the "
             f"table would record the cost of failing to start, not the cost of the suite (measured "
             f"elsewhere: 66 files at 0.5s total against a layer that takes 125s). And nothing would "
             f"read it: the kernel SKIPS the bare sweep for exactly these projects, so the table "
             f"schedules a run that never happens. An honest cannot-measure-this-from-here beats a "
             f"table of zeros — a measurement that is CONFIDENTLY WRONG costs more than an absent "
             f"one. The '{deleg}' layer is where this suite's cost is recorded; if a table already "
             f"exists at {table_path}, run bare `verify-durations` — it reports that table as "
             f"suspect. NOTHING was written and no existing table was touched.")
    if not discovered:
        _die(f"{test_dir} discovers no `test_*.py` — nothing to measure.")
    print(f"verify-durations: measuring {len(discovered)} file(s) through the land-verify runner "
          f"(fail_fast=False — every file runs to its own verdict) …")
    measured: list = []
    outcomes_locator: dict = {}
    bad = _run_verify_tests(test_dir, Path(REPO_ROOT), fail_fast=False, durations_out=measured,
                            metrics_out=outcomes_locator)
    walls: dict = {}
    for name, wall_ms, _outcome in measured:
        walls[str(name)] = max(int(wall_ms), walls.get(str(name), 0))
    missing = [n for n in discovered if n not in walls]
    if missing:
        _die(f"verify-durations --rebuild: {len(missing)} discovered file(s) carry no recorded "
             f"attempt — REFUSING to write a partial table (a partial table mis-ranks exactly the "
             f"files it is missing, and looks correct doing it). Missing: "
             f"{', '.join(missing[:20])}{' …' if len(missing) > 20 else ''}")
    unit = _VERIFY_DURATION_SERIES_UNIT_MS
    payload = {"unit_ms": unit,
               "files": {n: max(1, (walls[n] + unit // 2) // unit) for n in sorted(walls)}}
    write_text_atomic(table_path, json.dumps(payload, indent=2, sort_keys=True) + "\n")
    # T-12190 — the measuring run exported the per-file OUTCOME sidecar too (the runner writes it by
    # default). Printed here because a rebuild is exactly the run whose outcome list a reader wants:
    # it runs fail_fast=False, so every discovered file carries a real measured verdict.
    _ol = outcomes_locator.get("per_file_outcomes") or {}
    if _ol:
        print(f"verify-durations: per-file outcomes exported to {_ol['path']} — "
              f"{_ol['count']} file(s), sha256 {_ol['sha256'][:16]}… (complete: one row per "
              f"discovered file, with its outcome and wall_ms).")
    print(f"verify-durations: wrote {table_path} — {len(payload['files'])} file(s), unit {unit}ms. "
          f"Suite verdict: {'PASS' if not bad else str(len(bad)) + ' failing file(s)'} "
          f"(reported, NOT a gate on the write — a failing file's wall is real cost and is recorded).")

def hermetic_child_env(box: Path, tf_name: str, cwd, *, source_env=None,
                       expected_session_ref_env: str, scrub_carriers=None, _HELD_TURN_CLAIM_ENV=None, _HERMETIC_AUDITOR_ENV_OVERRIDES=None, _HERMETIC_HOME_ROOTED_OVERRIDES=None, _HERMETIC_XDG_KEYS=None, _REAL_STORE_ALLOWLIST=None, _live_journals=None) -> dict:
    """SPEC-0131 Rule 1+2 — the ambient env for ONE test subprocess, built in ONE place.

    THE single home for "what a verify-runner child sees" (CHARTER §P5). The land-verify runner
    (`_run_verify_tests` below) calls it for every test subprocess it spawns, and so does any
    INSTRUMENT that claims to measure that runner (`dev-utilities/measure-floor-cost.py`). It was
    extracted from the runner's own closure by T-11133 after a hand-MIRRORED copy of it drifted: the
    instrument set `YITC_EVENTS_PATH_DEFAULT` but never the `YITC_EVENTS_GUARD_ROOT` that
    scope-guards it (`bin/yitc-v2::_scope_guarded_events_default`), so the override never engaged and
    EVERY profiled child read the real 139MB `events.jsonl` — a whole-suite cost profile that was an
    artifact of the instrument, and was used as grounds to close a live card (T-10999). Two
    hand-maintained builders for one purpose drift again; one builder cannot.

    EVERY test (allowlisted or not) gets a private HOME/TMPDIR/XDG_*/git-config (Rule 1 is
    unconditional). The named `_REAL_STORE_ALLOWLIST` switches ONLY the real-store (default-journal)
    binding: a non-allowlisted test ALSO gets a private YITC_EVENTS_PATH_DEFAULT (its raw default
    journal quarantined, fail-closed default); an allowlisted test gets NO override — the ONE
    sanctioned real-store touch.

    `source_env` defaults to the live `os.environ` (what a real spawn inherits); `cwd` is the
    checkout being verified (the guard root); the two injected identity names come from
    `bin/yitc-v2` (single-SoT — never mirrored here).

    ## What is scrubbed and what is inherited by design (T-11477 — the decision, recorded HERE)

    The rest of the launching process's environment is INHERITED, and that is deliberate rather than
    an oversight. What decides membership is ONE criterion, applied mechanically:

      **An ambient var is SCRUBBED iff it OVERRIDES a default that Rule 1 already sandboxes**
      (HOME / TMPDIR / XDG_* / the git config) **— or carries the launching session's own state**
      (the auditor knobs, the journal/land-mode markers, the identity carriers).
      **Everything else is INHERITED**, because the child must still be able to FIND AND RUN the
      host toolchain it is testing.

    WHY THE FIRST HALF. A var that redirects where a host tool keeps its per-user state points INTO
    the very directory Rule 1 replaced. Inheriting it leaves the sandbox HALF-APPLIED — HOME private,
    its override live — and that is the worst of the three states, strictly worse than either
    inheriting everything or scrubbing everything: the child's answer then depends on THE LAUNCHER'S
    SHELL. Measured: `CODEX_HOME` is exported by an interactive-shell rc on this host, so the same
    capability probe passed 7/7 under a land started from an interactive controller and failed 25/25
    under one started headless — deterministic given the environment, which is exactly why it read as
    a flake and cost 9 blocked lands across 4 branches over 4 days before anyone diagnosed it
    (T-11472; `PLAYWRIGHT_BROWSERS_PATH` is the same shape one leg over, T-11473). The enumerated
    carrier is `_HERMETIC_HOME_ROOTED_OVERRIDES` above. This is the harness-level application of the
    craft SPEC-0131 Rule 1 already cites — [[test-on-the-real-target-provider-to-catch-env-leaks]]:
    sandbox every host-mutable env var the spawned code reads, not only the ones the current run
    happens to leave unset. That lesson NAMES `CODEX_HOME` as the var that leaked.

    WHY THE SECOND HALF — `PATH`, `PYTHONPATH` and the remaining ambient env stay. They override
    nothing HOME-rooted; they are how the child reaches `git`, `python` and the interpreter it runs
    under. Scrubbing them would not isolate a test, it would stop it running at all, so the sandbox
    would fail closed on its own subject. Hermeticity here is a claim about STATE the child could
    read or corrupt, never about severing it from the toolchain.

    FALSIFIERS — what would change each answer, so this is a reason and not a preference:
      * A var joins the scrub the moment it is found to redirect a HOST TOOL's per-user state
        directory (the `~/.<tool>` / `~/.cache/<tool>` class). Finding one is not a re-litigation of
        this decision, it is this decision being applied.
      * The inherited half is overturned by an ambient var that a child both inherits AND cannot run
        without, whose value nonetheless makes the child's answer about the HOST false. `PATH` is the
        near miss and it does NOT qualify: an inherited `PATH` is the launcher's REAL one, so a
        preflight that resolves a declared command against it answers TRULY for the user who started
        the land — unlike a `~`-rooted read under a synthetic HOME, which cannot.

    WHAT THIS DOES NOT REPLACE. Scrubbing removes the LAUNCHER-DEPENDENCE; it does NOT make a
    HOME-rooted probe honest. A probe reading a synthetic, user-less box HOME would then report "the
    operator must run `codex login`" deterministically instead of intermittently — still a false claim
    about a real person's machine. That is fixed at the LEG, by answering UNDETERMINABLE inside a
    hermetic child (`_in_hermetic_verify_child`, T-11472/T-11473). The two are complementary and
    neither subsumes the other; both are load-bearing."""
    base = os.environ if source_env is None else source_env
    # T-0579 / T-9555 / T-9794 / T-10073 / T-10166 / T-11477 — the base scrub, hermetic to the
    # LAUNCHING session. Rationale per variable is documented at the runner's call site below; the
    # membership CRITERION for the whole set is in this function's own docstring above.
    _scrubbed = (*_HERMETIC_AUDITOR_ENV_OVERRIDES, *_HERMETIC_HOME_ROOTED_OVERRIDES,
                 "YITC_EVENTS_SINK",
                 "YITC_EVENTS_PATH_DEFAULT", "YITC_EVENTS_GUARD_ROOT",
                 "YITC_SYNCHRONOUS_LAND", _HELD_TURN_CLAIM_ENV,
                 # T-11432 — the AMBIENT shared-store carrier, and ONLY the ambient one. It is the
                 # exact sibling of the three journal-store carriers above (SPEC-0084 rule 5: the
                 # coordination store is the same journal MECHANISM), and it meets this function's
                 # stated membership criterion verbatim — it OVERRIDES a default Rule 1 itself
                 # sandboxes, in the rule-1 block below.
                 #
                 # MEASURED, not anticipated: a dispatched worker's environment carries
                 # YITC_CROSS_LOG already set to the CANONICAL path — a redundant restatement of the
                 # default, not a redirect — so the rule-1 block's `if not env.get(...)` guard read
                 # it as a deliberate caller choice and handed the REAL store to every land-verify
                 # child. T-11445's own AC1 harness (dev-utilities/verify-no-live-journal-open.py)
                 # was consequently GREEN under an interactive controller and RED under dispatch:
                 # test_land.py 80 opens / 238 MB, test_pinned_verify.py 32 opens / 95 MB, traced to
                 # cli.py#_auto_file_kernel_deviations -> cross.read_events(CROSS_LOG_PATH). Same
                 # class as CODEX_HOME (T-11472): a half-applied sandbox whose answer depends on THE
                 # LAUNCHER'S SHELL, which is why it read as a flake rather than as a leak.
                 #
                 # AMBIENT-ONLY (`source_env is None`), deliberately. The two inputs mean different
                 # things: no `source_env` is "what a real spawn inherits", while a supplied one is a
                 # CALLER deliberately naming a store — and the rule-1 block's contract, pinned in
                 # both directions by tests/test_t11445_pinned_journal_slice.py
                 # ::test_an_explicit_cross_store_override_wins_over_the_harness_default, says such a
                 # caller wins. A blanket scrub would fix this leak by breaking that shipped
                 # assertion. An override applied as an OVERLAY after this builder returns
                 # (measure-land-verify-attribution.py#child_env, tests/_pinned_journal.py
                 # #env_for_child) is likewise untouched. Guard: tests/test_t11432_ambient_cross_log
                 # _scrub.py asserts BOTH legs, because either one alone is satisfiable by getting
                 # the other backwards.
                 *(("YITC_CROSS_LOG",) if source_env is None else ()))
    env = {k: v for k, v in base.items()
           if k != expected_session_ref_env and k not in _scrubbed}

    box = Path(box)
    home = box / "home"
    tmp = box / "tmp"
    for d in (home, tmp):
        d.mkdir(parents=True, exist_ok=True)
    # Isolated git config carrying a USABLE identity, so commit-bearing tests still commit while the
    # host's ~/.gitconfig (aliases / hooks / real name+email) is never read. GIT_CONFIG_GLOBAL is the
    # explicit redirect (independent of git's HOME interpretation); GIT_CONFIG_SYSTEM=/dev/null drops
    # /etc/gitconfig. Sandbox repos are same-owner, so no safe.directory concern.
    gitconfig = box / "gitconfig"
    # `core.fsync = none` (T-12184) — a DECLARED PIN, NOT a speedup. Say that plainly, because the
    # obvious reading of this line is the false one.
    #
    # MEASURED on the engine host before the line was written (git 2.43.0, /tmp on ext4, the shape
    # this builder makes): strace -f -c over `git init` + 10x(add+commit) counts ZERO fsync-family
    # syscalls under the DEFAULT config and zero under `none` — while `committed` costs 40,
    # `loose-object` 30 and `all` 60 (wall, N=40 commits x 7 reps, median: default 0.621s | none
    # 0.599s, -3.5% = noise | all 1.093s, +76%). The `all` arm is the differential control: the knob
    # IS honoured here and fsync here IS expensive when engaged. It is simply not engaged — this git
    # build's compiled-in default is effectively `none`, not the documented `committed`. So this line
    # removes no cost that exists today and MUST NOT be cited as having made the suite faster.
    #
    # WHAT IT DOES BUY is the same thing `GIT_CONFIG_SYSTEM=/dev/null` two lines below buys, and it
    # is bought for the same reason: the sandbox's answer stops depending on the HOST. Without it,
    # the fsync posture of every verify child is whatever compiled-in default the host's git happens
    # to carry — so a host git rebuilt or upgraded to the DOCUMENTED `committed` default would
    # silently start charging that 40-calls / +76% to every commit-bearing hermetic test, with no
    # diff to blame and nothing failing. That is this function's own recurring failure class, one leg
    # over: a half-applied sandbox whose answer depends on ambient state nobody declared (CODEX_HOME,
    # T-11472, 9 blocked lands over 4 days; YITC_CROSS_LOG, T-11445/T-11432). Sandbox repos are
    # throwaway by construction (SPEC-0041), so their durability is worth exactly nothing and `none`
    # is the honest declaration of that.
    #
    # `core.fsyncObjectFiles` is DELIBERATELY NOT SET, though T-12184's card prose prescribed it for
    # older-git compatibility: it is DEPRECATED as of git 2.43 and makes git print `warning:
    # core.fsyncObjectFiles is deprecated; use core.fsync instead` on EVERY invocation that reads
    # this config — stderr noise in every hermetic child, and a false-RED for any test asserting on
    # git stderr. `core.fsync` alone is honoured by git >= 2.36; below that this stanza is inert,
    # which is the correct failure direction for a pin.
    gitconfig.write_text(
        "[user]\n\tname = yitc-verify\n\temail = verify@yitc.invalid\n"
        "[init]\n\tdefaultBranch = main\n[commit]\n\tgpgsign = false\n"
        "[core]\n\tfsync = none\n",
        encoding="utf-8")
    env["HOME"] = str(home)
    env["TMPDIR"] = str(tmp)
    # T-12185: the lever is scoped to the run that SET it and must not reach a child. Left inherited,
    # a nested runner in the child would re-install it and point the child's temp base back OUT of
    # its box — the exact Rule 1 isolation `env["TMPDIR"]` above exists to give it.
    env.pop(_VERIFY_TMPDIR_ENV, None)
    for k in _HERMETIC_XDG_KEYS:
        p = box / "xdg" / k.lower()
        p.mkdir(parents=True, exist_ok=True)
        env[k] = str(p)
    env["GIT_CONFIG_GLOBAL"] = str(gitconfig)
    env["GIT_CONFIG_SYSTEM"] = os.devnull
    # T-12262 — THE VENUE PUBLICATION IS AN AMBIENT ROUTE SURFACE, and until this line it was the one
    # Rule-1 missed. Pointed at a path inside THIS test's box that is never created, so a verify child
    # resolves NO published venue and a fixture `land` takes the local path.
    #
    # MEASURED, not anticipated (2026-09-08). Running
    # tests/test_t10845_land_row_append_ledger_merge.py inside a detached worktree of a bare repo
    # printed `land: verify routed to the published venue <venue-ip> (legs=cand,pinned, full
    # suite)` and shipped the FIXTURE's own trees to the REAL shared box. On any tree predating
    # T-12247 (a223274e40, 04:53Z that day) `ship_trees` pushed `<shipped_main_sha>:refs/heads/main`,
    # so the fixture's two-commit «seed base»/«main side» history LANDED ON the box's shared
    # `refs/heads/main` at 08:50:38Z (commit e22fea4917, author `t <t@t>` — the fixture's own
    # repo-local identity). `main` is checked out nowhere in a bare clone, so the update SUCCEEDED
    # SILENTLY; every main-consulting test on the box then failed structurally with no assertion to
    # capture, and three candidates (T-12248 / T-12251 / T-12259) were charged with it.
    #
    # WHY THE EXISTING SANDBOX DOES NOT COVER IT — the reason this is a NEW line and not a duplicate
    # of one above. `venue.resolve_record_path` derives from `machine_settings.resolve_settings_path`
    # -> `cross.resolve_log_path` -> `host_paths.host_home()`, which is HOME-INDEPENDENT BY DESIGN
    # ("the home the ENGINE lives under", never `$HOME` — T-12024, so a peer uid still reaches the ONE
    # coordination store). Every other ambient route this function closes is reached through HOME or
    # through an env carrier; this one is reached through the ENGINE'S OWN PATH, which no HOME
    # replacement can move. The ambient `YITC_VENUE_RECORD` OVERRIDE would be scrubbed by the criterion
    # in this function's docstring; scrubbing it alone would leave the DEFAULT live, which is exactly
    # the half-applied sandbox that criterion exists to prevent (`YITC_CROSS_LOG`, T-11432, is the same
    # shape one leg over — there the ambient carrier restated the canonical path and the rule-1 block
    # read it as a deliberate choice). So the answer is a REDIRECT, like HOME/TMPDIR/XDG above, not a
    # scrub.
    #
    # FAIL-SAFE IN THE SAME DIRECTION AS THE REST OF THIS BUILDER: an absent record reads as "no venue
    # published", so a broken or unreadable artifact can only ever make a child MORE isolated, never
    # less. An explicit caller override still wins — a test that names its own record sets it
    # in-process or as an overlay applied after this builder returns (the same precedence
    # `YITC_EVENTS_PATH_DEFAULT` keeps below), so the venue tests are untouched.
    env[_VENUE_RECORD_ENV] = str(box / "venue-record-absent.json")
    if tf_name not in _REAL_STORE_ALLOWLIST:
        # Rule 1 real-store isolation via the LOW-PRECEDENCE, SCOPE-GUARDED default override (see the
        # YITC_EVENTS_PATH_DEFAULT block in bin/yitc-v2), NOT the top-precedence YITC_EVENTS_SINK: the
        # sink would override the in-process yitc.EVENTS_PATH redirect + explicit events_path= arg that
        # the suite's ~40 journal-readback tests rely on (T-0357 precedence). GUARD_ROOT = `cwd` (the
        # checkout being verified), so the override diverts ONLY the guarded checkout's own raw default
        # journal (a leaker that never redirects) — a nested CLI subprocess against its OWN sandbox
        # repo/worktree keeps its journal, so its read-gate anchor / claim / land still work. Real repo
        # events.jsonl protected AND every redirect/readback + nested-subprocess test keeps working with
        # no per-test change (the card's retire-per-test goal). Fail-closed: absence ⇒ the override is set.
        # BOTH vars or NEITHER: the default override is INERT without its guard root — that half-set
        # pair is exactly the T-11133 instrument defect, so they are written together, here, once.
        env["YITC_EVENTS_PATH_DEFAULT"] = str(box / "events.jsonl")
        # ABSOLUTE realpath (never str(cwd), which may be relative, e.g. "."): the guard is compared
        # in the CHILD against its own realpath(REPO_ROOT), and a relative guard would re-resolve
        # against the CHILD's cwd — a nested subprocess whose cwd IS its sandbox repo would then
        # spuriously match REPO_ROOT and wrongly engage the override (diverting its journal).
        env["YITC_EVENTS_GUARD_ROOT"] = os.path.realpath(str(cwd))
        # T-10401 — the FAIL-CLOSED backstop ABOVE the (low-precedence) default override on the line
        # above. That override only diverts the RAW DEFAULT journal, so it cannot catch a test that
        # names a live journal EXPLICITLY: lib/dispatch.py appends with
        # `events_path=_main_worktree(REPO_ROOT)/"events.jsonl"`, which outranks BOTH the default
        # override AND an in-process yitc.EVENTS_PATH patch — that is how test_dispatch leaked 80+
        # phantom rows into the real journal, waking armed `dispatch --watch` monitors. This var arms
        # the guard at the single write path (lib/events.append_event): an append to any LIVE journal
        # RAISES, so the leaking test FAILS instead of silently polluting an append-only log. Same
        # allowlist gate as the override: an allowlisted Class-B test keeps its sanctioned real-store
        # touch. `_live_journals()` covers this checkout AND main's (a worktree verify resolves
        # _main_worktree() to MAIN — the journal the leak actually hit).
        env["YITC_TEST_JOURNAL_GUARD"] = os.pathsep.join(str(p) for p in _live_journals(cwd))
        # T-11445 / SPEC-0190 rule 9 — the SHARED coordination store gets the SAME rule-1 treatment as
        # the journal beside it, because it IS the same journal mechanism (SPEC-0084 rule 5, a
        # permitted second INSTANCE) with the same unbounded growth. It was measured as the single
        # largest remaining reader after the journal was bounded: 39 of the 48 classified files read
        # it — 19.5 GB across one run — none of them asserting anything about its contents. They pay
        # it because the filing/land verbs fold it for report-only cross-territory hints.
        # A PRIVATE EMPTY store, not a slice: a test that IS about cross stands up its own store (and
        # its own explicit YITC_CROSS_LOG overrides this, since it is written into the base env), while
        # for everyone else "no coordination items overlap this card" is the correct answer. Same
        # allowlist gate as the journal redirect above — an allowlisted real-store touch keeps the
        # real store.
        # ONLY when the child env does not already name one: an explicit override is a caller's
        # deliberate choice of store and must WIN, exactly as the paragraph above says it does
        # (audit-post finding — the first draft overwrote it, contradicting its own contract).
        # T-11432 narrowed what "already names one" MEANS, and the narrowing is what makes this
        # guard honest: an AMBIENT YITC_CROSS_LOG (inherited from the launching shell) is scrubbed
        # in the base-scrub above and can no longer reach this line, because it is not a caller's
        # choice at all — under dispatch it arrived set to the CANONICAL path and silently disarmed
        # this whole redirect. What survives to be honoured here is a store a CALLER named, via
        # `source_env=` or an overlay applied after this builder returns.
        if not env.get("YITC_CROSS_LOG"):
            cross_store = box / "coordination.jsonl"
            cross_store.write_text("", encoding="utf-8")
            env["YITC_CROSS_LOG"] = str(cross_store)
        # T-10081 seed floor: this diverted box journal is FRESH, so the audience-seed read-gate
        # (`_require_seed_read`, checked at the main() dispatch chokepoint for every governed/mutating
        # verb — SPEC-0050 §8) would REFUSE every such verb a test drives against the guarded checkout.
        # Establish a valid session context in the box journal — a session_started anchor + a cli:seed
        # receipt under the ref the child resolves (its first-present SESSION_REF carrier) — the harness
        # analog of `session start` (the box already establishes an isolated HOME / git-identity / TMPDIR;
        # a valid session context is the same class of "make the box a place a governed verb can run").
        # NON-allowlisted only (inside this block): an allowlisted test keeps the REAL journal, which
        # carries the running session's own receipt. The gate's OWN tests control their journal
        # in-process (monkeypatched EVENTS_PATH), so a box-default seed never masks their refusal cases.
        # `cli:seed` mirrors gates.SEED_READ_NODE_ID (hardcoded like tests/_read_gate.py's sentinel —
        # the same value, drift-obvious); ts far in the past so any real event the verb appends is
        # in-window (receipt ts >= session_started ts; SPEC-0050 §2).
        # T-10149 (SPEC-0137 Rule 6a) — give this NON-allowlisted box a CLEAN, per-box v2-OWNED
        # identity so a test resolves ITS OWN box id, never the launcher's leaked session ref.
        # Post-T-10137 `_resolve_session_ref` is FAIL-CLOSED with YITC_SESSION_REF the HIGHEST-
        # precedence carrier, so an inherited launcher carrier would (a) key the box journal seed
        # below AND (b) win selector-1b in the keyer — resolving the LAUNCHER's identity inside the
        # box (the fu_54c5905adf9f leak; a fail-closed/foreign-refused test then sees the launcher id
        # resolve instead of failing). So SCRUB every launcher session-ref + provider transcript
        # carrier from THIS box env (the T-10152 `SUBENV_SCRUB_CARRIERS` union — the identity carrier
        # `SESSION_REF_ENV_VARS` PLUS the D-0030 provider transcript carriers; single-SoT via injection;
        # falls back to the hardcoded mirror only if unset) and MINT a fresh
        # v2-named uuid as the box's own YITC_SESSION_REF. Scrubbing the PROVIDER carriers is what makes
        # the box CURRENT-EPOCH ANCHORED: the box journal is seeded UNDER the fresh id (session_started +
        # cli:seed receipt), and with NO inherited provider carrier `_session_epoch()` computes epoch 0,
        # matching the receipt → the fail-closed keyer honors the backed carry (selector 1b) and never
        # falls through to the ambient worktree stamp. (Rule 8b removed the provider carriers from the
        # IDENTITY registry, so the union — not the bare registry tuple — is what preserves this epoch-0
        # hermeticity.) This is the hermetic-by-default generalization of the T-0579 EXPECTED-only scrub,
        # now that the keyer is carrier-precedence-first + fail-closed. ALLOWLISTED tests are UNTOUCHED
        # (they keep the launcher carriers + real journal and assert against the running session's own
        # ambient anchor) — the scrub is scoped to isolated boxes.
        for _carrier in (scrub_carriers
                         or ("YITC_SESSION_REF", "CLAUDE_CODE_SESSION_ID", "CODEX_THREAD_ID")):
            env.pop(_carrier, None)
        _seed_ref = str(uuid.uuid4())
        env["YITC_SESSION_REF"] = _seed_ref
        with open(box / "events.jsonl", "w", encoding="utf-8") as _bf:
            _bf.write(json.dumps({"ts": "2000-01-01T00:00:00Z", "type": "session_started",
                                  "session_ref": _seed_ref, "data": {}}) + "\n")
            _bf.write(json.dumps({"ts": "2000-01-01T00:00:01Z", "type": "cli_invoked",
                                  "session_ref": _seed_ref,
                                  "data": {"node_id": "cli:seed", "verb": "session start"}}) + "\n")
    return env
