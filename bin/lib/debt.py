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
import functools           # T-12698: the host residues wrap their moved bodies
import hashlib
import json
import inspect             # T-12698: `_residue_binds` derives each residue's historical signature
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
from lib import debt_landing  # T-12698: the extracted LANDING debt-view family (C9a)
from lib import debt_spec0161  # T-12703: the extracted SPEC-0161 payload-key family (C9b)
from lib import debt_adoption  # T-12707: the extracted ADOPTION debt-view family (C9c)


def _residue_binds(residue) -> None:
    """T-12698 — give a host residue its HISTORICAL signature. The residue's keyword-only `_inj` default
    is the tuple of HOST names it re-supplies from `globals()` at call time (host stayers, moved
    siblings via THEIR residue, the registry dict, and every moved constant the body reads — so a
    host-side rebind / monkeypatch is honoured; read as a default, never through the residue's own
    global name, which a test may have patched). `__signature__` = the leaf's signature minus those
    injected keyword-only params, so `inspect.signature(debt.<sym>)` still reads the pre-move
    contract that structural tests pin (`inspect.getsource` keeps unwrapping to the moved body)."""
    injects = residue.__kwdefaults__["_inj"]
    sig = inspect.signature(residue.__wrapped__)
    residue.__signature__ = sig.replace(parameters=[p for p in sig.parameters.values() if p.name not in injects])


# The stamped-window CARRIERS the fold reads (SPEC-0149 §1, verbatim). Only `deploy_completed` is
# STAMPED today (one writer — `cmd_deploy`; a second stamping site would be the dual source the
# one-window rule forbids). `deploy_backup_taken` is named by the spec as the alternate carrier and
# is read here, so a stamped backup event folds identically the day the spec's other half lands —
# without this reader growing a special case for it.
OBLIGATION_CARRIER_EVENTS = ("deploy_completed", "deploy_backup_taken")

# The CLOSING event: the recheck that discharges the obligation. It carries `{project, revision}` and
# rides the EXISTING generic `event` verb (`bin/yitc-v2 event deploy_recheck_completed --data …`) —
# SPEC-0149 §2 admits no new verb, emitter, or store for it.
OBLIGATION_CLOSING_EVENT = debt_adoption.OBLIGATION_CLOSING_EVENT   # T-12707 host re-export alias — moved WITH its readers

# The SECOND discharge: the honest MISS (T-11169, <project> X-0923). Rule 1 defined exactly ONE exit —
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
OBLIGATION_MISS_EVENT = debt_adoption.OBLIGATION_MISS_EVENT   # T-12707 host re-export alias — moved WITH its readers

# The JUDGEMENT is what keeps the miss from decaying into a "remove the line" button (owner refinement
# (a), 2026-08-16): the operator must state WHY a late re-check is or is not meaningful. It is gated
# fail-closed at the WRITE (`bin/yitc-v2#cmd_event`); this reader holds the same floor, because a
# judgement-less row that reached the journal by any other route must discharge nothing either.
OBLIGATION_MISS_JUDGEMENT_KEY = debt_adoption.OBLIGATION_MISS_JUDGEMENT_KEY   # T-12707 host re-export alias — moved WITH its readers

# The rolling window the DISCHARGE COUNTS below are reported over — the `recent_gate_overrides`
# (SPEC-0119 rule 14) analog, chosen for the same reason: a governed bypass must stay visible AFTER the
# fact, and an unbounded total would become a monument nobody reads instead of a live signal. Owner
# refinement (b): the miss stays COUNTABLE after discharge, so a systematic pattern of unmet windows
# does not vanish with the line it silenced.
MISS_WINDOW_DAYS = debt_adoption.MISS_WINDOW_DAYS   # T-12707 host re-export alias — moved WITH its readers


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
    class (SPEC-0165), and it is not cheap here: at <project> seven governance events had to be
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
        # T-13139 — the DECLARED read: only the carrier types this fold keeps (the whole history).
        for event in journal.segment_rows(events_path, types=OBLIGATION_CARRIER_EVENTS):
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


@functools.wraps(debt_adoption._superseded_before_deadline)
def _superseded_before_deadline(*a, **kw):
    """T-12707 host residue — the body now lives in `bin/lib/debt_adoption.py#_superseded_before_deadline`."""
    return debt_adoption._superseded_before_deadline(*a, **kw)


@functools.wraps(debt_adoption.open_proof_obligations)
def open_proof_obligations(*a, _inj=("MISS_WINDOW_DAYS", "OBLIGATION_CARRIER_EVENTS",
                                     "OBLIGATION_CLOSING_EVENT", "OBLIGATION_MISS_EVENT",
                                     "OBLIGATION_MISS_JUDGEMENT_KEY", "_obligation_key",
                                     "_parse_stamped_deadline", "_superseded_before_deadline",), **kw):
    """T-12707 host residue — body in `bin/lib/debt_adoption.py#open_proof_obligations`; host names read HERE at call time."""
    for _k in _inj:
        kw.setdefault(_k, globals()[_k])
    return debt_adoption.open_proof_obligations(*a, **kw)
_residue_binds(open_proof_obligations)


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


# ── SPEC-0189 rule 9 (T-13062): the OWNER DISPOSITION of ONE firing ────────────────────────────────
#
# THE GAP THIS CLOSES, measured on <project> (revizia-consumers-2026-09-27): the owner weighed the
# surface-2 proposal and answered LEAVE, but the answer existed only as prose inside a case `reason`,
# so the same proposal re-rendered at every session start for as long as its detector saw the same
# pair. The carrier is a list in the concern's OWN contract section — a project act in the project's
# own contract, which is what rule 4 requires — and it answers ONE FIRING, never the surface: a
# firing on different evidence renders open again, whatever was answered before.
#
# FAIL-OPEN TO VISIBILITY. Every entry the reader cannot trust — a non-mapping, an unknown action, a
# missing or mistyped field, a firing named twice — is REPORTED as a fault and silences nothing. The
# worst a malformed carrier can do is leave the proposal open, which is the state before this rule.
RESTORATION_DISPOSITION_KEY = "restoration_dispositions"
RESTORATION_DISPOSITION_ACTIONS = ("leave", "narrow", "restore")
_DISPOSITION_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")


def _proposal_firing(record, signal) -> str:
    """The stable identity of ONE firing: the detector's own `firing` token when it supplies one
    (surface 2 names its `<citing>:<exempted>` pair), else a hash of the observed signal — so the
    identity moves exactly when the evidence does."""
    token = record.get("firing") if isinstance(record, dict) else None
    if isinstance(token, str) and token.strip():
        return token.strip()
    return "sig:" + hashlib.sha256(str(signal or "").encode("utf-8")).hexdigest()[:12]


def _restoration_dispositions(contract, surface) -> tuple:
    """SPEC-0189 rule 9 — the VALID owner dispositions recorded for `surface`, and the FAULTS.
    Returns `(valid, faults)`: `valid` is `{firing: entry}`, `faults` a list of `{surface, reason}`.

    Pure and tolerant: reads the already-parsed contract the seam holds (no second parse), never
    raises, writes nothing. An absent or unreadable contract, or a section declaring no dispositions,
    answers `({}, [])` — nothing recorded, so nothing silenced."""
    section = _gap_carrier_section(contract, surface) if isinstance(contract, dict) else None
    entries = section.get(RESTORATION_DISPOSITION_KEY) if isinstance(section, dict) else None
    if entries is None:
        return {}, []
    if not isinstance(entries, list):
        return {}, [{"surface": surface,
                     "reason": f"`{surface}.{RESTORATION_DISPOSITION_KEY}` is not a list"}]
    by_firing: dict = {}
    faults: list = []
    for index, entry in enumerate(entries, 1):
        where = f"`{surface}.{RESTORATION_DISPOSITION_KEY}` entry {index}"
        if not isinstance(entry, dict):
            faults.append({"surface": surface, "reason": f"{where} is not a mapping"})
            continue
        firing, action = entry.get("firing"), entry.get("action")
        decided_at, decided_by = entry.get("decided_at"), entry.get("decided_by")
        problems = []
        if not (isinstance(firing, str) and firing.strip()):
            problems.append("`firing` is not a non-empty string")
        if action not in RESTORATION_DISPOSITION_ACTIONS:
            problems.append(f"`action` {action!r} is not one of {'|'.join(RESTORATION_DISPOSITION_ACTIONS)}")
        if not (isinstance(decided_at, (date, datetime))
                or (isinstance(decided_at, str) and _DISPOSITION_DATE_RE.match(decided_at.strip()))):
            problems.append("`decided_at` is not a YYYY-MM-DD date")
        if not (isinstance(decided_by, str) and decided_by.strip()):
            problems.append("`decided_by` is not a non-empty string")
        if problems:
            faults.append({"surface": surface, "reason": f"{where} is malformed: " + "; ".join(problems)})
            continue
        by_firing.setdefault(firing.strip(), []).append(
            {"firing": firing.strip(), "action": action, "decided_at": str(decided_at).strip(),
             "decided_by": decided_by.strip()})
    valid: dict = {}
    for firing, found in by_firing.items():
        if len(found) > 1:     # no precedence between two answers to one firing — neither counts
            faults.append({"surface": surface, "firing": firing,
                           "reason": f"firing `{firing}` is answered by {len(found)} entries "
                                     f"({', '.join(e['action'] for e in found)}) — a conflict, so none "
                                     f"of them counts"})
        else:
            valid[firing] = found[0]
    return valid, faults


def restoration_proposals(*, project, concerns, growth=None, root=None, _resolve=None,
                          contract=None) -> dict:
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
    THIS function rather than through a re-implementation of it in a test.

    `contract` IS THE PROJECT'S ALREADY-PARSED yitc-ops.yaml (T-13062, SPEC-0189 rule 9) — the seam's
    one carrier read, never a second parse. Each proposal carries its `firing` identity; one whose
    CURRENT firing a valid `leave` answers moves to `disposed`, and a `narrow`/`restore` answer rides
    the still-open proposal as its `disposition`. `disposition_faults` names every entry that could
    not be trusted, and every valid entry naming no current firing on a surface whose detector RAN
    (a degraded surface is not judged stale — its detector said nothing either way). `count` is the
    OPEN proposals only. With no contract the answer is exactly the pre-rule-9 one."""
    import inspect

    resolve = _resolve if _resolve is not None else resolve_born_permissive_detector
    proposals: list = []
    malformed: list = []
    degraded: list = []
    disposed: list = []
    faults: list = []
    ran: dict = {}                        # surface -> the firings its detector reported this fold
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
        current = ran.setdefault(surface.strip(), set())
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
            proposal["firing"] = _proposal_firing(record, proposal["signal"])
            current.add(proposal["firing"])
            proposals.append(proposal)
        else:
            malformed.append(dict(proposal, reason="a proposal names no observed signal — a growth "
                                                   "count alone is not evidence (SPEC-0189 rule 3)"))
    if contract is not None:
        still_open = []
        # A DEGRADED surface's entries are still read and a malformed one still reported; only the
        # stale check is skipped there, because a detector that raised said nothing either way.
        judged = dict.fromkeys((d["surface"] for d in degraded), None)
        judged.update(ran)
        for surface, current in sorted(judged.items()):
            valid, surface_faults = _restoration_dispositions(contract, surface)
            faults.extend(surface_faults)
            for firing in (sorted(set(valid) - current) if current is not None else ()):
                faults.append({"surface": surface, "firing": firing,
                               "reason": f"the `{valid[firing]['action']}` recorded for firing "
                                         f"`{firing}` names no current firing — it answers nothing"})
            for p in proposals:
                if p["surface"] != surface:
                    continue
                answer = valid.get(p["firing"])
                if answer is not None and answer["action"] == "leave":
                    disposed.append(dict(p, disposition=answer))
                else:
                    still_open.append(dict(p, disposition=answer) if answer is not None else p)
        proposals = still_open
    proposals.sort(key=lambda p: (str(p.get("surface") or ""), str(p.get("detector") or "")))
    return {"project": project, "count": len(proposals), "proposals": proposals,
            "malformed": malformed, "degraded": degraded, "growth": growth,
            "disposed": disposed, "disposition_faults": faults}


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
# 2026-08-22 — policy-off lands / pinned-leg aborts / chains: <project> 34 / 152 / 0, <project> 3 / 2 / 0,
# <project> 0 / 14 / 0. <project> is the naive-positive corpus: a volume-only detector fires there loudly
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


def _own_journal_rows(path=None, types=None) -> list:
    """This session's own journal events, segment-aware (`own_journal_path` decides WHOSE by default).

    `path` overrides that resolution and exists for the same reason `born_permissive_concerns(entries=
    None)` takes one: a fixture corpus is driven through THIS reader rather than through a
    re-implementation of it — which is also what makes it drivable by the SPEC-0190 segment-awareness
    and multiset-identity probes that hold every journal reader in this corpus to its contract.

    IT ADDS NO SECOND PARSE PATH: `journal.segment_rows` is the ONE fold every debt sibling reaches the
    journal through, and inside the echo's `rows_memo` scope this call is served from the memo the other
    ~15 lines already paid for (T-11453 / SPEC-0190 rule 4). A missing journal folds to no rows.

    T-13139 — `types` DECLARES the event types the caller's fold reads, so the read keeps only those
    rows (served from the debt seam's one-pass scope, or one bounded walk outside it) instead of the
    whole corpus. Every production caller declares; None keeps the undeclared whole-journal read."""
    try:
        return [e for e in journal.segment_rows(path if path is not None else own_journal_path(),
                                                types=types)
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
    return pinned_leg_regression(_own_journal_rows(own_journal_path(root) if root is not None else None,
                                                   types=("land_completed",)))


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
            from lib import git_env as _git_env  # T-13587 — the git child env policy (SPEC-0188 rule 7)
            r = subprocess.run(["git", "-C", str(repo_root), "show", "--name-only",
                                "--pretty=format:", sha],
                               capture_output=True, text=True, timeout=30, env=_git_env._git_child_env())
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


#: T-12847 — the host's bookkeeping authority, INJECTED rather than imported: this module is a leaf of
#: `lib.cli` (the `(debt, cli)` pair in tests/test_bin_lib_leaf_no_host_import.py) and never imports
#: it. A zero-arg callable returning `(allowlist, own_predicate)`, bound by the host
#: (`cli._bind_debt_bookkeeping_authority`) and CALLED at use time, so the host's live objects are read.
_BOOKKEEPING_AUTHORITY = None


def bind_bookkeeping_authority(authority) -> None:
    """Bind (or, with None, unbind) the bookkeeping authority `_authored_overlap` consults — the same
    module-level registration shape as `register_born_permissive_detector`. Last binder wins."""
    global _BOOKKEEPING_AUTHORITY
    _BOOKKEEPING_AUTHORITY = authority


def _authored_overlap(shared, tids) -> list:
    """T-12022 (X-1247) — the paths in `shared` that are AUTHORED work, i.e. limb 2's real subject.

    WHY THE RAW OVERLAP IS NOT THE EVIDENCE. Limb 2 exists to separate REWORK OF THE SAME SURFACE
    from a bare provenance citation, and `_diff_files` hands it every path the two cards' landed
    commits touched — including the lifecycle bookkeeping EVERY card writes. `events.jsonl` is the
    extreme case: it is appended by every land, so every pair of cards in every corpus overlaps on
    it and the limb collapses back into the "two cards touched a file" volume reading SPEC-0189
    rule 3 forbids. Measured (<project> 2026-09-03, X-1247): the sole shared path between the pair
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

    THE AUTHORITY IS INJECTED, NEVER IMPORTED (T-12847). This module imports nothing from the host at
    any level; the host binds both objects through `bind_bookkeeping_authority` and the lookup
    happens inside the call, so a rebound allow-list is still read live. It sits on the ADAPTER side
    of the fold, beside `_diff_files`'s git and `_own_cards`'s disk, so `exempted_rework` itself
    stays a pure function of its arguments.

    FAILURE SILENCES THE LIMB, never widens it. If no authority is bound or it raises, every
    path reads as bookkeeping and the remainder is empty — the same direction `_diff_files` takes on
    an unresolvable diff, and the safe one for a report-only proposal: an overlap that cannot be
    SHOWN to be authored must not be claimed as evidence."""
    paths = [str(x) for x in (shared or ())]
    if not paths:
        return []
    try:
        _allow, _own = _BOOKKEEPING_AUTHORITY()    # unbound (None) raises TypeError: same silence
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
# bookkeeping). X-1260 is the same class ONE TIER FINER: measured on <project> 2026-09-04, a pair that
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
            from lib import git_env as _git_env  # T-13587 — the git child env policy (SPEC-0188 rule 7)
            r = subprocess.run(["git", "-C", str(repo_root), "show", "--unified=0",
                                "--pretty=format:", sha],
                               capture_output=True, text=True, timeout=30, env=_git_env._git_child_env())
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
                # SPEC-0189 rule 9 (T-13062): the firing identity an owner disposition answers —
                # the PAIR, so a different pair is a different firing and re-opens the proposal.
                "firing": f"{later_id}:{exempt_id}",
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
    return exempted_rework(_own_journal_rows(journal_path, types=("task_closed", "commit_landed")),
                           cards=_own_cards(root), repo_root=root)


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
# acceptable in a shipped detector, and the reason is measured rather than aesthetic (<project> +
# <project> + <project>, every journal segment, 2026-09-02):
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


def _surface4_engine_carrier_freed():
    """T-13528 — the engine's OWN section-aware ops-carrier comparison, or REFUSE.

    Since T-13528 a land whose `yitc-ops.yaml` change leaves the `verify` / `verify_policy` / `tests`
    sections equal no longer takes the verify-infra full-run edge: the carrier path is freed and each
    layer's `subject_globs` judges it. A replay that kept treating EVERY carrier touch as a full run
    would report `safe-full-run-fail-closed-edge` on exactly the lands the engine now skips layers on
    — the detector would be blind where the skip widened. So the replay asks the SAME pure function
    the land asks, imported on the same terms as `_surface4_engine_predicate` and for the same reason
    (SPEC-0189 rule 5): a restated comparison would measure the restatement."""
    try:
        from lib import worktree as _wt
        return _wt._ops_carrier_freed_paths
    except Exception as exc:  # noqa: BLE001 — every cause is the same fact to the caller
        raise Surface4DetectorRefused(
            f"REFUSING to run the {_SURFACE4_DETECTOR} detector — could not import the engine's "
            f"ops-carrier section comparison from bin/lib/worktree.py ({type(exc).__name__}: {exc}). A "
            f"replayed comparison that is not the engine's own measures the replay, not the engine "
            f"(SPEC-0189 rule 5)") from exc


def _surface4_engine_owned_test_freed():
    """T-13531 — the engine's OWN owned-test-path proof, or REFUSE.

    Since T-13531 a land whose changed `tests/` path is a declared test file that some scoped layers
    claim and others do not no longer takes the verify-infra full-run edge: the path is freed and
    forces only the layers claiming it. A replay that kept treating EVERY test touch as a full run
    would report `safe-full-run-fail-closed-edge` on exactly the lands the engine now skips layers on.
    Imported on the same terms as its two siblings above, and for the same reason (SPEC-0189 rule 5)."""
    try:
        from lib import worktree as _wt
        return _wt._owned_test_freed_paths
    except Exception as exc:  # noqa: BLE001 — every cause is the same fact to the caller
        raise Surface4DetectorRefused(
            f"REFUSING to run the {_SURFACE4_DETECTOR} detector — could not import the engine's "
            f"owned-test-path proof from bin/lib/worktree.py ({type(exc).__name__}: {exc}). A "
            f"replayed proof that is not the engine's own measures the replay, not the engine "
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


def surface4_false_skip_cases(*, rows, layers, diff_paths, repairs_after, _predicate=None,
                              carrier_texts=None, _carrier_freed=None, _owned_test_freed=None) -> list:
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
         `_SUBJECT_VERIFY_INFRA_GLOBS`) did not force a full run on that content. T-13528 — the edge
         is asked the way the land asks it: when the corpus supplies `carrier_texts(sha, base_sha)`
         (the `yitc-ops.yaml` text at the replayed land's merge-base and at its sha), the engine's own
         `_ops_carrier_freed_paths` decides whether a carrier touch is freed, and that set rides the
         SAME `reachability_freed` seam. A corpus without the reader, a reader answering None, and a
         comparison answering None all leave a carrier touch on the full-run edge, as before.
         T-13531 — over those SAME two texts the engine's own `_owned_test_freed_paths` decides
         which changed `tests/` paths are freed (declared test files some scoped layers claim and
         others do not), and that set joins the carrier answer on the seam. No carrier reader, no
         freed test path: a test touch stays on the full-run edge.
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
    carrier_freed = owned_test_freed = None
    if carrier_texts is not None:
        carrier_freed = _carrier_freed or _surface4_engine_carrier_freed()
        owned_test_freed = _owned_test_freed or _surface4_engine_owned_test_freed()

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
        freed = None
        if carrier_freed is not None:
            texts = carrier_texts(sha, base)
            if isinstance(texts, (tuple, list)) and len(texts) == 2:
                freed = (frozenset(carrier_freed(paths, texts[0], texts[1]) or ())
                         | frozenset(owned_test_freed(paths, texts[0], texts[1]) or ())) or None
        # The kwarg is passed only when a freed set exists, so an injected edge stub that predates
        # the seam is called exactly as before.
        if (fail_closed_edge(paths, infra_globs, diff_error=None, reachability_freed=freed)
                if freed else fail_closed_edge(paths, infra_globs, diff_error=None)):
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
        from lib import git_env as _git_env  # T-13587 — the git child env policy (SPEC-0188 rule 7)
        try:
            r = subprocess.run(["git", "-C", str(root), *args],
                               capture_output=True, text=True, timeout=120, env=_git_env._git_child_env())
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
    rows = [e for e in _own_journal_rows(None if _same else root / "events.jsonl",
                                         types=("land_completed",))
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

    def carrier_texts(sha, base_sha):
        """T-13528 — the ops-carrier text at the replayed land's merge-base and at its sha, or None.
        The SAME two revisions `diff_paths` compares. Any unreadable side is None, which the oracle
        reads as «not freed» — a carrier touch, and since T-13531 a test touch, stays on the full-run
        edge."""
        base = _merge_base(sha, base_sha)
        if not base or not sha:
            return None
        base_text = git("show", f"{base}:yitc-ops.yaml")
        cand_text = git("show", f"{sha}:yitc-ops.yaml")
        if base_text is None or cand_text is None:
            return None
        return (base_text, cand_text)

    return {"rows": rows, "layers": layers, "diff_paths": diff_paths, "repairs_after": repairs_after,
            "carrier_texts": carrier_texts}


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
                                      repairs_after=corpus["repairs_after"],
                                      carrier_texts=corpus.get("carrier_texts"))
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
# months (the <project> warnings open since April — X-0306). This fold gives exactly those findings
# ONE mandatory reading moment by riding the debt echo's existing seams. Report-only, never a gate:
# the deploy gate's critical-only policy is UNCHANGED (this view does not add a second gate).

# SUB-CRITICAL IS AN ALLOWLIST, NOT A NEGATION (audit-pre finding 1). Defining it as "severity !=
# critical" would silently count an ABSENT / unknown / malformed severity as debt — nagging on an
# UNKNOWN, which the report-only discipline (SPEC-0119 rule 3) forbids. So the vocabulary is explicit:
# a severity outside this set is SKIPPED, and a future severity word must be ADMITTED here deliberately
# rather than becoming debt by default.
SUBCRITICAL_SEVERITIES = debt_adoption.SUBCRITICAL_SEVERITIES   # T-12707 host re-export alias — moved WITH its readers

# The report filename shape the scaffold writes (`bin/security-audit`) — the series this fold reads.
FINDINGS_REPORT_GLOB = debt_adoption.FINDINGS_REPORT_GLOB   # T-12707 host re-export alias — moved WITH its readers

_ISO_DATE_PREFIX = debt_adoption._ISO_DATE_PREFIX   # T-12707 host re-export alias — moved WITH its readers


@functools.wraps(debt_adoption._report_date)
def _report_date(*a, _inj=("_ISO_DATE_PREFIX",), **kw):
    """T-12707 host residue — body in `bin/lib/debt_adoption.py#_report_date`; host names read HERE at call time."""
    for _k in _inj:
        kw.setdefault(_k, globals()[_k])
    return debt_adoption._report_date(*a, **kw)
_residue_binds(_report_date)


@functools.wraps(debt_adoption._finding_identity)
def _finding_identity(*a, **kw):
    """T-12707 host residue — the body now lives in `bin/lib/debt_adoption.py#_finding_identity`."""
    return debt_adoption._finding_identity(*a, **kw)


@functools.wraps(debt_adoption._open_subcritical_identities)
def _open_subcritical_identities(*a, _inj=("SUBCRITICAL_SEVERITIES", "_finding_identity",), **kw):
    """T-12707 host residue — body in `bin/lib/debt_adoption.py#_open_subcritical_identities`; host names read HERE at call time."""
    for _k in _inj:
        kw.setdefault(_k, globals()[_k])
    return debt_adoption._open_subcritical_identities(*a, **kw)
_residue_binds(_open_subcritical_identities)


@functools.wraps(debt_adoption.open_subcritical_findings)
def open_subcritical_findings(*a, _inj=("FINDINGS_REPORT_GLOB", "_open_subcritical_identities",
                                        "_report_date", "_subcritical_authority", "_subcritical_result",), **kw):
    """T-12707 host residue — body in `bin/lib/debt_adoption.py#open_subcritical_findings`; host names read HERE at call time."""
    for _k in _inj:
        kw.setdefault(_k, globals()[_k])
    return debt_adoption.open_subcritical_findings(*a, **kw)
_residue_binds(open_subcritical_findings)


def probes_awaiting_first_check(repo_root: Path) -> dict:
    """T-12982 (SPEC-0119 rule 44): the declared SPEC-0098 `security.probes` this repo's journal does
    NOT currently vouch for — `{count, properties, unvouched}`. The land floor ADMITS a newly declared
    probe as awaiting its first post-deploy check (SPEC-0093 rule 27); this is where that admission is
    read back until the probe passes.

    ONE PREDICATE WITH THE FLOOR (audit-pre r1): it asks `_floor_declared_probes` itself, with
    `base_doc={}` so every declared property counts as not-yet-landed. `properties` is then exactly
    the set the floor would admit-or-refuse for want of a vouching pass (no row, stale, definition
    mismatch, legacy change); `unvouched` counts what it would still refuse outright (an escalated
    latest row, a malformed knob, an unreadable record). Derived from carrier + journal, no stored
    state; BEST-EFFORT — any failure is `{}`, so a debt seam is never broken by it."""
    try:
        from lib import worktree as _wt   # lazy: worktree imports this module
        ops_path = Path(repo_root) / "yitc-ops.yaml"
        if not ops_path.exists():
            return {}
        ops = state.load_ops_str(ops_path.read_text(encoding="utf-8"))
        if not isinstance(ops, dict):
            return {}
        import subprocess

        def _git_cap(args, cwd):
            from lib import git_env as _git_env  # T-13587 — the git child env policy (SPEC-0188 rule 7)
            return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True,
                                  env=_git_env._git_child_env())
        pending: list = []
        refused = _wt._floor_declared_probes(Path(repo_root), ops, _wt._floor_section(ops),
                                             _git_cap, base_doc={}, pending_out=pending)
        return {"count": len(pending) + len(refused), "properties": pending,
                "unvouched": len(refused)}
    except Exception:                                  # noqa: BLE001 — report-only surface
        return {}


@functools.wraps(debt_adoption._subcritical_authority)
def _subcritical_authority(*a, **kw):
    """T-12707 host residue — the body now lives in `bin/lib/debt_adoption.py#_subcritical_authority`."""
    return debt_adoption._subcritical_authority(*a, **kw)


@functools.wraps(debt_adoption._subcritical_result)
def _subcritical_result(*a, **kw):
    """T-12707 host residue — the body now lives in `bin/lib/debt_adoption.py#_subcritical_result`."""
    return debt_adoption._subcritical_result(*a, **kw)


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
    shown was, for every reader, not performed (the shape <project> measured at X-1100).
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
                events_path, _window_segment_floor(now, days=window_days),
                types=(_GATE_OVERRIDE_EVENT,)):
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
#
# WHAT IT SAYS ABOUT CLOSURE IS THE CLOSE GATE'S OWN ANSWER, NEVER ITS OWN (T-13470). The line used
# to say every late finding «BLOCKS its card's `task close`». Measured 2026-10-03: 22 findings on 18
# cards, all 18 `done`, 20 already carrying a `ceiling_decision`, 0 closes blocked — the fold read
# only `late_findings[]` and joined neither the decisions nor the card. So each finding now carries a
# `state`, from two injected collaborators: the card's status, and `audit.undecided_late_findings` —
# the very judgement `task close` refuses on. A finding is a closure blocker only when BOTH say so; the
# count itself is unchanged, because a decided finding is still the recorded cost of a pass-1 survey.
#
# THE JUDGEMENT IS FED FROM THIS FOLD'S OWN DECLARED READ, NEVER A SECOND ONE (SPEC-0190 rule 10). The
# debt seam owes ONE pass over the journal; handing the fold the close gate's host reader would have
# walked the journal again per card. So the fold reads the gate's two row types through its ONE call
# site and passes those rows to the judgement function. THE BOUND, stated: the rows are THIS
# checkout's, from the window's segment floor on. On the main checkout — where the echo's seams live —
# that is the corpus the gate itself reads. In a task worktree a decision recorded on main is not in
# this journal yet, so the on-demand `debt` re-fold there can still name that worktree's own decided
# finding a blocker; it errs toward visible, and `task close` remains the authority either way.
_LATE_FINDINGS_WINDOW_DAYS = 30   # the reading window; not a governance scalar — a report-only horizon
#: The two event types `audit.undecided_late_findings` judges over: the audit completion rows that
#: carry `late_findings[]`, and the decisions that bind them. Declared once; `debt_echo_scan` reads it.
LATE_FINDING_READ_TYPES = ("external_audit_completed", "ceiling_decision")
#: The card statuses with no `task close` left to block (QUEUE §State transitions: `done` is shipped
#: history, `wont-do` is decided-not-to-do — both terminal).
_LATE_FINDING_TERMINAL_STATUSES = ("done", "wont-do")


def _task_card_status(tasks_dir, tid, _read_yaml) -> "str | None":
    """The `status:` of card `tid` under `tasks_dir`, or None when it cannot be read (T-13470).

    TOLERANT by construction — a report-only line never breaks the seam it rides: a missing
    directory, no such card, an unparseable file, a non-mapping document or a blank status all answer
    None, and the caller treats None as «not proven terminal». Only a real task id is looked up, so
    the glob below can never be steered by a foreign `target_id` (a plan slug, a path)."""
    if not isinstance(tid, str) or not re.fullmatch(r"T-\d+", tid):
        return None
    try:
        paths = sorted(Path(tasks_dir).glob(f"{tid}-*.yaml")) or sorted(Path(tasks_dir).glob(f"{tid}.yaml"))
        if not paths:
            return None
        card = _read_yaml(paths[0])
    except Exception:                      # noqa: BLE001 — unreadable ⇒ unknown, never a raise
        return None
    status = card.get("status") if isinstance(card, dict) else None
    return status.strip() if isinstance(status, str) and status.strip() else None


def late_findings_per_pass(events_path, window_days: int = _LATE_FINDINGS_WINDOW_DAYS,
                           now=None, *, _card_status=None, _judge=None) -> dict:
    """Fold the journal → the `late_findings[]` recorded on audit passes inside `window_days`.

    EACH FINDING CARRIES A `state` (T-13470) — what the engine's own state says about closure:
      `card-terminal` — its card is `done` / `wont-do`: there is no `task close` left to block.
      `blocks-close`  — the card is not terminal AND the close gate's own judgement lists this
                        finding undecided. The ONLY state the line may call a blocker.
      `decided`       — the card is not terminal and the gate does NOT list it (a `ceiling_decision`
                        binds its ref, or the gate does not gate that row).
      `unjudged`      — the card is not terminal and the judgement could not be made (no judge
                        injected, or it raised). Never a blocker claim, and never read as cleared.
    `_card_status(tid) -> str | None` reads the card; `_judge(rows, tid) -> [undecided entries]` IS
    `audit.undecided_late_findings`, handed in rather than re-derived so this line and the gate cannot
    disagree about what «undecided» means. The card is read FIRST and the judge is called only for a
    NON-terminal card, once per card — so a window of findings on closed cards (18 of 18 when this
    was measured) costs nothing more. The rows the judge sees come from this fold's own read (see the
    block above for why, and for the bound). A card whose status cannot be read is NOT proven
    terminal: the judgement stands, visibly.

    Pure: reads the journal, writes nothing (the SPEC-0149 acceptance boundary every fold here
    shares). SEGMENT-AWARE (SPEC-0190 rule 4) on the same terms as its `recent_gate_overrides`
    sibling — the 30-day window is wider than the 7-day live segment, so a raw read of the live
    segment alone would report an older late finding as absent, which for every reader means it was
    never recorded.

    A missing/unreadable journal, a malformed line or an unparseable `ts` yields a clean zero-count
    result — a report-only surface never breaks the seam it rides and never nags on an unknown.

    Returns `{lens, now, window_days, count, passes, findings, blocking_count, blocking_tasks,
    unjudged_count, unjudged_tasks, decided_count, card_terminal_count, next}` — `count` is the number
    of LATE FINDINGS, `passes` the number of distinct (task, stage, pass) rows that carried at least
    one. Both are reported because they answer different questions: one card taking five late findings
    on one pass and five cards taking one each are the same `count` and very different signals. The
    four state counts partition `count`; nothing is ever dropped from it.
    """
    now = now if now is not None else datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    findings: list = []
    rows_seen: set = set()

    def _read(pred=None):
        # THE one journal call site of this fold: the window's segments, the gate's two row types.
        return journal.iter_rows(
            events_path, since=_window_segment_floor(now, days=window_days),
            types=LATE_FINDING_READ_TYPES, pred=pred)
    try:
        for event in _read():
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
                    "_row_passes": passes,
                })
    except (OSError, UnicodeDecodeError):
        findings, rows_seen = [], set()

    # THE CLOSURE JUDGEMENT (T-13470) — one card read per distinct card, and the judge called only for
    # the cards that are not terminal, over rows re-served by the SAME declared read.
    status_of: dict = {}

    def _status(tid):
        if tid not in status_of:
            try:
                status_of[tid] = _card_status(tid) if _card_status is not None else None
            except Exception:              # noqa: BLE001 — unreadable ⇒ not proven terminal
                status_of[tid] = None
        return status_of[tid]

    need = {f["task"] for f in findings
            if f["task"] and _status(f["task"]) not in _LATE_FINDING_TERMINAL_STATUSES}
    undecided_of: dict = {}                # tid -> [entries]; a tid ABSENT here was not judged
    if need and _judge is not None:
        def _names_needed(row):
            # At least as wide as the judge's own row→task test (envelope `task_id`, or the audit
            # family's `data.target_id` / `data.plan_slug`): the judge narrows, this only bounds.
            data = row.get("data") if isinstance(row.get("data"), dict) else {}
            return (row.get("task_id") in need or data.get("target_id") in need
                    or data.get("plan_slug") in need)
        try:
            gate_rows = [r for r in _read(_names_needed) if isinstance(r, dict)]
        except (OSError, UnicodeDecodeError):
            gate_rows = None               # could not read ⇒ nothing judged, nothing cleared
        for tid in (sorted(need, key=str) if gate_rows is not None else ()):
            try:
                answer = _judge(gate_rows, tid)
            except Exception:              # noqa: BLE001 — could not judge ⇒ unjudged, never cleared
                continue
            if isinstance(answer, (list, tuple)):
                undecided_of[tid] = list(answer)

    def _gate(tid):
        """The judge's undecided entries for `tid`, or None when it could not be judged."""
        return undecided_of.get(tid)

    for f in findings:
        row_passes = f.pop("_row_passes")
        status = _status(f["task"])
        f["card_status"] = status
        if status in _LATE_FINDING_TERMINAL_STATUSES:
            f["state"] = "card-terminal"
            continue
        entries = _gate(f["task"])
        if entries is None:
            f["state"] = "unjudged"
            continue
        # The gate keys an undecided late finding by (stage, fingerprint) and the pass of the ROW it
        # sits on (rule 4: a decision binds ONE (ceiling_ref, fingerprint) pair). A row that states no
        # counter was bound at the ceiling row's ref, which this fold does not re-derive — so there the
        # match is on (stage, fingerprint) alone, the direction that keeps a blocker visible.
        at_stage = [e for e in entries if isinstance(e, dict) and e.get("stage") == f["stage"]]
        key = f["finding_fingerprint"]
        if isinstance(key, str) and key:
            hit = any(e.get("finding_fingerprint") == key
                      and (not isinstance(row_passes, int) or e.get("pass") == row_passes)
                      for e in at_stage)
        else:
            hit = bool(at_stage)           # an unkeyed finding cannot be told apart — stay visible
        f["state"] = "blocks-close" if hit else "decided"

    findings.sort(key=lambda r: r["ts"], reverse=True)   # most recent first

    def _tasks_in(state):
        return sorted({str(f["task"]) for f in findings if f["state"] == state and f["task"]})
    blocking = [f for f in findings if f["state"] == "blocks-close"]
    unjudged = [f for f in findings if f["state"] == "unjudged"]
    return {
        "lens": f"late-findings-per-pass (SPEC-0204 rule 8) — defects the external auditor raised at "
                f"a pass >= 2 with `causality: pre-existing-in-subject`, i.e. ones its own pass-1 "
                f"whole-subject survey MISSED, in the last {window_days} days. Each was RECORDED and "
                f"excluded from that pass's verdict (owner ruling D8: a late finding is never a "
                f"verdict driver on its own). The COUNT is recorded history and includes findings "
                f"already decided and findings on cards already closed. Each finding's `state` says "
                f"what it means for closure, and only `blocks-close` — undecided by the close gate's "
                f"own judgement, on a card that is not done / wont-do — still needs a typed "
                f"`ceiling_decision` before its card can close; `unjudged` means that judgement could "
                f"not be made, which is not a clearance. DERIVED by folding the journal; zero stored "
                f"state, recomputed fresh, report-only, never a gate.",
        "now": now.isoformat().replace("+00:00", "Z"),
        "window_days": window_days,
        "count": len(findings),
        "passes": len(rows_seen),
        "findings": findings,
        "blocking_count": len(blocking),
        "blocking_tasks": _tasks_in("blocks-close"),
        "unjudged_count": len(unjudged),
        "unjudged_tasks": _tasks_in("unjudged"),
        "decided_count": sum(1 for f in findings if f["state"] == "decided"),
        "card_terminal_count": sum(1 for f in findings if f["state"] == "card-terminal"),
        "next": ("late findings are the measured cost of an incomplete pass-1 survey: they are "
                 "recorded, not penalised. "
                 + (f"{len(blocking)} of them block a `task close` until a `yitc-v2 audit decide` "
                    f"records fix / accept / defer ({', '.join(_tasks_in('blocks-close'))}). "
                    if blocking else "")
                 + (f"{len(unjudged)} could not be judged — the close-gate judgement was unavailable "
                    f"({', '.join(_tasks_in('unjudged'))}); that is not a clearance. "
                    if unjudged else "")
                 + ("None of them blocks a close: every one is decided or sits on a closed card. "
                    if not blocking and not unjudged else "")
                 + "A RISING count on one stage is the signal that the pass-1 packet, not the "
                   "auditor, is what needs the change."
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
    # T-12641 / X-1440 — an ORPHANED watcher still EXITS, so it still writes this receipt: it used to
    # launder itself into the "monitored" column while no wake ever reached the Controller. Decline the
    # credit when the arming is PROVEN unreachable, so the dispatch stays on this debt line and is
    # echoed at session-start and the land-tail — a surface OUTSIDE the dead log. CONSERVATIVE: only a
    # proven negative declines; `unproven` and an ABSENT key (every pre-change receipt) still credit, so
    # no existing path changes (AC3).
    if data.get("arming_reachability") == "unreachable":
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
ABSENT_CARD_RESOLUTIONS = debt_adoption.ABSENT_CARD_RESOLUTIONS   # T-12707 host re-export alias — moved WITH its readers

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
    from lib import git_env as _git_env  # T-13587 — the git child env policy (SPEC-0188 rule 7)
    import subprocess
    try:
        proc = subprocess.run(["git", "-C", str(root)] + list(argv), capture_output=True, text=True,
                              timeout=_PROVENANCE_GIT_TIMEOUT, env=_git_env._git_child_env())
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


@functools.wraps(debt_adoption._is_pre_claim_refusal)
def _is_pre_claim_refusal(*a, **kw):
    """T-12707 host residue — the body now lives in `bin/lib/debt_adoption.py#_is_pre_claim_refusal`."""
    return debt_adoption._is_pre_claim_refusal(*a, **kw)


@functools.wraps(debt_adoption.unresolved_worker_halts)
def unresolved_worker_halts(*a, _inj=("ABSENT_CARD_RESOLUTIONS", "TERMINAL_CARD_STATUSES",
                                      "_is_pre_claim_refusal", "_parse_stamped_deadline",
                                      "_unresolved_halt_result",), **kw):
    """T-12707 host residue — body in `bin/lib/debt_adoption.py#unresolved_worker_halts`; host names read HERE at call time."""
    for _k in _inj:
        kw.setdefault(_k, globals()[_k])
    return debt_adoption.unresolved_worker_halts(*a, **kw)
_residue_binds(unresolved_worker_halts)


@functools.wraps(debt_adoption._unresolved_halt_result)
def _unresolved_halt_result(*a, **kw):
    """T-12707 host residue — the body now lives in `bin/lib/debt_adoption.py#_unresolved_halt_result`."""
    return debt_adoption._unresolved_halt_result(*a, **kw)


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
# itself). On 2026-07-13 <project> ran 8 hours of total prod-auth death behind SIX such greens: a /healthz
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

# The FULL structural field set of the SPEC-0156 §2 contract, in the order the spec enumerates it, so a
# refusal reads in the same order as the rule it cites. `check` / `declaration` / `broken_input` /
# `definition_identity` must each be a non-empty string; `outcome` must be exactly ADMISSION_RED_OUTCOME.
# Derived from the two constants above rather than re-listed, so widening either widens this too (P5).
ADMISSION_PAYLOAD_KEYS = ("check",) + ADMISSION_REQUIRED_FIELDS + ("outcome", "definition_identity")

#: The four keys whose contract is "a non-empty string" — everything above except `outcome`, which has
#: the stricter one-legal-value contract below.
ADMISSION_STRING_KEYS = tuple(k for k in ADMISSION_PAYLOAD_KEYS if k != "outcome")


def validate_admission_payload(event_type, data) -> list:
    """The sorted problems of a `check_admission_demonstrated` payload: `missing:<key>` for any of
    check / declaration / broken_input / definition_identity / outcome that is absent, not a string or
    blank, and `bad:outcome` when `outcome` IS a non-blank string but is not the clearing value.
    An OPEN row — no `unknown:` arm, so an emitter may carry extra detail (`ts`, `task`, …). A non-dict
    payload is missing every key. Returns `[]` for a clean payload and for any other event type. Pure,
    no raise.

    THE ONE PREDICATE, SHARED BY THE WRITE AND THE READ (T-12648, <project> X-1456). This function is
    what `_admission_demonstrations` below applies to decide whether a journal row COUNTS, and what
    `cmd_event` applies at the WRITE to decide whether it may be appended at all — so "the write
    validates exactly what the read admits" is a property of the code, not a comment that two places
    must be kept agreeing by hand (CHARTER §P5). It expresses ONLY the STRUCTURAL half of the contract.

    WHAT IS DELIBERATELY NOT HERE, and why it may never move in (the fence that keeps this a payload
    validator rather than a new gate class): the two CARRIER-DEPENDENT conditions — that `check` names
    a DECLARED check, and that `definition_identity` matches the identity the carrier computes NOW.
    Those are the READER's judgement (`_near_miss_reason`), they need the ops carrier and its git
    history, and a recorded identity that no longer matches is a legitimate historical row — a REWIRE
    is exactly what the fold is built to notice, not something to refuse at the write. Refusing on them
    would gate a declaration, which SPEC-0156 §3 forbids.

    `outcome` earns its own problem string (`bad:outcome`, never a bare `missing:`) because the wrong
    value there is the miss most likely to be read as something else: a row whose outcome is "green"
    or "pass" is a COMPLETE-looking record that clears nothing, and the debt line it fails to clear
    reads as the demonstration having FAILED rather than as the payload having been ignored — the
    expensive misread SPEC-0156 §2 warns about in its own rewire-vs-wrong-key paragraph, and the one
    X-1456 actually made, twice.
    """
    if event_type != ADMISSION_EVENT:
        return []
    if not isinstance(data, dict):
        return sorted(f"missing:{k}" for k in ADMISSION_PAYLOAD_KEYS)
    problems = []
    for k in ADMISSION_STRING_KEYS:
        if not (isinstance(data.get(k), str) and data.get(k).strip()):
            problems.append(f"missing:{k}")
    outcome = data.get("outcome")
    if not (isinstance(outcome, str) and outcome.strip()):
        problems.append("missing:outcome")
    elif outcome.strip().lower() != ADMISSION_RED_OUTCOME:
        # STRIP + LOWER, DELIBERATELY — and this is the FOLD's tolerance, not a new one invented
        # here (audit-post finding 1, T-12648). It is the comparison `_near_miss_reason` below has
        # applied since SPEC-0156 shipped (53dcd8bee5, T-10509), so ` RED ` is a row that DOES clear
        # a check today. Byte-exact equality here would therefore REFUSE AT THE WRITE a payload the
        # READ still counts — which is not a stricter gate but a DISAGREEING one, and this card's
        # scope is the opposite instruction: "validate at WRITE time exactly what the fold admits at
        # READ time". The rule the card states as `literally red` is a rule about WHICH OUTCOME
        # clears — "anything else does not clear" — and ` RED ` is not an "anything else": it
        # clears. `green`, `pass`, `ok` and every other value are what this arm refuses.
        # CHANGING THE TOLERANCE IS A CHANGE TO THE FOLD, not to this validator: tighten it in ONE
        # place or not at all, and only with the history of already-emitted consumer rows in hand.
        problems.append("bad:outcome")
    return sorted(problems)


# ── The NEAR-MISS feedback (T-11178 / <project> X-0921) ─────────────────────────────────────────────
#
# THE GAP. Every condition above is evaluated at READ time, over a row emitted through the GENERIC
# `event` verb — and that is by design: SPEC-0156 §2 admits no new verb and no new emitter, so nothing
# validates the payload when it is written, and nothing CAN (a generic verb has no knowledge of one
# type's required keys). The consequence is that a row which misses ANY condition is simply not counted,
# and the debt line keeps reading `never` — INDISTINGUISHABLE from having emitted nothing at all. The
# author gets no signal that their row was seen and rejected, nor which condition rejected it.
#
# MEASURED COST (X-0921, <project> 2026-08-13, fingerprint
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
# Measured on <project>'s real history with this very function — `verify.layers[frontend-unit]` moved
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

# THE PROJECTION HAS A HISTORY, AND A RECORDED IDENTITY IS DATED BY IT (T-11665, resolving <project>
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
    section OR on a single entry — <project>'s `verify.layers[frontend]` carries its own — so this is
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
    re-owed a demonstration the rule never asks for. It was not hypothetical — <project>'s
    `verify.layers[default]`, demonstrated 2026-07-19 under 602b4cfb0fd129e9, read REWIRED with no command
    change, which actively PENALISED the very `subject_globs` rollout the kernel asks consumers to perform.
    Hashing the definition-bearing projection makes the docstring's claim true instead of merely asserted.

    THE SAME CORRECTION, ONCE MORE FOR THE COVERAGE KEYS (T-11415, X-1084). The projection shipped naming
    only `subject_globs`, and `covers:` / `covers_classes:` — descriptive coverage metadata the land RUN
    ignores — stayed hashed in. <project>, following the kernel's own advice to declare what each layer
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


@functools.wraps(debt_adoption.declared_checks)
def declared_checks(*a, _inj=("_check_rows_from_carrier",), **kw):
    """T-12707 host residue — body in `bin/lib/debt_adoption.py#declared_checks`; host names read HERE at call time."""
    for _k in _inj:
        kw.setdefault(_k, globals()[_k])
    return debt_adoption.declared_checks(*a, **kw)
_residue_binds(declared_checks)


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
                    continue              # a single WAIVED entry (<project>'s verify.layers[frontend])
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
    a false-green inside the very mechanism built to end false-greens (the <project> class, one level up).
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
        for event in journal.segment_rows(events_path, types=(ADMISSION_EVENT,)):
            if not isinstance(event, dict) or event.get("type") != ADMISSION_EVENT:
                continue
            data = event.get("data")
            if not isinstance(data, dict):
                continue
            # The five structural conditions — `check` names something, the outcome is RED, the
            # identity names a definition, and the record is COMPLETE — are applied by the ONE shared
            # predicate (T-12648). Behaviour is exactly what the four inline checks this replaced did;
            # what changed is that `cmd_event` now applies the SAME function at the WRITE, so a row
            # this fold would silently drop is refused before it can become permanent (X-1456). An
            # INCOMPLETE record is not a demonstration (§2): a RED with no NAMED broken input is a
            # claim, and a green/absent outcome demonstrates nothing.
            if validate_admission_payload(ADMISSION_EVENT, data):
                continue
            check = data["check"]
            identity = data["definition_identity"]
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
            # record and told its author to redo work that was done correctly (<project> X-1119).
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
        for event in journal.segment_rows(events_path, types=(ADMISSION_EVENT,)):
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


# THE IDENTITY-HISTORY REPLAY (T-11425, resolving <project> X-1095) — how a WRONG-KEY payload is told
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
# on <project> before this was written: `tests.classes[browser-row-press]` has exactly ONE identity across
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

    EVERY REVISION IS REPLAYED UNDER EVERY PROJECTION THIS KERNEL HAS EVER APPLIED (T-11665, <project>
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
        from lib import git_env as _git_env  # T-13587 — the git child env policy (SPEC-0188 rule 7)
        try:
            proc = subprocess.run(["git", "-C", str(root)] + list(argv), capture_output=True, text=True,
                                  timeout=_IDENTITY_HISTORY_GIT_TIMEOUT, env=_git_env._git_child_env())
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
    admission debt anyway is the fold billing a consumer for the kernel's own algorithm change (<project>
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


@functools.wraps(debt_adoption.unproven_checks)
def unproven_checks(*a, _inj=("_admission_demonstrations", "_admission_near_misses",
                              "_genuine_supersession", "_identities_ever_declared",
                              "_projection_superseded", "_unproven_result", "_wanted_identities",
                              "declared_checks",), **kw):
    """T-12707 host residue — body in `bin/lib/debt_adoption.py#unproven_checks`; host names read HERE at call time."""
    for _k in _inj:
        kw.setdefault(_k, globals()[_k])
    return debt_adoption.unproven_checks(*a, **kw)
_residue_binds(unproven_checks)


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


@functools.wraps(debt_adoption._unproven_result)
def _unproven_result(*a, _inj=("_near_miss_clause",), **kw):
    """T-12707 host residue — body in `bin/lib/debt_adoption.py#_unproven_result`; host names read HERE at call time."""
    for _k in _inj:
        kw.setdefault(_k, globals()[_k])
    return debt_adoption._unproven_result(*a, **kw)
_residue_binds(_unproven_result)


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
# <project> split keeps source bind mounts HERE, layered on top for local work only. A mount that lives ONLY
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
          move to a dev overlay (the <project> split — §3, so the PROD-scoped detector sees nothing).

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
        # dev-overlay mount (the <project> split) is silent, and a real waiver never reaches here (model=None
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
               "(1) the dev/prod compose SPLIT — keep source mounts in `docker-compose.dev.yaml`, run "
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
# fail. It never asks whether the check has ever ACTUALLY RUN green. <project>'s e2e test class was DECLARED
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
EXECUTION_EVENT = debt_adoption.EXECUTION_EVENT   # T-12707 host re-export alias — moved WITH its readers

# The ONLY outcome that records an execution: a class shown GREEN. A non-pass (or absent, or misspelt)
# outcome records NO successful run — it must not clear the line.
EXECUTION_PASS_OUTCOME = debt_adoption.EXECUTION_PASS_OUTCOME   # T-12707 host re-export alias — moved WITH its readers

# THE EVIDENCE, NOT JUST THE VERDICT (the SPEC-0156 ADMISSION_REQUIRED_FIELDS discipline). A bare "it ran"
# with no NAMED run is a CLAIM anyone could type, and clearing a class on a claim is the false-green this
# fold exists to end. A record must carry a non-empty `evidence:` (what run — a CI url, a log ref, a
# harness id) to clear a class. Under-evidenced ⇒ still owed; it never invents debt that was not declared.
EXECUTION_REQUIRED_FIELDS = debt_adoption.EXECUTION_REQUIRED_FIELDS   # T-12707 host re-export alias — moved WITH its readers


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
    names, so the row is invisible on every surface. MEASURED (<project>, 2026-08-20): two rows emitted with
    `class=stack` and `class=static` — verify LAYER ids, not any of their eight declared classes — accepted
    without a word, and the next morning's fold still reported the same declared-but-unproven count. The
    acceptance criterion that named the event stayed unmet for a day. The only seam where the mistake is
    still cheap is the emit itself, and the vocabulary needed to catch it is already in hand there.

    WHY THE WRONG VALUE IS THE EASY ONE TO WRITE — this is not carelessness, and the message is shaped to
    the actual confusion. Both vocabularies live in ONE file a few sections apart; they OVERLAP (<project>'s
    `frontend-unit` is BOTH a layer id and a class name, so "is this the right KIND of name" cannot be
    settled by inspection); and the run output on screen at the moment of recording prints the LAYER names,
    never the class names. The author copies what they just read.

    IT FAILS BY IMPROVING THE ARTIFACT, NOT BY REFUSING (the requester's ask, and their own external
    consult's finding on this class of fix — <project> decisions/gate-automation-frame-audit-adhoc.yaml
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


@functools.wraps(debt_adoption._execution_defect)
def _execution_defect(*a, _inj=("EXECUTION_PASS_OUTCOME", "EXECUTION_REQUIRED_FIELDS",), **kw):
    """T-12707 host residue — body in `bin/lib/debt_adoption.py#_execution_defect`; host names read HERE at call time."""
    for _k in _inj:
        kw.setdefault(_k, globals()[_k])
    return debt_adoption._execution_defect(*a, **kw)
_residue_binds(_execution_defect)


@functools.wraps(debt_adoption._test_class_executions)
def _test_class_executions(*a, _inj=("EXECUTION_EVENT", "_execution_defect", "_parse_stamped_deadline",), **kw):
    """T-12707 host residue — body in `bin/lib/debt_adoption.py#_test_class_executions`; host names read HERE at call time."""
    for _k in _inj:
        kw.setdefault(_k, globals()[_k])
    return debt_adoption._test_class_executions(*a, **kw)
_residue_binds(_test_class_executions)


NEAR_MISS_CAP = debt_adoption.NEAR_MISS_CAP   # T-12707 host re-export alias — moved WITH its readers


@functools.wraps(debt_adoption._test_class_near_misses)
def _test_class_near_misses(*a, _inj=("EXECUTION_EVENT", "NEAR_MISS_CAP", "_execution_defect",
                                      "_parse_stamped_deadline",), **kw):
    """T-12707 host residue — body in `bin/lib/debt_adoption.py#_test_class_near_misses`; host names read HERE at call time."""
    for _k in _inj:
        kw.setdefault(_k, globals()[_k])
    return debt_adoption._test_class_near_misses(*a, **kw)
_residue_binds(_test_class_near_misses)


@functools.wraps(debt_adoption.unexecuted_test_classes)
def unexecuted_test_classes(*a, _inj=("_declared_test_classes", "_test_class_executions",
                                      "_test_class_near_misses", "_unexecuted_result",), **kw):
    """T-12707 host residue — body in `bin/lib/debt_adoption.py#unexecuted_test_classes`; host names read HERE at call time."""
    for _k in _inj:
        kw.setdefault(_k, globals()[_k])
    return debt_adoption.unexecuted_test_classes(*a, **kw)
_residue_binds(unexecuted_test_classes)


@functools.wraps(debt_adoption._unexecuted_result)
def _unexecuted_result(*a, **kw):
    """T-12707 host residue — the body now lives in `bin/lib/debt_adoption.py#_unexecuted_result`."""
    return debt_adoption._unexecuted_result(*a, **kw)


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
# THE MEASURED INCIDENT (X-0860, <project>). `task test --run` printed PASS while two declared test
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
# the consult required: <project>'s own `tests/test_declared_vs_executed.py` is the prior art, and its
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

@functools.wraps(debt_adoption.unexecuted_subject_files)
def unexecuted_subject_files(*a, _inj=("_is_waived", "_unexecuted_subject_result",), **kw):
    """T-12707 host residue — body in `bin/lib/debt_adoption.py#unexecuted_subject_files`; host names read HERE at call time."""
    for _k in _inj:
        kw.setdefault(_k, globals()[_k])
    return debt_adoption.unexecuted_subject_files(*a, **kw)
_residue_binds(unexecuted_subject_files)


@functools.wraps(debt_adoption._unexecuted_subject_result)
def _unexecuted_subject_result(*a, **kw):
    """T-12707 host residue — the body now lives in `bin/lib/debt_adoption.py#_unexecuted_subject_result`."""
    return debt_adoption._unexecuted_subject_result(*a, **kw)


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
# (`trial_run_recorded` 2026-08-13T19:17:02Z): <project> 0% skip on all four layers across 453 lands at an
# 84.6s median, against <project>'s 0.9s median with subject_globs on all 8.
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
    Measured reason (<project>, 2026-08-13): its `frontend` layer is waived on 200 of 200 lands, so
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
        for event in journal.segment_rows(events_path, types=("land_completed",)):
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
    """The RUN-level companion of the per-layer reading above (T-11749 / <project> X-1165, X-1160).

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
                "RUN-level companion `run_skip` (T-11749 / a consumer's X-1165): over the SAME window, the "
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
# observed broken. X-0419 is that gap cashing in: on <project>, FIVE remediation tasks closed green over
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

SLOWEST_CHANGE_WINDOW_LANDS = debt_landing.SLOWEST_CHANGE_WINDOW_LANDS   # T-12698 host re-export alias — moved WITH its readers
SLOWEST_CHANGE_MIN_PRIOR = debt_landing.SLOWEST_CHANGE_MIN_PRIOR   # T-12698 host re-export alias — moved WITH its readers
SLOWEST_CHANGE_GROWTH_RATIO = debt_landing.SLOWEST_CHANGE_GROWTH_RATIO   # T-12698 host re-export alias — moved WITH its readers
SLOWEST_CHANGE_MIN_GROWTH_MS = debt_landing.SLOWEST_CHANGE_MIN_GROWTH_MS   # T-12698 host re-export alias — moved WITH its readers
_SLOWEST_COMPARABLE_OUTCOME = debt_landing._SLOWEST_COMPARABLE_OUTCOME   # T-12698 host re-export alias — moved WITH its readers


@functools.wraps(debt_landing._slowest_records)
def _slowest_records(*a, **kw):
    """T-12698 host residue — the body now lives in `bin/lib/debt_landing.py#_slowest_records`."""
    return debt_landing._slowest_records(*a, **kw)


@functools.wraps(debt_landing._median)
def _median(*a, **kw):
    """T-12698 host residue — the body now lives in `bin/lib/debt_landing.py#_median`."""
    return debt_landing._median(*a, **kw)


@functools.wraps(debt_landing.slowest_decile_changes)
def slowest_decile_changes(*a, _inj=("SLOWEST_CHANGE_GROWTH_RATIO", "SLOWEST_CHANGE_MIN_GROWTH_MS",
                                     "SLOWEST_CHANGE_MIN_PRIOR", "SLOWEST_CHANGE_WINDOW_LANDS",
                                     "_SLOWEST_COMPARABLE_OUTCOME", "_median", "_slowest_change_result",
                                     "_slowest_records",), **kw):
    """T-12698 host residue — body in `bin/lib/debt_landing.py#slowest_decile_changes`; host names read HERE at call time."""
    for _k in _inj:
        kw.setdefault(_k, globals()[_k])
    return debt_landing.slowest_decile_changes(*a, **kw)
_residue_binds(slowest_decile_changes)


@functools.wraps(debt_landing._slowest_change_result)
def _slowest_change_result(*a, _inj=("SLOWEST_CHANGE_GROWTH_RATIO", "SLOWEST_CHANGE_MIN_GROWTH_MS",), **kw):
    """T-12698 host residue — body in `bin/lib/debt_landing.py#_slowest_change_result`; host names read HERE at call time."""
    for _k in _inj:
        kw.setdefault(_k, globals()[_k])
    return debt_landing._slowest_change_result(*a, **kw)
_residue_binds(_slowest_change_result)


# ── SPEC-0119 rule 27 (T-11368 / <project> X-1036, corrected by X-1039): what ABORTED lands COST ─────
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

ABORT_COST_WINDOW_DAYS = debt_landing.ABORT_COST_WINDOW_DAYS   # T-12698 host re-export alias — moved WITH its readers
ABORT_COST_MATERIAL_MS = debt_landing.ABORT_COST_MATERIAL_MS   # T-12698 host re-export alias — moved WITH its readers
ABORT_COST_DECAY_RATIO = debt_landing.ABORT_COST_DECAY_RATIO   # T-12698 host re-export alias — moved WITH its readers
ABORT_COST_GROWTH_RATIO = debt_landing.ABORT_COST_GROWTH_RATIO   # T-12698 host re-export alias — moved WITH its readers
ABORT_COST_TREND_FLOOR_MS = debt_landing.ABORT_COST_TREND_FLOOR_MS   # T-12698 host re-export alias — moved WITH its readers
ABORT_PAID_VERIFY_MARKER = debt_landing.ABORT_PAID_VERIFY_MARKER   # T-12698 host re-export alias — moved WITH its readers
ABORT_GATE_CAUGHT_CLASSES = debt_landing.ABORT_GATE_CAUGHT_CLASSES   # T-12698 host re-export alias — moved WITH its readers
ABORT_INCONCLUSIVE_CLASSES = debt_landing.ABORT_INCONCLUSIVE_CLASSES   # T-12698 host re-export alias — moved WITH its readers
ABORT_UNCLASSIFIED = debt_landing.ABORT_UNCLASSIFIED   # T-12698 host re-export alias — moved WITH its readers
ABORT_PREFLIGHT_MARKER = debt_landing.ABORT_PREFLIGHT_MARKER   # T-12698 host re-export alias — moved WITH its readers
                                             # step-4a PREFLIGHT — its OWN recorded refusal point
ABORT_COST_GROUPS = debt_landing.ABORT_COST_GROUPS   # T-12698 host re-export alias — moved WITH its readers

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
ABORT_CLASS_PARK_LIMIT_EVICTION = debt_landing.ABORT_CLASS_PARK_LIMIT_EVICTION   # T-12698 host re-export alias — moved WITH its readers


@functools.wraps(debt_landing.abort_class_is_park_limit_eviction)
def abort_class_is_park_limit_eviction(*a, _inj=("ABORT_CLASS_PARK_LIMIT_EVICTION",), **kw):
    """T-12698 host residue — body in `bin/lib/debt_landing.py#abort_class_is_park_limit_eviction`; host names read HERE at call time."""
    for _k in _inj:
        kw.setdefault(_k, globals()[_k])
    return debt_landing.abort_class_is_park_limit_eviction(*a, **kw)
_residue_binds(abort_class_is_park_limit_eviction)

# ── T-11426 (<project> X-1096): THE ARM SPLIT — one abort class carrying two refusals ──────────────
#
# THE FINDING. `rebaseline-unauthorized` is ONE class NAME over TWO refusals with different
# placements and, decisively, different MOVABILITY:
#   • the AUTHORIZATION arm — "this `--rebaseline` ack has no current-state audit-post" — was MOVED
#     to the step-4a preflight by T-10850 on 2026-08-09. It refuses before verify but
#     after the land reservation queue, so it is NOT cheap: T-12499 measured p50 546 s, 77% of it reservation wait.
#     What is left to reclaim there is the QUEUE, not the verify.
#   • the WAIVE-COVERAGE arm (T-10754) — "your `--rebaseline-waive` declaration does not cover what
#     actually failed" — reads `pinned_bad`, so it is reachable only AFTER the pinned run. It has NOT
#     been moved and, on the measured consumer week, ran a median 597.9 s to reach its verdict.
# Folding those into one bucket unions a refusal we already made cheap with one we have not, and the
# TREND over that union is what makes it decision-grade-looking rather than merely coarse: this
# repo's own session-start echo printed `rebaseline-unauthorized 32x 369.0min DECAYING`, and a
# DECAYING verdict over a union of two arms of different movability points a reader at a cost that is
# going away on one arm while standing on the other. <project> filed this after their own earlier
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
# (preflight-vs-not) that <project>'s own journal happened to support: there, all 61 non-preflight rows
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
ABORT_ARM_SPLIT_CLASSES = debt_landing.ABORT_ARM_SPLIT_CLASSES   # T-12698 host re-export alias — moved WITH its readers
                                                       # union two refusals (T-11426, T-11607)
ABORT_ARM_AUTHORIZATION = debt_landing.ABORT_ARM_AUTHORIZATION   # T-12698 host re-export alias — moved WITH its readers
ABORT_ARM_WAIVE_COVERAGE = debt_landing.ABORT_ARM_WAIVE_COVERAGE   # T-12698 host re-export alias — moved WITH its readers
                                              # refuses at the step-4a preflight (T-11479), coverage
                                              # half still reads pinned_bad after a full pinned run
ABORT_ARM_INLAND_REAUDIT = debt_landing.ABORT_ARM_INLAND_REAUDIT   # T-12698 host re-export alias — moved WITH its readers
                                              # T-11483's MID-LAND re-audit over the merged tree could
                                              # not produce a verdict (`could-not-run`) or was refused
                                              # its one bounded pass by the SPEC-0204 ladder
                                              # (`ceiling-refused`). Its remedy is an audit that can
                                              # RUN, or `audit decide` — neither of which is what the
                                              # authorization arm's remedy (earn an audit-post) means,
                                              # which is why counting it as authorization described it
                                              # wrongly rather than approximately.
ABORT_ARM_UNATTRIBUTED = debt_landing.ABORT_ARM_UNATTRIBUTED   # T-12698 host re-export alias — moved WITH its readers
# The two refusals' own invariant sentences, used ONLY to attribute rows the structured markers cannot
# separate (see the order below). `_emit_land_abort` collapses whitespace on `abort_reason`, so each
# sentence is contiguous in the recorded row.
ABORT_ARM_AUTHORIZATION_MARK = debt_landing.ABORT_ARM_AUTHORIZATION_MARK   # T-12698 host re-export alias — moved WITH its readers
ABORT_ARM_WAIVE_COVERAGE_MARK = debt_landing.ABORT_ARM_WAIVE_COVERAGE_MARK   # T-12698 host re-export alias — moved WITH its readers

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
# THE FIFTH SHAPE, AND IT IS A CONSUMER'S (T-12406 / <project> X-1326). A CONSUMER verify LAYER that
# runs out of wall-clock reaches this same reader as a `verify-failed` row, because
# `worktree._run_verify_tests` appends its `verify layer 'X' command TIMED OUT after Ns` sentence to
# the SHARED `bad` list WITHOUT `_VERIFY_TIMEOUT_MARKER` — so the class fork never sees a timeout and
# rule (2) above answered `test-failure`, which is the one arm the render is entitled to call a caught
# defect. Measured on <project>, 2026-09-04: SIX `land_completed{abort, verify-failed}` rows across FOUR
# branches (T-0617, T-0621 x2, T-0623 x2, T-0624), each carrying exactly ONE assertion (that sentence),
# `failing_tests` EMPTY, and a `consumer_verify_layers` trail whose `frontend-unit` layer reads
# `outcome: timed-out` at ~300.1 s against a 300.0 s limit while `static` / `sandbox` / `stack` all
# PASSED. A host that times out an otherwise-healthy layer under a land wave is a host/limits signal;
# the echo priced all six as the gate EARNING ITS KEEP, and the honest signal was invisible.
#
#       6  a TIMED-OUT layer in the trail, every non-guard assertion is its timeout sentence
#                                                                      -> layer-timeout   [<project>]
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
ABORT_ARM_TEST_FAILURE = debt_landing.ABORT_ARM_TEST_FAILURE   # T-12698 host re-export alias — moved WITH its readers
ABORT_ARM_CORPUS_BOOKKEEPING = debt_landing.ABORT_ARM_CORPUS_BOOKKEEPING   # T-12698 host re-export alias — moved WITH its readers
ABORT_ARM_MIXED = debt_landing.ABORT_ARM_MIXED   # T-12698 host re-export alias — moved WITH its readers
ABORT_ARM_LAYER_TIMEOUT = debt_landing.ABORT_ARM_LAYER_TIMEOUT   # T-12698 host re-export alias — moved WITH its readers
                                                   # host/limits signal, not a statement about the code
# The two things that prove a layer timeout, kept beside the arm they attribute. The OUTCOME is the
# structured trail T-11973 records (`land_completed.data.consumer_verify_layers[*].outcome`); the MARK
# is the invariant opening of the sentence `worktree._run_verify_tests` appends to the shared `bad`
# list on a layer timeout, used ONLY by the legacy belt for rows predating that trail.
_LAYER_TIMEOUT_OUTCOME = debt_landing._LAYER_TIMEOUT_OUTCOME   # T-12698 host re-export alias — moved WITH its readers
_LAYER_TIMEOUT_ASSERTION_MARK = debt_landing._LAYER_TIMEOUT_ASSERTION_MARK   # T-12698 host re-export alias — moved WITH its readers
# THE ARM VOCABULARY'S ONE HOME (CHARTER §P5). The render asks THIS which of a gate-caught group's
# rows the "a real defect caught before it landed" sentence may be said of, instead of re-listing arm
# names in the echo text where they could silently drift from the fold that produces them.
ABORT_ARMS_CAUGHT_DEFECT = debt_landing.ABORT_ARMS_CAUGHT_DEFECT   # T-12698 host re-export alias — moved WITH its readers


@functools.wraps(debt_landing.abort_arm_is_caught_defect)
def abort_arm_is_caught_defect(*a, _inj=("ABORT_ARMS_CAUGHT_DEFECT",), **kw):
    """T-12698 host residue — body in `bin/lib/debt_landing.py#abort_arm_is_caught_defect`; host names read HERE at call time."""
    for _k in _inj:
        kw.setdefault(_k, globals()[_k])
    return debt_landing.abort_arm_is_caught_defect(*a, **kw)
_residue_binds(abort_arm_is_caught_defect)
# Each corpus guard's own invariant opening, as `_surface_failing_assertions` records it. Matched as
# a PREFIX-ish containment on the assertion element (the guards compose the rest of the sentence from
# the offending path), never on a flattened blob.
_CORPUS_GUARD_MARKS = debt_landing._CORPUS_GUARD_MARKS   # T-12698 host re-export alias — moved WITH its readers


@functools.wraps(debt_landing._is_corpus_guard_assertion)
def _is_corpus_guard_assertion(*a, _inj=("_CORPUS_GUARD_MARKS",), **kw):
    """T-12698 host residue — body in `bin/lib/debt_landing.py#_is_corpus_guard_assertion`; host names read HERE at call time."""
    for _k in _inj:
        kw.setdefault(_k, globals()[_k])
    return debt_landing._is_corpus_guard_assertion(*a, **kw)
_residue_binds(_is_corpus_guard_assertion)


@functools.wraps(debt_landing._row_has_timed_out_layer)
def _row_has_timed_out_layer(*a, _inj=("_LAYER_TIMEOUT_OUTCOME",), **kw):
    """T-12698 host residue — body in `bin/lib/debt_landing.py#_row_has_timed_out_layer`; host names read HERE at call time."""
    for _k in _inj:
        kw.setdefault(_k, globals()[_k])
    return debt_landing._row_has_timed_out_layer(*a, **kw)
_residue_binds(_row_has_timed_out_layer)


@functools.wraps(debt_landing._is_layer_timeout_assertion)
def _is_layer_timeout_assertion(*a, _inj=("_LAYER_TIMEOUT_ASSERTION_MARK",), **kw):
    """T-12698 host residue — body in `bin/lib/debt_landing.py#_is_layer_timeout_assertion`; host names read HERE at call time."""
    for _k in _inj:
        kw.setdefault(_k, globals()[_k])
    return debt_landing._is_layer_timeout_assertion(*a, **kw)
_residue_binds(_is_layer_timeout_assertion)


@functools.wraps(debt_landing._abort_arm_rebaseline)
def _abort_arm_rebaseline(*a, _inj=("ABORT_ARM_AUTHORIZATION", "ABORT_ARM_AUTHORIZATION_MARK",
                                    "ABORT_ARM_INLAND_REAUDIT", "ABORT_ARM_UNATTRIBUTED",
                                    "ABORT_ARM_WAIVE_COVERAGE", "ABORT_ARM_WAIVE_COVERAGE_MARK",), **kw):
    """T-12698 host residue — body in `bin/lib/debt_landing.py#_abort_arm_rebaseline`; host names read HERE at call time."""
    for _k in _inj:
        kw.setdefault(_k, globals()[_k])
    return debt_landing._abort_arm_rebaseline(*a, **kw)
_residue_binds(_abort_arm_rebaseline)


@functools.wraps(debt_landing._abort_arm_verify_failed)
def _abort_arm_verify_failed(*a, _inj=("ABORT_ARM_CORPUS_BOOKKEEPING", "ABORT_ARM_LAYER_TIMEOUT",
                                       "ABORT_ARM_MIXED", "ABORT_ARM_TEST_FAILURE",
                                       "ABORT_ARM_UNATTRIBUTED", "_is_corpus_guard_assertion",
                                       "_is_layer_timeout_assertion", "_row_has_timed_out_layer",), **kw):
    """T-12698 host residue — body in `bin/lib/debt_landing.py#_abort_arm_verify_failed`; host names read HERE at call time."""
    for _k in _inj:
        kw.setdefault(_k, globals()[_k])
    return debt_landing._abort_arm_verify_failed(*a, **kw)
_residue_binds(_abort_arm_verify_failed)


# The per-class dispatch. A class name maps to the ONE reader that knows its two refusals; the two
# readers share no rule, because the two class names union different things. Adding a third split
# class is a row here plus its own reader — never a widening of somebody else's.
_ABORT_ARM_READERS = {
    "rebaseline-unauthorized": _abort_arm_rebaseline,
    "verify-failed": _abort_arm_verify_failed,
}


@functools.wraps(debt_landing._abort_arm)
def _abort_arm(*a, _inj=("ABORT_ARM_SPLIT_CLASSES", "ABORT_ARM_UNATTRIBUTED", "_ABORT_ARM_READERS",), **kw):
    """T-12698 host residue — body in `bin/lib/debt_landing.py#_abort_arm`; host names read HERE at call time."""
    for _k in _inj:
        kw.setdefault(_k, globals()[_k])
    return debt_landing._abort_arm(*a, **kw)
_residue_binds(_abort_arm)


@functools.wraps(debt_landing._abort_label)
def _abort_label(*a, **kw):
    """T-12698 host residue — the body now lives in `bin/lib/debt_landing.py#_abort_label`."""
    return debt_landing._abort_label(*a, **kw)


@functools.wraps(debt_landing._abort_attributed_wait_ms)
def _abort_attributed_wait_ms(*a, **kw):
    """T-12698 host residue — the body now lives in `bin/lib/debt_landing.py#_abort_attributed_wait_ms`."""
    return debt_landing._abort_attributed_wait_ms(*a, **kw)


@functools.wraps(debt_landing._abort_phase_split)
def _abort_phase_split(*a, **kw):
    """T-12698 host residue — the body now lives in `bin/lib/debt_landing.py#_abort_phase_split`."""
    return debt_landing._abort_phase_split(*a, **kw)


@functools.wraps(debt_landing._abort_reservation_wait)
def _abort_reservation_wait(*a, **kw):
    """T-12698 host residue — the body now lives in `bin/lib/debt_landing.py#_abort_reservation_wait`."""
    return debt_landing._abort_reservation_wait(*a, **kw)


@functools.wraps(debt_landing._abort_rows)
def _abort_rows(*a, _inj=("ABORT_PAID_VERIFY_MARKER", "ABORT_PREFLIGHT_MARKER", "ABORT_UNCLASSIFIED",
                          "_abort_arm", "_abort_attributed_wait_ms", "_abort_phase_split",
                          "_abort_reservation_wait", "_parse_stamped_deadline", "_window_segment_floor",), **kw):
    """T-12698 host residue — body in `bin/lib/debt_landing.py#_abort_rows`; host names read HERE at call time."""
    for _k in _inj:
        kw.setdefault(_k, globals()[_k])
    return debt_landing._abort_rows(*a, **kw)
_residue_binds(_abort_rows)


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


@functools.wraps(debt_landing._abort_group)
def _abort_group(*a, _inj=("ABORT_GATE_CAUGHT_CLASSES", "ABORT_INCONCLUSIVE_CLASSES",), **kw):
    """T-12698 host residue — body in `bin/lib/debt_landing.py#_abort_group`; host names read HERE at call time."""
    for _k in _inj:
        kw.setdefault(_k, globals()[_k])
    return debt_landing._abort_group(*a, **kw)
_residue_binds(_abort_group)


@functools.wraps(debt_landing._abort_trend)
def _abort_trend(*a, _inj=("ABORT_COST_DECAY_RATIO", "ABORT_COST_GROWTH_RATIO",
                           "ABORT_COST_TREND_FLOOR_MS",), **kw):
    """T-12698 host residue — body in `bin/lib/debt_landing.py#_abort_trend`; host names read HERE at call time."""
    for _k in _inj:
        kw.setdefault(_k, globals()[_k])
    return debt_landing._abort_trend(*a, **kw)
_residue_binds(_abort_trend)


@functools.wraps(debt_landing.aborted_land_cost)
def aborted_land_cost(*a, _inj=("ABORT_COST_GROUPS", "ABORT_COST_MATERIAL_MS", "ABORT_COST_WINDOW_DAYS",
                                "_abort_group", "_abort_label", "_abort_rows", "_abort_trend",
                                "_aborted_land_cost_result", "abort_class_is_park_limit_eviction",), **kw):
    """T-12698 host residue — body in `bin/lib/debt_landing.py#aborted_land_cost`; host names read HERE at call time."""
    for _k in _inj:
        kw.setdefault(_k, globals()[_k])
    return debt_landing.aborted_land_cost(*a, **kw)
_residue_binds(aborted_land_cost)


@functools.wraps(debt_landing._aborted_land_cost_result)
def _aborted_land_cost_result(*a, **kw):
    """T-12698 host residue — the body now lives in `bin/lib/debt_landing.py#_aborted_land_cost_result`."""
    return debt_landing._aborted_land_cost_result(*a, **kw)


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

    The read is windowed at the WIDEST bound through `_window_segment_floor` over the segments
    `segment_paths_since` admits (SPEC-0190 rule 4) and each row is still placed by its own `ts`, so
    the segment pre-filter can only ever over-include. Never raises: an unreadable journal yields
    three empty sets, and the caller's youth guards then decide alone.

    T-13139 — the per-row logic is `PlanSliceReducer`, fed by `journal.reduce_journal`: inside the debt
    seam's one-pass scope it is the reducer that scope already fed (this fold reads EVERY type for its
    `touched` set, so it cannot be a typed read), outside it one bounded walk of the selected segments.
    The segment selection is applied to the reducer's per-segment record, so both answer exactly
    what the windowed fold answered."""
    since = _window_segment_floor(now, days=_PLAN_SLICE_STALE_BOUND_DAYS)
    try:
        reducer = journal.reduce_journal(events_path, PlanSliceReducer, name="plan_slice", since=since)
        allowed = journal.segment_indices(events_path, since) if since else None
    except (OSError, UnicodeDecodeError, TypeError):
        return set(), set(), set()
    return reducer.result(now, allowed)


class PlanSliceReducer:
    """`_plan_slice_recent`'s per-row logic (T-13139) — fed every admitted row, it keeps the LATEST placed
    `ts` per (task id, segment) and the `plan_stage_entered` rows, never the rows themselves.

    The latest `ts` is enough because the clause is monotone: "some row of this task is younger than
    the bound" holds iff its youngest row is. It is kept PER SEGMENT so the caller's segment selection
    decides exactly the rows the windowed fold would have seen."""

    def __init__(self):
        self._touch: dict = {}
        self._plan: list = []

    def add(self, seq, seg, event, line) -> None:
        ts = _parse_stamped_deadline(event.get("ts"))
        if ts is None:
            return                        # no establishable date ⇒ not placeable in any window
        tid = event.get("task_id")
        if isinstance(tid, str) and tid.strip():
            key = (tid.strip(), seg)
            cur = self._touch.get(key)
            if cur is None or ts > cur:
                self._touch[key] = ts
        if event.get("type") != _PLAN_STAGE_EVENT:
            return
        data = event.get("data") if isinstance(event.get("data"), dict) else {}
        slug, to = data.get("slug"), data.get("to")
        if not isinstance(slug, str) or not slug.strip() or not isinstance(to, str):
            return
        self._plan.append((seg, ts, slug.strip(), to.strip()))

    # T-13309 — the whole-history index's summary protocol (`journal._summary_identity`). A per-segment
    # instance holds one segment's rows; its summary drops the segment index (a summary is reused
    # wherever its segment sits) and `at_segment` re-places it. Datetimes travel as isoformat.
    def summary_key(self):
        return {"v": 1, "event": _PLAN_STAGE_EVENT, "parse": _parse_stamped_deadline.__qualname__}

    def summary(self):
        if len({seg for _t, seg in self._touch} | {p[0] for p in self._plan}) > 1:
            raise ValueError("a per-segment summary holds one segment")
        return {"touch": [[tid, ts.isoformat()] for (tid, _seg), ts in self._touch.items()],
                "plan": [[ts.isoformat(), slug, to] for _seg, ts, slug, to in self._plan]}

    def load_summary(self, state) -> None:
        self._touch = {(tid, None): datetime.fromisoformat(ts) for tid, ts in state["touch"]}
        self._plan = [(None, datetime.fromisoformat(ts), slug, to) for ts, slug, to in state["plan"]]

    def at_segment(self, seg) -> None:
        self._touch = {(tid, seg): ts for (tid, _s), ts in self._touch.items()}
        self._plan = [(seg, ts, slug, to) for _s, ts, slug, to in self._plan]

    def prepend(self, older) -> None:
        touch = dict(older._touch)
        for key, ts in self._touch.items():
            if key not in touch or ts > touch[key]:
                touch[key] = ts
        self._touch, self._plan = touch, older._plan + self._plan

    def result(self, now, allowed=None) -> tuple:
        decomposition, accepted, touched = set(), set(), set()
        # STRICTLY INSIDE the bound — the boundary belongs to the CANDIDATE, not to recency. The
        # rule says a candidate fires at `>= N days`, so a row EXACTLY N days old is the oldest thing
        # that still fires and must not count as a recent touch (the `<=` this replaces silenced
        # exactly the artifact at its own threshold).
        for (tid, seg), ts in self._touch.items():
            if (allowed is None or seg in allowed) and (now - ts).days < PLAN_CUT_CARD_UNTOUCHED_DAYS:
                touched.add(tid)
        for seg, ts, slug, to in self._plan:
            if allowed is not None and seg not in allowed:
                continue
            age_days = (now - ts).days
            if to == "decomposition" and age_days < PLAN_DECOMPOSITION_STALE_DAYS:
                decomposition.add(slug)
            if to == "accepted" and age_days < PLAN_UMBRELLA_RENEWAL_DAYS:
                accepted.add(slug)
        # Each set is rebuilt in SORTED insertion order: a set's iteration order follows how it was
        # filled, and this record is keyed by (task id, segment), so filling it in key order would
        # make the order an artifact of where the journal was cut (the T-11449 identity probe).
        return set(sorted(decomposition)), set(sorted(accepted)), set(sorted(touched))


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

    from lib.graph import _task_card_shape_fault   # T-13463: the one shared card-shape check
    unreadable: list = []
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
        # T-13463 — a card that cannot be read or walked DROPS ONLY ITSELF. `card_status` fills the
        # memo through a no-list `load_path`, which RAISES on a non-UTF-8 card (T-13266, by design),
        # so that one raise is caught here; the read below passes a discard list; and the ONE shared
        # shape check (`graph._task_card_shape_fault`, extended for the `requires:` this fold reads)
        # skips a mis-shaped card. Nothing is reported from here: `graph build` / `land` already
        # name a malformed card, and this view rides the SPEC-0119 echo, whose shared try would
        # otherwise blank every debt line over one bad card.
        try:
            status = state.card_status(path)
        except UnicodeDecodeError:
            continue
        if status not in ("ready", "wont-do"):
            continue
        doc = state.load_path(path, errors=unreadable)
        if _task_card_shape_fault(doc, also_iterable=("requires",)):
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


_LOAD_SENSITIVE_RATIFIED_RE = re.compile(
    r"\bratified\s+by\s+card\s+(T-\d+)\s*:\s*(?=\S)", re.IGNORECASE)


def load_sensitive_ratification(line) -> "str | None":
    """The ONE home of the RATIFY form the rule-41 view advertises (SPEC-0119 rule 41, T-12662).

    Returns the card id a carrier line's body RATIFIES the line with, or None when it carries no
    ratification. The accepted form is `ratified by card T-NNNN: <reason>` — the exact string the
    view's own `next:` text tells an author to append, because the advertised string and the accepted
    string must be one thing (this card exists because they were two).

    STRICT IN TWO DIRECTIONS, both deliberate:
      * a CARD ID is required, so a ratification is attributable to a recorded decision rather than
        to anonymous prose; and
      * a non-empty REASON must follow the colon, so the advertised ACT ("append a reason") is the
        act that actually suppresses — `ratified by card T-1: ` on its own is not a reason.
    Case-insensitive and whitespace-tolerant between the words, because the line is hand-typed;
    nothing else is normalised. A near-miss returns None and the file REPORTS — fail-closed toward
    reporting, which is the safe direction for a report-only view.

    Whether the named card EXISTS is a SEPARATE question, answered by the caller against the card id
    set (`load_sensitive_carded`'s `ids_out`): this reader answers only what the line SAYS."""
    m = _LOAD_SENSITIVE_RATIFIED_RE.search(str(line or ""))
    return m.group(1) if m else None


def load_sensitive_carded(tasks_dir, ids_out=None) -> dict:
    """Fold `tasks/*.yaml` → `{fingerprint: task_id}` for every NON-TERMINAL card that declares it
    holds a declared load-sensitive file (SPEC-0119 rule 41, T-12359).

    Args:
      tasks_dir: this repo's `tasks/` directory. Missing / unreadable ⇒ `{}` — a repo with no cards
        holds nothing, so history is never retro-charged (the SPEC-0149 lesson rule 36 also holds to).
      ids_out: OPTIONAL out-channel (T-12662) — a set the walk fills with EVERY card id it passes,
        in EVERY status, so a caller that needs "does this id name a real card?" gets it from THIS
        scan instead of opening a second one over the same corpus (the
        `verify_runner._verify_test_timeout_seconds(source_out=...)` idiom — extend, do not create).
        The id is taken from the FILENAME stem and collected BEFORE the terminal-status `continue`,
        so `done` / `wont-do` ids are included at no extra parse. That difference is the point, not
        an accident: EXISTENCE is permanent where the non-terminal fold below is not, which is what
        lets a ratification naming a long-closed card stay discharged (SPEC-0119 rule 41). Callers
        that pass nothing are byte-identically unaffected.

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
        if ids_out is not None:
            _stem = _LOAD_SENSITIVE_CARD_ID_RE.match(Path(path).name)
            if _stem:
                ids_out.add(_stem.group(1))
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


def load_sensitive_uncarded(listed, carded, card_ids=None) -> dict:
    """The rule-41 view: every DECLARED load-sensitive file that NOBODY has agreed to serialize —
    neither a non-terminal card holding it, nor a ratification on its own carrier line.

    Args:
      listed: `{<test basename>: <its carrier line>}` — the reader's answer from
        `verify_runner._load_sensitive_set`, passed IN rather than re-read, so this view can never
        disagree with the runner about what the set is (there is one parser for the carrier).
      carded: the `load_sensitive_carded` fold above.
      card_ids: the id set that fold's `ids_out` collected — every card in the corpus, in every
        status. None / empty means NO ratification can be verified, so every row REPORTS: the
        fail-closed direction for a report-only view is to report, never to discharge a line on a
        corpus nobody could read.

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
        # THE RATIFY EXIT, read from the CARRIER LINE (T-12662). The `carded` skip above is the
        # exit that EXPIRES: it holds only while a non-terminal card cites the fingerprint, so it
        # can suppress a line but never durably discharge one. A ratification is the other exit the
        # view has always ADVERTISED and never implemented — and reading it off the line is what
        # makes it durable, because the line outlives every card. The named card is
        # EXISTENCE-checked (a fabricated id must not buy permanent silence) and deliberately NOT
        # status-checked (a status check would re-create the very expiry this exit removes).
        _rat = load_sensitive_ratification(line)
        if _rat and _rat in (card_ids or ()):
            continue
        parts = str(line).split()
        entered = parts[1] if len(parts) > 1 and _LOAD_SENSITIVE_DATE_RE.match(parts[1]) else None
        rows.append({"file": name, "entered": entered, "line": str(line)})
    return _load_sensitive_uncarded_result(rows)


_LOAD_SENSITIVE_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# The card id in a `tasks/T-NNNN-<slug>.yaml` filename — the cheapest honest answer to "is this a
# real card?", needing no parse of the file (T-12662).
_LOAD_SENSITIVE_CARD_ID_RE = re.compile(r"^(T-\d+)\b")


# THE ADVERTISED EXITS, AS DATA — one entry per exit the reader IMPLEMENTS (SPEC-0119 rule 41,
# T-12662). The `next:` text is COMPOSED from this mapping and the echo RENDERS it, so an exit cannot
# be advertised without existing here, and the AC2 tripwire enumerates it: every key must have an
# exercised reader case, or the test fails. Before this, the exits were prose in two places and the
# reader implemented one of them — the whole defect this rule-41 card exists to close. The keys are
# the exit NAMES the tripwire maps its cases by; the values are the operator-facing sentences.
_LOAD_SENSITIVE_EXITS = {
    "FILE": ("FILE a card to make the file load-robust (`bin/yitc-v2 task file` — put "
             "`load-sensitive:<file>` in its `cites:` so this line stops firing while the card is "
             "open, and remove the carrier line in the ship diff)"),
    "RATIFY": ("RATIFY the line by appending `ratified by card T-NNNN: <reason>` to it in "
               "`tests/load-sensitive.txt`, which records that serialized is where the file belongs "
               "— the DURABLE exit, read off the line so it holds after the card that wrote it "
               "closes; the card it names must be a real card in `tasks/` (any status), and the "
               "reason must not be empty)"),
}
_LOAD_SENSITIVE_NEXT_HEAD = (
    "each of these will run serialized forever until a card decides otherwise. "
    f"{len(_LOAD_SENSITIVE_EXITS)} honest exits, and which one applies is a judgement about the "
    "TEST, not a sweep:")
_LOAD_SENSITIVE_NEXT_TAIL = ("Never delete the line to make the row go away — that returns the file "
                             "to the pool with nothing re-justified.")


def _load_sensitive_uncarded_result(files: list) -> dict:
    """The ONE place this view's lens/next wording lives, so the fold's exits cannot describe it
    differently (the `_unpickable_ready_result` precedent, reused)."""
    return {
        "lens": "load-sensitive-uncarded (SPEC-0119 rule 41) — files in the declared load-sensitive "
                "set (`tests/load-sensitive.txt`) that NO non-terminal card is holding AND whose "
                "carrier line carries no ratification. Entry into "
                "that set is automatic and exit is NEVER automatic by design (T-12358): a listed file "
                "no longer runs in the concurrent pool, so nothing can prove it pool-robust again and "
                "only a card can remove its line. A listed file that neither is held nor was ratified "
                "is therefore a permanent serialization nobody has agreed to. DERIVED at read time "
                "from the carrier + `tasks/` alone — zero stored state. Report-only, never a gate: it "
                "removes no line and files no card.",
        "count": len(files),
        "files": files,
        "next": (_LOAD_SENSITIVE_NEXT_HEAD + " " + ", or ".join(_LOAD_SENSITIVE_EXITS.values())
                 + " " + _LOAD_SENSITIVE_NEXT_TAIL
                 if files else
                 "every declared load-sensitive file is held by a live card or ratified on its own "
                 "carrier line — nothing owed."),
        # THE EXITS, HANDED TO THE RENDERER rather than re-spelled by it (T-12662). The echo used to
        # carry its own prose copy of these sentences, which is a third place for the text to drift
        # from the reader — the exact defect this card fixes between the `next:` text and the fold.
        # One home, two surfaces.
        "exits": dict(_LOAD_SENSITIVE_EXITS),
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
        project (`<project>` at `.../<project>`, X-0259): a pattern's `sourced_from` is authored
        by a human and may name EITHER, so matching one alone would silently miss that project's own
        evidence. Each is matched as a WHOLE token, so `<project>` can never match inside a longer
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
                "mention it. Measured 2026-08-16 across all nine v2 consumers (a consumer's X-0961): the "
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

_REMOTE_LAG_GIT_TIMEOUT = debt_landing._REMOTE_LAG_GIT_TIMEOUT   # T-12698 host re-export alias — moved WITH its readers

# The git subcommands this view MUST NEVER issue. It reads LOCAL refs only — no fetch, no ls-remote,
# no push, no pull, no connection of any kind (SPEC-0119 rule 20). Named here so the contract is
# assertable from a test rather than asserted in prose (T-11187 AC3 structural arm).
REMOTE_LAG_FORBIDDEN_GIT = frozenset({"fetch", "ls-remote", "push", "pull", "remote-http", "clone"})


@functools.wraps(debt_landing._remote_lag_git)
def _remote_lag_git(*a, _inj=("_REMOTE_LAG_GIT_TIMEOUT",), **kw):
    """T-12698 host residue — body in `bin/lib/debt_landing.py#_remote_lag_git`; host names read HERE at call time."""
    for _k in _inj:
        kw.setdefault(_k, globals()[_k])
    return debt_landing._remote_lag_git(*a, **kw)
_residue_binds(_remote_lag_git)


@functools.wraps(debt_landing._resolve_configured_remote)
def _resolve_configured_remote(*a, **kw):
    """T-12698 host residue — the body now lives in `bin/lib/debt_landing.py#_resolve_configured_remote`."""
    return debt_landing._resolve_configured_remote(*a, **kw)


@functools.wraps(debt_landing.remote_lag)
def remote_lag(*a, _inj=("_remote_lag_git", "_resolve_configured_remote",), **kw):
    """T-12698 host residue — body in `bin/lib/debt_landing.py#remote_lag`; host names read HERE at call time."""
    for _k in _inj:
        kw.setdefault(_k, globals()[_k])
    return debt_landing.remote_lag(*a, **kw)
_residue_binds(remote_lag)


# ---------------------------------------------------------------------------------------------
# DEAD LANDS (SPEC-0119 rule 23, T-11254 / <project> X-0976) — the land that died before its own
# terminal signal. The land step-1 fold commit is the marker land ALREADY wrote; the journal is the
# record of whether it ever reported. This view is the JOIN of those two things that already exist.
# ---------------------------------------------------------------------------------------------

# The land step-1 fold's commit subject (`worktree._land_bookkeeping_commit`, T-9799 / T-10821):
# `<msg_prefix>: bookkeeping (<branch>)`. ONLY the `land` prefix qualifies — `worktree sync` mints the
# byte-identical shape under its OWN prefix and a sync is NOT a land, so a sync-tipped branch is
# mid-normal-work and must stay silent. The BRANCH NAME inside the parens is matched too, so an
# authored commit that merely happens to start with the word `land:` can never impersonate the marker.
DEAD_LAND_TIP_PREFIX = debt_landing.DEAD_LAND_TIP_PREFIX   # T-12698 host re-export alias — moved WITH its readers

# The terminal row, in EITHER direction. An ABORT counts as REPORTED and therefore SUPPRESSES: it left
# a row, said what went wrong, and the repeated-abort backstop (`_land_repeated_abort_count`) already
# owns that class. This view exists for SILENCE, not for failure.
DEAD_LAND_TERMINAL_EVENT = debt_landing.DEAD_LAND_TERMINAL_EVENT   # T-12698 host re-export alias — moved WITH its readers

# T-11682 — the row a DEAD BATCH HEAD's batch already wrote about what killed it. A head that dies
# mid-verify writes no `land_completed`, so every reader that keys on that row (the abort-cost fold,
# the repeated-abort backstop, the halt cause) sees nothing — while the batch's OWN cause is sitting
# on main, on the `land_member_verdict` rows `_land_dissolve_batch` / `_land_release_peers_for_solo_head`
# emitted BEFORE the head died. Measured 2026-08-26: batch `bat-2114bce5cf05` (formed 11:02:13Z) put
# six named pinned failures and a `red_isolation_decline{pinned-entry}` on all four member rows at
# 11:10:22Z; the head then died and no surface joined the two. This is the join key.
DEAD_LAND_MEMBER_EVENT = debt_landing.DEAD_LAND_MEMBER_EVENT   # T-12698 host re-export alias — moved WITH its readers

# The keys whose PRESENCE means the row is about a RED batch. Gated on the EVIDENCE, never on the
# verdict string: rule 5's vocabulary is closed and owned elsewhere, and a `landed` / `unaccounted`
# row must never be dressable as a red.
DEAD_LAND_RED_EVIDENCE_KEYS = debt_landing.DEAD_LAND_RED_EVIDENCE_KEYS   # T-12698 host re-export alias — moved WITH its readers


@functools.wraps(debt_landing._dead_land_red_cause)
def _dead_land_red_cause(*a, _inj=("DEAD_LAND_RED_EVIDENCE_KEYS",), **kw):
    """T-12698 host residue — body in `bin/lib/debt_landing.py#_dead_land_red_cause`; host names read HERE at call time."""
    for _k in _inj:
        kw.setdefault(_k, globals()[_k])
    return debt_landing._dead_land_red_cause(*a, **kw)
_residue_binds(_dead_land_red_cause)


@functools.wraps(debt_landing._dead_land_tip_is_land_marker)
def _dead_land_tip_is_land_marker(*a, _inj=("DEAD_LAND_TIP_PREFIX",), **kw):
    """T-12698 host residue — body in `bin/lib/debt_landing.py#_dead_land_tip_is_land_marker`; host names read HERE at call time."""
    for _k in _inj:
        kw.setdefault(_k, globals()[_k])
    return debt_landing._dead_land_tip_is_land_marker(*a, **kw)
_residue_binds(_dead_land_tip_is_land_marker)


@functools.wraps(debt_landing.dead_lands)
def dead_lands(*a, _inj=("DEAD_LAND_MEMBER_EVENT", "DEAD_LAND_TERMINAL_EVENT", "_dead_land_red_cause",
                         "_dead_land_result", "_dead_land_tip_is_land_marker",
                         "_parse_stamped_deadline",), **kw):
    """T-12698 host residue — body in `bin/lib/debt_landing.py#dead_lands`; host names read HERE at call time."""
    for _k in _inj:
        kw.setdefault(_k, globals()[_k])
    return debt_landing.dead_lands(*a, **kw)
_residue_binds(dead_lands)


@functools.wraps(debt_landing.dead_land_remedy)
def dead_land_remedy(*a, **kw):
    """T-12698 host residue — the body now lives in `bin/lib/debt_landing.py#dead_land_remedy`."""
    return debt_landing.dead_land_remedy(*a, **kw)


@functools.wraps(debt_landing.dead_land_cause_clause)
def dead_land_cause_clause(*a, **kw):
    """T-12698 host residue — the body now lives in `bin/lib/debt_landing.py#dead_land_cause_clause`."""
    return debt_landing.dead_land_cause_clause(*a, **kw)


@functools.wraps(debt_landing._dead_land_result)
def _dead_land_result(*a, _inj=("dead_land_cause_clause", "dead_land_remedy",), **kw):
    """T-12698 host residue — body in `bin/lib/debt_landing.py#_dead_land_result`; host names read HERE at call time."""
    for _k in _inj:
        kw.setdefault(_k, globals()[_k])
    return debt_landing._dead_land_result(*a, **kw)
_residue_binds(_dead_land_result)


# ── SPEC-0119 rule 24 — work branches AHEAD of main (T-11303 / <project> X-1001, corrected by X-1003) ──
# The two branch namespaces `worktree new` creates, and therefore the two the lifecycle is RESPONSIBLE
# for landing. Named once so the subject bound cannot drift between the fold and its tests. A ref outside
# them (a bench fixture, a hand-cut experiment) is not lifecycle-owned work and is not this view's debt.
AHEAD_BRANCH_NAMESPACES = debt_landing.AHEAD_BRANCH_NAMESPACES   # T-12698 host re-export alias — moved WITH its readers


@functools.wraps(debt_landing.ahead_work_branches)
def ahead_work_branches(*a, _inj=("AHEAD_BRANCH_NAMESPACES", "_ahead_branches_result",
                                  "_dead_land_tip_is_land_marker", "_parse_stamped_deadline",), **kw):
    """T-12698 host residue — body in `bin/lib/debt_landing.py#ahead_work_branches`; host names read HERE at call time."""
    for _k in _inj:
        kw.setdefault(_k, globals()[_k])
    return debt_landing.ahead_work_branches(*a, **kw)
_residue_binds(ahead_work_branches)


@functools.wraps(debt_landing._ahead_branches_result)
def _ahead_branches_result(*a, **kw):
    """T-12698 host residue — the body now lives in `bin/lib/debt_landing.py#_ahead_branches_result`."""
    return debt_landing._ahead_branches_result(*a, **kw)



# ── SPEC-0119 rule 32 — LIVE work branches BEHIND main (T-11579 / <project> X-1105) ───────────────────
@functools.wraps(debt_landing.behind_work_branches)
def behind_work_branches(*a, _inj=("AHEAD_BRANCH_NAMESPACES", "_behind_branches_result",), **kw):
    """T-12698 host residue — body in `bin/lib/debt_landing.py#behind_work_branches`; host names read HERE at call time."""
    for _k in _inj:
        kw.setdefault(_k, globals()[_k])
    return debt_landing.behind_work_branches(*a, **kw)
_residue_binds(behind_work_branches)


@functools.wraps(debt_landing._behind_branches_result)
def _behind_branches_result(*a, **kw):
    """T-12698 host residue — the body now lives in `bin/lib/debt_landing.py#_behind_branches_result`."""
    return debt_landing._behind_branches_result(*a, **kw)

# ── SPEC-0119 rule 25 — CONCURRENT SESSION HOLDS on one repo (T-11353 / <project> X-1025) ─────────────
# The stamp value a worktree carries when `_read_worktree_stamp` could not resolve one (raw `git
# worktree add`, an unreadable or malformed stamp file). Named once so the fold and its tests cannot
# disagree about what "we could not tell who holds this" looks like on the wire.
UNKNOWN_HOLDER = debt_landing.UNKNOWN_HOLDER   # T-12698 host re-export alias — moved WITH its readers


@functools.wraps(debt_landing.concurrent_session_holds)
def concurrent_session_holds(*a, _inj=("UNKNOWN_HOLDER", "_concurrent_holds_result", "_hold_task_of",), **kw):
    """T-12698 host residue — body in `bin/lib/debt_landing.py#concurrent_session_holds`; host names read HERE at call time."""
    for _k in _inj:
        kw.setdefault(_k, globals()[_k])
    return debt_landing.concurrent_session_holds(*a, **kw)
_residue_binds(concurrent_session_holds)


@functools.wraps(debt_landing._hold_task_of)
def _hold_task_of(*a, **kw):
    """T-12698 host residue — the body now lives in `bin/lib/debt_landing.py#_hold_task_of`."""
    return debt_landing._hold_task_of(*a, **kw)


@functools.wraps(debt_landing._concurrent_holds_result)
def _concurrent_holds_result(*a, **kw):
    """T-12698 host residue — the body now lives in `bin/lib/debt_landing.py#_concurrent_holds_result`."""
    return debt_landing._concurrent_holds_result(*a, **kw)


@functools.wraps(debt_landing.holder_liveness)
def holder_liveness(*a, **kw):
    """T-13470 host residue — the body lives in `bin/lib/debt_landing.py#holder_liveness`."""
    return debt_landing.holder_liveness(*a, **kw)


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
_ABORT_BREADTH_EVENTS = debt_landing._ABORT_BREADTH_EVENTS   # T-12698 host re-export alias — moved WITH its readers
_ABORT_BREADTH_MEMBER_REQUEUE_VERDICT = debt_landing._ABORT_BREADTH_MEMBER_REQUEUE_VERDICT   # T-12698 host re-export alias — moved WITH its readers
_ABORT_BREADTH_MEMBER_LANDED_VERDICT = debt_landing._ABORT_BREADTH_MEMBER_LANDED_VERDICT   # T-12698 host re-export alias — moved WITH its readers
_ABORT_BREADTH_MAX_NAMED_ASSERTIONS = debt_landing._ABORT_BREADTH_MAX_NAMED_ASSERTIONS   # T-12698 host re-export alias — moved WITH its readers
_ABORT_BREADTH_WINDOW_HOURS = debt_landing._ABORT_BREADTH_WINDOW_HOURS   # T-12698 host re-export alias — moved WITH its readers
_ABORT_BREADTH_MIN_BRANCHES = debt_landing._ABORT_BREADTH_MIN_BRANCHES   # T-12698 host re-export alias — moved WITH its readers


@functools.wraps(debt_landing._abort_breadth_refusal)
def _abort_breadth_refusal(*a, _inj=("_ABORT_BREADTH_MEMBER_REQUEUE_VERDICT",), **kw):
    """T-12698 host residue — body in `bin/lib/debt_landing.py#_abort_breadth_refusal`; host names read HERE at call time."""
    for _k in _inj:
        kw.setdefault(_k, globals()[_k])
    return debt_landing._abort_breadth_refusal(*a, **kw)
_residue_binds(_abort_breadth_refusal)


@functools.wraps(debt_landing._abort_breadth_resolution)
def _abort_breadth_resolution(*a, _inj=("_ABORT_BREADTH_MEMBER_LANDED_VERDICT",), **kw):
    """T-12698 host residue — body in `bin/lib/debt_landing.py#_abort_breadth_resolution`; host names read HERE at call time."""
    for _k in _inj:
        kw.setdefault(_k, globals()[_k])
    return debt_landing._abort_breadth_resolution(*a, **kw)
_residue_binds(_abort_breadth_resolution)


@functools.wraps(debt_landing.land_abort_cause_breadth)
def land_abort_cause_breadth(*a, _inj=("_ABORT_BREADTH_EVENTS", "_ABORT_BREADTH_MAX_NAMED_ASSERTIONS",
                                       "_abort_breadth_refusal", "_abort_breadth_resolution",
                                       "_parse_stamped_deadline", "_window_segment_floor",), **kw):
    """T-12698 host residue — body in `bin/lib/debt_landing.py#land_abort_cause_breadth`; host names read HERE at call time."""
    for _k in _inj:
        kw.setdefault(_k, globals()[_k])
    return debt_landing.land_abort_cause_breadth(*a, **kw)
_residue_binds(land_abort_cause_breadth)


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
_BRANCH_BURN_MIN_ATTEMPTS = debt_landing._BRANCH_BURN_MIN_ATTEMPTS   # T-12698 host re-export alias — moved WITH its readers


@functools.wraps(debt_landing._branch_burn_land_row)
def _branch_burn_land_row(*a, _inj=("_ABORT_BREADTH_MEMBER_REQUEUE_VERDICT",), **kw):
    """T-12698 host residue — body in `bin/lib/debt_landing.py#_branch_burn_land_row`; host names read HERE at call time."""
    for _k in _inj:
        kw.setdefault(_k, globals()[_k])
    return debt_landing._branch_burn_land_row(*a, **kw)
_residue_binds(_branch_burn_land_row)


@functools.wraps(debt_landing.branch_unlanded_attempt_burn)
def branch_unlanded_attempt_burn(*a, _inj=("_ABORT_BREADTH_EVENTS", "_branch_burn_land_row",
                                           "_parse_stamped_deadline",), **kw):
    """T-12698 host residue — body in `bin/lib/debt_landing.py#branch_unlanded_attempt_burn`; host names read HERE at call time."""
    for _k in _inj:
        kw.setdefault(_k, globals()[_k])
    return debt_landing.branch_unlanded_attempt_burn(*a, **kw)
_residue_binds(branch_unlanded_attempt_burn)


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


# ---------------------------------------------------------------------------
# T-12703 (C9b): the SPEC-0161 payload-key family moved byte-identical to bin/lib/debt_spec0161.py.
# Each historical name below is a `functools.wraps` RESIDUE (host names re-supplied at call time from
# `globals()` — a monkeypatch on `debt.<name>` is honoured) or a re-export ALIAS of a moved constant.
# ---------------------------------------------------------------------------
@functools.wraps(debt_spec0161.spec0161_payload_key_coverage)
def spec0161_payload_key_coverage(*a, _inj=("SPEC0161_RECORD_HEADING",), **kw):
    """T-12703 host residue — body in `bin/lib/debt_spec0161.py#spec0161_payload_key_coverage`; host names read HERE at call time."""
    for _k in _inj:
        kw.setdefault(_k, globals()[_k])
    return debt_spec0161.spec0161_payload_key_coverage(*a, **kw)
_residue_binds(spec0161_payload_key_coverage)


_SPEC0161_TRIPLE_QUOTES = debt_spec0161._SPEC0161_TRIPLE_QUOTES
_SPEC0161_DOCSTRING_PRECEDERS = debt_spec0161._SPEC0161_DOCSTRING_PRECEDERS


@functools.wraps(debt_spec0161._spec0161_blank)
def _spec0161_blank(*a, **kw):
    """T-12703 host residue — the body now lives in `bin/lib/debt_spec0161.py#_spec0161_blank`."""
    return debt_spec0161._spec0161_blank(*a, **kw)


_SPEC0161_STRING_LITERAL = debt_spec0161._SPEC0161_STRING_LITERAL
_SPEC0161_IDENTIFIER = debt_spec0161._SPEC0161_IDENTIFIER


@functools.wraps(debt_spec0161._spec0161_is_identifier_literal)
def _spec0161_is_identifier_literal(*a, _inj=("_SPEC0161_IDENTIFIER", "_SPEC0161_STRING_LITERAL",), **kw):
    """T-12703 host residue — body in `bin/lib/debt_spec0161.py#_spec0161_is_identifier_literal`; host names read HERE at call time."""
    for _k in _inj:
        kw.setdefault(_k, globals()[_k])
    return debt_spec0161._spec0161_is_identifier_literal(*a, **kw)
_residue_binds(_spec0161_is_identifier_literal)


@functools.wraps(debt_spec0161.spec0161_code_text)
def spec0161_code_text(*a, _inj=("_SPEC0161_DOCSTRING_PRECEDERS", "_spec0161_blank", "_spec0161_is_identifier_literal",), **kw):
    """T-12703 host residue — body in `bin/lib/debt_spec0161.py#spec0161_code_text`; host names read HERE at call time."""
    for _k in _inj:
        kw.setdefault(_k, globals()[_k])
    return debt_spec0161.spec0161_code_text(*a, **kw)
_residue_binds(spec0161_code_text)


_SPEC0161_STRUCTURAL = debt_spec0161._SPEC0161_STRUCTURAL


@functools.wraps(debt_spec0161.spec0161_structural_keys)
def spec0161_structural_keys(*a, _inj=("spec0161_structural_key_sites",), **kw):
    """T-12703 host residue — body in `bin/lib/debt_spec0161.py#spec0161_structural_keys`; host names read HERE at call time."""
    for _k in _inj:
        kw.setdefault(_k, globals()[_k])
    return debt_spec0161.spec0161_structural_keys(*a, **kw)
_residue_binds(spec0161_structural_keys)


@functools.wraps(debt_spec0161.spec0161_structural_key_sites)
def spec0161_structural_key_sites(*a, _inj=("_SPEC0161_STRUCTURAL", "spec0161_code_text",), **kw):
    """T-12703 host residue — body in `bin/lib/debt_spec0161.py#spec0161_structural_key_sites`; host names read HERE at call time."""
    for _k in _inj:
        kw.setdefault(_k, globals()[_k])
    return debt_spec0161.spec0161_structural_key_sites(*a, **kw)
_residue_binds(spec0161_structural_key_sites)


_SPEC0161_EVENT_TYPE = debt_spec0161._SPEC0161_EVENT_TYPE


@functools.wraps(debt_spec0161._spec0161_payload_dict_keys)
def _spec0161_payload_dict_keys(*a, _inj=("_spec0161_payload_dict_keys",), **kw):
    """T-12703 host residue — body in `bin/lib/debt_spec0161.py#_spec0161_payload_dict_keys`; host names read HERE at call time."""
    for _k in _inj:
        kw.setdefault(_k, globals()[_k])
    return debt_spec0161._spec0161_payload_dict_keys(*a, **kw)
_residue_binds(_spec0161_payload_dict_keys)


@functools.wraps(debt_spec0161.spec0161_added_emit_pairs)
def spec0161_added_emit_pairs(*a, _inj=("_SPEC0161_EVENT_TYPE", "_spec0161_payload_dict_keys",), **kw):
    """T-12703 host residue — body in `bin/lib/debt_spec0161.py#spec0161_added_emit_pairs`; host names read HERE at call time."""
    for _k in _inj:
        kw.setdefault(_k, globals()[_k])
    return debt_spec0161.spec0161_added_emit_pairs(*a, **kw)
_residue_binds(spec0161_added_emit_pairs)


@functools.wraps(debt_spec0161.spec0161_attribute_unnamed)
def spec0161_attribute_unnamed(*a, _inj=("spec0161_structural_keys",), **kw):
    """T-12703 host residue — body in `bin/lib/debt_spec0161.py#spec0161_attribute_unnamed`; host names read HERE at call time."""
    for _k in _inj:
        kw.setdefault(_k, globals()[_k])
    return debt_spec0161.spec0161_attribute_unnamed(*a, **kw)
_residue_binds(spec0161_attribute_unnamed)


_SPEC0161_RECORD_ROW = debt_spec0161._SPEC0161_RECORD_ROW
_SPEC0161_BACKTICKED = debt_spec0161._SPEC0161_BACKTICKED
_SPEC0161_ROW_SEPARATOR = debt_spec0161._SPEC0161_ROW_SEPARATOR
_SPEC0161_ENUMERATION_DELIMITERS = debt_spec0161._SPEC0161_ENUMERATION_DELIMITERS


@functools.wraps(debt_spec0161._spec0161_record_span_keys)
def _spec0161_record_span_keys(*a, _inj=("SPEC0161_RECORD_HEADING", "_SPEC0161_BACKTICKED", "_SPEC0161_ENUMERATION_DELIMITERS", "_SPEC0161_RECORD_ROW", "_SPEC0161_ROW_SEPARATOR",), **kw):
    """T-12703 host residue — body in `bin/lib/debt_spec0161.py#_spec0161_record_span_keys`; host names read HERE at call time."""
    for _k in _inj:
        kw.setdefault(_k, globals()[_k])
    return debt_spec0161._spec0161_record_span_keys(*a, **kw)
_residue_binds(_spec0161_record_span_keys)


_SPEC0161_SPEC_NAME = debt_spec0161._SPEC0161_SPEC_NAME


@functools.wraps(debt_spec0161._spec0161_base_structural_keys)
def _spec0161_base_structural_keys(*a, _inj=("spec0161_structural_keys",), **kw):
    """T-12703 host residue — body in `bin/lib/debt_spec0161.py#_spec0161_base_structural_keys`; host names read HERE at call time."""
    for _k in _inj:
        kw.setdefault(_k, globals()[_k])
    return debt_spec0161._spec0161_base_structural_keys(*a, **kw)
_residue_binds(_spec0161_base_structural_keys)


@functools.wraps(debt_spec0161._spec0161_branch_added_code)
def _spec0161_branch_added_code(*a, _inj=("_SPEC0161_SPEC_NAME", "_spec0161_base_structural_keys", "_spec0161_record_span_keys", "spec0161_structural_key_sites",), **kw):
    """T-12703 host residue — body in `bin/lib/debt_spec0161.py#_spec0161_branch_added_code`; host names read HERE at call time."""
    for _k in _inj:
        kw.setdefault(_k, globals()[_k])
    return debt_spec0161._spec0161_branch_added_code(*a, **kw)
_residue_binds(_spec0161_branch_added_code)


@functools.wraps(debt_spec0161._spec0161_engine_record_specs)
def _spec0161_engine_record_specs(*a, **kw):
    """T-12703 host residue — the body now lives in `bin/lib/debt_spec0161.py#_spec0161_engine_record_specs`."""
    return debt_spec0161._spec0161_engine_record_specs(*a, **kw)


@functools.wraps(debt_spec0161.spec0161_branch_unnamed)
def spec0161_branch_unnamed(*a, _inj=("_spec0161_branch_added_code", "_spec0161_corpus_inputs", "_spec0161_engine_record_specs", "_spec0161_inputs", "spec0161_added_emit_pairs", "spec0161_attribute_unnamed", "spec0161_payload_key_coverage",), **kw):
    """T-12703 host residue — body in `bin/lib/debt_spec0161.py#spec0161_branch_unnamed`; host names read HERE at call time."""
    for _k in _inj:
        kw.setdefault(_k, globals()[_k])
    return debt_spec0161.spec0161_branch_unnamed(*a, **kw)
_residue_binds(spec0161_branch_unnamed)


SPEC0161_CONSUMER_FP_PREFIX = debt_spec0161.SPEC0161_CONSUMER_FP_PREFIX


@functools.wraps(debt_spec0161.spec0161_consumer_fingerprint)
def spec0161_consumer_fingerprint(*a, _inj=("SPEC0161_CONSUMER_FP_PREFIX",), **kw):
    """T-12703 host residue — body in `bin/lib/debt_spec0161.py#spec0161_consumer_fingerprint`; host names read HERE at call time."""
    for _k in _inj:
        kw.setdefault(_k, globals()[_k])
    return debt_spec0161.spec0161_consumer_fingerprint(*a, **kw)
_residue_binds(spec0161_consumer_fingerprint)


@functools.wraps(debt_spec0161.spec0161_unnamed_key_message)
def spec0161_unnamed_key_message(*a, _inj=("SPEC0161_RECORD_HEADING", "spec0161_consumer_fingerprint",), **kw):
    """T-12703 host residue — body in `bin/lib/debt_spec0161.py#spec0161_unnamed_key_message`; host names read HERE at call time."""
    for _k in _inj:
        kw.setdefault(_k, globals()[_k])
    return debt_spec0161.spec0161_unnamed_key_message(*a, **kw)
_residue_binds(spec0161_unnamed_key_message)


@functools.wraps(debt_spec0161._spec0161_corpus_inputs)
def _spec0161_corpus_inputs(*a, _inj=("_SEARCH_SKIP_DIRS",), **kw):
    """T-12703 host residue — body in `bin/lib/debt_spec0161.py#_spec0161_corpus_inputs`; host names read HERE at call time."""
    for _k in _inj:
        kw.setdefault(_k, globals()[_k])
    return debt_spec0161._spec0161_corpus_inputs(*a, **kw)
_residue_binds(_spec0161_corpus_inputs)


@functools.wraps(debt_spec0161._spec0161_inputs)
def _spec0161_inputs(*a, _inj=("_spec0161_corpus_inputs",), **kw):
    """T-12703 host residue — body in `bin/lib/debt_spec0161.py#_spec0161_inputs`; host names read HERE at call time."""
    for _k in _inj:
        kw.setdefault(_k, globals()[_k])
    return debt_spec0161._spec0161_inputs(*a, **kw)
_residue_binds(_spec0161_inputs)




def recorded_measurement_drift(events_path, *, specs_dir, code_dir, margin,
                              engine_specs_dir=None):
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

    `engine_specs_dir` (T-12618) — WHERE TO FIND THE RECORD WHEN THIS ROOT DOES NOT OWN IT, forwarded
    verbatim to `_spec0161_inputs`. SPEC-0161 is a KERNEL spec, so a `-C` consumer's `specs/` carries
    no `SPEC-0161-*.yaml`, `spec_text` came back EMPTY and the oracle's `named` test was ALWAYS false
    there: every governing pair read UNNAMED, coverage read 0.0, and this report-only line became a
    PERMANENT false reading on every consumer — naming a remedy (`spec edit SPEC-0161`) that
    SPEC-0078 refuses under `-C`, so the reader could neither act on it nor make it go away
    (<project> X-1418; measured both ways on 2026-09-14 — 0.0/2 unnamed without, 1.0/0 unnamed with).
    T-12412 gave the corpus reader that parameter and the LAND arm passes it; this fold's signature
    did not carry one at all, so the fix shipped DEAD at this seam while the helper's own tests
    passed. Keyword-only and defaulted, so omitting it reads exactly as this did before: a
    kernel-shaped root passes None (`_spec0161_engine_record_specs` returns None there) and the
    behaviour is byte-identical. The CORPUS is deliberately NOT extended — only the RECORD moves, or
    a consumer's own coverage measurement would be silently erased (`_spec0161_corpus_inputs`).

    `borrowed_record` + `remedy` (T-12619, X-1417) — WHAT IS TRUE FOR THE READER THIS LINE PRINTS TO.
    The at-or-beneath reading used to be reported to every root as "a land is being refused right
    now", which is FALSE on a consumer by construction since T-12412: `worktree._spec0161_land_preflight`
    takes the consumer arm, warns on stderr, appends ONE `deviation_captured` and RETURNS — the land
    proceeds and exits 0. The remedy named alongside it was unreachable for that same reader (a
    kernel spec edit SPEC-0078 refuses under `-C`), so the line told a consumer that something was
    broken now and that the fix was an action it could not perform; an <project> controller session
    read it at session start, treated lands as blocked, and spent four tool calls on kernel source
    establishing that they were not. `borrowed_record` is the fact (`engine_specs_dir is not None` —
    the T-12412 predicate's own answer, not a second derivation), and `remedy` is the ONE home of the
    root-specific instruction: the renderer prints it verbatim and composes none of its own, so the
    echo and this fold's `next` can never name different commands.

    Report-only and suppressed-when-clean: nothing here gates, refuses, emits, stores or refreshes."""
    corpus, code_blob, type_keys, spec_text = _spec0161_inputs(
        specs_dir, code_dir, events_path, engine_specs_dir=engine_specs_dir)
    # T-12619 (X-1417) / T-12819: WHICH ROOT IS THIS READING DESCRIBING? `engine_specs_dir` is already
    # the answer — non-None exactly when `_spec0161_engine_record_specs` found this root does NOT own
    # the record, i.e. a `-C` consumer borrowing the kernel's. Resolved HERE, ABOVE the oracle call,
    # because the oracle now needs it too (the consumer-arm membership test): ONE predicate feeds the
    # computation, the posture the line states and the remedy it names, so the three can never drift.
    borrowed = engine_specs_dir is not None
    result = spec0161_payload_key_coverage(
        corpus=corpus, code_blob=code_blob, type_keys=type_keys, spec_text=spec_text,
        borrowed_record=borrowed)

    coverage = result["coverage"]
    floor = SPEC0161_COVERAGE_FLOOR
    # TWO ARMS, and the at-or-beneath one is NOT disableable — written as an explicit disjunction
    # rather than as `coverage <= floor + margin`, which would be wrong for a NEGATIVE margin: at
    # margin -0.5 that single comparison silences a reading of 0.50 against a 0.80 floor, i.e. it
    # goes quiet exactly when a land is already being refused. The knob may make the line less
    # eager (narrow or close the APPROACH band); it may never make it blind (audit-post finding).
    drifting = coverage is not None and (
        coverage <= floor or (margin > 0 and coverage <= floor + margin))

    # THE ONE HOME OF THE REMEDY (audit-pre finding 2). The renderer prints this string verbatim and
    # composes no remedy of its own, so the debt ECHO and the `debt` verb's `next` cannot name
    # different commands. It forks for the same reason `spec0161_unnamed_key_message` does (T-12412):
    # the kernel remedy is UNEXECUTABLE by a consumer — SPEC-0161 is a kernel spec, query-only under
    # `-C`, and a consumer write into the engine corpus is refused outright (SPEC-0078). Naming it to
    # a consumer tells that reader to run a command the engine will refuse. The consumer arm points
    # at the route that actually gets a key named — `cross request` to the kernel — the SAME route
    # the land/commit WARN already names, never a second remedy vocabulary.
    # THE CONSUMER COMMAND IS RENDERED IN THE FORM THAT ROOT CAN ACTUALLY RUN (audit-post finding 1).
    # A `-C` consumer has NO local `bin/yitc-v2` — the engine is invoked from its install path with
    # `-C <consumer-root>` (the consumer verb-invocation form `session start` echoes). Printing a
    # repo-local `bin/yitc-v2 …` here would reproduce, in the replacement text, the exact defect this
    # card exists to remove: a remedy the reader cannot execute. Both paths are already in hand —
    # the engine root is `engine_specs_dir`'s parent, the consumer root is `specs_dir`'s — so the
    # command is rendered CONCRETE rather than as a form the reader must assemble.
    # AND IT IS SHELL-QUOTED (audit-post pass-2 finding, AC1). A concrete path is pasted into a
    # shell, so a checkout rooted at a path containing a space renders a `-C` argument that splits
    # into several words — the command fails, or worse, runs against a DIFFERENT root. That is this
    # card's own defect one layer down: a remedy the reader cannot run is worse than none, because
    # the reader trusts it. `shlex.quote` leaves an ordinary path byte-identical, so the common
    # rendering is unchanged and only a path that NEEDS quoting gains it.
    _engine_bin = (shlex.quote(str(Path(engine_specs_dir).parent / "bin" / "yitc-v2"))
                   if borrowed else None)
    _consumer_root = shlex.quote(str(Path(specs_dir).parent))
    remedy = (
        "SPEC-0161 is a KERNEL spec this repo cannot edit (query-only under `-C`, and a consumer "
        "write into the engine corpus is refused — SPEC-0078), so the fix is NOT a spec edit here. "
        f"Route it to the kernel, which is how these keys get named: `{_engine_bin} -C "
        f"{_consumer_root} cross request --to yitc-v2 --kind bugfix`."
        if borrowed else
        "Re-run SPEC-0161's PAYLOAD-KEY half and refresh its recorded candidate set + counts. Doing "
        "it now is one ordinary edit; doing it after the floor is crossed costs a refused land plus "
        "the re-measurement, paid by whoever happens to be landing.")

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
        "borrowed_record": borrowed,
        # T-12819 — the CONSUMER-AUTHORED types dropped from the denominator, and whether the kernel
        # catalog was parseable at all. Carried so the echo can SAY what was excluded: an exclusion
        # the reader cannot see is indistinguishable from a measurement bug. `[]` / True on the
        # kernel arm, where no membership question is asked.
        "excluded_types": result.get("excluded_types", []),
        "declared_types_resolved": result.get("declared_types_resolved", True),
        "remedy": remedy,
        # `next` IS `remedy` — not a paraphrase of it. Before T-12619 this key and the renderer each
        # carried their own wording of the same instruction, which is exactly the duplication that
        # lets two surfaces drift (CHARTER §P5). One string now serves both.
        "next": (remedy if drifting else
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
KNOWN_BROKEN_CARRIER_EVENT = debt_adoption.KNOWN_BROKEN_CARRIER_EVENT   # T-12707 host re-export alias — moved WITH its readers
KNOWN_BROKEN_RECORD_KEY = debt_adoption.KNOWN_BROKEN_RECORD_KEY   # T-12707 host re-export alias — moved WITH its readers

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
KNOWN_BROKEN_ESTABLISHING_SIDE = debt_adoption.KNOWN_BROKEN_ESTABLISHING_SIDE   # T-12707 host re-export alias — moved WITH its readers
KNOWN_BROKEN_CLEARING_SIDE = debt_adoption.KNOWN_BROKEN_CLEARING_SIDE   # T-12707 host re-export alias — moved WITH its readers

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
KNOWN_BROKEN_VACATED_REASON = debt_adoption.KNOWN_BROKEN_VACATED_REASON   # T-12707 host re-export alias — moved WITH its readers

# The test subdirectory the enumeration globs, and so the prefix a pair's file name is resolved
# against inside a historical tree. Matches `_LAND_CANDIDATE_TEST_SUBDIR` in `worktree.py`; stated
# here as this fold's own read of the same layout rather than imported, because `debt.py`
# back-imports nothing from the land path.
KNOWN_BROKEN_TEST_SUBDIR = debt_adoption.KNOWN_BROKEN_TEST_SUBDIR   # T-12707 host re-export alias — moved WITH its readers


@functools.wraps(debt_adoption._known_broken_pairs)
def _known_broken_pairs(*a, _inj=("KNOWN_BROKEN_RECORD_KEY",), **kw):
    """T-12707 host residue — body in `bin/lib/debt_adoption.py#_known_broken_pairs`; host names read HERE at call time."""
    for _k in _inj:
        kw.setdefault(_k, globals()[_k])
    return debt_adoption._known_broken_pairs(*a, **kw)
_residue_binds(_known_broken_pairs)


@functools.wraps(debt_adoption._known_broken_file)
def _known_broken_file(*a, **kw):
    """T-12707 host residue — the body now lives in `bin/lib/debt_adoption.py#_known_broken_file`."""
    return debt_adoption._known_broken_file(*a, **kw)


@functools.wraps(debt_adoption._known_broken_full_enumeration)
def _known_broken_full_enumeration(*a, **kw):
    """T-12707 host residue — the body now lives in `bin/lib/debt_adoption.py#_known_broken_full_enumeration`."""
    return debt_adoption._known_broken_full_enumeration(*a, **kw)


# T-11791 — THE KEY THAT ANSWERS "WAS THIS FILE AMONG THOSE I RAN". `verify_metrics` records what a
# land RAN as a COUNT, so before this key the only question a green land could answer was "did you
# run EVERYTHING" — and a SURGICAL repair, narrow by construction, could never answer yes. The
# emitter (`verify_runner._run_verify_tests`) writes it only on a NARROWED run, as the same BARE
# BASENAMES an attribution pair carries.
KNOWN_BROKEN_RAN_TESTS_KEY = debt_adoption.KNOWN_BROKEN_RAN_TESTS_KEY   # T-12707 host re-export alias — moved WITH its readers


@functools.wraps(debt_adoption._known_broken_ran_tests)
def _known_broken_ran_tests(*a, _inj=("KNOWN_BROKEN_RAN_TESTS_KEY",), **kw):
    """T-12707 host residue — body in `bin/lib/debt_adoption.py#_known_broken_ran_tests`; host names read HERE at call time."""
    for _k in _inj:
        kw.setdefault(_k, globals()[_k])
    return debt_adoption._known_broken_ran_tests(*a, **kw)
_residue_binds(_known_broken_ran_tests)


# T-11731 — THE KEYS THAT ANSWER "WHICH FILES DID THE DELEGATED LAYER ANSWER FOR". A consumer whose
# declared verify layer `covers:` its test dir REPLACES the kernel's bare sweep (SPEC-0152 rule 16),
# so its land rows carry NO `selection_ran_tests` and route (c) has nothing to read. Measured twice on
# 2026-08-27 (X-1151 / X-1164): a repo that did exactly what the delegation contract tells it to do
# could no longer clear a record its PRE-delegation sweep had established, and every governance-only
# branch — plan, spec, card — was refused pre-queue from then on. The emitter
# (`worktree._land_integrate`) writes the pair on the delegating branch only: the layer NAME, and the
# bare basenames of the test files the skipped sweep would have enumerated.
KNOWN_BROKEN_DELEGATED_LAYER_KEY = debt_adoption.KNOWN_BROKEN_DELEGATED_LAYER_KEY   # T-12707 host re-export alias — moved WITH its readers
KNOWN_BROKEN_DELEGATED_FILES_KEY = debt_adoption.KNOWN_BROKEN_DELEGATED_FILES_KEY   # T-12707 host re-export alias — moved WITH its readers
KNOWN_BROKEN_LAYER_ROWS_KEY = debt_adoption.KNOWN_BROKEN_LAYER_ROWS_KEY   # T-12707 host re-export alias — moved WITH its readers
KNOWN_BROKEN_LAYER_PASSED = debt_adoption.KNOWN_BROKEN_LAYER_PASSED   # T-12707 host re-export alias — moved WITH its readers


@functools.wraps(debt_adoption._known_broken_delegated_pass_files)
def _known_broken_delegated_pass_files(*a, _inj=("KNOWN_BROKEN_DELEGATED_FILES_KEY",
                                                 "KNOWN_BROKEN_DELEGATED_LAYER_KEY",
                                                 "KNOWN_BROKEN_LAYER_PASSED",
                                                 "KNOWN_BROKEN_LAYER_ROWS_KEY",), **kw):
    """T-12707 host residue — body in `bin/lib/debt_adoption.py#_known_broken_delegated_pass_files`; host names read HERE at call time."""
    for _k in _inj:
        kw.setdefault(_k, globals()[_k])
    return debt_adoption._known_broken_delegated_pass_files(*a, **kw)
_residue_binds(_known_broken_delegated_pass_files)


@functools.wraps(debt_adoption._known_broken_blob_exists)
def _known_broken_blob_exists(*a, _inj=("_PROVENANCE_GIT_TIMEOUT",), **kw):
    """T-12707 host residue — body in `bin/lib/debt_adoption.py#_known_broken_blob_exists`; host names read HERE at call time."""
    for _k in _inj:
        kw.setdefault(_k, globals()[_k])
    return debt_adoption._known_broken_blob_exists(*a, **kw)
_residue_binds(_known_broken_blob_exists)


@functools.wraps(debt_adoption.open_known_broken)
def open_known_broken(*a, _inj=("KNOWN_BROKEN_CARRIER_EVENT", "KNOWN_BROKEN_CLEARING_SIDE",
                                "KNOWN_BROKEN_ESTABLISHING_SIDE", "KNOWN_BROKEN_TEST_SUBDIR",
                                "KNOWN_BROKEN_VACATED_REASON", "_known_broken_blob_exists",
                                "_known_broken_delegated_pass_files", "_known_broken_file",
                                "_known_broken_full_enumeration", "_known_broken_pairs",
                                "_known_broken_ran_tests", "_parse_stamped_deadline",), **kw):
    """T-12707 host residue — body in `bin/lib/debt_adoption.py#open_known_broken`; host names read HERE at call time."""
    for _k in _inj:
        kw.setdefault(_k, globals()[_k])
    return debt_adoption.open_known_broken(*a, **kw)
_residue_binds(open_known_broken)


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

P8_WARN_EVENT = debt_adoption.P8_WARN_EVENT   # T-12707 host re-export alias — moved WITH its readers
# The payload key `task close` writes for a `class: infra` card (task.py). Named once here so this
# reader and that writer cannot drift.
P8_WARN_KEY = debt_adoption.P8_WARN_KEY   # T-12707 host re-export alias — moved WITH its readers
# The DECLARED carrier marker. Named ONCE — the fold reads it, the debt line's remedy prints it and
# the tests assert against it, so the three can never disagree about what a carrier looks like (the
# `DEAD_LAND_TIP_PREFIX` / `ABORT_PAID_VERIFY_MARKER` precedent).
P8_CARRIER_MARKER = debt_adoption.P8_CARRIER_MARKER   # T-12707 host re-export alias — moved WITH its readers
# The followup statuses that still HOLD an obligation. `promoted` counts: the followup became a real
# task, which is a stronger carrier than the followup was. `dropped` does not — dropping is the
# explicit decision that nothing is owed.
P8_CARRIER_FOLLOWUP_STATUSES = debt_adoption.P8_CARRIER_FOLLOWUP_STATUSES   # T-12707 host re-export alias — moved WITH its readers
# The reading HORIZON default (hours). Not a governance scalar and not a gate: what keeps a closure
# from a month ago being re-announced forever. The engine's own corpus carries 452 historical
# `adoption_evidence_seen: false` rows, so an unbounded fold would print a number nobody can act on.
P8_WARN_WINDOW_HOURS = debt_adoption.P8_WARN_WINDOW_HOURS   # T-12707 host re-export alias — moved WITH its readers
# The two CHARTER §P8 adoption-evidence event types — the ONLY discharge P8 recognises. Named here
# for the same reason `P8_WARN_KEY` is (this reader and its writer must not drift), and pinned EQUAL
# to the writer-side home `cli.py#P8_EVIDENCE_TYPES` by a test, because this module deliberately
# back-imports no host module at import time and so cannot read that constant directly.
P8_ADOPTION_EVENT_TYPES = debt_adoption.P8_ADOPTION_EVENT_TYPES   # T-12707 host re-export alias — moved WITH its readers


@functools.wraps(debt_adoption.p8_carrier_followups)
def p8_carrier_followups(*a, _inj=("P8_CARRIER_MARKER", "_TASK_ID_RE",), **kw):
    """T-12707 host residue — body in `bin/lib/debt_adoption.py#p8_carrier_followups`; host names read HERE at call time."""
    for _k in _inj:
        kw.setdefault(_k, globals()[_k])
    return debt_adoption.p8_carrier_followups(*a, **kw)
_residue_binds(p8_carrier_followups)


@functools.wraps(debt_adoption._p8_carrier_task_ids)
def _p8_carrier_task_ids(*a, _inj=("P8_CARRIER_FOLLOWUP_STATUSES", "p8_carrier_followups",), **kw):
    """T-12707 host residue — body in `bin/lib/debt_adoption.py#_p8_carrier_task_ids`; host names read HERE at call time."""
    for _k in _inj:
        kw.setdefault(_k, globals()[_k])
    return debt_adoption._p8_carrier_task_ids(*a, **kw)
_residue_binds(_p8_carrier_task_ids)


@functools.wraps(debt_adoption._p8_card_declares_carrier)
def _p8_card_declares_carrier(*a, **kw):
    """T-12707 host residue — the body now lives in `bin/lib/debt_adoption.py#_p8_card_declares_carrier`."""
    return debt_adoption._p8_card_declares_carrier(*a, **kw)


@functools.wraps(debt_adoption._p8_later_evidence_clears)
def _p8_later_evidence_clears(*a, **kw):
    """T-12707 host residue — the body now lives in `bin/lib/debt_adoption.py#_p8_later_evidence_clears`."""
    return debt_adoption._p8_later_evidence_clears(*a, **kw)


@functools.wraps(debt_adoption.uncarried_p8_warns)
def uncarried_p8_warns(*a, _inj=("P8_ADOPTION_EVENT_TYPES", "P8_WARN_EVENT", "P8_WARN_KEY",
                                 "_TASK_ID_RE", "_p8_card_declares_carrier", "_p8_carrier_task_ids",
                                 "_p8_later_evidence_clears", "_parse_stamped_deadline",), **kw):
    """T-12707 host residue — body in `bin/lib/debt_adoption.py#uncarried_p8_warns`; host names read HERE at call time."""
    for _k in _inj:
        kw.setdefault(_k, globals()[_k])
    return debt_adoption.uncarried_p8_warns(*a, **kw)
_residue_binds(uncarried_p8_warns)


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
                events_path, _window_segment_floor(now, days=span), types=(QUEUE_JUMP_FIRED_EVENT,)):
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


# ── T-13290 — the GIT-MAINTENANCE STARVATION view ────────────────────────────────────────────────
# `bin/git-maintenance.sh` journals ONE `git_maintenance_run` row per hourly window, `outcome:
# ran|deferred|failed`. Only a `ran` window does the full cruft/prune collection; a deferred one packs
# loose objects but prunes nothing. 2026-09-28..30 every window deferred for ~2 days, invisibly (the
# deferral then left no row at all). This fold is that reading: the TRAILING run of windows without a
# full collection. Windowed so it decays into silence once a window runs again.
GIT_MAINTENANCE_EVENT = "git_maintenance_run"
GIT_MAINTENANCE_WINDOW_DAYS = 7
GIT_MAINTENANCE_DEFERRAL_FLOOR = 3


def git_maintenance_deferrals(events_path, now=None, window_days: int = GIT_MAINTENANCE_WINDOW_DAYS) -> dict:
    """Fold the journal → `{consecutive, deferred, failed, since, last_ran, loose_objects, window_days,
    latest_reason, floor}` (`floor` = the run length the render starts reporting at, carried so it has
    ONE home; `latest_reason` = the newest non-ran row's RECORDED `error`/`reason`, so the reading names
    the cause the script saw instead of assuming one):
    the windows since the newest `ran` row (a row with no `outcome` is a pre-T-13290 row, which only
    the ran path ever wrote). `loose_objects` is the newest row's count. Never raises: an unreadable
    journal folds to `consecutive: 0` — a report-only surface must never nag on an unknown."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    span = max(1, int(window_days or GIT_MAINTENANCE_WINDOW_DAYS))
    empty = {"consecutive": 0, "deferred": 0, "failed": 0, "since": None, "last_ran": None,
             "loose_objects": None, "latest_reason": None, "window_days": span,
             "floor": GIT_MAINTENANCE_DEFERRAL_FLOOR}
    try:
        rows = []
        for event in journal.segment_rows_since(
                events_path, _window_segment_floor(now, days=span), types=(GIT_MAINTENANCE_EVENT,)):
            if not isinstance(event, dict) or event.get("type") != GIT_MAINTENANCE_EVENT:
                continue
            ts = _parse_stamped_deadline(event.get("ts"))
            if ts is None or (now - ts).days > span:
                continue
            rows.append((ts, event))
        rows.sort(key=lambda r: r[0])
        out = dict(empty)
        for ts, event in rows:
            data = event.get("data") if isinstance(event.get("data"), dict) else {}
            outcome = data.get("outcome") or "ran"
            loose = data.get("loose_objects")
            if loose is None and isinstance(data.get("after"), dict):
                loose = data["after"].get("loose_objects")
            out["loose_objects"] = loose
            if outcome == "ran":
                out.update(consecutive=0, deferred=0, failed=0, since=None, latest_reason=None,
                           last_ran=event.get("ts"))
                continue
            out["consecutive"] += 1
            out["failed" if outcome == "failed" else "deferred"] += 1
            out["since"] = out["since"] or event.get("ts")
            out["latest_reason"] = data.get("error") or data.get("reason")
        return out
    except Exception:                     # noqa: BLE001 — see docstring
        return empty


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

    Returns `{count, writers: {<writer>: <n>}, latest: {writer, test, reason, ts}, window_days,
    restore_failed, latest_restore_errors}`.
    The count is of WITHHOLDINGS, not distinct writers: one writer withheld nine times is the
    recurrence this view exists to make visible, and collapsing it would hide it.

    T-13579 — `restore_failed` counts the withholdings whose row carries `restore_errors`: the land
    declined to commit the write AND could not put it back, so it was left on `main`, uncommitted.
    That is a fact about THAT land — the fold reads rows, never the checkout, and cannot say whether
    the write is still there. `latest_restore_errors` is the newest such row's own list. A
    withholding is counted either way (the write was not committed); what this keeps the line from
    doing is calling it restored.

    Never raises: an unreadable / missing / malformed journal folds to `count: 0` — a REPORT-ONLY
    surface must never nag on, or die of, an unknown (the rule-9 fold's contract, reused)."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    span = max(1, int(window_days or TAIL_WITHHELD_WINDOW_DAYS))
    writers: dict = {}
    latest = None
    count = 0
    restore_failed, latest_restore_errors = 0, None
    try:
        for event in journal.segment_rows_since(
                events_path, _window_segment_floor(now, days=span), types=(TAIL_WITHHELD_EVENT,)):
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
            errs = data.get("restore_errors")
            if isinstance(errs, list) and errs:
                restore_failed += 1
                latest_restore_errors = [str(e) for e in errs]
    except Exception:                     # noqa: BLE001 — see docstring
        return {"count": 0, "writers": {}, "latest": None, "window_days": int(window_days),
                "restore_failed": 0, "latest_restore_errors": None}
    return {"count": count, "writers": writers, "latest": latest, "window_days": int(window_days),
            "restore_failed": restore_failed, "latest_restore_errors": latest_restore_errors}


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
                events_path, _window_segment_floor(now, days=span), types=(PREQUEUE_REFUSAL_EVENT,)):
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


def _is_count(v) -> bool:
    """A real numeric count — `bool` excluded, since it is an `int` subclass."""
    return isinstance(v, (int, float)) and not isinstance(v, bool)


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
    # T-12840 — the folds axis divides by `artifacts` (distinct physical files the row's span folded),
    # SPEC-0190 rule 10's "per artifact in scope". The repo's OWN `segments` count is the wrong
    # denominator whenever a seam's scope includes a FOREIGN journal: `--lifecycle-integrity` read 291
    # distinct artifacts ~once each (314 folds) and was reported 2.75x over 114 own segments. A real
    # re-read still reads > 1 (T-12204's 294 folds over 98 artifacts = 3.0). Rows written before the
    # key existed carry no `artifacts` and keep the `segments` reading until they leave the window.
    _folds_den = "artifacts" if _is_count(reads.get("artifacts")) else "segments"
    for name, num_key, den_key, floor in (
            ("folds_per_segment", "folds", _folds_den, SEAM_READ_MIN_SEGMENTS),
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


def _seam_exemption_bound(exemptions, verb: str, default: float, today=None) -> float:
    """The bound THIS seam is held to — `default`, unless a `reads.exemptions[]` entry names it.

    THE VISIBLE READER THE CARRIER NEVER HAD. `init.py#_hook_reads_exemptions` validates the entry's
    shape fail-closed and its own docstring records the gap this closes: "this surface has NO reader
    that fails visibly ... a half-registered entry would be inert AND invisible". A declared exemption
    that changed no reported number would be exactly that. So the four-field entry SPEC-0190 rule 10
    requires is honoured here, at the one place a bound is applied.

    SHAPE ONLY, never re-validation (the `_hook_reads_exemptions` division of labour): `seam` must
    match the verb, `ratio_bound` must be a positive number and `until` must be a date, because those
    three are what this function USES; `reason` is the hook's business and is not re-checked here, so
    a change to the carrier's shape rules has ONE home. An entry that fails this function's
    requirements yields the default — the fail-closed direction, since an unusable exemption must
    never read as a wider bound.

    T-13467 — AN ENTRY PAST ITS `until` HOLDS NOTHING (SPEC-0190 rule 10). `until` is the review-by
    date; an entry whose date is before `today` (the UTC date when not given), or that carries no
    readable date, is skipped — the rule the read-contract tripwire's `live_entries` already applies,
    so the two readers of one carrier agree. The day itself is still live.

    MATCH IS EXACT on the seam label, not a prefix: an exemption is a specific accepted risk at a
    specific wiring site, and prefix-matching `land` would silently exempt every land-family verb
    nobody wrote an entry for. RAISES the bound only (T-13467): the result is never below `default`,
    so an entry at `ratio_bound: 1` — the engine carrier's "1 widens nothing" — leaves its seam at
    the default instead of holding it under the tolerance the default exists to give."""
    if not exemptions:
        return default
    if today is None:
        today = datetime.now(timezone.utc).date()
    try:
        for e in exemptions:
            if not isinstance(e, dict) or str(e.get("seam") or "").strip() != verb:
                continue
            rb = e.get("ratio_bound")
            if isinstance(rb, bool) or not isinstance(rb, (int, float)) or rb <= 0:
                continue
            until = _exemption_until(e.get("until"))
            if until is None or until < today:
                continue
            return max(float(default), float(rb))
    except TypeError:                      # a non-iterable `exemptions` — treat as none declared
        return default
    return default


def _exemption_until(value):
    """An exemption's `until` as a date, or None: a YAML date/timestamp, or an ISO `YYYY-MM-DD` string."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value).strip())
    except ValueError:
        return None


def seam_read_leaf_verbs(verbs) -> list:
    """T-12854 — the INVOCABLE leaves of a `_live_cli_verbs()` set: a bare group that has
    `<group> <sub>` children is dropped (argparse cannot run it alone, so it never emits a
    `cli_invoked` label of its own); a group with no subcommands stays, because it IS the leaf.
    Sorted for a deterministic render. Pure — the verb set is the caller's (the parser, never a list)."""
    vs = {str(v).strip() for v in (verbs or ()) if str(v).strip()}
    groups = {v.split(" ", 1)[0] for v in vs if " " in v}
    return sorted(v for v in vs if " " in v or v not in groups)


def seam_read_coverage(events_path, verbs, *, since, until) -> dict:
    """T-12854 (T4.P6) — which verbs of the PARSER-DERIVED universe carry read counters, over the
    caller's explicit HALF-OPEN window [since, until).

    THE UNIVERSE IS THE PARSER, NOT THE JOURNAL. The P6 lens used to enumerate verbs from
    `cli_invoked` rows, which silently assumed every verb emits one; a verb that never does (land,
    task file, audit) was then simply ABSENT and read clean. Here the universe is `verbs` (the
    caller passes `_live_cli_verbs()`), so a verb with no counters lands in `unmeasured` by
    construction — no per-verb registration anywhere.

    ONE fold, one traversal: the same `_own_journal_rows` pass yields coverage AND each
    measured verb's worst-per-seam ratio via `_seam_read_ratios` (the worst observation, never the
    mean — rule 37's discipline). No default window lives here; the caller owns it.

    Returns `{since, until, universe, measured, partial, unmeasured, outside_universe[,
    journal_error]}` where each measured/partial entry is `{verb, total, with_reads, worst_ratio,
    axis, ratios}` — `ratios` holds each axis's maximum across the verb's rows, and `worst_ratio` /
    `axis` the largest of those; `partial` is a verb some of whose rows lack a `reads` block. Only
    universe verbs are graded; journal labels outside it are listed by name in `outside_universe`. Never raises: an unreadable journal yields every
    leaf unmeasured with `journal_error` set."""
    universe = seam_read_leaf_verbs(verbs)
    total: dict = {}
    with_reads: dict = {}
    worst: dict = {}
    err = None
    try:
        for event in _own_journal_rows(events_path, types=("cli_invoked",)):   # the ONE debt-sibling reader
            if event.get("type") != "cli_invoked":
                continue
            ts = _parse_stamped_deadline(event.get("ts"))
            if ts is None or ts < since or ts >= until:
                continue
            data = event.get("data") if isinstance(event.get("data"), dict) else {}
            verb = str(data.get("verb") or "").strip()
            if not verb:
                continue
            total[verb] = total.get(verb, 0) + 1
            reads = data.get("reads")
            if not isinstance(reads, dict):
                continue
            with_reads[verb] = with_reads.get(verb, 0) + 1
            axes = worst.setdefault(verb, {})
            for axis, ratio in _seam_read_ratios(reads).items():
                if ratio > axes.get(axis, -1.0):
                    axes[axis] = ratio     # the worst PER AXIS, each from whichever row maximised it
    except Exception as exc:               # noqa: BLE001 — see docstring
        total, with_reads, worst, err = {}, {}, {}, f"{type(exc).__name__}: {exc}"
    measured, partial, unmeasured = [], [], []
    for verb in universe:
        if not with_reads.get(verb):
            unmeasured.append(verb)
            continue
        ratios = dict(sorted((worst.get(verb) or {}).items()))
        axis, ratio = max(ratios.items(), key=lambda kv: kv[1]) if ratios else (None, None)
        entry = {"verb": verb, "total": total.get(verb, 0), "with_reads": with_reads[verb],
                 "worst_ratio": ratio, "axis": axis, "ratios": ratios}
        (partial if with_reads[verb] < total.get(verb, 0) else measured).append(entry)
    out = {"since": since, "until": until, "universe": universe, "measured": measured,
           "partial": partial, "unmeasured": unmeasured,
           # labels the journal carries that the parser no longer has (a retired verb): NAMED, never
           # graded as a parser verb — the graded population is the universe alone.
           "outside_universe": sorted(set(total) - set(universe))}
    if err:
        out["journal_error"] = err
    return out


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
        # T-13139 — the DECLARED read: the two types this fold keeps, over the WHOLE history (its
        # declared horizon is unchanged), with a `min_ts` LICENCE at this fold's own window floor —
        # the `(now - ts).days > span` test below rejects every row dated before it, so the debt
        # seam's scope may keep `cli_invoked` (588 MB parsed, whole history) to its window instead.
        for event in journal.iter_rows(events_path, types=("cli_invoked", "task_closed"),
                                       min_ts=_window_segment_floor(now, days=span)):
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
        seam_bound = _seam_exemption_bound(exemptions, rec["verb"], float(bound), now.date())
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


# The ENGINE QUIET LANE on the same row (SPEC-0105 §2c — `data.quiet_lane`, T-13457). The verdict
# that makes an instrument a debt line, read as an EXACT match on the `NIGHTLY_CHRONIC_VERDICT`
# terms. `failed` is what the lane records when an instrument exited non-zero, was killed at the
# lane's bound, or could not be run (bin/lib/nightly.py#_run_one_instrument) — so it covers an
# instrument that never measured AND one whose own assertion failed; this reader does not tell
# them apart, the recorded reason does. NOT `failed`, and so never a line: `skipped` (the host was
# not quiet, nothing was measured), an absent reading, and `ok` carrying `regression: true` (a
# passing run slower than its baseline — a different, measured verdict).
NIGHTLY_QUIET_LANE_FAILED = "failed"
# The pseudo-check name the lane's readings are projected under so `_nightly_chronic_spell` can walk
# them unchanged. It is a map KEY and nothing else — never a `results[]` check, never rendered.
_NIGHTLY_QUIET_LANE_CHECK = "quiet_lane"


def _nightly_quiet_lane_map(row) -> "tuple[dict, dict]":
    """One `nightly_run_completed` row → (`{instrument: {quiet_lane: verdict}}`, `{instrument: reason}`).

    THE SAME SHAPE AS `_nightly_verdict_map`, ON PURPOSE: an instrument stands where a project
    stands and its one reading where a check stands, so the spell walk that dates a chronic
    condition dates a failing instrument with no second walk written for it.

    The ENGINE lane only — the top-level `data.quiet_lane` block. The per-project lanes
    (`results[].quiet_lane`, T-12097) are a different subject and are not read here.

    A row with no block (every night before the lane shipped), a malformed block and a reading
    naming no instrument or no verdict all contribute NOTHING: membership in the map IS the claim
    "this instrument reported that night", so an unreadable night is an absent one — it ends a
    spell, it can never extend one."""
    verdicts: dict = {}
    reasons: dict = {}
    data = row.get("data") if isinstance(row.get("data"), dict) else {}
    lane = data.get("quiet_lane") if isinstance(data.get("quiet_lane"), dict) else {}
    readings = lane.get("readings") if isinstance(lane.get("readings"), list) else []
    for reading in readings:
        if not isinstance(reading, dict):
            continue
        inst = str(reading.get("instrument") or "").strip()
        if not inst or not isinstance(reading.get("verdict"), str):
            continue
        verdicts[inst] = {_NIGHTLY_QUIET_LANE_CHECK: reading["verdict"]}
        reasons[inst] = reading.get("reason")
    return verdicts, reasons


def _nightly_quiet_lane_failed(lanes, reasons) -> list:
    """The engine quiet-lane instruments whose LATEST reading is `failed`, each with its spell.

    WHY A FAILED READING IS A LINE. The lane exists to carry the wall-clock assertions SPEC-0077
    §3b took OFF the per-land verify, so a `failed` reading there is the ONLY place that assertion
    can report — whether the instrument could not run or ran and failed its own assertion — and
    the nightly said so only on its own stdout and in a block nothing read back. Measured:
    `t11451-coupled-bite-proof` read `failed` on every night from 2026-09-13 to 2026-10-02 (that
    spell was the could-not-run kind: it raised before measuring).

    ONE RECORD PER INSTRUMENT, dated by `_nightly_chronic_spell` over that instrument's own nights
    (the projection below is what lets the existing walk be reused rather than re-written): the
    first night of the CURRENT unbroken `failed` spell and its length, so a spell that cleared and
    returned is dated from its RETURN. Suppressed — no record at all — unless the LATEST night's
    reading is `failed`: an instrument stops being reported the night it reads anything else.

    `reason` is the FIRST non-empty line of what the latest night recorded, bounded. The lane stores
    `exited <rc>: <the last 400 characters of stderr>`, so the first line names the exit and where
    it happened; the rest is a traceback the row itself keeps for whoever goes to look.

    Never raises; an empty `lanes` is the nothing-to-report shape."""
    out: list = []
    try:
        if not lanes:
            return out
        for inst in sorted(lanes[-1]["map"] or {}):
            own = [{"ts": night["ts"], "map": {inst: (night["map"] or {}).get(inst) or {}}}
                   for night in lanes]
            spell = _nightly_chronic_spell(own, _NIGHTLY_QUIET_LANE_CHECK, NIGHTLY_QUIET_LANE_FAILED)
            if not spell:
                continue
            first = next((ln.strip() for ln in str((reasons or {}).get(inst) or "").splitlines()
                          if ln.strip()), "")
            out.append({"instrument": inst, "since": spell["since"], "nights": spell["nights"],
                        "reason": first[:200]})
    except Exception:                      # noqa: BLE001 — report-only: an unknown shape is silence
        return []
    return out


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

    THE ENGINE QUIET LANE RIDES THE SAME ROWS (T-13457). The row also carries `data.quiet_lane`
    (SPEC-0105 §2c), which had no reader either. Each instrument whose LATEST reading is `failed`
    gets one record in `quiet_lane` — the first night of its current unbroken failed spell, the
    night count, and the first line of the recorded reason (`_nightly_quiet_lane_failed`). It is
    read off the rows this pass already iterates, so it adds no read; it is INDEPENDENT of `count`,
    of the chronic lines, and of the two-row floor below — a `failed` reading is a fact about
    tonight, not a comparison, so it needs no previous night.

    Returns `{lens, count, projects, nights, chronic, quiet_lane}` — `projects` is one record per CHANGED project
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
             "nights": {}, "chronic": [], "quiet_lane": []}
    nights: list = []
    # The engine quiet lane, one thin entry per nightly row — EVERY row, including one whose
    # `results` yielded no verdict map and so never joins `nights`: the lane is a host duty outside
    # the project loop (SPEC-0105 §2c) and its reading does not depend on any project reporting.
    lanes: list = []
    lane_reasons: dict = {}
    try:
        # SPEC-0190 rule 4 — the WHOLE journal; T-13139 — declared: the nightly rows only.
        for event in journal.segment_rows(events_path, types=("nightly_run_completed",)):
            if not isinstance(event, dict) or event.get("type") != "nightly_run_completed":
                continue
            lane_map, lane_reasons = _nightly_quiet_lane_map(event)   # reasons: the LATEST row's only
            lanes.append({"ts": str(event.get("ts") or ""), "map": lane_map})
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
    quiet_lane = _nightly_quiet_lane_failed(lanes, lane_reasons)
    if len(nights) < 2:
        # A first night (or none) has no yesterday. Silence, never "everything changed" — for the
        # CHANGE and chronic lines. A `failed` quiet-lane reading is not a comparison and still reports.
        return {**empty, "quiet_lane": quiet_lane}

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
            "nights": {"previous": prev["ts"], "latest": latest["ts"]}, "chronic": chronic,
            "quiet_lane": quiet_lane}


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


def nightly_project_status(events_path, project: str) -> dict:
    """Fold the ENGINE journal → what the LATEST nightly said about ONE project (SPEC-0105 §1e).

    THE GAP THIS CLOSES (<project> X-1577). The nightly writes its row to the ENGINE's journal, so a
    consumer's own journal holds no nightly row at all and a `-C` session had no way to see what the
    nightly said about it. The ask was to MIRROR the row into the consumer's journal; that is a kernel
    write into another project's territory (D-0019 / SPEC-0084), so this is the VIEW instead: the rows
    already exist, one project reads its own entry out of them, and nothing is written anywhere.

    THE LATEST ROW DECIDES, BY `ts`. SPEC-0190 rule 5 promises no physical row order, so the nights
    are sorted before anything is read off them. `found` is judged against that latest row ALONE: a
    project the last run did not name is reported absent even when an older row names it, because
    printing a stale verdict as the current one is the false reading this view must not produce.

    THE CHRONIC SPELL IS THIS PROJECT'S, NOT THE FLEET'S. The rule-38 fold dates a condition from the
    first night it was present on ANY project; here the nights are restricted to this one project
    before `_nightly_chronic_spell` walks them, so "since" is the first night of THIS project's spell.
    The vocabulary (checks, verdicts, remedies, detail) is rule 38's own, reused — never re-typed.

    ONE PASS through `journal.segment_rows`, retaining only this project's verdict map per night and
    the raw `results` entry of the latest night. Never raises: an unreadable / missing journal folds
    to `nights_seen: 0`, which the render states as "no nightly verdict"."""
    out = {"project": project, "nights_seen": 0, "run_ts": None, "generated_at": None,
           "found": False, "checks": {}, "freshness": None, "project_health": None, "chronic": []}
    nights: list = []
    latest = None                           # (ts, entry-or-None, generated_at) of the latest row
    try:
        # SPEC-0190 rule 4 — the WHOLE journal; T-13139 — declared: the nightly rows only.
        for event in journal.segment_rows(events_path, types=("nightly_run_completed",)):
            if not isinstance(event, dict) or event.get("type") != "nightly_run_completed":
                continue
            ts = str(event.get("ts") or "")
            checks = _nightly_verdict_map(event).get(project)
            nights.append({"ts": ts, "map": {project: checks} if checks is not None else {}})
            if latest is None or ts >= latest[0]:
                data = event.get("data") if isinstance(event.get("data"), dict) else {}
                entry = next((r for r in (data.get("results") or [])
                              if isinstance(r, dict) and str(r.get("name") or "").strip() == project),
                             None)
                latest = (ts, entry, data.get("generated_at"))
    except Exception:                      # noqa: BLE001 — see docstring
        return out
    if latest is None:
        return out
    nights.sort(key=lambda n: n["ts"])     # stable: equal-ts rows keep their segment order
    out.update(nights_seen=len(nights), run_ts=latest[0], generated_at=latest[2])
    entry = latest[1]
    if entry is None:
        return out
    out["found"] = True
    out["checks"] = {c: v["verdict"] for c, v in entry.items()
                     if isinstance(v, dict) and isinstance(v.get("verdict"), str)}
    out["freshness"] = entry.get("freshness") if isinstance(entry.get("freshness"), dict) else None
    out["project_health"] = (entry.get("project_health")
                             if isinstance(entry.get("project_health"), dict) else None)
    for check in NIGHTLY_CHRONIC_CHECKS:
        spell = _nightly_chronic_spell(nights, check, NIGHTLY_CHRONIC_VERDICT[check])
        if spell:
            out["chronic"].append({
                "check": check, "verdict": NIGHTLY_CHRONIC_VERDICT[check],
                "since": spell["since"], "nights": spell["nights"],
                "remedy": NIGHTLY_CHRONIC_REMEDY[check],
                "detail": _nightly_chronic_detail(check, [entry], {project})})
    return out


def render_nightly_project_status(status: dict) -> list:
    """The `nightly --status` lines for one `nightly_project_status` fold (SPEC-0105 §1e).

    Absence is a stated line, never silence: a reader who sees nothing cannot tell "the nightly
    never named me" from "the view is broken". The named-check lines carry the detail that EXPLAINS
    a non-clean grade (the stale pipeline, the failing layer), because a bare `alert` sends the
    reader back to the raw row this view exists to read for them."""
    project = status.get("project")
    if not status.get("nights_seen"):
        return [f"no nightly verdict for {project} — the engine journal holds no "
                f"nightly_run_completed row"]
    if not status.get("found"):
        return [f"no nightly verdict for {project} — the latest nightly run ({status.get('run_ts')}) "
                f"did not name it (not a yitc_v2 registry project that night)"]
    lines = [f"nightly verdict for {project} — run {status.get('run_ts')} (SPEC-0105 §1e; "
             f"read-only view of the engine journal, nothing written)"]
    fr = status.get("freshness") or {}
    fr_line = f"  freshness: {fr.get('verdict', 'absent')}"
    if fr.get("reason"):
        fr_line += f" — {fr['reason']}"
    lines.append(fr_line)
    for pl in fr.get("pipelines") or []:
        if isinstance(pl, dict) and (pl.get("state") != "fresh" or pl.get("outcome") == "unreachable"):
            lines.append(f"    · pipeline {pl.get('name')}: {pl.get('state')}"
                         + (f" ({pl['outcome']})" if pl.get("outcome") else "")
                         + (f" — {pl['detail']}" if pl.get("detail") else ""))
    ph = status.get("project_health") or {}
    ph_line = f"  project_health: {ph.get('verdict', 'absent')}"
    if ph.get("reason"):
        ph_line += f" — {ph['reason']}"
    lines.append(ph_line)
    for ly in ph.get("layers") or []:
        if isinstance(ly, dict) and ly.get("outcome") != "pass":
            lines.append(f"    · layer {ly.get('layer')}: {ly.get('outcome')}"
                         + (f" (exit {ly['exit_code']})" if ly.get("exit_code") is not None else ""))
    others = sorted((c, v) for c, v in (status.get("checks") or {}).items()
                    if c not in ("freshness", "project_health"))
    if others:
        lines.append("  other checks: " + ", ".join(f"{c}={v}" for c, v in others))
    for ch in status.get("chronic") or []:
        lines.append(f"  CHRONIC {ch['check']}={ch['verdict']} for {ch['nights']} night(s) since "
                     f"{ch['since']}" + (f" — {ch['detail']}" if ch.get("detail") else "")
                     + f" — remedy: {ch['remedy']}")
    return lines


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
GAP_MARKER = debt_adoption.GAP_MARKER   # T-12707 host re-export alias — moved WITH its readers

#: The prefix of the stable dedupe key, carried on the followup's EXISTING `fingerprint` field
#: (T-10779 — a SOURCE-CLUSTER handle is exactly what this is). Never a new field.
GAP_KEY_PREFIX = debt_adoption.GAP_KEY_PREFIX   # T-12707 host re-export alias — moved WITH its readers
GAP_FILED_READ_TYPES = debt_adoption.GAP_FILED_READ_TYPES   # T-13139 — the declared read of the register

#: The reserved dimension label for the two CONSTANT_FLOOR lenses. They are unconditional — no
#: dimension activates them — so there is no dimension to name, and inventing one would make the
#: key lie about where the requirement came from.
GAP_CONSTANT_FLOOR_DIMENSION = debt_adoption.GAP_CONSTANT_FLOOR_DIMENSION   # T-12707 host re-export alias — moved WITH its readers

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
GAP_LENS_RISK_ORDER = debt_adoption.GAP_LENS_RISK_ORDER   # T-12707 host re-export alias — moved WITH its readers

#: THE CATALOG — one row per profile-required baseline item, as
#: (lens, item_id, label, carrier_section, carrier_key).
#:
#: `carrier_key` names the KEY WITHIN `carrier_section` that answers this item, or `None` when the
#: item is answered by the section AS A WHOLE. Most rows are section-granular and pass
#: `None`; the three `alert_routing` observability rows (SPEC-0164 rule 5) each name their own key,
#: because a live project is asked three separate questions and answering one must not answer the
#: others. Section granularity there let ONE declared key clear EVERY alert_routing item — so a
#: carrier declaring `health:` and a complete `slo:` but no `logs:` produced no gap at all (T-12088
#: audit-pre finding 1). `_gap_section_answer(section, key=…)` is where the distinction is read.
#:
#: `carrier_section` names the SPEC-0093 concern section whose ANSWER proves this item met. Every
#: name here is a REGISTERED section (`security` SPEC-0098 · `security.audit` SPEC-0145 ·
#: `remote_sync` SPEC-0163 · `alert_routing` SPEC-0164); none is invented, because a gap row
#: pointing at a section no spec owns would be unanswerable by construction. A DOTTED name is a
#: nested path resolved by `_gap_carrier_section` — the born template seeds the audit block as
#: `security:` → `audit:`, never top-level, so a flat `security_audit` key was unanswerable for
#: every born carrier (T-13040). A drift test pins every name here against graph/born-ops.yaml.
#: Each `security.audit` row is answered by ITS OWN KEY, never the section as a whole: the born
#: block always carries the kernel-RENDERED `profile_snapshot.command`, which states no audit, and
#: one audit `cadence:` proves nothing about webhook verification or key rotation (T-13040
#: audit-post). `webhook_verification` / `key_rotation` are not born-seeded, so those rows stay
#: UNMET until the project declares them — the fail-safe direction. The block's reasoned `waiver:`
#: still answers every key through the section-waiver fallback, exactly as for alert_routing.
#: `classification-and-deletion` reads its own `classification_and_deletion` key the same way.
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
     "the public surface is covered by a dated security audit", "security.audit", "cadence"),
    ("input-validation", "request-body-floor",
     "validation / rate-limit / CSRF / log-redaction on request intake", "security", None),
    # ID PRESERVED (T-13040 audit-post): consumer followups are keyed on it. Its own key, never born-
    # seeded, so the audit block's cadence cannot answer it — UNMET until declared or waived.
    ("data-retention", "classification-and-deletion",
     "PII classification, retention and deletion are stated", "security.audit",
     "classification_and_deletion"),
    ("payment-integrity", "webhook-verification",
     "payment webhook verification and a cost threshold", "security.audit",
     "webhook_verification"),
    ("authz", "roles-and-tenancy-probe",
     "a named authz probe over roles/tenancy", "security", None),
    ("key-rotation", "rehearsed-rotation",
     "a rehearsed rotation script covering every ciphertext surface", "security.audit",
     "key_rotation"),
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


@functools.wraps(debt_adoption.gap_item_lenses)
def gap_item_lenses(*a, **kw):
    """T-12707 host residue — the body now lives in `bin/lib/debt_adoption.py#gap_item_lenses`."""
    return debt_adoption.gap_item_lenses(*a, **kw)


@functools.wraps(debt_adoption.gap_dimension)
def gap_dimension(*a, _inj=("GAP_CONSTANT_FLOOR_DIMENSION",), **kw):
    """T-12707 host residue — body in `bin/lib/debt_adoption.py#gap_dimension`; host names read HERE at call time."""
    for _k in _inj:
        kw.setdefault(_k, globals()[_k])
    return debt_adoption.gap_dimension(*a, **kw)
_residue_binds(gap_dimension)


@functools.wraps(debt_adoption.gap_dedupe_key)
def gap_dedupe_key(*a, _inj=("GAP_KEY_PREFIX", "gap_dimension",), **kw):
    """T-12707 host residue — body in `bin/lib/debt_adoption.py#gap_dedupe_key`; host names read HERE at call time."""
    for _k in _inj:
        kw.setdefault(_k, globals()[_k])
    return debt_adoption.gap_dedupe_key(*a, **kw)
_residue_binds(gap_dedupe_key)


@functools.wraps(debt_adoption.gap_rank)
def gap_rank(*a, _inj=("GAP_LENS_RISK_ORDER",), **kw):
    """T-12707 host residue — body in `bin/lib/debt_adoption.py#gap_rank`; host names read HERE at call time."""
    for _k in _inj:
        kw.setdefault(_k, globals()[_k])
    return debt_adoption.gap_rank(*a, **kw)
_residue_binds(gap_rank)


#: The waiver reasons that read as OUT-OF-SCOPE rather than as a plain waiver. A project saying
#: "this does not apply to us" and a project saying "we accept this risk for now" are different
#: answers, and the register renders them as different terminal states rather than flattening both
#: into `waived`. Matched on the waiver's own words — the only place the distinction is written.
_GAP_OUT_OF_SCOPE_TOKENS = debt_adoption._GAP_OUT_OF_SCOPE_TOKENS   # T-12707 host re-export alias — moved WITH its readers

#: The tokens that make a DECLARATION read as `adapted` rather than `adopted` — the project met the
#: item its own way and said so. Same faithful-reading discipline: this reports what the carrier
#: says, it never judges whether the adaptation is good.
_GAP_ADAPTED_TOKENS = debt_adoption._GAP_ADAPTED_TOKENS   # T-12707 host re-export alias — moved WITH its readers


@functools.wraps(debt_adoption._gap_waiver_answer)
def _gap_waiver_answer(*a, _inj=("_GAP_OUT_OF_SCOPE_TOKENS",), **kw):
    """T-12707 host residue — body in `bin/lib/debt_adoption.py#_gap_waiver_answer`; host names read HERE at call time."""
    for _k in _inj:
        kw.setdefault(_k, globals()[_k])
    return debt_adoption._gap_waiver_answer(*a, **kw)
_residue_binds(_gap_waiver_answer)


@functools.wraps(debt_adoption._gap_section_answer)
def _gap_section_answer(*a, _inj=("GAP_CARRIER_TASK_KEY", "_GAP_ADAPTED_TOKENS", "_GAP_DECLARED_STATES",
                                  "_gap_declaration_incomplete", "_gap_section_answer",
                                  "_gap_waiver_answer",), **kw):
    """T-12707 host residue — body in `bin/lib/debt_adoption.py#_gap_section_answer`; host names read HERE at call time."""
    for _k in _inj:
        kw.setdefault(_k, globals()[_k])
    return debt_adoption._gap_section_answer(*a, **kw)
_residue_binds(_gap_section_answer)


#: The per-key answers whose CONCERN imposes a shape on them, as (section, key) -> the predicate in
#: `lib.init` that reports which required halves are missing.
#:
#: THIS NAMES WHERE TO ASK, NEVER WHAT THE ANSWER IS. A declaration that falls short of its concern's
#: shape is NOT an answer, and the concern — not this fold — is what decides "falls short". Shipped
#: as two independent readings, the two surfaces contradicted each other: `_hook_alert_routing`
#: REFUSED `slo: {objective: …}` at birth while this fold marked `one-slo-declared` adopted, so a
#: live project could close its SLO obligation with a promise carrying no number (T-12088 audit-post
#: finding, 2026-09-05). One predicate, two callers (CHARTER §P5).
_GAP_SHAPED_ANSWER_KEYS = debt_adoption._GAP_SHAPED_ANSWER_KEYS   # T-12707 host re-export alias — moved WITH its readers


@functools.wraps(debt_adoption._gap_declaration_incomplete)
def _gap_declaration_incomplete(*a, _inj=("_GAP_SHAPED_ANSWER_KEYS",), **kw):
    """T-12707 host residue — body in `bin/lib/debt_adoption.py#_gap_declaration_incomplete`; host names read HERE at call time."""
    for _k in _inj:
        kw.setdefault(_k, globals()[_k])
    return debt_adoption._gap_declaration_incomplete(*a, **kw)
_residue_binds(_gap_declaration_incomplete)


#: The terminal states that mean "the carrier DECLARED this" — the only ones a shape rule judges. A
#: `waived` / `out-of-scope` / `task-linked` row is a STANCE about the concern, not a declaration of
#: it, so the shape question does not arise (and a waiver is complete by definition).
_GAP_DECLARED_STATES = debt_adoption._GAP_DECLARED_STATES   # T-12707 host re-export alias — moved WITH its readers


#: The key a carrier section uses to say "a task is doing this" — the ONE nameable artifact the
#: writer will arm a gap followup on. A single key, read structurally, never mined out of prose:
#: routing on free text is the defect T-10335 records.
GAP_CARRIER_TASK_KEY = debt_adoption.GAP_CARRIER_TASK_KEY   # T-12707 host re-export alias — moved WITH its readers

_GAP_TASK_ID_RE = debt_adoption._GAP_TASK_ID_RE   # T-12707 host re-export alias — moved WITH its readers


@functools.wraps(debt_adoption.gap_task_linked)
def gap_task_linked(*a, _inj=("_GAP_TASK_ID_RE",), **kw):
    """T-12707 host residue — body in `bin/lib/debt_adoption.py#gap_task_linked`; host names read HERE at call time."""
    for _k in _inj:
        kw.setdefault(_k, globals()[_k])
    return debt_adoption.gap_task_linked(*a, **kw)
_residue_binds(gap_task_linked)


@functools.wraps(debt_adoption._gap_filed_rows)
def _gap_filed_rows(*a, _inj=("GAP_KEY_PREFIX",), **kw):
    """T-12707 host residue — body in `bin/lib/debt_adoption.py#_gap_filed_rows`; host names read HERE at call time."""
    for _k in _inj:
        kw.setdefault(_k, globals()[_k])
    return debt_adoption._gap_filed_rows(*a, **kw)
_residue_binds(_gap_filed_rows)


@functools.wraps(debt_adoption._gap_age_days)
def _gap_age_days(*a, **kw):
    """T-12707 host residue — the body now lives in `bin/lib/debt_adoption.py#_gap_age_days`."""
    return debt_adoption._gap_age_days(*a, **kw)


def _gap_carrier_section(carrier, section_name):
    """The carrier node a catalog `section_name` names — a dotted name descends nested mappings
    (`security.audit` → carrier["security"]["audit"]), the convention init uses for nested carrier
    paths. Any non-mapping hop reads as absent (None ⇒ UNMET, the fail-safe direction)."""
    node = carrier
    for part in section_name.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(part)
    return node


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
            # T-13041: a multi-lens row names the lens that ACTUALLY admitted it (display + autofile
            # text); `lens`/`key` stay on the primary so no filed row is re-keyed or re-filed.
            activated_by = next(l for l in lenses if l in active)
            base = {"lens": lens, "activated_by": activated_by, "item_id": item_id, "label": label,
                    "carrier": section_name, "key": gap_dedupe_key(lens, item_id)}
            # `carrier_key` is None for a section-granular item, which is exactly the historical
            # call — so the ten pre-existing rows read identically and only the three SPEC-0164
            # rule-5 rows take the per-key path.
            answer = _gap_section_answer(_gap_carrier_section(carrier, section_name), key=carrier_key,
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


@functools.wraps(debt_adoption.gap_autofile_text)
def gap_autofile_text(*a, _inj=("GAP_MARKER", "gap_dimension",), **kw):
    """T-12707 host residue — body in `bin/lib/debt_adoption.py#gap_autofile_text`; host names read HERE at call time."""
    for _k in _inj:
        kw.setdefault(_k, globals()[_k])
    return debt_adoption.gap_autofile_text(*a, **kw)
_residue_binds(gap_autofile_text)


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
# `no`/`not` are NOT here: dropping them inverted the label ("… does not meet" -> "… does meet", T-13091).
_DEBT_CLASS_STOPWORDS = frozenset((
    "a", "an", "and", "are", "at", "awaiting", "by", "for", "from", "in", "is", "its", "more",
    "of", "on", "or", "our", "over", "per", "still", "than", "that", "the", "their",
    "them", "then", "there", "these", "they", "this", "to", "up", "was", "were", "with", "yet",
))
# Kept in the label but not counted toward DEBT_CLASS_MAX_WORDS, so a negation never pushes the word it
# negates past the cap and a negation-free head derives the same slug it always did (T-13091).
_DEBT_CLASS_NEGATIONS = frozenset(("no", "not"))

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
    head = _DEBT_FIGURES_RE.sub(" ", body.split("—", 1)[0])
    m = re.search(r"\b(\d+)\b", head)
    return int(m.group(1)) if m else 1


# T-13621 (SPEC-0119 rule 40): a head MAY carry ONE square-bracketed FIGURES span — the numbers a
# single integer cannot hold (seconds, a share, a 7-day change). It is stripped before the class and
# the count are derived, and the row prints it after the count, so a line without one renders exactly
# as before. Taken from the line itself, like the class and the verb: no per-class code here.
_DEBT_FIGURES_RE = re.compile(r"\[[^\[\]]*\]")


def debt_row_figures(line: str) -> str:
    """The FIRST square-bracketed span of the line's head, without its brackets, else ''."""
    _prefix, body = _debt_line_prefix(line)
    m = _DEBT_FIGURES_RE.search(body.split("—", 1)[0])
    return " ".join(m.group(0)[1:-1].split()) if m else ""


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
    the per-project nightly lines fold together, drop stopwords (never a negation), lowercase, cap at
    DEBT_CLASS_MAX_WORDS non-negation words (a
    every later negation is appended with the word it negates). Two lines that derive the same slug are ONE class and fold to one row with
    summed counts — which is exactly what the card asks for for the nightly/chronic lines."""
    prefix, body = _debt_line_prefix(line)
    head = _DEBT_FIGURES_RE.sub(" ", body.split("—", 1)[0])   # the figures span is not identity
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
    kept, i = [], 0
    while i < len(words) and len([w for w in kept if w not in _DEBT_CLASS_NEGATIONS]) < DEBT_CLASS_MAX_WORDS:
        kept.append(words[i])
        i += 1
    # Every negation past the cap still reaches the label, with the word it negates (T-13091).
    tail_at = i
    for j in range(i, len(words)):
        if words[j] in _DEBT_CLASS_NEGATIONS:
            kept.extend(words[max(j, tail_at):j + 2])
            tail_at = j + 2
    return " ".join(kept) or prefix


def debt_echo_table(_debt_echo_lines, *, cli_form: str = "bin/yitc-v2") -> list:
    """The compact table the two ECHO seams render: `<marker>: <class> | <count> | <verb>`.

    One row per non-clean class, in FIRST-APPEARANCE order (so the render stays as stable as the
    renderer that fed it), equal classes folded with their counts summed, every row within
    DEBT_ROW_WIDTH. Clean in → clean out: an empty input yields an empty list, which is how
    suppressed-when-clean survives this change untouched (SPEC-0119 rule 5) — the table renderer
    prints no header, ever, precisely so that property is structural.

    `cli_form` (T-13075) is the host's `_cli_invocation_form()`. At the bare default the output is
    byte-identical to the engine render. Any other form (a consumer build, which has no local
    `bin/yitc-v2`) prints ONE prefix line naming that invocation above the rows, and each row's
    pointer drops its leading `bin/yitc-v2 ` — an engine-absolute `-C` form is ~70 chars, so
    repeating it per row would push rows past DEBT_ROW_WIDTH and truncate the pointer itself."""
    order = []
    rows = {}
    for line in list(_debt_echo_lines or ()):
        if not str(line or "").strip():
            continue
        prefix, _body = _debt_line_prefix(line)
        key = (prefix, debt_row_class(line))
        if key not in rows:
            order.append(key)
            rows[key] = {"count": 0, "verb": debt_row_verb(line), "figures": []}
        rows[key]["count"] += debt_row_count(line)
        _fig = debt_row_figures(line)
        if _fig and _fig not in rows[key]["figures"]:
            rows[key]["figures"].append(_fig)
    out = []
    bare = _DEBT_DEFAULT_VERB.split(" ", 1)[0]
    if order and cli_form != bare:
        out.append(f"{order[0][0]}: run each verb below as: {cli_form} <verb>")
    for key in order:
        prefix, klass = key
        verb = rows[key]["verb"]
        if cli_form != bare and verb.startswith(bare + " "):
            verb = verb[len(bare) + 1:]
        figures = "; ".join(rows[key]["figures"])
        row = f"{prefix}: {klass}{_DEBT_ROW_SEP}{rows[key]['count']}{_DEBT_ROW_SEP}{verb}"
        if figures:
            # the figures are shortened FIRST, so an over-wide row never loses its verb (T-13621)
            room = DEBT_ROW_WIDTH - len(row) - 3
            if len(figures) > room:
                figures = figures[:max(room - 1, 0)].rstrip() + "…"
            if room > 1:
                row = (f"{prefix}: {klass}{_DEBT_ROW_SEP}{rows[key]['count']} [{figures}]"
                       f"{_DEBT_ROW_SEP}{verb}")
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


def _lane_carrier_entries(path) -> dict:
    """{basename: entry-date token} over the carrier, by the runner's grammar (see
    `_lane_carrier_files`). The token is the line's SECOND whitespace-separated field — the carrier
    header's `<entered YYYY-MM-DD>` — or '' when the line has none; the first occurrence of a
    basename wins, as in the file list (T-13621)."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return {}
    out = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if parts[0].endswith(".py") and parts[0] not in out:
            out[parts[0]] = parts[1] if len(parts) > 1 else ""
    return out


def _lane_carrier_files(path) -> list:
    """The carrier's listed basenames, read by the SAME grammar the runner reads it with
    (`verify_runner._load_sensitive_set`): blank lines and `#` comments skipped, the FIRST
    whitespace-separated token is the test file's basename, the rest is provenance for humans.
    Restated here rather than imported because `verify_runner` is the LAND path and this is a
    report-only fold — but the grammar is the runner's, and the identity is the basename, which is
    unambiguous by that runner's own duplicate-basename refusal (SPEC-0185 / T-11204)."""
    return list(_lane_carrier_entries(path))


def load_sensitive_lane(root=None, *, carrier=None, table=None, env=None, today=None) -> dict:
    """T-12360 — the SEQUENTIAL-TAIL reading of the declared load-sensitive lane, folded from the two
    artifacts that already exist: the carrier `tests/load-sensitive.txt` (T-12358) and the FIXED
    per-file duration table `tests/verify-durations.json` (T-11316 / SPEC-0132 §6).

    Returns `{count, wall_s, suite_wall_s, share_pct, bound_share_pct, bound_files, unrecorded,
    entry_window_days, entered, entered_s, undated, crossed: [...]}` — the four entry keys being the
    T-13621 7-day reading (present only once the table was read). `wall_s` is the lane's SERIALIZED wall — the sum of the LISTED files' recorded
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
    dated = _lane_carrier_entries(carrier_path)   # ONE read of the carrier: names + entry dates
    listed = list(dated)
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
    # T-13621 — the 7-day ENTRY reading, from the carrier's own per-line entry date and the SAME
    # table: how many listed files entered inside the window and their recorded seconds. A line whose
    # date is missing or does not parse is counted as UNDATED and named, never dropped. Files that
    # LEFT the lane are not read at all (owner ruling events.jsonl#ts=2026-10-06T11:27:44Z).
    _today = today or datetime.now(timezone.utc).date()
    window_days = 7                    # the card's «last 7 days»; a reading window, not a bound
    entered, entered_s, undated = 0, 0.0, 0
    for name in listed:
        try:
            when = date.fromisoformat(str(dated.get(name) or ""))
        except ValueError:
            undated += 1
            continue
        if 0 <= (_today - when).days < window_days:
            entered += 1
            try:
                entered_s += _secs(files.get(name) or 0)
            except (TypeError, ValueError):
                pass
    out.update({"count": len(listed), "files": listed, "wall_s": round(lane, 1),
                "suite_wall_s": round(suite, 1), "share_pct": round(share, 1),
                "unrecorded": unrecorded, "entry_window_days": window_days,
                "entered": entered, "entered_s": round(entered_s, 1), "undated": undated})
    if share > bound_share:
        out["crossed"].append("share")
    if len(listed) > bound_files:
        out["crossed"].append("files")
    return out


# ---------------------------------------------------------------------------------------------
# T-12710 (C11c) — the 3 `_debt_echo_*` host bodies, relocated here byte-identical from `bin/lib/cli.py`
# (plan extract-the-13-over-budget-bin-lib-modules-into-le §Extraction map C11c;
# lessons/library-extraction.md — Design B full inject-residue seam, the C11b `cross.py` shape). Bodies
# are VERBATIM copies of the host originals; every non-stdlib, non-moved free name is a keyword-only
# inject the host residue supplies from ITS live globals at call time (`cli._debt_echo_inject`), so `-C`
# rebinds and `monkeypatch.setattr(yitc, ...)` stay honoured, and a moved sibling (`_debt_echo_lines`
# inside the land-tail wrapper) is reached through its host residue, never module-locally, so the same
# patch surface covers every call. The two positional collaborators of `_debt_echo_lines` default to
# `None` HERE because their originals name host stayers (`_plan_census_view` / `_concurrent_session_view`)
# — the host residue keeps the ORIGINAL signature and passes them through, so the object bound is the
# same host object as before the move (lessons/library-extraction.md §A default that NAMES a host symbol).
# `INJECTS` below is the per-mover roster the residues iterate — generated with `symtable` over each
# body's scope subtree.
# ---------------------------------------------------------------------------------------------
# ── T-12789 (SPEC-0093 rule 29 / SPEC-0076 §6c / SPEC-0119 rule 43): the UNCOVERED USER SURFACE ──
#
# A project DECLARES its user surfaces as path prefixes (`ui.surfaces:` in yitc-ops.yaml, OPT-IN —
# absent = no signal, never a guess). A surface FILE is covered when ANY non-retired scenario's
# `covers` names it (whole-file or `file#symbol`, the file is what counts). Test-shaped paths are
# never a surface. ONE home for the whole derivation: the Analysis line (cli
# `_print_uncovered_surface_warn`) and the debt row below both read it. Derived each time from the
# carrier + the graph index + git — no store, no event, no gate. Precision measured before shipping:
# dev-utilities/uncovered-surface-precision-T-12788.md (strict FP 0.200 <project> / 0.144 <project>).
_SURFACE_TEST_DIRS = frozenset({"tests", "test", "__tests__"})
_SURFACE_TEST_BASENAME_RE = re.compile(
    r"^(?:test_.*|.*_test\.[^.]+|.*\.test\.[^.]+|.*\.spec\.[^.]+|.*_spec\.[^.]+)$")


def _surface_is_test_path(path: str) -> bool:
    parts = PurePosixPath(str(path or "")).parts
    if not parts:
        return False
    return (any(seg in _SURFACE_TEST_DIRS for seg in parts[:-1])
            or bool(_SURFACE_TEST_BASENAME_RE.match(parts[-1])))


def user_surface_prefixes(ops) -> list:
    """The DECLARED `ui.surfaces:` prefixes (SPEC-0093 rule 29), normalized to end in `/`. Anything
    malformed or absent answers [] — no declaration means no signal."""
    if not isinstance(ops, dict):
        return []
    ui = ops.get("ui")
    raw = ui.get("surfaces") if isinstance(ui, dict) else None
    if not isinstance(raw, list):
        return []
    out = []
    for e in raw:
        e = str(e or "").strip()
        while e.startswith("./"):
            e = e[2:]
        if e and not e.startswith("/") and ".." not in PurePosixPath(e).parts:
            out.append(e if e.endswith("/") else e + "/")
    return sorted(set(out))


def scenario_covered_files(index) -> set:
    """Every FILE a non-retired scenario's `covers` names (a `file#symbol` anchor counts its file)."""
    out: set = set()
    for node in ((index or {}).get("scenarios") or {}).values():
        node = node or {}
        if str(node.get("status") or "") == "retired":
            continue
        for a in node.get("covers") or []:
            f = str(a).split("#", 1)[0].strip()
            if f:
                out.add(f)
    return out


def uncovered_surface_files(paths, prefixes, index) -> dict:
    """{prefix: [path, ...]} — the non-test `paths` under a declared prefix that no scenario covers.
    Pure; [] prefixes → {} (the no-declaration silence)."""
    if not prefixes:
        return {}
    covered = scenario_covered_files(index)
    out: dict = {}
    for p in sorted({str(x) for x in (paths or []) if x}):
        if p in covered or _surface_is_test_path(p):
            continue
        for pre in prefixes:
            if p.startswith(pre):
                out.setdefault(pre, []).append(p)
                break
    return out


def uncovered_surface_debt_lines(REPO_ROOT, _read_yaml) -> list:
    """SPEC-0119 rule 43: ONE report-only row `user-surface files no scenario covers: N`, over every
    TRACKED file under the declared prefixes. Suppressed-when-clean, and silent without a declaration
    (the engine itself declares none). Best-effort: [] on any failure — a seam is never broken."""
    from lib import git_env as _git_env  # T-13587 — the git child env policy (SPEC-0188 rule 7)
    try:
        from lib import profile as _profile
        prefixes = user_surface_prefixes(_profile._load_ops(Path(REPO_ROOT)))
        if not prefixes:
            return []
        gp = Path(REPO_ROOT) / "graph" / "index.json"
        index = _read_yaml(gp) if gp.exists() else {}
        import subprocess
        r = subprocess.run(["git", "-C", str(REPO_ROOT), "ls-files", "--", *prefixes],
                           capture_output=True, text=True, timeout=30, env=_git_env._git_child_env())
        if r.returncode != 0:
            return []
        hits = uncovered_surface_files(r.stdout.splitlines(), prefixes, index)
        n = sum(len(v) for v in hits.values())
        if not n:
            return []
        per = ", ".join(f"{k} {len(v)}" for k, v in sorted(hits.items()))
        return [f"debt: user-surface files no scenario covers: {n} ({per}) — author one "
                f"(`bin/yitc-v2 scenario new`) or bind it in an existing scenario's `covers:` "
                f"(report-only, SPEC-0119 rule 43 / SPEC-0093 rule 29)"]
    except Exception:                              # noqa: BLE001 — a debt row never breaks a seam
        return []


INJECTS = {
    "_debt_echo_lines": ('DISPATCH_WAVE_WINDOW_SEC', 'ENGINE_ROOT', 'EVENTS_PATH', 'READ_ONLY_ROOT', 'REPO_ROOT', '_abort_cause_breadth_view', '_ahead_branch_view', '_behind_branch_view', '_born_permissive_concerns_for_echo', '_branch_attempt_burn_view', '_carried_session_refs', '_dead_land_view', '_debt_followup_floor', '_debt_prequeue_refusal_window_days', '_debt_security_finding_floor_days', '_debt_test_class_stale_floor_days', '_dispatch_events_memo', '_gap_ops_carrier', '_gap_register_view', '_is_consumer_build', '_load_sensitive_uncarded_view', '_open_followup_counts', '_profile_gap_autofile', '_profile_resolution', '_profile_snapshot_record', '_project_growth_reading', '_read_yaml', '_reads_exemptions', '_recorded_measurement_view', '_review_due_view', '_self_project_aliases', '_uncarried_p8_view', '_unmonitored_dispatch_view', '_unpickable_ready_view', '_unresolved_halt_view', '_view_not_adopted', '_view_overdue_recheck', '_worker_session_ref', 'audit', 'debt_mod', 'followup_mod', 'init_mod', 'journal_mod', 'profile_mod', 'session', 'views', 'worktree_mod'),
    "_debt_echo_compact": ('_cli_invocation_form', 'debt_mod'),
}


# ── T-13139 — the debt seam's ONE-PASS declaration ─────────────────────────────────────────────────
#
# WHAT THE COMPOSED VIEWS READ, declared once at the wiring site (SPEC-0190 rule 10) and DERIVED from
# each reader's own type constant, so a reader and this declaration cannot name different rows. A view
# whose request this does not cover is still answered (one bounded walk) and is RECORDED on the
# scope's `fallbacks` — the regression that pins this seam fails on it (T-13139 AC2).
DEBT_ECHO_WINDOW_MARGIN_SEC = 3600   # past the dispatch wave window: the per-task retry reaches here


def debt_echo_scan(*, window_sec, followup_mod, views, profile_mod, journal_mod, session_refs=()) -> dict:
    """The keyword arguments of `journal.scan_scope` for the debt echo (see the block above).

    `session_refs` are the session refs this process CARRIES. A view that resolves the session asks
    whether such a ref is anchored in this journal (`_ref_current_epoch_anchored`), and when the answer
    is not in the tail that question is a WHOLE-journal read — measured on the kernel under `-C` with a
    ref the target cannot back: 8.8 GB and climbing before it was killed. Its rows are exactly the lines
    carrying the ref, so the ref is a NEEDLE of this pass and the question is answered from it. Only a
    ref whose JSON spelling is itself is declared: an escaped one would not be found in the raw line."""
    import functools as _ft
    from lib import land_floors as _lf
    whole = set(OBLIGATION_CARRIER_EVENTS) | {
        OBLIGATION_CLOSING_EVENT, OBLIGATION_MISS_EVENT, _GATE_OVERRIDE_EVENT, *LATE_FINDING_READ_TYPES,
        ADMISSION_EVENT, EXECUTION_EVENT, QUEUE_JUMP_FIRED_EVENT, TAIL_WITHHELD_EVENT, GIT_MAINTENANCE_EVENT,
        PREQUEUE_REFUSAL_EVENT, KNOWN_BROKEN_CARRIER_EVENT, P8_WARN_EVENT, "nightly_run_completed",
        "task_closed", "commit_landed", "land_member_verdict", "triage_run_completed"}
    whole |= set(P8_ADOPTION_EVENT_TYPES) | set(debt_landing._ABORT_BREADTH_EVENTS)
    whole |= set(views.REVIEW_DUE_READ_TYPES) | set(views.NOT_ADOPTED_READ_TYPES)
    whole |= set(views.PROJECT_GROWTH_READ_TYPES) | set(GAP_FILED_READ_TYPES)
    whole |= set(profile_mod._LIVE_EVENT_TYPES) | set(profile_mod.PROFILE_SNAPSHOT_EVENT_TYPES)
    whole |= set(journal_mod.HALT_ATTRIBUTION_INPUT_TYPES)
    keep = {t: None for t in sorted(whole)}
    keep["cli_invoked"] = ("row", SEAM_READ_WINDOW_DAYS)      # seam_read_amplification's own window
    return {
        "keep": keep,
        "parsed": ("land_completed",),                         # ~14 readers + the dispatch halt union
        "window_sec": int(window_sec) + DEBT_ECHO_WINDOW_MARGIN_SEC,
        "reducers": {
            "followup": followup_mod.FoldReducer,
            "plan_slice": PlanSliceReducer,
            "spec0161_type_keys": debt_spec0161.TypeKeysReducer,
            "p8_evidence": debt_adoption.P8EvidenceReducer,
            # the wait heartbeats are ~336k rows over the whole history: fed its own window only
            "abort_rows": (_ft.partial(debt_landing.AbortRowsReducer, _parse_stamped_deadline),
                           ("segment", ABORT_COST_WINDOW_DAYS)),
        },
        "needles": tuple(_lf.FLOOR_PROBE_NEEDLES) + tuple(
            r for r in dict.fromkeys(session_refs) if r and json.dumps(r)[1:-1] == r),
        # T-13309 — SPEC-0190 rule 4 class 3: every whole-history reader above is answered THROUGH the
        # index (T-13356): an archived segment whose summary covers this declaration — its keep rows,
        # the five reducers' states, the needles (captured, or a session ref proven absent) — is never
        # opened; any other is folded in this same walk and its summary built from that fold.
        "index": True,
    }


def _settled(view):
    """Evaluate `view` NOW and return a zero-arg callable that answers what it answered — its result,
    or the exception it raised, re-raised at the call — so a caller can move WHEN a pure view runs
    without moving what its consumer sees."""
    try:
        got = view()
    except Exception as exc:              # noqa: BLE001 — replayed verbatim at the consumer's call
        def _replay():
            raise exc
        return _replay
    return lambda: got


def _release_after(view, memo, *names):
    """Run `view`, then release `memo`'s stored reads (`DispatchEventsMemo.release`, or the scope's
    reducers `names` — `JournalScan.release`) — the debt seam's lifetime bound on what only that view
    reads. `memo` is whatever the seam's `with` yielded; one without `release` (an outer scope's, or a
    test double) is left alone."""
    try:
        return view()
    finally:
        getattr(memo, "release", lambda *_: None)(*names)


def scope_fold_entry(paths, _segment_lines):
    """`followup.fold_provider`'s answer inside the debt seam: the memo entry of the scope's one-pass
    `FoldReducer` for the ONE declared journal read through the segment-aware reader — or None, so
    any other fold key (an instance pair, a quarantine sink, another reader) folds exactly as before."""
    if len(paths) != 1 or not paths[0] or _segment_lines is not journal.segment_fold_lines:
        return None
    reducer = journal.scope_reducer(paths[0], "followup")
    return reducer.result() if reducer is not None else None


def _consumer_carrier_posture(is_consumer, repo_root) -> bool:
    """T-13525 (SPEC-0186 rule 6): is THIS root's `yitc-ops.yaml` to be judged as a CONSUMER ops
    contract? False on the engine's own checkout, whose root file is the kernel's verify-policy
    declaration and nothing else — so the sweeps that judge a repository AS a consumer of the
    contract are withheld BY IDENTITY, never by whether the file exists.

    The identity is the canonical one (`_is_consumer_build`, T-0952 — an engine linked worktree is
    the engine), read consistently with the documented `YITC_REPO_ROOT` override it honours at
    import: a root that override names IS the engine, also when a harness rebinds the root
    in-process after import (the same call-time read `own_journal_path` makes). A failing predicate
    answers True — the sweeps run, as before this rule existed."""
    try:
        if not is_consumer():
            return False
        override = os.environ.get("YITC_REPO_ROOT")
        return not (override and Path(override).resolve() == Path(repo_root).resolve())
    except Exception:
        return True


def _seam_audience(is_consumer) -> dict:
    """T-13395: the `audience: consumer` stamp merged onto the seam fold under `-C`; a failing
    predicate yields no stamp (the engine rendering — fail to today)."""
    try:
        return {"audience": "consumer"} if is_consumer() else {}
    except Exception:
        return {}


def _debt_echo_lines(_plan_census=None, _concurrent=None, *, DISPATCH_WAVE_WINDOW_SEC, ENGINE_ROOT, EVENTS_PATH, READ_ONLY_ROOT, REPO_ROOT, _abort_cause_breadth_view, _ahead_branch_view, _behind_branch_view, _born_permissive_concerns_for_echo, _branch_attempt_burn_view, _carried_session_refs, _dead_land_view, _debt_followup_floor, _debt_prequeue_refusal_window_days, _debt_security_finding_floor_days, _debt_test_class_stale_floor_days, _dispatch_events_memo, _gap_ops_carrier, _gap_register_view, _is_consumer_build, _load_sensitive_uncarded_view, _open_followup_counts, _profile_gap_autofile, _profile_resolution, _profile_snapshot_record, _project_growth_reading, _read_yaml, _reads_exemptions, _recorded_measurement_view, _review_due_view, _self_project_aliases, _uncarried_p8_view, _unmonitored_dispatch_view, _unpickable_ready_view, _unresolved_halt_view, _view_not_adopted, _view_overdue_recheck, _worker_session_ref, audit, debt_mod, followup_mod, init_mod, journal_mod, profile_mod, session, views, worktree_mod) -> list:
    """SPEC-0119 / T-9754: the SHARED proactive-debt echo — the 3 DERIVED debt counts (not-adopted /
    open-followups / overdue-rechecks) rendered as REPORT-ONLY lines, SUPPRESSED-WHEN-CLEAN (an empty
    list when clean). Injects the 3 existing view collaborators into the leaf `views._render_debt_echo`,
    plus the open-followups floor (`_debt_followup_floor`, T-9789). BEST-EFFORT: any failure returns []
    so a seam verb — session-start / `land` — is NEVER broken by the informational surface (the SPEC-0115
    `_context_seam_tail_line` precedent).

    `_plan_census` (T-11212, SPEC-0119 rule 21) is the ONE collaborator a CALLER may withhold: passing
    `None` means the census is NOT INJECTED for that seam, so the leaf never computes or renders it.
    It defaults to the fold, so the session-start seam and the on-demand `debt` re-fold keep it with
    no change. (Its withholding caller was the land-tail wrapper, retired with the land-tail seam by
    T-13142 — SPEC-0119 rule 2(b).)

    T-11453 installs the request-scoped memos here (T-11438 the second, T-12031 the third) — see
    the comment at the `with` below."""
    # T-11453 — THE REQUEST-SCOPED MEMOS, installed HERE, at the ONE shared residue,
    # which is what buys all three debt seams (session-start / land-tail / the `debt` re-fold)
    # from a single wiring site — the same property every collaborator below relies on, and the
    # reason this card needed no new seam of its own:
    #   `journal_mod.rows_memo([EVENTS_PATH])` collapses the ~15 INDEPENDENT folds of the LOCAL
    #     journal (12 readers in debt.py, `_iter_events` behind the not-adopted view, the
    #     review-due lens, and the followup fold) onto ONE parse. It DECLARES that single path
    #     deliberately: `_dispatch_status_events` reads a union of up to 17 journals and
    #     memoizing those would retain ~20 GB, so every other path falls straight through to its
    #     existing bounded/prescanned read.
    #   `_dispatch_events_memo()` (T-11438) collapses this fold's TWO dispatch-union reads — the
    #     rule-18 halt set (6 types) and rule 23's `land_completed` alone, a strict SUBSET of it.
    #   `followup_mod.fold_memo()` (T-12031) collapses this fold's TWO `followup._fold` calls —
    #     `_open_followup_counts` and, through `_uncarried_p8_view`, `debt.p8_carrier_followups`.
    #     It is a RESULT memo, not a read one, because `_fold` is defined over RAW LINES (it dedupes
    #     by line identity for the SPEC-0168 instance pair) and so cannot consume the `rows_memo`
    #     parsed-rows lane above: it re-parsed the whole memo-served journal on each call, which was
    #     T-12029's entire measured residual — 1,192,248 of 1,822,540 `json.loads`, exactly 2x the
    #     596,129-row logical journal, at every session start and every land tail.
    # Measured before, on a 176 MB / 394,242-line journal (2026-08-22): 17 opens, 529 MB read,
    # 49.0s / 51.2s / 74.4s per invocation — paid at EVERY session start and EVERY land tail.
    # After: 1 open of the local journal, 32.6s. Both scopes are plain pass-throughs outside
    # themselves, nothing survives them, and no answer moves — each is a memo of its OWN
    # reader's result, never a second reader (CHARTER §P5).
    #
    # The body below is INDENTED under this `with` rather than extracted into a wrapper: this
    # name is a contract surface six tripwires read by `inspect.getsource` / AST to prove the
    # one-wiring-site rule, and moving the collaborators out from under it would break all six
    # to save a whitespace diff (`git diff -w` shows this change as the two lines it is).
    #
    # T-13139 (X-1687) — `rows_memo([EVENTS_PATH])` IS REPLACED by the ONE-PASS ReadScope
    # (`journal_mod.scan_scope`): the memo held every segment's lines AND parsed rows — 4.2 GiB on
    # the kernel checkout — to give the seam one fold per segment. The scope keeps that bound and
    # holds only what the composed views DECLARE (`debt_echo_scan` — typed projections, the dispatch
    # window, the all-types reducers, the probe needles). `fold_memo` stays as the followup fold's
    # delivery contract; `fold_provider` answers its miss from the scope's `FoldReducer`, so every
    # `_fold` caller copies out of the one pass.
    with journal_mod.scan_scope(EVENTS_PATH, **debt_echo_scan(
            window_sec=DISPATCH_WAVE_WINDOW_SEC, followup_mod=followup_mod, views=views,
            profile_mod=profile_mod, journal_mod=journal_mod,
            session_refs=_carried_session_refs())) as _scope, \
            _dispatch_events_memo() as _dispatch_memo, followup_mod.fold_memo(), \
            followup_mod.fold_provider(scope_fold_entry):
        # T-13265: bound BEFORE the best-effort try — when a view inside it raises (e.g. on a
        # malformed task card) the writers after the render must SKIP, not crash `session start`
        # with an UnboundLocalError that leaves no seed receipt.
        _gap_reg = _gap_carrier = _gap_profile = None
        # T-13525 (SPEC-0186 rule 6): resolved ONCE for this seam. On the engine's own checkout the
        # four folds that judge THIS repo as a consumer of the ops contract are withheld — the
        # concern-conformance view, the unratified-adoption view, the gap register (and so its
        # writer) and the born-skew append. The first two walk the concern registry the moment a
        # carrier exists, so left running they do not merely print: an engine checkout without a
        # built registry dies on them. No other collaborator is guarded: each reads a section the
        # engine does not declare.
        _posture = _consumer_carrier_posture(_is_consumer_build, REPO_ROOT)
        try:
            # ONE fold (SPEC-0095) → the 3 open-followup counts, injected as 3 collaborators. The armed pair
            # is OPTIONAL in the leaf, so this is the only site that has to know about the T-10309 split.
            # T-13139 — the dispatch view FIRST, settled (its result replayed at its render slot): its
            # 24h all-types window is the seam's largest transient, and run here, what it frees is
            # reused by every later view instead of stacking on top of them (measured on the kernel
            # checkout: the whole verb's peak sat inside this view, ~79 MB over what preceded it).
            _ud = (None if _worker_session_ref() else
                   _settled(lambda: _release_after(_unmonitored_dispatch_view, _dispatch_memo)))
            # T-13139 — rule 28's view is a PURE read (the spec corpus, the `bin/` text, the scope's
            # type -> keys reducer) whose one large transient — the concatenated `bin/` text, ~67 MB as
            # ONE string — depends on no other view. Settled HERE, right after the dispatch view and
            # before the followup fold and the render's reads build up, and handed to the render as its
            # answer (or its exception, re-raised at the same call), it no longer stacks on top of them
            # (measured on the kernel checkout: the peak sat inside this view, ~62 MB over the followup
            # fold's retained state). Same inputs, same answer, still one evaluation.
            _rm = _settled(_recorded_measurement_view)
            _fu = _open_followup_counts()
            # T-12085 — resolved ONCE per seam and shared by the two profile-derived collaborators
            # below (the T-12080 readout line and the rule-39 gap register). Two resolutions of one
            # checkout are byte-identical (SPEC-0198 VP2), so this buys no correctness — it buys the
            # guarantee that both lines speak for the SAME resolution, and one tree walk instead of
            # two at every session start and every land tail.
            # ONE carrier read for this WHOLE seam — read FIRST, then threaded into every
            # consumer below (the resolution, the fold, and the writer after the render). The
            # order is the fix: while the resolution was taken first it opened `yitc-ops.yaml`
            # itself, so the seam paid two reads however carefully the helpers under it shared one.
            _gap_carrier = _gap_ops_carrier()
            _gap_profile = _profile_resolution(carrier=_gap_carrier)
            # T-12085 — the register is folded ONCE here, then both READ (the capped line below)
            # and WRITTEN FROM (the auto-file after the render). Folding it twice would let the
            # line and the filing disagree about what was unmet at this instant.
            _gap_reg = (_gap_register_view(_gap_profile, carrier=_gap_carrier) if _posture
                        else debt_mod.profile_gap_register(resolution=None, ops_path=None))
            lines = views._render_debt_echo(
                _view_not_adopted=lambda: _view_not_adopted(EVENTS_PATH),
                _view_overdue_recheck=_view_overdue_recheck,
                _open_followup_count=lambda: _fu.get("actionable"),
                _armed_fired_count=lambda: _fu.get("armed_fired"),
                _armed_waiting_count=lambda: _fu.get("armed_waiting"),
                followup_floor=_debt_followup_floor(),
                # T-10030 (SPEC-0119 rule 8 / SPEC-0128 Rule 2): the concern-conformance view over THIS repo's
                # ops carrier. No carrier → count 0 → suppressed; the engine kernel itself is not judged
                # at all (T-13525 — withheld by identity, SPEC-0186 rule 6).
                _concern_conformance=((lambda: init_mod.concern_conformance(REPO_ROOT / "yitc-ops.yaml"))
                                      if _posture else None),
                # T-10480 (SPEC-0125 VP1/VP2): the vendor-adapter conformance view over THIS repo's
                # adapter→neutral-home chain. Injecting it HERE — the one shared host residue — is what
                # gives a CONSUMER the per-repo `-C` surface for the check on all three debt seams at once
                # (`-C` session-start / land-tail / the on-demand `-C <repo> debt` re-fold), with NO new
                # verb: the same one-wiring-site-buys-every-seam discipline as `_security_findings` above.
                # The engine kernel itself has no consumer adapter → no-adapter → count 0 → suppressed.
                _adapter_conformance=lambda: init_mod.adapter_conformance(REPO_ROOT),
                # T-10508 (SPEC-0119 rule 13): the unratified-adoption view over THIS repo's ops carrier —
                # `adoption:` records still stamped `owner: init` (the birth sentinel) over a section the
                # carrier DECLARES. The T-10493 stance sweep passes them BY DESIGN (variant A leaves a
                # truthful-but-unreviewed record as DEBT rather than fail-closing honest consumers), so this
                # line is the residual's ONE reading moment. Wired at the same shared residue as its stance
                # siblings above → all three debt seams from one site. No carrier → 0 → suppressed; the engine
                # kernel itself is not judged at all (T-13525 — withheld by identity, SPEC-0186 rule 6).
                _unratified_adoptions=((lambda: init_mod.unratified_adoptions(REPO_ROOT / "yitc-ops.yaml"))
                                       if _posture else None),
                # T-10134 (SPEC-0119 / SPEC-0057 §9): the activity-gated review-due semaphore — surfaced
                # only when a periodic review is past cadence AND work happened since (no work → no nag).
                _review_due=_review_due_view,
                # T-10296 (SPEC-0149): the post-deploy proof-obligation fold — deploys whose STAMPED
                # window passed with no discharging recheck. Derived from the journal alone, zero stored
                # state; a repo with no window-carrying deploy (the engine kernel itself) folds to 0 →
                # suppressed.
                _proof_obligations=lambda: debt_mod.open_proof_obligations(EVENTS_PATH),
                # T-11663 (SPEC-0184 rule 9): the queue-jump FIRING fold — marks that actually
                # reordered land admission. Wired at the SAME shared residue as its siblings, so one
                # site buys all three debt seams (session-start / land-tail / the on-demand re-fold).
                # A repo where nobody has ever jumped the queue folds to 0 → suppressed.
                _queue_jump_firings=lambda: debt_mod.queue_jump_firings(EVENTS_PATH),
                # T-13290: the git-maintenance starvation fold — trailing hourly windows without a full
                # collection. Same shared residue as its siblings; a repo with no maintenance rows
                # (every consumer) folds to 0 and stays silent.
                _git_maintenance_deferrals=lambda: debt_mod.git_maintenance_deferrals(EVENTS_PATH),
                # T-12420 (SPEC-0119 rule 42 / SPEC-0188 rule 7): the WITHHELD post-ff tail-write
                # fold. Wired at this ONE shared residue like every sibling, so one site buys all
                # three debt seams (session-start / land-tail / the on-demand `debt` re-fold) with
                # no new seam or store. A repo where no tail write was ever withheld — every repo
                # today — folds to 0 and stays silent.
                _tail_writes_withheld=lambda: debt_mod.land_tail_writes_withheld(EVENTS_PATH),
                # T-12360 (SPEC-0132 §3 as extended): the DECLARED LOAD-SENSITIVE LANE's
                # sequential-tail reading — the carrier's file count and the sum of those files'
                # recorded durations, against the watch-point's two bounds. Wired at this ONE shared
                # residue like every sibling, which is what gives the weekly reviewer the numbers at
                # all three existing seams (session-start, the land tail, the on-demand `debt`
                # re-fold) with NO new seam, store or schedule — the reviewer never computes the
                # lane's wall by hand, which is why the watch-point had gone unread.
                # `root=REPO_ROOT` is the `-C`-rebound root (the T-12006 reading), so the fold reads
                # the carrier and table of the repo the CALLER POINTED AT. A repo with an empty
                # carrier — the engine's own state today — folds to 0 and stays silent.
                _load_sensitive_lane=lambda: debt_mod.load_sensitive_lane(root=REPO_ROOT),
                # T-11969 (SPEC-0189): the RESTORATION-PROPOSAL fold — the concerns born PERMISSIVE
                # whose NAMED detector has fired, rendered as a proposal naming the project, the
                # surface and the observed signal. Wired at this ONE shared residue like every sibling,
                # which is what gives it all three of the echo's existing seams (session-start,
                # land-tail, the on-demand `bin/yitc-v2 debt` re-fold) with NO new seam, store or
                # schedule of its own — exactly what the card's scope requires. The detector registry
                # ships EMPTY (each detector is inseparable from the default-flip it guards and rides
                # that card), so today this folds to 0 proposals in every repo and stays silent; the
                # rendering path exists BEFORE any default relaxes, which is the plan's build order.
                # The growth reading is taken here and passed IN as a reading; the rule claim for that
                # behaviour lives on the helper symbols this card anchors, NOT on this shared wiring
                # (owner decision 2026-09-02, option 2: a shared host symbol already anchored by other
                # specs is REGISTERED INTO, never claimed).
                # T-12006 (SPEC-0189 rules 3+5): `root=REPO_ROOT` is what makes the fold read the
                # repo the CALLER POINTED AT rather than the one the process happens to stand in.
                # `REPO_ROOT` is the `-C`-rebound root, and the assembler hands it to every detector
                # that accepts a `root=` keyword. Without it each detector resolved its own input
                # through `own_journal_path()`'s cwd walk, so `<engine>/bin/yitc-v2 -C <consumer> debt`
                # run from the ENGINE cwd folded the ENGINE's journal and printed nothing, while the
                # same command run from the consumer cwd printed a real proposal (measured on <project>,
                # 2026-09-03). One added keyword at this ONE site therefore fixes all three debt seams.
                _restoration_proposals=lambda: debt_mod.restoration_proposals(
                    project=REPO_ROOT.name,
                    concerns=_born_permissive_concerns_for_echo(),
                    growth=_project_growth_reading(),
                    root=REPO_ROOT,
                    # T-13062 (SPEC-0189 rule 9): the owner dispositions are read out of the SAME
                    # carrier this seam already parsed once (`_gap_carrier`, T-12085).
                    contract=_gap_carrier),
                # T-12080 (SPEC-0198 rules 3+5): the project growth PROFILE line — snapshot hash
                # + the lens set the profile activates. Wired at this ONE shared residue like every
                # sibling above, which is precisely what SPEC-0198 rule 5 requires: resolution runs
                # only inside verbs that are ALREADY RUNNING, and this residue IS all three of them
                # (session start, the land tail, the on-demand `debt` re-fold). One site, three
                # seams, no new surface.
                #
                # IT IS INSIDE THE `with` FOR THE SAME REASON ITS SIBLINGS ARE. `_iter_events()` here
                # is served by the residue's `journal_mod.rows_memo` scope, so the profile costs NO
                # second parse of the journal — it reuses the one every other collaborator already
                # shares (T-11453). That request-scoped ReadScope is the answer to SPEC-0190 rule 10:
                # the resolver carries NO cache of its own, and none is needed, because the seam that
                # composes it already owns the scope. A per-view cache here would be the mechanism
                # rule 10 forbids.
                #
                # `root=REPO_ROOT` is the `-C`-rebound root (the T-12006 lesson one line above): it
                # is what makes `<engine>/bin/yitc-v2 -C <consumer> debt` resolve the CONSUMER's
                # profile rather than the checkout the process happens to stand in.
                _profile_line=lambda: profile_mod.echo_line(_gap_profile),
                # T-12085 (SPEC-0119 rule 39 / SPEC-0198 rules 5+7): the BROWNFIELD GAP REGISTER —
                # the profile-required baseline items this project's own ops carrier does not
                # answer, rendered as ONE capped summary line. Wired at this ONE shared residue like
                # every sibling above, which is exactly what SPEC-0198 rule 5 requires: resolution
                # runs only inside verbs that are ALREADY RUNNING, and this residue IS all three of
                # them (session start, the land tail, the on-demand `debt` re-fold). One site,
                # three seams, no new surface.
                #
                # IT SHARES THE PROFILE THE LINE ABOVE RENDERS. `_gap_profile` is resolved ONCE, just
                # above this call, and handed to both collaborators — so the two cannot disagree
                # about which profile they are speaking for, and the resolution is not paid twice.
                # Inside the `with`, so it rides the residue's `journal_mod.rows_memo` scope and
                # costs no second parse: the SPEC-0190 rule 10 answer is that ONE request-scoped
                # ReadScope, never a cache of its own.
                _gap_register=lambda: _gap_reg,
                # T-11468 (SPEC-0119 rule 29 / SPEC-0181 §Known-broken-on-main): the known-broken-on-main
                # fold — tests a land's attribution probe REPRODUCED at the merge-base, still unproven
                # to pass there. Derived from `land_completed.failure_attribution` alone, zero stored
                # state and no window; a repo whose lands have never recorded an attribution (or whose
                # main is healthy) folds to 0 → suppressed. Wired at this ONE shared residue, which is
                # what gives it all three debt seams — session-start, land-tail, and the on-demand
                # `bin/yitc-v2 debt` re-fold — with no new verb and no new seam of its own.
                _known_broken=lambda: debt_mod.open_known_broken(EVENTS_PATH, root=REPO_ROOT),
                # T-11799 (SPEC-0119 rule 33 / SPEC-0181): the PRE-QUEUE REFUSAL fold — lands the
                # known-broken guard refused above the land queue, read back off the additive
                # `land_completed.prequeue_known_broken` key the refusal itself writes (one oracle,
                # re-derived nowhere). Its SIBLING is the rule-29 line one wiring up: that one says
                # what is broken on main, this one says what that cost and who was stopped. Wired at
                # this ONE shared residue like every sibling, so it reaches all three debt seams —
                # session-start, land-tail and the on-demand `bin/yitc-v2 debt` re-fold — with no new
                # store, no new event and no new verb. A repo whose main has not frozen anyone in the
                # window folds to 0 → suppressed.
                _prequeue_known_broken_refusals=lambda: debt_mod.prequeue_known_broken_refusals(
                    EVENTS_PATH, window_days=_debt_prequeue_refusal_window_days()),
                # T-12037 (SPEC-0119 rule 37 / SPEC-0190 rule 10): the SEAM-READ-AMPLIFICATION fold —
                # which verb physically read MORE of the corpus than the corpus it composed, read
                # back off the T-12034 `cli_invoked.reads` counters that until now nothing rendered.
                # Wired at this ONE shared residue like every sibling, so it reaches all three debt
                # seams — session-start, land-tail and the on-demand `bin/yitc-v2 debt` re-fold — with
                # no new store, no new event and no new verb.
                #
                # AND IT IS WIRED HERE FOR A SECOND REASON THE SIBLINGS DO NOT HAVE: this residue is
                # the very ReadScope whose bound the view reports on. Folding it INSIDE the scope is
                # what makes the amplification reporter incapable of being a source of amplification
                # — it reads through `journal.segment_rows` and the memoised `state.load_path`, both
                # served by the memos installed at the `with` above, so it costs no physical read.
                # `root` is passed because the instance-fix join resolves closed cards BY ID under it;
                # `exemptions` is this repo's own declared set (absent carrier ⇒ none, fail-closed).
                # T-13395 (GitHub #5): every seam that fold measures is an ENGINE verb, so under `-C`
                # the fold is stamped `audience: consumer` and the line is rendered as the kernel's
                # cost — no BLOCKING verdict, no wiring-site remedy the consumer cannot apply. The
                # canonical consumer test (T-0952), not a bare REPO_ROOT != ENGINE_ROOT, so an engine
                # linked worktree keeps the kernel rendering.
                _seam_read_amplification=lambda: debt_mod.seam_read_amplification(
                    EVENTS_PATH, root=REPO_ROOT, exemptions=_reads_exemptions())
                | _seam_audience(_is_consumer_build),
                # T-12078 (SPEC-0119 rule 38 / SPEC-0105): the NIGHTLY'S READER — what the last
                # `nightly_run_completed` row said that the night before it did not, per project and
                # per check, with the two chronic conditions split into dated lines naming a remedy.
                # Wired at this ONE shared residue like every sibling, so it reaches all three debt
                # seams — session-start, land-tail and the on-demand `bin/yitc-v2 debt` re-fold —
                # with no new store, no new event type, no new verb and no new seam of its own.
                #
                # AND INSIDE THE SCOPE, for the rule-37 reason one wiring up: the fold reads through
                # `journal.segment_rows`, which the `rows_memo` at the `with` above already serves,
                # so the reader of a fleet-wide nightly costs no physical read of its own (SPEC-0190
                # rule 10 — ONE request-scoped ReadScope at the wiring site, never a per-view cache).
                # A repo whose journal holds fewer than two nightly rows folds to nothing → silent.
                _nightly_verdict_changes=lambda: debt_mod.nightly_verdict_changes(EVENTS_PATH),
                # T-11486 (SPEC-0119 rule 30 / SPEC-0181): the rolled-back-selection fold — has the
                # auto-rollback taken governing affected-test selection OFF? The GOVERNOR ITSELF is
                # injected, so the fold counts nothing of its own and this view can never disagree with
                # the rule that decides what runs (the same borrowed-oracle discipline as the rule-26
                # abort-cause identity two blocks below). Wired at this ONE shared residue like every
                # sibling → all three debt seams with no new store, no new event and no new verb; a repo
                # whose selection governs folds to `rolled_back: False` → suppressed.
                _selection_rollback=lambda: debt_mod.selection_rollback(
                    EVENTS_PATH, _governs=worktree_mod._selection_governs),
                # T-11563 (SPEC-0119 rule 31): the UNCARRIED-P8-WARN fold — `class: infra`
                # closures whose CHARTER §P8 adoption WARN fired and which nothing is holding. The
                # WARN is non-blocking BY DESIGN (E-0005), which is exactly how two of them slipped
                # through in two days (T-11442, T-11473) with no followup, no post-ship observation
                # and no armed waiter; this is the reading moment that silence was missing. Wired at
                # this ONE shared residue like every sibling, so it reaches all three debt seams —
                # session-start, land-tail and the on-demand `debt` re-fold — with no new store, no
                # new event and no new verb. A repo whose infra closures carry their evidence folds
                # to 0 → suppressed.
                _uncarried_p8=lambda: _release_after(_uncarried_p8_view, _scope, "p8_evidence"),
                # T-10440 (SPEC-0119 rule 11 / X-0306 half 1): the sub-critical security-findings fold over
                # THIS repo's `.yitc/findings/` report series. Injecting it HERE — the one shared host
                # residue — is what buys all three debt seams (session-start / land-tail / `debt` re-fold)
                # from one wiring site, so they cannot drift apart. A repo that has never run a security
                # audit has no reports → count 0 → suppressed.
                _security_findings=lambda: debt_mod.open_subcritical_findings(
                    REPO_ROOT / ".yitc" / "findings", _debt_security_finding_floor_days()),
                # T-12982 (SPEC-0119 rule 44): declared security probes not yet vouched — the read-back
                # of the land floor's newly-declared admission, one wiring site for all three seams.
                _probes_awaiting_first_check=lambda: debt_mod.probes_awaiting_first_check(REPO_ROOT),
                # T-10502 (SPEC-0119 rule 14 / SPEC-0155 rule 7, X-0362/X-0363): the security-gate OVERRIDE
                # fold over THIS repo's journal — deploys that owner-overrode a REJECTING pre-deploy gate.
                # Wired at the same shared residue as its siblings → all three debt seams from one site. The
                # override is the one governed way past a fail-closed gate, so it MUST be read back: a repo
                # that never overrode it folds to 0 → suppressed.
                _security_gate_overrides=lambda: debt_mod.recent_gate_overrides(EVENTS_PATH),
                # T-12288 (SPEC-0204 rule 8 / SPEC-0119): the LATE-FINDINGS fold over THIS repo's
                # journal — defects the auditor raised at a pass >= 2 as `pre-existing-in-subject`.
                # Wired at the SAME shared residue as its siblings, so it rides all three debt seams
                # (session-start / land-tail / the `debt` re-fold) from ONE site and they cannot drift
                # apart. Report-only: rule 8 records the auditor's completeness and never gates on it
                # (owner ruling D8; T-12141 gated and measured worse). A repo whose audits surface
                # nothing late folds to 0 → suppressed.
                # T-13470: the closure half is the CLOSE GATE'S OWN judgement function, fed from the
                # fold's one declared read and joined to the card's status off this repo's cards — so
                # the line names a blocker only where an undecided finding sits on an open card.
                _late_findings=lambda: debt_mod.late_findings_per_pass(
                    EVENTS_PATH,
                    _card_status=lambda tid: _task_card_status(Path(REPO_ROOT) / "tasks", tid, _read_yaml),
                    _judge=lambda rows, tid: audit.undecided_late_findings(
                        rows, tid, repo_root=REPO_ROOT)),
                # T-11380 (SPEC-0119 rule 26): the land-abort CAUSE-BREADTH fold over THIS repo's journal —
                # ONE abort cause that has now refused several DIFFERENT branches inside the window. Every
                # existing surface for a repeating abort is per-branch or per-task, so a cause that fails
                # once on each of four branches trips none of them and each branch pays a full verify to
                # re-diagnose it. Wired at the same shared residue as its siblings → all three debt seams
                # from one site. A repo whose journal holds no such repeat folds to 0 → suppressed.
                _abort_cause_breadth=_abort_cause_breadth_view,
                # T-11821 (SPEC-0119 rule 34): the TRANSPOSE of the line above — ONE BRANCH burning
                # repeated UNLANDED land attempts, WHATEVER the cause each time. Every existing
                # surface is keyed on the REPETITION OF A CAUSE (the T-0655 backstop arms only on
                # consecutive aborts sharing a cause key, the ceiling counts audit passes per TASK,
                # re-run-vs-resolve is per SESSION, rule 27 groups BY CLASS), so a branch failing
                # for a different reason each time trips none of them — and a whole family of abort
                # classes carries NO cause identity at all, making its consecutive aborts
                # INCOMPARABLE rather than merely different, i.e. structurally un-armable. Measured
                # 2026-08-28: task/T-11810 five aborts / five classes / four identity-absent,
                # task/T-11733 seven with no two consecutive sharing a key. Wired at this SAME
                # shared residue as its rule-26 sibling so both transposes ride all three debt
                # seams from ONE site and cannot drift apart. Report-only: a cause-agnostic GATE was
                # externally rejected because it would confuse stuckness with legitimate iteration.
                # A repo whose branches land folds to 0 -> suppressed.
                _branch_attempt_burn=_branch_attempt_burn_view,
                # T-11396 (SPEC-0119 rule 28): the RECORDED-MEASUREMENT DRIFT fold — SPEC-0161's
                # recorded payload-key candidate set drifting toward the 0.80 floor its own land-verify
                # gate enforces. Wired at the same shared residue as its siblings → all three debt seams
                # (session-start / land-tail / `debt` re-fold) from one site. Report-only: it makes the
                # drift visible early enough that refreshing the record is a choice, instead of a hard
                # land refusal landing on whoever happens to be landing (measured 2026-08-21). A repo
                # with nothing governing folds to 0 → suppressed.
                _recorded_measurement=_rm,
                # T-10471 (SPEC-0119 rule 12 / X-0336): the unmonitored-dispatch fold — in-flight dispatches
                # with no journaled monitoring read. CONTROLLER-SEAM-ONLY: injected as None in a dispatched
                # WORKER session (`YITC_EXPECTED_SESSION_REF` set), where it contributes nothing. The
                # §Watcher obligation is the CONTROLLER's — a worker cannot arm a fleet watcher — and without
                # this gate a worker's land-tail would report its still-flying SIBLINGS (and, but for the
                # self-exclusion below, itself) as debt it can do nothing about. Same env-gated posture as
                # `_surface_concern_drift`'s consumer gate.
                # T-13139 — its 24 h all-types union is read by no later view, so the dispatch memo
                # is released after it too (the halt / dead-land reads that follow start their own).
                _unmonitored_dispatches=_ud,
                # T-10509 (SPEC-0156): the unproven-check fold — kernel-graded checks THIS repo DECLARES in
                # its yitc-ops.yaml carrier with no journaled RED demonstration of their current definition.
                # Injected at this ONE shared residue, so it rides all three debt seams (session-start /
                # land-tail / the `-C <repo> debt` re-fold) and they cannot drift apart — the rule-11 /
                # rule-12 wiring precedent. The engine kernel has no yitc-ops.yaml → declares no check →
                # count 0 → suppressed, so this never retro-charges history (the SPEC-0149 lesson).
                _unproven_checks=lambda: debt_mod.unproven_checks(
                    REPO_ROOT / "yitc-ops.yaml", EVENTS_PATH),
                # T-10513 (SPEC-0152 rule 24 / X-0375): the unexecuted-test-class fold — declared
                # `tests.classes` THIS repo carries with no recorded successful execution (never / stale). The
                # EXECUTION axis of the SPEC-0156 unproven-check line above, injected at this SAME shared residue
                # so it rides all three debt seams (session-start / land-tail / the `-C <repo> debt` re-fold) and
                # they cannot drift apart. The engine kernel has no yitc-ops.yaml → declares no class → count 0 →
                # suppressed, so history is never retro-charged (the SPEC-0149 lesson).
                _unexecuted_test_classes=lambda: debt_mod.unexecuted_test_classes(
                    REPO_ROOT / "yitc-ops.yaml", EVENTS_PATH, _debt_test_class_stale_floor_days()),
                # T-10575 (SPEC-0152 rule 16 subject_globs / SPEC-0119): the subject_globs rollout nudge — the
                # EXECUTABLE verify.layers THIS repo declares with no `subject_globs:` yet. NOT owed debt
                # (subject_globs is opt-in and fail-closed: absent → the layer always runs) — a rollout OPPORTUNITY
                # to trim land time via diff-relevant real skipping — a disjoint diff REMOVES the layer's run and its
                # prep at land, recording a {layer, outcome: skipped-disjoint-subject} row (T-10573). Injected at this SAME shared residue
                # so it rides all three debt seams (session-start / land-tail / the `-C <repo> debt` re-fold) and
                # they cannot drift apart — the rule-11 / rule-12 / rule-24 wiring precedent. The engine kernel has
                # no yitc-ops.yaml → declares no executable layer → count 0 → suppressed, never retro-charged.
                _undeclared_subject_layers=lambda: debt_mod.undeclared_subject_layers(
                    REPO_ROOT / "yitc-ops.yaml"),
                # T-11886 (SPEC-0119 rule 35 / SPEC-0152 rule 16 subject_globs, X-0860): the EXECUTION
                # axis of the two subject_globs lines around it — suite files inside a DECLARED subject
                # that no executable layer's execution registry names. Wired at this SAME shared residue
                # as its two siblings so all three ride the three debt seams (session-start / land-tail /
                # the `-C <repo> debt` re-fold) from ONE site and cannot drift apart. Bound to this
                # repo's carrier AND its checkout, because the question spans both (what is declared vs
                # what the commands name). The engine kernel has no yitc-ops.yaml → count 0 → suppressed,
                # so history is never retro-charged (the SPEC-0149 lesson).
                _unexecuted_subject_files=lambda: debt_mod.unexecuted_subject_files(
                    REPO_ROOT / "yitc-ops.yaml", REPO_ROOT),
                # T-11080 (SPEC-0119 / SPEC-0152 rule 16 subject_globs): the OBSERVED half of the line above —
                # the executable layers whose skip rate over the recent-lands window is 0%, read from the
                # per-layer `{layer, outcome}` rows `land` ALREADY writes onto land_completed (T-9719/T-10573).
                # No new event, no new store: a second reading of an existing payload. Wired at this SAME
                # shared residue as its carrier-read sibling so the two ride all three debt seams together
                # (session-start / land-tail / the `-C <repo> debt` re-fold) and cannot drift apart — the
                # rule-11 / rule-12 / rule-24 wiring precedent. A repo whose journal records no layered land
                # (the engine kernel itself) folds to 0 → suppressed, so history is never retro-charged.
                _zero_skip_layers=lambda: debt_mod.zero_skip_verify_layers(EVENTS_PATH),
                # T-11125 (SPEC-0119 rule 19): what CHANGED in the recorded slowest test files — a new
                # entrant into the slow tail, or a member that grew materially — read from the per-file
                # duration series T-11124 records on every successful land. No new event and no new store:
                # a second reading of an existing payload, exactly like `_zero_skip_layers` above. Wired at
                # this SAME shared residue so it rides all three debt seams from ONE site (session-start /
                # land-tail / the `debt` re-fold) and they cannot drift apart — the rule-11 / rule-12 /
                # rule-18 wiring precedent, and the reason this card needs no new seam of its own. It
                # reports the DELTA and never the level: a slowest set exists by definition, so printing
                # the set itself would print every land and train the reader to skip it. A journal whose
                # series is too short to have a previous state — the engine's own, freshly after T-11124 —
                # folds to 0 → suppressed, so a thin series is never over-read.
                _slowest_decile_changes=lambda: debt_mod.slowest_decile_changes(EVENTS_PATH),
                # T-11368 (SPEC-0119 rule 27, <project> X-1036 corrected by X-1039): what ABORTED lands
                # COST, split by abort_class, with the aborts that paid a FULL verify separated from those
                # that refused early. Wired at this SAME shared residue so it rides all three debt seams
                # from ONE site (session-start / land-tail / the `debt` re-fold) and they cannot drift
                # apart — the rule-11 / rule-12 / rule-18 / rule-19 wiring precedent, and the reason this
                # card needs no seam of its own. No new event and no new store: a THIRD reading of the
                # `land_completed` payload rules 19 and 23 already read, here narrowed to `status: abort`.
                # It is the only line in this echo whose subject is money ALREADY SPENT rather than work
                # still pending. A repo whose window holds no abort costing anything worth reporting —
                # the clean case, and the whole of a quiet week — folds to 0 → suppressed, so history is
                # never retro-charged and an instant-refusal-only journal is never over-read.
                _aborted_land_cost=lambda: debt_mod.aborted_land_cost(EVENTS_PATH),
                # T-10511 (SPEC-0119 rule 16 / SPEC-0093 rule 22, X-0370): the runtime-delivery coherence read —
                # the REVERSE of the not-adopted line this same echo prints. Injected at this ONE shared residue
                # so it rides all three debt seams (session-start / land-tail / the `-C <repo> debt` re-fold) and
                # they cannot drift apart. It is the only collaborator here that takes an ARGUMENT: the
                # not-adopted view the render helper ALREADY computed, so the forward and reverse readings of
                # that delta come from ONE derivation (no second git ancestry walk, no second live-revision
                # source — CHARTER §P5). The engine kernel has no yitc-ops.yaml and bind-mounts nothing → count
                # 0 → suppressed, so history is never retro-charged.
                _runtime_delivery=lambda _na: debt_mod.runtime_delivery_coherence(
                    REPO_ROOT / "yitc-ops.yaml", REPO_ROOT, _na),
                # T-10554 (SPEC-0119 rule 17 / SPEC-0093 rule 24, X-0419): the broken-outcome-invariant fold —
                # the standing PRODUCT-OUTCOME invariants THIS repo declares over its long-lived subsystems,
                # read as broken / degraded / unproven. Injected at this SAME shared residue so it rides all
                # three debt seams (session-start / land-tail / the `-C <repo> debt` re-fold) and they cannot
                # drift apart — the rule-11 / rule-12 / rule-16 wiring precedent. It is what retires the
                # owner-as-monitor role for a covered subsystem: adoption evidence is framed on the DIFF, so a
                # subsystem no card owns is otherwise unobservable (X-0419). The engine kernel has no
                # yitc-ops.yaml → declares no invariant → count 0 → suppressed, so history is never
                # retro-charged, and only the DECLARED set can interrupt.
                _broken_outcome_invariants=lambda: debt_mod.broken_outcome_invariants(
                    REPO_ROOT / "yitc-ops.yaml", EVENTS_PATH, REPO_ROOT),
                # T-11181 (SPEC-0119 rule 21): the NON-TERMINAL plan census — how many plans sit in
                # each non-terminal stage of the plan FSM, folded from the same `plans/*.md` frontmatter
                # `plan list` reads (no new store, no new parser, no cadence). Plans are the one tracked
                # work class NO seam surfaced: the picker reads `tasks/` ONLY, so a plan parked in
                # `postcheck` (the real-data soak) goes quiet indefinitely — this line is its one
                # reading moment. It SURFACES, it never picks: the AGENTS-PROTOCOL §Planning artifacts
                # carve-out keeps the picker reading `tasks/` only and take-into-work an owner cue. A
                # repo with no `plans/` folds to 0 → suppressed, so history is never retro-charged.
                # T-11212 (owner-surfaced): UNLIKE every sibling above, this ONE collaborator is
                # PARAMETERIZED, so the SESSION-START seam and the explicitly-invoked `debt` re-fold
                # get the default fold while a caller may pass None (the land-tail wrapper did, until
                # T-13142 retired that seam). Withholding the collaborator
                # (rather than injecting one taught to print nothing) is the rule: the detachment is what
                # a tripwire can honestly discriminate.
                _plan_census=_plan_census,
                # T-11868 (SPEC-0119 rule 36): the permanently-unpickable READY cards. Wired at this
                # SAME one shared residue as every sibling, so ONE site buys all three debt seams
                # (`-C` session-start / land-tail / the `debt` re-fold) and they cannot drift apart.
                # UNLIKE `_plan_census` above it is NOT parameterized: it is a `tasks/` fold, which
                # every seam incl. the land tail can honour.
                # T-12359 (SPEC-0119 rule 41): the DECLARED LOAD-SENSITIVE files no live card is
                # holding. Wired at this ONE shared residue like every sibling, so it reaches all
                # three debt seams — session-start, land-tail and the on-demand `bin/yitc-v2 debt`
                # re-fold — with no new store, no new event and no new verb. A repo whose carrier is
                # absent or fully carded folds to 0 → suppressed.
                _load_sensitive_uncarded=_load_sensitive_uncarded_view,
                _unpickable_ready=_unpickable_ready_view,
                # T-11211 (SPEC-0119 rule 22): the own-evidence uncited-pattern fold. Wired at this SAME one
                # shared residue as every sibling, so ONE site buys all three debt seams (`-C` session-start /
                # land-tail / the `debt` re-fold) and they cannot drift apart. TWO host-coupled inputs it
                # cannot resolve itself: ENGINE_ROOT/"patterns" is the KERNEL catalog — captured at import
                # BEFORE any `-C` rebind, so a consumer session reads the ENGINE's patterns, never its own
                # (which it has none of); and the identity is _cross_self() PLUS its aliases, never
                # REPO_ROOT.name — inside a task/work worktree that leaf is the TASK id (`T-11211`), and for
                # `<project>` at `.../<project>` the registry key and the basename genuinely differ
                # (X-0259). A repo whose patterns name it nowhere folds to 0 → suppressed.
                _own_evidence_patterns=lambda: debt_mod.unapplied_own_evidence_patterns(
                    ENGINE_ROOT / "patterns", REPO_ROOT, _self_project_aliases()),
                # T-10858 (SPEC-0119 rule 18): the unresolved-worker-halt fold — halts whose cause the
                # journal has not recorded as cleared. Wired at this SAME one shared residue as its rule-12
                # sibling above, so it rides all three debt seams (session-start / land-tail / the `debt`
                # re-fold) from ONE site and they cannot drift apart. UNLIKE rule 12 it is NOT gated to a
                # controller session: rule 12's gate exists because arming a watcher is a controller-only
                # remedy, whereas a stopped worker awaiting a terminal decision is debt every session should
                # see — and the originating incident (<project> 2026-08-09) is precisely that no surface
                # reported one. A repo whose journal records no halt folds to 0 → suppressed, so history is
                # never retro-charged, and a halt drops the moment its cause is recorded cleared.
                _unresolved_halts=_unresolved_halt_view,
                # T-11254 (SPEC-0119 rule 23 / <project> X-0976): the DEAD-LAND fold — a land that
                # committed its step-1 bookkeeping and then died before emitting ANY terminal row. Wired at
                # this SAME one shared residue as every sibling, so it rides all three debt seams
                # (session-start / land-tail / the `debt` re-fold) from ONE site and they cannot drift
                # apart. It rides ALL THREE deliberately — unlike the rule-21 census, the LAND TAIL is the
                # single most useful seam for it: the next land in the repo is exactly the moment a
                # stranded predecessor should be named, and it is a seam a dispatched worker reaches. NOT
                # controller-gated: the remedy (`worktree recover-land`) is available to any session. A repo
                # whose every started land left a terminal row folds to 0 → suppressed, so history is never
                # retro-charged, and a row drops the moment a terminal row lands for that branch.
                _dead_lands=_dead_land_view,
                # T-11303 (SPEC-0119 rule 24 / <project> X-1001, corrected by X-1003): the AHEAD-WORK-BRANCH
                # fold — `task/*` / `work/*` branches carrying commits main does not have. Wired at this SAME
                # one shared residue as every sibling, so it rides all three debt seams (session-start /
                # land-tail / the `debt` re-fold) from ONE site and they cannot drift apart. It rides ALL
                # THREE deliberately, like its rule-23 complement and unlike the rule-21 census: a land tail
                # is exactly the moment a stranded SIBLING branch should be named, and it is a seam a
                # dispatched worker reaches. NOT controller-gated — the remedy (read it, then merge or delete)
                # is available to any session. A repo whose every work branch is merged folds to 0 →
                # suppressed, so history is never retro-charged, and a row drops the moment its branch merges
                # or is deleted.
                _ahead_branches=_ahead_branch_view,
                _behind_branches=_behind_branch_view,
                # T-11187 (SPEC-0119 rule 20 / SPEC-0163, X-0932): the remote-lag fold over THIS repo's ops
                # carrier + LOCAL git refs. Wired at this SAME one shared residue, so it rides all three debt
                # seams (session-start / land-tail / the on-demand `debt` re-fold) from ONE site and they
                # cannot drift apart — the property that lets option (c) answer X-0932 with NO change to
                # `cmd_land` at all. Under `-C` it reads that consumer's own carrier and its own checkout.
                # A repo that declares no remote_sync — or waives — folds to `not-declared` → suppressed.
                # T-11353 (SPEC-0119 rule 25 / <project> X-1025): the CONCURRENT-SESSION-HOLDS fold — live
                # worktrees carrying ANOTHER session's T-0362 stamp. Rendered through this SAME one shared
                # residue as every sibling, so there is ONE fold and ONE render arm.
                # TWO GATES, and they are different in kind:
                #  (a) SEAM — the `_concurrent` PARAMETER, WITHHELD by default (rule 21's detached-not-
                #      conditioned discipline). This view rides SESSION-START and the on-demand `debt`
                #      re-fold, and NOT the LAND TAIL. Not a preference: T-11139 pins the land tail's
                #      count to AGREE with the `debt` verb re-folded over the SAME journal, and every
                #      sibling here is a JOURNAL / carrier fold that satisfies that. This one is a
                #      CHECKOUT fold — and the land tail is precisely the seam that DELETES a checkout, so
                #      it reads a frontier (its own landing worktree included) that the post-land re-fold
                #      cannot see. A view that cannot honour a seam's contract is withheld from that seam,
                #      never conditioned into silence inside it.
                #  (b) AUDIENCE — CONTROLLER-ONLY, the rule-12 gate reused verbatim: None in a dispatched
                #      WORKER (`YITC_EXPECTED_SESSION_REF` set), where it is noise it cannot act on — a
                #      worker INHERITS its controller's session id (T-0412), so its own fleet reads as its
                #      own stamp while every OTHER controller's work reads as a hold it cannot touch. The
                #      remedy the line points at (read before you dispatch or claim) is a CONTROLLER's.
                # A repo where every live worktree carries the reading session's own stamp folds to 0 →
                # suppressed, which is AC2 and the whole reason the line stays readable.
                _concurrent_sessions=(None if _worker_session_ref() else _concurrent),
                _remote_lag=lambda: debt_mod.remote_lag(REPO_ROOT / "yitc-ops.yaml", REPO_ROOT))
        except Exception:
            lines = []
        # T-10049 (SPEC-0152 rule 17 / SPEC-0119 rule 7, X-0191): APPEND the OPT-IN consumer startup-check
        # aggregated line (a project's declared yitc-ops.yaml `startup_checks:` — run + aggregated,
        # SUPPRESSED-WHEN-CLEAN), so it rides this echo's 3 seams (session-start / land-tail / `debt` re-fold)
        # with NO new mechanism. Best-effort ([] on any failure); a no-yitc-ops repo (the engine itself) → [].
        try:
            # T-13009: under `--read-only` the declared commands are NOT run (a not-run count line instead).
            lines = list(lines) + session.startup_check_lines(
                REPO_ROOT, _read_yaml, read_only=READ_ONLY_ROOT is not None)
        except Exception:
            pass
        # T-12789 (SPEC-0119 rule 43): APPEND the uncovered-user-surface row — silent without a
        # `ui.surfaces:` declaration and when clean; rides the same 3 seams with no new mechanism.
        lines = list(lines) + uncovered_surface_debt_lines(REPO_ROOT, _read_yaml)
        # T-10503 (SPEC-0119 rule 15 / SPEC-0093, X-0364): APPEND the per-user CAPABILITY preflight — which
        # DECLARED lifecycle commands (yitc-ops.yaml verify.layers/tests.classes + the ENGINE-resolved
        # external auditor binary) the CURRENT user cannot RUN (leading executable unresolvable). Read-only
        # (never runs the command), suppressed-when-clean, rides this echo's 3 seams with NO new mechanism.
        # The auditor binary is engine-resolved so a `-C` consumer session preflights the SAME auditor it
        # will invoke; `die` is a no-op so a config-read hiccup degrades to []-safe, never aborts the echo.
        try:
            _audit_bin = audit.resolve_codex_binary(
                config_path=ENGINE_ROOT / "bin" / "audit-config.yaml", die=lambda *_a, **_k: None)
        except Exception:
            _audit_bin = None
        try:
            _audit_auth = audit.subscription_auth_present()   # the real per-user auditor blocker (auth.json)
        except Exception:
            _audit_auth = None                                 # undeterminable → auth leg skipped, never false-flag
        # T-11472 — INSIDE A HERMETIC VERIFY CHILD THIS QUESTION HAS NO ANSWER, so give the honest one.
        #
        # THE MEASURED DEFECT. `subscription_auth_present()` is the ONE input to this whole echo that is
        # rooted at the USER'S HOME rather than at REPO_ROOT: it reads
        # `$CODEX_HOME/auth.json` → `~/.codex/auth.json` → `~/snap/codex/current/auth.json`. SPEC-0131
        # Rule 1 gives every verify child a PRIVATE mkdtemp HOME — correct, and the point — but
        # `hermetic_child_env` does NOT scrub CODEX_HOME the way it scrubs its three sibling auditor
        # knobs (`_HERMETIC_AUDITOR_ENV_OVERRIDES`). So the probe is HALF-hermetic: HOME sandboxed,
        # CODEX_HOME inherited from whatever launched the land — and on this host CODEX_HOME is exported
        # by an INTERACTIVE-shell rc (`~/.bashrc`). A land started from an interactive controller found
        # the login and this leg stayed silent; a land started from a non-interactive launcher (cron,
        # systemd, a headless dispatch) probed an EMPTY box home, concluded "no codex login", and
        # emitted a capability line. Measured 2026-08-23 in a pinned-verify-shaped sandbox: 7/7 pass
        # with CODEX_HOME inherited, 25/25 fail without it — deterministic given the environment, which
        # is why it read as a flake across lands and passed 7/7 in every standalone run.
        #
        # WHAT IT BROKE, and why it is a real defect rather than a test artifact. That one line is the
        # only part of `_debt_echo_lines()` that does NOT go mute when REPO_ROOT is removed, which is
        # the read-dependency `tests/test_t11139_land_tail_before_teardown.py::test_p2` pins. The pinned
        # last-green leg therefore went RED on four different branches on a fact about the LAUNCHER'S
        # SHELL. But the deeper wrong is the line itself: it told a synthetic, user-less sandbox HOME
        # that the OPERATOR must run `codex login`. That is a false statement about a real person's
        # machine, produced by reading a directory that belongs to the harness.
        #
        # THE FIX IS THE LEG'S OWN DOCUMENTED FAIL-SAFE, not a new one. `capability_preflight_lines`
        # already defines `audit_auth_present=None` as UNDETERMINABLE ⇒ the auth leg is skipped, never
        # false-flagged. Inside a hermetic child the answer genuinely IS undeterminable — there is no
        # user whose provisioning could be reported — so None is the honest value, not a suppression.
        # The discriminator is the EXISTING positive one (`_in_hermetic_verify_child`, T-11288): this
        # process's OWN TMPDIR resolving to a real directory under a verify-sandbox root. Never a new
        # marker, never "an error happened"; not resolving ⇒ production ⇒ unchanged behaviour.
        #
        # NARROW BY CONSTRUCTION — only THIS leg, and only where it would otherwise SPEAK. The
        # repo-derived legs (yitc-ops.yaml verify.layers / tests.classes, the auditor BINARY probe) are
        # untouched, so `test_t10503::test_d1` — which drives `-C <consumer> debt` as a subprocess,
        # hence inside the sandbox, and requires its verify:layer gap to surface — keeps working; its
        # own comment already calls this auth leg "an env-dependent confound", and this removes exactly
        # that confound. Asked ONLY when the probe came back False (a gap is about to be emitted), so
        # the common provisioned path never pays the lazy `worktree` import.
        if _audit_auth is False and worktree_mod._in_hermetic_verify_child():
            _audit_auth = None
        try:
            # T-11473 — the SAME hermetic answer for the SIBLING HOME-rooted leg. The playwright
            # browser-CACHE probe reads `$PLAYWRIGHT_BROWSERS_PATH` else `~/.cache/ms-playwright`, so
            # inside a verify child it too would report the harness's empty box HOME as a real
            # operator's missing browsers. Its value is computed INSIDE `capability_preflight_lines`
            # (unlike `_audit_auth` above, which the host computes), and `lib.session` is kernel-pure —
            # so the discriminator is INJECTED from here, and it is the SAME existing positive one the
            # `_audit_auth` carve-out just above uses. Never a second, hand-rolled containment read.
            #
            # PASSED AS A LAMBDA, not as the bound attribute, and that is load-bearing rather than
            # style: `worktree_mod` is a `_LazyLib` whose import fires on the FIRST ATTRIBUTE TOUCH, so
            # handing over `worktree_mod._in_hermetic_verify_child` would import `lib.worktree` on
            # EVERY debt echo — including the overwhelmingly common one with no playwright command
            # declared at all. The thunk keeps the touch inside the leg, which asks it only when a gap
            # is about to be emitted; the `_audit_auth` carve-out above preserves the same property by
            # short-circuiting on `is False` first.
            lines = list(lines) + session.capability_preflight_lines(
                REPO_ROOT, _read_yaml, audit_binary=_audit_bin, audit_auth_present=_audit_auth,
                _in_hermetic_child=lambda: worktree_mod._in_hermetic_verify_child())
        except Exception:
            pass
        # T-10077 (SPEC-0119 rule 8 / SPEC-0123): APPEND the report-only per-consumer born-schema-SKEW
        # self-check — whether THIS repo's OWN yitc-ops.yaml is behind the current kernel born schema (the
        # born sections/subfields a re-`init` would deliver, same detector the init update uses). Each
        # project watches AND updates ITSELF at its own debt seams (owner directive 2026-07-03) — this
        # REPLACES the retired engine-side registry sweep (the kernel enumerating every registry consumer
        # on their behalf; the sweep's host residue + registry-resident gate + view/debt-line were removed
        # by T-10077). The engine's own repo is not a consumer of the ops contract → withheld by identity
        # (T-13525, SPEC-0186 rule 6). Best-effort ([] on any failure); suppressed-when-clean.
        try:
            if _posture:
                lines = list(lines) + session.born_skew_check_line(
                    REPO_ROOT, _read_yaml, init_mod._consumer_carrier_skew)
        except Exception:
            pass
        # T-12085 (SPEC-0119 rule 39 / SPEC-0198 rule 5) — THE WRITER, and it is placed HERE for two
        # reasons that both matter. It runs AFTER the render, so a filing failure can never cost the
        # owner the report they came for; and it runs INSIDE this one shared residue, so the filing
        # rides exactly the seams the surfacing already rides — session start, the land tail, the
        # on-demand `debt` re-fold — with no schedule, no daemon and no seam of its own.
        #
        # IT FILES AND NOTHING ELSE. `_profile_gap_autofile` appends `followup_added` rows, capped
        # per run and deduped forever by the key the fold computed; it dispatches nothing, audits
        # nothing, deploys nothing and touches no code (SPEC-0198 rule 5 / CHARTER §6). On the engine's
        # own repo the register is the empty one (T-13525 — by identity), so this files nothing.
        # T-13011 — under READ_ONLY_ROOT both writers are SKIPPED (the render above is untouched):
        # their appends would land in the READER's journal while the dedupe/latch folds read the
        # TARGET's, so a read-only fold must stay write-free.
        if READ_ONLY_ROOT is not None:
            return lines
        if _gap_reg is None or _gap_profile is None:
            return lines
        _profile_gap_autofile(_gap_reg, carrier=_gap_carrier)
        # T-12452 (SPEC-0198 rule 7) — the latch's WRITER. `profile._prior_snapshot` folds the last
        # `profile_snapshot_recorded` row; without a writer at a production seam no row ever existed
        # and a toggled signal narrowed. Recorded from the SAME resolution the echo just rendered,
        # after the render, idempotent per snapshot hash.
        _profile_snapshot_record(_gap_profile)
        return lines


def _debt_echo_compact(_debt_echo_lines=None, *, debt_mod, _cli_invocation_form) -> list:
    """Compact rendered echo lines to the SPEC-0119 rule-40 table (T-12305), best-effort.

    BEST-EFFORT ON PURPOSE, exactly like the `_debt_echo_lines` fold it wraps: this is a report-only
    presentation surface riding the session-start seam, so a failure here falls back to the FULL
    lines rather than costing a `session start`. Degrading to unreadable beats degrading
    to broken — and to silent, which returning [] would be."""
    lines = list(_debt_echo_lines or ())
    # T-13075: resolved OUTSIDE the fail-open try — a failed resolution must never render a
    # bare-form table on a consumer that cannot run it.
    cli_form = _cli_invocation_form()
    try:
        return debt_mod.debt_echo_table(lines, cli_form=cli_form)
    except Exception:
        return lines
