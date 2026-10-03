"""debt_landing — the LANDING family of `bin/yitc-v2 debt` views, extracted byte-identical from
`bin/lib/debt.py` (T-12698, card C9a of plan `extract-the-13-over-budget-bin-lib-modules-into-le`).

WHAT IS IN HERE. The 13 landing-side debt views — `aborted_land_cost`, `dead_lands` (+ its cause /
remedy clauses), `land_abort_cause_breadth`, `branch_unlanded_attempt_burn`, `concurrent_session_holds`,
`remote_lag`, `ahead_work_branches` / `behind_work_branches`, `slowest_decile_changes`,
`abort_arm_is_caught_defect`, `abort_class_is_park_limit_eviction` — plus their transitive-EXCLUSIVE
helper closure (the `_abort_*` arms and folds, the `_dead_land_*` readers, the `_*_result` renderers,
and the small pure helpers), 42 defs frozen at baseline 02250d5 (plan §Extraction map C9a). A helper
moved iff EVERY top-level caller of it is already in the move-set; the 46 constants that only this
family reads moved with it and live module-local here (nine are read from a moved signature DEFAULT,
which is evaluated at def time and so cannot arrive by injection). A constant a BODY reads is ALSO
injected by the host residue, so rebinding the historical host name (`debt.ABORT_COST_WINDOW_DAYS =
…`, a monkeypatch) is honoured on every call through the host — a module attribute is not a live
alias across modules, so the alias alone would have kept lookup but lost assignment semantics
(T-12698 audit-pre finding 1).

NOT IN HERE. `cmd_debt` and the echo registry, the adoption / spec0161 / plan-census families, and
the host-shared readers (`_parse_stamped_deadline`, `_window_segment_floor`) — those arrive by
injection. The `_ABORT_ARM_READERS` dispatch dict STAYS host-side so it keeps mapping to the host
residues (the `is`-identity + monkeypatch contract, `lessons/library-extraction.md`).

SEAM (the T-9340 / T-9341 / T-11519 / T-11522 full inject-residue shape, `lessons/library-extraction.md`
§AST-freeze generator): bodies and signatures are spliced VERBATIM from the original source — never
`ast.unparse` — and every non-stdlib, non-moved free name (host stayers, host globals, AND moved
siblings via their host residue, AND body-read moved constants) arrives as a keyword-only injected
parameter, computed with `symtable` over each function's scope SUBTREE. The host keeps a
`functools.wraps` residue under every historical name and a re-export alias for every moved
constant, so every `debt.<symbol>` reader (cli / views / worktree / journal / task / batch_landing +
the tests' monkeypatches) keeps resolving.

Identity-agnostic KERNEL module (SPEC-0073 bin/ HARD class). It imports only stdlib + the lower
leaves `lib.state` / `lib.journal`; it NEVER back-imports its host `lib.debt`.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import yaml

from lib import state  # CHARTER §P5 one parser library — the ops-carrier reader
from lib import journal  # the ONE parsed journal fold + its request-scoped memo (CHARTER §P5)


# ---------------------------------------------------------------------------
# Constants moved WITH their readers (T-12698): each is read ONLY by this family (exclusivity computed
# as a fixpoint over host defs + module statements + every other bin/lib module); nine of them are
# read from a moved signature DEFAULT, which is evaluated at def time in THIS module. The host keeps
# a re-export alias under each historical name, and a body-read constant is ALSO injected by the
# host residue so a host-side rebind stays honoured (see the module docstring).
# ---------------------------------------------------------------------------
SLOWEST_CHANGE_WINDOW_LANDS = 10     # the BASELINE: how many prior recorded lands the comparison uses
SLOWEST_CHANGE_MIN_PRIOR = 3         # below this many prior records the fold says nothing at all
SLOWEST_CHANGE_GROWTH_RATIO = 0.25   # a member must grow at least this fraction over its baseline …
SLOWEST_CHANGE_MIN_GROWTH_MS = 2000  # … AND at least this many ms, so jitter on a small file is mute
_SLOWEST_COMPARABLE_OUTCOME = "passed"   # the ONLY outcome whose wall time compares across lands
ABORT_COST_WINDOW_DAYS = 7            # the reporting window: one week of lands, the requester's unit
ABORT_COST_MATERIAL_MS = 60_000       # below this an EARLY refusal costs nothing worth reporting …
ABORT_COST_DECAY_RATIO = 0.5          # … recent half <= this * older half ⇒ the class is DECAYING …
ABORT_COST_GROWTH_RATIO = 2.0         # … recent half >= this * older half ⇒ it is GROWING …
ABORT_COST_TREND_FLOOR_MS = 300_000   # … and below this much total cost no trend verdict is claimed
ABORT_PAID_VERIFY_MARKER = "verify_mode"     # the payload key present IFF the verify actually ran
ABORT_GATE_CAUGHT_CLASSES = ("verify-failed",)     # paid + FAILED: the gate earning its keep
ABORT_INCONCLUSIVE_CLASSES = ("verify-timeout",)   # paid + concluded NOTHING: neither of the above
ABORT_UNCLASSIFIED = "unclassified"   # a row carrying no abort_class is folded here, never dropped
ABORT_PREFLIGHT_MARKER = "abort_preflight"   # the payload key a row sets when it refused at the
ABORT_COST_GROUPS = ("gate-caught", "inconclusive", "process-refusal", "preflight-refused", "early")
ABORT_CLASS_PARK_LIMIT_EVICTION = "land-reservation-park-limit"   # the T-11819 `_die`'s abort_class
ABORT_ARM_SPLIT_CLASSES = ("rebaseline-unauthorized", "verify-failed")   # the class names that
ABORT_ARM_AUTHORIZATION = "authorization"      # the T-10850 arm — ALREADY moved to the step-4a preflight
ABORT_ARM_WAIVE_COVERAGE = "waive-coverage"    # the T-10754 arm — PARTLY moved: token-binding half
ABORT_ARM_INLAND_REAUDIT = "inland-reaudit"    # T-12630 — the THIRD refusal this class name carries:
ABORT_ARM_UNATTRIBUTED = "unattributed"        # provably neither — never guessed, never dropped
ABORT_ARM_AUTHORIZATION_MARK = "requires a GREEN/YELLOW audit-post"
ABORT_ARM_WAIVE_COVERAGE_MARK = "the ack is scoped to the pinned assertion(s)"
ABORT_ARM_TEST_FAILURE = "test-failure"            # the gate earning its keep — a real defect caught
ABORT_ARM_CORPUS_BOOKKEEPING = "corpus-bookkeeping"  # refused on the branch's PAPERWORK, not its code
ABORT_ARM_MIXED = "mixed"                          # both — attributed to neither arm alone
ABORT_ARM_LAYER_TIMEOUT = "layer-timeout"          # T-12406 — the LAYER ran out of wall-clock: a
_LAYER_TIMEOUT_OUTCOME = "timed-out"
_LAYER_TIMEOUT_ASSERTION_MARK = "command TIMED OUT after"
ABORT_ARMS_CAUGHT_DEFECT = (ABORT_ARM_TEST_FAILURE,)
_CORPUS_GUARD_MARKS = (
    "decisions content-freeze (T-0543/SPEC-0054): land REJECTED",     # SPEC-0054 decision freeze
    "spec-edit chokepoint (T-9730/SPEC-0005): land REJECTED",         # SPEC-0005 off-path spec edit
    "card-shape guard (T-10687/T-10726, SPEC-0165 L1/C1c): land REJECTED",   # SPEC-0165 card shape
)
_REMOTE_LAG_GIT_TIMEOUT = 10   # seconds — bound each local git read; a hung git degrades, never hangs a seam
DEAD_LAND_TIP_PREFIX = "land: bookkeeping ("
DEAD_LAND_TERMINAL_EVENT = "land_completed"
DEAD_LAND_MEMBER_EVENT = "land_member_verdict"
DEAD_LAND_RED_EVIDENCE_KEYS = ("red_assertions", "red_isolation", "red_isolation_decline",
                               "evicted_as_culprit")
AHEAD_BRANCH_NAMESPACES = ("task/", "work/")
UNKNOWN_HOLDER = "UNKNOWN (unstamped / raw-git)"
_ABORT_BREADTH_EVENTS = ("land_completed", "land_member_verdict")
_ABORT_BREADTH_MEMBER_REQUEUE_VERDICT = "requeued-after-red-batch"   # SPEC-0184 rule 5's requeue
_ABORT_BREADTH_MEMBER_LANDED_VERDICT = "landed"          # SPEC-0184 rule 5's member that REACHED main
_ABORT_BREADTH_MAX_NAMED_ASSERTIONS = 3   # the bounded AC6 sample carried per cause (render shows <=2)
_ABORT_BREADTH_WINDOW_HOURS = 24    # the reading horizon; a report-only bound, not a governance scalar
_ABORT_BREADTH_MIN_BRANCHES = 2     # DISTINCT branches on ONE cause before the line prints (see below)
_BRANCH_BURN_MIN_ATTEMPTS = 4     # DISTINCT unlanded attempts on ONE branch before the line prints


def _slowest_records(events_path) -> list:
    """The per-file duration records carried by successful lands, oldest→newest (T-11125).

    Reads the SAME `land_completed` rows the sibling folds read, and admits a row only when it
    carries a `verify_metrics.per_file_durations.slowest_files` list — the T-11124 record. A land
    that recorded nothing (a no-test-files run, or any land before T-11124 shipped) contributes
    NOTHING rather than an empty observation, so history is never read as "every file vanished".
    FAITHFUL, never fail-closed on parse: a malformed line is skipped, never fatal.

    READS THE WHOLE LOGICAL JOURNAL (T-11595 — SPEC-0190 rule 4). The horizon its caller judges is
    COUNT-bounded — the latest carrying land plus `SLOWEST_CHANGE_WINDOW_LANDS` priors — and so
    declares no TIME horizon at all: how far back it reaches is set by the land rate AND by the emit
    rate (only a minority of successful lands carry the T-11124 record), neither of which anything
    keeps inside the 7-day live segment. A single-file fold would therefore lose its OLDEST baseline
    records first, and that loss is SILENT in both directions: a file whose baseline membership
    rotated away reads as a fresh ENTRANT, and below `SLOWEST_CHANGE_MIN_PRIOR` the fold says
    nothing at all. `segment_rows` resolves the segment SET and reads each member through the SAME
    `fold_rows` primitive T-11453 shared, so this is still ONE parse path and the judgement below is
    untouched — the reader simply reads the whole history it was already judging."""
    records: list = []
    try:
        # SPEC-0190 rule 4 — the WHOLE journal; T-13139 — declared: the land rows only.
        for event in journal.segment_rows(events_path, types=("land_completed",)):
            if not isinstance(event, dict) or event.get("type") != "land_completed":
                continue
            data = event.get("data")
            if not isinstance(data, dict) or data.get("status") != "ok":
                continue                  # an ABORTed land's timings prove nothing about a trend
            metrics = data.get("verify_metrics")
            if not isinstance(metrics, dict):
                continue
            record = metrics.get("per_file_durations")
            if not isinstance(record, dict):
                continue
            rows = record.get("slowest_files")
            if not isinstance(rows, list) or not rows:
                continue                  # no recorded tail ⇒ this land is not an observation
            entries = {}
            for row in rows:
                if not isinstance(row, dict):
                    continue
                name = row.get("file")
                wall = row.get("wall_ms")
                if not isinstance(name, str) or not name.strip():
                    continue
                if isinstance(wall, bool) or not isinstance(wall, int):
                    continue              # a non-integer wall is not a measurement
                entries[name.strip()] = {"wall_ms": wall, "outcome": row.get("outcome")}
            if entries:
                records.append(entries)
    except (OSError, UnicodeDecodeError):
        return []
    return records



def _median(values: list) -> int:
    ordered = sorted(values)
    n = len(ordered)
    return ordered[n // 2] if n % 2 else (ordered[n // 2 - 1] + ordered[n // 2]) // 2



def slowest_decile_changes(events_path, window_lands: int = SLOWEST_CHANGE_WINDOW_LANDS,
                           min_prior_lands: int = SLOWEST_CHANGE_MIN_PRIOR,
                           growth_ratio: float = SLOWEST_CHANGE_GROWTH_RATIO,
                           min_growth_ms: int = SLOWEST_CHANGE_MIN_GROWTH_MS, *, SLOWEST_CHANGE_GROWTH_RATIO=None, SLOWEST_CHANGE_MIN_GROWTH_MS=None, SLOWEST_CHANGE_MIN_PRIOR=None, SLOWEST_CHANGE_WINDOW_LANDS=None, _SLOWEST_COMPARABLE_OUTCOME=None, _median=None, _slowest_change_result=None, _slowest_records=None) -> dict:
    """Fold the journal → what CHANGED in the recorded slowest test files (SPEC-0119 rule 19, T-11125).

    THE SUBJECT is the T-11124 record's `slowest_files` — the top-N slowest files each successful land
    names. On this suite N=10 over ~800 files, i.e. the ≥p99 band; the line therefore says "recorded
    slowest files", never claims a decile it cannot see (the record carries no more than the tail).

    TWO KINDS, and only these two:
      • ENTRANT — a file in the LATEST record that is absent from the BASELINE MEMBERSHIP (the union
        of the prior window's recorded names). MEMBERSHIP is the load-bearing word: an EXISTING,
        long-known test file that newly CLIMBS INTO the slowest set is the primary way a creep first
        shows itself, and a "never seen in any duration data" reading would miss exactly that case.
      • GROWN — a file in BOTH whose latest wall clears TWO bars against the MEDIAN of its baseline
        walls: a relative one (`growth_ratio`) and an absolute one (`min_growth_ms`).

    WHY THE BASELINE IS A MEDIAN OF A WINDOW, not the previous land. Comparing to a single prior run
    fires on ordinary run-to-run jitter, and a view that fires on noise is skipped within a week — the
    precise failure AC2 exists to prevent. The median over the window is the noise-robust reading and,
    on a genuinely unchanged series, is exactly the unchanged value, so the clean case stays silent.
    The two bars work together: the ratio makes the test scale-free, the ms floor keeps a small file's
    wobble mute (a 400ms file doubling is not news; a 40s file growing 25% is).

    ONLY `passed` OBSERVATIONS COMPARE. A file that failed, timed out, was killed by fail-fast, or
    never launched exits early or is capped, so its wall is not comparable across lands — reporting it
    would manufacture growth and shrinkage out of test OUTCOMES. Such an entry scores on neither side.
    Dropping it hides nothing: T-11124's record still carries every outcome, and this view's subject is
    duration comparability, not test health.

    THE EVIDENCE FLOOR. With fewer than `min_prior_lands` prior records the fold returns a clean
    zero-count result: with one or two lands there is no previous state to have changed from, and
    every file would read as an entrant. This is also why a freshly-started series (the real journal
    right after T-11124) says nothing at all — by design, not by accident (SPEC-0119 rule 3: a
    report-only surface must never nag on an unknown).

    Args:
      events_path: the journal to fold (missing / unreadable ⇒ a clean zero-count result, so a repo
        with no recorded land — the engine kernel before T-11124 — is never retro-charged).
      window_lands / min_prior_lands / growth_ratio / min_growth_ms: the settled parameters above,
        injectable for tests.

    Returns `{"lens", "count", "entrants", "grown", "window_lands", "observed_lands", "next"}` — the
    sibling shape, where `entrants` is a list of `{"file", "wall_ms"}` and `grown` a list of
    `{"file", "wall_ms", "baseline_ms", "growth_pct"}`. PURE: reads the journal — every segment of
    it (T-11595) — writes nothing (the SPEC-0149 §2 boundary), performs no action, and moves no
    exit code."""
    records = _slowest_records(events_path)
    try:
        window = int(window_lands)
    except (TypeError, ValueError):
        window = SLOWEST_CHANGE_WINDOW_LANDS
    try:
        floor = int(min_prior_lands)
    except (TypeError, ValueError):
        floor = SLOWEST_CHANGE_MIN_PRIOR
    try:
        ratio = float(growth_ratio)
    except (TypeError, ValueError):
        ratio = SLOWEST_CHANGE_GROWTH_RATIO
    try:
        min_growth = int(min_growth_ms)
    except (TypeError, ValueError):
        min_growth = SLOWEST_CHANGE_MIN_GROWTH_MS
    if len(records) < floor + 1:
        # Too little history to speak: not even ONE observation plus `floor` priors to compare it to.
        return _slowest_change_result([], [], window, len(records), floor)
    latest = records[-1]
    baseline = records[-(window + 1):-1] if window > 0 else records[:-1]
    membership = {name for record in baseline for name in record}
    walls: dict = {}
    for record in baseline:
        for name, row in record.items():
            if row.get("outcome") != _SLOWEST_COMPARABLE_OUTCOME:
                continue                      # a non-passed baseline sample is not comparable
            walls.setdefault(name, []).append(row["wall_ms"])
    entrants, grown = [], []
    for name, row in latest.items():
        if row.get("outcome") != _SLOWEST_COMPARABLE_OUTCOME:
            continue                          # a non-passed latest sample compares against nothing
        if name not in membership:
            entrants.append({"file": name, "wall_ms": row["wall_ms"]})
            continue
        prior = walls.get(name)
        if not prior:
            continue                          # in the set, but never comparably measured ⇒ silent
        base = _median(prior)
        delta = row["wall_ms"] - base
        if base > 0 and delta >= min_growth and row["wall_ms"] >= base * (1.0 + ratio):
            grown.append({"file": name, "wall_ms": row["wall_ms"], "baseline_ms": base,
                          "growth_pct": int(round(100.0 * delta / base))})
    entrants.sort(key=lambda e: (-e["wall_ms"], e["file"]))
    grown.sort(key=lambda g: (-g["growth_pct"], g["file"]))
    return _slowest_change_result(entrants, grown, window, len(records), floor)



def _slowest_change_result(entrants: list, grown: list, window_lands: int, observed_lands: int,
                           min_prior_lands: int, *, SLOWEST_CHANGE_GROWTH_RATIO=None, SLOWEST_CHANGE_MIN_GROWTH_MS=None) -> dict:
    return {
        "lens": "slowest-test-file-changes (SPEC-0119 rule 19, T-11125) — what MOVED in the recorded "
                "slowest test files (the T-11124 `verify_metrics.per_file_durations` series) between "
                "the latest successful land and the median of the previous "
                f"{window_lands}: a file that newly ENTERED the recorded slowest set, or a member "
                "that GREW materially (at least "
                f"{int(SLOWEST_CHANGE_GROWTH_RATIO * 100)}% AND {SLOWEST_CHANGE_MIN_GROWTH_MS}ms over "
                "its baseline median). The DELTA, never the level: a slowest set exists by "
                "definition, so printing the set itself would print every land and train the reader "
                "to skip it — the same silent failure by another route. Only `passed` observations "
                "compare (an early-exiting or timed-out file's wall is not comparable, and would "
                "manufacture growth out of outcomes), and nothing is reported until at least "
                f"{min_prior_lands} prior records exist — a report-only surface must never nag on an "
                "unknown. DERIVED at read time from the journal — zero stored state, no new event, no "
                "new store, no cadence (SPEC-0142 §4). Report-only, never a gate.",
        "count": len(entrants) + len(grown),
        "entrants": entrants,
        "grown": grown,
        "window_lands": window_lands,
        "observed_lands": observed_lands,
        "next": ("test cost moved in the slow tail. A NEW entrant is a file that was not among the "
                 "recorded slowest and now is; a GROWN member is one whose wall clears both the "
                 "relative and the absolute bar against its own recent median. Neither is a defect by "
                 "itself and nothing is gated — read the named file's recent change, and either "
                 "accept the cost deliberately or file a card to bring it back down. The full "
                 "current tail is available on demand from the latest land's "
                 "`verify_metrics.per_file_durations`."
                 if (entrants or grown) else
                 "the recorded slowest test files are unchanged — no new entrant, no material "
                 "growth."),
    }



def abort_class_is_park_limit_eviction(klass, *, ABORT_CLASS_PARK_LIMIT_EVICTION=None) -> bool:
    """Is this `abort_class` the T-11819 land-reservation park-limit EVICTION (SPEC-0119 rule 27)?

    THE ONE CLASSIFICATION HOME both readers ask — this fold, and the roster part-3
    parallel-landing-health block (which cannot import it, being contracted to run against any repo
    on pure stdlib, and so carries the literal under a test that asserts the two agree).

    Compared on the STRIPPED string, matching how `_abort_rows` normalizes the field, and FAIL-CLOSED
    on anything that is not a string: a row this cannot positively identify stays an ABORT, which is
    today's reading and the direction that never silently shrinks the abort count."""
    return isinstance(klass, str) and klass.strip() == ABORT_CLASS_PARK_LIMIT_EVICTION



def abort_arm_is_caught_defect(arm, *, ABORT_ARMS_CAUGHT_DEFECT=None) -> bool:
    """May the gate-caught not-waste sentence be said of a row carrying this arm? (T-11607)

    A POSITIVE predicate, deliberately, rather than a not-in-this-list one: an allowlist fails SAFE.
    `mixed` is excluded because the sentence is true of only PART of such a row (it refused on a
    failing test AND on paperwork), and `unattributed` is excluded because we do not know — claiming
    a caught defect for a row the reader could not place would be exactly the guess the fold refuses
    to make. `None` — a gate-caught class that unions nothing — IS a caught defect, which keeps every
    single-arm class reading as it did before this card."""
    return arm is None or arm in ABORT_ARMS_CAUGHT_DEFECT



def _is_corpus_guard_assertion(text: str, *, _CORPUS_GUARD_MARKS=None) -> bool:
    """True when this recorded assertion is a CORPUS-INTEGRITY guard's refusal rather than a test's.

    PURE, and deliberately a containment test rather than an equality one: each guard appends the
    offending path and its remediation cue after the invariant opening above, so the opening is the
    stable part. A test assertion never carries one of these openings — they are the guards' own
    prose, emitted from exactly one site each."""
    return any(mark in text for mark in _CORPUS_GUARD_MARKS) if isinstance(text, str) else False



def _row_has_timed_out_layer(data: dict, *, _LAYER_TIMEOUT_OUTCOME=None) -> bool:
    """True when this abort row's STRUCTURED per-layer trail records a layer that TIMED OUT (T-12406).

    PURE, and typed element by element for the same load-bearing reason `_abort_arm_verify_failed`
    types `failing_assertions`: a `consumer_verify_layers` that is a bare string is iterable, and a
    membership test over it would walk CHARACTERS and prove nothing about any layer. A value that is
    not a list of dicts proves nothing, so it answers False and the caller falls through to a reader
    that can prove something — never into the new arm."""
    rows = data.get("consumer_verify_layers")
    if not isinstance(rows, (list, tuple)):
        return False
    return any(isinstance(r, dict) and r.get("outcome") == _LAYER_TIMEOUT_OUTCOME for r in rows)



def _is_layer_timeout_assertion(text: str, *, _LAYER_TIMEOUT_ASSERTION_MARK=None) -> bool:
    """True when this recorded assertion is the LAYER-TIMEOUT sentence rather than a test's failure.

    Containment on the assertion ELEMENT, never on a flattened blob — the same shape as
    `_is_corpus_guard_assertion`, and for the same reason: only a per-element test can say that
    NOTHING ELSE is in the failing set."""
    return _LAYER_TIMEOUT_ASSERTION_MARK in text if isinstance(text, str) else False



def _abort_arm_rebaseline(data: dict, *, ABORT_ARM_AUTHORIZATION=None, ABORT_ARM_AUTHORIZATION_MARK=None, ABORT_ARM_INLAND_REAUDIT=None, ABORT_ARM_UNATTRIBUTED=None, ABORT_ARM_WAIVE_COVERAGE=None, ABORT_ARM_WAIVE_COVERAGE_MARK=None) -> str:
    """The T-11426 arm reader for `rebaseline-unauthorized`. Moved VERBATIM under the per-class
    dispatch below (T-11607) — the ordered reader, its 5 rules and its measured behaviour on the 180
    rows tabulated in the header above are UNCHANGED; only its call site moved:
      (0) T-12630: the THREE per-refusal markers, most-specific first    [structured, forward-only]
      (1) `abort_preflight`                                   -> authorization  [structured, current]
      (2) the authorization refusal's own sentence            -> authorization  [legacy AND current]
      (3) the waive-coverage refusal's own sentence           -> waive-coverage [legacy AND current]
      (4) `failing_assertions` / `rebaseline_bad_token_reasons` -> waive-coverage [structured belt]
      (5) otherwise                                           -> unattributed   [never guessed]

    T-12630 — RULE (0), AND WHY IT IS AN ADDITION RATHER THAN A REWRITE. Rule (1) reads the marker
    that says a PREFLIGHT refused this land and answers `authorization` — which was the only answer
    available to it, because the row carried no discriminator, and which is therefore WRONG for two
    of the three refusals that reach it. MEASURED (T-12499): every `abort_preflight` row in the fold
    fell into the authorization bucket, conflating three refusals with three different remedies.
    `_emit_land_abort` now folds each refusal's OWN marker onto the row (the markers already existed
    at the `_die` sites), so the reader can finally discriminate.

    ORDERED MOST-SPECIFIC-PROVEN-MARKER FIRST, and the order is a decision, not a default: a row may
    legitimately carry more than one preflight fact, and the narrowest proven one is the one whose
    remedy applies. Rules (1)-(5) are UNCHANGED and remain the fall-through, which is what keeps
    every HISTORICAL row — none of which can carry a forward-only marker — reading byte-identically
    to today, including the 180 tabulated above. A row proving none of the three still reaches rule
    (1) exactly as before, and one proving nothing at all still reaches `unattributed`: no row is
    guessed into the new arm.
    """
    if data.get("inland_reaudit_refusal"):
        return ABORT_ARM_INLAND_REAUDIT
    if data.get("waive_coverage_preflight"):
        return ABORT_ARM_WAIVE_COVERAGE
    if data.get("entry_authorization"):
        return ABORT_ARM_AUTHORIZATION
    if data.get("abort_preflight"):
        return ABORT_ARM_AUTHORIZATION
    reason = data.get("abort_reason")
    reason = reason if isinstance(reason, str) else ""
    if ABORT_ARM_AUTHORIZATION_MARK in reason:
        return ABORT_ARM_AUTHORIZATION
    if ABORT_ARM_WAIVE_COVERAGE_MARK in reason:
        return ABORT_ARM_WAIVE_COVERAGE
    if data.get("failing_assertions") or data.get("rebaseline_bad_token_reasons"):
        return ABORT_ARM_WAIVE_COVERAGE
    return ABORT_ARM_UNATTRIBUTED



def _abort_arm_verify_failed(data: dict, *, ABORT_ARM_CORPUS_BOOKKEEPING=None, ABORT_ARM_LAYER_TIMEOUT=None, ABORT_ARM_MIXED=None, ABORT_ARM_TEST_FAILURE=None, ABORT_ARM_UNATTRIBUTED=None, _is_corpus_guard_assertion=None, _is_layer_timeout_assertion=None, _row_has_timed_out_layer=None) -> str:
    """The T-11607 arm reader for `verify-failed` — WHICH HALF of the shared `bad` list refused.

    PER-ASSERTION, and that is the whole design (see the header above). `failing_assertions` holds
    the refusal's causes as SEPARATE list elements — a corpus guard's own message is one element,
    a failing test assertion is another — so partitioning the ELEMENTS is what makes SOLE-GUARD
    distinguishable from MIXED at all. A scan of the flattened `abort_reason` blob can say "a guard
    is in here"; it can never say "and nothing else is".

      (1) every readable assertion is a corpus-guard message -> corpus-bookkeeping
      (1a) a TIMED-OUT layer in the structured trail, and every non-guard assertion is that layer's
           timeout sentence                                  -> layer-timeout [T-12406]
      (1b) a timed-out layer beside anything else            -> mixed
      (1c) LEGACY BELT (no structured trail): a SOLE timeout sentence -> layer-timeout
      (2) no assertion is                                    -> test-failure
      (3) both kinds present                                 -> mixed        [never either alone]
      (4) no `failing_assertions` at all: the LEGACY BELT — a guard mark in `abort_reason`, with
          `failing_tests` telling SOLE from MIXED
      (5) nothing proved                                     -> unattributed [never guessed]
    """
    # STRUCTURED means a LIST of assertions, and the type check is load-bearing rather than defensive
    # (audit-post finding 2): a `failing_assertions` that is a bare STRING is iterable, so a bare
    # membership test would walk it CHARACTER BY CHARACTER, find no guard mark in any single letter,
    # and confidently answer `test-failure` — a row proving nothing GUESSED into an arm, which is the
    # one thing AC2 forbids. A malformed value proves nothing, so it falls through to the belt below.
    raw = data.get("failing_assertions")
    marks = [a for a in raw if isinstance(a, str)] if isinstance(raw, (list, tuple)) else []
    if marks:
        guard = [a for a in marks if _is_corpus_guard_assertion(a)]
        if len(guard) == len(marks):
            return ABORT_ARM_CORPUS_BOOKKEEPING
        # T-12406 — THE LAYER-TIMEOUT RULE, ORDERED BEFORE `test-failure`. A consumer verify LAYER
        # that ran out of wall-clock reaches this reader indistinguishable from a failing test,
        # because `worktree._run_verify_tests` appends its timeout sentence to the SAME shared `bad`
        # list WITHOUT the `_VERIFY_TIMEOUT_MARKER` the class fork keys on — so the row is emitted
        # `verify-failed` and rule (2) below, reading "no assertion is a guard message", would answer
        # `test-failure` and let the render say a real defect was caught before it landed. The
        # STRUCTURED trail is what makes the honest answer readable without parsing prose.
        non_guard = [a for a in marks if not _is_corpus_guard_assertion(a)]
        timeouts = [a for a in non_guard if _is_layer_timeout_assertion(a)]
        if timeouts and _row_has_timed_out_layer(data):
            # SOLE only when the timeout sentences are the WHOLE non-guard set AND no guard fired.
            # Anything else — a timed-out layer beside a real failing test, or beside a corpus-guard
            # message — is MIXED: attributed to neither arm alone, exactly as the existing mixed arm
            # is, because splitting one abort between arms would invent a division the row does not
            # record and placing it whole in either would overstate that arm.
            if not guard and len(timeouts) == len(non_guard):
                return ABORT_ARM_LAYER_TIMEOUT
            return ABORT_ARM_MIXED
        # LEGACY BELT, bounded DELIBERATELY to the sole-assertion case. A row predating the T-11973
        # trail has no structured proof, so the sentence is all there is; with exactly ONE assertion
        # and no guard mark, that sentence IS the whole refusal and the reading is safe. With more
        # than one, nothing in the row can say whether the other assertions are tests that genuinely
        # failed, so the row falls through UNCHANGED rather than being guessed into the new arm.
        if (not guard and len(marks) == 1 and _is_layer_timeout_assertion(marks[0])):
            return ABORT_ARM_LAYER_TIMEOUT
        if not guard:
            return ABORT_ARM_TEST_FAILURE
        return ABORT_ARM_MIXED
    # LEGACY BELT — a row predating `failing_assertions` (none exists in this repo's journal: the key
    # is present on 185/185 measured rows) or one whose list is unreadable. `failing_tests` is used
    # ONLY to tell sole from mixed once a guard mark is already proven present, NEVER on its own: 4
    # measured rows carry an EMPTY `failing_tests` and are genuine verify failures (a pinned-engine
    # driver error names no test file), so "no failing test ⇒ bookkeeping" would mis-bucket them.
    reason = data.get("abort_reason")
    reason = reason if isinstance(reason, str) else ""
    if _is_corpus_guard_assertion(reason):
        return ABORT_ARM_MIXED if data.get("failing_tests") else ABORT_ARM_CORPUS_BOOKKEEPING
    return ABORT_ARM_UNATTRIBUTED



def _abort_arm(klass: str, data: dict, *, ABORT_ARM_SPLIT_CLASSES=None, ABORT_ARM_UNATTRIBUTED=None, _ABORT_ARM_READERS=None):
    """Which ARM of a two-refusal abort class this row belongs to (T-11426 / T-11607), or None.

    Returns None for every class outside `ABORT_ARM_SPLIT_CLASSES` — those fold byte-identically to
    before these cards. For a split class the per-class reader above decides; a split class with no
    registered reader would be a contradiction between the tuple and the table, so it is reported
    `unattributed` rather than silently folded back into an undifferentiated name."""
    if klass not in ABORT_ARM_SPLIT_CLASSES:
        return None
    reader = _ABORT_ARM_READERS.get(klass)
    if reader is None:
        return ABORT_ARM_UNATTRIBUTED
    return reader(data)



def _abort_label(klass: str, arm) -> str:
    """The name a READER of the fold sees: `<class>[<arm>]` for a split class, else the bare class.

    The renderer prints THIS and never composes an arm itself, so the arm vocabulary has exactly one
    home (CHARTER §P5) and a class that unions two arms can never print as one undifferentiated name.
    """
    return f"{klass}[{arm}]" if arm else klass



def _abort_attributed_wait_ms(observations, land_ts, wall_ms):
    """T-11831 — the QUEUE WAIT this ONE abort row can PROVE, in ms, or `None`.

    THE SOURCE IS THE HEARTBEAT SERIES, not `land_completed.data.admission_wait_ms`. That field is
    the `secondary_instrument` the SPEC-0132 admission lens labels "UNDER-REPORTING (T-11119) ... Do
    not quote these figures as admission waits", and rule 27 quoted it anyway — two readers of one
    question, one forbidding what the other did (external verdict,
    `decisions/admission-wait-lens-dissonance-audit-adhoc.yaml` finding 1).

    THE FIELD IS NOT LYING, IT IS ANSWERING ABOUT THE WRONG QUEUE — which is why re-sourcing, not
    emitter-hardening, is the fix. `admission_waits` (worktree.py) is appended ONLY by
    `_verify_under_admission`, so it measures the SPEC-0132 verify-admission-slot queue and never the
    land-fairness RESERVATION. Since T-11117 serializes merge->verify->ff behind that reservation, a
    queued peer parks THERE and only the holder ever reaches the admission slot. Measured 2026-08-29:
    task/T-11799 and task/T-11618 hold reservation peaks of 8042s and 2950s with ZERO admission-slot
    heartbeats and `admission_wait_ms: 0` at `attempt_count: 1`. A literal, truthful 0 about a queue
    they never entered.

    ATTRIBUTION IS PER-LAND, AND THAT IS THE DIVERGENCE FROM THE ADMISSION LENS. Both readers resolve
    WHICH ROWS ARE THE SERIES through the one home (`journal.LAND_QUEUE_WAIT_TYPES` /
    `land_queue_wait_observation`), but they aggregate differently BECAUSE THEY ASK DIFFERENT
    QUESTIONS. `views._view_admission_series` asks "was this land queued at all", so it folds ONE peak
    per `(session_ref, branch)` and joins it to a single land. Rule 27 asks "how many minutes of THIS
    abort row were queueing", and one key routinely carries SEVERAL land rows — task/T-11799 has six.
    Taking the key-wide peak would charge every one of those rows the longest wait any of them paid.
    So the fold is taken over the heartbeats falling inside THIS land's OWN span, `[ts - wall, ts]`.

    THE FOLD IS A RESET-AWARE SEGMENT SUM, NOT A PEAK (T-11908). `waited_s` is per-PARK and RESTARTS
    at 0 when the land parks again, so a land that was displaced and re-parked journals two rising
    series inside one span. The peak this fold used to take reported only its LONGEST park while the
    land paid the SUM — an undercount by construction, in the one direction that makes a
    wait-dominated cost read gate-dominated, which is the verdict this rule's own text says the split
    decides. `journal.fold_wait_segments` cuts a new park at every DROP and sums the per-park peaks;
    a span with no reset is ONE segment and folds to exactly the peak it folded to before, so nothing
    about a single-park land moves.

    RETURNS `None` — never 0 — when the row cannot prove a wait: no `wall` to bound the span with, or
    no attributable heartbeat inside it. An unattributed row carries NO split (it joins `no_split_n`)
    rather than a zero-wait one, which is the T-0358 no-fabricated-measurement discipline this fold
    already applies to `duration_ms`, and the second half of the external verdict's fix. PURE."""
    if not observations or wall_ms is None or land_ts is None:
        return None
    # EPOCH SECONDS, not a `timedelta` — for the same external reason `aborted_land_cost` computes
    # its window that way: a MODULE-WIDE source assertion
    # (`test_spec0149_obligation_fold.test_ac2_the_fold_never_defaults_a_window`) forbids duration
    # vocabulary anywhere in `debt.py`. That guard's stated subject is `open_proof_obligations`'
    # resolution path and this span is a different concern, but the guard is DELIBERATE and not this
    # card's to narrow (SPEC-0103) — so the arithmetic is expressed to leave it untouched. Same
    # instants either way.
    land_at = land_ts.timestamp()
    span_start = land_at - (wall_ms / 1000.0)
    # SORTED ON THE STAMP before folding: the segment cut reads a DROP as a re-park, so it is only
    # meaningful in time order, and the collecting walk concatenates journal SEGMENTS in path order
    # rather than in `ts` order (SPEC-0190 rule 6). The sibling `_abort_rows` sorts for the same
    # reason. An out-of-order pair would otherwise manufacture a park that never happened.
    in_span = sorted(((stamp, waited_s) for stamp, waited_s in observations
                      if span_start <= stamp.timestamp() <= land_at),
                     key=lambda pair: pair[0])   # on the STAMP alone — a tie must never compare an
                                                 # unrecorded `waited_s` against an int
    total_s = journal.fold_wait_segments(waited_s for _stamp, waited_s in in_span)
    return None if total_s is None else int(total_s * 1000)



def _abort_phase_split(wait_ms, wall_ms):
    """T-11514, re-sourced by T-11831 — an abort row's WALL-CLOCK SPLIT: `(wait_ms, work_ms)`, or
    `(None, None)`.

    `wait_ms` is the heartbeat-attributed queue wait (`_abort_attributed_wait_ms`, which names why)
    and `work_ms` is the remainder of the land's OWN wall, `duration_ms - wait_ms`.

    THE CONTAINING WALL IS `duration_ms`, NOT `verify_duration_ms` — this is the load-bearing change
    beside the source. The reservation wait is paid BEFORE the verify starts, so it sits OUTSIDE
    `verify_duration_ms`: task/T-11799's 2026-08-28T14:53:47Z row has a 83.8min attributed wait
    against a 10.2min `verify_duration_ms`. Kept on the old queue-inclusive wall, the `wait > wall`
    guard below would refuse EVERY re-sourced row and the re-source would silently deliver no splits
    at all. `duration_ms` is the land's whole wall-clock, which is what rule 27 partitions by PHASE.

    RETURNS `(None, None)` RATHER THAN A ZERO whenever the row cannot prove the split (the T-0358
    discipline this fold already applies to `duration_ms`): either value missing; a bool (which
    `isinstance(x, int)` would otherwise admit); a negative; or a wait EXCEEDING the wall that
    contains it. That last one is a broken invariant, not a datum — deriving a negative RUN from it
    would put minutes nobody spent into the report, in the one direction this fold must not fail
    (it fires on 2 of 469 rows in the measured window). PURE: reads two numbers, decides nothing."""
    for v in (wait_ms, wall_ms):
        if isinstance(v, bool) or not isinstance(v, int) or v < 0:
            return None, None
    if wait_ms > wall_ms:
        return None, None          # a queue longer than the wall containing it — refuse, never guess
    return wait_ms, wall_ms - wait_ms



def _abort_reservation_wait(data: dict):
    """T-11690 — an abort row's LAND-RESERVATION wait in ms, or `None`.

    THE SECOND QUEUE, and it is not a slice of anything above. `_abort_phase_split` partitions the
    QUEUE-INCLUSIVE `verify_duration_ms` into the verify-admission wait and the verify RUN — an
    accounting identity over ONE wall. The land-fairness reservation (T-11117) is taken at the TOP of
    the attempt, BEFORE the merge and before step 4, so it is outside that wall entirely and no
    subtraction over it can recover the time. Folding it into `wait_ms` would corrupt the identity;
    it is reported as a THIRD phase instead, and stays a separate number because it asks for a
    DIFFERENT remedy (a peer land holding the serialized window, versus the verify slot pool).

    Measured 2026-08-27 on one completed group land (task/T-11683, sha cc5fcfa): 65 min total, 9 min
    verify, `admission_wait_ms` 0 — with 55 min of reservation wait carried in 195
    `waiting_for_land_reservation` heartbeats and in no summary field at all. That is why this rule's
    own live output read "2.6 min was QUEUE WAIT ... 1250.8 min was the verify RUN" over 174 aborts:
    not because the queue was cheap, but because the dominant queue was in nothing this fold could see.

    NEVER ZERO-FILLED, on exactly the terms `_abort_phase_split` and `duration_ms` already use: a
    pre-T-11690 row has no key, and a row whose land never reached the reservation carries `null`.
    Both are UNPROVEN, reported as such. A real `0` — an in-loop abort that took the reservation
    without waiting — is a MEASUREMENT and is admitted as one. PURE: reads a dict, decides nothing."""
    value = data.get("reservation_wait_ms")
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value



def _abort_rows(events_path, window_start, window_end, *, ABORT_PAID_VERIFY_MARKER=None, ABORT_PREFLIGHT_MARKER=None, ABORT_UNCLASSIFIED=None, _abort_arm=None, _abort_attributed_wait_ms=None, _abort_phase_split=None, _abort_reservation_wait=None, _parse_stamped_deadline=None, _window_segment_floor=None) -> list:
    """The aborted-land rows inside the window, oldest→newest (T-11368).

    Reads the SAME `land_completed` rows every sibling fold reads and admits ONLY `status == "abort"`
    — a successful land's cost is not this view's subject. FAITHFUL, never fail-closed on parse: a
    malformed line, an unparseable timestamp or a non-dict payload is skipped, never fatal. Returns
    `{"ts", "abort_class", "paid", "duration_ms", "wait_ms", "work_ms", "arm"}` per row, where
    `duration_ms` is None when
    the cost is UNDETERMINED — never 0, which would be a fabricated measurement — and `arm` is the
    T-11426 two-refusal split (None for every class that does not union two refusals).

    T-11514 — THE WALL-CLOCK SPLIT OF THAT COST, and it is the SAME SECOND READING this whole rule
    is (no new capture, no new event). T-11831 RE-SOURCED its wait half: it is the peak `waited_s`
    among this land's OWN `journal.LAND_QUEUE_WAIT_TYPES` heartbeats — the PRIMARY instrument the
    SPEC-0132 admission lens uses — and `work_ms` is the remainder of the land's own `duration_ms`.
    It is NOT `land_completed.data.admission_wait_ms`, the field that lens labels a
    `secondary_instrument` carrying "UNDER-REPORTING (T-11119) ... Do not quote these figures as
    admission waits". Rule 27 quoted it anyway, and the consequence was not cosmetic: over the 7-day
    window measured 2026-08-29 the old source reported 2.6 QUEUE minutes against 1283.1 verify-RUN
    minutes across 189 of 469 rows, so the split could only ever point at the gate. The SAME window
    re-sourced reports 7696.3 queue minutes against 3476.3 run minutes across 291 rows — the verdict
    INVERTS, which matters because this rule's own text says the split chooses the remedy
    (wait-dominated cost is a QUEUEING problem, not a gate one). See `_abort_attributed_wait_ms` for
    why the field was truthful about the wrong queue, and why attribution must be per-LAND.

    BOTH ARE None UNLESS THE ROW CAN PROVE THEM, on exactly the terms `duration_ms` already uses: a
    row with NO attributable heartbeat inside its own span is reported as CARRYING NO SPLIT (it joins
    `no_split_n`), never as a free one — a land that never queued and a land whose queueing left no
    record are different claims, and only the second is what an absent attribution proves. A row is
    admitted to the split only when both halves are non-negative ints and the wait does not exceed the
    wall — a wait larger than the wall it is contained in would mean the invariant is broken, and
    inventing a negative RUN from it would be worse than saying nothing. Nothing is back-filled.

    DECLARED HORIZON: the WHOLE logical journal (SPEC-0190 rule 4, T-11589). The window this fold's
    caller passes is EXACTLY ABORT_COST_WINDOW_DAYS = 7 days — IDENTICAL to JOURNAL_LIVE_WINDOW_DAYS,
    and rule 4 names that EQUALITY as the case that looks safe and is not. The two are the same
    length only in nominal terms: rotation moves rows on `ts < boundary`, so on an ordinary read the
    oldest hours of the declared week are ALREADY in an archive segment, and any skew or inclusivity
    choice widens the gap. This fold does not merely total those minutes — `_abort_trend` compares an
    OLDER half against a NEWER one — so losing the oldest end BIASES the comparison itself rather
    than merely shortening it, and in the direction that manufactures alarm: the OLDER half is the
    half rotation eats first, so the ratio `recent / older` is inflated and a class whose cost is
    flat reads GROWING — not because its cost rose, but because the half it is measured against is
    no longer in the file. (Rotate the older half away ENTIRELY and the verdict is an honest
    `unknown` — no older half to compare with; a PARTLY rotated one is worse, because it is
    confident and wrong.) So it takes the
    ARCHIVE branch (`journal.segment_rows`), which reads each segment through the SAME `fold_rows`
    primitive — one physical read path, one parse path, and the T-11453 `rows_memo` scope still
    serves each segment.

    ORDER-SENSITIVITY (SPEC-0190 rule 6, the reader-specific judgement). Segments concatenate in
    `segment_paths` order, not in `ts` order — but this reader SORTS EXPLICITLY on the parsed `ts`
    before returning, and its window filter is a pure per-row predicate. So the cross-segment
    reordering rule 5 admits can only permute rows comparing EQUAL on `ts`; it can neither drop a row
    nor let an older one outrank a newer."""
    rows: list = []
    # T-11831 — the QUEUE-WAIT observations, collected in this SAME single pass. Keyed by
    # `(session_ref, branch)`, the key the wait heartbeats and the land row share. Bounded to stamps
    # at-or-before `window_end`: a land INSIDE the window can have begun queueing long before
    # `window_start` (measured: 134 minutes), so filtering by the window's START would silently drop
    # exactly the longest waits this rule exists to surface — but nothing AFTER the window's end can
    # belong to a land inside it.
    waits: dict = {}
    try:
        # SPEC-0190 rule 4 (T-12030) — the segments the window can REACH, not the whole journal. The
        # floor is `window_start` widened by `_window_segment_floor`'s margin, which is what keeps the
        # queue-WAIT collection above correct: a wait may begin long before `window_start` (134
        # minutes, measured), so the margin has to cover the widest thing this pass collects, not just
        # the abort rows. Every in-loop predicate below is unchanged and still decides each row.
        # T-13139 — the walk is `AbortRowsReducer` (the wait heartbeats are ~56k rows a week, so a
        # typed list of them would be the materialisation this card removes): inside the debt seam's
        # scope it is the reducer the one pass already fed, outside it one bounded walk. The segment
        # selection is applied to the reducer's per-segment record, and both lists keep walk order.
        floor = _window_segment_floor(window_start, days=0)
        reducer = journal.reduce_journal(
            events_path, lambda: AbortRowsReducer(_parse_stamped_deadline), name="abort_rows", since=floor)
        allowed = journal.segment_indices(events_path, floor) if floor else None
        for seg, key, stamp, waited_s in reducer.waits:
            if (allowed is None or seg in allowed) and stamp <= window_end:
                waits.setdefault(key, []).append((stamp, waited_s))
        for seg, event in reducer.aborts:
            if allowed is not None and seg not in allowed:
                continue
            data = event.get("data")
            stamp = _parse_stamped_deadline(event.get("ts"))   # the ONE ts parser here (CHARTER §P5)
            if stamp is None or not (window_start <= stamp <= window_end):
                continue
            klass = data.get("abort_class")
            klass = klass.strip() if isinstance(klass, str) and klass.strip() else ABORT_UNCLASSIFIED
            marker = data.get(ABORT_PAID_VERIFY_MARKER)
            paid = bool(marker) and not isinstance(marker, bool)
            # T-11777 — the row's OWN recorded refusal point, read on the same terms as `paid`: a
            # truthy `abort_preflight` means this land refused at the step-4a preflight, before the
            # suite and before the admission slot. Absent ⇒ False, which is what every pre-T-10850
            # row and every non-preflight refusal already means.
            preflight = bool(data.get(ABORT_PREFLIGHT_MARKER))
            wall = data.get("duration_ms")
            if isinstance(wall, bool) or not isinstance(wall, int) or wall < 0:
                wall = None               # UNDETERMINED — reported as such, never as free
            rows.append({"ts": stamp, "abort_class": klass, "paid": paid, "duration_ms": wall,
                         "preflight": preflight,          # T-11777 — its own refusal point
                         "wait_ms": None, "work_ms": None,      # attributed after the walk, below
                         "_key": (event.get("session_ref"), data.get("branch")),
                         # T-11690: the SECOND queue, read INDEPENDENTLY of the pair above — a row
                         # may prove one and not the other, and dropping the reservation wait because
                         # the verify split is unprovable would discard the DOMINANT cost on exactly
                         # the rows (aborted before step 4) where it is the whole cost.
                         "reservation_wait_ms": _abort_reservation_wait(data),
                         "arm": _abort_arm(klass, data)})   # T-11426 — None for a single-arm class
    except (OSError, UnicodeDecodeError):
        return []
    # ATTRIBUTION HAPPENS AFTER THE WALK, not inside it, and that ordering is load-bearing twice: a
    # land's heartbeats are journaled BEFORE its `land_completed` row (so they are not yet collected
    # when the row is read), and segments concatenate in `segment_paths` order rather than `ts` order
    # (SPEC-0190 rule 5), so no single-pass ordering assumption is safe. A row whose wait cannot be
    # attributed keeps `None` for both halves and so joins `no_split_n` — never a zero-wait split.
    for row in rows:
        wait_ms = _abort_attributed_wait_ms(waits.get(row.pop("_key")), row["ts"], row["duration_ms"])
        row["wait_ms"], row["work_ms"] = _abort_phase_split(wait_ms, row["duration_ms"])
    rows.sort(key=lambda r: r["ts"])
    return rows



class AbortRowsReducer:
    """`_abort_rows`' walk as a REDUCER (T-13139): the land-queue wait heartbeats as `(segment, key,
    stamp, waited_s)` and the ABORTED `land_completed` rows, each in walk order — the two things the
    fold keeps, and nothing else. `parse_ts` is the host's ONE ts parser, the one `_abort_rows` reads."""

    def __init__(self, parse_ts):
        self._parse = parse_ts
        self._keys: dict = {}     # one shared `(session_ref, branch)` per land: its heartbeats repeat it
        self.waits: list = []
        self.aborts: list = []
        self._raw: list = []      # T-13309 — per `waits` entry its raw `ts` (re-parsed on load)

    def add(self, seq, seg, event, line) -> None:
        # The wait series, resolved through the ONE shared home the admission lens also reads
        # (`journal.land_queue_wait_observation`) — never a private type list and never the
        # `secondary_instrument` field that lens forbids quoting.
        observation = journal.land_queue_wait_observation(event)
        if observation is not None:
            key, waited_s = observation
            stamp = self._parse(event.get("ts"))
            if stamp is not None:
                self.waits.append((seg, self._keys.setdefault(key, key), stamp, waited_s))
                self._raw.append(event.get("ts"))
            return
        if event.get("type") != "land_completed":
            return
        data = event.get("data")
        if not isinstance(data, dict) or data.get("status") != "abort":
            return
        self.aborts.append((seg, event))

    # T-13309 — the whole-history index's summary protocol (`journal._summary_identity`). The key names
    # the bound ts parser (configuration); a summary stores each wait's RAW ts and each abort row as its
    # own JSON text (key order kept), re-derived on load through that same parser / json.loads.
    # It holds one segment and no segment index: `at_segment` re-places it.
    def summary_key(self):
        name = f"{getattr(self._parse, '__module__', '')}.{getattr(self._parse, '__qualname__', '<?>')}"
        if "<" in name:                    # a lambda / local function: its name does not identify it
            raise ValueError("the bound parser has no stable name")
        return {"v": 1, "parse": name}

    def summary(self):
        if len({w[0] for w in self.waits} | {a[0] for a in self.aborts}) > 1:
            raise ValueError("a per-segment summary holds one segment's walked rows")
        return {"waits": [[list(key), raw, waited] for (_s, key, _st, waited), raw
                          in zip(self.waits, self._raw)],
                "aborts": [json.dumps(ev) for _s, ev in self.aborts]}

    def load_summary(self, state) -> None:
        self.waits, self._raw = [], []
        for key, raw, waited in state["waits"]:
            stamp = self._parse(raw)
            if stamp is None:
                raise ValueError("a stored wait no longer parses")
            key = tuple(key)
            self.waits.append((None, self._keys.setdefault(key, key), stamp, waited))
            self._raw.append(raw)
        self.aborts = [(None, json.loads(text)) for text in state["aborts"]]

    def at_segment(self, seg) -> None:
        self.waits = [(seg, k, st, w) for _s, k, st, w in self.waits]
        self.aborts = [(seg, ev) for _s, ev in self.aborts]

    def prepend(self, older) -> None:
        self.waits, self.aborts = older.waits + self.waits, older.aborts + self.aborts
        self._raw = older._raw + self._raw


def _abort_group(klass: str, paid: bool, preflight: bool = False, *, ABORT_GATE_CAUGHT_CLASSES=None, ABORT_INCONCLUSIVE_CLASSES=None) -> str:
    """Which of the never-summed groups a row belongs to (T-11368, T-11777).

    THE ORDER IS THE ARGUMENT. `paid` is checked FIRST and the class name LAST, because the marker is
    the measurement and the class name is only a label: an unpaid `verify-failed` (were one ever
    written) is an EARLY refusal whatever it is called, and pricing it as a caught defect would put
    minutes nobody spent into the gate's column. `preflight` is checked between them, and for the
    same reason one step finer (T-11777): the row records WHERE it refused, and a row that refused at
    the step-4a preflight did not pay the full verify — so it belongs in neither the paid-and-failed
    group nor the paid-then-refused-on-bookkeeping one, whatever its class name says. Its minutes are
    still reported, under `preflight-refused`, which names the refusal point the row itself recorded.

    `preflight` DEFAULTS FALSE so the signature stays call-compatible, and a row that never records
    the marker folds exactly as it did before this card. PURE: three booleans-and-a-string in, one
    group name out."""
    if not paid:
        return "early"
    if preflight:
        return "preflight-refused"
    if klass in ABORT_GATE_CAUGHT_CLASSES:
        return "gate-caught"
    if klass in ABORT_INCONCLUSIVE_CLASSES:
        return "inconclusive"
    return "process-refusal"



def _abort_trend(recent_ms: int, older_ms: int, total_ms: int, *, ABORT_COST_DECAY_RATIO=None, ABORT_COST_GROWTH_RATIO=None, ABORT_COST_TREND_FLOOR_MS=None) -> str:
    """The DECAYING / GROWING / STANDING reading over the window's two halves (T-11368, X-1039).

    THE SUBJECT IS EVERY DETERMINED MINUTE THE CLASS REPORTS — paid AND early alike — not only its
    paid ones. Corrected at audit-post pass 1: the `early` group carries REPORTED minutes (764/week
    on this repo), so a paid-only trend would print the largest early class's cost with no trend
    beside it, re-creating the raw-minutes-only reading inside the mechanism built to prevent it.

    Returns `unknown` rather than guessing whenever the comparison would be noise: below the cost
    floor, or with no older half to compare against. That silence is deliberate — the whole point of
    this reading is to stop a reader chasing a cost that is already going away, and a trend verdict
    manufactured from two small numbers would send them somewhere else that is just as wrong."""
    if total_ms < ABORT_COST_TREND_FLOOR_MS:
        return "unknown"
    if older_ms <= 0:
        return "unknown"        # NO OLDER HALF ⇒ nothing to have changed FROM (audit-post pass 2)
    if recent_ms <= ABORT_COST_DECAY_RATIO * older_ms:
        return "decaying"
    if recent_ms >= ABORT_COST_GROWTH_RATIO * older_ms:
        return "growing"
    return "standing"



def aborted_land_cost(events_path, window_days: int = ABORT_COST_WINDOW_DAYS, now=None, *, ABORT_COST_GROUPS=None, ABORT_COST_MATERIAL_MS=None, ABORT_COST_WINDOW_DAYS=None, _abort_group=None, _abort_label=None, _abort_rows=None, _abort_trend=None, _aborted_land_cost_result=None, abort_class_is_park_limit_eviction=None) -> dict:
    """Fold the journal → what ABORTED lands COST, split by abort class (SPEC-0119 rule 27, T-11368).

    THE SUBJECT is `land_completed` rows with `status == "abort"` inside the trailing window. Each is
    split three ways that the headers above argue in full: PAID a verify vs refused EARLY (by the
    `verify_mode` marker, never by the class name — T-10850), cost DETERMINED vs UNDETERMINED (never
    zero-filled), and — for a class name that unions TWO refusals of different MOVABILITY — by ARM
    (`_abort_arm`, T-11426), so a reader never sees the two folded into one remedy. Classes are
    grouped into the never-summed groups — and a row that records its OWN refusal point at the
    step-4a preflight is bucketed by THAT rather than by its class name (`preflight-refused`,
    T-11777), because such a row never paid the full verify the reclaimable group describes. Each
    carries a
    TREND computed over the window's own two halves so a DECAYING cost is distinguishable from a
    STANDING one (the X-1039 requirement).

    CLEAN means nothing cost anything worth reporting: `count` is the number of aborts that PAID a
    verify, or whose determined cost clears `ABORT_COST_MATERIAL_MS`, or whose cost is UNDETERMINED.
    A window of instant `uncommitted-dirt` refusals folds to 0 → the caller suppresses.

    Args:
      events_path: the journal to fold (missing / unreadable ⇒ a clean zero-count result, so a repo
        that has never aborted a land is never retro-charged).
      window_days / now: the window, injectable for tests.

    Returns `{"lens", "now", "count", "aborts", "classes", "groups", "window_days", "undetermined",
    "trivial", "next"}` where `classes` is a list of
    `{"class", "arm", "label", "n", "paid", "early", "undetermined", "minutes", "group", "trend"}`
    keyed by the (class, ARM, GROUP) TRIPLE — a MIXED class appears once per (arm, group) it has rows
    in, so no total can contain another partition's minutes — and `groups` maps
    each group name to `{"n", "minutes"}`. PURE: reads one file, writes nothing (the SPEC-0149 §2
    boundary), performs no action, emits no event and moves no exit code."""
    now = now or datetime.now(timezone.utc)
    try:
        days = int(window_days)
    except (TypeError, ValueError):
        days = ABORT_COST_WINDOW_DAYS
    days = max(1, days)
    # THE WINDOW IS COMPUTED IN EPOCH SECONDS, not with a `timedelta`, and the reason is external to
    # this fold: SPEC-0149's one-window rule is guarded by a MODULE-WIDE source assertion
    # (`test_spec0149_obligation_fold.test_ac2_the_fold_never_defaults_a_window`) that forbids
    # duration vocabulary anywhere in `debt.py`. That guard's own docstring scopes the invariant to
    # `open_proof_obligations`' resolution path — this reporting window is a different concern
    # entirely — but the guard is deliberate and NOT this card's to narrow, so the arithmetic is
    # expressed in a way that leaves the invariant it protects untouched. Same instants, no duration
    # type in this module. (Followup filed to narrow the guard to its stated subject.)
    _span = float(days) * 86400.0
    start = datetime.fromtimestamp(now.timestamp() - _span, tz=timezone.utc)
    midpoint = datetime.fromtimestamp(now.timestamp() - _span / 2.0, tz=timezone.utc)
    rows = _abort_rows(events_path, start, now)
    # T-12396 — THE EVICTIONS LEAVE THE POPULATION HERE, BEFORE ANY FOLD TOUCHES THEM, and that
    # placement is the whole implementation: `by_class`, `groups`, `count`, `undetermined`, `trivial`,
    # the phase `split` and the `aborts` total below all derive from `rows`, so excluding the class at
    # the source makes every one of them true of the non-evicted set BY CONSTRUCTION. No clause
    # downstream subtracts anything, and none can be forgotten. (A later partition would have to
    # unwind five accumulators and the trend halves — the shape that leaves one of them stale.)
    # `.get`, not `[...]`, though `_abort_rows` always SETS the key (it normalizes a missing one to
    # ABORT_UNCLASSIFIED) and the fold below subscripts it directly. The partition runs FIRST, so a
    # raise here would take out the whole report-only view rather than one row; `.get` costs nothing
    # and fails in the direction the predicate already promises — a row that cannot be positively
    # identified stays an ABORT, never a silently-shrunk count (audit-post pass 2).
    evicted = [r for r in rows if abort_class_is_park_limit_eviction(r.get("abort_class"))]
    rows = [r for r in rows if not abort_class_is_park_limit_eviction(r.get("abort_class"))]
    # THE WAIT IS WHAT THE ROWS PROVE, NEVER WHAT THEY IMPLY. `reservation_wait_ms` is the land's own
    # recorded wait for the reservation (T-11690); a row that does not carry it is counted in `n` and
    # excluded from `waited_n`, so the minutes are always reported WITH the coverage that makes them
    # honest — the `split_n` discipline, reused, and the reason the render never prints a bare figure.
    _ev_waits = [r["reservation_wait_ms"] for r in evicted if r.get("reservation_wait_ms") is not None]
    evicted_result = {
        "n": len(evicted),
        "waited_minutes": round(sum(_ev_waits) / 60000.0, 1) if _ev_waits else 0.0,
        "waited_n": len(_ev_waits),
    }
    # KEYED BY (class, group), NEVER BY CLASS ALONE — the audit-post pass-2 correction, and it is a
    # correctness fix rather than a refinement. A class can be MIXED: `rebaseline-unauthorized` splits
    # by `abort_preflight` into a cheap pre-verify refusal and an expensive post-verify one under ONE
    # name (T-10850, the very finding that made the marker the measurement). Folding such a class into
    # one preferred group put its EARLY minutes inside the PAID group's total — which, for a paid
    # non-gate class, is the RECLAIMABLE total (T-11777 closes the same leak one step finer: a row
    # whose OWN payload records a step-4a preflight refusal is bucketed by that refusal point, so a
    # class NAME can no longer carry a cheap preflight refusal into the paid-a-full-verify total).
    # That is minutes nobody spent on bookkeeping being
    # reported as reclaimable, and it breaks the four-groups-never-summed rule from the inside. Keying
    # by the pair makes every group total the sum of its OWN rows, by construction.
    #
    # T-11426 EXTENDS THAT KEY BY THE ARM, for the same reason one level down. `rebaseline-unauthorized`
    # is one class NAME over TWO refusals with different MOVABILITY — the authorization arm moved WHOLE
    # to the step-4a preflight (T-10850), the waive-coverage arm only in PART (T-11479 moved its
    # token-binding half there; its coverage half still needs the full pinned run) — and BOTH sit
    # in the paid group, so the (class, group) pair does not separate them. Keying by the TRIPLE makes
    # every count, every minutes total AND every trend the property of ONE arm by construction, which
    # is why no separate trend path is needed: `_abort_trend` already reads this entry's own halves.
    by_class: dict = {}
    for row in rows:
        group = _abort_group(row["abort_class"], row["paid"], row.get("preflight", False))
        arm = row.get("arm")
        entry = by_class.setdefault((row["abort_class"], arm, group), {
            "class": row["abort_class"], "arm": arm,
            "label": _abort_label(row["abort_class"], arm), "group": group,
            "n": 0, "paid": 0, "early": 0,
            "undetermined": 0, "_ms": 0, "_recent_ms": 0, "_older_ms": 0, "_reportable": 0,
            # T-11514: the wall-clock split, accumulated over the rows of THIS (class, arm, group)
            # that CARRY it. `split_n` is reported beside the minutes so a reader can see how much of
            # the entry the split actually covers — a partial split presented as if it covered the
            # whole entry would be the same over-reading the never-zero-fill rule exists to prevent.
            "_wait_ms": 0, "_work_ms": 0, "_split_n": 0,
            # T-11690: the SECOND queue, with its OWN coverage count for the same reason `_split_n`
            # has one — it is proven by a different key on a different population of rows.
            "_res_ms": 0, "_res_n": 0,
        })
        entry["n"] += 1
        entry["paid" if row["paid"] else "early"] += 1
        # T-11514: accumulated INDEPENDENTLY of `duration_ms` below, and deliberately BEFORE its
        # `continue`: a row whose whole-land wall is UNDETERMINED can still carry a perfectly good
        # verify split, and dropping it would discard a measurement the row does prove.
        if row.get("wait_ms") is not None:
            entry["_wait_ms"] += row["wait_ms"]
            entry["_work_ms"] += row["work_ms"]
            entry["_split_n"] += 1
        # T-11690: accumulated on its OWN condition, BEFORE the `duration_ms` continue and beside the
        # verify split rather than inside it — a row that proves the reservation wait and nothing
        # else still proves the reservation wait.
        if row.get("reservation_wait_ms") is not None:
            entry["_res_ms"] += row["reservation_wait_ms"]
            entry["_res_n"] += 1
        wall = row["duration_ms"]
        if wall is None:
            entry["undetermined"] += 1
            entry["_reportable"] += 1        # an unknown cost is never a clean one
            continue
        entry["_ms"] += wall
        if row["ts"] >= midpoint:
            entry["_recent_ms"] += wall
        else:
            entry["_older_ms"] += wall
        if row["paid"] or wall >= ABORT_COST_MATERIAL_MS:
            entry["_reportable"] += 1
    classes, groups = [], {name: {"n": 0, "minutes": 0.0} for name in ABORT_COST_GROUPS}
    count = undetermined = trivial = 0
    for entry in by_class.values():
        minutes = round(entry["_ms"] / 60000.0, 1)
        group = entry["group"]
        classes.append({
            "class": entry["class"], "arm": entry["arm"], "label": entry["label"],
            "n": entry["n"], "paid": entry["paid"],
            "early": entry["early"], "undetermined": entry["undetermined"],
            "minutes": minutes, "group": group,
            # T-11514 — WAIT vs WORK, for the rows that carry the split. `split_n` is what keeps the
            # two minute figures honest: they are the cost of THOSE rows, never of the entry's whole
            # `n`, and they are never summed into `minutes` (which is the whole-land wall and already
            # contains them).
            "wait_minutes": round(entry["_wait_ms"] / 60000.0, 1),
            "work_minutes": round(entry["_work_ms"] / 60000.0, 1),
            "split_n": entry["_split_n"],
            # T-11690 — the SECOND queue's minutes, kept as their OWN column. Never added into
            # `wait_minutes` (which is the verify-admission queue and only that) and never into
            # `work_minutes` (which is the verify RUN, and the reservation is not inside it at all);
            # `reservation_n` is what keeps these minutes honest, exactly as `split_n` does above.
            "reservation_minutes": round(entry["_res_ms"] / 60000.0, 1),
            "reservation_n": entry["_res_n"],
            # The trend is computed from THIS entry's own halves, so it is per (class, arm, group) —
            # the same partition the count is (T-11426 AC3). A correct count under a union trend would
            # leave the misleading half in place, which is the whole finding.
            "trend": _abort_trend(entry["_recent_ms"], entry["_older_ms"], entry["_ms"]),
        })
        groups[group]["n"] += entry["n"]
        groups[group]["minutes"] = round(groups[group]["minutes"] + minutes, 1)
        count += entry["_reportable"]
        undetermined += entry["undetermined"]
        trivial += entry["n"] - entry["_reportable"]
    classes.sort(key=lambda c: (-c["minutes"], c["label"], c["group"]))
    # T-11514: the window-wide split, summed from the SAME per-entry accumulators so it can never
    # disagree with the per-class figures, and reported with its OWN coverage count (`split_n`) plus
    # the number of aborts carrying NO split — because "how much of an aborted land is queueing"
    # is a question about the window, and a reader must be able to see how much of the window
    # answered it. Not a headline over the never-summed groups: it is a partition of the SAME
    # minutes by PHASE, orthogonal to the group partition, and it is never added to any group total.
    split = {
        "wait_minutes": round(sum(c["wait_minutes"] for c in classes), 1),
        "work_minutes": round(sum(c["work_minutes"] for c in classes), 1),
        "split_n": sum(c["split_n"] for c in classes),
        "no_split_n": len(rows) - sum(c["split_n"] for c in classes),
        # T-11690 — the SECOND queue at window scale, summed from the SAME per-entry accumulators so
        # it can never disagree with the per-class figures, and carrying its own coverage counts.
        "reservation_minutes": round(sum(c["reservation_minutes"] for c in classes), 1),
        "reservation_n": sum(c["reservation_n"] for c in classes),
        "no_reservation_n": len(rows) - sum(c["reservation_n"] for c in classes),
        # THE DERIVED TOTAL, offered only because both components are printed beside it. Summing the
        # two queues is safe HERE — where a reader can still see which is which — and is exactly what
        # would be unsafe on the `land_completed` row, where one collapsed field would name neither
        # remedy. The value answers "how much of this cost was QUEUEING at all", which is the question
        # that used to read 0.0 min while a land spent 55 of its 65 minutes in a queue.
        "queue_wait_minutes": round(sum(c["wait_minutes"] + c["reservation_minutes"]
                                        for c in classes), 1),
    }
    return _aborted_land_cost_result(now, classes, groups, days, len(rows), count, undetermined,
                                     trivial, split, evicted_result)



def _aborted_land_cost_result(now, classes: list, groups: dict, window_days: int, aborts: int,
                              count: int, undetermined: int, trivial: int,
                              split: "dict | None" = None,
                              evicted: "dict | None" = None) -> dict:
    return {
        # T-12396 — the park-limit EVICTIONS, reported APART from every abort figure beside them and
        # added to none of them. Defaulted so every existing caller and probe keeps today's call
        # exactly, and defaulted to a zero COUNT rather than to absent: a window with no eviction has
        # provably none, which is a different claim from an unmeasured one.
        "evicted": evicted if evicted is not None else {"n": 0, "waited_minutes": 0.0,
                                                        "waited_n": 0},
        # T-11514 — the window-wide wait/work split (see `aborted_land_cost`). Defaulted so every
        # existing caller and probe keeps today's call exactly.
        "split": split if split is not None else {"wait_minutes": 0.0, "work_minutes": 0.0,
                                                  "split_n": 0, "no_split_n": aborts,
                                                  # T-11690 — the second queue's defaults, on the
                                                  # same never-fabricate terms: nothing measured
                                                  # means nothing covered, never zero minutes proven.
                                                  "reservation_minutes": 0.0, "reservation_n": 0,
                                                  "no_reservation_n": aborts,
                                                  "queue_wait_minutes": 0.0},
        "lens": "aborted-land cost (SPEC-0119 rule 27, T-11368 / a consumer's X-1036, corrected by "
                f"X-1039) — what the last {window_days} day(s) of ABORTED lands COST, split by "
                "`abort_class`, with the aborts that PAID a full verify separated from those that "
                "refused EARLY (by the `verify_mode` marker the abort payload already carries, never "
                "by the class name — an `abort_class` is not a reliable proxy for cost, T-10850), "
                "and — for the rows that can PROVE it — split by PHASE into the QUEUE WAIT and the "
                "verify RUN (T-11514, re-sourced by T-11831: the WAIT is the peak `waited_s` among "
                "that land's OWN land-queue heartbeats, the same PRIMARY instrument the SPEC-0132 "
                "admission lens folds, and the RUN is the remainder of its `duration_ms`. It is NOT "
                "`admission_wait_ms` — that field is the lens's `secondary_instrument`, labelled "
                "UNDER-REPORTING and not to be quoted as an admission wait, because it measures only "
                "the verify-admission-slot queue and never the land RESERVATION where the minutes "
                "actually go), and — reported BESIDE that split, never merged into either half — the "
                "LAND-RESERVATION queue (T-11690: `reservation_wait_ms`, the wait for the serialized "
                "merge->verify->ff window a peer land holds, T-11117). TWO QUEUES, KEPT APART "
                "DELIBERATELY: a verify-admission wait says the SLOT POOL is the constraint, a "
                "reservation wait says a PEER LAND is — different remedies, so one collapsed number "
                "would name neither. The reservation wait is also NOT inside the verify wall at all "
                "(it is spent before the merge and before step 4), so it is a THIRD phase rather "
                "than a re-slice of that wall — which is why it appeared in NO summary field "
                "until T-11690 and read as 0.0 min of queue wait while one measured land spent 55 of "
                "its 65 minutes queueing. That phase split is ORTHOGONAL to the groups below and is "
                "never added to any of them — it re-partitions the SAME minutes, and it is reported "
                "with its own coverage count so a partial split is never read as covering every "
                "abort. A row that cannot prove the split carries NO split rather than a zero-wait "
                "one; absent is never coerced to zero, which is the coercion that already published "
                "a wrong number (T-11236). "
                "and — where one class NAME unions two refusals — split further by ARM. "
                "`rebaseline-unauthorized` is that class: its AUTHORIZATION arm moved WHOLE to "
                "the step-4a preflight by T-10850, which refuses before verify but "
                "after the land reservation queue (T-12499: p50 546 s, 77% reservation wait), while its WAIVE-COVERAGE arm (T-10754) "
                "moved only in PART — T-11479 moved its token-binding half to that same preflight, and "
                "its coverage half still reads `pinned_bad` after a full pinned run. The two differ in "
                "MOVABILITY, so a fold that unions them prices a refusal already made cheap together "
                "with one that is still only partly moved, and reports one remedy where there are two "
                "(T-11426 / a consumer's X-1096). Each arm carries its OWN count, minutes and trend; a row "
                "that cannot be attributed to an arm is reported `unattributed`, never guessed. "
                "FIVE GROUPS THAT ARE NEVER SUMMED: gate-caught (a verify ran and FAILED — the gate "
                "EARNING ITS KEEP, a real defect caught before it landed, never waste), inconclusive "
                "(a verify that concluded nothing), process-refusal (a FULL verify paid and then "
                "refused on BOOKKEEPING — the only reclaimable total), preflight-refused (a row that "
                "carries a verify marker but refused at the step-4a PREFLIGHT, so it never paid the "
                "full verify the reclaimable sentence describes — bucketed by the row's OWN recorded "
                "refusal point rather than by its abort_class NAME, T-11777; its minutes are reported "
                "in full, never dropped), and early (refused before "
                "paying a verify). Each class carries a TREND over the window's own two halves, so a "
                "DECAYING cost is distinguishable from a STANDING one: a surface that ranked by raw "
                "minutes would point at a leg a one-line project declaration had already retired and "
                "send someone to fix a cost that no longer exists (X-1039, volunteered by the "
                "requester against their own interest). An abort whose cost cannot be determined is "
                "reported as UNDETERMINED, never as zero. ONE CLASS IS NOT IN ANY OF THIS: the "
                "T-11819 LAND-RESERVATION PARK-LIMIT eviction is EXCLUDED from the abort population "
                "entirely and reported apart under `evicted` (T-12396). It is not a cheap abort, it "
                "is a different kind of event — the land verified nothing, merged nothing and spent "
                "no CPU: it waited out the reservation behind a holder that would not release and "
                "then STOPPED. Every other class here describes a branch that was JUDGED and "
                "refused; an eviction is a fact about the QUEUE, and counting it as a failed attempt "
                "reads one congestion twice, once as the wait this fold already reports and once as "
                "a failure that never happened (measured 2026-09-11: 4 of 14 aborts in one 2-hour "
                "window, each after 149 min queued; owner ruling «в долгах не считать»). Its "
                "wall-clock is NOT dropped — `evicted` carries the wait those rows PROVE "
                "(`reservation_wait_ms`) with the coverage of that proof, because removing it from "
                "the abort count while leaving it unreported would trade an overstatement for a "
                "disappearance. DERIVED at read time from the journal — "
                "zero stored state, no new event, no new store, no cadence (SPEC-0142 §4). "
                "Report-only, never a gate.",
        "now": now.isoformat().replace("+00:00", "Z"),
        "count": count,
        "aborts": aborts,
        "classes": classes,
        "groups": groups,
        "window_days": window_days,
        "undetermined": undetermined,
        "trivial": trivial,
        "next": ("aborted lands cost real wall-clock that live sessions wait through. Read the "
                 "PROCESS-REFUSAL group first — that is a full verify paid and then thrown away on "
                 "bookkeeping, and it is the only part of this that is reclaimable. Read the "
                 "GATE-CAUGHT group as what the gate was WORTH, not as waste: those runs caught "
                 "defects. And read the TREND before acting on any of it — a DECAYING class is "
                 "already going away under its own steam (usually a declaration or a fix that has "
                 "landed), and building against it spends effort on a cost that no longer exists."
                 if count else
                 "no aborted land in the window cost anything worth reporting."),
    }



def _remote_lag_git(repo_root, *gitargs, _REMOTE_LAG_GIT_TIMEOUT=None) -> "str | None":
    """Read-only `git -C <repo_root> <gitargs>` → stdout (stripped) on exit-0, else None.

    A pure LOCAL reader (`remote -v` / `rev-parse` / `rev-list`) — never a write and never a network
    call. Same shape as `views._git_read`; module-local so the fold is self-contained and isolatable
    against a test sandbox repo. Never raises."""
    import subprocess
    try:
        r = subprocess.run(["git", "-C", str(repo_root), *gitargs],
                           capture_output=True, text=True, check=False,
                           timeout=_REMOTE_LAG_GIT_TIMEOUT)
    except (FileNotFoundError, OSError, ValueError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    return r.stdout.strip()



def _resolve_configured_remote(declared: str, repo_root, _git) -> "str | None":
    """Map the DECLARED `remote_sync.remote` value onto a CONFIGURED git remote NAME, or None.

    SPEC-0163's born scaffold shows a URL (`git@github.com:<org>/<repo>.git`) but the rule types the
    value only as a string and mandates no forge — so a project may equally have declared a bare
    remote NAME. Match on URL first (the documented shape), then on name; both exact. No fuzzy
    matching: a near-miss that silently resolved to the wrong remote would report a lag against a
    remote the project never declared, which is worse than the named degrade."""
    raw = (_git(repo_root, "remote", "-v") or "").splitlines()
    by_url, names = {}, []
    for line in raw:
        parts = line.split()
        if len(parts) < 2:
            continue
        name, url = parts[0], parts[1]
        names.append(name)
        by_url.setdefault(url, name)
        # `git remote -v` prints URLs verbatim; a declaration may or may not carry the `.git` suffix.
        by_url.setdefault(url[:-4] if url.endswith(".git") else url + ".git", name)
    d = declared.strip()
    if d in by_url:
        return by_url[d]
    if d.endswith(".git") and d[:-4] in by_url:
        return by_url[d[:-4]]
    if d in names:
        return d
    return None



def remote_lag(ops_path, repo_root, _git=None, *, _remote_lag_git=None, _resolve_configured_remote=None) -> dict:
    """remote-lag fold (SPEC-0119 rule 20 / SPEC-0163, T-11187 / X-0932): how far a project's declared
    OFFSITE copy has fallen behind `main` — the DERIVED "is the remote silently behind" surface.

    OPT-IN VIA THE EXISTING DECLARATION, never a new one. The carrier is SPEC-0163's `remote_sync:`
    concern (`remote:` + `pusher:` + `ci:`, declare-or-waive, landed T-10474). A project that declares
    nothing, or WAIVES, folds to 0 and is suppressed — today's behaviour, exactly (T-11187 AC4).

    LOCAL READ ONLY — NO NETWORK, BY CONSTRUCTION. The baseline is the local remote-tracking ref
    (`refs/remotes/<name>/<branch>`); this fold NEVER runs `fetch` / `ls-remote` / `push` / `pull`
    (`REMOTE_LAG_FORBIDDEN_GIT`). Three reasons: SPEC-0163 rule 3 holds that the kernel checks the
    STANCE and "never the remote's reachability" — scoped to the init sweep, but its intent reaches
    here and is honoured rather than routed around (CHARTER §P7); it makes "land is never contingent
    on the remote" STRUCTURAL rather than a matter of correct error-handling (T-11187 AC3); and it
    costs nothing at two hot seams (session-start + every land).

    WHY THE LOCAL READ IS HONEST FOR THE MOTIVATING INCIDENT. `git push` updates the tracking ref
    ONLY when it names a CONFIGURED REMOTE: a push BY URL updates the offsite copy and no local ref
    at all, so for a project whose `remote_sync.remote` IS a URL the baseline is exact only if the
    declared `pusher:` happens to push by remote NAME. That is not a footnote — it is the state
    <project> measured (X-1094 / T-11424): this view's OWN printed remedy interpolated the declared
    value verbatim, so following it pushed by URL and left the count unchanged, and the remedy could
    not clear the signal that printed it. Which is why the remedy now prints the RESOLVED CONFIGURED
    NAME (`push_remote`, from `_resolve_configured_remote`) rather than the declared string: the
    advice this view gives is the one form of push that updates the ref it reads. Given a push by
    name, the baseline is EXACT for the single declared `pusher:` the declaration describes. The failure
    this exists to catch — <project>'s v1 auto-pusher dying at quiesce (SPEC-0163 rationale / T-10419) —
    is a pusher that STOPS: no pushes, tracking ref frozen, `main` advancing, the count climbing at
    every seam. The residual imprecision runs in ONE direction only: a third party pushing from another
    machine leaves our tracking ref behind, so the count may OVER-report. It can never under-report to
    a false zero from staleness alone, so the view cannot go SILENT on real lag — the one degrade a
    report-only surface must never have.

    NO SILENT NON-DECLARATION. A genuine non-declaration (absent / no section / waived / no `remote:`)
    is suppressed; a carrier that cannot be READ or whose declaration is MALFORMED gets its OWN named
    degrade instead. Collapsing the two would let an INTENDED opt-in silently disappear (audit-pre
    finding, absorbed) — the same named-degrade discipline as the rule-23 live-revision adapter.

    Returns `{status, count, remote, branch, push_remote, commits, detail}`; `remote` is the DECLARED
    value (what the project wrote) and `push_remote` the CONFIGURED remote NAME it resolved to (None
    before resolution) — the two differ exactly when the declaration is a URL, which is why the
    prose names the first and the printed `git push` names the second. `count` is 0 for every non-`behind`
    status. Statuses: `not-declared` / `carrier-unreadable` / `malformed-declaration` /
    `declared-remote-not-configured` / `no-tracking-ref` / `in-sync` / `behind`. Never raises."""
    _git = _git if _git is not None else _remote_lag_git

    def _r(status, **kw):
        base = {"status": status, "count": 0, "remote": None, "branch": None, "push_remote": None,
                "commits": [], "detail": None}
        base.update(kw)
        return base

    # ── 1. The declaration. Genuine non-declaration is SILENT; unreadable/malformed is NAMED.
    p = Path(ops_path) if ops_path is not None else None
    if p is None or not p.is_file():
        return _r("not-declared")                      # no carrier at all — AC4
    try:
        carrier = state.load_ops(p)
    except (OSError, UnicodeDecodeError, yaml.YAMLError, TypeError, ValueError) as e:
        return _r("carrier-unreadable", detail=str(e)[:200])
    if not isinstance(carrier, dict):
        return _r("carrier-unreadable", detail="ops carrier is not a mapping")
    if "remote_sync" not in carrier:
        return _r("not-declared")                      # section absent — AC4
    sec = carrier.get("remote_sync")
    if sec is None:
        return _r("not-declared")                      # `remote_sync:` with an empty body — AC4
    if not isinstance(sec, dict):
        return _r("malformed-declaration",
                  detail="remote_sync is present but is not a mapping")
    # A WAIVE is a deliberate opt-out (declare-or-waive), not a degrade — the SPEC-0163 LOOSE waiver.
    if (sec.get("waived") is True or sec.get("state") == "waived"
            or isinstance(sec.get("waiver"), dict)):
        return _r("not-declared")                      # waived — AC4
    if "remote" not in sec:
        return _r("not-declared")                      # declared nothing to sync to — AC4
    declared = sec.get("remote")
    if not (isinstance(declared, str) and declared.strip()):
        return _r("malformed-declaration",
                  detail="remote_sync.remote is present but is not a non-empty string")
    declared = declared.strip()

    # ── 2. Resolve the declared remote to a CONFIGURED one. No match is real drift, and is NAMED.
    # The resolved NAME is carried out as `push_remote` (T-11424): it is the tracking ref's owner, so
    # it is also the ONLY push target whose success updates the ref this fold reads. Declared-vs-
    # configured is exactly the URL-declaration case, and printing the declared value as the remedy
    # is what made the advice unable to clear its own signal (X-1094).
    name = _resolve_configured_remote(declared, repo_root, _git)
    if name is None:
        return _r("declared-remote-not-configured", remote=declared)

    # ── 3. The integration branch. `main` is the SOLE integration branch (AGENTS §Writes-happen-in-a-
    # worktree); fall back to the checkout's current branch only where no local `main` exists, mirroring
    # `views._view_not_adopted`'s head_ref fallback so the fold never crashes on an unusual repo.
    branch = "main"
    head = _git(repo_root, "rev-parse", "--verify", "refs/heads/main")
    if head is None:
        branch = _git(repo_root, "rev-parse", "--abbrev-ref", "HEAD") or "HEAD"
        head = _git(repo_root, "rev-parse", "--verify", branch)
    if head is None:
        return _r("no-tracking-ref", remote=declared, branch=branch, push_remote=name,
                  detail="no local integration branch to compare")

    baseline_ref = f"refs/remotes/{name}/{branch}"
    if _git(repo_root, "rev-parse", "--verify", baseline_ref) is None:
        return _r("no-tracking-ref", remote=declared, branch=branch, push_remote=name,
                  detail=f"{baseline_ref} does not exist — nothing has been pushed or fetched yet")

    # ── 4. The lag itself: commits on the integration branch not reachable from the tracking ref.
    raw = _git(repo_root, "rev-list", "--format=%h%x1f%s", "--no-commit-header",
               f"{baseline_ref}..{branch}")
    if raw is None:
        return _r("no-tracking-ref", remote=declared, branch=branch, push_remote=name,
                  detail="the ancestry read failed")
    commits = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        short, _, subject = line.partition("\x1f")
        commits.append({"sha": short, "subject": subject})
    commits.reverse()   # oldest → newest (ship order), matching the not-adopted lens
    if not commits:
        return _r("in-sync", remote=declared, branch=branch, push_remote=name)
    return _r("behind", count=len(commits), remote=declared, branch=branch, push_remote=name,
              commits=commits)



def _dead_land_red_cause(row: "dict | None", branch: "str | None", *, DEAD_LAND_RED_EVIDENCE_KEYS=None) -> "dict | None":
    """T-11682 — the red record a dead land's own batch already wrote, COPIED off ONE
    `land_member_verdict` row. Returns None when the row says nothing about a red. PURE.

    COPY-NEVER-DECIDE, the shape `_emit_land_member_verdicts` uses at the writing end and this reads
    back at the reading end. Every field here was judged ONCE, at the seam that held both the member
    list and the failing set, and nothing is recomputed, re-derived or inferred here.

    THE ONE NAMING RULE, AND IT IS THE WHOLE OF AC3. A culprit NAME can be produced by EXACTLY ONE
    input — `evicted_as_culprit: True`, the single key that means the red-isolation probe named this
    member — in which case the name is that row's OWN branch. NO other field can yield a name:
      * `red_isolation_decline` is a DECLINE. It yields `culprit: None` and carries the decline's own
        reason, because the four fail-closed attribution gates named NOBODY and silence there is not
        evidence that the red was anyone's in particular.
      * `failure_attribution` is carried VERBATIM and is never promoted to a name. It answers whether
        the red still reproduces WITHOUT the branch (T-11464) — a different question from whose
        member it was, and reading `outcome: branch` as "this member is the culprit" would be exactly
        the plausible-name-in-place-of-a-gap this record exists to refuse.
      * a row with none of them yields `undecided_reason: "unrecorded"` — an explicit no-record
        reading, never a fallback onto a substantive answer.
    A salvaged verdict that guessed would be worse than the gap it fills, so the gap is structural:
    there is no code path here from an undecided input to a named member.

    ABSENT MEANS UNRECORDED throughout, the same discipline `_land_mark_red_assertions` applies when
    it declines to write an empty list for a red that surfaced no assertion text.
    """
    if not isinstance(row, dict):
        return None
    data = row.get("data")
    if not isinstance(data, dict):
        return None
    if not any(data.get(k) for k in DEAD_LAND_RED_EVIDENCE_KEYS):
        return None

    failing = data.get("red_assertions")
    failing = [str(x) for x in failing] if isinstance(failing, (list, tuple)) and failing else None

    culprit = None
    culprit_basis = None
    undecided_reason = None
    if data.get("evicted_as_culprit") is True:
        culprit = data.get("branch") or branch
        culprit_basis = "evicted-as-culprit"
    else:
        decline = data.get("red_isolation_decline")
        if isinstance(decline, dict) and decline.get("reason"):
            undecided_reason = str(decline["reason"])
        else:
            undecided_reason = "unrecorded"

    attribution = data.get("failure_attribution")
    attribution = dict(attribution) if isinstance(attribution, dict) else None

    return {
        "batch_id": data.get("batch_id") or None,
        "batch_size": data.get("batch_size") if isinstance(data.get("batch_size"), int) else None,
        "at": row.get("ts") or None,
        "failing": failing,
        "culprit": culprit,
        "culprit_basis": culprit_basis,
        "undecided_reason": undecided_reason,
        "attribution": attribution,
    }



def _dead_land_tip_is_land_marker(subject, branch, *, DEAD_LAND_TIP_PREFIX=None) -> bool:
    """True iff this tip subject is the LAND step-1 bookkeeping marker FOR THIS BRANCH.

    Both halves are load-bearing and each excludes a real near-miss measured on this repo:
      * the `land: ` prefix excludes `worktree sync: bookkeeping (<branch>)` — the same helper, the
        same shape, a different verb, and NOT a land (T-10821 added the prefix precisely so the two
        could be told apart in history);
      * the branch name inside the parens excludes an authored commit whose subject merely opens with
        `land:` — the same forgeable-subject hazard `_land_bookkeeping_commit` refuses to trust when it
        decides what to AMEND (it keys on the sha it minted, never on a subject). This reader cannot
        key on a sha, so it keys on the strictest subject shape available instead of the loosest.
    """
    if not isinstance(subject, str) or not isinstance(branch, str) or not branch:
        return False
    return subject.strip() == f"{DEAD_LAND_TIP_PREFIX}{branch})"



def dead_lands(_branch_tips, _land_rows, floor_minutes: int = 90, *, _worktree_of=None,
               _member_rows=None, now=None, DEAD_LAND_MEMBER_EVENT=None, DEAD_LAND_TERMINAL_EVENT=None, _dead_land_red_cause=None, _dead_land_result=None, _dead_land_tip_is_land_marker=None, _parse_stamped_deadline=None) -> dict:
    """Fold the branch frontier + the journal → the lands that STARTED and never REPORTED
    (SPEC-0119 rule 23). The newest sibling of `unresolved_worker_halts` / `nonterminal_plan_census`,
    and built to the identical contract: a pure fold, injected collaborators, `{lens, now, count, …}`
    out, report-only, ZERO stored state.

    THE ONE RULE THIS SHIPS. A land is killed between its first commit and its first event, and no
    surface in the system can see it — because every surface keys off a row that land never wrote. The
    `LAND:` token is stdout of a process that is gone. The repeated-abort backstop counts
    `land_completed{abort}` rows. The sibling debt views fold halts, followups and plans. So the ONE
    trace such a land does leave is a GIT COMMIT, and this is the only reader that looks at it.

    Measured, in this repo, 2026-08-18 (T-11254 — the kernel half of <project> X-0976): `land` ran on
    `work/cross-triage-round-2` at 2026-08-17T10:04:24Z, committed its step-1 bookkeeping (5fe2f328d)
    and died before update-from-main / verify / ff. NO `land_completed` row exists in main's journal,
    the branch's own journal, or the still-present worktree's — not even `status=abort`. Three filed
    cards (T-11228 / T-11229 / T-11230) sat stranded and invisible on main for ~16 hours; the strand
    was found only because an unrelated `task file` overlap advisory happened to name the branch.

    THE PREDICATE — two conditions, BOTH necessary, and the second is the load-bearing one:

      1. the branch is NOT merged into main AND its tip subject is the land step-1 fold marker for
         that same branch (`_dead_land_tip_is_land_marker`) — so a land STARTED here; AND
      2. NO `land_completed` row names that branch at a ts AT OR AFTER the tip's own committerdate —
         so that land never REPORTED, in either direction.

    WHY CONDITION 2 IS NOT A REFINEMENT BUT HALF THE DESIGN. "A branch ahead of main with a
    bookkeeping-only tip" is by itself a false-positive generator, and the measurement is unambiguous:
    SIX branches in this repo carry that tip and are unmerged (task/T-10116, task/T-10122,
    task/T-10174, task/T-10181, work/full-revizia-2026-07-10, work/cross-triage-round-2). FIVE of them
    landed FINE — each has a `land_completed{status:ok}` timestamped at or just after its tip (ok at
    04:59:38Z against a 04:58:04 tip, and so on). They persist only because
    `_land_bookkeeping_commit` AMENDS its commit (T-9799): the local ref still points at the stale
    PRE-amend object while main carries the amended one. So the tip test ALONE would report 6 and be
    WRONG on 5 — exactly the failure the card's AC1 names by its failing input ("a view that flags
    every unlanded branch fails this AC"). One condition without the other is not a weaker version of
    this view; it is a noise generator.

    AT OR AFTER THE TIP, never merely "any row for this branch". A branch may have landed ok once and
    had a LATER land die on it; anchoring to the tip's OWN timestamp is what lets the newest land be
    judged on its own evidence instead of being excused by an ancestor's success.

    THE ROW SET MUST BE THE UNIONED ONE — a correctness condition, not a wiring detail (audit-pre
    finding 1). `land` runs from main and appends to MAIN's journal, but a row can also sit in a
    branch's own journal or a live worktree's, and a local-only read would then report a land that DID
    report — a false dead-land, the very noise class condition 2 exists to prevent. The caller injects
    the same unioned reader the rule-18 sibling uses, narrowed BY TYPE and never by AGE (a dead land
    must not age out of its own detection). Verified across all three loci on the live incident before
    this shipped: 0 rows in main's journal, 0 in the branch's, 0 in the worktree's.

    THE AGE FLOOR, AND WHY THIS VIEW IS NOT UNFLOORED (T-11254, caught by its OWN AC2 live probe —
    the case for CHARTER §P8 demanding a live trigger over a unit test, made against this very card).
    Between land step-1's commit and its terminal row, a HEALTHY IN-FLIGHT land is byte-for-byte
    indistinguishable from a dead one: same marker tip, same absent row. The first live run reported 1
    branch; a second run minutes later — with four sibling lanes mid-`land` — reported 5, of which
    FOUR were healthy lands still verifying. Reporting those is not a cosmetic wart: it nags a
    controller about workers that are working, which is how a report-only line teaches its reader to
    ignore it.
    So a candidate younger than `floor_minutes` is SUPPRESSED. This is an AGE floor, never a COUNT
    floor — the count is never hidden, only YOUTH suppresses (rule 3), which is the exact shape and
    rationale `_debt_dispatch_monitor_floor_minutes` already ships for rule 12; the value is reused
    rather than newly decreed. WHY 90: measured over the 4365 `land_completed` rows carrying timings
    in this journal, the longest healthy land (verify + admission wait) ran 38.7 min, p95 8.0 min. 90
    exceeds the observed maximum by 2.3x, so a land that is merely SLOW — a long verify, a SPEC-0132
    admission wait, a retry — can never be reported as dead, while the incident this rule exists for
    (20 HOURS silent) surfaces with an enormous margin. The measured separation is not marginal: 20h
    against minutes.
    A candidate whose TIP DATE will not parse cannot be aged, so the floor cannot be applied to it and
    it is KEPT — condition 2 has already established that no terminal row exists, and a git
    committerdate that will not parse is a corruption worth a line, not a reason to go quiet.

    UNCERTAINTY DIRECTION — deliberately the OPPOSITE of `unresolved_worker_halts`, and the difference
    is the SUBJECT, not a change of posture (`lessons/fail-closed-belongs-to-the-reader-not-the-parser`
    — the missing-value judgement belongs to the use site). That view fails closed toward VISIBLE
    because its subject is a decision still owed, and a lost signal costs the decision. THIS view's
    subject is "nothing was reported at all", so a terminal row that EXISTS but whose ts will not parse
    is already not that class, and it SUPPRESSES. The asymmetry is paid for: the cost of a false row
    here is noise on every debt seam, which buries the echo it rides — the failure the SPEC-0149
    39-line trial disproof already bought once.

    COLLABORATOR CRITICALITY — two classes, and conflating them would let a cosmetic failure silence
    the incident (audit-pre finding 2). `_branch_tips` and `_land_rows` ARE the predicate: if either
    raises, the fold can judge nothing and returns a clean ZERO for the whole fold (the rule-12
    report-only posture, verbatim — a view must never break the seam it rides). `_worktree_of` is
    REMEDY CONTEXT ONLY, is never consulted by the predicate, and is guarded PER BRANCH: a raise, a
    None, or an absent collaborator yields a row whose `worktree` is None — the dead land still
    REPORTS, with its remedy clause adapted. A dead land whose worktree was already removed is still a
    dead land.

    WHAT THIS IS NOT (CHARTER §6 named retirement (d), the card's AC3 fence, asserted by test). It
    stores no queue state, arms no liveness FSM, registers no watcher, and STARTS NOTHING. It needs no
    writer because the state it reads already exists and is durable: the git ref IS the marker `land`
    already wrote, and the journal IS the record of whether it reported. That is why the card chose a
    derived view over an in-flight marker — a marker is only useful if something later ARMS on it and
    judges it stale, which is the orchestrator §6 forbids by name, and it could not see this incident
    anyway (the whole failure class is a process dying at an arbitrary point, including before its own
    marker write). The remedy this line NAMES is the existing idempotent verb `worktree recover-land`;
    the line never runs it.

    AND IT CARRIES WHAT THE DEAD LAND DIED ON (T-11682), when its own batch recorded one. Naming the
    branch answers WHO died; it never answered WHY, and for a dead BATCH HEAD the why is multiplied by
    the batch size. Measured 2026-08-26: the head of `bat-2114bce5cf05` (formed 11:02:13Z) dissolved
    its four-member batch at 11:10:22Z — putting six named pinned failures and a
    `red_isolation_decline{pinned-entry}` on all four `land_member_verdict` rows IN MAIN'S JOURNAL —
    and then died. Four branches had each paid ~8 minutes of a shared verify, the cause was on main
    the whole time, and NOTHING joined it to the death: the abort-cost fold and the repeated-abort
    backstop key on the `land_completed` row that land never wrote, and this view — the one reader
    built for exactly that silence — named a branch and a remedy and stopped. The cause survived only
    because a worker chose to write a prose escalation, which no worker is obliged to write.
    So the fold now JOINS the two. Nothing is recomputed: `_dead_land_red_cause` COPIES the record off
    the member row, and its one naming rule (a culprit name comes from `evicted_as_culprit` and from
    nothing else) is what keeps a salvaged verdict from filling the gap with a plausible member.

    THE JOIN WINDOW IS CLOSED BY CONDITION 2, not by a new rule. A branch is REPORTED here only when
    NO `land_completed` names it at or after the tip, so the interval [tip, now) provably contains no
    COMPLETED land for this branch — which is the one mis-attribution that would matter, blaming a
    branch that already reported. What the interval CAN hold is a retry of the same dead land, or a
    later land that ALSO died; both are this dead branch, so the NEWEST red is the state a reader is
    looking at. `batch_id` and `at` are carried and rendered so the attach is auditable rather than
    implicit — a reader always sees WHICH batch and WHEN, and can never mistake a stale attach for a
    fresh one.

    Args:
      _branch_tips: `() -> [{"branch", "sha", "subject", "committed_at"}]` — the branches NOT merged
        into main, with their tip metadata. ONE git call at the caller, never one-per-branch. A reader
        that raises or yields nothing ⇒ a clean, zero-count result.
      _land_rows: `() -> [event dict]` — the UNIONED `land_completed` rows. The branch is carried at
        `data.branch` and these rows carry NO task id, so the branch IS the join key. Indexed once
        (O(N)), never re-scanned per branch.
      _worktree_of: OPTIONAL `(branch) -> path|None` — the EXISTING `_worktree_path_for_branch`,
        remedy context only. KEYWORD-ONLY: it must never be bindable into a positional slot where a
        future caller could pass it where a predicate collaborator belongs.
      _member_rows: OPTIONAL `() -> [event dict]` — the UNIONED `land_member_verdict` rows (T-11682).
        SAME CRITICALITY CLASS AS `_worktree_of`, keyword-only for the same reason: it is CONTEXT, is
        NEVER consulted by either predicate condition, and a raise / None / non-list yields dead lands
        WITHOUT a cause rather than suppressing the view. A dead land whose cause was never recorded
        is still a dead land. Default None ⇒ nothing attached, so every pre-T-11682 caller and every
        hermetic probe is byte-identical.
      floor_minutes: the AGE floor (see above). A candidate younger than this is suppressed as a
        possibly-in-flight land. Non-positive DISABLES the floor (every candidate fires) — the same
        escape the sibling floors offer, and the shape a test uses to assert the floor is what
        silences a fresh candidate rather than some other property.
      now: aware datetime to age against; defaults to real UTC now. Injected by the tests, so no
        assertion is wall-clock-dependent.

    Returns `{"lens", "now", "count", "floor_minutes", "lands", "next"}` — the shape every sibling
    returns; a land row carries the ONE additive optional key `red_cause` when its batch recorded one.
    Pure: reads, writes nothing, emits nothing, gates nothing.
    """
    now = now if now is not None else datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    # LOAD-BEARING reader 1. A raise here leaves nothing to judge — clean zero, never a partial guess.
    try:
        tips = _branch_tips() or []
    except Exception:
        return _dead_land_result(now, [], floor_minutes)
    if not isinstance(tips, (list, tuple)):
        return _dead_land_result(now, [], floor_minutes)

    # Condition 1 first: it is a pure string test and it cuts the candidate set to a handful, so the
    # journal index below is only ever built when there is something it could decide.
    candidates = []
    for tip in tips:
        if not isinstance(tip, dict):
            continue
        branch = tip.get("branch")
        if _dead_land_tip_is_land_marker(tip.get("subject"), branch):
            candidates.append(tip)
    if not candidates:
        return _dead_land_result(now, [], floor_minutes)

    # LOAD-BEARING reader 2, same posture. ONE pass indexes the rows by branch; `land_completed` rows
    # carry no task id, only `data.branch`, which is exactly the key this fold joins on.
    try:
        rows = _land_rows() or []
    except Exception:
        return _dead_land_result(now, [], floor_minutes)
    by_branch: dict = {}
    for ev in rows if isinstance(rows, (list, tuple)) else []:
        if not isinstance(ev, dict) or ev.get("type") != DEAD_LAND_TERMINAL_EVENT:
            continue
        data = ev.get("data")
        b = data.get("branch") if isinstance(data, dict) else None
        if isinstance(b, str) and b:
            by_branch.setdefault(b, []).append(ev)

    lands = []
    for tip in candidates:
        branch = tip.get("branch")
        tip_at = _parse_stamped_deadline(tip.get("committed_at"))
        if tip_at is None:
            # The tip's own date is unreadable, so "at or after the tip" cannot be evaluated at all.
            # Fall back to the WEAKER, strictly-more-suppressing question — does ANY terminal row name
            # this branch? — because an unanswerable comparison must never be resolved in the
            # direction that INVENTS a row, i.e. toward reporting.
            if by_branch.get(branch):
                continue
        else:
            reported = False
            for ev in by_branch.get(branch) or []:
                ev_at = _parse_stamped_deadline(ev.get("ts"))
                # An unparseable ROW ts suppresses: a terminal row exists, so whatever else is true of
                # this branch, "nothing was reported at all" is not it (see UNCERTAINTY DIRECTION).
                if ev_at is None or ev_at >= tip_at:
                    reported = True
                    break
            if reported:
                continue

        # REMEDY CONTEXT ONLY — guarded per branch, can never suppress the row (audit-pre finding 2).
        worktree = None
        if _worktree_of is not None:
            try:
                wt = _worktree_of(branch)
                worktree = str(wt) if wt else None
            except Exception:
                worktree = None

        # THE AGE FLOOR — a land still in flight looks exactly like a dead one (see docstring). An
        # unparseable tip date cannot be aged, so the floor cannot apply and the candidate is kept.
        age_minutes = ((now - tip_at).total_seconds() / 60.0) if tip_at is not None else None
        if floor_minutes > 0 and age_minutes is not None and age_minutes < floor_minutes:
            continue

        age_hours = int((now - tip_at).total_seconds() // 3600) if tip_at is not None else None
        row = {
            "branch": branch,
            "sha": tip.get("sha") or None,
            "tip_at": tip.get("committed_at") or None,
            "age_hours": age_hours,
            "worktree": worktree,
        }
        # T-11682 — the tip instant is kept for the CAUSE pass below, which runs only if this list
        # ends up non-empty. Not part of the returned row.
        row["_tip_at"] = tip_at
        lands.append(row)

    # T-11682 — THE CAUSE PASS, AND IT IS LAZY BY DESIGN. The reader is consulted ONLY when at least
    # one dead land survived both predicate conditions and the age floor — which, on a healthy repo, is
    # NEVER. That laziness is a correctness-of-cost property, not an optimisation: this reader asks for
    # a type no sibling view reads, so the T-11453 request-scoped memo cannot serve it from an existing
    # base and it costs a REAL scan of a ~3 GB union of 17 journals. Paying that at every session-start
    # and land-tail seam to explain a set that is almost always EMPTY would make a report-only line
    # quietly expensive for every session — measured here: the file that drives the real `debt` verb
    # already runs near the 300 s per-file verify cap, and an unconditional second scan pushed it over
    # under parallel load. Gated on a non-empty result, the clean case costs exactly what it did before
    # this change, and the scan is paid only when there is genuinely something to explain.
    #
    # CONTEXT criticality throughout, exactly like `_worktree_of`: every failure degrades to "no cause
    # recorded" and the dead land still REPORTS. A dead land whose cause cannot be read is still one.
    if lands and _member_rows is not None:
        try:
            _mrows = _member_rows() or []
        except Exception:
            _mrows = []
        members_by_branch: dict = {}
        for ev in _mrows if isinstance(_mrows, (list, tuple)) else []:
            if not isinstance(ev, dict) or ev.get("type") != DEAD_LAND_MEMBER_EVENT:
                continue
            data = ev.get("data")
            b = data.get("branch") if isinstance(data, dict) else None
            if isinstance(b, str) and b:
                members_by_branch.setdefault(b, []).append(ev)
        for row in lands:
            tip_at = row.get("_tip_at")
            if tip_at is None:
                # The tip's own date is unreadable, so "at or after the tip" cannot be evaluated —
                # and an unanswerable comparison is never resolved toward INVENTING a record.
                continue
            best_at, cause = None, None
            for ev in members_by_branch.get(row.get("branch")) or []:
                ev_at = _parse_stamped_deadline(ev.get("ts"))
                if ev_at is None or ev_at < tip_at:
                    continue
                candidate = _dead_land_red_cause(ev, row.get("branch"))
                if candidate is None:
                    continue
                if best_at is None or ev_at >= best_at:
                    best_at, cause = ev_at, candidate
            if cause is not None:
                row["red_cause"] = cause
    for row in lands:
        row.pop("_tip_at", None)   # internal to the cause pass; never part of the returned shape

    # Oldest strand first; an unknown age sorts last rather than pretending to be age 0 (the rule-18
    # sort, verbatim — an unestablishable age is not a fresh one).
    lands.sort(key=lambda r: (r["age_hours"] is None, -(r["age_hours"] or 0), r["branch"] or ""))
    return _dead_land_result(now, lands, floor_minutes)



def dead_land_remedy(branch: "str | None") -> str:
    """T-11385 — render the recovery instruction for ONE dead-land branch: the invocation form
    `worktree recover-land` ACTUALLY ACCEPTS for that branch's namespace.

    WHY THIS EXISTS AT ALL. Rule 23 folds the whole branch frontier, so it names `work/<slug>`
    branches as readily as `task/T-XXXX` ones — but the remedy it printed was the bare verb name, and
    the verb took `--task` ONLY. A surface that NAMES a branch and then NAMES a verb that refuses it
    walks every reader into a dead end, under load, at a seam they reached because something was
    already wrong. That is the second half of the same defect the `--work` arm closes, and it is
    arguably the worse half: the arm makes recovery possible, this makes it FINDABLE.
    (`lessons/a-refusal-remedy-must-name-which-locus-it-repairs` — a prescribed remedy must state
    which case it addresses; a message is executable, and whoever reads it will do what it says.)

    THREE BRANCHES, and the third is the honest one. `task/` and `work/` render the flag form the
    parser accepts. ANYTHING ELSE — a ref outside the two namespaces `worktree new` creates, which
    rule 23 can still surface — renders a NON-INVOCATIONAL diagnostic: a read-only `git log` and a
    plain statement that the branch is outside what the verb serves. It deliberately does NOT print a
    bare `worktree recover-land`, because with `--task|--work` required that command refuses too —
    naming a fallback the reader cannot run would re-create the very dead end this closes, one
    namespace over (audit-pre finding 2).

    ONE renderer, TWO callers — the `debt` re-fold's `next:` and the session-start / land-tail echo
    (`views._render_debt_echo`) — so the two surfaces cannot drift into naming different remedies for
    the same branch. Pure: a string in, a string out, no I/O.
    """
    br = branch if isinstance(branch, str) and branch else None
    if br and br.startswith("task/"):
        return f"`bin/yitc-v2 worktree recover-land --task {br[len('task/'):]}`"
    if br and br.startswith("work/"):
        return f"`bin/yitc-v2 worktree recover-land --work {br[len('work/'):]}`"
    return (f"read it with `git log --oneline main..{br or '<branch>'}` and integrate it by hand — it "
            f"is outside the `task/` and `work/` namespaces `worktree recover-land` serves, so no "
            f"form of that verb accepts it")



def dead_land_cause_clause(land: "dict | None") -> str:
    """T-11682 — render ONE dead land's recovered red cause. Returns "" when none was recorded.

    ONE HOME, THREE CALLERS — `_dead_land_result`'s `next:`, the dead-land debt echo line, and the
    ABORT-COST echo line — for the reason `dead_land_remedy` already exists in this shape: three
    surfaces describing the same death in three different ways is how a reader learns to distrust all
    three. Pure: a dict in, a string out, no I/O.

    SILENCE IS NOT A CLAIM. A land with no `red_cause` renders "" — absent means UNRECORDED, and a
    clause invented for it would read as evidence.

    AND WHERE THE ATTRIBUTION DECLINED IT SAYS SO, OUT LOUD. This is AC3 at the reading end: the
    clause never renders a bare failing set that a reader could take as this branch's own doing. It
    either NAMES the member the isolation probe evicted, or it states that the culprit is UNNAMED,
    names the reason the attribution declined, and says in words that this is NOT evidence the red
    belongs to any one member. `lessons/a-signal-about-a-reader-fails-safe-the-opposite-way-to-a-gate`
    — fail toward silence about WHO, never toward accusation — while still saying WHAT died.

    The batch id and the row ts are always rendered when known: they are what make the attach
    AUDITABLE, so a reader can see which batch and which moment the cause was read from rather than
    trusting the join.
    """
    if not isinstance(land, dict):
        return ""
    c = land.get("red_cause")
    if not isinstance(c, dict):
        return ""
    failing = c.get("failing") if isinstance(c.get("failing"), list) else None
    parts = []
    if failing:
        first = str(failing[0])
        first = (first[:160] + "…") if len(first) > 160 else first
        parts.append(f"died on {len(failing)} failing assertion(s), first: {first}")
    else:
        parts.append("died on a red batch that surfaced no assertion text")
    src = []
    if c.get("batch_id"):
        src.append(f"batch {c['batch_id']}")
    if c.get("at"):
        src.append(f"recorded {c['at']}")
    if src:
        parts.append("read from " + ", ".join(src))
    if c.get("culprit"):
        parts.append(f"attributed to {c['culprit']} ({c.get('culprit_basis') or 'attributed'})")
    else:
        parts.append(
            f"CULPRIT UNNAMED — the attribution DECLINED ({c.get('undecided_reason') or 'unrecorded'}), "
            f"which is NOT evidence the red is any one member's")
    if isinstance(c.get("attribution"), dict) and c["attribution"].get("outcome"):
        _a = c["attribution"]
        parts.append(f"re-run at the merge-base: {_a.get('outcome')}"
                     + (f" ({_a.get('reason')})" if _a.get("reason") else ""))
    return "; ".join(parts)



def _dead_land_result(now, lands: list, floor_minutes: int = 90, *, dead_land_cause_clause=None, dead_land_remedy=None) -> dict:
    return {
        "lens": "dead-lands (SPEC-0119 rule 23) — branches whose `land` STARTED (its step-1 bookkeeping "
                "commit is the branch tip) and never REPORTED: no `land_completed` row names the branch "
                "at or after that tip, in EITHER direction. This is the one failure every other surface "
                "is blind to at once — the `LAND:` token is stdout of a dead process, the repeated-abort "
                "backstop counts abort ROWS, and the sibling debt views fold halts/followups/plans — so "
                "the only trace left is the commit, which is what this reads. An ABORTED land is NOT "
                "here: it reported. Derived from the git frontier + the journal; ZERO stored state, no "
                "marker, no watcher, report-only, never a gate, and it starts nothing. An AGE floor "
                "suppresses a candidate younger than `floor_minutes`, because between step-1's commit "
                "and the terminal row a HEALTHY IN-FLIGHT land is indistinguishable from a dead one.",
        "now": now.isoformat().replace("+00:00", "Z"),
        "count": len(lands),
        "floor_minutes": floor_minutes,
        "lands": lands,
        "next": ("these branches ran `land`, committed its bookkeeping, and then died before emitting "
                 "any terminal row — so whatever they carry is sitting unmerged and invisible on main. "
                 "Read what is stranded first (`git log --oneline main..<branch>`), then recover each "
                 "with the form that ACCEPTS it (T-11385 — the verb takes --task OR --work, and the "
                 "line names which): " + "; ".join(
                     f"{r.get('branch')} -> {dead_land_remedy(r.get('branch'))}"
                     + (f" [{dead_land_cause_clause(r)}]" if dead_land_cause_clause(r) else "")
                     for r in lands if isinstance(r, dict)) +
                 ". Each is idempotent; the row drops by itself the moment a terminal row lands."
                 if lands else
                 "every branch whose land started has a terminal row on record — nothing stranded."),
    }



def ahead_work_branches(_frontier, floor_hours: int = 24, *, now=None, AHEAD_BRANCH_NAMESPACES=None, _ahead_branches_result=None, _dead_land_tip_is_land_marker=None, _parse_stamped_deadline=None) -> dict:
    """Fold the branch frontier → the WORK branches that carry commits `main` does not have
    (SPEC-0119 rule 24). The COMPLEMENT of rule 23 (`dead_lands`), built to the identical contract: a
    pure fold, an injected collaborator, `{lens, now, count, …}` out, report-only, ZERO stored state.

    THE ONE FACT THIS SHIPS, and it is one fact. Whether a branch is AHEAD of main is the single thing
    that separates a benign stale branch from a serious one, and no surface reported it. Measured on
    this repo, 2026-08-20: 18 branches sit unmerged, every one of them ahead by 1-5 commits, and the
    only surface naming ANY of them is rule 23 — which by construction sees only branches whose TIP is
    the land step-1 marker. A branch whose land never STARTED (`work/park-bound-evidence-trigger`, 1
    commit, 25.8h; `work/bench-base-T0387|T9527|T9542`, 3 commits each, 56d) carries an ordinary work
    subject, so rule 23's condition 1 rejects it and NOTHING else in the system looks. The three
    surfaces a reader would reach for do not cover it and cannot: the dispatch-status census counts
    live WORKTREES, not branches; the not-adopted view walks main→live, the INVERSE leg, so a branch
    that never reached main is invisible to it by construction; and `worktree sweep` removes the desk
    copy without deleting the branch and says nothing at any seam.

    WHAT THE COUNT MEANS, stated because the reporter corrected themselves on exactly this (<project>
    X-1003, retracting the supporting half of X-1001). `main..<branch>` counts commits main does not
    have BY SHA. It is NEVER a claim their CONTENT is absent from main — a change that reached main by
    another commit still shows as a difference, which is how a line-level re-measure turned two
    "missing" branches into routine bookkeeping. So the fact is reported AS the fact it is, and the
    rendered line says so in its own words. That honest bound is the ground this view stands on, and
    it is why the view REPORTS rather than judges.

    THE COMPLEMENT BOUNDARY — how this partitions against rule 23 without overlapping it. Rule 23 owns
    branches where a land STARTED and never reported. This owns branches where a land never started at
    all. The split is drawn by rule 23's OWN predicate, reused and never re-derived
    (`_dead_land_tip_is_land_marker`), under ONE conjunct that is half the design:

      DROP iff `ahead == 1` AND the tip is the land marker for this branch.

    WHY `ahead == 1` IS LOAD-BEARING (audit-pre pass-1 high finding, and the correction that made this
    predicate honest). The tip test ALONE would drop a branch whose TIP merely looks like bookkeeping
    while EARLIER commits of real work are still missing from main — and rule 23 does not catch that
    branch either once its land REPORTED, because a `land_completed{abort}` row suppresses it there. So
    an unbounded tip test would restore, inside the very predicate meant to partition the two views,
    exactly the blind spot this card exists to close. Bounded to `ahead == 1` the drop covers EXACTLY
    the class it was written for: the `_land_bookkeeping_commit` AMEND residue (T-9799), which is by
    construction a SINGLE commit — the branch's work commits reached main by fast-forward and differ
    from it by no SHA at all, leaving only the stale pre-amend bookkeeping object — which is why all
    four such branches on the live frontier measure ahead=1 (task/T-10116, T-10122, T-10174, T-10181).
    A marker-tipped branch at ahead>1 carries real commits and IS reported.

    THE AGE FLOOR, and why this view is not unfloored. EVERY healthy in-flight build has a branch ahead
    of main — that is what a worktree IS — so youth is precisely what must never fire. A candidate
    younger than `floor_hours` is SUPPRESSED. This is an AGE floor, never a COUNT floor: the count is
    never hidden, only youth suppresses (SPEC-0119 rule 3), the same shape and rationale rules 12 and
    23 already ship, reused rather than newly decreed. WHY 24: measured separation on the live frontier
    at design time — two genuinely live lanes at 15.7h and 17.5h (`work/bump-11323`,
    `task/T-11319-recovered`) against the one genuinely abandoned branch at 25.8h
    (`work/park-bound-evidence-trigger`) — and the originating incident measured 28-40h, so the floor
    sits below every reported instance and above every live one. A candidate whose tip date will not
    parse cannot be aged, so the floor cannot be applied to it and it is KEPT: ahead-ness is already
    established by then, and a git committerdate that will not parse is a corruption worth a line, not
    a reason to go quiet (`dead_lands`' rule, verbatim).

    REPORT-ONLY, and the bound is the point (SPEC-0119 rule 21 precedent, `lessons/scope-the-trigger-
    not-the-view`). It names no candidate, ranks nothing, selects nothing and takes nothing into work;
    the only pointer it carries is a read-only `git log`. The frontier READ is deliberately broad — one
    call over every branch — and the three bounds that decide what INTERRUPTS (namespace, age,
    rule-23 ownership) live HERE, in the fold, never smuggled into the reader. A branch NOT ahead of
    main is NOT reported: alarming on normal behaviour is what teaches a reader to stop reading the
    echo, which costs more than the blind spot this closes.

    Args:
      _frontier: `() -> [{"branch", "ahead", "committed_at", "subject"}]` — the branches NOT merged
        into main, with their ahead-count and tip metadata. ONE git call at the caller, never one per
        branch. LOAD-BEARING: a reader that raises or yields a non-list ⇒ a clean, zero-count result
        (a view must never break the seam it rides).
      floor_hours: the AGE floor (see above). Non-positive DISABLES it — the sibling escape, and the
        shape a test uses to prove the floor is what silences a fresh candidate rather than some other
        property.
      now: aware datetime to age against; defaults to real UTC now. Injected by the tests, so no
        assertion is wall-clock-dependent.

    Returns `{"lens", "now", "count", "floor_hours", "branches", "next"}` — the shape every sibling
    returns. Pure: reads, writes nothing, emits nothing, gates nothing.
    """
    now = now if now is not None else datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    try:
        frontier = _frontier() or []
    except Exception:
        return _ahead_branches_result(now, [], floor_hours)
    if not isinstance(frontier, (list, tuple)):
        return _ahead_branches_result(now, [], floor_hours)

    branches = []
    for row in frontier:
        if not isinstance(row, dict):
            continue
        branch = row.get("branch")
        # (a) NAMESPACE — the lifecycle-owned refs, and nothing else.
        if not isinstance(branch, str) or not branch.startswith(AHEAD_BRANCH_NAMESPACES):
            continue
        # (b) AHEAD — a belt, not a duplicate of the reader's `--no-merged`: the fold must not trust its
        # reader's flags, and a git too old for `%(ahead-behind:)` yields an unreadable field here, which
        # DROPS the branch (the view degrades to SILENT rather than to a wrong count).
        ahead = row.get("ahead")
        if not isinstance(ahead, int) or isinstance(ahead, bool) or ahead <= 0:
            continue
        # (c) RULE-23 OWNERSHIP, narrowed by `ahead == 1` — see THE COMPLEMENT BOUNDARY above.
        if ahead == 1 and _dead_land_tip_is_land_marker(row.get("subject"), branch):
            continue
        # (d) AGE FLOOR — an unparseable tip date cannot be aged, so the floor cannot apply: KEEP.
        tip_at = _parse_stamped_deadline(row.get("committed_at"))
        age_hours = int((now - tip_at).total_seconds() // 3600) if tip_at is not None else None
        if floor_hours > 0 and age_hours is not None and age_hours < floor_hours:
            continue
        branches.append({
            "branch": branch,
            "ahead": ahead,
            "tip_at": row.get("committed_at") or None,
            "age_hours": age_hours,
        })

    # Oldest first; an unknown age sorts LAST rather than pretending to be age 0 (the sibling sort).
    branches.sort(key=lambda r: (r["age_hours"] is None, -(r["age_hours"] or 0), r["branch"] or ""))
    return _ahead_branches_result(now, branches, floor_hours)



def _ahead_branches_result(now, branches: list, floor_hours: int = 24) -> dict:
    return {
        "lens": "ahead-work-branches (SPEC-0119 rule 24) — `task/*` / `work/*` branches carrying "
                "commits `main` does not have, aged past the floor. Whether a branch is AHEAD of main "
                "is the ONE fact separating a benign stale branch from a serious one, and no other "
                "surface reports it: the dispatch census counts live worktrees not branches, the "
                "not-adopted view walks main->live (the INVERSE leg, so a branch that never reached "
                "main is invisible to it by construction), and `worktree sweep` removes the desk copy "
                "without deleting the branch. The COMPLEMENT of rule 23: that view owns branches whose "
                "land STARTED and never reported, this owns branches where it never started at all. "
                "The count is of commits main lacks BY SHA and is NEVER a claim their CONTENT is "
                "absent from main (a consumer's X-1003) — a change that reached main by another commit "
                "still shows as a difference. Derived from the git frontier at read time; ZERO stored "
                "state, report-only, never a gate, and it selects nothing. An AGE floor suppresses a "
                "candidate younger than `floor_hours`, because every healthy in-flight build has a "
                "branch ahead of main.",
        "now": now.isoformat().replace("+00:00", "Z"),
        "count": len(branches),
        "floor_hours": floor_hours,
        "branches": branches,
        "next": ("these branches carry commits main does not have and no seam was naming them. READ "
                 "what each carries first — `git log --oneline main..<branch>` — and remember the "
                 "count is by SHA, not by content: a change that already reached main another way "
                 "still shows here. The row drops by itself once the branch merges or is deleted."
                 if branches else
                 "no work branch carries commits main does not have — nothing unmerged and unnamed."),
    }



def behind_work_branches(_frontier, floor_commits: int = 200, *, now=None, AHEAD_BRANCH_NAMESPACES=None, _behind_branches_result=None) -> dict:
    """Fold the branch frontier → the LIVE `task/*` / `work/*` branches that main has run far AHEAD
    of (SPEC-0119 rule 32). The OTHER HALF of rule 24, built to that rule's contract without
    exception: a pure fold, an injected collaborator, `{lens, now, count, …}` out, report-only, ZERO
    stored state, nothing emitted and nothing gated.

    THE ONE FACT THIS SHIPS. Rule 24 reports how far AHEAD of main a branch is — which says whether
    the branch holds work nobody else has. It says nothing about the other direction, and that is the
    half that says whether the branch is about to hit a painful merge, or is about to run a test
    suite against a tree main fixed hours ago. Behind-ness is computed in exactly ONE place in the
    whole engine today — inside `worktree sync`, the verb that also CURES it — so
    `worktree_synced.behind_before` is a receipt for the cure and never a signal of the disease. A
    branch nobody synced is measured by nothing.

    WHAT THE REPORTER MEASURED (<project> X-1105). Five live worktrees, ALL behind main — by 881, 881,
    881, 273 and 168 commits — while that morning's debt echo named exactly ONE branch, and named it
    for being AHEAD by a single commit. Over that repo's whole history 1077 worktrees were created
    and 80 carry a sync record: 7% were ever measured at all, and that 7% is biased toward the
    best-tended copies. The concrete cost is theirs too (<project> T-0435, 2026-08-20/21): a
    234-behind worktree carried two verify REDs already fixed on main, so the session correctly ran
    on main instead — where the stage-bound verb was inapplicable, so it hand-ran per-layer scripts,
    missed one of three declared layers, and wrote receipts naming scripts instead of declared test
    classes. Sync-then-run-in-the-worktree cost a minute and is what the next morning did.

    WHAT THE COUNT MEANS — the sibling's honest bound, carried VERBATIM and for the same reason
    (<project> X-1003). `<branch>..main` counts commits main has BY SHA that the branch lacks. It is
    NEVER a claim that their CONTENT is absent from the branch — a change that reached the branch by
    another commit still shows as a difference. The bound is stated in the lens, in the `next`, and
    in the rendered line, because the reporter's own supporting claim had to be retracted on exactly
    this point and a view that overstates its measurement earns the skimming it gets.

    FOUR BOUNDS, and every one lives HERE rather than in the reader
    (`lessons/scope-the-trigger-not-the-view` — the frontier READ is deliberately broad; what
    INTERRUPTS is the trigger, and the trigger is the fold):

      (a) NAMESPACE — `AHEAD_BRANCH_NAMESPACES`, the two namespaces `worktree new` creates. SHARED
          with rule 24, never re-declared, so the subject bound cannot drift between the two halves.
      (b) BEHIND — a positive non-bool int. A git older than 2.41 has no `%(ahead-behind:)` field, so
          the count arrives unreadable and the branch DROPS: the view degrades to SILENT rather than
          to a wrong number, which is the only safe direction for a report-only surface.
      (c) LIVE — the branch must have a WORKTREE. This is where the two halves legitimately differ,
          and the difference is the harm each reports. Rule 24's subject is unmerged WORK, which is
          at risk whether or not a desk copy still exists. This rule's subject is a tree someone can
          RUN something in, which is the entire cost the card names — a stale suite, a re-fixed RED,
          a merge about to hurt. A branch with no worktree cannot host any of that. Measured on this
          repo 2026-08-25: the four abandoned `_land_bookkeeping_commit` amend-residue refs
          (task/T-10116, T-10122, T-10174, T-10181) sit 16.8k-17.6k commits behind with no worktree
          and no future, so an unbounded fold would put four permanent lines on every echo forever —
          which teaches a reader to skim the echo, and costs more than the blind spot this closes.
      (d) COUNT FLOOR — `behind < floor_commits` is SUPPRESSED; a non-positive floor DISABLES the
          bound (the sibling escape, and the shape a test uses to prove the floor is the cause).
          THIS FLOOR IS ON COMMITS, NOT ON AGE, and that is a deliberate departure from every sibling
          floor in this module. Age carries no information here: a repo committing hundreds of times
          a day makes a copy cut this morning hundreds behind by noon, while a quiet day barely moves
          it — so the same elapsed hours mean opposite things in two repos, and in the same repo on
          two days. Distance from main is the thing that hurts, so distance is what is measured.

    WHY 200 — measured separation, on both available datasets, never a decreed number. On this repo's
    live frontier 2026-08-25 the six genuinely live lanes sat at 29 / 33 / 33 / 33 / 42 / 68 commits
    behind and the three genuinely stale desk copies at 995 / 3946 / 4268: NOTHING at all lies between
    68 and 995, so the floor sits an order of magnitude above every live lane and an order below every
    stale one. It is also below the originating incident's own 234 (<project> T-0435), so it would have
    fired there. The knob is `YITC_DEBT_BEHIND_BRANCH_FLOOR_COMMITS` for a repo whose separation sits
    elsewhere.

    REPORT-ONLY, and the requester made this bound their own. It names no candidate, ranks nothing,
    selects nothing and gates nothing; the only pointer it carries is a read-only `git log`. A stale
    copy is very often perfectly fine — a parked card's worktree is stale BY DEFINITION and harmless
    until someone runs a suite in it — so a threshold that refused, or a verb that declined to serve
    a behind branch, would turn a surfacing view into a fence and ship something nobody asked for.

    Args:
      _frontier: `() -> [{"branch", "behind", "committed_at", "has_worktree"}]` — one row per local
        branch, with how far main has run ahead of it and whether a worktree is checked out on it.
        ONE frontier read at the caller, never one call per branch. LOAD-BEARING: a reader that
        raises or yields a non-list ⇒ a clean, zero-count result (a view must never break the seam it
        rides).
      floor_commits: the COUNT floor (see (d)). Non-positive DISABLES it.
      now: aware datetime, stamped into the result. Injected by the tests, so no assertion is
        wall-clock-dependent.

    Returns `{"lens", "now", "count", "floor_commits", "branches", "next"}` — the shape every sibling
    returns. Pure: reads, writes nothing, emits nothing, gates nothing.
    """
    now = now if now is not None else datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    try:
        frontier = _frontier() or []
    except Exception:
        return _behind_branches_result(now, [], floor_commits)
    if not isinstance(frontier, (list, tuple)):
        return _behind_branches_result(now, [], floor_commits)

    branches = []
    for row in frontier:
        if not isinstance(row, dict):
            continue
        branch = row.get("branch")
        # (a) NAMESPACE — the lifecycle-owned refs, shared with rule 24 and never re-declared.
        if not isinstance(branch, str) or not branch.startswith(AHEAD_BRANCH_NAMESPACES):
            continue
        # (b) BEHIND — an unreadable count DROPS the branch: silent, never wrong.
        behind = row.get("behind")
        if not isinstance(behind, int) or isinstance(behind, bool) or behind <= 0:
            continue
        # (c) LIVE — a tree someone can run something in. Anything else is not this view's subject.
        if row.get("has_worktree") is not True:
            continue
        # (d) COUNT FLOOR — distance, never elapsed time. See (d) above for why.
        if floor_commits > 0 and behind < floor_commits:
            continue
        branches.append({
            "branch": branch,
            "behind": behind,
            "tip_at": row.get("committed_at") or None,
        })

    # Furthest behind first — the one most likely to hurt reads first.
    branches.sort(key=lambda r: (-(r["behind"] or 0), r["branch"] or ""))
    return _behind_branches_result(now, branches, floor_commits)



def _behind_branches_result(now, branches: list, floor_commits: int = 200) -> dict:
    return {
        "lens": "behind-work-branches (SPEC-0119 rule 32) — LIVE `task/*` / `work/*` worktrees whose "
                "branch main has run far ahead of. Rule 24 reports how far AHEAD of main a branch is; "
                "this reports how far BEHIND, which is the half that says whether the branch is about "
                "to hit a painful merge or to run a suite against a tree main fixed hours ago. "
                "Behind-ness is otherwise computed in exactly ONE place in the engine — inside "
                "`worktree sync`, the verb that also CURES it — so its record is a receipt for the "
                "cure and never a signal of the disease, and a branch nobody synced is measured by "
                "nothing (a consumer's X-1105: five live worktrees behind by 881, 881, 881, 273 and 168 "
                "while the echo named one branch, for being AHEAD by one commit). The count is of "
                "commits main has BY SHA that the branch lacks and is NEVER a claim their CONTENT is "
                "absent from the branch (a consumer's X-1003). Derived from the git frontier at read "
                "time; ZERO stored state, report-only, never a gate, and it selects nothing. A COUNT "
                "floor — not an age floor — suppresses a branch nearer than `floor_commits`, because "
                "a fast repo makes a morning-cut copy hundreds behind by noon while a quiet day "
                "barely moves it, so elapsed time carries no information here.",
        "now": now.isoformat().replace("+00:00", "Z"),
        "count": len(branches),
        "floor_commits": floor_commits,
        "branches": branches,
        "next": ("these worktrees are running against a tree main has moved well past. READ what each "
                 "is missing first — `git log --oneline <branch>..main` — and remember the count is by "
                 "SHA, not by content: a change that reached the branch another way still shows here. "
                 "A stale copy is often perfectly fine; the row drops by itself once the branch catches "
                 "up or its worktree goes away."
                 if branches else
                 "no live work branch is further behind main than the floor — nothing running stale."),
    }



def concurrent_session_holds(_holders, own_ref, *, own_fleet_refs=None, now=None, UNKNOWN_HOLDER=None, _concurrent_holds_result=None, _hold_task_of=None) -> dict:
    """Fold the LIVE worktree list + its session stamps → the holds carried by a session OTHER than
    the reading one (SPEC-0119 rule 25). A pure fold over an injected reader, `{lens, now, count, …}`
    out, report-only, ZERO stored state — the rule-24 contract, reused rather than re-decreed.

    WHAT IT MAKES VISIBLE, and why nothing else does. Every surface a controller reads by default
    renders this repo as SINGLE-ACTOR. The line that looks like coverage —
    `session._session_build_dispatch`'s "N task(s) in-progress in other sessions" — folds
    `tasks/*.yaml` STATUS on the checkout it runs in, and a claim (ready→in-progress) is written
    INSIDE the claiming worktree and reaches main only through `land` (D-0037 option B). So a card
    another live session already holds still reads `ready` on main and that line stays silent. The
    only surface that does reveal a second actor is `journal query --dispatch-status`, a per-task
    liveness read a controller has to think to run. Measured on the kernel, 2026-08-21: a controller
    session ran all evening beside a second one, learned of it only by noticing an unfamiliar branch
    name in a `git worktree list` it ran for another reason, and later read T-11368 and T-11370 as
    `ready` on main — both already claimed — one step from dispatching duplicate workers. What
    stopped it was a hand `git worktree list`, not any surface. That is the gap, and it is the whole
    of what this view closes.

    WHAT THE STAMP PROVES, AND WHAT IT DOES NOT — the bound this fold is built to respect (T-0412),
    AND ITS MEASURED EXCEPTION (T-11606). Background workers that INHERIT their controller's provider
    session id share one `session_ref`, so such a fleet reads as ONE stamp. A DISPATCH-LAUNCHED worker
    does NOT: `dispatch` assigns a FRESH ref per worker (it scrubs the identity carriers deliberately)
    and records it as `expected` on its own `bg_dispatch_launched`. So one controller's dispatched
    fleet reads as N DISTINCT stamps, every one of them "other". Measured on the kernel
    2026-08-26T03:20Z: 19 stamps holding 19 worktrees, at least two of them the READING controller's
    own workers — and the one genuinely foreign holder that night was found by hand in `git worktree
    list`, not here, because it would have been the 20th row among 19 of the reader's own.
    ATTRIBUTION IS THEREFORE THE FOLD'S JOB, and `own_fleet_refs` is how the caller supplies it. This
    fold still counts DISTINCT STAMPS and never independent actors — what changes is WHICH stamps the
    count is OF: `count`/`worktrees`/`holders` are the FOREIGN ones, and an attributed own-fleet
    holder moves to `own_fleet` instead of being erased. An UNSTAMPED worktree resolves to
    `UNKNOWN_HOLDER` and is FOREIGN — fail-closed, `_read_worktree_stamp`'s own rule (presence alone
    proved indistinguishable from orphanhood in the 2026-06-05 T-0351 double-claim), and the one
    bucket that is deliberately NOT grouped: two unstamped worktrees are two unknowns, not one holder.
    It is also NEVER attributable: `UNKNOWN_HOLDER` is not a ref and can never match a launch record.

    THE FAIL-SAFE DIRECTION OF ATTRIBUTION IS THE INVERSE OF THIS VIEW'S OTHER ONES, and it is the
    whole safety of the feature (`lessons/a-signal-about-a-reader-fails-safe-the-opposite-way-to-a-gate`
    read from the other end). Elsewhere here the generous reading is the safe one, because a report-only
    signal that over-reports only costs noise. Attribution is the opposite: attributing a holder to MY
    OWN fleet SILENCES it, so a wrong attribution HIDES the exact foreign holder this whole view exists
    to surface. Attribution therefore demands POSITIVE PROOF — a ref the caller resolved from launch
    records THIS reader itself emitted — and every uncertainty resolves the other way: no set, an empty
    set, a non-iterable, an unstamped row, or any ref not positively proven mine stays FOREIGN and
    VISIBLE. Suppression is never a side effect of not knowing.

    PRESENCE AND LIVENESS ARE SEPARATE FIELDS, NEVER ONE BOOLEAN
    (`lessons/a-presence-count-is-not-a-liveness-probe`). A worktree exists for hours; a process probe
    answers about right now. ORing them lets the cheap leg define the answer, which is exactly the
    conflation behind T-0351. So `held` (presence — the FACT) and `alive` (the caller's advisory probe
    — TRUE / FALSE / None for could-not-tell) are carried apart, and a holder whose liveness is
    unknown reports as unknown rather than as either. Liveness is ADVISORY here and nothing more: the
    view adopts nothing, re-stamps nothing, cleans nothing up and acts on nothing.

    Args:
      _holders: `() -> [{"branch", "path", "session_ref", "started_at", "alive"}]` — one row per LIVE
        non-main worktree. ONE `git worktree list --porcelain` parse at the caller, never one call per
        worktree. LOAD-BEARING: a reader that raises or yields a non-list ⇒ a clean, zero-count result
        (a report-only view must never break the seam it rides — rule 24's posture, verbatim).
      own_ref: the READING session's `session_ref`. Rows carrying it are DROPPED in the fold, so AC2's
        suppression is a property of the fold and not of the renderer. `own_ref` None/empty means the
        reader could not resolve its own identity: then NOTHING can be proved foreign, so the whole
        view folds to a clean zero rather than reporting every holder — the fail-safe direction for a
        signal about someone else (`lessons/a-signal-about-a-reader-fails-safe-the-opposite-way-to-a-gate`).
      own_fleet_refs: OPTIONAL iterable of session refs the READING controller itself dispatched (the
        `expected` of its own `bg_dispatch_launched` records — resolved by the caller, never guessed
        here). A holder carrying one of these is ATTRIBUTED to the reader's own fleet: reported under
        `own_fleet` and excluded from `count`/`worktrees`/`holders`. Anything else — None, empty, a
        non-iterable, a raise — attributes NOTHING, so the result is byte-identical to this view before
        attribution existed. That is the fail-safe direction (see above): never suppress on a maybe.
      now: aware datetime for the result stamp; defaults to real UTC now. Injected by the tests.

    Returns `{"lens", "now", "count", "worktrees", "holders", "own_fleet", "next"}` where `count` is
    the number of DISTINCT FOREIGN STAMPS and `worktrees` the number of live worktrees they hold
    between them, and `own_fleet` is `None` unless a holder was positively attributed to the reader's
    own dispatched fleet. Pure: reads nothing, writes nothing, emits nothing, gates nothing, refuses
    nothing.
    """
    now = now if now is not None else datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    # An unresolvable own identity cannot prove ANY row foreign — go silent, never accuse.
    if not isinstance(own_ref, str) or not own_ref.strip():
        return _concurrent_holds_result(now, [])
    try:
        rows = _holders() or []
    except Exception:
        return _concurrent_holds_result(now, [])
    if not isinstance(rows, (list, tuple)):
        return _concurrent_holds_result(now, [])

    # THE ATTRIBUTION SET, normalized DEFENSIVELY because a wrong one SUPPRESSES (see the fail-safe
    # paragraph above): anything that is not a usable collection of non-empty ref strings attributes
    # NOTHING, which leaves every holder foreign and visible — the direction a mistake must fail in.
    # A bare `str`/`bytes` is REJECTED rather than iterated: iterating one yields CHARACTERS, so a
    # caller that passed a single ref instead of a set of them would attribute — and thereby SILENCE —
    # every one-character stamp. Caught by its own test arm; the cost of the mistake is a hidden
    # holder, which is the one outcome this view exists to prevent.
    if isinstance(own_fleet_refs, (str, bytes)):
        own_fleet_refs = None
    try:
        fleet = {r.strip() for r in (own_fleet_refs or ()) if isinstance(r, str) and r.strip()}
    except TypeError:                      # a non-iterable attributes nothing, and never raises out
        fleet = set()

    grouped: dict = {}
    own_fleet: dict = {}
    unknowns: list = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        branch = row.get("branch")
        if not isinstance(branch, str) or not branch.strip():
            continue
        ref = row.get("session_ref")
        ref = ref.strip() if isinstance(ref, str) and ref.strip() else None
        if ref == own_ref:
            continue                       # (a) OWN hold — this is AC2's suppression, in the fold.
        # `alive` is the caller's ADVISORY probe and stays SEPARATE from presence: True / False /
        # None (could not tell). It is never folded into the presence count and never gates a row.
        alive = row.get("alive") if isinstance(row.get("alive"), bool) else None
        entry = {"branch": branch, "task": _hold_task_of(branch),
                 "since": row.get("started_at") or None, "alive": alive}
        if ref is None:
            # (b) UNSTAMPED ⇒ FOREIGN, and NOT grouped: two unknowns are two unknowns, never one
            # holder — grouping them would invent a shared identity the stamps do not prove.
            unknowns.append({"session_ref": UNKNOWN_HOLDER, "held": 1, "alive": alive,
                             "branches": [branch], "tasks": [t for t in (entry["task"],) if t],
                             "since": entry["since"]})
            continue
        # (c) GROUP BY STAMP — the count is of DISTINCT STAMPS, never of actors (T-0412). A stamp the
        # caller proved is one of MY OWN dispatched workers groups into `own_fleet` instead, so it is
        # ATTRIBUTED rather than erased and never counts as evidence of another controller (T-11606).
        into = own_fleet if ref in fleet else grouped
        g = into.setdefault(ref, {"session_ref": ref, "held": 0, "alive": None,
                                  "branches": [], "tasks": [], "since": None})
        g["held"] += 1
        g["branches"].append(branch)
        if entry["task"]:
            g["tasks"].append(entry["task"])
        # The EARLIEST stamp wins the holder's `since` — how long this stamp has been present here.
        if entry["since"] and (g["since"] is None or str(entry["since"]) < str(g["since"])):
            g["since"] = entry["since"]
        # A holder is reported alive only if SOME row of theirs was probed alive; a probe that could
        # not tell leaves it None rather than asserting False (the could-not-tell leg stays honest).
        if alive is True:
            g["alive"] = True
        elif alive is False and g["alive"] is None:
            g["alive"] = False

    holders = sorted(grouped.values(), key=lambda h: (-h["held"], h["session_ref"]))
    holders += sorted(unknowns, key=lambda h: h["branches"][0])
    mine = sorted(own_fleet.values(), key=lambda h: (-h["held"], h["session_ref"]))
    for h in holders + mine:
        h["branches"] = sorted(h["branches"])
        h["tasks"] = sorted(set(h["tasks"]))
    return _concurrent_holds_result(now, holders, mine)



def _hold_task_of(branch: str) -> "str | None":
    """The task id a `task/T-XXXX` branch names, else None (a `work/<slug>` batch names no task).
    Kept beside the fold so the branch→id vocabulary has ONE home in this view."""
    m = re.fullmatch(r"task/(T-\d{4,})", branch or "")
    return m.group(1) if m else None



def _concurrent_holds_result(now, holders: list, own_fleet: "list | None" = None) -> dict:
    worktrees = sum(int(h.get("held") or 0) for h in holders)
    mine = own_fleet or []
    own = {"stamps": len(mine),
           "worktrees": sum(int(h.get("held") or 0) for h in mine),
           "holders": mine,
           "branches": sorted(b for h in mine for b in (h.get("branches") or [])),
           "tasks": sorted({t for h in mine for t in (h.get("tasks") or [])})} if mine else None
    return {
        "lens": "concurrent-session-holds (SPEC-0119 rule 25) — live worktrees in THIS repo stamped "
                "by a session OTHER than the reading one. Every default surface renders this repo as "
                "single-actor: a claim (ready->in-progress) lives in the claiming worktree until "
                "`land`, so a card another session already holds still reads `ready` on main and the "
                "in-progress count says nothing. Derived at read time from the live worktree list + "
                "the T-0362 session stamps; ZERO stored state — no lock, no lease, no registry, no "
                "heartbeat, no liveness FSM (CHARTER §6 named retirements). The count is of DISTINCT "
                "SESSION STAMPS, NEVER of independent actors: a controller and the workers that "
                "INHERIT its provider session id read as ONE stamp (T-0412), so own/foreign collapses "
                "inside such a fleet — but a DISPATCH-LAUNCHED worker gets a FRESH ref, so that fleet "
                "reads as N stamps and is ATTRIBUTED instead, from the reader's own "
                "`bg_dispatch_launched` records, into `own_fleet` (T-11606). Attribution needs "
                "POSITIVE proof and never suppresses on a maybe: an unattributable holder stays "
                "FOREIGN. Liveness is ADVISORY and separate from presence (T-0351, "
                "`lessons/a-presence-count-is-not-a-liveness-probe`) — presence is never proof the "
                "holder is alive. Report-only: it refuses nothing, adopts nothing and selects nothing.",
        "now": now.isoformat().replace("+00:00", "Z"),
        "count": len(holders),
        "worktrees": worktrees,
        "holders": holders,
        "own_fleet": own,
        "next": ("another session's work is live in this repo. READ before you dispatch or claim — "
                 "`git worktree list` for what is held, `bin/yitc-v2 journal query --dispatch-status` "
                 "for per-task liveness — because a held card still reads `ready` on main until its "
                 "land. Concurrency is NORMAL here (D-0083); this only makes it visible."
                 if holders else
                 "no live worktree in this repo carries another session's stamp"
                 + (f" beyond the {own['worktrees']} held by your own dispatched worker(s)."
                    if own else ".")),
    }



def _abort_breadth_refusal(event: dict, *, _ABORT_BREADTH_MEMBER_REQUEUE_VERDICT=None) -> "tuple | None":
    """One journal row -> `(identity_input, branch, class_label, assertions)` if it is a REFUSAL this
    fold counts, else None. It holds the per-type admission gates and NOTHING else — no digest, no
    key, no grouping (SPEC-0119 rule 26 / T-11810).

    `identity_input` is the dict handed to the INJECTED `_cause_identity`; this function never calls
    it and never computes one. For a `land_completed` row that dict IS the row's own `data` (today's
    behaviour, byte-identical). For a `land_member_verdict` row it is `{"failing_assertions": <the
    row's red_assertions>}` — the ONE-KEY ADAPTER described in the block above.

    FAIL-CLOSED, in the same posture the fold already had, extended to the new type rather than
    loosened for it:
      - `land_completed`: not a refusal unless `status == "abort"`; a row marked
        `cause_identity_absent` (T-10893) is skipped BEFORE any keying, never collapsed onto the
        coarse `abort_class`.
      - `land_member_verdict`: not a refusal unless the verdict is exactly
        `requeued-after-red-batch`. A `landed`, `evicted-for-conflict`, `dropped-dead-member` or
        `unaccounted` row is not a refusal at all — the precise analog of the `status != "abort"`
        skip above. ABSENT MEANS UNRECORDED: a requeue whose batch surfaced no assertion text carries
        no `red_assertions`, yields no identity, and contributes to no streak; it is never given one.
      - BOTH: the branch is the row's own `branch` field and must be a non-blank string, since a
        blank branch is not a distinct one and counting it would manufacture a cross-branch signal
        out of a single lane.
    Every one of these skips UNDER-counts, which is this fold's whole error direction.

    `class_label` is what the rendered line prints before the digest. An abort row supplies its real
    `abort_class`. A member row has none, so it supplies its OWN verdict string — vocabulary the
    reader already knows from the row itself, and the same "reuse the closed vocabulary, mint
    nothing" argument `_emit_land_member_verdicts` makes for keeping that string unchanged. A group
    that sees a real `abort_class` prefers it (see the fold), so no existing group's label moves.
    """
    if not isinstance(event, dict):
        return None
    etype = event.get("type")
    data = event.get("data") if isinstance(event.get("data"), dict) else {}
    if etype == "land_completed":
        if data.get("status") != "abort":
            return None           # a SUCCESSFUL land is not a refusal
        if data.get("cause_identity_absent"):
            return None           # fail-closed: never coarse-key onto abort_class
        identity_input, assertions = data, data.get("failing_assertions")
        class_label = data.get("abort_class")
    elif etype == "land_member_verdict":
        if data.get("verdict") != _ABORT_BREADTH_MEMBER_REQUEUE_VERDICT:
            return None           # only the red-batch requeue is a refusal
        assertions = data.get("red_assertions")
        if not assertions:
            return None           # ABSENT MEANS UNRECORDED — no cause to key on
        identity_input = {"failing_assertions": assertions}   # the ONE-KEY adapter
        class_label = _ABORT_BREADTH_MEMBER_REQUEUE_VERDICT
    else:
        return None
    branch = data.get("branch")
    if not isinstance(branch, str) or not branch.strip():
        return None               # fail-closed: a blank branch is not a distinct one
    names = [str(a) for a in assertions if str(a).strip()] if isinstance(assertions, list) else []
    return (identity_input, branch.strip(), class_label, names)



def _abort_breadth_resolution(event: dict, *, _ABORT_BREADTH_MEMBER_LANDED_VERDICT=None) -> "str | None":
    """One journal row -> the BRANCH it proves reached `main`, else None (SPEC-0119 rule 26).

    THE MIRROR OF `_abort_breadth_refusal`, and the reason rule 26 now drops on RESOLUTION rather
    than on AGE alone (T-12052). Rule 34's transpose has read the landing row since T-11821 — "a
    landed branch stops being reported" — and rule 18's family doctrine (T-10858) is that the drop
    criterion is RESOLUTION, never AGE. This is that predicate, borrowed rather than invented; the
    only thing rule 26 lacked was a way to notice that the branches a cause refused have since
    landed.

    TWO REFUSAL SHAPES, TWO RESOLUTION SHAPES — the symmetry is load-bearing, not tidiness. A
    `land_completed{status: ok}` row is the obvious one. A `land_member_verdict{verdict: landed}` row
    is the OTHER one, and it is REQUIRED rather than decorative: MEASURED on this repo's journal
    (2026-09-04), of 209 member `landed` rows, FIVE name a branch that carries no
    `land_completed{status: ok}` row at all (`task/T-11742`, `T-11767`, `T-11833`, `T-11609`,
    `T-11610`) — a branch that reached main AS A BATCH MEMBER can have its success recorded ONLY in
    the member verdict. Reading the abort row alone would therefore leave the requeue refusal shape
    (T-11810) PERMANENTLY unresolvable on exactly those branches, i.e. it would fix the incident for
    one shape and re-create it for the other. Both types are already in `_ABORT_BREADTH_EVENTS`, so
    this adds no source, no type set and no second reading of the journal.

    NO CAUSE IDENTITY IS COMPUTED OR CONSULTED, deliberately. A land resolves the BRANCH, whatever
    refused it: the branch is on main, so nothing it was refused for is still refusing it. Keying the
    resolution by cause would ask a question the row cannot answer (a successful land carries no
    failing-assertion set) and would mint a second opinion about identity, which is exactly what rule
    26 refuses to buy (CHARTER P5).

    FAIL-CLOSED ON THE BRANCH, in the same posture and for the same reason as its sibling: the branch
    is the row's own `branch` field and must be a non-blank string. Here the skip leans the OTHER way
    from every other skip in this fold — an unusable resolution row means a branch is NOT credited as
    resolved, so the fold keeps REPORTING it. That is the correct direction: this fold's error
    posture is "print nothing rather than lie", and failing to clear a line is a false POSITIVE the
    reader can check against the branch, whereas clearing one on a row we could not read would hide a
    live cause.
    """
    if not isinstance(event, dict):
        return None
    etype = event.get("type")
    data = event.get("data") if isinstance(event.get("data"), dict) else {}
    if etype == "land_completed":
        if data.get("status") != "ok":
            return None           # an ABORT is not a resolution; anything else is not one either
    elif etype == "land_member_verdict":
        if data.get("verdict") != _ABORT_BREADTH_MEMBER_LANDED_VERDICT:
            return None           # only the member that actually LANDED resolves its branch
    else:
        return None
    branch = data.get("branch")
    if not isinstance(branch, str) or not branch.strip():
        return None               # fail-closed: an unreadable branch credits nothing as resolved
    return branch.strip()



def land_abort_cause_breadth(events_path, *, _cause_identity,
                             window_hours: int = _ABORT_BREADTH_WINDOW_HOURS,
                             min_branches: int = _ABORT_BREADTH_MIN_BRANCHES, now=None, _ABORT_BREADTH_EVENTS=None, _ABORT_BREADTH_MAX_NAMED_ASSERTIONS=None, _abort_breadth_refusal=None, _abort_breadth_resolution=None, _parse_stamped_deadline=None, _window_segment_floor=None) -> dict:
    """Fold the journal → the causes still UNRESOLVED on `min_branches` or more DISTINCT branches
    inside `window_hours` (SPEC-0119 rule 26).

    THE DROP CRITERION IS RESOLUTION, NOT AGE (T-12052 — and this AMENDS what this fold used to
    claim). A branch is RESOLVED for a cause once a resolution row for that branch (see
    `_abort_breadth_resolution`) is dated AFTER that branch's last refusal on it; only UNRESOLVED
    branches are counted against `min_branches`. The window survives as the OUTER HORIZON only — it
    still ages out a branch that was abandoned or parked and never landed at all.
    WHAT THIS OVERTURNS, named rather than quietly replaced: the window was previously this fold's
    SOLE clearing rule, and both its own posture line ("the row drops by itself once the cause stops
    recurring") and the host knob's docstring ("what keeps a cause that was FIXED yesterday from
    being re-announced today") asserted that the horizon was enough. It was not, and the
    counter-example is exactly the class the line exists for: MEASURED 2026-09-04 ~04:00Z, this fold
    named `verify-failed#af84843f8263` on `task/T-11991` / `task/T-12008` / `task/T-12028` when all
    three had landed `status: ok` the previous day (06:52Z / 13:31Z / 18:12Z) and the fixing card
    T-12032 had landed at 02:38Z. Every fact in the line was true and the reading it produced —
    "one cause is refusing three branches" — was false, which is how a report-only surface stops
    being read (fingerprint `debt-rule26-stale-cause-after-fix-landed`, owner-surfaced). The
    predicate is BORROWED, not invented: rule 34's transpose has stopped reporting a landed branch
    since T-11821, and rule 18 (T-10858) states the family doctrine that a debt line drops on
    RESOLUTION and never on AGE. Rule 26 was the one member of the family still dropping on the
    clock.

    TWO REFUSAL SHAPES, ONE CAUSE IDENTITY (T-11810). A refusal is a `land_completed{status: abort}`
    row OR a `land_member_verdict{verdict: requeued-after-red-batch}` row — a red batch lands nobody
    and requeues every member, which is a fully paid verify that shipped nothing exactly as an abort
    is. Both are keyed through the SAME injected identity, the member row via a one-key rename of
    `red_assertions` onto `failing_assertions`; the admission gates and the reasons live in
    `_abort_breadth_refusal`, which is where a reader should go for them. A branch counts ONCE per
    cause however many shapes it arrived in, because the grouping key is the identity and the branch
    store is a SET.

    Pure: reads one file, writes nothing — the boundary every sibling fold here shares. A missing or
    unreadable journal, a malformed line, an unparseable `ts` all yield a clean zero-count result: a
    report-only surface never breaks the seam it rides and never nags on an unknown.

    WHY THE THRESHOLD DEFAULTS TO 2, and why that is not a noise setting. One branch repeating on one
    cause is ALREADY the repeated-abort backstop's business (T-0655) and never reaches this fold at all —
    the grouping key is the count of DISTINCT branches, so a branch that aborts ten times on one cause
    contributes exactly 1. What this owns is the FIRST cross-branch repeat, which is the whole gap, and
    each miss of it costs another full 430-560s verify. Two distinct branches is therefore the earliest
    honest moment the signal exists.

    WHY IT IS NOT A NOISE GENERATOR (AC1's second arm, and the design constraint that shaped the fold).
    N refusals of N DIFFERENT causes must produce NOTHING. A line that fired on any burst of aborts gets
    filtered by its reader inside a day, which is how a surface stops being read at all — so the grouping
    is on the cause identity FIRST and the branch count is only ever read WITHIN one such group.

    FAIL-CLOSED ON BOTH IDENTITIES — a row missing either one is SKIPPED, never approximated (the
    per-type predicates are `_abort_breadth_refusal`'s; what follows is why they are shaped so):

      (a) NO FINE CAUSE IDENTITY (AC3 / T-10893). A row carrying `cause_identity_absent`, or one whose
          injected identity is None, contributes to NO streak. It is NOT collapsed onto the coarse
          `abort_class` — that is the whole trap: `verify-failed` is the class of every verify failure
          (a chokepoint refusal, a pinned staleness, a real regression), so coarse-keying would FUSE
          two separately-resolved causes and print a confident false streak (the X-0737 / X-0741 class,
          ~2h and 5 land attempts frozen on a branch that was green throughout). The cost of the skip is
          a line that does not print; the cost of the collapse is a line that lies. This mirrors the skip
          `_land_repeated_abort_count` already performs on the same marker, rather than deciding it twice.

      (b) NO USABLE BRANCH. The branch is the row's own `branch` field; a row whose branch is absent,
          non-string or blank is skipped BEFORE grouping. Counting None/blank as "a branch" would
          manufacture a cross-branch signal out of a single lane — the same failure in the other axis.

    Both skips are UNDER-counts by design, and they compose with the identity under-count in the module
    comment above: this fold's every error leans toward printing nothing.

    `_cause_identity` is a REQUIRED keyword-only callable `(data_dict) -> str | None` — the host binds
    `worktree._land_abort_cause_identity`. Injected rather than imported so the fold stays leaf-testable
    and the identity keeps ONE home.

    Returns `{lens, now, window_hours, min_branches, count, causes, next}` — the shape the sibling views
    return. Each cause: `{identity, abort_class, assertions, branches, branch_count,
    unresolved_branches, resolved_count, first_ts, last_ts}`, where `assertions` is the BOUNDED
    sample of failing-assertion text the render names beside the digest (empty when no row carried
    any — never a fabricated name).

    THE TWO COUNTS ARE DIFFERENT QUESTIONS AND NEITHER IS REDUNDANT (T-12052). `branches` /
    `branch_count` are EVERY branch the cause refused in the window — meaning UNCHANGED, so no
    existing reader moves — and are what the render names, since a reader chasing the cause wants
    every lane it hit. `unresolved_branches` is the SUBJECT: the branches whose last refusal on this
    cause post-dates their last landing, and its length ALONE gates `min_branches`.
    `resolved_count` is their difference, rendered as "(K since landed)" so a partially-resolved
    cause is legible rather than silently under-stated. `abort_class`, `assertions`, `first_ts` and
    `last_ts` are built from the UNRESOLVED refusals only, because the render reads all four in the
    PRESENT TENSE — putting a since-landed refusal's stamp on `last_ts` would be the T-11900 misread
    arriving through the fix for it.
    """
    now = now if now is not None else datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    # Window expressed as elapsed SECONDS, the idiom every sibling fold in this module already
    # uses (`(now - ts).total_seconds()`); SPEC-0149's structural tripwire forbids duration
    # vocabulary anywhere in this module, and there is no reason for this fold to be the
    # exception when the existing idiom expresses the same window exactly.
    window_seconds = float(window_hours) * 3600.0

    # ONE pass, TWO collections (T-12052). Refusals are held as rows rather than folded straight
    # into their group, because whether a refusal COUNTS depends on a resolution that may arrive
    # later in the stream — so the grouping cannot be decided until the whole window is read. The
    # resolution map is per BRANCH and cause-agnostic (see `_abort_breadth_resolution`).
    refusals: list = []
    resolved_at: dict = {}
    try:
        # SPEC-0190 rule 4 (T-11868, bounded by T-12030) — the segments this fold's window can
        # REACH. NOTHING guarantees the live segment spans a 24h window: a rotation lands mid-window
        # and the view under-reports a cause that IS recurring (the X-1100 class), which is why this
        # reader is on the archive branch at all. What T-12030 removes is the OTHER end — it no longer
        # opens the 90-odd segments whose dated names lie wholly before the window. `segment_rows_since`
        # reads each selected member through the SAME `fold_rows` primitive, so this is still one
        # parse path and one request-scoped memo, and the `window_seconds` test below is unchanged and
        # still decides every row.
        for event in journal.segment_rows_since(
                events_path, _window_segment_floor(now, hours=window_hours), types=_ABORT_BREADTH_EVENTS):
            if not isinstance(event, dict) or event.get("type") not in _ABORT_BREADTH_EVENTS:
                continue
            ts = _parse_stamped_deadline(event.get("ts"))
            if ts is None or (now - ts).total_seconds() > window_seconds:
                continue          # undatable ⇒ unplaceable in the window; older ⇒ out of it
            # RESOLUTION FIRST — the two predicates are disjoint by construction (an abort is not an
            # ok; a requeue is not a landed), so the order is readability, not precedence.
            landed_branch = _abort_breadth_resolution(event)
            if landed_branch is not None:
                # LATEST wins: a branch that landed, was re-refused and landed again is resolved at
                # the LAST landing, so only refusals after that one can still be live.
                prev = resolved_at.get(landed_branch)
                if prev is None or ts > prev:
                    resolved_at[landed_branch] = ts
                continue
            refusal = _abort_breadth_refusal(event)
            if refusal is None:
                continue          # not a refusal, or fail-closed on branch/identity input
            identity_input, branch, class_label, names = refusal
            try:
                ident = _cause_identity(identity_input)
            except Exception:     # noqa: BLE001 — an identity that RAISED proved nothing
                ident = None
            if not ident:
                continue          # (a) again, for a row that carries no marker but yields no identity
            refusals.append((str(ident), branch, ts, event.get("type"), class_label, names))
    except (OSError, UnicodeDecodeError):
        refusals, resolved_at = [], {}

    groups: dict = {}
    for ident, branch, ts, etype, class_label, names in refusals:
        g = groups.setdefault(ident, {"identity": ident,
                                      "abort_class": None,
                                      "abort_class_is_class": False,
                                      "assertions": set(), "branches": set(),
                                      "unresolved": set(),
                                      "first_ts": None, "last_ts": None})
        # The branch SET is what makes AC2's dedup structural: the same branch arriving on both
        # row shapes for one cause is added twice and counts once. `branches` is EVERY branch this
        # cause refused — its meaning is UNCHANGED by T-12052, so no existing reader moves.
        g["branches"].add(branch)
        # THE RESOLUTION PREDICATE (T-12052). A refusal is LIVE only if it post-dates the branch's
        # most recent landing — the exact analog of rule 34's `attempts` filter, and the reason this
        # line now clears when the thing it named got fixed instead of when the clock ran out. Note
        # it is `>` and not `>=`: equal stamps are the SAME instant, and a landing cannot be said to
        # have resolved a refusal it did not follow.
        last_ok = resolved_at.get(branch)
        if last_ok is not None and ts <= last_ok:
            continue          # this refusal reached main afterwards — it is history, not a signal
        g["unresolved"].add(branch)
        # Everything below is an annotation the RENDER reads in the PRESENT TENSE (the label, the
        # named assertions, the T-11900 age), so each is built from LIVE refusals only. Folding a
        # since-landed refusal in here would put a dead cause's age on a live row — the precise
        # misread T-11900 fixed on the other axis.
        # An abort row's REAL `abort_class` wins over a member row's verdict-string stand-in, so a
        # group that ever sees one keeps today's label and no existing row's rendering moves.
        if g["abort_class"] is None or (etype == "land_completed" and not g["abort_class_is_class"]):
            g["abort_class"] = class_label
            g["abort_class_is_class"] = etype == "land_completed"
        g["assertions"].update(names)
        g["first_ts"] = ts if g["first_ts"] is None else min(g["first_ts"], ts)
        g["last_ts"] = ts if g["last_ts"] is None else max(g["last_ts"], ts)

    def _iso(t):
        return t.isoformat().replace("+00:00", "Z")

    causes = [{"identity": g["identity"], "abort_class": g["abort_class"],
               # `branches` / `branch_count` are EVERY branch this cause refused — meaning UNCHANGED
               # by T-12052, so every existing reader and test keeps its answer. What is NEW is the
               # pair below, and the GATE is the new count alone.
               "branches": sorted(g["branches"]), "branch_count": len(g["branches"]),
               "unresolved_branches": sorted(g["unresolved"]),
               # The K the render names as "(K since landed)" — how many of the refused branches
               # reached main afterwards. Zero for every cause that was reported before T-12052, which
               # is why the rendered line is byte-identical in that case.
               "resolved_count": len(g["branches"]) - len(g["unresolved"]),
               # The AC6 sample: BOUNDED and sorted for determinism. Empty when every row this cause
               # was built from carried no assertion text — the line then names the digest alone
               # rather than inventing a name.
               "assertions": sorted(g["assertions"])[:_ABORT_BREADTH_MAX_NAMED_ASSERTIONS],
               "first_ts": _iso(g["first_ts"]), "last_ts": _iso(g["last_ts"])}
              # THE GATE IS THE UNRESOLVED COUNT (T-12052). A cause every one of whose branches has
              # since landed has an empty `unresolved` set, so it fails this test at any threshold and
              # the line goes silent the moment the fix lands — rather than 24h later.
              # `g["unresolved"]` is tested for EMPTINESS as well as against the threshold, and the
              # first conjunct is not redundant with the second: a caller may pass `min_branches=0`
              # (a probe driving the fold below the knob's floor does exactly this), and a
              # fully-resolved group would then pass `0 >= 0` while carrying NO live refusal at all —
              # no class, no assertions and a `first_ts`/`last_ts` of None, which the `_iso` below
              # cannot render. A cause with nothing unresolved is RESOLVED, at every threshold: that
              # is the rule, so it is stated as one rather than left to arithmetic.
              for g in groups.values() if g["unresolved"] and len(g["unresolved"]) >= min_branches]
    causes.sort(key=lambda c: (-len(c["unresolved_branches"]), c["last_ts"]))
    return {
        "lens": f"land-abort cause breadth (SPEC-0119 rule 26) — ONE cause STILL UNRESOLVED on "
                f"{min_branches}+ DIFFERENT branches in the last {window_hours}h, counting BOTH "
                f"refusal shapes: a land ABORT and a red-batch REQUEUE (`land_member_verdict`), "
                f"since a red batch lands nobody and every member paid a full verify that shipped "
                f"nothing. A branch counts ONCE per cause however many shapes it arrived in. Every "
                f"surface is per-branch or per-task (the re-run-vs-resolve discipline is per SESSION, "
                f"the repeated-abort backstop per BRANCH, the audit-loop ceiling per TASK), so a cause "
                f"failing ONCE on each of four branches trips none of them and each branch re-diagnoses "
                f"it from scratch at a full verify's cost. Keyed on the SAME fine cause identity the "
                f"backstop streaks on — never a second one — so it UNDER-reports when one cause "
                f"co-fails with different sibling assertions, and rows with no fine identity or no "
                f"usable branch are SKIPPED rather than collapsed onto the coarse abort_class. Folded "
                f"from the journal; ZERO stored state, report-only, never a gate. A branch DROPS OUT "
                f"once it LANDS (T-12052): the drop criterion is RESOLUTION, never AGE (rule 18's "
                f"family doctrine, rule 34's landed-branch predicate), and the window is only the "
                f"outer horizon for a branch that never lands at all. A MITIGATION, not a "
                f"fix: a repo-wide freeze is fixed by making the gate branch-attributable (T-11379).",
        "now": _iso(now),
        "window_hours": window_hours,
        "min_branches": min_branches,
        "count": len(causes),
        "causes": causes,
        "next": ("one cause is refusing branch after branch and each is paying a full verify to "
                 "re-diagnose it independently. Read ONE of the named branches' abort rows, fix the "
                 "cause ON MAIN (or make the gate branch-attributable), and the rest stop paying for "
                 "it. This names a CAUSE, not a candidate: it selects nothing, refuses nothing, and "
                 "each branch drops off the row the moment it LANDS — the whole row goes silent as "
                 "soon as the last of them does, not when the window expires."
                 if causes else
                 "no abort cause is still unresolved on several different branches in the window."),
    }



def _branch_burn_land_row(event: dict, *, _ABORT_BREADTH_MEMBER_REQUEUE_VERDICT=None) -> "tuple | None":
    """One journal row -> `(kind, branch, class_label, identity_absent)` where `kind` is
    `"refusal"` or `"landed"`, else None (SPEC-0119 rule 34).

    CAUSE-AGNOSTIC BY CONSTRUCTION — and that is the whole rule, not an omission. Unlike rule 26's
    `_abort_breadth_refusal`, this admits a refusal that carries NO cause identity: those rows are
    precisely the ones the T-0655 backstop cannot streak on, so skipping them would rebuild the very
    blind spot this projection exists to remove. It therefore computes no identity and consults none.

    The REFUSAL SHAPES are rule 26's, reused: a `land_completed{status: abort}` row, and a
    `land_member_verdict{verdict: requeued-after-red-batch}` row — a red batch lands nobody and every
    member paid a full verify that shipped nothing, which is an unlanded attempt in every way this
    fold cares about.

    `kind == "landed"` is a `land_completed{status: ok}` row. It is not an attempt; it is what ENDS
    a burn, and the fold uses it to stop reporting a branch whose attempts reached main.

    `identity_absent` records whether the row could have carried a refined cause key at all — the
    marker on an abort row, or the absence of `red_assertions` on a requeue. Carried as an
    ANNOTATION only: it never admits or excludes a row here, and no key is derived from it.

    FAIL-CLOSED on the branch, exactly as the sibling is: the branch is the row's own `branch` field
    and must be a non-blank string. A blank branch is not a branch, and counting it would fuse
    unrelated lanes into one invented burn.
    """
    if not isinstance(event, dict):
        return None
    etype = event.get("type")
    data = event.get("data") if isinstance(event.get("data"), dict) else {}
    if etype == "land_completed":
        status = data.get("status")
        if status == "ok":
            kind, class_label, absent = "landed", None, False
        elif status == "abort":
            kind = "refusal"
            class_label = data.get("abort_class") or "unclassified"
            absent = bool(data.get("cause_identity_absent"))
        else:
            return None
    elif etype == "land_member_verdict":
        if data.get("verdict") != _ABORT_BREADTH_MEMBER_REQUEUE_VERDICT:
            return None
        kind = "refusal"
        class_label = _ABORT_BREADTH_MEMBER_REQUEUE_VERDICT
        absent = not data.get("red_assertions")
    else:
        return None
    branch = data.get("branch")
    if not isinstance(branch, str) or not branch.strip():
        return None
    return (kind, branch.strip(), class_label, absent)



def branch_unlanded_attempt_burn(events_path, *,
                                 window_hours: int = _ABORT_BREADTH_WINDOW_HOURS,
                                 min_attempts: int = _BRANCH_BURN_MIN_ATTEMPTS, now=None, _ABORT_BREADTH_EVENTS=None, _branch_burn_land_row=None, _parse_stamped_deadline=None) -> dict:
    """Fold the journal -> the BRANCHES that burned `min_attempts` or more UNLANDED land attempts
    inside `window_hours`, WHATEVER the cause each time (SPEC-0119 rule 34).

    Pure: reads one file, writes nothing — the boundary every sibling fold in this module shares. A
    missing or unreadable journal, a malformed line or an unparseable `ts` all yield a clean
    zero-count result: a report-only surface never breaks the seam it rides and never nags on an
    unknown.

    WHY THE WINDOW IS RULE 26'S AND NOT ITS OWN. `window_hours` defaults to
    `_ABORT_BREADTH_WINDOW_HOURS`, the horizon rule 26 already reads on (and the host binds the same
    knob). The two folds are transposes of ONE reading, met by the same reader at the same seam, and
    a second horizon would mean a reader holding two. Measured on this repo's journal over
    2026-08-21..28 — the freeze week, i.e. the unfavourable case — the reading at `min_attempts` 4
    barely moves between a 12h and a 24h horizon (a line in 68% of sampled hours naming at most 7
    branches, against 78% and at most 8), so an own window would buy almost no quiet at the price of
    a second governance scalar.

    WHY THE DEFAULT IS 4 AND NOT RULE 26'S 2. Rule 26's 2 is the EARLIEST honest moment its fact
    exists, because each further miss costs ANOTHER branch a full verify. Here the opposite pressure
    governs: retrying is the NORMAL shape of a converging build, and the external adjudication
    rejected a gate precisely so that legitimate iteration is not read as stuckness. So the floor
    must sit ABOVE the ordinary iteration band. Measured over the same window, still-unlanded
    refusals per branch in a trailing 24h: 106 branches never exceed 1, then 50 reach 2 or more, 28
    reach 3 or more, 18 reach 4 or more. The three-attempt convergence band dominates the
    population; 4 is the first value clear of it, and it is one BELOW the smaller of the two shapes
    that PROVED the gap (`task/T-11810` at five aborts, `task/T-11733` at seven) — so the line
    arrives while the burn is still worth interrupting rather than after it has finished.

    A LANDED BRANCH STOPS BEING REPORTED — this is what the word UNLANDED buys, and it is a fold
    predicate, never a gate. Attempts are counted only AFTER the branch's most recent SUCCESSFUL
    land inside the window: a branch whose attempts reached main is provably not burning now. It is
    the exact analog of rule 26's "the row drops by itself once the cause stops recurring", and it
    leans the same way every other skip here does — toward silence.

    Returns `{lens, now, window_hours, min_attempts, count, branches, next}` — the shape the sibling
    views return. Each branch: `{branch, attempts, classes, class_count, incomparable, first_ts,
    last_ts, elapsed_seconds}`, where `classes` is the sorted DISTINCT abort-class set (the
    annotation that says whether the burn is one wall or many), `elapsed_seconds` is the span from
    the first counted attempt to the last (the annotation that separates a three-hour burn from a
    three-minute one), and `incomparable` counts the attempts whose row carries no cause identity at
    all — the number that explains why the repeated-abort backstop never armed.
    """
    now = now if now is not None else datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    # Elapsed SECONDS, the idiom every sibling fold in this module already uses: SPEC-0149's
    # structural tripwire forbids duration vocabulary anywhere in this file, and there is no reason
    # for this fold to be the exception when the existing idiom expresses the same window exactly.
    window_seconds = float(window_hours) * 3600.0

    per_branch: dict = {}
    try:
        # T-13139 — declared: the two land row classes of THIS file (its live-segment horizon unchanged).
        for event in journal.fold_rows(events_path, types=_ABORT_BREADTH_EVENTS):
            if not isinstance(event, dict) or event.get("type") not in _ABORT_BREADTH_EVENTS:
                continue
            row = _branch_burn_land_row(event)
            if row is None:
                continue
            ts = _parse_stamped_deadline(event.get("ts"))
            if ts is None or (now - ts).total_seconds() > window_seconds:
                continue          # undatable => unplaceable in the window; older => out of it
            kind, branch, class_label, absent = row
            per_branch.setdefault(branch, []).append((ts, kind, class_label, absent))
    except (OSError, UnicodeDecodeError):
        per_branch = {}

    def _iso(t):
        return t.isoformat().replace("+00:00", "Z")

    branches = []
    for branch, rows in per_branch.items():
        rows.sort(key=lambda r: r[0])
        last_ok = max((r[0] for r in rows if r[1] == "landed"), default=None)
        # Only the attempts that have NOT been resolved by a land are this view's subject.
        attempts = [r for r in rows if r[1] == "refusal" and (last_ok is None or r[0] > last_ok)]
        if len(attempts) < min_attempts:
            continue
        classes = sorted({r[2] for r in attempts if r[2]})
        branches.append({
            "branch": branch,
            "attempts": len(attempts),
            "classes": classes,
            "class_count": len(classes),
            "incomparable": sum(1 for r in attempts if r[3]),
            "first_ts": _iso(attempts[0][0]),
            "last_ts": _iso(attempts[-1][0]),
            "elapsed_seconds": int((attempts[-1][0] - attempts[0][0]).total_seconds()),
        })
    branches.sort(key=lambda b: (-b["attempts"], b["last_ts"]))
    return {
        "lens": f"stuck-branch unlanded attempts (SPEC-0119 rule 34) — ONE branch that burned "
                f"{min_attempts}+ UNLANDED land attempts in the last {window_hours}h, WHATEVER the "
                f"cause each time. The exact TRANSPOSE of rule 26 (one cause across many branches), "
                f"over the same already-emitted rows and the same two refusal shapes: a land ABORT "
                f"and a red-batch REQUEUE. Every other surface is keyed on the REPETITION OF A "
                f"CAUSE — the repeated-abort backstop arms only on consecutive aborts sharing a "
                f"cause key, the audit-loop ceiling counts audit passes per TASK, re-run-vs-resolve "
                f"is per SESSION, and the aborted-land cost view groups BY CLASS so one branch's "
                f"several classes never sum — so a branch failing for a DIFFERENT reason each time "
                f"trips none of them. Worse: a whole family of abort classes carries NO cause "
                f"identity at all, so consecutive aborts within it are INCOMPARABLE rather than "
                f"merely different, and such a branch is structurally un-armable. The count of "
                f"attempts is the key; the elapsed span and the distinct-class count are "
                f"annotations that make the count actionable. A branch whose attempts reached main "
                f"stops being reported. Folded from the journal; ZERO stored state, report-only, "
                f"never a gate — a cause-agnostic GATE was rejected because it would confuse "
                f"stuckness with legitimate iteration.",
        "now": _iso(now),
        "window_hours": window_hours,
        "min_attempts": min_attempts,
        "count": len(branches),
        "branches": branches,
        "next": ("one branch is paying a full verify per attempt and getting nowhere, and no "
                 "cause-keyed surface can see it. Read that branch's own abort rows end to end "
                 "rather than the latest one — the useful question is whether the attempts are "
                 "converging or circling. This names a BRANCH, not a candidate: it selects "
                 "nothing, refuses nothing and excludes nothing from a batch, and the row drops by "
                 "itself once the branch lands or falls out of the window."
                 if branches else
                 "no branch has burned repeated unlanded land attempts in the window."),
    }
