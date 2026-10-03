"""bin/lib/land_reservation.py — the land RESERVATION family (card C5b, T-12709), relocated here
byte-identical from `bin/lib/worktree.py` (plan extract-the-13-over-budget-bin-lib-modules-into-le
§Extraction map C5b; lessons/library-extraction.md — Design B full inject-residue seam).

WHAT LIVES HERE: the queued pre-merge (`_queued_premerge_*`, `_premerge_*`, `_QueuedPremergeStop`),
the land-queue row / attempt helpers (`_land_queue_row_attempt_key`, `_land_queue_jump_reason`,
`_land_branch_attempt_rows`), the queued-land liveness classifier + heartbeat staleness, the
`land --withdraw` arm (`land_withdraw_arm`, `_land_write_withdraw_request`), and the held-turn
worker-binding arms (`_arm_worker_land_pdeathsig`, `_arm_worker_liveness_watchdog`,
`_worker_liveness_lost`, `_kill_this_land`, `_arm_external_termination_record`) — with the 13
constants exclusive to them, module-local.

THE SEAM: every body is a VERBATIM copy of its host original; every non-stdlib, non-moved free name
arrives as a keyword-only inject the host residue supplies from ITS live globals at call time
(`@functools.wraps(land_reservation.<sym>)` residues in `bin/lib/worktree.py`), so `-C` rebinds and
`monkeypatch.setattr(yitc, ...)` stay honoured, and a moved sibling is reached through its host
residue (never module-locally) so the same patch surface covers every call. Body-level
`globals()[...]` defaults are re-supplied by the residue in HOST scope. This leaf imports lower
leaves + stdlib only — NEVER `lib.worktree` (tests/test_bin_lib_leaf_no_host_import.py).

Spec-less by design (SPEC-0005 admission test): a byte-identical relocation mints no standing rule —
the governing specs (SPEC-0180, SPEC-0184, SPEC-0161) keep their homes and re-point their anchors.
"""
from __future__ import annotations

import os
import re
import sys
import time
from pathlib import Path

from lib import state


# T-12150 — the QUEUED PRE-MERGE knobs. A land parked in the reservation wait re-merges main into
# its own worktree on a throttled cadence, so it tracks main while it queues instead of meeting an
# hour of drift at acquisition. Three independent bounds, each answering a different objection:
_LAND_QUEUED_PREMERGE_INTERVAL_SEC = 120.0   # THROTTLE — at most one tick per this many seconds.
                                             # ~120 s is what AC1 specifies as the min-wait BETWEEN
                                             # ticks, so the default matches the AC as written rather
                                             # than halving it after the first wait (T-12150 r10).


_LAND_QUEUED_PREMERGE_INTERVAL_ENV = "YITC_LAND_QUEUED_PREMERGE_SECS"


_LAND_QUEUED_PREMERGE_MIN_WAIT_SEC = 120.0   # MIN-WAIT — no tick at all below this wait, so a short
                                             # contended wait (the regime where acquisition ordering
                                             # is actually in play) is BYTE-IDENTICAL to today.


_LAND_QUEUED_PREMERGE_MIN_WAIT_ENV = "YITC_LAND_QUEUED_PREMERGE_MIN_WAIT"


_LAND_QUEUED_PREMERGE_ENV = "YITC_LAND_QUEUED_PREMERGE"   # `0` = kill switch (the AC1 differential).


def _queued_premerge_enabled() -> bool:
    """T-12150 — the kill switch. `YITC_LAND_QUEUED_PREMERGE=0` disables every queued pre-merge tick
    AND the step-2 consumption that reads its record, so the land runs EXACTLY as it did before this
    card. That is what makes the AC1/AC2 differentials differential: the same fixture with the switch
    off must reproduce today's behaviour."""
    raw = os.environ.get(_LAND_QUEUED_PREMERGE_ENV)
    return not (raw is not None and raw.strip() == "0")


def _queued_premerge_interval(*, _premerge_env_float) -> float:
    """T-12150 — seconds between queued pre-merge ticks. Test seam via
    `_LAND_QUEUED_PREMERGE_INTERVAL_ENV` (set it tiny), the same idiom as
    `_land_reservation_park_limit_seconds`. A non-numeric or <=0 override falls back to the default:
    this is a THROTTLE, so a stray value must never be able to turn it into an unthrottled loop."""
    return _premerge_env_float(_LAND_QUEUED_PREMERGE_INTERVAL_ENV, _LAND_QUEUED_PREMERGE_INTERVAL_SEC)


def _queued_premerge_min_wait(*, _premerge_env_float) -> float:
    """T-12150 — the wait a land must ALREADY have served before its first pre-merge tick. Same env
    idiom and same fail-safe as `_queued_premerge_interval`: a <=0 override falls back to the
    default rather than removing the floor that keeps short contended waits untouched."""
    return _premerge_env_float(_LAND_QUEUED_PREMERGE_MIN_WAIT_ENV, _LAND_QUEUED_PREMERGE_MIN_WAIT_SEC)


def _premerge_env_float(env: str, default: float) -> float:
    """The shared numeric-override read for the two knobs above — ONE parser, not two copies."""
    raw = os.environ.get(env)
    if raw is None or not raw.strip():
        return default
    try:
        v = float(raw)
    except ValueError:
        return default
    return v if v > 0 else default


class _QueuedPremergeStop(Exception):
    """T-12150 — the raising `_die` substitute for a QUEUED pre-merge tick.

    `_update_from_main` / `_fold_trailing_bookkeeping` signal refusal by calling their injected
    `_die`, which in `land` is SystemExit. A pre-merge tick runs while the branch is PARKED in the
    reservation wait, where the HELPER must not end the land itself: it only REPORTS. So the tick
    injects a `_die` that raises THIS instead, and `_queued_premerge_from_main` converts it to a
    RECORD. What the land then does with a `conflict` record is the CALLER's decision — since T-13345
    a blocking `merge-non-union-conflict` makes the caller withdraw at once."""

    def __init__(self, msg: str, abort_class=None):
        super().__init__(msg)
        self.msg = msg
        self.abort_class = abort_class


def _queued_premerge_from_main(W: "Path", branch: str, *, _run_git_cap,
                               _fold_trailing_bookkeeping, _update_from_main,
                               _BOOKKEEPING_ALLOWLIST, _is_yitc_session_state,
                               _DERIVED_MERGE_ARTIFACTS, _dedup_events, write_text_atomic,
                               _anchor_signature_of_text=None) -> dict:
    """T-12150 — ONE queued pre-merge tick: bring `W` up to date with `main` WHILE THE BRANCH IS
    STILL PARKED in the land-reservation wait, and REPORT rather than abort. Never raises.

    WHY. `land` merges main into the branch only AFTER the serialized reservation is acquired
    (`_land_integrate` step 2), so the WHOLE reservation wait sits between the branch's last commit
    and its merge from main. Measured 2026-09-05: waits of 45-111 minutes, and three
    `merge-non-union-conflict` aborts (78.6 / 110.8 / 44.3 min) on pins a sibling had just landed —
    each sending the branch to the queue tail after it had already paid the wait. Running the same
    merge from INSIDE the park means the branch tracks main as it moves, so the merge at acquisition
    is a no-op. A conflict is met while still parked; this helper only RECORDS it, and the caller
    (T-13345) leaves the queue at once on a blocking `merge-non-union-conflict` rather than waiting
    to abort at acquisition.

    NO MERGE LOGIC OF ITS OWN (CHARTER §P1 F1). The two steps are exactly the two `land` and
    `worktree sync` already run — `_fold_trailing_bookkeeping` (without it git refuses to merge over
    the `events.jsonl` a peer verb appended during the wait) then the SHARED `_update_from_main`,
    which owns the fail-closed per-path auto-resolve classification. This is the THIRD caller of one
    implementation, never a second one.

    IT IS LABELLED `land`, NOT a label of its own. The label prefixes `_update_from_main`'s abort
    MESSAGES and selects its recovery pointer, and this merge IS the land's own merge — simply run
    earlier. A distinct label would make a CONSUMED conflict abort with different text from the
    identical abort today, which is exactly what AC2 forbids; it would also add a second
    bookkeeping-generator verb prefix (the T-11769 roster). The stderr lines below still say
    «queued pre-merge», so the diagnostics stay distinguishable where that costs nothing.

    IT TAKES NO LOCK AND TOUCHES ONLY `W`. It never opens, writes or locks the reservation path, so
    the acquisition mechanism stays the unordered flock contention it is today and the SPEC-0184
    rule-9 order is untouched.

    THE RECORD (`outcome` is the whole contract; the caller keys on it and nothing else):
      `current`  — main is not ahead: NO merge ran. The cheap, overwhelmingly common tick.
      `merged`   — the merge ran and succeeded (possibly after a mechanical auto-resolve).
      `conflict` — `_update_from_main` refused. `abort_class` / `message` carry ITS verdict verbatim,
                   so a caller consuming this record aborts with the identical class and text.
      `error`    — anything else went wrong. Never consumed; the caller falls back to its own merge.
      `dirty`    — the tree could NOT be PROVEN clean afterwards. The caller must disable all further
                   ticks for this land, so land's own steps meet a state no tick can have touched.

    CLEANUP IS GUARANTEED ON EVERY NON-SUCCESS PATH — AND A FAILED CLEANUP STOPS THE LAND. A
    `finally`-scoped `_ensure_no_merge_in_progress` aborts any merge left in progress and then
    RE-CHECKS that both MERGE_HEAD and the unmerged-path set are gone; failing that proof downgrades
    the record to `dirty` AND carries `unsafe_state` — a short reason naming what survived.
    `dirty` never silently overwrites a `conflict`'s class — it only ever ADDS the
    disable-further-ticks signal.

    WHY `unsafe_state` IS NOT MERELY «disable later ticks» (audit-post r5, HIGH). Disabling ticks
    only promises that NO FURTHER TICK touches the tree; it says nothing about the tree land's own
    step 2 is then handed. A worktree still carrying MERGE_HEAD or unmerged paths is one where step
    2's `git merge` would either refuse or, worse, commit a half-resolved index as if it were the
    branch's own content. Restoring and PROVING the exact pre-tick state is precisely what already
    failed here — that is what this record MEANS — so the honest option is the other one: land STOPS
    before step 2 with an explicit unsafe-state abort (`queued-premerge-unsafe-state`), main
    untouched and the worktree left exactly as found for a human to inspect."""
    rec: dict = {"branch": branch, "outcome": "error"}

    def _ensure_no_merge_in_progress():
        """`None` iff the tree is PROVABLY free of an in-progress merge; otherwise a SHORT REASON
        naming WHAT survived the cleanup (MERGE_HEAD, or the unmerged paths). Never raises.

        THE REASON IS THE POINT (audit-post r5, HIGH). A bare False said only «not proven clean»,
        which the caller could do nothing with but disable later ticks. Land now STOPS before step 2
        on this state, and an abort that cannot say WHICH contamination it met is not actionable —
        so the proof failure carries its own evidence."""
        try:
            mh = _run_git_cap(["rev-parse", "-q", "--verify", "MERGE_HEAD"], W)
            if getattr(mh, "returncode", 1) == 0:
                ab = _run_git_cap(["merge", "--abort"], W)
                if getattr(ab, "returncode", 1) != 0:
                    return (f"`git merge --abort` FAILED (rc={getattr(ab, 'returncode', None)!r}): "
                            f"{((getattr(ab, 'stderr', '') or '').strip() or 'no stderr')[:200]}")
            mh2 = _run_git_cap(["rev-parse", "-q", "--verify", "MERGE_HEAD"], W)
            if getattr(mh2, "returncode", 1) == 0:
                return "MERGE_HEAD still present after `git merge --abort`"
            un = _run_git_cap(["diff", "--name-only", "--diff-filter=U"], W)
            if getattr(un, "returncode", 1) != 0:
                return (f"could not list unmerged paths "
                        f"(rc={getattr(un, 'returncode', None)!r})")
            paths = [ln for ln in (getattr(un, "stdout", "") or "").splitlines() if ln.strip()]
            if paths:
                return "unmerged paths remain: " + ", ".join(paths[:8])
            return None
        except Exception as exc:               # noqa: BLE001 — a cleanup that cannot run is not clean
            return f"cleanup could not run: {type(exc).__name__}: {exc}"

    def _die_raises(msg, abort_class=None, **_kw):
        raise _QueuedPremergeStop(msg, abort_class)

    clean_success = False
    try:
        # THE TIP MUST BE PROVEN (audit-post r11, HIGH sibling) — `_run_git_cap` does not raise on a
        # nonzero git, so the rc is checked BEFORE the stdout is believed.
        _rp = _run_git_cap(["rev-parse", "main"], W)
        tip = (getattr(_rp, "stdout", "") or "").strip()
        if getattr(_rp, "returncode", 1) != 0 or not re.fullmatch(r"[0-9a-f]{7,64}", tip):
            rec["message"] = ("could not resolve the main tip "
                              f"(rc={getattr(_rp, 'returncode', None)!r}, stdout={tip!r})")
            return rec
        rec["tip"] = tip
        # THE COUNT MUST BE PROVEN, NOT ASSUMED (audit-post finding, HIGH). `_run_git_cap` does not
        # raise on a nonzero git; reading `.stdout or "0"` turned a FAILED or empty `rev-list` into
        # "0 behind" — a CONSUMABLE `current` record, which step 2 then stands in for by SKIPPING a
        # merge that was in fact still owed. `current` is the one outcome consumed with no merge at
        # all, so it is the one that may never be inferred from an absent answer. A bad return code,
        # empty stdout, or non-numeric output now yields the NON-consumable `error`, and land runs
        # its own step-2 merge exactly as today (fail-open).
        # AGAINST THE CAPTURED TIP, not the symbolic name — the count, the merge and the recorded
        # watermark must all describe ONE object (audit-post r11, MED).
        _cnt = _run_git_cap(["rev-list", "--count", f"HEAD..{tip}"], W)
        _cnt_out = (getattr(_cnt, "stdout", "") or "").strip()
        if getattr(_cnt, "returncode", 1) != 0 or not re.fullmatch(r"\d+", _cnt_out):
            rec["message"] = ("could not count commits behind main "
                              f"(rc={getattr(_cnt, 'returncode', None)!r}, stdout={_cnt_out!r})")
            return rec
        behind = int(_cnt_out)
        rec["behind_before"] = behind
        if behind == 0:
            # NOT a merge that happened to be empty — no merge ran at all. This is the arm the
            # main-tip watermark exists to make the common case of.
            rec["outcome"] = "current"
            clean_success = True
            return rec
        _fold_trailing_bookkeeping(W, branch, refuse_nonfoldable=True,
                                   msg_prefix="land",
                                   _run_git_cap=_run_git_cap, _die=_die_raises,
                                   _BOOKKEEPING_ALLOWLIST=_BOOKKEEPING_ALLOWLIST,
                                   _DERIVED_MERGE_ARTIFACTS=_DERIVED_MERGE_ARTIFACTS,
                                   _is_yitc_session_state=_is_yitc_session_state)
        resolved_sink: dict = {}
        # THE PHASE MARK. Everything above this line is PRE-MERGE setup whose refusal is not a merge
        # verdict (the fold); everything from here on is the merge itself. The caller consumes and
        # watermarks ONLY outcomes produced from here, so a fold refusal can never be mistaken for a
        # conflict `_update_from_main` reached (audit-post finding).
        rec["merge_attempted"] = True
        _update_from_main(W, label="land", source=tip, _run_git_cap=_run_git_cap,
                          _die=_die_raises, _DERIVED_MERGE_ARTIFACTS=_DERIVED_MERGE_ARTIFACTS,
                          _dedup_events=_dedup_events, write_text_atomic=write_text_atomic,
                          _anchor_signature_of_text=_anchor_signature_of_text,
                          _resolved_out=resolved_sink)
        rec["outcome"] = "merged"
        if resolved_sink.get("paths"):
            rec["resolved"] = list(resolved_sink["paths"])
            rec["resolved_kinds"] = dict(resolved_sink.get("kinds") or {})
        clean_success = True
        return rec
    except _QueuedPremergeStop as stop:
        # A stop raised BEFORE the merge began is NOT a merge conflict — it is the fold refusing.
        # Classify it as `error`, which is non-consumable and non-watermarking by construction, so
        # land still owes (and runs) its own step-2 merge.
        rec["outcome"] = "conflict" if rec.get("merge_attempted") else "error"
        rec["message"] = stop.msg
        if stop.abort_class:
            rec["abort_class"] = stop.abort_class
        return rec
    except Exception as exc:                   # noqa: BLE001 — the tick never raises into the caller
        rec["outcome"] = "error"
        rec["message"] = f"{type(exc).__name__}: {exc}"
        return rec
    finally:
        if not clean_success:
            _unsafe = _ensure_no_merge_in_progress()
            if _unsafe is not None:
                # The tree could not be PROVEN clean. Say so ADDITIVELY — a conflict's own class and
                # message survive, because the caller consuming a conflict must still see the verdict
                # `_update_from_main` actually reached.
                rec["dirty"] = True
                rec["unsafe_state"] = _unsafe
                rec["outcome"] = "dirty" if rec.get("outcome") != "conflict" else rec["outcome"]


def _premerge_consumable(W, state: dict, *, _run_git_cap, _queued_premerge_enabled):
    """T-12150 (plan step 3c) — is the recorded queued pre-merge CONSUMABLE by land's step 2?
    Returns the consumable record, or `None` meaning «run step 2's own merge exactly as today».

    ONE admission point, FAIL-OPEN BY CONSTRUCTION — every uncertainty returns `None`, so this can
    only ever remove a merge that is PROVABLY redundant, never a needed one. It admits only when
    ALL of the following hold:
      - the kill switch is not set (`YITC_LAND_QUEUED_PREMERGE=0` disables consumption too, which is
        what makes the AC1 differential differential);
      - ticks were not disabled mid-land (a `dirty` tree means land's own steps must meet a state no
        tick can have touched);
      - a tick actually ATTEMPTED a tip, and that attempt's outcome is one this step can stand in
        for — `merged` / `current` (consumed as success) or `conflict` (consumed as the SAME abort).
        An `error` or `dirty` outcome is deliberately NOT consumable;
      - `main` RIGHT NOW still stands at exactly that attempted tip. This is the whole proof: the
        pre-merge ran the same `_update_from_main` against the same tip in the same worktree, so
        repeating it could not reach a different answer. Any advance of main since — the fail-open
        arm — means step 2 has genuinely new work and runs its own merge.
    Pure and total: never raises, never writes, takes no lock."""
    if not _queued_premerge_enabled() or state.get("disabled"):
        return None
    tip = state.get("attempted_tip")
    outcome = state.get("attempted_outcome")
    if not tip or outcome not in ("merged", "current", "conflict"):
        return None
    # Belt for the phase rule the tick already applies when it sets the watermark: only an outcome
    # the merge path PRODUCED stands in for the merge (audit-post finding). `current` qualifies with
    # no merge because it is the proof none was needed.
    last = state.get("last") or {}
    if outcome != "current" and not last.get("merge_attempted"):
        return None
    # THE CURRENCY PROOF MUST BE PROVEN, NOT ASSUMED (audit-post r11, HIGH). `_run_git_cap` does not
    # raise on a nonzero git, so reading `.stdout` alone let a FAILED `rev-parse main` whose stdout
    # happened to equal `attempted_tip` (a cached/echoed value, a partially-written stream) admit the
    # consumption — the ONE step that lets land SKIP its own merge. That is a fail-OPEN on the proof
    # itself: the skip is admitted without ever having learned main's current tip. The rc must be 0
    # AND the stdout must be a syntactically valid SHA before the comparison is meaningful; anything
    # else falls through to step 2's own merge exactly as today (fail-open in the SAFE direction).
    try:
        _rp = _run_git_cap(["rev-parse", "main"], W)
    except Exception:                          # noqa: BLE001 — cannot prove currency: fall open
        return None
    if getattr(_rp, "returncode", 1) != 0:
        return None                            # the tip was never learned: nothing is proven
    now_tip = (getattr(_rp, "stdout", "") or "").strip()
    if not re.fullmatch(r"[0-9a-f]{7,64}", now_tip):
        return None                            # not a tip at all: nothing is proven
    if now_tip != tip:
        return None                            # main advanced: step 2 has real work (fail-open arm)
    rec = dict(state.get("last") or {})
    rec["tip"] = tip
    rec["outcome"] = outcome
    return rec


def _premerge_summary(state: dict):
    """T-12150 (plan steps 4+6) — the ADDITIVE `queued_premerge` record carried on the
    `waiting_for_land_reservation` heartbeat and on `land_completed`. Returns `None` until a tick has
    actually run, so every land that never pre-merges leaves both rows byte-identical to today (the
    additive-key growth `rebaselining` / `queued_since_s` / `attempt` already ride — SPEC-0025).

    Counts, the last record, and `premerge_block_ms` — the MEASURED wall-clock ticks spent off the
    reservation poll, max and total. That measurement is the point: the plan's min-wait bound
    replaced an unproven "fairness is unchanged" claim with a cost that is recorded rather than
    asserted, and this is where it is recorded. Pure: reads, never writes."""
    if not state or not (state.get("ticks") or state.get("base_errors")
                         or state.get("tip_read_errors")):
        return None
    out = {"ticks": int(state.get("ticks", 0)),
           "merges": int(state.get("merges", 0)),
           "conflicts": int(state.get("conflicts", 0)),
           "premerge_block_ms": {"max": int(state.get("block_ms_max", 0)),
                                 "total": int(state.get("block_ms_total", 0))}}
    if state.get("base_errors"):
        # The fail-open arm of the base capture — a tick that could not learn the pre-merge base and
        # therefore did NOT merge and set NO watermark. Recorded so the row shows a pre-merge that
        # was declined rather than a pre-merge that never happened (audit-post r5, MED).
        out["base_errors"] = int(state["base_errors"])
    if state.get("tip_read_errors"):
        # Admitted ticks whose `rev-parse main` failed or raised — they merged nothing and set no
        # watermark, but they DID spend poll time, and `premerge_block_ms` above is what records it
        # (audit-post r11, MED: without this counter the whole summary read `None` on that path).
        out["tip_read_errors"] = int(state["tip_read_errors"])
    if state.get("watermark_skips"):
        out["watermark_skips"] = int(state["watermark_skips"])
    if state.get("attempted_tip"):
        out["attempted_tip"] = state["attempted_tip"]
        out["attempted_outcome"] = state.get("attempted_outcome")
    if state.get("forced_ran"):
        out["forced_tick_ran"] = True
    if state.get("disabled"):
        out["disabled"] = True
    if state.get("aborted_while_queued"):
        # T-13345 — the land LEFT THE QUEUE on a blocking conflict a queued tick met, instead of
        # waiting to abort at acquisition. Step 2 never ran, so `consumed_by_step2` stays absent.
        out["aborted_while_queued"] = True
    if state.get("unsafe_state"):
        # The reason cleanup could not restore the pre-tick state — the same string the
        # `queued-premerge-unsafe-state` abort names, so the row and the abort agree.
        out["unsafe_state"] = state["unsafe_state"]
    if state.get("consumed"):
        # The step-2 skip actually taken — what "lands without a second merge" looks like in the
        # journal, rather than a claim the row leaves the reader to infer.
        out["consumed_by_step2"] = state["consumed"]
    last = state.get("last")
    if last:
        out["last"] = {k: v for k, v in last.items() if k != "branch"}
    return out


def _premerge_reservation_disposition(state: dict) -> str:
    """T-12150 (plan step 6, AC2's named new field) — how this land's reservation stood in relation
    to the merge conflict that aborted it. Reverting the queued pre-merge makes EVERY abort row read
    `first_met_at_acquisition`, which is exactly the AC2 differential.

    KEYED TO THE CONFLICT THIS ABORT CARRIES, never to a lifetime count: `conflict_consumed_tip` is
    written at the ONE point a queued conflict actually becomes this land's abort. A queued conflict
    at tip A followed by a clean attempt at tip B therefore leaves a later abort uncoloured. The
    caller attaches this ONLY to a merge-conflict abort, for the same reason.

    AND KEYED TO THE ATTEMPT'S ORIGIN. `surfaced_while_queued` requires that a QUEUED tick found the
    conflict. A short contended wait runs no queued tick at all, so a conflict there is first met by
    the FORCED post-acquisition tick — at which point the branch already HELD the reservation, which
    is the opposite of what this value asserts. Consumption alone cannot tell those apart, so the
    origin (`conflict_consumed_forced`) is carried with the tip.

    `surfaced_while_queued` — a queued pre-merge had ALREADY reported this conflict, so the branch
    did not take the reservation for a doomed merge.
    `first_met_at_acquisition` — the pre-change shape: the conflict was first met after the
    reservation was acquired.
    The flock's lifetime IS the land process, so the reservation is released at process exit either
    way; this field records WHEN the conflict was met, never a retention claim."""
    st = state or {}
    # BOTH conditions: a conflict this abort actually consumed, AND one a QUEUED tick found. A
    # conflict first met by the forced post-acquisition tick is `first_met_at_acquisition` — the
    # branch already held the reservation when it was discovered, which is the whole distinction
    # this field exists to draw (audit-post r4).
    return ("surfaced_while_queued"
            if st.get("conflict_consumed_tip") and not st.get("conflict_consumed_forced")
            else "first_met_at_acquisition")


def _land_queue_row_attempt_key(row) -> "str | None":
    """The ATTEMPT KEY a `journal.LAND_QUEUE_WAIT_TYPES` row RECORDS — `"<pid>-<starttime>"` — or
    None when the row does not record one. Accepts the whole row or its bare `data` dict.

    READS THE ROW AND NOTHING ELSE. There is no /proc fallback here, and adding one would reintroduce
    the entire defect: a row that does not carry `pid_starttime` is a row whose attempt identity was
    never recorded, and the honest answer to «which attempt is this?» is then None. Minting
    `f"{pid}-{starttime}"` out of CURRENT /proc state would answer with the identity of whatever
    process happens to hold that pid NOW — which, after the recorded process exited and the pid was
    reused, is a DIFFERENT attempt wearing the same number. That is consult finding B1 exactly, and
    it is why this function is pure.

    Both halves must be POSITIVE INTS. `bool` is rejected explicitly because `isinstance(True, int)`
    is True in Python, and `"True-True"` is not an attempt.

    PURE: it decides nothing, consumes nothing and mutates nothing. Its consumers are the successor
    units (T-12257's request marker, T-12258's admission-seam probe); nothing in this diff calls it
    at a decision point."""
    data = row.get("data") if isinstance(row, dict) and isinstance(row.get("data"), dict) else row
    if not isinstance(data, dict):
        return None
    vals = []
    for key in ("pid", "pid_starttime"):
        v = data.get(key)
        if isinstance(v, bool) or not isinstance(v, int) or v <= 0:
            return None
        vals.append(v)
    return f"{vals[0]}-{vals[1]}"


def _land_write_withdraw_request(main_wt: "Path | None", branch: "str | None", target_attempt_key,
                                 *, session_ref=None, _land_withdraw_request_path=None) -> bool:
    """Publish «withdraw the land attempt `<target_attempt_key>` on `<branch>`». Returns whether the
    request is on disk.

    NO KEY, NO WRITE. `target_attempt_key` is REQUIRED and the call REFUSES a None, an empty or a
    malformed one — writing NOTHING and creating NO directory. This is the fail-closed direction, and
    its worst outcome is a withdrawal that does not happen. The alternative — minting a key from
    current /proc state when the caller could not supply one — is consult finding B1 verbatim: it
    would address whatever process happens to hold that pid NOW, which after a reuse is a DIFFERENT
    attempt wearing the same number.

    RETURNS False RATHER THAN RAISING, the exception discipline of its sibling
    `_land_write_yield_offer` — but "best-effort" here describes THAT and never the reporting: the
    return value is load-bearing at the CLI (T-12243's arm refuses non-zero on False), so a failed
    write must be visible as a failure and not swallowed into an optimistic True.

    THE CONTENT IS FOR A HUMAN READING THE SIDECAR — `<branch>`, the requesting `<session_ref>`, and
    the `<target_attempt_key>` — and NOTHING in this family parses it back. `_land_withdraw_requested`
    asks `exists()` and nothing else, so a truncated or garbled file can never mislead a reader: the
    address is the filename, and the body is a note."""
    _land_withdraw_request_path = (_land_withdraw_request_path
                                   or globals()["_land_withdraw_request_path"])
    br = (branch or "").strip()
    try:
        path = _land_withdraw_request_path(main_wt, br, target_attempt_key)
        if not br or path is None:
            return False
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{br}\n{session_ref or ''}\n{target_attempt_key}\n", encoding="utf-8")
        return path.exists()
    except Exception:                  # noqa: BLE001 — a failed write REPORTS False (see docstring)
        return False


def _land_branch_attempt_rows(rows, branch: "str | None", *, _LAND_QUEUE_WAIT_TYPES):
    """The branch's journal rows TRIMMED TO ITS CURRENT LAND ATTEMPT, plus the queue row that
    defines that attempt: `(attempt_rows, newest_queue_row)`.

    THE TRIM IS THE WHOLE POINT, and without it the fold answers about the WRONG ATTEMPT.
    `_classify_queued_land_liveness` lets TERMINAL rows win over everything — by design, since a land
    that reached a token is decided whatever its heartbeats say. So an OLDER attempt's
    `land_completed`, left in the row set, makes a branch that is queued RIGHT NOW classify as
    `completed`, and the arm answers «nothing to withdraw» about a land it could have withdrawn. A
    branch is re-landed routinely (an ff-race retry, a re-land after an ABORT), so this is the
    ordinary case and not an edge one.

    THE CUT is every branch row with `ts >= the ts of the NEWEST queue-wait row`. That row is the
    START of the current attempt in the durable record: a land emits its first
    `_LAND_QUEUE_WAIT_TYPES` heartbeat before it can wait, be admitted, or terminate, so nothing
    belonging to this attempt precedes it and everything preceding it belongs to an older one.

    THE ROW ITSELF is returned and not merely the cut, because two later steps read it and must read
    the SAME one: the attempt key (`_land_queue_row_attempt_key`) and the no-later-attempt interlock.
    Resolving it twice would let the two disagree — the un-checkable-attestation shape T-12280's own
    consult finding C4 removed at the sibling seam.

    BRANCH ATTRIBUTION, stated as the bound it is rather than papered over: a row belongs to the
    branch when `data.branch` matches; OR, for a row carrying NO `data.branch` at all, when its
    top-level `task_id` equals the branch's task id. That second clause exists SOLELY for
    `land_terminated_externally`, whose measured payload is `{signal, pid, reason}` and carries no
    branch. It follows that for a `work/<slug>` branch — which has no task id — such a row is NOT
    attributable at all, and the fold judges that land on its remaining rows. That is a real limit of
    the shipped payload, not of this reader, and the fail-closed consequence is the safe direction:
    an unattributable kill row simply does not force a verdict.

    `([], None)` when there is no queue-wait row for the branch — the caller routes that to
    `unknown`, i.e. nothing durable to judge on. PURE: no clock, no /proc, no I/O."""
    tid = branch.split("/", 1)[1] if branch and branch.startswith("task/") else None

    def _mine(row):
        if not isinstance(row, dict):
            return False
        data = row.get("data") if isinstance(row.get("data"), dict) else {}
        rb = data.get("branch")
        if rb is not None:
            return rb == branch
        # No `data.branch` at all — the `land_terminated_externally` shape. Attributable only by the
        # task id, and only when the branch HAS one (see BRANCH ATTRIBUTION above).
        return bool(tid) and row.get("task_id") == tid

    mine = [r for r in (rows or ()) if _mine(r)]
    newest = None
    newest_ts = None
    for row in mine:
        if row.get("type") not in _LAND_QUEUE_WAIT_TYPES:
            continue
        try:
            ts = float(row.get("ts"))
        except (TypeError, ValueError):
            continue
        if newest_ts is None or ts > newest_ts:
            newest_ts, newest = ts, row
    if newest is None:
        return [], None

    def _at_or_after(row):
        try:
            return float(row.get("ts")) >= newest_ts
        except (TypeError, ValueError):
            return False               # an unparseable ts cannot be shown to belong to this attempt

    return [r for r in mine if _at_or_after(r)], newest


#: The three exit statuses this arm reports with, and the reason there are three rather than two.
#: 0 = a settled outcome (CONFIRMED, or an idempotent nothing-to-withdraw); 1 = a REFUSAL (this arm
#: did not, or would not, act); 2 = REQUESTED-UNCONFIRMED (it DID act and cannot yet prove the
#: outcome). 2 exists precisely because it is NOT 1: a caller that treats every non-zero exit as
#: failure must still be able to tell «I could not do this» from «I did this and cannot yet prove
#: it», and collapsing the two is what made T-12294's read-back assert things it had not observed.
_LAND_WITHDRAW_OK = 0


_LAND_WITHDRAW_REFUSED = 1


_LAND_WITHDRAW_UNCONFIRMED = 2


#: The verdicts of `_classify_queued_land_liveness` for which there is provably nothing to withdraw.
#: `completed`/`crashed` = the land reached a terminal token; `externally-killed` = a handler
#: witnessed a catchable signal; `unknown` = no durable row to judge on, so nothing can be addressed.
#: All four are IDEMPOTENT NO-OP SUCCESSES: no marker, nothing emitted, exit 0, byte-identical on a
#: re-run. `stopped-emitting` is deliberately ABSENT — it names a SILENCE whose cause is unknown
#: (`_classify_queued_land_liveness` THE LIMIT), so it is split on the T-12257 liveness tri-state
#: instead of being guessed at here.
_LAND_WITHDRAW_NOTHING_VERDICTS = ("completed", "crashed", "externally-killed", "unknown")


def land_withdraw_arm(args, main_wt: "Path | None", *, events_path,
                      session_ref=None, now_ts=None,
                      _worktree_path_for_branch=None, _read_worktree_stamp=None,
                      _stamp_is_own=None, _read_land_events=None,
                      _classify_queued_land_liveness=None, _queue_heartbeat_stale_after=None,
                      _land_branch_attempt_rows=None, _land_queue_row_attempt_key=None,
                      _land_attempt_liveness=None, _land_write_withdraw_request=None,
                      _land_withdraw_request_path=None, _land_attempt_key_parts):
    """`land --withdraw` — record a withdrawal request for THIS caller's own QUEUED land, and report
    EXACTLY what can be proven about it. Returns `(exit_code, out_lines, err_lines)`.

    MODULE-LEVEL, AND THAT IS NOT A STYLE CHOICE. `cmd_land` is not callable from a unit test, so an
    arm written inline there could only be asserted by INSPECTING ITS SOURCE — and a source-form
    probe is not a behaviour test (`lessons/a-source-form-probe-is-not-a-behaviour-test.md`, named as
    such by T-12280's own audit-post). Lifting it gives AC1-AC8 something to CALL, so what they
    assert is the routing this code really performs. It RETURNS lines rather than printing them for
    the same reason: the caller owns the streams, the tests own the assertions. Same shape, same
    recorded rationale, as the sibling `_land_withdrawn_exit`.

    NO `LAND:` TOKEN IS EVER COMPOSED HERE, ON ANY PATH (AC7) — and the call site makes that
    structural rather than remembered by short-circuiting BEFORE the T-0269 terminal-token wrapper is
    installed. The token is the land TERMINAL-STATUS contract (SPEC-0180 rule 2c) and this invocation
    does not land; a watcher keyed on it must never read a withdrawal request as its land verdict.

    THE ORDER IS FAIL-CLOSED AT EVERY STEP, and the ordering carries as much of the correctness as
    the steps do — identity closes BEFORE anything can be written, the key comes off the RESOLVED ROW
    and never off current /proc, and the read-back never claims more than the evidence in hand."""
    _worktree_path_for_branch = _worktree_path_for_branch or globals().get("_worktree_path_for_branch")
    _read_worktree_stamp = _read_worktree_stamp or globals().get("_read_worktree_stamp")
    _stamp_is_own = _stamp_is_own or globals().get("_stamp_is_own")
    _read_land_events = _read_land_events or globals()["_read_land_events"]
    _classify_queued_land_liveness = (_classify_queued_land_liveness
                                      or globals()["_classify_queued_land_liveness"])
    _queue_heartbeat_stale_after = (_queue_heartbeat_stale_after
                                    or globals()["_queue_heartbeat_stale_after"])
    _land_branch_attempt_rows = (_land_branch_attempt_rows
                                 or globals()["_land_branch_attempt_rows"])
    _land_queue_row_attempt_key = (_land_queue_row_attempt_key
                                   or globals()["_land_queue_row_attempt_key"])
    _land_attempt_liveness = _land_attempt_liveness or globals()["_land_attempt_liveness"]
    _land_write_withdraw_request = (_land_write_withdraw_request
                                    or globals()["_land_write_withdraw_request"])
    _land_withdraw_request_path = (_land_withdraw_request_path
                                   or globals()["_land_withdraw_request_path"])

    def _refuse(msg):
        return _LAND_WITHDRAW_REFUSED, [], [f"yitc-v2: land --withdraw: {msg}"]

    # ── (i) RESOLVE THE TARGET (AC8). A withdrawal must NAME what it withdraws: there is no
    # "current branch" default here on purpose. This arm runs from main, where the checked-out
    # branch is main itself, so any implicit target would be a guess — and the thing being guessed
    # at is which land to stop.
    target_task = (getattr(args, "task", None) or "").strip()
    target_branch = (getattr(args, "branch", None) or "").strip()
    if target_task:
        if not re.match(r"^T-\d{4,}$", target_task):
            return _refuse(f"`--task {target_task}` is not a task id (expected `T-NNNN`).")
        branch = f"task/{target_task}"
    elif target_branch:
        branch = target_branch
    else:
        return _refuse("no target — name the land to withdraw with `--task T-XXXX` or "
                       "`--branch work/<slug>`. Nothing was written.")

    # ── (ii) PROVE IDENTITY BEFORE ANYTHING IS WRITTEN (AC2). One may withdraw ONE'S OWN land and
    # nobody else's. This runs before any path that can create a directory, so "no marker anywhere"
    # is a structural property of the ordering and not a thing to remember; `_land_withdraw_branch_dir`
    # creates nothing either, so even resolving a path leaves no footprint. A MISSING or UNREADABLE
    # stamp refuses exactly as a FOREIGN one does — fail-closed: an identity that cannot be read is
    # not an identity that has been proven.
    if not callable(_worktree_path_for_branch) or not callable(_read_worktree_stamp) \
            or not callable(_stamp_is_own):
        return _refuse("cannot verify ownership of this branch's worktree in this context "
                       "(identity readers unavailable). Nothing was written.")
    try:
        wt = _worktree_path_for_branch(branch)
        stamp = _read_worktree_stamp(wt) if wt is not None else None
        own = bool(stamp is not None and _stamp_is_own(stamp))
    except Exception:                  # noqa: BLE001 — unreadable identity is UNPROVEN identity
        own = False
    if not own:
        return _refuse(f"the worktree for `{branch}` is not this session's to withdraw (its stamp is "
                       "missing, unreadable, or belongs to another session). Nothing was written.")

    # ── (iii) FOLD + JUDGE (AC3, AC4). Through the SEGMENT-AWARE reader (SPEC-0190 rule 4) — a raw
    # scan of the journal path sees the live segment alone and would silently answer "no rows" for a
    # land whose queue row has rotated. Then the current-attempt trim, then the SHIPPED classifier
    # with the SHIPPED window: this card contributes no bound, number, threshold or tunable.
    from lib import journal as _journal   # noqa: PLC0415 — T-13138: the declared-read rule
    try:
        # T-13138 — DECLARED: the queue-wait, terminal and killed rows the attempt trim + classifier read.
        rows = _journal.declared_read(_read_land_events, events_path, types=_withdraw_attempt_row_types())
    except Exception:                  # noqa: BLE001 — an unreadable journal judges nothing
        rows = []
    # ONE clock for this whole invocation. `now_ts` is injected by the tests so no arm here depends
    # on wall time; in production it is the real clock, read at the moments that need it. It is a
    # CALLABLE and not a single reading because the read-back below needs a timestamp taken at the
    # WRITE, which is strictly later than this classification.
    _clock = (lambda: now_ts) if now_ts is not None else time.time
    attempt_rows, queue_row = _land_branch_attempt_rows(rows, branch)
    verdict = _classify_queued_land_liveness(
        attempt_rows, now_ts=_clock(), stale_after=_queue_heartbeat_stale_after())

    def _nothing_to_withdraw(why):
        return _LAND_WITHDRAW_OK, [
            f"yitc-v2: land --withdraw: nothing to withdraw on `{branch}` — {why}. "
            "No request was written and nothing was changed."], []

    # ── (iv) ROUTE THE VERDICT EXHAUSTIVELY (AC3). One mapping, no default fall-through: every one
    # of the classifier's six verdicts is named here, so a verdict added later fails loudly at the
    # final `return` rather than silently taking someone else's branch.
    if verdict in _LAND_WITHDRAW_NOTHING_VERDICTS:
        return _nothing_to_withdraw(f"its land is `{verdict}`")

    attempt_key = _land_queue_row_attempt_key(queue_row) if queue_row is not None else None
    key_parts = _land_attempt_key_parts(attempt_key)

    if verdict == "stopped-emitting":
        # The land STOPPED EMITTING and the cause is unknown — the classifier says so and refuses to
        # guess (its THE LIMIT: an uncatchable kill and a silent crash leave identical durable
        # state). So ask the one question that IS answerable, of the attempt's OWN recorded pair:
        # the T-12257 tri-state. PROVEN NOT LIVE → there is nothing left to withdraw. PROVEN LIVE →
        # REFUSE, because a live land that has stopped heartbeating has most likely been ADMITTED
        # past its sole probe and will never observe a request; writing one would publish a request
        # nobody reads and report a withdrawal that does not happen. UNKNOWN → REFUSE, fail-closed:
        # nothing acts on a tri-state None.
        live = _land_attempt_liveness(*key_parts) if key_parts is not None else None
        if live is False:
            return _nothing_to_withdraw(
                "its land stopped emitting and that attempt is PROVEN NOT LIVE")
        if live is True:
            return _refuse(
                f"the land on `{branch}` stopped emitting but its attempt is still RUNNING — it has "
                "most likely been ADMITTED past the one point where it observes a withdrawal, so a "
                "request would never be read. Refusing rather than reporting a withdrawal that will "
                "not happen. Nothing was written.")
        return _refuse(
            f"the land on `{branch}` stopped emitting and its attempt's liveness cannot be "
            "determined. Refusing on unproven state. Nothing was written.")

    if verdict != "still-queued":      # belt: an unrecognised verdict is never routed by accident
        return _refuse(f"unrecognised land verdict `{verdict}` for `{branch}` — refusing on state "
                       "this arm does not understand. Nothing was written.")

    # ── (v) KEY + WRITE (AC1, AC5). The key is READ OFF THE RESOLVED QUEUE ROW and never minted from
    # current /proc — consult finding B1 verbatim: a pid is REUSABLE, so a key minted now could
    # address a DIFFERENT process wearing the same number. A land predating T-12256 recorded no
    # tick, so it has no attempt identity, and the honest answer is a NAMED REFUSAL rather than a
    # guess.
    if attempt_key is None:
        return _refuse(
            f"the queued land on `{branch}` did not record its attempt start tick "
            "(`pid_starttime`), so this attempt cannot be addressed. It predates the recorded-tick "
            "change; wait for it to finish or re-land. Nothing was written — a key is never minted "
            "from current process state, because a reused pid would address a different attempt.")

    # THE WRITE TIMESTAMP, taken immediately BEFORE the write, is load-bearing evidence and not
    # bookkeeping. The read-back may only be confirmed by a `land_withdrawn` row that this request
    # could actually have CAUSED — i.e. one at or after the moment the request was published. Without
    # that floor, a `land_withdrawn` row ALREADY PRESENT for this same attempt before the write
    # satisfies the row test, the interlock still holds (the newest queue row still carries my key),
    # and the arm prints CONFIRMED for a withdrawal that its own request had nothing to do with. That
    # is an attestation from a PRIOR event, the same class of error as attesting from a LATER
    # attempt's row that the interlock exists to prevent — the interlock bounds WHOSE row it is, and
    # this bounds WHEN, and neither alone is sufficient.
    write_ts = _clock()
    wrote = _land_write_withdraw_request(main_wt, branch, attempt_key, session_ref=session_ref)

    # ── (vi) READ BACK WITH THREE OUTCOMES (AC6) — the step this successor exists for.
    #
    # LEG 1 — the write did not land. `_land_write_withdraw_request` is an UNCONDITIONAL
    # truncate-and-overwrite returning `path.exists()` taken AFTER the write, so False has exactly
    # three causes, all genuine failures to publish: an empty branch, a None path (a malformed or
    # absent key), or an exception. False NEVER means "already exists" — an existing request for the
    # same attempt is simply rewritten and returns True — so refusing here cannot swallow an
    # idempotent re-run. (Recorded at audit-pre as the mode-(b) absorbed residual, on exactly this
    # reading of the shipped helper.)
    if not wrote:
        return _refuse(f"the withdrawal request for `{branch}` could not be written. Refusing "
                       "rather than reporting a withdrawal that was never published.")

    # The WAIT TYPE is the queue row's own event type — one of `_LAND_QUEUE_WAIT_TYPES`. Naming it
    # in the confirmed line tells the operator WHICH wait the land is sitting in (a verify-admission
    # slot vs a land reservation), which is the difference between "queued behind other verifies"
    # and "queued behind another land on this repo".
    wait_type = queue_row.get("type")

    def _confirmed():
        return _LAND_WITHDRAW_OK, [
            f"yitc-v2: land --withdraw: CONFIRMED — the land on `{branch}` (attempt {attempt_key}, "
            f"{wait_type}) has a withdrawal request recorded. It will withdraw itself at its "
            "admission seam without running its verify; `main` is untouched."], []

    # LEG 2a — POSITIVE EVIDENCE, the plain kind: the request is ON DISK at the same exact path the
    # LAND reads. Published and not yet consumed.
    on_disk = False
    try:
        path = _land_withdraw_request_path(main_wt, branch, attempt_key)
        on_disk = bool(path is not None and path.exists())
    except Exception:                  # noqa: BLE001 — an unreadable path is not positive evidence
        on_disk = False
    if on_disk:
        return _confirmed()

    # The request is GONE from disk. Something removed it — the target consuming it (the good case),
    # or the sweep reclaiming a dead attempt's entry. Re-fold the journal AFTER the write, never
    # before it, and look for the two facts that together attribute a `land_withdrawn` row to MY
    # target attempt.
    try:
        rows2 = _journal.declared_read(_read_land_events, events_path,
                                       types=_withdraw_attempt_row_types() + ("land_withdrawn",))
    except Exception:                  # noqa: BLE001
        rows2 = []
    rows2_mine, queue_row2 = _land_branch_attempt_rows(rows2, branch)

    # THE NO-LATER-ATTEMPT INTERLOCK, and it is what makes leg 2b sound. T-12280's `land_withdrawn`
    # payload is `{branch, wait_type, waited_s}` and carries NO attempt key, so exact key equality is
    # simply not readable off the shipped row — and this card may not add one (the emit is T-12280's,
    # and a new payload key would owe a SPEC-0161 naming in this diff). The interlock substitutes a
    # STRUCTURAL argument for the missing key: admit the row only while the NEWEST queue-wait row for
    # this branch STILL carries MY target attempt key, which proves NO LATER ATTEMPT HAS QUEUED since.
    # It is sound on a shipped fact rather than on timing — a withdrawal is raised only from the
    # admission-wait poll tick, which is DOWNSTREAM of the queue-wait heartbeat, so any attempt that
    # CAN be withdrawn has necessarily emitted a queue-wait row first. Under the interlock no such row
    # exists for any attempt but mine, so the row admitted here can only be my target attempt's.
    # Without it, a LATER attempt's withdrawal would attest MINE — the T-12294 audit-pre round-1 RED.
    interlock_holds = (queue_row2 is not None
                       and _land_queue_row_attempt_key(queue_row2) == attempt_key)

    def _withdrawn_at_or_after_write(row):
        if row.get("type") != "land_withdrawn":
            return False
        try:
            return float(row.get("ts")) >= write_ts
        except (TypeError, ValueError):
            return False               # an unparseable ts is not evidence of anything
    withdrawn_row = any(_withdrawn_at_or_after_write(r) for r in rows2_mine)

    # LEG 2b — POSITIVE EVIDENCE, the attributed kind: absent from disk, a `land_withdrawn` row for
    # this branch is present in the current attempt's rows, and the interlock holds.
    if withdrawn_row and interlock_holds:
        return _confirmed()

    # No positive evidence either way. The target's own liveness decides what can honestly be said.
    live = _land_attempt_liveness(*key_parts) if key_parts is not None else None

    # LEG 3 — PROVEN NOT LIVE: the attempt this request addressed is gone, so there is nothing left
    # to withdraw and nothing pending to report. The sweep/dead-attempt case, and an idempotent no-op.
    if live is False:
        return _nothing_to_withdraw(
            "its target attempt is PROVEN NOT LIVE — the request has nothing left to address")

    # LEG 4 — REQUESTED-UNCONFIRMED, THE THIRD OUTCOME. The request WAS written and is no longer on
    # disk, and no `land_withdrawn` row confirms it YET. Two states produce this and neither can be
    # told from the other from here: T-12280's consume-to-emit window (the target has taken the
    # request and has not yet journaled), or a LATER attempt having queued so the interlock cannot
    # attribute a row that may well be mine. This is NEITHER the confirmed line NOR a refusal, and
    # saying so is the whole point of this successor: T-12294 printed CONFIRMED here on liveness
    # alone, and its audit-pre was right that PROVEN LIVE does not prove the request was consumed or
    # honoured. RE-RUNNING THE ARM IS THE CONFIRMATION PATH and is idempotent by construction — a
    # re-run re-folds and reports CONFIRMED once the row exists, or nothing-to-withdraw once the
    # attempt is proven not live. That is cheaper and more honest than a bounded wait, which this
    # card is not permitted to add and which would only move the same uncertainty behind a timer.
    if live is True:
        return _LAND_WITHDRAW_UNCONFIRMED, [
            f"yitc-v2: land --withdraw: REQUESTED, NOT YET CONFIRMED — the request for `{branch}` "
            f"(attempt {attempt_key}) was written and is no longer on disk, but no `land_withdrawn` "
            "record confirms it yet. Most likely it was just consumed and the record is moments "
            "away. This is NOT a failure and NOT a confirmation. Re-run this exact command to "
            "resolve it: it reports CONFIRMED once the record appears, or nothing-to-withdraw once "
            "the attempt is proven finished."], []

    # LEG 5 — UNKNOWN liveness: refuse, fail-closed. Nothing acts on a tri-state None (finding C3),
    # and a report built on unproven state is exactly what this card exists to stop making.
    return _refuse(
        f"the withdrawal request for `{branch}` (attempt {attempt_key}) was written and is no longer "
        "on disk, but neither a `land_withdrawn` record nor the attempt's liveness can be "
        "determined, so its outcome cannot be reported honestly. Re-run to resolve it.")


def _land_queue_jump_reason(main_wt: "Path | None", branch: "str | None", *,
                            _load_card=None) -> "str | None":
    """The LIVE queue-jump reason carried by `branch`'s own task card, or None (T-11663).

    Branch -> card -> `state.queue_jump_reason`, and nothing else: the field's semantics (including
    the expiry) live in ONE place, and this is only the address lookup that reaches them. A
    `work/<slug>` branch has no card and so can never jump — the mark is a CARD's, and a batch that
    carries no card is not a queue-unblocking change anybody declared.

    FAIL-CLOSED TO None on every unclear shape — an absent card, an unparseable one, an unreadable
    tasks dir. The polarity is the one `_land_addressee_gone` takes and for the same reason: a reader
    that granted precedence on a misread would hand the road away on noise, which is worse than the
    arrival-order lottery it exists to fix.

    ONE glob and one YAML parse per branch per attempt — the caller memoises across yield rounds
    exactly as it memoises the cost class, so a repo with no marked cards pays one `glob` that finds
    nothing. This is deliberately NOT on the park poll tick (the cost class rule 9 refuses there);
    it runs where the queue is already being read and ranked."""
    br = (branch or "").strip()
    if main_wt is None or not br.startswith("task/"):
        return None
    tid = br.split("/", 1)[1].strip()
    if not re.fullmatch(r"T-\d+", tid):
        return None                    # a name that is not a task id addresses no card
    try:
        cards = sorted((Path(main_wt) / "tasks").glob(f"{tid}-*.yaml"))
        if not cards:
            cards = [Path(main_wt) / "tasks" / f"{tid}.yaml"]
        for c in cards:
            if not c.exists():
                continue
            card = (_load_card or state.load_path)(c)
            reason = state.queue_jump_reason(card)
            if reason:
                return reason
        return None
    except Exception:                  # noqa: BLE001 — an unreadable card grants no precedence
        return None


_LAND_TERMINAL_TYPES = ("land_completed", "land_aborted")


def _withdraw_attempt_row_types() -> tuple:
    """T-13138 (X-1687) — the row types `land_withdraw_arm`'s attempt reads can use: the queue-wait
    rows `_land_branch_attempt_rows` trims on, plus the terminal and killed rows
    `_classify_queued_land_liveness` reads. Every other type is ignored by both, so the arm reads the
    journal DECLARED to these instead of materialising all of it. The killed type is the literal of
    `worktree._TERMINATED_EXTERNALLY_EVENT` (this module cannot import its host)."""
    from lib import journal as _journal   # noqa: PLC0415 — journal never imports this module
    return tuple(_journal.LAND_QUEUE_WAIT_TYPES) + _LAND_TERMINAL_TYPES + ("land_terminated_externally",)


_QUEUE_HEARTBEAT_STALE_BEATS = 3     # missed beats before a queue row reads as "stopped-emitting"


def _classify_queued_land_liveness(rows, *, now_ts: float, stale_after: float, _LAND_QUEUE_WAIT_TYPES, _TERMINATED_EXTERNALLY_EVENT) -> str:
    """PURE fold of a land's DURABLE journal rows into exactly one verdict:

      'completed'         — a terminal `land_completed` row is present.
      'crashed'           — a terminal `land_aborted` row is present (the land reached its own abort).
      'externally-killed' — a `land_terminated_externally` row: a CATCHABLE signal (SIGTERM/SIGHUP/
                            SIGINT) that the land's own handler recorded before dying. This arm names
                            a CAUSE because a handler witnessed it.
      'stopped-emitting'  — a queue-wait row has gone STALE with no terminal row at all. The land
                            stopped mid-wait; the CAUSE IS UNKNOWN and this verdict deliberately does
                            not guess it (see THE LIMIT below).
      'still-queued'      — the newest queue-wait row is FRESH (age <= `stale_after`).
      'unknown'           — no queue-wait row and no terminal row; nothing durable to judge on.

    THE LIMIT, normative (T-11489, external adjudication `decisions/T-11489-audit-adhoc.yaml`, GREEN):
    'stopped-emitting' MUST NOT be reported as an external kill. An UNCATCHABLE kill (SIGKILL) and a
    silent hard crash (segfault, OOM) leave IDENTICAL durable state — a stale heartbeat and no terminal
    row — because no process can journal its own SIGKILL. Separating those two therefore requires an
    EXTERNAL observer (a parent's wait status, the killer's own log, cgroup/OOM or auditd records); none
    of it is the dead land's own durable state, and none of it is an input here. What this fold DOES
    guarantee is the differential AC2 exists for: a land that stopped emitting NEVER classifies the same
    as a healthy queued one. Widening this arm back to 'externally-killed' would assert a cause the
    evidence cannot support — the probes below pin that shut.

    ONE EXTERNAL OBSERVER NOW WRITES A ROW (T-12914), and it changes no logic here: a `land --task/
    --branch` re-exec PARENT that witnesses its queued child's SIGKILL in the wait status journals a
    `land_terminated_externally` row (`observed_by: re-exec-parent`, the CHILD's pid), which this fold
    already reads as 'externally-killed'. Staleness alone still never claims a kill — a land with no
    such parent (a bare in-worktree land) SIGKILLed while queued still reads 'stopped-emitting'.

    `rows` is an iterable of dicts carrying at least `type` and `ts` (epoch seconds). Terminal rows
    win over everything: a land that reached a token is decided, whatever its heartbeats say. PURE so
    the whole truth table is testable without a real land, a real kill, or a real clock."""
    terminal = None
    killed = False
    newest_queue_ts = None
    for row in rows or ():
        rtype = (row or {}).get("type")
        if rtype in _LAND_TERMINAL_TYPES:
            terminal = rtype
        elif rtype == _TERMINATED_EXTERNALLY_EVENT:
            killed = True
        elif rtype in _LAND_QUEUE_WAIT_TYPES:
            try:
                ts = float((row or {}).get("ts"))
            except (TypeError, ValueError):
                continue
            if newest_queue_ts is None or ts > newest_queue_ts:
                newest_queue_ts = ts
    if terminal == "land_completed":
        return "completed"
    if terminal == "land_aborted":
        return "crashed"
    if killed:
        return "externally-killed"
    if newest_queue_ts is None:
        return "unknown"
    # STALENESS NAMES THE SILENCE, NEVER THE CAUSE (see THE LIMIT in the docstring): an uncatchable
    # kill and a silent crash are indistinguishable from here, so this arm reports that the land
    # stopped emitting and stops there.
    return "still-queued" if (now_ts - newest_queue_ts) <= stale_after else "stopped-emitting"


def _queue_heartbeat_stale_after(_interval_fn=None, *, _VERIFY_HEARTBEAT_DEFAULT_SECS, _verify_heartbeat_interval) -> float:
    """The freshness window `_classify_queued_land_liveness` judges against: `_QUEUE_HEARTBEAT_STALE_BEATS`
    of the land's OWN published heartbeat cadence, so the window tracks the cadence instead of
    hard-coding a second, silently-diverging number. Falls back to the default cadence when the
    heartbeat is DISABLED (hb<=0), so a disabled heartbeat yields a usable window rather than 0 —
    which would read every row as instantly stale."""
    hb = (_interval_fn or _verify_heartbeat_interval)()
    if not hb or hb <= 0:
        hb = _VERIFY_HEARTBEAT_DEFAULT_SECS
    return float(hb) * _QUEUE_HEARTBEAT_STALE_BEATS


def _arm_external_termination_record(task_id: "str | None", *, _append_event, _signal_mod=None,
                                     _stderr=None, _TERMINATED_EXTERNALLY_EVENT) -> "list":
    """Journal `land_terminated_externally` when this land is killed by a CATCHABLE signal, then let
    the default disposition kill it. Returns the list of signal names actually armed.

    This is the POSITIVE half of the attribution: for SIGTERM / SIGHUP / SIGINT the record NAMES the
    signal, so a later reader gets an attributed kill rather than an inference. SIGKILL cannot be
    caught — that residual is exactly what the heartbeat-staleness rule above covers, which is why
    both halves exist. Never raises: an unarmable handler leaves the pre-change behaviour standing
    (silence), it does not fail the land."""
    import signal as _sig
    mod = _signal_mod if _signal_mod is not None else _sig
    out = _stderr if _stderr is not None else sys.stderr
    armed = []
    for name in ("SIGTERM", "SIGHUP", "SIGINT"):
        signo = getattr(mod, name, None)
        if signo is None:
            continue

        def _handler(_signo, _frame, _name=name, _signo_v=signo):
            try:
                _append_event(_TERMINATED_EXTERNALLY_EVENT, task_id,
                              {"signal": _name, "pid": os.getpid(),
                               "reason": f"this land was terminated by an EXTERNAL {_name} — recorded so a "
                                         f"later session can tell an external kill from a crash and from a "
                                         f"land still queued (T-11489 AC2); `main` is untouched unless a "
                                         f"`land_completed` row also exists. Recover with "
                                         f"`bin/yitc-v2 worktree recover-land`."})
            except Exception as exc:
                print(f"yitc-v2: land: EXTERNAL TERMINATION ({_name}) — the "
                      f"`{_TERMINATED_EXTERNALLY_EVENT}` record could NOT be written ({exc!r}); "
                      f"announcing it here so the death is not silent.", file=out, flush=True)
            try:
                mod.signal(_signo_v, mod.SIG_DFL)
                os.kill(os.getpid(), _signo_v)
            except Exception:
                os._exit(128 + int(_signo_v))

        try:
            mod.signal(signo, _handler)
            armed.append(name)
        except (OSError, ValueError, RuntimeError):
            continue        # not armable here (non-main thread / unsupported) — degrade to silence
    return armed


def _arm_worker_land_pdeathsig() -> str:
    """Dynamic die-with-worker enforcement (T-10136, SPEC-0103 §1) — the concrete same-session-background
    enforcement path (audit-loop consult, T-10136). Arm PR_SET_PDEATHSIG(SIGKILL) so THIS land is KILLED
    the moment its parent (the worker session) dies: a backgrounded worker land — of ANY shape, including a
    same-session `cmd &` that detection cannot see — then cannot OUTLIVE a yield (AC: cannot complete in the
    background). A FOREGROUND land the harness BLOCKS on keeps its parent alive → the signal never fires →
    it completes normally. Any done-but-unlanded work a killed land leaves is recovered by X-0211's PAIRED
    ask 2 (`worktree recover-land`). Returns:
      'orphaned'    — the parent has ALREADY exited (getppid()==1): this land is already detached from its
                      launcher → the caller REFUSES (a foreground land's parent is alive at entry).
      'armed'       — PDEATHSIG set with a live parent.
      'unsupported' — not Linux / no prctl (best-effort no-op; the reliable-detection refusal + ask-2
                      backstop still hold). Never raises."""
    try:
        if os.getppid() == 1:
            return "orphaned"          # already reparented to init → launcher gone → detached
    except OSError:
        pass
    try:
        import ctypes
        import signal
        PR_SET_PDEATHSIG = 1           # <linux/prctl.h>
        libc = ctypes.CDLL("libc.so.6", use_errno=True)
        if libc.prctl(PR_SET_PDEATHSIG, signal.SIGKILL, 0, 0, 0) != 0:
            return "unsupported"
        # Race: the parent may have died between the getppid() check and prctl() — the signal would then
        # never arrive. Re-check; a now-init parent means we were orphaned in that window.
        if os.getppid() == 1:
            return "orphaned"
        return "armed"
    except (OSError, AttributeError, ValueError):
        return "unsupported"


_LIVENESS_WATCHDOG_POLL_SECS = 5.0


def _liveness_watchdog_poll_secs() -> float:
    """T-12219 — the held-turn liveness watchdog cadence, machine file first, constant otherwise."""
    try:
        from lib import machine_settings      # deferred: keeps the hot import graph unchanged
        return float(machine_settings.resolve("lib.worktree._LIVENESS_WATCHDOG_POLL_SECS",
                                              _LIVENESS_WATCHDOG_POLL_SECS))
    except Exception:            # noqa: BLE001 — the settings STACK is never a
                                 # prerequisite either (SPEC-0193 rule 6 — the
                                 # `remote_workers_override` precedent)
        return _LIVENESS_WATCHDOG_POLL_SECS


_LIVENESS_LOST_EVENT = "land_worker_liveness_lost"


def _worker_liveness_lost(worker_pid: int, task_id: "str | None", liveness: str, *,
                          _append_event, _stderr=None, _kill=None, _kill_this_land) -> bool:
    """RECORD the liveness kill, THEN kill — in that order (SPEC-0180 rule 3). Returns whether the
    record was written (the kill happens either way).

    `_append_event` is the command's INJECTED journal writer, called with the same 3-positional shape
    every sibling emit in this module uses. `_stderr` / `_kill` are injectable so the record-and-kill
    core is exercisable without terminating the test runner; the defaults are the real ones."""
    out = _stderr if _stderr is not None else sys.stderr
    kill = _kill if _kill is not None else _kill_this_land
    recovery = "recover the branch with `bin/yitc-v2 worktree recover-land`"
    data = {"worker_pid": worker_pid, "liveness": liveness,
            "reason": f"the dispatched worker (pid {worker_pid}) holding this land's turn is no longer "
                      f"alive (liveness={liveness}) — terminating the land BEFORE any integration so "
                      f"`main` is untouched (T-11102 / SPEC-0180 rule 3); {recovery}"}
    recorded = False
    try:
        _append_event(_LIVENESS_LOST_EVENT, task_id, data)
        recorded = True
    except Exception as exc:                      # ANY writer failure — the kill must NOT depend on it
        print(f"yitc-v2: land: WORKER-LIVENESS KILL — worker pid {worker_pid} is {liveness}; the "
              f"`{_LIVENESS_LOST_EVENT}` record could NOT be written ({exc!r}). Killing this land "
              f"anyway — an UNRECORDED kill is a silent death (SPEC-0180 rule 3), so it is announced "
              f"here instead. `main` is untouched; {recovery}.", file=out, flush=True)
    if recorded:
        print(f"yitc-v2: land: WORKER-LIVENESS KILL — worker pid {worker_pid} is {liveness}; recorded "
              f"`{_LIVENESS_LOST_EVENT}`. `main` is untouched; {recovery}.", file=out, flush=True)
    kill()
    return recorded


def _kill_this_land() -> None:
    """Terminate THIS land process. SIGKILL and not SIGTERM: nothing downstream of the kill — no
    handler, no `finally`, no atexit — may reach the ff-only merge. `signal` is imported locally, the
    same idiom `_arm_worker_land_pdeathsig` uses."""
    import signal
    os.kill(os.getpid(), signal.SIGKILL)


def _arm_worker_liveness_watchdog(*, worker_pid: int, task_id: "str | None", _append_event,
                                  poll_secs: "float | None" = None,
                                  _pid_alive=None, _sleep=None, _stderr=None, _kill=None, _liveness_watchdog_poll_secs, _worker_liveness_lost):
    """Arm the die-with-the-WORKER binding for a land admitted under a held-turn claim (SPEC-0180 §3).

    Starts a DAEMON thread polling `worker_pid`; the first read that is not 'alive' records
    `land_worker_liveness_lost` and terminates this land. Returns the thread, or None when it cannot
    arm (an unusable pid / no threading) — an unarmable watchdog is reported by returning None, never
    by pretending it armed. Never raises."""
    try:
        pid = int(worker_pid)
    except (TypeError, ValueError):
        return None
    if pid <= 1:
        return None
    alive = _pid_alive if _pid_alive is not None else globals()["_pid_alive"]
    sleep = _sleep if _sleep is not None else time.sleep
    # T-12219 — resolved HERE, never as a module-level default (bound once at import, it could
    # never observe a later `config set`). The watchdog's VERDICT is `kill -0`; this is only how
    # often it asks, which is why it is performance-class under SPEC-0193.
    interval = (float(poll_secs) if poll_secs and float(poll_secs) > 0
                else _liveness_watchdog_poll_secs())

    def _watch() -> None:
        while True:
            sleep(interval)
            liveness = alive(pid)
            if liveness == "alive":
                continue
            _worker_liveness_lost(pid, task_id, liveness, _append_event=_append_event,
                                  _stderr=_stderr, _kill=_kill)
            return

    try:
        import threading
        th = threading.Thread(target=_watch, name=f"land-worker-liveness-{pid}", daemon=True)
        th.start()
        return th
    except (RuntimeError, ImportError):
        return None
