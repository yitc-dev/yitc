"""land_abort — the land ABORT family (the `land_completed{status: abort}` row composer, the
repeated-abort backstop's cause identity / key, the preflight / attributable / landable predicates, the
known-flake exemption test and the abort-assertion legibility fold), extracted byte-identical from
`bin/lib/worktree.py` (T-12705, card C5a of plan `extract-the-13-over-budget-bin-lib-modules-into-le`).

WHAT IS IN HERE. The 12 defs of plan §Extraction map C5a: `_emit_land_abort` (T-0375 — the ONE composer
of the abort half of `land_completed`, incl. the T-11241/T-11956 ts-pinned main-side clearing copy),
`_land_abort_cause_identity` / `_land_abort_key` (T-10302 — the fine cause identity the T-0655
repeated-abort backstop streaks on), `_land_abort_is_preflight` / `_land_abort_attributable` (T-12077 —
the single preflight discriminator + the attempt-attribution decision), `_land_abort_is_landable`
(T-11956), `_land_abort_flake_only` + `_module_repo_root` (T-12152 — the known-flake exemption), and the
`_abort_assertion_*` legibility fold (T-11428 / T-11739). No constant moves: every constant a body reads
(`_LAND_NEVER_LANDING_ABORT_CLASSES`, `_NO_ASSERTION_CAPTURED`) is NON-exclusive — read by other leaves
and by tests as `worktree.X` — so it stays host-owned and arrives by injection.

SEAM (the T-9340 / T-11519 / T-11522 / T-11524 / T-12695 / T-12700 full inject-residue shape,
`lessons/library-extraction.md` §AST-freeze generator): bodies and signatures are spliced VERBATIM from
the original source — never `ast.unparse` — and every non-stdlib free name (the host stayers
`_known_flake_test_names` / `_pinned_entry_core`, the two host consts above, AND moved siblings via their
host residue) arrives as a keyword-only injected parameter, computed with `symtable` over each function's
scope SUBTREE. The host keeps a `functools.wraps` residue under every historical name, so every
`worktree.<sym>` reader / monkeypatch keeps resolving and `inspect.getsource(worktree.<sym>)` unwraps to
the REAL body here. `_module_repo_root` reads `Path(__file__).resolve().parents[2]` — the repo root from
`bin/lib/land_abort.py` exactly as from `bin/lib/worktree.py` (same directory), so its answer is unchanged.

Identity-agnostic KERNEL module (SPEC-0073 bin/ HARD class). It imports stdlib plus the `debt_landing` leaf (T-13022); it NEVER back-imports
the host (`tests/test_bin_lib_leaf_no_host_import.py`). Intentionally spec-less (SPEC-0005 admission
test): a byte-identical relocation mints no standing rule — the governing spec (SPEC-0119) keeps its home
and re-points its `implements:` anchor here.
"""
from __future__ import annotations

import hashlib
import time
from pathlib import Path

from lib import debt_landing  # T-13022: `_CORPUS_GUARD_MARKS` — the ONE home of the corpus-guard gate names (a leaf, not the host)


def _module_repo_root() -> str:
    """This checkout's root — `bin/lib/worktree.py` -> the repo containing it. Used ONLY as the
    fallback root for the flake annotation when no explicit journal path pins the checkout; the
    two-part admission in `_known_flake_test_names` is what keeps a wrong guess harmless (a root
    without the registry file resolves an EMPTY set and exempts nothing)."""
    try:
        return str(Path(__file__).resolve().parents[2])
    except Exception:
        return ""


def _land_abort_flake_only(d: dict, flake_names: frozenset) -> bool:
    """True iff this land_completed{abort} row's failing set is ENTIRELY registered known-flake
    instruments. PURE — the resolved `flake_names` is passed in, never resolved here, so the walk
    below performs no per-row path work of any kind.

    An ABSENT or EMPTY `failing_tests` is False: an unknown failing set is never exempted (a row that
    cannot name what failed cannot prove the failure was a flake)."""
    tests = d.get("failing_tests")
    if not tests or not flake_names:
        return False
    return all(str(t).strip() in flake_names for t in tests)


def _land_abort_cause_identity(d: dict, *, _normalize_abort_cause) -> "str | None":
    """T-10302: the FINE cause identity of one land_completed{abort} row — a short stable digest of
    its `failing_assertions` set — or None when the row carries none.

    Set-shaped (sorted + deduped): the same failures reported in a different order are ONE cause.
    Each assertion is scrubbed through `_normalize_abort_cause` (the existing volatility normalizer:
    hex SHAs → 'SHA', digit-runs → 'N', case/whitespace collapsed), so a re-fail whose message
    embeds a temp path suffix or a changed count still matches itself — otherwise the backstop could
    never arm on a genuinely identical re-fail (the AC2 / 2026-06-09 freeze class).

    Returns None when `failing_assertions` is ABSENT. `failing_tests` is deliberately NOT a secondary
    identity source: a row lacking `failing_assertions` is a LEGACY row (pre-T-10302), and such rows
    MUST fall back to plain `abort_class` keying — re-keying them by their `failing_tests` (journaled
    since T-9240) would retro-change the cause key of already-recorded history, the retro re-arm AC3
    forbids.

    T-10893: the None case is NOT resolved here, and deliberately not — a pure identity/key function has
    no value that fails to equal itself, so "never streak" is not representable at this layer. It is
    resolved one layer out, by ROW SHAPE: `_emit_land_abort` marks a row it emits without assertions
    `cause_identity_absent`, and `_land_repeated_abort_count` skips it. That split is what lets a
    pre-existing legacy row keep this function's None → plain-`abort_class` key byte-identical (it
    cannot retroactively acquire the marker) while a row emitted from here on stops false-arming the
    backstop. Do not re-litigate it into this function."""
    raw = d.get("failing_assertions")
    if not raw:
        return None
    norm = sorted({_normalize_abort_cause(a) for a in raw if str(a).strip()})
    if not norm:
        return None
    return hashlib.sha1("\n".join(norm).encode("utf-8")).hexdigest()[:12]


def _land_abort_key(d: dict, *, _normalize_abort_cause, _land_abort_cause_identity) -> str:
    """Cause key for one land_completed{abort} data dict.

    T-10302: `abort_class` alone is too COARSE to be a cause — every verify failure (a chokepoint
    refusal, a pinned last-green staleness, a real regression) carries the same `verify-failed`
    class, so two aborts with DIFFERENT, each-already-RESOLVED causes streaked as one and false-armed
    the repeated-abort backstop three times on 2026-07-09 (T-10262 / T-10270 / T-10295). So when the
    row carries the finer failing-ASSERTION identity, the key is `<abort_class>#<identity-digest>`:
    a cause that CHANGED between attempts is evidence of progress, not of the T-0636 freeze.

    Without that identity the key is exactly today's value — the STABLE structured `abort_class` when
    present, else the normalized `abort_reason` (legacy fallback). So legacy rows keep their old key
    and never retro-arm (AC3), and an IDENTICAL re-fail still streaks + arms at today's threshold
    (AC2) since the same assertion set digests the same.

    T-10893: that coarse fallback is UNCHANGED here — changing it is what would retro-re-key history —
    but it is no longer what DECIDES a modern row's fate. A row emitted without a fine identity now
    carries `cause_identity_absent` and is skipped by `_land_repeated_abort_count` before this key is
    ever compared, so the fallback survives only as the key of PRE-EXISTING legacy rows. See
    `_land_abort_cause_identity` for why the fix cannot live in this function."""
    cls = d.get("abort_class")
    cls = cls if cls else _normalize_abort_cause(d.get("abort_reason"))
    ident = _land_abort_cause_identity(d, _normalize_abort_cause=_normalize_abort_cause)
    return f"{cls}#{ident}" if ident else cls


def _land_abort_is_landable(abort_class: "str | None", *, _LAND_NEVER_LANDING_ABORT_CLASSES) -> bool:
    """T-11956 — is this abort's branch one that CAN still land? PURE: no clock, no git, no journal.

    The truth-test over `_LAND_NEVER_LANDING_ABORT_CLASSES` above, given a name because it is the
    selection reason `cmd_land` adds to the main-side clearing COPY: an ordinary aborted land's
    `land_completed{status:abort}` row is written to the LANDING CHECKOUT, while the
    `waiting_for_*` heartbeats and the T-11219 land-queue liveness read both use MAIN's journal — so
    until that row reaches main the branch stays ADMITTED to the queue until its heartbeats age out
    of the `_LAND_QUEUE_FRESHNESS_SEC` (90 s) window, holding a slot nobody is waiting in.

    AN UNTAGGED (None) CLASS IS LANDABLE — fail TOWARD mirroring, deliberately. A mirrored row that
    was not needed costs one dedup at the next land (the copy is byte-identical, so it costs
    literally nothing durable); a row that is missing costs every other lander a 90 s phantom
    admission. `None` is also the shape every legacy / un-tagged abort carries, and none of those is
    a never-landing refusal.

    NOT folded into `_LAND_NEVER_LANDING_ABORT_CLASSES` as a method, and not inlined at the call
    site: the set is deliberately a greppable list rather than a predicate (see the comment above),
    and the call site needs a NAME so its selection expression reads as four independent reasons.
    """
    return abort_class not in _LAND_NEVER_LANDING_ABORT_CLASSES


def _land_abort_is_preflight(abort_detail: "dict | None") -> bool:
    """T-12077 — THE SINGLE preflight-vs-in-loop discriminator for a dying land.

    ONE predicate, read by BOTH sides that must agree about what "preflight" means: the
    `abort_preflight` marker `_emit_land_abort` writes onto the row, and the attribute decision
    `_land_abort_attributable` below makes about the T-10849 attempt keys. Before this, each side
    spelled the test itself — the emitter inline off `abort_detail`, the attribution off
    `cur_attempt` alone — and the two DISAGREED in production: 84 of 89 `abort_preflight: true` rows
    since 2026-08-14 carried `attempt_count`, 83 of them reading exactly `1`.

    NO NEW VOCABULARY (SPEC-0188 rule 3): this reads the EXISTING `abort_detail["preflight"]` shape
    T-10850 established; no key, flag, class or event is minted. Total over a possibly-absent,
    possibly-malformed detail, because the abort path is the one path that must never itself raise.
    """
    return bool(isinstance(abort_detail, dict) and abort_detail.get("preflight"))


def _land_abort_attributable(cur_attempt: int, abort_detail: "dict | None",
                             attempt_verify_ms: "int | None" = None, *, _land_abort_is_preflight) -> bool:
    """T-12077 — has this dying land actually PAID an attempt whose cost can be attributed?

    The attribute decision, built ON `_land_abort_is_preflight` above, so the row's
    `abort_preflight` marker and this answer cannot disagree by construction (CHARTER §P5 — one
    discriminator, not two spellings of it).

    FALSE on two shapes, for the same reason:
      * `cur_attempt == 0` — the land never entered the retry loop at all (every `cmd_land`
        preflight refusal, and the pre-queue `corpus-integrity` refusal above the loop). Unchanged
        from the guard this replaces.
      * a PREFLIGHT-shaped refusal on attempt 1 — `cur_attempt` is published at the TOP of each
        iteration, so an in-loop refusal raised BEFORE the admission slot and the suite (the late
        `rebaseline-unauthorized` arm, the assembled-tree `corpus-integrity` guard) already sees
        `cur_attempt == 1` while that attempt has paid NOTHING. Attributing it wrote the fabricated
        `attempt_count: 1` that SPEC-0025 §land_completed and `_attempt_attribution`'s own docstring
        both forbid in terms ("an `attempt_count: 1` there would be a fabricated fact" — the T-0358
        no-fabricated-0s discipline). Absence MEANS "no attempt was paid" and must not be read as one.
        T-12325 NARROWS THIS SHAPE TO THE FACT IT MEANT: a preflight that RECORDED a verify wall
        (`attempt_verify_ms`) DID pay, and is attributable. See the inline note at the test.

    TRUE otherwise — including a PREFLIGHT refusal on attempt >= 2, which is deliberately UNCHANGED:
    attempt 1 there genuinely ran and paid a verify (one such row exists in the measured window,
    carrying `attempt_count: 2` plus its `attempt_breakdown` and `pre_attempt_ms`), and that paid
    cost is exactly the residual T-10849 exists to attribute. SPEC-0025 keeps `attempt_count` = "the
    number of integration attempts this land took"; this only stops counting an attempt that took
    nothing. REPORT-ONLY, like everything it gates: no verdict, no threshold, no new abort path.
    """
    if not cur_attempt:
        return False
    if _land_abort_is_preflight(abort_detail) and cur_attempt < 2:
        # T-12325 — FOLLOW THE FACT, NOT THE MARKER. The paragraph above reads `abort_preflight` as
        # "this attempt paid NOTHING", which held for every preflight that existed when it was
        # written: all of them were pure bookkeeping. T-12325 ships the FIRST preflight that actually
        # RUNS TESTS (the pinned copies of the touched-and-weakened files), and there the marker and
        # the fact SEPARATE. So the question is now asked of the MEASURED wall rather than of the
        # marker: an attempt that recorded a verify run has paid a cost that can be attributed,
        # whatever refused it. The `fabricated fact` guard is UNWEAKENED and stays exact in the
        # direction it was written to protect — a preflight that ran nothing carries no wall
        # (`None`), falls through to the `return False` below, and attributes nothing, exactly as
        # before. `0` is not a measured run either (a wall this arm never starts), so the truth-test
        # is deliberately falsy-based, not `is not None`.
        if attempt_verify_ms:
            return True
        return False
    return True


def _emit_land_abort(branch: "str | None", reason: str, t0: float,
                     abort_class: "str | None" = None,
                     abort_detail: "dict | None" = None, *, _append_event,
                     events_path: "Path | None" = None,
                     attempt_attribution: "dict | None" = None,
                     clearing_copy_events_path: "Path | None" = None, _known_flake_test_names, _land_abort_flake_only, _land_abort_is_preflight, _module_repo_root) -> None:
    """T-0375: journal the ABORT outcome of a land attempt — the journal was blind to aborts
    (only the stdout `LAND: ABORT` token recorded them; 2026-06-05: 2 aborts invisible in
    events.jsonl). SAME `land_completed` carrier as the ok path, discriminated by `status`
    (consumers MUST key off it — SPEC-0025; no new event type, anti-cx F1/F2). Best-effort:
    its own failure NEVER masks the original abort (broad except; the caller's token print
    still follows). Appends to the CURRENT checkout's events.jsonl — worktree dirt folds at
    the next land; a main-checkout append is the D-0049 journal-append exception.

    T-0655: `abort_class` is the STABLE structured cause code (set at the _die origin) the
    repeated-abort backstop streaks on — recorded as an additive `land_completed{abort_class}`
    field (no new event type). Absent (legacy / un-tagged abort) → omitted; the backstop's
    reader then falls back to a normalized `abort_reason` key.

    T-10795: `events_path` overrides that CURRENT-checkout target. None (the default) is what EVERY
    landable-branch abort keeps — its row is written HERE and folds into main at the next land, so an
    UNPINNED main-side copy would DOUBLE-record. (T-11956 leaves this ROUTING exactly as it is; what
    it changes is that a landable abort no longer has to WAIT for that fold, because it now always
    also takes the PINNED copy below. The double-record warning is about the pinning, not the wait.) The caller passes an explicit
    main journal path only for `_LAND_NEVER_LANDING_ABORT_CLASSES`, where no next land exists and the
    row would otherwise die with the discarded worktree (measured 2026-08-07: a spike-branch abort
    visible only inside the spike checkout, so "how often does the spike gate fire?" was
    unanswerable from main). The record itself is UNCHANGED — only its target moves (SPEC-0025).
    (T-11241 reconciles that DOUBLE-record warning rather than contradicting it: what double-records
    is a copy written as a SECOND independent emit, which gets its own `ts` and so survives the union
    as a distinct row. A copy that reuses the FIRST row's `ts` is byte-identical and is collapsed by
    the same land-time dedup — see `clearing_copy_events_path` below. The warning holds; it is a
    warning about the pinning, not about copying as such.)

    T-11241: `clearing_copy_events_path` is the ORTHOGONAL half of that target question — a COPY
    where `events_path` is a MOVE. SPEC-0184 rule 4 marks a dissolved batch's members batch-ineligible
    for ONE ROUND, writing that mark to MAIN's journal because every lander must read it; the clearing
    signal is the member's own next `land_completed`. On an ABORT that row is written to the LANDING
    checkout (`land --task` re-execs into `-C <worktree>`), so it reaches main only when the branch
    finally lands — and the mark therefore outlives its one round for exactly the population that
    keeps failing to land (measured 2026-08-17: of 985 branches with abort rows on main, the only ones
    lacking a paired ok row are the 4 T-10795 spike branches). When set, the SAME row is additionally
    appended to main, so the clearing signal arrives where the mark lives.

    T-11956: the copy's selection is now GENERAL — every abort on a class outside
    `_LAND_NEVER_LANDING_ABORT_CLASSES` takes it, the three named reasons below having each been a
    special case of one rule. The general reason is the LAND QUEUE: the `waiting_for_*` heartbeats
    and the T-11219 liveness read (`batch_landing._land_queue_terminal_epochs`, for which a
    `land_completed` IS a terminal row) both use MAIN's journal, so an abort row that never reaches
    main leaves its branch ADMITTED until its heartbeats age out of the 90 s freshness window. Same
    seam, same pinning, same best-effort guard — only WHO gets the copy widens; `cmd_land` holds the
    selection, and the three reasons below stay live for the never-landing residual named there.

    T-11798: that copy now has a SECOND caller-side reason, on the same seam and with the same
    byte-identical pinning - an abort whose `failure_attribution` names an ESTABLISHING (`at_main`)
    known-broken pair. Same argument as rule 4's: the fact is about MAIN and every other lander
    needs it, but it is written by a branch whose land just FAILED, so waiting for that branch's
    eventual land is waiting on the land least likely to come (measured 2026-08-28: 67 minutes, see
    `_land_known_broken_discovery`). The seam is UNCHANGED - this records that it now serves two
    reasons, not one, so a reader does not conclude a copy implies batch-ineligibility.

    THE WORKTREE ROW STAYS — this is a copy and not a re-route for a concrete reason: the T-0655
    repeated-abort backstop reads the LANDING checkout's journal (`_read_land_events(EVENTS_PATH)`)
    BEFORE the land folds main in, so moving the row would silently shorten every abort streak by one
    and weaken a convergence safety gate. Both rows carry the SAME `ts`, taken from the first append's
    WITNESS (T-10949), which makes them byte-identical so the land-time `_dedup_events` (full
    canonical-JSON identity, SPEC-0002) collapses them to ONE on the union — nothing double-recorded,
    and nothing double-counted in that same streak. The copy is written in its OWN guard AFTER the
    primary row, so a narrow injected `_append_event` stub that rejects the kwargs (or returns no
    witness) can never cost the abort its real row; absent a witness `ts` the copy is simply skipped.
    Default None = today's behaviour, byte-for-byte.

    T-10849: `attempt_attribution` is the same `{attempt_count, attempt_breakdown?, pre_attempt_ms?}`
    key set the OK payload carries (SPEC-0025 §land_completed), composed by `_land_integrate`'s
    `_attempt_attribution` and handed here through the SystemExit attribute channel. It is the abort
    half of T-10847's per-attempt cost attribution: without it an abort at attempt 3 records one
    `duration_ms` and hides the two full suite runs it already paid (33.3h of abort cost in 7d that
    nothing attributed per attempt). None (the default) is exactly today's behaviour, which is what
    every PRE-LOOP abort keeps — a preflight has no attempt to attribute, and a fabricated
    `attempt_count: 1` there would be a fabricated fact. Additive / P5-safe; REPORT-ONLY, nothing
    gates on it (CHARTER non-goal #7).

    T-12630 narrows that last sentence without weakening it: an IN-LOOP preflight refusal now hands
    over a ONE-KEY attribution carrying only `reservation_wait_ms` — a per-LAND quantity that does
    not depend on an attempt having been paid. The attempt keys are still withheld there, so the
    fabricated `attempt_count: 1` stays impossible; what changes is that a measured reservation wait
    is no longer discarded with them. A `cmd_land` PREFLIGHT refusal still hands over nothing at all,
    because it never enters `_land_integrate`; its row gets its `0` from the floor below instead."""
    try:
        data: dict = {"status": "abort", "abort_reason": " ".join(str(reason).split()),
                      "duration_ms": int((time.monotonic() - t0) * 1000),
                      # T-11514 (SPEC-0025 §land_completed) — THE WALL-CLOCK SPLIT OF THE TOTAL ABOVE,
                      # written PRESENT-WITH-NULL here and overwritten with the measured ints by the
                      # `attempt_attribution` update below. The ok row has carried both since T-10972;
                      # the abort row carried neither (measured 2026-08-18..2026-08-25: present on
                      # 460/460 ok rows, 0/352 aborts), so the one row that reports what an aborted
                      # land COST could not say how much of it was QUEUEING and how much was verify RUN.
                      #
                      # WHY DEFAULTED HERE AND NOT LEFT TO THE ATTRIBUTION. `_attempt_attribution` runs
                      # inside `_land_integrate` and covers only aborts that entered the retry loop. A
                      # `cmd_land` PREFLIGHT refusal never reaches it, so attribution alone could not
                      # make the keys UNIFORM — and a key that is present on some abort rows and absent
                      # on others is the same reader problem, one population smaller. Every abort row
                      # now carries both.
                      #
                      # ABSENT-VS-ZERO, WHICH IS THE POINT: `None` means THIS LAND NEVER REACHED THE
                      # TIMED VERIFY (a preflight refusal, or an in-loop abort before step 4); an int
                      # means it did, and states what it paid. A fabricated `0` would be the one
                      # reading this record must never produce — it is exactly what a reader coercing
                      # the ABSENT key already produced (`... or 0`), classifying suite-running aborts
                      # as aborted-before-verify with 0.0 verify hours (T-0358 / T-11236).
                      #
                      # REPORT-ONLY (CHARTER non-goal #7): nothing gates on either key, no threshold is
                      # introduced, and no claim is made about whether any duration is too long.
                      #
                      # T-11690 — `reservation_wait_ms` joins them on IDENTICAL terms, and for the
                      # same reason the two above are defaulted here rather than left to the
                      # attribution: a `cmd_land` PREFLIGHT refusal never enters `_land_integrate`,
                      # so attribution alone could not make the key UNIFORM across abort rows. `None`
                      # means THIS LAND NEVER REACHED THE RESERVATION; an int means it did, and 0 then
                      # means it took the reservation without waiting — which is a MEASUREMENT, not an
                      # absence. It is a SEPARATE key from `admission_wait_ms` because it is a
                      # separate queue with a separate remedy (see the ok payload's semantics block),
                      # and it is NOT inside `verify_duration_ms`: the reservation is taken before the
                      # merge and before step 4, so it is a THIRD phase, never a re-slice of the wall.
                      #
                      # T-12630 NARROWS THAT `None` READING FOR ONE POPULATION, and the narrowing is
                      # the card: on an `abort_preflight` row this key is NEVER null (the floor just
                      # below this dict). The T-11690 text above stays exact for every OTHER abort
                      # row. What made the old reading untenable is that `None` was answering two
                      # different questions at once on the preflight population — `_attempt_attribution`
                      # discarded a MEASURED wait there (62/62 rows, 63% of the abort wall-clock,
                      # T-12499) and the `cmd_land` P0 arm never had one to discard — so a reader could
                      # not tell a wait that happened from a queue that was never entered. Both are
                      # answerable now, and by DIFFERENT keys: the int says what was waited, and
                      # `entry_authorization` (folded below) says the refusal fired before the
                      # reservation was ever requested.
                      "verify_duration_ms": None, "admission_wait_ms": None,
                      "reservation_wait_ms": None}
        if branch:
            data["branch"] = branch
        if abort_class:
            data["abort_class"] = abort_class
        # T-9240 (AC2): fold the structured abort detail (verify-failure's failing test name(s) +
        # verify mode) into the SAME land_completed{abort} record — additive keys (SPEC-0025-safe),
        # so the dispatch-status recovery line can NAME the concrete cause instead of a bare token.
        if abort_detail:
            if abort_detail.get("failing_tests"):
                data["failing_tests"] = abort_detail["failing_tests"]
            # T-10302: the failing-ASSERTION identity the repeated-abort backstop keys on
            # (_land_abort_key). Already computed for the abort message (_surface_failing_assertions);
            # persisting it is what lets two `verify-failed` aborts whose assertions DIFFER read as
            # different causes. Additive key, same shape as failing_tests (SPEC-0025-safe).
            if abort_detail.get("failing_assertions"):
                data["failing_assertions"] = abort_detail["failing_assertions"]
            if abort_detail.get("verify_mode"):
                data["verify_mode"] = abort_detail["verify_mode"]
            # T-11118: the verify-metrics of the attempt that FAILED — same key, same shape, and the
            # same single home (SPEC-0025) as the ok payload's `verify_metrics`, never a parallel
            # spelling. It carries the SPEC-0181 shadow selection record, which until now existed
            # only on succeeding lands; the failing ones are the only lands that can evidence a
            # selector DISAGREEMENT (`selection_failing_side: omitted`). Additive key on the existing
            # row (SPEC-0025-safe) — nothing gates on it, and an abort raised before verify ran
            # simply has none to carry.
            if abort_detail.get("verify_metrics"):
                data["verify_metrics"] = abort_detail["verify_metrics"]
            # T-11973 (SPEC-0189 / SPEC-0025 §land_completed) — THE PER-LAYER OUTCOME TRAIL ON THE
            # ABORT. `_land_integrate` has composed `_abort_detail["consumer_verify_layers"]` since
            # T-9719, whose whole stated point was "carry the per-layer outcome trail onto the abort
            # too, so a FAILED/timed-out layer's outcome is journaled (audit-pre F1 — one outcome per
            # layer, fail path included)". THIS ALLOW-LIST DROPPED IT. The intent shipped; the
            # persistence did not, and nothing surfaced the gap because the OK path carries the key
            # from its own payload site.
            #
            # MEASURED (<project> + <project> + <project>, all journal segments, 2026-09-02): 3322
            # `land_completed` rows, 813 of them aborts. `consumer_verify_layers` present on 2051 rows
            # and on ZERO aborts. So the one row that records a verify FAILURE could not say WHICH
            # DECLARED LAYER failed in machine-readable form — the only carrier was the
            # human-readable `abort_reason` / `failing_assertions` blob, which mixes recovery hints,
            # command output and layer narration, and which a reworded abort silently changes.
            #
            # WHY THIS IS A SHIPPED DELIVERABLE AND NOT HOUSEKEEPING: SPEC-0189 rule 1 admits a
            # born-permissive default only paired with a DETECTOR, and this surface's detector
            # (`debt.declared_test_regime_false_skips`) resolves the failing layer from THIS key and
            # from nothing else. A detector keyed on the prose blob reads GREEN on the same history
            # and degrades to inert the first time the text is reworded, with nobody noticing — which
            # is the failure rule 1 exists to prevent, one level down. The structured field is what
            # makes the refusal of the regex possible rather than merely stated.
            #
            # Additive key on the EXISTING row, guarded on presence exactly as `verify_metrics` above
            # — no new event type, no new store, no second emit (SPEC-0025 / D-0009). An abort raised
            # before any declared layer ran carries none, and its row stays byte-for-byte what it is
            # today.
            if abort_detail.get("consumer_verify_layers"):
                data["consumer_verify_layers"] = abort_detail["consumer_verify_layers"]
            # T-11468 — PERSIST the T-11464 attribution record. `_land_failure_attribution_probe`
            # re-runs the failing files at `merged_base` and splits the failing (file, assertion)
            # pairs into `at_main` / `at_branch`, and `_land_integrate` assigns that record to
            # `_abort_detail["failure_attribution"]`. Until now this allow-list dropped it: the answer
            # was computed on EVERY red land, printed once to stderr, and then lost — so the one fact
            # that says WHOSE red this is existed nowhere a later session could read. That is what
            # made a broken main cost a full verify per branch to rediscover (2026-08-23: every card;
            # 2026-08-22: five branches on two causes), which is precisely the cost the record exists
            # to remove.
            #
            # THE ESTABLISHING PAYLOAD OF THE KNOWN-BROKEN FOLD (SPEC-0181 §Known-broken-on-main).
            # `debt.open_known_broken` reads `at_main` from this key and NOTHING else — never
            # `fail_class` (which labelled a real reproducible breakage `verify-flake` on 2026-08-23)
            # and never the first-sight `failing_tests` / `failing_assertions` keys above. A pair
            # reaching `at_main` failed TWICE, in two independent executions on two different trees,
            # which is what lets a fold stand on it without a flake guard bolted on top.
            #
            # Additive key on the EXISTING land_completed row, guarded on presence exactly as
            # `verify_metrics` is — no new event type, no new store, no second emit (SPEC-0025 /
            # D-0009). An abort raised before the probe could run simply has none to carry, and its
            # row stays byte-for-byte what it is today.
            if abort_detail.get("failure_attribution"):
                data["failure_attribution"] = abort_detail["failure_attribution"]
            # T-11799 — THE PRE-QUEUE KNOWN-BROKEN REFUSAL'S OWN RECORD (SPEC-0025 §land_completed).
            # `{branch, pairs[{pair,file,since,established_by,establishing_sha}], main, merge_base}`,
            # composed by `_land_prequeue_known_broken_refusal` from the values it had already
            # computed for its operator-facing message. Until now this refusal reached main's journal
            # only if the refused branch later LANDED — which is the branch least likely to — so a
            # refusal followed by a discard left nothing anyone could read, count or answer.
            #
            # THE SIBLING OF `failure_attribution` ABOVE, AND ITS COMPLEMENT: that key records a land
            # DISCOVERING a break, this one a land REFUSED because of one already recorded. Both are
            # additive keys on the EXISTING row, guarded on presence exactly as `verify_metrics` is —
            # no new event type, no new abort class, no new emit path (SPEC-0025 / D-0009). An abort
            # from any other cause simply has none to carry and its row stays byte-for-byte what it
            # is today.
            #
            # REPORT-ONLY, and the fence matters here more than usual: the row makes a refusal
            # VISIBLE, it does not make anything RESUME. Nothing gates on it, it waives no gate and
            # excuses no red, and it is deliberately NOT shaped as a queue entry — it carries no
            # position, no ordering key and no retry hook. Whether a refused land should be retried
            # at all, and by whom, is an open question this record does not answer.
            if abort_detail.get("prequeue_known_broken"):
                data["prequeue_known_broken"] = abort_detail["prequeue_known_broken"]
            # T-11282 (SPEC-0184 rule 4a): the ATTEMPT-SCOPED removal sink — the SAME key and the same
            # `{branch, reason}` entries the OK payload carries (T-11277), folded onto the SAME
            # land_completed row rather than spelled a second way. Composed in `_land_integrate`'s
            # `_die` wrapper and handed here on this existing channel, exactly as `verify_metrics`
            # above is. Present only when NON-EMPTY, so an abort that removed nobody — and every
            # pre-loop abort, which has no attempt to attribute — keeps today's row byte-for-byte.
            # Additive / P5-safe; DIAGNOSTIC and NON-TERMINAL, never a member verdict.
            if abort_detail.get("members_removed"):
                data["members_removed"] = abort_detail["members_removed"]
            # T-13345 — the T-12150 queued pre-merge record + its `reservation_disposition`, which
            # the `_die` wrapper already composes onto `abort_detail` and this allow-list dropped:
            # the T-13324 census found every race-while-queued abort row without them although the
            # ticks had run (T-13075's heartbeats: 5 queued conflicts). Additive, present-only.
            for _pm_key in ("queued_premerge", "reservation_disposition",
                            "reservation_released_at_exit"):
                if abort_detail.get(_pm_key):
                    data[_pm_key] = abort_detail[_pm_key]
            # T-10850: this abort was raised by a PREFLIGHT — before the admission slot and the
            # suite. The repeated-abort backstop skips such a row by SHAPE, which is what lets the
            # cheap §3a authorization refusal be exempt while the EXPENSIVE T-10754 waive-coverage
            # refusal — same `rebaseline-unauthorized` abort_class, but raised from the pinned run —
            # keeps arming the streak. Additive key, same shape as failing_tests (SPEC-0025-safe).
            # T-12077: read through the SHARED discriminator rather than re-spelling the
            # truth-test here, so this marker and `_land_abort_attributable`'s answer are the same
            # predicate and cannot drift apart (they measurably had).
            if _land_abort_is_preflight(abort_detail):
                data["abort_preflight"] = True
            # T-12630 (SPEC-0025 §land_completed) — WHICH of the three step-4a-family refusals fired.
            # `abort_preflight` above says a preflight refused this land; it does NOT say WHICH, and
            # the three are different remedies: an authorization refusal wants an audit-post, a
            # waive-token refusal wants a correct token, an in-land re-audit refusal wants a verdict
            # that could not be obtained. MEASURED (T-12499): `debt._abort_arm_rebaseline` rule (1)
            # files EVERY `abort_preflight` row under `authorization`, so all three collapse into one
            # bucket and a trend over that bucket describes none of them.
            #
            # THE CAUSE IS HERE, NOT IN THE READER. Each `_die` site ALREADY composes its own marker
            # onto `abort_detail` (`entry_authorization` at the cmd_land P0 arm, `waive_coverage_
            # preflight` at the pinned-preflight token arm, `inland_reaudit` at the two T-11483 arms)
            # — this allow-list dropped all three, so the reader had nothing to discriminate on and
            # rule (1) was the only answer available to it. NO NEW VOCABULARY IS MINTED (SPEC-0188
            # rule 3): these are the markers that already exist, carried the last inch to the row.
            #
            # Additive, present-only, report-only, in the established `abort_preflight` /
            # `candidate_leg_run` shape — a row carrying none of them is byte-for-byte what it is
            # today, and nothing gates on any of them.
            if abort_detail.get("entry_authorization"):
                data["entry_authorization"] = True
            if abort_detail.get("waive_coverage_preflight"):
                data["waive_coverage_preflight"] = True
            # The OUTCOME that refused, from the CLOSED set the two refusing `_die` sites can raise —
            # never the whole `inland_reaudit` record (which also rides the OK row for a SUCCESSFUL
            # re-audit, and would then mark a row that refused nothing). Admitting only the two
            # refusing outcomes is what keeps this key a refusal discriminator rather than a second
            # spelling of the record.
            _ir = abort_detail.get("inland_reaudit")
            if isinstance(_ir, dict) and _ir.get("outcome") in ("could-not-run", "ceiling-refused"):
                data["inland_reaudit_refusal"] = str(_ir["outcome"])
            # T-12151 (SPEC-0025 §land_completed) — THE LEG THIS ABORT DID NOT SPEND. Pinned-FIRST
            # makes a land refusable BEFORE the candidate leg runs, so `land_completed` now has two
            # distinguishable abort shapes where it had one, and a reader cannot tell them apart from
            # `abort_class` (deliberately the UNCHANGED `verify-failed`) or from the wall clock. The
            # fact was already composed onto `_abort_detail` for the operator-facing message; without
            # this line it stopped at the process boundary and the durable record kept implying the
            # candidate leg had run and passed — the SPEC-0186 rule 7 "did not run" vs "ran and
            # passed" conflation, in the journal instead of in `verify_mode`. Additive key, guarded on
            # presence exactly as `verify_metrics` above — an abort that DID run the candidate leg
            # carries nothing and its row stays byte-for-byte what it is today. Report-only: no gate
            # reads it.
            if abort_detail.get("candidate_leg_run") is False:
                data["candidate_leg_run"] = False
            # T-12151 — and the two pinned-leg signals composed alongside it. Same additive,
            # present-only, report-only shape as `verify_metrics`; see the composition site in
            # `_land_integrate` for why a failing candidate leg can now carry a pinned result at all.
            if abort_detail.get("pinned_cache_hit"):
                data["pinned_cache_hit"] = True
            if abort_detail.get("pinned_layout_excused"):
                data["pinned_layout_excused"] = abort_detail["pinned_layout_excused"]
            # T-11375: WHICH sub-case rejected the operator's `--rebaseline-waive` token(s). The
            # T-10754 waive-coverage refusal (the EXPENSIVE arm above — raised FROM the pinned run,
            # median 597.9s over the one consumer-week measured on the card) mixes an UNBINDABLE
            # token with one refused on its SHAPE, and the abort row could not tell them apart: the
            # `rebaseline_bad_tokens` detail reaches this emitter already and was dropped here, so
            # the cost of the late refusal could not be attributed to either sub-case.
            #
            # DERIVED FROM THE BRANCH TAKEN, never from the message. Each `why` is set on exactly one
            # branch of `_waive_coverage_judge` (`ambiguous` | `insufficient-bare-token` | `no-match`)
            # — so re-wording the human-readable `abort_reason` cannot move this value, and no new
            # vocabulary is minted: the recorded strings ARE that closed set. Distinct + sorted, since
            # one refusal may reject several tokens and the row records WHICH sub-cases fired.
            #
            # Additive key, same shape (and same reason for that shape) as `abort_preflight` above,
            # which SPEC-0188 rule 3 names as the vocabulary to reuse rather than extend. Guarded on a
            # NON-EMPTY set, so a refusal that rejected no token at all — the uncovered-assertions-only
            # shape — keeps its row byte-for-byte. Nothing gates on it; RECORD-ONLY, and deliberately
            # NOT a step toward moving any refusal earlier: what that would be worth is precisely the
            # share this key exists to make measurable, and it is unmeasured until rows accumulate.
            if abort_detail.get("rebaseline_bad_tokens"):
                _rb_whys = sorted({str(t.get("why")) for t in abort_detail["rebaseline_bad_tokens"]
                                   if isinstance(t, dict) and t.get("why")})
                if _rb_whys:
                    data["rebaseline_bad_token_reasons"] = _rb_whys
        # T-10893: this row was emitted WITHOUT a fine cause identity — `_land_abort_cause_identity`
        # will return None for it, so the repeated-abort backstop has nothing but the coarse
        # `abort_class` to streak on, and two SEPARATELY-RESOLVED causes read as one (X-0737 / X-0741 /
        # X-0701: ~2h and 5 land attempts frozen on a branch whose audits and candidate verify were
        # GREEN throughout). `_land_repeated_abort_count` skips a row carrying this marker.
        #
        # WHY A MARKER AND NOT A KEY CHANGE — this is the whole design, and it is not free choice.
        # "Refuse to arm without a fine identity" is NOT representable inside `_land_abort_key`: a pure
        # key function has no value that fails to equal itself, so never-streak cannot be a key. And
        # re-keying every row that lacks `failing_assertions` is exactly what T-10302's AC3 forbids —
        # it would RETRO-re-arm already-recorded history. A marker written going FORWARD is the only
        # shape that satisfies both: a pre-existing legacy row cannot retroactively acquire it, so its
        # key stays byte-identical, while a row emitted from here on is distinguishable and skippable.
        # Written UNCONDITIONALLY of `abort_detail` (an abort with no detail at all is the emptiest
        # identity of all) — the `if` above is inside the detail block, this is deliberately outside it.
        # Same additive-key shape as `abort_preflight` (T-10850), which exempts by ROW SHAPE for the
        # same reason: an abort_class is not always a reliable proxy for what the row can prove.
        if not data.get("failing_assertions"):
            data["cause_identity_absent"] = True
        # T-12152: a failing set that is ENTIRELY registered known-flake instruments measured the
        # shared HOST, not this branch (T-12038's quiet-lane registry is the ONE carrier). NAME it on
        # the row, so a reader — the repeated-abort streak walk, `journal query`, a controller reading
        # why a land aborted — sees "flake re-run" instead of inferring it. Additive key of the SAME
        # shape as `cause_identity_absent` above and `abort_preflight` (SPEC-0025 same-carrier
        # discipline: no new event type, and a row whose set is not entirely registered is
        # byte-unchanged). RECORD-ONLY here; the streak walk resolves the tier, and it also recomputes
        # this predicate itself so rows written before this key existed are read identically.
        #
        # THE ROOT IS THE JOURNAL'S OWN CHECKOUT, never this module's install path. Under `-C
        # <consumer>` the executing `worktree.py` IS the engine's file, so an install-path root would
        # find the engine's `tests/test_t11451_...py` and could exempt a CONSUMER row naming a
        # same-filename test — the exact miss the two-part admission exists to prevent. The row is
        # written to `events_path` (when pinned) else this checkout's journal, and that file's parent
        # IS the checkout the row is about, so it is the only root that cannot lie here.
        _flake_root = str(events_path.parent) if events_path is not None else None
        if _land_abort_flake_only(data, _known_flake_test_names(_flake_root or _module_repo_root())):
            data["flake_only_rerun"] = True
        # T-10849: the per-attempt cost attribution, folded in as additive keys of the SAME shape the
        # ok payload uses (never a parallel spelling — SPEC-0025 is the single home for both halves).
        # Written LAST so it can never displace a cause key the backstop reads.
        if attempt_attribution:
            data.update(attempt_attribution)
            # T-11240 (SPEC-0025 §land_completed): the SAME accounting remainder the ok row records,
            # on the SAME terms — SPEC-0025 describes this key set ONCE for both outcomes, so an
            # abort row whose identity were merely approximate would split one described invariant
            # into two different ones. It is well-defined here because `duration_ms` just above is
            # measured off the SAME `t0` that `cmd_land` hands `_land_integrate` as its `t_start`
            # (one origin, one clock, both ends). On this path the span it names is the unwind
            # between `_die` composing the attribution and this emit — the very gap SPEC-0025 used to
            # excuse in prose as "up to the unwind"; the number replaces the excuse. Same presence
            # rule as the ok side, so a first-attempt or preflight abort row is byte-unchanged
            # (additive / P5-safe). REPORT-ONLY (CHARTER non-goal #7).
            # T-11870 — the same presence rule the ok row now carries: PRESENT whenever the land
            # ENTERED THE LOOP, absent when it never did. The attributed total is computed by
            # `_attempt_attribution` (the site that holds the parts and the pre-loop slice, which on
            # a single-attempt abort are correctly not published) and POPPED here, so the emitted row
            # carries the remainder and not the intermediate. A preflight abort supplies no
            # `_attributed_ms` (T-12630: an in-loop one now supplies `reservation_wait_ms` and
            # nothing else, so this pop still finds nothing) and is byte-unchanged here.
            _attributed_ms = data.pop("_attributed_ms", None)
            if _attributed_ms is not None:
                data["unattributed_ms"] = data["duration_ms"] - _attributed_ms
        # T-12630 — THE NEVER-NULL FLOOR, for `abort_preflight` ROWS ONLY. Two populations reach this
        # point with `reservation_wait_ms` still None: an in-loop preflight refusal is no longer one
        # of them (the attribution now publishes its measured wait), leaving the `cmd_land` P0 arm,
        # which refuses ABOVE `_land_integrate` and therefore never enters the attribution at all.
        #
        # 0 IS THE TRUE ANSWER THERE, not a coerced one. That land spent zero ms waiting for a land
        # reservation — it was refused before it ever requested one. This is NOT the `... or 0`
        # coercion T-0358 / T-11236 forbid: that one READ an absent key as a measurement it never
        # was; this WRITES a measurement the emitter can prove from the branch it took.
        #
        # AND THE FACT THE OLD `None` CARRIED IS NOT LOST — it moves to a key that states it
        # directly. `entry_authorization` (folded above) is present on exactly the rows where this 0
        # means "never reached the reservation"; a 0 without it means "took the reservation without
        # queueing". One value, two readings, disambiguated by a marker rather than by an absence
        # that also meant three other things.
        #
        # SCOPED, deliberately: every abort row that is NOT `abort_preflight` keeps today's `None`
        # and the T-11690 semantics above, byte-for-byte. Report-only; nothing gates on it.
        if data.get("abort_preflight") and data.get("reservation_wait_ms") is None:
            data["reservation_wait_ms"] = 0
        # T-10795: the kwarg rides ONLY the never-landing route. Passing `events_path=None` here would
        # be semantically identical but signature-WIDER — and this emit's own `except BaseException`
        # would silently swallow the resulting TypeError against any 3-arg `_append_event` (the shape
        # tests/test_t0655_backstop_keying.py injects), turning a real abort row into no row at all.
        # Same-shape-by-default is the smaller blast radius: today's callers keep today's call exactly.
        if events_path is not None:
            _witness = _append_event("land_completed", None, data, events_path=events_path)
        else:
            _witness = _append_event("land_completed", None, data)
    except BaseException:
        return
    # T-11241 (SPEC-0184 rule 4): the main-side CLEARING copy. Deliberately OUTSIDE the primary
    # try/except above — the abort's real row is already written by the time we get here, and a
    # narrow injected `_append_event` stub that rejects `ts=`/`events_path=` must fail HERE, alone,
    # rather than sharing a guard with the write that matters. Its own broad guard keeps the whole
    # emit best-effort, exactly as the primary is: a copy that cannot be written never masks the abort.
    if clearing_copy_events_path is None:
        return
    try:
        # The pinned `ts` IS the no-double-record property (see the docstring): reuse the FIRST row's
        # timestamp so the two rows are byte-identical and the land-time dedup folds them into one.
        # No witness (a stub returning None, an older 3-arg shape) → no pinnable ts → skip the copy
        # rather than write an unpinned row that WOULD double-record. Fail-open, and in the direction
        # rule 4 already chose: a missed clearing costs one extra solo round, a duplicated abort row
        # would inflate the T-0655 streak.
        _ts = (_witness or {}).get("ts") if isinstance(_witness, dict) else None
        if _ts:
            _append_event("land_completed", None, data, ts=_ts,
                          events_path=clearing_copy_events_path)
    except BaseException:
        pass


def _abort_assertion_legibility(rows: "list", *, current_layers=None, _NO_ASSERTION_CAPTURED, _abort_assertion_config_bound, _abort_assertion_layer_declaration, _abort_assertion_legibility_lines, _pinned_entry_core) -> dict:
    """T-11428 (<project> X-1050 fold 2) — PURE, REPORT-ONLY: what share of ABORTED lands can NAME what
    broke. Takes the `data` payloads of `land_completed` rows OLDEST-FIRST — the identical slice the
    sibling T6 lens already hands `_verify_scaling_signals` — and returns a dict of counts plus a
    ready-to-print `report` list. It mutates nothing, exits nothing, and raises nothing on malformed
    input (a fold that crashed on one odd row would be a gate, and this is not one).

    WHY THIS IS NOT LEGIBILITY GARNISH. A `land --rebaseline` waive token must NAME an assertion, so an
    abort whose entry reads `(no assertion captured)` leaves the token nothing to bind to and the land
    ends at a human. <project> measured 96 of 133 entries (72%) mute across 105 aborted lands, and their
    61 waive-coverage refusals are the SAME root seen from the other side. One root, two symptoms.

    THE FOLD IS ON THE ASSERTION TEXT AND NEVER ON `abort_class` — the method both projects paid to
    learn, and the one thing a reader of this function must not "simplify". `abort_class` is a ROUTING
    label: it unions refusals of different PLACEMENT and different MOVABILITY into one bucket, so a
    share computed from it measures the taxonomy rather than the legibility (that hazard is its own
    card, T-11426). This function therefore never reads `abort_class`, and its differential asserts a
    fold that did would produce the same number over a fixture whose classes were rewritten.

    THE MARKERS ARE READ BACK, NOT RE-DERIVED. `_NO_ASSERTION_CAPTURED` / `_PINNED_PREFIX` /
    `_NO_ASSERTION_CONTEXT_SEP` are written by `_surface_failing_assertions` and already read back by
    `_rebaseline_waive_coverage`; this is a THIRD reader of the same single definitions, never a second
    copy of the strings (CHARTER §P5).

    BUCKETS — three at the ENTRY level, and none is ever folded into another:
      * `named`    — the assertion position holds anything else, INCLUDING a T-11346 synthesised
                     unmarked-layer identifier: it names a BINDABLE identifier even where it does not
                     name the assertion, which is precisely the property a waive token needs.
      * `mute`     — the assertion position holds `_NO_ASSERTION_CAPTURED`. Nothing to bind to.
      * `unshaped` — a pass-through entry with no `"<name>: <assertion>"` shape (graph-build /
                     conflict-marker / timeout entries). It names a cause but no assertion identifier,
                     and it is neither of the two above. Reported in its own bucket because a bucket
                     that silently vanished into either neighbour is the false-clean this fold exists
                     to catch.
    And ONE at the ROW level, deliberately kept apart from the entry share: `rows_without_assertions`
    — an aborted land carrying no `failing_assertions` key at all. That is a DIFFERENT absence from a
    mute entry (nothing was ever captured, versus something was captured and named nothing), so adding
    the two would report a number neither of them supports.

    NO THRESHOLD IS DECREED, and that is a measurement, not a shrug: this kernel's last 300 aborted
    rows read ~2.5% mute (103 of 4132 entries) while <project>'s window read 72%. Two orders of
    magnitude on the same fold means no cross-repo number could be anything but voluntaristic, so the
    share ships as a TRAJECTORY the owner/Review reads — the roster's own "measured, not decreed"
    precedent (CHARTER §6 fence; SPEC-0057 §2).

    `current_layers` — the verify-layer names the repo declares TODAY (`verify.layers[].layer`,
    SPEC-0152 — the carrier key is `layer`; there is NO `name` key on a verify layer, and this
    docstring said otherwise until T-11739), or None when it declares none. See
    `_abort_assertion_config_bound` for the window rule; the honest no-declaration answer is stated,
    never rendered as "clean".

    A PASSED declaration that resolves to NO usable name is REFUSED, not folded (T-11739, <project>
    X-1145): the return is `{"refused": <reason>, "report": [...]}` with no count keys at all. See
    `_abort_assertion_layer_declaration` for why a null layer set and a real one must not read the
    same."""
    declared, refusal = _abort_assertion_layer_declaration(current_layers)
    if refusal:
        # Deliberately NO count keys — not even a null `mute_pct`. A refused fold that still carried
        # them would let a caller read a share off it, which is the exact false-clean this refusal
        # exists to stop; a KeyError is the honest outcome for code that tries.
        return {"refused": refusal, "report": _abort_assertion_legibility_lines({"refused": refusal})}
    rows = [d for d in (rows or []) if isinstance(d, dict)]
    aborts = [d for d in rows if d.get("status") == "abort"]
    bound = _abort_assertion_config_bound(aborts, declared)
    window = aborts[bound["start_index"]:]

    named = mute = unshaped = no_assertions = 0
    mute_names: "list" = []
    for d in window:
        fa = d.get("failing_assertions")
        if not isinstance(fa, list) or not [x for x in fa if str(x).strip()]:
            no_assertions += 1
            continue
        for raw in fa:
            entry = str(raw)
            if not entry.strip():
                continue
            core = _pinned_entry_core(entry)
            name, sep, assertion = core.partition(": ")
            if not sep or not name.strip():
                unshaped += 1
                continue
            if assertion.startswith(_NO_ASSERTION_CAPTURED):
                mute += 1
                if name.strip() not in mute_names:
                    mute_names.append(name.strip())
            else:
                named += 1

    entries = named + mute + unshaped
    share = (100.0 * mute / entries) if entries else None
    out = {
        "aborted_rows": len(window),
        "entries": entries,
        "named": named,
        "mute": mute,
        "unshaped": unshaped,
        "mute_pct": round(share, 1) if share is not None else None,
        "rows_without_assertions": no_assertions,
        "mute_subjects": mute_names[:5],
        "config_bound": bound,
        "report": [],
    }
    out["report"] = _abort_assertion_legibility_lines(out)
    return out


def _abort_assertion_layer_declaration(current_layers):
    """T-11739 (<project> X-1145) — read the caller's layer DECLARATION, and REFUSE one that resolves
    to nothing. Returns `(usable_names_or_None, refusal_or_None)`.

    THE DISTINCTION THIS EXISTS TO KEEP. `None` means the caller made NO claim about layers — the
    honest answer is "no boundary applies", and `_abort_assertion_config_bound` already says so out
    loud. An ALL-None or EMPTY list means something else entirely: the caller BELIEVED it passed a
    declaration and the READ FAILED. A null layer set and a real one MUST NOT read the same.

    WHY IT IS A REFUSAL AND NOT A THIRD REPORTED NUMBER — measured, not assumed. <project> ran the
    roster's own block verbatim on 2026-08-27; the block named `verify.layers[].name`, a key that
    does not exist (the carrier is `layer`, `verify_runner.py` `ly.get("layer")`), so their
    comprehension resolved `[None, None, None, None]`. The old code took that as a declaration: it
    built a `declared` set of the literal string "None", which matches no entry name, so EVERY shaped
    row read as recorded-under-a-removed-layer and the window truncated to nothing. The fold printed
    `0 of 0 assertion entries across 5 aborted lands are MUTE (None%)` and excluded 14 rows under
    "a layer no longer declared (stack, static)" — declaring that project's two BUSIEST LIVE layers
    removed. The real reading over the SAME journal was `12 of 16 across 19 aborted lands are MUTE
    (75.0%)`, a near-exact recurrence of the 72% they had already reported as X-1050. So the weekly
    slot that exists to WATCH that trajectory reported it clean. A confident false report is worse
    than no report: this is the roster's own F-#2 (probe null is not probe clean) applied to the case
    its author did not cover — a declaration that was passed rather than omitted.

    NORMALISATION IS PART OF THE FIX, not tidying. Dropping the null/blank entries is what makes an
    all-None list a REFUSAL rather than a differently-wrong number, and it stops a PARTIALLY null
    list (`["frontend", None]`) from minting "None" as a declared layer name.

    RAISES NOTHING, by contract. A non-iterable (or an entry whose `str()` explodes) fails CLOSED
    into the refusal rather than propagating: the caller is documented to raise nothing on malformed
    input, and a fold that crashed on one odd input would be a gate — this is not one."""
    if current_layers is None:
        return None, None
    try:
        usable = [str(x).strip() for x in current_layers
                  if x is not None and str(x).strip() and str(x).strip() != "None"]
    except Exception:
        usable = []
    if usable:
        return usable, None
    return None, (
        "a verify-layer declaration was PASSED but resolves to NO usable layer name (it is empty, or "
        "every entry is null) — so there is nothing to bound the window with. The usual cause is "
        "reading a key that does not exist: the carrier is `verify.layers[].layer`, NOT "
        "`verify.layers[].name` (a consumer's X-1145 / T-11739). REFUSED rather than folded: a null layer "
        "set and a real one must not read the same, and treating this as a declaration silently "
        "excludes live layers as `removed` and reports the result as clean.")


def _abort_assertion_config_bound(aborts: "list", current_layers, *, _pinned_entry_core) -> dict:
    """T-11428 (AC2) — bound the fold's window to the CURRENT layer configuration. Folding across a
    layer REMOVAL mixes a layer that no longer exists into today's diagnosis, so the window starts
    AFTER the newest row recorded under a removed layer. Returns the start index plus what was
    excluded and why — the exclusion is REPORTED, never a silent truncation.

    A row is PRE-REMOVAL iff one of its entry NAMES is a verify-layer name absent from
    `current_layers`. A kernel entry names a TEST FILE (`test_x.py`) rather than a layer and is
    therefore never read as a removed layer — the `.py` discriminator is the only signal the rendered
    `"<name>: <assertion>"` line still carries, and it is stated here rather than guessed at the call
    site.

    ONLY A SHAPED ENTRY CAN NAME A LAYER, and the check is on the SEPARATOR, not on the leading text
    (audit-post finding, T-11428 pass 1). An UNSHAPED pass-through entry — `graph build failed`, a
    conflict-marker line, a timeout line — has no `"<name>: <assertion>"` split at all, so reading its
    whole first line as a "name" made every such entry look like an undeclared layer and EXCLUDED the
    real in-window rows behind it, skewing the very share this fold reports. The bucketer above
    already refuses those entries on the same separator test; this reuses it, so the two cannot
    disagree about what an entry NAMES.

    NO DECLARATION ⇒ NO BOUNDARY, said out loud. When `current_layers` is None the repo declares no
    verify layers (this kernel), so nothing in the window CAN be identified as recorded under a
    removed one. That is reported as "no boundary applies", never as a clean bound — probe null is not
    probe clean (the roster's own F-#2)."""
    if current_layers is None:
        return {"applies": False, "start_index": 0, "excluded": 0, "removed_layers": [],
                "why": "the repo declares no `verify.layers` — no layer-configuration boundary applies "
                       "(stated, NOT read as clean)"}
    declared = {str(x) for x in current_layers}
    start, removed = 0, []
    for i, d in enumerate(aborts):
        for raw in (d.get("failing_assertions") or []):
            name, sep, _ = _pinned_entry_core(str(raw)).partition(": ")
            name = name.strip()
            if (not sep or not name or name.endswith(".py") or name in declared
                    or _is_kernel_gate_name(name)):
                continue
            start = i + 1                      # this row predates the removal — the window opens after it
            if name not in removed:
                removed.append(name)
    return {"applies": True, "start_index": start, "excluded": start, "removed_layers": removed,
            "why": (f"window opens after the newest row recorded under a layer no longer declared "
                    f"({', '.join(removed)})" if removed else
                    "no row in the window was recorded under a removed layer")}


# T-13022 — the EXACT kernel `land(<x>):` refusal-wrapper names (bin/lib/worktree.py, land_floors.py,
# land_verify_legs.py spell them inline). An exact set, never a `land(` prefix: a consumer layer named
# `land(custom)` is still a layer. tests/test_abort_legibility_kernel_gate_names.py pins this tuple to
# every `land(<x>)` spelling in bin/lib, so a new wrapper cannot drift out of it silently.
_KERNEL_LAND_GATE_NAMES = ("land(floor)", "land(consumer)", "land(verify-infra)")


def _is_kernel_gate_name(name: str) -> bool:
    """T-13022 — True when an entry NAME is a KERNEL gate refusal rather than a verify layer: one of
    `_KERNEL_LAND_GATE_NAMES`, or the name half of a `_CORPUS_GUARD_MARKS` opening (read from its home,
    never re-spelled — CHARTER §P5). Such a name was never a declared layer, so it cannot mark a layer
    REMOVAL; reading it as one opened the window after 67 of 70 <project> aborts
    (revizia-consumers-2026-09-27)."""
    return (name in _KERNEL_LAND_GATE_NAMES
            or name in {m.partition(": ")[0] for m in debt_landing._CORPUS_GUARD_MARKS})


def _abort_assertion_legibility_lines(res: dict, *, _NO_ASSERTION_CAPTURED) -> "list":
    """T-11428 — the report-only rendering, kept HERE rather than in the roster's doc block so the
    wording cannot drift between the code and the checklist that runs it (the doc block prints these
    lines verbatim). Report-only by construction: strings, no verdict, no exit code."""
    if res.get("refused"):
        return ["abort assertion legibility: REFUSED — " + str(res["refused"]),
                "    NO share is reported (report-only, as ever: this is a refusal to report a "
                "NUMBER, never a gate — no verdict, no exit code). Pass the layer names read from "
                "`verify.layers[].layer`, or pass None to get the honest no-boundary answer."]
    if not res.get("aborted_rows"):
        return ["abort assertion legibility: no aborted lands in the window — nothing to fold "
                "(report-only; this is no-data, NOT a clean bill)"]
    lines = [
        f"abort assertion legibility: {res['mute']} of {res['entries']} assertion entr(ies) across "
        f"{res['aborted_rows']} aborted land(s) are MUTE ({res['mute_pct']}%) — they read "
        f"`{_NO_ASSERTION_CAPTURED}`, so a `land --rebaseline` waive token has NOTHING to bind to and "
        f"the land ends at a human. Named: {res['named']}. Unshaped (a cause but no assertion "
        f"identifier — graph-build / conflict-marker / timeout entries): {res['unshaped']}.",
        f"    {res['rows_without_assertions']} further aborted land(s) carried NO `failing_assertions` "
        f"at all — a DIFFERENT absence from a mute entry, counted apart and never added to the share.",
        f"    window: {res['config_bound']['why']}"
        + (f"; {res['config_bound']['excluded']} row(s) excluded" if res['config_bound']['excluded'] else ""),
        "    Folded on the assertion TEXT, never on `abort_class` — a routing label unions refusals of "
        "different placement AND movability, so a share computed from it measures the taxonomy "
        "(T-11426). Report-only, no threshold decreed: this kernel measured 2.5% over its last 300 "
        "aborted lands and one consumer measured 72% over its own, so any cross-repo number would be "
        "voluntaristic. Read it as a trajectory.",
    ]
    if res["mute_subjects"]:
        lines.append("    mute subjects (first 5): " + ", ".join(res["mute_subjects"]))
    return lines
