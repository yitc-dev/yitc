"""debt_adoption — the ADOPTION family of `bin/yitc-v2 debt` views, extracted byte-identical from
`bin/lib/debt.py` (T-12707, card C9c of plan `extract-the-13-over-budget-bin-lib-modules-into-le`).

WHAT IS IN HERE. The 16 adoption-side debt verbs — `open_proof_obligations` (SPEC-0149),
`open_known_broken`, `open_subcritical_findings`, `p8_carrier_followups` / `uncarried_p8_warns`
(the Principle-8 carrier fold), `unproven_checks` / `declared_checks` (SPEC-0156), `unexecuted_test_classes`
(SPEC-0152) / `unexecuted_subject_files`, `unresolved_worker_halts`, and the gap-register helpers
`gap_autofile_text` / `gap_dedupe_key` / `gap_dimension` / `gap_item_lenses` / `gap_rank` / `gap_task_linked`
— plus their transitive-EXCLUSIVE helper closure (the `_gap_*`, `_known_broken_*`, `_p8_*`, `_test_class_*`
readers, the `_*_result` renderers and the small pure helpers), 44 defs frozen at baseline 02250d5 (plan
§Extraction map C9c: 39 by the fixpoint lens seeded at the 16 verbs + the 5 `_gap_*` helpers the host stayer
`profile_gap_register` drives through their residues). The 39 constants that only this family reads moved
with it and live module-local here (one is read from a moved signature DEFAULT — `uncarried_p8_warns`'s
`window_hours=P8_WARN_WINDOW_HOURS` — evaluated at def time, so it cannot arrive by injection). A constant
a BODY reads is ALSO injected by the host residue, so rebinding the historical host name (`debt.X = …`, a
monkeypatch) is honoured on every call through the host — a module attribute is not a live alias across
modules, so the alias alone would keep lookup but lose assignment semantics (T-12698 audit-pre finding 1).

NOT IN HERE. `cmd_debt` and the echo registry, the landing (`debt_landing`) / spec0161 (`debt_spec0161`) /
plan-census families, and the host-shared readers this family calls (`_parse_stamped_deadline`,
`_obligation_key`, `_check_rows_from_carrier`, `_declared_test_classes`, `_is_waived`, the admission
near-miss helpers, …) — those STAY host and arrive by injection, as do the 4 host constants a stayer
also reads (`OBLIGATION_CARRIER_EVENTS`, `TERMINAL_CARD_STATUSES`, `_PROVENANCE_GIT_TIMEOUT`, `_TASK_ID_RE`).

SEAM (the T-9340 / T-9341 / T-11519 / T-12698 / T-12703 full inject-residue shape,
`lessons/library-extraction.md` §AST-freeze generator): bodies and signatures are spliced VERBATIM from the
original source — never `ast.unparse` — and every non-stdlib, non-moved free name (host stayers, host
globals, AND moved siblings via their host residue, AND body-read moved constants) arrives as a keyword-only
injected parameter, computed with `symtable` over each function's scope SUBTREE. The host keeps a
`functools.wraps` residue under every historical name and a re-export alias for every moved constant, so
every `debt.<symbol>` reader (cli / views / worktree / journal / task / followup / audit / batch_landing /
verify_runner / the sibling leaves + the tests' monkeypatches) keeps resolving. The function-LOCAL lazy
imports inside the verbatim bodies (`lib.init` / `lib.task` / `lib.profile` / `lib.followup` /
`lib.worktree`, `subprocess`) are the bodies' own, unchanged.

Identity-agnostic KERNEL module (SPEC-0073 bin/ HARD class). It imports only stdlib + the lower
leaves `lib.state` / `lib.journal`; it NEVER back-imports its host `lib.debt`.
"""
from __future__ import annotations

import bisect
import json
import re
from array import array
from datetime import date, datetime, timezone
from pathlib import Path

import yaml

from lib import state  # CHARTER §P5 one parser library — the ops-carrier reader
from lib import journal  # the ONE parsed journal fold + its request-scoped memo (CHARTER §P5)


# ---------------------------------------------------------------------------
# Constants moved WITH their readers (T-12707): each is read ONLY by this family (exclusivity computed
# as a fixpoint over host defs + module statements); one is read from a moved signature DEFAULT, which
# is evaluated at def time in THIS module. The host keeps a re-export alias under each historical
# name, and a body-read constant is ALSO injected by the host residue so a host-side rebind stays
# honoured (see the module docstring).
# ---------------------------------------------------------------------------
OBLIGATION_CLOSING_EVENT = "deploy_recheck_completed"
OBLIGATION_MISS_EVENT = "deploy_recheck_missed"
OBLIGATION_MISS_JUDGEMENT_KEY = "judgement"
MISS_WINDOW_DAYS = 30
SUBCRITICAL_SEVERITIES = frozenset({"warning", "info"})
FINDINGS_REPORT_GLOB = "*-security.yaml"
_ISO_DATE_PREFIX = re.compile(r"^(\d{4}-\d{2}-\d{2})")
ABSENT_CARD_RESOLUTIONS = frozenset({"card-deleted", "test-fixture"})
EXECUTION_EVENT = "test_class_executed"
EXECUTION_PASS_OUTCOME = "pass"
EXECUTION_REQUIRED_FIELDS = ("evidence",)
NEAR_MISS_CAP = 3
KNOWN_BROKEN_CARRIER_EVENT = "land_completed"
KNOWN_BROKEN_RECORD_KEY = "failure_attribution"
KNOWN_BROKEN_ESTABLISHING_SIDE = "at_main"
KNOWN_BROKEN_CLEARING_SIDE = "at_branch"
KNOWN_BROKEN_VACATED_REASON = "test-file-removed"
KNOWN_BROKEN_TEST_SUBDIR = "tests"
KNOWN_BROKEN_RAN_TESTS_KEY = "selection_ran_tests"
KNOWN_BROKEN_DELEGATED_LAYER_KEY = "consumer_tests_delegated_layer"
KNOWN_BROKEN_DELEGATED_FILES_KEY = "consumer_tests_delegated_files"
KNOWN_BROKEN_LAYER_ROWS_KEY = "consumer_verify_layers"
KNOWN_BROKEN_LAYER_PASSED = "passed"
P8_WARN_EVENT = "task_closed"
P8_WARN_KEY = "adoption_evidence_seen"
P8_CARRIER_MARKER = "P8-CARRIER:"
P8_CARRIER_FOLLOWUP_STATUSES = frozenset({"open", "promoted"})
P8_WARN_WINDOW_HOURS = 168
P8_ADOPTION_EVENT_TYPES = frozenset({"consumer_read_evidence", "live_trigger_evidence"})
GAP_MARKER = "GAP:"
GAP_KEY_PREFIX = "gap"
# T-13139 — the rows `_gap_filed_rows` reads (its host injects a reader declaring exactly these).
GAP_FILED_READ_TYPES = ("followup_added", "followup_promoted", "followup_dropped")
GAP_CONSTANT_FLOOR_DIMENSION = "constant-floor"
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
_GAP_OUT_OF_SCOPE_TOKENS = ("not applicable", "n/a", "out of scope", "out-of-scope",
                            "does not apply", "no such surface")
_GAP_ADAPTED_TOKENS = ("adapted", "divergence", "instead of", "local variant", "override")
_GAP_SHAPED_ANSWER_KEYS = {("alert_routing", "slo"): "_alert_routing_slo_missing"}
_GAP_DECLARED_STATES = ("adopted", "adapted")
GAP_CARRIER_TASK_KEY = "task"
_GAP_TASK_ID_RE = re.compile(r"^T-\d{4,}$")


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



def open_proof_obligations(events_path, now=None, *, MISS_WINDOW_DAYS=None, OBLIGATION_CARRIER_EVENTS=None, OBLIGATION_CLOSING_EVENT=None, OBLIGATION_MISS_EVENT=None, OBLIGATION_MISS_JUDGEMENT_KEY=None, _obligation_key=None, _parse_stamped_deadline=None, _superseded_before_deadline=None) -> dict:
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
        # SPEC-0190 rule 4 — the WHOLE journal; T-13139 — declared: the three row classes this fold
        # keeps (every other row's key is computed and then matches no branch, so reading it moved nothing).
        for event in journal.segment_rows(
                events_path, types=(OBLIGATION_CLOSING_EVENT, OBLIGATION_MISS_EVENT)
                + tuple(OBLIGATION_CARRIER_EVENTS)):
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



def _report_date(path: Path, report: dict, *, _ISO_DATE_PREFIX=None):
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



def _open_subcritical_identities(report: dict, *, SUBCRITICAL_SEVERITIES=None, _finding_identity=None) -> dict:
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



def open_subcritical_findings(findings_dir, floor_days: int = 30, now=None, *, FINDINGS_REPORT_GLOB=None, _open_subcritical_identities=None, _report_date=None, _subcritical_authority=None, _subcritical_result=None) -> dict:
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
    if not isinstance(data, dict) or data.get("kind") != "refused":
        return False
    # T-12762 (X-1504) — EXCLUDE the CLAIM-LOST sub-class. Its caller drops a halt whose CARD reads
    # `refused: False`, on the T-11679 reasoning "the refusal was disposed, so the card awaits no
    # decision". A claim-lost halt writes NO card fields BY CONSTRUCTION (that is the whole point of
    # the arm that emits it), so the card reads `refused: False` from the very first moment and the
    # drop would fire on a halt nobody has disposed of — silently hiding a needs-decision row from
    # the rule-18 view, the exact hiding that view exists to prevent. Keeping the predicate to TRUE
    # pre-claim refusals only ever KEEPS a row, so the fold's fail-closed-toward-visible posture is
    # unchanged; a legacy row carrying no `refused_class` answers True exactly as before.
    return not data.get("refused_class")



def unresolved_worker_halts(_dispatch_events, _halt_resolution, _dispatch_task_of, now=None, *,
                            _card_state=None, _absent_card_provenance=None,
                            _halt_dispatcher=None, self_session_ref=None, ABSENT_CARD_RESOLUTIONS=None, TERMINAL_CARD_STATUSES=None, _is_pre_claim_refusal=None, _parse_stamped_deadline=None, _unresolved_halt_result=None) -> dict:
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
    <project> 2026-08-09: T-0146 idle 4h and T-0183 idle 2.5h, both absent from `--fleet-verdict`, both
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



def declared_checks(ops_path, *, _check_rows_from_carrier=None) -> list:
    """The kernel-graded checks THIS repo declares (SPEC-0156 §1), read from its yitc-ops.yaml carrier.

    Returns `[{check, declaration, definition_identity}]` — one row per declared check, each carrying the
    identity of the definition AS IT STANDS NOW. Never raises: a missing / unreadable / malformed / non-
    mapping carrier yields `[]`.

    A REPO WITH NO CARRIER DECLARES NOTHING, AND THAT IS WHAT MAKES HISTORY SAFE. A file with none of these
    checks (the engine kernel's own) reads the same: `[]`, and the whole view stays silent — no retro-charge. It
    is the same property the sibling proof-obligation fold had to buy with a disproof: a fold-side default
    over the real journals retro-created 39 debt lines across 3 consumers (SPEC-0149 §1). Debt is what a
    project DECLARED and has not PROVEN — never what it never declared.
    """
    try:
        carrier = state.load_ops(Path(ops_path))
    except (OSError, UnicodeDecodeError, yaml.YAMLError, TypeError):
        return []
    return _check_rows_from_carrier(carrier)



def unproven_checks(ops_path, events_path, now=None, *, _admission_demonstrations=None, _admission_near_misses=None, _genuine_supersession=None, _identities_ever_declared=None, _projection_superseded=None, _unproven_result=None, _wanted_identities=None, declared_checks=None) -> dict:
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



def _unproven_result(now, checks: list, *, _near_miss_clause=None) -> dict:
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



def _execution_defect(data, *, EXECUTION_PASS_OUTCOME=None, EXECUTION_REQUIRED_FIELDS=None) -> str:
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



def _test_class_executions(events_path, *, EXECUTION_EVENT=None, _execution_defect=None, _parse_stamped_deadline=None) -> dict:
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
    passing records in the archive as never-executed (X-1100, <project> 2026-08-25)."""
    out: dict = {}
    try:
        # SPEC-0190 rule 4 — the WHOLE journal; T-13139 — declared: the execution rows only.
        for event in journal.segment_rows(events_path, types=(EXECUTION_EVENT,)):
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



def _test_class_near_misses(events_path, names, *, EXECUTION_EVENT=None, NEAR_MISS_CAP=None, _execution_defect=None, _parse_stamped_deadline=None) -> list:
    """Fold the journal → the `test_class_executed` records that TRIED to record a run of a still-surfaced
    class and did NOT (X-0470). <project> emitted `outcome: green` with `run:` instead of `evidence:`; the
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
        # SPEC-0190 rule 4 — the WHOLE journal; T-13139 — declared: the execution rows only.
        for event in journal.segment_rows(events_path, types=(EXECUTION_EVENT,)):
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



def unexecuted_test_classes(ops_path, events_path, floor_days: int = 30, now=None, *, _declared_test_classes=None, _test_class_executions=None, _test_class_near_misses=None, _unexecuted_result=None) -> dict:
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
                "actually RUN. A class nobody ran is not coverage (a consumer's e2e suite: browsers never "
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



def unexecuted_subject_files(ops_path, repo_root=None, *, _is_waived=None, _unexecuted_subject_result=None) -> dict:
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
        SPEC-0149 lesson) and the engine kernel — whose own file declares none of it — folds to 0 ⇒ suppressed.
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
                "state; a repo declaring none of these subjects (the engine kernel itself) folds to 0 → suppressed. "
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



def _known_broken_pairs(data, side: str, *, KNOWN_BROKEN_RECORD_KEY=None) -> list:
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



def _known_broken_ran_tests(data, *, KNOWN_BROKEN_RAN_TESTS_KEY=None) -> "frozenset | None":
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



def _known_broken_delegated_pass_files(data, *, KNOWN_BROKEN_DELEGATED_FILES_KEY=None, KNOWN_BROKEN_DELEGATED_LAYER_KEY=None, KNOWN_BROKEN_LAYER_PASSED=None, KNOWN_BROKEN_LAYER_ROWS_KEY=None) -> "frozenset | None":
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



def _known_broken_blob_exists(root, sha: str, relpath: str, *, _PROVENANCE_GIT_TIMEOUT=None) -> "bool | None":
    """Was `relpath` present in the tree at `sha`? True / False / None = COULD NOT ANSWER.

    Three-valued deliberately (SPEC-0165 item 11) — `None` is not a soft False. A missing sha, an
    unresolvable one, a pruned history, or no git at all returns `None` and the fold FAILS CLOSED;
    collapsing that into False would silently VACATE records on a machine without git.
    """
    from lib import git_env as _git_env  # T-13587 — the git child env policy (SPEC-0188 rule 7)
    if not sha or not str(sha).strip():
        return None
    import subprocess
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "cat-file", "-e", f"{str(sha).strip()}:{relpath}"],
            capture_output=True, text=True, timeout=_PROVENANCE_GIT_TIMEOUT, env=_git_env._git_child_env())
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
                               capture_output=True, text=True, timeout=_PROVENANCE_GIT_TIMEOUT,
                               env=_git_env._git_child_env())
    except Exception:                     # noqa: BLE001
        return None
    return False if probe.returncode == 0 else None



def open_known_broken(events_path, root=None, _blob_exists=None, *, KNOWN_BROKEN_CARRIER_EVENT=None, KNOWN_BROKEN_CLEARING_SIDE=None, KNOWN_BROKEN_ESTABLISHING_SIDE=None, KNOWN_BROKEN_TEST_SUBDIR=None, KNOWN_BROKEN_VACATED_REASON=None, _known_broken_blob_exists=None, _known_broken_delegated_pass_files=None, _known_broken_file=None, _known_broken_full_enumeration=None, _known_broken_pairs=None, _known_broken_ran_tests=None, _parse_stamped_deadline=None) -> dict:
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
        # T-13139 — declared: the land rows only (the whole history, unchanged).
        for event in journal.segment_rows(events_path, types=(KNOWN_BROKEN_CARRIER_EVENT,)):
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
        # tried to land paperwork (<project>, X-1151 / X-1164, measured twice 2026-08-27).
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



def p8_carrier_followups(events_path, _followups=None, *, P8_CARRIER_MARKER=None, _TASK_ID_RE=None):
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
            toks = chunk.split()
            # T-13637 — a hand-typed carrier often ends its sentence on the id (`P8-CARRIER: T-0066.`);
            # trailing punctuation is not part of an id, so it is dropped before the anchored match.
            m = _TASK_ID_RE.match(toks[0].rstrip(".,;:!?)]}>'\"`")) if toks else None
            if m:
                carried.add(m.group(0))
        # T-13637 — a marker that names no readable id still yields its record, with EMPTY `task_ids`:
        # every consumer selects by id membership, so it carries nothing, and `followup add` can tell
        # "no marker" from "a marker this parse cannot read" without a second marker check.
        out.append({"id": it.get("id") or fid,
                    "task_ids": carried,
                    "trigger": it.get("trigger"),
                    "awaits": it.get("awaits"),
                    "status": it.get("status"),
                    "text": text})
    return out



def _p8_carrier_task_ids(events_path, _followups=None, *, P8_CARRIER_FOLLOWUP_STATUSES=None, p8_carrier_followups=None) -> set:
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
                              repo_root=None, _is_consumer_build=None):
    """T-11740 — was the adoption actually PROVED after the WARN fired?

    THE STRUCTURAL DEFECT THIS ENDS. The WARN is a HISTORICAL SNAPSHOT taken at `task close`: once
    fired it is immutable, and until this arm the fold had no way to read anything that happened
    afterwards. So all three existing drop tests were ways of saying "the proof is still OWED" — a
    marked carrier followup, a declared post-ship observation, a deferred probe — and emitting the
    genuine `consumer_read_evidence` / `live_trigger_evidence` that CHARTER §P8 actually recognises
    left the row exactly where it was, while writing a followup promising it removed the row. A
    reporting consumer routed 11 named closures and the count fell from 11 to 8: it fell by the three
    PROMISES and by NONE of the eight PROOFS (X-1190 / <project> T-0515, whose own AC2 had to be
    authored to expect that doing the right thing did not count). The sibling report is the same fold
    seen from the false-positive side — 7 of 11 rows were closures whose substantive P8 evidence was
    emitted 17-38 SECONDS after the `task_closed` row (X-1170).

    THE STANDARD IS NOT WIDENED — it is the close-time one, REUSED. The judgement is
    `task._p8_evidence_is_substantive`, the same predicate `task close` applies (SPEC-0015): a
    non-empty `failing_input` naming the differential AND an `evidence_events` ref that resolves to a
    real, correlated, non-circular row. A prose-only or circular payload therefore still fails and the
    row still reports. Re-implementing that judgement here is what would let the two drift (CHARTER
    §P5), so it is imported, never copied. Its realm dep `_is_consumer_build` is INJECTED by the host
    caller (T-12796) so a consumer ref is judged under the consumer arm, as at `task close`; absent,
    the predicate reads KERNEL — the STRICTER of the two readings.

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
    who had done nothing. Measured on <project> 2026-09-02: two genuine, task-tied
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
            # it is rule-PRESERVING, not a widening of what counts.
            # T-12796 — `_is_consumer_build` rides the SAME injection: this module back-imports no
            # host module that could answer the realm question, so the HOST caller passes its own
            # probe in, and a consumer `test:<path>::<node>` ref (T-10914, no `&contrast=`) is judged
            # under the consumer arm exactly as `task close` judges it. Absent (None — a harness
            # driving this fn directly) the predicate still reads the STRICTER kernel arm: fail-closed.
            ok, why = _task._p8_evidence_is_substantive(ev, task_id, rows, with_reason=True,
                                                        REPO_ROOT=repo_root,
                                                        _is_consumer_build=_is_consumer_build)
            if ok:
                return _verdict(True)
            reason = why               # LATEST failing payload wins — see the docstring
        return _verdict(False, reason)
    except Exception:                    # noqa: BLE001 — unreadable => NOT proved => clears nothing
        return _verdict(False)



def uncarried_p8_warns(events_path, *, root, window_hours: int = P8_WARN_WINDOW_HOURS,
                       now=None, _followups=None, P8_ADOPTION_EVENT_TYPES=None, P8_WARN_EVENT=None, P8_WARN_KEY=None, _TASK_ID_RE=None, _p8_card_declares_carrier=None, _p8_carrier_task_ids=None, _p8_later_evidence_clears=None, _parse_stamped_deadline=None, _is_consumer_build=None) -> dict:
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
    # T-13020 — under `-C`, the ENGINE's own self-telemetry receipts (`subject_realm: kernel`) land in the
    # consumer journal; they prove a KERNEL surface was read, never a consumer card's adoption.
    try:
        consumer = bool(_is_consumer_build and _is_consumer_build())
    except Exception:                          # noqa: BLE001 — undecidable realm => partition nothing
        consumer = False
    try:
        # T-13139 — ONE walk yields both halves: `P8EvidenceReducer` keeps the P8 adoption rows and
        # the WARN rows (this loop's input, in logical order, over the WHOLE journal — SPEC-0190 rule
        # 4, the horizon unchanged) AND the resolution corpus the later-evidence arm resolves refs
        # against. Inside the debt seam's scope it is the reducer that one pass already fed.
        _evidence = journal.reduce_journal(events_path, P8EvidenceReducer, name="p8_evidence")
        for event in _evidence.p8_rows():
            if not isinstance(event, dict):
                continue
            etype = event.get("type")
            if etype in P8_ADOPTION_EVENT_TYPES:
                # The later-evidence arm's candidates, collected in the SAME pass (T-11740). Placed
                # ahead of the WARN filter only because the two type sets are disjoint; an
                # unplaceable id or stamp is simply not collected, so it can clear nothing.
                if consumer and journal.is_kernel_self_telemetry(event.get("data")):
                    continue                   # T-13020: kernel self-telemetry clears no consumer card
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
    rows_corpus = None
    for ts, task_id in sorted(candidates):
        if task_id in seen or task_id in carried:
            continue
        if _p8_card_declares_carrier(root, task_id):
            continue
        if rows_corpus is None:
            try:
                rows_corpus = _evidence.result()
            except Exception:                  # noqa: BLE001 — an unreadable journal accuses nobody
                return empty
        cleared, unproved_reason = _p8_later_evidence_clears(
            task_id, ts, p8_by_task, rows_corpus, with_reason=True, repo_root=root,
            _is_consumer_build=_is_consumer_build)   # T-12796 — the host's realm probe, passed through
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



# ── T-13139 — the P8 RESOLUTION CORPUS, built in the debt seam's one pass ────────────────────────────
#
# `_p8_evidence_is_substantive` resolves each evidence ref against a list of journal rows. Every ref
# form but one reads rows of ONE known type — `land_completed@…#…` the land rows, `…#surface=` the
# nightly rows, `exit:` the `cli_invoked` rows of a read-only conformance verb — and those rows are
# kept, in walk order. The bare `<TYPE>` / `<TYPE>@<ts>` form asks whether ANY row of a named type
# carries this task's top-level `task_id` / this exact `ts`, over every type the ref may name: that is
# an EXISTENCE question, answered from an exact index (`_P8TypeIndex`) instead of a copy of the journal.
# The old corpus also held every non-dict JSON value, and the resolvers' `.get` raised on the first one
# they reached; the sentinels keep that, in the same relative order, and the index stops recording at
# the first one exactly as the old loop stopped answering there.
_CANON_TS = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z\Z")


def _canon_ts_key(ts: str):
    """The journal's fixed-width UTC `ts` as an exact integer (YYYYMMDDHHMMSS), or None for any other
    spelling — a bijection on the canonical shape, so membership by integer IS membership by string."""
    if len(ts) == 20 and _CANON_TS.match(ts):
        return int(ts[0:4] + ts[5:7] + ts[8:10] + ts[11:13] + ts[14:16] + ts[17:19])
    return None


class _P8TypeIndex:
    """Exact answers to the bare-ref questions: does a row of type `t` carry `ts` / top-level `task_id`?"""

    def __init__(self, ts_keys, ts_other, tids, stopped):
        self._ts_keys = ts_keys
        self._ts_other = ts_other
        self._tids = tids
        self._stopped = stopped

    def _answer(self, found: bool) -> bool:
        if found:
            return True
        if self._stopped:
            raise AttributeError("a non-dict journal value precedes any match")
        return False

    def has_ts(self, etype, ts) -> bool:
        key = _canon_ts_key(ts) if isinstance(ts, str) else None
        if key is not None:
            arr = self._ts_keys.get(etype)
            i = bisect.bisect_left(arr, key) if arr is not None else 0
            return self._answer(arr is not None and i < len(arr) and arr[i] == key)
        return self._answer(ts in self._ts_other.get(etype, ()))

    def has_task(self, etype, tid) -> bool:
        return self._answer(tid in self._tids.get(etype, ()))


class P8ResolutionCorpus(list):
    """The rows the typed ref forms iterate, in walk order, carrying `type_index` for the bare forms."""
    type_index = None


class P8EvidenceReducer:
    """Builds `P8ResolutionCorpus` from one walk (fed by `journal.reduce_journal` / the seam's scope),
    and keeps the P8 adoption + WARN rows `uncarried_p8_warns` folds, so ONE walk serves both."""

    def __init__(self):
        from lib import task_closure_evidence as _tce   # local import: debt family back-imports no host
        self._skip = frozenset(_tce._NON_EVIDENTIAL_EVIDENCE_TYPES)
        self._verbs = frozenset(_tce._READ_ONLY_CONFORMANCE_SURFACES)
        self._keep_types = frozenset(P8_ADOPTION_EVENT_TYPES) | {P8_WARN_EVENT}
        self._kept: list = []
        self._entries: list = []
        self._ts_keys: dict = {}
        self._ts_other: dict = {}
        self._tids: dict = {}
        self._stopped = False
        self._src: list = []      # T-13309 — per `_entries` entry, what its summary stores
        self._fill: list = []     # T-13309 — a served summary's land-row places, filled by `replay`

    def add(self, seq, seg, row, line) -> None:
        t = row.get("type")
        if isinstance(t, str) and t in self._keep_types:
            self._kept.append(line)
        if t == "land_completed":
            self._entries.append(("row", row))
            self._src.append(["row"])
        elif t == "nightly_run_completed":
            self._entries.append(("line", line))
            self._src.append(["line", line])
        elif t == "cli_invoked":
            data = row.get("data")
            if isinstance(data, dict) and data.get("verb") in self._verbs:
                self._entries.append(("row", {"type": "cli_invoked", "ts": row.get("ts"),
                                              "data": {"verb": data.get("verb"),
                                                       "exit_code": data.get("exit_code")}}))
                self._src.append(["cli", row.get("ts"), data.get("verb"), data.get("exit_code")])
        if self._stopped or not isinstance(t, str) or t in self._skip:
            return
        ts = str(row.get("ts") or "")
        key = _canon_ts_key(ts)
        if key is not None:
            arr = self._ts_keys.get(t)
            if arr is None:
                arr = self._ts_keys[t] = array("q")
            arr.append(key)
        else:
            self._ts_other.setdefault(t, set()).add(ts)
        tid = row.get("task_id")
        if isinstance(tid, str):
            self._tids.setdefault(t, set()).add(tid)

    def nondict(self, seg, value) -> None:
        self._entries.append(("raw", value))
        self._src.append(["raw", value])
        self._stopped = True

    # T-13309 — the whole-history index's summary protocol (`journal._summary_identity`). The key carries
    # the three type sets the constructor reads from the host (configuration). Parsed rows travel as
    # their own JSON text (`json.dumps` keeps key order; the index sorts object keys), the type
    # index as pair lists. `prepend` is one logical-order walk: entries and kept lines concatenate, and
    # the type index of an instance whose older half already STOPPED is dropped — no row after the
    # first non-dict value ever reached it.
    def summary_key(self):
        return {"v": 1, "skip": sorted(self._skip), "verbs": sorted(self._verbs),
                "keep": sorted(self._keep_types)}

    def summary(self):
        if not all(isinstance(x, str) for x in self._kept) or len(self._src) != len(self._entries) \
                or any(s[0] == "line" and not isinstance(s[1], str) for s in self._src):
            raise ValueError("a summary needs every walked row's line")
        # a land row is NOT stored: the summary keeps its place and the index REPLAYS it from the
        # scope's own parse (`summary_replay_types` / `replay`), the object the typed store shares
        entries = [list(s) for s in self._src]
        return {"kept": list(self._kept), "entries": entries,
                "ts_keys": [[t, list(a)] for t, a in self._ts_keys.items()],
                "ts_other": [[t, sorted(v)] for t, v in self._ts_other.items()],
                "tids": [[t, sorted(v)] for t, v in self._tids.items()], "stopped": self._stopped}

    def load_summary(self, state) -> None:
        self._kept = list(state["kept"])
        self._src, self._entries, self._fill = [], [], []
        for s in state["entries"]:
            if s[0] == "row":
                self._fill.append(len(self._entries))
                self._entries.append(("row", None))
                self._src.append(["row"])
                continue
            elif s[0] == "line":
                self._entries.append(("line", s[1]))
            elif s[0] == "cli":
                self._entries.append(("row", {"type": "cli_invoked", "ts": s[1],
                                              "data": {"verb": s[2], "exit_code": s[3]}}))
            elif s[0] == "raw":
                self._entries.append(("raw", s[1]))
            else:
                raise ValueError(f"unknown entry kind {s[0]!r}")
            self._src.append(list(s))
        self._ts_keys = {t: array("q", a) for t, a in state["ts_keys"]}
        self._ts_other = {t: set(v) for t, v in state["ts_other"]}
        self._tids = {t: set(v) for t, v in state["tids"]}
        self._stopped = bool(state["stopped"])

    def summary_replay_types(self):
        return ("land_completed",)

    def replay(self, seq, seg, row, line) -> None:
        """A served segment's land row, in walk order: it fills the next place its summary kept."""
        if row.get("type") == "land_completed" and self._fill:
            self._entries[self._fill.pop(0)] = ("row", row)

    def prepend(self, older) -> None:
        if older._fill or self._fill:
            raise ValueError("a served summary's land rows were not all replayed")
        self._kept = older._kept + self._kept
        self._entries, self._src = older._entries + self._entries, older._src + self._src
        if older._stopped:
            self._ts_keys = {t: array("q", a) for t, a in older._ts_keys.items()}
            self._ts_other = {t: set(v) for t, v in older._ts_other.items()}
            self._tids = {t: set(v) for t, v in older._tids.items()}
            self._stopped = True
            return
        keys = {t: array("q", a) for t, a in older._ts_keys.items()}
        for t, a in self._ts_keys.items():
            keys.setdefault(t, array("q")).extend(a)
        other = {t: set(v) for t, v in older._ts_other.items()}
        for t, v in self._ts_other.items():
            other.setdefault(t, set()).update(v)
        tids = {t: set(v) for t, v in older._tids.items()}
        for t, v in self._tids.items():
            tids.setdefault(t, set()).update(v)
        self._ts_keys, self._ts_other, self._tids = keys, other, tids

    def p8_rows(self):
        """The P8 adoption and WARN rows, parsed fresh, in walk order."""
        return (json.loads(line) for line in self._kept)

    def result(self) -> P8ResolutionCorpus:
        corpus = P8ResolutionCorpus()
        for kind, payload in self._entries:
            corpus.append(json.loads(payload) if kind == "line" else payload)
        keys = {t: array("q", sorted(arr)) for t, arr in self._ts_keys.items()}
        corpus.type_index = _P8TypeIndex(keys, self._ts_other, self._tids, self._stopped)
        return corpus


def gap_item_lenses(lens) -> tuple:
    """The lens(es) an `_GAP_ITEMS` row is activated by — one row MAY name several (T-12089).

    A row's `lens` field is either a single lens id or a tuple of them, and the FIRST is the
    PRIMARY: the key/rank/dimension surface still reads exactly ONE lens per item, so an item asked
    at either of two crossings dedupes to a single followup rather than one per crossing.
    Normalizing here — in the one helper every reader of the catalog calls — is what keeps the
    multi-lens form from leaking into each of them."""
    return (lens,) if isinstance(lens, str) else tuple(lens)



def gap_dimension(lens: str, *, GAP_CONSTANT_FLOOR_DIMENSION=None) -> str:
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



def gap_dedupe_key(lens: str, item_id: str, *, GAP_KEY_PREFIX=None, gap_dimension=None) -> str:
    """The STABLE dedupe key SPEC-0198 rule 7 requires — `gap|<dimension>|<item id>`.

    It is a pure function of the item, so the SAME gap computed at any seam, in any run, on any day
    produces the SAME key. That is the whole "one followup per gap item, EVER" property: the writer
    files only keys the journal has never seen, and re-running a seam files nothing."""
    return f"{GAP_KEY_PREFIX}|{gap_dimension(lens)}|{item_id}"



def gap_rank(item, *, GAP_LENS_RISK_ORDER=None) -> tuple:
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



def _gap_waiver_answer(waiver, *, _GAP_OUT_OF_SCOPE_TOKENS=None) -> "tuple | None":
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



def _gap_section_answer(section, key=None, section_name=None, *, GAP_CARRIER_TASK_KEY=None, _GAP_ADAPTED_TOKENS=None, _GAP_DECLARED_STATES=None, _gap_declaration_incomplete=None, _gap_section_answer=None, _gap_waiver_answer=None) -> "tuple | None":
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



def _gap_declaration_incomplete(section_name, key, value, *, _GAP_SHAPED_ANSWER_KEYS=None) -> bool:
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



def gap_task_linked(promoted_into, *, resolvable, _GAP_TASK_ID_RE=None) -> bool:
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



def _gap_filed_rows(rows, *, GAP_KEY_PREFIX=None) -> dict:
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



def gap_autofile_text(item, *, GAP_MARKER=None, gap_dimension=None) -> str:
    """The body an auto-filed gap followup is captured with.

    It opens with `GAP_MARKER` — the ONE home the fold reads — and then says, in the owner's own
    terms, WHAT is missing, WHY this project is being asked (the profile activated the lens), WHERE
    the answer goes (the carrier section), and every way the row may be closed. A reader of the
    debt list must be able to act on it without re-opening anything, which is the property the
    T-11980 carrier text established and this one keeps."""
    lens = str((item or {}).get("lens") or "")
    activated_by = str((item or {}).get("activated_by") or lens)   # T-13041: the lens that admitted it
    return (f"{GAP_MARKER} {gap_dimension(lens)}/{(item or {}).get('item_id')} — "
            f"{(item or {}).get('label')}. YOUR PROFILE REQUIRES IT: the `{activated_by}` lens is active for "
            f"this project (SPEC-0198), and `{(item or {}).get('carrier')}:` in yitc-ops.yaml does "
            f"not answer it. CLOSE IT by answering that section — DECLARE how you meet it "
            f"(`adopted`), declare how you meet it DIFFERENTLY (`adapted`), or WAIVE it with a "
            f"reason (`waived`, or `out-of-scope` when the surface does not exist here) — or "
            f"promote this followup into a task (`task-linked`, which needs a resolvable T-id). "
            f"Auto-filed at a seam that was already running (SPEC-0119 rule 39); report-only — "
            f"nothing was dispatched, audited or deployed by it.")
