"""audit_packet — the audit PACKET family (the prompt/packet builders, the packet-bound elision
+ manifest helpers, the readiness/touch sections, the `_format_*` evidence notes, the card-record readers
the packet folds and the declaration blocks), extracted byte-identical from `bin/lib/audit.py`
(T-12701, card C7a of plan `extract-the-13-over-budget-bin-lib-modules-into-le`).

WHAT IS IN HERE. The FROZEN manifest of the plan's §Extraction map C7a — 38 top-level defs:
`build_audit_prompt, decision_audit_prompt_parts, _render_packet_manifest, _packet_bound_elisions,
_packet_elision_marker, _packet_section_breakdown, _packet_section_protected, _packet_sections,
_bound_packet_total, packet_readiness_section, packet_touch_section, _format_adoption_evidence_lines,
_format_collector_shape_note, _format_monotonic_reaudit_section, _format_sandbox_evidence_exclusion_note,
_format_type_optin_exclusion_note, _format_window_exclusion_note, _card_declared_ac_ids,
_card_declares_forecast, _card_forecasts_path, _card_repair_chain_transparent, _card_repair_chain_walk,
_card_repair_subject_admitted, _ac_canonical_id, _amend_notes_since, _collector_shape_for_source,
_declares_owed_settlement, _is_main_guard, _is_own_card_path, _md_cell, _pso_declared_criteria,
class_id_vocabulary, declared_deferred_probes_block, deferred_by_declaration_block,
deferred_by_declaration_rows, delta_discipline_block, p8_carrier_ids_in_section, parse_resolution_note`.
NOT IN HERE: `cmd_audit` / `cmd_audit_pre|post|adhoc|run|status|canary_backstop`, the gates, the
`_invoke_*` / `_resolve_*` families and the ceiling family (C7b's own card) — those stay in the host.

SEAM (the T-9340 / T-9341 / T-11519 / T-12696 full inject-residue shape, `lessons/library-extraction.md`
§AST-freeze generator): every body and signature below is spliced VERBATIM from the original source —
never `ast.unparse` — and every non-stdlib free name that is not an already-extracted lower leaf
(host stayers, host globals, AND moved siblings via their host residue) arrives as a keyword-only
injected parameter, computed with `symtable` over each function's scope SUBTREE. Constants exclusive
to the move-set live module-local below (the host keeps a re-export alias for each). The host keeps a
`functools.wraps` residue under every historical name (`audit._packet_inject` reads the roster from
`INJECTS` below at call time), so every `yitc.<sym>` / `audit.<sym>` monkeypatch and every
cross-module injection keeps resolving, and `inspect.getsource` unwraps to the body here.

A LEAF: imports only already-extracted lower leaves + stdlib and NEVER `lib.audit`
(`tests/test_bin_lib_leaf_no_host_import.py`). Intentionally spec-less (SPEC-0005 admission test): a
byte-identical relocation mints no standing rule — the governing specs (SPEC-0028 / SPEC-0094 /
SPEC-0168 / SPEC-0205) keep their homes and point their `implements:` anchors here.
"""
from __future__ import annotations
import ast
import fnmatch
import json
import re
import subprocess
from pathlib import Path


# ---------------------------------------------------------------------------
# Constants exclusive to the move-set (referenced by movers only — verified across the host,
# tests/ and bin/lib/ by the generator's fixpoint), moved module-local so the bodies read them
# 1:1, uninjected. The host keeps a re-export alias under each historical name.
# ---------------------------------------------------------------------------
_AUDIT_REVIEW_ONLY_CLAUSE = (
    "## Your role: REVIEW only — do NOT act\n\n"
    "You are REVIEWING the plan / diff below for quality — you are NOT performing the work. Do NOT\n"
    "edit, apply, create, or run anything; you have no write or execute task here. Being unable to\n"
    "write or execute in your sandbox is OUT OF SCOPE and is NEVER a finding. Return ONLY the\n"
    "verdict + findings YAML specified under ## Output.\n"
)

_AUDIT_PRE_ABSORPTION_ROUTES = (
    "## Absorption discipline — how each finding will be absorbed (E-0008)\n\n"
    "The audit-loop ceiling counts RE-AUDIT passes (max 2 per task per stage). For EACH finding you\n"
    "raise, judge whether fixing it genuinely CHANGES the plan/diff:\n"
    "- A PASSABLE finding (YELLOW / cosmetic / evidence-only — does NOT change the plan/diff) is\n"
    "  absorbed via mode-b: recorded in the verdict notes:/absorbed:, with NO re-plan and NO\n"
    "  re-audit, so it burns NO new pass.\n"
    "- Only a finding that genuinely changes the plan/diff uses mode-a: re-plan / re-implement →\n"
    "  re-audit, which costs a pass.\n"
    "Do NOT escalate a passable finding into mode-a — pushing passable findings through re-audit is\n"
    "the E-0008 false-ceiling defect. Severity-tag findings honestly, but prefer recording residuals\n"
    "over forcing a re-audit. (Fuller treatment: LIFECYCLE §Stage 4.)\n"
    "\n"
)

# T-13239 — shared by both stage clauses; the pre text concatenates back byte-identical.
_AUDIT_REJECT_RATIONALE_CLAUSE = (
    "REJECTING a YELLOW finding as WRONG — judged mistaken, so the session declines to absorb it AND\n"
    "files no follow-up. When the session rejects a YELLOW finding as wrong it MUST record a one-line\n"
    "rejection rationale in the verdict notes: (e.g. \"rejected finding N: <why the auditor is\n"
    "wrong>\"), so the override is auditable rather than a silent decline. (Rule home: SPEC-0124\n"
    "§Audit-loop ceiling — reject-as-wrong rationale.)\n"
)

_AUDIT_ABSORPTION_CLAUSE = (
    _AUDIT_PRE_ABSORPTION_ROUTES
    + "Absorption (mode-a/mode-b) is for findings the session ACCEPTS. A THIRD disposition is\n"
    + _AUDIT_REJECT_RATIONALE_CLAUSE
)

# T-13239 — audit-post has NO mode-b route (`audit pre --absorb` is audit-pre only), so the post
# packet names the routes LIFECYCLE §Stage 8 actually offers instead of pointing at one it lacks.
_AUDIT_POST_ABSORPTION_CLAUSE = (
    "## Absorption discipline — how each finding will be absorbed (E-0008)\n\n"
    "This is audit-POST: the diff is already committed, and the audit-loop ceiling counts RE-AUDIT\n"
    "passes (max 2 per task per stage). There is NO record-only absorption at this stage. For EACH\n"
    "finding you raise, judge whether it must change the shipped diff:\n"
    "- A PASSABLE finding (YELLOW / cosmetic / evidence-only — the diff can ship as-is) is carried\n"
    "  as a FOLLOW-UP task: the session files it and proceeds to closure, with NO re-audit, so it\n"
    "  burns NO new pass.\n"
    "- Only a finding that genuinely requires changing the diff is absorbed inline via mode-a: a fix\n"
    "  committed with `task commit --absorb`, then a re-audit of that new commit, which costs a pass.\n"
    "Do NOT escalate a passable finding into mode-a — pushing passable findings through re-audit is\n"
    "the E-0008 false-ceiling defect. Severity-tag findings honestly, but prefer a follow-up task\n"
    "over forcing a re-audit. (Fuller treatment: LIFECYCLE §Stage 8.)\n"
    "\n"
    "A follow-up task or a mode-a fix is for findings the session ACCEPTS. A THIRD disposition is\n"
) + _AUDIT_REJECT_RATIONALE_CLAUSE

_EVIDENCE_NOISE_KEYS = frozenset({"source"})

_COLLECTOR_DISCOVERY_CALLS = frozenset({"globals", "vars", "dir", "locals"})

_COLLECTOR_FACT_MAX_FILES = 12      # bound the section: the packet already runs ~70k tokens at the top end

_COLLECTOR_FACT_MAX_NAMES = 20      # bound one file's unnamed-arm list

_MAIN_GUARD_LITERAL = 'if __name__ == "__main__":'

_RESOLUTION_NOTE_SHAPE = "RESOLVED <finding-index>: <text> | CHECK: <text> | OUTPUT: <text>"

_RESOLUTION_NOTE_RE = re.compile(
    r"^RESOLVED\s+(\d+)\s*:\s*(.*?)\s*\|\s*CHECK\s*:\s*(.*?)\s*\|\s*OUTPUT\s*:\s*(.*)$",
    re.DOTALL)

_SETTLE_VERB_RE = re.compile(
    r"--settle-probe(?![\w-])|--settle-observation(?![\w-])|--settle-evidence(?![\w-])"
    r"|task close --settle(?![\w-])", re.IGNORECASE)

_DEFERRED_UNTIL_RE = re.compile(r"deferred until stage\s*9\b", re.IGNORECASE)

_OWED_DECLARATION_RE = re.compile(
    r"\bdeferred\b|\bowed\b|\bto be settled\b|\bsettled (?:later|after|post)"
    r"|\bdischarg\w*|\bpost-land\b|\bafter the ship\b|\blate-link\w*", re.IGNORECASE)

_PSO_NAMED_CRITERION_RE = re.compile(r"\b([A-Z]{1,4})[\s-]?(\d{1,3})\b")

PACKET_READINESS_DEFERRED_FIELDS = (
    "post_ship_observation",
    "activation_gated_radius",
    "host_config",
    "substituted_instrument",
)

_PACKET_PROTECTED_PREFIXES = (
    "## V2 evaluation lens",
    "## Your role",
    "## Absorption discipline",
    "## audit-pre overlay",
    "## audit-post overlay",
    "## Activates at closure",   # T-12977 — never elided: its absence would read as "activates nothing"
    "## ad-hoc overlay",
    "## Task:",
    "## Plan:",
    "## Ad-hoc request:",
    "## Consult target:",
    "## Focus questions",
    "## Output",
    "### Acceptance",
    "### Scope",
    "### Analysis (Stage-1 record",   # T-11427 — the card's Stage-1 record, same card-field class as
                                      # Scope/Acceptance/Implementation plan and bounded the same way
                                      # (`task analyze --finalize` caps it at 40 lines). Trimming it
                                      # would re-open the very false-RED this section closes.
    "### Implementation plan",
    "### Stage-6 test evidence",
    "### Session resolution options",
)

_PACKET_KEEP_TAIL_PREFIXES = (
    "### Adoption evidence",
)

# T-13538 — the `### Stage-6 test evidence` section's OWN budget. The heading is in
# `_PACKET_PROTECTED_PREFIXES`, so `_bound_packet_total` never trims it: whatever is rendered there
# has to bound itself, on the BYTE axis, through the one budget primitive (`_keep_within_budget`).
# The segment budgets plus the fixed marker / note text sum to under STAGE6_SECTION_MAX_BYTES, which
# `stage6_evidence_section` also enforces on the assembled whole.
STAGE6_MAX_ROWS = 10                     # rows shown, the latest included; older ones are counted, not shown
STAGE6_EARLIER_ROW_MAX_BYTES = 700       # one earlier row = one line (ts + evidence)
STAGE6_LATEST_EVIDENCE_MAX_BYTES = 10_000
STAGE6_LATEST_ACCEPTANCE_MAX_BYTES = 6_000
STAGE6_SECTION_MAX_BYTES = 32_000


# ---------------------------------------------------------------------------
# INJECTS — per mover, the keyword-only names its spliced signature gained (generated with
# `symtable` over the function's scope subtree, minus stdlib imports / builtins / the lower-leaf
# aliases / the consts above). The host residue under each historical name reads exactly this
# roster from its OWN globals at call time (`audit._packet_inject`), so the roster lives beside
# the signatures it describes and every residue stays a 5-line forwarder.
# ---------------------------------------------------------------------------
INJECTS = {
    "decision_audit_prompt_parts": (),
    "_format_adoption_evidence_lines": (),
    "_format_type_optin_exclusion_note": (),
    "_format_sandbox_evidence_exclusion_note": (),
    "_format_window_exclusion_note": (),
    "p8_carrier_ids_in_section": ("_P8_CARRIER_ROW_PREFIX",),
    "_is_main_guard": (),
    "_collector_shape_for_source": ("_is_main_guard",),
    "_format_collector_shape_note": ("_collector_shape_for_source",),
    "_amend_notes_since": ("_parse_iso_ts",),
    "parse_resolution_note": (),
    "_md_cell": (),
    "_format_monotonic_reaudit_section": ("_amend_note_body", "_amend_notes_since", "_is_no_data_prior",
                                          "_md_cell", "_passes_recorded", "parse_resolution_note"),
    "delta_discipline_block": (),
    "build_audit_prompt": ("BASE_PASS1_SURVEY_CLAUSE", "PROTOTYPE_PRE_OVERLAY", "_bound_packet_total",
                           "_keep_within_budget",   # T-13538: the Stage-6 section bounds itself
                           "_format_adoption_evidence_lines", "_format_collector_shape_note",
                           "_format_monotonic_reaudit_section", "_format_sandbox_evidence_exclusion_note",
                           "_format_type_optin_exclusion_note", "_format_window_exclusion_note",
                           "_merge_tie_ordering_note", "class_id_vocabulary",
                           "decision_audit_prompt_parts", "declared_deferred_probes_block",
                           "deferred_by_declaration_block", "delta_discipline_block",
                           "land_emitted_named_evidence", "on_decisions_packet_block",
                           "p8_carrier_ids_in_section", "packet_readiness_section",
                           "packet_touch_reconciliation", "packet_touch_section"),
    "_card_declares_forecast": (),
    "_card_forecasts_path": (),
    "class_id_vocabulary": ("CONSULT_BLOCKING_CLASS_IDS", "_FINDING_CLASS_SNIFFS"),
    "_declares_owed_settlement": (),
    "_pso_declared_criteria": (),
    "deferred_by_declaration_rows": ("_CROSS_ID_RE", "_EVENT_TOKEN_RE", "_EVENT_TOKEN_STOPWORDS",
                                     "_LAND_EMITTED_PHRASE_RE", "_PSO_CARD_LEVEL",
                                     "_declares_owed_settlement", "_pso_declared_criteria",
                                     "declared_deferred_probe_rows", "land_emitted_named_evidence"),
    "deferred_by_declaration_block": ("deferred_by_declaration_rows",),
    "declared_deferred_probes_block": ("declared_deferred_probe_rows",),
    "packet_touch_section": (),
    "_ac_canonical_id": ("_AC_CANONICAL_ID_RE",),
    "packet_readiness_section": ("_ac_canonical_id",),
    "_packet_sections": (),
    "_packet_section_protected": (),
    "_packet_elision_marker": (),
    "_render_packet_manifest": ("_PACKET_MANIFEST_HEADER",),
    "_packet_section_breakdown": ("_linebytes", "_packet_sections"),
    "_packet_bound_elisions": ("_PACKET_MANIFEST_HEADER",),
    "_bound_packet_total": ("AUDIT_MAX_PACKET_BYTES", "_keep_within_budget", "_linebytes",
                            "_packet_elision_marker", "_packet_section_protected", "_packet_sections",
                            "_render_packet_manifest"),
    "_card_repair_chain_transparent": ("_git_ship_landed",),
    "_card_repair_chain_walk": ("_CARD_REPAIR_CHAIN_MAX_DEPTH", "_card_repair_chain_transparent"),
    "_card_repair_authored_ship": ("_CARD_REPAIR_CHAIN_MAX_DEPTH", "_card_repair_chain_walk",
                                   "_folded_audit_post_record"),
    "_card_repair_subject_admitted": ("_card_repair_chain_walk", "_empty_subject_own_paths",
                                      "_is_own_card_path", "_card_repair_authored_ship"),
    "_folded_audit_post_record": (),
    "_card_declared_ac_ids": ("_ACCEPTANCE_AC_RE",),
    "_is_own_card_path": (),
}


def decision_audit_prompt_parts(decision: dict, stage: str, ctx: str | None) -> tuple[str, str]:
    """(overlay, body) for a DECISION audit prompt (per D-0055). Mirrors the task overlays but
    grades a decision: pre = design soundness; post = realization + coherence across follow_ups."""
    if stage == "pre":
        overlay = (
            "## audit-pre overlay — DECISION (Draft → Accepted)\n\n"
            "«Is this design sound to commit task resource to?»\n"
            "- the 4 anti-complexity filters genuinely pass (a decision is a governance change);\n"
            "- it EXPLICITLY amends the canonical surfaces it changes (does not silently bypass them);\n"
            "- alternatives / prior-art considered (Principle 1 F1); reuse over reinvention;\n"
            "- scope bounded; retirements NAMED (replacement, not accretion — what is removed/forbidden?);\n"
            "- adoption_probe is event/state/measurable (Principle 3 + 8 for infra-class);\n"
            "- coherence: does it contradict an existing decision / handbook rule (Principle 7 dissonance)?\n"
        )
    else:  # post
        overlay = (
            "## audit-post overlay — DECISION (Accepted → Final)\n\n"
            "«Did reality realize the decision's intent, coherently, across ALL its implementing tasks?»\n"
            "- every implementing task (refs.follow_ups T-NNNN) is `done`;\n"
            "- acceptance_criteria / adoption_probe ACTUALLY realized — probe evidence present, not merely claimed;\n"
            "- coherence: shipped reality matches what the decision SAID — no drift / contradiction (P7);\n"
            "- the retirements actually happened (what it said to remove/forbid is removed/forbidden).\n"
            "Review-only (D-0043): do NOT run tests; VERIFY the recorded Stage-6 evidence of the implementing tasks.\n"
        )
    def _blk(v):
        return json.dumps(v, ensure_ascii=False, indent=2, default=str) if v not in (None, "", [], {}) else "(empty)"
    body = (
        f"## Decision: {decision.get('id')} — {decision.get('title', '')}\n\n"
        f"type: {decision.get('type')} | status: {decision.get('status')}\n\n"
        f"### Decision\n{decision.get('decision') or '(empty)'}\n\n"
        f"### anti_complexity_check\n{_blk(decision.get('anti_complexity_check'))}\n\n"
        f"### adoption_probe\n{_blk(decision.get('adoption_probe'))}\n\n"
        f"### acceptance_criteria\n{_blk(decision.get('acceptance_criteria'))}\n"
    )
    if stage == "pre":
        body += f"\n### implementation_plan\n{_blk(decision.get('implementation_plan'))}\n"
    else:
        body += f"\n{ctx or '(no realization context)'}\n"
    return overlay, body


def charter_p8_reaches_class(task_class) -> bool:
    """T-12725 — does CHARTER §Principle 8 (consumer-side adoption evidence) REACH a card of this class?
    THE ONE class predicate: the refuter (`audit.p8_adoption_gap_on_non_infra`, T-12386), the packet
    readiness `P8 carrier:` row (T-11977) and the audit-post overlay's adoption-evidence ASK all resolve
    it HERE, at call time, so the three seams can never disagree about which cards §8 binds (CHARTER
    §P5 — the two inline copies this replaced already differed: one case-insensitive, one not).

    THREE-VALUED by construction, mirroring the refuter's original shape: `infra` => True (the demand
    stands); an UNRESOLVABLE class — None / empty / whitespace, a caller that never supplied it — =>
    True (FAIL-CLOSED: a missing adoption demand on real infrastructure is the v1 «shipped, nobody
    invoked it» failure §8 exists to prevent, and one spurious ask is the cheaper error); any other
    non-empty class => False (§8 binds infra only; Principle-3 probe-side adoption is that card's
    standard). Compared stripped, case-insensitive. Pure f(task_class) — no I/O."""
    cls = str(task_class or "").strip().lower()
    return not cls or cls == "infra"


def _format_adoption_evidence_lines(evidence_events) -> str:
    """Render a list of diff-invisible AC-probe / adoption journal events as auditor-facing bullet
    lines (T-9626 — extracted from the audit-post branch so the CONSULT branch reuses the SAME
    rendering, no parallel copy; CHARTER §P1 F1). Each line names the event type + ts + subject +
    the task-SPECIFIC proof carried in `data`.

    T-10142 — render ALL truthy `data` keys EXCEPT the known-noise denylist below, dropping the old
    FIXED positive allowlist (probe/mechanism/…/saved_to). That allowlist omitted honestly-emitted
    fields (trigger/observed/seam — the live_trigger_evidence shape), rendering real adoption proof
    as "(no data fields)"; the auditor then false-RED'd "adoption missing at a real seam" (T-10134).
    An inverted denylist is strictly more permissive and cannot re-introduce that omission class for
    any future honestly-named field. Emission order is preserved.

    T-12016 (X-1249, <project>) — the FALSY half of that same omission class. The guard was a
    truthiness test (`and v`), so every falsy scalar a probe honestly recorded — `0`, `False`, `''`,
    `[]` — was dropped from the rendered payload exactly as if the emitter had never written the
    key. Measured on <project> T-0603 audit-post pass 1 (2026-09-03): a `state_checked` row carrying
    the canonical differential `before: 9, after: 0` rendered as `before: 9`, and the auditor
    correctly REDed the probe as incomplete against evidence that WAS recorded — a burned pass plus
    a fix-red cycle. Zero is the most common value a verification card proves, so this dropped
    precisely the strongest evidence. The rule is now ONE: omit only an ABSENT value (`None`);
    render every other value literally."""
    lines = []
    for ev in evidence_events:
        d = ev.get("data") or {}
        detail = ", ".join(f"{k}: {v}" for k, v in d.items()
                           if k not in _EVIDENCE_NOISE_KEYS and v is not None)
        lines.append(f"- `{ev.get('type')}` @ {ev.get('ts')} (subject: {ev.get('task_id')}) — "
                     f"{detail or '(no data fields)'}")
    return "\n".join(lines)


def _format_type_optin_exclusion_note(excluded_types) -> str:
    """T-10827 (X-0686, <project>) — the REPORT-ONLY note that makes a type-opt-in exclusion legible.

    A CONSUMER-defined event type reaches this packet only through the T-10708 CONJUNCTION: the
    audited card's acceptance TEXT names the type AND the row is task_id-tied. When the acceptance
    names no type, the reader dropped the row silently and this section rendered EMPTY — byte-
    identical to the healthy "no evidence recorded yet" case. The auditor then REDs a criterion that
    IS satisfied on disk, and nothing on the path fails closed; <project> burned an audit pass plus a
    full convergence consult discovering the difference by trial.

    So the note states the ONE fact the empty section could not: rows tied to this task exist, and
    they are EXCLUDED — naming the types and the opt-in route out of the exclusion. It is
    REPORT-ONLY: it renders no row, changes no verdict, no gate and no counted set. It is NOT a
    widening — the fold is untouched and the tenth per-type whitelist entry is still not taken
    (T-10708 closed that route after nine — `lessons/a-widening-log-means-invert-the-whitelist.md`).
    Widening the fold is an owner decision, captured separately.

    Returns "" for an empty/absent set, so the section is byte-identical when nothing was excluded —
    the note is a real discriminator, not an unconditional decoration (the SPEC-0168 rule 4 shape)."""
    types = sorted(t for t in (excluded_types or ()) if t)
    if not types:
        return ""
    named = ", ".join(f"`{t}`" for t in types)
    return (
        "\n\nNOTE — EVENT TYPE(S) EXCLUDED BY THE CARD OPT-IN, NOT ABSENT FROM THE JOURNAL "
        "(T-10708 / SPEC-0168):\n"
        f"the journal DOES carry row(s) tied to this task id whose event type is {named}. They are\n"
        "NOT rendered above, and their absence is an EXCLUSION, not a lack of evidence — do NOT read\n"
        "this section as 'no evidence exists' for a criterion those rows would prove.\n"
        "WHY: a type no kernel evidence class defines (e.g. one a CONSUMER project invented) renders\n"
        "only under a CONJUNCTION — the audited card's own ACCEPTANCE TEXT must NAME the event type\n"
        "verbatim AND the row must be task_id-tied. This card's acceptance names none of the types\n"
        "above, so the opt-in half is unmet. A task_id tie ALONE never folds a row: SPEC-0168 rule 2\n"
        "makes the tie NECESSARY, not sufficient.\n"
        "ROUTE: to have such a row rendered, the card's acceptance text must name its event type.\n"
        "That is a CARD edit, not an engine change — and it is not a defect in what you are auditing."
    )


def packet_optin_exclusion_line(excluded_types) -> str:
    """T-13508 (GitHub intake, issue #10) — the ONE LINE `audit post` prints (stderr) naming the task-tied
    event types the packet EXCLUDED by the card opt-in. The in-packet note above tells the AUDITOR;
    until this line nothing told the person RUNNING the audit, who is the one able to act on it.

    Same input as `_format_type_optin_exclusion_note` (the set the packet builder collected on its
    single pass), same emptiness rule: "" for an empty/absent set, so a run with nothing excluded
    prints nothing. Report-only — no verdict, gate, exit code or counted set reads it."""
    types = sorted(t for t in (excluded_types or ()) if t)
    if not types:
        return ""
    return ("# audit packet: task-tied event type(s) EXCLUDED from the evidence section — the card's "
            "acceptance does not name them (T-10708 / SPEC-0168 rule 7): " + ", ".join(types)
            + ". Rows of these types were NOT shown to the auditor; to have them rendered, name the "
              "type in the card's acceptance text.")


def _format_sandbox_evidence_exclusion_note(excluded) -> str:
    """T-12454 — the REPORT-ONLY note naming each sandbox lifecycle row the fold EXCLUDED, with its
    reason (the X-0686 loud-exclusion shape): a dangling `evidence_ref` or an `ok: false` run must never
    read like an absent row. Returns "" when nothing was excluded, so the packet is byte-identical then."""
    rows = [r for r in (excluded or ()) if isinstance(r, tuple) and len(r) == 2]
    if not rows:
        return ""
    lines = ["", "",
             "NOTE — SANDBOX LIFECYCLE ROW(S) EXCLUDED FROM EVIDENCE (T-12454 / SPEC-0161):",
             "the journal carries row(s) of the sandbox lifecycle vocabulary tied to this task that are NOT",
             "rendered above — each failed the evidence rule (payload valid, `ok: true`, `evidence_ref` resolves):"]
    for ev, reason in rows:
        d = ev.get("data") if isinstance(ev.get("data"), dict) else {}
        lines.append(f"- `{ev.get('type')}` @ {ev.get('ts')} (evidence_ref: {d.get('evidence_ref')!r}) — {reason}")
    lines.append("Do NOT read such a row as proof: a criterion it would prove stays unproven until a row passes.")
    return "\n".join(lines)


def stage6_rows_since_claim(rows, *, max_rows: int = STAGE6_MAX_ROWS):
    """T-13538 — WHICH task-tied `tests_passed` rows the Stage-6 section shows.

    `rows` are the task-tied `task_picked` + `tests_passed` rows in JOURNAL ORDER. The window opens
    at the card's CURRENT claim — the LAST `task_picked` row — so a run recorded under an earlier
    claim (a parked, discarded attempt) is not presented as this build's evidence. No claim row at
    all means NO window and every row is in it (the T-12337 "None = no window" precedent). Journal
    ORDER, not `ts`: the reader already returns the rows in append order, and a second ISO parser in
    this leaf would be the drift CHARTER P1 F1 forbids.

    Returns `(shown, omitted_older, pre_claim)`: the newest `max_rows` rows of the window, oldest
    first; how many OLDER window rows the row bound dropped; how many rows precede the claim. The
    two counts exist so the section can STATE what it does not show (SPEC-0165). Pure f(rows)."""
    claim_at, tests = -1, []
    for i, ev in enumerate(rows or ()):
        if not isinstance(ev, dict):
            continue
        if ev.get("type") == "task_picked":
            claim_at = i
        elif ev.get("type") == "tests_passed":
            tests.append((i, ev))
    window = [ev for i, ev in tests if i > claim_at]
    omitted_older = max(0, len(window) - max(1, int(max_rows)))
    return window[omitted_older:], omitted_older, len(tests) - len(window)


def stage6_evidence_section(shown, omitted_older: int, pre_claim: int, *, churn_note: str = "",
                            yaml_dump_block, keep_within_budget) -> str:
    """T-13538 — the body of `### Stage-6 test evidence`: every shown row, oldest first, the WHOLE
    section bounded in UTF-8 BYTES.

    Earlier rows are one line each (`- @ <ts>: <evidence>`); the LATEST row keeps the three-part form
    this section always had (header, `evidence:`, `acceptance-at-test:`), so a card with one row that
    fits its budget renders BYTE-IDENTICAL to the pre-T-13538 section. Every segment is bounded
    through `keep_within_budget` — the ONE budget-accounting primitive (bytes, multibyte-safe) — and
    every cut carries a visible marker, because this heading is PROTECTED from the total packet bound
    and an unmarked omission reads as content that was never there.

    A VIEW, never a trigger (lessons/scope-the-trigger-not-the-view): nothing here is counted
    evidence — the rows never enter `evidence_sink` or any gate. Pure f(rows); no journal, no I/O."""
    def _b(text: str) -> int:
        return len(text.encode("utf-8", "replace"))

    def _bounded(label: str, text: str, max_bytes: int) -> str:
        if _b(text) <= max_bytes:
            return text                                  # untouched: the byte-identical path
        lines = text.split("\n")
        kept, kept_b, _cut = keep_within_budget(lines, len(lines), max_bytes)
        return "\n".join(kept + [_packet_elision_marker(label, len(kept), len(lines), kept_b, _b(text) + 1)])

    def _ts(ev) -> str:
        ts = str(ev.get("ts"))
        return ts if _b(ts) <= 64 else ts[:40]           # a journal `ts` is ~20 bytes; never unbounded

    notes = ""
    if pre_claim > 0:
        notes = (f"\n\nNOTE (T-13538) — {pre_claim} task-tied `tests_passed` row"
                 f"{'' if pre_claim == 1 else 's'} recorded BEFORE this task's current claim "
                 f"{'is' if pre_claim == 1 else 'are'} EXCLUDED from this section: a run recorded under an\n"
                 "earlier claim of the card is not this build's evidence. Excluded, not absent from the journal.")
    if not shown:
        return ("(no `tests_passed` event recorded for this task — verify Stage-6 evidence via the\n"
                "shipped diff / commit context; its absence here is not itself a finding per D-0043)" + notes)
    earlier, tp = list(shown[:-1]), shown[-1]
    head = ""
    if earlier or omitted_older > 0:
        out = [f"task-tied `tests_passed` rows since this task's claim, oldest first — "
               f"{len(shown) + omitted_older} recorded (T-13538). The LAST row is the latest and is rendered in full:"]
        if omitted_older > 0:
            out.append(f"… {omitted_older} older row(s) since the claim are not shown (row bound {STAGE6_MAX_ROWS}) — "
                       "they EXIST in the journal; bounded here, it is NOT absent evidence")
        for ev in earlier:
            data = ev.get("data") if isinstance(ev.get("data"), dict) else {}
            evidence = " ".join(part.strip() for part in str(data.get("evidence")).splitlines() if part.strip())
            out.append(_bounded(f"earlier tests_passed row @ {_ts(ev)}",
                                f"- @ {_ts(ev)}: {evidence}", STAGE6_EARLIER_ROW_MAX_BYTES))
        head = "\n".join(out) + "\n"
    ev = tp.get("data") if isinstance(tp.get("data"), dict) else {}
    latest = (f"recorded `tests_passed` event @ {_ts(tp)}:\n"
              + _bounded("latest tests_passed evidence", f"evidence: {ev.get('evidence')}",
                         STAGE6_LATEST_EVIDENCE_MAX_BYTES) + "\n"
              + _bounded("latest tests_passed acceptance-at-test",
                         f"acceptance-at-test: {yaml_dump_block(ev.get('acceptance') or [])}",
                         STAGE6_LATEST_ACCEPTANCE_MAX_BYTES))
    section = head + latest + (churn_note or "") + notes
    # The belt: the segment budgets already sum under the section budget, but the whole is what the
    # protected heading has to guarantee — so the assembled section is bounded once more, as a unit.
    return _bounded("Stage-6 test evidence section", section, STAGE6_SECTION_MAX_BYTES - 400)


def _format_window_exclusion_note(excluded_count: int) -> str:
    """T-12337 — the REPORT-ONLY line that makes the CARD-WINDOW exclusion legible (SPEC-0165).

    `_ac_probe_evidence_events_for` admits a `spec_edited` / `spec_reverified` row only when its `ts`
    is at or after the audited card's own filing instant. That narrowing is CORRECT — a spec edit
    recorded before the card existed is another card's corpus maintenance, never this card's adoption
    evidence — but silently it is indistinguishable from the healthy "the corpus has no such rows"
    case, which is exactly the reading failure SPEC-0165 exists to forbid: a shrunken section and an
    empty one must not look alike to the auditor.

    So the note states the one fact the shrunken section cannot: rows for the cited/touched specs DO
    exist in the journal, and they are EXCLUDED for a stated reason rather than absent. Pure f(int) —
    no journal, no store, no I/O.

    Returns "" for a zero/absent count, so the section is BYTE-IDENTICAL when the window excluded
    nothing (the `_format_type_optin_exclusion_note` shape it is modelled on, and the SPEC-0168 rule-4
    discipline: a mark that always renders is decoration, not a discriminator).

    REPORT-ONLY: it renders no row, changes no verdict, no gate, and no counted set — the excluded
    rows are outside the SPEC-0168 rule-5 counted `evidence_sink` too, because they never folded."""
    try:
        n = int(excluded_count or 0)
    except (TypeError, ValueError):      # noqa: BLE001 — an uncountable input renders nothing
        return ""
    if n <= 0:
        return ""
    rows = "row" if n == 1 else "rows"
    return (
        "\n\nNOTE — SPEC-LIFECYCLE ROW(S) EXCLUDED BY THIS CARD'S OWN WINDOW, NOT ABSENT FROM THE "
        "JOURNAL (T-12337 / SPEC-0168):\n"
        f"{n} spec-lifecycle {rows} before this card's filing excluded.\n"
        "WHAT THAT MEANS: the journal DOES carry `spec_edited` / `spec_reverified` rows for the specs\n"
        "this card cites or whose files its diff touches, dated BEFORE the card was filed. They are\n"
        "NOT rendered above. Their absence is an EXCLUSION, not a lack of evidence — do NOT read this\n"
        "section as 'the corpus is empty' or as an adoption gap on that ground.\n"
        "WHY: a spec edit or re-verification recorded before this card existed is another card's\n"
        "corpus maintenance; it cannot be THIS card's adoption evidence. Admitting it made the section\n"
        "scale with the AGE OF THE CORPUS instead of with the change under audit, which twice made the\n"
        "packet too large for you to answer at all (T-11319 refused 3/3, T-12320 no-outcome 2/2).\n"
        "UNAFFECTED: every row tied to this card by `task_id` is folded regardless of its date — the\n"
        "window bounds the spec-subject class alone, which is the one class with no task tie."
    )


def p8_carrier_ids_in_section(section, *, _P8_CARRIER_ROW_PREFIX) -> list:
    """T-12009 — the carrier ids a rendered third-satisfier block names, read back off THAT block.

    PURE f(str) — no journal, no store, no I/O. A VIEW over the string the packet already built
    (CHARTER §P1 F2: a view, not a second fold), so the readiness row can NAME which carrier
    satisfied the criterion without re-reading the followups the body already read. Anything
    falsy — "" (no carrier qualified) or None (the block was never rendered, e.g. audit-pre) —
    reads as no ids, which is the same answer as an empty render: no carrier is claimed."""
    out = []
    for line in str(section or "").splitlines():
        if line.startswith(_P8_CARRIER_ROW_PREFIX):
            rest = line[len(_P8_CARRIER_ROW_PREFIX):].strip().split()
            if rest:
                out.append(rest[0])
    return out


def _is_main_guard(test) -> bool:
    """T-11778 audit-post finding — the guard is the module's ENTRY POINT, and ONLY
    `__name__ == "__main__"` (either operand order) is one.

    The first cut asked `"__name__" in ast.dump(n.test)`, which also matched
    `if __name__ != "__main__":` and every other incidental mention — so a module could be
    reported with a runner it does not have. That is the exact inversion of this card's purpose:
    the whole point is to hand the auditor a fact it can TRUST, and a fact that can be wrong in
    the "wired" direction is worse than no fact, because it launders a genuinely unwired arm.
    Anything that is not this shape falls through to `no-in-file-runner`, which is the
    fail-closed answer."""
    if not isinstance(test, ast.Compare) or len(test.ops) != 1 or len(test.comparators) != 1:
        return False
    if not isinstance(test.ops[0], ast.Eq):
        return False

    def _dunder(n):
        return isinstance(n, ast.Name) and n.id == "__name__"

    def _main(n):
        return isinstance(n, ast.Constant) and n.value == "__main__"

    left, right = test.left, test.comparators[0]
    return (_dunder(left) and _main(right)) or (_main(left) and _dunder(right))


def _collector_shape_for_source(src: str, *, _is_main_guard) -> "dict | None":
    """Derive HOW a python test file collects the test functions its own `__main__` runs. Pure
    f(source) — no I/O, no journal, no store.

    RUNNER-ROOTED, and that is the whole point (both audit-pre RED findings, T-11778 pass 1). An earlier
    draft scanned the WHOLE module on both axes and was over-broad in both directions: any mention of a
    name anywhere read as "wired" (so a genuinely-omitted arm mentioned in a docstring or in another
    test's body would have been laundered as wired), and any `globals()` call anywhere read as
    auto-discovery even when unrelated to the runner. Both are fixed by computing a RUNNER CLOSURE first
    and asking every question strictly inside it.

    The closure starts at the module-level `if __name__ == "__main__":` block and transitively pulls in
    (a) module-level FUNCTIONS whose name the closure references — the `main()` / `_run()` indirection —
    and (b) module-level ASSIGNMENT VALUES whose target name the closure references, which is the
    `TESTS = [...]` idiom that lives OUTSIDE the block and that a block-only scan misses (measured: real
    files in this repo, e.g. tests/test_spec0178_cases_carrier_and_preconditions.py). Anything outside
    that closure is not evidence of wiring.

    Returns None when the file defines no module-level `test_`-prefixed function (nothing to say), else
    a dict with:
      `shape`   — "no-in-file-runner" when there is no `__main__` block at all (the file makes no in-file
                  wiring claim either way, and NOTHING is asserted about its arms), else "in-file-runner".
      `dynamic` — FACT A: a `globals()`/`vars()`/`dir()`/`locals()` call occurs INSIDE the closure, so a
                  `test_`-prefixed function is collected by the act of defining it. None when no runner.
      `defined` — every module-level `test_`-prefixed function name, sorted.
      `unnamed` — FACT B: the defined names NOT referenced inside the closure (as an ast.Name, an
                  attribute, or a string constant).

    TWO ORTHOGONAL FACTS, never one forced label: a real file can do BOTH — tests/test_views.py after
    T-11728 carries a hand-maintained list AND a `globals()` completeness guard — and collapsing them into
    a single classification would hide one of them and launder it as the other."""
    try:
        tree = ast.parse(src)
    except (SyntaxError, ValueError, RecursionError):
        return None
    defs, assigns = {}, {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            defs[node.name] = node
        elif isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name):
                    assigns[tgt.id] = node.value
    defined = sorted(n for n in defs if n.startswith("test_"))
    if not defined:
        return None
    blocks = [n for n in tree.body
              if isinstance(n, ast.If) and _is_main_guard(n.test)]
    if not blocks:
        return {"shape": "no-in-file-runner", "dynamic": None,
                "defined": defined, "unnamed": []}
    closure, seen, i = list(blocks), set(), 0
    while i < len(closure):          # transitive; bounded by the module's own def/assign count
        for node in ast.walk(closure[i]):
            if isinstance(node, ast.Name) and node.id not in seen:
                seen.add(node.id)
                # Expand the runner SCAFFOLDING only — `main()`/`_run()` helpers and module-level list
                # bindings. NEVER descend into a `test_`-prefixed function's own BODY: calling a test
                # makes THAT test named (its ast.Name is already inside the closure), but a test's body
                # is not collector wiring, and treating it as such is how a genuinely-omitted arm gets
                # laundered as wired — a cross-reference in a sibling test ("see test_newly_added") or
                # a helper reached only from a test body would otherwise count. Both failure modes
                # measured against this card's own fixtures before the fix.
                if node.id in defs and not node.id.startswith("test_"):
                    closure.append(defs[node.id])
                elif node.id in assigns:
                    closure.append(assigns[node.id])
        i += 1
    dynamic = any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                  and n.func.id in _COLLECTOR_DISCOVERY_CALLS
                  for c in closure for n in ast.walk(c))
    named = set()
    for c in closure:
        for n in ast.walk(c):
            if isinstance(n, ast.Name):
                named.add(n.id)
            elif isinstance(n, ast.Attribute):
                named.add(n.attr)
            elif isinstance(n, ast.Constant) and isinstance(n.value, str):
                named.add(n.value)
    # The two facts are computed INDEPENDENTLY and both are always returned (T-11778 audit-post RED,
    # high). An earlier revision returned `unnamed: []` whenever `dynamic` was true, which collapsed
    # the two orthogonal facts back into ONE exclusive classification — the exact thing this docstring
    # says it does not do — and would have hidden a static omission in a file that ALSO does a dynamic
    # lookup. Callers must read `unnamed` in the light of `dynamic`: under dynamic collection an
    # unreferenced name is the NORMAL shape and carries no defect implication, because the collector
    # selects it out of globals() regardless. That interpretation is the RENDERER's job, not a reason
    # to suppress the datum here.
    return {"shape": "in-file-runner", "dynamic": dynamic, "defined": defined,
            "unnamed": [n for n in defined if n not in named]}


def _format_collector_shape_note(touched_test_paths, repo_root, *, _collector_shape_for_source) -> str:
    """T-11778 — the REPORT-ONLY per-touched-test-file collector-shape note appended to the packet's
    diff-invisible evidence section.

    Returns "" when the shipped diff touches no readable `tests/*.py` — so the packet is BYTE-IDENTICAL
    when the section does not apply, making the note a real discriminator rather than an unconditional
    decoration (SPEC-0168 rule 4, the shape `_format_type_optin_exclusion_note` already takes). Bounded
    by `_COLLECTOR_FACT_MAX_FILES` / `_COLLECTOR_FACT_MAX_NAMES` — ONE derived fact per touched test
    file, NEVER the file body: the T-11727 packet already ran 279KB / ~70k tokens, and dumping sources
    would make every packet worse to buy one fact.

    Report-only in the strict sense: it renders no evidence row and changes no verdict, no gate and no
    counted set."""
    entries = []
    for path in list(touched_test_paths)[:_COLLECTOR_FACT_MAX_FILES]:
        try:
            src = (Path(repo_root) / path).read_text(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            continue                 # unreadable in this checkout -> say nothing about it
        facts = _collector_shape_for_source(src)
        if not facts:
            continue
        total = len(facts["defined"])
        if facts["shape"] == "no-in-file-runner":
            entries.append(
                f"- `{path}` — {total} `test_`-prefixed function(s) defined; there is NO module-level\n"
                f"  `{_MAIN_GUARD_LITERAL}` runner in this file, so the file makes no in-file wiring\n"
                "  claim either way and NOTHING is asserted here about whether its arms run.")
        elif facts["dynamic"]:
            # BOTH facts are rendered for the same file, never one instead of the other. Under dynamic
            # collection the not-also-referenced COUNT is reported with its correct meaning (expected,
            # no defect implication) rather than suppressed — suppressing it is what the audit-post RED
            # caught, and listing the names as accusations would be the opposite error.
            n_unnamed = len(facts["unnamed"])
            if n_unnamed:
                also = (f" Of those, {n_unnamed} are not ALSO referenced by name inside that runner\n"
                        "  closure — under dynamic collection that is the NORMAL shape and carries NO\n"
                        "  defect implication, since the collector selects them out of `globals()`\n"
                        "  regardless of any list.")
            else:
                also = ("  Every defined name is ALSO referenced by name inside that runner closure,\n"
                        "  so this file collects dynamically AND enumerates explicitly.")
            entries.append(
                f"- `{path}` — {total} `test_`-prefixed function(s) defined. COLLECTION IS DYNAMIC: the\n"
                "  runner reachable from this file's `__main__` calls `globals()`/`vars()`/`dir()`/\n"
                "  `locals()` and selects `test_`-prefixed names out of it, so a newly added function is\n"
                "  collected BY THE ACT OF DEFINING IT — there is no list for it to be added to, and the\n"
                "  collector is correspondingly unchanged and absent from the diff." + also)
        elif not facts["unnamed"]:
            entries.append(
                f"- `{path}` — {total} `test_`-prefixed function(s) defined; collection is STATIC (no\n"
                "  dynamic lookup in the runner reachable from `__main__`), and EVERY defined name IS\n"
                "  referenced inside that runner closure.")
        else:
            unnamed = facts["unnamed"]
            shown = unnamed[:_COLLECTOR_FACT_MAX_NAMES]
            more = "" if len(unnamed) <= len(shown) else f" (+{len(unnamed) - len(shown)} more)"
            names = ", ".join(f"`{n}`" for n in shown)
            entries.append(
                f"- `{path}` — {total} `test_`-prefixed function(s) defined; collection is STATIC, and\n"
                f"  {len(unnamed)} defined name(s) are NOT referenced anywhere in the runner closure:\n"
                f"  {names}{more}. Treat this as a REAL signal to investigate, not as noise.")
    if not entries:
        return ""
    return (
        "\n\nCOLLECTOR SHAPE OF THE TEST FILE(S) THIS DIFF TOUCHES (T-11778) — a DERIVED fact the diff\n"
        "STRUCTURALLY CANNOT SHOW YOU:\n"
        "a card that adds a test function to an EXISTING test file does not modify that file's collector,\n"
        "so the collector is absent from the diff above BY CONSTRUCTION. Its absence is therefore NOT\n"
        "evidence that a newly added test is unwired. The facts below are read from each file AS IT IS IN\n"
        "THE AUDITED CHECKOUT (not from the diff):\n\n"
        + "\n".join(entries) +
        "\n\nHOW TO USE THIS — and its LIMITS, which are why it is stated as a fact and never as a verdict:\n"
        "  - It removes exactly ONE inference and no other: 'the collector is not in the diff, THEREFORE\n"
        "    the new arm is unwired'. Do NOT read it as clearance on wiring generally.\n"
        "  - 'Referenced in the runner closure' is NOT 'actually executed'. A hardcoded pass count, a\n"
        "    runner that iterates a list it then ignores, or a guard that never fires ALL still render as\n"
        "    referenced here. That is exactly what tests/test_views.py was — a hardcoded '16/16 passed'\n"
        "    while 17 functions ran (the T-10097 false-GREEN class, fixed under T-11728) — so KEEP ASKING\n"
        "    the wiring question on every ground other than diff-absence.\n"
        "  - 'Dynamic collection' describes the collector reachable from this file's `__main__`; it is not\n"
        "    a warranty that any arm PASSED, nor that the suite runner is this file's `__main__`.\n"
        "  - A file listed with NOT-referenced names is a genuine finding candidate: two files in this\n"
        "    repo are real omissions of exactly that class. Judge it; this section never judges for you."
    )


def _amend_notes_since(notes, since: "str | None", *, _parse_iso_ts) -> "list[str]":
    """T-11733 — the amend_notes entries written STRICTLY AFTER a prior audit pass.

    `notes` is the card's `amend_notes:` list, whose entries `cmd_task_update` writes as
    `f"{_utc_now_iso()} \u2014 {note}"` — an ISO-8601 UTC token, a separator, then the note text. Only
    the LEADING token is parsed, so the separator itself is never load-bearing here. `since` is the prior
    audit record's `audited_at`, the same shape. Only the entries that post-date it are returned: that
    differential is what keeps the re-audit prompt budget FLAT as a card accumulates amendments, and it
    is the whole reason this renders in the pass-N>=2 section rather than in the packet body.

    FAIL-CLOSED on both edges, matching `_parse_iso_ts`'s documented convention in this module:
      - an absent / unparseable `since` returns [] — the whole amendment history is NEVER dumped;
      - an entry whose own leading token will not parse is EXCLUDED — it cannot be PROVEN to
        post-date the prior pass, and a permissive default here is exactly the budget regression the
        differential exists to avoid.
    Pure; no I/O."""
    if not isinstance(notes, list) or not notes:
        return []
    since_at = _parse_iso_ts(since)
    if since_at is None:
        return []
    out = []
    for entry in notes:
        if not isinstance(entry, str) or not entry.strip():
            continue
        entry_at = _parse_iso_ts(entry.split(" ", 1)[0])
        if entry_at is not None and entry_at > since_at:
            out.append(entry)
    return out


def parse_resolution_note(text: "str | None") -> "dict | None":
    """T-11979 — parse a worker-authored resolution note (SPEC-0036 §Monotonic per-pass re-audit).

    Grammar: `RESOLVED <finding-index>: <text> | CHECK: <text> | OUTPUT: <text>` — the literal
    `RESOLVED`, a decimal 1-based index into the PRIOR verdict's findings order, then the three
    `|`-separated fields in that order. Returns
    `{"index": int, "text": str, "check": str, "output": str}` on a match, else None.

    The three fields carry the author's CLAIM, the CHECK that would settle it, and the OUTPUT the
    author recorded from running it. This function NEVER runs the check — it only reads text (the
    packet assembler must not execute worker-authored commands; the auditor reads the recorded
    output). Pure, no I/O, never raises: a non-string, an unprefixed note, a missing field or a
    non-numeric index all return None, and the caller renders the entry unstructured plus a
    diagnostic. `<text>` fields may span lines; only the FIRST `| CHECK:` / `| OUTPUT:` separators
    are structural (the non-greedy groups), so a `|` inside the trailing OUTPUT is preserved."""
    if not isinstance(text, str):
        return None
    m = _RESOLUTION_NOTE_RE.match(text.strip())
    if not m:
        return None
    try:
        idx = int(m.group(1))
    except (TypeError, ValueError):   # unreachable via the \d+ group; fail-closed regardless
        return None
    if idx < 1:
        return None
    return {"index": idx, "text": m.group(2).strip(),
            "check": m.group(3).strip(), "output": m.group(4).strip()}


def _md_cell(text: "str | None", limit: int = 300) -> str:
    """T-11979 — one markdown TABLE CELL: flattened to a single line, pipe-escaped, length-bounded.

    A cell is rendered inside a `|`-delimited row, so an un-escaped `|` or a newline in author or
    finding text would silently break the table the auditor is asked to read row-by-row. Bounded
    because a finding's `what` can run long and the table is an INDEX into the verbatim text rendered
    elsewhere in the same section, never a replacement for it. Pure."""
    t = " ".join(str(text or "").split())
    if len(t) > limit:
        t = t[:limit - 1].rstrip() + "\u2026"
    return t.replace("\\", "\\\\").replace("|", "\\|") or "\u2014"


def _format_monotonic_reaudit_section(prior_record: "dict | None", stage: str,
                                      cur_plan: "str | None", cur_diff: "str | None",
                                      amend_notes=None, *, delta_discipline: bool = False, _amend_note_body, _amend_notes_since, _is_no_data_prior, _md_cell, _passes_recorded, parse_resolution_note) -> str:
    """T-9681 — the MONOTONIC per-pass re-audit section (SPEC-0036 §Monotonic per-pass re-audit prompt).

    Rendered ONLY on pass N>=2 — i.e. when a prior saved audit record exists for this target+stage
    (`prior_record` carries a usable prior `verdict`); returns "" otherwise (pass 1). It makes a
    re-audit MONOTONIC: the auditor's FIRST task is to mark each PRIOR finding resolved/not-resolved
    against the CURRENT plan/diff, and only THEN may it raise a genuinely-NEW finding — killing the
    fresh-survey / goalpost-shift that structurally guarantees the audit-loop ceiling (X-0134 RC1a).
    It NEVER blinds the auditor: a genuinely-new REAL defect still surfaces + still blocks (the plan's
    constraint #2). The caller places this section BEFORE the fresh-survey overlay/body so the
    account-for-prior gate is read first.

    The DELTA block renders the FROM endpoint (the prior artifact IDENTITY from the prior audit input —
    `plan_fingerprint` for pre, `commit` sha for post) and, when the prior artifact TEXT is carried by
    the caller (`prior_record['_audited_diff']`, the post case), a COMPUTED line-level unified diff
    against the current artifact; otherwise it FRAMES the current plan/diff (in the body below) as the
    TO endpoint to judge the prior findings against. (Audit-pre has no stored prior-plan text, so it
    always takes the framing path — documented asymmetry, no new store.)

    T-11733 — the section ALSO renders the card's `amend_notes:` entries written since the prior pass
    (`_amend_notes_since`), framed as the author's answers to weigh, never as an automatic resolution.
    Differential by construction, so a card accumulating amendments does not grow the prompt.

    T-12288 / SPEC-0204 rule 8 — `delta_discipline` (TASK audit-pre/post only) makes this section the
    BELOW-CEILING DELTA OVERLAY rule 8 asks for. This section already IS the pass-N>=2 seam — it
    renders exactly when a prior record carries a verdict — so the round-awareness the SPEC-0200
    consult engine holds above the ceiling MOVES onto it rather than importing
    `consult_prompt_overlay`, whose delta text is EPISODE-scoped (frozen `B<n>` ids, the withdrawn
    block): those are precisely what SPEC-0204 rule 6 RETIRES, so calling it here would ship the
    retirement's own subject below the ceiling. Two additions, both flag-gated so a plan target and
    every existing caller render byte-identically:
      (a) each prior finding carries its ENGINE `fingerprint:` (C1 writes it onto every RED record's
          findings), because rule 1 makes that the ONLY identity by which the auditor's echo is
          matched to a prior finding — a re-DESCRIBED finding changed its key on 3 of 5 trial cards;
      (b) a closing block that scopes the pass to closure + regression «and nothing else» and REQUIRES
          `causality:` on every finding that is not one of those listed. Without (b) the record seam
          could not tell a regression from a late finding, and rule 8 fails CLOSED there (an absent
          causality counts at severity) — so the ASK is what makes the honest answer available at all.
    """
    if not isinstance(prior_record, dict) or _is_no_data_prior(prior_record):
        return ""   # T-12465 — a NO-DATA run (SPEC-0173 rule 1) is not a prior pass: fresh survey
    prior_verdict = str(prior_record.get("verdict") or "").strip()
    if not prior_verdict:
        return ""   # no usable prior outcome → pass 1 / unparseable: omit the section (fail-closed)
    try:
        # T-10951 — the pass LABEL reads what the record holds: a ledger-skipped prior renders
        # "pass 0", which is truthful (that attempt consumed no ceiling pass) rather than announcing
        # a phantom "pass 1" the ledger never counted. Cosmetic surface — no gate reads it.
        prior_pass_n = _passes_recorded(prior_record)
    except (ValueError, TypeError):
        prior_pass_n = 1
    if stage == "post":
        # T-11580 — READ THE RANGE BACK, not just the custody sha. This is the FROM endpoint of the
        # delta the next pass is judged against, so "commit <sha>" alone told the auditor how far the
        # prior sign-off REACHED while reading as what it JUDGED — the same conflation the record
        # itself carried (X-1108). When the prior record carries the pair, name the range beside the
        # sha; when it does not (a legacy record written before this field existed), render exactly
        # today's text — no fabricated range, no "(unrecorded)" noise on records that predate it.
        from_id = f"commit {prior_record.get('commit') or '(unrecorded)'}"
        _abase, _afiles = prior_record.get("audited_base"), prior_record.get("audited_files")
        if _abase and isinstance(_afiles, int):
            from_id += (f" (judged range {str(_abase)[:7]}.."
                        f"{str(prior_record.get('commit') or '')[:7]}, {_afiles} file(s))")
    else:
        from_id = f"plan_fingerprint {prior_record.get('plan_fingerprint') or '(unrecorded)'}"
    # (b) inline the PRIOR FINDINGS verbatim (what / where / prior-fix).
    prior_findings = prior_record.get("findings")
    if isinstance(prior_findings, list) and prior_findings:
        fl = []
        for i, f in enumerate(prior_findings, 1):
            if isinstance(f, dict):
                # T-12288 (rule 8(a)) — the engine fingerprint, rendered ONLY under
                # `delta_discipline` and ONLY when the record actually carries one. A record from
                # before C1, or a non-RED one, has none: the line is then OMITTED rather than
                # rendered `(none)`, because an auditor told to reference an identity that does not
                # exist would invent one.
                _fp = f.get("finding_fingerprint") if delta_discipline else None
                fl.append(f"  [{i}] ({f.get('severity', '?')}) {f.get('what', '')}\n"
                          + (f"      fingerprint: {_fp}\n" if _fp else "")
                          + f"      where: {f.get('where', '')}\n"
                          f"      prior-fix: {f.get('fix', '')}")
            else:
                fl.append(f"  [{i}] {f}")
        findings_block = "\n".join(fl)
    else:
        findings_block = ("  (the prior pass recorded NO findings — confirm the prior verdict still "
                          "holds against the current plan/diff; raise a finding ONLY if a genuinely-new "
                          "REAL defect appears.)")
    # (b2) T-11733 — the AMENDMENTS the author recorded SINCE the prior pass. `task update --note` is
    # the governed route for answering a finding, but it writes `amend_notes:` — which the packet did
    # not render, so an answered finding came back verbatim as "Prior finding N NOT-RESOLVED" and the
    # auditor was not disagreeing, it never saw the answer (<project> T-0521, X-1182). Rendered HERE —
    # immediately after the prior findings, before the delta — because this is the seam those answers
    # were written for. DIFFERENTIAL by construction (`_amend_notes_since`), so the budget stays flat.
    amend_since = _amend_notes_since(amend_notes, prior_record.get("audited_at"))
    # (b3) T-11979 — the RESOLUTION ROWS. Over the SAME differential cut (never widened), an entry
    # whose note body matches the `RESOLVED <i>: … | CHECK: … | OUTPUT: …` grammar is aligned to prior
    # finding `i` and rendered as a table row, so the auditor judges ONE recorded check per finding
    # instead of re-surveying it. A `RESOLVED`-prefixed entry that will not parse, or that names an
    # index outside the prior findings, is NEVER dropped and NEVER a refusal: it renders unstructured
    # exactly as before, plus ONE diagnostic line naming it and the expected shape.
    _n_prior = len(prior_findings) if isinstance(prior_findings, list) else 0
    resolutions, malformed = {}, []
    for _entry in amend_since:
        _body = _amend_note_body(_entry)
        _parsed = parse_resolution_note(_body)
        if _parsed and 1 <= _parsed["index"] <= _n_prior:
            # a later entry for the same finding supersedes an earlier one — amend_since is chronological
            resolutions[_parsed["index"]] = _parsed
        elif _body.startswith("RESOLVED"):
            malformed.append((_entry, _parsed))
    # The table renders whenever the author reached for the grammar at all — including when the
    # ONLY such entry failed to parse. That is deliberate: a row reading `(no resolution
    # recorded)` is the honest, visible consequence of the malformed note, where suppressing the
    # whole table would hide it. A pass carrying no resolution-shaped entry renders no table.
    if _n_prior and (resolutions or malformed):
        _rows = []
        for _i, _f in enumerate(prior_findings, 1):
            _what = _f.get("what", "") if isinstance(_f, dict) else _f
            _r = resolutions.get(_i)
            if _r:
                _rows.append(f"| {_i} | {_md_cell(_what, 160)} | {_md_cell(_r['text'])} | "
                             f"{_md_cell(_r['check'])} | {_md_cell(_r['output'])} |")
            else:
                _rows.append(f"| {_i} | {_md_cell(_what, 160)} | (no resolution recorded) "
                             f"| \u2014 | \u2014 |")
        resolution_block = (
            "### Recorded resolutions per prior finding \u2014 JUDGE THESE CHECKS FIRST\n"
            "The author recorded, through the same governed amendment route, a resolution claim for\n"
            "the prior findings below: what they assert, the CHECK that settles it, and the OUTPUT they\n"
            "recorded from running that check. For every row carrying one, judge THAT CHECK FIRST —\n"
            "before re-reading the finding at large. It is the cheapest decisive test available to you\n"
            "and it is what makes this pass converge instead of re-surveying settled ground.\n"
            "THE ENGINE DID NOT RUN THE CHECK. The OUTPUT column is the AUTHOR'S RECORDED READING, not\n"
            "a verified fact: weigh it as evidence, re-run or re-derive the check yourself when the\n"
            "packet lets you, and say so plainly if it does not hold. A recorded resolution is NOT, by\n"
            "itself, a resolution \u2014 a finding whose CONDITION is still unmet STILL blocks (verdict !=\n"
            "GREEN) however the row argues. A row reading `(no resolution recorded)` carries no claim\n"
            "either way: judge that finding on the packet, exactly as you would without this table.\n"
            "The rows are an INDEX into the verbatim notes below \u2014 those raw notes, not this table,\n"
            "are the source of truth; the cells are excerpts and may be truncated.\n\n"
            "| # | prior finding | author's resolution claim | CHECK | recorded OUTPUT |\n"
            "|---|---|---|---|---|\n"
            + "\n".join(_rows) + "\n\n")
    else:
        resolution_block = ""
    if malformed:
        _diags = "\n".join(
            f"  - NOT PARSED as a resolution row (rendered verbatim below instead): "
            f"\"{_md_cell(_e, 160)}\" \u2014 expected `{_RESOLUTION_NOTE_SHAPE}`"
            + (f", with <finding-index> in 1..{_n_prior}" if _p else "")
            for _e, _p in malformed)
        malformed_block = (
            "### Amendment(s) that LOOK like a resolution row but did not parse\n"
            f"{_diags}\n"
            "Nothing is lost: each entry above is rendered verbatim with the other amendments below,\n"
            "and is weighed exactly as any other amendment. This note only explains why it earned no\n"
            "row in the table.\n\n")
    else:
        malformed_block = ""
    if amend_since:
        amend_lines = "\n".join(f"  - {a}" for a in amend_since)
        amend_block = (
            f"{resolution_block}{malformed_block}"
            f"### Amendments the author recorded SINCE pass {prior_pass_n} "
            f"(the card's `amend_notes:`, entries after that pass only)\n"
            f"{amend_lines}\n\n"
            "These are the AUTHOR'S RECORDED ANSWERS, written through the governed route between the\n"
            "prior pass and this one — usually addressed at the prior findings above. Weigh each as\n"
            "EVIDENCE when you judge whether a prior finding's condition is NOW met.\n"
            "An amendment is NOT, by itself, a resolution: it is a claim plus its reasoning, and it\n"
            "resolves a finding only where the finding's CONDITION is actually satisfied in this\n"
            "packet. A condition still unmet STILL blocks (verdict != GREEN) however the amendment\n"
            "argues. Equally, do NOT mark a finding NOT-RESOLVED without engaging the answer here.\n\n"
        )
    else:
        amend_block = ""
    # (c) the DELTA block — computed unified diff when the prior artifact text is carried, else framing.
    prior_text = prior_record.get("_audited_diff")
    cur_text = cur_diff if stage == "post" else cur_plan
    if isinstance(prior_text, str) and prior_text and isinstance(cur_text, str) and cur_text:
        import difflib
        ud = "".join(difflib.unified_diff(
            prior_text.splitlines(keepends=True), cur_text.splitlines(keepends=True),
            fromfile=f"prior-pass ({from_id})", tofile="current", n=2))
        delta_block = (f"### Delta since pass {prior_pass_n} (computed: prior {from_id} -> current)\n"
                       f"```diff\n{ud or '(no textual change between the prior and current artifact)'}\n```\n")
    else:
        delta_block = (f"### Delta since pass {prior_pass_n}\n"
                       f"FROM: the prior pass audited {from_id}.\n"
                       f"TO: the CURRENT plan/diff is rendered in the body below.\n"
                       f"The DELTA shows what changed in the artifact between them. Use it as an AID for "
                       f"justifying a genuinely-NEW finding (what the current change introduced) and to "
                       f"avoid re-surveying settled ground — NOT as the sole test of whether a PRIOR "
                       f"finding is resolved (a prior finding may be resolved by a change OUTSIDE this "
                       f"diff — see the resolution rule above).\n")
    return (
        "## MONOTONIC PER-PASS RE-AUDIT (pass N>=2 — SPEC-0036 §Monotonic per-pass re-audit prompt) — READ FIRST\n\n"
        "This is a RE-AUDIT: a prior pass already ran at this stage. Do NOT re-survey from scratch.\n"
        "Your FIRST task is to go through EACH prior finding below and mark it RESOLVED or\n"
        "NOT-RESOLVED by re-evaluating its CURRENT satisfaction in the FULL packet you now see — the\n"
        "body, the attached/referenced files, AND the surfaced adoption/state evidence — NOT only by\n"
        "whether the audited DIFF changed since the prior pass. A prior finding is RESOLVED when its\n"
        "condition is NOW met in this packet, REGARDLESS of whether the audited diff itself changed: a\n"
        "resolution may live OUTSIDE the diff — an engine/environment fix or freshly-surfaced evidence\n"
        "that now renders a once-missing thing PRESENT. Do NOT carry a prior finding forward merely\n"
        "because the diff is unchanged — re-check the finding's CONDITION itself. Resolution must still\n"
        "be GENUINE: mark RESOLVED only when the condition is ACTUALLY satisfied now, never a blanket\n"
        "clear-on-no-change; a still-unmet condition STILL blocks (verdict != GREEN) even with no diff\n"
        "change. The fresh-survey overlay that follows is SECONDARY: only\n"
        "AFTER the prior-finding resolution may you raise a finding, and a NEW finding MUST be\n"
        "justified as genuinely-new (a real defect the current change introduced OR the prior pass\n"
        "missed) — NOT a re-survey of settled ground and NOT a goalpost-shift onto a concern the prior\n"
        "pass did not raise.\n\n"
        "CONVERGENCE: if every prior finding is RESOLVED and there is no new REAL defect, return GREEN.\n"
        "NOT BLINDED (constraint #2): a genuinely-new REAL defect STILL surfaces and STILL blocks — it\n"
        "is a finding and the verdict is NOT GREEN. \"Account for prior first\" never means \"new\n"
        "findings forbidden\".\n\n"
        f"### Prior audit verdict (pass {prior_pass_n}): {prior_verdict}\n"
        f"{findings_block}\n\n"
        f"{amend_block}"
        f"{delta_block}"
        "\nNOTE — an UNCHANGED audited diff is NOT grounds to carry a prior finding forward. Re-check\n"
        "whether the finding's CONDITION is satisfied in the current FULL packet (its evidence may have\n"
        "been surfaced by an out-of-diff engine/environment fix since the prior pass). Carry it forward\n"
        "ONLY if the condition is still genuinely unmet.\n"
    )


def delta_discipline_block(has_prior_findings: bool) -> str:
    """T-12288 / SPEC-0204 rule 8(b) — the BELOW-CEILING delta instruction of a TASK audit-pre/post
    pass >= 2. Two jobs and no third: SCOPE the pass (closure + regression, nothing else) and ASK for
    the `causality` the record seam classifies on.

    The causality ask is the LOAD-BEARING half. The engine fails CLOSED on an absent value (it counts
    at its severity), so telling the auditor that an honest `pre-existing-in-subject` is RECORDED
    rather than held against the change is the only thing that makes the honest answer cheaper than
    silence — without the ask, rule 8's late-finding bucket would simply never be entered.

    `has_prior_findings` is FALSE when the pass-N>=2 monotonic section did not render — a prior record
    that carries no usable verdict (an ABORT, an unparseable response). The pass is STILL a pass >= 2
    and still gets the delta discipline (rule 8: «EVERY later pass»), but the sentences that point AT
    a rendered list are dropped rather than pointing at nothing: an auditor told to reference
    fingerprints that are not in its packet would invent them. That case is exactly the AC1 finding
    an audit-pre pass raised against keying this fork on the section instead of on the pass number.

    Pure f(has_prior_findings)."""
    _identity = (
        "Each prior finding above is listed with its engine `fingerprint:`. That fingerprint is the "
        "ONLY\nidentity the engine matches your finding against — re-describing a prior finding in "
        "new words\nmakes it read as a NEW one. When you re-raise a prior finding, keep its "
        "`criterion_ref`/`class_id`,\n`locator` and `failing_input` EXACTLY as they are above.\n\n"
        if has_prior_findings else
        "The prior pass recorded no readable findings, so there is no list above to judge closure "
        "against.\nDo NOT re-survey the subject to fill the gap: report what the CURRENT change "
        "introduces, and\nnothing else.\n\n")
    return (
        "\n### Delta discipline (SPEC-0204 rule 8) — judge the findings above, plus regression, and\n"
        "NOTHING ELSE\n\n"
        "The whole-subject survey happened on PASS 1 and is NOT re-opened. Judge EXACTLY two things:\n"
        "  (1) for each prior finding above, whether it is now CLOSED — and the evidence that shows "
        "it.\n"
        "      A `closed` with no evidence is not a closure and the finding stays open.\n"
        "  (2) any REGRESSION the change introduced since that pass.\n"
        "Do NOT re-survey the subject and do NOT enumerate defects over the whole tree.\n\n"
        + _identity +
        "EVERY finding you raise that is NOT one of the prior findings above MUST carry `causality`:\n"
        "```yaml\n"
        "    causality: introduced-by-subject      # the change under audit INTRODUCED this defect\n"
        "    causality: pre-existing-in-subject    # it was already there at pass 1; that survey "
        "missed it\n"
        "```\n"
        "A `pre-existing-in-subject` finding is RECORDED as a LATE FINDING: it is never a verdict "
        "driver\n"
        "on its own, and it must still be DECIDED before the card closes — so naming one honestly "
        "costs\n"
        "this change nothing. An ABSENT or unrecognised `causality` counts AT ITS SEVERITY "
        "(fail-closed):\n"
        "the engine never guesses which it was. This does NOT lower the bar — a REAL defect the "
        "change\nintroduced still blocks.\n"
    )


def build_audit_prompt(task: dict, stage: str, diff: str | None, extra: str | None,
                       target_kind: str = "task", focus: str = None,
                       event_emit_only: bool = False, serve_deploy: bool = False,
                       reaudit_after_close: bool = False, external_action: bool = False,
                       host_config: bool = False, land_emitted_event: bool = False,
                       preshipped_deliverable: bool = False, preshipped_commit: "str | None" = None,
                       settlement_sweep: bool = False, settlement_commits: list | None = None,
                       post_ship_observation: "dict | None" = None,
                       activation_gated_radius: "dict | None" = None,
                       prior_record: "dict | None" = None, prior_passes: int = 0,
                       on_decisions: "dict | None" = None, *,
                       zero_ship_diff: bool = False, evidence_locator: "str | None" = None,
                       foreign_subject: "dict | None" = None,   # T-12737 — {commit, reason, land_evidence}
                       churn_tie: "dict | None" = None,
                       prototype_diff: "str | None" = None, prototype_identity: "dict | None" = None,
                       yaml_dump_block, latest_event_for, diff_touched_files,
                       norm_repo_path, ac_probe_evidence_events_for,
                       spec_coverage_section, build_referenced_files_section,
                       scenario_contract_section=None, evidence_sink=None,
                       activation_section=None,
                       readiness_sink=None, readiness_journal_silent: bool = False,
                       cross_evidence_section_for=None, p8_carrier_section_for=None,
                       repo_root=None, cross_section_sink=None, optin_excluded_sink=None, task_events_for=None, BASE_PASS1_SURVEY_CLAUSE, PROTOTYPE_PRE_OVERLAY, _bound_packet_total, _keep_within_budget, _format_adoption_evidence_lines, _format_collector_shape_note, _format_monotonic_reaudit_section, _format_sandbox_evidence_exclusion_note, _format_type_optin_exclusion_note, _format_window_exclusion_note, _merge_tie_ordering_note, class_id_vocabulary, decision_audit_prompt_parts, declared_deferred_probes_block, deferred_by_declaration_block, delta_discipline_block, land_emitted_named_evidence, on_decisions_packet_block, p8_carrier_ids_in_section, packet_readiness_section, packet_touch_reconciliation, packet_touch_section) -> str:
    """Construct codex prompt с V2 universal lens + per-stage overlay + task/decision context (D-0055).
    `focus` (T-0350, SPEC-0036 --focus): an owner/session question block appended AFTER the overlay+body
    — it never replaces the template/overlay; deterministic order: focus part precedes ## Extra context.
    `event_emit_only` (T-0393, --task audit-post only): appends an EVENT-EMIT-ONLY carve-out paragraph
    to the audit-post overlay — the task's P8 adoption event lands in a SEPARATE Stage-9 commit AFTER
    this audit, so its absence at audit-post is EXPECTED, never a finding (the carve-out is gated to the
    `post` overlay branch; the keyword default keeps positional callers / pre prompts unchanged).

    `serve_deploy` (T-9393, --task audit-post only, SPEC-0094 §5): the SIBLING carve-out for a
    serve/deploy task — a live deploy is an ACTION, not a code diff, so live-adoption is recorded at
    Stage-9 Closure (the live_probe evidence, T-9391), not at this diff-only audit-post. Appends a
    serve/deploy paragraph telling the auditor the adoption absence here is EXPECTED, never a finding
    (the X-0039 owner-reset/ceiling-burn fix). Same deferred-adoption family as event_emit_only.

    `reaudit_after_close` (T-9456, --task audit-post only, the `--reaudit-after-close` re-audit path):
    a re-audit of an ALREADY-CLOSED (status:done) task audits HEAD, whose diff therefore CONTAINS the
    Stage-9 closure metadata (status: done + recorded probes + the task_closed bookkeeping). The base
    post overlay expects closure metadata to be ABSENT (Stage 9 follows the auditor) and would otherwise
    false-RED a "closed inside shipped diff" finding. This flag appends a closure-in-diff-expected
    paragraph telling the auditor the closure metadata in the diff is EXPECTED for a post-close re-audit,
    NEVER a finding — the SIBLING of event_emit_only/serve_deploy but for closure PRESENCE rather than
    adoption ABSENCE (the false-RED that blocked T-9445's --rebaseline land). Gated to the `post` branch.

    `external_action` (T-9585, --task audit-post only, SPEC-0094 §7): the THIRD SIBLING in the
    deferred-adoption family (after event_emit_only / serve_deploy) for a task whose ship is an EXTERNAL
    OWNER ACTION (e.g. registering a domain in a webmaster panel — the T-0085 / X-0099 case), NOT a code
    diff. Its proof is an owner-confirmation probe recorded at Stage-9 Closure, so the acceptance-probe
    RESULTS legitimately do NOT exist at this diff-only audit-post. Appends an external-action paragraph
    telling the auditor the probe-results-absent / "AC probes not in the diff" category here is EXPECTED,
    never a finding (the X-0099 false-RED that forced an owner-gated Stage-9 hand-edit). Gated to `post`.

    `host_config` (T-9621, --task audit-post only, SPEC-0094 §3 / SPEC-0111): the FOURTH SIBLING in the
    deferred-adoption family (after event_emit_only / serve_deploy / external_action) for a HOST-CONFIG
    task (the `host_config: true` marker, SPEC-0028). Its adoption proof is the THREE hostapply evidences
    — apply_confirmed / host_health_sweep_passed / host_reconciliation_recorded — RECORDED by the SPEC-0111
    apply seam at Stage-9 Closure, AFTER this diff-only audit-post. So the 3 evidences legitimately do NOT
    exist yet at audit-post; the base post overlay reads their absence as the gap → false-RED "adoption
    missing" (X-0117). Appends a host-config paragraph telling the auditor the absence of those 3 evidences
    here is EXPECTED for a host-config ship, never a finding. Gated to `post`.

    `land_emitted_event` (T-10045, --task audit-post only, SPEC-0036 / X-0188): the FIFTH SIBLING in the
    deferred-adoption family (after event_emit_only / serve_deploy / external_action / host_config) — the
    GENERALIZATION of event_emit_only to a NON-P8 event. For a task whose acceptance probe is a
    land-Stage-9-emitted NON-P8 event (e.g. `verify_layer_prep`, emitted by `land` at Stage 9), that
    event legitimately does NOT yet exist at the diff-only Stage-8 audit-post. The event_emit_only
    overlay text is P8-CLOSURE-event-specific (consumer_read_evidence / live_trigger_evidence), so the
    auditor does NOT extend it to an arbitrary land-emitted acceptance event → the base post overlay
    false-REDs "acceptance probe not satisfied" (X-0188 — T-0073 burned 2 RED passes + a convergence
    consult on this structural false-RED). Appends a land-emitted-event paragraph telling the auditor a
    declared land-emitted NON-P8 acceptance event's absence at audit-post is EXPECTED, never a finding.
    Gated to `post`.

    `preshipped_deliverable` (T-10062, --task audit-post only, SPEC-0036 / X-0201): the SIXTH SIBLING in
    the deferred-adoption family (after event_emit_only / serve_deploy / external_action / host_config /
    land_emitted_event). For a re-claimed task whose deliverable ALREADY LANDED in a PRIOR session
    (<project> T-0131, X-0201), the re-claim diff is gate-proof + closure bookkeeping ONLY and carries
    NO deliverable → the base post overlay false-REDs "code shipped but not invoked" / "nothing shipped".
    Appends a pre-shipped-deliverable paragraph NAMING the derived prior deliverable commit
    (`preshipped_commit`, the task's durable `commit_landed` sha the cmd_audit fail-closed guard proved)
    and telling the auditor the deliverable-absent / empty-diff category is EXPECTED here, never a
    finding. Gated to `post`.

    `post_ship_observation` (T-10916, --task audit-post only, SPEC-0036 / X-0710): the EIGHTH SIBLING in
    the deferred-adoption family — the card's VALIDATED `post_ship_observation:` declaration (a
    {observation, due_by} mapping the `_require_post_ship_observation` guard proved well-formed and
    unsettled), passed as the declaration itself rather than a bare bool so the carve-out can NAME to the
    auditor exactly what will be observed and by when. For a task whose acceptance probe is a MULTI-DAY
    POST-SHIP PRODUCTION OBSERVATION (<project> T-0008: «the daily count is flat or falling over 7 days»),
    that reading cannot exist at this pre-land, diff-only Stage-8 audit — the observation window has not
    even opened. No existing overlay covers it (event-emit-only is P8-specific, land-emitted-event needs
    an event `land` itself emits, serve-deploy/host-config name their own evidence sets), so the base
    post overlay reads the missing reading as a defect and the worker must misuse a non-matching flag or
    halt (X-0710). Appends a paragraph telling the auditor the absence is the NORMAL ordering here, never
    a finding. Gated to `post`.

    `activation_gated_radius` (T-11014, --task audit-post only, SPEC-0176): the NINTH SIBLING, and the
    only one whose deferred proof is SCOPE FIDELITY ITSELF — so it is passed as the guard's validated
    PARTITION ({declaration, reconciliation, specs, forecast}), never a bare bool. When a card's own
    CLOSURE flips a `proposed` spec that registers a concern, the registry answers only for
    already-ACTIVE specs, so the fixtures that activation invalidates are invisible while the card is
    planned and audited — T-10866 burned 4 audit passes, 2 owner resets and a convergence consult
    arguing about a forecast that could not have existed. The paragraph is deliberately SCOPED, not
    blanket: it names the eligible spec, lists the reconciliation as the WHOLE of the exemption, states
    that every other touched path is still covered by `expected_touch` under ordinary scope fidelity,
    and tells the auditor that a reconciliation entry which is plainly an ordinary authored change IS a
    finding. That last instruction is load-bearing — the guard proves the exemption is scoped and the
    remainder enforced, but per-path activation-causation is the judgement it deliberately does not
    mechanize (SPEC-0176 rule 5 names the registry projection query as that stronger, unbuilt fix).
    Gated to `post`.

    `readiness_sink` (T-11977, SPEC-0036 §Packet preview): an optional list — supplied ONLY by the
    `--preview` path — that this assembler appends the rendered REPORT-ONLY packet-readiness block to.
    The `evidence_sink` shape exactly, and for the same reason: the block is built HERE, from the
    parts this one pass already computed, so it can neither be a second assembler nor a re-parse of
    the rendered packet. Nothing in the assembled prompt changes when it is supplied — a preview and
    a real invocation still produce a byte-identical packet (the T-11407 AC2 claim).
    `readiness_journal_silent` (T-11977): the D2 fact — is there NO journal row for this card since
    the previous RED verdict? It is an INPUT because it is read from the journal, which this pure
    assembler does not touch; the caller computes it with the same `packet_journal_silence_since_red`
    that produced the standalone diagnostic this block folds. The RENDERING still happens only here.

    `evidence_sink` (T-10741, SPEC-0168 rule 5): an optional list the TASK audit-post branch fills
    with the AC-probe evidence rows this packet COUNTED, at the moment it counts them, so the caller
    can record that set durably (the land-time custody snapshot recomputes at land time and therefore
    cannot see a row destroyed before the land began — this is the only moment the packet-time set
    exists). CAPTURE ONLY: the sink is never read here, nothing branches on it, and the prompt is
    byte-identical whether or not one is passed. Scoped to the counting branch, never the whole fold —
    the fold's breadth is the VIEW, this is the TRIGGER (`lessons/scope-the-trigger-not-the-view.md`).

    `cross_evidence_section_for` (T-10915, X-0695): an OPTIONAL host-injected `f(task) -> str` that
    renders the task-tied coordination items from the SHARED store (outside every repo per SPEC-0084
    rule 5) with visible cross-instance provenance. A card whose acceptance PROBE is a filed
    coordination item has its artifact in a store this packet's journal readers cannot see, so the
    section rendered EMPTY and the auditor honestly REDs a criterion whose artifact provably exists.
    Injected, never imported (this module reads no host global and knows no store path). Its output is
    APPENDED to the adoption block and NEVER enters `evidence_sink`: the sink is rule 5's COUNTED set
    and must stay scoped to LANDABLE journal rows — a cross row can never land in this repo, so
    counting it would trip the custody check forever (rule 5 mode (c)). Report-only, fail-open: a
    missing or raising injector degrades to "", because an evidence READ must never break an audit.

    The host-coupled prompt-section helpers (yaml_dump_block, latest_event_for, diff_touched_files,
    norm_repo_path, ac_probe_evidence_events_for, spec_coverage_section, build_referenced_files_section)
    are INJECTED by the bin/yitc-v2 wrapper (T-9248) — this module reads no host global."""
    lens = (
        _AUDIT_REVIEW_ONLY_CLAUSE + "\n"
        "## V2 evaluation lens\n\n"
        "CHARTER principles check: anti-complexity (4 filters) / Done = Adopted (probe evidence) /\n"
        "Documentation-first (`from:` chain + spec-coverage of touched code — see the coverage section) / Single SoT (no parallel storage) / AI Independence\n"
        "(provider-neutral in normative text) / Controller+Worker only (CHARTER §P6 — no pipeline or role-split crept in).\n"
        "Repeated work (T-12054, SPEC-0036 §Universal lens): does the plan/diff add repeated work — an\n"
        "N+1, a re-read, a re-fetch, an unbounded loop or poll, a repeated scan, an unwatermarked pass —\n"
        "WITHOUT naming the neighbouring mechanism at the same seam it reuses (or recording that none\n"
        "exists)? The classes + detect heuristics are single-homed in `patterns/repeated-work-lens.md`;\n"
        "ask the one question, do not re-derive them. Inert for an artifact that adds no read / loop /\n"
        "poll / fetch / scan / worker pass — silence there is correct, never a finding.\n"
        "TOUCH-FORECAST / COVERAGE COMPLETENESS IS CONTEXT, NEVER A FINDING (T-12302, SPEC-0036\n"
        "§Universal lens): that a file or a spec is ABSENT from the card's `expected_touch` or from\n"
        "the coverage forecast is NOT a defect at any severity, and you MUST NOT raise it as a\n"
        "finding — not as high, not as low, not as a note dressed as a finding. `expected_touch` is\n"
        "an OPTIONAL plan-time forecast that `task commit` REFRESHES from the committed diff, so a\n"
        "gap is a fact about when the card was written, not about the change. Use the comparison as\n"
        "CONTEXT for your scope-fidelity judgement instead: a path in the diff that the card's SCOPE\n"
        "does not justify is still a scope-fidelity finding — judge the CHANGE, never the forecast's\n"
        "completeness. A RED whose only finding carries `class_id: forecast-completeness` is REFUSED\n"
        "at the parse floor: no verdict is recorded and the pass is not spent, so the finding is\n"
        "lost rather than acted on.\n"
        "\n" + (_AUDIT_POST_ABSORPTION_CLAUSE if stage == "post" else _AUDIT_ABSORPTION_CLAUSE)
    )
    # T-12237 — what makes the `### DEFERRED BY DECLARATION` section BINDING rather than
    # decorative. T-12225's packet already carried a CORRECT post-ship-observation carve-out and
    # the auditor RED-ed straight across it, because nothing told it how to READ a carve-out. This
    # paragraph is appended ONLY when the section is actually rendered for this target, so a card
    # that declares nothing sees an unchanged lens (inert by construction, same as the section).
    # T-12237 consult B4 — derived ONCE per prompt build (audit-post, task target) and reused by
    # the lens clause below AND the task body: both passes used to rescan the card and rerun the
    # land-emitted evidence read at the same prompt-building seam (repeated-work lens).
    # T-13150 (X-1712) — rendered at audit-PRE too: a plan whose criterion is DECLARED provable only
    # after landing was RED-ed at pre as "missing adoption" (<project> T-0732 x8, T-0733 x3, T-0734 x4,
    # each an audit-ceiling halt), because pre never saw the declaration post already honours.
    _deferred_block = (deferred_by_declaration_block(task)
                       if (target_kind == "task" and stage in ("pre", "post")) else "")
    if _deferred_block:
        lens += (
            "\nDEFERRED BY DECLARATION (SPEC-0036, T-12237). This packet carries a\n"
            "`### DEFERRED BY DECLARATION` section listing criteria whose proof lands AFTER the\n"
            "subject you are judging, each with the declaration that defers it. That section is\n"
            "BINDING on your verdict class: for a criterion listed there, the ABSENCE of its proof is\n"
            "EXPECTED and is NEVER a finding and NEVER a RED. It is EXHAUSTIVE — a criterion NOT\n"
            "listed is judged exactly as usual, so the section widens nothing. What you still judge is\n"
            "the DECLARATION: does it correspond to the criterion it defers, and is it dated/tracked?\n"
            "A deferral naming no reading, no due date and no settle carrier IS a finding.\n")
    # T-12312 — the FILING-TIME declared-deferred-probe section, rendered at BOTH task stage overlays.
    # Derived ONCE per prompt build and reused by the lens clause here AND the task body below, so the
    # section and the clause can never disagree about whether this packet carries one (the T-12237
    # sibling's repeated-work lens, applied to its own seam).
    #
    # WHY BOTH STAGES, unlike the audit-POST-only sibling above: two of the six measured incidents were
    # audit-PRE REDs (T-12305, T-12306, each RED x2 to a ceiling exit). A pre-audit judges a plan, and a
    # plan that NAMES a criterion provable only after landing is exactly what the auditor was reading
    # when it red-ed. Inert ("") on a card that declares nothing, so no unrelated packet changes.
    _declared_probe_block = (declared_deferred_probes_block(task)
                             if (target_kind == "task" and stage in ("pre", "post")) else "")
    if _declared_probe_block:
        lens += (
            "\nDEFERRED PROBES, DECLARED AT FILING (SPEC-0060 / SPEC-0036, T-12312). This packet\n"
            "carries a `### DEFERRED PROBES — settled after landing by the Controller` section listing\n"
            "criteria this card declared, AT FILING, to be proven only by the FIRST REAL USE AFTER\n"
            "LANDING, each with the moment its proof becomes readable. That section is BINDING on your\n"
            "verdict class: for a criterion listed there, the ABSENCE of its proof is the DECLARED\n"
            "ORDERING and is NEVER a finding and NEVER a RED, at any severity. It is EXHAUSTIVE — a\n"
            "criterion NOT listed is judged exactly as usual, so the section widens nothing. What you\n"
            "still judge is the DECLARATION: does it correspond to the criterion it defers, and is its\n"
            "moment one a reader can decide? A RED whose ONLY findings are P8-adoption complaints\n"
            "against a criterion listed there is REFUSED at the parse floor: no verdict is recorded and\n"
            "the pass is not spent, so the finding is lost rather than acted on. Raise any REAL defect\n"
            "instead — a RED carrying one alongside is recorded normally.\n")
    # T-11427 (X-1097, <project>) — RENDER the card's Stage-1 analysis record. SPEC-0032 homes the
    # prior-art sweep + premise check and says to record them in `analysis:`; the audit-pre packet
    # showed Scope / Acceptance / Implementation plan and NOT that field, so a correctly-performed
    # Stage 1 read to the auditor as SKIPPED (measured: one RED pass on <project> T-0461, whose sweep
    # HAD run and was recorded). DISTINCT from the SPEC-0036 deferred-adoption overlay family: those
    # exist because the evidence does not YET exist at audit time — here it exists, in the card, and
    # was simply not put in front of the auditor, so no overlay flag could fix it. Derived-context
    # rendering of data the builder already holds (the `### Stage-6 test evidence` class): no new
    # rule, flag, store or event. The heading is emitted UNCONDITIONALLY — an empty record renders as
    # an explicitly ABSENT section, never vanishes, because omitting it silently would convert this
    # false RED into a false GREEN (a genuinely skipped Stage 1 must stay catchable).
    # T-12756 — DERIVED ONCE HERE, ABOVE THE PRE/POST FORK, because audit-POST renders the SAME
    # section from the SAME expression (one source, so the two stages can never drift into showing
    # the card's Stage-1 record differently). The measured reason post needs it: on 2026-09-19 three
    # placement-walk cards (T-12741/T-12742/T-12743) homed their AC2(b) evidence in `analysis:` and
    # reached the audit-post CEILING because the post auditor could not see it — pass 2 re-reported
    # pass 1 verbatim (deviation events.jsonl#ts=2026-09-19T09:26:04Z, followup fu_710501bdf4c6).
    # The pre-branch rendering is byte-identical to before: only the derivation MOVED.
    _analysis = str(task.get("analysis") or "").strip()
    _analysis_block = _analysis or (
        "(no analysis record on the card — Stage 1 left no durable record. This absence is shown,\n"
        "not hidden: judge it on its merits.)")
    # T-12009 — the rendered SPEC-0015 third-satisfier block, computed ONCE below (audit-post only)
    # and consumed TWICE: appended to the adoption body exactly as before, and handed to the
    # readiness row so the two cannot disagree. Initialised here so every other target/stage — which
    # renders no carrier body at all — reaches the readiness block with an honest empty value.
    _p8_carrier_block = ""
    if target_kind == "decision":
        overlay, body = decision_audit_prompt_parts(task, stage, diff)
    elif target_kind == "plan":   # T-0193 — plan-finalization aggregate (post-only, accepted→realized)
        overlay = (
            "## audit-post overlay — PLAN FINALIZATION (aggregate)\n\n"
            "This grades the WHOLE realization of a PLAN — a DIFFERENT, higher altitude than a single\n"
            "task's diff. Focus: did every spec the plan birthed reach `active`? is the plan+spec corpus\n"
            "coherent (no contradiction, no orphan, no half-realized spec)? Per Part D/1 (T-0209) the\n"
            "corpus now ALSO includes the task side — the implementing tasks reached via the cites:<plan>\n"
            "edge, each with its status. Grade whether those tasks realize the plan (drift / orphan /\n"
            "half-done). Review-only (D-0043): do NOT run tests; the plan/spec/task STATUS fields are the\n"
            "evidence.\n\n"
            "POSTCHECK-ENTRY FRAMING (T-0331, folds T-0330) — the plan FSM is\n"
            "draft -> specs -> trial -> accepted -> decomposition -> executing -> postcheck -> realized. `audit post --plan`\n"
            "produces the postcheck-ENTRY verdict — the canonical flow runs it at status `executing`\n"
            "to GATE entry into the postcheck stage (`plan stage executing` then `audit post --plan`\n"
            "then `plan stage postcheck`), NOT only at the final `realized` close. So a corpus where\n"
            "not every task is `done` can be CORRECT at this altitude — judge realization, not closure.\n"
            "RETIRE-ON-PROOF EXEMPTION: a RETIRE-ON-PROOF task — a cited task carrying a `return_trigger`\n"
            "('retire the OLD mechanism once the NEW is proven') — is postcheck-EXIT payload, NOT a\n"
            "finalization blocker at this entry. It stays open (typically `parked`) THROUGH postcheck:\n"
            "postcheck IS the real-data soak that proves the new mechanism, and the old is retired only\n"
            "at the `realized` EXIT gate. So a not-done retire-on-proof task (flagged `[retire-on-proof]`\n"
            "in the corpus below) is EXPECTED here and is NEVER a finding — do NOT RED the plan as\n"
            "half-realized for it.\n"
            "SCOPE-CUT EXEMPTION (T-10365 + T-10406, the task-side mirror of the DELIBERATE-TERMINAL\n"
            "EXEMPTION below): a `wont-do` implementing task whose `wont_do_reason` NAMES carrier(s) —\n"
            "either an id-shaped kernel successor (`T-NNNN` / `SPEC-NNNN`), or a `commit:<sha>` under\n"
            "which the work was DELIVERED OUT OF THIS TERRITORY (shipped in another repo, e.g. host-side;\n"
            "recognized only when the reason states BOTH the delivery-out-of-territory AND the commit) —\n"
            "is a DELIBERATE scope-cut: the plan's scope was intentionally\n"
            "narrowed and that work was re-homed onto the named carriers. It is NOT an unrealized\n"
            "obligation. The code gate already exempts it (`_require_plan_postcheck_ready`, T-0384: a\n"
            "terminal wont-do can never become done, so blocking on it would deadlock the plan FSM), and\n"
            "so must you: it is flagged `[deliberate scope-cut - EXEMPT]` in the corpus below WITH its\n"
            "`wont_do_reason`, is EXCLUDED from the `all-done?` tally, and is NEVER a half-done finding.\n"
            "Do NOT RED or YELLOW the plan because an implementing task is a rationale-bearing wont-do.\n"
            "INSTEAD, JUDGE THE MAPPING — that is the job T-0384 delegates to THIS audit: read each\n"
            "exempt card's `wont_do_reason` and ask whether the named carriers genuinely hold the cut\n"
            "work. If a rationale does NOT hold up (the successors do not exist, the delivery claim is\n"
            "unsupported, or the carriers plainly do not cover the cut scope), THAT is a legitimate\n"
            "finding — report it as such.\n"
            "FAIL-CLOSED (both exemptions above): a non-retire-on-proof, non-scope-cut implementing task\n"
            "that is not done IS still a genuine half-done / drift finding; that judgement is unchanged.\n"
            "In particular a BARE `wont-do` naming no successor carrier is NOT\n"
            "exempt (nor is one that merely MENTIONS a commit without claiming the work was delivered\n"
            "out of this territory under it) — it appears untagged, is still counted in the `all-done?`\n"
            "tally, and genuinely does\n"
            "mean unrealized scope. Grade against the `all-done? N/M` line below, which already reports\n"
            "over the REALIZATION subset (scope-cut cards excluded) — not over a raw task count.\n"
            "REACHED-ACTIVE ACCEPTANCE (T-0485, SPEC-0034 §realized clause (a)) — DO NOT relitigate this:\n"
            "the realize-gate requires every `proposed_by` spec to have REACHED `active`, which is\n"
            "current `active` OR a POST-active state (`superseded` / `retired`). In the spec FSM\n"
            "(proposed -> active -> superseded -> retired) `superseded`/`retired` are reachable ONLY\n"
            "AFTER `active`, so a spec in either status PROVABLY became normative — it SATISFIES the\n"
            "gate. Its content is typically carried forward by lineage evolution into the active head\n"
            "(e.g. SPEC-0037 -> SPEC-0040 -> SPEC-0046). So a corpus whose specs are `superseded`/\n"
            "`retired` (not currently `active`) is CORRECT and realized — do NOT RED it for 'zero\n"
            "active specs' and do NOT YELLOW it for 'a superseded spec in the corpus'. ONLY a\n"
            "never-active NON-TERMINAL status (`proposed` / `draft`) or any unknown status is a\n"
            "genuine half-realized / not-reached-active finding. DELIBERATE-TERMINAL EXEMPTION\n"
            "(T-0627, mirrors SPEC-0034 §realized clause (a)): a `withdrawn` / `rejected` proposed_by\n"
            "spec is a plan-born spec the plan DELIBERATELY abandoned (a scope-cut tracked as a\n"
            "follow-up), NOT an unfinished promise — the code gate `_require_plan_finalization_ready`\n"
            "EXEMPTS it, and so must you: it is flagged `[deliberately abandoned]` in the corpus below,\n"
            "is EXCLUDED from the `reached-active?` realization tally, and is NEVER a half-realized\n"
            "finding. Do NOT RED or YELLOW the plan because a corpus spec is withdrawn/rejected. The\n"
            "corpus line below reports `reached-active? N/N` over the REALIZATION subset (active +\n"
            "post-active count, deliberate terminals excluded) for exactly this gate — judge against\n"
            "THAT, not a bare current-active tally and not the abandoned terminals.\n"
            "TARGET SCENARIOS (T-13019, SPEC-0082): when the corpus carries a `Target scenarios` section,\n"
            "those are the user flows this plan declares it BUILDS. Task closure does not realize a target\n"
            "scenario whose steps are unproven: closed cards and active specs are NOT evidence that the flow\n"
            "works. GRADE every step flagged `[UNPROVEN step]` (no covers test anchor is bound to it) and\n"
            "every `[UNRESOLVED target]` slug. `[UNPROVEN step]` is a proof PROXY, not a reachability\n"
            "measurement — it does not assert the step is unreachable; judge from the corpus whether the\n"
            "plan still realizes that flow, and say so in the finding.\n"
        )
        body = (
            f"## Plan: {task.get('id')} (status: {task.get('status')})\n\n"
            f"### Realization corpus (plan + its proposed_by specs + its cites:<plan> tasks)\n{diff or '(no corpus captured)'}\n"
        )
    elif target_kind == "ad-hoc":   # T-0361 — open-form consult (AGENTS §Per-stage overlays — ad-hoc)
        overlay = (
            "## ad-hoc overlay — OPEN-FORM REVIEW\n\n"
            "This is an open-form consult (AGENTS §Per-stage overlays — ad-hoc Review): the\n"
            "session/owner specifies the focus in the request below; there is no fixed per-stage\n"
            "schema. Answer the request directly, grounded in the V2 evaluation lens above.\n"
            "Review-only: you are consulted for judgement — never to perform work.\n"
        )
        body = (
            f"## Ad-hoc request: {task.get('id')}\n\n"
            f"{task.get('adhoc_prompt') or '(empty request)'}\n"
        )
    elif target_kind == "consult":   # T-0429 — ceiling-convergence triage consult (SPEC-0124)
        # Deterministic prompt assembly: the consult is the pass-3 triage step — it evaluates the
        # session's resolution options after the 2-pass audit-loop ceiling is exhausted. The body
        # carries task YAML + implementation_plan + (post) commit diff + the prior verdict YAML
        # (incl. passes_trail) + the session-formulated options. The overlay forces the convergence
        # question + a STRICT machine-readable output schema (survivors must be a subset of the
        # submitted options; a single recommendation that is exactly one survivor).
        cstage = task.get("consult_stage")   # the audit stage this triage is for: pre | post
        options = task.get("consult_options") or []
        opts_block = "\n".join(f"- [{i + 1}] {o}" for i, o in enumerate(options)) or "(none submitted)"
        if task.get("on_demand_fork"):
            # T-9684 (lever #6) — the ON-DEMAND technical-fork overlay. SAME strict survivors output
            # schema, DIFFERENT framing: this is NOT a pass-3 ceiling triage but a BELOW-ceiling
            # design-fork variant-pick (no prior absorption loop). The auditor RATIFIES technical merit;
            # it does NOT hold value/draft authority — a value/draft fork is ESCALATED, never picked.
            overlay = (
                "## ON-DEMAND TECHNICAL-FORK consult (SPEC-0124 §On-demand technical-fork consult)\n\n"
                "This is NOT a ceiling triage — there is no prior absorption loop and NO prior verdict\n"
                "trail. The session stands at a TECHNICAL DESIGN FORK (e.g. a plan's specs, the\n"
                "decomposition cut, or a task's Analysis) and has formulated >=2 candidate VARIANTS below.\n"
                "It is a 1:1 copy of how the owner manually consults you on a fork: you RATIFY technical\n"
                "merit, the owner keeps a lightweight ratify/veto.\n\n"
                "FIRST, classify the fork:\n"
                "  (a) TECHNICAL-MERIT fork — the better variant is decidable on ENGINEERING merit\n"
                "      (correctness, simplicity, coherence, anti-complexity, reuse). Proceed: name which\n"
                "      variants SURVIVE (a subset, fail-closed) + a SINGLE recommendation that is EXACTLY\n"
                "      ONE surviving variant.\n"
                "  (b) VALUE / DRAFT-AUTHORITY fork — the choice depends on PRODUCT VALUE, owner\n"
                "      preference, scope authority, or a draft-level judgement that is NOT yours to make.\n"
                "      Do NOT pick: return `verdict: ABORT` with `survivors: []` and explain in notes that\n"
                "      it must ESCALATE to the owner. You judge technical merit ONLY — never value/draft\n"
                "      authority.\n\n"
                "FAIL-CLOSED: a single surviving variant you recommend is the only auto-proceed outcome\n"
                "(the owner still ratifies/vetoes). >1 survivor, no survivor, a value/draft classification,\n"
                "or any ABORT escalates to the owner — the session does NOT auto-pick. Review-only: judge —\n"
                "never perform the work.\n"
            )
        else:
            overlay = (
                "## CEILING-CONVERGENCE TRIAGE consult (SPEC-0124 §Audit-loop ceiling)\n\n"
                "The audit-loop ceiling (2 absorption passes) is EXHAUSTED for this task at the named\n"
                "audit stage. This is the pass-3 triage step — NOT a fresh audit. The session has\n"
                "formulated the candidate RESOLUTION OPTIONS below; evaluate EACH against the task scope\n"
                "+ acceptance + the prior verdict trail, decide which SURVIVE (are defensible resolutions),\n"
                "and give a SINGLE recommendation that is EXACTLY ONE surviving option.\n"
                "Per the SPEC-0124 contract: exactly ONE survivor + session agreement enables ONE\n"
                "standing-authorized `--owner-reset` continuation; >1 survivor / disagreement / ABORT\n"
                "escalate to the owner. Review-only: judge — never perform the work.\n"
            )
        # T-9626 (X-0117): surface the task's diff-invisible AC-probe / adoption journal events (the
        # same set audit-post sees — P8 adoption types, spec_edited, AND the 3 host-config apply
        # evidences). The consult carries the REAL task dict (consult_artifact = dict(artifact)), so
        # ac_probe_evidence_events_for(task) ties them by task_id. The consult has NO host-config
        # overlay, so WITHOUT this it could not see a host-config task's deferred-adoption proof and
        # false-RED'd "adoption missing" (the X-0117 ceiling-deadend that forced the <project> T-0088
        # Stage-9 hand-edit). events.jsonl is excluded from the diff (T-0219), so this section is the
        # only place the proof appears.
        _consult_ev = ac_probe_evidence_events_for(task)
        _consult_adoption = (_format_adoption_evidence_lines(_consult_ev) if _consult_ev
                             else ("(no diff-invisible AC-probe / adoption event — e.g. a P8 adoption "
                                   "event, a\nspec_edited tied via cites:, or a host-config apply "
                                   "evidence — recorded for\nthis task. Its absence from the DIFF is "
                                   "expected, events.jsonl is excluded\nper T-0219, and is not itself a "
                                   "finding.)"))
        # T-10947 (the T-9626 shape, different carrier) — surface the card's DECLARED post-ship
        # observation as task-tied deferral CONTEXT. T-10916 shipped the `--post-ship-observation`
        # Stage-8 carve-out, so an audit-post already knows a multi-day production reading
        # legitimately cannot exist yet; the consult has NO overlay of any kind, so a task ceilinged
        # on that same not-yet-observable reading met a triage step that could not see the deferral
        # was already granted — the exact X-0117 gap T-9626 closed for --host-config. The carrier
        # here is a CARD FIELD, not a journal event, so the `ac_probe_evidence_events_for` channel
        # above cannot carry it (routing it there would need an invented event/store); the consult
        # already holds the real task dict, so the smallest edit is to RENDER what it holds.
        # The DECLARATION is the trigger: rendered only when `post_ship_observation` is
        # GRAMMAR-VALID per the single-home `_post_ship_observation_declaration_error` — the same
        # predicate the Stage-8 guard and the debt lens read (CHARTER P5), so an absent or malformed
        # declaration renders NOTHING and this surfacing can never invent a deferral for a card that
        # never declared one. No consult flag, no store, no event type; audit-post is unchanged.
        # T-12237 — the T-10947 `_consult_pso_block` is RETIRED here (CHARTER §P1 F3), SUBSUMED by
        # the family-wide `### DEFERRED BY DECLARATION` section: it renders the SAME declaration
        # PLUS the two kinds the consult was blind to (land-emitted, settle-probe-owed). T-12225's
        # consult saw only the post-ship-observation block, so its AC2 land-emitted half was
        # invisible to the very triage step that exists to clear the ceiling — and it held. The
        # consult holds the real task dict, so this needs no flag and no overlay (the same reason
        # T-10947 gave), and it is inert by construction on a card that declares nothing.
        _consult_deferred_block = deferred_by_declaration_block(task)
        body = (
            f"## Consult target: {task.get('id')} — {task.get('title', '')} (audit stage: {cstage})\n\n"
            f"class: {task.get('class')}, priority: {task.get('priority')}\n\n"
            f"### Scope\n{yaml_dump_block(task.get('scope') or [])}\n\n"
            f"### Acceptance\n{yaml_dump_block(task.get('acceptance') or [])}\n\n"
            f"### Implementation plan\n{task.get('implementation_plan') or '(empty)'}\n\n"
            + (f"### Commit diff (audit stage = post)\n```diff\n{diff}\n```\n\n" if diff else "")
            + f"### Adoption / AC-probe evidence (diff-invisible journal events)\n{_consult_adoption}\n\n"
            + _consult_deferred_block
            + f"### Prior audit-{cstage} verdict trail (incl. passes_trail)\n"
              f"{task.get('consult_prior_trail') or '(no prior verdict captured)'}\n\n"
            f"### Session resolution options (the survivors set is a SUBSET of THESE — verbatim)\n{opts_block}\n"
        )
    elif stage == "pre":
        overlay = (
            "## audit-pre overlay\n\n"
            "Focus: scope match with AC, alternatives considered (Principle 1 F1 prior-art),\n"
            "scope creep risk, implementation plan completeness (files / order / risks / tests).\n"
            "Prior-art spans the PLAN layer too (per T-0111): check the change against PENDING PLANS\n"
            "(plans status:accepted = audit-vetted what-will-be, `plan list --status accepted`) — is it\n"
            "already planned? does it contradict a plan? Flag re-derivation of an existing plan.\n\n"
            "SPEC-COVERAGE OF TOUCHED CODE (T-0444 — use the `### Spec coverage of touched files`\n"
            "section below, which lists the governing active specs the planned files forecast):\n"
            "  (1) Does the plan forecast touching code that has NO governing spec? If so — is that\n"
            "      justified spec-less (the SPEC-0005 admission test does not warrant a spec) or is it a\n"
            "      DOCUMENTATION GAP (code about to be born/changed with no rule describing it)?\n"
            "  (2) Does the plan forecast touching the `implements:` anchor(s) of an active spec WITHOUT\n"
            "      planning to update that spec? If so — is that justified (unrelated symbol / deliberate)\n"
            "      or undeclared DOC DRIFT? A drift flag in the coverage section makes this concrete.\n"
            "      Each flag carries an `origin:` (T-13229): `card-owned` / `indeterminate` is this card's\n"
            "      question; a `stale-signature DEBT` line is PROVEN non-card corpus debt (untouched by the\n"
            "      card, main's bytes, already stale on main) — NEVER a finding against this card. That\n"
            "      settles ATTRIBUTION ONLY: the planned change is still judged against each governing\n"
            "      spec's CURRENT meaning.\n"
            "  BOTH questions are about DOCUMENTATION of the code, never about the COMPLETENESS of the\n"
            "  forecast itself: a file or spec missing FROM the forecast is CONTEXT and is never a\n"
            "  finding (see the universal lens, T-12302).\n\n"
            "PLACEMENT (the corpus-wide placement contract, T-0888): is each NEW or RE-SCOPED artifact\n"
            "the plan forecasts CORRECTLY PLACED — kernel (methodology a consumer pins) vs v2-self\n"
            "(this repo's dev-history that never travels) vs project? Flag a V2-SELF class (tasks /\n"
            "decisions / events / this-repo plans+ideas / graph) being treated as kernel (export-slice\n"
            "leak — the contract's primary failure), or an EXCEPTION-capable artifact (a spec/pattern)\n"
            "whose placement decision the plan leaves implicit (`spec new` fails closed without one).\n\n"
            "STANDARD DECOMPOSITION / EDGE-LABEL NOTATION IS LEGITIMATE — DO NOT RED-FLAG IT (T-9676,\n"
            "E-0016 recurrence, X-0133): a plan/card written in the methodology's own decomposition\n"
            "shorthand is CORRECT plan content, never a defect. Specifically:\n"
            "  (a) A card EDGE-LABEL or TRANSITION LABEL like `proposed-rework` (or `on-review -> proposed`,\n"
            "      `draft -> accepted`, any `<from> -> <to>` arrow) is a normal plan-FSM TRANSITION between\n"
            "      two existing states — it is NOT a missing / undefined / undeclared FSM STATE. Do NOT\n"
            "      RED the plan for an 'undefined state' or 'incomplete state machine' on the strength of a\n"
            "      transition/edge label; the plan FSM's states are fixed by the methodology, and a rework\n"
            "      edge back to an earlier state (e.g. on-review -> proposed) is a SANCTIONED transition.\n"
            "  (b) SPEC-0046 'one claim per accept-unit' (a.k.a. one-claim / single-claim) language is\n"
            "      standard decomposition GUIDANCE the card SATISFIES when it cites it — a plan stating it\n"
            "      cuts one provable claim per accept-unit is COMPLIANT, not deficient. It is NOT a required\n"
            "      governance ARTIFACT the plan is 'missing': do NOT RED the plan for a 'missing one-claim\n"
            "      artifact / undefined one-claim unit / unsatisfied governance requirement' when the card\n"
            "      is expressing or following that very guidance. Judge whether the cut is actually sound\n"
            "      (one provable claim, named proof) — NOT whether a notation token names an artifact.\n\n"
            "SPEC-CONTENT-BOUNDARY IS METHODOLOGY LAW — DO NOT DEMAND IMPL DETAIL IN A SPEC (T-9687,\n"
            "X-0134 RC1b, SPEC-0005 §3 content boundary): when the audited change AUTHORS or EDITS a\n"
            "spec (a `specs/SPEC-*.yaml` body), that spec carries ONLY (a) the standing RULE-TEXT and\n"
            "(b) rationale strictly in service of interpreting/applying that rule. Implementation\n"
            "detail is METHODOLOGY-FORBIDDEN inside a spec — it belongs in the CODE or the PLAN, never\n"
            "the spec. Specifically forbidden as spec content: DTO / payload / request / response /\n"
            "schema SHAPES; field or function or method SIGNATURES; class / data-structure layouts;\n"
            "runtime FLAGS, env-var names, config keys, CLI option spellings; concrete file paths or\n"
            "line numbers as the rule itself. THEREFORE the auditor MUST NOT flag the ABSENCE of any\n"
            "such impl detail as a defect, and MUST NOT DEMAND that the spec ADD a DTO shape, a field\n"
            "list, a flag table, a signature, or any code-level mechanism — demanding them asks the\n"
            "author to VIOLATE SPEC-0005 §3. A spec that states its rule and OMITS the wire-level /\n"
            "code-level shape is CORRECT and COMPLETE, not 'under-specified' / 'missing detail' /\n"
            "'incomplete'. Judge whether the RULE is sound, bounded, single-homed, and adoption-shaped\n"
            "— NOT whether the spec enumerates implementation artifacts the methodology forbids it to\n"
            "carry. (A spec MAY name a code anchor in its `implements:` field or a brief pointer; that\n"
            "is provenance, not the rule body — do not confuse a pointer with a demand for impl detail.)\n"
            "\n"
            "THE CARD'S STAGE-1 ANALYSIS RECORD IS IN THE PACKET — READ IT BEFORE JUDGING THE SWEEP\n"
            "(T-11427, X-1097): the `### Analysis (Stage-1 record from the card)` section below carries\n"
            "the card's own `analysis:` field, where SPEC-0032 says the Stage-1 prior-art sweep — INCLUDING\n"
            "the plan-layer `plan list --status accepted` sweep this overlay asks about — and the premise\n"
            "check are recorded. So judge the sweep against THAT section: a sweep recorded there IS a\n"
            "performed sweep (a `no accepted plans` result is a RESULT, not an omission), and flagging it\n"
            "as absent while the record sits in that section is a FALSE finding. Only an actually-EMPTY\n"
            "record — the section says so explicitly — can support an absent-Stage-1 finding.\n"
        )
        body = (
            f"## Task: {task.get('id')} — {task.get('title', '')}\n\n"
            f"class: {task.get('class')}, priority: {task.get('priority')}\n\n"
            f"### Scope\n{yaml_dump_block(task.get('scope') or [])}\n\n"
            f"### Acceptance\n{yaml_dump_block(task.get('acceptance') or [])}\n\n"
            # T-12312 — placed immediately after the acceptance list, so the auditor reads WHICH
            # criteria are declared deferred BEFORE it reads the plan it would otherwise find them
            # unproven in. Inert ("") on a card that declares nothing.
            f"{_declared_probe_block}"
            f"{_deferred_block}"         # T-13150 — the same section audit-post renders
            f"### Analysis (Stage-1 record from the card)\n{_analysis_block}\n\n"
            f"### Implementation plan\n{task.get('implementation_plan') or '(empty)'}\n"
        )
    else:  # post
        overlay = (
            "## audit-post overlay\n\n"
            "Focus: shipped diff drift from plan, acceptance probes verified (each AC has probe result),\n"
            "missing adoption (code shipped but not invoked), coherence with other docs/state.\n\n"
            "Review-only contract (per D-0043): do NOT execute the test suite. Stage 6 (the primary AI)\n"
            "owns test execution and is the sole authority that tests passed. Instead VERIFY that\n"
            "Stage-6 test evidence exists + is plausible (see the `### Stage-6 test evidence` section\n"
            "below + the diff) and matches the acceptance probes. You being unable to run tests in your\n"
            "sandbox is OUT OF SCOPE — never a finding.\n\n"
            "STAGE BOUNDARY (per T-0123): this audit IS Stage 8. The task is CORRECTLY still\n"
            "`in-progress` and NOT yet closed — closure metadata (status: done, the task_closed event,\n"
            "recorded probes in the YAML) is written at Stage 9 AFTER you return. Its ABSENCE now is\n"
            "EXPECTED and is NEVER a finding. Judge ADOPTION (is the shipped artifact actually used /\n"
            "invoked / wired in?), NOT CLOSURE (task marked done). A genuine diff-drift-from-plan or a\n"
            "truly-unmet acceptance criterion is still RED — that judgement is unchanged.\n\n"
            "THE CARD'S STAGE-1 ANALYSIS RECORD IS IN THIS PACKET TOO (T-12756): the\n"
            "`### Analysis (Stage-1 record from the card)` section below carries the card's own\n"
            "`analysis:` field, where SPEC-0032 says the Stage-1 prior-art sweep, the premise check\n"
            "and the smallest-concrete-edit reasoning are recorded — so evidence a card HOMES there\n"
            "is now in front of you and is judged exactly like any other section, never treated as\n"
            "absent because it did not appear in the diff. It EXEMPTS nothing: an actually-empty\n"
            "record says so explicitly and can still support an absent-Stage-1 finding, and every\n"
            "acceptance criterion is judged as usual.\n\n"
            "ANCHOR-LESS ACTIVATION IS A RED-CLASS CLOSURE DEFECT (T-12977, SPEC-0151 / SPEC-0036):\n"
            "when this card's `task close` activates a `proposed` spec (the `## Activates at closure`\n"
            "section lists them), a spec with NO code anchor in `implements:`, NO delivering `binding:`\n"
            "and NO explicit `execution:` disposition turns active executed by nothing. That is a\n"
            "RED-class closure defect — NEVER LOW, NEVER a followup, because the close is the activation\n"
            "and nothing re-checks it after. The in-scope fix is a `spec edit` of that spec BEFORE close.\n\n"
        )
        # T-12725 — THE ASK SEAM. CHARTER §Principle 8 binds consumer-side adoption evidence to
        # INFRA-class work only and says in terms that probe-side adoption (Principle 3) is sufficient
        # for product-class work. The paragraphs below are the packet's Principle-8 DEMAND — and they
        # used to be rendered for EVERY card, so the auditor asked every card for a carrier: measured
        # over the full audit history (T-12724 census, 2026-05-26..09-16) 400 adoption-evidence
        # findings at the gates, 202 of them on cards whose class is NOT infra (137 fix / 30 feature /
        # 28 docs / 6 refactor / 1 hygiene), 281 of the 400 HIGH — verdict-reddening. The READ-side
        # refutation (`p8_adoption_gap_on_non_infra`, T-12386) catches them AFTER the pass is spent;
        # the non-infra share still ROSE (3.6% -> 20.3% after it shipped) because nothing told the
        # auditor not to ask. So the boundary is applied HERE, at the ASK: the demand is withheld for
        # a card §8 does not reach, through THE SAME predicate the refuter and the readiness row use
        # (`charter_p8_reaches_class` — one home, CHARTER §P5; the refuter stays as the backstop).
        # FAIL-CLOSED: an unresolvable class KEEPS the demand (the predicate's own third value).
        # Everything that is NOT the §8 demand — the Principle-3 adoption focus above, the non-P8
        # AC-probe paragraphs below, the differential-probe demand, the `### Adoption evidence`
        # section (it carries non-P8 AC-probe events) — renders for every class, unchanged.
        _p8_reaches = charter_p8_reaches_class(task.get("class"))
        if _p8_reaches:
            overlay += (
            "ADOPTION EVIDENCE (per T-0236): for an infra-class P8 adoption probe, the carrier is an\n"
            "events.jsonl event (consumer_read_evidence / live_trigger_evidence) — and events.jsonl is\n"
            "INTENTIONALLY excluded from the shipped diff (T-0219). So look for the P8 adoption artifact\n"
            "in the `### Adoption evidence` section below, NOT in the diff. Its ABSENCE FROM THE DIFF is\n"
            "never the adoption finding; if that section shows a matching event, the adoption probe is met.\n"
            "EITHER FORM SATISFIES (per CHARTER §8, T-0255): consumer_read_evidence OR live_trigger_evidence\n"
            "are equally valid — NEVER RED because the task used one form when you expected the other; a\n"
            "form-mismatch is not an adoption gap. Only a task with NO P8 artifact of either form is a gap.\n"
            "A THIRD FORM ALSO SATISFIES (per CHARTER §8, SPEC-0015, T-11995): an EXPLICITLY BLOCKING\n"
            "ADOPTION FOLLOW-UP FILED — a follow-up declaring `P8-CARRIER: <this task id>` and carrying\n"
            "BOTH a named trigger condition AND a machine-resolvable awaited artifact (its ownership).\n"
            "CHARTER §Principle 8 has always named three carriers, not two; this is the third, in the\n"
            "machine-checkable shape SPEC-0119 rule 31 gives it. When the `### Adoption evidence` section\n"
            "below shows such a filed carrier for THIS task, the adoption criterion is SATISFIED AT THIS\n"
            "AUDIT and the absence of a consumer_read_evidence / live_trigger_evidence row is NOT an\n"
            "adoption gap and NEVER a finding on its own — this is the DEFERRED-adoption case, where the\n"
            "live firing is unreachable before the ship lands. NOTHING IS WAIVED: the obligation stands\n"
            "unchanged — closure's own §P8 WARN still reads only the two P8 event types, and the follow-up\n"
            "stays on the debt echo until its named trigger fires. A follow-up MISSING the marker, the\n"
            "trigger or the awaited artifact is NOT a carrier and buys nothing; judge every other\n"
            "acceptance criterion, and diff-drift from plan, exactly as usual.\n"
            "ORDERING (per E-0008 sub-cause 2, SPEC-0015/0016): an event-based P8 adoption event is emitted\n"
            "DURING Execution — by the SESSION running `bin/yitc-v2 event consumer_read_evidence /\n"
            "live_trigger_evidence` (V2 has NO automated emitter code path and adds none — emission is a\n"
            "session action, not a code call-site; CHARTER non-goal #7). So it is EXPECTED already present\n"
            "here. Judge ONLY whether SOME P8 artifact of either form EXISTS in the `### Adoption evidence`\n"
            "section above — NOT whether a code call-site emits it. The absence of an automated emit\n"
            "call-site is NEVER a finding; never RED a not-yet-emitted event as if it were missing.\n"
            )
        else:
            _cls = str(task.get("class") or "").strip()
            overlay += (
            "ADOPTION EVIDENCE — NOT ASKED OF THIS CARD (T-12725): CHARTER §Principle 8's consumer-side\n"
            "carriers (consumer-read evidence / live-trigger evidence / a blocking adoption follow-up)\n"
            f"bind INFRA-class work only, and this card is class `{_cls}`. Its adoption standard is\n"
            "Principle 3 — the probe on each acceptance criterion, judged under DIFFERENTIAL PROBE below\n"
            "— so the `### Adoption evidence` section below is read for the NON-P8 AC-probe events it\n"
            "carries, never for a Principle-8 carrier. Do NOT raise the absence of a Principle-8 carrier\n"
            "as a finding at any severity: on this card it is a category error, not a gap, and it is\n"
            "machine-refuted at the parse floor (`p8-adoption-on-non-infra`), so such a finding is lost\n"
            "rather than acted on. A truly-unmet acceptance criterion is still RED — unchanged.\n"
            )
        overlay += (
            "AC-PROBE EVENTS BEYOND P8 (per T-0290 + T-0551): an AC probe may name a journal event that\n"
            "is NOT a P8 adoption type — e.g. `spec_edited` (proof a spec was edited via the\n"
            "before-rule-change chokepoint), tied to this task EITHER by its `cites:` OR by the edited\n"
            "spec file appearing in this task's SHIPPED DIFF (T-0551 — a task may edit a spec it does\n"
            "not cite). Such events are ALSO surfaced in the `### Adoption evidence` section below (they\n"
            "are equally diff-excluded per T-0219). Treat a matching event there as the AC probe MET —\n"
            "its absence from the diff is never the finding.\n"
            "CARD-NAMED EVENT TYPES (per T-10708): an event whose type is NAMED IN THIS CARD'S OWN\n"
            "ACCEPTANCE text and which carries this task's id is ALSO surfaced there — including a type\n"
            "you do not recognise, because a CONSUMER project (not the kernel) may define it. An\n"
            "unfamiliar event type in that section is therefore NEVER itself a finding: judge it as the\n"
            "AC probe MET if it matches what the acceptance names. Naming a type buys VISIBILITY only —\n"
            "it never satisfies a Principle-8 adoption gate where one applies (the two P8 event types).\n\n"
            "SPEC-COVERAGE OF TOUCHED CODE (T-0444 — use the `### Spec coverage of touched files`\n"
            "section below, derived from the SHIPPED DIFF: the governing active specs per touched file\n"
            "+ symbol-level drift flags):\n"
            "  (1) Does the diff touch code with NO governing spec? If so — is that justified spec-less\n"
            "      (SPEC-0005 admission) or did this ship code with no rule describing it (a doc gap)?\n"
            "  (2) Does the diff touch the `implements:` anchor(s) of an active spec WITHOUT updating\n"
            "      that spec in the same change? A `possibly-stale` drift flag whose `origin:` is\n"
            "      `card-owned` or `indeterminate` marks exactly this — is it justified (unrelated symbol /\n"
            "      deliberate) or undeclared DOC DRIFT (the governing rule now lags the code)? This is the\n"
            "      core fear to catch. A `stale-signature DEBT` line (T-13229) is PROVEN non-card: this\n"
            "      card never changed that anchor's code or stored signature, and both are main's, already\n"
            "      stale there — standing corpus debt, NEVER a finding against this card. That settles\n"
            "      ATTRIBUTION ONLY: still judge the card's own delta against each governing spec's CURRENT\n"
            "      meaning at HEAD and on the resolved tree (a main-side change of a spec's meaning that\n"
            "      the card's code no longer satisfies is still a finding).\n"
            "  BOTH questions are about DOCUMENTATION of the shipped code, never about the COMPLETENESS\n"
            "  of the card's forecast: a file or spec missing FROM `expected_touch` is CONTEXT and is\n"
            "  never a finding (see the universal lens, T-12302). `task commit` refreshes the forecast\n"
            "  from this very diff, so the declared list you see is derived, not a claim to grade.\n\n"
            "PLAN-ADVANCEMENT SCOPE GUARD (per T-9319): when THIS task's deliverable is ITSELF a\n"
            "plan-FSM advancement (its diff advances a plan stage, or authors the plan/spec content a\n"
            "plan forecast), judge DIFF-VS-PLAN ONLY — did the shipped diff do what THIS task's scope\n"
            "+ implementation_plan said? Do NOT re-litigate the PLAN's STRATEGY or whether the plan is\n"
            "a good idea: a plan's strategy/quality is owned by the PLAN gates (gate-specs /\n"
            "decomposition-fidelity / finalization), which are MANDATORY-BLOCKING per SPEC-0083 — a\n"
            "DIFFERENT axis from this task audit-post. The two axes are coherent: PLAN gates own\n"
            "plan-strategy (blocking); the TASK audit-post owns diff-vs-plan. Re-judging the plan's\n"
            "strategy here is OUT OF SCOPE and is NEVER a finding (a genuine diff-drift-from-plan or\n"
            "an unmet acceptance criterion is still RED — that judgement is unchanged).\n\n"
            "SCENARIO-STATUS COMPUTED-VIEW carve-out (SPEC-0076 §3): when the diff touches a\n"
            "`scenarios/` node, a scenario's `status` is a COMPUTED, DERIVED read-only VIEW\n"
            "(`draft → building → live` is derived from the cited specs' FSM + the binding-test signal);\n"
            "it MUST NOT be stored — only `retired` (human-set) or an ABSENT status frontmatter field is\n"
            "legal, and `graph build` exits 2 on any illegally-stored status. So a scenario file with NO\n"
            "`status:` frontmatter is CORRECT BY CONSTRUCTION: its absence is the required state, NEVER a\n"
            "'missing required status field' / 'missing required frontmatter' finding. Do NOT flag a\n"
            "scenario node for an absent status — that absence is conformance, never a defect or a RED.\n\n"
            "DIFFERENTIAL PROBE — per acceptance criterion, NAME THE INPUT THAT WOULD MAKE IT FAIL\n"
            "(T-10282 / X-0246; derived from SPEC-0036 §audit-post overlay). For EACH acceptance\n"
            "criterion in the `### Acceptance` section, answer explicitly: WOULD THIS CRITERION STILL\n"
            "PASS IF THE THING UNDER TEST WERE BROKEN? If yes it is a smoke check, not a probe — the\n"
            "criterion is NOT met, and that is a RED no matter how exactly the shipped diff matches the\n"
            "plan. 'Diff matches plan' and 'criterion is differential' are INDEPENDENT questions: a card\n"
            "can pass the first and fail the second. Report, per criterion, the concrete input/state that\n"
            "must make it fail; if you cannot name one, say so — that is the finding.\n"
            "VACUOUS-ABSENCE sub-class (the named failure mode): a criterion satisfied by asserting an\n"
            "artifact is ABSENT (no event fired / no command ran / no file written) is VACUOUS unless the\n"
            "shipped diff shows the mechanism that PRODUCES that artifact was actually INVOKED in the same\n"
            "scenario — an absence asserted over a state where the mechanism was never called is true of\n"
            "the EMPTY state and proves nothing. Its mirror: a criterion asserting an artifact IS present\n"
            "while the property under test is VIOLATED enshrines the defect as expected behaviour. Real\n"
            "incident (T-9418, corrected by T-10279): a proof card shipped a test whose escalate-branch\n"
            "never invoked the verb it claimed to gate, so its 'no deploy_completed' assertion was\n"
            "vacuously true; it passed byte-for-byte against a verb carrying NO gate at all — which is\n"
            "exactly what had shipped, and this audit-post went GREEN over it. A tests-only diff that\n"
            "asserts a vacuous absence is a DECLARATION, not a ship: RED it.\n"
            "This is a lens DEMAND, not a new mechanism — the discipline is homed at CHARTER §Principle 3\n"
            "(done = adopted) and cued at authoring by SPEC-0060 §4; you are asked it HERE, at verify.\n"
        )
        if event_emit_only:
            # T-0393 — EVENT-EMIT-ONLY carve-out (--task audit-post only). Closes the N>=3 false-RED
            # class (T-0030/T-0382/T-0391). For the ORDERING note above, the default assumption is the
            # P8 event was emitted DURING Execution and is thus already present here. This carve-out
            # REVERSES that single assumption for a declared event-emit-only ship: the emission IS the
            # Stage-9 closure substance, so the event legitimately does NOT yet exist at THIS Stage-8
            # audit — operationalizing the contract's own "closure-time emission would post-date you"
            # exemption (SPEC-0036 audit-post overlay). Everything else (diff-drift, non-adoption AC,
            # coherence) is judged unchanged.
            overlay += (
                "\nEVENT-EMIT-ONLY SHIP (per T-0393, this task is flagged --event-emit-only): the\n"
                "task's adoption probe IS a single Stage-9-recorded P8 event (consumer_read_evidence /\n"
                "live_trigger_evidence) — the EMISSION is the closure substance, recorded in a SEPARATE\n"
                "Stage-9 commit AFTER this audit. So for THIS task the P8 adoption event is EXPECTED to\n"
                "be ABSENT from the `### Adoption evidence` section right now — that absence is the\n"
                "NORMAL ordering, NEVER a finding and NEVER a RED. Do NOT flag the closure-event-absent\n"
                "category as a defect. Judge ONLY: (1) shipped-diff drift from plan, (2) any NON-adoption\n"
                "acceptance criterion that the diff/evidence fails to meet, (3) coherence with other\n"
                "docs/state. A genuine diff-drift or a truly-unmet non-adoption AC is still RED — that\n"
                "judgement is unchanged; ONLY the not-yet-emitted closure event is exempted.\n"
            )
        if serve_deploy:
            # T-9393 (SPEC-0094 §5) — SERVE/DEPLOY carve-out (--task audit-post only). The SIBLING of
            # the event-emit-only carve-out in the same deferred-adoption family. A live deploy is an
            # ACTION, not a code diff: live-adoption is proven at the DEPLOY seam + recorded at Stage-9
            # Closure (the per-change live_probe evidence, T-9391), so it legitimately does NOT exist at
            # this diff-only Stage-8 audit. Removes the X-0039 owner-reset/ceiling-burn the diff-only
            # audit forced on a deploy task. Everything else (diff-drift, non-adoption AC, coherence)
            # is judged unchanged.
            overlay += (
                "\nSERVE/DEPLOY SHIP (per T-9393, this task is flagged --serve-deploy): this task's\n"
                "ship is a serve/deploy ACTION, not a code diff. Its live-adoption is proven at the\n"
                "DEPLOY seam and RECORDED at Stage-9 Closure (the per-change `live_probe` evidence) —\n"
                "AFTER this audit. So for THIS task live-adoption is EXPECTED to be ABSENT from the\n"
                "`### Adoption evidence` section right now — that absence is the NORMAL ordering for a\n"
                "serve/deploy ship, NEVER a finding and NEVER a RED. Do NOT flag the adoption-missing\n"
                "category as a defect. Judge ONLY: (1) shipped-diff drift from plan, (2) any NON-adoption\n"
                "acceptance criterion the diff/evidence fails to meet, (3) coherence with other\n"
                "docs/state. A genuine diff-drift or a truly-unmet non-adoption AC is still RED — that\n"
                "judgement is unchanged; ONLY the deferred-to-Closure live-adoption is exempted.\n"
            )
        if external_action:
            # T-9585 (SPEC-0094 §7) — EXTERNAL-ACTION carve-out (--task audit-post only). The THIRD
            # SIBLING of event-emit-only / serve-deploy in the same deferred-adoption family. The ship
            # is an EXTERNAL OWNER ACTION (e.g. registering a domain in a webmaster panel — T-0085 /
            # X-0099), not a code diff: its proof is an owner-confirmation probe RECORDED at Stage-9
            # Closure, so the acceptance-probe RESULTS legitimately do not exist at this diff-only
            # Stage-8 audit. Removes the X-0099 false-RED ("AC probe results not in the diff") that —
            # surviving the --event-emit-only overlay + the passes=2 ceiling — forced an owner-gated
            # Stage-9 hand-edit. Everything else (diff-drift, non-adoption AC, coherence) is unchanged.
            overlay += (
                "\nEXTERNAL-ACTION SHIP (per T-9585, this task is flagged --external-action): this\n"
                "task's ship is an EXTERNAL OWNER ACTION (e.g. a webmaster/registrar panel action, a\n"
                "DNS-TXT verification), NOT a code diff. Its acceptance is proven by an OWNER-CONFIRMATION\n"
                "probe recorded at Stage-9 Closure — AFTER this audit. So for THIS task the acceptance\n"
                "probe RESULTS are EXPECTED to be ABSENT from the shipped diff right now — that absence\n"
                "(\"AC probe results not in the diff\") is the NORMAL ordering for an external-action ship,\n"
                "NEVER a finding and NEVER a RED. Do NOT flag the probe-results-missing / not-in-diff\n"
                "category as a defect, and do NOT expect a host artifact (URL/file) the external action\n"
                "does not produce (e.g. a DNS-TXT verification leaves no served URL to curl). Judge ONLY:\n"
                "(1) shipped-diff drift from plan, (2) any acceptance criterion the diff/evidence fails\n"
                "to meet that does NOT depend on the deferred external action, (3) coherence with other\n"
                "docs/state. A genuine diff-drift or such an unmet AC is still RED — that judgement is\n"
                "unchanged; ONLY the deferred-to-Closure owner-confirmation proof is exempted.\n"
            )
        if host_config:
            # T-9621 (SPEC-0094 §3 / SPEC-0111) — HOST-CONFIG carve-out (--task audit-post only). The
            # FOURTH SIBLING of event-emit-only / serve-deploy / external-action in the same deferred-
            # adoption family. A host-config task's adoption proof is the THREE hostapply evidences
            # (apply_confirmed / host_health_sweep_passed / host_reconciliation_recorded) RECORDED by the
            # SPEC-0111 apply seam at Stage-9 Closure — AFTER this diff-only Stage-8 audit. So they
            # legitimately do not exist yet at audit-post; the base post overlay reads their absence as the
            # gap → false-RED "adoption missing" (X-0117). Everything else (diff-drift, non-adoption AC,
            # coherence) is judged unchanged.
            overlay += (
                "\nHOST-CONFIG SHIP (per T-9621, this task is flagged --host-config): this task's\n"
                "adoption proof is the THREE host-config apply evidences — apply_confirmed,\n"
                "host_health_sweep_passed, host_reconciliation_recorded — RECORDED by the host-config\n"
                "apply seam (SPEC-0111) at Stage-9 Closure, AFTER this audit. So for THIS task those 3\n"
                "evidences are EXPECTED to be ABSENT from the `### Adoption evidence` section right now —\n"
                "that absence is the NORMAL ordering for a host-config ship, NEVER a finding and NEVER a\n"
                "RED. Do NOT flag the adoption-missing category (the 3 missing apply evidences) as a\n"
                "defect. Judge ONLY: (1) shipped-diff drift from plan, (2) any NON-adoption acceptance\n"
                "criterion the diff/evidence fails to meet, (3) coherence with other docs/state. A genuine\n"
                "diff-drift or a truly-unmet non-adoption AC is still RED — that judgement is unchanged;\n"
                "ONLY the deferred-to-Closure host-config apply evidences are exempted.\n"
            )
        if land_emitted_event:
            # T-10045 (SPEC-0036 / X-0188) — LAND-EMITTED-EVENT carve-out (--task audit-post only). The
            # FIFTH SIBLING of event-emit-only / serve-deploy / external-action / host-config in the same
            # deferred-adoption family, and the GENERALIZATION of event-emit-only to a NON-P8 event. When a
            # task's acceptance probe is an event EMITTED BY `land` AT Stage 9 (e.g. verify_layer_prep) —
            # NOT a P8 closure event — that event legitimately does not exist yet at this pre-land Stage-8
            # audit-post. The event-emit-only overlay is P8-CLOSURE-event-specific, so the auditor does not
            # extend it to an arbitrary land-emitted acceptance event and the base post overlay false-REDs
            # "acceptance probe not satisfied" (X-0188 — T-0073 burned 2 RED passes + a consult on this
            # structural false-RED). Everything else (diff-drift, non-adoption AC, coherence) is unchanged.
            overlay += (
                "\nLAND-EMITTED-EVENT SHIP (per T-10045, this task is flagged --land-emitted-event): this\n"
                "task's acceptance probe is a NON-P8 event EMITTED BY `land` at Stage 9 (e.g. a\n"
                "`verify_layer_prep` / layer-prep event the land verb records), NOT a code-diff artifact\n"
                "and NOT a P8 closure event. It is recorded AFTER this diff-only Stage-8 audit-post. So\n"
                "for THIS task that acceptance event is EXPECTED to be ABSENT right now — that absence is\n"
                "the NORMAL ordering for a land-emitted-event ship, NEVER a finding and NEVER a RED. Do\n"
                "NOT flag the acceptance-probe-not-satisfied / event-absent category as a defect. Judge\n"
                "ONLY: (1) shipped-diff drift from plan, (2) any acceptance criterion the diff/evidence\n"
                "fails to meet that does NOT depend on the deferred land-emitted event, (3) coherence with\n"
                "other docs/state. A genuine diff-drift or such an unmet non-deferred AC is still RED —\n"
                "that judgement is unchanged; ONLY the deferred-to-land acceptance event is exempted.\n"
            )
            # T-11000 (X-0837) — NAME the deferred evidence. Without this the paragraph above exempts an
            # ABSTRACT event while the packet renders the card's ACTUAL deferred evidence concretely
            # below (a not-yet-resolved coordination row in the CROSS-INSTANCE EVIDENCE section), so the
            # auditor cannot match the two and follows the row it can see. The names come from the card's
            # own acceptance (`land_emitted_named_evidence`), and the fail-closed guard has already
            # refused the flag if there were none — so this block is never empty in a real run.
            _named = land_emitted_named_evidence(task)
            if _named:
                overlay += (
                    "The evidence THIS card defers to land, named by its OWN acceptance, is EXACTLY:\n"
                    + "".join(f"  - {n}\n" for n in _named) +
                    "That list is the WHOLE of the exemption — evidence this card does NOT name is NOT\n"
                    "exempted. IMPORTANT, and the reason a previous run of this carve-out still failed: if\n"
                    "one of the names above is a coordination item (an `X-NNNN` id), the CROSS-INSTANCE\n"
                    "EVIDENCE section below will show that row in a NOT-YET-TERMINAL state (e.g. status\n"
                    "`accepted`/`picked`, with no resolution note) — because `land` emits its closing\n"
                    "`cross_done` at the integration step that follows THIS audit. That not-yet-closed row\n"
                    "IS the pending evidence named above; it is NOT an unmet acceptance criterion, and its\n"
                    "unresolved state is NEVER a finding and NEVER a RED. Do not ask for the closed rows or\n"
                    "the resolution note to be quoted before land — they cannot exist yet.\n"
                )
        if preshipped_deliverable:
            # T-10062 (SPEC-0036 / X-0201) — PRE-SHIPPED-DELIVERABLE carve-out (--task audit-post only). The
            # SIXTH SIBLING of event-emit-only / serve-deploy / external-action / host-config /
            # land-emitted-event in the same deferred-adoption family. When a PARKED task is re-claimed but
            # its deliverable ALREADY LANDED in a PRIOR session (<project> T-0131, X-0201), the re-claim
            # diff is gate-proof + closure bookkeeping ONLY and carries NO deliverable — the base post
            # overlay reads that as "code shipped but not invoked" / "nothing shipped" → structural
            # false-RED. UNLIKE the trust-model siblings, the prior deliverable commit is DERIVED from
            # durable task-linked `commit_landed` journal state (the cmd_audit fail-closed guard
            # `_require_preshipped_deliverable` refuses when no such record exists), so the auditor can be
            # told WHICH prior commit shipped the deliverable it is now told is legitimately absent.
            _pc = preshipped_commit or "(prior-session commit)"
            overlay += (
                "\nPRE-SHIPPED-DELIVERABLE SHIP (per T-10062, this task is flagged --preshipped-deliverable):\n"
                "this is a RE-CLAIMED task whose deliverable ALREADY LANDED in a PRIOR session — at commit\n"
                f"{_pc} (derived from this task's durable `commit_landed` journal record, D-0082). So the\n"
                "diff you are auditing NOW is the RE-CLAIM diff: gate-proof + Stage-9 closure bookkeeping\n"
                "ONLY, carrying NO deliverable (the deliverable is in that prior commit, not here). For THIS\n"
                "task the deliverable-absent / 'code shipped but not invoked' / 'nothing shipped' category is\n"
                "EXPECTED — that absence is the NORMAL state for a pre-shipped-deliverable re-claim, NEVER a\n"
                "finding and NEVER a RED. Do NOT flag the deliverable-missing / empty-diff category as a\n"
                "defect. Judge ONLY: (1) any acceptance criterion the diff/evidence + the named prior commit\n"
                "fail to meet, (2) coherence of the re-claim bookkeeping with other docs/state. A genuine\n"
                "unmet acceptance criterion is still RED — that judgement is unchanged; ONLY the\n"
                "already-shipped deliverable's absence from THIS re-claim diff is exempted.\n"
            )
        if foreign_subject:
            # T-12737 (X-1487, <project> T-0084) — FOREIGN-DECLARED SUBJECT (--task audit-post only).
            # NOT a deferred-adoption sibling: nothing is exempted from judgement. The card DECLARED an
            # already-landed commit it did NOT author as its audit-post subject (the CHARTER §P2
            # emergency-bypass retro-audit: the 72-hour post-incident review the bypass skipped). The
            # admission leg proved the commit resolves + is an ancestor of `main`; the reason is the
            # card's own recorded why. What the auditor must NOT do is read "this diff was not
            # authored under this card / does not match this card's scope bullets" as drift — that is
            # the DEFINITION of the route. What it MUST do is the review the bypass skipped: judge the
            # foreign diff on its own merits against the universal lens.
            _fc = str(foreign_subject.get("commit") or "")[:12] or "(declared commit)"
            _fr = str(foreign_subject.get("reason") or "").strip()
            _fe = str(foreign_subject.get("land_evidence") or "").strip()
            overlay += (
                "\nFOREIGN-DECLARED SUBJECT — a RETRO-AUDIT (per T-12737, this card's own "
                "`foreign_audit_subject:` declaration):\n"
                f"the diff you are auditing is commit {_fc}, which this card did NOT author. It landed "
                "EARLIER — under another batch / an emergency bypass — WITHOUT the audit-post the CHARTER "
                "requires, and this card's whole deliverable is to obtain that missing review now. The "
                f"card's recorded reason: {_fr}\n"
                f"Governed-landing trail: {_fe}\n"
                "So: (1) do NOT flag 'the diff does not match this card's scope / plan / expected_touch' "
                "or 'authored under a different task' — that is the NORMAL shape of this route, never a "
                "finding. (2) DO judge the foreign diff itself, fully, on the universal lens: correctness, "
                "spec coherence, security boundary, test evidence, anti-complexity — exactly the review "
                "the bypass skipped. A genuine defect IN THAT DIFF is RED, and it is this card's job to "
                "carry it (file the follow-up naming the defect; the card's acceptance is the review, not "
                "the diff's perfection — say which in your finding). (3) This card's OWN acceptance "
                "criteria are judged as always.\n"
            )
        if settlement_sweep:
            # T-11753 (SPEC-0036 / X-1147) — SETTLEMENT-SWEEP carve-out (--task audit-post only). The
            # SEVENTH SIBLING of preshipped-deliverable / post-ship-observation / land-emitted-event /
            # host-config / external-action / serve-deploy in the same deferred-adoption family. When a
            # card's WHOLE deliverable is settling deferred probes on OTHER cards, `task close
            # --settle-probe` self-commits each settlement AT THE MOMENT IT IS MADE (T-11107 — by
            # design, so a settlement never strands a dirty worktree) and journals it under the SETTLED
            # card's id. So this card's own ship is card YAML + audit records + events.jsonl, and the
            # base overlay reads that as "nothing shipped" — a structural false-RED on a card that did
            # ALL of its work. UNLIKE the trust-model siblings, this is not asserted by a flag: the
            # guard (`_require_settlement_sweep`) has PROVEN each named settlement against durable
            # journal state, so the auditor is handed the settlement commits BY NAME and judges the
            # deliverable rather than being asked to excuse its absence.
            _rows = "".join(f"  - {e.get('task')}: {e.get('commit')}\n"
                            for e in (settlement_commits or []))
            overlay += (
                "\nSETTLEMENT-SWEEP SHIP (per T-11753, this task is flagged --settlement-sweep):\n"
                "this card's DELIVERABLE is a set of deferred-probe SETTLEMENTS made on OTHER cards. Each\n"
                "settlement was SELF-COMMITTED at the moment it was made (T-11107), so the deliverable is\n"
                "in those commits and CANNOT be in the diff you are reading now — this card's own ship is\n"
                "lifecycle bookkeeping (its card YAML, its audit records, events.jsonl) BY CONSTRUCTION,\n"
                "not by omission. The settlements, each PROVEN against the journal (emitted in this card's\n"
                "own session, at or after its work began, and already integrated), are EXACTLY:\n"
                + (_rows or "  (none recorded)\n") +
                "That list is the WHOLE of the exemption. For THIS task the 'nothing shipped' /\n"
                "'deliverable absent from the diff' category is EXPECTED — the NORMAL ordering for this\n"
                "ship — and is NEVER a finding and NEVER a RED. Judge ONLY: (1) any acceptance criterion\n"
                "the diff + the named settlement commits fail to meet, (2) coherence of this card's own\n"
                "bookkeeping with the settlements it claims. A genuine unmet acceptance criterion is still\n"
                "RED — that judgement is unchanged; ONLY the settled deliverable's absence from THIS diff\n"
                "is exempted, and ONLY for the cards named above.\n"
            )
        if post_ship_observation:
            # T-10916 (SPEC-0036 / X-0710) — POST-SHIP-OBSERVATION carve-out (--task audit-post only). The
            # EIGHTH SIBLING of event-emit-only / serve-deploy / external-action / host-config /
            # land-emitted-event / preshipped-deliverable in the same deferred-adoption family. When a
            # task's acceptance probe is a MULTI-DAY POST-SHIP PRODUCTION OBSERVATION («the daily count is
            # flat or falling over 7 days»), the reading legitimately cannot exist at this pre-land,
            # diff-only Stage-8 audit — the observation window has not opened yet. UNLIKE the trust-model
            # siblings, the deferral is not merely asserted by a flag: the guard
            # (`_require_post_ship_observation`) proved the card DECLARES what will be observed and by
            # when, so the auditor is told the concrete observation + due date and the debt stays visible
            # on the overdue-recheck lens until `settled_by` names where the recorded proof landed. That
            # declaration is what keeps this from being a blanket «my proof is in the future» excuse.
            _obs = str((post_ship_observation or {}).get("observation") or "").strip()
            _due = str((post_ship_observation or {}).get("due_by") or "").strip()
            # T-11672 / X-1126 — the SENSITIVITY half of the declaration. Read through the SAME
            # function-local import this branch already uses for this field family: `task.py` imports
            # this module at module level, so the reverse import stays lazy (the audit-pre finding).
            from lib.task import _post_ship_observation_sensitivity as _pso_sens
            _sens = _pso_sens(post_ship_observation)
            if _sens:
                _sens_para = (
                    "SENSITIVITY: the card names this as the evidence that the observation's predicate\n"
                    f"FIRES when the defect IS present: {_sens}\n"
                    "Weigh it under judgement (4) below — an observation settles by READING A PREDICATE,\n"
                    "so a predicate that could never match anything would read EMPTY and be\n"
                    "indistinguishable from «the defect is absent» (a VACUOUS ZERO).\n")
            else:
                _sens_para = (
                    "SENSITIVITY: the card names NO evidence that the observation's predicate fires when\n"
                    "the defect IS present. Naming it is an AUTHORING PROMPT (SPEC-0028), printed\n"
                    "report-only at the declaring seam — its absence is NEVER a finding and NEVER a RED on\n"
                    "its own, and you must NOT raise it as one. Judgement (4) below is unchanged.\n")
            overlay += (
                "\nPOST-SHIP-OBSERVATION SHIP (per T-10916, this task is flagged --post-ship-observation):\n"
                "this task's acceptance proof is a MULTI-DAY POST-SHIP PRODUCTION OBSERVATION — a reading\n"
                "taken from production over a window that opens only AFTER this ship goes out. The declared\n"
                f"observation is: {_obs or '(declared on the card)'}\n"
                f"and its window closes on {_due or '(the declared due_by date)'}. So for THIS task that\n"
                "observation RESULT is EXPECTED to be ABSENT right now — that absence is the NORMAL\n"
                "ordering for a post-ship-observation ship, NEVER a finding and NEVER a RED. Do NOT flag\n"
                "the acceptance-probe-not-satisfied / no-observation-result / adoption-missing category as\n"
                "a defect, and do NOT demand the observation be taken before land — it cannot be. The\n"
                "deferral is TRACKED, not waived: the declaration above is recorded on the card and the\n"
                "pending observation stays on the overdue-recheck debt view until a `settled_by` locator\n"
                "names where the recorded reading landed. Judge ONLY: (1) shipped-diff drift from plan,\n"
                "(2) any acceptance criterion the diff/evidence fails to meet that does NOT depend on the\n"
                "deferred observation, (3) coherence with other docs/state, (4) whether the declared\n"
                "observation actually corresponds to the acceptance criterion it defers. A genuine\n"
                "diff-drift or such an unmet non-deferred AC is still RED — that judgement is unchanged;\n"
                "ONLY the not-yet-observable production reading is exempted.\n"
                + _sens_para
            )
        if activation_gated_radius:
            # T-11014 (SPEC-0176) — ACTIVATION-GATED BLAST-RADIUS carve-out (--task audit-post only). The
            # NINTH SIBLING, and the one that must be written most carefully, because what it defers is
            # SCOPE FIDELITY — the check every other overlay leaves standing. So the paragraph is a
            # PARTITION, not an exemption: it names the claimed-hidden paths exhaustively, re-asserts
            # ordinary enforcement everywhere else, and explicitly invites a RED on a reconciliation entry
            # that looks like ordinary authored work. The guard has already proved the card owns a
            # proposed concern-bearing spec, still carries a non-empty forecast, and that the
            # reconciliation matches the real diff — so none of the lists below is author-asserted.
            _agr_specs = ", ".join(activation_gated_radius.get("specs") or []) or "(the owned proposed spec)"
            _agr_rec = list(activation_gated_radius.get("reconciliation") or [])
            _agr_fc = list(activation_gated_radius.get("forecast") or [])
            _agr_why = str(activation_gated_radius.get("declaration") or "").strip()
            overlay += (
                "\nACTIVATION-GATED BLAST RADIUS (per T-11014, this task is flagged\n"
                "--activation-gated-radius): this card's OWN CLOSURE performs the `proposed → active`\n"
                f"flip of {_agr_specs}, and that spec registers a CONCERN. The concern registry and the\n"
                "activation checklist answer ONLY for specs that are ALREADY active, so the fixtures the\n"
                "activation invalidates were STRUCTURALLY INVISIBLE while this card was planned and\n"
                "audited — the flip that reveals them is performed by the closure that follows THIS\n"
                "audit. An up-front touched-file forecast for those paths could not have been written by\n"
                "anyone, and demanding one is NEVER a finding and NEVER a RED.\n"
                f"The card states the condition as: {_agr_why or '(declared on the card)'}\n"
                "The EXEMPTION IS EXACTLY THIS MEASURED SET — the paths the activation actually reached,\n"
                "verified against the real diff by a fail-closed guard, not accepted on the author's word:\n"
                + "".join(f"  - {p}\n" for p in _agr_rec) +
                "NOTHING ELSE IS EXEMPT. This is not a waiver of scope fidelity; it moves WHEN the\n"
                "evidence for those paths exists. Every OTHER path this ship touches is covered by the\n"
                "card's ORDINARY up-front forecast, which is still required and still governs:\n"
                + "".join(f"  - {p}\n" for p in _agr_fc) +
                "So judge scope fidelity EXACTLY AS USUAL on the forecast paths above — drift there is\n"
                "still RED. And judge the measured set on its own terms: if an entry in the exempted list\n"
                "is plainly ORDINARY AUTHORED WORK rather than a consequence of the activation (a\n"
                "hand-written source change, a feature edit, anything the author could have forecast at\n"
                "Analysis), say so — THAT IS A FINDING and it should be RED. The carve-out covers the\n"
                "activation's blast radius, never the author's convenience.\n"
            )
        if zero_ship_diff:
            # T-12730 (SPEC-0036 / X-1488) — ZERO-SHIP-DIFF re-lens overlay (--task audit-post only),
            # RESTORED. T-10084 had turned this flag into a SHORT-CIRCUIT that recorded GREEN without
            # invoking the auditor; <project> MEASURED that on a call whose `--from-file` carried
            # the whole commit diff — a subject to judge, silently discarded. A waive must never stand
            # in for the auditor: the flag now only tells the auditor WHICH absence is expected (the
            # authored ship-diff — proven zero by the fail-closed `_require_zero_ship_diff` guard) and
            # hands it the named evidence + whatever subject the caller supplied.
            _loc = evidence_locator or "(none named)"
            overlay += (
                "\nZERO-SHIP-DIFF SHIP (per T-12730, this task is flagged --zero-ship-diff):\n"
                "this is a close of an ALREADY-LIVE task whose authored ship-diff is ZERO after subtracting\n"
                "governed lifecycle bookkeeping (task YAML, events.jsonl, the task's own audit records) —\n"
                "PROVEN by a deterministic fail-closed guard before you were invoked, so the shipped diff\n"
                "you see carries bookkeeping ONLY. For THIS task the empty-diff / 'nothing shipped' /\n"
                "'code shipped but not invoked' category is EXPECTED — NEVER a finding and NEVER a RED on\n"
                f"its own. The close rests on the named immutable evidence: {_loc}. JUDGE: (1) whether\n"
                "that evidence, plus any subject supplied below (an explicit diff or record passed in by\n"
                "the caller), actually MEETS every acceptance criterion — a criterion the evidence fails\n"
                "is RED exactly as usual; (2) coherence of the closure bookkeeping with the card and the\n"
                "journal. Only the authored-diff absence is exempted; nothing else is.\n"
            )
        if reaudit_after_close:
            # T-9456 — CLOSURE-IN-DIFF-EXPECTED carve-out (--task audit-post --reaudit-after-close only).
            # The SIBLING of the event-emit-only / serve-deploy carve-outs, but inverted: those exempt an
            # ABSENT adoption artifact; this exempts a PRESENT closure artifact. A re-audit of an
            # already-CLOSED task audits HEAD, whose diff INCLUDES the Stage-9 closure metadata (status:
            # done + recorded probes + the task_closed bookkeeping) — the base post overlay's STAGE BOUNDARY
            # note expects that metadata to be ABSENT (Stage 9 follows the auditor) and would otherwise
            # false-RED "closed inside shipped diff". This carve-out tells the auditor the closure-in-diff
            # is the NORMAL state for a post-close re-audit, never a finding (the false-RED that blocked
            # T-9445's --rebaseline land — no GREEN/YELLOW audit-post → --rebaseline refused).
            overlay += (
                "\nPOST-CLOSE RE-AUDIT (per T-9456, this task is flagged --reaudit-after-close): this is a\n"
                "FRESH audit-post over the CURRENT tree (HEAD) of an ALREADY-CLOSED (status: done) task —\n"
                "re-baselining a legitimate post-close source change. So UNLIKE a normal in-progress\n"
                "audit-post, the shipped diff CONTAINS this task's Stage-9 closure metadata (status: done\n"
                "in the task YAML, the recorded acceptance probes, the task_closed bookkeeping). That\n"
                "closure-in-diff is EXPECTED and is the NORMAL state for a post-close re-audit — NEVER a\n"
                "finding and NEVER a RED. Do NOT flag the 'closed inside shipped diff' / 'task marked done\n"
                "in the diff' category as a defect; the STAGE BOUNDARY note above (which expects closure\n"
                "metadata to be absent) is REVERSED for this re-audit. Judge ONLY: (1) shipped-diff drift\n"
                "from plan, (2) any acceptance criterion the diff/evidence fails to meet, (3) coherence\n"
                "with other docs/state. A genuine diff-drift or a truly-unmet acceptance criterion is\n"
                "still RED — that judgement is unchanged; ONLY the expected closure-in-diff is exempted.\n"
            )
        # T-13538 — EVERY task-tied `tests_passed` row since the claim, not only the latest: the
        # red-run rows a card records with `task test --evidence` are the differential half of its
        # proof, and the auditor could not see them. ONE read (it replaces the single-row read, so
        # the fold count is unchanged); a caller that injects no multi-row reader keeps the
        # single-row view. `tp` stays the row rendered LAST and in full — the readiness block below
        # reads it. A VIEW only: these rows never enter `evidence_sink` (the counted set).
        if task_events_for is not None:
            _s6_rows = list(task_events_for(task.get("id"), ("task_picked", "tests_passed")) or [])
        else:
            _s6_one = latest_event_for(task.get("id"), "tests_passed")
            _s6_rows = [_s6_one] if _s6_one else []
        _s6_shown, _s6_omitted, _s6_pre_claim = stage6_rows_since_claim(_s6_rows)
        tp = _s6_shown[-1] if _s6_shown else None
        stage6 = stage6_evidence_section(
            _s6_shown, _s6_omitted, _s6_pre_claim,
            churn_note=_merge_tie_ordering_note(churn_tie) if (tp and churn_tie) else "",   # T-12718
            yaml_dump_block=yaml_dump_block, keep_within_budget=_keep_within_budget)
        # Adoption / AC-probe evidence (T-0236 + T-0290 + T-0551): surface the task's diff-invisible
        # journal events HERE because events.jsonl is excluded from the audit diff (T-0219) — without
        # this the auditor cannot see an event-based AC probe. T-0290 broadens beyond the two P8 types
        # to the AC-probe evidence-class (e.g. spec_edited, tied via cites:); T-0551 ALSO ties a
        # spec_edited event when the spec file it edited is touched by the shipped diff (the recurring
        # T-0549/T-0550 false-RED: a task edits a spec it does not cite). The touched spec paths come
        # from the SAME diff `diff_touched_files` already parses for the spec-coverage section.
        # Normalize each touched path FIRST, then filter — so a non-canonical `./specs/...` form from
        # diff_touched_files survives the spec-file filter and reaches the path-tie (T-0551 audit-post
        # F0). ac_probe_evidence_events_for re-normalizes both sides, so passing normalized paths here
        # is idempotent.
        touched_spec_paths = [np for np in (norm_repo_path(p) for p in diff_touched_files(diff or ""))
                              if re.match(r"specs/SPEC-[\w.-]+\.yaml$", np)]
        # T-10827 (X-0686) — collect the TYPES this pass dropped for the type-opt-in reason alone, so
        # the section below can NAME them instead of rendering an unexplained empty block.
        excluded_types = set()
        # T-12337 — the rows the CARD-WINDOW predicate dropped, collected on the SAME single pass
        # (no second call, no second journal read) so the section can state the count out loud below.
        window_excluded = []
        # T-12454 — sandbox lifecycle rows that failed the evidence rule, same single pass.
        sandbox_excluded = []
        evidence_events = ac_probe_evidence_events_for(task, touched_paths=touched_spec_paths,
                                                       excluded_types_sink=excluded_types,
                                                       window_excluded_sink=window_excluded,
                                                       sandbox_excluded_sink=sandbox_excluded)
        # T-10741 (SPEC-0168 rule 5) — hand the COUNTED set to the caller AT THE COUNTING MOMENT, so
        # it can be recorded durably per task. Guarded because a recording path must never raise into
        # an audit run (AC2): the sink is caller-supplied, so a bad one degrades to "not recorded".
        if evidence_sink is not None:
            try:
                evidence_sink.extend(evidence_events)
            except Exception:      # noqa: BLE001 — observation only; an audit never fails on capture
                pass
        if evidence_events:
            # T-9248: surface `probe`/`marker`/`detail` too — a P8 live_trigger/consumer-read event
            # carries its task-SPECIFIC proof in those fields (e.g. the routing detail of a live
            # trigger). T-9626: extracted to _format_adoption_evidence_lines so the consult branch
            # reuses the SAME rendering. Render them so the proof is visible.
            adoption = _format_adoption_evidence_lines(evidence_events)
        else:
            adoption = ("(no P8 adoption event — consumer_read_evidence / live_trigger_evidence — and no\n"
                        "other AC-probe event — e.g. spec_edited tied via cites: or via a spec file in the\n"
                        "shipped diff — recorded for this task.\n"
                        "For an infra-class task a missing P8 event may be a real adoption gap; for a\n"
                        "product-class task a probe/state-check is the carrier instead. Its absence from the\n"
                        "DIFF is expected (events.jsonl is excluded per T-0219) and is not itself a finding.)")
        adoption += _format_type_optin_exclusion_note(excluded_types)
        # T-13508 — hand the SAME set to the caller, so `audit post` can name the excluded types in
        # its own output (the `evidence_sink` shape: caller-supplied, guarded, observation only).
        if optin_excluded_sink is not None:
            try:
                optin_excluded_sink.extend(sorted(t for t in excluded_types if t))
            except Exception:      # noqa: BLE001 — observation only; an audit never fails on capture
                pass
        adoption += _format_sandbox_evidence_exclusion_note(sandbox_excluded)
        # T-12337 — and the sibling exclusion note for the card-window narrowing (SPEC-0165):
        # a shrunken section must never read like an empty corpus. Renders "" when nothing
        # was excluded, so the packet is byte-identical on the no-exclusion path.
        adoption += _format_window_exclusion_note(len(window_excluded))
        # T-11778 — the per-touched-test-file COLLECTOR SHAPE, appended to this same diff-invisible
        # evidence section. The collector of a test file a card only ADDS an arm to is unchanged and
        # therefore absent from the diff, so the auditor cannot tell auto-discovery from a
        # hand-maintained list and REDs the arm as unwired (fired twice in six hours — T-11778 scope).
        # Report-only; renders "" when the diff touches no tests/*.py. Guarded because a rendering path
        # must never raise into an audit run — the same posture the evidence sink and the cross-evidence
        # section take just below/above.
        if repo_root is not None:
            try:
                touched_test_paths = [np for np in (norm_repo_path(p) for p in diff_touched_files(diff or ""))
                                      if re.match(r"tests/[\w./-]+\.py$", np)]
                adoption += _format_collector_shape_note(touched_test_paths, repo_root)
            except Exception:      # noqa: BLE001 — report-only; an audit never fails on a derived fact
                pass
        # T-10915 (X-0695) — the task-tied SHARED-STORE coordination items, rendered with visible
        # cross-instance provenance. A separate section on purpose: the store stays outside the repo
        # (SPEC-0084 rule 5) and these rows stay outside the rule-5 counted set (they cannot land
        # here). Guarded — an evidence read must never fail an audit (the same posture the sink takes).
        if cross_evidence_section_for is not None:
            try:
                # T-12590 — HOLD the render: the flip guard's `cross_section` axis digests exactly
                # the text the auditor reads, via its OWN sink — never `evidence_sink`, so these rows
                # stay outside the rule-5 counted set.
                _cross_render = cross_evidence_section_for(task) or ""
                adoption += _cross_render
                if cross_section_sink is not None:
                    cross_section_sink.append(_cross_render)
            except Exception:      # noqa: BLE001 — report-only; an audit never fails on an evidence read
                pass
        # T-11995 — the SPEC-0015 THIRD adoption satisfier: the task's OWN filed blocking adoption
        # follow-up(s), rendered as a carrier rather than as an anonymous `followup_added` bullet.
        # Host-injected exactly like the cross-evidence section above (the fold needs the journal
        # path this engine does not hold) and guarded on the same posture: report-only, never fatal
        # to an audit, and never entered into the SPEC-0168 rule-5 counted `evidence_sink` — this
        # renders a DECLARATION the auditor must weigh, not a counted evidence row.
        if p8_carrier_section_for is not None:
            try:
                # T-12009 — HOLD the render: this one string is the body AND the readiness row's
                # third satisfier. Re-calling the injector, or re-folding the followups for the row,
                # would reintroduce the very split this card removes.
                _p8_carrier_block = p8_carrier_section_for(task) or ""
                adoption += _p8_carrier_block
            except Exception:      # noqa: BLE001 — report-only; an audit never fails on an evidence read
                pass
        # T-11761 (X-1166) — the DECLARED SUBSTITUTED ACCEPTANCE INSTRUMENT, rendered to the auditor.
        # NOT a tenth deferred-adoption overlay, and deliberately so: every overlay in that family
        # exempts an ABSENCE (a proof that cannot exist yet at this pre-land, diff-only stage). Here
        # there is no absence to exempt — the measurement WAS taken; what the auditor lacked was the
        # knowledge of WHICH instrument produced it, so it read evidence-taken-another-way as evidence
        # missing and RED-ed (<project> T-0506: the planned nightly runs against LANDED state, so its
        # AFTER reading was structurally unavailable pre-land and the worker directly called the same
        # detector functions the nightly uses — sound, unrecorded, one wasted audit pass).
        #
        # The carrier is a CARD FIELD, so this follows the T-10947 precedent exactly: RENDER what the
        # builder already holds. No CLI flag, no fail-closed guard, no store, no event type — and
        # nothing here EXEMPTS anything. The auditor is told which instrument was run and why the
        # planned one could not be; whether that substitution actually satisfies the criterion stays
        # entirely its judgement, and an unmet AC is still RED.
        #
        # THE DECLARATION IS THE TRIGGER, fail-closed: rendered only when `substituted_instrument` is
        # GRAMMAR-VALID per the single-home `_substituted_instrument_declaration_error` (CHARTER §P5),
        # so a reasonless or instrument-less declaration renders NOTHING and can never present itself
        # as a valid substitution. Read through a FUNCTION-LOCAL import, the form this file already
        # uses for the `post_ship_observation` family: `task.py` imports THIS module at module level,
        # so the reverse import must stay lazy. Gated to a TASK audit-POST — the stage that judges the
        # shipped evidence, and the stage that RED-ed.
        _subst_block = ""
        _si = task.get("substituted_instrument")
        if _si is not None and stage == "post":
            from lib.task import _substituted_instrument_declaration_error
            if _substituted_instrument_declaration_error(_si) is None:
                _si_inst = str((_si or {}).get("instrument") or "").strip()
                _si_why = str((_si or {}).get("reason") or "").strip()
                _subst_block = (
                    "### Substituted acceptance instrument (the differential was taken another way)\n"
                    "This task's card DECLARES that an acceptance differential below was measured with a\n"
                    "DIFFERENT INSTRUMENT than the one it planned, because the planned one could not run\n"
                    "before this ship lands.\n"
                    f"- instrument actually run: {_si_inst}\n"
                    f"- why the planned instrument was unavailable pre-land: {_si_why}\n"
                    "So evidence produced by the instrument named above is NOT thereby missing evidence,\n"
                    "and «the planned probe was not run» is NOT on its own a finding here. NOTHING IS\n"
                    "EXEMPTED: the requirement that a differential EXIST is unchanged, and you must still\n"
                    "judge whether the substituted instrument actually measures the criterion it stands in\n"
                    "for — if it does not, or if the stated reason does not hold, THAT IS A FINDING and it\n"
                    "should be RED. Every other acceptance criterion is judged exactly as usual.\n\n")
        # T-12237 — the DEFERRED-BY-DECLARATION section (rendered at audit-pre too since T-13150).
        # Placed immediately after the acceptance list and BEFORE the plan, the test
        # evidence and the diff, so the auditor reads WHICH criteria are deferred before it reads
        # the evidence it would otherwise find them missing from. Inert ("") on a card that
        # declares nothing, so no unrelated packet changes.
        body = (
            f"## Task: {task.get('id')} — {task.get('title', '')}\n\n"
            f"### Acceptance criteria\n{yaml_dump_block(task.get('acceptance') or [])}\n\n"
            f"{_declared_probe_block}"   # T-12312 — the filing-time declaration, both stages
            f"{_deferred_block}"
            f"{_subst_block}"
            f"### Implementation plan\n{task.get('implementation_plan') or '(empty)'}\n\n"
            # T-12756 — the SAME block the audit-pre body renders, from the SAME hoisted expression
            # (one source). Placed after the plan and before the test evidence, so the auditor reads
            # what the card RECORDED at Stage 1 before it judges the evidence it would otherwise find
            # missing. Heading emitted UNCONDITIONALLY with the same absent-marker, for the same
            # reason as in pre: a vanishing section would turn this false RED into a false GREEN.
            f"### Analysis (Stage-1 record from the card)\n{_analysis_block}\n\n"
            f"### Stage-6 test evidence\n{stage6}\n\n"
            f"### Adoption evidence (CHARTER §P8 + journal-event AC probes)\n{adoption}\n\n"
            f"### Shipped diff\n```diff\n{diff or '(no diff captured)'}\n```\n"
        )
    if target_kind == "consult":   # T-0429 — strict survivors/recommendation schema for the triage
        output_spec = (
            "## Output\n\n"
            "Return strict YAML at the END of your response. The `survivors:` list MUST be a SUBSET\n"
            "of the submitted option numbers above; `recommendation:` MUST be EXACTLY ONE of the\n"
            "survivors (a single option number). If no option is defensible, return `verdict: ABORT`\n"
            "with `survivors: []`. Do NOT invent options outside the submitted set.\n"
            "```yaml\n"
            "verdict: GREEN | YELLOW | RED | ABORT\n"
            "survivors: [<option-number>, ...]   # subset of the submitted options\n"
            "recommendation: <single option-number>   # exactly one of survivors (omit if survivors is empty)\n"
            "notes: <free-form rationale, optional>\n"
            "```\n"
        )
    else:
        # T-12293 (AC3) — the ASK half of SPEC-0204 rule 1's per-finding contract. The ENFORCEMENT
        # half lives at the parse floor in `cmd_audit` (`red_findings_missing_contract_fields`), and
        # a floor without its ask is an unbounded refuse-and-retry loop, never a contract: the
        # measured asymmetry was 15/15 consult findings carrying the fields (that prompt asks) vs
        # 3/3 base findings lacking them (this one did not). The three field lines are the
        # CONSULT prompt's own wording (`_CONSULT_BASELINE_OUTPUT_BLOCK`), reused verbatim so the
        # two prompts cannot drift apart. `severity` / `what` / `where` / `fix` are unchanged.
        output_spec = (
            "## Output\n\n"
            "Return strict YAML at the END of your response. Single `verdict:` line on its own:\n"
            "```yaml\n"
            "verdict: GREEN | YELLOW | RED | ABORT\n"
            "findings:\n"
            "  - severity: high | medium | low\n"
            "    what: <one-line>\n"
            "    where: <file:line or scope ref>\n"
            "    fix: <one-line concrete>\n"
            "    criterion_ref: <an EXACT acceptance-criterion id of this target's lens>   # or class_id\n"
            "    locator: <file:symbol or scope ref>\n"
            "    failing_input: <the concrete input/state that demonstrates it>\n"
            "notes: <free-form, optional>\n"
            "```\n"
            "On a **RED** verdict the last three keys are REQUIRED on EVERY finding: `criterion_ref`\n"
            "(the `AC<n>` of this target's lens that the finding fails) OR `class_id`, plus `locator`\n"
            "and `failing_input`. A RED finding lacking any of them is MALFORMED and is DROPPED —\n"
            "it is not recorded as a finding and cannot be acted on, so a real defect spelled\n"
            "without these keys is a defect nobody fixes. Its well-formed SIBLINGS are unaffected:\n"
            "they are recorded and the verdict stands, with each dropped finding named by index and\n"
            "its text preserved. If EVERY finding is malformed the whole response is discarded\n"
            "unread. A GREEN / YELLOW / ABORT verdict is unaffected.\n"
            # T-12405 (X-1367 / X-1342) — the slot was asked for with no vocabulary, so spec-coverage
            # / P8 / process findings (which fail no ACn) kept arriving without it. Rendered FROM the
            # two constants, never re-listed, so the prompt and the engine cannot drift apart.
            "A finding that fails no `AC<n>` MUST carry `class_id`, one of (SPEC-0036 §Saved audit\n"
            "result): " + " | ".join(class_id_vocabulary()) + ".\n"
        )
    # T-9681 — MONOTONIC per-pass re-audit (SPEC-0036 §Monotonic per-pass re-audit prompt). On pass
    # N>=2 (a prior audit record exists for this target+stage) the section LEADS the prompt — placed
    # AFTER the fixed lens but BEFORE the fresh-survey overlay/body — so the auditor accounts for the
    # prior findings FIRST instead of re-surveying (kills X-0134 RC1a). Gated to the absorption-loop
    # audits (task/plan pre/post); consult/ad-hoc/decision carry their own prior-trail handling and the
    # caller passes them no prior_record. Never blinds the auditor — a genuinely-new REAL defect still
    # blocks (constraint #2). The prompt_excerpt opens at the lens (T-0350 F3) regardless.
    # T-12288 (SPEC-0204 rule 8) — THE ROUND FORK, below the ceiling. The discriminator is the
    # SPEC-0124 PASS NUMBER (`prior_passes`), NOT whether the monotonic section happened to render.
    # Those two are usually the same fact and come apart in exactly one case an audit-pre pass named:
    # a pass-2 whose prior record carries NO usable verdict (an ABORT, an unparseable response) renders
    # no monotonic section, and keying on the section would then hand pass 2 the whole-subject SURVEY —
    # the one thing rule 8 says a later pass must never receive. Keyed on the counter, a pass >= 2 gets
    # the delta discipline whether or not there is a prior list to point at
    # (`delta_discipline_block(has_prior_findings=...)` drops the pointing sentences instead).
    # Pass 1 gets the whole-subject survey directive; a later pass gets the delta discipline INSTEAD.
    # NEVER BOTH: shipping both from one home is what T-12141 did, and it ordered a fresh whole-subject
    # survey on every pass (audit-post RED share 16% -> 44%, max consult rounds per (task, stage)
    # 1 -> 11) before being withdrawn whole by T-12168.
    # T-12571 (SPEC-0205 rules 5/6) — inert for every card without a prototype reading (byte-unchanged).
    if target_kind == "task" and stage == "pre" and prototype_diff and task.get("prototype_ref"):
        overlay += (f"\n### Prototype diff (the specification — prototype_ref: {task.get('prototype_ref')})\n"
                    f"```diff\n{prototype_diff}\n```\n\n" + PROTOTYPE_PRE_OVERLAY)
    if target_kind == "task" and stage == "post" and prototype_identity:
        _pi = prototype_identity
        overlay += (f"\nprototype_identity: prototype_ref {task.get('prototype_ref') or 'none declared (partial overlap reported, not refused)'} — whole-file hits "
                    f"{', '.join(_pi.get('whole_file_hits') or []) or 'none'}; hunk-subset "
                    f"{_pi.get('hunk_subset')}; verbatim share {_pi.get('verbatim_share')}"
                    f"{' (best ' + str(_pi.get('best_spike')) + ')' if _pi.get('best_spike') else ''}"
                    f"{'; not computed: ' + str(_pi.get('error')) if _pi.get('error') else ''} — "
                    f"cited from {_pi.get('source_type')} {_pi.get('source_row')} (a projection of that "
                    f"row, never recomputed; SPEC-0205 rule 6). Judge the derivation: the share is "
                    f"context, not a verdict.\n")
    parts = [lens]
    _task_absorption =target_kind == "task" and stage in ("pre", "post")
    _later_pass = _task_absorption and int(prior_passes or 0) >= 1
    _prior_rendered = False
    if prior_record and target_kind in ("task", "plan") and stage in ("pre", "post"):
        _mono = _format_monotonic_reaudit_section(
            prior_record, stage, cur_plan=task.get("implementation_plan"), cur_diff=diff,
            amend_notes=task.get("amend_notes"),   # T-11733 — a plan target carries none → omitted
            delta_discipline=_task_absorption)     # rule 8 is scoped to the TASK audit-pre/post axis
        if _mono:
            parts.append(_mono)
            _prior_rendered = True
    if _later_pass:
        parts.append(delta_discipline_block(_prior_rendered))
    elif _task_absorption:
        parts.append("\n" + BASE_PASS1_SURVEY_CLAUSE)
    # T-12289 (SPEC-0204 rule 3) — the DECISION-AWARE section of the ONE bounded pass past the
    # ceiling. Appended AFTER the monotonic/delta-discipline section because it REFINES it: the delta
    # section tells the auditor to judge the prior findings' closure, and this one says which of them
    # the Controller has already settled and how. `on_decisions` is the projection
    # (`on_decisions_projection`) or None; every existing caller passes None and renders
    # byte-identically.
    if on_decisions:
        parts.append(on_decisions_packet_block(on_decisions))
    parts.extend([overlay, body])
    # T-0444: derived spec-coverage of touched files — TASK pre/post only (decision/plan/adhoc/consult
    # unaffected). Appended right after the body so the auditor sees governing specs + drift flags
    # while answering the two coverage questions the overlay now asks. Report-not-block.
    if target_kind == "task" and stage in ("pre", "post"):
        # T-11977 — the stale-anchor pairs the readiness block reports come from the coverage
        # helper's OWN drift walk, handed back through a sink: a view over the computation that
        # already ran, never a re-parse of the section it rendered. The 4-arg form is used ONLY when
        # a readiness block is being built, so every non-preview caller (and any 3-arg helper a test
        # injects) is reached exactly as before.
        _stale_anchors: list = []
        if readiness_sink is not None:
            try:
                _cov = spec_coverage_section(task, stage, diff, _stale_anchors)
            except TypeError:      # an injected 3-arg helper — the block simply reports no anchors
                _cov = spec_coverage_section(task, stage, diff)
        else:
            _cov = spec_coverage_section(task, stage, diff)
        if _cov:
            parts.append(_cov)
        # T-9315 (F-014 / X-0023): when the diff touches scenarios/, surface the governing scenario
        # contract (SPEC-0076) so the auditor judges against the real doctrine (the `(ungoverned)`
        # marker is sanctioned) instead of inventing a coverage rule. Report-only; omitted otherwise.
        # SPEC-LESS by justification (audit-pre F1): this is prompt-ASSEMBLY plumbing — the same class
        # as the spec_coverage_section / build_referenced_files_section injected helpers above, none of
        # which carry a governing spec; the GOVERNING rule is SPEC-0076 (embedded), and SPEC-0036 (the
        # auditor contract) is documentary with no implements: anchors. No new rule is born here.
        if scenario_contract_section is not None:
            _scn = scenario_contract_section(task, stage, diff)
            if _scn:
                parts.append(_scn)
        # T-12977 (SPEC-0036 audit-post overlay) — the proposed specs THIS card's close activates, each
        # with its anchors and the all-specs SPEC-0151 result. Audit-post only: that is the last gate
        # before the flip. FAIL-VISIBLE, never fail-open (audit-pre RED fp1:2d1b8e0492009bf1): a raising
        # helper renders an explicit UNAVAILABLE block, because an omitted section reads exactly like
        # "this card activates nothing" — the silence the section exists to end.
        if stage == "post" and activation_section is not None:
            try:
                _act = activation_section(task)
            except Exception as exc:      # noqa: BLE001 — rendered, not swallowed
                _act = ("## Activates at closure — UNAVAILABLE (T-12977)\n\n"
                        f"The packet could not derive which proposed specs this card activates "
                        f"({type(exc).__name__}: {exc}). Treat every activation this card may perform as "
                        "UNVERIFIED: no GREEN may rest on an activation the packet could not show.\n")
            if _act:
                parts.append(_act)
        # T-11820 — the declared-vs-audited touch reconciliation, rendered INTO the packet. Appended
        # HERE, inside the one assembler, is the whole of the preview/real identity guarantee: the
        # preview writes THIS string and the real invocation hands the auditor THIS string, so the two
        # cannot disagree by construction (SPEC-0036 §Packet preview names a second assembler as the
        # thing to refuse, and none is added). AUDIT-POST ONLY: audit-pre carries no diff (`diff` is
        # None until the post paths assign it), so a pre-stage reconciliation would report every
        # declared path as declared-only against an empty audited set — noise, and audit-pre already
        # has `_forecast_touched_files` (T-0444) as its forecast surface. Guarded like its two
        # neighbours above: a derived rendering must never raise into an audit run.
        if stage == "post":
            try:
                _touch = packet_touch_section(
                    packet_touch_reconciliation(task.get("expected_touch"), diff))
                if _touch:
                    parts.append(_touch)
            except Exception:      # noqa: BLE001 — report-only; an audit never fails on a derived fact
                pass
        # T-11977 (SPEC-0036 §Packet preview) — THE PREVIEW PATH, and the whole of it: when the
        # caller supplied a `readiness_sink` (only `--preview` does), render the report-only
        # readiness block from the parts computed ABOVE in this same pass — the acceptance list, the
        # adoption evidence this pass counted, the Stage-6 row, the coverage walk's stale anchors,
        # the touch reconciliation, and the prior record. That placement IS the "no second
        # assembler" guarantee SPEC-0036 §Packet preview names as the thing to refuse. It appends
        # NOTHING to `parts`: the packet is unchanged, so a preview stays byte-identical to the real
        # invocation (T-11407 AC2). Guarded like its neighbours — an ADVISORY must never raise into
        # an audit run; a failure costs the reader the block and nothing else.
        if readiness_sink is not None:
            try:
                _touch_recon = packet_touch_reconciliation(task.get("expected_touch"), diff)
                _ev_types = {str((ev or {}).get("type") or "") for ev in (evidence_events or [])}
                _deferred = next((f for f in PACKET_READINESS_DEFERRED_FIELDS if task.get(f)), None)
                # The count is the FOLD of the D2 diagnostic: it is non-zero only when the previous
                # verdict was RED and nothing is on record for this card since it — in which case
                # every finding of that verdict is still unanswered.
                _unanswered = 0
                if (readiness_journal_silent
                        and isinstance(prior_record, dict)
                        and str(prior_record.get("verdict") or "") == "RED"):
                    _unanswered = len(prior_record.get("findings") or [])
                # T-12009 — CHARTER §P8 accepts THREE carriers, and this row now reads all three:
                # the two adoption EVENT types, plus the blocking-followup carrier the packet BODY
                # already rendered above. Presence is `bool(_p8_carrier_block)` — the body's own
                # render, not a second derivation — so the row and the body agree by construction.
                _p8_carrier_ids = p8_carrier_ids_in_section(_p8_carrier_block)
                # T-12013: what counts as a test reference is the PROJECT's declaration
                # (`tests.classes[].globs`) when it has one — resolved here, from the `repo_root`
                # this assembler already holds (T-11778), so the section itself stays pure. Read
                # through the ONE recognizer's own reader; an unreadable declaration yields `[]`
                # and the row reads exactly as it did before this card.
                _test_globs = ()
                if repo_root is not None:
                    from lib.task import declared_test_globs as _declared_test_globs  # lazy: cycle
                    _test_globs = _declared_test_globs(repo_root)
                readiness_sink.append(packet_readiness_section(
                    task.get("acceptance"), task.get("class"), _ev_types,
                    stage6_present=bool(tp), p8_present=bool(
                        _ev_types & {"consumer_read_evidence", "live_trigger_evidence"}
                    ) or bool(_p8_carrier_block),
                    deferred_field=_deferred, stale_anchors=_stale_anchors,
                    touch_recon=_touch_recon, prior_findings_unanswered=_unanswered,
                    p8_carrier_ids=_p8_carrier_ids, declared_test_globs=_test_globs))
            except Exception:      # noqa: BLE001 — report-only; an audit never fails on a derived fact
                pass
    # T-0350 (SPEC-0036 --focus): the composable owner/session append — AFTER the overlay+body,
    # never replacing them; deterministically BEFORE ## Extra context (--prompt-extra).
    if focus:
        parts.append(f"## Focus questions (owner/session --focus append — SPEC-0036)\n\n"
                     f"Answer these IN ADDITION to the overlay above (the append never replaces it):\n\n"
                     f"{focus}\n")
    # T-0035: enrich audit-pre с referenced-file excerpts. Audit-post already has diff
    # via _get_audit_post_diff — only pre needs this. Task-only (decisions have no code-path refs).
    if target_kind == "task" and stage == "pre":
        refs_section = build_referenced_files_section(task)
        if refs_section:
            parts.append(refs_section)
    if extra:
        parts.append(f"## Extra context\n\n{extra}\n")
    # T-12289 (SPEC-0204 rule 3) — the ASK half of `echo_of`, added to the base output contract ONLY
    # on the rule-3 pass. The ENGINE-VERIFIED matching (`on_decisions_matrix`) is worthless without
    # it: an auditor never told the key exists cannot supply it, every re-raised residual would count
    # NEW, and an all-accept set would read RED — the exact asymmetry the C1 parse floor's own ask
    # was added to avoid. Scoped to this pass, because `echo_of` means nothing below the ceiling.
    if on_decisions:
        output_spec = output_spec + (
            "On THIS pass every finding that RE-RAISES a residual of the ceiling table above MUST\n"
            "additionally carry `echo_of: <that residual's EXACT fingerprint>`. The engine VERIFIES it\n"
            "against that table: an unverifiable value is DROPPED and the finding counts as a NEW one.\n")
    parts.append(output_spec)
    # T-11328 — the TOTAL bound, at the ONE site where the packet becomes a packet. Every ceiling
    # before this one bounded a single segment; this is the first thing that measures the join. A
    # packet inside the ceiling passes through byte-identical, so an ordinary audit is unchanged.
    bounded, _packet_elisions = _bound_packet_total("\n".join(parts))
    return bounded


def _card_declares_forecast(artifact) -> bool:
    """T-12623 — does this card carry a USABLE `expected_touch` forecast at all? The field is
    OPTIONAL (dispatch.py reads an absent forecast as UNKNOWN, load-bearing), and a card that
    declares none cannot PROVE a file is uncreated — so the audit-pre absent-file arm fails open
    there. Stated as its own predicate so that bound is read from one place. Pure; never raises."""
    rows = (artifact or {}).get("expected_touch") if isinstance(artifact, dict) else None
    if not isinstance(rows, (list, tuple)):
        return False
    return any(str(e).split("#", 1)[0].strip() for e in rows)


def _card_forecasts_path(artifact, file_rel, *, symbol=None) -> bool:
    """T-12623 — does THIS card's own `expected_touch` forecast `file_rel`?

    The forecast is already DECLARED machine-readably on the card, so the audit-pre absent-file arm
    reads it rather than parsing a plan's prose about what it "proposes to create". Entries are
    normalized through the shared touch-unit vocabulary (`dispatch._touch_unit_path` semantics,
    re-spelled here only as the `#symbol` strip the leaf already documents) and matched three ways:
    exact, `fnmatch` glob (`tests/*`), and directory prefix (`tests/`). Pure; never raises.

    `symbol` (T-12717) NARROWS the question to «does the card forecast THIS SYMBOL in that file?»: an
    entry then matches only when its path half matches AND its `#symbol` half equals `symbol` — a
    bare-file entry names no symbol and does not match. This is the absent-SYMBOL arm's forecast read
    (audit-post finding 1: forecasting the FILE alone leaves the symbol named nowhere on the card)."""
    rows = (artifact or {}).get("expected_touch") if isinstance(artifact, dict) else None
    target = str(file_rel or "").strip()
    if not isinstance(rows, (list, tuple)) or not target:
        return False
    for entry in rows:
        unit, _sep, entry_symbol = str(entry).partition("#")
        unit = unit.strip()
        if unit.startswith("./"):
            unit = unit[2:]
        if not unit:
            continue
        if symbol is not None and entry_symbol.strip() != str(symbol):
            continue
        if unit == target or fnmatch.fnmatch(target, unit):
            return True
        if target.startswith(unit.rstrip("/") + "/"):
            return True
    return False


def class_id_vocabulary(*, CONSULT_BLOCKING_CLASS_IDS, _FINDING_CLASS_SNIFFS) -> list:
    """T-12405 — the closed `class_id` vocabulary the base audit prompt names: SPEC-0200 rule 3's six
    blocking classes, then the `_FINDING_CLASS_SNIFFS` names in their sniff order. Derived from both
    constants, so a class added to either reaches the prompt without a second edit."""
    return sorted(CONSULT_BLOCKING_CLASS_IDS) + [cls for _rx, cls in _FINDING_CLASS_SNIFFS]


def _declares_owed_settlement(entry) -> bool:
    """True only when the acceptance entry DECLARES that its own proof is settled after the ship.

    Fail-closed in the direction that WITHHOLDS the exemption: when in doubt, no row, and the
    criterion is judged exactly as usual.
    """
    text = str(entry or "")
    if _DEFERRED_UNTIL_RE.search(text):
        return True
    if not _SETTLE_VERB_RE.search(text):
        return False
    return _OWED_DECLARATION_RE.search(_SETTLE_VERB_RE.sub(" ", text)) is not None


def _pso_declared_criteria(pso, acceptance) -> list:
    """The criterion ids a post-ship-observation declaration NAMES, in acceptance order.

    Deterministic and fail-closed in the direction that withholds an exemption: a token is admitted
    ONLY if the declaration's own `observation` text names it AND the card's acceptance actually
    carries that criterion id (the `_criterion_key_namespace` authority, reused rather than
    restated). Nothing else is inferred. Returns [] when the declaration names none — the caller
    renders `_PSO_CARD_LEVEL` rather than inventing one."""
    from lib.task import _leading_criterion_id
    text = str((pso or {}).get("observation") or "")
    legal = []
    for entry in acceptance:
        cid = _leading_criterion_id(entry)
        if cid is not None and cid not in legal:
            legal.append(cid)
    if not legal:
        return []
    named = {(m.group(1).upper(), int(m.group(2))) for m in _PSO_NAMED_CRITERION_RE.finditer(text)}
    return [f"{p}{n}" for (p, n) in legal if (p, n) in named]


def deferred_by_declaration_rows(task: dict, *, _CROSS_ID_RE, _EVENT_TOKEN_RE, _EVENT_TOKEN_STOPWORDS, _LAND_EMITTED_PHRASE_RE, _PSO_CARD_LEVEL, _declares_owed_settlement, _pso_declared_criteria, declared_deferred_probe_rows, land_emitted_named_evidence) -> list:
    """T-12237 — the criteria THIS card DECLARES are proven after the ship, each with the declaration
    that defers it. Pure f(card): no I/O, no args, no journal. Ordered; never raises on a malformed
    card (a card that cannot be read declares nothing, which fails closed).

    Each row is `{"kind", "declaration", "criteria"}`. FOUR kinds:

      (a) `post-ship-observation` — grammar-valid per the single-home
          `_post_ship_observation_declaration_error` AND UNSETTLED per `_post_ship_observation_settled`.
          A SETTLED observation YIELDS NO ROW, for the same reason `derive_overlay_from_card` derives
          nothing there: the proof EXISTS, so nothing is deferred and the ordinary audit applies.

      (b) `land-emitted` — built ENTRY BY ENTRY, so every name maps DETERMINISTICALLY back to the
          criterion that defers it. For each acceptance entry we extract candidates with the SAME two
          shapes `land_emitted_named_evidence` uses, then admit a candidate ONLY if that flat namer
          also returns it. The flat namer stays the TRUST-BOUNDARY oracle, so this derivation and the
          `_require_land_emitted_event` guard can NEVER disagree about what the card named; what the
          per-entry walk adds is only the CRITERION the name was found in. Edges, each tested: a name
          in TWO entries yields ONE row listing BOTH criteria in acceptance order, de-duplicated; a
          name in an entry with no parseable leading identifier renders `(criterion unnamed)` rather
          than being dropped; a name the flat namer does NOT return is omitted entirely (the
          no-widening bound — a card naming nothing yields nothing).

      (c) `settle-probe-owed` — TWO card-derived sources, both narrow: probe keys already RECORDED
          `deferred` in `task['probes']` (the re-audit-after-close case), and acceptance entries
          admitted by `_declares_owed_settlement` (a NAMED settle verb TOGETHER WITH an
          owed-declaration marker, or the self-contained `deferred until Stage 9` shape — a bare
          MENTION of a settle verb is NOT a declaration, T-12237 B3).

      (d) `probe-moment` (T-13150, X-1712) — each filing-time `probe_moments:` entry admitted by
          `declared_deferred_probe_rows` (the ONE grammar + namespace home, T-12312), one row per
          criterion. Reusing that reader keeps an orphan or undecidable moment out of this section
          exactly as it is kept out of the T-12312 one, so the two can never disagree.
    """
    if not isinstance(task, dict):
        return []
    acceptance = task.get("acceptance") or []
    if not isinstance(acceptance, (list, tuple)):
        acceptance = [acceptance]
    try:
        from lib.task import (_post_ship_observation_declaration_error,
                              _post_ship_observation_settled, _leading_criterion_id)
    except ImportError:
        return []

    def _crit(entry) -> str:
        cid = _leading_criterion_id(entry)
        return f"{cid[0]}{cid[1]}" if cid else "(criterion unnamed)"

    rows: list = []

    # (a) post-ship observation
    pso = task.get("post_ship_observation")
    if pso is not None and _post_ship_observation_declaration_error(pso) is None \
            and not _post_ship_observation_settled(pso):
        obs = str((pso or {}).get("observation") or "").strip()
        due = str((pso or {}).get("due_by") or "").strip()
        decl = f"post_ship_observation: {obs} (due_by {due})" if due else f"post_ship_observation: {obs}"
        # The criteria this observation defers: the acceptance entries that name a post-land reading.
        crits = _pso_declared_criteria(pso, acceptance)
        rows.append({"kind": "post-ship-observation", "declaration": decl,
                     "criteria": crits or [_PSO_CARD_LEVEL]})

    # (b) land-emitted — per-entry, gated on the flat namer (the trust-boundary oracle)
    oracle = set(land_emitted_named_evidence(task))
    if oracle:
        linked = {str(x).strip().upper() for x in (task.get("resolves_cross") or [])
                  if isinstance(x, (str, int))}
        by_name: dict = {}
        for entry in acceptance:
            text = str(entry or "")
            cands: list = []
            if _LAND_EMITTED_PHRASE_RE.search(text):
                cands += [t for t in _EVENT_TOKEN_RE.findall(text)
                          if t not in _EVENT_TOKEN_STOPWORDS]
            cands += [x.upper() for x in _CROSS_ID_RE.findall(text) if x.upper() in linked]
            for name in cands:
                if name not in oracle:
                    continue                      # no-widening bound: the oracle is the whole namespace
                by_name.setdefault(name, [])
                c = _crit(entry)
                if c not in by_name[name]:
                    by_name[name].append(c)
        for name in land_emitted_named_evidence(task):   # acceptance order, from the oracle itself
            if name in by_name:
                rows.append({"kind": "land-emitted",
                             "declaration": f"emitted by `land` at Stage 9: {name}",
                             "criteria": by_name[name]})

    # (c) settle-probe-owed
    owed: dict = {}
    probes = task.get("probes")
    if isinstance(probes, dict):
        for key, val in probes.items():
            if str(val).strip().lower() == "deferred":
                owed.setdefault("recorded `probes:` entry still `deferred`", [])
                c = str(key)
                if c not in owed["recorded `probes:` entry still `deferred`"]:
                    owed["recorded `probes:` entry still `deferred`"].append(c)
    declared: list = []
    for entry in acceptance:
        if _declares_owed_settlement(entry):
            c = _crit(entry)
            if c not in declared:
                declared.append(c)
    if declared:
        owed["acceptance names a settle verb (`task close --settle-*`)"] = declared
    for decl, crits in owed.items():
        rows.append({"kind": "settle-probe-owed", "declaration": decl, "criteria": crits})

    # (d) probe-moment — the filing-time declaration, via its one reader
    for r in declared_deferred_probe_rows(task):
        rows.append({"kind": "probe-moment", "declaration": f"probe_moments: {r['moment']}",
                     "criteria": [r["criterion"]]})

    return rows


def deferred_by_declaration_block(task: dict, *, deferred_by_declaration_rows) -> str:
    """T-12237 — render `deferred_by_declaration_rows` as the packet section. "" when there are no
    rows, so the section is INERT by construction on every card that declares nothing."""
    rows = deferred_by_declaration_rows(task)
    if not rows:
        return ""
    parts: list = []
    parts.append("### DEFERRED BY DECLARATION — judge the declaration, not the absence\n")
    parts.append("This card DECLARES that the proof of the criteria below lands AFTER the subject you are\n"
              "judging. Each row names the criterion, the kind of deferral, and the declaration that\n"
              "defers it — so an exemption can be matched to the criterion it covers.\n\n")
    for r in rows:
        parts.append(f"- {', '.join(r['criteria'])} — {r['kind']}\n"
                  f"    declared as: {r['declaration']}\n")
    parts.append("\nHOW THIS BINDS YOUR VERDICT:\n"
              "- The ABSENCE of a listed proof is EXPECTED and is NEVER a finding and NEVER a RED. It is\n"
              "  the normal ordering for this ship, not a defect.\n"
              "- This list is the WHOLE of the exemption. A criterion NOT listed above is judged exactly\n"
              "  as usual — the section widens nothing.\n"
              "- What you DO still judge: whether each declaration actually corresponds to the criterion\n"
              "  it defers, and whether it is dated/tracked rather than open-ended.\n"
              "This is NOT a blanket excuse and must not be read as «my proof is in the future»: a\n"
              "deferral that names no reading, no due date and no settle carrier is a defect, and saying\n"
              "so is exactly what this section asks of you.\n\n")
    return "".join(parts)


def declared_deferred_probes_block(task: dict, *, declared_deferred_probe_rows) -> str:
    """T-12312 — render `declared_deferred_probe_rows` as the packet section. "" when there are no
    rows, so the section is INERT by construction on every card that declares nothing."""
    rows = declared_deferred_probe_rows(task)
    if not rows:
        return ""
    parts: list = [
        "### DEFERRED PROBES — settled after landing by the Controller\n",
        "This card DECLARED, AT FILING, that the criteria below are proven only by the FIRST REAL USE\n"
        "AFTER LANDING. Each row names the criterion and the moment its proof becomes readable.\n\n",
    ]
    for r in rows:
        parts.append(f"- {r['criterion']} — awaited moment: {r['moment']}\n")
    parts.append(
        "\nHOW THIS BINDS YOUR VERDICT:\n"
        "- For a criterion listed above, the ABSENCE of its proof right now is the DECLARED ORDERING\n"
        "  of this ship — it is NEVER a finding and NEVER a RED, at any severity, and you must not\n"
        "  raise it as one. The proof cannot exist yet: by the criterion's own wording it is a\n"
        "  first real use that happens AFTER this change lands.\n"
        "- This list is the WHOLE of the exemption. A criterion NOT listed above is judged exactly as\n"
        "  usual, so this section widens nothing — and a RED that raises any other defect is recorded\n"
        "  normally, alongside whatever you say about these.\n"
        "- What you DO still judge: whether each declaration actually corresponds to the criterion it\n"
        "  defers, and whether its moment is one a reader can decide rather than an open-ended\n"
        "  «later». A deferral naming no decidable moment and no settle carrier IS a finding, and\n"
        "  saying so is exactly what this section asks of you.\n"
        "The deferral is TRACKED, not waived: the Controller settles each one after the land via\n"
        "`task close --settle-probe`, and the card carries `probe_passed: deferred` until then.\n\n")
    return "".join(parts)


def packet_touch_section(recon: dict) -> str:
    """T-11820 — the PACKET rendering of `packet_touch_reconciliation`, for the TASK audit-post
    prompt. Sibling of the readiness block's `touch:` row: same dict, same ruling, different reader.

    WHY IT EXISTS AT ALL. Until T-11820 this comparison had exactly ONE call site, inside the
    `--preview` branch that returns before `_invoke_auditor` — so it reached the OPERATOR on stderr
    and never the AUDITOR. The packet's task body renders id/title/acceptance/plan/stage-6/adoption/
    diff and NOT `expected_touch`, which left the auditor a single view of the forecast: the card
    YAML hunk inside the shipped diff, i.e. its COMMITTED state. That collides with the governed
    correction route: `task analyze --forecast-correction` (T-11358) deliberately leaves the card
    DIRTY so the audited commit does not move, so the sanctioned correction was STRUCTURALLY
    INVISIBLE to the very gate demanding it (T-11819: audit-post pass 3 restated pass 2 verbatim
    against a card that on disk already declared all 18 paths, while branch HEAD carried the old 10 —
    two owner-authorized ceiling resets spent on it). This section renders the ON-DISK forecast, so
    the correction is visible where it is judged.

    ADVISORY BY CONSTRUCTION — a RULING, not an oversight, carried over unchanged from
    `packet_touch_reconciliation`: X-1060's own external consult ruled this comparison must NOT
    become a hard gate, because it is LIFECYCLE behaviour rather than artifact integrity. The
    section therefore says so IN THE TEXT the auditor reads, and nothing branches on it: no verdict,
    exit code, ceiling pass or counted set moves.

    PURE — dict in, string out. No git, no journal, no I/O; the caller supplies the reconciliation.
    Returns "" only when there is genuinely nothing to say (nothing declared AND nothing audited)."""
    declared, audited = recon.get("declared") or [], recon.get("audited") or []
    if not declared and not audited:
        return ""
    d_only, a_only = recon.get("declared_only") or [], recon.get("audited_only") or []
    lines = [
        "## Declared vs audited touch (derived; REPORT-ONLY CONTEXT — never a finding)",
        "",
        "The card's `expected_touch` forecast AS IT STANDS ON DISK, compared against the paths in the",
        "shipped diff above. The on-disk reading is the point: a governed forecast correction",
        "(`task analyze --forecast-correction`, T-11358) deliberately leaves the card uncommitted so",
        "the audited commit does not move, so the card YAML hunk in the diff may show an OLDER list",
        "than this section does. Where they disagree, THIS section is the current declaration.",
        "",
        f"- declared on disk ({len(declared)}): " + (", ".join(declared) if declared else "(none)"),
        f"- audited in the diff ({len(audited)}): " + (", ".join(audited) if audited else "(none)"),
        f"- declared but NOT audited ({len(d_only)}): " + (", ".join(d_only) if d_only else "(none)"),
        f"- audited but NOT declared ({len(a_only)}): " + (", ".join(a_only) if a_only else "(none)"),
        "",
        "This is DATA for your scope-fidelity judgement, not a verdict and not a rule. An entry in",
        "either difference list is NOT a defect at ANY severity, and you MUST NOT raise one as a",
        "finding (T-12302; X-1060's consult had already ruled the comparison advisory). The forecast",
        "is a plan-time guess that `task commit` REFRESHES from the committed diff, so a gap here is",
        "a fact about when the card was written, not about the change. A RED whose only finding",
        "carries `class_id: forecast-completeness` is REFUSED at the parse floor — no verdict",
        "recorded, no pass spent, the finding lost rather than acted on. Judge the CHANGE: a path the",
        "card's SCOPE does not justify is still a scope-fidelity finding, on its own merits.",
        "",
    ]
    return "\n".join(lines)


def _ac_canonical_id(criterion: str, position: int, *, _AC_CANONICAL_ID_RE) -> str:
    """T-11977 — the canonical row label for ONE acceptance criterion: its own leading `ACn` token
    when it carries one, else the positional `AC<position>` (1-based). Pure f(str, int).

    The SAME rule the plan's B2 AC-coverage check is specified against, so the readiness rows and
    that refusal name a criterion identically — one id rule, not two."""
    m = _AC_CANONICAL_ID_RE.match(str(criterion or ""))
    return m.group(1).upper() if m else f"AC{position}"


def packet_readiness_section(acceptance, task_class, evidence_types, stage6_present,
                             p8_present, deferred_field, stale_anchors, touch_recon,
                             prior_findings_unanswered, p8_carrier_ids=(),
                             declared_test_globs=(), *, _ac_canonical_id) -> str:
    """T-11977 (SPEC-0036 §Packet preview) — the REPORT-ONLY packet-readiness block the `--preview`
    path prints, built from parts `build_audit_prompt` has ALREADY computed in the same pass.

    ADVISORY, and that is the X-1060 consult's RULING carried forward unchanged: exit 0, no verdict,
    no ceiling pass, no gate, no counted set. Nothing branches on a row. The only record stays the
    existing `audit_packet_previewed` receipt. A row is DATA for the worker about to spend a pass —
    it never decides anything, here or downstream.

    WHY IT EXISTS. Measured 2026-09-02 over the kernel journal since 2026-08-18: of 383 RED
    audit-post passes, P8-adoption 37% + test-evidence 24% + spec-coherence 17% + scope-fidelity 11%
    are FORM mismatches the packet's own inputs already reveal — and 23% of REDs are withdrawn on the
    SAME commit with no code change. The packet held the answer; nothing read it back to the worker.

    IT FOLDS THE TWO STANDALONE PREVIEW DIAGNOSTICS (X-1060 D1/D2), which stop printing as their own
    lines: the declared-vs-audited touch comparison becomes the `touch:` row, and the
    no-journal-row-since-the-last-RED observation becomes the `prior findings without response:`
    count. One report surface, not three — still advisory.

    ROWS ARE THE CONTRACT (machine-stable, ONE per line, fixed labels — downstream cards parse them):
      `AC<n>: verifier <PRESENT|ABSENT|WAIVED>; evidence <PRESENT|ABSENT>`
      `P8 carrier: <PRESENT|DEFERRED-DECLARED <field>|ABSENT|n/a (class <x>)>`
      `stale anchors: <file> -> <SPEC-ID>`  (one row per pair) | `stale anchors: none`
      `touch: declared <n> audited <m> outside-forecast <k>`
      `prior findings without response: <n>`
    Anything else the block prints is an INDENTED detail line beneath its row, never a row itself —
    so naming the differing paths costs the parser nothing.

    PURE — every input is supplied by the caller; no git, no journal, no graph, no I/O.
    That is why `declared_test_globs` (T-12013) is a PARAMETER rather than a read: the `verifier`
    column is now answered by the ONE recognizer `task.criterion_names_test`, which reads the
    project's declared `tests.classes[].globs` when it has them (SPEC-0160 rule 10) and falls back to
    the kernel regex when it does not — so a consumer whose tests live at `spec/**/*_spec.rb` stops
    reading ABSENT while its criteria honestly name a verifier (X-1235). The caller resolves the
    value from the `repo_root` it already holds; an empty tuple is the pre-T-12013 behaviour exactly.
    The WAIVED limb still reads `_AC_WAIVE_RE` directly — a waive is not a test reference.
    `evidence_types` are the event TYPES the packet's adoption section renders; `stale_anchors` are
    `(file, SPEC-ID)` pairs from the coverage section's own drift walk; `touch_recon` is the
    `packet_touch_reconciliation` dict.

    `p8_present` / `p8_carrier_ids` (T-12009): CHARTER §P8 accepts THREE carriers, not two, and this
    row reads all three — the caller ORs the two adoption event types with the blocking-followup
    carrier the packet BODY already rendered, and passes the ids that body named. The row label is
    unchanged (`P8 carrier: PRESENT` stays the machine-stable contract); the carrier is named on an
    INDENTED detail line beneath it, which the row contract above already reserves for detail. This
    row and that body block therefore report ONE derived value: before T-12009 the row counted only
    the two event types and printed ABSENT four screens under a body declaring the criterion
    SATISFIED by a named open carrier (measured on T-12001 / T-12004 / T-12005)."""
    from lib.task import _AC_WAIVE_RE, criterion_names_test   # lazy: task.py imports THIS module

    crits = list(acceptance or [])
    types = {str(t) for t in (evidence_types or []) if str(t)}
    lines = [
        "# ---- packet readiness (T-11977; REPORT-ONLY — ADVISORY, gates nothing) ----",
        "# Every row below is DATA about the packet printed above: no verdict, no ceiling pass, no",
        "# gate moves on any of it. Read it before spending an auditor pass; act or do not.",
    ]
    if not crits:
        lines.append("AC0: verifier ABSENT; evidence ABSENT")
        lines.append("    (the card lists NO acceptance criteria — there is nothing for the auditor to judge)")
    for i, crit in enumerate(crits, start=1):
        text = str(crit)
        if _AC_WAIVE_RE.search(text):
            verifier = "WAIVED"
        elif criterion_names_test(text, declared_test_globs):
            verifier = "PRESENT"
        else:
            verifier = "ABSENT"
        # EVIDENCE is PRESENT only when the packet carries a row THIS criterion's own text points
        # at: an adoption-evidence event type it names, or the Stage-6 `tests_passed` row when it
        # names a test. Anything looser would report evidence the auditor cannot match to the
        # criterion — the exact confusion the block exists to remove.
        # TOKEN match, never a bare substring: an event type embedded inside a larger word
        # (`unspec_edited_thing` containing `spec_edited`) would otherwise make an unrelated
        # criterion read evidence PRESENT — a row that says the packet answers a criterion it does
        # not (audit-post finding 2, absorbed).
        named_type = any(re.search(r"(?<![\w-])" + re.escape(t) + r"(?![\w-])", text) for t in types)
        evidence = "PRESENT" if (named_type or (stage6_present and verifier == "PRESENT")) else "ABSENT"
        lines.append(f"{_ac_canonical_id(text, i)}: verifier {verifier}; evidence {evidence}")

    cls = str(task_class or "").strip() or "(unset)"
    # T-12725 — the class question is answered by THE ONE predicate (`charter_p8_reaches_class`), the
    # same one the refuter and the overlay's ASK seam resolve: an unresolvable class now reads the
    # infra-shaped row (fail-closed, as the prompt keeps its demand) instead of an `n/a (class (unset))`
    # that contradicted the packet above it.
    if not charter_p8_reaches_class(task_class):
        lines.append(f"P8 carrier: n/a (class {cls})")
    elif p8_present:
        lines.append("P8 carrier: PRESENT")
        _cids = [str(c) for c in (p8_carrier_ids or ()) if str(c)]
        if _cids:
            lines.append("    (satisfied by the filed blocking adoption follow-up(s): "
                         + ", ".join(_cids) + " — the CHARTER §P8 third satisfier, rendered in full "
                         "in the adoption section above)")
    elif deferred_field:
        lines.append(f"P8 carrier: DEFERRED-DECLARED {deferred_field}")
    else:
        lines.append("P8 carrier: ABSENT")
        lines.append("    (class infra closes on CHARTER §P8 consumer-read / live-trigger evidence — "
                     "name a carrier or declare a deferred proof on the card)")

    pairs = sorted({(str(f), str(sid)) for f, sid in (stale_anchors or []) if f and sid})
    if not pairs:
        lines.append("stale anchors: none")
    else:
        for f, sid in pairs:
            lines.append(f"stale anchors: {f} -> {sid}")

    recon = touch_recon or {}
    declared = recon.get("declared") or []
    audited = recon.get("audited") or []
    d_only = recon.get("declared_only") or []
    a_only = recon.get("audited_only") or []
    lines.append(f"touch: declared {len(declared)} audited {len(audited)} "
                 f"outside-forecast {len(a_only)}")
    if d_only:
        lines.append("    declared-not-audited: " + ", ".join(d_only[:6]))
    if a_only:
        lines.append("    audited-not-declared: " + ", ".join(a_only[:6]))

    lines.append(f"prior findings without response: {int(prior_findings_unanswered or 0)}")
    if prior_findings_unanswered:
        lines.append("    (the previous verdict was RED and NOTHING is on record for this card since "
                     "it — re-invoking re-audits the same state; CHARTER §P7 re-run-vs-resolve)")
    lines.append("# ---- end packet readiness ----")
    return "\n".join(lines)


def _packet_sections(text: str):
    """Cut an ASSEMBLED audit packet into NAMED sections on its own `## ` / `### ` headings.

    The level-up sibling of `_split_diff_segments` (T-11136): that one names paths inside the diff,
    this one names sections inside the packet. Every byte belongs to exactly ONE section (the text
    before the first heading is `<preamble>`), so a per-section byte breakdown is TOTAL by
    construction — which is what makes the AC2 report an accounting rather than a sample.

    Returns a list of (label, header_lines, body_lines); the heading line is the header and is emitted
    unconditionally, so no section can vanish from the packet whatever the budget.
    """
    lines = text.splitlines()
    sections, current, preamble = [], None, []
    for ln in lines:
        if ln.startswith("## ") or ln.startswith("### "):
            current = (ln.strip(), [ln], [])
            sections.append(current)
        elif current is None:
            preamble.append(ln)
        else:
            current[2].append(ln)
    if preamble:
        sections.insert(0, ("<preamble>", [], preamble))
    return sections


def _packet_section_protected(label: str) -> bool:
    return label.startswith(_PACKET_PROTECTED_PREFIXES)


def _packet_elision_marker(label: str, kept_lines: int, total_lines: int,
                           kept_bytes: int, total_bytes: int) -> str:
    return (f"... [elided: {label} — kept {kept_lines} of {total_lines} lines, "
            f"{kept_bytes} of {total_bytes} bytes; the omitted content EXISTS in the repository and "
            f"the journal — it was bounded here, it is NOT absent]")


def _render_packet_manifest(elisions, *, over_floor: bool, _PACKET_MANIFEST_HEADER) -> list:
    """The manifest — the half of the bound that stops "not shown" being read as "not present".

    A packet may be trimmed; it may NEVER be trimmed SILENTLY. A silently truncated packet is worse
    than a refused one: the verdict is then formed on a subset nobody knows about and reads as a full
    one. So every cut section is named here with kept/total on both axes.
    """
    if not elisions:
        return []
    out = [f"{_PACKET_MANIFEST_HEADER} ({len(elisions)} section(s) shown only in part) ===",
           "NOTE: this packet exceeded the total-size ceiling the external auditor can read, so the",
           "sections below were BOUNDED — every one of them is present in full in the repository and",
           "the journal. \"not shown\" NEVER means \"not present\": do NOT report bounded content as",
           "absent, missing, or unrecorded, and do NOT treat a bounded evidence section as an evidence",
           "gap. Sections carrying your instructions and this task's criteria are never bounded."]
    if over_floor:
        out.append("NOTE: the protected instruction/criteria sections alone exceed the ceiling, so every")
        out.append("other section was reduced as far as it goes and the packet is STILL over budget.")
    for e in elisions:
        out.append(f"- {e['label']} — kept {e['kept_lines']} of {e['total_lines']} lines, "
                   f"{e['kept_bytes']} of {e['total_bytes']} bytes")
    return out


def _packet_section_breakdown(text: str, *, _linebytes, _packet_sections) -> list:
    """The per-section byte breakdown of an assembled packet (T-11328 AC2), largest first.

    Reported on EVERY audit run — to the operator on stderr and onto the `audit_prompt_sent` event —
    because the packet's size was observable through NO governed surface at all: T-11319 was lost to a
    936KB packet whose dominant section could only be found by hand-importing this module. Derived,
    read-only, no stored state.
    """
    rows = [{"label": label, "bytes": sum(_linebytes(x) for x in (header + body))}
            for label, header, body in _packet_sections(text)]
    return sorted(rows, key=lambda r: r["bytes"], reverse=True)


def _packet_bound_elisions(text: str, *, _PACKET_MANIFEST_HEADER) -> list:
    """The cuts an ALREADY-BOUNDED packet carries, read back out of its own manifest (T-11328 AC2).

    Derived from the emitted packet rather than threaded out of the bound, deliberately: the report to
    the operator and the record on the journal then describe what the AUDITOR ACTUALLY RECEIVED, and
    cannot drift from it. An unbounded packet carries no manifest and yields [] — so the report is a
    real discriminator, never an unconditional decoration.
    """
    lines = text.splitlines()
    try:
        start = next(i for i, ln in enumerate(lines) if ln.startswith(_PACKET_MANIFEST_HEADER))
    except StopIteration:
        return []
    out = []
    for ln in lines[start + 1:]:
        m = re.match(r"^- (?P<label>.+) — kept (?P<kl>\d+) of (?P<tl>\d+) lines, "
                     r"(?P<kb>\d+) of (?P<tb>\d+) bytes$", ln)
        if m:
            out.append({"label": m.group("label"), "kept_lines": int(m.group("kl")),
                        "total_lines": int(m.group("tl")), "kept_bytes": int(m.group("kb")),
                        "total_bytes": int(m.group("tb"))})
    return out


def _bound_packet_total(text: str, *, max_bytes: int = None, AUDIT_MAX_PACKET_BYTES, _keep_within_budget, _linebytes, _packet_elision_marker, _packet_section_protected, _packet_sections, _render_packet_manifest):
    """Bound the WHOLE assembled audit packet, naming every section it cuts (T-11328).

    WHY THIS EXISTS ALONGSIDE `_bound_diff_for_audit`: that one bounds the DIFF, and it worked — on
    T-11319 the diff obeyed both of its ceilings (4144 lines / 309905 B). The packet still reached
    979708 B (~245k tokens) and the auditor refused it 3/3, because 587052 B of it was
    `### Adoption evidence`: every `spec_edited` / `spec_reverified` event ever recorded for the 44
    spec files the diff touched. That section grows with the AGE OF THE CORPUS, not with the change
    under audit, so no diff-side ceiling could ever have caught it. The gate was not strict, it was
    UNRUNNABLE — and the only ways past were waiving it or shrinking a legitimate change.

    WHY THE TRIMMABLE SET IS INVERTED: a named list of trimmable sections repeats the very defect —
    it bounds only the shapes someone already thought of, and the next dominator (audit-pre's
    `## Referenced files`, `## Extra context`, or a section a future card adds without knowing this
    bound exists) walks straight past it. So a NAMED, CLOSED set is PROTECTED and everything else is
    trimmable, fail-closed. Prior-art for the inversion:
    `lessons/a-widening-log-means-invert-the-whitelist.md`.

    CONTRACT:
      * A packet already inside the ceiling is returned BYTE-IDENTICAL — no marker, no manifest. An
        ordinary audit sees exactly what it saw before (the T-11136 AC3 contract, held here).
      * Trimming is LOUD or it does not happen: every cut section carries a named marker AND a
        manifest line. There is no path through this function that reduces the packet silently.
      * Largest-first, so one bloated section cannot starve the others out of the packet.
      * The marker and manifest costs are RESERVED BEFORE content is admitted, so the manifest can
        never push the packet back over the ceiling it enforces (the T-11136 floor contract).
      * A section rendered oldest-first keeps its TAIL (`_PACKET_KEEP_TAIL_PREFIXES`), so bounding
        adoption evidence can never hide the NEWEST proof and manufacture a false adoption gap.

    Returns (bounded_text, elisions); elisions is empty when nothing was cut.
    """
    max_bytes = AUDIT_MAX_PACKET_BYTES if max_bytes is None else max_bytes
    if len(text.encode("utf-8", "replace")) <= max_bytes:
        return text, []                                   # untouched — the ordinary case

    sections = _packet_sections(text)
    if not sections:
        return text, []
    nbytes = lambda ls: sum(_linebytes(x) for x in ls)

    # FLOOR: what is emitted unconditionally — every heading, every protected body, and (worst case)
    # one marker + one manifest line per trimmable section. Computed BEFORE any content is admitted.
    trimmable = [i for i, (lbl, _h, _b) in enumerate(sections) if not _packet_section_protected(lbl)]
    floor = sum(nbytes(h) for _l, h, _b in sections)
    floor += sum(nbytes(b) for lbl, _h, b in sections if _packet_section_protected(lbl))
    worst = [{"label": sections[i][0], "kept_lines": 0, "total_lines": len(sections[i][2]),
              "kept_bytes": 0, "total_bytes": nbytes(sections[i][2])} for i in trimmable]
    floor += nbytes(_render_packet_manifest(worst, over_floor=True))
    floor += sum(_linebytes(_packet_elision_marker(w["label"], 0, w["total_lines"], 0, w["total_bytes"]))
                 for w in worst)
    budget = max(0, max_bytes - floor)

    # LARGEST-FIRST allocation: hand each trimmable section, biggest down, what it needs out of the
    # shared remainder. A section that fits keeps everything; the ones that do not share what is left.
    need = {i: nbytes(sections[i][2]) for i in trimmable}
    alloc, left = {}, budget
    for i in sorted(trimmable, key=lambda k: need[k], reverse=True):
        remaining = [j for j in trimmable if j not in alloc]
        share = left // max(1, len(remaining))
        take = min(need[i], share)
        alloc[i] = take
        left -= take
    for i in sorted(trimmable, key=lambda k: need[k]):     # redistribute what the small ones released
        if left <= 0:
            break
        want = need[i] - alloc[i]
        if want > 0:
            add = min(want, left)
            alloc[i] += add
            left -= add

    out, elisions = [], []
    for i, (label, header, body) in enumerate(sections):
        out.extend(header)
        if _packet_section_protected(label):
            out.extend(body)                                # never cut — instructions and criteria
            continue
        keep_tail = label.startswith(_PACKET_KEEP_TAIL_PREFIXES)
        source = list(reversed(body)) if keep_tail else body
        kept, kept_b, cut = _keep_within_budget(source, len(source), alloc.get(i, 0))
        out.extend(reversed(kept) if keep_tail else kept)
        if cut:
            elisions.append({"label": label, "kept_lines": len(kept), "total_lines": len(body),
                             "kept_bytes": kept_b, "total_bytes": nbytes(body)})
            out.append(_packet_elision_marker(label, len(kept), len(body), kept_b, nbytes(body)))
    out.extend(_render_packet_manifest(elisions, over_floor=budget == 0 and bool(elisions)))
    return "\n".join(out), elisions


def _card_repair_chain_transparent(commit: str, tid: str, *, _bookkeeping_commit_authored_paths,
                                   REPO_ROOT, _git_ship_landed) -> bool:
    """T-12436 — may `_card_repair_subject_admitted` conjunct (e)'s first-parent walk CROSS this
    commit on its way back to the covered ship? TRANSPARENT means the commit puts nothing of this
    card's own between the graded ship and the repair built on top of it.

    TWO shapes, and no third — both read from GIT, and neither introduces a vocabulary this module
    did not already have (CHARTER §P5 — one definition of "authored" on this route):
      (i)  a NON-MERGE commit whose OWN diff carries no authored path, read through the EXISTING
           injected `_bookkeeping_commit_authored_paths` (the T-11991 allow-list conjuncts (a)/(d)
           already read). `[]` is transparent; `None` means git could not answer and is NOT `[]`, so
           an unverifiable commit refuses, and an uninjected reader refuses too. This is the `chore:
           card bookkeeping` / `worktree sync: bookkeeping` commit.
      (ii) a MERGE commit whose SECOND parent is an ancestor of `main` — the update-from-main IMPORT
           that `worktree sync` and `land` write. Read through the EXISTING in-module three-valued
           `_git_ship_landed` (T-12362 — the same `merge-base --is-ancestor <x> main` call), and only
           `is True` admits, so an unanswerable ancestry refuses rather than being read as a `no`
           that happens to fall the permissive way.

    WHAT STAYS OPAQUE, i.e. what conjunct (e) still fences: an authored non-merge commit (it puts
    unaudited content between the ship and the repair — `--fix-red` proper's case, not this route's),
    a merge whose second parent is NOT on main (a private branch merged in is not an import of main's
    landed history), and an OCTOPUS merge (>2 parents), which is not a shape any governed verb on
    this route writes and which has no single "the imported side" to test.

    Pure predicate, never raises: every git failure, every unreadable parent list and every
    unprovable input answers False — a walk that cannot verify must not grant."""
    from lib import git_env as _git_env  # T-13587 — the git child env policy (SPEC-0188 rule 7)
    try:
        r = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "rev-list", "--parents", "-n", "1", str(commit)],
            capture_output=True, text=True, check=False, env=_git_env._git_child_env())
        if r.returncode != 0:
            return False
        fields = (r.stdout or "").split()
        if not fields:
            return False
        parents = fields[1:]
        if len(parents) > 1:
            # (ii) a MERGE — only the two-parent update-from-main import is transparent.
            if len(parents) != 2:
                return False
            return _git_ship_landed(parents[1], repo_root=REPO_ROOT) is True
        # (i) a NON-merge commit — transparent only when its own diff is provably record-only.
        if not callable(_bookkeeping_commit_authored_paths):
            return False
        return _bookkeeping_commit_authored_paths(commit, tid) == []
    except Exception:      # noqa: BLE001 — an unverifiable crossing is simply not granted
        return False


def _card_repair_chain_walk(sha: str, covered: str, tid: str, *,
                            _bookkeeping_commit_authored_paths, _git_resolve_sha, REPO_ROOT, _CARD_REPAIR_CHAIN_MAX_DEPTH, _card_repair_chain_transparent) -> bool:
    """Does `sha` REACH `covered` along its FIRST-PARENT chain, crossing TRANSPARENT commits only?

    T-12614 extracted this from `_card_repair_subject_admitted` conjunct (e) VERBATIM — behaviour
    unchanged — because a SECOND admission now asks the identical question
    (`_ship_contained_record_only`). Two copies of a chain walk is how two doors on one route come to
    disagree about which crossings are transparent, which is the X-1251 class T-12026 closed on a
    different conjunct; one `def` is the structural answer.

    The FIRST iteration is the original bare-parenthood test unchanged — `sha^1 == covered` admits
    before any transparency question is asked. Beyond it the walk crosses only what
    `_card_repair_chain_transparent` PROVES carries nothing of this card between the two (a
    record-only non-merge commit, or an update-from-main merge), and it is BOUNDED by
    `_CARD_REPAIR_CHAIN_MAX_DEPTH`, so an unbounded or cyclic history refuses rather than spinning.
    MERE ANCESTRY IS STILL REFUSED: an AUTHORED commit anywhere on the chain stops the walk, which is
    exactly the card-only-commit-made-later-in-the-branch case this fence exists for.

    Pure predicate; never raises; False on any git failure, any unreadable parent and any unprovable
    input — a walk that cannot verify must not grant."""
    from lib import git_env as _git_env  # T-13587 — the git child env policy (SPEC-0188 rule 7)
    try:
        cur = str(sha)
        for _ in range(_CARD_REPAIR_CHAIN_MAX_DEPTH):
            par = subprocess.run(
                ["git", "-C", str(REPO_ROOT), "rev-parse", "--verify", f"{cur}^1"],
                capture_output=True, text=True, check=False, env=_git_env._git_child_env())
            if par.returncode != 0:
                return False
            raw = par.stdout.strip()
            parent = (_git_resolve_sha(raw) or "")
            if not parent:
                return False
            if parent == (_git_resolve_sha(covered) or "\x00"):
                return True
            if not _card_repair_chain_transparent(
                    raw, tid, _bookkeeping_commit_authored_paths=_bookkeeping_commit_authored_paths,
                    REPO_ROOT=REPO_ROOT):
                return False
            cur = raw
        return False       # depth exceeded — an unprovable chain is simply not granted
    except Exception:      # noqa: BLE001 — an unprovable crossing is simply not granted
        return False


def _folded_audit_post_record(sha: str, tid: str, REPO_ROOT) -> "dict | None":
    """T-12723 — the audit-post record a `--fix-red --card-repair` commit FOLDED: the superseded
    verdict as committed IN `sha` itself (`<sha>:decisions/<tid>-audit-post.yaml`), i.e. the record
    BEFORE the repair. None on any git / parse failure, on a missing path, and on a non-mapping.

    WHY THIS RECORD IS READABLE AT ALL, and why it is the right one. LIFECYCLE §Stage 8 has the
    repair arm fold the superseded RED into its own commit (never hand-deleted — that zeroes the
    passes counter), so the verdict the repair ANSWERED is durably in git at the repair's own sha,
    pinned to the ship it graded. The live `decisions/<tid>-audit-post.yaml` is a DIFFERENT record
    once a later pass audited the repair itself: pinned to the repair, carrying that pass's cause.
    `_card_repair_subject_admitted` conjuncts (c)/(d)/(e) ask about the record the repair answered,
    so when the live record is pinned to the subject they must read THIS one — measured on T-12708
    (2026-09-18): pass 2 audited the repair c8cea16 and RED-ed on a non-card cause, the ceiling
    row's subject became the repair, and the rule-3 pass had no admissible subject because every
    door read the pass-2 record (cause AC6, `covered == sha`) instead of the pass-1 record the
    repair had folded (cause = the card record, `commit` = the ship 508b303).

    ONE path shape, the ONE the fold writes (`_audit_rel` at the commit door, `audit_yaml_path`'s
    active path at the audit door): an in-flight card's record is never archived (T-0527), and a
    repair is only ever committed on an in-flight card, so the archive fallbacks are not consulted.
    A governed record read from GIT — the same trust boundary the other conjuncts sit behind; the
    actor being fenced cannot rewrite a committed blob. Pure; never raises; no host collaborator."""
    from lib import git_env as _git_env  # T-13587 — the git child env policy (SPEC-0188 rule 7)
    try:
        if not sha or not tid or REPO_ROOT is None:
            return None
        r = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "show", f"{sha}:decisions/{tid}-audit-post.yaml"],
            capture_output=True, text=True, check=False, env=_git_env._git_child_env())
        if r.returncode != 0 or not (r.stdout or "").strip():
            return None
        import yaml
        d = yaml.safe_load(r.stdout)
        return d if isinstance(d, dict) else None
    except Exception:      # noqa: BLE001 — an unreadable folded record is simply not granted
        return None


def _card_repair_authored_ship(tid: str, covered: str, *, _bookkeeping_commit_authored_paths,
                               _git_resolve_sha, REPO_ROOT, _CARD_REPAIR_CHAIN_MAX_DEPTH,
                               _card_repair_chain_walk, _folded_audit_post_record) -> "str | None":
    """T-12829 (X-1523) — the AUTHORED ship a card-repair chain rides on, resolved from the commit an
    audit-post record covers. Returns that ship's resolved sha, else None.

    THE DEFECT. Every door on the card-repair route asked ONE hop: «does the commit the audit-post
    record covers carry authored content?» After one `--fix-red --card-repair` is itself RED-audited,
    the live record covers THAT repair — record-only by construction — so every later repair was
    refused forever, on a card whose ship is real (<project> T-0736, 2026-09-22: ship 1cb9163 with 3187
    authored insertions; repair 00e6f39; pass 2 RED; ceiling). The three doors (the commit door's
    conjunct (B), `_card_repair_subject_admitted` conjunct (d), `_ship_contained_record_only`
    conjunct (3)) now ask THIS function, so they cannot disagree about which ship a repair rides on
    (the X-1251 two-doors class).

    THE WALK. While `covered` is PROVABLY record-only (`[]` — `None` means git could not answer and
    refuses), step to the commit named by the audit-post record that repair FOLDED
    (`_folded_audit_post_record`, T-12723 — a governed record read from git, never a journal row),
    and require `covered` to REACH it along a TRANSPARENT first-parent chain (the SHARED
    `_card_repair_chain_walk`), so an authored commit between two links stops the walk exactly as it
    stops conjunct (e). The first authored commit is the ship. The first hop is the pre-T-12829 test
    unchanged: an authored `covered` answers at once.

    Pure; NEVER raises; None on an unreadable fold, an unresolvable or self-referencing link, a chain
    longer than `_CARD_REPAIR_CHAIN_MAX_DEPTH`, and any git failure — a walk that cannot verify must
    not grant."""
    try:
        if not callable(_bookkeeping_commit_authored_paths) or not callable(_git_resolve_sha):
            return None
        cur = _git_resolve_sha(str(covered or "").strip()) or ""
        # At most `_CARD_REPAIR_CHAIN_MAX_DEPTH` link TRAVERSALS, each followed by an authored check —
        # so the commit reached by the last permitted traversal is still examined (a chain of exactly
        # the bound resolves; one longer refuses).
        for hop in range(_CARD_REPAIR_CHAIN_MAX_DEPTH + 1):
            if not cur:
                return None
            authored = _bookkeeping_commit_authored_paths(cur, tid)
            if authored:
                return cur
            if authored != [] or hop == _CARD_REPAIR_CHAIN_MAX_DEPTH:
                return None             # None = git could not answer; or the traversal bound is spent
            folded = (_folded_audit_post_record(cur, tid, REPO_ROOT)
                      if callable(_folded_audit_post_record) else None)
            nxt = _git_resolve_sha(str((folded or {}).get("commit") or "").strip()) or ""
            if not nxt or nxt == cur:
                return None
            if not _card_repair_chain_walk(
                    cur, nxt, tid, _bookkeeping_commit_authored_paths=_bookkeeping_commit_authored_paths,
                    _git_resolve_sha=_git_resolve_sha, REPO_ROOT=REPO_ROOT):
                return None
            cur = nxt
        return None
    except Exception:      # noqa: BLE001 — an unprovable resolution is simply not granted
        return None


def _card_repair_subject_admitted(tid: str, sha: str, *, _bookkeeping_commit_authored_paths,
                                  _prior_audit_record, _recorded_commit_landed, _git_resolve_sha,
                                  REPO_ROOT, _red_cause_is_card_record=None, _custody_commit_landed=None,
                                  _card_repair_chain_walk, _empty_subject_own_paths, _is_own_card_path,
                                  _card_repair_authored_ship) -> bool:
    """T-11991 — the derivation behind the card-repair admission in
    `_require_nonempty_audit_subject` (its call site carries the full rationale).

    THE ADMISSION IS DERIVED FROM VERIFIABLE FACTS, NEVER FROM A SELF-DECLARED FLAG. Pass-1 RED said
    a git-only admission un-ties this from the governed arm; pass-2 RED said the fix for that — ANDing
    in the `commit_landed{card_repair:true}` marker — leans on a row anyone can append, so the marker
    half proved only that a forged row named a forged subject. Both are right, and the answer to both
    is the same: the marker stays REQUIRED (it is the governed arm's own provenance) but it is never
    SUFFICIENT, and every OTHER conjunct is read from something the actor being fenced does not
    author — GIT, and the RECORDED audit-post verdict the audit verb itself wrote:
      · the subject's diff carries THIS card's own record (git, `--name-only`);
      · the subject REACHES the previously audited custody sha along its FIRST-PARENT chain, across
        TRANSPARENT commits only — chain continuity read off git, not a record's claim about
        ancestry. A card repair is made ON TOP of the ship it repairs, so bare parenthood was this
        conjunct's original shape; T-12436 widened it to a BOUNDED walk because the dispatch
        preamble now MANDATES a `worktree sync` pre-flight (point 7 / T-11313) whose governed
        update-from-main merge + bookkeeping commit sit between the two, and refusing them left any
        pre-flighted card unable to pass this door on a route the COMMIT door had just admitted it
        to (measured on T-12420). Transparency is proven, never assumed — see
        `_card_repair_chain_transparent` — so MERE ANCESTRY is still refused: an authored commit on
        the chain stops the walk, which is the case this conjunct exists for;
      · the prior audit-post record is RED and its cause DERIVES to this card's own record — i.e.
        the repair being admitted is the repair that verdict asked for. Read from
        `decisions/<tid>-audit-post.yaml`, a governed record pinned to that custody sha, NOT from
        the journal row, and judged by the ONE shared predicate `_red_cause_is_card_record`
        (T-12026) that the governed `--fix-red --card-repair` arm reads too — so the two doors on
        this route cannot disagree (the X-1251 defect). It replaced a KEYWORD TEST over the
        auditor's prose; see that predicate for what the derivation reads instead.
    T-12060 WIDENED CONJUNCT (a) BY ONE FACT-SHAPE, not by relaxing it: the marker may ALSO be
    `absorption` (what `task commit --absorb --owner-reset` records for an owner-directed acceptance
    amendment), and ONLY on the extra proof the `card_repair` marker otherwise stands in for — the
    subject's own diff is card-record-only by the same allow-list conjunct (d) reads. See the branch
    itself for why the other marker was unreachable (the non-stackable escapes, T-12030).

    So a hand-emitted `card_repair` row on a hand-made card-only commit no longer buys admission: it
    must ALSO sit directly on the audited ship AND answer a RED that actually named the card. The
    residual — an actor who can rewrite the audit record itself — is the same trust boundary every
    governed record in this kernel sits behind, and is not something this predicate can narrow.

    Provenance is read through the EXISTING `_recorded_commit_landed` — the payload reader D-0082
    already uses (T-10737 widened it to the whole payload for the `absorption` marker beside this
    one). No new journal consumer enters the system, so the SPEC-0190 census is untouched: this is a
    new READ of a row already read, not a new reader (CHARTER §P1 F1/F2).
    T-12727 — WHICH ROW IS «THE RECORDED COMMIT» IS THE CUSTODY VIEW'S ANSWER, NOT THE KIND-BLIND
    LAST ROW. The subject this predicate is asked about was resolved by the audit-post subject
    resolver through the ship-vs-bookkeeping custody view (`audit_custody_commit`, T-12362: a park /
    pause / wont-do self-commit PROVEN record-only on an UNLANDED ship is transparent). Conjunct (a)
    read the RAW last row instead, so a `task pause --reason audit-ceiling` self-commit written AFTER
    the `--fix-red --card-repair` commit — carrying no marker — refused the very subject the resolver
    had settled on, while (b)-(e) all held (measured on T-12708, 2026-09-18: the two doors of one
    route disagreeing, the X-1251 class again). So (a) now reads the row through the SAME view when
    the host injects it (`_custody_commit_landed`, `bin/lib/cli.py`); an uninjected reader falls back
    to the raw row, which is today's stricter behaviour. NOTHING is widened: the identity half — the
    subject IS the row's commit — and the marker half are unchanged, so a pause / park / closure
    record offered AS the subject is refused exactly as before (its own row carries no marker, and
    when it holds custody the view returns that raw row).

    Pure predicate: True ONLY when every conjunct is provable; False on absence, on malformed input,
    and on any git failure. Never raises — a discriminator that cannot verify must not grant."""
    try:
        # (a) PROVENANCE — the subject IS the task's recorded commit, and that record is the one the
        #     governed `--fix-red --card-repair` arm wrote. Identity first: an admission that did not
        #     check WHICH commit it is looking at could be satisfied by any marked history.
        #     T-12727: «recorded» is read through the custody view the subject resolver took
        #     (`_custody_commit_landed`), the kind-blind raw row only when no such view is injected.
        _read_recorded = _custody_commit_landed or _recorded_commit_landed
        rec = _read_recorded(tid) if _read_recorded else None
        if not isinstance(rec, dict):
            return False
        if rec.get("card_repair") is not True:
            # T-12060 (T-12030, fourth halt) — THE ABSORPTION-MARKED SIBLING. The `card_repair`
            # marker is the governed arm's provenance, but it is not the only way a card repair
            # legitimately reaches the journal: an OWNER-DIRECTED acceptance amendment committed
            # through the E-0030 late-finding escape `task commit --absorb --owner-reset` records
            # `absorption: true` instead. That commit IS a card repair by every fact this predicate
            # can check — and the arm that would stamp the other marker cannot be re-entered,
            # because the same `--absorb` dissolved the T-0275 hazard state `--fix-red --card-repair`
            # requires (the escapes are STRUCTURALLY NON-STACKABLE by design, `bin/lib/task.py`
            # :13958-13966 / :14027). Refusing on the MARKER NAME alone therefore left T-12030 with
            # NO governed custody route at all, with conjuncts (b)-(e) all passing.
            #
            # WHAT REPLACES THE MARKER, so this stays a discriminator and not a hole: `card_repair`
            # is written by an arm that ALREADY proved the commit is record-only, so admitting
            # `absorption` requires that same property PROVEN HERE — every path in the subject's own
            # diff is lifecycle bookkeeping for this tid, read through the SAME
            # `_bookkeeping_commit_authored_paths` allow-list conjunct (d) below uses (CHARTER §P5 —
            # one definition of "authored"). `[]` is record-only; `None` (git could not answer) is
            # not `[]`, so an unverifiable subject refuses, and an uninjected reader refuses too.
            # NOTHING ELSE IS RELAXED: conjuncts (b)-(e) apply to this arm unchanged, so an
            # absorption-marked commit whose RED is about the SHIPPED DIFF (c), or that does not sit
            # directly on the audited ship (e), is refused exactly as before — and the
            # `card_repair`-marked path above is byte-unchanged.
            if rec.get("absorption") is not True:
                return False
            if not callable(_bookkeeping_commit_authored_paths):
                return False
            if _bookkeeping_commit_authored_paths(sha, tid) != []:
                return False
        recorded = str(rec.get("commit") or "").strip()
        if not recorded or not _git_resolve_sha:
            return False
        if (_git_resolve_sha(recorded) or "") != (_git_resolve_sha(sha) or "\x00"):
            return False
        # (b) SHAPE — the subject's diff carries THIS card's own record. Read off GIT, which the
        #     marker cannot forge: without this clause a marked commit touching anything at all would
        #     qualify. (The caller has already established the rest of the diff is bookkeeping.)
        own = _empty_subject_own_paths(sha, REPO_ROOT)
        if not any(_is_own_card_path(pth, tid) for pth in own):
            return False
        # (c) a PRIOR audit-post record names the commit it covered — the audited ship — AND that
        #     record is a RED whose cause is the CARD RECORD. Read from the governed verdict YAML:
        #     this is what makes the admission answer a real repair request rather than a claim.
        prior = _prior_audit_record(tid, "post") if _prior_audit_record else None
        covered = str((prior or {}).get("commit") or "").strip()
        # T-12723 — THE LIVE RECORD IS THE PASS PINNED TO THIS REPAIR ITSELF. When a later pass
        #     audited the repair (the T-12708 shape: pass 2 on the `--card-repair` commit RED-ed on a
        #     NON-card cause and became the ceiling row's own subject), the live record's `commit`
        #     IS `sha`: its cause is that pass's, not the repair request's, and (e) would be asked to
        #     reach `sha` from `sha`. Conjuncts (c)/(d)/(e) are about the record the repair ANSWERED,
        #     so over exactly that equality they read the record the repair commit FOLDED — the
        #     superseded verdict committed in `sha` (`_folded_audit_post_record`), pinned to the
        #     ship and carrying the card-record cause. This is what lets the SPEC-0204 rule-3 pass
        #     re-admit the subject the ceiling pass already admitted, without a flag and without
        #     widening the guard: a subject whose live record is pinned ELSEWHERE reads exactly as
        #     before, a subject that folded no record refuses, and (a)/(b) are already proven above.
        #     Both shas resolve through the injected resolver, so a short recorded form still
        #     compares on identity; an unresolvable side is not `==` and the read stays off.
        if (covered and callable(_git_resolve_sha)
                and (_git_resolve_sha(covered) or "") == (_git_resolve_sha(sha) or "\x00")):
            prior = _folded_audit_post_record(sha, tid, REPO_ROOT)
            covered = str((prior or {}).get("commit") or "").strip()
        if not covered or not _bookkeeping_commit_authored_paths:
            return False
        # T-12026: the SHARED predicate — the SAME call `task commit --fix-red --card-repair`
        # makes, so the commit door and this one cannot disagree about one RED (X-1251). Injected,
        # because its allow-list + card readers are the host's; a missing injection refuses.
        if not (callable(_red_cause_is_card_record) and _red_cause_is_card_record(tid, prior)):
            return False
        # (d) that ship carries authored content, so the cumulative range the packet sends is not
        #     empty — a record that merely NAMES a commit proves nothing about what the auditor gets.
        #     T-12829: when `covered` is itself an EARLIER card-repair (record-only), the authored
        #     ship is resolved back through the records each repair folded — the SHARED resolver the
        #     commit door and `_ship_contained_record_only` also read. Conjunct (e) below is unchanged:
        #     the subject must still reach `covered` transparently.
        ship = _card_repair_authored_ship(tid, covered,
                                          _bookkeeping_commit_authored_paths=_bookkeeping_commit_authored_paths,
                                          _git_resolve_sha=_git_resolve_sha, REPO_ROOT=REPO_ROOT)
        if not ship or not _bookkeeping_commit_authored_paths(ship, tid):
            return False
        # (e) CHAIN CONTINUITY — the first-parent chain from the subject reaches that covered ship
        #     across TRANSPARENT commits ONLY. T-12436 WIDENED THIS FROM BARE PARENTHOOD, and the
        #     widening is not a relaxation of what it fences. The arm builds the repair on top of the
        #     commit the RED graded, so the ORIGINAL `sha^1 == covered` was its exact shape — until
        #     the dispatch preamble began MANDATING a `worktree sync` pre-flight before the land
        #     (point 7 / T-11313). That sync writes GOVERNED commits between the two: an
        #     update-from-main merge and its own bookkeeping commit. Measured on T-12420 (2026-09-12):
        #     ship f0ab1656 -> chore card bookkeeping bc6d0ed5 -> `worktree sync: bookkeeping`
        #     b24dd40b -> merge 41878308 -> repair 8e3533cd, with conjuncts (a)-(d) ALL passing and
        #     this one alone refusing — so ANY card that pre-flighted its land became structurally
        #     unable to pass the audit door on a route the COMMIT door had just admitted it to. That
        #     is the X-1251 two-doors-disagree class again (T-12026), on a different conjunct.
        #     So the walk crosses only what `_card_repair_chain_transparent` PROVES carries nothing of
        #     this card between the two — a record-only non-merge commit, or an update-from-main merge
        #     — and it is BOUNDED, so an unbounded or cyclic history refuses rather than spinning.
        #     MERE ANCESTRY IS STILL REFUSED: an authored commit anywhere on the chain stops the walk,
        #     which is exactly the card-only-commit-made-later-in-the-branch case this conjunct exists
        #     for. The FIRST iteration is the original test unchanged — `sha^1 == covered` admits
        #     before any transparency question is asked.
        return _card_repair_chain_walk(
            sha, covered, tid,
            _bookkeeping_commit_authored_paths=_bookkeeping_commit_authored_paths,
            _git_resolve_sha=_git_resolve_sha, REPO_ROOT=REPO_ROOT)
    except Exception:      # noqa: BLE001 — an unprovable admission is simply not granted
        return False


def _card_declared_ac_ids(card, *, _ACCEPTANCE_AC_RE) -> set:
    """T-12026 — the acceptance-criterion ids THIS CARD actually declares (`AC1`, `AC3`, ...), read
    from the card's own `acceptance` list. Pure f(card); `set()` on an absent or malformed card, so
    strand (iii) above simply does not fire rather than firing on a number the card never declared.

    Anchored at the START of each acceptance entry — the shape every card in this corpus authors
    (`AC3: the lens reads ...`). A bare `AC7` mentioned mid-sentence in some other criterion's prose
    is NOT a declaration, and admitting one would let a card widen its own admission by writing a
    number, which is the card-authored analog of the keyword test this replaces."""
    if not isinstance(card, dict):
        return set()
    acc = card.get("acceptance") or []
    if isinstance(acc, str):
        acc = [acc]
    out = set()
    for entry in acc:
        m = _ACCEPTANCE_AC_RE.match(str(entry))
        if m:
            out.add(m.group(1).lstrip("0") or "0")
    return out


def _is_own_card_path(path: str, tid: str) -> bool:
    """T-11991 — is `path` THIS task's own card (`tasks/<tid>(-slug)?.yaml`)? The same path shape
    `_zero_ship_diff_bookkeeping` allow-lists as the card, read here from the positive side. Stated as
    its own two-line predicate rather than importing the host's, so this module keeps no second
    opinion about what a lifecycle record is — it only asks which ONE of them is the card."""
    parts = (path or "").strip().split("/")
    return (len(parts) == 2 and parts[0] == "tasks"
            and re.fullmatch(rf"{re.escape(tid)}(-[^/]*)?\.yaml", parts[1]) is not None)
