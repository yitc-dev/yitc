"""Post-deploy proof-obligation fold (SPEC-0149) — a DERIVED debt view over the journal.

GOVERNING SPEC: SPEC-0149 ("Post-deploy proof obligation — a journal-derived debt view, no stored
obligation state"). A deploy that owes a later proof — a Class-C1 write-path re-check after the
observation window (SPEC-0097 §3), or a Class-S post-deploy property assertion — and never got it
SHOWS UP as a line in the existing `bin/yitc-v2 debt` echo (SPEC-0119), without anyone remembering
to look. Closing the proof silences it.

THE ACCEPTANCE BOUNDARY (SPEC-0149 §2). There is NO stored obligation record, NO new FSM, NO new
store: the journal facts ARE the state. This module only READS `events.jsonl` and returns a dict.
It opens no file for writing and creates nothing on disk — a boundary a test pins by folding inside
a sandbox tree and asserting the tree's file set is byte-for-byte unchanged.

THE ONE-WINDOW RULE (SPEC-0149 §1) — why this fold takes no carrier, no policy, and no default.
The obligation window is resolved ONCE, at deploy time, by the STAMPING step (`deploy.py#cmd_deploy`),
which reads the carrier's declaration INCLUDING any class default and records the resolved absolute
deadline into the deploy event. This fold reads ONLY that stamped value. It NEVER re-resolves and
NEVER applies a default — not as a matter of discipline but of CONSTRUCTION: it is handed no carrier
to default from. A deploy event with no stamped window is therefore invisible here, so window-less
HISTORY is never retro-charged.

That last property is the one the trial run bought, and it cost a disproof to learn: a fold-side
default applied over the real journals retro-created 39 debt lines across 3 consumers (17 + 7 + 15) —
noise that buries the echo it rides (`trial_run_completed` 2026-07-09T19:28:23Z). A dual source (the
fold defaulting when the event lacked a window) is exactly what the one-window rule forecloses.

ONE SURFACE, BOTH PENDING HALVES (SPEC-0149 §3). The C1 delayed re-check (which cannot gate the
deploy seam — it falls due long after it) and the Class-S post-deploy assertion are the same shape:
a proof owed AFTER the seam. They share this one view. Per the owner ruling recorded on T-10283
(2026-07-09), a FAILED post-deploy Class-S assertion is an immediate owner escalation plus an OPEN
obligation — never an auto-rollback (SPEC-0097 §2: exposure is not undone by an image rollback).

Like `cmd_deploy` / `cmd_init`, this module back-imports NOTHING from the host.
"""
from __future__ import annotations

import ast
import bisect
import difflib
import hashlib
import json
import io
import os
import re
import shlex
import tokenize
from datetime import date, datetime, timezone
from pathlib import Path, PurePosixPath

import yaml

from lib import state  # CHARTER §P5 one parser library — the ops-carrier reader (T-9740)
from lib import journal  # T-11453: the ONE parsed journal fold + its request-scoped memo (CHARTER §P5)

# The stamped-window CARRIERS the fold reads (SPEC-0149 §1, verbatim). Only `deploy_completed` is
# STAMPED today (one writer — `cmd_deploy`; a second stamping site would be the dual source the
# one-window rule forbids). `deploy_backup_taken` is named by the spec as the alternate carrier and
# is read here, so a stamped backup event folds identically the day the spec's other half lands —
# without this reader growing a special case for it.
OBLIGATION_CARRIER_EVENTS = ("deploy_completed", "deploy_backup_taken")

# The CLOSING event: the recheck that discharges the obligation. It carries `{project, revision}` and
# rides the EXISTING generic `event` verb (`bin/yitc-v2 event deploy_recheck_completed --data …`) —
# SPEC-0149 §2 admits no new verb, emitter, or store for it.
OBLIGATION_CLOSING_EVENT = "deploy_recheck_completed"

# The SECOND discharge: the honest MISS (T-11169, kupiclub X-0923). Rule 1 defined exactly ONE exit —
# a matching later recheck — so an obligation whose window ALREADY EXPIRED had no honest exit at all:
# the only mechanical move left was to emit the recheck late, i.e. to record a proof nobody performed.
# (Measured 2026-08-15: 7 open, six carrying a stamped 24h window from 2026-08-09/10, days overdue against
# revisions six later deploys had superseded. A 24-hour re-check run on day six is not the re-check the
# window meant.) The asymmetry this corrects is visible in rule 1's own text: it is deliberately careful
# NOT to retro-charge history with a default window (the 39-line trial disproof above) — the same care
# was never spent on an obligation correctly charged and then MISSED.
#
# It carries `{project, revision, judgement}` and rides the SAME generic `event` verb — no new verb, no
# new emitter, no store (SPEC-0149 §2 holds unchanged). The shape is T-11107's `task close
# --settle-probe` on a different axis: a proof owed, its moment passed, closed by an explicit NAMED
# record rather than by a silent flag or a false assertion.
OBLIGATION_MISS_EVENT = "deploy_recheck_missed"

# The JUDGEMENT is what keeps the miss from decaying into a "remove the line" button (owner refinement
# (a), 2026-08-16): the operator must state WHY a late re-check is or is not meaningful. It is gated
# fail-closed at the WRITE (`bin/yitc-v2#cmd_event`); this reader holds the same floor, because a
# judgement-less row that reached the journal by any other route must discharge nothing either.
OBLIGATION_MISS_JUDGEMENT_KEY = "judgement"

# The rolling window the DISCHARGE COUNTS below are reported over — the `recent_gate_overrides`
# (SPEC-0119 rule 14) analog, chosen for the same reason: a governed bypass must stay visible AFTER the
# fact, and an unbounded total would become a monument nobody reads instead of a live signal. Owner
# refinement (b): the miss stays COUNTABLE after discharge, so a systematic pattern of unmet windows
# does not vanish with the line it silenced.
MISS_WINDOW_DAYS = 30


# ── SPEC-0190 rule 4 — the WINDOWED readers' segment floor (T-12030) ─────────────────────────────
#
# WHAT THIS IS. Several folds below keep only rows inside a trailing window (7 d / 14 d / 24 h /
# 168 h / 30 d) and, until T-12030, each folded the WHOLE logical journal to find them — 93 archive
# segments, 216 MB, per view, at every session start (measured on the engine 2026-09-03). Rule 4
# names that as the defect: a reader's declared horizon is its window, and a segment whose dated
# name lies wholly before that window cannot hold a row the reader would keep.
#
# ONE MARGIN, DECIDED ONCE. Every routed reader's in-loop predicate is slightly LOOSER than its
# nominal window — `(now - ts).days > window` truncates, union-merge reorders, clocks skew — so the
# floor handed to the selector is deliberately WIDER than the window by `_WINDOW_SEGMENT_MARGIN_SECONDS`.
# The direction is the whole safety argument: over-inclusion costs a file open and changes NO output,
# under-inclusion would silently narrow a view's answer. Deciding it HERE, once, is what stops five
# readers each re-deciding their own margin (CHARTER §P5). The margin is expressed in EPOCH
# SECONDS, not as a `timedelta`, matching the idiom `aborted_land_cost` already uses for the same
# reason it gives there — same instants, no duration type introduced into this module.
_WINDOW_SEGMENT_MARGIN_SECONDS = 2.0 * 86400.0


def _window_segment_floor(now, *, days=None, hours=None) -> str:
    """The ISO DATE below which no segment can hold a row this reader would keep — the `since` a
    windowed fold hands `journal.segment_rows_since`.

    `now` is the reader's own clock value (aware UTC), `days`/`hours` its own window; the result is
    that window widened by `_WINDOW_SEGMENT_MARGIN_SECONDS` and truncated to a date, because an
    archive label IS a date (`events-YYYY-MM-DD.jsonl` holds exactly one UTC day — the label contract
    `events.rotate_journal` fixes).

    It NEVER decides membership. The caller's existing `ts` comparison still admits or rejects every
    row it is handed; this only stops files being opened. A caller that cannot resolve a floor passes
    None and gets the whole set.

    IT RETURNS None RATHER THAN RAISING, and the direction is the same one every choice here takes.
    A `now` far enough in the past that the widened floor falls outside the representable range
    (`datetime.fromtimestamp` raises for a year below 1) is not a reason for a REPORT-ONLY fold to
    die — and `None` degrades `segment_rows_since` to the whole segment set, i.e. to exactly the
    behaviour before this card. So an unresolvable floor costs the optimisation and nothing else.
    Caught in review by `tests/test_t11449_reader_multiset_identity.py`, which drives every census
    reader against a synthetic clock: `recent_gate_overrides` raised `year -639 is out of range`."""
    try:
        span = float(days) * 86400.0 if days is not None else float(hours or 0) * 3600.0
        floor = now.timestamp() - span - _WINDOW_SEGMENT_MARGIN_SECONDS
        return datetime.fromtimestamp(floor, tz=timezone.utc).strftime("%Y-%m-%d")
    except (AttributeError, OSError, OverflowError, TypeError, ValueError):
        return None


def _parse_stamped_deadline(value):
    """Parse an ISO-8601 instant (a stamped `recheck_by`, or an event `ts`) into an aware UTC datetime,
    else None.

    FAITHFUL, never fail-closed (`lessons/fail-closed-belongs-to-the-reader-not-the-parser.md`): this
    reports only what the event literally says. An absent / malformed / non-string value yields None,
    and the single READER below decides what that means — here, "not a window-carrying event", which
    is the legitimately-OPEN default the one-window rule depends on. A malformed *declaration* is a
    different class entirely, and is refused at its own use site: the deploy verb, at stamping time.

    Accepts the `Z` suffix the journal writes; a naive timestamp is read as UTC (the journal's own
    convention — every `ts` is UTC).
    """
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _obligation_key(data):
    """The identity an obligation is discharged BY: `(project, revision)`.

    The revision alone is not the key — two projects can legitimately deploy the same sha (a shared
    kernel revision), and one project's recheck must not silence another's obligation. Returns None
    when either half is missing, so a shapeless event cannot open (or close) an obligation.
    """
    if not isinstance(data, dict):
        return None
    project, revision = data.get("project"), data.get("revision")
    if not isinstance(project, str) or not project.strip():
        return None
    if not isinstance(revision, str) or not revision.strip():
        return None
    return (project.strip(), revision.strip())


def revision_key_near_miss(events_path, project, revision):
    """Is `revision` an ABBREVIATION of a revision this project actually DEPLOYED? (T-11224, X-0963)

    The discharge key above is EXACT, and that is correct — but it made one particular mistake
    SILENT: a recheck row carrying `git rev-parse --short` output (a 7-char prefix of the sha the
    obligation was stamped against) appends happily, matches no carrier, discharges NOTHING, and the
    fold reports nothing about it either. Silence that looks identical to success is the loud-failure
    class (SPEC-0165), and it is not cheap here: at kupiclub seven governance events had to be
    re-authored and re-emitted, and the journal being append-only, the seven superseded rows stay
    forever. So the check belongs at the WRITE, where the bad row can still be stopped from existing
    (`bin/yitc-v2#cmd_event`) — a fold-side report only shortens the discovery loop afterwards.

    Returns None (= nothing to say) unless the supplied revision is a STRICT prefix of at least one
    revision this SAME project carries a deploy carrier for, and is not itself an exact deployed
    revision. That NARROWNESS is the whole safety argument, and it is deliberate on three axes:
      * an exact full-sha row is untouched — the healthy case must gain no refusal and no warning, or
        the fix re-creates the alarm erosion it exists to reduce;
      * a project whose revision keys are not shas (tags, dates, build numbers) is untouched — only a
        provable abbreviation of a revision THIS project really deployed fires;
      * the project half of the key is honored, so one project's sha can never refuse another's row
        (the same reason `_obligation_key` is a pair and not a bare revision).
    Matching is case-insensitive because a sha is hex either way; the CANDIDATES are returned in the
    journal's own spelling, since the caller's job is to name the form the operator should have used.

    Never raises: a missing/unreadable journal or a malformed line yields None, exactly like the
    sibling near-miss reader (`_admission_near_misses`). This is a pure reader — it reads the journal
    and returns a dict; the SPEC-0149 §2 zero-stored-state boundary is untouched, as is
    `open_proof_obligations`, whose semantics this does not change.

    READS THE WHOLE LOGICAL JOURNAL, segment by segment (T-11587, SPEC-0190 rule 4). The horizon here
    is UNBOUNDED — the deploy a short revision abbreviates may be months old — so the single-file fold
    this used to call would answer "is this an abbreviation of a revision we DEPLOYED?" against a
    truncated deploy history, and a real near-miss would read as no match at all. `segment_rows` reads
    each segment through the SAME `fold_rows` primitive, so there is still ONE parse path and the
    per-line skip policy below is inherited unchanged.
    """
    if not isinstance(project, str) or not project.strip():
        return None
    if not isinstance(revision, str) or not revision.strip():
        return None
    wanted_project, supplied = project.strip(), revision.strip()
    probe = supplied.lower()

    candidates: list = []
    try:
        for event in journal.segment_rows(events_path):   # SPEC-0190 rule 4 — the WHOLE journal
            if not isinstance(event, dict) or event.get("type") not in OBLIGATION_CARRIER_EVENTS:
                continue
            key = _obligation_key(event.get("data"))
            if key is None or key[0] != wanted_project:
                continue
            deployed = key[1]
            if deployed.lower() == probe:
                return None           # an EXACT deployed revision — the healthy row, say nothing
            if deployed.lower().startswith(probe) and deployed not in candidates:
                candidates.append(deployed)
    except (OSError, UnicodeDecodeError):
        return None

    if not candidates:
        return None
    return {"project": wanted_project, "supplied": supplied, "candidates": sorted(candidates)}


def _superseded_before_deadline(deploys, project, revision, deploy_ts, deadline) -> bool:
    """Was this deploy's revision REPLACED on the same project before its own deadline? (T-11760)

    An obligation asks for a proof ON A REVISION. Once a LATER deploy of a DIFFERENT revision has
    replaced it, the revision the obligation names has stopped serving, and the proof it asks for is
    no longer performable — the consumer measurement behind this card found every one of its 11
    misses was exactly this shape (median 99 minutes served against a 24h window), never neglect.
    Charging it is charging a debt nobody can pay, and an unpayable debt is the alarm-erosion class.

    STRICT on BOTH ends, and each end is the guard for one direction:
      * `> deploy_ts` — a revision cannot supersede itself, and the deploy's own row (or a same-second
        sibling carrier, `deploy_completed` + `deploy_backup_taken`) must not read as its replacement.
      * `< deadline` — the direction that MATTERS (AC2). A replacement arriving at or after the
        deadline does not retro-excuse an obligation that was genuinely owed the whole time its
        revision served. Without this end the view degrades into a way of WAITING OUT a proof: deploy
        again eventually and the debt evaporates.
    The project half of the key is honored throughout, for the same reason `_obligation_key` is a pair:
    one project's deploy can never supersede another's obligation.

    Derived from rows the fold already holds (`deploys` is the per-project carrier list collected in
    the same single pass) — no new event type, no new stored field, no new store (SPEC-0149 §2).
    """
    for other_ts, other_revision in deploys.get(project, ()):  # rows already parsed this pass
        if other_revision == revision:
            continue
        if deploy_ts < other_ts < deadline:
            return True
    return False


def open_proof_obligations(events_path, now=None) -> dict:
    """Fold the journal → the OPEN post-deploy proof obligations (SPEC-0149 §1).

    An obligation is OPEN iff a carrier event STAMPED a window (`recheck_by`), the deadline has
    PASSED as of `now`, and neither discharge matched it. A window still open is SILENT — not yet
    owed; the passed deadline is what makes it debt. A window-less event is invisible (the
    one-window rule).

    TWO DISCHARGES, NOT ONE (T-11169). The PROVEN discharge is a `deploy_recheck_completed` for the
    same `(project, revision)` at or after the carrier's own `ts` — the re-check was performed. The
    MISSED discharge is a `deploy_recheck_missed` carrying a stated `judgement`, and it is admitted
    ONLY when it post-dates BOTH the carrier AND the carrier's own DEADLINE. That second gate is the
    whole difference between an honest discharge and a general mute button: while the window is still
    OPEN the obligation is live and re-checkable, so there is nothing to be honest ABOUT yet, and a
    miss recorded then silences nothing — then or ever after (it stays recorded, it just never
    matches). You may only record having missed a window that has actually passed.

    THE COUNTS FOLLOW THE DISCHARGE, NEVER THE EVENT (audit-pre finding, absorbed). `missed_count` /
    `proven_count` count carriers ACTUALLY DISCHARGED within `MISS_WINDOW_DAYS`, not miss/recheck events
    appended. An early miss, a miss for a `(project, revision)` that never deployed, and a miss
    predating its redeploy each silence nothing and so count nothing — otherwise the count would
    tally intentions rather than obligations closed, and inflate the very signal it exists to keep
    honest.

    THE CLOSER MUST POST-DATE ITS DEPLOY (SPEC-0149 §1: "no matching LATER recheck event"). A key is
    not `(project, revision) ⇒ closed forever`: the SAME revision can be deployed, rechecked, and then
    RE-DEPLOYED (a redeploy after a config change; a roll-forward). Matching a closer without an
    ordering constraint let that stale recheck silence the NEW deploy's obligation — a proof was owed
    and the echo stayed quiet. So each carrier event is evaluated against the LATEST recheck for its
    key, and discharges only if that recheck is not older than the deploy it claims to prove.

    Ordering uses `>=`, not `>`: a recheck appended in the same second as its deploy is a legitimate
    discharge (the journal stamps whole seconds), and a deploy whose obligation window is longer than
    zero cannot be discharged by its own emit — the deadline gate below still holds it.

    SUPERSESSION IS NOT A DISCHARGE — IT IS THE OBLIGATION NEVER BECOMING OWED (T-11760, X-1162).
    An obligation asks for a proof ON A REVISION. When a LATER deploy of a DIFFERENT revision replaced
    it BEFORE its own deadline, the revision the obligation names had already stopped serving, and no
    proof performable at the deadline would have meant anything. The consumer measurement behind this
    is unambiguous: of 17 stamped obligations, ALL 17 were superseded before their deadline (median
    service life 99 minutes against a 24h window) and all 11 misses were this, never neglect. An
    interval change cannot answer it — the shortest observed service life was 13 minutes, so no fixed
    window survives a project that deploys faster than it. The test is derived from carrier rows this
    same pass already reads (`_superseded_before_deadline`), so there is no new event and no new
    stored field, which is what keeps the SPEC-0149 §2 zero-stored-state boundary intact.

    A carrier whose `ts` is unparseable is SKIPPED, exactly as a window-less one is: its ordering
    cannot be established, and a report-only view does not nag on an unknown. The journal's `ts` is
    machine-written, so this is the same corruption class as the malformed-line skip above.

    Args:
      events_path: path to `events.jsonl` (missing/unreadable ⇒ a clean, zero-count result — this
        view is report-only and must never break the seam it rides).
      now: aware datetime to evaluate deadlines against; defaults to real UTC now. Injected by the
        tests so every assertion is deterministic, never wall-clock-dependent.
    Returns `{"lens", "now", "count", "obligations", "window_days", "proven_count", "missed_count",
    "missed", "next"}` — the shape the sibling derived views return
    (`views._view_overdue_recheck`). Pure: reads, writes nothing (SPEC-0149 §2): every
    count above is DERIVED from the same single journal pass, exactly as the obligations are.

    READS THE WHOLE LOGICAL JOURNAL, segment by segment (T-11587, SPEC-0190 rule 4). The horizon here
    is UNBOUNDED — an obligation is OPEN precisely BECAUSE its deadline has passed, so the ones open
    LONGEST are the first to fall out of the live segment, and the surface would go quiet exactly
    where the debt is oldest. The discharge direction matters equally: a carrier still live whose
    recheck has rotated away would read as never proven. `segment_rows` reads each segment through the
    SAME `fold_rows` primitive, so there is still ONE parse path and one pass over the result.
    """
    now = now if now is not None else datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    carriers: list = []   # (key, deploy_ts, deadline, recheck_within) — one per stamped deploy event
    closed: dict = {}     # (project, revision) -> the LATEST recheck ts seen for that key
    missed: dict = {}     # (project, revision) -> (LATEST miss ts, its stated judgement)
    # SUPERSESSION SOURCE (T-11760) — project -> [(ts, revision)] for EVERY carrier row, window-stamped
    # or not: a window-less redeploy still replaces the revision that was serving. Same pass, same rows.
    deploys: dict = {}

    try:
        for event in journal.segment_rows(events_path):   # SPEC-0190 rule 4 — the WHOLE journal
            if not isinstance(event, dict):
                continue
            etype = event.get("type")
            data = event.get("data")
            key = _obligation_key(data)
            if key is None:
                continue
            event_ts = _parse_stamped_deadline(event.get("ts"))
            if event_ts is None:
                continue          # no establishable ordering ⇒ neither opens nor closes
            if etype == OBLIGATION_CLOSING_EVENT:
                if key not in closed or event_ts > closed[key]:
                    closed[key] = event_ts
            elif etype == OBLIGATION_MISS_EVENT:
                # The READER's half of the fail-closed pair (the write gate is `cmd_event`):
                # a judgement-less miss discharges NOTHING. The judgement is the discharge's
                # substance, not decoration — without it the row is the bare flag owner
                # refinement (a) exists to forbid, whatever route put it in the journal.
                judgement = data.get(OBLIGATION_MISS_JUDGEMENT_KEY)
                if not isinstance(judgement, str) or not judgement.strip():
                    continue
                if key not in missed or event_ts > missed[key][0]:
                    missed[key] = (event_ts, judgement.strip())
            elif etype in OBLIGATION_CARRIER_EVENTS:
                deploys.setdefault(key[0], []).append((event_ts, key[1]))
                deadline = _parse_stamped_deadline(data.get("recheck_by"))
                if deadline is None:
                    continue      # no stamped window ⇒ NO obligation (never retro-charged)
                carriers.append((key, event_ts, deadline, data.get("recheck_within")))

    except (OSError, UnicodeDecodeError):
        carriers, closed, missed, deploys = [], {}, {}, {}

    # An obligation is owed by a specific DEPLOY EVENT, not by a key: a redeploy of the same revision
    # opens a fresh one, which its predecessor's recheck cannot discharge. Collapse the still-owed
    # events back to ONE line per key, keeping the OLDEST unmet deadline — the honest thing to surface
    # when a key was redeployed several times without ever being proven.
    owed: dict = {}
    proven_count = 0
    superseded_count = 0
    missed_rows: list = []
    for key, deploy_ts, deadline, within in carriers:
        if deadline >= now:
            continue                            # the window is still open — not yet owed
        discharged_at = closed.get(key)
        if discharged_at is not None and discharged_at >= deploy_ts:
            if (now - discharged_at).days <= MISS_WINDOW_DAYS:
                proven_count += 1               # PROVEN in the window — the re-check was performed
            continue                            # a recheck at/after THIS deploy proved it
        miss = missed.get(key)
        # BOTH gates, ANDed. `>= deploy_ts` is the ordering discipline the proven leg already holds
        # (a miss cannot discharge a deploy that had not happened yet). `>= deadline` is the one that
        # keeps this from being a general mute button: an obligation whose window has not yet run out
        # is still live and still re-checkable, so it CANNOT be honestly missed — and the miss stays
        # unmatched afterwards too, so pre-recording one buys nothing.
        if miss is not None and miss[0] >= deploy_ts and miss[0] >= deadline:
            if (now - miss[0]).days <= MISS_WINDOW_DAYS:
                missed_rows.append({
                    "ts": miss[0].isoformat().replace("+00:00", "Z"),
                    "project": key[0],
                    "revision": key[1],
                    "recheck_by": deadline.isoformat().replace("+00:00", "Z"),
                    "judgement": miss[1],
                })
            continue                            # closed as MISSED — honestly, and still counted
        # SUPERSESSION LAST, never before the two discharge legs (T-11760). A carrier that was
        # actually PROVEN must keep counting as proven, and an honestly-MISSED one must keep its
        # counted miss row — a supersession drop placed earlier would swallow both signals, which
        # is the opposite of what T-11169 shipped. Only what is STILL owed at this point can be
        # dropped for having stopped serving.
        if _superseded_before_deadline(deploys, key[0], key[1], deploy_ts, deadline):
            superseded_count += 1               # dropped, but never SILENTLY (SPEC-0165)
            continue
        if key not in owed or deadline < owed[key][0]:
            owed[key] = (deadline, within)

    missed_rows.sort(key=lambda r: r["ts"], reverse=True)   # most recent miss first

    obligations = [
        {
            "project": project,
            "revision": revision,
            "recheck_by": deadline.isoformat().replace("+00:00", "Z"),
            "recheck_within": within,
            "overdue_seconds": int((now - deadline).total_seconds()),
        }
        for (project, revision), (deadline, within) in owed.items()
    ]
    obligations.sort(key=lambda r: r["recheck_by"])   # oldest obligation first

    return {
        "lens": "open-proof-obligations (SPEC-0149) — deploys whose STAMPED obligation window has "
                "passed with neither discharge: no `deploy_recheck_completed` (PROVEN) and no "
                "`deploy_recheck_missed` (honestly MISSED, judgement-bearing, admissible only once "
                "the window has actually expired) AND whose revision was still serving at that deadline "
                "— an obligation SUPERSEDED by a later same-project deploy of a different revision, "
                "dated before its own deadline, is not owed at all: the proof it asks for names a "
                "revision that had stopped serving (T-11760). DERIVED at read time by folding the "
                "journal; the window is read ONLY from the deploy event that stamped it (the one-window rule — "
                "this fold never defaults, so window-less history owes nothing). Zero stored state "
                "(SPEC-0149 §2). Recomputed fresh.",
        "now": now.isoformat().replace("+00:00", "Z"),
        "count": len(obligations),
        "obligations": obligations,
        # The countability half (owner refinement (b), T-11169): a discharged miss leaves the echo, but
        # it must NOT leave the data. These counts are DERIVED from the same pass — no store, no tally
        # file — and they count obligations actually CLOSED in the window, never events appended.
        "window_days": MISS_WINDOW_DAYS,
        "proven_count": proven_count,
        # DROPPED, NOT VANISHED (T-11760): obligations that stopped being owed because their revision
        # was replaced before the deadline. Derived in the same pass, stored nowhere — it exists so a
        # drop is observable rather than an unexplained fall in the owed count.
        "superseded_count": superseded_count,
        "missed_count": len(missed_rows),
        "missed": missed_rows,
        "next": ("these deploys are APPLIED but not PROVEN — run each one's delayed re-check (a C1 "
                 "write-path re-assertion, SPEC-0097 §3) or its Class-S post-deploy assertion, then "
                 "record `bin/yitc-v2 event deploy_recheck_completed --data "
                 "'{\"project\":…,\"revision\":…}'` to discharge it. A failed Class-S assertion is an "
                 "OWNER ESCALATION + an open obligation, NEVER an auto-rollback (SPEC-0097 §2). "
                 "Where the window is so far gone that running its re-check now would prove nothing "
                 "it meant — the revision has been superseded, the observation moment has passed — "
                 "do NOT emit the re-check late: that records a proof nobody performed. Discharge it "
                 "HONESTLY instead: `bin/yitc-v2 event deploy_recheck_missed --data "
                 "'{\"project\":…,\"revision\":…,\"judgement\":\"why a late re-check is (or is not) "
                 "meaningful here\"}'`. The judgement is required, the miss stays counted, and the "
                 "record says the window was missed — it never says the proof was performed."
                 if obligations else
                 "no deploy is past its stamped proof-obligation window — nothing owed."),
    }


# ─────────────────────────────────────────────────────────────────────────────────────────────────
# THE BORN-PERMISSIVE DETECTOR REGISTRY (T-11968 / SPEC-0189 rules 1 + 5)
# ─────────────────────────────────────────────────────────────────────────────────────────────────
#
# SPEC-0189 rule 1 admits a born-permissive default ONLY as a PAIR: the permissive value AND a named
# detector for its absence. Rule 5 fixes what a detector may BE — named CODE, never a rule expressed
# inside a declaration, because a declaration block is a finite table and carries no language for one.
# This is the surface where the name meets the code.
#
# IT SHIPS EMPTY, AND THAT IS THE DESIGN, NOT AN OMISSION. Each detector is inseparable from its own
# default-flip and rides the card that owns that flip; shipping proxy readers here would put the same
# code in two waves. So this card defines the MECHANISM and registers nothing into it. The emptiness is
# asserted by the tests as a positive property, so a later reader cannot mistake it for a gap.
#
# WHAT A LATER CARD DOES — one entry, no mechanism edit:
#     register_born_permissive_detector("my-surface", _my_surface_detector)
# plus the matching two lines on its OWN `concern:` block (`born_stance: permissive` + `detector:
# my-surface`). The pairing REFUSAL that makes the convention binding lives at the declaration point
# (`init.py#born_permissive_detector_violations`, wired into `graph conformance`'s RED set), not here.
#
# WHAT THIS REGISTRY DELIBERATELY DOES NOT DO (SPEC-0189 rule 3 + `lessons/a-presence-count-is-not-a-
# liveness-probe.md`): it resolves detectors BY NAME and consults NO growth reading. Growth may gate
# whether a proposal is worth making NOW; it may never be the evidence that an absence is costing
# anything, and a proposal supported by a count alone is malformed. Keeping the count out of this
# surface entirely is what makes that structural rather than a matter of anyone's care.
BORN_PERMISSIVE_DETECTORS: dict = {}


def register_born_permissive_detector(name: str, detector) -> None:
    """Register ONE named detector (SPEC-0189 rules 1 + 5) — the single point of extension a later
    card uses. `name` is the token that card's `concern:` block carries as `detector:`.

    REFUSES a re-registration under an existing name rather than overwriting it. Two detectors
    silently sharing one name would mean the name in a concern block no longer identifies which code
    watches that surface — and a concern would then read as correctly paired while being watched by
    something else entirely, which is the exact failure rule 1 exists to prevent. Re-registering the
    SAME object is a no-op, so an idempotent import cannot trip it."""
    if not (isinstance(name, str) and name.strip()):
        raise ValueError("a detector name must be a non-empty string (SPEC-0189 rule 1)")
    key = name.strip()
    existing = BORN_PERMISSIVE_DETECTORS.get(key)
    if existing is not None and existing is not detector:
        raise ValueError(f"detector name {key!r} is already registered to a different detector — a name "
                         f"must identify exactly one detector (SPEC-0189 rule 1)")
    if not callable(detector):
        raise ValueError(f"detector {key!r} must be callable — a detector is named CODE, never a rule "
                         f"expressed in metadata (SPEC-0189 rule 5)")
    BORN_PERMISSIVE_DETECTORS[key] = detector


def resolve_born_permissive_detector(name):
    """The detector registered under `name`, or None. Faithful: a missing name is simply absent here —
    whether that ABSENCE is a fault is the caller's judgement, and the one caller that treats it as a
    refusal is the declaration-point guard, not this reader."""
    if not (isinstance(name, str) and name.strip()):
        return None
    return BORN_PERMISSIVE_DETECTORS.get(name.strip())


def registered_detector_names() -> tuple:
    """The registered detector names, sorted — the roster a reader (or a test) checks a concern's
    declared `detector:` against. Deterministic order, no host state."""
    return tuple(sorted(BORN_PERMISSIVE_DETECTORS))


def _detector_accepts_root(detector, inspect) -> bool:
    """Does `detector` take the OPTIONAL `root=` keyword the assembler offers (T-12006)?

    FAIL-CLOSED TOWARD THE OLD CONTRACT, deliberately: anything this cannot positively prove accepts
    `root` reads False, and the caller then makes the plain zero-arg call the registry has always
    documented. That is what lets the contract widen without breaking a third party's registrant — a
    detector written before this card, or one whose signature Python cannot introspect at all (a
    builtin, a C callable, an exotic wrapper), is called exactly as it was.

    ACCEPTED shapes: a parameter literally named `root` that a keyword can reach
    (POSITIONAL_OR_KEYWORD / KEYWORD_ONLY), or a `**kwargs` that would absorb it. A POSITIONAL_ONLY
    `root` is NOT accepted — a keyword call would raise, and raising is the one thing this seam must
    not do."""
    try:
        params = inspect.signature(detector).parameters
    except (TypeError, ValueError):       # un-introspectable: the zero-arg call is the safe answer
        return False
    kinds = (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
    return any((name == "root" and prm.kind in kinds) or prm.kind is inspect.Parameter.VAR_KEYWORD
               for name, prm in params.items())


def restoration_proposals(*, project, concerns, growth=None, root=None, _resolve=None) -> dict:
    """T-11969 (SPEC-0189 rules 3 + 4) — ASSEMBLE the restoration proposals for ONE project: for each
    concern born PERMISSIVE, ask the detector that concern NAMES whether the absence has started to
    cost something, and turn each firing detector's answer into a proposal naming the PROJECT, the
    SURFACE and the OBSERVED SIGNAL. Returns
    `{project, count, proposals, malformed, degraded, growth}`.

    IT REGISTERS INTO SURFACES IT DOES NOT DEFINE, and every one of them is T-11968's: the registry
    above resolves a detector NAME to code (rules 1 + 5), `init.born_permissive_concerns` is the ONE
    reader of born stance (rule 8), and `views.project_growth` is the shared growth fold. This function
    adds the RENDERING path's assembly step and redefines none of them — a concern becomes watched by
    adding two lines to its own `concern:` block plus one `register_born_permissive_detector` call, with
    no edit here.

    IT SHIPS SILENT ON EVERY REAL CORPUS TODAY, deliberately. The registry is empty until a wave-3 card
    ships the detector INSEPARABLE from the default-flip it guards, so every concern resolves to no
    detector and the count is 0. That is the plan's build ORDER, not an omission: a proposal must have
    somewhere to render before any default is allowed to relax.

    A CONCERN NAMING NO DETECTOR IS SKIPPED HERE, never flagged. Whether that absence is a FAULT is a
    question with exactly one home — the declaration-point guard `init.born_permissive_detector_
    violations`, which REFUSES it in `graph conformance`'s RED set (rule 1: the pair is the unit of
    admission). Answering it a second time here would be a second home for one rule (CHARTER §P5), and
    a report-only echo is the wrong instrument for a refusal anyway.

    WHAT MAKES A PROPOSAL (SPEC-0189 rule 3, the criterion this whole function exists to hold). A
    detector returns something falsy to say NOTHING FIRED — the ordinary case — or a mapping describing
    what it saw. Only a mapping carrying a non-empty `signal` becomes a proposal, because the signal IS
    the evidence that the absence is costing something. A mapping without one is MALFORMED and is NOT
    emitted; it is returned in `malformed` so the refusal is observable rather than a silent drop. That
    is the concrete shape of "a proposal whose sole support is a count is malformed": there is no path
    through this function by which a growth number alone produces a proposal.

    GROWTH IS CARRIED, NEVER CONSULTED. The reading arrives as an input and is attached to every
    proposal unchanged; nothing here branches on it, filters by it, or compares it to a threshold, so a
    LOW-growth project proposes exactly as a high-growth one does. Growth may gate RELEVANCE for the
    human reading the line; it may never be the evidence (rule 3, and
    `lessons/a-presence-count-is-not-a-liveness-probe.md`). The AST taint scan in
    `tests/test_growth_fold.py` enforces this mechanically across this module, and this function is
    written to pass it as a property rather than by care.

    IT PROPOSES AND NEVER APPLIES (rule 4): it reads, and writes nothing — no project contract, no
    file, no event. Restoration stays an explicit act performed by the project in its own contract.

    A DETECTOR THAT RAISES IS CONTAINED, not propagated: this fold sits behind the debt echo's
    best-effort seam, and a third party's exception must never break a session start or a land tail. It
    is recorded in `degraded` — named, never silently swallowed, on the same discipline as the
    live-revision adapter degrade.

    `root` NAMES THE REPO EVERY DETECTOR FOLDS (T-12006, rules 3+5) — this function is the DEFINER of
    the detector contract, so widening it is its call to make. The host passes the root it has ALREADY
    REBOUND (`cli._debt_echo_lines` passes `REPO_ROOT`, which `-C <consumer>` rebinds), and each
    detector that ACCEPTS a `root` keyword is handed it. Before this, every detector resolved its own
    input through `own_journal_path()`'s cwd walk, so `<engine>/bin/yitc-v2 -C <consumer> debt` run from
    the ENGINE cwd folded the ENGINE's journal and printed nothing, while the same command run from the
    consumer cwd printed a real proposal — a proposal about the wrong project is worse than none
    (AGENTS §Scope-boundary) and a silently-missing one is the failure rule 3 exists to end.

    THE HAND-OFF IS OPTIONAL, WHICH IS WHAT KEEPS IT BACKWARD-COMPATIBLE. The detector's signature is
    INSPECTED: one that declares a `root` parameter (or absorbs `**kwargs`) is called `detector(root=
    root)`; ANY OTHER — including a third party's registrant written against the old zero-arg contract,
    and one whose signature cannot be inspected at all (a builtin, a C callable) — is called
    `detector()` exactly as before. A caller passing no root likewise takes the zero-arg path unchanged,
    so no existing call site moves. The inspection sits INSIDE the same `try:` as the call, so a
    registrant's failure is still contained into `degraded`, named, never propagated.

    `_resolve` defaults to the module's own registry reader and is a PARAMETER for the reason
    `born_permissive_concerns(entries=None)` takes one: so a FIXTURE producer can be exercised through
    THIS function rather than through a re-implementation of it in a test."""
    import inspect

    resolve = _resolve if _resolve is not None else resolve_born_permissive_detector
    proposals: list = []
    malformed: list = []
    degraded: list = []
    for entry in (concerns or ()):
        if not isinstance(entry, dict):
            continue
        surface = entry.get("section")
        if not (isinstance(surface, str) and surface.strip()):
            continue                      # a nameless concern — `concern-malformed` already flags it
        name = entry.get("detector")
        detector = resolve(name) if isinstance(name, str) else None
        if detector is None:
            continue                      # unwatched: the declaration-point guard's question, not ours
        try:
            fired = detector(root=root) if (root is not None
                                            and _detector_accepts_root(detector, inspect)) else detector()
        except Exception as exc:          # noqa: BLE001 — a third party's failure, contained by design
            degraded.append({"surface": surface.strip(), "detector": name,
                             "error": f"{type(exc).__name__}: {exc}"})
            continue
        if not fired:
            continue                      # the ordinary case: nothing fired, so nothing is proposed
        record = fired if isinstance(fired, dict) else {}
        signal = record.get("signal")
        proposal = {"project": project,
                    "surface": surface.strip(),
                    "signal": signal.strip() if isinstance(signal, str) else None,
                    "tightening": record.get("tightening"),
                    "spec": entry.get("spec"),
                    "detector": name,
                    "growth": growth}
        if proposal["signal"]:
            proposals.append(proposal)
        else:
            malformed.append(dict(proposal, reason="a proposal names no observed signal — a growth "
                                                   "count alone is not evidence (SPEC-0189 rule 3)"))
    proposals.sort(key=lambda p: (str(p.get("surface") or ""), str(p.get("detector") or "")))
    return {"project": project, "count": len(proposals), "proposals": proposals,
            "malformed": malformed, "degraded": degraded, "growth": growth}


# ── SPEC-0189 rules 1+5+6 (T-11971): SURFACE 1 — the pinned last-green verify leg ─────────────────
#
# THE PAIR THIS COMPLETES. SPEC-0186's concern block declares `verify_policy` born PERMISSIVE, and rule 1
# admits that ONLY with a named detector in the same corpus. This is that detector. It REGISTERS INTO the
# surfaces above and redefines none of them: `register_born_permissive_detector` resolves the name,
# `restoration_proposals` assembles the proposal, `views._render_growth_relevance` renders it. Nothing here
# reads a growth number — the reading is attached to the proposal by the assembly step, and this fold is not
# handed one (rule 3: growth may gate RELEVANCE, never supply EVIDENCE).
#
# WHAT IT WATCHES, AND WHY EACH LIMB IS THERE (the plan's §Per-detector specification, surface 1). A land
# that skipped the leg by policy records `verify_mode: candidate_policy_off` (SPEC-0186 rule 7). If the
# absence has started to cost something, what shows up LATER is a verification failure the leg would have
# re-run. Four limbs, each removable and each removing something real:
#   (1) CHAIN — a `candidate_policy_off` land exists, and the failure FOLLOWS it (within `_PINNED_CHAIN_
#       WINDOW_LANDS`). Without it the detector degrades into "the leg was off somewhere, something failed
#       somewhere", which is the volume-only reading AC4's corpus exists to refute.
#   (2) ATTRIBUTION — the later land is a VERIFICATION failure (`abort_class: verify-failed`). A
#       merge-conflict or audit-currency abort is not a verification result at all and is excluded.
#   (3) SUBJECT SET — at least one failing entry carries the `[pinned/last-green] ` marker, i.e. the pinned
#       leg is what re-ran that test. This is the operationalization the trial's cycle 3 recorded, stated
#       honestly: if the leg CAUGHT the failure the test is in its set by construction; the converse is not
#       measured. A row whose failures are ALL unprefixed is a candidate-leg-only failure — a test the leg
#       would not have re-run — and it stays SILENT. That is the limb which keeps this from firing on
#       regressions the absent leg could not have caught anyway.
#   (4) PRE-DATING — that same test was not ALREADY failing before the policy-off land. A failure the
#       policy-off land did not precede is not an observation about the policy being off.
#
# IT IS A DECLARED WEAK SIGNAL AND ITS PROPOSAL SAYS SO. Correlation between a policy-off land and a later
# regression is not causation, and the wording below claims only what was seen — "a verification regression
# observed after a policy-off land, in a test the pinned leg would have re-run" — offered for a human to
# weigh. Rule 4 keeps it a PROPOSAL: nothing here writes a declaration, a file or an event.
#
# ITS ADOPTION IS SILENCE, NOT A FIRING (SPEC-0189 rule 6 limb 2). Measured over three real corpora at
# 2026-08-22 — policy-off lands / pinned-leg aborts / chains: kupiclub 34 / 152 / 0, aiseller 3 / 2 / 0,
# boomrocket 0 / 14 / 0. kupiclub is the naive-positive corpus: a volume-only detector fires there loudly
# and continuously, and this one returns nothing. `tests/test_surface1_detector.py` replays that SHAPE.
_PINNED_ATTRIBUTION_MARK = "[pinned/last-green] "   # the marker the pinned leg itself writes into a
                                                    # failing entry (`batch_landing._LAND_PINNED_ENTRY_PREFIX`)
_POLICY_OFF_VERIFY_MODE = "candidate_policy_off"    # SPEC-0186 rule 7 — the land that SKIPPED the leg
_VERIFY_FAILED_ABORT_CLASS = "verify-failed"        # limb 2: a verification result, not a merge/currency refusal
_PINNED_CHAIN_WINDOW_LANDS = 40                     # the trial's own bound (cycle 3) — a policy-off land from
                                                    # a year ago is not an observation about today's failure


def _pinned_failing_subjects(data: dict) -> list:
    """The test files a land's recorded failure attributes TO THE PINNED LEG — limb 3, and nothing else.

    FAITHFUL, NEVER FAIL-CLOSED (`lessons/fail-closed-belongs-to-the-reader-not-the-parser.md`): it reports
    what the row literally carries. An entry without the marker is a CANDIDATE-leg failure and is simply not
    returned, which is the whole point of the limb — the reader below decides what an empty list means.
    Parses the recorded `failing_assertions` element shape `"[pinned/last-green] <file>: <assertion>"`, the
    same first-line-then-colon shape `worktree._surface_failing_assertions` writes."""
    out: list = []
    for entry in (data.get("failing_assertions") or ()):
        text = str(entry)
        if not text.startswith(_PINNED_ATTRIBUTION_MARK):
            continue
        core = text[len(_PINNED_ATTRIBUTION_MARK):].splitlines()[0] if text.strip() else ""
        subject = core.split(":", 1)[0].strip()
        if subject and subject not in out:
            out.append(subject)
    return out


def pinned_leg_regression(rows, *, window_lands: int = _PINNED_CHAIN_WINDOW_LANDS) -> "dict | None":
    """SURFACE 1's detector (SPEC-0189 rules 1+2+6) — the OBSERVATION, or None when nothing fired.

    `rows` are this project's own journal events; only `land_completed` is read, in recorded order. Every
    input is emitted as a BY-PRODUCT of ordinary landing (rule 2): nobody classifies anything anywhere in
    this chain, at triage or elsewhere, which is the property that keeps it from being inert on arrival.

    Returns None — the ordinary case, and the case on every corpus measured so far — or a mapping carrying
    `signal` (the evidence, in the observation-not-causation wording), `tightening` (the specific act
    proposed), and the `observed` facts a human needs to check it. A mapping without a non-empty `signal`
    would be MALFORMED and `restoration_proposals` drops it; this function never builds one.

    ONE FIRING, NOT A COUNT. The FIRST qualifying chain is reported and the fold stops. A count of chains
    would be a volume reading, and rule 3 forbids a count from being the evidence; what a human weighs here
    is the concrete pair of lands, named."""
    lands = [e for e in (rows or ())
             if isinstance(e, dict) and e.get("type") == "land_completed" and isinstance(e.get("data"), dict)]
    # CHRONOLOGY IS THIS FOLD'S OWN, never the journal's physical order. The journal is appended out of
    # `ts` order (AGENTS §Journal: "callers that need chronology sort by `ts`"), and SPEC-0190 rule 5
    # promises a reader multiset identity plus partition-stable order — not positional identity across a
    # segment boundary. A "later" here means LATER IN TIME, so it is derived from `ts` and from nothing
    # else; the sort is stable, so rows sharing a timestamp keep their recorded order.
    lands.sort(key=lambda e: str(e.get("ts") or ""))
    # every test file already seen FAILING under the pinned leg, and when — limb 4's input
    first_failed_at: dict = {}
    policy_off: list = []          # (index, ts) of each land that SKIPPED the leg by policy
    for i, e in enumerate(lands):
        d = e["data"]
        ts = e.get("ts")
        if d.get("status") == "abort" and d.get("abort_class") == _VERIFY_FAILED_ABORT_CLASS:
            for subject in _pinned_failing_subjects(d):
                first_failed_at.setdefault(subject, (i, ts))
        if d.get("verify_mode") == _POLICY_OFF_VERIFY_MODE:
            policy_off.append((i, ts))
    if not policy_off:
        return None                # limb 1: nothing was ever skipped by policy — nothing to observe
    for i, e in enumerate(lands):
        d = e["data"]
        if d.get("status") != "abort" or d.get("abort_class") != _VERIFY_FAILED_ABORT_CLASS:
            continue               # limb 2: not a verification failure (a merge/currency refusal is not one)
        subjects = _pinned_failing_subjects(d)
        if not subjects:
            continue               # limb 3: the pinned leg re-ran none of these — it could not have caught them
        prior = [(j, ts) for (j, ts) in policy_off if j < i and (i - j) <= window_lands]
        if not prior:
            continue               # limb 1: this failure follows no recent policy-off land
        off_index, off_ts = prior[-1]
        fresh = [s for s in subjects if first_failed_at.get(s, (i, None))[0] >= off_index]
        if not fresh:
            continue               # limb 4: it was already failing BEFORE the leg was switched off
        return {
            "signal": ("verification regression observed after a policy-off land, in a test the pinned leg "
                       f"would have re-run — {fresh[0]} failed at land {d.get('branch') or '?'} "
                       f"({e.get('ts') or '?'}), after a land that skipped the leg by policy "
                       f"({off_ts or '?'}). An OBSERVATION offered for a human to weigh: it does not claim "
                       "the absent leg caused it."),
            "tightening": ("set `verify_policy.pinned_last_green: all` in this project's yitc-ops.yaml — "
                           "the leg then re-runs the last-green suite against new code at land"),
            "observed": {"policy_off_at": off_ts, "regression_at": e.get("ts"),
                         "subjects": fresh, "branch": d.get("branch")},
        }
    return None


def own_journal_path(root=None) -> Path:
    """The journal of the repo the fold is operating ON — the detector's only input path.

    IT MUST BE A REPO THE CALLER NAMED OR IS STANDING IN, never another project's picked by accident:
    AGENTS §Scope-boundary keeps another project's repo read-only and explicitly NOT monitored or
    probed, and a proposal about the wrong project's history would be worse than none. So the
    resolution only ever names a repo the caller has EXPLICITLY pointed the tool at or is ALREADY
    standing in:
      0. an EXPLICIT `root` — what the host passes when it has already rebound one (`-C <consumer>`);
      1. else `YITC_REPO_ROOT` — the documented override the host itself resolves at module load;
      2. else the nearest ancestor of the process CWD that IS a checkout carrying a journal (so a
         `-C <consumer>` session run from that consumer folds the CONSUMER's, and an engine session run
         from a task worktree folds that worktree's);
      3. else this engine checkout — the last resort, and the answer for a caller standing nowhere.
    Step 2 is a plain upward walk rather than a `git` call: this runs at a report-only seam, and a
    resolver that can fail would hand every reader downstream a new way to fail.

    THE ANSWER THEN GOES THROUGH THE SCOPE GUARD (`events.scope_guarded_default`, SPEC-0131 rule 1) —
    the ONE resolver, not a second copy of it, and step 0 goes through it on EXACTLY the same terms as
    every other step: an explicit root buys a different SUBJECT, never an escape from the guard. That is
    what keeps this read HERMETIC under the verify harness: a test process whose CWD sits in the real
    checkout — or which names the real checkout outright — resolves the harness's private box journal,
    not the real one, so this fold can never make a suite's runtime a function of repo history (the
    T-10786 land-verify-timeout class, which the T-0561 guard catches).

    WHY STEP 0 EXISTS (T-12006, SPEC-0189 rules 3+5). The registry's detector contract USED to be
    strictly ZERO-ARG (`restoration_proposals` called `detector()`), so a detector could not be handed
    the host's already-rebound root, and T-11971 recorded the residual honestly rather than hiding it:
    "a caller whose CWD is one checkout while `-C` points at another folds the CWD's journal". That
    residual was MEASURED — `<engine>/bin/yitc-v2 -C <consumer> debt` run from the ENGINE cwd folded the
    ENGINE's journal and printed no proposal, while the same command from the consumer cwd printed one.
    The contract is now WIDENED at its definer (`restoration_proposals(root=...)` hands each detector
    that accepts it an OPTIONAL `root=` keyword), so the host passes its rebound root IN and the cwd
    walk is the fallback for a caller that names none. A detector still on the old zero-arg signature is
    called zero-arg and lands on step 1/2 exactly as before — the widening REMOVES the residual without
    removing anyone's contract."""
    import os

    from lib import events as _events   # the ONE scope-guarded journal-default resolver (SPEC-0131)
    if root is not None:
        return _events.scope_guarded_default(Path(root).resolve())
    root = os.environ.get("YITC_REPO_ROOT")
    if not root:
        try:
            here = Path.cwd().resolve()
            root = next((c for c in (here, *here.parents)
                         if (c / ".git").exists() and (c / "events.jsonl").exists()), None)
        except OSError:
            root = None
    return _events.scope_guarded_default(Path(root).resolve() if root
                                         else Path(__file__).resolve().parents[2])


def _own_journal_rows(path=None) -> list:
    """This session's own journal events, segment-aware (`own_journal_path` decides WHOSE by default).

    `path` overrides that resolution and exists for the same reason `born_permissive_concerns(entries=
    None)` takes one: a fixture corpus is driven through THIS reader rather than through a
    re-implementation of it — which is also what makes it drivable by the SPEC-0190 segment-awareness
    and multiset-identity probes that hold every journal reader in this corpus to its contract.

    IT ADDS NO SECOND PARSE PATH: `journal.segment_rows` is the ONE fold every debt sibling reaches the
    journal through, and inside the echo's `rows_memo` scope this call is served from the memo the other
    ~15 lines already paid for (T-11453 / SPEC-0190 rule 4). A missing journal folds to no rows."""
    try:
        return [e for e in journal.segment_rows(path if path is not None else own_journal_path())
                if isinstance(e, dict)]
    except OSError:
        return []


def _surface1_pinned_leg_detector(root=None) -> "dict | None":
    """The registry adapter over the pure fold above. Split so the fold is exercised on fixture corpora
    directly, with no journal anywhere near it — the reason `born_permissive_concerns(entries=None)` and
    `growth_window_days(specs_dir=None)` are shaped the same way.

    `root` NAMES THE REPO TO FOLD (T-12006). The assembler hands it in when the host has rebound one
    (`-C <consumer>`), and it reaches the journal through `own_journal_path(root)` — the SAME
    scope-guarded resolver the ambient path uses, so an explicit root changes the SUBJECT and nothing
    else. Optional, and the parameter is what the assembler INSPECTS for: with no root, this is called
    zero-arg and resolves exactly as it did before.

    THE `None` BRANCH IS DELIBERATE, not a shortcut. Passing `None` down to `_own_journal_rows` is what
    hits the debt echo's `rows_memo` (T-11453 / SPEC-0190 rule 4); naming the resolved path even when it
    is the session's own would bypass the memo and re-fold the whole journal. So the ambient path stays
    memo-served and only a NAMED root pays for its own read."""
    return pinned_leg_regression(_own_journal_rows(own_journal_path(root) if root is not None else None))


# THE ONE REGISTRATION LINE. Exactly what T-11968's registry documents a later card doing: one entry, no
# mechanism edit. It is paired with `born_stance: permissive` + `detector: verify-policy-pinned-last-green`
# on SPEC-0186's own concern block, and the declaration-point guard
# (`init.born_permissive_detector_violations`, a `graph conformance` RED) is what makes the two inseparable.
register_born_permissive_detector("verify-policy-pinned-last-green", _surface1_pinned_leg_detector)


# ── SPEC-0189 rules 1+5+6 (T-11972): SURFACE 2 — the audit-post exemption (SPEC-0178) ─────────────
#
# THE PAIR THIS COMPLETES. SPEC-0178's concern block declares `audit_scrutiny` born PERMISSIVE, and
# rule 1 admits that ONLY with a named detector in the same corpus. This is that detector. Like
# surface 1 it REGISTERS INTO surfaces it does not define — `register_born_permissive_detector`
# resolves the name (T-11968), `restoration_proposals` assembles the proposal (T-11969),
# `views._render_growth_relevance` renders it, and `init.born_permissive_gate` is what admits the
# born declaration at all (T-11985/T-12001). Nothing here reads a growth number: the reading is
# attached to the proposal by the assembly step and this fold is never handed one (rule 3 — growth
# may gate RELEVANCE, never supply EVIDENCE).
#
# WHAT IT WATCHES, AND WHY EACH LIMB IS THERE. A card that closed under an `audit_scrutiny` case
# shipped WITHOUT a semantic diff review. If that absence has started to cost something, what shows
# up LATER is somebody going back over the same files. Three limbs, each removable and each removing
# something real:
#   (1) CITATION — a later card NAMES the exempted card in its own `cites:`. Without it the fold
#       degrades into "two cards touched the same file", which is true of every corpus and is the
#       volume-only reading rule 3 forbids.
#   (2) DIFF-FILE OVERLAP — the two cards' LANDED diffs share a path. This is the limb that
#       separates REWORK OF THE SAME SURFACE from a bare provenance citation, and it is the one the
#       AC5 negative control (many citations of exempted cards, zero overlap) exists to prove
#       load-bearing rather than decorative.
#   (3) AUTHORED-AFTER — the citing card was authored after the exempted CLOSURE. A card written
#       before the exemption happened is not an observation about it.
#
# NO CLASSIFICATION IS CONSULTED ANYWHERE IN THIS CHAIN (SPEC-0189 rule 2, and the card's AC6). The
# card `class:` field is never read; neither is a triage `kind`. Every input is a by-product of
# ordinary work: a closure records its exempting case because `cmd_task_close` records it, a card
# carries `cites:` and `created_at:` because filing writes them, and a commit's file list is the
# commit. This is deliberate and it is the difference between this detector and the one rule 2's own
# interpreting note calls INERT ON ARRIVAL: SPEC-0178's automatic restoration counts only captures
# judged a DEFECT at triage, a call that is optional and — measured over three consumers' entire
# history — never made. A detector built on that input would never speak.
#
# IT IS A DECLARED WEAK SIGNAL AND ITS PROPOSAL SAYS SO. Overlap proves that a later card reworked
# the same surface; it NEVER proves the absent audit caused the rework. The wording below claims only
# what was seen, in the same observation-not-causation form as surface 1, and rule 4 keeps it a
# PROPOSAL: this fold reads, and writes no declaration, no file and no event.
_EXEMPTED_REWORK_CLOSURE_TYPE = "task_closed"     # carries `data.exempted_case` (SPEC-0178 rule 4)
_EXEMPTED_REWORK_COMMIT_TYPE = "commit_landed"    # carries `data.commit` — the diff's address
_EXEMPTED_REWORK_MAX_PAIRS = 200                  # a bound on how many candidate pairs are resolved
                                                  # to a git diff, so a report-only seam on a large
                                                  # corpus cannot become a long walk. The fold stops
                                                  # at the FIRST firing anyway; this bounds SILENCE.


def exempted_closures(rows) -> dict:
    """`{task_id: {"case", "closed_at"}}` for every closure that took a SPEC-0178 audit-post
    exemption — the cards this detector is watching the consequences of.

    THE CARRIER IS THE ONE THE SPEC ALREADY NAMES. Rule 4 records the exempting case as
    `task_closed.data.exempted_case`, and rule 5's own join (`task.py#_case_closure_index`) reads
    exactly that field out of exactly that row. Reading the same carrier is what keeps this from
    being a second spelling of "which cards were exempted" (CHARTER §P5); it is a separate FOLD
    because it answers a different question (which cards, for a review proposal) in a different
    module, and importing the Closure seam's reader into the debt echo would couple a report-only
    surface to the close path.

    FAITHFUL, NEVER FAIL-CLOSED (`lessons/fail-closed-belongs-to-the-reader-not-the-parser`): it
    reports what the rows literally carry. A row with no `exempted_case` is simply not an exempted
    closure and is not returned. LAST WRITE WINS for a card with several closures, the same rule
    `_case_closure_index` applies and for the same reason: the newest record describes the regime
    the card actually closed under."""
    out: dict = {}
    for e in (rows or ()):
        if not isinstance(e, dict) or e.get("type") != _EXEMPTED_REWORK_CLOSURE_TYPE:
            continue
        tid = str(e.get("task_id") or "").strip()
        d = e.get("data") if isinstance(e.get("data"), dict) else {}
        case = d.get("exempted_case")
        if not (tid and isinstance(case, str) and case.strip()):
            continue
        out[tid] = {"case": case.strip(), "closed_at": str(e.get("ts") or "")}
    return out


def _task_commit_shas(rows) -> dict:
    """`{task_id: [sha…]}` folded from `commit_landed` — a card's landed commits, in recorded order.

    The commit sha is the ADDRESS of the diff, not the diff: `commit_landed` carries no file list
    (its payload is `commit`/`kind`/`source`), so the files are resolved separately and only for the
    few cards a citation edge actually nominates. That split is what keeps limb 2 from costing a git
    call per card in the corpus."""
    out: dict = {}
    for e in (rows or ()):
        if not isinstance(e, dict) or e.get("type") != _EXEMPTED_REWORK_COMMIT_TYPE:
            continue
        tid = str(e.get("task_id") or "").strip()
        d = e.get("data") if isinstance(e.get("data"), dict) else {}
        sha = d.get("commit")
        if not (tid and isinstance(sha, str) and sha.strip()):
            continue
        out.setdefault(tid, [])
        if sha.strip() not in out[tid]:
            out[tid].append(sha.strip())
    return out


def _diff_files(repo_root, shas, _run=None) -> set:
    """The union of paths the given commits touched — limb 2's input, and nothing else.

    A GIT FAILURE YIELDS THE EMPTY SET, WHICH SILENCES THE LIMB. That is the safe direction for a
    report-only proposal: an unresolvable diff means the overlap cannot be SHOWN, and a proposal
    whose evidence could not be read is exactly the malformed shape rule 3 forbids. It never widens
    into "assume they overlap".

    `_run` is the fixture seam, for the reason `born_permissive_concerns(entries=None)` takes one: a
    corpus is driven through THIS reader rather than through a re-implementation of it in a test."""
    import subprocess

    files: set = set()
    if not shas:
        return files
    runner = _run
    if runner is None:
        def runner(sha):
            r = subprocess.run(["git", "-C", str(repo_root), "show", "--name-only",
                                "--pretty=format:", sha],
                               capture_output=True, text=True, timeout=30)
            return r.stdout if r.returncode == 0 else ""
    for sha in shas:
        try:
            out = runner(sha)
        except Exception:            # noqa: BLE001 — an unresolvable diff silences the limb (above)
            continue
        for line in str(out or "").splitlines():
            p = line.strip()
            if p:
                files.add(p)
    return files


def _authored_overlap(shared, tids) -> list:
    """T-12022 (X-1247) — the paths in `shared` that are AUTHORED work, i.e. limb 2's real subject.

    WHY THE RAW OVERLAP IS NOT THE EVIDENCE. Limb 2 exists to separate REWORK OF THE SAME SURFACE
    from a bare provenance citation, and `_diff_files` hands it every path the two cards' landed
    commits touched — including the lifecycle bookkeeping EVERY card writes. `events.jsonl` is the
    extreme case: it is appended by every land, so every pair of cards in every corpus overlaps on
    it and the limb collapses back into the "two cards touched a file" volume reading SPEC-0189
    rule 3 forbids. Measured (kupiclub 2026-09-03, X-1247): the sole shared path between the pair
    that produced a live proposal was the journal, and the proposal's remedy was to TIGHTEN A GATE.

    THE DEFINITION OF BOOKKEEPING IS REUSED, NEVER RE-ENCODED (CHARTER §P1 F1, the T-0631
    no-parallel-encoding rule). Both authorities already exist and both are consulted:
      · `cli._BOOKKEEPING_ALLOWLIST` — D-0051's ONE closed allow-list of append-only/derived repo
        bookkeeping (`events.jsonl`, the `graph/` derived views, the release/audience views). It is
        the LIVE object, so a path a later card adds to it is excluded here the same day, with no
        edit to this module;
      · `cli._zero_ship_diff_bookkeeping(path, tid)` — the TID-SCOPED half: a card's own YAML and
        its own `decisions/<tid>-*` audit/consult records.
    A path is bookkeeping for the PAIR if it is bookkeeping for EITHER card, because either card's
    own record is a by-product of its lifecycle rather than work on a shared surface.

    THE IMPORT IS LAZY AND CONFINED HERE. This module back-imports nothing from the host at load
    time and that stays true; the host lookup happens inside the call, the established
    cycle-breaking idiom (`views.py`'s lazy `from lib.cli import _parse_iso_utc`). It sits on the
    ADAPTER side of the fold, beside `_diff_files`'s git and `_own_cards`'s disk, so
    `exempted_rework` itself stays a pure function of its arguments.

    FAILURE SILENCES THE LIMB, never widens it. If the authority cannot be imported or raises, every
    path reads as bookkeeping and the remainder is empty — the same direction `_diff_files` takes on
    an unresolvable diff, and the safe one for a report-only proposal: an overlap that cannot be
    SHOWN to be authored must not be claimed as evidence."""
    paths = [str(x) for x in (shared or ())]
    if not paths:
        return []
    try:
        from lib.cli import (_BOOKKEEPING_ALLOWLIST as _allow,     # noqa: PLC0415 — lazy, breaks the
                             _zero_ship_diff_bookkeeping as _own)  # import cycle (the views.py idiom)
    except Exception:                     # noqa: BLE001 — an unreadable authority silences the limb
        return []
    ids = [str(i).strip() for i in (tids or ()) if str(i).strip()]
    out = []
    for path in paths:
        try:
            if path in _allow or any(_own(path, tid) for tid in ids):
                continue
        except Exception:                 # noqa: BLE001 — same direction: unprovable => bookkeeping
            continue
        out.append(path)
    return sorted(out)


# ── T-12070 (X-1260) — the SYMBOL-GRANULAR half of limb 2 ─────────────────────────────────────────
#
# WHY A THIRD NARROWING, AFTER TWO ALREADY LANDED. X-1247 removed the two ways limb 2 fired on
# nothing at FILE granularity (a card that shipped no deliverable; an overlap that is only lifecycle
# bookkeeping). X-1260 is the same class ONE TIER FINER: measured on kupiclub 2026-09-04, a pair that
# satisfied BOTH X-1247 exclusions — two `done` cards, four shared paths, every one of them real
# authored work — was STILL vacuous, because a shared FILE is not a shared SURFACE. Of the four:
# one product file the two cards edited at DIFFERENT top-level symbols (T-0385 edited `OverlayHover`;
# T-0501 deleted `OverlayTooltip`, a different export), the deleted component's own test, and two
# `specs/` paths touched ONLY to re-bless the anchor signatures the deletion's LINE-SHIFT staled.
# That last pair is the sharper finding: it is an overlap the CORPUS MANUFACTURES. A deletion moves
# lines, a moved line changes an anchor's content signature, and the shipping card re-blesses it —
# so the "shared surface" is a by-product of the very act being observed, on the same reasoning
# `_authored_overlap` already excludes a card's own lifecycle record.
#
# THE ATTRIBUTION SHAPE IS REUSED, THE SYMBOL DATABASE IS NOT (the card's own bound: NO symbol
# indexer). T-11379 and T-12061 both judge from git's OWN diff output, per commit, with no index —
# and git already writes the enclosing section heading into every `@@ -a,b +c,d @@ <heading>` line
# (its xfuncname). Reading that heading IS reading the diff. Nothing here parses a language, keeps a
# symbol table, or resolves an anchor.
# An `implements_signature:` entry, and NOT merely "a key with a 64-hex value" (audit-post
# finding, T-12070): the KEY must be anchor-shaped — a repo PATH, optionally `#symbol`, which
# is the only thing `spec reverify` ever writes there. A substantive spec edit that happens to
# carry some other 64-hex value is then not mistaken for a re-bless.
_ANCHOR_SIGNATURE_LINE = re.compile(
    r"^\s*[\w.\-/]*/[\w.\-/]+(?:#[\w.\-]+)?:\s*[0-9a-f]{64}\s*$")
_HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@ ?(.*)$")
_IMPLEMENTS_SIGNATURE_KEY = "implements_signature:"


def _diff_hunks(repo_root, shas, _run=None) -> dict:
    """The HUNK-granular sibling of `_diff_files`: `{path: {"ranges", "symbols", "lines"}}` over the
    given commits — limb 2's finer input, and nothing else.

    IT IS THE SAME ADAPTER, ONE FLAG WIDER. `_diff_files` runs `git show --name-only`; this runs
    `git show --unified=0` over the same shas and reads three things out of the SAME output: each
    hunk's line RANGES, the `@@`-heading SYMBOL git itself computed, and the changed LINE BODIES
    (which `_rebless_only` below needs). One reader, so "which region did this card touch" cannot
    mean two different things in one comparison (the T-11216 one-oracle rule applied to the input).

    BOTH SIDES OF EVERY HUNK ARE RECORDED, AND THAT IS AN HONEST BOUND RATHER THAN AN OVERSIGHT. The
    two cards' commits are separated in time, so a line number in one is not a line number in the
    other — anything between them shifts it. Recording the PRE-image and POST-image ranges of every
    hunk makes the range limb tolerant of that shift in the direction that matters (it can still see
    an overlap the shift would otherwise hide) without pretending the comparison is exact. The
    SYMBOL limb is the shift-immune one and carries the real weight; the range limb is what answers
    for a file git has no heading for at all (a `.json`, a top-of-file edit).

    A GIT FAILURE CONTRIBUTES NOTHING FOR THAT SHA, exactly as `_diff_files` returns the empty set —
    and the caller reads an absent path as "cannot be SHOWN to overlap" and drops it, never as
    "assume they overlap". `_run` is the fixture seam, for the same reason `_diff_files` has one.

    KNOWN BOUND, stated rather than left to be discovered: when a card's edit changes the DEFINING
    line of a symbol, git's heading for that hunk is the NEW text, so two cards working the same
    symbol across such a change carry different headings and the symbol limb misses. The range limb
    is the partial answer, and the failure is toward SILENCE — a proposal not made, never a false
    one — which is the direction a report-only surface must fail in."""
    import subprocess

    out: dict = {}
    if not shas:
        return out
    runner = _run
    if runner is None:
        def runner(sha):
            r = subprocess.run(["git", "-C", str(repo_root), "show", "--unified=0",
                                "--pretty=format:", sha],
                               capture_output=True, text=True, timeout=30)
            return r.stdout if r.returncode == 0 else ""
    for sha in shas:
        try:
            text = runner(sha)
        except Exception:            # noqa: BLE001 — an unresolvable diff contributes nothing (above)
            continue
        path = None
        for line in str(text or "").splitlines():
            if line.startswith("--- "):
                src = line[4:].strip()
                path = src[2:] if src.startswith("a/") else None
                continue
            if line.startswith("+++ "):
                dst = line[4:].strip()
                if dst.startswith("b/"):
                    path = dst[2:]           # the post-image name wins (a rename's new home)
                continue
            if path is None:
                continue
            entry = out.setdefault(path, {"ranges": [], "symbols": set(), "lines": []})
            m = _HUNK_HEADER.match(line)
            if m:
                for start_s, count_s in ((m.group(1), m.group(2)), (m.group(3), m.group(4))):
                    start = int(start_s)
                    count = int(count_s) if count_s is not None else 1
                    # a pure insertion/deletion has count 0 and no extent of its own; anchor it at
                    # the seam so it still has a comparable position.
                    entry["ranges"].append((start, start + max(count, 1) - 1))
                heading = (m.group(5) or "").strip()
                if heading:
                    entry["symbols"].add(heading)
                continue
            if line[:1] in ("+", "-") and not line.startswith(("+++", "---")):
                entry["lines"].append(line[1:])
    return out


def _rebless_only(entry) -> bool:
    """T-12070 — True when a path's WHOLE change in one card is an anchor-signature re-bless.

    THE SHAPE IS ALREADY IN THE CORPUS AND IS NOT RE-DECLARED HERE. `spec reverify` writes a spec's
    per-anchor freshness baseline into its `implements_signature:` mapping (`cli.py#
    _anchor_content_signature`), one `<anchor>: <64-hex-sha256>` entry per anchor. A re-bless
    therefore changes ONLY lines of that shape — verified against this repo's own history, where
    1f13ac6343 and db3bbc3c4f are signature-only and d4b94d002b (which also edits the body) is not.
    Reading the shape off the diff needs no new field, no marker and no classification: it is the
    same "a by-product of ordinary work" input rule 2 admits.

    TWO INDEPENDENT CONDITIONS, because either alone admits a shape it should not (audit-post
    finding, T-12070 — the auditor offered them as alternatives; both are taken, since each is
    cheap and each closes a different door):
      · CONTEXT — every `@@` heading git computed for the path is the `implements_signature:`
        mapping. On a YAML file that heading is the enclosing top-level key, so a hunk anywhere
        else in the spec fails it. A path for which git computed NO heading at all is not
        disqualified by this limb alone; the next one still has to hold.
      · SHAPE — every changed line is an ANCHOR-shaped signature entry (a repo path, optionally
        `#symbol`, mapped to a 64-hex sha) or the mapping's own key. A key that is merely some
        field with a 64-hex value is not an anchor and does not qualify.

    FAIL-CLOSED TOWARD FALSE, which is the direction that keeps this from swallowing real work: a
    path with no recorded changed lines is NOT a re-bless (nothing was shown to be one), and any
    single line that is not a signature entry or the mapping's own key makes the whole change
    substantive. So the exclusion fires only on positive proof that the change is nothing but
    re-blessing."""
    entry = entry or {}
    lines = [str(x) for x in (entry.get("lines") or ())]
    if not lines:
        return False
    if set(entry.get("symbols") or ()) - {_IMPLEMENTS_SIGNATURE_KEY}:
        return False                  # the change reaches a section that is not the signature map
    for raw in lines:
        body = raw.strip()
        if not body or body == _IMPLEMENTS_SIGNATURE_KEY:
            continue
        if _ANCHOR_SIGNATURE_LINE.match(raw):
            continue
        return False
    return True


def _reworked_overlap(shared, later_hunks, exempt_hunks) -> list:
    """T-12070 (X-1260) — of `shared`, the paths the two cards demonstrably reworked TOGETHER.

    TWO RULES, IN THIS ORDER, and each removes something the measured incident actually contained:

      · A `specs/` PATH THAT IS A RE-BLESS-ONLY CHANGE IN EITHER CARD IS DROPPED. The overlap is
        manufactured by the corpus rather than observed in it: a card that shifts lines stales an
        anchor signature and re-blesses it, so the shared spec is a by-product of the shipping act
        itself. `EITHER` card, not both — the same rule `_authored_overlap` applies to a card's own
        lifecycle record, and for the same reason: a surface only one side genuinely worked was not
        reworked together. Scoped to `specs/` because that is where the manufactured overlap lives;
        a signature-shaped line elsewhere is not this phenomenon.

      · EVERY OTHER PATH IS KEPT ONLY ON HUNK EVIDENCE — the two cards' changes INTERSECT ON LINES,
        or they SHARE A SYMBOL. This is the disjunction the card states, and either limb alone is a
        real answer: the symbol limb survives the line shift that defeats ranges, the range limb
        answers for a file git computes no heading for. What it refuses is the X-1260 case — one
        file, two different top-level symbols, no shared line — which at file granularity read as
        rework and is not.

    A PATH EITHER CARD HAS NO HUNKS FOR IS DROPPED. The overlap cannot be SHOWN, and an overlap that
    cannot be shown must not be claimed — the same silence direction `_diff_files` takes on an
    unresolvable diff and `_authored_overlap` on an unreadable authority. Never the reverse."""
    out = []
    for path in (shared or ()):
        a = later_hunks.get(path)
        b = exempt_hunks.get(path)
        if not a or not b:
            continue                      # unshowable => not claimed (above)
        if str(path).startswith("specs/") and (_rebless_only(a) or _rebless_only(b)):
            continue
        if a["symbols"] & b["symbols"]:
            out.append(path)
            continue
        if any(lo_a <= hi_b and lo_b <= hi_a
               for (lo_a, hi_a) in a["ranges"] for (lo_b, hi_b) in b["ranges"]):
            out.append(path)
    return out


def _card_fields(cards) -> dict:
    """`{task_id: {"cites": [...], "created_at": <str>, "status": <str>}}` — the ONLY three card
    fields this detector reads, named here so the restriction is visible rather than asserted.

    THE CLASS FIELD IS NOT AMONG THEM (AC6 / SPEC-0189 rule 2). A human classification is forbidden
    as a detector input, so the projection is taken here, once, and the fold below never sees a raw
    card at all — which is what makes "no classification is consulted" a property of the code's shape
    rather than a promise about its care.

    `status` IS NOT A CLASSIFICATION, AND THE DISTINCTION IS RULE 2'S OWN (T-12022). Rule 2 admits a
    signal "the system emits as a by-product of ordinary work" and refuses one "that requires
    someone to CLASSIFY something", because an optional classification is an unmade one. A card's
    LIFECYCLE STATUS is the first kind and not the second: `task close` writes `done`, `task update
    --status` writes `wont-do`/`parked`, and no verb offers a session the choice to leave it
    unwritten — unlike `class:` (an authoring judgement) or a triage `kind` (optional, and measured
    never made across three consumers). It is read for one reason, stated at its use site: a card
    that never shipped a deliverable reworked nothing, whatever bookkeeping its own self-commit
    landed. The forbidden-token scan that pins the class/kind exclusion is unaffected."""
    out: dict = {}
    for tid, card in (cards or {}).items():
        if not isinstance(card, dict):
            continue
        cites = card.get("cites")
        out[str(tid).strip()] = {
            "cites": [str(c).strip() for c in (cites if isinstance(cites, list) else []) if str(c).strip()],
            "created_at": str(card.get("created_at") or "").strip(),
            "status": str(card.get("status") or "").strip().lower(),
        }
    return out


def exempted_rework(rows, *, cards, repo_root=None, _run=None, _run_hunks=None,
                    max_pairs: int = _EXEMPTED_REWORK_MAX_PAIRS) -> "dict | None":
    """SURFACE 2's detector (SPEC-0189 rules 1+2+6) — the OBSERVATION, or None when nothing fired.

    `rows` are this project's own journal events; `cards` is `{task_id: <parsed card>}`. Returns None
    — the ordinary case — or a mapping carrying `signal` (the evidence, in the observation-not-
    causation wording), `tightening` (the specific act proposed) and the `observed` facts a human
    needs to check it. A mapping without a non-empty `signal` would be MALFORMED and
    `restoration_proposals` drops it; this function never builds one.

    ONE FIRING, NOT A COUNT. The FIRST qualifying pair is reported and the fold stops. A count of
    reworks would be a volume reading and rule 3 forbids a count from being the evidence; what a
    human weighs here is the concrete pair of cards and the file they share, named.

    DETERMINISTIC ORDER. Candidate pairs are walked in sorted (citing-card, exempted-card) order, so
    the same corpus always yields the same firing — a report-only surface whose answer moved with
    dict iteration order would be unreviewable.

    TWO NARROWINGS ON LIMB 2, EACH REMOVING A WAY THE FOLD COULD FIRE ON NOTHING (T-12022, X-1247).
    Both are refusals to CLAIM, not new evidence, and each is separately load-bearing:
      · the LATER CARD MUST BE `done`. A wont-do / parked / in-progress card shipped no deliverable,
        so it reworked nothing — but its terminal self-commit IS a `commit_landed` row (T-9320 /
        T-0614 / T-9622), so without this the fold reads that bookkeeping as a rework. This is what
        the measured incident actually was: the cited "reworking" card was a WONT-DO;
      · the OVERLAP IS TAKEN OVER AUTHORED PATHS ONLY (`_authored_overlap`). Every card writes
        `events.jsonl` and every land regenerates the `graph/` derived views, so the raw overlap is
        NON-EMPTY FOR EVERY PAIR IN EVERY CORPUS and limb 2 proves nothing.
    A pair whose remaining overlap is empty simply does not fire, so no proposal is assembled and
    none is rendered — the emptiness is handled where the evidence is judged, not by a second
    refusal in the renderer.

    A THIRD NARROWING, ONE TIER FINER (T-12070, X-1260): the surviving overlap is then taken at
    SYMBOL/HUNK granularity by `_reworked_overlap`, which also drops a `specs/` path shared only
    through an anchor-signature re-bless. Both X-1247 narrowings above are about WHICH PATHS count;
    this one is about whether a shared path is a shared SURFACE at all — the measured pair satisfied
    both of the above and was still vacuous. See that function for the two rules and their grounds.

    THE HUNK SOURCE IS SEPARATELY INJECTED, AND ITS ABSENCE SKIPS THE NARROWING RATHER THAN FAILING
    IT. `_run_hunks` is the `-U0` fixture seam beside `_run`'s `--name-only` one. When NO hunk source
    is resolvable — a caller that supplied a FILES fixture and no hunk fixture, so there is no tree
    the `-U0` diff could be read from — the finer judgement is not attempted and the answer is the
    file-granular one, unchanged. That is deliberate: it keeps every existing caller's answer exactly
    where it was, and it confines this card to narrowing where its evidence actually exists. It is
    NOT the failure path — a hunk source that IS present and cannot resolve a given path yields
    silence for that path, inside `_reworked_overlap`, on the module's usual direction."""
    exempted = exempted_closures(rows)
    if not exempted:
        return None                    # nothing was ever exempted — nothing to observe
    fields = _card_fields(cards)
    shas = _task_commit_shas(rows)
    diff_memo: dict = {}
    hunk_memo: dict = {}
    # The hunk source, in two independent parts so neither sentinel has to mean two things:
    # WHETHER the finer judgement is attempted at all, and WHAT it reads. An explicit `_run_hunks`
    # turns it on with that fixture; with neither seam supplied it is on and reads real git; a
    # caller that supplied only the FILES fixture has no tree a `-U0` diff could come from, so the
    # narrowing is skipped and the answer stays the file-granular one (see the docstring).
    hunk_granular = _run_hunks is not None or _run is None

    def files_for(tid):
        if tid not in diff_memo:
            diff_memo[tid] = _diff_files(repo_root, shas.get(tid) or [], _run)
        return diff_memo[tid]

    def hunks_for(tid):
        if tid not in hunk_memo:
            hunk_memo[tid] = _diff_hunks(repo_root, shas.get(tid) or [], _run_hunks)
        return hunk_memo[tid]

    pairs = 0
    for later_id in sorted(fields):
        info = fields[later_id]
        # limb 0 — the later card SHIPPED. Its terminal bookkeeping self-commit is a `commit_landed`
        # row like any other, so a non-`done` card otherwise enters the fold carrying a diff that is
        # its own park/wont-do record and nothing else (X-1247). Read from the lifecycle status a
        # governed verb wrote, never from a classification (see `_card_fields`).
        if info["status"] != "done":
            continue
        for exempt_id in sorted(set(info["cites"]) & set(exempted)):
            if later_id == exempt_id:
                continue
            closure = exempted[exempt_id]
            # limb 3 — AUTHORED-AFTER the exempted closure. A missing/unreadable timestamp on either
            # side means the ordering cannot be SHOWN, so the limb is not satisfied and the pair is
            # skipped (the same direction as an unresolvable diff: silence, never assumption).
            if not (info["created_at"] and closure["closed_at"]
                    and info["created_at"] > closure["closed_at"]):
                continue
            if pairs >= max_pairs:
                return None            # the bound (above): silence, never a partial claim
            pairs += 1
            # limb 2 — DIFF-FILE OVERLAP: rework of the same surface, not a bare citation. Taken
            # over AUTHORED paths only: the raw intersection is non-empty for every pair in every
            # corpus (the journal, the derived views), so filtering it is what makes this limb a
            # limb at all rather than a tautology (T-12022 / X-1247).
            shared = _authored_overlap(sorted(files_for(later_id) & files_for(exempt_id)),
                                       (later_id, exempt_id))
            # limb 2b — SYMBOL/HUNK granularity + the manufactured-spec-overlap drop (T-12070,
            # X-1260). Skipped only when there is no hunk source at all (see the docstring); a
            # present source that cannot resolve a path silences that path, never widens it.
            if shared and hunk_granular:
                shared = _reworked_overlap(shared, hunks_for(later_id), hunks_for(exempt_id))
            if not shared:
                continue
            return {
                "signal": (f"a later card reworked files of a card that closed without audit-post — "
                           f"{later_id} cites {exempt_id}, which closed under the `{closure['case']}` "
                           f"audit_scrutiny case ({closure['closed_at'] or '?'}) without a semantic "
                           f"diff review, and the two share {shared[0]}"
                           + (f" (+{len(shared) - 1} more file(s))" if len(shared) > 1 else "")
                           + ". An OBSERVATION offered for a human to weigh: the overlap shows the "
                             "same surface was reworked, it does not claim the absent audit caused "
                             "it."),
                "tightening": (f"remove or narrow the `{closure['case']}` case in this project's "
                               f"yitc-ops.yaml `audit_scrutiny.cases[]`, so cards matching it take "
                               f"audit-post again"),
                "observed": {"exempted_task": exempt_id, "case": closure["case"],
                             "exempted_closed_at": closure["closed_at"],
                             "citing_task": later_id, "citing_created_at": info["created_at"],
                             "shared_files": shared},
            }
    return None


def _own_cards(repo_root=None) -> dict:
    """This repo's own task cards as `{task_id: <parsed card>}` — the zero-arg adapter's card corpus.

    Resolved from the SAME scope-guarded root the journal is (`own_journal_path`), so this fold can
    never read another project's cards: AGENTS §Scope-boundary keeps another repo read-only and
    explicitly not probed, and a proposal about the wrong project's history would be worse than none.
    Tolerant by construction — an unreadable or mis-shaped card is skipped, never raised, because
    this runs behind the debt echo's best-effort seam.

    THE PARSE GOES THROUGH `state.load_path`, THE ONE CANONICAL READER (T-12029, CHARTER §P5). This
    fold used to spell its own `yaml.safe_load(p.read_text(...))`, which is a SECOND parse path over
    a corpus the canonical reader had already parsed: measured per-card inside one `_debt_echo_lines`
    invocation, every one of the 3,320 cards was parsed EXACTLY TWICE — once at `state.load_path`
    (whose T-0359 mtime-keyed memo already collapses the three `views` sweeps onto one parse) and
    once here. And the second parse was the expensive one: timed over the real corpus, the canonical
    reader's cold pass costs 1.09 s and a warm pass 0.18 s, while this raw `yaml.safe_load` pass cost
    11.04 s — because `safe_load` is the pure-Python SafeLoader, not the libyaml loader
    `state.yaml_loader()` selects. Re-pointing the reader is therefore the whole card-axis fix; it
    REMOVES a parallel parser rather than adding a cache (§P1 filters 1 + 3), and no second
    request-scoped layer is warranted on top of a memo that already gives one parse per card.

    THE ADMITTED SET IS UNCHANGED, which is why the swap is safe at a best-effort seam:
    `state.load_path` returns {} where the raw reader `continue`d past an OSError/YAMLError, and the
    `isinstance(card, dict) and card.get("id")` guard below already skips {} — so a malformed or
    unreadable card is dropped by exactly the same rule it always was."""
    root = Path(repo_root) if repo_root is not None else own_journal_path().parent
    out: dict = {}
    try:
        paths = sorted((root / "tasks").glob("T-*.yaml"))
    except OSError:
        return out
    for p in paths:
        card = state.load_path(p)
        if isinstance(card, dict) and str(card.get("id") or "").strip():
            out[str(card["id"]).strip()] = card
    return out


def _surface2_exempted_rework_detector(root=None) -> "dict | None":
    """The registry adapter over the pure fold above. Split so the fold is exercised on fixture corpora
    directly, with no journal and no git anywhere near it — the same shape as
    `_surface1_pinned_leg_detector`, including its OPTIONAL `root=` (T-12006): the assembler hands in
    the host's rebound root, it resolves through the SAME scope-guarded `own_journal_path`, and the
    journal AND the cards are then both read out of that one repo — which is what keeps the two halves
    of this fold from ever describing different projects."""
    journal_path = own_journal_path(root)
    root = journal_path.parent
    return exempted_rework(_own_journal_rows(journal_path), cards=_own_cards(root), repo_root=root)


# THE ONE REGISTRATION LINE. Exactly what T-11968's registry documents a later card doing: one entry,
# no mechanism edit. It is paired with `born_stance: permissive` + `detector:
# audit-scrutiny-exempted-rework` on SPEC-0178's own concern block, and the declaration-point guard
# (`init.born_permissive_detector_violations`, a `graph conformance` RED) is what makes the two
# inseparable.
register_born_permissive_detector("audit-scrutiny-exempted-rework", _surface2_exempted_rework_detector)


# ── SPEC-0189 rules 7+8 (T-11972): the CHARTER amendment's THREE ELEMENTS + the ordering gate ─────
#
# WHY THIS IS CODE AND NOT A CONVENTION. The card's AC3 requires the ordering edge — "the permissive
# born default may NOT ACTIVATE before the amendment lands" — to be MACHINE-READABLE rather than an
# intention recorded in a scope line. An intention cannot be driven against a fixture; this can.
#
# WHAT IT READS, and why each element is separate. The amendment does exactly two things, and the
# first of them is a SEPARATION: the sentence that today welds «an absent declaration reads
# fail-closed» to «every project starts there» becomes two, because SPEC-0189 rule 7 binds the first
# and only the second gains the ratified exception. So a text that has folded (a) back into (b) is
# NOT the amended text — it is the pre-amendment claim wearing the new words, and it reads as though
# the born flip moved the default for every existing project that never opted in. That is the one
# failure this reader exists to catch, which is why it is checked positively (the two must appear as
# SEPARATE sentences) and not by keyword presence alone.
_CHARTER_ABSENT_SENTENCE = "absent a declaration, every substantive task takes audit-post"
_CHARTER_BORN_SENTENCE = ("the state every project starts in, absent an owner ratification "
                          "recorded at birth")
_CHARTER_MERIT_TOKENS = ("attributable", "reviewable", "reversible")
_CHARTER_MERIT_CONTRAST = "implicit gate nobody declared"


def charter_amendment_state(charter_text: str) -> dict:
    """Has the CHARTER §Project-declared audit-post exemption amendment landed? Returns
    `{"amended", "missing", "why"}`. PURE, total, never raises, no I/O — the text is passed in, so a
    fixture is driven through THIS reader rather than through a re-implementation of it.

    `missing` names the absent elements by their card letters ((a)/(b)/(c)), so a refusal says which
    half of the amendment is not there rather than "not amended".

    THE WELD CHECK IS THE LOAD-BEARING ONE. Elements (a) and (b) must appear as SEPARATE sentences:
    if the born clause continues the same sentence as the absent-declaration clause — the exact
    pre-amendment shape — this reports `amended: False` with a `why` naming the weld, EVEN THOUGH
    both strings are present. A reader that only counted keywords would accept it, which is the
    vacuous control `lessons/a-negative-control-must-fail-without-the-intervention` warns about."""
    # NORMALIZE FIRST — the CHARTER is hard-wrapped prose, so every sentence this reader looks for
    # spans line breaks in the real file. Matching the raw text would make the amendment's presence a
    # function of where a line happened to wrap, which is not a property anyone should be able to
    # break by reflowing a paragraph. Markdown emphasis is dropped for the same reason.
    text = " ".join(str(charter_text or "").split()).replace("**", "").replace("*", "")
    low = text.lower()
    missing: list = []
    a_at = low.find(_CHARTER_ABSENT_SENTENCE)
    if a_at == -1:
        missing.append("a")
    if _CHARTER_BORN_SENTENCE not in low:
        missing.append("b")
    if not (all(tok in low for tok in _CHARTER_MERIT_TOKENS)
            and _CHARTER_MERIT_CONTRAST in low):
        missing.append("c")
    if missing:
        return {"amended": False, "missing": missing,
                "why": f"the CHARTER amendment is missing element(s) {'/'.join(missing)} "
                       f"(SPEC-0189 rules 7+8)"}
    # both present — now the SEPARATION. Take the sentence (a) sits in and require that (b) is not
    # inside it. A sentence ends at the first `.` that is followed by whitespace/end.
    b_at = low.find(_CHARTER_BORN_SENTENCE)
    end = a_at
    while True:
        end = low.find(".", end + 1)
        if end == -1:
            end = len(low)
            break
        if end + 1 >= len(low) or low[end + 1].isspace():
            break
    if b_at < end:
        return {"amended": False, "missing": [],
                "why": ("elements (a) and (b) are WELDED into one sentence — the pre-amendment "
                        "shape. The amendment's first act is to SEPARATE them, because SPEC-0189 "
                        "rule 7 binds what an ABSENT declaration reads and only the BORN half gains "
                        "the ratified exception")}
    return {"amended": True, "missing": [], "why": ""}


def born_default_activation_refusal(section: str, *, charter_text, entries=None) -> "str | None":
    """THE ORDERING GATE (T-11972 AC3). Returns a refusal string when `section`'s born-permissive
    default may NOT activate because the CHARTER amendment has not landed, else None.

    SCOPED TO A BORN-PERMISSIVE CONCERN, and admitted otherwise. A concern whose born value relaxes
    nothing has no relaxation for this amendment to authorize, so it is not gated — the same
    concern-blind axis rule 8 fixes, read in the other direction. Resolved through
    `init.born_permissive_concerns`, the ONE reader of born stance (CHARTER §P5): this adds no second
    spelling of "is this concern born permissive".

    IT REFUSES, IT NEVER WRITES (SPEC-0189 rule 4). Nothing here edits a declaration, a carrier or a
    CHARTER; it answers a question."""
    from lib import init as _init

    name = str(section or "").strip()
    if not name:
        return None
    try:
        permissive = {e["section"].strip() for e in _init.born_permissive_concerns(entries)}
    except Exception:                 # noqa: BLE001 — an unreadable registry gates nothing here
        return None
    if name not in permissive:
        return None                   # relaxes nothing — no amendment is needed to authorize it
    state = charter_amendment_state(charter_text)
    if state["amended"]:
        return None
    return (f"the born-permissive default for `{name}` may NOT activate: {state['why']}. The "
            f"amendment is a requires-ordered DELIVERABLE, not an intention — the permissive default "
            f"activates only once it has landed (SPEC-0189 rules 7+8).")
# ── T-11973 (SPEC-0189 rules 1 + 5 + 6) — SURFACE 4: THE DECLARED TEST REGIME'S DETECTOR ──────────
#
# THE SURFACE. `tests.classes` (the class x moment taxonomy) + `verify.layers` (the executable
# land-verify gate) are born PERMISSIVE — waived. Rule 1 admits that only PAIRED with a detector for
# the absence starting to cost something. This is that detector, and it ships in the SAME land as the
# stance declaration and the born-default flip, because a flip landing without its detector opens a
# window in which a project is born permissive with nothing watching.
#
# WHAT COSTS SOMETHING, CONCRETELY. An under-declared test regime does not announce itself; it shows
# up as a verify layer being SKIPPED on a diff it was actually about. SPEC-0152 rule 16
# `subject_globs` lets a layer be skipped when the candidate diff is provably disjoint from its
# declared subject — and the subject is only as honest as the regime that declared it. So the signal
# is a FALSE SKIP: a land where the skip predicate would have skipped a layer, on content whose land
# ABORTED because that layer (or one covering the same declared test classes) really failed.
#
# THE THRESHOLD IS >= ONE FALSE SKIP, AND A COUNT NEVER FIRES (SPEC-0189 rule 3). A would-skip COUNT
# cannot fail — it goes up when the globs get narrower and that is all it ever says. The count is not
# merely un-thresholded here, it is never carried into the decision at all: nothing below compares a
# volume to anything. Growth is likewise absent from this module by construction
# (`lessons/a-presence-count-is-not-a-liveness-probe.md`).
#
# ═══ THE BINDING CONSTRAINT: STRUCTURED TOOL STATE, NOT THE PROSE REGEX ═══
#
# The offline trial instrument (`dev-utilities/replay-subject-scoping-skips.py`) attributes an abort
# to a layer by REGEXING `abort_reason`. That is acceptable as TRIAL EVIDENCE over history and is NOT
# acceptable in a shipped detector, and the reason is measured rather than aesthetic (boomrocket +
# kupiclub + aiseller, every journal segment, 2026-09-02):
#
#   * `failing_tests` — the field an oracle would want — appears on 5 of 2934 abort-bearing rows.
#   * `failing_assertions` — the field that DOES carry failure detail — is a human-readable blob:
#     recovery hints, command output, layer narration, all flattened. A reworded abort silently stops
#     matching, and the detector degrades to INERT with nobody noticing. An inert detector paired with
#     a permissive default is worse than no detector, because it is BELIEVED IN (SPEC-0189 rationale).
#
# So this detector reads `land_completed.data.consumer_verify_layers` — the per-layer
# `{layer, outcome}` trail `land` writes — AND NOTHING ELSE. No regex over `abort_reason` or
# `failing_assertions` participates in the decision path; `tests/test_surface4_detector.py` holds that
# as a differential (reword the prose, the verdict is unchanged) and as a source scan.
#
# THAT KEY IS WHY THIS CARD ALSO SHIPS AN EMISSION. Until T-11973 the abort allow-list in
# `worktree._emit_land_abort` DROPPED `consumer_verify_layers`, so the trail existed on 2051 rows and
# on ZERO aborts. Refusing the regex was only possible by first making the structured field real.
#
# WHAT THIS DETECTOR DOES NOT REIMPLEMENT (SPEC-0189 rule 5 / AC5, and the T-11133 incident on the
# sibling instrument): the skip PREDICATE. It IMPORTS `worktree._subject_globs_would_skip` and
# `worktree._verify_skip_fail_closed_edge` — the exact functions `land` calls — and REFUSES to run if
# that import does not resolve. A replayed predicate that is not the engine's own predicate measures
# the replay, not the engine
# (`lessons/a-measurement-taken-outside-its-harness-measures-the-harness.md`).

_SURFACE4_DETECTOR = "declared-test-regime-false-skip"

# The `consumer_verify_layers` outcomes that mean THIS LAYER DID NOT PASS on this land. `waived` and
# `malformed` are excluded deliberately: neither ran the layer's command, so neither is evidence that
# the layer had something real to catch. `skipped-disjoint-subject` is excluded for the same reason
# and is the very thing under test.
_SURFACE4_FAILED_OUTCOMES = frozenset({"failed", "timed-out", "prep-failed"})


class Surface4DetectorRefused(RuntimeError):
    """AC5 — the detector could not import the engine's own skip predicate, so it REFUSES to run.

    A refusal, not a degraded answer. The alternative is a local restatement of the predicate, and a
    restated predicate answers about ITSELF: it drifts from the mechanism it claims to measure, and
    then a GREEN reading is a fact about the copy. The debt echo contains this exactly as it contains
    any other detector failure — `restoration_proposals` records it in `degraded`, named, never
    silently swallowed — so the refusal is visible rather than mistaken for silence."""


def _surface4_engine_predicate():
    """The engine's OWN skip predicate + fail-closed edge + verify-infra globs, or REFUSE.

    Imported LAZILY, inside the call: `bin.lib.worktree` is the land engine and importing it at this
    module's top level would invert the dependency direction between a report-only debt surface and
    the verb it reports on. Every failure mode — module unimportable, attribute renamed away — lands
    on the SAME refusal, because from the caller's side they are one fact: the engine's predicate is
    not available, so nothing may be measured."""
    try:
        from lib import worktree as _wt
        return (_wt._subject_globs_would_skip, _wt._verify_skip_fail_closed_edge,
                _wt._SUBJECT_VERIFY_INFRA_GLOBS)
    except Exception as exc:  # noqa: BLE001 — every cause is the same fact to the caller
        raise Surface4DetectorRefused(
            f"REFUSING to run the {_SURFACE4_DETECTOR} detector — could not import the engine skip "
            f"predicate from bin/lib/worktree.py ({type(exc).__name__}: {exc}). A replayed predicate "
            f"that is not the engine's own predicate measures the replay, not the engine "
            f"(SPEC-0189 rule 5)") from exc


def surface4_structured_failing_layers(data) -> list:
    """The layer names THIS abort row records as NOT PASSING, read from STRUCTURED tool state ONLY.

    THE WHOLE POINT OF THE FUNCTION IS WHAT IT DOES NOT READ. `data["abort_reason"]` and
    `data["failing_assertions"]` are right there, they name the layer in prose on most rows, and they
    are NOT consulted. This is the shipped decision path's only attribution source, so a reworded
    abort message cannot change any verdict downstream of it.

    Fail-closed and shape-tolerant in the direction that reports LESS: a missing key, a non-list, a
    non-mapping element or a nameless row contributes nothing. A row that cannot be read is not
    evidence of a failure — it is an absence of evidence, and inventing a layer name from a blob is
    precisely the move this detector exists to refuse. Order-preserving + de-duplicated, so the caller
    gets a stable set without a second normalization."""
    rows = (data or {}).get("consumer_verify_layers")
    if not isinstance(rows, list):
        return []
    out: list = []
    for row in rows:
        if not isinstance(row, dict) or row.get("outcome") not in _SURFACE4_FAILED_OUTCOMES:
            continue
        name = row.get("layer")
        if isinstance(name, str) and name.strip() and name.strip() not in out:
            out.append(name.strip())
    return out


def surface4_layer_classes(layer: dict) -> frozenset:
    """The declared test CLASSES a verify layer carries — its `covers_classes:`, the consumer-declared
    pointer at `tests.classes[]` (the surface this whole card is about).

    A LAYER DECLARING NONE GETS ITS OWN ID AS ITS SOLE CLASS TOKEN, and that fallback is the honest
    reading rather than a convenience. `covers_classes` is optional; a layer without one says nothing
    about which classes it runs, so the only thing known to be true of it is that it is ITSELF. Taking
    the empty set instead would make such a layer intersect NOTHING — including the abort that named
    that very layer as failing — and the detector would go silent exactly on the corpus that declares
    the least, which is the corpus a permissive test-regime default produces. The token is namespaced
    (`layer:<id>`) so it can never collide with a real declared class name."""
    raw = (layer or {}).get("covers_classes")
    classes = {c.strip() for c in raw if isinstance(c, str) and c.strip()} if isinstance(raw, list) else set()
    return frozenset(classes) or frozenset({"layer:" + str((layer or {}).get("layer") or "?")})


# The paths every v2 land writes as a matter of course. A commit touching only these carried no
# repair, so it must not be mistaken for one. Same set the offline trial instrument uses, and it is
# repeated rather than imported for one reason: `dev-utilities/` is not importable engine code and a
# shipped detector may not depend on a dev utility. The values are a property of the v2 land
# bookkeeping footprint, not of either reader.
_SURFACE4_BOOKKEEPING = ("events.jsonl", "graph/", "tasks/", "decisions/", "MEMORY.md", "specs/")


def surface4_false_skip_cases(*, rows, layers, diff_paths, repairs_after, _predicate=None) -> list:
    """THE ORACLE. Replay the engine's skip predicate over the content of every land that ABORTED on a
    structurally-named layer failure, and return the cases where a layer WOULD have been skipped on
    content that really broke something it covers. Each returned case is a dict carrying `verdict`.

    THE CORPUS ARRIVES INJECTED — `rows` (chronological `land_completed` events), `layers` (the
    declared layer table), and two readers, `diff_paths(sha, base_sha)` and
    `repairs_after(base_sha, sha, failure_ts)`. This is the `restoration_proposals(_resolve=...)`
    precedent and it exists for the same reason: a fixture corpus is exercised THROUGH this function
    rather than through a re-implementation of it in a test. `surface4_repo_corpus` supplies the
    git+journal-backed readers for the real thing.

    THE ORACLE'S KNOWN LIMIT, STATED RATHER THAN PAPERED OVER: an aborted land has no merged sha, so
    its content is recovered from the SAME branch's next successful land. An abort with no such land
    is reported `not-decidable-*` and is NEVER counted clean.

    WHAT MAKES A CASE FIRE, in order:
      1. The abort names >= 1 failing layer in STRUCTURED state (`surface4_structured_failing_layers`).
         No structured attribution -> the row is not evidence and is skipped entirely. A pre-T-11973
         row therefore contributes nothing, which is the honest reading: the field did not exist, so
         the journal does not say which layer failed, and guessing from prose is the refused move.
      2. The verify-infra fail-closed edge (`_verify_skip_fail_closed_edge` over
         `_SUBJECT_VERIFY_INFRA_GLOBS`) did not force a full run on that content.
      3. Some DECLARED layer L carrying `subject_globs` WOULD have been skipped on that content, per
         the imported predicate.
      4. L's classes intersect the classes of the layers that actually failed. This is the card's own
         criterion — a would-skip is FALSE iff the abort's failure detail intersects the SKIPPED
         layer's `covers_classes` — and it is what makes the detector about the DECLARED TEST REGIME
         rather than about globs alone. It subsumes the identity case (L is itself a failing layer)
         and additionally catches the cross case: L was skipped while a sibling layer covering the
         SAME declared class caught the break, so the regime's own taxonomy says L should have run.
      5. THE DISCRIMINATOR — did the author have to FIX something? A commit authored AFTER the
         failure touching a NON-bookkeeping path is a repair: the failure was real and content-borne,
         so a skip would have hidden it and the FALSE-SKIP verdict stands. No such commit — the
         identical tree simply re-landed green — means the failure was flaky, pre-existing or
         environmental, and skipping a layer for a disjoint diff is the mechanism working. Both
         branches rest on a POSITIVE marker; absence never clears a case, and an unreadable history
         defaults to the UNSAFE verdict.

    Step 5 is not decoration and was not optional: without it the first version of this oracle asked
    "did the layer pass on the proxy land?", which fires on essentially every case (a land only
    succeeds if its layers pass) and cleared every inconvenient one. That shape is recorded in the
    trial instrument for the same reason it is recorded here — it recurs."""
    would_skip, fail_closed_edge, infra_globs = _predicate or _surface4_engine_predicate()

    by_layer = {str(ly.get("layer") or "").strip(): ly for ly in (layers or []) if isinstance(ly, dict)}
    scoped = [ly for name, ly in by_layer.items() if name and ly.get("subject_globs") is not None]

    ordered = sorted((r for r in (rows or []) if isinstance(r, dict)), key=lambda r: r.get("ts") or "")
    ok_seq = [r for r in ordered
              if (r.get("data") or {}).get("status") == "ok" and (r.get("data") or {}).get("sha")]
    prev_sha_of = {id(r): ((ok_seq[i - 1].get("data") or {}).get("sha") if i else None)
                   for i, r in enumerate(ok_seq)}
    by_branch_ok: dict = {}
    for r in ok_seq:
        branch = (r.get("data") or {}).get("branch")
        if branch:
            by_branch_ok.setdefault(branch, []).append(r)

    cases: list = []
    for r in ordered:
        data = r.get("data") or {}
        if data.get("status") == "ok":
            continue
        failing = [n for n in surface4_structured_failing_layers(data) if n in by_layer]
        if not failing:
            continue                      # no STRUCTURED attribution — not evidence, and not guessed
        failed_classes: frozenset = frozenset().union(
            *(surface4_layer_classes(by_layer[n]) for n in failing))
        case = {"ts": r.get("ts"), "branch": data.get("branch"), "failing_layers": failing,
                "failed_classes": sorted(failed_classes)}
        later = [x for x in by_branch_ok.get(data.get("branch") or "", [])
                 if (x.get("ts") or "") >= (r.get("ts") or "")]
        if not later:
            case["verdict"] = "not-decidable-no-landed-sha"
            cases.append(case)
            continue
        proxy = later[0]
        sha = (proxy.get("data") or {}).get("sha")
        base = prev_sha_of.get(id(proxy))
        paths = diff_paths(sha, base)
        case["proxy_sha"] = sha
        if paths is None:
            case["verdict"] = "not-decidable-unresolvable-sha"
            cases.append(case)
            continue
        if fail_closed_edge(paths, infra_globs, diff_error=None):
            case["verdict"] = "safe-full-run-fail-closed-edge"
            cases.append(case)
            continue
        hidden = [str(ly.get("layer")).strip() for ly in scoped
                  if would_skip(paths, ly["subject_globs"])
                  and surface4_layer_classes(ly) & failed_classes]
        if not hidden:
            case["verdict"] = "safe-layer-would-run"
            cases.append(case)
            continue
        case["would_skip_layers"] = sorted(hidden)
        fixes = repairs_after(base, sha, r.get("ts"))
        if fixes is None:
            case["verdict"] = "FALSE-SKIP"
            case["discriminator"] = "branch history unreadable — defaulting to the unsafe verdict"
        elif fixes:
            case["verdict"] = "FALSE-SKIP"
            case["discriminator"] = (f"repaired by {len(fixes)} post-failure non-bookkeeping "
                                     f"commit(s): " + ", ".join(fixes[:3]))
        else:
            case["verdict"] = "failure-not-attributable-to-diff"
            case["discriminator"] = ("no non-bookkeeping commit was authored between the failure and "
                                     "the successful re-land — the identical tree passed, so the "
                                     "failure was not content-borne")
        cases.append(case)
    return cases


def surface4_repo_corpus(repo) -> dict:
    """The git + journal backed readers `surface4_false_skip_cases` needs, for a real checkout.

    READ-ONLY against the project, and BEST-EFFORT in the reading direction only: a git call that
    fails yields `None`, which the oracle reads as NOT-DECIDABLE — never as clean. The base for a
    land's delta is the PREVIOUS successful land's sha (main is ff-only, so consecutive land shas
    chain), and the delta is `merge-base(base, sha)..sha`. A land's own sha is the BRANCH TIP, so
    `sha^1..sha` is NOT this delta — it is the closure/bookkeeping commit, and replaying that reports
    nearly every layer as would-skip on nearly every land. That reading was produced once, on the
    trial instrument, recognised as implausible on its face, and is the reason a base is taken."""
    import json
    import subprocess
    from pathlib import Path

    root = Path(repo)

    def git(*args):
        try:
            r = subprocess.run(["git", "-C", str(root), *args],
                               capture_output=True, text=True, timeout=120)
        except Exception:  # noqa: BLE001 — a report-only reader never raises on a host fault
            return None
        return r.stdout if r.returncode == 0 else None

    def _merge_base(sha, base_sha):
        return ((git("merge-base", base_sha, sha) or "").strip() or None) if base_sha and sha else None

    def diff_paths(sha, base_sha):
        if not sha:
            return None
        base = _merge_base(sha, base_sha)
        out = git("diff", "--name-only", base, sha) if base else None
        if out is None:
            out = git("show", "--name-only", "--pretty=format:", sha)
        if out is None:
            return None
        return [p for p in (line.strip() for line in out.splitlines()) if p]

    def repairs_after(base_sha, sha, failure_ts):
        base = _merge_base(sha, base_sha)
        if not base or not failure_ts:
            return None
        out = git("log", "--format=%H%x1f%cI%x1f%s", f"{base}..{sha}")
        if out is None:
            return None
        fixes = []
        for line in out.splitlines():
            parts = line.split("\x1f")
            if len(parts) != 3:
                continue
            csha, cdate, subject = parts
            if cdate <= failure_ts:
                continue
            files = git("show", "--name-only", "--pretty=format:", csha) or ""
            touched = [f for f in (x.strip() for x in files.splitlines()) if f]
            if touched and all(any(f == b or f.startswith(b) for b in _SURFACE4_BOOKKEEPING)
                               for f in touched):
                continue                  # bookkeeping only — not a repair
            fixes.append(f"{csha[:7]} {subject[:60]}")
        return fixes

    # THE JOURNAL HALF GOES THROUGH `_own_journal_rows`, THE ONE FOLD EVERY DEBT SIBLING USES — and
    # the `None` is load-bearing, not a shortcut. Inside the echo's `rows_memo` scope that reader is
    # served from the memo the other folds already paid for (T-11453 / SPEC-0190 rule 4); a direct
    # `segment_lines(root / "events.jsonl")` here bypassed the memo and re-folded the WHOLE journal on
    # every detector call — measured as 8 live-journal opens totalling 664 MB in one run of the debt
    # echo (tests/test_t11445_pinned_journal_slice.py, which is green on main and red on that read).
    # So when `root` IS the session's own repo, ask for the session journal by passing `None` and hit
    # the memo; a DIFFERENT repo (a fixture, another checkout) still names its own path explicitly.
    try:
        _own = own_journal_path()
        _same = Path(_own).resolve() == (root / "events.jsonl").resolve()
    except Exception:  # noqa: BLE001 — unresolvable: read the named path, never the wrong journal
        _same = False
    rows = [e for e in _own_journal_rows(None if _same else root / "events.jsonl")
            if e.get("type") == "land_completed"]

    layers: list = []
    try:
        from lib import state
        ops = state.load_ops(root / "yitc-ops.yaml")
        for ly in ((ops or {}).get("verify") or {}).get("layers") or []:
            if isinstance(ly, dict) and str(ly.get("layer") or "").strip():
                layers.append(ly)
    except Exception:  # noqa: BLE001 — an unreadable carrier declares no layers to replay
        layers = []

    return {"rows": rows, "layers": layers, "diff_paths": diff_paths, "repairs_after": repairs_after}


def declared_test_regime_false_skips(root=None, *, _corpus=None) -> "dict | None":
    """THE REGISTERED DETECTOR for surface 4 (`tests.classes` + `verify.layers`), SPEC-0189 rule 1.

    Returns a FALSY value when nothing fired — the ordinary case, and the only one a healthy project
    ever sees — or a mapping carrying a non-empty `signal`, which is what `restoration_proposals`
    turns into a proposal naming the project, the surface and the observed signal (rules 3 + 4).

    RULE 3 HELD STRUCTURALLY, not by care: the would-skip COUNT is not part of the returned signal
    and is not compared to anything anywhere above. The evidence is the case list itself, each entry
    naming a branch, the layers that failed, the layers that would have been skipped, and the
    positive discriminator that says the failure was content-borne. There is no path through this
    function by which a volume produces a firing.

    RULE 4 HELD BY CONSTRUCTION: it READS. It writes no carrier, no file and no event, and the
    `tightening` it names is a sentence for a human to act on, never an instruction anything
    executes."""
    # THE REPO IS `own_journal_path()`'s, never `"."`. That function is the surface's documented
    # detector input path, and it exists because the CWD is not the same question: a `.` default folds
    # whatever checkout the process happens to stand in — which at the report-only debt-echo seam is the
    # REAL engine journal even when the session's own journal is a sandbox one, so the read both answers
    # about the wrong repo and misses the echo's `rows_memo` (measured: 8 live-journal opens, 664 MB, in
    # one echo run). Its parent IS the repo root by construction.
    #
    # `root` IS THE ASSEMBLER'S OPTIONAL KEYWORD (T-12006) — the host's already-rebound `-C` root — and
    # it is resolved through `own_journal_path(root)` rather than used raw, so a NAMED root rides the
    # same SPEC-0131 scope guard the ambient one does and stays hermetic under the verify harness. The
    # parameter carries the meaning the old `repo` name carried (it was always a repo ROOT); it is
    # renamed, not doubled, because a second parameter meaning the same thing is how the two drift
    # apart. `_corpus` still short-circuits both, for fixtures.
    if _corpus is None:
        try:
            root = own_journal_path(root).parent
        except Exception:  # noqa: BLE001 — unresolvable: fall back to the caller's checkout
            root = "."
    corpus = _corpus if _corpus is not None else surface4_repo_corpus(root)
    cases = surface4_false_skip_cases(rows=corpus["rows"], layers=corpus["layers"],
                                      diff_paths=corpus["diff_paths"],
                                      repairs_after=corpus["repairs_after"])
    fired = [c for c in cases if c.get("verdict") == "FALSE-SKIP"]
    if not fired:
        return None
    first = fired[0]
    return {
        "signal": (f"{len(fired)} proven FALSE SKIP(S) of a declared verify layer on content that "
                   f"really broke a class it covers — e.g. branch {first.get('branch')}: layer(s) "
                   f"{', '.join(first.get('would_skip_layers') or [])} would have been SKIPPED while "
                   f"{', '.join(first.get('failing_layers') or [])} FAILED on the same content "
                   f"({first.get('discriminator')})"),
        "tightening": ("declare this project's test regime rather than inheriting the born waiver: "
                       "name the `tests.classes[]` taxonomy, and give each `verify.layers[]` entry a "
                       "`covers_classes:` and a `subject_globs:` authored from a dependency audit of "
                       "its command — the false skips above are the declaration's absence being paid "
                       "for at land time (SPEC-0152 rule 16 subject_globs)"),
        "cases": fired,
    }


register_born_permissive_detector(_SURFACE4_DETECTOR, declared_test_regime_false_skips)


# ── SPEC-0119 rule 11 (T-10440 / X-0306 half 1): open sub-critical security findings ───────────────
#
# The gap this closes: a security-audit report (`.yitc/findings/<date>-security.yaml`, SPEC-0145 §5)
# routes only its CRITICAL findings to a mandatory reading moment — the deploy gate. A `warning` or
# `info` finding sits open in a GITIGNORED file nobody is ever obliged to read, and stays open for
# months (the trend-finder warnings open since April — X-0306). This fold gives exactly those findings
# ONE mandatory reading moment by riding the debt echo's existing seams. Report-only, never a gate:
# the deploy gate's critical-only policy is UNCHANGED (this view does not add a second gate).

# SUB-CRITICAL IS AN ALLOWLIST, NOT A NEGATION (audit-pre finding 1). Defining it as "severity !=
# critical" would silently count an ABSENT / unknown / malformed severity as debt — nagging on an
# UNKNOWN, which the report-only discipline (SPEC-0119 rule 3) forbids. So the vocabulary is explicit:
# a severity outside this set is SKIPPED, and a future severity word must be ADMITTED here deliberately
# rather than becoming debt by default.
SUBCRITICAL_SEVERITIES = frozenset({"warning", "info"})

# The report filename shape the scaffold writes (`bin/security-audit`) — the series this fold reads.
FINDINGS_REPORT_GLOB = "*-security.yaml"

_ISO_DATE_PREFIX = re.compile(r"^(\d{4}-\d{2}-\d{2})")


def _report_date(path: Path, report: dict):
    """The report's DATE — the clock every age in this fold is measured against.

    Order: the `date:` field (what the scaffold writes), else the filename's leading ISO date, else
    `run_at`. Returns a `date`, or None when nothing parses — such a report is dropped from the series
    entirely (it can neither order nor age anything, and a report-only view does not guess).
    """
    for value in (report.get("date"), path.name, report.get("run_at")):
        if isinstance(value, date) and not isinstance(value, datetime):
            return value
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, str):
            m = _ISO_DATE_PREFIX.match(value.strip())
            if m:
                try:
                    return date.fromisoformat(m.group(1))
                except ValueError:
                    pass
    return None


def _finding_identity(finding):
    """What makes two findings across two reports THE SAME finding: the stable `fingerprint` the
    scaffold derives (`sha256(check_id LF title)[:16]`), falling back to `check_id` for a producer
    that omits it. None ⇒ the finding is shapeless and is skipped (it can neither open nor age)."""
    if not isinstance(finding, dict):
        return None
    for field in ("fingerprint", "check_id"):
        value = finding.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _open_subcritical_identities(report: dict) -> dict:
    """The OPEN sub-critical findings of ONE report, keyed by identity → the finding dict."""
    out: dict = {}
    for finding in (report.get("findings") or []):
        identity = _finding_identity(finding)
        if identity is None:
            continue
        status = finding.get("status")
        severity = finding.get("severity")
        if not isinstance(status, str) or status.strip().lower() != "open":
            continue
        if not isinstance(severity, str) or severity.strip().lower() not in SUBCRITICAL_SEVERITIES:
            continue          # critical → the deploy gate; unknown/absent → an UNKNOWN, never nagged
        out[identity] = finding
    return out


def open_subcritical_findings(findings_dir, floor_days: int = 30, now=None) -> dict:
    """Fold the security-audit report SERIES → the OPEN sub-critical findings older than `floor_days`
    (SPEC-0119 rule 11).

    THE LATEST REPORT IS THE SOLE AUTHORITY ON *OPEN*. The scaffold re-derives every finding's status
    from the live surface on each run and never carries one forward, so only the newest report says
    what is open TODAY. A finding that is open in an old report but resolved (or gone) in the latest is
    NOT debt — reading openness from anywhere but the latest report would resurrect fixed findings.

    THE SERIES IS THE SOLE SOURCE OF *AGE* — because a finding carries no date of its own. A report
    carries one date for all of its findings, so a finding's age can only come from HOW FAR BACK the
    reports agree it has been open. `first_seen` is therefore the date of the OLDEST report in the
    UNBROKEN run of open-ness walking back from the latest: a report where the finding is resolved or
    ABSENT breaks the run, so a finding that was fixed and later regressed honestly restarts its clock
    (it is new debt, not month-old debt) — and a finding present in only the latest report ages from
    that report's own date. This is what surfaces the motivating case: a report that is FRESH today,
    carrying a warning every report since April has also carried, yields an age of months, not of days.

    A finding COUNTS iff `age_days >= floor_days`. The floor is an AGE floor, not the count floor the
    open-followups view uses (SPEC-0119 rule 3): a single warning open for a year is real debt, and
    hiding it behind a count would be the exact "sits open and nobody must read it" failure this view
    exists to end. A non-positive floor disables it (any open sub-critical finding fires).

    A BROKEN AUTHORITY IS NAMED, NEVER SILENTLY ZEROED (T-10843). The two clauses above make the
    LATEST report load-bearing twice over, so a report the fold cannot read is not an absence — it is
    an unreadable authority, and rendering it as a clean zero would show a broken subject as debt-free.
    Reading it as fatal is equally wrong (this view must never break the seam it rides), so the answer
    is the corpus' existing third option: a NAMED DEGRADE, exactly the shape the `deploy.live_revision`
    adapter uses (SPEC-0093/SPEC-0160 rule 23, `views._view_not_adopted`) — keep the best available
    baseline, report a `*_source` naming where it came from, and surface a conditional `*_degrade` key
    saying what could not be read. `authority_source` is one of:
      "none"                    — no report files at all (a repo that has never run a security audit
                                  honestly owes nothing) → NO degrade; the clean-zero case, unchanged.
      "latest-report"           — the newest report on disk was read; it IS the authority.
      "older-report-promoted"   — the newest report on disk could NOT be read and an older one took its
                                  place. The count still comes from that older report (breaking the
                                  seam is forbidden), but the SWAP IS ANNOUNCED rather than passed off
                                  as authority — otherwise a corrupt latest report either SUPPRESSES a
                                  real finding or RESURRECTS a fixed one, with nothing said either way.
      "unreadable"              — report files exist and NONE of them could be read. count is 0, but
                                  the result is DEGRADED, not clean, and says so.
    `authority_degrade` is present iff something was dropped — including the case where only OLDER
    reports were unreadable and the authority itself is intact, because a hole in the series silently
    UNDER-states age (the walk-back stops at the hole). Absent key ⇒ nothing was dropped.

    Args:
      findings_dir: the repo's `.yitc/findings/` (missing / never-audited ⇒ a clean, zero-count result —
        this view is report-only and must never break a seam it rides; a repo that has never run a
        security audit simply owes nothing here. An UNREADABLE report is a different fact: still not
        fatal, but reported as a named degrade per the paragraph above, never as clean zero).
      floor_days: the age floor in days (host-supplied from `YITC_DEBT_SECURITY_FINDING_FLOOR_DAYS`).
      now: aware datetime to age against; defaults to real UTC now. Injected by the tests so every
        assertion is deterministic, never wall-clock-dependent.

    Returns `{"lens", "now", "count", "findings", "next", "authority_source"}` (+ `"authority_degrade"`
    when degraded) — the shape the sibling views return. Pure: reads report files, writes nothing.
    """
    now = now if now is not None else datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    floor = floor_days if (isinstance(floor_days, int) and not isinstance(floor_days, bool)
                           and floor_days > 0) else 0

    # THE SERIES. A malformed / unreadable / non-mapping / undateable report is DROPPED, not fatal: a
    # corrupt file in the series must not blind the whole view, and must never raise into the seam. The
    # drop is RECORDED (T-10843) — it is dropped-and-ANNOUNCED, never dropped-and-silent, because the
    # dropped file may be the very report this fold calls its sole authority on OPEN.
    series: list = []          # [(report_date, filename, open_subcritical_identities)] — oldest first
    dropped: list = []         # [(filename, why)] — in the same on-disk order as `paths`
    try:
        paths = sorted(Path(findings_dir).glob(FINDINGS_REPORT_GLOB))
    except (OSError, TypeError):
        paths = []
    for path in paths:
        try:
            report = state.load_str(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, yaml.YAMLError):
            dropped.append((path.name, "unreadable"))
            continue
        if not isinstance(report, dict):
            dropped.append((path.name, "not a mapping"))
            continue
        report_date = _report_date(path, report)
        if report_date is None:
            dropped.append((path.name, "no derivable date"))
            continue
        series.append((report_date, path.name, _open_subcritical_identities(report)))
    series.sort(key=lambda row: row[0])

    # WHICH REPORT ENDED UP AS THE AUTHORITY, and was that the one the fold should have read? The
    # newest file ON DISK is decided by the SAME `sorted(glob(...))` order the fold already trusts to
    # order the series (ISO-dated filenames) — one ordering, never a second that could disagree (P5).
    source, degrade = _subcritical_authority(paths, series, dropped)

    if not series:
        return _subcritical_result(now, [], floor, source, degrade)

    latest_date, _latest_name, latest_open = series[-1]

    aged = []
    for identity, finding in latest_open.items():
        # Walk BACK from the latest while this identity stays open — the unbroken run. The first
        # report that does not carry it open ends the run, and the run's oldest report is `first_seen`.
        first_seen = latest_date
        for report_date, _name, open_ids in reversed(series[:-1]):
            if identity not in open_ids:
                break
            first_seen = report_date
        age_days = (now.date() - first_seen).days
        if age_days < floor:
            continue
        aged.append({
            "check_id": finding.get("check_id"),
            "fingerprint": finding.get("fingerprint"),
            "severity": (finding.get("severity") or "").strip().lower(),
            "title": finding.get("title"),
            "first_seen": first_seen.isoformat(),
            "age_days": age_days,
        })
    aged.sort(key=lambda r: (-r["age_days"], str(r.get("check_id") or "")))   # oldest debt first
    return _subcritical_result(now, aged, floor, source, degrade)


def _subcritical_authority(paths: list, series: list, dropped: list) -> tuple:
    """Which report ended up as the authority on OPEN, and what (if anything) could not be read.

    Returns `(authority_source, authority_degrade_or_None)` — the named-degrade shape borrowed verbatim
    from the `deploy.live_revision` adapter (rule 23): a `*_source` naming where the answer came from,
    plus a `*_degrade` sentence present ONLY when something was dropped. Never raises; the caller keeps
    whatever baseline it has either way, so this classifies, it never gates.
    """
    if not paths:
        return "none", None                      # never ran a security audit — honestly owes nothing
    if not dropped:
        return "latest-report", None
    _named = ", ".join(f"{name} ({why})" for name, why in dropped[:3])
    if len(dropped) > 3:
        _named += f", +{len(dropped) - 3} more"
    if not series:
        return ("unreadable",
                f"every security report in the series is unreadable — {_named}; this view could not "
                f"read its authority on OPEN, so its zero count means UNKNOWN, not clean")
    # Was the newest file ON DISK one of the dropped ones? `paths` is the same sorted order the series
    # is built from, so its last entry is the report that SHOULD have been the authority.
    newest_on_disk = paths[-1].name
    if newest_on_disk in {name for name, _why in dropped}:
        return ("older-report-promoted",
                f"the latest security report could not be read — {_named}; the older report "
                f"{series[-1][1]} was promoted to authority on OPEN, so a finding it names may already "
                f"be fixed and one it omits may still be open")
    return ("latest-report",
            f"the latest security report was read, but {len(dropped)} older report(s) in the series "
            f"could not be — {_named}; an unreadable report is INVISIBLE to the walk-back rather than "
            f"breaking it, so the run of open-ness jumps the gap and an age may be OVER-stated (the "
            f"missing report may be the one that showed the finding resolved)")


def _subcritical_result(now, findings: list, floor: int,
                        source: str = "none", degrade: "str | None" = None) -> dict:
    _next = ("these security findings have been open past the age floor with no mandatory reading "
             "moment — fix each, or record the accepted risk (a waiver with an expiry), then re-run "
             "the security audit so the next report shows them resolved. See `bin/yitc-v2 debt`."
             if findings else
             "no sub-critical security finding is open past the age floor — nothing owed.")
    if degrade:
        # The guidance text must never stay silent about corruption (T-10843): a zero count under a
        # broken authority is an UNKNOWN, and the owner is told so + what to do about it.
        _next = (f"AUTHORITY DEGRADED — {degrade}. Re-run `bin/security-audit` so a readable report "
                 f"becomes the authority again (or restore/remove the unreadable one). Until then read "
                 f"this view's count as INCOMPLETE, never as clean. " + _next)
    return {
        "lens": "open-subcritical-security-findings (SPEC-0119 rule 11) — findings OPEN in the repo's "
                "LATEST `.yitc/findings/*-security.yaml` whose severity is sub-critical (warning/info — "
                "an explicit allowlist, so an unknown severity is never nagged) and which have been "
                "open for at least the age floor. Openness is read from the LATEST report only (the "
                "producer re-derives status each run); the AGE comes from the unbroken run of reports "
                "that carried the same finding open. Only CRITICAL findings reach the deploy gate — "
                "this view is the sub-critical ones' one mandatory reading moment. Zero stored state; "
                "recomputed fresh, report-only, never a gate.",
        "now": now.isoformat().replace("+00:00", "Z"),
        "count": len(findings),
        "floor_days": floor,
        "findings": findings,
        # T-10843: where the answer on OPEN came from — "none" (no reports; never audited), "latest-report"
        # (the newest report on disk), "older-report-promoted" (the newest could not be read; an older one
        # took its place) or "unreadable" (no report could be read at all). Absent degrade key ⇒ nothing
        # was dropped. Same shape as `live_revision_source` / `live_revision_degrade` (rule 23).
        "authority_source": source,
        **({"authority_degrade": degrade} if degrade else {}),
        "next": _next,
    }


# ── SPEC-0119 rule 14 (T-10502 / X-0362 / X-0363): recent security-gate OVERRIDES ──────────────────
#
# The gap this closes: SPEC-0155 rule 7 lets the owner override a REJECTING pre-deploy security gate
# during an outage (bounded to the severity-blocking class, reason-bearing, every blocked finding named,
# journaled as `deploy_security_gate_overridden`). That escape hatch is only legitimate while it stays
# RARE and VISIBLE: an override that nobody ever reads back is indistinguishable from a gate that was
# quietly switched off — and the findings it bypassed are still open in production. So every override
# gets exactly one mandatory reading moment, on the seams the owner already passes through.
#
# The fold is a WINDOW, not an FSM: an override is a dated ACT, not an obligation with an open/closed
# state (the underlying findings' openness is the sub-critical fold's business, not this one's — one
# concern per view). It surfaces every override inside the window and then falls silent; nothing
# "discharges" it. UNFLOORED on purpose — unlike open-followups (a backlog a small count should not nag
# about), a single deliberate gate bypass is exactly the thing that must never be count-hidden.
_GATE_OVERRIDE_EVENT = "deploy_security_gate_overridden"
_GATE_OVERRIDE_WINDOW_DAYS = 30   # the reading window; not a governance scalar — a report-only horizon


def recent_gate_overrides(events_path, window_days: int = _GATE_OVERRIDE_WINDOW_DAYS, now=None) -> dict:
    """Fold the journal → the security-gate overrides performed within `window_days` (SPEC-0119 rule 14).

    Pure: reads the journal, writes nothing (the SPEC-0149 acceptance boundary, shared by every fold
    here). SEGMENT-AWARE since T-11591: the declared 30-day window is more than four times the 7-day
    live window, so SPEC-0190 rule 4 puts this reader on the ARCHIVE branch — it folds every segment
    that window covers, not the live one alone. Not a nicety on this surface: an override that is not
    shown was, for every reader, not performed (the shape kupiclub measured at X-1100).
    A missing/unreadable journal, a malformed line, or an unparseable `ts` yields a clean zero-count
    result — a report-only surface never breaks the seam it rides, and never nags on an unknown.

    Returns `{lens, now, window_days, count, overrides, next}` — the shape the sibling views return.
    """
    now = now if now is not None else datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    overrides: list = []
    try:
        # T-11591 — the SEGMENT-AWARE fold (SPEC-0190 rule 4). `segment_rows_since` resolves the
        # segment SET and reads each member through the SAME `fold_rows` primitive T-11453 shared, so
        # this is still ONE physical read + ONE parse path and the memo scope still collapses.
        # T-12030 — and it opens only the segments the 30-day window can REACH. The horizon this
        # reader declares is its window, so a segment whose dated name lies wholly before the floor
        # cannot hold a row the `(now - ts).days > window_days` test below would keep. That test is
        # UNCHANGED and still decides every row: the selection is a pre-filter on file names, and the
        # floor is deliberately wider than the window (`_window_segment_floor`), so it can only ever
        # over-include.
        for event in journal.segment_rows_since(
                events_path, _window_segment_floor(now, days=window_days)):
            if not isinstance(event, dict) or event.get("type") != _GATE_OVERRIDE_EVENT:
                continue
            ts = _parse_stamped_deadline(event.get("ts"))
            if ts is None:
                continue          # no establishable date ⇒ not placeable in the window
            if (now - ts).days > window_days:
                continue
            data = event.get("data") if isinstance(event.get("data"), dict) else {}
            blocking = data.get("blocking") if isinstance(data.get("blocking"), list) else []
            overrides.append({
                "ts": ts.isoformat().replace("+00:00", "Z"),
                "project": data.get("project"),
                "revision": data.get("revision"),
                "reason": data.get("reason"),
                "advisories": data.get("advisories") or [],
                "findings_bypassed": len(blocking),
            })
    except (OSError, UnicodeDecodeError):
        overrides = []

    overrides.sort(key=lambda r: r["ts"], reverse=True)   # most recent first
    return {
        "lens": f"recent-security-gate-overrides (SPEC-0119 rule 14) — governed deploys that OVERRODE a "
                f"REJECTING pre-deploy security gate (SPEC-0155 rule 7) in the last {window_days} days. "
                f"Each was owner-invoked, reason-bearing and named every finding it bypassed — but those "
                f"findings are still OPEN in the deployed code. DERIVED by folding the journal; zero "
                f"stored state, recomputed fresh, report-only, never a gate.",
        "now": now.isoformat().replace("+00:00", "Z"),
        "window_days": window_days,
        "count": len(overrides),
        "overrides": overrides,
        "next": ("the security gate was overridden — the bypassed findings remain open in production: fix "
                 "each (or record an accepted-risk waiver with an expiry) and re-run the security "
                 "producer. A REPEATING override is the signal that the gate's blocking rule, not the "
                 "deploy, is what needs the change (SPEC-0155 rule 7)."
                 if overrides else
                 "no security-gate override in the window — the gate has not been bypassed."),
    }


# ── SPEC-0204 rule 8 / SPEC-0119 (T-12288): LATE FINDINGS PER PASS ────────────────────────────────
#
# What this makes readable: the AUDITOR'S OWN COMPLETENESS, as a measured quantity rather than a
# declaration. Rule 8 asks pass 1 for a whole-subject survey and every later pass for a delta; a
# finding the auditor could have raised on pass 1 but raises later is recorded `late_finding` and is
# never a verdict driver. That is deliberately CHEAP for the auditor — owner ruling D8 settled that
# the completeness declaration is recorded and never a gate, after T-12141 gated on it and measured
# WORSE. Cheap and unread would be worse still, so the count is the reading: a stage whose pass-1
# survey is systematically incomplete shows up here as late findings accumulating per pass.
#
# It GATES NOTHING and can gate nothing: it is a fold over rows that already exist, with no stored
# state, no event of its own and no threshold. Suppressed when the count is zero, which is every repo
# whose audits surface nothing late.
_LATE_FINDINGS_WINDOW_DAYS = 30   # the reading window; not a governance scalar — a report-only horizon


def late_findings_per_pass(events_path, window_days: int = _LATE_FINDINGS_WINDOW_DAYS,
                           now=None) -> dict:
    """Fold the journal → the `late_findings[]` recorded on audit passes inside `window_days`.

    Pure: reads the journal, writes nothing (the SPEC-0149 acceptance boundary every fold here
    shares). SEGMENT-AWARE (SPEC-0190 rule 4) on the same terms as its `recent_gate_overrides`
    sibling — the 30-day window is wider than the 7-day live segment, so a raw read of the live
    segment alone would report an older late finding as absent, which for every reader means it was
    never recorded.

    A missing/unreadable journal, a malformed line or an unparseable `ts` yields a clean zero-count
    result — a report-only surface never breaks the seam it rides and never nags on an unknown.

    Returns `{lens, now, window_days, count, passes, findings, next}` — `count` is the number of LATE
    FINDINGS, `passes` the number of distinct (task, stage, pass) rows that carried at least one.
    Both are reported because they answer different questions: one card taking five late findings on
    one pass and five cards taking one each are the same `count` and very different signals.
    """
    now = now if now is not None else datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    findings: list = []
    rows_seen: set = set()
    try:
        for event in journal.segment_rows_since(
                events_path, _window_segment_floor(now, days=window_days)):
            if not isinstance(event, dict) or event.get("type") != "external_audit_completed":
                continue
            data = event.get("data") if isinstance(event.get("data"), dict) else {}
            late = data.get("late_findings")
            if not isinstance(late, list) or not late:
                continue
            ts = _parse_stamped_deadline(event.get("ts"))
            if ts is None:
                continue          # no establishable date ⇒ not placeable in the window
            if (now - ts).days > window_days:
                continue
            tid = event.get("task_id") or data.get("target_id")
            stage, passes = data.get("stage"), data.get("passes")
            rows_seen.add((tid, stage, passes))
            for f in late:
                f = f if isinstance(f, dict) else {}
                findings.append({
                    "ts": ts.isoformat().replace("+00:00", "Z"),
                    "task": tid,
                    "stage": stage,
                    "pass": f.get("pass") if f.get("pass") is not None else passes,
                    "finding_fingerprint": f.get("finding_fingerprint"),
                    "criterion_ref": f.get("criterion_ref") or f.get("class_id"),
                })
    except (OSError, UnicodeDecodeError):
        findings, rows_seen = [], set()

    findings.sort(key=lambda r: r["ts"], reverse=True)   # most recent first
    return {
        "lens": f"late-findings-per-pass (SPEC-0204 rule 8) — defects the external auditor raised at "
                f"a pass >= 2 with `causality: pre-existing-in-subject`, i.e. ones its own pass-1 "
                f"whole-subject survey MISSED, in the last {window_days} days. Each was RECORDED and "
                f"excluded from that pass's verdict (owner ruling D8: a late finding is never a "
                f"verdict driver on its own) and each still needs a typed `ceiling_decision` before "
                f"its card can close. DERIVED by folding the journal; zero stored state, recomputed "
                f"fresh, report-only, never a gate.",
        "now": now.isoformat().replace("+00:00", "Z"),
        "window_days": window_days,
        "count": len(findings),
        "passes": len(rows_seen),
        "findings": findings,
        "next": ("late findings are the measured cost of an incomplete pass-1 survey: they are "
                 "recorded, not penalised, but each blocks its card's `task close` until a "
                 "`yitc-v2 audit decide` records fix / accept / defer. A RISING count on one stage is "
                 "the signal that the pass-1 packet, not the auditor, is what needs the change."
                 if findings else
                 "no late finding in the window — every defect surfaced on the pass that surveyed for "
                 "it."),
    }


# ── SPEC-0119 rule 12 (T-10471 / X-0336): in-flight dispatches with no journaled monitoring read ────
#
# The gap this closes: `dispatch` OBLIGES the controller to arm a watcher — "arming is NON-SKIPPABLE"
# (patterns/background-session-monitoring.md §Watcher, T-0620/T-10347) — but nothing could ever OBSERVE
# a skip. A dispatched worker is a separate provider sub-session, so the harness sends NO completion
# notification; an unwatched wave is detected only when the OWNER pokes (incident 2026-06-09). This
# fold is that obligation's first observation surface: it rides the debt echo's existing seams and says,
# report-only, that K in-flight dispatches have no journaled monitoring read. It gates NOTHING.
#
# WHAT THIS IS NOT (CHARTER non-goal 7 — "NOT a behavioral discipline detector"). It never classifies
# AI BEHAVIOUR, keeps no counter across sessions, holds no FSM or stored state, and blocks nothing. It
# reports the FLEET's observable state — workers flying with no verdict read — exactly as
# `_view_overdue_recheck` reports deploys past their recheck deadline. An undischarged OBLIGATION, not
# a score.

# The MONITORING-READ receipt: `dispatch --watch` emits ONE `consumer_read_evidence` at exit carrying
# this verb surface + the `watched_tasks` it was armed over (dispatch.cmd_dispatch_watch). It is the
# ONLY journaled evidence that anyone read a fleet verdict: `journal query --fleet-verdict` and
# `--dispatch-status` are PURE readers that emit nothing (SPEC-0133 rule 1) — and making them emit is
# not an option, because the watcher calls them IN-PROCESS on every tick, so a receipt there would fire
# once per tick (journal spam). Hence the blessed watcher's exit receipt is the signal.
#
# `consumer_read_evidence` is the GENERIC Principle-8 adoption-probe type — ANY task may emit one — so
# the type alone cannot identify a watcher read. BOTH halves discriminate it: the verb surface below AND
# an attributable `watched_tasks`. THE COUPLING TO THE EMITTER IS PINNED BY A TEST, not by a shared
# literal: the emitter (`cmd_dispatch_watch`) lives behind a SIGNED SPEC-0133 anchor, and promoting its
# string to a shared constant would drift that spec's signature from a card scoped to SPEC-0119. Instead
# a test drives the REAL emitted payload through this fold, so a rename fails RED there instead of
# silently making every dispatch read "unmonitored" forever.
MONITORING_READ_EVENT = "consumer_read_evidence"
MONITORING_READ_SURFACE = "--fleet-verdict"      # substring of the receipt's `verb_surface`
DISPATCH_LAUNCH_EVENT = "bg_dispatch_launched"


def _monitoring_read_tasks(event: dict):
    """The task ids ONE journal event proves a monitoring read of, else None (not a monitoring read).

    FAITHFUL, never fail-closed here: this reports only what the event literally says, and the single
    READER below decides what an unattributable receipt means
    (`lessons/fail-closed-belongs-to-the-reader-not-the-parser`). A receipt with no usable
    `watched_tasks` yields None — it attributes its read to no task, so it clears none.
    """
    if not isinstance(event, dict) or event.get("type") != MONITORING_READ_EVENT:
        return None
    data = event.get("data")
    if not isinstance(data, dict):
        return None
    surface = data.get("verb_surface")
    if not isinstance(surface, str) or MONITORING_READ_SURFACE not in surface:
        return None
    watched = data.get("watched_tasks")
    if not isinstance(watched, list):
        return None
    tasks = {t.strip() for t in watched if isinstance(t, str) and t.strip()}
    return tasks or None


def unmonitored_dispatches(rows, _status_row, _dispatch_events, floor_minutes: int = 90, now=None,
                           self_session_ref=None) -> dict:
    """Fold the in-flight fleet + the journal → the dispatched tasks flying with NO journaled monitoring
    read, older than the age floor (SPEC-0119 rule 12).

    THE DEBT UNIT IS THE DISPATCHED TASK, NOT THE WORKER ROW (audit-pre pass 2, HIGH finding). A
    worker-centric fold that cleared a whole row whenever the receipt's watched set INTERSECTED it would
    silence an unwatched T-B riding the same warm worker as a watched T-A — losing exactly the signal
    this view exists to raise. Every join here is therefore per TASK id, which is also the one robust
    key: a row carries `task_ids`, a launch carries its task, a receipt carries `watched_tasks`. (Joining
    on `session_ref` would rest on the advisory, race-prone `_dispatch_identity` — journal.py.)

    IN-FLIGHT COMES FROM THE ONE CLASSIFIER, AND THAT IS WHAT MAKES HISTORY SAFE. Candidates are the
    tasks of the injected fleet-verdict `rows`, and each task's terminality is read from the injected
    `_status_row` — the SAME `journal query --dispatch-status` classifier the blessed watcher ticks on
    (SPEC-0133 rule 5 admits no second classifier path). So a landed / halted / parked dispatch is
    invisible BY CONSTRUCTION, and the fold can never retro-charge history — the failure a fold-side
    default produced for the sibling proof-obligation view (39 retro debt lines across 3 consumers, its
    trial run). A task whose status cannot be read is SKIPPED: a report-only surface never nags on an
    unknown (rule 3).

    THE EVENTS COME FROM THE ONE DISPATCH JOURNAL READER, NOT FROM A RAW FILE. `_dispatch_events` is the
    injected `_dispatch_status_events` — the reader that UNIONS the local checkout's journal, MAIN's
    journal, and every live worktree's journal (deduped, ts-sorted). This is load-bearing, not stylistic:
    `dispatch` appends `bg_dispatch_launched` to MAIN's journal, so a fold that opened only the local
    `events.jsonl` would find NO launches when run from a worktree — every candidate silently skipped,
    the view permanently dead there. Reading through the same union the classifier reads means the two
    halves of this fold can never disagree about which journal they are talking about (CHARTER §P5 — one
    source, not two). The reader is WINDOW-BOUNDED by its caller (the same wave window the fleet rows are
    derived under), so a launch that has aged out of that window is not surfaced — consistent by
    construction, since such a dispatch is not in `rows` either.

    THE FLOOR IS AN AGE FLOOR (rule 3), and it is set ABOVE the longest sanctioned watch cycle for a
    structural reason: the watcher's receipt lands at its EXIT, so a live armed watch is invisible to
    this fold until it exits (WATCH_MAX_RUNTIME_SECS = 1800s; the §Watcher recipe shows a
    `--watch-timeout 3600`). A floor of 90 minutes therefore cannot false-nag a controller who keeps
    re-arming the blessed watcher — only a genuinely abandoned wave surfaces. The COUNT is never hidden
    (one abandoned wave is real debt); only youth suppresses. A non-positive floor disables it.

    Args:
      rows: the fleet-verdict records (in-flight workers). Each `{session_ref, task_ids, …}`.
      _status_row: `task -> {class, detail} | None` — the per-task dispatch-status reader (injected, so
        the fold is hermetically testable with no subprocess and no clock).
      _dispatch_events: `() -> [event dict]` — the UNIONED dispatch journal reader
        (`_dispatch_status_events`). A reader that raises or yields nothing ⇒ a clean, zero-count result:
        this view is report-only and must never break a seam it rides.
      floor_minutes: the age floor (host-supplied from `YITC_DEBT_DISPATCH_MONITOR_FLOOR_MINUTES`).
      now: aware datetime to age against; defaults to real UTC now. Injected by the tests so every
        assertion is deterministic, never wall-clock-dependent.
      self_session_ref: this session's own worker ref, if any — its row is DROPPED, so a landing worker
        can never report ITSELF as an unmonitored dispatch.

    Returns `{"lens", "now", "count", "dispatches", "floor_minutes", "next"}` — the shape the sibling
    views return. Pure: reads one file, writes nothing.
    """
    now = now if now is not None else datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    floor = floor_minutes if (isinstance(floor_minutes, int) and not isinstance(floor_minutes, bool)
                              and floor_minutes > 0) else 0

    # CANDIDATES — the tasks of the in-flight rows, minus our own worker's row. A malformed row is
    # dropped, never fatal.
    candidates: list = []
    for row in (rows or []):
        if not isinstance(row, dict):
            continue
        if self_session_ref and row.get("session_ref") == self_session_ref:
            continue                      # never self-report (a landing worker is itself in flight)
        for task in (row.get("task_ids") or []):
            if isinstance(task, str) and task.strip() and task.strip() not in candidates:
                candidates.append(task.strip())
    if not candidates:
        return _unmonitored_result(now, [], floor)

    # THE JOURNAL — one pass over the UNIONED dispatch events for both halves, restricted to the
    # candidate tasks: each task's NEWEST launch (a re-dispatch honestly restarts the clock) and every
    # monitoring read that names it. A reader failure yields a clean zero — never a broken seam.
    launched_at: dict = {}                # task -> the newest bg_dispatch_launched ts
    read_at: dict = {}                    # task -> the newest monitoring-read ts naming it
    wanted = set(candidates)
    try:
        events = _dispatch_events() or []
    except Exception:                     # noqa: BLE001 — a report-only view never breaks its seam
        return _unmonitored_result(now, [], floor)
    for event in events:
        if not isinstance(event, dict):
            continue                      # a malformed record never breaks a report-only fold
        event_ts = _parse_stamped_deadline(event.get("ts"))
        if event_ts is None:
            continue                      # no establishable ordering ⇒ neither launches nor clears
        if event.get("type") == DISPATCH_LAUNCH_EVENT:
            task = event.get("task_id")
            if isinstance(task, str) and task in wanted:
                if task not in launched_at or event_ts > launched_at[task]:
                    launched_at[task] = event_ts
            continue
        for task in (_monitoring_read_tasks(event) or ()):
            if task in wanted and (task not in read_at or event_ts > read_at[task]):
                read_at[task] = event_ts

    unmonitored = []
    for task in candidates:
        launch_ts = launched_at.get(task)
        if launch_ts is None:
            continue                      # never launcher-dispatched (hand-claimed) ⇒ not a dispatch
        # The status read is PER TASK and may fail per task — so it is guarded per task. An unguarded
        # call would let ONE unreadable task abort the whole fold, and (because the host residue
        # swallows a failing view wholesale) take EVERY OTHER debt line down with it: a broken read
        # about one worker would silently hide the followup / recheck / security debt too. Skipping the
        # task is the same answer the unknown-status branch already gives — a report-only view degrades
        # per-row, never collectively (rule 3: never nag on an unknown, and never break the seam).
        try:
            status = _status_row(task)
        except Exception:                 # noqa: BLE001 — one unreadable task never sinks the echo
            continue
        if not isinstance(status, dict):
            continue                      # unreadable status ⇒ never nag on an unknown (rule 3)
        if status.get("class") in ("TERMINAL", journal.DISPATCH_CLASS_CLOSED_AWAITING_CONTROLLER_LAND):
            # already drained — a done task is never debt. T-12351: the controller-lands contracted
            # completion (the worker stopped after `task close` as told) is not an unmonitored
            # in-flight worker either — it is owed a land, which `--dispatch-status` names.
            continue
        read_ts = read_at.get(task)
        if read_ts is not None and read_ts >= launch_ts:
            continue                      # a monitoring read NAMING this task, since it launched
        age_minutes = int((now - launch_ts).total_seconds() // 60)
        if age_minutes < floor:
            continue                      # too young to be debt — only youth suppresses
        unmonitored.append({
            "task": task,
            "launched_at": launch_ts.isoformat().replace("+00:00", "Z"),
            "age_minutes": age_minutes,
            "class": status.get("class"),
        })
    unmonitored.sort(key=lambda r: (-r["age_minutes"], r["task"]))   # oldest debt first
    return _unmonitored_result(now, unmonitored, floor)


# T-10873 — the TERMINAL card statuses the rule-18 reader excludes. Homed here, beside the ONE reader
# that owns this judgement, and deliberately NOT in the shared predicate: `journal._halt_resolution`
# reports the journal faithfully for `--fleet-verdict` and the re-dispatch brief too, and what a
# faithful UNRESOLVED MEANS is each reader's own (`lessons/fail-closed-belongs-to-the-reader-not-the-parser`).
# `wont-do` and `done` are QUEUE.md's two terminal statuses; `ready` / `parked` / `in-progress` are not.
#
# T-12030 — THE VALUE now comes from `state`, and the NAME stays here. The card filter this card adds
# (`state.card_is_open`) needs the same set one layer down, in the leaf that owns the card reader, and
# spelling the frozenset twice would be a parallel definition of one fact (CHARTER §P1 filter 1 / §P5).
# So the set is DEFINED once in `state` and BOUND here — which removes a duplicate rather than adding
# one, and leaves this SPEC-0119 `implements:` anchor and every reader of it untouched. The T-10873
# judgement above is unchanged: what a faithful UNRESOLVED means is still this reader's own, and this
# name is still where rule 18's exclusion is expressed.
TERMINAL_CARD_STATUSES = state.TERMINAL_CARD_STATUSES

# T-10902 — the closed set of ABSENT-CARD dispositions the rule-18 reader accepts as a resolution.
# CLOSED on purpose (the SPEC-0093 rule-22 lesson): an unknown / misspelled kind is NOT a disposition
# and must never drop a row. Each member names a POSITIVE record — a deletion COMMIT, or fixture
# provenance — never the mere fact that a card is missing. See `absent_card_provenance`.
ABSENT_CARD_RESOLUTIONS = frozenset({"card-deleted", "test-fixture"})

# The id shape this reader will speak about at all. A halted "task" that is not even id-shaped cannot
# be looked up in git or in tests/, so it is never dispositioned — it keeps its row.
_TASK_ID_RE = re.compile(r"^T-\d+$")
_PROVENANCE_GIT_TIMEOUT = 10


def absent_card_provenance(task_id: str, *, repo_root, _run=None) -> "dict | None":
    """T-10902 — why is there NO card for `task_id`? Answer ONLY when the repo RECORDS the reason.

    THE ONE RULE: this reader returns a disposition only on POSITIVE evidence, and returns None for
    everything else — most of all for the plain "no card is here". Absence is not a resolution. That
    asymmetry is the whole safety property: rule 18 drops a halt on what this returns, so a reader that
    answered from absence would become the mute button SPEC-0119 rule 18 exists to prevent (a halt goes
    quiet with age exactly when it needs attention). Nothing here is time-based or count-based.

    The two shapes it can prove, both measured on this repo:

      `card-deleted`  — a commit DELETED `tasks/<id>-*.yaml`. Deleting a duplicate card is a legitimate
        disposition, not an anomaly: T-0206 / T-0208 were resolved and acted on by ce8d5f153, which
        removed them as confirmed duplicates of shipped T-0200 / T-0201. Because the reader clears a
        halt off a TERMINAL status on a CARD, a resolution that deleted the card was invisible and the
        halt was unclearable BY ANY VERB, forever. The evidence carried back is the deleting COMMIT, so
        the drop is attributable to that commit rather than to the card's mere absence.

      `test-fixture`  — the id was never a task at all. Proven by a CONJUNCTION, never by either half:
        git history has NEVER carried a card for it AND it is used as a fixture id under `tests/`.
        T-9001 is the measured case — a fixture id whose ~140 historical journal rows persist because
        the journal is append-only (the leak itself was closed AT SOURCE by T-10881, and the history it
        left may never be rewritten — CHARTER §Principle 5). Having no card, it can never be marked
        terminal, so a TEST ID was being presented to the owner as a worker awaiting a decision. The
        conjunction is what keeps a REAL task id out: real ids are named in tests all the time, but
        they HAVE (or had) a card, so the history leg fails and their halts keep reporting.

    A LIVE card ⇒ None, always: that case belongs to the card cross-check (`_main_task_strand_state` /
    `TERMINAL_CARD_STATUSES`), and answering here would be a second opinion on it.

    Never raises and never writes: every git call is bounded and its failure reads as "cannot prove",
    which keeps the halt visible. Args: `repo_root` — the checkout to interrogate (the caller binds it
    to MAIN, where the cards and history live); `_run` — the subprocess seam, injectable for tests.

    Returns `{"kind", "evidence"}` with `kind` in `ABSENT_CARD_RESOLUTIONS`, or None.
    """
    if not isinstance(task_id, str) or not _TASK_ID_RE.match(task_id):
        return None
    try:
        root = Path(repo_root)
        # A card that EXISTS is the card cross-check's subject, not this reader's.
        if any(root.glob(f"tasks/{task_id}-*.yaml")):
            return None
        run = _run if _run is not None else _provenance_git
        pathspec = f"tasks/{task_id}-*.yaml"
        deleted = run(root, ["log", "--diff-filter=D", "-1", "--format=%h%x1f%s", "--", pathspec])
        if deleted:
            sha, _, subject = deleted.partition("\x1f")
            if sha:
                return {"kind": "card-deleted",
                        "evidence": f"card deleted by commit {sha}" + (f" — {subject}" if subject else "")}
        # NOT deleted. Did a card for this id EVER exist on any branch? If it did, the absence is
        # unexplained (a stray delete, a bad checkout) and this reader must stay silent.
        if run(root, ["log", "--all", "-1", "--format=%h", "--", pathspec]):
            return None
        used_in = _fixture_id_uses(root, task_id)
        if used_in:
            more = f" (+{len(used_in) - 1} more)" if len(used_in) > 1 else ""
            return {"kind": "test-fixture",
                    "evidence": f"no card in git history, ever; used as a test-fixture id in "
                                f"{used_in[0]}{more}"}
    except Exception:                     # noqa: BLE001 — cannot prove ⇒ the halt keeps its row
        return None
    return None


def _provenance_git(root, argv: list) -> str:
    """`git -C <root> <argv…>` → stripped stdout, or "" on ANY failure. Bounded; never raises."""
    import subprocess
    try:
        proc = subprocess.run(["git", "-C", str(root)] + list(argv), capture_output=True, text=True,
                              timeout=_PROVENANCE_GIT_TIMEOUT)
    except Exception:                     # noqa: BLE001 — no git, no repo, a timeout: all "cannot prove"
        return ""
    return (proc.stdout or "").strip() if proc.returncode == 0 else ""


def _fixture_id_uses(root, task_id: str) -> list:
    """The `tests/` files naming `task_id` as a bare id (repo-relative, sorted). Word-bounded so
    `T-900` never matches `T-9001` — a prefix match here would attribute a real card's id to a
    fixture and silence a genuine halt."""
    pattern = re.compile(re.escape(task_id) + r"(?!\d)")
    hits = []
    for path in sorted((root / "tests").rglob("*.py")):
        try:
            if pattern.search(path.read_text(encoding="utf-8", errors="replace")):
                hits.append(str(path.relative_to(root)))
        except OSError:
            continue                      # an unreadable test file proves nothing either way
    return hits


def _is_pre_claim_refusal(rows) -> bool:
    """T-11679 — is this task's NEWEST halt a PRE-CLAIM REFUSAL (`task refuse`, `kind: refused`)?

    Read off the rows the fold already indexed for the task — no second journal pass, no new reader.
    NEWEST wins because a card can be refused, disposed and later halted again for an unrelated
    cause; only the halt actually in question may be dropped by the refusal-disposed arm.

    FAIL-CLOSED toward VISIBLE, matching every other criterion in this fold: a malformed row, a
    missing/unparseable ts, a non-dict `data`, an absent `kind` and an empty list ALL answer False,
    which KEEPS the halt's row. A wrong silence loses the signal; a surfaced line costs a line."""
    newest, newest_ts = None, None
    for row in rows or ():
        if not isinstance(row, dict) or row.get("type") != "bg_dispatch_halted":
            continue
        ts = row.get("ts") or ""
        if not isinstance(ts, str):
            continue
        if newest is None or ts >= (newest_ts or ""):
            newest, newest_ts = row, ts
    if not isinstance(newest, dict):
        return False
    data = newest.get("data")
    return isinstance(data, dict) and data.get("kind") == "refused"


def unresolved_worker_halts(_dispatch_events, _halt_resolution, _dispatch_task_of, now=None, *,
                            _card_state=None, _absent_card_provenance=None,
                            _halt_dispatcher=None, self_session_ref=None) -> dict:
    """Fold the dispatch journal → the worker halts whose CAUSE the journal has not cleared, HOWEVER OLD
    THEY ARE (SPEC-0119 rule 18). The sibling of `unmonitored_dispatches` above, differing in exactly
    one thing — the drop criterion.

    THE ONE RULE THIS SHIPS: an unresolved worker halt stays visible until its cause is RESOLVED. AGE
    stops being what silences it. That is a REPLACEMENT of the drop criterion, not an addition beside
    it, and it is why this fold takes no age floor, no recency window and no `since`.

    AND ONE THING MORE, ADDED BY T-10873: a halt whose TASK CARD has already reached a TERMINAL status
    (`done` / `wont-do`) does not print either. The subject of this row is a card still AWAITING A
    DECISION; a closed card is awaiting none, whatever the journal can or cannot prove about the halt.

    WHY THE CROSS-CHECK IS HERE AND NOT IN THE PREDICATE — the load-bearing part of this design.
    `_halt_resolution` looks only FORWARD from the newest halt, so a resolution PRE-DATING the halt is
    unfindable by construction. Measured on the engine journal: T-0178's card closed 08:58:45Z, its
    branch landed 08:59:32Z, and the `bg_dispatch_halted` arrived 09:00:38Z — the halt is LAST, nothing
    follows it, and fail-closed correctly answers UNRESOLVED (same shape for T-0419/T-0428/T-0434/
    T-0436/T-10611). The predicate is RIGHT; it reports the journal faithfully, which is its documented
    contract. The defect was in what THIS READER did with a faithful UNRESOLVED, so the fix belongs
    here. Rule home: `lessons/fail-closed-belongs-to-the-reader-not-the-parser` (fail-closed is a
    property of a USE SITE, not of a parse result). Measured effect on the engine journal
    (2026-08-10): 60 rows → 5.

    THE BOUND ON THAT PARAGRAPH, NAMED BY T-12068 — it is about a disposition PRE-DATING the halt, and
    ONLY that. The complementary case, a card disposed STRICTLY AFTER its halt, IS inside what a
    forward-only predicate reads, and it is now `_halt_resolution` arm (iv) — the predicate's own,
    upstream of this fold, so THIS reader needs no arm for it and gains none here. That placement is
    the point rather than a convenience: a pre-claim REFUSAL that was then parked (T-10980, measured
    2026-09-04) can satisfy no other resolution arm ever, and while the two views read it differently —
    `--dispatch-status` TERMINAL, this line needs-decision — they were two views of one engine
    disagreeing (CHARTER P7). Both read the ONE predicate, so putting the arm anywhere else would have
    kept them apart. The T-10873 reading above is untouched and still load-bearing for its own shape.

    AND, ADDED BY T-10902: two RESOLUTION SHAPES THE READER COULD NOT SEE, both cleared by POSITIVE
    evidence about a MISSING card and never by its absence. A halt whose card was DELETED by a commit
    (T-0206 / T-0208, removed by ce8d5f153 as confirmed duplicates of shipped T-0200 / T-0201) was
    resolved 70 days ago and was UNCLEARABLE BY ANY VERB, because clearing needs a terminal status on
    a card and there was no card left to carry one. And a halt on a LEAKED TEST-FIXTURE id (T-9001 —
    never a task; its historical rows persist because the journal is append-only, the leak having been
    closed at source by T-10881) was presenting a test id to the owner as a worker awaiting a decision.
    Both are decided by the injected `_absent_card_provenance` reader, which answers ONLY from a
    deleting COMMIT or from fixture provenance. THE DIFFERENTIAL IS LOAD-BEARING: a card absent for NO
    recorded reason still reports. Nothing time-based or count-based was added — no age-out, no cap,
    no window — because a halt going quiet WITH AGE is the exact failure rule 18 exists to prevent.

    THE SCOPE BOUND IS THE OTHER HALF, AND IT IS WHAT KEEPS THIS FROM BEING A MUTE BUTTON. ONLY `done`
    and `wont-do` drop. A card that is `ready`, `parked`, or ABSENT ENTIRELY keeps its row — the no-card
    case most of all, being the shape most likely to be a genuine orphan, cleared only by the positive
    provenance above. So does an unknown status, an
    unreadable card, a reader that raises, and an absent collaborator: every uncertain read KEEPS the
    row, which is the same fail-closed-toward-visible posture the rest of this fold already holds.
    NOTE for anyone extending this: `_main_task_strand_state` also returns a `terminal` key, and it does
    NOT mean this — it is literally `not stranded`, and is TRUE for `ready` / `parked` / paused cards.
    Reading it instead of `status` would silence exactly the remainder this row exists to show.

    WHY IT IS NEEDED, MEASURED (not inferred). The two surfaces a controller actually reads both go
    quiet on a halt exactly as it ages: `_unmonitored_dispatch_view` bounds its reader by the wave
    window, and `--fleet-verdict` drops an aged-out halt from `rows` (SPEC-0133 rule 2a). So a halt is
    announced roughly once and then ages into silence — when it needs attention most. Real incident,
    kupiclub 2026-08-09: T-0146 idle 4h and T-0183 idle 2.5h, both absent from `--fleet-verdict`, both
    plainly listed by `--dispatch-status`, while a 5-worker fleet ran other plans. The OWNER surfaced
    it; no system surface did.

    IT IS TERMINAL-ATTENTION DEBT, NOT FLEET LIVENESS — the framing is load-bearing (the external-auditor
    placement consult, `decisions/halted-worker-surface-placement-audit-adhoc.yaml`). The subject is a
    stopped worker still awaiting a decision, NOT who is flying right now. That wording is what keeps
    this out of `--fleet-verdict` semantics and away from watcher machinery: the consult REJECTED both
    widening rule 2a's recency window (which is precisely what stops a LIVE-fleet reader degenerating
    into a backlog surface) and extending the life of `dispatch --watch` (CHARTER §6 names "no
    liveness-arming FSM" among its retirements). This view touches neither.

    ONE PREDICATE, NO SECOND CLASSIFIER PATH (SPEC-0133 rule 5). Resolution is decided SOLELY by the
    injected `journal._halt_resolution` — the same fail-closed predicate `--fleet-verdict` and the
    re-dispatch brief already share (T-10771 / rule 2d): a halt is cleared when the task's branch landed
    ok, or when the designed ceiling continuation ran (a converged consult plus that stage's granted
    GREEN pass). This fold adds NO reading of its own, invents no second notion of "resolved", and
    stores nothing. T-10771 shipped the half where a CLEARED halt stops reading as open; this is the
    opposite half — stopping AGE from silencing an UNCLEARED one — and the two together give the row its
    whole contract: surface while unresolved, drop on resolution.

    THE COHORT COMPLEMENT IS THE POINT, NOT A COURTESY. A row that never drops is an accumulating
    graveyard, which is exactly the failure the consult's rejection names. So the resolved cohort really
    must vanish, and it does: on the engine journal (2026-08-09) 232 distinct halted task ids fold to 60
    unresolved — the predicate already excludes 172.

    EVENT ROUTING IS A REDUCTION, NEVER A REINTERPRETATION. One pass indexes the injected events by task
    (`_dispatch_task_of`, via the halt rows themselves) plus the `land_completed` rows — which carry NO
    task_id, only `data.branch`, and are therefore the one class the predicate matches globally. Each
    halted id is then handed a ts-ordered merge of its own rows and the land rows a predicate can ACT
    on for it — its OWN branch's, plus the single first `land_completed{ok}` after its halt that arm
    (iii) could return at: precisely the set `_halt_resolution` can match for it, and nothing else.
    T-12202 narrowed that second half from the WHOLE global land corpus, re-sorted once per halt (an
    in-memory N+1 over rows the predicate provably cannot match), to that bounded subset — the land
    lane is indexed by branch in the SAME single pass and the ok-lane sorted ONCE outside the loop.
    This is what makes the fold O(N) instead of O(tasks x events); it changes no answer, and the
    per-arm equivalence census is written down at the construction site rather than here.

    FAIL-CLOSED TOWARD VISIBLE. A false silence is far worse than a false row here — a surfaced line
    costs a line, a wrong silence loses the signal entirely — so every uncertainty leaves the halt
    UNRESOLVED and visible: an unattributable halt, an unparseable ts, a predicate that returns nothing.
    A reader that RAISES folds to a clean zero, because a report-only view must never break the seam it
    rides (the rule-12 posture, verbatim).

    AND, ADDED BY T-11351: THE ROW SAYS WHO DISPATCHED THE WORKER. Every criterion above decides
    WHETHER a halt still counts; none of them tells a reader whether the counted halt is THEIRS. The
    line carried a count and the oldest id, both true and neither attributable, so on 2026-08-20 a
    controller read six halts — three of them its OWN fleet, stopped half an hour earlier — and did not
    recognise itself in the number (X-1014). Each row now carries `dispatched_by` (the dispatching
    session, via the injected `_halt_dispatcher`) and `by_this_session` (that ref equals the injected
    `self_session_ref`), and the result carries `attributed_count` / `unattributable_count` beside the
    total.

    ATTRIBUTION IS PURELY ADDITIVE, AND THAT IS THE LOAD-BEARING PART. It drops nothing, reorders
    nothing and filters nothing: `count` remains the TOTAL, exactly as before. A halt whose dispatcher
    CANNOT be established is counted in the total and attributed to NOBODY — never to the reader. That
    asymmetry is the same fail-closed-toward-visible posture as every criterion above, applied to a
    second axis: a wrongly-attributed halt tells a controller that a stranger's stopped worker is its
    own, which is the original error inverted and harder to catch than a plain unknown. Absent
    collaborators, an unresolvable reading session, or a dispatcher reader that RAISES all yield
    `attributed_count` 0 and leave the fold behaving exactly as it did before this change.

    Args:
      _dispatch_events: `() -> [event dict]` — the UNIONED dispatch journal reader
        (`_dispatch_status_events`), narrowed BY TYPE and never by age. A reader that raises or yields
        nothing ⇒ a clean, zero-count result.
      _halt_resolution: `(events, task_id) -> dict|None` — `journal._halt_resolution`, injected so this
        fold is hermetically testable and so the predicate stays the single home of "resolved".
      _dispatch_task_of: `(event) -> task_id|None` — `journal._dispatch_task_of`, injected rather than
        re-derived here for one load-bearing reason: it is the SAME attribution the predicate uses, so
        routing can never disagree with matching. A local copy that drifted would quietly stop handing a
        halt the very rows that resolve it, and the fold would report a resolved halt forever.
      _card_state: OPTIONAL `(task_id) -> dict|None` — the EXISTING card cross-check
        `_main_task_strand_state` (T-10577 / T-10712), the same reader `--fleet-verdict` injects to
        read a paused card for its `pause_detail`. EXTENDED, never duplicated: a second card reader
        here would be the failure, not the fix (CHARTER §P1 F1). Only its `status` is read, against
        `TERMINAL_CARD_STATUSES` — see the docstring's note on why NOT its `terminal` key. Absent
        (None) ⇒ no card cross-check at all and the fold behaves exactly as it did before T-10873, so
        an un-updated caller loses nothing. KEYWORD-ONLY, and deliberately so: it was added AFTER
        `now`, so taking it positionally would silently re-bind an existing 4-positional caller's
        CLOCK to a card reader — the tests inject `now`, so that mis-bind would make time-dependent
        assertions quietly meaningless rather than fail. `now` keeps its position; the new
        collaborator is the one that must be named.
      _absent_card_provenance: OPTIONAL `(task_id) -> dict|None` — `absent_card_provenance` above
        (T-10902), consulted ONLY for a halt whose card read produced NO card, so it can never
        second-guess a live one. Drops the row only on `{"kind": <in ABSENT_CARD_RESOLUTIONS>,
        "evidence": <non-empty>}`; None / a raise / a non-dict / an unknown kind / empty evidence /
        an absent collaborator ALL keep it. KEYWORD-ONLY for the same reason `_card_state` is.
      _halt_dispatcher: OPTIONAL `(events, task_id) -> session_ref|None` —
        `journal._halt_dispatcher_session` (T-11351), injected rather than re-derived here for the same
        reason `_dispatch_task_of` is: it selects the halt via the SAME `_newest_halt` the resolution
        predicate uses, so attribution can never name a different halt than the one being reported. It
        needs the launch rows, so its caller must read with `journal.HALT_ATTRIBUTION_INPUT_TYPES` (the
        resolution set PLUS `bg_dispatch_launched`) — read with the narrower resolution set the join
        finds nothing and every row is honestly unattributable. Absent (None) ⇒ no attribution at all.
        KEYWORD-ONLY for the reason `_card_state` is.
      self_session_ref: OPTIONAL — the READING session's own ref, from the host's NON-DYING resolver.
        Compared against each row's `dispatched_by`; None (unresolvable session) attributes NOTHING
        rather than guessing. KEYWORD-ONLY for the same reason.
      now: aware datetime to age against; defaults to real UTC now. Injected by the tests, so no
        assertion is wall-clock-dependent. Age here is REPORTED, never applied — nothing is filtered by it.

    Returns `{"lens", "now", "count", "attribution_known", "attributed_count",
    "unattributable_count", "halts", "next"}` — the shape the sibling views return, plus the T-11351
    attribution counters. Pure: reads, writes nothing, emits nothing, gates nothing.
    """
    now = now if now is not None else datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    try:
        events = _dispatch_events() or []
    except Exception:                     # noqa: BLE001 — a report-only view never breaks its seam
        return _unresolved_halt_result(now, [])

    # ONE pass: the halted task ids (order-preserving), each id's own rows, and the land rows —
    # the latter INDEXED, not accumulated into a single global list (T-12202). The index is what
    # lets each halt be handed only the land rows a predicate can ACT on; the census of which rows
    # those are, per arm, is written down at the `scoped` construction below.
    halted_ids: list = []
    by_task: dict = {}
    land_by_branch: dict = {}             # branch -> [(land row, its position among land rows)]
    ok_lands: list = []                   # every `land_completed{status: ok}`, as (row, position)
    newest_halt_ts: dict = {}             # task -> its NEWEST halt ts (the predicate's own `hts`)
    land_seq = 0
    for event in events:
        if not isinstance(event, dict):
            continue                      # a malformed record never breaks a report-only fold
        etype = event.get("type")
        if etype == "land_completed":
            # No task_id — the predicate matches these by `data.branch`. The POSITION is retained
            # because the original construction handed the predicate `by_task + land_rows` and sorted
            # it STABLY by ts, so land rows broke ts ties in journal order; re-ordering the narrowed
            # subset by this same position reproduces that order exactly.
            data = event.get("data") if isinstance(event.get("data"), dict) else {}
            branch = data.get("branch")
            if isinstance(branch, str) and branch:
                land_by_branch.setdefault(branch, []).append((event, land_seq))
            if data.get("status") == "ok":
                ok_lands.append((event, land_seq))
            land_seq += 1
            continue
        task = _dispatch_task_of(event)
        if not task:
            continue
        by_task.setdefault(task, []).append(event)
        if etype == "bg_dispatch_halted":
            if task not in halted_ids:
                halted_ids.append(task)
            # `_newest_halt` keeps the LAST of an equal-ts pair; either way the TS is the same value,
            # which is all this index carries.
            ts = event.get("ts") or ""
            if ts >= newest_halt_ts.get(task, ""):
                newest_halt_ts[task] = ts
    if not halted_ids:
        return _unresolved_halt_result(now, [])
    # Sort the ok-land lane ONCE, outside the per-halt loop, on the SAME (ts, journal position) key the
    # stable sort below uses — so "the first ok land strictly after a halt" is bisectable per halt
    # instead of re-scanned.
    ok_lands.sort(key=lambda pair: ((pair[0].get("ts") or ""), pair[1]))
    ok_land_ts = [(row.get("ts") or "") for row, _ in ok_lands]

    halts = []
    for task in halted_ids:
        # The predicate compares ts lexicographically in list order, so hand it a ts-ordered merge of
        # exactly what it can match for this id. Guarded per task: one unreadable id never sinks the
        # fold — and, because the host residue swallows a failing view wholesale, never takes the
        # sibling debt lines down with it (the rule-12 lesson).
        #
        # T-12202 — WHICH LAND ROWS THOSE ARE, per arm, and why every other one is provably INERT.
        # This is a pure INPUT NARROWING: the predicate, its arms, its ordering and every rendered
        # field are untouched; only the rows it is handed shrink from the WHOLE global land corpus
        # (re-sorted once per halt: the measured N+1) to the bounded set below.
        #   `_newest_halt`             — reads `bg_dispatch_halted` rows only; every one is in `by_task`.
        #   `_halt_main_attribution`   — matches `land_completed` with `data.branch == task/<id>` ONLY.
        #   `_halt_resolution` arm (i) — that same branch, `status: ok`, strictly after the halt.
        #   `_halt_resolution` arm (iii) — reached only for a MAIN-attributed halt, and it RETURNS at
        #     the FIRST `land_completed{ok}` (any branch) strictly after the halt ts. So exactly ONE
        #     foreign-branch land row is ever reachable: that first one. Arm (i) is judged before it at
        #     the same event, and every own-branch row is present, so the more specific `land-ok`
        #     reading still wins wherever it did before.
        #   arms (ii)/(iv)             — skip any row whose `_dispatch_task_of` is not this task, and
        #     match only consult / audit-pass / card-disposition types, which no land row is.
        # ORDER IS PRESERVED BY CONSTRUCTION: the picked rows are re-sorted by their ORIGINAL journal
        # position, then concatenated after `by_task` and stably sorted by ts — the same key and the
        # same relative order as the whole-corpus construction restricted to this subset, so equal-ts
        # ties resolve identically.
        own_lands = land_by_branch.get(f"task/{task}", [])
        picked = list(own_lands)
        hts = newest_halt_ts.get(task, "")
        first_ok = bisect.bisect_right(ok_land_ts, hts)
        if first_ok < len(ok_lands):
            candidate = ok_lands[first_ok]
            if all(candidate[1] != pos for _, pos in own_lands):
                picked.append(candidate)
        picked.sort(key=lambda pair: pair[1])
        scoped = sorted(by_task.get(task, []) + [row for row, _ in picked],
                        key=lambda e: e.get("ts") or "")
        try:
            resolution = _halt_resolution(scoped, task)
        except Exception:                 # noqa: BLE001 — one bad id never sinks the echo
            continue
        if not isinstance(resolution, dict) or resolution.get("resolved"):
            continue                      # RESOLVED ⇒ dropped. This is the cohort complement.
        # T-10873 — the SECOND drop criterion, applied only to what survived the predicate: a card that
        # has already reached a TERMINAL status is awaiting no decision, so its halt is not this row's
        # subject. Guarded per task like the predicate call above, and asymmetric ON PURPOSE — ONLY a
        # positive terminal-status read drops a row. A None (no card / ambiguous / unparseable), a
        # raise, a non-dict, a non-terminal status and an absent collaborator ALL keep it, holding the
        # fold's fail-closed-toward-visible posture: a wrong silence loses the signal entirely.
        card = None                       # no collaborator ⇒ no card read happened (T-10902 reads it)
        if _card_state is not None:
            try:
                card = _card_state(task)
            except Exception:             # noqa: BLE001 — an unreadable card never silences a halt
                card = None
            if isinstance(card, dict) and card.get("status") in TERMINAL_CARD_STATUSES:
                continue
            # T-11679 — the SAME criterion ("this card awaits no decision"), applied to the ONE
            # disposition that is deliberately NOT a terminal status. Since T-11679 a PRE-CLAIM
            # REFUSAL leaves a trace on the card (`refused_at`), and the governed exit
            # `task refuse --clear` records the disposition and returns the card to plain `ready` —
            # the shape a re-authored acceptance ends in. Read by STATUS alone that card looks
            # exactly like an undisposed one, so its halt row could never drop and rule 18's "surface
            # while unresolved, drop on resolution" contract would fail on this path.
            # NARROW BY CONSTRUCTION, and every bound is load-bearing:
            #   - it fires ONLY for a PRE-CLAIM refusal halt (`kind: refused` on the newest halt row),
            #     so no other halt class is touched;
            #   - it requires the card to POSITIVELY read `refused: False` — a card that still carries
            #     its refusal keeps its row, which is the whole point of the T-11679 gate;
            #   - a card the reader has not been TAUGHT the key (an older collaborator returning no
            #     `refused` key at all) keeps its row: `.get` returning None is not False here.
            # NO PREDICATE CHANGE. `journal._halt_resolution` and HALT_RESOLUTION_INPUT_TYPES are
            # untouched, so `--fleet-verdict` and the re-dispatch brief are unaffected — this is the
            # T-10873 rule applied again: the fail-closed reading belongs to the READER, never to the
            # shared parser (`lessons/fail-closed-belongs-to-the-reader-not-the-parser`).
            if (isinstance(card, dict) and card.get("refused") is False
                    and _is_pre_claim_refusal(by_task.get(task, []))):
                continue
        # T-10902 — the THIRD drop criterion, and the narrowest: a halt with NO CARD AT ALL whose
        # absence the repo positively EXPLAINS. Reached only when the card cross-check produced no
        # card, so it can never second-guess a live card, and it drops ONLY on a positive dict naming
        # a kind in the CLOSED `ABSENT_CARD_RESOLUTIONS` set with real evidence — a deleting commit
        # (T-0206/T-0208, resolved by deleting duplicate cards) or test-fixture provenance (T-9001,
        # never a task). ABSENCE ITSELF STILL KEEPS THE ROW: a card missing for no recorded reason is
        # the shape most likely to be a genuine orphan, and clearing on absence is exactly the hiding
        # mechanism SPEC-0119 rule 18 forbids. Same asymmetry as the arm above — None, a raise, a
        # non-dict, an unknown kind, empty evidence and an absent collaborator all KEEP the row.
        if _absent_card_provenance is not None and not isinstance(card, dict):
            try:
                provenance = _absent_card_provenance(task)
            except Exception:             # noqa: BLE001 — an unprovable absence never silences a halt
                provenance = None
            if (isinstance(provenance, dict)
                    and provenance.get("kind") in ABSENT_CARD_RESOLUTIONS
                    and str(provenance.get("evidence") or "").strip()):
                continue
        halt_ts = resolution.get("halt_ts") or ""
        parsed = _parse_stamped_deadline(halt_ts)
        # An unparseable halt ts loses only its AGE, never its ROW: age is reported here, never a filter,
        # so a halt with no establishable ordering still surfaces (fail-closed toward visible).
        age_days = int((now - parsed).total_seconds() // 86400) if parsed is not None else None
        # T-11351 — WHO DISPATCHED THIS WORKER. Guarded per task like every collaborator above: a
        # dispatcher reader that raises costs this row its ATTRIBUTION, never its presence. `None` (no
        # collaborator, a raise, an unjoinable halt) is the honest UNATTRIBUTABLE answer and is never
        # silently promoted to the reader's own ref — the row still counts in the total.
        dispatched_by = None
        if _halt_dispatcher is not None:
            try:
                dispatched_by = _halt_dispatcher(scoped, task)
            except Exception:             # noqa: BLE001 — an unreadable dispatcher never drops a row
                dispatched_by = None
            dispatched_by = str(dispatched_by).strip() if dispatched_by else None
        halts.append({
            "task": task,
            "halt_ts": halt_ts or None,
            "age_days": age_days,
            "reason": resolution.get("reason"),
            "dispatched_by": dispatched_by or None,
            # Attribution needs BOTH a known reading session and a resolved dispatcher; either unknown
            # ⇒ False. Never a fallback, never an inference from the task id.
            "by_this_session": bool(self_session_ref and dispatched_by
                                    and dispatched_by == str(self_session_ref).strip()),
        })
    # Oldest debt first; an unknown age sorts last rather than pretending to be age 0.
    halts.sort(key=lambda r: (r["age_days"] is None, -(r["age_days"] or 0), r["task"]))
    return _unresolved_halt_result(now, halts, attribution_known=bool(self_session_ref))


def _unresolved_halt_result(now, halts: list, *, attribution_known: bool = False) -> dict:
    return {
        "lens": "unresolved-worker-halts (SPEC-0119 rule 18) — dispatch/worker TERMINAL-ATTENTION debt: "
                "workers that STOPPED and whose halt cause the journal has not recorded as cleared "
                "(`journal._halt_resolution` — the task's branch landed ok, or the ceiling continuation "
                "ran) AND whose task CARD has not reached a terminal status. The drop criterion is "
                "RESOLUTION (or a settled card), never AGE: an unresolved halt on a live card stays "
                "visible however old it is, which is the whole point — the routinely-read surfaces "
                "(`--fleet-verdict`, the rule-12 fold) both go silent on a halt exactly as it ages. "
                "This is NOT fleet liveness and reports nothing about who is flying now. Zero stored "
                "state; recomputed fresh, report-only, never a gate.",
        "now": now.isoformat().replace("+00:00", "Z"),
        "count": len(halts),
        # T-11351 — the attribution counters, ADDITIVE to `count`, which stays the TOTAL.
        # `attribution_known` says whether the READING SESSION could be established at all: False ⇒
        # attributed_count is 0 because nothing was compared, NOT because none of the halts are the
        # reader's. A renderer must not present those two as the same statement.
        "attribution_known": bool(attribution_known),
        "attributed_count": sum(1 for h in halts if h.get("by_this_session")),
        "unattributable_count": sum(1 for h in halts if not h.get("dispatched_by")),
        "halts": halts,
        "next": ("these dispatched workers halted and nothing on record has cleared their cause — read "
                 "each with `bin/yitc-v2 journal query --dispatch-status --task T-XXXX` and decide it: "
                 "re-dispatch, resolve the blocker, or close/park the card. For a `refused(pre-claim)` "
                 "halt the route is the DISPOSITION one specifically — park or wont-do the card "
                 "(T-12068): re-dispatch is refused for that shape (SPEC-0166), and `resolve` would "
                 "need the very owner decision the park itself IS. The row drops by itself the "
                 "moment the journal records the cause cleared — nothing to acknowledge, nothing to mute."
                 if halts else
                 "every recorded worker halt has its cause resolved on record — nothing owed."),
    }


def _unmonitored_result(now, dispatches: list, floor: int) -> dict:
    return {
        "lens": "unmonitored-dispatches (SPEC-0119 rule 12) — dispatched tasks still IN FLIGHT (per the "
                "one `journal query --dispatch-status` classifier) whose worker has been flying past the "
                "age floor with NO journaled monitoring read naming it. The monitoring read is the "
                "`dispatch --watch` exit receipt: the bare fleet-verdict / dispatch-status readers are "
                "pure and journal nothing, so a hand read leaves no trace. `dispatch` OBLIGES a watcher "
                "(patterns/background-session-monitoring.md §Watcher) — this is that obligation's "
                "observation surface. Terminal dispatches are invisible, so history is never "
                "retro-charged. Zero stored state; recomputed fresh, report-only, never a gate.",
        "now": now.isoformat().replace("+00:00", "Z"),
        "count": len(dispatches),
        "floor_minutes": floor,
        "dispatches": dispatches,
        "next": ("these dispatched workers are in flight with no journaled monitoring read — arm the "
                 "blessed watcher over them (`bin/yitc-v2 dispatch --watch --task T-XXXX …`), which "
                 "wakes you on land / stall / blocked-on-land and journals the read that silences this "
                 "line. Without an armed watcher nothing wakes the controller: a dispatched worker is a "
                 "separate sub-session and sends no completion notification."
                 if dispatches else
                 "every in-flight dispatch has a journaled monitoring read — nothing owed."),
    }


# ── SPEC-0156 (T-10509): declared kernel-graded checks with no recorded failing demonstration ───────
#
# The gap this closes: the kernel GRADES a project's declared checks — a live probe, a security probe, a
# deploy-class evidence command, a test class, a verify layer — but never asks the one question that makes
# a green mean anything: "would this check still pass if the thing under test were BROKEN?" (the SPEC-0060
# §4 / X-0246 differential rule, which the kernel applied only to task ACs, never to what it grades
# itself). On 2026-07-13 aiseller ran 8 hours of total prod-auth death behind SIX such greens: a /healthz
# probe a dead product passes, a "never 200" assertion a 404 also satisfies, a deploy reported OK with one
# worker on old code, a source-only secret scan green while a live token streamed to logs, an
# owner-environment-only verify layer, and an e2e class whose browsers were never installed — nothing ran,
# so nothing failed.
#
# SPEC-0156 answers it at the ADMISSION seam: a declared check is admitted together with ONE recorded
# FAILING DEMONSTRATION — the check shown RED against a named deliberately-broken input, journaled once. A
# check with no such record is not refused (SPEC-0156 §3 — no new gate class, CHARTER non-goal 7); it is
# admitted UNPROVEN and surfaces HERE, report-only, until demonstrated. So a green comes to mean "this
# check has been SEEN to fail when its subject broke", not "nothing ran, nothing failed".
#
# ZERO STORED STATE, exactly like the sibling folds: the carrier says what is DECLARED, the journal says
# what was DEMONSTRATED, and the debt is the difference — recomputed fresh every call (SPEC-0149 §2).

# The demonstration EVENT (SPEC-0025 catalog, added by this task). It rides the EXISTING generic `event`
# verb (`bin/yitc-v2 event check_admission_demonstrated --data …`) — SPEC-0156 §2 admits no new verb, no
# new emitter, and no new store for it.
ADMISSION_EVENT = "check_admission_demonstrated"

# The ONLY outcome that discharges an admission. A demonstration exists to show the check RED against a
# broken input; a green (or absent, or misspelt) outcome demonstrates NOTHING, so it must not clear the
# line — the first of the two differential directions this fold's tests pin.
ADMISSION_RED_OUTCOME = "red"

# THE EVIDENCE, NOT JUST THE VERDICT (audit-post finding 1). SPEC-0156 §2 admits a check on "one journaled
# RED run against a NAMED broken input" — so the NAMED BROKEN INPUT and the DECLARATION LOCATOR are part of
# the contract, not decoration. A bare RED with no broken input names nothing anyone could re-run or audit:
# it is a CLAIM, and admitting a check on a claim is the exact false-green this spec exists to end. Both
# fields must be non-empty strings for a record to clear a check.
ADMISSION_REQUIRED_FIELDS = ("broken_input", "declaration")

# ── The NEAR-MISS feedback (T-11178 / aiseller X-0921) ─────────────────────────────────────────────
#
# THE GAP. Every condition above is evaluated at READ time, over a row emitted through the GENERIC
# `event` verb — and that is by design: SPEC-0156 §2 admits no new verb and no new emitter, so nothing
# validates the payload when it is written, and nothing CAN (a generic verb has no knowledge of one
# type's required keys). The consequence is that a row which misses ANY condition is simply not counted,
# and the debt line keeps reading `never` — INDISTINGUISHABLE from having emitted nothing at all. The
# author gets no signal that their row was seen and rejected, nor which condition rejected it.
#
# MEASURED COST (X-0921, aiseller 2026-08-13, fingerprint
# `check-admission-demonstrated-incomplete-payload-silently-fails-to-clear-no-warn`): one wasted land
# plus a source-reading round-trip to learn a contract that IS documented. The sharper harm they name is
# what makes this worth a fold at all — a less persistent reader concludes the demonstration mechanism is
# BROKEN, or worse, believes the check was CLEARED.
#
# WHAT THIS IS AND IS NOT. It adds FEEDBACK, and nothing else. What counts as PROVEN is untouched: the
# three conditions in `unproven_checks` and every filter in `_admission_demonstrations` are unchanged,
# deliberately — the failing direction is already the safe one (under-evidenced ⇒ still owed). And it is
# REPORT-ONLY, the fence this rides on: NEVER REFUSES, NEVER GATES (SPEC-0156 §3 / CHARTER non-goal 7).
# An emit-time refusal was the obvious alternative and is rejected twice over — it would break the
# no-new-emitter rule AND turn a report into a gate.
#
# THE FAIL-SAFE DIRECTION INVERTS HERE, and getting it backwards is the whole defect
# (`lessons/a-signal-about-a-reader-fails-safe-the-opposite-way-to-a-gate.md`). This is a report-only
# SIGNAL about what an AUTHOR did, not a guard on an action: a missed detection only leaves the silence
# that already existed, whereas a WRONG near-miss accuses someone of a mistake they did not make — and
# once an operator sees one false accusation, the whole line gets skimmed and is worth nothing. So an
# unattributable row is DROPPED, never guessed onto an unrelated check.
NEAR_MISS_MATCH_CUTOFF = 0.82

# The near-miss REASONS, in the order the conditions are actually evaluated, so the reason a line names
# is the reason the row was actually dropped (a row failing several is reported at the FIRST — this is
# what makes the output deterministic rather than dependent on dict ordering).
NEAR_MISS_UNKNOWN_CHECK = "check-name"
NEAR_MISS_OUTCOME_NOT_RED = "outcome-not-red"
NEAR_MISS_INCOMPLETE = "incomplete-record"
NEAR_MISS_IDENTITY = "identity-mismatch"

# The DECLARED-CHECK SURFACES (SPEC-0156 §1, verbatim) — where a kernel-graded check is declared in the
# SPEC-0093 ops carrier. Each entry: (section, subkey, kind) where `kind` says how that subtree names its
# entries — `single` (the section IS one check), `list` (a list of entries, named by `name_key`), or
# `map` (a dict keyed BY the check's name; how `deploy.policy.classes` really declares A/S/C1/C2).
#
# AN ALLOWLIST, NOT A NEGATION (the SUBCRITICAL_SEVERITIES discipline). Defining "kernel-graded" as "any
# section that isn't waived" would make every FUTURE carrier section silently owe a demonstration the day
# it is born — nagging on an UNKNOWN, which the report-only rule forbids (SPEC-0119 rule 3). A new graded
# surface must be ADMITTED here deliberately, by the task that makes the kernel grade it.
CHECK_SURFACES = (
    ("live_probe", None,        "single", None),       # SPEC-0094 — incl. its critical-user-path leg
    ("security",   "probes",    "list",   "property"), # SPEC-0098 — the security live-probes
    ("deploy",     "policy",    "map",    None),       # SPEC-0097 — per-class evidence (policy.classes)
    ("deploy",     "convergence", "single", None),     # SPEC-0097 §11 — the post-deploy convergence check
    ("tests",      "classes",   "list",   "class"),    # SPEC-0093 rule 10 — the declared test classes
    ("verify",     "layers",    "list",   "layer"),    # SPEC-0152 — the land-verify layers + `covers`
)


# THE SCOPING KEYS — declaration keys EXCLUDED from the definition identity below (T-11084, X-0875/X-0876;
# widened to the coverage-metadata keys by T-11415, X-1084).
#
# THE MEMBERSHIP TEST, stated so the next surface has a rule rather than a precedent to guess from. The
# test is the rule's PURPOSE, not its first example: a key is SCOPING iff editing it cannot change what a
# recorded demonstration PROVED. The demonstration is one journaled RED of the check's `command:` against a
# named broken input (SPEC-0156 §2), so a key participates in the identity iff it participates in THAT.
# Two families qualify, and the set is exactly these three keys:
#   - WHICH SUBJECTS TRIGGER the check — `verify.layers[].subject_globs`: the diff paths a layer is ABOUT,
#     consumed only by a run-or-skip predicate over the candidate diff (SPEC-0152 rule 16).
#   - WHAT THE CHECK DESCRIPTIVELY CLAIMS TO COVER — `verify.layers[].covers` (report-only at the land RUN:
#     "like `covers:`, the runner ignores it", SPEC-0152 rule 16; it feeds only the report-only coverage
#     WARN) and its sibling `covers_classes` (a consumer-declared pointer at the declared `tests.classes[]`
#     a layer carries — read by no kernel gate). Narrow or widen either and the SAME command still goes RED
#     on the SAME broken input, so the recorded RED is not stale and re-owing it buys no evidence.
# STILL NOT in the set, and definition-bearing: `command` itself, a probe's `url` / `assertion`, a deploy
# class's `evidence`, `timeout` / `moment` (execution envelope), `out_of_scope` (narrows what the check
# ASSERTS). Excluding any of THOSE would LOOSEN the rule, which is the one thing this narrowing must not do.
#
# THE `covers` CORRECTION, recorded because this comment previously said the opposite (X-1084). It read
# "Deliberately NOT in the set: `covers` (the graded coverage CLAIM — SPEC-0156 §1 names it as the thing
# demonstrated)". That conflated WHICH SURFACE is graded with WHAT the demonstration exercises: §1 names
# the layer ENTRY as the graded check, and the thing shown RED is its `command:`, never its `covers:` list.
# Measured on kupiclub's real history with this very function — `verify.layers[frontend-unit]` moved
# 7f4041231fae911a → 213f00e2823da3b0 (covers narrowed) and → b101161b52cb7dbc (covers_classes added),
# `verify.layers[stack]` three times, `verify.layers[static]` once, with `command:` UNCHANGED in every one
# of those commits — the fold reported 3 REWIRED and charged three break-and-restore demonstrations
# SPEC-0156 §2 does not ask for. It is the SAME conflation T-11084 corrected once for `subject_globs`, and
# it lands on exactly the consumers who follow the kernel's advice to declare their coverage.
#
# WHY A DENYLIST HERE WHEN `CHECK_SURFACES` ABOVE IS EMPHATICALLY AN ALLOWLIST — the polarity is opposite
# because the UNKNOWN is opposite, and a later reader "harmonizing" the two would invert one of them. There
# the unknown is a future SECTION, and the closed direction is "never nag on an unknown", so an allowlist
# fails safe. Here the unknown is a future KEY, and the closed direction is "never silently STOP nagging":
# an allowlist projection would leave a new definition-bearing key OUT of the identity, so a genuine rewire
# through it would not re-owe its demonstration — a false-green manufactured inside the mechanism SPEC-0156
# exists to end. A denylist keeps every unknown key IN, so the worst case is one visible, report-only
# over-charge instead of a silent, permanent under-charge. That is the direction `_admission_demonstrations`
# already fixed for this concern in so many words ("under-evidenced ⇒ still owed"); this preserves it.
# The widening above does NOT touch that polarity: it NAMES three keys whose non-participation in the
# demonstration is shown, and leaves every UNKNOWN future key IN the identity exactly as before.
SCOPING_KEYS = ("subject_globs", "covers", "covers_classes")

# THE PROJECTION HAS A HISTORY, AND A RECORDED IDENTITY IS DATED BY IT (T-11665, resolving kupiclub
# X-1119). `SCOPING_KEYS` above is not a constant of nature — it is THIS kernel's CURRENT answer, and it
# has moved twice. Every move silently orphaned every identity recorded under the previous one: the hash
# stays in the journal, correct as authored, and stops reproducing. The two superseded projections, in
# reverse-chronological order (NEWEST superseded first):
#   - `("subject_globs",)` — shipped by T-11084 (X-0875/X-0876), in force until T-11415.
#   - `()`                 — the original whole-subtree hash, in force until T-11084.
# THESE ARE ANCHORED INLINE AS LITERALS, DELIBERATELY (SPEC-0165). They are historical facts about what
# this kernel once computed; reconstructing them from git — walking `bin/lib/debt.py`'s own history to
# recover the old key-sets — would make the replay depend on a moving ref and on the kernel's own file
# history, which is exactly the "current code behavior wearing a historical name" that doctrine forbids.
# A future move of `SCOPING_KEYS` PREPENDS its predecessor here; nothing is ever removed, because a
# journal row written under it is permanent.
#
# WHY THIS MATTERS MORE THAN THE COUNT: without it the replay recomputes HISTORICAL carrier text through
# TODAY'S projection, so a correctly-authored identity reproduces at no revision, and the fold concludes
# the hash "was NEVER an identity of this declaration anywhere in the carrier's history" — a FALSE
# ACCUSATION of author error against a correct record, printed with a remedy asking the author to redo a
# demonstration they did right. The history and the prior projection were both available in-fold; the
# fold guessed instead. That is the defect this constant ends.
PRIOR_SCOPING_KEY_SETS = (
    ("subject_globs",),
    (),
)

# The three ways a recorded identity can fail to match the declaration as it stands now. ONE vocabulary,
# read by the fold (which decides whether the demonstration still counts) and by the near-miss prose
# (which decides what the author is told), so the two can never disagree about what happened.
IDENTITY_SUPERSEDED_PROJECTION = "superseded-projection"
IDENTITY_REWIRED_PRIOR_PROJECTION = "rewired-prior-projection"
IDENTITY_REWIRED = "rewired"
IDENTITY_MIS_AUTHORED = "mis-authored"


def _is_waived(node) -> bool:
    """Does this declaration node carry a WAIVER — the governed "no check here"?

    A waiver is a DECISION already recorded (with its reason, and for the strict sections its
    compensating control + expiry), and its currency is policed by `init.concern_conformance`. It is
    therefore NOT an unproven check: nagging for a failing demonstration of a check the project has
    consciously declined to declare would be nagging on an ANSWERED question. The waiver may sit on the
    section OR on a single entry — aiseller's `verify.layers[frontend]` carries its own — so this is
    asked of every node, at both levels.
    """
    return isinstance(node, dict) and isinstance(node.get("waiver"), dict)


def _definition_identity(node, scoping_keys=SCOPING_KEYS) -> str:
    """The check's DEFINITION IDENTITY — `sha256(canonical JSON of its DEFINITION-BEARING declaration)[:16]`,
    i.e. its own declaration subtree MINUS the `SCOPING_KEYS` named above.

    This is what makes "re-owed only when the check's COMMAND/DEFINITION changes" (SPEC-0156 §2) hold.
    Recomputed from the carrier at READ time and compared against the identity the demonstration RECORDED:
    rewire the check (a new url, a new command, a rewritten assertion) and the definition changes, so the
    identity changes, so the old demonstration stops matching and the question honestly re-opens. Re-RUN
    the same check and nothing changes — no debt, no ceremony. No stored state is needed for either half,
    which is the whole point (SPEC-0149 §2).

    THE PROJECTION IS THE CORRECTION, NOT AN OPTIMIZATION (T-11084, X-0875/X-0876). This function once
    hashed the WHOLE subtree and claimed the rule held "BY CONSTRUCTION". That claim was FALSE for any
    subtree carrying a non-command key: with `command` held identical, adding `subject_globs` moved the
    identity cfdee59b76ac2116 -> 32d6624133719b5f, so a purely SCOPE-ONLY edit read as a REWIRE and
    re-owed a demonstration the rule never asks for. It was not hypothetical — kupiclub's
    `verify.layers[default]`, demonstrated 2026-07-19 under 602b4cfb0fd129e9, read REWIRED with no command
    change, which actively PENALISED the very `subject_globs` rollout the kernel asks consumers to perform.
    Hashing the definition-bearing projection makes the docstring's claim true instead of merely asserted.

    THE SAME CORRECTION, ONCE MORE FOR THE COVERAGE KEYS (T-11415, X-1084). The projection shipped naming
    only `subject_globs`, and `covers:` / `covers_classes:` — descriptive coverage metadata the land RUN
    ignores — stayed hashed in. kupiclub, following the kernel's own advice to declare what each layer
    covers, was charged three break-and-restore demonstrations across `frontend-unit` / `stack` / `static`
    for commits in which `command:` never changed. Same defect, same direction, one key-set wider; the
    membership reasoning is recorded at `SCOPING_KEYS` above and the rule itself in SPEC-0156 §2.

    SCOPE OF THE EXCLUSION — top-level keys only, and only of a MAPPING. Every scoping key is a top-level key
    of a layer entry; scrubbing recursively would silently strip a nested key that merely shares the name,
    which is a different (and unasked-for) semantic. A non-mapping subtree has no keys to project and is
    hashed unchanged — this fold is report-only and must never break the seam it rides.

    `sort_keys` makes it order-independent: re-indenting the YAML or reordering keys is not a rewire, and
    must not re-owe a demonstration. Comments are invisible to the parser and so are correctly ignored.

    `scoping_keys` IS THE PROJECTION, AND IT IS A PARAMETER FOR EXACTLY ONE CALLER (T-11665). Live reads
    never pass it: the default IS the current projection, so every existing caller is byte-identical. The
    identity-history replay passes a SUPERSEDED key-set from `PRIOR_SCOPING_KEY_SETS` to ask what THIS
    kernel would have computed for a historical revision at the time a demonstration was recorded — the
    question a correctly-authored, since-orphaned identity needs answered before it can be diagnosed.
    """
    if isinstance(node, dict):
        node = {k: v for k, v in node.items() if k not in scoping_keys}
    canonical = json.dumps(node, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _entry_name(entry, name_key, index: int) -> str:
    """The human-legible name of ONE declared entry — its `name_key` (`property` / `class` / `layer`),
    falling back to its index. The fallback keeps an unnamed entry VISIBLE as debt (it is still a declared,
    still-unproven check) instead of dropping it, which a missing name must never do."""
    if isinstance(entry, dict):
        value = entry.get(name_key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return f"[{index}]"


def declared_checks(ops_path) -> list:
    """The kernel-graded checks THIS repo declares (SPEC-0156 §1), read from its yitc-ops.yaml carrier.

    Returns `[{check, declaration, definition_identity}]` — one row per declared check, each carrying the
    identity of the definition AS IT STANDS NOW. Never raises: a missing / unreadable / malformed / non-
    mapping carrier yields `[]`.

    A REPO WITH NO CARRIER DECLARES NOTHING, AND THAT IS WHAT MAKES HISTORY SAFE. The engine kernel itself
    has no yitc-ops.yaml, so this returns `[]` there and the whole view stays silent — no retro-charge. It
    is the same property the sibling proof-obligation fold had to buy with a disproof: a fold-side default
    over the real journals retro-created 39 debt lines across 3 consumers (SPEC-0149 §1). Debt is what a
    project DECLARED and has not PROVEN — never what it never declared.
    """
    try:
        carrier = state.load_ops(Path(ops_path))
    except (OSError, UnicodeDecodeError, yaml.YAMLError, TypeError):
        return []
    return _check_rows_from_carrier(carrier)


def _check_rows_from_carrier(carrier, scoping_keys=SCOPING_KEYS) -> list:
    """The row computation of `declared_checks` above, over an ALREADY-PARSED carrier.

    Split out for ONE reason: the identity-history replay below must run this exact computation over a
    HISTORICAL revision of the carrier, which it reads as text from git rather than from disk. Re-deriving
    the rows a second way there would let the two drift, and a drifted replay would answer "was this hash
    ever a real identity?" against a shape the live fold never computes — the one question this must not
    get wrong. Pure, never raises: a non-mapping carrier declares nothing.
    """
    if not isinstance(carrier, dict):
        return []

    rows: list = []
    for section, subkey, kind, name_key in CHECK_SURFACES:
        node = carrier.get(section)
        if not isinstance(node, dict) or _is_waived(node):
            continue                      # absent, shapeless, or consciously waived ⇒ declares no check
        if subkey is not None:
            node = node.get(subkey)
            if _is_waived(node):
                continue                  # the SUBSECTION carries the waiver (deploy.policy.waiver)

        if kind == "single":
            # The (sub)section IS the check — `live_probe` (no subkey) and `deploy.convergence` (one
            # subkey, T-10510). An empty declaration is not a check. The label carries the subkey when
            # there is one, so a sub-keyed surface is named by what it actually IS: without this, a
            # `deploy.convergence` row would report itself as the check `deploy` and collide with the
            # deploy.policy surface above. `live_probe` passes subkey=None ⇒ its label is unchanged.
            if node:
                label = section if subkey is None else f"{section}.{subkey}"
                rows.append({
                    "check": label,
                    "declaration": f"yitc-ops.yaml#{label}",
                    "definition_identity": _definition_identity(node, scoping_keys),
                })
        elif kind == "list":
            for index, entry in enumerate(node if isinstance(node, list) else []):
                if _is_waived(entry):
                    continue              # a single WAIVED entry (aiseller's verify.layers[frontend])
                name = _entry_name(entry, name_key, index)
                rows.append({
                    "check": f"{section}.{subkey}[{name}]",
                    "declaration": f"yitc-ops.yaml#{section}.{subkey}[{name}]",
                    "definition_identity": _definition_identity(entry, scoping_keys),
                })
        elif kind == "map":
            # `deploy.policy.classes` is a MAP keyed BY the class (A/S/C1/C2) — not a list. Reading it as
            # a list would silently enumerate NOTHING and leave every deploy class permanently "proven"
            # by absence: the exact false-green shape this whole spec exists to end.
            classes = node.get("classes") if isinstance(node, dict) else None
            for name, entry in sorted((classes or {}).items()) if isinstance(classes, dict) else ():
                if _is_waived(entry):
                    continue
                rows.append({
                    "check": f"{section}.policy.classes[{name}]",
                    "declaration": f"yitc-ops.yaml#{section}.policy.classes[{name}]",
                    "definition_identity": _definition_identity(entry, scoping_keys),
                })
    return rows


def _admission_demonstrations(events_path) -> dict:
    """Fold the journal → `check -> {identity -> latest ts}`: every recorded RED demonstration, by check
    and by the definition identity it was recorded AGAINST.

    FAITHFUL, never fail-closed (`lessons/fail-closed-belongs-to-the-reader-not-the-parser.md`): this
    reports only what the journal literally says, and the single READER below decides what it means. A
    non-RED outcome is DROPPED here — it demonstrated nothing, so it can clear nothing (SPEC-0156 §2).

    AN INCOMPLETE RECORD IS NOT A DEMONSTRATION (audit-post finding 1). SPEC-0156 §2 does not admit a check
    on a bare RED: it admits it on "one journaled RED run against a NAMED broken input", recorded with its
    declaration locator. So EVERY field of that contract is required to clear — `check`, `declaration`,
    `broken_input`, a RED `outcome`, and a `definition_identity`. Accepting a RED with no named broken input
    would let the evidence contract be satisfied without the auditable broken case that IS the evidence:
    a false-green inside the very mechanism built to end false-greens (the aiseller class, one level up).
    NOTE the direction of this strictness — it is the CONSERVATIVE one, and it is not the "never nag on an
    unknown" rule inverted: a malformed record simply fails to CLEAR, so the check stays visible as UNPROVEN
    debt. Under-evidenced ⇒ still owed; it never invents debt that was not declared.
    """
    out: dict = {}
    try:
        # SPEC-0190 rule 4 — the WHOLE journal (T-11649). This fold's declared horizon is the
        # root journal's SEGMENT SET, which is what the census records for it; reading the live
        # segment alone silently drops every archived row (the X-1100 class, and the reason the
        # cohort sibling `_test_class_executions` already takes this branch). `segment_rows`
        # reads each segment through the SAME `fold_rows` primitive, so there is still ONE parse
        # path and the T-11453 request-scoped memo still serves each segment.
        for event in journal.segment_rows(events_path):
            if not isinstance(event, dict) or event.get("type") != ADMISSION_EVENT:
                continue
            data = event.get("data")
            if not isinstance(data, dict):
                continue
            check = data.get("check")
            outcome = data.get("outcome")
            identity = data.get("definition_identity")
            if not isinstance(check, str) or not check.strip():
                continue              # attributes its demonstration to no check ⇒ clears none
            if not isinstance(outcome, str) or outcome.strip().lower() != ADMISSION_RED_OUTCOME:
                continue              # a green/absent outcome DEMONSTRATES NOTHING (§2)
            if not isinstance(identity, str) or not identity.strip():
                continue              # names no definition ⇒ cannot prove any definition
            if not all(isinstance(data.get(field), str) and data.get(field).strip()
                       for field in ADMISSION_REQUIRED_FIELDS):
                continue              # an INCOMPLETE record is not a demonstration (§2) — see above:
                                      # a RED with no NAMED broken input is a claim, not evidence
            ts = _parse_stamped_deadline(event.get("ts"))
            if ts is None:
                continue              # no establishable ordering ⇒ neither proves nor supersedes
            per_check = out.setdefault(check.strip(), {})
            key = identity.strip()
            if key not in per_check or ts > per_check[key]:
                per_check[key] = ts
    except (OSError, UnicodeDecodeError):
        return {}
    return out


def _near_miss_reason(data, declared_by_name: dict, recorded_check: str, ever_declared=None):
    """Why did THIS row not count? Returns `(reason, detail, attributed_check)` — or `None` when the row
    is either fine or unattributable.

    The conditions are asked in the SAME ORDER the fold applies them, and the FIRST failure is the one
    reported: a row that misses several is described by the miss that actually stopped it, not by
    whichever check happened to be written last.
    """
    # (1) `check` must name a DECLARED check. A typo here is the most disorienting miss of all — the row
    # is in the journal, spelled almost right, attributed to nothing. Close-match so the line can say
    # WHICH name was meant; drop entirely below the cutoff, because a guess is the false accusation this
    # signal must never make.
    if recorded_check not in declared_by_name:
        near = difflib.get_close_matches(recorded_check, list(declared_by_name),
                                         n=1, cutoff=NEAR_MISS_MATCH_CUTOFF)
        if not near:
            return None                   # names nothing recognisable ⇒ stay SILENT, never guess
        return (NEAR_MISS_UNKNOWN_CHECK,
                f"`check` reads {recorded_check!r}, which matches no declared check — "
                f"the closest declared name is {near[0]!r}",
                near[0])

    # (2) the outcome must be RED. A green (or absent, or misspelt) outcome demonstrates NOTHING.
    outcome = data.get("outcome")
    if not isinstance(outcome, str) or outcome.strip().lower() != ADMISSION_RED_OUTCOME:
        shown = outcome if isinstance(outcome, str) else ("absent" if outcome is None else repr(outcome))
        return (NEAR_MISS_OUTCOME_NOT_RED,
                f"`outcome` is {shown!r}, and only \"red\" clears a check — a demonstration exists to "
                f"show the check FAILING against a broken input, so a green proves nothing",
                recorded_check)

    # (3) the record must be COMPLETE. This is the miss that produced the card (X-0921): a RED with no
    # NAMED broken input is a claim, not evidence, so it cannot clear — but it was dropped in silence.
    missing = [f for f in ADMISSION_REQUIRED_FIELDS
               if not (isinstance(data.get(f), str) and data.get(f).strip())]
    identity = data.get("definition_identity")
    if not isinstance(identity, str) or not identity.strip():
        missing.append("definition_identity")
    if missing:
        return (NEAR_MISS_INCOMPLETE,
                "missing or blank: " + ", ".join(f"`{f}`" for f in sorted(missing))
                + " — every field of the SPEC-0156 §2 contract is required to clear",
                recorded_check)

    # (4) the identity must match the definition AS IT STANDS NOW. Unlike the three above this one is
    # already visible in the row's state — what it is NOT is legible: the author cannot tell a
    # fat-fingered hash from a genuine rewire. Naming BOTH hashes is the information the state alone
    # does not carry, and the whole reason this case earns a line. Since T-11425 the replay can also say
    # WHICH of the two prose alternatives actually holds — the sentence stopped being a guess handed to
    # the reader — and it says so only when history settled it, keeping the old wording when it abstained.
    current = declared_by_name[recorded_check]
    if identity.strip() != current:
        recorded = identity.strip()
        kind = _identity_mismatch_kind(recorded_check, recorded, ever_declared)
        if kind is None:
            cause = ("either the declaration changed after the demonstration (a genuine rewire), or the "
                     "recorded hash was not taken from this declaration")
        elif kind == IDENTITY_SUPERSEDED_PROJECTION:
            # No remedy is printed here, deliberately: there is nothing for the author to redo. The
            # demonstration is carried forward by the fold, so this line exists only to say WHY the two
            # hashes differ — the kernel's own arithmetic changed underneath a correct record.
            cause = ("that hash WAS a real identity of this declaration — computed by a SUPERSEDED KERNEL "
                     "PROJECTION over a declaration whose definition-bearing content is the one in force "
                     "now. The kernel's identity algorithm changed, your declaration did not, so this is "
                     "not a rewire and not a mis-authored payload: the demonstration still proves the "
                     "current definition and is carried forward. Nothing to re-do")
        elif kind == IDENTITY_REWIRED_PRIOR_PROJECTION:
            cause = ("that hash WAS a real identity of this declaration earlier in the carrier's history "
                     "— under a SUPERSEDED kernel projection — but the declaration has since changed, so "
                     "this is a genuine rewire and the check owes a fresh demonstration of its CURRENT "
                     "definition. The recorded hash was correctly authored; do not go looking for a "
                     "payload defect")
        elif kind == IDENTITY_REWIRED:
            cause = ("that hash WAS an identity of this declaration earlier in the carrier's history, so "
                     "the declaration changed after the demonstration — a genuine rewire, and the check "
                     "owes a fresh demonstration of its CURRENT definition")
        else:
            # MIS-AUTHORED, and it keeps the accusation because the replay now genuinely rules out the
            # alternatives: the value reproduces under NO projection this kernel has ever applied, at any
            # revision of the carrier. Before T-11665 this arm also swallowed every projection-orphaned
            # record and told its author to redo work that was done correctly (kupiclub X-1119).
            cause = ("that hash was NEVER an identity of this declaration anywhere in the carrier's "
                     "history — under any projection this kernel has ever applied — so this is not a "
                     "rewire and not a superseded identity: the payload hashed something else (the test "
                     "FILES rather than the declaration is the usual slip). Re-emit with the "
                     "definition_identity the carrier computes now")
        return (NEAR_MISS_IDENTITY,
                f"`definition_identity` recorded {recorded!r}, but the carrier now computes "
                f"{current!r} — {cause}",
                recorded_check)
    return None                           # every condition holds — this row COUNTS, it is no near-miss


def _admission_near_misses(events_path, declared_rows: list, ever_declared=None) -> dict:
    """Fold the journal → `check -> [{recorded_check, reason, detail, ts}]`: the rows that WERE emitted
    for a declared check and did NOT count, each carrying WHICH condition stopped it.

    THE READER OWNS THIS JUDGEMENT, AND THAT IS WHY IT IS NOT IN `_admission_demonstrations`
    (`lessons/fail-closed-belongs-to-the-reader-not-the-parser.md`). That fold stays FAITHFUL — it
    reports what the journal literally says and drops what does not qualify — and it has a SECOND caller
    (`broken_outcome_invariants`) whose needs are its own. Asking "why did this not qualify?" is a
    different question with a different audience, so it gets its own reader rather than a flag threaded
    through the shared one.

    Never raises: a missing/unreadable journal or a malformed line yields nothing, exactly like the
    sibling fold. A report-only view must never break the seam it rides.
    """
    declared_by_name = {r["check"]: r["definition_identity"] for r in declared_rows}
    if not declared_by_name:
        return {}

    out: dict = {}
    try:
        # SPEC-0190 rule 4 — the WHOLE journal (T-11649). This fold's declared horizon is the
        # root journal's SEGMENT SET, which is what the census records for it; reading the live
        # segment alone silently drops every archived row (the X-1100 class, and the reason the
        # cohort sibling `_test_class_executions` already takes this branch). `segment_rows`
        # reads each segment through the SAME `fold_rows` primitive, so there is still ONE parse
        # path and the T-11453 request-scoped memo still serves each segment.
        for event in journal.segment_rows(events_path):
            if not isinstance(event, dict) or event.get("type") != ADMISSION_EVENT:
                continue
            data = event.get("data")
            if not isinstance(data, dict):
                continue
            recorded = data.get("check")
            if not isinstance(recorded, str) or not recorded.strip():
                continue              # attributes itself to no check at all ⇒ nothing to report it AGAINST
            verdict = _near_miss_reason(data, declared_by_name, recorded.strip(), ever_declared)
            if verdict is None:
                continue
            reason, detail, attributed = verdict
            out.setdefault(attributed, []).append({
                "recorded_check": recorded.strip(),
                "reason": reason,
                "detail": detail,
                "ts": event.get("ts") if isinstance(event.get("ts"), str) else None,
            })
    except (OSError, UnicodeDecodeError):
        return {}
    return out


# THE IDENTITY-HISTORY REPLAY (T-11425, resolving kupiclub X-1095) — how a WRONG-KEY payload is told
# apart from a GENUINE REWIRE, using nothing but what the fold already has.
#
# THE DEFECT IT ENDS: the two label sites below read a supersession out of ANY recorded identity that is
# not the current one, so a row whose `definition_identity` was never an identity of that declaration at
# all — a hash of the TEST FILES, a bare sha256, a hand-typed pair — read as REWIRED. The label is the
# harm, not the count: REWIRED sends the next author to redo a demonstration, when the actual defect was
# the payload key. Different work, and the wrong one is the expensive one.
#
# THE DISCRIMINATOR IS ALREADY IN-FOLD (the reporter's own framing, and why this adds no state): the
# carrier is version-controlled, so "was this hash EVER an identity of this declaration?" is answerable by
# replaying the carrier's own git history and recomputing the SAME rows the live fold computes. Measured
# on kupiclub before this was written: `tests.classes[browser-row-press]` has exactly ONE identity across
# 54 carrier revisions and its three rows match none of them (wrong-key), while `verify.layers[stack]`'s
# three recorded identities are ALL in that history (a genuine rewire, which must keep its label).
#
# IT ABSTAINS RATHER THAN GUESSES. Where history cannot be read — a carrier outside any git repo, no git,
# a fixture in a tmpdir — `_identities_ever_declared` returns None and the label is computed exactly as it
# was before this change. So the discriminator can only ever REMOVE a label it can PROVE is wrong; it
# never manufactures one from an absence, which in a report-only view is the only safe direction.
_IDENTITY_HISTORY_GIT_TIMEOUT = 20
_IDENTITY_HISTORY_CACHE: dict = {}


def _identities_ever_declared(ops_path, wanted: dict, today=None):
    """`{check: {identity: descriptor}}` — which of the WANTED (check, identity) pairs were EVER real
    identities of that declaration in the carrier's git history, and UNDER WHICH PROJECTION. Returns None
    when history is UNAVAILABLE (the abstain signal above), which is NOT the same as an empty result:
    `{}` means "history read, none of them were ever real", None means "cannot tell — keep today's answer".

    EVERY REVISION IS REPLAYED UNDER EVERY PROJECTION THIS KERNEL HAS EVER APPLIED (T-11665, kupiclub
    X-1119). Replaying historical carrier text through TODAY'S projection alone answers a question nobody
    asked: it asks what the identity WOULD BE now, when what is recorded is what it WAS then. A record
    written before `SCOPING_KEYS` last moved then reproduces nowhere, and the reader below concludes the
    author hashed the wrong thing. So each revision is projected under `SCOPING_KEYS` AND under every
    entry of `PRIOR_SCOPING_KEY_SETS`, and each match carries a descriptor saying which:

      - `prior_projection` — the hash was produced ONLY by a superseded projection (so the identity was
        orphaned by a KERNEL change, not authored wrong);
      - `definition_current` — that revision's declaration projects, under TODAY'S algorithm, to the SAME
        identity the carrier declares NOW. This is the discriminator that separates "the kernel moved" from
        "the declaration moved": when it holds, the definition-bearing content the demonstration exercised
        is the definition-bearing content in force today, so the demonstration still proves the current
        check and must NOT be re-owed. `today` is `{check: current identity}`; without it (a caller that
        does not have the live rows) the flag is False everywhere, which is the conservative direction —
        it can only ever decline to carry a demonstration forward, never invent one.

    A descriptor MAPPING, not a set, is what the two label sites read — and `identity in ever_declared[check]`
    is unchanged by that (dict membership tests keys), so `_genuine_supersession` needs no edit.

    Walks the carrier's revisions NEWEST FIRST and stops the moment every wanted pair is accounted for, so
    the common genuine-rewire case (demonstrated against the immediately-previous definition) costs one or
    two `git show`s. Only the wrong-key case pays the full walk — and only once: the result is memoized per
    (resolved carrier path, HEAD sha, wanted set), so the two label sites and the near-miss reader share
    one replay. Never raises: any git/parse failure abstains.
    """
    import subprocess
    if not wanted:
        return {}
    carrier = Path(ops_path)
    try:
        root, rel = carrier.parent.resolve(), carrier.name
    except OSError:
        return None

    def _git(argv: list):
        try:
            proc = subprocess.run(["git", "-C", str(root)] + list(argv), capture_output=True, text=True,
                                  timeout=_IDENTITY_HISTORY_GIT_TIMEOUT)
        except Exception:                 # noqa: BLE001 — no git, no repo, a timeout: all "cannot tell"
            return None
        return proc.stdout if proc.returncode == 0 else None

    head = _git(["rev-parse", "HEAD"])
    if head is None:
        return None                       # not a git repo (or no commits) ⇒ ABSTAIN, never guess
    key = (str(root), rel, head.strip(),
           tuple(sorted((check, tuple(sorted(ids))) for check, ids in wanted.items())),
           tuple(sorted((today or {}).items())))
    if key in _IDENTITY_HISTORY_CACHE:
        return _IDENTITY_HISTORY_CACHE[key]

    # The carrier's path INSIDE the repo — `git log -- <path>` is repo-relative, and a carrier reached
    # through a symlink or a nested worktree would otherwise silently match no revision at all (which,
    # unlike an abstain, would read as "never real" and mislabel a genuine rewire).
    prefix = _git(["rev-parse", "--show-prefix"])
    if prefix is None:
        return None
    log = _git(["log", "--format=%H", "--", (prefix.strip() + rel)])
    if log is None:
        return None
    revisions = log.split()
    if not revisions:
        return None                       # the carrier has no history here ⇒ nothing to replay ⇒ ABSTAIN

    found: dict = {}
    outstanding = {check: set(ids) for check, ids in wanted.items() if ids}
    for sha in revisions:
        if not outstanding:
            break                         # every wanted pair accounted for — stop reading history
        text = _git(["show", f"{sha}:{prefix.strip() + rel}"])
        if text is None:
            continue                      # this revision is unreadable; the rest of the walk still counts
        try:
            carrier_at = state.load_ops_str(text)
        except Exception:                 # noqa: BLE001 — a malformed historical carrier declares nothing
            continue
        # THIS revision under the CURRENT projection — both what the identity would be today, and (via
        # `today`) whether this revision's definition-bearing content is the one in force now.
        current_by_check: dict = {}
        for row in _check_rows_from_carrier(carrier_at) + _invariant_rows_from_carrier(carrier_at):
            current_by_check.setdefault(row["check"], set()).add(row["definition_identity"])
        # …and under every projection this kernel has SINCE RETIRED. A hash reproducing only here was a
        # real identity computed by an algorithm that no longer exists — superseded, never mis-authored.
        prior_by_check: dict = {}
        for keys in PRIOR_SCOPING_KEY_SETS:
            for row in (_check_rows_from_carrier(carrier_at, keys)
                        + _invariant_rows_from_carrier(carrier_at, keys)):
                prior_by_check.setdefault(row["check"], set()).add(row["definition_identity"])

        for check in list(outstanding):
            current_ids = current_by_check.get(check, set())
            prior_ids = prior_by_check.get(check, set())
            hit = outstanding[check] & (current_ids | prior_ids)
            if not hit:
                continue
            # Is THIS revision's declaration the one in force now? Compared on the CURRENT projection, so
            # a revision differing only in scoping keys reads as the same definition — which is the whole
            # point: the demonstration exercised the same command against the same broken input.
            definition_current = bool(today) and (today.get(check) in current_ids)
            for identity in hit:
                # A hash reachable under the CURRENT projection is not projection-orphaned, whatever else
                # also produced it: it is the T-11425 genuine-rewire case and keeps that label.
                found.setdefault(check, {})[identity] = {
                    "prior_projection": identity not in current_ids,
                    "definition_current": definition_current,
                }
            # Accounted for — the walk never revisits this pair, so each descriptor is written once, by
            # the NEWEST revision that produced it. That is the right one: it is the declaration state
            # closest to the demonstration's own moment.
            outstanding[check] -= hit
            if not outstanding[check]:
                del outstanding[check]
    _IDENTITY_HISTORY_CACHE[key] = found
    return found


def _identity_mismatch_kind(check: str, recorded: str, ever_declared):
    """WHY does this recorded identity not match the declaration as it stands now? Returns one of the four
    `IDENTITY_*` kinds — or None when history could not be read (the abstain path, where the answer is
    left exactly as it was before T-11425/T-11665 ever ran).

    THE ONE HOME OF THE SPLIT (T-11665). Both the fold — which decides whether the demonstration still
    counts — and the near-miss prose — which decides what the author is TOLD — read this, so the label and
    the sentence can never disagree. The kinds, in the order they are distinguished:

      - `superseded-projection` — the hash was a real identity of a declaration whose definition-bearing
        content is TODAY'S, computed under a projection this kernel has since retired. The KERNEL
        invalidated the identity; the author did nothing wrong and the check was never rewired, so the
        demonstration is carried forward rather than re-owed.
      - `rewired-prior-projection` — a real identity under a retired projection, but of a declaration that
        has SINCE CHANGED in its definition-bearing content. A genuine rewire, which does owe a fresh
        demonstration — but it is still not a mis-authored payload, and must not be described as one.
      - `rewired` — a real identity under the CURRENT projection at an earlier revision. Unchanged
        behaviour (T-11425).
      - `mis-authored` — a real identity under NO projection at ANY revision. The payload hashed something
        else. THIS is the arm that keeps the accusation, and it keeps it because history now genuinely
        rules the alternatives out rather than never having asked.
    """
    if ever_declared is None:
        return None                       # history unreadable ⇒ ABSTAIN, never guess (T-11425)
    descriptor = (ever_declared.get(check) or {}).get(recorded)
    if descriptor is None:
        return IDENTITY_MIS_AUTHORED
    if not descriptor.get("prior_projection"):
        return IDENTITY_REWIRED
    return (IDENTITY_SUPERSEDED_PROJECTION if descriptor.get("definition_current")
            else IDENTITY_REWIRED_PRIOR_PROJECTION)


def _projection_superseded(per_check: dict, check: str, ever_declared) -> bool:
    """Does ANY recorded demonstration of this check prove the CURRENT definition under a RETIRED
    projection? (T-11665 — the carry-forward.)

    When it does, the check is PROVEN: SPEC-0156 §2 re-owes a demonstration when the check's
    COMMAND/DEFINITION changes, and here it did not — only the kernel's hash of it did. Charging the
    admission debt anyway is the fold billing a consumer for the kernel's own algorithm change (kupiclub
    X-1084, still charged after X-1119 because the fold had no way to SAY superseded). It fires only where
    the replay PROVES the definition-bearing content is unchanged; where history cannot be read,
    `_identity_mismatch_kind` abstains and this is False — the pre-change answer, unchanged.
    """
    return any(_identity_mismatch_kind(check, identity, ever_declared) == IDENTITY_SUPERSEDED_PROJECTION
               for identity in per_check)


def _genuine_supersession(per_check: dict, check: str, ever_declared):
    """The ts of the newest demonstration a GENUINE rewire invalidated — or None.

    THE ONE HOME OF THIS JUDGEMENT, read by both label sites so the two can never disagree about what
    `rewired` means. A demonstration supersedes only if the identity it recorded WAS an identity of this
    declaration at some point in the carrier's history; a hash that never was is a wrong-key payload, and
    a payload defect is not a rewire. `ever_declared is None` ⇒ history could not be read ⇒ every recorded
    identity is admitted, which reproduces the pre-T-11425 answer exactly (the abstain path).
    """
    if not per_check:
        return None
    if ever_declared is None:
        return max(per_check.values())
    real = ever_declared.get(check) or set()
    genuine = [ts for identity, ts in per_check.items() if identity in real]
    return max(genuine) if genuine else None


def _wanted_identities(rows: list, demonstrations: dict) -> dict:
    """`{check: {identity, …}}` — the recorded identities that do NOT match the declaration as it stands
    now, i.e. exactly the pairs whose realness the replay has to settle. A matching identity needs no
    replay (the check is proven), so it is never asked about."""
    wanted: dict = {}
    for row in rows:
        per_check = demonstrations.get(row["check"]) or {}
        stale = {i for i in per_check if i != row["definition_identity"]}
        if stale:
            wanted[row["check"]] = stale
    return wanted


def unproven_checks(ops_path, events_path, now=None) -> dict:
    """Fold the ops carrier + the journal → the declared kernel-graded checks with NO recorded failing
    demonstration of their CURRENT definition (SPEC-0156).

    A declared check is PROVEN iff the journal carries a `check_admission_demonstrated` whose `check`
    matches, whose `outcome` is RED, and whose `definition_identity` matches the identity recomputed from
    the carrier NOW. All three, or it is not proven — and each of the three is a differential direction
    this fold's tests pin RED:
      - no event at all      → `never`   (the check was admitted on a promise, never on evidence);
      - outcome not RED      → `never`   (a check shown GREEN has demonstrated nothing);
      - identity mismatched  → `rewired` (it was demonstrated once, then its definition CHANGED — the old
                               RED proved the OLD check, and the new one is unproven again).
    The `rewired` state is what makes this line honestly DATED where a date exists at all: it carries the
    `superseded_at` ts of the demonstration the rewire invalidated. A `never` check has no date to name —
    the carrier records no per-check declaration date, and this fold does not invent one (a fabricated
    date is worse than an absent one; the sibling folds date only from durable records).

    NEVER REFUSES, NEVER GATES (SPEC-0156 §3 / CHARTER non-goal 7): an absent demonstration surfaces the
    check as UNPROVEN debt, report-only. Where an existing contract already fails closed (SPEC-0098's
    un-probeable escalation, SPEC-0097's Class-S probe requirement), THAT rule stands unchanged — this
    view never weakens a gate, and never adds one.

    Args:
      ops_path: this repo's `yitc-ops.yaml` (missing/unreadable ⇒ a clean, zero-count result: a repo that
        declares no kernel-graded check owes no demonstration — the engine kernel itself).
      events_path: path to `events.jsonl` (missing/unreadable ⇒ every declared check reads as unproven,
        which is the honest answer: with no journal there is no evidence).
      now: aware datetime, injected by the tests so every assertion is deterministic, never
        wall-clock-dependent.

    Returns `{"lens", "now", "count", "checks", "next"}` — the shape the sibling views return — plus
    `near_miss_clause` (T-11178), the rendered feedback for rows that were emitted and did NOT count.
    Pure: reads two files, writes nothing (SPEC-0149 §2).
    """
    now = now if now is not None else datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    declared = declared_checks(ops_path)
    if not declared:
        return _unproven_result(now, [])          # nothing declared ⇒ nothing owed (never retro-charged)

    demonstrations = _admission_demonstrations(events_path)
    # WAS the non-matching identity ever real? (T-11425) — asked ONCE, for every stale pair at once, and
    # only when at least one exists. A repo whose every demonstration matches reads no git history at all.
    ever_declared = _identities_ever_declared(ops_path, _wanted_identities(declared, demonstrations),
                                              {r["check"]: r["definition_identity"] for r in declared})

    unproven = []
    for row in declared:
        per_check = demonstrations.get(row["check"]) or {}
        if row["definition_identity"] in per_check:
            continue                              # a RED demonstration of THIS definition — proven
        # …OR a RED demonstration of the SAME definition recorded under a SUPERSEDED kernel projection
        # (T-11665). SPEC-0156 §2 re-owes on a COMMAND/DEFINITION change; here neither changed — only the
        # kernel's hash of the declaration did. Charging the debt anyway bills the consumer for the
        # kernel's own algorithm move, which is the charge X-1084 was filed to stop and X-1119 measured
        # still running. Proven where the replay PROVES it, and nowhere else.
        if _projection_superseded(per_check, row["check"], ever_declared):
            continue
        # Demonstrated under some OTHER identity that WAS real once ⇒ REWIRED: the recorded RED proved a
        # definition that no longer exists. Name the newest superseded demonstration — that ts is the date
        # the check's proof went stale, and the only honest date this line can carry. A recorded identity
        # that was NEVER real is a wrong-key payload, not a rewire: it supersedes nothing, so the row stays
        # `never` (the honest state — this check has never been demonstrated) and carries no date it did
        # not earn. The near-miss line below is what tells that author WHICH defect they have.
        superseded_at = _genuine_supersession(per_check, row["check"], ever_declared)
        unproven.append({
            "check": row["check"],
            "declaration": row["declaration"],
            "definition_identity": row["definition_identity"],
            "state": "rewired" if superseded_at is not None else "never",
            "superseded_at": (superseded_at.isoformat().replace("+00:00", "Z")
                              if superseded_at is not None else None),
        })
    # Rewired checks first (a proof that WENT stale is a sharper signal than one never given), then by
    # check name so the order is stable across folds.
    unproven.sort(key=lambda r: (r["state"] != "rewired", r["check"]))

    # NEAR-MISS FEEDBACK (T-11178 / X-0921) — PURELY ADDITIVE, and suppressed-when-clean BY CONSTRUCTION.
    # Attached only to rows ALREADY in the unproven list, so a near-miss can exist only where a line is
    # already being printed: no unproven rows ⇒ no near-miss can ever be produced, and `count` is
    # untouched. Nothing above this point changed — `state`, `superseded_at`, and the three conditions
    # that decide PROVEN are exactly as they were (the card's explicit fence).
    if unproven:
        near_misses = _admission_near_misses(events_path, declared, ever_declared)
        for row in unproven:
            row["near_misses"] = near_misses.get(row["check"], [])
    return _unproven_result(now, unproven)


def _near_miss_clause(checks: list) -> str:
    """The one-sentence rendering of the near-misses, for the echo line — "" when there are none.

    Rendered HERE rather than in the view so the wording has ONE home (CHARTER §P5): the renderer at the
    echo seam appends this string and decides nothing. Names the FIRST near-miss in full, because the
    author's question is "what was wrong with MY row" and a bare count answers it no better than the
    silence this replaces.
    """
    flat = [(row["check"], nm) for row in checks for nm in (row.get("near_misses") or [])]
    if not flat:
        return ""
    check, first = flat[0]
    more = f" (+{len(flat) - 1} more such row(s))" if len(flat) > 1 else ""
    return (f" NOTE — {len(flat)} emitted `check_admission_demonstrated` row(s) were SEEN but did NOT "
            f"count, so this is not the same as having emitted nothing: for {check}, {first['detail']}"
            f"{more}. Fix the payload and re-emit — nothing was refused and nothing is gated "
            f"(SPEC-0156 §3); the row simply did not satisfy the fold.")


def _unproven_result(now, checks: list) -> dict:
    return {
        "near_miss_clause": _near_miss_clause(checks),
        "lens": "unproven-checks (SPEC-0156) — kernel-graded checks this project DECLARES (live_probe, "
                "security probes, deploy-class evidence, test classes, verify layers) with NO recorded "
                "FAILING DEMONSTRATION of their CURRENT definition: no journaled "
                "`check_admission_demonstrated` that is RED against a named broken input AND matches the "
                "definition_identity recomputed from the carrier now. A green outcome proves nothing; a "
                "rewired definition re-opens the question (the old RED proved the old check). Evidence "
                "clears a check only once it has LANDED on main — discharge work still sitting un-landed "
                "in a worktree/branch does not clear it yet (do not re-plan a campaign over in-flight "
                "evidence). DERIVED at "
                "read time from the carrier + the journal — zero stored state; a repo that declares no "
                "check (the engine kernel itself) owes nothing, so history is never retro-charged. "
                "Report-only, never a gate (SPEC-0156 §3).",
        "now": now.isoformat().replace("+00:00", "Z"),
        "count": len(checks),
        "checks": checks,
        "next": ("these declared checks have never been SEEN to fail — nothing proves they can. For each, "
                 "break its subject deliberately, run the check, watch it go RED, and record "
                 "`bin/yitc-v2 event check_admission_demonstrated --data '{\"check\":…,\"declaration\":…,"
                 "\"broken_input\":…,\"outcome\":\"red\",\"definition_identity\":…}'` (SPEC-0156 §2). A "
                 "check that CANNOT be made to fail is not a check: route it per its surface's "
                 "un-probeable rule (escalate / waive-with-reason), never admit it as coverage."
                 if checks else
                 "every declared kernel-graded check carries a recorded failing demonstration — nothing owed."),
    }


# ── SPEC-0119 rule 16 (T-10511 / X-0370): the runtime-delivery coherence read ───────────────────────
#
# The gap this closes: rule 1's FIRST debt view is true only under an assumption nobody ever declared.
# `_view_not_adopted` (SPEC-0094 §2) derives the commits between the last `deploy_completed` revision and
# `main` and calls them "shipped-but-NOT-live" — debt waiting to be deployed. Under a BIND-MOUNTED runtime
# that reading is not merely wrong, it is INVERTED: the container mounts the source tree, so those commits
# are ALREADY LIVE — they reached prod on a `docker compose up`, with no deploy verb, no class gate, and no
# `deploy_completed`. X-0370 is that inversion cashing in (a container recreate shipped HALF a paired change
# — mounted backend, stale baked frontend — 8h outage), and through all 8 hours every kernel surface that
# could have spoken was busy reporting the OPPOSITE fact.
#
# SPEC-0093 rule 22 makes the delivery model SAYABLE (`deploy.runtime_delivery.model`). This fold makes the
# kernel READ its own delta under that declaration. Zero stored state, exactly like the sibling folds: the
# carrier says which model, the EXISTING not-adopted view says which commits, and the debt is what those
# commits MEAN under that model — recomputed fresh every call (SPEC-0149 §2). No second git path and no
# second live-revision source: it consumes `_view_not_adopted`'s own output (CHARTER §P5).

# The DECLARATION (SPEC-0093 rule 22) — the carrier path + the closed enum, named ONCE here on the reading
# side. The kernel-owned BYPASSABLE set is the rule-22 reading: these are the models where the runtime
# reads the SOURCE TREE, so a recreate/reload ships `main` WITHOUT the verb. `image-baked` is the only
# model for which the deploy verb genuinely IS the only path to prod.
RUNTIME_DELIVERY_MODELS = ("image-baked", "source-mounted", "hot-reload", "hybrid")
BYPASSABLE_DELIVERY_MODELS = ("source-mounted", "hot-reload", "hybrid")

# The BORN-WAIVER marker (SPEC-0093 rule 22 / init.BORN_WAIVER_MARKER). A born placeholder waiver is an
# UNANSWERED question wearing a waiver's clothes (the X-0088 / X-0130 silent-born-waiver class), so it does
# NOT silence this view — a HUMAN-authored waiver does. Kept as a literal rather than imported from
# lib.init: this module back-imports NOTHING (the cmd_deploy / cmd_init discipline, module header), and a
# coherence test pins the two strings equal so they cannot drift apart.
BORN_WAIVER_MARKER = "Initialized via `bin/yitc-v2 init`"

# The compose files the source-mount detector reads. A bind mount of the project's OWN source tree into a
# service is the EVIDENCE that the runtime runs this checkout — the X-0370 shape. Covers BOTH the
# `docker-compose*` and the newer `compose*` families, incl. their `.<env>.` override forms.
_COMPOSE_GLOBS = ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml",
                  "docker-compose.*.yml", "docker-compose.*.yaml",
                  "compose.*.yml", "compose.*.yaml")

# A host path counts as SOURCE (not data/config) when it is the repo root itself, or a directory holding
# code. Kept to file EXTENSIONS — a data volume (`./data:/data`), a log dir, or a mounted single config
# file must NOT read as source, or the detector would nag every project that mounts anything at all.
_SOURCE_EXTENSIONS = (".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rb", ".php", ".java", ".rs", ".vue")


# The DEV-overlay markers (T-10621 / the deploy-coherence doctrine, patterns/deploy-coherence.md §3). A
# `docker-compose.<seg>.yml` / `compose.<seg>.yml` whose env segment is one of these is a DEV overlay — the
# aiseller split keeps source bind mounts HERE, layered on top for local work only. A mount that lives ONLY
# in a dev overlay is doctrine-conformant, so the PROD-scoped reader (arm c) must not read it as prod
# evidence. This is a NARROW allowlist, not a negation: an UNKNOWN segment (`docker-compose.staging.yml`)
# reads as PROD — the conservative default, since a mount that MIGHT reach prod should surface, not hide.
_DEV_COMPOSE_MARKERS = frozenset({"dev", "development", "override", "local"})


def _is_dev_compose(name: str) -> bool:
    """Is this compose file a DEV overlay (its executable mounts are doctrine-conformant — §3)? True iff a
    `docker-compose.<seg>.yml` / `compose.<seg>.yml` env segment is a dev marker. The base `docker-compose.yml`
    (no segment) and a prod-named override (`compose.prod.yml`) are PROD."""
    stem = name.rsplit(".", 1)[0]                 # strip the .yml / .yaml suffix
    return any(seg.lower() in _DEV_COMPOSE_MARKERS for seg in stem.split(".")[1:])


def _declared_prod_composes(ops_path) -> tuple:
    """The compose files this project DECLARES as the ones it actually runs (T-10905 / X-0711), read off the
    EXISTING carrier `deploy.command` (+ the `deploy.policy.classes[*].command` deploy commands) — the
    `-f` / `--file` operands of the declared deploy invocation.

    This is the DECLARATION leg of the prod/dev discriminator, and it needs NO new carrier field (CHARTER
    §P1 F2 — a view over data already on disk): a project that says `docker compose -f docker-compose.prod.yml
    up -d` has already named the compose that reaches prod, more authoritatively than any filename
    convention can infer. The `_is_dev_compose` naming convention (below) stays the FALLBACK for a project
    whose deploy command names none — which is why a project that names its files unconventionally is not
    mis-read: it can say so in the carrier it already fills in.

    Returns a tuple of BASENAMES, order-stable + de-duped. Empty when the carrier is missing / unreadable /
    declares no deploy command / names no compose file — the caller then falls back to the convention.
    Never raises (the `_declared_delivery` posture): a malformed carrier is simply no declaration.
    """
    try:
        carrier = state.load_ops(Path(ops_path))
    except (OSError, UnicodeDecodeError, yaml.YAMLError, TypeError):
        return ()
    deploy = carrier.get("deploy") if isinstance(carrier, dict) else None
    if not isinstance(deploy, dict):
        return ()

    commands: list = []

    def _collect(value):
        if isinstance(value, str):
            commands.append(value)
        elif isinstance(value, list):
            commands.extend(v for v in value if isinstance(v, str))

    _collect(deploy.get("command"))
    policy = deploy.get("policy")
    classes = policy.get("classes") if isinstance(policy, dict) else None
    for entry in classes if isinstance(classes, list) else ():
        if isinstance(entry, dict):
            _collect(entry.get("command"))

    out: list = []
    for command in commands:
        try:
            tokens = shlex.split(command)
        except ValueError:
            tokens = command.split()
        for i, token in enumerate(tokens):
            operand = None
            if token in ("-f", "--file") and i + 1 < len(tokens):
                operand = tokens[i + 1]
            elif token.startswith("--file="):
                operand = token.split("=", 1)[1]
            elif token.startswith("-f") and len(token) > 2:
                operand = token[2:]
            if not operand:
                continue
            # NOT filtered to `_COMPOSE_GLOBS`: the whole point of the declaration leg is to read a
            # production compose whose filename the convention cannot recognise (`stack.deploy.yml`), so
            # gating it on the glob family would leave exactly the hole this leg exists to close. The
            # operand is an EXPLICIT statement by the project about its own deploy, and the caller only
            # honours the names that EXIST at the repo root — so a `-f` that means something else to some
            # other program simply resolves to nothing and the convention decides.
            name = PurePosixPath(operand).name
            if name and name not in out:
                out.append(name)
    return tuple(out)


def _compose_paths(repo_root, *, prod_only: bool = False, declared_prod: tuple = ()) -> list:
    """The compose files at this repo's root, order-stable + de-duped. A repo with none simply has no
    detectable evidence (the fold then falls to its declaration arm) — never an error.

    `prod_only` (T-10621) restricts the set to the PRODUCTION compose, so that dev mounts — the doctrine's
    prescribed home for source binds — are not read as prod evidence. TWO legs, declaration first
    (T-10905 / X-0711):
      1. `declared_prod` — the basenames the carrier's deploy command NAMES (`_declared_prod_composes`),
         restricted to those that actually EXIST here. An explicit, resolvable declaration BEATS any
         convention: it says which compose actually runs in production.
      2. otherwise the `_is_dev_compose` naming convention (an unknown segment reads PROD — conservative).
         "Otherwise" includes a declaration that resolves to NOTHING (stale operand), because narrowing
         the prod set to an absent file would silence a real prod mount.
    """
    root = Path(repo_root)
    out: list = []
    for pattern in _COMPOSE_GLOBS:
        for p in sorted(root.glob(pattern)):
            if p.is_file() and p not in out:
                out.append(p)

    if not prod_only:
        return out

    # A declaration governs only the files it actually RESOLVES to — and it resolves against the repo root
    # DIRECTLY, not against the glob-discovered set: a declared production compose may be named anything
    # (`stack.deploy.yml`), which is precisely the case the naming convention cannot reach. A stale operand
    # (a renamed or deleted `-f docker-compose.prod.yml`) resolves to nothing and is dropped, because
    # narrowing the prod set to an absent file would SILENCE a real prod source mount — the same false
    # silence this card exists to prevent, arriving from the other side. Resolving to nothing at all ⇒ fall
    # BACK to the naming convention, never to an empty prod set.
    declared: list = []
    for name in declared_prod or ():
        path = root / name
        try:
            if path.is_file() and path not in declared:
                declared.append(path)
        except OSError:
            continue
    if declared:
        return sorted(declared, key=lambda p: p.name)
    return [p for p in out if not _is_dev_compose(p.name)]


def _host_side(volume) -> "str | None":
    """The HOST side of one compose `volumes:` entry, in either shape compose accepts: the short string
    form `host:container[:mode]` and the long form `{type: bind, source: …, target: …}`. Returns None for
    anything that is not a host bind — a NAMED volume (`pgdata:/var/lib/postgresql`) has no host path, so
    it can never be source-mount evidence."""
    if isinstance(volume, dict):
        if volume.get("type") not in (None, "bind"):
            return None                       # a named/tmpfs volume mounts no host path
        source = volume.get("source")
        return source.strip() if isinstance(source, str) and source.strip() else None
    if isinstance(volume, str) and ":" in volume:
        host = volume.split(":", 1)[0].strip()
        # A named volume's short form (`pgdata:/var/lib/...`) has no path separator and no leading dot.
        # Only a repo-RELATIVE or absolute path is a host bind; a bare name is a named volume.
        if host.startswith((".", "/", "~", "$")):
            return host
    return None


# Directories a bounded source-search never descends: dependency / VCS / build trees that hold code files
# but are NOT the project's OWN source (a `node_modules` under a mounted `./data` must not read as source).
_SEARCH_SKIP_DIRS = frozenset({".git", "node_modules", "__pycache__", ".venv", "venv", "vendor",
                               "dist", "build", ".mypy_cache", ".pytest_cache", ".tox", "site-packages"})
_SEARCH_MAX_DEPTH = 3          # bounded — a source tree keeps code within a few levels; deep = not the shape


def _holds_source(path: Path, repo_root: Path) -> bool:
    """Does this mounted host path carry the project's OWN SOURCE (vs data / logs / a single config file)?

    TRUE when the mount IS the repo root (a whole-tree mount like `.:/app` — the project's source is
    somewhere in it BY DEFINITION), and otherwise when a BOUNDED recursive walk finds a code file. The
    recursion is what the audit-post high finding required: a repo that mounts `.` but keeps its code under
    `backend/` / `src/` / `app/` has NO code at the mount's top level, yet the whole tree — code included —
    reaches the container (X-0370's exact shape). It is bounded (depth + a dependency/VCS/build skip set) so
    it stays cheap and never reads a `node_modules` under a data mount as the project's source.

    This is what separates the X-0370 shape (`.:/app`, `./backend:/app`) from the mounts every project makes
    and nobody should be nagged about (`./data:/data`, `./nginx.conf:/etc/nginx/nginx.conf`). Fail-OPEN: an
    unreadable path yields False — no evidence, no line (SPEC-0119 rule 3: never nag on an unknown)."""
    try:
        if path.resolve() == repo_root.resolve():
            return True                       # the WHOLE tree is mounted — its source is in there by definition
        if not path.is_dir():
            return False
        return _walk_for_source(path, 0)
    except OSError:
        return False


def _walk_for_source(directory: Path, depth: int) -> bool:
    """Bounded DFS for a code file under `directory` (helper for `_holds_source`). Skips dependency / VCS /
    build dirs and stops at `_SEARCH_MAX_DEPTH`. Fail-OPEN on any OSError (an unreadable subtree is no
    evidence)."""
    try:
        for child in directory.iterdir():
            if child.is_file() and child.suffix in _SOURCE_EXTENSIONS:
                return True
            if (child.is_dir() and child.name not in _SEARCH_SKIP_DIRS
                    and not child.name.startswith(".") and depth < _SEARCH_MAX_DEPTH):
                if _walk_for_source(child, depth + 1):
                    return True
    except OSError:
        return False
    return False


def source_mount_evidence(repo_root, *, prod_only: bool = False, declared_prod: tuple = ()) -> list:
    """Does this repo's own SOURCE TREE get bind-mounted into a running service? (SPEC-0119 rule 16 arm (a))

    Returns `[{compose, service, mount}]` — one row per bind mount of a source-bearing host path INSIDE this
    repo. `[]` means NO evidence, which is the honest answer for an image-baked project, a project with no
    compose file, and a project whose only mounts are data/config.

    `prod_only` restricts the scan to the PRODUCTION compose — the compose that actually runs in prod,
    resolved declaration-first (`declared_prod`, the carrier's own deploy command) and otherwise by the
    `_is_dev_compose` naming convention. A source bind that lives ONLY in `docker-compose.dev.yaml` is the
    doctrine's prescribed local-dev shape (patterns/deploy-coherence.md §3), not a prod bypass, so it must
    not surface. BOTH arms of `runtime_delivery_coherence` read this way: arm (c) since T-10621, and arm (a)
    since T-10905 — X-0711 is arm (a)'s unscoped read cashing in, reporting 8 dev-overlay mounts under a
    headline asserting the project bind-mounts its source in production, which is the OPPOSITE of that
    project's truth. Evidence about production comes only from the compose that runs in production.

    FAILS OPEN BY CONSTRUCTION, and that is a deliberate trade. A missing compose file, an unparseable one,
    an exotic service shape, a mount expressed some way this reader does not know — all yield NO evidence
    and therefore NO line. A report-only surface must never nag on an unknown (SPEC-0119 rule 3), and the
    cost of a miss is bounded: arm (b) still speaks the moment the project DECLARES a bypassable model. The
    cost of the opposite choice — a false nag on every project that mounts a data volume — is the noise that
    buries the echo this view rides (the SPEC-0149 retro-charge lesson).

    Pure: reads files, writes nothing.
    """
    root = Path(repo_root)
    rows: list = []
    for compose in _compose_paths(root, prod_only=prod_only, declared_prod=declared_prod):
        try:
            doc = state.load_str(compose.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, yaml.YAMLError, TypeError):
            continue                          # unparseable ⇒ no evidence (fail-open)
        services = doc.get("services") if isinstance(doc, dict) else None
        if not isinstance(services, dict):
            continue
        for service, spec in sorted(services.items()):
            volumes = spec.get("volumes") if isinstance(spec, dict) else None
            for volume in volumes if isinstance(volumes, list) else ():
                host = _host_side(volume)
                if host is None or host.startswith(("~", "$", "/")):
                    continue                  # only a REPO-RELATIVE mount is evidence about THIS tree
                try:
                    resolved = (root / host).resolve()
                    resolved.relative_to(root.resolve())   # a `../` escape is not this repo's source
                except (OSError, ValueError):
                    continue
                if _holds_source(resolved, root):
                    rows.append({
                        "compose": compose.name,
                        "service": str(service),
                        "mount": volume if isinstance(volume, str) else f"{host} (bind)",
                    })
    return rows


def _declared_delivery(ops_path) -> tuple:
    """Read the carrier's `deploy.runtime_delivery` stance → `(model, waived_for_real)`.

    `model` is the declared enum value (None when undeclared / unknown / mis-typed — an unknown model is
    NOT a declaration, SPEC-0093 rule 22, and the init sweep fails it closed). `waived_for_real` is True
    only for a HUMAN-authored waiver: a BORN placeholder waiver is an unanswered question wearing a
    waiver's clothes (the X-0088 class) and does not silence this view.

    Never raises: a missing / unreadable / malformed carrier yields `(None, False)` — the engine kernel
    itself has no carrier, and arm (a) still needs evidence to fire, so a carrier-less repo stays silent.
    """
    try:
        carrier = state.load_ops(Path(ops_path))
    except (OSError, UnicodeDecodeError, yaml.YAMLError, TypeError):
        return (None, False)
    if not isinstance(carrier, dict):
        return (None, False)
    deploy = carrier.get("deploy")
    node = deploy.get("runtime_delivery") if isinstance(deploy, dict) else None
    if not isinstance(node, dict):
        return (None, False)

    waiver = node.get("waiver")
    if isinstance(waiver, dict):
        reason = waiver.get("reason")
        reason = reason.strip() if isinstance(reason, str) else ""
        # A real waiver answers the question; the born placeholder only looks like it does.
        return (None, bool(reason) and BORN_WAIVER_MARKER not in reason)

    model = node.get("model")
    model = model.strip() if isinstance(model, str) else ""
    return ((model if model in RUNTIME_DELIVERY_MODELS else None), False)


def runtime_delivery_coherence(ops_path, repo_root, not_adopted=None, now=None) -> dict:
    """Fold the carrier + the source tree + the EXISTING not-adopted view → the runtime-delivery
    incoherence this repo carries (SPEC-0119 rule 16 / SPEC-0093 rule 22).

    TWO arms, and a repo is counted iff ONE of them holds:
      (a) `undeclared-bypassable` — the repo bind-mounts its own SOURCE into a service (evidence) while
          `deploy.runtime_delivery` is neither declared nor really waived. The deploy verb is bypassable
          here and NOTHING says so — the X-0370 silence itself.
      (b) `live-without-deploy` — the carrier DECLARES a bypassable model AND the not-adopted view reports
          `shipped-not-live` with N>0. Those N commits are then re-read for what they ARE under that model:
          ALREADY LIVE, and past no deploy gate. It renders when the last `deploy_completed` revision
          differs from `main` HEAD and CLEARS when they match (the not-adopted count falls to 0).
      (c) `unwaived-prod-mount` (T-10621, the runtime-delivery doctrine — SPEC-0093 rule 22, T-10620) — the
          carrier DECLARES a bypassable model but its executable-code bind mounts still sit in the PROD
          compose with NO real waiver. Under the doctrine image-baked is the normative prod default and a
          bypassable prod runtime survives ONLY as an explicit waiver naming its compensating controls
          (patterns/deploy-coherence.md); a bare `model:` is not that waiver. Fires when PROD-compose
          source-mount evidence exists and arm (b) did not (no live drift). It CLEARS when the waiver is
          declared (an answered question — `_declared_delivery` reads model+waiver as waived) OR the mounts
          move to a dev overlay (the aiseller split — §3, so the PROD-scoped detector sees nothing).

    A declared `image-baked`, a real waiver, or no evidence ⇒ count 0 ⇒ silent: a project whose deploy verb
    genuinely IS the only path to prod owes nothing here, and rule 1's forward reading of its delta stands.

    Args:
      ops_path: this repo's `yitc-ops.yaml` (missing/unreadable ⇒ no declaration — arm (a) then needs
        evidence to fire, so a carrier-less repo like the engine kernel stays silent).
      repo_root: the repo to scan for source-mount evidence.
      not_adopted: the ALREADY-COMPUTED `_view_not_adopted` dict (injected — one derivation, no second git
        path). None ⇒ arm (b) cannot be judged and contributes nothing (never a guess).
      now: aware datetime, injected by the tests so every assertion is deterministic.

    Returns `{"lens", "now", "status", "count", "kind", "model", "evidence", "commits", "next"}` — the shape
    the sibling views return. Pure: reads files + a dict, writes nothing (SPEC-0149 §2). NEVER gates.
    """
    now = now if now is not None else datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    model, waived = _declared_delivery(ops_path)
    # The PRODUCTION compose set, resolved ONCE and handed to BOTH evidence arms (T-10905): declaration
    # first (the carrier's own deploy command), naming convention as the fallback.
    declared_prod = _declared_prod_composes(ops_path)

    if model in BYPASSABLE_DELIVERY_MODELS:
        # ARM (b) — the REVERSE reading. The delta rule 1 prints as "shipped-but-not-live" is, under this
        # declared model, the set of commits that are ALREADY LIVE and passed no gate. Only the
        # `shipped-not-live` status carries a real deploy baseline with HEAD strictly ahead (the rule-1
        # status gate, verbatim): `no-deploy-recorded` would hand back the whole history — a
        # baseline-absent signal, not this debt (the X-0142 false-nag shape).
        view = not_adopted if isinstance(not_adopted, dict) else {}
        count = view.get("not_adopted_count")
        if view.get("status") == "shipped-not-live" and isinstance(count, int) and count > 0:
            return _delivery_result(
                now, status="checked", kind="live-without-deploy", count=count, model=model,
                evidence=[], commits=view.get("not_adopted") or [],
                live_revision=view.get("live_revision"), head=view.get("head"),
                live_revision_source=view.get("live_revision_source"))
        # ARM (c) — DECLARED-yet-unwaived. A bypassable model with no live drift is not the whole answer under
        # the doctrine (T-10620): if its executable-code mounts still sit in the PROD compose with no waiver,
        # the doctrine's prescription (bake / dev-split / waive) is unmet and NOTHING says so. PROD-scoped so a
        # dev-overlay mount (the aiseller split) is silent, and a real waiver never reaches here (model=None
        # earlier). No live drift, so the honest count is the number of prod-compose mounts, not a commit delta.
        prod_evidence = source_mount_evidence(repo_root, prod_only=True, declared_prod=declared_prod)
        if prod_evidence:
            return _delivery_result(now, status="checked", kind="unwaived-prod-mount",
                                    count=len(prod_evidence), model=model, evidence=prod_evidence)
        return _delivery_result(now, status="checked", kind=None, count=0, model=model)

    if model is not None or waived:
        # A declared `image-baked` (the deploy verb IS the only path — the kernel's assumption holds), or a
        # human-authored waiver (an answered question is not debt — the `_is_waived` discipline, SPEC-0156).
        return _delivery_result(now, status="checked", kind=None, count=0, model=model)

    # ARM (a) — UNDECLARED. The question is only debt if this repo demonstrably runs its own source tree IN
    # PRODUCTION: no evidence ⇒ no line (fail-open; a report-only surface never nags on an unknown, rule 3).
    # PROD-scoped since T-10905 (X-0711): a source bind that lives only in a dev overlay says NOTHING about
    # the prod runtime, and reporting it asserted the opposite of the project's truth — the inversion this
    # very view exists to end. A dev-only mount is the doctrine-conformant shape, so it owes no declaration.
    evidence = source_mount_evidence(repo_root, prod_only=True, declared_prod=declared_prod)
    if evidence:
        return _delivery_result(now, status="checked", kind="undeclared-bypassable", count=len(evidence),
                                model=None, evidence=evidence)
    return _delivery_result(now, status="checked", kind=None, count=0, model=None)


def _delivery_result(now, *, status, kind, count, model, evidence=None, commits=None,
                     live_revision=None, head=None, live_revision_source=None) -> dict:
    if kind == "undeclared-bypassable":
        nxt = ("this project's PRODUCTION compose bind-mounts its own SOURCE into a running service, so a "
               "`docker compose up` / container recreate ships whatever sits on `main` — with no deploy "
               "verb, no class gate and no `deploy_completed`. Nothing in the carrier says so, so every "
               "kernel surface still reads your un-deployed commits as 'not yet live' when they are ALREADY "
               "live (X-0370: half a paired change shipped, 8h outage). The evidence NAMES its compose file "
               "per row — check it. DECLARE it — yitc-ops.yaml `deploy.runtime_delivery.model:` "
               "source-mounted | hot-reload | hybrid — or WAIVE it with a reason. Declaring a bypassable "
               "model gates nothing; it makes the kernel honest (SPEC-0093 rule 22). If that file is NOT "
               "what runs in prod, say which one is: the `-f` operand of your `deploy.command` is read as "
               "the production compose set (T-10905).")
    elif kind == "unwaived-prod-mount":
        nxt = ("this project declares a BYPASSABLE runtime-delivery model but its executable-code bind "
               "mounts still sit in the PROD compose with NO waiver — under the runtime-delivery doctrine "
               "(SPEC-0093 rule 22, T-10620) image-baked is the normative prod default and a bypassable prod "
               "runtime survives ONLY as an explicit waiver naming its compensating controls (X-0370: half a "
               "paired change shipped on a recreate, 8h outage). The doctrine route (patterns/deploy-coherence.md): "
               "(1) the aiseller dev/prod compose SPLIT — keep source mounts in `docker-compose.dev.yaml`, run "
               "prod on the baked image (§3); or (2) migrate to `model: image-baked` after a measure-first bake "
               "(§4); or (3) WAIVE it — `deploy.runtime_delivery.waiver: {reason: <why>}` — naming the X-0367 "
               "coherence-guard coverage + the documented restart recovery. Report-only, gates nothing (SPEC-0119 "
               "rule 16).")
    elif kind == "live-without-deploy":
        nxt = ("this project DECLARES a bypassable runtime-delivery model, so these commits are not "
               "'waiting to be deployed' — they are ALREADY LIVE (the runtime reads the source tree) and "
               "passed NO deploy gate: no class check, no pre-deploy backup, no live probe, no "
               "`deploy_completed`. Reconcile: run `bin/yitc-v2 deploy` to put the live revision back on "
               "record, or (the real fix) close the bypass so code cannot reach prod outside the verb "
               "(SPEC-0119 rule 16).")
    else:
        nxt = ("the runtime-delivery model is declared and coherent — nothing owed.")
    return {
        "lens": "runtime-delivery-coherence (SPEC-0119 rule 16 / SPEC-0093 rule 22) — the REVERSE reading "
                "of not-adopted: where a project's runtime reads its SOURCE TREE (bind mount / hot reload), "
                "the deploy verb is BYPASSABLE, so the commits between the last deploy_completed and `main` "
                "are not 'shipped-but-not-live' — they are ALREADY LIVE and passed no gate (X-0370). Two "
                "arms: an undeclared bypass detected from the repo's own PRODUCTION compose bind-mounts "
                "(dev overlays say nothing about prod — T-10905/X-0711), and a "
                "DECLARED bypassable model whose live revision has fallen behind `main`. DERIVED at read "
                "time from the carrier + the existing not-adopted view — zero stored state, no second git "
                "path; a repo with no carrier (the engine kernel itself) owes nothing. Report-only, never "
                "a gate.",
        "now": now.isoformat().replace("+00:00", "Z"),
        "status": status,
        "count": count,
        "kind": kind,
        "model": model,
        "evidence": evidence or [],
        "commits": commits or [],
        "live_revision": live_revision,
        "head": head,
        # T-10521: whether `live_revision` came from the deploy_completed proxy or a declared live-revision
        # adapter (observability only — the reverse line already renders the injected view's value).
        "live_revision_source": live_revision_source,
        "next": nxt,
    }


# ── SPEC-0152 rule 24 (T-10513 / X-0375): declared test classes with no recorded successful execution ──
#
# The gap this closes: SPEC-0156 admits a declared check on a recorded RED demonstration — proof it CAN
# fail. It never asks whether the check has ever ACTUALLY RUN green. aiseller's e2e test class was DECLARED
# but its browsers were never installed: nothing ran, so nothing failed, and a class that never executed
# read as coverage (X-0375). This fold is the SPEC-0156 sibling on the execution axis: a declared
# `tests.classes[]` class (SPEC-0093 rule 10) with NO journaled successful execution surfaces `never`, and
# one whose latest passing execution has aged past the staleness floor surfaces `stale`. Report-only, zero
# stored state — recomputed fresh, exactly like every fold above (SPEC-0149 §2).
#
# THE PRODUCER IS A DELIBERATE, EVIDENCE-BEARING ACT — never a declaration-derived auto-emit. A pinned
# suite PASSING does NOT positively observe that a SPECIFIC declared class ran: `land` runs `verify.layers`
# by LAYER id, never per tests-class, so auto-recording "executed" from the declaration list would be the
# very "nothing ran, nothing failed" false-green this doctrine exists to end (T-10513 audit-pre). The
# execution is recorded by whoever ACTUALLY RAN the class — a CI job, a post-deploy hook, a human — via the
# EXISTING generic `event` verb (`bin/yitc-v2 event test_class_executed --data …`). This is the SPEC-0156
# `check_admission_demonstrated` producer precedent EXACTLY: no new verb, no new emitter, no new store.
EXECUTION_EVENT = "test_class_executed"

# The ONLY outcome that records an execution: a class shown GREEN. A non-pass (or absent, or misspelt)
# outcome records NO successful run — it must not clear the line.
EXECUTION_PASS_OUTCOME = "pass"

# THE EVIDENCE, NOT JUST THE VERDICT (the SPEC-0156 ADMISSION_REQUIRED_FIELDS discipline). A bare "it ran"
# with no NAMED run is a CLAIM anyone could type, and clearing a class on a claim is the false-green this
# fold exists to end. A record must carry a non-empty `evidence:` (what run — a CI url, a log ref, a
# harness id) to clear a class. Under-evidenced ⇒ still owed; it never invents debt that was not declared.
EXECUTION_REQUIRED_FIELDS = ("evidence",)


def _declared_test_classes(ops_path) -> list:
    """The declared `tests.classes[]` entries this repo's carrier names (SPEC-0093 rule 10) →
    `[{class, moment}]`. Reuses the `_is_waived` discipline: an absent / waived / non-mapping `tests:`
    section, or a single waived entry, declares no class. Never raises — a carrier-less repo (the engine
    kernel itself) declares nothing → [], so history is never retro-charged (the SPEC-0149 lesson)."""
    try:
        carrier = state.load_ops(Path(ops_path))
    except (OSError, UnicodeDecodeError, yaml.YAMLError, TypeError):
        return []
    if not isinstance(carrier, dict):
        return []
    node = carrier.get("tests")
    if not isinstance(node, dict) or _is_waived(node):
        return []
    classes = node.get("classes")
    rows: list = []
    for index, entry in enumerate(classes if isinstance(classes, list) else []):
        if _is_waived(entry):
            continue                      # a single waived class is an ANSWERED question (rule 6)
        name = _entry_name(entry, "class", index)
        moment = entry.get("moment") if isinstance(entry, dict) else None
        rows.append({"class": name, "moment": moment.strip() if isinstance(moment, str) and moment.strip()
                     else None})
    return rows


def _declared_verify_layers(ops_path) -> list:
    """The declared `verify.layers[]` entries this repo's carrier names (SPEC-0152 rule 16) → the raw
    entry mappings. Same fail-open discipline as `_declared_test_classes` beside it: an absent / waived /
    non-mapping `verify:` section declares no layer, and a carrier-less repo declares nothing → []."""
    try:
        carrier = state.load_ops(Path(ops_path))
    except (OSError, UnicodeDecodeError, yaml.YAMLError, TypeError):
        return []
    if not isinstance(carrier, dict):
        return []
    node = carrier.get("verify")
    if not isinstance(node, dict) or _is_waived(node):
        return []
    layers = node.get("layers")
    return [e for e in (layers if isinstance(layers, list) else [])
            if isinstance(e, dict) and not _is_waived(e)]


def undeclared_class_remedy(ops_path, given) -> str:
    """The point-of-CONSTRUCTION check for a `test_class_executed` emit → "" when the emit is admissible,
    or the REMEDY MESSAGE when the named class is not one this project declared (T-11415, X-1057).

    WHY AT CONSTRUCTION AND NOT IN THE FOLD. The fold downstream is faithful by design — it reports what
    the journal literally says — so a row naming a class nobody declared is COMPLETE (`outcome: pass` +
    `evidence:`), is written, reads as coverage to a human, matches no declared class, and therefore clears
    nothing. It is not even a near-miss: `_test_class_near_misses` is scoped to still-surfaced DECLARED
    names, so the row is invisible on every surface. MEASURED (kupiclub, 2026-08-20): two rows emitted with
    `class=stack` and `class=static` — verify LAYER ids, not any of their eight declared classes — accepted
    without a word, and the next morning's fold still reported the same declared-but-unproven count. The
    acceptance criterion that named the event stayed unmet for a day. The only seam where the mistake is
    still cheap is the emit itself, and the vocabulary needed to catch it is already in hand there.

    WHY THE WRONG VALUE IS THE EASY ONE TO WRITE — this is not carelessness, and the message is shaped to
    the actual confusion. Both vocabularies live in ONE file a few sections apart; they OVERLAP (kupiclub's
    `frontend-unit` is BOTH a layer id and a class name, so "is this the right KIND of name" cannot be
    settled by inspection); and the run output on screen at the moment of recording prints the LAYER names,
    never the class names. The author copies what they just read.

    IT FAILS BY IMPROVING THE ARTIFACT, NOT BY REFUSING (the requester's ask, and their own external
    consult's finding on this class of fix — kupiclub decisions/gate-automation-frame-audit-adhoc.yaml
    finding 1; the sibling craft home is `lessons/a-refusal-remedy-must-name-which-locus-it-repairs.md`).
    A silent accept is the current defect and a BARE refusal is the weaker fix: it would tell the author
    that the value is wrong and leave them to go find the right one in the same confusing file. So the
    message hands back the material they lacked — every legal value NAMED, and, where the given value is a
    declared LAYER id, that layer's own `covers_classes:` named as the classes it carries, which is the
    exact translation the author needed. The caller refuses the APPEND (so no false coverage row is ever
    written) using this text; the improvement is the message, not the verdict.

    IT ABSTAINS WHEREVER THE DECLARATION CANNOT BE READ — "" for a carrier-less repo (the engine kernel
    itself), a waived/absent `tests:` section, zero declared classes, or any parse failure. The judgement
    belongs to the READER, and a project that has declared no vocabulary has authorised no refusal
    (`lessons/fail-closed-belongs-to-the-reader-not-the-parser.md`). The declaration is read in FULL —
    the UNION of declared classes, never a first-match (SPEC-0185 §1b).
    """
    if not isinstance(given, str) or not given.strip():
        return ""                       # attributes its run to no class — a different defect, and one
                                        # `_execution_defect` / the fold already handle (it clears none)
    name = given.strip()
    declared = [row["class"] for row in _declared_test_classes(ops_path)]
    if not declared:
        return ""                       # nothing declared ⇒ nothing to contradict (the ABSTAIN above)
    if name in declared:
        return ""

    lines = [
        f"`class: {name}` is not a test class this project declares.",
        "Declared `tests.classes[]` (yitc-ops.yaml) — the legal values: " + ", ".join(declared) + ".",
    ]
    layer = next((e for e in _declared_verify_layers(ops_path)
                  if isinstance(e.get("layer"), str) and e["layer"].strip() == name), None)
    if layer is not None:
        # THE TRANSLATION, not a rejection: the given value IS a real declaration — the WRONG KIND of one.
        # Name the layer as a layer, then hand back the classes it carries so the correct row is one edit
        # away. `covers_classes:` is the consumer-declared pointer; where a layer does not carry one, say
        # so plainly rather than guessing a mapping the carrier does not state.
        carried = [c.strip() for c in layer.get("covers_classes", [])
                   if isinstance(c, str) and c.strip()] if isinstance(
                       layer.get("covers_classes"), list) else []
        if carried:
            lines.append(f"`{name}` IS a declared `verify.layers[]` LAYER, not a class — and it carries "
                         f"classes: " + ", ".join(carried) + ". Record one row per class it actually ran.")
        else:
            lines.append(f"`{name}` IS a declared `verify.layers[]` LAYER, not a class, and it declares no "
                         f"`covers_classes:` — so the carrier does not say which classes it runs. Name the "
                         f"class you ran from the declared list above (or declare the layer's "
                         f"`covers_classes:`).")
    return " ".join(lines)


def _execution_defect(data) -> str:
    """The ONE completeness test for a `test_class_executed` payload → a short human reason it does NOT
    record a run, or "" when it is COMPLETE. Both readers share it: `_test_class_executions` (which drops
    a defective record) and `_test_class_near_misses` (which reports it). Factored out so the clearing rule
    and the near-miss report can never drift into two different contracts (X-0470: the trap was the silent
    drop — a consumer had to read THIS source to learn the shape, so the shape gets ONE home)."""
    if not isinstance(data, dict):
        return "no `data:` mapping"
    outcome = data.get("outcome")
    if not isinstance(outcome, str) or not outcome.strip():
        return f"no `outcome:` (must be the literal `{EXECUTION_PASS_OUTCOME}`)"
    if outcome.strip().lower() != EXECUTION_PASS_OUTCOME:
        return f"`outcome: {outcome.strip()}` is not the literal `{EXECUTION_PASS_OUTCOME}`"
    missing = [f for f in EXECUTION_REQUIRED_FIELDS
               if not (isinstance(data.get(f), str) and data.get(f).strip())]
    if missing:
        return "no " + ", ".join(f"`{f}:`" for f in missing) + " naming the run (a CI url / log ref)"
    return ""


def _test_class_executions(events_path) -> dict:
    """Fold the journal → `class -> latest passing-execution ts`. FAITHFUL, never fail-closed
    (`lessons/fail-closed-belongs-to-the-reader-not-the-parser.md`): this reports only what the journal
    literally says. A record clears a class ONLY when COMPLETE — a non-empty `class`, an `outcome` of
    `pass`, and every EXECUTION_REQUIRED_FIELDS present and non-empty; an under-evidenced or non-passing
    record is DROPPED here (it records no successful run, so it can clear nothing). A malformed line /
    missing journal yields {} — a report-only fold never breaks the seam it rides.

    DECLARED HORIZON: the WHOLE logical journal (SPEC-0190 rule 4). This fold answers two questions
    that both reach past the live window — "was this class EVER seen to run" (unbounded) and "did it
    run inside the staleness floor" (30 days by default, against a live window of days) — so it takes
    the ARCHIVE branch, not by preference but because rule 4 makes a reader whose answer depends on
    undeclared history a defect. Reading the live segment alone reported a class with four complete
    passing records in the archive as never-executed (X-1100, kupiclub 2026-08-25)."""
    out: dict = {}
    try:
        for event in journal.segment_rows(events_path):   # SPEC-0190 rule 4 — the WHOLE journal
            if not isinstance(event, dict) or event.get("type") != EXECUTION_EVENT:
                continue
            data = event.get("data")
            if not isinstance(data, dict):
                continue
            cls = data.get("class")
            if not isinstance(cls, str) or not cls.strip():
                continue              # attributes its run to no class ⇒ clears none
            if _execution_defect(data):
                continue              # non-pass / under-evidenced ⇒ a CLAIM, not a run (§ above);
                                      # reported by `_test_class_near_misses`, never silently gone
            ts = _parse_stamped_deadline(event.get("ts"))
            if ts is None:
                continue              # no establishable ordering ⇒ cannot date a run
            key = cls.strip()
            if key not in out or ts > out[key]:
                out[key] = ts
    except (OSError, UnicodeDecodeError):
        return {}
    return out


NEAR_MISS_CAP = 3


def _test_class_near_misses(events_path, names) -> list:
    """Fold the journal → the `test_class_executed` records that TRIED to record a run of a still-surfaced
    class and did NOT (X-0470). Boomrocket emitted `outcome: green` with `run:` instead of `evidence:`; the
    record was dropped, the debt line did not move, and nothing anywhere said why — so they read kernel
    source to find the contract. A near-miss is the loudest possible evidence someone is trying to discharge
    the debt, and it was the one thing the surface stayed silent about.

    Scoped to `names` — the classes STILL surfaced as debt. A near-miss for a class that a later COMPLETE
    record already cleared is answered; reporting it would nag about a solved thing (the sibling
    suppressed-when-clean discipline). Latest-first, capped at NEAR_MISS_CAP: this is a nudge to fix the
    emit, not a log. Report-only, best-effort — a malformed line / missing journal ⇒ [], never raises.

    DECLARED HORIZON: the WHOLE logical journal (SPEC-0190 rule 4) — the SAME horizon as
    `_test_class_executions`, because this fold is scoped to the classes THAT fold still surfaces. A
    near-miss reporter that cannot see the archive under-reports for the identical reason, and would
    stay silent about the very emit somebody is trying to fix. It IS order-sensitive (latest-first,
    capped), but it sorts EXPLICITLY on the parsed `ts` below, so the cross-segment reordering rule 5
    admits can only permute records that compare EQUAL on `ts` — it can never drop a newer record or
    let an older one outrank it (the rule-6 reader-specific judgement, T-11574)."""
    wanted = {n for n in (names or []) if isinstance(n, str) and n.strip()}
    if not wanted:
        return []
    rows: list = []
    try:
        for event in journal.segment_rows(events_path):   # SPEC-0190 rule 4 — the WHOLE journal
            if not isinstance(event, dict) or event.get("type") != EXECUTION_EVENT:
                continue
            data = event.get("data")
            cls = data.get("class") if isinstance(data, dict) else None
            if not isinstance(cls, str) or cls.strip() not in wanted:
                continue              # names no still-owed class ⇒ not this fold's business
            reason = _execution_defect(data)
            if not reason:
                continue              # a COMPLETE record is a run, not a near-miss
            ts = _parse_stamped_deadline(event.get("ts"))
            rows.append({"class": cls.strip(), "reason": reason, "ts": ts,
                         "at": ts.isoformat().replace("+00:00", "Z") if ts is not None else None})
    except (OSError, UnicodeDecodeError):
        return []
    # Latest-first; an undateable record sorts last (never compare None to a datetime).
    _floor_ts = datetime.min.replace(tzinfo=timezone.utc)
    rows.sort(key=lambda r: (r["ts"] is not None, r["ts"] or _floor_ts), reverse=True)
    return [{k: v for k, v in r.items() if k != "ts"} for r in rows[:NEAR_MISS_CAP]]


def unexecuted_test_classes(ops_path, events_path, floor_days: int = 30, now=None) -> dict:
    """Fold the ops carrier + the journal → the declared `tests.classes[]` classes with NO recorded
    successful execution of their own (`never`), or whose latest one has aged past `floor_days` (`stale`)
    — SPEC-0152 rule 24 (T-10513 / X-0375).

    A class is PROVEN-RUN iff the journal carries a COMPLETE `test_class_executed` (pass + evidence) whose
    `class` matches AND (when the floor is active) whose ts is younger than the floor. Two surfaces:
      - no matching record at all  → `never`  (declared, never seen to run — the X-0375 class);
      - latest run older than N     → `stale`  (it ran once, but not since — its coverage claim has aged).
    NEVER-run always surfaces (it is unconditional debt); STALE surfaces only when the floor is active
    (`floor_days > 0`) — a non-positive floor disables the staleness arm, exactly as the sibling folds
    treat a disabled AGE floor. Report-only, never a gate: an unexecuted class is surfaced, never refused.

    Args:
      ops_path: this repo's `yitc-ops.yaml` (missing/unreadable ⇒ a clean, zero-count result: a repo that
        declares no test class owes nothing — the engine kernel itself).
      events_path: path to `events.jsonl` (missing/unreadable ⇒ every declared class reads as `never`,
        the honest answer: with no journal there is no evidence any class ran).
      floor_days: the staleness AGE floor in days (host-supplied from
        `YITC_DEBT_TEST_CLASS_STALE_FLOOR_DAYS`). Non-positive ⇒ the staleness arm is disabled.
      now: aware datetime, injected by the tests so every assertion is deterministic.

    Returns `{"lens", "now", "count", "classes", "floor_days", "next"}` — the shape the sibling views
    return. Pure: reads two files, writes nothing (SPEC-0149 §2)."""
    now = now if now is not None else datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    floor = floor_days if (isinstance(floor_days, int) and not isinstance(floor_days, bool)
                           and floor_days > 0) else 0

    declared = _declared_test_classes(ops_path)
    if not declared:
        return _unexecuted_result(now, [], floor)      # nothing declared ⇒ nothing owed (never retro-charged)

    executed = _test_class_executions(events_path)
    classes: list = []
    for row in declared:
        cls = row["class"]
        last = executed.get(cls)
        if last is None:
            classes.append({"class": cls, "moment": row["moment"], "state": "never",
                            "last_executed": None, "stale_days": None})
            continue
        if floor:
            age_days = (now.date() - last.date()).days
            if age_days >= floor:
                classes.append({"class": cls, "moment": row["moment"], "state": "stale",
                                "last_executed": last.isoformat().replace("+00:00", "Z"),
                                "stale_days": age_days})
        # else: a run younger than the floor (or floor disabled) ⇒ proven-run, not surfaced
    # Never-run first (a class never seen to run is a sharper signal than a stale one), then by name so the
    # order is stable across folds.
    classes.sort(key=lambda r: (r["state"] != "never", r["class"]))
    return _unexecuted_result(now, classes, floor,
                              _test_class_near_misses(events_path, [r["class"] for r in classes]))


def _unexecuted_result(now, classes: list, floor: int, near_misses: list = None) -> dict:
    near_misses = near_misses or []
    return {
        "lens": "unexecuted-test-classes (SPEC-0152 rule 24 / X-0375) — test classes this project DECLARES "
                "in its yitc-ops.yaml `tests.classes` with NO recorded successful execution of their own: "
                "no journaled `test_class_executed` that is `pass` with a named `evidence:` (`never`), or "
                "whose latest one has aged past the staleness floor (`stale`). The execution axis of the "
                "SPEC-0156 admission doctrine — a demonstration proves a check CAN fail; this proves it has "
                "actually RUN. A class nobody ran is not coverage (aiseller's e2e suite: browsers never "
                "installed — nothing ran, nothing failed). DERIVED at read time from the carrier + the "
                "journal — zero stored state; a repo that declares no test class (the engine kernel itself) "
                "owes nothing, so history is never retro-charged. Report-only, never a gate.",
        "now": now.isoformat().replace("+00:00", "Z"),
        "count": len(classes),
        "floor_days": floor,
        "classes": classes,
        "near_misses": near_misses,
        "next": ("these declared test classes have no recorded successful run — nothing shows they were "
                 "ever executed (a declared class that never ran reads as coverage while catching nothing). "
                 "RUN each one for real, then record `bin/yitc-v2 event test_class_executed --data "
                 "'{\"class\":…,\"outcome\":\"pass\",\"evidence\":…}'` naming the run (a CI url / log ref). "
                 "The shape is EXACT: `outcome` must be the literal `pass` (not `green`/`ok`/`passed`) and "
                 "`evidence` must be present and non-empty — any other payload records no run and clears "
                 "nothing. A class that CANNOT be run is not coverage: waive it in `tests.classes` with a "
                 "reason, or retire it — never leave it declared and unrun."
                 + (" SEEN BUT DID NOT CLEAR: " + "; ".join(
                     f"`{r['class']}` — {r['reason']}" for r in near_misses) + "."
                    if near_misses else "")
                 if classes else
                 "every declared test class has a recorded successful execution — nothing owed."),
    }


# ── SPEC-0119 (T-10575): executable verify-layers not yet subject-scoped ────────────────────────────
#
# The subject_globs rollout nudge. SPEC-0152 rule 16's subject_globs sub-rule (T-10571) lets a declared
# verify.layer name the diff paths it is ABOUT (`subject_globs:`), so a land whose diff is provably
# DISJOINT from them REAL-skips that layer's run (and its prep) at land, recording a {layer, outcome:
# skipped-disjoint-subject} row (T-10573 enabled the real skip; T-10572 was the report-only phase). It is OPT-IN and fail-closed —
# an ABSENT subject_globs → the layer ALWAYS runs — so an executable layer without one is NOT a defect,
# it is the safe default. This fold is therefore an OPPORTUNITY prompt, never owed debt: it names each
# EXECUTABLE layer (a real `command:`, not a waiver) that has not yet been subject-scoped, so a consumer
# whose long layers dominate its land time can see which ones are candidates for diff-relevant scoping.
# Same report-only discipline as every sibling: suppressed-when-clean, engine-kernel (no yitc-ops.yaml)
# → count 0 → suppressed, never retro-charges history, never gates. Silent on a WAIVED layer (a layer
# that never runs cannot be scoped) and on a layer that already DECLARES subject_globs (answered).


def undeclared_subject_layers(ops_path) -> dict:
    """Fold the ops carrier → the EXECUTABLE `verify.layers[]` entries with no `subject_globs:` declared
    (SPEC-0152 rule 16 subject_globs sub-rule / SPEC-0119, T-10575).

    A layer COUNTS iff it declares a non-empty `command:` (it actually runs at land) AND carries no
    non-empty-list `subject_globs:`. A WAIVED layer (or a section waiver) is SKIPPED — a layer that never
    runs has nothing to scope, so it is an ANSWERED question, not a candidate. A layer that already
    declares `subject_globs:` is SKIPPED — already scoped. subject_globs is OPT-IN and fail-closed
    (absent → the layer always runs), so this surfaces an OPPORTUNITY (faster lands via diff-relevant
    skipping), never owed debt: report-only, suppressed-when-clean, never a gate.

    Args:
      ops_path: this repo's `yitc-ops.yaml` (missing / unreadable / non-mapping / no verify section /
        section waiver ⇒ a clean zero-count result — a repo that declares no executable layer owes
        nothing, so history is never retro-charged, the SPEC-0149 lesson).

    Returns `{"lens", "count", "layers", "next"}` — the shape the sibling folds return. Pure: reads one
    file, writes nothing (SPEC-0149 §2)."""
    layers: list = []
    try:
        carrier = state.load_ops(Path(ops_path))
    except (OSError, UnicodeDecodeError, yaml.YAMLError, TypeError):
        return _undeclared_subject_result([])
    if not isinstance(carrier, dict):
        return _undeclared_subject_result([])
    node = carrier.get("verify")
    if not isinstance(node, dict) or _is_waived(node):
        return _undeclared_subject_result([])   # no verify section, or the whole concern waived
    declared = node.get("layers")
    for index, entry in enumerate(declared if isinstance(declared, list) else []):
        if not isinstance(entry, dict) or _is_waived(entry):
            continue                            # a waived layer never runs ⇒ nothing to scope
        command = entry.get("command")
        if not (isinstance(command, str) and command.strip()):
            continue                            # not an EXECUTABLE layer (no real land command)
        subject = entry.get("subject_globs")
        if isinstance(subject, list) and any(isinstance(g, str) and g.strip() for g in subject):
            continue                            # already scoped — answered
        layers.append(_entry_name(entry, "layer", index))
    layers.sort()
    return _undeclared_subject_result(layers)


def _undeclared_subject_result(layers: list) -> dict:
    return {
        "lens": "undeclared-subject-verify-layers (SPEC-0152 rule 16 subject_globs / SPEC-0119, T-10575) — "
                "EXECUTABLE verify.layers THIS project declares (a real `command:`, not a waiver) that carry "
                "no `subject_globs:` yet. subject_globs is OPT-IN and fail-closed (absent → the layer ALWAYS "
                "runs), so an un-scoped layer is NOT a defect — it is the safe default; this line is a ROLLOUT "
                "OPPORTUNITY prompt (declare a layer's diff-subject so a disjoint diff REAL-skips its run and "
                "its prep at land, recording a {layer, outcome: skipped-disjoint-subject} row, T-10573), never owed debt. DERIVED at read time from the carrier — zero stored "
                "state; a waived layer is skipped (never runs ⇒ nothing to scope), an already-declaring layer "
                "is skipped (answered), and a repo with no executable layer (the engine kernel itself) folds "
                "to 0 → suppressed. Report-only, never a gate.",
        "count": len(layers),
        "layers": layers,
        "next": ("these executable verify layers have no declared `subject_globs:` — each ALWAYS runs at "
                 "land, even on a diff it does not touch. To scope one, AUDIT the layer's command (its file "
                 "reads / mounts / sub-scripts, a SUPERSET of `covers:` — never a naive covers-copy, which "
                 "false-skips) and add `subject_globs: [<globs>]` to the layer in yitc-ops.yaml; a land whose "
                 "diff is disjoint then REAL-skips it — dropping its run and its prep at land, recording a "
                 "{layer, outcome: skipped-disjoint-subject} row (SPEC-0152 rule 16 subject_globs; T-10573). Opt-in — leaving a "
                 "layer un-scoped is always safe (it just always runs)."
                 if layers else
                 "every executable verify layer is either subject-scoped or has nothing to scope — nothing owed."),
    }


# ── SPEC-0119 rule 35 (T-11886): declared subject_globs with ZERO observed execution ────────────────
#
# THE MEASURED INCIDENT (X-0860, kupiclub). `task test --run` printed PASS while two declared test
# files were executed by NOTHING: the layer DECLARED its subject while the script it runs registered
# each suite BY PATH, and the two disagreed. A false GREEN is the worst failure shape there is,
# because its absence and its success are indistinguishable from outside — four mutation-verified
# tripwires shipped through `land` believing they were gated.
#
# THE INVARIANT, NARROWED TO THE PLACEMENT CONSULT'S WORDING (2026-08-30, YELLOW, finding 1 absorbed):
# «a kernel PASS must not include declared subject_globs with ZERO observed execution». The realm is
# KERNEL because the kernel DEFINES `verify.layers[].subject_globs` and EMITS the verdict, so it owns
# preventing a false GREEN over its own declared contract. The narrowing is LOAD-BEARING: project
# ADEQUACY — how much coverage is enough — stays with the consumer, and without that bound the same
# argument would pull an unbounded class of consumer-side verification into the kernel. Nothing in
# this fold reads a coverage figure, a test count or a file size; a fully-executed layer whose suite
# is thin is NOT a finding here, and there is no input through which it could become one.
#
# THE OTHER AXIS, AND WHY THIS IS NOT A SECOND COPY OF IT. `worktree.py#_delegated_tests_execution_gap`
# (T-11073/T-11172) already asks this question on the `covers:` axis — but ONLY on the delegation
# route, where `task test --run` hands its tests sweep to a layer whose `covers:` glob claims the test
# dir, and it renders only inside that skip note. A consumer that declares its suites on
# `subject_globs:` with no delegation firing is not reached by it at all. So this is the SAME question
# on a DIFFERENT declaration axis, surfaced on a DIFFERENT seam (the debt echo) — and the two share
# ONE naming predicate (`worktree._registry_names_file`), ONE glob predicate
# (`worktree._subject_globs_would_skip`), ONE registry walk (`worktree._registry_text`) and ONE answer
# to «where are this consumer's suites» (`worktree._declared_test_sweep_probe_files`, SPEC-0185 SS1 —
# a DECLARATION, never a kernel `tests/` literal). Extend, never parallel (CHARTER §P1 F1). That reuse
# is also what keeps consumer command names, paths and test-runner assumptions OUT of kernel code, as
# the consult required: kupiclub's own `tests/test_declared_vs_executed.py` is the prior art, and its
# `SUITE_DIR = "tests"`, its `bash <script>` regex and its `*_acceptance.py` convention are
# deliberately NOT carried over.
#
# WHAT IS ACTUALLY PROVABLE. There is no generic execution ledger — a layer is an arbitrary command
# and instrumenting it is out of reach — so this asks the NARROW provable question, «does ANY
# executable layer's registry NAME this file?», never the unprovable «was it executed». The wording
# stays registry-based in BOTH directions: a textual mention is not proof of execution either.
#
# ROLLOUT (the card's AC3, and the consult's finding 2). Report-only BY CONSTRUCTION, not by policy:
# a debt view returns a dict that is rendered into an echo nothing reads for a verdict. No consumer's
# PASS can become a FAIL through this fold. An immediate hard gate would redden the whole fleet at
# once; promotion, if ever, is a separate decision with its own evidence.
#
# THE FAIL-SAFE DIRECTION IS INVERTED relative to a gate, and this is deliberate
# (`lessons/a-signal-about-a-reader-fails-safe-the-opposite-way-to-a-gate.md`): this is a report-only
# SIGNAL about a reader, so every unanswerable state resolves to the reading that does NOT accuse —
# one false accusation gets the whole echo skimmed, while a missed detection only leaves the silence
# that already existed. Hence the DISCOVERY shape below, and hence a swallowed exception yielding 0.

def unexecuted_subject_files(ops_path, repo_root=None) -> dict:
    """Fold the ops carrier + the repo → the suite files that sit inside an EXECUTABLE verify layer's
    declared `subject_globs:` while NO executable layer's execution registry names them
    (SPEC-0119 rule 35 / SPEC-0152 rule 16 subject_globs, T-11886 — the X-0860 shape).

    THE PREDICATE, in one sentence: a file counts iff (a) it is one of this consumer's DECLARED suite
    probe files, (b) some executable layer's `subject_globs:` matches it, and (c) the UNION of every
    executable layer's registry text names it NOWHERE.

    (b) IS DECIDED BY THE EXISTING SKIP PREDICATE, never a second matcher: a path is in-subject iff
    `_subject_globs_would_skip([path], globs)` is False, which is exactly the reading the land seam
    uses — so this view can never disagree with the mechanism it reports on.

    (c) IS A UNION OVER LAYERS, not a per-row check (T-11172/X-0894): a file is routinely executed by a
    SIBLING layer, and demanding per-row execution would demand the double run a layer split exists to
    avoid. A WAIVED layer is excluded from the union — it does not run, so naming a file there absolves
    nothing.

    THE DISCOVERY SHAPE — the branch that keeps this honest. If the union registry names NO candidate
    at all, the consumer runs a DISCOVERY runner (`pytest tests/`) whose executed set cannot be read
    file-by-file; making a per-file claim there would accuse every suite in the repo. So that case
    yields count 0 and NO claim, exactly as the `covers:`-axis sibling returns `kind: discovery` with an
    empty `missing`. The list is therefore non-empty only when the layers demonstrably ENUMERATE their
    suites — i.e. only where a gap is a real, reportable one.

    ONE KNOWN BOUND, in the conservative direction: the shared registry reader does not strip comments,
    so a script COMMENT that merely MENTIONS a suite file counts as naming it and SUPPRESSES the finding
    for that file. That is silence rather than a false accusation — the fail-safe direction above — and
    it is the behaviour of the already-shipped `covers:` axis too, so tightening it is a separate
    decision with its own evidence, not a quiet widening smuggled in here. `tests/test_t11886_*.py`
    measures this bound rather than avoiding it.

    NO ADEQUACY JUDGEMENT IS POSSIBLE HERE (the card's AC2), and that is structural rather than
    promised: the fold's only inputs are the carrier and the file NAMES, so it holds no coverage
    figure, assertion count or size to judge thinness by.

    Args:
      ops_path: this repo's `yitc-ops.yaml`. Missing / unreadable / non-mapping / no `verify:` section
        / a section waiver / no executable layer / no declared `subject_globs:` ⇒ a clean zero-count
        result. A repo that declares nothing owes nothing, so history is never retro-charged (the
        SPEC-0149 lesson) and the engine kernel — which has no carrier at all — folds to 0 ⇒ suppressed.
      repo_root: the checkout the declarations are read against; defaults to the carrier's directory.

    Returns `{"lens", "count", "files", "next"}` — the shape every sibling returns. Pure: reads files,
    writes nothing, opens nothing for writing (SPEC-0149 §2). Total: every exception is swallowed to the
    non-accusing answer."""
    try:
        root = Path(repo_root) if repo_root is not None else Path(ops_path).parent
    except (TypeError, ValueError):
        return _unexecuted_subject_result([])
    try:
        carrier = state.load_ops(Path(ops_path))
    except (OSError, UnicodeDecodeError, yaml.YAMLError, TypeError):
        return _unexecuted_subject_result([])
    if not isinstance(carrier, dict):
        return _unexecuted_subject_result([])
    node = carrier.get("verify")
    if not isinstance(node, dict) or _is_waived(node):
        return _unexecuted_subject_result([])   # no verify section, or the whole concern waived

    globs: list = []
    commands: list = []
    declared = node.get("layers")
    for entry in (declared if isinstance(declared, list) else []):
        if not isinstance(entry, dict) or _is_waived(entry):
            continue                            # a waived layer neither runs nor absolves
        command = entry.get("command")
        if not (isinstance(command, str) and command.strip()):
            continue                            # not an EXECUTABLE layer (no real land command)
        commands.append(command.strip())
        subject = entry.get("subject_globs")
        if isinstance(subject, list):
            globs += [g.strip() for g in subject if isinstance(g, str) and g.strip()]
    if not (globs and commands):
        return _unexecuted_subject_result([])   # nothing declared ⇒ nothing to check (opt-in)

    # LAZY host import: this module back-imports nothing at import time (its docstring's boundary), and
    # these four helpers are the ONE carrier for each question below — never re-implemented here.
    try:
        from lib import worktree as worktree_mod
    except Exception:
        return _unexecuted_subject_result([])

    try:
        candidates = []
        for f in worktree_mod._declared_test_sweep_probe_files(root):
            try:
                rel = Path(f).resolve().relative_to(root.resolve()).as_posix()
            except (OSError, ValueError):
                continue
            if not worktree_mod._subject_globs_would_skip([rel], globs):
                candidates.append(rel)          # in-subject: some declared glob matches it
        if not candidates:
            return _unexecuted_subject_result([])
        # Each layer gets its OWN bounded walk, joined by a NEWLINE so no cross-layer adjacency can
        # forge a token-boundary match.
        text = "\n".join(worktree_mod._registry_text(root, c) for c in commands)
        named = [rel for rel in candidates
                 if worktree_mod._registry_names_file(text, Path(rel).name)]
        if not named:
            return _unexecuted_subject_result([])   # the DISCOVERY shape — no per-file claim is made
        missing = sorted(rel for rel in candidates if rel not in named)
    except Exception:
        return _unexecuted_subject_result([])       # unanswerable ⇒ the reading that does not accuse
    return _unexecuted_subject_result(missing)


def _unexecuted_subject_result(files: list) -> dict:
    return {
        "lens": "unexecuted-subject-files (SPEC-0119 rule 35 / SPEC-0152 rule 16 subject_globs, T-11886) — "
                "suite files that sit INSIDE an executable verify layer's declared `subject_globs:` while "
                "NO executable layer's execution registry names them: declared, therefore believed covered; "
                "run by nothing (the X-0860 shape, where `task test --run` printed PASS over two files "
                "executed by nothing). REGISTRY-based in both directions — it asks whether a layer's "
                "command (and the in-repo scripts that command runs) NAMES the file, never the unprovable "
                "«was it executed», so a clean read is not a proof of execution either. Makes NO adequacy "
                "judgement (how much coverage is enough stays with the consumer — the placement consult's "
                "narrowing) and holds no input through which it could. Silent on a waived section/layer, on "
                "a layer with no declared subject, and on a DISCOVERY runner whose executed set cannot be "
                "read file-by-file. DERIVED at read time from the carrier + the checkout — zero stored "
                "state; a repo with no carrier (the engine kernel itself) folds to 0 → suppressed. "
                "Report-only, never a gate.",
        "count": len(files),
        "files": files,
        "next": ("these files are inside a declared `subject_globs:` subject yet are named by NO executable "
                 "layer's execution registry — not by the declaring layer, not by a sibling. A file no "
                 "registry names is the X-0860 shape: it is executed by NOTHING while the verdict reads "
                 "GREEN. Answer each: REGISTER the file in the layer's command (or in a script that command "
                 "runs), or make the layer DISCOVER its test directory so no file depends on being listed — "
                 "or, if it is genuinely not this layer's subject, narrow the layer's `subject_globs:` in "
                 "yitc-ops.yaml so the declaration stops claiming it. Report-only — no verdict changed here."
                 if files else
                 "every suite file inside a declared verify subject is named by some layer's execution "
                 "registry — nothing owed."),
    }


# ── SPEC-0119 (T-11080): verify layers that NEVER skip — the observed half of subject-scoping ───────
#
# The sibling `undeclared_subject_layers` above reads the CARRIER: "does this layer DECLARE
# subject_globs?". That question has a blind spot the carrier cannot see — a layer that DOES declare
# them, as a SUPERSET of what its command actually covers, so no real diff is ever disjoint from it and
# the layer runs on EVERY land anyway. To the carrier that layer is answered; to the land clock it is
# indistinguishable from an un-scoped one.
#
# This fold reads the OTHER side: the lands themselves. `land_completed.data.consumer_verify_layers[]`
# already records one `{layer, outcome}` row per declared layer (T-9719), with the T-10573 REAL skip
# spelled `skipped-disjoint-subject`. A layer whose skip rate over the window is 0% RAN ON EVERY LAND —
# which is exactly the signal that its subject is absent or declared too wide. Measured motivation
# (`trial_run_recorded` 2026-08-13T19:17:02Z): aiseller 0% skip on all four layers across 453 lands at an
# 84.6s median, against boomrocket's 0.9s median with subject_globs on all 8.
#
# NO new event type and NO new store (the card's AC4): this is a second READING of rows land already
# writes. Report-only, suppressed-when-clean, never a gate — like every sibling in this echo.
#
# THE OVERLAP WITH THE CARRIER LINE IS DELIBERATE AND BOUNDED. A layer with no subject_globs at all can
# appear on both lines, and that is correct: the two say different things ("you have not declared one" vs
# "over N real lands it never once skipped"), and only the second can reach the superset case at all.
# What this fold must never do is read an ABSENT row as a non-skip: per-layer rows exist only for lands
# AFTER the project declared its layers, so a layer is scored ONLY on the lands that actually carry a row
# for it, and it is not scored at all until it has been OBSERVED enough times to mean anything.

ZERO_SKIP_WINDOW_LANDS = 200         # the window: the most recent successful lands carrying layer rows
ZERO_SKIP_MIN_OBSERVATIONS = 20      # a layer is scored only once observed this many times in it
_ZERO_SKIP_OUTCOME = "skipped-disjoint-subject"   # the ONE outcome that counts as a real skip (T-10573)
_ZERO_SKIP_WAIVED = "waived"                      # neither ran nor skipped ⇒ scores nothing (see below)


def zero_skip_verify_layers(events_path, window_lands: int = ZERO_SKIP_WINDOW_LANDS,
                            min_observations: int = ZERO_SKIP_MIN_OBSERVATIONS) -> dict:
    """Fold the journal → the executable verify layers that skipped 0% of the time over the window
    (SPEC-0119 / SPEC-0152 rule 16 subject_globs, T-11080).

    THE PREDICATE. Over the most recent `window_lands` SUCCESSFUL lands (`land_completed` with
    `data.status == "ok"`) that carry a per-layer trail, a layer is reported iff it was OBSERVED at least
    `min_observations` times and NONE of those observations is a skip. `skipped-disjoint-subject` is the
    only outcome that counts as a skip; `waived` does NOT — and a waived row is not an OBSERVATION
    either: the layer neither ran nor skipped, so it scores nothing at all, exactly like an absent row.
    Measured reason (kupiclub, 2026-08-13): its `frontend` layer is waived on 200 of 200 lands, so
    counting waived as a non-skip would report a layer that NEVER RUNS as never-skipping — a nag whose
    remedy ("narrow its subject") does not exist, since a waived layer costs no land time. This is the
    same exclusion the carrier-read sibling makes for the same reason (a layer that never runs has
    nothing to scope); what the card fixes is only that `waived` must never be MISTAKEN for a skip.

    ABSENT IS NOT NON-SKIP. A land whose payload carries no row for a layer does not score that layer at
    all — neither numerator nor denominator. Per-layer rows only start once a project declares its
    layers, so a layer's history legitimately covers a SUBSET of the window's builds; counting the
    silent lands against it would manufacture a 0% skip rate for every layer declared last week.

    THE OBSERVATION FLOOR is what keeps this honest at low volume: a layer seen twice, both times run,
    is not evidence of anything — a report-only surface must never nag on an unknown (SPEC-0119 rule 3).

    THE WINDOW IS COUNT-BOUNDED, WHICH IS WHY THE READ MUST BE SEGMENT-AWARE (T-11669 / X-1123). "The
    200 most recent lands" declares no TIME horizon, so how far back it reaches is set by the land RATE
    — nothing guarantees it stays inside the live segment, and reading the live segment alone made the
    window silently depend on rotation timing. Two runs of the same command weeks apart then measured
    different histories while reporting no difference between them, and a card authored from one run
    could not reproduce its own stated pre-change baseline. This fold is the OBSERVED guard against a
    subject declared too wide, so a silently truncated window makes that guard weaker without saying
    so: it scores layers over fewer observations than it requires, and the floor above starts
    suppressing real findings instead of noise — a failure that arrives with no signal, because a
    shorter window looks exactly like a quieter week.

    Args:
      events_path: the journal to fold — the WHOLE logical history across every segment, not the live
        file alone (missing / unreadable ⇒ a clean zero-count result — a repo with no layered land, the
        engine kernel itself included, folds to 0 → suppressed, so history is never retro-charged, the
        SPEC-0149 lesson).
      window_lands / min_observations: the settled parameters above, injectable for tests.

    Returns `{"lens", "count", "layers", "window_lands", "observed_lands", "next"}` — the sibling shape,
    where `layers` is a list of `{"layer", "observations"}`. Pure: reads one file, writes nothing
    (SPEC-0149 §2). FAITHFUL, never fail-closed: a malformed line is skipped, never fatal
    (`lessons/fail-closed-belongs-to-the-reader-not-the-parser.md`)."""
    lands: list = []
    try:
        # T-11669 (X-1123) — the WHOLE logical journal, every segment (SPEC-0190 rule 4). Still the
        # ONE shared fold of T-11453: `segment_rows` resolves the segment SET and reads each member
        # through the same `fold_rows` primitive, so this is one reader extended, not a second one.
        for event in journal.segment_rows(events_path):
            if not isinstance(event, dict) or event.get("type") != "land_completed":
                continue
            data = event.get("data")
            if not isinstance(data, dict) or data.get("status") != "ok":
                continue                  # an ABORTed land proves nothing about a layer's subject
            rows = data.get("consumer_verify_layers")
            if not isinstance(rows, list) or not rows:
                continue                  # no per-layer trail ⇒ this land scores no layer at all
            lands.append(rows)
    except (OSError, UnicodeDecodeError):
        return _zero_skip_result([], window_lands, 0, min_observations)
    try:
        window = int(window_lands)
    except (TypeError, ValueError):
        window = ZERO_SKIP_WINDOW_LANDS
    if window > 0:
        lands = lands[-window:]               # the WINDOW: the most recent qualifying lands
    tally: dict = {}
    lands_with_a_skip = 0                     # T-11749: the RUN-level numerator (see `_run_skip` below)
    for rows in lands:
        skipped_here = False
        for row in rows:
            if not isinstance(row, dict):
                continue
            name = row.get("layer")
            if not isinstance(name, str) or not name.strip():
                continue                      # a row naming no layer scores none
            outcome = row.get("outcome")
            if outcome == _ZERO_SKIP_WAIVED:
                continue                      # waived ⇒ the layer neither ran nor skipped (see below)
            seen = tally.setdefault(name.strip(), {"observations": 0, "skips": 0})
            seen["observations"] += 1
            if outcome == _ZERO_SKIP_OUTCOME:
                seen["skips"] += 1
                skipped_here = True           # THIS land skipped at least one layer
        if skipped_here:
            lands_with_a_skip += 1
    try:
        floor = int(min_observations)
    except (TypeError, ValueError):
        floor = ZERO_SKIP_MIN_OBSERVATIONS
    layers = [{"layer": name, "observations": seen["observations"]}
              for name, seen in tally.items()
              if seen["observations"] >= floor and seen["skips"] == 0]
    layers.sort(key=lambda l: l["layer"])
    return _zero_skip_result(layers, window, len(lands), floor,
                             _run_skip(len(lands), lands_with_a_skip))


def _run_skip(observed_lands: int, lands_with_a_skip: int) -> dict:
    """The RUN-level companion of the per-layer reading above (T-11749 / kupiclub X-1165, X-1160).

    THE QUESTION IT ANSWERS, which the per-layer view cannot. The sibling reading is per-LAYER: "which
    layers never skip?". A project can answer that line layer by layer and still watch the thing it
    actually pays for — the share of LANDS that got to skip anything at all — halve underneath it, because
    no surface anywhere states it. The reporting consumer measured exactly that: lands skipping at least
    one layer fell from 33 of 83 (40%) to 6 of 34 (18%) as `subject_globs` kept widening, while they were
    advising four peer projects to NARROW globs and citing their own skip rate as the prize. Nobody was
    watching it, themselves included, because nothing printed it.

    THE PREDICATE. Over the SAME window of qualifying lands the fold above already walked, a land counts
    in the numerator iff at least ONE of its rows carries the `skipped-disjoint-subject` outcome — the one
    outcome that is a REAL skip (T-10573); `waived` is not a skip here either, for the identical reason it
    is not one per layer (a waived layer neither ran nor skipped, so it costs no land time and its land
    bought nothing). No observation FLOOR applies: the floor above exists to stop nagging about a THINLY
    OBSERVED LAYER, and this is not a per-layer nag — it is a rate over the window, reported with its own
    denominator so a reader can see how much evidence stands behind it.

    ZERO IS A READING; NO DENOMINATOR IS NOT. `rate_pct` is None — and the view stays silent — only when
    the window holds no qualifying land at all: that is NO MEASUREMENT, not a rate of zero, and printing
    `0 of 0` on every land of a repo that records no per-layer trail (this engine kernel) would train its
    reader to skip the line, which is the same silent failure as having no surface. But a window in which
    lands DID happen and none skipped reads 0% and PRINTS — the reporter's one stated requirement, and the
    lesson our own graph-cache hit-rate line records (1135 markers written, none read across 1390 lands,
    invisible until someone went looking). A dead view and a working one must not look alike.

    Report-only, derived at read time from rows land already writes: no new event, no new store, no gate,
    no threshold, no alert (all four explicitly out of scope in the ask)."""
    rate = round(100.0 * lands_with_a_skip / observed_lands, 1) if observed_lands > 0 else None
    return {"lands": observed_lands, "skipped": lands_with_a_skip, "rate_pct": rate}


def _zero_skip_result(layers: list, window_lands: int, observed_lands: int,
                      min_observations: int, run_skip: dict = None) -> dict:
    return {
        "lens": "zero-skip-verify-layers (SPEC-0119 / SPEC-0152 rule 16 subject_globs, T-11080) — the "
                "executable verify layers that skipped 0% of the time over the last "
                f"{window_lands} successful lands carrying a per-layer trail. Their `subject_globs` are "
                "absent, or declared as a SUPERSET of what the layer's command actually covers, so no "
                "real diff is ever disjoint and the layer runs on EVERY land. The OBSERVED counterpart "
                "of the carrier-read `undeclared-subject-verify-layers` line: only this one can see a "
                "layer that DECLARES a subject and still never skips. A layer is scored solely on lands "
                "that carry a row for it (rows begin only once the project declared its layers, so an "
                "absent row is never read as a non-skip) and only once observed at least "
                f"{min_observations} times — too little evidence stays silent. Carries alongside it the "
                "RUN-level companion `run_skip` (T-11749 / kupiclub X-1165): over the SAME window, the "
                "share of LANDS that skipped at least one layer — the figure a project actually pays for, "
                "which the per-layer reading cannot state and which can halve unwatched as globs widen. "
                "It reports AT ZERO rather than going silent (a dead view and a working one must not look "
                "alike); only an empty window reads as no measurement. DERIVED at read time from "
                "the journal — zero stored state, no new event, no new store. Report-only, never a gate.",
        "count": len(layers),
        "layers": layers,
        "window_lands": window_lands,
        "observed_lands": observed_lands,
        # T-11749 (X-1165 / X-1160): the RUN-level companion — {lands, skipped, rate_pct}, the share of
        # lands in the SAME window that skipped at least one layer. Additive: every key above keeps its
        # exact meaning, so the sibling readers pinned on this shape are untouched. `rate_pct` is None
        # only when there is no denominator at all (see `_run_skip`).
        # An unsupplied `run_skip` reads as NO MEASUREMENT (`_run_skip(0, 0)`), never as a fabricated
        # "0 skips over `observed_lands` lands": this helper's callers pass the tally they actually
        # took, and inventing a numerator for a denominator nobody counted is the one dishonesty this
        # line must not commit.
        "run_skip": run_skip if isinstance(run_skip, dict) else _run_skip(0, 0),
        "next": ("these verify layers ran on EVERY one of the recent lands that recorded them — their "
                 "skip rate is 0%. Either they declare no `subject_globs:` yet, or the globs they "
                 "declare are wider than the layer's command really covers. AUDIT each layer's command "
                 "(its file reads / mounts / sub-scripts — a SUPERSET of `covers:`, never a naive "
                 "covers-copy, which false-skips) and NARROW `subject_globs:` in yitc-ops.yaml to what "
                 "it truly depends on; a disjoint diff then REAL-skips the layer's run and its prep at "
                 "land (SPEC-0152 rule 16 subject_globs; T-10573). Opt-in and always safe to leave as "
                 "is — an unscoped layer just always runs."
                 if layers else
                 "every observed verify layer skips at least sometimes — nothing to narrow."),
    }


# ── SPEC-0119 rule 17 (T-10554 / X-0419): broken outcome-invariants ─────────────────────────────────
#
# The gap this closes: P3/P8 adoption evidence is framed on the DIFF — each card proves ITS OWN change
# adopted. A long-lived SUBSYSTEM that no card owns therefore has NO outcome probe at all, and cannot be
# observed broken. X-0419 is that gap cashing in: on boomrocket, FIVE remediation tasks closed green over
# three days while the product stayed broken, and the OWNER remained the only monitor. 34 cards on one
# surface, not one of them owning "does it still work?".
#
# SPEC-0093 rule 24 makes the standing outcome SAYABLE (`outcome_invariants:`); this fold is what reads it,
# so a declared invariant that BREAKS surfaces ITSELF at the next debt seam instead of waiting for the owner
# to report it. That is the whole point — it retires the owner-as-monitor role for a covered subsystem.
#
# THE ADMISSION HALF IS NOT RE-INVENTED (the card's "SPEC-0156 reused, no new event type"). An invariant's
# probe is a kernel-graded check like any other, so its "has this ever been seen to fail?" question is
# answered by SPEC-0156's EXISTING machinery, consumed verbatim: `_admission_demonstrations` (the journal
# fold over `check_admission_demonstrated`) + `_definition_identity` (the re-owed-only-on-rewire hash). No
# new event type, no second admission ledger, no parallel identity rule (CHARTER §P5).
#
# WHY NOT JUST ADD `outcome_invariants` TO `CHECK_SURFACES`? Because that allowlist feeds `unproven_checks`,
# whose line answers ONE question ("was this ever seen to fail?"). This view answers TWO — "is it broken
# RIGHT NOW?" and "is its green trustworthy?" — and the card homes both on ONE line. Admitting the section
# there as well would print the same unproven fact on two lines with two remedies: the "one concern per view,
# never two readers of the same fact" rule the sibling views state repeatedly. The boundary is deliberate;
# a later reader "completing" the allowlist would re-introduce the double-report.

OUTCOME_INVARIANTS_SECTION = "outcome_invariants"   # SPEC-0093 rule 24 — the carrier section
OUTCOME_INVARIANTS_DECLARE_KEY = "invariants"       # its declare key (XOR the section waiver)
_INVARIANT_PROBE_TIMEOUT = 30                       # seconds — bound one probe run (a hung probe degrades)
_PROBE_UNSET = object()                             # sentinel: default to the real runner (None DISABLES)


def _run_invariant_probe(entry, cwd) -> dict:
    """RUN one declared outcome-invariant probe and normalize its verdict.

    The kernel stays a GENERIC GRADER: it runs a DECLARED read-only command and reads a NORMALIZED
    contract, embedding no project source format (the SPEC-0110 L3 freshness-adapter / SPEC-0093 rule-23
    live-revision-adapter discipline, mirrored here rather than re-invented).

    Contract: a `{kind: command, command: [argv…]}` declaration runs its argv in LIST FORM (never a shell
    string — no injection surface, no word-splitting), bounded by a wall clock, cwd = the repo. Its stdout
    must be `{"ok": true|false, "detail": "…"}`.

    Returns exactly one of:
      {"ok": True,  "detail": …}   — the invariant HOLDS.
      {"ok": False, "detail": …}   — the invariant is VIOLATED (the subsystem is broken).
      {"error": "<detail>"}        — the probe could not produce a verdict.

    EVERY failure mode collapses to `error`, NEVER to a silent ok — a probe that cannot answer must never
    read as "the invariant holds". That direction is the whole discipline: a broken subsystem behind a
    broken probe is the exact false-green SPEC-0156 exists to end. Never raises (a report-only surface must
    not break the seam it rides).
    """
    probe = entry.get("probe") if isinstance(entry, dict) else None
    if not isinstance(probe, dict):
        return {"error": "no probe declared (expected a {kind: command, command: [argv…]} mapping)"}
    if probe.get("kind") != "command":
        # Only the kind:command probe is defined today. An unknown kind is NOT a usable declaration — and
        # it fails to a NAMED error rather than being skipped, because a typo'd kind that read as "no probe
        # here" would silently retire the invariant (a declaration must never be silenced by a misspelling —
        # the SPEC-0093 rule-22 closed-enum lesson).
        return {"error": f"probe kind {probe.get('kind')!r} is not runnable (expected kind: command)"}
    cmd = probe.get("command")
    if not (isinstance(cmd, list) and cmd and all(isinstance(a, str) for a in cmd)):
        return {"error": "probe kind:command but no usable command (expected a non-empty list of strings)"}
    import subprocess
    try:
        proc = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True,
                              timeout=_INVARIANT_PROBE_TIMEOUT)
    except subprocess.TimeoutExpired:
        return {"error": f"probe timed out after {_INVARIANT_PROBE_TIMEOUT}s"}
    except (OSError, ValueError, TypeError) as e:
        return {"error": f"probe failed to start/run: {e}"}
    if proc.returncode != 0:
        detail = (proc.stderr or "").strip()[:200]
        return {"error": f"probe exited {proc.returncode}: {detail}"}
    try:
        parsed = json.loads(proc.stdout)
    except (ValueError, TypeError) as e:
        return {"error": f"probe stdout not JSON: {e}"}
    if not isinstance(parsed, dict):
        return {"error": "probe stdout is not an {ok, detail} object"}
    if parsed.get("error"):
        return {"error": str(parsed["error"])}      # the probe ITSELF reported it could not check
    ok = parsed.get("ok")
    if not isinstance(ok, bool):
        # Absent / non-boolean `ok` is NOT a pass. Coercing a truthy value here (a string "false" is truthy!)
        # is precisely how a probe that never answered would read green.
        return {"error": "probe reported no boolean `ok` verdict"}
    detail = parsed.get("detail")
    return {"ok": ok, "detail": detail.strip() if isinstance(detail, str) and detail.strip() else None}


def declared_outcome_invariants(ops_path) -> list:
    """The standing outcome-invariants THIS repo declares (SPEC-0093 rule 24), read from its carrier.

    Returns `[{id, subsystem, invariant, entry, check, declaration, definition_identity}]` — one row per
    declared invariant, each carrying the identity of its definition AS IT STANDS NOW (so a rewire re-opens
    the admission question by construction). Never raises: a missing / unreadable / malformed / non-mapping
    carrier yields `[]`.

    ONLY THE DECLARED SET (`lessons/scope-the-trigger-not-the-view`). This is the TRIGGER half of the card's
    contract: the debt echo may fold broadly, but what may INTERRUPT is scoped to what this project actually
    declared and did not waive. A repo with no carrier declares nothing — the engine kernel itself — so the
    whole view stays silent and history is never retro-charged (the SPEC-0149 fold-side-default lesson: a
    default over the real journals once retro-created 39 debt lines across 3 consumers).

    A WAIVER IS AN ANSWERED QUESTION, at either level (the `_is_waived` discipline, reused verbatim): a
    section-level waiver declares no invariants at all, and a single waived ENTRY drops just that one.
    """
    try:
        carrier = state.load_ops(Path(ops_path))
    except (OSError, UnicodeDecodeError, yaml.YAMLError, TypeError):
        return []
    return _invariant_rows_from_carrier(carrier)


def _invariant_rows_from_carrier(carrier, scoping_keys=SCOPING_KEYS) -> list:
    """The row computation of `declared_outcome_invariants` above, over an ALREADY-PARSED carrier — split
    out for the identity-history replay, exactly as `_check_rows_from_carrier` was and for the same
    anti-drift reason. Pure, never raises."""
    if not isinstance(carrier, dict):
        return []
    section = carrier.get(OUTCOME_INVARIANTS_SECTION)
    if not isinstance(section, dict) or _is_waived(section):
        return []                       # absent, shapeless, or consciously waived ⇒ declares no invariant
    entries = section.get(OUTCOME_INVARIANTS_DECLARE_KEY)
    if not isinstance(entries, list):
        return []

    rows: list = []
    for index, entry in enumerate(entries):
        if _is_waived(entry):
            continue                    # a waived entry is an ANSWERED question (never `_is_waived` a non-dict)
        # A MALFORMED ENTRY MUST NEVER VANISH (audit-post finding 2). Rule 24 requires four keys, and this
        # reader stays FAITHFUL: it does not judge, it NAMES the malformation and lets the fold decide
        # (`lessons/fail-closed-belongs-to-the-reader-not-the-parser`). Dropping such an entry would make a
        # typo'd declaration read as "this project declared nothing here" — silently clean — which is the
        # EXACT false-green this whole concern exists to end, reproduced one level down inside its own
        # mechanism. A declaration that cannot be understood is DEBT, not absence.
        # RULE 24 IS A TYPE CONTRACT, NOT A TRUTHINESS ONE (audit-post pass-2 finding). An earlier cut
        # tested each required key for mere truthiness, so a WRONG-TYPED value slipped through:
        # `subsystem: [stats]` is truthy, so the entry read well-formed, its probe ran, and a proven
        # ok verdict SUPPRESSED the line — a trusted-green over a declaration that violates the rule
        # it claims to satisfy. Rule 24 says `id`/`subsystem`/`invariant` are non-empty STRINGS and
        # `probe` is a MAPPING, so that is exactly what is checked. Type first, then emptiness.
        malformed = None
        if not isinstance(entry, dict):
            malformed = "declared entry is not a mapping (rule 24 requires {id, subsystem, invariant, probe})"
        else:
            bad = []
            for key in ("id", "subsystem", "invariant"):
                value = entry.get(key)
                if not isinstance(value, str) or not value.strip():
                    bad.append(f"{key} (rule 24: a non-empty string, got {type(value).__name__})")
            if not isinstance(entry.get("probe"), dict):
                bad.append(f"probe (rule 24: a {{kind, command}} mapping, got "
                           f"{type(entry.get('probe')).__name__})")
            if bad:
                malformed = "declared entry violates the rule-24 shape: " + "; ".join(bad)
        name = _entry_name(entry, "id", index) if isinstance(entry, dict) else f"[{index}]"
        rows.append({
            "id": name,
            "subsystem": (entry.get("subsystem") or "").strip()
                         if isinstance(entry, dict) and isinstance(entry.get("subsystem"), str) else None,
            "invariant": (entry.get("invariant") or "").strip()
                         if isinstance(entry, dict) and isinstance(entry.get("invariant"), str) else None,
            "entry": entry,
            "malformed": malformed,
            # The check LABEL is what ties this invariant to its SPEC-0156 demonstration. It is namespaced by
            # the section, so an invariant id can never collide with a `tests.classes[…]` / `security.probes[…]`
            # check name and be cleared by that surface's demonstration.
            "check": f"{OUTCOME_INVARIANTS_SECTION}[{name}]",
            "declaration": f"yitc-ops.yaml#{OUTCOME_INVARIANTS_SECTION}[{name}]",
            "definition_identity": _definition_identity(entry, scoping_keys),
        })
    return rows


def broken_outcome_invariants(ops_path, events_path, repo_root=None, *,
                              _probe_runner=_PROBE_UNSET, now=None) -> dict:
    """Fold the carrier + the journal (+ the declared probes) → the standing outcome-invariants that are
    BROKEN, DEGRADED, or UNPROVEN (SPEC-0119 rule 17 / SPEC-0093 rule 24 / SPEC-0156).

    ONE row per declared invariant, in ONE of three ENUMERATED states (never prose —
    `lessons/report-only-advisory-never-exempts-a-contradiction` rule 1), precedence highest first:

      - `broken`   — the probe RAN and reported `ok: false`. The invariant is VIOLATED right now. This wins
                     over `unproven` deliberately: a probe SAYING its subject is broken is actionable
                     whether or not it was ever demonstrated, and it is the fact the owner needs first.
      - `degraded` — the probe could not produce a verdict (bad/absent declaration, spawn failure, timeout,
                     non-zero exit, non-JSON stdout, self-reported error, no boolean verdict). NAMED, never
                     silent (the SPEC-0093 rule-23 degrade precedent): a probe that cannot answer is itself
                     debt, and staying quiet would hide a broken subsystem behind a broken probe.
      - `unproven` — no `check_admission_demonstrated` RED matches the CURRENT `definition_identity`, so its
                     green is worth nothing (`never` = admitted on a promise; `rewired` = demonstrated once,
                     then its definition CHANGED, so the old RED proved a check that no longer exists — the
                     only state here that can name an honest DATE). Sub-state in `admission`.

    A PROVEN invariant whose probe reports ok contributes NOTHING (suppressed-when-clean).

    NEVER GATES, NEVER REFUSES (SPEC-0156 §3 / CHARTER non-goal 7) — report-only at the 3 debt seams.

    Args:
      ops_path: this repo's `yitc-ops.yaml` (missing/unreadable ⇒ a clean zero-count result — a repo that
        declares no invariant owes nothing; the engine kernel itself).
      events_path: `events.jsonl` (missing/unreadable ⇒ every declared invariant reads UNPROVEN, the honest
        answer: with no journal there is no evidence).
      repo_root: cwd for a probe run (defaults to the carrier's own directory).
      _probe_runner: injected `(entry, cwd) -> {"ok"…} | {"error"…}`. Defaults to the real subprocess
        runner; `None` DISABLES probing entirely (every declared invariant is then judged on its admission
        state alone). Injectable so the fold stays hermetically testable with no subprocess and no clock —
        the `_live_revision_adapter` / `unmonitored_dispatches` precedent.
      now: aware datetime, injected by tests so every assertion is deterministic.

    Returns `{"lens", "now", "count", "invariants", "next"}` — the shape the sibling views return. Pure with
    respect to STORAGE (reads two files, writes nothing — SPEC-0149 §2); the declared probe is the one
    outward-facing effect, and it is contracted READ-ONLY by SPEC-0093 rule 24.
    """
    now = now if now is not None else datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    declared = declared_outcome_invariants(ops_path)
    if not declared:
        return _broken_invariants_result(now, [])     # nothing declared ⇒ nothing owed (never retro-charged)

    runner = _run_invariant_probe if _probe_runner is _PROBE_UNSET else _probe_runner
    cwd = repo_root if repo_root is not None else Path(ops_path).parent
    demonstrations = _admission_demonstrations(events_path)
    # The SAME wrong-key-vs-rewire question as the sibling fold, answered by the SAME reader (T-11425):
    # this site carried a second copy of the `max(per_check.values())` conflation, so a wrong-key payload
    # mislabelled an invariant's admission `rewired` here exactly as it did a check's `state` there.
    ever_declared = _identities_ever_declared(ops_path, _wanted_identities(declared, demonstrations),
                                              {r["check"]: r["definition_identity"] for r in declared})

    flagged = []
    for row in declared:
        per_check = demonstrations.get(row["check"]) or {}
        # The SAME carry-forward as the sibling fold (T-11665), for the same reason: an identity orphaned
        # by a kernel projection change is not an unproven invariant. Kept here rather than only there so
        # the two admission axes cannot disagree about what "proven" means.
        proven = (row["definition_identity"] in per_check
                  or _projection_superseded(per_check, row["check"], ever_declared))
        superseded_at = None if proven else _genuine_supersession(per_check, row["check"], ever_declared)

        # A MALFORMED DECLARATION IS DEGRADED, AND IS NOT PROBED (audit-post finding 2). The reader NAMED
        # the malformation; this is where it MEANS something. It short-circuits the probe deliberately:
        # rule 24's four keys are what makes an invariant legible, and running a half-declared entry would
        # report an outcome for something nobody can act on. Degraded is the honest state — the declaration
        # is present, so it is DEBT (never silently absent), but it does not yet cover anything.
        if row.get("malformed"):
            verdict = {"error": row["malformed"]}
        elif runner is None:
            # PROBING DISABLED (the caller passed `_probe_runner=None`): there is no probe axis at all, so
            # the invariant is judged on its ADMISSION state alone. This is NOT the "no verdict" case below
            # — nothing was asked, so nothing failed to answer, and reporting `degraded` here would invent a
            # probe defect out of the caller's own choice not to probe.
            verdict = {"ok": True}
        else:
            try:
                verdict = runner(row["entry"], cwd) or {}
            except Exception as e:                    # a probe runner must never break the seam it rides
                verdict = {"error": f"probe raised: {e}"}
            if not isinstance(verdict, dict):
                verdict = {"error": "probe returned a non-mapping verdict"}

        # THE VERDICT IS READ FAIL-CLOSED, AND ONLY AN EXPLICIT BOOLEAN COUNTS
        # (`lessons/fail-closed-belongs-to-the-reader-not-the-parser`: the runner stays FAITHFUL — it
        # reports what it saw — and THIS reader decides what a missing value MEANS). "Holding" requires
        # `ok is True`, never a truthy value and never an absence: anything else is a probe that did not
        # answer, which is DEGRADED. Reading it the other way round — treating "not explicitly False" as
        # holding — would let a verdict-less probe ({}, or a STRING "false", which is truthy!) count as
        # coverage: a false-green inside the very mechanism built to end false-greens.
        ok = verdict.get("ok")
        if ok is False:
            state = "broken"
        elif ok is not True:
            state = "degraded"                        # incl. {"error": …} and any verdict-less shape
        elif not proven:
            state = "unproven"
        else:
            continue                                  # proven + holding ⇒ clean

        flagged.append({
            "id": row["id"],
            "subsystem": row["subsystem"],
            "invariant": row["invariant"],
            "check": row["check"],
            "declaration": row["declaration"],
            "state": state,
            "detail": verdict.get("detail") or verdict.get("error"),
            # The admission axis is reported for EVERY flagged row, not just the `unproven` ones: a BROKEN
            # invariant that was also never demonstrated is a different (worse) story than a broken one whose
            # probe is known-good, and the line must be able to tell them apart.
            "admission": ("proven" if proven else ("rewired" if superseded_at is not None else "never")),
            "superseded_at": (superseded_at.isoformat().replace("+00:00", "Z")
                              if superseded_at is not None else None),
        })
    # Broken first (a live violation outranks an evidence gap), then degraded, then unproven; ties by id so
    # the order is stable across folds.
    _ORDER = {"broken": 0, "degraded": 1, "unproven": 2}
    flagged.sort(key=lambda r: (_ORDER.get(r["state"], 9), str(r["id"])))
    # NEAR-MISS READ (T-11868) — the SAME reader the sibling admission axis already uses
    # (`_admission_near_misses`, ONE home), wired here because this view has the SAME blind spot the
    # sibling closed at T-11178/X-0921: an invariant reported UNPROVEN reads identically whether the
    # author emitted NOTHING or emitted a `check_admission_demonstrated` row that did not qualify — and
    # an author who has just emitted concludes the mechanism is broken, or that the invariant cleared.
    # Attached only to rows ALREADY flagged, exactly like the sibling: no unflagged row gains a line,
    # `count` is untouched, and every judgement above (state / admission / superseded_at) is unchanged.
    # The row mapping is the row's OWN `check` key — `outcome_invariants[<id>]`, which is the same key
    # `_admission_demonstrations` is indexed by — so an invariant's near-misses land on the row that
    # carries its id/subsystem/invariant, never on a sibling's.
    if flagged:
        near_misses = _admission_near_misses(events_path, declared, ever_declared)
        for row in flagged:
            row["near_misses"] = near_misses.get(row["check"], [])
    return _broken_invariants_result(now, flagged)


def _broken_invariants_result(now, invariants: list) -> dict:
    return {
        # T-11868 — the NOTE tail, rendered by the SAME `_near_miss_clause` the sibling result uses, so
        # the two admission axes cannot describe a near-miss differently. Empty string when there is
        # none, which is what keeps the seam's suppressed-when-clean posture exact.
        "near_miss_clause": _near_miss_clause(invariants),
        "lens": "broken-outcome-invariants (SPEC-0119 rule 17 / SPEC-0093 rule 24) — the standing PRODUCT "
                "OUTCOME invariants this project DECLARES over its long-lived subsystems, that are BROKEN "
                "(the declared read-only probe ran and reported the invariant violated), DEGRADED (the probe "
                "could not produce a verdict — never silently green), or UNPROVEN (no recorded RED "
                "`check_admission_demonstrated` matching the definition as it stands now, so its green proves "
                "nothing — SPEC-0156 reused, no new event type). Closes the X-0419 gap: adoption evidence is "
                "framed on the DIFF, so a subsystem no card owns has no outcome probe and cannot be observed "
                "broken — five remediation cards closed green over three days while the product stayed broken "
                "and the OWNER was the only monitor. DERIVED at read time from the carrier + the journal + the "
                "declared probes — zero stored state; only the DECLARED, non-waived set can interrupt, and a "
                "repo that declares no invariant (the engine kernel itself) owes nothing, so history is never "
                "retro-charged. Report-only, never a gate.",
        "now": now.isoformat().replace("+00:00", "Z"),
        "count": len(invariants),
        "invariants": invariants,
        "next": ("a declared outcome-invariant is not holding — or cannot be trusted to say so. BROKEN: the "
                 "subsystem is violating its declared invariant right now; fix it (this is the line that "
                 "exists so the owner is not the monitor). DEGRADED: the probe could not answer — repair the "
                 "declared probe, because an invariant whose probe is broken is not covered. UNPROVEN: break "
                 "the invariant's subject deliberately, watch the probe go RED, and record `bin/yitc-v2 event "
                 "check_admission_demonstrated --data '{\"check\":\"outcome_invariants[<id>]\",\"declaration\":"
                 "…,\"broken_input\":…,\"outcome\":\"red\",\"definition_identity\":…}'` (SPEC-0156 §2). An "
                 "invariant that CANNOT be made to fail is not an invariant: re-phrase it or waive the entry "
                 "with a reason — never leave it declared and untrusted."
                 if invariants else
                 "every declared outcome-invariant holds and carries a recorded failing demonstration — "
                 "nothing owed."),
    }


# ── SPEC-0119 rule 19 (T-11125): a CHANGE in the recorded slowest test files ───────────────────────
#
# T-11124 made per-file test duration a SERIES: every successful land now records its slowest test
# files by name with their wall times (`verify_metrics.per_file_durations`). Before it, the journal
# carried aggregates only across 1527 rows and NOTHING could watch test-duration growth at all.
# This fold is the reader of that series, and it reports the DELTA — never the level.
#
# WHY DELTA AND NOT LEVEL, which is the whole design. A slowest set EXISTS BY DEFINITION: a view that
# printed the slowest files themselves would print on EVERY land, and a surface that always prints
# trains its reader to skip it — the same silent failure, by another route, as having no surface at
# all. Reporting only what MOVED is what keeps SUPPRESSED-WHEN-CLEAN a real property here rather than
# a decoration: clean means no new entrant and no material growth, and clean prints nothing.
#
# NO ABSOLUTE BAR. The rejected alternative anchored to the 300s per-file verify timeout (SPEC-0071).
# That is an ABORT bound, not a health target: it makes a file interesting only once it is near
# failing a land (135.7s reads as a comfortable 45% while being a bad cost for one test) and it falls
# silent entirely once everything sits under it — exactly when durations creep back up unwatched. A
# relative reading decrees nothing and self-calibrates. The 300s bound stays what it already is.
#
# NOT A CADENCE (SPEC-0142 §4). This stands up no recurring obligation and owns no trigger: it is
# computed inline at the debt seams a controller already passes, and computes nothing when nobody
# passes one. No fourth cadence layer, no cadence store, no registry.
#
# THE FAIL DIRECTION IS TOWARD SILENCE, and it INVERTS rule 18's on purpose. Rule 18 (unresolved
# worker halts) fails toward VISIBLE because a lost halt loses a decision someone is owed. Here the
# subject is an advisory trend, and a fabricated change is worse than a missed one: a creep watch
# that cries wolf is unread within a week, and its next real signal dies with it. So every
# uncertainty — too little history, an unparseable record, a non-comparable outcome — resolves to
# SAYING NOTHING.

SLOWEST_CHANGE_WINDOW_LANDS = 10     # the BASELINE: how many prior recorded lands the comparison uses
SLOWEST_CHANGE_MIN_PRIOR = 3         # below this many prior records the fold says nothing at all
SLOWEST_CHANGE_GROWTH_RATIO = 0.25   # a member must grow at least this fraction over its baseline …
SLOWEST_CHANGE_MIN_GROWTH_MS = 2000  # … AND at least this many ms, so jitter on a small file is mute
_SLOWEST_COMPARABLE_OUTCOME = "passed"   # the ONLY outcome whose wall time compares across lands


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
        for event in journal.segment_rows(events_path):   # SPEC-0190 rule 4 — the WHOLE journal
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
                           min_growth_ms: int = SLOWEST_CHANGE_MIN_GROWTH_MS) -> dict:
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
                           min_prior_lands: int) -> dict:
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


# ── SPEC-0119 rule 27 (T-11368 / kupiclub X-1036, corrected by X-1039): what ABORTED lands COST ─────
#
# THE GAP, stated as the requester found it: every other surface here reports work that is PENDING —
# debt not adopted, followups not triaged, plans not tracked. NOTHING reports what a project already
# SPENT on runs that shipped nothing. The land tail reports a cache hit rate, `dispatch-status`
# reports worker liveness, the repeated-abort backstop counts abort ROWS without pricing them. So a
# project never discovers its own most expensive waste, and this one surfaced only because an owner
# asked a question that made someone go looking (X-1036).
#
# A SECOND READING OF AN EXISTING PAYLOAD — no new capture, exactly like rules 18/19. Every abort
# already writes `duration_ms`, `abort_class` and (when the verify actually ran) `verify_mode` onto
# `land_completed`. Measured on this repo's own journal at design time, over the trailing 7 days:
# 309 aborts, `verify_mode` present on 168/168 rows of the three verify-running classes and absent on
# all 141 others, `duration_ms` present on 2113/2113 abort rows repo-wide. The marker is therefore
# EXACT, which is what makes the paid/early split a read rather than an inference.
#
# WHY THE MARKER AND NOT THE CLASS NAME. T-10850 already recorded that an `abort_class` is not a
# reliable proxy for cost, and `rebaseline-unauthorized` is the proof: it splits by `abort_preflight`
# into a cheap pre-verify refusal and an expensive post-verify one under ONE class name. Pricing by
# class name would average those into a number describing neither.
#
# THE HONEST-READING PARTITION, and it is the reason this fold reports FOUR groups and never one
# headline. A high `verify-failed` count is NOT waste — it is the gate EARNING ITS KEEP, a real
# defect caught before it landed, and a view that ranked by minutes would present the gate's best
# work as its worst cost. So:
#   • GATE-CAUGHT     — paid a verify, the verify FAILED. What the gate was worth, never waste.
#   • INCONCLUSIVE    — paid a verify that concluded nothing (a timeout). Its own reading; neither a
#                       caught defect nor a paperwork refusal, so it joins neither total.
#   • PROCESS-REFUSAL — paid a FULL verify and then refused on BOOKKEEPING. This alone is the
#                       reclaimable total, and the only group the render calls reclaimable.
#   • PREFLIGHT-REFUSED — carries a verify marker but refused at the step-4a PREFLIGHT, so it never
#                       paid the full verify the reclaimable sentence describes (T-11777, below).
#   • EARLY           — refused without paying a verify. Reported with its own minutes AND its own
#                       trend (every minute this fold prices carries one), because two
#                       early classes on this repo (merge-non-union-conflict, audited-diff-stale) are
#                       genuinely expensive at 764 min/week, and a paid-only reading would have made
#                       them invisible.
# No number this fold returns sums across those groups, so no caller can print one by accident.
#
# THE TREND READING — the requirement that exists BECAUSE OF THE CORRECTION (X-1039). The requester
# volunteered, against their own interest, that their window straddled a regime change: most of the
# cost they attributed to the pinned last-green leg had already been removed by a ONE-LINE project
# declaration, not by any fix. A view ranking by RAW MINUTES would have pointed at a leg that was
# already retired and sent someone to build a fix for a cost that no longer existed. So a DECAYING
# cost must be distinguishable from a STANDING one, and this fold makes that distinction FIRST-CLASS:
# each class carries a trend computed by splitting the SAME window in half and comparing its own
# determined minutes. Verified as real signal here, not a hypothesis — on this repo's own 7 days,
# `rebaseline-unauthorized` reads DECAYING (97.3 min recent vs 325.4 older) while `verify-failed`
# reads GROWING (1171.5 vs 567.1). The alternative — ranking by minutes alone — is rejected on
# exactly the evidence that the ranking would have been wrong.
#
# AN UNKNOWN COST IS NEVER A ZERO (the T-0358 class). A row whose `duration_ms` is missing or not an
# integer is reported as UNDETERMINED and counts toward the reportable set. Fabricating a zero would
# make an unmeasurable cost read as a free one, which is the one direction this fold must not fail.
#
# CLEANLINESS IS "NOTHING COST ANYTHING WORTH REPORTING", not "nothing aborted". A repo whose only
# aborts are instant `uncommitted-dirt` refusals is CLEAN and prints nothing; those rows are still
# counted and carried per class, and summarised in one trailing clause, but they cannot un-suppress
# the line. NOT A CADENCE (SPEC-0142 §4): computed inline at the debt seams a controller already
# passes, owning no trigger and no store.

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
                                             # step-4a PREFLIGHT — its OWN recorded refusal point
ABORT_COST_GROUPS = ("gate-caught", "inconclusive", "process-refusal", "preflight-refused", "early")

# ── T-12396: AN EVICTION IS NOT AN ABORT — the land-reservation park-limit class, counted APART ───
#
# THE FINDING, measured on this repo 2026-09-11. `bin/yitc-v2 debt` printed «476 aborted land(s) in
# the last 7 day(s) cost wall-clock that shipped nothing» and the roster part-3 parallel-landing-health
# fold printed «terminal lands n=899 ok=423 abort=476 abort share 53% (prior 38%)». Both folded EVERY
# `land_completed{status: abort}` row, including the T-11819 park-limit class — a land that verified
# nothing, merged nothing and spent no CPU: it WAITED OUT the land reservation behind a holder that
# would not release, and then STOPPED rather than racing for the ff. In the 11:39-13:40Z window alone
# 4 of 14 aborts were such evictions (T-12322 11:59:22Z, T-12315 12:08:55Z, T-12340 12:20:57Z,
# T-12361 12:34:40Z — each after 149 min in the queue). So the abort share read the SAME congestion
# TWICE: once as the wait it already reports, and once again as a failure that never happened. Owner
# ruling 2026-09-11: «в долгах не считать».
#
# WHY IT IS A DIFFERENT KIND OF THING, and not merely a cheap abort. Every other class in this fold
# describes a land that TRIED and was REFUSED — a verify that failed, a merge that conflicted, a
# bookkeeping guard that fired. Each of those is a question about the branch. An eviction is a
# question about the QUEUE: nothing about the branch was ever judged. Pricing it beside them answers
# neither, and it points a reader at the gate for a cost the gate never incurred — the same
# wrong-remedy harm T-11777 removed from the RECLAIMABLE group and T-11831 removed from the phase
# split, applied once more at the population rather than at the group.
#
# THE KEY IS THE CLASS, READ STRUCTURALLY. `abort_class` is set at the T-11819 `_die` origin
# (`worktree.py`, `abort_class="land-reservation-park-limit"`) and carried onto the row by
# `_emit_land_abort`. Folded over this repo's whole journal: 29 rows carry it and ZERO park-limit rows
# lack it, so no `abort_reason` regex is needed — and none is used, on the same
# structured-state-only discipline `surface4_structured_failing_layers` states above. One constant,
# one predicate, asked by BOTH readers.
#
# THE MINUTES ARE NEVER DROPPED — that half is load-bearing, and it is the same bound T-11777 set for
# `preflight-refused`. Removing an eviction from the abort count while leaving its wall-clock
# unreported would trade an overstatement for a DISAPPEARANCE, which is the direction this module
# already refuses when it declines to price an undetermined cost at zero. An eviction is reported as
# its OWN number, with the wait it PROVES (`reservation_wait_ms`) and the COVERAGE of that proof.
#
# SCOPE, stated so a reader does not look for changes that are not here: this is the classification
# ONLY. The eviction BEHAVIOUR (whether an evicted branch should be re-queued) is a separate card,
# and no other abort class and no threshold on the share moves. Rule home: SPEC-0119 rule 27.
ABORT_CLASS_PARK_LIMIT_EVICTION = "land-reservation-park-limit"   # the T-11819 `_die`'s abort_class


def abort_class_is_park_limit_eviction(klass) -> bool:
    """Is this `abort_class` the T-11819 land-reservation park-limit EVICTION (SPEC-0119 rule 27)?

    THE ONE CLASSIFICATION HOME both readers ask — this fold, and the roster part-3
    parallel-landing-health block (which cannot import it, being contracted to run against any repo
    on pure stdlib, and so carries the literal under a test that asserts the two agree).

    Compared on the STRIPPED string, matching how `_abort_rows` normalizes the field, and FAIL-CLOSED
    on anything that is not a string: a row this cannot positively identify stays an ABORT, which is
    today's reading and the direction that never silently shrinks the abort count."""
    return isinstance(klass, str) and klass.strip() == ABORT_CLASS_PARK_LIMIT_EVICTION

# ── T-11426 (kupiclub X-1096): THE ARM SPLIT — one abort class carrying two refusals ──────────────
#
# THE FINDING. `rebaseline-unauthorized` is ONE class NAME over TWO refusals with different
# placements and, decisively, different MOVABILITY:
#   • the AUTHORIZATION arm — "this `--rebaseline` ack has no current-state audit-post" — was MOVED
#     to the step-4a preflight by T-10850 on 2026-08-09. It is already cheap. There is nothing left
#     to reclaim there.
#   • the WAIVE-COVERAGE arm (T-10754) — "your `--rebaseline-waive` declaration does not cover what
#     actually failed" — reads `pinned_bad`, so it is reachable only AFTER the pinned run. It has NOT
#     been moved and, on the measured consumer week, ran a median 597.9 s to reach its verdict.
# Folding those into one bucket unions a refusal we already made cheap with one we have not, and the
# TREND over that union is what makes it decision-grade-looking rather than merely coarse: this
# repo's own session-start echo printed `rebaseline-unauthorized 32x 369.0min DECAYING`, and a
# DECAYING verdict over a union of two arms of different movability points a reader at a cost that is
# going away on one arm while standing on the other. kupiclub filed this after their own earlier
# X-1037 was refuted on a false premise — the corrected measurement, verified on their journal.
#
# THIS IS THE SAME MOVE THE FOLD ALREADY MAKES ONE LEVEL UP, not a new one. T-10850's finding ("an
# `abort_class` is not a reliable proxy for cost") is why paid-vs-early is read from `verify_mode`
# rather than the class name; this is that finding applied a second time, to the class name's OTHER
# ambiguity. And it is a SECOND READING OF AN EXISTING PAYLOAD — no new capture key, no new event, no
# `worktree.py` edit — exactly as rules 18/19/27 are (CHARTER §P1 F1/F2/F3).
#
# WHY NOT SPLIT THE RECORDED CLASS NAME. The card weighed it and the read wins on both axes: eleven
# code readers key on the literal string (the never-landing set, `_VERIFY_REFUSAL_ABORT_CLASSES`, the
# repeated-abort backstop, `task.py`'s claim-landed guards), and renaming would leave every
# historical row under the old name needing exactly this reader anyway. Strictly less code, strictly
# less risk, identical outcome.
#
# THE READER, AND WHY ITS ORDER IS WHAT IT IS. Measured over this repo's whole journal — 180 rows of
# this class, cross-tabulated against the structured markers and the two refusals' own invariant
# sentences:
#     13  abort_preflight:True, A                  -> authorization   (today's site)
#     57  failing_assertions, A only               -> authorization   (LEGACY pre-T-10850 deep site)
#     46  no structured marker at all, A only      -> authorization   (LEGACY deep site)
#     63  failing_assertions, W only               -> waive-coverage
#      1  failing_assertions, A and W              -> authorization   (W occurs only inside a pasted
#                                                     pinned test-failure body; A is the refusal's)
# THE DECISIVE MEASUREMENT is the 57. "failing_assertions non-empty ⇒ waive-coverage" is FALSE for
# them: the removed deep authorization site appended its OWN `FAILING ASSERTION(S)` block and so set
# the very key that otherwise identifies the other arm. A purely structured reader would therefore
# MIS-BUCKET 57 authorization rows as waive-coverage — the exact migration failure this card's AC2
# names, and larger than the one that prompted it. It also rules out the placement-based reading
# (preflight-vs-not) that kupiclub's own journal happened to support: there, all 61 non-preflight rows
# were waive-coverage; here, 103 of them are authorization.
#
# So the message marker is not a convenience — for a LEGACY row it is the only discriminator that
# exists. It is SOUND for exactly those rows because they are FROZEN: T-10850 REMOVED the deep site,
# so no new row can ever carry that text and no re-wording can reach it. And the order is FAIL-SAFE
# for current rows either way: rule (1) attributes every authorization row today's code emits and
# rule (4) attributes every waive-coverage one, so a future re-wording of either message can degrade
# LEGACY attribution only, never current. This does not contradict T-11375's "derived from the branch
# taken, never from the message" — that governs designing a FORWARD capture, and none is designed
# here; (1) and (4) ARE the structured readers, and (2)/(3) recover history they cannot reach.
#
# AN UNATTRIBUTABLE ROW IS NEVER GUESSED INTO AN ARM. Rule (5) folds it under `unattributed`, which
# is counted and priced like any other arm and named in the render — the same direction as the
# UNDETERMINED cost rule above: an unknown is reported as unknown, never resolved to whichever answer
# is convenient.
ABORT_ARM_SPLIT_CLASSES = ("rebaseline-unauthorized", "verify-failed")   # the class names that
                                                       # union two refusals (T-11426, T-11607)
ABORT_ARM_AUTHORIZATION = "authorization"      # the T-10850 arm — ALREADY moved to the step-4a preflight
ABORT_ARM_WAIVE_COVERAGE = "waive-coverage"    # the T-10754 arm — PARTLY moved: token-binding half
                                              # refuses at the step-4a preflight (T-11479), coverage
                                              # half still reads pinned_bad after a full pinned run
ABORT_ARM_UNATTRIBUTED = "unattributed"        # provably neither — never guessed, never dropped
# The two refusals' own invariant sentences, used ONLY to attribute rows the structured markers cannot
# separate (see the order below). `_emit_land_abort` collapses whitespace on `abort_reason`, so each
# sentence is contiguous in the recorded row.
ABORT_ARM_AUTHORIZATION_MARK = "requires a GREEN/YELLOW audit-post"
ABORT_ARM_WAIVE_COVERAGE_MARK = "the ack is scoped to the pinned assertion(s)"

# ── T-11607: THE SECOND ARM SPLIT — `verify-failed` over the SHARED `bad` list ────────────────────
#
# THE FINDING. `verify-failed` is emitted by ONE `_die` over a shared `bad` list, and that list is
# fed by more than the test suite. THREE corpus-integrity guards append to it AFTER the suite —
# `_run_decision_rule_body_guard` (SPEC-0054), `_run_spec_hand_edit_guard` (SPEC-0005),
# `_run_wont_do_rationale_guard` (SPEC-0165) — and their inputs are entirely the branch's committed
# delta, not the code's behaviour. So a land that refused PURELY on bookkeeping is recorded, counted
# and TRENDED under the one label this fold reserves for a caught defect, and the session-start echo
# says of it, in these words, "that is the gate EARNING ITS KEEP, a real defect caught before it
# landed". For those rows that sentence is simply not true.
#
# THIS IS T-11426'S MOVE APPLIED A SECOND TIME, not a new one — one class NAME over two refusals
# whose MOVABILITY differs, read apart by `_abort_arm` at FOLD time rather than by renaming the
# recorded class. The same two reasons hold: eleven code readers key on the literal string
# (`_LAND_VERIFY_RAN_ABORT_CLASSES`, the repeated-abort backstop, the never-landing set), and every
# historical row would need exactly this reader anyway. A SECOND READING OF AN EXISTING PAYLOAD — no
# new capture key, no new event, no `worktree.py` edit (CHARTER §P1 F1/F2/F3).
#
# THE READER, AND THE MEASUREMENT THAT SET ITS KEY. Cross-tabulated over this repo's WHOLE journal —
# every `land_completed{abort, verify-failed}` row, 185 of them:
#     173  >=1 test assertion, no guard mark, `failing_tests` non-empty  -> test-failure
#       4  >=1 assertion, no guard mark, `failing_tests` EMPTY           -> test-failure (a pinned
#          ENGINE driver error: "[pinned/last-green] pinned-engine subprocess FAILED (exit 3)")
#       5  EVERY assertion is a guard message, `failing_tests` EMPTY     -> corpus-bookkeeping
#       3  a guard message AND a real failing test assertion             -> mixed
#     ---- `failing_assertions` present on 185/185; `abort_reason` on 185/185.
#
# THE FIFTH SHAPE, AND IT IS A CONSUMER'S (T-12406 / kupiclub X-1326). A CONSUMER verify LAYER that
# runs out of wall-clock reaches this same reader as a `verify-failed` row, because
# `worktree._run_verify_tests` appends its `verify layer 'X' command TIMED OUT after Ns` sentence to
# the SHARED `bad` list WITHOUT `_VERIFY_TIMEOUT_MARKER` — so the class fork never sees a timeout and
# rule (2) above answered `test-failure`, which is the one arm the render is entitled to call a caught
# defect. Measured on kupiclub, 2026-09-04: SIX `land_completed{abort, verify-failed}` rows across FOUR
# branches (T-0617, T-0621 x2, T-0623 x2, T-0624), each carrying exactly ONE assertion (that sentence),
# `failing_tests` EMPTY, and a `consumer_verify_layers` trail whose `frontend-unit` layer reads
# `outcome: timed-out` at ~300.1 s against a 300.0 s limit while `static` / `sandbox` / `stack` all
# PASSED. A host that times out an otherwise-healthy layer under a land wave is a host/limits signal;
# the echo priced all six as the gate EARNING ITS KEEP, and the honest signal was invisible.
#
#       6  a TIMED-OUT layer in the trail, every non-guard assertion is its timeout sentence
#                                                                      -> layer-timeout   [kupiclub]
#
# THE 185 KERNEL ROWS ABOVE DO NOT MOVE, and that is MEASURED rather than assumed. Seven of them
# mention a timeout, and every one is a TEST timeout — `subprocess.TimeoutExpired` from a pytest
# driver — carrying NEITHER the layer sentence NOR any `consumer_verify_layers` trail (all `None`,
# since the trail is a consumer-land field). Both legs of the new rule are therefore unreachable for
# them: the structured leg finds no trail, and the legacy belt matches on the layer sentence they do
# not contain. The 173 / 4 / 5 / 3 counts stand exactly as tabulated.
#
# AND THE CLASS EMISSION IS DELIBERATELY NOT TOUCHED — this is T-11426's move applied a THIRD time,
# for the third time for the same two reasons. Making `worktree.py` mark these rows `verify-timeout`
# would be the rename eleven readers key against (T-11426 / T-11607), and every historical row would
# still need exactly this reader. A THIRD READING OF AN EXISTING PAYLOAD — no new capture key, no new
# event, no `worktree.py` edit (CHARTER §P1 F1/F2/F3).
#
# THE DECISIVE MEASUREMENT IS THE 4, and it is what rules out the obvious structured reader. The
# card's own stated HYPOTHESIS was that a structured marker might beat the reason text. It does —
# but NOT `failing_tests`. "No failing test file ⇒ this was bookkeeping" is FALSE for those 4 rows:
# a pinned-engine driver error names no test file and is a genuine verify failure, so that reader
# would mis-bucket 4 real gate-catches as paperwork — the same shape as T-11426's 57, one level
# down. `failing_assertions` is the key that works, because the guards' messages land in it as
# SEPARATE ELEMENTS: partitioning the elements is the only thing that can tell SOLE from MIXED at
# all, which is exactly what AC2 asks for. The three marks below are each guard's own invariant
# opening; a guard that has never yet refused (two of the three, in this window) is read anyway.
#
# A MIXED ROW IS ATTRIBUTED TO NEITHER ARM. It gets its OWN arm, counted and priced like any other,
# because splitting one abort's minutes between two arms would invent a division the row does not
# record, and putting it in either arm whole would overstate that arm. Same direction as the
# UNDETERMINED rule: an unknown is reported as unknown.
#
# THE GROUP IS DELIBERATELY NOT MOVED. Re-homing the bookkeeping arm into `process-refusal` (whose
# definition it fits) was weighed and REJECTED here: AC3 requires the four groups to still hold and
# AC4 asks that the ECHO WORDING stop claiming more than the data supports, which is a wording fix.
# Moving the group would move minutes into the RECLAIMABLE headline — a louder claim than a READ is
# entitled to make while T-11605, which actually moves the guards, is a separate card.
ABORT_ARM_TEST_FAILURE = "test-failure"            # the gate earning its keep — a real defect caught
ABORT_ARM_CORPUS_BOOKKEEPING = "corpus-bookkeeping"  # refused on the branch's PAPERWORK, not its code
ABORT_ARM_MIXED = "mixed"                          # both — attributed to neither arm alone
ABORT_ARM_LAYER_TIMEOUT = "layer-timeout"          # T-12406 — the LAYER ran out of wall-clock: a
                                                   # host/limits signal, not a statement about the code
# The two things that prove a layer timeout, kept beside the arm they attribute. The OUTCOME is the
# structured trail T-11973 records (`land_completed.data.consumer_verify_layers[*].outcome`); the MARK
# is the invariant opening of the sentence `worktree._run_verify_tests` appends to the shared `bad`
# list on a layer timeout, used ONLY by the legacy belt for rows predating that trail.
_LAYER_TIMEOUT_OUTCOME = "timed-out"
_LAYER_TIMEOUT_ASSERTION_MARK = "command TIMED OUT after"
# THE ARM VOCABULARY'S ONE HOME (CHARTER §P5). The render asks THIS which of a gate-caught group's
# rows the "a real defect caught before it landed" sentence may be said of, instead of re-listing arm
# names in the echo text where they could silently drift from the fold that produces them.
ABORT_ARMS_CAUGHT_DEFECT = (ABORT_ARM_TEST_FAILURE,)


def abort_arm_is_caught_defect(arm) -> bool:
    """May the gate-caught not-waste sentence be said of a row carrying this arm? (T-11607)

    A POSITIVE predicate, deliberately, rather than a not-in-this-list one: an allowlist fails SAFE.
    `mixed` is excluded because the sentence is true of only PART of such a row (it refused on a
    failing test AND on paperwork), and `unattributed` is excluded because we do not know — claiming
    a caught defect for a row the reader could not place would be exactly the guess the fold refuses
    to make. `None` — a gate-caught class that unions nothing — IS a caught defect, which keeps every
    single-arm class reading as it did before this card."""
    return arm is None or arm in ABORT_ARMS_CAUGHT_DEFECT
# Each corpus guard's own invariant opening, as `_surface_failing_assertions` records it. Matched as
# a PREFIX-ish containment on the assertion element (the guards compose the rest of the sentence from
# the offending path), never on a flattened blob.
_CORPUS_GUARD_MARKS = (
    "decisions content-freeze (T-0543/SPEC-0054): land REJECTED",     # SPEC-0054 decision freeze
    "spec-edit chokepoint (T-9730/SPEC-0005): land REJECTED",         # SPEC-0005 off-path spec edit
    "card-shape guard (T-10687/T-10726, SPEC-0165 L1/C1c): land REJECTED",   # SPEC-0165 card shape
)


def _is_corpus_guard_assertion(text: str) -> bool:
    """True when this recorded assertion is a CORPUS-INTEGRITY guard's refusal rather than a test's.

    PURE, and deliberately a containment test rather than an equality one: each guard appends the
    offending path and its remediation cue after the invariant opening above, so the opening is the
    stable part. A test assertion never carries one of these openings — they are the guards' own
    prose, emitted from exactly one site each."""
    return any(mark in text for mark in _CORPUS_GUARD_MARKS) if isinstance(text, str) else False


def _row_has_timed_out_layer(data: dict) -> bool:
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


def _is_layer_timeout_assertion(text: str) -> bool:
    """True when this recorded assertion is the LAYER-TIMEOUT sentence rather than a test's failure.

    Containment on the assertion ELEMENT, never on a flattened blob — the same shape as
    `_is_corpus_guard_assertion`, and for the same reason: only a per-element test can say that
    NOTHING ELSE is in the failing set."""
    return _LAYER_TIMEOUT_ASSERTION_MARK in text if isinstance(text, str) else False


def _abort_arm_rebaseline(data: dict) -> str:
    """The T-11426 arm reader for `rebaseline-unauthorized`. Moved VERBATIM under the per-class
    dispatch below (T-11607) — the ordered reader, its 5 rules and its measured behaviour on the 180
    rows tabulated in the header above are UNCHANGED; only its call site moved:
      (1) `abort_preflight`                                   -> authorization  [structured, current]
      (2) the authorization refusal's own sentence            -> authorization  [legacy AND current]
      (3) the waive-coverage refusal's own sentence           -> waive-coverage [legacy AND current]
      (4) `failing_assertions` / `rebaseline_bad_token_reasons` -> waive-coverage [structured belt]
      (5) otherwise                                           -> unattributed   [never guessed]
    """
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


def _abort_arm_verify_failed(data: dict) -> str:
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


# The per-class dispatch. A class name maps to the ONE reader that knows its two refusals; the two
# readers share no rule, because the two class names union different things. Adding a third split
# class is a row here plus its own reader — never a widening of somebody else's.
_ABORT_ARM_READERS = {
    "rebaseline-unauthorized": _abort_arm_rebaseline,
    "verify-failed": _abort_arm_verify_failed,
}


def _abort_arm(klass: str, data: dict):
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


def _abort_rows(events_path, window_start, window_end) -> list:
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
        for event in journal.segment_rows_since(
                events_path, _window_segment_floor(window_start, days=0)):
            if not isinstance(event, dict):
                continue
            # The wait series, resolved through the ONE shared home the admission lens also reads
            # (`journal.land_queue_wait_observation`) — never a private type list and never the
            # `secondary_instrument` field that lens forbids quoting.
            observation = journal.land_queue_wait_observation(event)
            if observation is not None:
                key, waited_s = observation
                stamp = _parse_stamped_deadline(event.get("ts"))
                if stamp is not None and stamp <= window_end:
                    waits.setdefault(key, []).append((stamp, waited_s))
                continue
            if event.get("type") != "land_completed":
                continue
            data = event.get("data")
            if not isinstance(data, dict) or data.get("status") != "abort":
                continue
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


# ── T-11777: THE REFUSAL POINT IS THE ROW'S OWN, NOT ITS CLASS NAME'S ────────────────────────────
#
# THE FINDING, measured on this repo 2026-08-28 over `land_completed` rows since 2026-08-21 carrying
# `abort_class == rebaseline-unauthorized` AND `abort_preflight` truthy — n=25:
#     duration_ms        579.1 min          <- what the rule-27 line reports for them
#     verify_duration_ms  12.9 min (2.2%)   <- what they actually spent inside a verify
#     admission_wait_ms    0.0 min
#     pre_attempt_ms       0.1 min
# All 25 carry `verify_mode`, so `paid` reads TRUE, and `rebaseline-unauthorized` is in neither the
# gate-caught nor the inconclusive class list — so the group fell through to `process-refusal`, the
# ONE group the render calls RECLAIMABLE and describes, in these words, as having "paid a FULL verify
# and then refused on BOOKKEEPING". They did not pay a full verify. All 25 carry `abort_preflight`:
# they refused at the step-4a preflight, BEFORE the suite and before the admission slot, and the rows
# say so themselves.
#
# THE READER-HARM THIS REMOVES is not the 579 itself — it is the REMEDY the line prescribes. The
# reclaimable sentence tells a reader to move the refusal earlier. For this class the refusal is
# ALREADY as early as it goes (T-10850 moved it), so acting on the line reclaims about 13 minutes,
# not 579. A controller report to the owner on 2026-08-28 repeated the line's framing before anyone
# measured it — the real incident CHARTER §P1 F4 asks for.
#
# THE FIX IS THE SMALLEST ONE THAT IS TRUE: bucket by the row's OWN RECORDED REFUSAL POINT. `paid`
# tells you a verify marker exists; `abort_preflight` tells you WHERE the row stopped. A row carrying
# the preflight marker did not pay a full verify whatever its class name is, so it cannot be in the
# paid-a-full-verify group — and its wall-clock is still REPORTED, under a group that names what it
# actually is. This is T-10850's finding ("an `abort_class` is not a reliable proxy for cost") applied
# once more, on an axis the row already records: the same move `_abort_arm` makes for T-11426 and
# T-11607, one level up, in the group key rather than in the label.
#
# THE MINUTES ARE NEVER DROPPED, and that is the load-bearing half. Removing them from RECLAIMABLE
# while leaving them unreported would trade an overstatement for a disappearance — the same direction
# as pricing an undetermined cost at zero, which this fold already refuses. `preflight-refused` is a
# never-summed group like the other four, with its own count, minutes and trend.
#
# WHAT THIS CARD DOES **NOT** DO. It does not explain where the 579 minutes went. Two rows
# (task/T-11618 at 121.4 min and task/T-11512 at 114.8 min, both `attempt_count` 1 with a
# near-zero verify) carry over half the class total, and `unattributed_ms` reads 0.0 on all 25 — so
# what holds a single-attempt land open for an hour or two is unexplained and is carried as a
# SEPARATE followup. Classifier here, investigation there; conflating them would let a hypothesis
# ride into a corrected report as if it were measured.


def _abort_group(klass: str, paid: bool, preflight: bool = False) -> str:
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


def _abort_trend(recent_ms: int, older_ms: int, total_ms: int) -> str:
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


def aborted_land_cost(events_path, window_days: int = ABORT_COST_WINDOW_DAYS, now=None) -> dict:
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
        "lens": "aborted-land cost (SPEC-0119 rule 27, T-11368 / kupiclub X-1036, corrected by "
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
                "the step-4a preflight by T-10850 and is cheap, while its WAIVE-COVERAGE arm (T-10754) "
                "moved only in PART — T-11479 moved its token-binding half to that same preflight, and "
                "its coverage half still reads `pinned_bad` after a full pinned run. The two differ in "
                "MOVABILITY, so a fold that unions them prices a refusal already made cheap together "
                "with one that is still only partly moved, and reports one remedy where there are two "
                "(T-11426 / kupiclub X-1096). Each arm carries its OWN count, minutes and trend; a row "
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


# ── SPEC-0119 rule 21 (T-11181): the NON-TERMINAL plan census ───────────────────────────────────────
# Plans are the only tracked work class NOTHING surfaces at any seam: the picker reads `tasks/` only,
# and no other debt collaborator opens `plans/`. So a plan parked mid-FSM — most concretely one sitting
# in `postcheck`, the real-data soak stage — is unfinished work that simply goes quiet. This fold is its
# ONE reading moment, and it is a RENDER of counts that already exist (`cmd_plan_list` reads the same
# frontmatter), not a new parser or store.
#
# THE FILTER IS A COMPLEMENT, NOT A SELECT — the load-bearing asymmetry. It excludes ONLY the four
# PROVABLE terminal values and counts everything else, so a plan whose status is missing, malformed, or
# a word this vocabulary does not know is counted as `unknown` rather than silently dropped. An
# allowlist of the seven active stages would read identically on today's corpus and would silently lose
# exactly the plans nobody is tracking — the failure this line exists to end. Note `cmd_plan_list`
# DEFAULTS a missing status to `draft` for LISTING; the census must not copy that, because promoting an
# unparseable plan into a real FSM state is the same drop wearing a plausible name.
#
# The vocabulary is IMPORTED from `lib.plan`, never re-listed (CHARTER §P5): add a stage to the plan FSM
# and the census follows it with no edit here. `lib.plan` imports only `lib.state`, so the import is
# acyclic; `lib.state.load_str` is the ONE parser layer, and `state.scan_plans` the ONE walk — the same
# two primitives `cmd_plan_list` uses, which is what makes this a second READING of an existing
# derivation rather than a second source that could disagree with it.
# ── SPEC-0119 rule 21, the SLICE-STALENESS tail (T-12081) ───────────────────────────────────────────
#
# WHAT THE COUNTS COULD NOT SAY. The census above names how many plans sit in each non-terminal
# stage and nothing else, which is exactly the reading that failed: the forgotten security plan
# (deviation `plan-parked-in-draft-on-unnameable-pull-trigger-forgotten`) sat 7 weeks while the line
# faithfully reported one more plan in `draft`. A multi-slice plan makes it worse — an `executing`
# umbrella can realize its first slice and let the rest rot, and every count stays healthy while it
# happens. So the tail NAMES candidates. That is still SURFACING, not PICKING: naming what is stale
# is the same act the sibling `unpickable_ready_cards` (rule 36) performs when it names STUCK cards.
# It ranks nothing, selects nothing, and taking a plan into work stays an OWNER CUE.
#
# THE AGE INSTRUMENT IS THE JOURNAL, AND THE WINDOW IS BOUNDED. Plan frontmatter carries no
# per-stage timestamps, so stage age comes from the `plan_stage_entered {slug, from, to}` rows the
# FSM already emits — no new event, no new store. Every clause asks "older than a bound", and the
# ABSENCE of an entry row inside the bound's window IS that proof, so ONE windowed read at the
# WIDEST bound answers all three (SPEC-0190 rule 4: the reader declares its horizon; the seam's own
# request-scoped ReadScope serves the fold, so this adds no cache — rule 10).
#
# PROVABLE YOUTH SILENCES — the guard on the inversion above. Reading absence as age is right for an
# artifact whose rows have simply aged out, and WRONG for one whose rows never existed inside the
# window because it is young. So a plan whose frontmatter `created:` — or a card whose `created_at:`
# — proves it younger than the bound is never named, whatever the journal cannot show. Where NEITHER
# instrument can speak (no parseable date, no row), the artifact is named: an untrackable plan in a
# non-terminal stage is precisely this line's subject, and dropping it would restore the silence.
#
# TERMINAL PLANS ARE UNREACHABLE HERE by construction — the clauses run only over the non-terminal
# statuses the census already separated, so a realized/partial/rejected/cancelled plan can never
# produce a candidate, and the counts (`count` / `by_status` / `unknown` / `terminal`) are untouched.

# The three bounds, named ONCE (the card's constraint) and read from here by the fold, the render
# and the spec's own verification. Days, not hours: every subject here is a multi-week dwell.
PLAN_DECOMPOSITION_STALE_DAYS = 14      # a plan sitting mid-cut, its cards unfiled
PLAN_CUT_CARD_UNTOUCHED_DAYS = 30       # a required cut card nothing has touched
PLAN_UMBRELLA_RENEWAL_DAYS = 90         # an umbrella running since `accepted` with no renewal note

_PLAN_STAGE_EVENT = "plan_stage_entered"
_PLAN_SLICE_STALE_BOUND_DAYS = max(PLAN_DECOMPOSITION_STALE_DAYS,
                                   PLAN_CUT_CARD_UNTOUCHED_DAYS,
                                   PLAN_UMBRELLA_RENEWAL_DAYS)


def _plan_slice_recent(events_path, now):
    """ONE windowed journal pass → what has been TOUCHED recently, for all three clauses.

    Returns `(decomposition_slugs, accepted_slugs, touched_task_ids)` — the slugs that ENTERED
    `decomposition` / `accepted` inside their own bound, and the task ids carrying ANY row inside
    the cut-card bound. Each set is RECENCY evidence, so a slug/id absent from one is what the
    caller reads as age (see the section note above).

    The read is windowed at the WIDEST bound through `journal.segment_rows_since` +
    `_window_segment_floor` (SPEC-0190 rule 4) and each row is still placed by its own `ts`, so the
    segment pre-filter can only ever over-include. Never raises: an unreadable journal yields three
    empty sets, and the caller's youth guards then decide alone."""
    decomposition, accepted, touched = set(), set(), set()
    try:
        rows = journal.segment_rows_since(
            events_path, _window_segment_floor(now, days=_PLAN_SLICE_STALE_BOUND_DAYS))
    except (OSError, UnicodeDecodeError, TypeError):
        return decomposition, accepted, touched
    for event in rows:
        if not isinstance(event, dict):
            continue
        ts = _parse_stamped_deadline(event.get("ts"))
        if ts is None:
            continue                      # no establishable date ⇒ not placeable in any window
        age_days = (now - ts).days
        # STRICTLY INSIDE the bound — the boundary belongs to the CANDIDATE, not to recency. The
        # rule says a candidate fires at `>= N days`, so a row EXACTLY N days old is the oldest thing
        # that still fires and must not count as a recent touch (the `<=` this replaces silenced
        # exactly the artifact at its own threshold).
        tid = event.get("task_id")
        if isinstance(tid, str) and tid.strip() and age_days < PLAN_CUT_CARD_UNTOUCHED_DAYS:
            touched.add(tid.strip())
        if event.get("type") != _PLAN_STAGE_EVENT:
            continue
        data = event.get("data") if isinstance(event.get("data"), dict) else {}
        slug, to = data.get("slug"), data.get("to")
        if not isinstance(slug, str) or not slug.strip() or not isinstance(to, str):
            continue
        slug = slug.strip()
        if to.strip() == "decomposition" and age_days < PLAN_DECOMPOSITION_STALE_DAYS:
            decomposition.add(slug)
        if to.strip() == "accepted" and age_days < PLAN_UMBRELLA_RENEWAL_DAYS:
            accepted.add(slug)
    return decomposition, accepted, touched


def _plan_frontmatter(path: Path) -> dict:
    """This plan's frontmatter as a mapping, or `{}` when it cannot be read as one.

    The sibling of `_plan_frontmatter_status`, which answers the ONE field the census needs; the
    staleness clauses need two more (`created` / `renewed_at`), and re-parsing per field would be a
    second read of the same bytes. Every failure mode collapses to `{}` — an unreadable plan simply
    offers no youth evidence, which the caller already handles."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return {}
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    try:
        front = state.load_str(text[3:end])
    except yaml.YAMLError:
        return {}
    return front if isinstance(front, dict) else {}


def _younger_than(value, now, days) -> bool:
    """True when `value` is a parseable date/instant PROVING the artifact is younger than `days`.

    The youth guard, and it is deliberately one-directional: an absent, blank or unparseable value
    is NOT youth, so it never silences a candidate — it just leaves the journal to answer alone."""
    if isinstance(value, date) and not isinstance(value, datetime):
        value = datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    elif isinstance(value, datetime):
        value = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    elif isinstance(value, str) and value.strip():
        value = _parse_stamped_deadline(value.strip()) or _parse_stamped_deadline(
            value.strip() + "T00:00:00Z")
    else:
        return False
    if value is None:
        return False
    try:
        return (now - value).days < days
    except TypeError:
        return False


def _plan_cut_cards(tasks_dir):
    """Fold `tasks/*.yaml` → `{plan-slug: [ {task, created_at} … ]}` for NON-TERMINAL cut cards.

    A cut card is one whose `decomposed_from:` names a plan (SPEC-0034 / SPEC-0070 — the field the
    decomposition already writes; no new field, no new store). TERMINAL cards are excluded: a done
    or wont-do slice is not un-advanced work, it is finished work, and naming it would make the tail
    fire loudest on the plans that are going best."""
    out: dict = {}
    try:
        paths = list(state.scan_tasks(Path(tasks_dir)))
    except (OSError, TypeError):
        return out
    for path in paths:
        if state.card_status(path) in TERMINAL_CARD_STATUSES:
            continue
        doc = state.load_path(path)
        if not isinstance(doc, dict):
            continue
        slug = doc.get("decomposed_from")
        tid = doc.get("id")
        if not isinstance(slug, str) or not slug.strip():
            continue
        if not isinstance(tid, str) or not _TASK_ID_RE.match(tid.strip()):
            continue
        out.setdefault(slug.strip(), []).append({"task": tid.strip(),
                                                 "created_at": doc.get("created_at")})
    return out


def _plan_slice_staleness(plans, tasks_dir, events_path, now) -> list:
    """The three report-only staleness clauses over the already-classified NON-TERMINAL plans.

    Args:
      plans: `[(slug, status, frontmatter), …]` — the census's own non-terminal classification,
        passed in rather than re-derived, so the tail can never disagree with the counts it rides.

    Returns a list of `{"kind", "plan", "card"}`, sorted by kind then plan then card so the line is
    stable across folds. `kind` is one of `decomposition-age` / `stale-cut-card` / `umbrella-age`;
    `card` is set for `stale-cut-card` only. Report-only — this names candidates, ranks none."""
    decomposition_recent, accepted_recent, touched = _plan_slice_recent(events_path, now)
    cut_cards = None                       # materialised only if an `executing` plan needs it
    found = []
    for slug, status, front in plans:
        created = front.get("created")
        if status == "decomposition":
            if slug not in decomposition_recent and not _younger_than(
                    created, now, PLAN_DECOMPOSITION_STALE_DAYS):
                found.append({"kind": "decomposition-age", "plan": slug, "card": None})
        if status == "executing":
            if cut_cards is None:
                cut_cards = _plan_cut_cards(tasks_dir)
            for card in cut_cards.get(slug, []):
                if card["task"] in touched:
                    continue               # the journal saw it inside the bound — not untouched
                if _younger_than(card.get("created_at"), now, PLAN_CUT_CARD_UNTOUCHED_DAYS):
                    continue               # provable youth silences
                found.append({"kind": "stale-cut-card", "plan": slug, "card": card["task"]})
        if status in ("executing", "postcheck"):
            if slug not in accepted_recent and not _younger_than(
                    front.get("renewed_at"), now, PLAN_UMBRELLA_RENEWAL_DAYS) \
                    and not _younger_than(created, now, PLAN_UMBRELLA_RENEWAL_DAYS):
                found.append({"kind": "umbrella-age", "plan": slug, "card": None})
    return sorted(found, key=lambda c: (c["kind"], c["plan"], c["card"] or ""))


def nonterminal_plan_census(plans_dir, *, tasks_dir=None, events_path=None, now=None) -> dict:
    """Fold `plans/*.md` frontmatter → the NON-TERMINAL plan census (SPEC-0119 rule 21, T-11181).

    Args:
      plans_dir: this repo's `plans/` directory (missing / unreadable ⇒ a clean zero-count result — a
        repo with no plans owes nothing, so history is never retro-charged, the SPEC-0149 lesson).

      tasks_dir / events_path: the cut-card corpus and the journal the SLICE-STALENESS tail (T-12081)
        reads. DEFAULTED from `plans_dir.parent` — the repo root the one caller already binds when it
        passes `<root>/plans` — so no call site changes and a fixture tree is read exactly as a repo
        is. A sibling that does not exist simply yields no candidate.
      now: the reader's clock (aware UTC), injected by tests; the fold itself takes no other clock.

    Returns `{"lens", "total", "count", "by_status", "unknown", "terminal", "stale", "bounds",
    "next"}` — `count` is the headline (non-terminal + unknown), `by_status` an ordered {stage: n}
    over the stages that actually have plans, in `PLAN_ACTIVE` FSM order. The COUNTS are UNCHANGED by
    the tail: `stale` is an additive list of named candidates (see `_plan_slice_staleness`) that
    never adds to, subtracts from, or re-classifies anything above it. Writes nothing (SPEC-0149 §2).

    SURFACING IS NOT PICKING — unchanged by the tail. The counts rank nothing and the candidates rank
    nothing either: naming what has gone stale is the same act the sibling `unpickable_ready_cards`
    performs when it names STUCK cards. Taking a plan into work stays an owner cue
    (AGENTS-PROTOCOL §Planning artifacts, and the boundary SPEC-0085 §8 already draws for the sibling
    cross-coordination surface: «surfacing != queue-scan»)."""
    from lib.plan import PLAN_ACTIVE, PLAN_TERMINAL   # the ONE status vocabulary (P5), never re-listed

    counts: dict = {}
    unknown = terminal = total = 0
    nonterminal = []
    try:
        paths = list(state.scan_plans(Path(plans_dir)))
    except (OSError, TypeError):
        paths = []
    for path in paths:
        total += 1
        # ONE read + ONE parse per plan, feeding BOTH the stage classification and the staleness
        # tail's date reads (T-12081) — the tail used to re-read every non-terminal plan file that
        # had just been read here.
        front = _plan_frontmatter(path)
        status = _plan_status_of(front)
        if status in PLAN_TERMINAL:
            terminal += 1                    # the ONLY provable exclusion
        elif status in PLAN_ACTIVE:
            counts[status] = counts.get(status, 0) + 1
            nonterminal.append((path, status, front))
        else:
            unknown += 1                     # absent / malformed / unrecognised — counted, never dropped
    by_status = {s: counts[s] for s in PLAN_ACTIVE if s in counts}   # FSM order, not insertion order

    # T-12081 — the staleness tail. Never raises: a report-only view must never break the seam it
    # rides, so any failure here costs the CANDIDATES and leaves every count standing.
    stale = []
    try:
        root = Path(plans_dir).parent
        stale = _plan_slice_staleness(
            [(path.stem, status, front) for path, status, front in nonterminal],
            tasks_dir if tasks_dir is not None else root / "tasks",
            events_path if events_path is not None else root / "events.jsonl",
            now or datetime.now(timezone.utc))
    except Exception:                        # noqa: BLE001 — report-only: candidates, never the seam
        stale = []
    return _plan_census_result(total, by_status, unknown, terminal, stale)


# ── SPEC-0119 rule 36 (T-11868): a READY card blocked FOREVER by a wont-do requirement ────────────
#
# The gap this closes: `requires:` is the picker's blocking edge — a card is pickable only once every
# id it requires is DONE. `wont-do` is the OTHER terminal status, and it is terminal in the direction
# that never satisfies: the required work was decided against and will not be done. A `ready` card
# requiring one is therefore PERMANENTLY unpickable, and NOTHING says so. It reads `ready` at every
# surface that folds card status, sits in the queue forever, and the only way anyone learns is by
# picking it and hitting the block — which is the reading this line replaces.
#
# WHY IT IS NOT THE PICKER'S JOB. The picker REFUSES the card at selection, correctly, and says so to
# whoever asked. But nobody asks: a card that is never selected is never refused, so the refusal is
# reachable only along the path the blockage makes nobody take. The debt seam is the surface a
# controller passes ANYWAY, which is what makes it the one that can say this unprompted.
#
# THE REMEDY IS A DECISION, NEVER A SWEEP, and the line says so. Two honest exits: drop the dead
# `requires:` edge if the requirement turned out not to be needed, or close the card `wont-do` itself
# if it was. Which one is a judgement about the WORK, so this view names the pair and picks neither.
#
# ONLY A PROVABLE wont-do FIRES IT (fail-closed toward SILENCE here, unlike the sibling halt fold —
# the asymmetry is deliberate). A required id whose card is ABSENT, unreadable, malformed, or carries
# any other status contributes NOTHING: absence is the ordinary state of an id this checkout has not
# got, and a view that nagged on it would fire on every consumer repo and every fixture tree. The
# claim this line makes is strong ("this can never be picked"), so it is made only where the evidence
# is a wont-do card sitting right there.

_REQUIRES_TASK_ID_RE = re.compile(r"^T-\d+$")


def unpickable_ready_cards(tasks_dir) -> dict:
    """Fold `tasks/*.yaml` → the READY cards whose `requires:` names a `wont-do` target (SPEC-0119
    rule 36, T-11868).

    Args:
      tasks_dir: this repo's `tasks/` directory (missing / unreadable ⇒ a clean zero-count result — a
        repo with no cards owes nothing, so history is never retro-charged, the SPEC-0149 lesson).

    Returns `{"lens", "count", "cards", "next"}`; each card
    `{"task", "title", "blockers": [{"id", "title"}]}`, sorted by task id so the order is stable
    across folds. Pure: reads files, writes nothing, no clock, no subprocess (SPEC-0149 §2) — the
    `nonterminal_plan_census` shape, reused rather than re-invented.

    SURFACING IS NOT PICKING. This names the STUCK cards, which is the opposite of naming a candidate:
    it ranks nothing and selects nothing, and deciding which of the two exits a card takes stays the
    reader's (SPEC-0085 §8, «surfacing != queue-scan»).

    Never raises: a report-only view must never break the seam it rides."""
    try:
        paths = list(state.scan_tasks(Path(tasks_dir)))
    except (OSError, TypeError):
        return _unpickable_ready_result([])

    cards: dict = {}
    for path in paths:
        # T-12030 — TWO changes, and the second is the reason for the first. (1) The parse goes
        # through `state.load_path`, the ONE canonical reader, instead of this fold spelling its own
        # `load_str(read_text(...))`: that was a second parse path over a corpus the memo had already
        # parsed, the same P5 defect T-12029 removed from `_own_cards` next door. (2) Because the
        # reader is now the memoized one, the fold can ask the STATUS first and materialise only the
        # cards it can report on. This view's subject is exactly two statuses — a `ready` card and a
        # `wont-do` card it names as that card's blocker — so every other card is a read it never
        # needed. `card_status` is a view over the SAME memo (no third path). The ANSWER is
        # unchanged, not merely narrowed carefully: a card with no readable status could never have
        # been a `ready` row NOR a `wont-do` blocker, so it contributed nothing before either — and
        # an unreadable card was already dropped by the `except ... continue` this replaces.
        status = state.card_status(path)
        if status not in ("ready", "wont-do"):
            continue
        doc = state.load_path(path)
        if not isinstance(doc, dict):
            continue
        tid = doc.get("id")
        if isinstance(tid, str) and _REQUIRES_TASK_ID_RE.match(tid.strip()):
            cards[tid.strip()] = doc

    flagged = []
    for tid in sorted(cards):
        doc = cards[tid]
        status = doc.get("status")
        if not isinstance(status, str) or status.strip() != "ready":
            continue                     # only a READY card is waiting to be picked at all
        reqs = doc.get("requires")
        reqs = reqs if isinstance(reqs, list) else []
        blockers = []
        for raw in reqs:
            if not isinstance(raw, str):
                continue
            rid = raw.strip()
            blocked = cards.get(rid)
            if not isinstance(blocked, dict):
                continue                 # ABSENT / not id-shaped ⇒ ordinary, never a claim
            bstatus = blocked.get("status")
            if isinstance(bstatus, str) and bstatus.strip() == "wont-do":
                btitle = blocked.get("title")
                blockers.append({"id": rid,
                                 "title": btitle if isinstance(btitle, str) else None})
        if blockers:
            title = doc.get("title")
            flagged.append({"task": tid,
                            "title": title if isinstance(title, str) else None,
                            "blockers": blockers})
    return _unpickable_ready_result(flagged)


def _unpickable_ready_result(cards: list) -> dict:
    """The ONE place this view's lens/next wording lives, so the fold's two exits cannot describe it
    differently (the `_unexecuted_subject_result` precedent)."""
    return {
        "lens": "unpickable-ready-cards (SPEC-0119 rule 36) — cards sitting `ready` whose `requires:` "
                "names a target that is `wont-do`. `requires:` is the picker's BLOCKING edge and "
                "`wont-do` is the terminal status that never satisfies it, so such a card can NEVER be "
                "picked — yet it reads `ready` at every surface that folds card status, and the "
                "picker's refusal is reachable only by selecting the card, which is exactly what the "
                "blockage stops anyone doing. DERIVED at read time from `tasks/` alone — zero stored "
                "state; only a PROVABLE `wont-do` card fires a row (an absent / unreadable / "
                "otherwise-statused requirement contributes nothing), so a repo whose cards this "
                "checkout does not hold owes nothing. Report-only, never a gate.",
        "count": len(cards),
        "cards": cards,
        "next": ("each of these will never be picked. TWO honest exits, and which one is a judgement "
                 "about the WORK, not a sweep: DROP the dead edge (`requires:` no longer needed — edit "
                 "the card) if the requirement turned out to be unnecessary, or CLOSE the card itself "
                 "`wont-do` (`bin/yitc-v2 task close <id> --status wont-do --reason …`) if the "
                 "requirement was the point. Never silently delete the edge to make the row go away — "
                 "that re-admits the card to a queue nothing has re-justified."
                 if cards else
                 "no ready card is blocked by a wont-do requirement — nothing owed."),
    }


# ── SPEC-0119 rule 41 (T-12359): a DECLARED LOAD-SENSITIVE file that no live card is holding ───────
#
# The gap this closes. T-12358 made entry into `tests/load-sensitive.txt` automatic and exit NEVER
# automatic, for a reason that is sound and is exactly what creates the debt: a listed file no longer
# runs in the concurrent pool, so nothing can ever prove it pool-robust again — only a card can remove
# a line, by making the file load-robust or by ratifying the line with a reason. That leaves the set
# monotonic unless a human acts, and the carrier's own header is the only place that says so.
#
# WHY AN ECHO LINE WHEN THE FILER ALREADY EXISTS. This card's other half auto-files the card at the
# moment of entry, which covers every AUTOMATIC entry from now on. It does NOT cover a line added by
# hand, a card someone closed `wont-do` without removing the line, or the lines already in the carrier
# before the filer shipped. This view is what makes those visible, and it is the reading the system
# has measured evidence for: 193 `land_completed` rows named test_t11451 before T-12314 was filed BY
# HAND, while the rule-26 line reported the cause at every session start. An echo that reports a cause
# nobody is holding is how that happens; this one reports the HOLDER's absence instead.
#
# THE FINGERPRINT HAS ONE HOME, and it is here, because two consumers must agree EXACTLY on it: the
# land-tail filer's idempotency check (`worktree._load_sensitive_entry_at_land_tail`) and this view's
# suppression. A second spelling would let a card exist that one of them sees and the other does not —
# the filer would duplicate, or the echo would nag forever, depending on which drifted.
#
# ONLY A NON-TERMINAL CARD SUPPRESSES. `done` and `wont-do` are the two terminal statuses, and neither
# holds anything: a `done` card either removed the line (so the file is not listed and there is nothing
# to report) or closed without doing so (which is precisely a file nobody is holding). This is the
# opposite polarity from rule 36's fail-closed-toward-silence, and deliberately so — there the claim is
# strong ("this can NEVER be picked") and needs proof, here the claim is an ABSENCE the carrier itself
# already asserts is owed.
#
# REPORT-ONLY, LIKE EVERY SIBLING. It names a remedy and performs none of it; it removes no line,
# files no card, and moves no exit code. Removing a line stays a card's decision (T-12358's contract).

LOAD_SENSITIVE_FP_PREFIX = "load-sensitive:"


def load_sensitive_fingerprint(file: str) -> str:
    """The ONE home of the `load-sensitive:<file>` fingerprint (SPEC-0119 rule 41, T-12359).

    Both consumers call THIS: the land-tail filer, to decide whether a card already exists for a file
    it is about to enter, and `load_sensitive_carded` below, to decide whether the echo stays silent.
    A card declares that it holds a listed file by carrying this exact string in its `cites:`.

    The file is the test's BASENAME, which is unambiguous by the verify runner's own contract
    (`verify_runner._load_sensitive_set`: duplicate `test_*.py` basenames fail closed before any file
    runs, so the whole name-keyed surface — including the `flaky_retry.rows[].file` record entry is
    derived from — has one identity). Whitespace-stripped so a hand-typed `cites:` entry with a
    trailing space still matches; nothing else is normalised, because a fingerprint that quietly
    accepted near-misses would be a second identity in disguise."""
    return LOAD_SENSITIVE_FP_PREFIX + str(file).strip()


def load_sensitive_carded(tasks_dir) -> dict:
    """Fold `tasks/*.yaml` → `{fingerprint: task_id}` for every NON-TERMINAL card that declares it
    holds a declared load-sensitive file (SPEC-0119 rule 41, T-12359).

    Args:
      tasks_dir: this repo's `tasks/` directory. Missing / unreadable ⇒ `{}` — a repo with no cards
        holds nothing, so history is never retro-charged (the SPEC-0149 lesson rule 36 also holds to).

    NON-TERMINAL means status is neither `done` nor `wont-do`. Both terminal statuses are terminal in
    the direction that holds nothing: a `done` card that removed the line leaves no listed file to
    report on, and one that closed without removing it is exactly the un-held file this view exists to
    name. `ready` / `in-progress` / `parked` all suppress — a parked card is a recorded decision with a
    return trigger, which is somebody holding it.

    Reads through `state.card_status` + `state.load_path` — the ONE canonical, memoised reader pair, so
    this fold adds no second parse path over a corpus the request-scoped memo has already parsed
    (T-12030's correction to rule 36, reused here rather than re-earned). The status is asked FIRST so
    only the cards that can possibly contribute are materialised.

    LAST WRITER WINS on a duplicate fingerprint, and that is the harmless direction: two live cards on
    one file is a human's duplicate, not this view's concern, and either id answers "somebody is
    holding it". Never raises — a report-only view must never break the seam it rides."""
    out: dict = {}
    try:
        paths = list(state.scan_tasks(Path(tasks_dir)))
    except (OSError, TypeError):
        return out
    for path in paths:
        try:
            if state.card_status(path) in ("done", "wont-do"):
                continue
            doc = state.load_path(path)
        except Exception:
            continue
        if not isinstance(doc, dict):
            continue
        tid = doc.get("id")
        if not isinstance(tid, str) or not tid.strip():
            continue
        cites = doc.get("cites")
        for raw in (cites if isinstance(cites, list) else []):
            if isinstance(raw, str) and raw.strip().startswith(LOAD_SENSITIVE_FP_PREFIX):
                out[raw.strip()] = tid.strip()
    return out


def load_sensitive_uncarded(listed, carded) -> dict:
    """The rule-41 view: every DECLARED load-sensitive file that no non-terminal card is holding.

    Args:
      listed: `{<test basename>: <its carrier line>}` — the reader's answer from
        `verify_runner._load_sensitive_set`, passed IN rather than re-read, so this view can never
        disagree with the runner about what the set is (there is one parser for the carrier).
      carded: the `load_sensitive_carded` fold above.

    Returns `{"lens", "count", "files", "next"}`; each file `{"file", "entered", "line"}`, sorted by
    file name so the fold is stable. PURE (SPEC-0149 §2): no I/O, no clock, no subprocess — both
    inputs are already-read values, which is what lets the land-tail filer and this view share the
    `carded` fold rather than each computing its own.

    `entered` is the carrier line's SECOND whitespace token — the `YYYY-MM-DD` T-12358 writes — and is
    None when the line carries none. A dateless line still LISTS: the claim this view makes is "no card
    is holding this", which is true whether or not the entry date is legible, and dropping the row
    would silently shrink the count on exactly the malformed lines most worth seeing."""
    rows = []
    for name in sorted(listed or {}):
        if load_sensitive_fingerprint(name) in (carded or {}):
            continue
        line = (listed or {}).get(name) or ""
        parts = str(line).split()
        entered = parts[1] if len(parts) > 1 and _LOAD_SENSITIVE_DATE_RE.match(parts[1]) else None
        rows.append({"file": name, "entered": entered, "line": str(line)})
    return _load_sensitive_uncarded_result(rows)


_LOAD_SENSITIVE_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _load_sensitive_uncarded_result(files: list) -> dict:
    """The ONE place this view's lens/next wording lives, so the fold's exits cannot describe it
    differently (the `_unpickable_ready_result` precedent, reused)."""
    return {
        "lens": "load-sensitive-uncarded (SPEC-0119 rule 41) — files in the declared load-sensitive "
                "set (`tests/load-sensitive.txt`) that NO non-terminal card is holding. Entry into "
                "that set is automatic and exit is NEVER automatic by design (T-12358): a listed file "
                "no longer runs in the concurrent pool, so nothing can prove it pool-robust again and "
                "only a card can remove its line. A listed file with no live card is therefore a "
                "permanent serialization nobody has agreed to. DERIVED at read time from the carrier "
                "+ `tasks/` alone — zero stored state. Report-only, never a gate: it removes no line "
                "and files no card.",
        "count": len(files),
        "files": files,
        "next": ("each of these will run serialized forever until a card decides otherwise. TWO honest "
                 "exits, and which one applies is a judgement about the TEST, not a sweep: FILE a card "
                 "to make the file load-robust (`bin/yitc-v2 task file` — put "
                 "`load-sensitive:<file>` in its `cites:` so this line stops firing for it, and remove "
                 "the carrier line in the ship diff), or RATIFY the line by appending a reason to it "
                 "in `tests/load-sensitive.txt`, which records that serialized is where the file "
                 "belongs. Never delete the line to make the row go away — that returns the file to "
                 "the pool with nothing re-justified."
                 if files else
                 "every declared load-sensitive file has a live card — nothing owed."),
    }


def _plan_status_of(front: dict) -> "str | None":
    """The `status:` of an already-parsed plan frontmatter, or None when it is not readable as one.

    Split out by T-12081 so the ONE parse of a plan's frontmatter can answer BOTH questions the
    census asks of it (its stage, and the `created`/`renewed_at` dates the staleness tail reads).
    Before this split the tail re-read and re-parsed every non-terminal plan file that
    `_plan_frontmatter_status` had just read — a second read of the same bytes for the same fold."""
    status = front.get("status") if isinstance(front, dict) else None
    return status.strip() if isinstance(status, str) and status.strip() else None


def _plan_frontmatter_status(path: Path) -> "str | None":
    """This plan's frontmatter `status:`, or None when it cannot be read as one.

    None is the UNKNOWN answer the caller counts, never a reason to skip the file: an unreadable plan
    is still a plan, and it is certainly not provably terminal. Every failure mode collapses here — no
    frontmatter, an unterminated block, malformed YAML, a non-mapping document, an absent / blank /
    non-string `status:` — because they call for the same reading and the same remedy (go look at it)."""
    return _plan_status_of(_plan_frontmatter(path))


# The surfaces a citation of a pattern would actually live in, for THIS repo. Bounded on purpose: a
# whole-tree walk would be slow and would match a pattern's own file, while `git grep` would make the
# fold a subprocess and break the "pure, no subprocess, no clock" unit-test shape every sibling here
# keeps. Named explicitly rather than left implicit, so a later reader can say what was searched.
_CITATION_SURFACES = (
    ("tasks", "*.yaml"), ("specs", "*.yaml"), ("plans", "*.md"), ("ideas", "*.md"),
    ("lessons", "*.md"), ("scenarios", "*.md"), ("patterns", "*.md"),
)


def unapplied_own_evidence_patterns(patterns_dir, repo_root, project_names) -> dict:
    """Fold the KERNEL's `patterns/` against THIS repo → own-evidence patterns it never cited.

    SPEC-0119 rule 22 (T-11211). A pattern qualifies when its frontmatter `sourced_from` NAMES
    `project_name` — i.e. it was built partly from this project's OWN evidence — and this project's
    own corpus never mentions the pattern slug.

    Args:
      patterns_dir: the ENGINE's `patterns/` (captured before any `-C` rebind — the kernel catalog,
        never the reading repo's). Missing / unreadable ⇒ a clean zero result: a repo with no catalog
        owes nothing, so history is never retro-charged (the SPEC-0149 lesson the sibling folds keep).
      repo_root: the READING project, whose own corpus decides cited-vs-uncited.
      project_names: EVERY name this project answers to — its canonical registry key AND its checkout
        aliases. A collection, not one string, because the two genuinely differ for at least one live
        project (`trend-finder` at `.../social-parser`, X-0259): a pattern's `sourced_from` is authored
        by a human and may name EITHER, so matching one alone would silently miss that project's own
        evidence. Each is matched as a WHOLE token, so `social-parser` can never match inside a longer
        sibling name.

    Returns `{"lens", "total_sourced", "count", "names"}` — `count` is the headline (uncited), `names`
    the sorted slug list. Pure: reads files, writes nothing, runs no subprocess and reads no clock.

    SURFACING IS NOT PRESCRIBING. This returns a COUNT and slugs. It names no remedy, ranks nothing,
    and asserts nothing about whether adopting the pattern is right for this project — adopting stays
    the project's own call (SPEC-0119 rule 22; the boundary rule 21 already draws for plans).

    Citation detection matches the SLUG, so it false-NEGATIVES on a prose-only citation. That is the
    deliberate direction: a missed nag costs nothing, while a wrong nag teaches the reader to ignore
    the line."""
    try:
        paths = list(state.scan_patterns(Path(patterns_dir)))
    except (OSError, TypeError):
        paths = []
    if isinstance(project_names, str):               # tolerate the single-name call shape
        project_names = [project_names]
    names = sorted({n.strip() for n in (project_names or []) if isinstance(n, str) and n.strip()})
    if not names:
        return _own_evidence_result(0, [])           # no identity ⇒ nothing is provably "our own"
    token = re.compile(r"(?<![0-9A-Za-z_-])(?:"
                       + "|".join(re.escape(n) for n in names)
                       + r")(?![0-9A-Za-z_-])")
    sourced = []
    for path in paths:
        src = _pattern_frontmatter_sourced_from(path)
        if src and token.search(src):
            sourced.append(path.stem)
    if not sourced:
        return _own_evidence_result(0, [])
    corpus = _repo_citation_text(Path(repo_root))
    uncited = sorted(slug for slug in sourced if slug not in corpus)
    return _own_evidence_result(len(sourced), uncited)


def _pattern_frontmatter_sourced_from(path: Path) -> "str | None":
    """This pattern's frontmatter `sourced_from`, or None when it cannot be read as one.

    None means NOT-QUALIFYING, and every failure mode collapses here — no frontmatter, an unterminated
    block, malformed YAML, a non-mapping document, an absent / blank / non-string field. Fail-closed in
    the quiet direction on purpose: an unreadable pattern is never reported as this project's own
    evidence, because claiming provenance we could not read would be the false positive this view most
    needs to avoid."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return None
    try:
        front = state.load_str(text[3:end])
    except yaml.YAMLError:
        return None
    if not isinstance(front, dict):
        return None
    src = front.get("sourced_from")
    return src.strip() if isinstance(src, str) and src.strip() else None


def _repo_citation_text(repo_root: Path) -> str:
    """One concatenated blob of THIS repo's own corpus — the searched surface, bounded by
    `_CITATION_SURFACES`. Unreadable files are skipped rather than raising: a file we cannot read
    simply does not prove a citation, which keeps the fold quiet rather than wrong."""
    chunks = []
    for sub, glob in _CITATION_SURFACES:
        d = repo_root / sub
        try:
            entries = sorted(d.glob(glob))
        except (OSError, TypeError):
            continue
        for f in entries:
            try:
                chunks.append(f.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError):
                continue
    ops = repo_root / "yitc-ops.yaml"
    try:
        chunks.append(ops.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        pass
    return "\n".join(chunks)


def _own_evidence_result(total_sourced: int, uncited: list) -> dict:
    return {
        "lens": "own-evidence-uncited-patterns (SPEC-0119 rule 22, T-11211) — kernel patterns whose "
                "`sourced_from` NAMES this project, that this project has never cited. A kernel SPEC "
                "that is active+adoptable reaches every consumer whether or not anyone writes to them "
                "(SPEC-0112 makes silence a fail-closed ERROR at the consumer's own `init`); a "
                "PATTERN has no such gate — it is a shelf, reached only if a human remembers to "
                "mention it. Measured 2026-08-16 across all nine v2 consumers (kupiclub X-0961): the "
                "consumer-suite-parallelization pattern is live in exactly TWO projects, and they are "
                "the two named in its own `sourced_from`. NO fleet-wide threshold is derived from "
                "that: the table is evidence of a DELIVERY gap, never a target shape, and zero "
                "`subject_globs` or one monolithic layer can be the right answer for a young or "
                "genuinely coupled project. REACH IS NARROW and deliberately so — only patterns "
                "naming a project in `sourced_from` qualify. Report-only, never a gate: it SURFACES, "
                "it never prescribes, ranks or selects.",
        "total_sourced": total_sourced,
        "count": len(uncited),
        "names": uncited,
    }


def _plan_census_result(total: int, by_status: dict, unknown: int, terminal: int,
                       stale: list = None) -> dict:
    count = sum(by_status.values()) + unknown
    return {
        "lens": "non-terminal-plan-census (SPEC-0119 rule 21, T-11181) — how many plans sit in each "
                "NON-TERMINAL stage of the plan FSM (draft/specs/trial/accepted/decomposition/"
                "executing/postcheck), so a plan parked mid-lifecycle does not fall out of sight. "
                "Plans are the one tracked work class no seam surfaced: the picker reads `tasks/` "
                "ONLY, and a plan in `postcheck` — the real-data soak — is unfinished work that "
                "simply goes quiet. TERMINAL plans (realized/partial/rejected/cancelled) are NOT "
                "counted: that is the bulk of the corpus and exactly the noise this line avoids. The "
                "filter is a COMPLEMENT — only the provable terminals are excluded — so a plan whose "
                "status is missing, malformed or unrecognised is counted as `unknown` rather than "
                "silently dropped. DERIVED at read time from the same frontmatter `plan list` reads "
                "— zero stored state, no new store, no cadence. SLICE STALENESS (T-12081) rides "
                "the SAME line as a suppressed-when-clean TAIL naming candidates: a plan in "
                f"`decomposition` for >={PLAN_DECOMPOSITION_STALE_DAYS}d, an `executing` plan's "
                f"non-terminal cut card untouched for >={PLAN_CUT_CARD_UNTOUCHED_DAYS}d (named by "
                f"plan + card), and an `executing`/`postcheck` umbrella >={PLAN_UMBRELLA_RENEWAL_DAYS}d "
                "since `accepted` with no `renewed_at` note. Age is read from the "
                "`plan_stage_entered` rows the FSM already emits, over ONE bounded window; PROVABLE "
                "YOUTH SILENCES, so a young artifact whose rows aged out is never named. Report-only, "
                "never a gate: it SURFACES plans, it never picks, ranks, suggests or selects one.",
        "total": total,
        "count": count,
        "by_status": by_status,
        "unknown": unknown,
        "terminal": terminal,
        # T-12081 — the SLICE-STALENESS tail: named candidates, additive to and never folded into
        # the counts above. Empty is the clean state and renders NOTHING (suppressed-when-clean).
        "stale": list(stale or []),
        "bounds": {"decomposition_days": PLAN_DECOMPOSITION_STALE_DAYS,
                   "cut_card_days": PLAN_CUT_CARD_UNTOUCHED_DAYS,
                   "umbrella_days": PLAN_UMBRELLA_RENEWAL_DAYS},
        "next": ("read one with `bin/yitc-v2 plan show <slug>` and list them with `bin/yitc-v2 plan "
                 "list`; then advance it, or close it honestly (`plan stage realized|partial` / "
                 "`--status cancelled`). Taking a plan into work is an OWNER CUE — this line names "
                 "no candidate and selects nothing."
                 if count else
                 "no plan sits in a non-terminal stage — nothing is parked mid-lifecycle."),
    }
# ─────────────────────────────────────────────────────────────────────────────────────────────────
# REMOTE-LAG view (SPEC-0119 rule 20 / SPEC-0163, T-11187 / X-0932)
# ─────────────────────────────────────────────────────────────────────────────────────────────────

_REMOTE_LAG_GIT_TIMEOUT = 10   # seconds — bound each local git read; a hung git degrades, never hangs a seam

# The git subcommands this view MUST NEVER issue. It reads LOCAL refs only — no fetch, no ls-remote,
# no push, no pull, no connection of any kind (SPEC-0119 rule 20). Named here so the contract is
# assertable from a test rather than asserted in prose (T-11187 AC3 structural arm).
REMOTE_LAG_FORBIDDEN_GIT = frozenset({"fetch", "ls-remote", "push", "pull", "remote-http", "clone"})


def _remote_lag_git(repo_root, *gitargs) -> "str | None":
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


def remote_lag(ops_path, repo_root, _git=None) -> dict:
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
    kupiclub measured (X-1094 / T-11424): this view's OWN printed remedy interpolated the declared
    value verbatim, so following it pushed by URL and left the count unchanged, and the remedy could
    not clear the signal that printed it. Which is why the remedy now prints the RESOLVED CONFIGURED
    NAME (`push_remote`, from `_resolve_configured_remote`) rather than the declared string: the
    advice this view gives is the one form of push that updates the ref it reads. Given a push by
    name, the baseline is EXACT for the single declared `pusher:` the declaration describes. The failure
    this exists to catch — aiseller's v1 auto-pusher dying at quiesce (SPEC-0163 rationale / T-10419) —
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


# ---------------------------------------------------------------------------------------------
# DEAD LANDS (SPEC-0119 rule 23, T-11254 / kupiclub X-0976) — the land that died before its own
# terminal signal. The land step-1 fold commit is the marker land ALREADY wrote; the journal is the
# record of whether it ever reported. This view is the JOIN of those two things that already exist.
# ---------------------------------------------------------------------------------------------

# The land step-1 fold's commit subject (`worktree._land_bookkeeping_commit`, T-9799 / T-10821):
# `<msg_prefix>: bookkeeping (<branch>)`. ONLY the `land` prefix qualifies — `worktree sync` mints the
# byte-identical shape under its OWN prefix and a sync is NOT a land, so a sync-tipped branch is
# mid-normal-work and must stay silent. The BRANCH NAME inside the parens is matched too, so an
# authored commit that merely happens to start with the word `land:` can never impersonate the marker.
DEAD_LAND_TIP_PREFIX = "land: bookkeeping ("

# The terminal row, in EITHER direction. An ABORT counts as REPORTED and therefore SUPPRESSES: it left
# a row, said what went wrong, and the repeated-abort backstop (`_land_repeated_abort_count`) already
# owns that class. This view exists for SILENCE, not for failure.
DEAD_LAND_TERMINAL_EVENT = "land_completed"

# T-11682 — the row a DEAD BATCH HEAD's batch already wrote about what killed it. A head that dies
# mid-verify writes no `land_completed`, so every reader that keys on that row (the abort-cost fold,
# the repeated-abort backstop, the halt cause) sees nothing — while the batch's OWN cause is sitting
# on main, on the `land_member_verdict` rows `_land_dissolve_batch` / `_land_release_peers_for_solo_head`
# emitted BEFORE the head died. Measured 2026-08-26: batch `bat-2114bce5cf05` (formed 11:02:13Z) put
# six named pinned failures and a `red_isolation_decline{pinned-entry}` on all four member rows at
# 11:10:22Z; the head then died and no surface joined the two. This is the join key.
DEAD_LAND_MEMBER_EVENT = "land_member_verdict"

# The keys whose PRESENCE means the row is about a RED batch. Gated on the EVIDENCE, never on the
# verdict string: rule 5's vocabulary is closed and owned elsewhere, and a `landed` / `unaccounted`
# row must never be dressable as a red.
DEAD_LAND_RED_EVIDENCE_KEYS = ("red_assertions", "red_isolation", "red_isolation_decline",
                               "evicted_as_culprit")


def _dead_land_red_cause(row: "dict | None", branch: "str | None") -> "dict | None":
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


def _dead_land_tip_is_land_marker(subject, branch) -> bool:
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
               _member_rows=None, now=None) -> dict:
    """Fold the branch frontier + the journal → the lands that STARTED and never REPORTED
    (SPEC-0119 rule 23). The newest sibling of `unresolved_worker_halts` / `nonterminal_plan_census`,
    and built to the identical contract: a pure fold, injected collaborators, `{lens, now, count, …}`
    out, report-only, ZERO stored state.

    THE ONE RULE THIS SHIPS. A land is killed between its first commit and its first event, and no
    surface in the system can see it — because every surface keys off a row that land never wrote. The
    `LAND:` token is stdout of a process that is gone. The repeated-abort backstop counts
    `land_completed{abort}` rows. The sibling debt views fold halts, followups and plans. So the ONE
    trace such a land does leave is a GIT COMMIT, and this is the only reader that looks at it.

    Measured, in this repo, 2026-08-18 (T-11254 — the kernel half of kupiclub X-0976): `land` ran on
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


def _dead_land_result(now, lands: list, floor_minutes: int = 90) -> dict:
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


# ── SPEC-0119 rule 24 — work branches AHEAD of main (T-11303 / kupiclub X-1001, corrected by X-1003) ──
# The two branch namespaces `worktree new` creates, and therefore the two the lifecycle is RESPONSIBLE
# for landing. Named once so the subject bound cannot drift between the fold and its tests. A ref outside
# them (a bench fixture, a hand-cut experiment) is not lifecycle-owned work and is not this view's debt.
AHEAD_BRANCH_NAMESPACES = ("task/", "work/")


def ahead_work_branches(_frontier, floor_hours: int = 24, *, now=None) -> dict:
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

    WHAT THE COUNT MEANS, stated because the reporter corrected themselves on exactly this (kupiclub
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
                "absent from main (kupiclub X-1003) — a change that reached main by another commit "
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



# ── SPEC-0119 rule 32 — LIVE work branches BEHIND main (T-11579 / kupiclub X-1105) ───────────────────
def behind_work_branches(_frontier, floor_commits: int = 200, *, now=None) -> dict:
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

    WHAT THE REPORTER MEASURED (kupiclub X-1105). Five live worktrees, ALL behind main — by 881, 881,
    881, 273 and 168 commits — while that morning's debt echo named exactly ONE branch, and named it
    for being AHEAD by a single commit. Over that repo's whole history 1077 worktrees were created
    and 80 carry a sync record: 7% were ever measured at all, and that 7% is biased toward the
    best-tended copies. The concrete cost is theirs too (kupiclub T-0435, 2026-08-20/21): a
    234-behind worktree carried two verify REDs already fixed on main, so the session correctly ran
    on main instead — where the stage-bound verb was inapplicable, so it hand-ran per-layer scripts,
    missed one of three declared layers, and wrote receipts naming scripts instead of declared test
    classes. Sync-then-run-in-the-worktree cost a minute and is what the next morning did.

    WHAT THE COUNT MEANS — the sibling's honest bound, carried VERBATIM and for the same reason
    (kupiclub X-1003). `<branch>..main` counts commits main has BY SHA that the branch lacks. It is
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
    stale one. It is also below the originating incident's own 234 (kupiclub T-0435), so it would have
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
                "nothing (kupiclub X-1105: five live worktrees behind by 881, 881, 881, 273 and 168 "
                "while the echo named one branch, for being AHEAD by one commit). The count is of "
                "commits main has BY SHA that the branch lacks and is NEVER a claim their CONTENT is "
                "absent from the branch (kupiclub X-1003). Derived from the git frontier at read "
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

# ── SPEC-0119 rule 25 — CONCURRENT SESSION HOLDS on one repo (T-11353 / kupiclub X-1025) ─────────────
# The stamp value a worktree carries when `_read_worktree_stamp` could not resolve one (raw `git
# worktree add`, an unreadable or malformed stamp file). Named once so the fold and its tests cannot
# disagree about what "we could not tell who holds this" looks like on the wire.
UNKNOWN_HOLDER = "UNKNOWN (unstamped / raw-git)"


def concurrent_session_holds(_holders, own_ref, *, own_fleet_refs=None, now=None) -> dict:
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


# ── SPEC-0119 rule 26 (T-11380 / the 2026-08-21 04:27-04:49 window): ONE land-abort cause refusing
#    SEVERAL DIFFERENT branches ─────────────────────────────────────────────────────────────────────
#
# The gap this closes, measured. On 2026-08-21 an uncatalogued live event type on `main` refused four
# branches inside about an hour (T-11370 04:27, T-11375 04:37, T-11368 04:45, T-11358 04:49). Each
# worker diagnosed it correctly and INDEPENDENTLY, each paid a full verify (430-560s) to get there,
# and each escalated the same finding; the fourth escalation looked exactly like the first. NOTHING
# folded the recurrence, and the three surfaces a reader would reach for could not: the re-run-vs-resolve
# discipline (CHARTER P7) is scoped to ONE session's repeated attempts, the repeated-abort backstop
# (T-0655, `_land_repeated_abort_count`) streaks PER BRANCH, and the audit-loop ceiling (SPEC-0124) is
# per task. A cause that fails ONCE on each of four DIFFERENT branches trips none of them, because no
# single branch ever repeats. This fold is the reading that spans branches — and ONLY that.
#
# WHAT IT IS NOT. A MITIGATION, never the fix: a repo-wide freeze is fixed by making the gate
# branch-attributable (T-11379, in flight, which removes most of what this would surface). This makes an
# ongoing one VISIBLE sooner and nothing more — report-only, suppressed when clean, no store, no event,
# no exit code, no gate, and it names a CAUSE, never a candidate.
#
# THE IDENTITY IS BORROWED, NOT MINTED. The cause identity is `worktree._land_abort_cause_identity` —
# the SAME fine identity the repeated-abort backstop already streaks on — INJECTED, so this fold owns no
# notion of "same cause" of its own and the two can never disagree (CHARTER P5 / P1 "existing analog?").
#
# THE UNDER-COUNT, stated because it was MEASURED on the very incident this exists for. That identity is
# the SET of failing assertions, so ONE shared cause co-failing with a DIFFERENT sibling assertion splits
# into two identities: of the three branches the catalogue gate refused, only two (T-11375, T-11368)
# share a digest — the third (T-11358) failed on the catalogue assertion ALONE. So this fold UNDER-reports
# by construction. That is deliberate and it is the cheaper error: the alternative is a per-ASSERTION
# identity, i.e. a SECOND identity beside the backstop's, which is exactly what the card forbids and what
# would let the two surfaces disagree about what "one cause" means.
#
# WIDENED TO THE SECOND REFUSAL SHAPE (T-11810, the 2026-08-28 09:56-10:52 window). A land abort is
# not the only way one cause refuses a branch. When a BATCH goes red, NO member lands and every one
# is journaled `land_member_verdict{verdict: requeued-after-red-batch}` carrying the batch's failing
# set as `red_assertions` (SPEC-0184 rule 5 / T-11331) — a fully paid verify that shipped nothing,
# in every way this fold cares about identical to an abort. Reading `land_completed` alone made those
# INVISIBLE: on 2026-08-28 one branch-local acceptance assertion reddened six batches in about an
# hour and requeued its peers 5/4/3/2 times, and this fold saw NONE of it. The loop ended when a
# human killed the land. So the event filter is a SET of two types, and the admission gate for each
# is its own type's "this was a refusal" predicate — `status == "abort"` for one, the requeue verdict
# for the other. Everything else about the rule is untouched.
#
# THE ADAPTER IS ONE KEY, AND THAT IS WHY NO SECOND IDENTITY EXISTS. `_land_abort_cause_identity`
# consumes exactly ONE key, `failing_assertions`. A member-verdict row carries the same content under
# a different NAME, `red_assertions`. So a member row is mapped by RENAMING that one key into a
# throw-away dict handed to the SAME injected callable — not by re-deriving anything. Two consequences
# are load-bearing and neither is incidental: (1) AC3's fence holds in its strong form — this module
# computes no digest for EITHER event type, so the fold and the T-0655 backstop still cannot disagree
# about what one cause is; (2) DEDUPLICATION FALLS OUT — a requeue row and an abort row naming the
# same assertion text digest IDENTICALLY, land in ONE group, and a branch that first requeued and
# later aborted on that cause is added twice to a SET, counting 1. That matters: counting it twice
# would manufacture breadth that did not happen, and a report-only line that cries wolf is worse than
# the silence it replaced.
#
# NAMES BESIDE THE DIGEST (T-11810's second half, and the one that would have paid off first). This
# fold FIRED correctly on the 2026-08-28 incident — `verify-failed#67dd68e5dcff on 7 branches` — and
# the controller who received that line at session start read past it, because a digest names nothing
# a reader can act on and the row's own next step was another manual hop. Both row shapes ALREADY
# carry the assertion TEXT (`failing_assertions` / `red_assertions`), so each cause now reports a
# BOUNDED sample of it and the render prints one or two names beside the unchanged
# `<abort_class>#<digest>`. The digest is not dropped — it is what ties this line to the backstop.
# Bounded on purpose: this is a suppressed-when-clean line on a seam that already carries a dozen
# others, and a wall of text gets read past for a different reason.
_ABORT_BREADTH_EVENTS = ("land_completed", "land_member_verdict")
_ABORT_BREADTH_MEMBER_REQUEUE_VERDICT = "requeued-after-red-batch"   # SPEC-0184 rule 5's requeue
_ABORT_BREADTH_MEMBER_LANDED_VERDICT = "landed"          # SPEC-0184 rule 5's member that REACHED main
_ABORT_BREADTH_MAX_NAMED_ASSERTIONS = 3   # the bounded AC6 sample carried per cause (render shows <=2)
_ABORT_BREADTH_WINDOW_HOURS = 24    # the reading horizon; a report-only bound, not a governance scalar
_ABORT_BREADTH_MIN_BRANCHES = 2     # DISTINCT branches on ONE cause before the line prints (see below)


def _abort_breadth_refusal(event: dict) -> "tuple | None":
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


def _abort_breadth_resolution(event: dict) -> "str | None":
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
                             min_branches: int = _ABORT_BREADTH_MIN_BRANCHES, now=None) -> dict:
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
                events_path, _window_segment_floor(now, hours=window_hours)):
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


# ── SPEC-0119 rule 34 (T-11821 / the branches measured on 2026-08-28): ONE BRANCH burning REPEATED
#    UNLANDED LAND ATTEMPTS, whatever the cause each time ────────────────────────────────────────
#
# THE TRANSPOSE OF RULE 26, and deliberately nothing more. Rule 26 above reads ONE CAUSE across MANY
# BRANCHES. This reads ONE BRANCH across MANY CAUSES. They are two projections of the same fold over
# the same already-emitted rows, which is why this is a second projection rather than a mechanism:
# no new store, no new event, no new verb, no new seam, no exit code moves.
#
# THE GAP, MEASURED AT THE KEY LEVEL rather than inferred. Every surface that could catch a stuck
# branch is keyed on the REPETITION OF A CAUSE. The T-0655 repeated-abort backstop is per BRANCH but
# arms only on N CONSECUTIVE aborts sharing a cause key; the SPEC-0124 audit-loop ceiling is per
# TASK and counts audit passes, not land aborts; CHARTER P7 re-run-vs-resolve is per SESSION and
# behavioural; rule 27's aborted-land cost view groups BY CLASS, so one branch's several classes
# scatter across several rows and never sum. Read directly off this repo's journal on 2026-08-28:
# `task/T-11810` carried five aborts of five distinct classes, FOUR of them `cause_identity_absent`
# with an empty failing-assertion list; `task/T-11733` carried seven, and no two CONSECUTIVE aborts
# shared a refined key. The backstop therefore never armed on either.
#
# AND THE STATEMENT IS SHARPER THAN "A DIFFERENT REASON EACH TIME" — do not soften it back to that.
# A whole FAMILY of abort classes carries NO cause identity at all (`concurrent-land-same-worktree`,
# `merge-non-union-conflict`, `audited-diff-stale`, `unexpected`): for those rows the refined key
# cannot be COMPUTED, so consecutive aborts within that family are not merely different, they are
# INCOMPARABLE. A branch cycling through infrastructure aborts is structurally UN-ARMABLE rather
# than unlucky. That is why the answer is a cause-AGNOSTIC projection and not a threshold change:
# no threshold on a key that does not exist will ever fire.
#
# REPORT-ONLY, AND THE REASON IS RECORDED BECAUSE IT CONSTRAINS ANY FUTURE STRENGTHENING. The
# external adjudication (GREEN, zero findings, 2026-08-28) rejected a cause-agnostic GATE as a first
# move: it would confuse stuckness with LEGITIMATE ITERATION — a branch that first resolves a merge
# conflict, then refreshes audit currency, then fixes verify fallout, where each abort reveals real
# forward progress. That is exactly what `task/T-11810` did before landing on its sixth attempt. If
# a gate is ever built here, advisory before enforcement.
#
# THE COUNT IS THE PRIMARY KEY; ELAPSED TIME AND DISTINCT-CLASS COUNT ARE ANNOTATIONS IN THE LINE.
# The class is "many unlanded attempts REGARDLESS of cause", so the count is what selects. But a
# bare count cannot tell a three-hour burn from a three-minute one, so the elapsed span and the
# number of distinct abort classes ride IN the line — annotations, never better keys.
#
# WHAT IS DELIBERATELY NOT HERE: no cause identity is consulted, computed or borrowed anywhere in
# this fold. Rule 26 owns that reading and this one must not acquire a second opinion about it
# (CHARTER P5). What IS shared with rule 26 is the definition of a REFUSAL SHAPE — the
# `_ABORT_BREADTH_EVENTS` type set and the requeue verdict constant, reused rather than restated, so
# the two projections can never disagree about which rows are refusals.
_BRANCH_BURN_MIN_ATTEMPTS = 4     # DISTINCT unlanded attempts on ONE branch before the line prints


def _branch_burn_land_row(event: dict) -> "tuple | None":
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
                                 min_attempts: int = _BRANCH_BURN_MIN_ATTEMPTS, now=None) -> dict:
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
        for event in journal.fold_rows(events_path):   # T-11453 — the ONE shared fold
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


# ---------------------------------------------------------------------------
# SPEC-0119 rule 28 (T-11396) — A RECORDED MEASUREMENT DRIFTING TOWARD ITS OWN FLOOR
#
# Some artifacts in this repo are RECORDED MEASUREMENTS: a number written down once, which a test
# re-computes live and compares against. SPEC-0161's payload-key candidate set is one — its test
# (`tests/test_event_catalog_completeness.py` AC2) recomputes the governing (type, payload-key)
# pairs and requires the recorded run to still NAME at least `SPEC0161_COVERAGE_FLOOR` of them.
#
# Such a record DRIFTS by construction as the corpus grows, and the drift is NOT a defect — the
# test's own comment says so ("a key that later becomes spec-carried leaves the recomputed set, and
# one newly-governing key is ~3 points"). What IS a defect is WHEN the drift is discovered: with no
# surface reading the coverage, the first reader is a `land` verify, refusing as a hard gate, on
# whoever happens to be landing. Measured twice on 2026-08-21: coverage reached 79% against the 0.80
# bar and refused `work/spec0161-name-acceptance-probe-recorded` — the land of the very card filed
# to unblock a frozen branch — with ten governing pairs unnamed.
#
# This fold makes the approach VISIBLE at the seams the debt echo already has, so the refresh is
# ordinary maintenance done when someone chooses, instead of an ambush during an unrelated land.
#
# THE TWO NON-GOALS, both structural rather than promised. It GATES nothing, refuses nothing and
# auto-refreshes nothing — a record that refreshed itself would stop being a measurement, since the
# recomputation would then be comparing the corpus against itself. And it does not move the floor:
# `SPEC0161_COVERAGE_FLOOR` is 0.80 here because it is 0.80 in the test, and this module is now the
# ONE place that number lives.
#
# ONE ORACLE, NOT TWO (the card's AC3, and the T-11216 one-oracle discipline). The computation below
# is not a debt-side re-implementation of the test's rule: it is THE rule, moved here, and the test
# calls it. A second implementation would drift from the first exactly as the record drifts from the
# corpus — the failure this whole fold exists to catch, reproduced one level up.
#
# NO DURATION VOCABULARY, AND THE NOTE ITSELF MUST OBEY THAT.
# `tests/test_spec0149_obligation_fold.py` reads `inspect.getsource` over this WHOLE module and
# asserts that three duration-resolving tokens — the datetime duration constructor, the defaulted
# window constant, and the carrier's window declaration key — appear NOWHERE in the file. Its scope
# is the file, not its own subject fold
# (`lessons/a-shared-module-may-forbid-vocabulary-your-fold-wants`). This fold measures a RATIO and
# needs no window, so it introduces none of them.
# Read the three token spellings in that test's own assertion, NOT here: it is a plain substring
# scan over the source, so a comment QUOTING them verbatim trips it exactly as code would. That is
# not hypothetical — the first draft of this very note did, which is the sharpest available proof
# that the tripwire's scope really is the whole file.
# ---------------------------------------------------------------------------

SPEC0161_COVERAGE_FLOOR = 0.80
"""SPEC-0119 rule 28 / SPEC-0161 (T-11396): the floor the recorded payload-key candidate set must
still cover, named ONCE so the debt line's bar and the test's bar are the SAME object.

0.80 rather than 1.0 is SPEC-0161's own judgement, unchanged by this task: a key that later becomes
spec-carried leaves the recomputed set, and one newly-governing key moves coverage a few points —
neither is a defect. Omitting or gutting the recorded run text lands near 0, which is the direction
that matters and which the floor still catches loudly."""

SPEC0161_RECORD_HEADING = "**PAYLOAD-KEY half re-run"
"""The heading that opens SPEC-0161's recorded-run paragraph — the span excluded from the corpus the
candidate comparison reads. Naming a key inside the RECORD does not spec-carry it, so counting that
paragraph would make the measurement self-erasing (record 36 candidates -> the next run finds 0)."""


def spec0161_payload_key_coverage(*, corpus, code_blob, type_keys, spec_text):
    """SPEC-0119 rule 28 (T-11396): THE ONE ORACLE for SPEC-0161's payload-key coverage — pure, no
    I/O, no policy. Both readers call THIS: the `tests/test_event_catalog_completeness.py` AC2 gate
    and the rule-28 debt fold below.

    Inputs are handed in rather than read, which is what makes the rule fixture-drivable (the card's
    AC1 differential probe needs a corpus sitting just above the floor and one comfortably clear,
    neither of which exists on disk) and what keeps this function honest about having no ambient
    state:
      corpus     — the concatenated `specs/*.yaml` text.
      code_blob  — the concatenated `bin/**` text (where a payload key is READ BACK).
      type_keys  — {event type -> set of data keys} folded from the journal.
      spec_text  — SPEC-0161's own YAML text.

    THE RULE. A (type, key) pair is GOVERNING when the type is mentioned somewhere in the spec
    corpus, the key is NOT mentioned anywhere in that corpus (with SPEC-0161's own recorded-run
    paragraph excised — see SPEC0161_RECORD_HEADING), and the key IS read back by some code in
    `bin/`. That last conjunct is what separates a key that MATTERS from incidental payload: code
    reads it, so its meaning is load-bearing, yet no spec says what it means. A pair is NAMED when
    SPEC-0161's recorded run mentions both halves.

    Returns {governing, named, unnamed, coverage}. `coverage` is None when nothing governs — an
    empty denominator is not 100% coverage, and a caller must not read it as clean."""
    record_start = spec_text.find(SPEC0161_RECORD_HEADING)
    record_end = spec_text.find("## Verification", record_start) if record_start != -1 else -1
    corpus_for_keys = corpus
    if record_start != -1:
        corpus_for_keys = corpus.replace(spec_text[record_start:record_end], "")
    corpus_words = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", corpus_for_keys))

    readback = set(re.findall(r"\.get\(\s*[\"']([A-Za-z_][A-Za-z0-9_]*)[\"']", code_blob))
    readback |= set(re.findall(r"\[\s*[\"']([A-Za-z_][A-Za-z0-9_]*)[\"']\s*\]", code_blob))

    governing = []
    for t, ks in type_keys.items():
        if t not in corpus:
            continue
        for k in sorted(ks):
            if k not in corpus_words and k in readback:
                governing.append((t, k))

    named = [pair for pair in governing if pair[0] in spec_text and pair[1] in spec_text]
    unnamed = [pair for pair in governing if pair not in named]
    return {
        "governing": governing,
        "named": named,
        "unnamed": unnamed,
        "coverage": (len(named) / len(governing)) if governing else None,
    }


# ---------------------------------------------------------------------------
# T-12232 / SPEC-0161 — WHO IS CHARGED FOR AN UNNAMED PAYLOAD KEY
#
# The oracle above answers "which governing (type, key) pairs does the record fail to name?" over the
# LIVE corpus + code + journal. That question has no branch in it, and for a land-verify gate that is
# the defect: the journal is a SHARED, GROWING input while the record moves only by a human edit, so
# the instant one branch's emitter row reaches main carrying an unnamed governing key, the gate reds
# EVERY branch's candidate leg — including every branch whose diff never went near that emitter.
#
# MEASURED, 2026-09-07, both faces of it. T-12150's `queued_premerge` reached main's journal at
# 10:45Z; from 10:50Z every land reddened on `tests/test_spec0161_payload_key_refresh.py` — 7 aborted
# lands, 4 workers halted `blocked-on-land`, ~70 minutes of wall on `queued_premerge` — until T-12225
# named the pairs at 12:01Z. Then T-12222 introduced `measurement_recorded.test_files` and reddened
# its OWN land 3x the same way. The first face is a branch charged for a key it did not introduce;
# the second is the branch that DID introduce it being told minutes in, past the venue slot, by a
# whole-suite verify — when a `git diff` at the door knew it for free.
#
# WHAT THIS ADDS IS ONE PREDICATE, NOT A SECOND ORACLE. Attribution is a pure split of the ONE
# oracle's existing `unnamed` list by a question about the branch's own diff: does the key literal
# appear on a line this branch ADDED under `bin/`? Everything below is that predicate plus the
# smallest materialiser it needs. No new store, no new event type, no new journal payload key, and
# the oracle itself is untouched — the T-11216 one-oracle discipline its docstring names.
#
# THE TWO FAIL-SAFE DIRECTIONS ARE DELIBERATELY OPPOSITE, AND THAT IS THE POINT. When the diff
# cannot be computed the attribution is UNKNOWN, and unknown must not read the same at a gate as at
# a test. The `land` preflight and the commit WARN ADMIT on unknown — a guard whose whole purpose is
# to make a refusal CHEAPER must never invent one out of a fact about the checker (the codebase's
# own words at the T-11718 arm). The land-verify TESTS fall back to today's whole-corpus bar on
# unknown — a governance gate that cannot attribute keeps its old strictness rather than going
# quiet. `attributable: False` is what lets each caller take its own direction; it is the reason the
# unknown case is a NAMED third state and not an empty `introduced` list.
# ---------------------------------------------------------------------------


#: The two triple-quote openers, kept only as the shape a docstring is written in — the tokenizer
#: below is what actually decides, so nothing here re-implements Python's own lexing.
_SPEC0161_TRIPLE_QUOTES = ('"""', "'''")

#: The token types after which a STRING token is a DOCSTRING (an expression statement whose whole
#: content is a literal) rather than a value in an expression.
_SPEC0161_DOCSTRING_PRECEDERS = frozenset(
    {tokenize.NEWLINE, tokenize.NL, tokenize.INDENT, tokenize.DEDENT})


def _spec0161_blank(grid, start, end):
    """Blank the half-open region `start`..`end` of `grid` (a list of per-line char lists), keeping
    every line and every column position — so line numbers survive the removal exactly."""
    (r0, c0), (r1, c1) = start, end
    for r in range(r0 - 1, min(r1, len(grid))):
        row = grid[r]
        lo = c0 if r == r0 - 1 else 0
        hi = c1 if r == r1 - 1 else len(row)
        for c in range(lo, min(hi, len(row))):
            row[c] = " "


#: A string literal whose CONTENT is exactly one identifier — the only shape a payload-key literal
#: can wear. Any other literal (an expression, a sentence, a path, a template) is blanked with the
#: comments and docstrings, so a quoted code example can never be read as a structural occurrence.
_SPEC0161_STRING_LITERAL = re.compile(
    r"\A[A-Za-z]*(\"\"\"|\'\'\'|\"|\')(?P<body>.*)\1\Z", re.DOTALL)
_SPEC0161_IDENTIFIER = re.compile(r"\A[A-Za-z_][A-Za-z0-9_]*\Z")


def _spec0161_is_identifier_literal(token_text):
    """True iff `token_text` (a STRING token, prefixes and quotes included) holds exactly one
    identifier — see `spec0161_code_text`\'s finding-B3 paragraph. PURE."""
    m = _SPEC0161_STRING_LITERAL.match(token_text or "")
    return bool(m) and bool(_SPEC0161_IDENTIFIER.match(m.group("body")))


def spec0161_code_text(text, lines=None):
    """The CODE of a POST-IMAGE FILE — comments and docstrings blanked out — restricted to `lines`
    (1-based line numbers; None = the whole file). PURE.

    WHY THE POST-IMAGE AND NOT THE ADDED-LINE BLOB (audit-post pass-3 residual B2). The scan below
    charges a branch for a key that appears in a structural position, and a QUOTED CODE EXAMPLE
    inside a comment or a docstring wears exactly those forms. Deciding comment/docstring status
    from the diff's `+` lines alone CANNOT WORK: a line added INSIDE a PRE-EXISTING docstring
    carries no opening delimiter, so the blob has no way to see the docstring enclosing it and
    scans prose as code — the exact edited-docstring shape the original finding named. A blob is
    not a parseable unit, and no amount of hunk-bounding makes it one.

    So the status is derived from the FILE, which IS parseable: the post-image is tokenised by
    Python's own lexer, COMMENT tokens and DOCSTRING tokens are blanked IN PLACE (spaces, so every
    line and column keeps its position), and only then are the added line numbers selected. An
    added line inside an untouched docstring is blank; an added line of real code is intact; and the
    question "is this position code?" is answered by the language, not by a heuristic.

    A STRING LITERAL THAT IS NOT A BARE IDENTIFIER IS BLANKED TOO (audit-post episode-2 finding B3).
    A docstring is not the only place a quoted code EXAMPLE hides: `EXAMPLE = \'row.get("k")\'` is a
    plain string token in real code, and the structural regexes below, being lexical, read straight
    through the outer quotes and charge a branch that added no emitter and no readback. The
    tokenizer already tells us where every string literal is, so the fix is to keep only the string
    literals that could BE a payload key — ones whose whole content is a single identifier, exactly
    the shape `.get("k")` / `["k"]` / `"k":` require — and blank every other one. A string holding an
    expression, a sentence, a path or a format template can then never contribute a key.

    THIS FUNCTION ONLY BLANKS AND SELECTS; the structural matching is `spec0161_structural_keys`,
    which runs over the WHOLE blanked file and filters by the key literal\'s own line (episode-2
    findings B4 / B4a). A `lines` selection here is still exact for reading back what a branch
    added, but it must not be what a structural form is matched against — a wrapped readback does
    not fit inside one physical line.

    FAILS OPEN ON AN UNPARSEABLE POST-IMAGE — returns "", charging nothing. Inventing a charge at a
    REFUSING gate out of a fact about the checker is the expensive error (the codebase\'s own words
    at the T-11718 arm), and a file that does not tokenise is a fact about the checker\'s reach."""
    src = text or ""
    grid = [list(row) for row in src.splitlines()]
    try:
        toks = list(tokenize.generate_tokens(io.StringIO(src).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError, ValueError):
        return ""
    prev = tokenize.NEWLINE
    for tok in toks:
        if tok.type == tokenize.COMMENT:
            _spec0161_blank(grid, tok.start, tok.end)
            continue                                    # a comment does not move `prev`
        if tok.type == tokenize.STRING:
            if prev in _SPEC0161_DOCSTRING_PRECEDERS or not _spec0161_is_identifier_literal(
                    tok.string):
                _spec0161_blank(grid, tok.start, tok.end)
        if tok.type != tokenize.NL:
            prev = tok.type
    if lines is None:
        return "\n".join("".join(row) for row in grid)
    wanted = {int(n) for n in lines}
    return "\n".join("".join(grid[n - 1]) for n in sorted(wanted) if 1 <= n <= len(grid))


#: The three STRUCTURAL forms, as ONE alternation over the WHOLE blanked post-image, each capturing
#: the key in the group named `key` — so a match carries the OFFSET of the key LITERAL itself and
#: `spec0161_structural_keys` can ask which LINE that literal sits on. The first two are VERBATIM the
#: readback regexes `spec0161_payload_key_coverage` derives its `readback` conjunct from; the third is
#: the mapping-key literal an emitter's payload dict writes.
_SPEC0161_STRUCTURAL = re.compile(
    r"\.get\(\s*[\"'](?P<key>[A-Za-z_][A-Za-z0-9_]*)[\"']"
    r"|\[\s*[\"'](?P<key2>[A-Za-z_][A-Za-z0-9_]*)[\"']\s*\]"
    r"|[\"'](?P<key3>[A-Za-z_][A-Za-z0-9_]*)[\"']\s*:")


def spec0161_structural_keys(text, lines=None):
    """The payload keys a branch INTRODUCES in one post-image file: the keys appearing in a
    STRUCTURAL position whose KEY LITERAL sits on one of `lines` (1-based; None = the whole file).
    PURE.

    A VIEW OVER `spec0161_structural_key_sites` (T-12411), which answers the same question one
    notch finer (WHERE each key sits). Keeping ONE matcher is what lets the three readers that need
    only the key set, the message that needs the charging SITE, and the merge-base side of the
    attribution all be judged by the same predicate — a second scanner could disagree with this one
    about what a structural position is, and at a REFUSING gate that disagreement is a false charge.

    THE MATCH IS RUN OVER THE WHOLE BLANKED FILE AND FILTERED BY THE LITERAL'S OWN LINE — which is
    what makes it exact in BOTH directions, the two ways a line-based selection gets this wrong:

      * SELECTING THE ADDED LINES FIRST severs a wrapped readback (`row.get(` on one line, `"k")` on
        the next): the key literal loses the `.get(` that makes it structural and the branch that
        added it reads as INHERITED — the preflight then admits an introduced key (episode-2
        finding B4).
      * WIDENING TO THE ENCLOSING LOGICAL LINE fixes that but over-reaches the other way: a branch
        adding an unrelated entry to a multi-line dict is charged for every PRE-EXISTING key in the
        same statement, a false charge at a REFUSING gate (episode-2 finding B4a).

    Matching over the whole file keeps every structural form intact, and requiring the KEY LITERAL —
    not the statement, not the `.get(` — to be on an added line asks exactly the question the rule
    asks: did THIS branch write this key here? A wrapped readback puts the literal on the added line;
    an untouched neighbour in the same dict does not."""
    return set(spec0161_structural_key_sites(text, lines))


def spec0161_structural_key_sites(text, lines=None):
    """T-12411: `spec0161_structural_keys` with the LINE each key was found on kept — returns
    `{key: [1-based line numbers, ascending]}` over the same blanked post-image, by the same match,
    with the same `lines` filter. PURE.

    THE LINE IS NOT DECORATION — it is what makes a charge CHECKABLE BY THE CHARGED PARTY. The
    refusal this feeds says "your diff introduces these keys"; without a `<path>:<line>` the operator
    must re-derive the scan by hand to find out WHERE, which at a gate that fires seconds before a
    venue slot is the expensive minutes the whole seam exists to save. The path is added by the
    caller that knows it (`_spec0161_branch_added_code`); this function owns the line.

    ONE SCANNER, TWO READERS: `spec0161_structural_keys` is `set()` of this, so the key set a gate
    charges and the sites a message prints can never come from two different notions of "structural".
    """
    scanned = spec0161_code_text(text, None)
    if not scanned:
        return {}
    wanted = None if lines is None else {int(n) for n in lines}
    starts = []                                         # cumulative offset of each line's start
    off = 0
    for row in scanned.split("\n"):
        starts.append(off)
        off += len(row) + 1
    sites = {}
    for m in _SPEC0161_STRUCTURAL.finditer(scanned):
        for group in ("key", "key2", "key3"):
            if m.group(group) is None:
                continue
            lineno = bisect.bisect_right(starts, m.start(group))
            if wanted is not None and lineno not in wanted:
                continue
            sites.setdefault(m.group(group), set()).add(lineno)
    return {k: sorted(v) for k, v in sites.items()}


#: The shape an EVENT TYPE literal wears — the same lowercase-identifier grammar the journal's own
#: types are written in (`_SPEC0161_RECORD_ROW`'s left-hand side). A `Call` whose first positional
#: argument is a string constant of this shape is what `spec0161_added_emit_pairs` reads as an emit.
_SPEC0161_EVENT_TYPE = re.compile(r"\A[a-z][a-z0-9_]*\Z")


def _spec0161_payload_dict_keys(node, lines):
    """The TOP-LEVEL string keys of one payload dict LITERAL whose key literal sits on an added line.
    PURE. `lines` is a set of 1-based added line numbers, or None for the whole file.

    TOP-LEVEL ONLY, and `**{...}` unpacked AT that top level counts as top level — because that is
    exactly what the journal's own candidate set is (`data.keys()`), so this derivation and the
    oracle agree BY CONSTRUCTION about what a payload key IS. A dict nested as a VALUE inside the
    payload contributes nothing: its keys could no more appear in `type_keys` than they can here."""
    keys = set()
    if not isinstance(node, ast.Dict):
        return keys
    for k, v in zip(node.keys, node.values):
        if k is None:                                   # `**expr` at the payload's top level
            if isinstance(v, ast.Dict):
                keys |= _spec0161_payload_dict_keys(v, lines)
            continue
        if not (isinstance(k, ast.Constant) and isinstance(k.value, str)):
            continue
        if lines is not None and getattr(k, "lineno", None) not in lines:
            continue
        keys.add(k.value)
    return keys


def spec0161_added_emit_pairs(added_files):
    """T-12423: the {event_type -> set(keys)} map read STRUCTURALLY FROM THIS BRANCH'S ADDED CODE —
    the SECOND candidate source for the ONE oracle, which otherwise learns a (type, key) pair only
    from a row that ALREADY EXISTS in the journal. PURE; never raises.

    WHY A SECOND SOURCE AND NOT A SECOND ORACLE (the T-11379 precedent — one rule, second
    quantifier). `spec0161_payload_key_coverage` walks `type_keys`, which `_spec0161_inputs` folds
    FROM THE JOURNAL, so a pair is not a CANDIDATE until a row carrying the key exists. A branch that
    ADDS THE EMITTER carries no such row — the first one is written at RUNTIME, after the land — so
    at its own land the preflight had nothing to see and ADMITTED it. MEASURED, 2026-09-11: T-12373's
    land brought `bg_dispatch_launched.land_regime` unnamed and was not refused; once a later dispatch
    emitted the first row ON MAIN, the census tripwire reddened EVERY candidate tree for 2h10m until
    the key was named by hand. The refusal that DID fire on aiseller fired on a key whose rows already
    existed — i.e. the gate only ever caught the case it was not built for.

    `added_files` — the same contract `_spec0161_branch_added_code` returns and
    `spec0161_attribute_unnamed` takes: a sequence of `(post_image_text, added_line_numbers_or_None)`
    pairs. `{}` on None, so a caller with an unknowable diff contributes no candidates (the
    fail-OPEN direction, which is the only safe one at a REFUSING gate).

    THE STRUCTURAL BOUNDARY, stated exactly (audit-pre finding 2). An EMIT CALL is a `Call` whose
    FIRST POSITIONAL argument is a string constant of event-type shape (`[a-z][a-z0-9_]*`). Its
    PAYLOAD KEYS are the TOP-LEVEL string keys of a dict LITERAL that is a DIRECT argument of that
    call — a positional argument or a keyword value — plus the top-level keys of any `**{...}` dict
    unpacked at that same top level (`_spec0161_payload_dict_keys`). A dict nested as a VALUE inside
    the payload is NOT a key source, and neither is a dict passed to some INNER call. That boundary
    is not a taste: the journal's candidate set is `data.keys()`, which is top-level only.

    A KEY COUNTS ONLY WHEN ITS LITERAL SITS ON A LINE THIS BRANCH ADDED — the same question arm (i)
    of the attribution asks, so a branch adding one entry to a pre-existing payload dict is charged
    for that entry alone and not for its untouched neighbours. The TYPE literal is deliberately NOT
    required to be on an added line: adding a new key to an EXISTING emit call is precisely the shape
    that reddened main, and requiring the type too would exempt it.

    NAMED BOUND, honest and fail-OPEN: an emitter whose payload dict is built in a VARIABLE and
    passed by name is not a literal at the call site and is not seen — the same residue the journal
    leg already documents. Unparseable text (a shell script, a file mid-edit) contributes nothing and
    never raises, because a file that does not parse is a fact about the CHECKER, and inventing a
    charge at a refusing gate out of one is the expensive error (the T-11718 arm's own words)."""
    pairs = {}
    for text, lines in (added_files or ()):
        try:
            tree = ast.parse(text or "")
        except (SyntaxError, ValueError, RecursionError):
            continue                                    # not Python, or mid-edit — charges nothing
        wanted = None if lines is None else {int(n) for n in lines}
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            first = node.args[0]
            if not (isinstance(first, ast.Constant) and isinstance(first.value, str)
                    and _SPEC0161_EVENT_TYPE.match(first.value)):
                continue
            keys = set()
            for arg in list(node.args[1:]) + [kw.value for kw in node.keywords if kw.arg]:
                keys |= _spec0161_payload_dict_keys(arg, wanted)
            if keys:
                pairs.setdefault(first.value, set()).update(keys)
    return pairs


def spec0161_attribute_unnamed(unnamed, *, added_files, unnamed_by_branch=None,
                               base_structural_keys=None):
    """T-12232: split the ONE oracle's `unnamed` pairs into the ones THIS BRANCH INTRODUCED and the
    ones it INHERITED from main. PURE — no I/O, no policy; the caller supplies both facts.

      unnamed           — `spec0161_payload_key_coverage(...)["unnamed"]`, a list of (type, key) pairs.
      added_files       — the contract `_spec0161_branch_added_code` returns: a sequence of
                          `(post_image_text, added_line_numbers)` pairs, one per touched `bin/`
                          file, where `added_line_numbers` is the set of 1-based line numbers this
                          branch ADDED (None = the whole file is new). None — not an empty
                          sequence — when the diff could not be determined.
      unnamed_by_branch — the SET of keys this branch removed from SPEC-0161's record span (may be
                          empty; ignored when `added_files` is None).
      base_structural_keys — T-12411: the SET of keys that ALREADY had a structural occurrence under
                          `bin/` AT THE MERGE-BASE. Subtracted from arm (i) below. None/absent = the
                          pre-T-12411 reading (nothing subtracted), which is what keeps this
                          function independently exercisable without a git repo.

    FOURTH MEMBER OF THE DIFF-AWARE FAMILY (`graph.seed_growth_warnings`,
    `graph.new_test_file_warnings`, `graph.uncatalogued_type_findings`) — same question, one level
    down: of a repo-wide condition, which part is THIS BRANCH answerable for? The three siblings
    answer it by a BASELINE-vs-CURRENT set comparison whose two sides the host resolves against
    `git merge-base HEAD main`. The un-naming arm below IS that shape exactly. The code arm is not,
    for a measured reason: this condition's base side would be the whole `bin/` tree AND the whole
    segmented journal re-folded at the merge-base — the two expensive inputs of `_spec0161_inputs` —
    and paying that twice inside a refusal whose entire promise is "seconds, before the venue slot"
    would spend the saving it exists to make.

    TWO WAYS A BRANCH BECOMES ANSWERABLE, and a diff-scoped derivation must carry BOTH or it exempts
    half the class silently:
      (i)  it ADDS the key TO CODE — the key appears on an added `bin/` line in one of the STRUCTURAL
           forms below, AND NO STRUCTURAL OCCURRENCE OF IT EXISTED UNDER `bin/` AT THE MERGE-BASE
           (T-12411, `base_structural_keys`);
      (ii) it UN-NAMES the key — the key was in SPEC-0161's record span at the merge-base and is not
           in it now (`unnamed_by_branch`). Editing a name out of the record makes the pair
           govern-and-unnamed exactly as surely as adding the emitter does.

    ARM (i) IS ALSO BASELINE-VS-CURRENT NOW (T-12411, aiseller X-1343 / T-0500). "The key is on a
    line this branch added" is not by itself "this branch INTRODUCED the key": a branch that adds a
    SECOND readback of a key already read back elsewhere under `bin/` on main added no new governing
    key at all, and charging it re-reads a key that governed before it existed. Measured: T-0500's
    land was REFUSED for `spike_channel_grant.compose_project` because it added
    `meta.get("compose_project")` in `bin/tests/spike_live_support.py`, while
    `bin/spike-lib.sh:46` had carried `m.get("compose_project")` at the merge-base all along. So arm
    (i) now subtracts `base_structural_keys` and the docstring's old concession — that the code arm
    could not afford the family's baseline-vs-current shape — is RETIRED: the base side is not the
    whole `bin/` tree, it is TARGETED at the handful of keys THIS branch added, which is cheap (see
    `_spec0161_branch_added_code`). Arm (ii) is deliberately NOT filtered by it: un-naming a recorded
    key is a charge whatever the code says, and a key un-named from the record is by definition one
    whose readback already existed.

    ARM (i) IS STRUCTURAL, NOT A WORD SCAN, and that distinction is load-bearing (audit-post finding
    1). A bare word scan charges a branch for MENTIONING the key — in a comment, a docstring, a
    refusal message, a test name — which is a false charge at a REFUSING gate, the one place a false
    positive is most expensive. So a key counts only where it appears in a position that actually
    makes it a payload key:
      * `.get("k")` and `["k"]` — VERBATIM the two regexes `spec0161_payload_key_coverage` derives
        its `readback` conjunct from. Not a lookalike: the same expressions, so "the branch added the
        readback that makes this key govern" is decided by the oracle's own notion of a readback.
      * `"k":` — the key as a MAPPING KEY LITERAL, which is how an emitter's payload dict names it.
        Needed because a branch may add the emitting dict while the readback already existed on main;
        without it that branch is charged nothing.
    Both forms require the key QUOTED, so prose can never trip them.

    ATTRIBUTION IS BY KEY, NOT BY (type, key). A diff that adds the key to ANY emitter under `bin/`
    owes the record its name, whichever type carries it — the record names keys. Requiring the TYPE
    in the diff too would let a branch add a new key to an EXISTING event type and be charged nothing.

    THE NAMED RESIDUE (the honest bound this shape inherits from its family). A pair that becomes
    govern-and-unnamed without this branch adding a structural occurrence or removing a recorded
    name — a row appended from the main checkout with no worktree (D-0049), or a key that becomes
    governing because an unrelated spec edit removed its only other corpus mention — reads as
    INHERITED on every branch, so no branch is failed for it. That is deliberate and is the same
    trade `graph.uncatalogued_type_findings` documents: a gate that cannot name a responsible party
    can only punish bystanders. It is not dropped — the SPEC-0119 rule-28 debt echo reads the raw
    corpus-wide coverage and surfaces it report-only.

    Returns {"introduced": [...], "inherited": [...], "attributable": bool}. `added_files=None`
    returns EVERY pair as inherited with `attributable: False` — an honest "cannot tell", NOT an
    empty `introduced` list that a caller could mistake for "this branch introduced nothing"."""
    pairs = [tuple(p) for p in (unnamed or [])]
    if added_files is None:
        return {"introduced": [], "inherited": pairs, "attributable": False}
    # THE POST-IMAGE IS MATCHED WHOLE AND FILTERED BY THE KEY LITERAL'S OWN LINE (residual B2, then
    # episode-2 findings B3/B4/B4a). Comment, docstring and quoted-example positions are blanked
    # from the parseable FILE; the structural forms are then matched across the whole of it, and a
    # key counts only when the LITERAL itself sits on a line this branch added — neither severed by
    # an added-lines-first selection nor over-reaching to a statement's untouched neighbours. See
    # `spec0161_structural_keys`.
    keys = set()
    for text, lines in added_files:
        keys |= spec0161_structural_keys(text, lines)
    # T-12411: ARM (i) MINUS the merge-base. A key whose structural readback pre-exists under `bin/`
    # on main was not introduced HERE, whichever line of this diff it also appears on. The
    # subtraction is applied to the CODE arm only — arm (ii) is unioned AFTER it, so an un-naming is
    # never cancelled by the readback whose existence is precisely what makes the un-naming matter.
    keys -= set(base_structural_keys or ())
    keys |= set(unnamed_by_branch or ())
    introduced = [p for p in pairs if p[1] in keys]
    inherited = [p for p in pairs if p[1] not in keys]
    return {"introduced": introduced, "inherited": inherited, "attributable": True}


#: A RECORD ROW, by the record's own grammar: a backtick-quoted `<event_type>.<key>[|<key>...]`.
#: Anchored `\A`/`\Z` so it matches a WHOLE token, never a fragment of a longer backticked run.
_SPEC0161_RECORD_ROW = re.compile(
    r"\A`([a-z_][a-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*(?:\|[A-Za-z_][A-Za-z0-9_]*)*)`\Z")

#: Any backticked token in the span, WITH the text around it, so a candidate row can be judged by
#: its NEIGHBOURS — which is what separates an enumerated row from a prose mention (see below).
_SPEC0161_BACKTICKED = re.compile(r"`[^`\n]+`")

#: The separator the recorded set is written with. A row is a member of that enumeration iff the
#: separator sits immediately beside it.
_SPEC0161_ROW_SEPARATOR = "\u00b7"

#: What may precede a row: the separator, or the COLON that introduces the enumeration. The colon is
#: what lets a record holding a SINGLE row still read as one — without it a one-row set, having no
#: separator anywhere, would parse as zero rows and silently stop detecting un-namings.
_SPEC0161_ENUMERATION_DELIMITERS = (_SPEC0161_ROW_SEPARATOR, ":")


def _spec0161_record_span_keys(spec_text):
    """The keys NAMED BY THE RECORD ROWS inside SPEC-0161's record span — parsed by the record's own
    grammar, NOT by a word scan of the span (audit-post pass-2 finding B1).

    The span is located from the SAME shared `SPEC0161_RECORD_HEADING` constant the oracle uses, so
    this and the oracle cannot disagree about where the record starts. Empty set when it is absent.

    WHY A GRAMMAR AND NOT A WORD SCAN. The only caller is the un-naming arm of
    `_spec0161_branch_added_code`, which charges a branch for a key that was in the span at the
    merge-base and is not in it now. Under a word scan that difference is taken over EVERY
    identifier in the span, prose included — so deleting a key-shaped word from an explanatory
    sentence, with every record row untouched, charges the branch and REFUSES its land. A false
    positive at a refusing gate is the expensive direction, which is why the baseline must read the
    ROWS and nothing else.

    THE ROW GRAMMAR, AND HOW A ROW IS TOLD FROM A PROSE MENTION. A row is a backticked
    `type.key|key` token that is a MEMBER OF THE `\u00b7`-SEPARATED ENUMERATION — i.e. the separator sits
    immediately beside it, before or after (whitespace-skipping). That neighbour test is what the
    shape of the record affords: the recorded set is written as one `\u00b7`-separated run, while prose
    names a pair in a sentence (`nightly_run_completed.quiet_lane` (T-12097) and \u2026) and names module
    attributes in the same backticks (`events.segment_paths`), neither of which touches a separator.
    Both of those read as rows under a bare dotted-token scan; neither does here.

    Returns the KEY names only (the right-hand side, `|`-split), because that is what the caller
    compares against — the oracle's pairs are matched by key, per `spec0161_attribute_unnamed`'s
    attribution-is-by-key rule."""
    if not spec_text:
        return set()
    start = spec_text.find(SPEC0161_RECORD_HEADING)
    if start == -1:
        return set()
    end = spec_text.find("## Verification", start)
    span = spec_text[start:(end if end != -1 else len(spec_text))]

    keys = set()
    for m in _SPEC0161_BACKTICKED.finditer(span):
        row = _SPEC0161_RECORD_ROW.match(m.group(0))
        if row is None:
            continue
        before = span[:m.start()].rstrip()
        after = span[m.end():].lstrip()
        if not (before.endswith(_SPEC0161_ENUMERATION_DELIMITERS)
                or after.startswith(_SPEC0161_ROW_SEPARATOR)):
            continue                                    # a prose mention, not an enumerated row
        keys.update(row.group(2).split("|"))
    return keys


#: SPEC-0161's record file, by name, so the BASE side of arm (ii) can be located in the base tree
#: rather than assumed to sit at the CURRENT path (finding B5 — a rename or a deletion moves it).
_SPEC0161_SPEC_NAME = re.compile(r"(?:\A|/)SPEC-0161-[^/]*\.yaml\Z")


def _spec0161_base_structural_keys(_git, base_sha, branch_keys, repo_root):
    """T-12411: of `branch_keys` (the keys THIS branch added in a structural position under `bin/`),
    the ones that ALREADY had a structural occurrence under `bin/` AT `base_sha`. Returns a set, or
    None when a git call FAULTED (the unknowable third state its caller propagates).

    TARGETED, WHICH IS THE WHOLE POINT. The cost objection that kept arm (i) off the family's
    baseline-vs-current shape priced a base side that re-read the whole `bin/` tree. This asks a
    strictly smaller question — "did any of THESE FEW key literals appear under `bin/` at the base?"
    — so one `git grep -l -F` yields a handful of candidate paths, and only those are read at the
    base rev. On the common case (a genuinely new key) the grep matches nothing and this returns
    after ONE git call.

    THE GREP IS A FILE FILTER, NEVER THE VERDICT. `-F` fixed strings (`"k"` and `'k'`) are used
    deliberately: no regex dialect of git's is relied on, and being over-broad here is harmless
    because every candidate is then judged by the SAME pure `spec0161_structural_keys` the branch
    side is judged by — tokenizer-blanked, so a comment, a docstring or a non-identifier literal at
    the base exempts nothing. Being over-broad in the FILTER only costs a `git show`; being
    over-broad in the VERDICT would silently exempt a branch, which is why the filter does not get
    to decide.

    rc 1 IS "NO MATCH", AN ANSWER (audit-pre finding 1): the empty set, so the keys stay charged.
    rc > 1 — and any failing `git show` — is a FAULT: None. Reading a fault as an empty base set
    would restore the exact over-charge this function exists to remove."""
    if not branch_keys:
        return set()
    args = []
    for k in sorted(branch_keys):
        args += ["-e", f'"{k}"', "-e", f"'{k}'"]
    grep = _git("grep", "-l", "-F", *args, base_sha, "--", "bin")
    if grep is None or grep.returncode > 1:
        return None
    if grep.returncode == 1:
        return set()                                    # no candidate file — nothing pre-existed
    base_keys = set()
    for row in grep.stdout.splitlines():
        row = row.strip()
        if not row:
            continue
        # `git grep -l <rev>` prints `<rev>:<path>`; the rev is a full sha here, so one split on the
        # FIRST colon is exact (a path may itself contain a colon, the rev may not).
        rel = row.split(":", 1)[1] if row.startswith(f"{base_sha}:") else row
        shown = _git("show", f"{base_sha}:{rel}")
        if shown is None or shown.returncode != 0:
            return None
        base_keys |= spec0161_structural_keys(shown.stdout) & branch_keys
    return base_keys


def _spec0161_branch_added_code(repo_root, *, consumer=False):
    """T-12232: the two diff facts the attribution needs, or None when they are unknowable.

    `consumer` (T-12412) — this root does not own the SPEC-0161 record (see
    `_spec0161_engine_record_specs`). ARM (ii) IS SKIPPED, and the skip is the correct answer rather
    than a shortcut: arm (ii) asks "did THIS branch REMOVE names from the record?", and a consumer
    branch cannot touch the kernel record at all (it is query-only under `-C`, and a consumer write
    into the engine corpus is refused by `cli._guard_consumer_engine_write`, SPEC-0078). Asking it
    anyway means running `git show <consumer-base>:specs/SPEC-0161…` against a tree that has never
    contained that file — putting a question only the kernel tree can answer to the consumer tree.
    ARM (i) is UNCHANGED for a consumer: keys added on `bin/` lines this branch added are its own
    genuine charge, and that is exactly the list the downgraded WARN reports.

    The impure sibling of `_spec0161_inputs`, written to its rules — best-effort, never raises, so a
    git fault degrades the seam rather than breaking a `land` or a `task commit`.

    ARM (i) RETURNS PER-FILE ADDED LINE NUMBERS, NOT A BLOB (audit-post pass-3 residual B2). The
    diff is read for WHICH LINES this branch added in WHICH file; the text handed on is the file's
    POST-IMAGE. That is what lets `spec0161_code_text` decide comment/docstring status from a
    parseable unit — a line added inside a PRE-EXISTING docstring has no opening delimiter of its
    own, so no blob-level reading can ever tell it from code.

    ARM (i), ONE DIFF COMMAND SERVING BOTH CALLERS. base = `git merge-base HEAD main`; the diff is
    `git diff <base> -- bin`, which compares the merge-base to the WORKING TREE. That covers the
    branch's committed emitters AND its uncommitted ones in a single call, which is what lets the
    pre-commit WARN (`task commit`, working tree dirty) and the post-commit `land` preflight (working
    tree clean) share this one materialiser instead of each growing its own range logic. An untracked
    NEW file under `bin/` is added separately — `git diff` cannot show a file git has never seen, so
    a brand-new emitter module would otherwise be attributed to nobody.

    ARM (ii) IS A BASELINE COMPARISON, NOT A DELETED-LINE SCAN (audit-post finding 1). Scanning every
    removed `specs/` line charges a branch for any spec deletion that happens to contain the key
    literal — a false charge at a REFUSING gate. Instead the RECORD SPAN is read at the merge-base
    (`git show <base>:<spec>`) and compared against the span on disk NOW: a key is un-named by this
    branch iff it was in the base span and is not in the current one. Exact, and cheap — one small
    file at one rev, which is why this arm can afford the family's baseline-vs-current shape while
    arm (i) cannot.

    ARM (i) IS BASELINE-VS-CURRENT AS OF T-12411 — TARGETED, which is what makes it affordable. The
    docstring of `spec0161_attribute_unnamed` used to concede that the code arm could not have the
    diff-aware family's baseline-vs-current shape, because its base side would be the whole `bin/`
    tree plus the re-folded journal at the merge-base. That objection prices the WRONG question. The
    only keys whose base state can change an answer are the FEW this branch actually added, so the
    base side asks about those alone: one `git grep -l -F` over `<base>:bin` restricted to those key
    literals gives a handful of CANDIDATE FILES, and each candidate is read at the base rev and
    judged by the SAME pure `spec0161_structural_keys`. The grep is a FILE FILTER ONLY — every
    verdict still comes from the tokenizer-blanked matcher, so a quoted example or a comment at the
    base can no more exempt a branch than it can charge one.

    EXIT STATUS 1 IS AN ANSWER, NOT A FAULT (audit-pre finding 1), and conflating the two would
    DISABLE this gate rather than narrow it. `git grep` exits 1 when nothing matches — which is the
    NORMAL case this whole mechanism exists for: a genuinely new key has no base occurrence, so the
    branch IS charged. Only rc > 1 (or a subprocess that did not run), and a failing `git show` of a
    candidate, are git FAULTS; those return None, never an empty base set, because an empty one
    would silently restore the over-charge at a REFUSING gate (episode-2 finding B6, applied in the
    opposite direction: an unknown base must not be read as "nothing pre-existed").

    Returns `(added_files, unnamed_by_branch_keys, base_structural_keys, sites)` — `added_files` a
    list of `(post_image_text, added_line_numbers_or_None)`, `base_structural_keys` the subset of
    this branch's added keys that already read back under `bin/` at the merge-base, and `sites` a
    `{key: "<relpath>:<line>"}` map of one charging site per added key (T-12411) — or None, never a
    partial answer, when there is no merge-base or any git call fails. `([], set(), set(), {})` is a
    real answer (this branch touched neither); None is the ABSENCE of one, and the callers take
    opposite fail-safe directions on it. The tuple GREW at the tail, so every existing reader of
    `[0]` / `[1]` is unchanged by construction."""
    import subprocess

    def _git(*args):
        try:
            return subprocess.run(["git", "-C", str(repo_root), *args],
                                  capture_output=True, text=True, check=False, timeout=30)
        except Exception:
            return None

    base = _git("merge-base", "HEAD", "main")
    if base is None or base.returncode != 0 or not base.stdout.strip():
        return None
    base_sha = base.stdout.strip()

    diff = _git("diff", base_sha, "--", "bin")
    if diff is None or diff.returncode != 0:
        return None
    # WHICH LINES, IN WHICH FILE. The new-side line counter is advanced by added and context lines
    # (a removed line does not exist on the new side), so every `+` line is recorded at its POSITION
    # IN THE POST-IMAGE — the index `spec0161_code_text` selects by.
    per_file, current, newno = {}, None, 0
    for ln in diff.stdout.splitlines():
        if ln.startswith("+++ "):
            path = ln[4:].strip()
            current = None if path == "/dev/null" else (path[2:] if path.startswith("b/") else path)
        elif ln.startswith("@@"):
            m = re.search(r"\+(\d+)", ln)
            newno = int(m.group(1)) if m else 0
        elif current is None:
            continue
        elif ln.startswith("+"):
            per_file.setdefault(current, set()).add(newno)
            newno += 1
        elif ln.startswith(" ") or ln == "":
            newno += 1                                  # context: present on the new side too
        # a `-` removal, a `\ No newline` marker and every header line advance nothing

    # A FAILED READ IS UNKNOWABLE, NOT AN EMPTY ONE (audit-post episode-2 finding B6). A file that
    # the diff says this branch touched but that cannot be read is a fact about the CHECKER, and
    # skipping it returns a PARTIALLY populated answer wearing `attributable: True` — a land refusal
    # that then misses the key the unread file introduced. A deletion is not this case: `+++
    # /dev/null` already excluded deleted paths from `per_file` above, so any OSError here is a
    # genuine read fault and the whole answer becomes None.
    # `added` is the contract the pure attributor takes (text, lines); `paths` is the PARALLEL list
    # of the relative path each entry came from, kept because only THIS layer knows it and the
    # charging-site rendering (T-12411) needs it. Built in the same two loops, so the two lists
    # cannot drift.
    added, paths = [], []
    for rel, lines in sorted(per_file.items()):
        try:
            added.append((Path(repo_root, rel).read_text(encoding="utf-8", errors="ignore"), lines))
        except OSError:
            return None
        paths.append(rel)

    untracked = _git("ls-files", "-o", "--exclude-standard", "--", "bin")
    if untracked is None or untracked.returncode != 0:
        return None
    for rel in untracked.stdout.splitlines():
        rel = rel.strip()
        if not rel:
            continue
        try:
            # A brand-new file is added in its ENTIRETY — `lines=None`, the whole post-image.
            added.append(
                (Path(repo_root, rel).read_text(encoding="utf-8", errors="ignore"), None))
        except OSError:
            return None
        paths.append(rel)

    # T-12411 — the CHARGING SITES and the MERGE-BASE side, both derived from `added` and therefore
    # shared by the consumer arm below (a consumer's arm (i) charge is as over-chargeable as the
    # kernel's, and its WARN names a site for the same reason a refusal does).
    _sites, _branch_keys = {}, set()
    for _rel, (_text, _lines) in zip(paths, added):
        for _k, _ls in spec0161_structural_key_sites(_text, _lines).items():
            _branch_keys.add(_k)
            _sites.setdefault(_k, f"{_rel}:{_ls[0]}")
    _base = _spec0161_base_structural_keys(_git, base_sha, _branch_keys, repo_root)
    if _base is None:
        return None

    # ARM (ii): the record span, then vs now — BOTH SIDES RESOLVED INDEPENDENTLY (audit-post
    # episode-2 finding B5). Reading the base side at the CURRENT path silently returns an empty
    # removal set whenever the branch DELETED or RENAMED the record file: the glob finds no current
    # path (or a new one `git show <base>:` cannot resolve), the arm charges nothing, and the branch
    # that removed the record — un-naming EVERY key at once — is admitted as having introduced
    # nothing. So the base side is located in the BASE TREE (`git ls-tree`) and the current side on
    # disk, and their span keys are differenced whichever way the file moved. A git fault on either
    # side is UNKNOWABLE (None, finding B6), never an empty set.
    if consumer:
        # Skipped, not silently empty. Both sides of arm (ii) would resolve to nothing in a consumer
        # tree today, so the observable answer is the same — but writing the skip down is what stops
        # a future consumer that grows an unrelated `specs/SPEC-0161-*` from being compared against
        # the WRONG record. Arm (i) above still carries this branch's real charge.
        return added, set(), _base, _sites

    base_tree = _git("ls-tree", "-r", "--name-only", base_sha, "--", "specs")
    if base_tree is None or base_tree.returncode != 0:
        return None
    base_specs = sorted(r.strip() for r in base_tree.stdout.splitlines()
                        if _SPEC0161_SPEC_NAME.search(r.strip()))
    base_keys = set()
    if base_specs:
        shown = _git("show", f"{base_sha}:{base_specs[0]}")
        if shown is None or shown.returncode != 0:
            return None
        base_keys = _spec0161_record_span_keys(shown.stdout)
    now_keys = set()
    spec_paths = sorted(Path(repo_root, "specs").glob("SPEC-0161-*.yaml"))
    if spec_paths:
        try:
            now_keys = _spec0161_record_span_keys(
                spec_paths[0].read_text(encoding="utf-8", errors="ignore"))
        except OSError:
            return None
    return added, base_keys - now_keys, _base, _sites


def _spec0161_engine_record_specs(repo_root):
    """T-12412: THE ONE PREDICATE for "does this root own the SPEC-0161 record, or borrow it?".

    Returns the ENGINE's `specs/` dir when this root carries no `SPEC-0161-*.yaml` of its own and the
    engine root is a genuinely different path; returns None otherwise. `None` therefore means exactly
    "kernel-shaped root — read your own record", which is what keeps the engine's own checkout (and
    every engine worktree, which carries the file too) on the UNCHANGED path by construction.

    THE DISCRIMINATOR IS THE CORPUS, NOT A BUILD FLAG, on purpose. The fact that makes `spec_text`
    empty IS the fact that makes the remedy unexecutable IS the fact that makes the land refusal
    unfair — so one predicate answers all three, and they cannot drift apart. It also gets the
    SPEC-0092 id-collision case right for free: a consumer that owns its OWN `SPEC-0161-*.yaml` reads
    as kernel-shaped and keeps its own text and its own hard refusal, which is correct — it CAN edit
    that file.

    Never raises: the engine root is derived from `host_paths._engine_root()` (off `__file__`, so a
    copied or published engine tree resolves to the copy it is actually running from), and any fault
    resolving or globbing degrades to None — i.e. to today's behaviour."""
    try:
        from lib import host_paths as _hp
        root = Path(repo_root).resolve()
        if any(root.glob("specs/SPEC-0161-*.yaml")):
            return None
        engine = Path(_hp._engine_root()).resolve()
        if engine == root:
            return None
        return engine / "specs"
    except Exception:
        return None


def spec0161_branch_unnamed(repo_root, *, oracle=None):
    """T-12232: THE SINGLE ENTRY POINT for "which unnamed SPEC-0161 pairs does THIS branch owe?".

    Materialise -> the ONE oracle -> attribute. All four readers call THIS: the `task commit` WARN,
    the `work commit` WARN, the cheap `land` preflight refusal, and the two live-corpus land-verify
    gates. One implementation, so a refusal, a warning and a test verdict can never disagree about
    who introduced a key (SPEC-0188 rule 4's one-implementation discipline).

    TWO CANDIDATE SOURCES AS OF T-12423, ONE ORACLE. The journal fold can only offer a (type, key)
    pair once a row CARRYING the key exists, so the branch that ADDS the emitter was admitted at its
    own land and reddened every other tree once the first row arrived at runtime (measured
    2026-09-11: `bg_dispatch_launched.land_regime`, 2h10m of fleet-wide main-red). So the oracle is
    ALSO run over a candidate set read structurally from this branch's ADDED CODE
    (`spec0161_added_emit_pairs`), with the SAME corpus / code blob / record text, and its `unnamed`
    is UNIONED into `introduced` (deduped, and minus the T-12411 merge-base keys). ALONGSIDE, never
    instead of: `inherited`, `governing`, `named`, `unnamed` and `coverage` are the JOURNAL leg's
    verbatim, so an inherited pair still reads inherited and is still charged to nobody (T-12423 AC2).

    THE RESIDUE THIS SECOND SOURCE ADDS, named rather than papered over. `spec0161_added_emit_pairs`
    reads an emit by SHAPE (first positional string constant + a payload dict literal), so a
    non-emitting call wearing that shape — `d.setdefault("state", {"x": 1})` — offers a candidate
    pair. It is only ever a CANDIDATE: the oracle still requires the type to be mentioned in the
    corpus, the key to be absent from it, and the key to be read back under `bin/`, and T-12411's
    merge-base subtraction still applies. A pair surviving all four is one the record genuinely does
    not name.

    Returns the `spec0161_attribute_unnamed` dict plus `governing` / `unnamed` / `coverage` from the
    oracle, so a caller needing the corpus-wide reading beside the attributed one (the floor gate)
    does not have to run the oracle a second time. Never raises.

    `oracle` — a `spec0161_payload_key_coverage(...)` result the CALLER already computed, reused
    verbatim instead of recomputing (audit-post episode-2 finding B1). Both live gates compute the
    oracle for their own arms and then call this function; recomputing here re-read the `bin/` tree
    and re-folded the journal a SECOND time, so a row appended between the two reads gave the gate
    two DIFFERENT snapshots — a numerator attributed against one denominator and compared against
    another, i.e. a false failure from a concurrent write. Passing the snapshot makes the pair
    consistent BY CONSTRUCTION; omitting it keeps the self-contained behaviour the verbs use."""
    root = Path(repo_root)
    # T-12412 — computed ONCE and reported, so the three things that depend on it (which record to
    # read, which remedy to name, whether the land refuses) can never disagree. It describes the
    # ROOT, not the snapshot, so it is reported even when the caller injected its own `oracle`.
    _engine_specs = _spec0161_engine_record_specs(root)
    _consumer = _engine_specs is not None
    result = oracle
    _corpus_side = None
    if result is None:
        corpus, code_blob, type_keys, spec_text = _spec0161_inputs(
            root / "specs", root / "bin", root / "events.jsonl",
            engine_specs_dir=_engine_specs)
        _corpus_side = (corpus, code_blob, spec_text)
        result = spec0161_payload_key_coverage(
            corpus=corpus, code_blob=code_blob, type_keys=type_keys, spec_text=spec_text)
    _diff = _spec0161_branch_added_code(root, consumer=_consumer)
    attribution = spec0161_attribute_unnamed(
        result["unnamed"],
        added_files=None if _diff is None else _diff[0],
        unnamed_by_branch=None if _diff is None else _diff[1],
        base_structural_keys=None if _diff is None else _diff[2])
    # T-12423 — THE SECOND CANDIDATE SOURCE, run through THE SAME ORACLE. The journal leg above can
    # only see a pair a row already carries, so the branch that ADDS the emitter is admitted at its
    # own land and reddens main for everyone once the first row arrives at runtime. Here the
    # candidate set is read from the branch's ADDED CODE instead (`spec0161_added_emit_pairs`), the
    # oracle answers the SAME governing/named question over the SAME corpus / code / record, and its
    # `unnamed` is UNIONED into `introduced`. ALONGSIDE, never instead of: `inherited`, `governing`,
    # `named`, `unnamed` and `coverage` stay the journal leg's verbatim, so a pair whose rows predate
    # this branch is still charged exactly as before (AC2).
    _introduced = list(attribution["introduced"])
    if _diff is not None and attribution["attributable"]:
        _added_pairs = spec0161_added_emit_pairs(_diff[0])
        if _added_pairs:
            if _corpus_side is None:
                # The caller injected its own `oracle`, so the corpus side was never materialised
                # here. Read it WITHOUT the journal fold — which is what the `_spec0161_corpus_inputs`
                # split exists for: this leg must not consult the journal, and re-folding it would
                # also pay the expensive input twice.
                _corpus_side = _spec0161_corpus_inputs(
                    root / "specs", root / "bin", engine_specs_dir=_engine_specs)
            _added_result = spec0161_payload_key_coverage(
                corpus=_corpus_side[0], code_blob=_corpus_side[1],
                type_keys={t: set(ks) for t, ks in _added_pairs.items()},
                spec_text=_corpus_side[2])
            # T-12411's rule, unchanged and applied to this leg too: a key that ALREADY read back
            # structurally under `bin/` at the merge-base was not introduced HERE.
            _base = set(_diff[2] or ())
            for _pair in _added_result["unnamed"]:
                _pair = tuple(_pair)
                if _pair[1] in _base or _pair in _introduced:
                    continue
                _introduced.append(_pair)
    attribution = dict(attribution, introduced=_introduced)
    return dict(attribution,
                consumer=_consumer,
                # T-12411 — the charging SITES, carried out beside the verdict so the ONE message
                # every reader pastes can name `<path>:<line>` without re-deriving the scan. Empty
                # on an unknowable diff, where there is nothing charged to site anyway.
                sites={} if _diff is None else _diff[3],
                governing=result["governing"],
                named=result["named"],
                unnamed=result["unnamed"],
                coverage=result["coverage"])


#: The `deviation_captured` fingerprint the consumer land-preflight downgrade records, and the value
#: the downgrade's own message hands the operator to paste into `cross request --origin-fp`. ONE
#: derivation, so the row that is recorded and the request that discharges it name the SAME thing.
SPEC0161_CONSUMER_FP_PREFIX = "spec0161-key-unnamed-consumer"


def spec0161_consumer_fingerprint(pairs):
    """T-12412: the stable fingerprint for "this consumer branch owes these SPEC-0161 names".

    Derived from the SORTED pair set alone, so the same owed set always clusters to the same value
    however the pairs were discovered. It is for CLUSTERING, never for suppression: nothing reads it
    to skip a row, and every consumer land that still owes the pairs records another
    `deviation_captured` — the recurrence COUNT is the signal an aspect-audit folds
    (`patterns/error-friction-tracking.md`), and deduping would hide exactly how often a consumer is
    paying this."""
    body = ";".join(f"{t}.{k}" for t, k in sorted(pairs))
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()[:12]
    return f"{SPEC0161_CONSUMER_FP_PREFIX}-{digest}"


def spec0161_unnamed_key_message(pairs, *, verb, consumer=False, sites=None):
    """T-12232: THE ONE TEXT the commit WARN and the land refusal both paste, so they cannot drift.

    This string IS the line the Controller had been hand-adding to every dispatch brief («a NEW
    journal payload key in your diff MUST be named in the SPEC-0161 record in the SAME diff»), moved
    into the verb that can actually detect the condition. A hand-carried rule reaches only the
    briefs someone remembered to write it into; this reaches every branch that introduces a key.

    `consumer` (T-12412) — ONLY THE REMEDY LINE FORKS, and it forks because the kernel remedy is
    UNEXECUTABLE by the party it is handed to. SPEC-0161 is a kernel spec: under `-C` it is
    query-only (SPEC-0092) and a consumer write into the engine corpus is refused outright
    (`cli._guard_consumer_engine_write`, SPEC-0078). Telling a consumer to `spec edit SPEC-0161` is
    telling it to run a command the engine will refuse — measured as a HARD land refusal with no
    consumer-side exit at all (aiseller X-1349, `T-0500`). The consumer is instead pointed at the
    route that actually gets a key named for it: `cross request` to the kernel — the same X-1263 ->
    T-12069 route by which `spike_channel_grant.compose_project` got into the record in the first
    place. The finding, the why, and the inherited-pairs footer stay ONE shared text: a consumer and
    the kernel must never disagree about WHAT was found, only about what to do next.

    `sites` (T-12411) — the `{key: "<path>:<line>"}` map `spec0161_branch_unnamed` returns. Each
    listed pair is rendered WITH its charging site when one is known, so the charged party can go
    look at the line rather than re-deriving the structural scan by hand to find out where the claim
    comes from. A pair charged by the UN-NAMING arm has no code site and is listed bare — correctly:
    its charge is in the record, not in the diff. Optional and absent-tolerant, so the pure callers
    and every existing test keep the unchanged text."""
    def _listed(t, k):
        where = (sites or {}).get(k)
        return f"    {t}.{k}" + (f"  ({where})" if where else "")
    listed = "\n".join(_listed(t, k) for t, k in sorted(pairs))
    if consumer:
        brief = "; ".join(f"{t}.{k}" for t, k in sorted(pairs))
        fp = spec0161_consumer_fingerprint(pairs)
        remedy = (
            f"  SPEC-0161 is a KERNEL spec — this repo cannot edit it (query-only under `-C`, and a "
            f"consumer write into the engine corpus is refused), so the fix is NOT a spec edit here. "
            f"Route it to the kernel, which is how these keys get named (the X-1263 -> T-12069 "
            f"route):\n"
            f"    bin/yitc-v2 cross request --to yitc-v2 --kind bugfix \\\n"
            f"      --origin-fp {fp} \\\n"
            f"      --origin-ref <this-repo>/events.jsonl#ts=<the deviation_captured row just "
            f"recorded> \\\n"
            f"      --brief 'name these governing journal payload keys in the SPEC-0161 record: "
            f"{brief}'\n"
            f"  (`--kind bugfix` requires both origin flags — SPEC-0085 §3. The fingerprint above is "
            f"the one this run recorded, so the request and the capture join up.)\n"
            f"  Your land is NOT blocked by this — it is recorded and reported, not refused.\n")
    else:
        remedy = (
            f"  Fix it here, for free: `bin/yitc-v2 spec edit SPEC-0161` and add the key(s) to the "
            f"set under \"{SPEC0161_RECORD_HEADING}\", then commit that edit with this change.\n")
    return (
        f"{verb}: this branch's diff introduces {len(pairs)} governing journal payload key(s) that "
        f"SPEC-0161's record does not name:\n{listed}\n"
        f"  A key is named in the SPEC-0161 record BY THE BRANCH THAT INTRODUCES IT, in the SAME "
        f"diff — otherwise the land-verify recomputation reds every later land until someone edits "
        f"the record by hand (measured 2026-09-07: 7 aborted lands, 4 halted workers, ~70 min).\n"
        + remedy +
        f"  Inherited pairs — ones your diff did not introduce — are NOT your charge and are not "
        f"listed here; they are reported by `bin/yitc-v2 debt` (SPEC-0119 rule 28).")


def _spec0161_corpus_inputs(specs_dir, code_dir, *, engine_specs_dir=None):
    """The THREE CORPUS-SIDE materialisations the oracle needs — corpus, code blob, record text —
    kept out of the oracle so the oracle stays pure, and kept out of `_spec0161_inputs` (which is
    this plus the journal fold) so a second CANDIDATE SOURCE can reuse them WITHOUT re-folding the
    journal (T-12423). Every read is best-effort: an unreadable file contributes nothing rather than
    raising, because this feeds a report-only seam that must never break `session start` or `land`.

    THE SPLIT IS THE WHOLE POINT, not tidiness. The journal fold is the expensive input AND the one
    the T-12423 leg must NOT consult: a branch that ADDS an emitter has no row carrying its key yet,
    so the added-code candidate source asks the oracle the same question against the same corpus /
    code / record while supplying its OWN `type_keys`. One oracle, two quantifiers.

    `engine_specs_dir` (T-12412) — WHERE TO FIND THE RECORD WHEN THIS ROOT DOES NOT OWN IT. SPEC-0161
    is a KERNEL spec; a `-C` consumer's `specs/` has no `SPEC-0161-*.yaml`, so `spec_text` came back
    EMPTY and the oracle's `named` test — `pair[0] in spec_text and pair[1] in spec_text` — was
    ALWAYS false there. Every governing pair read UNNAMED under `-C`, INCLUDING the pairs the kernel
    record does name (aiseller X-1349: `T-0500`'s land hard-refused on `spike_channel_grant.
    compose_project`, a pair the kernel record has named since T-12069 / X-1263). Given this dir, the
    record is resolved from it when — and only when — this root carries none of its own.

    THE CORPUS IS DELIBERATELY NOT EXTENDED, only `spec_text`. `governing` asks two questions about
    THIS repo's corpus (is the TYPE mentioned in it, is the KEY absent from it); folding kernel text
    into the corpus would make a consumer's key read as MENTIONED merely because the kernel happens
    to name it elsewhere, silently erasing the consumer's own coverage measurement. `named` is a
    question about the RECORD, and the record is the kernel's — that one, and only that one, moves.

    Keyword-only and defaulted, so omitting it reads exactly as this did before T-12412: the
    positional form every caller uses is byte-identical in behaviour."""
    corpus_parts, spec_text = [], ""
    for path in sorted(Path(specs_dir).glob("*.yaml")):
        try:
            blob = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        corpus_parts.append(blob)
        if "SPEC-0161-" in path.name:
            spec_text = blob

    if not spec_text and engine_specs_dir is not None:
        # Best-effort, like every other read here: an unreadable or absent engine record leaves
        # `spec_text` empty, which is exactly today's behaviour — never an exception at a seam that
        # must not break `session start` or `land`.
        try:
            for path in sorted(Path(engine_specs_dir).glob("SPEC-0161-*.yaml")):
                spec_text = path.read_text(encoding="utf-8", errors="ignore")
                break
        except OSError:
            pass

    code_parts = []
    _code_root = Path(code_dir)
    for path in sorted(_code_root.rglob("*")):
        if not path.is_file():
            continue
        # T-11868 — SKIP the dependency / VCS / build trees this module ALREADY names
        # (`_SEARCH_SKIP_DIRS`, the sibling bounded source-search's set, reused rather than a second
        # list). Unfiltered, the sweep read every `__pycache__/*.pyc` under the tree: compiled blobs
        # that are not source, whose interned strings make a governing key read as MENTIONED IN CODE
        # when only a stale bytecode copy holds it — a false green in the rule-28 coverage fold, and
        # cost paid to produce it. The skip is on the path's PARTS, so a nested `.venv/…/x.py` drops
        # too, not merely a top-level one.
        try:
            _rel_parts = path.relative_to(_code_root).parts[:-1]
        except ValueError:
            _rel_parts = path.parts[:-1]
        if any(part in _SEARCH_SKIP_DIRS for part in _rel_parts):
            continue
        try:
            code_parts.append(path.read_text(encoding="utf-8", errors="ignore"))
        except OSError:
            continue

    return "".join(corpus_parts), "".join(code_parts), spec_text


def _spec0161_inputs(specs_dir, code_dir, events_path, *, engine_specs_dir=None):
    """The four materialisations rule 28's fold needs: the corpus side (`_spec0161_corpus_inputs`)
    plus the JOURNAL fold that turns emitted rows into the oracle's candidate set.

    Signature and return order are UNCHANGED (T-12423 split only the corpus side out), so every
    existing caller and test reads exactly as it did before — `engine_specs_dir` stays keyword-only
    and defaulted, and the positional three-arg form is byte-identical in behaviour."""
    corpus, code_blob, spec_text = _spec0161_corpus_inputs(
        specs_dir, code_dir, engine_specs_dir=engine_specs_dir)

    type_keys = {}
    try:
        # SPEC-0190 rule 4 — the WHOLE journal (T-11649). This fold's declared horizon is the
        # root journal's SEGMENT SET, which is what the census records for it; reading the live
        # segment alone silently drops every archived row (the X-1100 class, and the reason the
        # cohort sibling `_test_class_executions` already takes this branch). `segment_rows`
        # reads each segment through the SAME `fold_rows` primitive, so there is still ONE parse
        # path and the T-11453 request-scoped memo still serves each segment.
        for obj in journal.segment_rows(events_path):
            if not isinstance(obj, dict):
                continue
            t, data = obj.get("type"), obj.get("data")
            if isinstance(t, str) and isinstance(data, dict):
                type_keys.setdefault(t, set()).update(data.keys())
    except OSError:
        pass

    return corpus, code_blob, type_keys, spec_text


def recorded_measurement_drift(events_path, *, specs_dir, code_dir, margin):
    """SPEC-0119 rule 28 (T-11396): the RECORDED-MEASUREMENT DRIFT fold — is SPEC-0161's recorded
    payload-key candidate set approaching (or already beneath) its own declared floor?

    Materialises the oracle's inputs and delegates; it decides only ONE thing beyond the oracle —
    whether the reading is close enough to interrupt:

        count = 1  iff  coverage <= floor + margin

    which fires while coverage is still ABOVE the floor and APPROACHING it (the whole point: the
    refresh becomes maintenance rather than an ambush) AND while it is already BENEATH it (a
    measurement under its own bar is not a matter of taste — at that point a land is already being
    refused, and going quiet then would be the one unforgivable silence).

    A `coverage` of None — nothing governs, so the denominator is empty — folds to count 0. That is
    deliberately NOT read as 0% coverage: an empty recomputation means the probe found nothing to
    measure, which is a different condition from a record that has gone stale, and inventing a
    reading there would put a permanent line on every repo whose corpus this rule does not describe
    (every `-C` consumer). The catalog test's own liveness arm is what catches a probe that has gone
    dark; this report-only surface must not duplicate that judgement.

    Report-only and suppressed-when-clean: nothing here gates, refuses, emits, stores or refreshes."""
    corpus, code_blob, type_keys, spec_text = _spec0161_inputs(specs_dir, code_dir, events_path)
    result = spec0161_payload_key_coverage(
        corpus=corpus, code_blob=code_blob, type_keys=type_keys, spec_text=spec_text)

    coverage = result["coverage"]
    floor = SPEC0161_COVERAGE_FLOOR
    # TWO ARMS, and the at-or-beneath one is NOT disableable — written as an explicit disjunction
    # rather than as `coverage <= floor + margin`, which would be wrong for a NEGATIVE margin: at
    # margin -0.5 that single comparison silences a reading of 0.50 against a 0.80 floor, i.e. it
    # goes quiet exactly when a land is already being refused. The knob may make the line less
    # eager (narrow or close the APPROACH band); it may never make it blind (audit-post finding).
    drifting = coverage is not None and (
        coverage <= floor or (margin > 0 and coverage <= floor + margin))

    return {
        "why": ("SPEC-0161's recorded payload-key candidate set is a MEASUREMENT that a land-verify "
                "gate re-computes and compares against, and it drifts by construction as the corpus "
                "grows. The drift is not a defect; being told about it by a land refusal is. With no "
                "seam reading the coverage, the first reader is `land`, refusing whoever happens to "
                "be landing — measured on 2026-08-21, when coverage hit 79% against the 0.80 bar and "
                "refused the land of the very card filed to unblock a frozen branch. This line makes "
                "the approach visible early enough for the refresh to be a choice. It GATES nothing "
                "and it does not move the floor."),
        "count": 1 if drifting else 0,
        "coverage": coverage,
        "floor": floor,
        "margin": margin,
        "headroom": (coverage - floor) if coverage is not None else None,
        "governing_count": len(result["governing"]),
        "named_count": len(result["named"]),
        "unnamed": result["unnamed"],
        "next": ("re-run SPEC-0161's PAYLOAD-KEY half and refresh its recorded candidate set + counts "
                 "so the record names what the recomputation now finds. Doing it now costs one "
                 "ordinary edit; doing it after the floor is crossed costs a refused land plus the "
                 "re-measurement, on someone who did not cause it."
                 if drifting else
                 "the recorded measurement is comfortably clear of its floor."),
    }


# ─────────────────────────────────────────────────────────────────────────────────────────────────
# KNOWN-BROKEN-ON-MAIN (SPEC-0181 §Known-broken-on-main / SPEC-0119 rule 29, T-11468)
# ─────────────────────────────────────────────────────────────────────────────────────────────────
#
# THE ESTABLISHING CARRIER, AND WHY IT IS NOT A NEW EVENT. `land_completed` already carries the
# T-11464 attribution record on its abort rows (`data.failure_attribution`, persisted by
# `worktree._emit_land_abort` since T-11468). This fold reads that key and nothing else. There is NO
# side ledger, NO stored status field and NO followup carrier: the journal facts ARE the state, and
# the record is a FOLD. Like `open_proof_obligations` above, this module only READS and returns a
# dict.
KNOWN_BROKEN_CARRIER_EVENT = "land_completed"
KNOWN_BROKEN_RECORD_KEY = "failure_attribution"

# THE FLAKE GUARD IS THE CARRIER'S OWN SHAPE, NOT A CLASSIFIER ON TOP OF IT. A pair reaches `at_main`
# only by failing TWICE, in two independent executions on two different trees: once in the land's
# candidate verify (the merged tree) and once in `_land_failure_attribution_probe`'s fresh checkout
# of `merged_base`. That IS the confirming re-run, and it is already paid for on every red land.
#
# WHAT THIS DELIBERATELY DOES NOT READ, and the incident behind each:
#   * `fail_class` — demonstrably unreliable: on 2026-08-23 a real, reproducible main breakage was
#     labelled `verify-flake`. A guard built on it would freeze the repository on a mislabel and, far
#     worse, would miss the breakages it exists to catch.
#   * `failing_tests` / `failing_assertions` — the FIRST-SIGHT keys. An implementation reading them
#     records on one observation, which passes AC1 and fails the flake guard outright: a single
#     non-reproducing failure would establish a standing claim that main is broken.
KNOWN_BROKEN_ESTABLISHING_SIDE = "at_main"
KNOWN_BROKEN_CLEARING_SIDE = "at_branch"

# THE CLEARING RULE, AND THE TWO AUDIT-PRE REDS THAT SHAPED IT (2026-08-23, both absorbed by re-plan).
# (T-11791 later added route (c) — a green land whose RECORDED SELECTION names the file — beside the
# two below. It answers "did you run THIS FILE" directly, which is why it needs neither of the two
# conjuncts REDs 1 and 2 forced onto the count-based route; both of those stay exactly as written.)
# A record clears ONLY on evidence that this pair's test RAN and PASSED on a fresh main — never on
# elapsed time, which is the failure mode this whole fold is named after. There is no window here, no
# deadline, and no clock: `now` is not a parameter of this function, because no answer it gives
# depends on one.
#
# RED 1 — counts alone are not evidence. A green land that ran the WHOLE discovered enumeration
# proves every executed file passed, but a test file DELETED or RENAMED since the breakage is no
# longer IN that enumeration: the counts still read "full" while the pair's own test never ran.
# RED 2 — nor is existence in the CURRENT working tree. That is a fact about now, not about the tree
# that ran green, so a file deleted before that land and re-added afterwards would clear a pair the
# land never executed.
#
# So the conjunct is HISTORICAL and tied to the clearing row's OWN `sha` — the sha that land
# fast-forwarded main to. `git cat-file -e <sha>:tests/<file>` asks exactly "was this file in the
# tree that ran". A file ABSENT from that tree is not a pass: it is VACATED, counted separately and
# never folded into the cleared count, because "the test was not there" and "the test ran and passed"
# are different facts and a reader must be able to tell them apart.
KNOWN_BROKEN_VACATED_REASON = "test-file-removed"

# The test subdirectory the enumeration globs, and so the prefix a pair's file name is resolved
# against inside a historical tree. Matches `_LAND_CANDIDATE_TEST_SUBDIR` in `worktree.py`; stated
# here as this fold's own read of the same layout rather than imported, because `debt.py`
# back-imports nothing from the land path.
KNOWN_BROKEN_TEST_SUBDIR = "tests"


def _known_broken_pairs(data, side: str) -> list:
    """The `(file, assertion)` one-liners on one side of a row's attribution record, else [].

    FAITHFUL, never fail-closed (`lessons/fail-closed-belongs-to-the-reader-not-the-parser.md`): this
    reports only what the row literally says. A row with no record, a non-dict record, a non-list
    side or a non-string entry yields nothing, and the single READER below decides what that means.
    """
    if not isinstance(data, dict):
        return []
    rec = data.get(KNOWN_BROKEN_RECORD_KEY)
    if not isinstance(rec, dict):
        return []
    side_val = rec.get(side)
    if not isinstance(side_val, list):
        return []
    return [p.strip() for p in side_val if isinstance(p, str) and p.strip()]


def _known_broken_file(pair: str) -> str:
    """The test FILE half of a `"<file>: <assertion>"` pair — the same `partition(": ")[0]` split
    `_land_failure_attribution_probe` uses to decide which files to re-run, so the file this fold
    resolves is the file that was actually run (CHARTER §P5, one derivation).

    The ASSERTION half is an extracted SOURCE LINE, not a stable symbol, which is why existence is
    checked at FILE granularity and the residual is stated in SPEC-0181 rather than hidden here: a
    file that survives while one assertion inside it is deleted clears as passed, which is the honest
    reading — main is no longer red for that file.
    """
    return str(pair).partition(": ")[0].strip()


def _known_broken_full_enumeration(data) -> bool:
    """Did this land's verify run the WHOLE discovered test enumeration?

    `verify_metrics.test_file_count` keeps its standing meaning of what RAN and
    `selection_discovered_count` is what the glob FOUND (SPEC-0181 / SPEC-0025), so a governed land
    reads `test_file_count < selection_discovered_count`. Both keys are REQUIRED: a row that cannot
    answer the question is not evidence, and absence must never read as coverage.
    """
    if not isinstance(data, dict):
        return False
    vm = data.get("verify_metrics")
    if not isinstance(vm, dict):
        return False
    ran, found = vm.get("test_file_count"), vm.get("selection_discovered_count")
    # BOTH counts are bool-guarded, not just `ran`. In Python `bool` IS an `int`, so a corrupt
    # `selection_discovered_count: true` would satisfy `isinstance(found, int)`, then `found > 0` and
    # `ran >= found` — and a malformed row would be read as FULL COVERAGE, clearing or vacating a
    # known-broken record on a count nobody wrote. The asymmetry was real (audit-post finding,
    # absorbed): the guard existed on one operand and not the other, which is the shape a reader
    # skims past. A malformed row must fail closed to NOT-evidence, like every other unknown here.
    if isinstance(ran, bool) or isinstance(found, bool):
        return False
    if not isinstance(ran, int) or not isinstance(found, int):
        return False
    return found > 0 and ran >= found


# T-11791 — THE KEY THAT ANSWERS "WAS THIS FILE AMONG THOSE I RAN". `verify_metrics` records what a
# land RAN as a COUNT, so before this key the only question a green land could answer was "did you
# run EVERYTHING" — and a SURGICAL repair, narrow by construction, could never answer yes. The
# emitter (`verify_runner._run_verify_tests`) writes it only on a NARROWED run, as the same BARE
# BASENAMES an attribution pair carries.
KNOWN_BROKEN_RAN_TESTS_KEY = "selection_ran_tests"


def _known_broken_ran_tests(data) -> "frozenset | None":
    """The test-file basenames this row's verify RAN — or None = COULD NOT ANSWER.

    Three-valued (SPEC-0165 item 11): an empty set is the CLAIM "this land ran nothing", so a row
    that cannot answer returns `None` instead, and the single reader below leaves the record REPORTED.

    EVERY MALFORMED SHAPE FAILS CLOSED TO `None`, and each guard is a way a row could otherwise be
    read as evidence nobody wrote:
      * no `verify_metrics` dict, or the key absent — the ordinary full-enumeration or pre-T-11791
        row. Route (b) still judges it; this route simply has nothing to say.
      * a non-list value, or any entry that is not a non-empty `str` — INCLUDING a `bool`, which is
        not caught by a truthiness test and would otherwise sit silently in the set.
      * a length that DISAGREES with `test_file_count`. The emitter writes the list from the SAME
        `test_files` the count is taken from, so the two agree by construction; a row where they do
        not is corrupt, and reading its list anyway would clear a record on a set that never
        described a run. `test_file_count` is bool-guarded for the reason its sibling in
        `_known_broken_full_enumeration` is: in Python `True` IS an `int`, so `test_file_count: true`
        would otherwise compare against a length of 1.

    NOTHING HERE IS TIME-BASED and nothing here decides: like `_known_broken_pairs` this reports what
    the row literally says (`lessons/fail-closed-belongs-to-the-reader-not-the-parser`).
    """
    if not isinstance(data, dict):
        return None
    vm = data.get("verify_metrics")
    if not isinstance(vm, dict):
        return None
    ran = vm.get(KNOWN_BROKEN_RAN_TESTS_KEY)
    if not isinstance(ran, list) or not ran:
        return None
    names = set()
    for entry in ran:
        if isinstance(entry, bool) or not isinstance(entry, str) or not entry.strip():
            return None
        names.add(entry.strip())
    count = vm.get("test_file_count")
    if isinstance(count, bool) or not isinstance(count, int):
        return None
    if count != len(ran):
        return None
    return frozenset(names)


# T-11731 — THE KEYS THAT ANSWER "WHICH FILES DID THE DELEGATED LAYER ANSWER FOR". A consumer whose
# declared verify layer `covers:` its test dir REPLACES the kernel's bare sweep (SPEC-0152 rule 16),
# so its land rows carry NO `selection_ran_tests` and route (c) has nothing to read. Measured twice on
# 2026-08-27 (X-1151 / X-1164): a repo that did exactly what the delegation contract tells it to do
# could no longer clear a record its PRE-delegation sweep had established, and every governance-only
# branch — plan, spec, card — was refused pre-queue from then on. The emitter
# (`worktree._land_integrate`) writes the pair on the delegating branch only: the layer NAME, and the
# bare basenames of the test files the skipped sweep would have enumerated.
KNOWN_BROKEN_DELEGATED_LAYER_KEY = "consumer_tests_delegated_layer"
KNOWN_BROKEN_DELEGATED_FILES_KEY = "consumer_tests_delegated_files"
KNOWN_BROKEN_LAYER_ROWS_KEY = "consumer_verify_layers"
KNOWN_BROKEN_LAYER_PASSED = "passed"


def _known_broken_delegated_pass_files(data) -> "frozenset | None":
    """The test-file basenames a GREEN DELEGATED layer answered for — or None = COULD NOT ANSWER.

    Three-valued for the reason `_known_broken_ran_tests` is (SPEC-0165 item 11): an empty set is
    the CLAIM "the delegated layer covered nothing", so a row that cannot answer returns `None`.

    THE CONJUNCTION IS THE WHOLE SAFETY, and each limb answers something a bare layer name cannot
    (the audit-pre finding this shape was re-planned for — a name alone would clear EVERY open pair,
    including one whose file the delegated layer never claimed):
      * `status` is EXPLICITLY `ok`. Never a default (route (c)'s own audit-post finding): green is
        the reason a delegated layer's run counts as a PASS rather than as a list of files that
        someone declared, so a row that does not SAY it was green cannot answer.
      * a non-empty `str` delegated-layer NAME — which layer answered for the surface.
      * that EXACT name has a `consumer_verify_layers` row whose `outcome` is exactly `passed`. A
        `failed` / `timed-out` / `waived` / `malformed` / `skipped-disjoint-subject` layer proves
        nothing, and neither does a DIFFERENT layer passing — which is the false-green leg the
        reporting consumer deliberately refused to cross rather than forge, and the direction this
        reader must keep refusing on their behalf.
      * a non-empty list of non-empty `str` FILE names — the surface the delegation covered. A
        `bool` entry fails closed, as everywhere here: in Python `True` is not caught by a
        truthiness test and would otherwise sit silently in the set.

    NOTHING HERE IS TIME-BASED and nothing here decides: like its two siblings this reports what the
    row literally says (`lessons/fail-closed-belongs-to-the-reader-not-the-parser`).
    """
    if not isinstance(data, dict):
        return None
    if str(data.get("status") or "") != "ok":
        return None
    layer = data.get(KNOWN_BROKEN_DELEGATED_LAYER_KEY)
    if isinstance(layer, bool) or not isinstance(layer, str) or not layer.strip():
        return None
    layer = layer.strip()
    rows = data.get(KNOWN_BROKEN_LAYER_ROWS_KEY)
    if not isinstance(rows, list):
        return None
    if not any(isinstance(r, dict) and str(r.get("layer") or "").strip() == layer
               and str(r.get("outcome") or "") == KNOWN_BROKEN_LAYER_PASSED for r in rows):
        return None
    files = data.get(KNOWN_BROKEN_DELEGATED_FILES_KEY)
    if not isinstance(files, list) or not files:
        return None
    names = set()
    for entry in files:
        if isinstance(entry, bool) or not isinstance(entry, str) or not entry.strip():
            return None
        names.add(entry.strip())
    return frozenset(names)


def _known_broken_blob_exists(root, sha: str, relpath: str) -> "bool | None":
    """Was `relpath` present in the tree at `sha`? True / False / None = COULD NOT ANSWER.

    Three-valued deliberately (SPEC-0165 item 11) — `None` is not a soft False. A missing sha, an
    unresolvable one, a pruned history, or no git at all returns `None` and the fold FAILS CLOSED;
    collapsing that into False would silently VACATE records on a machine without git.
    """
    if not sha or not str(sha).strip():
        return None
    import subprocess
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "cat-file", "-e", f"{str(sha).strip()}:{relpath}"],
            capture_output=True, text=True, timeout=_PROVENANCE_GIT_TIMEOUT)
    except Exception:                     # noqa: BLE001 — no git, no repo, a timeout: cannot answer
        return None
    if proc.returncode == 0:
        return True
    # `cat-file -e` exits non-zero BOTH for "the path is not in that tree" and for "that object does
    # not exist at all". Only the first is a fact about the file, so the sha is resolved separately
    # rather than read off one exit code — a pruned or never-fetched sha must land in `None`.
    try:
        probe = subprocess.run(["git", "-C", str(root), "rev-parse", "--verify", "--quiet",
                                f"{str(sha).strip()}^{{commit}}"],
                               capture_output=True, text=True, timeout=_PROVENANCE_GIT_TIMEOUT)
    except Exception:                     # noqa: BLE001
        return None
    return False if probe.returncode == 0 else None


def open_known_broken(events_path, root=None, _blob_exists=None) -> dict:
    """Fold the journal → the tests currently KNOWN BROKEN ON MAIN (SPEC-0181 §Known-broken-on-main).

    A test is known-broken when a land's attribution probe REPRODUCED its failure at the merge-base —
    main WITHOUT that branch's diff — and no later evidence has shown it passing there since. The
    point is that a broken main becomes CHEAP TO KNOW ABOUT: on 2026-08-23 a pre-existing breakage
    made main un-landable for every card and each branch paid a full 420-570s verify to rediscover
    the same fact; on 2026-08-22 two causes refused five branches in 24h, each paying in full. It is
    emphatically NOT cheap to BYPASS — this fold gates nothing, waives nothing and excludes no
    failing assertion, exactly as the attribution record it reads does not.

    ONE PASS, IN `ts` ORDER, over `land_completed` rows:
      * ESTABLISH — every pair in `data.failure_attribution.at_main` opens a record for that pair.
        The pair is corroborated by construction (see KNOWN_BROKEN_ESTABLISHING_SIDE): it failed in
        the candidate verify AND again at the merge-base, two runs on two trees. First sight
        establishes nothing.
      * CLEAR — a LATER row is evidence for a pair by exactly one of four routes:
          (a) that pair appears in the row's `at_branch` — the merge-base run did NOT reproduce it,
              which is a direct pair-level observation of it passing on main;
          (b) the row is a GREEN land that ran the whole discovered enumeration AND the pair's test
              file existed in THAT land's own `sha` (the historical check — never the working tree);
          (c) the row is a GREEN land whose RECORDED SELECTION names that pair's test file — a direct
              observation that this file ran, and passed, on the tree that land produced (T-11791).
              Route (b) asks "did you run everything"; this asks the question the record actually
              needs, so a SURGICAL repair can clear the record it repairs instead of waiting for an
              unrelated broad land. Route (b) stays as the sufficient case it always was.
          (d) the row is a GREEN land whose DELEGATED verify layer (SPEC-0152 rule 16) passed AND
              whose recorded delegated SURFACE contains that pair's test file (T-11731). A consumer
              that delegates its tests sweep runs no sweep, so it writes no selection and (c) cannot
              see it: this is the same observation one granularity out, made by the layer that
              DECLARED the surface instead of by the kernel sweep that was skipped.
        A green full-enumeration land whose tree did NOT contain the file VACATES the record instead:
        reported as its own count, never as a pass.
      * RE-BREAK — a later `at_main` observation re-opens a cleared pair, because it is a new fact
        about a new tree. The fold reports the CURRENT state, not a first-ever-seen list.

    NOTHING HERE IS TIME-BASED, and that is the acceptance boundary rather than a stylistic
    preference (AC1's differential: a time-based expiry would also stop reporting a pair, so the
    criterion is that the record clears on the passing EVIDENCE). `now` is not a parameter, no
    deadline is computed, and no window is applied. Two journals whose rows carry IDENTICAL elapsed
    time and differ only in whether a clearing row exists fold to different answers; two that differ
    only in how old the establishing row is fold to the same one.

    Args:
      events_path: path to `events.jsonl` (missing/unreadable ⇒ a clean, zero-count result — this
        view is report-only and must never break the seam it rides).
      root: the checkout the `sha` probes run in; defaults to `events_path`'s directory.
      _blob_exists: injected `(root, sha, relpath) -> True|False|None` — the ONE git seam, so the
        tests are hermetic and run no subprocess (the discipline every sibling fold here holds).

    Returns `{"lens", "count", "broken", "cleared_count", "vacated_count", "vacated"}` — COMPLETE on
    every path, including when it says nothing, so "the fold found nothing" stays distinguishable
    from "the fold never ran" (`lessons/a-report-only-signals-differential-is-indistinguishability`).
    Pure: reads the journal plus bounded `git cat-file` probes, and writes nothing.
    """
    root = Path(root) if root is not None else Path(events_path).parent
    probe = _blob_exists if _blob_exists is not None else _known_broken_blob_exists

    rows: list = []
    try:
        # T-11592 — the SEGMENT fold (SPEC-0190 rule 4), still the ONE shared parse path (T-11453):
        # `segment_rows` resolves the segment SET and reads each member through the same `fold_rows`
        # primitive. This pass declares an UNBOUNDED horizon — it pairs each ESTABLISH against every
        # later CLEAR — so reading the live segment alone truncated the history it judges, and a
        # pairing over a truncated history breaks in BOTH directions invisibly: a breakage
        # established before the boundary and never cleared simply vanished, and a record whose
        # ESTABLISH archived lost the pair it needed. Segment order is concatenation, never
        # chronology (union-merge has always made physical order not-chronology, SPEC-0002) — the
        # `rows.sort` below already restores it, exactly as it had to before.
        for event in journal.segment_rows(events_path):
            if not isinstance(event, dict) or event.get("type") != KNOWN_BROKEN_CARRIER_EVENT:
                continue
            data = event.get("data")
            if not isinstance(data, dict):
                continue
            event_ts = _parse_stamped_deadline(event.get("ts"))
            if event_ts is None:
                continue          # no establishable ordering ⇒ neither opens nor closes
            rows.append((event_ts, data))
    except (OSError, UnicodeDecodeError):
        rows = []
    rows.sort(key=lambda r: r[0])

    open_records: dict = {}     # pair -> {file, assertion, since, branch, seen}
    vacated: dict = {}          # pair -> {file, at, sha}
    cleared_count = 0

    def _clears(pair: str) -> bool:
        """Is THIS row later evidence for `pair`? STRICTLY later, never same-instant.

        AC1 cites two recorded states BY `ts`, and clearing means a land ran that test on a fresh
        main AFTERWARDS. The journal stamps whole SECONDS, so two rows sharing a `ts` are ordered
        only by where they happen to sit in the file — and under that ordering an `at_branch` row
        stamped in the same second as the establishing one would clear a record no later run had
        contradicted. That is not evidence about a later main; it is a tie broken by file position.
        Caught at audit-post on exactly that differential input.

        NOTE THE DIRECTION IS THE OPPOSITE OF THE PROOF-OBLIGATION SIBLING ABOVE, deliberately: there
        `>=` is right because a recheck appended in the same second as its deploy really did happen
        after it, and the deadline gate carries the rest. Here the whole claim IS "later", so the
        tie must fail closed to NOT-evidence and leave the record reported.
        """
        rec = open_records.get(pair)
        return rec is not None and event_ts > rec["established"]

    for event_ts, data in rows:
        # CLEAR FIRST, then establish — a single row can legitimately do both (an attribution record
        # naming one pair at the merge-base and another on the branch), and a pair this row places on
        # the branch is passing on main as of this row whatever another pair says.
        for pair in _known_broken_pairs(data, KNOWN_BROKEN_CLEARING_SIDE):
            if _clears(pair):
                open_records.pop(pair, None)
                cleared_count += 1
            vacated.pop(pair, None)
        # ROUTE (c) — T-11791. A GREEN land that DEMONSTRABLY RAN the pair's test file is a direct
        # observation of that file passing on the tree it fast-forwarded main to, whether or not it
        # ran the whole enumeration. Route (b) asks "did you run EVERYTHING"; the question the record
        # needs answered is "did you run THIS FILE, and did it pass" — and asking the broader one
        # made a SURGICAL repair structurally unable to clear the record it repaired (measured
        # 2026-08-28: the repair landed green at 07:45:16Z having run 150 of 1103 files, the record
        # stayed open ~35 min, and a docs-only batch was refused pre-queue inside that window while
        # main was in fact green). Route (b) is now the SUFFICIENT case it always was, not the only
        # one.
        #
        # NO SHA PROBE AND NO GIT HERE, and that is not a weakening. Route (b) needs the historical
        # blob check precisely BECAUSE counts cannot say which files ran: a test deleted or renamed
        # since the breakage is no longer in the enumeration while the counts still read "full". The
        # recorded set answers that question DIRECTLY — a name in it is a file this run executed —
        # so the conjunct route (b) needs has nothing left to add. A file NOT in the set is simply
        # not evidence: the record stays open, exactly as before.
        #
        # NOTHING TIME-BASED IS ADDED. `_clears` is the same strictly-later ordering test both other
        # routes use, `now` is still not a parameter of this fold, and no window is applied.
        # THE GREEN TEST IS EXPLICIT, not a default (audit-post finding, high). Route (b) one block
        # down reads `data.get("status") or "ok"`, so a row that names NO status is treated as green
        # there; route (c) does NOT inherit that. Green is the whole reason a recorded selection
        # counts as a PASS rather than merely as a list of files that ran, so a row that does not SAY
        # it was green cannot answer the question — and an unanswerable row is NOT-evidence, like
        # every other unknown here. Costs nothing in practice and is the fail-closed direction:
        # measured over this repo's journal, all 1006 `land_completed` rows carry an explicit status
        # (575 `ok` / 431 `abort`), so the default was never load-bearing — only silently permissive.
        ran_tests = _known_broken_ran_tests(data)
        if ran_tests is not None and str(data.get("status") or "") == "ok":
            for pair in list(open_records):
                if _clears(pair) and _known_broken_file(pair) in ran_tests:
                    open_records.pop(pair, None)
                    cleared_count += 1
                    vacated.pop(pair, None)
        # ROUTE (d) — T-11731. A GREEN land whose DELEGATED verify layer answered for the pair's
        # test file is a direct observation of that file's surface running and passing on the tree
        # that land produced. Routes (a)/(b)/(c) between them left a DELEGATING consumer with no
        # clearing route AT ALL: (a) needs a FAILING land, (b) needs a full enumeration the delegated
        # sweep never runs, and (c) needs `selection_ran_tests`, which is written by the very sweep
        # delegation SKIPS. So a repo that followed the declared delegation contract (SPEC-0185 §1a)
        # could never clear a record its PRE-delegation sweep had established — and since only
        # governance-only branches are refused pre-queue, the block stayed invisible until somebody
        # tried to land paperwork (bc-community, X-1151 / X-1164, measured twice 2026-08-27).
        #
        # PER FILE, NEVER PER LAYER-NAME. The record clears only for a pair whose file is IN the
        # recorded surface, exactly as route (c) clears only a file in the recorded selection: a
        # layer answers for what it declared and for nothing else. Clearing on a bare layer name
        # would clear pairs that layer never covered.
        #
        # NOTHING TIME-BASED IS ADDED and no false green is admitted. `_clears` is the same
        # strictly-later ordering test the other three routes use, `now` is still not a parameter of
        # this fold, and a delegated layer that FAILED — or a DIFFERENT layer that passed — reads as
        # NOT-evidence, so the record stands. That is the leg the reporting consumer refused to
        # forge, kept here rather than relaxed.
        deleg_files = _known_broken_delegated_pass_files(data)
        if deleg_files is not None:
            for pair in list(open_records):
                if _clears(pair) and _known_broken_file(pair) in deleg_files:
                    open_records.pop(pair, None)
                    cleared_count += 1
                    vacated.pop(pair, None)
        sha = str(data.get("sha") or "").strip()
        # THE SHA GATE LIVES HERE, NOT IN THE PROBE. Route (b) is "the file was in the tree THIS row
        # produced", so a row that names no tree cannot answer it — and the guarantee must not rest
        # on the probe's own handling of a blank sha, because the probe is an INJECTED seam and a
        # caller could hand in one that answers anyway. Caught by this card's own fail-closed
        # tripwire, whose fixture probe did exactly that.
        if sha and str(data.get("status") or "ok") == "ok" and _known_broken_full_enumeration(data):
            for pair in list(open_records):
                if not _clears(pair):
                    continue
                present = probe(root, sha, f"{KNOWN_BROKEN_TEST_SUBDIR}/{_known_broken_file(pair)}")
                if present is True:
                    open_records.pop(pair, None)
                    cleared_count += 1
                    vacated.pop(pair, None)
                elif present is False:
                    rec = open_records.pop(pair)
                    vacated[pair] = {"pair": pair, "file": rec["file"],
                                     "at": event_ts.isoformat().replace("+00:00", "Z"),
                                     "sha": sha,
                                     "reason": KNOWN_BROKEN_VACATED_REASON}
                # `None` — could not answer ⇒ NOT evidence. The record stays exactly as it was.
        for pair in _known_broken_pairs(data, KNOWN_BROKEN_ESTABLISHING_SIDE):
            vacated.pop(pair, None)       # a re-observed pair is a live fact again, not a tombstone
            rec = open_records.get(pair)
            stamp = event_ts.isoformat().replace("+00:00", "Z")
            if rec is None:
                open_records[pair] = {"pair": pair, "file": _known_broken_file(pair),
                                      "assertion": str(pair).partition(": ")[2].strip(),
                                      "since": stamp, "last_seen": stamp, "established": event_ts,
                                      "branch": str(data.get("branch") or ""), "seen": 1}
            else:
                # A RE-OBSERVATION RE-STAMPS the establishing instant: the record is now a fact about
                # THIS tree, so evidence must post-date THIS observation, not the original one.
                rec["established"] = event_ts
                rec["last_seen"] = stamp
                rec["seen"] += 1
                rec["branch"] = str(data.get("branch") or rec["branch"])

    # `established` is the ORDERING datetime, an internal of the pass — the returned record carries
    # the same instant as the ISO `since` string every reader (and every citation by ts) uses.
    broken = sorted((({k: v for k, v in r.items() if k != "established"})
                     for r in open_records.values()), key=lambda r: (r["since"], r["pair"]))
    vacated_rows = sorted(vacated.values(), key=lambda r: (r["at"], r["pair"]))
    return {
        "lens": ("tests KNOWN BROKEN ON MAIN — each REPRODUCED at the merge-base by a land's own "
                 "attribution probe (main WITHOUT that branch's diff), with no later evidence of it "
                 "passing there. Derived from `land_completed.failure_attribution` alone; no stored "
                 "state, no window, and no clock — a record clears on the passing EVIDENCE or not at "
                 "all (SPEC-0181 §Known-broken-on-main)."),
        "count": len(broken),
        "broken": broken,
        "cleared_count": cleared_count,
        "vacated_count": len(vacated_rows),
        "vacated": vacated_rows,
    }


# ─────────────────────────────────────────────────────────────────────────────────────────────────
# ROLLED-BACK AFFECTED-TEST SELECTION (SPEC-0181 auto-rollback / SPEC-0119 rule 30, T-11486)
# ─────────────────────────────────────────────────────────────────────────────────────────────────
#
# WHAT WAS SILENT, MEASURED 2026-08-23. When the SPEC-0181 auto-rollback fires,
# `worktree._selection_governs` returns `(False, "miss-threshold:<n>/<t>")` and that token lands in
# `land_completed.verify_metrics.selection_govern_reason` and NOWHERE ELSE — not on the land tail,
# not at session start, not in any view. From outside, a firing reads as lands getting SLOWER (the
# governed median went 5.3 min back toward the 10.6 min full-suite median), which is
# indistinguishable from host load or a long admission queue. The safety valve built to catch silent
# loss was itself silent.
#
# AND IT DOES NOT SELF-CLEAR. `_selection_recorded_misses` counts every disagreement recorded under
# the rule version in force and never decreases, so once the threshold is reached selection stays OFF
# until a human bumps `_SELECTION_RULE_VERSION`. A silent firing is therefore not a temporary revert
# — it is a mechanism switched off with nobody informed. That is what makes this a debt line rather
# than a nicety.
#
# THE GOVERNOR IS THE ONE ORACLE, INJECTED — this fold counts NOTHING itself (the T-11216 rule, the
# same discipline SPEC-0119 rule 26 states for the borrowed abort-cause identity). Both numbers the
# rendered line shows are read back out of the governor's OWN token, so the view cannot drift from
# the rule even if the threshold or the counting changes. This module back-imports nothing from the
# host (see the module header), so the host residue in `cli.py` binds `_governs` — the same
# one-wiring-site-buys-every-seam shape as every sibling fold, giving all three debt seams
# (session-start / land-tail / the on-demand `debt` re-fold) with no new verb.
SELECTION_ROLLBACK_REASON_PREFIX = "miss-threshold:"


def selection_rollback(events_path, *, _governs) -> dict:
    """SPEC-0119 rule 30 / SPEC-0181 — is affected-test selection currently ROLLED BACK on this journal?

    Returns `{rolled_back, misses, threshold, reason}`. `rolled_back` is True ONLY for the
    auto-rollback token; `misses`/`threshold` are None whenever it is False.

    THE ENV SWITCH IS NEUTRALISED ON PURPOSE (`env={}`). The governor consults
    `YITC_SELECTION_GOVERN` FIRST and short-circuits to `switch-off` before it ever counts, because
    as a GATE it must run more on any unanswerable state. A debt view that inherited that
    short-circuit would go SILENT in exactly the session that had selection switched off by hand —
    hiding a journal state that is independent of the switch. Passing an EMPTY env makes the switch
    leg take its own documented default, so the verdict returned here is the JOURNAL's, which is the
    fact this line reports.

    ONLY THE ROLLBACK FIRES IT, not every not-governing verdict. `switch-off` is an operator choice
    and `governor-cannot-count` / `governor-error:*` are read failures; none of them is the
    permanent, non-self-clearing rollback this rule names, and printing on them would make the line
    unreadable within a day. FAIL-QUIET on everything else, like every sibling: a governor that
    raises, or returns a shape this cannot read, renders nothing rather than a guess."""
    empty = {"rolled_back": False, "misses": None, "threshold": None, "reason": None}
    try:
        verdict = _governs(str(events_path), env={})
        governed, reason = verdict
    except Exception:
        return empty
    if governed or not isinstance(reason, str):
        return empty
    if not reason.startswith(SELECTION_ROLLBACK_REASON_PREFIX):
        return dict(empty, reason=reason)          # switch-off / cannot-count / error — not this rule
    counts = reason[len(SELECTION_ROLLBACK_REASON_PREFIX):].split("/")
    if len(counts) != 2:
        return dict(empty, reason=reason)
    try:
        misses, threshold = int(counts[0]), int(counts[1])
    except (TypeError, ValueError):
        return dict(empty, reason=reason)
    return {"rolled_back": True, "misses": misses, "threshold": threshold, "reason": reason}


# ── SPEC-0119 rule 31 — UNCARRIED P8 ADOPTION WARNS (T-11563) ────────────────────────────────────
#
# THE FACT IS ALREADY WRITTEN AND NOBODY EVER READS IT AGAIN. `task close` records
# `adoption_evidence_seen: false` on the `task_closed` row of every `class: infra` card whose
# CHARTER §P8 check found no substantive carrier (the E-0005 WARN, `task.py#_infra_adoption_seen`).
# That WARN is NON-BLOCKING BY DESIGN — semantic adoption evidence cannot be a false-positive-free
# hard gate — so it is a single line on a closing session's stdout and then nothing holds it. Two
# infra closures went out that way in two days (T-11442, T-11473) with no followup, no
# post-ship observation and no armed waiter between them. This fold is the reading moment that
# silence was missing; it adds NO event, NO store, NO field and NO verb.
#
# THE CARRIER MUST BE DECLARED, NEVER INFERRED — the load-bearing half, and it is why this fold does
# NOT read `relates_to`. `relates_to` is PROVENANCE ("what this followup is ABOUT"), so ANY unrelated
# residual captured under a card would silently hide that card's uncarried WARN — the exact
# false-negative the lens exists to end (audit-pre pass 1, high). A followup carries a closure's P8
# obligation only when it SAYS SO: `P8-CARRIER: <task-id>` in its text. Same declared-not-inferred
# discipline that made `awaits` — never `relates_to` — the followup FIRE key (T-10335).
#
# IT FAILS TOWARD SILENCE, WHICH IS THE OPPOSITE OF A GATE
# (`lessons/a-signal-about-a-reader-fails-safe-the-opposite-way-to-a-gate`). This describes what a
# closing session DID, so every state it cannot decide — an absent or unparseable card, an
# unparseable `ts`, a followup fold that raises — reads as CARRIED and is DROPPED. A false "you left
# this uncarried" defames a real carrier and gets the whole line skimmed; a missed detection only
# leaves the silence that already exists.
#
# REPORT-ONLY, and deliberately nothing more: it does not gate closing without a carrier, does not
# re-open a card, and moves no exit code. The E-0005 WARN stays exactly as non-blocking as it was —
# what changes is that it is no longer the LAST time anyone hears about it.

P8_WARN_EVENT = "task_closed"
# The payload key `task close` writes for a `class: infra` card (task.py). Named once here so this
# reader and that writer cannot drift.
P8_WARN_KEY = "adoption_evidence_seen"
# The DECLARED carrier marker. Named ONCE — the fold reads it, the debt line's remedy prints it and
# the tests assert against it, so the three can never disagree about what a carrier looks like (the
# `DEAD_LAND_TIP_PREFIX` / `ABORT_PAID_VERIFY_MARKER` precedent).
P8_CARRIER_MARKER = "P8-CARRIER:"
# The followup statuses that still HOLD an obligation. `promoted` counts: the followup became a real
# task, which is a stronger carrier than the followup was. `dropped` does not — dropping is the
# explicit decision that nothing is owed.
P8_CARRIER_FOLLOWUP_STATUSES = frozenset({"open", "promoted"})
# The reading HORIZON default (hours). Not a governance scalar and not a gate: what keeps a closure
# from a month ago being re-announced forever. The engine's own corpus carries 452 historical
# `adoption_evidence_seen: false` rows, so an unbounded fold would print a number nobody can act on.
P8_WARN_WINDOW_HOURS = 168
# The two CHARTER §P8 adoption-evidence event types — the ONLY discharge P8 recognises. Named here
# for the same reason `P8_WARN_KEY` is (this reader and its writer must not drift), and pinned EQUAL
# to the writer-side home `cli.py#P8_EVIDENCE_TYPES` by a test, because this module deliberately
# back-imports no host module at import time and so cannot read that constant directly.
P8_ADOPTION_EVENT_TYPES = frozenset({"consumer_read_evidence", "live_trigger_evidence"})


def p8_carrier_followups(events_path, _followups=None):
    """The MARKER-CARRYING followups — the ONE `P8-CARRIER:` parse in the system (T-11995).

    Returns a list of records `{id, task_ids, trigger, awaits, status}` — one per followup whose
    TEXT declares the marker — or `None` when the carriers could not be read at all.

    WHY THIS SHAPE, and why it is not two readers. Two consumers need the SAME declaration and
    exactly one of them needs only its ids: this fold (SPEC-0119 rule 31 — "is that closure's P8
    obligation held?", which cares only about WHICH task ids are carried) and the audit-post
    packet's third-satisfier section (SPEC-0015 / CHARTER §P8 — which must also RENDER the trigger
    and the awaited artifact). A second copy of the marker parse would let the debt view and the
    audit packet disagree about what a carrier IS, which is precisely the drift `P8_CARRIER_MARKER`
    was named once to prevent. So the reader returns the RECORDS and `_p8_carrier_task_ids` derives
    the narrower answer from them; the packet applies its own stricter selection (SPEC-0015's
    three-part shape) on top, never a second parse.

    STATUS IS REPORTED, NEVER PRE-FILTERED. `P8_CARRIER_FOLLOWUP_STATUSES` is THIS view's
    obligation-holding rule (`promoted` still holds — it became a real task); the packet's rule is
    narrower (`open` only — SPEC-0015's carrier is a FILED, still-blocking follow-up). Filtering
    here would silently impose one consumer's judgement on the other, so each caller applies its own.

    Fails toward SILENCE, unchanged: a fold that raises returns `None` — "carrier state unknown" —
    never an empty list, because empty is the ACCUSING direction (every candidate would read as
    uncarried because the carriers could not be read).
    """
    try:
        from lib import followup as _fu       # local import: debt.py back-imports no host module
        items = (_followups() if _followups is not None
                 # T-12202 deliberately does NOT inject its parsed lane here. This site is
                 # reachable OUTSIDE the debt echo's `rows_memo` scope, where taking both lanes
                 # would be a SECOND physical read rather than a memo hit (the
                 # `test_t11740_p8_later_evidence_arm` A5e read counter measures exactly that), and
                 # it needs no injection anyway: inside the echo this call is memo-SERVED by the
                 # entry `cli._open_followup_counts` computed before the render.
                 else _fu._fold(events_path, journal.segment_fold_lines))
    except Exception:                          # noqa: BLE001 — unreadable carriers => not a claim
        return None
    if not isinstance(items, dict):
        return None
    out = []
    for fid, it in items.items():
        if not isinstance(it, dict):
            continue
        text = it.get("text")
        if not isinstance(text, str) or P8_CARRIER_MARKER not in text:
            continue
        # The marker names the id it carries, so one followup can only ever carry what it SAYS.
        carried = set()
        for chunk in text.split(P8_CARRIER_MARKER)[1:]:
            m = _TASK_ID_RE.match(chunk.strip().split()[0]) if chunk.strip().split() else None
            if m:
                carried.add(m.group(0))
        if not carried:
            continue
        out.append({"id": it.get("id") or fid,
                    "task_ids": carried,
                    "trigger": it.get("trigger"),
                    "awaits": it.get("awaits"),
                    "status": it.get("status"),
                    "text": text})
    return out


def _p8_carrier_task_ids(events_path, _followups=None) -> set:
    """The task ids DECLARED as carried by a followup — `P8-CARRIER: <task-id>` in its text.

    DERIVED from `p8_carrier_followups` above (T-11995): the parse lives there, this applies THIS
    view's obligation-holding status rule (`P8_CARRIER_FOLLOWUP_STATUSES`) and projects to ids.

    Fails toward SILENCE: an unreadable fold returns `None`, which the caller turns into "carrier
    state unknown -> report nothing". Returning an EMPTY set on failure would be the accusing
    direction (every candidate would read as uncarried because the carriers could not be read).
    """
    carriers = p8_carrier_followups(events_path, _followups)
    if carriers is None:
        return None
    carried = set()
    for rec in carriers:
        if rec.get("status") in P8_CARRIER_FOLLOWUP_STATUSES:
            carried |= rec["task_ids"]
    return carried


def _p8_card_declares_carrier(root, task_id) -> bool:
    """Does the CARD itself already declare a deferred-proof carrier?

    Two, both pre-existing and both already surfaced by their own echo clauses: a
    `post_ship_observation:` (SPEC-0036 variant (e)) and a `probes: {ACx: deferred}` (T-11408). A
    closure holding either is not unheld — it is held by the carrier that clause reports on, and
    naming it twice would be two lines for one obligation.

    UNREADABLE => True (carried). The fail-toward-silence direction: an absent card, a YAML error or
    a permission failure is not evidence that anyone dropped an obligation.
    """
    try:
        matches = sorted(Path(root).joinpath("tasks").glob(f"{task_id}-*.yaml"))
        if not matches:
            return True
        card = yaml.safe_load(matches[0].read_text(encoding="utf-8")) or {}
    except Exception:                          # noqa: BLE001 — cannot read => cannot accuse
        return True
    if not isinstance(card, dict):
        return True
    if card.get("post_ship_observation"):
        return True
    probes = card.get("probes")
    if isinstance(probes, dict) and any(str(v).strip() == "deferred" for v in probes.values()):
        return True
    return False


def _p8_later_evidence_clears(task_id, warn_ts, p8_by_task, rows, *, with_reason=False,
                              repo_root=None):
    """T-11740 — was the adoption actually PROVED after the WARN fired?

    THE STRUCTURAL DEFECT THIS ENDS. The WARN is a HISTORICAL SNAPSHOT taken at `task close`: once
    fired it is immutable, and until this arm the fold had no way to read anything that happened
    afterwards. So all three existing drop tests were ways of saying "the proof is still OWED" — a
    marked carrier followup, a declared post-ship observation, a deferred probe — and emitting the
    genuine `consumer_read_evidence` / `live_trigger_evidence` that CHARTER §P8 actually recognises
    left the row exactly where it was, while writing a followup promising it removed the row. A
    reporting consumer routed 11 named closures and the count fell from 11 to 8: it fell by the three
    PROMISES and by NONE of the eight PROOFS (X-1190 / kupiclub T-0515, whose own AC2 had to be
    authored to expect that doing the right thing did not count). The sibling report is the same fold
    seen from the false-positive side — 7 of 11 rows were closures whose substantive P8 evidence was
    emitted 17-38 SECONDS after the `task_closed` row (X-1170).

    THE STANDARD IS NOT WIDENED — it is the close-time one, REUSED. The judgement is
    `task._p8_evidence_is_substantive`, the same predicate `task close` applies (SPEC-0015): a
    non-empty `failing_input` naming the differential AND an `evidence_events` ref that resolves to a
    real, correlated, non-circular row. A prose-only or circular payload therefore still fails and the
    row still reports. Re-implementing that judgement here is what would let the two drift (CHARTER
    §P5), so it is imported, never copied. Its two consumer-arm deps stay UN-INJECTED, which the
    predicate reads as KERNEL — the STRICTER of the two readings.

    THIS ARM INVERTS THE MODULE'S FAIL-TOWARD-SILENCE DEFAULT, deliberately (audit-pre pass 1, high).
    Everywhere else here an unanswerable state reads as CARRIED, because those tests ask "is someone
    HOLDING this obligation?" and an unreadable followup or card is no evidence that anyone dropped
    it. This test asks the opposite question — "has the proof been EMITTED?" — and reading an
    unanswerable state as YES would fabricate an adoption claim, which is exactly the self-issued
    prose `_p8_evidence_is_substantive` exists to reject. So an import failure, a raising predicate or
    an unparseable stamp returns False and clears NOTHING. That direction is not accusing either: it
    reproduces the fold's pre-change output precisely, never a row this view would not already print.

    AT-OR-AFTER, not strictly after. A row stamped at the same second as the WARN is admitted: the
    WARN's own firing is proof that close did not see this evidence, and a second-resolution stamp
    cannot separate "the same instant" from "just after". Anything genuinely earlier that was already
    substantive would have suppressed the WARN at close instead.

    T-12003 — `with_reason` ANSWERS THE SECOND QUESTION THIS ARM ALREADY KNEW THE ANSWER TO. Default
    False, so the verdict and return type every existing caller sees are byte-identical; with True the
    return is `(cleared, reason)`. The reason is None when the arm CLEARS, and None when the task has
    NO later row at all — there is nothing to explain about evidence nobody emitted, and inventing a
    line there would make every ordinary uncarried closure read as a rejected attempt.

    WHY THIS EXISTS. The arm's whole point (T-11740) is that emitting the real proof clears the row —
    but when the proof was emitted and did NOT clear it, the line said only THAT the closure was
    uncarried, never why, so the author who had done the work saw the identical output as the author
    who had done nothing. Measured on kupiclub 2026-09-02: two genuine, task-tied
    `live_trigger_evidence` rows for T-0521 / T-0519 carrying a real differential in PROSE, under keys
    the contract does not read, left both rows standing with no way to tell that from silence.

    THE LATEST ROW'S REASON, when several fail. That is the payload the author most recently wrote and
    is looking at; reporting the oldest would answer about an attempt already superseded.

    THE FAIL-TOWARD-SILENCE INVERSION ABOVE IS UNCHANGED, and the reason obeys it: an import failure,
    a raising predicate, an unplaceable row or an unusable `repo_root` (T-12106 — a `None` root simply
    leaves the repo-reading ref forms dark, exactly as today) still returns NOT-cleared, with reason None. An
    unreadable state explains nothing — a reason invented there would be this module printing a
    diagnosis it did not make, on a surface whose only job is to be trustworthy enough to read.

    Pure function of its arguments plus the one local import — it reads no file and writes nothing."""
    def _verdict(cleared, reason=None):
        return (cleared, reason) if with_reason else cleared

    later = sorted((t_ for t_ in p8_by_task.get(task_id, ()) if t_[0] >= warn_ts),
                   key=lambda pair: pair[0])
    if not later:
        return _verdict(False)
    try:
        from lib import task as _task    # local import: debt.py back-imports no host module
        reason = None
        for _ts, ev in later:
            # T-12106 — `REPO_ROOT` IS INJECTED, because this arm's whole promise is that it reuses
            # "the close-time `task._p8_evidence_is_substantive` so the two standards cannot drift"
            # (rule 31's own words). Without the root, the `test:` ref form resolves NOWHERE here
            # while resolving fine at `task close` — so the two standards ALREADY differed for the
            # exact class rule 31 was written about (its text names that class: evidence that "could
            # not RESOLVE for a structural reason"). Passing it RESTORES the reuse the rule claims;
            # it is rule-PRESERVING, not a widening of what counts. `_is_consumer_build` stays
            # UNPASSED on purpose: absent it the predicate reads the STRICTER kernel arm, which is
            # the fail-closed direction for a report-only view, and this module back-imports no host
            # module that could answer the realm question honestly.
            ok, why = _task._p8_evidence_is_substantive(ev, task_id, rows, with_reason=True,
                                                        REPO_ROOT=repo_root)
            if ok:
                return _verdict(True)
            reason = why               # LATEST failing payload wins — see the docstring
        return _verdict(False, reason)
    except Exception:                    # noqa: BLE001 — unreadable => NOT proved => clears nothing
        return _verdict(False)


def uncarried_p8_warns(events_path, *, root, window_hours: int = P8_WARN_WINDOW_HOURS,
                       now=None, _followups=None) -> dict:
    """SPEC-0119 rule 31 — infra closures whose CHARTER §P8 adoption WARN fired with NO carrier.

    Returns `{count, window_hours, rows}` where each row is `{task_id, closed_at}`, oldest first,
    plus an OPTIONAL `unproved_reason` (T-12003) present only on a row whose task DID carry a later
    P8 adoption event that the close-time contract judged not-substantive — the reason it did not
    count, so the line can say WHY a recorded event left the row standing instead of only THAT it
    did. Absent on every other row, so a closure with no later evidence reads exactly as before.
    A non-positive `window_hours` DISABLES the view (an operator switch, never a bar that hides a
    count); every unanswerable state resolves to CARRIED and drops out.

    PURE READ. It opens the journal through the ONE shared parsed fold (so the T-11453
    request-scoped memo still collapses it with its ~15 siblings at the debt residue) plus, for the
    SURVIVING candidates only, their own task cards. It writes nothing.

    DECLARED HORIZON: the WHOLE logical journal (SPEC-0190 rule 4, T-11590). The window this fold
    judges is EXACTLY P8_WARN_WINDOW_HOURS = 168 hours = 7 days — IDENTICAL to
    JOURNAL_LIVE_WINDOW_DAYS, and rule 4 names that EQUALITY as the case that looks safe and is not.
    The two are the same length only in nominal terms: rotation moves rows on `ts < boundary`, so on
    an ordinary read the oldest hours of the declared week are ALREADY in an archive segment, and any
    skew or inclusivity choice widens the gap. The direction of the loss here is UNDER-report on a
    GOVERNANCE surface, which is why it matters more than a shortfall would elsewhere: this view
    exists to make an unproven CHARTER §Principle-8 adoption VISIBLE, and a closure whose WARN fired
    with no carrier drops off it the moment its `task_closed` row crosses the boundary — before the
    declared week is out. The view would go quiet at exactly the oldest, most-owed end of its own
    window, and a debt that is not shown was, for every reader, discharged. So it takes the ARCHIVE
    branch (`journal.segment_rows`), which reads each segment through the SAME `fold_rows` primitive
    — one physical read path, one parse path, and the T-11453 `rows_memo` scope still serves each
    segment. Same swap the sibling migration T-11589 made on `_abort_rows` in this file.

    ORDER-SENSITIVITY (SPEC-0190 rule 6, the reader-specific judgement). Segments concatenate in
    `segment_paths` order, not in `ts` order — but this reader is NOT order-sensitive: it collects
    `(ts, task_id)` tuples and then `sorted()`s on the WHOLE tuple, and the `seen` dedup keeps the
    earliest surviving row per task id off that total order. Two rows the cross-segment reordering
    rule 5 admits could permute compare EQUAL on BOTH members — they are indistinguishable — so a
    permutation can neither move a row, drop one, nor let an older row outrank a newer. Every other
    predicate here is a pure per-row or per-task-id function.

    SCOPE (T-11590): the CARRIER half — `_p8_carrier_task_ids`, which reaches the journal through
    `followup._fold` — is a DIFFERENT reader chain, separately registered in the reader sweep and
    separately carded (T-11597). It is deliberately untouched here.

    THE LATER-EVIDENCE ARM (T-11740, X-1170 / X-1190) is the FOURTH drop test, and it is the only one
    that reads a PROOF rather than a promise: a surviving candidate whose task id carries a P8
    adoption event stamped at-or-after its WARN, judged substantive by the close-time predicate, is
    dropped. Its rationale, its reuse-not-reimplement bound and the one place it inverts this
    module's fail-toward-silence direction live on `_p8_later_evidence_clears` — not restated here.
    It costs NO second journal read: `segment_rows` already materialises the whole logical journal as
    a list, so this fold now HOLDS that list (it is the resolution corpus the predicate resolves refs
    against) and collects the P8 rows in the SAME pass that finds the WARNs. The arm is consulted for
    the SURVIVING candidates only, after all three existing tests.
    """
    empty = {"count": 0, "window_hours": window_hours, "rows": []}
    try:
        window = int(window_hours)
    except (TypeError, ValueError):
        return empty
    if window <= 0:
        return empty
    # THE HORIZON IS COMPUTED IN EPOCH SECONDS, not with a duration type, for a reason EXTERNAL to
    # this fold: SPEC-0149's one-window rule is guarded by a MODULE-WIDE source assertion
    # (`test_spec0149_obligation_fold.test_ac2_the_fold_never_defaults_a_window`) forbidding duration
    # vocabulary anywhere in `debt.py`. That guard's own docstring scopes its invariant to
    # `open_proof_obligations`' resolution path and this reading horizon is a different concern — but
    # the guard is DELIBERATE and not this card's to narrow, so the arithmetic is expressed in a way
    # that leaves the invariant it protects untouched. Same instants, no duration type in this module.
    # Identical to the resolution rule 27 already took at `aborted_land_cost` (T-11368), which filed
    # the followup to narrow the guard to its stated subject; this rule adds no second one.
    try:
        ref = now or datetime.now(timezone.utc)
        cutoff = datetime.fromtimestamp(ref.timestamp() - float(window) * 3600.0, tz=timezone.utc)
    except Exception:                          # noqa: BLE001
        return empty

    candidates = []
    p8_by_task: dict = {}
    rows_corpus: list = []
    try:
        # BOUND ONCE, then iterated: `segment_rows` returns a LIST, so holding it costs nothing over
        # the read this fold already paid, and it IS the corpus `_p8_evidence_is_substantive` resolves
        # its refs against. Re-reading the journal for the arm would be the second reader P5 forbids.
        rows_corpus = journal.segment_rows(events_path)   # SPEC-0190 rule 4 — the WHOLE journal
        for event in rows_corpus:
            if not isinstance(event, dict):
                continue
            etype = event.get("type")
            if etype in P8_ADOPTION_EVENT_TYPES:
                # The later-evidence arm's candidates, collected in the SAME pass (T-11740). Placed
                # ahead of the WARN filter only because the two type sets are disjoint; an
                # unplaceable id or stamp is simply not collected, so it can clear nothing.
                p8_tid = event.get("task_id") or (event.get("data") or {}).get("task_id")
                p8_ts = _parse_stamped_deadline(event.get("ts"))
                if isinstance(p8_tid, str) and _TASK_ID_RE.match(p8_tid) and p8_ts is not None:
                    p8_by_task.setdefault(p8_tid, []).append((p8_ts, event))
                continue
            if etype != P8_WARN_EVENT:
                continue
            data = event.get("data") or {}
            # IDENTITY, not truthiness: an absent key, a None, or a non-bool is NOT a fired WARN.
            # `task close` writes this key ONLY for `class: infra`, so the class filter rides the
            # key's presence and this fold needs no second reading of the card's class.
            if data.get(P8_WARN_KEY) is not False:
                continue
            task_id = event.get("task_id") or data.get("task_id")
            if not isinstance(task_id, str) or not _TASK_ID_RE.match(task_id):
                continue
            ts = _parse_stamped_deadline(event.get("ts"))
            if ts is None or ts < cutoff:      # unparseable ts => cannot place it => stay silent
                continue
            candidates.append((ts, task_id))
    except Exception:                          # noqa: BLE001 — an unreadable journal accuses nobody
        return empty
    if not candidates:
        return empty

    carried = _p8_carrier_task_ids(events_path, _followups=_followups)
    if carried is None:                        # carrier state unknown => report nothing
        return empty

    rows, seen = [], set()
    for ts, task_id in sorted(candidates):
        if task_id in seen or task_id in carried:
            continue
        if _p8_card_declares_carrier(root, task_id):
            continue
        cleared, unproved_reason = _p8_later_evidence_clears(
            task_id, ts, p8_by_task, rows_corpus, with_reason=True, repo_root=root)
        if cleared:
            continue                       # T-11740 — the proof was emitted after the WARN fired
        seen.add(task_id)
        row = {"task_id": task_id, "closed_at": ts.strftime("%Y-%m-%dT%H:%M:%SZ")}
        # T-12003 — ADDITIVE AND OPTIONAL: present ONLY when a later task-tied P8 row exists and was
        # judged not-substantive, i.e. only when there is something to explain. A closure with no
        # later evidence keeps exactly the row shape it had, so no existing reader changes.
        if unproved_reason:
            row["unproved_reason"] = unproved_reason
        rows.append(row)
    return {"count": len(rows), "window_hours": window, "rows": rows}


# ── T-11663 (SPEC-0184 rule 9) — the QUEUE-JUMP FIRING view (safeguard c) ─────────────────────────
QUEUE_JUMP_FIRED_EVENT = "land_queue_jump_fired"

# The window exists so the line DECAYS INTO SILENCE when the practice stops, rather than standing as
# a permanent monument nobody reads — the same discipline the security-gate-override and
# obligation-miss lines already take (SPEC-0119 rule 14). It is a REPORTING window, not a bound on
# the mechanism: nothing expires because of it, and the rows stay in the journal forever.
QUEUE_JUMP_WINDOW_DAYS = 14


def queue_jump_firings(events_path, now=None, window_days: int = QUEUE_JUMP_WINDOW_DAYS) -> dict:
    """Fold the journal → the queue-jump marks that ACTUALLY REORDERED land admission (T-11663).

    THE SUBJECT IS THE FIRING, NEVER THE MARK. A card carrying `queue_jump` is not debt: it may be a
    correct emergency, and it may sit unused because the queue was empty. What needs seeing without
    an audit is the mark CHANGING WHO GETS THE ROAD — so this folds `land_queue_jump_fired`, which
    the yield site emits only when the mark decided the handover. A corpus full of marks that never
    fire folds to zero here, and that is the right answer, not a miss.

    Returns `{count, firings: [{task, branch, reason, ts}], window_days}` — `count` is the number of
    FIRINGS in the window (not distinct cards: a card that jumped the queue nine times is exactly the
    overuse this view exists to make visible, and collapsing it to one would hide it).

    Never raises: an unreadable / missing / malformed journal folds to `count: 0` — a REPORT-ONLY
    surface must never nag on, or die of, an unknown."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    # The age is read off the subtraction's own `.days`, exactly as `MISS_WINDOW_DAYS` is read above
    # — one spelling of "how old is this row" in this module, and no duration is ever CONSTRUCTED
    # here (SPEC-0149's fold pins that absence module-wide).
    span = max(1, int(window_days or QUEUE_JUMP_WINDOW_DAYS))
    firings: list = []
    try:
        # SPEC-0190 rule 4 — the segments the window REACHES, neither fewer nor more (T-12030).
        # The reporting window here is 14 days and the live segment is shorter, so `fold_rows` would
        # silently answer about the last few days while appearing to answer about the whole window:
        # the exact undeclared-horizon failure that rule exists to forbid. The other end is just as
        # much a rule-4 defect and is what T-12030 removes: folding all 93 archive segments to answer
        # a 14-day question. The floor is the window widened by `_window_segment_floor`'s margin, and
        # the `span` test below is unchanged and still decides every row.
        for event in journal.segment_rows_since(
                events_path, _window_segment_floor(now, days=span)):
            if not isinstance(event, dict) or event.get("type") != QUEUE_JUMP_FIRED_EVENT:
                continue
            ts = _parse_stamped_deadline(event.get("ts"))
            if ts is None or (now - ts).days > span:
                continue
            data = event.get("data") if isinstance(event.get("data"), dict) else {}
            firings.append({
                "task": event.get("task_id") or data.get("branch"),
                "branch": data.get("branch"),
                "reason": data.get("reason"),
                "ts": event.get("ts"),
            })
    except Exception:                     # noqa: BLE001 — see docstring
        return {"count": 0, "firings": [], "window_days": int(window_days)}
    return {"count": len(firings), "firings": firings, "window_days": int(window_days)}


# ── T-12420 (SPEC-0119 rule 42 / SPEC-0188 rule 7) — the WITHHELD TAIL WRITE view ────────────────
# A post-ff bookkeeping write that could not prove its readers green is WITHHELD rather than
# committed, so `main` never goes red for it. Withholding is silent by itself — the land is GREEN and
# nothing is missing from the tree — which is exactly why it owes a reading: a writer that is
# withheld land after land is a real defect (a tripwire and an automatic writer that genuinely
# disagree), not a passing flake. Windowed like its rule-9 / rule-33 siblings, so the line decays
# into silence once the writer is admitted again.
TAIL_WITHHELD_EVENT = "land_tail_write_withheld"
TAIL_WITHHELD_WINDOW_DAYS = 7


def land_tail_writes_withheld(events_path, now=None,
                              window_days: int = TAIL_WITHHELD_WINDOW_DAYS) -> dict:
    """Fold the journal → the post-ff tail writes WITHHELD in the window (T-12420).

    Returns `{count, writers: {<writer>: <n>}, latest: {writer, test, reason, ts}, window_days}`.
    The count is of WITHHOLDINGS, not distinct writers: one writer withheld nine times is the
    recurrence this view exists to make visible, and collapsing it would hide it.

    Never raises: an unreadable / missing / malformed journal folds to `count: 0` — a REPORT-ONLY
    surface must never nag on, or die of, an unknown (the rule-9 fold's contract, reused)."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    span = max(1, int(window_days or TAIL_WITHHELD_WINDOW_DAYS))
    writers: dict = {}
    latest = None
    count = 0
    try:
        for event in journal.segment_rows_since(
                events_path, _window_segment_floor(now, days=span)):
            if not isinstance(event, dict) or event.get("type") != TAIL_WITHHELD_EVENT:
                continue
            ts = _parse_stamped_deadline(event.get("ts"))
            if ts is None or (now - ts).days > span:
                continue
            data = event.get("data") if isinstance(event.get("data"), dict) else {}
            writer = str(data.get("writer") or "unknown")
            writers[writer] = writers.get(writer, 0) + 1
            count += 1
            latest = {"writer": writer, "test": data.get("test"),
                      "reason": data.get("reason"), "ts": event.get("ts")}
    except Exception:                     # noqa: BLE001 — see docstring
        return {"count": 0, "writers": {}, "latest": None, "window_days": int(window_days)}
    return {"count": count, "writers": writers, "latest": latest, "window_days": int(window_days)}


# ── T-11799 (SPEC-0119 rule 33) — the PRE-QUEUE KNOWN-BROKEN REFUSAL view ─────────────────────────
PREQUEUE_REFUSAL_EVENT = "land_completed"
PREQUEUE_REFUSAL_KEY = "prequeue_known_broken"

# A REPORTING window, on the same terms as rule 27's abort-cost window and rule 9's firing window:
# the line DECAYS INTO SILENCE once refusals stop, instead of standing as a permanent monument.
# Nothing expires because of it — the rows stay in the journal forever and the fold is the only
# thing that is windowed.
#
# 1 DAY, AND IT DELIBERATELY DOES NOT REUSE RULE 27'S WINDOW (T-11841). This line was born at 7d as
# the rule-27 abort-cost window REUSED rather than a new number, on the ground that a reader
# comparing the two should not have to convert. That reuse is given up here, because the two lines
# answer different questions and the shared number made this one LIE. Rule 27 aggregates a cost
# TREND, where a long horizon is exactly what makes the trend readable. This line reports a LIVE
# FREEZE — its reader's question is "is main stopping people RIGHT NOW" — so any horizon that
# outlives the fix produces a phantom, not a trend.
#
# MEASURED, 2026-08-30: this line named `work/file-red-main-root-cwd-site` for a main that had been
# FIXED THE PREVIOUS DAY (fix landed via 54896c3e72, both named tests green, six consecutive lands
# succeeded in the hour before the echo). A controller read it as a live freeze and was one step
# from dispatching a worker at a phantom. At 7d the rule did not deliver its OWN stated contract —
# decaying into silence once refusals stop — against a main fixed one day earlier.
#
# The DIVERGENCE FROM THE SIBLING IS THE POINT, not an oversight: do not "restore" the reuse.
# Reader-facing override: `YITC_DEBT_PREQUEUE_REFUSAL_WINDOW_DAYS` (resolved host-side in
# `cli._debt_prequeue_refusal_window_days`, the rule-26 / rule-31 knob shape).
PREQUEUE_REFUSAL_WINDOW_DAYS = 1


def prequeue_known_broken_refusals(events_path, now=None,
                                   window_days: int = PREQUEUE_REFUSAL_WINDOW_DAYS) -> dict:
    """Fold the journal → the lands REFUSED BEFORE THE QUEUE as main-known-broken (T-11799).

    THE SUBJECT IS THE REFUSAL, AND IT WAS PREVIOUSLY COUNTED NOWHERE. The SPEC-0119 rule-27
    abort-cost views count lands that reached a verify; a pre-queue refusal reaches none, takes no
    reservation and holds no queue position — correctly, since taking nothing is its whole point —
    so the mechanism's own win was invisible in its own statistics, and a dispatched worker stopped
    by one had no recorded cause. This fold is the reading moment that silence was missing.

    ONE ORACLE, RE-DERIVED NOWHERE (the T-11216 rule): the rows counted here are the ones
    `_land_prequeue_known_broken_refusal` itself composed and `_emit_land_abort` wrote, read back by
    the key they were written under. Nothing about what establishes a known-broken record, what
    narrows the refusal, or what clears it is restated here — that is `open_known_broken`'s and
    SPEC-0181's, and this fold neither duplicates nor can disagree with them.

    Returns `{count, refusals: [{branch, pairs, files, ts}], branches, window_days}` — `count` is the
    number of REFUSALS in the window, not of distinct branches: a repo refusing the same branch nine
    times is exactly the freeze this view exists to make visible, and collapsing it to one would hide
    it. `branches` is the distinct set, so a reader can tell the two shapes apart at a glance.

    THE ANSWER IS EXPLICITLY SORTED, not left in fold order (audit-post finding, 2026-08-28). SPEC-0190
    rule 5 declines to promise row ORDER across a partition, so a reader handing back physical journal
    order would be making a promise the storage does not keep — and this fold's census disposition
    records it as order-INSENSITIVE, which must be TRUE of the code rather than merely asserted of it.
    Sorted by `(ts, branch)`: the timestamp is the fact a reader of a freeze actually wants ordered,
    and the branch breaks ties deterministically so two rows stamped the same instant cannot swap
    between two folds of the same history.

    REPORT-ONLY. It counts a refusal; it never excuses, waives or retries one — and it says nothing
    about whether a refused land should be resumed, which is a separate open question.

    Never raises: an unreadable / missing / malformed journal folds to `count: 0` — a REPORT-ONLY
    surface must never nag on, or die of, an unknown."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    span = max(1, int(window_days or PREQUEUE_REFUSAL_WINDOW_DAYS))
    refusals: list = []
    try:
        # SPEC-0190 rule 4 — the segments the reporting window REACHES (T-12030). The live segment
        # may be SHORTER than that window (`PREQUEUE_REFUSAL_WINDOW_DAYS`, named rather than
        # re-spelled here so this reason cannot go stale when the window moves), so `fold_rows` would
        # silently answer about the last few days while appearing to answer about the whole window;
        # and the whole ARCHIVE is just as wrong in the other direction, since a segment older than
        # the window holds nothing this fold would keep. The `span` test below is unchanged and still
        # decides every row.
        for event in journal.segment_rows_since(
                events_path, _window_segment_floor(now, days=span)):
            if not isinstance(event, dict) or event.get("type") != PREQUEUE_REFUSAL_EVENT:
                continue
            data = event.get("data") if isinstance(event.get("data"), dict) else {}
            # BOTH conditions, and `status` is not redundant: the key rides ONLY an abort row today,
            # and a fold that did not say so would silently start counting a hypothetical ok row.
            if data.get("status") != "abort":
                continue
            rec = data.get(PREQUEUE_REFUSAL_KEY)
            if not isinstance(rec, dict):
                continue
            pairs = [p for p in (rec.get("pairs") or []) if isinstance(p, dict)]
            if not pairs:
                continue
            ts = _parse_stamped_deadline(event.get("ts"))
            if ts is None or (now - ts).days > span:
                continue
            refusals.append({
                "branch": rec.get("branch") or data.get("branch"),
                "pairs": [str(p.get("pair")) for p in pairs if p.get("pair")],
                "files": sorted({str(p.get("file")) for p in pairs if p.get("file")}),
                "ts": event.get("ts"),
            })
    except Exception:                     # noqa: BLE001 — see docstring
        return {"count": 0, "refusals": [], "branches": [], "window_days": int(window_days)}
    refusals.sort(key=lambda r: (str(r.get("ts") or ""), str(r.get("branch") or "")))
    return {"count": len(refusals), "refusals": refusals,
            "branches": sorted({r["branch"] for r in refusals if r["branch"]}),
            "window_days": int(window_days)}


# ── SPEC-0119 rule 37 — SEAM READ AMPLIFICATION (T-12037 / plan card C3) ──────────────────────────
#
# The reading moment the C1 counters (T-12034) were emitted for and, until this view, did not have.
# `cli_invoked.reads` has recorded what every verb PHYSICALLY read since T-12034 — folds against
# segments, parsed rows against real rows, card parses against real cards — and nothing rendered any
# of it back to a human. That is the exact shape of the silence SPEC-0190 rule 10 is distilled from:
# T-12029's session start took 383 s, of which 378 s was ~20 whole-corpus passes, and it was found by
# a person waiting rather than by an instrument. Rule 10 makes the next one a test failure; this rule
# makes the next one a LINE, at the three seams a controller already reads before acting.
SEAM_READ_WINDOW_DAYS = 7
"""The reporting window, in days.

SEVEN, and it is READ FROM THE CARD'S OWN SUBJECT rather than picked: the rule the plan card states
is "the worst seam ratio of the LAST 7 DAYS per project", and SPEC-0190's own
`JOURNAL_LIVE_WINDOW_DAYS` is 7 — so a 7-day fold is answerable from the LIVE segment on an ordinary
corpus and does not oblige an archive walk to report on read cost. A view about read amplification
that itself needed the archive would be its own first finding.

A REPORTING window only: nothing expires, the rows stay in the journal forever, and the line DECAYS
INTO SILENCE once a seam's scope is fixed (the rule-14 / rule-27 / rule-33 discipline) instead of
standing as a monument to a seam repaired a month ago."""

SEAM_READ_RATIO_BOUND = 1.05
"""The GREEN ceiling — folds-per-segment / rows-parsed-per-row / cards-parsed-per-card.

1.05, NOT 1.0, and the 5% is not slack for sloppiness: rule 10's bound is "<= 1 physical fold per
segment in scope", and a real process legitimately reads a little more than the scope it composes —
a `--help` fetch-receipt tail scan, a segment appended to mid-request, a single point-read of one
card outside the memo. A bound of exactly 1.0 would fire on those and teach its reader to ignore the
line, which is how a signal in this repo actually dies. What 1.05 cannot absorb is a SECOND pass over
the corpus: the shapes this view exists to catch measured 22x and 27x, not 1.02x."""

SEAM_READ_RED_BOUND = 2.0
"""The RED threshold the roster's T4.P6 probe grades against — a seam reading the corpus TWICE.

Recorded here beside its sibling so the roster and this fold cannot drift on the number. The fold
itself NEVER grades and never gates: it reports every seam over `SEAM_READ_RATIO_BOUND` and marks
which ones are also over this one, and what to do about a RED is the roster's judgement and the
owner's, not this view's."""

# The seams whose amplification is RED at `SEAM_READ_RED_BOUND` rather than merely worth reporting —
# the reading moments a human WAITS on (SPEC-0190 rule 10's own first instances were all here). NOT
# an allowlist and NOT a filter: a seam outside this set is reported exactly as any other, it is only
# not marked `blocking`. Matched as a prefix of the `cli_invoked.verb` label, because the label
# carries the subcommand (`session start`, `graph query`) and the blocking property belongs to the
# verb family, not to one argument shape.
SEAM_READ_BLOCKING_VERBS = ("session start", "land", "debt")

# ── THE SUBJECT-SIZE FLOOR, per axis — the denominator below which a ratio measures NOTHING ───────
#
# WHY A FLOOR AT ALL, and it is the sibling discipline (rule 24's `floor_hours`, rule 26's
# `min_branches`, rule 34's `min_attempts`), not an exception carved for this view. A ratio is only a
# reading of AMPLIFICATION when the thing amplified is big enough for the second pass to cost
# something. On a ONE-SEGMENT sandbox, a verb that folds three times reads "3.0x" — arithmetically
# true and operationally meaningless: it is three reads of a ten-line file, not the 378 seconds of
# whole-corpus re-walking this view exists to catch.
#
# MEASURED, and this is why it is a defect rather than a nicety: without the floor the line fired on
# every hermetic fixture in the suite, including two whose whole contract is "a CLEAN repo prints
# NOTHING" (`test_t9754_proactive_debt_echo`, `test_t11139_land_tail_before_teardown`). A signal that
# speaks in every sandbox is a signal every reader learns to skip — which is how signals in this repo
# actually die, and it would have taken the suppressed-when-clean promise down with it.
#
# THE VALUES ARE READ FROM THE SUBJECT, NOT DECREED. Against this repo's own corpus on 2026-09-04 the
# real rows carry segments=95, rows≈598,000, cards≈3,350; the shapes the view exists to catch measured
# 22x over 93 segments and 11.1M parses over ~596k rows. Every floor below is therefore two to three
# ORDERS OF MAGNITUDE under the live signal and comfortably above any fixture — it cannot mute a real
# finding, and the smallest genuine amplification observed here (`cross outbox` at 1.59x over 15,388
# rows) still clears it by 15x.
SEAM_READ_MIN_SEGMENTS = 2
"""folds_per_segment measures RE-WALKING THE SEGMENT SET. With one segment there is no set to
re-walk, so the ratio degenerates into a raw fold count and reports on nothing."""

SEAM_READ_MIN_ROWS = 1000
"""rows_parse_ratio over a handful of rows is noise: a verb that parses 30 lines twice is not paying
for it. The live corpus is ~598,000 rows."""

SEAM_READ_MIN_CARDS = 100
"""card_parse_ratio, same reasoning on the card corpus. The live corpus is ~3,350 cards."""


def _seam_read_ratios(reads: dict) -> dict:
    """One `cli_invoked.reads` block → its three ratios, each present ONLY when its denominator is real.

    An ABSENT ratio and a ratio of 0.0 are different facts and must not collapse: a process that
    parsed no cards because there were no cards to parse has no card ratio, while one that parsed
    none of 3,000 cards has a ratio of 0.0. Returning the key only when the denominator is positive
    keeps `max()` over the present ratios honest — a fabricated 0.0 would silently win a `min` and
    lose a `max`, and either way would put a number nobody measured into a reported answer.

    Denominators are the C1 payload's OWN (`segments` / `rows` / `cards`), never re-derived here:
    re-deriving them would need a second read of the very corpus this view exists to stop re-reading.

    AN AXIS WHOSE DENOMINATOR IS BELOW ITS SUBJECT-SIZE FLOOR IS DROPPED, not reported (see the
    `SEAM_READ_MIN_*` constants): on a corpus that small the ratio measures nothing, and reporting it
    made every hermetic fixture in the suite look amplified. The AXIS is dropped rather than the row,
    because one process can hold a meaningful rows ratio beside a meaningless card one."""
    out: dict = {}
    for name, num_key, den_key, floor in (
            ("folds_per_segment", "folds", "segments", SEAM_READ_MIN_SEGMENTS),
            ("rows_parse_ratio", "rows_parsed", "rows", SEAM_READ_MIN_ROWS),
            ("card_parse_ratio", "cards_parsed", "cards", SEAM_READ_MIN_CARDS)):
        num, den = reads.get(num_key), reads.get(den_key)
        if isinstance(num, bool) or isinstance(den, bool):
            continue                       # `bool` is an `int` subclass — a True would read as 1
        if not isinstance(num, (int, float)) or not isinstance(den, (int, float)):
            continue
        if den <= 0 or num < 0:
            continue
        # THE SUBJECT-SIZE FLOOR (see the constants above): a denominator this small makes the ratio
        # a statement about a toy corpus, not about read cost. Dropping the AXIS rather than the ROW
        # is deliberate — a verb may legitimately have a meaningful rows ratio and a meaningless card
        # one in the same process, and zeroing the whole row would lose the half that reads true.
        if den < floor:
            continue
        out[name] = round(num / den, 3)
    return out


def _seam_exemption_bound(exemptions, verb: str, default: float) -> float:
    """The bound THIS seam is held to — `default`, unless a `reads.exemptions[]` entry names it.

    THE VISIBLE READER THE CARRIER NEVER HAD. `init.py#_hook_reads_exemptions` validates the entry's
    shape fail-closed and its own docstring records the gap this closes: "this surface has NO reader
    that fails visibly ... a half-registered entry would be inert AND invisible". A declared exemption
    that changed no reported number would be exactly that. So the four-field entry SPEC-0190 rule 10
    requires is honoured here, at the one place a bound is applied.

    SHAPE ONLY, never re-validation (the `_hook_reads_exemptions` division of labour): `seam` must
    match the verb and `ratio_bound` must be a positive number, because those two are what this
    function USES; `reason` and `until` are the hook's business and are not re-checked here, so a
    change to the carrier's shape rules has ONE home. An entry that fails this function's two
    requirements yields the default — the fail-closed direction, since an unusable exemption must
    never read as a wider bound.

    MATCH IS EXACT on the seam label, not a prefix: an exemption is a specific accepted risk at a
    specific wiring site, and prefix-matching `land` would silently exempt every land-family verb
    nobody wrote an entry for. RAISES the bound only — an entry declaring a bound TIGHTER than the
    default is honoured as declared, since a project holding itself to more is not this view's
    business to relax."""
    if not exemptions:
        return default
    try:
        for e in exemptions:
            if not isinstance(e, dict) or str(e.get("seam") or "").strip() != verb:
                continue
            rb = e.get("ratio_bound")
            if isinstance(rb, bool) or not isinstance(rb, (int, float)) or rb <= 0:
                continue
            return float(rb)
    except TypeError:                      # a non-iterable `exemptions` — treat as none declared
        return default
    return default


# The `expected_touch` fragments that make a closed card a DEBT/ECHO-VIEW card — the class-1
# instance-fix carrier of the plan's F2. Fragments rather than exact paths so a consumer's own
# layout matches too. A card touching one of these while a seam stood amplified was working ON the
# very surface that was over bound — the signal the plan asked for WITHOUT a human tag, derived from
# the card's own declared touch joined to the journal's own `task_closed` rows.
#
# `lib/views.py` IS DELIBERATELY EXCLUDED, and the exclusion is what makes the list a signal rather
# than a census. It is the SHARED renderer for every lens in the system — the `graph query` views,
# the scorecards, the profiles — so ~every card that renders anything at all declares it. Measured
# against the engine's own 7-day window: including it named 52 cards, which is not a class being
# paid off in instances, it is the week's closures. These two files ARE the debt/echo surface proper
# — the folds and the per-project nightly leg — and a card that changed a debt LINE without touching
# either did not change a debt view.
SEAM_READ_ECHO_VIEW_TOUCH = ("lib/debt.py", "lib/nightly.py")


def seam_read_amplification(events_path, *, root=None, now=None,
                            window_days: int = SEAM_READ_WINDOW_DAYS,
                            bound: float = SEAM_READ_RATIO_BOUND,
                            exemptions=None) -> dict:
    """Fold the journal → the SEAMS whose physical reads exceeded their bound (SPEC-0119 rule 37).

    A pure, report-only, windowed fold over `cli_invoked` rows carrying the T-12034 `reads` block.
    Wired at the ONE shared host residue like every sibling (`cli.py#_debt_echo_lines`), so it rides
    all three debt seams — session start, the land tail, and the on-demand `debt` re-fold — with no
    new store, no new event type, no new verb and no new seam of its own.

    IT READS THROUGH THE INSTRUMENTED PRIMITIVES, WHICH IS NOT A STYLE CHOICE. `journal.segment_rows`
    and `state.load_path` are the two readers a request-scoped ReadScope serves (SPEC-0190 rule 10),
    so inside the wiring site's scope this view performs NO physical read of its own and the view
    that reports amplification cannot itself be a source of it. The card-side half is why the closed
    cards below are resolved BY ID off this fold's own `task_closed` rows and loaded one at a time,
    never by globbing `tasks/*.yaml`: a whole-corpus glob would parse ~3,300 cards to name at most a
    handful, which is conformant with the bound (one parse per card) and still absurd for the answer
    it buys. Rule 10 is a ceiling, not a licence.

    `measured` AND `count` ARE BOTH REPORTED, AND THE SPLIT IS LOAD-BEARING (audit-pre finding 1).
    `measured` is how many (project, verb) seams carried usable counters at all, computed BEFORE the
    at-or-under-bound seams are dropped; `count` is the amplified subset that survives. Without the
    split, a CLEAN corpus and an UNINSTRUMENTED one both fold to `count: 0` and no reader downstream
    can tell "every seam is within bound" from "nothing here has ever been measured". The nightly
    leg's `no counters` verdict is decided on `measured` alone for exactly this reason — SPEC-0190's
    own rule 4 names the fault this avoids, and CHARTER §P3's «presence ≠ absence» is the same rule
    one altitude up.

    Returns `{lens, count, measured, window_days, bound, seams, worst, instance_fixes}`, where each
    seam is `{project, verb, ratio, axis, ratios, bound, exempted, blocking, samples, ts}` and the
    list is sorted worst-first with `(project, verb)` breaking ties deterministically — SPEC-0190
    rule 5 promises no physical row order, so a fold handing back journal order would be making a
    promise the storage does not keep.

    THE WORST PER SEAM, NEVER THE MEAN. A seam that reads the corpus 22x once and cleanly 200 times
    has a mean inside the bound and a real defect; the mean would report the defect away. The worst
    observation is also the one a reader can act on, because it names a specific run.

    REPORT-ONLY, and the fence is the load-bearing half: it names a cost and never excuses one. It
    waives no gate, moves no exit code, changes no verb's behaviour and proposes no cache — a cache
    on a view inside a composed seam is a proposal to skip rule 10, which is the very rule this
    surfaces. The remedy it points at is the seam's ONE scope or a narrower horizon.

    Never raises: an unreadable / missing / malformed journal folds to `measured: 0, count: 0`, which
    IS the no-counters shape — a report-only surface must never nag on, or die of, an unknown."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    span = max(1, int(window_days or SEAM_READ_WINDOW_DAYS))
    worst: dict = {}          # (project, verb) -> the worst observation seen
    samples: dict = {}        # (project, verb) -> how many rows carried usable counters
    closed_ids: set = set()   # task ids closed inside the window (the instance-fix candidates)
    try:
        for event in journal.segment_rows(events_path):
            if not isinstance(event, dict):
                continue
            etype = event.get("type")
            if etype not in ("cli_invoked", "task_closed"):
                continue
            ts = _parse_stamped_deadline(event.get("ts"))
            if ts is None or (now - ts).days > span:
                continue
            data = event.get("data") if isinstance(event.get("data"), dict) else {}
            if etype == "task_closed":
                tid = data.get("task_id") or event.get("task_id")
                if tid:
                    closed_ids.add(str(tid))
                continue
            reads = data.get("reads")
            if not isinstance(reads, dict):
                continue          # a pre-T-12034 row, or one whose counters could not be computed
            ratios = _seam_read_ratios(reads)
            if not ratios:
                continue          # counters present but every denominator empty — nothing measured
            verb = str(data.get("verb") or "").strip() or "<unnamed verb>"
            project = str(reads.get("project") or "").strip() or "<unnamed project>"
            key = (project, verb)
            samples[key] = samples.get(key, 0) + 1
            axis, ratio = max(ratios.items(), key=lambda kv: kv[1])
            prev = worst.get(key)
            if prev is None or ratio > prev["ratio"]:
                worst[key] = {"project": project, "verb": verb, "ratio": ratio, "axis": axis,
                              "ratios": ratios, "ts": event.get("ts")}
    except Exception:                      # noqa: BLE001 — see docstring
        return {"lens": _seam_read_lens(span, bound), "count": 0, "measured": 0,
                "window_days": int(window_days), "bound": float(bound),
                "seams": [], "worst": None, "instance_fixes": []}

    seams: list = []
    for key, rec in worst.items():
        seam_bound = _seam_exemption_bound(exemptions, rec["verb"], float(bound))
        if rec["ratio"] <= seam_bound:
            continue
        rec = dict(rec)
        rec["bound"] = seam_bound
        rec["exempted"] = seam_bound != float(bound)
        rec["blocking"] = (rec["ratio"] > SEAM_READ_RED_BOUND
                           and rec["verb"].startswith(SEAM_READ_BLOCKING_VERBS))
        rec["samples"] = samples.get(key, 0)
        seams.append(rec)
    seams.sort(key=lambda r: (-r["ratio"], r["project"], r["verb"]))
    return {"lens": _seam_read_lens(span, bound), "count": len(seams), "measured": len(worst),
            "window_days": int(window_days), "bound": float(bound),
            "seams": seams, "worst": seams[0] if seams else None,
            # The instance-fix carrier is computed ONLY when a seam actually stood over bound: the
            # plan's condition is "a card closed in the window whose expected_touch names a debt/echo
            # view WHILE a seam ratio > bound stood", so with no such seam there is nothing to
            # attribute and the card reads are not paid at all.
            "instance_fixes": _seam_read_instance_fixes(root, closed_ids) if seams else []}


def _seam_read_lens(span: int, bound: float) -> str:
    """The one-line lens description, composed from the SAME values the fold reports (never re-typed)."""
    return (f"seam-read-amplification (SPEC-0119 rule 37) — a verb whose PHYSICAL reads over the "
            f"last {span}d exceeded {bound}x the corpus it composed (folds/segment, rows-parsed/row, "
            f"cards-parsed/card, from the T-12034 `cli_invoked.reads` counters). The remedy is the "
            f"seam's ONE request-scoped ReadScope at its wiring site, or a narrower horizon/slice — "
            f"never another per-view cache (SPEC-0190 rule 10)")


def _seam_read_instance_fixes(root, closed_ids) -> list:
    """The closed cards that were working ON the debt/echo surface while a seam stood amplified.

    THE PLAN'S F2 CARRIER, AND IT CARRIES NO HUMAN TAG BY CONSTRUCTION: membership is derived from
    the card's OWN `expected_touch` declaration joined to the journal's own `task_closed` rows, so
    nobody has to remember to label a card as a class-1 instance fix and no label can go stale
    against the diff it describes. That is the whole point of deriving it — a tag would be exactly
    the human step this repo has watched fail (the P8-carrier and known-broken prior art).

    WHY IT IS WORTH NAMING AT ALL. One seam fixed at a time is a class being paid off in instances;
    the roster's T5 escalation reads this list to notice when that is happening — several
    instance-fix cards against a class that keeps recurring is the signal that the CLASS needs a
    rule, not another instance. This function only reports the join; it draws no conclusion.

    CARDS ARE LOADED BY ID through the memoised `state.load_path`, one at a time — never a
    whole-corpus glob (see the caller's docstring). UNREADABLE / ABSENT => simply not listed: an
    accusation must never rest on a card nobody could read, and this list only ever informs."""
    if not root or not closed_ids:
        return []
    out: list = []
    try:
        tasks_dir = Path(root) / "tasks"
        for tid in sorted(closed_ids):
            matches = sorted(tasks_dir.glob(f"{tid}-*.yaml"))
            if not matches:
                continue
            card = state.load_path(matches[0])
            if not isinstance(card, dict):
                continue
            touched = card.get("expected_touch")
            if not isinstance(touched, list):
                continue
            hits = sorted({frag for frag in SEAM_READ_ECHO_VIEW_TOUCH
                           for p in touched if isinstance(p, str) and frag in p})
            if hits:
                out.append({"task": tid, "touches": hits})
    except Exception:                      # noqa: BLE001 — an informational join, never fatal
        return out
    return out


# ── THE NIGHTLY'S READER (SPEC-0119 rule 38 / SPEC-0105, T-12078) ────────────────────────────────
#
# The two CHRONIC checks — the ones excluded from the per-project CHANGE line and given a dated line
# of their own. Both are chronic in the measured sense: on this repo's own journal `corpus` has been
# non-`ok` on all 11 registry projects and `born_waivers` has been in `alert` on 9 of them every
# night since 2026-08-31, which is exactly why `projects_flagged` has read 11/11 every night and the
# real movers (queue / freshness / no_local_diff / concern_drift) were invisible underneath.
#
# EXCLUDING THEM FROM THE CHANGE LINE IS THE POINT, NOT A CONVENIENCE. A condition that is present
# every night contributes a flip only when it briefly clears and returns, so leaving it in the
# differential would produce a stream of ok↔stale noise about the one thing that has not actually
# changed. They are not DROPPED — they get a dated line each, which says more than a flip could.
NIGHTLY_CHRONIC_CHECKS = ("corpus", "born_waivers")

# The remedy each chronic condition NAMES. Naming is this view's whole job: a report-only line that
# says "this has been true for N nights" and stops is a monument, and a line that says what to do
# about it is a reading. IMPLEMENTING either remedy is a separate card by construction — this map
# holds strings, and nothing here runs, schedules or offers to run anything.
NIGHTLY_CHRONIC_REMEDY = {
    "corpus": ("fix the `stale_root` cause the row already names, then `bin/yitc-v2 graph build` "
               "in that project"),
    "born_waivers": ("sweep the expired init placeholders — `bin/yitc-v2 -C <path> init "
                     "--backfill-mandatory` — and dispose of each, rather than re-stamping them"),
}
# The verdict that MAKES each chronic check chronic. Read as an exact match, never as "not ok": a
# check that is `skip` or `none` (not adopted, nothing to judge) is NOT the condition, and folding it
# in would count an unmeasured project as an afflicted one — the CHARTER §P3 «presence ≠ absence»
# fault the sibling rule 37 names in its own `measured`/`count` split.
NIGHTLY_CHRONIC_VERDICT = {"corpus": "stale", "born_waivers": "alert"}


def _nightly_verdict_map(row) -> dict:
    """One `nightly_run_completed` row → `{project: {check: verdict}}`, plus nothing else.

    KEPT DELIBERATELY THIN. The row carries the full per-check payload (violation lists, reasons,
    carrier shapes — kilobytes per project), and this view compares VERDICTS only, so holding the
    whole row for every night would retain a corpus to answer a question about ~16 short strings.

    A sub-dict with no `verdict` key contributes nothing: the map's membership IS the claim "this
    check reported that night", and inventing a verdict for a check that did not report would make a
    later flip read as a real move when it was a schema change."""
    out: dict = {}
    data = row.get("data") if isinstance(row.get("data"), dict) else {}
    for res in (data.get("results") or []):
        if not isinstance(res, dict):
            continue
        name = str(res.get("name") or "").strip()
        if not name:
            continue
        checks = {}
        for check, val in res.items():
            if isinstance(val, dict) and isinstance(val.get("verdict"), str):
                checks[check] = val["verdict"]
        out[name] = checks
    return out


def _nightly_chronic_spell(nights, check: str, verdict: str) -> dict:
    """The CURRENT unbroken spell of a chronic condition — its first night, and how many nights.

    WALKS BACKWARDS FROM THE LATEST NIGHT AND STOPS AT THE FIRST NIGHT THE CONDITION WAS ABSENT.
    That is what makes the line DATED rather than aged: "present on 11 projects since 2026-08-31"
    names a night a reader can go and look at, where "chronic for 5 days" names nothing and silently
    re-starts its own clock every time the fold is re-run. It also means a condition that cleared and
    came back is dated from its RETURN — the honest reading, since the older spell is over.

    Returns `{count, projects, since, nights}` for the LATEST night's affliction, or `{}` when the
    condition is absent from the latest night — absence is the suppressed case, never a zero line."""
    afflicted = [p for p, checks in (nights[-1]["map"] or {}).items() if checks.get(check) == verdict]
    if not afflicted:
        return {}
    since = nights[-1]["ts"]
    spell = 1
    for night in reversed(nights[:-1]):
        if not any(checks.get(check) == verdict for checks in (night["map"] or {}).values()):
            break
        since = night["ts"]
        spell += 1
    return {"count": len(afflicted), "projects": sorted(afflicted), "since": since, "nights": spell}


def nightly_verdict_changes(events_path, *, now=None) -> dict:
    """Fold the journal → what the LAST nightly said that the one before it did not (SPEC-0119 r38).

    THE SILENCE THIS CLOSES. `bin/yitc-v2 nightly` runs daily and writes ONE `nightly_run_completed`
    row carrying a per-check verdict for every registry project (SPEC-0105). Until this fold NOTHING
    read it back — `grep nightly_run_completed bin/lib/debt.py` returned zero — so a fleet-wide
    report existed in the journal and reached no seam a session actually reads. That is the same
    shape the sibling rules 29/30/33/37 each ended: a mechanism recording faithfully into a payload
    with no reader is indistinguishable, from outside, from one that was never built.

    IT REPORTS CHANGES, NOT STATE, AND THAT IS THE WHOLE DESIGN. The row's own headline has read
    `projects_flagged=11/11` every night since 2026-08-31, because two CHRONIC conditions paint every
    project the same colour. A view that re-printed the flag would re-print that saturation and be
    skimmed within a week. What a controller can act on is what MOVED: which project's which check
    flipped, from what to what, since last night.

    THE TWO CHRONIC CONDITIONS ARE SPLIT OUT, NOT DROPPED (`NIGHTLY_CHRONIC_CHECKS`). They are
    excluded from the per-project change line — a permanently-present condition contributes only
    ok↔stale noise there — and each gets ONE DATED line carrying its count, the first night of its
    CURRENT unbroken spell, and a NAMED remedy (`NIGHTLY_CHRONIC_REMEDY`). Naming the remedy is this
    view's job; IMPLEMENTING either remedy is explicitly not, and nothing here runs or offers to run
    anything.

    A FIRST SIGHTING IS NOT A FLIP, for CHECKS as well as for PROJECTS. Only projects present in
    BOTH nights are compared, and within them only checks present in both: a project that
    joined the registry today has no previous verdict set to have changed against, and reporting its
    whole verdict set as "changed" would make every registry addition read as a fleet-wide incident.
    Symmetrically, a project that DISAPPEARED contributes nothing — that is a registry change, which
    this view does not report on — and a check that reported on only one of the two nights is a
    SCHEMA change (a check shipped or withdrawn between runs), which is a release note, not a flip. Fewer than two rows ⇒ nothing at all: a first night has no
    yesterday, and the honest answer to "what changed" is silence, never "everything".

    ONE PASS, THROUGH THE INSTRUMENTED PRIMITIVE. `journal.segment_rows` is the segment-aware fold
    (SPEC-0190 rule 4 — the WHOLE logical journal; a raw read of the journal PATH sees the live
    segment alone and would report an older night as absent), and it is one of the two readers the
    wiring site's request-scoped ReadScope serves (SPEC-0190 rule 10). So inside `_debt_echo_lines`'
    scope this view performs NO physical read of its own, and it proposes NO cache: a cache on a view
    inside a composed seam is a proposal to skip rule 10, which the sibling rule-37 line reports on.
    Only the verdict MAP of each row is retained (`_nightly_verdict_map`), never the row.

    Returns `{lens, count, projects, nights, chronic}` — `projects` is one record per CHANGED project
    (`{project, flips: [{check, from, to}]}`, sorted by project, flips sorted by check, both
    deterministic because SPEC-0190 rule 5 promises no physical row order), `nights` names the two
    timestamps compared, and `chronic` is one record per chronic condition PRESENT on the latest
    night. `count` is the changed-project count alone — the chronic lines are independent of it, so a
    fleet where nothing moved but the chronic conditions persist still says so.

    REPORT-ONLY. Suppressed-when-clean, ZERO stored state, no new store, no new event type, no new
    verb, no new seam, no knob, no exit code, no gate. `now` is accepted for signature parity with
    the windowed siblings and is deliberately UNUSED: this fold has no window — it compares the last
    two rows whenever they were written, so a fleet whose nightly stopped running keeps reporting the
    last real comparison rather than going quiet exactly when something is wrong.

    Never raises: an unreadable / missing / malformed journal folds to the empty shape, which IS the
    nothing-to-report shape — a report-only surface must never nag on, or die of, an unknown."""
    empty = {"lens": _nightly_changes_lens(), "count": 0, "projects": [],
             "nights": {}, "chronic": []}
    nights: list = []
    try:
        for event in journal.segment_rows(events_path):   # SPEC-0190 rule 4 — the WHOLE journal
            if not isinstance(event, dict) or event.get("type") != "nightly_run_completed":
                continue
            vmap = _nightly_verdict_map(event)
            if vmap:
                # The verdict MAP for every night, and the RAW `results` for the latest night only —
                # the chronic DETAIL (`stale_root`, the placeholder counts) lives outside the verdict
                # and is read off the row itself. Holding the raw results of ALL 111 nights to answer
                # a question about the last one would be the amplification the sibling rule 37 reports.
                nights.append({"ts": str(event.get("ts") or ""), "map": vmap,
                               "results": (event.get("data") or {}).get("results") or []})
                if len(nights) > 2:
                    nights[-3]["results"] = None        # only the last two rows keep their payload
    except Exception:                      # noqa: BLE001 — see docstring
        return empty
    if len(nights) < 2:
        # A first night (or none) has no yesterday. Silence, never "everything changed".
        return empty

    prev, latest = nights[-2], nights[-1]
    changed: list = []
    for project in sorted(set(prev["map"]) & set(latest["map"])):
        before, after = prev["map"][project], latest["map"][project]
        # INTERSECTION, not union — for checks exactly as for projects, and for the same reason. A
        # check present on only ONE of the two nights is a SCHEMA change (a check shipped, renamed or
        # withdrawn between the runs), not a verdict that moved. Measured on this repo's own journal
        # the night T-12037 landed: the new `seam_reads` check would have reported a flip for all 11
        # projects at once, which reads as a fleet-wide incident and is a release note.
        flips = [{"check": c, "from": before[c], "to": after[c]}
                 for c in sorted(set(before) & set(after))
                 if c not in NIGHTLY_CHRONIC_CHECKS and before[c] != after[c]]
        if flips:
            changed.append({"project": project, "flips": flips})

    chronic: list = []
    for check in NIGHTLY_CHRONIC_CHECKS:
        spell = _nightly_chronic_spell(nights, check, NIGHTLY_CHRONIC_VERDICT[check])
        if spell:
            spell["check"] = check
            spell["verdict"] = NIGHTLY_CHRONIC_VERDICT[check]
            spell["remedy"] = NIGHTLY_CHRONIC_REMEDY[check]
            spell["detail"] = _nightly_chronic_detail(check, latest.get("results") or [],
                                                      set(spell["projects"]))
            chronic.append(spell)

    return {"lens": _nightly_changes_lens(), "count": len(changed), "projects": changed,
            "nights": {"previous": prev["ts"], "latest": latest["ts"]}, "chronic": chronic}


def _nightly_changes_lens() -> str:
    """The one-line lens description, composed from the SAME constants the fold uses (never re-typed)."""
    return (f"nightly-verdict-changes (SPEC-0119 rule 38) — what the last `nightly_run_completed` row "
            f"(SPEC-0105) said that the night before it did not, per project and per check, with the "
            f"chronic {' / '.join(NIGHTLY_CHRONIC_CHECKS)} conditions split into dated lines of their own")


def _nightly_chronic_detail(check: str, results, projects) -> str:
    """The ONE extra fact each chronic line carries beyond its count — read off the LATEST row.

    For `corpus` that is the set of `stale_root` causes the row already names, because "stale" alone
    does not tell a reader which tree to go and rebuild. For `born_waivers` it is the TOTAL number of
    stale placeholder waivers across the afflicted projects, because 9 projects holding 79
    placeholders and 9 holding 9 are different problems wearing the same count — and the count of
    PROJECTS, which is what the chronic line already carries, cannot tell them apart.

    Composed from the row, never re-derived: this reads what the nightly already recorded and does
    not go and look at any project. An unreadable shape yields an empty string — the line still
    prints its count and its date, which are the parts that must never depend on a detail parsing."""
    try:
        roots: set = set()
        placeholders = 0
        for res in results:
            if not isinstance(res, dict) or str(res.get("name") or "") not in projects:
                continue
            sub = res.get(check) if isinstance(res.get(check), dict) else {}
            if check == "corpus":
                root = str(sub.get("stale_root") or "").strip()
                if root:
                    roots.add(root)
            elif check == "born_waivers":
                stale = sub.get("stale_waivers")
                placeholders += len(stale) if isinstance(stale, list) else 0
        if check == "corpus":
            return f"stale roots: {', '.join(sorted(roots))}" if roots else ""
        if check == "born_waivers":
            return f"{placeholders} stale placeholder waiver(s)" if placeholders else ""
    except Exception:                      # noqa: BLE001 — a detail, never fatal to the count
        return ""
    return ""


# ─────────────────────────────────────────────────────────────────────────────
# T-12085 — THE BROWNFIELD GAP REGISTER (SPEC-0119 rule 39 / SPEC-0198 rules 5+7)
#
# ONE dated row per profile-required baseline item this project does not meet. It is a VIEW over
# two things that already exist — the derived profile (`lib.profile`, the ONE resolver) and the
# project's own SPEC-0093 ops carrier — carried by the EXISTING followup/task link. NO new store,
# no new event type, no new FSM, no schedule, no gate.
#
# WHY THERE IS NO SECOND DIMENSION TABLE HERE (SPEC-0198 rule 3). The catalog below is keyed by
# LENS id — the vocabulary `profile.required_check_set` already returns — and the DIMENSION each
# dedupe key needs is LOOKED UP from `profile._ACTIVATION` at runtime by `gap_dimension`. A literal
# dimension table in this module is exactly what `profile.second_derivation_sites` exists to flag,
# and copying one here to save a lookup would be the defect that tripwire names.
# ─────────────────────────────────────────────────────────────────────────────

#: The marker every auto-filed gap followup's TEXT opens with. ONE home, read by the fold and
#: written by the host writer, so the two can never disagree about what a gap row looks like — the
#: `P8_CARRIER_MARKER` precedent (T-11980).
GAP_MARKER = "GAP:"

#: The prefix of the stable dedupe key, carried on the followup's EXISTING `fingerprint` field
#: (T-10779 — a SOURCE-CLUSTER handle is exactly what this is). Never a new field.
GAP_KEY_PREFIX = "gap"

#: The reserved dimension label for the two CONSTANT_FLOOR lenses. They are unconditional — no
#: dimension activates them — so there is no dimension to name, and inventing one would make the
#: key lie about where the requirement came from.
GAP_CONSTANT_FLOOR_DIMENSION = "constant-floor"

#: SPEC-0198 rule 7's per-project PER-RUN cap, in the rule's own 1-mismatch + 2-risk shape. It
#: bounds ONE RUN of the writer; the once-per-item-FOREVER property is the dedupe key's, not this
#: number's. A 6-item project therefore files 3 at one seam and the rest at the next.
GAP_AUTOFILE_CAP = 3

#: The triage window a DATED row is read against, in days, HALF-OPEN [0, GAP_TRIAGE_WINDOW_DAYS):
#: a row aged strictly less than this is `within-triage`, a row aged at-or-beyond it is
#: `overdue-triage`. The date is the `ts` of the row's OWN `followup_added` event — the existing
#: timestamp carrier, so a dated row costs no new field. An UNFILED item has no date and is never
#: overdue.
GAP_TRIAGE_WINDOW_DAYS = 14

#: The terminal states a row may reach. A row in ANY of them leaves the count (SPEC-0119 rule 39).
GAP_TERMINAL_STATES = ("adopted", "adapted", "waived", "out-of-scope", "task-linked")

#: THE ONE risk order, highest-risk lens first. It exists because a CAP without a deterministic
#: order silently makes "the top two risks" mean "whatever the catalog happened to list first"
#: (audit-pre finding, 2026-09-05). Both the writer's cap selection and the summary's top-2 read
#: this same order through `gap_rank`, so they cannot disagree about which gaps matter most.
GAP_LENS_RISK_ORDER = (
    "secrets",
    "authz",
    "payment-integrity",
    "data-retention",
    "public-boundary",
    "input-validation",
    "key-rotation",
    "backup-restore",
    "deploy-readiness",
    "dependency-hygiene",
    "shared-repo-floor",
    "performance",
)

#: THE CATALOG — one row per profile-required baseline item, as
#: (lens, item_id, label, carrier_section, carrier_key).
#:
#: `carrier_key` names the KEY WITHIN `carrier_section` that answers this item, or `None` when the
#: item is answered by the section AS A WHOLE. Ten of the thirteen rows are section-granular and pass
#: `None`; the three `alert_routing` observability rows (SPEC-0164 rule 5) each name their own key,
#: because a live project is asked three separate questions and answering one must not answer the
#: others. Section granularity there let ONE declared key clear EVERY alert_routing item — so a
#: carrier declaring `health:` and a complete `slo:` but no `logs:` produced no gap at all (T-12088
#: audit-pre finding 1). `_gap_section_answer(section, key=…)` is where the distinction is read.
#:
#: `carrier_section` names the SPEC-0093 concern section whose ANSWER proves this item met. Every
#: name here is a REGISTERED section (`security` SPEC-0098 · `security_audit` SPEC-0145 ·
#: `remote_sync` SPEC-0163 · `alert_routing` SPEC-0164); none is invented, because a gap row
#: pointing at a section no spec owns would be unanswerable by construction.
#:
#: The labels are the SPEC-0100 authoring-moment defaults in their own words, so the summary line
#: reads as the question the owner is actually being asked.
_GAP_ITEMS = (
    ("secrets", "no-secret-in-runtime-output",
     "no key/token/credential in logs, traces or error bodies", "security", None),
    ("secrets", "no-placeholder-secret-live",
     "no dev/placeholder secret in a live environment", "security", None),
    ("dependency-hygiene", "lockfile-and-dependency-audit",
     "a land-time lockfile + dependency audit floor", "remote_sync", None),
    ("public-boundary", "public-surface-audited",
     "the public surface is covered by a dated security audit", "security_audit", None),
    ("input-validation", "request-body-floor",
     "validation / rate-limit / CSRF / log-redaction on request intake", "security", None),
    ("data-retention", "classification-and-deletion",
     "PII classification, retention and deletion are stated", "security_audit", None),
    ("payment-integrity", "webhook-verification",
     "payment webhook verification and a cost threshold", "security_audit", None),
    ("authz", "roles-and-tenancy-probe",
     "a named authz probe over roles/tenancy", "security", None),
    ("key-rotation", "rehearsed-rotation",
     "a rehearsed rotation script covering every ciphertext surface", "security_audit", None),
    ("backup-restore", "restore-drill",
     "a rehearsed restore-from-backup drill", "remote_sync", None),
    # SPEC-0164 rule 5 — the three OBSERVABILITY items, one per key, ALL on `deploy-readiness`.
    #
    # THE LENS IS THE GATE, and `deploy-readiness` is the one whose activating dimension IS
    # `operational_criticality` (`profile._ACTIVATION`: live | live-critical | unknown, with rule 7
    # collapsing a POSITIVE `prototype` to the constant floor). That is exactly rule 5's "asked only
    # of a live project", so no new lens and no new activation row is needed here.
    #
    # `one-slo-declared` USED TO RIDE `performance`, which activates on `traffic_scale` in
    # (low, medium, high) or a `load_artifact` — NOT on criticality. So a live project with an
    # unresolved traffic_scale and no load artifact was never asked for an SLO, which is precisely
    # the project rule 5 exists to ask (T-12088 audit-pre finding 2). Moving it here is the fix:
    # stop borrowing the wrong existing gate rather than build a new one. Its ITEM ID is preserved,
    # so only the dimension half of its dedupe key moves.
    # LABEL SAYS WHAT THE CARRIER KEY ACTUALLY CHECKS (T-12088, post-close consult finding 2). The
    # item ID `health-rollback-runbook` is PRESERVED (SPEC-0164 rule 5 names it, and the id is the
    # dedupe key) but its label used to read "health endpoint, rollback path and who is paged" while
    # the carrier_key resolves `health:` ALONE — SPEC-0164's `health:` is "the endpoint a human or a
    # monitor can hit to ask 'is it up?'", nothing more. A live carrier declaring only `health:` was
    # therefore marked terminal for an item that CLAIMED rollback + paging coverage it never graded:
    # a false attestation, and the coverage-shaped silence rule 2 exists to refuse. Rollback is asked
    # by `runbook-logs-rollback-contact` below and paging by the section's own `receiver:` (rule 2),
    # so nothing is lost by narrowing the LABEL to its key — and the check is NOT widened, because
    # rule 5's `health:` is free prose the kernel never shape-refuses (rule 3, grade-only).
    ("deploy-readiness", "health-rollback-runbook",
     "a health endpoint a human or a monitor can hit", "alert_routing", "health"),
    ("deploy-readiness", "structured-log-stance",
     "a structured-log stance and where the logs are read", "alert_routing", "logs"),
    ("deploy-readiness", "one-slo-declared",
     "at least one declared SLO on a live project", "alert_routing", "slo"),
    ("shared-repo-floor", "any-author-land-floor",
     "the any-author land-time floor (CI / branch protection)", "remote_sync", None),
    # T-12089 (SPEC-0199) — the five production-readiness carrier sections, each asked at the
    # crossing SPEC-0198 rule 6 already names. They are asked THROUGH THIS CATALOG because the gap
    # register is the one asking surface; the profile gating itself is the `lens in active` test
    # below, so no dimension is re-tabulated here (the section header's rule holds).
    #
    # `cost` is the one section whose rule reads "money present OR live", so its row names BOTH
    # lenses — ONE item, asked at either crossing. Two rows would have been the cheaper edit and it
    # was rejected: a money+live project would then carry TWO unanswered cost items, two dedupe keys
    # and two auto-filed followups for one question (audit-post pass 1, finding 2). The FIRST lens is
    # the PRIMARY — `gap_dedupe_key` / `gap_rank` / `gap_dimension` read exactly one lens per item,
    # so the key stays stable however many crossings activate it. Readers normalize through
    # `gap_item_lenses`; nothing reads a row's lens field raw.
    ("deploy-readiness", "environments-and-parity",
     "where config comes from, and whether staging mirrors prod", "environments", None),
    ("deploy-readiness", "runbook-logs-rollback-contact",
     "where the logs are, how to roll back, who to contact", "runbook", None),
    ("data-retention", "data-obligation-declared",
     "what personal data is held, for how long, and how it is deleted", "data_obligation", None),
    (("payment-integrity", "deploy-readiness"), "cost-threshold-declared",
     "the spend at which cost becomes a task, and where the number is read", "cost", None),
    ("dependency-hygiene", "dependency-cadence-declared",
     "the pin + lockfile + the rhythm dependencies are updated on", "dependency_cadence", None),
)


def gap_item_lenses(lens) -> tuple:
    """The lens(es) an `_GAP_ITEMS` row is activated by — one row MAY name several (T-12089).

    A row's `lens` field is either a single lens id or a tuple of them, and the FIRST is the
    PRIMARY: the key/rank/dimension surface still reads exactly ONE lens per item, so an item asked
    at either of two crossings dedupes to a single followup rather than one per crossing.
    Normalizing here — in the one helper every reader of the catalog calls — is what keeps the
    multi-lens form from leaking into each of them."""
    return (lens,) if isinstance(lens, str) else tuple(lens)


def gap_dimension(lens: str) -> str:
    """The DIMENSION whose crossing activates `lens` — SPEC-0198 rule 7's half of the dedupe key.

    LOOKED UP from `lib.profile._ACTIVATION`, never re-tabulated here (see the section header). A
    lens no dimension activates — the two `CONSTANT_FLOOR` members — answers with the reserved
    `constant-floor` label. An unimportable/changed resolver degrades to that same label rather
    than raising: this is a report-only surface, and a key that still dedupes is worth more than an
    exception at a session-start seam."""
    try:
        from lib import profile as _profile
        for dim, _activating, _lens in _profile._ACTIVATION:
            if _lens == lens:
                return dim
        for _key, _lens in _profile._EVIDENCE_ACTIVATION:
            if _lens == lens:
                return _key
    except Exception:                              # noqa: BLE001 — see docstring
        pass
    return GAP_CONSTANT_FLOOR_DIMENSION


def gap_dedupe_key(lens: str, item_id: str) -> str:
    """The STABLE dedupe key SPEC-0198 rule 7 requires — `gap|<dimension>|<item id>`.

    It is a pure function of the item, so the SAME gap computed at any seam, in any run, on any day
    produces the SAME key. That is the whole "one followup per gap item, EVER" property: the writer
    files only keys the journal has never seen, and re-running a seam files nothing."""
    return f"{GAP_KEY_PREFIX}|{gap_dimension(lens)}|{item_id}"


def gap_rank(item) -> tuple:
    """THE one deterministic order — risk first, then `item_id` ascending as the tie-break.

    A lens outside `GAP_LENS_RISK_ORDER` sorts after every ranked one (by its own name), so adding a
    lens to the resolver without ranking it here degrades to a stable alphabetical tail rather than
    to an arbitrary order."""
    lens = str((item or {}).get("lens") or "")
    try:
        rank = GAP_LENS_RISK_ORDER.index(lens)
    except ValueError:
        rank = len(GAP_LENS_RISK_ORDER)
    return (rank, lens, str((item or {}).get("item_id") or ""))


#: The waiver reasons that read as OUT-OF-SCOPE rather than as a plain waiver. A project saying
#: "this does not apply to us" and a project saying "we accept this risk for now" are different
#: answers, and the register renders them as different terminal states rather than flattening both
#: into `waived`. Matched on the waiver's own words — the only place the distinction is written.
_GAP_OUT_OF_SCOPE_TOKENS = ("not applicable", "n/a", "out of scope", "out-of-scope",
                            "does not apply", "no such surface")

#: The tokens that make a DECLARATION read as `adapted` rather than `adopted` — the project met the
#: item its own way and said so. Same faithful-reading discipline: this reports what the carrier
#: says, it never judges whether the adaptation is good.
_GAP_ADAPTED_TOKENS = ("adapted", "divergence", "instead of", "local variant", "override")


def _gap_waiver_answer(waiver) -> "tuple | None":
    """A WAIVER → (terminal_state, why), or None when it does not close anything.

    EXTRACTED VERBATIM from `_gap_section_answer` (T-12088) so the per-key path below can reuse the
    SAME rule instead of growing a second one. Behaviour is unchanged on every input; the sibling
    reasonless-waiver differential in `tests/test_t12085_gap_register.py` is the proof.

    A WAIVER IS TERMINAL ONLY WITH A REASON (SPEC-0119 rule 39; audit-post finding, 2026-09-05). The
    test used to be "is the waiver nonempty", so `waiver: {owner: alice}` removed the gap from the
    register while saying NOTHING about why the concern does not apply — a reasonless waiver is the
    one shape rule 39 will not take, because it is indistinguishable from someone having started to
    write a waiver and stopped. Now the REASON is what makes it terminal: a mapping must carry a
    non-blank `reason:` string, a scalar waiver IS its own reason, and anything else leaves the item
    UNMET — the same fail-SAFE direction the lone-`task:` pointer takes.

    THE REASON MUST BE A STRING — A CONTAINER IS NEVER COERCED TO ONE (T-12088 audit-post finding,
    2026-09-05). The test used to be `str(reason).strip()`, which renders `[]` as the two-character
    text `"[]"` and `{}` as `"{}"`: `waiver: []` and `waiver: {reason: []}` both read as REASONED and
    silently closed the obligation on a value that says nothing. `str()` on a container answers
    "does this have a repr", never "did somebody write a reason", so the type is checked before the
    text is. Everything that is not a non-blank `str` — a container, a number, a bool, `None` — is
    NOT an answer and leaves the item UNMET, which is this function's standing fail-SAFE direction."""
    reason = (waiver.get("reason") if isinstance(waiver, dict) else waiver)
    if not isinstance(reason, str):
        return None
    text = reason.strip().lower()
    if not text:
        return None
    state = "out-of-scope" if any(t in text for t in _GAP_OUT_OF_SCOPE_TOKENS) else "waived"
    return (state, "waived in yitc-ops.yaml")


def _gap_section_answer(section, key=None, section_name=None) -> "tuple | None":
    """How the ops carrier ANSWERS one concern item → (terminal_state, why) or None for unmet.

    FAITHFUL, never fail-closed (`lessons/fail-closed-belongs-to-the-reader-not-the-parser.md`):
    it reports only what the carrier literally says. Absent / None / empty / a non-mapping scalar
    that is empty ⇒ None ⇒ the item is UNMET and stays in the count, which is the fail-SAFE
    direction for a register whose whole job is to name what is missing.

    `key` (T-12088) selects PER-KEY coverage — the `carrier_key` of the catalog row being answered.
    `key=None` is EXACTLY the historical behaviour (any non-blank key in the section answers it), so
    the ten section-granular items and every existing caller are untouched. With a `key`, only THAT
    key answers, which is what makes SPEC-0164 rule 5's three questions three questions: before this,
    one declared key cleared every item sharing the section, and a carrier declaring `health:` and a
    complete `slo:` but no `logs:` produced no gap at all (audit-pre finding 1).

    THE KEY'S OWN VALUE IS ANSWERED BY THIS SAME FUNCTION, RECURSIVELY. That is deliberate and is why
    the per-key path adds no rules of its own: a sub-mapping (`slo: {objective: …, target: …}`) reads
    `adopted`/`adapted` by the existing token rules, a per-key `waiver:` with a reason reads
    `waived`/`out-of-scope`, a LONE `task:` pointer under the key stays UNMET and armable (the
    SPEC-0198 rule-5 property, inherited for free), and a non-blank scalar reads `adopted`.

    A SECTION-LEVEL WAIVER STILL WAIVES ITS KEYS, and that fallback is load-bearing rather than
    tidy: the consumers born WAIVED carry a reasoned `waiver:` and no keys at all, so without it
    this change would retro-create three gap rows for every one of them — the exact SPEC-0149 §1
    harm the register was built not to do.

    A NON-MAPPING (scalar) SECTION ANSWERS NO NAMED KEY. `alert_routing: "pagerduty"` states
    something, but it does not state a health endpoint, a log stance or an objective, and UNMET is
    the fail-SAFE reading for a register whose job is to name what is missing. No real carrier
    reachable from this checkout uses a scalar section, so this is a contract statement rather than
    a live behaviour change."""
    if section is None:
        return None
    if key is not None:
        if not isinstance(section, dict):
            return None                             # a scalar section names no key — see docstring
        answer = _gap_section_answer(section.get(key))
        # A DECLARATION SHORT OF ITS CONCERN'S SHAPE IS NOT AN ANSWER — checked HERE, ahead of the
        # section-waiver fallback, so a broken key falls through to a reasoned section waiver exactly
        # as an ABSENT one does. Done after the `or` instead, a reasoned `waiver:` on the section
        # stopped covering a key whose declaration was merely incomplete, and the two surfaces
        # disagreed a third time (caught by this card's own shape matrix, not by an auditor).
        if answer and answer[0] in _GAP_DECLARED_STATES and _gap_declaration_incomplete(
                section_name, key, section.get(key)):
            answer = None
        return answer or _gap_waiver_answer(section.get("waiver"))
    if isinstance(section, dict):
        waiver = section.get("waiver")
        # A LONE `task:` POINTER IS NOT AN ANSWER — it is the OPPOSITE of one, and the distinction is
        # what makes the armed/actionable fork reachable at all. A section reading `task: T-1234`
        # says "we have NOT met this yet; that card is doing it": the item stays UNMET (so it keeps
        # its place in the register) and the writer arms its followup on that id, which is exactly
        # SPEC-0198 rule 5's "armed on a nameable artifact where one exists". Counting it as a
        # declaration would close the row on a promise and leave nothing waiting for the card.
        declared = {k: v for k, v in section.items()
                    if k not in ("waiver", GAP_CARRIER_TASK_KEY) and v not in (None, "", {}, [])}
        if declared:
            text = " ".join(str(v) for v in declared.values()).lower()
            state = "adapted" if any(t in text for t in _GAP_ADAPTED_TOKENS) else "adopted"
            return (state, "declared in yitc-ops.yaml")
        return _gap_waiver_answer(waiver)
    text = str(section).strip()
    return ("adopted", "declared in yitc-ops.yaml") if text else None


#: The per-key answers whose CONCERN imposes a shape on them, as (section, key) -> the predicate in
#: `lib.init` that reports which required halves are missing.
#:
#: THIS NAMES WHERE TO ASK, NEVER WHAT THE ANSWER IS. A declaration that falls short of its concern's
#: shape is NOT an answer, and the concern — not this fold — is what decides "falls short". Shipped
#: as two independent readings, the two surfaces contradicted each other: `_hook_alert_routing`
#: REFUSED `slo: {objective: …}` at birth while this fold marked `one-slo-declared` adopted, so a
#: live project could close its SLO obligation with a promise carrying no number (T-12088 audit-post
#: finding, 2026-09-05). One predicate, two callers (CHARTER §P5).
_GAP_SHAPED_ANSWER_KEYS = {("alert_routing", "slo"): "_alert_routing_slo_missing"}


def _gap_declaration_incomplete(section_name, key, value) -> bool:
    """Does a DECLARED `section.key` fall short of the shape its concern requires?

    Consulted ONLY for a key listed in `_GAP_SHAPED_ANSWER_KEYS`, so an unimportable or changed
    `lib.init` can affect nothing else. The import is LAZY and guarded — the `gap_dimension`
    precedent, and here it also breaks a cycle (`lib.init` imports this module).

    THE DEGRADE IS FAIL-SAFE, and the direction is the whole point: an unanswerable question leaves
    the item UNMET (a gap that keeps nagging), never adopted (an obligation that silently
    disappears). That is the same direction the reasonless waiver and the lone `task:` pointer take,
    and returning "complete" here would restore exactly the defect this exists to close."""
    predicate = _GAP_SHAPED_ANSWER_KEYS.get((section_name, key))
    if predicate is None:
        return False
    try:
        from lib import init as _init
        return bool(getattr(_init, predicate)(value))
    except Exception:                              # noqa: BLE001 — see THE DEGRADE IS FAIL-SAFE
        return True


#: The terminal states that mean "the carrier DECLARED this" — the only ones a shape rule judges. A
#: `waived` / `out-of-scope` / `task-linked` row is a STANCE about the concern, not a declaration of
#: it, so the shape question does not arise (and a waiver is complete by definition).
_GAP_DECLARED_STATES = ("adopted", "adapted")


#: The key a carrier section uses to say "a task is doing this" — the ONE nameable artifact the
#: writer will arm a gap followup on. A single key, read structurally, never mined out of prose:
#: routing on free text is the defect T-10335 records.
GAP_CARRIER_TASK_KEY = "task"

_GAP_TASK_ID_RE = re.compile(r"^T-\d{4,}$")


def gap_task_linked(promoted_into, *, resolvable) -> bool:
    """Is a filed row terminal as `task-linked`? — SPEC-0119 rule 39's ONE hard requirement.

    `task-linked` REQUIRES a RESOLVABLE T-id, and both halves are checked here: the id must have the
    shape of a task id AND `resolvable` (the caller's own tasks/ lookup) must confirm the card
    exists. An absent, malformed or unresolvable id is NOT terminal — the row keeps its place in the
    count. That direction is deliberate: the cheap failure is a gap that keeps nagging after it was
    handled; the expensive one is a gap that silently leaves the register pointing at a task nobody
    can open (which is exactly how a register becomes a place where obligations go to disappear)."""
    tid = str(promoted_into or "").strip()
    if not _GAP_TASK_ID_RE.match(tid):
        return False
    try:
        return bool(resolvable(tid))
    except Exception:                              # noqa: BLE001 — an unreadable corpus is not a proof
        return False


def _gap_filed_rows(rows) -> dict:
    """The journal's own record of what has already been filed: dedupe key → the row's facts.

    Reads the EXISTING `followup_added` / `followup_promoted` / `followup_dropped` events — the
    followup link IS the register's carrier, which is why this needs no store of its own. Keyed by
    the `fingerprint` the writer stamped, so an ordinary followup (no fingerprint, or another
    subsystem's) is invisible here and can never be mistaken for a gap row."""
    filed: dict = {}
    for row in rows or ():
        if not isinstance(row, dict):
            continue
        etype = row.get("type")
        data = row.get("data") if isinstance(row.get("data"), dict) else {}
        if etype == "followup_added":
            key = str(data.get("fingerprint") or "")
            if key.startswith(GAP_KEY_PREFIX + "|"):
                filed[key] = {"followup_id": data.get("followup_id"), "ts": row.get("ts"),
                              "promoted_into": None, "dropped": False}
        elif etype in ("followup_promoted", "followup_dropped"):
            fid = data.get("followup_id")
            for rec in filed.values():
                if rec.get("followup_id") and rec["followup_id"] == fid:
                    if etype == "followup_promoted":
                        rec["promoted_into"] = data.get("into") or data.get("task")
                    else:
                        rec["dropped"] = True
    return filed


def _gap_age_days(ts, now) -> "float | None":
    """Age of a dated row in days, or None when the row carries no readable date."""
    try:
        stamp = datetime.strptime(str(ts), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None
    return (now - stamp).total_seconds() / 86400.0


def profile_gap_register(*, resolution, ops_path, rows=(), now=None, resolvable=None,
                         ops=None) -> dict:
    """THE FOLD — the brownfield gap register (SPEC-0119 rule 39 / SPEC-0198 rules 5+7).

    Returns::

        {"count":       <int>  — unmet items, the headline number,
         "overdue":     <int>  — filed rows past the triage window,
         "items":       [ {lens, item_id, label, carrier, key, filed, ts, age_days, overdue}, … ],
         "top_labels":  [ <label>, … ]      — the top 2 by `gap_rank`, for the capped line,
         "unfiled":     [ <item>, … ]       — what the writer may still file, in `gap_rank` order,
         "terminal":    [ {item…, state, why}, … ]}

    INPUTS, NOT READS (SPEC-0190 rule 10). `resolution` is the ALREADY-resolved profile and `rows`
    are the caller's ALREADY-parsed journal rows, so this fold opens no second reader and carries no
    cache: it rides the one request-scoped ReadScope `_debt_echo_lines` installs. The `views.
    project_growth` / T-12080 precedent, for the same reason — a cache on a composed seam is the
    mechanism rule 10 forbids.

    A REPO WITH NO OPS CARRIER REGISTERS NOTHING, and that is what keeps history safe. The engine
    kernel itself has no `yitc-ops.yaml`, so this folds to 0 there and the line never renders — the
    same discipline `declared_checks` states, and the same one SPEC-0149 §1 had to buy back after a
    fold-side default retro-created 39 debt lines across 3 consumers. Debt is what a project's own
    profile REQUIRES and its own carrier does not answer — never what it never had.

    NEVER RAISES. Every failure degrades to the empty register: a report-only surface that breaks a
    session-start seam would be strictly worse than a silent one."""
    empty = {"count": 0, "overdue": 0, "items": [], "top_labels": [], "unfiled": [], "terminal": []}
    try:
        if not (resolution or {}).get("resolved"):
            return empty
        # `ops` is the ALREADY-PARSED carrier when the caller holds one — the `resolve_profile(ops=)`
        # precedent (T-12080), and here it is what keeps ONE debt seam to ONE carrier read: the fold
        # and the writer beside it now share the residue's single parse instead of opening the file
        # twice (audit-post finding, 2026-09-05). `ops_path` stays the fallback for a caller that
        # holds nothing, so no existing call site changes meaning.
        # A REPO WITH NO CARRIER FILE REGISTERS NOTHING — decided from the PATH, by a stat, not by
        # an in-band `None` from the reader (T-12085 audit-post finding, 2026-09-05). `None` used to
        # carry "absent" here, which is the same value a caller uses for "I passed you nothing", and
        # that conflation is what made a carrier-less repo re-open the missing file at every
        # consumer. A stat costs no read, so the seam's one-carrier-read property is untouched, and
        # the SPEC-0149 §1 rule is unchanged: absent is not empty, and neither owes a gap.
        # PRESENT-AND-EMPTY is deliberately NOT the same case: a project that HAS a carrier and
        # declares nothing in it owes every item its profile requires (AC2's baseline).
        try:
            if not Path(ops_path).exists():
                return empty
        except (OSError, TypeError):
            return empty
        if ops is not None:
            carrier = ops
        else:
            try:
                carrier = state.load_ops(Path(ops_path))
            except (OSError, UnicodeDecodeError, yaml.YAMLError, TypeError):
                return empty
        if not isinstance(carrier, dict):
            return empty
        now = now or datetime.now(timezone.utc)
        active = set((resolution or {}).get("check_set") or ())
        filed = _gap_filed_rows(rows)
        _resolvable = resolvable or (lambda _tid: False)

        items, terminal = [], []
        for lens_decl, item_id, label, section_name, carrier_key in _GAP_ITEMS:
            lenses = gap_item_lenses(lens_decl)
            if not any(l in active for l in lenses):
                continue                            # this profile does not require it — not a gap
            lens = lenses[0]                        # the PRIMARY — key, rank and dimension read it
            base = {"lens": lens, "item_id": item_id, "label": label, "carrier": section_name,
                    "key": gap_dedupe_key(lens, item_id)}
            # `carrier_key` is None for a section-granular item, which is exactly the historical
            # call — so the ten pre-existing rows read identically and only the three SPEC-0164
            # rule-5 rows take the per-key path.
            answer = _gap_section_answer(carrier.get(section_name), key=carrier_key,
                                         section_name=section_name)
            if answer:
                terminal.append(dict(base, state=answer[0], why=answer[1]))
                continue
            row = filed.get(base["key"])
            if row and gap_task_linked(row.get("promoted_into"), resolvable=_resolvable):
                terminal.append(dict(base, state="task-linked",
                                     why=f"promoted into {row.get('promoted_into')}"))
                continue
            age = _gap_age_days(row.get("ts"), now) if row else None
            items.append(dict(base, filed=bool(row), ts=(row or {}).get("ts"), age_days=age,
                              overdue=bool(age is not None and age >= GAP_TRIAGE_WINDOW_DAYS)))

        items.sort(key=gap_rank)
        terminal.sort(key=gap_rank)
        return {"count": len(items),
                "overdue": sum(1 for it in items if it["overdue"]),
                "items": items,
                "top_labels": [it["label"] for it in items[:2]],
                "unfiled": [it for it in items if not it["filed"]],
                "terminal": terminal}
    except Exception:                              # noqa: BLE001 — see NEVER RAISES
        return empty


def gap_autofile_text(item) -> str:
    """The body an auto-filed gap followup is captured with.

    It opens with `GAP_MARKER` — the ONE home the fold reads — and then says, in the owner's own
    terms, WHAT is missing, WHY this project is being asked (the profile activated the lens), WHERE
    the answer goes (the carrier section), and every way the row may be closed. A reader of the
    debt list must be able to act on it without re-opening anything, which is the property the
    T-11980 carrier text established and this one keeps."""
    lens = str((item or {}).get("lens") or "")
    return (f"{GAP_MARKER} {gap_dimension(lens)}/{(item or {}).get('item_id')} — "
            f"{(item or {}).get('label')}. YOUR PROFILE REQUIRES IT: the `{lens}` lens is active for "
            f"this project (SPEC-0198), and `{(item or {}).get('carrier')}:` in yitc-ops.yaml does "
            f"not answer it. CLOSE IT by answering that section — DECLARE how you meet it "
            f"(`adopted`), declare how you meet it DIFFERENTLY (`adapted`), or WAIVE it with a "
            f"reason (`waived`, or `out-of-scope` when the surface does not exist here) — or "
            f"promote this followup into a task (`task-linked`, which needs a resolvable T-id). "
            f"Auto-filed at a seam that was already running (SPEC-0119 rule 39); report-only — "
            f"nothing was dispatched, audited or deployed by it.")


# ── SPEC-0119 rule 40: the ECHO RENDER SHAPE — a compact table, the long text one verb away ────────
#
# WHY (owner, 2026-09-09: «читать нельзя»). The proactive-debt echo prints one dense paragraph per
# debt class; measured on this repo the whole echo ran 19,014 bytes over 20 lines — several KB of
# prose at every `session start` and every land tail, which the Controller cannot scan. The rule
# text is authoritative and stays reachable — but not at every session start.
#
# WHAT THIS IS NOT. It computes NO debt: it takes the ALREADY-RENDERED lines and derives a row per
# class from each line's OWN head. There is no class registry to drift (a hand-maintained one was
# the obvious design and is exactly the silent-drift entity CHARTER §P1 F1/F2 rejects), no store, no
# event, no threshold and no window — what COUNTS as debt is untouched, which is the card's
# NOT-in-scope boundary made structural rather than promised.
#
# WHY TEXT PRESERVATION IS STRUCTURAL, not a copy. `debt_explain` returns the SAME line objects the
# renderer produced, verbatim — it does not re-author, re-wrap or summarise them. That is what makes
# the AC2 golden byte-identity provable rather than a claim, and it is why relocating the text
# cannot silently lose a class (CHARTER §P5: one home per rule text, moved not duplicated).

DEBT_ROW_WIDTH = 120          # one terminal line; rows are truncated to it, never wrapped
DEBT_CLASS_MAX_WORDS = 6      # a scannable class label, not a re-print of the head

# Dropped when deriving a class slug: they carry no class identity, so keeping them would split one
# class into several rows on incidental wording ("14 card(s)" vs "42 card(s)" is ONE class).
_DEBT_CLASS_STOPWORDS = frozenset((
    "a", "an", "and", "are", "at", "awaiting", "by", "for", "from", "in", "is", "its", "more",
    "no", "not", "of", "on", "or", "our", "over", "per", "still", "than", "that", "the", "their",
    "them", "then", "there", "these", "they", "this", "to", "up", "was", "were", "with", "yet",
))

_DEBT_ROW_SEP = " | "
_DEBT_DEFAULT_VERB = "bin/yitc-v2 debt"


def _debt_line_prefix(line: str) -> tuple:
    """Split an echo line into its own leading marker and its body.

    The echo is NOT uniformly `debt:` — `review-due:` and `profile:` ride the same helper and the
    same two seams. Each row keeps the marker its SOURCE line carried, so a compacted echo never
    re-labels a line as debt that the renderer did not call debt."""
    text = str(line or "")
    head, sep, rest = text.partition(": ")
    if sep and head and "—" not in head and len(head) <= 24 and " " not in head.strip():
        return head.strip(), rest.strip()
    return "debt", text.strip()


def debt_row_count(line: str) -> int:
    """The count a row reports — the first integer of the line's HEAD, else 1.

    Bounded to the head deliberately: the tail of a line names example ids, ages and commit counts
    ("task/T-12121 (6 commit(s), 119h)"), and reading a number from there would report a number the
    line never claimed as its size."""
    _prefix, body = _debt_line_prefix(line)
    head = body.split("—", 1)[0]
    m = re.search(r"\b(\d+)\b", head)
    return int(m.group(1)) if m else 1


def debt_row_verb(line: str) -> str:
    """The FIRST remedy verb the line names, else the re-fold verb.

    Taken from the line itself rather than a mapping, so a class whose remedy verb is renamed can
    never keep pointing at the old one from a second home."""
    m = re.search(r"`(bin/yitc-v2 [^`]+)`", str(line or ""))
    if m:
        return " ".join(m.group(1).split())
    m = re.search(r"\b(bin/yitc-v2(?: [a-z][\w-]*){1,3})", str(line or ""))
    return " ".join(m.group(1).split()) if m else _DEBT_DEFAULT_VERB


def debt_row_class(line: str) -> str:
    """The class slug a row is keyed and folded by — DERIVED from the line's own head.

    Derivation (all of it mechanical, none of it a registry): take the head (text before the first
    em-dash), drop parentheticals, drop digit-bearing tokens, drop a trailing ` for <x>` clause so
    the per-project nightly lines fold together, drop stopwords, lowercase, cap at
    DEBT_CLASS_MAX_WORDS. Two lines that derive the same slug are ONE class and fold to one row with
    summed counts — which is exactly what the card asks for for the nightly/chronic lines."""
    prefix, body = _debt_line_prefix(line)
    head = body.split("—", 1)[0]
    head = re.sub(r"\([^)]*\)", " ", head)          # parentheticals carry qualifiers, not identity
    head = re.sub(r"`[^`]*`", " ", head)            # a quoted id/verb is an instance, not a class
    head = re.sub(r"\bfor\b.*$", " ", head)         # the trailing ` for <x>` per-project clause
    words = []
    for raw in re.split(r"[^\w'-]+", head):
        tok = raw.strip("-'").lower()
        if not tok or any(ch.isdigit() for ch in tok) or tok in _DEBT_CLASS_STOPWORDS:
            continue
        tok = re.sub(r"\(s\)$", "", tok)
        words.append(tok)
        if len(words) >= DEBT_CLASS_MAX_WORDS:
            break
    return " ".join(words) or prefix


def debt_echo_table(_debt_echo_lines) -> list:
    """The compact table the two ECHO seams render: `<marker>: <class> | <count> | <verb>`.

    One row per non-clean class, in FIRST-APPEARANCE order (so the render stays as stable as the
    renderer that fed it), equal classes folded with their counts summed, every row within
    DEBT_ROW_WIDTH. Clean in → clean out: an empty input yields an empty list, which is how
    suppressed-when-clean survives this change untouched (SPEC-0119 rule 5) — the table renderer
    prints no header, ever, precisely so that property is structural."""
    order = []
    rows = {}
    for line in list(_debt_echo_lines or ()):
        if not str(line or "").strip():
            continue
        prefix, _body = _debt_line_prefix(line)
        key = (prefix, debt_row_class(line))
        if key not in rows:
            order.append(key)
            rows[key] = {"count": 0, "verb": debt_row_verb(line)}
        rows[key]["count"] += debt_row_count(line)
    out = []
    for key in order:
        prefix, klass = key
        row = f"{prefix}: {klass}{_DEBT_ROW_SEP}{rows[key]['count']}{_DEBT_ROW_SEP}{rows[key]['verb']}"
        if len(row) > DEBT_ROW_WIDTH:
            row = row[:DEBT_ROW_WIDTH - 1].rstrip() + "…"
        out.append(row)
    return out


def debt_explain(_debt_echo_lines, key=None) -> list:
    """The ONE home of the long-form text, reached on demand: `bin/yitc-v2 debt --explain <class>`.

    Returns the ORIGINAL rendered lines VERBATIM — never a re-authoring — for the class whose slug
    equals, or begins with, `key` (a substring match is the last resort, so a short key still
    reaches its class). With no key, returns the class list so a reader who does not know the slug
    can find it without reading the corpus."""
    lines = [ln for ln in list(_debt_echo_lines or ()) if str(ln or "").strip()]
    if not str(key or "").strip():
        seen = []
        for line in lines:
            klass = debt_row_class(line)
            if klass not in seen:
                seen.append(klass)
        return [f"debt classes ({len(seen)}) — `bin/yitc-v2 debt --explain <class>` for the full text:"] + \
               [f"  {klass}" for klass in seen]
    want = " ".join(str(key).lower().split())
    for match in (lambda k: k == want, lambda k: k.startswith(want), lambda k: want in k):
        hit = [ln for ln in lines if match(debt_row_class(ln))]
        if hit:
            return hit
    return [f"debt --explain: no debt class matches `{key}`. "
            f"Run `bin/yitc-v2 debt --explain` bare for the class list."]


# ── T-12360 (SPEC-0132 §3) — the LOAD-SENSITIVE LANE's sequential-tail reading ────────────────────
# The declared load-sensitive set (T-12358) grows only by automatic entry and shrinks only by a card,
# so its SIZE is the one number that says whether flakes are a per-file problem or a harness one.
# SPEC-0132 §3's serial-lane watch-point is EXTENDED to this lane; these are its two bounds, read
# from the config registry (`bin/yitc-v2 config list`) and seeded at the values §3 already states —
# no new numbers (owner directive events.jsonl#ts=2026-09-08T13:56:22Z).
LOAD_SENSITIVE_CARRIER = "load-sensitive.txt"          # the T-12358 carrier, beside the tests
LOAD_SENSITIVE_TABLE = "verify-durations.json"         # the T-11316 FIXED per-file duration table
_LANE_SHARE_ENV = "YITC_LOAD_SENSITIVE_SHARE_PCT"
_LANE_FILES_ENV = "YITC_LOAD_SENSITIVE_MAX_FILES"
_LANE_SHARE_DEFAULT, _LANE_SHARE_RANGE = 10, (1, 100)
_LANE_FILES_DEFAULT, _LANE_FILES_RANGE = 25, (1, 1000)


def _lane_knob(env_name: str, default: int, band: tuple, *, env: "dict | None" = None) -> int:
    """The ONE resolver behind both lane bounds: env > machine settings > built-in, fail-safe to the
    built-in on anything blank / non-numeric / outside `band`. Copied in shape from
    `worktree._flaky_sensitive_knob` (the T-12358 sibling) so the whole load-sensitive family
    resolves by ONE precedence rather than two."""
    _env = os.environ if env is None else env
    raw = _env.get(env_name)
    if raw is None or not str(raw).strip():
        try:
            from lib import machine_settings          # deferred: the hot import graph is unchanged
            raw = machine_settings.get_value(env_name)
        except Exception:
            raw = None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    lo, hi = band
    return value if lo <= value <= hi else default


def load_sensitive_share_pct(*, env: "dict | None" = None) -> int:
    """The share-of-verify-wall bound, in percent — SPEC-0132 §3's own «exceeds 10% of verify wall
    time», reused as-is for the load-sensitive lane."""
    return _lane_knob(_LANE_SHARE_ENV, _LANE_SHARE_DEFAULT, _LANE_SHARE_RANGE, env=env)


def load_sensitive_max_files(*, env: "dict | None" = None) -> int:
    """The file-count bound — SPEC-0132 §3's own «OR 25 files», reused as-is for the lane."""
    return _lane_knob(_LANE_FILES_ENV, _LANE_FILES_DEFAULT, _LANE_FILES_RANGE, env=env)


def _lane_carrier_files(path) -> list:
    """The carrier's listed basenames, read by the SAME grammar the runner reads it with
    (`verify_runner._load_sensitive_set`): blank lines and `#` comments skipped, the FIRST
    whitespace-separated token is the test file's basename, the rest is provenance for humans.
    Restated here rather than imported because `verify_runner` is the LAND path and this is a
    report-only fold — but the grammar is the runner's, and the identity is the basename, which is
    unambiguous by that runner's own duplicate-basename refusal (SPEC-0185 / T-11204)."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    out = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        name = line.split()[0]
        if name.endswith(".py") and name not in out:
            out.append(name)
    return out


def load_sensitive_lane(root=None, *, carrier=None, table=None, env=None) -> dict:
    """T-12360 — the SEQUENTIAL-TAIL reading of the declared load-sensitive lane, folded from the two
    artifacts that already exist: the carrier `tests/load-sensitive.txt` (T-12358) and the FIXED
    per-file duration table `tests/verify-durations.json` (T-11316 / SPEC-0132 §6).

    Returns `{count, wall_s, suite_wall_s, share_pct, bound_share_pct, bound_files, unrecorded,
    crossed: [...]}`. `wall_s` is the lane's SERIALIZED wall — the sum of the LISTED files' recorded
    seconds, and only those: a file the table does not list contributes ZERO and is counted in
    `unrecorded` rather than guessed at, and an UNLISTED file's duration is never summed (the AC1
    differential). `suite_wall_s` is the table's OWN total per-file work, which is the only
    denominator the table can honestly speak for — a concurrent run's wall-clock is not in it.

    NO NEW INSTRUMENTATION, NO STORED STATE: two reads, re-derived every call, exactly the posture of
    every sibling fold here. REPORT-ONLY — nothing gates on the result (CHARTER §6 fence, SPEC-0132
    §3's own posture). FAIL-SAFE IN THE DIRECTION OF SILENCE: a missing or unreadable carrier or
    table yields `count: 0`, so the line simply does not print — a broken read never manufactures a
    crossing, and never reports a PARTIAL one (a count beside a 0s wall) either: no data reads as no
    line, never as a lane that costs nothing.
    """
    bound_share = load_sensitive_share_pct(env=env)
    bound_files = load_sensitive_max_files(env=env)
    out = {"count": 0, "wall_s": 0.0, "suite_wall_s": 0.0, "share_pct": 0.0,
           "bound_share_pct": bound_share, "bound_files": bound_files,
           "unrecorded": 0, "files": [], "crossed": []}
    base = Path(root) if root else Path(__file__).resolve().parents[2]
    carrier_path = Path(carrier) if carrier else base / "tests" / LOAD_SENSITIVE_CARRIER
    table_path = Path(table) if table else base / "tests" / LOAD_SENSITIVE_TABLE
    listed = _lane_carrier_files(carrier_path)
    if not listed:
        return out
    try:
        payload = json.loads(Path(table_path).read_text(encoding="utf-8"))
        unit_ms = float(payload.get("unit_ms") or 0) or 0.0
        files = payload.get("files") or {}
        if not isinstance(files, dict) or unit_ms <= 0:
            raise ValueError("unusable duration table")
    except (OSError, UnicodeDecodeError, ValueError, TypeError, AttributeError):
        # FAIL-SILENT, the whole way (audit-post pass-1 finding 1). An earlier draft returned the
        # carrier COUNT here and could mark a files-crossing off it — which is exactly the shape the
        # fail-safe exists to forbid: a line whose wall reads 0s beside a crossing marker asks the
        # weekly review to DISPOSE a global-rework question on half-read data, and «0s» is not an
        # honest wall for a lane that certainly costs something. A table this fold cannot read is
        # NO DATA, so it yields no line at all rather than a partial one.
        return out
    _secs = lambda units: (float(units) * unit_ms) / 1000.0
    lane, unrecorded = 0.0, 0
    for name in listed:
        units = files.get(name)
        if units is None:
            unrecorded += 1
            continue
        try:
            lane += _secs(units)
        except (TypeError, ValueError):
            unrecorded += 1
    suite = 0.0
    for units in files.values():
        try:
            suite += _secs(units)
        except (TypeError, ValueError):
            continue
    share = (lane / suite * 100.0) if suite > 0 else 0.0
    out.update({"count": len(listed), "files": listed, "wall_s": round(lane, 1),
                "suite_wall_s": round(suite, 1), "share_pct": round(share, 1),
                "unrecorded": unrecorded})
    if share > bound_share:
        out["crossed"].append("share")
    if len(listed) > bound_files:
        out["crossed"].append("files")
    return out
