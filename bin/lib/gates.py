"""Lifecycle-gate cluster for the yitc-v2 CLI — the must-read precondition gate (`_require_reads`),
the stage-correspondence guard (`_require_stage_correspondence`), and the artifacts-as-gate audit
preconditions (`_require_audit_pre_matches_plan` / `_require_audit_post_for_commit`), plus their
gate-exclusive journal helpers (`_session_started_lower_bound` / `_fetched_spec_ids` /
`_stage_correspondence_status`).

This is the home for the lifecycle GATES that used to be scattered across bin/yitc-v2 (the SPEC-0080
§Trigger-surface size lens flagged the 19k-line monolith). bin/yitc-v2 keeps the argparse VERBS (the
cmd_* drivers that CALL these gates), the host globals, and a thin residue under the historical names
that delegates here — so every `yitc.<symbol>` test contract stays byte-identical (the T-9332
extraction; precedent: state.py T-9207 / events.py T-9247 / audit.py T-9248 / graph.py T-9249).

Identity-agnostic KERNEL module (SPEC-0073 bin/ HARD class — travels with the engine). The
host-coupled inputs the gates must NOT read themselves — the host globals (AUDIT_VERDICT_CANONICAL /
AUDIT_VERDICT_CLOSURE_OK) and the host helper callables (_die, _audit_yaml_path, _git_resolve_sha,
_plan_content_hash, _resolve_session_ref, _emit_read_gate_refused, _iter_events, _stage_bundle_specs,
_plan_stage_bundle_specs, _is_consumer_build) — are RESOLVED BY THE CALLER (the bin/yitc-v2 wrappers)
and passed in by INJECTION as keyword params NAMED IDENTICALLY to the host symbols (the state.py
`rel_root` / events.py `guard=` / audit.py `_fn` precedent), so the function BODIES are verbatim and a
test's attribute-replacement of `yitc.<symbol>` is honored by the host wrapper at call time. Behaviour
is byte-identical to the inline original — the test suite is the oracle. Governance follows the SYMBOL,
not the file: SPEC-0042/0049/0050 (must-read precondition family) + SPEC-0059 (universal stage contract)
keep `implements:` anchors repointed to bin/lib/gates.py#<sym>.
"""
from __future__ import annotations

import sys
import time

from lib import state  # lower extracted leaf (CHARTER §P5 one parser library) — leaf-up, no host import


# T-10115 — bounded-retry parameters for the receipt read-gates (`_require_seed_read` /
# `_require_help_read`). The reconcile rewrites events.jsonl IN-PLACE (worktree.py `write_text`, NOT
# an atomic temp+rename), so a concurrent reader can catch a truncated file and TORN-MISS a durably
# present receipt (the 2026-07-04 transient-miss incident). On a would-be refusal the gate re-reads a
# bounded number of times with a small backoff — enough to outlast one in-place rewrite — before it
# refuses. Return-on-first-credit keeps the pass path single-read; the bounded latency lands ONLY on
# the rare refusal path. This is a READ-side consistency belt, NOT a durability layer (append
# atomicity — E-0021 / T-10092 — is unchanged and NOT reopened).
_READ_GATE_RETRY_ATTEMPTS = 3       # total read attempts before a refusal is final
_READ_GATE_RETRY_BACKOFF = 0.05     # seconds between attempts (lets a concurrent in-place rewrite finish)


# T-9786 (X-0158) — the sentinel node_id the `bin/yitc-v2 --help` fetch-receipt records (a `cli_invoked`
# data.node_id row, the emit analog of `graph query <SPEC>`'s node_id). `_require_help_read` checks for
# THIS id in the same evidence window `_require_reads` uses. `cli:` prefix — deliberately NOT a spec id,
# so it never collides with a SPEC-XXXX read and is self-describing in the journal.
HELP_INVENTORY_NODE_ID = "cli:help"
SEED_READ_NODE_ID = "cli:seed"   # T-10081 — the audience-seed read receipt sentinel (SPEC-0042/0050 seed floor); emitted by `session start` after it delivers the audience seed.


# T-11551 — the STAGE POINTER model (the pointer axis of SPEC-0027 §Stage FSM per class).
#
# WHY THIS EXISTS. `_stage_correspondence_status` below is a POINT check: proceed iff `current_stage`
# is already the verb's stage. Since T-0288 the ONLY writer of `current_stage` is the explicit `stage
# <NAME>` verb — a call the natural lifecycle sequence never makes. The T-11048 cluster fold measured
# what that costs: 1170 `stage_mismatch` refusals across 782 sessions, of which `task plan` was
# refused at Analysis in 477 of 483 cases and `task execute` at Audit-pre in 105 of 112. A refusal
# firing on 99% of a verb's real invocations is measuring its own model, not catching an error.
#
# WHAT CHANGES — the POINTER, never the CONTRACT. Which stage delivers what, what each stage gates,
# and every readiness precondition are UNTOUCHED; `stage <NAME>` remains the explicit stage-ENTRY verb
# and the SOLE deliverer of a stage BUNDLE. What this adds is that the pointer ALSO moves along the
# per-class row when the verb sequence itself implies the move. Three admitted moves, one refusal:
#   explicit — current == expected                                  -> proceed (T-0288, unchanged)
#   advance  — expected is the SUCCESSOR of current in this row     -> record the move, then proceed
#   absorb   — current is an AUDIT stage and expected is EARLIER    -> record the move, then proceed
#   (none)   — anything else                                        -> the EXISTING refusal, verbatim
# The refusal is reached by the SAME `_require_stage_correspondence` call as before, so an OUT-OF-ORDER
# sequence (a forward SKIP, a backward move from a non-audit stage, or an absent / numeric-legacy /
# unrecognized `current_stage`) still refuses and still names the stage — by construction, not by a
# re-implementation that could drift.
#
# The `absorb` move is the mode-(a) ABSORPTION arm, which the FSM did not model at all: LIFECYCLE
# §Stage 4 / §Stage 8 both sanction going BACK to fix an audit finding, and the fold found `task
# commit` (177/226) and `task test` (142/200) refused at exactly that point. It is bounded to a return
# FROM an audit stage — the seam where absorption is the sanctioned path — so a backward move from any
# other stage still refuses (fail-closed; this is a guard, not a free pointer).
#
# NOT an FSM engine (CHARTER non-goal #7): no new field, status, event type, verb or state machine —
# the successor relation is a READ of the ordered row SPEC-0027 already publishes, and the write goes
# through the SAME `_write_task_transition` the `stage` verb uses.
#
# The rows are transcribed from SPEC-0027 §Stage FSM per class. FILING is deliberately absent: no
# work-verb declares it as an expected stage (`cmd_task_file` runs no correspondence check — the card
# does not exist yet), and LIFECYCLE §Stage 2 sends an already-filed card straight to Stage 3, so
# including it would make the ordinary Analysis->Plan move read as a SKIP.
LIFECYCLE_STAGE_POINTER_FSM = {
    "standard": ("Analysis", "Plan", "Audit-pre", "Execution", "Tests", "Commit", "Audit-post", "Closure"),
    "hygiene":  ("Analysis", "Execution", "Tests", "Commit", "Closure"),
}
ABSORPTION_RETURN_STAGES = ("Audit-pre", "Audit-post")   # the two seams a sanctioned return departs FROM


def stage_pointer_row(task: dict) -> tuple:
    """The ordered stage row this task's `class` selects (SPEC-0027 §Stage FSM per class). `hygiene`
    takes the fast-path row; every other class takes the standard row — matching the spec's own table,
    where a future class adds a row rather than a branch."""
    return LIFECYCLE_STAGE_POINTER_FSM["hygiene" if (task or {}).get("class") == "hygiene"
                                       else "standard"]


def stage_pointer_move(task: dict, expected_stage: str) -> "str | None":
    """PURE classifier — the move `expected_stage` would be FROM this task's recorded `current_stage`.

    Returns 'explicit' | 'advance' | 'absorb', or **None** when the move is not admitted (the caller
    then falls through to the existing strict refusal). Total and side-effect-free: an absent, numeric
    -legacy or unrecognized `current_stage` is not in the row, so it yields None — the T-0288
    remediation leg is preserved exactly."""
    current = (task or {}).get("current_stage")
    if current == expected_stage:
        return "explicit"
    row = stage_pointer_row(task)
    if current not in row or expected_stage not in row:
        return None
    i, j = row.index(current), row.index(expected_stage)
    if j == i + 1:
        return "advance"                                     # the one-step-behind arm
    if j < i and current in ABSORPTION_RETURN_STAGES:
        return "absorb"                                      # the mode-(a) absorption return
    return None


def advance_stage_pointer(task: dict, expected_stage: str, *, task_path, yaml_mod, verb: str,
                          _write_task_transition, _append_event, _readiness=None) -> "str | None":
    """Move the pointer to `expected_stage` when `stage_pointer_move` admits the move; otherwise do
    NOTHING and return None, leaving the caller's `_require_stage_correspondence` to refuse unchanged.

    Call it IMMEDIATELY BEFORE that guard. It is a no-op on the 'explicit' move (the pointer is already
    there), so a session that did run `stage <NAME>` behaves exactly as today.

    `_readiness` is the caller's stage-entry precondition for the edge being crossed, run BEFORE the
    write so a refusal leaves NO half-entry — the ordering `cmd_stage` fixes for the same reason
    (T-10141 / E-0043: a task may not LEAVE Analysis without its finalized analysis record). It is
    invoked only on a move that actually crosses the edge, never on 'explicit'.

    Records through the SAME `_write_task_transition` the `stage` verb uses (one writer, CHARTER §P5)
    and emits `stage_entered` — the same event, carrying `from_stage` + `mode` + `advanced_by` so the
    journal distinguishes a pointer move from an explicit stage entry. It deliberately does NOT carry
    `delivered` / `delivered_patterns` / `delivered_verbs`: this path delivers no BUNDLE, and an empty
    list would claim a delivery that did not happen. `stage <NAME>` remains the bundle deliverer."""
    move = stage_pointer_move(task, expected_stage)
    if move is None or move == "explicit":
        return None if move is None else move
    if _readiness is not None:
        _readiness()
    from_stage = (task or {}).get("current_stage")
    _write_task_transition(yaml_mod, task_path, task, expected_stage)
    _append_event("stage_entered", (task or {}).get("id"),
                  {"stage": expected_stage, "from_stage": from_stage, "mode": move,
                   "advanced_by": verb})
    print(f"stage pointer: {from_stage} -> {expected_stage} "
          f"({'advanced' if move == 'advance' else 'absorption return'} by `{verb}`; "
          f"run `yitc-v2 stage {expected_stage} --task {(task or {}).get('id')}` to read this "
          f"stage's bundle)")
    return move


def _stage_correspondence_status(current_stage, expected_stage: str) -> str:
    """STRICT stage-correspondence classifier (T-0288). Returns:
      'explicit'  — current_stage == expected_stage (the value written by `stage <NAME>`) → PROCEED;
      'mismatch'  — anything else: a recognized-but-wrong stage, OR an absent / numeric-legacy /
                    unrecognized value (an in-flight task with an old/absent current_stage) → REFUSE.
    Lazy-on-touch: an absent/old current_stage yields a DEFINED read (a remediation refusal), never a
    crash — the equality comparison tolerates None / int / any value without raising. NOT a read-receipt:
    it checks recorded STATE (current_stage), never 'did you read'. (The COMPAT 'legacy'/'tolerated'
    grace was retired with the legacy setters — T-0288.)"""
    return "explicit" if current_stage == expected_stage else "mismatch"


def _require_stage_correspondence(task: dict, tid: str, expected_stage: str, *,
                                  verb: "str | None" = None, extra_hint: str = "",
                                  _stage_correspondence_status, _resolve_session_ref,
                                  _emit_read_gate_refused, _die) -> str:
    """Mandatory entry-check for a TASK-BOUND work-verb (T-0288, strict). Dies with a remediation string
    unless current_stage == expected_stage; returns 'explicit' when it proceeds. Excludes Review-session /
    aspect-audits / decision + plan audits (the caller decides scope).

    On refusal it ALSO emits a `read_gate_refused` event with `kind="stage-correspondence"` (T-0596 — the
    SECOND locked refusal kind beside the read-check leg; SPEC-0025 / SPEC-0059 §enforcement-split), so a
    wrong-stage block is journal-visible like the read-check refusal, never a silent `_die`. The
    session_ref is captured GUARANTEED-non-None best-effort here (this guard runs EARLY — before
    `_require_reads` resolves it — and the fail-closed keying resolver `_die`s on a blank/absent contract):
    on a `SystemExit` from resolution the refusal row still journals under a best-effort id (the T-0561
    diagnostic-emit precedent — a refusal must not be lost from a pre-resolution / unidentified state).
    `verb` labels the emitted row's `verb` field (the offending work-verb); `extra_hint` is an optional
    caller-specific trailing sentence appended to the die message — it folds the T-0511 commit
    `work commit` hint without a duplicated inline stage-check at the call site (DRY)."""
    status = _stage_correspondence_status(task.get("current_stage"), expected_stage)
    if status != "explicit":
        actual = task.get("current_stage")
        try:
            sref = _resolve_session_ref()
        except SystemExit:
            sref = "session-unresolved"   # best-effort: the refusal row MUST journal (T-0561 precedent)
        _emit_read_gate_refused(
            verb or f"stage {expected_stage} work-verb",
            {"action": "stage-bound work-verb", "stage": expected_stage, "current_stage": actual},
            kind="stage-correspondence", reason="stage_mismatch", task_id=tid, session_ref=sref)
        msg = (f"{tid}: current_stage={actual!r} does not correspond to stage "
               f"{expected_stage!r} (stage-correspondence precondition, T-0288). Run `stage "
               f"{expected_stage}` first: `yitc-v2 stage {expected_stage} --task {tid}` — it records the "
               f"entered stage and delivers that stage's bundle.")
        if extra_hint:
            msg += " " + extra_hint
        _die(msg)
    return status


def _session_started_lower_bound(session_ref: str, *, _iter_events, events_path=None, events=None) -> "str | None":
    """The ts lower-bound for the `_require_reads` evidence window (SPEC-0042 §2 / SPEC-0050): the
    EARLIEST `session_started` ts of THIS session_ref in the current checkout's journal (the session
    ORIGIN), or **None** when none exists. FAIL-CLOSED (T-0538, external-audit M4 fix): a ref with NO
    session_started has NO valid evidence window — `_require_reads` REFUSES rather than crediting reads
    on an unbounded admit-any window. The prior `""` return was the fail-OPEN — `_fetched_spec_ids`
    excludes nothing against `""`, so a stale or shared `cli_invoked` under a reused/unanchored ref
    could credit a later commit/close. SPEC-0050 §2 anchors the window AT `session_started`; this aligns
    the code to that stated rule (no admit-any).

    EARLIEST, not latest (T-9243 — the worktree-hop same-session-credit fix). A single logical session
    emits MULTIPLE `session_started` rows under ONE stable `session_ref` (env:CLAUDE_CODE_SESSION_ID is
    stable across a provider session's worktrees): once per worktree, because per-worktree `session
    start` (SPEC-0049/T-0861) re-anchors in each checkout. Taking the LATEST advanced the window on every
    worktree hop, so a `graph query <SPEC>` fetched earlier in the SAME session (e.g. on `main` or a
    decompose worktree) fell BELOW a later worktree's anchor and was orphaned → a redundant re-fetch,
    contradicting SPEC-0050 §2 («an earlier same-session fetch should still credit»). The session ORIGIN
    (the earliest anchor) is the honest lower bound: it is stable across the session's worktree hops, so
    a same-ref fetch made at any point after the session began credits a later gate in any of its
    worktrees. This does NOT over-credit: the window stays per-`session_ref` (a DIFFERENT ref's
    session_started never lowers this ref's bound — the cross-session credit SPEC-0050 forbids, see
    `_require_reads` / the wrong-ref test), and reads BEFORE the origin are still excluded.

    POST-/compact ORTHOGONALITY (SPEC-0050 §4): a `/compact` does NOT emit `session_started`, so this
    origin lower-bound is independent of post-compact freshness. Post-compact freshness for the SEED
    receipt is now handled ORTHOGONALLY by epoch-scoping (T-10082, SPEC-0050 §8): the seed_read receipt
    is stamped with the CONTEXT EPOCH (`_session_epoch()`, the transcript's `compact_boundary` count)
    and `_require_seed_read` refuses a receipt from an earlier epoch — a receipt-STAMP compare, NOT a
    lower-bound shift, so this window origin stays the earliest-anchor value (they compose: the window
    still selects same-session receipts; the epoch check then rejects the pre-compact ones).

    A COMPLIANT worker emits `session_started` via `session start` (the dispatch contract forces a fresh
    per-worker session identifier), so this returns its ts and the window is honest — and the refusal is
    deadlock-free: the worker runs `session start` in THIS checkout → the anchor is local → the retry
    passes (mirroring the SPEC-0050 §3 model). Journal-only, the single `_iter_events` reader (P5). The
    sole caller is `_require_reads` (it guards the None).

    `events` (T-10115, additive): a PRE-MATERIALIZED snapshot of this journal (a list from a single
    `_iter_events` read). When given, iterate THAT instead of re-reading — so the anchor scan and the
    receipt scan a caller runs share ONE consistent snapshot (a concurrent in-place rewrite cannot
    interleave between them). `events=None` keeps the original single-reader behavior (P5)."""
    src = events if events is not None else _iter_events(events_path)
    lb = None
    for e in src:
        if e.get("type") != "session_started" or e.get("session_ref") != session_ref:
            continue
        ts = e.get("ts") or ""
        if lb is None or ts < lb:   # EARLIEST anchor (T-9243): the session ORIGIN, stable across worktree hops
            lb = ts
    return lb


def _fetched_spec_ids(session_ref: str, lower_bound: str, *, _iter_events, events_path=None, events=None,
                      realms_out=None, discarded_out=None) -> set:
    """The spec/node ids this session has FETCHED — the PASS-GRANTING evidence of the SPEC-0042 read-gate
    (the pilot's ONLY form): a `cli_invoked` event (the verb-routed `graph query` emitter, T-0260) of
    THIS session_ref with ts >= lower_bound, carrying data.node_id. `commanded_read` (Read-tool reads
    materialized from the transcript) is DELIBERATELY excluded — observed-only in the pilot (SPEC-0042
    §2: the file-path↔spec-id identity + materialization latency are unvalidated). Journal-only, read via
    the single `_iter_events` reader (P5); freshness is the existing pre-verb auto-sync (D-0049), not a
    sync here.

    `events` (T-10115, additive — mirror of `_session_started_lower_bound`): a pre-materialized snapshot
    to iterate instead of re-reading, so the anchor + receipt scans share ONE consistent read.

    `realms_out` (T-11077 / X-0865, additive OUT-param): when a dict is passed it is filled
    `node_id -> set(realm)` from each crediting receipt's `data.node_realm` (the T-11077 realm stamp —
    which CORPUS answered the fetch, "kernel" or "own"). A receipt with NO stamp contributes NO realm
    entry, so it makes no realm claim; `_require_reads` turns that absence into a fail-closed refusal
    under -C. Default None keeps every existing caller byte-identical — ONE reader over ONE journal,
    no parallel scan (P5).

    A DISCARDED FETCH DOES NOT CREDIT (T-11411 / kupiclub X-1068). A receipt the producer recorded
    `stdout_delivered: False` — the T-11010 discriminator, meaning fd 1 WAS the null device, i.e.
    `graph query <SPEC> >/dev/null 2>&1` — is SKIPPED here. The reported form is the natural one: a
    scripted loop over several spec ids is how a multi-spec gate gets satisfied, and suppressing its
    output is how the loop stays readable, so this is cheaper and likelier than the hand-written-
    analysis bypass T-9472/X-0079 already closed. This REVERSES the one clause T-11010 wrote
    (`stdout_delivered` was recorded but deliberately gate-inert — SPEC-0050 §4): the gate's boundary
    is that it checks DELIVERY, not comprehension, and a fetch whose bytes reached no reader is not
    delivery either. It is the SAME boundary, applied honestly — NOT a comprehension check, which the
    corpus refuses to build and this adds nothing toward.

    THE DIRECTION IS FAIL-SAFE, mirroring the producer's own. Only `is False` suppresses: an ABSENT
    key (every pre-T-11010 row, and `dispatch.py#_worker_seed_bootstrap_events`'s pre-recorded
    seed/help bootstrap receipts, which carry none), a None, or a non-bool all still CREDIT. So the
    unknown never accuses a real read, exactly as `_stdout_was_delivered` fails safe toward delivered.
    HONEST BOUND: this catches only what it can SEE was discarded — `> /tmp/x` is just as unread while
    looking delivered, and nothing here reaches it. Narrow is the whole claim.

    SCOPE: this reader ONLY — so `_require_reads` (contract gate) and `_require_help_read`
    (verb-inventory gate) both stop crediting a discarded fetch. `_seed_receipt_epochs` (the §8 seed
    floor) reads its own receipts and is deliberately UNTOUCHED — no report stands behind widening it
    (CHARTER §P1 F4).

    `discarded_out` (T-11576 / aiseller X-1101, additive OUT-param — the exact shape of `realms_out`):
    when a set is passed it is filled with the node_ids this scan SKIPPED for `stdout_delivered is False`.
    It REPORTS the suppression the clause above performs; it grants nothing and moves no verdict (an id
    may appear in BOTH the returned set and here — one delivered receipt and one discarded receipt for
    the same id — and the RETURNED set still decides alone). Its whole purpose is that the two refusal
    sites can tell «no scan at all» from «a scan whose bytes reached the null device» and SAY which:
    X-1101 measured a reader that ran the refusal's own prescribed cure in a redirected shell and was
    refused identically, because the message named neither DELIVERY nor the flag. Default None keeps
    every existing caller byte-identical — still ONE reader over ONE journal, no second scan (P5)."""
    fetched = set()
    for e in (events if events is not None else _iter_events(events_path)):
        if e.get("type") != "cli_invoked" or e.get("session_ref") != session_ref:
            continue
        if (e.get("ts") or "") < lower_bound:
            continue
        data = e.get("data") or {}
        # T-11411 (X-1068): a fetch the producer recorded as reaching the NULL DEVICE grants no pass.
        # `is False` deliberately — absent/None/non-bool must never suppress a credit (see docstring).
        if data.get("stdout_delivered") is False:
            # T-11576: REPORT the suppression to the refusal sites (DIAGNOSTIC only — the `continue`
            # is unchanged, so this row still grants no pass).
            if discarded_out is not None:
                nid_d = data.get("node_id")
                if nid_d:
                    discarded_out.add(nid_d)
            continue
        nid = data.get("node_id")
        if nid:
            fetched.add(nid)
            if realms_out is not None and data.get("node_realm"):
                realms_out.setdefault(nid, set()).add(data["node_realm"])
    return fetched


def _seed_receipt_epochs(session_ref: str, lower_bound: str, *, _iter_events, events_path=None, events=None) -> list:
    """The CONTEXT EPOCHS of the in-window seed_read receipts (T-10082, SPEC-0050 §8) — the epoch-aware
    reader `_require_seed_read` uses in place of the boolean `SEED_READ_NODE_ID in _fetched_spec_ids`
    check. Returns one entry per in-window seed receipt (a `cli_invoked` of THIS session_ref with
    ts >= lower_bound whose data.node_id == SEED_READ_NODE_ID): `int(data.epoch)` when the receipt
    carries an integer epoch stamp, ELSE **0**.

    missing-epoch → 0 (NOT epoch-exempt): a receipt with no epoch stamp is a pre-change historical
    receipt (or a test seed) = the ZEROTH epoch. So it credits ONLY while the current epoch is still 0
    (a fresh session that never compacted); once a `/compact` advances the current epoch past 0, an
    epoch-less pre-compact receipt goes stale like any other lower-epoch receipt — closing the hole an
    exempt-always reading would leave (audit-pre f1). Same journal-only single-reader (`_iter_events`)
    discipline + in-window predicate as `_fetched_spec_ids` (P5).

    `events` (T-10115, additive — mirror of `_fetched_spec_ids`): a pre-materialized snapshot to iterate
    instead of re-reading, so the anchor + receipt scans share ONE consistent read."""
    out = []
    for e in (events if events is not None else _iter_events(events_path)):
        if e.get("type") != "cli_invoked" or e.get("session_ref") != session_ref:
            continue
        if (e.get("ts") or "") < lower_bound:
            continue
        data = e.get("data") or {}
        if data.get("node_id") != SEED_READ_NODE_ID:
            continue
        ep = data.get("epoch")
        out.append(ep if isinstance(ep, int) and not isinstance(ep, bool) else 0)
    return out


def fresh_seed_receipt(events_path, session_ref: str, current_epoch: int, *, _iter_events,
                       _iter_events_tail=None) -> bool:
    """Does `events_path` hold a FRESH seed_read receipt for `session_ref` (T-12116, SPEC-0050 §8)?

    "Fresh" is the credit rule `_require_seed_read` already applies to each candidate journal, and it is
    computed HERE from the SAME two readers rather than restated: an in-window `cli:seed` receipt (window
    origin = `_session_started_lower_bound`, the EARLIEST `session_started` of this ref in THIS journal)
    whose stamped context epoch is >= `current_epoch`. There is deliberately NO second notion of
    freshness — a divergence between this predicate and the gate would let a run skip work on a receipt
    the gate would then refuse to credit.

    The CALLER supplies which journal to ask about. Its one production caller asks about the MAIN
    checkout's journal, because a fresh receipt there is precisely what makes an in-worktree `session
    start` a RECEIPT-ONLY need (the seed content is already in the session's context; the gate already
    credits the main receipt from a worktree — see `_require_seed_read`'s candidate breadth). This
    predicate GRANTS NOTHING: it never stamps, credits or waives anything, and the seed floor is
    unchanged whichever way it answers. It only tells a caller whether a re-DELIVERY would be redundant.

    FAIL-CLOSED in the direction that preserves existing behaviour: a falsy path/ref, an unreadable
    journal, no anchor for this ref, no receipt, or a receipt from an EARLIER epoch all answer False —
    i.e. "not fresh, do the full thing". A stale-epoch or foreign-ref receipt therefore never shortcuts
    anything, which is the SPEC-0050-semantics-unchanged clause this predicate must preserve.

    TAIL-FIRST (T-12201). `_iter_events_tail` (optional, additive) routes the physical read through the
    SAME `_gate_snapshot` primitive both read-gates already use — tail probe first, and a would-be False
    computed from a genuinely BOUNDED snapshot is RE-DECIDED on the full read. The soundness argument is
    the one stated once at `_gate_pass_tail_first` and NOT restated here: a tail snapshot is a suffix of
    the full one, so lb_tail >= lb_full, and every receipt predicate is `ts >= lower_bound` — hence a
    tail CREDIT is provably also a full-read credit, while a tail REFUSAL may be false. So the answer is
    identical either way and the window carries NO correctness role; it removed a full fold of the main
    journal measured at 10.93 s of an 18.41 s fresh-worktree `session start` (T-12194's box-side term).
    `_iter_events_tail=None` (the default) keeps the full-read-only path byte-identical for every
    existing caller and test.

    The RETRY budget (`_gate_pass_tail_first`) is deliberately NOT pulled in: that loop exists to make a
    read-gate's REFUSAL survive a torn read, and this predicate has no refusal to phrase — its False is
    already the safe direction (do the full delivery), so three full passes with backoff would only add
    cost to the negative path it is meant to make cheap."""
    if not events_path or not session_ref:
        return False

    def _attempt(*, tail: bool) -> "tuple[bool, bool]":
        events, bounded = _gate_snapshot(events_path, tail=tail, _iter_events=_iter_events,
                                         _iter_events_tail=_iter_events_tail)
        lower = _session_started_lower_bound(session_ref, _iter_events=_iter_events, events=events)
        if lower is None:
            return False, bounded
        epochs = _seed_receipt_epochs(session_ref, lower, _iter_events=_iter_events, events=events)
        return (bool(epochs) and any(e >= current_epoch for e in epochs)), bounded

    try:
        if _iter_events_tail is not None:
            fresh, bounded = _attempt(tail=True)
            if fresh:
                return True            # sound by monotonicity — a tail credit is never a false credit
            if not bounded:
                return False           # that probe WAS the full read; there is nothing more to see
        return _attempt(tail=False)[0]
    except Exception:
        return False


def _require_reads(kind: str, ctx: dict, *, _plan_stage_bundle_specs, _is_consumer_build,
                   _stage_bundle_specs, _resolve_session_ref, _session_started_lower_bound,
                   _emit_read_gate_refused, _fetched_spec_ids, _die, REPO_ROOT, ENGINE_ROOT,
                   credited_out=None) -> None:
    """ONE shared must-read precondition (SPEC-0042 — the require-reads verb entry gate). A verb whose
    action is governed by stage-entry contracts REFUSES to act unless THIS session's journal shows the
    governing contract spec(s) were actually FETCHED (`graph query <SPEC>` → a `cli_invoked` node_id row).
    Reuses the existing binding-derived doc-set lens + the existing journal — NO new store/hook/flag/map
    (the D-0082 `_require_audit_pre_matches_plan` verb-precondition is the analog, P1 F1).

    kind=="stage" is the ONLY wired kind. CROSS-AXIS (T-0599 graduation, SPEC-0050 §1 / SPEC-0059): the
    doc-set is the verb's stage-entry bundle on the relevant axis — the task `stage-entry:<STAGE>` bundle
    (`_stage_bundle_specs`, default) OR the plan `plan-stage-entry:<STAGE>` bundle (`_plan_stage_bundle_specs`)
    when ctx["axis"]=="plan"; both are the SAME binding carrier as the floor-trigger-map (P5), just the
    task vs plan slice. `seed`/`action` are RESERVED API shape carrying NO code until a first-connection
    decision wires them — invoking them here is a programming error, not a runtime path.

    Graceful: an empty doc-set (a stage with no retrieved bundle, OR a degraded/unreadable corpus that
    `_stage_bundle_specs` reports as []) imposes NO obligation → return (mirrors `_governing_contract_for`
    returning an empty `specs` list — a gate helper must never crash the verb). Bypass: emergency MODE only (by-hand, the
    verb is not run) — no `--force`, no code path. The gate proves FETCH at the action moment, never
    comprehension, and never post-compact/restart freshness (the check is session-scoped, SPEC-0042 §4).

    The refusal's `graph query` command list is CORPUS-AWARE (T-10564 / X-0416): under a `-C` consumer
    it names the `{ENGINE_ROOT}/bin/yitc-v2 -C {REPO_ROOT} graph query <D>` form — the SAME shape the
    X-0093 foreign-corpus guard (`_guard_bare_invocation_foreign_corpus`) names, mirrored for
    discoverability. The corpus-BLIND `bin/yitc-v2 graph query <D>` it replaced could not SATISFY the
    gate that printed it: a fetch run from the engine cwd without `-C` records its `cli_invoked` receipt
    on the KERNEL journal while this gate reads the CONSUMER journal, so the identical list re-printed
    and the natural retry repeated the wrong-corpus fetch (the trend-finder loop — 3 duplicate calls per
    contract). Engine self-build (`_is_consumer_build()` False) keeps the bare form, byte-identical.

    `credited_out` (T-11885, additive OUT-param — the same shape `_fetched_spec_ids` already uses for
    `realms_out`/`discarded_out`): when a set is passed it is filled with the doc ids this call
    actually CREDITED, i.e. exactly the `_credited` decision already computed below. It exists so a
    caller that RECORDS the read in the journal records what was verified instead of a literal
    (`plan draft --finalize` emitted a hardcoded `reads_verified` — a false record in an append-only
    journal, CHARTER P7). It is REPORT-ONLY: nothing here reads it back, `missing`/`_credited` are
    untouched, and both refusal branches are unchanged — what the gate ADMITS does not move. The
    graceful-empty branch (no doc-set → no obligation) returns with it left EMPTY, which is the honest
    answer for a vacuous gate, not a bypass. Default None keeps every existing caller byte-identical."""
    if kind != "stage":
        raise ValueError(f"_require_reads: kind={kind!r} is RESERVED, not wired (pilot = stage only, "
                         "SPEC-0042 §6)")
    stage = ctx.get("stage")
    # T-0599 — kind=stage is CROSS-AXIS (SPEC-0050 §1, the SPEC-0059 graduation): the doc-set is the
    # verb's stage-entry bundle on the RELEVANT axis — the task `stage-entry:` bundle (default) via
    # `_stage_bundle_specs`, OR the plan `plan-stage-entry:` bundle via `_plan_stage_bundle_specs` when
    # ctx["axis"]=="plan". BOTH are the SAME binding-derived carrier (P5), just the task vs plan slice —
    # this is graduation-level wiring of the EXISTING kind=stage, NOT a new reserved kind (the seed/
    # action expansion stays T-0420's). Everything below (evidence window, refusal, emit) is axis-agnostic.
    axis = ctx.get("axis", "task")
    if axis not in ("task", "plan"):
        # FAIL-CLOSED (T-0599 audit-post F1): an unknown axis is a CALLER error — never silently
        # treat it as "task" (that would mask a mis-wired verb). ABSENT axis defaults to "task" (the
        # `.get` default above); a PRESENT-but-unknown value raises, mirroring the reserved-kind guard.
        raise ValueError(f"_require_reads: ctx['axis']={axis!r} is invalid (must be 'task' or 'plan'; "
                         "omit it for the 'task' default)")
    # T-11077 (X-0865) — `doc_realms` maps a doc id to the REALM ("kernel" | "own") whose corpus binding
    # put it in this doc-set, i.e. the realm a fetch receipt must MATCH to credit it. Populated ONLY on a
    # -C consumer build (the sole place a kernel/consumer id collision can exist — the positive
    # discriminator); EMPTY on the engine's own session, where own IS the kernel (SPEC-0092) and credit
    # therefore stays id-only, byte-identical to before this change.
    doc_realms: dict = {}
    if not stage:
        docs = []
    elif axis == "plan":
        # plan-axis own-only: `_plan_stage_bundle_specs` has no kernel-merge knob, so plan-stage
        # delivery AND enforcement both stay own-only — already symmetric, not the F-016 asymmetry (T-9269).
        # No kernel doc can enter this doc-set, so it is never realm-qualified (T-11077 leaves it as-is).
        docs = _plan_stage_bundle_specs(stage)
    else:
        # T-9269 / F-016 — the TASK-axis read-gate DOC-SET is kernel-MERGED under -C
        # (`include_kernel=_is_consumer_build()`), SYMMETRIC with the `include_kernel=True` delivery
        # surfaces (~2067 claim-moment / ~6572 `stage <NAME>`). So a `-C` consumer's stage read-check
        # ENFORCES the kernel stage-entry contract it is SHOWN — satisfiable via the engine-index
        # point-lookup (`graph query <SPEC>`), never vacuous. Engine self-build: `_is_consumer_build()`
        # is False → own-only → byte-unchanged. Amends SPEC-0031 §"DELIVERY + DOC-SET vs BUILD".
        # T-11077: under -C ask for the per-doc REALM too (`with_realms`), so a kernel contract in this
        # bundle requires the KERNEL fetch receipt. On the engine's own session the knob is False and the
        # plain list is returned — no realm qualification, no behaviour change.
        if _is_consumer_build():
            docs, doc_realms = _stage_bundle_specs(stage, include_kernel=True, with_realms=True)
        else:
            docs = _stage_bundle_specs(stage, include_kernel=False)
    if not docs:
        return
    sref = _resolve_session_ref()
    lower_bound = _session_started_lower_bound(sref)
    if lower_bound is None:
        # FAIL-CLOSED (T-0538, external-audit M4): no `session_started` anchor for THIS session in
        # this checkout → NO valid evidence window. REFUSE rather than credit reads on an unbounded
        # admit-any window — a stale/shared `cli_invoked` under a reused/unanchored ref must never
        # credit a later commit/close. Deadlock-free like SPEC-0050 §3: `session start` runs IN this
        # checkout and writes `session_started` into its local journal, so the retry then anchors.
        verb = ctx.get("verb", "this verb")
        _emit_read_gate_refused(verb, ctx, kind="read-check", reason="no_session_started_anchor",
                                session_ref=sref)
        _die("\n".join([
            f"{verb}: no session_started anchor for this session in this checkout — refusing (fail-closed).",
            "The read-gate credits governing-contract reads ONLY within a window anchored by THIS",
            "session's own session_started (SPEC-0050 §2). Emit the anchor in this checkout, then re-invoke:",
            "  bin/yitc-v2 session start",
            "(session start writes session_started into this checkout's journal; the retry then evaluates "
            "your contract reads)",
        ]))
    # T-11077 (X-0865) — THE CREDIT RULE, realm-aware. `receipt_realms` maps each fetched id to the
    # realm(s) its receipts recorded. A doc that carries a REQUIRED realm (consumer build only) is
    # credited ONLY by a receipt whose realm equals it; a doc with no required realm (the engine's own
    # session, or the plan axis) is credited id-only exactly as before. An UNSTAMPED receipt records no
    # realm, so under -C it credits NOTHING — fail-closed with no own-vs-kernel exception, and
    # self-healing (re-issuing the fetch produces a stamped receipt). This is the half X-0865 was missing:
    # T-10581 kernel-pinned the gate TEMPLATE resolution; the READ CREDIT stayed keyed on the bare id, so
    # a -C consumer's unrelated same-id spec satisfied a kernel contract silently.
    receipt_realms: dict = {}
    # T-11576: `discarded` reports which ids had an in-window receipt SKIPPED for stdout_delivered
    # False. It takes no part in `_credited` below — it only lets the refusal name the real
    # precondition (a scan WAS run, its bytes were not delivered) instead of "not fetched".
    discarded: set = set()
    fetched = _fetched_spec_ids(sref, lower_bound, realms_out=receipt_realms, discarded_out=discarded)
    def _credited(d):
        if d not in fetched:
            return False
        want = doc_realms.get(d)
        return True if want is None else want in receipt_realms.get(d, set())
    missing = [d for d in docs if not _credited(d)]
    # T-11885 — hand the CREDITED set back (report-only; the same `_credited` decision `missing` is
    # computed from, so no second scan and no divergence possible). Filled before the success return
    # so a caller that journals the read records what was verified, never a literal.
    if credited_out is not None:
        credited_out.update(d for d in docs if _credited(d))
    if not missing:
        # AC3 — a SATISFIED gate names which realm satisfied it, so a future mis-credit is not silent
        # (report-only, stderr, never the verb's stdout; only when the realm was actually qualified).
        if doc_realms:
            named = ", ".join(f"{d} ({doc_realms.get(d, 'unqualified')})" for d in docs)
            sys.stderr.write(f"yitc-v2: read-check satisfied for {ctx.get('verb', 'this verb')} — "
                             f"credited {named}.\n")
        return
    verb = ctx.get("verb", "this verb")
    action = ctx.get("action", "this action")
    # Refusal contract (SPEC-0042 §4 + the T-0418 amend re-check refinement): the per-missing-doc
    # `graph query` commands + the fetch-not-comprehension boundary line are PRIMARY; the RE-CHECK
    # step is a SECONDARY sentence (it names a judgement re-check, NOT a canned verbatim retry — a
    # mechanical fetch→retry double-tap would suppress the re-think moment the gate exists for).
    lines = [f"{verb}: required governing contract(s) not fetched this session — refusing.",
             "Fetch each missing contract (one command per doc):"]
    # T-10564 (X-0416) — CORPUS-AWARE command form. A printed command that cannot SATISFY the gate that
    # printed it is a self-defeating instruction: under `-C` the receipt this gate reads lives on the
    # CONSUMER journal, so the bare form (run from the engine cwd, the natural reading of a relative
    # `bin/yitc-v2`) records on the KERNEL journal and never credits. Name the `-C` form the X-0093
    # refusal already names. Engine self-build → the bare form, byte-identical.
    consumer = _is_consumer_build()
    if consumer:
        # T-11077 (X-0865): a KERNEL-realm doc names the `--kernel` form. Under -C a bare
        # `graph query <D>` resolves consumer-own-first (SPEC-0092), so for a kernel contract the bare
        # command printed here could not satisfy the gate that printed it — the same self-defeating
        # instruction X-0416 fixed on the -C axis, now fixed on the REALM axis.
        # The printed line stays PURE + copy-runnable (a trailing inline comment would break a caller
        # that runs it verbatim — the X-0416 loop-closing contract); the explanation is its own line.
        lines += [f"  {ENGINE_ROOT}/bin/yitc-v2 -C {REPO_ROOT} graph query "
                  f"{'--kernel ' if doc_realms.get(d) == 'kernel' else ''}{d}"
                  for d in missing]
        if any(doc_realms.get(d) == "kernel" for d in missing):
            lines.append("(the `--kernel` ones are KERNEL contracts: under -C the BARE form resolves "
                         "YOUR OWN spec at that id (SPEC-0092), which does NOT credit this gate — T-11077.)")
        lines.append(f"(-C targets THIS corpus: {REPO_ROOT}. A fetch run from inside the engine "
                     f"checkout WITHOUT -C records its receipt on the KERNEL journal and will NOT "
                     f"credit this gate — X-0416.)")
    else:
        lines += [f"  bin/yitc-v2 graph query {d}" for d in missing]
        # T-11888: name the checkout whose journal this gate READ. The receipt lives on the journal of
        # the checkout the fetch RAN in, and a session crosses between main and its worktrees many
        # times a day — so a reader who fetched elsewhere is otherwise sent to re-read what they
        # already read, with no hint why it did not count. Own line, never appended to a command line:
        # the printed commands stay PURE + copy-runnable (the X-0416 loop-closing contract).
        lines.append(f"(this gate read the journal of THIS checkout: {REPO_ROOT}. A fetch run in a "
                     f"DIFFERENT checkout records its receipt on THAT journal and does not credit "
                     f"here — run the command(s) above from this checkout, T-11888.)")
    lines.append("the gate checks delivery (fetch), not comprehension")
    # T-11576 (aiseller X-1101) — DISCRIMINATE, so the refusal's own cure cannot loop. A doc whose only
    # in-window receipt was recorded `stdout_delivered: False` was ALREADY fetched this session; what is
    # missing is DELIVERY, not the fetch. Repeating "not fetched this session" sends the reader to re-run
    # the identical redirected command and be refused identically. NOTHING about what the gate ADMITS
    # changes here — `missing` is computed above from `_credited`, which never reads `discarded`.
    undelivered = [d for d in missing if d in discarded]
    if undelivered:
        lines.append(f"NOTE — {', '.join(undelivered)}: a fetch WAS recorded this session, but its "
                     "producer recorded stdout_delivered=false — the output went to the null device "
                     "(e.g. `>/dev/null`), and a fetch no reader received grants no pass (T-11411). "
                     "Re-run the command(s) above with stdout ATTACHED; do not redirect or discard it.")
    lines.append(f"After reading, verify your prepared {action} against the contract — does it conform? "
                 "Fix any divergence, then re-invoke the verb (re-compose it yourself; do NOT copy a "
                 "canned retry).")
    # T-11077: carry the required realm per missing doc so a realm miss is greppable in the journal,
    # not merely visible in the printed refusal (`{}` on the engine's own session / the plan axis).
    _emit_read_gate_refused(verb, ctx, kind="read-check", reason="contracts_unfetched",
                            missing=missing, session_ref=sref,
                            missing_realms={d: doc_realms[d] for d in missing if d in doc_realms})
    _die("\n".join(lines))


# ── T-10396: the tail-first read discipline shared by both receipt gates ────────────────────────────
# The read-gates' evidence scans (`_session_started_lower_bound` + `_fetched_spec_ids` /
# `_seed_receipt_epochs`) each parsed the WHOLE journal — 0.89s per scan on the 90MB main journal, paid
# per candidate journal, per retry attempt. Receipts are session/epoch-scoped, so the PHYSICAL read can
# be bounded to the journal tail (the T-10387 primitive, reused via the host's `_iter_events_tail`).
#
# The two helpers below are the ONE home for that discipline — both gates route through them, so the
# soundness argument lives in a single place rather than being restated per gate.

def _gate_snapshot(ev_path, *, tail: bool, _iter_events, _iter_events_tail):
    """One candidate journal → `(events, bounded)`. `bounded` is True only when the read was genuinely
    NARROWED to a tail (so a refusal computed from it is not yet final). Falls back to the full reader
    whenever the tail reader is absent (not injected — the pre-T-10396 behavior every existing test
    relies on) or not requested."""
    if tail and _iter_events_tail is not None:
        return _iter_events_tail(events_path=ev_path)
    return list(_iter_events(events_path=ev_path)), False


def _gate_pass_tail_first(attempt, *, _sleep, tail_enabled: bool) -> "tuple[bool, object]":
    """Run a gate's evaluation TAIL-FIRST, then FULL — with EXACTLY the semantics of the original
    full-read-only retry loop. `attempt(tail=…)` returns `(credited, payload, bounded)`; this returns
    `(credited, payload)` taken from the pass that actually DECIDED. The `payload` is whatever the gate
    needs to phrase its refusal (the help gate: `any_anchor`; the seed gate: `(any_anchor, epochs)`) —
    and because a refusal is only ever decided on a FULL pass, that payload is always computed from
    complete evidence, so the distinct refusal REASONS and their message values (e.g. the stale-epoch
    line's `max(epochs)`) are chosen exactly as before.

    WHY A TAIL CREDIT MAY BE TRUSTED (the soundness argument, stated once for both gates). A tail
    snapshot is a SUFFIX of the full one, so the earliest anchor it can find is >= the true earliest
    (it may MISS an older anchor; it can never INVENT one) — lb_tail >= lb_full. Every receipt predicate
    is `ts >= lower_bound`, so a LATER lower-bound only ever EXCLUDES receipts: it can turn a PASS into a
    REFUSE, never a REFUSE into a PASS. Hence a tail-window CREDIT is provably also a credit under the
    full read (SOUND — never a false credit), while a tail-window REFUSAL may be a FALSE refusal (the
    anchor or receipt lies below the cutoff — a long-lived session).

    So: try the cheap tail pass; on a credit, return (the hot path — a compliant session, anchored and
    receipted minutes ago, never touches the full file). On a would-be refusal, fall through to the FULL
    pass and let IT decide. A refusal is therefore ALWAYS backed by a complete read of the history — the
    fail-closed bound, and the reason the window size carries NO correctness role.

    The BOUNDED RETRY (T-10115 — torn-read recovery from a concurrent in-place rewrite) is preserved
    EXACTLY, and a would-be refusal is ALWAYS decided by it. The windowing is an optimization; the retry
    budget is a correctness guarantee (its job is to re-read a file whose first read may have been
    truncated mid-rewrite), and the two must stay independent: short-circuiting the loop because "the
    tail already read everything" would make a transient torn read FINAL, silently undoing T-10115.

    RETRY ACCOUNTING — the budget counts FULL reads. A tail probe that was NOT narrowed (a short journal,
    no provable boundary, a read fault) IS a full read: `_iter_events_tail` DELEGATES to the full reader
    in that case. So it CONSUMES the first attempt of the budget rather than adding a 4th read on top of
    it — the refusal path performs exactly `_READ_GATE_RETRY_ATTEMPTS` full reads, before and after this
    change alike. A probe that WAS narrowed read only the tail bytes, so it consumes nothing and the full
    budget follows it intact."""
    payload = None
    done = 0
    if tail_enabled:
        credited, payload, bounded = attempt(tail=True)
        if credited:
            return True, payload          # sound by monotonicity — a tail credit is never a false credit
        if not bounded:
            done = 1                      # that probe WAS a full read — it consumed attempt #1
    for attempt_i in range(done, _READ_GATE_RETRY_ATTEMPTS):
        if attempt_i > 0:
            _sleep(_READ_GATE_RETRY_BACKOFF)   # between attempts (never before the first, nor after the last)
        credited, payload, _bounded = attempt(tail=False)
        if credited:
            return True, payload
    return False, payload


def _require_help_read(*, verb: str, _resolve_session_ref, _session_started_lower_bound,
                       _fetched_spec_ids, _emit_read_gate_refused, _die, candidate_events_paths,
                       _iter_events, _sleep=time.sleep, _iter_events_tail=None,
                       _cli_form="bin/yitc-v2") -> None:
    """The `--help` verb-inventory read-gate (T-9786 / X-0158). A session-ENTRY work-verb (`worktree
    new` / `task file` / `land` — whichever fires first enforces) REFUSES to act unless THIS session
    scanned the current verb inventory this session — i.e. the journal shows a `bin/yitc-v2 --help`
    fetch-receipt (a `cli_invoked` row whose data.node_id == HELP_INVENTORY_NODE_ID, the emit analog of
    `graph query <SPEC>`'s node_id). REUSES the SPEC-0042 read-gate machinery VERBATIM — the SAME
    evidence window (`_session_started_lower_bound` + `_fetched_spec_ids`) and the SAME
    `read_gate_refused` emit — NO new store/hook/flag/map (P1 F1). It is `_require_reads` with a
    fixed one-item "doc-set" (the help sentinel) instead of a stage-derived bundle.

    Closes X-0158: AGENTS Phase-1 SAYS «scan --help at session start» but nothing ENFORCED it, so a
    session could act on a STALE verb inventory (incident 2026-07-02: a Controller offered raw deploy.sh
    because the governed `deploy` VERB was not in its working set — adoption-gap class #17). The AGENTS
    Phase-1 MANDATORY wording covers the advice-before-any-verb case a verb-gate structurally cannot;
    THIS gate covers the do-real-work case.

    MULTI-JOURNAL evidence (T-10013, breadth generalized T-10115): the receipt may live in either the
    current checkout's journal OR the main-checkout journal — `land --task/--branch` runs FROM main but
    re-execs the engine `-C <worktree>` (T-0835) so at the child's gate the current journal is the
    WORKTREE's while the scan landed in MAIN; symmetrically a worker running a verb from a worktree may
    have its receipt only in MAIN (the launcher records it there — SPEC-0050 §8 co-producer). So the
    caller supplies a LIST of `candidate_events_paths` = [current checkout, main checkout] for EVERY
    governed verb (T-10115 generalized the prior land-only carve-out — the boundary was incident scope,
    not a principled land-only limit). Each candidate is tested as its OWN anchored window (per-journal
    `session_started` lower-bound + per-journal fetched set) — NEVER a raw union across journals (a union
    would let one journal's `session_started` anchor another journal's receipt, over-crediting a
    stale/different-checkout receipt — external-consult decisions/land-audit-gate-tangles-audit-adhoc.yaml,
    T1). PASS if ANY candidate credits the scan.

    CONSISTENT READ + BOUNDED RETRY (T-10115). Per candidate the anchor scan and the receipt scan read a
    SINGLE materialized snapshot (`list(_iter_events)`), so a concurrent in-place reconcile rewrite of
    events.jsonl (worktree.py `write_text`, NOT atomic) cannot interleave BETWEEN the two scans and
    torn-miss a durably-present receipt. And a torn read WITHIN one snapshot is survived by re-reading a
    bounded number of times before refusing (`_READ_GATE_RETRY_ATTEMPTS` × `_READ_GATE_RETRY_BACKOFF`) —
    return-on-first-credit keeps the pass path single-read; the bounded latency lands only on the refusal
    path. A GENUINE miss still refuses after the attempts (retry never waves through a real absence).

    FAIL-CLOSED, byte-consistent with `_require_reads` (audit-pre finding, 2026-07-02): a session with no
    `session_started` for this ref in ANY candidate journal (no valid evidence window anywhere) is REFUSED
    with a session-start remediation, NOT waved through — a fail-OPEN would be a bypass hole (an unanchored
    session runs the gated verb without the receipt) AND Principle-7 dissonance with the established
    read-gate. Deadlock-free the SAME way (`session start` writes the anchor into this checkout's
    journal, so the retry then evaluates the receipt).

    TAIL-FIRST READ (T-10396). Each candidate snapshot used to be a FULL parse of the journal (~90MB /
    200k lines on the main journal — 0.89s per scan, paid per candidate, per attempt). When the host
    injects `_iter_events_tail`, the FAST path reads a TAIL-WINDOWED snapshot instead, and a would-be
    refusal is RE-DECIDED on the full snapshot before it is emitted (`_gate_pass_tail_first`, which see
    for the monotonicity proof: a tail credit is provably a full credit, so only the REFUSAL path needs
    the full read). Semantics are unchanged — an absent receipt still refuses, having paid exactly the
    full read it always paid. `_iter_events_tail=None` (the default) keeps the original full-read-only
    behavior, so every existing test that injects only `_iter_events` is honored byte-identically.

    REMEDY NAMES THE CARRY, IN THE FORM THIS SESSION CAN RUN (T-11409 / X-1069). The receipt is
    SESSION-TIED — credited only inside a window anchored by THIS session's own `session_started` — so
    the commonest way to earn this refusal is scanning `--help` WITHOUT the `YITC_SESSION_REF` carry
    (the receipt then lands under a different/unresolvable ref). Both refusal branches therefore print
    the carry explicitly with the resolved ref substituted, and render the command via the injected
    `_cli_form` (engine self `bin/yitc-v2`; a `-C` consumer `<engine>/bin/yitc-v2 -C <repo>`, which has
    no local `bin/yitc-v2` and would otherwise be told to run a command it does not have). `_cli_form`
    defaults to the engine-self form, so every existing caller and test is byte-unchanged. Message text
    ONLY — the reason codes, the `read_gate_refused` emit and the credit semantics are untouched.

    THE REFUSAL DISCRIMINATES A DISCARDED SCAN (T-11576 / aiseller X-1101). Since T-11411 a receipt whose
    producer recorded `stdout_delivered: False` grants no pass, but the refusal named neither delivery nor
    the flag: it named the session-ref carry as the usual explanation, so a reader in a redirected shell
    ran the prescribed cure, wrote another undelivered receipt, and earned the IDENTICAL refusal. The
    evaluation now carries the reader's `discarded_out` observation out in its payload and the
    `help_inventory_unfetched` refusal branches on it — an in-window-but-undelivered receipt gets text
    naming stdout delivery as the unmet precondition and the remedy (re-run with stdout ATTACHED); NO
    receipt at all keeps the original wording verbatim. DIAGNOSTIC ONLY: both branches are reached only
    after the credit test has already failed, the reason code and the emit are unchanged, and nothing
    here can admit a verb the gate previously refused."""
    sref = _resolve_session_ref()
    ctx = {"action": "session-entry work-verb", "stage": None}

    def _attempt(*, tail: bool = False) -> "tuple[bool, bool, bool]":
        """ONE consistent evaluation pass over the candidates. Returns (credited, any_anchor, bounded).
        Each candidate is read into a SINGLE snapshot shared by the anchor + receipt scans (T-10115);
        `bounded` is True iff SOME candidate's snapshot was a genuinely narrowed tail (so a refusal here
        is not yet final — the full read may still credit)."""
        anchored = False
        narrowed = False
        discarded = False      # T-11576: did SOME candidate hold an in-window help receipt skipped for
                               # stdout_delivered False? Diagnostic only — it never credits (below).
        for ev_path in candidate_events_paths:
            snapshot, was_bounded = _gate_snapshot(ev_path, tail=tail, _iter_events=_iter_events,
                                                   _iter_events_tail=_iter_events_tail)
            narrowed = narrowed or was_bounded
            lower_bound = _session_started_lower_bound(sref, events=snapshot)
            if lower_bound is None:
                continue   # no anchor in THIS journal → not a valid window here (do not credit across journals)
            anchored = True
            skipped: set = set()
            if HELP_INVENTORY_NODE_ID in _fetched_spec_ids(sref, lower_bound, events=snapshot,
                                                           discarded_out=skipped):
                return True, (anchored, discarded), narrowed
            discarded = discarded or (HELP_INVENTORY_NODE_ID in skipped)
        return False, (anchored, discarded), narrowed

    # T-11576: the payload is the DECIDING pass's `(any_anchor, help_discarded)` — a TUPLE payload, the
    # shape the seed gate already uses; `_gate_pass_tail_first` is payload-opaque and only ever decides a
    # REFUSAL on a FULL read, so the discarded observation phrasing the refusal is complete evidence.
    credited, payload = _gate_pass_tail_first(_attempt, _sleep=_sleep,
                                              tail_enabled=_iter_events_tail is not None)
    any_anchor, help_discarded = payload if payload is not None else (False, False)
    if credited:
        return
    if not any_anchor:
        # FAIL-CLOSED (mirrors `_require_reads`): no anchor in ANY candidate → no valid evidence window → refuse.
        _emit_read_gate_refused(verb, ctx, kind="read-check", reason="no_session_started_anchor",
                                session_ref=sref)
        _die("\n".join([
            f"{verb}: no session_started anchor for this session in any candidate journal — refusing (fail-closed).",
            "The verb-inventory read-gate credits the --help scan ONLY within a window anchored by THIS",
            "session's own session_started (SPEC-0050 §2). Emit the anchor in this checkout, then re-invoke",
            "BOTH carrying your session ref — the receipt is session-tied, so without the carry the scan",
            "is recorded under a different ref and is not credited:",
            f"  YITC_SESSION_REF={sref} {_cli_form} session start",
            f"  YITC_SESSION_REF={sref} {_cli_form} --help",
        ]))
    _emit_read_gate_refused(verb, ctx, kind="read-check", reason="help_inventory_unfetched",
                            session_ref=sref)
    if help_discarded:
        # T-11576 (aiseller X-1101) — the DISCRIMINATING branch. The scan DID happen this session, under
        # this very ref; its producer recorded `stdout_delivered: False`, so `_fetched_spec_ids` skipped
        # it (T-11411) and it grants no pass. The generic text above names the session-ref carry as the
        # usual explanation, which is WRONG here — the carry was right and the DELIVERY was not — so the
        # reader re-runs the same redirected command and earns the identical refusal (measured: a second
        # refused verb call plus a journal investigation before the real precondition was found). Say what
        # is actually unmet. The gate still REFUSES: this branch is reached only after the credit test
        # already failed, and it changes no verdict.
        _die("\n".join([
            f"{verb}: the verb-inventory scan was recorded but NOT DELIVERED this session — refusing "
            "(T-11576 / T-11411).",
            "A `--help` fetch-receipt for THIS session ref exists, but its producer recorded",
            "stdout_delivered=false: fd 1 was the null device (e.g. `--help >/dev/null 2>&1`), so no",
            "reader received the inventory and the scan grants no pass. The carry is NOT the problem —",
            "re-running it redirected will be refused identically.",
            "Re-run the scan with stdout ATTACHED (do not redirect or discard it), then re-invoke:",
            f"  YITC_SESSION_REF={sref} {_cli_form} --help",
            "(the gate checks DELIVERY of the scan, not comprehension — a fetch whose bytes reached no",
            "reader is not delivery either. This session IS anchored: do NOT re-run `session start`.)",
        ]))
    _die("\n".join([
        f"{verb}: the verb inventory was not scanned this session — refusing (X-0158 / T-9786).",
        "Scan the current verb inventory CARRYING your session ref, then re-invoke:",
        f"  YITC_SESSION_REF={sref} {_cli_form} --help",
        "(--help emits a session fetch-receipt; the gate checks the scan happened, not comprehension)",
        "The receipt is SESSION-TIED: a scan run WITHOUT that carry is recorded under a different ref",
        "and is not credited here — so an ALREADY-RUN bare scan is the usual explanation. This session",
        "IS anchored, so re-scanning with the carry is the whole cure — do NOT re-run `session start`.",
    ]))


def _require_seed_read(*, verb: str, _resolve_session_ref, _session_started_lower_bound,
                       _seed_receipt_epochs, _session_epoch, _emit_read_gate_refused, _die,
                       candidate_events_paths, _iter_events, _sleep=time.sleep,
                       _try_resolve_session_ref_with_source=None, _iter_events_tail=None) -> None:
    """The audience-seed read-gate (T-10081, SPEC-0042/0050 machinery reused). A governed/mutating verb
    REFUSES to act unless THIS session recorded a seed_read receipt FOR THE CURRENT CONTEXT EPOCH — the
    journal shows a `cli_invoked` row whose data.node_id == SEED_READ_NODE_ID (emitted by `session start`
    after it delivers the audience seed; the emit analog of the --help fetch-receipt), stamped with an
    epoch >= the current epoch. MIRRORS `_require_help_read` — same per-journal anchored evidence window
    (`_session_started_lower_bound`), same `read_gate_refused` emit, same multi-journal
    `candidate_events_paths` OR (NO raw union) — a fixed one-item sentinel doc-set (the seed sentinel).
    It is the BROAD-coverage anti-Forgetting floor: the central dispatch chokepoint (bin/yitc-v2 main)
    calls it for every governed/mutating verb, bypassing ONLY the small semantic allowlist (SPEC-0050 §8).

    EPOCH-SCOPING (T-10082, SPEC-0050 §8). A `/compact` evicts the seed from context but emits NO
    `session_started`, so a session-scoped receipt would keep crediting after the compaction — the
    receipt LIES (auditor finding #2). The CONTEXT EPOCH (`_session_epoch()`, the transcript's
    `compact_boundary` count) fixes this: a receipt credits only when its stamped epoch >= the current
    epoch. A pre-compact receipt (lower epoch) no longer credits, forcing a post-compact re-read +
    `session start` refresh (the sole producer re-stamps the fresh epoch; safe by EARLIEST-anchor — the
    window origin is unchanged). A receipt with NO epoch stamp normalizes to 0 (`_seed_receipt_epochs`),
    so pre-change historical receipts + test seeds credit while current_epoch==0 but go stale once a
    compact advances it — NOT exempt-always (audit-pre f1). Three refusal reasons, DISTINCT so the
    failure says exactly what is missing: `no_session_started_anchor`, `seed_read_unfetched` (no receipt
    at all), `seed_read_stale_epoch` (a receipt exists but predates the current epoch).

    CANDIDATE BREADTH + CONSISTENT READ (T-10115, mirror of `_require_help_read`). The candidate set is
    [current checkout, main checkout] for EVERY governed verb (the prior land-only carve-out was incident
    scope, not a principled limit) — so a worker's receipt recorded only on MAIN (the launcher, SPEC-0050
    §8 co-producer) credits a non-land verb it runs from a worktree, removing the per-worktree `session
    start` for THIS gate. Per candidate the anchor + receipt scans read a SINGLE materialized snapshot,
    and a would-be refusal is re-read a bounded number of times (`_READ_GATE_RETRY_ATTEMPTS`) before it is
    final — so a concurrent in-place reconcile rewrite cannot torn-miss a durably-present receipt. A
    genuine miss still refuses after the attempts.

    FAIL-CLOSED, byte-consistent with `_require_help_read`: a session with no `session_started` for this
    ref in ANY candidate journal (no valid evidence window anywhere) is REFUSED with a session-start
    remediation, NOT waved through (a fail-OPEN would be a bypass hole). Deadlock-free the SAME way
    (`session start` writes the anchor AND emits the epoch-stamped receipt into this checkout's journal,
    so the retry then credits). Worker-before-worktree ordering is T-10083 — OUT of this card.

    BOUNDED READ-TOLERANCE EXCEPTION (T-10353). Rule home: SPEC-0050 §8a — the ACTIVE head of the
    must-read/seed-floor lineage (SPEC-0042 → SPEC-0049 → SPEC-0050); the superseded ancestors are frozen
    history and carry no pointer to it. Owner-decided + externally consulted
    (`decisions/seedgate-read-tolerance-audit-adhoc.yaml`, verdict
    extend-with-bounds). EXACTLY the three verbs in `_TOLERANT_VERBS` below — `debt`, `followup list`
    and `profile` —
    TOLERATE a stale/unbacked/absent session ref instead of refusing. They are PURE DURABLE-STATE FOLDS
    (`cmd_debt` / `cmd_followup_list` / `cmd_profile`: no worktree, no mutation, no event), i.e. read-only
    observers of state the journal already owns, so waving them through grants no write the strict floor
    was guarding. This is an EXPLICIT BOUNDED EXCEPTION, never a general weakening of the SEED-READ floor:

      MEMBER 3 — `profile` (T-12165). SPEC-0198 declares the verb READ-ONLY in exactly the terms this
        set's membership criterion asks for: "no write, no event, no worktree (the `debt` posture)", and
        `cmd_profile`'s own docstring says it holds THE SAME POSTURE AS `cmd_debt`, deliberately. It is
        admitted because a byte-copied consumer's SPEC-0145 producer (`bin/security-audit`) is fired by
        cron/systemd with NO session and NO anchor in its checkout, and the SPEC-0093 carrier it reads
        declares `<engine>/bin/yitc-v2 -C <repo> profile --json` as the route to the ONE derivation site
        (`bin/lib/profile.py#resolve_profile`). A read-only VIEW verb refusing that trigger on
        `no_session_started_anchor` starved the seam entirely. Ratified on technical merit by the
        external consult `decisions/T-12165-audit-consult-on-demand.yaml` (GREEN, single survivor) and
        decided by the owner's standing authorization 2026-09-05T02:47:11Z; every bound below survives
        unchanged — still a closed enumeration, still the stderr WARNING, still the `selected_source=` /
        `fallback_reason=` telemetry.

      BOUND 1 (scope) — the allowlist is a CLOSED set of three verb labels. Every mutating, stage,
        seed-delivery and session-guidance verb keeps the strict fail-closed path VERBATIM. The
        fail-safe direction of the chokepoint is therefore preserved: an unlisted verb is strict.
      BOUND 2 (the nudge survives) — a tolerated read is NOT silent. It prints a visible fallback
        WARNING to stderr saying the floor was bypassed and how to restore it. Tolerated output is
        OBSERVATIONAL ONLY: a starved controller must not base a governance decision on it.
      BOUND 3 (auditable) — that warning carries the machine-readable telemetry `selected_source=`
        (which selector produced the ref, or `unresolved`) and `fallback_reason=` (which of the four
        gate reasons WOULD have refused), so a stale/unbacked fallback is visibly auditable.

    The bound lives INSIDE this function — not in a module constant — so that widening it necessarily
    changes this signed `implements:` anchor's content signature and trips SPEC-0050 spec-freshness. A
    module-level constant would sit outside every anchor and could drift silently (audit-pre finding).

    A tolerant verb resolves its ref through the injected NON-DYING keyer twin
    (`_try_resolve_session_ref_with_source`, T-10167/T-10318) rather than the fail-closed keyer: the
    keyer `_die`s on an unbacked carry having ALREADY printed its diagnostic, so catching its SystemExit
    would leak that stderr line (`lessons/fail-closed-belongs-to-the-reader-not-the-parser.md`). When the
    twin is not injected the verb falls back to STRICT — the fail-safe direction, never a silent bypass.
    The PASS path (a fresh receipt) is untouched: it returns before any of this, so a healthy session
    sees no warning and no behaviour change.

    TAIL-FIRST READ (T-10396, mirror of `_require_help_read`). This gate fires on EVERY governed/mutating
    verb, so its per-candidate FULL journal parse was the broadest per-invocation cost in the CLI (0.89s
    per scan on the 90MB main journal). The fast path now reads a TAIL-WINDOWED snapshot when the host
    injects `_iter_events_tail`, and every would-be refusal is RE-DECIDED on the full snapshot before it
    is emitted (`_gate_pass_tail_first` — the monotonicity proof lives there). All three refusal reasons
    keep their exact meaning and are still computed from a COMPLETE read: in particular a STALE-EPOCH
    receipt still refuses (it fails the tail, the full pass re-reads, and it still fails), which is the
    semantics-unchanged clause this conversion was required to preserve. `_iter_events_tail=None` (the
    default) keeps the original full-read-only behavior for every existing caller/test.

    CREDIT SHORT-CIRCUIT (T-11329). `_attempt` stops scanning candidates the moment one has yielded a
    receipt for the current epoch, instead of always reading the whole candidate set. The verdict is
    MONOTONE in the accumulated epoch list, so this changes WHEN reading stops, never WHICH receipts
    are accepted; it fires only on a credit, so every refusal still reads every candidate and its
    payload is unchanged. It halves the PASS cost of a call from a WORKTREE, where the candidate set is
    two distinct paths holding near-identical journals (T-11327: 2.012s vs 0.937s from main) and the
    existing path-dedup in `_gate_candidate_events_paths` cannot collapse them. The full argument sits
    beside the code."""
    ctx = {"action": "governed/mutating verb", "stage": None}

    # BOUND 1 — the closed allowlist. Kept LOCAL (inside the signed anchor) on purpose; see docstring.
    _TOLERANT_VERBS = frozenset({"debt", "followup list", "profile"})
    # Fail-safe: a tolerant verb whose non-dying twin was not injected degrades to STRICT, not to open.
    tolerant = verb in _TOLERANT_VERBS and _try_resolve_session_ref_with_source is not None

    def _tolerate(reason: str, source: "str | None") -> None:
        """BOUND 2 + BOUND 3 — the visible, machine-readable fallback nudge on a tolerated read."""
        print("\n".join([
            f"yitc-v2: WARNING — {verb}: seed-gate TOLERATED (bounded read-only exception, SPEC-0050 §8a).",
            f"  selected_source={source or 'unresolved'} fallback_reason={reason}",
            "  This output is OBSERVATIONAL ONLY — do not base a governance decision on it.",
            "  Restore the anti-Forgetting floor: bin/yitc-v2 session start",
        ]), file=sys.stderr)

    selected_source = None
    if tolerant:
        sref, selected_source = _try_resolve_session_ref_with_source()
        if sref is None:
            # Nothing resolved at all — the strict keyer would have `_die`d here, before any receipt logic.
            _tolerate("session_ref_unresolved", selected_source)
            return
    else:
        sref = _resolve_session_ref()

    def _refuse(reason: str, lines: "list[str]") -> None:
        """The ONE refusal seam. STRICT: emit `read_gate_refused` + `_die` (byte-identical to the prior
        three inline blocks). TOLERANT: warn + return, so the read-only fold exits 0."""
        if tolerant:
            _tolerate(reason, selected_source)
            return
        _emit_read_gate_refused(verb, ctx, kind="read-check", reason=reason, session_ref=sref)
        _die("\n".join(lines))

    current_epoch = _session_epoch()

    def _attempt(*, tail: bool = False) -> "tuple[bool, tuple, bool]":
        """ONE consistent evaluation pass. Returns (credited, (any_anchor, epochs), bounded). Per candidate
        the anchor + receipt scans share a SINGLE snapshot (T-10115), so a concurrent rewrite cannot
        interleave between them. Per-journal anchored windows, OR-ed — no raw union (mirror of
        _require_help_read). `bounded` is True iff some candidate's snapshot was a genuinely narrowed tail
        (T-10396), i.e. a refusal computed here is NOT final — the full read may still credit."""
        anchored = False
        narrowed = False
        found = []
        for ev_path in candidate_events_paths:
            snapshot, was_bounded = _gate_snapshot(ev_path, tail=tail, _iter_events=_iter_events,
                                                   _iter_events_tail=_iter_events_tail)
            narrowed = narrowed or was_bounded
            lower_bound = _session_started_lower_bound(sref, events=snapshot)
            if lower_bound is None:
                continue   # no anchor in THIS journal -> not a valid window here (do not credit across journals)
            anchored = True
            found.extend(_seed_receipt_epochs(sref, lower_bound, events=snapshot))
            # SHORT-CIRCUIT ON CREDIT (T-11329) — stop reading once the answer is SETTLED, never to
            # settle it differently. The verdict `bool(found) and any(e >= current_epoch for e in
            # found)` is MONOTONE in `found`: a later candidate can only APPEND epochs, and `any()`
            # over a growing list never goes back to False. So once one candidate has yielded a
            # fresh-epoch receipt, scanning the remaining candidates cannot change `credited` — it
            # can only re-read the same near-identical journal (a call from a worktree scans TWO
            # copies: T-11327 measured 2.012s against 0.937s from main). This fires ONLY on a credit,
            # so the REFUSAL path is structurally unreachable from here and still scans EVERY
            # candidate — its payload (`anchored`, `found`) is therefore byte-identical to a full
            # loop, and every refusal reason and message value (the stale-epoch `max(epochs)`) is
            # chosen exactly as before. `narrowed` is likewise irrelevant on this exit:
            # `_gate_pass_tail_first` returns on a credit without consulting it.
            if any(e >= current_epoch for e in found):
                return True, (anchored, found), narrowed
        credited = bool(found) and any(e >= current_epoch for e in found)
        return credited, (anchored, found), narrowed

    credited, (any_anchor, epochs) = _gate_pass_tail_first(
        _attempt, _sleep=_sleep, tail_enabled=_iter_events_tail is not None)
    if credited:
        return
    if not any_anchor:
        # FAIL-CLOSED (mirrors _require_help_read): no anchor in ANY candidate -> no valid window -> refuse.
        return _refuse("no_session_started_anchor", [
            f"{verb}: no session_started anchor for this session in any candidate journal — refusing (fail-closed).",
            "The audience-seed read-gate credits the seed_read receipt ONLY within a window anchored by THIS",
            "session's own session_started (SPEC-0050 §2). Emit the anchor in this checkout, then re-invoke:",
            "  bin/yitc-v2 session start",
        ])
    if not epochs:
        return _refuse("seed_read_unfetched", [
            f"{verb}: the audience seed was not read this session — refusing (T-10081 / SPEC-0050 §8 seed floor).",
            "`session start` delivers your audience seed AND emits the receipt; read the seed, then re-invoke:",
            "  bin/yitc-v2 session start",
            "(session start emits the seed_read receipt after delivering the seed; the gate checks the receipt, not comprehension)",
        ])
    # Reached only when a receipt exists but every one predates the current context epoch (the credit
    # check in the retry loop already returned on any fresh receipt) — a /compact evicted the seed from
    # context after it was read, so the receipt is STALE (T-10082 / SPEC-0050 §8).
    return _refuse("seed_read_stale_epoch", [
        f"{verb}: your seed_read receipt is from an earlier context epoch — refusing (T-10082 / SPEC-0050 §8).",
        f"A /compact advanced the context epoch (receipt epoch {max(epochs)} < current {current_epoch}); the",
        "pre-compact seed is gone from context. Re-read your audience seed, then re-run `session start` ONCE",
        "to refresh the receipt for this epoch (the sanctioned post-compact re-run — SPEC-0007 §5b):",
        "  bin/yitc-v2 session start",
    ])


def _require_audit_post_for_commit(yaml, tid: str, full_sha: str, *, _audit_yaml_path, _die,
                                   _git_resolve_sha, AUDIT_VERDICT_CANONICAL,
                                   AUDIT_VERDICT_CLOSURE_OK) -> str:
    """Artifacts-as-gate (D-0082 step 3, extends D-0015): the <tid>-audit-post.yaml must EXIST, carry
    a GREEN/YELLOW verdict, AND be for THIS commit (its recorded `commit:` resolves to full_sha).
    Returns the verdict; dies otherwise. (T-0527/SPEC-0052: resolves the active decisions/ path OR the
    archive fallback — this gate fires for an IN-FLIGHT task whose audits are NOT yet archived, so the
    active path wins in practice; the fallback only matters for a re-close of an already-archived task.)"""
    audit_post = _audit_yaml_path(tid, "post")
    if audit_post is None:
        _die(f"audit-post YAML missing: decisions/{tid}-audit-post.yaml — "
             "Stage 8 must precede Stage 9 per D-0015 (or pass --hygiene-fast-path for hygiene tasks)")
    try:
        ap = state.load_str(audit_post.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        _die(f"audit-post YAML parse error: {e}")
    verdict = ap.get("verdict")
    if verdict not in AUDIT_VERDICT_CANONICAL:
        _die(f"audit-post verdict {verdict!r} not canonical (expected one of {list(AUDIT_VERDICT_CANONICAL)})")
    if verdict not in AUDIT_VERDICT_CLOSURE_OK:
        _die(f"audit-post verdict {verdict!r} blocks Stage 9 — revert or escalate per LIFECYCLE Stage 8")
    ap_commit = (ap.get("commit") or "").strip()
    if not ap_commit:
        _die(f"audit-post {audit_post.name} has no commit: field (predates the D-0082 commit-binding) — "
             f"re-run `yitc-v2 audit post --task {tid} --commit {full_sha[:7]}` so closure can verify it.")
    ap_full = _git_resolve_sha(ap_commit)
    if ap_full != full_sha:
        _die(f"audit-post is for commit {ap_commit} (≠ the task's recorded {full_sha[:7]}) — re-run "
             f"`yitc-v2 audit post --task {tid}` against the recorded commit (D-0082 chain-of-custody).")
    return verdict


def _require_audit_pre_matches_plan(yaml, tid: str, plan_text: str, *, _audit_yaml_path, _die,
                                    _plan_content_hash, AUDIT_VERDICT_CANONICAL,
                                    AUDIT_VERDICT_CLOSURE_OK) -> str:
    """Artifacts-as-gate (D-0082 step 4): a substantive `task execute` needs a GREEN/YELLOW audit-pre
    BOUND to the CURRENT plan — its recorded plan_fingerprint must match. A stale pre-audit on a
    since-edited plan is refused. Returns the verdict; dies otherwise. (T-0527/SPEC-0052: resolves the
    active OR archive path; this gate fires at `task execute` for an IN-FLIGHT task whose audits are
    not archived, so the active path wins — the fallback is uniformity, not a live need.)"""
    audit_pre = _audit_yaml_path(tid, "pre")
    if audit_pre is None:
        _die(f"audit-pre YAML missing: decisions/{tid}-audit-pre.yaml — run `yitc-v2 audit pre "
             f"--task {tid}` (Stage 4) before execute (D-0082 step 4).")
    try:
        ap = state.load_str(audit_pre.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        _die(f"audit-pre YAML parse error: {e}")
    verdict = ap.get("verdict")
    if verdict not in AUDIT_VERDICT_CANONICAL:
        _die(f"audit-pre verdict {verdict!r} not canonical (expected one of {list(AUDIT_VERDICT_CANONICAL)})")
    if verdict not in AUDIT_VERDICT_CLOSURE_OK:
        _die(f"audit-pre verdict {verdict!r} blocks execute — re-plan per LIFECYCLE Stage 4 (need GREEN/YELLOW).")
    fp = ap.get("plan_fingerprint")
    if not fp:
        _die(f"audit-pre {audit_pre.name} has no plan_fingerprint (predates D-0082 step 4) — re-run "
             f"`yitc-v2 audit pre --task {tid}` so execute can verify the plan is unchanged.")
    if fp != _plan_content_hash(plan_text):
        _die(f"the implementation_plan changed since audit-pre (fingerprint mismatch) — the pre-audit "
             f"is stale; re-run `yitc-v2 audit pre --task {tid}` before execute (D-0082 step 4).")
    return verdict
