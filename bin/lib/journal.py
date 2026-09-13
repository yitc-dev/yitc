"""bin/lib/journal.py — the journal verb-family + the session-log sync engine
(T-9381, byte-identical extraction from bin/yitc-v2). Full inject-residue seam
(plan.py/T-9341 pattern): host collaborators + host globals/consts + moved siblings arrive by
keyword-only injection; the host keeps a residue wrapper per moved fn so every `yitc.<symbol>`
caller / monkeypatch keeps resolving. The module is a clean lower leaf: imports only already-
extracted lib leaves (state, events) + stdlib, never back-imports the host."""
from __future__ import annotations
import argparse
import contextlib
import datetime as _dt
import functools
import hashlib
import json
import os
import re
import sys
import threading
import time
from pathlib import Path
from lib import state    # noqa: E402
from lib import events   # noqa: E402
from lib import textutil  # noqa: E402  # T-10390: the ONE home of the path-token extractor
                          # (derive_path_tokens) shared with the Stage-1 write-back; textutil is a
                          # leaf (stdlib + state + events) — back-imports nothing, no cycle.


def _all_source_refs(*, EVENTS_PATH) -> set:
    """ALL source_ref values in events.jsonl (full-history dedup — recovery path only).

    Used only on first-sync / stale-cursor rescan (rare), so full scan is acceptable
    and CORRECT for arbitrarily large replays (audit-post F1: bounded window was
    insufficient for the no-duplicate contract). Steady-state sync skips dedup entirely
    — entries after the checkpoint cursor are new and cannot already be materialized.
    """
    if not EVENTS_PATH.exists():
        return set()
    refs = set()
    for line in segment_lines(EVENTS_PATH):  # T-11444: segment-aware fold (SPEC-0190 r4)
        try:
            sr = json.loads(line).get("source_ref")
        except (json.JSONDecodeError, AttributeError):
            continue
        if sr:
            refs.add(sr)
    return refs

def _attachment_injection(e: dict) -> dict | None:
    """attachment entry → instruction_injection POINTER data (T-0089 / D-0046 Component 2), or None.

    Captures the substantive context AUTO-LOADED into the AI's input — `nested_memory` (the
    CLAUDE.md / AGENTS.md + nested memory files) and `skill_listing` (the capabilities catalog).
    Parser-captured rows carry POINTER + SIZE ONLY (target / size_lines / size_chars / form /
    source) — NEVER the document body (owner directive 2026-05-29: «какие прочитал и размер
    фиксируем, само содержание нет» — avoids duplicating the doc into the journal; the text of the
    moment is recovered via `graph query --as-of` over the versioned docs). EXEMPT from the
    authoring-side rationale / category / mandatory fields (T-0089 audit-pre F0) — an auto-load
    carries no derivable «why». Harness ephemera (task_reminder, deferred_tools_delta,
    command_permissions, edited_text_file, queued_command) are NOT doc-injections → skipped.
    """
    att = e.get("attachment")
    if not isinstance(att, dict):
        return None
    atype = att.get("type")
    if atype == "nested_memory":
        target = att.get("displayPath") or att.get("path") or "nested_memory"
    elif atype == "skill_listing":
        target = "skill_listing"
    else:
        return None
    body = att.get("content")
    if not isinstance(body, str):           # real logs carry structured content for some types
        body = "" if body is None else json.dumps(body, ensure_ascii=False)
    # `inject_source` carries D-0008's how-injected semantic (auto vs owner/hook); kept DISTINCT
    # from the envelope `source` (which _append_event sets to yitc-v2-cli — writer provenance).
    # `size_lines` uses splitlines() (NOT `count("\n")+1`, which over-counts a newline-terminated
    # body by one); the T-0089 tests assert this rule.
    return {"injection_kind": atype, "target": target, "arrival": "auto",  # D-0048 arrival tag
            "size_lines": len(body.splitlines()),
            "size_chars": len(body), "form": "link_only", "inject_source": "auto"}

def _checkpoint_path(session_ref: str, *, SYNC_STATE_DIR) -> Path:
    h = hashlib.sha256(session_ref.encode("utf-8")).hexdigest()[:16]
    return SYNC_STATE_DIR / f"{h}.yaml"

def _classify_cc_entry(e: dict, *, _extract_text) -> str | None:
    """Claude Code JSONL entry → parser-captured event type, or None (noise).

    Loose heuristic per D-0030 rejected_ideas (strict normalization rejected):
    instruction_injection vs owner_directive distinction is best-effort.
    """
    if e.get("type") != "user":
        return None                       # only user-origin input; assistant/runtime = noise
    if "toolUseResult" in e:
        return None                       # tool result, not owner input
    # D-0048 denoise: harness machinery (command caveats, slash-command OUTPUT / skill bodies)
    # is flagged isMeta by the tool — it is NOT owner intent. Drop it. Slash-command INVOCATIONS
    # are NOT isMeta, so they still classify as slash_command below (no slash_command suppressed).
    if e.get("isMeta"):
        return None
    content = e.get("message", {}).get("content")
    text = _extract_text(content).strip()
    if not text:
        return None
    # belt-and-suspenders for logs lacking isMeta: explicit local-command wrappers are machinery.
    if "<local-command-caveat>" in text or "<local-command-stdout>" in text:
        return None
    if "<command-name>" in text or (text.startswith("/") and "\n" not in text[:80]):
        return "slash_command"
    # `<task-notification>` wraps machine output — a completed background task / primary sub-agent
    # + audit payload injected by the harness as a non-isMeta user entry. It is NOT owner intent
    # (X-0210: classifying it owner_directive polluted the intent-vs-actual surface AND the
    # owner_directive-first recovery grep). Route it to the same non-owner machinery bucket.
    if "<system-reminder>" in text or "<command-message>" in text or "<task-notification>" in text:
        return "instruction_injection"
    # list-structured long content w/o owner phrasing = context/skill injection
    if isinstance(content, list) and len(text) > 500:
        return "instruction_injection"
    # T-12400: a DISPATCHED WORKER's standing preamble arrives as a plain-STRING `user` entry, so
    # every one of them fell through to `owner_directive` below — 209 rows in 3 days in the kernel,
    # polluting the ONE channel AGENTS §Recovery tells a session to grep FIRST for the owner's own
    # wording (kupiclub X-1364 / aiseller X-1345). It IS machine-injected instruction text, which is
    # exactly what `instruction_injection` names. The marker is SINGLE-SOURCED from the module that
    # BUILDS the preamble (it interpolates the same constant), read by the established LAZY leaf-order
    # import — dispatch imports journal, so a module-level import here would be circular. Fail-SAFE:
    # any import/attribute failure leaves today's classification untouched (a best-effort denoise must
    # never be able to break the materializer).
    try:
        from lib import dispatch as _dispatch   # noqa: PLC0415 — lazy by design (leaf-order)
        if text.startswith(_dispatch.DISPATCH_PREAMBLE_MARKER):
            return "instruction_injection"
    except Exception:
        pass
    return "owner_directive"


# ---------------------------------------------------------------------------------------------
# The dispatch CLASS vocabulary — the SINGLE carrier (T-10253).
#
# Homed with its PRODUCERS: `_classify_dispatch` below emits every class but `halted`, which
# `cmd_journal_fleet_verdict` adds (SPEC-0133 rule 2a). Every reader-facing surface that
# ENUMERATES the vocabulary — the `--dispatch-status` + `--fleet-verdict` argparse help
# (bin/yitc-v2) and the `DISPATCH_WATCHER_CUE` (bin/lib/dispatch.py) — RENDERS it from here via
# the three pure renderers below. Before T-10253 each surface hand-restated a different SUBSET,
# so a controller asking «did THIS dispatch halt?» could not learn from either that the verb
# covers it, and fell back to the raw-journal grep the cue forbids (E-0001; withdrawn X-0245).
#
# A new class therefore lands HERE first: `tests/test_dispatch.py` ast-parses `_classify_dispatch`
# and fails if any class it returns is missing from this tuple, which is what forecloses a third
# hand-maintained list. Peer in shape to DISPATCH_TERMINAL_DETAIL (a dispatch vocabulary constant
# consumed by renderers) — no new store, no new event, no registry.
# ── The land-queue WAIT SERIES: the one named source both readers resolve through (T-11831) ──────
#
# WHAT THESE ROWS ARE. A land that cannot proceed parks at one of two seams and journals a throttled
# heartbeat carrying its cumulative `waited_s`: `waiting_for_verify_admission_slot` while blocked on
# one of the N SPEC-0132 verify-concurrency slots (T-10128), and `waiting_for_land_reservation` while
# parked on the single reservation flock that serializes merge->verify->ff (T-10549). They are two
# genuinely DIFFERENT queues, and a land can be parked at either — since T-11117 serializes that span,
# a queued PEER normally parks at the RESERVATION and only the holder ever reaches the admission slot.
#
# WHY THE CARRIER LIVES HERE, IN THE LEAF, RATHER THAN WITH THE EMITTER. It has three consumers in
# two directions: the emitter (`worktree._LAND_QUEUE_WAIT_TYPES`, which now consumes this name) and
# two independent READERS of the series — the SPEC-0132 admission lens (`views._view_admission_series`)
# and SPEC-0119 rule 27's aborted-land phase split (`debt._abort_rows`). Homing it with the emitter
# and re-exporting it downward would put an import edge from the debt echo UP into the land engine
# (audit-pre finding, 2026-08-29). `journal.py` imports only state/events/textutil, and both readers
# already import it eagerly — so this is the only home where every edge points DOWN.
#
# WHY IT IS A SINGLE SOURCE AND NOT A CONVENIENCE. Rule 27 previously sourced its wait from
# `land_completed.data.admission_wait_ms`, the SAME field the admission lens labels a
# `secondary_instrument` with status "UNDER-REPORTING ... Do not quote these figures as admission
# waits" (T-11119). Two readers, one question, one forbidding what the other did. The field is not
# false — it is TRUE about the wrong queue: `admission_waits` is appended only by
# `_verify_under_admission`, so it never records the RESERVATION wait, which is where the minutes
# actually go (measured 2026-08-29: task/T-11799 and task/T-11618 carry reservation peaks of 8042s
# and 2950s with ZERO admission-slot heartbeats and `admission_wait_ms: 0`). Both readers now resolve
# WHICH ROWS ARE THE SERIES through this one home; each keeps its OWN aggregation, because they ask
# different questions (see `debt._abort_attributed_wait_ms` for why rule 27's must be per-LAND).
LAND_QUEUE_WAIT_TYPES = ("waiting_for_verify_admission_slot", "waiting_for_land_reservation")


def land_queue_wait_observation(event):
    """One journal row -> `((session_ref, branch), waited_s)` for a land-queue wait heartbeat, else None.

    `None` means NOT A WAIT ROW — the caller skips it. A row that IS a wait row but carries no usable
    `waited_s` yields `waited_s=None` rather than `None`, because the two answers are different
    questions: the row still proves the land PARKED at that seam (which is what the admission lens's
    per-stream attribution reads), while its DURATION is simply unrecorded. Collapsing them would let
    an unreadable number erase the park itself.

    `bool` is rejected — `isinstance(True, int)` is True, so an unguarded read would score a
    `waited_s: true` as a one-second wait. No emitter writes one (both sites `int()` the value); this
    is the same never-admit-a-bool discipline the abort-cost fold applies to every duration it reads.

    PURE: reads a dict, decides nothing, touches no journal."""
    if not isinstance(event, dict) or event.get("type") not in LAND_QUEUE_WAIT_TYPES:
        return None
    data = event.get("data")
    if not isinstance(data, dict):
        return None
    waited = data.get("waited_s")
    if isinstance(waited, bool) or not isinstance(waited, (int, float)):
        waited = None
    return (event.get("session_ref"), data.get("branch")), waited


def fold_wait_segments(observations):
    """A wait series -> the TOTAL seconds it waited: the peak of each PARK, summed. `None` when the
    series proves no duration at all.

    `observations` is `waited_s` values in JOURNAL ORDER (oldest first) — the caller sorts, because
    only the caller knows which stamps belong to the span it is attributing.

    WHY A SEGMENT SUM AND NOT A MAX (T-11908). `waited_s` is per-PARK, not per-land: `_t0` is
    re-seeded on every entry to `_acquire_land_reservation` (`worktree.py`), and it restarts at 0
    whenever a NEW land process parks (`batch_landing.py`) — an observed reset is recorded at
    `worktree.py` for T-11702, 11:17:14Z, after 561s of waiting. So a land that parks, is displaced and
    parks again journals TWO rising series, and `max` over them reports only the LONGEST park while
    the land paid the sum. Taken over the T-11236 window that fold made the published reservation
    figure low by construction. A DROP below the running peak is the ONLY reset marker the series
    carries (the value rises monotonically within one park), which is the same cut
    `dev-utilities/measure-land-budget.py::_fold_queue` already makes.

    A SERIES WITH NO RESET IS UNCHANGED, structurally and not by luck: with no drop there is exactly
    ONE segment, so the return is exactly `max(observations)` — the value the old fold produced, to
    the bit. That is the invariant `tests/test_t11908_reservation_wait_sum.py` pins.

    Unusable values are SKIPPED, never scored: `None` (a wait row whose duration is unrecorded still
    proves the park, which is the caller's business, not this fold's) and `bool` (`isinstance(True,
    int)` is True, the same never-admit-a-bool discipline `land_queue_wait_observation` applies).
    A series of nothing but unusable values returns `None`, never 0 — an unrecorded wait and a
    zero-length one are different claims (T-0358).

    THE SUM KEEPS THE VALUES' OWN TYPE — the accumulator starts at `0`, not `0.0`, so an int series
    returns an int and the no-reset case is identical in TYPE as well as in value.

    PURE: reads numbers, decides nothing, touches no journal."""
    total = 0
    peak = None
    for waited in observations:
        if waited is None or isinstance(waited, bool) or not isinstance(waited, (int, float)):
            continue
        if peak is None:
            peak = waited
        elif waited < peak:
            total += peak          # the previous park ended at its peak; this row starts a new one
            peak = waited
        else:
            peak = waited
    if peak is None:
        return None
    return total + peak


DISPATCH_CLASS_VOCAB = (
    ("working",
     "the worker is alive and progressing — NOT actionable (detail: `recent` | `alive-proc` = a "
     "live `--session-id` proc despite a stale journal | `audit-heartbeat` = journal-silent but the "
     "dispatch log is fresh mid-audit | `still-booting,age=Nm` = PRE-ANCHOR: dispatched but not yet "
     "anchored by its own `session_started`, so the worker has journaled no evidence of its own yet "
     "— within the near-launch grace, or past it with the proc alive (a slow bootstrap) | `landing` = "
     "MID-LAND: the chain carries a `blocked_on_land` halt marker but the worker proc (or its land "
     "child) is POSITIVELY alive, so the worker is retrying `land` inline — a transient, NOT the "
     "settled stop (T-10394; the blocked_on_land detail surfaces only once the proc is gone))"),
    ("TERMINAL",
     "the dispatched PROCESS ended — this says NOTHING about the task's status. detail: `done` (the "
     "worker landed, or main already reads `status: done`) | `halt` (the worker self-halted) | "
     "`wont-do` (the worker declined a superseded / self-unsatisfiable task) | "
     "`stopped(controller)` (a governed `dispatch --stop` — the CONTROLLER stopped this worker, so the "
     "stop IS the decision: observable here, but NEVER surfaced by `--fleet-verdict` as a "
     "needs-decision halt; the released slot just drops from the in-flight view, T-10403) | "
     "`blocked_on_land(needs-controller)` (a SPEC-0103 §3 halt carrying `blocked_on_land` — the worker "
     "STOPPED rather than force a land and escalated to the CONTROLLER, worktree intact; no owner "
     "clause governs it, so the controller decides: resolve the named cause, or consciously continue "
     "with the land's `--ack-repeated-abort`, which is NOT owner-gated, T-10788. SPEC-0204 rule 6 "
     "(T-12290) routes the AUDIT-LOOP-CEILING halt here too — it carries `residual_fingerprints`, and "
     "the controller\'s move is one `yitc-v2 audit decide` per fingerprint, then re-dispatch, where "
     "the worker resumes with the decision-governed audit pass) | "
     "`blocked_on_land(needs-owner)` (the same halt shape carrying `needs_owner_reset` — recoverable, "
     "but an OWNER-authorized continuation flag gated the re-dispatch: the audit-loop ceiling\'s "
     "former owner-reset, RETIRED by SPEC-0204 rule 6, so only rows already on record read "
     "this way. The two labels stay deliberately distinct so a controller does not escalate a "
     "decision the owner does not own). "
     "BOTH surface ONLY once the worker proc AND its land child are gone — while either lives the "
     "same chain reads working(landing), T-10394. "
     "Read `TERMINAL(done)` as «the dispatch is over», never as «the task is done»: a task PAUSED "
     "awaiting an owner decision whose bookkeeping then landed also reads TERMINAL(done) — and "
     "`--fleet-verdict` now DELIVERS that reading on the ROW itself, as an optional report-only "
     "`pause_detail` naming the card's pause reason + stage whenever the CARD cross-check reads a "
     "paused card (T-10712/X-0557: the semantics were already documented HERE, but a controller "
     "reading one row alone re-dispatched a task that was merely waiting on the owner). Same class, "
     "same verdict — a detail, never a reclassification"),
    ("closed_pending_land",
     "built + closed but NOT integrated — a live `task/T-XXXX` worktree claim is still on disk "
     "(detail: `own|foreign|unknown-stamp` + `land-alive` = the worker's own self-land is in "
     "flight, LEAVE IT (a controller `land` races it, E-0035) / `land-dead,session-alive` = the land "
     "CHILD is gone but the WORKER SESSION still lives — it may be re-invoking its own land per the "
     "synchronous-to-LAND discipline, so WAIT/re-poll; recovery is NOT applicable (T-10953, X-0815) / "
     "`land-dead` = abandoned, recover "
     "with the governed `bin/yitc-v2 worktree recover-land --task T-XXXX`). Scoped to the WORKER "
     "land regime (the launch row's `land_regime` absent or `worker`) — under `controller` the same "
     "shape reads `closed_awaiting_controller_land` below, never here"),
    ("closed_awaiting_controller_land",
     "the CONTRACTED completion under the CONTROLLER-LANDS regime (T-12351 / T-12373): the worker's "
     "launch row carries `land_regime: controller`, the task is `done` on its branch (task_closed, "
     "live `task/T-XXXX` worktree claim still on disk) and NO land process is running — the worker "
     "stopped after `task close` exactly as its composed STOP/LAND CONTRACT told it to (SPEC-0103). "
     "NOT a death, NOT a halt, NOT a recovery case: the one owed step is the CONTROLLER's plain "
     "`bin/yitc-v2 land --task T-XXXX` from main (never `worktree recover-land` — that verb's "
     "predicate is a DEAD worker, and this worker is not dead, it is finished). The dispatch watcher "
     "reads it as a positive TERMINAL(done) (`WATCH: ANY_TERMINAL` names it; no WAKE) and the "
     "SPEC-0119 rule-12/18 debt lines exclude it. Detail: the claim stamp's provenance "
     "`own|foreign|unknown-stamp`. A land process ALIVE on that branch keeps the "
     "`closed_pending_land(…,land-alive)` reading — a running land is left alone whatever the regime"),
    ("paused",
     "a CONTROLLER-CUED CLEAN STOP (T-12304): the worker\'s brief ended in «STOP and report» (a "
     "re-plan-only / align-only step), it exited cleanly and recorded the stop via `task pause "
     "--reason controller-wait`, which writes the resume contract (`resume_from` / `next_action`). "
     "TERMINAL and NOT `working` — the process is over and nothing is settling; and NOT a block "
     "either (no gate refused it), so it is not `halted`. `--fleet-verdict` reads it as "
     "needs-decision, because the pending step is the CONTROLLER\'s and the card NAMES it in "
     "`next_action`. The relaunch is one command — `dispatch --resume T-XXXX` — which needs no "
     "`--force` (the in-flight guard yields to this row) and heads the worker\'s task-specific "
     "brief with the recorded contract. Detail: the pause reason (`controller-wait`)"),
    ("halted",
     "`--fleet-verdict` ONLY (SPEC-0133 rule 2a): a RECENT unresolved self-halt whose proc and "
     "child are both gone — the dropped-worker case the base classes do not cover. Carries the halt "
     "`reason` straight from the `bg_dispatch_halted` event, so the controller routes it (re-dispatch "
     "once the blocker is resolved) WITHOUT re-grepping the journal. One halt kind routes DIFFERENTLY: "
     "`refused(pre-claim)` (T-10291) = the worker came up, ANALYZED a ready task and refused it via "
     "`task refuse` — a governed refusal, NOT a dead bootstrap, so a plain re-dispatch LOOPS it; "
     "resolve the named blocker (or take the owner decision) first. UNRESOLVED is the operative word "
     "(T-10771 / rule 2d): a halt whose OWN CAUSE the journal records as cleared — the task's branch "
     "landed ok, or the designed ceiling continuation ran (converged consult + granted GREEN pass) — "
     "is NOT reported here. It stays fully visible as an in-flight row carrying a report-only "
     "`halt_detail` naming the halt and how it was resolved; only its needs-decision ACTIONABILITY "
     "drops, so a cleared halt stops reading as an open owner-gated block. Fail-closed: any halt whose "
     "resolution is not positively recorded still reports as `halted`"),
    ("stranded",
     "`--fleet-verdict` ONLY (SPEC-0133 rule 2a, T-10577): the worker LANDED the task (so the journal "
     "axis reconciles TERMINAL(done)) but the CARD on main is still `in-progress` and NOT paused — a "
     "task stranded MID-LIFECYCLE (no audit-post/closure). Off the journal alone the released slot "
     "would drop and the batch read FINISHED, hiding the strand until someone greps (X-0428); the CARD "
     "cross-check surfaces it as needs-decision so the controller drives it to closure (or park/wont-do) "
     "— NOT a re-dispatch. Report-only, no new FSM/store"),
    ("launch-stall",
     "a launcher-dispatched worker that never came up past the near-launch bootstrap grace and never "
     "claimed — process gone, nothing to adopt; re-dispatch (detail: `no-claim-past-grace`). TWO "
     "details route DIFFERENTLY, in OPPOSITE directions: `auth-failure` (T-10792) = the launch log "
     "carries a provider AUTHENTICATION signature («Not logged in · Please run /login» and kin), so "
     "the bootstrap died before any worker code ran — a plain re-dispatch re-dies identically until "
     "the credential is restored (it needs a HUMAN); `transient-overload` (T-11565) = the log declares "
     "its own failure TEMPORARY and server-side («…usually temporary - try again in a moment»), so the "
     "remedy is the opposite one — WAIT, then re-dispatch the SAME task unchanged; nothing is wrong "
     "with the task, the worker or the credential. Only a RECOGNISED signature earns either; an empty "
     "or unreadable log keeps "
     "`no-claim-past-grace` (fail-closed — an unexplained death is never relabelled as explained)"),
    ("silent_stop",
     "non-terminal, journal-stale, and NO live worktree claim — the worker stopped without landing or "
     "claiming anything (detail: `no-live-claim`)"),
    ("hang_suspect",
     "non-terminal, journal-stale, but a LIVE worktree claim is still held — the dead-but-unlanded "
     "orphan (detail: the claim stamp's provenance `own|foreign|unknown-stamp`)"),
)


# T-12304 — the pause reason that mints the `paused` class, named ONCE here so the classifier, the
# fleet-verdict branch and the dispatch in-flight guard all key on the same literal (T-10253: one
# carrier per state, never a second vocabulary).
CONTROLLER_WAIT_PAUSE_REASON = "controller-wait"

# T-12373 / T-12351 — the LAND REGIME values a `bg_dispatch_launched.data.land_regime` row carries,
# named ONCE at the journal leaf so the launcher (dispatch.py re-binds these), the stage reminder
# resolver and the dispatch-status classifier cannot spell them apart. `worker` is the CANON (CHARTER
# §6, owner ruling «оставляем канон» events.jsonl#ts=2026-09-11T03:38:42Z); an absent key reads `worker`.
LAND_REGIME_WORKER = "worker"
LAND_REGIME_CONTROLLER = "controller"

# T-12351 — the class token for a worker that STOPPED AFTER `task close` under `land_regime:
# controller` (the contracted completion, SPEC-0103 / T-12373). Named once here, beside the vocabulary
# that carries its gloss, so the classifier, the fleet-verdict fold, the `--watch` reader and the
# SPEC-0119 rule-12 debt fold all key on the same literal (T-10253: one carrier, never a second).
DISPATCH_CLASS_CLOSED_AWAITING_CONTROLLER_LAND = "closed_awaiting_controller_land"


def _launch_land_regime(launch_data) -> str:
    """The land regime ONE launch row's `data` declares, fail-safe toward canon (PURE, T-12351).

    The same read `dispatch.land_regime_for_worker` makes over the whole stream, applied to the ONE
    launch row `_classify_dispatch` already holds (`newest_launch`) — the classifier cannot import
    dispatch.py (it imports this leaf), and re-scanning the stream for a row already in hand would be
    a second keying path. Absent key / unrecognised value / malformed data → `worker`, the canon."""
    if not isinstance(launch_data, dict):
        return LAND_REGIME_WORKER
    regime = launch_data.get("land_regime")
    return LAND_REGIME_CONTROLLER if regime == LAND_REGIME_CONTROLLER else LAND_REGIME_WORKER


# T-12304 — the CONTROLLER-WAIT pause row, derived from the SAME ts-ascending chain the classifier
# already holds. Pure + reader-only: the newest `task_paused(controller-wait)` with no NEWER
# `task_resumed` for the task (a resumed pause is over and must never re-read as a stop). Returns the
# event, or None. Shared by `_classify_dispatch` and the fleet-verdict branch so both key on one
# derivation, and by the renderer that surfaces the recorded `next_action`.
def _controller_wait_pause(events):
    pause = next((e for e in reversed(events or [])
                  if e.get("type") == "task_paused"
                  and ((e.get("data") or {}).get("reason") if isinstance(e.get("data"), dict) else None)
                  == CONTROLLER_WAIT_PAUSE_REASON), None)
    if pause is None:
        return None
    resumed = next((e for e in reversed(events or []) if e.get("type") == "task_resumed"), None)
    if resumed is not None and (resumed.get("ts") or "") > (pause.get("ts") or ""):
        return None
    return pause


def _controller_wait_next_action(events):
    """The `next_action` the controller-wait pause recorded — the CONTROLLER's own pending step.
    Report-only (SPEC-0133 rule 2): naming it is what makes the needs-decision actionable without a
    second journal grep. Empty string when the row carries none."""
    pause = _controller_wait_pause(events)
    data = (pause or {}).get("data") if isinstance((pause or {}).get("data"), dict) else {}
    return (data.get("next_action") or "").strip()


def dispatch_class_vocab_names() -> tuple:
    """The bare class tokens (no detail suffix) — the machine-checkable set every enumerating
    surface must render, and the set the T-10253 anti-divergence guard asserts `_classify_dispatch`
    (+ the fleet-verdict `halted`) against."""
    return tuple(name for name, _ in DISPATCH_CLASS_VOCAB)


def dispatch_class_vocab_prose() -> str:
    """The vocabulary as ONE flowed paragraph, for argparse `help=` (argparse re-wraps it, so it
    must carry no pre-baked line structure)."""
    return "; ".join(f"{name} — {gloss}" for name, gloss in DISPATCH_CLASS_VOCAB)


def dispatch_class_vocab_block(indent: str = "    ") -> str:
    """The vocabulary as one `name — gloss` line per class, for a pre-formatted stdout cue."""
    return "\n".join(f"{indent}{name} — {gloss}" for name, gloss in DISPATCH_CLASS_VOCAB)


# T-10291 (X-0271) — the halt DETAILS that `--fleet-verdict` surfaces as an unresolved `halted`
# needing a controller decision. SINGLE carrier: `_terminal_detail` mints them, the fleet-verdict
# halted filter consumes them (no second hand-kept list — the E-0001 divergence class).
_HALT_DETAIL_REFUSED = "refused(pre-claim)"
# T-10394 — the OWNER-gated land-block detail, named because THREE sites now key on it (`_terminal_detail`
# mints it, the fleet-verdict needing-decision filter + the `_dispatch_cause_tag` scope consume it, and the
# live-land override in `_classify_dispatch` suppresses it while the worker proc lives). Same single-carrier
# discipline as _HALT_DETAIL_REFUSED — no re-typed string literal.
# T-10788 — it is now the NARROWER of a PAIR. It stays reserved for a block a genuine OWNER clause gates
# (the audit-loop ceiling's `audit --owner-reset`), keyed on `needs_owner_reset`.
_HALT_DETAIL_BLOCKED_ON_LAND = "blocked_on_land(needs-owner)"
# T-10788 — the CONTROLLER-escalation sibling, keyed on `blocked_on_land`. SPEC-0103 §3 — the normative
# home of this halt — says the blocked worker "STOPS and ESCALATES to the controller (`blocked-on-land
# <task> <reason>`, worktree intact)": no owner appears in that clause. Both the deliberate escalation
# verb (`worktree.cmd_blocked_on_land`) and the land repeated-abort backstop
# (`worktree.blocked_on_land_repeated_abort_disposition`) land here — the backstop's continuation flag
# `--ack-repeated-abort` is NOT owner-gated (contrast `land --no-tests`, which REFUSES without
# `--owner-authorized`), so rendering it `needs-owner` told the controller to escalate a decision the
# owner does not own. Behaviourally identical to its sibling everywhere (needs-decision, cause-taggable,
# live-land-suppressed) — only the word it renders differs, which is the whole point.
_HALT_DETAIL_BLOCKED_ON_LAND_CONTROLLER = "blocked_on_land(needs-controller)"
# The pair, for the sites that treat both blocked-on-land readings alike (scope tuples / overrides).
_HALT_DETAILS_BLOCKED_ON_LAND = (_HALT_DETAIL_BLOCKED_ON_LAND, _HALT_DETAIL_BLOCKED_ON_LAND_CONTROLLER)
# T-10403 (SPEC-0133 rule 2c) — the CONTROLLER-STOP detail: a `dispatch --stop` terminal. Named for the
# same single-carrier reason as its two siblings, but note what it is NOT: it is DELIBERATELY ABSENT from
# _HALT_DETAILS_NEEDING_DECISION below. That omission IS the quiet path — not an oversight.
_HALT_DETAIL_STOPPED = "stopped(controller)"
# The halt details that ASK the controller for a decision it has not yet made. A controller_stop is
# exactly the opposite — the controller ITSELF stopped that worker, so the stop IS the decision, and
# re-surfacing it as needs-decision re-asks a settled question + re-wakes armed watchers for the whole
# recency window (for a phantom task id NO re-dispatch decision can ever consume the echo — the live
# 2026-07-11 incident, fp controller-stop-halted-echo-rewakes-watcher-no-quiet-path-for-phantom).
# T-11926 (X-1208) — the PREMATURE-EXIT detail: a dispatched worker whose process is CONFIRMED gone
# while its task is non-terminal and it emitted no terminal of its own. Every sibling above is a halt
# the worker AUTHORED before yielding; this is the one nobody authored, which is exactly why it had to
# be recorded rather than inferred. Two measured incidents: kupiclub 2026-08-31 worker 580b7aa8
# (T-0559) ended its turn mid-Stage-6 with all work uncommitted, no halt row, surfacing 19 minutes
# later; and the 2026-08-12 four-worker wave killed by a provider account session limit, whose own
# capture recorded verbatim that «the CAUSE was visible only by reading the dispatch log». Named here
# under the same single-carrier discipline as its siblings — `_terminal_detail` mints it, the
# fleet-verdict needing-decision filter consumes it, no second hand-kept list (the E-0001 class).
# It is the DEAD sibling of T-10792's `blocked_on_land(needs-controller)`: that task gave a worker
# ALIVE enough to speak a way to reach the fleet reader, and named this same hole in doing so — the
# dispatch log «no fleet-verdict surface reads». This closes it for the worker that cannot speak.
_HALT_DETAIL_PREMATURE_EXIT = "premature_exit(worker-died)"
_HALT_DETAILS_NEEDING_DECISION = ("halt", *_HALT_DETAILS_BLOCKED_ON_LAND, _HALT_DETAIL_REFUSED,
                                  _HALT_DETAIL_PREMATURE_EXIT)


# T-11770 (X-1189) — the PREMISE-FALSE markers a hand-written halt text uses, and the advisory that
# names the covering verb at the seam where that halt is WRITTEN. Homed here, beside the
# `refused(pre-claim)` reading it points at, so the surfacing and the reading it exists to produce
# cannot drift apart; `cli.cmd_event` is the one call site (SPEC-0007 §3 plumbing thinness).
#
# WHY IT HAD TO EXIST. `task refuse` (T-10291) is the governed pre-claim exit and it is named in the
# dispatch preamble, in the AGENTS capture-reflex corollary, and by `blocked-on-land` when that verb
# meets a genuinely unclaimed card. None of that reaches the path a worker actually takes at the
# moment of discovery: `bg_dispatch_halted` has NO dedicated code emit — it is HAND-emitted through
# the generic `event` verb — and that write said nothing about the refusal verb whatever the halt
# text confessed. X-1189 measured the consequence in a consumer on 2026-08-27: the author knew the
# rule well enough to CITE it in the halt text and still exited through the halt path, because the
# halt path is the one reachable at that moment. The card whose premise was false then reads as a
# STALLED worker (`launch-stall` — "never came up, re-dispatch") instead of `refused(pre-claim)`, so
# the controller loops the re-dispatch and re-derives the refusal by hand (the same 2/2 miss of
# 2026-07-10, T-10367/T-10368).
#
# NAMING, NOT ROUTING — the Analysis decision, and the bound on this whole surface. Auto-converting a
# hand-emitted halt into a refusal would take a classification the halt text cannot carry: a false
# positive would record `refused(pre-claim)`, i.e. "this card was never worked", for a worker that HAD
# worked — the exact false reading X-0740/X-0754 made `blocked-on-land` stop making. So this returns
# TEXT and nothing else. It writes nothing, reads no journal, moves no status, and its caller prints
# it beside the other report-only WARNs: a false positive costs one stderr line, never a lost halt and
# never a mis-recorded verdict. It likewise NEVER gates the capture reflex (D-0035/D-0086) — it does
# not judge `deviation_captured` at all.
_PREMISE_FALSE_HALT_MARKERS = (
    "premise false", "premise is false", "premise-false", "false premise",
    "pre-claim", "preclaim", "unmet precondition", "self-unsatisfiable",
)


# T-11775 (kupiclub X-1120's SECOND observation, made actionable by three MEASURED instances) — the
# `impact` values that READ as a description and are not one. T-11417's triageability test is
# PAYLOAD-IS-EMPTY, so `{fingerprint: <fp>, impact: "medium"}` is two non-blank values and warns
# about nothing; three inbound coordination items arrived that way and each cost the draining
# session a trip out of the coordination log, into the peer journal by origin_ref, and then into
# kernel SOURCE to reconstruct what the reporter meant. All three defects were real — one fails
# OPEN — so the silence was a near-miss on genuine findings, not a wasted item.
#
# THE LINE, and it is deliberately narrow: a fingerprint ALONE is genuinely enough to act on (that
# same session proved it by acting on three), so this does NOT demand more prose in general and does
# NOT fire on a payload that never reached for `impact`. What it rejects is an `impact` the author
# DID reach for and that carries no subject — blank, or a bare severity word. The vocabulary is the
# kernel's OWN severity list, imported from `error.ERROR_SEVERITIES` rather than re-typed, so a word
# added there is covered here with no second list to remember (E-0001). No speculative synonyms: the
# measured instances are exactly these words, and a wider list would start firing on real impacts.
def untriageable_impact(data: object) -> bool:
    """True when a caller payload's `impact` is PRESENT but carries no subject. PURE.

    Blank, or a bare severity token (`error.ERROR_SEVERITIES`). An ABSENT `impact` is False —
    fingerprint-only captures stay acceptable by design. Advisory only: the caller WARNs on this
    and still records, because capture is a reflex and is never gated (D-0035/D-0086).
    """
    if not isinstance(data, dict) or "impact" not in data:
        return False
    value = str(data.get("impact") or "").strip()
    if not value:
        return True
    # DEFERRED, not module-level (T-11540): `error` is not on journal's eager import set, and a
    # top-level `from lib import error` here would drag it into every narrow CLI path that touches
    # this module for nothing — the lazy-lib-import check measures exactly that and refused a land
    # over it. The import is inside the one function that needs it and only on the branch that needs
    # it; `sys.modules` makes the repeat cost nil.
    from lib import error   # noqa: PLC0415 — deliberate, see above
    return value.lower() in error.ERROR_SEVERITIES


# T-11890 — THE CAPTURE-CONTENT VOCABULARY, and the two views over it. The defect this closes is not
# which key is blessed: it is that each READER chose its own. Three in-repo readers of capture content
# existed and all three chose differently (`task.py#_capture_text` folded impact+finding,
# `cross.py#_deviation_briefs` preferred finding-then-impact, `triage.py#_scan_captures` normalized the
# two separately), so a capture whose prose lived under any other key read as EMPTY — the reported
# symptom was 53 rich captures read as empty before someone checked. The journal is APPEND-ONLY, so a
# write-side rule alone fixes nothing: 5967 existing rows keep their keys forever. The single-SoT unit
# is therefore the PARSER, not the field (external consult 2026-08-30, HIGH finding,
# decisions/capture-payload-content-key-vocabulary-audit-adhoc.yaml).
#
# THE ORDER IS MEASURED, NOT GUESSED — and the measurement is recorded HERE, per key, because a
# vocabulary justified by a truncated top-N list is a vocabulary partly chosen blind (audit-post
# 2026-08-30 caught exactly that: the tail keys were real but their evidence was not on the record).
# Over the full segment-aware history (archive/events-*.jsonl + events.jsonl, 5967
# deviation_captured + friction_captured rows), as `rows carrying it / of those, rows with no usable
# `impact``:
#     impact 5538/0 · what 363/176 · finding 239/2 · note 123/55 · why_it_matters 63/43 · where 61/29
#     detail 50/20 · evidence 47/20 · why 45/34 · fix 34/17 · suggested_fix 28/5 · summary 26/21
#     next 19/12 · resolution 18/12 · action 13/11 · remedy 12/9 · why_deviation 9/7 · scope 7/5
#     expected 4/3 · actual 3/3 · why_a_deviation 1/1
# 431 rows (7.2%) carry no usable `impact`; 276 of them carry content under one of the keys above,
# 154 are fingerprint-only (acceptable BY DESIGN — see `untriageable_impact`) and exactly ONE in 5967
# is genuinely contentless. EVERY key below is on that list — even the single-digit tail, which is
# deliberately kept: a key found on 1 row is still a capture that would otherwise read as empty, and
# the cost of carrying it is one tuple entry. There are no speculative synonyms, for the same reason
# `untriageable_impact` refuses to guess at severity words — a wider vocabulary starts matching noise.
# `content` measures 0/0 and is the ONE deliberate exception: it is not a historical author key at
# all but this accessor's OWN output key (see the idempotence note below). Adding a future alias is a
# one-line edit HERE, which is the growth this removes: no reader ever chooses again.
#
# `content` is FIRST so both views are IDEMPOTENT over their own output: `triage._scan_captures`
# stores the normalized value under that key, so a scanned ROW and a raw PAYLOAD can be passed to the
# same function. `impact` is second (the canonical write key), `finding` third (what `audit run`
# emits).
CAPTURE_CONTENT_KEYS = (
    "content", "impact", "finding", "what", "summary", "note", "detail",
    "why_it_matters", "why", "why_deviation", "why_a_deviation", "where",
    "fix", "suggested_fix", "remedy", "resolution", "next", "action",
    "evidence", "scope", "expected", "actual",
)


def _capture_content_values(data: object) -> list:
    """The non-blank capture-content values in `CAPTURE_CONTENT_KEYS` order. PURE.

    An `impact` that `untriageable_impact` rejects (blank, or a bare severity word) is SKIPPED and the
    fold falls through to the next key. That skip is what makes the accessor correct on the 237
    measured rows shaped `{"impact": "low", "finding": "<the prose>"}` — and it is exactly the
    finding-before-impact preference `cross.py` already had, preserved rather than reinvented.
    """
    if not isinstance(data, dict):
        return []
    skip_impact = untriageable_impact(data)
    out = []
    for key in CAPTURE_CONTENT_KEYS:
        if key == "impact" and skip_impact:
            continue
        value = str(data.get(key) or "").strip()
        if value:
            out.append(value)
    return out


def capture_content(data: object) -> str:
    """The ONE content string a capture carries — the first non-blank value in vocabulary order. PURE.

    Accepts either a raw `deviation_captured` / `friction_captured` `data` payload or an already
    normalized `triage._scan_captures` row. Returns '' when the capture carries no content at all,
    which the caller decides what to do with (`cross.py` falls back to the fingerprint) — this
    function never gates and never raises.
    """
    values = _capture_content_values(data)
    return values[0] if values else ""


def capture_text(data: object) -> str:
    """EVERY content value a capture carries, joined in vocabulary order, DE-DUPLICATED by value. PURE.

    The superset view, for a token/path matcher that wants all the signal rather than the single best
    string. The de-duplication is load-bearing, not tidiness: a scanned row carries the normalized
    `content` AND the source field it was normalized from, so a plain fold would emit the same string
    twice and inflate every match it feeds (audit-pre 2026-08-30, medium finding).
    """
    seen, out = set(), []
    for value in _capture_content_values(data):
        if value not in seen:
            seen.add(value)
            out.append(value)
    return " ".join(out)


# T-11880 — DERIVE the recurrence key a capture did not carry, so no capture is ever unroutable.
#
# THE DEFECT. `event deviation_captured` accepted a payload with NO `fingerprint` and returned
# success. Every routing carrier triage owns is keyed BY fingerprint — a task `cites:`
# (`triage._fingerprint_cites_index`), a cross `origin_fp` (`_cross_origin_fp_index`), an E-XXXX case
# file (`_error_fingerprint_index`) — so such a row could never be routed: `triage run` showed it,
# withheld it from `--complete`'s route set, and advanced the watermark past it anyway. 92 rows sat in
# the 2026-08-30 window in exactly that state, every one emitted through the sanctioned CLI path
# (`source: yitc-v2-cli`), which is what makes it a CONTRACT GAP and not operator error.
#
# WHAT IS LOST, stated honestly, because the answer shapes the remedy. The rows are NOT deleted — the
# journal is append-only and `journal query --grep` still finds every one of them. What is lost is
# their ROUTING: once the watermark passes, they never surface in a triage window again, so the
# obligation to disposition them evaporates silently. A silent evaporation, not a visible failure.
#
# THE DISPOSITION IS **DERIVE**, and the alternative was REFUSE. Refusing was the obvious answer and
# it is the wrong one here: this verb's own write block already says so three times over — capture is
# a one-command REFLEX (D-0035/D-0086), and gating it "would trade a useless row for a LOST one,
# which is strictly worse" (T-11417's WARN-not-refuse rationale, and T-10410's actor stamp degrades
# rather than blocks for the same reason). A refusal converts a fingerprint-less capture into NO
# capture, from an author who is mid-flight in other work and reached for the reflex precisely
# because it costs one command. Deriving keeps the row AND makes it routable, so the reflex pays
# nothing and triage gains a carrier. The report-only WARN this replaces was the third option —
# accept-and-complain — and it is exactly what the card removes: it landed the unroutable row anyway.
#
# TWO ARMS, and the split is the whole design.
#   CONTENT arm — fold the caller's own substantive payload. Two captures OF THE SAME DEVIATION
#   derive the SAME key, which is the recurrence property a fingerprint exists for (SPEC-0056 §1/§2
#   both KEY on it), so a derived key is a real recurrence key and not a unique row id.
#   ENVELOPE arm — when nothing substantive survives the fold, there is nothing to be stable ABOUT,
#   so the key is derived from the row's own envelope (ts + task + actor) and is UNIQUE per row. A
#   constant "contentless" key would have been simpler and is wrong: it would collapse every empty
#   capture in the corpus into ONE fingerprint class, fabricating a recurrence count in the hundreds
#   and making `_suggest_route` promote a phantom root. Unique-per-row keeps them individually
#   addressable (each can still be cited, routed, or promoted) while recurrence-matching nothing.
#   The envelope's own resolution is the journal's: `ts` is second-granular, so two CONTENTLESS
#   captures sharing one second, one task id and one actor derive one key. That is stated rather
#   than papered over with a nonce, because a nonce would make this function impure for no gain:
#   two payload-free captures from one actor in one second are INDISTINGUISHABLE rows — nothing
#   about either says which is which — so deriving one key for them loses no information a second
#   key could carry. The content arm, which is where real captures land, is unaffected.
#
# WHAT NEVER ENTERS THE DERIVED VALUE, and this is a spec obligation rather than a preference.
# SPEC-0025 §deviation_captured states three times that `captured_via`, `actor` and `exempted_case`
# are provenance/attribution ONLY and MUST NOT enter a fingerprint — "else recurrence fragments
# across sources", which would defeat the very property the content arm exists to provide. `kind` is
# excluded on the same reasoning from the other end: it is a CLOSED vocabulary decided at TRIAGE
# (SPEC-0056 §1), not at capture, so folding it would let one deviation derive two different keys
# depending on a judgement made later. `probe` and `remedy_ref` are read by triage as row METADATA
# (`_scan_captures` excludes probe rows outright).
#
# `impact` IS INCLUDED — CONDITIONALLY (the audit-pre YELLOW, absorbed mode-a). Excluding it
# wholesale was the first cut and it fails in the direction that matters: for many real captures the
# descriptive `impact` is the ONLY subject the payload carries, so dropping it pushes exactly those
# rows into the envelope arm, where two captures of one deviation derive different keys and never
# match. So the discriminator is the EXISTING `untriageable_impact` above (T-11775), reused rather
# than re-typed (CHARTER §P1 filter 1): a bare severity word carries no subject and stays out; a
# descriptive impact is subject and folds in.
#
# TOTAL BY CONSTRUCTION — it never raises, never returns empty, for any payload in any script. That
# is load-bearing, not defensive coding: this function is called on the capture path, so a derivation
# that could die would re-gate the reflex through the back door. It is why `textutil.slug` is NOT
# reused here despite being the repo's kebab-case helper — `slug` REFUSES on an untransliterable
# script (T-11164, deliberately), which on this path would refuse the capture. The readable stem is
# therefore best-effort ASCII and the sha256 suffix — computed over the canonical fold, never over
# the stem — carries the identity, so a payload with no ASCII at all still derives a stable, unique,
# perfectly routable key; it just reads as a hash.
_FINGERPRINT_EXCLUDED_KEYS = frozenset({
    "captured_via", "actor", "exempted_case",   # SPEC-0025: provenance/attribution, MUST NOT enter
    "kind",                                     # closed vocabulary, decided at TRIAGE not capture
    "probe", "remedy_ref",                      # triage row-metadata, not subject
    "fingerprint",                              # absent or blank by construction on this path
})
DERIVED_FINGERPRINT_PREFIX = "derived-"


def _fingerprint_stem(text: str) -> str:
    """A short readable ASCII stem for a derived fingerprint. PURE, TOTAL — never raises, may be ''."""
    ascii_only = "".join(c if (c.isascii() and (c.isalnum() or c in " -_/")) else " "
                         for c in text.lower())
    words = [w for w in re.split(r"[^a-z0-9]+", ascii_only) if w]
    stem = "-".join(words[:6])[:48].strip("-")
    return stem


def derived_fingerprint(caller_data: object, *, ts: str = "", task_id: object = None,
                        actor: object = None) -> str:
    """The recurrence key for a capture that carried none. PURE, TOTAL — see the block comment above.

    Returns `derived-<stem>-<hash8>` (content arm) or `derived-contentless-<hash8>` (envelope arm).
    Identical substantive payloads derive an identical key; a contentless payload derives a key
    unique to its row. Never raises and never returns an empty string, for any input.
    """
    content: dict = {}
    if isinstance(caller_data, dict):
        for key, value in caller_data.items():
            if key in _FINGERPRINT_EXCLUDED_KEYS:
                continue
            if key == "impact" and untriageable_impact(caller_data):
                continue          # a bare severity word is no subject (T-11775) — see the comment
            text = str(value).strip() if value is not None else ""
            if text:
                content[str(key)] = text
    if content:
        # sort_keys: the fold is over the payload's CONTENT, so two captures that spell the same
        # facts in a different key ORDER must derive the same key.
        canonical = json.dumps(content, sort_keys=True, ensure_ascii=False)
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:8]
        stem = _fingerprint_stem(" ".join(content[k] for k in sorted(content)))
        return f"{DERIVED_FINGERPRINT_PREFIX}{stem}-{digest}" if stem             else f"{DERIVED_FINGERPRINT_PREFIX}{digest}"
    envelope = json.dumps({"ts": str(ts or ""), "task_id": str(task_id or ""),
                           "actor": str(actor or "")}, sort_keys=True)
    digest = hashlib.sha256(envelope.encode("utf-8")).hexdigest()[:8]
    return f"{DERIVED_FINGERPRINT_PREFIX}contentless-{digest}"


def premise_false_halt_hint(event_type: str, data: object) -> str:
    """The advisory naming `task refuse` when a HAND-emitted halt confesses a false premise. PURE.

    Fires only on `bg_dispatch_halted` whose free `reason` carries a §_PREMISE_FALSE_HALT_MARKERS
    phrase AND which is not ALREADY the refusal (`kind: refused` — the discriminator
    `task.cmd_task_refuse` stamps and `_terminal_detail` reads at the `refused(pre-claim)` branch);
    re-advising a worker who already ran the verb would be noise on the one path that got it right.
    Returns '' for everything else, so the caller's decision is `if hint:` and nothing more.
    """
    if event_type != "bg_dispatch_halted" or not isinstance(data, dict):
        return ""
    if str(data.get("kind") or "").strip() == "refused":
        return ""
    reason = str(data.get("reason") or "").lower()
    if not any(marker in reason for marker in _PREMISE_FALSE_HALT_MARKERS):
        return ""
    return (
        "yitc-v2: NOTE this halt's reason reads PREMISE-FALSE, and a halt is not the exit for one. "
        "If you have NOT claimed this task (no `worktree new`), the covering verb is `yitc-v2 task "
        "refuse <T-XXXX> --reason <why>` — it records the SAME bg_dispatch_halted with `kind: "
        f"refused`, which `--fleet-verdict` reads as `{_HALT_DETAIL_REFUSED}` / needs-decision, and "
        "leaves the card `ready` and cleanly re-dispatchable. A bare halt here reads as `launch-stall` "
        "instead — «the worker never came up, re-dispatch it» — which loops the very dispatch your "
        "refusal exists to stop (T-10291 / SPEC-0133). If you HAVE claimed it, this is a POST-claim "
        "block: `yitc-v2 blocked-on-land <T-XXXX> <reason>`, worktree intact (SPEC-0103 §3). "
        "The halt row below IS recorded either way — this names the verb, it does not gate you."
    )
# T-11344 — the details whose class/detail `_terminal_detail` MINTS FROM a `bg_dispatch_halted`, i.e.
# exactly the rows whose reading is produced by a halt MARKER and therefore carries a marker clock of
# its own, distinct from the chain's last-event clock. A SUPERSET of the needing-decision set by one:
# `stopped(controller)` is equally marker-derived, and rendering ITS marker ts is a provenance fact,
# not a re-asked decision (the deliberate _HALT_DETAILS_NEEDING_DECISION omission above is untouched —
# a stopped row still never reaches the fleet-verdict halted/needs-decision branch). COMPOSED from the
# named carriers above, never re-typed literals, so no second hand-kept list can diverge (E-0001).
_HALT_DETAILS_MARKER_MINTED = (*_HALT_DETAILS_NEEDING_DECISION, _HALT_DETAIL_STOPPED)

# T-10792 — the LAUNCH-STALL cause detail read off the dispatch LOG. A launch-stall says only "launched,
# never came up"; every dead bootstrap collapsed into the single detail `no-claim-past-grace`, so an AUTH
# failure at launch (the worker process printed one line and exited before any worker code ran) was
# indistinguishable from a genuinely EMPTY log. Real incident 2026-08-08: three workers stopped in one
# session and the controller read all three as identical silent deaths; the logs held three different
# causes (`T-10790-0789e646…log` = "Not logged in · Please run /login", 35 bytes).
# Distinguishing them changes the remedy: an auth death re-dies identically on re-dispatch until the
# credential is restored, whereas an unexplained one is worth a re-dispatch.
# T-11352 — the un-landed-evidence provenance key stamped on an event admitted ONLY from a live
# worktree journal (never present on main). PRIVATE to the dispatch-status read path: it is set on a
# COPY of the parsed dict in memory, never written to any journal, and every JSON row is constructed
# field-by-field, so it cannot leak into a row unbidden.
DISPATCH_LOCUS_KEY = "_locus"

_STALL_DETAIL_NO_CLAIM = "no-claim-past-grace"
_STALL_DETAIL_AUTH = "auth-failure"
# The literal, lower-cased provider-authentication substrings. NARROW by construction: each is a phrase a
# provider CLI prints when it refuses to run for want of a credential — never a generic word like "login"
# or "auth", which a worker's own reasoning about an auth-shaped TASK would trip. Provider-neutral in kind
# (CHARTER §P4b): the set is a signature list, not a binding to one vendor.
_LAUNCH_AUTH_SIGNATURES = (
    "not logged in",
    "please run /login",
    "invalid api key",
    "authentication_error",
    "oauth token has expired",
    "invalid bearer token",
)
# T-11565 — the SECOND cause family, added on the terms the predicate's own docstring sets out (its own
# signature list, its own incident). MEASURED 2026-08-24T07:08:23Z: the dispatched worker for T-11447 died
# at bootstrap with the WHOLE launch log reading «API Error: 529 Overloaded. This is a server-side issue,
# usually temporary - try again in a moment.» — a transient, SELF-DESCRIBING, retry-able server condition
# that read as the generic `no-claim-past-grace`, whose standing advice («never came up — re-dispatch») is
# the wrong one at the wrong moment. The two causes need OPPOSITE handling: an auth failure needs a HUMAN
# (it re-dies identically until the credential is restored), an overload needs a WAIT and a retry.
_STALL_DETAIL_TRANSIENT = "transient-overload"
# The literal, lower-cased TRANSIENT-server substrings. Same NARROW construction as the auth list, and
# provider-neutral in KIND (CHARTER §P4b): each entry matches the SHAPE of a server naming its own
# condition as temporary — never a vendor brand, and never a bare numeric code (`529` is the incident's
# provenance, deliberately NOT a signature: a status number is a vendor's dialect, and the self-declared
# transience is the fact that routes the remedy). Deliberately excludes a bare "overloaded" / "try again",
# which a worker's own reasoning about a load-shaped TASK would trip.
# DASH-FREE BY CONSTRUCTION (measured, not stylistic): the incident text was quoted with an ASCII
# hyphen but the ACTUAL on-disk logs (.yitc/dispatch-logs/T-11447-64751cb5*.log, -7260ded4*.log) carry
# an EM DASH — «usually temporary — try again in a moment». A signature spanning the separator would
# have missed the very incident this arm exists for, so every entry stops at the phrase boundary.
_LAUNCH_TRANSIENT_SIGNATURES = (
    "usually temporary",
    "please try again in a moment",
    "temporarily overloaded",
    "server is overloaded",
    "service is temporarily unavailable",
    "overloaded_error",
)


def _launch_failure_signature(text):
    """T-10792 — the launch log's self-declared failure cause, or None. PURE + FAITHFUL: it reports only
    what the text literally says, and owns NO judgement about what a miss MEANS — per
    `lessons/fail-closed-belongs-to-the-reader-not-the-parser`, that judgement belongs to the reader (the
    launch-stall branch keeps the pre-existing generic detail on a None).

    Returns `_STALL_DETAIL_AUTH` when the text carries a provider-authentication signature,
    `_STALL_DETAIL_TRANSIENT` (T-11565) when it carries a SELF-DECLARED transient server-side condition;
    None for everything else — an empty log, an unreadable one (the caller hands None), a log the worker
    actually wrote, or a failure of some other kind. NOT a general log classifier: adding a THIRD cause
    means adding its signature list beside these, deliberately, with its own incident behind it.

    Auth is tested FIRST and its arm is UNCHANGED: the two families are disjoint in practice, and a
    credential failure is the one that cannot be waited out, so it wins any pathological overlap."""
    if not text:
        return None
    low = str(text).lower()
    if any(sig in low for sig in _LAUNCH_AUTH_SIGNATURES):
        return _STALL_DETAIL_AUTH
    if any(sig in low for sig in _LAUNCH_TRANSIENT_SIGNATURES):
        return _STALL_DETAIL_TRANSIENT
    return None

# T-10771 (SPEC-0133 rule 2d) — the RESOLVED-HALT reading. `bg_dispatch_halted` is append-only and
# nothing ever marks it resolved when its cause is CLEARED, so a halt whose story the journal already
# finished still read as an open owner-gated block. Real incident: T-10729 (2026-08-06) halted at
# 16:09:19 (needs_owner_reset, auto-consult RED), a second consult CONVERGED GREEN at 16:11:44, the
# granted pass went GREEN at 16:11:53 (a08dc26) and the task landed ok at 16:16:54 — and TWO later
# sessions still reconstructed that timeline BY HAND before concluding nothing was wrong (the
# 2026-08-06 hand-off carried it forward as an open forensic item). Measured over the real journal:
# of 266 halts, 80 are resolved by exactly this recorded path and leave no trace of it.
#
# DERIVED, not a superseding event (the card's fork, taken deliberately — CHARTER §P1 F1/F2): every
# resolution fact is ALREADY in the append-only journal, and a new event would need new EMIT SITES,
# which this change must not touch. It joins the reader's existing family of derived reconciles
# (T-9750 main-status, T-9766 land_ok, T-0606 live-claim, T-10095 newest-launch) as a fifth member.
_HALT_CONSULT_STAGE_PASS = {"consult-pre": "audit_pre_completed",
                            "consult-post": "audit_post_completed"}
_HALT_RESOLVED_BY_LAND = "land-ok"
_HALT_RESOLVED_BY_CONSULT = "consult-converged+granted-green-pass"
# T-11792 (SPEC-0133 rule 2d, arm (iii)) — a halt whose recorded cause was a RED MAIN, once main is green
# again. `undecidable` is the MAJORITY attribution (measured 2026-08-29: abort/undecidable 159,
# abort/branch 36, abort/main 27) and does NOT admit — only the literal `main` does.
_HALT_RESOLVED_BY_MAIN_GREEN = "main-green"
_HALT_MAIN_ATTRIBUTION = "main"

# T-12068 (SPEC-0119 rule 18 / SPEC-0133 rule 2d, arm (iv)) — the halt whose CARD was itself DISPOSED
# after the halt. A card REFUSED AT PRE-CLAIM (SPEC-0133 / T-10291) and then PARKED can satisfy none of
# the arms above, EVER: it never claims, so `task/<id>` never exists and no `land_completed` can carry
# that branch; it runs no audit stage, so no consult/pass pair exists; and its halt is `kind: refused`,
# never main-attributed. Measured on the kernel journal 2026-09-04 — T-10980 halted
# 2026-08-29T05:51:02Z (`kind: refused`, `pre_claim: true`), `task_parked` 06:06:03Z, zero land rows on
# its branch and there never will be. Unresolvable BY CONSTRUCTION, not by delay, so it sat on the rule-18
# debt line while `--dispatch-status` read the same halt as TERMINAL — two views of one engine
# disagreeing (CHARTER P7). The disposition IS the positively-recorded clearing of the cause.
#
# A MAP, not a set, because the `resolved_by` label carries WHICH disposition (`card-disposed:parked`),
# so a reader can tell a park (a return condition the owner holds) from a wont-do (a decision already
# made). The event names are the GOVERNED emitters and nothing else — `task.py` writes exactly these
# three; there is no `task_updated`-with-status form to match.
_HALT_RESOLVED_BY_CARD_DISPOSED = "card-disposed"
_HALT_CARD_DISPOSITION_TYPES = {
    "task_parked": "parked",       # `task park` / the park arm of `task pause`
    "task_wont_do": "wont-do",     # the status-set and the park-to-wont-do path
    "task_closed": "done",         # ordinary closure
}
# The REVERSAL, kept a SEPARATE constant rather than folded into the map above: an unparked card is not
# a disposition with a different label, it is the ABSENCE of one. This is the whole reason arm (iv) is
# decided at END OF SCAN instead of returning eagerly like arms (i)/(ii)/(iii) — a park later undone
# must leave the halt UNRESOLVED and visible, which an eager return could never express.
_HALT_DISPOSITION_REVERSAL_TYPES = frozenset({"task_unparked"})

# T-10858 (SPEC-0119 rule 18) — the predicate's DECLARED INPUT SURFACE: every event type
# `_halt_resolution` can match, and nothing else. Homed HERE, beside the predicate that owns it, so the
# two cannot drift: a future THIRD resolution arm adds its type here in the same edit, or the tripwire
# (tests/test_t10471_unmonitored_dispatches.py, the coupling pin) goes RED.
#
# Why it exists at all. Rule 18 drops the AGE bound — an unresolved halt stays visible however old it
# is — so its fold cannot pass `_dispatch_status_events` a `since` window. An UNBOUNDED read of the
# union costs seconds per journal (measured 3.47s / 252936 events on the engine journal, 2026-08-09),
# far too heavy for a surface riding session-start. This set is what replaces that bound: the reader is
# narrowed by TYPE, never by AGE (`_dispatch_status_events(include_types=…)`), which is exactly the
# substitution rule 18 makes — resolution, not recency, decides what is in scope.
#
# FAITHFULNESS, not cleverness: narrowing to these types is a no-op for the predicate's ANSWER, because
# every branch of `_halt_resolution` tests `type` against one of them. Adding a type here is harmless
# (a superset only costs time); OMITTING one would silently make a resolved halt read unresolved — a
# false ROW, which is the safe direction (a surfaced line costs a line; a wrong silence loses the
# signal) but still wrong, hence the pin.
HALT_RESOLUTION_INPUT_TYPES = frozenset({
    "bg_dispatch_halted",          # the halt itself (arm 0 — identity)
    "land_completed",              # arm (i) — the task's branch landed ok
    "external_audit_completed",    # arm (ii) first half — the converged consult
    "audit_pre_completed",         # arm (ii) second half — the granted GREEN pass (consult-pre)
    "audit_post_completed",        # arm (ii) second half — the granted GREEN pass (consult-post)
# T-12068 — arm (iv): the card's OWN terminal disposition, plus the reversal that cancels it. DERIVED
# from the two constants above rather than re-listed, so the declared input surface cannot drift from
# the arm that reads it (the same anti-drift reason the consult arm reaches its types through a map).
}) | frozenset(_HALT_CARD_DISPOSITION_TYPES) | _HALT_DISPOSITION_REVERSAL_TYPES

# T-11351 (SPEC-0119 rule 18) — the ATTRIBUTION reader's input surface: the resolution set PLUS the
# launch row, because "who dispatched this worker" is a join the resolution predicate never needed.
# A STRICT SUPERSET, and deliberately a SECOND constant rather than a widening of the first: the
# resolution bound is what `--fleet-verdict` and the re-dispatch brief read through, and admitting a
# type `_halt_resolution` cannot match would break the sibling's own stated contract ("every event type
# `_halt_resolution` can match, and NOTHING else") and the pin that guards it. Derived from that
# constant rather than re-listed, so a future third resolution arm reaches this reader for free.
#
# The cost of the extra type is the launch rows themselves, and it is bounded: on this repo's journal
# (2026-08-20, 361491 lines) `bg_dispatch_launched` is 2274 rows against the resolution set's ~18.7k —
# ~12% more, on a fold already measured at ~0.8s/journal. The signal axis is untouched: nothing is
# bounded by AGE here either, which is the whole of rule 18.
HALT_ATTRIBUTION_INPUT_TYPES = HALT_RESOLUTION_INPUT_TYPES | frozenset({
    "bg_dispatch_launched",        # the join row — `session_ref` dispatcher, `data.expected` worker
})


def _green(data, key="verdict") -> bool:
    """A verdict field reads GREEN, tolerating case/whitespace. Anything else — a missing key, a
    non-dict `data`, RED/YELLOW/ABORT — is NOT green (fail-closed by construction)."""
    if not isinstance(data, dict):
        return False
    return str(data.get(key) or "").strip().upper() == "GREEN"


def _newest_halt(events, task_id):
    """This task's NEWEST `bg_dispatch_halted` row, or None. PURE.

    Factored out of `_halt_resolution` by T-11351 so the attribution reader below selects the SAME halt
    the resolution predicate reports on, by the same rule, rather than re-scanning with a private one.
    A drifted second copy would let the debt line attribute one halt while resolving another — the two
    would silently disagree about which stopped worker they mean.

    Selection is unchanged from the original inline scan: `_dispatch_task_of` decides whose row this is
    (the one attribution the predicate matches on), ts compares lexicographically on the same ISO basis
    as every other scan in this module, and `>=` keeps the LAST of an equal-ts pair. A malformed row is
    skipped, never fatal."""
    if not task_id:
        return None
    halt = None
    for e in events or []:
        if not isinstance(e, dict):
            continue
        if e.get("type") == "bg_dispatch_halted" and _dispatch_task_of(e) == task_id:
            if halt is None or (e.get("ts") or "") >= (halt.get("ts") or ""):
                halt = e
    return halt


def _halt_dispatcher_session(events, task_id):
    """T-11351 (SPEC-0119 rule 18) — WHICH SESSION DISPATCHED the worker that halted on `task_id`?
    Returns the dispatching (controller) session ref, or None when it cannot be established. PURE:
    reads, never mutates, persists nothing.

    THE JOIN, AND WHY IT NEEDS NO NEW STORE. The journal already carries both ends and has all along;
    the rule-18 fold simply never performed the join:
      `bg_dispatch_halted.session_ref`      = the WORKER's own session ref
      `bg_dispatch_launched.data.expected`  = the ref `dispatch` ASSIGNED to the worker it spawned
      `bg_dispatch_launched.session_ref`    = the LAUNCHING controller's session
    So worker-ref -> the launch that assigned it -> that launch's session. Re-measured on this repo's
    journal before the design was committed to (2026-08-20, 361491 lines): 389 of 468 halts join to a
    dispatcher across 120 distinct dispatching sessions, 79 do not. Both halves of that measurement are
    load-bearing — the join is real AND it is incomplete, which is exactly why None is a first-class
    answer here rather than an error.

    NOT the task id. Attribution deliberately keys on the assigned session ref, never on `task_id`: a
    task can be dispatched more than once, and matching by task would hand a halt the dispatcher of a
    DIFFERENT launch. The expected-ref join names the one launch this worker actually came from. Where
    several launches carry the same expected ref (a duplicate the journal should not hold), the NEWEST
    at-or-before the halt wins — the launch this halt could have come from.

    FAIL-CLOSED TO None IN EVERY UNCERTAIN DIRECTION, which is the contract the caller depends on:
    no halt for the id, a halt with no/blank `session_ref`, no launch row carrying that expected ref, a
    launch with a blank dispatcher ref, a malformed row — all None. None means UNATTRIBUTABLE, and a
    caller must count it in its TOTAL while attributing it to NOBODY. Guessing here (falling back on
    the reading session, or on the task's most recent launch whatever its ref) would put someone else's
    halted worker in the reader's own column — the precise error the widened line exists to end, only
    inverted and harder to see.

    `events` may be scoped or unscoped, and must have been read with `HALT_ATTRIBUTION_INPUT_TYPES`
    (the resolution set plus `bg_dispatch_launched`) or the launch half is simply absent and every
    answer is a fail-closed None."""
    halt = _newest_halt(events, task_id)
    if halt is None:
        return None
    worker_ref = str(halt.get("session_ref") or "").strip()
    if not worker_ref:
        return None                       # a halt that names no worker joins to nothing
    hts = halt.get("ts") or ""
    launch = None
    for e in events or []:
        if not isinstance(e, dict) or e.get("type") != "bg_dispatch_launched":
            continue
        data = e.get("data")
        if not isinstance(data, dict):
            continue
        if str(data.get("expected") or "").strip() != worker_ref:
            continue
        ts = e.get("ts") or ""
        if hts and ts > hts:
            continue                      # a launch AFTER this halt did not spawn this worker
        if launch is None or ts >= (launch.get("ts") or ""):
            launch = e
    if launch is None:
        return None
    return str(launch.get("session_ref") or "").strip() or None


def _halt_main_attribution(events, task_id):
    """T-11792 (SPEC-0133 rule 2d, arm (iii)) — was this task's NEWEST halt caused by a RED MAIN, on the
    record? Returns None (not main-attributed / not establishable) or a dict {abort_ts, outcome, reason}.
    PURE: reads, never mutates, persists nothing (SPEC-0133 rule 1).

    WHERE THE ATTRIBUTION LIVES, and why NOT on the halt. Measured over this repo's journal (2026-08-29,
    242 `bg_dispatch_halted` rows): the halt payload carries NO structured attribution — the key census is
    reason/source/dispatch/task/stage/kind/blocked_on_land/worktree_intact/…, and a MAIN attribution
    appears only as PROSE inside `data.reason` ("ATTRIBUTION: MAIN", "main is RED on a cause outside this
    card's scope", …). Reading that prose is exactly the unreliable read the fail-closed arm must not make.
    The STRUCTURED fact sits ONE ROW EARLIER, on the land the worker halted over:
    `land_completed.data.failure_attribution` = {outcome: 'main'|'branch'|'undecidable', reason, …},
    computed by the land verify itself against the merge-base. Nobody types it, so it is EVIDENCE rather
    than a claim — the same standard `needs_owner_reset` meets for `_recorded_owner_gate` (T-11618).

    THE JOIN: `_newest_halt` selects the halt (never a private re-scan — the T-11351 rule, so this reader
    and `_halt_resolution` can never report on different halts), then the NEWEST `land_completed` for
    branch `task/<id>` AT-OR-BEFORE that halt's ts is the abort the worker halted over. At-or-before, not
    strictly-before: the abort and the halt are emitted seconds apart and an equal ts is ordinary.

    FAIL-CLOSED TO None IN EVERY UNCERTAIN DIRECTION (AC2), because a wrongly-admitted attribution
    SUPPRESSES a live halt — the one failure mode rule 2d is asymmetric against: no halt, no land row for
    the branch, a non-dict row / `data` / `failure_attribution`, a missing or non-`main` outcome
    (`branch` and `undecidable` both leave the halt UNRESOLVED), a land whose status is `ok`, a blank ts.
    Only the explicit literal `main` admits.

    `events` may be scoped or unscoped, but arm (iii)'s caller needs the UNSCOPED stream: `land_completed`
    carries no task_id and is matched BY BRANCH (the same requirement arm (i) states)."""
    if not task_id:
        return None
    halt = _newest_halt(events, task_id)
    if halt is None:
        return None
    hts = halt.get("ts") or ""
    branch = f"task/{task_id}"
    abort = None
    for e in events or []:
        if not isinstance(e, dict) or e.get("type") != "land_completed":
            continue
        data = e.get("data")
        if not isinstance(data, dict) or data.get("branch") != branch:
            continue
        if data.get("status") == "ok":
            continue                      # an ok land is not an abort the worker could have halted over
        ts = e.get("ts") or ""
        if not ts or (hts and ts > hts):
            continue                      # AT-OR-BEFORE the halt; a later abort is a different story
        if abort is None or ts >= (abort.get("ts") or ""):
            abort = e
    if abort is None:
        return None
    fa = (abort.get("data") or {}).get("failure_attribution")
    if not isinstance(fa, dict):
        return None                       # no recorded attribution — fail closed, never guess from prose
    if str(fa.get("outcome") or "").strip() != _HALT_MAIN_ATTRIBUTION:
        return None                       # 'branch' / 'undecidable' / missing — the halt stays live
    return {"abort_ts": abort.get("ts") or "", "outcome": _HALT_MAIN_ATTRIBUTION,
            "reason": str(fa.get("reason") or "").strip() or None}


def _halt_resolution(events, task_id):
    """T-10771 (SPEC-0133 rule 2d) — is this task's NEWEST `bg_dispatch_halted` RESOLVED by what the
    journal recorded AFTER it? PURE: reads, never mutates, persists nothing (SPEC-0133 rule 1).

    Returns None when the id has no halt in `events` (nothing to read); else a dict:
      halt_ts / reason  — the halt's own identity, straight off the event
      resolved          — bool
      resolved_by       — None | 'land-ok' | 'consult-converged+granted-green-pass' | 'main-green'
                          | 'card-disposed:<parked|wont-do|done>'
      resolved_ts       — the ts at which the resolution completed (None when unresolved)
      consult_ts / pass_ts / pass_type / land_sha — the supporting evidence, for the render
      card_disposition  — arm (iv)'s label ('parked' / 'wont-do' / 'done'), else None

    FOUR resolution arms, any sufficient, each judged STRICTLY AFTER the newest halt's ts:
      (i)  LAND — a `land_completed{status: ok}` for branch `task/<id>`. NOT a duplicate of the T-9766
           `_last_land_ok` reconcile: that one is last-outcome-wins AND re-claim-gated, so it reads
           False when a LATER unrelated abort follows the ok land — exactly the shape that leaves a
           resolved halt reading `halted`. `land_completed` carries NO task_id (only `data.branch`),
           so this arm matches BY BRANCH and callers must pass the UNSCOPED stream.
      (ii) CONSULT+PASS — the DESIGNED audit-loop-ceiling continuation: a CONVERGED consult
           (`external_audit_completed`, `data.stage` = consult-pre|consult-post, verdict GREEN)
           followed AT-OR-AFTER by THAT stage's granted GREEN pass (`audit_pre_completed` /
           `audit_post_completed`). Both halves are required: a converged consult alone only GRANTS
           the continuation — the granted pass may still come back RED.
      (iii) MAIN WENT GREEN (T-11792) — for a MAIN-ATTRIBUTED halt ONLY (`_halt_main_attribution`: the
           land the worker halted over recorded `failure_attribution.outcome == 'main'`), ANY
           `land_completed{status: ok}` on ANY branch. A land ok is a full verify passing against main,
           so it is the positively-recorded event that FIXES main — the halt's named cause, gone. Matches
           any branch on purpose: the whole point is that an outage halting N workers is cleared for all N
           by whoever fixes it, and the halted branch itself is by definition not landing. This arm is
           GATED on the attribution, never on the green event alone: a BRANCH-attributed or unattributed
           halt reads UNRESOLVED however many green lands follow it. Nothing here ages out on TIME —
           SPEC-0119 rule 18 is untouched.

      (iv) THE CARD WAS DISPOSED (T-12068) — a `task_parked` / `task_wont_do` / `task_closed` for THIS
           task, with no `task_unparked` after it. A card the journal records as parked, retired or done
           is AWAITING NO DECISION, and its halt's subject is precisely a decision still owed. Written
           for the shape no other arm can EVER reach: a PRE-CLAIM REFUSAL (`kind: refused`, SPEC-0133 /
           T-10291) never claims, so `task/<id>` never exists and arm (i) is unsatisfiable forever; it
           runs no audit stage, so arm (ii) is too; it is not main-attributed, so arm (iii) is gated off.
           Measured: T-10980, halted 2026-08-29T05:51:02Z and parked 06:06:03Z, sat on the SPEC-0119
           rule-18 debt line as needs-decision while `--dispatch-status` read the SAME halt as TERMINAL.
           THE ONE STRUCTURAL DIFFERENCE, and it is deliberate: this arm is decided at END OF SCAN
           rather than returning eagerly, so a LATER `task_unparked` can CANCEL it — an un-parked card
           is awaiting a decision again, and an eager return could not express that. The eager arms
           therefore keep PRIORITY: a halt that landed ok and was later closed still reads `land-ok`,
           which is the more specific answer.
           NOT a duplicate of the T-10873 reader-side card cross-check in `debt.unresolved_worker_halts`,
           and the two do not overlap: that one covers a disposition PRE-DATING the halt (measured
           T-0178 — card closed 08:58:45Z, land 08:59:32Z, halt 09:00:38Z), which a FORWARD-only
           predicate cannot see by construction and which therefore belongs to the reader. This arm
           covers the strictly-AFTER case, squarely inside what this predicate already reads, in the
           same ts direction as every arm above. Both views keep reading THIS one predicate (SPEC-0133
           rule 5 — no second classifier path), which is exactly why they can no longer disagree.
           Nothing here ages out on TIME either — SPEC-0119 rule 18 is untouched.

    FAIL-CLOSED IN EVERY DIRECTION, because suppressing a live halt is far worse than leaving a
    resolved one visible: a non-dict row, a missing/mistyped verdict, a non-task consult key (e.g.
    a plan's `consult-finalization`), a foreign branch, a non-ok land status, an unrecognised
    disposition type, a disposition at-or-before the halt ts, a disposition since REVERSED by a
    `task_unparked`, or any out-of-order ts all leave the halt UNRESOLVED. Per lessons/fail-closed-belongs-to-the-reader-not-the-parser this
    function stays FAITHFUL — it reports what the journal says — and each READER owns what the
    reading means for it.

    `events` may be scoped or unscoped: halt/audit rows are matched by `_dispatch_task_of` here, so an
    unscoped list is exact (and is what arm (i) needs). ts compares lexicographically — the same ISO
    basis as every other scan in this module."""
    if not task_id:
        return None
    halt = _newest_halt(events, task_id)
    if halt is None:
        return None
    hts = halt.get("ts") or ""
    hdata = halt.get("data") if isinstance(halt.get("data"), dict) else {}
    out = {"halt_ts": hts, "reason": str(hdata.get("reason") or "").strip() or None,
           "resolved": False, "resolved_by": None, "resolved_ts": None,
           "consult_ts": None, "pass_ts": None, "pass_type": None, "land_sha": None,
           "card_disposition": None}
    branch = f"task/{task_id}"
    # arm (iii) gate, computed ONCE before the scan: was this halt's cause a RED MAIN, on the record?
    # None for every other halt kind, which is what keeps the fail-closed default unchanged for them.
    main_attr = _halt_main_attribution(events, task_id)
    out["main_attribution"] = (main_attr or {}).get("reason") if main_attr else None
    out["main_green_ts"] = None
    # T-12273 (SPEC-0133 rule 2d, arm (ii)) — the PRE-CLAIM REFUSAL exclusion, computed ONCE before the
    # scan in the same shape as arm (iii)'s `main_attr` gate above. A halt the worker recorded as a
    # pre-claim refusal (`kind: refused` / `pre_claim` — the SPEC-0133 / T-10291 marker
    # `_terminal_detail` refinement (2) already reads) names a FALSE PREMISE as its cause, not an audit
    # ceiling. The ceiling continuation is the remedy for a ceiling; it is not the remedy for a premise,
    # so no consult+granted-pass pair can clear this halt HOWEVER GREEN — the card was never claimed and
    # the audit rows that follow it belong to a later, different attempt. Gating BOTH halves (not just
    # the return) means a refusal never even records a `consult_ts`, so no downstream reader can narrate
    # a continuation that did not resolve anything. Arms (i) land-ok, (iii) main-green and (iv)
    # card-disposed are DELIBERATELY untouched: each resolves a refusal on its own recorded ground, and
    # arm (iv) (T-12068) is the one written for precisely this shape.
    # Read off `hdata` — the newest halt this predicate ALREADY resolved — so there is no second scan
    # and no new reader. SIBLING, named so the two cannot drift silently: `debt._is_pre_claim_refusal`
    # (T-11679) tests the SAME marker for the rule-18 fold, but takes raw ROWS and re-finds the newest
    # halt itself, and journal.py is BELOW debt.py in the import order (debt is handed
    # `_halt_resolution`, not the reverse) — so importing it here would invert the layering to save two
    # lines. This admits `pre_claim` as well as `kind`, because the governed `task refuse` emit stamps
    # both and either alone is proof of the shape.
    pre_claim_refusal = (str(hdata.get("kind") or "").strip() == "refused"
                         or bool(hdata.get("pre_claim")))
    out["pre_claim_refusal"] = pre_claim_refusal
    consult_ts = consult_pass_type = None
    # arm (iv) accumulator — the STANDING card disposition, (ts, label). Not a `return` inside the loop:
    # a later `task_unparked` clears it back to None, so the answer is only final at end of scan.
    disposed = None
    for e in events or []:
        if not isinstance(e, dict):
            continue
        ts = e.get("ts") or ""
        if ts <= hts:                     # STRICTLY after the halt — a pre-halt GREEN resolves nothing
            continue
        etype, data = e.get("type"), e.get("data")
        data = data if isinstance(data, dict) else {}
        # arm (i) — the task's branch landed ok. Terminal for the halt's story: report and stop.
        if etype == "land_completed" and data.get("branch") == branch and data.get("status") == "ok":
            out.update({"resolved": True, "resolved_by": _HALT_RESOLVED_BY_LAND, "resolved_ts": ts,
                        "land_sha": data.get("sha")})
            return out
        # arm (iii) — a MAIN-attributed halt is cleared by the next land ok on ANY branch: main is green
        # again. Judged AFTER arm (i) so an own-branch land keeps its more specific `land-ok` reading.
        if (main_attr and etype == "land_completed" and data.get("status") == "ok"):
            out.update({"resolved": True, "resolved_by": _HALT_RESOLVED_BY_MAIN_GREEN, "resolved_ts": ts,
                        "main_green_ts": ts, "land_sha": data.get("sha")})
            return out
        if _dispatch_task_of(e) != task_id:
            continue
        # arm (ii), first half — a CONVERGED consult grants the ceiling continuation. NOT reached for a
        # pre-claim refusal (T-12273): the gate is applied HERE, at the first half, so such a halt never
        # records a `consult_ts` to be narrated later.
        if (not pre_claim_refusal and etype == "external_audit_completed"
                and str(data.get("stage") or "") in _HALT_CONSULT_STAGE_PASS and _green(data)):
            consult_ts, consult_pass_type = ts, _HALT_CONSULT_STAGE_PASS[str(data.get("stage"))]
            continue
        # arm (ii), second half — that stage's GRANTED pass came back GREEN.
        # T-12273 — the TIMESTAMP BELT: report resolved ONLY when BOTH supporting timestamps are REAL.
        # A resolution whose own evidence is absent is not a resolution, and this is the point at which
        # the pair is asserted rather than assumed. `consult_ts` is truthy by construction today (the
        # first half sets it from a row whose ts already passed `ts <= hts`), so this changes no reading
        # recorded on the journal — it is the belt that keeps a future refactor from re-opening the
        # class. On a falsy side we DO NOT resolve and DO NOT return: the scan continues, so a later arm
        # (a land ok, a card disposition) may still fire and an unresolvable read stays UNRESOLVED —
        # fail-closed in the predicate's own stated direction.
        if consult_ts is not None and etype == consult_pass_type and _green(data):
            if consult_ts and ts:
                out.update({"resolved": True, "resolved_by": _HALT_RESOLVED_BY_CONSULT,
                            "resolved_ts": ts, "consult_ts": consult_ts, "pass_ts": ts,
                            "pass_type": etype})
                return out
            continue
        # arm (iv) — the card's own terminal disposition, RECORDED here and DECIDED after the loop, so
        # the reversal below can cancel it. Last one wins: a park→unpark→park ends disposed.
        if etype in _HALT_CARD_DISPOSITION_TYPES:
            disposed = (ts, _HALT_CARD_DISPOSITION_TYPES[etype])
        elif etype in _HALT_DISPOSITION_REVERSAL_TYPES:
            disposed = None               # un-parked ⇒ awaiting a decision again ⇒ still UNRESOLVED
    # arm (iv), decided. Reached only when no eager arm fired, so `land-ok` / the consult pair /
    # `main-green` keep their more specific readings when both apply.
    if disposed is not None:
        dts, label = disposed
        out.update({"resolved": True,
                    "resolved_by": f"{_HALT_RESOLVED_BY_CARD_DISPOSED}:{label}",
                    "resolved_ts": dts, "card_disposition": label})
    return out


def _halt_resolution_how(hr):
    """T-12273 — the ONE narration of a `_halt_resolution` result: the "how" clause both surfaces
    print. PURE: reads the predicate's own return dict, mutates nothing.

    Returns None when `hr` is falsy or not resolved (there is nothing to narrate); else a clause naming
    the arm that ACTUALLY FIRED.

    WHY THIS EXISTS AS A FUNCTION, when the two call sites each already had the branch chain inline:
    they had DRIFTED, and the drift was the defect. Both were `if land-ok / elif main-green / ELSE
    consult`, so when T-12068 added arm (iv) (`card-disposed:*`) to the PREDICATE and gave it no render
    branch, both fell through to the else and narrated an arm that never ran. Measured on the kernel
    journal 2026-09-08: T-12231 self-halted 10:30:29Z (`kind: refused`, `pre_claim: true`) and its card
    was PARKED 10:56:42Z, so `_halt_resolution` correctly returned `card-disposed:parked` with
    `consult_ts`/`pass_ts` None — and `--fleet-verdict` reported «the ceiling continuation ran — consult
    CONVERGED GREEN @ None, granted pass GREEN @ None». No consult ever ran and no pass was ever
    granted. The false narration then MANUFACTURED a task cut against the wrong subject (the matcher),
    so the bug's cost was paid twice.

    TWO PROPERTIES CARRY THE FIX, and both are why a fifth arm cannot reproduce the class:
      * ARM-EXHAUSTIVE — every `resolved_by` the predicate can return has its OWN branch, and the tail
        is a FALLBACK that names the raw recorded value verbatim. An unrecognised arm therefore reads
        as itself; it can never be narrated as some other arm's story.
      * NO ABSENT VALUE IS EVER NARRATED AS A RECORDED FACT — the card's title claim, held UNIFORMLY
        ACROSS EVERY ARM. Each arm names a MOMENT as the fact that cleared the halt, so each renders
        only when its OWN required timestamp is present — `resolved_ts` for land-ok and card-disposed,
        `main_green_ts` for main-green, BOTH `consult_ts` and `pass_ts` for the consult. An arm whose
        moment is missing has no fact to report and falls to the fallback, which itself SUPPRESSES its
        `@ <ts>` clause when `resolved_ts` is absent. So no surface can print `@ None` by ANY path.
        (Guarding the consult arm alone left the other three able to, while this section claimed all
        of them — audit-post RED, 2026-09-08; the earlier audit-pre residual covered the fallback.)

    Wording is preserved verbatim from the two former inline chains ("branch LANDED ok (<sha>)",
    "consult CONVERGED GREEN", "main went GREEN again") — this is a de-duplication, not a re-wording,
    so the surfaces' pinned substrings are unchanged."""
    if not hr or not hr.get("resolved"):
        return None
    by = str(hr.get("resolved_by") or "")
    rts, sha, mgts = hr.get("resolved_ts"), hr.get("land_sha"), hr.get("main_green_ts")
    # EVERY arm is gated on ITS OWN required timestamp, uniformly — not just the consult one. Each of
    # these arms STATES A MOMENT as the fact that cleared the halt ("landed ok @ X", "main went green
    # @ X", "the card was parked @ X"), so an arm whose moment is absent has no fact to report and
    # falls to the raw-value fallback below rather than interpolating `None` into a sentence that
    # reads as evidence. Without this the no-absent-evidence contract held only for the consult arm
    # while the section CLAIMED every path (audit-post RED, 2026-09-08) — the claim now matches the code.
    if by == _HALT_RESOLVED_BY_LAND and rts:
        return ("its branch LANDED ok"
                + (f" ({sha})" if sha else "")
                + f" @ {rts}")
    if by == _HALT_RESOLVED_BY_MAIN_GREEN and mgts:
        attr = hr.get("main_attribution")
        return ("its cause was a RED MAIN (the land it halted over recorded "
                "failure_attribution.outcome=main"
                + (f": {attr}" if attr else "")
                + f"), and main went GREEN again @ {mgts}"
                + (f" (land ok {sha})" if sha else ""))
    if by.startswith(_HALT_RESOLVED_BY_CARD_DISPOSED + ":") and rts:
        # arm (iv), T-12068 — THE BRANCH THAT WAS MISSING. A card the journal records as parked,
        # retired or done awaits no decision, which is exactly what the halt's subject was.
        return (f"its CARD was {hr.get('card_disposition') or by.split(':', 1)[1]} @ {rts} "
                f"— the card awaits no decision")
    if by == _HALT_RESOLVED_BY_CONSULT and hr.get("consult_ts") and hr.get("pass_ts"):
        return (f"the ceiling continuation ran — consult CONVERGED GREEN @ "
                f"{hr.get('consult_ts')}, granted pass GREEN @ {hr.get('pass_ts')}")
    # FALLBACK — an arm this narrator does not know, or a consult read missing its evidence. Name the
    # raw recorded value and invent NOTHING; drop the `@` clause entirely when there is no ts to state.
    return (f"the journal records it resolved by {by or '(unrecorded)'}"
            + (f" @ {rts}" if rts else ""))


def _terminal_detail(terminal, DISPATCH_TERMINAL_DETAIL):
    """T-9618 — the detail label for a terminal dispatch event. STATIC per type
    (DISPATCH_TERMINAL_DETAIL), with FOUR refinements off the `bg_dispatch_halted` `data`:

    (1) `needs_owner_reset` — the LEGACY audit-loop-ceiling blocked-on-land STOP: a RECOVERABLE
    OWNER-gated block (the owner authorized ONE `audit --owner-reset` and the controller respawned),
    surfaced distinctly as `blocked_on_land(needs-owner)` rather than a plain `halt`. SPEC-0204 rule 6
    (T-12290) RETIRED that route, so no NEW row carries this key — the arm stays for the rows already
    on record, which really were halted under it.
    (1c) `residual_fingerprints` (T-12290) — the audit-loop-ceiling STOP as emitted now: the worker
    halts naming the ceiling row's residual fingerprints and the CONTROLLER records one typed
    `ceiling_decision` per residual, so it reads `blocked_on_land(needs-controller)` — the existing
    sibling reused, since its meaning is already «no owner clause governs it, the controller decides».
    (1b) `blocked_on_land` (T-10788) — the SPEC-0103 §3 escalation proper: the worker STOPPED rather
    than force a land and escalated TO THE CONTROLLER, worktree intact. No owner clause governs it, so
    it is surfaced as `blocked_on_land(needs-controller)`. Checked AFTER (1) deliberately: the two keys
    are meant to be exclusive (each emitter stamps ONE), and if a future emit carried both, the
    STRICTER owner reading wins — over-escalating is recoverable, under-escalating an owner-gated block
    is not. Collapsing the pair onto one label is what made a worker's principled STOP indistinguishable
    from an owner gate and sent controllers to the owner for a decision the owner does not own.
    (2) `kind: refused` (T-10291) — the PRE-CLAIM refusal a worker records with `task refuse`
    after analyzing a ready task it must not claim; surfaced as `refused(pre-claim)` so the controller
    reads a GOVERNED refusal, never a dead bootstrap (whose class is `launch-stall`, whose remedy is
    re-dispatch — running it over a refusal LOOPS: the X-0271 incident). Checked AFTER (1)/(1b), so a
    blocked-on-land block keeps its finer label even if a future emit carries both keys.
    (3) `kind: controller_stop` (T-10403 / SPEC-0133 rule 2c) — the governed `dispatch --stop` of a
    rogue/dead claim-less worker; surfaced as `stopped(controller)`, the ONE halt detail that is NOT in
    _HALT_DETAILS_NEEDING_DECISION: the controller ITSELF made this stop, so fleet-verdict must not
    re-ask it as needs-decision. Checked after (1)/(1b)/(2) on the same both-keys rationale.

    All four keep the dispatch CLASS `TERMINAL` (so none is a hang_suspect/dead-but-unlanded orphan —
    the worker emitted a contracted terminal before yielding) while giving the controller the finer
    routing signal. Reuses the EXISTING bg_dispatch_halted marker — no new event type.

    T-11618 — THIS FUNCTION STAYS EVENT-LOCAL, and that is exactly its limit. Refinements (1)/(1b)
    read the LATEST halt and nothing else, which is how the authority arm was lost: measured across
    four cards on 2026-08-25/26, `audit post` at its loop
    ceiling auto-emits a MACHINE-derived `bg_dispatch_halted{needs_owner_reset: true}`, and 30-90
    seconds later the worker hand-runs `blocked-on-land`, emitting a SECOND halt carrying
    `blocked_on_land: true` plus free text. The worker-authored row is newer, so it WON, and an
    owner-gated audit-ceiling block rendered `needs-controller` — telling a controller to push
    `--ack-repeated-abort` through a gate the owner holds. (T-11204 20:59:33Z/21:01:04Z; T-11529
    16:16:17Z/16:17:51Z; T-11566 21:58:59Z/22:11:53Z; T-11580 01:27:09Z/01:27:59Z — same shape, four
    times.) The remedy needs the WHOLE chain, not one event, so it lives OUTSIDE this function as
    `_owner_gated_detail` — applied by the reader to THIS function's result. Kept separate on
    purpose: (1)/(1b) stay a faithful reading of one row, and the cross-row derivation is a named,
    separately-testable step rather than a hidden flag on an event-local mapper.
    """
    typ = terminal.get("type")
    if typ == "bg_dispatch_halted":
        data = terminal.get("data")
        if isinstance(data, dict) and data.get("needs_owner_reset"):
            return _HALT_DETAIL_BLOCKED_ON_LAND
        # (1c) SPEC-0204 rule 6 (T-12290) — the audit-loop-ceiling halt as it is emitted NOW: it
        # carries `residual_fingerprints` and NO `needs_owner_reset`, because the continuation past
        # the ceiling is no longer an owner grant but the CONTROLLER's typed `ceiling_decision` per
        # residual. So it reads with the CONTROLLER sibling — reused verbatim, not a new label: that
        # constant's own documented meaning is «no owner clause governs it, so the controller
        # decides», which is exactly true of this halt. Checked AFTER (1) so a LEGACY row carrying
        # `needs_owner_reset` keeps the needs-OWNER reading it was written under — that halt really
        # was taken under the old route, and re-labelling history would misreport it.
        if isinstance(data, dict) and data.get("residual_fingerprints") is not None:
            return _HALT_DETAIL_BLOCKED_ON_LAND_CONTROLLER
        if isinstance(data, dict) and data.get("blocked_on_land"):
            return _HALT_DETAIL_BLOCKED_ON_LAND_CONTROLLER
        if isinstance(data, dict) and data.get("kind") == "refused":
            return _HALT_DETAIL_REFUSED
        if isinstance(data, dict) and data.get("kind") == "controller_stop":
            return _HALT_DETAIL_STOPPED
        # (4) `kind: premature_exit` (T-11926) — the worker DIED without authoring any terminal; the
        # row was written FOR it by the watcher that observed the death (rule 2f). Checked LAST on the
        # same both-keys rationale as (2)/(3): every arm above is a halt the worker itself authored,
        # and an authored halt must always keep its finer, self-reported label.
        if isinstance(data, dict) and data.get("kind") == "premature_exit":
            return _HALT_DETAIL_PREMATURE_EXIT
    return DISPATCH_TERMINAL_DETAIL[typ]


def _recorded_owner_gate(events, task_id, *, _dispatch_task_of):
    """T-11618 — is an OWNER-gated blocker RECORDED for this task and still standing? PURE (reads,
    never mutates, persists nothing — SPEC-0133 rule 1).

    The one owner-gated blocker in the dispatch path WAS the audit-loop ceiling, whose continuation
    was `audit post --owner-reset` (SPEC-0124). `audit.py` recorded it MACHINE-side as a
    `bg_dispatch_halted` carrying `needs_owner_reset: true` — nobody types that key, so it is evidence
    rather than a claim. This function answers whether such a record exists for `task_id` and has not
    since been CLEARED.

    SPEC-0204 rule 6 (T-12290) RETIRED that continuation, so no NEW row carries the key and this
    function reads only history. It is kept, not deleted: a card halted under the old route before the
    retirement still has a standing record, and reading it faithfully is what keeps a controller from
    silently treating a real past block as if it never happened. A card halted under the CURRENT route
    carries `residual_fingerprints` instead, has no owner gate, and correctly reads needs-controller.

    CLEARED BY (either, judged strictly AFTER the newest owner-gate record's ts):
      (i)  the granted continuation came back GREEN — an `audit_pre_completed` / `audit_post_completed`
           with a GREEN verdict for this task. The gate did its job; nothing is owed to the owner.
      (ii) the branch LANDED — a `land_completed{status: ok}` for `task/<id>`. Matched BY BRANCH
           because `land_completed` carries no scoped task_id, so callers must pass the UNSCOPED
           stream (the same requirement `_last_land_abort` / `_halt_resolution` arm (i) carry).

    FAIL-CLOSED, deliberately asymmetric: a non-dict row, a missing or unreadable verdict, an
    out-of-order ts — any of these leave the gate STANDING. This mirrors `_terminal_detail`'s own
    stated rule that where the two readings could disagree the STRICTER owner reading wins, and for
    the same reason: over-escalating is recoverable, under-escalating an owner-gated block is not.
    Per lessons/fail-closed-belongs-to-the-reader-not-the-parser this stays FAITHFUL — it reports what
    the journal says — and the reader owns what the reading means.

    ts compares lexicographically, the same ISO basis as every other scan in this module."""
    if not task_id:
        return False
    gate_ts = None
    for e in events or []:
        if not isinstance(e, dict) or e.get("type") != "bg_dispatch_halted":
            continue
        data = e.get("data")
        if not isinstance(data, dict) or not data.get("needs_owner_reset"):
            continue
        if _dispatch_task_of(e) != task_id:
            continue
        ts = e.get("ts") or ""
        if gate_ts is None or ts >= gate_ts:
            gate_ts = ts
    if gate_ts is None:
        return False
    branch = f"task/{task_id}"
    for e in events or []:
        if not isinstance(e, dict):
            continue
        ts = e.get("ts") or ""
        if ts <= gate_ts:            # strictly after the gate — a pre-gate GREEN clears nothing
            continue
        etype = e.get("type")
        data = e.get("data")
        data = data if isinstance(data, dict) else {}
        # (ii) the branch landed — terminal for the gate's story.
        if etype == "land_completed" and data.get("branch") == branch and data.get("status") == "ok":
            return False
        # (i) the granted continuation pass came back GREEN.
        if (etype in ("audit_pre_completed", "audit_post_completed")
                and _dispatch_task_of(e) == task_id and _green(data)):
            return False
    return True


# T-11926 — the bounded dispatch-log TAIL reader. The cause of a premature exit is in the worker's
# own `.yitc/dispatch-logs/<task>-<ref>.log` and NOTHING read it: T-10792's docstring records that
# hole verbatim, and the 2026-08-12 wave's capture says the cause «was visible only by reading the
# dispatch log». So the halt row carries the tail, and this is the only new reader it needs.
#
# BOUNDED BY CONSTRUCTION: `seek` to the last `nbytes` and read to EOF, so a multi-megabyte worker log
# is never loaded. Decoding goes through the EXISTING `events._byte_tail` primitive (CHARTER §P1 F1 —
# the same byte-bounded tail the audit/plan stdout-tail paths already use), which drops a partial
# leading UTF-8 sequence rather than raising. FAIL-OPEN: a missing/unreadable/empty log returns "" —
# an absent log must never suppress the halt row, because the death is the fact and the tail is only
# its explanation.
_DISPATCH_LOG_TAIL_BYTES = 4096


def _dispatch_log_tail(path, *, nbytes: int = _DISPATCH_LOG_TAIL_BYTES) -> str:
    """Last `nbytes` bytes of a dispatch log, decoded. "" when absent/unreadable (fail-open)."""
    if not path:
        return ""
    try:
        p = Path(path)
        size = p.stat().st_size
        with p.open("rb") as fh:
            if size > nbytes:
                fh.seek(size - nbytes)
            raw = fh.read()
    except OSError:
        return ""
    return events._byte_tail(raw.decode("utf-8", "ignore"), nbytes)


def _premature_exit_finding(evs, task_id, *, _task_of, log_tail_fn, now_iso,
                            confirmed_death_basis: str, _task_is_terminal=None):
    """T-11926 (X-1208, SPEC-0133 rule 2f) — PURE predicate: does this task's newest dispatch describe
    a worker that DIED without authoring any terminal? Returns the `bg_dispatch_halted` payload to
    record, or None. Emits nothing, persists nothing, opens nothing except through `log_tail_fn`
    (injected, so the predicate stays hermetically testable) — it is a pure function of the events it
    is handed plus that reader, exactly like every other reader in this module (SPEC-0133 rule 1).

    TAKES THE **UNSCOPED** EVENT STREAM, and resolves ids with `_task_of` (the `_event_task_of` shape).
    This is not a convenience: `land_completed` carries NO `task_id`, only `data.branch` — the same
    trap T-10771 names on the resolved-halt arm. Handed a task-SCOPED list the land row would be
    absent and every landed worker would read as a premature exit; matching `land_completed` without
    resolving its branch would let ANY land in the fleet suppress this task's row. One resolver, both
    directions.

    FAIL-CLOSED ON EVERY AXIS — a spurious row would mark a LIVE worker's task re-dispatchable
    (`bg_dispatch_halted` is in DISPATCH_TERMINAL_TYPES), so each condition is asserted POSITIVELY
    here and none is inherited from the caller's control flow:
      (a) a `bg_dispatch_launched` exists for this id (a never-launched id can never have died);
      (b) NO `bg_dispatch_halted` at-or-after that launch — the worker authored no terminal of its
          own, and this is ALSO what makes the recorder IDEMPOTENT: once the row exists the next tick
          sees it here and returns None, so no second row can be written;
      (c) NO `land_completed` and no `task_closed`/`task_wont_do` at-or-after that launch — a worker
          that exits AFTER landing exited NORMALLY. This is AC1's differential;
      (d) the caller passes a CONFIRMED-death basis (the fleet reader's own judgement that the proc
          is gone with no live child and no consumer-locus liveness). The liveness call is NOT
          re-implemented here — one classifier path, never a second (SPEC-0133 rule 5);
      (e) the CARD ITSELF is not already terminal (`_task_is_terminal`). Conditions (b)/(c) read the
          JOURNAL WINDOW, which is anchored at the newest launch — so a RE-dispatch of an
          already-done task has a launch with genuinely nothing after it and satisfies them both.
          Measured on this repo's own journal (2026-09-01, 14-day fold, 686 launched ids): T-11284
          and T-11289 were re-dispatched on 2026-08-19 hours AFTER they closed and landed on
          2026-08-18, and (b)/(c) alone reported both as premature exits. Their workers did come up
          and exit — but a DONE card needs no controller decision, so a row there is noise. This is
          the card's own AC1 wording ("with its task NON-TERMINAL") which (b)/(c) do not express.
          In production the caller's class gate already blocks this (the fleet reader classifies a
          landed task TERMINAL, so those ids never reach here — which is why the live production
          run returned zero); the condition is asserted HERE too so the predicate does not depend on
          a caller's guard for a condition of its own. Direction: only a POSITIVE terminal read
          suppresses — an absent/unreadable/un-injected probe proceeds, because silencing every real
          death on an unreadable card would be the worse failure, and the caller's class gate is the
          primary guard.

    THE EXIT STATUS, HONESTLY. A dispatched worker is reparented onto init by
    `cli._spawn_detached_from_caller_tree` (T-11906) precisely so a descendant-tree kill cannot reach
    it — so it is nobody's child and NO waiter anywhere can read its exit code. The payload therefore
    carries `exit_status: null` WITH `exit_status_unavailable` naming why, beside the death evidence
    that IS observable. Recording the impossibility is strictly more than the silence it replaces;
    omitting the field, or synthesising a code, would each be worse.
    """
    launch = None
    for e in evs:
        if e.get("type") == "bg_dispatch_launched" and _task_of(e) == task_id:
            launch = e                                    # (a) newest launch wins
    if launch is None:
        return None
    lts = launch.get("ts") or ""
    for e in evs:
        if (e.get("ts") or "") < lts or _task_of(e) != task_id:
            continue
        if e.get("type") == "bg_dispatch_halted":         # (b) authored terminal / already recorded
            return None
        if e.get("type") in ("task_closed", "task_wont_do"):
            return None
        if e.get("type") == "land_completed":             # (c) landed → NORMAL exit (AC1 differential)
            return None
    if _task_is_terminal is not None and _task_is_terminal(task_id):   # (e) the card is already done
        return None
    data = launch.get("data") if isinstance(launch.get("data"), dict) else {}
    return {
        "dispatch": task_id,
        "kind": "premature_exit",
        "expected": data.get("expected"),
        "reason": (f"dispatched worker for {task_id} is CONFIRMED gone but authored no terminal — "
                   f"it neither landed nor halted, so its work (if any) is un-landed and its cause "
                   f"is in the dispatch log tail below, not in this journal"),
        # THE EXIT-STATUS STRAND — see the docstring. Unavailable BY DESIGN, and said so on the row.
        "exit_status": None,
        "exit_status_unavailable": ("the worker is reparented onto init by "
                                    "_spawn_detached_from_caller_tree (T-11906) so it is nobody's "
                                    "child and no waiter can observe its exit code"),
        # THE DEATH EVIDENCE that IS observable — so a reader never re-greps for it.
        "pid": data.get("pid"),
        "proc_alive": False,
        "confirmed_death_basis": confirmed_death_basis,
        "observed_at": now_iso,
        "log": data.get("log"),
        "log_tail": log_tail_fn(data.get("log")),
        "launched_at": lts,
    }


def _owner_gated_detail(detail, events, task_id, *, _dispatch_task_of):
    """T-11618 — upgrade a `blocked_on_land(needs-controller)` detail to the needs-OWNER reading when
    an owner gate is RECORDED for this task and still standing. PURE.

    This is the cross-row half of the authority arm. `_terminal_detail` mints the detail from ONE
    event, faithfully — and that is precisely why the arm was lost: the worker's hand-run
    `blocked-on-land` is the NEWEST halt, so it won over the audit-ceiling's own machine-emitted
    `needs_owner_reset` row seconds earlier. Applied HERE, by the reader that holds the whole
    UNSCOPED stream, so the event-local mapper stays event-local and the derivation stays a named,
    separately-testable step.

    NARROW BY CONSTRUCTION — it only ever moves a detail WITHIN the blocked-on-land pair, in the
    STRICTER direction. Every other detail (`halt`, `refused(pre-claim)`, `stopped(controller)`, and
    the needs-owner reading `_terminal_detail` already minted) is returned untouched: those are
    different questions, and rule (1) already answers this one when the latest halt carries the key.
    Because it only ever tightens, it cannot mask a block — the failure mode it is guarding is a
    controller pushing a continuation through a gate the owner holds."""
    if detail != _HALT_DETAIL_BLOCKED_ON_LAND_CONTROLLER:
        return detail
    if _recorded_owner_gate(events, task_id, _dispatch_task_of=_dispatch_task_of):
        return _HALT_DETAIL_BLOCKED_ON_LAND
    return detail


def _derived_halt_cause(events, task_id, *, _dispatch_task_of):
    """T-11618 — the ROUTING CAUSE for a halted dispatch, DERIVED from the machine record. PURE.
    Returns a member of DISPATCH_CAUSE_TAGS — always, the vocabulary is CLOSED.

    WHAT THIS REPLACES. The cause used to be minted by lowercasing the halting WORKER's free-text
    `reason` (plus `ra_key`) and substring-matching it into three buckets. The worker was being asked
    to re-author, by hand, a truth the journal already held: `land_completed` carries `abort_class`
    over a closed machine vocabulary, stamped at the `_die` origin. Measured over ~24h across five
    cards, that hand authorship mislabelled six halts — T-11566 and T-11580 both read
    `cause=verify-flake` ("may self-resolve on retry") while their newest recorded land abort was
    `rebaseline-unauthorized`, which re-fails identically forever. Nothing flaked in any of the six.

    DERIVATION, in priority order:
      (i)   the newest UNRESOLVED land abort for branch `task/<id>` — read via the EXISTING
            `_last_land_abort` (CHARTER §P1 F1: extend the reader that already answers this, do not
            add a parallel one). It is already cleared by a later ok land, so a landed branch carries
            no pending cause. Its `abort_class` when that class is an ADMITTED member, else
            `unmapped`; an abort row carrying no `abort_class` at all → `unknown`.
      (i-b) else the newest RED `land_member_verdict` for that branch WITHIN the current attempt
            (`_last_red_member_verdict`, T-11682) — a land that DIED wrote no abort row, so arm (i)
            is silent for the one failure mode that leaves nothing behind; its batch's member rows
            hold the cause. `verify-failed` ONLY when that row names failing assertions
            (`red_assertions`), else fall through — the tag is evidence-derived, never a bucket.
      (ii)  else an unresolved owner gate (`_recorded_owner_gate`) → `audit-ceiling`.
      (iii) else `unknown` — an EXPLICIT no-record reading, never a fallback onto a substantive class.

    The land arm outranks the audit arm ON PURPOSE, and the two are not competing answers: this is
    WHAT blocks the land, while `_recorded_owner_gate` separately answers WHO clears it. A card can
    (and in all four measured pairs does) carry both — a standing audit-ceiling gate AND a concrete
    land refusal — and the reader is told both facts rather than one of them twice.

    The worker's free text is read by NOTHING here. It survives as a non-routing detail, rendered
    beside the derived cause by `cmd_journal_fleet_verdict` (its evidence value is unchanged; only its
    authority as the routing key is removed).

    `events` must be the UNSCOPED stream — arm (i) matches `land_completed` by branch."""
    abort = _last_land_abort(events, task_id)
    if isinstance(abort, dict):
        klass = str(abort.get("abort_class") or "").strip()
        if not klass:
            return _CAUSE_UNKNOWN
        return klass if klass in DISPATCH_CAUSE_LAND_CLASSES else _CAUSE_UNMAPPED
    # (i-b) T-11682 — the land DIED instead of aborting, so arm (i) found nothing; its batch's own
    # member verdicts hold the cause. Runs only when arm (i) is silent, so nothing that already
    # resolves changes, and it is bounded to the CURRENT attempt by `_last_red_member_verdict`.
    #
    # THE VOCABULARY STAYS CLOSED AND THE TAG IS EVIDENCE-DERIVED, NEVER GUESSED. `verify-failed` is
    # an existing member of DISPATCH_CAUSE_LAND_CLASSES, and the ONLY input that can produce it here
    # is a row whose `red_assertions` literally names failing assertions. A red that surfaced no
    # assertion text — a verify TIMEOUT, an unnamed failure — carries no such key and falls through to
    # `unknown` rather than being labelled: absent means UNRECORDED, the same discipline
    # `_land_mark_red_assertions` applies at the writing end. That is what keeps this arm from
    # becoming the catch-all the retired `verify-flake` bucket became (T-11618).
    #
    # IT ATTRIBUTES NO CULPRIT. `cause=` answers WHAT blocked the land, never WHOSE change it was —
    # the attribution question is T-11612's and stays on the member rows, fail-closed.
    _red = _last_red_member_verdict(events, task_id)
    if isinstance(_red, dict) and _red.get("red_assertions"):
        return "verify-failed"
    if _recorded_owner_gate(events, task_id, _dispatch_task_of=_dispatch_task_of):
        return _CAUSE_AUDIT_CEILING
    return _CAUSE_UNKNOWN


# T-9751 — the controlled cause-tag vocabulary. SINGLE HOME (audit-pre F1: no dual truth surface):
# the named constants below derive from this ONE tuple, so no tag string is ever re-typed, and
# bin/yitc-v2 RE-EXPORTS this (never redefines it).
#
# T-11618 — the vocabulary is now DERIVED-FACING, not authored-facing. It used to be three buckets a
# WORKER's free-text halt `reason` was substring-matched into ("verify-flake", "audit-ceiling",
# "owner-gate"); both retired members are named below with the ground for retiring them, because a
# controlled vocabulary that loses a member without saying why reads as a rename.
#   RETIRED "verify-flake" — it won on a bare "verify"/"test" substring of worker prose, so it
#     absorbed everything the other two did not name and became a catch-all. Measured 2026-08-25/26
#     across five cards: SIX halts labelled verify-flake or needs-controller where NOTHING flaked —
#     T-11566 and T-11580 both read cause=verify-flake while their newest recorded land abort was
#     `rebaseline-unauthorized` (deterministic, re-fails identically on retry). A controller routing
#     on "may self-resolve on retry" there re-runs an 8-11 minute verify against a cause a prior pass
#     already surfaced — the CHARTER §Principle 7 freeze class.
#   RETIRED "owner-gate" — the residual bucket. Its own T-10788 note already recorded that its name
#     misdescribed who authorizes (the `--ack-repeated-abort` continuation it covered is cleared by
#     the CONTROLLER, not the owner). The authority question is answered by the DERIVED arm
#     (`_recorded_owner_gate` → the needs-owner / needs-controller detail), never by a cause literal,
#     so the residual bucket has nothing left to carry.
#
# The members below are the MEASURED BOUND (SPEC-0133): the eight `abort_class` literals the five
# cited branches actually recorded in `land_completed`, plus the audit arm, plus two STRUCTURAL
# members. The widening deliberately EXCLUDES every other `abort_class` literal the engine can stamp
# that no measured case produced — `on-main`, `self-land`, `spike-branch`, `detached-head`,
# `not-worktree`, `no-main-worktree`, `rebaseline-policy-off`, `bookkeeping-fold-failed`,
# `uncommitted-dirt`'s work-batch peers and the rest: they are real classes, but admitting a member
# no measured case needed is exactly the speculative widening CHARTER §P1 F4 defers.
#
# The vocabulary is CLOSED — `_derived_halt_cause` returns a member of DISPATCH_CAUSE_TAGS and
# nothing else (audit-pre finding, 2026-08-26). That is what the two structural members are for, and
# neither is a catch-all: `unknown` means NO blocker is recorded at all, `unmapped` means a class WAS
# recorded and is outside the admitted set — it names the gap instead of absorbing it, and the raw
# class survives beside it as a non-routing detail (the same treatment the worker's free text gets).
DISPATCH_CAUSE_LAND_CLASSES = ("verify-failed", "verify-timeout", "rebaseline-unauthorized",
                               "repeated-abort-backstop", "merge-non-union-conflict",
                               "audited-diff-stale", "corpus-integrity", "uncommitted-dirt")
_CAUSE_AUDIT_CEILING = "audit-ceiling"   # the audit-loop-ceiling STOP — needs owner --owner-reset
_CAUSE_UNKNOWN = "unknown"               # structural: no recorded blocker for this branch/task
_CAUSE_UNMAPPED = "unmapped"             # structural: a recorded class outside the measured bound
DISPATCH_CAUSE_TAGS = (_CAUSE_AUDIT_CEILING, *DISPATCH_CAUSE_LAND_CLASSES,
                       _CAUSE_UNKNOWN, _CAUSE_UNMAPPED)

# T-10130 — clock-skew tolerance for the recency signal (SPEC-0133 rule 2). An event ts more than
# this far AHEAD of `now` is treated as spurious (a far-future 2098/2099 sentinel row), NOT a fresh
# recency signal — so it cannot mask a true worker death as settling (F3b MISSED-TRUE-DEATH). Sized
# to swallow benign cross-machine clock skew while excluding any genuinely far-future row.
_DISPATCH_FUTURE_SKEW_SEC = 5 * 60

# T-10387 — tail-window physical read for the recency status readers. Every recency reader
# (`--dispatch-status` / `--fleet-verdict` / `--dispatch-readiness` / `--lifecycle-integrity`)
# funnels through `_dispatch_status_events` with a `since = now - WINDOW`; the fold used to parse
# the WHOLE journal (main events.jsonl is ~85MB / 200k lines) from byte 0, costing 11-15s/call
# (deviation status-readers-scan-full-85mb-journal-per-call; 818 calls / 2.66h CPU 2026-07-10;
# owner_directive 2026-07-11 item 2). When `since` is set the physical read is bounded to the TAIL
# newer than the cutoff. The classification recency thresholds are 15/30min — far tighter than the
# 24h window — so the coarse window pre-filter can be tail-bounded without changing any verdict.
# Full-history queries (`journal query` by type/task, prior-art / owner_directive recovery) do NOT
# pass a `since` here and stay full-read.
_TAIL_WINDOW_MARGIN_SEC = 24 * 60 * 60   # TIME margin: a line counts as in-window for the boundary
                                         # if ts >= since - this (>> observed ~4-5h land-fold/skew disorder)
_TAIL_WINDOW_BLOCK = 1 << 20             # backward physical read block (1 MiB)
_TAIL_WINDOW_CONFIRM_BYTES = 4 << 20     # purely-old bytes required PAST the lowest in-window line
                                         # before cutting — absorbs an old land-folded batch (append
                                         # disorder is the hazard; audit-pre RED T-10387)

# T-12129 — the SHARED-PREFIX offset, the sibling of the tail window above and the SECOND way this
# fold narrows a physical read. The tail window asks "how far back does my time window reach"; this
# asks "how much of this leg is a byte-for-byte copy of the leg beside it". Both answer in the same
# currency (a line-aligned byte offset into the live segment) and both fail open to 0.
_SHARED_PREFIX_BLOCK = 1 << 22           # forward compare block (4 MiB) — sized for a memcmp, not for
                                         # the backward seek-and-parse the tail window does


class _PrefixStart(int):
    """The `with_tail=True` answer: STILL THE BYTE OFFSET (an `int`), with the bytes above it attached.

    WHY AN INT SUBCLASS AND NOT A TUPLE (T-12208). `_shared_prefix_start` answers ONE question — the
    offset past the shared prefix — and three pinned suites read it as exactly that: they wrap it with
    a test double that passes `**kw` through, compares the answer with `> 0`, and substitutes a plain
    `0` to bypass the narrowing (test_t12129, test_t12205, test_t12031's siblings). Returning a tuple
    under a keyword would silently change the primitive's TYPE for every one of those readers while
    leaving its contract nominally intact — the shape breaks at the double, not at the call site, so
    the failure lands in a stale-looking assertion rather than on the change that caused it. An int
    subclass keeps the answer an offset (every arithmetic, comparison and truth test is unchanged, and
    a plain `0` substituted by a double still reads as fail-open) and carries `.tail` as what it is:
    the caller's own next read, taken one moment earlier on the handle that was already open. Read the
    bytes with `getattr(answer, "tail", None)` — the `None` default IS the from-byte-0 path.

    NOT A CACHE (SPEC-0190 rule 10), on the same standing as the offset itself: nothing is stored or
    keyed, and the object lives exactly as long as the caller's own expression."""

    def __new__(cls, start, tail=None):
        obj = super().__new__(cls, start)
        obj.tail = tail
        return obj


def _shared_prefix_start(path, other, *, block=_SHARED_PREFIX_BLOCK, with_tail=False):
    """Byte offset past the longest COMPLETE-LINE prefix `path` shares byte-for-byte with `other`.

    WHAT IT IS FOR (T-12129). `_dispatch_status_events` unions the live worktree journals with main's,
    and each worktree journal is ~99.9% a copy of main's: the whole of that copy is read, parsed, and
    then thrown away by the identity dedup, to recover a handful of un-landed rows at the tail. This
    returns the offset past the copied part, so the leg starts where it stops being a copy. Every byte
    below the answer is IDENTICAL to `other` at the same offset, so a caller that also reads `other`
    over that region loses no row — which is the whole of the correctness argument, and why the
    comparison is against the OTHER LEG rather than against a git revision.

    WHY NOT THE MERGE-BASE BLOB SIZE, which is the shortcut this reader exists instead of (measured
    2026-09-05, deviation `dispatch-status-merge-base-blob-size-is-not-a-byte-prefix-of-the-worktree-
    journal`). `events.jsonl` carries the `merge=union` git attribute, and that driver resolves an
    append-vs-append conflict as base + OURS-tail + THEIRS-tail — so main's blob at the merge-base is
    NOT a prefix of the merged worktree file. On this repo the blob was a true prefix in only 2 of the
    9 live worktrees; the other 7 diverged 0.2-2.8 MB BELOW the blob size, and a size-derived offset
    would have skipped worktree-only rows. The shared row-frontier is therefore VERIFIED, never
    asserted — which costs one bounded memcmp over the shared span (0.57 s across 9 worktrees on this
    repo) in place of a full json parse of it (5.11 s over the same 9).

    FAIL-OPEN, the same standing as `_tail_window_start`: a missing file, an unreadable one, any
    OSError, or a divergence before the first newline all return 0 — read from byte 0, exactly as
    before. It NEVER returns an offset mid-line (the answer is always just past a `\n`), so the
    caller's first line is whole.

    NOT A CACHE (SPEC-0190 rule 10). Nothing is stored, keyed or remembered: the answer is recomputed
    from the two files on every call, and is a NARROWER SLICE of the read the caller was already
    doing. It reports its own physical read through `note_fold` with ZERO rows parsed, because it
    parses none — a nonzero rows figure here would be a number nobody measured.

    SEGMENT HORIZON (SPEC-0190 rules 4/6). This is a PHYSICAL-POSITION question about the LIVE
    segment, the class rule 6 names and the standing `_tail_window_start` already holds — it locates a
    byte inside one file and reads nothing else. Whether the ARCHIVE segments beside that file may
    also be skipped is a DIFFERENT question this function does not answer and its caller does not ask.

    `with_tail` (T-12208, SPEC-0190 rule 10) — ONE PHYSICAL OPEN PER ARTIFACT. Every caller that takes
    this offset then READS the file from it, which was a SECOND open of an artifact this function has
    already opened: measured 2026-09-07 inside one scoped `session start`, 64 prefix-probe opens and
    17 bounded-superset opens over the same live-worktree legs, i.e. folds > distinct paths for the
    request even with the seam's ReadScope installed. With `with_tail` the remainder is read from the
    SAME handle, before it closes, and returned as a `_PrefixStart` (the offset, with `.tail`
    carrying those bytes) — so the caller needs no
    second open. NOT a cache, on exactly the standing above: nothing is stored or keyed, the bytes are
    the caller's own next read taken one moment earlier, and they are the un-landed span above the
    shared frontier — the handful of rows the leg exists to contribute, never the ~99.9% below it.
    Every fail-open exit returns `_PrefixStart(0)` in this mode, which reads as "no offset
    established, no bytes handed over" and takes the caller's unchanged from-byte-0 path.
    """
    _t0 = time.monotonic()
    _tail_bytes = None
    try:
        a, b = Path(path), Path(other)
        with a.open("rb") as fa, b.open("rb") as fb:
            shared = 0
            tail = b""          # the bytes of the last shared block, for the newline cut below
            while True:
                x = fa.read(block)
                y = fb.read(block)
                if not x or not y:
                    break                      # one file ended — everything compared so far is shared
                if x == y:
                    shared += len(x)
                    tail = x
                    break_at = None
                else:
                    n = min(len(x), len(y))
                    break_at = next((i for i in range(n) if x[i] != y[i]), n)
                    tail = x[:break_at]
                    shared += break_at
                if break_at is not None:
                    break
            cut = tail.rfind(b"\n")
            if cut < 0:
                # The divergence is inside the FIRST line of the last shared block. Whether an
                # earlier block ended on a newline is not knowable from `tail` alone, so answer
                # conservatively.
                return _PrefixStart(0) if with_tail else 0
            start = max(0, shared - (len(tail) - cut - 1))
            if with_tail:
                # T-12208 — the caller's next read, taken on THIS handle instead of a second open.
                # Inside the `with` on purpose: `fa` is still open, and this is the whole point.
                fa.seek(start)
                _tail_bytes = fa.read()
    except (OSError, ValueError):
        # fail open — read from byte 0, exactly as before (and hand over no bytes)
        return _PrefixStart(0) if with_tail else 0
    note_fold(a, 0, time.monotonic() - _t0)
    return _PrefixStart(start, _tail_bytes) if with_tail else start


def _tail_window_start(path, cutoff, *, block=_TAIL_WINDOW_BLOCK, confirm_bytes=_TAIL_WINDOW_CONFIRM_BYTES,
                      floor=0, collect=None):
    """Byte offset to start reading `path` from so EVERY line with ts >= cutoff is included, without
    parsing the whole file. Scans fixed byte-blocks BACKWARD from EOF (`cutoff` is an ISO-8601 `Z`
    string — lexical compare == chronological, the same basis as the since/until filter). FAIL-CLOSED:
    returns 0 (== read the whole file) unless it can positively establish the boundary.

    The journal is append-ordered but NOT strictly ts-sorted — a `land` union-merge appends a batch of
    a worktree's (possibly old-ts) events at the tail, AFTER newer main appends. So the scan must not
    cut at the first old block: it (i) never cuts while it has not yet seen an in-window line (an
    all-old TAIL batch → keep reading back), (ii) tracks `boundary` = the lowest byte offset of any
    in-window line, and (iii) cuts at `boundary` only once `confirm_bytes` of purely-old data has been
    scanned PAST it (absorbs a sandwiched old fold). Reaching BOF or never seeing an in-window line
    returns 0 (full read).

    A line that STRADDLES a block boundary is reconstructed via `carry` (the leading fragment of one
    block is the TAIL of a line whose head is in the next, earlier block) — so every JSON row is parsed
    exactly once, never split into two unparseable halves (audit-post RED T-10387).

    `floor` (T-12129) — a byte offset BELOW WHICH THIS SCAN NEED NOT LOOK, because the caller has
    established that the region under it is carried by ANOTHER leg of the same fold. The scan stops
    there instead of at BOF, and the two BOF-equivalent exits return `floor` instead of 0. It is the
    caller's claim, not this function's: `_dispatch_status_events` passes the offset a worktree leg
    provably shares with the main leg (`_shared_prefix_start`), and the main leg reads that region.
    The DEFAULT 0 is exactly today's behaviour — a caller that establishes nothing claims nothing, and
    the fail-closed full read is what it gets. Without it the windowed branch pays the whole backward
    parse anyway: the scan json.loads every line it walks over, which is the cost, not the seek.

    `collect` (T-12209, SPEC-0190 rule 4) — HAND BACK WHAT THIS SCAN ALREADY READ, so its caller does
    not read the same artifact a second time. Pass a list and every complete line this walk parses is
    appended as `(byte_offset, parsed_value)`; the caller keeps the entries at `offset >= the returned
    start` and has the window WITHOUT re-opening the file. Nothing else moves: the return value, the
    scan order, the boundary logic, `floor`, the carry/straddle reconstruction, both fail-closed exits
    and both counter calls are untouched, and with the DEFAULT `None` this function is byte-identical
    for every caller that does not ask (`_dispatch_status_events`' two call sites, and any test).

    WHY IT EXISTS, measured on this repo 2026-09-07 (98 segments / ~650k rows). `cli._iter_events_tail`
    called this scan for a byte offset and then seeked to it and read + parsed the window AGAIN — TWO
    physical reads of the SAME artifact for one request: folds 2, rows_parsed 22493 over rows 14020
    (ratio 1.604), which is the whole of the ~1.6-1.8x floor every gated light verb paid (`config get`
    / `config list` / `cross show` / `cross inbox` / `cross outbox` / `task list` / `task pick`), and
    doubled again to 3.6x on `--help`, which asks the identity question twice. The rows this scan
    parses to find the boundary are exactly the rows the second read re-parsed, so the second read was
    never buying anything.

    NOT A CACHE (SPEC-0190 rule 10's named retirement (a)): nothing is stored, keyed, or remembered
    across calls, and there is no lifetime to invalidate — the caller passes a list in and gets THIS
    call's own rows back. The obligation lands on the primitive that owns the physical read, which is
    the T-12204 shape.

    COLLECTION ORDER IS THE SCAN's, NOT THE FILE's — the walk goes BACKWARD in blocks (ascending
    within a block, descending across them), so entries carry their byte offset and a caller that
    wants file order sorts by it. Stating this here rather than sorting for the caller keeps the
    primitive doing one thing; `_iter_events_tail` sorts."""
    # T-12034: a physical-read counter site, and the one that makes the PER-VERB FLOOR visible. This
    # scan is not reached through `_fold_lines_uncached` — it seeks backward in fixed byte blocks and
    # json.loads each line itself — so it must report its own read, and it is paid by EVERY gated verb:
    # measured, even `bin/yitc-v2 --help` parses ~54k rows here plus ~20.4k in `cli._iter_events_tail`,
    # a floor paid ~1,316 times per verify run (T-11317) that no surface reported until now.
    _t0 = time.monotonic()
    _scanned = 0
    size = path.stat().st_size
    floor = max(0, int(floor or 0))
    if floor >= size:
        return 0         # a floor at or past EOF establishes nothing here — fail open to a full read
    boundary = None      # lowest byte offset of a line with ts >= cutoff
    old_bytes = 0        # purely-old bytes accumulated (scanning back) since the last in-window line
    pos = size
    carry = b""          # bytes AFTER this block that complete its last (straddling) line
    with path.open("rb") as f:
        while pos > floor:
            bstart = max(floor, pos - block)
            f.seek(bstart)
            chunk = f.read(pos - bstart)
            pos = bstart
            if bstart > floor:
                nl = chunk.find(b"\n")
                if nl < 0:   # a single line spans the whole block — defer it all to the earlier block
                    carry = chunk + carry
                    continue
                next_carry = chunk[:nl]            # tail of a line whose head is in the earlier block
                region = chunk[nl + 1:]            # complete lines + a trailing head fragment
                region_start = bstart + nl + 1
            else:
                next_carry = b""
                region = chunk
                region_start = floor
            parts = region.split(b"\n")            # last element is the head fragment (no trailing '\n')
            saw_recent = False
            off = region_start
            last = len(parts) - 1
            for idx, raw in enumerate(parts):
                ln = (raw + carry if idx == last else raw).strip()   # complete the straddling line
                if ln:
                    _scanned += 1
                    # T-12209 — the parse is SPLIT from the `.get("ts")` so the parsed value can
                    # survive both arms and be handed to `collect`. `ValueError` (not the narrower
                    # `json.JSONDecodeError` this clause used to name) is deliberate and is itself a
                    # FIX: `ln` is BYTES, and on malformed UTF-8 `json.loads` decodes before it parses
                    # and raises `UnicodeDecodeError` — a `ValueError`, but NOT a `JSONDecodeError`,
                    # so the old clause did not catch it and this scan RAISED, out of a function whose
                    # entire contract is to fail open to a full read and never to an exception
                    # (surfaced by the T-12209 audit-pre, verified at the interpreter). One clause now
                    # covers both, and an undecodable line is skipped exactly as a syntactically bad
                    # one already was — the per-line skip-on-failure policy `_fold_lines_uncached`
                    # documents. `AttributeError` still covers a well-formed NON-dict row (no `.get`),
                    # which stays `ts=""` exactly as before and is still collected: the caller's own
                    # `isinstance(e, dict)` filter drops it, so no admitted set widens here.
                    try:
                        obj = json.loads(ln)
                    except ValueError:
                        ts = ""
                    else:
                        if collect is not None:
                            collect.append((off, obj))
                        try:
                            ts = obj.get("ts") or ""
                        except AttributeError:
                            ts = ""
                    if ts and ts >= cutoff:
                        saw_recent = True
                        if boundary is None or off < boundary:
                            boundary = off
                off += len(raw) + 1   # +1 for the split '\n'; `raw` is this block's bytes (carry excluded)
            carry = next_carry
            if saw_recent:
                old_bytes = 0
            elif boundary is not None:
                old_bytes += len(chunk)
                if old_bytes >= confirm_bytes:
                    note_fold(path, _scanned, time.monotonic() - _t0)
                    note_rows_parsed(_scanned)
                    return boundary
    note_fold(path, _scanned, time.monotonic() - _t0)
    note_rows_parsed(_scanned)
    # Reaching the floor (or BOF, when `floor` is 0) WITHOUT the confirmation the loop needs is the
    # FAIL-CLOSED exit, and it is unchanged: read everything this scan was allowed to look at. For
    # every pre-existing caller `floor` is 0, so that is still the literal whole file.
    return floor


@functools.lru_cache(maxsize=64)
def _superset_matcher(tokens):
    """T-11452 — the per-line SUPERSET test of `_bounded_superset_lines`, built ONCE per token set.

    WHY IT EXISTS. The test used to be `any(t in bline for t in wanted)` evaluated per line, so each
    line paid len(wanted) interpreted membership checks plus a generator frame — a cost that scales
    with the TOKEN COUNT, not just the file. Profiled on the engine journal (177MB / 393728 lines,
    2026-08-22): 40,870,664 generator calls / 18.2s inside this one filter, on a `bin/yitc-v2 debt`
    run measured at 148.5s — which had crossed BOTH the 180s in-test subprocess timeout and the 300s
    per-file land-verify cap, aborting unrelated lands. One compiled alternation moves that scan into
    C and makes it one match per line regardless of how many tokens were asked for.

    WHY IT IS THE SAME PREDICATE, not a tightening. `_bounded_superset_lines` documents its filter as
    "only ever a SUPERSET, so the caller's exact parsed check still decides membership". A line
    survives iff at least one token appears ANYWHERE in its raw bytes, free text included — which is
    exactly what an alternation of the same tokens matches. Three properties carry that equality and
    each is pinned by a test rather than assumed:
      * `re.escape` per token — a token carrying regex metacharacters stays LITERAL. Without it the
        pattern would silently mean something else than the `in` test it replaces.
      * alternation — overlapping tokens both stay admitted; no ordering or longest-match effect can
        drop a line, because `search` only answers whether SOME branch matched.
      * `search` over the RAW line — never anchored, never field-scoped, so a token appearing only in
        a payload's free text is still admitted, as the superset contract requires.

    THE EMPTY SET IS THE TRAP, and it is why this returns None rather than a pattern. `any(...)` over
    an empty token list is False, so NO line survives; but `b"|".join(())` is the EMPTY pattern, which
    matches EVERY line. A careless alternation therefore INVERTS the answer precisely where the caller
    asked for nothing. None is the explicit "match nothing" answer and the caller turns it into [].
    (`tokens=None` is a different case entirely — "keep every line" — and returns before reaching here.)

    Memoized on the token TUPLE (bytes, hashable): the measured profile made 24 calls into the filter,
    which compiled the identical pattern 24 times. Bounded at 64 entries — the token sets are a small
    fixed vocabulary of envelope types, not user input."""
    if not tokens:
        return None
    return re.compile(b"|".join(re.escape(t) for t in tokens)).search


# ── The ONE parsed whole-journal fold + its request-scoped memo (T-11453) ────────────────────────────
#
# WHAT IT REMOVES, MEASURED. `_debt_echo_lines` — the ONE shared residue behind all three debt seams
# (session-start / land-tail / the on-demand `debt` re-fold) — folded the local events.jsonl ~15 times
# per invocation, each fold an independently written copy of the identical
# `open() → for line → strip → json.loads` loop: 12 in bin/lib/debt.py, plus `cli._iter_events` (which
# serves `views._view_not_adopted`) and `followup._fold`. Profiled on the engine journal 2026-08-22
# (176 MB / 394,242 lines): one real `debt` run opened the journal 17 times, read 529 MB, and cost
# 49.0s / 51.2s / 74.4s across three timed runs — 59% of it in re-reading and re-parsing bytes it had
# already parsed. It is paid at every session start and every land tail.
#
# IT IS NOT A SECOND READER (CHARTER §P5 / §P1 filter 1). This is the sibling of `DispatchEventsMemo`
# (T-11438) on the other axis: that one memoizes a request-scoped VIEW over the dispatch UNION reader,
# this one memoizes the PHYSICAL FOLD of a single journal file. Neither adds a parse path — every
# caller still resolves through the same reader it always did, re-pointed at a memo of that reader's
# own result. No store, no cache file, no config, no new window constant, and nothing survives the
# scope.
#
# THE MEMO IS DECLARED, NEVER UNIVERSAL — and this is a MEASUREMENT, not a preference. A full parsed
# fold of the engine journal retains 1.2 GB. `debt` already peaks at 1.08 GB, so ONE such fold is not a
# regression in kind. But `_dispatch_status_events` reads a UNION of 17 journals (local + main + every
# live task worktree, ~176 MB each), and memoizing that union would retain ~20 GB. So `rows_memo`
# holds only the paths its caller DECLARES — in practice the local EVENTS_PATH, the one file that was
# being folded fifteen times — and every other path falls straight through to an uncached read, which
# keeps that reader's `include_types` byte-prescan fast path intact for the 16 foreign journals it must
# still scan.
#
# A DECLARATION NAMES A LOGICAL JOURNAL, NOT A PHYSICAL FILE (T-12029, SPEC-0190 rule 1). The
# paragraph above was written before rotation existed, when the two were the same thing. They are
# not: every reader folds `events.segment_paths()`, so declaring `[EVENTS_PATH]` once the archive
# appeared held 1 of 94 paths and the other 93 were re-read and re-parsed by each of the ~20 debt
# views — 378 s of a 383 s `session start` (2026-09-03). `holds` therefore admits any SEGMENT of a
# declared logical journal, via the round-trip-verified `events.logical_journal` mapping. What does
# NOT change is the bound that made the declaration a measurement rather than a preference: the
# LIVE journal must still be DECLARED, so the 17-journal `_dispatch_status_events` union stays out
# and keeps its prescan. Retention grows from the live segment to the whole logical journal — one
# parsed fold, the same ~1.2 GB order this comment already accepted, not a regression in kind.
#
# LINES FIRST, ROWS LAZILY. The one pass produces the stripped non-empty LINES (~200 MB retained); the
# parsed ROWS (the 1.2 GB) are derived from them on first `fold_rows`. Two views are needed because the
# followup fold replays LINES and dedupes by raw-line identity while every other reader wants parsed
# rows — deriving both from ONE read is what makes it impossible for them to disagree about which
# journal state they are talking about (the same consistency property `_dispatch_status_events` argues
# for at its own union).
# REQUEST-SCOPED MEANS PER-THREAD, AND THAT IS A CORRECTNESS BOUND, NOT TIDINESS (T-12424). This was
# a module GLOBAL, which is request-scoped only in a single-threaded process. Two concurrent callers
# in ONE process shared it, and the re-entrancy arm in `rows_memo` below (T-12208) — whose `holds()`
# test asks «does the installed scope cover this path», never «is the installed scope MINE» — handed
# the SECOND caller the FIRST caller's already-cached snapshot. Measured on
# `tests/test_ceiling_decisions_decide.py::test_concurrent_decisions_are_serialized_to_one_row`,
# where two `audit decide` calls race under the REAL flock: the lock WINNER folded the journal into
# the shared memo BEFORE appending its `ceiling_decision` row, and the LOSER — inside its own
# critical section, holding the lock the winner had released — was served that pre-append snapshot,
# saw no decision, and appended a second row. The flock was sound throughout (two distinct open file
# descriptions, so it does exclude in-process); what the shared memo de-serialized was the READ. So
# SPEC-0190 rule 10's «the seam owes ONE ReadScope, never a stale one» was being broken by the
# scope's LIFETIME rather than by its placement, and the T-12287 contract «the journal read, the
# duplicate check and the append are ONE critical section» was structurally true and semantically
# false. 11 of 12 single-test runs red on the engine host; it also aborted the pinned leg of an
# unrelated worker land (2026-09-11T20:13:40Z) and had been mislabelled a load flake.
#
# The fix is a NARROWING of this variable's lifetime — the same memo, scoped to the unit that owns
# it — not a new mechanism (CHARTER §P1: the existing analog IS this variable; no new entity; it
# REMOVES both the cross-thread read and the lost-update where one thread's scope EXIT restored over
# a peer's live scope; the incident is measured, not imagined). It adds no lock, no timeout and no
# retry. FAIL-SAFE BY CONSTRUCTION: a memo MISS already falls through to a plain read, so a thread
# that no longer inherits an outer scope pays one uncached read and can never get a wrong answer —
# which is why the engine's other threads (the `verify_runner` pools, the audit/land heartbeats,
# none of which install or consume a scope) are unaffected. Every `rows_memo(` caller installs and
# consumes inside one synchronous `with` body on one thread, so none of them loses a hit.
_ROWS_MEMO_TLS = threading.local()   # request-scoped == THREAD-scoped; INSTALLED ONLY inside
                                     # `rows_memo()` and absent on every other thread


def _rows_memo_current():
    """The memo installed by THIS thread's innermost `rows_memo()` scope, or None.

    The single read site for the scope — every reader below goes through it, so "is a scope
    installed" can never be answered off another thread's state. Outside a scope this returns None
    and each reader folds plainly, byte-for-byte as before the memo existed."""
    return getattr(_ROWS_MEMO_TLS, "memo", None)


# ── T-12034 — the PROCESS-SCOPED read counters (SPEC-0190 / SPEC-0161 / SPEC-0025) ────────────────
#
# WHAT THEY ARE FOR. SPEC-0190 rule 4 already names "a reader that folds the whole archive to answer
# a question about the last seven days" as a defect — a rule with no measurement behind it. Nothing
# in this system reported how many times a verb physically re-reads the journal, so read
# amplification drifted invisibly until a human waited: T-11453's measured 32.6 s became 378 s once
# the archive grew into the segment set, with no site changing. These counters make that number
# reportable on the row the CLI already emits.
#
# THE ANTI-COMPLEXITY SHAPE (CHARTER §P1). Filter 1 — the existing analog is
# `JournalRowsMemo.folds`/`served` (T-11453): a plain counter living ON a read primitive, read by
# tests, never by a gate. This is that shape, moved down one level to the PHYSICAL primitives and
# widened from one memo's lifetime to the process. Filter 2 — a VIEW over reads that already happen,
# not a new entity: no store, no file, no config, no event of its own. Filter 3 — what it removes is
# the blind spot, which is the T-11326 precedent stated out loud: a silent dead mechanism and a
# working one are otherwise indistinguishable (1135 markers written, none read across 1390 lands,
# invisible until someone went looking). Filter 4 — the incident is measured, not imagined: engine
# `debt` = 2,052 physical segment reads over 93 segments (22x), 11.1M json.loads over ~596k rows;
# kupiclub under `-C` = 27x on the SAME code.
#
# WHERE THEY MAY BE INCREMENTED — the LOWEST PHYSICAL PRIMITIVES ONLY, and this bound is the whole
# design. Counted here: `_fold_lines_uncached` (the one physical byte read), `_rows_from_lines` (the
# one event-line parser), `segment_lines` + `segment_text` (the two folds that open segments
# THEMSELVES rather than delegating), and `_tail_window_start` (the read-gate's backward byte scan,
# which is a physical read + its own json.loads). NOT counted: `fold_lines` / `fold_rows` /
# `segment_rows` / `segment_fold_lines` / `cli._iter_events` — every one of them reaches bytes only
# through a primitive above, so counting them would double-count the same physical read and make an
# amplification ratio unreadable. A VIEW NEVER SELF-REPORTS (the external consult's F1/Q2): a reader
# that wants to be counted routes through a primitive, it does not call `note_fold` for itself. The
# ONE exception is `cli._iter_events_tail`, which owns a genuine physical tail read of its own and
# so reports THAT read here while parsing through `_rows_from_lines` like everyone else.
#
# `rows` HAS NO SEPARATE READ. The denominator is the folds' OWN line counts: `_FOLD_LINES` records,
# per physically-folded path, the number of lines that fold saw. Summed at the emit site that IS the
# logical journal's row count, so the ratio costs nothing beyond the reads it measures.
#
# THE CARD COUNTER IS NOT HERE, and the reason is the import direction: this module imports
# `lib.state` (above), so `state.load_path` cannot call into here without inverting that edge.
# `state.read_counters()` is its symmetric twin; `cli._emit_cli_invoked` merges the two.
_READ_COUNTERS = {"folds": 0, "rows_parsed": 0, "wall_ms": 0.0}
_FOLD_LINES: dict = {}          # path -> that path's own line count, from the fold that read it


def note_fold(path, nlines: int, secs: float = 0.0) -> None:
    """Record ONE physical read of `path` that saw `nlines` lines and took `secs`.

    `_FOLD_LINES` is keyed by path and holds the LARGEST count seen, never a sum and never the last
    writer: it is the DENOMINATOR (how many rows that journal HAS), so a path folded five times must
    contribute its line count ONCE. `folds` is what accumulates — five folds of one path is exactly
    the amplification being measured.

    MAX, not last-wins, because the folds of one path do not all see the same number of lines. A full
    fold of the live segment sees every line; `_tail_window_start` sees only the tail it scanned back
    through, and an abandoned `segment_lines` generator sees only what it yielded. Under last-wins the
    denominator would depend on which reader happened to run last — a `--help` tail scan following a
    full fold would silently shrink `rows` below the row count that was actually read, inflating every
    ratio computed from it. The largest fold observed is the only order-independent answer available
    without a second read, and it can never claim more rows than some reader really saw.
    """
    _READ_COUNTERS["folds"] += 1
    _READ_COUNTERS["wall_ms"] += secs * 1000.0
    try:
        key = str(path)
        _FOLD_LINES[key] = max(_FOLD_LINES.get(key, 0), int(nlines))
    except (TypeError, ValueError):
        pass


def note_rows_parsed(n: int) -> None:
    """Record `n` event lines handed to the parser — the numerator of the rows ratio."""
    _READ_COUNTERS["rows_parsed"] += int(n)


def read_counters() -> dict:
    """A SNAPSHOT of the journal-side counters plus the derived `rows` denominator.

    A copy, deliberately: the emit site must not be able to mutate the live counters, and a reader
    that holds this dict across further reads should see the moment it asked about."""
    out = dict(_READ_COUNTERS)
    out["rows"] = sum(_FOLD_LINES.values())
    return out


def reset_read_counters() -> None:
    """Zero the counters. For TESTS ONLY — a CLI process reads the journal once and exits, so
    production never needs this; a test that measures two verbs in one interpreter does."""
    _READ_COUNTERS.update({"folds": 0, "rows_parsed": 0, "wall_ms": 0.0})
    _FOLD_LINES.clear()


def _fold_lines_uncached(path) -> list:
    """The physical read: every non-empty, stripped line of `path`, in file order, as `str`.

    DECODE POLICY — per line, strict, skip-on-failure: an undecodable line was never a parseable
    event, which is the policy `_dispatch_status_events` already applies to its own prescan survivors.
    It is strictly MORE tolerant than the `read_text(encoding="utf-8")` the replaced readers used (a
    single bad byte there raised, and inside a report-only debt fold that blanked the whole echo), and
    it can never ADMIT a line that a strict whole-file decode would have admitted differently.

    A missing / unreadable file yields [] — a report-only fold never breaks the seam it rides.
    """
    # T-12034: THE physical-read counter site. Placed inside the primitive rather than at its callers
    # because every migrated reader reaches bytes through here — instrumenting the callers would both
    # miss the ones that arrive indirectly and double-count the ones that do not.
    t0 = time.monotonic()
    try:
        raw = Path(path).read_bytes()
    except OSError:
        # A read that never happened is not a fold: an absent file is the fresh-checkout case, and
        # counting it would put a phantom in the numerator of every ratio.
        return []
    out = []
    for bline in raw.splitlines():
        bline = bline.strip()
        if not bline:
            continue
        try:
            out.append(bline.decode("utf-8"))
        except UnicodeDecodeError:
            continue
    # The line count recorded is the ADMITTED set (stripped, non-empty) — the same set every caller
    # goes on to parse, so the `rows` denominator and the `rows_parsed` numerator count the same
    # thing and their ratio is meaningful.
    note_fold(path, len(out), time.monotonic() - t0)
    return out


def _rows_from_lines(lines) -> list:
    """Parse folded lines → the events. Skips an unparseable line, never raises.

    Returns EVERY parsed value, including non-dicts: each caller keeps its own `isinstance(e, dict)`
    guard, so the admitted set of every replaced reader is unchanged rather than silently widened or
    narrowed here.
    """
    # T-12034: THE parse counter site. Counts lines HANDED to the parser, not rows successfully
    # parsed — the cost being measured is the json.loads attempt, and an unparseable line costs it too.
    t0 = time.monotonic()
    out = []
    n = 0
    for line in lines:
        n += 1
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    note_rows_parsed(n)
    _READ_COUNTERS["wall_ms"] += (time.monotonic() - t0) * 1000.0
    return out


class JournalRowsMemo:
    """ONE fold of each DECLARED journal path, shared by every reader inside one request scope.

    `folds` / `served` count real physical folds vs memo-served calls; they are the collapse's probe
    subject (the T-11453 AC1 differential) and are read by the tests, never by a gate — the
    `DispatchEventsMemo.reads`/`served` precedent.
    """

    def __init__(self, paths):
        self._keys = set()
        for p in (paths or ()):
            if p:
                self._keys.add(self._key(p))
        self._lines = {}
        self._rows = {}
        self.folds = 0
        self.served = 0

    @staticmethod
    def _key(path) -> str:
        try:
            return str(Path(path).resolve())
        except OSError:
            return str(path)

    def holds(self, path) -> bool:
        """True iff `path` belongs to a DECLARED LOGICAL journal — its live segment OR any of its
        archive segments (T-12029, SPEC-0190 rule 1).

        A DECLARATION NAMES THE LOGICAL JOURNAL, NOT ONE PHYSICAL FILE — which is rule 1's own
        framing, and the property the memo silently lost when the archive appeared. Every migrated
        reader folds `events.segment_paths()`, so a memo declaring the live file alone held 1 of 94
        paths here: the other 93 fell through to an uncached read and were re-read AND re-parsed by
        each of the ~20 debt views. Measured on the engine 2026-09-03: `session start` = 383 s, of
        which 378 s inside `_debt_echo_lines`, 11.4M `json.loads` = ~20 full passes over the 595k-row
        logical journal. T-11453's own 32.6 s figure predates rotation, so the collapse it shipped
        was undone on the archive axis without any site changing.

        THE MAPPING IS `events.logical_journal`, REUSED, NEVER RE-SPELLED. That resolver is already
        the segment -> logical identity SPEC-0190 rule 1 keys the journal LOCK on, and it is
        round-trip verified: a file that merely SITS in a directory called `archive` does not
        round-trip and is returned unchanged, so it can never be silently re-keyed onto another
        journal's memo. Its rule-1b fence comes with it — the `.yitc/` hook-tail and the kernel-owned
        shared coordination store are not segmented, never reach the archive branch, and are
        admitted here only by an exact declaration exactly as before.

        THE DECLARED-ONLY BOUND IS UNCHANGED, which is what keeps T-11453's memory decision intact:
        admission still requires the resolved LIVE journal to have been DECLARED. `_dispatch_status_events`
        unions up to 17 FOREIGN journals; none of them is declared, so none is admitted — with or
        without an archive — and each keeps the `include_types` byte-prescan fast path that memoizing
        them (~20 GB) exists to preserve.
        """
        key = self._key(path)
        if key in self._keys:
            return True
        return self._key(events.logical_journal(path)) in self._keys

    def lines(self, path) -> list:
        key = self._key(path)
        if key not in self._lines:
            self.folds += 1
            self._lines[key] = _fold_lines_uncached(path)
        else:
            self.served += 1
        return self._lines[key]

    def rows(self, path) -> list:
        key = self._key(path)
        if key not in self._rows:
            self._rows[key] = _rows_from_lines(self.lines(path))
        else:
            self.served += 1
        return self._rows[key]


@contextlib.contextmanager
def rows_memo(paths):
    """Collapse one fold's repeated reads of the DECLARED journal path(s) onto a single read.

    Scope discipline, taken verbatim from `cli._dispatch_events_memo` (T-11438): the prior value is
    SAVED and RESTORED, so a nested scope degrades to the outer memo rather than leaking, and an
    exception inside the body can never leave a stale snapshot installed for a later, unrelated verb.
    Both the save and the restore are THIS THREAD's (T-12424 — see `_ROWS_MEMO_TLS`), so a scope
    exiting on one thread can no longer restore over a peer's still-live scope.

    RE-ENTRANT (T-12208), WITHIN ONE THREAD: when the installed scope ALREADY declares every path
    this one would, the
    inner `with` yields THAT memo and installs nothing. Without it, wiring a scope at a COMPOSING
    seam (SPEC-0190 rule 10 — `cli.cmd_session_start` is the first such caller of an inner site that
    already scopes itself) would make the INNER scope re-fold everything the outer one holds, so the
    seam would pay MORE reads for adopting the rule. The `holds()` test is the whole condition and
    is deliberately strict: a NARROWER outer scope must never swallow a WIDER inner declaration, so
    a scope declaring paths the outer one does not hold installs its own memo exactly as before.
    "Outer" means outer IN THIS THREAD — the only reading this arm was ever written for (its
    motivating caller, `cli.cmd_session_start` wrapping an inner site that already scopes itself, is
    a same-thread nesting). A PEER thread's memo does not satisfy it: the `holds()` test asks which
    paths a scope covers, never whose scope it is, so before T-12424 a concurrent caller silently
    adopted another request's snapshot — see `_ROWS_MEMO_TLS` for the measured incident.
    """
    prior = _rows_memo_current()
    if prior is not None and all(prior.holds(p) for p in (paths or ()) if p):
        yield prior
        return
    memo = JournalRowsMemo(paths)
    _ROWS_MEMO_TLS.memo = memo
    try:
        yield memo
    finally:
        _ROWS_MEMO_TLS.memo = prior


def rows_memo_holds(path) -> bool:
    """True iff a scope is installed AND it holds `path` — the opt-in test a reader with its own
    cheaper bounded/prescanned path consults before giving that path up (see
    `_dispatch_status_events`)."""
    memo = _rows_memo_current()
    return memo is not None and memo.holds(path)


def fold_lines(path) -> list:
    """The stripped non-empty lines of `path` — memo-served inside a declaring scope, a plain read
    outside one. Pass-through by default, so no caller's behaviour moves."""
    memo = _rows_memo_current()
    if memo is not None and memo.holds(path):
        return memo.lines(path)
    return _fold_lines_uncached(path)


def fold_rows(path) -> list:
    """The parsed events of `path` — memo-served inside a declaring scope, a plain fold outside one.

    THE replacement for the ~15 hand-written `open() → for line → strip → json.loads` loops. Physical
    order is preserved; a caller that needs chronology still sorts by `ts`, exactly as before.
    """
    memo = _rows_memo_current()
    if memo is not None and memo.holds(path):
        return memo.rows(path)
    return _rows_from_lines(_fold_lines_uncached(path))


# ── SPEC-0190 — the segment-aware FOLDS (T-11444) ────────────────────────────────────────────────
#
# The segment SET is resolved once, in the leaf (`events.segment_paths` — read its contract there:
# ordering, naming, the rule-1b scope fence, and why the resolver lives below this module). These are
# the FOLDS built on it, and they are the surface every journal READER migrates onto.
#
# THEY EXTEND THE EXISTING FOLD, they are not a second one. Each segment is read through the SAME
# `fold_lines` / `fold_rows` primitive above, so there is still exactly ONE physical read + ONE parse
# path (CHARTER §P1 filter 1 / §P5 no-parallel-paths), the `rows_memo` scope still serves each
# segment, and a caller inside a memo scope keeps its collapse. SPEC-0190 rule 4 names the shape
# directly — `task.py#_folded_journal_events` already folds several physical carriers into one
# logical result — so this is that shape applied to the segment set, not a new folding path.
#
# THE DECODE POLICY IS THE CALLER'S, PASSED THROUGH VERBATIM. `segment_text` / `segment_lines` take
# `encoding=` / `errors=` and hand them to `read_text` unchanged, so a single-segment call is
# byte-identical to the `path.read_text(encoding=..., errors=...)` it replaces. That is deliberate:
# the migrated readers deliberately differ (strict / `ignore` / `replace`), and folding one policy
# onto all of them would silently widen or narrow which lines each admits — a behaviour change no
# card asked for. `segment_rows` has no such knob because the reader it replaces is `fold_rows`,
# whose per-line skip-on-failure policy is already the one answer.
#
# WITH ROTATION OFF AND NO ARCHIVE the set is `(live,)` and every function here is exactly today's
# single-file read.
_SEGMENT_CHUNK_BYTES = 1 << 20     # the streaming read block; a tuning knob, never a semantic one


def stream_lines(fh, *, _chunk=_SEGMENT_CHUNK_BYTES):
    """Yield the lines of an ALREADY-OPEN text handle, reading it in bounded blocks.

    THE ONE block-and-carry-over splitter (T-12226). It was extracted from `segment_lines`, which had
    been its only caller, when the SECOND caller arrived — `worktree#_floor_scan_files`, the
    kernel-floor secrets reader, which has exactly the same problem (a file too large to hold whole)
    and must not answer "where does a line end" differently from the journal reader. Two copies of a
    carry-over splitter are two answers to that question, and they drift (CHARTER §P1 F1).

    THE LINE SHAPE IS `str.splitlines()`, EXACTLY — not `for line in fh`. That is deliberate and is
    the reason this is a splitter rather than a loop over the handle: `splitlines` breaks on line
    boundaries file iteration does not (`\x0b`, `\x0c`, `\u2028`, `\u2085`), so iterating the handle
    would silently NARROW the admitted line set. The carry-over keeps a trailing UNTERMINATED part
    until the next block confirms it, which is why a block boundary cannot invent or lose a line;
    universal-newline decoding buffers a pending `\r` in the incremental decoder, so a `\r\n` split
    across two blocks stays ONE break.

    THE MEMORY BOUND, EXACTLY — the longest logical LINE plus one block, NOT one block alone. The
    carry holds an unterminated fragment until a terminator arrives, so a handle over content with NO
    newline at all is still held whole. That is deliberate, not an oversight: cutting a long line at
    an arbitrary offset would hand each caller a pair of half-lines, and for the secrets reader a
    credential straddling the cut would then go unmatched — a false green, which is the one failure a
    security floor may not have. For the callers that motivate this the bound is the real win anyway:
    a journal segment and a `events.jsonl` line are newline-delimited, so the per-line bound is ONE
    row against a segment of any size. Callers state this bound; none may claim block-only memory."""
    carry = ""
    while True:
        block = fh.read(_chunk)
        if not block:
            break
        carry += block
        parts = carry.splitlines(keepends=True)
        # A part is TERMINATED iff stripping its terminator shortens it. The last part of a
        # block is the only one that can be an unterminated fragment; carry it forward.
        if parts and len(parts[-1]) == len(parts[-1].splitlines()[0]):
            carry = parts.pop()
        else:
            carry = ""
        for part in parts:
            yield part.splitlines()[0]
    if carry:
        yield carry.splitlines()[0]


def segment_lines(path, *, encoding="utf-8", errors=None, _chunk=_SEGMENT_CHUNK_BYTES):
    """Yield the lines of the WHOLE logical journal at `path`, segment by segment, in segment order.

    A GENERATOR, AND GENUINELY STREAMING — it never holds a segment whole. Several migrated readers
    were written as `for line in open(...)` precisely so a ~175 MB journal is never materialised
    (`worktree#_newest_dispatch_row_in`, `views#_view_trend_report`, `views#_view_observation`,
    `views#_audit_observations`, `grants#_read_journal`, `observe`, `cli#_uncatalogued_type_warnings`).
    A `read_text()` per segment would have been a correctness fix bought with a memory regression, so
    the read is CHUNKED with a carry-over for the fragment a block boundary cuts in half.

    THE SPLITTING ITSELF IS `stream_lines` ABOVE (T-12226) — the shared block-and-carry splitter, whose
    docstring is the one home for the line shape (`str.splitlines()`, exactly — not `for line in fh`,
    which would silently narrow the admitted line set) and for the memory bound (the longest logical
    LINE plus one block, never one block alone). The replaced expression here was
    `read_text(...).splitlines()`, and that shape is preserved verbatim. Not restated (CHARTER §P5).

    A missing segment yields nothing — the live segment is legitimately absent on a fresh checkout,
    and every replaced reader already guarded for that."""
    # T-12034: a physical-read counter site. This fold does NOT delegate to `_fold_lines_uncached`
    # (it streams, deliberately, so a ~175 MB journal is never materialised), so it opens segments
    # itself and must report them itself. The count is accumulated AS IT YIELDS and reported when
    # the segment is exhausted, because a generator's caller may abandon it early: reporting the
    # lines actually produced keeps the denominator honest about what was really read.
    for seg in events.segment_paths(path):
        # T-12035 (SPEC-0190 rule 10) — INSIDE a request-scoped ReadScope this streaming primitive
        # SERVES from the scope instead of re-opening the segment. Without this the rule is
        # unenforceable at any seam whose views stream: `triage._scan_captures` and
        # `_last_triage_watermark` both fold through here, so `task file`'s advisory tail read every
        # one of the engine's 95 segments THREE times (285 folds) INSIDE a correctly-installed scope —
        # one legitimate fold plus these two bypasses.
        #
        # THE MEMORY ARGUMENT THIS PRIMITIVE EXISTS FOR IS NOT WEAKENED, and that is the whole reason
        # this is safe rather than a quiet reversal of the streaming decision. `holds` admits a
        # segment only when the caller DECLARED its logical journal, and a declared journal inside a
        # live scope is ALREADY materialised — some reader in the scope folded it, which is what makes
        # the memo able to answer. So serving here retains nothing new; it removes a second physical
        # read of bytes the process is holding anyway. OUTSIDE a scope, and for any UNDECLARED path
        # (`_dispatch_status_events`' union of up to 17 foreign journals — the ~20 GB T-11453
        # deliberately kept out), `rows_memo_holds` is False and this streams exactly as before.
        #
        # `note_fold` is deliberately NOT called on this branch: no physical read happened, and
        # counting one would report amplification where the collapse succeeded — the same reason
        # `state.load_path` counts misses and not memo hits (T-12034).
        if rows_memo_holds(seg):
            yield from _rows_memo_current().lines(seg)
            continue
        t0 = time.monotonic()
        try:
            fh = Path(seg).open("r", encoding=encoding, errors=errors)
        except OSError:
            continue
        seen = 0
        try:
            with fh:
                # The block-and-carry splitter itself is `stream_lines` (T-12226) — shared with the
                # kernel-floor secrets reader, so the two cannot disagree about where a line ends.
                # The count is accumulated HERE, as it yields, because the counter is this reader's
                # own accounting and not the splitter's concern.
                for line in stream_lines(fh, _chunk=_chunk):
                    seen += 1
                    yield line
        finally:
            # `finally`, so an abandoned generator (GeneratorExit) still records the read it paid for.
            note_fold(seg, seen, time.monotonic() - t0)


def segment_text(path, *, encoding="utf-8", errors=None) -> str:
    """The WHOLE logical journal at `path` as one string — the drop-in for `path.read_text(...)`.

    Segments are joined with a newline so a segment that does not end in one cannot glue its last row
    onto the next segment's first. With a single segment the result is that segment's text verbatim
    (the join has nothing to join), so a migrated reader's byte-level behaviour is unchanged.

    A missing segment contributes nothing; if NO segment exists the result is `""` — which is what
    every replaced reader's `if not path.exists(): return ...` guard already produced."""
    # T-12034: a physical-read counter site — like `segment_lines`, this fold reads segments itself
    # rather than through `_fold_lines_uncached` (it must preserve the caller's exact decode policy
    # and return raw text), so it reports its own reads. The line count is the text's own, so the
    # denominator it contributes is the same quantity every other primitive contributes.
    parts = []
    for seg in events.segment_paths(path):
        t0 = time.monotonic()
        try:
            text = Path(seg).read_text(encoding=encoding, errors=errors)
        except OSError:
            continue
        note_fold(seg, len(text.splitlines()), time.monotonic() - t0)
        parts.append(text)
    return "\n".join(p for p in parts if p)


def segment_rows(path) -> list:
    """The parsed events of the WHOLE logical journal at `path`, in segment order.

    THE replacement for a reader that folded one file through `fold_rows`. Physical order is preserved
    within each segment and the segments are concatenated in `segment_paths` order, so a caller that
    needs chronology still sorts by `ts` — exactly as it had to before, since union-merge has always
    made physical order not-chronology (SPEC-0002)."""
    out = []
    for seg in events.segment_paths(path):
        out.extend(fold_rows(seg))
    return out


def segment_rows_since(path, since, *, until=None) -> list:
    """The parsed events of the segments of `path` that can OVERLAP `[since, until]`, in segment order.

    THE WINDOWED SIBLING of `segment_rows` above, and built the SAME way — there is no second reader
    here (CHARTER §P5 / §P1 filter 1). The segment SET is resolved once by `events.segment_paths_since`
    (read its contract there: it is a PRE-FILTER on FILE NAMES, never a predicate on rows), and each
    selected member is read through the SAME `fold_rows` primitive, so there is still exactly ONE
    physical read + ONE parse path and a `rows_memo` scope still serves every segment it holds.

    WHY IT EXISTS (SPEC-0190 rule 4, T-12030). Rule 4 requires a reader to declare its horizon, and a
    reader whose own predicate keeps rows inside a trailing window has already declared one: its
    window. Before this, such a reader called `segment_rows` and folded all 93 archive segments to
    answer a 7-day question — building a 596k-row list per call, per view, at every session start.

    THE ANSWER IS UNCHANGED, BY CONSTRUCTION, not by care. The caller keeps its in-loop `ts` test and
    that test still decides every row; this only stops OPENING files whose dated names prove they
    hold nothing the test could admit. `since=None` degrades to `segment_rows` exactly.

    THE MARGIN IS THE CALLER'S. A reader passes the floor it wants compared against — widened past
    its nominal window where its own predicate is looser than the name suggests (see
    `debt._window_segment_floor`, the one place `debt`'s routed readers decide that margin)."""
    out = []
    for seg in events.segment_paths_since(path, since, until=until):
        out.extend(fold_rows(seg))
    return out


def segment_fold_lines(path) -> list:
    """The stripped non-empty LINES of the WHOLE logical journal at `path`, in segment order.

    THE replacement for a reader that folded one file through `fold_lines` — the line-shaped sibling
    of `segment_rows` above, and built the same way: the segment SET is resolved once by
    `events.segment_paths` and each member is read through the SAME `fold_lines` primitive, so there
    is still exactly ONE physical read + ONE parse path and a missing segment contributes nothing.

    WHY THIS EXISTS BESIDE `segment_lines`, which also yields lines (T-11734). The two are NOT
    interchangeable, and the difference is the whole reason a caller picks one:
      * `segment_lines` is a STREAMING generator over RAW lines — deliberately, so a ~175 MB journal
        is never materialised — and it opens each segment itself, so it is never memo-served.
      * this one returns the `fold_lines` CONTRACT: a LIST of stripped, non-empty lines, memo-served
        per segment inside a `rows_memo` scope.
    A reader written against `fold_lines` therefore migrates onto THIS function without moving its
    own behaviour: it would silently gain empty/unstripped lines and lose the request-scoped
    shared-parse collapse (T-11453) if it were handed the streaming sibling instead. Callers that
    genuinely stream keep `segment_lines`; callers that folded a list keep folding a list."""
    out = []
    for seg in events.segment_paths(path):
        out.extend(fold_lines(seg))
    return out


def segment_size(path) -> int:
    """The LOGICAL byte size of the journal at `path` — the SUM over its segments.

    SPEC-0190 rule 8: a size-derived governance bound must never read the live segment alone. Reading
    only the live file would let rotation silently disable the very mechanism that decides whether
    rotation is still warranted — a bound that can never fire again, reporting as healthy. A missing
    segment contributes 0, so an absent journal is 0 exactly as `stat()`-with-an-exists-guard was."""
    total = 0
    for seg in events.segment_paths(path):
        try:
            total += Path(seg).stat().st_size
        except OSError:
            continue
    return total


def segment_stat_key(path) -> tuple:
    """A cache key that changes whenever ANY segment changes — the drop-in for a `(mtime_ns, size)`
    key taken off the live file alone.

    A key computed from the live segment only would serve a STALE cached answer after an archive
    segment changed, which is the same class of miss as rule 8's: correct-looking and wrong."""
    key = []
    for seg in events.segment_paths(path):
        try:
            st = Path(seg).stat()
            key.append((str(seg), st.st_mtime_ns, st.st_size))
        except OSError:
            key.append((str(seg), None, None))
    return tuple(key)


def revision_segment_paths(rev: str, cwd, journal_rel: str = "events.jsonl", *, run=None) -> list:
    """SPEC-0190 rule 4b — the repo-relative journal segments present AT a git revision, in fold order.

    Rule 4 governs readers that go through the shared fold; this exists because a whole CLASS of
    readers does NOT. Five readers in this corpus shell out to git against a literal path (three
    `git show <rev>:events.jsonl`, one `git grep`, one more found by A1's census) and never touch the
    shared iterator, so making that iterator segment-aware does not reach them. At a POST-rotation
    revision the literal path is the LIVE SEGMENT ALONE, and each of them would read a truncated
    journal while looking entirely healthy.

    Returns repo-relative POSIX paths — archive segments first (sorted), the live journal LAST — for
    the caller to feed to its own `git show <rev>:<path>` / pathspec. The paths are returned rather
    than the CONTENT because the five callers stream, grep and parse differently, and imposing one
    read shape here would change behaviour none of them asked to change.

    THE PRE-ROTATION REVISION IS THE HARMLESS CASE, not the hard one (rule 4b says so explicitly): a
    revision from before segmentation has no archive beside it because the single file IS the whole
    journal there, so this returns exactly `[journal_rel]` and every caller is unchanged. Any git
    failure degrades to that same single-element answer — the pre-segmentation behaviour — so a reader
    can never end up with an EMPTY set and silently fold nothing.

    `run` is the injection seam (the `_run_git_cap` shape the worktree callers already hold); it
    defaults to a plain captured `git -C <cwd>` subprocess."""
    live = Path(journal_rel)
    adir = f"{events.ARCHIVE_DIRNAME}/"
    pattern = adir + events.archive_glob(live)
    if run is None:
        def run(argv):                                   # noqa: ANN001 — local default runner
            import subprocess
            return subprocess.run(["git", "-C", str(cwd), *argv], capture_output=True,
                                  text=True, errors="replace")
    try:
        r = run(["ls-tree", "-r", "--name-only", rev, "--", adir])
    except OSError:
        return [journal_rel]
    if getattr(r, "returncode", 1) != 0:
        return [journal_rel]
    archives = sorted(n for n in ((raw or "").strip() for raw in (r.stdout or "").splitlines())
                      if n and Path(n).match(pattern))
    return [*archives, journal_rel]


def revision_segment_show_argvs(rev: str, cwd, journal_rel: str = "events.jsonl", *,
                                run=None) -> list:
    """SPEC-0190 rule 4b — the READ-SHAPE sibling of `revision_segment_paths`: the `git show` argv
    LIST that reads the whole fold at `rev`, in fold order, in ONE git process where that is safe.

    `revision_segment_paths` answers WHICH segments; every rule-4b caller then loops
    `for rel in rels: git show <rev>:<rel>`. That loop is correct and, once rotation has run, it is
    also the whole cost of this reader class: it forks one git per segment, and the segment count
    grows by one per DAY of history. MEASURED on this repo at 88 segments (T-11805): 3.289s CPU
    across 88 forks for the per-segment loop vs 0.421s CPU for ONE `git show` over the same 88 specs —
    7.8x, of which the entire difference is per-process git startup buying no content at all. The two
    reads were verified BYTE-IDENTICAL over 238,404,929 B, because `git show` emits blobs in argv
    order, so batching preserves fold order and completeness exactly rather than approximately.

    Returns a LIST of argvs for the caller to run IN ORDER — never the content — for the same reason
    `revision_segment_paths` returns paths: the callers capture, stream and early-exit differently,
    and imposing one read shape here would change behaviour none of them asked to change. A caller
    keeps its existing loop and simply iterates argvs instead of rels.

    THE FALLBACK IS PART OF THE CONTRACT, not an optimisation detail — it is rule 4b's own failure
    mode in a new form. `git show A B` with B absent exits 128 and writes ZERO bytes to stdout, so an
    unguarded batch over a segment set holding one unresolvable spec would read NOTHING where the
    per-segment loop read every other segment: a truncated fold looking perfectly healthy. So which
    specs resolve is settled FIRST, by one `git cat-file --batch-check` (rc 0 even when a spec is
    missing — it names it `<spec> missing`); unresolvable specs are DROPPED, which is exactly what
    the per-segment loops already do on a non-zero returncode. If the probe itself cannot run, or
    nothing resolves, this degrades to the PER-SEGMENT argvs — the shipped behaviour, verbatim — so a
    caller can never end up reading less than the loop it replaced.

    `run` is the same injection seam `revision_segment_paths` takes and is passed through to it."""
    rels = revision_segment_paths(rev, cwd, journal_rel, run=run)
    per_segment = [["show", f"{rev}:{rel}"] for rel in rels]
    if len(rels) < 2:
        return per_segment                      # nothing to batch — the pre-rotation case, unchanged
    specs = [f"{rev}:{rel}" for rel in rels]
    # The probe feeds its spec list on STDIN, which the injected `run` seam does not carry: callers
    # inject a captured `git -C <cwd>` ARGV runner with no stdin channel. So the probe is run directly
    # here — the seam stays exactly what it is everywhere else — and any failure of it degrades to the
    # per-segment argvs below, which is the shipped behaviour.
    try:
        import subprocess
        pr = subprocess.run(["git", "-C", str(cwd), "cat-file", "--batch-check"],
                            input="\n".join(specs), capture_output=True, text=True,
                            errors="replace")
    except (OSError, ValueError):
        return per_segment
    if getattr(pr, "returncode", 1) != 0:
        return per_segment
    lines = (pr.stdout or "").splitlines()
    if len(lines) != len(specs):
        return per_segment                       # cannot align probe to spec — do not guess
    ok = [spec for spec, line in zip(specs, lines)
          if line.strip() and not line.rstrip().endswith(("missing", "ambiguous"))]
    if not ok:
        return per_segment
    return [["show", *ok]]


def _bounded_superset_lines(path, tokens, *, start=0, max_bytes=None, drop_fragment=False,
                            _opener=None, _raw=None):
    """T-10939 — the ONE bounded-prescan primitive: a bounded physical read, then a cheap byte-substring
    SUPERSET filter. Returns the surviving RAW lines (bytes), never parsed events.

    This shape had been written TWICE — `tail_scan_events` (T-10897) and `_dispatch_status_events`'
    `include_types` prescan (T-10858) — differing only in how the read is bounded (a `max_bytes` tail
    from EOF vs a line-aligned `start` offset) and in how many tokens are matched. Both are now
    instances of this one function, so the shape cannot drift (CHARTER §P1 filter 1 — extend the
    existing analog, do not keep a parallel; §P5 no-parallel-paths; SPEC-0133 rule 5 admits no second
    dispatch-journal path). It returns BYTES on purpose: the two callers have deliberately different
    decode policies (replace-and-parse vs skip-on-UnicodeDecodeError), so decoding here would force one
    caller's policy onto the other and change behaviour that neither card asked to change.

    `tokens=None` keeps every line (an unfiltered bounded read); otherwise a line survives iff ANY
    token is a byte-substring of it — only ever a SUPERSET, so the caller's exact parsed check still
    decides membership. `drop_fragment` drops the first line when the read started mid-file (a
    `max_bytes` tail cuts the first line in half; a line-aligned `start` does not). `_opener` is the
    injection seam the byte-counting tests read through.

    `_raw` (T-12208, SPEC-0190 rule 10) — the ALREADY-READ bytes of the bounded region, handed over by
    a caller that has just read them from its own open handle (`_shared_prefix_start(with_tail=True)`).
    When given, this function opens NOTHING: the artifact was already folded once, and opening it again
    to re-read the same span is exactly the per-artifact repeat rule 10 forbids. The bytes MUST already
    have the bound applied — they are spliced in where `raw` would have landed, so the filter below is
    the SAME one every other caller runs (no second matcher, no parallel path). `start` still governs
    `drop_fragment` only.
    """
    if _raw is not None:
        raw = _raw
    else:
        opener = _opener or (lambda p: p.open("rb") if hasattr(p, "open") else open(p, "rb"))
        with opener(path) as fh:
            if max_bytes is not None:
                size = fh.seek(0, os.SEEK_END)
                start = max(0, size - max_bytes)
                fh.seek(start)      # unconditional: the SEEK_END probe above left us AT the end, so a
                                    # `start == 0` that skipped the rewind would read zero bytes
            elif start > 0:
                fh.seek(start)
            raw = fh.read()
    lines = raw.splitlines()
    if drop_fragment and start > 0 and lines:
        lines = lines[1:]
    if tokens is None:
        return lines
    wanted = tuple(t.encode("utf-8") if isinstance(t, str) else bytes(t) for t in tokens)
    match = _superset_matcher(wanted)
    if match is None:
        return []                      # no token can match — the `any(...)`-over-empty answer, kept
    return [bline for bline in lines if match(bline)]


def tail_scan_events(path, token, *, max_bytes, _opener=None):
    """T-10897 — parse the events in the LAST `max_bytes` of a journal whose RAW line contains `token`.

    The SAME shape `_dispatch_status_events`' include_types prescan uses, applied to a fingerprint
    lookup instead of an envelope type: a BOUNDED physical read, then a cheap byte-substring SUPERSET
    filter, with the caller's EXACT parsed check deciding membership. The prescan is only ever a
    superset — a line that merely MENTIONS the token in its free text survives it and is returned for
    the caller to REJECT on the parsed fields — so the answer equals filtering a full parse of the
    same span. This is that reader made reusable, NOT a second journal path (CHARTER §P1 filter 1):
    a raw `token in read_text()` decides on a MENTION, which lets any line writing ABOUT a record
    impersonate the record, and costs a whole-file read (measured 0.40s / 125MB, 2026-08-10).

    The read starts at `size - max_bytes`, so the first line of a truncated span is a FRAGMENT and is
    dropped (an unparseable half would otherwise be a silent miss). `_opener` is the injection seam
    the tests count bytes through; it defaults to a plain binary open of `path`.

    T-10939 — the bounded read + superset filter itself now lives ONCE, in `_bounded_superset_lines`;
    this function is that primitive plus its own decode+parse policy. What the docstring above always
    promised ("that reader made reusable, NOT a second journal path") is now literally true of the
    dispatch-status reader too, which used to carry its own copy of the same shape.

    T-11444 / SPEC-0190 rule 4 — ITS DECLARED HORIZON IS THE LAST `max_bytes`, AND IT STAYS THERE.
    Rule 4 asks every reader to declare a horizon and then honour it; this one's horizon is the
    journal's physical END, sized far below the live window (its callers ask NOW questions — is a
    land queued, did this branch just complete), so it reads the LIVE segment alone by design and is
    NOT widened to the segment set. Widening it would be the second half of the same rule's defect:
    "a reader that folds the whole archive to answer a question about the last seven days". A caller
    that needs history beyond the tail takes the full segment-aware fold (`segment_rows`), exactly as
    `_iter_events_tail` falls back to `_iter_events`.
    """
    out = []
    for bline in _bounded_superset_lines(path, [token], max_bytes=max_bytes,
                                         drop_fragment=True, _opener=_opener):
        try:
            ev = json.loads(bline.decode("utf-8", "replace"))
        except ValueError:
            continue
        if isinstance(ev, dict):
            out.append(ev)
    return out

def _row_epoch(ts) -> "float | None":
    """The epoch seconds of a journal row's `ts`, or None when it cannot be read.

    The same reading `batch_landing#_land_queue_row_epoch` performs, homed here because
    `tail_scan_events_covering` below must date a row WITHOUT importing its callers (this module is
    the leaf every one of them imports, never the other way round)."""
    if not ts:
        return None
    try:
        s = str(ts).strip().replace("Z", "+00:00")
        d = _dt.datetime.fromisoformat(s)
        if d.tzinfo is None:
            d = d.replace(tzinfo=_dt.timezone.utc)
        return d.timestamp()
    except Exception:                      # noqa: BLE001 — undatable row: no boundary evidence
        return None


_BACKWARD_SCAN_CHUNK_BYTES = 4 * 1024 * 1024
_BACKWARD_SCAN_HEAD_LINES = 64      # enough undatable leading rows to date any real slice


def _backward_superset_chunks(path, tokens, *, chunk_bytes=None, _opener=None):
    """T-11904 — `_bounded_superset_lines`' contract (a bounded physical read, then a cheap byte-
    substring SUPERSET filter) applied INCREMENTALLY BACKWARDS, so the reader's memory stops
    scaling with how far back it reads. Yields `(lines, start_offset)` per slice, NEWEST slice
    first, each `lines` in file order and already superset-filtered.

    WHY THE INCREMENTAL FORM EXISTS AT ALL, given the primitive above already reads a bounded tail.
    The two bound DIFFERENT things and only one of them is the bound a horizon-sized read needs.
    `_bounded_superset_lines` bounds the SPAN — it reads `max_bytes` in one `read()` and then
    materialises every line in it — so its memory is O(span) and a caller that must reach further
    back can only do so by asking for a bigger span and paying for it in resident bytes. Measured on
    this repo's journal (2026-08-30): the 53MB span that covers the land readers' declared 72h costs
    ~0.10s but 120-131MB resident, and ~95k line objects, because the whole span is materialised at
    once. TIME was never the constraint (~500MB/s, against a land verify that runs 30-60s+); MEMORY
    was, and it is the only reason a byte ceiling had to exist at all. Walking the same bytes in
    fixed slices and keeping only the MATCHING lines makes memory O(chunk + matches) — independent
    of the span — which is what lets a reader be bounded by its DECLARED HORIZON instead of by a
    constant that covers a shrinking fraction of that horizon as the write rate grows.

    IT IS THE SAME MECHANISM, NOT A SECOND JOURNAL PATH (CHARTER §P1 filter 1 / §P5). Same
    `_superset_matcher` predicate, same bytes-in/bytes-out policy, same "only ever a SUPERSET, the
    caller's exact parsed check still decides membership" contract. What differs is where the read
    stops, which is the caller's business and never the primitive's.

    LINE ALIGNMENT IS THE WHOLE CORRECTNESS ARGUMENT, so it is explicit rather than incidental. A
    fixed-size slice cuts a line in half at BOTH ends. This walker snaps each slice's OLD end to the
    first newline inside it and CARRIES the leading fragment into the next (older) slice, where it is
    re-joined to the bytes that precede it. So every line is yielded EXACTLY ONCE and never as a
    fragment: without the carry the line straddling each slice boundary would be dropped by the newer
    slice as a fragment and read as truncated JSON by the older one — one silently lost row per
    boundary, which on a 4MB chunk over a 53MB span is a dozen chances to miss the very row the read
    exists to find. The FIRST slice (the file's tail) has no newer neighbour and so carries nothing;
    the LAST slice reaches offset 0, where the leading bytes ARE a complete line and are kept.

    `head` IS UNFILTERED ON PURPOSE, and it is the whole reason the walk yields two lists instead of
    one. A caller dating the window must date it on the lines the window ACTUALLY CONTAINS, never on
    the ones its token happened to match: deciding a boundary on filtered rows reads a QUIET window —
    one genuinely covered, in which no matching row happens to appear — as short, and then reports a
    shortfall that is not there (the property T-11816 established and this walk must not lose). The
    unfiltered lines are materialised inside this slice anyway, so handing back its first few costs
    nothing and keeps the O(chunk) bound.

    `tokens=None` keeps every line, exactly as in `_bounded_superset_lines`.
    """
    opener = _opener or (lambda p: p.open("rb") if hasattr(p, "open") else open(p, "rb"))
    chunk = max(1, int(chunk_bytes or _BACKWARD_SCAN_CHUNK_BYTES))
    match = None
    if tokens is not None:
        wanted = tuple(t.encode("utf-8") if isinstance(t, str) else bytes(t) for t in tokens)
        match = _superset_matcher(wanted)
        if match is None:
            return                         # no token can match — the `any(...)`-over-empty answer
    with opener(path) as fh:
        end = fh.seek(0, os.SEEK_END)
        carry = b""
        while end > 0:
            start = max(0, end - chunk)
            fh.seek(start)
            raw = fh.read(end - start) + carry
            if start > 0:
                # Snap to the OLD end's line boundary and hand the leading fragment to the next
                # (older) slice, which holds the bytes that complete it.
                cut = raw.find(b"\n")
                if cut < 0:                # no boundary inside this slice — grow the carry, read on
                    carry = raw
                    end = start
                    continue
                carry, raw = raw[:cut + 1], raw[cut + 1:]
            else:
                carry = b""
            lines = raw.splitlines()
            yield (([bl for bl in lines if match(bl)] if match is not None else lines),
                   lines[:_BACKWARD_SCAN_HEAD_LINES], start)
            end = start


def tail_scan_events_covering(path, token, *, horizon_s, now=None, base_bytes,
                              max_bytes=None, spend_out=None, _opener=None,
                              _has_older=None):
    """T-11816 — `tail_scan_events` whose window is sized by the ANSWER'S OWN LIFETIME, in TIME,
    with the byte span DERIVED. Returns `(rows, covered)`.

    WHY A SECOND SIZING AND NOT A BIGGER NUMBER. `tail_scan_events` declares its horizon in BYTES,
    which is the right unit only when the question itself is about the last N bytes. For a reader
    whose answer has a LIFETIME — a rule-4 one-round mark, a rule-12 reddened composition, a declared
    rebaseline inside its freshness window — bytes and lifetime are related only by the journal's
    write RATE, so the window shrinks in the only dimension that matters exactly when the journal
    grows fastest, i.e. under contention, which is when the answer is load-bearing. Measured on this
    repo's own journal (2026-08-28): a 512KB tail covered 36 minutes, while the gap a rule-4 mark has
    to outlive ran to a median of 30 minutes and a maximum of 49.5 hours over 121 observations. The
    marking row of an ineligible branch therefore sat past the bound and the read returned the EMPTY
    set — twice, on two different branches (T-11814, and again live at this card's analysis). Raising
    the constant relocates that cliff; declaring the horizon in the unit the answer is actually
    measured in removes it, and the byte span then follows the journal instead of bounding it.

    THIS IS THE EXISTING READER'S SHAPE, NOT A SECOND JOURNAL PATH (CHARTER §P1 filter 1 / §P5). It
    goes through the SAME `_bounded_superset_lines` primitive, the same byte-substring SUPERSET
    prescan and the same decode+parse policy as `tail_scan_events`, which STAYS exactly as it is for
    every caller whose horizon genuinely is the last N bytes. The only thing added is how far back to
    read, and whether the read got there.

    COVERAGE IS DECIDED ON THE WINDOW, NEVER ON THE FILTERED ROWS. The span is read ONCE and
    UNFILTERED; the WINDOW BOUNDARY is the ts of the oldest parseable line in it, and the token filter
    is applied afterwards to produce the returned rows. Deciding coverage on the token-filtered oldest
    row instead would read a QUIET horizon — one the window genuinely covers, but in which no matching
    row happens to appear — as truncated, over-read to the ceiling, and then report a shortfall that
    is not there. A loudness that fires when nothing is wrong is the fastest way to make the signal
    ignored, which would defeat the very discrimination this function exists to provide.

    `covered` IS TRUE iff the read reached offset 0 — the whole live segment, so nothing older exists
    to miss — OR the window boundary is at/older than `now - horizon_s`. A span with no parseable line
    at all is covered iff it reached offset 0: an EMPTY journal is fully covered and silent, while a
    span that ran out of file before the horizon is NOT. That is the discrimination the callers need:
    today a truncated read and a genuinely-nothing-marked read produce the same empty answer, which is
    why the defect ran unnoticed. This function never decides what to DO about a shortfall — the
    caller owns the polarity (every one of them fails OPEN) and the reporting.

    ROTATION NEEDS NO SEPARATE HANDLING, and that is a consequence rather than an omission. The read
    stays on the LIVE segment, which SPEC-0190 rule 4 requires while the declared horizon is under the
    live window (7 days here). If rotation ever leaves the live segment starting LATER than the
    horizon, the boundary test fails and the read reports `covered False` — loudly — instead of
    silently answering short. A horizon that legitimately needs the archive takes the segment-aware
    fold, exactly as rule 4 says.

    T-11904 — THE READ IS BOUNDED BY THE DECLARED HORIZON, NOT BY A CONSTANT, because a constant in
    BYTES cannot bound a window declared in TIME. T-11816 (above) converted this reader's HORIZON
    from bytes to time and left its CAP in bytes; this is the other half of that conversion. The two
    are related only by the journal's write RATE, so a fixed `max_bytes` covers a shrinking fraction
    of a fixed window as that rate grows — measured on this repo 2026-08-30: the land readers'
    48MB cap reached 64.8h against a DECLARED 72h, and had done so on every land watched that day.
    Raising the constant relocates that cliff exactly as T-11816 says of the constant IT replaced,
    which is why `max_bytes` is now OPTIONAL and the land readers pass none.

    WHAT MAKES DROPPING THE CAP SAFE IS A CHEAPER READ, NOT A BIGGER BUDGET. The cap existed to bound
    MEMORY: the old sizing re-read the whole tail in one `read()` and materialised every line in it,
    so resident bytes scaled with how far back the reader went (120-131MB for the 53MB span that
    covers 72h today, ~1.2GB at a ten-fold write rate). The walk now goes through
    `_backward_superset_chunks`, which keeps only the MATCHING lines of one slice at a time, so
    memory is O(chunk + matches) whatever the span — and the read stops at the FIRST slice that
    crosses the horizon rather than overshooting by an estimated margin. That retires the three-pass
    density estimator and its 25% margin along with the constant (CHARTER §P1 F3): a derived span was
    only ever a way to guess how big a single read had to be, and there is no longer a single read.

    ROTATION IS NO LONGER READ AS COVERAGE. Reaching offset 0 means "nothing older exists IN THIS
    SEGMENT", which is the same thing as "nothing older exists" only when no ARCHIVE segment sits
    beside the journal (SPEC-0190 §Archive segments). Where one does, a freshly-rotated live segment
    younger than the declared horizon would otherwise report `covered True` while silently missing
    the history it declared — the same declared-versus-delivered gap this reader exists to surface,
    in its worst form, since nothing would print. So the segment start counts as coverage only when
    the journal has no older segment; otherwise the boundary decides, and a short live segment is
    reported as the rule-4 archive-branch condition it is.

    `spend_out`, when a list, receives the bytes the walk actually read — so a caller reporting a
    shortfall can name what it cost rather than quoting a ceiling that no longer exists.

    T-11924 — `_has_older` EXISTS SO THIS SAME WALK CAN READ AN ARCHIVE SEGMENT, and it is an
    injection rather than a rewrite because the coverage RULE above is already right; the only
    thing that is wrong off a non-live segment is the ONE question that rule asks of the path.
    `_has_older_segment` answers "does an `archive/` directory sit beside this file", which is
    the correct reading of "is there older history" for the LIVE segment and a FALSE one for an
    archive segment — an archive segment has no `archive/` beside it, so the default would
    certify its offset 0 as full coverage while OLDER archive segments still sit next to it.
    That is the same declared-versus-delivered gap this function exists to surface, in the one
    place it would go unprinted. A caller that already knows a segment's POSITION in the
    ordered set (`archive_scan_events_covering` below) answers the question itself; every
    existing caller passes nothing and is byte-identical.
    """
    now = time.time() if now is None else now
    cutoff = now - float(horizon_s)
    chunk = max(1, int(base_bytes))
    ceiling = None if max_bytes is None else max(chunk, int(max_bytes))
    try:
        size = _journal_span_size(path, _opener=_opener)
    except Exception:                      # noqa: BLE001 — unmeasurable size: judge on the boundary
        size = None
    slices: "list[list]" = []
    boundary = None
    reached_start = False
    read_bytes = 0
    saw_slice = False
    for lines, head, start in _backward_superset_chunks(path, [token], chunk_bytes=chunk,
                                                        _opener=_opener):
        saw_slice = True
        slices.append(lines)
        if size is not None:
            read_bytes = max(read_bytes, size - start)
        # The oldest parseable row of the oldest slice read so far IS the window boundary — dated on
        # the slice's UNFILTERED head, never on its matched rows, so a genuinely-covered window in
        # which nothing matched still reads as covered (T-11816's property, kept).
        for bline in head:
            try:
                ev = json.loads(bline.decode("utf-8", "replace"))
            except ValueError:
                continue
            if isinstance(ev, dict):
                ts = _row_epoch(ev.get("ts"))
                if ts is not None:
                    boundary = ts if boundary is None else min(boundary, ts)
                    break
        reached_start = start <= 0
        if reached_start or (boundary is not None and boundary <= cutoff):
            break
        if ceiling is not None and read_bytes >= ceiling:
            break
    if not saw_slice:
        reached_start = True               # nothing to read IS reading all of it — an empty journal
    if isinstance(spend_out, list):        # is fully covered and silent, exactly as before
        spend_out.append(int(read_bytes))
    older_q = _has_older_segment if _has_older is None else _has_older
    covered = (boundary is not None and boundary <= cutoff) or (
        reached_start and not older_q(path))
    out = []
    for lines in reversed(slices):
        for bline in lines:
            try:
                ev = json.loads(bline.decode("utf-8", "replace"))
            except ValueError:
                continue
            if isinstance(ev, dict):
                out.append(ev)
    return out, covered


def _has_older_segment(path) -> bool:
    """Whether an ARCHIVE segment of the same logical journal sits beside `path` — i.e. whether
    reaching this file's offset 0 still leaves history unread (SPEC-0190 rule 1 + §Archive segments).

    Reads the naming rule from `events`, never a second copy of it (CHARTER §P5). Fail-CLOSED on any
    unreadable directory: an unanswerable question must not be allowed to certify coverage."""
    try:
        d = events.archive_dir(path)
        if not d.is_dir():
            return False
        return any(d.glob(Path(events.archive_glob(path)).name))
    except Exception:                      # noqa: BLE001 — cannot tell: assume history exists
        return True


def archive_scan_events_covering(path, token, *, horizon_s, now=None, base_bytes,
                                 max_bytes=None, spend_out=None, _opener=None, _scan=None):
    """T-11924 (SPEC-0190 rule 4) — THE ARCHIVE BRANCH: continue a live-segment read BACKWARDS
    through the archive segments of the same logical journal. Returns `(rows, covered)`.

    WHY THIS EXISTS. `tail_scan_events_covering` above deliberately stays on the LIVE segment and
    reports `covered False` when its declared horizon reaches past that segment's start — and its own
    docstring names the remedy: *"a horizon that legitimately needs the archive takes the segment-aware
    fold, exactly as rule 4 says."* Nothing implemented that fold, so every land-formation reader whose
    horizon outran the live segment printed a DEFECT line and then returned the truncated answer
    anyway. Measured on kupiclub 2026-09-01: the live segment reached back to 2026-08-26T17:28:41Z
    against the 7-day pinned-supersession declaration, TWICE in one day (X-1202, X-1204), so an arming
    row that had rotated into archive was invisible and the branch it should have excluded rode the
    batch. This is that fold.

    ARCHIVE SEGMENTS ONLY — THE LIVE READ IS THE CALLER'S AND IS NEVER REPEATED. The caller has
    already read the live segment and already knows it fell short; re-reading it here would pay the
    whole live span a second time on exactly the branch that is already the expensive one. So this
    walks `events.segment_paths(path)[:-1]` — the archive members, which that resolver returns sorted
    OLDEST-FIRST with the live segment LAST — and the caller concatenates.

    NEWEST-FIRST, AND IT STOPS AT THE FIRST SEGMENT THAT REACHES THE CUTOFF. The declared horizon is
    a distance BACKWARDS from now, so the segment adjacent to the live one is the one most likely to
    contain the boundary; walking oldest-first would read the whole archive to answer a question about
    the last seven days, which rule 4 names as a defect in its own right ("a reader that folds the
    whole archive to answer a question about the last seven days"). Rows are accumulated OLDEST-FIRST
    regardless of the walk direction, so the caller's `archive_rows + live_rows` is the ONE logical
    history in order (SPEC-0190 rule 5 — partition-stable order).

    THE SAME PRIMITIVE, NOT A SECOND JOURNAL PATH (CHARTER §P1 filter 1 / §P5). Every member is read
    through `tail_scan_events_covering` itself: same `_backward_superset_chunks` walk, same byte-
    substring SUPERSET prescan, same decode+parse policy, same coverage rule, same O(chunk + matches)
    memory bound. The only thing this adds is WHICH files get walked — which is precisely the
    "extend the fold to take a segment SET" shape rule 4 prescribes, and the reason it names that
    extension is so an implementer finds it instead of reinventing it.

    COVERAGE IS ASKED OF EACH MEMBER WITH ITS POSITION SUPPLIED, never of its filename. A member at
    index `i > 0` in the ordered set still has older siblings, so reaching ITS offset 0 is not
    coverage; the oldest member (`i == 0`) has none, so reaching its offset 0 means the whole logical
    history has been read and there is nothing left to miss. That is what `_has_older` above is for.

    THE BOUND, STATED WHERE THE NEXT IMPLEMENTER READS IT (the audit-pre residual absorbed on this
    card). This branch answers exactly ONE question — *is there older history BEYOND the live
    segment* — and repairs exactly the shortfall that comes from the live segment being younger than
    the declared horizon. It CANNOT repair an INTRA-LIVE gap, i.e. a live read that stopped on its own
    `max_bytes` ceiling before exhausting the live segment: the rows it would be missing are in the
    live file, not in the archive. That gap is unreachable today because all four `_land_horizon_rows`
    callers pass NO `max_bytes` (T-11904 retired the ceiling constant precisely so a number in bytes
    could not bound a window declared in time), so `covered False` provably means the live segment was
    exhausted. A future caller that reintroduces a finite ceiling would need to close its own gap
    there, not here — no guard is added for a caller that does not exist (CHARTER §P1 filter 4).

    NO ARCHIVE, NO REPAIR — and that answer is `False`, not `True`. With no archive directory or no
    archive segment there is genuinely nothing older to reach, but the caller's live read has already
    reported that it could not cover its declared horizon, so certifying coverage here would silence
    a real shortfall on the strength of having found nothing. Fail-OPEN on any error inside a member's
    scan, matching every caller's polarity: the walk ends with whatever it has gathered and the rows
    it did read are kept, because a partial answer is what these readers already fail open to.
    """
    scan = _scan or tail_scan_events_covering
    try:
        segs = list(events.segment_paths(path))
    except Exception:                      # noqa: BLE001 — unresolvable segment set: no repair
        segs = []
    archives = segs[:-1] if segs else []   # oldest-first; the live segment is always the last element
    rows: list = []
    covered = False
    total = 0
    for i in range(len(archives) - 1, -1, -1):
        seg = archives[i]
        spend: list = []
        try:
            got, seg_covered = scan(
                seg, token, horizon_s=horizon_s, now=now, base_bytes=base_bytes,
                max_bytes=max_bytes, spend_out=spend, _opener=_opener,
                _has_older=(lambda _p, _i=i: _i > 0))
        except Exception:                  # noqa: BLE001 — fail-open: keep what the walk already has
            break
        total += int(spend[0]) if spend else 0
        rows = list(got or ()) + rows      # older segment's rows precede the ones already gathered
        if seg_covered:
            covered = True
            break
    if isinstance(spend_out, list):
        spend_out.append(int(total))
    return rows, covered


def _journal_span_size(path, *, _opener=None) -> int:
    """The physical size of the file `_bounded_superset_lines` reads — measured THROUGH the same
    `_opener` seam, so the byte-counting fixtures that inject an opener see one consistent file."""
    opener = _opener or (lambda p: p.open("rb") if hasattr(p, "open") else open(p, "rb"))
    with opener(path) as fh:
        return fh.seek(0, os.SEEK_END)


# ── Observability constants (T-10386, owner_directive 2026-07-11 item 1) ─────────────────────────────
# The sanctioned server-resource numbers the dispatch / watch / readiness surfaces ECHO instead of ad-hoc
# literals (owner: «система должна подсказывать эти цифры» — the system must SUGGEST these numbers). Homed
# HERE — the shared dispatch-observability config carrier (alongside DISPATCH_CLASS_VOCAB) — so every
# consumer reads ONE source over the EXISTING `from lib import journal` edge: the host `--watch-interval` /
# `--watch-timeout` argparse defaults, dispatch.py's `--watch` fallback + readiness render, and the
# readiness advisor in THIS module. This is the card's "shared config home" alternative to bin/lib/
# worktree.py (where the sibling _VERIFY_WORKER_CEILING lives): worktree.py would force this journal LEAF
# (which imports zero sibling libs) to import the big worktree module, so the import graph selects journal.
# Measurement basis for the CADENCE (T-12211, 2026-09-07 — supersedes the T-10371 reading that set 300).
# What a tick COSTS: one `journal query --fleet-verdict` fold, measured off this repo's own cli_invoked
# rows in the post-T-12205 window (n=8) — duration_ms median 11951 (max 16067), reads.wall_ms median
# 7394, 98 segments, ~395k rows parsed. That is NOT cheap, and it did NOT get cheaper: T-10371's
# «11-15s per read» still describes the fold today (T-12205 removed the per-request read amplification
# while the journal grew to 98 segments). What was WRONG was the INFERENCE, not the arithmetic — a ~12s
# tick under a 60s interval is a bounded ~20% duty cycle for ONE armed watcher, and since the cost sits
# well under the interval, ticks never overlap or pile up: the cadence stays the binding constraint.
# What the cadence BUYS: `dispatch --watch` confirms a verdict across `--watch-confirm-ticks` (default 2)
# consecutive ticks, so terminal-seam detection is bounded by 2 x interval. At 300 that is ~10 min — the
# 9.5 min measured on 2026-09-07, when T-12197's land at 04:46:51Z was not reported until 04:56:21Z and
# the dependent card went out ~8 min late on an owner poke. At 60 the same seam bounds to ~2 min.
# The owner's standing directive of 2026-09-06 («своевременно пускай другие в работу») prices that
# latency above the fold. `--watch-interval` remains the per-call override for a genuinely slow fleet.
WATCH_POLL_INTERVAL_SECS = 60     # `dispatch --watch` poll cadence
WATCH_MAX_RUNTIME_SECS = 1800     # `dispatch --watch` max runtime; on expiry the watcher exits with a
                                  # reassess-and-rearm cue, NEVER silent (was the ad-hoc hardcoded 3600s)
MAX_FLEET_WIDTH = 8               # per-server owner bound on concurrent workers (replaces the ad-hoc ~5
                                  # guidance); the dispatch-readiness advisor ECHOES this as a SUGGESTED
                                  # bound the controller judges against — it is NEVER used to clamp
                                  # recommended_wave_ceiling (SPEC-0133 §6: «never a coded cap»; a coded
                                  # cap would be the forbidden orchestrator, CHARTER §6)


def max_fleet_width() -> int:
    """T-12219 — the per-server worker bound, machine file first, `MAX_FLEET_WIDTH` otherwise.

    A PER-SERVER bound is the exact thing the machine-scoped settings file exists for (SPEC-0193),
    and this one is unusually safe to move there: SPEC-0133 §6 forbids it from ever CLAMPING
    `recommended_wave_ceiling` («never a coded cap»), so it decides nothing and only advises.
    Resolved per call rather than at import so a `config set` is observed without a restart, and
    falling back to the module constant keeps the absent-file default and every test that patches
    `MAX_FLEET_WIDTH` working unchanged."""
    try:
        from lib import machine_settings      # deferred: keeps the hot import graph unchanged
        return int(machine_settings.resolve("lib.journal.MAX_FLEET_WIDTH",
                                            MAX_FLEET_WIDTH))
    except Exception:            # noqa: BLE001 — the settings STACK is never a
                                 # prerequisite either (SPEC-0193 rule 6 — the
                                 # `remote_workers_override` precedent)
        return MAX_FLEET_WIDTH


def _dispatch_cause_tag(events, task_id, cls, detail, *, _dispatch_task_of):
    """T-9751 — a short controlled-vocabulary cause-tag for a HALTED dispatch. Lets a controller route
    a blocked task WITHOUT opening each worker's events.jsonl. Returns a member of
    DISPATCH_CAUSE_TAGS, or None.

    T-11618 — this function is now the SCOPE GUARD only; the cause itself is DERIVED from the machine
    record by `_derived_halt_cause` (which is where the derivation and its measured grounds are
    documented). What changed is the SOURCE, not the surface: it used to substring-match the halting
    worker's free-text `reason`/`ra_key` into three buckets, so `verify-flake` won on a bare "verify"
    or "test" appearing in prose and became a catch-all — six mislabels in ~24h across five cards,
    with nothing having flaked in any of them.

    SCOPE — unchanged, and still narrow because this is a ROUTING signal: `cls == 'TERMINAL'` AND
    `detail` in ('halt', either blocked-on-land reading — T-10788, the escalation TARGET differs, the
    routing need does not). So a done/wont-do terminal, a T-9750 main-status-reconciled done, a
    `stopped(controller)` terminal, and a stale halt SUPERSEDED by a live worker (a non-TERMINAL
    class, which covers the T-10394 live-land override) all carry NO tag.

    A row in scope with NO halt of its own still carries no tag — the tag describes a halt, and
    minting `unknown` for a row that never halted would state a blocker where none is claimed. Every
    row that DOES carry a halt gets a member: `unknown` is the explicit reading for "halted, but the
    journal records no blocker", which is exactly the case that used to fall through to verify-flake.

    `events` must be the UNSCOPED stream (the land arm matches `land_completed` by branch)."""
    if cls != "TERMINAL" or detail not in ("halt", *_HALT_DETAILS_BLOCKED_ON_LAND):
        return None
    if _newest_halt(events, task_id) is None:
        return None
    return _derived_halt_cause(events, task_id, _dispatch_task_of=_dispatch_task_of)


def _dispatch_halt_marker_ts(events, task_id, cls, detail, *, _dispatch_task_of):
    """T-11344 — the HALT MARKER's OWN timestamp for a marker-derived row. PURE (reads, never mutates).
    Peer of `_dispatch_cause_tag` right above: same reversed scan for the task's NEWEST
    `bg_dispatch_halted`, same "None unless this row is genuinely marker-derived" discipline. Returns
    the marker's `ts` string, or None.

    WHY it exists. A dispatch row's CLASS and `cause=` come from the halt marker, while its `last=`
    clock is the chain's most recent event OF ANY TYPE. The two can be hours apart and the row did not
    distinguish them: measured 2026-08-20, `--dispatch-status --task T-10971` rendered
    `TERMINAL(blocked_on_land(needs-controller)) last=2026-08-20T16:08:38Z cause=verify-flake` where the
    16:08:38Z event was a `worktree_synced` and the marker behind the class/cause was ~5h older. Two
    controllers misread that shape within one hour, the second escalating a block that did not exist.
    So the marker's own clock is rendered BESIDE the class it produced — the reader stops having to do
    a manual journal lookup to know which clock it is looking at.

    SCOPE — `_HALT_DETAILS_MARKER_MINTED`, deliberately WIDER than the cause-tag's. The cause-tag is a
    ROUTING signal, so it is narrow (only blocks a controller must route). This is a PROVENANCE clock,
    so it belongs to every detail minted from a marker, `stopped(controller)` included.

    NEUTRAL BY CONTRACT: this returns a TIMESTAMP and nothing else — no age, no freshness verdict, no
    stale/old/expired judgement. The external auditor's own condition on this change (ad-hoc GREEN
    2026-08-20, decisions/halt-marker-freshness-audit-adhoc.yaml): a halt marker stays FULLY actionable
    until positively cleared, and a judgemental label would quietly erode that fail-closed intent. The
    reader is given both clocks and judges; the renderer never judges for it."""
    if cls != "TERMINAL" or detail not in _HALT_DETAILS_MARKER_MINTED:
        return None
    halt = next((e for e in reversed(events)
                 if e.get("type") == "bg_dispatch_halted" and _dispatch_task_of(e) == task_id), None)
    return (halt.get("ts") or None) if halt is not None else None


def _dispatch_last_event_type(events, last_ts):
    """T-11344 — the TYPE of the event the row's `last_ts` came from, read from the row's OWN chain by
    matching that ts (newest match wins, mirroring how `last_ts` is taken as the chain's newest event).
    PURE. Returns None when nothing matches.

    This is the second half of the same defect: naming the last event's type is what tells a reader
    that a fresh `last=` belongs to a `worktree_synced` rather than to the halt. `cmd_journal_fleet_verdict`
    already renders `last={ts}({type})`; this brings `cmd_journal_dispatch_status` to that parity
    (CHARTER §P1 F1 — extend the sibling that already solves it).

    INDEPENDENTLY SOURCED, on purpose: it resolves the LAST-EVENT clock, `_dispatch_halt_marker_ts`
    resolves the MARKER clock, and neither is derived from the other — so where the two coincide the
    row honestly shows one timestamp twice, and where they differ it shows the real interval."""
    if not last_ts:
        return None
    return next((e.get("type") for e in reversed(events or []) if (e.get("ts") or "") == last_ts), None)


def _dispatch_phase(events):
    """T-9748 — which lifecycle PHASE a dispatched worker is currently in, from the stage of its
    MOST-RECENT stage_entered event. Returns 'audit' for the external-audit stages (Audit-pre /
    Audit-post) — the journal-SILENT, legitimately-minutes-long stage the T-9747 dispatch-log
    heartbeat covers — and 'normal' for every other stage (a tight staleness window, corroborated by
    proc_alive / the dispatch-log heartbeat before hang_suspect). Defaults 'normal' when no stage is
    recorded yet (a booting worker is separately covered by the near-launch grace). PURE (no I/O).
    NOTE: LAND is deliberately NOT a phase here — a worker mid-land reads closed_pending_land
    (task_closed + live claim) and returns ABOVE the staleness split, covered by the T-9601
    land-verify heartbeat."""
    for e in reversed(events):
        if e.get("type") == "stage_entered":
            d = e.get("data")
            stage = d.get("stage") if isinstance(d, dict) else None
            return "audit" if stage in ("Audit-pre", "Audit-post") else "normal"
    return "normal"

def _classify_dispatch(events, task_id, now=None, proc_alive=None, identity=None, land_ok=None, land_alive=None, *, DISPATCH_NEAR_LAUNCH_GRACE_SEC, DISPATCH_STALE_NORMAL_SEC, DISPATCH_STALE_AUDIT_SEC, DISPATCH_TERMINAL_DETAIL, DISPATCH_TERMINAL_TYPES, _dispatch_log_mtime, _dispatch_task_of, _land_proc_alive, _live_claimed_task_ids, _main_task_status, _parse_iso_ts, _read_worktree_stamp, _session_proc_alive, _stamp_is_own, _worktree_path_for_branch, _dispatch_log_text=None):
    """Classify ONE dispatched task from its events (already scoped to task_id, ts-ascending).
    Returns (cls, detail, last_ts, session_ref). `identity` is the caller's _dispatch_identity
    verdict (clean | COLLAPSED | not-yet-started | None), passed in so the launch-stall branch can
    reuse it (no second session_started scan).

    MAIN-STATUS RECONCILE (T-9750, runs FIRST): the MAIN task record tasks/<id>.yaml carries the
    authoritative status. A task already `status: done` on main reads TERMINAL(done) regardless of
    the journal bg-axis — a late successful `land` emits `land_completed`, NOT a bg_dispatch
    terminal, so the chain can still carry a STALE bg_dispatch_halted(blocked_on_land) /
    closed_pending_land marker while the task is in fact done+landed. `_main_task_status` is
    fail-open (None on any miss), so the reconcile only ever fires on a POSITIVE `done` read — it
    never fabricates a done. Scoped to `done`; every other status falls through to the journal-axis
    classes below. The six journal-axis classes (scope §2):
      - launch-stall: a LAUNCHER-dispatched worker (bg_dispatch_launched present) that never came up
        and never claimed, PAST the near-launch bootstrap grace (T-9749). Fires ONLY when
        `identity == 'not-yet-started'` (the assigned worker ref journaled NO session_started —
        'clean'/'COLLAPSED' both mean it DID start, so are NOT a stall), no live worktree claim, no
        post-launch task_picked/read_gate_refused (scoped to the LATEST launch window so a relaunch /
        a started-but-slow worker is not misread), and `now - launch_ts` exceeds
        DISPATCH_NEAR_LAUNCH_GRACE_SEC. PROC-AWARE (T-10096): past the grace the stall keys on
        proc-liveness, not the clock alone — a POSITIVE `--session-id <worker_ref>` proc read means a
        slow opus worker is still BOOTING (20-40 min bootstrap), so it reads working(still-booting,
        age=Nm), NOT a stall; only a proc-DEAD/unconfirmable worker past grace is a genuine
        launch-stall (fail-closed). Within the grace it stays "still booting" (working). The
        row's session_ref is the WORKER's assigned ref (launched.data.expected) — NOT the inherited
        controller envelope ref (which would point a live-proc check at the always-alive controller).
        SURFACE-only — turns the T-9727/T-9737 silent bootstrap hangs into a visible signal; the
        controller's >=2-poll gate + Confirmed-dead GATE still decide any action, the reader never
        kills/redispatches (CHARTER detect+surface).
      - TERMINAL: task_closed -> 'done' | bg_dispatch_halted -> 'halt' (T-0378 emitted markers) |
        task_wont_do -> 'wont-do' (T-0588 — a reader-recognized task-status terminal, a worker
        declining a superseded/self-unsatisfiable task). DISPATCH_TERMINAL_DETAIL maps type -> label.
        A task_closed counts TERMINAL(done) ONLY once LANDED (T-0691, below).
      - closed_pending_land: terminal is task_closed BUT a live task/T-XXXX worktree claim still
        exists -> the close has NOT landed (land removes the worktree, D-0037), so it is not yet
        Done=Adopted (CHARTER §P3). A distinct NON-terminal state: the controller must LAND it, not
        read it as a finished success (T-0691). Detail surfaces the stamp provenance (own / foreign
        / unknown-stamp), like hang_suspect. halt/wont-do stay land-independent terminals.
      - working: non-terminal, last event recent (within the PER-PHASE window — T-9748:
        DISPATCH_STALE_NORMAL_SEC, or DISPATCH_STALE_AUDIT_SEC in the Audit-pre/Audit-post phase) ->
        detail 'recent'; OR (AUDIT phase) journal-stale BUT the dispatch-log heartbeat (T-9747) is
        fresher than the window -> detail 'audit-heartbeat' (the worker process is alive mid-audit);
        OR stale-journal BUT a REAL `--session-id <ref>` process is running NOW (T-9240, AC1) -> detail
        'alive-proc' (alive, just journal-silent — the Confirmed-dead GATE predicate (b) positively-alive
        — so it is NOT a hang_suspect/orphan and recovery does not fire over a live worker).
      - silent_stop: non-terminal, stale, NO live worktree claim.
      - hang_suspect: non-terminal, stale, a LIVE worktree claim still present (alive-but-stale,
        worktree-corroborated). F0 absorption: the stamp provenance is surfaced —
        'hang_suspect(own)' vs 'hang_suspect(foreign/unknown)' — a foreign/unreadable claim is
        NEVER silently asserted as own-alive. Detect+surface ONLY, never auto-kill (CHARTER)."""
    now = now or _dt.datetime.now(_dt.timezone.utc)
    proc_alive = proc_alive or _session_proc_alive   # T-9240 (AC1): injectable for tests
    land_alive = land_alive or _land_proc_alive       # T-10043: injectable land-liveness probe
    # T-10095 — NEWEST-LAUNCH-EPOCH segmentation (runs before every journal-axis scan below). The
    # scoped chain concatenates EVERY dispatch epoch for this task_id, so a RE-DISPATCHED task's
    # STALE prior launch (its bg_dispatch_halted / silent tail) sits in the same flat chain as the
    # FRESH launch's live worker. The reversed terminal scan then returns the OLD terminal and
    # shadows the fresh worker (incident: dispatch-status-stale-launch-shadows-fresh-worker). The
    # T-0606 live-claim override only supersedes a stale terminal for a DIFFERENT worker with a
    # readable live worktree stamp — a launcher relaunch whose fresh worker holds no such stamp
    # still misclassifies. So SEGMENT to the newest launch: keep only events at/after the latest
    # bg_dispatch_launched ts (events are ts-ascending), classifying the fresh worker on its OWN
    # epoch. No launch event -> a hand-claimed / non-launcher chain -> events unchanged (T-9749
    # already keys launch-stall off this same "latest launch wins" reversed scan). Reader-only,
    # within the SPEC-0025 terminal-marker contract — like T-0588 / T-0606, no store/emit change.
    newest_launch = next((e for e in reversed(events) if e.get("type") == "bg_dispatch_launched"), None)
    if newest_launch is not None:
        seg_ts = newest_launch.get("ts") or ""
        events = [e for e in events if (e.get("ts") or "") >= seg_ts]
    last_ts = events[-1].get("ts") if events else None
    sref = next((e.get("session_ref") for e in reversed(events) if e.get("session_ref")), None)
    # T-10254 — the row's session_ref is the WORKER's ref FROM THE MOMENT OF DISPATCH, never the
    # dispatcher's. The reversed scan above returns the newest ref in the TASK-SCOPED chain; a
    # worker's first events (session_started / seed_read / the help scan) carry NO task_id, so
    # `_dispatch_task_of` drops them and PRE-ANCHOR — between `dispatch` and the worker's first
    # task-tagged emit — the chain holds ONLY the dispatcher-emitted `bg_dispatch_launched`, whose
    # ENVELOPE session_ref is the DISPATCHER's own ref C. The row then keys to C: `_session_proc_alive`
    # probes the controller instead of the worker, and (fleet-verdict) the row inherits the
    # DISPATCHER's unrelated events as its evidence line. Incident 2026-07-09: T-10246 read
    # `needs-decision / proc_alive=false / basis: proc gone but last event recent` — borrowing the
    # controller's own `land_completed` — while the worker was ALIVE (pid up, 11 events under its own
    # ref); the controller nearly declared a live worker dead and re-dispatched it. This verb exists
    # precisely so a raw journal grep does not mis-read healthy workers as actionable.
    #
    # So bind sref to the assigned worker ref E (`bg_dispatch_launched.data.expected`, the launcher's
    # journaled output per T-0558) at the SOURCE. This is the invariant this function's docstring
    # ALREADY asserts — it was implemented in the launch-stall branch ALONE (T-9749 "audit-pre F1"),
    # which left every OTHER branch inheriting C. Hoisting it here makes every downstream reader
    # (grouping, proc_alive, the fleet evidence filter) key on E BY CONSTRUCTION — no second keying
    # path, no evidence-side filter (CHARTER §P1 F2 view-over-entity). Post-anchor this is a no-op: the
    # worker's own events already carry E. Fallback to the reversed scan when there is NO launch (a
    # hand-claimed chain) or no `expected` (a pre-T-0558 row) — those chains are bit-for-bit unchanged.
    # Fail-closed under a COLLAPSED identity (a worker that inherited C): proc_alive(E) reads dead,
    # SURFACING the collapse rather than masking it behind the always-alive controller proc; the
    # collapse itself is reported on its own axis by `_dispatch_identity` (which likewise keys 'clean'
    # on `expected`, never on C — so this binding cannot perturb the identity verdict).
    _ldata = newest_launch.get("data") if isinstance(newest_launch, dict) else None
    _worker_ref = _ldata.get("expected") if isinstance(_ldata, dict) else None
    if _worker_ref:
        sref = _worker_ref
    # T-9750 — MAIN-status reconcile (authoritative, runs FIRST). A task already `status: done` on
    # main IS done+landed: a late successful `land` emits no bg_dispatch terminal, so the journal
    # chain may still carry a stale bg_dispatch_halted(blocked_on_land) / closed_pending_land marker
    # that the bg-axis would otherwise surface as TERMINAL(blocked_on_land) — the false 'work lost'
    # inference (fingerprint controller-inferred-work-loss-from-worktree-absence-without-checking-
    # main-status-FALSE). `_main_task_status` fail-opens to None, so this fires ONLY on a positive
    # `done` read (never fabricates one). Scoped to `done`; other statuses fall through.
    if task_id and _main_task_status(task_id) == "done":
        return ("TERMINAL", "done", last_ts, sref)
    # T-9766 — AUTHORITATIVE terminal JOURNAL-event reconcile (the SETTLE-race fix, sibling of the
    # T-9750 main-status reconcile above). A successful `land_completed{status:ok}` for this task's
    # branch (the direct LANDED signal — `_last_land_ok`, computed by the caller from the UNIONED
    # stream because land_completed is branch-carried and filtered out of the scoped `events`) means
    # the worker LANDED, even while the journal chain still carries a stale bg_dispatch_halted(
    # blocked_on_land) marker that a rebaseline-`land` committed a few seconds after the worker pid
    # appeared gone. So the reader keys off the terminal EVENT (after it settles into the journal),
    # never pid-death. Fail-open (land_ok defaults None/False → falls through to the bg-axis, so a
    # pre-settle poll reads blocked; the §Watcher ≥2-poll settle window re-polls until it lands).
    if land_ok:
        return ("TERMINAL", "done", last_ts, sref)
    # TERMINAL — a recognized terminal event in the chain ends a dispatch (done|halt|wont-do)...
    # UNLESS a DIFFERENT live worker is progressing past it (T-0606, the converse of T-0588): an
    # OLDER terminal marker from a SUPERSEDED/dead worker must not mask a LIVE worker's progress for
    # the SAME task_id. Incident T-0590: a dead redundant worker's bg_dispatch_halted (main journal,
    # session refA) sat in the same UNIONED chain (T-0566) as the live worker's stage_entered
    # (worktree journal, session refB), and "terminal anywhere wins" misclassified TERMINAL(halt) —
    # poisoning a controller monitor keyed on it. The override is SCOPED to the LIVE WORKTREE CLAIM
    # (the task scope's option 2; reuses the SAME _live_claimed_task_ids / stamp reads the
    # hang_suspect branch below uses — no new helper): the terminal is superseded ONLY when a live
    # worktree claim is held by a session DIFFERENT from the terminal's AND that claim-session's
    # LATEST event in the unioned chain is non-terminal and newer than the terminal. Keying on the
    # claim-session's latest event (not merely "any newer non-terminal event") means a claim-session
    # that itself later went terminal does NOT supersede; and a SAME-session live claim (a worker
    # that closed its own task) never un-terminalizes (the different-session guard). `terminal` is the
    # globally-latest terminal (reversed scan), so the claim-session cannot hold a terminal newer than
    # it. ts compares lexicographically — same ISO ordering as the chain's ts-sort.
    terminal = next((e for e in reversed(events) if e.get("type") in DISPATCH_TERMINAL_TYPES), None)
    # T-12304 — CONTROLLER-WAIT: a clean, CUED stop is a TERMINAL, RESUMABLE state. The worker exited
    # after a «STOP and report» brief step and recorded it via `task pause --reason controller-wait`,
    # which writes the resume contract. Without this branch the chain has no terminal marker at all,
    # so the row read `working` (proc gone, last event recent — «settling») and the watcher woke with a
    # needs-decision it could not name (measured 2026-09-09: T-12297 / T-12288). The row is NOT a
    # `halt` — no gate refused anything — so it takes its own class rather than borrowing one whose
    # gloss would misroute the controller. Placed at the terminal seam and preferred only when the
    # pause is NEWER than any terminal marker: a worker that paused and then genuinely halted/closed
    # keeps its later terminal. Reader-only, no store/emit change (SPEC-0025 §Terminal-marker, the
    # T-0588/T-0606 shape).
    _cw_pause = _controller_wait_pause(events)
    if _cw_pause is not None and (_cw_pause.get("ts") or "") > ((terminal or {}).get("ts") or ""):
        return ("paused", CONTROLLER_WAIT_PAUSE_REASON, last_ts, sref)
    if terminal is not None:
        superseded = False
        if task_id and task_id in _live_claimed_task_ids():
            stamp = _read_worktree_stamp(_worktree_path_for_branch(f"task/{task_id}"))
            claim_sref = stamp.get("session_ref") if isinstance(stamp, dict) else None
            if claim_sref and claim_sref != terminal.get("session_ref"):
                # Both callers pass events ALREADY scoped to this task_id, but re-assert it here so the
                # supersession check is self-defending and never clears a terminal on a different task's
                # activity from the same live session (audit-post finding — defense in depth).
                claim_events = [e for e in events
                                if e.get("session_ref") == claim_sref and _dispatch_task_of(e) == task_id]
                claim_last = claim_events[-1] if claim_events else None  # events are ts-ascending
                if (claim_last is not None
                        and claim_last.get("type") not in DISPATCH_TERMINAL_TYPES
                        and (claim_last.get("ts") or "") > (terminal.get("ts") or "")):
                    superseded = True
        if not superseded:
            # T-0691 — Done=Adopted (CHARTER §P3): a `task_closed` reached IN-WORKTREE is NOT
            # integrated until `land` ff's it to main and REMOVES the task/T-XXXX worktree on success
            # (D-0037). So a close whose worktree is STILL LIVE has not landed -> a distinct
            # closed_pending_land state, NOT TERMINAL(done): the controller must LAND it, never read
            # it as a finished success (incident: a worker died after closure before land yet read
            # TERMINAL(done) — dispatched-worker-died-after-closure-before-land-ffstorm). halt /
            # wont-do are land-INDEPENDENT terminals (a halted/declined worker never claimed done),
            # so this carve-out is scoped to task_closed ONLY. Reuses the SAME live-claim + stamp
            # reads as the supersession branch above and the hang_suspect branch below — no new
            # helper, no new store; reader-only (SPEC-0025 §Terminal-marker, like T-0588/T-0606).
            if (terminal.get("type") == "task_closed"
                    and task_id and task_id in _live_claimed_task_ids()):
                stamp = _read_worktree_stamp(_worktree_path_for_branch(f"task/{task_id}"))
                prov = "own" if _stamp_is_own(stamp) else ("foreign" if stamp else "unknown-stamp")
                # T-10043 — the land-liveness sub-signal: closed_pending_land is a TRANSIENT
                # self-land phase, so surface whether THIS task's `land` process is running NOW.
                # land-alive => the worker's own self-land is in flight (leave it — firing the
                # controller's own `land` RACES it, E-0035); land-dead => no live land proc (an
                # abandoned close awaiting the controller's grace-wait + recovery `land`). The
                # controller reads it off the class instead of hand-rolling a (NUL-hazardous) probe.
                # T-10953 (X-0815) — WHOSE liveness the detail speaks about. The probe above reads the
                # LAND CHILD only, but the recovery this class prescribes (`worktree recover-land`) has a
                # CONFIRMED-DEAD WORKER as its own predicate — so on land-dead the detail must also say
                # whether the WORKER SESSION is alive, or the reader is told "the worker CLOSED, recover
                # it" about a worker that is still running and merely BETWEEN land invocations (the
                # synchronous-to-LAND retry loop): two refusals naming each other, read as a deadlock.
                # The liveness is already in hand — `proc_alive`, the SAME probe the T-9240/T-10096
                # branches and the T-10394 override below read; this branch just stopped consulting it.
                # FAIL-CLOSED per lessons/fail-closed-belongs-to-the-reader-not-the-parser: proc_alive
                # confirms POSITIVELY only (False on unknowable/unscannable), so an unprovable session
                # keeps the plain `land-dead` + its recovery route — a dead worker is never dressed up
                # as alive. APPEND-ONLY: `land-dead` keeps its spelling as the prefix, so every existing
                # substring/equality reader of the two original values is untouched.
                if land_alive(task_id):
                    detail = f"{prov},land-alive"
                elif _launch_land_regime(_ldata) == LAND_REGIME_CONTROLLER:
                    # T-12351 — the CONTROLLER-LANDS regime (T-12373): the worker's own launch row
                    # says the Controller lands, so a worker that stopped after `task close` with no
                    # land running is the CONTRACTED completion, not a death (SPEC-0103 / T-12303:
                    # «yielding AFTER task close, with the sha reported, IS the completion»). Measured
                    # 2026-09-10: T-12319 + T-12337 stopped as contracted and read land-dead, so the
                    # Controller filed a death-class deviation (premise false) and used the RECOVERY
                    # verb for the sanctioned next step. Same evidence, honest class: the launch row is
                    # the one already bound above (`_ldata`), the provenance the one just derived; no
                    # second read, no new state. Worker regime / no key falls through unchanged, and a
                    # land ALIVE on the branch stays closed_pending_land(land-alive) above whatever the
                    # regime (a running land is left alone). Whether the worker SESSION still lives
                    # is not a sub-signal here: under this regime it has nothing left to do.
                    # (Emitted as the LITERAL, like every sibling class: the T-10253 single-carrier
                    # test AST-derives the emitted set from these return heads.)
                    return ("closed_awaiting_controller_land", prov, last_ts, sref)
                elif sref and proc_alive(sref):
                    detail = f"{prov},land-dead,session-alive"
                else:
                    detail = f"{prov},land-dead"
                return ("closed_pending_land", detail, last_ts, sref)
            # T-10394 — LIVE-LAND override: a `blocked_on_land(...)` marker is a TRANSIENT while
            # the worker still lives. The worker emits it at the land repeated-abort backstop
            # (worktree.blocked_on_land_repeated_abort_disposition) and then, per the synchronous-to-LAND
            # discipline, RE-INVOKES `land` inline — so the marker sits in the chain while the worker is
            # merely MID-LAND. The reader surfaced it as a TERMINAL settled STOP: 3 live
            # false-transients on 2026-07-10/11 (T-10373 x2, T-10379), each disambiguated only by a MANUAL
            # proc check, and a watcher acting on one would have escalated a NON-decision to the owner. So
            # consult the liveness evidence this function ALREADY holds — the worker's own proc
            # (`proc_alive`, the T-9240/T-10096 branches) or its land child (`land_alive`, the T-10043
            # closed_pending_land probe) — the SAME evidence fleet-verdict reads. Positive liveness =>
            # working(landing); a blocked_on_land detail may only surface once the proc is gone.
            # FAIL-CLOSED, per lessons/fail-closed-belongs-to-the-reader-not-the-parser: both probes confirm
            # POSITIVELY only (False on unknowable/unscannable), and the READER owns what absence means —
            # no positive liveness leaves today's TERMINAL(blocked_on_land(...)) intact, so a real settled
            # stop is never masked. SCOPED to the blocked-on-land PAIR (T-10788 — both readings ride the
            # same self-land retry loop, so the override cannot key on the escalation target): every other
            # terminal (halt / wont-do / done / refused(pre-claim)) is land-independent and stays TERMINAL
            # even with a live proc.
            # T-11618 — the AUTHORITY arm is upgraded from the recorded blocker by the READER
            # (`_owner_gated_detail`), not here: that derivation needs the UNSCOPED stream, while
            # this function's `events` is task-scoped and cannot see the branch's land rows (the
            # same reason `land_ok` is passed in rather than derived here). The live-land override
            # just below is unaffected — it keys on the blocked-on-land PAIR, and the upgrade moves
            # a detail WITHIN that pair.
            t_detail = _terminal_detail(terminal, DISPATCH_TERMINAL_DETAIL)
            if t_detail in _HALT_DETAILS_BLOCKED_ON_LAND and (
                    (sref and proc_alive(sref)) or (task_id and land_alive(task_id))):
                return ("working", "landing", last_ts, sref)
            return ("TERMINAL", t_detail, last_ts, sref)
        # else: a DIFFERENT live worker is progressing past the stale terminal -> fall through to the
        #       non-terminal recency/liveness branch (working | silent_stop | hang_suspect) below.
    # non-terminal. Compute the live-claim corroboration ONCE (reused by launch-stall + the
    # silent_stop/hang_suspect split below).
    live_claim = task_id in _live_claimed_task_ids() if task_id else False
    # T-9749 — launch-stall: a launcher-dispatched worker that never came up (identity
    # not-yet-started) and never claimed, PAST the near-launch bootstrap grace. This runs BEFORE the
    # staleness split so the window from the grace edge (>=10 min) through the per-phase staleness
    # window (T-9748) — which otherwise reads working(recent), masking the hang — is
    # surfaced. Scoped to the LATEST launch window (reversed scan) so a relaunch does not classify
    # against a stale earlier launch (audit-pre F2). Any post-launch worker-progress event
    # (task_picked / read_gate_refused) OR identity != 'not-yet-started' (a session_started came up)
    # OR a live claim disqualifies it -> falls through to the ordinary recency/liveness branches.
    # T-10254 — `newest_launch` IS this reversed scan's result (the segmentation above keeps it in the
    # chain), so reuse it rather than re-scanning; and `sref` is ALREADY the worker's assigned ref E,
    # so the branch's local `ldata`/`worker_ref` re-derivation is redundant and REMOVED (CHARTER §P1 F3
    # — the invariant is now enforced at the one source above, not re-stated per branch).
    launched = newest_launch
    if launched is not None and not live_claim and identity == "not-yet-started":
        launch_ts = launched.get("ts") or ""
        post_launch = any(e.get("type") in ("task_picked", "read_gate_refused")
                          and (e.get("ts") or "") >= launch_ts for e in events)
        dt_launch = _parse_iso_ts(launch_ts)
        if not post_launch and dt_launch is not None:
            # T-10254 — the PRE-ANCHOR window: launched, identity `not-yet-started` (the assigned ref
            # journaled NO session_started), never claimed. The dispatched worker has produced NO
            # evidence of its own yet, so the ONLY event in the chain is the dispatcher's launch. Name
            # that state honestly with the class DISPATCH_CLASS_VOCAB already carries for it —
            # working(still-booting,age=Nm) — for the WHOLE pre-anchor window, not just past the grace.
            # Previously the within-grace arm fell through to the recency split and read
            # working(recent), whose `recent` signal was the DISPATCHER's launch ts read as if it were
            # worker progress. Same class, honest detail: NO new class token, so the T-10253
            # single-carrier vocabulary is untouched (the card's "if a pre-anchor state needs a name,
            # add it to DISPATCH_CLASS_VOCAB rather than inventing a second vocabulary" — it was
            # already named there).
            #
            # T-10096 — PROC-AWARE grace: a slow opus worker's bootstrap can run 20-40 min before it
            # journals its first session_started/claim, yet its `--session-id <worker_ref>` PROCESS is
            # ALIVE + consuming CPU the whole time (deviation launch-stall-false-positive-live-proc-slow-
            # bootstrap: T-10082 flagged launch-stall while proc c76933b6 was alive; sibling T-10083
            # claimed at the same elapsed). The fixed 10-min grace clock does not scale to that bootstrap,
            # so key the stall on PROC-LIVENESS, not the clock alone: a POSITIVE `--session-id` proc read
            # means the worker is still BOOTING — surface it as working(still-booting,age=Nm), NOT an
            # actionable stall (launch-stall is a controller-wake state, T-10034; a false one tempts a
            # duplicate re-dispatch). Mirrors the T-9240 alive-proc upgrade below; reuses the SAME
            # injected proc_alive + the `working` class (no new class, no per-tier grace table). Only a
            # proc-DEAD/unconfirmable worker PAST the grace is a genuine launch-stall (launched, never
            # came up, process gone). Fail-closed: an unconfirmable proc past grace reads as a stall
            # (never masks a death); WITHIN the grace a cold worker's legitimate pre-claim silence is
            # preserved (T-9749), so the stall cannot false-fire on a worker that has not had time yet.
            age_sec = (now - dt_launch).total_seconds()
            within_grace = age_sec <= DISPATCH_NEAR_LAUNCH_GRACE_SEC
            if within_grace or (sref and proc_alive(sref)):
                return ("working", f"still-booting,age={int(age_sec // 60)}m", last_ts, sref)
            # T-10792 — NAME THE CAUSE when the launch log declares one. The dead bootstrap's own stdout
            # is the only witness to WHY it died, and it is already carried on the launch event
            # (`data.log`, the same field the T-9747 audit heartbeat reads through `_dispatch_log_mtime`)
            # — so this reuses an existing carrier on an existing injection seam, adding no plumbing.
            # The READER owns the fail-closed judgement (lessons/fail-closed-belongs-to-the-reader-not-
            # the-parser): only a RECOGNISED signature replaces the detail; a missing text, an
            # unreadable/absent log, or an unrecognised one all keep `no-claim-past-grace`, so a death
            # nobody can explain is never dressed up as an explained one. Same class token either way —
            # a DETAIL, not a new class (the T-10253 single-vocabulary bound is untouched).
            stall_detail = _STALL_DETAIL_NO_CLAIM
            # `_ldata` is the newest launch event's data, derived ONCE above (T-10254 removed this
            # branch's redundant local re-derivation) — and `launched IS newest_launch` here, so it is
            # this row's own launch payload, never a borrowed one.
            if _dispatch_log_text is not None and isinstance(_ldata, dict):
                stall_detail = _launch_failure_signature(_dispatch_log_text(_ldata.get("log"))) \
                    or _STALL_DETAIL_NO_CLAIM
            return ("launch-stall", stall_detail, last_ts, sref)
    # recent => working; stale => silent_stop / hang_suspect on live-claim corroboration. T-9748 —
    # PER-PHASE window: a worker journal is SPARSE (events only at stage boundaries), so the window is
    # the trigger to consult liveness, tuned by phase — NORMAL tight (catches a 10-20 min silent hang),
    # AUDIT generous (the external-audit stage is legitimately minutes-long + journal-silent). In the
    # AUDIT phase, when the journal alone is stale, the T-9747 dispatch-log heartbeat (a fresher log
    # mtime than the last journal event) RESETS staleness -> working(audit-heartbeat): the worker is
    # alive mid-audit, not hung. This is sref-INDEPENDENT, so it holds even where proc_alive would
    # false-alive on a collapsed controller-ref. LAND is already handled by closed_pending_land above.
    phase = _dispatch_phase(events)
    window = DISPATCH_STALE_AUDIT_SEC if phase == "audit" else DISPATCH_STALE_NORMAL_SEC
    # T-10130 — FAR-FUTURE-ROW ROBUSTNESS (F3b MISSED-TRUE-DEATH; SPEC-0133 rule 2 recency contract).
    # A spurious far-future journal row (e.g. a 2098/2099 sentinel ts) must NOT read as a fresh
    # recency signal: (now - dt_future) is NEGATIVE, so journal_stale/stale would compute False and
    # mask a truly dead worker as settling/working. EXCLUDE future-dated rows from the recency signal
    # — derive dt_last from the newest event whose ts is at/before now (+ a small clock-skew
    # tolerance), so the last REAL event ages to stale and the death surfaces. Clamping a future ts to
    # `now` would ALSO read fresh at age 0 — exclusion, not clamp, is what restores the true-death
    # verdict. All-future chain -> dt_last None -> journal_stale True (fail-closed toward death, never
    # masks). The reported last_ts tuple element is unchanged (it stays the raw newest ts).
    # SCOPE (T-10130 audit-pre): this hardens the RECENCY clock only — the death-masking vector, since
    # only the ts arithmetic goes negative on a future row. Other derivations off the same chain are
    # NOT ts-driven so a sentinel row cannot false-alive through them: `phase` keys on event TYPES not
    # ts, and a bogus `session_ref` on a future row only feeds proc_alive (a non-existent proc reads
    # DEAD, fail-closed — never a false-alive). Broadening the filter to those is deliberately out of
    # scope (no death-masking path through them).
    dt_last = _parse_iso_ts(last_ts)
    if dt_last is not None and (dt_last - now).total_seconds() > _DISPATCH_FUTURE_SKEW_SEC:
        dt_last = next(
            (t for t in (_parse_iso_ts(e.get("ts")) for e in reversed(events))
             if t is not None and (t - now).total_seconds() <= _DISPATCH_FUTURE_SKEW_SEC),
            None,
        )
    journal_stale = dt_last is None or (now - dt_last).total_seconds() > window
    dt_progress = dt_last
    if phase == "audit" and journal_stale:
        ldata = launched.get("data") if isinstance(launched, dict) else None
        hb = _dispatch_log_mtime(ldata.get("log")) if isinstance(ldata, dict) else None
        if hb is not None and (dt_progress is None or hb > dt_progress):
            dt_progress = hb   # the heartbeat is fresher than the last journal event -> alive mid-audit
    stale = dt_progress is None or (now - dt_progress).total_seconds() > window
    if not stale:
        return ("working", "audit-heartbeat" if journal_stale else "recent", last_ts, sref)
    if not live_claim:
        return ("silent_stop", "no-live-claim", last_ts, sref)
    # T-9240 (AC1): journal-quiescence is only a PROXY for death. Before declaring hang_suspect (which
    # surfaces as quiescent:true + DEAD-BUT-UNLANDED orphan), consult the §Abnormal Confirmed-dead GATE
    # predicate (b) — a REAL `--session-id <ref>` process running NOW means the worker is ALIVE, just
    # journal-silent (a long synchronous suite under CPU load). A POSITIVE proc confirmation UPGRADES it
    # to `working` (alive-proc): quiescent:false + not an orphan, so recovery does NOT fire over a live
    # worker. Not-confirmed (not found / unscannable) leaves the journal-derived hang_suspect intact —
    # fail-closed, never masking a real death; the controller then runs its own gate.
    if sref and proc_alive(sref):
        return ("working", "alive-proc", last_ts, sref)
    # alive-but-stale, worktree-corroborated — surface the stamp provenance (F0 failure-mode absorb)
    wt = _worktree_path_for_branch(f"task/{task_id}")
    stamp = _read_worktree_stamp(wt)
    detail = "own" if _stamp_is_own(stamp) else ("foreign" if stamp else "unknown-stamp")
    return ("hang_suspect", detail, last_ts, sref)

def _dispatch_dead_but_unlanded(cls):
    """T-1117 — the EXPLICIT dead-but-unlanded ORPHAN classification, derived from the journal SHAPE
    alone (AC1). True iff class == `hang_suspect`: non-terminal + journal-stale (quiescent) + a LIVE
    `task/T-XXXX` worktree claim STILL on disk — i.e. the worker's work was neither landed nor torn
    down, the exact dead-but-unlanded case the T-1052 root cause produced (backgrounded its tests,
    yielded, died mid-Execution). This SURFACES the case as its own signal rather than leaving it
    buried in the generic `hang_suspect` label.

    HONEST naming — it is the journal-derived CANDIDATE shape, NOT a confirmed process-death: the
    reader NEVER process-walks (CHARTER L59/148; detect+surface, non-goal #7). Death is CONFIRMED by
    the controller's §Abnormal «Confirmed-dead GATE» predicate (b) (no live `--session-id` proc) before
    `worktree adopt`. False for `working` (alive), `silent_stop` (stale but NO live worktree → already
    landed/gone, nothing to adopt — not an orphan), and `launch-stall` (T-9749 — a worker that never
    came up: no worktree was ever created, so there is nothing to adopt; the recovery is re-bootstrap).
    None where the question is inapplicable (TERMINAL / closed_pending_land / no_dispatch)."""
    if cls == "hang_suspect":
        return True
    if cls in ("working", "silent_stop", "launch-stall"):
        return False
    return None

def _dispatch_identity(launched, started_events, now=None):
    """ADVISORY, race-prone (T-0559) controller-side identity check for ONE launcher-dispatched
    task — option (4) of plan `dispatch-via-sub-sessions-only-subagents-forbidden`, DEMOTED to
    advisory by the FULL ad-hoc external review (race-prone: the worker may not have journaled its
    ref yet). It carries NO correctness guarantee — that lives in launch-time env-scrub (T-0558) +
    the worker fail-closed self-check (T-0561), NOT here.

    Reads ONLY the producers' journaled outputs — NEVER re-derives a session_ref (re-audit finding 1):
      - the launcher's `bg_dispatch_launched` (T-0558): `data.expected` = the assigned distinct
        worker ref E; envelope `session_ref` = the controller's own ref C.
      - the worker's `session_started.resolved_session_ref` (T-0557).

    Returns one of (or None when inapplicable):
      - 'clean'           : a session_started resolved to the assigned distinct E — the worker has
                            its OWN identity (E is a unique per-worker uuid, so any match is the
                            worker; clean takes precedence over a collapse reading).
      - 'COLLAPSED'       : no E-session, but a POST-launch (ts >= launch ts) session_started
                            resolved to the controller's own C — a second session inherited the
                            controller's identity (the §Findings H1-CAVEAT controller↔worker
                            collapse). The ts filter excludes the controller's OWN pre-launch
                            session_started (which also carries C) from reading as a collapse.
      - 'not-yet-started' : neither observed yet — the worker has not journaled a session_started
                            (the benign race: re-check shortly).
      - None              : inapplicable — no `bg_dispatch_launched` (not a launcher dispatch, so a
                            hand-claimed task never false-COLLAPSEs) or no `expected` to compare.
    """
    if not launched:
        return None
    data = launched.get("data")
    expected = data.get("expected") if isinstance(data, dict) else None
    controller = launched.get("session_ref")
    if not expected:                       # no assigned ref to compare against -> inapplicable
        return None
    launch_ts = launched.get("ts") or ""
    collapsed = False
    for e in started_events:
        if e.get("type") != "session_started":
            continue
        d = e.get("data")
        ref = d.get("resolved_session_ref") if isinstance(d, dict) else None
        if not ref:
            continue
        if ref == expected:                # the worker started with its OWN distinct identity
            return "clean"
        if controller and ref == controller and (e.get("ts") or "") >= launch_ts:
            collapsed = True               # a post-launch session resolved to the controller's ref
    return "COLLAPSED" if collapsed else "not-yet-started"

def _dispatch_lifecycle_integrity(allev, *, _DISPATCH_AUDIT_TYPES, _DISPATCH_COMPLETION_TYPES, _DISPATCH_REQUIRED_LIFECYCLE, _event_task_of, _audit_outside_window=None):
    """Given the dispatch-relevant events (from `_dispatch_status_events`), return a list of per-task
    rows {task_id, completed, missing:[...], severity} for every DISPATCHED task (one with a
    `bg_dispatch_launched`) that REACHED a completion terminal. `missing` lists the absent governed
    lifecycle events (worktree_created / task_picked / audit); an EMPTY `missing` = a clean
    full-lifecycle land. `severity` TIERS the signal in THREE tiers (T-11021):
      - 'bypass'    = the claim evidence is WHOLLY absent (BOTH worktree_created and task_picked
                      missing), OR a claim marker is missing AND no audit ran. That is the X-0044
                      shape — no claim, no external audit — and it stays the top tier.
      - 'claim-gap' = EXACTLY ONE claim marker missing while the OTHER claim marker IS present AND an
                      audit ran: a governed, externally-audited land with one un-emitted claim marker.
                      Surfaced, but BELOW bypass. This tier exists because the undifferentiated
                      version labelled 10 of the kernel's 12 flagged rows (T-0662/T-9265/T-10036/
                      T-10588 et al — all full governed lifecycles) with the same "the X-0044 shape;
                      investigate" text as a real audit-skipping bypass, which is what taught
                      operators to skim the report. A report-only SIGNAL fails safe toward the reading
                      that does not ACCUSE (lesson `a-signal-about-a-reader-fails-safe-the-opposite-
                      way-to-a-gate`) — the opposite direction to a gate.
      - 'advisory'  = ONLY audit absent — expected for a Fast-Path docs/hygiene task, a human triages.
      - 'instrument-gap' (T-11026) = the audit is the ONLY absent item AND an audit event for this
                      task EXISTS outside what this check can see — after the first completion it
                      judges against, or outside the report window. That is a fact about the
                      INSTRUMENT, not about the task, so the row carries `missing: []` +
                      `unobserved: ['audit']` and is never rendered as a missing audit. Measured
                      2026-08-15: T-10866 and T-10977 both read «landed but MISSING: audit» while
                      carrying audit_post_completed 2026-08-10T17:36:01Z / 2026-08-12T15:05:37Z —
                      each had an EARLIER dispatch attempt whose land_completed became the judged
                      terminal, so the real audit fell outside the slice. A report-only SIGNAL fails
                      safe toward the reading that does NOT accuse (lesson `a-signal-about-a-reader-
                      fails-safe-the-opposite-way-to-a-gate`); one false accusation is what teaches
                      operators to skim the report. This never hides a REAL bypass: it applies only
                      when an audit for that task provably exists somewhere.
    `_audit_outside_window(task_id) -> bool` is an OPTIONAL probe supplied by the caller for the
    window half (the slice half is answerable from `allev` alone). Absent ⇒ only the slice half
    applies and every pre-existing caller is byte-identical.
    PURE read; no emit, no gate."""
    by_task = {}
    for e in allev:
        tid = _event_task_of(e)
        if not tid:
            continue
        by_task.setdefault(tid, []).append(e)
    rows = []
    for tid, evs in by_task.items():
        # evs preserves the ts-ascending order of `allev` (_dispatch_status_events ts-sorts), so the
        # terminal we judge against is the first completion that FOLLOWS this task's own dispatch —
        # and the chain must PRECEDE that terminal (a worktree/claim/audit event appearing only AFTER
        # the land cannot retro-justify it, the X-0044 recovery-attempt confusion; audit-post finding
        # absorbed T-9365). BOTH halves are load-bearing and they answer DIFFERENT questions:
        # T-9365 bounds what counts as preceding the completion; T-11057 bounds WHICH completion.
        types = {e.get("type") for e in evs}
        if "bg_dispatch_launched" not in types:   # not a dispatched worker — out of scope
            continue
        if "task_wont_do" in types:   # a legitimate DECLINE shipped no work — never a bypass
            continue
        # T-11057 — a task's stream is its WHOLE history, not just this dispatch: a completion may
        # PREDATE the launch entirely (a synthetic adoption-probe close, an earlier hygiene close, a
        # prior interactive lifecycle). Scanning from index 0 handed the terminal slot to that older
        # event, leaving `before` empty and every governed marker reading missing — a full governed
        # land reported as the X-0044 bypass. Measured 2026-08-15: T-9378 closed 2026-06-05T21:09:30Z
        # by a synthetic probe, dispatched 15 days later 2026-06-20T10:52:40Z and then ran the entire
        # chain (task_picked / audit_pre / audit_post / task_closed) — all of it after the judged
        # terminal. The FIRST launch is the anchor, deliberately not the last: a re-dispatched task's
        # earlier attempt legitimately owns the earliest post-launch terminal, which is exactly the
        # slice the T-11026 instrument-gap tier exists to describe (T-10866 / T-10977) — anchoring on
        # the last launch would silently dismantle that tier instead of leaving it to do its job.
        launch = next(i for i, e in enumerate(evs) if e.get("type") == "bg_dispatch_launched")
        first_completion = next((i for i, e in enumerate(evs)
                                 if i > launch and e.get("type") in _DISPATCH_COMPLETION_TYPES), None)
        if first_completion is None:
            # No completion AFTER the launch — still in flight, and that stays a SKIP. A pre-launch
            # completion is not this dispatch's terminal, so it can never be reclassified into one:
            # the row leaves the report entirely rather than being judged against a foreign event.
            continue
        before = {e.get("type") for e in evs[:first_completion]}   # the chain that PRECEDED completion
        missing_claim = [t for t in _DISPATCH_REQUIRED_LIFECYCLE if t not in before]
        missing = list(missing_claim)
        audited = bool(before & set(_DISPATCH_AUDIT_TYPES))
        if not audited:
            missing.append("audit")
        if not missing:
            continue   # clean full-lifecycle land — not a row to surface
        # The 3-way tier (T-11021). A single-claim-miss on an otherwise externally-audited land is
        # NOT the X-0044 shape, so it does not carry that label: the down-tier is what keeps 'bypass'
        # meaning what its text says. The differential the other way is deliberate — a land missing
        # BOTH claim markers, or missing a claim marker with NO audit, still reads 'bypass'.
        if not missing_claim:
            # T-11026: before calling an audit absent, ask whether this check could SEE one. An audit
            # for the task after the judged completion (already in `types`) or outside the report
            # window (the caller's probe) means the instrument, not the task, is what fell short.
            audit_elsewhere = bool((types - before) & set(_DISPATCH_AUDIT_TYPES))
            if not audit_elsewhere and _audit_outside_window is not None:
                try:
                    audit_elsewhere = bool(_audit_outside_window(tid))
                except Exception:   # noqa: BLE001 — a failed probe must not turn into an accusation
                    audit_elsewhere = False
            if audit_elsewhere:
                rows.append({"task_id": tid, "completed": True, "missing": [],
                             "unobserved": ["audit"], "severity": "instrument-gap"})
                continue
            severity = "advisory"
        elif len(missing_claim) == 1 and audited:
            severity = "claim-gap"
        else:
            severity = "bypass"
        rows.append({"task_id": tid, "completed": True, "missing": missing,
                     "unobserved": [], "severity": severity})
    rows.sort(key=lambda r: r["task_id"])
    return rows

def _dispatch_quiescent(cls):
    """Journal-quiescence VIEW over the dispatch class (T-0583) — a pure derived projection, NO new
    liveness logic and NO process walk (CHARTER L59/148: detect+surface only). This is the signal the
    §Abnormal premature-exit / respawn-adopt PROCEDURE keys off — NEVER the launched pid. The
    2026-06-08 soak proved `kill -0 bg_dispatch_launched.data.pid` unreliable BOTH ways: pid-reuse ->
    false-ALIVE (masks a dead worker); the `claude -p` Popen-parent exits while the real worker keeps
    running under the SAME session_ref -> false-DEAD -> respawn-adopt over a still-live worker = a
    two-workers-on-one-worktree concurrency breach (incident, deviations
    `false-premature-exit-detection-launched-pid-unreliable-respawn-over-live-worker-concurrency-breach`
    + `premature-exit-pid-liveness-check-false-positive-on-pid-reuse`).
      - True  : non-terminal AND journal-stale (silent_stop | hang_suspect | launch-stall — no new
                events for the session_ref). Journal-quiescent → respawn/re-bootstrap is ELIGIBLE,
                but only after the controller's second predicate below. `launch-stall` (T-9749) is
                journal-quiescent like silent_stop (no worktree to adopt → re-bootstrap, not adopt).
      - False : `working` (recent events under the session_ref) → NOT quiescent → respawn DEFERRED.
                This is the predicate the real false-DEAD breach hinged on (the live worker kept
                emitting → `working`), and the pid is NEVER consulted.
      - None  : TERMINAL | no_dispatch — quiescence inapplicable (already done/halted, or no dispatch).
    NECESSARY-not-sufficient: `quiescent` is the JOURNAL predicate only. Before authorizing
    respawn-adopt the controller MUST ALSO verify NO live OS process is working under the session_ref
    (a controller PROCEDURE step — not done here; this read-only reader does no process walk). Full
    gate + the worker-side re-stamp-over-live fail-safe: patterns/background-session-operation.md
    §Abnormal → «Premature exit»."""
    if cls in ("silent_stop", "hang_suspect", "launch-stall"):
        return True
    if cls == "working":
        return False
    # closed_pending_land (T-0691): work built+closed but NOT integrated on main — the recovery is
    # to LAND it, NOT respawn-adopt (the task is already done in-worktree). Quiescence is the
    # respawn-adopt predicate, so it is inapplicable here -> None (like a terminal). The distinct
    # `closed_pending_land` class label is what tells the controller "land it".
    return None

def _dispatch_recovery_hint(cls, task_id=None, detail=None):
    """Advisory NEXT-ACTION hint per recovery-bearing dispatch class (T-1117) — a PURE derived
    projection over the class, NO new liveness logic and NO process walk (detect+surface only,
    CHARTER L59/148). Surfaced on the dispatch-status row so a controller reads the concrete
    recovery route off the verdict instead of reconstructing it from §Recovery-trigger / §Abnormal
    prose each poll. The route per class is the doctrine, condensed:
      - closed_pending_land → built+closed, only INTEGRATION missing → grace-wait for the worker's OWN
        self-land to reach terminal FIRST (T-9258 — it is a transient self-land phase; firing `land`
        against a live self-land RACES it), then `land` only if still un-landed (NEVER respawn, T-0691).
      - hang_suspect → non-terminal + a LIVE orphan worktree claim = the dead-but-unlanded case →
        once the Confirmed-dead GATE holds, `worktree adopt` the orphan worktree (T-1117 verb), then
        resume/close/land. This is the route the dead-but-unlanded worker (the T-1052 root cause) takes.
      - silent_stop → non-terminal but NO live worktree claim (already landed / removed / never made)
        → nothing to ADOPT → re-bootstrap a fresh worker and resume from current_stage on main.
      - launch-stall → launched but never CAME UP (identity not-yet-started) and never claimed, past
        the near-launch bootstrap grace (T-9749) → NOT dead-but-unlanded (no worktree to adopt) →
        confirm no live `--session-id` proc UNDER THE WORKER's assigned ref (the row's surfaced
        session_ref), then re-bootstrap a fresh worker. SURFACE for a confirmed controller decision —
        never auto-kill/redispatch on silence (races a slow-but-live boot).
    None for working / TERMINAL / no_dispatch (no recovery action). `task_id` is interpolated into the
    concrete command when known (the wave + single-task callers both pass it).

    T-11565 — `detail` ROUTES the launch-stall route, because the class alone does not determine the
    remedy: a `transient-overload` stall (the log declares its own failure temporary) is the one
    launch-stall whose answer is WAIT-then-retry, not the standing "confirm dead, re-bootstrap"
    advice. OPTIONAL by construction: `detail=None` (the 2-arg call every existing caller and test
    makes) returns exactly what it returned before this card, byte for byte."""
    t = task_id or "T-XXXX"
    if cls == DISPATCH_CLASS_CLOSED_AWAITING_CONTROLLER_LAND:
        # T-12351 — the contracted completion under the controller-lands regime: the ONE owed step is
        # the plain land from main. Not a recovery route (no grace-wait, no liveness check, no
        # `recover-land` — its predicate is a dead worker and this worker simply finished).
        return (f"built+closed as CONTRACTED under land_regime: controller — the worker stopped after "
                f"`task close` on purpose; nothing to recover. Next: `bin/yitc-v2 land --task {t}` "
                f"(from main)")
    if cls == "closed_pending_land":
        return (f"built+closed, NOT integrated -> self-land likely IN PROGRESS (land verify is SILENT for "
                f"minutes — journal-silence is NOT death); grace-wait for terminal FIRST (T-9258: "
                f"closed_pending_land is a TRANSIENT self-land phase — re-poll until the worker's OWN self-land "
                f"reaches terminal [LAND: OK / `task/{t}` worktree removed] OR the worker is confirmed DEAD by a "
                f"LIVE-PROC check NOT journal-silence; firing recovery against a live self-land RACES it), THEN "
                f"`worktree recover-land --task {t}` only if still un-landed (T-10139: governed, fail-closed, "
                f"idempotent — re-verifies land-dead+proc-dead IN-CODE, adopts + lands; never respawn)")
    if cls == "hang_suspect":
        return (f"confirm dead (Confirmed-dead GATE: no live `--session-id` proc) -> "
                f"`worktree adopt --task {t} --confirm-dead` -> resume/close/land")
    if cls == "silent_stop":
        return ("no live worktree (already landed/removed) -> nothing to adopt; "
                "re-bootstrap a fresh worker, resume from current_stage")
    if cls == "launch-stall" and detail == _STALL_DETAIL_TRANSIENT:
        # T-11565 — the log NAMED its own cause as a temporary server-side condition. Nothing is wrong
        # with the task, the worker or the credential, so the generic "confirm dead, re-bootstrap"
        # advice reads as an investigation this row does not need. Report the remedy the cause implies —
        # WAIT, then re-dispatch the SAME task unchanged. This is ADVICE ONLY: no retry machinery, no
        # backoff policy, no auto-redispatch (that is orchestrator territory, CHARTER §6) — the verb
        # states what a controller should do and mutates nothing, exactly like every sibling route here.
        return ("launched but the bootstrap died on a TRANSIENT server-side condition its own launch "
                "log declares TEMPORARY — not a dead worker, not a bad task, not a credential fault "
                "(contrast auth-failure, which needs a human). NOTHING to adopt and nothing to "
                f"investigate: WAIT for the provider to recover, then re-dispatch {t} UNCHANGED. "
                "Re-dispatching immediately just re-dies while the condition lasts")
    if cls == "launch-stall":
        return ("launched but never came up past the near-launch bootstrap grace (identity "
                "not-yet-started, no claim) -> NOT dead-but-unlanded (no worktree to adopt); confirm "
                "no live `--session-id <worker-ref>` proc, then re-bootstrap a fresh worker. SURFACE "
                "for a confirmed controller decision — never auto-kill/redispatch on silence")
    return None


def _is_checkout_root(d) -> bool:
    """Is `d` ITSELF a git checkout root — a repo root (`.git` DIR) or a linked worktree root
    (`.git` FILE)? T-11085.

    Deliberately an EXACT-ROOT test, never a `rev-parse`-style walk-up: it reuses
    `events._resolve_git_common_dir`, which inspects `d / ".git"` ALONE by pure path inspection (no
    subprocess, no parent traversal). That exactness is the whole point — a plain tmpdir created
    with `dir=REPO_ROOT` sits INSIDE a checkout but owns no marker of its own, so it answers False
    here while a walk-up would answer True and hand back the host's real journal (the T-11078 §4c
    seam; the same shape T-10869 fixed one seam of). Pinned in both directions by a tripwire."""
    try:
        return events._resolve_git_common_dir(Path(d)) is not None
    except (OSError, TypeError, ValueError):
        return False


def _coherent_default_loci(EVENTS_PATH, REPO_ROOT, _main_worktree):
    """The DEFAULT journal union's two loci — (local journal, main worktree or None) — resolved so a
    caller's locus can never be silently swapped for the HOST's. T-11085 / SPEC-0077.

    Two independent ways the pair goes wrong, both measured on the pinned cohort (T-11078 §4b: 1122
    escaping opens of the real ~136 MB journal from 111 of 792 files):

      (a) AN INCOHERENT PAIR. `EVENTS_PATH` and `REPO_ROOT` are separate globals, and a caller can
          rebind one without the other — `tests/test_dispatch.py#_repo_root` rebinds REPO_ROOT to a
          sandbox and leaves EVENTS_PATH pointing at the real checkout, which then gets folded from
          the stale half. So: EVENTS_PATH is honoured UNLESS its own directory is a checkout root
          OTHER than REPO_ROOT — i.e. it names a DIFFERENT checkout than the locus we were given —
          in which case the locus the caller actually named wins. This deliberately keeps the
          SPEC-0131 rule-1 scope-guarded redirect working: that target is a private TMPDIR file, no
          checkout root of its own, so it is honoured exactly as before (and it is already hermetic).

      (b) A WALK-UP FROM OFF-CHECKOUT. `_main_worktree` runs `git worktree list` FROM the locus, so a
          locus that is merely INSIDE a checkout (a tmpdir under REPO_ROOT) walks up and answers the
          host's real main. Resolve main ONLY from a locus that is itself a checkout root.

    In PRODUCTION both guards are no-ops: EVENTS_PATH.parent IS REPO_ROOT (module load and
    `_rebind_repo_root` keep them in lockstep) and REPO_ROOT is always a real checkout, so the
    main-checkout fold this reader legitimately performs is untouched — this narrows WHOSE journals
    are read, never WHICH journals a real checkout gets. Returning None for main is ordinary, and the
    reader's contract already says so (`if main_wt else None`) — the stub-legitimacy test of
    `lessons/a-slow-pinned-test-is-usually-a-sandbox-escaping-the-host`."""
    local = Path(EVENTS_PATH)
    root = Path(REPO_ROOT)
    if local.parent != root and _is_checkout_root(local.parent):
        local = root / "events.jsonl"          # (a) the pair disagreed — trust the named locus
    main_wt = _main_worktree(root) if _is_checkout_root(root) else None   # (b)
    return local, main_wt


def _parsed_lines(lines_iter):
    """Lines → parsed events, skipping blank/unparseable ones. Exists so `_dispatch_status_events` has
    ONE filter/dedup/sort body whether its rows came from a physical read or from the T-11453
    request-scoped fold — two bodies would be exactly the drift CHARTER §P5 forbids."""
    for line in lines_iter:
        line = line.strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            continue


def _dispatch_status_events(task_id=None, since=None, until=None, *, DISPATCH_EXCLUDED_TYPES, EVENTS_PATH, REPO_ROOT, _dispatch_task_of, _live_task_worktrees, _main_worktree, include_types=None, journals=None, _live_worktree_journal_roots=None):
    """Read BOTH journals (current EVENTS_PATH + the main checkout's events.jsonl) and return the
    dispatch-relevant events, de-duplicated by identity (ts|type|task_id|session_ref) and ts-sorted.
    The DEFAULT pair is resolved by `_coherent_default_loci` (T-11085) — same two journals for a real
    checkout, but never the HOST's when the caller's locus is a sandbox; see that helper.
    Reuses the per-line json.loads reader (Principle 1). Kill (b): DISPATCH_EXCLUDED_TYPES dropped by
    anchored envelope type. Kill (c): both journals scanned (a halt may live in the worktree journal,
    a close on main) — and the worktree leg is EVERY live non-main worktree, whatever its branch
    shape (T-11352); a row admitted only from such a leg carries `_locus` (the un-landed-evidence
    provenance the dispatch-status row names). `task_id` (when set) scopes to that task by the
    top-level-id-OR-data.task pair.
    `since`/`until` bound the window (honors the same ISO strings as `journal query`).

    `include_types` (T-10858 / SPEC-0119 rule 18) — an OPTIONAL set narrowing the read to those envelope
    types. This is a NARROWING OF THIS ONE READER, deliberately, not a second one: SPEC-0133 rule 5
    admits no second dispatch-journal path, and every caller must keep reading through the same union
    (local checkout + main + every live worktree) or the two halves of a fold can disagree about which
    journal they mean. Default None ⇒ every pre-existing caller is byte-identical.

    It exists because rule 18's fold must NOT bound its read by AGE (that bound is the very bug the rule
    removes), and an unbounded read of the whole union is seconds per journal. So that caller bounds by
    TYPE instead, and this narrowing makes it cheap: the type is tested against the RAW LINE first, so a
    line that cannot carry a wanted type is skipped before `json.loads` — the substring prescan is the
    whole speedup (measured 3.47s → 0.56s per journal on the engine journal, 2026-08-09). The prescan is
    only ever a cheap SUPERSET filter — a line that merely mentions a type in its payload survives it and
    is then rejected by the exact `type` check below, so the result is identical to filtering after a
    full parse. That equivalence is pinned by a tripwire, not assumed.

    `journals` (T-11022) — an OPTIONAL EXPLICIT locus: read exactly these journal paths INSTEAD of the
    default union above. Like `include_types` it is a re-pointing of THIS ONE reader, not a second one
    (SPEC-0133 rule 5), and default None ⇒ every pre-existing caller is byte-identical. It exists for
    the lifecycle-integrity sweep's consumer fold, which must judge each project's journal SEPARATELY:
    task ids are allocated PER PROJECT, so a consumer's `T-0001` and the kernel's `T-0001` are different
    tasks, and folding every locus into one event list would merge them into one row (inventing both
    false flags and false cleans). The caller therefore loops loci and passes one at a time; widening
    the default union instead would have produced exactly that merge. The main-checkout + live-worktree
    union is deliberately NOT applied to an explicit locus — those are THIS repo's siblings, and a
    foreign repo's worktree frontier is neither enumerable from here nor this reader's business."""
    include_types = frozenset(include_types) if include_types else None
    main_ref = None                    # T-12129 — set only on the DEFAULT union (see below)
    narrow_exempt = set()              # T-12129 — the legs that carry the shared span (see below)
    explicit_locus = journals is not None
    if explicit_locus:
        journals = list(journals)
    else:
        local, main_wt = _coherent_default_loci(EVENTS_PATH, REPO_ROOT, _main_worktree)
        main_j = (main_wt / "events.jsonl") if main_wt else None
        # Drop the main leg when it IS the local journal (a run ON main): the (ts|type|task|
        # session_ref) dedup below already made that second pass output-identical, so reading the
        # same ~136 MB file twice was pure cost. A strict subtraction, never a visibility change.
        journals = [local, None if (main_j is not None and main_j == local) else main_j]
        # T-12129 — the leg a worktree leg is compared against for its shared-prefix offset below.
        # It is the leg that CARRIES the shared region, which is `main_j` when the union has a
        # separate main leg and `local` when the run IS on main (the line above dropped the second
        # copy precisely because they are the same file). None when no main journal resolves at all —
        # and then no offset is taken, because nothing is established to carry the skipped rows.
        main_ref = main_j or (local if main_wt else None)
        # ... and the legs that must NEVER be narrowed, because they are the ones CARRYING the
        # shared region for everyone else. The main leg is obvious. The LOCAL leg is not, and it is
        # the one this rule exists for: run from inside a worktree, `local` IS that worktree's
        # journal and is therefore also a member of `wt_journal_set`, so a `p in wt_journal_set`
        # test alone narrows it — and then a row shared with main is admitted from the MAIN leg
        # instead of from the local one and loses its T-11352 `_locus` stamp. That is a changed
        # answer, not a narrower read, and the AC1 multiset differential caught it (the arm compares
        # the `_locus` keys precisely so it would). Every OTHER worktree leg sits AFTER these two in
        # the list, so its shared rows were already being admitted from one of them, stamped exactly
        # as before — which is what makes narrowing those output-identical.
        narrow_exempt = {q.resolve() for q in (local, main_ref) if q is not None}
    # T-0566: UNION the live task/ worktree journals too. An in-flight worker's events sit in its
    # PRIVATE task/T-XXXX worktree journal until land — invisible on main — so a dispatch-status run
    # from main otherwise sees only the stale foreign task_filed + the live claim and misreads a
    # healthy worker as hang_suspect(foreign) (incident 2026-06-08 T-0561). Enumerate the live worktree
    # frontier and add each one's events.jsonl. NO new liveness policy: the (ts|type|task|session_ref)
    # dedup below folds overlaps, the missing-file guard skips a removed worktree dir, and the
    # per-phase staleness recency check (T-9748) still decides working/stale — the union only WIDENS
    # visibility (a dead sibling's old events stay stale). Read-only durable-state read, no new store.
    # Skipped for an EXPLICIT `journals` locus (T-11022) — see the docstring: a foreign repo's worktree
    # frontier is not this repo's to enumerate, and mixing it in would re-merge the loci.
    # T-11085: enumerated only for a locus that IS a checkout — the frontier walk resolves from the
    # SAME call-time location as the main leg above, so an off-checkout locus must not reach it either.
    # T-11352 — the locus is EVERY live non-main worktree (`_live_worktree_journal_roots`), NOT only
    # the `task/T-XXXX` ones. Keying this union on the CLAIM set made a worker's visibility depend on
    # its BRANCH SHAPE: a dispatched worker whose events land on a `work/<slug>` branch was invisible,
    # so its session_started never resolved (identity `not-yet-started`) and its bg_dispatch_halted
    # was never read — the row classified `launch-stall(no-claim-past-grace)` and PRINTED
    # "re-bootstrap a fresh worker" over a worker that had done the work and halted deliberately
    # (kupiclub X-1024 / T-0444). A widening of THIS ONE reader's locus, not a second reader
    # (SPEC-0133 rule 5); the claim set itself stays task-keyed, where task-only is correct.
    wt_journals = []
    if not explicit_locus and _is_checkout_root(REPO_ROOT):
        # T-11352 — the union locus WIDENS to every live non-main worktree, supplied ADDITIVELY as
        # the DEFAULTED `_live_worktree_journal_roots`. The BASE stays `_live_task_worktrees` — the
        # parameter main's 24 call sites inject — whose name and meaning are UNCHANGED (renaming it
        # broke every one of them); a caller that supplies only the base gets exactly the old
        # behaviour, which is what keeps every existing caller and its hermetic stub working.
        _roots = {f"task/{t}": p for t, p in _live_task_worktrees().items()}
        # The WIDENING is additionally gated on LOCUS COHERENCE (T-11085's own principle, applied to
        # the frontier leg): `_live_worktree_journal_roots` resolves the frontier from the module-level
        # REPO_ROOT, not from the locus passed in here, so it is only in lockstep with the local+main
        # legs when EVENTS_PATH IS this root's own journal. In production that always holds. When it
        # does not — a caller reading a journal that is not this root's — the base is already the
        # caller's own (injected, hence redirectable) view and the wider frontier would be a DIFFERENT
        # checkout's, so mixing it in would re-merge the loci T-11085 separated.
        if _live_worktree_journal_roots is not None and \
                Path(EVENTS_PATH).resolve().parent == Path(REPO_ROOT).resolve():
            _roots.update(_live_worktree_journal_roots())
        wt_journals = [wt / "events.jsonl" for wt in _roots.values()]
        journals += wt_journals
    # T-11352 — the un-landed-evidence provenance (AC3), computed BY THIS SAME READ, no second scan.
    # `journals` is ordered [local, main, *worktrees], so an event that ALSO exists on main is
    # admitted from the main leg first and the branch copy is dropped by the dedup below. Tagging
    # only the worktree legs therefore marks exactly the rows that exist ONLY on an un-landed branch
    # — which is what a controller reading main cannot corroborate and must be told where to find.
    wt_journal_set = {Path(j) for j in wt_journals}
    # T-12144 (SPEC-0190 rule 10) — DE-DUPLICATE THE LEG LIST BY RESOLVED PATH, keeping the FIRST
    # occurrence. A checkout that is itself one of the live task worktrees appears TWICE in the list
    # above: once as `local` and once as its own member of `wt_journals`. Both legs opened the same
    # bytes, and every row the second one produced was already in `seen` and thrown away — so this
    # removes a read, never a row. Measured on this repo 2026-09-05: `journal query --dispatch-status`
    # read 14 journals over 13 distinct paths, the repeat being 33,917 of 462,419 lines, which is the
    # whole of that seam's residual 1.079x rows_parse_ratio; with this it reads at 1.000x.
    #
    # IT EXTENDS THE DEDUP THAT WAS ALREADY HERE rather than adding a mechanism (CHARTER §P1 filter 1):
    # the `journals` assembly above already drops the MAIN leg when it IS the local one
    # (`None if main_j == local`), by exactly this argument. That test compares Path objects as
    # spelled; resolving generalises it to the worktree legs, whose spelling comes from a different
    # source (`_live_task_worktrees`) than `local`'s.
    #
    # ORDER AND LOCUS TAGGING ARE BOTH UNTOUCHED, which is what makes it output-identical. First
    # occurrence wins, so the surviving order is still [local, main, *worktrees] and the dedup below
    # still admits a row from the leftmost leg that carries it. `wt_journal_set` is built ABOVE from
    # the unfiltered `wt_journals`, deliberately: a checkout that is its own worktree leg keeps being
    # a member of that set, so the T-11352 un-landed-provenance stamp lands on exactly the rows it
    # landed on before.
    _seen_legs, _deduped = set(), []
    for _j in journals:
        if not _j:
            _deduped.append(_j)            # a None main leg is meaningful to the loop below; keep it
            continue
        try:
            _key = Path(_j).resolve()
        except OSError:                    # unresolvable (a removed worktree dir) — never collapse it
            _deduped.append(_j)
            continue
        if _key in _seen_legs:
            continue
        _seen_legs.add(_key)
        _deduped.append(_j)
    journals = _deduped
    # T-10387 — when `since` bounds the window, physically read only the journal TAIL newer than the
    # cutoff instead of parsing the whole (~85MB) file from byte 0. `cutoff` = since - margin (a line
    # older than it cannot be in-window even under land-fold/skew disorder); a failed parse of `since`
    # leaves cutoff=None → full read (fail-closed, same as a full-history query).
    cutoff = None
    if since:
        try:
            cutoff = (_dt.datetime.fromisoformat(since.replace("Z", "+00:00"))
                      - _dt.timedelta(seconds=_TAIL_WINDOW_MARGIN_SEC)).strftime("%Y-%m-%dT%H:%M:%SZ")
        except (ValueError, TypeError):
            cutoff = None
    seen, out = set(), []
    for j in journals:
        if not j or not Path(j).exists():
            continue
        p = Path(j)
        start = 0
        events_iter = None      # T-11453 — set when this journal is served from the request-scoped fold
        # T-12035 (SPEC-0190 rule 10) — CONSULT THE INSTALLED SCOPE BEFORE READING, not after. The
        # memo test below (`start == 0 and rows_memo_holds(p)`) already served the declared local
        # journal from the request's one fold, but only AFTER `_tail_window_start` had physically
        # seek-scanned it — a `note_fold` charged to a segment the scope already owns. The seek is
        # pointless for a memo-held journal by construction: the memo's fold IS the whole file, so
        # the window it would compute is the whole file (`start = 0`) whatever the cutoff. Ordering
        # the test first therefore removes a read and moves no answer. Every journal the memo does
        # NOT hold (main + up to 16 live worktrees) takes the seek branch verbatim, so the ~20 GB
        # retention argument for declaring only the local path is untouched.
        # T-12129 (SPEC-0190 rule 10) — START A WORKTREE LEG WHERE IT STOPS BEING A COPY OF MAIN.
        # Each live worktree journal is ~99.9% byte-identical to main's and was read in FULL to
        # recover the handful of un-landed rows the identity dedup then keeps; the rest was parsed
        # and thrown away. `_shared_prefix_start` VERIFIES how much of this leg main's leg already
        # carries (see that function for why the merge-base blob SIZE is not that answer), and every
        # byte below its offset is identical to main's at the same offset — so the main leg, which
        # reads that region, yields the identical row and the dedup admits it from there exactly as
        # it did before. A NARROWER SLICE of a read already being performed, not a cache: nothing is
        # stored, and the offset is recomputed from the two files on every call.
        #
        # THE THREE CONDITIONS ARE EACH LOAD-BEARING, so the fail-open direction is never a guess:
        #   * a WORKTREE leg only (`p in wt_journal_set`) — the local and main legs carry the shared
        #     region, so narrowing one of them would remove the very coverage the argument rests on;
        #   * a main leg must EXIST (`main_ref`) — with no main journal in the union nothing else
        #     reads the skipped span, so no offset is taken (this also excludes the explicit-`journals`
        #     locus and the off-checkout case, where `main_ref` is never set);
        #   * the T-11453 request memo must NOT hold this leg — a memo-held journal is served from
        #     rows already parsed, where an offset would save nothing and mean nothing;
        #   * and the leg must not be one of the two CARRYING legs (`narrow_exempt`) — see there.
        # The fourth condition is not a safety one but an honesty one: the plain UNBOUNDED branch
        # below folds the whole segment set (`segment_lines`), where this offset must not be applied
        # at all — it addresses the LIVE segment only, and starting there would silently drop the
        # leg's ARCHIVE segments, which nothing here has established are on main. So do not pay for
        # an answer that branch cannot use.
        mb = 0
        mb_tail = None      # T-12208 — the bytes above `mb`, read on the prefix probe's OWN handle
        if (cutoff is not None or include_types is not None) \
                and main_ref is not None and p in wt_journal_set and not rows_memo_holds(p):
            try:
                narrowable = p.resolve() not in narrow_exempt
            except OSError:
                narrowable = False                 # unresolvable — fail open, read from byte 0
            if narrowable:
                # T-12208 (SPEC-0190 rule 10) — ONE PHYSICAL OPEN PER ARTIFACT. `_shared_prefix_start`
                # opens this leg to VERIFY the shared frontier; both branches below then opened it a
                # SECOND time to read the span above that frontier. Measured 2026-09-07 inside one
                # scoped `session start`: 64 + 17 + 14 repeat opens over the same live-worktree legs,
                # so the request folded more artifacts than it read — the exact bound this card's AC1
                # is stated over, still violated INSIDE a single call after the seam's ReadScope
                # collapsed the repeats ACROSS calls. `with_tail=True` hands the span over from the
                # handle that is already open. The bytes are the leg's un-landed tail (the rows it
                # exists to contribute), never the ~99.9% below the frontier, and every fail-open exit
                # hands over no bytes — which is byte-for-byte today's from-zero path.
                mb = _shared_prefix_start(p, main_ref, with_tail=True)
                # `.tail` via getattr, never attribute access: a test double that substitutes a
                # plain `0` for the offset hands over no bytes, which is the fail-open path.
                mb_tail = getattr(mb, "tail", None)
        if rows_memo_holds(p):
            start = 0
        elif mb > 0:
            # T-12205 (SPEC-0190 rule 10) — ONE PHYSICAL READ PER ARTIFACT: when the shared frontier
            # is known, START THERE and do NOT seek-scan this leg a SECOND time. `_shared_prefix_start`
            # above has ALREADY physically read this artifact (its own `note_fold`), and
            # `_tail_window_start(p, cutoff, floor=mb)` would read it AGAIN (a second `note_fold`) only
            # to move the offset from `mb` UP to the window. Measured 2026-09-07 on a live
            # `journal query --dispatch-status` over 12 live worktrees: 11 of 12 legs folded exactly
            # 2x — 119 folds over 108 DISTINCT paths, i.e. 1.102 folds/artifact against rule 10's
            # stated bound of <= 1. Skipping the second read takes it to 1.00.
            # OUTPUT-IDENTICAL, and this is the load-bearing part: `_tail_window_start` is fail-closed
            # and floors at `mb`, so its answer is always in [mb, EOF) — [mb, EOF) is therefore a
            # strict SUPERSET of the window it would have returned. The per-event `if since and
            # ts < since` / `if until and ts > until` tests below then re-decide membership EXACTLY,
            # and the identity dedup is unchanged, so the admitted set is bit-for-bit the same. The
            # extra rows walked are only this leg's un-landed span above the shared frontier — the
            # handful of rows the leg exists to contribute — never the ~99.9% below it.
            # NOT A NEW SHAPE: the adjacent `if start == 0 and mb > 0 and include_types is not None:
            # start = mb` line directly below already makes exactly this substitution, on exactly
            # this argument, for the type-narrowed branch (T-12129).
            start = mb
        elif cutoff is not None:
            try:
                # Bounded twice over: by the journal count (kernel + live worktrees), and because this
                # is a backward byte-block seek from EOF reading only the tail past `cutoff`, never a
                # fold of the file.
                # inloop-journal-read: per-FILE — `p` is the loop variable, so each iteration reads a
                # DIFFERENT journal and there is nothing to hoist.
                # T-12205 — this branch is now the `mb == 0` case only (no shared frontier was taken,
                # or the probe found none), so it is this artifact's FIRST physical read, not a second.
                start = _tail_window_start(p, cutoff, floor=mb)
            except OSError:
                start = 0
        # T-12129 — the UNBOUNDED-but-type-narrowed branch has no `cutoff` to bound it, so the offset
        # IS its bound. `_bounded_superset_lines` takes a line-aligned `start` already (T-10939).
        if start == 0 and mb > 0 and include_types is not None:
            start = mb
        if start == 0 and rows_memo_holds(p):
            # T-11453 — this journal is already folded ONCE for this request (the local EVENTS_PATH,
            # the file the debt echo was folding fifteen times), so take the parsed rows instead of
            # re-reading and re-prescanning it. EXACT, not approximate: `start == 0` means the memo's
            # fold IS the whole file, and the include_types prescan below is only ever a cheap
            # SUPERSET filter whose survivors the exact `type` check re-decides — so parsing the whole
            # file and applying that same exact check admits the identical set. DECLARED PATHS ONLY:
            # every other journal in the union (main + up to 16 live worktrees, ~176 MB each) keeps
            # the prescan branch below verbatim, because memoizing them would retain ~20 GB.
            # SPEC-0190 rule 4 — the WHOLE journal (T-11649). The census records this reader's
            # horizon as the root journal's SEGMENT SET; folding the live segment alone made every
            # archived dispatch row invisible, so an old halt simply stopped existing (the X-1100
            # class). `segment_rows` reads each segment through this same `fold_rows` primitive,
            # so the memo above still serves the live segment and there is still ONE parse path.
            events_iter = segment_rows(p)
        elif include_types is not None:
            # T-10858 — the include_types PRESCAN, done on BYTES. An unbounded caller (rule 18, which may
            # not bound by age) reads whole journals, and decoding a ~116MB file to utf-8 only to discard
            # ~93% of its lines is where the time goes. So prescan the raw bytes and decode only the
            # survivors (measured: the same read drops from seconds to ~0.6s per journal). The test is a
            # cheap SUPERSET — a line merely MENTIONING a type in its payload survives it — and the exact
            # envelope-type check below still decides membership, so the result is identical to filtering
            # after a full parse (pinned by a tripwire, not assumed).
            # T-10939 — the bounded-read + superset-filter shape is NOT re-implemented here: it is the
            # shared `_bounded_superset_lines` primitive, the same one `tail_scan_events` runs on. Only
            # this reader's own decode policy stays local (an undecodable line is skipped, never
            # replacement-decoded). `start` is line-aligned by `_tail_window_start`, so no fragment drop.
            # T-12208 — when the prefix probe already read this exact span (`start == mb`), the
            # filter runs over THOSE bytes instead of re-opening the file. Identical answer by
            # construction: it is the same primitive, the same token set, over the same region.
            _raw = mb_tail if (mb_tail is not None and start == mb and mb > 0) else None
            candidates = []
            for bline in _bounded_superset_lines(p, include_types, start=start, _raw=_raw):
                try:
                    candidates.append(bline.decode("utf-8"))
                except UnicodeDecodeError:
                    continue              # an undecodable line was never a parseable event
            lines_iter = candidates
        elif start > 0:
            if mb_tail is not None and start == mb:
                # T-12208 — same single-open property as the prescan branch above.
                lines_iter = mb_tail.decode("utf-8").splitlines()
            else:
                with p.open("rb") as fh:
                    fh.seek(start)
                    lines_iter = fh.read().decode("utf-8").splitlines()
        else:
            # SPEC-0190 rule 4 — the WHOLE journal (T-11649). This is the UNBOUNDED read (no `cutoff`
            # window, no type prescan), and its declared horizon is the root journal's SEGMENT SET,
            # which is what the census records for this reader. A single-file `read_text` here made
            # every ARCHIVED dispatch row invisible, so an old halt simply stopped existing — and the
            # halts this reader answers for are exactly the ones that do not age out. `segment_lines`
            # streams each segment in segment order through the same one read path, so a ~176 MB
            # journal is still never materialised whole. The BOUNDED branches above are untouched:
            # they locate a window by physical position past `start`, which is a live-segment
            # question by construction (SPEC-0190 rule 6).
            lines_iter = segment_lines(p)
        if events_iter is None:
            events_iter = _parsed_lines(lines_iter)
        for e in events_iter:
            if not isinstance(e, dict):
                continue
            if include_types is not None and e.get("type") not in include_types:
                continue                                  # T-10858 — the exact narrowing (the prescan
                                                          # only ever over-admits, never under-admits)
            if e.get("type") in DISPATCH_EXCLUDED_TYPES:   # kill (b) — anchored type, not substring
                continue
            ts = e.get("ts") or ""
            if since and ts < since:
                continue
            if until and ts > until:
                continue
            if task_id is not None and _dispatch_task_of(e) != task_id:   # kill (a)+(c) scoping
                continue
            ident = (ts, e.get("type"), _dispatch_task_of(e), e.get("session_ref"))
            if ident in seen:
                continue
            seen.add(ident)
            if p in wt_journal_set:
                # T-11352 — un-landed branch provenance, stamped on a SHALLOW COPY. The rows reaching
                # here may be the request-scoped fold's OWN dicts (T-11453 `fold_rows`), shared with
                # every other reader of that journal this invocation; mutating them in place would
                # leak a private read-path key across readers. Copy only the rare stamped row.
                e = dict(e)
                e[DISPATCH_LOCUS_KEY] = str(p.parent)
            out.append(e)
    out.sort(key=lambda e: e.get("ts") or "")
    return out


class DispatchEventsMemo:
    """A REQUEST-SCOPED memo over ONE `_dispatch_status_events` binding, for a fold that reads it
    repeatedly (T-11438).

    THE SHAPE IT REMOVES, MEASURED. `_unmonitored_dispatch_view` (SPEC-0119 rule 12) reports N
    in-flight dispatches, and reads the dispatch journal ONCE PER DISPATCH: the view's own event
    lambda, `--fleet-verdict`, and then `--dispatch-status --task` for EVERY candidate — each of which
    bottoms out in `_dispatch_status_events(task_id=None, since=now-DISPATCH_WAVE_WINDOW_SEC)`. Those
    calls differ only in the SECONDS of their independently recomputed `now`; they are one read
    repeated. Profiled on the engine journal 2026-08-22: 15 reads, 143.1s, for 13 candidate tasks —
    and that fold aborted the task/T-11430 land twice the same day (a 180s subprocess timeout and the
    300s per-file land-verify cap).

    IT IS NOT A SECOND READER (SPEC-0133 rule 5). Every call still resolves through the SAME injected
    `_dispatch_status_events` union (local checkout + main + every live worktree). This is a
    request-scoped VIEW over one of that reader's own results — the identical framing its
    `include_types` (T-10858) and `journals` (T-11022) parameters carry: a re-pointing of THIS ONE
    reader, never a parallel path. No store, no cache file, no config, no new window constant.

    WHY DERIVING IS EXACT, NOT APPROXIMATE. Inside `_dispatch_status_events` the `since` / `until` /
    `task_id` tests are PER-EVENT filters applied BEFORE the dedup set and before the final ts-sort. A
    read taken at an EARLIER `since` is therefore a strict SUPERSET whose surviving members, dedup
    identity and order are unchanged by a subset filter — so filtering the snapshot returns the
    identical list the real reader would return for the narrower arguments. The base is taken
    `task_id=None` and `until=None` (upper-UNBOUNDED), so no requested `until` can reach past it and an
    `until` filter over the snapshot is exact. The one axis that can UNDER-reach is `since`: a request
    WIDER than the base is never served from the narrower snapshot and falls through to a real read.

    THE SAME ARGUMENT ON THE TYPE AXIS (T-11453). `include_types` is a per-event filter too, applied
    BEFORE the dedup set and the ts-sort, so a base read at a WIDER type set is a strict superset whose
    surviving members and order are unchanged by a narrowing type filter — and the dedup identity
    itself CONTAINS `type`, so rows of unwanted types can never have collided with wanted ones and
    their removal cannot resurrect a row the real reader dropped. A request is therefore served from
    any stored base whose type set is None-or-a-SUPERSET of it AND whose `since` is None-or-no-later
    than it. Measured motivation: `_debt_echo_lines` calls this reader twice, at the rule-18 halt set
    (6 types) and then at `land_completed` alone (rule 23) — the second is a strict subset of the
    first, and each call scans a ~3 GB union of 17 journals.

    WHAT IS NEVER SERVED. `journals` re-points the read at a different LOCUS, which no snapshot of this
    one can answer, so it always falls through. So does any request WIDER than every stored base — a
    falsy `since` against a windowed base, or a type set reaching outside a narrowed one. Fail-open by
    construction: every case this memo cannot answer EXACTLY takes the real reader, so a wrong answer
    is not reachable, only a slower one.

    SNAPSHOT CONSISTENCY IS A GAIN, NOT A COST. Serving the fold's later halves from one snapshot means
    they read ONE journal state instead of several taken seconds apart — the property
    `_dispatch_status_events` already argues for at its own union ("the two halves of this fold can
    never disagree about which journal they are talking about", CHARTER §P5).

    Args:
      read: the host `_dispatch_status_events` binding to memoize (injected, so a `-C` rebind or a test
        monkeypatch stays authoritative and this class needs no host residue of its own).
      _dispatch_task_of: the SAME task attribution the reader scopes by — never a second notion.

    `reads` / `served` count real journal reads vs memo-served calls; they are the collapse's probe
    subject (the T-11438 AC1 differential) and are read by the tests, never by a gate.
    """

    def __init__(self, read, _dispatch_task_of):
        self._read = read
        self._task_of = _dispatch_task_of
        # (types, since) -> rows. `types` is a frozenset or None (None = every type); `since` is the
        # ISO string the base was read at, or None for an unbounded-history base. A base can serve any
        # request whose type set is a SUBSET of its own and whose `since` is no WIDER than its own.
        self._bases = {}
        self.reads = 0
        self.served = 0

    def _covering_base(self, types, since):
        """The stored base — if any — that EXACTLY covers a (types, since) request.

        Covering means: its type set is None or a SUPERSET of the request's, and its `since` is None or
        no LATER than the request's. Both are widenings, and a wider base is a strict SUPERSET of the
        narrower read, so filtering it down returns the identical list (see the class docstring).
        """
        for (base_types, base_since), rows in self._bases.items():
            if base_types is not None and (types is None or not types <= base_types):
                continue
            if base_since is not None and (not since or since < base_since):
                continue
            return rows
        return None

    def __call__(self, task_id=None, since=None, until=None, include_types=None, journals=None):
        types = frozenset(include_types) if include_types else None
        # `journals` re-points the read at a different LOCUS, which no snapshot of this one can answer.
        # A request that is neither type-narrowed nor `since`-bounded is an unbounded full-history read
        # of every type — derivable only from an equally unbounded base, which is what the lookup below
        # tests, so it is not special-cased here.
        if journals is not None:
            self.reads += 1
            return self._read(task_id=task_id, since=since, until=until,
                              include_types=include_types, journals=journals)
        base = self._covering_base(types, since)
        if base is None:
            self.reads += 1
            # ALWAYS task_id=None + until=None — the widest snapshot this request can serve from.
            # The type set and `since` are taken AS REQUESTED, never widened: widening them would make
            # the first caller pay for reads no one asked for (an unbounded all-type read of the
            # 17-journal union is minutes), and the whole point of the T-10858 include_types narrowing
            # is that its caller must not pay that. So a base is only ever as wide as some real caller
            # already needed it to be.
            base = self._read(task_id=None, since=since, until=None,
                              include_types=include_types, journals=None)
            self._bases[(types, since)] = base
        self.served += 1     # every call that took the memo PATH, base-establishing one included
        out = base
        if types is not None:
            out = [e for e in out if e.get("type") in types]
        if since:
            out = [e for e in out if (e.get("ts") or "") >= since]
        if until:
            out = [e for e in out if (e.get("ts") or "") <= until]
        if task_id is not None:
            out = [e for e in out if self._task_of(e) == task_id]
        return out


# ── T-10473: the consumer-locus liveness fold for `--fleet-verdict` ─────────────────────────────────
# A KERNEL-dispatched worker whose WORK rides a CONSUMER journal (it runs `bin/yitc-v2 -C <consumer>`
# and every stage/land event lands in that consumer's events.jsonl) emits NOTHING to the kernel journal
# while alive: `_dispatch_status_events` reads only EVENTS_PATH + main + the LIVE task/ worktree journals
# (all kernel-locus), so the fleet-verdict recency clock ages the worker's last kernel event (its launch)
# to stale and — proc gone / no live claim — reports it `dead`. Three false CONFIRMED-DEAD reads on
# 2026-07-12 (T-10427 class) were exactly this. This helper folds the registry's yitc_v2 CONSUMER
# journals (the `consumer_journals` list the host derives from the SAME read-only nightly `_v2_projects`
# scan) and returns the set of session_refs that carry a FRESH line there — a positive LIVENESS signal
# the reader consults BEFORE declaring silent_stop/dead (SPEC-0133 rule 2 recency contract). PURE read,
# no store/emit (SPEC-0133 rule 1 §6-safe): it only widens visibility, exactly as the T-0566 live-worktree
# union does for the kernel-locus reader — a dead worker's OLD consumer lines stay stale and never revive.
def _consumer_live_refs(consumer_journals, now, window, _parse_iso_ts):
    """Set of session_refs with a line NEWER than `window` seconds in any consumer journal — the
    consumer-locus liveness signal. `consumer_journals` = the list of consumer `events.jsonl` Paths (host-
    injected; empty disables the fold — the differential the acceptance probe reads). FAIL-CLOSED /
    FAIL-OPEN toward NO false liveness: a missing/unreadable file or an unparseable line is skipped, a
    future-dated ts (beyond the clock-skew tolerance) is NOT counted fresh (mirrors the recency-robustness
    of `_classify_dispatch`, so a 2099-sentinel consumer row cannot resurrect a dead worker), and a line
    with no session_ref/ts contributes nothing. Reads only the journal TAIL past the recency cutoff
    (`_tail_window_start`) so a large (~85MB) consumer journal is not parsed from byte 0."""
    live = set()
    if not consumer_journals:
        return live
    cutoff = (now - _dt.timedelta(seconds=window + _TAIL_WINDOW_MARGIN_SEC)).strftime("%Y-%m-%dT%H:%M:%SZ")
    for j in consumer_journals:
        p = Path(j)
        if not p.exists():
            continue
        try:
            # Bounded by the registry consumer count, and the call is a tail seek past `cutoff`, not a
            # fold of the file.
            # inloop-journal-read: per-FILE — `p` is the loop variable (one consumer journal per
            # iteration), so there is nothing to hoist.
            start = _tail_window_start(p, cutoff)
        except OSError:
            start = 0
        try:
            if start > 0:
                with p.open("rb") as fh:
                    fh.seek(start)
                    text = fh.read().decode("utf-8")
            else:
                text = p.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(e, dict):
                continue
            sref = e.get("session_ref")
            if not sref or sref in live:
                continue
            ts = _parse_iso_ts(e.get("ts"))
            if ts is None:
                continue
            age = (now - ts).total_seconds()
            # fresh = within the recency window AND not future-dated past the skew tolerance
            if -_DISPATCH_FUTURE_SKEW_SEC <= age <= window:
                live.add(sref)
    return live


# ── T-10397: the tail-first read discipline for the dispatch in-flight guard ────────────────────────
# T-10387 tail-bounded every reader that passes a `since`; the in-flight guard sites (dispatch.py's 3
# guards + `--dispatch-status --task`) pass NONE, so each still parsed the whole ~90MB journal —
# `--dispatch-status --task` cost 5.54s of which CLI boot is 0.17s, paying TWO full scans. T-10396
# surveyed this reader and deliberately KEPT it full-read: unlike the receipt gates, a naive tail here
# fails OPEN. The guard's dangerous conclusion is the NEGATIVE ("no launch in flight" -> spawn), so a
# tail that MISSED an old launch would permit a DOUBLE DISPATCH. This helper converts it by running the
# T-10396 monotonicity argument in the GUARD's own direction, and is the ONE home for that discipline.
def _dispatch_events_tail_first(task_id, *, _dispatch_status_events, _dispatch_task_of, window_sec,
                                with_unscoped=False, now=None):
    """One task's dispatch events, read TAIL-FIRST and FAIL-CLOSED. Returns `(events, allev, launch_ts)`
    — `launch_ts` is the ts of the newest `bg_dispatch_launched` in `events` (None only after a FULL read
    has confirmed the task has no launch at all). `allev` is the UNSCOPED stream, and is None unless the
    caller asks for it (`with_unscoped`).

    NO NEW WINDOW CONSTANT: `window_sec` is injected, and every caller passes the EXISTING
    `DISPATCH_WAVE_WINDOW_SEC` — the same 24h window the `--dispatch-status` WAVE view already uses to
    bound "which dispatches are current" (CHARTER §P1 F1 — reuse the existing analog). The physical read
    it drives is T-10387's `_tail_window_start` (via `_dispatch_status_events(since=..)`); no second
    window primitive is introduced.

    WHY A TAIL POSITIVE MAY BE TRUSTED (the soundness argument, stated once for every guard site). A
    tail snapshot is a SUFFIX of the full one — it may MISS an old event, it can never INVENT one. And
    `_classify_dispatch` SEGMENTS to the NEWEST-LAUNCH EPOCH (T-10095): it keeps only the events at/after
    the latest `bg_dispatch_launched`. So a suffix that CONTAINS that newest launch row contains, by the
    definition of a suffix, the ENTIRE epoch the classifier reads — every event at/after it — and its
    classification is therefore BIT-IDENTICAL to the full read's. The launch row is the whole epoch's
    lower bound, so finding it is finding everything that matters.

    WHY A TAIL NEGATIVE MAY NOT. "No launch in the window" is NOT "no launch": an OLDER launch may sit
    below the cutoff. Concluding `no launch in flight` from it would let the guard SPAWN a second worker
    over a live one — fail-OPEN on a safety guard, the exact reason T-10396 KEPT this reader full-read.
    So a negative is NEVER concluded from a bounded read: it re-reads the FULL journal and decides on
    THAT. This is the mirror of `gates._gate_pass_tail_first`, whose trusted verdict is a CREDIT (its
    predicate `ts >= lower_bound` makes a suffix only ever EXCLUDE evidence, so a tail REFUSAL is the
    unsound direction there). Same discipline, opposite trusted pole — because the fail-closed direction
    is a property of the READER, not of the window (lessons/fail-closed-belongs-to-the-reader-not-the-
    parser.md).

    Consequence: `window_sec` carries NO correctness role. Shrinking it only moves work from the tail to
    the full-read fallback; a launch is either found (exact) or re-decided on complete history.

    THE COST OF FAIL-CLOSED, MEASURED AND STATED (real 90MB journal, 2026-07-11). The tail probe costs
    ~0.53s; a full union read costs ~2.9s scoped / ~4.0s unscoped. So a task WITH a launch (the hazard
    the guard exists for — a live in-flight id) is decided from the probe ALONE: 2.9s -> 0.53s. A task
    with NO launch anywhere (a fresh id) pays the probe AND the full read it already paid: +0.53s. That
    asymmetry is not a defect — it IS the fail-closed price, and it is paid on the path where the guard
    has nothing to guard (a fresh dispatch, about to spawn a multi-minute worker) rather than on the path
    where a wrong answer double-dispatches a live one. It is NOT recoverable by a cheaper probe: proving
    a task was NEVER launched is a statement about ALL history, and the only structure that could answer
    it cheaply is an index — a new store (CHARTER §P1, and the card's "add no second window primitive").

    `with_unscoped` — one read serving both views. `_dispatch_status_events` parses every line and only
    THEN filters by task, so a scoped read costs the same as an unscoped one; a caller that needs BOTH
    (`--dispatch-status --task`, whose identity / land_ok / land_abort checks scan the unscoped stream)
    therefore takes the unscoped read and derives the scoped view from it IN MEMORY, instead of reading
    the journal twice. That is what turns this verb's 2 full scans into 1 — the negative path gets FASTER
    (6.8s -> 4.5s) even though it pays the probe. Callers that need only the task's own chain (the
    dispatch.py guards) leave it False and keep the scoped read's smaller footprint."""
    now = now or _dt.datetime.now(_dt.timezone.utc)
    since = (now - _dt.timedelta(seconds=window_sec)).strftime("%Y-%m-%dT%H:%M:%SZ")

    def _read(bounded):
        s = since if bounded else None
        if with_unscoped:
            allev = _dispatch_status_events(task_id=None, since=s)
            return [e for e in allev if _dispatch_task_of(e) == task_id], allev
        return _dispatch_status_events(task_id=task_id, since=s), None

    evs, allev = _read(bounded=True)              # physically tail-bounded (T-10387)
    launch_ts = _newest_launch_ts(evs)
    if launch_ts is not None:
        return evs, allev, launch_ts   # POSITIVE — the whole newest-launch epoch is present (sound)
    # NEGATIVE — inconclusive by construction. Re-decide on the FULL history before ANY 'no launch'.
    evs, allev = _read(bounded=False)
    return evs, allev, _newest_launch_ts(evs)


def _dispatch_events_tail_first_multi(task_ids, *, _dispatch_status_events, _dispatch_task_of,
                                      window_sec, with_unscoped=False, now=None):
    """The SAME tail-first, fail-CLOSED read as `_dispatch_events_tail_first`, decided ONCE for a
    REQUEST of many ids instead of once per id. Returns `(chains, allev, launch_ts_of)` — `chains` maps
    each requested id to ITS OWN ts-ascending chain, `allev` is the UNSCOPED stream (None unless
    `with_unscoped`), `launch_ts_of` maps each id to its newest launch ts (None only after a FULL read
    has confirmed that id has no launch at all).

    T-11896. The soundness argument is NOT restated here — it lives once, in full, on
    `_dispatch_events_tail_first` (tail POSITIVE is exact because a suffix containing the newest launch
    contains the whole epoch `_classify_dispatch` reads; tail NEGATIVE is inconclusive, so it re-decides
    on the FULL journal). What this helper adds is WHERE that decision is taken.

    WHY THE DECISION IS THE REQUEST'S, NOT THE ID'S. "The tail window contains no launch" is a property
    of the WINDOW and the READ. `--dispatch-status --task A --task B --task C` used to run the whole
    reader once per id, and the ids a controller reads at a refill seam were launched HOURS earlier —
    so their launch rows sit below the cutoff and EVERY id took the negative arm: N ids, N FULL passes.
    Worse, those passes were byte-identical work: `with_unscoped=True` reads UNSCOPED and filters in
    memory, so the N passes parsed the same journal and differed only in which id they kept. Measured
    2026-08-30 on an 84MB journal: 26.5s for one id, 69.7s for three (~+21s per extra id, linear), an
    eight-id read past 120s — on the read SPEC-0133 §5 names as the PRIMARY way to read fleet state,
    with a hand grep of raw journal lines explicitly warned against. A cost that pushes its reader
    toward the forbidden grep is a correctness pressure, not a comfort one.

    So: ONE bounded read, partitioned per id. If EVERY requested id has a launch in the window, the
    whole request is answered from the tail (zero full passes, exactly as before). If ANY id has none,
    ONE full read is taken and EVERY id is re-derived from it — 1 full pass regardless of N.

    THE FAIL-SAFE IS UNWEAKENED, and that is the point of the shape. An empty window still never yields
    a 'no launch' answer; it only ever escalates the WHOLE request to the full journal. Escalating on
    ANY id's empty window is strictly MORE conservative than escalating per id, never less — an id is
    never answered from a bounded read that some OTHER id's emptiness has already discredited.

    NO ID IS ANSWERED FROM ANOTHER ID'S CHAIN (the concern the caller's in-loop comment named). The
    partition predicate is `_dispatch_task_of` — the SAME predicate `_dispatch_status_events(task_id=..)`
    applies to build a scoped read, so a partitioned chain is that scoped read, not an approximation of
    it. And an id whose launch WAS in the window loses nothing by being re-derived from the full read
    instead: `_classify_dispatch` segments to the newest-launch epoch, and the full read is a SUPERSET
    containing that same epoch, so its classification is bit-identical.

    NO NEW STORE AND NO NEW WINDOW: no cache, no index, `window_sec` is the injected, existing
    `DISPATCH_WAVE_WINDOW_SEC` its single-id sibling already uses (CHARTER §P1 F1)."""
    ids = list(dict.fromkeys(t for t in (task_ids or []) if t))
    now = now or _dt.datetime.now(_dt.timezone.utc)
    since = (now - _dt.timedelta(seconds=window_sec)).strftime("%Y-%m-%dT%H:%M:%SZ")

    def _read(bounded):
        # UNSCOPED always: a scoped read costs the same (`_dispatch_status_events` parses every line and
        # only THEN filters), and one unscoped pass serves every requested id's chain AND the unscoped
        # view — which is what collapses N passes into one.
        allev = _dispatch_status_events(task_id=None, since=(since if bounded else None))
        chains = {t: [] for t in ids}
        for e in allev:
            c = chains.get(_dispatch_task_of(e))
            if c is not None:
                c.append(e)
        return chains, (allev if with_unscoped else None)

    chains, allev = _read(bounded=True)              # physically tail-bounded (T-10387)
    launch_ts_of = {t: _newest_launch_ts(chains[t]) for t in ids}
    if all(v is not None for v in launch_ts_of.values()):
        return chains, allev, launch_ts_of   # POSITIVE for EVERY id — each whole epoch is present (sound)
    # NEGATIVE for at least one id — inconclusive by construction. Re-decide the WHOLE request on the
    # FULL history before ANY 'no launch': one full pass, not one per unanswered id.
    chains, allev = _read(bounded=False)
    return chains, allev, {t: _newest_launch_ts(chains[t]) for t in ids}


def _newest_launch_ts(events):
    """ts of the newest `bg_dispatch_launched` in a ts-ascending dispatch chain, or None."""
    e = next((e for e in reversed(events) if e.get("type") == "bg_dispatch_launched"), None)
    return (e.get("ts") or None) if e else None


def _dispatch_task_of(e: dict):
    """Pollution kill (c): the task id of a dispatch event = the TOP-LEVEL `task_id` (the T-0378
    contract form) OR the legacy `data.task` fallback (the run-9 form). Never an unscoped substring.
    Returns the id string or None."""
    tid = e.get("task_id")
    if isinstance(tid, str) and tid:
        return tid
    data = e.get("data")   # P5 tolerance: a scalar/list `data` has no fallback task (never .get-raise)
    dtask = data.get("task") if isinstance(data, dict) else None
    return dtask if isinstance(dtask, str) and dtask else None

def _event_task_of(e: dict, *, _dispatch_task_of):
    """The task id of any event — the dispatch top-level/`data.task` form (`_dispatch_task_of`) OR,
    for branch-carried events (land_completed / worktree_created), the id parsed from `data.branch`
    (`task/T-XXXX`) or `data.leaf` (`T-XXXX`). Returns the id string or None."""
    tid = _dispatch_task_of(e)
    if tid:
        return tid
    data = e.get("data") if isinstance(e.get("data"), dict) else {}
    branch = data.get("branch")
    if isinstance(branch, str) and branch.startswith("task/"):
        leaf = branch[len("task/"):]
        if leaf:
            return leaf
    leaf = data.get("leaf")
    return leaf if isinstance(leaf, str) and leaf else None

def _governed_read_target(file_path: str, *, GOVERNED_DIRS, GOVERNED_DOCS) -> str | None:
    """A Read `file_path` → its repo-relative governed-doc target, or None if not governed (D-0048).

    Worktree-agnostic: matches the canonical handbook by basename and the doc layer by directory
    segment, so a Read in any `<repo>*/…` checkout normalizes the same way.
    """
    parts = file_path.replace("\\", "/").split("/")
    if not parts:
        return None
    if parts[-1] in GOVERNED_DOCS:
        return parts[-1]
    for d in GOVERNED_DIRS:
        if d in parts:
            return "/".join(parts[parts.index(d):])
    return None

def _graph_query_node_ids(command: str, *, _GRAPH_QUERY_NODE_ID_RE) -> list:
    """Node-id(s) ACTUALLY queried by an EXECUTED `yitc-v2 graph query <ID>` argv in a Bash command
    string (T-0434, SPEC-0042 §3). Returns [] for any non-`graph query` command or an option-only form.

    STRUCTURAL parse, never a raw-text regex (the audit-pre false-mint risk): `echo "yitc-v2 graph
    query SPEC-0015"`, a `# yitc-v2 graph query SPEC-X` comment, and a heredoc body line must NOT mint a
    pass-granting id. Defenses, fail-closed (mint nothing on any doubt — a missed real fetch costs one
    redundant re-fetch; a false mint defeats the gate):
      - A command containing a heredoc operator (`<<`) is SKIPPED whole (its body is unparseable as
        argv — never misread a body line as an executed command).
      - Split on shell statement/pipeline separators `;` `&&` `||` `|` ONLY (NOT raw newlines — a
        multi-line construct must not be torn into pseudo-segments), then shlex.split each segment.
        shlex collapses a quoted "…echo argument…" into ONE token, so a quoted/echoed `graph query`
        never forms an adjacent argv pair — the structural defense against finding (audit-pre F1).
      - The segment's command word (after skipping `VAR=val` assignments + an optional `sudo`/`env`
        prefix) MUST be a yitc-v2 invocation (argv[0] basename == 'yitc-v2'); `echo`/`cat`/anything
        else mints nothing. A `#`-leading token (a comment) is not a yitc-v2 command word.
      - Within that argv, the `graph` `query` adjacent subcommand pair must be present; the first
        following NON-option token full-matching the node-id shape is the queried id.
    """
    import shlex
    if "<<" in command:                       # heredoc — body is not argv; never mint from it
        return []
    out: list = []
    # split on ; && || | (newlines stay inside a segment — never tear a construct apart)
    segments = re.split(r"\s*(?:;|&&|\|\||\|)\s*", command)
    for seg in segments:
        seg = seg.strip()
        if not seg or seg.startswith("#"):
            continue
        try:
            argv = shlex.split(seg)
        except ValueError:                    # unbalanced quotes etc. → fail-closed skip
            continue
        i = 0
        # skip leading VAR=val env assignments
        while i < len(argv) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", argv[i]):
            i += 1
        # skip an optional sudo/env launcher prefix
        if i < len(argv) and argv[i] in ("sudo", "env"):
            i += 1
            while i < len(argv) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", argv[i]):
                i += 1
        if i >= len(argv):
            continue
        cmd_word = argv[i]
        if cmd_word.startswith("#"):
            continue
        if os.path.basename(cmd_word) != "yitc-v2":   # the command word must BE the CLI
            continue
        rest = argv[i + 1:]
        # find an adjacent `graph query` subcommand pair; the positional id (if any) is the IMMEDIATE
        # next token. If that token is an OPTION (`--type`/`--projected`/…) there is NO positional id
        # (those forms are mutually-exclusive alternatives to the id) → mint nothing for this invocation.
        for j in range(len(rest) - 1):
            if rest[j] == "graph" and rest[j + 1] == "query":
                tail = rest[j + 2:]
                if tail and not tail[0].startswith("-") and _GRAPH_QUERY_NODE_ID_RE.fullmatch(tail[0]):
                    out.append(tail[0])
                break
    return out

def _infer_directive_classification(text: str) -> str:
    """Best-effort owner_directive label (D-0048): directive | question | stop | correction.

    Loose heuristic per D-0030 (strict normalization rejected) — a coarse cue, not a parser.
    Default = directive (the common case: an instruction / approval like «да», «делай», «1»).
    """
    t = text.strip().lower()
    if not t:
        return "directive"
    if any(w in t for w in ("стоп", "stop", "halt", "отмена", "cancel", "прекрат")):
        return "stop"
    first = t.split()[0] if t.split() else ""
    if t.endswith("?") or first in ("как", "что", "почему", "зачем", "где", "когда", "кто",
                                    "какой", "какая", "сколько", "how", "what", "why", "when",
                                    "where", "who", "which"):
        return "question"
    if first in ("нет", "no") or any(w in t for w in ("не так", "неверно", "поправ", "не то",
                                                      "wrong", "incorrect", "не верно")):
        return "correction"        # bare «нет»/«no» = a rejection/correction, not a directive
    return "directive"

def _journal_sync(session_ref: str | None = None, *, SYNC_STATE_DIR, _all_source_refs, _append_event, _attachment_injection, _cap_text, _checkpoint_path, _classify_cc_entry, _die, _extract_text, _governed_read_target, _graph_query_node_ids, _infer_directive_classification, _normalize_log_ts, _resolve_session_ref, _session_log_path, _provider_transcript_ref, _utc_now_iso, write_text_atomic) -> int:
    """Materialize new chat-class events from the session log (per D-0030 + SPEC-0004).

    session_ref None → current (fail-closed resolve). Returns count materialized.
    Fail-closed ONLY on catastrophic errors (explicit ref's log missing, log
    unreadable); per-line malformed = skip (lossy normalization).
    """
    import yaml
    # T-0357: under the YITC_EVENTS_SINK test quarantine (see _append_event) the sync is
    # INERT — no materialization, no checkpoint write. Fail-closed: with appends diverted
    # to the sink, materializing would advance the HOST checkpoint while the materialized
    # chat events never reach the host journal — silently LOSING them for the real session.
    if os.environ.get("YITC_EVENTS_SINK", "").strip():
        return 0
    ref = session_ref or _resolve_session_ref()
    log = _session_log_path(ref)
    if log is None and not session_ref:
        # T-12400: the IMPLICIT current-session resolve only. Since T-10152 an interactive session's
        # identity is a MINTED uuid that names no transcript, so this leg was reached on EVERY
        # interactive Controller verb and returned 0 — the auto-sync was structurally inert and every
        # real owner turn had to be hand-emitted (kupiclub X-1364 / aiseller X-1345). Retry with the
        # ref that NAMES the transcript (the live D-0030 provider carrier, else the provider id this
        # session recorded at birth). Rebind `ref` TOO, not just `log`: the checkpoint is keyed on
        # `ref`, so keying it on the ref that LOCATED the transcript gives the implicit path and the
        # explicit `--session-ref <provider id>` recovery path ONE shared cursor instead of two
        # cursors over the same file. Identity is untouched — this is the transcript name, never a
        # resolution fallback (SPEC-0137 Rule 4).
        alt = _provider_transcript_ref(ref)
        if alt and alt != ref:
            alt_log = _session_log_path(alt)
            if alt_log is not None:
                ref, log = alt, alt_log
    if log is None:
        if session_ref:                    # explicit recovery for a named session
            _die(f"session log not found for --session-ref {ref}")
        return 0                            # current session, no log yet → nothing to sync
    try:
        raw = log.read_text(encoding="utf-8")
    except OSError as exc:
        _die(f"session log inaccessible: {log} ({exc})")

    cp_path = _checkpoint_path(ref)
    last_uuid = None
    if cp_path.exists():
        try:
            last_uuid = (state.load_str(cp_path.read_text(encoding="utf-8")) or {}).get("last_processed_uuid")
        except Exception:
            last_uuid = None

    # Parse all entries once (lossy per-line skip).
    entries = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue                        # lossy per-line skip

    # Locate the checkpoint cursor. If a cursor was recorded but is NOT present in the
    # log (stale / rotated / truncated), treat as RECOVERY: rescan from the start with
    # full-history dedup — never skip-all-then-advance (audit-post F0 data-loss fix).
    start = 0
    recovery = last_uuid is None           # first sync = recovery-style (dedup vs history)
    if last_uuid is not None:
        idx = next((i for i, e in enumerate(entries) if e.get("uuid") == last_uuid), None)
        if idx is None:
            recovery = True                # stale cursor → full rescan, do NOT lose tail
        else:
            start = idx + 1                # steady state: only entries after cursor

    # Dedup ONLY on recovery/first-sync (full history — correct for any replay size).
    # Steady-state entries (after cursor) are new and cannot pre-exist → no dedup scan.
    seen = _all_source_refs() if recovery else set()

    new_count = 0
    for e in entries[start:]:
        ets = _normalize_log_ts(e.get("timestamp"))   # T-0095: utterance-time ts
        # T-0089: attachment entries carry the AUTO-LOADED context (nested_memory = CLAUDE.md/
        # AGENTS.md, skill_listing) → instruction_injection as a POINTER (target+size, no body).
        # User entries → owner_directive / slash_command (the directive IS its small content).
        if e.get("type") == "attachment":
            data = _attachment_injection(e)
            if data is None:
                continue                    # harness ephemera (reminders / tool deltas) = noise
            etype = "instruction_injection"
        elif e.get("type") == "assistant":
            # D-0048: a COMMANDED read — the AI Read a governed doc. The materializer used to drop
            # assistant entries entirely; capture each governed-doc Read as instruction_injection
            # arrival=commanded (POINTER-ONLY: target + arrival, NO size — the tool_use entry has no
            # body bytes, audit-pre F2). Per-target source_ref suffix keeps multiple reads in one
            # entry distinct (no dedup collision). Then `continue` (assistant text is not owner input).
            uuid = e.get("uuid")
            content = e.get("message", {}).get("content")
            for b in (content if isinstance(content, list) else []):
                if not (isinstance(b, dict) and b.get("type") == "tool_use"):
                    continue
                name = b.get("name")
                if name == "Read":
                    tgt = _governed_read_target((b.get("input") or {}).get("file_path") or "")
                    if not tgt:
                        continue
                    sref = f"{log}#uuid:{uuid}#read:{tgt}" if uuid else None
                    if sref and sref in seen:
                        continue
                    _append_event("instruction_injection", None,
                                  {"injection_kind": "commanded_read", "target": tgt,
                                   "arrival": "commanded", "form": "link_only",
                                   "inject_source": "commanded"}, source_ref=sref, ts=ets)
                    if sref:
                        seen.add(sref)
                    new_count += 1
                elif name == "Bash":
                    # T-0434 (SPEC-0042 §3): a pre-worktree `yitc-v2 graph query <SPEC>` is the pilot's
                    # ONLY pass-granting fetch (§2), but its `cli_invoked` event lives in the checkout's
                    # journal where it RAN — absent from a worktree branched off committed HEAD. The
                    # transcript is the cross-checkout carrier: re-materialize each EXECUTED graph-query
                    # invocation as a `cli_invoked{node_id}` so the fresh worktree's full recovery rescan
                    # reconstructs it LOCALLY (`_fetched_spec_ids` then credits it). Reuses THIS existing
                    # materializer path — no new store/hook (P1/P5). The id extraction is structural (an
                    # executed yitc-v2 argv only), never raw-text — see `_graph_query_node_ids`.
                    for nid in _graph_query_node_ids((b.get("input") or {}).get("command") or ""):
                        sref = f"{log}#uuid:{uuid}#cli_invoked:{nid}" if uuid else None
                        if sref and sref in seen:
                            continue
                        _append_event("cli_invoked", None,
                                      {"verb": "graph query", "node_id": nid},
                                      source_ref=sref, ts=ets)
                        if sref:
                            seen.add(sref)
                        new_count += 1
            continue
        else:
            etype = _classify_cc_entry(e)
            if etype is None:
                continue
            data = _cap_text(_extract_text(e.get("message", {}).get("content")))
            if etype == "owner_directive":      # D-0048: best-effort label on the owner channel
                data["classification"] = _infer_directive_classification(data.get("text", ""))
        uuid = e.get("uuid")
        sref = f"{log}#uuid:{uuid}" if uuid else None
        if sref and sref in seen:
            continue                        # dedup (replay / checkpoint loss)
        _append_event(etype, None, data, source_ref=sref, ts=ets)
        if sref:
            seen.add(sref)
        new_count += 1

    # Advance checkpoint to newest entry uuid (only when entries exist + changed).
    newest_uuid = next((e.get("uuid") for e in reversed(entries) if e.get("uuid")), last_uuid)
    if newest_uuid and newest_uuid != last_uuid:
        SYNC_STATE_DIR.mkdir(parents=True, exist_ok=True)
        write_text_atomic(cp_path, state.dump(
            {"session_ref": ref, "last_processed_uuid": newest_uuid,
             "updated_at": _utc_now_iso()}))
    return new_count

def _land_abort_suffix(ab, *, _normalize_abort_cause) -> str:
    """T-9240 (AC2): render the last-land-abort detail as an inline suffix for the recovery line —
    NAMES the cause + (when verify-failed) the failing test(s) + pinned/candidate verify mode, so a
    controller reads a concrete 'real pinned-fail on test_X.py' instead of theorizing/--ack-ing blind.
    Empty string when there is no pending abort.

    T-10892 (SPEC-0077 §3a): the failing ASSERTION(S) are named here too. The row has carried
    `failing_assertions` since T-9240 and this renderer dropped them, so the ONE controller-facing
    surface for a pending abort said WHICH FILE failed and never WHAT failed — the same question the
    abort block itself exists to answer. Bounded (first 3, de-duplicated, each clipped) because this is
    an inline suffix on a status line, not the block."""
    if not ab:
        return ""
    cause = ab.get("abort_class") or _normalize_abort_cause(ab.get("abort_reason"))
    parts = [f"last land abort: {cause}"]
    ft = ab.get("failing_tests")
    if ft:
        parts.append(f"failing test(s): {', '.join(ft)}")
    fa = [a for a in dict.fromkeys(str(x) for x in (ab.get("failing_assertions") or [])) if a.strip()]
    if fa:
        _shown = ", ".join(a if len(a) <= 120 else a[:117] + "..." for a in fa[:3])
        parts.append(f"failing assertion(s): {_shown}"
                     + (f" (+{len(fa) - 3} more)" if len(fa) > 3 else ""))
    vm = ab.get("verify_mode")
    if vm:
        parts.append(f"verify mode: {vm}")
    return "  [" + "; ".join(parts) + "]"

def _last_land_abort(events, task_id):
    """T-9240 (AC2): the most-recent UNRESOLVED land abort for this task's branch, or None. Scans the
    (unioned) event stream for `land_completed` rows on `task/<task_id>`; a non-abort (successful) land
    AFTER an abort CLEARS it (mirrors the repeated-abort streak reset — a landed task has no pending
    cause). land_completed carries no scoped task_id (only data.branch), so this is a TARGETED branch
    scan, not the dispatch-event scoping. Returns the abort row's `data` dict (carries abort_class /
    abort_reason / failing_tests / verify_mode)."""
    if not task_id:
        return None
    branch = f"task/{task_id}"
    last = None
    for e in events or []:
        if e.get("type") != "land_completed":
            continue
        d = e.get("data") or {}
        if d.get("branch") != branch:
            continue
        last = d if d.get("status") == "abort" else None
    return last

def _last_red_member_verdict(events, task_id):
    """T-11682 — the newest RED `land_member_verdict` row for this task's branch that belongs to the
    CURRENT land attempt, or None. PURE, read-only.

    WHY IT EXISTS. `_derived_halt_cause` arm (i) reads `_last_land_abort`, which is a
    `land_completed{status:abort}` row. A land that DIED mid-verify wrote no such row, so the whole
    derivation falls through to `unknown` — the dispatch reader reports the death with no cause at
    all. That is exactly the loss this card measures, in the surface a controller routes on. But the
    cause is NOT missing: the batch this land headed wrote it to MAIN's journal, on every member's
    `land_member_verdict` row, BEFORE the head died (measured 2026-08-26, batch `bat-2114bce5cf05`:
    six named pinned failures on all four member rows at 11:10:22Z; the head then died silently).

    BOUNDED TO THE CURRENT ATTEMPT, which is the whole of its correctness. Only rows NEWER than the
    newest `land_completed` for this branch — of EITHER status — are eligible. A later land that
    FINISHED, in either direction, closes the window on every red before it, so a branch that went
    red, was fixed, landed, and is now halted for some unrelated reason reads no cause from here. This
    is the same clearing rule `_last_land_abort` already applies ("a non-abort land AFTER an abort
    CLEARS it"), stated for the member-row arm and applied to BOTH statuses rather than only to ok:
    an abort is already arm (i)'s to answer, so a red older than it must not out-rank it either.

    `events` must be the UNSCOPED stream — like its two siblings, this matches by `data.branch`,
    because member verdict rows carry the branch and (for a work batch) no task id.
    """
    if not task_id:
        return None
    branch = f"task/{task_id}"
    last_completed_ts = None
    for e in events or []:
        if e.get("type") != "land_completed":
            continue
        if (e.get("data") or {}).get("branch") != branch:
            continue
        last_completed_ts = e.get("ts") or last_completed_ts
    last = None
    for e in events or []:
        if e.get("type") != "land_member_verdict":
            continue
        d = e.get("data") or {}
        if d.get("branch") != branch:
            continue
        # ts compares lexicographically — events are ts-sorted ascending, the same basis
        # `_last_land_ok` uses for its re-claim comparison.
        if last_completed_ts is not None and str(e.get("ts") or "") <= str(last_completed_ts):
            continue
        last = d
    return last


# T-11797 — the THREE dispositions a `requeued-after-red-batch` row can carry. Held as a constant set
# so the two render sites and the tripwire name the same strings, and so a reader can see at a glance
# that `penalised` is ONE of three readings rather than the only one.
#
# THIS IS NOT A VERDICT VOCABULARY. Rule 5's vocabulary (`_LAND_MEMBER_VERDICTS`) is CLOSED and owned
# by `bin/lib/batch_landing.py`; nothing here writes, extends or compares a verdict value except the
# single equality below. These are the names of a READING taken over keys the writer already stamped.
_BATCH_DISPOSITION_RELEASED = "released"
_BATCH_DISPOSITION_NOT_PENALISED = "not-penalised"
_BATCH_DISPOSITION_PENALISED = "penalised"
_BATCH_DISPOSITIONS = (_BATCH_DISPOSITION_RELEASED, _BATCH_DISPOSITION_NOT_PENALISED,
                       _BATCH_DISPOSITION_PENALISED)
# The ONE verdict value this reading applies to. Spelled here rather than imported because reading it
# is the whole of the coupling: `batch_landing` OWNS the string, this module only recognises it.
_BATCH_REQUEUED_VERDICT = "requeued-after-red-batch"


def _dispatch_batch_disposition(events, task_id):
    """T-11797 — WHETHER a red batch PENALISED this member or CLEARED it, on the surface a controller
    actually reads. Returns `{verdict, disposition, reason, head}` or None. PURE, read-only.

    THE DEFECT (measured 2026-08-28). A red batch attributed to its HEAD RELEASES its peers
    unpenalised, and the release is recorded: `_land_release_peers_for_solo_head` stamps
    `released_from_batch{reason: head-is-culprit, head}` and `batch_ineligible: False` on every peer's
    `land_member_verdict` row. But BOTH ends of the red fork emit the SAME verdict string —
    `_land_dissolve_batch` and the release path both call `_emit_land_member_verdicts(...,
    "requeued-after-red-batch", ...)` — deliberately, because rule 5's vocabulary is closed and
    `_land_batch_ineligible_branches` reads that exact string. So an EXONERATED member and a
    PENALISED one were externally identical: `task/T-11782` (released, `batch_ineligible: False`) and
    `task/T-11732` (marked, `red_isolation_decline{undecidable/pinned-entry}`) both read
    `verdict: requeued-after-red-batch`, and `--dispatch-status` rendered the two rows IDENTICALLY,
    with no batch fact at all. The only word a reader saw was the penalty word, for a branch that had
    been explicitly cleared. It cost a controller three misreads in one shift, three owner reports,
    and one card (T-11788) closed wont-do on the resulting false premise.

    WHAT THIS FIXES IS THE NAME AND THE RENDERING, NEVER THE BEHAVIOUR. Nothing here decides anything:
    every input was judged ONCE, at the seam that held both the member list and the failing set, and
    this COPIES it back out — the same copy-never-decide shape `_emit_land_member_verdicts` uses at
    the writing end and `_dead_land_red_cause` uses at the reading end. No verdict value is added, no
    member row changes, and who is penalised is untouched.

    IT READS ONE VERDICT AND ONE ONLY. A row whose verdict is not `requeued-after-red-batch` yields
    None: `landed` / `evicted-for-conflict` / `dropped-dead-member` / `unaccounted` are not about a
    red-batch penalty, and a reading that could dress one of them as `not-penalised` would be
    inventing a clearance out of a row that never faced the mark.

    THE THREE DISPOSITIONS, each decided by a key the writer already stamped:
      * `released`      — `released_from_batch` present. The head owned the red, so this peer was
                          taken out of the batch rather than marked. `reason` and `head` are copied
                          VERBATIM off that record and are never minted here.
      * `not-penalised` — `batch_ineligible is False` with no release key: the dissolve ATTRIBUTED its
                          red and proved this member innocent, so T-11272's one-round ineligibility
                          was explicitly WITHHELD. Tested with `is False`, never truthiness, because
                          ABSENT and FALSE mean different things — absent is the pre-T-11272 reading
                          every older row on main carries, and it is the PENALISED one.
      * `penalised`     — neither key. The genuine rule-4 mark, which is exactly T-11732's row.
    Collapsing `not-penalised` into `penalised` would reproduce this function's own defect one level
    down — two opposite facts under one word — so the three are kept distinct.

    BOUNDING IS INHERITED, NOT RE-INVENTED. It calls the EXISTING `_last_red_member_verdict`
    (T-11682), which already returns the newest member row for `task/<id>` belonging to the CURRENT
    land attempt — only rows newer than the newest `land_completed` of EITHER status. A branch that
    went red, was fixed and landed therefore reads no disposition from a stale round. One scan, one
    bounding rule, no second reader.

    `events` must be the UNSCOPED stream — like its three siblings this matches by `data.branch`,
    because member verdict rows carry the branch and (for a work batch) no task id.
    """
    row = _last_red_member_verdict(events, task_id)
    if not isinstance(row, dict):
        return None
    if row.get("verdict") != _BATCH_REQUEUED_VERDICT:
        return None
    released = row.get("released_from_batch")
    if isinstance(released, dict) and released:
        reason = str(released.get("reason") or "").strip() or None
        head = str(released.get("head") or "").strip() or None
        return {"verdict": _BATCH_REQUEUED_VERDICT, "disposition": _BATCH_DISPOSITION_RELEASED,
                "reason": reason, "head": head}
    if row.get("batch_ineligible") is False:
        return {"verdict": _BATCH_REQUEUED_VERDICT, "disposition": _BATCH_DISPOSITION_NOT_PENALISED,
                "reason": None, "head": None}
    return {"verdict": _BATCH_REQUEUED_VERDICT, "disposition": _BATCH_DISPOSITION_PENALISED,
            "reason": None, "head": None}


def _batch_disposition_token(disp):
    """T-11797 — the human row's `batch=` token for a `_dispatch_batch_disposition` record, or "" when
    there is nothing to say. PURE. One home for the rendering so the --task path, the wave path and
    the tripwire cannot spell it three ways.

    NEUTRAL BY CONSTRUCTION: it prints the disposition and, for a release, the reason the writer
    recorded — no age, no freshness verdict, no advice. Same discipline as the `marked=` label."""
    if not isinstance(disp, dict):
        return ""
    name = disp.get("disposition")
    if name not in _BATCH_DISPOSITIONS:
        return ""
    reason = disp.get("reason")
    return f"  batch={name}({reason})" if reason else f"  batch={name}"


def _last_land_ok(events, task_id):
    """T-9766: True iff the AUTHORITATIVE terminal journal event `land_completed{status:ok}` is the
    MOST-RECENT land outcome for this task's branch. A successful `land` is the direct LANDED signal
    — the reader keys off it (AFTER settle) rather than pid-death, closing the race where a
    (rebaseline-)`land` commits/emits its terminal event a few seconds after the worker pid appears
    gone (the bench 0/8-vs-6/8 misread). Complement of `_last_land_abort` (a later abort clears a
    prior ok; a later ok sets it — last-outcome-wins). land_completed carries no scoped task_id (only
    data.branch), so this is a TARGETED branch scan over the UNIONED stream, not the dispatch-event
    scoping — the SAME reason `_last_land_abort` scans by branch. Read-only; no new store/event.

    T-10042 (X-0185): distinguish a CLOSURE land from a REACTIVATION one. A task that already landed
    a closure (`land_completed{ok}` on this branch) can be reactivated/re-scoped — a same-session
    work-batch land flips tasks/<tid>.yaml back to `ready` on main — and RE-DISPATCHED. The fresh
    task/<tid> worktree INHERITS that stale closure land in its unioned stream, so a bare
    last-outcome-wins scan would report the live re-dispatch as TERMINAL(done). So the ok land is
    honored ONLY when NO re-claim (`task_picked` / `bg_dispatch_launched` for this task) postdates
    it: a fresh dispatch past a prior closure land means that land is a STALE closure signal, not the
    current dispatch's terminal. Normal flow is unaffected — within one build the claim precedes the
    closure land, so no re-claim postdates it. ts compares lexicographically (events are ts-sorted
    ascending, `_dispatch_status_events`), the same basis as the outcome scan above."""
    if not task_id:
        return False
    branch = f"task/{task_id}"
    last_ok_ts = None   # ts of the winning ok land (None when the last outcome is abort / no land)
    last_reclaim_ts = None   # ts of the latest re-claim (task_picked | bg_dispatch_launched) for this task
    for e in events or []:
        typ = e.get("type")
        if typ == "land_completed":
            d = e.get("data") or {}
            if d.get("branch") != branch:
                continue
            # last-outcome-wins: a later abort clears (None), a later ok sets the ts
            last_ok_ts = (e.get("ts") or "") if d.get("status") != "abort" else None
        elif typ in ("task_picked", "bg_dispatch_launched") and _dispatch_task_of(e) == task_id:
            last_reclaim_ts = e.get("ts") or ""
    if last_ok_ts is None:
        return False
    # a re-claim strictly AFTER the ok land supersedes it (the task was re-dispatched → not terminal)
    return not (last_reclaim_ts is not None and last_reclaim_ts > last_ok_ts)

def _normalize_log_ts(raw) -> str | None:
    """Provider session-log entry `timestamp` → envelope ISO-Z (second precision), or None if
    absent/unparseable (caller falls back to sync-time). T-0095: materialized chat-class events
    carry their UTTERANCE time, not the sync moment. Handles trailing Z / fractional seconds / offset."""
    if not raw or not isinstance(raw, str):
        return None
    try:
        from datetime import datetime, timezone
        dt = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (ValueError, TypeError):
        return None

def _proc_scan_is_takeable() -> bool:
    """T-11925 — CAN an exhaustive `--session-id` process scan be taken on THIS host, right now?
    True  = yes: `/proc` exists, is iterable, and every candidate's cmdline was readable, so a scan
            that finds no match is a DEFINITE negative — a statement about NOW.
    False = no: there is no procfs at all (a non-Linux host), the scan raised (hidepid / sandbox /
            restricted `/proc`), or at least one candidate's cmdline was UNREADABLE (PermissionError).
            A scan with doors it could not open is not exhaustive, so a no-match cannot rule a worker
            out, and `_session_proc_alive`'s fail-closed False is INDETERMINATE rather than negative.
    A vanished-pid ENOENT is ordinary churn and does NOT make the scan un-takeable — that pid is gone,
    which is exactly what an exhaustive scan is entitled to observe.

    WHY THIS IS REF-INDEPENDENT, and why that matters (the shape this fix turns on): the question
    "was the probe takeable?" is a property of the HOST, not of any one worker's ref. So the
    fleet-verdict reader answers it WITHOUT a second injected per-ref dependency — it keeps reading
    liveness through the ONE injected `_session_proc_alive` it always had. A caller that stubs that
    boolean (every hermetic sandbox) therefore keeps its behaviour EXACTLY: a stubbed True is alive, a
    stubbed False is a definite negative on any ordinary Linux host. Adding a per-ref tri-state dep
    instead would have made every un-migrated sandbox fall through to the host `/proc` and report its
    synthetic live workers as gone — a required-argument break wearing the costume of a behaviour
    regression. READ-ONLY, NO emit, NEVER kills."""
    try:
        proc = Path("/proc")
        if not proc.is_dir():
            return False
        self_pid = os.getpid()
        for entry in proc.iterdir():
            if not entry.name.isdigit() or int(entry.name) == self_pid:
                continue
            try:
                (entry / "cmdline").read_bytes()
            except PermissionError:
                return False   # a door we could not open — the scan is not exhaustive
            except OSError:
                continue       # process vanished — ordinary churn
    except Exception:
        return False           # the scan failed — indeterminate, never an asserted death
    return True


def _session_proc_alive(session_ref: "str | None") -> bool:
    """T-9240 (AC1) — the §Abnormal «Confirmed-dead GATE» predicate (b), in code: is a REAL OS process
    running the worker's launch invocation `--session-id <session_ref>` right now? READ-ONLY, NO emit,
    NEVER kills — a single TARGETED existence probe, NOT a process-TREE walk (CHARTER detect+surface;
    the prohibition T-0583 honored is the unreliable LAUNCHED-PID + the tree walk, NOT this blessed
    exact-adjacency match). Matches argv where an element == '--session-id' and the NEXT element ==
    session_ref EXACTLY (never a bare-`<ref>` substring — the 2026-06-08 controller-own-command
    false-positive), and EXCLUDES our own pid (the reader). Returns True ONLY on positive confirmation;
    False on not-found OR any scan failure — fail-closed toward the journal classification, so an
    unreadable /proc never MASKS a real death (it only declines to UPGRADE a confirmed-live worker).

    T-11925: UNCHANGED. The "was the probe takeable?" question is answered separately and
    ref-independently by `_proc_scan_is_takeable()`, so this predicate keeps its exact contract and
    every caller — including every hermetic sandbox that stubs it — is untouched."""
    if not session_ref:
        return False
    try:
        self_pid = os.getpid()
        proc = Path("/proc")
        if not proc.is_dir():
            return False
        for entry in proc.iterdir():
            if not entry.name.isdigit() or int(entry.name) == self_pid:
                continue
            try:
                raw = (entry / "cmdline").read_bytes()
            except OSError:
                continue   # process vanished / unreadable — skip
            argv = [a for a in raw.split(b"\x00") if a]
            for i, a in enumerate(argv):
                if a == b"--session-id" and i + 1 < len(argv) \
                        and argv[i + 1] == session_ref.encode("utf-8", "surrogateescape"):
                    return True
    except Exception:
        return False   # fail-closed: a scan error never asserts liveness
    return False

def _land_frontier_line(_live_land_frontier) -> "str | None":
    """T-10010: the cross-session land-frontier summary line for `journal query --dispatch-status`
    (human mode). Counts ALL live non-main worktrees — `task/` dispatches AND `work/` lands — so a
    controller sizes the land-admission wave against every session's lands on the box, not just its
    own dispatches (the 2026-07-02 `concurrent-land-thundering-herd-full-verify-per-ff-retry` miss:
    2 concurrent `work/` lands were invisible to the `task/`-only count). Returns None when the
    frontier helper is unavailable or the box is idle (total==0) — suppressed-when-clean."""
    if _live_land_frontier is None:
        return None
    try:
        fr = _live_land_frontier() or {}
    except Exception:
        return None
    total = fr.get("total") or 0
    if total <= 0:
        return None
    return (f"land-frontier (cross-session): {total} live worktree(s) — "
            f"task/ {len(fr.get('task') or [])}, work/ {len(fr.get('work') or [])}. "
            f"Size the land-admission wave against THIS count (all sessions' lands), "
            f"not your own dispatches.")

def _land_proc_alive(task_id: "str | None") -> bool:
    """T-10043 — is a REAL OS process running THIS task's `land` right now? The land-liveness
    discriminator carried on a `closed_pending_land` row (§Watcher): closed_pending_land is a
    TRANSIENT self-land phase (a worker `task close`s then `land`s in the same turn), so the
    controller must distinguish an ACTIVE self-land (leave it — firing its own `land` RACES it,
    E-0035) from an ABANDONED close (worker died un-landed — land it). READ-ONLY, NO emit, NEVER
    kills — a single TARGETED existence probe, the land sibling of `_session_proc_alive`.

    THE NUL-SAFE ELEMENT MATCH (the class this closes): /proc/<pid>/cmdline is NUL-separated, so a
    naive space-grep for `land --task T-XXXX` NEVER matches (the argv elements never join with
    spaces) -> false process-gone -> premature controller re-land (E-0035). So split on b"\\x00" and
    match ELEMENTS. Matching ELEMENTS (not a `pgrep -f`/flattened-line grep) is LOAD-BEARING for
    PRECISION: a dispatched worker's OWN claude process carries the whole dispatch preamble — which
    NAMES its task and the word `land` — as ONE big argv element, so a flattened-line substring/regex
    scan FALSE-POSITIVES on the booting worker's prompt (the T-10053 §(c) footgun; also observed live
    for X-0202's own worker). Element-matching excludes it: `land` is never a WHOLE element in the
    prompt, and the id is only a substring of that one big arg — never a path SEGMENT of a real
    filesystem-path element. So this stays a NUL-split element scan, NOT `pgrep -f`.

    Matches argv that carries a standalone `land` element AND an element in which the task id is a
    PATH SEGMENT — `== task_id` (the `land --task T-XXXX` form), a TRAILING `/<task_id>` (the
    `-C <worktree> land` form, worktree dir == the id), OR a MIDDLE `/<task_id>/` segment (X-0202,
    the T-10043 residual: a bare `land` run from INSIDE the `.../yitc-v2-wt/T-XXXX/bin/yitc-v2`
    worktree — that script-path element ENDS in `/bin/yitc-v2`, so the old `endswith('/'+id)` MISSED
    it though it CONTAINS `/T-XXXX/`). Requiring a path BOUNDARY (`/` before, `/` or end after) keeps
    the id from matching mid-token (a longer id `T-XXXXY`, an unrelated `.../T-XXXX-slug/...`), so the
    precision the element scan buys is preserved. EXCLUDES our own pid (the reader). Per-pid read
    races are SKIPPED (an unrelated pid that vanishes mid-scan must never flip a live land into
    land-dead); returns True ONLY on positive confirmation, False after a COMPLETED scan with no
    match OR on a truly GLOBAL scan failure (/proc absent / outer error) — fail-closed toward the
    conservative "not confirmed alive" (never MASKS a real live land into land-dead)."""
    if not task_id:
        return False
    try:
        self_pid = os.getpid()
        proc = Path("/proc")
        if not proc.is_dir():
            return False
        tid = task_id.encode("utf-8", "surrogateescape")
        tail = b"/" + tid          # trailing  .../T-XXXX      (worktree dir == the id)
        mid = b"/" + tid + b"/"    # middle     .../T-XXXX/...  (id is a path segment, X-0202)
        for entry in proc.iterdir():
            if not entry.name.isdigit() or int(entry.name) == self_pid:
                continue
            try:
                raw = (entry / "cmdline").read_bytes()
            except OSError:
                continue   # per-pid race: process vanished / unreadable — skip, NOT a global fail
            argv = [a for a in raw.split(b"\x00") if a]
            if b"land" not in argv:
                continue
            if any(a == tid or a.endswith(tail) or mid in a for a in argv):
                return True
    except Exception:
        return False   # fail-closed: a GLOBAL scan error never asserts liveness
    return False


def _work_land_proc_alive(slug: "str | None") -> bool:
    """T-11137 — is a REAL OS process running THIS `work/<slug>` batch's `land` right now? The
    work/-branch SIBLING of `_land_proc_alive`, in the same NUL-safe element shape. READ-ONLY, NO
    emit, NEVER kills.

    WHY IT EXISTS (the incident it closes, `lessons/a-presence-count-is-not-a-liveness-probe.md`):
    `_dispatch_readiness_report` used to answer "is a land running?" with
    `work_lands > 0 or any(_land_proc_alive(t) ...)` — where `work_lands` merely COUNTED existing
    `work/<slug>` worktrees parsed from `git worktree list`. A work/ worktree lives from
    `worktree new --work` until `land`, often hours, so that leg pinned `in_flight_land` true
    whenever any filing batch was open (measured 2026-08-15: 0 land procs alive, 3 open work/
    worktrees, signal true) and the controller's land-queue loops degraded into timers. A boolean
    that ORs a cheap PRESENCE proxy with a real PROBE takes the proxy's answer. The innocent origin:
    `_land_proc_alive` keys on a TASK ID and a work/ land has none — so presence was substituted for
    a probe. This function writes the missing probe instead; the frontier VIEW is unchanged and
    `live_worker_count` still legitimately counts worktrees (T-10010).

    Matches argv that carries a standalone `land` element AND one ANCHORED slug element. A slug is
    NOT as unique as a task id, so a bare trailing `/<slug>` (what the task-id sibling can afford)
    would be too loose here — every accepted form carries its own anchor:
      (a) BRANCH form      — `== work/<slug>` or a trailing `/work/<slug>`: the documented
                             `land --branch work/<slug>` argv, and `refs/heads/work/<slug>`.
      (b) WORKTREE-PATH form — a trailing `-wt/<slug>` or a contained `-wt/<slug>/`: the
                             `-C <checkout>-wt/<slug> land` child form, and a bare `land` whose own
                             script-path element is `.../-wt/<slug>/bin/yitc-v2` (the X-0202
                             mid-segment case the task sibling also had to learn). `<repo>-wt` is
                             the worktree-parent leaf `worktree new` places every linked worktree
                             under, so the `-wt/` prefix is the anchor.

    Inherits the sibling's hard-won discipline verbatim: /proc/<pid>/cmdline is NUL-separated, so we
    split on b"\\x00" and match ELEMENTS — never a flattened `pgrep -f` line, which false-positives on
    a booting dispatched worker whose whole prompt (naming `land`) is ONE argv element (E-0035 /
    T-10053 §(c)). EXCLUDES our own pid. Per-pid read races are SKIPPED (an unrelated pid vanishing
    mid-scan must never flip a live land into land-dead). Returns True ONLY on positive confirmation,
    False after a COMPLETED scan with no match OR on a truly GLOBAL scan failure — fail-closed toward
    "not confirmed alive", which never MASKS a real live land and never fabricates one."""
    if not slug:
        return False
    try:
        self_pid = os.getpid()
        proc = Path("/proc")
        if not proc.is_dir():
            return False
        sl = slug.encode("utf-8", "surrogateescape")
        branch = b"work/" + sl          # exact   work/<slug>            (--branch form)
        branch_tail = b"/work/" + sl    # trailing .../work/<slug>       (refs/heads/work/<slug>)
        wt_tail = b"-wt/" + sl          # trailing .../<repo>-wt/<slug>  (-C <worktree> land)
        wt_mid = b"-wt/" + sl + b"/"    # middle   .../<repo>-wt/<slug>/... (X-0202 script-path form)
        for entry in proc.iterdir():
            if not entry.name.isdigit() or int(entry.name) == self_pid:
                continue
            try:
                raw = (entry / "cmdline").read_bytes()
            except OSError:
                continue   # per-pid race: process vanished / unreadable — skip, NOT a global fail
            argv = [a for a in raw.split(b"\x00") if a]
            if b"land" not in argv:
                continue
            if any(a == branch or a.endswith(branch_tail)
                   or a.endswith(wt_tail) or wt_mid in a for a in argv):
                return True
    except Exception:
        return False   # fail-closed: a GLOBAL scan error never asserts liveness
    return False


def _worker_child_proc_kind(task_id: "str | None") -> "str | None":
    """SPEC-0133 (rule 2 evidence) — the slow-≠-hung discriminator: is a REAL OS child proc of THIS
    task's worker running RIGHT NOW, and of what kind? Returns one of {'auditor','test','land'} on a
    positive match, else None. READ-ONLY, NO emit, NEVER kills — a single TARGETED /proc existence
    scan, the fleet-verdict sibling of `_land_proc_alive` / `_session_proc_alive`, reusing the SAME
    proven NUL-safe element + task-id-PATH-SEGMENT match (a naive space-grep never matches
    NUL-separated cmdline; a substring match false-positives on a booting worker's prompt — E-0035 /
    T-10053). A live child proc means the worker is BUSY (auditing / testing / landing), NOT hung —
    so the verdict reads `alive` even while its own journal is momentarily quiet mid-audit.

    Kind by argv signature, priority land > auditor > test (the later a phase, the more decisive):
      - land    — a standalone `land` element + the task-id path segment (the `_land_proc_alive` shape).
      - auditor — a `codex` executable element (the governed auditor / codex-worker, spawned
                  `codex exec -C <worktree>` — the worktree dir carries the task id) + the path segment.
      - test    — a `pytest` element (the verify suite when run standalone) + the task-id path segment.
    Matches the task id ONLY at a PATH BOUNDARY (== tid, a trailing `/<tid>`, or a middle `/<tid>/`
    segment) — never mid-token, so a longer id / an unrelated `.../T-XXXX-slug/...` never false-hits.
    EXCLUDES our own pid; per-pid read races are skipped; returns None after a completed no-match scan
    OR on a GLOBAL scan failure — fail-closed toward 'no live child' (never fabricates a busy child)."""
    if not task_id:
        return None
    try:
        self_pid = os.getpid()
        proc = Path("/proc")
        if not proc.is_dir():
            return None
        tid = task_id.encode("utf-8", "surrogateescape")
        tail = b"/" + tid          # trailing  .../T-XXXX
        mid = b"/" + tid + b"/"    # middle     .../T-XXXX/...
        found = set()
        for entry in proc.iterdir():
            if not entry.name.isdigit() or int(entry.name) == self_pid:
                continue
            try:
                raw = (entry / "cmdline").read_bytes()
            except OSError:
                continue   # per-pid race: process vanished / unreadable — skip
            argv = [a for a in raw.split(b"\x00") if a]
            if not any(a == tid or a.endswith(tail) or mid in a for a in argv):
                continue   # not THIS task's process tree — the path-boundary scope
            # ACCUMULATE across ALL matching procs, then rank by priority below — returning the FIRST
            # match would let a concurrent test/auditor proc mask a live `land` (audit-post finding).
            if b"land" in argv:
                found.add("land")
            elif any(a == b"codex" or a.endswith(b"/codex") for a in argv):
                found.add("auditor")
            elif any(a == b"pytest" or a.endswith(b"/pytest") for a in argv):
                found.add("test")
        for kind in ("land", "auditor", "test"):   # priority land > auditor > test (decisiveness)
            if kind in found:
                return kind
    except Exception:
        return None   # fail-closed: a GLOBAL scan error never asserts a live child
    return None

def cmd_journal_fleet_verdict(args: argparse.Namespace, *, DISPATCH_BOUNDARY_TYPES, DISPATCH_STALE_NORMAL_SEC, DISPATCH_WAVE_WINDOW_SEC, _classify_dispatch, _consumer_journals, _dispatch_dead_but_unlanded, _dispatch_identity, _dispatch_status_events, _dispatch_task_of, _last_land_ok, _live_claimed_task_ids, _main_task_strand_state, _parse_iso_ts, _session_proc_alive, _worker_child_proc_kind, _proc_scan_takeable=None) -> None:
    """`journal query --fleet-verdict` — the §6-SAFE controller-observability verb (SPEC-0133), PURE
    READ-ONLY. Answers ONLY «what is observable NOW about each in-flight worker + what human decision
    (if any) is needed», derived from the CURRENT journals + proc table + worktrees. It persists no
    state, runs no loop/sleep/schedule, mutates nothing, re-invokes nothing, kills/lands/adopts
    nothing, and moves no queue item (the 7-clause §6-compliance test, SPEC-0133 rule 1) — a pure
    function of current state → a report, re-derivable every heartbeat tick.

    Output is WORKER-CENTRIC, keyed on `session_ref` (rule 4) — a warm worker drains a SEQUENCE of
    tasks, so a task reaching TERMINAL(done) does NOT extinguish a still-live worker. Per in-flight
    worker (one record):
      session_ref, task_ids (drain sequence, ts-ascending), class (the dispatch-status class of the
      worker's newest-active task), evidence {last_event_ts, last_event_type, proc_alive,
      child_proc (auditor|test|land|null), land_readiness}, verdict ∈ {alive, dead, needs-decision},
      verdict_basis (one line tying verdict → evidence). There is DELIBERATELY NO `recommended_action`
      key (external-audit finding): the verb reports state + THAT a decision is needed, never the
      mutating act (kill / adopt / re-dispatch) — choosing the act stays the controller's call.

    IN-FLIGHT filter: a worker is reported iff its proc is alive OR a live child proc is running OR it
    holds a non-terminal task — a worker whose only tasks are TERMINAL and whose proc is gone has
    released its slot and is dropped. The warm-worker IDLE-between-lands state (task A done, task B not
    yet claimed, proc alive) reads `alive` (proc-alive wins over the terminal task), NOT dead."""
    now = _dt.datetime.now(_dt.timezone.utc)
    since, until = getattr(args, "since", None), getattr(args, "until", None)
    if not since and not until:
        since = (now - _dt.timedelta(seconds=DISPATCH_WAVE_WINDOW_SEC)).strftime("%Y-%m-%dT%H:%M:%SZ")
    allev = _dispatch_status_events(task_id=None, since=since, until=until)
    # T-10473 — CONSUMER-LOCUS LIVENESS FOLD. A kernel-dispatched worker whose work rides a `-C` consumer
    # journal emits NOTHING to the kernel-locus journals `allev` reads, so its kernel recency clock ages to
    # stale and (proc gone / no live claim) it reads `dead` — the 3 false CONFIRMED-DEAD reads of 2026-07-12
    # (T-10427 class). Fold the registry's yitc_v2 consumer journals ONCE here and collect the session_refs
    # carrying a FRESH line there; a worker in this set is corroborated ALIVE by its consumer-locus activity
    # even when the kernel journal is silent. PURE read, no store/emit (SPEC-0133 rule 1) — a peer of the
    # T-0566 live-worktree union, just widening visibility to the consumer locus. Empty enumerator disables
    # the fold (the acceptance differential). Reuses the SAME recency window as the kernel silent_stop split.
    consumer_live = _consumer_live_refs(_consumer_journals(), now, DISPATCH_STALE_NORMAL_SEC, _parse_iso_ts)
    # T-11925 — is a DEFINITE process reading available on this host at all? Folded ONCE per run: it is
    # a property of the HOST, not of any worker's ref (see `_proc_scan_is_takeable`). Overridable for
    # tests via `_proc_scan_takeable`; when absent it defaults to the real predicate, and on any
    # ordinary Linux host that is True — so a caller that stubs only `_session_proc_alive` reads its
    # stubbed False as the DEFINITE negative it has always been.
    _scan_takeable = bool((_proc_scan_takeable or _proc_scan_is_takeable)())
    # SEED the task set from boundary events (the same wave seed as --dispatch-status), then classify
    # each with the SHARED _classify_dispatch — no second classifier path (SPEC-0133 rule 5 F1/F2).
    tids = []
    for e in allev:
        if e.get("type") in DISPATCH_BOUNDARY_TYPES:
            tid = _dispatch_task_of(e)
            if tid and tid not in tids:
                tids.append(tid)
    started = [e for e in allev if e.get("type") == "session_started"]
    per_task = {}
    for tid in tids:
        evs = [e for e in allev if _dispatch_task_of(e) == tid]
        launched = next((e for e in reversed(evs) if e.get("type") == "bg_dispatch_launched"), None)
        identity = _dispatch_identity(launched, started, now)
        land_ok = _last_land_ok(allev, tid)
        cls, detail, last_ts, sref = _classify_dispatch(evs, tid, now, identity=identity, land_ok=land_ok)
        detail = _owner_gated_detail(detail, allev, tid, _dispatch_task_of=_dispatch_task_of)
        # T-10378 — worker_parked is a ROW-TERMINAL event (the bg_dispatch_halted analog): a
        # dispatched worker AUTO-PARKED on an auditor-outage / orphan-recovery (SPEC-0103 §3a,
        # `_park_worktree`, T-9583) tears its worktree+branch down and leaves the task `ready` on
        # main → cleanly re-dispatchable. It is NOT a DISPATCH_TERMINAL_TYPES marker, so
        # `_classify_dispatch` reads a RECENTLY-parked task as `working`(recent); that kept the
        # parked/recovered dead worker in the in-flight set and WOKE `dispatch --watch` (T-10347) on
        # an already-recovered ghost every arm until recency aged it out (fingerprint
        # fleet-verdict-ignores-worker-parked-terminal, observed live 2026-07-10). Fold it here as a
        # worker-record in-flight refinement — a peer of the halted_tids surface / drop-terminal-
        # worker filter below, NOT a second classifier path (SPEC-0133 rule 5): a task is parked iff
        # its chain's NEWEST event is `worker_parked` (a later re-dispatch's task_picked /
        # bg_dispatch_launched sorts newer → not parked, so a re-claimed task un-parks by itself).
        parked = bool(evs) and evs[-1].get("type") == "worker_parked"
        # T-10577 (X-0428) — batch-end CARD cross-check. `land_ok` reconciles a landed task to
        # TERMINAL(done) off the land EVENT alone (line ~536), so a task that LANDED but never ran
        # audit-post/closure still reads terminal → a proc-gone worker is DROPPED by the in-flight
        # filter below and the batch reads FINISHED, hiding a task stranded mid-lifecycle (the
        # boomrocket incident — invisible until someone grepped). Cross-check the authoritative CARD
        # state on main (`_main_task_strand_state`, fail-open): a landed task whose card is still
        # `in-progress` and NOT paused is STRANDED — report-only, never folded into batch-finished. No
        # new FSM/store — a per-id read of fields already on main after `land`, the peer of the
        # halted_tids surface below (SPEC-0133 rule 5: no second classifier path — this reads the card,
        # not the journal-axis class).
        strand = _main_task_strand_state(tid) if land_ok else None
        stranded = bool(strand and strand.get("stranded"))
        per_task[tid] = {"cls": cls, "detail": detail, "last_ts": last_ts, "sref": sref,
                         "parked": parked, "stranded": stranded, "strand": strand}
    # GROUP tasks by session_ref → one worker record per live session (rule 4).
    workers = {}
    for tid in tids:
        r = per_task[tid]
        workers.setdefault(r["sref"] or "(unknown)", []).append(tid)
    live_claims = _live_claimed_task_ids()
    records = []
    for sref, wtids in workers.items():
        # drain sequence: ts-ascending by each task's last event (empty ts sorts first)
        wtids = sorted(wtids, key=lambda t: per_task[t]["last_ts"] or "")
        classes = [per_task[t]["cls"] for t in wtids]
        # T-10378 — a PARKED task is row-terminal (see the per-task fold above): exclude it from the
        # nonterminal set so a parked-only worker (proc gone, no child) is DROPPED by the in-flight
        # filter below, and a parked task never drives a still-live mixed worker's reported `class`.
        # T-12351 — closed_awaiting_controller_land is TERMINAL-EQUIVALENT here: the dispatch is over
        # by contract (the worker stopped after close as told), so its slot is released exactly like a
        # TERMINAL(done) row and it never yields the needs-decision that woke the watcher. The owed land
        # is read off `--dispatch-status` (its `recovery` cue), not off an in-flight row.
        nonterminal = [t for t in wtids if per_task[t]["cls"] not in ("TERMINAL", DISPATCH_CLASS_CLOSED_AWAITING_CONTROLLER_LAND)
                       and not per_task[t]["parked"]]
        # T-10193 (SPEC-0133) — a self-HALTED worker (`bg_dispatch_halted` terminal, e.g. a PRE-claim
        # halt at analysis that never created a worktree) classifies TERMINAL(halt): it carries no live
        # proc, no child proc, and no non-terminal task, so the IN-FLIGHT filter below would DROP it —
        # silently hiding an EXPLICIT self-halt that needs a controller re-dispatch decision. Surface a
        # RECENT, UNRESOLVED halt as its own `halted` / needs-decision record: the JOURNAL analog of the
        # admission-slot heartbeat (SPEC-0133 rule 2), reusing the SAME recency window + terminal detail
        # — NO new store/mechanism (CHARTER §P1). "Unresolved" USED to be read off the class alone: a
        # later claim (T-0606 live-claim override), a successful land (T-9766 land_ok reconcile), or a
        # re-dispatch (T-10095 newest-launch segmentation) would each have reclassified the task AWAY
        # from TERMINAL(halt). T-10771 (rule 2d) adds the FIFTH reclassifier those four missed — a halt
        # whose OWN CAUSE the journal records as CLEARED (`_halt_resolution`, FOUR arms — the task's
        # branch landed ok; the designed ceiling continuation ran (converged consult + granted GREEN
        # pass); a MAIN-attributed halt whose main went green again (T-11792); or the CARD itself was
        # disposed — parked / wont-do / closed (T-12068). Enumerated in full here per T-12273: this
        # comment named only the first two for as long as arms (iii)/(iv) existed, and the sibling
        # under-enumeration in the RENDER is what let a disposed card's halt be narrated as a consult
        # continuation with `@ None` timestamps). The
        # four above are all about the DISPATCH moving on; none of them notices the halt's own story
        # finishing, so T-10729's fully-recorded resolution still read as an open owner-gated block.
        # A STALE halt ages out of the window (heartbeat semantics) — the controller's live window to
        # decide, not a permanent orphan record.
        #
        # SCOPE THE TRIGGER, NOT THE VIEW (lessons/scope-the-trigger-not-the-view): a RESOLVED halt is
        # collected SEPARATELY rather than simply dropped. It still keeps its worker IN-FLIGHT below —
        # so nothing that is visible today becomes invisible — and only stops driving the
        # `halted`/needs-decision branch. Suppressing a live halt is a far worse failure than leaving a
        # resolved one visible, so every uncertainty resolves toward "still needs a decision".
        halted_tids, resolved_halt_tids, halt_res = [], [], {}
        for t in wtids:
            if per_task[t]["cls"] != "TERMINAL":
                continue
            if per_task[t]["detail"] not in _HALT_DETAILS_NEEDING_DECISION:
                continue
            hts = _parse_iso_ts(per_task[t]["last_ts"]) if per_task[t]["last_ts"] else None
            # Recency-robustness (T-10130 / SPEC-0133 rule 2): a FAR-FUTURE halt ts must NOT read as
            # fresh. (now - hts) goes NEGATIVE for a future ts and would pass the window, resurrecting a
            # spurious sentinel-dated halt (e.g. a 2098/2099 row) forever. EXCLUDE a ts more than the
            # clock-skew tolerance AHEAD of now (the same at-or-before-now guard the recency signal uses
            # in _classify_dispatch), so a future-dated halt ages out (fail-closed) instead of masking.
            if (hts is not None
                    and (hts - now).total_seconds() <= _DISPATCH_FUTURE_SKEW_SEC
                    and (now - hts).total_seconds() < DISPATCH_STALE_NORMAL_SEC):
                # T-10771 (rule 2d) — the resolution split. `allev` is the UNSCOPED stream, which arm
                # (i) needs: `land_completed` carries no task_id, only `data.branch`. Computed ONCE
                # per task and kept in `halt_res` — the render below reuses it rather than re-scanning.
                halt_res[t] = _halt_resolution(allev, t)
                (resolved_halt_tids if (halt_res[t] or {}).get("resolved") else halted_tids).append(t)
        # T-10577 (X-0428) — STRANDED tasks: a landed-but-unclosed in-progress card (per_task strand
        # cross-check above). Like halted_tids, this is a terminal-classed task that the in-flight
        # filter would DROP (proc gone) — surfacing it keeps the strand from folding into a finished
        # batch. No recency window: unlike a self-halt heartbeat, a stranded card is a PERSISTENT
        # artifact fact (it stays in-progress until someone closes/parks it), so it must remain visible
        # every tick until resolved, not age out.
        stranded_tids = [t for t in wtids if per_task[t]["stranded"]]
        # T-12304 — the CONTROLLER-WAIT stops in this wave, read off the SHARED `_classify_dispatch`
        # class (SPEC-0133 rule 5: no second classifier path — the class is minted once, above). Like
        # halted_tids/stranded_tids this is a terminal-classed task the in-flight filter would DROP
        # (proc gone), so it must be surfaced or the wave reads as a finished batch while the
        # controller's own step sits unnamed. No recency window: a pause is a PERSISTENT card fact.
        controller_wait_tids = [t for t in wtids if per_task[t]["cls"] == "paused"]
        marker_ts = None   # T-11344 — set ONLY by the halted branch below (see there)
        # T-10712 (X-0557) — the PAUSED-CARD detail. The DISPATCH_CLASS_VOCAB TERMINAL gloss already
        # documents the semantics correctly («the dispatch is over» ≠ «the task is done»: an
        # owner-wait PAUSE whose bookkeeping then landed also reads TERMINAL(done)) — and those
        # semantics STAY. The reported gap is DELIVERY: the gloss lives in the vocabulary while the
        # verdict ROW carried no signal, so a controller reading one row re-dispatched a task that was
        # merely waiting on an owner answer. Surface it off the SAME card cross-check already in hand
        # (`per_task[t]["strand"]`) — the sibling of stranded_tids, on the branch stranded_tids
        # DELIBERATELY excludes (`stranded` is positive-scoped to in-progress AND NOT paused, T-10577).
        # Report-only: no new class (TERMINAL stays TERMINAL), no new event/store, no verdict change,
        # and the IN-FLIGHT filter is UNTOUCHED — a paused-landed worker whose proc is gone still drops
        # as a released slot (the T-10577 boundary does not move). No recency window: a pause is a
        # PERSISTENT card fact, not a heartbeat.
        paused_tids = [t for t in wtids
                       if per_task[t]["cls"] == "TERMINAL" and (per_task[t]["strand"] or {}).get("paused")]
        # newest-active task drives the reported `class` (a non-terminal task if any, else the newest).
        newest_active = (sorted(nonterminal, key=lambda t: per_task[t]["last_ts"] or "")[-1]
                         if nonterminal else wtids[-1])
        cls = per_task[newest_active]["cls"]
        # evidence — the raw observables the verdict rests on (so the controller never re-greps).
        proc_alive = _session_proc_alive(sref) if sref != "(unknown)" else False
        # T-11925 — «the probe was TAKEN and came back NEGATIVE», which `proc_alive` alone cannot say
        # (it is fail-closed False for an unreadable /proc too). Only this state demotes the fold below.
        proc_reading_negative = (sref != "(unknown)") and (not proc_alive) and _scan_takeable
        # T-10473 — consumer-locus liveness: this worker carries a FRESH line in a `-C` consumer journal
        # (folded once above), so it is ALIVE even though the kernel-locus journals are silent. Treated as
        # a positive liveness corroboration PEER of `proc_alive` (a live process and a fresh consumer emit
        # are two independent alive-signals); consulted below BEFORE the silent_stop→dead recency verdict.
        consumer_alive = sref != "(unknown)" and sref in consumer_live
        # T-11925 (X-1206) — the fold may CORROBORATE liveness, it may not OVERRIDE a direct reading.
        # A process reading is a statement about NOW; a journal line is the record of a PAST act —
        # exactly what a dead worker leaves behind — so the two are not peers, and a fold that treats
        # them as peers cannot tell a worker that IS working from one that worked and died, for the
        # whole recency window (kupiclub 2026-08-31: `alive` returned with `proc_alive=false` printed
        # beside it, 11 minutes after the worker exited; the controller stood down from recovery for
        # 19 minutes because patterns/background-session-monitoring.md makes `alive` AUTHORITATIVE).
        # So the fold PROMOTES to alive only where no direct reading could be taken — which is exactly
        # the T-10473 rationale (journal.py's `_consumer_live_refs` header): a reader BLIND to the
        # consumer locus. Where the reading WAS takeable, the reader was not blind.
        # NARROW BY CONSTRUCTION: this gates the alive VERDICT only. The in-flight filter and the
        # stranded/halted guards below keep the RAW `consumer_alive` — dropping or mis-classing a
        # consumer-locus row is the T-10473 failure, and it is untouched here.
        consumer_promotes_alive = consumer_alive and not proc_reading_negative
        child = None
        for t in wtids:
            child = _worker_child_proc_kind(t)
            if child:
                break
        # T-10254 — a worker row's evidence is WORKER-OWNED: `sref` is the worker's own ref for a
        # dispatched task from the moment of dispatch (`_classify_dispatch` binds it to
        # `bg_dispatch_launched.data.expected`), so this session_ref filter excludes every
        # DISPATCHER-owned event BY CONSTRUCTION — no evidence-side allow/deny list is needed. Before
        # that binding a pre-anchor row keyed to the controller's ref and this same filter handed it
        # the CONTROLLER's newest event: T-10246 (2026-07-09) borrowed the controller's unrelated
        # `land_completed` and read `needs-decision / proc gone but last event recent` over a live
        # worker. When the worker has not journaled yet (pre-anchor) `worker_events` is EMPTY and the
        # row falls back to its OWN task chain's `last_ts` with a null `last_event_type` — an honest
        # "no worker event yet", never a borrowed dispatcher event.
        worker_events = [e for e in allev if e.get("session_ref") == sref]
        last_ev = max(worker_events, key=lambda e: e.get("ts") or "") if worker_events else None
        last_event_ts = last_ev.get("ts") if last_ev else (per_task[newest_active]["last_ts"])
        last_event_type = last_ev.get("type") if last_ev else None
        # land-readiness: a closed-but-unlanded worktree is READY to land; a live claim on a working
        # task is CLAIM-LIVE (a land would race it); no live claim → none.
        if any(per_task[t]["cls"] in ("closed_pending_land", DISPATCH_CLASS_CLOSED_AWAITING_CONTROLLER_LAND)
               for t in wtids):
            land_readiness = "ready"
        elif any(t in live_claims for t in wtids):
            land_readiness = "claim-live"
        else:
            land_readiness = "none"
        # IN-FLIGHT filter: drop a fully-terminal, proc-gone, child-less worker (slot released) —
        # EXCEPT a recent unresolved self-halt (halted_tids), which is a needs-decision the controller
        # must see, not a released slot (T-10193).
        # T-10577 (X-0428): a STRANDED task keeps its worker in-flight too — a landed-but-unclosed
        # card is a mid-lifecycle strand the controller must see, not a released slot.
        # T-10771 (rule 2d): a RESOLVED recent halt keeps its worker in-flight too. This term is what
        # makes the resolved-halt reading a TRIGGER change and not a VIEW change — the row that is
        # visible today stays visible (it just stops reading `halted`/needs-decision), so the change
        # cannot silently drop a worker the controller can currently see.
        # T-12304: a controller-wait stop keeps its worker in-flight for the same reason — the
        # released slot must not drop before the controller has taken the step the pause names.
        if not (proc_alive or child or consumer_alive or nonterminal or halted_tids
                or resolved_halt_tids or stranded_tids or controller_wait_tids):
            continue
        # VERDICT — a NON-mutating classification (never a recommended act).
        dead_but_unlanded = any(_dispatch_dead_but_unlanded(per_task[t]["cls"]) for t in wtids)
        needs_claim_decision = any(per_task[t]["cls"] in ("closed_pending_land", "hang_suspect")
                                   for t in wtids) or dead_but_unlanded
        if stranded_tids and not (proc_alive or child or consumer_alive):
            # T-10577 (X-0428) — a task LANDED but its card is stranded mid-lifecycle (in-progress, no
            # audit-post/closure, not paused): the batch-end read must NOT report this worker's slot as
            # a finished batch. Report class=stranded + verdict=needs-decision, naming the card state
            # (status @ current_stage) straight off the cross-check so the controller routes it (drive
            # the task to closure, or park/wont-do it) WITHOUT re-grepping. Report-only, no mutating
            # act (SPEC-0133 rule 2). This branch precedes the halted one: a landed strand is a
            # distinct, more specific signal than a self-halt (which never landed).
            stid = stranded_tids[-1]   # newest by drain order (wtids is ts-ascending)
            st = per_task[stid]["strand"] or {}
            stage = st.get("current_stage") or "?"
            cls = "stranded"
            verdict = "needs-decision"
            verdict_basis = (f"{stid} LANDED but its card is stranded mid-lifecycle "
                             f"(status={st.get('status') or '?'} @ stage={stage}, no audit-post/closure) "
                             f"— proc gone; do NOT read as a finished batch. Drive it to closure "
                             f"(or park/wont-do); NOT a re-dispatch")
        elif halted_tids and not (proc_alive or child or consumer_alive):
            # A RECENT self-halt with no live proc/child — the dropped-worker case (T-10193). Report
            # class=halted + verdict=needs-decision, carrying the halt REASON straight from the
            # `bg_dispatch_halted` event so the controller routes it (re-dispatch after the blocker is
            # resolved) WITHOUT re-grepping. No `recommended_action` (SPEC-0133 rule 2 — the verb
            # reports THAT a decision is needed, never the mutating act).
            htid = halted_tids[-1]   # newest by drain order (wtids is ts-ascending)
            halt_ev = next((e for e in reversed(allev)
                            if e.get("type") == "bg_dispatch_halted" and _dispatch_task_of(e) == htid), None)
            hdata = halt_ev.get("data") if (halt_ev and isinstance(halt_ev.get("data"), dict)) else {}
            reason = str(hdata.get("reason") or per_task[htid]["detail"] or "halt")
            # T-11344 — the marker's OWN clock, already in hand on this branch (no second scan). The
            # evidence line prints `last={ts}({type})` — the chain's newest event of ANY type — which
            # on a halted row can be hours newer than the marker that produced `class=halted`. Carry
            # the marker ts so the row shows WHICH clock is which; the label stays neutral (`marked=`),
            # a bare timestamp with no freshness judgement (a marker is actionable until cleared).
            marker_ts = (halt_ev.get("ts") or None) if halt_ev else None
            # T-11618 — the DERIVED routing cause, rendered BESIDE the worker's free text. Until now
            # this branch printed the free text alone, which made it the whole of what a controller
            # read to route the block — and free text is exactly what mislabelled six halts in ~24h.
            # The free text is NOT dropped: it keeps its evidence value (it is often the only place
            # the worker says WHAT it tried), it loses only its authority as the routing key. So the
            # basis line now carries both, and the reader can see them disagree.
            hcause = _derived_halt_cause(allev, htid, _dispatch_task_of=_dispatch_task_of)
            # The raw recorded class when it is OUTSIDE the measured vocabulary — named here rather
            # than swallowed, so `unmapped` reports a gap instead of hiding one (audit-pre, 2026-08-26).
            _habort = _last_land_abort(allev, htid)
            _hraw = str((_habort or {}).get("abort_class") or "").strip()
            causetxt = (f"cause={hcause}"
                        + (f" [recorded abort_class={_hraw}]" if hcause == _CAUSE_UNMAPPED and _hraw else ""))
            cls = "halted"
            verdict = "needs-decision"
            # T-10291 (X-0271) — a PRE-CLAIM REFUSAL is a halt the controller must route DIFFERENTLY
            # from a dropped worker. Before `task refuse` existed, a worker that came up, analyzed a
            # ready task and correctly refused it had no way to say so: it exited, and the task chain
            # (launch only, no claim, past grace) read `launch-stall` — «never came up, re-dispatch».
            # Re-dispatching a refusal reproduces it, so the controller looped (the trend-finder
            # incident, 2026-07-09). The refusal now arrives as bg_dispatch_halted(kind=refused) →
            # detail `refused(pre-claim)`, so say plainly that the worker WORKED and the remedy is the
            # blocker, not a respawn. Same class/verdict (no new token — SPEC-0133 rule 2a vocabulary
            # unchanged); only the basis line, which is where a controller reads the routing.
            # T-11926 (rule 2f) — the PREMATURE-EXIT arm, checked FIRST because it is the one halt
            # the worker did NOT author: rendering it "worker self-halted" would credit a dead worker
            # with a deliberate stop it never made, which is the exact misreading the card exists to
            # end. The basis names the kind, the confirmed-death basis, and the log tail's FINAL
            # non-empty line — so the cause is readable off the verdict without opening the log by
            # hand (AC2/AC3). Same class/verdict as its siblings — no new token (rule 2a vocabulary
            # unchanged); only the basis line, which is where a controller reads the routing.
            if per_task[htid]["detail"] == _HALT_DETAIL_PREMATURE_EXIT:
                _tail = str(hdata.get("log_tail") or "")
                _last = next((ln for ln in reversed(_tail.splitlines()) if ln.strip()), "")
                verdict_basis = (
                    f"worker for {htid} DIED without authoring any terminal (premature_exit) — it "
                    f"neither landed nor halted, so any work it did is UN-LANDED. Confirmed by: "
                    f"{hdata.get('confirmed_death_basis') or 'proc gone'}; exit code unavailable "
                    f"(worker reparented to init, T-11906). Last dispatch-log line: "
                    f"{_last or '(log empty/unreadable)'} — full tail on the halt row "
                    f"({hdata.get('log') or 'no log path recorded'}). Inspect the worktree before "
                    f"re-dispatching: a re-dispatch does NOT recover un-landed work")
            elif per_task[htid]["detail"] == _HALT_DETAIL_REFUSED:
                verdict_basis = (f"worker analyzed {htid} and REFUSED it pre-claim ({reason}) — a governed "
                                 f"refusal, NOT a dead bootstrap: the task is still ready and un-claimed. "
                                 f"Re-dispatching as-is reproduces the refusal; resolve the named blocker "
                                 f"(or take the owner decision) first")
            else:
                verdict_basis = (f"worker self-halted on {htid} [{causetxt}] (worker detail: {reason}) — "
                                 f"proc gone, no worktree/claim; controller re-dispatch decision needed "
                                 f"once the blocker is resolved")
        elif controller_wait_tids and not (proc_alive or child or consumer_alive):
            # T-12304 — a CLEAN, CUED STOP. The worker's brief ended in «STOP and report»; it exited
            # and recorded the stop with `task pause --reason controller-wait`, which wrote the resume
            # contract. Without this branch the row fell through to the settling/`working` reading and
            # the watcher woke with a needs-decision it could not NAME. Report class=paused +
            # verdict=needs-decision, naming the pause reason and the recorded `next_action` — the
            # CONTROLLER's own pending step — so the routing is readable off the verdict without a
            # journal grep. Report-only, no `recommended_action` (SPEC-0133 rule 2: the verb reports
            # THAT a decision is needed, never the mutating act). Placed after the stranded/halted
            # branches (both are more specific block/strand signals) and before the alive branch,
            # which its own no-live-proc guard already excludes.
            cwtid = controller_wait_tids[-1]   # newest by drain order (wtids is ts-ascending)
            cwev = _controller_wait_pause([e for e in allev if _dispatch_task_of(e) == cwtid])
            cwdata = cwev.get("data") if (cwev and isinstance(cwev.get("data"), dict)) else {}
            cwnext = str(cwdata.get("next_action") or "").strip()
            cls = "paused"
            verdict = "needs-decision"
            verdict_basis = (
                f"worker for {cwtid} STOPPED CLEANLY as cued and recorded it "
                f"(task pause --reason={CONTROLLER_WAIT_PAUSE_REASON} @ stage="
                f"{cwdata.get('stage') or '?'}) — proc gone, nothing settling and nothing blocked. "
                f"The pending step is the CONTROLLER's: "
                f"{cwnext or '(none recorded on the pause row)'}. Relaunch is `dispatch --resume "
                f"{cwtid}` (no --force needed)")
        elif proc_alive or child or consumer_promotes_alive:
            verdict = "alive"
            if child:
                verdict_basis = f"active {child} child proc for {newest_active} — busy, not hung"
            elif len(nonterminal) < len(wtids):
                verdict_basis = "worker proc alive with a completed task — IDLE between lands (warm)"
            elif not proc_alive and consumer_alive:
                # T-10473 — the kernel journal is silent but a FRESH consumer-journal line under this
                # worker's ref proves it is alive on a `-C` consumer locus (not the false CONFIRMED-DEAD
                # of 2026-07-12). Name the locus so the controller does not re-dispatch a live worker.
                verdict_basis = ("worker journal-silent on the kernel locus but a fresh consumer-journal "
                                 "line under its ref proves it ALIVE (consumer-locus work) — NOT a re-dispatch")
            else:
                verdict_basis = "worker proc alive"
        elif needs_claim_decision:
            verdict = "needs-decision"
            verdict_basis = (f"proc gone, no live child; unlanded/ambiguous claim ({cls}) — "
                             f"controller land/adopt decision needed")
        else:
            # proc gone, no live child, no claim. A RECENT last event = just went quiet → let the
            # ≥2-poll settle window decide (needs-decision); a STALE journal = confirmed dead.
            recent = False
            ts = _parse_iso_ts(last_event_ts) if last_event_ts else None
            if ts is not None:
                recent = (now - ts).total_seconds() < DISPATCH_STALE_NORMAL_SEC
            if recent:
                verdict = "needs-decision"
                verdict_basis = "proc gone but last event recent — settling; re-poll before deciding"
            else:
                verdict = "dead"
                verdict_basis = "proc gone, no live child, stale journal, no live claim — confirmed gone"
        # T-11925 (AC3) — when a fresh consumer-journal line was present but did NOT promote the row to
        # alive, SAY SO in the basis and name the reading that outranked it. A controller reading a
        # non-alive verdict on a worker that has a fresh consumer line would otherwise have no way to
        # tell this apart from «no consumer signal at all», and the whole point of the demotion is that
        # the controller can now act on the death instead of standing down.
        if consumer_alive and proc_reading_negative and verdict != "alive":
            verdict_basis += (f" — NOTE: a fresh consumer-journal line under this ref was present but did "
                              f"NOT promote this row to alive: the direct process reading WAS taken and is "
                              f"NEGATIVE (exhaustive /proc scan found no live `--session-id {sref}` process). "
                              f"A journal line records a PAST act, not liveness, so it does not override a "
                              f"reading of NOW (T-11925)")

        # T-10712 (X-0557) — render the paused-card detail (report-only, OPTIONAL key). Built from the
        # NEWEST paused tid in drain order, mirroring the halted/stranded branches' newest-first pick.
        # It carries NO `recommended_action` (SPEC-0133 rule 2 — report the state + that a decision is
        # pending, never the mutating act), and the wording mirrors the DISPATCH_CLASS_VOCAB TERMINAL
        # gloss (one wording, two surfaces). Emitted ONLY on a POSITIVE paused read — absent otherwise,
        # so the field-contract stays byte-identical for every non-paused row and the acceptance
        # differential can fail if the detail were ever emitted unconditionally.
        pause_detail = None
        if paused_tids:
            ptid = paused_tids[-1]
            pst = per_task[ptid]["strand"] or {}
            pause_detail = (f"{ptid} card is PAUSED (reason={pst.get('paused_reason') or '?'}, "
                            f"status={pst.get('status') or '?'} @ stage={pst.get('current_stage') or '?'}) "
                            f"— the DISPATCH is over, the TASK is not: it is waiting on a pending "
                            f"decision, NOT a re-dispatch")
        # T-10771 (rule 2d) — render the RESOLVED-HALT detail. Exact sibling of `pause_detail` above:
        # report-only, an OPTIONAL key emitted ONLY on a POSITIVE resolved read (so every other row's
        # field contract stays byte-identical and the acceptance differential can fail if it were ever
        # emitted unconditionally), carrying NO `recommended_action`. This is what stops the reader
        # re-deriving the timeline by hand — the failure T-10729 cost two sessions.
        halt_detail = None
        if resolved_halt_tids:
            rtid = resolved_halt_tids[-1]   # newest by drain order (wtids is ts-ascending)
            hr = halt_res.get(rtid) or {}   # computed once in the split above — no second scan
            # T-12273 — ONE arm-exhaustive narrator, shared with the re-dispatch brief. The former
            # inline chain here had no branch for arm (iv) and fell through to the consult wording.
            how = _halt_resolution_how(hr)
            halt_detail = (f"{rtid} self-halted @ {hr.get('halt_ts')} "
                           f"({hr.get('reason') or 'halt'}) but the journal records that halt as "
                           f"RESOLVED: {how} — NOT an open owner-gated block, and NOT a decision "
                           f"waiting on you")
        records.append({
            "session_ref": sref,
            "task_ids": wtids,
            "class": cls,
            "evidence": {
                "last_event_ts": last_event_ts,
                "last_event_type": last_event_type,
                "proc_alive": proc_alive,
                "child_proc": child,
                "land_readiness": land_readiness,
            },
            "verdict": verdict,
            "verdict_basis": verdict_basis,
        })
        if marker_ts:   # T-11344 — OPTIONAL key, emitted only on a positive marker read, so every
            # other row's evidence field-contract stays byte-identical (the T-10712/T-10771 pattern).
            records[-1]["evidence"]["marker_ts"] = marker_ts
        if pause_detail:
            records[-1]["pause_detail"] = pause_detail
        if halt_detail:   # T-10771 — report-only, printed only on a positive RESOLVED-halt read
            records[-1]["halt_detail"] = halt_detail
    records.sort(key=lambda r: r["session_ref"])
    if getattr(args, "json", False):
        for rec in records:
            print(json.dumps(rec, ensure_ascii=False))
        return
    if not records:
        print("(no in-flight workers)")
        return
    for rec in records:
        ev = rec["evidence"]
        print(f"{rec['session_ref']:<28} {rec['verdict']:<15} class={rec['class']} "
              f"tasks={','.join(rec['task_ids'])}")
        mtxt = f"  marked={ev['marker_ts']}" if ev.get("marker_ts") else ""   # T-11344
        print(f"    evidence: last={ev['last_event_ts'] or '-'}({ev['last_event_type'] or '-'}){mtxt}  "
              f"proc_alive={str(ev['proc_alive']).lower()}  child={ev['child_proc'] or '-'}  "
              f"land={ev['land_readiness']}")
        print(f"    basis: {rec['verdict_basis']}")
        if rec.get("pause_detail"):   # T-10712 — report-only, printed only on a positive paused read
            print(f"    pause: {rec['pause_detail']}")
        if rec.get("halt_detail"):    # T-10771 — report-only, printed only on a positive RESOLVED halt
            print(f"    halt:  {rec['halt_detail']}")

def _dispatch_readiness_report(args, *, DISPATCH_WAVE_WINDOW_SEC, _cpu_count, _load_avg, _dispatch_status_events, _live_land_frontier, _live_claimed_task_ids, _land_proc_alive, _session_proc_alive, _work_land_proc_alive=_work_land_proc_alive):
    """PURE fleet-width computation for `--dispatch-readiness` (SPEC-0133) — extracted (T-10178) so the
    Axis-B `--dispatch-plan` advisor CONSUMES the SAME numbers (one computation, two readers; CHARTER
    §P1 F1). Reads CURRENT host/proc/journal state only; emits/mutates nothing. Returns
    (report, num_live_controllers) — report carries the 5 canonical SPEC-0133 fields byte-unchanged."""
    now = _dt.datetime.now(_dt.timezone.utc)
    since, until = getattr(args, "since", None), getattr(args, "until", None)
    if not since and not until:
        since = (now - _dt.timedelta(seconds=DISPATCH_WAVE_WINDOW_SEC)).strftime("%Y-%m-%dT%H:%M:%SZ")
    # --- headroom: current host CPU pressure (os reads, injected for hermetic tests) ------------
    nproc = _cpu_count() or 1
    try:
        load1, load5, load15 = _load_avg()
    except Exception:
        load1, load5, load15 = 0.0, 0.0, 0.0   # fail-open toward "idle": an unreadable loadavg
                                                # never inflates pressure (advisory read, never a gate)
    free_slots = max(0, nproc - 2)              # reserve controller + OS ('cores - 2' envelope shape)
    load_slots = max(0, int(nproc - load1))     # idle-core estimate from the 1-min load
    # --- live_worker_count: ALL sessions' live workers (task/ + work/), the authoritative source ---
    frontier = _live_land_frontier() or {}
    live_worker_count = frontier.get("total") or 0
    work_slugs = frontier.get("work") or []
    # --- sole_controller: ≤1 distinct LIVE controller session_ref dispatched in the window ---------
    allev = _dispatch_status_events(task_id=None, since=since, until=until)
    controller_refs = set()
    for e in allev:
        if e.get("type") == "bg_dispatch_launched":
            ref = e.get("session_ref")   # the launcher/controller's ref (agent=main)
            if ref:
                controller_refs.add(ref)
    live_controllers = {r for r in controller_refs if _session_proc_alive(r)}
    num_live_controllers = len(live_controllers)
    sole_controller = num_live_controllers <= 1
    # --- recommended_wave_ceiling: advisory only (never enforced) -----------------------------------
    base = min(free_slots, load_slots)
    ceiling = max(0, base - live_worker_count)
    if not sole_controller and num_live_controllers > 1:
        ceiling = ceiling // num_live_controllers   # fair-share the box across live controllers
    # NOTE (T-10386): recommended_wave_ceiling is DELIBERATELY NOT clamped to MAX_FLEET_WIDTH. SPEC-0133
    # §6 is a normative anti-orchestrator fence — the advisor MUST NOT clamp/cap this number («never a
    # coded cap»); it stays the pure headroom-minus-workers math the controller MAY ignore. The owner's
    # per-server MAX_FLEET_WIDTH is SUGGESTED (echoed as an advisory bound by the printers), never coded
    # into this value — the controller judges its wave against BOTH numbers.
    # --- in_flight_land: any live land on the box (task/ self-land OR cross-session work/ land) ------
    # BOTH legs are PROBES (T-11137). The work/ leg used to be `work_lands > 0` — a COUNT of existing
    # work/<slug> worktrees, which live for hours — so the signal was pinned true whenever any filing
    # batch was open and every consumer loop gated on it degraded into a timer
    # (lessons/a-presence-count-is-not-a-liveness-probe.md). The frontier VIEW above is unchanged:
    # live_worker_count still counts worktrees on purpose (T-10010); only THIS consumer was wrong.
    in_flight_land = (any(_work_land_proc_alive(s) for s in work_slugs)
                      or any(_land_proc_alive(t) for t in _live_claimed_task_ids()))
    report = {
        "headroom": {
            "nproc": nproc,
            "loadavg1": round(load1, 2),
            "loadavg5": round(load5, 2),
            "loadavg15": round(load15, 2),
            "free_slots": free_slots,
        },
        "live_worker_count": live_worker_count,
        "recommended_wave_ceiling": ceiling,
        "sole_controller": sole_controller,
        "in_flight_land": in_flight_land,
    }
    return report, num_live_controllers


def cmd_journal_dispatch_readiness(args: argparse.Namespace, *, DISPATCH_WAVE_WINDOW_SEC, _cpu_count, _load_avg, _dispatch_status_events, _live_land_frontier, _live_claimed_task_ids, _land_proc_alive, _session_proc_alive, _parse_iso_ts, _work_land_proc_alive=_work_land_proc_alive) -> None:
    """`journal query --dispatch-readiness` — the read-only dispatch-readiness / WAVE-SIZING ADVISOR
    (SPEC-0133, CARD-2 of the mechanize-controller-worker-observability plan). A THIRD §6-safe sibling
    of `--dispatch-status` / `--fleet-verdict` on the SAME reader — NOT a new subsystem (CHARTER §P1 F1:
    the host/proc/journal reads are all existing blessed helpers).

    It answers ONE question a controller asks BEFORE a dispatch wave — «how loaded is the box and how
    big a wave is sane right now» — as a numbers report derived PURELY from CURRENT host + proc +
    journal state. It is an ADVISOR, NEVER a gate/cap/scheduler: it PRINTS numbers and performs NO
    admission control (SPEC-0133 rule-1 §6-compliance test — pure current-state read, does NONE of:
    remember / wait-sleep-loop / schedule / mutate / re-invoke-AI / kill-respawn-land-adopt /
    choose-queue-movement). The `recommended_wave_ceiling` is an ADVISORY integer the controller may
    ignore; the verb does not enforce, cap, or queue against it.

    Five fields:
      - headroom — {nproc, loadavg1/5/15, free_slots} from os.cpu_count()/os.getloadavg(); free_slots =
        max(0, nproc - 2) reserving a slot for the controller + the OS (the same 'cores - 2' shape the
        dispatch concurrency envelope uses).
      - live_worker_count — EVERY live worker across ALL sessions, from `_live_land_frontier()["total"]`
        (the cross-session task/ + work/ worktree count, T-10010) — the AUTHORITATIVE all-session
        enumeration (a task/-only count missed the 2026-07-02 concurrent-land thundering-herd; audit-pre
        finding: this helper IS the all-session source, not merely an in_flight_land input).
      - recommended_wave_ceiling — max(0, min(free_slots, load_slots) - live_worker_count), then shared
        across live controllers when NOT sole_controller. load_slots = max(0, floor(nproc - loadavg1)).
        ADVISORY only, and DELIBERATELY NOT clamped to MAX_FLEET_WIDTH (SPEC-0133 §6 — «never a coded
        cap»); the owner per-server MAX_FLEET_WIDTH is SUGGESTED alongside it by the printers (T-10386).
      - sole_controller — is this the only live controller dispatching against the box? True iff ≤1
        distinct live controller session_ref appears on `bg_dispatch_launched` events in the window.
      - in_flight_land — is a land running RIGHT NOW anywhere on the box? BOTH legs are PROCESS
        PROBES (T-11137): true iff any live-claimed task has a live `land` proc (_land_proc_alive,
        the E-0035 land-liveness probe) OR any live `work/<slug>` batch has a live `land` proc
        (_work_land_proc_alive, the cross-session sibling covering the 2026-07-02 miss-class).
        The work/ leg was a worktree-PRESENCE count until T-11137, which pinned this signal true for
        the hours a filing batch stays open; the frontier view it read is correct and unchanged
        (T-10010) — only this consumer misread it. Both probes fail CLOSED (never assert liveness on
        a scan error), the conservative (throttle-toward) direction for an advisor."""
    # T-10178 (SPEC-0136): the READ portion is now a pure helper `_dispatch_readiness_report` so the
    # Axis-B dispatch-plan advisor can CONSUME the same fleet-width numbers without a second reader path
    # (CHARTER §P1 F1 — one readiness computation, two readers). This command keeps the print.
    report, num_live_controllers = _dispatch_readiness_report(
        args, DISPATCH_WAVE_WINDOW_SEC=DISPATCH_WAVE_WINDOW_SEC, _cpu_count=_cpu_count,
        _load_avg=_load_avg, _dispatch_status_events=_dispatch_status_events,
        _live_land_frontier=_live_land_frontier, _live_claimed_task_ids=_live_claimed_task_ids,
        _land_proc_alive=_land_proc_alive, _work_land_proc_alive=_work_land_proc_alive,
        _session_proc_alive=_session_proc_alive)
    ceiling = report["recommended_wave_ceiling"]
    live_worker_count = report["live_worker_count"]
    in_flight_land = report["in_flight_land"]
    sole_controller = report["sole_controller"]
    if getattr(args, "json", False):
        print(json.dumps(report, ensure_ascii=False))
        return
    h = report["headroom"]
    print("dispatch-readiness (ADVISORY — read-only, no admission control):")
    print(f"  headroom: nproc={h['nproc']}  loadavg={h['loadavg1']}/{h['loadavg5']}/{h['loadavg15']}  "
          f"free_slots={h['free_slots']}")
    print(f"  live_worker_count (all sessions task/+work/): {live_worker_count}")
    print(f"  recommended_wave_ceiling: {ceiling}  (advisory — you may ignore it)")
    print(f"  server bounds (T-10386, SUGGESTED — never a coded cap): max_fleet_width={max_fleet_width()}  "
          f"watch_poll_interval={WATCH_POLL_INTERVAL_SECS}s  watch_max_runtime={WATCH_MAX_RUNTIME_SECS}s")
    print(f"  sole_controller: {str(sole_controller).lower()}  "
          f"({num_live_controllers} live controller(s) dispatching in window)")
    print(f"  in_flight_land: {str(in_flight_land).lower()}")


# ── dispatch-plan advisor (T-10178, SPEC-0136) — read-only Axis-B batch proposal + Handback ──────────
# The tasks-PER-worker (Axis-B) + queue-shaping layer ON TOP OF two shipped read-only advisors it
# CONSUMES, never rebuilds: `graph query --carve-out` (SPEC-0044 — eligibility/chains/waits/clash/
# in-flight) and `journal query --dispatch-readiness` (SPEC-0133 — fleet-width). PURE/stateless/read-
# only: emits nothing, mutates nothing, gates nothing (SPEC-0136 §6 fence). If it ever held queue state
# / auto-picked / capped-as-enforcement → that is the forbidden orchestrator (CHARTER §6) — it does not.
_TIER_RANK = {"normal": 0, "critical": 1}   # higher rank = higher effort_tier (SPEC-0072 routing axis)


def _split_task_ids(raw: str) -> list:
    """Parse a `--tasks` value: comma/space separated T-ids, order-preserving + de-duplicated."""
    out, seen = [], set()
    for tok in re.split(r"[,\s]+", (raw or "").strip()):
        if tok and tok not in seen:
            seen.add(tok)
            out.append(tok)
    return out


def _card_touch_tokens(card: dict, _is_governance_surface):
    """Split a card's `expected_touch` into (symbol-tokens, governance-surface paths, ordinary paths).
    A `path#symbol` entry is a symbol token (same-symbol overlap = the STRONGEST land-conflict). A path
    whose surface is governance (spec / handbook-seed / pinned-test — SPEC-0136 §2 blast-radius
    weighting, classified by the REUSED `_is_governance_surface`) is high-blast; every other path is
    ordinary (a path-only overlap is ambiguous → Handback, never an auto-chain)."""
    syms, gpaths, ppaths = set(), set(), set()
    for e in (card.get("expected_touch") or []):
        e = str(e)
        path = e.split("#", 1)[0]
        if "#" in e:
            syms.add(e)
        if _is_governance_surface(path):
            gpaths.add(path)
        else:
            ppaths.add(path)
    return syms, gpaths, ppaths


def _derive_card_touch(card):
    """LEG-2 (T-10389, SPEC-0136 §2 read-time derivation): DERIVE low-confidence path-shaped touch
    candidates from a card's title+scope when it carries NO stored expected_touch. STORED WINS — a
    card with a real forecast returns [] (never derive over fact). The result is LOW-CONFIDENCE +
    VOLATILE: it is used ONLY to PROPOSE a chain via the Handback (with a verify line) and is NEVER
    written to the card or anywhere else (the consult's P5 bound — no guessed touch stored as fact).
    Pure/read-only: f(card) -> sorted[str], no fs/journal/mutation.

    The path-token EXTRACTION itself is homed once in `textutil.derive_path_tokens` (T-10390 / P5) —
    the same extractor the leg-3 Stage-1 write-back scores this guess against; this fn adds only the
    card semantics (stored-wins + which fields feed the text)."""
    if card.get("expected_touch"):
        return []
    text = " ".join([str(card.get("title") or "")] + [str(s) for s in (card.get("scope") or [])])
    return textutil.derive_path_tokens(text)


def _dispatch_plan_proposal(scope_label, scope_ids, carve, cards, readiness, *,
                            _resolve_effort_routing, _resolve_warm_worker_cap, _is_governance_surface):
    """PURE core of the Axis-B advisor (SPEC-0136 buckets 1-4). f(scope, consumed carve-out, cards,
    consumed readiness) → a proposal dict {groups, excluded, handback, sizing}. Reads only the passed-in
    data; computes; returns. NO host/fs/journal access, NO mutation (the §6 read-only fence — the
    make-or-break purity guard, mirror of _carve_out_selection's VP4)."""
    # ---- consumed carve-out (SPEC-0044) — eligibility/chains/waits/clash, CONSUMED not rebuilt -------
    ready_chains = [list(c) for c in (carve.get("chains") or [])]
    ready_singletons = list(carve.get("singletons") or [])
    waits = carve.get("waits") or []
    clash_report = carve.get("clash_report") or []
    in_flight = set(carve.get("in_flight") or [])
    ready_ids = {t for ch in ready_chains for t in ch} | set(ready_singletons)

    # ---- bucket 1: eligibility WITHIN scope (consumed, never re-derived) -----------------------------
    excluded = []        # [{task, reason}] — surfaced, never silently dropped
    for t in sorted(scope_ids - ready_ids):
        card = cards.get(t) or {}
        if card.get("closed_into"):                                     # HARD-exclude: durable closure
            excluded.append({"task": t, "reason": f"duplicate — already closed_into {card['closed_into']}"})
        elif t in in_flight:
            excluded.append({"task": t, "reason": "already claimed (live worktree — in-flight frontier)"})
        elif any(w.get("task") == t for w in waits):
            w = next(w for w in waits if w.get("task") == t)
            excluded.append({"task": t, "reason": f"waiting: ordered after {','.join(w.get('wait_on') or [])} — release: {w.get('predicate')}"})
        elif any(t in (e.get("tasks") or []) for e in clash_report):
            excluded.append({"task": t, "reason": "spec-lineage CLASH (P7) — see Handback, order before dispatch"})
        elif not card:
            excluded.append({"task": t, "reason": "not in index / unknown id"})
        elif (card.get("status") or "") != "ready":
            excluded.append({"task": t, "reason": f"not ready (status={card.get('status') or '?'})"})
        else:
            excluded.append({"task": t, "reason": "requires: target not done (blocked in picker)"})

    # ---- bucket 2: grouping — requires-chains (from SPEC-0044) + Axis-B clash-packing ----------------
    # requires-chains restricted to scope (order preserved). A chain reduced to <2 in-scope members
    # rejoins the independent singleton pool.
    chain_groups, reduced = [], []
    for ch in ready_chains:
        in_scope = [t for t in ch if t in scope_ids]
        if len(in_scope) >= 2:
            chain_groups.append(in_scope)
        elif len(in_scope) == 1:
            reduced.append(in_scope[0])
    scoped_singletons = [t for t in ready_singletons if t in scope_ids] + reduced

    # land-conflict clash-chaining among independents: same-symbol OR shared governance-surface path →
    # CHAIN (strongest clash); a path-only (ordinary) overlap is ambiguous → Handback, NOT an auto-chain.
    forecasted = [t for t in scoped_singletons if (cards.get(t) or {}).get("expected_touch")]
    no_forecast = [t for t in scoped_singletons if not (cards.get(t) or {}).get("expected_touch")]
    tok = {t: _card_touch_tokens(cards.get(t) or {}, _is_governance_surface) for t in forecasted}
    parent = {t: t for t in forecasted}

    def _find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def _union(a, b):
        ra, rb = _find(a), _find(b)
        if ra != rb:
            parent[ra] = rb

    path_only_overlaps = []
    for i, a in enumerate(forecasted):
        sa, ga, pa = tok[a]
        for b in forecasted[i + 1:]:
            sb, gb, pb = tok[b]
            if (sa & sb) or (ga & gb):
                _union(a, b)                                            # clear overlap → land-conflict chain
            elif pa & pb:
                path_only_overlaps.append({"tasks": [a, b], "paths": sorted(pa & pb)})
    clash_chains, alone = {}, []
    for t in forecasted:
        clash_chains.setdefault(_find(t), []).append(t)
    clash_groups = [sorted(g) for g in clash_chains.values() if len(g) >= 2]
    alone = [g[0] for g in clash_chains.values() if len(g) == 1]

    # shadow-packing: pack the independent remainder (no clash) into warm groups, tier-homogeneous, so a
    # warm worker reuses its context across a few small tasks (≤ the per-model cap; when a requires-chain
    # exists, ALSO bounded by its length so the wave finishes together — critical-path-shadow packing).
    # With NO requires-chain there is no critical path to shadow, so the per-model cap alone bounds the
    # pack (else independents would never pack — audit-post F2). no_forecast tasks stay their own group
    # (conflict-detection blind → flagged, never blind-packed).
    longest_chain = max((len(c) for c in chain_groups), default=0)
    packs, singletons_out = [], []
    by_tier = {}
    for t in alone:
        by_tier.setdefault((cards.get(t) or {}).get("effort_tier") or "normal", []).append(t)
    for tier, ids in by_tier.items():
        model, _eff = _resolve_effort_routing(tier)
        cap = _resolve_warm_worker_cap(model) if model else 1
        bound = min(cap, longest_chain) if longest_chain else cap   # shadow the critical path only if one exists
        width = max(1, bound)
        ids = sorted(ids)
        if width <= 1:
            singletons_out.extend(ids)
            continue
        for i in range(0, len(ids), width):
            chunk = ids[i:i + width]
            (packs if len(chunk) >= 2 else singletons_out).extend([chunk] if len(chunk) >= 2 else chunk)
    singletons_out.extend(no_forecast)

    # ---- assemble warm groups (each = one warm worker; ordered chains keep their order) --------------
    groups = []

    def _group_meta(members, kind):
        tiers = sorted({(cards.get(m) or {}).get("effort_tier") or "normal" for m in members})
        top = max(tiers, key=lambda x: _TIER_RANK.get(x, 0))
        model, effort = _resolve_effort_routing(top)
        cap = _resolve_warm_worker_cap(model) if model else None
        return {"members": list(members), "kind": kind, "tiers": tiers, "tier": top,
                "model": model, "effort": effort, "cap": cap,
                "mixed_tier": len(tiers) > 1, "over_cap": bool(cap and len(members) > cap)}

    for ch in chain_groups:
        groups.append(_group_meta(ch, "requires-chain"))
    for cg in clash_groups:
        groups.append(_group_meta(cg, "land-conflict-chain"))
    for pk in packs:
        groups.append(_group_meta(pk, "shadow-pack"))
    for s in sorted(singletons_out):
        groups.append(_group_meta([s], "singleton"))

    # ---- bucket 3: sizing — fleet width (consumed from SPEC-0133) bounds the wave --------------------
    ceiling = readiness.get("recommended_wave_ceiling")
    sizing = {"recommended_wave_ceiling": ceiling,
              "proposed_warm_workers": len(groups),
              "exceeds_fleet_width": bool(ceiling is not None and len(groups) > ceiling)}

    # ---- bucket 4: Handback — the residual judgement the verb CANNOT decide (returns to AI/owner) ----
    handback = []
    # spec-lineage CLASH (P7): scope tasks named in a carve clash entry — order before dispatch.
    for e in clash_report:
        hit = [t for t in (e.get("tasks") or []) if t in scope_ids]
        if hit:
            handback.append({"kind": "clash-p7", "tasks": sorted(hit),
                             "note": f"order via requires:/supersedes: before parallel dispatch — {e.get('question')}"})
    # mixed-tier chain: chaining for land-safety would run the whole group at the higher tier (SPEC-0072
    # economy vs land-safety) — SURFACE, never a silent auto-override (SPEC-0136 §2 finding 2).
    for g in groups:
        if g["mixed_tier"] and g["kind"] in ("requires-chain", "land-conflict-chain"):
            handback.append({"kind": "mixed-tier-chain", "tasks": g["members"],
                             "note": f"chain spans tiers {g['tiers']}; chaining for land-safety runs the group at "
                                     f"'{g['tier']}' (model {g['model']}) — confirm, or split (a SPEC-0072 amend "
                                     "is a separate follow-up)"})
    # no-forecast blind spot: conflict-detection is blind on cards with empty expected_touch. LEG-2
    # (T-10389, SPEC-0136 §2): before flagging blind, DERIVE low-confidence touch candidates from the
    # card's title+scope (volatile, provenance-marked, NEVER written to the card — stored expected_touch
    # always wins so forecasted cards never derive). A derived overlap only PROPOSES a chain — it is
    # surfaced as a `derived-overlap` Handback with a verify line, never an auto-chain (unlike a STORED
    # same-symbol/governance overlap). A card with no derivable token stays truly BLIND.
    if no_forecast:
        derived = {t: _derive_card_touch(cards.get(t) or {}) for t in no_forecast}
        truly_blind = sorted(t for t in no_forecast if not derived[t])
        if truly_blind:
            handback.append({"kind": "no-forecast", "tasks": truly_blind,
                             "note": "no expected_touch and none derivable from title/scope — "
                                     "clash-detection BLIND; verify before parallelizing "
                                     "(graceful degradation, not a false all-clear)"})

        def _touch_paths(cid):
            """A card's touch PATHS for overlap: a forecasted card's STORED paths (symbol file-parts +
            governance + ordinary), else its DERIVED low-confidence paths (no_forecast cards only)."""
            c = cards.get(cid) or {}
            if c.get("expected_touch"):
                s, g, p = _card_touch_tokens(c, _is_governance_surface)
                return {x.split("#", 1)[0] for x in s} | g | p
            return set(derived.get(cid) or [])

        for t in sorted(t for t in no_forecast if derived[t]):
            dt = set(derived[t])
            for other in sorted(scope_ids - {t}):
                # pair-dedupe a derived<->derived overlap: emit only once (when t < other); a
                # derived-vs-STORED overlap is never in `derived`, so it always emits.
                if other in derived and other < t:
                    continue
                shared = dt & _touch_paths(other)
                if shared:
                    handback.append({"kind": "derived-overlap", "tasks": sorted([t, other]),
                                     "low_confidence": True, "derived_from": {t: sorted(dt)},
                                     "note": f"LOW-CONFIDENCE: {t} has no stored expected_touch; path(s) "
                                             f"{sorted(shared)} were DERIVED from its title/scope and overlap "
                                             f"{other} — verify the derivation, then chain or parallelize "
                                             "(derived data is volatile, never written to the card)"})
    # path-only overlaps: ambiguous — chain or parallelize is the controller's call.
    for ov in path_only_overlaps:
        handback.append({"kind": "path-only-overlap", "tasks": ov["tasks"],
                         "note": f"share path(s) {ov['paths']} (path-only, no shared symbol/governance surface) — "
                                 "chain or parallelize? your call"})
    # missing/ambiguous requires edge → §6(f) STOP (resolve / ask owner, never dispatch-by-default).
    known = set(cards)
    for t in sorted(scope_ids):
        for r in ((cards.get(t) or {}).get("requires") or []):
            if r not in known:
                handback.append({"kind": "missing-requires", "tasks": [t],
                                 "note": f"requires: names unknown id {r} — resolve / ask owner before dispatch (§6(f) STOP)"})
    # symbol-only possible-duplicate: two scope cards with IDENTICAL non-empty expected_touch — a
    # possible dup that carries NO durable closure evidence → controller judgement, never silently dropped.
    et = {t: tuple(sorted((cards.get(t) or {}).get("expected_touch") or [])) for t in scope_ids if (cards.get(t) or {}).get("expected_touch")}
    seen = {}
    for t, key in sorted(et.items()):
        if key in seen:
            handback.append({"kind": "possible-duplicate", "tasks": sorted([seen[key], t]),
                             "note": "identical expected_touch, no closed_into — possible duplicate, decide before dispatch"})
        else:
            seen[key] = t
    # /compact-risk-on-window: a packed/chained group whose estimated context approaches the window
    # (over the per-model cap, OR at-cap and heavy — a governance-surface touch counts heavier).
    for g in groups:
        if len(g["members"]) < 2:
            continue
        gov_heavy = any(_card_touch_tokens(cards.get(m) or {}, _is_governance_surface)[1] for m in g["members"])
        if g["over_cap"] or (g["cap"] and len(g["members"]) >= g["cap"] and gov_heavy):
            handback.append({"kind": "compact-risk", "tasks": g["members"],
                             "note": f"group of {len(g['members'])} on a '{g['tier']}' ({g['model']}) worker "
                                     f"(cap {g['cap']}){' + governance-surface touch' if gov_heavy else ''} may /compact — split or shrink"})
    # over-decomposition: the WHOLE scope is one serial requires-chain, all on the same governance
    # surface, and exceeds one worker's window → no parallelism gain (SPEC-0136 §4 backtest #6).
    if len(chain_groups) == 1 and not clash_groups and not packs and not singletons_out:
        only = chain_groups[0]
        govs = [_card_touch_tokens(cards.get(m) or {}, _is_governance_surface)[1] for m in only]
        one_surface = bool(govs and all(govs) and len(set().union(*govs)) == 1)
        g0 = groups[0]
        if one_surface and g0["over_cap"]:
            handback.append({"kind": "over-decomposition", "tasks": only,
                             "note": "all-serial + all-same-governance-surface + exceeds one worker's window — "
                                     "no parallelism gain, reconsider granularity"})

    # /compact-weight per eligible task (heuristic: expected_touch count; governance touch heavier).
    compact_weight = {}
    for g in groups:
        for m in g["members"]:
            syms, gpaths, ppaths = _card_touch_tokens(cards.get(m) or {}, _is_governance_surface)
            compact_weight[m] = {"paths": len(syms | gpaths | ppaths), "governance": len(gpaths)}

    return {"scope": scope_label, "groups": groups, "excluded": excluded,
            "sizing": sizing, "handback": handback, "compact_weight": compact_weight}


def cmd_journal_dispatch_plan(args, *, _die, _load_dispatch_plan_substrate, _resolve_effort_routing, _resolve_warm_worker_cap, _is_governance_surface) -> None:
    """`journal query --dispatch-plan --plan <slug> | --tasks T-…,… | --whole-ready-queue` — the read-
    only Axis-B dispatch-planning advisor (SPEC-0136). Proposes WITHIN the owner-authorized batch which
    ready cards pack into which warm workers, in what order, how wide — and hands back the judgement it
    cannot make. CONSUMES `graph query --carve-out` (SPEC-0044) + `journal query --dispatch-readiness`
    (SPEC-0133) + the T-10177 per-model warm cap; it does NOT re-derive eligibility. PURE/stateless/
    read-only — emits nothing, mutates nothing, gates nothing (SPEC-0136 §6). Honors --json."""
    # ---- bucket 0: scope gate runs FIRST (the §6 batch-bounded fence made concrete). A bare unscoped
    #      call REFUSES — never auto-propose the whole ready queue without an explicit owner cue. ------
    plan_slug = getattr(args, "plan", None)
    tasks_arg = getattr(args, "tasks", None)
    whole = getattr(args, "whole_ready_queue", False)
    if sum([bool(plan_slug), bool(tasks_arg), bool(whole)]) == 0:
        _die("journal query --dispatch-plan requires a scope: --plan <slug> | --tasks T-…,… | "
             "--whole-ready-queue. A bare unscoped call REFUSES (SPEC-0136 §0: the batch-bounded fence — "
             "the advisor proposes WITHIN an owner-authorized batch, never auto-decides the whole ready "
             "queue; --whole-ready-queue is the explicit owner cue).")
    if sum([bool(plan_slug), bool(tasks_arg), bool(whole)]) > 1:
        _die("--plan / --tasks / --whole-ready-queue are mutually exclusive — choose ONE scope (SPEC-0136 §0).")

    # substrate reads (read-only): the consumed carve-out + readiness + the task cards. Done AFTER the
    # gate so a refused call touches nothing.
    sub = _load_dispatch_plan_substrate()
    carve, cards, readiness = sub["carve"], sub["cards"], sub["readiness"]

    if plan_slug:
        scope_ids = {tid for tid, c in cards.items() if c.get("decomposed_from") == plan_slug}
        scope_label = f"plan {plan_slug}"
    elif tasks_arg:
        scope_ids = set(_split_task_ids(tasks_arg))
        scope_label = f"tasks {','.join(sorted(scope_ids))}"
    else:
        ready_ids = {t for ch in (carve.get("chains") or []) for t in ch} | set(carve.get("singletons") or [])
        wait_ids = {w.get("task") for w in (carve.get("waits") or [])}
        clash_ids = {t for e in (carve.get("clash_report") or []) for t in (e.get("tasks") or [])}
        scope_ids = ready_ids | wait_ids | clash_ids
        scope_label = "whole ready queue (explicit owner cue)"

    proposal = _dispatch_plan_proposal(
        scope_label, scope_ids, carve, cards, readiness,
        _resolve_effort_routing=_resolve_effort_routing,
        _resolve_warm_worker_cap=_resolve_warm_worker_cap,
        _is_governance_surface=_is_governance_surface)

    if getattr(args, "json", False):
        print(json.dumps(proposal, ensure_ascii=False))
        return

    print(f"dispatch-plan (ADVISORY — read-only, proposes within the batch; you authorize the wave):")
    print(f"  scope: {proposal['scope']}  ({len(scope_ids)} card(s) in scope)")
    s = proposal["sizing"]
    fw = "n/a" if s["recommended_wave_ceiling"] is None else s["recommended_wave_ceiling"]
    warn = "  ⚠ exceeds fleet width — stagger" if s["exceeds_fleet_width"] else ""
    print(f"  fleet: recommended_wave_ceiling={fw}  proposed_warm_workers={s['proposed_warm_workers']}{warn}")
    if not proposal["groups"]:
        print("  (no eligible ready cards in scope — nothing to propose)")
    for i, g in enumerate(proposal["groups"], 1):
        order = " → ".join(g["members"]) if g["kind"] in ("requires-chain", "land-conflict-chain") else ", ".join(g["members"])
        preview = f"({g['model']}, {g['effort']})" if g["model"] else "(model unresolved)"
        flags = []
        if g["mixed_tier"]:
            flags.append("mixed-tier")
        if g["over_cap"]:
            flags.append(f"over-cap>{g['cap']}")
        fl = f"  [{', '.join(flags)}]" if flags else ""
        print(f"  W{i} [{g['kind']}] {preview}: {order}{fl}")
    if proposal["excluded"]:
        print("  excluded (in scope, NOT proposed — surfaced, never silently dropped):")
        for e in proposal["excluded"]:
            print(f"    - {e['task']}: {e['reason']}")
    cw = proposal["compact_weight"]
    if cw:
        heavy = sorted((m for m in cw), key=lambda m: (-cw[m]["paths"], m))[:5]
        wt = "  ".join(f"{m}={cw[m]['paths']}p" + (f"/{cw[m]['governance']}gov" if cw[m]['governance'] else "") for m in heavy)
        print(f"  /compact-weight (paths; gov=governance-surface, heavier): {wt}")
    print("  next: (Handback — the judgement the advisor CANNOT make; decide before you dispatch)")
    if not proposal["handback"]:
        print("    - (none — no residual judgement flags for this scope)")
    for hb in proposal["handback"]:
        print(f"    - [{hb['kind']}] {', '.join(hb['tasks'])}: {hb['note']}")


def _dispatch_unlanded_loci(chain) -> list:
    """The worktree paths whose UN-LANDED journals supplied rows in this task's chain (T-11352) —
    sorted, de-duplicated, `[]` when every row was corroborated on main.

    It answers the one question a controller cannot answer from `main`: this verdict rests on
    evidence `main`'s journal does not have, so WHERE is that evidence? Naming the worktree is the
    difference between a reading the controller can check and one it must take on trust — the
    X-1024 controller was handed a confident verdict plus a destructive recovery and no locus at
    all. PURE (no I/O): the provenance was stamped by the read that produced `chain`."""
    return sorted({e.get(DISPATCH_LOCUS_KEY) for e in (chain or [])
                   if isinstance(e, dict) and e.get(DISPATCH_LOCUS_KEY)})


def _requested_task_ids(args: argparse.Namespace) -> list:
    """The `--task` ids this `journal query` invocation ASKED FOR, in the order asked, de-duplicated.

    T-11743. The flag is `action="append"` on the CLI, so a real invocation delivers a LIST — but
    every in-process caller (9 test files, `bin/lib/*` namespaces built by hand) passes a bare
    STRING, and both must keep working. So the normalization is str-tolerant by construction: a
    `str` is the one-element request it has always been, a list is itself, `None` is the unscoped
    read. This is the ONE place the shape is decided; both consumers below read it, so the two
    cannot drift into disagreeing about what "was asked for" means."""
    raw = getattr(args, "task", None)
    if raw is None:
        return []
    ids = [raw] if isinstance(raw, str) else list(raw)
    seen, out = set(), []
    for tid in ids:
        if tid and tid not in seen:
            seen.add(tid)
            out.append(tid)
    return out


def cmd_journal_dispatch_status(args: argparse.Namespace, *, DISPATCH_BOUNDARY_TYPES, DISPATCH_WAVE_WINDOW_SEC, _classify_dispatch, _dispatch_cause_tag, _dispatch_dead_but_unlanded, _dispatch_identity, _dispatch_quiescent, _dispatch_recovery_hint, _dispatch_status_events, _dispatch_task_of, _land_abort_suffix, _last_land_abort, _last_land_ok, _live_land_frontier=None, _dispatch_events_tail_first_multi=None) -> None:
    """`journal query --dispatch-status [--task T-XXXX ...]` — PURE READ-ONLY (no emit). With --task:
    classify EACH requested dispatch — the flag is REPEATABLE and every id asked for is reported, in
    the order asked; an id with no dispatch rows is NAMED as unanswerable (`no_dispatch` /
    "no dispatch events match …") rather than omitted, so a fleet read can never silently cover
    fewer ids than were requested (T-11743: last-occurrence-wins made a three-worker read answer for
    one, and the natural next move on that reading is a re-dispatch onto live worktrees, T-0351).
    Without --task: the wave view — seed the task set from ANY dispatch-boundary
    event in the window (top-level task_id OR data.task), then classify each. --since/--until bound
    the wave (F1 absorption); the no-`--task` view defaults to DISPATCH_WAVE_WINDOW_SEC so older
    waves do not bleed in. --json emits one object per task. Each row carries a derived `quiescent`
    field (T-0583, _dispatch_quiescent) — the journal-quiescence predicate the §Abnormal
    premature-exit / respawn-adopt PROCEDURE keys off, NEVER the launched pid."""
    now = _dt.datetime.now(_dt.timezone.utc)
    # T-11743 — the REQUESTED SET, in the order asked. This branch used to read one scalar id, so a
    # repeated `--task` reported only the last occurrence: a fleet read that silently covered fewer
    # ids than were asked for. The per-id work below is the SAME chain it always was; what changed is
    # that it runs once per requested id and that an id it cannot answer for is NAMED, not omitted.
    requested = _requested_task_ids(args)
    since, until = getattr(args, "since", None), getattr(args, "until", None)
    # Per-id maps, so each row resolves its render clocks + land/cause/batch reads against ITS OWN
    # chain and ITS OWN unscoped stream. A single shared `all_events` would have been wrong the
    # moment a second id joined the read.
    rows, chain_of, allev_of, missing = [], {}, {}, []
    # T-10397 — this path used to pay TWO full 90MB scans per id (the scoped chain + the unscoped stream
    # below): 7.2s, of which CLI boot is 0.17s. ONE tail-first read serves BOTH — a launch found in the
    # window carries its whole newest-launch epoch (sound); a window with NO launch is re-decided on the
    # FULL journal (never a 'no launch' from a bounded read).
    # T-11896 — and that read is now taken ONCE FOR THE REQUEST, not once per requested id. The
    # empty-window decision is a property of the WINDOW, not of an id, so hoisting it out of the loop is
    # what stops N ids from paying N full passes over the same bytes (measured: 26.5s for one id, 69.7s
    # for three on an 84MB journal). The fail-safe is unweakened — a single id's empty window still
    # escalates, and now escalates the WHOLE request, which is strictly more conservative. Engaged only
    # when the caller passes no explicit --since/--until: an operator-bounded query keeps its own window
    # verbatim (and that arm keeps its per-id scoped read below).
    tailed = not since and not until and _dispatch_events_tail_first_multi is not None
    if tailed:
        chains, shared_allev, _launch_ts_of = _dispatch_events_tail_first_multi(
            task_ids=requested, with_unscoped=True)
    for one in requested:
        if tailed:
            # already in hand — the one request-scoped read above, partitioned by the SAME
            # `_dispatch_task_of` predicate a scoped read applies, so this IS `one`'s scoped chain.
            evs, _allev = chains.get(one, []), shared_allev
        else:
            # inloop-journal-read: the loop iterates the caller's OWN requested --task ids (a
            # one-shot, operator-sized outer iterable, T-11743) and this read is SCOPED to `one`,
            # so it cannot be hoisted without answering for a different id than was asked for. It
            # is also the non-default arm — reached only when the caller passed an explicit
            # --since/--until, which is what disables the tail-first read above.
            evs = _dispatch_status_events(task_id=one, since=since, until=until)
        if not evs:
            # an absent/typo --task (zero matching dispatch events) is NO-MATCH, NOT a fabricated
            # silent_stop (audit-post F1): never classify an empty chain as a dispatch.
            # T-11743 — RECORDED, never dropped. The id is rendered below (json: the same
            # `no_dispatch` object as ever; human: the same "(no dispatch events match …)" wording),
            # so an id the reader cannot answer for and a healthy-but-unread one never look alike.
            missing.append(one)
            continue
        # ADVISORY identity check (T-0559): the worker's session_started carries NO task_id, so read
        # it UNSCOPED; the task-scoped bg_dispatch_launched in `evs` carries expected+controller.
        launched = next((e for e in reversed(evs) if e.get("type") == "bg_dispatch_launched"), None)
        # T-10397 — the UNSCOPED stream is the SAME read that produced `evs` above (one journal pass,
        # two views), so the second full scan is GONE. Its three consumers all stay exact under that
        # read's window, because the window POSITIVELY contained the newest launch (else the read was
        # full anyway):
        #   _dispatch_identity — matches `data.expected`, a uuid MINTED AT LAUNCH, so every row that can
        #     match it postdates the launch (the COLLAPSED branch is explicitly `ts >= launch_ts`).
        #   _last_land_ok      — explicitly re-claim-gated (T-10042): an ok land BELOW the newest launch
        #     is already discarded as a stale closure signal, so excluding it changes nothing.
        #   _last_land_abort   — the one epoch-AGNOSTIC consumer (last-outcome-wins). An abort older than
        #     the window necessarily predates this launch, i.e. belongs to a PRIOR dispatch epoch —
        #     exactly the stale-shadowing the T-10095 newest-launch segmentation already discards on the
        #     bg-axis (and the window carries T-10387's 24h disorder margin on top).
        # inloop-journal-read: same bound as above (T-11743) — one pass per REQUESTED id, and on
        # the DEFAULT path this is not a read at all (`_allev` is the tail-first read's second view,
        # already in hand). The unscoped fallback is reached only under an explicit caller window.
        started = _allev if tailed else _dispatch_status_events(task_id=None, since=None, until=None)
        all_events = started   # T-9240 (AC2): land_completed source for the recovery abort-suffix
        # T-9749: compute identity FIRST, then pass it into _classify_dispatch (the launch-stall
        # branch reuses it — 'not-yet-started' means the worker journaled no session_started).
        identity = _dispatch_identity(launched, started, now)
        # T-9766: the authoritative land_completed:ok signal for this branch (from the unscoped
        # stream — branch-carried, so absent from the scoped `evs`); reconciled ahead of the bg-axis.
        land_ok = _last_land_ok(all_events, one)
        _c, _d, _l, _s = _classify_dispatch(evs, one, now, identity=identity, land_ok=land_ok)
        _d = _owner_gated_detail(_d, all_events, one, _dispatch_task_of=_dispatch_task_of)
        rows.append((one, _c, _d, _l, _s, identity))
        # T-11344 — keep each row's OWN task chain (the exact list classify read), so the two
        # render clocks below resolve against it rather than against a re-derived stream. It
        # matters on the --task path: `evs` may carry live-worktree-union rows (T-11090) that the
        # unscoped `all_events` does not, and a re-filter there would silently lose them.
        chain_of[one] = evs
        allev_of[one] = all_events   # T-11743 — this id's OWN unscoped stream (see the map note)
    # T-11743 — a SINGLE requested id that has no dispatch rows keeps its pre-existing output
    # verbatim (and its pre-frontier early return). The multi-id rendering below is strictly
    # additive: it exists for the case that used to produce a partial answer, and changes nothing
    # about the shape a one-id caller has always received.
    if len(requested) == 1 and missing:
        one = missing[0]
        if getattr(args, "json", False):
            print(json.dumps({"task_id": one, "class": "no_dispatch", "detail": "no-matching-events",
                              "last_ts": None, "session_ref": None, "identity": None,
                              # T-11344 — the same two clock keys as a real row, both null: an
                              # empty chain has neither a last event nor a marker.
                              "last_type": None, "marker_ts": None,
                              "quiescent": None, "recovery": None,
                              "dead_but_unlanded": None, "cause_tag": None}, ensure_ascii=False))
        else:
            print(f"(no dispatch events match {one})")
        return
    if not requested:
        # wave view: default-bound the window so older waves do not bleed in (kill (a) at seed layer)
        if not since and not until:
            since = (now - _dt.timedelta(seconds=DISPATCH_WAVE_WINDOW_SEC)).strftime("%Y-%m-%dT%H:%M:%SZ")
        allev = _dispatch_status_events(task_id=None, since=since, until=until)
        all_events = allev   # T-9240 (AC2): land_completed source for the recovery abort-suffix
        # SEED the task set from boundary events ONLY (startup is one seed, not the sole enumerator)
        tids = []
        for e in allev:
            if e.get("type") in DISPATCH_BOUNDARY_TYPES:
                tid = _dispatch_task_of(e)
                if tid and tid not in tids:
                    tids.append(tid)
        # ADVISORY identity (T-0559): session_started carries no task_id -> match by ref value over
        # the (windowed) wave events; the per-task bg_dispatch_launched carries expected+controller.
        started = [e for e in allev if e.get("type") == "session_started"]
        for tid in tids:
            evs = [e for e in allev if _dispatch_task_of(e) == tid]
            launched = next((e for e in reversed(evs) if e.get("type") == "bg_dispatch_launched"), None)
            identity = _dispatch_identity(launched, started, now)   # T-9749: reused by classify
            land_ok = _last_land_ok(all_events, tid)   # T-9766: authoritative land_completed:ok signal
            _c, _d, _l, _s = _classify_dispatch(evs, tid, now, identity=identity, land_ok=land_ok)
            _d = _owner_gated_detail(_d, all_events, tid, _dispatch_task_of=_dispatch_task_of)
            rows.append((tid, _c, _d, _l, _s, identity))
            chain_of[tid] = evs   # T-11344 — the row's own chain (see the --task branch note)
            allev_of[tid] = all_events   # T-11743 — the wave's one stream serves every wave row
    # T-11743 — RENDER IN THE ORDER ASKED. Walking the requested list (rather than the answered
    # rows) is what makes an unanswerable id impossible to drop: the loop is driven by what the
    # caller asked for, so a missing id has to be printed to be skipped.
    row_of = {r[0]: r for r in rows}
    order = requested if requested else [r[0] for r in rows]
    if getattr(args, "json", False):
        for tid in order:
            _row = row_of.get(tid)
            if _row is None:
                # the SAME empty-chain object the single-id path emits — an id named as
                # unanswerable, never an absent line the reader could mistake for silence.
                print(json.dumps({"task_id": tid, "class": "no_dispatch", "detail": "no-matching-events",
                                  "last_ts": None, "session_ref": None, "identity": None,
                                  "last_type": None, "marker_ts": None,
                                  "quiescent": None, "recovery": None,
                                  "dead_but_unlanded": None, "cause_tag": None}, ensure_ascii=False))
                continue
            tid, cls, detail, last_ts, sref, identity = _row
            all_events = allev_of.get(tid) or []
            print(json.dumps({"task_id": tid, "class": cls, "detail": detail,
                              "last_ts": last_ts, "session_ref": sref, "identity": identity,
                              # T-11344 — the two clocks, INDEPENDENTLY sourced: the type of the event
                              # `last_ts` came from, and the halt marker's OWN ts (null on a row whose
                              # reading is not marker-minted). A row where they coincide honestly
                              # repeats one timestamp; nothing derives either from the other.
                              "last_type": _dispatch_last_event_type(chain_of.get(tid), last_ts),
                              "marker_ts": _dispatch_halt_marker_ts(chain_of.get(tid) or [], tid, cls, detail,
                                                                    _dispatch_task_of=_dispatch_task_of),
                              "quiescent": _dispatch_quiescent(cls),
                              # T-11565 — the row's own detail routes the launch-stall remedy
                              "recovery": _dispatch_recovery_hint(cls, tid, detail),
                              "dead_but_unlanded": _dispatch_dead_but_unlanded(cls),
                              # T-9240 (AC2): the last unresolved land abort cause/test/mode for the row
                              "last_land_abort": _last_land_abort(all_events, tid),
                              # T-9751: the controlled-vocab block cause-tag (halted rows only, else null)
                              "cause_tag": _dispatch_cause_tag(all_events, tid, cls, detail, _dispatch_task_of=_dispatch_task_of),
                              # T-11352 — ADDITIVE: the worktree path(s) whose un-landed journal
                              # supplied rows behind this verdict (null when main corroborates all
                              # of them). Readers were checked before adding: no dispatch-status
                              # reader pins an exact key set.
                              "unlanded_evidence": _dispatch_unlanded_loci(chain_of.get(tid)) or None,
                              # T-11797 — ADDITIVE: whether this branch's red batch PENALISED it or
                              # CLEARED it. Null when its current attempt carries no red-batch member
                              # row, so every row that had no such history is byte-identical. Readers
                              # were re-checked before adding, the same duty T-11352 recorded above:
                              # the only programmatic consumer of this record (`_watch_wake_decision`,
                              # bin/lib/dispatch.py) reads `class`/`detail` by `.get()`, and no reader
                              # in bin/ or tests/ pins an exact key set.
                              "batch_disposition": _dispatch_batch_disposition(all_events, tid)},
                             ensure_ascii=False))
        return
    # T-10010: the cross-session land-frontier summary (human mode only — JSON per-row shape above is
    # unchanged), printed ABOVE the rows so a controller sizes the land-admission wave against ALL
    # sessions' lands (task/ AND work/), not just its own dispatches. Suppressed when the box is idle.
    _fl = _land_frontier_line(_live_land_frontier)
    if _fl:
        print(_fl)
    # T-11743 — `and not missing`: a read whose every requested id is unanswerable must NAME them,
    # not collapse to one anonymous "(no dispatches match)" that says nothing about which ids it
    # covered. The no-request wave view is unchanged.
    if not rows and not missing:
        print("(no dispatches match)")
        return
    for tid in order:
        _row = row_of.get(tid)
        if _row is None:
            # T-11743 — same wording as the single-id path, rendered as a row so the id keeps its
            # place in the requested order beside the ids that DID answer.
            print(f"{tid:<8} no_dispatch(no-matching-events)  (no dispatch events match {tid})")
            continue
        tid, cls, detail, last_ts, sref, identity = _row
        all_events = allev_of.get(tid) or []
        label = f"{cls}({detail})" if detail and cls in ("TERMINAL", "hang_suspect", "closed_pending_land", DISPATCH_CLASS_CLOSED_AWAITING_CONTROLLER_LAND, "launch-stall", "paused") else cls
        # T-12304 — a `paused(controller-wait)` row is actionable ONLY if the pending step is named,
        # and the pause row already carries it; print it beside the class (report-only, AC1).
        natxt = ""
        if cls == "paused":
            _na = _controller_wait_next_action(chain_of.get(tid) or [])
            natxt = f'  next-action="{_na}"' if _na else ""
        idtxt = f"  identity={identity}" if identity else ""
        # T-0583: surface the journal-quiescence predicate the respawn-adopt PROCEDURE keys off (never
        # the launched pid). Only when applicable (non-terminal): quiescent=false => respawn DEFERRED;
        # quiescent=true => journal-quiescent, eligible only after the controller's no-live-process check.
        q = _dispatch_quiescent(cls)
        qtxt = f"  quiescent={str(q).lower()}" if q is not None else ""
        # T-1117: mark the explicit dead-but-unlanded ORPHAN classification inline (a journal-shape
        # candidate the controller confirms via the Confirmed-dead GATE; the reader never process-walks).
        dbu = "  [DEAD-BUT-UNLANDED orphan]" if _dispatch_dead_but_unlanded(cls) else ""
        # T-9751: the controlled-vocab block cause-tag for a halted row (verify-flake | audit-ceiling
        # | owner-gate) so a controller routes the block without opening the worker's events.jsonl.
        cause = _dispatch_cause_tag(all_events, tid, cls, detail, _dispatch_task_of=_dispatch_task_of)
        ctxt = f"  cause={cause}" if cause else ""
        # T-11344 — the row used to print ONE clock (`last=<ts>`, the chain's newest event OF ANY TYPE)
        # while its CLASS and `cause=` came from a halt marker that could be hours older. Print the two
        # clocks distinguishably: the last event NAMED BY TYPE (the sibling fleet-verdict shape) and, on
        # a marker-minted row, `marked=<ts>` — the marker's own clock, beside the class it produced.
        # `marked=` is a NEUTRAL label carrying a bare timestamp: no age, no freshness verdict, no
        # stale/old/expired word (the auditor's condition — a halt marker is fully actionable until
        # positively cleared, and a judgemental label would erode that fail-closed intent).
        ltype = _dispatch_last_event_type(chain_of.get(tid), last_ts)
        ltxt = f"{last_ts or '-'}({ltype or '-'})"
        marker_ts = _dispatch_halt_marker_ts(chain_of.get(tid) or [], tid, cls, detail,
                                             _dispatch_task_of=_dispatch_task_of)
        mtxt = f"  marked={marker_ts}" if marker_ts else ""
        # T-11352 — NAME THE LOCUS when this verdict rests on evidence `main` does not carry. The row
        # is read on main, so a controller that cannot corroborate it there has, until now, had no way
        # to tell "the journal disagrees with me" from "the journal has not seen it yet". One neutral
        # token, no verdict of its own; absent whenever main corroborates every row.
        loci = _dispatch_unlanded_loci(chain_of.get(tid))
        utxt = f"  unlanded-evidence={','.join(loci)}" if loci else ""
        # T-11797 — SAY WHICH SIDE OF A RED BATCH THIS BRANCH IS ON. Until now an EXONERATED member
        # (released because the HEAD owned the red) and a genuinely MARKED one carried the same
        # `requeued-after-red-batch` verdict and rendered here identically — no batch fact at all — so
        # the only word a reader could reach for was the penalty word, for a branch that had been
        # explicitly cleared (measured on T-11782 vs T-11732, 2026-08-28). The facts were always on
        # the member rows; nothing rendered them. Absent whenever the branch has no red-batch history
        # in its current attempt, so a row that never faced a batch is unchanged.
        btxt = _batch_disposition_token(_dispatch_batch_disposition(all_events, tid))
        print(f"{tid:<8} {label:<22} last={ltxt}{mtxt}  session={sref or '-'}{idtxt}{qtxt}{ctxt}{btxt}{dbu}{utxt}{natxt}")
        # T-1117: surface the concrete recovery route for a recovery-bearing class on its own
        # indented line (the hint is long); None for healthy/terminal classes => no line.
        rec = _dispatch_recovery_hint(cls, tid, detail)   # T-11565 — detail routes the launch-stall remedy
        if rec:
            # T-9240 (AC2): name the last land abort cause + failing test(s) + verify mode on the
            # existing recovery line, so a controller does not theorize/--ack a real pinned verify-fail.
            print(f"         recovery: {rec}{_land_abort_suffix(_last_land_abort(all_events, tid))}")

def cmd_journal_lifecycle_integrity(args: argparse.Namespace, *, LIFECYCLE_INTEGRITY_WINDOW_SEC, _consumer_journals, _dispatch_lifecycle_integrity, _dispatch_status_events, _DISPATCH_AUDIT_TYPES=("audit_pre_completed", "audit_post_completed", "external_audit_completed")) -> None:
    """`journal query --lifecycle-integrity` — PURE READ-ONLY (no emit, no gate). Flags any DISPATCHED
    worker that reached a land/close terminal WITHOUT its governed worktree_created + task_picked +
    audit chain (the X-0044 bypass shape). Report-only backstop for the dispatch-worker preamble
    (T-9365); surfaced in the QUEUE §Re-review weekly sweep. Rows print in THREE tiers — BYPASS (the
    X-0044 shape) / claim-gap (one claim marker absent, the other + the audit present) / advisory
    (audit only); the tier rule itself is homed in `_dispatch_lifecycle_integrity` (T-11021). --since/--until bound the window; the
    no-arg default spans a WEEK (~8 days, LIFECYCLE_INTEGRITY_WINDOW_SEC) to match the weekly cadence
    — the 24h dispatch-wave default would miss bypasses older than 1 day (T-9367); --json emits one
    object per flagged task.

    CONSUMER FOLD (T-11022). The sweep judges the KERNEL locus and then EACH registry consumer locus,
    reusing the `_consumer_journals` enumerator T-10473 built for `--fleet-verdict`. Without it a run
    from the kernel was BLIND to every `-C` dispatch — a consumer dispatch appends `bg_dispatch_launched`
    to the CONSUMER journal (0 such rows in the kernel's vs 203/370/190 in kupiclub/boomrocket/aiseller),
    so the weekly sweep reported clean over the population that never had the problem and said nothing
    about the one that did: the single real X-0044 occurrence in the system's history was a consumer
    dispatch. The loci are judged SEPARATELY, never merged, because task ids are allocated PER PROJECT —
    a consumer's `T-0001` and the kernel's `T-0001` are different tasks, and one merged map would invent
    both false flags and false cleans. Each row therefore carries `project` (None = the kernel locus).
    An unreadable/missing consumer journal is skipped, and the header STATES how many loci were read so
    a fold that silently read nothing cannot pass for a clean fleet."""
    now = _dt.datetime.now(_dt.timezone.utc)
    since, until = getattr(args, "since", None), getattr(args, "until", None)
    if not since and not until:
        since = (now - _dt.timedelta(seconds=LIFECYCLE_INTEGRITY_WINDOW_SEC)).strftime("%Y-%m-%dT%H:%M:%SZ")
    def _audit_probe(journals=None):
        """T-11026 — 'is there an audit for this task ANYWHERE on this locus?', unbounded by the
        report window. Reuses the ONE dispatch reader (SPEC-0133 rule 5 — no second journal path),
        narrowed to the audit types so the raw-line prescan keeps it cheap, and re-pointed at the
        SAME locus the row came from (task ids are per project). Used only to decide whether an
        absent audit is the task's gap or the window's."""
        def _probe(task_id):
            evs = _dispatch_status_events(task_id=task_id, since=None, until=None,
                                          include_types=_DISPATCH_AUDIT_TYPES, journals=journals)
            return any(e.get("type") in _DISPATCH_AUDIT_TYPES for e in evs)
        return _probe

    allev = _dispatch_status_events(task_id=None, since=since, until=until)
    # only the flagged (missing-something) lands
    rows = _dispatch_lifecycle_integrity(allev, _audit_outside_window=_audit_probe())
    for r in rows:
        r["project"] = None                       # the kernel locus — the key is present on EVERY row
    loci_read = 1
    for cj in (_consumer_journals() or []):
        cj = Path(cj)
        if not cj.exists():
            continue
        project = cj.parent.name
        # Bounded by the registry consumer count; reading every locus exactly once is the point of the
        # verb (T-11022 — a silent 1-locus read read as a clean fleet).
        # inloop-journal-read: per-LOCUS — `cj` is the loop variable, so each iteration reads a
        # DIFFERENT consumer journal and no single read can serve them all.
        cev = _dispatch_status_events(task_id=None, since=since, until=until, journals=[cj])
        loci_read += 1
        for r in _dispatch_lifecycle_integrity(cev, _audit_outside_window=_audit_probe(journals=[cj])):
            r["project"] = project
            rows.append(r)
    rows.sort(key=lambda r: (r.get("project") or "", r["task_id"]))
    if getattr(args, "json", False):
        for r in rows:
            print(json.dumps(r, ensure_ascii=False))
        return
    # The locus count is printed WHETHER OR NOT anything flagged: "clean" only means something once the
    # reader knows how many journals were actually read (T-11022 — the whole defect was a silent 1-locus
    # read reading as a clean fleet).
    scope = f" over {loci_read} locus/loci (kernel + registry consumers)"
    if not rows:
        print(f"lifecycle-integrity: no bypassed dispatched lands in window{scope} (report-only)")
        return
    bypass = [r for r in rows if r["severity"] == "bypass"]
    claim_gap = [r for r in rows if r["severity"] == "claim-gap"]
    advisory = [r for r in rows if r["severity"] == "advisory"]
    instrument_gap = [r for r in rows if r["severity"] == "instrument-gap"]
    print(f"lifecycle-integrity (report-only, no gate){scope}: {len(bypass)} BYPASS, "
          f"{len(claim_gap)} claim-gap, {len(advisory)} advisory, "
          f"{len(instrument_gap)} instrument-gap")

    def _who(r):
        # A bare id is ambiguous once several projects are in the same report (ids are per-project) —
        # so name the locus on every row, never only on the consumer ones.
        return f"{r.get('project') or 'kernel'}/{r['task_id']}"

    for r in bypass:
        print(f"  BYPASS   {_who(r):<24} landed but MISSING: {', '.join(r['missing'])}  (no claim+worktree — the X-0044 shape; investigate)")
    for r in claim_gap:
        print(f"  claim-gap {_who(r):<24} landed but MISSING: {', '.join(r['missing'])}  (the OTHER claim marker AND the external audit are present — a governed land with one un-emitted marker, NOT the X-0044 shape)")
    for r in advisory:
        print(f"  advisory {_who(r):<24} landed but MISSING: {', '.join(r['missing'])}  (audit absent — may be a Fast-Path docs/hygiene task)")
    for r in instrument_gap:
        # NOT a "MISSING" row (T-11026): an audit for this task provably exists, this check just
        # could not see it. Say what was not observed and why, and claim nothing about the task.
        print(f"  instrument-gap {_who(r):<18} audit NOT OBSERVED by this check: an audit event for "
              f"this task exists outside the judged slice (before/after the first completion) or "
              f"outside the report window — an instrument gap, NOT a missing audit; widen --since or "
              f"read `journal query --dispatch-status --task {r['task_id']}` for the full chain")

# T-11899 — `journal query` --since/--until: REFUSE an unparseable value instead of silently
# returning an empty result. The filter at the single comparison site below is a RAW STRING
# comparison (`ts < args.since`); any non-ISO value — `24h` is the natural duration form to type —
# sorts above every real timestamp, so the whole journal is silently excluded and the caller reads a
# REJECTED FILTER as a PROVEN ABSENCE. That is SPEC-0165 item 11 case (c) verbatim: a reader
# returning a SET must return a third value when it cannot answer, never an empty set. (MEASURED
# pre-fix: `--since 24h` and `--since banana` both exited 0 with zero rows against a journal that
# returns 169 for the equivalent ISO window.) NOT in scope: accepting durations — `24h` is now a
# loud refusal, not a parsed window.
_TS_WINDOW_SHAPE = "ISO-8601 date (2026-05-29) or timestamp (2026-05-29T15:00:00Z)"
# The ONLY two zone-less spellings that are an exact prefix of a canonical timestamp, and so
# the only two safe to compare verbatim. Every other zone-less shape fromisoformat accepts is
# refused rather than mis-ordered.
_ZONELESS_PREFIX_SHAPE = re.compile(r"\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}:\d{2})?")


def _normalize_ts_window_value(raw: str) -> "str | None":
    """Parse an ISO-8601 --since/--until value; return the form the raw string comparison may use,
    or None if it does not parse (the caller refuses).

    TWO SHAPES, handled DIFFERENTLY so that no currently-valid input changes its result set:

    The split is by TIMEZONE PRESENCE, and it is the whole rule:

    * ZONE-BEARING (`2026-05-29T10:00:00Z`, `2026-05-29T10:00:00+03:00`) -> NORMALIZED to the
      journal's canonical comparable form `%Y-%m-%dT%H:%M:%SZ` in UTC. Validation ALONE would not be
      enough here: an offset-bearing value parses fine yet still mis-orders under a raw string
      comparison (`+` sorts below `Z`), so it would answer with the wrong SET rather than refusing.
      An already-canonical `...Z` timestamp normalizes to itself, byte-identical.
    * ZONE-LESS -> passed through VERBATIM, deliberately NOT normalized, but ONLY for the two shapes
      that are an exact PREFIX of a canonical timestamp: a date `2026-05-29` and a naive timestamp
      `2026-05-29T10:00:00`. Those two ALREADY order correctly under the raw comparison, so leaving
      them untouched preserves today's semantics EXACTLY.
      Any OTHER zone-less shape is REFUSED, because the prefix invariant is what makes the
      pass-through safe and it holds for those two shapes ONLY. `fromisoformat` is far more
      permissive than the prefix rule: it accepts a space separator (`2026-05-29 10:00:00`), the
      basic form (`20260529`), a minute-precision form (`2026-05-29T10:00`) and fractional seconds
      (`2026-05-29T10:00:00.5`) — and `20260529` is the loud case, sorting ABOVE every canonical
      timestamp ('0' > '-') and so silently excluding the whole journal, the very bug this closes.
      Parseability is NOT the admission test here; comparability is. Refusing is the honest answer
      for a value this reader cannot order, and it costs nothing real: a zone-BEARING value of any
      of those shapes is still accepted, because normalization makes its input spelling irrelevant.

    The pass-through is deliberate, not an omission: normalizing a zone-less value would append the
    missing tail (`<date>` -> `<date>T00:00:00Z`, `<naive>` -> `<naive>Z`), and because `--until` is
    an INCLUSIVE `ts > until` exclusion, that lengthening flips the boundary-sharp event from
    EXCLUDED to INCLUDED. That is a silent answer change on an input that is VALID TODAY — precisely
    the class of failure this card exists to close, so it must not be introduced while closing it.
    Assuming UTC for a naive value would compound it with an invented timezone the caller never gave.
    """
    v = (raw or "").strip()
    if not v:
        return None
    try:
        # fromisoformat does not accept a trailing `Z` before 3.11; map it to the explicit offset.
        parsed = _dt.datetime.fromisoformat(v[:-1] + "+00:00" if v.endswith("Z") else v)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        # Comparability, not parseability: admit ONLY the two canonical-PREFIX spellings verbatim.
        return v if _ZONELESS_PREFIX_SHAPE.fullmatch(v) else None
    return parsed.astimezone(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _fallback_die(msg: str, code: int = 1) -> None:
    """Refusal path for a caller that reaches this reader WITHOUT the injected `_die` — the census
    drivers and any other direct `cmd_journal_query(...)` call site. `_die` stays INJECTED for the
    real CLI wiring, but it must not be REQUIRED: making it so turned every such direct call into a
    TypeError, which is a WORSE failure than the one this card closes (the reader stops answering at
    all rather than answering wrongly). Same shape as cli.py#_die: the `yitc-v2: ` prefix on stderr,
    then SystemExit."""
    print(f"yitc-v2: {msg}", file=sys.stderr)
    raise SystemExit(code)


def _validate_ts_window(args: argparse.Namespace, _die=None) -> None:
    """Validate + canonicalize --since/--until at argument-handling time, refusing loudly.

    Called at the TOP of cmd_journal_query — BEFORE the sub-mode early-returns — because every
    sub-mode reader (dispatch-status, dispatch-readiness, fleet-verdict, lifecycle-integrity) reads
    the SAME parser's --since/--until off `args`. One check at the entry covers every arm; the
    comparison site itself stays a plain string compare over canonical values."""
    _die = _die or _fallback_die
    for flag in ("since", "until"):
        raw = getattr(args, flag, None)
        if not raw:
            continue
        normalized = _normalize_ts_window_value(raw)
        if normalized is None:
            _die(f"journal query: --{flag} {raw!r} is not a comparable timestamp — expected "
                 f"{_TS_WINDOW_SHAPE}. A value WITHOUT a timezone must be exactly one of those two "
                 f"spellings (a space separator, the basic form 20260529, minute precision or "
                 f"fractional seconds cannot be ordered against the journal and are refused). "
                 f"Durations (e.g. '24h') are NOT accepted. Refusing rather than returning an empty "
                 f"result, which would read as a proven absence (SPEC-0165 item 11c).")
        setattr(args, flag, normalized)


def cmd_journal_query(args: argparse.Namespace, *, CROSS_LOG_PATH, EVENTS_PATH, cmd_journal_dispatch_status, cmd_journal_fleet_verdict, cmd_journal_dispatch_readiness, cmd_journal_lifecycle_integrity, cmd_journal_dispatch_plan, _die=None) -> None:
    """Read-only query over events.jsonl (the one journal SoT), peer to `graph query`
    (D-0039). Reuses the per-line json.loads reader (Principle 1). Un-parseable lines are
    skipped (P5 tolerance — consumers ignore malformed/opaque rows). Results are ordered by
    `ts` ascending — events.jsonl physical order is NOT chronology after a union-merge
    (SPEC-0002). `--limit N` (default 50; <=0 = all) keeps the last N (tail)."""
    # T-11899 — BEFORE every sub-mode early-return: all arms read this parser's --since/--until.
    _validate_ts_window(args, _die)
    if getattr(args, "dispatch_status", False):   # T-0391: the dispatch-status reader mode
        return cmd_journal_dispatch_status(args)
    if getattr(args, "fleet_verdict", False):   # SPEC-0133: the §6-safe fleet-verdict surface
        return cmd_journal_fleet_verdict(args)
    if getattr(args, "dispatch_readiness", False):   # SPEC-0133 CARD-2: the §6-safe wave-sizing advisor
        return cmd_journal_dispatch_readiness(args)
    if getattr(args, "dispatch_plan", False):   # SPEC-0136: the §6-safe Axis-B dispatch-planning advisor
        return cmd_journal_dispatch_plan(args)
    if getattr(args, "lifecycle_integrity", False):   # T-9365: post-hoc lifecycle-integrity report
        return cmd_journal_lifecycle_integrity(args)
    # SPEC-0084 r4 one-parser/one-query parity: --coordination swaps the SOURCE to the shared
    # coordination log read via the SAME loop below — proving no second coordination-log parser path.
    # T-11444 — THE SEGMENT-AWARE READ, BRANCHED BY STORE (SPEC-0190 rule 4 / SPEC-0084 rule 4).
    # This verb is the one the handbook and `patterns/` now name in place of a raw `grep events.jsonl`,
    # so it is the reader that MUST span the segment set — a `journal query` that read the live
    # segment alone would answer "not found" for every row older than the live window while looking
    # entirely healthy, and it would do so for the audience the migration just pointed here.
    # The `--coordination` arm is DELIBERATELY NOT widened: the kernel-owned shared coordination
    # store is a different store with its own kernel-only rotation (SPEC-0084), and this card's scope
    # fence keeps it out. The parity SPEC-0084 rule 4 asks for is ONE PARSER and one query loop —
    # which is exactly what stays shared below; only the physical fold differs, because only one of
    # the two stores has segments. (Census note: this reader is ABSENT from T-11442's census — its
    # target was a conditional assignment the AST enumerator could not resolve. Captured as
    # `census-missed-conditional-target-journal-reader-cmd-journal-query`.)
    coordination = bool(getattr(args, "coordination", False))
    src = CROSS_LOG_PATH if coordination else EVENTS_PATH
    if not src.exists():
        print("(no coordination log)" if coordination else "(no events.jsonl)")
        return
    grep = (args.grep or "").lower() if getattr(args, "grep", None) else None
    # T-11743 — `--task` is REPEATABLE on this parser, so the plain filter is set-membership. It
    # must not become the second place where a repeated flag silently keeps only the last id.
    want_tasks = set(_requested_task_ids(args))
    matched = []
    lines = (src.read_text(encoding="utf-8").splitlines() if coordination
             else segment_lines(src))
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(e, dict):
            continue
        if args.type and e.get("type") != args.type:
            continue
        if want_tasks and e.get("task_id") not in want_tasks:
            continue
        # session_ref is an envelope-level writer-metadata field (per _append_event), NOT data.*
        if args.session and e.get("session_ref") != args.session:
            continue
        ts = e.get("ts") or ""
        if args.since and ts < args.since:
            continue
        if args.until and ts > args.until:
            continue
        if grep is not None:
            # decoded haystack — robust regardless of how non-ASCII was stored (cross-language)
            if grep not in json.dumps(e, ensure_ascii=False).lower():
                continue
        matched.append(e)

    matched.sort(key=lambda e: e.get("ts") or "")
    limit = getattr(args, "limit", 50)
    if limit and limit > 0:
        matched = matched[-limit:]

    if getattr(args, "json", False):
        for e in matched:
            print(json.dumps(e, ensure_ascii=False))
        return
    if not matched:
        print("(no events match)")
        return
    for e in matched:
        ts = e.get("ts") or "-"
        typ = e.get("type") or "-"
        task = e.get("task_id") or "-"
        print(f"{ts}  {typ:<28} {task:<8} {events._event_summary(e.get('data') or {})}".rstrip())

def cmd_journal_sync(args: argparse.Namespace, *, _journal_sync) -> None:
    n = _journal_sync(getattr(args, "session_ref", None))
    print(f"journal sync: {n} event(s) materialized")
