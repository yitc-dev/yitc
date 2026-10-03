"""audit_consult — the audit CONSULT subsystem (the consult episode FSM, its packet and its parser),
extracted byte-identical from `bin/lib/audit.py` (T-12696, card C6 of plan
`extract-the-13-over-budget-bin-lib-modules-into-le`).

WHAT IS IN HERE. The FROZEN manifest of the plan's §Extraction map C6 — the `consult_*` + `_consult_*`
families plus `cmd_audit_consult`, `build_plan_consult_prompt`, `parse_audit_verdict`,
`_parse_consult_result`, `_parse_findings_structured`, `_extract_fenced_block`, `_bounded_raw_source`,
`_survivor_is_hold_for_owner`, `_consult_str`, `_consult_adjudicate`, `consult_adjudicate_round` —
69 top-level defs, ONE indivisible subsystem (the episode FSM + its packet + its parser are one flow).
NOT IN HERE: `cmd_audit` / `cmd_audit_pre|post|adhoc|run|status|canary_backstop`, the gates, the
`_invoke_*` / `_resolve_*` families and the packet builders — those stay in the host (C7a/C7b are the
packet and ceiling families' own cards).

SEAM (the T-9340 / T-9341 / T-11519 / T-11522 full inject-residue shape, `lessons/library-extraction.md`
§AST-freeze generator): every body and signature below is spliced VERBATIM from the original source —
never `ast.unparse` — and every non-stdlib free name (host stayers, host globals, the host's `lib`
module aliases, AND moved siblings via their host residue) arrives as a keyword-only injected
parameter, computed with `symtable` over each function's scope SUBTREE. Constants exclusive to the
move-set live module-local below (the host keeps a re-export alias for each). The host keeps a
`functools.wraps` residue under every historical name, so every `yitc.<sym>` / `audit.<sym>`
monkeypatch and every cross-module injection keeps resolving, and `inspect.getsource` unwraps to the
body here.

Identity-agnostic KERNEL module (SPEC-0073 bin/ HARD class). It imports only stdlib; it NEVER
back-imports the host (`tests/test_bin_lib_leaf_no_host_import.py`). Intentionally spec-less
(SPEC-0005 admission test): a byte-identical relocation mints no standing rule — the governing specs
(SPEC-0025 / SPEC-0200 / SPEC-0204) keep their homes and point their `implements:` anchors here.
"""
from __future__ import annotations

import re
import subprocess
import sys
import time
from pathlib import Path


# ---------------------------------------------------------------------------
# Constants exclusive to the move-set (referenced by movers only — verified across the host,
# tests/ and bin/lib/ by the generator's fixpoint), moved module-local so the bodies read them
# 1:1, uninjected. The host keeps a re-export alias under each historical name.
# ---------------------------------------------------------------------------
_FENCE_LINE_RE = re.compile(r"^\s*```")

_OPENING_FENCE_RE = re.compile(r"^\s*```+\s*\S")

_BASIS_NONCONVERGED_MARK = "did not converge to exactly ONE survivor"

_BASIS_NO_BASIS_FP_MARK = "carries NO basis_fingerprint"

_BASIS_TERMINAL_EPISODE_MARK = "the ceiling EPISODE has already ENDED"

_CONSULT_BASIS_DERIVED_BOOKKEEPING_FILES = frozenset({"events.jsonl"})

_CONSULT_BASIS_DERIVED_BOOKKEEPING_DIRS = ("graph/",)

CONSULT_BLOCKING_AUDITOR_FIELDS = ("locator", "failing_input", "causality")

CONSULT_CAUSALITY_VALUES = frozenset({"introduced-by-subject", "pre-existing-in-subject"})

CONSULT_VIOLATION_UNSUBSTANTIATED = "unsubstantiated-block"

CONSULT_VIOLATION_MISSING_DISPOSITION = "missing-disposition"

CONSULT_VIOLATION_INVALID_CRITERION = "invalid-criterion"

CONSULT_VIOLATION_INVALID_CLASS = "invalid-class"

CONSULT_VIOLATION_INVALID_RESOLUTION = "invalid-resolution"

CONSULT_VIOLATION_DUPLICATE_REF = "duplicate-ref"

CONSULT_VIOLATION_CONFLICT = "conflict"

CONSULT_VIOLATION_UNACCOUNTED = "unaccounted"

CONSULT_VIOLATION_INVALID_REF = "invalid-ref"

CONSULT_VIOLATION_INCOMPLETE_SURVEY = "incomplete-survey"

CONSULT_RESOLUTION_WITHDRAWN_SCOPE_CUT = "withdrawn-by-scope-cut"

CONSULT_RESOLUTION_WITHDRAWN_OWNER_RULING = "withdrawn-by-owner-ruling"

CONSULT_RESOLVED_VALUES = ("closed", CONSULT_RESOLUTION_WITHDRAWN_SCOPE_CUT,
                           CONSULT_RESOLUTION_WITHDRAWN_OWNER_RULING)

CONSULT_WITHDRAWN_VALUES = (CONSULT_RESOLUTION_WITHDRAWN_SCOPE_CUT,
                            CONSULT_RESOLUTION_WITHDRAWN_OWNER_RULING)

_CONSULT_CUT_RECEIVER_RE = re.compile(r"\bCUT\s+to\s+([A-Z]+-\d{3,})\b")

_CONSULT_CUT_DIRECTIVE_RE = re.compile(r"\bowner_directive\s+(\S+)")

_CONSULT_CUT_LOCATOR_STRIP = ")],;:.'\""

_CONSULT_RULING_RE = re.compile(
    r"^WITHDRAWN\s+(B\d+|R\d+\.\d+)\s+out-of-subject\s+to\s+([A-Z]+-\d{3,})\b")

_CONSULT_EMBEDDED_ID_RE = re.compile(r"(?<![\w.])(?:B\d+|R\d+\.\d+)(?![\w.])")

CONSULT_MAX_RETESTS = 2          # rule 6 (4): R = 2 is the terminal bound

CONSULT_MAX_MALFORMED = 1        # rule 2: ONE malformed re-run PER EPISODE

CONSULT_BASELINE_SCHEMA = 1      # rule 2: the ONLY legacy-migration provenance marker

CONSULT_ESCAPE_FINGERPRINT = "consult-baseline-completeness-failure"

CONSULT_SUCCESSOR_PREFIX = "consult-successor:"

CONSULT_ESCAPE_KEY_FIELD = "escape_key"

_CONSULT_RETEST_OUTPUT_BLOCK = (
    "findings:            # SPEC-0200 rule 4 — ECHOES of the open ids, plus any REGRESSION\n"
    "  - baseline_ref: <the BARE id from that row's `id:` column — e.g. `B1` or `R1.2`, and\n"
    "                   NOTHING else: not the whole table row, not the id in brackets>\n"
    "    resolution: open | closed\n"
    "    resolution_evidence: <REQUIRED when closed — a locator / test node / diff ref>\n"
    "  - disposition: blocking          # a NEW finding: a regression the fix introduced\n"
    "    criterion_ref: <exact criterion>   # or class_id, per rule 3\n"
    "    locator: <file:symbol>\n"
    "    failing_input: <concrete>\n"
    "    causality: introduced-by-subject\n"
)

_CONSULT_LENS_SLUG_RE = re.compile(r"[^a-z0-9]+")

CONSULT_REFUSAL_HAND_FRAMED = "hand-framed-options"

CONSULT_REFUSAL_EPISODE_BUSY = "episode-busy"

CONSULT_REFUSAL_EPISODE_ENDED = "episode-ended"

CONSULT_CONTRACT_ACTIVE = True

CONSULT_PARTIAL_SWITCH_REFUSAL = (
    "consult-contract-partially-switched: the SPEC-0200 round-k prompt overlay is disabled while the "
    "re-keyed predicates are live. That is not a degraded mode, it is a CONTRADICTORY state — the "
    "auditor would be asked a whole-subject question and its answer judged by delta rules (or the "
    "reverse), and rule 7 says in as many words that a partially-landed state is not a valid state of "
    "this contract. Refusing rather than falling through to the pre-C3 path: the legacy path cannot "
    "produce the persisted `offered_options` the re-keyed `_survivor_is_hold_for_owner` compares "
    "against, so a fall-through would silently stop recognising owner-held HOLDs — exactly the "
    "T-12150 r8 failure. There is no supported way to run half of this contract."
)


# ---------------------------------------------------------------------------
# INJECTS — per mover, the keyword-only names its spliced signature gained (generated with
# `symtable` over the function's scope subtree, minus stdlib imports / builtins / the consts
# above). The host residue under each historical name reads exactly this roster from its OWN
# globals at call time (`audit._consult_inject`), so the roster lives beside the signatures it
# describes and every residue stays a 5-line forwarder. A mover with no entry takes no inject.
# ---------------------------------------------------------------------------
INJECTS = {
    "consult_packet_max_bytes": ("CONSULT_PACKET_MAX_BYTES",),
    "_parse_findings_structured": ("AUDITOR_SUPPLIED_FINDING_FIELDS", "BULLET_START_RE", "CONT_FIELD_RE",
                                   "ENGINE_SUPPLIED_FINDING_FIELDS", "ON_DECISIONS_FINDING_FIELDS"),
    "_bounded_raw_source": ("RAW_FINDINGS_SOURCE_MAX_CHARS",),
    "parse_audit_verdict": ("BULLET_LINE_RE", "RAW_BULLET_FALLBACK_MARKER", "RAW_FINDINGS_SOURCE_HEADER",
                            "SEVERITY_WORD_RE", "VERDICT_LINE_RE", "_bounded_raw_source",
                            "_extract_fenced_block", "_parse_findings_structured", "state"),
    "consult_hold_is_nonconverged": ("CONSULT_OUTCOME_HOLD",),
    "_survivor_is_hold_for_owner": ("CONSULT_OUTCOME_OWNER_HELD",),
    "_consult_record_only_delta": ("events_mod", "textutil"),
    "_consult_basis": ("CONSULT_OUTCOME_OWNER_HELD", "CONSULT_OUTCOME_PROCEED", "CONSULT_OUTCOME_TERMINAL",
                       "_consult_record_only_delta", "_survivor_is_hold_for_owner", "state"),
    "_parse_consult_result": ("VERDICT_LINE_RE", "state"),
    "consult_finding_disposition": ("CONSULT_BLOCKING_CLASS_IDS", "_consult_str"),
    "_consult_baseline_entry": ("_consult_str",),
    "consult_freeze_baseline": ("_consult_baseline_entry", "consult_finding_disposition"),
    "consult_legacy_baseline": ("_consult_baseline_entry",),
    "_consult_survivor_texts": ("_consult_str",),
    "consult_admission": ("AUTO_CONSULT_PROCEED_OPTION", "CONSULT_NON_ADMISSIBLE_MULTIPLE_SURVIVORS",
                          "CONSULT_NON_ADMISSIBLE_RED_PROCEED", "CONSULT_NON_ADMISSIBLE_SURVIVOR_NOT_OFFERED",
                          "CONSULT_NON_ADMISSIBLE_ZERO_SURVIVORS", "_consult_survivor_texts"),
    "consult_response_is_malformed": ("CONSULT_ROUND_KIND_BASELINE", "_consult_str"),
    "consult_round_kind": ("CONSULT_ROUND_KIND_BASELINE", "CONSULT_ROUND_KIND_RETEST",
                           "_consult_prior_state"),
    "consult_packet_assemble": ("CONSULT_PACKET_SCOPE_DELTA", "CONSULT_PACKET_SCOPE_FULL",
                                "CONSULT_ROUND_KIND_RETEST"),
    "_consult_classify_retest": ("_consult_baseline_entry", "_consult_embedded_open_id", "_consult_str",
                                 "consult_finding_disposition"),
    "consult_adjudicate_round": ("CONSULT_MAX_NO_ANSWERS", "CONSULT_NO_ANSWER_ROUTE_UNAVAILABLE",
                                 "CONSULT_OUTCOME_HOLD", "CONSULT_OUTCOME_MALFORMED",
                                 "CONSULT_OUTCOME_NO_ANSWER", "CONSULT_OUTCOME_OWNER_HELD",
                                 "CONSULT_OUTCOME_PROCEED", "CONSULT_OUTCOME_TERMINAL",
                                 "CONSULT_ROUND_KIND_BASELINE", "CONSULT_ROUND_KIND_RETEST",
                                 "CONSULT_TERMINAL_MALFORMED_EXHAUSTED", "CONSULT_TERMINAL_NON_ADMISSIBLE",
                                 "CONSULT_TERMINAL_OPEN_IDS_AT_R2", "CONSULT_VIOLATION_MALFORMED",
                                 "_consult_classify_retest", "_consult_prior_state", "consult_admission",
                                 "consult_freeze_baseline", "consult_response_is_malformed",
                                 "is_no_data_verdict"),
    "consult_allocate_episode": ("consult_episode_id", "consult_episode_transition"),
    "consult_escape_residual_ids": ("_consult_str",),
    "consult_escape_keys": ("consult_attempt_id", "consult_escape_residual_ids"),
    "consult_escape_deviations": ("consult_escape_key_token", "consult_escape_keys",
                                  "consult_recorded_escape_keys"),
    "consult_emit_escape_deviations": ("consult_escape_deviations",),
    "consult_successor_text": ("_consult_str",),
    "consult_file_successors": ("consult_successor_key", "consult_successor_locator",
                                "consult_successor_text"),
    "consult_episode_row_fields": ("consult_escape_residual_ids",),
    "consult_task_lens": ("_card_declared_ac_ids",),
    "consult_scope_cuts": ("_ACCEPTANCE_AC_RE",),
    "consult_owner_rulings": ("_amend_note_body",),
    "consult_plan_gate_lens": ("consult_criterion_slug",),
    "consult_open_entries": ("_consult_prior_state",),
    "consult_baseline_table": ("_consult_prior_state", "_consult_str"),
    "consult_withdrawn_block": ("_consult_prior_state",),
    "consult_prompt_overlay": ("CONSULT_ROUND_KIND_BASELINE", "_AUDIT_FULL_VERDICT_CLAUSE",
                               "_CONSULT_BASELINE_OUTPUT_BLOCK", "consult_baseline_table",
                               "consult_lens_block", "consult_withdrawn_block"),
    "consult_offered_pair": ("AUTO_CONSULT_HOLD_OPTION", "AUTO_CONSULT_PROCEED_OPTION"),
    "consult_options_are_offered_pair": ("consult_offered_pair",),
    "consult_hand_framed_refusal": ("consult_options_are_offered_pair",),
    "consult_episode_scan": ("CONSULT_TERMINAL_OUTCOMES",),
    "consult_journal_state": ("consult_episode_scan",),
    "consult_episode_ended_refusal": ("CONSULT_TERMINAL_OUTCOMES",),
    "consult_episode_is_terminal": ("CONSULT_TERMINAL_OUTCOMES",),
    "consult_episode_busy_refusal": ("consult_episode_id",),
    "consult_hold_is_sticky": ("consult_sticky_hold_open_ids",),
    "consult_plan_reset_admitted": ("CONSULT_OUTCOME_PROCEED",),
    "consult_terminal_owner_route": ("consult_sticky_hold_open_ids",),
    "_consult_adjudicate": ("AUDIT_INSPECTION_CONSULT_CLASS", "CONSULT_ADJUDICATION_RECORD_FIELDS",
                            "CONSULT_NO_ANSWER_ROUTE_UNAVAILABLE", "CONSULT_OUTCOME_NO_ANSWER",
                            "CONSULT_OUTCOME_PROCEED", "CONSULT_ROUND_KIND_BASELINE",
                            "CONSULT_TERMINAL_OUTCOMES", "_audit_duration_ms", "_capacity_hint_via",
                            "auditor_failure_cause", "consult_adjudicate_round", "consult_allocate_episode",
                            "consult_emit_escape_deviations", "consult_episode_busy_refusal",
                            "consult_episode_ended_refusal", "consult_episode_row_fields",
                            "consult_file_successors", "consult_hand_framed_refusal", "consult_journal_state",
                            "consult_offered_pair", "consult_opens_next_episode", "consult_packet_assemble",
                            "consult_packet_max_bytes", "consult_prompt_overlay", "consult_round_kind",
                            "consult_round_withdrawn", "consult_terminal_owner_route",
                            "findings_complete_declared", "inspection", "invoke_auditor_tiered",
                            "is_no_data_verdict", "observe", "stamp_auditor_verdict", "state"),
    "cmd_audit_consult": ("RETIRED_AUDIT_SURFACES", "RETIRED_CEILING_POINTER", "_consult_adjudicate",
                          "_consult_post_subject", "build_plan_consult_prompt",
                          "consult_hold_is_nonconverged", "consult_status_refusal",
                          "consult_sticky_hold_open_ids", "consult_task_lens", "observe",
                          "parse_audit_verdict", "resolve_model_for_provider", "state"),
}


def consult_packet_max_bytes(*, CONSULT_PACKET_MAX_BYTES) -> int:
    """The byte bound on an assembled consult packet — a SPEC-0193 PERFORMANCE read site (T-12233).

    Same per-call resolution shape and the same rule-6 read-site validation as
    `_inspection_timeout_seconds` above (a 0 or negative bound would put EVERY packet over bound).

    The bound is SOFT and RECORDED: it chooses between two scopes that admit the SAME judgement and
    otherwise sends the packet whole — see `consult_packet_scope_for` for the contract it feeds.
    """
    try:
        from lib import machine_settings      # deferred: keeps the hot import graph unchanged
        val = int(machine_settings.resolve("lib.audit.CONSULT_PACKET_MAX_BYTES",
                                           CONSULT_PACKET_MAX_BYTES))
    except Exception:            # noqa: BLE001 — SPEC-0193 rule 6: never a prerequisite
        return CONSULT_PACKET_MAX_BYTES
    return val if val > 0 else CONSULT_PACKET_MAX_BYTES


def _parse_findings_structured(text: str, *, AUDITOR_SUPPLIED_FINDING_FIELDS, BULLET_START_RE, CONT_FIELD_RE, ENGINE_SUPPLIED_FINDING_FIELDS, ON_DECISIONS_FINDING_FIELDS) -> list[dict]:
    """T-0037: structured multi-line bullet parser для codex findings блока.

    Recovers {severity, what, where, fix} dicts from text где yaml.safe_load
    failed но findings формат still recognizable. Each finding starts с
    «- severity: <word>» line; continuation fields (what/where/fix) on
    subsequent deeper-indented lines. Continuation values may span multiple
    lines until next bullet либо less-indented non-blank line.
    """
    findings: list[dict] = []
    current: dict | None = None
    base_indent = -1  # indent of «- severity:» line for current item
    cont_indent = -1  # indent of currently-accumulating continuation field
    current_key: str | None = None
    lines = text.splitlines()

    _CONTRACT_KEYS = frozenset(
        AUDITOR_SUPPLIED_FINDING_FIELDS + ENGINE_SUPPLIED_FINDING_FIELDS
        + ON_DECISIONS_FINDING_FIELDS      # T-12289 — an `echo_of`-led bullet is a finding too
    )

    def flush() -> None:
        nonlocal current, current_key
        # A legacy finding is kept iff it recovered a `what` — unchanged. A contract-led finding is
        # kept on any declared field, since `what` is not required to carry one (and a legacy
        # finding never has a contract key, so this disjunction cannot alter the legacy verdict).
        if current is not None and (
            current.get("what") or (_CONTRACT_KEYS & current.keys())
        ):
            findings.append(current)
        current = None
        current_key = None

    for raw_line in lines:
        line = raw_line.rstrip()
        # Empty line OR end-of-text — close current accumulating field but keep
        # the finding open (codex sometimes emits blank line between fields).
        if not line.strip():
            current_key = None
            continue
        start_match = BULLET_START_RE.match(line)
        if start_match:
            flush()
            # A severity-led bullet builds EXACTLY the dict it always did — the legacy seeding of
            # what/where/fix is preserved byte-for-byte (AC2).
            #
            # An `id:`/`disposition:`-led bullet is the WIDENED recognition, and it seeds NOTHING:
            # `severity` is optional under the response contract, so inventing a sentinel rank —
            # or empty what/where/fix — would be exactly the defaulting the contract forbids
            # (absent -> ABSENT). Only the leading key is transcribed, verbatim.
            sev = start_match.group("sev")
            if sev:
                current = {"severity": sev.lower(), "what": "", "where": "", "fix": ""}
            else:
                current = {start_match.group("key").lower(): start_match.group("val").strip()}
            base_indent = len(start_match.group("indent"))
            cont_indent = -1
            current_key = None
            continue
        if current is None:
            continue
        # Determine indent level — must be deeper than base_indent для continuation.
        line_indent = len(line) - len(line.lstrip())
        if line_indent <= base_indent:
            flush()
            continue
        cont_match = CONT_FIELD_RE.match(line)
        if cont_match:
            current_key = cont_match.group("key").lower()
            cont_indent = len(cont_match.group("indent"))
            current[current_key] = cont_match.group("value").strip()
            continue
        # Multi-line continuation of previous field — append с space separator.
        if current_key and line_indent > cont_indent:
            extra = line.strip()
            current[current_key] = (
                f"{current[current_key]} {extra}".strip() if current[current_key] else extra
            )
    flush()
    return findings


def _bounded_raw_source(region: str, *, RAW_FINDINGS_SOURCE_MAX_CHARS) -> str:
    """Bound `region` to the tail RAW_FINDINGS_SOURCE_MAX_CHARS, marking any truncation.

    Verbatim by contract — no fence-stripping, no degenerate-tail collapse: the whole point is
    that a human can read what the auditor actually said. Pure f(str)->str."""
    text = region.strip("\n")
    if len(text) <= RAW_FINDINGS_SOURCE_MAX_CHARS:
        return text
    dropped = len(text) - RAW_FINDINGS_SOURCE_MAX_CHARS
    return f"[truncated {dropped} leading chars]\n{text[-RAW_FINDINGS_SOURCE_MAX_CHARS:]}"


def _extract_fenced_block(text: str) -> str:
    """T-0468 — return the content of the FIRST markdown code-fence in `text`, dropping the
    opening ```lang line + the closing ``` line + any stray prose before/after the block.
    Mirrors the proven _parse_consult_result fence-normalize (between the first opening fence
    and the next closing fence). Four shapes, all from the live fingerprint
    `audit-adhoc-fenced-yaml-findings-not-parsed`:
      - full ```yaml … ``` block (possibly prose-wrapped, audit-pre F2): take the lines BETWEEN
        the first fence and the next fence.
      - a tail that begins INSIDE a fence (the verdict line is past the opening ```, so only a
        trailing CLOSING ``` survives — a bare ``` with no info-string): take the lines BEFORE
        it (a lone closing fence truncates, the _parse_consult_result branch).
      - a lone OPENING fence (```yaml with an info-string, no closing fence — an unterminated /
        truncated auditor response, audit-post pass-1 F0): take the lines AFTER it, so the YAML
        payload is recovered rather than the leading prose (the no-closing-fence fallback).
      - NO fence at all: return the input UNCHANGED, so the bare path stays byte-for-byte
        identical (AC2 regression guard — this helper is identity on un-fenced input).
    Pure f(str)->str, trivially testable."""
    lines = text.splitlines()
    fence_idxs = [i for i, ln in enumerate(lines) if _FENCE_LINE_RE.match(ln)]
    if not fence_idxs:
        return text                                          # no fence → identity (AC2)
    if len(fence_idxs) >= 2:
        block = lines[fence_idxs[0] + 1:fence_idxs[1]]       # between first opening + next closing
    elif _OPENING_FENCE_RE.match(lines[fence_idxs[0]]):
        block = lines[fence_idxs[0] + 1:]                    # lone OPENING fence → payload AFTER it
    else:
        block = lines[:fence_idxs[0]]                        # lone CLOSING fence truncates the tail
    return "\n".join(block)


def parse_audit_verdict(stdout: str, *, BULLET_LINE_RE, RAW_BULLET_FALLBACK_MARKER, RAW_FINDINGS_SOURCE_HEADER, SEVERITY_WORD_RE, VERDICT_LINE_RE, _bounded_raw_source, _extract_fenced_block, _parse_findings_structured, state) -> tuple[str, list, str]:
    """Parse codex stdout: take LAST canonical verdict line (audit-pre F1 absorption).

    Returns (verdict, findings_list, parse_notes).

    Three-stage extraction:
      1. YAML-shape block AFTER last verdict line — strict, preferred (T-0034). The strict
         attempt runs on the raw tail FIRST, then (on a YAMLError OR a no-findings result)
         retries on the fence-normalized tail (_extract_fenced_block, T-0468) — recovers
         findings the auditor wrapped in a markdown ```yaml fence (fingerprint
         `audit-adhoc-fenced-yaml-findings-not-parsed`, N=2+ incl. this task's own audit-pre).
      2. Structured multi-line bullet parser в preamble — recovers nested
         findings когда yaml.safe_load fails on mixed-quote unquoted scalars (T-0037).
      3. Raw single-line bullet fallback — last resort; produces misleading
         «what: severity: X» dicts but preserves observation что bullets existed (T-0034).

    T-10714 — SOURCE PRESERVATION on a degraded parse: when the findings come from stage 2 or
    stage 3 (i.e. yaml-strict failed), the scanned findings region is appended VERBATIM to
    parse_notes under RAW_FINDINGS_SOURCE_HEADER, bounded per RAW_FINDINGS_SOURCE_MAX_CHARS.
    A clean stage-1 parse attaches NOTHING — the preservation is a discriminator of degradation,
    not an unconditional attachment. The degradation wording itself is unchanged (still loud).

    T-12179 — THE PER-FINDING RESPONSE CONTRACT IS TRANSCRIBED, NEVER JUDGED (SPEC-0036 §Saved audit
    result; semantics SPEC-0200 rules 3-4). The eleven contract keys — the nine
    AUDITOR_SUPPLIED_FINDING_FIELDS and the two ENGINE_SUPPLIED_FINDING_FIELDS declared above — are
    carried ADDITIVELY per finding: present -> verbatim, absent -> ABSENT. There is NO defaulting
    (an absent `disposition` never becomes `blocking`, and no key is added `None`-valued), NO
    validation, and NO mapping — `severity` is outside the contract set and NEVER derives
    `disposition`. Fail-closed is a property of the USE SITE, not of a parse result
    (`lessons/fail-closed-belongs-to-the-reader-not-the-parser.md`): the reader that classifies these
    fields owns every missing-value judgement. Nothing on main consumes them yet.

    Per-stage coverage of that promise, because it is unconditional:
      * Stage 1 (yaml-strict, the normal path) returns the auditor's dicts VERBATIM, so all eleven
        keys ride through with no code that names them.
      * Stage 2 (structured fallback) recognises a finding bullet led by `severity:`, `id:` or
        `disposition:` and captures continuations on a CLOSED allowlist generated from those same
        declarations — so a compliant finding survives a malformed-YAML response instead of being
        dropped whole. A legacy `severity:`-led finding takes the identical path and yields the
        identical dict.
      * Stage 3 (raw single-line scrape) is UNCHANGED and carries no contract field, by design: it
        recovers one line into {severity, what} as a last resort, and deriving a `locator` or
        `causality` from that would be INVENTING one. It says so loudly in parse_notes instead.
    """
    matches = VERDICT_LINE_RE.findall(stdout)
    no_verdict = not matches
    verdict = "ABORT" if no_verdict else matches[-1]  # LAST match — codex shows example в narrative
    findings = []
    explicit_empty = False  # T-13156 — stage 1 parsed an explicit `findings: []`
    parse_notes = "no canonical verdict line found в codex stdout" if no_verdict else ""
    last_verdict_pos = -1 if no_verdict else stdout.rfind(f"verdict: {verdict}")

    # Stage 1: try YAML parse of tail after verdict (strict path).
    if last_verdict_pos >= 0:
        import yaml
        tail = stdout[last_verdict_pos:]

        def _safe_findings(candidate: str):
            """Parse `candidate` via the single state layer; findings list (dicts only), or None
            when no `findings:` LIST parsed. T-13156: None (did not parse) is kept distinct from
            [] (an explicit `findings: []` — a parsed, clean result the scrapes must not reopen).
            state.load_str raises yaml.YAMLError exactly as safe_load did — fallback unchanged."""
            try:
                parsed = state.load_str(candidate)
            except yaml.YAMLError:
                return None  # parse failure tolerated — caller tries the next candidate
            if isinstance(parsed, dict) and isinstance(parsed.get("findings"), list):
                raw = parsed["findings"]
                kept = [f for f in raw if isinstance(f, dict)]
                # Only an EXACTLY empty list is a clean result; a non-empty list that yields no
                # dict finding (`findings: [invalid]`) stays "did not parse" — fallback unchanged.
                return kept if (kept or not raw) else None
            return None

        # Raw tail FIRST so the existing bare (un-fenced) path is byte-for-byte unchanged (AC2).
        parsed_findings = _safe_findings(tail)
        findings = parsed_findings or []
        fenced = False
        if not findings:
            # T-0468: the auditor wrapped verdict+findings in a markdown ```yaml fence — the
            # trailing ``` makes the raw tail invalid YAML (safe_load RAISES) OR yields no
            # findings. Retry on the fence-normalized tail. _extract_fenced_block is identity
            # on un-fenced input, so this retry never changes the bare-path result.
            stripped = _extract_fenced_block(tail)
            if stripped != tail:
                fenced_findings = _safe_findings(stripped)
                if fenced_findings:
                    findings, fenced = fenced_findings, True
                elif parsed_findings is None and fenced_findings is not None:
                    parsed_findings, fenced = fenced_findings, True
        # T-13156: the block parsed and its findings list is explicitly EMPTY — a clean result.
        explicit_empty = parsed_findings is not None and not findings
        if findings or explicit_empty:
            # T-0037 audit-post F1 absorption: label Stage 1 success path so saved audits name
            # parser provenance per AC2 (+ the T-0468 fence-normalize provenance when used).
            parse_notes = (
                f"findings parsed via yaml-strict on "
                f"{'fence-normalized tail (T-0468)' if fenced else 'tail'} ({len(findings)} items"
                f"{' — explicit empty list, T-13156' if explicit_empty else ''})"
            )

    # Preamble = stdout BEFORE last verdict line (codex emits findings then verdict
    # per prompt «Return strict YAML at the END»). Fall back к whole stdout если
    # no verdict found earlier (defensive — caller already returned ABORT в that case).
    scan_region = stdout[:last_verdict_pos] if last_verdict_pos > 0 else stdout

    # Stage 2: structured multi-line bullet parser (T-0037) — preferred fallback,
    # recovers nested {severity, what, where, fix} dicts от codex multi-line YAML
    # output что failed yaml.safe_load on mixed-quote scalars.
    degraded = False   # T-10714 — True once findings came from a FALLBACK stage (2 or 3)
    # T-13156: the bullet scrapes run only when NO structured findings block parsed.
    structured_block_parsed = explicit_empty

    if not findings and not structured_block_parsed:
        structured = _parse_findings_structured(scan_region)
        if structured:
            findings = structured
            degraded = True
            structured_msg = (
                f"findings recovered via structured multi-line bullet parser "
                f"({len(structured)} items); YAML-shape strict parse failed on "
                f"codex stdout tail (T-0037 path)"
            )
            parse_notes = f"{parse_notes}; {structured_msg}" if parse_notes else structured_msg

    # Stage 3: raw single-line bullet fallback (T-0034) — last resort. Produces
    # likely-misleading {severity, what: «severity: X»} dicts but preserves
    # observation что bullets existed когда other parsers gave nothing.
    if not findings and not structured_block_parsed:
        bullets = BULLET_LINE_RE.findall(scan_region)
        recovered = []
        for bullet_text in bullets:
            text = bullet_text.strip()
            if not text:
                continue
            sev_match = SEVERITY_WORD_RE.search(text)
            severity = sev_match.group(1).lower() if sev_match else "unknown"
            recovered.append({"severity": severity, "what": text})
        if recovered:
            findings = recovered
            degraded = True
            fallback_msg = (
                f"findings recovered via {RAW_BULLET_FALLBACK_MARKER} "
                f"({len(recovered)} items) — likely misleading per T-0037; "
                f"YAML strict + structured multi-line parsers both failed"
            )
            parse_notes = f"{parse_notes}; {fallback_msg}" if parse_notes else fallback_msg

    # T-10714 — the parse DEGRADED (findings came from stage 2 or stage 3), so the placeholder /
    # best-effort dicts above are not a faithful record of what the auditor said. Append the
    # scanned region VERBATIM so the saved verdict stays recoverable by hand. Appended AFTER the
    # degradation wording, never in place of it (the warning stays loud).
    if degraded:
        preserved = _bounded_raw_source(scan_region)
        if preserved:
            parse_notes = f"{parse_notes}\n\n{RAW_FINDINGS_SOURCE_HEADER}\n{preserved}"

    return verdict, findings, parse_notes


def consult_hold_is_nonconverged(survivor_records: list, options: list, findings_complete,
                                 record=None, *, CONSULT_OUTCOME_HOLD) -> bool:
    """Is this HOLD survivor NON-CONVERGED — i.e. does it fail SPEC-0200 rule-6 validation?

    RE-KEYED TO THE C2 RECORD (T-12182 / SPEC-0200 rule 7). Rule 7 states the reading in one
    sentence: «non-converged <=> the round's stated survivor fails rule-6 validation (a PROCEED over
    open blocking ids, or a HOLD that does not name the open set) — never off the `findings_complete`
    declaration, which is RECORDED (rule 2), not gated on».

    THE THREE-STATE HISTORY, because the parameter list still carries its scar and a reader owes an
    explanation for it. T-12141 made this read a HOLD lacking `findings_complete: true` as
    non-converged. That was one half of an every-surface full-verdict clause which ordered a fresh
    whole-subject survey on EVERY pass; measured over the day that followed, audit-post RED share
    went 16% -> 44%, post-audits per task median 2 -> 3, and max consult rounds per (target, stage)
    1 -> 11. T-12168 reverted it to an unconditional `False` — the safe temporary rollback an
    external consult ruled for, because a PROMPT-ONLY narrowing would have left this predicate
    reading every later HOLD as non-converged, defeating owner-held recognition (T-10899) and
    perpetuating the sticky hold (T-11840). This card is the narrowed successor that revert named:
    the exhaustive survey is re-homed to the BASELINE round alone, and this predicate re-arms on the
    RECORD instead of on the declaration.

    `findings_complete` is now READ BY NOTHING here, and the parameter is kept only so the existing
    call shape stays valid. It CANNOT be read: at round k >= 1 the field does not exist in the
    response at all (rule 4 asks for no declaration), so a predicate keyed on it would answer from a
    field the auditor was never asked for — which is exactly how T-12141's version defeated the
    owner-held path.

    `record` is the C2 adjudication delta for this round. FAIL-CLOSED on its ABSENCE: with no record
    there is no open set to validate a survivor against, so this returns False (converged) and the
    caller's other gates decide — the pre-C3 answer, so a legacy record is classified exactly as it
    was. Pure f(args), no I/O."""
    if not isinstance(record, dict) or not record.get("outcome"):
        return False                       # no adjudication to validate against — the legacy answer
    outcome = record.get("outcome")
    if record.get("survivor_overridden"):
        # Row 12: the auditor said PROCEED while blocking ids were open. The machine overrode it to
        # HOLD; the SURVIVOR as stated failed validation, which is precisely non-convergence.
        return True
    if outcome == CONSULT_OUTCOME_HOLD:
        # Row 17: an ordinary HOLD over a NON-EMPTY open set. The episode CONTINUES (the next call is
        # a retest), so this is not a converged basis — and rule 7 is explicit that it is never an
        # owner-reset basis either, because text equality alone cannot tell row 17 from row 16.
        return True
    # Row 16 (owner-held, an EMPTY open set) and row 18 (PROCEED) are CONVERGED. A terminal or a
    # malformed round is not a convergence question — its route is the owner's, per rule 7.
    return False


def _survivor_is_hold_for_owner(d: dict, *, CONSULT_OUTCOME_OWNER_HELD) -> bool:
    """Does this consult record carry a genuine OWNER-HELD hold — the one shape `--owner-reset`
    admits as its basis?

    RE-KEYED (T-12182 / SPEC-0200 rule 7) ON TWO AXES, and BOTH are required:
      (1) the survivor is the HOLD option of the record's PERSISTED `offered_options` pair, by EXACT
          EQUALITY — «never against a reconstruction from post-adjudication state». The pair is
          written onto the record at adjudication time, so the comparison is against what was
          actually offered to the auditor rather than against whatever the constant says today.
      (2) the round's RECORDED `outcome` is `owner-held` (matrix row 16: the matrix proved the open
          set EMPTY and no new blocking finding was returned).

    WHY (2) IS NOT REDUNDANT, which is the whole content of this change. Rows 16 and 17 carry the
    SAME fixed HOLD text — the auditor picks the same option either way — so text equality alone
    cannot tell them apart. Row 17 is a HOLD over a NON-EMPTY open set: the ordinary «retest needed»
    outcome, which CONTINUES the episode. Admitting it as an owner-reset basis would let a card walk
    past open blocking ids on the strength of a HOLD that said the opposite (retest-1 regression
    R1.2). So a row-17 HOLD is never a basis, and `--owner-reset` refuses it.

    T-10899's contribution is UNCHANGED and still load-bearing: the text must match the offered HOLD
    option exactly. `audit consult --option` once accepted arbitrary hand-passed texts, where
    "option 2" meant nothing in particular; rule 7 now refuses those pre-auditor
    (`hand-framed-options`), and this exact-equality check is the second lock behind that refusal —
    it also covers every LEGACY record written before the refusal existed.

    FAIL-CLOSED throughout: a record with no persisted pair, no recorded outcome, or a non-single /
    unresolvable survivor returns False. Pure f(record), no I/O."""
    if not isinstance(d, dict):
        return False
    # (2) the RECORDED outcome. A record predating the contract carries none, and proves no row 16.
    if d.get("outcome") != CONSULT_OUTCOME_OWNER_HELD:
        return False
    # (1) the PERSISTED pair. Absent => nothing to compare by exact equality against => fail closed.
    offered = d.get("offered_options")
    if not isinstance(offered, list) or len(offered) != 2:
        return False
    hold_text = offered[1]
    if not isinstance(hold_text, str) or not hold_text.strip():
        return False
    survivors = d.get("survivors")
    if not isinstance(survivors, list) or len(survivors) != 1:
        return False
    surv = survivors[0]
    text = None
    if isinstance(surv, dict):
        text = surv.get("text")
        if not text:
            idx = surv.get("option")
            if isinstance(idx, int) and 1 <= idx <= len(offered):
                text = offered[idx - 1]
    elif isinstance(surv, int) and 1 <= surv <= len(offered):
        text = offered[surv - 1]
    return isinstance(text, str) and text.strip() == hold_text.strip()


def _consult_record_only_delta(basis_fp: str | None, current_fp: str | None,
                               consult_rel: str, *, REPO_ROOT, events_mod, textutil) -> bool:
    """T-11007 (<project> X-0848) — is the ONLY tree change between the consult's pinned basis and the
    CURRENT subject the consult's OWN verdict record?

    THE CYCLE THIS SCOPES OUT. A post-stage consult pins `basis_fingerprint` to the task's recorded
    commit SHA (`_recorded_commit_sha`, the last `commit_landed`). `task commit` stages `git add -A`,
    so a commit run while the consult verdict YAML is dirty SWEEPS `decisions/<tid>-audit-consult-
    <stage>.yaml` into a new ship commit and records it — moving the recorded commit PAST the SHA the
    consult pinned ITSELF to, with nothing else changed. The consult then reads `stale` and the
    owner-reset pass is refused: the consult invalidated its own basis by being FILED. Cost as
    measured: one wasted consult + one wasted audit pass, and the only exit was undocumented ordering
    knowledge (run the consult LAST, do not commit it until the owner-reset pass has read it) that
    every operator rediscovers by burning that cycle.

    NOT the sibling cycle, and deliberately so: when a NEW commit ABSORBS the consult's FINDING the
    audit SUBJECT genuinely postdates the consult, the staleness is CORRECT, and the sanctioned exit
    is the existing T-0448 re-consult against the absorbed tree. That delta touches the absorbed
    source, so it is not consult-record-only and this predicate returns False — the freshness
    guarantee is SCOPED here, never removed.

    FAIL-CLOSED — the exception opens only on POSITIVE evidence on EVERY axis (the standing craft rule
    for relaxing a fail-closed gate, `lessons/carving-an-exception-into-a-fail-closed-gate.md`):
    BOTH fingerprints must resolve to real git COMMITS, the diff command must SUCCEED, the delta must
    be NON-EMPTY and CONTAIN `consult_rel`, and every remaining path must be derived bookkeeping.
    Anything the discriminator cannot answer — a fingerprint that is not a commit (a PRE-stage
    plan_fingerprint is a content hash, so this predicate is inert on that whole stage by
    construction), a missing fingerprint, a non-git repo, a git failure of ANY kind — returns False
    and leaves the caller's existing `stale` refusal untouched."""
    if not basis_fp or not current_fp or not consult_rel:
        return False
    resolved = []
    for fp in (basis_fp, current_fp):
        try:
            r = subprocess.run(["git", "-C", str(REPO_ROOT), "rev-parse", "--verify", "--quiet",
                                f"{fp}^{{commit}}"], capture_output=True, text=True, check=False)
        except (FileNotFoundError, OSError):
            return False
        if r.returncode != 0 or not (r.stdout or "").strip():
            return False   # not a commit (e.g. a plan-fingerprint content hash) — no relief here
        resolved.append(r.stdout.strip())
    try:
        d = subprocess.run(["git", "-C", str(REPO_ROOT), "diff", "--name-only",
                            resolved[0], resolved[1]], capture_output=True, text=True, check=False)
    except (FileNotFoundError, OSError):
        return False
    if d.returncode != 0:
        return False
    # T-12014: decoded through the ONE decoder — under git's default `core.quotepath` an escaped
    # non-ASCII path matches neither `consult_rel` nor the derived-bookkeeping names below, so it read
    # as an authored path and this benign case was mis-refused.
    paths = [q for q in (textutil.git_unquote_path(p).strip()
                         for p in (d.stdout or "").splitlines()) if q]
    if not paths or consult_rel not in paths:
        return False   # an EMPTY delta, or one that never touches the consult record, is not this case
    for p in paths:
        if p == consult_rel or p in _CONSULT_BASIS_DERIVED_BOOKKEEPING_FILES:
            continue
        # An ARCHIVE SEGMENT IS THE SAME LOGICAL JOURNAL (T-11536 / SPEC-0190 rule 1) — derived
        # bookkeeping for exactly the reason the live `events.jsonl` above is. Asked through the
        # definer, never a re-spelled glob. FAIL-CLOSED IS UNTOUCHED: the loop below still returns
        # False on the first path that is not derived bookkeeping.
        if events_mod.is_archive_segment(Path(p), Path("events.jsonl")):
            continue
        if any(p.startswith(prefix) for prefix in _CONSULT_BASIS_DERIVED_BOOKKEEPING_DIRS):
            continue
        return False   # a real subject change rode along — STILL stale (the differential)
    return True


def _consult_post_subject(recorded_fp: str | None, head_fp: str | None,
                          head_supersedes_recorded: bool) -> tuple[str | None, str | None]:
    """T-11421 (<project> X-1088) — WHICH TREE a post-stage ceiling consult shows the auditor.

    THE WEDGE. An in-progress `audit consult --task T-XXXX --stage post` builds its diff from
    `_recorded_commit_sha(tid)` — the task's last `commit_landed`. A fix committed OUTSIDE
    `task commit` (raw git, `work commit`, a bookkeeping self-commit) emits no `commit_landed`, so the
    recorded sha stays BEHIND HEAD and every consult re-run shows the auditor the SUPERSEDED tree. The
    already-applied fix is invisible, the consult re-returns RED on a defect that no longer exists,
    and — because a non-converged consult is not an `--owner-reset` basis — the only exit is an owner
    ask. Re-running is exactly the CHARTER §Principle 7 «re-run against an unresolved contradiction»
    freeze, except here re-running can NEVER converge: the input is pinned to the past.

    THE FIX, and its bound. When HEAD is a strict DESCENDANT of the recorded commit — the recorded
    commit is genuinely superseded, on this same branch, by work that moved forward — the consult
    reads HEAD, the shape `--reaudit-after-close` already uses on both this verb and `cmd_audit`.

    WHAT DELIBERATELY DOES NOT MOVE: `basis_fingerprint`. It stays pinned to the RECORDED commit,
    because it is a PAIRING token, not a claim about the diff: `audit post --owner-reset` resolves
    `current_fp` to the commit IT audits (the recorded one) and `_consult_basis` demands an EXACT
    match. Re-pinning the fingerprint to HEAD would make every such consult read `stale` at that
    pairing and would trade this wedge for the T-10081 one. What actually unwedges the worker is the
    consult CONVERGING on the real tree: a fresh single-survivor GREEN/YELLOW consult then GOVERNS the
    `--owner-reset` pass (T-0522) without re-invoking an auditor at all.

    FAIL-CLOSED to today's behaviour on every other shape — a missing or unresolvable sha, HEAD equal
    to the recorded commit, a divergent or rewritten history (recorded not an ancestor of HEAD), or
    any git failure at the call site — all return the recorded sha and NO note. The relaxation opens
    only on positive evidence on every axis (`lessons/carving-an-exception-into-a-fail-closed-gate.md`).

    Returns `(subject_sha, note_or_None)`. The note is NOT decoration: the caller prints it to stderr
    AND prepends it to the diff, so the operator and the auditor both know which tree this verdict
    rests on (the sibling of T-11249's checkout-provenance line). A subject that moved silently would
    be the same defect one layer down.

    Pure function of its three arguments — no I/O, so the differential can test it directly."""
    if not recorded_fp or not head_fp or head_fp == recorded_fp or not head_supersedes_recorded:
        return recorded_fp, None
    return head_fp, (
        f"NOTE (T-11421): this consult reads the CURRENT TREE (HEAD {head_fp[:12]}), not the task's "
        f"recorded commit {recorded_fp[:12]} — HEAD is a strict descendant of it, so commits were made "
        f"outside `task commit` and the recorded commit is superseded. The diff below is the current "
        f"branch state; judge THAT. (`basis_fingerprint` stays pinned to the recorded commit — it is "
        f"the `audit post --owner-reset` pairing token, not the subject.)")


def _consult_basis(tid: str, stage: str, current_fp: str | None,
                   consult_cmd_hint: str | None = None, *, REPO_ROOT,
                   record: dict | None = None, CONSULT_OUTCOME_OWNER_HELD, CONSULT_OUTCOME_PROCEED, CONSULT_OUTCOME_TERMINAL, _consult_record_only_delta, _survivor_is_hold_for_owner, state) -> tuple[str, str | None, str]:
    """T-0429 — resolve the standing converged-consult basis for an `audit pre|post --owner-reset`.

    GENERIC over (id, key) (T-9286): a TASK passes (tid, stage∈{pre,post}); a PLAN passes
    (slug, gate∈PLAN_CONSULT_GATES) — both read decisions/<id>-audit-consult-<key>.yaml, so the gate-id
    match is STRUCTURAL (a wrong-gate consult is a DIFFERENT file → "none"). `consult_cmd_hint` overrides
    the re-pin command in the stale-fingerprint guidance (the plan form `audit consult --plan … --gate …`);
    None keeps the task form.

    SPEC-0124 §ceiling-convergence triage + §owner-reset: a FRESH consult verdict for this task+stage
    naming EXACTLY ONE survivor authorizes the single ceiling-continuation WITHOUT a fresh owner ask.

    Reads decisions/<tid>-audit-consult-<stage>.yaml. Returns (status, file, reason):
      - ("consult", relpath, "...")  -> a fresh single-survivor GREEN/YELLOW consult exists; the
        owner-reset is standing-authorized, record owner_reset_basis: consult:<relpath>.
      - ("owner-held", relpath, "...") -> T-10899 (<project> X-0718): a fresh consult that CONVERGED to
        exactly ONE survivor which IS the fixed HOLD-FOR-OWNER option. It converged, so it is a VALID
        basis — but a HOLD adjudicates NOTHING technically (it asks for the owner), so it resolves to
        the OWNER-AUTHORIZED basis, NOT the consult-GOVERNED carry: the `--owner-reset` flag IS the
        owner acting on the escalation this consult asked for, and the granted pass runs a REAL fresh
        auditor. Verdict-AGNOSTIC by design (a HOLD is typically recorded RED — "do NOT proceed" —
        which is exactly why the GREEN/YELLOW gate below used to misfile it as `multi`).
      - ("stale", None, "...")       -> a consult exists but its basis_fingerprint no longer matches
        the CURRENT plan_fingerprint (pre) / recorded commit SHA (post) — a plan/diff change
        invalidated it; REFUSE (escalate-to-owner).
      - ("multi", None, "...")       -> a consult exists but did NOT converge to exactly one survivor
        (0 / >1 survivors, or verdict ABORT) — REFUSE (escalate-to-owner).
      - ("none", None, "...")        -> no consult verdict for this task+stage — the consult basis is
        absent; the caller falls back to the flag's standing explicit-owner-authorized meaning.

    FRESHNESS (p2-F1, exact-match not mtime): the consult records the basis_fingerprint it was
    formed against (pre = plan_fingerprint; post = recorded commit SHA); a mismatch means the
    plan/diff changed since, so the consult is stale. `current_fp` is that current fingerprint."""
    path = REPO_ROOT / "decisions" / f"{tid}-audit-consult-{stage}.yaml"
    rel = str(path.relative_to(REPO_ROOT))
    # T-12234 — `record` is the ALREADY-LOADED canonical record, when the caller has one. It is the
    # request-scoped-read seam (SPEC-0190 rule 10): `cmd_audit`'s terminal-episode arm reads this
    # exact YAML for its `outcome` and then needs the basis derived FROM THE SAME BYTES, and a helper
    # that re-opened the path would make the two answers separately derived from one file — a second
    # read, and a window in which they could disagree. Passing it in is not an optimisation, it is
    # what makes «one read at the wiring site» true rather than claimed. Default None = read it here,
    # so every other caller is byte-unchanged.
    if record is None:
        if not path.exists():
            return "none", None, f"no consult verdict at {rel} — fall back to explicit owner-authorization"
        try:
            import yaml
            d = state.load_str(path.read_text(encoding="utf-8")) or {}
        except (yaml.YAMLError, OSError) as e:
            return "multi", None, f"consult verdict {rel} unreadable/malformed ({e}) — cannot form a basis"
    else:
        d = record
    if not isinstance(d, dict):
        return "multi", None, f"consult verdict {rel} did not parse as a mapping — cannot form a basis"
    # ── T-12249 — a TERMINAL episode is not a basis, whatever its verdict reads ────────────────────
    # THE GAP THIS CLOSES IS ONE SPEC-0124 ALREADY PRESUMED CLOSED. Its T-12234 EXCEPT clause reasons
    # that «once an episode is terminal, `_consult_basis` reads the record as `multi` … or as
    # `stale`», and builds the owner-authorized PROCEED on top of that reading. The premise was false
    # in one shape: a row-15 terminal is written by the OUTCOME layer over whatever verdict the round
    # returned, so a terminal episode can carry `verdict: GREEN` + exactly one survivor + a matching
    # basis_fingerprint and sail through every gate below as `consult` — consult-GOVERNED, no fresh
    # auditor, and the terminal seam above never reached because it keys on `stale`/`multi`. That is
    # not hypothetical: T-12237's `audit pre --owner-reset` of 2026-09-07T23:52Z was ADMITTED on
    # `owner_reset_basis: consult:decisions/T-12237-audit-consult-pre.yaml` — an episode that had
    # ended `terminal / open-ids-at-r2` one minute earlier, still carrying open id B1.
    #
    # THE CHECK IS THE COMPLEMENT OF THE ADMITTED SET, NOT A REASON LIST. SPEC-0124 §Basis resolution
    # admits exactly two converged shapes, and both are DISTINCT `outcome` VALUES: row-18 PROCEED is
    # `proceed`, row-16 owner-held is `owner-held`. So `outcome == terminal` names precisely what is
    # not admitted, and keys on nothing else — narrowing it to `terminal_reason: open-ids-at-r2`
    # would leave `malformed-exhausted` (the measured T-12220 shape) and `non-admissible-verdict`
    # resolving as a governing basis, which is the same defect wearing another reason.
    #
    # IT TAKES NOTHING AWAY FROM T-12234, it FEEDS it: for a TASK target at `--stage post` the
    # terminal arm admits exactly `cstatus in ("stale", "multi")`, so a GREEN-terminal record that
    # used to bypass that arm as `consult` now ROUTES INTO it and can take the owner-authorized
    # PROCEED with a stated `--reason` — a route it could never reach before. Upstream of
    # `_invoke_auditor`, so the refusal spends no pass.
    if d.get("outcome") == CONSULT_OUTCOME_TERMINAL:
        _treason = d.get("terminal_reason")
        return "multi", None, (
            f"consult {rel} is not a valid owner-reset basis: {_BASIS_TERMINAL_EPISODE_MARK} "
            f"(`outcome: {d.get('outcome')}`"
            + (f", `terminal_reason: {_treason}`" if _treason else "")
            + (f", open ids at the terminal: {', '.join(str(i) for i in d['open_ids'])}"
               if isinstance(d.get("open_ids"), list) and d.get("open_ids") else "")
            + f"). A verdict recorded on a terminal round is NOT a convergence: SPEC-0124 §Basis "
              f"resolution admits exactly two shapes — a fresh single-survivor TECHNICAL-PROCEED "
              f"(`outcome: {CONSULT_OUTCOME_PROCEED}`, row 18) and a converged HOLD-FOR-OWNER "
              f"(`outcome: {CONSULT_OUTCOME_OWNER_HELD}`, row 16) — and this record is neither, so "
              f"carrying its verdict would attest a convergence the episode never reached (T-12249; "
              f"measured on T-12237, whose GREEN-with-open-ids record cost four downstream HOLDs). "
              f"FORWARD PATH: (1) AMEND the subject and RE-CONSULT — but note a re-consult INSIDE a "
              f"terminal episode is refused `episode-ended`, so it needs the boundary too; "
              f"(2) `yitc-v2 audit consult --task {tid} --stage {stage} --reopen --reason '<the "
              f"owner grant locator>'` allocates episode n+1 with a fresh baseline (SPEC-0200 rule "
              f"7 — an OWNER act, refused in a dispatched-worker context); or (3) for a TASK target "
              f"at `--stage post`, `--owner-reset --reason '<grant>'` IS rule 7's owner-authorized "
              f"PROCEED on an ended episode (T-12234) — this refusal routes you there rather than "
              f"past it.")
    survivors = d.get("survivors")
    recommendation = d.get("recommendation")
    verdict = d.get("verdict")
    # T-10899 (<project> X-0718 + the kernel-side T-10873 wall) — CONVERGENCE and the survivor's KIND are
    # two different questions, and collapsing them made the mechanism fail SHUT precisely where it was
    # designed to open. A ceiling consult that names the fixed HOLD-FOR-OWNER option as its SOLE survivor
    # HAS converged — it converged on "the owner decides" — and it is recorded RED (`do NOT proceed`,
    # the real <project> record). The gate below reads GREEN/YELLOW-only, so that record was misfiled as
    # `_BASIS_NONCONVERGED_MARK` and `--owner-reset` refused it naming "escalate to the owner" as the
    # exit — while the owner IS the escalation target and HAD authorized. So: decide the convergence
    # SHAPE first (exactly one survivor + a recommendation), and let a converged HOLD through the
    # verdict gate as its OWN status. Everything else is byte-unchanged: 0 / >1 survivors, a missing
    # recommendation, an ABORT (which `_parse_consult_result` fail-closes to EMPTY survivors, so it can
    # never present as converged), and a non-HOLD RED all still return `multi` and still REFUSE.
    converged_shape = isinstance(survivors, list) and len(survivors) == 1 and bool(recommendation)
    hold_for_owner = converged_shape and _survivor_is_hold_for_owner(d)
    if not hold_for_owner and (verdict not in ("GREEN", "YELLOW") or not converged_shape):
        return "multi", None, (f"consult {rel} {_BASIS_NONCONVERGED_MARK} "
                               f"(verdict={verdict}, survivors={survivors}) — escalate to owner")
    # The status a FRESH read resolves to below. FRESHNESS is unchanged and applies IDENTICALLY to a
    # HOLD basis: a stale / fingerprint-less HOLD consult still falls through to `stale` and REFUSES.
    _fresh_status = "owner-held" if hold_for_owner else "consult"
    # FRESHNESS is FAIL-CLOSED (audit-post F2): the consult MUST carry a basis_fingerprint AND it
    # MUST equal the current one. A missing basis_fingerprint is NOT "fresh" — it is unusable (a
    # hand-edited / pre-fingerprint / malformed consult can never authorize an owner-reset). Likewise
    # if the caller cannot compute current_fp we cannot prove freshness, so we refuse rather than
    # silently accept. Only an exact match proves the plan/diff has not moved since the consult.
    basis_fp = d.get("basis_fingerprint")
    if not basis_fp:
        return "stale", None, (f"consult {rel} {_BASIS_NO_BASIS_FP_MARK} — cannot prove freshness "
                               "(fail-closed); escalate to owner")
    if not current_fp:
        return "stale", None, (f"cannot compute the current fingerprint to verify consult {rel} "
                               "freshness (fail-closed); escalate to owner")
    if basis_fp != current_fp and current_fp and d.get("adopted_fingerprint") \
            and d.get("adopted_fingerprint") == current_fp:
        # T-9617 (X-0111) — ADOPTED-plan governs. The converged single survivor's adoption IS a plan
        # edit: the session set implementation_plan to the recommended option's text, so the CURRENT
        # plan_fingerprint now equals the adopted_fingerprint this consult recorded at convergence
        # (= hash(survivor text)). basis_fingerprint (the PRE-change plan) no longer matches — that is
        # EXPECTED, not staleness — so this is the FIRST re-audit of the adopted plan and the consult
        # GOVERNS it (binding the carried verdict to the adopted/post-change plan, X-0111). The
        # exact-match still PROVES the session adopted the auditor-approved option VERBATIM; a paraphrase
        # would not match and falls through to the T-0448 stale re-consult path below (unchanged). This
        # fires ONCE per adopted plan: a further edit away from the survivor text matches neither
        # fingerprint → stale → re-consult, so it is not a spin loophole.
        return _fresh_status, rel, (f"fresh single-survivor consult {rel} governs the ADOPTED plan "
                                    f"(adopted_fingerprint matches current; recommendation={recommendation})")
    if basis_fp != current_fp and _consult_record_only_delta(basis_fp, current_fp, rel,
                                                             REPO_ROOT=REPO_ROOT):
        # T-11007 (<project> X-0848) — the consult record is NOT its own subject. The fingerprints
        # differ, but the ONLY tree change between the pinned basis and the current subject is this
        # consult's OWN verdict record (plus derived bookkeeping) — i.e. the consult was invalidated
        # by being FILED, not by the subject moving. That is bookkeeping, not staleness, so the basis
        # still GOVERNS. Same slot + shape as the T-9617 `adopted_fingerprint` carve-out above (the
        # other self-inflicted invalidation), and equally narrow: any OTHER path in the delta — the
        # absorb-then-consult cycle's absorbed source above all — fails the predicate and falls
        # through to the UNCHANGED `stale` refusal below.
        return _fresh_status, rel, (f"fresh single-survivor consult {rel} governs — the only tree "
                                    f"change between its pinned basis {str(basis_fp)[:12]}… and the "
                                    f"current subject {str(current_fp)[:12]}… is the consult's OWN "
                                    f"verdict record (committing it does not invalidate it, T-11007; "
                                    f"recommendation={recommendation})")
    if basis_fp != current_fp:
        # T-0448 — ACTIONABLE re-pinnable stale path (self-staleness repair). Reaching here means a
        # CONVERGED single-survivor consult EXISTS (the converged check above passed) but its basis no
        # longer matches the current plan/diff. This is the absorb-then-consult cycle: a re-run of
        # `audit consult` re-pins basis_fingerprint to the CURRENT plan/diff (cmd_audit_consult recomputes
        # it every run), so the converged basis is recoverable WITHOUT an owner ask. The canonical case is
        # the converged option whose OWN action is a plan edit — applying it re-fingerprints the plan and
        # self-invalidates the basis; a flat "escalate to owner" dead-ends that loop. Detection is
        # UNCHANGED (still a HARD refusal of THIS pass — the caller must re-consult first); only the
        # GUIDANCE changes. (The missing-basis_fingerprint / cannot-compute-current_fp sub-cases above are
        # NOT re-pinnable by a re-consult, so they keep the plain escalate message.)
        return "stale", None, (f"consult {rel} basis_fingerprint {str(basis_fp)[:12]}… no longer "
                               f"matches the current {str(current_fp)[:12]}… (plan/diff changed since "
                               f"the consult). This is the absorb-then-consult cycle: RE-RUN "
                               f"`{consult_cmd_hint or f'yitc-v2 audit consult --task {tid} --stage {stage} --option … --option …'}` "
                               f"against the current (absorbed) plan/diff to RE-PIN the converged basis, "
                               f"then retry --owner-reset. (No owner ask needed if it re-converges to the "
                               f"same single survivor.)")
    if _fresh_status == "owner-held":
        return "owner-held", rel, (
            f"fresh CONVERGED consult {rel} whose SOLE survivor is the fixed HOLD-FOR-OWNER option "
            f"(verdict={verdict}, recommendation={recommendation}) — a valid owner-reset basis: the "
            f"consult asked for the owner, and the flag IS the owner acting (T-10899, SPEC-0124 "
            f"§Basis resolution). NOT consult-governed — a fresh auditor runs on the granted pass.")
    return "consult", rel, f"fresh single-survivor consult {rel} (recommendation={recommendation})"


def _parse_consult_result(stdout: str, options: list, *, NOTES_KEY_LINE_RE, RECOMMENDATION_LINE_RE, SURVIVORS_LINE_RE, VERDICT_LINE_RE, state) -> tuple[str, list, str, str]:
    """T-0429 — STRICT parse of a ceiling-convergence consult result (SPEC-0124 triage).

    Returns (verdict, survivors, recommendation, parse_notes). FAIL-CLOSED (p2-F2 absorption):
    `survivors` MUST be a subset of the submitted option numbers; `recommendation` MUST be exactly
    ONE survivor. Any malformed / unknown / out-of-set / recommendation-not-a-survivor result
    DOWNGRADES the verdict to ABORT with empty survivors + no recommendation — so it can NEVER be
    recorded as a usable single-survivor `--owner-reset` basis. A GREEN/YELLOW verdict survives ONLY
    if it carries exactly-one well-formed survivor + a recommendation equal to it (the autonomy-grant
    condition); 0 or >1 survivors keep the verdict but leave NO usable single-survivor basis (the
    escalate-to-owner path). The auditor's verdict line is taken via the shared VERDICT_LINE_RE.

    `options` is the submitted option list (1-based numbering matches the prompt). Survivors and the
    recommendation are normalized to 1-based ints in range [1, len(options)]."""
    n = len(options)
    survivors: list = []
    recommendation = ""
    notes = ""

    def _as_int(v):
        """The ONE coercion point for an option INDEX — for survivors entries and the recommendation
        alike. T-11006 (X-0835) widens WHICH RENDERING of an index is recognised; it does NOT widen
        WHICH INDICES are admissible. Every caller still range-checks, subset-checks and
        exactly-one-checks the returned int exactly as before, so a rendering that resolves to no
        index still fails closed and a genuinely non-converged verdict is still refused.

        THE DEFECT. A consult that HAD adjudicated was recorded as the auditor-unavailable/malformed
        ABORT class with zero survivors — the escalation reached the owner on a PARSE mismatch rather
        than on substance, and the verdict was human-legible but machine-invisible (<project>
        2026-08-12, fingerprint audit-consult-survivors-by-index-parsed-as-zero-survivors-abort). The
        auditor had named its options BY 1-BASED INDEX, in renderings a bare `int()` rejects:

          (a) a MAPPING carrying an `option:` key — `survivors:\\n  - option: 2` /
              `- option: 2\\n    text: ...`. This one stings: `{option, text}` is THIS MODULE'S OWN
              canonical survivor shape (`survivor_records`, written into every saved consult YAML and
              shown back to the auditor in the prior record), so the reader was rejecting precisely
              the form its own writer emits. `int({'option': 2})` raises TypeError -> None -> the
              range check reports "out of the submitted option set" -> ABORT, zero survivors.
          (b) a STRING index — `["2"]`, or `recommendation: "2"` whose captured line value carries
              the quotes verbatim. `int('"2"')` raises ValueError -> None.

        Narrow by construction: a mapping WITHOUT an `option:` key, a list, a bool, None, or any text
        that is not a plain integer all still return None. Nothing here invents an index the auditor
        did not name."""
        if isinstance(v, dict):
            # ONLY the `option:` key — the index carrier of the saved survivor record. A mapping that
            # names no option names no index (a `{text: ...}` fragment must NOT resolve to something).
            if "option" not in v:
                return None
            v = v.get("option")
        if isinstance(v, bool):
            return None      # bool is an int subclass; `survivors: [true]` names no option
        if isinstance(v, str):
            v = v.strip().strip("\"'").strip()
        try:
            return int(v)
        except (TypeError, ValueError):
            return None

    # T-0447 — PER-FIELD extraction, NOT a whole-block yaml.safe_load of the verdict-onward tail.
    # The old design fed the ENTIRE tail (which includes the free-form, unquoted multi-line `notes:`
    # scalar) to one yaml.safe_load; an auditor `notes:` value containing a bare `colon-space` (e.g.
    # "`done_definition` is present") makes safe_load raise "mapping values are not allowed here" ->
    # parsed=None -> a well-formed `verdict: GREEN / survivors: [1] / recommendation: 1` was discarded
    # as a fail-closed ABORT (the T-0437 / T-0037 codex-stdout-parse fragility incident). The fix —
    # ORDER MATTERS (audit-post p1-F1): bound the notes region FIRST, anchor SECOND, so a standalone
    # `verdict:`/`survivors:`/`recommendation:` line INSIDE the free-form notes body can never hijack
    # the parse:
    #   (1) FENCE-NORMALIZE: auditors commonly wrap the result block in a markdown code-fence. Take the
    #       lines from after an OPENING fence up to (not incl.) the next CLOSING fence if a fence block
    #       exists; otherwise the whole stdout. This skips an opening ```yaml preamble fence AND drops a
    #       trailing ``` (invalid YAML), mirroring _parse_audit_verdict's fence tolerance.
    #   (2) BOUND a STRUCTURED slice = the fence-normalized lines BEFORE the first `notes:` key line.
    #       Everything from `notes:` onward is the free-form notes body and is EXCLUDED from every
    #       structured field — so a standalone `verdict:`/`survivors:`/`recommendation:` line INSIDE
    #       notes can never hijack the parse (audit-pre p1-F1 + pass-2 F0 + audit-post p1/p2-F1).
    #   (3) extract verdict / survivors / recommendation PER-FIELD from that bounded pre-notes slice ONLY.
    #       The verdict keeps LAST-match semantics WITHIN the pre-notes slice (a result block may restate
    #       it; the prior `findall(...)[-1]` behavior is preserved, just scoped to the bounded slice).
    # Every fail-closed downgrade below is PRESERVED verbatim — only the parse SOURCE changed.
    all_lines = stdout.splitlines()
    fence_idxs = [i for i, ln in enumerate(all_lines) if ln.lstrip().startswith("```")]
    if len(fence_idxs) >= 2:
        block = all_lines[fence_idxs[0] + 1:fence_idxs[1]]   # between the first opening + next closing
    elif len(fence_idxs) == 1:
        block = all_lines[:fence_idxs[0]]                    # a lone (closing) fence truncates the tail
    else:
        block = all_lines                                    # no fence at all
    # (2) notes boundary: the FIRST `notes:` key line bounds the structured slice. structured = pre-notes
    # lines; the free-form notes value (captured loosely for the rationale) = the notes line onward.
    notes_idx = None
    for i, ln in enumerate(block):
        if NOTES_KEY_LINE_RE.match(ln):
            notes_idx = i
            break
    structured_lines = block if notes_idx is None else block[:notes_idx]
    structured = "\n".join(structured_lines)
    if notes_idx is not None:
        notes = "\n".join(block[notes_idx:])

    # (2a) T-11019 — the ORDERING-TOLERANT supplement. The T-0447 bound above assumes the auditor emits
    # the structured fields BEFORE `notes:`. An auditor that emits `notes:` FIRST puts survivors: and
    # recommendation: PAST the bound, so survivors read as the EMPTY SET and a real adjudication reports
    # NOT converged — SILENTLY (the verdict line still parses, so the saved record looks well-formed and
    # the escalation reaches the owner on a PARSE mismatch rather than on substance; measured against
    # this reader 2026-08-16, the positional sibling of T-11006's by-INDEX class).
    #
    # The T-0447 bound is NOT relaxed — it is SUPPLEMENTED under two conjunctive guards, so BOTH readings
    # hold at once:
    #   (i) the pre-notes slice carries NO `survivors:` line AT ALL. The hijack case T-0447 exists for has
    #       a real `survivors:` above `notes:` (that is what a forged notes-internal line would be
    #       overriding), so this guard makes the supplement unreachable there BY CONSTRUCTION — the
    #       structured block is complete, and a complete block is still the ONLY source. Only an
    #       INCOMPLETE structured block — which today yields the empty set — can reach the post-notes
    #       region at all, so nothing that parses today changes.
    #   (ii) the supplement is ADMITTED only by a COLUMN-0 (unindented, top-level) `survivors:` key line
    #       in the post-notes region, and starts AT that line. A free-form notes VALUE is indented (a
    #       `notes: |` block scalar, a wrapped continuation), so the notes body can never open the
    #       supplement; a column-0 `survivors:` after the notes block is a top-level YAML key, i.e. the
    #       auditor's own structured field. Admission is column-0; the region then runs to the end so a
    #       multi-line VALUE stays intact (`survivors:\n  - option: 2` — this module's own saved survivor
    #       shape, T-11006 — would be destroyed by filtering the indented continuation lines out).
    # Every downstream fail-closed check is UNCHANGED and still applies to whatever this locates (explicit
    # list shape, `_as_int`, range, subset, duplicate, exactly-one-recommendation) — the supplement widens
    # WHERE a field may be found, never WHICH values are admissible.
    supplement = ""
    if notes_idx is not None and not SURVIVORS_LINE_RE.search(structured):
        post = block[notes_idx + 1:]
        for j, ln in enumerate(post):
            if ln and not ln[:1].isspace() and SURVIVORS_LINE_RE.match(ln):
                supplement = "\n".join(post[j:])
                break
    # The region survivors/recommendation are read from: the pre-notes slice, or — only under the guards
    # above — the post-notes supplement. `recovered` drives the parse_notes marker below: the T-11019
    # failure was SILENT, so a supplement-sourced parse must be VISIBLE in the saved record.
    surv_region = supplement or structured
    recovered = bool(supplement)

    # (3.0) verdict — the LAST canonical `verdict:` line WITHIN the pre-notes structured slice (preserves
    # the prior last-match semantics, now scoped to the slice). A standalone `verdict:` inside notes is
    # past the bound and unreachable. No structured verdict line -> ABORT (prior no-verdict downgrade).
    vmatches = VERDICT_LINE_RE.findall(structured)
    if not vmatches:
        return "ABORT", [], "", "no canonical verdict line found in the structured consult region (fail-closed)"
    verdict = vmatches[-1]

    # (2) survivors — per-field: grab the `survivors:` line's VALUE from the structured slice and
    # yaml.safe_load JUST that small self-contained scalar (`[1]` / `1` / `[1, 2]`). A MISSING line =
    # the empty set (no-survivor escalate path, == the prior `parsed.get("survivors") is None` branch).
    # ANCHOR COHERENCE (T-9252): take the LAST `survivors:` match within the pre-notes slice, mirroring
    # the verdict's `vmatches[-1]` last-match. The three structured fields MUST anchor to the SAME (final)
    # restatement — an auditor that restates the block before `notes:` (a preamble verdict/survivors/rec
    # then a final restatement) otherwise desyncs verdict (last) from survivors/rec (first), producing an
    # incoherent triple that "oscillates" across audit-post passes whose stdout differs only in restatement
    # (fingerprint consult-parser-audit-post-anchor-oscillation, deviation 2026-06-06 @ T-0447). A single
    # block (the common case) has first==last, so this is byte-identical there.
    # T-11019: `surv_region` is the pre-notes slice in every case that parses today; it is the column-0
    # post-notes supplement ONLY under the two guards above (no pre-notes survivors line + column-0).
    surv_matches = list(SURVIVORS_LINE_RE.finditer(surv_region))
    surv_m = surv_matches[-1] if surv_matches else None
    if surv_m is not None:
        try:
            import yaml
            raw_surv = state.load_str(surv_m.group(1).strip())  # T-9207: single state layer; raises YAMLError as before
        except yaml.YAMLError:
            return "ABORT", [], "", "consult `survivors` value did not parse as YAML (fail-closed, p2-F2)"
    else:
        raw_surv = None
    # FAIL-CLOSED on shape (audit-post p2-F2): `survivors` MUST be an explicit YAML list. A missing
    # key is the empty set (the no-survivor escalate path); ANY non-list scalar (e.g. `survivors: 1`)
    # is MALFORMED -> ABORT, never coerced into a one-element list (coercion could fabricate a
    # single-survivor convergence the auditor did not actually express).
    if raw_surv is None:
        raw_surv = []
    elif not isinstance(raw_surv, list):
        return "ABORT", [], "", (f"consult `survivors` is {type(raw_surv).__name__}, not a YAML list "
                                 "(fail-closed, p2-F2) — refusing to coerce a scalar into a basis")
    seen = set()
    for v in raw_surv:
        iv = _as_int(v)
        if iv is None or not (1 <= iv <= n) or iv in seen:
            return "ABORT", [], "", (f"consult survivor {v!r} is out of the submitted option set "
                                     f"[1..{n}] or duplicate (fail-closed, p2-F2)")
        seen.add(iv)
        survivors.append(iv)
    # (3) recommendation — per-field from the structured slice; _as_int validates membership; the
    # RETURNED type is a STRING `str(rec_iv)` (audit-pre p1 F2 canonical contract — unchanged from the
    # prior `recommendation = str(rec_iv)`). The "must be exactly one survivor" check is UNCHANGED.
    # ANCHOR COHERENCE (T-9252): LAST `recommendation:` match in the pre-notes slice, same as verdict +
    # survivors above — all three anchor to the final restatement.
    # T-11019 ANCHOR COHERENCE across the supplement: when the survivors came from the post-notes
    # supplement, the recommendation anchors to the SAME region if it names one there (the auditor moved
    # the whole structured block past `notes:`); it falls back to the pre-notes slice only when the
    # supplement carries no recommendation line — so verdict/survivors/recommendation never straddle two
    # restatements. Identical to the prior behaviour whenever the supplement is unused.
    rec_matches = list(RECOMMENDATION_LINE_RE.finditer(surv_region))
    if not rec_matches and recovered:
        rec_matches = list(RECOMMENDATION_LINE_RE.finditer(structured))
    rec_m = rec_matches[-1] if rec_matches else None
    rec_iv = _as_int(rec_m.group(1).strip()) if rec_m is not None else None
    if rec_iv is not None:
        if rec_iv not in survivors:
            return "ABORT", [], "", (f"consult recommendation {rec_iv!r} is not exactly one of the "
                                     f"survivors {survivors} (fail-closed, p2-F2)")
        recommendation = str(rec_iv)
    # A GREEN/YELLOW single-survivor convergence MUST carry the recommendation (the autonomy grant).
    if verdict in ("GREEN", "YELLOW") and len(survivors) == 1 and not recommendation:
        return "ABORT", [], "", ("single-survivor consult is missing its recommendation — cannot "
                                 "form a usable basis (fail-closed, p2-F2)")
    parse_notes = f"consult parsed strict: {len(survivors)} survivor(s), recommendation={recommendation or '(none)'}"
    if recovered:
        # T-11019 — make the recovery VISIBLE. The defect this branch fixes was silent; a saved record
        # whose fields were located past the notes block must say so, so a reader can tell an
        # ordering-tolerant parse from an ordinary one without re-deriving it from the raw stdout.
        parse_notes += (" [structured fields recovered from the column-0 post-notes region (T-11019) — "
                        "the pre-notes slice carried no survivors: line]")
    if notes.strip():
        parse_notes += f"\n\n--- consult rationale ---\n{notes.strip()}"
    return verdict, survivors, recommendation, parse_notes


def _consult_embedded_open_id(ref, open_ids) -> "str | None":
    """T-12249 — the ONE open id a non-bare `baseline_ref` EMBEDS, or None. Pure f(text, ids).

    THE MEASURED SHAPE, twice in one day. `consult_baseline_table` renders the retest scope table as
    `- [B1] disposition: blocking | resolution: open | AC2 | <locator>`, and the retest prompt asks
    for the id «verbatim from the table above» — so an auditor that reads that literally copies the
    WHOLE ROW into `baseline_ref`. It happened on T-12237's consult-pre (2026-09-07T23:51Z) and again
    on T-12208's consult-post (2026-09-08T04:30Z): both auditors CLOSED their ids WITH evidence, and
    both closures were discarded — the ref matched no open id, so row 21 recorded `invalid-ref`, the
    id itself went `unaccounted` (row 8), and the open set never shrank. The T-12237 record then read
    `verdict: GREEN` while carrying `open_ids: [B1]`, which is the attestation four later HOLDs were
    spent disbelieving.

    An id-embedding ref DOES name its id — it names it inside a row rather than alone — so reading it
    is a transcription question, not a matrix question. Row 21's own definition (SPEC-0200 rule 4) is
    a ref that names NO open blocking id: «an unknown id (`B999`), an already-closed id, or a
    `deferrable` entry». A ref carrying `[B1]` while B1 is open is none of those three, so crediting
    it adds NO row and re-defines none — the extraction runs BEFORE row 21, in the same slot row 22's
    scope-cut withdrawal occupies before the echo precedence.

    FAIL-CLOSED ON AMBIGUITY, which is the whole reason this returns an id rather than a list: the
    intersection must be EXACTLY ONE. A ref embedding two open ids (`B1 and B2 are both fixed`) names
    no single id to credit the closure to, and guessing would close an id the auditor may have meant
    to leave open — so it stays row 21, exactly as today. Zero matches likewise. Only `open_ids` is
    intersected, so an embedded id that is already CLOSED, withdrawn or unknown contributes nothing
    and cannot rescue a ref that names no OPEN id."""
    text = ref if isinstance(ref, str) else ""
    if not text:
        return None
    open_set = {i for i in (open_ids or ()) if isinstance(i, str)}
    found = {tok for tok in _CONSULT_EMBEDDED_ID_RE.findall(text)} & open_set
    return next(iter(found)) if len(found) == 1 else None


def _consult_str(value):
    """A present, non-empty STRING field, else None. Absence and blankness read alike — a field
    spelled `locator: ""` substantiates nothing (rule 3 is a substantiation test, not a key test)."""
    return value.strip() if isinstance(value, str) and value.strip() else None


def consult_finding_disposition(finding: dict, lens, *, CONSULT_BLOCKING_CLASS_IDS, _consult_str) -> tuple:
    """Rule 3 — the disposition of ONE finding, and the violation (if any) that demoted it.

    `blocking` ONLY when the finding says so AND carries every substantiation field AND its
    membership VALIDATES: `criterion_ref` must name a criterion of the CURRENT target's lens (a task
    AC id the card carries; a plan-gate `<gate>:<criterion>`), or `class_id` must be one of the six
    CLOSED classes. Everything else is `deferrable`, visibly — an unproven block never blocks, and
    never silently. `severity` is NEVER read: it is optional triage metadata and derives nothing.

    Returns `(disposition, violation_reason_or_None)`. Pure f(finding, lens)."""
    lens = set(lens or ())
    raw = _consult_str(finding.get("disposition"))
    stated = raw.lower() if raw else None
    if stated == "deferrable":
        return "deferrable", None                       # row 19 — explicitly deferrable
    if stated != "blocking":
        # absent, blank, or a value outside the two-member vocabulary — it cannot block (row 2).
        return "deferrable", CONSULT_VIOLATION_MISSING_DISPOSITION
    causality = _consult_str(finding.get("causality"))
    missing = [f for f in CONSULT_BLOCKING_AUDITOR_FIELDS if not _consult_str(finding.get(f))]
    if causality is not None and causality not in CONSULT_CAUSALITY_VALUES:
        missing.append("causality")                     # a causality outside the vocabulary is not one
    criterion = _consult_str(finding.get("criterion_ref"))
    class_id = _consult_str(finding.get("class_id"))
    if missing or (criterion is None and class_id is None):
        return "deferrable", CONSULT_VIOLATION_UNSUBSTANTIATED
    if criterion is not None and criterion not in lens:
        return "deferrable", CONSULT_VIOLATION_INVALID_CRITERION
    if criterion is None and class_id not in CONSULT_BLOCKING_CLASS_IDS:
        return "deferrable", CONSULT_VIOLATION_INVALID_CLASS
    return "blocking", None


def _consult_baseline_entry(finding: dict, fid: str, disposition: str, revision, *, _consult_str) -> dict:
    """One frozen survey entry (rule 2's shape). `id` + `subject_revision` are ENGINE-supplied; the
    rest is the auditor's own text, transcribed, never invented — an absent optional field stays
    absent rather than becoming a None-valued key."""
    entry = {"id": fid, "disposition": disposition, "resolution": "open",
             "subject_revision": revision}
    for key in ("criterion_ref", "class_id", "locator", "failing_input", "causality"):
        val = _consult_str(finding.get(key))
        if val is not None:
            entry[key] = val
    return entry


def consult_freeze_baseline(prior_baseline, findings, *, revision, established_at,
                            findings_complete, lens, _consult_baseline_entry, consult_finding_disposition) -> tuple:
    """Rule 2 — the round-0 freeze: ids allocated ONCE (`B1`..`B<n>`, in response order, never
    re-derived from text), each entry's disposition validated by rule 3, `resolution: open`.

    IMMUTABLE: a prior baseline is returned UNCHANGED and no violation is re-recorded — a second
    adjudication on the same revision does not rewrite the block. An EMPTY complete survey freezes
    an EMPTY baseline (a valid baseline: the retest set is empty).

    Returns `(baseline_block, violations)`. Pure."""
    if prior_baseline:
        return prior_baseline, []
    entries, violations = [], []
    for n, finding in enumerate(findings or (), start=1):
        fid = f"B{n}"
        disposition, violation = consult_finding_disposition(finding, lens)
        entries.append(_consult_baseline_entry(finding, fid, disposition, revision))
        if violation:
            violations.append({"id": fid, "field": "disposition", "reason": violation})
    baseline = {
        "revision": revision,
        "established_at": established_at,
        "findings": entries,
        "findings_complete": findings_complete,
    }
    if findings_complete is not True:
        # Rule 2: RECORDED, never a gate — the round's own HOLD/PROCEED follows rule 6 on the ids
        # returned, and later escapes are what rule 8 counts.
        violations.append({"id": None, "field": "findings_complete",
                           "reason": CONSULT_VIOLATION_INCOMPLETE_SURVEY})
    return baseline, violations


def consult_legacy_baseline(record: dict, *, _consult_baseline_entry):
    """Rule 2 — migrate a PRE-contract consult record, ONLY on the explicit provenance marker
    `baseline_schema: 1`. Absence means «not a baseline record», NEVER a guessed baseline, so a
    legacy record without the marker returns None and is never read as one. A migrated finding
    freezes `disposition: blocking, disposition_source: legacy-default` (row 3 by fiat, marked)."""
    if not isinstance(record, dict) or record.get("baseline_schema") != CONSULT_BASELINE_SCHEMA:
        return None
    entries = []
    for n, finding in enumerate(record.get("findings") or (), start=1):
        entry = _consult_baseline_entry(finding if isinstance(finding, dict) else {},
                                        f"B{n}", "blocking", record.get("basis_fingerprint"))
        entry["disposition_source"] = "legacy-default"
        entries.append(entry)
    return {
        "revision": record.get("basis_fingerprint"),
        "established_at": record.get("date"),
        "findings": entries,
        "findings_complete": record.get("findings_complete"),
    }


def _consult_survivor_texts(survivors, *, _consult_str) -> list:
    """The survivor TEXTS of a parsed response, in the record's own `{option, text}` shape."""
    out = []
    for surv in survivors or ():
        if isinstance(surv, dict):
            text = _consult_str(surv.get("text"))
            if text is not None:
                out.append(text)
        elif isinstance(surv, str):
            text = _consult_str(surv)
            if text is not None:
                out.append(text)
    return out


def consult_admission(verdict, survivors, offered_options, *, AUTO_CONSULT_PROCEED_OPTION, CONSULT_NON_ADMISSIBLE_MULTIPLE_SURVIVORS, CONSULT_NON_ADMISSIBLE_RED_PROCEED, CONSULT_NON_ADMISSIBLE_SURVIVOR_NOT_OFFERED, CONSULT_NON_ADMISSIBLE_ZERO_SURVIVORS, _consult_survivor_texts) -> tuple:
    """Rule 4's PRE-MATRIX admission — verdict + survivor cardinality, fail-closed. WELL-FORMED
    responses only (an ABORT is row 0 first, so its one re-run per episode stays reachable and a
    `verdict: ABORT` with zero survivors is malformed, never «non-admissible»).

    TWO shapes are admissible: GREEN/YELLOW with EXACTLY ONE survivor, or RED with exactly one
    survivor that IS the persisted HOLD option. The survivor is identified by EXACT EQUALITY against
    the PERSISTED offered pair, so a survivor whose text is neither persisted option is
    `survivor-not-offered` — the matrix reads an IDENTITY, never a free text.

    Returns `(non_admissible_or_None, survivor_is_proceed_or_None)`. Pure."""
    texts = _consult_survivor_texts(survivors)
    if not texts:
        return CONSULT_NON_ADMISSIBLE_ZERO_SURVIVORS, None
    if len(texts) > 1:
        return CONSULT_NON_ADMISSIBLE_MULTIPLE_SURVIVORS, None
    offered = [t.strip() for t in (offered_options or ()) if isinstance(t, str)]
    text = texts[0]
    if text not in offered:
        return CONSULT_NON_ADMISSIBLE_SURVIVOR_NOT_OFFERED, None
    is_proceed = text == AUTO_CONSULT_PROCEED_OPTION.strip()
    if str(verdict).upper() == "RED" and is_proceed:
        return CONSULT_NON_ADMISSIBLE_RED_PROCEED, None
    return None, is_proceed


def consult_response_is_malformed(verdict, findings, round_kind, *, CONSULT_ROUND_KIND_BASELINE, _consult_str) -> bool:
    """Rule 2 / row 0 — is this response MALFORMED? An ABORT at ANY round (auditor unavailable or
    output malformed), and at round 0 a NON-EMPTY survey in which EVERY finding lacks `disposition`
    (the response contract was not delivered at all, as opposed to a per-finding lapse — that stays
    rows 1-2). An EMPTY survey is NOT malformed: an empty baseline is a valid baseline."""
    if str(verdict).upper() == "ABORT":
        return True
    if round_kind != CONSULT_ROUND_KIND_BASELINE:
        return False
    findings = [f for f in (findings or ()) if isinstance(f, dict)]
    return bool(findings) and all(
        _consult_str(f.get("disposition")) is None for f in findings)


def _consult_prior_state(prior: dict) -> dict:
    """The PRE-CALL state read off the prior record — the state that FIXES `round_kind` (rule 4) and
    supplies the open set. A prior of None (or a record with no frozen baseline) is round 0."""
    prior = prior if isinstance(prior, dict) else {}
    baseline = prior.get("baseline") if isinstance(prior.get("baseline"), dict) else None
    residuals = [r for r in (prior.get("residuals") or ()) if isinstance(r, dict)]
    resolutions = [r for r in (prior.get("resolutions") or ()) if isinstance(r, dict)]
    # A withdrawn id (row 22) is out of the open set as durably as a closed one — the difference is
    # the RECORDED reason, not the reachability: re-opening it would re-strand the card on the next
    # round (T-12244).
    closed = {r.get("id") for r in resolutions
              if r.get("resolution") in CONSULT_RESOLVED_VALUES}
    entries = {}
    for entry in ((baseline or {}).get("findings") or ()):
        if isinstance(entry, dict) and entry.get("id"):
            entries[entry["id"]] = entry
    for entry in residuals:
        if entry.get("id"):
            entries[entry["id"]] = entry
    open_ids = [fid for fid, e in entries.items()
                if e.get("disposition") == "blocking" and fid not in closed]
    return {
        "baseline": baseline,
        "entries": entries,
        "residuals": residuals,
        "resolutions": resolutions,
        "closed": closed,
        "open_ids": open_ids,
        "r_before": int(prior.get("r_after") or 0),
        "malformed_count": int(prior.get("malformed_count") or 0),
        "no_answer_count": int(prior.get("no_answer_count") or 0),
        "completeness_failures": int(prior.get("completeness_failures") or 0),
        "deferrals": [d for d in (prior.get("deferrals") or ()) if isinstance(d, dict)],
        "violations": [],
    }


def consult_round_kind(prior: dict, *, CONSULT_ROUND_KIND_BASELINE, CONSULT_ROUND_KIND_RETEST, _consult_prior_state) -> str:
    """Rule 4 — `round_kind` is fixed by the state BEFORE the call, NEVER by its outcome. No frozen
    baseline yet => `baseline` (including the re-run after a malformed round 0); otherwise the call
    judges a non-empty open set => `retest`. There is no `clearance` kind: a call over an empty open
    set is never made, because PROCEED already terminated the episode."""
    return (CONSULT_ROUND_KIND_BASELINE if not _consult_prior_state(prior)["baseline"]
            else CONSULT_ROUND_KIND_RETEST)


def consult_packet_assemble(base_prompt, overlay, *, round_kind, bound, baseline_revision,
                            rebuild_delta=None, CONSULT_PACKET_SCOPE_DELTA, CONSULT_PACKET_SCOPE_FULL, CONSULT_ROUND_KIND_RETEST) -> tuple:
    """T-12233 — assemble the consult packet under the SOFT, RECORDED byte bound. PURE given
    `rebuild_delta`; returns `(prompt, packet_bytes, packet_scope, packet_over_bound)`.

    THE BOUND NEVER TRUNCATES AND NEVER REFUSES. That is what keeps it a SPEC-0193 PERFORMANCE key
    rather than a gate: a key that could cut the auditor's input, or block a round, would change what
    the audit CONCLUDES. All it does is choose between TWO SCOPES THAT ADMIT THE SAME JUDGEMENT:

      * `full` — the whole subject diff. Always the round-0 scope, and the scope of any round under
        the bound.
      * `delta-since-baseline` — the diff since the baseline revision. Reachable ONLY at a RETEST,
        where it is equivalent to the full diff by SPEC-0200 rule 4's own terms: a retest judges ONLY
        each open blocking id and any regression the fix INTRODUCED, and rule 4 forbids a
        whole-subject survey there. So the delta IS the rule-4 correct scope and the full diff is the
        over-inclusive one — narrowing to it removes nothing the round is entitled to judge.

    ROUND 0 IS NEVER DELTA-SCOPED (rule 2 requires it to survey the whole subject), delivered by the
    `round_kind` guard rather than by a caller remembering to skip it.

    STILL OVER THE BOUND after that — an oversized DELTA, or a rule-4 overlay that ALONE exceeds it —
    and the packet is returned WHOLE and UNTRUNCATED with `packet_over_bound` True. The two corners
    are ONE case, by the ruled invariant (owner_directive events.jsonl#ts=2026-09-07T23:44:44Z): an
    honest, VISIBLE, measured over-bound send beats a silently narrowed one, and cutting the diff is
    exactly the verdict-changing input the key's class forbids.

    `rebuild_delta` is a callable taking the baseline revision and returning a re-assembled BASE
    prompt, or None when the delta cannot be taken (no resolvable revision, no commit subject, an
    unreadable history). None means «keep the full packet», never «cut it»: a scope that cannot be
    computed simply does not apply. A candidate that is not actually SMALLER is discarded — narrowing
    that does not narrow is pure risk.

    Every branch returns the MEASURED size, so the outcome is checkable from the recorded row alone
    rather than re-derived by a reader.
    """
    prompt = base_prompt + overlay
    packet_bytes = len(prompt.encode("utf-8"))
    scope = CONSULT_PACKET_SCOPE_FULL
    if (packet_bytes > bound and round_kind == CONSULT_ROUND_KIND_RETEST
            and rebuild_delta is not None and baseline_revision):
        delta_base = rebuild_delta(baseline_revision)
        if delta_base is not None:
            candidate = delta_base + overlay
            candidate_bytes = len(candidate.encode("utf-8"))
            if candidate_bytes < packet_bytes:
                prompt, packet_bytes = candidate, candidate_bytes
                scope = CONSULT_PACKET_SCOPE_DELTA
    return prompt, packet_bytes, scope, packet_bytes > bound


def _consult_classify_retest(findings, state, *, revision, round_k, lens, scope_cuts=None,
                             owner_rulings=None, _consult_baseline_entry, _consult_embedded_open_id, _consult_str, consult_finding_disposition) -> dict:
    """The retest per-finding layer (rows 4-11, 19-21) in the rule-4 ECHO precedence.

    Two DISJOINT sub-layers, exactly as rule 4's row-composition paragraph specifies: every finding
    hits at most one ECHO row (for the id it references) and at most one NON-ECHO row (for its own
    content) — so a row-21 bad-ref echo that ALSO carries a complete blocking set hits row 21 AND
    row 9/10 and allocates a residual (fail-closed: a bad ref never hides a must-not-land defect)."""
    violations, resolutions, residuals = [], [], []
    escapes, deferrals = 0, []
    open_before = list(state["open_ids"])

    # ── rows 22 + 23, FIRST — the WITHDRAWALS, decided before any echo is read ─────────────────
    # ONE pass over two admission tests, because they are one row in every respect that matters
    # downstream — both take the id out of `open_before` up front, both ride `resolutions[]` under
    # their own `resolution` value carrying the directive locator + the receiving id, and neither
    # ever reads as resolved-by-code. Taking them out UP FRONT is what makes them precede the echo
    # precedence: an echo re-judging a withdrawn id `open` cannot hold it (the T-12235 strand), and
    # its ABSENCE from the response is not `unaccounted` (row 8) either.
    #
    # What differs is only WHAT the owner ruled, and therefore what the marker is keyed on:
    #   * row 22 (T-12244) — the id's CRITERION was CUT out of this card and handed to another. Read
    #     off the criterion's own text; keyed on `criterion_ref`.
    #   * row 23 (T-12248) — the id's SUBJECT was ruled OUT OF THIS CARD altogether (a governed
    #     RECORD artefact, an engine defect, a foreign card's fix): no criterion moved, so there is
    #     no criterion to key on and no code change on THIS card can move the id. Read off the
    #     card's `amend_notes`; keyed on the FINDING ID itself.
    # Row 22 is evaluated first, so a card that both cut a criterion AND ruled its finding
    # out-of-subject records the CUT — the narrower, criterion-anchored fact — and records it once.
    cuts = scope_cuts if isinstance(scope_cuts, dict) else {}
    rulings = owner_rulings if isinstance(owner_rulings, dict) else {}
    withdrawn = set()
    if cuts or rulings:
        for fid in list(open_before):
            criterion = _consult_str((state["entries"].get(fid) or {}).get("criterion_ref"))
            cut = cuts.get(criterion) if criterion else None
            if cut:
                record = dict(cut, resolution=CONSULT_RESOLUTION_WITHDRAWN_SCOPE_CUT,
                              criterion_ref=criterion)
            else:
                ruling = rulings.get(fid)
                if not ruling:
                    continue
                # The ruling names the id, not a criterion — so `criterion_ref` carries whatever the
                # ENTRY had (often none: an out-of-subject finding is typically substantiated by
                # `class_id`), never a value invented to fill the field.
                record = dict(ruling, resolution=CONSULT_RESOLUTION_WITHDRAWN_OWNER_RULING,
                              criterion_ref=criterion)
            withdrawn.add(fid)
            resolutions.append({
                "id": fid,
                "resolution": record["resolution"],
                "criterion_ref": record["criterion_ref"],
                "owner_directive": record.get("owner_directive"),
                "receiving_task": record.get("receiving_task"),
                "closed_at_round": round_k,
            })
        open_before = [fid for fid in open_before if fid not in withdrawn]

    echoes = {}
    non_echo, bad_ref = [], []
    for finding in findings or ():
        if not isinstance(finding, dict):
            continue
        ref = _consult_str(finding.get("baseline_ref"))
        if ref is None:
            non_echo.append((finding, False))              # rule 4: a finding without a ref is NEW
        elif ref in withdrawn:
            continue                                      # rows 22/23 — the id is gone; echo moot
        elif ref in open_before:
            echoes.setdefault(ref, []).append(finding)
        elif (embedded := _consult_embedded_open_id(ref, open_before)) is not None:
            # T-12249 — the ref is not BARE but EMBEDS exactly one open id (the auditor copied the
            # whole scope-table row). It names that id, so it is that id's echo and rows 4/5/6/7/20
            # apply to it UNCHANGED — this is a transcription step ahead of row 21, not a new row.
            echoes.setdefault(embedded, []).append(finding)
        else:
            bad_ref.append((ref, finding))                 # row 21 — names no OPEN BLOCKING id

    # ── ECHO layer: every OPEN id hits exactly one of rows 4 / 5 / 6 / 7 / 20 / 8 ──
    for fid in open_before:
        group = echoes.get(fid) or []
        if not group:
            violations.append({"id": fid, "field": "baseline_ref",
                               "reason": CONSULT_VIOLATION_UNACCOUNTED})       # row 8
            continue
        states = {(_consult_str(f.get("resolution")) or "").lower() for f in group}
        entry = state["entries"].get(fid) or {}
        conflicting = [f for f in group
                       if _consult_str(f.get("disposition"))
                       and _consult_str(f.get("disposition")).lower() != entry.get("disposition")]
        if "open" in states and "closed" in states:
            violations.append({"id": fid, "field": "resolution",
                               "reason": CONSULT_VIOLATION_DUPLICATE_REF})     # row 6
        elif conflicting:
            violations.append({"id": fid, "field": "disposition",
                               "reason": CONSULT_VIOLATION_CONFLICT})          # row 7 — ENTRY wins
        elif states == {"closed"}:
            evidence = None
            for f in group:
                evidence = evidence or _consult_str(f.get("resolution_evidence"))
            if evidence is None:
                violations.append({"id": fid, "field": "resolution_evidence",
                                   "reason": CONSULT_VIOLATION_INVALID_RESOLUTION})   # row 5 (B4)
            else:
                resolutions.append({"id": fid, "resolution": "closed",
                                    "resolution_evidence": evidence,
                                    "closed_at_round": round_k})               # row 4
        elif states == {"open"}:
            pass                                                               # row 20 — no violation
        else:
            violations.append({"id": fid, "field": "resolution",
                               "reason": CONSULT_VIOLATION_INVALID_RESOLUTION})       # row 5

    for ref, finding in bad_ref:
        violations.append({"id": ref, "field": "baseline_ref",
                           "reason": CONSULT_VIOLATION_INVALID_REF})           # row 21
        # Re-read WITHOUT its ref — but ONLY to catch a defect the bad ref would otherwise HIDE.
        # Row 21 is explicit that a bare bad-ref echo changes NOTHING ELSE (VP26(a)), so a re-read
        # that fails to substantiate a block records no SECOND violation: the finding was already
        # classified once, as `invalid-ref`. Hence the re-read is `strict` — it can allocate a
        # residual (rows 9-10) and nothing else.
        non_echo.append((finding, True))

    # ── NON-ECHO layer: rows 19 -> 9/10 -> 11 ──
    for finding, strict in non_echo:
        disposition, violation = consult_finding_disposition(finding, lens)
        if disposition == "blocking":
            fid = f"R{round_k}.{len(residuals) + 1}"
            residuals.append(_consult_baseline_entry(finding, fid, "blocking", revision))
            if _consult_str(finding.get("causality")) == "pre-existing-in-subject":
                escapes += 1                          # row 10 — an ESCAPE of the freeze (rule 8)
        elif strict:
            continue                                  # row 21 bare bad ref — nothing else changes
        elif violation:
            violations.append({"id": None, "field": "disposition", "reason": violation})  # rows 2/11
        else:
            deferrals.append({"id": None, "locator": _consult_str(finding.get("locator"))})  # row 19
    return {"violations": violations, "resolutions": resolutions, "residuals": residuals,
            "escapes": escapes, "deferrals": deferrals}


def consult_adjudicate_round(prior, response, *, lens, revision, established_at,
                             offered_options, episode_id=None, payload_present=True,
                             scope_cuts=None, owner_rulings=None, CONSULT_MAX_NO_ANSWERS, CONSULT_NO_ANSWER_ROUTE_UNAVAILABLE, CONSULT_OUTCOME_HOLD, CONSULT_OUTCOME_MALFORMED, CONSULT_OUTCOME_NO_ANSWER, CONSULT_OUTCOME_OWNER_HELD, CONSULT_OUTCOME_PROCEED, CONSULT_OUTCOME_TERMINAL, CONSULT_ROUND_KIND_BASELINE, CONSULT_ROUND_KIND_RETEST, CONSULT_TERMINAL_MALFORMED_EXHAUSTED, CONSULT_TERMINAL_NON_ADMISSIBLE, CONSULT_TERMINAL_OPEN_IDS_AT_R2, CONSULT_VIOLATION_MALFORMED, _consult_classify_retest, _consult_prior_state, consult_admission, consult_freeze_baseline, consult_response_is_malformed, is_no_data_verdict) -> dict:
    """SPEC-0200 rules 2-6 — THE core. One immutable prior state in, ONE record delta out.

    `response` is the parsed auditor result: `{verdict, survivors, findings}` (the survivors in the
    record's own `{option, text}` shape). Neither `prior` nor `response` is mutated.

    Order of operations, exactly as rule 4 specifies:
      0. NO-ANSWER detection (T-12233, rule 4 row 0a) — checked FIRST, and it consumes no round.
      1. `round_kind` + `r_after` from the PRE-CALL state (never from the outcome).
      2. malformed detection (row 0) — nothing frozen, no resolution changed.
      3. the PRE-MATRIX admission check, on a WELL-FORMED response only.
      4. the per-finding layer (the freeze at round 0, the echo/non-echo rows at a retest).
      5. the OUTCOME layer in the fixed precedence 0a -> 15 -> 0 -> non-admissible -> 12 -> 16 -> 18 -> 17.

    `payload_present` (T-12233) is the ONE new input, and it is the only thing the invocation seam
    knows that this function cannot derive: did ANY payload come back from the auditor at all? It
    DEFAULTS TRUE — «a payload came back» is the status-quo assumption — so every existing caller
    and test keeps today's malformed reading byte-identical. NO-ANSWER is the CONJUNCTION
    `is_no_data_verdict(verdict, findings) and not payload_present`: the ratified SPEC-0173 rule-1
    predicate answers «did the run produce a verdict?» and cannot, alone, tell a
    returned-but-unparseable payload from no payload (`_parse_consult_result` yields ABORT + [] at
    rc 0 over a REAL payload), which is why the second signal is carried in rather than re-derived.
    `rc` is deliberately NOT the discriminator: an rc-0 blank stdout and an rc-124 empty stdout must
    read identically, and a nonzero rc over a REAL payload must stay MALFORMED.

    NO-ANSWER's effect, and it is a subtraction everywhere: `r_after` is UNCHANGED (no round is
    consumed), `malformed` is False and `malformed_count` UNCHANGED, nothing is frozen, no
    resolution changes, `no_answer_count` is the prior + 1, and the outcome is `no-answer` — which
    is NOT in `CONSULT_TERMINAL_OUTCOMES`, so the episode stays OPEN and the next call JOINS it. It
    is checked BEFORE row 15 because row 15's bound is on CALLS THAT ANSWERED: a call that consumed
    no round can never be the call that reaches R=2. Every round that DOES answer writes
    `no_answer_count: 0`, so the budget is per-ROUND rather than per-episode.

    Returns a dict of the SPEC-0200 top-level fields (`CONSULT_ADJUDICATION_RECORD_FIELDS`). Pure."""
    state = _consult_prior_state(prior)
    findings = [f for f in ((response or {}).get("findings") or ()) if isinstance(f, dict)]
    verdict = (response or {}).get("verdict")
    round_kind = (CONSULT_ROUND_KIND_BASELINE if not state["baseline"]
                  else CONSULT_ROUND_KIND_RETEST)

    # ── row 0a (T-12233) — did the auditor ANSWER at all? A no-answer consumes NO round. ──
    no_answer = is_no_data_verdict(verdict, findings) and not payload_present
    r_after = state["r_before"] + (
        0 if no_answer or round_kind != CONSULT_ROUND_KIND_RETEST else 1)
    no_answer_count = (state["no_answer_count"] + 1) if no_answer else 0

    malformed = (False if no_answer
                 else consult_response_is_malformed(verdict, findings, round_kind))
    non_admissible, survivor_is_proceed = (None, None)
    if not (malformed or no_answer):
        non_admissible, survivor_is_proceed = consult_admission(
            verdict, (response or {}).get("survivors"), offered_options)

    delta = {
        "baseline": state["baseline"],
        "baseline_revision": (state["baseline"] or {}).get("revision", revision),
        "episode_id": episode_id,
        "open_ids": list(state["open_ids"]),
        "resolutions": list(state["resolutions"]),
        "residuals": list(state["residuals"]),
        "contract_violations": [],
        "deferrals": list(state["deferrals"]),
        "completeness_failures": state["completeness_failures"],
        "round_kind": round_kind,
        "malformed": malformed,
        "malformed_count": state["malformed_count"] + (1 if malformed else 0),
        "no_answer": no_answer,
        "no_answer_count": no_answer_count,
        "no_answer_route": (CONSULT_NO_ANSWER_ROUTE_UNAVAILABLE
                            if no_answer and no_answer_count >= CONSULT_MAX_NO_ANSWERS else None),
        "r_after": r_after,
        "outcome": None,
        "terminal_reason": None,
        "non_admissible": non_admissible,
        "owner_held": False,
        "survivor_overridden": False,
    }
    if no_answer:
        pass                    # nothing frozen, no resolution changed, no violation recorded —
                                # there is no response to hold against the contract
    elif malformed:
        delta["contract_violations"] = [{"id": None, "field": "verdict",
                                         "reason": CONSULT_VIOLATION_MALFORMED}]
    elif non_admissible is None:
        # ── the per-finding layer ──
        if round_kind == CONSULT_ROUND_KIND_BASELINE:
            baseline, violations = consult_freeze_baseline(
                state["baseline"], findings, revision=revision,
                established_at=established_at,
                findings_complete=(response or {}).get("findings_complete"), lens=lens)
            delta["baseline"] = baseline
            delta["baseline_revision"] = baseline.get("revision")
            delta["contract_violations"] = violations
            delta["deferrals"] = [{"id": e["id"], "locator": e.get("locator")}
                                  for e in baseline["findings"] if e["disposition"] != "blocking"]
            delta["open_ids"] = [e["id"] for e in baseline["findings"]
                                 if e["disposition"] == "blocking"]
        else:
            got = _consult_classify_retest(findings, state, revision=revision,
                                           round_k=r_after, lens=lens, scope_cuts=scope_cuts,
                                           owner_rulings=owner_rulings)
            delta["contract_violations"] = got["violations"]
            delta["resolutions"] = state["resolutions"] + got["resolutions"]
            delta["residuals"] = state["residuals"] + got["residuals"]
            delta["deferrals"] = state["deferrals"] + got["deferrals"]
            delta["completeness_failures"] = state["completeness_failures"] + got["escapes"]
            closed = state["closed"] | {r["id"] for r in got["resolutions"]}   # incl. row-22 withdrawals
            delta["open_ids"] = [fid for fid in state["open_ids"] if fid not in closed] + \
                                [r["id"] for r in got["residuals"]]

    # ── the OUTCOME layer — the first row that applies wins (rule 4's precedence) ──
    open_ids = delta["open_ids"]
    if no_answer:
        delta["outcome"] = CONSULT_OUTCOME_NO_ANSWER                   # row 0a — FIRST, non-terminal
    elif r_after >= CONSULT_MAX_RETESTS and open_ids:
        delta["outcome"] = CONSULT_OUTCOME_TERMINAL                    # row 15 — FIRST, always
        delta["terminal_reason"] = CONSULT_TERMINAL_OPEN_IDS_AT_R2
    elif malformed:
        if delta["malformed_count"] > CONSULT_MAX_MALFORMED:
            delta["outcome"] = CONSULT_OUTCOME_TERMINAL                # row 0, second occurrence
            delta["terminal_reason"] = CONSULT_TERMINAL_MALFORMED_EXHAUSTED
        else:
            delta["outcome"] = CONSULT_OUTCOME_MALFORMED               # row 0 — re-run once
    elif non_admissible is not None:
        delta["outcome"] = CONSULT_OUTCOME_TERMINAL                    # the pre-matrix terminal
        delta["terminal_reason"] = CONSULT_TERMINAL_NON_ADMISSIBLE
    elif survivor_is_proceed and open_ids:
        delta["outcome"] = CONSULT_OUTCOME_HOLD                        # row 12 — overridden
        delta["survivor_overridden"] = True
    elif not survivor_is_proceed and not open_ids:
        delta["outcome"] = CONSULT_OUTCOME_OWNER_HELD                  # row 16 — terminal
        delta["owner_held"] = True
    elif survivor_is_proceed:
        delta["outcome"] = CONSULT_OUTCOME_PROCEED                     # row 18 — the episode ENDS
    else:
        delta["outcome"] = CONSULT_OUTCOME_HOLD                        # row 17 — the ordinary retest
    return delta


def consult_episode_transition(*, open_episode, round_in_flight, highest_n) -> dict:
    """Rule 1 — the SERIALIZED pre-call transition, as a PURE decision (its caller holds the lock).

    No open episode      -> ALLOCATE n+1 (round 0).
    An open episode      -> JOIN it as its next round, or `episode-busy` while a round of it is in
                            flight. It NEVER allocates a second episode: n+2 exists only after a
                            durable owner boundary or a new basis closed episode n.

    Returns `{decision, n}` with decision ∈ {allocate, join, episode-busy}."""
    if open_episode is None:
        return {"decision": "allocate", "n": int(highest_n or 0) + 1}
    if round_in_flight:
        return {"decision": "episode-busy", "n": int(open_episode)}
    return {"decision": "join", "n": int(open_episode)}


def consult_episode_id(target_id, consult_key, n) -> str:
    """Rule 1 — `<target>/<stage|gate>/<attempt n>`. The baseline revision is carried as its own
    field (`baseline_revision`), never as part of the id."""
    return f"{target_id}/{consult_key}/{n}"


def consult_allocate_episode(target_id, consult_key, *, scan, _with_repo_lock, ref,
                             commit=None, consult_episode_id, consult_episode_transition) -> dict:
    """Rule 1 — the episode allocation: the SCAN, the transition AND the durable APPEND run inside
    ONE critical section, so two producers can never both allocate n+1 (B8).

    `scan()` returns `{open_episode, round_in_flight, highest_n}` read from durable state; `commit`,
    when given, is called with the decision to MAKE that allocation durable. BOTH run under the
    lock, because the rule is "read AND appended under the lock": serializing only the READ leaves
    the window between the decision and its recording open, and a second producer entering it scans
    the pre-allocation state and allocates the SAME n — the exact B8 collision. (Measured: the AC5
    differential caught this shape under parallel land load, 2026-09-06.)

    The lock is the repo's EXISTING cross-session `_with_repo_lock` (injected, this module's
    established dependency style) — see this block's LOCK NOTE: no new lock class, no new lock file,
    no second lock path."""
    with _with_repo_lock(ref):
        decision = consult_episode_transition(**scan())
        decision["episode_id"] = consult_episode_id(target_id, consult_key, decision["n"])
        if commit is not None:
            commit(decision)
        return decision


def consult_attempt_id(episode_id, r_after) -> str:
    """Rule 8 — the PRE-RESPONSE attempt identity: `<episode_id>/r<r_after>`.

    BOTH components are fixed by the state BEFORE the auditor is called (rule 4: `round_kind` and
    therefore `r_after` are pre-call quantities), which is the whole point — a PARAPHRASED RETRY of
    the same attempt re-derives the SAME attempt id, so it cannot re-emit. An id derived from the
    RESPONSE (its text, its finding count, its timestamp) would differ on every retry and would
    re-emit exactly the deviation this key exists to deduplicate."""
    return f"{episode_id}/r{int(r_after or 0)}"


def consult_escape_residual_ids(delta, *, _consult_str) -> list:
    """Rule 8 / matrix row 10 — the residual ids this round allocated for an ESCAPE of the freeze.

    An escape is a NEW blocking finding at a retest whose `causality` is `pre-existing-in-subject`:
    the baseline declared the survey complete (or did not), and a defect that was ALREADY THERE
    surfaced anyway. C2 already counts them into `completeness_failures`; this recovers their
    IDENTITY, which is what makes two escapes in one response two deviations instead of one.

    Pure f(delta), and derived rather than re-plumbed: C2's residual entry transcribes `causality`,
    and a residual allocated at round k carries the id `R<k>.<n>` (rule 5), so THIS round's escapes
    are exactly the pre-existing residuals whose id names this round. Residuals carried forward from
    an earlier round keep their own round's prefix and are therefore not re-counted."""
    delta = delta if isinstance(delta, dict) else {}
    prefix = f"R{int(delta.get('r_after') or 0)}."
    return [r.get("id") for r in (delta.get("residuals") or ())
            if isinstance(r, dict) and isinstance(r.get("id"), str)
            and r["id"].startswith(prefix)
            and _consult_str(r.get("causality")) == "pre-existing-in-subject"]


def consult_escape_key_token(attempt_id, residual_id) -> str:
    """The DURABLE journal identity of one escape — `(attempt_id, residual_id)` as one string.

    A token rather than a tuple because it has to survive a round-trip through JSON: the dedupe reads
    it back off `deviation_captured` rows written by earlier sessions, and a tuple does not."""
    return f"{attempt_id}#{residual_id}"


def consult_escape_keys(delta, *, episode_id, consult_attempt_id, consult_escape_residual_ids) -> list:
    """Rule 8 — the `(attempt_id, residual_id)` keys of THIS round's escapes, in allocation order.

    The residual id is IN the key, which is B7's whole content: TWO distinct pre-existing NEW blocking
    findings in ONE response are TWO escapes and owe TWO deviations. A key made of the fingerprint
    alone — or of the attempt alone — collapses them to one, which is the failing input this card's
    AC1 requires to fail."""
    attempt = consult_attempt_id(episode_id, (delta or {}).get("r_after"))
    return [(attempt, rid) for rid in consult_escape_residual_ids(delta)]


def consult_recorded_escape_keys(rows) -> set:
    """The escape key tokens ALREADY on the journal — the dedupe's memory.

    Pure over ROWS, so the caller decides which fold produced them; the wired caller passes a
    SEGMENT-AWARE fold, and that is what makes an archived segment still dedupe (SPEC-0190 rule 4).
    Only rows carrying THIS fingerprint are read, so an unrelated `deviation_captured` can never
    suppress an escape."""
    out = set()
    for row in rows or ():
        if not isinstance(row, dict) or row.get("type") != "deviation_captured":
            continue
        data = row.get("data")
        if not isinstance(data, dict):
            continue
        if data.get("fingerprint") != CONSULT_ESCAPE_FINGERPRINT:
            continue
        token = data.get(CONSULT_ESCAPE_KEY_FIELD)
        if isinstance(token, str) and token.strip():
            out.add(token.strip())
    return out


def consult_escape_deviations(delta, *, episode_id, target_id, rows, consult_escape_key_token, consult_escape_keys, consult_recorded_escape_keys) -> list:
    """Rule 8 — the `deviation_captured` payloads owed for THIS round's escapes: ONE per FIRST
    discovery, deduped against durable journal identity.

    Three dedupe layers, and all three are needed: against the journal (a paraphrased retry of the
    same attempt, and a retry after ROTATION, both re-derive a key that is already recorded), and
    WITHIN this call (a response that names the same residual twice owes one deviation, not two).
    Returns payloads rather than emitting: the emit is the caller's, so this stays pure and the probe
    can assert the exact set without a journal."""
    recorded = consult_recorded_escape_keys(rows)
    seen, out = set(), []
    for attempt, rid in consult_escape_keys(delta, episode_id=episode_id):
        token = consult_escape_key_token(attempt, rid)
        if token in recorded or token in seen:
            continue
        seen.add(token)
        out.append({
            "relates_to": target_id,
            "impact": (f"consult baseline completeness failure: residual {rid} is a NEW blocking "
                       f"finding at retest {attempt} with causality pre-existing-in-subject — a "
                       f"defect the frozen baseline survey MISSED (SPEC-0200 rule 8, matrix row 10). "
                       f"The escape blocks and joins the residual set; this row is what makes the "
                       f"auditor's completeness a measured quantity."),
            "fingerprint": CONSULT_ESCAPE_FINGERPRINT,
            CONSULT_ESCAPE_KEY_FIELD: token,
            "episode_id": episode_id,
            "attempt_id": attempt,
            "residual_id": rid,
        })
    return out


def consult_emit_escape_deviations(delta, *, episode_id, target_id, events_path,
                                   _iter_events, _append_event, consult_escape_deviations) -> list:
    """The WIRED half of rule 8's escape accounting — fold, dedupe, append. Called by NOTHING today.

    The reader is INJECTED and the host passes `cli._iter_events`, which folds the SEGMENT SET
    (SPEC-0190 rule 4). That is the correctness property: reading the live segment alone would make
    every recorded deviation invisible after rotation and re-emit the lot. Returns the payloads it
    appended, so a caller (and the probe) sees exactly what was written.

    THE WRITE GOES TO THE JOURNAL THE DEDUPE READ, and that is passed EXPLICITLY rather than left to
    the appender's ambient default. A dedupe is a claim about ONE journal: read journal A, write
    journal B, and every append is a first discovery forever — the deduplication silently degrades
    to none while still reading as correct. The host appender resolves its own default target when
    given none, so an injection of the real `events.append_event` would take that other path; naming
    the path closes the read/write asymmetry at the only place that knows both halves."""
    rows = list(_iter_events(events_path))
    payloads = consult_escape_deviations(delta, episode_id=episode_id, target_id=target_id, rows=rows)
    for payload in payloads:
        _append_event("deviation_captured", target_id, payload, events_path=events_path)
    return payloads


def consult_successor_key(episode_id, finding_id) -> str:
    """Rule 8 / B6 — the COMPOSITE successor identity `(episode_id, finding_id)`, as one token.

    NEVER the bare `B<n>` / `R<k>.<n>`: those are unique only inside their episode, so two episodes
    each allocating a deferrable `B1` would share a key and the second would silently reuse the
    first's carrier. The composite is what the carrier's text carries and what the locator lookup
    matches on."""
    return f"{CONSULT_SUCCESSOR_PREFIX}{episode_id}#{finding_id}"


def consult_successor_locator(key, *, rows, task_texts=None):
    """Rule 8 — an EXISTING carrier naming this composite identity, or None.

    STATUS IS DELIBERATELY NOT READ. Rule 8 says an existing OPEN **or TERMINAL** followup / task
    naming the composite is a valid locator: the successor work was already filed, and whether it was
    later promoted or dropped is a DISPOSITION of that work, not a reason to file it again. A lookup
    that skipped terminal carriers would re-file every dropped deferral on every re-run — the exact
    non-idempotency this helper exists to prevent.

    Two carrier kinds, both existing: a `followup_added` row whose text or provenance carries the key
    (the SPEC-0095 primitive — no new store), and a task card whose text carries it. `task_texts` is
    an optional `{task_id: text}` supplied by the caller, which owns `tasks/`."""
    key = (key or "").strip()
    if not key:
        return None
    for row in rows or ():
        if not isinstance(row, dict) or row.get("type") != "followup_added":
            continue
        data = row.get("data")
        if not isinstance(data, dict):
            continue
        blob = " ".join(str(data.get(f) or "") for f in ("text", "relates_to"))
        if key in blob:
            fid = data.get("followup_id")
            if isinstance(fid, str) and fid:
                return fid
    for tid, text in sorted((task_texts or {}).items()):
        if key in str(text or ""):
            return tid
    return None


def consult_successor_text(key, *, target_id, finding_id, entry=None, _consult_str) -> str:
    """The capture text a filed successor carries. It EMBEDS the composite key verbatim, because that
    embedding IS the identity the next run's lookup matches on — the carrier is its own index."""
    entry = entry if isinstance(entry, dict) else {}
    where = _consult_str(entry.get("locator")) or "(no locator supplied)"
    return (f"consult deferral {finding_id} on {target_id} — successor work for a SPEC-0200 rule-8 "
            f"deferrable finding at {where}. identity: {key}")


def consult_file_successors(delta, *, episode_id, target_id, rows, file_followup,
                            task_texts=None, consult_successor_key, consult_successor_locator, consult_successor_text) -> list:
    """Rule 8 — file successor work for every `deferrable` finding, ONCE, keyed by the composite.

    IDEMPOTENT BY CONSTRUCTION rather than by a guard: the carrier it files EMBEDS the composite key,
    so the next run's `consult_successor_locator` finds it and files nothing. There is no "already
    filed" flag to keep in sync, and no state that can disagree with the journal.

    `file_followup(text=..., relates_to=...)` is INJECTED and returns the new carrier's locator; the
    host wires it to `followup add` (SPEC-0095) — the REUSED carrier, so this adds no question store
    and no second FSM. Returns the top-level `deferrals: [{id, locator}]` rule 8 records."""
    delta = delta if isinstance(delta, dict) else {}
    rows = list(rows or ())
    out = []
    for entry in (delta.get("deferrals") or ()):
        if not isinstance(entry, dict):
            continue
        fid = entry.get("id")
        if not isinstance(fid, str) or not fid:
            # A pre-id deferral (a row-19 retest finding C2 records before an id exists) carries no
            # composite identity, so it is passed through UNCHANGED rather than filed under a key
            # that would not be stable across runs — filing it would be the non-idempotent branch.
            out.append(dict(entry))
            continue
        key = consult_successor_key(episode_id, fid)
        locator = consult_successor_locator(key, rows=rows, task_texts=task_texts)
        if locator is None:
            locator = file_followup(
                text=consult_successor_text(key, target_id=target_id, finding_id=fid, entry=entry),
                relates_to=target_id)
        out.append({"id": fid, "locator": locator})
    return out


def consult_episode_row_fields(delta, *, episode_id=None, consult_escape_residual_ids) -> dict:
    """Rule 9 — render EXACTLY `CONSULT_EPISODE_ROW_FIELDS` from a C2 record delta. EMITTED BY NOTHING.

    Two shapes differ deliberately between the record and the row, and both are rule 9's own words:
      * `contract_violations` rides the row as `[{id, kind}]` — this ROUND's violations, the reading
        the fold needs — while the record keeps C2's richer `{id, field, reason}`. The row is a
        measurement surface, not a second copy of the record.
      * `completeness_failures_delta` is the escapes counted THIS ROUND (B13), not the running total.
        The running total is the record's; a row carrying the total would double-count under the
        fold's own summation.
    Returns exactly `CONSULT_EPISODE_ROW_FIELDS` and no other key, so a caller cannot leak a record
    field onto the durable row by accident."""
    delta = delta if isinstance(delta, dict) else {}
    violations = [{"id": v.get("id"), "kind": v.get("reason")}
                  for v in (delta.get("contract_violations") or ()) if isinstance(v, dict)]
    return {
        "episode_id": episode_id if episode_id is not None else delta.get("episode_id"),
        "baseline_revision": delta.get("baseline_revision"),
        "round_kind": delta.get("round_kind"),
        "malformed": bool(delta.get("malformed")),
        # T-12233 — the no-answer half of the round's classification. `no_answer_route` is None on
        # every round but the SECOND consecutive no-answer, which carries `auditor-unavailable`.
        "no_answer": bool(delta.get("no_answer")),
        "no_answer_count": int(delta.get("no_answer_count") or 0),
        "no_answer_route": delta.get("no_answer_route"),
        "r_after": int(delta.get("r_after") or 0),
        "malformed_count": int(delta.get("malformed_count") or 0),
        "contract_violations": violations,
        "completeness_failures_delta": len(consult_escape_residual_ids(delta)),
        "outcome": delta.get("outcome"),
        "terminal_reason": delta.get("terminal_reason"),
        "non_admissible": delta.get("non_admissible"),
    }


def consult_round_withdrawn(delta, *, prior=None) -> list:
    """T-12248 — the withdrawals THIS ROUND recorded, as `[{id, resolution, receiving_task}]`.

    A DELTA, not the running list, and for the same reason `completeness_failures_delta` is one
    (rule 9 / B13): the record's `resolutions` is CUMULATIVE, so a row carrying all of it would
    re-report on every later round an id withdrawn once. The delta is computed by subtracting the
    ids the PRIOR record already resolved — the same pre-call state the adjudication itself read —
    rather than by trusting a caller to slice the list correctly.

    Returns [] for a round that withdrew nothing (and for `delta=None`, the malformed/no-answer and
    pre-C3 paths), which is what keeps the row's `withdrawn` key ABSENT on an ordinary round. The
    three keys are the ones a reader of the journal needs and no more — the directive locator stays
    on the RECORD, where the full resolution entry lives.

    WHY IT RIDES THE ROW AT ALL, on the same terms as `owner_reopen`: rule 9's reason for the eleven
    episode fields. The RECORD is rewritten in place by the next adjudication, so a withdrawal
    readable only there could be edited out from under the reader that needs it; the row is
    append-only. It is NOT a twelfth rule-9 episode field — `consult_episode_row_fields` still
    returns exactly its declared set, and this key is attached beside it, as `owner_reopen` is.
    Pure f(delta, prior)."""
    if not isinstance(delta, dict):
        return []
    already = {r.get("id") for r in ((prior or {}).get("resolutions") or ())
               if isinstance(r, dict)}
    return [{"id": r.get("id"), "resolution": r.get("resolution"),
             "receiving_task": r.get("receiving_task")}
            for r in (delta.get("resolutions") or ())
            if isinstance(r, dict) and r.get("resolution") in CONSULT_WITHDRAWN_VALUES
            and r.get("id") not in already]


def consult_pick_held_record(records) -> dict:
    """Rule 9 / B8 — the held-record fallback in a TOTAL order: the PERSISTED attempt ordinal
    (`episode_id`'s n) first, then the in-record `established_at`. NEVER file mtime and never
    timestamp alone — two held records written in the same second must still order deterministically.

    `records` is an iterable of loaded record dicts; returns the winner, or None when empty."""
    def _ordinal(rec):
        eid = (rec or {}).get("episode_id")
        if isinstance(eid, str) and "/" in eid:
            tail = eid.rsplit("/", 1)[-1]
            if tail.isdigit():
                return int(tail)
        return -1

    def _established(rec):
        baseline = (rec or {}).get("baseline")
        at = baseline.get("established_at") if isinstance(baseline, dict) else None
        return str(at or "")

    ranked = sorted((r for r in (records or ()) if isinstance(r, dict)),
                    key=lambda r: (_ordinal(r), _established(r)))
    return ranked[-1] if ranked else None


def consult_task_lens(card, *, _card_declared_ac_ids) -> set:
    """The TASK lens: the acceptance-criterion ids the card actually declares, as `AC<n>` tokens.

    REUSES `_card_declared_ac_ids` (which reads the same `acceptance` list, anchored at each entry's
    start) rather than re-parsing the card — one reader, one answer. An absent or malformed card
    yields the EMPTY lens, and empty is the FAIL-CLOSED direction: every `criterion_ref` then reads
    `invalid-criterion` and demotes to `deferrable`, so a lens the engine could not build can never
    let an unvalidated block through. Pure f(card)."""
    return {f"AC{n}" for n in _card_declared_ac_ids(card)}


def consult_scope_cuts(card, *, _ACCEPTANCE_AC_RE) -> dict:
    """T-12244 (rule 4 row 22) — the acceptance criteria the CURRENT card marks CUT by a recorded
    owner decision, as `{"AC<n>": {"owner_directive": <locator>, "receiving_task": <id>}}`.

    A DERIVED VIEW over the SAME `acceptance` list `consult_task_lens` reads — the criterion stays
    declared (so the lens is unchanged and a `criterion_ref` naming it is still valid), but its text
    now records that its subject was moved out of this card. Both marker tokens are REQUIRED:

      * the receiving card id — `CUT to T-12243`;
      * the recorded owner-directive locator — `owner_directive events.jsonl#ts=<...>`.

    Fail-closed on everything else: an absent or malformed card, an entry carrying only one of the
    two tokens, or a blank locator yields NO cut for that criterion, and its baseline finding stays
    open. Withdrawing a finding is a scope judgement the OWNER already made and recorded; a card
    that merely reworded a criterion must not be able to withdraw a live defect. Pure f(card)."""
    if not isinstance(card, dict):
        return {}
    acc = card.get("acceptance") or []
    if isinstance(acc, str):
        acc = [acc]
    if not isinstance(acc, (list, tuple)):
        return {}                       # a malformed `acceptance` cuts nothing (fail-closed)
    out = {}
    for entry in acc:
        text = str(entry)
        m = _ACCEPTANCE_AC_RE.match(text)
        if not m:
            continue
        receiver = _CONSULT_CUT_RECEIVER_RE.search(text)
        directive = _CONSULT_CUT_DIRECTIVE_RE.search(text)
        if not receiver or not directive:
            continue
        locator = directive.group(1).strip().strip(_CONSULT_CUT_LOCATOR_STRIP)
        if not locator:
            continue
        out[f"AC{m.group(1).lstrip('0') or '0'}"] = {
            "owner_directive": locator, "receiving_task": receiver.group(1)}
    return out


def consult_owner_rulings(card, *, task_exists=None, _amend_note_body) -> dict:
    """T-12248 (rule 4 row 23) — the open FINDING IDS the CURRENT card records as ruled OUT OF ITS
    SUBJECT by the owner, as `{"B1": {"owner_directive": <locator>, "receiving_task": <id>}}`.

    The SIBLING of `consult_scope_cuts`, and read the same way for the same reason: a DERIVED VIEW
    over a place the ruling is ALREADY recorded, never a second store. A scope cut writes on the
    criterion that moved; an out-of-subject ruling has no criterion to write on, so it is read from
    `amend_notes` — the governed home a recorded owner ruling on a card lands in (`task update
    --note`, SPEC-0028), which this module already reads on its packet path. All THREE tokens are
    required, in the SAME entry:

      * the finding id, at the note body's START — `WITHDRAWN B1 out-of-subject to T-12249`;
      * the receiving card id, in that same clause;
      * the recorded owner-directive locator — `owner_directive events.jsonl#ts=<...>`.

    THE RECEIVING CARD MUST BE A FILED ONE (audit-pre finding 1). Two layers, because a reader that
    opens files is neither the row-22 shape nor testable as one:

      * SHAPE, always — `_CONSULT_RULING_RE` admits only a `<PREFIX>-<NNN+>` id token;
      * EXISTENCE, through the INJECTED `task_exists` predicate. That injection is the correctness
        property, not a style — the same shape `consult_emit_escape_deviations` uses for the journal
        reader: the check is REAL at the seam and substitutable in a fixture. Both live producers
        pass the real resolver, so the LIVE path is fail-closed on an id naming no filed card.
        `task_exists=None` is the shape-only analysis form and is never what a producer passes; the
        wiring pin in this card's test is what keeps that honest.

    Fail-closed on everything else, in the one direction that cannot let a live defect leave the
    open set: an absent or malformed card, a malformed `amend_notes`, a missing token, a blank
    locator, a marker mentioned mid-prose, or a receiving id the predicate does not recognise —
    each yields NO ruling for that id, and its finding stays open. Withdrawing a finding is a
    judgement the OWNER already made and recorded; a card that merely discusses a finding must not
    be able to withdraw it. A plan gate holds no card and therefore yields none."""
    if not isinstance(card, dict):
        return {}
    notes = card.get("amend_notes") or []
    if isinstance(notes, str):
        notes = [notes]
    if not isinstance(notes, (list, tuple)):
        return {}                       # a malformed `amend_notes` rules nothing out (fail-closed)
    out = {}
    for entry in notes:
        if not isinstance(entry, str):
            continue
        body = _amend_note_body(entry)
        m = _CONSULT_RULING_RE.match(body)
        if not m:
            continue
        directive = _CONSULT_CUT_DIRECTIVE_RE.search(body)
        if not directive:
            continue
        locator = directive.group(1).strip().strip(_CONSULT_CUT_LOCATOR_STRIP)
        if not locator:
            continue
        receiver = m.group(2)
        if task_exists is not None and not task_exists(receiver):
            continue                    # named no FILED card — not a receiving card (fail-closed)
        out[m.group(1)] = {"owner_directive": locator, "receiving_task": receiver}
    return out


def consult_criterion_slug(text: str) -> str:
    """One gate-lens criterion id, slugged deterministically from its template bullet.

    Bounded to the first six words: the bullets are full sentences, and a slug of a whole sentence is
    an id no auditor would reproduce. Six words is enough to separate the four-to-five bullets of any
    one gate template, which is all this id has to do."""
    words = _CONSULT_LENS_SLUG_RE.sub("-", str(text or "").lower()).strip("-").split("-")
    return "-".join([w for w in words if w][:6])


def consult_plan_gate_lens(gate_token: str, template_text: "str | None", *, consult_criterion_slug) -> set:
    """The PLAN-GATE lens: `<gate>:<criterion>` ids derived from THAT gate's normative audit lens.

    Rule 3 spells the shape (`gate-specs:P2-scope-stability`) but names no catalog, and there is no
    criterion-id store in this corpus to read one from — the gate lenses are the prose bullets of
    SPEC-0036's per-gate question templates. So the ids are DERIVED from that single normative home,
    one per bullet, rather than hand-listed here: a hand list would be a second home for the gate
    lens and would drift from the spec the auditor is actually judging against.

    The EMPTY lens on an unavailable template is the fail-closed direction, exactly as for a task: a
    plan-gate finding then cannot substantiate a block by `criterion_ref` at all (it may still block
    by a closed `class_id`, which needs no lens). Pure f(text)."""
    out = set()
    for line in str(template_text or "").splitlines():
        line = line.strip()
        if not line.startswith("- "):
            continue
        slug = consult_criterion_slug(line[2:])
        if slug:
            out.add(f"{gate_token}:{slug}")
    return out


def consult_lens_block(lens, *, is_plan) -> str:
    """The round-0 prompt's rendering of the lens — the ids a `criterion_ref` may name.

    An auditor cannot cite a criterion it was never shown, and rule 3 DEMOTES an unrecognised one to
    `deferrable`. Withholding the list would therefore make the validation a trap rather than a
    contract: the auditor would report a real defect in good faith and the engine would silently
    decline to let it block. Pure f(lens)."""
    ids = sorted(lens or ())
    kind = "plan-gate criterion" if is_plan else "acceptance-criterion id"
    if not ids:
        return (f"\n### Valid `criterion_ref` values ({kind})\n\n"
                "(none resolvable for this target — substantiate a block by `class_id` instead)\n")
    return (f"\n### Valid `criterion_ref` values ({kind}) — an EXACT match, or the finding cannot "
            f"block\n\n" + "\n".join(f"- {i}" for i in ids) + "\n")


def consult_open_entries(prior, *, _consult_prior_state) -> list:
    """The OPEN blocking entries of a prior consult record, in id order — what a retest is scoped to.

    Reads the same pre-call state the C2 core reads (`_consult_prior_state`), so the prompt the
    auditor sees and the matrix that judges its answer can never disagree about which ids are open.
    Pure f(record)."""
    state = _consult_prior_state(prior if isinstance(prior, dict) else {})
    return [state["entries"][fid] for fid in state["open_ids"] if fid in state["entries"]]


def consult_baseline_table(prior, *, _consult_prior_state, _consult_str) -> str:
    """Rule 4(i) — the baseline + residual ids WITH their disposition and resolution, as the retest
    prompt's scope table. EVERY entry is listed (not just the open ones) with its current resolution,
    because rule 4(i) says «lists the baseline + residual ids with their disposition and resolution»:
    an auditor that cannot see an id was already CLOSED has no way to tell a re-report from a
    regression. Pure f(record)."""
    prior = prior if isinstance(prior, dict) else {}
    state = _consult_prior_state(prior)
    closed = state["closed"]
    resolved = {r.get("id"): r.get("resolution") for r in state["resolutions"]
                if isinstance(r, dict)}
    receivers = {r.get("id"): r.get("receiving_task") for r in state["resolutions"]
                 if isinstance(r, dict) and r.get("resolution") in CONSULT_WITHDRAWN_VALUES}
    lines = []
    for fid, entry in sorted(state["entries"].items()):
        # A row-22/23 withdrawal is shown under ITS OWN name: an auditor told an id is `closed` reads
        # a fix that never happened, which is the misreading the disposition exists to prevent.
        resolution = (resolved.get(fid) or "closed") if fid in closed else "open"
        where = _consult_str(entry.get("locator")) or "(no locator)"
        why = (_consult_str(entry.get("criterion_ref"))
               or _consult_str(entry.get("class_id")) or "(no criterion)")
        # T-12249 — the id gets its OWN leading `id:` column. The row used to open `- [B1] ...`, and
        # an auditor asked for the id «verbatim from the table above» copied the whole row into
        # `baseline_ref` twice in one day (T-12237, T-12208). Naming the column makes «the id» a
        # thing the row points at rather than something to be picked out of it. The PARSER-side
        # extraction is the guarantee; this is the hygiene that stops producing the input.
        # T-12248 — and WHERE THE WORK WENT, on a withdrawn row only. Telling an auditor an id was
        # withdrawn without naming the card that now owns the fix leaves it unable to tell a
        # withdrawal from an abandonment, which is exactly the reading a withdrawal must not carry.
        handed = receivers.get(fid)
        tail = f" | -> {handed}" if (fid in closed and handed) else ""
        lines.append(f"- id: {fid} | disposition: {entry.get('disposition')} | "
                     f"resolution: {resolution} | {why} | {where}{tail}")
    return "\n".join(lines) or "(no ids frozen — the baseline survey was empty)"


def consult_withdrawn_block(prior, *, _consult_prior_state) -> str:
    """T-12248 — the WITHDRAWN heading of the retest packet: every id an OWNER took out of this
    episode, with the card that now owns its fix and the directive that ruled it.

    ONE block for BOTH withdrawal kinds (rows 22 and 23), because an auditor asks one question about
    them — «why is this id gone, and who has it now?» — and two headings answering it differently
    would invite the reading that one of them IS a closure. The scope table above still lists these
    ids with their own `resolution`; this block is what states, in the packet's own words, that the
    absence is an OWNER RULING and not work the retest should look for.

    Returns the EMPTY STRING when nothing was withdrawn, so an ordinary episode's packet is
    byte-identical to what it was before this card. Pure f(record)."""
    state = _consult_prior_state(prior if isinstance(prior, dict) else {})
    rows = [r for r in state["resolutions"]
            if isinstance(r, dict) and r.get("resolution") in CONSULT_WITHDRAWN_VALUES]
    if not rows:
        return ""
    lines = ["\n### WITHDRAWN by owner ruling — NOT closed, and NOT yours to judge\n",
             "These ids left the open set by an OWNER decision recorded on the target, not by a fix.",
             "Do NOT re-report them, do NOT judge them `open`, and do NOT count them as resolved:",
             "the work rides the RECEIVING card named on each row.\n"]
    for r in sorted(rows, key=lambda x: str(x.get("id"))):
        lines.append(f"- [{r.get('id')}] {r.get('resolution')} | receiving card: "
                     f"{r.get('receiving_task') or '(unnamed)'} | owner directive: "
                     f"{r.get('owner_directive') or '(unrecorded)'}")
    return "\n".join(lines) + "\n"


def consult_prompt_overlay(prior, *, round_kind, revision=None, lens=None,
                           is_plan=False, CONSULT_ROUND_KIND_BASELINE, _AUDIT_FULL_VERDICT_CLAUSE, _CONSULT_BASELINE_OUTPUT_BLOCK, consult_baseline_table, consult_lens_block, consult_withdrawn_block) -> str:
    """SPEC-0200 rule 4 — the ROUND-AWARE overlay appended to the base consult prompt.

    ROUND 0 gets `_AUDIT_FULL_VERDICT_CLAUSE` + the `findings_complete` ask + the rule-3 output block.
    ROUND k >= 1 gets the DELTA overlay and NO whole-subject directive ANYWHERE — rule 4(iii) is a
    statement about the ASSEMBLED prompt, not about this fragment, which is why AC1's differential
    greps the whole assembled string rather than this return value.

    THE ASYMMETRY IS THE POINT, not an optimization. Under the retired every-surface clause the
    auditor was ordered to re-survey the whole tree on every pass, so every round could return a
    fresh set of ids and the loop had no fixed point — the «new set every round» outcome rule 10
    retires. Scoping the retest to the frozen ids is what makes rule 6's three-rule machine
    TERMINATE: a retest either closes ids or adds residuals that are themselves ids for the next
    retest, and R ≤ 2 bounds the rest.

    Pure f(prior, round_kind)."""
    if round_kind == CONSULT_ROUND_KIND_BASELINE:
        return (
            "\n" + _AUDIT_FULL_VERDICT_CLAUSE
            + consult_lens_block(lens, is_plan=is_plan)
            + "\n## Baseline output — add these to the YAML block below (SPEC-0200 rules 2-3)\n\n"
            + "```yaml\n" + _CONSULT_BASELINE_OUTPUT_BLOCK + "```\n"
            "A finding claiming `blocking` WITHOUT all of criterion_ref-or-class_id + locator +\n"
            "failing_input + causality reads `deferrable` immediately — an unproven block does not\n"
            "block, and there is no second ask. `severity` derives NOTHING.\n"
        )
    return (
        "\n## Delta retest — judge ONLY the ids below (SPEC-0200 rule 4)\n\n"
        "This is a RETEST round of an OPEN ceiling episode. The whole-subject survey was FROZEN at\n"
        "round 0 and is NOT re-opened: do NOT re-survey the subject, and do NOT enumerate defects\n"
        "over the whole tree. Judge EXACTLY two things:\n"
        "  (1) for each OPEN blocking id below, whether it is now `closed` — and if closed, the\n"
        "      `resolution_evidence` that shows it (a locator, a test node, a diff ref). A `closed`\n"
        "      with no evidence is NOT a closure and the id stays open.\n"
        "  (2) any REGRESSION the fix introduced — a NEW finding with `causality:\n"
        "      introduced-by-subject`, substantiated per rule 3.\n"
        "An id you do not mention at all stays OPEN and is recorded `unaccounted`.\n"
        f"\n### The frozen baseline + residual ids (subject revision: {revision or '(unrecorded)'})\n\n"
        f"{consult_baseline_table(prior)}\n"
        f"{consult_withdrawn_block(prior)}"
        "\n### Retest output — add this to the YAML block below\n\n"
        + "```yaml\n" + _CONSULT_RETEST_OUTPUT_BLOCK + "```\n"
    )


def consult_offered_pair(*, AUTO_CONSULT_HOLD_OPTION, AUTO_CONSULT_PROCEED_OPTION) -> list:
    """Rule 7 — the OFFERED option pair, which is the two fixed constants and nothing else.

    A function rather than a module constant so the pair is built fresh per call: it is PERSISTED
    onto the record, and a shared mutable list persisted into many records is a defect waiting for
    the first caller that sorts it."""
    return [AUTO_CONSULT_PROCEED_OPTION, AUTO_CONSULT_HOLD_OPTION]


def consult_options_are_offered_pair(options, *, consult_offered_pair) -> bool:
    """Are these EXACTLY the two fixed constants, in order? Exact equality on both texts.

    Not a fuzzy match and not a prefix test: rule 7 identifies the survivor by exact equality against
    the persisted pair, so admitting a near-miss here would persist a pair the survivor check then
    fails against — a refusal deferred to after the auditor was paid."""
    texts = [o.strip() for o in (options or ()) if isinstance(o, str)]
    return texts == [o.strip() for o in consult_offered_pair()]


def consult_hand_framed_refusal(target_id, consult_key, options, *, consult_options_are_offered_pair) -> "str | None":
    """Rule 7 — the PRE-AUDITOR refusal of hand-supplied `--option` texts at a baseline-bearing
    consult, or None when the pair is the offered one.

    WHAT IS RETIRED (rule 10, first item): the Controller practice of writing its own consult
    options. It is not a style preference — it DEFEATED owner-held recognition. T-10899 keyed that
    recognition on the survivor's exact text matching `AUTO_CONSULT_HOLD_OPTION`, so a consult run
    with hand-written options produced a survivor that matched nothing, and a genuine owner-held HOLD
    read as an unclassifiable verdict (the T-12150 r8 failure input).

    PRE-AUDITOR is the load-bearing half: no auditor call, no round, R unchanged, no matrix row, and
    NEVER an `external_audit_completed` row (C4.2). Refusing after the call would burn a round to
    tell the caller something computable from its own argv. Pure f(args); the caller `_die`s with it,
    so the verb's EXISTING refusal emit journals it."""
    if consult_options_are_offered_pair(options):
        return None
    return (
        f"audit consult refused ({CONSULT_REFUSAL_HAND_FRAMED}): {target_id} {consult_key} is a "
        f"BASELINE-BEARING ceiling consult, and SPEC-0200 rule 7 retires hand-framed options there "
        f"— the verb generates the pair, the Controller never writes it. Hand-written option texts "
        f"defeat owner-held recognition: `_survivor_is_hold_for_owner` compares the survivor by "
        f"EXACT EQUALITY against the PERSISTED pair, so a survivor naming a hand-written option "
        f"matches neither and a genuine owner HOLD becomes unclassifiable (the T-12150 r8 input).\n"
        f"NOTHING WAS SPENT: this refusal fired BEFORE any auditor invocation — no auditor call, no "
        f"round, R unchanged, no `external_audit_completed` row.\n"
        f"Re-run with the two fixed constants (a file is the ergonomic form):\n"
        f"  yitc-v2 audit consult ... -f <a two-line file carrying AUTO_CONSULT_PROCEED_OPTION then "
        f"AUTO_CONSULT_HOLD_OPTION>\n"
        f"The delta framing lives in the PROMPT OVERLAY (rule 4), never in the option texts — there "
        f"is nothing a hand-written option can say that the overlay does not already carry."
    )


def consult_episode_scan(rows, target_id, consult_key, *, CONSULT_TERMINAL_OUTCOMES) -> dict:
    """Rule 1 — the `{open_episode, round_in_flight, highest_n}` scan `consult_allocate_episode`
    takes, read off the JOURNAL rather than off the record.

    THE CARRIER IS THE JOURNAL, DELIBERATELY (rule 9's gate-trial F4: «the postcheck fold must never
    read a rewritable file»). The canonical record is overwritten in place by the next adjudication
    on the same (target, key) — that is the very defect T-11840 measured — so an ordinal derived
    from it would be re-derivable to a DIFFERENT value after an overwrite. The
    `external_audit_completed` rows are append-only, so `highest_n` computed from them is monotone by
    construction.

    `round_in_flight` reads the pairing rule 1 needs for `episode-busy`: an `audit_prompt_sent` for
    this key with no `external_audit_completed` after it means a round of the open episode is
    mid-auditor-call. Pure f(rows)."""
    stage = f"consult-{consult_key}"
    highest_n, open_episode, open_outcome = 0, None, None
    sent, completed = 0, 0
    for row in rows or ():
        if not isinstance(row, dict):
            continue
        data = row.get("data")
        if not isinstance(data, dict) or data.get("stage") != stage:
            continue
        if data.get("target_id") != target_id:
            continue
        etype = row.get("type")
        if etype == "audit_prompt_sent":
            sent += 1
            continue
        if etype != "external_audit_completed":
            continue
        completed += 1
        eid = data.get("episode_id")
        n = None
        if isinstance(eid, str) and "/" in eid:
            tail = eid.rsplit("/", 1)[-1]
            if tail.isdigit():
                n = int(tail)
        if n is None:
            continue
        if n >= highest_n:
            highest_n = n
            open_outcome = data.get("outcome")
            open_episode = n
    # An episode whose LAST recorded round ended on a terminal outcome is CLOSED; anything else (an
    # ordinary hold, a first malformed round awaiting its one re-run) leaves it OPEN to be joined.
    if open_outcome in CONSULT_TERMINAL_OUTCOMES:
        open_episode = None
    return {"open_episode": open_episode, "round_in_flight": sent > completed,
            "highest_n": highest_n, "last_outcome": open_outcome}


def consult_journal_state(target_id, consult_key, *, events_path, _iter_events, consult_episode_scan) -> dict:
    """The ONE journal fold a consult adjudication takes — the rows, and the rule-1 episode scan
    computed from them.

    ONE FOLD PER INVOCATION, deliberately (SPEC-0190 rule 10). Three things downstream want journal
    rows — the episode scan, the escape dedupe and the successor lookup — and the answer to «cache
    this?» for a composed seam is «one request-scoped read at the wiring site», never N caches. This
    IS that wiring site: it reads once and hands the rows on.

    IT IS ALSO THE ENGINE'S ONE NAMED JOURNAL READER, which is what makes it drivable by the
    SPEC-0190 rule-4 segment-awareness census. `_consult_adjudicate` is a top-level verb — driving it
    would invoke an external auditor and write governed artifacts — so folding the read into a
    verb-shaped function would have left a content reader that could not be exercised. Extracted
    here, the read is a pure f(rows) an identity probe can compare across segmentations.

    The reader is INJECTED and the host passes `cli._iter_events`, which folds the SEGMENT SET: an
    episode ordinal computed off the live segment alone would RESET after rotation and re-allocate an
    `n` an archived row already used — the B8 collision, arriving silently and only once the journal
    grew."""
    rows = list(_iter_events(events_path))
    return {"rows": rows, "scan": consult_episode_scan(rows, target_id, consult_key)}


def consult_episode_ended_refusal(target_id, consult_key, scan, prior, *, CONSULT_TERMINAL_OUTCOMES) -> "str | None":
    """Rule 4 — the PRE-AUDITOR `episode-ended` refusal: a third retest, or any further call, inside
    an episode that already reached a terminal outcome.

    Like `hand-framed-options` it allocates NOTHING (trial cycle-5 C5.2): no episode, no round, R
    unchanged, no `external_audit_completed` row. A NEW episode is opened by an explicit owner action
    or a new basis (rule 1), and both arrive as a call that this scan sees no OPEN episode for — so
    this refusal cannot strand a subject that legitimately moved on. Pure f(scan, record)."""
    if scan.get("open_episode") is not None:
        return None
    prior = prior if isinstance(prior, dict) else {}
    # TWO SOURCES, and the refusal fires on EITHER — fail-closed by construction.
    #
    # The JOURNAL is rule 9's durable carrier and is the authority whenever it has rows for this key:
    # it is append-only, so a terminal recorded there cannot be edited away by the next adjudication.
    # But it is not always populated for a key the RECORD already describes — a rotated-away segment,
    # or a record written by a producer whose row this fold has not reached — and in that state a
    # journal-only reader answers «no episode has ended here» about an episode that demonstrably has.
    # That answer is wrong in the ADMITTING direction, which is the direction this refusal exists to
    # close, so the prior record's OWN recorded outcome is read beside it. The caller has already
    # scoped `prior` to the SAME basis (a new basis opens a new episode and passes None), so this can
    # never refuse a subject that legitimately moved on.
    last = scan.get("last_outcome") or prior.get("outcome")
    if last not in CONSULT_TERMINAL_OUTCOMES:
        return None                      # no episode has ended here — this call opens n+1
    open_ids = [i for i in (prior.get("open_ids") or ()) if isinstance(i, str)]
    reason = prior.get("terminal_reason")
    route = ("park the card with a successor carrier as its `return_trigger`, close it `wont-do`, or "
             "authorize a re-open (a NEW episode n+1)")
    return (
        f"audit consult refused ({CONSULT_REFUSAL_EPISODE_ENDED}): the ceiling episode for "
        f"{target_id} {consult_key} already ENDED (`outcome: {last}`"
        + (f", `terminal_reason: {reason}`" if reason else "") + ")."
        + (f" Open ids at the terminal: {', '.join(open_ids)}." if open_ids else "")
        + f" SPEC-0200 rule 4 bounds an episode at 1 baseline + 1 malformed re-run + 2 retests, and "
          f"every terminal ENDS it — no further auditor call is admitted inside it. NOTHING WAS "
          f"SPENT: this refusal fired BEFORE any auditor invocation (no round, R unchanged, no "
          f"`external_audit_completed` row).\nThe route is the OWNER's, per rule 7: {route}. An "
          f"explicit owner action allocates episode n+1 with a FRESH baseline; nothing else opens one."
    )


def consult_opens_next_episode(prior_ended, *, basis_moved, reaudit_after_close,
                               owner_reopen) -> bool:
    """Rule 1 — the EPISODE BOUNDARY, as a named pure predicate: does this call open episode n+1?

    Rule 1 states it as a CONJUNCTION: «n+1 needs a terminal AND a boundary: a moved basis, or an
    explicit owner action, of which `--reaudit-after-close` is one rule 1 names outright». The
    conjunction lived inline in `_consult_adjudicate`; naming it here puts it beside its siblings
    (`consult_episode_transition`, `consult_episode_ended_refusal`) and makes the boundary drivable
    by a probe — the expression it replaces could only be exercised by running the whole engine.

    THE THIRD DISJUNCT (T-12234) is the OTHER explicit owner action rule 7 already promises for a
    TASK target — «an owner-authorized PROCEED / re-open (a NEW episode, n+1, rule 1)» — which no
    verb reached. Rule 7 named it; `--reaudit-after-close` was the only boundary the code carried, so
    three finished, audited builds ended a terminal episode with no verb able to continue them
    (T-12225 open-ids-at-r2, T-12220 malformed-exhausted, T-12219 a converged PROCEED — 2026-09-07).

    ONE PREDICATE COVERS ALL THREE SHAPES, and that is a measurement rather than a convenience:
    `CONSULT_TERMINAL_OUTCOMES` is rule 1's «ONE exhaustive set», and it holds `proceed`,
    `owner-held` and `terminal` alike — so `prior_ended` reads the same for a converged PROCEED as
    for a HOLD over open ids, and a re-open that treated them differently would be splitting a state
    the contract does not split. The owner GATE (who may pass it, and on what target) is
    `consult_reopen_refusal`'s, deliberately NOT this predicate's: this one answers only «is this a
    boundary?». Pure f(args)."""
    if not prior_ended:
        return False                      # nothing has ended — a boundary opens nothing
    return bool(basis_moved or reaudit_after_close or owner_reopen)


def consult_episode_is_terminal(record, *, CONSULT_TERMINAL_OUTCOMES) -> bool:
    """Rule 1/4 — has this key's CURRENT episode ENDED? Pure f(record).

    The exact sibling of `consult_plan_reset_admitted`, and shaped like it on purpose: one pure read
    of the canonical record's own `outcome` against the ONE exhaustive terminal set. It takes the
    RECORD rather than a path because the caller has already read it — cmd_audit reads that YAML once
    at its ceiling seam and passes the SAME object to both the ceiling guard and the basis arm, which
    is the «one request-scoped read at the wiring site» answer (SPEC-0190 rule 10), not N reads.

    FAIL-CLOSED on a record that is absent, unreadable or carries no `outcome`: a pre-contract record
    proves no terminal, and the direction that matters is not admitting an owner grant on a state
    nobody recorded."""
    record = record if isinstance(record, dict) else {}
    return record.get("outcome") in CONSULT_TERMINAL_OUTCOMES


def consult_episode_busy_refusal(target_id, consult_key, scan, *, consult_episode_id) -> "str | None":
    """Rule 1 — the PRE-AUDITOR `episode-busy` refusal: another round of this episode is in flight.

    The serialized pre-call transition (R2.4) admits exactly three outcomes, and this is the third:
    a call that finds an OPEN episode with a round already mid-flight is REFUSED rather than allowed
    to become a second concurrent round — two rounds adjudicating the same open set would each
    write the record the other read. It NEVER allocates a second episode. Pure f(scan)."""
    # `open_episode` is NOT required. At ROUND 0 no completion row exists yet, so the episode is not
    # yet "open" by the scan's own reading — and that is exactly the case VP28 names: two producers
    # calling concurrently with no open episode must yield ONE episode, the second refused busy while
    # round 0 is in flight. Requiring an open episode here would let the second allocate a rival n+1.
    if not scan.get("round_in_flight"):
        return None
    return (
        f"audit consult refused ({CONSULT_REFUSAL_EPISODE_BUSY}): a round of the ceiling episode "
        f"{consult_episode_id(target_id, consult_key, scan.get('open_episode') or '?')} is already "
        f"in flight (an `audit_prompt_sent` with no completion recorded after it). SPEC-0200 rule 1 "
        f"serializes the pre-call transition: a second concurrent round would adjudicate the same "
        f"open set and each would overwrite the record the other read. NOTHING WAS SPENT: no "
        f"auditor call, no round, R unchanged, no episode allocated. Wait for the in-flight round to "
        f"record its outcome, then re-run — this call will JOIN the episode as its next round."
    )


def consult_sticky_hold_open_ids(record) -> list:
    """T-11840, RE-KEYED (rule 7) — the UNRESOLVED id set a recorded HOLD rests on.

    THE RE-KEY, and why it is not a refinement of the old key. T-11840 made a ceiling HOLD sticky by
    keying the preserved record on the SUBJECT FINGERPRINT: a re-roll on an unchanged subject found
    the prior hold and was refused. That was right about the disease (SPEC-0124's ESCALATE is
    terminal-to-owner, not terminal-until-lucky) and wrong about the key. A fingerprint answers «is
    this the same subject?», but what a HOLD is ABOUT is a set of unresolved defects — so the old
    key was simultaneously too tight (any commit, including one that resolved every open id, minted a
    fresh fingerprint and cleared the hold) and too loose (a subject that did not change but whose
    ids were closed by an owner action still read as held).

    Rule 7 states the correct key: the hold «is cleared ONLY by a recorded resolution of those ids
    (a later retest closing them) or by an explicit owner action — never by the mere absence of
    `findings_complete` on a retest (that field does not exist at round k >= 1)». So the key IS the
    id set. Pure f(record)."""
    record = record if isinstance(record, dict) else {}
    ids = [i for i in (record.get("open_ids") or ()) if isinstance(i, str) and i.strip()]
    return sorted(set(ids))


def consult_hold_is_sticky(prior_hold, current, *, consult_sticky_hold_open_ids) -> bool:
    """T-11840 re-keyed — does a preserved HOLD still bind, given the CURRENT canonical record?

    STICKY iff the ids the hold rested on are still unresolved. `current` is the canonical record as
    it stands now (or None): an id is cleared by a recorded `resolutions[]` closure, and the whole
    hold is cleared by an explicit owner action — which, per rule 1, arrives as a NEW EPISODE, so a
    current record whose `episode_id` ordinal is higher than the hold's is by construction past it.

    FAIL-CLOSED on a LEGACY hold (one carrying no `open_ids` — every hold preserved before this
    contract): with no id set to reason about, the hold binds. That is deliberately the same answer
    the pre-C3 fingerprint-keyed code gave, so a hold drawn under the old rule is not silently
    released by the new one. Pure f(records)."""
    if not isinstance(prior_hold, dict):
        return False
    held_ids = consult_sticky_hold_open_ids(prior_hold)
    if not held_ids:
        # No id set recorded: either a legacy hold (bind — fail-closed) or a row-16 owner-held
        # terminal over an EMPTY open set, which is likewise terminal-to-owner until an owner acts.
        return True

    def _ordinal(rec):
        eid = (rec or {}).get("episode_id")
        if isinstance(eid, str) and "/" in eid:
            tail = eid.rsplit("/", 1)[-1]
            if tail.isdigit():
                return int(tail)
        return None

    current = current if isinstance(current, dict) else {}
    held_n, cur_n = _ordinal(prior_hold), _ordinal(current)
    if held_n is not None and cur_n is not None and cur_n > held_n:
        return False                      # an explicit owner action opened a later episode (rule 1)
    closed = {r.get("id") for r in (current.get("resolutions") or ())
              if isinstance(r, dict) and r.get("resolution") in CONSULT_RESOLVED_VALUES}
    return bool([i for i in held_ids if i not in closed])


def consult_plan_reset_admitted(record, *, CONSULT_OUTCOME_PROCEED) -> bool:
    """Rule 7, PLAN-gate arm — may `plan stage <NEXT> --owner-reset` / `audit post --plan
    --owner-reset` proceed on this gate?

    ADMITTED only when the consult record's CURRENT episode ended `outcome: proceed` (row 18). Rule 7
    is explicit that a plan gate has no other exit: «a plan has NO park, `return_trigger` or
    `wont-do`: it simply STAYS at its current FSM stage ... its ceiling closes ONLY through a
    consult-governed `--owner-reset` PROCEED on the SAME gate ... the explicit owner action opens a
    NEW episode (round 0, n+1) on that gate, and THAT episode's PROCEED is the basis the reset
    verifies». So a row-15 terminal, a row-16 owner-held and a non-admissible terminal all read
    False, and stay False until a LATER episode records a PROCEED.

    FAIL-CLOSED on a record carrying no `outcome` at all — a pre-contract record proves no PROCEED.
    Pure f(record)."""
    record = record if isinstance(record, dict) else {}
    return record.get("outcome") == CONSULT_OUTCOME_PROCEED


def consult_terminal_owner_route(record, *, is_plan, target_id, consult_key, consult_sticky_hold_open_ids) -> str:
    """Rule 7 — the owner route a terminal opens, SPLIT BY TARGET KIND.

    The MACHINE is carrier-neutral: rows 0-second / 15 / 16 and the pre-matrix terminal all end the
    episode identically (B9). What differs is what the OWNER can then do, and the two vocabularies do
    not overlap — a plan has no park, no `return_trigger` and no `wont-do`; a task has no FSM stage
    to stay at. Emitting the wrong one is not a cosmetic slip: it names an action the target's own
    FSM cannot perform, which is how a blocked session ends up hand-editing state. Pure f(record)."""
    record = record if isinstance(record, dict) else {}
    open_ids = consult_sticky_hold_open_ids(record)
    ids = (f" naming the open ids {', '.join(open_ids)}" if open_ids
           else " over an EMPTY open set (a value/design judgement)")
    if is_plan:
        return (
            f"OWNER ROUTE (plan-gate target, SPEC-0200 rule 7). The plan {target_id} STAYS at its "
            f"current FSM stage — the {consult_key} gate transition does not fire, and the engine "
            f"writes NO task-side field, because a plan HAS none. (The task vocabulary is "
            f"deliberately not repeated here even to deny it: naming an action the target's own FSM "
            f"cannot perform is how a blocked session ends up hand-editing state, and this text is "
            f"read under exactly that pressure.) This episode rests on ONE owner HOLD{ids}. "
            f"`plan stage <NEXT> --owner-reset` "
            f"(or `audit post --plan {target_id} --owner-reset` for `finalization`) is REFUSED until "
            f"a NEW episode on the SAME gate ends PROCEED. The explicit owner action opens that "
            f"episode (round 0, n+1); the plan's only other exit is its own FSM terminal "
            f"(`plan stage rejected|cancelled --reason`).")
    return (
        f"OWNER ROUTE (task target, SPEC-0200 rule 7). {target_id} rests on ONE owner HOLD{ids}, and "
        f"the engine writes NO plan-side transition. The explicit owner action is one of: PARK the "
        f"card with a successor carrier recorded as its `return_trigger` "
        f"(`task update {target_id} --status parked --reason ... --return-trigger ...`); close it "
        f"`wont-do`; or authorize a re-open, which is a NEW episode n+1 with a FRESH baseline. The "
        f"task FSM carries all three (QUEUE §State transitions).")


def _consult_adjudicate(target_id, consult_key, is_plan, options, prompt, prompt_excerpt,
                        prior_passes, basis_fp, provider, model, effort, *,
                        _invoke_auditor, _parse_consult_result, _strip_degenerate_tail,
                        _append_event, _utc_now_iso, _plan_content_hash, _auto_rebuild_graph,
                        write_text_atomic, _die, REPO_ROOT, reaudit_after_close: bool = False,
                        _with_repo_lock=None, _iter_events=None, events_path=None,
                        _file_followup=None, _parse_audit_verdict=None, lens=None,
                        scope_cuts=None, owner_rulings=None, owner_reopen: str | None = None,
                        _capacity_retry_hint=None, _resolve_audit_reserve=None,   # T-12606
                        _rebuild_prompt_with_delta=None, AUDIT_INSPECTION_CONSULT_CLASS, CONSULT_ADJUDICATION_RECORD_FIELDS, CONSULT_NO_ANSWER_ROUTE_UNAVAILABLE, CONSULT_OUTCOME_NO_ANSWER, CONSULT_OUTCOME_PROCEED, CONSULT_ROUND_KIND_BASELINE, CONSULT_TERMINAL_OUTCOMES, _audit_duration_ms, _capacity_hint_via, auditor_failure_cause, consult_adjudicate_round, consult_allocate_episode, consult_emit_escape_deviations, consult_episode_busy_refusal, consult_episode_ended_refusal, consult_episode_row_fields, consult_file_successors, consult_hand_framed_refusal, consult_journal_state, consult_offered_pair, consult_opens_next_episode, consult_packet_assemble, consult_packet_max_bytes, consult_prompt_overlay, consult_round_kind, consult_round_withdrawn, consult_terminal_owner_route, findings_complete_declared, inspection, invoke_auditor_tiered, is_no_data_verdict, observe, stamp_auditor_verdict, state):
    """Shared consult-adjudication CORE (extracted T-9683), and — since T-12182 (SPEC-0200 card C3) —
    the LIVE post-ceiling contract engine. Given a fully PREPARED consult prompt + metadata: allocate
    or join the ceiling EPISODE, apply the ROUND-AWARE prompt overlay, invoke the auditor, adjudicate
    the response through the C2 core, persist the record and emit the instrumented
    `external_audit_completed` row. RETURNS (audit_dict, survivors_int, recommendation, audit_path).

    The CALLER owns target-resolution + prompt-build + the human print/exit policy. Reused by BOTH
    `cmd_audit_consult` (the interactive/manual verb) AND `cmd_audit`'s dispatched-worker AUTO-consult
    (T-9683) — so the headless auto-consult IS the EXISTING consult engine, NOT a parallel writer
    (CHARTER §P1 F1).

    WHY THE CONTRACT LIVES HERE AND NOT IN THE THREE PROMPT BUILDERS (SPEC-0200 rule 9). This is the
    ONE seam every producer passes through — the task consult verb, the dispatched-worker
    auto-consult, and the plan-gate producer in `bin/lib/plan.py`. Rule 9 states the consequence as a
    property rather than a request: «this contract binds the engine, so both producers comply by
    construction». The AC5 producer-parity e2e is what proves it: the two producers are run over one
    fixture with only the auditor subprocess mocked, and their records, terminations, successor
    filings and eleven-field rows are compared field by field.

    THE FIVE NEW INJECTIONS, and why each is injected rather than resolved here:
      * `_with_repo_lock` — rule 1's serialized pre-call transition rides the repo's EXISTING
        cross-session lock. It is INJECTED because this module must not itself call an flock
        primitive: `consult_allocate_episode`'s own contract says so, and the C2 AC5 probe pins it
        with an AST check over this file. Injection is the mechanism, not the style.
      * `_iter_events` + `events_path` — the escape dedupe, the episode scan and the successor
        lookup all read the JOURNAL, and they must read the SEGMENT SET (SPEC-0190 rule 4). The host
        passes `cli._iter_events`; a local re-implementation would read the live segment only and
        re-emit every deduped deviation the moment an archive segment appeared. `events_path` is
        passed EXPLICITLY beside it so the dedupe reads and the emit writes THE SAME journal — a
        dedupe that reads A and writes B degrades silently to no dedupe at all.
      * `_file_followup` — rule 8's successor carrier is the EXISTING `followup add` primitive
        (SPEC-0095); injecting the filer keeps this module free of a second capture path.
      * `_parse_audit_verdict` — the C1 transcriber. `_parse_consult_result` reads SURVIVORS and
        carries no findings at all, so the per-finding contract rule 3 judges arrives through the C1
        parser. Injected for parity with every other parse dependency here.
      * `lens` — the criterion set rule 3 VALIDATES `criterion_ref` against: a task's own acceptance
        criterion ids, or a plan gate's `<gate>:<criterion>` lens. The engine cannot derive it (it
        holds no card and no gate policy), and guessing it would turn rule 3's validation into a
        presence check — every invented criterion would read blocking.
      * `scope_cuts` — rule 4 row 22's cut map, read off the SAME card the lens is read from
        (`consult_scope_cuts`): the criteria a recorded owner decision moved to another card. Passed
        beside the lens for the same reason — the engine holds no card — and EMPTY for a plan gate
        (no card, hence no cut), which is the fail-closed direction: no id is ever withdrawn.
      * `owner_rulings` — rule 4 row 23's ruling map, read off the SAME card by the sibling reader
        (`consult_owner_rulings`): the open FINDING IDS a recorded owner ruling put out of this
        card's subject. The producers pass it with the REAL `task_exists` resolver bound, so an id
        naming no filed receiving card withdraws nothing. EMPTY for a plan gate, same fail-closed
        direction as the cut map above.

    FAIL-CLOSED ON A MISSING INJECTION. A caller that omits them gets a refusal, never a quiet
    fall-through to the pre-C3 path. The pre-C3 path cannot persist `offered_options`, so the
    re-keyed `_survivor_is_hold_for_owner` would stop recognising owner-held HOLDs against records it
    silently produced — the T-12150 r8 failure, re-introduced invisibly. There is one atomically
    switched contract, or a refusal."""
    import yaml
    audit_path = REPO_ROOT / "decisions" / f"{target_id}-audit-consult-{consult_key}.yaml"

    # ── SPEC-0200 (T-12182) — the LIVE contract, PRE-AUDITOR half ────────────────────────────────
    # Everything in this block runs BEFORE `_invoke_auditor`, and every refusal in it costs NOTHING:
    # no auditor call, no round, R unchanged, no matrix row, no `external_audit_completed` row
    # (rule 9's C4.2). The ordering is rule 1's and is load-bearing — a refusal that fired after the
    # call would burn a round to report something computable from durable state and argv.
    if not CONSULT_CONTRACT_ACTIVE:
        _die(CONSULT_PARTIAL_SWITCH_REFUSAL)                                   # AC7 atomicity seam
    _missing = [n for n, v in (("_with_repo_lock", _with_repo_lock), ("_iter_events", _iter_events),
                               ("events_path", events_path),
                               ("_parse_audit_verdict", _parse_audit_verdict)) if v is None]
    if _missing:
        _die(f"consult engine mis-wired: SPEC-0200 injection(s) {', '.join(_missing)} missing. "
             f"Refusing rather than adjudicating on the pre-C3 path — that path persists no "
             f"`offered_options`, so the re-keyed owner-held predicate would stop recognising a "
             f"genuine owner HOLD against the records it produced (SPEC-0200 rule 7 / the T-12150 "
             f"r8 failure input). Wire the engine or do not call it.")

    _prior = None
    if audit_path.exists():
        _loaded = state.load_str(audit_path.read_text(encoding="utf-8"))
        _prior = _loaded if isinstance(_loaded, dict) else None
    # THE EPISODE BOUNDARY IS A CONJUNCTION, and rule 1 states both halves. Getting either half
    # alone wrong breaks a different, real path, and this build got each wrong in turn.
    #
    # HALF ONE — AN OPEN EPISODE SPANS SUBJECT REVISIONS. Rule 1 carries the baseline revision «as
    # its own field (`baseline_revision`), not as part of the id», and rule 2 says outright that «an
    # episode may span several subject revisions and the [malformed] budget must not grow with them».
    # Rule 4's retest judges «any regression THE FIX INTRODUCED» — and a fix CHANGES THE SUBJECT. So
    # a moved basis must NOT end a live episode: if it did, every round after a fix leg would freeze
    # a fresh baseline and R would never advance — the «new set every round» outcome rule 10 retires,
    # reintroduced through the episode boundary. (Caught by the AC5 producer-parity e2e once its auto
    # arm drove `cmd_audit` for real: the auto producer sat at round 0 across three calls.)
    #
    # HALF TWO — ONCE AN EPISODE HAS ENDED, A NEW BASIS OPENS THE NEXT ONE. Rule 1: «n+2 exists only
    # after a durable owner boundary (rule 7) OR A NEW BASIS closed episode n — so two episodes on
    # the SAME basis (a row-16 terminal reopened by the owner without a code change) never collide.»
    # This is also T-11840's landed contract, which keys the preserved HOLD on the subject
    # fingerprint precisely so that «the fix blocks the re-roll, not the legitimate continuation»: a
    # genuinely reworked subject after a terminal converges through the ordinary path.
    #
    # So: a TERMINAL alone does not open anything (a plain re-run on the same subject is refused
    # `episode-ended` — SPEC-0124 §ESCALATE is terminal-to-owner, not terminal-until-lucky), and a
    # NEW BASIS alone does not end anything. n+1 needs a terminal AND a boundary: a moved basis, or
    # an explicit owner action, of which `--reaudit-after-close` is one rule 1 names outright.
    _prior_outcome = (_prior or {}).get("outcome")
    _prior_ended = _prior_outcome in CONSULT_TERMINAL_OUTCOMES
    _prior_revision = (_prior or {}).get("baseline_revision")
    _basis_moved = bool(_prior) and _prior_revision is not None and _prior_revision != basis_fp
    # T-12234 — the boundary is now the NAMED predicate `consult_opens_next_episode`, with rule 7's
    # OTHER explicit owner action (`audit consult --reopen`, the owner grant) as its third disjunct.
    # The conjunction itself is unchanged; extracting it is what lets a probe drive the boundary
    # without running the whole engine, and the owner GATE on who may pass `owner_reopen` is
    # `consult_reopen_refusal`'s, taken by the caller BEFORE this point.
    _opens_next = consult_opens_next_episode(
        _prior_ended, basis_moved=_basis_moved, reaudit_after_close=reaudit_after_close,
        owner_reopen=owner_reopen)
    _prior_episode = None if (not _prior or _opens_next) else _prior

    _state = consult_journal_state(target_id, consult_key, events_path=events_path,
                                   _iter_events=_iter_events)
    _rows, _scan = _state["rows"], _state["scan"]
    # `episode-ended` fires only when the ended episode is NOT succeeded by a boundary — i.e. a plain
    # re-run on the SAME subject with no owner action. A call that opens n+1 (a moved basis, or
    # `--reaudit-after-close`) is never refused by the terminal of the episode it succeeds.
    #
    # This one is decided OUTSIDE the lock on purpose: it reads the prior RECORD's terminal and this
    # call's own basis, neither of which another producer can change under us. `episode-busy` is the
    # opposite case and is decided INSIDE the critical section below, where it belongs.
    if not _opens_next:
        _refusal = consult_episode_ended_refusal(target_id, consult_key, _scan, _prior)
        if _refusal:
            _die(_refusal)

    # Rule 7 — hand-framed options are refused at a BASELINE-BEARING consult. Scoped exactly there:
    # the on-demand below-ceiling fork picker (T-9684) submits genuine session-authored VARIANTS and
    # is not a ceiling episode at all, so it keeps its own option semantics untouched.
    _baseline_bearing = consult_key in ("pre", "post") or is_plan
    if _baseline_bearing:
        _hand = consult_hand_framed_refusal(target_id, consult_key, options)
        if _hand:
            _die(_hand)

    _round_kind = consult_round_kind(_prior_episode)
    # `highest_n` is the JOURNAL's (rule 1: «one more than the highest attempt already recorded for
    # that key on the journal» — the append-only carrier), RAISED by any higher ordinal the prior
    # RECORD carries. The raise is the fail-closed direction and it is not hypothetical: the journal
    # fold can legitimately not see a row the record describes — a rotated-away segment, or a
    # concurrently-written row not yet folded — and taking the journal's answer alone there would
    # RE-ALLOCATE an ordinal an existing episode already used. That is the B8 collision, arriving
    # silently. Reusing an ordinal is unrecoverable (two episodes share an id forever); skipping one
    # costs nothing, since the ordinal is an identity, not a count.
    _prior_n = 0
    _prior_eid = (_prior or {}).get("episode_id")
    if isinstance(_prior_eid, str) and "/" in _prior_eid:
        _tail = _prior_eid.rsplit("/", 1)[-1]
        if _tail.isdigit():
            _prior_n = int(_tail)
    # THE SCAN RE-FOLDS INSIDE THE LOCK, and the allocation is made DURABLE inside it too.
    #
    # `consult_allocate_episode`'s own contract spells out why, and the first implementation defeated
    # it: it passed a lambda that closed over a scan taken BEFORE the lock, so the critical section
    # re-read nothing and two concurrent producers both decided from the same pre-lock state — the
    # exact B8 collision the helper exists to prevent, with the lock present and doing nothing.
    # Reading `consult_journal_state` HERE means the second entrant folds a journal that already
    # carries the first's marker.
    #
    # AND THE MARKER IS WRITTEN IN THE SAME SECTION. `audit_prompt_sent` is this key's durable
    # "a round is in flight" record — the row `consult_episode_scan` pairs against completions — so
    # emitting it after the lock would leave precisely the window rule 1 closes: at ROUND 0 there is
    # no completion row yet, so a concurrent second call would see no open episode, not be refused
    # busy, and allocate a SECOND n+1. VP28 names that case outright. Emitted through `commit`, it is
    # durable before the lock is released.
    #
    # `episode-busy` is therefore decided from the RE-FOLDED state, on `round_in_flight` alone: at
    # round 0 there is no open episode to qualify it, which is the whole point.
    # Rule 4 — the ROUND-AWARE overlay. Round 0 carries the exhaustive-survey clause and the
    # `findings_complete` ask; round k >= 1 carries the delta overlay and NO whole-subject directive
    # anywhere in the ASSEMBLED prompt. This is the one place the two prompts diverge, so the AC1
    # differential greps `prompt` as assembled here.
    #
    # ASSEMBLED HERE, BEFORE THE ALLOCATION LOCK (moved by T-12233), because `audit_prompt_sent` is
    # emitted INSIDE that lock and now carries the packet MEASUREMENT — a measurement taken after
    # the emit would describe a packet the row does not. The overlay depends only on state computed
    # above (`_prior_episode`, `_round_kind`, `basis_fp`, `lens`, `is_plan`), none of which the
    # allocation touches, so the move is a pure reordering.
    _overlay = ""
    if _baseline_bearing:
        _overlay = consult_prompt_overlay(_prior_episode, round_kind=_round_kind,
                                          revision=basis_fp, lens=lens, is_plan=is_plan)

    # ── T-12233 — the SOFT, RECORDED packet bound (SPEC-0193 performance) ────────────────────────
    # It NEVER truncates and NEVER refuses a round. Over the bound it chooses between two scopes
    # that admit the SAME judgement: the FULL subject diff, or the DELTA SINCE THE BASELINE
    # REVISION. At a RETEST those are equivalent by SPEC-0200 rule 4's own terms — a retest judges
    # ONLY each open blocking id and any regression the fix INTRODUCED, and rule 4 forbids a
    # whole-subject survey there — so the delta IS the rule-4 correct scope and the full diff is the
    # over-inclusive one. ROUND 0 IS NEVER DELTA-SCOPED (rule 2 requires it to survey the whole
    # subject), which the `round_kind == retest` guard delivers by construction. Still over the
    # bound after that — an oversized delta, or a rule-4 overlay that alone exceeds it — and the
    # packet is sent WHOLE and UNTRUNCATED with `packet_over_bound: true` and the measured size:
    # cutting the diff is exactly the verdict-changing input a performance key may not have, so an
    # honest VISIBLE over-bound send beats a silently narrowed one.
    prompt, _packet_bytes, _packet_scope, _packet_over_bound = consult_packet_assemble(
        prompt, _overlay, round_kind=_round_kind, bound=consult_packet_max_bytes(),
        baseline_revision=(_prior_episode or {}).get("baseline_revision"),
        rebuild_delta=_rebuild_prompt_with_delta)
    prompt_excerpt = prompt[:200]   # the excerpt describes the packet ACTUALLY sent

    _prompt_data = {
        "stage": f"consult-{consult_key}", "model": model, "provider": provider,
        "tier": "full", "prompt_excerpt": prompt_excerpt,
        "target_kind": "consult", "target_id": target_id,
        # T-12233 — every branch records its MEASURED size, so the outcome is checkable from the
        # row alone rather than re-derived. `packet_scope` is the CLOSED two-value enum.
        "packet_bytes": _packet_bytes,
        "packet_scope": _packet_scope,
        "packet_over_bound": _packet_over_bound,
    }

    def _scan_locked():
        st = consult_journal_state(target_id, consult_key, events_path=events_path,
                                   _iter_events=_iter_events)["scan"]
        return {"open_episode": st["open_episode"], "round_in_flight": st["round_in_flight"],
                "highest_n": max(st["highest_n"], _prior_n)}

    def _commit_allocation(decision):
        if decision["decision"] == "episode-busy":
            return                      # nothing is allocated and no marker is written
        _append_event("audit_prompt_sent", (None if is_plan else target_id), _prompt_data)

    _episode = consult_allocate_episode(
        target_id, consult_key, scan=_scan_locked, commit=_commit_allocation,
        _with_repo_lock=_with_repo_lock, ref=REPO_ROOT)
    if _episode["decision"] == "episode-busy":
        _die(consult_episode_busy_refusal(target_id, consult_key,
                                          {"round_in_flight": True,
                                           "open_episode": _episode["n"]}))
    _episode_id = _episode["episode_id"]
    _offered = consult_offered_pair() if _baseline_bearing else list(options)

    print(f"# Invoking external auditor: {provider}/{model} (full) — ceiling-convergence consult "
          f"{target_id} {consult_key} ({len(options)} options)...", file=sys.stderr)
    if _baseline_bearing:
        print(f"# SPEC-0200 episode {_episode_id} — round_kind={_round_kind} "
              f"(decision={_episode['decision']}); the prompt carries the "
              f"{'whole-subject BASELINE survey' if _round_kind == CONSULT_ROUND_KIND_BASELINE else 'DELTA retest overlay (no whole-subject survey)'}.",
              file=sys.stderr)
    # NOTE: `audit_prompt_sent` was already emitted INSIDE the allocation's critical section above —
    # it is this key's in-flight marker, and a second emit here would double-count the pairing
    # `consult_episode_scan` reads.
    _consult_t0 = time.monotonic()   # T-12007 — the anchor for this path's completion duration_ms
    # read_only=True (T-9576): same auditor-never-writes pin as the cmd_audit lifecycle path.
    # T-11149: INSPECTION class. This SHARED helper is the auditor surface for BOTH the task
    # convergence consult (`cmd_audit_consult`) and the plan-gate consult, and both measured rc=124
    # wall ABORTs came through it (T-10149 2026-07-06, T-11063 2026-08-13). Marking it once is
    # correct rather than a widening: both consult shapes are inside the n=1278 fold the 540s budget
    # was derived from. The plan-gate AUDIT calls in plan.py are a different surface and stay ROUTINE.
    # T-12233 (a2) — LAUNCH / TRANSPORT failures are normalized HERE, at the one consult call site,
    # to the SAME shape the timeout path already returns. `run_auditor_subprocess` RE-RAISES a
    # FileNotFoundError (missing auditor binary) and any other post-spawn failure after reaping the
    # group, so before this such a failure never reached the classifier at all: it crashed the verb
    # mid-episode, leaving an in-flight `audit_prompt_sent` and NO completion row — an episode no
    # later call could join or end. Normalized, it becomes an ordinary no-answer round WITH a
    # completion row, and the episode stays joinable. `run_auditor_subprocess` ITSELF IS NOT
    # CHANGED: its other callers rely on the raise, and narrowing the normalization to this call
    # site is what keeps the change in scope. KeyboardInterrupt is deliberately NOT caught — it is
    # not an auditor failure.
    _answered_pair: dict = {}      # T-12606 — INVOCATION-scoped: which pair answered THIS consult
    try:
        rc, stdout, stderr = invoke_auditor_tiered(_invoke_auditor, provider, prompt, model,
                                                   effort=effort, read_only=True,
                                                   consult_class=AUDIT_INSPECTION_CONSULT_CLASS,
                                                   full=True,   # T-12350: a consult is the FULL tier
                                                   _resolve_audit_reserve=_resolve_audit_reserve,   # T-12606
                                                   append_event=_append_event,
                                                   answered_out=_answered_pair,
                                                   iter_events=_iter_events, events_path=events_path)   # T-13109
    except (OSError, subprocess.SubprocessError) as exc:
        rc, stdout, stderr = 124, "", f"{type(exc).__name__}: {exc}"
    if rc != 0:
        parse_notes = auditor_failure_cause(rc, stderr,   # T-12582
                                            capacity_hint=_capacity_hint_via(_capacity_retry_hint, model, provider))   # T-12603
        print(f"# {parse_notes}", file=sys.stderr)
        verdict, survivors, recommendation = "ABORT", [], ""
    else:
        verdict, survivors, recommendation, parse_notes = _parse_consult_result(stdout, options)

    # The auditor's `findings_complete:` declaration for the saved consult record — REPORT-ONLY.
    # T-12141's carried defect list, its consult output-schema ask, and the one-shot completion
    # re-prompt this seam drove were all reverted by T-12168 (owner directive 2026-09-05); the
    # declaration parse survives because the field is additive, harmless, and reused by the
    # narrowed successor in plan `frozen-defect-baseline-at-the-audit-loop-ceiling-d`.
    findings_complete = findings_complete_declared(stdout) if rc == 0 else None

    clean_stdout = _strip_degenerate_tail(stdout)
    if rc == 0 and clean_stdout.strip():
        print(clean_stdout.rstrip())   # the consult payload — the auditor's reasoning

    # Saved verdict: canonical saved-audit schema + structured survivors/recommendation (SPEC-0036
    # §Saved-audit-result extension). survivors are recorded as {option, text} so the basis is
    # human-legible and the owner-reset verifier reads len(survivors)==1.
    survivor_records = [{"option": i, "text": options[i - 1]} for i in survivors]
    # T-9617 (X-0111) — ADOPTED-plan fingerprint. For a TASK PRE consult that converged to exactly ONE
    # survivor, record the fingerprint the plan WILL hash to once the session ADOPTS the recommendation
    # by setting implementation_plan to that surviving option's text (= hash(survivor text), the SAME
    # _plan_content_hash audit-pre/task-execute compute). _consult_basis then GOVERNS the first audit-pre
    # of the adopted (changed) plan — current plan_fingerprint == adopted_fingerprint — instead of the
    # adoption re-staling the basis (which was pinned to the PRE-change plan) and re-burning a ceiling
    # pass. Recorded only for PRE + single-survivor (POST adjudicates a commit SHA, not a plan; a plan
    # gate / non-converged consult has no single adopted plan); None otherwise (additive-optional, the
    # same class as basis_fingerprint / commit).
    # T-12182 (SPEC-0200 rules 7 + 10) — RETIRED ON THE CEILING PATH, and stated as a retirement
    # rather than left to rot into a field that is silently always None.
    #
    # T-9617 records this fingerprint on ONE premise: that the sole survivor IS the plan text the
    # session will adopt, by setting `implementation_plan` to it. Rule 7 removes that premise at a
    # baseline-bearing consult — the offered pair is now the two FIXED constants, so the survivor is
    # «PROCEED … Land it.» or «HOLD FOR OWNER …», never a candidate plan. Computing the hash anyway
    # would write a value that is meaningless AND reads to a later session as an adopted-plan basis.
    #
    # X-0111 IS NOT RE-OPENED BY THIS, which is the question that matters. That incident was: the
    # session adopts the recommendation, the plan's content hash therefore CHANGES, the consult's
    # basis was pinned to the PRE-change plan, and the first audit-pre re-stales it and re-burns a
    # ceiling pass. Every step rests on an adoption happening. At a post-ceiling consult under this
    # contract there is nothing to adopt — the adjudication is PROCEED-or-HOLD over a frozen defect
    # baseline, and the plan is not a candidate the auditor picks between — so the failure mode has
    # no first step. Plan-variant picking still exists and still records nothing here: it is the
    # BELOW-ceiling `audit consult --on-demand` fork (SPEC-0124 §On-demand technical-fork consult),
    # which by T-9684's own design binds to no plan or commit and persists no basis at all.
    #
    # Captured as a deviation before acting, because SPEC-0200 does not mention `adopted_fingerprint`
    # anywhere and this reconciles two contracts rather than applying one:
    # `spec0200-fixed-option-pair-makes-t9617-adopted-fingerprint-inert-on-the-ceiling-path`.
    adopted_fp = (_plan_content_hash(options[survivors[0] - 1])
                  if (not is_plan and consult_key == "pre" and len(survivors) == 1
                      and not _baseline_bearing) else None)
    audit = {
        "target_kind": "consult",
        "target_id": target_id,
        "stage": f"consult-{consult_key}",
        "date": _utc_now_iso()[:10],
        "verdict": verdict,
        "passes": prior_passes,            # the ceiling count this consult triages (NOT a re-audit pass)
        "commit": (basis_fp if (not is_plan and consult_key == "post") else None),
        "consult_for_stage": consult_key,
        "basis_fingerprint": basis_fp,     # p2-F1/INV-2 — exact-match freshness carrier for --owner-reset
        "adopted_fingerprint": adopted_fp,  # T-9617 — fingerprint of the ADOPTED (post-change) plan (PRE single-survivor only)
        "options": options,
        "survivors": survivor_records,
        # Whether the auditor declared its defect list complete (True / False / None = "not
        # stated"). REPORT-ONLY: no gate, verdict or pass count reads it (T-12168).
        "findings_complete": findings_complete,
        "recommendation": recommendation or None,
        "auditor_provider": "external-auditor-full",
        "prompt_excerpt": prompt_excerpt,
        "notes": (f"{parse_notes}\n\n" if parse_notes else "")
                 + f"--- auditor response (consult payload) ---\n{clean_stdout.rstrip()}",
    }
    if not is_plan:
        audit["task"] = target_id          # legacy alias (TASK only) — keeps the graph audit-edge keyed on task:
    if reaudit_after_close:
        audit["reaudit_after_close"] = True   # T-10094 — durable trail: this consult basis is HEAD-pinned
                                              # (post-close rebaseline), mirroring the audit-post marker.

    # ── SPEC-0200 (T-12182) — the LIVE contract, POST-AUDITOR half ───────────────────────────────
    _delta, _episode_row, _withdrawn_now = None, {}, []
    if _baseline_bearing:
        # The per-finding contract arrives through the C1 transcriber. `_parse_consult_result` reads
        # SURVIVORS and carries no findings at all, so without this the matrix would judge an empty
        # survey every round and freeze an empty baseline — the response would be read as compliant
        # and silent. On a nonzero auditor exit the findings are empty by construction and row 0
        # (malformed) is what classifies the round, which is the correct reading of an ABORT.
        _findings = []
        if rc == 0:
            try:
                _, _findings, _ = _parse_audit_verdict(stdout)
            except (ValueError, TypeError):
                _findings = []      # an unparseable body is row 0's business, not an exception's
        _response = {"verdict": verdict, "survivors": survivor_records,
                     "findings": [f for f in (_findings or ()) if isinstance(f, dict)],
                     "findings_complete": findings_complete}
        # T-12233 (d) — THE SEAM. This is the only place that sees the invocation RESULT, so the
        # payload signal is computed here and passed down explicitly rather than re-derived from a
        # second no-data notion. `clean_stdout` is the tail-stripped stdout this path already
        # derives for the record; a blank one means NO PAYLOAD came back, whatever the rc.
        _payload_present = bool(clean_stdout.strip())
        _delta = consult_adjudicate_round(
            _prior_episode, _response, lens=(lens or ()), revision=basis_fp,
            established_at=_utc_now_iso(), offered_options=_offered, episode_id=_episode_id,
            payload_present=_payload_present, scope_cuts=scope_cuts,
            owner_rulings=owner_rulings)

        # Rule 8, first bullet — the ESCAPE accounting, LIVE for the first time. The reader is the
        # injected segment-aware fold and the write goes to the journal it read, so a deviation
        # deduped before rotation stays deduped after it.
        # The emitter is handed THE FOLD ALREADY TAKEN, not a second one — the request-scoped read
        # above serves every consumer in this invocation (SPEC-0190 rule 10). The emitter's own
        # contract is satisfied exactly: it reads rows through the callable it is given and appends
        # to `events_path`, so the dedupe still reads the journal the emit writes.
        _escapes = consult_emit_escape_deviations(
            _delta, episode_id=_episode_id, target_id=target_id, events_path=events_path,
            _iter_events=lambda _p: _rows, _append_event=_append_event)
        # Rule 8, second bullet — successor work for every deferrable, ONCE, keyed by the composite
        # `(episode_id, finding_id)`. Idempotent by construction: the carrier embeds the key, so the
        # next run finds it and files nothing. Skipped (deferrals passed through unfiled) when no
        # filer is wired — a missing carrier must not cost the adjudication.
        if _file_followup is not None:
            _delta["deferrals"] = consult_file_successors(
                _delta, episode_id=_episode_id, target_id=target_id,
                rows=_rows, file_followup=_file_followup)

        audit["offered_options"] = list(_offered)
        audit["baseline_schema"] = CONSULT_BASELINE_SCHEMA   # rule 2's provenance marker
        for _field in CONSULT_ADJUDICATION_RECORD_FIELDS:
            audit[_field] = _delta.get(_field)
        _episode_row = consult_episode_row_fields(_delta, episode_id=_episode_id)
        # T-12248 — the round's WITHDRAWALS, derived here beside the other f(delta) quantities and
        # attached to the payload at the emit on `owner_reopen`'s terms (rationale + the
        # why-the-row-and-not-the-record argument live in `consult_round_withdrawn`'s docstring).
        _withdrawn_now = consult_round_withdrawn(_delta, prior=_prior_episode)
        if _escapes:
            print(f"# SPEC-0200 rule 8: {len(_escapes)} baseline COMPLETENESS FAILURE(s) recorded — "
                  f"{', '.join(e['residual_id'] for e in _escapes)} are NEW blocking findings with "
                  f"causality pre-existing-in-subject, i.e. defects the frozen survey MISSED.",
                  file=sys.stderr)
        # T-12233 (e) — the no-answer operator route. The FIRST says the round cost nothing and is
        # simply re-runnable; the SECOND names the SPEC-0103 §3a auditor-OUTAGE class, and the verb
        # exits nonzero through the ordinary ABORT verdict path so that handling fires unchanged.
        if _delta.get("outcome") == CONSULT_OUTCOME_NO_ANSWER:
            if _delta.get("no_answer_route") == CONSULT_NO_ANSWER_ROUTE_UNAVAILABLE:
                print(f"# {CONSULT_NO_ANSWER_ROUTE_UNAVAILABLE}: the auditor did not answer "
                      f"{_delta.get('no_answer_count')} times in a row — this is an auditor OUTAGE "
                      f"(SPEC-0103 §3a), NOT a verdict on the subject. Episode {_episode_id} is "
                      f"still OPEN at R={_delta.get('r_after')} and no round was spent; escalate "
                      f"per SPEC-0103 rather than re-running.", file=sys.stderr)
            else:
                print(f"# no-answer: the auditor did not answer (no payload came back) — it cost NO "
                      f"round (R={_delta.get('r_after')}, malformed_count unchanged) and episode "
                      f"{_episode_id} is still OPEN. Re-run the SAME consult.", file=sys.stderr)
        if _delta.get("outcome") in CONSULT_TERMINAL_OUTCOMES and \
                _delta.get("outcome") != CONSULT_OUTCOME_PROCEED:
            print("# " + consult_terminal_owner_route(_delta, is_plan=is_plan, target_id=target_id,
                                                      consult_key=consult_key), file=sys.stderr)

    # T-12234 — the grant also rides the RECORD, so a reader of the artifacts alone sees that this
    # episode was owner-reopened. The durable carrier is still the row (above); this is convenience.
    if owner_reopen:
        audit["owner_reopen"] = owner_reopen
    # T-12466 — SPEC-0173 rule 1 on the consult record too: an auditor child that exited without a
    # verdict (or any verdict-less ABORT) persists as `no_data: true`, written ALWAYS via the ONE producer.
    audit.update(inspection.no_data_fields(is_no_data_verdict(verdict, [])))

    # T-12350 (SPEC-0201 rule 2) — the ONE saved-verdict writer helper: stamp + same-provider row.
    # A consult always runs the FULL tier (the `full = ... or True` at its verb).
    stamp_auditor_verdict(audit, provider=provider, model=model, full=True,
                          target_kind=("plan" if is_plan else "task"), target_id=target_id,
                          stage=f"consult-{consult_key}", append_event=_append_event,
                          answered=_answered_pair)   # T-12606 — which PAIR produced this verdict

    # SPEC-0001 self-test (keyed on target_id — the plan-gate-audit precedent; `task` may be absent).
    content = state.dump(audit)
    try:
        roundtrip = state.load_str(content)
        if not isinstance(roundtrip, dict) or roundtrip.get("target_id") != target_id:
            _die("SPEC-0001 self-test failed: serialized consult YAML did not round-trip")
    except yaml.YAMLError as e:
        _die(f"SPEC-0001 self-test failed: {e}")

    write_text_atomic(audit_path, content)

    # ONE audit-family event surface (audit-pre p3-F1 absorption — no second parallel event):
    # external_audit_completed with the distinguishing consult fields, and — since T-12182 — the
    # ELEVEN SPEC-0200 rule-9 episode fields. This is their FIRST LIVE EMISSION: C4 defined the
    # formatter and the fold and emitted nothing, precisely so the C4-landed intermediate state had
    # ONE record contract (rule 9's B11). An EXTENSION of an existing event, never a new event type.
    #
    # THE ROW IS THE DURABLE CARRIER, and the record is not. The postcheck fold reads R and the
    # outcome from these rows because the record is REWRITABLE — the next adjudication on the same
    # (target, key) overwrites it in place, which is the defect T-11840 measured on T-10444. The row
    # is append-only, so a reading taken from it cannot be edited out from under the reader.
    _completed_data = {
        "stage": f"consult-{consult_key}",
        "verdict": verdict,
        **observe.auditor_triple(provider, model, effort, answered=_answered_pair),   # T-12857/T-13031 — the task row's triple (SPEC-0135 §4)
        "duration_ms": _audit_duration_ms(_consult_t0),   # T-12007 — REQUIRED (SPEC-0025)
        "survivors_count": len(survivors),
        "recommendation": recommendation or None,
        "saved_to": str(audit_path.relative_to(REPO_ROOT)),
        "target_kind": "consult",
        "target_id": target_id,
        "tier": "full",
    }
    _completed_data.update(_episode_row)
    # T-12234 — the owner GRANT LOCATOR, on the round-0 row of an owner-reopened episode and
    # nowhere else (rationale at `consult_reopen_refusal`; it rides the row for the same reason
    # rule 9 gives for the eleven fields above). Absent on every ordinary round.
    if owner_reopen:
        _completed_data["owner_reopen"] = owner_reopen
    if _withdrawn_now:                      # T-12248 — see `consult_round_withdrawn`
        _completed_data["withdrawn"] = _withdrawn_now
    _append_event("external_audit_completed", (None if is_plan else target_id), _completed_data)
    _auto_rebuild_graph("audit_consult")
    return audit, survivors, recommendation, audit_path


def build_plan_consult_prompt(slug, gate, options, plan_fm, plan_body, *,
                              _PLAN_AUDIT_LENS, _plan_fsm_line, _PLAN_CONSULT_GATE_AUDIT, DECISIONS_DIR):
    """Shared PLAN-gate ceiling-convergence consult PROMPT builder (extracted T-9702). The plan analog
    of the task `_build_audit_prompt(..., "consult")` branch (T-9286): FULL plan-audit lens +
    authoritative FSM + ceiling context + the gate's prior verdict trail + the candidate options.

    Reused by BOTH `cmd_audit_consult` (the interactive `audit consult --plan --gate`) AND cmd_audit's
    dispatched-worker AUTO-consult at the plan FINALIZATION ceiling (T-9702 L3 parity) — so the headless
    plan auto-consult IS the EXISTING plan consult prompt, not a parallel one (CHARTER §P1 F1 / §P5).
    Behaviour is byte-identical to the inlined cmd_audit_consult body it replaced."""
    _pat = _PLAN_CONSULT_GATE_AUDIT[gate][0].format(slug=slug)
    _prior_p = DECISIONS_DIR / _pat
    prior_trail = _prior_p.read_text(encoding="utf-8") if _prior_p.exists() else None
    _opts_block = "\n".join(f"{i + 1}. {o}" for i, o in enumerate(options))
    return (
        f"{_PLAN_AUDIT_LENS}\n## Authoritative plan FSM\n{_plan_fsm_line()}\n"
        f"\n## Ceiling-convergence consult — plan {slug}, gate {gate} "
        f"(SPEC-0124 §Plan-target parity)\n\nThe {gate} gate reached its audit-loop ceiling. "
        f"Name which of the candidate resolution OPTIONS below SURVIVE (a subset, fail-closed) and a "
        f"single recommendation (exactly one survivor). Output `verdict:` (GREEN/YELLOW/RED/ABORT) + "
        f"`survivors:` (a YAML list of option numbers) + `recommendation:` (one number) + `notes:`.\n"
        f"\n## Prior verdict trail ({_pat})\n\n{prior_trail or '(none on record)'}\n"
        f"\n## Candidate options\n\n{_opts_block}\n"
        f"\n## Plan {slug}\n\nfrontmatter: {plan_fm}\n\n{plan_body}\n")


def consult_status_refusal(tid: str, status, on_demand: bool = False) -> str:
    """T-10507 — the `audit consult` status-gate refusal, ROUTED (never a dead end).

    The gate itself is UNCHANGED (a consult still requires status: in-progress, or status: done
    with --reaudit-after-close). Only the TEXT routes: a status:done target is told the sanctioned
    exit it is standing on — `--reaudit-after-close` (T-10094), the HEAD-pinned post-close consult
    that re-opens ONE pass past a SPENT --owner-reset.

    WHY (the T-10481 incident, 2026-07-12/13, fp
    consult-refuses-done-unlanded-task-circular-ceiling-deadend): the reopen MECHANISM already
    shipped with T-10094, but this refusal named no exit — so a done-but-UNLANDED task past the
    ceiling read a flat "in-progress only" as an absolute wall, captured a deviation, and
    park+transplanted a converged build (T-10493). The capability was there; the discoverability
    was the deadlock. Park+transplant is NOT the canonical exit (SPEC-0124 §Post-close reaudit
    exit). A task whose `done` already LANDED has no reopen at all — that is a NEW task
    (QUEUE §Prematurely-closed / LIFECYCLE §Stage 9), and the message says so rather than
    letting a session hunt for a flag that cannot help it."""
    base = f"{tid} status={status!r} — consult only valid for status: in-progress"
    if status != "done":
        return base
    if on_demand:
        return (f"{base}. A status: done task has NO --on-demand consult (that fork is a "
                f"below-ceiling design pick on live work). If this is a done-but-UNLANDED task "
                f"re-baselining post-close, the sanctioned path is the ceiling-convergence "
                f"consult: `yitc-v2 audit consult --task {tid} --stage post --reaudit-after-close` "
                f"(T-10094 / SPEC-0124 §Post-close reaudit exit). If {tid}'s `done` already LANDED "
                f"there is no reopen at all: file a NEW task (QUEUE §Prematurely-closed / "
                f"LIFECYCLE §Stage 9).")
    return (f"{base}, UNLESS this is the post-close rebaseline path. If {tid} is done-but-UNLANDED "
            f"on the `--reaudit-after-close` flow (past the ceiling, --owner-reset spent), the "
            f"consult DOES admit it — re-run with the flag:\n"
            f"  yitc-v2 audit consult --task {tid} --stage post --reaudit-after-close --option … --option …\n"
            f"That consult pins its basis to HEAD (the same fp `audit post --reaudit-after-close` "
            f"audits), so a fresh single-survivor verdict RE-OPENS one more `audit post "
            f"--owner-reset --reaudit-after-close` past the exhausted budget (T-10094 / T-0515). "
            f"Do NOT park+redo the build — that is not the canonical exit (SPEC-0124 §Post-close "
            f"reaudit exit; the T-10481 circle). If {tid}'s `done` already LANDED there is no "
            f"reopen at all: file a NEW task (QUEUE §Prematurely-closed / LIFECYCLE §Stage 9).")


def cmd_audit_consult(args: argparse.Namespace, *, _capacity_retry_hint=None, AUDIT_PASS_CEILING, DECISIONS_DIR, PLANS_DIR, PLAN_CONSULT_GATES, REPO_ROOT, TASK_ID_RE, _with_repo_lock=None, _iter_events=None, EVENTS_PATH=None, _file_followup=None, _plan_gate_lens=None, _PLAN_AUDIT_LENS, _PLAN_CONSULT_GATE_AUDIT, _append_event, _auto_rebuild_graph, _build_audit_prompt, _count_audit_passes, _die, _find_task_yaml, _get_audit_post_diff, _git_resolve_sha, _invoke_auditor, _load_draft, _parse_consult_result, _plan_content_hash, _plan_fsm_line, _plan_gate_prior_passes, _plan_gate_recorded_signature, _recorded_commit_sha, _reject_id_shaped_plan_slug, _require_plan_finalized, _require_writing_worktree, _resolve_audit_effort, _resolve_audit_model, _resolve_audit_reserve=None, _resolve_audit_provider, _resolve_prompt_file, _strip_degenerate_tail, _utc_now_iso, _verdict_exit_code, write_text_atomic, RETIRED_AUDIT_SURFACES, RETIRED_CEILING_POINTER, _consult_adjudicate, _consult_post_subject, build_plan_consult_prompt, consult_hold_is_nonconverged, consult_status_refusal, consult_sticky_hold_open_ids, consult_task_lens, observe, parse_audit_verdict, resolve_model_for_provider, state) -> None:
    """T-0429 — `audit consult --task T-XXXX --stage pre|post`: the ceiling-convergence triage step
    (SPEC-0124 §Audit-loop ceiling) mechanized as a NAMED audit subcommand.

    It is the pass-3 triage, NOT an anytime escape hatch: it REFUSES unless the audit-loop ceiling
    for that task+stage is exhausted (prior_passes >= AUDIT_PASS_CEILING) — the chokepoint that keeps
    a consult honest. The session submits its candidate resolution OPTIONS (>=2, via repeatable
    --option / -f file / stdin); the verb deterministically assembles the prompt (task YAML + plan +
    (post) commit diff + the prior verdict trail incl. passes_trail + the options), asks the external
    auditor to name SURVIVORS (a subset of the submitted options) + a single recommendation, and
    saves a STRUCTURED verdict decisions/<tid>-audit-consult-<stage>.yaml. A fresh single-survivor
    verdict is the standing basis the SAME task's `audit pre|post --owner-reset` then verifies
    (_consult_basis) to grant ONE ceiling continuation WITHOUT a fresh owner ask.

    Reuses the EXISTING audit machinery end-to-end (anti-complexity F1 — no parallel path):
    _build_audit_prompt (consult branch), _invoke_auditor, _parse_consult_result (strict survivors),
    write_text_atomic, _append_event. Like `audit adhoc` it WRITES a decisions/ artifact, so it is
    bound by the D-0037/D-0051 write-isolation guard (a Build session runs it inside the task/ wt)."""
    # T-11249 (<project> X-0970) — SAY WHICH CHECKOUT THIS VERDICT RESTS ON, before anything else.
    # Diagnostic only, on stderr: every stdout contract stays byte-identical, and it sits beside
    # the sibling `# audit-loop ceiling:` notes. UNCONDITIONAL by design — the cost being removed
    # is the SILENCE, and a line that appears only when the engine already suspects a mismatch is
    # the same silence with extra steps. FIRST statement in the body, ahead of
    # `_require_writing_worktree()`: a wrong-tree invocation is exactly what that guard refuses,
    # so its refusal needs the tree named too.
    print(observe.checkout_provenance_line(REPO_ROOT, verb="audit consult"), file=sys.stderr)
    _require_writing_worktree()
    try:
        import yaml
    except ImportError:
        _die("PyYAML required for `audit` (pip install pyyaml)")

    # TARGET resolution (T-9286): a TASK (--task + --stage) OR a PLAN gate (--plan + --gate). Both
    # save decisions/<id>-audit-consult-<key>.yaml; key = stage(pre|post) for a task, gate for a plan.
    # T-9684 (lever #6): a THIRD entry — the ON-DEMAND technical-fork variant-pick (--on-demand --task),
    # BELOW the ceiling, decoupled from the owner-reset basis (a distinct consult key, no fingerprint).
    is_plan = bool((getattr(args, "plan", None) or "").strip())
    on_demand = bool(getattr(args, "on_demand", False))
    # ── SPEC-0204 rule 6 (T-12290) — THE RETIREMENT SHIM for the TASK-target consult form ──────────
    # `audit consult --task <T-XXXX> --stage <pre|post>` WAS the ceiling-adjudication route: an
    # episode, frozen finding ids, retest rounds, a PROCEED/HOLD option pair, and a record that then
    # governed an `--owner-reset`. All of that is retired; a residual past the ceiling is settled by
    # ONE typed `ceiling_decision` and verified by ONE `--on-decisions` pass. The refusal is FIRST in
    # the verb — above target resolution, the ceiling chokepoint and every read — so it can neither
    # write a record nor spend a pass, and so a caller learns the route before paying for anything.
    #
    # THE TWO SURVIVING FORMS ARE NOT TOUCHED, and the condition says so positively rather than by
    # omission: `--on-demand` is the BELOW-ceiling technical-fork pick (explicitly outside the
    # retirement list) and `--plan --gate` is the plan-gate consult, which is the ONLY basis
    # `plan stage --owner-reset` (T-9286, also outside the list) accepts. Retiring either here would
    # take down a surface nobody retired.
    if not on_demand and not is_plan:
        _die(RETIRED_AUDIT_SURFACES["consult-task-form"] + "\n\n" + RETIRED_CEILING_POINTER)
    # ── SPEC-0204 rule 6, PLAN-GATE arm (T-12335) — THE SHIM FOR THE PLAN-GATE FORM ────────────────
    # The paragraph above says `--plan --gate` «is the ONLY basis `plan stage --owner-reset` accepts»
    # and is therefore untouched. THAT IS NO LONGER TRUE, and this shim is the same retirement reaching
    # the plan axis: the plan-gate consult existed for exactly one job — adjudicating a plan gate's
    # ceiling so `--owner-reset` could verify its PROCEED — and both halves are retired together
    # (`plan-gate-owner-reset` in the same carrier). Placed HERE, beside its sibling and above target
    # resolution, for the same reason: no record written, no pass spent, and the route learned before
    # anything is paid for.
    #
    # MEASURED, not tidied. Two consumer plans CONVERGED on the merits (RED→YELLOW→every finding
    # closed) and were still stranded, because their episodes ended `malformed-exhausted` and every
    # door was shut behind them: the consult refused `episode-ended`, `plan stage --owner-reset`
    # refused on a HOLD survivor, `--reopen` was retired, and the only exit left was to CANCEL the plan
    # (<project> `otgruzki-design-parity-…` gate draft-specs, X-1334, 2026-09-08; <project>
    # `podklyuchenie-statistiki-…` gate specs-trial, X-1336, 2026-09-09). The decision route replaces
    # the episode; `plan_gate_live_terminal_reasons` reads this same carrier so `graph conformance`
    # watches the retirement rather than trusting it.
    #
    # `not on_demand` KEEPS AN EXISTING REFUSAL PRECISE rather than carving out a live surface:
    # `--on-demand --plan` was never a form (the below-ceiling technical fork is TASK-only) and is
    # already refused, by name, a few lines down. Letting THIS shim swallow that combination would
    # answer «the plan-gate consult is retired, run the decision route» to a caller whose actual
    # mistake is pairing a task-only flag with a plan target — a worse answer, and one that
    # contradicts this refusal's own closing sentence that `--on-demand` is unchanged.
    if is_plan and not on_demand:
        _die(RETIRED_AUDIT_SURFACES["consult-plan-gate-form"] + "\n\n"
             + "Run, verbatim:\n"
             + f"  1) yitc-v2 audit decide --plan {(getattr(args, 'plan', None) or '<slug>').strip()} "
             + f"--gate {(getattr(args, 'gate', None) or '<gate>').strip()} --finding <fp> "
             + "--disposition fix|accept|defer --reason … --directive events.jsonl#ts=<ISO>\n"
             + "     (ONCE PER RESIDUAL of the gate's ceiling row — `plan stage <NEXT> "
             + "--on-decisions` names the undecided ones)\n"
             + "  2) yitc-v2 plan stage <NEXT> <slug> --on-decisions\n\n"
             + RETIRED_CEILING_POINTER)
    # T-10094 — post-close rebaseline consult carve-out (mirror `audit post --reaudit-after-close`).
    # TASK + --stage post ONLY: it forms the ceiling-convergence basis for a status:done task's
    # post-close `land --rebaseline`, pinning the basis to HEAD (not the last commit_landed).
    reaudit_after_close = bool(getattr(args, "reaudit_after_close", False))
    if reaudit_after_close and (on_demand or is_plan):
        _die("audit consult --reaudit-after-close is TASK + --stage post ONLY (a status:done task's "
             "post-close land --rebaseline) — not valid with --on-demand or --plan (T-10094).")
    stage = None
    plan_fm = None
    plan_body = None
    artifact = None
    if on_demand:
        # T-9684 — TASK-only, below-ceiling design-fork consult. The auditor ratifies TECHNICAL merit;
        # the owner keeps a lightweight ratify/veto. Forbid --plan/--gate (a plan gate is a CEILING
        # surface, not a design fork); --stage is irrelevant (this is not a pre/post audit ceiling).
        if is_plan or (getattr(args, "gate", None) or "").strip():
            _die("audit consult --on-demand is TASK-only (a technical DESIGN fork) — not a --plan/--gate "
                 "target (a plan gate is a ceiling surface, not a below-ceiling fork). Pass --task T-XXXX.")
        tid = (args.task or "").strip()
        if not TASK_ID_RE.match(tid) or not tid.startswith("T-"):
            _die(f"--task must be a T-NNNN id; got {tid!r}")
        art_path = _find_task_yaml(tid)
        if art_path is None:
            _die(f"task YAML not found for {tid}")
        artifact = state.load_str(art_path.read_text(encoding="utf-8")) or {}
        if not isinstance(artifact, dict):
            _die("task target did not parse as a mapping")
        if artifact.get("status") != "in-progress":
            # T-10507 — routed refusal: a status:done target is pointed at the sanctioned
            # --reaudit-after-close consult instead of a dead end (the T-10481 circle).
            _die(consult_status_refusal(tid, artifact.get("status"), on_demand=True))
        target_id = tid
        consult_key = "on-demand"   # DISTINCT key -> decisions/<tid>-audit-consult-on-demand.yaml; the
        prior_passes = 0            # owner-reset basis reader (<tid>-audit-consult-{pre,post}) never sees it.
    elif is_plan:
        if (getattr(args, "task", None) or "").strip() or (getattr(args, "stage", None) or "").strip():
            _die("audit consult: pass EITHER --task (with --stage) OR --plan (with --gate), not both.")
        slug = args.plan.strip()
        _reject_id_shaped_plan_slug(slug)            # T-0193 F1 — no audit-namespace collision
        gate = (getattr(args, "gate", None) or "").strip()
        if gate not in PLAN_CONSULT_GATES:
            _die(f"--gate is REQUIRED with --plan and must be one of {list(PLAN_CONSULT_GATES)} "
                 f"(the SPEC-0124 ceiling-bearing plan gates, INV-1); got {gate!r}")
        _pp, plan_fm, plan_body = _load_draft(slug, dirs=(PLANS_DIR,))
        if not isinstance(plan_fm, dict):
            plan_fm = {}
        target_id = slug
        consult_key = gate
        prior_passes = _plan_gate_prior_passes(slug, gate)
    else:
        tid = (args.task or "").strip()
        if not TASK_ID_RE.match(tid) or not tid.startswith("T-"):
            _die(f"--task must be a T-NNNN id; got {tid!r}")
        stage = (args.stage or "").strip()
        if stage not in ("pre", "post"):
            _die(f"--stage must be 'pre' or 'post'; got {stage!r}")
        art_path = _find_task_yaml(tid)
        if art_path is None:
            _die(f"task YAML not found for {tid}")
        artifact = state.load_str(art_path.read_text(encoding="utf-8")) or {}
        if not isinstance(artifact, dict):
            _die("task target did not parse as a mapping")
        if reaudit_after_close:
            # T-10094 — mirror `audit post --reaudit-after-close`'s done-only carve-out (cmd_audit):
            # this consult forms the post-close rebaseline basis for a status:done task, so it runs
            # ONLY on a done task and ONLY for the post stage.
            if stage != "post":
                _die("audit consult --reaudit-after-close is post-only (it forms the post-close "
                     "rebaseline basis); drop the flag or pass --stage post (T-10094).")
            if artifact.get("status") != "done":
                _die(f"{tid} status={artifact.get('status')!r} — --reaudit-after-close consult is ONLY "
                     "for a status: done task re-baselining post-close; a non-done task runs the "
                     "ordinary in-progress consult (drop the flag) (T-10094).")
        elif artifact.get("status") != "in-progress":
            # T-10507 — the T-10481 dead-end site: the reopen path EXISTS (T-10094) but this
            # refusal named no exit, so a done-but-unlanded task past the ceiling read a wall.
            _die(consult_status_refusal(tid, artifact.get("status")))
        target_id = tid
        consult_key = stage
        prior_passes = _count_audit_passes(tid, stage)

    # CHOKEPOINT (the whole point — SPEC-0124): the CEILING-driven consult is the pass-3 triage step, so
    # it REFUSES unless the audit-loop ceiling for this target+key is actually exhausted (prior_passes >=
    # 2). T-9684: the ON-DEMAND fork-picker is the NARROWED exception — it is a below-ceiling design-fork
    # variant-pick, so it bypasses this chokepoint (the ceiling-driven path is otherwise UNCHANGED).
    if not on_demand and prior_passes < AUDIT_PASS_CEILING:
        _die(f"audit consult refused: {target_id} {consult_key} has {prior_passes} audit pass(es) on "
             f"record (< the {AUDIT_PASS_CEILING}-pass ceiling). A consult is the ceiling-convergence "
             f"triage (pass-{AUDIT_PASS_CEILING + 1}) step, NOT an anytime escape hatch — run the normal "
             f"absorption passes first (SPEC-0124 §Audit-loop ceiling). For a below-ceiling TECHNICAL "
             f"design fork use `audit consult --on-demand --task {target_id}`.")

    # SPEC-0204 rule 6 (T-12290) — the T-12234 `--reopen` OWNER GATE is REMOVED with the flag it
    # gated: there are no consult EPISODES left to re-open. `owner_reopen` is therefore always None
    # from here down, and the round-0 grant-locator field it wrote is never produced again.
    owner_reopen = None

    # Assemble the candidate resolution options: --option (repeatable), then -f/--from-file (one
    # option per non-empty line; REPO_ROOT-only fail-closed resolution), then stdin fallback.
    options: list[str] = []
    for o in (getattr(args, "option", None) or []):
        if o and o.strip():
            options.append(o.strip())
    if getattr(args, "from_file", None):
        fp = _resolve_prompt_file(args.from_file)
        try:
            for ln in fp.read_text(encoding="utf-8").splitlines():
                if ln.strip():
                    options.append(ln.strip())
        except (FileNotFoundError, PermissionError, OSError) as e:
            _die(f"--from-file {args.from_file!r} unreadable: {e}")
    if not options and not sys.stdin.isatty():
        for ln in sys.stdin.read().splitlines():
            if ln.strip():
                options.append(ln.strip())
    if len(options) < 2:
        _die("audit consult needs >=2 resolution options (the triage compares them) — pass repeatable "
             "--option, a -f/--from-file (one option per line), or pipe options via stdin.")

    # Freshness basis the consult is formed against (p2-F1 exact-match): pre = the finalized plan's
    # content hash (the SAME one audit-pre/task-execute hash); post = the recorded commit SHA. Persisted
    # in the verdict so `--owner-reset` can later verify the consult still matches the current state.
    basis_fp = None
    diff = None
    #: T-12233 — the git ref the DIFF was taken against, so the soft packet bound can re-take it as
    #: a delta since the baseline revision. None wherever there is no commit subject (a PRE consult's
    #: basis is a plan CONTENT HASH, a plan gate has no diff at all), and the bound then simply
    #: measures and records the full packet.
    _subject_ref = None
    if on_demand:
        # T-9684 — NO freshness basis: an on-demand fork consult is NOT an --owner-reset basis (it is
        # decoupled by construction), so it persists no basis_fingerprint and binds to no plan/commit.
        pass
    elif is_plan:
        # INV-2 — the consult basis_fingerprint REUSES the gate audit's ALREADY-RECORDED signature.
        basis_fp = _plan_gate_recorded_signature(target_id, consult_key)
        if not basis_fp:
            _die(f"{target_id}: the {consult_key} gate audit has recorded no signature to bind the "
                 f"consult basis to (INV-2) — run/complete the {consult_key} gate audit first so it "
                 f"records its signature, then re-run the consult.")
    elif stage == "pre":
        basis_fp = _plan_content_hash(_require_plan_finalized(artifact, tid))
    else:
        if reaudit_after_close:
            # T-10094 — pin the basis to HEAD, the SAME source `audit post --reaudit-after-close`
            # audits (cmd_audit: sha = _git_resolve_sha("HEAD")). Binding to _recorded_commit_sha
            # (the last commit_landed) would diverge from HEAD once HEAD moved past it via a
            # non-task-commit path (raw-git / land-bookkeeping / rebaseline) — the T-10081 dead-end
            # where a converged consult's basis never matched the reaudit ceiling_fp(HEAD).
            basis_fp = _git_resolve_sha("HEAD")
            if not basis_fp:
                _die("audit consult --reaudit-after-close: could not resolve HEAD to a commit "
                     "(not a valid git ref).")
        else:
            recorded = _recorded_commit_sha(tid) or ""
            if not recorded:
                _die(f"{tid}: no recorded commit to consult on for stage=post — run `task commit {tid}` "
                     "first (the consult diff + basis bind to the recorded commit, D-0082).")
            basis_fp = _git_resolve_sha(recorded) or recorded
        if reaudit_after_close:
            diff = _get_audit_post_diff(basis_fp)
            _subject_ref = basis_fp
        else:
            # T-11421 (X-1088) — the SUBJECT may legitimately be ahead of the pinned basis. Rationale,
            # bound and the deliberate non-move of `basis_fingerprint`: `_consult_post_subject`.
            _head_fp = _git_resolve_sha("HEAD")
            _supersedes = False
            if _head_fp and basis_fp and _head_fp != basis_fp:
                try:
                    _supersedes = subprocess.run(
                        ["git", "-C", str(REPO_ROOT), "merge-base", "--is-ancestor", basis_fp, _head_fp],
                        capture_output=True, text=True, check=False).returncode == 0
                except (FileNotFoundError, OSError):
                    _supersedes = False   # fail-closed: an unreadable history reads the recorded commit
            _subject_sha, _subject_note = _consult_post_subject(basis_fp, _head_fp, _supersedes)
            diff = _get_audit_post_diff(_subject_sha)
            _subject_ref = _subject_sha
            if _subject_note:
                print(f"# {_subject_note}", file=sys.stderr)
                diff = f"{_subject_note}\n\n{diff}"

    full = bool(getattr(args, "full", False)) or True   # a consult is the architectural/triage class
    provider = _resolve_audit_provider(full)            # — FULL by default (SPEC-0036 audit posture).
    model = resolve_model_for_provider(_resolve_audit_model, full, provider)
    _answered_pair: dict = {}      # T-12606 — INVOCATION-scoped: which pair answered THIS audit   # T-12350: provider first (admission)
    effort = _resolve_audit_effort(full)
    if is_plan:
        # PLAN consult prompt (T-9286): the plan analog of the task `_build_audit_prompt(..., "consult")`
        # branch. Extracted to `build_plan_consult_prompt` (T-9702) so cmd_audit's dispatched-worker
        # AUTO-consult at the finalization ceiling reuses the SAME prompt (no parallel one — P5).
        prompt = build_plan_consult_prompt(
            target_id, consult_key, options, plan_fm, plan_body,
            _PLAN_AUDIT_LENS=_PLAN_AUDIT_LENS, _plan_fsm_line=_plan_fsm_line,
            _PLAN_CONSULT_GATE_AUDIT=_PLAN_CONSULT_GATE_AUDIT, DECISIONS_DIR=DECISIONS_DIR)
    else:
        if on_demand:
            # T-9684 — a below-ceiling design fork: there is NO prior audit ceiling trail to carry.
            cstage, prior_trail = "design-fork", None
        else:
            # Prior verdict trail (incl. passes_trail) — the consult must see WHAT was absorbed already.
            prior_path = REPO_ROOT / "decisions" / f"{tid}-audit-{stage}.yaml"
            cstage = stage
            prior_trail = prior_path.read_text(encoding="utf-8") if prior_path.exists() else None
        consult_artifact = dict(artifact)
        consult_artifact.update({
            "consult_stage": cstage,
            "consult_options": options,
            "consult_prior_trail": prior_trail,
            "on_demand_fork": on_demand,   # T-9684 — switches build_audit_prompt to the fork overlay
        })
        prompt = _build_audit_prompt(consult_artifact, "consult", diff, None, "consult")
    prompt_excerpt = prompt[:200]

    def _delta_prompt_builder(baseline_revision):
        """T-12233 — RE-ASSEMBLE this consult's base prompt over the DELTA SINCE `baseline_revision`.

        Returns the re-assembled prompt, or None when the delta cannot be taken (no resolvable
        baseline revision — a PRE consult's basis is a plan CONTENT HASH, not a commit; no subject
        sha; an unreadable history). None means «keep the full packet», never «cut it»: the bound is
        soft, so a scope it cannot compute simply does not apply.
        """
        if is_plan or on_demand or not diff:
            return None
        _base = _git_resolve_sha(baseline_revision or "")
        _subj = _git_resolve_sha(_subject_ref or "")
        if not _base or not _subj or _base == _subj:
            return None
        try:
            _out = subprocess.run(["git", "-C", str(REPO_ROOT), "diff", f"{_base}..{_subj}"],
                                  capture_output=True, text=True, check=False)
        except (FileNotFoundError, OSError):
            return None
        if _out.returncode != 0:
            return None
        _delta_note = (f"[SPEC-0200 rule 4 / T-12233: DELTA SINCE THE BASELINE REVISION "
                       f"{_base[:12]}..{_subj[:12]} — this retest judges only the open blocking ids "
                       f"and any regression the fix INTRODUCED, which is exactly this delta; a "
                       f"whole-subject survey is not asked for at a retest.]")
        _delta_artifact = dict(consult_artifact)
        return _build_audit_prompt(_delta_artifact, "consult",
                                   f"{_delta_note}\n\n{_out.stdout}", None, "consult")

    # T-9683 — the invoke→parse→write→emit core is the shared `_consult_adjudicate` helper (reused by
    # cmd_audit's dispatched-worker AUTO-consult, so the headless path IS this engine, not a parallel one).
    audit, survivors, recommendation, audit_path = _consult_adjudicate(
        target_id, consult_key, is_plan, options, prompt, prompt_excerpt, prior_passes, basis_fp,
        provider, model, effort,
        _invoke_auditor=_invoke_auditor, _parse_consult_result=_parse_consult_result,
        _strip_degenerate_tail=_strip_degenerate_tail, _append_event=_append_event,
        _utc_now_iso=_utc_now_iso, _plan_content_hash=_plan_content_hash,
        _auto_rebuild_graph=_auto_rebuild_graph, write_text_atomic=write_text_atomic,
        _die=_die, REPO_ROOT=REPO_ROOT, reaudit_after_close=reaudit_after_close,
        _capacity_retry_hint=_capacity_retry_hint,   # T-12603
        _resolve_audit_reserve=_resolve_audit_reserve,   # T-12606 — the FULL tier's reserve pair
        # SPEC-0200 (T-12182) — the contract injections. `on_demand` is NOT a ceiling episode, so it
        # passes no lens and the engine's `_baseline_bearing` test leaves its option semantics alone.
        # T-12233 — the delta re-assembly the SOFT packet bound may choose at a RETEST. It is an
        # INJECTION rather than an inline branch because `_consult_adjudicate` never sees the diff
        # or the prompt BUILDER — only the assembled prompt. Absent (None) on every path that
        # cannot rebuild — the plan-gate consult and cmd_audit's auto-consult — where the packet is
        # simply measured and recorded at scope `full`, never narrowed and never cut.
        _rebuild_prompt_with_delta=(None if is_plan else _delta_prompt_builder),
        _with_repo_lock=_with_repo_lock, _iter_events=_iter_events, events_path=EVENTS_PATH,
        _file_followup=_file_followup, _parse_audit_verdict=parse_audit_verdict,
        lens=(((_plan_gate_lens(consult_key) if _plan_gate_lens else set()) if is_plan
               else consult_task_lens(artifact))),
        # SPEC-0204 rule 6 (T-12290) — the WITHDRAWAL MARKERS no longer ACT. `CUT to <id>` and
        # `WITHDRAWN <id> out-of-subject to <id>` used to withdraw a baseline finding from the open
        # set on the card's say-so; a residual that leaves this card's subject is now a typed `defer`
        # decision naming its receiving card and its authorizing directive, on an append-only row.
        # The READERS are kept and are now a REFUSAL detector (`card_carries_retired_markers`, read
        # by `cmd_audit` on the card it already loaded) — a card still carrying a marker is
        # recognised and refused, never silently audited against a scope it disputes. The forms that
        # reach here (`--on-demand`, `--plan --gate`) hold no baseline findings to withdraw anyway.
        scope_cuts={},
        owner_rulings={},
        owner_reopen=owner_reopen)
    verdict = audit["verdict"]
    converged = verdict in ("GREEN", "YELLOW") and len(survivors) == 1
    # The HOLD-survivor convergence seam (SPEC-0124), LIVE since T-12182. The predicate now reads
    # the C2 ADJUDICATION RECORD `_consult_adjudicate` just wrote (`audit` carries the delta), so the
    # seam asks rule-6's question — did the stated survivor survive validation? — rather than the
    # retired `findings_complete` question. The RECORD is what is passed, which is the whole re-key:
    # the same fixed HOLD text means row 16 (converged, owner-held) or row 17 (an open set, the
    # episode continues) depending on state the text cannot carry. ONE-WAY SAFE, unchanged: this
    # branch can only WITHHOLD convergence, never grant it, so no `--owner-reset` basis widens.
    if converged and consult_hold_is_nonconverged(audit.get("survivors") or [], options,
                                                  audit.get("findings_complete"), record=audit):
        converged = False
        _open = ", ".join(consult_sticky_hold_open_ids(audit)) or "(none recorded)"
        print(f"# NOT converged (SPEC-0200 rule 6): the stated survivor failed validation — "
              f"outcome={audit.get('outcome')!r}, survivor_overridden="
              f"{bool(audit.get('survivor_overridden'))}, open ids: {_open}. This is NOT an "
              f"--owner-reset basis; the episode continues with a retest, or rests on the owner "
              f"route (SPEC-0124 / SPEC-0200 rule 7).", file=sys.stderr)

    if on_demand:
        # T-9684 — the ON-DEMAND fork-picker outcome. FAIL-CLOSED: a single surviving variant is the
        # only auto-proceed; a value/draft escalation (ABORT), a disagreement, a multi-survivor, or any
        # not-GREEN/YELLOW does NOT auto-pick. A single survivor RECORDS the owner ratify/veto evidence
        # as a journal event (the durable STATE probe — CHARTER §P2/P3); this is NOT a --owner-reset basis.
        print(f"{target_id} audit-consult-on-demand: {verdict} ({len(survivors)} survivor(s)"
              + (f", recommend variant {recommendation}" if recommendation else "")
              + f") → {audit_path.relative_to(REPO_ROOT)}")
        if converged:
            _append_event("audit_on_demand_consult", target_id, {
                "stage": "consult-on-demand",
                "verdict": verdict,
                "survivor": survivors[0],
                "survivor_text": options[survivors[0] - 1],
                "recommendation": recommendation or None,
                "owner_disposition": "ratify-veto",   # auditor ratified TECHNICAL merit; owner ratifies/vetoes
                "fork_scope": "technical",
                "saved_to": str(audit_path.relative_to(REPO_ROOT)),
            })
            print(f"# converged: a single surviving variant (variant {survivors[0]}). The auditor RATIFIED "
                  f"its technical merit;\n# the OWNER keeps a lightweight ratify/veto (SPEC-0124 §On-demand "
                  f"technical-fork consult).\n# Recorded audit_on_demand_consult. This is NOT an "
                  f"--owner-reset basis.", file=sys.stderr)
        else:
            print(f"# NOT converged ({len(survivors)} survivor(s) / verdict {verdict}) — FAIL-CLOSED: no "
                  f"auto-pick.\n# A value/draft-authority fork (ABORT), a disagreement, a multi-survivor, "
                  f"or any not-GREEN/YELLOW\n# verdict escalates to the OWNER (SPEC-0124 §On-demand "
                  f"technical-fork consult).", file=sys.stderr)
        sys.exit(_verdict_exit_code(verdict))

    _reset_verb = (f"plan stage <NEXT> --owner-reset {target_id}" if (is_plan and consult_key != "finalization")
                   else f"audit post --plan {target_id} --owner-reset" if is_plan
                   else f"audit {consult_key} --task {target_id} --owner-reset")
    print(f"{target_id} audit-consult-{consult_key}: {verdict} ({len(survivors)} survivor(s)"
          + (f", recommend option {recommendation}" if recommendation else "")
          + f") → {audit_path.relative_to(REPO_ROOT)}")
    if converged:
        print(f"# converged: a single surviving option — `{_reset_verb}` "
              f"will verify this consult as the standing basis (SPEC-0124).", file=sys.stderr)
    else:
        print(f"# NOT converged ({len(survivors)} survivors / verdict {verdict}) — escalate to the "
              f"owner per SPEC-0124 (the consult basis is NOT a usable --owner-reset basis).",
              file=sys.stderr)
    sys.exit(_verdict_exit_code(verdict))
