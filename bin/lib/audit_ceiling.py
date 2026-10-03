"""audit_ceiling — the audit CEILING family (the SPEC-0204 `audit decide` verb, the `--on-decisions`
admission/bind/matrix/projection/residual readers, the residual-fingerprint + finding-index helpers,
the owner-directive resolvers and the card-record RED-cause reader), extracted byte-identical from
`bin/lib/audit.py` (T-12706, card C7b of plan `extract-the-13-over-budget-bin-lib-modules-into-le`).

WHAT IS IN HERE. The FROZEN manifest of the plan's §Extraction map C7b — 24 top-level defs:
`cmd_audit_decide, on_decisions_admission, on_decisions_absorption_grant, on_decisions_bind, on_decisions_matrix, on_decisions_packet_block, on_decisions_projection, on_decisions_residuals, on_decisions_row_absorbable, on_decisions_row_problems, _on_decisions_row_is_real, plan_gate_synthetic_ceiling_row, prior_audit_record, row_residual_fingerprints, _red_cause_is_card_record, _ac_named_verifier_paths, _accept_reason_quotes_directive, _currency_finding_index, residual_finding_records, _directive_covers_task, _directive_row_text, _late_finding_index, _prose_names_token, _repo_path_tokens, _resolve_owner_directive`.
NOT IN HERE: `cmd_audit` / `cmd_audit_pre|post|adhoc|run|status|canary_backstop`, the gates, the
`_invoke_*` / `_resolve_*` provider families, the ceiling COUNTERS (`terminal_ceiling_row`,
`_ceiling_row_of`, `validate_ceiling_payload`, `finding_fingerprint`, …) and the packet / consult
families (their own leaves, C7a / C6) — those stay in the host or their own module.

SEAM (the T-9340 / T-9341 / T-11519 / T-12696 / T-12701 full inject-residue shape,
`lessons/library-extraction.md` §AST-freeze generator): every body and signature below is spliced
VERBATIM from the original source — never `ast.unparse` — and every non-stdlib free name (host
stayers, host globals, lib aliases, AND moved siblings via their host residue) arrives as a
keyword-only injected parameter, computed with `symtable` over each function's scope SUBTREE.
Constants exclusive to the move-set live module-local below (the host keeps a re-export alias for
each). The host keeps a `functools.wraps` residue under every historical name
(`audit._ceiling_inject` reads the roster from `INJECTS` below at call time), so every `yitc.<sym>` /
`audit.<sym>` monkeypatch and every cross-module injection keeps resolving, and `inspect.getsource`
unwraps to the body here.

A LEAF: imports only stdlib and NEVER `lib.audit` (`tests/test_bin_lib_leaf_no_host_import.py`).
Intentionally spec-less (SPEC-0005 admission test): a byte-identical relocation mints no standing
rule — the governing specs (SPEC-0204 and siblings) keep their homes and point their `implements:`
anchors here.
"""
from __future__ import annotations
import hashlib
import inspect
import os
import re
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Constants exclusive to the move-set (referenced by movers only — verified across the host by
# the generator's fixpoint; external readers resolve the host re-export alias), moved
# module-local so the bodies read them 1:1, uninjected.
# ---------------------------------------------------------------------------
_C3_ROW_EXTENSION_KEYS = ("basis", "ceiling_ref", "decisions_applied",
                          "overruled_by_decision", "new_findings")

ABSORBABLE_NEW_FINDING_SEVERITIES = ("medium", "low")

CEILING_DECISION_DISPOSITIONS = ("fix", "accept", "defer")

PLAN_CARD_SET_FINGERPRINT_ERROR = hashlib.sha256(b"<plan-card-set-fingerprint-error>").hexdigest()

_DIRECTIVE_LOCATOR_RE = re.compile(r"events\.jsonl#ts=(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)")

_ACCEPT_QUOTE_RE = re.compile("«([^»]+)»|\u201c([^\u201d]+)\u201d|\"([^\"]+)\"")

_CONTROLLER_DELEGATED = "controller-delegated"

DIRECTIVE_COVERAGE_HELP = (
    "\n\nHOW A DIRECTIVE COVERS A TASK — three admitting shapes, and no fourth (SPEC-0204 rule 2):\n"
    "  (1) BATCH  — the task id is an element of the row's `data.cards` list;\n"
    "  (2) NAMES-IT — the task id appears as a WHOLE TOKEN in the row's prose "
    "(`data.text` / `data.directive` / a mid-turn row's `data.owner_text`);\n"
    "  (3) PLAN   — the slug the card is `decomposed_from` appears in `data.cards` or in that prose.\n"
    "Every arm is token-exact: prose naming `plan-foobar` never covers a card cut from `plan-foo`.\n"
    "\nWhen the owner's own row does not name this card (a verbatim cue like «go ahead»), the route is a "
    "CONTROLLER-DELEGATED capture that cites it. The owner row must ALREADY EXIST and PRECEDE this one:\n"
    "  bin/yitc-v2 event owner_directive --source-ref <owner-transcript-locator> \\\n"
    "    --data '{\"captured_via\": \"controller-delegated\", \"cards\": [\"T-XXXX\"], "
    "\"text\": \"<what the owner authorized> cites events.jsonl#ts=<owner row ts>\"}'\n"
    "then pass the NEW row's own `events.jsonl#ts=<ISO>` as `--directive`. The chain must END in an "
    "owner row: a delegated row citing another delegated row is refused.\n"
    "\nMID-TURN route (T-12801): an owner decision that arrived MID-TURN has no owner row to chain to. "
    "Record it at once as a delegated row anchored at the owner's transcript entry — the verb takes "
    "the owner's COMPLETE message as `owner_text` from that entry (or, if you supply `owner_text`, proves "
    "it EQUALS the entry) and stamps `owner_text_verified`:\n"
    "  bin/yitc-v2 event owner_directive --source-ref <transcript>#uuid:<owner entry uuid> \\\n"
    "    --data '{\"captured_via\": \"controller-delegated\", \"mid_turn\": true, "
    "\"cards\": [\"T-XXXX\"]}'"
)

_RED_CAUSE_PATH_RE = re.compile(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)+")

_RED_CAUSE_LOCATOR_RE = re.compile(r"[#:][^\s]*$")

_ACCEPTANCE_AC_RE = re.compile(r"^\s*AC-?(\d{1,3})\b", re.IGNORECASE)


# T-13364 — the event types `audit decide`'s ladder reads off the view, one per reader (audit_ceiling
# `cmd_audit_decide` and the pure helpers it calls): external_audit_completed (`_stage_audit_rows`, late /
# currency finding indices), audit_prompt_sent (`_on_decisions_row_is_real` via `terminal_ceiling_row`),
# ceiling_decision (`_ceiling_decision_rows`), worktree_synced (`worktree_sync_merges`), commit_landed (the
# T-13256 evidence-reachable set; cli's custody readers), session_started (gate i-ter), owner_directive
# (`_resolve_owner_directive`). DECLARED so the verb's scope serves them per archived segment from the
# T-13356 index instead of materializing every row. The one any-type question (a row at a `ts`) is
# answered by the ladder's whole-corpus re-resolve on the two refusals it can change.
DECIDE_ROW_TYPES = frozenset({"external_audit_completed", "audit_prompt_sent", "ceiling_decision",
                              "worktree_synced", "commit_landed", "session_started", "owner_directive"})


def _typed_cross_instance(thunk, types):
    """T-13364 — the cross-instance delta cut to `types`: the host thunk computes it typed when it takes
    `types` (the cli wiring), else (a bare thunk) its rows are filtered here."""
    try:
        params = inspect.signature(thunk).parameters
    except (TypeError, ValueError):
        params = {}
    if "types" in params:
        return thunk(types=types)
    return [r for r in thunk() or () if isinstance(r, dict) and r.get("type") in types]


def _any_type_axis(axis, diag) -> bool:
    """T-13364 — True for the two `_resolve_owner_directive` outcomes a NON-owner row at a ts can change:
    `directive-unresolved` (vs wrong-type) and a chain broken as `cited-row-missing` (vs cited-not-owner)."""
    return axis == "directive-unresolved" or (
        axis == "delegation-chain-broken" and (diag or {}).get("reason") == "cited-row-missing")


# ---------------------------------------------------------------------------
# INJECTS — the generated keyword-only inject roster per mover (host stayers, host globals,
# lib aliases, moved siblings). `audit._ceiling_inject(kw, name)` reads it at call time.
# ---------------------------------------------------------------------------
INJECTS = {
    'cmd_audit_decide': ('AUDIT_DECIDE_STDIN_CONFLICTING_ARGV_FLAGS', 'AUDIT_DECIDE_STDIN_KEYS', 'EXPECTED_SESSION_REF_ENV', 'ON_DECISIONS_ABSORPTION_BASIS', '_accept_reason_quotes_directive', '_ceiling_row_of', '_currency_finding_index', '_decide_journal_view', '_directive_row_text', '_git_commit_on_a_branch', '_git_strict_descendant', '_late_finding_index', '_resolve_owner_directive', '_ship_contained_record_only', 'decision_names_subject', 'late_finding_refs_by_fp', 'observe', 'on_decisions_admission', 'on_decisions_bind', 'plan_gate_synthetic_ceiling_row', 'prior_audit_record', 'row_residual_fingerprints', 'state', 'terminal_ceiling_row', 'textutil', 'validate_ceiling_payload'),
    'on_decisions_admission': ('on_decisions_bind',),
    'on_decisions_absorption_grant': ('ON_DECISIONS_ABSORPTION_BASIS', '_ceiling_row_of', 'on_decisions_row_absorbable'),
    'on_decisions_bind': ('decision_names_subject',),
    'on_decisions_matrix': ('read_time_finding_key', 'verdict_excluding_late'),
    'on_decisions_packet_block': (),
    'on_decisions_projection': (),
    'on_decisions_residuals': ('_currency_finding_index', '_late_finding_index', 'row_residual_fingerprints'),
    'on_decisions_row_absorbable': ('ON_DECISIONS_BASIS',),
    'on_decisions_row_problems': ('validate_ceiling_payload',),
    '_on_decisions_row_is_real': ('ON_DECISIONS_BASIS', '_decide_row_is_for'),
    'plan_gate_synthetic_ceiling_row': (),
    'prior_audit_record': ('audit_yaml_path', 'state'),
    'row_residual_fingerprints': ('CURRENCY_BASIS', 'DEGRADED_FINDING_FINGERPRINT_VERSION', 'FINDING_FINGERPRINT_VERSION', 'is_non_defect_finding', 'prior_audit_record', 'read_time_finding_key'),
    '_red_cause_is_card_record': ('_RED_CAUSE_AC_RE', '_RED_CAUSE_FIX_FIELD', '_RED_CAUSE_REPRO_FIELD', '_ac_named_verifier_paths', '_card_declared_ac_ids', '_fix_edit_fenced_invocation_paths', '_fix_invocation_exempt_paths', '_repo_path_tokens'),
    '_ac_named_verifier_paths': ('_repo_path_tokens',),
    '_accept_reason_quotes_directive': (),
    '_currency_finding_index': ('CURRENCY_BASIS', 'finding_key_of'),
    '_directive_covers_task': ('_directive_row_text', '_prose_names_token'),
    '_directive_row_text': (),
    '_late_finding_index': ('finding_key_of',),
    'residual_finding_records': ('finding_key_of',),
    '_prose_names_token': (),
    '_repo_path_tokens': (),
    '_resolve_owner_directive': ('_directive_covers_task', '_directive_row_text'),
}


def cmd_audit_decide(args, *, DECISIONS_DIR, EVENTS_PATH, REPO_ROOT, TASK_ID_RE, AUDIT_PASS_CEILING,
                     _append_event, _count_audit_passes, _die, _find_task_yaml, _git_resolve_sha,
                     _iter_events, _plan_content_hash, _resolve_session_ref,
                     _utc_now_iso, _with_repo_lock,
                     PLANS_DIR=None, PLAN_CONSULT_GATES=(), _PLAN_CONSULT_GATE_AUDIT=None,
                     _plan_gate_prior_passes=None, _plan_gate_recorded_signature=None,
                     _plan_card_set_fingerprint=None,
                     _plan_consult_gate_audit_record=None, _load_draft=None,
                     _plan_gate_template_of=None,
                     _cross_instance_events=None, _cross_instance_path=None,
                     _evidence_subject_refusal=None,
                     _find_receiving_task_yaml=None,
                     _t12614_authored_paths=None, _t12614_prior_record=None, _t12926_card_cause=None, _t12926_chain=None, AUDIT_DECIDE_STDIN_CONFLICTING_ARGV_FLAGS, AUDIT_DECIDE_STDIN_KEYS, EXPECTED_SESSION_REF_ENV, ON_DECISIONS_ABSORPTION_BASIS, _accept_reason_quotes_directive, _ceiling_row_of, _currency_finding_index, _decide_journal_view, _directive_row_text, _git_commit_on_a_branch, _git_strict_descendant, _late_finding_index, _resolve_owner_directive, _ship_contained_record_only, decision_names_subject, late_finding_refs_by_fp, observe, on_decisions_admission, on_decisions_bind, plan_gate_synthetic_ceiling_row, prior_audit_record, row_residual_fingerprints, state, terminal_ceiling_row, textutil, validate_ceiling_payload) -> None:
    """SPEC-0204 rule 2 — record ONE typed Controller decision for ONE residual of a ceiling row.

    `bin/yitc-v2 audit decide --task T-XXXX --stage pre|post --finding <fp>
     --disposition fix|accept|defer --reason … --directive <locator>
     [--receiving T-YYYY] [--evidence <revision>]`

    TWO TARGET KINDS, ONE LADDER (the plan-gate arm, T-12335): `--plan <slug> --gate <id>` decides a
    residual of a PLAN GATE's ceiling row on identical terms — same refusal seam, same
    `read_gate_refused` kinds, same append-only `ceiling_decision` event. Exactly FOUR axes are
    target-shaped and each is marked at its own site: which id shape is valid, where `prior_passes` is
    read from, what `subject_revision` is, and what a `fix`'s evidence must be. The plan-gate pass that
    consumes these decisions is `plan stage <NEXT> --on-decisions` (see the wrong-door refusal in
    `cmd_audit` for why it is not carried here).

    It appends exactly ONE `ceiling_decision` row carrying every rule-2 key and does nothing else:
    no worktree is required or created (D-0049), no file is written, no auditor is invoked, no pass
    is spent. The one thing it DOES take is the repo's existing cross-session lock, held across the
    journal read, the duplicate check and the append so that two concurrent Controller calls on the
    same residual cannot both observe «no decision yet» — see THE CRITICAL SECTION below. Every admission axis is FAIL-CLOSED, emits exactly ONE `read_gate_refused` with its own
    distinct `kind`, exits nonzero, and writes NO `ceiling_decision` row — the loud-failure discipline
    SPEC-0165 asks of each axis, so a refusal is never a silent no-op.

    THE CORPUS IS FOLDED, NOT THIS CHECKOUT'S (T-12338, rule 3 / SPEC-0168). `_cross_instance_events`
    — when the host wires it — yields the rows the SPEC-0168 fold found in the OTHER checkout's
    journal and not in this one, and the ladder resolves the ceiling row, its `passes`, its residual
    fingerprints and the `--directive` locator over the UNION. Rule 3 already promised the reader
    side of this («decisions from `main`'s journal are visible to an audit running in the card's
    worktree through the EXISTING SPEC-0168 folded corpus»); the writer read one checkout, which is
    the asymmetry this closes. Why a DELTA rather than a whole folded corpus — and why the own
    instance must keep coming through `_iter_events` inside the lock — is in `_decide_journal_view`.
    The decision row is still appended to the checkout the verb RUNS in, unchanged; the
    `--on-decisions` admission already folds both sides. An unwired hook keeps today's read exactly.
    The `defer` receiving card follows the same two checkouts (T-12919): `_find_receiving_task_yaml`,
    when wired, also finds a card filed in the other checkout that fold reads — see axis (vii).

    The `read_gate_refused` KIND vocabulary is open at this seam by shipped precedent, not by this
    card: C1 already emits `finding-fields-missing` and `task close` emits `post-verification-fill`,
    both through this same direct `_append_event` route. (`_emit_read_gate_refused`'s docstring
    describes the enum of the THREE categories IT emits — the read-check / stage-correspondence /
    verification-exists gates — which is a different, narrower set than the event's own.)"""
    # T-11249 / X-0970 — the checkout-provenance line, on the SAME terms as `plan check` /
    # `plan stage` / `audit consult`: with the plan-gate arm this verb READS a tree-local record (the
    # gate's recorded pass count and its saved gate-audit YAML), and a decision recorded against the
    # wrong checkout's record is exactly the confusion that render exists to prevent. Printed FIRST,
    # above every gate, so it is present on a refusal too.
    print(observe.checkout_provenance_line(REPO_ROOT, verb="audit decide"), file=sys.stderr)
    # ── T-12617 (E-0054, X-1427): the SHELL-PROOF INGEST FORK, before any local is read ──────────
    # The escape every prose-bearing sibling already carries (`task commit` / `work commit` /
    # `blocked-on-land` / `worktree park` / `task update` / `followup add`), arriving here last and
    # for the sharpest reason: this verb's `--reason` lands in an APPEND-ONLY row (rule 4), so the
    # damage an argv shell does is permanent. stdin never rides a shell, so a reason carrying
    # backticks reaches the row intact.
    #
    # HOISTED ABOVE the locals deliberately, so ONE reading of every field serves BOTH routes and the
    # escape can never become a second, weaker validator (the discipline `cmd_blocked_on_land` states
    # at its own fork). Fail-closed on a conflict: a field passed BOTH on argv and in the mapping is
    # REFUSED here, before any read and any emit, naming the flag and the key.
    from_stdin = bool(getattr(args, "from_stdin", False))
    stdin_reason = None
    if from_stdin:
        _fields = textutil.stdin_mapping_ingest(
            args, AUDIT_DECIDE_STDIN_CONFLICTING_ARGV_FLAGS, stdin_text=sys.stdin.read(),
            die=_die, carries="the decision fields",
            recognised=AUDIT_DECIDE_STDIN_KEYS, argv_dests=set(vars(args)), verb="audit decide")
        for _key in AUDIT_DECIDE_STDIN_KEYS:
            if _key in _fields:
                setattr(args, _key, _fields[_key])
        # THE REASON IS KEPT VERBATIM (audit-pre pass 1, fp1:0405e8cf26125d55 / AC1). Every other
        # field below is `str(...).strip()`ed, which is right for the id-shaped ones — but a reason
        # is PROSE, and stripping it would mean the row does not store what the author wrote. The
        # whole promise of this route is a byte-for-byte round trip, so the raw value is carried
        # separately here and `.strip()` is used ONLY to answer the existing non-emptiness question.
        if "reason" in _fields and _fields["reason"] is not None:
            stdin_reason = str(_fields["reason"])
    tid = str(getattr(args, "task", "") or "").strip()
    stage = str(getattr(args, "stage", "") or "").strip()
    # ── SPEC-0204 PLAN-GATE ARM (T-12335) — the SECOND target kind, on the SAME ladder ─────────────
    # The verb's whole admission ladder is generic over an opaque pair; what a plan target changes is
    # exactly FOUR axes and nothing else: which id shape is valid, where `prior_passes` is read from,
    # what `subject_revision` is, and what a `fix`'s evidence must be. Every other axis below — the
    # worker-context gate, the directive resolution, the residual membership, the late-finding rule,
    # the `accept` quote, the `defer` receiving card, the duplicate check, the payload validator — is
    # the task arm's, called with `(slug, gate)` in place of `(tid, stage)`.
    plan_slug_arg = str(getattr(args, "plan", "") or "").strip()
    gate = str(getattr(args, "gate", "") or "").strip()
    is_plan = bool(plan_slug_arg)
    #: The TARGET pair every generic helper below is keyed on. For a plan gate the `stage` slot IS the
    #: gate id — the identity SPEC-0124 established and `ceiling_ref` names — never the audit TEMPLATE
    #: name, which is the RECORD's name and is carried beside it (the T-11250 discipline).
    target_id = plan_slug_arg if is_plan else tid
    target_key = gate if is_plan else stage
    finding_fp = str(getattr(args, "finding", "") or "").strip()
    disposition = str(getattr(args, "disposition", "") or "").strip()
    # VERBATIM on the stdin route, stripped on argv (AC1 / AC4): the argv path keeps its
    # pre-T-12617 normalization byte-for-byte, and only the shell-proof route — whose entire point
    # is fidelity — stores exactly what was piped in.
    reason = stdin_reason if stdin_reason is not None else str(getattr(args, "reason", "") or "").strip()
    # RAW — the resolver `fullmatch`es the argument AS GIVEN (audit-post finding 2, pass 2), so the
    # padding must still be there when it gets there. Only the ABSENT/blank test below strips, and
    # only to answer a different question («was an argument supplied at all?» — `directive-missing`),
    # never to normalize a supplied one into resolving.
    locator = str(getattr(args, "directive", "") or "")
    receiving = str(getattr(args, "receiving", "") or "").strip()
    evidence = str(getattr(args, "evidence", "") or "").strip()
    decision_ts = _utc_now_iso()

    def _ceiling_subject_commit(ceiling_row) -> str | None:
        """T-12367 (SPEC-0204 rules 2/4) — THE AUDITED COMMIT this verb records and checks against
        at post: the CEILING ROW's OWN subject, never the task's latest `commit_landed`.

        A decision binds to ONE `ceiling_ref`, and the residual it decides was fingerprinted at THAT
        row's subject — so the revision the `fix` descendant check is measured from, and the
        `subject_revision` the row records, are both the ceiling row's `commit` (written by every
        post completion, stored SHORT, so it is resolved here), with the saved record's `commit:`
        as the legacy fallback for a row that carries none. ONE resolver for BOTH readers, so the
        revision a decision is REFUSED against and the revision it BINDS to can never disagree —
        and `on_decisions_admission` reads `ceiling_subject_revision` back off these decisions, so
        the rule-3 pass agrees with them by construction.

        WHY NOT ANY `commit_landed` reader (measured on T-12327, 2026-09-10): chain A (RED at the
        ceiling, the row's commit) → B (the fix, `task commit --fix-red`) → C (`task pause`
        self-commit, kind=pause). The kind-blind D-0082 value is C, so `--evidence B` refused
        «not a descendant of C»; the T-12362 custody reader (bookkeeping transparent) is B, so the
        same call refused «the audited commit itself». Under BOTH the rule-2 `fix` route had no
        admissible evidence at all. The ceiling row names A, and B is its strict descendant."""
        data = ceiling_row.get("data") if isinstance(ceiling_row, dict) else None
        data = data if isinstance(data, dict) else {}
        raw = str(data.get("commit") or "").strip()
        if not raw:
            rec = prior_audit_record(tid, stage, decisions_dir=Path(DECISIONS_DIR))
            raw = str((rec or {}).get("commit") or "").strip()
        if not raw:
            return None
        return _git_resolve_sha(raw) or None

    def _ceiling_subject_plan_fp(ceiling_row, local_record) -> str | None:
        """T-12383 (SPEC-0204 rule 2, amended) — THE AUDITED PLAN FINGERPRINT at pre, the exact
        sibling of `_ceiling_subject_commit` above: the CEILING ROW's own `plan_fingerprint` first
        (stamped by every pre completion since T-12383, so it arrives through the SPEC-0168 fold and
        main answers exactly as the worktree does), the saved record's second — the LEGACY fallback
        for a pre-stamp row, and never the sole source.

        WHY NOT THE RECORD ALONE (measured on <project> T-0552, X-1371, 2026-09-11): the record is
        the untracked `decisions/<tid>-audit-pre.yaml` of the checkout the verb RUNS in, and the
        sanctioned posture — a no-worktree journal append from main (rule 2, D-0049) — holds none, so
        the record-only read yielded None and the row recorded `subject_revision: null`. WHY NOT THE
        CARD'S CURRENT PLAN as a third source: rule 3's arm 1 compares the current plan fingerprint
        AGAINST this value, so a value taken FROM the current plan makes that arm vacuous — the
        decision would bind to whatever the plan happens to be at decide time, not to the plan the
        residual was found on. None here is refused by name at the call site, never written."""
        data = ceiling_row.get("data") if isinstance(ceiling_row, dict) else None
        data = data if isinstance(data, dict) else {}
        fp = str(data.get("plan_fingerprint") or "").strip()
        if not fp:
            fp = str((local_record or {}).get("plan_fingerprint") or "").strip()
        return fp or None

    def _refuse(kind: str, why: str, message: str, extra=None) -> None:
        """The ONE refusal seam: journal the axis, then die. The emit is wrapped so a journal write
        error can NEVER mask the refusal (the `_emit_read_gate_refused` best-effort idiom)."""
        payload = {"verb": "audit decide", "action": "record a ceiling decision",
                   "kind": kind, "stage": target_key, "reason": why}
        if is_plan:
            payload.update({"target_kind": "plan", "plan_slug": plan_slug_arg, "gate": gate})
        if extra:
            payload.update(extra)
        try:
            _append_event("read_gate_refused", (None if is_plan else (tid or None)), payload)
        except (Exception, SystemExit):     # noqa: BLE001 — never let journaling mask the refusal
            pass
        _die(f"audit decide: {message}")

    if is_plan and tid:
        _die("audit decide: pass EITHER --task (with --stage) OR --plan (with --gate), never both — "
             "a decision binds to ONE ceiling row (SPEC-0204 rules 2 + 4).")
    if is_plan:
        if gate not in tuple(PLAN_CONSULT_GATES or ()):
            _die(f"audit decide: --gate is REQUIRED with --plan and must be one of "
                 f"{list(PLAN_CONSULT_GATES or ())} (the SPEC-0124 ceiling-bearing plan gates, INV-1); "
                 f"got {gate!r}")
        if stage:
            _die("audit decide: --stage is the TASK axis (pre|post) — a plan gate is named by --gate.")
        # The slug must resolve to a PLAN, not merely look like one: `TASK_ID_RE` is the wrong shape
        # here and «any non-empty string» would let a typo bind a decision to a ceiling row nobody can
        # ever find. Read through the host's own plan loader so there is one notion of «this plan
        # exists» (a missing plan makes `_load_draft` die with its own message).
        if PLANS_DIR is None or _load_draft is None:
            _die("audit decide --plan: the plan collaborators are not wired at this call site "
                 "(engine defect — report it).")
        _load_draft(plan_slug_arg, dirs=(PLANS_DIR,))
    else:
        if not TASK_ID_RE.fullmatch(tid):
            _die(f"audit decide: --task {tid!r} is not a T-NNNN id")
        if gate:
            _die("audit decide: --gate names a PLAN gate — pass --plan <slug> with it.")
        if stage not in ("pre", "post"):
            _die(f"audit decide: --stage must be pre|post (got {stage!r})")
    if disposition not in CEILING_DECISION_DISPOSITIONS:
        _die(f"audit decide: --disposition must be one of {', '.join(CEILING_DECISION_DISPOSITIONS)}")
    if not finding_fp:
        _die("audit decide: --finding <fingerprint> is required")
    # The non-emptiness question is asked of the STRIPPED form on BOTH routes — a stdin reason of
    # pure whitespace is as empty as an absent one — while the value STORED stays whatever the route
    # above resolved. Not argparse-`required` since T-12617: `--reason` may arrive in the stdin
    # mapping instead, so its absence is a GOVERNED refusal here, the posture `--directive` already
    # takes at this seam.
    if not reason.strip():
        _die("audit decide: --reason is required and must be non-empty (rule 2) — pass it on argv, "
             "or carry it as `reason:` in the --from-stdin YAML mapping")

    # (i) WORKER CONTEXT. Rule 2 keeps «no self-grant past the ceiling» by the AUTHORITY OF THE
    # WRITER, not by budget arithmetic: the dispatched Worker that hit the ceiling HALTS
    # (SPEC-0103 §3) and the CONTROLLER decides. Checked FIRST — before any read — because a worker
    # must not be able to learn the residual set by probing this verb's later refusals.
    # PRESENCE, not truthiness (audit-post finding 2). `EXPECTED_SESSION_REF_ENV` is a contract var
    # the LAUNCHER sets; a process carrying it EMPTY is still a dispatched worker, and a truthiness
    # read would have let one through with `YITC_EXPECTED_SESSION_REF=""`. This deliberately differs
    # from the truthiness reading in `run_auditor_subprocess` above: that one shapes an OBSERVABILITY
    # heartbeat, where reading an empty carrier as "not a worker" costs a log line; this is an
    # AUTHORITY gate, where it costs the whole «no self-grant past the ceiling» property.
    if EXPECTED_SESSION_REF_ENV in os.environ:
        _refuse("worker-context", "dispatched_worker_context",
                f"{target_id} — a ceiling decision is the CONTROLLER's (SPEC-0204 rule 2). This process "
                f"carries {EXPECTED_SESSION_REF_ENV}, i.e. it is a dispatched Worker: HALT with "
                f"`bin/yitc-v2 blocked-on-land"
                + (f" --task {tid}" if not is_plan else "")
                + " <reason>` naming your residual fingerprints and let the Controller decide.")

    # (i-bis) ARGV BACKTICK. T-12617 (E-0054, X-1427) — the refusal half of the fork above, and the
    # one that protects the APPEND-ONLY row. Placed immediately AFTER the worker-context gate, which
    # keeps its «checked FIRST, before any read» property (a worker must not learn the residual set
    # by probing later refusals), and still BEFORE every journal read and every write.
    #
    # ARGV ONLY. On the `--from-stdin` route there is no shell in that position — it is the escape
    # this very refusal prescribes — so firing there would cry wolf at correct usage, which is how a
    # guard teaches the reader to skim it (the X-0599 erosion class the sibling WARN names).
    #
    # WHAT THIS DOES NOT CLAIM, stated at the seam so it cannot erode: the SHELL RUNS BEFORE THIS
    # VERB EXISTS. A balanced backtick span on a double-quoted argv has ALREADY been executed and
    # replaced by its stdout before Python sees anything, and that stdout may carry no backtick at
    # all. So this refusal cannot PREVENT the execution half of X-1427 — no argv-side check can. It
    # refuses the WRITE whenever a backtick SURVIVED, so a partly-substituted reason never becomes an
    # uncorrectable governance record. Preventing the execution is what `--from-stdin` is for.
    _backtick = (None if from_stdin else textutil.argv_backtick_span(reason))
    if _backtick:
        _refuse("reason-argv-backtick", "reason_carries_argv_backtick",
                f"{target_id} — the --reason passed on argv carries a backtick, which is REFUSED "
                f"before anything is written (T-12617 / X-1427):\n"
                f"  ...{_backtick.strip()}...\n"
                f"  A `ceiling_decision` row is APPEND-ONLY (SPEC-0204 rule 4) — it can never be "
                f"corrected — and argv rides the SHELL, which substitutes a `...` span before this "
                f"verb runs. Measured: a reason quoting a script in backticks EXECUTED that script "
                f"against a live sandbox and wrote 7947 characters of its stdout into the recorded "
                f"decision, with the quoted name absent from it.\n"
                f"  Use the shell-proof route — pipe the fields as a YAML mapping:\n"
                f"    printf 'reason: |\\n  <your prose>\\n' | bin/yitc-v2 audit decide "
                f"--from-stdin <the same target/finding/disposition/directive flags>\n"
                f"  (or drop the backticks from the argv reason). NOT a guarantee that a reason "
                f"WITHOUT a surviving backtick is intact: a span the shell fully substituted leaves "
                f"none, which is exactly why the stdin route — not this check — is the fix.",
                extra={"excerpt": _backtick[:200]})

    card = {}
    if not is_plan:
        task_path = _find_task_yaml(tid)
        if task_path is not None:
            try:
                card = state.load_str(task_path.read_text(encoding="utf-8")) or {}
            except (OSError, ValueError, TypeError):
                card = {}
        # T-13148 (X-1699): a pre-stage `fix` names the plan fingerprint the WORKER wrote — in its own
        # live `task/<id>` worktree card, not yet landed. From main the local card carries no plan, so
        # the plan is read from the SAME other checkout the T-12919/T-12836 fold reads. ONLY the plan
        # field is taken: the local card stays authoritative for everything else (`decomposed_from`
        # and `cites` feed directive admission — a worker-owned card must not widen it, audit-pre
        # fp1:3ab10ea1891fa2b1). Any failure keeps the local card, so the refusal is today's.
        # TASK TARGETS ONLY by construction: this sits inside the `if not is_plan:` arm above, so a
        # plan-gate decision (whose `stage` slot is empty and whose `fix` evidence is the gate's own
        # signature) never reaches it — audit-post fp1:7480db32b9418474.
        if (stage == "pre" and disposition == "fix" and _cross_instance_path is not None
                and not str(card.get("implementation_plan") or "").strip()):
            try:
                _other = _cross_instance_path()
                _matches = (sorted((Path(_other).parent / "tasks").glob(f"{tid}-*.yaml"))
                            if _other else [])
                if len(_matches) == 1:
                    _remote = state.load_path(_matches[0]) or {}
                    _remote_plan = (_remote.get("implementation_plan")
                                    if isinstance(_remote, dict) else None)
                    if str(_remote_plan or "").strip():
                        card = {**card, "implementation_plan": _remote_plan}
            except (OSError, ValueError, TypeError):
                pass
    # The PLAN a directive may name in place of the target. For a TASK that is the plan the card is
    # `decomposed_from`; for a PLAN target the target IS the plan, and passing it again would only
    # duplicate the arm `_directive_covers_task(row, target_id)` already covers token-exactly — so it
    # stays None there rather than widening the coverage test.
    plan_slug = (None if is_plan
                 else (str(card.get("decomposed_from") or "").strip() or None))

    # THE CRITICAL SECTION (audit-post pass-3 RED, fp1:f571ec95fe26b8e1). The duplicate check (ix)
    # reads the `ceiling_decision` rows recorded SO FAR and the append writes one; between them sits
    # the whole admission ladder. Unserialized, two Controller invocations with the same (task,
    # stage, ceiling_ref, fingerprint) both observe no existing decision, both append, and rule 4's
    # «ONE decision per (ceiling_ref, fingerprint), never edited» is broken by a race the refusal
    # axis cannot see — so the READ, the CHECK and the APPEND run inside ONE critical section and
    # the second call refuses `decision-duplicate` as rule 4 requires.
    #
    # THE SCOPE STARTS AT THE READ, NOT AT THE CHECK, and that is a correctness bound rather than a
    # convenience: the wiring site installs ONE request-scoped ReadScope over the journal
    # (`cli.py#cmd_audit_decide`, SPEC-0190 rule 10), so a SECOND `_iter_events` fold taken inside a
    # narrower lock would be served from the memo — i.e. it would re-read the same pre-lock rows and
    # serialize nothing. Holding the lock from the one read the verb already takes is what makes the
    # duplicate check observe a state no peer can still be about to change.
    #
    # The lock is the repo's EXISTING cross-session `_with_repo_lock` (injected, this module's
    # established dependency style — the same one `consult_allocate_episode` takes for the episode
    # allocation): no new lock class, no new lock file, no second lock path, no retry and no timeout
    # knob (CHARTER §P1 F1, and see this module's LOCK NOTE). The section is short by construction —
    # journal + card reads and a couple of `git` resolutions, no auditor call and no file write — and
    # it is never nested inside another `_with_repo_lock`, so it stays deadlock-free. A refusal
    # raises `SystemExit` THROUGH the context manager, which releases the lock in its `finally`.
    with _with_repo_lock(REPO_ROOT):
        # T-13364 — the view holds only the row types the ladder reads (DECIDE_ROW_TYPES), served by the
        # verb's indexed scope; `view["whole"]` is the untyped corpus, read only on the two refusals below.
        view = _decide_journal_view(
            target_id, target_key, _iter_events=_iter_events, events_path=EVENTS_PATH,
            cross_instance_rows=(_typed_cross_instance(_cross_instance_events, DECIDE_ROW_TYPES)
                                 if _cross_instance_events else None),
            types=DECIDE_ROW_TYPES, whole_cross_instance=_cross_instance_events)
        rows, stage_rows = view["rows"], view["stage_rows"]

        # (i-ter) WORKER SESSION IDENTITY (T-13043). Gate (i) reads the launcher's env var, but the
        # identity actually STAMPED as `decided_by` is the rediscovered ref — and a Controller run
        # from a Worker's worktree (no launcher contract in its process) rediscovers the Worker's
        # stamp (measured: <project> T-0684/T-0690). So rule 2 is also enforced on the stamped ref:
        # ANY `session_started` of posture `build` under it refuses — ANY, not the newest, so a later
        # controller-typed start under the same ref cannot launder a Worker identity (audit-pre
        # fp1:535db1d909bd8232). Read from the view's rows (no second reader), so gate (i) still fires first.
        decided_by = _resolve_session_ref()
        if decided_by and any(
                r.get("type") == "session_started" and r.get("session_ref") == decided_by
                and (r.get("data") or {}).get("type") == "build"
                for r in rows):
            _refuse("worker-session-identity", "dispatched_worker_session_identity",
                    f"{target_id} — the deciding session resolved to {decided_by}, a dispatched "
                    f"Worker (`session_started` type build); a ceiling decision is the CONTROLLER's "
                    f"(SPEC-0204 rule 2). Run `audit decide` from the MAIN checkout carrying your own "
                    f"Controller session ref (YITC_SESSION_REF=<your ref>) — NOT with `-C <worker "
                    f"worktree>`, where the worktree stamp is the selected identity (SPEC-0137 "
                    f"Rule 3, T-13362).")

        # (ii) PAST THE CEILING. Three causes, ONE axis: there is no completion row for this
        # (target, key) at all, the ceiling row's own `passes` cannot be resolved, or the recorded
        # pass count is below the ceiling. The second is not pedantry — `ceiling_ref` IS `pass-<N>`
        # read from that counter, and C1's read path returns `None` for an unresolvable one with the
        # explicit warning that no caller may treat it as a number. A decision that cannot name its
        # ceiling row durably is not provably past the ceiling.
        #
        # THE ORDER IS THE ROW FIRST, THE COUNT SECOND (T-12338), and that is the change: the pass
        # COUNT is read from `decisions/<tid>-audit-<stage>.yaml`, which a dispatched worker wrote
        # inside its OWN worktree — so a Controller deciding from MAIN was told «0 recorded pass(es)»
        # about a card sitting two passes deep (measured on T-12335). The ceiling ROW carries the
        # same counter and now arrives through the FOLDED corpus, so it can answer where the file
        # cannot. Resolving the row before the count is what makes that answer available; the two
        # refusals keep their kinds and their messages, only their order moves.
        #
        # THE CEILING ROW — resolved in a FIXED ORDER, with the second source live for a plan gate
        # only (T-12335, C-A2). (1) the journal row for this target pair; (2) failing that, a READ-TIME
        # SYNTHETIC row built purely from the saved gate record. A plan gate whose ceiling was reached
        # BEFORE this arm shipped has NO row and never will — `plan_gate_ceiling_row_payload` only
        # covers future runs — so without (2) the two consumer plans this arm exists to unwedge would
        # stay exactly as wedged as they are. It is NOT a backfill: nothing is appended, and the row is
        # a pure f(record) carrying `synthesized_from`. A TASK target keeps source (1) alone, unchanged.
        _gate_record = None
        ceiling_row = _ceiling_row_of(stage_rows) if stage_rows else None
        if ceiling_row is None and is_plan:
            if _plan_consult_gate_audit_record is None:
                _die("audit decide --plan: `_plan_consult_gate_audit_record` is not wired at this call "
                     "site (engine defect — report it).")
            _gate_record = _plan_consult_gate_audit_record(plan_slug_arg, gate) or None
            if _gate_record:
                _tmpl = (_plan_gate_template_of(gate) if _plan_gate_template_of else gate)
                _pat = ((_PLAN_CONSULT_GATE_AUDIT or {}).get(gate) or (None,))[0]
                ceiling_row = plan_gate_synthetic_ceiling_row(
                    plan_slug_arg, gate, _tmpl, _gate_record,
                    saved_to=(f"decisions/{_pat.format(slug=plan_slug_arg)}" if _pat else None))
        if ceiling_row is None:
            _refuse("below-ceiling", "no_completion_row",
                    f"{target_id} audit-{target_key} has no `external_audit_completed` row in the "
                    f"journal"
                    + (" and no saved gate-audit record to resolve one from" if is_plan else "")
                    + " — there is no ceiling row to bind a decision to (SPEC-0204 rule 2).")
        residual = row_residual_fingerprints(ceiling_row, repo_root=[REPO_ROOT],
                                             decisions_dir=DECISIONS_DIR, record=_gate_record,
                                             # T-12370 — same reader, same seam: a decision must not
                                             # be refused `unresolvable` for a subject that was
                                             # merely rolled back.
                                             commit_reachable=(lambda _s: _git_commit_on_a_branch(
                                                 _s, repo_root=REPO_ROOT)))
        # ONE read of this checkout's saved record, shared by the two questions below that ask about
        # it — the `passes` fallback and the «does this checkout hold a record at all?» test. Taking
        # it twice would let the two disagree under a concurrent write. For a PLAN GATE the record is
        # the gate's own saved gate-audit YAML (resolved by its gate→template map, T-12335), never
        # the task-shaped `decisions/<id>-audit-<stage>.yaml` address.
        if is_plan:
            local_record = _gate_record
            if local_record is None and _plan_consult_gate_audit_record is not None:
                local_record = _plan_consult_gate_audit_record(plan_slug_arg, gate) or None
        else:
            local_record = prior_audit_record(tid, stage, decisions_dir=Path(DECISIONS_DIR))
        passes = residual.get("passes")
        if passes is None:
            # The SAME resolution chain C1 documents (the row's own value first, the saved record's
            # EXPLICIT value second — never `_passes_recorded`, whose legacy default of 1 for an absent
            # field is a real ceiling value and would make a record stating NOTHING answer "not a ceiling
            # row"). C1 walks it for a row carrying no findings; a legacy row that carries findings but
            # no counter reaches here instead, and must read the record the same way.
            rec_passes = (local_record or {}).get("passes")
            passes = int(rec_passes) if isinstance(rec_passes, int) else None
        if passes is None:
            _refuse("below-ceiling", "ceiling_row_passes_unresolved",
                    f"{target_id} audit-{target_key}: the ceiling row records no `passes` counter and "
                    f"its saved "
                    f"record states none either, so `ceiling_ref` cannot name a pass — the decision "
                    f"would not be durably bound to a ceiling row (SPEC-0204 rule 2).")
        ceiling_ref = f"{target_id}/{target_key}/pass-{passes}"

        # The pass COUNTER. The saved record stays the authority WHEREVER THIS CHECKOUT HOLDS ONE —
        # deliberately not a `max()` of the two sources (T-12338): a record stating 1 beside a row
        # claiming 2 is a disagreement this verb must keep refusing, not paper over. The folded row's
        # own counter answers ONLY the case the record cannot be asked at all — no
        # `decisions/<tid>-audit-<stage>.yaml` in this checkout, because it was written in the
        # worker's worktree and this is main (or the reverse). `passes` is an int here by
        # construction: the refusal above returned on `None`.
        # PRIOR PASSES — the ONE axis whose SOURCE differs by target (T-12335). A plan gate's counter
        # lives in its own saved gate-audit YAML (`_plan_gate_prior_passes` reads the SAME counter the
        # gate itself enforces), not in the task audit records `_count_audit_passes` folds.
        if is_plan:
            if _plan_gate_prior_passes is None:
                _die("audit decide --plan: `_plan_gate_prior_passes` is not wired at this call site "
                     "(engine defect — report it).")
            prior_passes = _plan_gate_prior_passes(plan_slug_arg, gate)
        else:
            prior_passes = _count_audit_passes(tid, stage)
        if local_record is None:
            prior_passes = passes
        # T-12510 — A RECORDED LATE FINDING IS DECIDABLE AT ANY PASS (rule 2), so the pass-count
        # guard below does not apply to it. Measured on T-12466: a reship reset the saved record to
        # `passes: 1`, and the pass-2 late finding became undecidable while `task close` still
        # refused `late_findings_undecided`. The index is pure over `stage_rows` and is read again at
        # (iv); the guard for a NON-late residual is unchanged.
        late_index = _late_finding_index(stage_rows, target_id, target_key, repo_root=[REPO_ROOT])
        if prior_passes < AUDIT_PASS_CEILING and finding_fp not in late_index:
            _refuse("below-ceiling", "prior_passes_below_ceiling",
                    f"{target_id} audit-{target_key} has {prior_passes} recorded pass(es), below the "
                    f"{AUDIT_PASS_CEILING}-pass ceiling — a ceiling decision only exists AFTER the "
                    f"ceiling is reached (SPEC-0204 rule 2). Absorb inline instead (LIFECYCLE §Stage 4).",
                    {"prior_passes": prior_passes, "pass_ceiling": AUDIT_PASS_CEILING})

        # (ii-b) CEILING-TERMINAL (T-12613 / SPEC-0204 rule 4, X-1433 + X-1434). A stage whose
        # `--on-decisions` (or absorption re-audit) pass came back RED is ENDED: the only consumer of
        # a pre-stage decision is that pass, which `cmd_audit` refuses `ceiling-terminal` by name —
        # so a decision recorded here could NEVER be spent, and it reads to the operator as a route
        # (<project> T-0646: a second `fix` recorded 29 minutes after the terminal RED, and the plan
        # amended on the strength of it). The SAME predicate the reader consults, the SAME kind and
        # the SAME `reason` tokens, so the closed asymmetry is legible in the journal. Ordered after
        # (ii) by construction: a terminal stage is past the ceiling. A PLAN target is never
        # terminal here (rule 9(f) — the predicate answers None for it; see its docstring).
        _terminal = terminal_ceiling_row(("plan" if is_plan else "task"), stage_rows, rows,
                                         target_id, target_key)
        if _terminal is not None:
            _term_data = _terminal.get("data") if isinstance(_terminal.get("data"), dict) else {}
            _term_absorption = str(_term_data.get("basis") or "") == ON_DECISIONS_ABSORPTION_BASIS
            _term_mi = str(_term_data.get("basis") or "") == MERGE_INTEGRATION_BASIS   # T-13260
            _term_label = ("post-GREEN MERGE-INTEGRATION pass (T-13260)" if _term_mi else
                           f"SPEC-0204 rule-3 {'ABSORPTION re-audit' if _term_absorption else 'pass'}")
            _refuse("ceiling-terminal",
                    ("merge_integration_pass_returned_red" if _term_mi
                     else "absorption_reaudit_returned_red" if _term_absorption
                     else "on_decisions_pass_returned_red"),
                    f"{target_id} audit-{target_key}: TERMINAL. The {_term_label} "
                    f"({_term_data.get('ceiling_ref') or 'merge-integration'}, recorded {_terminal.get('ts')}) came back "
                    f"RED, which ENDED this stage for this card (rule 4): no further `audit "
                    f"{target_key}` runs here, so a decision bound to {ceiling_ref} could never be "
                    f"consumed — it is refused rather than recorded as a route nobody can take. The "
                    f"exits are the EXISTING terminals — `yitc-v2 task update --status "
                    f"parked|wont-do {target_id}`, `yitc-v2 worktree park`, or a NEW card carrying "
                    f"the remaining work. Land eligibility (SPEC-0077) is unchanged.",
                    {"ceiling_ref": ceiling_ref, "terminal_at": _terminal.get("ts"),
                     "terminal_ceiling_ref": _term_data.get("ceiling_ref")})

        # (ii-c) T-13260 — the post-GREEN merge-integration pass is FINAL for a task's audit-post: no
        # `--on-decisions` pass follows it (`cmd_audit` refuses `merge_integration_pass_is_final`), so a
        # decision recorded after it could never be consumed. Same kind + reason as the reader
        # (writer/reader parity, X-1433). A plan target never carries that basis.
        _mi_row = None if is_plan else merge_integration_row(stage_rows)
        if _mi_row is not None:
            _refuse("ceiling-terminal", "merge_integration_pass_is_final",
                    f"{target_id} audit-{target_key}: the post-GREEN merge-integration pass (recorded "
                    f"{_mi_row.get('ts')}, {(_mi_row.get('data') or {}).get('verdict')}) is FINAL for "
                    f"this stage — no `--on-decisions` pass follows it, so a decision bound to "
                    f"{ceiling_ref} could never be consumed (T-13260, SPEC-0124).",
                    {"ceiling_ref": ceiling_ref, "merge_integration_at": _mi_row.get("ts")})

        # (iii) THE DIRECTIVE, RESOLVED. Rule 2: REQUIRED and resolved AT WRITE.
        # `.strip()` HERE and NOWHERE ELSE: this axis answers «was an argument supplied at all?», for
        # which an all-whitespace value is indistinguishable from an absent one. The RESOLUTION below
        # gets the raw value — a SUPPLIED-but-padded locator is `directive-unresolved`, not missing.
        if not locator.strip():
            _refuse("directive-missing", "directive_absent",
                    f"{target_id} — `--directive events.jsonl#ts=<ISO>` is REQUIRED: every ceiling "
                    f"decision cites the owner directive that authorizes it (SPEC-0204 rule 2).")
        # `target_id` is the token the coverage test matches — the task id for a task, the PLAN SLUG for
        # a plan gate. `_directive_covers_task`'s prose arm is `_prose_names_token`, which is token-exact
        # over the `[A-Za-z0-9_-]` alphabet both id shapes are drawn from, so a directive naming the plan
        # covers its gate decisions and one naming `plan-foobar` never covers `plan-foo`.
        # `decision_pos=len(rows)` — the slot the row this call is about to append will occupy, so
        # every row already in the corpus PRECEDES it. Stated explicitly rather than left to the
        # resolver's default, because the default is what the AC2 tripwire overrides to drive the
        # refusing arm; a caller that relied on it silently would make the two arms untestable.
        chain_diag = {}
        directive_row, axis = _resolve_owner_directive(rows, locator, target_id,
                                                      decision_ts=decision_ts,
                                                      decision_pos=len(rows), plan_slug=plan_slug,
                                                      diag=chain_diag)
        if _any_type_axis(axis, chain_diag):
            # T-13364 — a row of ANY type at a `ts` is what separates these two outcomes from their
            # siblings (unresolved vs wrong-type; cited-row-missing vs cited-not-owner), and only they can
            # differ on the typed rows: every owner_directive row is in them. So re-resolve on the
            # whole corpus — the pre-T-13364 read, paid only on these refusals.
            whole = view["whole"]()
            chain_diag = {}
            directive_row, axis = _resolve_owner_directive(whole, locator, target_id,
                                                          decision_ts=decision_ts,
                                                          decision_pos=len(whole), plan_slug=plan_slug,
                                                          diag=chain_diag)
        if axis:
            # T-12836 (X-1533) — a broken delegation chain names WHICH of its causes fired, as the
            # row's `reason`; the `kind` axis is unchanged. A missing cited row also names every
            # journal the lookup folded, so «not found here» is never read as «not recorded».
            why, cause_line, chain_extra = axis.replace("-", "_"), "", {}
            if axis == "delegation-chain-broken" and chain_diag.get("reason"):
                cause = chain_diag["reason"]
                why = "delegation_" + cause.replace("-", "_")
                cited = list(chain_diag.get("cited_ts") or ())
                chain_extra = {"cause": cause, "cited_ts": cited}
                cause_line = {
                    "no-cited-locator": "the delegated row cites no `events.jsonl#ts=<ISO>` owner row.",
                    "cited-not-owner": f"a row exists at the cited ts {cited} but it is not an "
                                       f"`owner_directive`.",
                    "cited-delegated": f"the row at the cited ts {cited} is itself "
                                       f"`controller-delegated` — the chain must END in an owner row.",
                    "cited-late": f"the owner row at the cited ts {cited} is LATER than the delegated "
                                  f"row citing it — the owner row must come first.",
                }.get(cause, "")
                if cause == "cited-row-missing":
                    other = _cross_instance_path() if _cross_instance_path else None
                    searched = [str(EVENTS_PATH)] + ([str(other)] if other else [])
                    chain_extra["journals_searched"] = searched
                    cause_line = (
                        f"NO journal row carries the cited ts {cited}. Journals searched: "
                        + "; ".join(searched)
                        + ("" if other else " (no other checkout instance was folded)")
                        + ". Owner rows are recorded on MAIN (SPEC-0204): a row sitting in an "
                          "unlanded sibling worktree is not visible here — land it (or record it on "
                          "main) rather than writing a second owner row.")
                cause_line = f" CAUSE ({cause}): {cause_line}"
            _refuse(axis, why,
                    f"{target_id} — `--directive {locator}` did not resolve to an owner directive that "
                    f"authorizes this decision ({axis}). Rule 2: authority is proven by RESOLUTION, "
                    f"never by a non-empty string — the row must exist, be an `owner_directive`, "
                    f"strictly PRECEDE this decision, ground any `controller-delegated` capture in the "
                    f"owner row it cites, and COVER this task (name it, or a plan the card is "
                    f"`decomposed_from`, or a batch listing it)."
                    + cause_line
                    # T-12401: the two axes a Controller resolves by WRITING a covering row get the
                    # concrete route; every other axis's message is byte-identical to before.
                    + (DIRECTIVE_COVERAGE_HELP
                       if axis in ("directive-not-covering", "delegation-chain-broken") else ""),
                    {"directive": locator, **({"plan": plan_slug} if plan_slug else {}),
                     **chain_extra})
        directive_text = _directive_row_text(directive_row)

        # (iv) THE FINGERPRINT IS A RESIDUAL. Resolved THROUGH C1's row-level read path — never a second
        # fingerprint computation — unioned with the `late_findings[]` rule 8 records (C4 writes them;
        # this card reads them if present).
        residual_keys = set(residual.get("keys") or ())
        # Both indexes are keyed on the TARGET pair — `(tid, stage)` for a task, `(plan slug, gate)`
        # for a plan gate (T-12382). They are pure over `stage_rows` and use that pair only to key
        # through `finding_key_of`, so passing the plan-gate pair is what makes a plan-gate residual
        # key IDENTICALLY on this side and on the ceiling-row read path above. `late_index` was read
        # before the pass-count guard (T-12510).
        # T-12422 — A THIRD NAMED SOURCE: the findings of a `basis: currency` row. An audit-currency
        # check is not one of the card's counted passes, so its findings are neither residuals of the
        # ceiling row nor rule-8 late findings — and before this arm existed, NO verb could dispose of
        # one. Measured on T-12340: an identical-cause re-raise of an owner-ACCEPTED residual came
        # back on a currency row and refused here (`residual_count=0, late_count=1`), wedging a card
        # whose residual the authority had already settled. The decision still binds at the ceiling
        # ref derived from the COUNTED ceiling row, exactly as it does for the other two sources.
        currency_index = _currency_finding_index(stage_rows, target_id, target_key,
                                                 repo_root=[REPO_ROOT])
        if (finding_fp not in residual_keys and finding_fp not in late_index
                and finding_fp not in currency_index):
            # T-12894 (X-1554) — NAME the decidable keys, not just count them: a refusal that said only
            # «8 residual(s)» left the caller to recompute keys by hand, and the canonical `fp1:`
            # function collapses every fieldless plan-gate finding onto ONE value.
            decidable = sorted(residual_keys | set(late_index) | set(currency_index))
            _refuse("fingerprint-not-residual", "fingerprint_not_a_residual",
                    f"{target_id} audit-{target_key}: {finding_fp} is neither a residual of the "
                    f"ceiling row "
                    f"({ceiling_ref}, {len(residual_keys)} residual(s)"
                    + (", UNRESOLVABLE" if residual.get("unresolvable") else "")
                    + f") nor a recorded late finding ({len(late_index)}) nor a finding of an "
                    f"audit-currency row ({len(currency_index)}). A decision binds to a "
                    f"residual of THIS ceiling row (SPEC-0204 rules 1 + 4). Run `audit decide` "
                    f"ONCE PER RESIDUAL, passing one of these engine keys verbatim: "
                    + (", ".join(decidable) or "(none resolvable)") + ".",
                    {"ceiling_ref": ceiling_ref, "finding_fingerprint": finding_fp,
                     "residual_count": len(residual_keys), "late_count": len(late_index),
                     "currency_count": len(currency_index),
                     "residual_fingerprints": decidable})

        # (v) A LATE FINDING ON THE RULE-3 PASS ADMITS accept/defer ONLY. Rule 8: «a `fix` of a late
        # finding is verified only on the ONE rule-3 pass» — one recorded ON that pass has no later pass
        # to be verified in, so a `fix` there would be a promise nothing can check.
        if (disposition == "fix" and finding_fp in late_index
                and late_index.get(finding_fp) == "on-decisions"):
            _refuse("late-finding-no-further-pass", "late_finding_on_decisions_row",
                    f"{target_id} audit-{target_key}: {finding_fp} is a late finding recorded ON the "
                    f"`basis: on-decisions` pass — no further audit pass exists at this stage, so a "
                    f"`fix` can never be verified. Rule 8 admits `accept` or `defer` here.",
                    {"ceiling_ref": ceiling_ref, "finding_fingerprint": finding_fp})

        # (vi) AN `accept` QUOTES THE AUTHORIZING WORDS.
        if disposition == "accept" and not _accept_reason_quotes_directive(reason, directive_text):
            _refuse("accept-reason-not-quoting", "accept_reason_quotes_nothing",
                    f"{target_id} — an `accept` reason MUST QUOTE the authorizing words: a «…» or \"…\" span "
                    f"present VERBATIM in the resolved directive's text (SPEC-0204 rule 2). "
                    f"`accept` is TERMINAL for a finding, so the authority for it is quoted, not "
                    f"paraphrased.",
                    {"directive": locator})

        # (vii) A `defer` NAMES A REAL RECEIVING CARD.
        #
        # WHERE «filed» IS LOOKED FOR (T-12919, X-1565): this checkout, then — through the injected
        # `_find_receiving_task_yaml` — the SAME other checkout the journal fold above reads (from
        # main, the decided task's own live `task/<id>` worktree). A worker at the ceiling files its
        # receiving card INSIDE that worktree and pauses there, so from main the card is filed but not
        # yet landed; reading one checkout refused it `receiving-unfiled` (T-12848 -> T-12906 and
        # T-12869 -> T-12901, 2026-09-23). The filed and non-terminal requirements are unchanged and
        # apply to whichever card was found. Unwired, the lookup is `_find_task_yaml`, exactly as before.
        if disposition == "defer":
            if not receiving:
                _refuse("receiving-missing", "receiving_task_absent",
                        f"{target_id} — `--receiving T-YYYY` is REQUIRED for a `defer`: the deferred work "
                        f"rides a NAMED card (SPEC-0204 rule 2).")
            recv_path = ((_find_receiving_task_yaml or _find_task_yaml)(receiving)
                         if TASK_ID_RE.fullmatch(receiving) else None)
            if recv_path is None:
                _refuse("receiving-unfiled", "receiving_task_not_filed",
                        f"{target_id} — `--receiving {receiving}` is not a FILED card (searched this "
                        f"checkout and the decided task's own worktree). Rule 2: the receiving "
                        f"task is a filed card of any non-terminal status; a followup id is NOT a card.",
                        {"receiving_task": receiving})
            recv = {}
            try:
                recv = state.load_str(recv_path.read_text(encoding="utf-8")) or {}
            except (OSError, ValueError, TypeError):
                recv = {}
            recv_status = str(recv.get("status") or "").strip()
            if recv_status in state.TASK_TERMINAL_STATUSES:
                _refuse("receiving-terminal", "receiving_task_terminal",
                        f"{target_id} — `--receiving {receiving}` is `{recv_status}`, a TERMINAL status. "
                        f"Deferred work cannot ride a card that is already finished (SPEC-0204 rule 2).",
                        {"receiving_task": receiving, "receiving_status": recv_status})


        # `subject_revision` — rule 1's audited subject: the CEILING ROW's commit SHA at post (T-12367 —
        # the revision the decision binds to), the CEILING ROW's plan fingerprint at pre (T-12383 —
        # the record is the legacy fallback; the SAME basis identities SPEC-0036 already records,
        # read back rather than recomputed). A PLAN GATE takes its own third identity (T-12382): the
        # gate's ALREADY-RECORDED signature (INV-2) — read back, never recomputed, so a re-run gate
        # audit that records a DIFFERENT signature self-stales the decisions bound to this ceiling
        # row, exactly as a changed `plan_fingerprint` does on the task-pre axis.
        if is_plan:
            subject_revision = (_plan_gate_recorded_signature(plan_slug_arg, gate)
                                if _plan_gate_recorded_signature else None)
        elif stage == "post":
            subject_revision = _ceiling_subject_commit(ceiling_row)
        else:
            subject_revision = _ceiling_subject_plan_fp(ceiling_row, local_record)
        # Resolved HERE, before (viii), because the pre + plan-gate `fix` arms refuse evidence that
        # EQUALS it (T-12827, X-1538); its null refusal (x) still fires at its own position below.

        # (viii) A `fix` NAMES THE REVISION THAT CARRIES THE CHANGE.
        if disposition == "fix":
            if not evidence:
                _refuse("evidence-missing", "evidence_revision_absent",
                        f"{target_id} — `--evidence <revision>` is REQUIRED for a `fix`: the revision "
                        f"that carries the change (SPEC-0204 rule 2). «Already in the audited commit» "
                        f"is an `accept` with that reason, never a `fix`.")
            if is_plan:
                # A plan-gate `fix` is a PLAN-BODY edit, so the evidence is the plan's CURRENT
                # signature computed THE WAY THAT GATE RECORDS IT (`_PLAN_CONSULT_GATE_AUDIT`'s
                # per-gate field — INV-2, no second signature scheme).
                #
                # THE ROUTE IS PER-GATE, KEYED ON THE SIGNATURE FIELD (T-12615, <project> X-1420).
                # Two of the five gates record something other than a plan-body hash, and the two are
                # NOT alike — which is the correction this card carries:
                #
                #   `decomposition-executing` records a `card_set_fingerprint`. Its audited SUBJECT is
                #   the FILED CARD SET, so the normal remedy for a gate RED is to EDIT THAT CARD SET —
                #   and that value IS computable here: `_plan_card_set_fingerprint(slug)` is a PURE
                #   function of the filed cards + the plan's proposed specs, the SAME helper
                #   `_require_plan_decomposition_fidelity` calls to recompute the cut before every gate
                #   run. The prior refusal read it as uncomputable and left only `accept` — which rule 3
                #   reads as `overruled_by_decision`, so a Controller who genuinely REPAIRED the cut had
                #   to record a WAIVER, silencing an auditor re-raise of the same fingerprint (measured
                #   on plan `podklyuchenie-statistiki-yandeks-metriki-obratnyy-`, two residuals repaired
                #   in 4f08a57 + 2f24c32 and recorded `accept`). So `fix` is ADMITTED here, against the
                #   CURRENT cut fingerprint, and the `fix` arm of rule 3's matrix keeps a re-raise
                #   verdict-driving.
                #
                #   `finalization` records a `corpus_signature` — a function of the plan's SPEC CORPUS,
                #   a different subject this card does not touch. It stays REFUSED BY NAME.
                #
                # FAIL-CLOSED ON A DEGRADED FINGERPRINT (audit-pre finding fp1:dd744a3bf8b91729).
                # `_plan_card_set_fingerprint` is TELEMETRY-GRADE by its own contract: it never raises,
                # degrading to a STABLE sentinel hash on any card/spec read failure. A sentinel is a
                # CONSTANT, so without this check a Controller could type it as `--evidence` and satisfy
                # the equality below with no repaired cut behind it. A degraded read — the sentinel, an
                # unwired collaborator, or one that raises — takes the SAME uncomputable refusal, which
                # is exactly what it is in that state.
                _sig_field = ((_PLAN_CONSULT_GATE_AUDIT or {}).get(gate) or (None, None))[1]
                current_fp = None
                if _sig_field == "content_hash":
                    _pp2, _fm2, _body2 = _load_draft(plan_slug_arg, dirs=(PLANS_DIR,))
                    current_fp = _plan_content_hash(_body2) if _body2 else None
                elif _sig_field == "card_set_fingerprint":
                    try:
                        current_fp = (_plan_card_set_fingerprint(plan_slug_arg)
                                      if _plan_card_set_fingerprint else None)
                    except Exception:   # noqa: BLE001 — a raising collaborator IS a degraded read
                        current_fp = None
                    if current_fp == PLAN_CARD_SET_FINGERPRINT_ERROR:
                        current_fp = None   # the telemetry sentinel is NOT a signature
                if _sig_field not in ("content_hash", "card_set_fingerprint") or current_fp is None:
                    _why = ("a function of the plan's SPEC CORPUS, whose one home is the gate that "
                            "computes it, not this journal append"
                            if _sig_field not in ("content_hash", "card_set_fingerprint")
                            else "computable here in principle, but THIS read DEGRADED (the cut could "
                                 "not be read), and the helper's telemetry sentinel is not a signature")
                    _refuse("fix-evidence-not-computable-at-gate",
                            "gate_signature_not_computable_at_decide_time",
                            f"{plan_slug_arg} gate {gate}: a `fix` names the plan revision that "
                            f"carries the change, but this gate's recorded signature is "
                            f"`{_sig_field or 'unrecorded'}` — {_why}. `fix` is not available here "
                            f"(SPEC-0204 rule 9(d)); use `accept` with the reason, or `defer` naming "
                            f"the receiving card.",
                            {"evidence_revision": evidence, "signature_field": _sig_field})
                if subject_revision and evidence == subject_revision:
                    # T-12827 (X-1538): the UNEDITED audited subject is not a moved one. Admitting it
                    # binds a `fix` to the very plan the ceiling pass found wanting, and rule 4 then
                    # forbids every correction — the card wedges (<project> T-0681).
                    _refuse("evidence-is-audited-subject", "evidence_is_the_audited_subject",
                            f"{plan_slug_arg} gate {gate}: `--evidence {evidence}` is the ceiling pass's OWN audited "
                            f"`{_sig_field}` — the subject has not moved. Edit the plan body / filed card set first, then record "
                            f"the `fix` against the NEW fingerprint. «Already in the audited subject» "
                            f"is an `accept` with that reason, never a `fix` (SPEC-0204 rule 2).",
                            {"evidence_revision": evidence, "subject_revision": subject_revision})
                if evidence != current_fp:
                    _subject = ("the FILED CARD SET, so a `fix` is a CUT edit"
                                if _sig_field == "card_set_fingerprint"
                                else "the PLAN BODY, so a `fix` is a plan-body edit")
                    _refuse("evidence-not-plan-fingerprint", "evidence_is_not_the_plan_fingerprint",
                            f"{plan_slug_arg} gate {gate}: this gate's subject is {_subject} — "
                            f"`--evidence` must be the CURRENT `{_sig_field}` ({current_fp}); got "
                            f"{evidence!r}. A `fix` asserts the subject ALREADY MOVED — «already "
                            f"satisfied in the audited subject» is an `accept` with that reason "
                            f"(SPEC-0204 rules 2-3 + rule 9(d); the strict-descendant clause is "
                            f"post-only and a content hash has no ancestry).",
                            {"evidence_revision": evidence})
            elif stage == "pre":
                plan_text = str(card.get("implementation_plan") or "")
                current_fp = _plan_content_hash(plan_text) if plan_text.strip() else None
                if subject_revision and evidence == subject_revision:
                    # T-12827 (X-1538): the UNEDITED audited subject is not a moved one. Admitting it
                    # binds a `fix` to the very plan the ceiling pass found wanting, and rule 4 then
                    # forbids every correction — the card wedges (<project> T-0681).
                    _refuse("evidence-is-audited-subject", "evidence_is_the_audited_subject",
                            f"{tid} audit-pre: `--evidence {evidence}` is the ceiling pass's OWN audited "
                            f"plan fingerprint — the subject has not moved. Edit the `implementation_plan` first, then record "
                            f"the `fix` against the NEW fingerprint. «Already in the audited subject» "
                            f"is an `accept` with that reason, never a `fix` (SPEC-0204 rule 2).",
                            {"evidence_revision": evidence, "subject_revision": subject_revision})
                if not current_fp or evidence != current_fp:
                    _refuse("evidence-not-plan-fingerprint", "evidence_is_not_the_plan_fingerprint",
                            f"{tid} audit-pre: a `fix` is an `implementation_plan` edit, so "
                            f"`--evidence` must be the card's CURRENT plan fingerprint "
                            f"({current_fp or 'unresolvable — the card carries no implementation_plan'}); "
                            f"got {evidence!r} (SPEC-0204 rules 2-3; the descendant clause is post-only).",
                            {"evidence_revision": evidence})
            else:
                # The ceiling row's subject (T-12367), already resolved to a full sha — never the
                # task's latest `commit_landed`, whatever its kind.
                audited = _ceiling_subject_commit(ceiling_row)
                evidence_sha = _git_resolve_sha(evidence)
                # T-12385 — an evidence that does not RESOLVE is refused BY NAME, before the
                # descendant check, and the row below carries the RESOLVED full sha, never the
                # typed form: the Controller typed `bd3a478` on T-12327, the check resolved it,
                # the row kept the short form, and arm 1 of `on_decisions_admission` then
                # string-compared it to the 40-char subject and refused the commit it named.
                if not evidence_sha:
                    _refuse("evidence-unresolvable", "evidence_revision_unresolvable",
                            f"{tid} audit-post: `--evidence {evidence}` does not resolve to a commit "
                            f"in this checkout — `evidence_revision` is journaled as the RESOLVED "
                            f"full sha (SPEC-0204 rule 2), so an unresolvable revision cannot be "
                            f"recorded. Nothing was written.",
                            {"evidence_revision": evidence})
                evidence = evidence_sha
                if not audited or _git_strict_descendant(
                        audited, evidence_sha, repo_root=REPO_ROOT) is not True:
                    _refuse("evidence-not-descendant", "evidence_not_strict_descendant",
                            f"{tid} audit-post: `--evidence {evidence}` must be a STRICT DESCENDANT of "
                            f"the audited commit — the ceiling row's own subject "
                            f"({audited or 'unrecorded'}) — not the audited commit itself, not an "
                            f"unrelated or unresolvable revision (SPEC-0204 rule 2). «Already in the "
                            f"audited commit» is an `accept` with that reason.",
                            {"evidence_revision": evidence, "audited_commit": audited})
        # (ix) APPEND-ONLY: one decision per (ceiling_ref, fingerprint), never edited. A stored row
        # that names NO subject is NOT a decision (`decision_names_subject`, T-12383 / X-1371): it is
        # skipped here exactly as `on_decisions_bind` skips it, so ONE corrected decision for the
        # same fingerprint is admitted — the null row stays (append-only) and is superseded by it.
        for prior in view["decisions"]:
            pdata = prior.get("data") if isinstance(prior.get("data"), dict) else {}
            if (pdata.get("ceiling_ref") == ceiling_ref
                    and pdata.get("finding_fingerprint") == finding_fp
                    and decision_names_subject(pdata)):
                _refuse("decision-duplicate", "decision_already_recorded",
                        f"{target_id} — a `ceiling_decision` for {finding_fp} on {ceiling_ref} already "
                        f"exists "
                        f"(`{pdata.get('disposition')}`, recorded {prior.get('ts')}). Rule 4: decisions "
                        f"are append-only and never edited — a wrong one is superseded by a NEW ceiling "
                        f"row, not by a second decision here.",
                        {"ceiling_ref": ceiling_ref, "finding_fingerprint": finding_fp})

        # (x) FAIL-CLOSED ON THE SUBJECT (T-12383, X-1371). A null `subject_revision` is never a
        # legitimate value — it only ever produces a row rule 3 can never admit and rule 4 never lets
        # anyone correct — so it is refused by name here, exactly as an unresolvable `--directive` or
        # a wrong `--evidence` is, and nothing is written.
        # STAGE PRE ONLY — the post axis (T-12367) keeps main's behaviour unchanged.
        if stage == "pre" and not subject_revision:
            _refuse("subject-revision-unresolvable", "subject_revision_unresolvable",
                    f"{tid} audit-{stage}: the audited subject of ceiling row {ceiling_ref} cannot be "
                    f"resolved — the row carries no `plan_fingerprint` (a pre-T-12383 row) and this "
                    f"checkout holds no `decisions/{tid}-audit-pre.yaml` naming one"
                    ". A decision must bind to a revision (SPEC-0204 rules 2-3); a null is never "
                    f"written. Run the verb where the saved record exists, or re-audit so the ceiling "
                    f"row carries its subject.",
                    {"ceiling_ref": ceiling_ref})

        payload = {
            "task_id": (None if is_plan else tid),
            "plan_slug": (plan_slug_arg if is_plan else None),
            "gate": (gate if is_plan else None),
            "stage": target_key,
            "subject_revision": subject_revision,
            "ceiling_ref": ceiling_ref,
            "finding_fingerprint": finding_fp,
            "disposition": disposition,
            "reason": reason,
            "directive": locator,
            "receiving_task": receiving or None,
            "evidence_revision": evidence or None,
            "decided_by": decided_by,
        }
        # (xi) THE WRITE-SITE HALF OF SPEC-0046 §A. C1 birthed the declaration + the pure validator; this
        # is its first caller. A payload the validator reports on is REFUSED, not written — a
        # `ceiling_decision` row missing a rule-2 key would be an unreadable decision that every later
        # reader must special-case.
        problems = validate_ceiling_payload("ceiling_decision", payload)
        if problems:
            _refuse("payload-incomplete", "ceiling_decision_payload_incomplete",
                    f"{target_id} — the `ceiling_decision` payload does not satisfy the SPEC-0204 "
                    f"rule-2 key "
                    f"contract: {', '.join(problems)}. Nothing was written.",
                    {"problems": problems})

        # (xii) WRITE == READ (T-12542, <project> X-1388). Every check above is this verb's own; this
        # one is the PASS's. The rule-3 ladder (`on_decisions_admission`, the ONE function the CLI
        # pass, the in-land pass and — through `late_finding_refs_by_fp` — `task close` read) is run
        # over the PROSPECTIVE set: the decisions already on this ceiling ref plus the row about to
        # be written. Only what the ROW decides is asked: every bound key is passed as the residual
        # set (undecided siblings are the normal state mid-decision), and the time-dependent arm 1
        # is given the revision the set names as its subject (the pass's subject is whatever custody
        # holds when it runs, not a write-time fact). And the row is refused only when IT turns an
        # admissible set into a refused one — an older row's problem is the pass's to name, never a
        # reason to refuse an unrelated decision. The refusal carries the ladder's own kind, why and
        # message, and nothing is written. Task targets only: the plan-gate ladder is untouched.
        if not is_plan:
            # T-13430 — THE RECORD THE PASS WILL READ. The ship resolver's conjunct (2) reads the
            # governed audit-post record; a Controller decides from MAIN, where a worker that has not
            # landed has no such record (it lives in the worker's worktree), so the resolver answered
            # None here while the SAME resolver answered the ship in the pass (measured on T-13377:
            # the decide refused the card-only repair and its hint named the sync merge instead). So
            # the reader folds the OTHER checkout's record — the instance T-12836/T-13148 already
            # fold — and the one recording more passes wins (tie or unreadable -> local), i.e. the
            # newest pass, which is the record the pass reads. Inert without `_cross_instance_path`.
            def _folded_prior_record(_tid, _stage):
                local = (_t12614_prior_record(_tid, _stage)
                         if callable(_t12614_prior_record) else None)
                other = None
                try:
                    _o = _cross_instance_path() if _cross_instance_path is not None else None
                    if _o:
                        other = prior_audit_record(_tid, _stage,
                                                   decisions_dir=Path(_o).parent / "decisions")
                except Exception:      # noqa: BLE001 — an unreadable other checkout folds nothing
                    other = None
                if not isinstance(other, dict):
                    return local
                if not isinstance(local, dict):
                    return other
                _lp, _op = local.get("passes"), other.get("passes")
                return other if (isinstance(_op, int) and (not isinstance(_lp, int) or _op > _lp)) \
                    else local

            def _write_time_ladder(decs):
                _bound = on_decisions_bind(decs, ceiling_ref)
                _res = ((lambda v: (_git_resolve_sha(str(v)) or str(v)) if v else v)
                        if stage == "post" else None)
                _fix_revs = [str(d.get("evidence_revision") or "").strip() for d in _bound.values()
                             if str(d.get("disposition") or "").strip().lower() == "fix"]
                _fix_revs = [r for r in _fix_revs if r]
                if stage == "post":
                    # T-13244 — a NESTED set is audited at its unique maximal revision, so that is
                    # the subject the ladder is given; with none the ladder refuses split anyway.
                    _resolved_fix = [_res(r) for r in _fix_revs]
                    _sd = (lambda a, b: _git_strict_descendant(a, b, repo_root=REPO_ROOT))
                    _current = ((maximal_evidence_revision(_resolved_fix, _sd) or _resolved_fix[0])
                                if _fix_revs else subject_revision)
                else:
                    _pt = str(card.get("implementation_plan") or "")
                    _current = _plan_content_hash(_pt) if _pt.strip() else subject_revision
                # The T-11405 judgement arrives as ONE host-built callable (`cli.py#
                # _evidence_subject_refusal` -> `empty_audit_subject_refusal`), never as the custody
                # collaborators themselves: this verb binds to the CEILING ROW's subject and takes no
                # `commit_landed` / authored-paths reader of its own (T-12367). The callable judges
                # only the EVIDENCE a `fix` names, exactly as the pass's guard would.
                _subject_refusal = ((lambda _s: _evidence_subject_refusal(tid, _s))
                                    if stage == "post" and _evidence_subject_refusal is not None
                                    else None)
                # T-12614 — the write seam runs the READER's ladder (T-12542), so it must carry the
                # reader's record-only redirect too: without it `audit decide` would refuse at WRITE
                # time exactly the `fix` the bounded pass now admits at READ time, which is the
                # write/read asymmetry T-12542 exists to prevent, pointed the other way.
                # T-12926 — and its card-field fallback, through the SAME two readers the pass passes.
                _ship_reader = ((lambda _r: _ship_contained_record_only(
                    tid, _r, _bookkeeping_commit_authored_paths=_t12614_authored_paths,
                    _prior_audit_record=_folded_prior_record,   # T-13430
                    _git_resolve_sha=_git_resolve_sha, REPO_ROOT=REPO_ROOT,
                    _card_record_cause=_t12926_card_cause,   # cli's HOST (tid, prior) wrapper
                    _task_commit_landed_chain=_t12926_chain))
                    if stage == "post" and _t12614_authored_paths is not None else None)
                return on_decisions_admission(
                    tid=tid, stage=stage, residual_keys=list(_bound), decisions=decs,
                    ceiling_ref=ceiling_ref, ceiling_subject_revision=subject_revision,
                    current_subject=_current, reaudit_after_close=False, unresolvable=False,
                    strict_descendant=(lambda a, b: _git_strict_descendant(a, b, repo_root=REPO_ROOT)),
                    resolve_revision=_res,
                    late_refs=late_finding_refs_by_fp(rows, tid, stage, repo_root=[REPO_ROOT]),
                    subject_refusal=_subject_refusal, ship_of_record_only=_ship_reader,
                    sync_merges=(worktree_sync_merges(rows, tid, resolve=_git_resolve_sha)
                                 if stage == "post" else None))[1]

            _prior_refusal = _write_time_ladder(list(view["decisions"]))
            _refusal = _write_time_ladder(list(view["decisions"]) + [
                {"ts": decision_ts, "type": "ceiling_decision", "task_id": tid, "data": payload}])
            if _refusal and (_prior_refusal is None
                             or (_prior_refusal.get("kind"), _prior_refusal.get("why"))
                             != (_refusal.get("kind"), _refusal.get("why"))):
                _refuse(_refusal["kind"], _refusal["why"], _refusal["message"],
                        {"ceiling_ref": ceiling_ref, "finding_fingerprint": finding_fp,
                         "parity": "rule-3-admission",
                         **{k: v for k, v in _refusal.items()
                            if k not in ("kind", "why", "message") and not isinstance(v, set)}})

        if not is_plan and stage == "post" and disposition.lower() == "fix" and evidence:
            # T-13256 — AN EVIDENCE NO ON-DECISIONS PASS COULD REACH. The pass's subject is the
            # recorded commit, or a recorded `worktree sync` merge descending from it (rule 3);
            # an evidence that is neither a recorded commit of this card (`commit_landed`) nor a
            # recorded sync merge is a revision custody can never be audited at, and the row
            # would be permanent (rule 4) — so it is refused before the append, AFTER every existing
            # refusal above so none of them changes its kind.
            _recorded = {str((r.get("data") or {}).get("commit") or "").strip()
                         for r in rows if isinstance(r, dict)
                         and r.get("type") == "commit_landed"
                         and str(r.get("task_id") or "") == tid} - {""}
            _recorded = {(_git_resolve_sha(c) or c) for c in _recorded}
            _syncs = worktree_sync_merges(rows, tid, resolve=_git_resolve_sha)
            if evidence_sha not in _recorded and evidence_sha not in _syncs:
                _refuse("evidence-unreachable", "evidence_not_recorded_commit_or_sync_merge",
                        f"{tid} audit-post: `--evidence {evidence}` is neither a recorded commit "
                        f"of {tid} (`commit_landed`) nor a merge `worktree sync` recorded on its "
                        f"branch (`worktree_synced`), so no `--on-decisions` pass could be "
                        f"audited at it (SPEC-0204 rules 2-3, T-13256). Record the fix with "
                        f"`yitc-v2 task commit {tid} …` (or produce the merge with `yitc-v2 "
                        f"worktree sync --task {tid}`) and name THAT revision. Nothing was "
                        f"written.",
                        {"evidence_revision": evidence})

        _append_event("ceiling_decision", (None if is_plan else tid), payload)
    print(f"{target_id} audit-{target_key}: ceiling decision recorded — {disposition} on "
          f"{finding_fp} @ {ceiling_ref} (directive {locator})")


def maximal_evidence_revision(revisions, strict_descendant):
    """T-13244 (SPEC-0204 rule 3) — the UNIQUE MAXIMAL revision of a NESTED `fix` set, or None.

    Returns the ONE revision of `revisions` that every OTHER one is a STRICT ANCESTOR of — the newest
    revision of a chain of fixes, which CONTAINS every earlier one and is therefore the one combined
    state that can be audited. It is DERIVED from the rows by git ancestry each time it is asked,
    never stored (rule 4: the decisions stay exactly as written).

    Unique by construction: two candidates would each be a strict ancestor of the other, which a
    commit graph cannot hold. FAIL-CLOSED on everything that is not a proven chain — two siblings,
    an unrelated branch, a revision that does not resolve, an object that is not a commit (git
    answers neither yes nor no), a reader that raises: each leaves no candidate standing, so the
    answer is None and the caller keeps `evidence-revision-split`. A single revision is its own
    maximum. Pure f(args); never raises."""
    revs = list(dict.fromkeys(str(r or "").strip() for r in (revisions or ())))
    revs = [r for r in revs if r]
    if len(revs) == 1:
        return revs[0]

    def _below(anc, desc):
        try:
            return strict_descendant(anc, desc) is True
        except Exception:      # noqa: BLE001 — a reader that raises answered nothing
            return False
    for cand in revs:
        if all(_below(other, cand) for other in revs if other != cand):
            return cand
    return None


def worktree_sync_merges(rows, tid, resolve=None) -> set:
    """T-13256 (SPEC-0204 rule 3) — the merge commits `worktree sync` produced on `tid`'s branch.

    Read off the card's own `worktree_synced` rows: a non-noop sync whose `head_after` moved is the
    merge the verb committed (`worktree sync` / `--resolved`, the ONE governed producer). Each value
    passes through `resolve` when given, so a short or typed form compares as the full sha. A DERIVED
    set, never stored; an unreadable row contributes nothing. Pure f(args); never raises."""
    out = set()
    for r in rows or ():
        if not isinstance(r, dict) or r.get("type") != "worktree_synced":
            continue
        if str(r.get("task_id") or "") != str(tid or ""):
            continue
        d = r.get("data") or {}
        head = str(d.get("head_after") or "").strip()
        if d.get("noop") is not False or not head or head == str(d.get("head_before") or "").strip():
            continue
        if resolve is not None:
            try:
                head = str(resolve(head) or head)
            except Exception:      # noqa: BLE001 — an unanswerable resolver keeps the typed value
                pass
        out.add(head)
    return out


def sync_merge_subject(subject, fix_revisions, sync_merges, *, strict_descendant) -> "str | None":
    """T-13256 (SPEC-0204 rule 3) — the worktree-sync merge an on-decisions pass is audited AT, or None.

    A `fix` whose honest evidence IS the `worktree sync` merge (the merge that took an out-of-scope
    hunk out of the cumulative diff) names a revision no recorded commit contains: custody stays on
    the last `commit_landed`, which the merge DESCENDS from. Returns the merge E when E is the ONE
    revision the `fix` set names (`maximal_evidence_revision`), E is a recorded sync merge of this
    card, and E STRICTLY descends from `subject` (the recorded commit) — so E contains the ship and
    the packet's cumulative range covers ship + merge. FAIL-CLOSED: anything else (no fix, a split, a
    non-sync-merge, a non-descendant, an unanswerable ancestry) is None and the subject is untouched.
    Pure f(args); never raises."""
    revs = [str(r or "").strip() for r in (fix_revisions or ())]
    revs = [r for r in revs if r]
    if not revs or not subject:
        return None
    named = maximal_evidence_revision(revs, strict_descendant)
    if not named or named == subject or named not in (sync_merges or ()):
        return None
    try:
        return named if strict_descendant(subject, named) is True else None
    except Exception:      # noqa: BLE001 — an unanswered ancestry never redirects
        return None


def on_decisions_audited_revision(named, ship_of_record_only) -> str:
    """T-13430 (SPEC-0204 rule 3) — the revision a `fix` set names, AS THE PASS AUDITS IT: the ship a
    RECORD-ONLY `named` provably contains (T-12614, `ship_of_record_only`), else `named` itself.

    THE ONE RESOLVER both seams read — `on_decisions_admission` (which `audit decide` runs at write
    time) for arm 1's named revision, and `on_decisions_pass_subject` for the subject `audit post
    --on-decisions` hands the auditor — so the revision a decision names and the subject the pass
    audits cannot be derived twice (measured on T-13377: decide and the pass disagreed and the card
    had no route). An uninjected or raising reader answers `named` unchanged. Never raises."""
    named = str(named or "").strip()
    if not named or ship_of_record_only is None:
        return named
    try:
        return str(ship_of_record_only(named) or "").strip() or named
    except Exception:      # noqa: BLE001 — an unanswerable reader is the no-redirect arm
        return named


def on_decisions_pass_subject(sha, redirected, fix_revisions, *, ship_of_record_only,
                              strict_descendant, resolve=None) -> str:
    """T-13430 (SPEC-0204 rule 3) — the subject an `audit post --on-decisions` pass audits, given the
    custody subject `sha` and `redirected`, the ship the T-12614 redirect found under it (or None).

    Rule 3 admits a subject that IS or CONTAINS the revision the decisions name. The T-12614 redirect
    moves a record-only custody subject DOWN to the ship; that is right only when the ship still
    contains the named revision. When the `fix` set names a revision ABOVE the ship (T-13377: the
    `worktree sync` merge the decide hint printed, the custody subject being a card-only repair on
    top of it), the redirect would drop the subject BELOW the evidence and arm 1 refuses — with rule 4
    forbidding a second decision. So the redirect is kept iff there is no `fix` revision, or the
    redirected ship IS / STRICTLY DESCENDS FROM `on_decisions_audited_revision(E)` (E = the set's
    unique maximal revision); otherwise the custody subject `sha` stays and rule 3 judges it.
    FAIL-SAFE toward today: no redirect, no fix, no maximal revision, or an unanswerable ancestry
    keeps the redirect exactly as before. Pure f(args); never raises."""
    if not redirected:
        return sha
    try:
        res = (lambda v: (str(resolve(v) or v) if resolve is not None and v else v))
        revs = [res(str(r or "").strip()) for r in (fix_revisions or ()) if str(r or "").strip()]
        if not revs:
            return redirected
        top = maximal_evidence_revision(revs, strict_descendant) if len(revs) > 1 else revs[0]
        if not top:
            return redirected
        named = res(on_decisions_audited_revision(top, ship_of_record_only))
        red = res(redirected)
        if named == red or strict_descendant(named, red) is True:
            return redirected
        if sha and (res(sha) == named or strict_descendant(named, res(sha)) is True):
            return sha
        return redirected
    except Exception:      # noqa: BLE001 — an unanswerable question keeps today's redirect
        return redirected


#: T-13260 (SPEC-0124 §Ledger-skip axes, «Post-GREEN merge integration») — the `basis` the ONE
#: post-GREEN merge-integration audit-post records, and the marker key naming its sync evidence. A
#: distinct basis, deliberately: the one-shot bound is DERIVED from its presence (no counter), the
#: rule-4 terminal reading admits it (a RED here ENDS audit-post), and no rule-3 reader mistakes it
#: for an `--on-decisions` pass.
MERGE_INTEGRATION_BASIS = "merge-integration"
MERGE_INTEGRATION_MARKER = "merge_integration_reaudit"
_MI_REAL_VERDICTS = ("GREEN", "YELLOW", "RED")


def merge_integration_row(stage_rows) -> "dict | None":
    """T-13260 — the LATEST `(task, post)` completion row recorded by the merge-integration pass with a
    REAL verdict (GREEN / YELLOW / RED), or None. A no-verdict ABORT (timeout / no-data) spent no pass
    and does not count. Read by the one-shot bound and by the «that pass is final» refusals of
    `--on-decisions` and `audit decide`. Pure f(rows); never raises."""
    found = None
    for r in stage_rows or ():
        d = r.get("data") if isinstance(r, dict) and isinstance(r.get("data"), dict) else {}
        if (str(d.get("basis") or "") == MERGE_INTEGRATION_BASIS
                and str(d.get("verdict") or "").strip().upper() in _MI_REAL_VERDICTS):
            found = r
    return found


def merge_integration_admission(tid, *, prior_record, custody_sha, head_sha, rows, stage_rows,
                                git, resolve, diff_cap=None) -> tuple:
    """T-13260 (SPEC-0124 §Ledger-skip axes, «Post-GREEN merge integration») — may ONE ordinary
    audit-post run past the ceiling because the only thing since a GREEN is a merge with main?

    Returns `(evidence, None)` when admitted, else `(None, reason)` with a NAMED reason. Decided BEFORE
    any auditor runs, from the saved record + git + the journal rows the caller already folded
    (SPEC-0190 rule 10 — this opens nothing). `git(args) -> (returncode, stdout)` and `resolve(ref) ->
    full sha | None` are injected, so the predicate is pure; ANY git failure or unreadable input is
    «not admitted» (fail-closed — the ceiling refusal is the safe direction).

    THE SIX GUARDS, all must hold:
      G2 one-shot — no merge-integration row with a real verdict exists (checked first: once spent,
         nothing else is worth asking).
      G1 the LATEST real post verdict in the journal is GREEN and pins the custody commit A; the saved
         record, when it carries a real verdict, agrees. Latest by journal ORDER, not by `passes`: a
         GREEN row with no findings carries no `passes` key, so ranking by it would pick an older RED.
      G3 HEAD is M, a TWO-parent merge whose FIRST parent is A exactly — so A as the second parent, a
         commit between A and M, and a commit after M (HEAD is then not that merge) all refuse.
      G4 a `merge_resolved_by_hand` row of this card names M, with `head_before` = A, `main_sha` = M's
         second parent, `resolved_source` = `merge-msg` (git's own conflict-time `# Conflicts:`
         record, never the staged-delta superset) and a non-empty `resolved` list.
      G5 every path where M's tree differs from the MECHANICAL merge of (A, main) — `git merge-tree`,
         which applies the repo's merge drivers (the journal's `merge=union` included) — is a recorded
         conflict path, and the recorded set is inside the set `merge-tree` re-derives, so a hand-edited
         MERGE_MSG cannot widen it. No inert exemption.
      G6 a `tests_passed` row of this card postdates the sync row (the pass is terminal-bearing, the
         T-12642 posture).

    The evidence is the marker the pass records (merge / prior / main shas, the conflict paths, the
    sync row locator); `resolution_diff` rides beside it for the PACKET only and is never recorded,
    bounded by the host's existing packet diff cap (`diff_cap`, the caller's `AUDIT_MAX_DIFF_BYTES`)."""
    def _g(args):
        try:
            rc, out = git(list(args))
        except Exception:      # noqa: BLE001 — an unanswered git question is a refusal
            return None
        return (rc, out or "")

    def _r(ref):
        if not ref:
            return None
        try:
            return (resolve(str(ref).strip()) or None)
        except Exception:      # noqa: BLE001
            return None

    def _d(row):
        return row.get("data") if isinstance(row, dict) and isinstance(row.get("data"), dict) else {}

    # G2 — ONE-SHOT.
    spent = merge_integration_row(stage_rows)
    if spent is not None:
        return None, (f"merge_integration_allowance_spent: the post-GREEN merge-integration pass already "
                      f"ran for {tid} ({spent.get('ts')}, {_d(spent).get('verdict')}) — it is admitted once")
    # G1 — the latest real verdict is GREEN at A.
    a_sha = _r(custody_sha)
    if not a_sha:
        return None, "custody_unresolved: the recorded commit does not resolve"
    real = [r for r in (stage_rows or ())
            if str(_d(r).get("basis") or "") != "currency"
            and str(_d(r).get("verdict") or "").strip().upper() in _MI_REAL_VERDICTS]
    if not real:
        return None, "no_prior_verdict: no recorded audit-post verdict for this card"
    latest = real[-1]
    lv = str(_d(latest).get("verdict") or "").strip().upper()
    if lv != "GREEN":
        return None, f"prior_verdict_not_green: the latest recorded audit-post verdict is {lv}"
    if _r(_d(latest).get("commit")) != a_sha:
        return None, (f"prior_green_not_at_custody: the latest GREEN pins {_d(latest).get('commit')}, "
                      f"not the recorded commit {a_sha[:12]}")
    if isinstance(prior_record, dict):
        pv = str(prior_record.get("verdict") or "").strip().upper()
        if pv in _MI_REAL_VERDICTS and (pv != "GREEN" or _r(prior_record.get("commit")) != a_sha):
            return None, (f"saved_record_disagrees: the saved audit-post record reads {pv} at "
                          f"{prior_record.get('commit')}, not GREEN at {a_sha[:12]}")
    # G3 — HEAD is exactly one merge M over A.
    m_sha = _r(head_sha)
    if not m_sha:
        return None, "head_unresolved: HEAD does not resolve"
    rl = _g(["rev-list", "--parents", "-n", "1", m_sha])
    if rl is None or rl[0] != 0:
        return None, "head_parents_unreadable: git could not list HEAD's parents"
    parts = rl[1].split()
    if len(parts) != 3:
        return None, (f"head_not_a_merge: HEAD {m_sha[:12]} has {max(len(parts) - 1, 0)} parent(s) — "
                      f"exactly one two-parent merge over the GREEN commit is admitted")
    p1, p2 = parts[1], parts[2]
    if p1 != a_sha:
        return None, (f"first_parent_not_prior_green: HEAD's first parent is {p1[:12]}, not the "
                      f"GREEN-pinned {a_sha[:12]} (a commit before/after the merge, or the GREEN commit "
                      f"merged in as the second parent)")
    # G4 — governed sync provenance.
    sync = None
    for r in rows or ():
        if (isinstance(r, dict) and r.get("type") == "merge_resolved_by_hand"
                and str(r.get("task_id") or "") == str(tid)
                and _r(_d(r).get("merge_commit")) == m_sha):
            sync = r
    if sync is None:
        return None, (f"sync_provenance_missing: no `merge_resolved_by_hand` row of {tid} names the merge "
                      f"{m_sha[:12]} (resolve through `worktree sync --resolved`)")
    sd = _d(sync)
    if _r(sd.get("head_before")) != a_sha:
        return None, f"sync_head_before_mismatch: the sync row's head_before is {sd.get('head_before')}"
    if _r(sd.get("main_sha")) != p2:
        return None, (f"sync_main_parent_mismatch: the sync row's main_sha {sd.get('main_sha')} is not "
                      f"the merge's second parent {p2[:12]}")
    if sd.get("resolved_source") != "merge-msg":
        return None, (f"sync_conflict_record_inexact: resolved_source is {sd.get('resolved_source')!r}, "
                      f"not git's conflict-time `merge-msg` record")
    recorded = sd.get("resolved")
    if not isinstance(recorded, list) or not [p for p in recorded if str(p or "").strip()]:
        return None, "sync_conflict_paths_empty: the sync row records no conflict path"
    recorded = sorted({str(p).strip() for p in recorded if str(p or "").strip()})
    # G5 — the resolution is confined to the conflict paths.
    mt = _g(["merge-tree", "--write-tree", "--name-only", "-z", a_sha, p2])
    if mt is None or mt[0] != 1:
        return None, ("mechanical_merge_not_conflicting: `git merge-tree` of the GREEN commit and main "
                      "did not report a conflict (or could not run)")
    fields = mt[1].split("\0")
    mech_tree = fields[0].strip()
    derived = set()
    for f in fields[1:]:
        if not f:
            break
        derived.add(f)
    if not mech_tree or not derived:
        return None, "mechanical_merge_unreadable: `git merge-tree` output could not be parsed"
    widened = [p for p in recorded if p not in derived]
    if widened:
        return None, (f"sync_conflict_set_widened: recorded conflict path(s) git does not re-derive: "
                      f"{', '.join(widened)}")
    df = _g(["diff", "--name-only", "--no-renames", "-z", mech_tree, m_sha])
    if df is None or df[0] != 0:
        return None, "resolution_diff_unreadable: git could not diff the merge against the mechanical merge"
    changed = sorted({p for p in df[1].split("\0") if p})
    outside = [p for p in changed if p not in recorded]
    if outside:
        return None, (f"resolution_outside_conflict_paths: the merge changes non-conflict path(s) "
                      f"relative to the mechanical merge: {', '.join(outside)}")
    # G6 — Stage-6 proof postdates the sync.
    sync_ts = str(sync.get("ts") or "")
    if not sync_ts or not any(isinstance(r, dict) and r.get("type") == "tests_passed"
                              and str(r.get("task_id") or "") == str(tid)
                              and str(r.get("ts") or "") > sync_ts for r in rows or ()):
        return None, (f"stage6_evidence_predates_merge: no `tests_passed` row of {tid} postdates the sync "
                      f"({sync_ts or 'no ts'}) — run `task test --run --evidence` at the merge first")
    # LITERAL pathspecs: a conflict path is a recorded file NAME, never pathspec magic (a file named
    # `:(literal)f.txt` must not select `f.txt`). A diff git could not produce REFUSES — an empty
    # stand-in would admit a pass whose packet silently lacks the resolution it exists to show.
    rd = _g(["--literal-pathspecs", "diff", mech_tree, m_sha, "--", *recorded])
    if rd is None or rd[0] != 0:
        return None, ("resolution_patch_unreadable: git could not produce the resolution diff of the "
                      "conflict paths")
    res_diff = rd[1]
    if isinstance(diff_cap, int) and diff_cap > 0 and len(res_diff) > diff_cap:
        res_diff = res_diff[:diff_cap] + f"\n... [truncated at {diff_cap} bytes]\n"
    return {"merge_commit": m_sha, "prior_commit": a_sha, "main_sha": p2,
            "conflict_paths": recorded, "sync_evidence": f"events.jsonl#ts={sync_ts}",
            "resolution_diff": res_diff}, None


def merge_integration_context(evidence) -> str:
    """T-13260 — the packet CONTEXT block for an admitted merge-integration pass: what was GREEN, what
    was merged, which paths were hand-resolved, and the resolution itself. Pure; never raises."""
    ev = evidence if isinstance(evidence, dict) else {}
    return (
        "## Post-GREEN merge integration (T-13260, SPEC-0124 §Ledger-skip axes)\n\n"
        f"This card's audit-post was GREEN at {ev.get('prior_commit')}. Since then its branch took ONE "
        f"merge with main ({ev.get('main_sha')}) via the governed `worktree sync --resolved`, recorded "
        f"at {ev.get('sync_evidence')}. The subject is the WHOLE merged HEAD {ev.get('merge_commit')}. "
        "Judge whether the merged result still meets the card's acceptance, with particular attention "
        "to the hand-resolved conflict paths below — every other path is byte-identical to git's "
        "mechanical merge. This pass is admitted ONCE; a RED here ENDS audit-post for this card.\n\n"
        "Hand-resolved conflict paths:\n"
        + "".join(f"- {p}\n" for p in (ev.get("conflict_paths") or []))
        + "\nResolution diff (mechanical merge -> merged HEAD, conflict paths only):\n```diff\n"
        + str(ev.get("resolution_diff") or "(empty)") + "\n```\n")


def on_decisions_admission(*, tid, stage, residual_keys, decisions, ceiling_ref,
                           ceiling_subject_revision, current_subject, reaudit_after_close,
                           unresolvable, strict_descendant, unresolvable_reason=None,
                           resolve_revision=None, late_refs=None, subject_refusal=None,
                           ship_of_record_only=None, sync_merges=None, on_decisions_bind) -> tuple:
    """SPEC-0204 rule 3's ADMISSION — `(named_revision, None)` or `(None, {kind, why, message})`.

    THE CLOSED REFUSAL LADDER: three kinds, exactly the set rule 3 names and no fourth. Each is its
    own `read_gate_refused` kind at the call site, invokes no auditor and spends no pass.

      (i)   `residual-undecided` — a residual with no `ceiling_decision` on this `ceiling_ref`,
            NAMING each; AND the UNRESOLVABLE ceiling row; AND (T-12736) the COLLAPSED residual set,
            one key standing for more than one residual. ONE kind, THREE causes, because all are
            the same fact: this pass cannot prove every residual is decided. `unresolvable_reason`
            (C1's, when it gave one) is APPENDED to the message — a row can be unresolvable because
            no record exists OR because the record that exists belongs to a DIFFERENT pass (T-12319),
            and those need different operator actions. It adds no fourth kind.
      (ii)  `evidence-revision-split` — more than one distinct `evidence_revision` among the `fix`
            decisions AND no single revision the pass could be audited at. At audit-POST a NESTED
            set is not a split (T-13244): when ONE named revision E strictly descends from every
            other (`maximal_evidence_revision`), E contains them all and IS the revision the set
            names — arm 1 then asks the subject to contain E, arm 2 asks EVERY named revision to
            strictly descend from the ceiling row's subject. Divergent, unresolvable, non-commit or
            unanswerable revisions leave no E and still refuse here. At audit-PRE the revisions are
            plan fingerprints with no ancestry, so any two distinct ones still refuse.
      (iii) `decisions-not-for-this-revision` — TWO INDEPENDENT ARMS, each EVALUATED ON ITS OWN and
            each SUFFICIENT ON ITS OWN (audit-pre pass-2 finding fp1:002dfa006e2d181e).

    THE TWO ARMS, and why they are not conjoined. An earlier shape joined them with AND, which reads
    as «refuse only when BOTH hold» and so let a non-descendant evidence revision through whenever it
    happened to equal the current subject; the intent was, and is, DISJUNCTIVE.

      ARM 1 — SUBJECT CONTAINMENT (post) / EQUALITY (pre). Refuses when `current_subject` neither IS
        nor CONTAINS the ONE revision the decisions name. At audit-PRE that revision is a PLAN
        FINGERPRINT — a hash with no ancestry — so the current plan fingerprint must EQUAL it
        (T-12422: «the descendant clause is post-only», rule 3). At audit-POST it is a COMMIT, and a
        STRICT DESCENDANT of it is admitted too: the descendant CONTAINS the evidence the decisions
        name, and anything authored on top is put before the auditor as this pass's own diff and
        counts NEW at its own severity. That is what lets a card survive the commits the LIFECYCLE
        ITSELF mandates after the decisions were recorded — the merge-fallout round (T-12327) and the
        `task commit --fix-red --card-repair` custody move (T-12417) — neither of which rule 4 allows
        to be answered by re-recording the decisions. The NON-descendant is still refused, fail-closed
        on anything `strict_descendant` does not answer True. Evaluated without reference to arm 2.
        THE EMPTY RESIDUAL SET RIDES THIS SAME CLAUSE (T-12434, on the generic containment arm
        T-12422 landed): when the ceiling row's residual set is EMPTY no decision is `fix`, so
        `revisions` is empty, `named_revision` falls back to the ceiling row's OWN subject and arm 2
        is silent by construction — a `current_subject` that STRICTLY DESCENDS from that subject is
        therefore admitted by the containment clause above, with no second arm and no second notion
        of descent. What T-12434 adds is the residue: the revision that admission NAMES (the current
        subject, not the already-audited one) and the never-raises read below. Descent stays
        REQUIRED, STRICT and `is True`.
      ARM 2 — ANCESTRY (post stage only, and only when a `fix` NAMED an evidence revision; audit-pre
        pass-1 finding 2). Refuses when that `evidence_revision` is NOT a STRICT DESCENDANT of the
        ceiling row's `subject_revision`. Evaluated without reference to arm 1 — so an evidence
        revision on an unrelated branch is REFUSED EVEN WHEN it is the current subject, which is
        precisely the hole the conjunction left open. It REUSES C2's `_git_strict_descendant`
        (injected as `strict_descendant`, so this helper stays a testable f(args) and the module
        keeps ONE notion of descent) and refuses on anything that is not True, so an unanswerable
        ancestry fails closed. It is DEFENCE IN DEPTH over C2's write-time check, not a duplicate of
        it: C2 proves descent from the RECORDED commit at WRITE time, which by admission time has
        moved to the evidence revision itself, so only this side can still ask the question against
        the ceiling row's own subject.

    BOTH arms are deliberately the SAME `kind` rather than a fourth: rule 3 closes the set at three,
    and «the decisions do not name a revision this subject may be audited at» is exactly what that
    kind says for either arm — what pass 2 faulted was the CONJUNCTION, not the shared kind.

    `--reaudit-after-close` returns the CURRENT subject and skips BOTH arms, by that route's own
    contract (its subject is HEAD, for ANY decision set — never «HEAD because the decisions say so»).
    That is the ONE place the two arms are disabled together, and it is the route contract that
    disables them, never one arm gating the other.

    `resolve_revision` (T-12385) — the injected revision resolver (the caller's `_git_resolve_sha`
    at post; identity when None, so the pure-f(args) tests and the in-land arm — which skips both
    arms — read exactly as before). EVERY revision the arms compare passes through it: each `fix`'s
    stored `evidence_revision` (before the split set, so two rows naming one commit in two
    spellings are ONE revision), `ceiling_subject_revision`, and `current_subject`. A value that does
    not resolve stays as typed, so it can never equal a resolved sha — fail-closed. This is what
    admits a decision row that RECORDED a short sha (T-12327's two rows, append-only under rule 4)
    when it names the subject, without touching the journal.

    Pure f(args); never raises."""
    bound = on_decisions_bind(decisions, ceiling_ref)

    def _resolved(v):
        v = str(v or "").strip()
        if not v or resolve_revision is None:
            return v
        try:
            return str(resolve_revision(v) or v)
        except Exception:      # noqa: BLE001 — an unanswerable resolver leaves the typed value
            return v
    ceiling_subject_revision = _resolved(ceiling_subject_revision) or ceiling_subject_revision
    current_subject = _resolved(current_subject) or current_subject

    # (i) residual-undecided — the unresolvable cause first: with no resolvable residual set there is
    # nothing for the per-key walk below to be about.
    if unresolvable:
        # The REASON, when C1 gave one, is appended rather than folded into the sentence: it names
        # WHICH check refused the record (T-12319), which is the difference between «go find the
        # record» and «the record you have is a DIFFERENT pass's». Without it the operator who hit
        # the live T-12261 case had to diff two YAMLs by hand to learn that much.
        _why = f" WHY: {unresolvable_reason}." if unresolvable_reason else ""
        return None, {
            "kind": "residual-undecided",
            "why": "ceiling_row_residuals_unresolvable",
            "message": (f"{tid} audit-{stage}: the ceiling row ({ceiling_ref}) states no findings and "
                        f"its saved record resolves none, so its residual set CANNOT BE RESOLVED — "
                        f"this pass cannot prove every residual is decided (SPEC-0204 rule 3). An "
                        f"unresolvable residual set is not an empty one.{_why} No auditor was invoked "
                        f"and no pass was spent."),
        }
    # T-12736 — (i-c) A COLLAPSED RESIDUAL SET: one key standing for MORE THAN ONE residual. Rule 9(f)
    # admits the round once EVERY residual carries a decision, and a decision binds to a KEY — so a
    # key carried by N residuals lets one decision discharge N findings the Controller never read
    # as separate (<project> X-1489: ten under one key, four of them high). The reader re-keys a
    # pre-T-12736 collapsed row on its colliding findings, so this fires only when the re-key STILL
    # collides (byte-identical prose) or a caller hands in a raw collided set — and then it refuses
    # rather than admit a decision-per-key as a decision-per-residual. Same kind, a THIRD cause of
    # the same fact: this pass cannot prove every residual is decided. No fourth kind (rule 3).
    _keys = list(residual_keys or ())
    _collapsed = sorted({k for k in _keys if _keys.count(k) > 1})
    if _collapsed:
        _named = ", ".join(f"{k} x{_keys.count(k)}" for k in _collapsed)
        return None, {
            "kind": "residual-undecided",
            "why": "residual_keys_collapsed",
            "message": (f"{tid} audit-{stage}: the residual set of {ceiling_ref} is COLLAPSED — "
                        f"{len(_collapsed)} key(s) each stand for more than one residual ({_named}), "
                        f"so a decision per KEY is not a decision per RESIDUAL and this pass cannot "
                        f"prove every residual is decided (SPEC-0204 rules 3 + 9(f), T-12736). The "
                        f"findings under one key are substantively different only if their text "
                        f"differs; the reader has already re-keyed what it could. No auditor was "
                        f"invoked and no pass was spent."),
            "collapsed": list(_collapsed),
        }
    undecided = [k for k in _keys if k not in bound]
    if undecided:
        return None, {
            "kind": "residual-undecided",
            "why": "residual_without_ceiling_decision",
            "message": (f"{tid} audit-{stage}: {len(undecided)} of {len(list(residual_keys or ()))} "
                        f"residual(s) of {ceiling_ref} carry no `ceiling_decision` — "
                        f"{', '.join(undecided)}. Record one per residual with `yitc-v2 audit decide "
                        f"--task {tid} --stage {stage} --finding <fp> --disposition fix|accept|defer "
                        f"…` (SPEC-0204 rules 2-3), then re-run. No auditor was invoked and no pass "
                        f"was spent."),
            "undecided": list(undecided),
        }

    # (ii) evidence-revision-split
    fixes = [d for d in bound.values() if str(d.get("disposition") or "").strip().lower() == "fix"]
    revisions = sorted({_resolved(d.get("evidence_revision")) for d in fixes} - {""})
    # T-13244 — a NESTED set names its unique maximal revision; only a set with none is a split.
    maximal = revisions[0] if len(revisions) == 1 else None
    if len(revisions) > 1 and stage == "post":
        maximal = maximal_evidence_revision(revisions, strict_descendant)
    if len(revisions) > 1 and maximal is None:
        return None, {
            "kind": "evidence-revision-split",
            "why": "fix_decisions_name_multiple_revisions",
            "message": (f"{tid} audit-{stage}: the `fix` decisions on {ceiling_ref} name "
                        f"{len(revisions)} DIFFERENT evidence revisions ({', '.join(revisions)}) and "
                        f"no ONE of them provably contains every other — divergent, unresolvable or "
                        f"non-commit evidence — so there is no single revision this pass could be "
                        f"audited at (SPEC-0204 rule 3). No auditor was invoked and no pass was "
                        f"spent."),
            "evidence_revisions": list(revisions),
        }

    # T-12542 — (i-b) THE LATE-FINDING BINDING CLOSURE READS. `late_refs` (`late_finding_refs_by_fp`,
    # the SAME derivation `task close` applies) names, per late finding, the `ceiling_ref` a decision
    # must carry for closure to count it. A decision bound here for a late finding whose closure ref
    # is another pass can never clear Closure (rule 8), so the pass refuses it rather than spend a
    # pass on a card that cannot close — and `audit decide` refuses to WRITE it, through this same
    # clause. Revision-independent (like the split above), so it holds on `--reaudit-after-close`
    # too. Kind `residual-undecided`: that residual is not decided anywhere closure can see. None
    # (every caller before T-12542) reads exactly as before.
    for _fp in (bound if late_refs else ()):
        _refs = set((late_refs or {}).get(_fp) or ())
        if _refs and _refs != {ceiling_ref}:
            _other = sorted(str(r) for r in _refs if r != ceiling_ref)
            return None, {
                "kind": "residual-undecided",
                "why": "late_finding_bound_to_another_pass",
                "message": (f"{tid} audit-{stage}: the late finding {_fp} is decided on {ceiling_ref}, "
                            f"but it sits on the audit row(s) of {', '.join(_other)} — `task close` "
                            f"counts a late finding decided only at the ref of the row it sits on "
                            f"(SPEC-0204 rule 8), so this decision can never clear Closure. No auditor "
                            f"was invoked and no pass was spent."),
                "finding_fingerprint": _fp,
                "closure_refs": _other,
            }

    named_revision = maximal if revisions else ceiling_subject_revision

    # T-12614 (SPEC-0204 rules 2-3) — A RECORD-ONLY `fix` EVIDENCE NAMES ITS SHIP AS THE SUBJECT.
    # A `fix` whose only honest artifact is a bookkeeping / journal commit carries the change
    # truthfully (rule 2: «the revision that carries the change») but is NOT what the auditor should
    # be shown — its own diff holds none of the card's work. `ship_of_record_only` (the injected
    # `_ship_contained_record_only`) answers, fail-closed and off GIT plus the GOVERNED audit-post
    # record, with the SHIP that revision provably contains; the pass is then audited THERE. Without
    # this the residual had to be recorded `accept` — a disposition that is TERMINAL and means the
    # residual STANDS — so the ledger said the opposite of what happened (<project> X-1424, <project>
    # X-1428).
    #
    # SCOPED TO ARM 1, AND THAT SPLIT IS LOAD-BEARING. Arm 1 asks «may this SUBJECT be audited for
    # these decisions», so it must compare against the redirected value. Arm 2 asks «is the EVIDENCE
    # a strict descendant of the ceiling row's subject» — a question about the evidence revision
    # ITSELF, which is unchanged and must stay so: measured against the redirected value it would ask
    # whether the ship descends from itself and refuse every admission this clause exists to grant.
    # So arm 2 keeps reading `evidence_revision` below, and only the subject side moves.
    #
    # Post only (a pre `evidence_revision` is a plan fingerprint, which has no diff and no ancestry),
    # and only when a `fix` actually named a revision. An uninjected reader or an unprovable revision
    # answers None and NOTHING changes — every card admitted today is admitted identically.
    evidence_revision = named_revision
    if stage == "post" and revisions:
        # T-13430 — the ONE shared resolver: the pass's subject redirect asks the same question.
        named_revision = _resolved(on_decisions_audited_revision(named_revision, ship_of_record_only))

    # `--reaudit-after-close` — the subject is HEAD by that route's OWN contract, for ANY decision set.
    if reaudit_after_close:
        return current_subject, None

    # (iii) the two INDEPENDENT arms. Each is computed on its own; the refusal fires on EITHER.
    # ARM 1 — ANCESTRY AT POST, EQUALITY AT PRE (T-12422). At audit-POST a subject that CONTAINS the
    # named revision is admitted: the descendant carries the very evidence the decisions name, and
    # whatever was authored on top is put in front of the auditor as THIS pass's diff and counts NEW
    # at its own severity — so auditing a descendant is never less safe than auditing the named
    # revision itself. At audit-PRE the subject is a PLAN FINGERPRINT, a hash with no ancestry, so
    # equality is kept verbatim (rule 3: «the descendant clause is post-only»). FAIL-CLOSED
    # unchanged: `strict_descendant` is three-valued and anything that is not True — a
    # non-descendant, an unanswerable ancestry — still refuses `subject_not_named_revision`.
    #
    # WHY ANCESTRY AND NOT «ancestry through bookkeeping-only commits» (measured, T-12327): the
    # commits between bd3a478 and fe0d502 are `fix(T-12327): merge-fallout — re-express a superseded
    # differential` and `chore(T-12327): re-sign the two anchors` — AUTHORED content, produced by the
    # mandatory merge-fallout round the lifecycle ITSELF requires after the decisions were recorded.
    # A bookkeeping-bounded form would refuse that card, and rule 4 (append-only) forbids re-recording
    # the decisions, so the card would have no governed exit at all.
    def _descends(anc, desc):
        """`strict_descendant`, held to THIS function's own «never raises» contract (T-12434).

        Arm 2 calls the injected reader BARE because its caller has always supplied
        `_git_strict_descendant`, which swallows its own subprocess failures; arm 1 does not assume
        that of a future injection. A raising reader told us NOTHING, so it reads as None and the
        admission REFUSES — the same direction `is True` already gives an unanswerable answer, and
        the direction this function's own closing line («Pure f(args); never raises») promises.
        Scoped to arm 1: arm 2's bare call is unchanged."""
        try:
            return strict_descendant(anc, desc)
        except Exception:      # noqa: BLE001 — a reader that raises is an unanswered question
            return None

    arm1_equality = (str(current_subject or "") != str(named_revision or ""))
    arm1_admitted_by_descent = False
    if (arm1_equality and stage == "post" and current_subject and named_revision
            and _descends(named_revision, current_subject) is True):
        arm1_equality = False
        arm1_admitted_by_descent = True
    # T-12504 — AT TASK AUDIT-PRE AN ALL-`accept`/`defer` SET IS PLAN-FINGERPRINT-AGNOSTIC. Such a set
    # names no revision of its own (no `fix`, so no `evidence_revision`): the residual stands whatever
    # the plan text now says, and the pass audits the CURRENT plan, where anything new counts NEW.
    # Without this a plan edited after the ceiling pass deadlocked the card — this arm refused, and
    # rule 4 forbids re-recording the decision (measured on T-12477, 2026-09-13: accept bound to
    # 9b23ea9b, plan d397442c). SCOPED: `stage == "pre"` only (a plan gate passes its gate id, post
    # keeps ancestry), a NON-EMPTY bound set only, and ANY `fix` — alone or mixed — keeps the
    # current-fingerprint equality verbatim. No row is read differently and none is written.
    arm1_plan_agnostic = False
    if (arm1_equality and stage == "pre" and bound
            and all(str(d.get("disposition") or "").strip().lower() in ("accept", "defer")
                    for d in bound.values())):
        arm1_equality = False
        arm1_plan_agnostic = True
    # T-13400 — THE EMPTY RESIDUAL SET AT TASK AUDIT-PRE: the pre mirror of the T-12434 post-side
    # admission. A GREEN (empty, resolved) ceiling row carries no decision, so `named_revision` is the
    # ceiling row's own plan fingerprint. A plan amended AFTER that row has no ancestry to ride, so
    # arm 1's equality refused it and no decision could be recorded either (0 residuals) — a dead end
    # (<project> T-0823). So when BOTH fingerprints are known and DIFFER, the pass is admitted at the
    # CURRENT plan fingerprint; when they are EQUAL the plan is unchanged and there is nothing new to
    # audit, so the pass is REFUSED rather than handed out free. SCOPED: `stage == "pre"` only (plan
    # gates pass their gate id, post keeps descent), no bound decision, no `fix` revision, a resolved
    # EMPTY residual set. An unknown fingerprint on either side changes nothing (fail-closed). Bounded
    # to ONE pass by construction: the admitted pass writes the next ceiling row, and a re-run at that
    # same plan meets the equal-fingerprint refusal below.
    arm1_pre_empty_amended = False
    if (stage == "pre" and not bound and not revisions and not unresolvable and not _keys
            and current_subject and named_revision):
        if arm1_equality:
            arm1_equality = False
            arm1_pre_empty_amended = True
        else:
            return None, {
                "kind": "decisions-not-for-this-revision",
                "why": "plan_unchanged_since_ceiling",
                "message": (f"{tid} audit-{stage}: the ceiling row {ceiling_ref} has no residuals and "
                            f"the current plan fingerprint ({current_subject}) is the one it already "
                            f"audited — an unchanged plan has nothing new for a pass to judge, so none "
                            f"is admitted (SPEC-0204 rule 3, T-13400). Amend `implementation_plan` "
                            f"first if the plan must change. No auditor was invoked and no pass was "
                            f"spent."),
                "named_revision": named_revision,
                "current_subject": current_subject,
            }
    arm2_ancestry = False
    arm2_revision = evidence_revision
    if stage == "post" and revisions:
        # T-12614 — the EVIDENCE revision, never the (possibly redirected) subject: this arm judges
        # the revision the decisions NAME, and the redirect above moves only the subject side.
        arm2_ancestry = strict_descendant(ceiling_subject_revision, evidence_revision) is not True
        # T-13244 — a NESTED set names E, but every OTHER named revision must be a valid `fix`
        # evidence on its own (rule 2: a STRICT descendant of the ceiling row's subject). E
        # containing it is not enough — «already in the audited commit» is never a `fix`.
        if not arm2_ancestry:
            for _rev in revisions:
                if _rev != evidence_revision and _descends(ceiling_subject_revision, _rev) is not True:
                    arm2_ancestry, arm2_revision = True, _rev
                    break
    if arm1_equality or arm2_ancestry:
        _why = []
        if arm1_equality:
            _why.append(f"the current subject ({current_subject or 'unresolvable'}) is not the "
                        f"revision the decisions name ({named_revision or 'unresolvable'}) and does "
                        f"not contain it")
        if arm2_ancestry:
            _why.append(f"the named evidence revision ({arm2_revision or 'unresolvable'}) is not a "
                        f"STRICT DESCENDANT of the ceiling row's subject "
                        f"({ceiling_subject_revision or 'unresolvable'})")
        return None, {
            "kind": "decisions-not-for-this-revision",
            "why": ("subject_equality_and_ancestry" if (arm1_equality and arm2_ancestry)
                    else "subject_not_named_revision" if arm1_equality
                    else "evidence_revision_not_descendant"),
            "message": (f"{tid} audit-{stage}: the decisions on {ceiling_ref} do not name a revision "
                        f"this subject may be audited at — {'; '.join(_why)} (SPEC-0204 rule 3; the "
                        f"two arms are INDEPENDENT, either alone refuses). No auditor was invoked and "
                        f"no pass was spent."),
            "named_revision": named_revision,
            "current_subject": current_subject,
            "arms": ([k for k, v in (("subject-equality", arm1_equality),
                                     ("ancestry", arm2_ancestry)) if v]),
        }
    # T-12542 — THE AUTHORED-CONTENT ARM. A `fix` names the revision that carries the change; one the
    # T-11405 guard refuses (`subject_refusal` = `empty_audit_subject_refusal`) carries none of the
    # card's work, so no pass can be audited at it. Same kind as arms 1-2 — «the decisions do not
    # name a revision this subject may be audited at» — and the guard's OWN message. Post only, and
    # after the reaudit return: it judges the revision the decisions name, which that route replaces
    # with HEAD. A resolver that raises proves nothing and proceeds, the guard's own polarity.
    if subject_refusal is not None and stage == "post":
        for _rev in revisions:
            # T-12614 — a revision the REDIRECT covered is not judged here. This arm asks «does the
            # revision the decisions name carry the card's work», and for a record-only `fix` the
            # honest answer is «no, and it does not have to»: the redirect above already proved, off
            # git and the governed audit-post record, that it CONTAINS the ship — and the ship is
            # what this pass audits and what conjunct (3) of that predicate proved authored. Judging
            # it here anyway would refuse exactly the admission the redirect exists to grant, with
            # the guard's own message, which is how the two would silently disagree.
            if named_revision != evidence_revision and _resolved(_rev) == evidence_revision:
                continue
            # T-13256 — a recorded `worktree sync` merge carries no authored content OF ITS OWN by
            # construction; arm 2 above already proved it strictly descends from the ceiling row's
            # subject, so the cumulative range it is audited over carries the ship.
            if _resolved(_rev) in (sync_merges or ()):
                continue
            try:
                _msg = subject_refusal(_rev)
            except Exception:      # noqa: BLE001 — an unanswerable guard is the proceed arm
                _msg = None
            if _msg:
                return None, {
                    "kind": "decisions-not-for-this-revision",
                    "why": "evidence_revision_carries_no_authored_content",
                    "message": _msg,
                    "named_revision": _rev,
                    "current_subject": current_subject,
                }
    # T-12434 — WHICH REVISION THE EMPTY-SET ADMISSION NAMES. When arm 1 admitted BY DESCENT over an
    # EMPTY-and-RESOLVED residual set with NO `fix` decision, `named_revision` above is the CEILING
    # ROW's own subject — the already-audited commit — while the subject this pass actually audits is
    # the current one. Reporting the former makes the admission line and the projection name a
    # revision this pass is not about (measured on T-12038, 2026-09-12). So over exactly that shape
    # the named revision IS the current subject.
    #
    # SCOPED TO THE EMPTY SHAPE, so nothing existing moves: a `fix` set (`revisions` non-empty) keeps
    # `revisions[0]` verbatim, and `not unresolvable` is restated rather than inferred from
    # `not residual_keys` — an unresolvable row also carries zero keys, and the two must never be read
    # as one fact (the collapse T-12311 removed; an unresolvable row is refused upstream by cause (i)
    # regardless).
    #
    # THIS IS A REPORTING CORRECTNESS FIX, NOT A CLAIM ABOUT WHICH DIFF IS AUDITED. The returned value
    # feeds `_od_named` -> `on_decisions_projection` and the stderr admission line only; the audited
    # subject is `sha`, resolved by the caller and untouched here.
    if (arm1_admitted_by_descent and not revisions and not unresolvable
            and not list(residual_keys or ())):
        return current_subject, None
    # T-12504 — the plan-agnostic pre admission names the plan fingerprint the pass audits (the
    # CURRENT one), never the stale one the decisions were bound to. Reporting only, as above.
    if arm1_plan_agnostic or arm1_pre_empty_amended:
        return current_subject, None
    return named_revision, None


def on_decisions_absorption_grant(stage_rows, *, ON_DECISIONS_ABSORPTION_BASIS, _ceiling_row_of, on_decisions_row_absorbable) -> "dict | None":
    """T-12376 — the ONE bounded ABSORPTION re-audit a YELLOW-absorbable rule-3 verdict admits, or
    None. Returns `{"ceiling_ref", "on_decisions_row", "passes"}` when admitted.

    DERIVED from the rows already written — a VIEW, never a counter (CHARTER §P1 F2): the grant
    exists iff the (task, stage) carries a YELLOW-absorbable `basis: on-decisions` row R (the
    highest-`passes` such row, so a later rule-3 verdict on a new ceiling row wins) AND NO row with
    `basis: on-decisions-absorption` names R's `ceiling_ref`. Once the absorption re-audit is
    recorded — whatever its verdict — the same reading yields None, which is the whole of the
    «once per ceiling row» bound. The caller feeds it the PHANTOM-FILTERED stage rows (T-12310),
    so a carried-forward row can never admit a pass. Pure f(rows); never raises."""
    candidates = [r for r in (stage_rows or ()) if on_decisions_row_absorbable(r)]
    if not candidates:
        return None
    row = _ceiling_row_of(candidates)
    data = row.get("data") or {}
    ceiling_ref = data.get("ceiling_ref")
    if not ceiling_ref:
        return None
    for r in stage_rows or ():
        d = r.get("data") if isinstance(r, dict) and isinstance(r.get("data"), dict) else {}
        if (str(d.get("basis") or "") == ON_DECISIONS_ABSORPTION_BASIS
                and d.get("ceiling_ref") == ceiling_ref):
            return None
    return {"ceiling_ref": ceiling_ref, "on_decisions_row": row, "passes": data.get("passes")}


def on_decisions_bind(decisions, ceiling_ref, *, decision_names_subject) -> dict:
    """`{finding_fingerprint: decision payload}` over the `ceiling_decision` rows bound to THIS
    ceiling row.

    The `ceiling_ref` filter is not a convenience: rule 4 binds a decision to ONE (ceiling_ref,
    fingerprint) pair, so a decision recorded against a DIFFERENT pass of the same stage decided a
    different occurrence and must not admit this one. Append-only means a fingerprint is decided at
    most once per ref (`audit decide` refuses `decision-duplicate`); should a journal nevertheless
    carry two, the FIRST is kept — a later row can never quietly re-decide.

    A row that names NO subject is skipped as if absent (`decision_names_subject`, T-12383): it is
    the X-1371 wedge shape, superseded by the ONE corrected decision `audit decide` admits for the
    same fingerprint — which is therefore the row this keeps.

    Pure f(rows); never raises."""
    out = {}
    for row in decisions or ():
        data = row.get("data") if isinstance(row, dict) and isinstance(row.get("data"), dict) else {}
        if data.get("ceiling_ref") != ceiling_ref or not decision_names_subject(data):
            continue
        fp = data.get("finding_fingerprint")
        if isinstance(fp, str) and fp and fp not in out:
            out[fp] = data
    return out


def on_decisions_matrix(findings, *, tid, stage, verdict, residual_keys, decisions_by_fp,
                        repo_root=None, absorb_new=True, read_time_finding_key, verdict_excluding_late) -> dict:
    """SPEC-0204 rule 3's CLOSED RESULT MATRIX over the rule-3 pass's response.

    Returns `{"verdict", "overruled", "fix_open", "new", "new_entries", "absorbable", "dropped_echo",
    "findings"}` — the recomputed verdict, the fingerprints an `accept`/`defer` decision OVERRULED,
    the fingerprints of `fix` residuals the auditor re-raised OPEN, the findings that count NEW, the
    row entries for those NEW findings ({finding_fingerprint, severity, absorbable}), whether the
    pass as a whole is YELLOW-ABSORBABLE, the `echo_of` values that did not verify, and the finding
    list with every unverifiable `echo_of` DROPPED (and every NEW finding marked `absorbable`).

    THE ABSORBABLE ARM (T-12376 — SPEC-0204 rule 3 as amended; measured on T-12333 + T-12366, two
    cards burned in one batch by a bounded medium finding). With `absorb_new=True` (the rule-3 pass
    itself), a computed RED is folded to YELLOW — the ordinary absorption verdict — ONLY under the
    conjunction of THREE conditions, each stated because dropping any one of them re-opens a hole:
      (a) NO `fix` residual is echoed open (a fix that did not close is RED, whatever else is true);
      (b) the NEW set is NON-EMPTY — checked as `len(new) >= 1` EXPLICITLY, because `all()` over an
          empty set is vacuously true and would otherwise mark a zero-new-finding pass absorbable
          (the audit-pre finding on this card's own plan);
      (c) EVERY new finding's `severity` is in the CLOSED set `ABSORBABLE_NEW_FINDING_SEVERITIES`
          (medium | low) — a `high`, and an ABSENT or unknown severity, is NOT absorbable.
    `absorbable` is True only under (a)+(b)+(c); a new HIGH finding keeps the computed verdict
    (RED → terminal, rule 4) exactly as before. With `absorb_new=False` (the ONE absorption re-audit
    that a YELLOW-absorbable pass admits) the arm is OFF: a second new finding there counts at its
    own severity and a RED is terminal — the absorption is bounded to one re-audit per ceiling row.

    THE ENGINE VERIFIES `echo_of`, the auditor does not assert it (rule 3): a reference is honoured
    only when it names a residual of THIS ceiling row. An unverifiable reference is DROPPED from the
    finding and the finding counts NEW at its own severity — never silently overruled, which is the
    one direction an auditor could otherwise steer by naming a fingerprint of its choosing.
    Without a verified `echo_of`, a finding whose ENGINE-recomputed rule-1 key equals a residual's
    key is that residual's echo (T-12922): the same finding in new prose, never a coarser match.

    THE MATRIX:
      * an echo of an `accept` / `defer` residual  -> `overruled_by_decision`, removed from the
        driver set: the authority already settled it and this pass records, never re-argues, it;
      * an echo of a `fix` residual                -> `fix_open` -> RED, whatever word the auditor
        returned. Rule 3's one explicit clause: a fix that did not close is the pass's whole point;
      * anything else                              -> NEW, counting at its severity.

    The verdict of the remainder REUSES C4's `verdict_excluding_late(verdict, non_overruled)` rather
    than re-deriving a second downgrade rule: an overruled echo is removed from the driver set
    exactly as a late finding is, and the two must not disagree about what a REMAINING finding means
    (the `disposition: deferrable` fail-closed reading is C4's and stays C4's).

    ABORT is returned UNTOUCHED, findings and all — rule 5 owns the no-outcome class, and arithmetic
    over an empty list must never turn a run that observed nothing into a GREEN.

    Pure f(findings); never raises."""
    if str(verdict or "").strip().upper() == "ABORT":
        return {"verdict": verdict, "overruled": [], "fix_open": [], "new": [], "new_entries": [],
                "absorbable": False, "dropped_echo": [], "findings": list(findings or ())}
    keys = set(residual_keys or ())
    by_fp = decisions_by_fp if isinstance(decisions_by_fp, dict) else {}
    out_findings, overruled, fix_open, new, dropped = [], [], [], [], []
    fix_open_findings = []
    for f in findings or ():
        f = dict(f) if isinstance(f, dict) else {}
        echo = str(f.get("echo_of") or "").strip()
        disposition = (str((by_fp.get(echo) or {}).get("disposition") or "").strip().lower()
                       if echo and echo in keys else "")
        if not disposition:
            # T-12922 (X-1571) — rule 1's IDENTITY, not a coarser key: with no verified `echo_of`,
            # the engine RECOMPUTES the finding's key from its structured fields (a carried
            # `finding_fingerprint` is never trusted here) and, when that key IS a decided residual
            # of this row, binds the finding to it on the same arms. Reworded `what`/`where` prose
            # is outside the key, so it no longer re-raises a decided residual as NEW; a different
            # criterion, locator or failing_input is still a different key, still NEW.
            own, _deg = read_time_finding_key(tid, stage, f, repo_root=repo_root)
            own_disp = (str((by_fp.get(own) or {}).get("disposition") or "").strip().lower()
                        if own in keys else "")
            if own_disp in ("accept", "defer", "fix"):
                echo, disposition = own, own_disp
                f["echo_of"] = own
        if disposition in ("accept", "defer"):
            overruled.append(echo)
            out_findings.append(f)
            continue
        if disposition == "fix":
            fix_open.append(echo)
            fix_open_findings.append(f)
            out_findings.append(f)
            continue
        # Everything else is NEW. That INCLUDES a reference the engine could not verify — a
        # fingerprint on no residual of this row, or one whose decision carries no readable
        # disposition — and the field is DROPPED so the saved record never shows a claim the engine
        # refused to honour.
        if echo:
            f.pop("echo_of", None)
            dropped.append(echo)
        new.append(f)
        out_findings.append(f)
    # The DRIVER SET is everything the decisions did NOT overrule — the `fix` residuals re-raised
    # open, plus every NEW finding. Exactly the shape rule 8's exclusion takes, which is why the same
    # helper judges it.
    non_overruled = fix_open_findings + new
    computed = verdict_excluding_late(verdict, non_overruled)
    if fix_open:
        computed = "RED"      # rule 3's explicit clause — a `fix` residual echoed OPEN forces RED
    # T-12376 — the ABSORBABLE arm (docstring). Each NEW finding is keyed by the engine (rule 1 keys
    # only RED records at the record seam, and this arm exists precisely to make some of these passes
    # NOT RED — so the key is stamped here, where the finding is judged new) and marked per-finding;
    # the pass-level `absorbable` is the conjunction, with the non-empty check EXPLICIT.
    # T-12736 (SPEC-0204 rule 9(b), <project> X-1489) — THE KEY IS THE READER'S DECISION, NEVER A DIRECT
    # `finding_fingerprint` CALL. This stamp used to call `finding_fingerprint` verbatim, which hashes
    # the four structured fields whatever their presence. On a PLAN gate a finding carries NONE of
    # them (rule 9(b): the task parse floor is task-only), so every new finding of an on-decisions
    # plan-gate pass hashed the SAME all-null tuple: <project>'s pass-4 wrote 10 findings — four of them
    # high — under ONE `fp1:` key, and the kernel's own 2026-09-13 plan gates wrote 6->1, 4->1, 3->2.
    # Rule 9(f) then admits the next round once EVERY residual key is decided, so one recorded decision
    # discharged the whole set. `read_time_finding_key` is the ONE home of the fp1-vs-fp1d judgement
    # (a fieldless finding gets the marked `fp1d:` key over what+where): keying through it here makes
    # the writer and `row_residual_fingerprints` agree by construction, not by two call sites. A
    # well-formed TASK finding keys `fp1:` exactly as before — the canonical tuple and its version are
    # untouched, so no recorded key is invalidated (forward-only, the card's AC3).
    new_entries = []
    for f in new:
        if not f.get("finding_fingerprint"):
            f["finding_fingerprint"], _deg = read_time_finding_key(tid, stage, f, repo_root=repo_root)
        sev = str(f.get("severity") or "").strip().lower()
        f_absorbable = bool(absorb_new) and not fix_open and sev in ABSORBABLE_NEW_FINDING_SEVERITIES
        f["absorbable"] = f_absorbable
        new_entries.append({"finding_fingerprint": f["finding_fingerprint"],
                            "severity": f.get("severity"), "absorbable": f_absorbable})
    absorbable = (bool(absorb_new) and not fix_open and len(new_entries) >= 1
                  and all(e["absorbable"] for e in new_entries))
    if absorbable and computed == "RED":
        computed = "YELLOW"
    return {"verdict": computed, "overruled": overruled, "fix_open": fix_open, "new": new,
            "new_entries": new_entries, "absorbable": absorbable,
            "dropped_echo": dropped, "findings": out_findings,
            # T-12370 — the DRIVER SET, NAMED rather than recomputed. It is the `non_overruled` list
            # this function already built one line above; the currency bound
            # (`currency_verdict_bound`) needs exactly it, and a second reconstruction at that seam
            # could disagree with the set this verdict was computed from (CHARTER §P5). Additive: no
            # existing reader of this mapping is touched.
            "drivers": list(non_overruled)}


#: T-13169 — the recorded fields of a residual the rule-3 packet renders beside its fingerprint.
RESIDUAL_RECORDED_FIELDS = ("severity", "criterion_ref", "locator", "failing_input", "what")


def on_decisions_packet_block(projection) -> str:
    """Render the rule-3 packet section: the decided residuals, what each disposition MEANS for this
    pass, and the `echo_of` REQUIREMENT.

    THE UNRESOLVABLE LINE IS PRINTED EXPLICITLY (audit-pre pass-1 finding 1): a packet that rendered
    an empty residual list would read identically to «this pass found nothing», and a reader could
    not tell the two apart. The DEGRADED count is printed for the same reason — a pre-contract
    ceiling row was keyed at READ time, and the auditor should know that before matching against
    those keys.

    Pure f(projection); never raises."""
    p = projection if isinstance(projection, dict) else {}
    rows = p.get("residuals") or []
    if p.get("mode") == "currency":
        # T-13169 — an AUDIT-CURRENCY re-audit is not the bounded pass and spends none (T-12370), so
        # it must not be introduced as one; what it shares with that pass is only that the recorded
        # decisions govern the findings it returns.
        _intro = (f"This is an AUDIT-CURRENCY re-audit of the merged tree for {p.get('task')} "
                  f"audit-{p.get('stage')} — not a counted pass. The ceiling row `{p.get('ceiling_ref')}` "
                  f"carries typed decisions the Controller recorded, and they govern what you return "
                  f"here exactly as on the bounded pass. The subject audited here is "
                  f"`{p.get('named_revision') or '(the current head)'}`.\n")
    else:
        _intro = (f"This is the ONE bounded pass past the audit-loop ceiling for {p.get('task')} "
                  f"audit-{p.get('stage')}. Its ceiling row is `{p.get('ceiling_ref')}` and the "
                  f"Controller has recorded a typed decision for EVERY residual of it. The subject "
                  f"audited here is `{p.get('named_revision') or '(the ceiling row subject)'}`.\n")
    lines = [
        "\n### Ceiling decisions — this pass is GOVERNED BY THEM (SPEC-0204 rules 3-5)\n",
        _intro,
    ]
    if p.get("mode") == "absorption-reaudit":
        # T-12376 — the ONE absorption re-audit: same decisions, same echo discipline, but the
        # auditor is told this pass is the LAST at this stage, so a further NEW finding is terminal.
        lines.append(
            "**ABSORPTION RE-AUDIT (SPEC-0204 rule 3, amended T-12376).** The decided pass above came "
            "back YELLOW with NEW medium/low finding(s) the card ABSORBED (fix + `task commit --absorb`); "
            "this is the ONE bounded re-audit of that absorption under the same ceiling row. Verify the "
            "absorbed finding(s) closed and any regression the fix introduced. The decisions in the "
            "table still govern: echo them with `echo_of`. No further pass exists at this stage — a "
            "NEW finding here, at any severity, is a defect the card cannot absorb again.\n")
    if p.get("superseded_null_subject"):
        # T-12383 — the null-subject row is SEEN and SET ASIDE, said out loud rather than dropped.
        lines.append(
            "**SUPERSEDED null-subject decision row(s)** — a stored `ceiling_decision` naming NO "
            "`subject_revision` is not a decision (SPEC-0204 rule 2, X-1371); the corrected decision "
            "for the same fingerprint governs instead: "
            + ", ".join(f"`{fp}`" for fp in p["superseded_null_subject"]) + ".\n")
    if p.get("unresolvable"):
        lines.append(
            "**UNRESOLVABLE residual set** — the ceiling row states no findings and its saved record "
            "resolves none, so the list below is EMPTY FOR THAT REASON and not because the prior pass "
            "found nothing. Judge accordingly.\n")
    if p.get("non_defect_rows_skipped"):
        lines.append(
            f"non_defect_rows_skipped: {p['non_defect_rows_skipped']} — rows of the ceiling record "
            f"whose severity states no defect (pass/ok/none/info) are not residuals and carry no "
            f"decision (T-12402).\n")
    if p.get("degraded"):
        lines.append(
            f"{p['degraded']} of the residuals below were keyed at READ time (`fp1d:` — the ceiling "
            f"row predates the fingerprint contract), so their identity is derived from the saved "
            f"record rather than stamped by the engine at record time.\n")
    if not rows:
        lines.append("_(no residual is listed — see above)_\n")
    else:
        lines.append("| # | fingerprint | decision | detail |\n|---|---|---|---|\n")
        for i, r in enumerate(rows, 1):
            detail = []
            if r.get("reason"):
                detail.append(str(r["reason"]))
            if r.get("receiving_task"):
                detail.append(f"receiving card {r['receiving_task']}")
            if r.get("evidence_revision"):
                detail.append(f"evidence {r['evidence_revision']}")
            if r.get("late"):
                detail.append("recorded as a LATE finding (rule 8)")
            lines.append(f"| {i} | `{r.get('finding_fingerprint')}` | "
                         f"**{r.get('disposition') or '(none)'}** | "
                         f"{'; '.join(detail).replace('|', '/') or '—'} |\n")
        # T-13169 — WHAT each residual WAS, verbatim from its record: without it the auditor holds a
        # fingerprint it cannot recognise, re-describes a decided defect in new words, and the
        # engine — which never matches on prose — counts it NEW (<project> T-0752, X-1549).
        lines.append("\nWhat each residual above RECORDED (verbatim — copy these fields, or name "
                     "its fingerprint in `echo_of`, when you re-raise it):\n")
        for i, r in enumerate(rows, 1):
            rec = r.get("recorded")
            if not rec:
                lines.append(f"  {i}. `{r.get('finding_fingerprint')}` — no recorded finding "
                             f"resolves for this fingerprint; only the decision above is known.\n")
                continue
            lines.append(f"  {i}. `{r.get('finding_fingerprint')}`\n")
            for k in RESIDUAL_RECORDED_FIELDS:
                if k in rec:
                    lines.append(f"     {k}: {' '.join(str(rec[k]).split())}\n")
    lines.append(
        "\nWhat each disposition asks of YOU on this pass:\n"
        "  * `fix`    — VERIFY it at the subject above. Is the defect actually closed, and what is "
        "the evidence?\n"
        "             A `fix` you find still OPEN makes this pass RED, whatever else you conclude.\n"
        "  * `accept` — AUTHORITY-ACCEPTED and RECORDED, never re-argued. It is not a defect of this\n"
        "             pass; do not spend the pass re-making the case against it.\n"
        "  * `defer`  — OUT OF THIS SUBJECT: it rides the receiving card named above. Not a defect "
        "here.\n"
        "\n**REQUIRED — `echo_of` on every finding that re-raises a residual above:**\n"
        "```yaml\n"
        "  - severity: high\n"
        "    echo_of: <the EXACT fingerprint from the table above>\n"
        "    criterion_ref: …        # keep the prior finding's fields EXACTLY as recorded\n"
        "    locator: …\n"
        "    failing_input: …\n"
        "```\n"
        "The engine VERIFIES `echo_of` against the table: a value naming no residual above is "
        "DROPPED and\n"
        "that finding counts as a NEW one at its own severity. Re-describing a decided residual in "
        "new words\n"
        "WITHOUT `echo_of` therefore reads as a new defect — name the fingerprint, or raise it as "
        "genuinely new.\n"
        "\n**POSSIBLE UNBOUND ECHO — FLAGGED, never bound (T-13431):** a finding WITHOUT `echo_of` "
        "whose text names a\nreceiving card or a fingerprint from the table above, or that shares a "
        "residual's `criterion_ref`\nand `locator`, is reported LOUDLY on the journal record as a "
        "possible unbound echo — and it still\ncounts NEW. So for every finding at a decided "
        "residual's ground: carry `echo_of`, or state in the\nfinding why it is a NEW defect.\n")
    return "".join(lines)


def on_decisions_projection(*, tid, stage, ceiling_ref, residual_keys, decisions_by_fp,
                            degraded=0, unresolvable=False, late=None,
                            named_revision=None, mode="on-decisions",
                            superseded_null_subject=None, non_defect_rows_skipped=0,
                            residual_records=None) -> dict:
    """The PACKET PROJECTION of rule 3: every residual WITH its fingerprint and its decision beside
    it, plus the read-path facts a reader needs to judge what it is looking at.

    Returns a plain mapping (`on_decisions_packet_block` renders it) so the projection is testable
    without parsing prose. `late` marks a residual that came from a `late_findings[]` entry rather
    than from the ceiling row's own `findings[]` — the auditor is told which, because rule 8 makes a
    late finding a different kind of thing from a residual of the audited subject.

    `residual_records` (T-13169) is `{fingerprint: recorded finding entry}` from
    `residual_finding_records`: each residual then carries its RECORDED `severity` / `criterion_ref` /
    `locator` / `failing_input` / `what` under `recorded`, so the auditor sees WHAT was decided and can
    name `echo_of` for a re-raise it would otherwise re-describe as new (<project> T-0752, X-1549). A
    residual with no resolvable record carries `recorded: None` — never an invented field.

    Pure; never raises."""
    by_fp = decisions_by_fp if isinstance(decisions_by_fp, dict) else {}
    late_index = late if isinstance(late, dict) else {}
    records = residual_records if isinstance(residual_records, dict) else {}
    residuals = []
    for fp in (residual_keys or ()):
        d = by_fp.get(fp) or {}
        rec = records.get(fp) if isinstance(records.get(fp), dict) else None
        residuals.append({
            "finding_fingerprint": fp,
            "disposition": d.get("disposition"),
            "reason": d.get("reason"),
            "receiving_task": d.get("receiving_task"),
            "evidence_revision": d.get("evidence_revision"),
            "late": fp in late_index,
            "recorded": ({k: rec.get(k) for k in RESIDUAL_RECORDED_FIELDS if rec.get(k) is not None}
                         if rec is not None else None),
        })
    return {"task": tid, "stage": stage, "ceiling_ref": ceiling_ref,
            "named_revision": named_revision, "degraded": int(degraded or 0),
            "unresolvable": bool(unresolvable), "residuals": residuals,
            # T-12376 — `on-decisions` (the rule-3 pass) or `absorption-reaudit` (the ONE bounded
            # mode-a re-audit a YELLOW-absorbable rule-3 verdict admits under the same ceiling_ref);
            # T-13169 — or `currency` (an audit-currency re-audit the recorded decisions govern).
            "mode": mode,
            # T-12383 — fingerprints whose null-subject rows the bind passed over (X-1371 recovery).
            "superseded_null_subject": list(superseded_null_subject or ()),
            # T-12402 — non-defect rows (`severity: pass` …) the residual reader skipped.
            "non_defect_rows_skipped": int(non_defect_rows_skipped or 0)}


def on_decisions_residuals(ceiling_row, stage_rows, tid, stage, *, repo_root=None,
                           decisions_dir=None, record=None, commit_reachable=None, _currency_finding_index, _late_finding_index, row_residual_fingerprints) -> dict:
    """SPEC-0204 rule 3 — THE RESIDUAL SET of a (task, stage) at the ceiling.

    Returns `{"keys": [...], "decidable": [...], "currency": {fingerprint: ts}, "degraded": int,
    "unresolvable": bool, "unresolvable_reason": str|None, "passes": int|None,
    "late": {fingerprint: basis}, "stale": bool, "stale_reason": str|None}`.

    `keys` vs `decidable` (T-12422) — TWO SETS, TWO QUESTIONS. `keys` is «what must this pass have
    decided?» and is what `on_decisions_admission` refuses on; `decidable` is «what may the
    authority record a decision about?» and additionally carries the findings of a `basis: currency`
    row (`_currency_finding_index`). A currency check is not one of the card's counted passes, so
    its findings are not residuals the pass must have settled — but they are not thereby ignorable
    either, and before this split no verb could dispose of one at all.

    `stale` / `stale_reason` / `commit_reachable` are C1's, PASSED THROUGH unread (T-12370). A stale
    row is NOT unresolvable, so it takes the ordinary empty-residual path here and `on_decisions_
    admission` admits it exactly as it admits the T-12311 empty set — which is the intent: a row
    whose subject was rolled back must be SUPERSEDABLE by the next currency check, never a wall. It
    is surfaced so a reader (and the packet projection) can say WHICH of the two zero-key facts this
    is; nothing in this module branches on it.

    The set is the ceiling row's `findings[]` UNION every `late_findings[]` entry rule 8 records on
    the (task, stage) rows — read through C1's `row_residual_fingerprints` and C2's
    `_late_finding_index` respectively, so this side and `audit decide` key a residual IDENTICALLY by
    construction rather than by two loops agreeing (CHARTER §P5). Order is the ceiling row's own,
    then the late findings that are not already in it; duplicates are dropped, never doubled.

    `unresolvable` IS CARRIED, AND CARRYING IT IS THE POINT (audit-pre pass-1 finding 1). C1 returns
    `unresolvable: True` with an EMPTY key list for a ceiling row that states no findings and whose
    saved record resolves none — so a caller that iterated `keys` alone would read «no residual is
    undecided» and ADMIT a pass on a row whose residual set nobody could resolve. The flag is
    threaded into `on_decisions_admission` as a HARD refusal and printed in the projection.

    `degraded` is C1's count of `fp1d:` read-time keys (a pre-contract ceiling row); it changes no
    decision here and is rendered in the packet so the auditor sees the row was keyed at read time.

    Pure read; never raises."""
    residual = row_residual_fingerprints(ceiling_row, repo_root=repo_root,
                                         decisions_dir=decisions_dir, record=record,
                                         commit_reachable=commit_reachable)
    late = _late_finding_index(stage_rows, tid, stage, repo_root=repo_root)
    keys = list(residual.get("keys") or ())
    seen = set(keys)
    for k in late:
        if k not in seen:
            seen.add(k)
            keys.append(k)
    # T-12422 — THE DECIDABLE SET, SPLIT FROM THE MUST-BE-DECIDED SET. `keys` is UNCHANGED: it stays
    # exactly the set `on_decisions_admission` requires to carry a decision, so no card that is
    # admitted today starts being refused. `decidable` ADDS the findings of any `basis: currency`
    # row — decidable by the authority (`audit decide`) and matchable by an `echo_of`, but NOT
    # residuals this pass must have decided, because a currency check is not one of the card's
    # passes. Two names because they answer two different questions; collapsing them would either
    # make a currency finding block the pass (it is not the card's residual) or leave it undecidable
    # (the T-12340 wedge).
    currency = _currency_finding_index(stage_rows, tid, stage, repo_root=repo_root)
    decidable = list(keys)
    _seen_dec = set(decidable)
    for k in currency:
        if k not in _seen_dec:
            _seen_dec.add(k)
            decidable.append(k)
    return {"keys": keys,
            "decidable": decidable,
            "currency": currency,
            "degraded": int(residual.get("degraded") or 0),
            "unresolvable": bool(residual.get("unresolvable")),
            "unresolvable_reason": residual.get("unresolvable_reason"),
            "stale": bool(residual.get("stale")),
            "stale_reason": residual.get("stale_reason"),
            "passes": residual.get("passes"),
            "non_defect_skipped": int(residual.get("non_defect_skipped") or 0),
            "collapsed_rekeyed": int(residual.get("collapsed_rekeyed") or 0),     # T-12736
            "late": late}


def on_decisions_row_absorbable(row, *, ON_DECISIONS_BASIS) -> bool:
    """T-12376 — is this `external_audit_completed` row a YELLOW-ABSORBABLE rule-3 verdict?

    True iff the row carries `basis: on-decisions`, `verdict: YELLOW`, and a NON-EMPTY `new_findings`
    list every entry of which is `absorbable: true`. Read off the ROW (the canonical store, rule 1),
    never the YAML; a legacy row whose `new_findings` is the pre-T-12376 integer count is NOT
    absorbable (it recorded no per-finding judgement). Pure f(row); never raises."""
    data = row.get("data") if isinstance(row, dict) and isinstance(row.get("data"), dict) else {}
    if str(data.get("basis") or "") != ON_DECISIONS_BASIS:
        return False
    if str(data.get("verdict") or "").strip().upper() != "YELLOW":
        return False
    entries = data.get("new_findings")
    if not isinstance(entries, list) or not entries:
        return False
    return all(isinstance(e, dict) and e.get("absorbable") is True for e in entries)


def on_decisions_row_problems(row_data, *, validate_ceiling_payload) -> list:
    """The payload problems of a rule-3 completion row that THIS write site must refuse on.

    It calls C1's shared `validate_ceiling_payload('external_audit_completed', ...)` — the one
    validator, never a second one — and keeps only the problems naming a key in
    `_C3_ROW_EXTENSION_KEYS`.

    WHY THE FILTER EXISTS, stated here because a silent narrowing of a validator is exactly what a
    later reader would take for a bug — and it is the SAME filter, for the SAME reason, that C4's
    `late_findings_row_problems` applies (that docstring carries the long form). C1's
    `external_audit_completed` branch is ALL-OR-NOTHING over the nine-key extension union: once ANY
    declared key is present it reports every other as `missing:`. A rule-3 row legitimately carries
    the five keys below plus `passes` (and `findings` only when the pass is RED), so the unfiltered
    call also reports `late_findings` and a row-level `finding_fingerprint` that no write site in the
    system writes at all. Refusing on those would make every rule-3 pass die.

    WHAT IS STILL CAUGHT is what this site can actually be wrong about: one of its five keys computed
    but not written, or written under a misspelling (which reads as `missing:<key>`).

    Pure f(row_data); never raises."""
    problems = validate_ceiling_payload("external_audit_completed", row_data)
    owned = {f"missing:{k}" for k in _C3_ROW_EXTENSION_KEYS}
    owned |= {f"unknown:{k}" for k in _C3_ROW_EXTENSION_KEYS}
    return [p for p in problems if p in owned]


def _on_decisions_row_is_real(row, stage_rows, rows, tid, stage, *, ON_DECISIONS_BASIS, _decide_row_is_for) -> bool:
    """Is this `external_audit_completed` row a REAL SPEC-0204 rule-3 verdict, or a PHANTOM?

    Rule 3 contracts the `--on-decisions` pass as ONE pass that RUNS A REAL AUDITOR on the recorded
    decisions, and rule 4 makes its RED terminal for the (task, stage). Before T-12309 the two could
    come apart: an ADMITTED rule-3 pass at an unchanged plan fingerprint was pre-empted by the T-0544
    carry-forward, which invokes no auditor at all — yet the closing row still carried `basis:
    on-decisions` + the carried RED. Rule 4 then read that row as the stage's terminal verdict and
    dead-ended the card on a pass that never happened (measured live on T-12305 and T-12306,
    2026-09-10T03:3xZ / 05:10Z). T-12309 closed the CAUSE; the rows it already wrote are still in the
    append-only journal, so this predicate is what stops them being LOAD-BEARING.

    THE TEST IS THE AUDITOR INVOCATION, read off the journal's own witness of it: an
    `audit_prompt_sent` row for the SAME (task, stage) inside this row's admission window — after the
    PRECEDING (task, stage) completion row (the pass this one follows) and at/before this row's own
    `ts`. Every path that sends a prompt emits that row FIRST, and the two short-circuit arms that
    send none (T-0544 unchanged-fingerprint, T-10084 zero-ship-diff) deliberately emit none — so the
    row's presence is the invocation, not a proxy for it. The window matters as much as the row: an
    EARLIER real pass's prompt must not vouch for a later phantom, which is exactly the T-12306 shape
    (its last `audit_prompt_sent` sits at 03:2xZ, one pass before the 03:40:04Z phantom).

    A row that does NOT claim `basis: ON_DECISIONS_BASIS` is True by construction — there is nothing
    here to judge, and this predicate never touches an ordinary pass. Pure f(rows); never raises; it
    opens no journal of its own (the caller passes the rows the at-ceiling fold already folded —
    SPEC-0190 rule 10)."""
    data = row.get("data") if isinstance(row, dict) and isinstance(row.get("data"), dict) else {}
    if str(data.get("basis") or "") != ON_DECISIONS_BASIS:
        return True
    ts = str(row.get("ts") or "")
    # The admission window opens at the preceding (task, stage) completion row; before the first
    # such row it is open-ended (the empty string sorts below every ISO timestamp).
    prior_ts = max((str(r.get("ts") or "") for r in stage_rows or ()
                    if str(r.get("ts") or "") < ts), default="")
    for r in rows or ():
        if not isinstance(r, dict) or r.get("type") != "audit_prompt_sent":
            continue
        if not _decide_row_is_for(r, tid):
            continue
        d = r.get("data") if isinstance(r.get("data"), dict) else {}
        if d.get("stage") != stage:
            continue
        if prior_ts < str(r.get("ts") or "") <= ts:
            return True
    return False


def plan_gate_synthetic_ceiling_row(slug, gate_id, template, record, *, saved_to=None) -> dict:
    """The READ-TIME ceiling row of a plan gate whose ceiling was reached BEFORE any row was emitted.

    NOT A BACKFILL, and the distinction is the whole design. A backfill would append history to an
    append-only journal for passes that are over, inventing a `ts` and an authorship for rows nobody
    emitted. This row is a pure `f(record)`: it is never appended, never emitted, and carries
    `synthesized_from` so a projection can tell an operator WHICH source answered. It exists because
    the two consumer plans this arm was written to unwedge reached their ceilings with no row, and no
    row will ever be written for them — `plan_gate_ceiling_row_payload` only covers FUTURE gate runs.

    It carries NO `findings[]` DELIBERATELY, so `row_residual_fingerprints` takes its shape-(c)
    branch — «the saved record is the SOLE source of its degraded key» — with the record INJECTED
    (see that function's `record` parameter for why injection rather than a plan-shaped twin). That is
    what keeps the T-12319 this-row's-record checks, the EXPLICIT-`passes` take and the T-12311
    empty-vs-unresolvable distinction applying here unchanged and un-restated.

    `passes` is written ONLY when the record states an INT — never through `_passes_recorded`, whose
    documented legacy default of 1 for an absent field is a real ceiling-arithmetic value and would
    let a record stating NOTHING answer «this IS a ceiling row». Absent → the row carries no counter,
    the reader returns `passes: None`, and the caller refuses `ceiling_row_passes_unresolved` exactly
    as the task arm does.

    Pure; never raises."""
    record = record if isinstance(record, dict) else {}
    data = {
        "stage": str(gate_id),
        "verdict": record.get("verdict"),
        "target_kind": "plan",
        "target_id": str(slug),
        "gate": str(gate_id),
        "stage_template": str(template),
        "synthesized_from": str(saved_to) if saved_to else None,
    }
    passes = record.get("passes")
    if isinstance(passes, int):
        data["passes"] = passes
    return {"ts": str(record.get("date") or ""), "type": "external_audit_completed",
            "task_id": None, "data": data}


def prior_audit_record(tid: str, stage: str, *, decisions_dir: Path, audit_yaml_path, state) -> dict | None:
    """T-0486 — read the PRIOR saved decisions/<tid>-audit-<stage>.yaml mapping (or None if no prior
    file / unparseable). Sibling of count_audit_passes (same tolerant read) — exposes both the prior
    `verdict` AND the prior `corpus_signature` from ONE read (P5: a single reader), so cmd_audit can
    decide a PLAN freshness re-audit (already-GREEN + a genuinely-stale corpus_signature) without a
    second YAML load. Pure read, no I/O side-effects. Reads the active decisions/ path OR the archive
    fallback (T-0527/SPEC-0052) — an archived (closed) task's prior record is still resolvable."""
    audit_path = audit_yaml_path(tid, stage, decisions_dir=decisions_dir)
    if audit_path is None:
        return None
    try:
        import yaml
        d = state.load_str(audit_path.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else None
    except (yaml.YAMLError, OSError):
        return None  # file exists but unparseable — no usable prior record (fail-closed)


def row_residual_fingerprints(row, *, repo_root=None, decisions_dir=None, record=None,
                              commit_reachable=None, CURRENCY_BASIS, DEGRADED_FINDING_FINGERPRINT_VERSION, FINDING_FINGERPRINT_VERSION, is_non_defect_finding, prior_audit_record, read_time_finding_key) -> dict:
    """SPEC-0204 rule 1 / T-12293 AC4 — the ROW-LEVEL read path: the residual keys of ONE
    `external_audit_completed` row, how many are DEGRADED, whether they could be resolved at all, and
    the row's RESOLVED `passes`.

    Returns `{"keys": [...], "degraded": int, "unresolvable": bool, "passes": int|None,
    "unresolvable_reason": str|None, "stale": bool, "stale_reason": str|None}` — the reason is set
    ONLY when `unresolvable`, and names WHICH check refused the record.

    `stale` IS A THIRD FACT, NOT A SOFTER `unresolvable` (T-12370). It is set when the subject leg
    below would have refused the record AND the ROW'S OWN COMMIT IS CONTAINED IN NO BRANCH — the
    record did not go missing, the row's SUBJECT was ROLLED BACK. Measured on T-12315 (deviation
    2026-09-10T23:46:24Z): the in-land re-audit recorded its row at the land BOOKKEEPING commit
    28db87a, the same land then ABORTed after verify, `_land_rollback_bookkeeping_to_entry` took that
    commit back off the branch, and every later admission — in-land and by hand — refused
    `unresolvable subject-commit-mismatch(row=28db87a,record=f7ae441)`. A done, twice-green card was
    wedged by its own land bookkeeping, and the recovery was a raw-git `git show` of a commit object
    no branch contained. «I cannot resolve this row» and «this row names a subject that no longer
    exists» need different reader actions, and only the second may be superseded by the next
    currency check.

    IT IS NARROW AND FAIL-CLOSED IN BOTH DIRECTIONS. `commit_reachable(sha) -> bool|None` is
    INJECTED; an UNINJECTED caller, a `None` answer («could not tell») and a `True` answer all keep
    today's `unresolvable` verbatim. Only an explicit `False` — git said no branch contains it —
    reads `stale`. And it reaches ONLY the subject leg: a verdict-mismatch, a missing saved record
    and a malformed one are unchanged, because none of them is a statement about the subject.

    A SAVED RECORD RESOLVES A ROW ONLY WHEN IT IS *THAT ROW'S* RECORD (T-12319): its `verdict` must
    equal the row's, and for audit-POST its `commit` must START WITH the row's `data.commit` when
    both sides carry one. A record failing either is not the row's source — zero keys,
    `unresolvable: True`, `passes` None. `audited_at` is never compared (two independent clock reads,
    ~9% skew); see the guard's own comment for the measurement. This closes the hole the archive
    fallback opened: a DROPPED record does not get answered for by an ARCHIVED pass of the same task.

    THREE ROW SHAPES, and the LEGACY read path is a Controller SCOPE decision settled by authority
    (owner_directive events.jsonl#ts=2026-09-08T19:33:49Z), written into T-12293's AC4:

      (a) POST-CONTRACT — the row carries `findings[]` each with an engine `finding_fingerprint`.
          Returned VERBATIM, degraded 0. This is the case SPEC-0204 rule 1's journal-only resolution
          binds: the row IS the source, so a hand-edited YAML changes nothing.
      (b) PRE-CONTRACT with findings ON the row but WITHOUT the structured fields — keyed through
          `read_time_finding_key`, every key counted degraded.
      (c) PRE-CONTRACT with NO `findings[]` at all — which is EVERY pre-contract row (measured 0/5 on
          the five trial cards). Its findings are loaded from the SAVED verdict YAML
          `decisions/<tid>-audit-<stage>.yaml` through the EXISTING reader `prior_audit_record`,
          NEVER a second YAML parser (CHARTER §P5). A pre-contract row has no journal findings to
          resolve from, so its saved record is the SOLE source of its degraded key.

    A row with no findings AND no resolvable saved record resolves to ZERO keys and is REPORTED
    `unresolvable: True` — never a silent empty, which a caller could not tell from "this pass found
    nothing".

    AND THE CONVERSE, which is a DIFFERENT FACT WEARING THE SAME ZERO KEYS (T-12311): a row with no
    findings whose saved record DOES resolve — it carries a non-empty `verdict` of GREEN or YELLOW
    and an explicit `findings` LIST that is empty — resolves to ZERO keys with `unresolvable: False`.
    That record does not fail to say what the pass found; it says the pass found nothing, and its
    residual set is EMPTY. The distinction is load-bearing at exactly one reader: SPEC-0204 rule 3
    admits the `--on-decisions` pass over an empty residual set (zero decisions to record) and
    HARD-REFUSES an unresolvable one. Collapsing the two closed every exit for a done-but-unlanded
    card reworked in place — no re-audit (over the ceiling), no decision (nothing to decide), no land
    (SPEC-0077 §3a). A RED or ABORT verdict with no findings is a malformed record rather than an
    empty one and stays `unresolvable: True`, fail-closed.

    A GREEN ROW ANSWERS FOR ITSELF WHEN A CURRENCY PASS DISPLACED ITS RECORD (T-12422). The saved
    record is ONE FILE PER (task, stage) and an AUDIT-CURRENCY re-audit rewrites it while being no
    pass of the card at all — so it can destroy a counted GREEN ceiling row's only source of
    residuals. When the rejected record is provably that currency pass's AND the row itself says
    GREEN, the row resolves EMPTY off its own verdict (SPEC-0204 rule 7: GREEN and an undecided
    residual are mutually exclusive). Bounded on BOTH sides — a non-GREEN row, and any other reason
    a record fails to resolve, keep today's `unresolvable` verbatim.

    THE RESOLVED `passes` (T-12293, absorbing audit-pre pass 1): taken from the ROW when it carries
    one, and OTHERWISE from the SAVED record loaded by the SAME single `prior_audit_record` call this
    function already makes for the findings — one read, one reader. It is read as the record's
    EXPLICIT value and never through `_passes_recorded`, whose documented legacy default of `1` for an
    absent `passes` is a real ceiling-arithmetic value: routing through it would make a record that
    states NOTHING about passes silently answer "this is not a ceiling row". Unresolvable therefore
    yields `passes: None`, and no caller may treat `None` as a number.

    Pure read; never raises."""
    row = row if isinstance(row, dict) else {}
    data = row.get("data") if isinstance(row.get("data"), dict) else {}
    task = row.get("task_id") or data.get("target_id") or data.get("task_id")
    stage = data.get("stage")
    row_findings = data.get("findings")
    row_passes = data.get("passes")
    passes = int(row_passes) if isinstance(row_passes, int) else None

    def _out(keys, degraded, unresolvable, reason=None, stale=False, non_defect_skipped=0,
             collapsed_rekeyed=0):
        return {"keys": list(keys), "degraded": int(degraded),
                "unresolvable": bool(unresolvable), "passes": passes,
                "unresolvable_reason": (reason if unresolvable else None),
                # T-12370 — always PRESENT so a reader never has to tell an absent key from a False
                # one; `stale_reason` mirrors `unresolvable_reason`'s set-only-when-true rule.
                "stale": bool(stale),
                "stale_reason": (reason if stale else None),
                # T-12402 — how many NON-DEFECT rows (`severity: pass` …) were skipped as no residual.
                "non_defect_skipped": int(non_defect_skipped),
                # T-12736 — how many stored `fp1:` keys that COLLIDED on this row were re-keyed at
                # read time (see the shape-(a) block); 0 on every row whose stored keys are distinct.
                "collapsed_rekeyed": int(collapsed_rekeyed)}

    if isinstance(row_findings, list) and row_findings:
        keys, degraded, skipped = [], 0, 0
        # T-12736 — the findings behind each stored `fp1:` key, so a COLLISION (one stored key carried
        # by more than one finding) can be told from the ordinary one-key-one-finding shape below.
        _stored_at, _rekeyable = {}, {}
        for f in row_findings:
            f = f if isinstance(f, dict) else {}
            if is_non_defect_finding(f):                   # T-12402 — not a residual, never keyed
                skipped += 1
                continue
            engine_fp = f.get("finding_fingerprint")
            if isinstance(engine_fp, str) and engine_fp.startswith(FINDING_FINGERPRINT_VERSION + ":"):
                _stored_at.setdefault(engine_fp, []).append(len(keys))
                _rekeyable[len(keys)] = f
                keys.append(engine_fp)                     # shape (a) — verbatim, never recomputed
                continue
            if (isinstance(engine_fp, str)
                    and engine_fp.startswith(DEGRADED_FINDING_FINGERPRINT_VERSION + ":")):
                # T-12736 — a stored DEGRADED engine key is ALSO verbatim (the rule `finding_key_of`
                # already holds for the rule-8 late-finding reader): the on-decisions writer now
                # stamps a fieldless finding `fp1d:` (SPEC-0204 rule 9(b)), and recomputing it here
                # from fields that may since have been re-serialized could silently change it.
                keys.append(engine_fp)
                degraded += 1
                continue
            k, deg = read_time_finding_key(task, stage, f, repo_root=repo_root)   # shape (b)
            keys.append(k)
            degraded += 1 if deg else 0
        # ── T-12736 — COLLAPSED STORED KEYS ARE RE-KEYED, ON THE COLLIDING FINDINGS ONLY ──────────
        # A stored `fp1:` key carried by MORE THAN ONE finding of the same row is a WRITER DEFECT, not
        # an identity: rule 1 keys a finding on its structured fields, so two findings under one key
        # were either byte-identical (the auditor said the same thing twice) or — the measured case —
        # FIELDLESS findings hashed on an all-null tuple by the pre-T-12736 `on_decisions_matrix`
        # (<project> X-1489: 10 findings under `fp1:77f4daca93d31c92`; this repo's own 2026-09-13
        # plan gates: 6->1, 4->1, 3->2). Read verbatim, such a row lets ONE `ceiling_decision`
        # discharge every finding under the key — the exact laundering rule 9(f) exists to prevent.
        # So the colliding findings are re-keyed through `read_time_finding_key`, the key rule 9(b)
        # prescribed for them all along (a fieldless finding -> the marked `fp1d:` key over
        # what+where), and the count is REPORTED as `collapsed_rekeyed`.
        #
        # SCOPED TO COLLISIONS. A stored key carried by exactly ONE finding stands for exactly one
        # residual and is never touched — so every row whose keys are distinct (every TASK row: the
        # parse floor guarantees the fields) reads byte-for-byte as before, and a decision recorded
        # against such a key keeps its reach. FORWARD-ONLY (the card's AC3): no journal row is
        # rewritten and `on_decisions_bind` is untouched, so a decision recorded against a collapsed
        # key still reads as bound to its (ceiling_ref, fingerprint); what it can no longer do is
        # stand for N residuals at a FUTURE admission of that row (measured 2026-09-18: no live gate
        # depends on one). If the re-key STILL collides (byte-identical prose), `on_decisions_
        # admission` refuses the set (`residual_keys_collapsed`) rather than let one decision cover it.
        rekeyed = 0
        for _fp, _idxs in _stored_at.items():
            if len(_idxs) < 2:
                continue
            for _i in _idxs:
                k, deg = read_time_finding_key(task, stage, _rekeyable[_i], repo_root=repo_root)
                keys[_i] = k
                degraded += 1 if deg else 0
                rekeyed += 1
        return _out(keys, degraded, False, non_defect_skipped=skipped, collapsed_rekeyed=rekeyed)

    # shape (c) — the row states no findings at all; the saved record is the sole source.
    #
    # `record` IS THAT SOURCE, SUPPLIED (T-12335, the plan-gate arm). `prior_audit_record` resolves a
    # record by `decisions/<id>-audit-<stage>.yaml`, which is the right address for a TASK stage
    # (`pre`/`post`) and the WRONG one for a PLAN GATE: a gate's record is named by its TEMPLATE
    # (`<slug>-audit-gate-specs.yaml`), not by the gate id this row carries as its `stage`. So the
    # plan arm resolves the RECORD with its own gate→template map and hands it in, and EVERY rule
    # below — the T-12319 this-row's-record checks, the explicit `passes` take, the T-12311
    # empty-vs-unresolvable distinction, the keying through `read_time_finding_key` — applies to it
    # UNCHANGED. That is the point of injecting it rather than writing a plan-shaped twin of this
    # function: one reader, one set of rules, one place a later fix lands (CHARTER §P5).
    if record is not None:
        rec = record if isinstance(record, dict) else None
    elif not (task and stage and decisions_dir):
        return _out([], 0, True, "row-names-no-record-to-resolve-from")
    else:
        try:
            rec = prior_audit_record(str(task), str(stage), decisions_dir=Path(decisions_dir))
        except Exception:  # noqa: BLE001 — an unreadable decisions dir is an unresolvable row, never a raise
            rec = None
    if not isinstance(rec, dict):
        return _out([], 0, True, "no-saved-record")

    # ── THE RECORD MUST BE *THIS ROW'S* RECORD (T-12319) ──────────────────────────────────────────
    # `prior_audit_record` answers «what is the saved record for this (task, stage)?» — the ACTIVE
    # path, else the SPEC-0052 archive. That is the right answer to ITS question and is left alone.
    # It is NOT the answer to THIS reader's question, which is «what did THE PASS THIS ROW RECORDS
    # find?». The two diverge whenever the row's own record is gone: measured live on T-12261
    # (2026-09-10, deviation ts=2026-09-10T09:38:58Z) — a later merge dropped the pass-3 RED record
    # from the branch tree, the archive still held the pass-2 GREEN one, and this reader answered
    # `{"keys": [], "unresolvable": False, "passes": 2}` FOR A RED ROW. That is the T-12311 «empty
    # residual set» shape, so SPEC-0204 rule 3 would have ADMITTED `--on-decisions` with ZERO
    # decisions recorded — the exact hole rule 7 («a verdict never reads GREEN with an undecided
    # residual») exists to close, reachable by an ordinary merge rather than by any misuse.
    #
    # TWO CHECKS, and a record failing EITHER is not this row's source — zero keys, UNRESOLVABLE,
    # `passes` left None. Note the placement: BEFORE the `passes` take below, so a rejected record
    # cannot leak its counter either (a `passes` from the wrong pass is the same lie in a number).
    #
    #   VERDICT — the record's `verdict` must equal the row's. This leg ALONE catches the T-12261
    #     incident and can never false-reject: both sides are recorded from the SAME parsed verdict.
    #   SUBJECT — audit-POST only: the record's `commit` (the full audited sha) must START WITH the
    #     row's `data.commit` (the short sha every post row carries — measured on every post row of
    #     T-12261 / T-12290 and the trial cards).
    #
    # `audited_at` IS NEVER COMPARED — not exactly, not with a tolerance. It is the obvious-looking
    # discriminator and it is the WRONG INSTRUMENT: the record's `audited_at` and the row's `ts` are
    # two INDEPENDENT clock reads ~440 lines apart in `cmd_audit`, so they straddle a second boundary
    # on ~9% of rows (10 of 113 pre-contract pairs measured on the live journal — the T-12319
    # pre-claim refusal, bg_dispatch_halted 2026-09-10T11:45:36Z). A guard keyed on it would read 9%
    # of legitimately-matching records as unresolvable, re-creating on legacy rows the very wall
    # T-12311 removed. The skew is structural, not a data accident.
    #
    # SILENCE IS NOT A CONTRADICTING SUBJECT, and that is why the subject leg is conditional on BOTH
    # sides carrying an identity. An audit-PRE row carries NO subject identity at all (neither
    # `commit` nor `plan_fingerprint` — measured on the T-12294 pre rows), and a record may carry no
    # `commit`; in either case the leg degrades to VERDICT-ONLY and the reason SAYS SO, rather than
    # rejecting a record that never claimed a different subject. This is the same doctrine the
    # T-12311 branch below already holds for an absent `findings` key — an ABSENT key is silence, and
    # silence is neither an assertion nor a denial. Fail-closed on CONTRADICTION; honest about
    # silence.
    _rec_verdict = str(rec.get("verdict") or "").strip().upper()
    _row_verdict = str(data.get("verdict") or "").strip().upper()
    _row_subject = str(data.get("commit") or "").strip()
    _rec_subject = str(rec.get("commit") or "").strip()
    _failed = []
    if not (_rec_verdict and _row_verdict and _rec_verdict == _row_verdict):
        _failed.append(f"verdict-mismatch(row={_row_verdict or 'absent'},"
                       f"record={_rec_verdict or 'absent'})")
    _subject_checked = bool(str(stage).strip().lower() == "post" and _row_subject and _rec_subject)
    if _subject_checked and not _rec_subject.startswith(_row_subject):
        _failed.append(f"subject-commit-mismatch(row={_row_subject},record={_rec_subject})")
    if _failed:
        # The reason names WHICH check failed AND what was checkABLE, so the caller's refusal can say
        # why the record was not admitted — «verdict-mismatch» alone would leave a reader unable to
        # tell a subject leg that PASSED from one that never ran.
        if not _subject_checked:
            _failed.append("subject-not-checked(verdict-only: no subject identity on the "
                           + ("row" if not _row_subject else "record") + ")")
        # T-12370 — THE ROLLED-BACK SUBJECT IS `stale`, NOT `unresolvable`. Conditions, ALL required
        # and each fail-closed on its own: the subject leg is the ONLY thing that failed (a
        # verdict-mismatch says the record belongs to a different PASS, which a rollback does not
        # explain); a reachability reader was INJECTED; and it answered an explicit `False` for the
        # ROW's own commit. A `None` («could not tell») keeps `unresolvable` — see the docstring for
        # why that direction is the safe one.
        if (callable(commit_reachable) and _row_subject
                and _failed == [f"subject-commit-mismatch(row={_row_subject},record={_rec_subject})"]):
            try:
                _reachable = commit_reachable(_row_subject)
            except Exception:      # noqa: BLE001 — a reader that raises told us nothing; stay closed
                _reachable = None
            if _reachable is False:
                return _out([], 0, False,
                            f"row-subject-rolled-back(row={_row_subject}, contained in no branch; "
                            f"the saved record is a different pass's {_rec_subject})",
                            stale=True)
        # ── A GREEN ROW ANSWERS FOR ITSELF WHEN THE RECORD THAT DISPLACED IT IS A CURRENCY PASS'S
        # (T-12422) ──────────────────────────────────────────────────────────────────────────────
        # The guard above is correct and stays: a record belonging to a DIFFERENT pass must not
        # answer for this row. But `decisions/<tid>-audit-<stage>.yaml` is ONE FILE PER (task,
        # stage), rewritten in place by every later run — INCLUDING an AUDIT-CURRENCY re-audit
        # (`--reaudit-after-close`), which by its own contract is NOT one of the card's passes at
        # all: it spends no pass, ranks below every counted row in `_ceiling_row_of`, and can never
        # end a (task, stage). So a currency check silently destroys the counted ceiling row's only
        # source of residuals and wedges the card on a set that was never in dispute.
        #
        # MEASURED on T-12340 (2026-09-11, worker halt ts=2026-09-11T18:28:17Z): the counted
        # on-decisions GREEN pass-3 row @ac78abb had its record clobbered by the 18:17Z currency RED
        # @fb1d270 (`reaudit_after_close: true` in the live record), this guard then refused it on
        # BOTH legs (verdict-mismatch GREEN/RED + subject-commit-mismatch), and the card could
        # neither decide, re-audit nor land.
        #
        # THE EXIT IS THE ROW'S OWN VERDICT, and only for GREEN: SPEC-0204 rule 7 makes «GREEN» and
        # «an undecided residual» mutually exclusive, so a GREEN row's residual set is EMPTY as a
        # property of the verdict — a fact the displaced record was never needed to supply.
        #
        # NARROW ON BOTH SIDES, and each bound is load-bearing:
        #   * THE ROW must be GREEN. A YELLOW may have findings listed and absorbed, and a RED or
        #     ABORT stating no findings is a MALFORMED record rather than an empty one — this floor
        #     does not get to reinterpret a blocking verdict as a clean one (the same bound the
        #     T-12311 branch below holds).
        #   * THE DISPLACING RECORD must be provably a CURRENCY pass's (`reaudit_after_close: true`,
        #     or `basis: currency`). Anything else — no record at all, a record stating no verdict, a
        #     record of THIS row's own pass that says RED — is NOT a currency overwrite and keeps
        #     today's `unresolvable` verbatim. Those three are exactly the states the T-12303 /
        #     T-12311 / T-12319 differentials pin, and none of them moves.
        if (_row_verdict == "GREEN"
                and (rec.get("reaudit_after_close") is True
                     or str(rec.get("basis") or "") == CURRENCY_BASIS)):
            return _out([], 0, False)
        return _out([], 0, True, "+".join(_failed))

    if passes is None:
        rec_passes = rec.get("passes")          # the record's EXPLICIT value, never _passes_recorded
        passes = int(rec_passes) if isinstance(rec_passes, int) else None
    saved = rec.get("findings")
    if not (isinstance(saved, list) and saved):
        # EMPTY vs UNRESOLVABLE — TWO DIFFERENT FACTS, and collapsing them closed every exit for a
        # done-but-unlanded card reworked in place (T-12311). A ceiling row that states no findings
        # and whose SAVED RECORD RESOLVES AND SAYS «this pass found nothing» has an EMPTY residual
        # set, not an unresolvable one: rule 3 admits its `--on-decisions` pass with zero decisions
        # («an all-accept/defer set with nothing new is GREEN with no code change» — an empty set is
        # the limit of that). Read UNRESOLVABLE, the same row instead hits
        # `on_decisions_admission`'s cause-(i) hard refusal, no auditor is invoked, and the card can
        # neither re-audit (over the ceiling), decide (nothing to decide), nor land (SPEC-0077 §3a
        # wants a fresh GREEN over the current tree). Measured live 2026-09-10 ~07:05Z on T-12303,
        # whose record carries `verdict: GREEN`, `passes: 3`, `findings: []`; T-12310 and T-12304 sat
        # behind the same wall.
        #
        # THE RECORD MUST RESOLVE ON THE RULE-1 FLOOR, and all three parts are load-bearing — this is
        # what keeps the branch from swallowing case (ii). `verdict` non-empty: a record stating no
        # verdict states nothing about what the pass found. `findings` PRESENT AND A LIST: an ABSENT
        # key is silence, and silence is not an assertion of emptiness — which is why the check is an
        # `isinstance(..., list)` over the RAW key (a missing key reads as None and fails it) and
        # never a truthiness test, which would read the two identically. And the verdict must be one
        # that CAN report nothing: GREEN says so positively, and a YELLOW whose findings list is empty
        # has every finding absorbed vacuously. A RED or ABORT carrying no findings is a MALFORMED
        # record, not an empty one — it stays UNRESOLVABLE, fail-closed, because this floor does not
        # get to reinterpret a blocking verdict as a clean one.
        #
        # `passes` is already resolved from this same `rec` above, so the empty branch still names
        # `pass-<N>` and the ceiling arithmetic is untouched. No second record or journal read is made
        # here — the fold's own `rec` is reused (SPEC-0190 rule 10).
        _verdict = rec.get("verdict")
        _resolves = (isinstance(_verdict, str) and _verdict.strip()
                     and isinstance(rec.get("findings"), list))
        if _resolves and str(_verdict).strip().upper() in ("GREEN", "YELLOW"):
            return _out([], 0, False)
        return _out([], 0, True, "record-states-no-empty-residual-set")
    keys, degraded, skipped = [], 0, 0
    for f in saved:
        # T-12402 — filtered at READ time, so a record saved before this filter existed unwedges too.
        # A list that is ALL non-defect resolves EMPTY (the record did state what the pass found).
        if is_non_defect_finding(f):
            skipped += 1
            continue
        k, deg = read_time_finding_key(task, stage, f if isinstance(f, dict) else {}, repo_root=repo_root)
        keys.append(k)
        degraded += 1 if deg else 0
    return _out(keys, degraded, False, non_defect_skipped=skipped)


def _red_cause_is_card_record(prior, tid: str, *, card=None, _zero_ship_diff_bookkeeping=None,
                              _card_named_task_tied_event_types=None, REPO_ROOT=None,
                              _criterion_named_test_paths=None, _RED_CAUSE_AC_RE, _RED_CAUSE_FIX_FIELD, _RED_CAUSE_REPRO_FIELD, _ac_named_verifier_paths, _card_declared_ac_ids, _fix_edit_fenced_invocation_paths, _fix_invocation_exempt_paths, _repo_path_tokens) -> bool:
    """T-12026 — is the RECORDED prior audit-post RED's cause the CARD'S OWN RECORD? THE ONE shared
    predicate, read by BOTH doors on the card-repair route (`task commit --fix-red --card-repair` in
    `bin/lib/task.py`, and `_card_repair_subject_admitted`'s conjunct (c) here), so the two cannot
    disagree about the same RED.

    WHAT THIS RETIRES, named per CHARTER §P1 filter 3. It REPLACES `_red_record_names_card_cause`
    (T-11991, widened by T-12018) — a KEYWORD TEST over free auditor prose: admission turned on
    whether the external auditor happened to write `tasks/<tid>*.yaml`, the word "card", or the
    phrase "recorded evidence". T-12018 shipped that widening and said so out loud, in its own
    comment: it "inherits the brittleness of a keyword test over free auditor prose, which is exactly
    the defect T-12026 exists to end". This is that end. The MEASURED cost of the keyword test is
    X-1251 (<project> T-0603): a pass-1 RED whose two findings named the task-tied `state_checked`
    PROBE EVENT the card's acceptance names — a corrected probe event is bookkeeping, no authored
    content — matched no keyword, so `task commit --fix-red --card-repair` ADMITTED the commit and
    directed the worker to `audit post --commit <new>`, which this conjunct then REFUSED. Two verbs
    on one governed route disagreeing is CHARTER §Principle 7 dissonance, not a phrasing problem, and
    a third keyword would only move the next miss one wording along.

    THE DERIVATION — read from the RECORD'S FACTS, in two parts, both of which must hold:

      (1) THE RECORD REFERENCES NO AUTHORED PATH. Every repo-path-shaped token in the record is
          classed lifecycle bookkeeping FOR THIS TID by the injected T-11991 allow-list
          (`_zero_ship_diff_bookkeeping` — the SAME list the arm's other conjuncts read, so there is
          no second definition of "what is a card record"). One authored path (`bin/lib/task.py:100`,
          or the EXTENSIONLESS `bin/yitc-v2#_emit_cli_invoked` — see `_repo_path_tokens` for why the
          lexer must reach it) refuses outright: a RED that locates its cause in the shipped diff is
          `--fix-red` PROPER's case, and a record-only subject over it would move custody onto a
          commit that fixes nothing. This half is what makes the predicate safe without any prose
          judgement at all.
          ONE CLASS of token is IGNORED here: a path the card's OWN acceptance names for an AC id
          the SAME FINDING cites as a coordinate for that value — either in the SAME recorded value
          (free prose), or in that finding's STRUCTURED `criterion_ref` field, which is a
          FINDING-LEVEL coordinate (T-12427) (`_ac_named_verifier_paths`). Two shapes of such a
          path, one rule: the criterion's VERIFIER LOCATOR (T-12056 — a RED that locates a
          criterion's cause writes the criterion AND its verifier, and reading the second as an
          authored defect path left an owner-directed AC amendment with no governed route at all,
          T-12030), and ANY repo-path token that criterion names VERBATIM (T-12433 — T-12406's AC3
          names the invocation `bin/yitc-v2 -C <consumer-repo> debt` and its pass-1 RED
          quoted that invocation back as the `failing_input` it was judging; `bin/yitc-v2` lexed as
          an authored path and refused a record whose part (2) was already satisfied, halting the
          card `blocked_on_land`). Either way it is SKIPPED, not admitted: it satisfies no strand of
          part (2), so the record must still name this card's own record by (i), (ii) or (iii) on
          its own merits.
          ONE VALUE of a finding is not read by this half at all: its `failing_input` (T-12616). The
          schema that asks for it defines it as «the concrete input/state that fails» — the input
          that REPRODUCES the defect, i.e. what you RUN to see it, never a claim about what the fix
          touches. The fields that DO make that claim — `where`, `locator`, `fix` — are read
          unchanged, and because the disqualification runs PER VALUE the fence is kept by
          construction: the same authored path written in any of them still refuses the record
          outright, including when `failing_input` names it too. Measured on <project> T-0582
          (X-1426, audit-post pass 2, fp1:9411d2937520c87d): `where` and `locator` both read the
          card's own `implementation_plan` step and `fix` said to rewrite it, but `failing_input`
          named the shell command that reproduced the defect — so this half refused, while
          `--fix-red` PROPER refused the same commit from the opposite side for carrying no authored
          content, leaving a true card-only fix at the 2-pass ceiling with no route at all.
          THE BOUND, stated exactly, because the nearby exemption's is DIFFERENT and conflating the
          two would claim more than this does. This is a relaxation of THIS half ONLY: part (2) is
          byte-unchanged and goes on reading EVERY value of the record, `failing_input` included,
          exactly as it did before this card. So a repro input that names this card's own record can
          satisfy strand (i) — as it always could whenever part (1) let the record through — and
          what this card changes is solely WHETHER part (1) refuses first. The guarantee that
          matters is the other direction, and it is kept by construction: a repro input can never
          RESCUE a record whose `where` / `locator` / `fix` claim authored code, because those
          values are still read, each on its own.
          ONE MORE SKIP, read from a finding's `fix` value ONLY (T-12693, successor of T-12672 —
          incident T-12663, fp1:4c4b69de4324ebcc / fp1:e061578a5028e325): a repo-path token tied
          to a QUOTED VERB INVOCATION (`_fix_invocation_exempt_paths`). `fix` is the schema's
          REMEDY field (the third coordinate read by name, `_RED_CAUSE_FIX_FIELD`), and the auditor
          writes «run this and record it» there — T-12663 finding 1 quoted `bin/yitc-v2 task test
          --run` with no criterion_ref, finding 2 quoted the cited AC3 probe `bin/yitc-v2 debt` and
          then the card's OWN `expected_touch` subject file as its object; both lexed as authored
          paths, so every commit door refused and the auditor's GREEN could not be banked
          (T-10318). The skip has three arms: (a) the invocation's own path token; (b-ARG) a
          card-subject token inside the SAME quoted span as an invocation the CITED criterion
          names verbatim (already in `named`); (b-CTX) a card-subject token in a LATER quoted span
          of that value, ONLY under `_subject_follows_cited_probe`'s context proof — no path and
          no edit-verb stem between the spans, the subject the immediate object of a fixed
          preposition, and the finding's `locator` naming this card's own path AT the cited AC id.
          T-12672's ordering-only following arm was refused at audit-pre terminal RED
          (fp1:1eab54a24173413c) for admitting «… then edit `<subject>` …»; that shape now
          refuses. Subjects come from the STRUCTURED `expected_touch` only, never scope prose
          (audit-pre pass 1 of T-12693, fp1:d59b403d280c0e2f). With no invocation in the value
          nothing is skipped; unquoted, before-the-anchor and un-cited-invocation subjects refuse
          as before; `where` / `locator` / `what` are read unchanged. SKIPPED, never admitted —
          it satisfies no strand of part (2).

      (2) THE RECORD REFERENCES AT LEAST ONE THING THAT IS THIS CARD'S OWN RECORD, by any of three
          strands — each derived from an artifact the AUDITOR does not author:
            (i)   a path the allow-list classes as this card's OWN record (its `tasks/<tid>*.yaml`
                  card or its own `decisions/<tid>-*.yaml`). Bare `events.jsonl` is deliberately NOT
                  a strand: the journal FILE is where every card's records live, so naming it
                  identifies no card. It is still bookkeeping for part (1), so naming it never
                  refuses either.
            (ii)  an event TYPE that THIS CARD'S OWN acceptance NAMES and for which a task_id-tied
                  row exists — the T-10708 card-opt-in CONJUNCTION, reused whole rather than
                  re-invented (CHARTER §P1 F1). This is the X-1251 shape: the card's acceptance names
                  its probe, the RED says that probe event is wrong, the fix is a corrected event.
            (iii) an acceptance-criterion id (`AC<N>`) that THIS CARD ACTUALLY DECLARES. This is the
                  T-12018 DECLARING shape ("AC3's recorded evidence still shows `sandbox_entry:
                  waived`"), whose cause is located at a criterion of the card's own acceptance and
                  nowhere in the tree — derived here from the card's own acceptance list instead of
                  from the auditor's noun. T-12018's route is thereby PRESERVED, on a derivation
                  rather than on the phrase it had to match.

    Why part (2) needs three strands and not one: "the card's own record" is a thing a RED can point
    at in three genuinely different ways — by the FILE, by the EVENT the card nominated as its probe,
    or by the CRITERION whose recorded reading is stale. Each is read off the card or the allow-list;
    none is read off the auditor's vocabulary. Adding a fourth would need a fourth measured shape.
    T-12926 measured it — (iv), the FIELD: see `_finding_locates_card_field`.

    Pure predicate over its inputs. FAIL-CLOSED on absence, on a missing injection, on a non-RED or
    unreadable verdict, and on malformed input; never raises — a discriminator that cannot verify
    must not grant."""
    try:
        if not isinstance(prior, dict) or str(prior.get("verdict") or "").strip().upper() != "RED":
            return False
        if not callable(_zero_ship_diff_bookkeeping):
            return False          # a plumbing failure must never open a carve-out
        # EVERY recorded value of every finding, plus `finding_class`. Reading ALL of them IS the
        # "structured fields where present" read — a finding's structured locator (`where`, `path`,
        # `file`, whatever this auditor emitted) is one of these values, and taking them all means
        # this predicate needs no per-auditor KEY vocabulary, which would just be the retired keyword
        # test moved from the values to the keys.
        # GROUPED BY FINDING as well as flattened (T-12427): part (1)'s verifier-locator exemption
        # pairs the STRUCTURED `criterion_ref` coordinate across the whole FINDING, so it needs to
        # know which values came from the same finding. `blob` itself is byte-unchanged in content
        # and order — parts (1) and (2) read exactly the same values as before.
        blob = []
        # (AC ids the finding's structured `criterion_ref` names, its values, the INDICES of those
        # values that came from the `failing_input` key — T-12616). Indices, not the value STRINGS:
        # a finding whose `locator` and `failing_input` happen to carry the identical text must have
        # the locator checked, and a membership test on the string would skip both.
        groups = []
        for f in (prior.get("findings") or []):
            if isinstance(f, dict):
                items = list(f.items())
                vals = [str(v) for _k, v in items]      # byte-identical to `f.values()`, in order
                # the TWO structured fields SPEC-0036's saved-record schema itself provides; no other
                # key is read, so these stay schema coordinates and not a key vocabulary.
                carried = {m.group(1).lstrip("0") or "0"
                           for m in _RED_CAUSE_AC_RE.finditer(str(f.get("criterion_ref") or ""))}
                repro = {i for i, (k, _v) in enumerate(items)
                         if _RED_CAUSE_REPRO_FIELD is not None and k == _RED_CAUSE_REPRO_FIELD}
                # T-12693 — the indices of the values that came from the `fix` key (the THIRD
                # schema coordinate), and the finding itself so the skip can read the LOCATING
                # coordinates for its condition (iii). Indices, not strings, for the T-12616 reason.
                fixidx = {i for i, (k, _v) in enumerate(items)
                          if _RED_CAUSE_FIX_FIELD is not None and k == _RED_CAUSE_FIX_FIELD}
                fnd = f
            else:
                # a free-form finding has no keys at all, so it has no repro coordinate either — its
                # one value is checked in full, exactly as before.
                vals, carried, repro, fixidx, fnd = [str(f)], set(), set(), set(), {}
            blob.extend(vals)
            groups.append((carried, vals, repro, fixidx, fnd))
        fclass = str(prior.get("finding_class") or "")
        blob.append(fclass)
        groups.append((set(), [fclass], set(), set(), {}))
        text = "\n".join(blob)
        if not text.strip():
            return False          # a RED with no findings refers to nothing

        # ── part (1) — no AUTHORED reference anywhere in the record ───────────────────────────────
        # ONE exemption: a repo path the card's OWN acceptance names for an AC id THIS RECORD CITES
        # is neither authored-defect evidence nor bookkeeping. Two shapes, one rule — the criterion's
        # VERIFIER LOCATOR, where the RED says to LOOK (T-12056), and a token that criterion names
        # VERBATIM, which is the card's own text the RED is quoting back (T-12433, measured on
        # T-12406's AC3-named `bin/yitc-v2 -C <repo> debt`). Ignoring it is what makes the exemption
        # narrow: it is skipped, never admitted, so it can satisfy no strand of part (2).
        # PAIRING SCOPE, and it is DIFFERENT for the two ways a record can cite an AC id (T-12427):
        #   · the STRUCTURED `criterion_ref` field is a FINDING-LEVEL coordinate — it applies to
        #     EVERY value of ITS OWN finding. SPEC-0036's saved-record schema provides that field, so
        #     an auditor using it as intended SPLITS the two coordinates across values of one
        #     finding: `{criterion_ref: AC2, fix: "… tests/test_x.py …"}` (measured on T-12420's
        #     pass-1 RED, which a per-value pairing refused although the record was well-formed).
        #   · a FREE-PROSE AC id stays PER VALUE, exactly as T-12056 shipped it. That bound is the
        #     reason the exemption is still narrow, and it is deliberate: a `fix:` that merely SAYS
        #     "amend AC1" must NOT exempt AC1's verifier cited in some other value — the "cited
        #     beside a DIFFERENT AC id" case, pinned by the wrong-AC differential. The structured
        #     carry does not launder a free-prose id: they are unioned only INTO each value's own set.
        # NEVER ACROSS THE RECORD either way: a path in finding B is not exempted by finding A's
        # criterion_ref, and the path must still be the verifier the CITED criterion NAMES.
        # The DISQUALIFICATION ITSELF still runs per value, so the pairing survives it: a path exempt
        # in a value whose set names its criterion is NOT exempt in a value of ANOTHER finding that
        # cites it unpaired. Deciding the skip on a UNION of exempt paths over the whole record would
        # let one correctly-paired citation license every other occurrence in it.
        for carried, values, repro, fixidx, fnd in groups:
            for idx, value in enumerate(values):
                if idx in repro:
                    # T-12616 — the finding's `failing_input`. The schema defines this value as the
                    # INPUT that REPRODUCES the defect, so a path in it is what you RUN, never where
                    # the fix lands. Skipping it is PER VALUE, which is what keeps the fence intact:
                    # the same path written in `where`, `locator` or `fix` is still checked in ITS
                    # own value and still refuses the record outright. Measured on <project> T-0582
                    # (X-1426, audit-post pass 2, fp1:9411d2937520c87d): `where` AND `locator` both
                    # read the card's own `implementation_plan` and `fix` said to rewrite it, but
                    # `failing_input` named the command that reproduced the defect — so part (1)
                    # refused, `--fix-red` proper refused the same commit for carrying no authored
                    # content, and one true card-only fix at the 2-pass ceiling had no route at all.
                    continue
                acs = carried | {m.group(1).lstrip("0") or "0"
                                 for m in _RED_CAUSE_AC_RE.finditer(value)}
                named = (_ac_named_verifier_paths(card, acs, _criterion_named_test_paths,
                                                  REPO_ROOT=REPO_ROOT)
                         if acs else set())
                # T-12693 — a `fix` value ALSO skips the tokens tied to a quoted verb invocation
                # (`_fix_invocation_exempt_paths`: the invocation's own path, and the card's own
                # `expected_touch` subject as that cited probe's ARGUMENT or proven OBJECT). Every
                # other value keeps `exempt = named` exactly as before, so a subject token in
                # `where` / `locator` / `what` still refuses outright.
                exempt = named
                if idx in fixidx:
                    # an invocation the clause names as an EDIT TARGET is fenced out of EVERY
                    # exemption of this value — `named` included — before the skip is unioned in
                    fenced = _fix_edit_fenced_invocation_paths(value, REPO_ROOT)
                    exempt = (named - fenced) | _fix_invocation_exempt_paths(
                        value, card, named - fenced, tid, fnd, acs, REPO_ROOT=REPO_ROOT)
                for pth in _repo_path_tokens(value, REPO_ROOT):
                    if pth not in exempt and not _zero_ship_diff_bookkeeping(pth, tid):
                        return False
        cited_acs = {m.group(1).lstrip("0") or "0" for m in _RED_CAUSE_AC_RE.finditer(text)}
        paths = _repo_path_tokens(text, REPO_ROOT)

        # ── part (2) — at least one reference that IS this card's own record ──────────────────────
        # (i) the card / its own audit records, by path.
        if any(pth != "events.jsonl" and _zero_ship_diff_bookkeeping(pth, tid) for pth in paths):
            return True
        # (ii) a task-tied event type the CARD's own acceptance names (the T-10708 conjunction).
        if callable(_card_named_task_tied_event_types):
            for etype in (_card_named_task_tied_event_types(card) or ()):
                et = str(etype or "").strip()
                if et and re.search(rf"\b{re.escape(et)}\b", text):
                    return True
        # (iii) an acceptance-criterion id THIS CARD declares.
        declared = _card_declared_ac_ids(card)
        if declared and cited_acs & declared:
            return True
        # (iv) T-12926 — a finding's LOCATING coordinate names a text FIELD this card declares.
        if _finding_locates_card_field(groups, card, _RED_CAUSE_AC_RE):
            return True
        return False
    except Exception:      # noqa: BLE001 — an unprovable admission is simply not granted
        return False


#: T-12926 — the card TEXT fields a fidelity finding can locate its cause in. Closed and read off the
#: card's own schema (SPEC-0028), never off the auditor's vocabulary: a field counts only when THIS
#: card declares it non-empty.
_CARD_TEXT_FIELDS = ("implementation_plan", "acceptance", "scope", "analysis")

#: T-12926 — the two STRUCTURED locating coordinates of SPEC-0036's saved-record schema. `what` /
#: `fix` / `failing_input` are deliberately NOT read: they describe or remedy, they do not locate.
_CARD_FIELD_LOCATING_KEYS = ("where", "locator")


def _finding_locates_card_field(groups, card, ac_re=None) -> bool:
    """T-12926 — part (2) strand (iv) of `_red_cause_is_card_record`: does a finding's `where` or
    `locator` name a text field THIS card declares — «Implementation plan step 2», `acceptance`?

    THE MEASURED SHAPE (T-12826, audit-post pass 2, fp1:9049017f4b6c3c44): a PLAN-TEXT fidelity
    finding located at «Implementation plan step 2 / Adoption evidence». Its only fix is a card-field
    amendment, yet no strand fired — it names no card PATH (i), no acceptance-named event (ii) and no
    AC id (iii) — so it was not «the card's own record» and the ceiling had no governed exit short of
    an owner `accept`. <project> X-1426 was the same shape (`where` + `locator` read the card's own
    `implementation_plan`). A fourth way a RED points at the card's record: by the FIELD.

    Read from the card, not the auditor: the field must be one this card DECLARES non-empty, and only
    the two structured locating keys are read, whole-word, `_` or space spelled. Part (1) is untouched
    and still runs first, so an authored path in ANY value refuses the record before this is asked.
    A locating value that cites an AC id (`ac_re`) is SKIPPED here: strand (iii) owns it, so
    «acceptance criterion AC3» against a card that never declared AC3 stays refused.
    Pure; never raises; False on a missing card."""
    try:
        if not isinstance(card, dict):
            return False
        fields = [f for f in _CARD_TEXT_FIELDS if card.get(f) not in (None, "", [], {})]
        if not fields:
            return False
        pats = [re.compile(r"(?<![A-Za-z0-9_])" + re.escape(f).replace("_", "[_ ]") + r"(?![A-Za-z0-9_])",
                           re.IGNORECASE) for f in fields]
        for _carried, _vals, _repro, _fixidx, fnd in groups:
            if not isinstance(fnd, dict):
                continue
            for key in _CARD_FIELD_LOCATING_KEYS:
                val = str(fnd.get(key) or "")
                if not val or (ac_re is not None and ac_re.search(val)):
                    continue
                if any(p.search(val) for p in pats):
                    return True
        return False
    except Exception:      # noqa: BLE001 — an unprovable admission is simply not granted
        return False


def _ac_named_verifier_paths(card, cited_acs, _criterion_named_test_paths=None,
                             REPO_ROOT=None, *, _repo_path_tokens) -> set:
    """T-12056 — the repo paths this card's OWN acceptance names for the AC ids a RED record
    CITES. The exempting half of `_red_cause_is_card_record` part (1). TWO sources, ONE criterion:
    the SPEC-0060 item-4 VERIFIER cue (T-12056), and every repo-path token that criterion's text
    carries VERBATIM (T-12433). Both are read off the SAME acceptance entry, selected the SAME way.

    THE DEFECT IT CLOSES (2026-09-04, T-12030). A card's acceptance names its verifier through the
    SPEC-0060 item-4 test-or-waive cue (`(test: tests/test_x.py section D)`). When the RED locates a
    criterion's cause it writes BOTH coordinates — `tasks/<tid>-….yaml:acceptance AC1;
    tests/test_x.py:D2` — because that is where the reader must look. Part (1) read the second
    coordinate as an AUTHORED path and refused the record outright, so an owner-directed AC amendment
    on an unlanded card had NO governed custody route left at all: `--repin-ship` needs the ship on
    main, `audit post --commit <bookkeeping sha>` is stopped by T-11405, and `task commit --fix-red
    --card-repair` — the arm built for exactly this case — refused here. The same fork PASSED on
    T-12029 and T-12031 only because their RED records happened to cite no test path.

    WHY THIS IS NOT A HOLE IN PART (1), which is the whole safety of the predicate. The exemption is
    tied to TWO things the auditor does not author, BOTH required: the AC id must be cited as a
    COORDINATE FOR THAT VALUE — in the SAME recorded value, which is how an auditor writes a locator
    in prose (`where: <card>:acceptance AC1; <test>:D2`), or in the finding's STRUCTURED
    `criterion_ref` field, which SPEC-0036's saved-record schema provides and which therefore reads
    as a coordinate for EVERY value of THAT finding (T-12427: an auditor using it writes
    `{criterion_ref: AC2, fix: "… tests/test_x.py …"}`, splitting the two coordinates across values
    of one finding — measured on T-12420, where a per-value pairing refused a well-formed record).
    A free-prose AC id stays PER VALUE, so the structured carry launders nothing: an "amend AC1" in
    one value still exempts no verifier cited in another, and a criterion_ref never reaches ANOTHER
    finding's values. And the path must be the verifier THAT criterion NAMES. So a source path under
    `bin/lib/` still refuses (no criterion names it), a test named by NO criterion still refuses, a
    bare directory still refuses, and the card's own verifier cited beside a DIFFERENT AC id than the
    one naming it still refuses — the record must point at the criterion whose verifier it locates.
    A card cannot widen its own admission by naming more tests, because a test it names buys nothing
    until a RED cites that criterion's id.

    THE SECOND SOURCE, AND THE SECOND MEASURED INCIDENT (2026-09-12, T-12406). The T-12013 reader
    above recognizes TEST paths — that is what it is for — so a NON-test path a criterion names is
    invisible to it. T-12406's AC3 names an INVOCATION — `bin/yitc-v2 -C <consumer-repo> debt`, the
    host path abstracted here per SPEC-0195 rule 1a, since this file is published engine code — and
    its pass-1 RED quoted that invocation back in `failing_input` as the input it was judging. `_repo_path_tokens` lexes `bin/yitc-v2` (extensionless, and `bin` exists at REPO_ROOT —
    see that lexer for why it must reach the corpus's most-authored path), part (1) found it neither
    exempt nor on the bookkeeping allow-list, and refused a record whose part (2) was already
    satisfied by the card path. That left T-12406 halted `blocked_on_land` with no governed custody
    route — the SAME dead end T-12056 closed, reached through a path shape rather than a lexing one
    (deviation fingerprint `card-repair-refused-by-ac-named-cli-invocation-token`). So a repo-path
    token the CITED criterion names VERBATIM is exempt too, read through the EXISTING
    `_repo_path_tokens` lexer so no second path vocabulary is born.

    THE WIDENING KEEPS EVERY BOUND ABOVE, because it moves only WHICH tokens one criterion yields —
    never WHICH criterion is read, nor how the record must cite it. The path must still appear in
    the acceptance text of a criterion the record cites as a coordinate for that value. So
    `bin/lib/debt.py` beside that same citation still refuses (AC3 names it nowhere), the same
    invocation cited beside AC1 still refuses (AC1 names it nowhere), and a token the card carries
    only in `scope` / `title` / `analysis` still refuses — ONLY `acceptance` entries are read. A card
    still cannot widen its own admission by naming more paths: a path it names buys nothing until a
    RED cites THAT criterion's id.

    POLARITY — the root check lives HERE, on the granting side, and it is the OPPOSITE of the
    lexer's. `_repo_path_tokens` treats an unresolvable REPO_ROOT as STRICT (every slash token counts
    as a path) because its part-(1) caller REFUSES on what it returns, so an unanswerable lexer must
    push toward refusal. This helper GRANTS, so the identical input must fail the other way: an
    absent or unreadable `REPO_ROOT` yields NO exemption from this strand, which is the same
    fail-closed rule the paragraph below already states for every other unprovable input. The lexer
    itself is byte-unchanged; only the caller that reads it differs in what unknown means.

    Recognition is NOT a second vocabulary: `_criterion_named_test_paths` is the injected host reader
    over the ONE T-12013 recognizer (`task.criterion_names_test` + `task.declared_test_globs`,
    SPEC-0185 §5 / SPEC-0160 rule 10), so a project declaring where its test files live is read by its
    own declaration here exactly as it is everywhere else.

    Pure f(card, cited_acs, injected reader). `set()` — i.e. NO exemption, the pre-T-12056 refusal —
    on an absent/malformed card, no cited AC ids, a missing injection, or a raising reader: this
    helper GRANTS, so every unprovable input must fail closed."""
    if not isinstance(card, dict) or not cited_acs or not callable(_criterion_named_test_paths):
        return set()
    acc = card.get("acceptance") or []
    if isinstance(acc, str):
        acc = [acc]
    # T-12433 — the granting-side root check (see POLARITY above). An unresolvable REPO_ROOT grants
    # NO verbatim-token exemption; the T-12056 verifier strand is unaffected, it needs no root.
    root_readable = False
    try:
        if REPO_ROOT is not None:
            from pathlib import Path as _P
            root_readable = _P(str(REPO_ROOT)).is_dir()
    except Exception:      # noqa: BLE001 — an unreadable root simply grants nothing here
        root_readable = False
    out: set = set()
    for entry in acc:
        text = str(entry)
        m = _ACCEPTANCE_AC_RE.match(text)      # the SAME anchored declaration reading strand (iii)
        if not m:                              # uses — a bare `AC7` mid-prose declares nothing
            continue
        if (m.group(1).lstrip("0") or "0") not in cited_acs:
            continue
        try:
            for pth in (_criterion_named_test_paths(text) or ()):
                tok = str(pth or "").strip()
                if tok:
                    out.add(tok)
        except Exception:      # noqa: BLE001 — a reader that cannot answer grants no exemption
            return set()
        if root_readable:
            # T-12433 — the SAME criterion's verbatim repo-path tokens, through the SAME lexer part
            # (1) uses on the record. One vocabulary, read on both sides of the comparison.
            out |= _repo_path_tokens(text, REPO_ROOT)
    return out


def _accept_reason_quotes_directive(reason, directive_text) -> bool:
    """Rule 2: an `accept` reason MUST QUOTE the authorizing words — a «…» or "…" span present
    VERBATIM in the resolved directive's text.

    Fail-closed twice over: a reason with NO quoted span at all cannot satisfy it (an unquoted
    paraphrase is exactly what the rule refuses), and a span that is not found VERBATIM in the
    directive cannot either.

    VERBATIM IS LITERAL — no normalization of any kind (audit-post finding 3). An earlier shape
    collapsed whitespace on both sides so a line wrap in the journal's stored prose would not defeat
    a quote; but that also admitted a span that differs from the directive by its INTERNAL spacing,
    which is not the same words as stored and is exactly the latitude rule 2 refuses on a TERMINAL
    disposition. The Controller quotes the span AS THE ROW STORES IT; a wrapped span is quoted as
    wrapped. Pure."""
    if not isinstance(reason, str) or not isinstance(directive_text, str) or not directive_text.strip():
        return False
    for m in _ACCEPT_QUOTE_RE.finditer(reason):
        span = next((g for g in m.groups() if g), "")
        if span and str(span) in directive_text:
            return True
    return False


def _currency_finding_index(stage_rows, tid, stage, *, repo_root=None, CURRENCY_BASIS, finding_key_of) -> dict:
    """T-12422 (SPEC-0204 rule 3) — `{fingerprint: ts}` over the `findings[]` recorded on the
    (task, stage) rows whose `basis` is `CURRENCY_BASIS`: THE DECIDABLE FINDINGS OF AN
    AUDIT-CURRENCY CHECK.

    The structural SIBLING of `_late_finding_index` above — same shape, same pure-f(rows) posture,
    same `finding_key_of` keying, so this side and `audit decide` key a finding IDENTICALLY by
    construction rather than by two loops agreeing (CHARTER §P5). It exists because a currency row's
    findings were decidable by NOBODY: a currency check is not one of the card's counted passes, so
    its findings are not residuals of the ceiling row; and the auditor declares no `causality` on
    them, so they are not rule-8 late findings either. Measured on T-12340 (2026-09-11): the 18:17Z
    currency RED raised fp1:d7f6ecd9bf336982, an identical-cause re-raise of a residual the OWNER had
    already accepted, and `audit decide` refused it `fingerprint_not_a_residual` (residual_count=0,
    late_count=1) — a finding no verb in the system could dispose of.

    IT MAKES THE FINDING DECIDABLE BY THE AUTHORITY, NOT AUTOMATICALLY FORGIVEN. Nothing here
    matches causes or infers that a re-raise is «the same» finding under a new fingerprint; that
    would be the one direction rule 3 forbids («never silently overruled»). The Controller records
    an explicit typed `ceiling_decision` on it, which is strictly more governance, not less.

    A fingerprint the row itself already lists in `overruled_by_decision` is EXCLUDED: a decision
    settled it, so offering it again as decidable would invite a duplicate `audit decide` refuses.
    The VALUE is the row's `ts` — provenance for the refusal text, read by nothing for a decision.

    Pure f(rows); opens no journal; never raises."""
    out = {}
    for row in stage_rows or ():
        data = row.get("data") if isinstance(row.get("data"), dict) else {}
        if str(data.get("basis") or "") != CURRENCY_BASIS:
            continue
        found = data.get("findings")
        if not isinstance(found, list):
            continue
        settled = {f for f in (data.get("overruled_by_decision") or ()) if isinstance(f, str)}
        for f in found:
            key = finding_key_of(tid, stage, f if isinstance(f, dict) else {}, repo_root=repo_root)
            if key in settled:
                continue
            out[key] = row.get("ts")
    return out


def _directive_covers_task(row, tid, *, plan_slug=None, _directive_row_text, _prose_names_token) -> bool:
    """Rule 2's COVERS THE TASK test: the directive «names it, or names a plan/batch the task is cut
    from».

    Three admitting shapes, and no fourth:
      * the task id is listed in `data.cards` (the BATCH shape — a directive over a card set);
      * the task id appears as a whole token in the row's prose (the NAMES-IT shape);
      * the plan the card is `decomposed_from` appears in `data.cards` or in the prose (the PLAN
        shape). `decomposed_from` ONLY — a card that merely `cites` the plan is NOT cut from it, and
        AC3 pins exactly that difference. Passing `plan_slug=None` therefore disables this arm
        rather than widening it.

    EVERY arm is TOKEN-EXACT, none is a substring test. The two list arms are exact-element
    membership by construction; both prose arms go through `_prose_names_token`, so a directive
    naming `plan-foobar` never covers a card cut from `plan-foo`, and one naming `T-12287` never
    covers `T-1228`. Pure; never raises."""
    data = row.get("data") if isinstance(row, dict) and isinstance(row.get("data"), dict) else {}
    cards = [str(c) for c in (data.get("cards") or []) if isinstance(data.get("cards"), list)]
    if tid in cards:
        return True
    text = _directive_row_text(row)
    if _prose_names_token(text, tid):
        return True
    if plan_slug:
        if str(plan_slug) in cards or _prose_names_token(text, plan_slug):
            return True
    return False


def _directive_row_text(row) -> str:
    """The PROSE of an `owner_directive` row — the surface both the coverage test and the `accept`
    quote test read. Three carriers exist on disk and all are authored text: `data.text` (the owner's
    verbatim input, as the session-log adapter materializes it), `data.directive` (a structured
    Controller-authored directive) and `data.owner_text` (the owner's COMPLETE message on a T-12801
    mid-turn row, proven against the transcript entry at the write). Joined, never chosen between — a
    row may carry any of them. T-12911 (<project> X-1567): without `owner_text` a mid-turn row whose
    only prose is the owner's words read as EMPTY, so every `accept` quoting them was refused."""
    data = row.get("data") if isinstance(row, dict) and isinstance(row.get("data"), dict) else {}
    return "\n".join(str(data.get(k)) for k in ("text", "directive", "owner_text")
                     if isinstance(data.get(k), str))


def residual_finding_records(stage_rows, keys, tid, stage, *, repo_root=None, finding_key_of) -> dict:
    """T-13169 (SPEC-0204 rule 3) — `{fingerprint: recorded finding entry}` for the residual `keys`,
    read off the `findings[]` + `late_findings[]` of the (task, stage) rows.

    What it is FOR: the rule-3 packet listed each decided residual by fingerprint alone, so the
    auditor was asked to keep a prior finding's fields «EXACTLY as recorded» without being shown
    them. On <project> T-0752 (X-1549) it re-raised both deferred residuals at the same criterion and
    locator with the `failing_input` re-worded — new keys, NEW, RED. The engine cannot tell a
    re-wording from a new defect (rule 1/3 forbid text similarity), so the discriminator is the
    auditor's own `echo_of`, made with the record in view; this reader supplies the record.

    Keying is `finding_key_of`, the SAME the residual readers use (`_late_finding_index`,
    `_currency_finding_index`), so an entry is found under exactly the key the residual set holds. The
    first occurrence wins (the ceiling row precedes later rows in fold order). Pure f(rows); opens no
    journal; never raises."""
    want = set(keys or ())
    out: dict = {}
    if not want:
        return out
    try:
        for row in stage_rows or ():
            data = row.get("data") if isinstance(row, dict) and isinstance(row.get("data"), dict) else {}
            for e in list(data.get("findings") or ()) + list(data.get("late_findings") or ()):
                if not isinstance(e, dict):
                    continue
                k = finding_key_of(tid, stage, e, repo_root=repo_root)
                if k in want and k not in out:
                    out[k] = e
    except Exception:   # noqa: BLE001 — a missing record degrades to «no recorded finding», never a crash
        return out
    return out


def _late_finding_index(stage_rows, tid, stage, *, repo_root=None, finding_key_of) -> dict:
    """`{fingerprint: basis}` over the `late_findings[]` recorded on the (task, stage) rows.

    Rule 8 records a NEW finding the auditor could have raised on an earlier pass as a `late_finding`
    rather than a verdict driver, and rule 2 admits a decision on one «at any pass». C4 is what
    WRITES them — this card only READS them if present, so an absent key is the ordinary case and
    yields `{}`.

    The VALUE is the `basis` of the row the late finding SITS ON, because that is the only thing AC4
    needs it for: a late finding recorded ON the rule-3 pass (`basis: on-decisions`) admits `accept`
    or `defer` only — there is no further audit pass in which a `fix` could ever be verified.

    EVERY (task, stage) ROW IS SCANNED, INCLUDING THE CURRENT CEILING ROW — deliberately, and the
    implementation plan's looser phrase «`late_findings[]` of EARLIER rows» is the imprecision, not
    this (audit-post finding 4, rejected with this reason rather than absorbed). Rule 8: «a late
    finding recorded ON the rule-3 pass admits `accept` or `defer` only», and rule 3 makes that pass
    TERMINAL for the (task, stage) — no later row can exist at that stage. So restricting the scan to
    `stage_rows[:-1]` would make the `late-finding-no-further-pass` refusal AC2 pins UNREACHABLE in
    any real journal, and would leave a late finding recorded on the terminal pass undecidable while
    rule 8 requires every late finding to be decided before Closure. Pinned by
    ::test_refuses_late_finding_no_further_pass, whose fixture is exactly that shape.

    Keying REUSES C1: an entry that already carries an engine `finding_fingerprint` is taken
    VERBATIM (never recomputed — the same rule the row-level read path holds), and one that does not
    is keyed through `read_time_finding_key`, which decides the canonical-vs-degraded key itself.
    Pure; never raises."""
    out = {}
    for row in stage_rows or ():
        data = row.get("data") if isinstance(row.get("data"), dict) else {}
        late = data.get("late_findings")
        if not isinstance(late, list):
            continue
        basis = data.get("basis")
        for f in late:
            out[finding_key_of(tid, stage, f, repo_root=repo_root)] = basis
    return out


def _prose_names_token(text, token) -> bool:
    """Does `text` name `token` as a WHOLE token — bounded on BOTH sides by a non-slug character or
    the string edge?

    The ONE place the coverage test's prose arms match, so neither can drift into the substring
    reading the other refuses. A slug character is `[A-Za-z0-9_-]`: task ids and plan slugs are drawn
    from exactly that alphabet, so a boundary is anything outside it.

    Substring matching FAILS OPEN on an authority boundary, which is why this is a regex and not an
    `in` (audit-post consult B1, episode T-12287/post/2): prose naming `plan-foobar` would otherwise
    authorize a card cut from `plan-foo`, and prose naming `T-12287` would authorize a decision on
    `T-1228`. Pure; never raises."""
    return bool(re.search(r"(?<![A-Za-z0-9_-])" + re.escape(str(token)) + r"(?![A-Za-z0-9_-])",
                          str(text)))


def _repo_path_tokens(text: str, REPO_ROOT=None) -> set:
    """T-12026 — the slash-joined tokens in `text` that are REPO PATHS, with their `#symbol` /
    `:line` locators stripped. The lexing half of `_red_cause_is_card_record` part (1); it decides
    only WHICH tokens are paths, never whether a path is authored (that is the injected allow-list's
    call, and keeping the two apart is what stops this becoming a second vocabulary).

    A dot-extension is SUFFICIENT but not NECESSARY (`bin/yitc-v2`). For an extensionless token the
    test is DERIVED FROM THE REPO, not from a list of directory names: its first segment must name an
    entry that actually EXISTS at `REPO_ROOT`. That is what keeps ordinary auditor prose out —
    `GREEN/YELLOW`, `pre/post`, `and/or` are slash-joined but name no repo entry, and admitting them
    as authored paths would refuse legitimate card-record REDs on a slash in a sentence.

    UNKNOWN IS STRICT, and the direction is deliberate: when `REPO_ROOT` is absent or unreadable,
    EVERY slash token counts as a path. The caller GRANTS an exception, so a lexer that cannot answer
    must push it toward refusal — the opposite polarity to the T-11405 guard a few functions up,
    which only ever REFUSES and so proceeds on unknown (`lessons/carving-an-exception-into-a-
    fail-closed-gate` §1).

    TRAILING SENTENCE PUNCTUATION IS STRIPPED after the locator strip (T-12430), because a path
    written at the END OF A SENTENCE is the same path. `.` is IN `_RED_CAUSE_PATH_RE`'s char class,
    so T-12420's verbatim pass-1 RED — `… does not name or report
    tests/test_land_tail_write_withheld.py.` — lexed as `…withheld.py.`, which matched no verifier
    its card names and is not bookkeeping, so part (1) refused a well-formed card-record RED and left
    that card with no governed custody route (measured 2026-09-12, deviation fingerprint
    `t12420-verifier-locator-refused-by-sentence-final-period-lexing`). The strip is TRAILING-ONLY
    and repeat-safe, so an interior dot (`x.py.bak`) and a `#symbol` / `:line` locator are untouched.
    HONEST BOUND on the closed set `.,;:)"\'`: only `.` is actually REACHABLE here — the others are
    not in the path char class, so a match can never end in one (and `:` could not survive the
    locator strip anyway). They are stripped for uniformity, not because this lexer can meet them;
    the outcome for those characters was already correct before this change.

    A LOCATOR REMAINDER IS NEVER A SECOND PATH (T-13443, GitHub #20). `:` and `#` are NOT in the path
    char class, so `tasks/T-X.yaml:implementation_plan.step7/probe_moments.AC4` lexed as TWO matches,
    and the field-path half (a dot in its last segment) read as an authored path — part (1) then
    refused a RED whose only cause was the card record. A match that starts right after a `:` / `#`
    which itself sits exactly where the PREVIOUS match ended is the rest of that one `path:locator`
    word, so it is skipped. A path after `: ` (with a space) or after prose is untouched."""
    root = None
    try:
        if REPO_ROOT is not None:
            from pathlib import Path as _P
            cand = _P(str(REPO_ROOT))
            root = cand if cand.is_dir() else None
    except Exception:      # noqa: BLE001 — an unreadable root just means the strict branch
        root = None
    out = set()
    text = text or ""
    prev_end = -1
    for m in _RED_CAUSE_PATH_RE.finditer(text):
        glued = m.start() >= 1 and text[m.start() - 1] in ":#" and m.start() - 1 == prev_end
        prev_end = m.end()
        if glued:
            continue                          # the locator remainder of one `path:locator` word
        tok = _RED_CAUSE_LOCATOR_RE.sub("", m.group(0)).rstrip(".,;:)\"'").strip("/")
        if not tok or "/" not in tok:
            continue
        head, _, tail = tok.partition("/")
        if "." in tail.rsplit("/", 1)[-1]:
            out.add(tok)                      # has a file extension — a path on its face
            continue
        if root is None:
            out.add(tok)                      # cannot check the repo => strict (see docstring)
            continue
        try:
            if (root / head).exists():
                out.add(tok)
        except Exception:      # noqa: BLE001 — an unanswerable existence check reads as a path
            out.add(tok)
    return out


def _locate_owner_directive(rows, locator) -> tuple:
    """The first two axes of rule 2 — «does this locator NAME an owner directive at all?».

    Returns `((position, row), None)` for the first `owner_directive` row carrying the locator's `ts`,
    else `(None, kind)` with kind `directive-unresolved` (not a whole-value `events.jsonl#ts=<ISO>`
    locator, or no row at that ts) or `directive-wrong-type` (rows at that ts, none an owner
    directive). Extracted from `_resolve_owner_directive` (T-13195) so the hostapply `--confirmed-by`
    gate (SPEC-0111 §1) resolves through the SAME grammar and lookup — one contract, two consumers.
    The later axes (precedes / delegation / covers) stay the ceiling resolver's own. Pure f(rows)."""
    m = _DIRECTIVE_LOCATOR_RE.fullmatch(str(locator or ""))
    if not m:
        return None, "directive-unresolved"   # the WHOLE value must be a locator — see the pattern
        # RAW, NEVER STRIPPED (audit-post finding 2, pass 2). «The WHOLE value must BE a locator» and
        # «the whole value once I have quietly trimmed it» are different contracts, and only the
        # first is the one rule 2 states. A `.strip()` here re-admitted exactly the class the
        # trailing-text refusal above closes: `--directive " events.jsonl#ts=… "` is a value that is
        # NOT a locator, and normalizing it before the test makes the resolver decide what the
        # caller MEANT. Authority is proven by RESOLUTION of the argument as given.
    ts = m.group(1)
    corpus = list(rows or ())
    at_ts = [(i, r) for i, r in enumerate(corpus) if isinstance(r, dict) and r.get("ts") == ts]
    if not at_ts:
        return None, "directive-unresolved"
    hit = next(((i, r) for i, r in at_ts if r.get("type") == "owner_directive"), None)
    if hit is None:
        return None, "directive-wrong-type"
    return hit, None


def _resolve_owner_directive(rows, locator, tid, *, decision_ts, decision_pos=None,
                             plan_slug=None, diag=None, _directive_covers_task,
                             _directive_row_text) -> tuple:
    """Rule 2's «AUTHORITY IS PROVEN BY RESOLUTION, NEVER BY A NON-EMPTY STRING».

    Returns `(row, None)` when the locator resolves to an owner directive that authorizes THIS
    decision, else `(None, kind)` naming the ONE refusal axis that stopped it — each of which is its
    own `read_gate_refused` kind at the call site:

      `directive-unresolved`      — the locator is not an `events.jsonl#ts=<ISO>` form, or no journal
                                    row carries that ts.
      `directive-wrong-type`      — a row exists at that ts but none of them is an `owner_directive`.
      `directive-late`            — the directive does not strictly PRECEDE the decision. Rule 2 is
                                    explicit that the bound is «precedes the DECISION», NEVER
                                    «precedes the ceiling row» — under the latter, trial cycle 4
                                    found no directive qualified for four of five real cards.

    PRECEDES IS JOURNAL ROW ORDER, NOT SECOND-GRANULARITY `ts` (T-12338). The comparison is the TUPLE
    `(ts, position) < (decision_ts, decision_pos)`, where `position` is the row's index in the
    caller's corpus and `decision_pos` DEFAULTS to `len(rows)` — the slot the pending decision will
    occupy, so every row already in the corpus precedes it. The reason this is not pedantry:
    `_utc_now_iso` is second-granularity, so a Controller who appends the `owner_directive` row and
    then records the decision within the SAME wall-clock second was refused `directive-late` under
    the old `str(ts) < str(decision_ts)` — measured on T-12335 (2026-09-10 14:02-14:05Z), where the
    only remaining exit was to wait out a second. A directive whose `ts` is strictly LATER than the
    decision is still `directive-late`: the tuple's first element decides before position is ever
    consulted, so the future-stamped fixtures are unchanged. `decision_pos` is a parameter rather
    than a constant precisely so BOTH arms are drivable by a pinned-identical-`ts` tripwire — a
    predicate that can only ever be called with «one past the end» cannot be shown to refuse.

    The DELEGATION sub-chain below keeps its own `str(cts) <= str(ts)` bound unchanged: that one
    orders a cited owner row against the DELEGATED row (two rows both already in the corpus, where
    `<=` already admits the same-second case), not against the pending decision.
      `delegation-chain-broken`   — a `captured_via: controller-delegated` row that cites no owner
                                    locator, or whose cited row is absent / is not an
                                    `owner_directive` / is itself delegated / does not precede it.
                                    A delegated row resolves ONLY through its chain, and a chain
                                    that ends in another delegation is not grounded in an owner.
                                    ONE named exception — the MID-TURN route (T-12801): a delegated
                                    row with `mid_turn: true`, a non-empty verbatim `owner_text`, a
                                    `source_ref`, and the verb-stamped `owner_text_verified: true`
                                    (proven against the anchored transcript entry at the write by
                                    `events._mid_turn_owner_text_refusal`) is grounded by that proof.
      `directive-not-covering`    — the row does not cover the task (see `_directive_covers_task`).

    THE BROKEN CHAIN NAMES ITS CAUSE (T-12836, X-1533). `delegation-chain-broken` stays ONE axis — the
    `read_gate_refused` kind every reader keys on — but five different faults reach it, and a caller
    passing a `diag` dict gets told which: `diag["reason"]` is one of `no-cited-locator`,
    `cited-row-missing`, `cited-not-owner`, `cited-delegated`, `cited-late`, and `diag["cited_ts"]`
    lists the ts values the row cites (self-citations excluded). With several citations the reported
    cause is the one that got FURTHEST (late > delegated > not-owner > missing), because that is the
    one the Controller is closest to fixing. Measured on <project> 2026-09-22: the owner row sat in an
    unlanded sibling worktree, the refusal could not say «not found», and three retries plus one
    duplicated owner row followed.

    Pure f(rows) — the rows come from the caller's segment-aware read."""
    corpus = list(rows or ())
    hit, kind = _locate_owner_directive(corpus, locator)
    if hit is None:
        return None, kind
    pos, row = hit
    ts = row.get("ts")
    # Row ORDER, not second-granularity `ts` — see PRECEDES IS JOURNAL ROW ORDER above. The default
    # `len(corpus)` is the position the decision this call authorizes is about to be appended at.
    dec_pos = len(corpus) if decision_pos is None else int(decision_pos)
    if not ((str(ts), pos) < (str(decision_ts), dec_pos)):
        return None, "directive-late"
    data = row.get("data") if isinstance(row.get("data"), dict) else {}
    if data.get("captured_via") == _CONTROLLER_DELEGATED:
        cited_ok = False
        cited_ts = []
        # How far each citation got — ordered so `max` names the cause closest to a grounded chain.
        causes = ("cited-row-missing", "cited-not-owner", "cited-delegated", "cited-late")
        furthest = -1
        for cm in _DIRECTIVE_LOCATOR_RE.finditer(_directive_row_text(row)):
            cts = cm.group(1)
            if cts == ts:
                continue                      # a row citing ITSELF grounds nothing
            cited_ts.append(cts)
            reached = 0                       # cited-row-missing until a row carries the ts
            for cand in rows or ():
                if not isinstance(cand, dict) or cand.get("ts") != cts:
                    continue
                reached = max(reached, 1)
                if cand.get("type") != "owner_directive":
                    continue
                reached = max(reached, 2)
                cdata = cand.get("data") if isinstance(cand.get("data"), dict) else {}
                if cdata.get("captured_via") == _CONTROLLER_DELEGATED:
                    continue                  # the chain must END in an owner row, not another delegation
                reached = max(reached, 3)
                if str(cts) <= str(ts):
                    cited_ok = True
                    break
            furthest = max(furthest, reached)
            if cited_ok:
                break
        # T-12801 — the NAMED MID-TURN route: the row grounds itself when the write verb proved its
        # verbatim owner text against the anchored transcript entry. Every element required; a
        # hand-appended row never carries the verb's `owner_text_verified` stamp.
        owner_text = data.get("owner_text")
        mid_turn_proven = (data.get("mid_turn") is True
                           and isinstance(owner_text, str) and bool(owner_text.strip())
                           and bool(str(row.get("source_ref") or "").strip())
                           and data.get("owner_text_verified") is True)
        if not cited_ok and not mid_turn_proven:
            if diag is not None:
                diag["reason"] = causes[furthest] if furthest >= 0 else "no-cited-locator"
                diag["cited_ts"] = cited_ts
            return None, "delegation-chain-broken"
    if not _directive_covers_task(row, tid, plan_slug=plan_slug):
        return None, "directive-not-covering"
    return row, None
