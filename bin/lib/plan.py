"""plan verb-family for the yitc-v2 CLI (T-9341, plan
`layer-2-final-tail-decomposition-of-bin-yitc-v2-pl`). The plan-lifecycle FSM
(plan file/draft/stage/check/to_idea/list/show), spec-birth, the gate-audit + finalization
machinery, and the decomposition/postcheck gates, plus their plan-exclusive helpers + consts.
The next layer-2-tail extraction after worktree.py (T-9340).

bin/yitc-v2 keeps a thin argparse residue cmd_plan_* (the set_defaults(func=…) entrypoints,
wiring unchanged) plus a host re-export wrapper under the historical name for every moved helper
+ a re-export alias for every moved const, each delegating here and injecting the host
collaborators + host globals it reads at call time (so a `-C` REPO_ROOT rebind and every
`monkeypatch.setattr(yitc, …)` stay honoured). Design B (the worktree.py / triage.py precedent):
the moved bodies are byte-identical with the inline originals — the test suite is the oracle.

Identity-agnostic KERNEL module (SPEC-0073 bin/ HARD class — travels with the engine). It imports
only stdlib + already-extracted lower leaves; it NEVER back-imports the host.
"""

from pathlib import Path
import argparse
import contextlib
import hashlib
import json
import os
import re
import sys

from lib import audit as audit_lib   # T-11299: the shared timeout-ABORT classifier + its reported face.
                                    # ALIASED on purpose — cmd_plan_check binds a LOCAL name `audit` to
                                    # the verdict mapping it writes, which would shadow a bare module import.
from lib import observe   # T-11249: the shared checkout-provenance render
from lib import state
from lib import events as events_mod  # T-11536: the SPEC-0190 logical-journal pathspec view
from lib import graph as graph_lib   # T-11876: the ONE hardened LIST-only glob/ref read (`_glob_list`)
                                     # — acyclic, graph.py imports only lib.state + stdlib.

# ── plan-exclusive module constants (moved verbatim from host) ──
# RE-EXPORT from the `lib.vocab` leaf (T-11320): the entry composes PLAN_STATUSES from this while
# building the `plan list --status` choices, so reading it here imported lib.plan on every CLI load.
# Single home moved to vocab.py, no copy — same object, same name here.
from lib.vocab import PLAN_TERMINAL  # noqa: F401,E402  (re-export)

# T-9369 — markers for the `## Realized-by-record` eligibility declaration (SPEC-0034 §Realized-by-record).
RECORD_ELIGIBILITY_MARKERS = ("## realized-by-record", "## realized by record", "realized-by-record:")


def _realized_by_record_declared(body: str) -> bool:
    """T-9369 — eligibility presence check (mirrors `_postcheck_probe_block_declared`): does the plan
    body declare a `## Realized-by-record` eligibility rationale (which soak-proof + which handoff
    happened OUTSIDE this plan's decomposition, and why it is record-class)? Presence ONLY — never
    parses the content (no detector, anti-cx; the SAME model as the postcheck-probe-block heuristic).
    Tolerant: empty/None → False. The owner-authored declaration is the EXPLICIT eligibility predicate
    the `--by-record` shortcut is gated on (audit-pre F1: a non-record-class plan cannot terminalize
    by record merely by supplying two refs)."""
    low = (body or "").lower()
    return any(m in low for m in RECORD_ELIGIBILITY_MARKERS)

PLAN_ACTIVE = ("draft", "specs", "trial", "accepted", "decomposition", "executing", "postcheck")

PLAN_LARGE_LINES = 200


def _plan_is_large(body: str) -> bool:
    """The SINGLE big-plan size predicate (T-9350 audit-pre F2): a plan is LARGE when its non-blank
    body-line count exceeds `PLAN_LARGE_LINES`. Shared by `cmd_plan_check` (the big-plan-checklist gate)
    AND `cmd_plan_draft`'s finalize pre-pass, so the finalize-time WARN and the later `plan check` agree
    by construction — no divergent line-count basis (the audit-pre divergence risk)."""
    return len([ln for ln in (body or "").splitlines() if ln.strip()]) > PLAN_LARGE_LINES

_PLAN_DRAFT_SKELETON = """\
# {title}

<!-- Front-load doctrine: SPEC-0043 (`{s43_hint}`) — fill these as PROMPTS, not gates. -->

## Problem / intent

<!-- What is wrong/missing and why now. Do the prior-art sweep FIRST (CHARTER §P1 F1):
     `yitc-v2 graph query <related-spec>` / `graph query --type view` / grep — extend over create. -->

## Done criterion

<!-- The owner-visible result that means "done" (CHARTER §P3 — an observable outcome, not "code shipped"). -->

## Verification plan

<!-- UPFRONT: probe targets + real-data soak expectation + a postcheck probe-block STUB
     (observed / min-runs / failure-threshold / evidence-home) — contract in SPEC-0034 §postcheck. -->

## External checks / audits

<!-- Which external audits at which boundaries (SPEC-0036 / SPEC-0034 §Audit-posture). Trial-eligibility
     (SPEC-0035): is this mechanism/behavioral (soak in `trial`) or text-audit-verifiable (skips trial)? -->

## Planned artifacts / corpus impact

<!-- Expected spec/task/decision OUTPUTS this plan will create or change — or "none yet".
     Scenario INPUTS: if this plan shapes/touches a user-path, declare its scenario INPUTS by listing
     the scenario slug(s) in this plan's `cites:` frontmatter (reuse cites: — NOT a new scenarios:
     field; convention SPEC-0043, semantics SPEC-0076 §4 `cites(plan→scenario)`).
     Scenario ROLES (SPEC-0082 — optional; drives the `plan check` scenario-fidelity dimension): if this
     plan ASSUMES some scenarios already work and/or BUILDS new ones, declare them in a FRONTMATTER field
       scenario_roles: {{baseline: [<scenario-slug>...], target: [<scenario-slug>...]}}
     baseline = an existing working invariant the plan relies on (a non-`live` one → a YELLOW finding);
     target = a scenario the plan is building (never flagged). Omit the field entirely if neither applies. -->

## Realization-exit criteria

<!-- UP FRONT (like a task's `acceptance` at filing): the postcheck probe block that says when this plan
     is `realized` — observed-behaviour / min-runs / failure-threshold / evidence-home. Author it HERE so
     the plan declares HOW it will be proven before it is built; CONFIRMED at `accepted`. Author-declared +
     owner-judged (no coded gate). Contract: SPEC-0034 §accepted/§postcheck. -->
"""


def _plan_draft_skeleton(title: str, *, is_consumer: bool = False) -> str:
    """Render the plan-draft skeleton for THIS session's realm (T-11992, SPEC-0092).

    The front-load pointer names the KERNEL SPEC-0043 (the draft-authoring doctrine). Under `-C` a
    bare id resolves consumer-own-first, and a consumer owning its own SPEC-0043 read the WRONG body
    off this exact line (aiseller 2026-09-02, X-1228) — so the hint is rendered kernel-explicit there
    via the ONE shared `graph.spec_query_hint`. The engine's own session renders the bare form, so
    every existing engine-side draft is byte-identical."""
    return _PLAN_DRAFT_SKELETON.format(
        title=title,
        s43_hint=graph_lib.spec_query_hint("SPEC-0043", is_consumer=is_consumer, cli="yitc-v2"))


# The CANONICAL header of the plan's realization-exit declaration — the name the skeleton seeds and
# SPEC-0043 item 8 blesses. ONE name across all three surfaces (T-10293): the skeleton above, the
# front-load completeness advisory `_plan_draft_sections_filled`, and `_postcheck_probe_block_declared`
# (the predicate the finalize WARN + the accept/postcheck REQUIRE-gates share).
REALIZATION_EXIT_SECTION = "Realization-exit criteria"

_PLAN_DRAFT_FRONT_LOAD_SECTIONS = (
    "Problem / intent", "Done criterion", "Verification plan",
    "External checks / audits", "Planned artifacts / corpus impact", REALIZATION_EXIT_SECTION,
)

_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)

# T-0483: a postcheck-probe-block-DECLARED advisory is a PRESENCE heuristic over the plan body — NOT a
# content parser, and NOT a "soak min-runs met" boolean (real-data ×N is owner-judged per plan, NEVER a
# coded count — SPEC-0034 §postcheck; the rejected fork-B mechanisms). The markers below are the LEGACY
# probe-block phrasings observed across the live postcheck plans (`## Postcheck probe block`, the inline
# "POSTCHECK CRITERIA") — a bare `## Postcheck` heading is deliberately EXCLUDED (audit-post pass-2 F1: it
# over-matches a generic postcheck section that declares no probe block). A hit means "the plan AUTHORED a
# probe block", nothing about its contents. `REALIZATION_EXIT_SECTION` is the CANONICAL name; these stay
# accepted so already-authored plans keep passing (T-10293).
_POSTCHECK_PROBE_BLOCK_MARKERS = ("postcheck probe block", "postcheck criteria")

# T-12027 — the SAME legacy phrasings as SECTION HEADERS, so the disclosure below can ask whether a
# legacy-marker plan's block carries AUTHOR content using the ONE filled-ness computation
# (`_plan_section_filled`, T-10293). No second parser and no content parsing: this only distinguishes
# "a heading with author text under it" from "a heading the gate accepted while it is still empty".
_PROBE_BLOCK_LEGACY_SECTIONS = ("Postcheck probe block", "Postcheck criteria")

PLAN_NONLINEAR_TERMINALS = ("partial", "rejected", "cancelled")

ACCEPTED_PREDECESSORS = ("specs", "trial")

_SPEC_STATUS_LINE_RE = re.compile(r"(?m)^status:.*$")

_PLAN_SCENARIO_ROLES_KEYS = ("baseline", "target")

_SF_UNSET = object()

PLAN_GATE_TEMPLATE_SPEC = "SPEC-0036"

PLAN_GATE_TEMPLATE_ANCHORS = {
    "plan-draft": "P1", "gate-specs": "P2", "gate-trial": "P3", "gate-accepted": "P4",
    # P5 = the decomposition->executing fidelity gate (SPEC-0070 §3). The CODE that consumes it lands in
    # T-0649; the P5 PROSE in SPEC-0036 lands in T-0650 (the settled SPEC-0070 §9 build order). Until the
    # prose exists, a mandatory-blocking gate-executing run FAILS CLOSED (safe) — see
    # _require_plan_decomposition_fidelity.
    "gate-executing": "P5",
}

_PLAN_TEMPLATE_TO_GATE_ID = {
    "gate-specs": "draft-specs", "gate-trial": "specs-trial",
    "gate-accepted": "trial-accepted", "gate-executing": "decomposition-executing",
}

_PLAN_CHECKLIST_KEY_RE = re.compile(r"^[ \t]*checklist_pass[ \t]*:(.*)$", re.IGNORECASE)

_PLAN_CHECKLIST_INLINE_RE = re.compile(r"\{[^}]*\bP[1-9]\b")

_PLAN_CHECKLIST_PROBE_RE = re.compile(r"^[ \t]+P[1-9]\b", re.IGNORECASE)

# ── plan→task LINK index, scoped to ONE invocation (T-10927) ──────────────────────────────────
# The plan→task LINK predicate (`decomposed_from == slug` OR `slug in cites`) is evaluated by
# `_plan_tasks` and `_plan_retire_on_proof`, each as a FULL sweep of the tasks/ corpus. A caller that
# asks it once PER PLAN therefore re-reads the WHOLE corpus once per plan: measured on the
# postcheck-plans-readiness lens at 17 postcheck plans x 2294 cards = 174,399 `_read_yaml` calls over
# tasks/ (~4.5 sweeps per plan), 15.1s — O(N*M) where O(M) suffices. `state.load_path` already
# memoizes the PARSE (T-0359), so what remains per call is an os.stat + a deepcopy of the whole tree;
# the fix is to stop MAKING the calls.
#
# WHAT THIS IS: a VIEW-LEVEL REUSE scoped to ONE invocation (CHARTER §P1 F2), NOT a new store. The
# BOUND (T-10927 acceptance AC3) is deliberate and load-bearing: NO cache file, NO staleness window,
# NO module-level state surviving the invocation. `_PLAN_LINK_INDEX` is None before the scope opens
# and is restored to None in a `finally` when it closes — including on an exception — so the corpus is
# still read FRESH on every run and no caller outside an open scope can observe a stale index. This is
# deliberately UNLIKE `views._any_close_missing_disposition`'s mtime/size-keyed CROSS-invocation memo:
# that shape needs an invalidation key precisely because it survives the call, and T-10927's bound
# refuses that trade here.
_PLAN_LINK_INDEX = None


def _plan_link_index():
    """The live plan→task link index, or None when no scope is open (the fallback-to-sweep signal).

    Value shape: {slug: [(tid, status, has_return_trigger, cls), ...]} — every field a per-plan reader
    needs off a LINKED card, so none of them has to re-read it: `status` + the link itself
    (`_plan_tasks`), the `return_trigger` PRESENCE (`_plan_retire_on_proof`), and `class`
    (`views._dispositionless_infra_closures`, which otherwise re-opened every done member's card just
    to test `class == infra`). A slug absent from the index means "no task links to this plan", which
    is the same empty answer the sweep gives."""
    return _PLAN_LINK_INDEX


@contextlib.contextmanager
def _plan_link_index_scope(*, TASKS_DIR, _read_yaml):
    """Sweep tasks/ ONCE and serve the plan→task link predicate from the result for the duration of
    this `with` block; tear the index down on exit (see the §BOUND note above — nothing survives).

    RE-ENTRANT: if a scope is already open, this is a no-op and the OUTER scope owns teardown — a
    nested caller must never null the index out from under its parent. Callers that do NOT open a
    scope are entirely unaffected: `_plan_tasks` / `_plan_retire_on_proof` keep their original full
    sweep, so the pre-change behaviour stays executable (this is what T-10927 AC2 compares against)."""
    global _PLAN_LINK_INDEX
    if _PLAN_LINK_INDEX is not None:   # nested — the outer scope owns build + teardown
        yield _PLAN_LINK_INDEX
        return
    index: dict = {}
    for p in state.scan_tasks(TASKS_DIR):   # T-* glob excludes _template.yaml — the SAME scan the sweeps do
        d = _read_yaml(p)
        if not isinstance(d, dict):
            continue
        entry = (d.get("id") or p.stem,
                 d.get("status"),
                 bool(str(d.get("return_trigger") or "").strip()),
                 d.get("class"))
        # index by EVERY slug this card links to, under the SAME union the sweeps read (T-9152):
        # `decomposed_from == slug` OR `slug in cites` (list-membership equality, NOT substring).
        links = set()
        dfrom = d.get("decomposed_from")
        if isinstance(dfrom, str) and dfrom:
            links.add(dfrom)
        cites = d.get("cites")
        if isinstance(cites, list):
            links.update(c for c in cites if isinstance(c, str))
        for slug in links:
            index.setdefault(slug, []).append(entry)
    _PLAN_LINK_INDEX = index
    try:
        yield index
    finally:
        _PLAN_LINK_INDEX = None


def _plan_cut_cards(slug: str, *, TASKS_DIR, _read_yaml) -> list:
    """The plan's DECOMPOSITION CUT MEMBER-SET (T-0694): every tasks/T-*.yaml whose `decomposed_from`
    marker EQUALS slug (the NARROW structural cut-membership relation, SPEC-0070 §5) — the SOLE
    authoritative writer is the decomposition cut (`task file --decomposed-from`). Returns sorted
    [(tid, status)]. The cut-fidelity member-set carrier — DISTINCT from `_plan_tasks` (the BROAD
    `cites:`-the-plan informational/T-0256-finalization-corpus relation): the two are NON-SUBSTITUTABLE
    (SPEC-0070 §5 / SPEC-0034). Keying the member-set on `cites:` over-counted an informational citer as
    a cut member — it wrongly staled the cut fingerprint AND was shown to the fidelity auditor as a cut
    card (the overload T-0685 closed for the claim-block; this closes it for the fingerprint + the
    audit-prompt card-set). Mirror of `_task_decomposed_from_pre_executing_plan`'s marker read."""
    out = []
    for p in state.scan_tasks(TASKS_DIR):   # T-* glob excludes _template.yaml
        d = _read_yaml(p)
        if isinstance(d, dict) and d.get("decomposed_from") == slug:
            out.append((d.get("id") or p.stem, d.get("status")))
    return sorted(out)


def _plan_card_set_fingerprint(slug: str, *, SPECS_DIR, TASKS_DIR, _plan_cut_cards, _read_yaml) -> str:
    """Canonical fingerprint of a plan's CUT — the task-card SET + the spec-activation linkage — for the
    decomposition-fidelity verdict freshness contract (SPEC-0070 §4). The direct analog of the accept-gate
    _plan_content_hash / _plan_corpus_signature: the decomposition-fidelity verdict RECORDS this, and
    `plan stage executing` RECOMPUTES it and requires an EXACT match (edit the cut after the audit →
    re-fingerprint → stale → REFUSE → re-audit). NO new machinery class.

    Canonical, sorted/stable inputs (SPEC-0070 §4):
      - the sorted set of cut task ids (= `_plan_cut_cards(slug)`, the cards whose `decomposed_from`
        marker names the plan — the NARROW cut-membership relation, T-0694; an informational `cites:`-only
        citer is NOT a cut member, so it no longer staling the fingerprint);
      - PER card: its `requires:` (sorted), its `acceptance:` (= the embedded PROBE carrier — V2 task
        cards have NO separate `probe` field, probes live inside acceptance entries per LIFECYCLE Stage
        2), its `scope:` (the card body), its `cites:` (sorted), and its `title` — the STRUCTURAL shape
        of the cut. Volatile build-PROGRESS fields (status / current_stage / analysis /
        implementation_plan / last_verified) are EXCLUDED so a benign claim/stamp does not stale the cut;
      - the plan's proposed-spec ACTIVATION mapping: sorted [(spec_id, activation_owner_task)] for every
        spec with `proposed_by == slug` — WHICH task activates each spec is a cut decision (re-pointing it
        re-fingerprints). (In V2 the activation owner is this spec→task pointer, not a per-card field.)
    Telemetry-grade: degrades to a stable error-hash on any read failure (must never crash the gate verb)."""
    try:
        cards = []
        for tid, _st in _plan_cut_cards(slug):   # T-0694: cut MEMBER-set via decomposed_from, NOT cites:
            p = next(TASKS_DIR.glob(f"{tid}-*.yaml"), None) or (TASKS_DIR / f"{tid}.yaml")
            d = _read_yaml(p) if (p and p.exists()) else {}
            d = d if isinstance(d, dict) else {}
            cards.append({
                "id": tid,
                "requires": sorted(d.get("requires") or []),
                "acceptance": list(d.get("acceptance") or []),   # the PROBE carrier (no separate field)
                "scope": list(d.get("scope") or []),             # the card body
                "cites": sorted(d.get("cites") or []),
                # T-10388: the touch-forecast is now a fidelity-checked cut property (SPEC-0036 P5),
                # so it MUST be in the freshness basis — else a post-audit expected_touch edit would
                # reuse the stale GREEN verdict without re-checking the forecast the auditor blessed.
                "expected_touch": sorted(d.get("expected_touch") or []),
                "title": d.get("title") or "",
            })
        cards.sort(key=lambda c: c["id"])
        spec_activation = []
        for sp in state.scan_specs(SPECS_DIR):   # SPEC-* glob excludes _template.yaml
            d = _read_yaml(sp)
            if isinstance(d, dict) and d.get("proposed_by") == slug:
                spec_activation.append([d.get("id") or sp.stem, d.get("activation_owner_task")])
        spec_activation.sort(key=lambda x: (x[0] or ""))
        basis = json.dumps({"cards": cards, "spec_activation": spec_activation},
                           sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(basis.encode("utf-8")).hexdigest()
    except Exception:
        return hashlib.sha256(b"<plan-card-set-fingerprint-error>").hexdigest()


def _plan_section_filled(body: str, name: str) -> bool:
    """Does the `## <name>` section exist AND carry AUTHOR content? A section is FILLED when, after
    removing the `<!-- ... -->` skeleton stub comment(s) + whitespace, its body is non-empty; a heading
    absent entirely is unfilled. PRESENCE only, never a semantic-completeness judgement (CHARTER
    non-goal #7). Extracted from `_plan_draft_sections_filled`'s per-section body (T-10293) so the
    front-load advisory and `_postcheck_probe_block_declared` share ONE computation. Tolerant: an
    unreadable/empty body → False (a report helper must never crash the verb)."""
    try:
        m = re.search(r"^##\s+" + re.escape(name) + r"\s*$(.*?)(?=^##\s|\Z)",
                      body or "", flags=re.MULTILINE | re.DOTALL)
        if not m:
            return False
        return bool(_HTML_COMMENT_RE.sub("", m.group(1)).strip())
    except Exception:
        return False


def _postcheck_probe_block_declared(body: str) -> bool:
    """Advisory presence heuristic (T-0483): does the plan body declare its realization-exit — the
    postcheck probe block? The SINGLE predicate the `plan draft --finalize` WARN and the `plan stage
    accepted` / `plan stage postcheck` REQUIRE-gates share. TRUE when either the CANONICAL
    `## Realization-exit criteria` section is FILLED, or a LEGACY marker phrasing appears in the body.
    ADVISORY ONLY — it reports whether a block was authored, NEVER parses min-runs/thresholds (that
    would be the rejected free-text-parser fork B). Tolerant: empty/None body → False.

    T-10293 — matched on the COMMENT-STRIPPED body, and the canonical section counts. Before, this read
    the RAW body against the legacy markers alone, which inverted the check both ways: the seeded
    skeleton's own `<!-- ... -->` stub contains the phrase "postcheck probe block", so an UNTOUCHED
    skeleton passed the accept-gate (declaring nothing), while an author who filled the seeded
    `## Realization-exit criteria` section and dropped the stub was WARNed for content they had just
    written (the 2026-07-09 incident — the plan had to carry BOTH headers)."""
    if _plan_section_filled(body, REALIZATION_EXIT_SECTION):
        return True
    low = _HTML_COMMENT_RE.sub("", body or "").lower()
    return any(m in low for m in _POSTCHECK_PROBE_BLOCK_MARKERS)


def _plan_probe_block_state(body: str) -> str:
    """T-12027 — is the plan's realization-exit probe block `filled`, a `stub`, or `absent`?

    The gate (`_postcheck_probe_block_declared`) is a PRESENCE predicate: a body carrying a legacy
    marker phrase passes it with an EMPTY section, so "the gate was satisfied" and "someone wrote the
    exit criteria" are indistinguishable at the transition (the X-1250 plan transited
    executing->postcheck->realized in two seconds on an unfilled stub). This REPORT-ONLY helper names
    the difference. It parses NO content — no min-runs, no thresholds, no soak arithmetic (the
    rejected fork-B stays rejected); it asks only whether SOME probe-block section carries author
    text, reusing `_plan_section_filled` (the ONE filled-ness computation, T-10293).

      `filled`  — the canonical `## Realization-exit criteria` OR a legacy probe-block section has
                  author content under it.
      `stub`    — the block is DECLARED (the gate's presence predicate passes) but no such section
                  carries author content: PRESENT-BUT-UNREAD.
      `absent`  — not declared at all; the postcheck gate refuses before any of this prints.

    Tolerant by contract: any failure degrades to `absent` — a report helper must never crash the
    verb, and never move admission (mirrors `_plan_draft_sections_filled` / `_stage_bundle_specs`)."""
    try:
        names = (REALIZATION_EXIT_SECTION, *_PROBE_BLOCK_LEGACY_SECTIONS)
        if any(_plan_section_filled(body, n) for n in names):
            return "filled"
        return "stub" if _postcheck_probe_block_declared(body) else "absent"
    except Exception:
        return "absent"


# T-12027 — the label sets the two soak-bounding transitions disclose. LABELS, not re-run checks: the
# gate has ALREADY passed when the disclosure prints, so re-executing its clauses to render them would
# be a second (and divergent) copy of the gate. What the disclosure adds is the honest NEGATIVE half —
# what no gate on this path reads — which is what a silent pass and a satisfied gate otherwise share.
_PLAN_GATE_CHECKED = {
    "postcheck": ("linked_tasks_done", "corpus_specs_active", "aggregate_audit_post_plan",
                  "realization_exit_block_present"),
    "realized": ("plan_finalization_ready", "retire_on_proof_tasks_terminal",
                 "captures_routed_advisory", "closed_into_recorded"),
}
_PLAN_GATE_NOT_CHECKED = ("realization_exit_block_content", "soak_duration")


def _plan_gate_disclosure(slug: str, body: str, stage: str, delivered) -> dict:
    """T-12027 — REPORT-ONLY: what the `postcheck` / `realized` gate that just passed actually read,
    and what it did NOT. Returns {slug, stage, probe_block, checked, not_checked}; the SAME dict is
    printed AND folded into the `plan_stage_entered` payload, so the transition line and the journal
    row can never disagree (P5 — one computation, two surfaces).

    NOT a gate: it decides nothing, raises nothing, and is called only AFTER admission is settled.
    Deliberately carries NO duration threshold — a minimum-seconds soak rule is voluntaristic (a
    number no plan's evidence justifies), so `soak_duration` is disclosed as UNREAD rather than
    enforced. Tolerant: any failure degrades to an empty disclosure, never a raise."""
    try:
        state_ = _plan_probe_block_state(body)
        not_checked = list(_PLAN_GATE_NOT_CHECKED)
        if state_ == "stub":
            not_checked.append("realization_exit_block_is_unfilled_stub")
        if not delivered:
            not_checked.append("delivered_set_empty")
        return {"slug": slug, "stage": stage, "probe_block": state_,
                "checked": list(_PLAN_GATE_CHECKED.get(stage, ())),
                "not_checked": not_checked}
    except Exception:
        return {}


def _print_plan_gate_disclosure(d: dict) -> None:
    """T-12027 — the SINGLE print for `_plan_gate_disclosure` (the `_print_plan_stage_delivery`
    precedent: one home for a transition print FORMAT). stdout only; never touches the exit code."""
    if not d:
        return
    slug, stage = d.get("slug"), d.get("stage")
    if d.get("checked"):
        print(f"{slug}: {stage} gate CHECKED: {', '.join(d['checked'])}")
    if d.get("not_checked"):
        print(f"{slug}: {stage} gate did NOT check: {', '.join(d['not_checked'])}")
    if d.get("probe_block") == "stub":
        print(f"{slug}: realization-exit probe block is PRESENT-BUT-UNREAD — it satisfied the presence "
              f"gate while carrying no author content (an unfilled stub), and NO gate on this path "
              f"reads its content or the elapsed soak. A two-second {stage} is admissible by "
              f"construction; the evidence this plan claims is NOT established by this transition. "
              f"Fill `## {REALIZATION_EXIT_SECTION}` in plans/{slug}.md and record the reading "
              f"(report-only — the transition PROCEEDS, T-12027 / X-1252).")


def _plan_draft_sections_filled(body: str) -> "tuple[bool, list]":
    """REPORT-ONLY structural pre-pass for `plan draft --finalize` (SPEC-0046 / SPEC-0059
    §enforcement-split — advisory, NEVER a blocker). Returns (ok, missing): which of the six SPEC-0043
    front-load sections have AUTHOR content — a PRESENCE check, never a semantic-completeness judgement
    (CHARTER non-goal #7). Filled-ness is `_plan_section_filled`'s ONE computation (T-10293), shared with
    `_postcheck_probe_block_declared` so the advisory and the gate cannot diverge on the same section.
    Tolerant: an unreadable/empty body degrades to (True, []) — a report helper must never crash the
    verb (mirrors `_postcheck_probe_block_declared` / `_stage_bundle_specs`)."""
    try:
        missing = [n for n in _PLAN_DRAFT_FRONT_LOAD_SECTIONS if not _plan_section_filled(body, n)]
        return (len(missing) == 0, missing)
    except Exception:
        return (True, [])


def _plan_draft_finalized_fresh(slug: str, body: str, *, _iter_events, _plan_content_hash) -> bool:
    """True iff a `plan_draft_finalized` journal event exists for `slug` whose recorded `body_hash`
    matches the CURRENT body content-hash — the PROVENANCE-bound draft worked-through proof that
    `plan stage specs` requires (T-0601, audit-post HIGH). Only `plan draft --finalize` emits this
    event, so the proof is bound to the VERB's emission, not a forgeable frontmatter field; a body
    edited since the last finalize no longer hash-matches → stale → the gate refuses. Journal-only via
    the single `_iter_events` reader (P5); session-agnostic (the worked-through proof carries across
    sessions — the per-session doctrine read is enforced separately by the read-check leg)."""
    want = _plan_content_hash(body)
    for e in _iter_events():
        if e.get("type") != "plan_draft_finalized":
            continue
        d = e.get("data") or {}
        if d.get("slug") == slug and d.get("body_hash") == want:
            return True
    return False


def cmd_plan_draft(args: argparse.Namespace, *, PLANS_DIR, _append_event, _die, _emit_read_gate_refused, _load_draft, _plan_content_hash, _plan_draft_sections_filled, _postcheck_probe_block_declared, _require_reads, _require_writing_worktree, _resolve_session_ref) -> None:
    """`plan draft --finalize <slug>` (T-0601, R7) — the DRAFT-stage check-carrier WORK-verb, the
    plan-axis realization of SPEC-0059 §First-stage-check-carrier-gap (mirror of the task-axis
    `task analyze --finalize`). It is the draft's END verb: the incident it closes is that the draft
    stage had a START verb — `plan file` delivers the SPEC-0043 doctrine — but NO end verb, so the
    SPEC-0034 pointer went unfetched and no verb gated the read before `plan stage specs`
    (the postcheck-to-realized incident, SPEC-0059 §Rationale).

    Built BY CONSTRUCTION per patterns/verb-design.md §Stage-work-verb recipe — TWO BLOCKING refusal
    axes (each emits `read_gate_refused`) + a REPORT-ONLY structural pre-pass:
      1. status==draft guard — the plan-axis analog of `_require_stage_correspondence` (the plan FSM has
         no `current_stage`; `status` IS the stage). Refusal → `read_gate_refused` kind=stage-correspondence.
      2. read-check (SPEC-0042 / SPEC-0050 cross-axis, T-0599): the draft bundle [SPEC-0043, SPEC-0034]
         must be FETCHED this session. Refusal → `read_gate_refused` kind=read-check.
      report-only: `_plan_draft_sections_filled` WARNs about unfilled front-load sections — advisory,
      NEVER blocks (keeps SPEC-0043's "no draft-completeness validator" / CHARTER non-goal #7 stance).
      ALSO report-only (T-9350): surface — at FINALIZE, before the first accept-gate `plan check` — the
      two checks the LATER gates apply, so they are fixed UP FRONT, not at `plan stage accepted` where
      editing the body stales the check's content_hash/accept_freshness_hash → a forced re-check (the
      3-plan-check incident, T-9342): (a) a missing postcheck probe block per the accept-gate's OWN
      marker test `_postcheck_probe_block_declared` (the SAME predicate `plan stage accepted` gates on,
      plan.py §accepted) — NOT the front-load section NAME, so it catches the naming mismatch where a
      draft passes finalize+check then fails at accept; (b) for a LARGE plan (over `PLAN_LARGE_LINES`) a
      missing `checklist_pass` per `_plan_has_checklist_pass` (the big-plan check `plan check` later
      WARNs on — SPEC-0034). Both advisory, never block (reuse the existing helpers — no new gate).
    On success it EMITS a `plan_draft_finalized` journal event carrying `body_hash`
    (`_plan_content_hash(body)`) — the PROVENANCE-bound worked-through proof (only this verb emits it;
    not a forgeable frontmatter field — audit-post HIGH). `plan stage specs` REQUIRES a FRESH such
    proof (matching the current body) + the recorded reads (non-skippable); a later hollow-out edit
    no longer hash-matches → stale → refused. --finalize-only (mirror of `task plan --finalize`)."""
    if not getattr(args, "finalize", False):
        _die("`plan draft` currently supports only --finalize (the draft-stage finalize action)")
    _require_writing_worktree()
    path, fm, body = _load_draft(args.slug, dirs=(PLANS_DIR,))
    slug = fm.get("id") or args.slug
    status = fm.get("status") or "draft"
    # BLOCKING axis 1 — status==draft (the plan-axis stage-correspondence analog; journaled refusal).
    if status != "draft":
        try:
            sref = _resolve_session_ref()
        except SystemExit:
            sref = "session-unresolved"   # best-effort: the refusal row MUST journal (T-0561 precedent)
        _emit_read_gate_refused(
            "plan draft --finalize",
            {"action": "draft finalize", "stage": "draft", "current_stage": status},
            kind="stage-correspondence", reason="status_mismatch", task_id=None, session_ref=sref)
        _die(f"{slug}: status={status!r} — `plan draft --finalize` finalizes a plan still at "
             f"status=draft (the draft-stage END verb). A plan past draft has already been finalized.")
    # BLOCKING axis 2 — read-check: the draft bundle [SPEC-0043, SPEC-0034] fetched this session.
    # T-11885 — collect what the gate ACTUALLY credited, so the proof event below records the
    # verified read set instead of a hardcoded literal. Report-only: the gate's admit behaviour is
    # unchanged, and a vacuous gate (empty doc-set) leaves this EMPTY — the honest record.
    credited: set = set()
    _require_reads("stage", {"axis": "plan", "stage": "draft", "verb": "plan draft --finalize",
                             "action": "draft finalize"}, credited_out=credited)
    # REPORT-ONLY structural pre-pass (SPEC-0046 / SPEC-0059 §enforcement-split) — advisory, never blocks.
    ok, missing = _plan_draft_sections_filled(body)
    if not ok:
        sys.stderr.write(
            f"WARN: {slug} front-load section(s) still unfilled: {', '.join(missing)} "
            f"(SPEC-0043 checklist — advisory, NOT a gate). Fill them for a thought-through draft; "
            f"finalizing anyway.\n")
    # ALSO surface the two LATER-gate checks at finalize, before the first accept-gate `plan check` —
    # advisory, never blocks (T-9350). Reuses the accept-gate's OWN predicate + the big-plan helper, so
    # finalize mirrors exactly what `plan stage accepted` / the big-plan `plan check` will apply.
    postcheck_declared = _postcheck_probe_block_declared(body)
    if not postcheck_declared:
        sys.stderr.write(
            f"WARN: {slug} declares NO postcheck probe block — `plan stage accepted` will REQUIRE one "
            f"(realization-exit: observed / min-runs / failure-threshold / evidence-home). FILL the "
            f"seeded `## {REALIZATION_EXIT_SECTION}` section NOW, before the first `plan check` "
            f"(advisory, NOT a gate); adding it at accept edits the body and stales the check → a "
            f"forced re-check. (A legacy `## Postcheck probe block` section also counts.)\n")
    n_lines = len([ln for ln in body.splitlines() if ln.strip()])
    large = _plan_is_large(body)   # the SHARED big-plan predicate (audit-pre F2 — agrees with `plan check`)
    checklist_present = _plan_has_checklist_pass(body)
    if large and not checklist_present:
        sys.stderr.write(
            f"WARN: {slug} is LARGE ({n_lines} body lines > {PLAN_LARGE_LINES}) but declares NO "
            f"`checklist_pass` block — the big-plan check (`plan check`) will WARN on it (the 7-probe "
            f"self-traversal, patterns/big-plan-checklist.md). Add the `checklist_pass:` block NOW, "
            f"before the first `plan check` (advisory, NOT a gate); adding it later stales the check.\n")
    # RECORD the worked-through proof as a JOURNAL event bound to the current body content-hash
    # (audit-post HIGH: provenance, NOT a forgeable frontmatter field). `plan stage specs` REQUIRES a
    # `plan_draft_finalized` event whose `body_hash` matches the live body — and only THIS verb emits
    # it, so the proof is bound to the verb's emission, not to plain editable state. No frontmatter
    # write: the journal IS the single source of the proof (P5), and a body edited after finalize no
    # longer hash-matches → the gate sees no fresh proof → refuses (the freshness binding).
    body_hash = _plan_content_hash(body)
    _append_event("plan_draft_finalized", None,
                  {"slug": slug, "body_hash": body_hash,
                   # T-11885 — the CREDITED fetch set, not a literal. A hardcoded list left a FALSE
                   # record in the append-only journal wherever the gate was vacuous (a -C consumer
                   # with no plan-stage-entry bindings gets an empty doc-set and the gate returns on
                   # its graceful-empty branch) — CHARTER P7 dissonance, worse than an absent gate.
                   "reads_verified": sorted(credited),
                   "sections_filled": ok, "sections_missing": missing,
                   "postcheck_block_declared": postcheck_declared,
                   "checklist_pass_present": checklist_present, "large": large})
    suffix = ("— all six front-load sections filled" if ok
              else f"— WARN unfilled: {', '.join(missing)}")
    print(f"{slug} draft finalized (plan_draft_finalized proof emitted; bound to current body hash) {suffix}")
    print(f"next: `yitc-v2 plan stage specs {slug}` — it REQUIRES this FRESH proof (a plan_draft_finalized "
          f"event matching the current body) + the recorded SPEC-0043/SPEC-0034 reads (non-skippable), "
          f"AND it now asks the MANDATORY-BLOCKING gate-specs external audit (RED/ABORT holds — gate "
          f"policy: SPEC-0083).")
    # T-10727 — the cue names BOTH staleness sources, not just the plan body. `accept_freshness_hash`
    # covers the plan-born DRAFT SPECS + the active/proposed corpus CONTENT too (T-0332; see
    # `_plan_accept_core`'s accept-freshness branch), so a draft-spec body edit or a `travels:` re-pin
    # made after the check stales the accept gate EXACTLY as a body edit does. That half was invisible
    # here — the operator fixed the body in time and still ate a forced re-check for a spec edit.
    print("TIMING: fix any postcheck-block / checklist_pass WARN above NOW — and finish your DRAFT-SPEC "
          "edits too — BEFORE the first accept-gate `plan check`. Adding them at `plan stage accepted` "
          "edits the body, staling the check's content_hash/accept_freshness_hash → a forced re-check "
          "(the 3-plan-check incident, T-9342); and `accept_freshness_hash` covers the plan-born "
          "draft-spec + active/proposed corpus CONTENT, not only the plan body (T-0332) — so editing a "
          "draft spec's body, or re-pinning its `travels:` at plan-accept, stales it exactly the same way.")


def cmd_plan_file(args: argparse.Namespace, *, IDEAS_DIR, PLANS_DIR, REPO_ROOT, _append_event, _die, _emit_plan_stage_entered, _find_draft, _print_plan_stage_delivery, _require_writing_worktree, _slug, _utc_now_iso, _write_draft, _is_consumer_build=None) -> None:
    """Create а plan (plans/<slug>.md, full FSM frontmatter, initial status: draft) или an idea
    (--idea → ideas/<slug>.md, minimal frontmatter, no FSM per audit-pre F2).

    T-0416 — for a PLAN (not an idea) `plan file` ALSO delivers the `plan-stage-entry:draft` bundle
    (the draft-authoring doctrine SPEC-0043) through the SAME path every other stage uses, and seeds
    the front-load skeleton. `draft` is the INITIAL status, so `plan stage draft` is unreachable — this
    is the delivery point for the draft bundle (closing that wiring gap)."""
    _require_writing_worktree()
    title = (args.title or "").strip()
    if not title:
        _die("--title required (non-empty)")
    slug = _slug(title, die=_die)
    is_idea = bool(args.idea)
    target = (IDEAS_DIR if is_idea else PLANS_DIR) / f"{slug}.md"
    existing = _find_draft(slug)
    if existing is not None:
        _die(f"slug collision: {existing.relative_to(REPO_ROOT)} already uses {slug!r}")
    created = _utc_now_iso()[:10]
    if is_idea:
        # MINIMAL frontmatter — flat holding pen, no FSM (D-0034 + audit-pre F2).
        fm = {"id": slug, "created": created, "source": (args.source or "owner observation")}
    else:
        # FULL FSM frontmatter — the planning workspace (D-0034 §File shape). `implementation_plan`
        # (T-0316) is the acceptance-stage decomposition-map output, mirroring the task field of the
        # same name; the `plan stage executing` entry-gate checks it is composed (non-empty). Initialized
        # null — edited into the frontmatter during the `accepted` stage, like the task field.
        fm = {"id": slug, "status": "draft", "created": created, "closed_into": [],
              "implementation_plan": None}
    # T-0416 — ideas keep the flat minimal body; a PLAN gets the front-load base sections (SPEC-0043).
    body = (f"# {title}\n\n<!-- planning prose below -->\n" if is_idea
            else _plan_draft_skeleton(title, is_consumer=bool(_is_consumer_build and _is_consumer_build())))
    _write_draft(target, fm, body)
    kind = "idea" if is_idea else "plan"
    data = {"slug": slug, "kind": kind, "path": str(target.relative_to(REPO_ROOT))}
    if not is_idea:
        data["status"] = "draft"
    _append_event("draft_filed", None, data)
    print(f"{kind} filed: {target.relative_to(REPO_ROOT)} (id={slug})")
    if is_idea:
        print("next: held in ideas/ (flat, no FSM) — re-file as a plan when an incident pulls it.")
    else:
        # T-0416 — DELIVER the draft bundle (the draft-authoring doctrine) at draft-entry, the same
        # path every other stage uses (`_emit_plan_stage_entered` from=null → draft) + the SHARED
        # delivery print. Closes the gap: `plan stage draft` is unreachable (draft is initial), so
        # `plan file` is the delivery point. Journals `plan_stage_entered` = the P8 live-trigger.
        delivered = _emit_plan_stage_entered(slug, None, "draft")
        # T-10919 (X-0704) — the hint NAMES `plan draft --finalize`, the draft's mandatory END verb,
        # in its true position: `plan stage specs` BLOCKS on the body-bound `plan_draft_finalized`
        # proof only that verb emits (_plan_draft_finalized_fresh). Omitting it cost every session one
        # failed transition per plan. The specs-branch refusal stays the unchanged backstop (AC2) —
        # this ADDS the step to the first-trusted surface, it does not relocate the guidance.
        print(f"next: front-load the draft (skeleton sections seeded); `yitc-v2 plan draft --finalize "
              f"{slug}` (the draft's MANDATORY end verb — emits the proof the next transition "
              f"requires), `yitc-v2 plan stage specs "
              f"{slug}` (compose+gate the draft specs), `yitc-v2 plan check {slug}` to verify, then "
              f"the post-specs FORK (SPEC-0035): trial-eligible (mechanism/behavioral) → "
              f"`yitc-v2 plan stage trial {slug}`; else (non-eligible prose/docs, the skip) → "
              f"`yitc-v2 plan stage accepted {slug}`.")
        _print_plan_stage_delivery("draft", delivered)


def _birth_plan_draft_specs(plan_slug: str, *, SPECS_DIR, _decision_apply_field_edits, _read_yaml) -> list:
    """T-0192 (Part B, plan↔spec coupling) — flip every DRAFT spec OWNED by `plan_slug`
    (status: draft AND proposed_by == plan_slug) to status: proposed, in sorted-id order.
    Returns the list of SPEC ids flipped this call.

    Reuses the EXISTING generic targeted line-edit helper `_decision_apply_field_edits`
    (comment-preserving + reload self-test) — it operates on any YAML; the `_decision_` prefix is
    a misnomer (a neutral rename is deferred to avoid decision-caller blast radius). NO parallel
    edit/re-dump path. IDEMPOTENT: the status==draft filter skips already-`proposed` specs, so a
    re-run after a partial failure finishes the rest — the coupling is one COMMAND, resumable, NOT
    a cross-file transaction (V2 has no transactions; same non-transactional contract plan accept
    already has for its own plan-write + event-emit)."""
    born = []
    for p in state.scan_specs(SPECS_DIR):   # SPEC-* glob excludes _template.yaml
        d = _read_yaml(p)
        if not isinstance(d, dict):
            continue
        if d.get("status") == "draft" and d.get("proposed_by") == plan_slug:
            raw = p.read_text(encoding="utf-8")
            _decision_apply_field_edits(p, raw, [("status", "status: proposed")], {"status": "proposed"})
            if d.get("id"):
                born.append(d["id"])
    return sorted(born)


def _split_into(raw) -> list:
    """Flatten a repeatable+comma-separated `--into` arg into a clean id list (close/realized/partial)."""
    return [x.strip() for item in (raw or []) for x in str(item).split(",") if x.strip()]


def _emit_plan_stage_entered(slug: str, frm, to: str, *, extra=None, _append_event, _plan_stage_bundle_specs) -> list:
    """Emit the `plan_stage_entered {slug, from, to, delivered}` transition event + return the
    delivered bundle. The single transition-event emitter, used by `plan stage` AND the shims (so the
    journal shows the stage transition regardless of entry verb — AC1/AC2)."""
    delivered = _plan_stage_bundle_specs(to)
    data = {"slug": slug, "from": frm, "to": to, "delivered": delivered}
    if extra:
        data.update(extra)
    _append_event("plan_stage_entered", None, data)
    return delivered


def _print_plan_stage_delivery(stage: str, delivered: list) -> None:
    """SINGLE source for the plan-stage bundle delivery print (the `delivered` spec ids), shared by
    `cmd_plan_stage` (every transition) AND `cmd_plan_file` (draft-entry, T-0416) so the delivery
    print FORMAT has ONE home — no mirror/copy of the print block (audit-pre F0). The slug→stage
    header line + the per-stage work-items pointer stay caller-local (they are transition-specific)."""
    if delivered:
        print(f"read before acting (fetch via `yitc-v2 graph query <SPEC>`): {', '.join(delivered)}")
    else:
        print(f"no spec bound to plan-stage-entry:{stage} (per-stage detail lands with the "
              f"\"Plan lifecycle\" spec, T-0317).")


def _plan_accept_core(path: Path, fm: dict, body: str, slug: str, *, AUDIT_VERDICT_CLOSURE_OK, DECISIONS_DIR, REPO_ROOT, _birth_plan_draft_specs, _die, _plan_accept_freshness_hash, _plan_content_hash, _read_yaml):
    """Shared accept-gate + spec-birth (T-0316; was the cmd_plan_accept body). The FRESH GREEN/YELLOW
    `plan check` gate (content-hash freshness, mirror of `decision accept`) + birth the plan's draft
    specs (proposed_by==slug) → `proposed` (T-0192 Part B), BEFORE the caller flips status (resumable,
    idempotent). Caller-loaded (path/fm/body) — does NOT validate the FROM status nor write the TO
    status; the caller owns the FSM edge (cmd_plan_accept: draft→accepted shim; cmd_plan_stage:
    specs→accepted). Returns (verdict, specs_born, structural, event_data)."""
    audit_path = DECISIONS_DIR / f"{slug}-audit.yaml"
    if not audit_path.exists():
        _die(f"{slug}: no `plan check` verdict on record — run `yitc-v2 plan check {slug}` first "
             "(accept is gated on a fresh GREEN/YELLOW check, mirroring `decision accept`).")
    av = _read_yaml(audit_path) or {}
    # T-0348 — canonical shape ONLY (P5/SPEC-0036): a legacy draft:/kind: draft-check verdict is
    # stale by construction (the shape is retired; no second-format fallback reader survives).
    if av.get("target_kind") != "plan" or av.get("target_id") != slug:
        _die(f"{slug}: the recorded `plan check` verdict is not in the canonical plan-audit schema "
             f"(target_kind: plan / target_id) — the legacy draft-check shape is retired (T-0348). "
             f"Re-run `yitc-v2 plan check {slug}`.")
    verdict = str(av.get("verdict") or "").upper()
    if verdict not in AUDIT_VERDICT_CLOSURE_OK:   # GREEN | YELLOW
        _die(f"{slug}: last `plan check` verdict is {verdict or 'MISSING'} — accept needs GREEN/YELLOW. "
             f"Rework the plan, then re-run `yitc-v2 plan check {slug}`.")
    checked_hash = av.get("content_hash")
    cur_hash = _plan_content_hash(body)
    if not checked_hash:
        _die(f"{slug}: the recorded check predates content-hash freshness — re-run `yitc-v2 plan check {slug}`.")
    if checked_hash != cur_hash:
        _die(f"{slug}: plan edited since the check (content hash mismatch) — the verdict is stale. "
             f"Re-run `yitc-v2 plan check {slug}` before accept.")
    # T-0332 — the accept-gate audit must cover the PLAN-BORN draft specs vs the active+proposed
    # corpus, and the draft→proposed BIRTH is gated on a check whose freshness reflects the draft
    # specs + corpus CONTENT. Editing a draft spec (or a corpus spec) after the check stales the
    # gate (AC2) — so a draft spec is never born `proposed` without a fresh corpus-coherence audit.
    # A check predating this field (recorded before T-0332) is stale by construction — re-run.
    checked_accept = av.get("accept_freshness_hash")
    cur_accept = _plan_accept_freshness_hash(slug, body, fm)   # SPEC-0082 — same fm-aware basis the check recorded
    if checked_accept != cur_accept:
        _die(f"{slug}: the accept-gate audit no longer covers the current draft specs / corpus "
             f"(a draft spec or an active/proposed corpus spec changed since `plan check`, or the "
             f"check predates the draft-spec corpus audit). The draft→proposed birth needs a FRESH "
             f"GREEN/YELLOW check that audited THESE draft specs against the live corpus — re-run "
             f"`yitc-v2 plan check {slug}` before accept (T-0332).")
    specs_born = _birth_plan_draft_specs(slug)
    structural = av.get("structural_findings") or []
    event_data = {"slug": slug, "verdict_ref": str(audit_path.relative_to(REPO_ROOT)),
                  "checked_hash": cur_hash, "specs_born": specs_born,
                  "structural_findings_consumed": len(structural)}
    return verdict, specs_born, structural, event_data


def _plan_close_core(path: Path, fm: dict, body: str, slug: str, into: list,
                     resolution: str, deferred, note, by_record=False, soak_evidence=None, handoff=None, *, PLAN_SLUG_RE, _die, _link_plan_into_targets, _require_captures_routed, _require_plan_finalization_ready, _require_plan_retire_on_proof_resolved, _write_draft) -> dict:
    """Shared terminal-close side-effects (T-0316; was the cmd_plan_close body): the `realized`
    finalization gate (T-0193 aggregate `audit post --plan`), the `closed_into` write, the `partial`
    --deferred remainder, and the AC4 reverse-link (`_link_plan_into_targets`). Caller-loaded; does NOT
    validate the FROM status (caller owns the edge). Writes fm+file. Returns the `draft_closed` payload.

    T-9369 (SPEC-0034 §Realized-by-record): when `by_record`, the `realized` close substitutes the
    build-oriented finalization gate (the aggregate `audit post --plan` that REDs on no-work-left, for a
    plan whose prototype soaked + handed-off OUTSIDE its own decomposition) with the REQUIREMENT of
    EXISTING soak-proof + handoff evidence (`soak_evidence` + `handoff`, both non-empty). The evidence
    requirement IS the gate — it is NOT loosened for an unproven plan (AC2)."""
    if resolution == "realized" and by_record:
        se, ho = (soak_evidence or "").strip(), (handoff or "").strip()
        if not se or not ho:
            _die("plan stage realized --by-record requires BOTH --soak-evidence <ref> AND --handoff "
                 "<ref> — the EXISTING soak-proof + handoff that substitute for the build-oriented "
                 "finalization gate (SPEC-0034 §Realized-by-record, T-9369). Without that evidence the "
                 "shortcut is REFUSED — take the normal FSM path (the gates are not loosened for an "
                 "unproven plan).")
        fm["realized_by"] = "record"
        fm["soak_evidence"] = se
        fm["handoff"] = ho
    elif resolution == "realized":
        _require_plan_finalization_ready(slug, body)   # T-0193 plan-finalization gate (Part B)
        _require_plan_retire_on_proof_resolved(slug)   # T-0326 realized-EXIT gate: old retired (done)
        _require_captures_routed(slug)                 # T-0327 realized-EXIT gate: captures routed
    if resolution == "partial":
        deferred = (deferred or "").strip()
        if not deferred:
            _die("--deferred <new-draft-slug> required when --resolution partial "
                 "(the remainder lives on as a NEW draft, not an idea — D-0034)")
        if not PLAN_SLUG_RE.match(deferred):
            _die(f"--deferred slug must be kebab-case; got {deferred!r}")
    fm["status"] = resolution
    fm["closed_into"] = into
    data = {"slug": slug, "resolution": resolution, "closed_into": into}
    if resolution == "realized" and by_record:
        data["realized_by"] = "record"
        data["soak_evidence"] = fm["soak_evidence"]
        data["handoff"] = fm["handoff"]
    if resolution == "partial":
        fm["deferred"] = deferred
        data["deferred"] = deferred
    if note:
        fm["close_note"] = note
    _write_draft(path, fm, body)
    reverse_linked = _link_plan_into_targets(slug, into)
    data["reverse_linked"] = reverse_linked
    return data


def _require_plan_decomposition_ready(slug: str, fm: dict, body: str, *, AUDIT_VERDICT_CLOSURE_OK, DECISIONS_DIR, SPEC_ABANDONED_TERMINAL, _die, _plan_content_hash, _plan_specs, _read_yaml) -> None:
    """The `accepted → decomposition` entry gate (RELOCATED from the `executing` gate by SPEC-0070 §9.3 —
    was `_require_plan_executing_ready`): refuse (nonzero, with a reason) unless (a) a FRESH GREEN/YELLOW
    `plan check`, (b) `implementation_plan` composed (non-empty), and (c) the plan's specs are `proposed`
    (born). The plan analog of task audit-pre validating the implementation plan + the proposed specs
    (not the bare idea). A task-only plan (no proposed_by specs) passes (c) vacuously — there are no specs
    to require (backward-compat). The MANDATORY big-plan check (LARGE plans) rides on the fresh-`plan
    check` requirement, so it RELOCATES here transitively (SPEC-0070 §F3) — the cut (decomposition) is the
    TEXT boundary the big-plan map audit belongs at, before the cards exist.

    T-0627: clause (c) EXEMPTS a corpus spec in a DELIBERATE never-active terminal
    (`SPEC_ABANDONED_TERMINAL` = withdrawn/rejected) — a plan-born spec deliberately abandoned (a
    scope-cut tracked as a follow-up) must not block the plan's own lifecycle, symmetric with
    the postcheck `_plan_postcheck_exempt_specs` exemption. NARROW: only those two; a `draft` (un-born)
    or `superseded`/`retired` corpus spec still BLOCKS, as before."""
    audit_path = DECISIONS_DIR / f"{slug}-audit.yaml"
    if not audit_path.exists():
        _die(f"{slug}: `plan stage decomposition` needs a fresh GREEN/YELLOW `plan check` — none on record. "
             f"Run `yitc-v2 plan check {slug}`.")
    av = _read_yaml(audit_path) or {}
    # T-0348 — canonical shape ONLY (P5/SPEC-0036): mirror of the accept-gate shape guard.
    if av.get("target_kind") != "plan" or av.get("target_id") != slug:
        _die(f"{slug}: the recorded `plan check` verdict is not in the canonical plan-audit schema "
             f"(target_kind: plan / target_id) — the legacy draft-check shape is retired (T-0348). "
             f"Re-run `yitc-v2 plan check {slug}`.")
    verdict = str(av.get("verdict") or "").upper()
    if verdict not in AUDIT_VERDICT_CLOSURE_OK:
        _die(f"{slug}: `plan check` verdict is {verdict or 'MISSING'} — decomposition needs GREEN/YELLOW.")
    checked_hash = av.get("content_hash")
    if not checked_hash or checked_hash != _plan_content_hash(body):
        _die(f"{slug}: `plan check` is stale (content-hash mismatch) — re-run `yitc-v2 plan check {slug}`.")
    ip = fm.get("implementation_plan")
    if not (ip and str(ip).strip()):
        _die(f"{slug}: implementation_plan is empty — compose the decomposition map (the acceptance-stage "
             f"output) into the plan frontmatter before `plan stage decomposition`.")
    not_proposed = [sid for sid, stt in _plan_specs(slug)
                    if stt not in ("proposed", "active") and stt not in SPEC_ABANDONED_TERMINAL]
    if not_proposed:
        _die(f"{slug}: these specs are not yet proposed: {', '.join(not_proposed)} — births happen at "
             f"`plan stage accepted`. Run it first. (A deliberately withdrawn/rejected corpus spec is "
             f"EXEMPT and does NOT appear here — T-0627; a draft/superseded/retired one still blocks.)")


_SPEC_ID_RE = re.compile(r"^SPEC-\d{4}$")


_SURFACE_PAREN_ANNOTATION_RE = re.compile(r"\s+\(.*\)$")
_SURFACE_DASH_ANNOTATION_RE = re.compile(r"\s+[—–-]\s+(?P<tail>\S+\s+\S.*)$")
_SURFACE_FILENAME_TAIL_RE = re.compile(r"\.[A-Za-z0-9]{1,6}$")


def _surface_key(entry: str) -> str:
    """The NAMED SURFACE an `expected_touch` entry addresses: the PATH part, i.e. the text before the
    optional `#<symbol>` anchor (the `<file>` / `<file>#<symbol>` address space the graph resolves),
    with any trailing ANNOTATION normalized off. Grouping on the path part is deliberate — the X-0593
    incident's two cards named ONE surface at DIFFERENT granularity, so keying on the whole entry
    would miss exactly the shape under test.

    T-10825 (kupiclub X-0679): annotating an entry is established card practice
    (`tests/config_acceptance.py (new cases)`, `bin/lib/journal.py — the liveness fold`), and keying
    on the annotated text made the annotated entry a DIFFERENT surface from its bare form — so a
    genuinely shared surface reported NO overlap and the auditor's shared-surface context went
    silently empty (kupiclub T-0158 vs T-0159, one gate pass burned on that blindness).

    The stripping is deliberately CONSERVATIVE — over-stripping would COLLAPSE distinct surfaces,
    which is the same blindness in the other direction. Only two tails are annotations:

    - a parenthetical that CLOSES at end-of-string — so `docs/foo (bar).md`, whose paren is mid-NAME,
      is left whole;
    - a spaced dash (em/en/hyphen) followed by PROSE: at least two words AND not ending in a
      filename-style extension — so `docs/foo - bar.md` and `docs/foo - bar baz.md` are left whole
      (a dashed FILENAME ends in its extension), while `bin/lib/journal.py — the liveness fold`
      strips.

    Anything else — including an entry with plain internal spaces, e.g. `bin/yitc-v2 graph build` —
    keys unchanged."""
    path = str(entry).split("#", 1)[0].strip()
    path = _SURFACE_PAREN_ANNOTATION_RE.sub("", path)
    m = _SURFACE_DASH_ANNOTATION_RE.search(path)
    if m and not _SURFACE_FILENAME_TAIL_RE.search(m.group("tail")):
        path = path[:m.start()]
    return path.strip()


def _plan_shared_surfaces(cards: list, *, SPECS_DIR, _read_yaml) -> str:
    """T-10751 (X-0593) — the SET-LEVEL shared-surface view over a cut, for the gate-executing fidelity
    prompt (SPEC-0036 P5 set-level semantic-coherence bullet).

    Card-level fidelity was checked; SET-level semantic coherence over a shared surface was not — so two
    independently well-formed, correctly-ordered cards from ONE cut could land CONTRADICTORY semantics
    for the same surface, and the contradiction surfaced only at the merge land verify with both sides
    already built (boomrocket 2026-07-24, T-0384 vs T-0388 — prod-absent proposal deltas, one
    attempt-keyed, one record-keyed). Under parallel dispatch independent workers cannot see each
    other's semantics, so nothing but a set-level view can catch it.

    Pure over the ALREADY-read card dicts: groups every card's `expected_touch` by `_surface_key` and
    reports each surface named by >=2 DISTINCT cards, with the cards' COMMON `cites:` SPEC-ids RESOLVED
    against the corpus — only an EXISTING + `status: active` spec is rendered `(active)`; a non-active
    one carries its status and an unresolvable id reads `(missing)`, so a draft/absent cite can never
    read as the governing definition. Empty overlap emits an EXPLICIT no-overlap line (checked-and-clean
    must be distinguishable from not-computed). REPORT-ONLY: this is auditor CONTEXT, never a gate — and
    exception-tolerant, since a render helper must never crash a MANDATORY-BLOCKING gate.

    NOT in `_plan_card_set_fingerprint`: this view is DERIVED from `expected_touch` + `cites:`, both
    already in the freshness basis (T-10388 / SPEC-0070 §4), so a post-audit edit already stales the
    verdict — hashing the derived value too would be a second truth (CHARTER §P5)."""
    try:
        by_surface = {}
        for c in cards:
            tid = c.get("id") or "?"
            for entry in (c.get("expected_touch") or []):
                key = _surface_key(entry)
                if not key:
                    continue
                by_surface.setdefault(key, {}).setdefault(tid, []).append(str(entry).strip())
        shared = sorted((k, v) for k, v in by_surface.items() if len(v) >= 2)
        head = ("## Shared surfaces — 2+ cut cards name the SAME surface "
                "(SPEC-0036 P5 set-level semantic coherence; X-0593)")
        if not shared:
            return head + "\n(no surface is named by more than one card in this cut)"
        cites_by_tid = {(c.get("id") or "?"): {str(x).strip() for x in (c.get("cites") or [])}
                        for c in cards}
        out = [head]
        for key, holders in shared:
            tids = sorted(holders)
            named = "; ".join(f"{t}: {holders[t]}" for t in tids)
            common = set.intersection(*[cites_by_tid.get(t, set()) for t in tids]) if tids else set()
            rendered = []
            for sid in sorted(s for s in common if _SPEC_ID_RE.match(s)):
                p = next(SPECS_DIR.glob(f"{sid}-*.yaml"), None) or (SPECS_DIR / f"{sid}.yaml")
                d = (_read_yaml(p) if (p and p.exists()) else None)
                if not isinstance(d, dict):
                    rendered.append(f"{sid} (missing)")
                    continue
                st = str(d.get("status") or "?")
                rendered.append(f"{sid} (active)" if st == "active" else f"{sid} (status: {st})")
            governs = (", ".join(rendered) if any(r.endswith("(active)") for r in rendered)
                       else ("(no ACTIVE governing spec cited in common — the cut does not say which "
                             "definition governs)" + (f" [non-active cites: {', '.join(rendered)}]"
                                                      if rendered else "")))
            out.append(f"- surface `{key}` — named by {', '.join(tids)} ({named})\n"
                       f"    governing spec cited in common: {governs}")
        return "\n".join(out)
    except Exception:
        return ("## Shared surfaces — 2+ cut cards name the SAME surface "
                "(SPEC-0036 P5 set-level semantic coherence; X-0593)\n"
                "(shared-surface view unavailable — read the per-card expected_touch above)")


def _plan_spec_activation(cards: list, slug: str, *, SPECS_DIR, _read_yaml) -> str:
    """T-10918 (X-0707) — the PLAN-BORN PROPOSED-SPEC ACTIVATION view for the gate-executing fidelity
    prompt (SPEC-0036 P5 singular-activation bullet).

    P5 asks the auditor whether each `proposed` spec has EXACTLY ONE `activation_owner_task` — but in
    V2 that owner is a spec→task POINTER on the SPEC yaml, not a per-card field, so a CARD-ONLY
    rendering carries no evidence for the question at all. The auditor answered it from the only proxy
    in the prompt (each card's `cites:`) and reported "no card owns activation of SPEC-XXXX": a HIGH
    that was both FALSE (a spec DOES carry the pointer) and UNVERIFIABLE (nothing in the prompt could
    confirm or refute it). In a MANDATORY-BLOCKING gate that inflated the finding count AND burned one
    of the two ceiling passes that exist to resolve REAL findings — the compound cost X-0707 reports.
    Same defect class as T-10825 (kupiclub X-0679): an EMPTY auditor context read as a genuine absence.

    Renders every spec with `proposed_by == slug` — the SAME set `_plan_card_set_fingerprint` folds
    into its `spec_activation` basis, so the auditor sees exactly the linkage the freshness contract
    hashes — with its `activation_owner_task` ANNOTATED against the cut member-set: an owner that is a
    cut member reads `IN this cut`, an owner outside it reads `NOT a member of this cut`, and an absent
    pointer reads `UNOWNED` (the real defect shape). Zero plan-born proposed specs emits an EXPLICIT
    no-proposed-specs line — checked-and-clean MUST be distinguishable from not-computed, which is the
    whole defect being fixed here. REPORT-ONLY: auditor CONTEXT, never a gate — and exception-tolerant,
    since a render helper must never crash a MANDATORY-BLOCKING gate.

    NOT in `_plan_card_set_fingerprint`: this view is DERIVED from `proposed_by` +
    `activation_owner_task`, both ALREADY in the freshness basis (SPEC-0070 §4), so re-pointing an
    owner after the audit already stales the verdict — hashing the derived view too would be a second
    truth (CHARTER §P5). The exact reasoning `_plan_shared_surfaces` records for its own view."""
    head = ("## Proposed-spec activation — the plan-born specs and WHICH task activates each "
            "(SPEC-0036 P5 singular activation; X-0707)")
    try:
        cut_ids = {(c.get("id") or "?") for c in cards}
        rows = []
        for sp in state.scan_specs(SPECS_DIR):   # SPEC-* glob excludes _template.yaml
            d = _read_yaml(sp)
            if not isinstance(d, dict) or d.get("proposed_by") != slug:
                continue
            rows.append((str(d.get("id") or sp.stem), str(d.get("status") or "?"),
                         d.get("activation_owner_task")))
        if not rows:
            return (head + "\n(no spec is born of this plan — `proposed_by` names it on no spec in the "
                           "corpus, so the singular-activation question is ANSWERED-CLEAN here, not "
                           "unchecked: do NOT report a missing activation owner)")
        out = [head]
        for sid, status, owner in sorted(rows):
            if not owner:
                where = "NO activation_owner_task — UNOWNED"
            elif str(owner) in cut_ids:
                where = f"owner: {owner} — IN this cut"
            else:
                where = f"owner: {owner} — NOT a member of this cut"
            out.append(f"- {sid} (status: {status}) — {where}")
        return "\n".join(out)
    except Exception:
        return head + "\n(proposed-spec activation view unavailable — read the specs corpus directly)"


def _plan_card_set_context(slug: str, *, SPECS_DIR, TASKS_DIR, _plan_cut_cards, _read_yaml) -> str:
    """A compact, readable rendering of a plan's filed task CARD SET (the cut) for the gate-executing
    fidelity-audit prompt — so the auditor judges the CARDS-vs-plan (coverage / ordering / singular
    activation / probe quality / no reopened settled choice), not just the plan text. Read-only over
    `_plan_cut_cards(slug)` — the cut MEMBER-set via the `decomposed_from` marker, NOT `cites:` (T-0694):
    this is the SAME set `_plan_card_set_fingerprint` hashes, so the auditor judges exactly the
    fingerprinted cut and an informational `cites:`-only citer is never shown as a cut card.

    T-10751: the per-card blocks are followed by the SET-LEVEL shared-surface view
    (`_plan_shared_surfaces`) — the cross-card relation no per-card block can express (X-0593).

    T-10918: and then by the PROPOSED-SPEC ACTIVATION view (`_plan_spec_activation`) — the spec→task
    ownership pointer no CARD carries, so P5's singular-activation question had no evidence in the
    prompt at all and drew an unverifiable HIGH (X-0707)."""
    lines = []
    cards = []
    for tid, _st in _plan_cut_cards(slug):
        p = next(TASKS_DIR.glob(f"{tid}-*.yaml"), None) or (TASKS_DIR / f"{tid}.yaml")
        d = (_read_yaml(p) if (p and p.exists()) else {}) or {}
        status = d.get("status") or _st or "?"
        block = (
            f"- {tid} [{d.get('class','?')}] {d.get('title','')}\n"
            f"    status: {status}\n")
        # T-9608: a PARKED card is not-executable-now — surface its parked_reason +
        # return_trigger so the fidelity auditor does not RED-flag a correctly-parked
        # (e.g. grow-on-pull) card as 'executable now' (the false-coverage signal).
        if str(status) == "parked":
            block += (
                f"    parked_reason: {d.get('parked_reason') or ''}\n"
                f"    return_trigger: {d.get('return_trigger') or ''}\n")
        block += (
            f"    requires: {d.get('requires') or []}\n"
            f"    cites: {d.get('cites') or []}\n"
            f"    scope: {d.get('scope') or []}\n"
            # T-10388: surface expected_touch so the fidelity auditor can check the touch-forecast
            # is present + plausible on every cut card (SPEC-0036 P5 touch-forecast bullet). An empty
            # forecast on a decomposed card is a cut-fidelity gap (SPEC-0046 §Persist-blast-radius).
            f"    expected_touch: {d.get('expected_touch') or []}\n"
            f"    acceptance: {d.get('acceptance') or []}")
        lines.append(block)
        cards.append({"id": tid, "expected_touch": list(d.get("expected_touch") or []),
                      "cites": list(d.get("cites") or [])})
    if not lines:
        return "(no task cards filed for this plan)"
    return ("\n".join(lines) + "\n\n"
            + _plan_shared_surfaces(cards, SPECS_DIR=SPECS_DIR, _read_yaml=_read_yaml) + "\n\n"
            + _plan_spec_activation(cards, slug, SPECS_DIR=SPECS_DIR, _read_yaml=_read_yaml))


def _require_plan_decomposition_fidelity(slug: str, fm: dict, body: str,
                                         *, owner_reset: bool = False, AUDIT_VERDICT_CLOSURE_OK, DECISIONS_DIR, _die, _plan_card_set_context, _plan_card_set_fingerprint, _plan_cut_cards, _read_yaml, _run_plan_gate_audit) -> None:
    """The `decomposition → executing` entry gate (SPEC-0070 §3/§4 — the NEW mandatory gate added by
    T-0649): entry to `executing` REQUIRES a FRESH GREEN/YELLOW external **decomposition-fidelity**
    verdict over the task CARD SET whose recorded `card_set_fingerprint` MATCHES the current cut.

    - A fresh matching verdict already on record → REUSE it (no re-invocation — the cut is unchanged).
    - Else RUN the gate-executing fidelity audit (the `_run_plan_gate_audit` family under the NEW
      `gate-executing` / mandatory-blocking template, SPEC-0070 §3): it records the verdict + the
      card-set fingerprint and FAILS CLOSED on RED/ABORT/missing-template (the build-order window before
      T-0650 ships the P5 prose — the SAFE direction). A post-run re-check requires GREEN/YELLOW with a
      matching fingerprint, else refuse (stale-cut / mismatch).
    Editing any card after a GREEN verdict re-fingerprints the cut → no longer matches → re-audit
    (the freshness contract, the direct analog of the accept-gate `_plan_content_hash`)."""
    fp = _plan_card_set_fingerprint(slug)
    audit_path = DECISIONS_DIR / f"{slug}-audit-gate-executing.yaml"
    av = (_read_yaml(audit_path) or {}) if audit_path.exists() else {}
    if (str(av.get("verdict") or "").upper() in AUDIT_VERDICT_CLOSURE_OK
            and av.get("card_set_fingerprint") == fp):
        return   # fresh GREEN/YELLOW verdict bound to THIS exact cut — reuse, no re-audit
    # T-9755: about to RUN the fidelity audit — first diagnose the EMPTY cut member-set. An empty set
    # means no task card carries `decomposed_from == slug` (the common author mistake: cutting cards
    # without the marker — the member-set is decomposed_from-keyed, NOT cites:, SPEC-0070 §5 / T-0694).
    # Sending an empty card-set to the fidelity auditor reads as a generic fidelity RED and costs a
    # wasted audit pass (a 2-pass ceiling burn); short-circuit it here at zero audit cost with the
    # likely cause named. Placed AFTER the fresh-verdict reuse-return (not before the fingerprint): a
    # real empty cut can never hold a legit GREEN to reuse, so only the audit-RUN path needs the hint —
    # and the isolation tests that pre-record a verdict over an empty set keep their reuse-path pass.
    if not _plan_cut_cards(slug):
        # T-11091 (kupiclub X-0866): name a REACHABLE repair for BOTH states. The original text named
        # only the filing-time route — unreachable once the cards exist, since re-filing an already-cut
        # set means duplicate cards, wont-do records, and renumbering ids the cards require each other
        # by. Read as prescriptive, it sent an author either to that cost or to a hand-edit of the
        # YAMLs. The post-filing repair is the governed field-edit (SPEC-0070 §5), so say so here.
        _die(f"{slug}: `plan stage executing` blocked — the decomposition cut member-set is EMPTY "
             f"(no task card carries `decomposed_from: {slug}`).\n"
             f"  - Cut cards NOT filed yet? File them with `task file --decomposed-from {slug}` "
             f"(or `decomposed_from: {slug}` in stdin YAML).\n"
             f"  - Cards ALREADY filed without the marker? Do NOT re-file them — repair each in "
             f"place with the governed field-edit, e.g.\n"
             f"      yitc-v2 task update T-XXXX --old 'cites:' "
             f"--new 'decomposed_from: {slug}\\ncites:'\n"
             f"    (any adjacent unique line works — `--new` may SUPERSET `--old`, which is how it "
             f"ADDS an absent key). The marker is dangling-checked and the write emits "
             f"`task_amended` naming the plan, so the repair is visible across sessions.\n"
             f"The cut member-set is keyed on `decomposed_from`, NOT `cites:` (SPEC-0070 §5).")
    # run the gate-executing fidelity audit over the CARD SET (mandatory-
    # blocking: dies on RED/ABORT or — until T-0650 — a missing template; the safe fail-closed window).
    _run_plan_gate_audit(slug, fm, body, "gate-executing", "mandatory-blocking",
                         blocking=True, card_set_fp=fp, extra_context=_plan_card_set_context(slug),
                         owner_reset=owner_reset)
    av = (_read_yaml(audit_path) or {}) if audit_path.exists() else {}
    if (str(av.get("verdict") or "").upper() not in AUDIT_VERDICT_CLOSURE_OK
            or av.get("card_set_fingerprint") != fp):
        _die(f"{slug}: `plan stage executing` blocked — no fresh GREEN/YELLOW decomposition-fidelity "
             f"verdict matching the current card-set fingerprint (SPEC-0070 §3/§4). Settle the cut, then "
             f"re-run the gate-executing fidelity audit.")


def _plan_postcheck_exempt_specs(slug: str, *, SPECS_DIR, _plan_retire_on_proof, _plan_specs, _read_yaml) -> frozenset:
    """T-0342 — the postcheck-ENTRY spec-exemption set: plan-corpus specs that are `proposed`-
    awaiting-activation DURING the soak BY DESIGN, so demanding them `active` at entry deadlocks
    (the 2026-06-05 case: SPEC-0035 `proposed`, its `activation_owner_task` T-0339 parked-with-
    return_trigger — and T-0339 closes, flipping the spec `proposed→active`, only DURING postcheck).

    A corpus spec (`_plan_specs` — the ONE corpus builder, P5) is exempt iff BOTH hold:
      (1) its `activation_owner_task` is in the PARKED retire-on-proof subset
          (`{tid for tid,stt in _plan_retire_on_proof(slug) if stt=="parked"}`) — the EXACT SAME set
          the T-0326 task-done exemption keys on (`_require_plan_postcheck_ready` below). Symmetry is
          deliberate: a non-parked retire-on-proof carrier (e.g. moved parked→ready, not yet done)
          STILL blocks ENTRY as a task, so exempting its spec while the task itself blocks would be
          incoherent. NOT the full `_plan_retire_on_proof` set (audit-pre F1).
      (2) the spec status is `proposed` — an exempted-carrier spec in ANY other state still BLOCKS
          (it falls out of the exempt set, so the active-state demand still applies). Only the
          designed proposed-awaiting-activation state passes.
    Reads `activation_owner_task` straight from the spec YAML (the SPEC-0005 §5 activation carrier)."""
    parked_retire = {tid for tid, stt in _plan_retire_on_proof(slug) if stt == "parked"}
    if not parked_retire:
        return frozenset()
    exempt = set()
    corpus_ids = {sid for sid, _st in _plan_specs(slug)}   # only specs the plan realizes (P5 corpus)
    for p in state.scan_specs(SPECS_DIR):   # SPEC-* glob excludes _template.yaml
        d = _read_yaml(p)
        if not isinstance(d, dict):
            continue
        sid = d.get("id") or p.stem
        if sid not in corpus_ids:
            continue
        if d.get("status") == "proposed" and d.get("activation_owner_task") in parked_retire:
            exempt.add(sid)
    return frozenset(exempt)


def _require_plan_postcheck_ready(slug: str, body: str, *, _die, _plan_postcheck_exempt_specs, _plan_retire_on_proof, _plan_tasks, _postcheck_probe_block_declared, _require_plan_finalization_ready, _require_verification_artifact) -> None:
    """The `postcheck` ENTRY gate (governing plan §Stage model): all implementing tasks `done` EXCEPT
    the retire-on-proof ones, + the aggregate `audit post --plan` GREEN/YELLOW. A RETIRE-ON-PROOF task
    that is currently `parked` (a task LINKED to the plan by EITHER carrier — `decomposed_from` or
    `cites`, the `_plan_tasks` union (T-10952) — carrying a `return_trigger`, T-0326) does NOT block ENTRY:
    postcheck IS the real-data soak that PROVES the new mechanism, and retiring the OLD is EXIT payload
    (the `realized` gate requires those tasks resolved — `_require_plan_retire_on_proof_resolved`). The
    exemption is the EXACT parked subset of `_plan_retire_on_proof` (the same set the EXIT gate keys
    on) — an unrelated plain `parked` linked task (no `return_trigger`) STILL blocks entry (audit-pre F1).
    REUSES `_require_plan_finalization_ready` (the existing aggregate-audit gate: specs active + fresh
    GREEN/YELLOW `audit post --plan` + task-carrier match — spec-bearing only; task-only plans auto-skip
    it) PLUS this explicit all-done-except-retire-on-proof check so a task-only plan still requires its
    active implementing tasks done. The SPEC side of the same entry-vs-exit model (T-0342): the
    finalization call is passed `_plan_postcheck_exempt_specs` so a retire-on-proof CARRIER spec
    (`proposed`, `activation_owner_task` ∈ the parked subset) is NOT required `active` at ENTRY — it
    activates DURING the soak when its carrier closes; the EXIT call (`_plan_close_core`) passes no
    exemption, so the FULL specs-active requirement holds at `realized` (fail-closed).

    T-0598 — verification-artifact-exists readiness (SPEC-0059 §contract leg 2b, PLAN axis): postcheck IS
    the real-data soak whose exit is judged against the plan's realization-exit (the postcheck probe
    block), so that artifact must EXIST entering postcheck. Reuses `_postcheck_probe_block_declared` —
    the SAME presence computation the T-0483 view surfaces, now GATED (the task scope: «today only
    SURFACED by the view, not gated»). The `plan file` skeleton seeds the probe-block prompt, so a
    normally-filed plan passes; this refuses a plan whose realization-exit was never authored / deleted."""
    _require_verification_artifact(
        _postcheck_probe_block_declared(body), verb="plan stage postcheck", stage="postcheck", tid=None,
        missing_label="realization_exit",
        message=(f"{slug}: the plan body declares NO realization-exit ({REALIZATION_EXIT_SECTION}) — postcheck "
                 f"is the real-data soak judged against it, so it must be PRESENT entering postcheck "
                 f"(verification-artifact-exists readiness, SPEC-0059 §universal-stage-contract leg 2b; "
                 f"composed up front at `accepted` per SPEC-0034). FILL the seeded "
                 f"`## {REALIZATION_EXIT_SECTION}` section (observed / min-runs / failure-threshold / "
                 f"evidence-home) in plans/{slug}.md — a legacy `## Postcheck probe block` section also "
                 f"counts — then re-run `yitc-v2 plan stage postcheck {slug}`."))
    exempt = {tid for tid, stt in _plan_retire_on_proof(slug) if stt == "parked"}
    # T-0384: a TERMINAL wont-do cited task can never become done — blocking on it deadlocks the plan
    # FSM permanently (the T-0377 owner-reroute incident; deviation
    # plan-postcheck-gate-deadlocks-on-wont-do-cited-task). Excluded as a blocker but REPORTED
    # (observable, never silent); scope honesty stays with the REQUIRED aggregate `audit post --plan`
    # half of this same gate below — it reads the corpus + reasons, so a wont-do that genuinely means
    # unrealized scope still fails the audit half. ENTRY-ONLY by construction: this helper has exactly
    # one call site (the `postcheck` branch of cmd_plan_stage); the realized EXIT path runs
    # _plan_close_core and never this helper.
    wont_do = sorted(tid for tid, stt in _plan_tasks(slug) if stt == "wont-do")
    if wont_do:
        print(f"{slug}: postcheck entry — excluding TERMINAL wont-do cited task(s): {', '.join(wont_do)} "
              f"(can never become done; scope honesty held by the aggregate `audit post --plan`)")
    not_done = [tid for tid, stt in _plan_tasks(slug)
                if stt not in ("done", "wont-do") and tid not in exempt]
    if not_done:
        _die(f"{slug}: these implementing tasks are not done: {', '.join(not_done)} — `postcheck` entry "
             f"requires all linked tasks (decomposed_from:{slug} or cites:{slug}) done EXCEPT parked "
             f"retire-on-proof tasks "
             f"(parked + return_trigger), which are postcheck-EXIT payload, not an entry prerequisite "
             f"(T-0326), and EXCEPT terminal wont-do tasks (T-0384 — reported above, judged by the "
             f"aggregate audit).")
    # T-0342: exempt the retire-on-proof CARRIER specs (proposed, activation_owner_task ∈ the parked
    # retire-on-proof subset) from the specs-active demand — they activate DURING the soak by design,
    # so requiring `active` at ENTRY deadlocks (the same model as the task exemption above, spec side).
    # The realized EXIT call (`_plan_close_core`) passes NO exemption → full specs-active at exit.
    _require_plan_finalization_ready(slug, body, exempt_specs=_plan_postcheck_exempt_specs(slug))


def _require_plan_retire_on_proof_resolved(slug: str, *, _die, _retire_on_proof_unresolved) -> None:
    """T-0326 — the `realized` EXIT gate half of the entry-vs-exit postcheck task model. `realized` =
    the NEW mechanism PROVEN (real-data soak) AND the OLD mechanism RETIRED; so every RETIRE-ON-PROOF
    linked task (`_plan_retire_on_proof` — a task linked by `decomposed_from` OR `cites` (T-10952)
    carrying a `return_trigger`) MUST be RESOLVED to
    a TERMINAL close — `done` OR `wont-do` (T-0613: a legitimately-abandoned retire-on-proof task is as
    resolved as a done one; the old mechanism is retired either way). Keyed on the retire-on-proof SET
    being terminal, NOT on still-being-`parked` (audit-pre F2: a retire-on-proof task moved
    parked→ready/blocked but not finished would otherwise slip the gate). The postcheck ENTRY gate
    deliberately ALLOWS these open while parked (they soak during postcheck) — this is the EXIT half that
    requires them complete. Uses the single-source `_retire_on_proof_unresolved` predicate (P5 — byte-for-
    byte parity with the postcheck-readiness lens). Called ONLY on the `realized` close path
    (`_plan_close_core`), NOT inside the entry-shared `_require_plan_finalization_ready`."""
    unresolved = _retire_on_proof_unresolved(slug)
    if unresolved:
        ids = ", ".join(f"{tid} (status={stt})" for tid, stt in unresolved)
        _die(f"{slug}: cannot close realized — these retire-on-proof tasks are not terminal "
             f"(done|wont-do): {ids}. `realized` = the new mechanism proven AND the old retired; "
             f"resolve them to a terminal close (`done`, or `wont-do` if the retirement is abandoned) "
             f"before close.")


def _require_captures_routed(slug: str, *, EVENTS_PATH, _last_triage_watermark, _scan_captures) -> None:
    """T-0327 — the THIRD `realized` EXIT-gate clause: "captures routed". DEMOTED TO AN ADVISORY WARN
    by T-0644 / Option B (owner-chosen): this clause now REPORTS, it does NOT block. (Name kept for
    continuity — renaming would dangle the SPEC-0055 §watermark-consumer reference + the view-YAML refs;
    the function ADVISES, it no longer requires.)

    A plan's `realized` close is its postcheck retrospective at corpus altitude (the owner's "after a big
    block, run a retrospective and ROUTE the outputs" discipline); routing the captured outputs is still
    the recommended discipline, so this WARNs while un-routed `deviation_captured` events exist since the
    last triage watermark — the GLOBAL backlog (the same since-last-watermark sweep `triage run` reports,
    NOT a plan-corpus filter: the whole backlog stays the scope, no new filter — B does NOT scope per-plan).
    But it PROCEEDS: the report-not-block norm (D-0040 / CHARTER non-goal #7 — no behavioral-discipline
    gates). WHY the demote (T-0644): as a HARD block this clause wired a per-plan realize criterion to the
    shared since-watermark firehose of ALL sessions, so an unrelated session's capture re-blocked every
    postcheck plan (never stably empty) and an event-only/no-action capture could only be cleared by a
    blind global watermark sweep. Advisory keeps the un-routed COUNT visible without those failure modes.
    Remediation (still advised, not required): route via `triage run` then record the watermark with
    `triage run --complete`.

    READS the EXISTING watermark + deviation journal ONLY — `_last_triage_watermark` + `_scan_captures`,
    the SAME two helpers `triage run` uses; no new store/verb/format/detector. The window predicate
    MIRRORS `cmd_triage_run` EXACTLY (`ts > prior`, the watermark a CLOSED boundary, D-0086/T-0152) so the
    advisory count matches the window `triage run --complete` drains (the boundary-tie surfacing stays
    informational — unchanged). Called ONLY on the `realized` close path (`_plan_close_core`), AFTER the
    finalization + retire-on-proof gates."""
    prior = _last_triage_watermark(EVENTS_PATH)
    unrouted = [c for c in _scan_captures(EVENTS_PATH)
                if c["type"] == "deviation_captured" and (prior is None or c["ts"] > prior)]
    if unrouted:
        sys.stderr.write(
            f"WARN: {slug} realizing with {len(unrouted)} un-routed deviation_captured event(s) since "
            f"the last triage watermark ({prior or 'bootstrap — journal start'}) — route or accept. "
            f"`realized` is the plan's postcheck retrospective at corpus altitude; routing the captured "
            f"outputs first is the recommended discipline (`yitc-v2 triage run` to see the routes: "
            f"errors/E-XXXX · spec-amending task · spec edit · ideas/ · MEMORY.md — SPEC-0034 routing "
            f"table; then `yitc-v2 triage run --complete`). Transition PROCEEDS (non-blocking advisory, "
            f"T-0644 / Option B; the un-routed count is reported, not gated).\n")


def cmd_plan_stage(args: argparse.Namespace, *, DECISIONS_DIR, PLANS_DIR, REPO_ROOT, PLAN_STAGE_SEQUENCE, PLAN_STATUSES, _append_event, _commit_worktree, _die, _emit_plan_stage_entered, _find_decision_yaml, _find_task_yaml, _in_writing_worktree, _load_draft, _plan_accept_core, _plan_close_core, _plan_draft_finalized_fresh, _plan_next_stage, _plan_stage_bundle_specs, _postcheck_probe_block_declared, _print_plan_stage_delivery, _read_yaml, _require_plan_decomposition_fidelity, _require_plan_decomposition_ready, _require_plan_postcheck_ready, _require_reads, _require_verification_artifact, _require_writing_worktree, _run_plan_gate_audit, _split_into, _write_draft, _is_consumer_build=None) -> None:
    """`plan stage <NAME> <slug>` (T-0316) — the authoritative gated plan-lifecycle transition verb,
    mirroring `task stage` on ONE `status` field. On each call it (a) GATES the target stage's entry
    (= the prior stage's completion), (b) runs the stage's side-effects, (c) writes status=<NAME>,
    (d) DELIVERS the stage bundle (`plan-stage-entry:<NAME>` specs) + EMITS `plan_stage_entered`. It
    ABSORBS `plan accept` / `plan close --resolution` (their side-effects are branches here). A WRITE
    → runs in a writing worktree. Linear FSM (one step along PLAN_STAGE_SEQUENCE); the wont-do terminals
    partial/rejected/cancelled are reachable from any active stage."""
    # T-11249 (kupiclub X-0970) — SAY WHICH CHECKOUT THIS VERDICT RESTS ON, before anything else.
    # Diagnostic only, on stderr: every stdout contract stays byte-identical, and it sits beside
    # the sibling `# audit-loop ceiling:` notes. UNCONDITIONAL by design — the cost being removed
    # is the SILENCE, and a line that appears only when the engine already suspects a mismatch is
    # the same silence with extra steps. FIRST statement in the body, ahead of
    # `_require_writing_worktree()`: a wrong-tree invocation is exactly what that guard refuses,
    # so its refusal needs the tree named too.
    print(observe.checkout_provenance_line(REPO_ROOT, verb="plan stage"), file=sys.stderr)
    _require_writing_worktree()
    name = (args.name or "").strip()
    _owner_reset = bool(getattr(args, "owner_reset", False))   # T-9286 — plan-gate ceiling consult-governs
    _by_record = bool(getattr(args, "by_record", False))       # T-9369 — realized-by-record terminal
    if name not in PLAN_STATUSES:
        _die(f"plan stage: unknown stage {name!r} — must be one of {list(PLAN_STATUSES)} (the plan FSM).")
    path, fm, body = _load_draft(args.slug, dirs=(PLANS_DIR,))
    slug = fm.get("id") or args.slug
    cur = fm.get("status") or "draft"
    if cur in PLAN_TERMINAL:
        _die(f"{slug} status={cur!r} is terminal — no further `plan stage` transition.")
    # --- FSM edge validation ---
    if name in PLAN_NONLINEAR_TERMINALS:
        pass   # a wont-do terminal — reachable from any active stage (cur is non-terminal here)
    elif name == "accepted" and cur in ACCEPTED_PREDECESSORS:
        # TWO-BRANCH `accepted` entry-gate (T-0336, SPEC-0035 rules 1-2): `accepted` is reachable from
        # BOTH `trial` (a trial-eligible plan whose design CONVERGED on real data) AND `specs` (the SKIP
        # path — a non-eligible prose/docs plan; the UNCHANGED pre-trial live path). Eligibility is the
        # owner's judgement made at `trial` ENTRY (SPEC-0035 rule 2), NOT a stored flag/detector here
        # (SPEC-0035 rules 5/8 — no convergence detector, anti-cx). Both predecessors are accepted; the
        # ONLY other linear stages keep the strict one-step rule below.
        pass
    elif name == "realized" and _by_record:
        # T-9369 (SPEC-0034 §Realized-by-record): a trial/record plan whose prototype shipped + soaked +
        # handed-off OUTSIDE its own decomposition reaches `realized` from ANY active stage (like the
        # wont-do terminals) — bypassing the build-oriented finalization gate that REDs on no-work-left,
        # GATED on EXISTING soak-proof + handoff evidence (enforced in the side-effect branch below).
        # WITHOUT --by-record, `realized` stays the strict postcheck successor (the linear arm) — AC2.
        pass
    elif name in PLAN_STAGE_SEQUENCE:
        ci = PLAN_STAGE_SEQUENCE.index(cur) if cur in PLAN_STAGE_SEQUENCE else -1
        ti = PLAN_STAGE_SEQUENCE.index(name)
        if ti != ci + 1:
            nxt = PLAN_STAGE_SEQUENCE[ci + 1] if 0 <= ci < len(PLAN_STAGE_SEQUENCE) - 1 else "(none)"
            _die(f"{slug}: illegal transition {cur!r} → {name!r} — `plan stage` advances ONE step along "
                 f"{' → '.join(PLAN_STAGE_SEQUENCE)} (the verb gates the prior stage's completion; "
                 f"`accepted` additionally accepts the `specs → accepted` skip for non-trial-eligible "
                 f"plans — SPEC-0035 rules 1-2). The forward step from {cur!r} is {nxt!r}.")
    else:   # a terminal name not in the nonlinear set and not the linear `realized` successor path
        _die(f"{slug}: cannot enter {name!r} from {cur!r}.")
    # --- per-target gate + side-effects ---
    wrote = False
    legacy = None          # (event_type, data) — the legacy event the absorbed verb used to emit
    extra = {}             # extra fields folded into the plan_stage_entered event
    msg = ""
    if name == "specs":
        # T-0601 (R7) — the draft→specs transition is NON-SKIPPABLE: it requires the draft's END verb
        # (`plan draft --finalize`) to have run. TWO blocking legs, each journaling `read_gate_refused`,
        # mapping 1:1 to the acceptance ("REFUSES without a recorded SPEC-0043 AND SPEC-0034 read + a
        # draft-worked-through state"):
        #   (1) verification-exists (SPEC-0059 leg 2b) — a FRESH `plan_draft_finalized` journal proof
        #       whose body_hash matches the CURRENT body (only `plan draft --finalize` emits it, so the
        #       gate binds to the VERB's emission — not a forgeable field; audit-post HIGH). A body
        #       edited after finalize no longer hash-matches → no fresh proof → refuse.
        #   (2) read-check (SPEC-0042/0050) — the draft bundle [SPEC-0043, SPEC-0034] fetched this
        #       session. Closes the postcheck-to-realized incident (a START verb but no END verb).
        # Runs BEFORE the advisory gate-audit below — the blocking legs gate the transition first.
        fresh = _plan_draft_finalized_fresh(slug, body)
        _dwt_msg = (f"{slug}: no `plan draft --finalize` proof matching the CURRENT draft body — the "
                    f"draft's END verb has not run (or the body changed since it did, staling the proof). "
                    f"Run `yitc-v2 plan draft --finalize {slug}` first: it read-checks SPEC-0043 + "
                    f"SPEC-0034 and emits the body-bound plan_draft_finalized proof this gate requires "
                    f"(non-skippable; SPEC-0059 §First-stage-check-carrier-gap / SPEC-0034 §draft).")
        _require_verification_artifact(fresh, verb="plan stage specs", stage="specs", tid=None,
                                       missing_label="plan_draft_finalized", message=_dwt_msg)
        _require_reads("stage", {"axis": "plan", "stage": "draft", "verb": "plan stage specs",
                                 "action": "draft->specs transition"})
        # T-9282 — the P2 draft→specs entry-gate is MANDATORY-BLOCKING (gate policy home: SPEC-0083;
        # settles the former SPEC-0034 open question). Wired the SAME inline-blocking way as the
        # adjacent P3 gate-trial below: RED/ABORT HOLDS the transition (status unchanged); the
        # 2-pass audit-loop ceiling applies (ABORT burns no pass).
        gate_verdict = _run_plan_gate_audit(slug, fm, body, "gate-specs", "mandatory-blocking",
                                            blocking=True, owner_reset=_owner_reset)
        msg = (f"(draft specs being composed + checked; gate-specs MANDATORY-BLOCKING gate passed: "
               f"{gate_verdict} — SPEC-0083)")
    elif name == "trial":
        # T-0349 — the P3 specs→trial entry-gate template (SPEC-0036 §Gate policy:
        # MANDATORY-BLOCKING — RED/ABORT holds the transition; the 2-pass ceiling applies).
        _run_plan_gate_audit(slug, fm, body, "gate-trial", "mandatory-blocking", blocking=True,
                             owner_reset=_owner_reset)
        # `plan stage trial` (T-0336, SPEC-0035 rule 3): a trial-eligible plan enters controlled
        # real-data design-convergence. No status side-effect beyond the transition write + bundle
        # delivery (shared `_emit_plan_stage_entered`); the contract is to PROMPT the protocol-baking
        # step — before dwell-work, the plan MUST bake a `## Trial protocol` section so a fresh session
        # works from the PLAN alone (the resume-contract analog). Eligibility (SPEC-0035 rule 2) +
        # convergence (rule 5) are OWNER judgement — no detector here (rules 5/8, anti-cx).
        msg = ("(controlled real-data trial — SPEC-0035) — BEFORE dwell-work, bake a `## Trial protocol` "
               "section into the plan: mode + why (patterns/trial-methods.md), probe targets, exit "
               "criteria (the rule-5 floor + per-plan), safety envelope, eligibility rationale (rule 2b). "
               "A trial NEVER mutates production data (rule 4). Advance to `accepted` only when the design "
               "has CONVERGED against real data — owner judgement citing the journal run-refs (rule 5).")
    elif name == "accepted":
        # T-0598 — verification-artifact-exists readiness (SPEC-0059 §contract leg 2b, PLAN axis): the
        # realization-exit (postcheck probe block) is authored UP FRONT — «the way a task authors
        # `acceptance` at filing» — and COMPOSED at the accept-gate (SPEC-0034 §accepted). Gate it on
        # BOTH accept paths (trial→accepted + the specs→accepted skip), before `_plan_accept_core` births
        # the specs. Reuses `_postcheck_probe_block_declared` (the T-0483 view's presence computation,
        # now gated). A plan that FILLED the skeleton's `## Realization-exit criteria` section passes; an
        # untouched skeleton does NOT (T-10293 — its stub comment no longer satisfies the marker).
        _require_verification_artifact(
            _postcheck_probe_block_declared(body), verb="plan stage accepted", stage="accepted", tid=None,
            missing_label="realization_exit",
            message=(f"{slug}: the plan body declares NO realization-exit (postcheck probe block) — it must "
                     f"be COMPOSED at the accept-gate, the way a task authors `acceptance` at filing "
                     f"(verification-artifact-exists readiness, SPEC-0059 §universal-stage-contract leg "
                     f"2b; SPEC-0034 §accepted). FILL the seeded `## {REALIZATION_EXIT_SECTION}` section "
                     f"(observed / min-runs / failure-threshold / evidence-home) in plans/{slug}.md — a "
                     f"legacy `## Postcheck probe block` section also counts — then re-run "
                     f"`yitc-v2 plan stage accepted {slug}`."))
        if cur == "trial":
            # T-0349 — P4 trial-evidence requirement (SPEC-0036: MANDATORY-BLOCKING when a trial
            # ran; the P4 block JOINS the accept-gate `plan check` prompt). A trial→accepted needs
            # the recorded check to be the P4-bearing one (run AT trial status — stage_template:
            # gate-accepted). Freshness/verdict/shape stay enforced by _plan_accept_core below on
            # the SAME file (content_hash + accept_freshness_hash, T-0332).
            ap = DECISIONS_DIR / f"{slug}-audit.yaml"
            av = (_read_yaml(ap) or {}) if ap.exists() else {}
            if av.get("stage_template") != "gate-accepted":
                _die(f"{slug}: trial→accepted needs a FRESH `plan check` run AT trial status — it "
                     f"asks the P4 trial-evidence block (stage_template: gate-accepted; SPEC-0036 "
                     f"mandatory-blocking when a trial ran). On record: "
                     f"{av.get('stage_template') or 'no check'}. Run `yitc-v2 plan check {slug}`.")
        _verdict, specs_born, structural, ev = _plan_accept_core(path, fm, body, slug)
        legacy = ("plan_accepted", ev)
        extra = {"specs_born": specs_born}
        msg = (f"+ birthed {len(specs_born)} draft spec(s)→proposed: {', '.join(specs_born)}"
               if specs_born else "(no draft specs to birth)")
    elif name == "decomposition":
        # accepted → decomposition (SPEC-0070 §2): the RELOCATED executing-readiness gate (fresh plan
        # check + impl_plan + specs proposed; the LARGE big-plan check rides on the fresh-check
        # requirement). WORK = cut the plan into task cards. The cut-rules bundle (SPEC-0046 plan-cut
        # face + SPEC-0070) is delivered by `_emit_plan_stage_entered` below.
        _require_plan_decomposition_ready(slug, fm, body)
        msg = "(cut into task cards — SPEC-0046: ONE provable claim per accept-unit, order via requires:)"
    elif name == "executing":
        # decomposition → executing (SPEC-0070 §3/§8): (1) the cut-rules read-gate — you cannot leave the
        # cut for build unless the decomposition bundle was fetched this session (graceful-empty until the
        # binding is non-empty); (2) the mandatory decomposition-fidelity gate over the CARD SET. WORK =
        # the tasks run their own 9 stages (pure build).
        _require_reads("stage", {"axis": "plan", "stage": "decomposition",
                                 "verb": "plan stage executing",
                                 "action": "decomposition->executing transition"})
        _require_plan_decomposition_fidelity(slug, fm, body, owner_reset=_owner_reset)
        msg = "(tasks run their own 9 stages — pure build; the cut is fidelity-audited)"
    elif name == "postcheck":
        _require_plan_postcheck_ready(slug, body)
        msg = "(real-data soak + monitoring; declare the postcheck probe block)"
    elif name == "realized":
        into = _split_into(args.into)
        if not into:
            _die("plan stage realized requires --into <artifact ID(s)> (what the plan became).")
        if _by_record:
            # T-9369 — soak-OUTSIDE-the-FSM terminal: bypass the finalization gate, require the
            # EXISTING soak-proof + handoff evidence (validated inside _plan_close_core). AC1/AC3.
            # Audit-pre F1 — EXPLICIT eligibility predicate (not «any plan with two refs»): the plan
            # body MUST declare a `## Realized-by-record` rationale (owner-authored, presence-checked
            # like the postcheck-probe-block — no detector). A non-record-class plan is refused here.
            _require_verification_artifact(
                _realized_by_record_declared(body), verb="plan stage realized --by-record",
                stage="realized", tid=None, missing_label="record_eligibility",
                message=(f"{slug}: --by-record requires the plan body to declare a `## Realized-by-record` "
                         f"eligibility rationale (WHICH soak-proof + WHICH handoff happened OUTSIDE this "
                         f"plan's decomposition, and why it is record-class) — the EXPLICIT eligibility "
                         f"predicate the shortcut is gated on (SPEC-0034 §Realized-by-record, audit-pre "
                         f"F1). Author that section in plans/{slug}.md, then re-run. A plan that is NOT "
                         f"record-class cannot terminalize by record."))
            legacy = ("draft_closed", _plan_close_core(
                path, fm, body, slug, into, "realized", None, args.note, by_record=True,
                soak_evidence=getattr(args, "soak_evidence", None), handoff=getattr(args, "handoff", None)))
            extra = {"closed_into": into, "realized_by": "record"}
        else:
            legacy = ("draft_closed", _plan_close_core(path, fm, body, slug, into, "realized", None, args.note))
            extra = {"closed_into": into}
        wrote = True
    elif name == "partial":
        into = _split_into(args.into)
        if not into:
            _die("plan stage partial requires --into <artifact ID(s)> (what the plan became).")
        legacy = ("draft_closed", _plan_close_core(path, fm, body, slug, into, "partial", args.deferred, args.note))
        extra = {"closed_into": into}
        wrote = True
    elif name in ("rejected", "cancelled"):
        reason = (getattr(args, "reason", None) or "").strip()
        if not reason:
            _die(f"plan stage {name} requires --reason (non-empty) — why this plan is abandoned.")
        fm["status"] = name
        fm["rejected_reason" if name == "rejected" else "cancelled_reason"] = reason
        _write_draft(path, fm, body)
        if name == "rejected":
            legacy = ("draft_rejected", {"slug": slug, "reason": reason})
        extra = {"reason": reason}
        wrote = True
    # --- commit the status write (for branches that did not write themselves) + events ---
    if not wrote:
        fm["status"] = name
        _write_draft(path, fm, body)
    if legacy:
        _append_event(legacy[0], None, legacy[1])
    # T-12027 — the two soak-BOUNDING transitions disclose what their gate read and what it did not,
    # in the transition output AND (same dict, P5) the `plan_stage_entered` payload. Computed AFTER
    # admission is settled, so it cannot move it; `_plan_stage_bundle_specs` is the SAME pure lookup
    # `_emit_plan_stage_entered` uses for `delivered`, consulted here so an empty bundle is disclosed
    # rather than left to be noticed in the journal row (the X-1250 rows read `delivered:[]`).
    _disclosure = {}
    if name in _PLAN_GATE_CHECKED:
        _disclosure = _plan_gate_disclosure(slug, body, name, _plan_stage_bundle_specs(name))
        if _disclosure:
            extra["gate_disclosure"] = _disclosure
    delivered = _emit_plan_stage_entered(slug, cur, name, extra=extra)
    # T-10052 — a TERMINAL plan-stage transition (realized/partial/rejected/cancelled) is a HALT with
    # NO later plan-stage to commit its dirty status write, so without a self-commit the worktree is
    # left dirty and the terminal status never reaches main via a governed commit. This mirrors the
    # task pause/park/wont-do self-commits (T-9320/T-0614/T-9622): a terminal transition owns its own
    # record here, giving the one-verb path `plan stage <terminal> ... -> land`. Calling
    # `_commit_worktree` DIRECTLY reuses the shared commit core (D-0045), as close/pause/wont-do do.
    # UNCONDITIONAL (like pause/wont-do, NOT conditional like the non-terminal park): a terminal IS the
    # end of the plan's lifecycle, so there is always a status write to land. SCOPED staging
    # (E-0037/T-9539): the plan file + events.jsonl + the reverse-linked target YAMLs
    # (`_link_plan_into_targets` AC4 write, present only for realized/partial) ONLY — never unrelated
    # worktree dirt a blanket `git add -A` would sweep into the plan-terminal record (a `work/<slug>`
    # worktree may carry other batch artifacts). Only in a REAL writing worktree
    # (`_in_writing_worktree()`, the close precedent) — a degraded/main transition + the non-git
    # sandbox tests keep the old leave-dirty behaviour. The trailing commit_landed re-dirties
    # events.jsonl by one line, folded by land step-1 (T-0106: a real commit leaves an event).
    if name in PLAN_TERMINAL and _in_writing_worktree():
        rel_plan = str(path.relative_to(REPO_ROOT))
        # T-11536 / SPEC-0190 rule 1 — "the journal" here is the LOGICAL journal: its live segment
        # PLUS every archive segment on disk. A terminal transition taken at a seam that also rotated
        # would otherwise leave the archive segment unstaged, hence uncommitted on a path outside
        # `_BOOKKEEPING_ALLOWLIST` — wedging the next land, and the one after it (the X-0274 shape
        # SPEC-0190 rule 3 names). Resolved through the ONE view (`events.journal_pathspecs`) rather
        # than re-spelled here. The SCOPED-staging rule (E-0037/T-9539) is UNCHANGED: what this adds
        # is physical segments of the journal already being staged, and nothing else.
        pathspecs = [rel_plan, *events_mod.journal_pathspecs(REPO_ROOT / "events.jsonl", REPO_ROOT)]
        for rid in ((legacy[1] if legacy else {}).get("reverse_linked") or []):
            rpath = (_find_task_yaml(rid) if re.match(r"^T-\d{4,}$", rid)
                     else _find_decision_yaml(rid) if re.match(r"^D-\d{4,}$", rid) else None)
            if rpath and rpath.exists():
                pathspecs.append(str(rpath.relative_to(REPO_ROOT)))
        _, short = _commit_worktree(
            rel_plan,
            f"chore({slug}): plan {name} record — status:{name} (+ reverse-links)",
            pathspecs=pathspecs)
        _append_event("commit_landed", None, {"slug": slug, "commit": short, "kind": f"plan-{name}"})
        print(f"  plan {name} record committed {short} — worktree land-clean (T-10052); "
              f"`yitc-v2 land` (from main) to integrate")
    print(f"{slug} -> {name} (plan stage; status recorded) {msg}".rstrip())
    _print_plan_stage_delivery(name, delivered)   # shared delivery print (audit-pre F0)
    _print_plan_gate_disclosure(_disclosure)      # T-12027 report-only gate disclosure
    # Precise work-pointer (T-0333): name THIS stage's Work section so the session knows the
    # action-plan lives there — closes the "moved to accepted but skipped compose impl_plan" miss.
    # POINTER ONLY: the stage `name` is interpolated into a fixed string; the work-item CONTENT
    # stays single-sourced in SPEC-0034 §Per-stage mechanics (each stage's `- Work:` line) — no
    # per-stage work-item map/copy in the verb, deliberately UNLIKE task stage's STAGE_WORK_VERBS
    # (plan FSM still evolving; verb=pointer, spec=content). Linear stages only — wont-do terminals
    # have no Work content.
    if name in PLAN_STAGE_SEQUENCE:
        _s34 = graph_lib.spec_query_hint(   # T-11992: kernel-explicit under -C (SPEC-0092)
            "SPEC-0034", is_consumer=bool(_is_consumer_build and _is_consumer_build()), cli="yitc-v2")
        print(f"work-items of this stage → SPEC-0034 §Per-stage mechanics `{name}` Work "
              f"(`{_s34}`)")
    # T-0623 — POST-SPECS FORK: at the decision point after the draft specs are composed, surface
    # BOTH branches so a trial-ELIGIBLE plan is not silently routed past `trial` straight to
    # `accepted` (the deviation trial-eligible-plan-routed-past-trial-verb-hints-omit-trial). Both
    # branches named; eligibility is OWNER judgement, no detector (SPEC-0035 rules 2/5/8, non-goal #7).
    if name == "specs":
        print(f"next (post-specs FORK — SPEC-0035): is this plan trial-eligible (mechanism/behavioral "
              f"— births a spec/verb/flow AND convergence can't honestly come from text-audit alone)? "
              f"YES → `yitc-v2 plan stage trial {slug}` (controlled real-data soak); NO (non-eligible "
              f"prose/docs, the skip) → `yitc-v2 plan check {slug}` then `yitc-v2 plan stage accepted "
              f"{slug}`. Your judgement — no detector.")
    else:
        # T-0683 — after every OTHER (linear, non-fork) successful transition, surface the FSM
        # successor so the "what is the next gate" line is no longer omitted after accepted/
        # decomposition/executing/postcheck/trial (the forgotten-stage problem). `specs` is the ONE
        # FORK — handled by the `if` arm above, never a single-successor line. `_plan_next_stage`
        # derives the successor from the ONE FSM constant PLAN_STAGE_SEQUENCE and returns None for
        # every terminal (realized/partial/rejected/cancelled) → no spurious successor hint there.
        nxt = _plan_next_stage(name)
        if nxt is not None:
            print(f"next: `yitc-v2 plan stage {nxt} {slug}` — enter the {nxt} stage "
                  f"(the FSM successor of {name}; LIFECYCLE §Plan lifecycle).")


def _plan_draft_specs(slug: str, *, SPECS_DIR, _read_yaml) -> list:
    """The plan's PLAN-BORN draft specs = specs/SPEC-*.yaml with status==draft AND
    proposed_by==slug, as sorted [(sid, path, raw_text)]. SAME selector predicate
    `_birth_plan_draft_specs` births at accept (single source — the audited set IS the
    born set, no parallel selector). A work-first spec (proposed_by==<task>) is excluded —
    it is content-audited by its own task's audit-pre/post (no double-audit, AC4)."""
    out = []
    for p in state.scan_specs(SPECS_DIR):   # SPEC-* glob excludes _template.yaml
        d = _read_yaml(p)
        if not isinstance(d, dict):
            continue
        if d.get("status") == "draft" and d.get("proposed_by") == slug:
            out.append((d.get("id") or p.stem, p, p.read_text(encoding="utf-8")))
    return sorted(out, key=lambda t: t[0])


def _plan_active_proposed_corpus(*, SPECS_DIR, _read_yaml) -> list:
    """The active+proposed spec corpus the draft specs are audited AGAINST, as sorted
    [(sid, status, title, raw_text)]. CONTENT-BEARING (the auditor needs the spec bodies to
    judge semantic overlap/contradiction — titles alone cannot; audit-pre F1). `active` is the
    only normative status, `proposed` is the design-grade «what-will-be» — both are the live
    corpus a new draft spec must not duplicate/contradict (D-0047 one-active-lineage / P7)."""
    out = []
    for p in state.scan_specs(SPECS_DIR):   # SPEC-* glob excludes _template.yaml
        d = _read_yaml(p)
        if not isinstance(d, dict):
            continue
        if d.get("status") in ("active", "proposed"):
            out.append((d.get("id") or p.stem, d.get("status"), d.get("title") or "",
                        p.read_text(encoding="utf-8")))
    return sorted(out, key=lambda t: t[0])


def _spec_content_sans_status(raw: str) -> str:
    """A spec's content with the top-level `status:` line blanked — so the draft→proposed
    BIRTH (which only flips `status:`) does NOT perturb the freshness basis, while a real
    body/title EDIT still does. Lets the accept gate detect an external edit yet stay stable
    across the birth's own idempotent, resumable status-flips (the partial-failure resume
    contract, _birth_plan_draft_specs)."""
    return _SPEC_STATUS_LINE_RE.sub("status:", raw, count=1)


def _plan_scenario_roles(fm: dict):
    """SPEC-0082 — read the plan-owned `scenario_roles` marker. Returns
    (baseline: list[str], target: list[str], malformed: list[str]); `malformed` is a list of human
    reasons (empty when well-formed). DISTINGUISHES absent/empty (strict no-op — both lists empty AND
    no malformed) from MALFORMED (present but wrong shape — a reason is recorded so the caller emits a
    structural finding, NEVER a silent no-op; audit-pre F1/F2 absorptions). A non-mapping value, an
    unknown top-level key (only baseline/target allowed), or a non-string slug element each records a
    reason. Pure."""
    fm = fm or {}
    if "scenario_roles" not in fm:
        return [], [], []                                   # key ABSENT → strict no-op
    raw = fm["scenario_roles"]
    if isinstance(raw, dict) and not raw:
        return [], [], []                                   # explicit EMPTY mapping → strict no-op
    if not isinstance(raw, dict):
        # PRESENT but not a mapping (null / scalar / list) → MALFORMED, never a silent no-op
        # (audit-post F1: `scenario_roles: null` is an explicit half-declaration, distinct from absent).
        return [], [], [f"scenario_roles is present but not a mapping (got {type(raw).__name__}: {raw!r}) "
                        f"— declare {{baseline: [...], target: [...]}} or omit the field"]
    malformed = []
    unknown = sorted(str(k) for k in raw.keys() if k not in _PLAN_SCENARIO_ROLES_KEYS)
    if unknown:
        malformed.append(f"scenario_roles has unknown key(s) {unknown} (only 'baseline'/'target' allowed)")

    def _slugs(key):
        v = raw.get(key)
        if v is None:
            return []
        items = v if isinstance(v, list) else [v]
        out = []
        for it in items:
            if isinstance(it, str):
                out.append(it)
            else:
                malformed.append(f"scenario_roles.{key} has a non-string element {it!r}")
        return out
    return _slugs("baseline"), _slugs("target"), malformed


def _plan_scenario_fidelity(fm: dict, *, _plan_scenario_roles, _scenario_index_nodes):
    """SPEC-0082 — the deterministic scenario-fidelity dimension of the `plan check` verdict. Returns
    None for the STRICT no-op (no/empty + well-formed scenario_roles) so the caller adds NOTHING (no
    prompt cue, no verdict section, no freshness input — byte-identical output). Else returns
    {medium: [...], structural: [...], fresh_inputs: str}: a BASELINE scenario that does NOT have every
    spec it cites `active` → a MEDIUM finding (contributes YELLOW, never RED); a malformed marker / baseline∩target
    overlap / a slug that does not resolve to a scenario node → a STRUCTURAL finding (report-not-block);
    a TARGET is NEVER a fidelity finding (greenfield-safe). REUSES `_scenario_index_nodes()` (the built
    status map) + the `cites_all_active` field the pure `_scenario_cites_all_active` puts on each node —
    no new scan/parser (CHARTER §P1)."""
    baseline, target, malformed = _plan_scenario_roles(fm)
    if not baseline and not target and not malformed:
        return None                                         # strict no-op
    structural, medium = [], []
    _sf = lambda what, fix: {"severity": "low", "source": "structural", "what": what,
                             "where": "plan frontmatter scenario_roles", "fix": fix}
    for reason in malformed:
        structural.append(_sf(reason, "fix scenario_roles to {baseline: [<scenario-slug>...], "
                              "target: [<scenario-slug>...]} (SPEC-0082)"))
    overlap = sorted({s for s in baseline if s in set(target)})
    if overlap:
        structural.append(_sf(f"scenario_roles baseline∩target overlap: {overlap}",
                              "baseline and target MUST be disjoint (SPEC-0082) — a scenario is either "
                              "ASSUMED (baseline) or BUILT (target), not both"))
    nodes = _scenario_index_nodes() if (baseline or target) else {}
    for slug in baseline + target:
        if slug not in nodes:
            structural.append(_sf(f"scenario_roles slug does not resolve to a scenario node: {slug}",
                                  f"declare scenarios/{slug}.md (frontmatter scenario: {slug}) or fix the "
                                  f"slug (SPEC-0082 — each entry MUST resolve to a scenario node)"))
    fresh_parts = []
    for slug in baseline:                                   # AUTHORED ORDER (audit-pre F2: a reorder stales)
        node = nodes.get(slug) or {}
        status = node.get("computed_status") or "draft"
        # T-11004: keyed on `cites_all_active`, NOT on the retired `live` status. `live` required a
        # binding-test-green signal no repository ever produced, so `status != "live"` was TRUE for
        # every baseline everywhere — the finding fired always and said nothing. The reachable half of
        # what it meant is "not every cited spec is active", which the node now carries directly. Both
        # pre-change MEDIUM populations are preserved: a `building` baseline (a cited spec not active)
        # AND a `draft` one (cites no spec at all — `cites_all_active` is False there, never vacuously
        # true). The unresolved-slug case stays the STRUCTURAL finding above, so `slug in nodes` still
        # guards this arm.
        # EXPLICIT `is False`, never truthiness (audit-post F1): the two ways this field can be
        # non-true are DIFFERENT problems and must not collapse into one verdict. `False` is the real
        # fidelity FACT — the baseline is not a working invariant. A MISSING key is not a fact about
        # the scenario at all: our own index build always writes the field, so its absence means a
        # STALE or foreign index (a schema/evidence problem), which belongs in the structural bucket
        # next to the other "this declaration cannot be read" findings, not in the verdict-contributing
        # MEDIUM. Silently PASSING the missing case is not an option either — that would let a stale
        # index clear the dimension unnoticed.
        if slug in nodes and node.get("cites_all_active") is None:
            structural.append(_sf(
                f"baseline scenario {slug} resolved to a node with no `cites_all_active` field",
                "rebuild the graph index (`yitc-v2 graph build`) — the field is written by every "
                "current index build, so its absence means a stale/foreign index, not a fact about "
                "the scenario (SPEC-0082)"))
        if slug in nodes and node.get("cites_all_active") is False:
            medium.append({"severity": "medium", "source": "scenario-fidelity",
                           "what": f"baseline scenario {slug} is {status} and does not have every spec it "
                                   f"cites `active` (the plan ASSUMES a working invariant that is not "
                                   f"actually working)",
                           "where": f"scenarios/{slug}.md (computed status: {status})",
                           "fix": "get the baseline scenario's cited specs active (or cite the specs that "
                                  "govern it, if it cites none) before assuming it, or reclassify it as a "
                                  "target (SPEC-0082)"})
        # LIST-only, through the ONE hardened read (`graph._glob_list`, T-11135/T-11876). A SCALAR
        # `covers: "src/**"` is malformed, and `for c in <str>` walks its CHARACTERS — every one a
        # non-blank string — so the malformed scalar used to enter this freshness basis as a fully
        # declared 7-element list. That is worse than cosmetic HERE: the basis string is what decides
        # whether an accepted plan's scenario-fidelity reading is still current, so a fabricated
        # declaration both mis-states the record and re-keys on every re-read of the same bad value.
        # A non-list declares nothing (the family's fail-open direction).
        cites = sorted(str(c) for c in graph_lib._glob_list(node.get("cites")))
        covers = sorted(str(c) for c in graph_lib._glob_list(node.get("covers")))
        fresh_parts.append(f"B {slug}|{status}|cites={cites}|covers={covers}")
    return {"medium": medium, "structural": structural, "fresh_inputs": "\n".join(fresh_parts)}


def _plan_accept_freshness_hash(slug: str, body: str, fm: dict = None, sf=_SF_UNSET, *, SPECS_DIR, _plan_active_proposed_corpus, _plan_content_hash, _plan_scenario_fidelity, _read_yaml, _spec_content_sans_status) -> str:
    """T-0332 accept-gate freshness basis — sha256 over the plan body content_hash + the plan's
    OWN spec CONTENT + the EXTERNAL active+proposed corpus CONTENT. Mirrors `_plan_corpus_signature`
    (the close-gate basis) but binds the accept-relevant inputs so the draft→proposed BIRTH is
    re-audited iff an input the auditor saw changed:
    - **plan-own specs** = every `proposed_by==slug` spec (draft OR already-proposed), hashed with
      its `status:` line BLANKED (`_spec_content_sans_status`). Editing a draft spec body post-check
      stales the gate (AC2); but the birth's OWN draft→proposed status-flip does NOT (so a partial-
      birth RESUME is not falsely blocked — the idempotent resume contract).
    - **external corpus** = the active+proposed set MINUS the plan's own specs, full content. A
      corpus spec body/status edit post-check stales the gate (audit-pre F2 / YELLOW absorbed); the
      plan's own specs are excluded here so their birth-flip into `proposed` does not perturb it.
    `plan check` records this; `_plan_accept_core` recomputes + compares, refusing the birth on
    mismatch. **Scope guard (audit-post F1): a plan with NO PLAN-BORN specs AT ALL (`proposed_by==slug`
    in ANY status) SHORT-CIRCUITS to the legacy plan-body-only basis** (`<content_hash>`) — a no-spec
    (work-first / task-only) plan has nothing to audit against the corpus, so an UNRELATED corpus edit
    must NOT stale its accept path. The guard keys on the plan's OWN spec set being EMPTY — NOT on
    having no `draft`-status specs (audit-post F1 second pass): once a partial birth has flipped some of
    the plan's specs draft→proposed, the plan STILL owns them, so the rich (resume-stable, status-
    blanked) hash must keep applying — else the partial-birth RESUME falls back to the body-only hash,
    mismatches the recorded rich hash, and is wrongly refused as stale (the idempotent resume contract,
    `_birth_plan_draft_specs`)."""
    # SPEC-0082 — the scenario-fidelity BASELINE slice (baseline list in authored order + each
    # baseline scenario's cites/covers/computed status). Folded into the basis ONLY when non-empty, so
    # a plan with no/empty scenario_roles hashes EXACTLY as before (byte-identical — no churn for the
    # existing corpus; the target list is NOT a freshness input, by construction of `fresh_inputs`).
    if sf is _SF_UNSET:                                  # not precomputed by the caller → derive it here
        sf = _plan_scenario_fidelity(fm) if fm is not None else None
    scen = sf["fresh_inputs"] if sf else ""
    own_ids, own = set(), []
    for p in state.scan_specs(SPECS_DIR):   # SPEC-* glob excludes _template.yaml
        d = _read_yaml(p)
        if isinstance(d, dict) and d.get("proposed_by") == slug:
            sid = d.get("id") or p.stem
            own_ids.add(sid)
            own.append(f"OWN {sid}\n{_spec_content_sans_status(p.read_text(encoding='utf-8'))}\n")
    if not own_ids:
        if not scen:
            return _plan_content_hash(body)   # NO plan-born specs + no scenario slice → legacy plan-body-only basis
        return hashlib.sha256(f"{_plan_content_hash(body)}|SCEN\n{scen}".encode("utf-8")).hexdigest()
    own_s = "".join(sorted(own))
    corpus = "".join(f"CORPUS {sid}:{st}\n{raw}\n"
                     for sid, st, _t, raw in _plan_active_proposed_corpus() if sid not in own_ids)
    basis = f"{_plan_content_hash(body)}|{own_s}|{corpus}"
    if scen:
        basis += f"|SCEN\n{scen}"
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


_SPEC_SCENARIO_RE = re.compile(r"(?m)^[ \t]*##[ \t]+Scenario\b[^\n]*\n")


def _spec_scenario_oneline(raw: str, *, _limit: int = 240) -> str:
    """A ONE-LINE digest of a spec's `## Scenario` (the user-path framing) for the COMPACT corpus
    comparand (T-9383). Returns the first non-empty prose line under the spec body's `## Scenario`
    heading, whitespace-collapsed + truncated; "" when the spec has no Scenario (4/68 a+p specs).
    The auditor needs to know what each corpus spec IS to spot duplication/overlap — not its full
    body — so the comparand list stays bounded (id+status+title+scenario), NOT linear in body size."""
    m = _SPEC_SCENARIO_RE.search(raw)
    if not m:
        return ""
    for line in raw[m.end():].splitlines():
        s = line.strip()
        if not s or s.startswith("##"):
            if s.startswith("##"):
                break          # next heading reached, no prose found
            continue           # skip blank lines
        s = " ".join(s.split())
        return s if len(s) <= _limit else s[: _limit - 1].rstrip() + "…"
    return ""


_CORPUS_BLOCK_BUDGET = 64_000   # BYTES (UTF-8) — HARD ceiling on the ENTIRE rendered accept-gate block
#   (prose + draft bodies + corpus index + footer), NOT only the corpus rows (T-9383 audit-post p1).
#   The fixed prose (~2KB) always fits; the VARIABLE parts fill the rest in priority order — draft
#   bodies first (the artifacts under audit), then the compact corpus index — and anything past the
#   ceiling is truncated / omitted with an explicit note. A reserved footer keeps the notices under the
#   ceiling, so the whole block can NEVER overflow codex regardless of corpus size OR draft-spec size.
_CORPUS_BLOCK_FOOTER_RESERVE = 800   # BYTES held back from the budget for the always-appended notices.


def _plan_draft_related_ids(drafts) -> tuple:
    """The high-signal duplication comparands for the draft specs (T-9383): (related_ids, surfaces).
    related_ids = every spec id a draft references via requires/cites/supersedes; surfaces = the set
    of `implements:` file-anchors (file part of file#symbol) the drafts touch, used to flag a corpus
    spec on the SAME surface (same-surface closure — the auditor's named refinement). Pure (parses the
    draft raw text only)."""
    related, surfaces = set(), set()
    for _sid, _path, raw in drafts:
        d = state.load_str(raw) or {}
        if not isinstance(d, dict):
            continue
        for k in ("requires", "cites", "supersedes"):
            v = d.get(k)
            if isinstance(v, str):
                related.add(v)
            elif isinstance(v, list):
                related.update(x for x in v if isinstance(x, str))
        impl = d.get("implements") or []
        if isinstance(impl, list):
            surfaces.update(str(a).split("#", 1)[0] for a in impl if isinstance(a, str))
    return related, surfaces


def _spec_on_surface(raw: str, surfaces: set) -> bool:
    """True when a corpus spec's `implements:` anchors touch any of `surfaces` (same-surface). Pure."""
    if not surfaces:
        return False
    d = state.load_str(raw) or {}
    if not isinstance(d, dict):
        return False
    impl = d.get("implements") or []
    if not isinstance(impl, list):
        return False
    return any(str(a).split("#", 1)[0] in surfaces for a in impl if isinstance(a, str))


def _plan_draft_corpus_audit_block(slug: str, *, _plan_active_proposed_corpus, _plan_draft_specs,
                                   coverage_out: "dict | None" = None) -> str:
    """The accept-gate corpus-conflict audit block appended to the `plan check` prompt WHEN the
    plan has PLAN-BORN draft specs (T-0332). It feeds the auditor (a) the draft spec FILE
    CONTENTS (FULL bodies — these are the artifacts UNDER audit) and (b) a COMPACT index of the
    active+proposed corpus — id + status + title + the one-line `## Scenario` (T-9383, NOT full bodies:
    at corpus scale the full-body inline reached ~1.05MB/~261k tokens and overflowed codex, perpetually
    ABORTing the gate). The ENTIRE rendered block — prose + draft bodies + corpus index + footer — is
    accumulated under ONE hard byte ceiling (`_CORPUS_BLOCK_BUDGET`), so it can NEVER overflow codex
    regardless of corpus size OR draft-spec size: the fixed prose always fits, then the VARIABLE parts
    fill the remaining budget in PRIORITY order — draft bodies first (the subject), then the corpus
    index with RELATED comparands (a draft's requires/cites/supersedes targets + same-`implements:`-
    surface specs) before the rest — and anything past the ceiling is truncated / omitted with an
    explicit count + a fetch pointer (a reserved footer keeps those notices under the ceiling). This
    preserves the P7 corpus-conflict lens (the auditor sees what each comparand IS, highest-risk ones
    first) while the prompt stays hard-bounded. Empty string when the plan has no draft specs
    (work-first / task-only plan → the block is omitted, the prompt is unchanged).

    T-10917 — `coverage_out` is an optional dict SINK for the gate's REACH: the two omission counters
    this builder already computes (and until now spent only on footer prose) are written into it so the
    CALLER can record a reach shortfall in the VERDICT instead of leaving it in auditor prose (SPEC-0034
    §accepted: a partial corpus read must never render as a full pass). Purely additive — the returned
    block is byte-identical whether or not a sink is passed."""
    drafts = _plan_draft_specs(slug)
    if not drafts:
        # A work-first / task-only plan births no drafts, so there is NOTHING the gate could fail to
        # reach — full reach by definition (recorded explicitly, not left absent-and-ambiguous).
        if coverage_out is not None:
            coverage_out.update({"corpus_omitted": 0, "draft_truncated": 0, "clamped_bytes": 0,
                                 "corpus_total": 0, "drafts_total": 0})
        return ""
    corpus = _plan_active_proposed_corpus()
    draft_ids = {sid for sid, _p, _r in drafts}
    related_ids, surfaces = _plan_draft_related_ids(drafts)

    parts, used = [], 0
    budget = _CORPUS_BLOCK_BUDGET - _CORPUS_BLOCK_FOOTER_RESERVE   # rows fill up to here; footer reserved

    def _add(text):
        # Append ESSENTIAL fixed prose unconditionally (small + bounded). Counts toward `used`.
        nonlocal used
        parts.append(text)
        used += len(text.encode("utf-8"))

    def _add_capped(text) -> bool:
        # Append a VARIABLE-size piece only if it fits under `budget`; returns False when it does not.
        nonlocal used
        n = len(text.encode("utf-8"))
        if used + n > budget:
            return False
        parts.append(text)
        used += n
        return True

    _add(
        "\n## Accept-gate: draft specs vs the active+proposed corpus (P7 — coherence)\n"
        "This plan BIRTHS the draft spec(s) below into `proposed` at acceptance. Audit each draft "
        "spec's OWN content against the live corpus (active + proposed) for overlap, duplication, or "
        "contradiction (CHARTER §P7 dissonance; D-0047 one-active-lineage). A draft spec that "
        "duplicates an existing spec, contradicts it, or belongs INSIDE an existing spec (SPEC-0005 "
        "delete-test / one-home) → RED/YELLOW; a genuine relationship must be encoded via "
        "`requires:` / `supersedes:`. GREEN only if every draft spec is coherent + non-redundant "
        "with the corpus.\n")
    # (a) Draft specs UNDER audit — FULL bodies, but still under the block ceiling (a pathological plan
    # birthing megabytes of draft specs truncates here rather than overflowing — the safety valve).
    _add("\n### Draft specs born by this plan (the artifacts UNDER audit — FULL content)\n")
    draft_truncated = 0
    for sid, path, raw in drafts:
        if not _add_capped(f"\n--- {sid} ({path.name}) ---\n{raw}\n"):
            draft_truncated += 1
    # (b) The active+proposed corpus as a COMPACT index: RELATED comparands first, then the rest, all
    # under the SAME ceiling (related ∪ same-surface are the highest duplication risk).
    comparands = [(sid, st, title, raw) for sid, st, title, raw in corpus if sid not in draft_ids]
    related, other = [], []
    for sid, st, title, raw in comparands:
        (related if (sid in related_ids or _spec_on_surface(raw, surfaces)) else other).append(
            (sid, st, title, raw))

    def _line(sid, st, title, raw):
        scen = _spec_scenario_oneline(raw)
        return f"- {sid} [{st}] {title}" + (f" — {scen}" if scen else "") + "\n"

    _add(
        "\n### Active + proposed corpus INDEX (audit the draft specs AGAINST these)\n"
        "Compact index — id, [status], title, and the one-line Scenario of each live spec (NOT full "
        "bodies, by design — the WHOLE block is byte-budgeted so it cannot overflow at corpus scale). "
        "Use it to spot any draft spec that duplicates / overlaps / contradicts an existing spec, or "
        "that belongs INSIDE one. RELATED comparands (the drafts' requires/cites/supersedes targets + "
        "same-surface specs) are the highest-duplication-risk set and are emitted FIRST. If a draft "
        "looks like it may collide with a specific corpus spec, fetch that spec's full body "
        "(`graph query <SPEC>`) to confirm.\n")
    corpus_omitted = 0

    def _emit(rows):
        nonlocal corpus_omitted
        for sid, st, title, raw in rows:
            if not _add_capped(_line(sid, st, title, raw)):
                corpus_omitted += 1

    if related:
        _add(f"\n#### Related comparands ({len(related)} — highest duplication risk)\n")
        _emit(related)
    _add(f"\n#### Other active + proposed specs ({len(other)})\n")
    _emit(other)
    # Footer: name anything dropped so the auditor knows the block is a bounded view. Built into its OWN
    # string (NOT via `_add`) so the final clamp can truncate ONLY the variable content and ALWAYS append
    # the footer intact (T-9384: the prior reserve-then-clamp could cut the footer when the fixed prose +
    # uncapped section headers themselves exceeded the 800B reserve — an extreme synthetic case).
    footer = ""
    if corpus_omitted:
        footer += (f"\n(+{corpus_omitted} further active+proposed spec(s) omitted to keep the whole block "
                   f"within the {_CORPUS_BLOCK_BUDGET}-byte ceiling — fetch any spec's full body via "
                   f"`graph query <SPEC>` / list all via `graph query --type spec`.)\n")
    if draft_truncated:
        footer += (f"\n(WARNING: {draft_truncated} draft spec(s) under audit were omitted to keep the block "
                   f"within the {_CORPUS_BLOCK_BUDGET}-byte ceiling — the plan births an unusually large draft "
                   f"corpus; audit them directly via `graph query <SPEC>`.)\n")
    # FINAL hard clamp (T-9383 audit-post p3, hardened T-9384): reserve the footer's ACTUAL byte length up
    # front, clamp the content to the remainder, THEN append the footer — so content + footer is GUARANTEED
    # <= _CORPUS_BLOCK_BUDGET bytes AND the omission notice + fetch pointer ALWAYS survive (independent of
    # how large the fixed prose / headers grew; the prior single reserve-then-clamp could cut the footer
    # when prose + uncapped section headers exceeded the 800B reserve). This realizes acceptance option B —
    # "truncate only the rows before appending the footer": `parts` is ordered prose → headers → variable
    # comparand rows, and the byte-slice keeps the FRONT, so the small fixed prelude (prose + headers,
    # ~2.5KB << the ~63KB content limit) is never reached by the cut — only the TRAILING comparand rows are
    # dropped. Slice on encoded bytes (decode errors='ignore' drops a split trailing multibyte char).
    content = "".join(parts)
    footer_bytes = len(footer.encode("utf-8"))
    content_limit = _CORPUS_BLOCK_BUDGET - footer_bytes
    encoded = content.encode("utf-8")
    clamped_bytes = 0
    if len(encoded) > content_limit:
        clamped_bytes = len(encoded) - content_limit
        content = encoded[:content_limit].decode("utf-8", "ignore")
    # T-10917 — publish the gate's REACH to the caller's sink, AFTER the clamp. The counters alone would
    # UNDERCOUNT: `_add_capped` reserves a fixed 800B for the footer, so a footer larger than that reserve
    # makes the final clamp cut rows the counters already accepted as fitting. `clamped_bytes` is the
    # third, independent shortfall signal covering exactly that residue — otherwise a run whose reach fell
    # short at the clamp would report full reach, which is the very silence this task closes.
    if coverage_out is not None:
        coverage_out.update({"corpus_omitted": corpus_omitted, "draft_truncated": draft_truncated,
                             "clamped_bytes": clamped_bytes,
                             "corpus_total": len(comparands), "drafts_total": len(drafts)})
    return content + footer


# T-10917 / X-0706 — the auditor's OWN self-report that it could not fully read the corpus. Each pattern
# pins a NEGATION to a read/verify verb whose OBJECT is the corpus/specs/plan, so ordinary prose that
# merely mentions the corpus ("audited each draft spec against the corpus index") cannot trip it. This
# scan is a SUPPLEMENT, never the sole guard: the deterministic counters catch the mechanical case on
# their own, so a phrase this list misses degrades to today's behaviour rather than to a false GREEN.
_CORPUS_SELF_REPORT_PATTERNS = (
    r"(?:could|can|was|were)\s*n(?:o|')t\s+(?:fully\s+|completely\s+)?"
    r"(?:read|review|verify|validate|assess|evaluate|examine|inspect)\b[^.\n]{0,80}"
    r"\b(?:corpus|specs?|spec\s+bodies|plan|draft)",
    r"\b(?:unable|failed|not\s+able)\s+to\s+(?:fully\s+|completely\s+)?"
    r"(?:read|review|verify|validate|assess|evaluate|examine|inspect)\b[^.\n]{0,80}"
    r"\b(?:corpus|specs?|spec\s+bodies|plan|draft)",
    # Bare "did not fully verify" / "only partially reviewed" — the verb may be an infinitive (after a
    # "did not" auxiliary) or a participle, so both forms are accepted.
    r"\b(?:only\s+)?(?:partially|incompletely)\s+"
    r"(?:read|review(?:ed)?|verif(?:y|ied)|validate[d]?|assess(?:ed)?|evaluate[d]?|"
    r"examine[d]?|inspect(?:ed)?)\b",
    r"\bnot\s+(?:fully|completely)\s+"
    r"(?:read|review(?:ed)?|verif(?:y|ied)|validate[d]?|assess(?:ed)?|evaluate[d]?|"
    r"examine[d]?|inspect(?:ed)?)\b",
)


def _plan_corpus_coverage_shortfall(coverage: "dict | None", stdout: str) -> "dict | None":
    """T-10917 (SPEC-0034 §accepted) — did the accept gate actually REACH the whole corpus it claims to
    judge? Returns None for a FULL read (the ordinary path — the caller then adds nothing at all, so the
    verdict stays byte-identical to pre-T-10917 output), else a record NAMING what was not reached.

    Two independent shortfall sources, deliberately not collapsed into one:
      * MECHANICAL — the corpus block dropped draft bodies / corpus rows / clamped bytes at the
        `_CORPUS_BLOCK_BUDGET` ceiling. Exact and always available.
      * SELF-REPORTED — the auditor's own prose says it could not fully read/verify the corpus. This is
        the literal X-0706 shape: the reach was short for a reason the counters cannot see, and the
        caveat used to survive only in prose while the verdict read as a normal pass.
    Either one alone is enough. Pure — no I/O, no state; the caller owns recording + escalation."""
    cov = coverage or {}
    omitted = int(cov.get("corpus_omitted") or 0)
    truncated = int(cov.get("draft_truncated") or 0)
    clamped = int(cov.get("clamped_bytes") or 0)
    self_report = bool(stdout) and any(
        re.search(p, stdout, re.IGNORECASE) for p in _CORPUS_SELF_REPORT_PATTERNS)
    if not (omitted or truncated or clamped or self_report):
        return None
    sources, reasons = [], []
    if truncated or omitted or clamped:
        sources.append("block-ceiling")
        if truncated:
            reasons.append(f"{truncated} of {cov.get('drafts_total') or truncated} draft spec(s) under "
                           f"audit were NOT put in front of the auditor")
        if omitted:
            reasons.append(f"{omitted} of {cov.get('corpus_total') or omitted} active+proposed corpus "
                           f"spec(s) were NOT indexed for comparison")
        if clamped:
            reasons.append(f"{clamped} byte(s) of the assembled block were cut at the "
                           f"{_CORPUS_BLOCK_BUDGET}-byte ceiling")
    if self_report:
        sources.append("auditor-self-report")
        reasons.append("the auditor SELF-REPORTED it could not fully read/verify the corpus")
    return {
        "full_read": False,
        "sources": sources,
        "not_reached": ("accept-gate corpus reach FELL SHORT — " + "; ".join(reasons) +
                        ". The verdict rests on a PARTIAL read of the corpus it judges "
                        "(SPEC-0034 §accepted; escalated to YELLOW, not a full pass)."),
        "corpus_omitted": omitted, "draft_truncated": truncated, "clamped_bytes": clamped,
        "corpus_total": cov.get("corpus_total"), "drafts_total": cov.get("drafts_total"),
    }


def _plan_gate_template_text(template: str, *, _find_spec_path):
    """Extract the named per-gate question template (the P1-P4 block) from the auditor-contract
    spec body (PLAN_GATE_TEMPLATE_SPEC — ONE home, SPEC-0036 §Plan-stage overlays). Returns the
    block text, or None when the spec / anchor is unavailable — the CALLER applies the policy
    split (T-0349 audit-pre F1): a MANDATORY-BLOCKING surface fails CLOSED (die), an ADVISORY
    surface records the gap and never holds."""
    anchor = PLAN_GATE_TEMPLATE_ANCHORS.get(template)
    if anchor is None:
        return None
    try:
        import yaml
        # KERNEL-PIN (T-10581 / X-0433, the SPEC-0092 kernel-prefixed retrieval path): the gate-template
        # spec is BY DEFINITION the kernel external-auditor contract, so resolve it from the KERNEL even
        # when a -C consumer OWNS the same id (force_engine INVERTS precedence). The prior
        # engine_fallback=True (T-0860, own-wins-then-engine) let a consumer PRODUCT spec at the same id
        # (boomrocket SPEC-0036, an F2a import with no P-anchor) shadow the kernel contract → None →
        # the MANDATORY-BLOCKING gate-specs surface failed CLOSED. Kernel-pinned, never consumer-resolved.
        path = _find_spec_path(PLAN_GATE_TEMPLATE_SPEC, force_engine=True)
        if path is None:
            return None
        body = (state.load_str(path.read_text(encoding="utf-8")) or {}).get("body") or ""
        m = re.search(rf"(?m)^\*\*{anchor} — ", body)
        if not m:
            return None
        rest = body[m.start():]
        nxt = re.search(r"(?m)^\*\*", rest[2:])   # the next bold line-start block heading
        return (rest[: nxt.start() + 2] if nxt else rest).rstrip()
    except Exception:
        return None


def _run_plan_gate_audit(slug: str, fm: dict, body: str, template: str, gate_policy: str,
                         *, blocking: bool, card_set_fp: "str | None" = None,
                         extra_context: "str | None" = None, owner_reset: bool = False, _with_repo_lock=None, _iter_events=None, EVENTS_PATH=None, _file_followup=None, _plan_gate_lens=None, _parse_audit_verdict_c1=None, AUDIT_PASS_CEILING, AUTO_CONSULT_HOLD_OPTION, AUTO_CONSULT_PROCEED_OPTION, DECISIONS_DIR, REPO_ROOT, _PLAN_AUDIT_LENS, _PLAN_CONSULT_GATE_AUDIT, _append_event, _auto_rebuild_graph, _consult_adjudicate, _consult_basis, _die, _invoke_auditor, _parse_audit_verdict, _parse_consult_result, _plan_content_hash, _plan_fsm_line, _plan_gate_recorded_signature, _plan_gate_template_text, _read_consult_adjudication, _read_yaml, _resolve_audit_effort, _resolve_audit_model, _resolve_audit_provider, _strip_degenerate_tail, _utc_now_iso, build_plan_consult_prompt, finding_count_trend, is_trend_convergence_grant, write_text_atomic) -> str:
    """T-0349 — the verb-asked plan-gate audit (SPEC-0036 §Plan-stage overlays): `plan stage specs`
    asks P2 (auto-advisory), `plan stage trial` asks P3 (mandatory-blocking). FULL-capability
    auditor (SPEC-0034 plan-audit posture). Saves the canonical verdict (T-0348 schema +
    stage_template/gate_policy) to decisions/<slug>-audit-<template>.yaml (the dogfood filename
    precedent). Blocking: RED/ABORT — or a missing template, fail closed — refuses the transition;
    the 2-pass ceiling applies (ABORT burns no pass). Advisory: any verdict proceeds — recorded,
    never holds. Returns the verdict string.

    ABSORBING a residual from the verdict this writes (T-11167 / X-0928): use the governed route
    `yitc-v2 audit pre --plan <slug> --gate <id> --absorb "<text>"` (audit.py#absorb_into_plan_gate_record)
    — NEVER hand-edit the saved YAML's absorbed:/notes:. The verb is the only path that emits
    audit_finding_absorbed, which is what makes the absorption visible to a later session; it burns no
    ceiling pass (SPEC-0124 §Audit-loop ceiling mode-b)."""
    import yaml
    audit_path = DECISIONS_DIR / f"{slug}-audit-{template}.yaml"
    prior = (_read_yaml(audit_path) or {}) if audit_path.exists() else {}
    # passes: 0 (a prior ABORT burned no pass) must stay 0 — only a genuinely ABSENT field on a
    # legacy file defaults to 1 (T-0349 audit-post F1: `or 1` coerced 0 → 1, tripping the ceiling early).
    prior_passes = (int(prior["passes"]) if prior.get("passes") is not None else 1) if prior else 0
    # T-9286 — plan-gate ceiling owner-reset consult-GOVERNS escape (SPEC-0124 §Plan-target parity).
    # At the ceiling a plan gate normally escalates to the owner; with --owner-reset AND a fresh
    # single-survivor converged consult for THIS gate (matched on the gate's RECORDED signature —
    # INV-1 gate id + INV-2 fingerprint), the FULL consult GOVERNS: carry its verdict VERBATIM, no
    # auditor re-invocation. Plan owner-reset is consult-governed ONLY (no bare owner-authorized
    # fallback): a stale / multi-survivor / ABORT / missing / wrong-gate consult → REFUSE + escalate.
    _consult_carry = None
    _trend_ceiling_grant = False
    _worker_auto_consult = False
    if blocking and prior_passes >= AUDIT_PASS_CEILING:
        gate_id = _PLAN_TEMPLATE_TO_GATE_ID.get(template)
        # T-9717 (L2 parity with T-9682/T-9702) — TREND-AWARE ceiling grant for the EARLY plan gates.
        # Pure f(prior record): when the recorded finding-count trend is strictly DECREASING with LOW
        # residual severity AND prior_passes == the flat cap (the one pass the +1 unblocks), grant ONE
        # bounded extra pass — the same single +1 mechanic as --owner-reset, but AUTONOMOUS (no owner
        # ask). BOUNDED to +1: it fires ONLY at prior_passes == AUDIT_PASS_CEILING, so a second
        # still-decreasing step at cap+1 stays blocked; a FLAT/GROWING/high-residual trend blocks too.
        # Gated on `not owner_reset` so an explicit --owner-reset keeps its UNCHANGED T-9286
        # consult-governs path (a trend grant never preempts the owner's explicit reset).
        trend_grant = (not owner_reset and prior_passes == AUDIT_PASS_CEILING
                       and is_trend_convergence_grant(prior))
        # T-9717 (L3 parity with T-9683/T-9702) — DISPATCHED-worker AUTO-consult. A headless worker
        # (YITC_EXPECTED_SESSION_REF set) cannot self-grant the owner-gated --owner-reset, so at the
        # ceiling it would die-but-unlanded. Instead it AUTO-runs THIS gate's plan-gate consult (an
        # AUDITOR adjudication, NOT an owner decision) via the SHARED consult engine
        # (build_plan_consult_prompt + _consult_adjudicate — the SAME the finalization ceiling T-9702
        # and the interactive `audit consult --plan --gate` use) with the TWO fixed framed options; on
        # a CLEAN single TECHNICAL survivor (option-1 PROCEED) it flips owner_reset=True so the EXISTING
        # T-9286 consult-governs branch below carries the fresh consult's verdict WITHOUT an owner ask.
        # FAIL-CLOSED: a value/design ambiguity (option-2 HOLD), RED, ABORT, or >1 survivor keeps
        # owner_reset False → escalate. Interactive sessions (no worker ref) are UNTOUCHED.
        _worker_ref = os.environ.get("YITC_EXPECTED_SESSION_REF", "").strip()
        if not trend_grant and not owner_reset and gate_id and _worker_ref:
            cur_sig = _plan_gate_recorded_signature(slug, gate_id)
            if cur_sig:
                _auto_opts = [AUTO_CONSULT_PROCEED_OPTION, AUTO_CONSULT_HOLD_OPTION]
                _auto_prompt = build_plan_consult_prompt(
                    slug, gate_id, _auto_opts, fm, body,
                    _PLAN_AUDIT_LENS=_PLAN_AUDIT_LENS, _plan_fsm_line=_plan_fsm_line,
                    _PLAN_CONSULT_GATE_AUDIT=_PLAN_CONSULT_GATE_AUDIT, DECISIONS_DIR=DECISIONS_DIR)
                print(f"# audit-loop ceiling reached for {slug} {gate_id} (dispatched worker) — "
                      f"AUTO-running the ceiling-convergence consult before any owner escalation "
                      f"(T-9717/T-9683, SPEC-0124 §Audit-loop ceiling).", file=sys.stderr)
                _auto_provider = _resolve_audit_provider(True)
                _ca, _csurv, _crec, _cpath = _consult_adjudicate(
                    slug, gate_id, True, _auto_opts, _auto_prompt, _auto_prompt[:200],
                    prior_passes, cur_sig,
                    _auto_provider, audit_lib.resolve_model_for_provider(_resolve_audit_model, True, _auto_provider),
                    _resolve_audit_effort(True),   # T-12350: provider first (admission)
                    _invoke_auditor=_invoke_auditor, _parse_consult_result=_parse_consult_result,
                    _strip_degenerate_tail=_strip_degenerate_tail, _append_event=_append_event,
                    _utc_now_iso=_utc_now_iso, _plan_content_hash=_plan_content_hash,
                    _auto_rebuild_graph=_auto_rebuild_graph, write_text_atomic=write_text_atomic,
                    _die=_die, REPO_ROOT=REPO_ROOT,
                    # SPEC-0200 (T-12182) — the PLAN-GATE producer takes the SAME contract
                    # injections the task producers do. That identity is what rule 9's «both
                    # producers comply by construction» means operationally: the plan gate is not a
                    # second adjudication path, it is the same engine with a plan-shaped lens.
                    _with_repo_lock=_with_repo_lock, _iter_events=_iter_events,
                    events_path=EVENTS_PATH, _file_followup=_file_followup,
                    _parse_audit_verdict=_parse_audit_verdict_c1,
                    lens=(_plan_gate_lens(gate_id) if _plan_gate_lens else set()))
                # FAIL-CLOSED grant gate: verdict GREEN/YELLOW, EXACTLY one survivor, AND survivor ==
                # option-1 (PROCEED, not the HOLD option). Anything else escalates below (unchanged).
                if (_ca.get("verdict") in ("GREEN", "YELLOW")
                        and len(_csurv) == 1 and _csurv[0] == 1):
                    owner_reset = True
                    _worker_auto_consult = True
                    _append_event("audit_worker_auto_consult_granted", None, {
                        "slug": slug, "gate": gate_id, "prior_passes": prior_passes,
                        "granted_pass": prior_passes + 1,
                        "consult": str(_cpath.relative_to(REPO_ROOT)), "verdict": _ca.get("verdict"),
                        "worker_ref": _worker_ref, "pass_ceiling": AUDIT_PASS_CEILING})
                    print(f"# audit-loop ceiling: DISPATCHED-WORKER AUTO-CONSULT grant — the auto-run "
                          f"{gate_id} consult converged to the clean TECHNICAL-PROCEED survivor "
                          f"({_ca.get('verdict')}) for {slug}; granting the consult-governed "
                          f"continuation (pass {prior_passes + 1}) WITHOUT an owner ask "
                          f"(T-9717/T-9683, SPEC-0124).", file=sys.stderr)
                else:
                    print(f"# audit-loop ceiling: DISPATCHED-WORKER AUTO-CONSULT did NOT converge to a "
                          f"clean single TECHNICAL survivor (verdict={_ca.get('verdict')}, "
                          f"survivors={_csurv}) for {slug} {gate_id} — value/design ambiguity or "
                          f"non-convergence. HOLDING; escalating to the owner (T-9717/T-9683, "
                          f"SPEC-0124).", file=sys.stderr)
        if owner_reset and gate_id:
            cur_sig = _plan_gate_recorded_signature(slug, gate_id)
            cstatus, cfile, creason = _consult_basis(
                slug, gate_id, cur_sig,
                consult_cmd_hint=f"yitc-v2 audit consult --plan {slug} --gate {gate_id} --option … --option …")
            if cstatus == "consult":
                # SPEC-0200 rule 7, PLAN-GATE arm (T-12182). A plan has NO park, `return_trigger` or
                # `wont-do`: when an episode on this gate ends on a terminal — row 15, row 16, or the
                # rule-4 pre-matrix non-admissible terminal — the plan simply STAYS at its current FSM
                # stage, and its ceiling closes ONLY through a consult-governed PROCEED. So the reset
                # is admitted by a recorded `outcome: proceed` on the CURRENT episode and by nothing
                # else. The explicit owner action opens a NEW episode (round 0, n+1) on the SAME gate,
                # and THAT episode's PROCEED is what this verifies — there is no bare
                # owner-authorized fallback for a plan gate (SPEC-0124 §Plan-target parity).
                #
                # LEGACY-TOLERANT, deliberately: a record carrying NO `outcome` at all predates this
                # contract and is left to the unchanged `_read_consult_adjudication` convergence check
                # below. The new gate BINDS a record that HAS an outcome, so it can only ever refuse a
                # terminal the old check would have admitted — it never admits one the old check
                # refused.
                _crec_raw = _read_yaml(REPO_ROOT / cfile) if (REPO_ROOT / cfile).exists() else None
                if isinstance(_crec_raw, dict) and _crec_raw.get("outcome") \
                        and not audit_lib.consult_plan_reset_admitted(_crec_raw):
                    _die(f"{slug}: --owner-reset REFUSED at the {template} gate (SPEC-0200 rule 7, "
                         f"plan-gate arm). The consult episode "
                         f"{_crec_raw.get('episode_id') or '(unrecorded)'} on gate {gate_id} recorded "
                         f"`outcome: {_crec_raw.get('outcome')}`"
                         + (f" / `terminal_reason: {_crec_raw.get('terminal_reason')}`"
                            if _crec_raw.get("terminal_reason") else "")
                         + f", not PROCEED. "
                         + audit_lib.consult_terminal_owner_route(_crec_raw, is_plan=True,
                                                                 target_id=slug,
                                                                 consult_key=gate_id)
                         + " (no pass burned — this refusal fired before any auditor invocation).")
                adj = _read_consult_adjudication(cfile, expected_basis_fp=cur_sig)
                if adj is None:
                    _die(f"{slug}: --owner-reset consult-governs at the {template} gate: the verified "
                         f"consult basis {cfile} could not be re-read as a converged single-survivor "
                         f"GREEN/YELLOW verdict — re-run `audit consult --plan {slug} --gate {gate_id}` "
                         f"or escalate to the owner.")
                _consult_carry = (cfile, adj)
            else:
                _die(f"{slug}: --owner-reset refused at the {template} gate: {creason}. A plan gate "
                     f"owner-reset is CONSULT-GOVERNED ONLY — escalate to the owner per SPEC-0124 "
                     f"§Plan-target parity (no bare owner-authorized fallback for a plan gate).")
        elif trend_grant:
            # GRANT-MOMENT JOURNAL — emit the grant NOW, BEFORE the (minutes-long, possibly-ABORTing)
            # auditor invocation, so the grant is journal-visible at the instant granted; the completed
            # audit YAML ALSO carries `trend_ceiling_grant: true` (the durable trail). Then FALL THROUGH
            # (no _die, no _consult_carry) so the normal auditor invocation below RUNS as the granted pass.
            _trend_ceiling_grant = True
            _trend_counts = finding_count_trend(prior)
            _residual_sev = sorted({str(f.get("severity") or "").lower()
                                    for f in (prior.get("findings") or [])
                                    if isinstance(f, dict)}) or ["none"]
            _append_event("audit_ceiling_trend_grant", None, {
                "slug": slug, "gate": gate_id, "template": template,
                "prior_passes": prior_passes, "granted_pass": prior_passes + 1,
                "trend": _trend_counts, "residual_severity": _residual_sev,
                "pass_ceiling": AUDIT_PASS_CEILING})
            print(f"# audit-loop ceiling: TREND GRANT — recorded finding-count trend {_trend_counts} is "
                  f"strictly decreasing with low residual severity for {slug} {template}; granting ONE "
                  f"bounded extra pass (pass {prior_passes + 1}) past the flat {AUDIT_PASS_CEILING}-pass "
                  f"cap (T-9717/T-9682, SPEC-0124 §Audit-loop ceiling).", file=sys.stderr)
        else:
            # T-11250 (kupiclub X-0974) — PRINT THE EXACT COMMAND, do not make the caller derive it.
            # This refusal is reached precisely when the caller is already blocked and under time
            # pressure, and it used to name the gate ONLY by its audit-TEMPLATE name (`gate-executing`)
            # while prescribing "a converged plan consult" with no invocation. `--stage` is the
            # nearest-named flag on that very verb and takes {pre,post}, so the obvious reading dies
            # on an argparse error — two failed invocations, reported. `gate_id` (computed above from
            # _PLAN_TEMPLATE_TO_GATE_ID) IS the `--gate` token, so the command can simply be spelled.
            # The template name stays — it is the audit RECORD's name, visible in the filename right
            # there — but the two identifiers are now told apart instead of left to collide. Nothing
            # in the parser is widened: the fix is entirely in this text (SPEC-0124 owns the gate
            # identity). Same discipline as the `land` recovery line, and the reporter's own ask.
            _consult_cmd = (f'yitc-v2 audit consult --plan {slug} --gate {gate_id} --full '
                            f'--option "<proceed: …>" --option "<hold: …>"') if gate_id else None
            _die(f"{slug}: audit-loop ceiling reached at the {template} gate ({prior_passes} passes on "
                 f"record in {audit_path.name}); pass {prior_passes + 1} = escalate to owner per "
                 f"CHARTER §audit-loop-ceiling — never silent-loop"
                 + ("" if owner_reset else
                    " (a converged plan consult + the gate verb `--owner-reset` may continue ONE pass).")
                 + ("" if (owner_reset or not _consult_cmd) else
                    f"\nRun, verbatim:\n"
                    f"  1) {_consult_cmd}\n"
                    f"  2) re-run this gate verb with --owner-reset\n"
                    f"NOTE the two identifiers are DIFFERENT and both are real: `{template}` is the "
                    f"audit-record/template name printed above, `{gate_id}` is the value "
                    f"`audit consult --gate` takes (SPEC-0124 gate identity). The consult flag is "
                    f"`--gate`, NOT `--stage` — `--stage` exists on that verb but is the TASK axis "
                    f"and takes only pre|post."))
    tmpl = _plan_gate_template_text(template)

    def _save(audit: dict) -> None:
        content = state.dump(audit)
        rt = state.load_str(content)
        if not isinstance(rt, dict) or rt.get("target_id") != slug or rt.get("target_kind") != "plan":
            _die("SPEC-0001 self-test failed: plan-gate audit YAML did not round-trip")
        write_text_atomic(audit_path, content)
        _append_event("draft_checked", None, {
            "slug": slug, "verdict": audit["verdict"], "findings_count": len(audit["findings"]),
            "stage_template": template, "gate_policy": gate_policy,
            "saved_to": str(audit_path.relative_to(REPO_ROOT))})

    base = {"target_kind": "plan", "target_id": slug, "stage": template,
            "stage_template": template, "gate_policy": gate_policy,
            "date": _utc_now_iso()[:10], "content_hash": _plan_content_hash(body)}
    if card_set_fp is not None:
        # SPEC-0070 §4 — the decomposition-fidelity freshness basis: the verdict is bound to the CUT
        # (card-set fingerprint). `plan stage executing` recomputes + requires an EXACT match, so a cut
        # edited after the audit re-fingerprints → stale → re-audit. Only the gate-executing run passes it.
        base["card_set_fingerprint"] = card_set_fp
    if _consult_carry is not None:
        # T-9286 consult-GOVERNS carry: the FULL ceiling-convergence consult already adjudicated this
        # gate — record its verdict VERBATIM (no auditor re-invocation), mirroring the task T-0522 path.
        cfile, adj = _consult_carry
        cverdict = adj["verdict"]
        cfindings = ([] if cverdict == "GREEN" else [{
            "severity": "low",
            "what": f"consult-governed residual: surviving option {adj.get('recommendation')} carried "
                    f"from the FULL ceiling-convergence consult",
            "where": cfile,
            "fix": adj.get("survivor_text") or "(see the consult survivor)"}])
        audit = {**base, "verdict": cverdict, "passes": prior_passes + 1, "commit": None,
                 "findings": cfindings, "absorbed": [], "followups": [],
                 "owner_reset": True, "owner_reset_basis": f"consult:{cfile}", "consult_governed": True,
                 # T-9717 — durable marker: when a DISPATCHED-worker auto-consult (L3) drove this
                 # consult-governed continuation (not an owner-passed --owner-reset), record it (the
                 # audit YAML analog of cmd_audit's worker_auto_consult marker, T-9683/T-9702).
                 **({"worker_auto_consult": True} if _worker_auto_consult else {}),
                 "auditor_provider": "external-auditor-full",
                 "prompt_excerpt": f"(consult-governed — no auditor call; basis {cfile})",
                 "notes": (f"T-9286 consult-GOVERNS: carried verdict {cverdict} from {cfile} "
                           f"(recommendation {adj.get('recommendation')}); no auditor re-invocation "
                           f"(SPEC-0124 §Plan-target parity)."
                           + (" DISPATCHED-worker auto-consult (T-9717 L3)." if _worker_auto_consult else ""))}
        _save(audit)
        print(f"{slug} {template} gate ({gate_policy}): {cverdict} (consult-governed owner-reset, "
              f"pass {prior_passes + 1}) -> {audit_path.relative_to(REPO_ROOT)}")
        return cverdict
    if tmpl is None:
        # Template home broken/unavailable — the policy split (T-0349 audit-pre F1). NOTE (T-9316/F-010,
        # kernel-pin T-10581/X-0433): the PRIMARY -C path never reaches here — `_plan_gate_template_text`
        # routes through `_find_spec_path(..., force_engine=True)` (the SPEC-0092 KERNEL-PINNED path), so a
        # consumer resolves the real per-gate template from the KERNEL SPEC-0036 even when it OWNS a
        # colliding product spec at the same id (the auditor config resolves at the engine path too,
        # T-9313) and records a REAL verdict. Reaching this branch means the KERNEL template is
        # unavailable/unresolved (the spec is missing OR its required P-anchor is absent) — for the
        # MANDATORY-BLOCKING gate-specs gate that is fail-closed BEFORE any `_save`,
        # so NO ABORT record is written (the perpetual-ABORT symptom the friction described pre-dates
        # T-9282's advisory→blocking flip and no longer occurs).
        if blocking:
            _die(f"{slug}: the {template} question template is unavailable from "
                 f"{PLAN_GATE_TEMPLATE_SPEC} (spec or P-anchor missing) — a MANDATORY-BLOCKING "
                 f"gate fails CLOSED. Fix the template home, then retry (no pass burned).")
        audit = {**base, "verdict": "ABORT", "passes": prior_passes, "commit": None,
                 "findings": [], "absorbed": [], "followups": [],
                 "auditor_provider": "external-auditor-full", "prompt_excerpt": "",
                 "notes": f"{template} template unavailable from {PLAN_GATE_TEMPLATE_SPEC} — "
                          f"advisory gate proceeds without an ask (never holds); fix the template home."}
        _save(audit)
        print(f"# WARNING: {template} template unavailable from {PLAN_GATE_TEMPLATE_SPEC} — "
              f"advisory gate recorded ABORT and proceeds (fix the template home).", file=sys.stderr)
        print(f"{slug} {template} gate: ABORT (template unavailable) -> "
              f"{audit_path.relative_to(REPO_ROOT)}")
        return "ABORT"
    provider = _resolve_audit_provider(True)  # plan-level audits run FULL-capability (SPEC-0034 audit
    model = audit_lib.resolve_model_for_provider(_resolve_audit_model, True, provider)   # posture); T-12350: provider first (admission)
    prompt = (f"{_PLAN_AUDIT_LENS}"
              f"\n## Authoritative plan FSM\n{_plan_fsm_line()}\n"
              f"\n## Gate question template ({template} — {PLAN_GATE_TEMPLATE_SPEC}, "
              f"policy: {gate_policy})\n\nAnswer EACH question of the template against the plan "
              f"below; ground the verdict in them:\n\n{tmpl}\n"
              f"\n## Plan {slug}\n\nfrontmatter: {fm}\n\n{body}\n"
              + (f"\n## Decomposition — the filed task CARD SET (audit the CUT against the plan)\n"
                 f"{extra_context}\n" if extra_context else ""))
    print(f"# Invoking external auditor: {provider}/{model} (full) — {template} gate "
          f"({gate_policy}) on plan {slug}...", file=sys.stderr)
    rc, stdout, stderr = audit_lib.invoke_auditor_tiered(_invoke_auditor, provider, prompt, model, full=True)   # T-12350
    if rc != 0:
        verdict, findings, parse_notes = "ABORT", [], f"auditor exit {rc}: {stderr[:500]}"
    else:
        verdict, findings, parse_notes = _parse_audit_verdict(stdout)
    passes = prior_passes + (0 if verdict == "ABORT" else 1)   # ABORT burns no pass
    audit = {**base, "verdict": verdict, "passes": passes, "commit": None,
             "findings": findings, "absorbed": [], "followups": [],
             # T-9717 — durable marker: this pass was granted past the flat cap by the L2 trend grant
             # (the audit YAML analog of cmd_audit's trend_ceiling_grant, T-9682/T-9702).
             **({"trend_ceiling_grant": True} if _trend_ceiling_grant else {}),
             "auditor_provider": "external-auditor-full", "prompt_excerpt": prompt[:200],
             "notes": parse_notes or f"Raw stdout captured ({len(stdout)} chars)."}
    if rc != 0:
        audit["notes"] = (f"auditor exit {rc}: {stderr[:500]}\n\n--- stdout tail ---\n"
                          f"{_strip_degenerate_tail(stdout)[-2000:]}")
    elif verdict in ("YELLOW", "RED") or not findings:
        _clean = _strip_degenerate_tail(stdout)
        audit["notes"] = f"{audit['notes']}\n\n--- stdout tail ---\n{_clean[-2000:]}"
    # T-12350 (SPEC-0201 rule 2) — the ONE saved-verdict writer helper, on the branch that actually
    # invoked an auditor (the consult-governed carry and the template-unavailable ABORT above ran none).
    audit_lib.stamp_auditor_verdict(audit, provider=provider, model=model, full=True,
                                    target_kind="plan", target_id=slug, stage=template,
                                    append_event=_append_event)
    _save(audit)
    print(f"{slug} {template} gate ({gate_policy}): {verdict} ({len(findings)} findings) -> "
          f"{audit_path.relative_to(REPO_ROOT)}")
    if blocking and verdict in ("RED", "ABORT"):
        _die(f"{slug}: the {template} gate is MANDATORY-BLOCKING and the verdict is {verdict} — "
             f"the transition is held (status unchanged). "
             + ("Absorb the findings and retry (ceiling: 2 passes)." if verdict == "RED"
                else "Auditor unavailable/malformed — don't proceed without a verdict; retry "
                     "(no pass burned)."))
    return verdict


def _build_draft_check_prompt(slug: str, fm: dict, body: str, large: bool,
                              template_name: str = None, template_text: str = None,
                              focus: str = None, sf=_SF_UNSET, coverage_out: "dict | None" = None, *, _PLAN_AUDIT_LENS, _plan_draft_corpus_audit_block, _plan_fsm_line, _plan_scenario_fidelity, _is_consumer_build=None) -> str:
    """V2-lens prompt for the plan accept-gate audit (+ big-plan-checklist when large; + the
    T-0332 draft-spec corpus-conflict block when the plan has PLAN-BORN draft specs; + the
    SPEC-0036 status-selected question template with the authoritative FSM line — P1 at draft,
    the P4 trial-evidence block at trial — T-0349)."""
    checklist = ""
    if large:
        checklist = (
            "\n## Big-plan checklist (this draft is large — apply all 6 probes)\n"
            "P1 deferred/parked items traversed? P2 per-layer ship status explicit? "
            "P3 done-definition owner-aligned? P4 external review done? "
            "P5 cross-checked against existing patterns? P6 quantitative claims grounded?\n"
        )
    template_block = ""
    if template_text:
        template_block = (
            f"\n## Authoritative plan FSM\n{_plan_fsm_line()}\n"
            f"\n## Question template ({template_name} — {PLAN_GATE_TEMPLATE_SPEC})\n\n"
            f"Answer EACH question of the template against the plan below; ground the verdict "
            f"in them:\n\n{template_text}\n")
    focus_block = ""
    if focus:
        # T-0350 (SPEC-0036 --focus): the composable owner/session append — DIRECTLY AFTER the
        # stage template block (never replacing it; after lens/checklist when no template applies).
        focus_block = (
            f"\n## Focus questions (owner/session --focus append — SPEC-0036)\n\n"
            f"Answer these IN ADDITION to the template above (the append never replaces it):\n\n"
            f"{focus}\n")
    # T-10917 — `coverage_out` rides through untouched to the block builder's reach sink; the prompt
    # text is identical with or without it.
    corpus_block = _plan_draft_corpus_audit_block(slug, coverage_out)
    # SPEC-0082 — ADVISORY §5 cue: a POINTER (by reference, never copied rule-text — SPEC-0076 stays the
    # sole normative home, P5) added ONLY when the plan declares scenario_roles. Non-recorded /
    # non-freshness / non-gating; a no-scenario_roles plan gets NO addition (the strict no-op — the prompt
    # is byte-identical, so prompt_excerpt + the auditor verdict are unchanged).
    if sf is _SF_UNSET:                          # not precomputed by the caller → derive it here
        sf = _plan_scenario_fidelity(fm)
    scenario_cue = ""
    if sf is not None:
        scenario_cue = (
            "\n## Scenario-fidelity (advisory — SPEC-0076 §5/§6, by reference)\n\n"
            "This plan declares `scenario_roles`. Orient to SPEC-0076 §5/§6 (the scenario-conformance "
            f"rules — read them via `{graph_lib.spec_query_hint('SPEC-0076', is_consumer=bool(_is_consumer_build and _is_consumer_build()), cli='yitc-v2')}`; "
            "NOT copied here) when judging whether "
            "the plan's user-path claims are coherent. This cue is ADVISORY — it does NOT enter the "
            "recorded scenario-fidelity result or the freshness fingerprint, and it never gates.\n")
    return (f"{_PLAN_AUDIT_LENS}{checklist}{template_block}{focus_block}{scenario_cue}"
            f"\n## Plan {slug}\n\nfrontmatter: {fm}\n\n{body}\n{corpus_block}")


def _plan_has_checklist_pass(body: str) -> bool:
    """True if the plan declares a real `checklist_pass:` block — the big-plan 7-probe self-traversal
    (patterns/big-plan-checklist.md §Filing format). A line-anchored `checklist_pass:` key satisfied by
    EITHER an inline FLOW mapping carrying a probe (`checklist_pass: {P1: documented, ...}`) OR ≥1
    indented `P<n>:` mapping line in the block that follows — scanned until the block ends (the next
    non-blank, non-indented line), NOT a fixed character window. The flow-brace / indented-mapping
    shape means a bare prose P-token on the key line does NOT suppress the WARN (audit-pre F1 / audit-
    post F1), and scanning to the block boundary means a probe far down a long block is still seen
    (audit-post F2). Detection for a WARN — NOT a structured-YAML validator (report-not-block spirit;
    per-probe value validation stays the auditor's job)."""
    lines = body.splitlines()
    for i, ln in enumerate(lines):
        m = _PLAN_CHECKLIST_KEY_RE.match(ln)
        if not m:
            continue
        if _PLAN_CHECKLIST_INLINE_RE.search(m.group(1)):   # inline flow mapping on the key line
            return True
        for nxt in lines[i + 1:]:                           # following block — scan until it ends
            if not nxt.strip():
                continue                                    # blank lines inside the block are fine
            if not nxt[:1].isspace():
                break                                       # a non-indented line ends the block
            if _PLAN_CHECKLIST_PROBE_RE.match(nxt):
                return True
    return False


def _plan_missing_checklist_pass_finding(large: bool, body: str, *, _plan_has_checklist_pass) -> list:
    """LARGE-only WARN (SPEC-0034 mandatory big-plan check at the pre-`executing` gate): a large plan
    with no `checklist_pass` self-traversal block → one structural-shaped finding (severity:low,
    source:structural). REPORT-NOT-BLOCK — recorded in the `plan check` verdict, never flips it."""
    if not large or _plan_has_checklist_pass(body):
        return []
    return [{
        "severity": "low", "source": "structural",
        "what": "LARGE plan has no `checklist_pass` block (the big-plan 7-probe self-traversal)",
        "where": "plan body (opening section)",
        "fix": "add the `checklist_pass:` block (P1–P7) per patterns/big-plan-checklist.md §Filing "
               "format before the pre-`executing` gate (SPEC-0012 structural pre-pass; report-not-block)"}]


def cmd_plan_check(args: argparse.Namespace, *, DECISIONS_DIR, PLANS_DIR, REPO_ROOT, _PLAN_CONSULT_GATE_AUDIT, _append_event, _build_draft_check_prompt, _die, _governing_contract_for, _invoke_auditor, _load_draft, _parse_audit_verdict, _plan_accept_freshness_hash, _plan_content_hash, _plan_gate_template_text, _plan_missing_checklist_pass_finding, _plan_scenario_fidelity, _plan_structural_findings, _read_yaml, _require_reads, _require_writing_worktree, _resolve_audit_model, _resolve_audit_provider, _strip_degenerate_tail, _utc_now_iso, write_text_atomic) -> None:
    """Promote-gate verification (D-0034): run the external auditor on the draft, record the
    verdict to decisions/<slug>-audit.yaml. Does NOT change status (verification is an action,
    not а persisted state — it decays; take-into-work re-checks currency). No autosync/rebuild."""
    # T-11249 (kupiclub X-0970) — SAY WHICH CHECKOUT THIS VERDICT RESTS ON, before anything else.
    # Diagnostic only, on stderr: every stdout contract stays byte-identical, and it sits beside
    # the sibling `# audit-loop ceiling:` notes. UNCONDITIONAL by design — the cost being removed
    # is the SILENCE, and a line that appears only when the engine already suspects a mismatch is
    # the same silence with extra steps. FIRST statement in the body, ahead of
    # `_require_writing_worktree()`: a wrong-tree invocation is exactly what that guard refuses,
    # so its refusal needs the tree named too.
    print(observe.checkout_provenance_line(REPO_ROOT, verb="plan check"), file=sys.stderr)
    # T-0399 / E-0014: writes decisions/<slug>-audit.yaml — bound by the D-0037/D-0051 write-
    # isolation guard (mirror of cmd_task_file). `plan check` is the plan-gate filing, taken in a
    # work/<slug> worktree; a main-checkout invocation is refused with the hint before any verdict
    # is written. This is the verb behind the recurring plan-check-verdict-written-on-main-blocks-land
    # fingerprint (E-0014, x3 over 2 days).
    _require_writing_worktree()
    import yaml
    path, fm, body = _load_draft(args.slug, dirs=(PLANS_DIR,))
    slug = fm.get("id") or args.slug
    # T-0599 — read-check graduation onto the plan-axis `accepted` work-verb (SPEC-0050 §6 / SPEC-0059):
    # `plan check` is the accept-gate audit (the plan `accepted` stage), so it REFUSES — BEFORE the costly
    # external-auditor invocation below — unless THIS session fetched the plan `accepted` stage bundle
    # (plan-stage-entry:accepted = [SPEC-0034]; the verb-governance SPEC-0034/0046 is a DISTINCT concern).
    _require_reads("stage", {"axis": "plan", "stage": "accepted", "verb": "plan check",
                             "action": "plan accept-gate check"})
    # T-11986 — MODE-(b) ABSORPTION on the ACCEPT-GATE verdict, the plan-CHECK sibling of the two
    # shipped absorb routes (`audit pre --task --absorb`, T-10770; `audit pre --plan --gate --absorb`,
    # T-11167). SPEC-0124 governs the accept gate by the same mode-a/mode-b rule, but the only mode-(b)
    # path onto THIS record was `audit pre --plan <slug> --gate trial-accepted --absorb` — a spelling an
    # operator holding a YELLOW `plan check` does not reach for. So a YELLOW residual got absorbed by
    # EDITING THE PLAN BODY, which re-hashes it and forces a whole new FULL `plan check` (measured
    # 2026-09-02: plan audit-friction-packet-contract-ac-contract-so-pre- paid exactly that extra full
    # check to absorb five findings; the T-9342 3-plan-check incident is the same class).
    #
    # NO SECOND WRITER: this branch resolves the SAME record through the SAME `_PLAN_CONSULT_GATE_AUDIT`
    # gate identity and delegates to the SAME `absorb_into_plan_gate_record` symbol — the accept-gate
    # verdict `decisions/<slug>-audit.yaml` IS that map's `trial-accepted` record. Ceiling-neutrality,
    # the absent-record refusal and the non-YELLOW refusal are the helper's, unchanged and not re-stated.
    #
    # Placed AFTER `_require_writing_worktree()` + `_load_draft` + the plan-`accepted` read-gate (this
    # route WRITES the governed record, so it is held to the same gates as the check it edits) and
    # BEFORE the prompt/auditor below — so no auditor can run and no pass can be bought.
    # PRESENCE, not truthiness (audit-post finding 1): `--absorb ""` is a MALFORMED absorb, not an
    # absent one. Branching on the stripped truthiness let an empty/whitespace value fall through to
    # the full check below and SPEND AN AUDITOR PASS — the exact cost this route exists to avoid. The
    # empty-text refusal is the SHARED helper's (it already owns it for both sibling routes), so the
    # raw value is passed through rather than pre-validated here — one refusal, one home.
    absorb_text = getattr(args, "absorb", None)
    if absorb_text is not None:
        audit_path = DECISIONS_DIR / f"{slug}-audit.yaml"
        if not audit_path.exists():
            _die(f"{slug}: no `plan check` verdict on record — mode-(b) absorption records a residual "
                 f"INTO an existing accept-gate verdict (decisions/{audit_path.name}); it never CREATES "
                 f"one, which would be an unaudited verdict. Run `yitc-v2 plan check {slug}` first.")
        # BODY-DRIFT REFUSAL — the one guard that is this route's OWN, not the helper's. Absorption is
        # cheap precisely because the recorded verdict still judges the CURRENT body; once the body has
        # moved, the verdict is stale by `_plan_accept_core`'s own content-hash test and the honest
        # answer is a fresh check, not a note appended to a verdict that no longer covers the text. So
        # a body edit STILL forces a new `plan check` — this route removes the forced re-check ONLY for
        # the case where nothing about the plan changed.
        rec = _read_yaml(audit_path) or {}
        recorded = rec.get("content_hash") if isinstance(rec, dict) else None
        if not recorded:
            _die(f"{slug}: the recorded `plan check` verdict carries no content_hash (it predates "
                 f"content-hash freshness), so absorption cannot prove it still covers the current "
                 f"body — re-run `yitc-v2 plan check {slug}`.")
        if recorded != _plan_content_hash(body):
            _die(f"{slug}: plan edited since the check (content hash mismatch) — the verdict is stale, "
                 f"so there is nothing current to absorb INTO. Mode-(b) absorption applies to a residual "
                 f"on the verdict that judged THIS body; a body edit still forces a fresh check. "
                 f"Re-run `yitc-v2 plan check {slug}`.")
        audit_lib.absorb_into_plan_gate_record(
            slug, "trial-accepted", absorb_text,
            decisions_dir=DECISIONS_DIR, repo_root=REPO_ROOT,
            gate_audit_map=_PLAN_CONSULT_GATE_AUDIT,
            _die=_die, _append_event=_append_event, _utc_now_iso=_utc_now_iso,
            write_text_atomic=write_text_atomic, _governing_contract_for=_governing_contract_for,
            invocation=f"yitc-v2 plan check {slug} --absorb")
        print(f"note: the accept-gate verdict / content_hash / accept_freshness_hash are UNCHANGED — "
              f"`plan stage accepted` still accepts this record, and no ceiling pass was burned.")
        return
    n_lines = len([ln for ln in body.splitlines() if ln.strip()])
    large = _plan_is_large(body)   # the SHARED big-plan predicate (T-9350 — agrees with the finalize pre-pass)
    # T-0386 — `plan check` is a plan-lifecycle-transition audit, so the model posture is FULL,
    # never routine, regardless of size or --full (SPEC-0034 §Audit posture, owner-settled
    # 2026-06-05: FULL "OVERRIDES the AGENTS §External-auditor routine→light default for PLAN-level
    # audits"). `large` no longer governs MODEL selection (it was a strict subset of "always full");
    # it still drives the big-plan-checklist below (the `large` flag). --full is now a harmless no-op
    # (kept for backward-compat). Closes the `plan-check-routine-model-contradicts-spec-0034-full-posture`
    # deviation.
    full = True
    provider = _resolve_audit_provider(full)   # T-12350: provider first (admission)
    model = audit_lib.resolve_model_for_provider(_resolve_audit_model, full, provider)
    # T-0349 — SPEC-0036 status-selected question template (the selection carrier is the VERB
    # invocation + the plan's live status, never a bare flag): draft → the P1 shaping template
    # (on-demand, advisory; text missing → pre-T-0349 lens fallback + note); trial → the P4
    # trial-evidence block joins THIS accept-gate prompt (MANDATORY-BLOCKING when a trial ran;
    # text missing → fail CLOSED); other active statuses → the unchanged accept-gate lens
    # (recorded as plan-check / on-demand — the T-0348 values).
    status = fm.get("status") or "draft"
    template_note = ""
    if status == "draft":
        stage_template, gate_policy = "plan-draft", "on-demand"
        template_text = _plan_gate_template_text("plan-draft")
        if template_text is None:
            stage_template = "plan-check"   # honest: P1 was NOT asked — the lens fallback ran
            template_note = (f"plan-draft (P1) template unavailable from {PLAN_GATE_TEMPLATE_SPEC} "
                             f"— fell back to the plain accept-gate lens; fix the template home.")
    elif status == "trial":
        stage_template, gate_policy = "gate-accepted", "mandatory-blocking"
        template_text = _plan_gate_template_text("gate-accepted")
        if template_text is None:
            _die(f"{slug}: the gate-accepted (P4 trial-evidence) template is unavailable from "
                 f"{PLAN_GATE_TEMPLATE_SPEC} — a MANDATORY-BLOCKING surface fails CLOSED "
                 f"(SPEC-0036; T-0349 audit-pre F1). Fix the template home, then re-run.")
    else:
        stage_template, gate_policy, template_text = "plan-check", "on-demand", None
    # T-0350 (SPEC-0036 --focus) — RAW string preserved (byte-equal carrier; audit-post F1):
    _focus_raw = getattr(args, "focus", None)
    focus = _focus_raw if (_focus_raw and _focus_raw.strip()) else None
    # SPEC-0082 — compute the scenario-fidelity dimension ONCE per `plan check` (audit-post F2: the
    # single `_scenario_index_nodes()` reuse), then thread it into the prompt cue, the structural merge,
    # the verdict escalation, and the freshness hash. sf is None for the STRICT no-op (no/empty +
    # well-formed scenario_roles): nothing merged/recorded, no verdict change, no prompt cue → byte-
    # identical output.
    sf = _plan_scenario_fidelity(fm)
    # T-10917 — the reach sink: filled by the corpus-block builder while the prompt is assembled, read
    # back below to decide whether this gate actually covered the corpus it claims to judge.
    coverage = {}
    prompt = _build_draft_check_prompt(slug, fm, body, large,
                                       template_name=stage_template, template_text=template_text,
                                       focus=focus, sf=sf, coverage_out=coverage)
    prompt_excerpt = prompt[:200]   # opens at the fixed lens — the focus block is unreachable (T-0350 F3)
    print(f"# Invoking external auditor: {provider}/{model} ({'full' if full else 'routine'}) "
          f"on draft {slug} ({n_lines} body lines{'; LARGE → big-plan-checklist' if large else ''})...",
          file=sys.stderr)
    # T-0226 — structural pre-pass: deterministic, local, REPORT-NOT-BLOCK. Computed regardless of
    # the auditor outcome (even on ABORT) so the grep-able subset is ALWAYS recorded + cannot be
    # skipped like the T-0188 manual memo. WARN-level: does NOT flip the auditor `verdict`.
    structural = _plan_structural_findings(slug, body)
    # T-0320 — LARGE-plan `checklist_pass`-presence WARN (SPEC-0034 mandatory big-plan check); LARGE-only,
    # so gated here where `large` is known. Same report-not-block shape — flows untouched into the verdict.
    structural += _plan_missing_checklist_pass_finding(large, body)
    # SPEC-0082 — the malformed/overlap/unresolved findings ride the report-not-block structural bucket;
    # the baseline-fidelity MEDIUM findings are kept separate (they CONTRIBUTE the verdict).
    if sf:
        structural += sf["structural"]
    rc, stdout, stderr = audit_lib.invoke_auditor_tiered(_invoke_auditor, provider, prompt, model, full=full)   # T-12350
    if rc != 0:
        verdict, findings, parse_notes = "ABORT", [], f"auditor exit {rc}: {stderr[:500]}"
    else:
        verdict, findings, parse_notes = _parse_audit_verdict(stdout)
    # SPEC-0082 — a baseline-fidelity MEDIUM finding "contributes YELLOW": escalate a GREEN auditor
    # verdict to YELLOW (recorded + visible; NEVER RED, never a transition-refusing gate). A YELLOW /
    # RED / ABORT verdict passes through unchanged (the dimension never lowers severity).
    if sf and sf["medium"] and verdict == "GREEN":
        verdict = "YELLOW"
    # T-10917 (SPEC-0034 §accepted) — REACH before verdict: a gate that read only part of the corpus it
    # claims to judge must not render as a full pass. Same shape SPEC-0082 settled just above — one
    # report-not-block structural finding + a GREEN→YELLOW escalation, never RED (a partial read is a
    # statement about CONFIDENCE, not a proven defect) and never a lowering (YELLOW/RED/ABORT pass
    # through). STRICTLY CONDITIONAL: a full-reach run gets no finding, no key and no verdict change,
    # so the ordinary small-plan path stays byte-identical to pre-T-10917 output (AC2).
    corpus_coverage = _plan_corpus_coverage_shortfall(coverage, stdout if rc == 0 else "")
    if corpus_coverage:
        structural.append({"source": "corpus-coverage", "what": corpus_coverage["not_reached"]})
        if verdict == "GREEN":
            verdict = "YELLOW"
    # T-0348 — ONE canonical plan-audit verdict schema (P5/SPEC-0036): the legacy draft:/kind:
    # draft-check shape is RETIRED; this writer emits the canonical audit-result schema
    # (AGENTS §Saved audit result) extended by the SPEC-0036 additive fields stage_template /
    # gate_policy + the freshness extras (content_hash / accept_freshness_hash / large /
    # big_plan_checklist). Template SELECTION per plan status wired by T-0349 (see above).
    audit = {
        "target_kind": "plan", "target_id": slug,
        "stage": stage_template, "stage_template": stage_template, "gate_policy": gate_policy,
        "date": _utc_now_iso()[:10],
        "verdict": verdict, "content_hash": _plan_content_hash(body),
        # T-0332 — accept-gate freshness over the plan body + the PLAN-BORN draft specs + the
        # active+proposed corpus CONTENT; `_plan_accept_core` recomputes + compares so editing a
        # draft spec OR a corpus spec after this check stales the accept gate (AC2).
        "accept_freshness_hash": _plan_accept_freshness_hash(slug, body, fm, sf=sf),
        "large": large, "big_plan_checklist": large,
        "findings": findings, "structural_findings": structural, "absorbed": [], "followups": [],
        "auditor_provider": "external-auditor-full" if full else "external-auditor-routine",
        "prompt_excerpt": prompt_excerpt,
        "notes": parse_notes or f"Raw stdout captured ({len(stdout)} chars).",
    }
    # SPEC-0082 — record the scenario-fidelity result ONLY when the dimension applied (sf is not None);
    # a no/empty-scenario_roles plan gets NO key → the verdict YAML is byte-identical to pre-dimension
    # output (the strict negative invariant, AC1 / T-9268 case 3).
    if sf is not None:
        audit["scenario_fidelity_findings"] = sf["medium"] + sf["structural"]
    # T-10917 — additive ONLY on a shortfall: the key's very PRESENCE is the honest signal that this
    # verdict rests on a partial read; a full-reach gate writes no key (AC2 byte-identity).
    if corpus_coverage:
        audit["corpus_coverage"] = corpus_coverage
    # T-11299 (X-0999) — WAS THIS ABORT THE WALL-CLOCK BUDGET RUNNING OUT, or a governance stop?
    # `plan check` collapsed EVERY nonzero auditor rc into a bare ABORT, so the timeout cause survived
    # only as prose inside `notes:` ("auditor exit 124: timeout after 300s") — while LIFECYCLE Stage 4/8
    # define ABORT as STOP, i.e. a session behaving CORRECTLY escalates a TIMEOUT KNOB to the owner
    # (X-0999's measured cost). Classified through the SHARED, UNCHANGED, fail-closed `is_timeout_abort`
    # (T-9548), which demands ALL THREE of verdict==ABORT, findings==[] and rc==124 — so a genuine
    # auditor-unavailable (any other nonzero rc) and a substantive ABORT that carries findings are NOT
    # this class and keep their STOP semantics untouched (the cohort this must not move).
    #
    # SAME KEY, SAME SPELLING as cmd_audit's durable marker — one grep finds both surfaces, and no new
    # verdict value is minted (the cause rides an additive-optional FIELD, not a fourth verdict word).
    # Additive-optional like the two keys above: a run that did not time out gets NO key, so its verdict
    # YAML stays byte-identical to pre-T-11299 output.
    timeout_abort = audit_lib.is_timeout_abort(verdict, findings, rc)
    if timeout_abort:
        audit["timeout_abort"] = True
    if template_note:
        audit["notes"] = f"{template_note}\n{audit['notes']}"
    if rc != 0:
        audit["notes"] = f"auditor exit {rc}: {stderr[:500]}\n\n--- stdout tail ---\n{_strip_degenerate_tail(stdout)[-2000:]}"
    elif verdict in ("YELLOW", "RED") or not findings:
        _clean = _strip_degenerate_tail(stdout)
        tail = _clean[-2000:] if len(_clean) > 2000 else _clean
        audit["notes"] = f"{audit['notes']}\n\n--- stdout tail ---\n{tail}"
    # T-0350 (SPEC-0036 --focus): `notes` IS the single VERBATIM carrier of the appended focus text
    # (full text, byte-equal); appended as the LAST notes mutation so no tail interleaves into it.
    if focus:
        audit["notes"] = f"{audit['notes']}\n\n--- focus (verbatim, SPEC-0036 --focus) ---\n{focus}"
    # T-12350 (SPEC-0201 rule 2) — the ONE saved-verdict writer helper: stamp + same-provider row.
    audit_lib.stamp_auditor_verdict(audit, provider=provider, model=model, full=full,
                                    target_kind="plan", target_id=slug, stage=stage_template,
                                    append_event=_append_event)
    content = state.dump(audit)
    try:
        rt = state.load_str(content)
        if not isinstance(rt, dict) or rt.get("target_id") != slug or rt.get("target_kind") != "plan":
            _die("SPEC-0001 self-test failed: plan-check audit YAML did not round-trip")
    except yaml.YAMLError as e:
        _die(f"SPEC-0001 self-test failed: {e}")
    audit_path = DECISIONS_DIR / f"{slug}-audit.yaml"
    write_text_atomic(audit_path, content)
    _append_event("draft_checked", None, {"slug": slug, "verdict": verdict,
                  "findings_count": len(findings),
                  "structural_findings_count": len(structural), "large": large,
                  "stage_template": stage_template, "gate_policy": gate_policy,
                  "saved_to": str(audit_path.relative_to(REPO_ROOT))})
    print(f"{slug} plan-check [{stage_template}]: {verdict} ({len(findings)} findings) -> "
          f"{audit_path.relative_to(REPO_ROOT)}")
    # T-0226 — structural pre-pass summary (report-not-block; WARN-level, recorded in the verdict).
    if structural:
        print(f"structural pre-pass: {len(structural)} WARN finding(s) (report-not-block, "
              "recorded in verdict — SPEC-0012):")
        for f in structural:
            print(f"  - [{f['source']}] {f['what']}")
    else:
        print("structural pre-pass: 0 findings (ids/paths resolve; no prose-only deferrals).")
    # SPEC-0082 — scenario-fidelity summary (report-not-block; the baseline-fidelity medium findings
    # CONTRIBUTE YELLOW). Printed only when the dimension applied (a no-roles plan prints nothing).
    if sf and sf["medium"]:
        print(f"scenario-fidelity: {len(sf['medium'])} baseline-fidelity finding(s) → contributes "
              f"YELLOW (SPEC-0082; report-not-block, recorded in verdict):")
        for m in sf["medium"]:
            print(f"  - [{m['source']}] {m['what']}")
    # T-10917 — corpus-reach summary. LOUD and only on a shortfall: the operator reading a YELLOW must
    # see, at the terminal, that the verdict rests on a partial read (SPEC-0034 §accepted). A full-reach
    # run prints nothing here.
    if corpus_coverage:
        print(f"corpus coverage: PARTIAL [{', '.join(corpus_coverage['sources'])}] → "
              f"this verdict does NOT rest on the whole corpus (SPEC-0034 §accepted; GREEN escalated "
              f"to YELLOW, recorded as `corpus_coverage`):")
        print(f"  - {corpus_coverage['not_reached']}")
    print("note: `check` records a verdict + content hash; it does NOT change status (verification "
          "decays — re-checked at take-into-work). `plan stage accepted` requires this verdict GREEN/YELLOW + fresh.")
    if timeout_abort:
        # T-11299 (X-0999) — the ONE class where the `rework` line below is actively misleading: nothing
        # was judged, so there is nothing to rework. RENDER + MARKER ONLY — the control flow is unchanged
        # (the verdict stays ABORT, the plan stays `draft`, `plan stage accepted` still refuses on it);
        # what changes is that the reader learns the cause is a configuration value rather than a stop.
        print(audit_lib.timeout_abort_note(f"{slug} plan-check",
                                           f"yitc-v2 plan check {slug}"), file=sys.stderr)
    elif verdict in ("RED", "ABORT"):
        print(f"# {verdict} — keep status: draft and rework (D-0034 accept-gate).", file=sys.stderr)


def _link_plan_into_targets(slug: str, targets: list, *, _dump_state_yaml, _find_decision_yaml, _find_task_yaml, _read_yaml, write_text_atomic) -> list:
    """AC4 (T-0114) reverse provenance link: append plan `slug` to each task/decision target's
    `cites:` (the existing any→any graph edge — NO new edge type), so a decomposed task/decision
    points BACK to its authoritative plan (plan→target already lives in `closed_into`). Idempotent;
    spec/other ids are skipped. Returns the ids actually updated."""
    updated = []
    for tid in targets:
        if re.match(r"^T-\d{4,}$", tid):
            tpath = _find_task_yaml(tid)
        elif re.match(r"^D-\d{4,}$", tid):
            tpath = _find_decision_yaml(tid)
        else:
            continue
        if not tpath or not tpath.exists():
            continue
        d = _read_yaml(tpath)
        if not isinstance(d, dict):
            continue
        cites = d.get("cites")
        cites = list(cites) if isinstance(cites, list) else ([cites] if cites else [])
        if slug in cites:
            continue
        cites.append(slug)
        d["cites"] = cites
        write_text_atomic(tpath, _dump_state_yaml(d))
        updated.append(tid)
    return updated


def _require_plan_finalization_ready(slug: str, plan_body: str,
                                     exempt_specs: frozenset = frozenset(), *, AUDIT_VERDICT_CLOSURE_OK, DECISIONS_DIR, SPEC_ABANDONED_TERMINAL, _die, _plan_corpus_signature, _plan_specs, _plan_task_carrier, _read_yaml, _reject_id_shaped_plan_slug) -> None:
    """T-0193 plan-finalization gate (Part B; mirror of `task close` D-0015). `plan close
    --resolution realized` requires: (a) EVERY proposed_by spec REACHED `active` — current `active`
    OR a post-active state (`superseded`/`retired`, reachable only after `active` in the spec FSM);
    a never-active status (proposed/draft/withdrawn/rejected) or any unknown status blocks, T-0485;
    (b) a GREEN/YELLOW
    `decisions/<slug>-audit-post.yaml` (`audit post --plan`) verdict on record; (c) that verdict is
    FRESH — its corpus_signature still equals the current plan+corpus signature (a plan-body edit OR a
    spec add/remove/status-change since the audit makes it stale); (d) Part D/1 (T-0209) — the recorded
    task-side carrier `tasks:` still equals the current cites:<plan> task set (membership + status), so
    a task filed/removed or a status regression since the audit also marks the verdict stale.

    `exempt_specs` (T-0342) narrows ONLY clause (a): spec ids in this set are not required `active`.
    It is **empty by default**, so the `realized` EXIT call (`_plan_close_core`) keeps the FULL
    specs-active requirement UNCHANGED (fail-closed at exit). The ONLY non-empty caller is the
    postcheck ENTRY gate (`_require_plan_postcheck_ready` → `_plan_postcheck_exempt_specs`), where a
    retire-on-proof carrier spec is `proposed`-awaiting-activation DURING the soak by design (T-0326).
    Exemption touches the active-state demand ONLY — the audit-currency checks (corpus_signature,
    task-carrier, verdict freshness) still cover the FULL corpus, so a stale aggregate-audit is never
    masked by the exemption."""
    _reject_id_shaped_plan_slug(slug)   # T-0193 F1 — the audit file we read shares the <id> namespace
    specs = _plan_specs(slug)
    if not specs:
        return   # no proposed_by specs → no plan→spec realization to finalize-audit. Backward-compat:
                 # task-only plans (the common decomposition) close exactly as before; this gate is
                 # SPECIFIC to the spec-bearing lifecycle Part B introduced (no corpus → nothing to gate).
    # Clause (a) — the proposed_by spec must have REACHED `active` (its content became normative at
    # some point), NOT necessarily still be CURRENT-active. POSITIVE fail-closed whitelist (T-0485): a
    # spec satisfies the gate iff its status is one of the three REACHED-active states. The spec FSM
    # (GRAPH §Spec-lifecycle) is proposed → active → superseded → retired (+ terminal withdrawn/
    # rejected; `draft` is the plan-local pre-proposed status). `superseded` and `retired` are reachable
    # ONLY after `active` (the sole writer of `superseded` is `_activate_task_proposed_specs`, on a
    # successor's activation), so they PROVABLY mean "reached active" — the gate's intent (the spec was
    # realized). A never-active status (proposed/draft/withdrawn/rejected) AND any unknown/future/
    # malformed status BLOCKS (fail-closed: a negative `!= "active"` set would pass OPEN on an unknown
    # status; the whitelist passes only the three proven states). Touches clause (a) ONLY — the
    # audit-currency/freshness/task-carrier checks (b,c,d) below still grade the FULL corpus (a
    # superseded spec stays in `_plan_specs`'s corpus + corpus_signature), so no audit hole is opened.
    # T-0627: ALSO exempt a corpus spec in a DELIBERATE never-active terminal (SPEC_ABANDONED_TERMINAL =
    # withdrawn/rejected) — a plan-born spec the plan deliberately abandoned (a scope-cut tracked as a
    # follow-up) is NOT an unfinished promise, so it must not block the plan's own `realized`. NARROW +
    # FAIL-CLOSED PRESERVED: only those two known terminals are exempted; a never-active proposed/draft
    # AND any unknown/garbage status is in NEITHER SPEC_REACHED_ACTIVE nor SPEC_ABANDONED_TERMINAL, so it
    # still BLOCKS (the load-bearing T-0485 positive-whitelist property holds — a negative `!= active`
    # set would false-pass an unknown status). Touches clause (a) ONLY — (b,c,d) still grade the FULL
    # corpus (a withdrawn spec stays in `_plan_specs`'s corpus + corpus_signature), so no audit hole.
    SPEC_REACHED_ACTIVE = ("active", "superseded", "retired")
    non_active = [sid for sid, st in specs
                  if st not in SPEC_REACHED_ACTIVE and st not in SPEC_ABANDONED_TERMINAL
                  and sid not in exempt_specs]
    if non_active:
        _die(f"{slug}: cannot close realized — these specs never reached `active`: {', '.join(non_active)} "
             "(finalize requires every proposed_by spec to reach `active` first — current `active` OR a "
             "post-active state, `superseded`/`retired`, counts, since those are reachable only after "
             "`active`; a never-active proposed/draft AND any unknown status blocks. A DELIBERATE terminal "
             "`withdrawn`/`rejected` is EXEMPT — T-0627 — a deliberately-abandoned plan-born spec is not "
             "an unfinished promise.)")
    ap = DECISIONS_DIR / f"{slug}-audit-post.yaml"
    if not ap.exists():
        _die(f"{slug}: no `audit post --plan` verdict on record — run `yitc-v2 audit post --plan {slug}` "
             "first (plan-finalization gate, mirror of `task close` D-0015).")
    av = _read_yaml(ap) or {}
    verdict = str(av.get("verdict") or "").upper()
    if verdict not in AUDIT_VERDICT_CLOSURE_OK:
        _die(f"{slug}: `audit post --plan` verdict is {verdict or 'MISSING'} — finalize needs GREEN/YELLOW. "
             f"Rework, then re-run `yitc-v2 audit post --plan {slug}`.")
    recorded_sig = av.get("corpus_signature")
    if not recorded_sig:
        _die(f"{slug}: the recorded `audit post --plan` predates corpus_signature — re-run "
             f"`yitc-v2 audit post --plan {slug}`.")
    if recorded_sig != _plan_corpus_signature(slug, plan_body):
        _die(f"{slug}: the plan or its spec corpus changed since `audit post --plan` (signature "
             f"mismatch) — the verdict is stale. Re-run `yitc-v2 audit post --plan {slug}` before close.")
    # Part D/1 (T-0209; re-keyed T-9152): READ the same canonical task-side carrier the audit recorded
    # and confirm it still equals the current implementing-task set (decomposed_from:<plan> OR
    # cites:<plan> — the `_plan_tasks` union) (membership AND status — "<tid>:<status>"). A task
    # filed/removed OR a status regression (e.g. done→blocked) since the audit makes the verdict stale —
    # this is how `plan close --resolution realized` reads the same carrier (AP-D2). A `tasks:` key
    # absent from a pre-T-0209 audit-post record reads as [] (additive, P5-safe); for a spec-bearing
    # plan re-audited under T-0209 the carrier is present.
    recorded_tasks = av.get("tasks") or []
    current_tasks = _plan_task_carrier(slug)
    if list(recorded_tasks) != current_tasks:
        _die(f"{slug}: the implementing-task set (decomposed_from:{slug} OR cites:{slug}) changed since `audit post --plan` "
             f"(recorded {list(recorded_tasks) or '[]'} ≠ current {current_tasks or '[]'} — a task "
             f"filed/removed or a status change) — the verdict is stale. Re-run `yitc-v2 audit post "
             f"--plan {slug}` before close.")


def cmd_plan_to_idea(args: argparse.Namespace, *, IDEAS_DIR, PLANS_DIR, REPO_ROOT, _append_event, _die, _load_draft, _utc_now_iso, _write_draft) -> None:
    """Move an active plan → ideas/ (out of the FSM; minimal frontmatter). The plan file
    is relocated (it leaves the planning workspace for the flat holding pen)."""
    path, fm, body = _load_draft(args.slug, dirs=(PLANS_DIR,))
    slug = fm.get("id") or args.slug
    st = fm.get("status")
    if st in PLAN_TERMINAL:
        _die(f"{slug} status={st!r} is terminal — cannot move to ideas/ (only active draft|accepted)")
    dest = IDEAS_DIR / f"{slug}.md"
    if dest.exists():
        _die(f"idea already exists: {dest.relative_to(REPO_ROOT)}")
    idea_fm = {"id": slug, "created": fm.get("created") or _utc_now_iso()[:10],
               "source": f"demoted from draft {slug}"}
    _write_draft(dest, idea_fm, body)
    path.unlink()
    _append_event("draft_to_idea", None, {"slug": slug,
                  "from": str(path.relative_to(REPO_ROOT)),
                  "to": str(dest.relative_to(REPO_ROOT))})
    print(f"{slug}: draft → idea ({dest.relative_to(REPO_ROOT)}) — out of the FSM, flat holding pen.")


def cmd_plan_list(args: argparse.Namespace, *, IDEAS_DIR, PLANS_DIR, _pattern_frontmatter) -> None:
    """List drafts (default = active: draft|plan). --ideas also lists ideas/. Read-only; no event.
    Uses the tolerant frontmatter reader so one malformed file doesn't kill the listing."""
    statuses = args.status or list(PLAN_ACTIVE)
    rows = []
    if PLANS_DIR.exists():
        for p in state.scan_plans(PLANS_DIR):
            fm = _pattern_frontmatter(p)
            st = fm.get("status") or "draft"
            if st in statuses:
                rows.append(("plan", fm.get("id") or p.stem, st, fm.get("created") or "",
                             ",".join(str(c) for c in (fm.get("closed_into") or []))))
    if getattr(args, "ideas", False) and IDEAS_DIR.exists():
        for p in state.scan_ideas(IDEAS_DIR):
            fm = _pattern_frontmatter(p)
            rows.append(("idea", fm.get("id") or p.stem, "-", fm.get("created") or "", ""))
    if not rows:
        print("(no drafts match)")
        return
    print(f"{'KIND':<6} {'ID':<42} {'STATUS':<9} {'CREATED':<11} CLOSED_INTO")
    for kind, sid, st, created, ci in rows:
        print(f"{kind:<6} {sid:<42} {st:<9} {created:<11} {ci}")


def _plan_next_stage(cur: str, *, PLAN_STAGE_SEQUENCE) -> "str | None":
    """The LINEAR successor of `cur` in PLAN_STAGE_SEQUENCE (the plan FSM), or None when `cur` is a
    terminal (PLAN_TERMINAL — incl. the `realized` tail) or unknown. Derived from the ONE FSM constant
    (no parallel stage map — P5) so inserting/removing a stage cannot desync it. A low-level helper
    shared by the read-only re-orientation view (`plan show`, T-0682) and re-usable by the
    post-transition hint (T-0683). CAVEAT (audit-pre F0): `specs` has a real FORK — `specs → trial`
    (trial-eligible plans) OR the `specs → accepted` skip (non-eligible; ACCEPTED_PREDECESSORS /
    SPEC-0035 rules 1-2). This returns only the LINEAR successor, so a USER-FACING caller MUST
    special-case `specs` and surface BOTH branches rather than trust this helper alone."""
    if cur in PLAN_TERMINAL or cur not in PLAN_STAGE_SEQUENCE:
        return None
    i = PLAN_STAGE_SEQUENCE.index(cur)
    return PLAN_STAGE_SEQUENCE[i + 1] if i + 1 < len(PLAN_STAGE_SEQUENCE) else None


def _plan_body_title(body: str) -> str:
    """The plan's human title = its first `# ` heading (plan frontmatter carries no `title` field —
    the skeleton writes `# {title}` into the body). Falls back to '(no title)'."""
    for line in (body or "").splitlines():
        s = line.strip()
        if s.startswith("# "):
            return s[2:].strip()
    return "(no title)"


def cmd_plan_show(args: argparse.Namespace, *, IDEAS_DIR, PLANS_DIR, PLAN_STAGE_SEQUENCE, TASKS_DIR, _load_draft, _plan_body_title, _plan_next_stage, _plan_stage_bundle_specs, _plan_cut_cards, _read_yaml) -> None:
    """`plan show <slug>` (T-0682) — the read-only PLAN re-orientation surface; the plan analog of the
    task resume-contract print (`_print_task_resume` / SPEC-0027). A pure VIEW re-derived from the plan
    artifact + PLAN_STAGE_SEQUENCE + the plan-stage-entry bindings (CHARTER §P1 F2 — a view, not a new
    data structure): the current status + FSM position, the next stage + its entry-gate + the spec
    bundle bound to the next stage, and (at status==decomposition) the task cards cut so far. Read-only
    — NO _append_event, NO FSM mutation, and NO `cli_invoked_verb` marker (so the verb emits nothing of
    its own; acceptance #1 «mutates nothing»). Ideas (no FSM) are reported as such, not staged.

    T-10908 — the cut-card listing reads `_plan_cut_cards` (the `decomposed_from` marker), the SAME link
    `_require_plan_decomposition_fidelity` judges: the set a reader SEES is the set the gate JUDGES. It
    used to read `_plan_tasks` (the BROAD T-9152 finalization corpus, `decomposed_from` ∪ `cites`) under a
    "cards citing this plan" heading, so an informational `cites:`-only citer DISPLAYED as a cut card the
    gate does not judge, and the empty-state named the wrong link ("no task cites: <slug>") — sending the
    author to repair `cites:` while the gate waits on `decomposed_from` (kupiclub X-0661 → X-0662). The
    corpus reader is deliberately UNCHANGED: SPEC-0070 §5 makes the two NON-SUBSTITUTABLE one-way (the
    corpus is a superset; re-deriving cut membership FROM `cites` is the T-0678 defect, and narrowing the
    corpus is the inverse T-9152 defect). Only this DISPLAY moves onto the marker."""
    path, fm, body = _load_draft(args.slug, dirs=(PLANS_DIR, IDEAS_DIR))
    slug = fm.get("id") or args.slug
    title = _plan_body_title(body)
    # An idea is a flat note with no FSM/stages — nothing to re-orient (D-0034).
    if path.parent == IDEAS_DIR or fm.get("kind") == "idea":
        print(f"idea {slug} — {title}")
        print("  ideas/ are flat forward-looking notes — no FSM, no stages, no next gate (D-0034). "
              "Promote to a plan (`yitc-v2 plan file`) to enter the lifecycle.")
        return
    status = fm.get("status") or "draft"
    print(f"plan {slug} — {title}")
    if status in PLAN_STAGE_SEQUENCE:
        pos = (f" (step {PLAN_STAGE_SEQUENCE.index(status) + 1}/{len(PLAN_STAGE_SEQUENCE)} along "
               f"{' → '.join(PLAN_STAGE_SEQUENCE)})")
    else:
        pos = ""
    print(f"  status: {status}{pos}")
    if status in PLAN_TERMINAL:
        print("  next stage: (none) — terminal status; no further `plan stage` transition.")
    elif status == "specs":
        # The ONE branching stage (audit-pre F0): surface BOTH forks, never a single linear next.
        print("  next stage: FORK — `trial` (owner-invoked, trial-ELIGIBLE plans — SPEC-0035) OR "
              "`accepted` (the specs→accepted SKIP for non-eligible prose/docs plans). Eligibility is "
              "owner judgement (SPEC-0035 rules 1-2), not a detector.")
        print(f"    next action: `yitc-v2 plan stage trial {slug}`  OR  `yitc-v2 plan stage accepted {slug}`")
        for nxt in ACCEPTED_PREDECESSORS[::-1]:   # trial, accepted (the two fork targets)
            b = _plan_stage_bundle_specs(nxt)
            print(f"    {nxt} delivers (read before acting — `yitc-v2 graph query <SPEC>`): "
                  f"{', '.join(b) if b else '(no bound spec)'}")
        print("  gate detail: LIFECYCLE.md §Plan lifecycle + the bound spec(s) (authoritative).")
    else:
        nxt = _plan_next_stage(status)
        if nxt is None:
            print("  next stage: (none).")
        else:
            print(f"  next stage: {nxt} — entry-gate = completion of the current `{status}` stage, "
                  f"gated by `yitc-v2 plan stage {nxt} {slug}`.")
            print(f"    next action: `yitc-v2 plan stage {nxt} {slug}`")
            b = _plan_stage_bundle_specs(nxt)
            print(f"    {nxt} delivers (read before acting — `yitc-v2 graph query <SPEC>`): "
                  f"{', '.join(b) if b else '(no bound spec)'}")
        print("  gate detail: LIFECYCLE.md §Plan lifecycle + the bound spec(s) (authoritative).")
    # At decomposition, list the cut cards — the CUT MEMBER-SET (`decomposed_from`), i.e. the exact set
    # `_require_plan_decomposition_fidelity` judges, NOT the broad `_plan_tasks` corpus (T-10908).
    if status == "decomposition":
        cards = _plan_cut_cards(slug)
        if cards:
            print(f"  task cards cut so far — the cut member-set the executing gate judges "
                  f"(decomposed_from: {slug}):")
            for tid, st in cards:
                p = next(TASKS_DIR.glob(f"{tid}-*.yaml"), None) or (TASKS_DIR / f"{tid}.yaml")
                d = (_read_yaml(p) if (p and p.exists()) else {}) or {}
                print(f"    - {tid} [{st or '?'}] {d.get('title') or ''}")
        else:
            # Mirror of the gate's own refusal text (`_require_plan_decomposition_fidelity`): name the
            # link the gate reads, so an author repairs the field that actually unblocks them.
            print(f"  task cards cut so far: (none yet — no task carries `decomposed_from: {slug}`).")
            print(f"    file cut cards with `yitc-v2 task file --decomposed-from {slug}` — an "
                  f"informational `cites: {slug}` alone is NOT cut membership (SPEC-0070 §5), and the "
                  f"executing gate will block until the marker is there.")
