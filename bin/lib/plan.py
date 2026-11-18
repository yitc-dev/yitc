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
import time

from lib import audit as audit_lib   # T-11299: the shared timeout-ABORT classifier + its reported face.
                                    # ALIASED on purpose — cmd_plan_check binds a LOCAL name `audit` to
                                    # the verdict mapping it writes, which would shadow a bare module import.
from lib import observe   # T-11249: the shared checkout-provenance render
from lib import state
from lib import spec as spec_lib   # T-12976: the SPEC-0151 anchor predicate — spec.py imports only state/graph/textutil, acyclic
from lib import events as events_mod  # T-11536: the SPEC-0190 logical-journal pathspec view
from lib import journal as journal_mod   # T-13298: plan stage's one-pass ReadScope (SPEC-0190 rule 10)
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

<!-- Which external audits at which boundaries (SPEC-1040 / SPEC-0034 §Audit-posture). Trial-eligibility
     (SPEC-0035): is this mechanism/behavioral (soak in `trial`) or text-audit-verifiable (skips trial)?
     HISTORY STAYS OUT OF THIS BODY: gate-pass and trial-run history lives in the journal (raw run
     observations — SPEC-0035 rule 6) and in the saved audit records under `decisions/` (each pass's
     findings and dispositions — SPEC-1040 §Saved audit result; an overwritten record keeps its earlier
     passes in its git history). Here, and in a `## Trial summary`, keep ONE CURRENT summary per check
     with REFERENCES to those rows and records — update it in place, never append a pass-by-pass or
     run-by-run log. The per-correction record lines of SPEC-0083 §Correction invalidation still go here. -->

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

## Draft documents

<!-- For a large plan, the project documents prepared BEFORE the first check round — list their paths
     (only the ones this plan needs): rights or threat matrix, seam map, guards by change kind,
     pre-mortem, readiness checklist, decision records. Verify first: a document about a mechanism is
     verified against the live system before it enters a plan. How: `patterns/plan-draft-documents.md`
     (SPEC-0043 item 11). Project documents — the auditor never reads them whole. -->

## Units

<!-- The decomposition map, one bullet per unit (one coherent change-set = one card at the cut, SPEC-0046 §A):
     - **U1 — <title>.** Carries: <what the card delivers>. requires: — (or U<n>, U<a>–U<b>).
       Owns: `<path>[#symbol]`, `<path>` (new), SPEC-XXXX §<section>. Proves: <probe>; <probe>.
     `(new)` after a locator declares a creation; a unit already cut says `filed as T-NNNN`.
     Form: SPEC-0043 item 10. `yitc-v2 plan show <slug> --unit-skeletons` prints the card skeletons. -->

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
    off this exact line (<project> 2026-09-02, X-1228) — so the hint is rendered kernel-explicit there
    via the ONE shared `graph.spec_query_hint`. The engine's own session renders the bare form, so
    every existing engine-side draft is byte-identical."""
    return _PLAN_DRAFT_SKELETON.format(
        title=title,
        s43_hint=graph_lib.spec_query_hint("SPEC-0043", is_consumer=is_consumer, cli="yitc-v2"))


# --- T-14625 (SPEC-0043 item 10): card skeletons from a plan's `## Units` section ---------------------
# A VIEW over plan text: `plan show <slug> --unit-skeletons` prints the `task file --from-stdin` BATCH a
# cutter would otherwise hand-write. Emit only — nothing is filed, no store, no event.
_UNIT_HEAD_RE = re.compile(r"^- \*\*([A-Z]+\d+[a-z]?)\s*[—–-]+\s*(.+?)\*\*\s*(.*)$")
# A label preceded by a backtick or a word char is prose quoting the label (e.g. "`requires:`").
_UNIT_LABEL_RE = re.compile(r"(?<![`\w])(Carries|requires|Owns|Proves)(\s*\([^)]*\))?:")
_UNIT_FILED_RE = re.compile(r"\bfiled\b[^.]*?\bas (T-\d+)", re.IGNORECASE)
_UNIT_LOCATOR_RE = re.compile(r"`([^`\s]+)`(\s*\(new\))?")
_UNIT_SPEC_RE = re.compile(r"\bSPEC-\d{4}\b")


class PlanUnitsError(ValueError):
    """A `## Units` section the skeleton view cannot render — the message names the cause."""


def _unit_id_re(ids_alt: str) -> "re.Pattern":
    return re.compile(rf"(?<![\w-])({ids_alt})(?:\s*[–-]\s*({ids_alt}))?(?![\w])")


def _strip_parens(text: str) -> str:
    prev = None
    while prev != text:
        prev, text = text, re.sub(r"\([^()]*\)", "", text)
    return text


def parse_plan_units(body: str, *, spec_path=None) -> list:
    """Parse the `## Units` section of a plan body (SPEC-0043 item 10) into unit dicts, in plan order.

    Each unit: id, title, carries, owns, proves (texts), requires (resolved: unit ids or filed T-ids),
    filed (the T-id when the unit is already cut, else None), touch (locator paths), new (declared
    creations), cites (SPEC ids). `spec_path(spec_id)` maps a SPEC id in Owns to its file (or None).
    Raises PlanUnitsError naming the cause: no section, no units, a duplicate id, an undeclared requires
    target (the edge is named)."""
    lines = (body or "").splitlines()
    start = next((i for i, ln in enumerate(lines) if re.match(r"^##\s+Units\b", ln)), None)
    if start is None:
        raise PlanUnitsError("the plan has no `## Units` section (SPEC-0043 item 10)")
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    bullets, cur = [], None
    for ln in lines[start + 1:end]:
        if ln.startswith("- "):
            cur = [ln]
            bullets.append(cur)
        elif cur is not None and ln.startswith((" ", "\t")) and ln.strip():
            cur.append(ln.strip())
        elif ln.strip():
            cur = None   # a top-level non-bullet line ends the bullet
    raw = []
    for b in bullets:
        m = _UNIT_HEAD_RE.match(" ".join(b))   # a bold head may wrap over lines
        if m:
            raw.append({"id": m.group(1), "title": m.group(2).strip().rstrip(".").strip(),
                        "text": m.group(3)})
    if not raw:
        raise PlanUnitsError("the `## Units` section holds no unit bullet of the form "
                             "`- **U1 — <title>.** Carries: … requires: … Owns: … Proves: …`")
    seen = set()
    for u in raw:
        if u["id"] in seen:
            raise PlanUnitsError(f"unit {u['id']} is declared twice in `## Units`")
        seen.add(u["id"])
    order = [u["id"] for u in raw]
    id_re = _unit_id_re("|".join(re.escape(i) for i in sorted(order, key=len, reverse=True))
                        + r"|[A-Z]+\d+[a-z]?")
    units = []
    for u in raw:
        text = u["text"]
        fields, marks = {}, list(_UNIT_LABEL_RE.finditer(text))
        for k, m in enumerate(marks):
            label = m.group(1)
            if label in fields:
                continue
            stop = next((mm.start() for mm in marks[k + 1:] if mm.group(1) not in fields
                         and mm.group(1) != label), len(text))
            fields[label] = text[m.end():stop].strip().rstrip(".").strip()
        if "Carries" not in fields:
            first = marks[0].start() if marks else len(text)
            fields["Carries"] = text[:first].strip().rstrip(".").strip()
        filed = _UNIT_FILED_RE.search(text)
        req_text = _strip_parens(fields.get("requires", ""))
        requires = []
        for m in id_re.finditer(req_text):
            a, b = m.group(1), m.group(2)
            for end_id in (a, b):
                if end_id and end_id not in seen:
                    raise PlanUnitsError(f"unit {u['id']} requires {end_id}, which no unit in `## Units` "
                                         f"declares — declare it or correct the edge")
            span = [a] if not b else order[order.index(a):order.index(b) + 1]
            if b and order.index(b) < order.index(a):
                raise PlanUnitsError(f"unit {u['id']} requires the range {a}–{b}, whose end comes before "
                                     f"its start in `## Units`")
            if u["id"] in span:
                raise PlanUnitsError(f"unit {u['id']} requires itself — a requires cycle; correct the edge")
            requires += [x for x in span if x not in requires]
        requires += [t for t in re.findall(r"\bT-\d+\b", req_text) if t not in requires]
        owns = fields.get("Owns", "")
        touch, new = [], []
        for m in _UNIT_LOCATOR_RE.finditer(owns):
            loc = m.group(1).split("#", 1)[0]
            if not loc or not ("/" in loc or re.search(r"\.[A-Za-z0-9]+$", loc)):
                continue
            if loc not in touch:
                touch.append(loc)
            if m.group(2) and loc not in new:
                new.append(loc)
        for sid in _UNIT_SPEC_RE.findall(owns):
            p = spec_path(sid) if spec_path else None
            if p and p not in touch:
                touch.append(p)
        cites = []
        for sid in _UNIT_SPEC_RE.findall(text):
            if sid not in cites:
                cites.append(sid)
        units.append({"id": u["id"], "title": u["title"], "carries": fields["Carries"], "owns": owns,
                      "proves": fields.get("Proves", ""), "requires": requires,
                      "filed": filed.group(1) if filed else None, "touch": touch, "new": new,
                      "cites": cites})
    return units


def render_unit_skeletons(slug: str, units: list) -> str:
    """Render parsed units as a `task file --from-stdin` BATCH (`---`-separated documents). A unit already
    cut (`filed`) is not emitted; an edge to it carries its filed id. An edge to an emitted unit is `@N`
    (its 1-based batch position) — the documents are in a stable topological order, so every `@N` names
    an EARLIER card, as the batch requires. A requires cycle raises PlanUnitsError naming its units."""
    by_id = {u["id"]: u for u in units}
    todo = [u for u in units if not u["filed"]]
    ordered, placed = [], set()
    while todo:
        ready = next((u for u in todo if all(r not in by_id or r in placed or by_id[r]["filed"]
                                             for r in u["requires"])),
                     None)
        if ready is None:
            raise PlanUnitsError("a requires cycle among units " + ", ".join(u["id"] for u in todo))
        ordered.append(ready)
        placed.add(ready["id"])
        todo.remove(ready)
    pos = {u["id"]: n for n, u in enumerate(ordered, 1)}
    docs = []
    for u in ordered:
        scope = [f"Carries: {u['carries'] or '(name what this card delivers)'}"]
        if u["owns"]:
            scope.append(f"Owns: {u['owns']}")
        scope += [f"Creates (declared new): {p}" for p in u["new"]]
        items = [s.strip().rstrip(".").strip() for s in u["proves"].split(";") if s.strip()]
        acceptance = [f"AC{n}: {it} (fill: the test or probe that proves it, SPEC-0060)"
                      for n, it in enumerate(items, 1)] or [
            "AC1: (fill: the probe that proves this unit — its Proves was empty, SPEC-0060)"]
        doc = {"title": f"{u['id']} — {u['title']}", "class": "feature", "priority": "medium",
               "scope": scope, "acceptance": acceptance,
               "requires": [r if r not in by_id else (by_id[r]["filed"] or f"@{pos[r]}")
                            for r in u["requires"]],
               "cites": u["cites"], "expected_touch": u["touch"], "decomposed_from": slug}
        docs.append(f"# unit {u['id']} (batch @{pos[u['id']]})\n" + state.dump(doc))
    skipped = [f"{u['id']}={u['filed']}" for u in units if u["filed"]]
    head = (f"# Card skeletons from plans/{slug}.md `## Units` (SPEC-0043 item 10) — EMITTED, not filed.\n"
            f"# Fill class / seams / guards / acceptance, then: bin/yitc-v2 task file --from-stdin < this-file\n"
            + (f"# already cut (not emitted; edges carry the id): {', '.join(skipped)}\n" if skipped else ""))
    return head + "---\n".join(docs)


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

PLAN_GATE_TEMPLATE_SPEC = "SPEC-0083"   # T-12889: re-homed out of SPEC-0036 (Audit-pre bundle cut)

PLAN_GATE_TEMPLATE_ANCHORS = {
    "plan-draft": "P1", "gate-specs": "P2", "gate-trial": "P3", "gate-accepted": "P4",
    # P5 = the decomposition->executing fidelity gate (SPEC-0070 §3). The CODE that consumes it lands in
    # T-0649; the P5 PROSE (now in SPEC-0083, T-12889) lands in T-0650 (the settled SPEC-0070 §9 build order). Until the
    # prose exists, a mandatory-blocking gate-executing run FAILS CLOSED (safe) — see
    # _require_plan_decomposition_fidelity.
    "gate-executing": "P5",
    # T-14628 — the accept-gate ROUND template, appended after the stage template by `plan check --round`.
    "plan-round": "P4 round",
}

_PLAN_TEMPLATE_TO_GATE_ID = {
    "gate-specs": "draft-specs", "gate-trial": "specs-trial",
    "gate-accepted": "trial-accepted", "gate-executing": "decomposition-executing",
}

# T-14673 (SPEC-0034 §Plan-stage obligations) — the stage whose work each gate template judges: its
# packet lists the obligations due THROUGH that stage. The accept gate is `plan check` (through the
# plan's status); the change check reads the plan's status too.
PLAN_GATE_OBLIGATIONS_THROUGH = {"gate-specs": "draft", "gate-trial": "specs", "gate-executing": "decomposition"}

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


def _plan_cut_rows(slug: str, *, TASKS_DIR, _plan_cut_cards, _read_yaml) -> list:
    """One read of a plan's cut: [{id, status, doc}] for `_plan_cut_cards(slug)`, a missing or unreadable
    card reading as an empty doc."""
    rows = []
    for tid, st in _plan_cut_cards(slug):
        p = next(TASKS_DIR.glob(f"{tid}-*.yaml"), None) or (TASKS_DIR / f"{tid}.yaml")
        d = _read_yaml(p) if (p and p.exists()) else {}
        rows.append({"id": tid, "status": st, "doc": d if isinstance(d, dict) else {}})
    return rows


# T-14673 — the marker the fingerprint wrapper passes when the obligation view is UNAVAILABLE: the
# fingerprint then degrades to its stable error-hash, never equal to a recorded real fingerprint.
PLAN_OBLIGATIONS_UNAVAILABLE = object()


def _plan_card_set_fingerprint(slug: str, *, SPECS_DIR, TASKS_DIR, _plan_cut_cards, _read_yaml, PLANS_DIR=None, _carry=None, _obligations=None) -> str:
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
      - T-14457 (SPEC-1058 §3), ONLY for a plan that opts into a prototype carry: each card's
        `prototype_lines` plus the registry text and the pinned prototype pair. Any other plan's basis is
        byte-identical, so its recorded verdicts stay fresh. `_carry` is the gate's (fm, body, rows) —
        its one read of the cut; without it the plan and the cards are read here.
      - T-14673 (SPEC-0034 §Plan-stage obligations) — `_obligations`: the digest of the plan-stage
        obligations due through `decomposition`, joined as `obligations` only when non-None (nothing
        due = a byte-identical basis); `PLAN_OBLIGATIONS_UNAVAILABLE` yields the error-hash.
    Telemetry-grade: degrades to a stable error-hash on any read failure (must never crash the gate verb)."""
    try:
        if _obligations is PLAN_OBLIGATIONS_UNAVAILABLE:
            raise ValueError("the plan-stage obligation view is unavailable")
        if _carry is not None:
            fm, body, rows = _carry
        else:
            plan_path = (PLANS_DIR / f"{slug}.md") if PLANS_DIR is not None else None
            fm, body = (state.split_frontmatter_text(plan_path.read_text(encoding="utf-8"))
                        if plan_path is not None and plan_path.exists() else ({}, ""))
            rows = _plan_cut_rows(slug, TASKS_DIR=TASKS_DIR, _plan_cut_cards=_plan_cut_cards, _read_yaml=_read_yaml)
        opted = _plan_is_prototype_opted_in(fm)
        cards = []
        for row in rows:   # T-0694: cut MEMBER-set via decomposed_from, NOT cites:
            tid, d = row["id"], row["doc"]
            cards.append({
                "id": tid,
                "requires": sorted(d.get("requires") or []),
                "acceptance": list(d.get("acceptance") or []),   # the PROBE carrier (no separate field)
                "scope": list(d.get("scope") or []),             # the card body
                "cites": sorted(d.get("cites") or []),
                # T-10388: the touch-forecast is now a fidelity-checked cut property (SPEC-0083 P5),
                # so it MUST be in the freshness basis — else a post-audit expected_touch edit would
                # reuse the stale GREEN verdict without re-checking the forecast the auditor blessed.
                "expected_touch": sorted(d.get("expected_touch") or []),
                "title": d.get("title") or "",
            })
            if opted:
                lines = d.get("prototype_lines")
                cards[-1]["prototype_lines"] = (sorted(str(x) for x in lines) if isinstance(lines, list)
                                                else lines)
        cards.sort(key=lambda c: c["id"])
        spec_activation = []
        for sp in state.scan_specs(SPECS_DIR):   # SPEC-* glob excludes _template.yaml
            d = _read_yaml(sp)
            if isinstance(d, dict) and d.get("proposed_by") == slug:
                spec_activation.append([d.get("id") or sp.stem, d.get("activation_owner_task")])
        spec_activation.sort(key=lambda x: (x[0] or ""))
        fp_input = {"cards": cards, "spec_activation": spec_activation}
        if _obligations is not None:
            fp_input["obligations"] = _obligations
        if opted:
            fp_input["prototype"] = {"ref": str(fm.get("prototype_ref") or "").strip(),
                                     "tip": str(fm.get("prototype_tip") or "").strip(),
                                     "base": str(fm.get("prototype_base") or "").strip(),
                                     "registry": _plan_prototype_registry_section(body) or ""}
        basis = json.dumps(fp_input, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(basis.encode("utf-8")).hexdigest()
    except Exception:
        return hashlib.sha256(b"<plan-card-set-fingerprint-error>").hexdigest()


def _plan_section_text(body: str, name: str) -> "str | None":
    """The AUTHOR text of the `## <name>` section: its body with the `<!-- ... -->` skeleton stub
    comment(s) removed and outer whitespace stripped; None when the heading is absent or the section
    carries no author text. Text only, never a semantic judgement (CHARTER non-goal #7). The ONE
    section computation `_plan_section_filled` and the postcheck readiness view (T-14477) share.
    Tolerant: an unreadable/empty body → None (a report helper must never crash the verb)."""
    try:
        m = re.search(r"^##\s+" + re.escape(name) + r"\s*$(.*?)(?=^##\s|\Z)",
                      body or "", flags=re.MULTILINE | re.DOTALL)
        if not m:
            return None
        return _HTML_COMMENT_RE.sub("", m.group(1)).strip() or None
    except Exception:
        return None


def _plan_section_filled(body: str, name: str) -> bool:
    """Does the `## <name>` section exist AND carry AUTHOR content? A section is FILLED when, after
    removing the `<!-- ... -->` skeleton stub comment(s) + whitespace, its body is non-empty; a heading
    absent entirely is unfilled. PRESENCE only, never a semantic-completeness judgement (CHARTER
    non-goal #7). Extracted from `_plan_draft_sections_filled`'s per-section body (T-10293) so the
    front-load advisory and `_postcheck_probe_block_declared` share ONE computation. Tolerant: an
    unreadable/empty body → False (a report helper must never crash the verb)."""
    return _plan_section_text(body, name) is not None


def _plan_realization_exit_criteria(body: str) -> "list | None":
    """T-14477 — the realization-exit criteria the plan DECLARES, verbatim: the non-empty lines of the
    first filled probe-block section (canonical `## Realization-exit criteria`, then the legacy
    names). `[]` when such a heading is present but carries no author text (an empty or comment-only
    stub); None when no such heading exists. Lists, never judges: whether a criterion is met is the
    owner's call against its evidence-home (SPEC-0034 §postcheck)."""
    names = (REALIZATION_EXIT_SECTION, *_PROBE_BLOCK_LEGACY_SECTIONS)
    for name in names:
        text = _plan_section_text(body, name)
        if text:
            return [ln.strip() for ln in text.splitlines() if ln.strip()]
    try:
        if any(re.search(r"^##\s+" + re.escape(n) + r"\s*$", body or "", flags=re.MULTILINE)
               for n in names):
            return []
    except Exception:
        pass
    return None


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


def _plan_draft_finalized_fresh(slug: str, body: str, *, _iter_events, _plan_content_hash,
                                EVENTS_PATH=None) -> bool:
    """True iff a `plan_draft_finalized` journal event exists for `slug` whose recorded `body_hash`
    matches the CURRENT body content-hash — the PROVENANCE-bound draft worked-through proof that
    `plan stage specs` requires (T-0601, audit-post HIGH). Only `plan draft --finalize` emits this
    event, so the proof is bound to the VERB's emission, not a forgeable frontmatter field; a body
    edited since the last finalize no longer hash-matches → stale → the gate refuses. Journal-only via
    the single `_iter_events` reader (P5); session-agnostic (the worked-through proof carries across
    sessions — the per-session doctrine read is enforced separately by the read-check leg)."""
    want = _plan_content_hash(body)

    def _proof(e) -> bool:
        if e.get("type") != "plan_draft_finalized":
            return False
        d = e.get("data") or {}
        return d.get("slug") == slug and d.get("body_hash") == want
    # T-13298 — PLAN-scoped: inside plan stage's ReadScope the scope's rows naming the slug (a superset
    # of every row this predicate can match), else the whole journal exactly as before.
    scoped = journal_mod.scope_needle_rows(EVENTS_PATH, slug) if EVENTS_PATH is not None else None
    if scoped is not None:
        return any(_proof(e) for e in scoped)
    for e in _iter_events():
        if _proof(e):
            return True
    return False


# ── T-13298 — plan stage's ONE-PASS ReadScope (SPEC-0190 rules 4 + 10) ─────────────────────────────
#
# MEASURED BEFORE (kernel checkout, 122 segments, auditor stubbed): `plan stage specs` folded every
# segment 5 times (611 folds, 3.8 GB peak RSS, ~90 s) — the read-gate's anchor (this checkout + MAIN)
# and receipts, the draft-finalized proof, and the auditor breaker; `plan stage executing` at a gate
# ceiling folded the plan-gate journal union (this checkout + MAIN) in place of the proof. Every one
# of them asks about ONE plan, ONE session, or a 7-day window.
#
# THE SHAPE: T-13293's `audit_pre_read_scope`, keyed on the PLAN — installed at the WIRING SITE
# (`cli.py#cmd_plan_stage`): one lazy walk from the plan's filing day (less a margin) on, keeping the
# lines naming the slug (PLAN needle), the lines naming the carried session refs (SESSION needles) and
# the breaker's three types over its window. A session older than that horizon is served by the
# scope's ONE remainder walk of the segments the horizon left unopened (`remainder=True`). Outside the
# scope every reader is exactly the read it was.
#
# PLAN HORIZON PREMISE (the T-12337 premise on the plan axis): a row naming a plan slug cannot predate
# the plan file, so the rows those readers keep all live in segments dated on/after `created`.
#
# T-13300 — `plan draft --finalize` installs the SAME scope at its wiring site (`cli.py#cmd_plan_draft`):
# its only journal readers are the read-gate's anchor + receipts (366 folds / ~73 s / 3.8 GB before),
# both SESSION-scoped and served horizon-first exactly as here; no breaker window (no auditor).
PLAN_HORIZON_MARGIN_DAYS = 2          # union-merge / clock-skew margin under the filing day


def plan_horizon(fm: dict) -> "str | None":
    """The PLAN horizon floor (`YYYY-MM-DD`): the plan frontmatter's `created` date less
    `PLAN_HORIZON_MARGIN_DAYS` — or None when it carries none (the caller then reads the whole history,
    in one pass, and says so — routed T-13288)."""
    import datetime as _dt
    day = str((fm or {}).get("created") or "")[:10]
    if not re.match(r"\d{4}-\d{2}-\d{2}$", day):
        return None
    try:
        return (_dt.date.fromisoformat(day) - _dt.timedelta(days=PLAN_HORIZON_MARGIN_DAYS)).isoformat()
    except ValueError:
        return None


_PLAN_SCOPE_HORIZON = None     # the open scope's plan horizon (None outside one) — see `plan_scope_horizon`


def plan_scope_horizon() -> "str | None":
    """The horizon of the plan stage ReadScope now open, for a reader the scope cannot serve itself
    (the plan-gate fold's MAIN leg); None outside one = the whole history, as before."""
    return _PLAN_SCOPE_HORIZON


@contextlib.contextmanager
def plan_stage_read_scope(args, *, events_path, load_draft, plans_dir, session_refs=(), verb="plan stage",
                          breaker=True):
    """Install plan stage's ONE-PASS ReadScope (the block above); a pass-through yielding None when
    there is no journal or the plan cannot be read (the verb makes its own refusal, unchanged).
    T-13300 — `plan draft` installs the same scope: `verb` names the reader in the routing line and
    `breaker=False` declares no auditor-breaker window (that verb runs no auditor), so its walk starts
    at the plan horizon alone."""
    global _PLAN_SCOPE_HORIZON
    if events_path is None:
        yield None
        return
    import datetime as _dt
    try:
        _p, fm, _b = load_draft(args.slug, dirs=(plans_dir,))
        slug = str((fm or {}).get("id") or args.slug)
    except BaseException:   # noqa: BLE001 — incl. the loader's own refusal; the verb re-raises it
        yield None
        return
    horizon = plan_horizon(fm)
    since = None
    if horizon is None:
        print(f"{verb}: {slug} carries no `created` — plan-scoped reads fall back to whole history "
              f"(one pass) — routed T-13288", file=sys.stderr)
    elif not breaker:
        since = horizon
    else:
        since = min(horizon, journal_mod._retention_floor(_dt.datetime.now(_dt.timezone.utc),
                                                          audit_lib.AUDITOR_NO_ANSWER_WINDOW_DAYS))
    needles = (slug,) + tuple(r for r in dict.fromkeys(session_refs or ())
                              if r and json.dumps(r)[1:-1] == r)
    keep = ({t: ("segment", audit_lib.AUDITOR_NO_ANSWER_WINDOW_DAYS) for t in audit_lib.BREAKER_READ_TYPES}
            if breaker else {})
    global _PLAN_OBLIGATION_HOLDER
    prior = _PLAN_SCOPE_HORIZON
    prior_holder = _PLAN_OBLIGATION_HOLDER
    with journal_mod.scan_scope(events_path, keep=keep, needles=needles, since=since,
                                remainder=True) as scope:
        _PLAN_SCOPE_HORIZON = horizon
        _PLAN_OBLIGATION_HOLDER = {}   # T-14673 — the obligation view, computed once inside this scope
        try:
            yield scope
        finally:
            _PLAN_SCOPE_HORIZON = prior
            _PLAN_OBLIGATION_HOLDER = prior_holder


# ---------------------------------------------------------------------------------------------------
# T-14673 (SPEC-0034 §Plan-stage obligations at the plan checkpoints) — ONE derived projection of the
# plan-axis bindings: per plan stage the ACTIVE specs bound `plan-stage-entry:<stage>`, keyed
# (realm, id), each with the content digest of its file chain and its source path. Three readers: the
# catch-up delivery at the plan checkpoints, the plan-gate packet checklist and the verdict freshness
# records. No store: it is recomputed from the corpus, once per invocation inside a plan read scope
# (SPEC-0190 rule 10 — the scope is the request-scoped seam, no cache of its own).
_PLAN_OBLIGATION_HOLDER = None   # the open plan read scope's one-slot holder (None outside one)


def plan_scope_obligations(compute):
    """The obligation view: computed ONCE inside an open plan read scope (held for its life), fresh
    on every call outside one."""
    holder = _PLAN_OBLIGATION_HOLDER
    if holder is None:
        return compute()
    if "view" not in holder:
        holder["view"] = compute()
    return holder["view"]


def _plan_obligation_chain_digest(path) -> str:
    """sha256 over the spec's whole read chain (base + continuation parts) — any byte edit moves it.
    The pre-T-14697 obligation digest, kept unchanged: a record written in that form is still read
    by it (the cli comparison hosts), and an unparseable part falls back to it."""
    h = hashlib.sha256()
    for p in state.spec_part_paths(path):
        h.update(Path(p).name.encode("utf-8") + b"\0" + Path(p).read_bytes() + b"\0")
    return h.hexdigest()


# T-14697 — what a plan must meet of a due spec: its status and its rule text. The field set and the
# section set are the ones a stage-entry contract view leaves out (cli.py#_CONTRACT_VIEW_DROPPED_FIELDS
# / _CONTRACT_VIEW_OMITTED_SECTIONS), held equal by tests/test_t14697_obligation_normative_digest.py.
_PLAN_OBLIGATION_BOOKKEEPING_FIELDS = frozenset({
    "implements", "implements_signature", "concern", "init_concern",
    "created_at", "consumed", "activation_owner_task", "proposed_by"})
_PLAN_OBLIGATION_OMITTED_SECTIONS = ("Rationale", "Verification", "Implementation notes", "Drift review")
_PLAN_OBLIGATION_DIGEST_FORM = "normative-v1"
_PLAN_FENCE_OPEN = re.compile(r"[ ]{0,3}(`{3,}|~{3,})")
_PLAN_SECTION = re.compile(r"##[ \t]")
_PLAN_PARAGRAPH_END = re.compile(r"\n(?=[ \t]*(?:\n|$)|[ ]{0,3}#{1,6}(?:[ \t]|\n|$)|[ ]{0,3}(?:`{3,}|~{3,}))")


def _plan_obligation_sections(body: str) -> list:
    """ONE pass over a chain-joined spec body -> [(section name or None, kept text)]. Markdown read as a
    reader sees it: a fenced block (an opening run of 3+ backticks or tildes, closed by a line holding a
    run of the same character at least as long, or the body's end) is kept verbatim and never opens a
    section; an inline code span (a backtick run closed by a run of the same length within its
    paragraph) is kept verbatim; an HTML comment outside both is removed whole, its newlines included; a
    column-0 `## ` line outside all three opens a section."""
    sections, name, buf = [], None, []
    i, n = 0, len(body)
    while i < n:
        bol = i == 0 or body[i - 1] == "\n"
        if bol:
            m = _PLAN_FENCE_OPEN.match(body, i)
            if m:
                run = m.group(1)
                close = re.compile(r"\n[ ]{0,3}" + re.escape(run[0]) + "{" + str(len(run)) + r",}[ \t]*(?=\n|$)")
                c = close.search(body, m.end())
                j = c.end() if c else n
                buf.append(body[i:j])
                i = j
                continue
            if _PLAN_SECTION.match(body, i):
                head, j = [], i + 3   # the heading's name, read comment-aware as the body is
                while j < n and body[j] != "\n":
                    if body.startswith("<!--", j):
                        k = body.find("-->", j + 4)
                        j = n if k < 0 else k + 3
                        continue
                    head.append(body[j])
                    j += 1
                sections.append((name, "".join(buf)))
                name, buf = "".join(head).rstrip(" \t"), []
        if body.startswith("<!--", i):
            j = body.find("-->", i + 4)
            i = n if j < 0 else j + 3
            continue
        if body[i] == "`":
            k = i
            while k < n and body[k] == "`":
                k += 1
            run = body[i:k]
            pend = _PLAN_PARAGRAPH_END.search(body, k)
            limit = pend.start() if pend else n
            c = re.compile(r"(?<!`)" + run + r"(?!`)").search(body, k, limit)
            if c:
                buf.append(body[i:c.end()])
                i = c.end()
            else:
                buf.append(run)
                i = k
            continue
        buf.append(body[i])
        i += 1
    sections.append((name, "".join(buf)))
    return sections


def _plan_obligation_rule_text(body: str) -> str:
    """The rule text of a chain-joined spec body: its sections (`_plan_obligation_sections`) minus the
    ones a stage entry leaves out; the kept text is exact — only the blank lines at a section's edges
    are dropped."""
    kept = []
    for name, text in _plan_obligation_sections(body):
        if name in _PLAN_OBLIGATION_OMITTED_SECTIONS:
            continue
        lines = text.split("\n")
        while lines and not lines[0].strip():
            lines = lines[1:]
        while lines and not lines[-1].strip():
            lines = lines[:-1]
        if lines:
            kept.append("\n".join(lines))
    return "\n\0\n".join(kept)


def _plan_obligation_digest(path) -> str:
    """T-14697 — the NORMATIVE digest of a due spec: its status and rule text across the read chain
    (base + continuation parts) — every parsed top-level field but `body` and the bookkeeping fields,
    plus the rule text of the chain-joined body. A prose, history or implementation-notes edit leaves it;
    a status flip or a rule-text edit moves it. A part that does not parse to a mapping -> the whole-chain
    digest (fail toward stale). An unreadable file raises OSError, as before."""
    fields, bodies = [], []
    for p in state.spec_part_paths(path):
        raw = Path(p).read_text(encoding="utf-8")
        try:
            doc = state.load_str(raw)
        except Exception:   # noqa: BLE001 — an unparseable part: the whole-chain digest
            return _plan_obligation_chain_digest(path)
        if not isinstance(doc, dict):
            return _plan_obligation_chain_digest(path)
        body = doc.get("body")
        if isinstance(body, str):
            bodies.append(body if body.endswith("\n") else body + "\n")
        fields.append({str(k): v for k, v in doc.items()
                       if str(k) not in _PLAN_OBLIGATION_BOOKKEEPING_FIELDS
                       and not (k == "body" and isinstance(body, str))})
    basis = json.dumps({"fields": fields, "rule_text": _plan_obligation_rule_text("".join(bodies))},
                       sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(f"{_PLAN_OBLIGATION_DIGEST_FORM}\0{basis}".encode("utf-8")).hexdigest()


def plan_obligation_view(maps, *, sequence, spec_source, map_errors=(), consumer=False) -> dict:
    """The projection. `maps` = `(own, kernel)` plan-axis binding maps (`_plan_stage_maps`), or None
    when the own corpus could not be read. Per stage the precedence of `_plan_stage_bundle_specs`: an id
    the kernel binds at that stage is (kernel, id), an id only this repo binds is (own, id) — on the
    engine's own session the kernel map is empty and every entry is own. `spec_source(realm, id)` ->
    the base file Path or None. COMPLETE or UNAVAILABLE, never silently empty: an unreadable corpus, a
    kernel read error (`map_errors`) or a bound entry whose file does not resolve or cannot be read is
    named in `unavailable`, and no reader proceeds on such a view."""
    view = {"stages": {}, "specs": {}, "unavailable": [str(e) for e in (map_errors or ())],
            "consumer": bool(consumer)}
    if maps is None:
        view["unavailable"].append("this repository's spec corpus could not be read, so the plan-axis "
                                   "bindings are unknown")
        return view
    own, kernel = maps
    for st in sequence:
        own_ids = [str(i) for i in (own.get(st) or [])]
        k_ids = [str(i) for i in (kernel.get(st) or [])]
        entries = ([("kernel" if i in k_ids else "own", i) for i in own_ids]
                   + [("kernel", i) for i in k_ids if i not in own_ids])
        if entries:
            view["stages"][st] = entries
        for key in entries:
            if key in view["specs"]:
                continue
            realm, sid = key
            try:
                path = spec_source(realm, sid)
            except Exception as exc:   # noqa: BLE001 — named, never swallowed
                path, why = None, f"{type(exc).__name__}: {exc}"
            else:
                why = "no file resolves for it"
            if path is None:
                view["unavailable"].append(f"{sid} ({realm}) is bound at plan-stage-entry:{st} but {why}")
                continue
            try:
                digest = _plan_obligation_digest(path)
                raw = Path(path).read_text(encoding="utf-8")
            except OSError as exc:
                view["unavailable"].append(f"{sid} ({realm}) bound at plan-stage-entry:{st} cannot be read "
                                           f"({exc})")
                continue
            m = re.search(r"(?m)^title:\s*(.+)$", raw)
            title = m.group(1).strip().strip("'\"") if m else ""
            view["specs"][key] = {"path": Path(path), "digest": digest, "title": title}
    return view


def plan_obligations_due(view: dict, through: str, *, sequence) -> tuple:
    """(due, future) at a boundary: `due` = the entries bound at a stage up to and INCLUDING `through`
    (the stage whose work the gate judges), each with its bound stage(s); `future` = the entries bound
    only after it. An unknown `through` (a terminal) -> ([], every entry)."""
    stages = (view or {}).get("stages") or {}
    specs = (view or {}).get("specs") or {}

    def _row(key, sts):
        info = specs.get(key) or {}
        return {"realm": key[0], "id": key[1], "stages": sts, "digest": info.get("digest"),
                "path": info.get("path"), "title": info.get("title") or ""}
    order, bound = [], {}
    for st in sequence:
        for key in stages.get(st) or []:
            if key not in bound:
                order.append(key)
            bound.setdefault(key, []).append(st)
    if through not in sequence:
        return [], [_row(k, bound[k]) for k in order]
    idx = list(sequence).index(through)
    due, future = [], []
    for key in order:
        sts = bound[key]
        due_sts = [s for s in sts if list(sequence).index(s) <= idx]
        if due_sts:
            due.append(_row(key, due_sts))
        else:
            future.append(_row(key, sts))
    return due, future


def plan_obligations_digest(due, digest_of=None) -> "str | None":
    """The freshness input: None when nothing is due (the basis then stays byte-identical), else a
    sha256 over the sorted `realm id digest` lines — an unrelated spec is absent from `due`.
    T-14697: `digest_of(row)`, when given, replaces `row["digest"]` — with the whole-chain digest of
    `row["path"]` it reproduces the pre-change due-set digest byte for byte."""
    if not due:
        return None
    lines = sorted(f"{d['realm']} {d['id']} {digest_of(d) if digest_of is not None else d['digest']}"
                   for d in due)
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def _plan_obligation_source(d: dict, consumer: bool) -> str:
    p = d.get("path")
    name = Path(p).name if p is not None else f"{d['id']}-*.yaml"
    return f"{'kernel ' if consumer and d['realm'] == 'kernel' else ''}specs/{name}"


def plan_obligations_block(due, future, *, through: str, consumer: bool = False,
                           change_check: bool = False) -> str:
    """The packet checklist of the obligations DUE at the audited boundary, from the same projection
    the session receives; "" when nothing is bound at any stage. `change_check` keeps the same data and
    asks only the change check's question: does the cumulative change contradict a listed obligation."""
    if not due and not future:
        return ""
    if change_check:
        ask = (f"The rules below are bound to the plan stages up to and including `{through}` "
               f"(`plan-stage-entry:<stage>`), listed from the ONE projection the session receives. "
               f"This is a change check: do NOT re-audit them. Report a listed obligation only where "
               f"the cumulative change shown above contradicts it or removes what met it — a "
               f"regression under question (2).")
    else:
        ask = (f"The rules below are bound to the plan stages up to and including `{through}` "
               f"(`plan-stage-entry:<stage>`); each is delivered to the session and listed here from ONE "
               f"projection. For EACH listed rule, judge whether the plan meets every clause that is due "
               f"by the end of stage `{through}`. A clause that is not yet due or does not apply to this "
               f"plan (for example a trial clause on a plan that skipped `trial`) is STATED as such, with "
               f"the reason — never passed over silently. A missed due clause is a finding.")
    lines = [f"\n## Plan-stage obligations due at this boundary (through stage `{through}`) — SPEC-0034",
             "", ask, ""]
    if due:
        for d in due:
            realm = f" [{d['realm']}]" if consumer else ""
            lines.append(f"- {d['id']}{realm} — {d['title']} — bound at: {', '.join(d['stages'])}; "
                         f"digest {d['digest']}; source `{_plan_obligation_source(d, consumer)}`")
    else:
        lines.append("- (none due at this boundary)")
    if future:
        lines += ["", "Not due at this boundary — do NOT judge these (bound only to later stages):"]
        for d in future:
            realm = f" [{d['realm']}]" if consumer else ""
            lines.append(f"- {d['id']}{realm} — bound at: {', '.join(d['stages'])}")
    return "\n".join(lines) + "\n"


def plan_obligation_catch_up(view: dict, rows, slug: str, status: str, *, sequence,
                             spec_source=None) -> list:
    """[(stage, [ids])] — the bound rules a plan has PASSED without receiving them. Passed stages =
    the sequence up to and including `status`, minus `trial` only when a `plan_stage_entered` row
    proves the specs->accepted skip. Per passed stage the proof of delivery is the union of the
    `delivered` lists of this plan's rows entering it; NO row (history invisible — an older plan, a
    worktree branched before the row, `rows` None) proves nothing, so every bound entry of that stage
    is a candidate (conservative; no historical completion is asserted and nothing is written). A
    recorded id carries no realm, so under -C it is proof only when UNAMBIGUOUS: an id that also
    resolves in the other realm (`spec_source(other, id)`) stays a candidate. Pure."""
    seq = list(sequence)
    if status not in seq:
        return []
    passed = seq[:seq.index(status) + 1]
    entered = [r.get("data") or {} for r in (rows or [])
               if isinstance(r, dict) and r.get("type") == "plan_stage_entered"
               and (r.get("data") or {}).get("slug") == slug]
    if "trial" in passed and any(d.get("to") == "accepted" and d.get("from") == "specs" for d in entered):
        passed.remove("trial")
    consumer = bool((view or {}).get("consumer"))
    out = []
    for st in passed:
        recorded = set()
        for d in entered:
            if d.get("to") == st:
                recorded.update(str(x) for x in (d.get("delivered") or []))
        late = []
        for realm, sid in ((view or {}).get("stages") or {}).get(st) or []:
            if sid in recorded:
                other = "own" if realm == "kernel" else "kernel"
                if not (consumer and spec_source is not None and spec_source(other, sid) is not None):
                    continue
            if sid not in late:
                late.append(sid)
        if late:
            out.append((st, late))
    return out


# ---------------------------------------------------------------------------------------------------
# T-14672 (SPEC-0034 §Project-declared plan check at the plan checkpoints) — ONE project command,
# declared as `plan_checks: {command: ...}` in the project's yitc-ops.yaml, run at the plan
# checkpoints BEFORE any auditor call, any stage write and any reuse of a prior verdict. The kernel
# knows no project's duties: it passes the plan path, the acting checkout and a FIXED phase name, and
# admits ONLY exit 0 — every other outcome refuses (closed vocabulary,
# lessons/carving-an-exception-into-a-fail-closed-gate.md). An undeclared project runs nothing.
PLAN_CHECK_SECTION = "plan_checks"
PLAN_CHECK_PHASES = ("finalize", "plan-check", "change-check", "specs", "accepted", "decomposition",
                     "executing")
PLAN_CHECK_TIMEOUT_SECONDS = 300          # GATE — the bound on one checker run (machine_settings INVENTORY)
_PLAN_CHECK_CAPTURE_BYTES = 8192          # the ring buffer: the last 8 KB of output, nothing on disk
_PLAN_CHECK_TAIL_LINES = 40               # rendered tail: at most 40 lines AND 4000 bytes
_PLAN_CHECK_TAIL_BYTES = 4000
_PLAN_CHECK_KILL_WAIT_SECONDS = 10        # after killpg on timeout: the bounded wait on the direct child
_PLAN_CHECK_READER_JOIN_SECONDS = 2       # the reader is joined this long, then abandoned (never drained)
_PLAN_CHECK_REASONS = {0: "admitted", 1: "duties-missing", 2: "could-not-check"}


class _PlanCheckCapture:
    """A fixed-size ring buffer over the checker's combined output: keeps the LAST `cap` bytes and
    discards older bytes as they arrive, so captured storage never exceeds `cap` whatever the checker
    writes. `seen` counts every byte fed. Thread-safe: the reader thread feeds, the verb reads."""

    def __init__(self, cap: int = _PLAN_CHECK_CAPTURE_BYTES):
        import threading
        self.cap = cap
        self.seen = 0
        self._buf = bytearray()
        self._lock = threading.Lock()

    def feed(self, chunk: bytes) -> None:
        with self._lock:
            self.seen += len(chunk)
            if len(chunk) >= self.cap:
                self._buf = bytearray(chunk[-self.cap:])
                return
            self._buf += chunk
            over = len(self._buf) - self.cap
            if over > 0:
                del self._buf[:over]

    def data(self) -> bytes:
        with self._lock:
            return bytes(self._buf)


def _plan_check_drain(fd: int, capture: _PlanCheckCapture) -> None:
    """The daemon reader: drain the pipe into the ring buffer until EOF (or a read error)."""
    try:
        while True:
            chunk = os.read(fd, 4096)
            if not chunk:
                return
            capture.feed(chunk)
    except (OSError, ValueError):
        return


def _plan_check_tail(raw: bytes) -> str:
    """The rendered tail of the checker's output: decoded with replacement, the last 40 lines, then
    cut to the last 4000 bytes (one enormous line is cut by the byte cap)."""
    text = raw.decode("utf-8", "replace")
    text = "\n".join(text.splitlines()[-_PLAN_CHECK_TAIL_LINES:])
    enc = text.encode("utf-8")
    if len(enc) > _PLAN_CHECK_TAIL_BYTES:
        # the cut may start inside a multibyte character: drop that partial prefix (never replace it,
        # a replacement character would push the tail past the byte cap)
        text = enc[-_PLAN_CHECK_TAIL_BYTES:].decode("utf-8", "ignore")
    return text.strip()


def _plan_check_command(carrier_root, *, verb: str, _die) -> "str | None":
    """The declared `plan_checks.command`, or None when the project declares none (no carrier, an
    empty carrier, no section). An unreadable carrier and a malformed declaration REFUSE: whether a
    check is declared, or what it is, cannot then be told (fail-closed)."""
    from lib import host_apply as _host_apply
    carrier_path = Path(carrier_root) / _host_apply.CONSUMER_OPS_CONTRACT
    if not carrier_path.is_file():
        return None
    try:
        carrier = state.load_ops(carrier_path)
    except Exception as exc:                           # noqa: BLE001 — unreadable: cannot tell, say so
        _die(f"{verb}: refused before any auditor call — unreadable-carrier: {carrier_path} could not be "
             f"read ({exc}), so whether a `{PLAN_CHECK_SECTION}` check is declared cannot be told. Nothing "
             f"was written. Fix the carrier, then re-run `yitc-v2 {verb}` (SPEC-0034 §Project-declared "
             f"plan check).")
    if carrier is None:
        return None
    if not isinstance(carrier, dict):
        _die(f"{verb}: refused before any auditor call — unreadable-carrier: {carrier_path} is not a "
             f"mapping, so whether a `{PLAN_CHECK_SECTION}` check is declared cannot be told. Nothing was "
             f"written. Fix the carrier, then re-run `yitc-v2 {verb}`.")
    if PLAN_CHECK_SECTION not in carrier:
        return None
    sec = carrier.get(PLAN_CHECK_SECTION)
    cmd = sec.get("command") if isinstance(sec, dict) else None
    if not isinstance(cmd, str) or not cmd.strip():
        _die(f"{verb}: refused before any auditor call — malformed-declaration: `{PLAN_CHECK_SECTION}` in "
             f"{carrier_path.name} must be a mapping with one non-empty shell-command string under "
             f"`command`, got {type(sec).__name__ if not isinstance(sec, dict) else repr(sec)}. Nothing was "
             f"written. Fix the declaration, then re-run `yitc-v2 {verb}` (SPEC-0034 §Project-declared "
             f"plan check).")
    return cmd


def run_project_plan_check(plan_path, phase: str, *, slug: str, verb: str, carrier_root, checkout,
                           _append_event, _die) -> "dict | None":
    """Run the project's declared plan check at one checkpoint (SPEC-0034 §Project-declared plan check).

    Returns None when the project declares no check (nothing runs, nothing is printed or journaled).
    Otherwise runs the command ONCE — bounded in time (PLAN_CHECK_TIMEOUT_SECONDS, the group killed on
    expiry) and in captured storage (a fixed ring buffer) — appends ONE `project_plan_check_ran` row,
    and either returns the admitted outcome (exit 0) or refuses through `_die`, naming the command, the
    phase, the exit or reason and the checker's output tail. No caching: every call runs the checker."""
    import signal
    import subprocess
    import threading
    if phase not in PLAN_CHECK_PHASES:
        raise ValueError(f"run_project_plan_check: unknown phase {phase!r} (one of {PLAN_CHECK_PHASES})")
    cmd = _plan_check_command(carrier_root, verb=verb, _die=_die)
    if cmd is None:
        return None
    plan_abs = str(Path(plan_path).resolve())
    checkout_abs = str(Path(checkout).resolve())
    env = dict(os.environ)
    env.update({"YITC_PLAN_CHECK_PLAN": plan_abs, "YITC_PLAN_CHECK_CHECKOUT": checkout_abs,
                "YITC_PLAN_CHECK_PHASE": phase})
    capture = _PlanCheckCapture()
    t0 = time.monotonic()
    rc = None
    launch_error = None
    try:
        proc = subprocess.Popen(cmd, shell=True, cwd=checkout_abs, env=env, stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)
    except OSError as exc:
        reason, launch_error = "launch-failure", str(exc)
    else:
        reader = threading.Thread(target=_plan_check_drain, args=(proc.stdout.fileno(), capture),
                                  name="plan-check-reader", daemon=True)
        reader.start()
        try:
            rc = proc.wait(timeout=PLAN_CHECK_TIMEOUT_SECONDS)
            reason = _PLAN_CHECK_REASONS.get(rc, "unexpected-exit")
        except subprocess.TimeoutExpired:
            reason = "timeout"
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                pass
            try:
                proc.wait(timeout=_PLAN_CHECK_KILL_WAIT_SECONDS)
            except subprocess.TimeoutExpired:
                pass
        reader.join(_PLAN_CHECK_READER_JOIN_SECONDS)   # a descendant holding the pipe cannot block us
    seconds = round(time.monotonic() - t0, 3)
    admitted = reason == "admitted"
    tail = _plan_check_tail(capture.data()) if launch_error is None else launch_error
    _append_event("project_plan_check_ran", None,
                  {"slug": slug, "plan": plan_abs, "phase": phase, "verb": verb, "command": cmd,
                   "outcome": "admitted" if admitted else "refused", "exit": rc, "reason": reason,
                   "seconds": seconds})
    if admitted:
        sys.stderr.write(f"# project plan check ({PLAN_CHECK_SECTION}, phase {phase}): admitted — "
                         f"`{cmd}` exit 0 in {seconds}s\n")
        if tail:
            sys.stderr.write(tail + "\n")
        return {"phase": phase, "command": cmd, "exit": rc, "reason": reason, "seconds": seconds}
    if reason == "timeout":
        what = f"timeout after {PLAN_CHECK_TIMEOUT_SECONDS}s (process group killed)"
    elif reason == "launch-failure":
        what = "launch-failure (the command could not be started)"
    else:
        what = f"exit {rc} ({reason})"
    _die(f"{verb}: refused before any auditor call — the project's declared plan check "
         f"(`{PLAN_CHECK_SECTION}` in yitc-ops.yaml) did not admit phase {phase!r}: command `{cmd}` — "
         f"{what}. Only exit 0 admits; exit 1 = duties missing, exit 2 = could not check, anything "
         f"else refuses too.\n--- checker output (tail) ---\n{tail or '(no output)'}\n--- end ---\n"
         f"Fix what it names, then re-run `yitc-v2 {verb}`. No auditor ran, no verdict was reused and "
         f"the plan was not changed (SPEC-0034 §Project-declared plan check).")
    return None   # unreachable — _die exits


def cmd_plan_draft(args: argparse.Namespace, *, PLANS_DIR, _append_event, _die, _emit_read_gate_refused, _load_draft, _plan_content_hash, _plan_draft_sections_filled, _postcheck_probe_block_declared, _require_reads, _require_writing_worktree, _resolve_session_ref, _run_plan_checks=None) -> None:
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
    # T-14672 (SPEC-0034 §Project-declared plan check) — the project's declared check, phase `finalize`,
    # before the read-check and the proof row: a refusal writes nothing. None = no runner (unchanged).
    if _run_plan_checks is not None:
        _run_plan_checks(path, "finalize", slug, verb=f"plan draft --finalize {slug}")
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
        _print_plan_stage_delivery("draft", delivered,
                                   is_consumer=bool(_is_consumer_build and _is_consumer_build()))


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
            # T-12976 — SPEC-0151 §Internal 3 authoring WARN at the birth seam, all-specs scope (a
            # plan-born spec is authored `draft`, so `spec new`/`spec edit` never evaluated it).
            # Report-only: never raises, never changes the return value or the transition.
            reason = spec_lib.anchor_rule_violation({**d, "status": "proposed"}, statuses=("proposed",),
                                                    all_specs=True)
            if reason:
                print(f"⚠ anchor-rule (SPEC-0151) at plan-spec birth: {d.get('id') or p.name} {reason}",
                      file=sys.stderr)
    return sorted(born)


def _restore_withdrawn_draft_specs(written: list, *, write_text_atomic) -> None:
    """T-13857 — put back, byte for byte, the files a `cancelled` / `rejected` transition started to
    write and then could not complete. `written` = [(label, path, text before the write)] — every
    file the transition STARTED on, whether or not its write happened. A file that already reads as
    before is left alone. Each other file is put back with the atomic writer, so a restore that
    cannot write leaves that file WHOLE, as the transition wrote it — never empty or partial. Such
    a file is named on stderr; the caller re-raises the failure that brought it here either way,
    and no failure of one restore stops the others."""
    stuck = []
    for label, p, before in written:
        try:
            if p.read_text(encoding="utf-8") == before:
                continue
        except BaseException:
            pass   # unreadable now: try to put it back
        try:
            write_text_atomic(p, before)
        except BaseException as e:
            stuck.append(f"{label} ({p.name}: {e})")
    if stuck:
        print("⚠ plan stage: the transition failed AND these files could not be restored — each is "
              "left on disk as the failed transition wrote it and is named by no journal row: "
              + "; ".join(stuck), file=sys.stderr)


def _withdraw_plan_draft_specs(plan_slug: str, *, _decision_apply_field_edits, _plan_draft_specs, write_text_atomic, then=None, then_path=None) -> list:
    """T-13857 (SPEC-0005 §4) — the END of a plan's still-draft specs when the plan itself ends
    `cancelled` / `rejected`: flip each one to status: withdrawn, in sorted-id order, then run `then`
    (the plan's own terminal write, to the file `then_path`) as part of the same unit. Returns
    [(spec id, path, text before the write)] for the specs THIS call flipped — the set the caller
    records on the transition row and stages in the terminal-record commit, and no other file.

    The set is `_plan_draft_specs` — the SAME selector the accept-gate audits and
    `_birth_plan_draft_specs` births (status: draft AND proposed_by == plan_slug) — so a `proposed`
    or `active` spec of the plan, a spec the plan withdrew earlier, and a work-first spec are never
    in it. The write is the same comment-preserving line edit the birth uses.

    ALL OR NOTHING on a failure: each file — every spec, then the plan file — is registered for the
    restore BEFORE its write starts, so a failure raised before, during or after any one write puts
    back every file the unit had started on, the one in flight included, and then propagates. So a
    failed attempt leaves no spec withdrawn and the plan non-terminal, and the next attempt meets
    every draft again and records all of them — there is never a spec withdrawn by an earlier
    attempt that a later one would have to find."""
    written, started = [], []
    try:
        for sid, p, raw in _plan_draft_specs(plan_slug):
            started.append((sid, p, raw))
            _decision_apply_field_edits(p, raw, [("status", "status: withdrawn")], {"status": "withdrawn"})
            written.append((sid, p, raw))
        if then is not None:
            if then_path is not None:
                started.append(("the plan file", then_path, then_path.read_text(encoding="utf-8")))
            then()
    except BaseException:
        _restore_withdrawn_draft_specs(started, write_text_atomic=write_text_atomic)
        raise
    return written


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


def _print_plan_stage_delivery(stage: str, delivered: list, *, is_consumer: bool = False,
                               _deliver_stage_bundle_contracts, homes=None) -> None:
    """SINGLE source for the plan-stage bundle delivery (the `delivered` spec ids), shared by
    `cmd_plan_stage` (every transition) AND `cmd_plan_file` (draft-entry, T-0416) so the delivery
    has ONE home — no mirror/copy of the print block (audit-pre F0). The slug→stage
    header line + the per-stage work-items pointer stay caller-local (they are transition-specific).

    T-13708 — a non-empty bundle is handed to the stage deliverer (`_deliver_stage_bundle_contracts`,
    injected by the host): each contract arrives as its contract view with the ordinary `graph query`
    receipt the plan-stage read check credits, or as one pointer line while this context epoch
    already holds the same content. Before this the ids were printed and each contract was fetched
    by hand, as the full point-lookup render. The deliverer reads its first argument for ONE thing,
    the realm map of a `-C` consumer's bundle; for the plan-axis binding token passed here it reads
    the plan-axis realms (T-14408), so a kernel-bound contract is fetched with `--kernel` and the
    plan-stage read check credits it by that realm (see `_require_reads`). A delivery that fails leaves the transition as recorded and each contract one
    `graph query` away: the plan-stage read check then refuses with its ready commands."""
    if delivered:
        print(f"read before acting — plan-stage-entry:{stage} contract(s), rendered below as contract "
              f"views (or as a one-line pointer when this context epoch already holds the same "
              f"content); each counts toward the read-gate (SPEC-0042/0050) only once its delivery "
              f"completes: {', '.join(delivered)}")
        try:
            _deliver_stage_bundle_contracts(f"plan-stage-entry:{stage}", list(delivered))
        except Exception:   # noqa: BLE001 — never break the verb whose transition is already recorded
            pass
    else:
        # T-12988 — name the REAL homes, never the stale T-0317 promise. T-14408 — under -C the bundle
        # already reads the kernel corpus, so an empty one means NO corpus read binds this stage; the
        # homes named are the host's derivation from the plan-axis bindings (`homes`), and the fixed
        # pair below only when those bindings are empty too.
        homes = list(homes or []) or ((["SPEC-0043"] if stage == "draft" else []) + ["SPEC-0034"])
        hints = "; ".join(f"`{graph_lib.spec_query_hint(h, is_consumer=is_consumer, cli='yitc-v2')}`"
                          for h in homes)
        print(f"this repo's spec corpus binds no spec to plan-stage-entry:{stage} — the plan-stage "
              f"doctrine lives in {', '.join(homes)} (read: {hints}).")


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
    # T-14627 (SPEC-1061 §3) — two admission arms: (i) the anchor GREEN/YELLOW and fresh on both
    # hashes (the predicate below, unchanged); (ii) the latest change check binds this anchor to the
    # current hashes and closes every anchor high (`_plan_change_check_admission`). The current hashes
    # and the per-input digests come from ONE pass of the freshness hash.
    cur_hash, cur_parts = _plan_content_hash(body), {}
    cur_accept = _plan_accept_freshness_hash(slug, body, fm, parts_out=cur_parts)   # SPEC-0082 — same fm-aware basis the check recorded
    cue = " — or, after one fix batch, the change check from this anchor (SPEC-1061 §2)."

    def _arm_ii():
        adm, why = _plan_change_check_admission(
            slug, av, current={"content_hash": cur_hash, "accept_freshness_hash": cur_accept},
            cur_parts=cur_parts, DECISIONS_DIR=DECISIONS_DIR, _read_yaml=_read_yaml)
        if adm is None and why:
            _die(f"{slug}: `plan stage accepted` refused — {why} (SPEC-1061 §3). Next: `yitc-v2 audit adhoc "
                 f"--plan {slug}` (a change check from the anchor) or `yitc-v2 plan check {slug}` (a fresh anchor).")
        return adm

    admission = None
    if verdict not in AUDIT_VERDICT_CLOSURE_OK:   # GREEN | YELLOW — a RED anchor admits on arm (ii) only
        admission = _arm_ii()
        if admission is None:
            _die(f"{slug}: last `plan check` verdict is {verdict or 'MISSING'} — accept needs GREEN/YELLOW. "
                 f"Rework the plan, then re-run `yitc-v2 plan check {slug}`{cue}")
    # T-14456 (SPEC-1058 §2-§3) — an opted-in plan's registry + audited prototype pair, refused by name
    # BEFORE the freshness checks and the spec birth; None (nothing read) for every other plan. Runs on
    # BOTH admission arms (SPEC-1061 §3: every non-freshness check applies alike).
    proto_pin = _require_plan_prototype_at_accept(slug, fm, body, av, REPO_ROOT=REPO_ROOT, _die=_die)
    if admission is None:
        checked_hash = av.get("content_hash")
        if not checked_hash:
            _die(f"{slug}: the recorded check predates content-hash freshness — re-run `yitc-v2 plan check {slug}`.")
        # T-0332 — the accept-gate audit must cover the PLAN-BORN draft specs vs the active+proposed
        # corpus, and the draft→proposed BIRTH is gated on a check whose freshness reflects the draft
        # specs + corpus CONTENT. Editing a draft spec (or a corpus spec) after the check stales the
        # gate (AC2) — so a draft spec is never born `proposed` without a fresh corpus-coherence audit.
        # A check predating this field (recorded before T-0332) is stale by construction — re-run.
        checked_accept = av.get("accept_freshness_hash")
        if checked_hash == cur_hash and checked_accept == cur_accept:
            admission = {"arm": "i", "anchor": str(audit_path.relative_to(REPO_ROOT))}
        else:
            admission = _arm_ii()
        if admission is None and checked_hash != cur_hash:
            _die(f"{slug}: plan BODY edited since the check (content hash mismatch) — the verdict is stale. "
                 f"The freshness basis is `content_hash (plan body)`: it covers the plan BODY only, so a "
                 f"FRONTMATTER-field edit (e.g. `implementation_plan`) does NOT stale the check, while any "
                 f"body edit (e.g. the realization-exit block) does — compose the body BEFORE the check "
                 f"(SPEC-0034 §accepted Work-ORDER). Re-run `yitc-v2 plan check {slug}` before accept{cue}")
        if admission is None:
            _die(f"{slug}: the accept-gate audit no longer covers the current draft specs / corpus "
                 f"(a draft spec or an active/proposed corpus spec changed since `plan check`, or the "
                 f"check predates the draft-spec corpus audit). The draft→proposed birth needs a FRESH "
                 f"GREEN/YELLOW check that audited THESE draft specs against the live corpus — re-run "
                 f"`yitc-v2 plan check {slug}` before accept (T-0332){cue}")
    specs_born = _birth_plan_draft_specs(slug)
    structural = av.get("structural_findings") or []
    event_data = {"slug": slug, "verdict_ref": str(audit_path.relative_to(REPO_ROOT)),
                  "checked_hash": cur_hash, "specs_born": specs_born,
                  "structural_findings_consumed": len(structural),
                  "admitted_on": admission}   # T-14627 — the arm and the record it admitted on
    if proto_pin:
        # SPEC-1058 §2 — pin the audited pair; the caller's status write persists it, and every later
        # registry check reads it instead of the moving tag. Additive event keys only on this path.
        fm.update(proto_pin)
        event_data.update(proto_pin)
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


def _require_plan_decomposition_ready(slug: str, fm: dict, body: str, *, AUDIT_VERDICT_CLOSURE_OK, DECISIONS_DIR, SPECS_DIR, SPEC_ABANDONED_TERMINAL, _die, _plan_content_hash, _read_yaml) -> None:
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
    or `superseded`/`retired` corpus spec still BLOCKS, as before.

    T-14352: clause (c) reads the plan's OWN born specs (`proposed_by == slug`) only — never the broad
    `_plan_specs` finalization corpus (T-0256/T-9152), which also holds specs activated by any task that
    merely CITES the slug. Such a task may belong to another plan and its specs may be long superseded
    (<project> X-2138); they are not this plan's births, so they cannot be "not yet proposed" here."""
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
    checked_hash, cur_hash = av.get("content_hash"), _plan_content_hash(body)
    # T-14627 (SPEC-1061 §4) — «fresh» = arm (i): the anchor GREEN/YELLOW AND its body hash current;
    # else arm (ii) over this gate's basis (the body hash). A RED anchor ALWAYS takes arm (ii), whether
    # the body moved or not. With no change check on record the old refusals stand, plus a cue line.
    if not (verdict in AUDIT_VERDICT_CLOSURE_OK and checked_hash and checked_hash == cur_hash):
        adm, why = _plan_change_check_admission(slug, av, current={"content_hash": cur_hash},
                                                DECISIONS_DIR=DECISIONS_DIR, _read_yaml=_read_yaml)
        if adm is None:
            cue = " — or, after one fix batch, the change check from this anchor (SPEC-1061 §2)."
            if why:
                _die(f"{slug}: `plan stage decomposition` refused — {why} (SPEC-1061 §4). Next: `yitc-v2 "
                     f"audit adhoc --plan {slug}` (a change check from the anchor) or `yitc-v2 plan check {slug}`.")
            if verdict not in AUDIT_VERDICT_CLOSURE_OK:
                _die(f"{slug}: `plan check` verdict is {verdict or 'MISSING'} — decomposition needs "
                     f"GREEN/YELLOW: `yitc-v2 plan check {slug}`{cue}")
            _die(f"{slug}: `plan check` is stale (content-hash mismatch) — the freshness basis is "
                 f"`content_hash (plan body)`: it covers the plan BODY only, so a FRONTMATTER-field edit "
                 f"(e.g. `implementation_plan`) does NOT stale it, while any body edit (e.g. the "
                 f"realization-exit block) does — compose the body BEFORE the check (SPEC-0034 §accepted "
                 f"Work-ORDER). Re-run `yitc-v2 plan check {slug}`{cue}")
    ip = fm.get("implementation_plan")
    if not (ip and str(ip).strip()):
        _die(f"{slug}: implementation_plan is empty — compose the decomposition map (the acceptance-stage "
             f"output) into the plan frontmatter before `plan stage decomposition`.")
    own = {}
    for p in state.scan_specs(SPECS_DIR):   # SPEC-* glob excludes _template.yaml
        d = _read_yaml(p)
        if isinstance(d, dict) and d.get("proposed_by") == slug:
            own[d.get("id") or p.stem] = d.get("status")
    not_proposed = [sid for sid, stt in sorted(own.items())
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

    T-10825 (<project> X-0679): annotating an entry is established card practice
    (`tests/config_acceptance.py (new cases)`, `bin/lib/journal.py — the liveness fold`), and keying
    on the annotated text made the annotated entry a DIFFERENT surface from its bare form — so a
    genuinely shared surface reported NO overlap and the auditor's shared-surface context went
    silently empty (<project> T-0158 vs T-0159, one gate pass burned on that blindness).

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
    prompt (SPEC-0083 P5 set-level semantic-coherence bullet).

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
                "(SPEC-0083 P5 set-level semantic coherence; X-0593)")
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
                "(SPEC-0083 P5 set-level semantic coherence; X-0593)\n"
                "(shared-surface view unavailable — read the per-card expected_touch above)")


def _plan_spec_activation(cards: list, slug: str, *, SPECS_DIR, _read_yaml) -> str:
    """T-10918 (X-0707) — the PLAN-BORN PROPOSED-SPEC ACTIVATION view for the gate-executing fidelity
    prompt (SPEC-0083 P5 singular-activation bullet).

    P5 asks the auditor whether each `proposed` spec has EXACTLY ONE `activation_owner_task` — but in
    V2 that owner is a spec→task POINTER on the SPEC yaml, not a per-card field, so a CARD-ONLY
    rendering carries no evidence for the question at all. The auditor answered it from the only proxy
    in the prompt (each card's `cites:`) and reported "no card owns activation of SPEC-XXXX": a HIGH
    that was both FALSE (a spec DOES carry the pointer) and UNVERIFIABLE (nothing in the prompt could
    confirm or refute it). In a MANDATORY-BLOCKING gate that inflated the finding count AND burned one
    of the two ceiling passes that exist to resolve REAL findings — the compound cost X-0707 reports.
    Same defect class as T-10825 (<project> X-0679): an EMPTY auditor context read as a genuine absence.

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
            "(SPEC-0083 P5 singular activation; X-0707)")
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


# T-14624 — the card-set cue for the P5 path-evidence question: a card that names itself a verifier, and
# an acceptance that names one connected path. Report-only wording keys, never a gate.
_VERIFIER_CARD_RE = re.compile(r"\bverif(?:y|ier|iers|ies|ication)\b", re.IGNORECASE)
_CONNECTED_PATH_RE = re.compile(r"\bconnected path\b|\bone path\b|\bpath through\b", re.IGNORECASE)


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
            # is present + plausible on every cut card (SPEC-0083 P5 touch-forecast bullet). An empty
            # forecast on a decomposed card is a cut-fidelity gap (SPEC-0046 §Persist-blast-radius).
            f"    expected_touch: {d.get('expected_touch') or []}\n"
            f"    acceptance: {d.get('acceptance') or []}")
        # T-14624: a VERIFIER card whose acceptance names no connected path gets a report-only cue line
        # beside it, so the P5 path-evidence question (its template's home: SPEC-1058 §3) lands on THAT
        # card. Text only — the auditor judges; nothing here refuses or gates.
        _role = f"{d.get('title') or ''} {' '.join(map(str, d.get('scope') or []))}"
        _proof = " ".join(map(str, d.get("acceptance") or []))
        if _VERIFIER_CARD_RE.search(_role) and not _CONNECTED_PATH_RE.search(_proof):
            block += ("\n    path-evidence cue: a verifier card whose acceptance names no connected path — "
                      "ask the P5 path-evidence question (the verifier template, SPEC-1058 §3)")
        lines.append(block)
        cards.append({"id": tid, "expected_touch": list(d.get("expected_touch") or []),
                      "cites": list(d.get("cites") or [])})
    if not lines:
        return "(no task cards filed for this plan)"
    return ("\n".join(lines) + "\n\n"
            + _plan_shared_surfaces(cards, SPECS_DIR=SPECS_DIR, _read_yaml=_read_yaml) + "\n\n"
            + _plan_spec_activation(cards, slug, SPECS_DIR=SPECS_DIR, _read_yaml=_read_yaml))


_CUT_CREATES_RE = re.compile(r"^\s*Creates \(declared new\):\s*(\S+)")
_CUT_OWNS_RE = re.compile(r"^\s*Owns:\s*(.*)$", re.DOTALL)
_CUT_SPEC_PATH_RE = re.compile(r"(?:^|/)(SPEC-\d{4})[-.]")
# T-14682 (SPEC-0070 §3): a card marks its edit of a file append-only by `(append)` after the path in an
# expected_touch entry (`tests/layers.yaml (append)`) or after the locator in its `Owns:` line.
_CUT_APPEND_TOUCH_RE = re.compile(r"\s\(append\)\s*$")
_CUT_APPEND_OWNS_RE = re.compile(r"`([^`\s]+)`\s*\(append\)")
# T-14682 (SPEC-0070 §3): a non-append-only file named by this many cards draws the modularity hint.
_CUT_SHARED_FILE_HINT_MIN = 3


def _cut_set_precheck(rows: list) -> dict:
    """T-14626 (SPEC-0070 §3) — the MECHANICAL cut-set pre-check printed before the decomposition-fidelity
    gate. Pure over the cut rows [{id, doc}] (`_plan_cut_rows`). REPORT-ONLY: it never refuses, and the
    gate runs whatever it finds. Order = the transitive closure of `requires` among the cut's own cards (a
    target outside the cut is not part of what is checked). Returns {defects, overlaps, longest_chain}:
    a requires cycle; two writers of one spec not ordered by requires; a declared creation (the skeleton's
    `Creates (declared new):` line or a `(new)` locator in `Owns:`, T-14625) used by a card not ordered
    after its creator; a spec in `Owns:` missing from the same card's expected_touch. An EXISTING shared
    file named by unordered cards is an overlap line — never a defect, never a defining card.

    T-14682 adds {hints, append_only}. A non-spec file is APPEND-ONLY when it is union-merged at land (the
    one carrier, `dispatch._touch_path_is_union_merged`) or when EVERY card naming it marks it `(append)`;
    it is non-serialising — no overlap line, no hint — and is listed in `append_only`. Every other non-spec
    file named by `_CUT_SHARED_FILE_HINT_MIN` or more cards, ordered by requires or not, draws one hint."""
    from lib import dispatch as dispatch_lib   # noqa: PLC0415 — the union-merged carrier; lazy, no cycle
    ids = sorted(str(r.get("id") or "?") for r in rows)
    docs = {str(r.get("id") or "?"): (r.get("doc") if isinstance(r.get("doc"), dict) else {}) for r in rows}
    member = set(ids)

    def _lst(v):
        return [str(x) for x in v] if isinstance(v, list) else ([str(v)] if isinstance(v, str) and v else [])

    req = {t: sorted({r for r in _lst(docs[t].get("requires")) if r in member}) for t in ids}
    anc = {}
    for t in ids:   # full reachability per card, no shared cache — exact through a requires cycle too
        seen, todo = set(), list(req[t])
        while todo:
            r = todo.pop()
            if r not in seen:
                seen.add(r)
                todo.extend(req[r])
        anc[t] = seen

    def _ordered(a, b):
        return a in anc.get(b, set()) or b in anc.get(a, set())

    defects, overlaps = [], []
    # (1) requires cycles — Tarjan SCC over the member edges.
    idx, low, stack, on, sccs, n = {}, {}, [], set(), [], [0]

    def _strong(v):
        idx[v] = low[v] = n[0]
        n[0] += 1
        stack.append(v)
        on.add(v)
        for w in req[v]:
            if w not in idx:
                _strong(w)
                low[v] = min(low[v], low[w])
            elif w in on:
                low[v] = min(low[v], idx[w])
        if low[v] == idx[v]:
            comp = []
            while True:
                w = stack.pop()
                on.discard(w)
                comp.append(w)
                if w == v:
                    break
            sccs.append(sorted(comp))

    for t in ids:
        if t not in idx:
            _strong(t)
    for comp in sorted(sccs):
        if len(comp) > 1 or comp[0] in req[comp[0]]:
            defects.append(f"requires cycle among {', '.join(comp)} — no build order exists")
    # per-card surfaces
    owns = {}
    touch = {}
    creates = {}
    marks_append = {}
    for t in ids:
        d = docs[t]
        owns_text = " ".join(m.group(1) for s in _lst(d.get("scope")) for m in [_CUT_OWNS_RE.match(s)] if m)
        owns[t] = owns_text
        touch[t] = {_surface_key(e) for e in _lst(d.get("expected_touch")) if _surface_key(e)}
        marked = {_surface_key(e) for e in _lst(d.get("expected_touch")) if _CUT_APPEND_TOUCH_RE.search(e)}
        marked |= {_surface_key(m.group(1)) for m in _CUT_APPEND_OWNS_RE.finditer(owns_text)}
        marks_append[t] = {p for p in marked if p and not p.startswith("specs/")}
        made = {m.group(1) for s in _lst(d.get("scope")) for m in [_CUT_CREATES_RE.match(s)] if m}
        made |= {m.group(1).split("#", 1)[0] for m in _UNIT_LOCATOR_RE.finditer(owns_text) if m.group(2)}
        creates[t] = {p for p in made if p}

    def _specs_in_touch(t):
        return {m.group(1) for p in touch[t] if p.startswith("specs/") for m in [_CUT_SPEC_PATH_RE.search(p)] if m}

    # (2) a spec named in Owns but absent from the same card's expected_touch.
    writers = {}
    for t in ids:
        named = set(_UNIT_SPEC_RE.findall(owns[t]))
        named |= {m.group(1) for loc in _UNIT_LOCATOR_RE.finditer(owns[t])
                  for m in [_CUT_SPEC_PATH_RE.search(loc.group(1))] if m and loc.group(1).startswith("specs/")}
        in_touch = _specs_in_touch(t)
        for sid in sorted(named - in_touch):
            defects.append(f"{t} names {sid} in Owns but its expected_touch has no specs/{sid}-… path")
        for sid in named | in_touch:
            writers.setdefault(sid, set()).add(t)
    # (3) two writers of one spec not ordered by requires.
    for sid in sorted(writers):
        ws = sorted(writers[sid])
        for i, a in enumerate(ws):
            for b in ws[i + 1:]:
                if not _ordered(a, b):
                    defects.append(f"{sid} has two writers not ordered by requires: {a}, {b}")
    # (4) a declared creation used by a card not ordered after its creator.
    created_by = {}
    for t in ids:
        for p in creates[t]:
            created_by.setdefault(p, set()).add(t)
    for p in sorted(created_by):
        for c in sorted(created_by[p]):
            for u in ids:
                if u != c and p in touch[u] and c not in anc.get(u, set()):
                    defects.append(f"{p} is declared new by {c} but {u} uses it without requiring {c}")
    # (5a) T-14682 — append-only files: union-merged, or marked `(append)` by every card naming them. A card
    # names a file by its touch forecast, by ANY `Owns:` locator (marked or not) or by a declared creation —
    # an unmarked writer on any of the three keeps the file serialising (audit-post fp1:ba07745788c92227).
    named_by = {}
    for t in ids:
        owns_locs = {_surface_key(m.group(1)) for m in _UNIT_LOCATOR_RE.finditer(owns[t])}
        owns_locs = {p for p in owns_locs if "/" in p or re.search(r"\.[A-Za-z0-9]+$", p)}
        for p in touch[t] | owns_locs | creates[t] | marks_append[t]:
            if p and not p.startswith("specs/"):
                named_by.setdefault(p, set()).add(t)
    append_set = {p for p, hs in named_by.items()
                  if dispatch_lib._touch_path_is_union_merged(p) or all(p in marks_append[h] for h in hs)}
    append_only = sorted(append_set)
    serialising = {p: hs for p, hs in named_by.items() if p not in append_set}
    # (5) overlap — an EXISTING non-spec, non-append-only file named by unordered cards: report-only.
    by_path = {p: hs for p, hs in serialising.items() if p not in created_by}
    for p in sorted(by_path):
        hs = sorted(by_path[p])
        if any(not _ordered(a, b) for i, a in enumerate(hs) for b in hs[i + 1:]):
            overlaps.append(f"{p} is edited by independent cards {', '.join(hs)} (overlap, report-only — "
                            f"not a defect)")
    # (5b) T-14682 — the modularity hint: a non-append-only file many cards name, ordered or not.
    hints = []
    for p in sorted(serialising):
        hs = sorted(serialising[p])
        if len(hs) >= _CUT_SHARED_FILE_HINT_MIN:
            hints.append(f"{p} is edited by {len(hs)} cards ({', '.join(hs)}) — check whether they touch "
                         f"different concerns in it (SPEC-0046 §A)")
    # (6) the longest requires chain over the acyclic part (cycle members are skipped).
    cyc = {t for comp in sccs if len(comp) > 1 or comp[0] in req[comp[0]] for t in comp}
    best = {}

    def _chain(t):
        if t not in best:
            tails = [_chain(r) for r in req[t] if r not in cyc]
            best[t] = max(tails, key=lambda c: (len(c), c), default=[]) + [t]
        return best[t]

    longest = max((_chain(t) for t in ids if t not in cyc), key=lambda c: (len(c), c), default=[])
    return {"defects": defects, "overlaps": overlaps, "hints": hints, "append_only": append_only,
            "longest_chain": longest}


def _print_cut_set_precheck(rows: list) -> dict:
    """Compute + print the cut-set pre-check (report-only, exception-tolerant: a broken pre-check prints
    `unavailable` and the gate runs as before)."""
    try:
        pc = _cut_set_precheck(rows)
    except Exception as exc:   # report-only: a render helper never crashes the mandatory gate
        print(f"cut-set pre-check (report-only, SPEC-0070 §3): unavailable ({type(exc).__name__})")
        return {"error": type(exc).__name__}
    chain = pc["longest_chain"]
    chain_line = f"longest requires chain: {len(chain)}" + (f" ({' -> '.join(chain)})" if chain else "")
    if not (pc["defects"] or pc["overlaps"] or pc["hints"] or pc["append_only"]):
        print(f"cut-set pre-check (report-only, SPEC-0070 §3): no defect, no overlap; {chain_line}")
    else:
        print("cut-set pre-check (report-only, SPEC-0070 §3 — the gate runs regardless):")
        for line in pc["defects"]:
            print(f"  - DEFECT: {line}")
        for line in pc["overlaps"]:
            print(f"  - {line}")
        for line in pc["hints"]:
            print(f"  - MODULARITY HINT: {line}")
        if pc["append_only"]:
            print(f"  counted as append-only (non-serialising): {', '.join(pc['append_only'])}")
        print(f"  {chain_line}")
    return pc


def _require_plan_decomposition_fidelity(slug: str, fm: dict, body: str,
                                         *, owner_reset: bool = False, on_decisions: bool = False, AUDIT_VERDICT_CLOSURE_OK, DECISIONS_DIR, TASKS_DIR, _die, _plan_card_set_context, _plan_card_set_fingerprint, _plan_content_hash, _plan_cut_cards, _read_yaml, _run_plan_gate_audit) -> None:
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
    # T-14626 (SPEC-0070 §3): the mechanical cut-set pre-check prints BEFORE anything else of the gate —
    # report-only; its result is returned so `cmd_plan_stage` records it on the `plan_stage_entered` row.
    precheck = _print_cut_set_precheck(_plan_cut_rows(slug, TASKS_DIR=TASKS_DIR, _plan_cut_cards=_plan_cut_cards,
                                                      _read_yaml=_read_yaml))
    # T-14457 (SPEC-1058 §3): an opted-in plan's list checks run FIRST — a list fault refuses even beside
    # a fresh fidelity verdict, and costs no audit. A plan without `prototype_ref` takes no branch here.
    opted, rows = _plan_is_prototype_opted_in(fm), []
    if opted:
        rows = _plan_cut_rows(slug, TASKS_DIR=TASKS_DIR, _plan_cut_cards=_plan_cut_cards, _read_yaml=_read_yaml)
        accept_path = DECISIONS_DIR / f"{slug}-audit.yaml"
        accept = (_read_yaml(accept_path) or {}) if accept_path.exists() else {}
        # T-14627 (SPEC-1061 §4) — arm (ii) of «fresh», over the body hash, read by the shared reader.
        faults = _plan_prototype_cut_faults(
            fm, body, rows, accept, _plan_content_hash=_plan_content_hash,
            change_check=lambda: _plan_change_check_admission(
                slug, accept, current={"content_hash": _plan_content_hash(body)},
                DECISIONS_DIR=DECISIONS_DIR, _read_yaml=_read_yaml))
        if faults:
            listed = "".join(f"  - {f}\n" for f in faults)
            _die(f"{slug}: `plan stage executing` blocked — the prototype carry cut (SPEC-1058 §3):\n{listed}"
                 f"Repair the cards: `yitc-v2 task update T-XXXX --old 'cites:' --new "
                 f"'prototype_lines: [R-1]\\ncites:'` adds an absent field, `yitc-v2 task update T-XXXX "
                 f"--prototype-ref {fm.get('prototype_ref')}` names the prototype; a stale accept takes "
                 f"`yitc-v2 plan check {slug}`. Then retry.")
    fp = _plan_card_set_fingerprint(slug, _carry=(fm, body, rows)) if opted else _plan_card_set_fingerprint(slug)
    audit_path = DECISIONS_DIR / f"{slug}-audit-gate-executing.yaml"
    av = (_read_yaml(audit_path) or {}) if audit_path.exists() else {}
    if (str(av.get("verdict") or "").upper() in AUDIT_VERDICT_CLOSURE_OK
            and av.get("card_set_fingerprint") == fp):
        return precheck   # fresh GREEN/YELLOW verdict bound to THIS exact cut — reuse, no re-audit
    # T-9755: about to RUN the fidelity audit — first diagnose the EMPTY cut member-set. An empty set
    # means no task card carries `decomposed_from == slug` (the common author mistake: cutting cards
    # without the marker — the member-set is decomposed_from-keyed, NOT cites:, SPEC-0070 §5 / T-0694).
    # Sending an empty card-set to the fidelity auditor reads as a generic fidelity RED and costs a
    # wasted audit pass (a 2-pass ceiling burn); short-circuit it here at zero audit cost with the
    # likely cause named. Placed AFTER the fresh-verdict reuse-return (not before the fingerprint): a
    # real empty cut can never hold a legit GREEN to reuse, so only the audit-RUN path needs the hint —
    # and the isolation tests that pre-record a verdict over an empty set keep their reuse-path pass.
    if not _plan_cut_cards(slug):
        # T-11091 (<project> X-0866): name a REACHABLE repair for BOTH states. The original text named
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
                         blocking=True, card_set_fp=fp,
                         extra_context=_plan_card_set_context(slug) + (_plan_prototype_cut_packet(body, rows) if opted else ""),
                         owner_reset=owner_reset, on_decisions=on_decisions)
    av = (_read_yaml(audit_path) or {}) if audit_path.exists() else {}
    if (str(av.get("verdict") or "").upper() not in AUDIT_VERDICT_CLOSURE_OK
            or av.get("card_set_fingerprint") != fp):
        _die(f"{slug}: `plan stage executing` blocked — no fresh GREEN/YELLOW decomposition-fidelity "
             f"verdict matching the current card-set fingerprint (SPEC-0070 §3/§4). Settle the cut, then "
             f"re-run the gate-executing fidelity audit.")
    return precheck


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


def _require_plan_postcheck_ready(slug: str, body: str, *, on_decisions: bool = False, _die, _plan_postcheck_exempt_specs, _plan_retire_on_proof, _plan_tasks, _postcheck_probe_block_declared, _require_plan_finalization_ready, _require_verification_artifact, _run_plan_gate_audit=None, _run_plan_finalization_pass=None) -> None:
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
    if on_decisions:
        # T-13844 (public issue #78; SPEC-0204 rule 9(e), text in SPEC-1014) — THE FINALIZATION GATE'S
        # ONE BOUNDED PASS, carried by the FSM advance the gate blocks like every other plan gate's.
        # Until this arm the flag was dropped here: `audit decide --plan <slug> --gate finalization`
        # recorded the decisions and no verb could spend them, so a plan at that ceiling could not
        # leave `executing`.
        # Two halves, both existing. (1) THE ADMISSION is the plan-gate ladder's, keyed
        # (slug, `finalization`) over the gate's own saved record `<slug>-audit-post.yaml` — it
        # refuses below the ceiling, on an undecided residual (naming it) and on every other rule-3
        # axis, with no auditor invoked and no pass spent. (2) THE PASS is the aggregate
        # `audit post --plan`, run under that admission: its record is what the readiness check below
        # reads, so a GREEN/YELLOW advances the FSM in this same call and a RED holds it.
        # Placed AFTER the tasks-done check above, so the pass is never spent on a plan whose
        # implementing tasks are still open.
        _run_plan_finalization_pass(slug, _run_plan_gate_audit(
            slug, {}, body, "post", "mandatory-blocking", blocking=True, on_decisions=True,
            gate_id="finalization", admission_only=True))
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
                if c["type"] in journal_mod.ROUTABLE_CAPTURE_TYPES and (prior is None or c["ts"] > prior)]
    if unrouted:
        sys.stderr.write(
            f"WARN: {slug} realizing with {len(unrouted)} un-routed deviation_captured event(s) since "
            f"the last triage watermark ({prior or 'bootstrap — journal start'}) — route or accept. "
            f"`realized` is the plan's postcheck retrospective at corpus altitude; routing the captured "
            f"outputs first is the recommended discipline (`yitc-v2 triage run` to see the routes: "
            f"errors/E-XXXX · spec-amending task · spec edit · ideas/ · MEMORY.md — SPEC-0034 routing "
            f"table; then `yitc-v2 triage run --complete`). Transition PROCEEDS (non-blocking advisory, "
            f"T-0644 / Option B; the un-routed count is reported, not gated).\n")


def _plan_live_state(fm: dict, slug: str, _retire_on_proof_unresolved) -> list:
    """T-12845 — the live facts an automated age-sweep must read before `cancelled` ends a plan
    (SPEC-0034 §Terminals): the plan is in `postcheck` (a soak is running), or a retire-on-proof task
    (a linked task with a `return_trigger`) is still unresolved. Returns human-readable reasons; empty
    = nothing live. The 2026-09-13T03 sweep cancelled 22 postcheck soaks on «older than 2 days»."""
    out = []
    if str(fm.get("status") or "") == "postcheck":
        out.append("status is postcheck (a soak is running)")
    if _retire_on_proof_unresolved is not None:
        pending = _retire_on_proof_unresolved(slug)
        if pending:
            out.append("live return trigger on " + ", ".join(f"{t} ({s})" for t, s in pending))
    return out


def cmd_plan_stage(args: argparse.Namespace, *, DECISIONS_DIR, PLANS_DIR, REPO_ROOT, PLAN_STAGE_SEQUENCE, PLAN_STATUSES, _append_event, _commit_worktree, _die, _emit_plan_stage_entered, _find_decision_yaml, _find_task_yaml, _in_writing_worktree, _load_draft, _plan_accept_core, _plan_close_core, _plan_draft_finalized_fresh, _plan_next_stage, _plan_stage_bundle_specs, _postcheck_probe_block_declared, _print_plan_stage_delivery, _read_yaml, _require_plan_decomposition_fidelity, _require_plan_decomposition_ready, _require_plan_postcheck_ready, _require_reads, _require_verification_artifact, _require_writing_worktree, _run_plan_gate_audit, _split_into, _write_draft, _withdraw_plan_draft_specs, _is_consumer_build=None, _retire_on_proof_unresolved=None, AUDIT_VERDICT_CLOSURE_OK=("GREEN", "YELLOW"), _plan_card_set_fingerprint=None, _run_plan_checks=None) -> None:
    """`plan stage <NAME> <slug>` (T-0316) — the authoritative gated plan-lifecycle transition verb,
    mirroring `task stage` on ONE `status` field. On each call it (a) GATES the target stage's entry
    (= the prior stage's completion), (b) runs the stage's side-effects, (c) writes status=<NAME>,
    (d) DELIVERS the stage bundle (`plan-stage-entry:<NAME>` specs) + EMITS `plan_stage_entered`. It
    ABSORBS `plan accept` / `plan close --resolution` (their side-effects are branches here). A WRITE
    → runs in a writing worktree. Linear FSM (one step along PLAN_STAGE_SEQUENCE); the wont-do terminals
    partial/rejected/cancelled are reachable from any active stage."""
    # T-11249 (<project> X-0970) — SAY WHICH CHECKOUT THIS VERDICT RESTS ON, before anything else.
    # Diagnostic only, on stderr: every stdout contract stays byte-identical, and it sits beside
    # the sibling `# audit-loop ceiling:` notes. UNCONDITIONAL by design — the cost being removed
    # is the SILENCE, and a line that appears only when the engine already suspects a mismatch is
    # the same silence with extra steps. FIRST statement in the body, ahead of
    # `_require_writing_worktree()`: a wrong-tree invocation is exactly what that guard refuses,
    # so its refusal needs the tree named too.
    print(observe.checkout_provenance_line(REPO_ROOT, verb="plan stage"), file=sys.stderr)
    _require_writing_worktree()
    name = (args.name or "").strip()
    _owner_reset = bool(getattr(args, "owner_reset", False))   # T-9286 — RETIRED at the gate (T-12335)
    # T-12335 (SPEC-0204 rule 3, plan-gate arm) — the ONE bounded pass past a plan-gate ceiling,
    # governed by the Controller's recorded `ceiling_decision` rows. Carried by THIS verb and not by
    # `audit pre --plan --gate` because `_run_plan_gate_audit` is invoked from here ALONE and it is the
    # FSM ADVANCE the gate blocks: the ONE pass and the advance become the SAME act, so the pass cannot
    # be spent without the FSM moving, and there is no second door at which a plan-gate ceiling can be
    # argued. Additive-optional getattr shape, like `--owner-reset` above.
    # T-13844 — the `postcheck` branch carries it too, for the `finalization` gate: the admission is
    # the same ladder, and the pass it admits is the aggregate `audit post --plan` (see
    # `_require_plan_postcheck_ready`).
    _on_decisions = bool(getattr(args, "on_decisions", False))
    if _on_decisions and _owner_reset:
        _die("plan stage: --on-decisions and --owner-reset are not combinable — each was a DIFFERENT "
             "basis for the ONE pass past a plan-gate ceiling, and `--owner-reset` is RETIRED "
             "(SPEC-0204 rule 6, plan-gate arm). Drop it.")
    _by_record = bool(getattr(args, "by_record", False))       # T-9369 — realized-by-record terminal
    # T-14563 (SPEC-0070 §4) — re-run the decomposition-fidelity gate for a plan ALREADY executing whose
    # cut changed (a card filed into it after the freeze). Same gate, same record, same pass rules.
    _recut = bool(getattr(args, "recut", False))
    if name not in PLAN_STATUSES:
        _die(f"plan stage: unknown stage {name!r} — must be one of {list(PLAN_STATUSES)} (the plan FSM).")
    path, fm, body = _load_draft(args.slug, dirs=(PLANS_DIR,))
    slug = fm.get("id") or args.slug
    cur = fm.get("status") or "draft"
    if cur in PLAN_TERMINAL:
        _die(f"{slug} status={cur!r} is terminal — no further `plan stage` transition.")
    # --- FSM edge validation ---
    if _recut:
        if not (name == "executing" and cur == "executing"):
            _die(f"{slug}: `--recut` re-runs the decomposition-fidelity gate of a plan ALREADY in "
                 f"`executing` (SPEC-0070 §4) — it takes `yitc-v2 plan stage executing {slug} --recut` on an "
                 f"executing plan only; this plan is {cur!r} and the target is {name!r}.")
    elif name in PLAN_NONLINEAR_TERMINALS:
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
    # T-14672 (SPEC-0034 §Project-declared plan check) — the project's declared check, phase = the stage
    # being ENTERED (the gate at which the prior stage's work is complete), after the FSM edge check and
    # BEFORE every per-target gate: no auditor call, no stage write and — for `--recut` — no read of the
    # recorded verdict happens before it. trial / postcheck / realized / the terminals are not checkpoints.
    # T-14673 — `trial` IS a plan checkpoint for the catch-up of late plan-stage rules (its gate is the
    # gate-trial audit); the host's pre-pass runs no project check at a phase outside PLAN_CHECK_PHASES.
    if _run_plan_checks is not None and name in ("specs", "trial", "accepted", "decomposition", "executing"):
        _run_plan_checks(path, name, slug,
                         verb=f"plan stage {name} {slug}" + (" --recut" if _recut else ""))
    # --- per-target gate + side-effects ---
    wrote = False
    withdrawn_specs = []   # T-13857 — [(spec id, path, text before)] a `cancelled`/`rejected` transition withdrew
    legacy = None          # (event_type, data) — the legacy event the absorbed verb used to emit
    extra = {}             # extra fields folded into the plan_stage_entered event
    msg = ""
    _units_declared = 0    # T-14651 — units in `## Units`, read at the decomposition entry only
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
                                            blocking=True, owner_reset=_owner_reset,
                                            on_decisions=_on_decisions)
        msg = (f"(draft specs being composed + checked; gate-specs MANDATORY-BLOCKING gate passed: "
               f"{gate_verdict} — SPEC-0083)")
    elif name == "trial":
        # T-0349 — the P3 specs→trial entry-gate template (SPEC-0036 §Gate policy:
        # MANDATORY-BLOCKING — RED/ABORT holds the transition; the 2-pass ceiling applies).
        _run_plan_gate_audit(slug, fm, body, "gate-trial", "mandatory-blocking", blocking=True,
                             owner_reset=_owner_reset, on_decisions=_on_decisions)
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
        # T-14627 (SPEC-1061 §3) — the plan_stage_entered row names the arm and the record it admitted on.
        extra = {"specs_born": specs_born, "admitted_on": ev.get("admitted_on")}
        msg = (f"+ birthed {len(specs_born)} draft spec(s)→proposed: {', '.join(specs_born)}"
               if specs_born else "(no draft specs to birth)")
    elif name == "decomposition":
        # accepted → decomposition (SPEC-0070 §2): the RELOCATED executing-readiness gate (fresh plan
        # check + impl_plan + specs proposed; the LARGE big-plan check rides on the fresh-check
        # requirement). WORK = cut the plan into task cards. The cut-rules bundle (SPEC-0046 plan-cut
        # face + SPEC-0070) is delivered by `_emit_plan_stage_entered` below.
        _require_plan_decomposition_ready(slug, fm, body)
        msg = "(cut into task cards — SPEC-0046: one coherent change-set per card, split only on its grounds, order via requires:)"
        # T-14651 (SPEC-0070 §2 Work) — name the unit-skeletons view at the cut, when the plan declares
        # Units. Report-only: a section the parser cannot render means no cue, never a refusal.
        try:
            _units_declared = len(parse_plan_units(body))
        except PlanUnitsError:
            _units_declared = 0
    elif name == "executing":
        # decomposition → executing (SPEC-0070 §3/§8): (1) the cut-rules read-gate — you cannot leave the
        # cut for build unless the decomposition bundle was fetched this session (graceful-empty until the
        # binding is non-empty); (2) the mandatory decomposition-fidelity gate over the CARD SET. WORK =
        # the tasks run their own 9 stages (pure build).
        if _recut:
            # T-14563 — refuse when nothing changed: a GREEN/YELLOW verdict on record already binds the
            # LIVE cut, so a re-run would spend an auditor pass judging the same card set (no pass, no
            # auditor). Otherwise the SAME read-gate + gate call below re-audits and re-fingerprints.
            _ap = DECISIONS_DIR / f"{slug}-audit-gate-executing.yaml"
            _av = (_read_yaml(_ap) or {}) if _ap.exists() else {}
            _old_fp = _av.get("card_set_fingerprint")
            _live_fp = _plan_card_set_fingerprint(slug)
            if (str(_av.get("verdict") or "").upper() in AUDIT_VERDICT_CLOSURE_OK
                    and _old_fp == _live_fp):
                _die(f"{slug}: `plan stage executing --recut` refused — nothing changed: the recorded "
                     f"decomposition-fidelity verdict ({_av.get('verdict')}) already binds the live cut "
                     f"(card_set_fingerprint {_live_fp}). No auditor invoked, no pass spent. File the "
                     f"new card with `yitc-v2 task file --decomposed-from {slug}` first (SPEC-0070 §4).")
            extra.update({"recut": True, "card_set_fingerprint_from": _old_fp})
        _require_reads("stage", {"axis": "plan", "stage": "decomposition",
                                 "verb": "plan stage executing",
                                 "action": ("executing re-cut fidelity re-run" if _recut
                                            else "decomposition->executing transition")})
        _precheck = _require_plan_decomposition_fidelity(slug, fm, body, owner_reset=_owner_reset,
                                                         on_decisions=_on_decisions)
        if isinstance(_precheck, dict):   # T-14626 — the cut-set pre-check, recorded on the stage row
            extra["cut_set_precheck"] = _precheck
        msg = ("(re-cut: the changed card set is fidelity-audited and re-fingerprinted; the plan stays "
               "executing)" if _recut else
               "(tasks run their own 9 stages — pure build; the cut is fidelity-audited)")
    elif name == "postcheck":
        _require_plan_postcheck_ready(slug, body, on_decisions=_on_decisions)
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
        live = _plan_live_state(fm, slug, _retire_on_proof_unresolved) if name == "cancelled" else []
        despite = bool(getattr(args, "despite_live_state", False))
        if live and not despite:
            _die(f"plan stage cancelled {slug}: REFUSED — the plan is still LIVE, so age is not a reason to "
                 f"end it (SPEC-0034 §Terminals, T-12845): " + "; ".join(live) + ". Let the soak/trigger "
                 f"resolve, or pass --despite-live-state to cancel anyway (journaled).")
        # T-13857 (SPEC-0005 §4) — a plan that ends without accepting its drafts ends them too: every
        # spec of this plan still `draft` becomes `withdrawn` (it never governed). The specs are
        # written BEFORE the plan's own terminal write, and both are one unit: a failure in either
        # puts every file the unit started on back (the plan file too), so a failed attempt leaves
        # the plan non-terminal with its drafts still drafts — re-runnable (a terminal plan takes
        # no further `plan stage`), with nothing for the next attempt to find already withdrawn. The row (`specs_withdrawn` — the
        # `specs_born` of the accept, mirrored) and the terminal-record commit below carry exactly
        # the specs THIS call flipped.
        def _write_terminal():
            fm["status"] = name
            fm["rejected_reason" if name == "rejected" else "cancelled_reason"] = reason
            _write_draft(path, fm, body)

        withdrawn_specs = _withdraw_plan_draft_specs(slug, then=_write_terminal, then_path=path)
        if name == "rejected":
            legacy = ("draft_rejected", {"slug": slug, "reason": reason})
        extra = {"reason": reason, "specs_withdrawn": [sid for sid, _p, _raw in withdrawn_specs]}
        if withdrawn_specs:
            msg = (f"+ withdrew {len(withdrawn_specs)} draft spec(s) of this plan (draft→withdrawn, "
                   f"SPEC-0005 §4): {', '.join(sid for sid, _p, _raw in withdrawn_specs)}")
        if name == "cancelled" and live:
            extra["despite_live_state"] = live
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
        # T-13857 — the draft specs THIS transition withdrew are part of its own record; no other
        # spec file is staged (one the plan withdrew earlier may carry someone's unrelated edit).
        pathspecs.extend(str(sp.relative_to(REPO_ROOT)) for _sid, sp, _raw in withdrawn_specs)
        _, short = _commit_worktree(
            rel_plan,
            f"chore({slug}): plan {name} record — status:{name} (+ reverse-links)",
            pathspecs=pathspecs)
        _append_event("commit_landed", None, {"slug": slug, "commit": short, "kind": f"plan-{name}"})
        print(f"  plan {name} record committed {short} — worktree land-clean (T-10052); "
              f"`yitc-v2 land` (from main) to integrate")
    print(f"{slug} -> {name} (plan stage; status recorded) {msg}".rstrip())
    _print_plan_stage_delivery(name, delivered,   # shared delivery print (audit-pre F0)
                               is_consumer=bool(_is_consumer_build and _is_consumer_build()))
    _print_plan_gate_disclosure(_disclosure)      # T-12027 report-only gate disclosure
    if name == "decomposition" and _units_declared:
        print(f"cut aid: this plan declares {_units_declared} unit(s) in `## Units` — "
              f"`yitc-v2 plan show {slug} --unit-skeletons` prints their card skeletons as a "
              f"`task file --from-stdin` batch (SPEC-0043 item 10).")
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
    # T-12404 — ORDER cue at `accepted` entry: the accept-gate freshness `content_hash` covers the plan
    # BODY, and the realization-exit block IS a body section — so a body edit made NOW re-stales the
    # check the `decomposition` gate re-reads, buying a full re-`plan check` for no design change.
    # POINTER ONLY (the T-0333 rule): the ORDER is stated here as a cue; its content + rationale stay
    # single-sourced in SPEC-0034 §accepted Work-ORDER — no work-item map in the verb.
    if name == "accepted":
        print("order (SPEC-0034 §accepted Work-ORDER): compose `implementation_plan` + the "
              "realization-exit block FIRST, then `plan check`, then `plan stage accepted`, then "
              "`plan stage decomposition` — the freshness basis is `content_hash (plan body)`, so a "
              "BODY edit from here re-stales the check (a frontmatter-field edit does not), and a "
              "fresh `plan check` does NOT preserve mode-b `absorbed:`.")
    # T-0623 — POST-SPECS FORK: at the decision point after the draft specs are composed, surface
    # BOTH branches so a trial-ELIGIBLE plan is not silently routed past `trial` straight to
    # `accepted` (the deviation trial-eligible-plan-routed-past-trial-verb-hints-omit-trial). Both
    # branches named; eligibility is OWNER judgement, no detector (SPEC-0035 rules 2/5/8, non-goal #7).
    if name == "specs":
        print(f"next (post-specs FORK — SPEC-0035): is this plan trial-eligible (mechanism/behavioral "
              f"— births a spec/verb/flow AND convergence can't honestly come from text-audit alone)? "
              f"YES → `yitc-v2 plan stage trial {slug}` (controlled real-data soak); NO (non-eligible "
              f"prose/docs, the skip) → `yitc-v2 plan check {slug}` then `yitc-v2 plan stage accepted "
              f"{slug}`. Your judgement — no detector; "
              f"{_plan_pre_gate_reread_cue(is_consumer=bool(_is_consumer_build and _is_consumer_build()))}.")
        _seam = _plan_seam_default_line(name, ("trial", "accepted"))
        if _seam:
            print(_seam)
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
                  f"(the FSM successor of {name}; LIFECYCLE §Plan lifecycle); "
                  f"{_plan_pre_gate_reread_cue(is_consumer=bool(_is_consumer_build and _is_consumer_build()))}.")
            _seam = _plan_seam_default_line(name, (nxt,))
            if _seam:
                print(_seam)


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


# ── T-14456 (SPEC-1058 §1-§3) — the plan-side prototype carry registry ────────────────────────────
# OPT-IN: every helper below is reached only when the plan frontmatter names `prototype_ref`; a plan
# without it never enters this block, so its check prompt, verdict record, accept path and freshness
# basis stay byte-identical (SPEC-1058 §1).
PROTOTYPE_REGISTRY_SECTION = "Prototype registry"
_PROTO_ITEM_ID_RE = re.compile(r"^R-[1-9][0-9]*$")
_PROTO_KINDS = ("added", "changed", "removed", "supporting")
_PROTO_DISPOSITIONS = ("carry", "not-carried")
# T-14622 (SPEC-1058 §2) — the third value: the item is carried by an EARLIER plan of the same lineage.
_PROTO_CARRIED_BY_RE = re.compile(r"^carried-by-plan\s+(?P<slug>[a-z0-9][a-z0-9-]*)$")
_PROTO_LOCATOR_RE = re.compile(r"^(?P<path>.+):(?P<a>[1-9][0-9]*)(?:-(?P<b>[1-9][0-9]*))?$")
_PROTO_OWNER_READ_RE = re.compile(r"^owner_read:\s*(?P<ref>\S+)\s*$")
_PROTO_OWNER_REF_RE = re.compile(r"^events\.jsonl#ts=\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_PROTO_FENCE_RE = re.compile(r"^```(?:ya?ml)?\s*$")


def _proto_carried_by(it) -> "str | None":
    """The earlier plan's slug of a `carried-by-plan <slug>` item, else None (SPEC-1058 §2)."""
    d = it.get("disposition") if isinstance(it, dict) else None
    m = _PROTO_CARRIED_BY_RE.match(d.strip()) if isinstance(d, str) else None
    return m.group("slug") if m else None


def _plan_is_prototype_opted_in(fm) -> bool:
    return isinstance(fm, dict) and bool(str(fm.get("prototype_ref") or "").strip())


def _plan_prototype_registry_section(body: str) -> "str | None":
    """The text of the `## Prototype registry` section (heading excluded), or None when absent."""
    lines, out, inside = body.splitlines(), [], False
    for ln in lines:
        if ln.startswith("## "):
            if inside:
                break
            inside = ln[3:].strip() == PROTOTYPE_REGISTRY_SECTION
            continue
        if inside:
            out.append(ln)
    return "\n".join(out) if inside or out else None


def _plan_prototype_registry(body: str) -> "tuple[str | None, list, str | None]":
    """SPEC-1058 §2 — read the registry: (owner_read, items, fault). `fault` names the FIRST defect;
    when it is set the other two values are not to be trusted. The fenced list is read by the ONE
    YAML parser (`state.load_str`)."""
    sec = _plan_prototype_registry_section(body)
    if sec is None:
        return None, [], f"the plan has no `## {PROTOTYPE_REGISTRY_SECTION}` section"
    lines = sec.splitlines()
    start = next((i for i, ln in enumerate(lines) if _PROTO_FENCE_RE.match(ln.strip())), None)
    if start is None:
        return None, [], f"the `## {PROTOTYPE_REGISTRY_SECTION}` section carries no fenced yaml list"
    end = next((j for j in range(start + 1, len(lines)) if lines[j].strip() == "```"), None)
    if end is None:
        return None, [], f"the fenced yaml list in `## {PROTOTYPE_REGISTRY_SECTION}` is not closed"
    owner_read = None
    for ln in lines[:start]:
        m = _PROTO_OWNER_READ_RE.match(ln.strip())
        if m:
            owner_read = m.group("ref")
            break
    if owner_read is None:
        return None, [], ("the registry has no owner read-back row — the section must open with "
                          "`owner_read: events.jsonl#ts=<ISO>`")
    if not _PROTO_OWNER_REF_RE.match(owner_read):
        return None, [], f"owner_read `{owner_read}` is not an `events.jsonl#ts=<ISO>` locator"
    try:
        items = state.load_str("\n".join(lines[start + 1:end]))
    except Exception as e:   # noqa: BLE001 — any parser failure is the named fault, never a traceback
        return owner_read, [], f"the registry list does not parse as YAML: {str(e).splitlines()[0]}"
    if not isinstance(items, list) or not items:
        return owner_read, [], "the registry is not a non-empty YAML list of items"
    seen = set()
    for n, it in enumerate(items, 1):
        if not isinstance(it, dict):
            return owner_read, [], f"registry entry #{n} is not a mapping"
        iid = str(it.get("id") or "")
        where = f"registry item {iid or f'#{n}'}"
        if not _PROTO_ITEM_ID_RE.match(iid):
            return owner_read, [], f"{where}: id must be `R-<n>`"
        if iid in seen:
            return owner_read, [], f"{where}: duplicate id"
        seen.add(iid)
        if it.get("kind") not in _PROTO_KINDS:
            return owner_read, [], f"{where}: kind must be one of {', '.join(_PROTO_KINDS)}"
        for key in ("surface", "what"):
            if not isinstance(it.get(key), str) or not it[key].strip():
                return owner_read, [], f"{where}: `{key}` must be a non-empty string"
        locs = it.get("locators")
        if not isinstance(locs, list) or not locs:
            return owner_read, [], f"{where}: `locators` must be a non-empty list of path:line"
        for loc in locs:
            if not isinstance(loc, str) or not _PROTO_LOCATOR_RE.match(loc.strip()):
                return owner_read, [], f"{where}: locator `{loc}` is not `path:line` (or `path:a-b`)"
        if it.get("disposition") not in _PROTO_DISPOSITIONS and _proto_carried_by(it) is None:
            return owner_read, [], (f"{where}: disposition must be one of {', '.join(_PROTO_DISPOSITIONS)}"
                                    ", carried-by-plan <slug>")
        orow = it.get("owner_row")
        if orow is not None and (not isinstance(orow, str) or not orow.strip()):
            return owner_read, [], f"{where}: `owner_row` must be a non-empty locator when present"
        if it["disposition"] == "not-carried" and orow is None:
            return owner_read, [], f"{where}: a `not-carried` item must cite its `owner_row`"
        if "owner_risk" in it:   # T-14533 — the owner-risk marker IS its own owner row (SPEC-1058 §2)
            risk = it.get("owner_risk")
            if not isinstance(risk, str) or not _PROTO_OWNER_REF_RE.match(risk.strip()):
                return owner_read, [], (f"{where}: `owner_risk` must be the owner's row, an "
                                        f"`events.jsonl#ts=<ISO>` locator")
            if it["disposition"] != "carry":
                return owner_read, [], f"{where}: `owner_risk` marks a `carry` item only"
    return owner_read, items, None


def _plan_prototype_owner_risk_rows(items: list, events_path) -> dict:
    """T-14533 (SPEC-1058 §2) — resolve every owner-risk marker: {item id: {"loc", "row_text"}}, where
    `row_text` is the owner's verbatim words of the `owner_directive` row at the locator's ts (redacted
    at write, SPEC-0163 §4e) or None when no such row exists. The kernel checks only that the row is
    real; whether its words accept THIS item's risk is the accept check's judgement. Reads the journal
    once, through the segment-aware reader, and only when some item is marked."""
    marked = [(str(it["id"]), str(it["owner_risk"]).strip()) for it in items
              if isinstance(it, dict) and it.get("owner_risk")]
    if not marked:
        return {}
    texts: dict = {}
    tss = sorted(loc.split("#ts=", 1)[1] for _iid, loc in marked)
    if events_path is not None and Path(events_path).exists():
        # the owner-words view's own segment-aware reader (SPEC-0190 rule 4), bounded to the markers' span
        for r in _ow_period_rows(events_path, tss[0], tss[-1]):
            if r.get("type") != "owner_directive":
                continue
            d = r.get("data") if isinstance(r.get("data"), dict) else {}
            words = str(d.get("owner_text") or d.get("text") or "").strip()
            texts.setdefault(_ow_ts(r.get("ts")), words or "(the owner row carries no words)")
    return {iid: {"loc": loc, "row_text": texts.get(loc.split("#ts=", 1)[1])} for iid, loc in marked}


def _plan_prototype_git(repo_root, *args) -> "tuple[str | None, str | None]":
    from lib import spike_identity as si   # noqa: PLC0415 — the one git runner
    try:
        return si._git(repo_root, *args).strip(), None
    except RuntimeError as e:
        return None, str(e)


# ── SPEC-1058 §2 — the owner-words reconciliation before the read-back (T-14520) ─────────────────
# A read-only VIEW over the journal and the transcripts of the sessions that worked the spike. It
# never writes the plan or the registry and never refuses: the matching is a CANDIDATE shown to the
# owner (SPEC-0142 §2 — AI judgement separable and non-gating).
_OW_ROW_TYPES = frozenset({"worktree_created", "spike_declared_late", "session_started",
                           "owner_directive", "trial_run"})
_OW_STEM_RE = re.compile(r"\w{4,}", re.UNICODE)
_OW_STOP = frozenset({"this", "that", "with", "from", "have", "will", "into", "only", "also", "then",
                      "there", "here", "what", "when", "which", "where", "should", "would", "could",
                      "make", "just", "like", "need", "want", "keep", "that's", "этот", "чтобы",
                      "будет", "можно", "нужно", "тоже", "только", "когда", "сейчас", "давай",
                      "пока", "потом", "здесь", "там", "надо", "есть", "просто", "очень"})
_OW_REVERSAL_RE = re.compile(
    r"\b(?:not|no|don't|dont|instead|cancel\w*|revert\w*|undo|actually|rather|drop)\b"
    r"|(?:^|\s)(?:не|нет)(?=\s|$|[,.!?])|отмен|вместо|передума|вс[её]-таки|убра|убер",
    re.IGNORECASE | re.UNICODE)


def _ow_stems(text: str) -> set:
    return {w.lower()[:5] for w in _OW_STEM_RE.findall(text or "") if w.lower() not in _OW_STOP}


def _ow_ts(raw) -> str:
    """A row/entry timestamp converted to UTC `YYYY-MM-DDTHH:MM:SSZ` ('' when absent or unreadable).
    An offset is honoured (`+02:00` is converted, never dropped); a value with no offset reads as UTC."""
    import datetime as _dt   # noqa: PLC0415
    s = str(raw or "").strip()
    if not s:
        return ""
    try:
        t = _dt.datetime.fromisoformat(s[:-1] + "+00:00" if s.endswith(("Z", "z")) else s)
    except ValueError:
        return ""
    if t.tzinfo is None:
        t = t.replace(tzinfo=_dt.timezone.utc)
    return t.astimezone(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ow_registry_items(body: str) -> "tuple[list, str | None]":
    """The registry items read LENIENTLY — the step runs BEFORE the owner's read-back, so no
    `owner_read` row is required. (items, fault); a fault leaves every word unmapped."""
    sec = _plan_prototype_registry_section(body)
    if sec is None:
        return [], f"the plan has no `## {PROTOTYPE_REGISTRY_SECTION}` section"
    lines = sec.splitlines()
    start = next((i for i, ln in enumerate(lines) if _PROTO_FENCE_RE.match(ln.strip())), None)
    end = (next((j for j in range(start + 1, len(lines)) if lines[j].strip() == "```"), None)
           if start is not None else None)
    if start is None or end is None:
        return [], f"the `## {PROTOTYPE_REGISTRY_SECTION}` section carries no closed fenced yaml list"
    try:
        items = state.load_str("\n".join(lines[start + 1:end]))
    except Exception as e:   # noqa: BLE001 — a parse failure is named, never a traceback
        return [], f"the registry list does not parse as YAML: {str(e).splitlines()[0]}"
    if not isinstance(items, list):
        return [], "the registry is not a YAML list"
    return [it for it in items if isinstance(it, dict) and it.get("id")], None


def _ow_plan_rules(body: str) -> list:
    """The plan's own rules as mapping targets: every bullet, numbered line or paragraph line of the
    body OUTSIDE the `## Prototype registry` section and outside fenced blocks."""
    rules, inside_reg, fenced = [], False, False
    for ln in body.splitlines():
        s = ln.strip()
        if ln.startswith("## "):
            inside_reg = ln[3:].strip() == PROTOTYPE_REGISTRY_SECTION
            continue
        if s.startswith("```"):
            fenced = not fenced
            continue
        if inside_reg or fenced or not s or s.startswith("#"):
            continue
        rules.append(re.sub(r"^(?:[-*]|\d+[.)])\s+", "", s))
    return rules


def _ow_annotation_commit(repo_root, tag) -> "tuple[dict | None, str | None, str]":
    """(annotation, tag commit, tagger date) of an annotated spike tag; (None, None, '') if unreadable."""
    from lib import spike_identity as si   # noqa: PLC0415
    ann = si._tag_annotation(repo_root, tag)
    commit = si._git(repo_root, "rev-parse", "--verify", "--quiet", f"refs/tags/{tag}^{{commit}}",
                     check=False).strip()
    date = si._git(repo_root, "for-each-ref", "--format=%(taggerdate:iso-strict)", f"refs/tags/{tag}",
                   check=False).strip()
    if date:
        try:
            import datetime as _dt   # noqa: PLC0415
            date = _dt.datetime.fromisoformat(date).astimezone(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            date = ""
    return ann, (commit or None), date


def _ow_transcript_turns(path) -> "tuple[list, str | None]":
    """The owner turns of one transcript file: [(ts, text, uuid)], or ([], why) when unreadable."""
    from lib import textutil   # noqa: PLC0415
    out = []
    try:
        fh = open(path, encoding="utf-8", errors="replace")
    except OSError as e:
        return [], f"unreadable: {e.strerror or e}"
    with fh:
        for line in fh:
            try:
                e = json.loads(line)
            except (ValueError, TypeError):
                continue                     # a corrupt line is skipped, the rest still read
            if not isinstance(e, dict):
                continue
            turn = journal_mod.conversation_turn(e, _extract_text=textutil.extract_text)
            if turn and turn[0] == "owner" and turn[1]:
                out.append((_ow_ts(e.get("timestamp")), turn[1], turn[2]))
    return out, None


def _ow_period_rows(events_path, start: str, end: str) -> list:
    """The spike-life rows of the owner-words view: every `_OW_ROW_TYPES` row of the WHOLE logical
    journal (the segment-aware fold, SPEC-0190 rule 4) with start <= ts <= end (an empty `end` = no
    upper bound), sorted by (ts, type, session_ref) so neither segmentation nor physical order changes
    the answer."""
    def _key(r):
        return (_ow_ts(r.get("ts")), str(r.get("type") or ""), str(r.get("session_ref") or ""),
                json.dumps(r, sort_keys=True, default=str))
    out = []
    for r in journal_mod.segment_rows(events_path, types=_OW_ROW_TYPES, min_ts=start or None):
        ts = _ow_ts(r.get("ts"))
        if ts and ts >= start and (not end or ts <= end):
            out.append(r)
    return sorted(out, key=_key)


def _ow_row_names(d: dict, names) -> bool:
    """An owner_directive row's data names one of `names` (the plan slug, its prototype, its branch) in
    its text, owner_text or cards — the one plan-naming match of the owner-words view (SPEC-1058 §2),
    shared with the pre-pass line `plan_owner_rows_outside` (T-14618)."""
    blob = " ".join([str(d.get("text") or ""), str(d.get("owner_text") or ""),
                     " ".join(str(c) for c in (d.get("cards") or []))])
    return any(n and n in blob for n in names)


def plan_owner_rows_outside(slug: str, fm: dict, body: str, *, events_path) -> list:
    """T-14618 (SPEC-0046 §C) — REPORT-ONLY pre-pass line: every owner_directive row that names the plan
    or its prototype (`prototype_ref`) and whose ts the plan body does not cite. Reads the journal
    through the owner-words view's own reader (`_ow_period_rows`, segment-aware) — no new store; an
    absent journal reads as no rows. Never refuses."""
    names = {n for n in (str(slug or "").strip(), str(fm.get("id") or "").strip(),
                         str(fm.get("prototype_ref") or "").strip()) if n}
    if not names or events_path is None:
        return []
    findings, seen = [], set()
    for r in _ow_period_rows(events_path, "", ""):
        if r.get("type") != "owner_directive":
            continue
        d = r.get("data") if isinstance(r.get("data"), dict) else {}
        if not _ow_row_names(d, names):
            continue
        raw, ts = str(r.get("ts") or ""), _ow_ts(r.get("ts"))
        if (raw and raw in body) or (ts and ts in body):
            continue
        ident = json.dumps(r, sort_keys=True, default=str)   # the row itself — never its ts alone
        if ident in seen:
            continue
        seen.add(ident)
        words = journal_mod.redact_owner_text(str(d.get("owner_text") or d.get("text") or "").strip())
        findings.append({
            "severity": "low", "source": "structural",
            "what": f"owner answer outside the plan: owner_directive events.jsonl#ts={raw or '(no ts)'} "
                    f"names the plan or its prototype and the plan body does not cite it"
                    + (f" — «{words[:120]}»" if words else ""),
            "where": "plan body (owner rows of the journal)",
            "fix": "carry the answer into the plan and cite the row (`events.jsonl#ts=<ts>`), or cite it "
                   "as considered and not carried (SPEC-0046 §C, report-only)"})
    return findings


def owner_words_reconciliation(repo_root, slug: str, fm: dict, body: str, *, events_path,
                               resolve_transcript, earlier_tags=()) -> dict:
    """SPEC-1058 §2 — the read-only owner-words reconciliation for a plan opted in to the carry
    registry. `resolve_transcript(ref) -> [Path]` is the kernel's existing transcript resolution (the
    cli seam injects it). Returns a dict the renderer prints; writes nothing, raises nothing on an
    unmapped word or a missing file."""
    from lib import spike_identity as si   # noqa: PLC0415
    rec = {"slug": slug, "opted_in": _plan_is_prototype_opted_in(fm), "faults": [], "rounds": [],
           "unfollowed": [],
           "start": "", "end": "", "refs": [], "read": [], "no_file": [], "words": [],
           "mapped": [], "unmapped": [], "reversals": [], "trials": []}
    if not rec["opted_in"]:
        return rec
    tag = str(fm.get("prototype_ref") or "").strip()
    rec["prototype_ref"] = tag
    ann, tip, end = _ow_annotation_commit(repo_root, tag)
    if not ann or not ann.get("declared_row_ts") or not tip:
        rec["faults"].append(f"`{tag}` has no readable declaring-row annotation — no spike life is "
                             "derived and no session is read (nothing is guessed)")
        return rec
    rounds = [(ann.get("declared_row_ts", ""), ann.get("declared_session_ref", ""),
               ann.get("branch", ""), tag)]
    # T-14538: a declaring row records no tag it was copied from, so an earlier round the owner NAMES
    # (`--earlier-tag`) is read as a round of the same life: its declaring session, its branch, and the
    # life from its declaring row. Only named tags are followed; a tag with no readable declaring-row
    # annotation is a fault, never guessed.
    named = []
    for et in dict.fromkeys(str(t).strip() for t in (earlier_tags or ()) if str(t).strip()):
        if et == tag:
            continue
        eann, ecommit, _ = _ow_annotation_commit(repo_root, et)
        if not eann or not eann.get("declared_row_ts") or not ecommit:
            rec["faults"].append(f"--earlier-tag `{et}` has no readable declaring-row annotation — "
                                 "not read (nothing is guessed)")
            continue
        named.append(et)
        rounds.append((eann.get("declared_row_ts", ""), eann.get("declared_session_ref", ""),
                       eann.get("branch", ""), et))
    # Only the prototype's OWN declaring row is followed: no journal row links one spike round to the
    # next, and commit ancestry cannot tell a continued round from a spike merged into the branch. An
    # ancestral spike tag absent from `main` is therefore LISTED for the owner, never read.
    rec["unfollowed"] = []
    for other in si._git(repo_root, "for-each-ref", "--format=%(refname:short)", "refs/tags/spike/",
                         check=False).split():
        if other == tag or other in named:
            continue
        _oann, ocommit, _ = _ow_annotation_commit(repo_root, other)
        if not ocommit:
            continue
        on_tip = si._git(repo_root, "merge-base", ocommit, tip, check=False).strip() == ocommit
        on_main = si._git(repo_root, "merge-base", ocommit, "main", check=False).strip() == ocommit
        if on_tip and not on_main:
            rec["unfollowed"].append(other)
    rec["rounds"] = sorted(rounds)
    start = _ow_ts(min(r[0] for r in rounds))
    rec["start"], rec["end"] = start, end
    branches = {r[2] for r in rounds if r[2]}
    names = {slug, tag} | branches

    def _in_life(ts):
        return bool(ts) and ts >= start and (not end or ts <= end)

    rows = _ow_period_rows(events_path, start, end)
    refs = [r[1] for r in rec["rounds"] if r[1]]
    for r in rows:
        d = r.get("data") if isinstance(r.get("data"), dict) else {}
        ref = str(r.get("session_ref") or "")
        if not ref:
            continue
        if r.get("type") == "trial_run" and str(d.get("plan") or "") == slug:
            refs.append(ref)
        elif r.get("type") == "owner_directive":
            if _ow_row_names(d, names):
                refs.append(ref)
    rec["refs"] = list(dict.fromkeys(refs))
    part = set(rec["refs"])
    words, seen_uuid = [], set()
    for ref in rec["refs"]:
        files = list(resolve_transcript(ref) or [])
        for r in rows:
            sr = str(r.get("source_ref") or "")
            if str(r.get("session_ref") or "") == ref and sr and not sr.startswith("events.jsonl"):
                files.append(Path(sr.split("#", 1)[0]))
        files = [p for p in dict.fromkeys(Path(f) for f in files) if p.is_file()]
        if not files:
            rec["no_file"].append(ref)
            continue
        for p in files:
            turns, why = _ow_transcript_turns(p)
            rec["read"].append((ref, str(p), why or f"read ({len(turns)} owner turn(s))"))
            for ts, text, uuid in turns:
                if not _in_life(ts) or (uuid and uuid in seen_uuid):
                    continue
                seen_uuid.add(uuid) if uuid else None
                words.append({"ts": ts, "text": text, "source": f"{p.name}#uuid:{uuid}"})
    for r in rows:
        d = r.get("data") if isinstance(r.get("data"), dict) else {}
        if r.get("type") == "trial_run" and str(d.get("plan") or "") == slug:
            rec["trials"].append({"ts": _ow_ts(r.get("ts")), "cycle": d.get("cycle"),
                                  "scenario": str(d.get("scenario") or ""),
                                  "observed": str(d.get("observed") or "")})
        if r.get("type") != "owner_directive" or str(r.get("session_ref") or "") not in part:
            continue
        m = re.search(r"#uuid:(\S+)$", str(r.get("source_ref") or ""))
        if m and m.group(1) in seen_uuid:
            continue                         # the same turn, already read from its transcript
        text = str(d.get("owner_text") or d.get("text") or "").strip()
        if text:
            if m:
                seen_uuid.add(m.group(1))
            words.append({"ts": _ow_ts(r.get("ts")), "text": text,
                          "source": f"events.jsonl#ts={r.get('ts')}"})
    for w in words:
        w["text"] = journal_mod.redact_owner_text(w["text"])
    words.sort(key=lambda w: w["ts"])
    rec["words"] = words
    items, fault = _ow_registry_items(body)
    if fault:
        rec["faults"].append(fault)
    ids = {str(it["id"]) for it in items}
    rules = _ow_plan_rules(body)
    for w in words:
        st = _ow_stems(w["text"])
        named = [i for i in re.findall(r"\bR-[1-9][0-9]*\b", w["text"]) if i in ids]
        target = None
        if named:
            target = f"registry {named[0]}"
        else:
            best = max(((len(st & _ow_stems(f"{it.get('what', '')} {it.get('surface', '')}")), str(it["id"]))
                        for it in items), default=(0, ""))
            if best[0] >= 2:
                target = f"registry {best[1]}"
            else:
                rb = max(((len(st & _ow_stems(r)), r) for r in rules), default=(0, ""))
                if rb[0] >= 2:
                    target = f"plan rule: {rb[1][:80]}"
        (rec["mapped"] if target else rec["unmapped"]).append((w, target))
    for i, later in enumerate(words):
        if not _OW_REVERSAL_RE.search(later["text"]):
            continue
        ls = _ow_stems(later["text"])
        for earlier in words[:i]:
            if len(ls & _ow_stems(earlier["text"])) >= 2 and earlier["text"] != later["text"]:
                rec["reversals"].append((earlier, later))
    return rec


def render_owner_words(rec: dict) -> str:
    """The owner-facing text of the reconciliation, shown beside the registry at the read-back."""
    out = [f"owner words of the spike period — plan {rec['slug']} (SPEC-1058 §2; read-only: writes "
           "nothing, refuses nothing; every mapping is a CANDIDATE — the owner decides)"]
    if not rec["opted_in"]:
        out.append("  the plan does not opt in to the carry registry (no prototype_ref, SPEC-1058 §1) — "
                   "nothing to reconcile")
        return "\n".join(out) + "\n"
    for f in rec["faults"]:
        out.append(f"  ! {f}")
    if rec["rounds"]:
        out.append(f"  spike life: {rec['start']} .. {rec['end'] or 'now'} — "
                   + ", ".join(f"{r[3]} (declared {r[0]} by {r[1]})" for r in rec["rounds"]))
        out.append("  sessions read: the prototype's declaring session, the sessions of this plan's "
                   "trial_run rows, and those whose owner_directive names the plan, the prototype or "
                   "its branch")
    if rec.get("unfollowed"):
        out.append("  NOT READ — spike tags inside the prototype's history and absent from main (an earlier "
                   "round or a merged spike; no row links them, so the owner decides whether to read them "
                   "with their own plan, or name it with `--earlier-tag <tag>`): " + ", ".join(rec["unfollowed"]))
    out.append("  transcripts read:")
    out += [f"    - {ref}: {path} — {how}" for ref, path, how in rec["read"]] or ["    (none)"]
    out.append("  refs with no transcript file:")
    out += [f"    - {ref}" for ref in rec["no_file"]] or ["    (none)"]
    out.append(f"  owner words: {len(rec['words'])}")
    out.append("  mapped (candidate):")
    out += [f"    - [{w['ts']}] {w['text']!r} -> {t}  ({w['source']})" for w, t in rec["mapped"]] \
        or ["    (none)"]
    out.append("  UNMAPPED — no registry item and no plan rule (show the owner):")
    out += [f"    - [{w['ts']}] {w['text']!r}  ({w['source']})" for w, _ in rec["unmapped"]] \
        or ["    (none)"]
    out.append("  REVERSALS (candidate — a later word turning an earlier one):")
    out += [f"    - [{a['ts']}] {a['text']!r}  ->  [{b['ts']}] {b['text']!r}"
            for a, b in rec["reversals"]] or ["    (none)"]
    out.append("  trial_run rows of this plan in the spike life (SPEC-0035):")
    out += [f"    - [{t['ts']}] cycle {t['cycle']}: {t['scenario']} — {t['observed']}"
            for t in rec["trials"]] or ["    (none)"]
    return "\n".join(out) + "\n"

def _plan_prototype_commits(repo_root, fm: dict) -> "tuple[str | None, str | None, str | None]":
    """(tip, base, fault). Once accept PINNED the pair (`prototype_tip` + `prototype_base`), it is read
    from the frontmatter and NEITHER the tag NOR main is read again (SPEC-1058 §2 one prototype
    commit). Before that: the tag's commit and its merge-base with main."""
    ref = str(fm.get("prototype_ref") or "").strip()
    tip, base = str(fm.get("prototype_tip") or "").strip(), str(fm.get("prototype_base") or "").strip()
    if tip and base:
        return tip, base, None
    tip, err = _plan_prototype_git(repo_root, "rev-parse", "--verify", f"refs/tags/{ref}^{{commit}}")
    if err:
        return None, None, f"prototype_ref `{ref}` does not resolve to a commit ({err})"
    base, err = _plan_prototype_git(repo_root, "merge-base", "main", tip)
    if err or not base:
        return tip, None, f"no merge-base between main and {ref} ({tip[:12]}): {err or 'empty'}"
    return tip, base, None


def _plan_prototype_changed_paths(repo_root, base: str, tip: str) -> "tuple[list, str | None]":
    """The changed paths of `git diff <base>...<tip>`; a rename lists BOTH its paths (--no-renames),
    since a `removed` item's locator points into the base."""
    out, err = _plan_prototype_git(repo_root, "diff", "--name-only", "--no-renames", f"{base}...{tip}")
    if err:
        return [], f"git diff {base[:12]}...{tip[:12]} failed: {err}"
    return sorted({p for p in out.splitlines() if p.strip()}), None


def _plan_prototype_unlocated(items: list, paths: list) -> list:
    """The changed paths no registry item locates (any kind, any disposition counts — SPEC-1058 §3)."""
    located = set()
    for it in items:
        for loc in it.get("locators") or ():
            m = _PROTO_LOCATOR_RE.match(str(loc).strip())
            if m:
                located.add(m.group("path"))
    return [p for p in paths if p not in located]


def _plan_prototype_read(repo_root, fm: dict, body: str, events_path=None) -> dict:
    """The one reader both seams use (plan check, plan stage accepted): ref validation (only while
    unpinned — a pinned plan no longer reads the tag), registry parse, commits, changed paths.
    Returns {fault, owner_read, items, tip, base, paths, diff}; `fault` names the first defect — a
    failed git read included, so no packet is ever built without its subject."""
    from lib import task as task_lib   # noqa: PLC0415 — prototype_ref_error, SPEC-0205 rule 5
    res = {"fault": None, "owner_read": None, "items": [], "tip": None, "base": None, "paths": [],
           "diff": None}
    ref = str(fm.get("prototype_ref") or "").strip()
    if not str(fm.get("prototype_tip") or "").strip():
        err = task_lib.prototype_ref_error(repo_root, ref, events_path)
        if err:
            res["fault"] = f"prototype_ref: {err}"
            return res
    res["owner_read"], res["items"], fault = _plan_prototype_registry(body)
    if fault:
        res["fault"] = fault
        return res
    res["owner_risk"] = _plan_prototype_owner_risk_rows(
        res["items"], events_path if events_path is not None else Path(repo_root) / "events.jsonl")
    res["tip"], res["base"], fault = _plan_prototype_commits(repo_root, fm)
    if fault:
        res["fault"] = fault
        return res
    res["paths"], res["fault"] = _plan_prototype_changed_paths(repo_root, res["base"], res["tip"])
    if res["fault"]:
        return res
    rng = f"{res['base']}...{res['tip']}"
    diff, err = _plan_prototype_git(repo_root, "diff", "--no-ext-diff", "-M", rng)
    if err is not None:
        res["fault"] = f"git diff {res['base'][:12]}...{res['tip'][:12]} failed: {err}"
        return res
    res["diff"] = diff
    # T-14528 — the per-path entries the packet renders by the mechanical reference rule (rename
    # detection ON for the packet only; the path floor above keeps --no-renames, both paths of a move).
    res["entries"], fault = _plan_prototype_entries(repo_root, rng, diff)
    if fault:
        res["fault"] = fault
    return res


# ── T-14528 (<project> X-2241) — the accept packet within the auditor's input budget ─────────────
# The provider refused a 1,279,908-char prompt (limit 1,048,576); the budget keeps a margin for the
# invoker's own wrapper. Owner rule events.jsonl#ts=2026-11-05T05:25:12Z: send by REFERENCE by a
# MECHANICAL path/kind rule; over budget after that, the per-surface SPLIT of the check is the standard
# path (events.jsonl#ts=2026-11-05T05:33:21Z); a refusal only for what cannot be split.
_AUDITOR_INPUT_BUDGET = 1_000_000
# T-14612 — how many parts of a split check run at once (0 = every part; 1 = one after another, in
# part order). PERFORMANCE: it changes the round's wall, never the verdict (worst part wins either
# way); read per call through `machine_settings.resolve("lib.plan.PLAN_CHECK_SLICE_WORKERS", ...)`.
PLAN_CHECK_SLICE_WORKERS = 0
_PROTO_TEST_DIRS = frozenset({"tests", "test", "__tests__"})   # never `spec(s)/`: specs are source
_PROTO_GENERATED_DIRS = frozenset({"vendor", "node_modules", "third_party", "dist"})
_PROTO_LOCKFILES = frozenset({"package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock",
                              "Pipfile.lock", "Cargo.lock", "Gemfile.lock", "composer.lock", "go.sum",
                              "uv.lock", "bun.lockb", "npm-shrinkwrap.json"})


def _plan_prototype_path_class(path: str, status: str, binary: bool) -> str:
    """'full', or the reference class of a changed path — a fixed path/kind rule, never a judgement.
    A deleted path is always 'full' (a removed feature is owner-meaningful)."""
    if status.startswith("D"):
        return "full"
    parts = path.split("/")
    name = parts[-1]
    dirs = set(parts[:-1])
    if binary:
        return "binary"
    if "__snapshots__" in dirs or name.endswith(".snap"):
        return "snapshot"
    if name in _PROTO_LOCKFILES:
        return "lockfile"
    if (dirs & _PROTO_GENERATED_DIRS or name.endswith((".min.js", ".min.css", ".map"))):
        return "generated"
    if (dirs & _PROTO_TEST_DIRS or (name.startswith("test_") and name.endswith(".py"))
            or re.search(r"(_test|\.test|\.spec)\.[A-Za-z0-9]+$", name)):
        return "test"
    return "full"


def _plan_prototype_entries(repo_root, rng: str, diff: str) -> "tuple[list, str | None]":
    """One entry per changed path of the -M diff: {path, old, status, similarity, added, deleted,
    cls, text}. The chunks of the diff are zipped with -M name-status/numstat (same order); a count
    mismatch is a fault — never a silently dropped path."""
    ns, err = _plan_prototype_git(repo_root, "diff", "--name-status", "-M", "-z", rng)
    if err is not None:
        return [], f"git diff --name-status {rng} failed: {err}"
    nm, err = _plan_prototype_git(repo_root, "diff", "--numstat", "-M", "-z", rng)
    if err is not None:
        return [], f"git diff --numstat {rng} failed: {err}"
    toks = [t for t in (ns or "").split("\0")]
    while toks and toks[-1] == "":
        toks.pop()
    rows, i = [], 0
    while i < len(toks):
        st = toks[i].strip()
        if st[:1] in ("R", "C"):
            rows.append((st, toks[i + 1], toks[i + 2]))
            i += 3
        else:
            rows.append((st, None, toks[i + 1]))
            i += 2
    ntoks = (nm or "").split("\0")
    stats, j = [], 0
    while j < len(ntoks):
        t = ntoks[j]
        if not t.strip():
            j += 1
            continue
        a, d, rest = (t.split("\t", 2) + ["", ""])[:3]
        if rest == "":   # a rename: the two paths follow as their own tokens
            j += 3
        else:
            j += 1
        stats.append((a, d))
    chunks = [c for c in re.split(r"(?m)^(?=diff --git )", diff or "") if c.startswith("diff --git ")]
    if not (len(rows) == len(stats) == len(chunks)):
        return [], (f"the base diff could not be split per path ({len(rows)} paths, {len(stats)} stat "
                    f"rows, {len(chunks)} diff chunks) — refused rather than render a partial subject")
    out = []
    for (st, old, path), (a, d), text in zip(rows, stats, chunks):
        binary = a == "-" and d == "-"
        sim = int(st[1:]) if st[:1] in ("R", "C") and st[1:].isdigit() else None
        out.append({"path": path, "old": old, "status": st[:1], "similarity": sim,
                    "added": None if binary else int(a or 0), "deleted": None if binary else int(d or 0),
                    "cls": _plan_prototype_path_class(path, st, binary), "text": text.rstrip("\n") + "\n"})
    return out, None


def _proto_entry_line(e: dict) -> str:
    lines = "binary" if e["added"] is None else f"+{e['added']}/-{e['deleted']} lines"
    move = f"moved {e['old']} -> {e['path']}, {e['similarity']}% similar; " if e["old"] else ""
    return f"- `{e['path']}` — {move}{e['cls']}, {lines}, {len(e['text'])} chars of diff"


def _proto_surface(path: str) -> str:
    parts = path.split("/")
    if len(parts) == 1:
        return "(root)"
    return "/".join(parts[:2]) if len(parts) > 2 else parts[0]


def _proto_items_for(items: list, paths: set) -> list:
    hit = []
    for it in items:
        for loc in it.get("locators") or ():
            m = _PROTO_LOCATOR_RE.match(str(loc).strip())
            if m and m.group("path") in paths:
                hit.append(it)
                break
    return hit


def _plan_prototype_packet(repo_root, fm: dict, body: str, read: dict, *, entries=None, part=None,
                           items=None) -> str:
    """The accept-check packet block: the base diff beside the registry and SPEC-1058 §3's question.
    T-14528: the registry is a POINTER to the plan body above (never a verbatim second copy); the diff
    renders per path by the mechanical reference rule — reference-only paths are LISTED with their
    class and size. `entries`/`part`/`items` render one surface slice of a split check; `part` =
    "whole" renders the final whole pass (the full path list, no code)."""
    import yaml   # noqa: PLC0415
    all_entries = read.get("entries") or []
    sec_note = ("The registry is the `## Prototype registry` section of the plan body above "
                "(not repeated here).")
    missing = _plan_prototype_unlocated(read["items"], read["paths"])
    floor = ("every changed path of the diff is a locator of some item" if not missing else
             f"{len(missing)} changed path(s) are located by NO item ({', '.join(missing)}) — "
             "`plan stage accepted` refuses until each is located")
    head = (f"\n## Prototype carry registry (SPEC-1058 §2-§3 — the accept question)\n\n"
            f"prototype_ref: {fm.get('prototype_ref')} · prototype commit {read['tip']} · "
            f"base (merge-base with main) {read['base']}\n\n")
    question = (
        "Accept question — judge the registry against the base diff below, hunk by hunk: (1) every "
        "owner-meaningful change of the diff has an item; (2) granularity — no item bundles two things "
        "the owner could see or test separately, and a change no owner sees is a `supporting` item "
        "naming the item it serves; (3) the section opens with the owner's read-back row "
        "(`owner_read`) and it is cited; (4) every item added after that read-back, or changed in "
        "`what`, `locators` or `disposition` after it, and every `not-carried` item, cites an "
        f"`owner_row`. The kernel's list checks, computed for this packet: the list parses; {floor}. "
        "The meaning is yours.\n\n")
    question += _plan_prototype_owner_risk_block(read.get("owner_risk") or {})
    rng = f"`git diff -M {read['base'][:12]}...{read['tip'][:12]}`"
    if part == "whole":
        listing = "\n".join(_proto_entry_line(e) for e in all_entries) or "(no changed paths)"
        return (head + "WHOLE PASS of a check split by surface (T-14528): the code was judged in the "
                "surface slices; judge here ONLY coverage and granularity of the whole registry against "
                "the full path list below — (1) and (2) of the question across slices, plus (3) and (4). "
                + question + f"### Registry\n\n{sec_note}\n\n### Every changed path of {rng}\n\n"
                + listing + "\n")
    ents = all_entries if entries is None else entries
    full = [e for e in ents if e["cls"] == "full"]
    refs = [e for e in ents if e["cls"] != "full"]
    moves = [e for e in full if e["old"]]
    out = head
    if part:
        out += (f"SURFACE SLICE {part} of a check split by surface (T-14528): judge the question for THIS "
                "slice's paths and the registry items located in them; one final whole pass judges "
                "coverage across slices.\n\n")
    out += question + f"### Registry\n\n{sec_note}\n\n"
    if items is not None:
        out += ("Items located in this slice (verbatim from the registry):\n\n```yaml\n"
                + (yaml.safe_dump(items, sort_keys=False, allow_unicode=True) if items else "[]\n")
                + "```\n\n")
    if refs:
        out += ("### Sent by reference (T-14528 mechanical rule: tests, lockfiles, generated/vendored/"
                "minified, snapshots, binary) — listed, not rendered\n\n"
                + "\n".join(_proto_entry_line(e) for e in refs) + "\n\n")
    if moves:
        out += ("### Moved files (rename detection; only the differing hunks below)\n\n"
                + "\n".join(_proto_entry_line(e) for e in moves) + "\n\n")
    body_diff = "".join(e["text"] for e in full)
    out += f"### Base diff {rng} (every path not listed above, in full)\n\n```diff\n{body_diff}```\n"
    return out


def _plan_prototype_owner_risk_block(risk: dict) -> str:
    """T-14533 (SPEC-1058 §2-§3) — the accept question's binding paragraph for owner-risk items, with
    the owner's own words of each cited row. Empty for a registry with no marked item, so that packet
    stays byte-identical."""
    if not risk:
        return ""
    rows = []
    for iid in sorted(risk, key=lambda rid: int(rid[2:])):
        r = risk[iid]
        words = (f"owner's words: «{r['row_text']}»" if r["row_text"] is not None else
                 "UNRESOLVED — no `owner_directive` row at this ts; `plan stage accepted` refuses it")
        rows.append(f"- {iid} · owner_risk {r['loc']} · {words}")
    return ("Owner-risk items (SPEC-1058 §2 — the owner's own decision; binding on this verdict):\n\n"
            + "\n".join(rows) + "\n\n"
            "For an item whose cited owner words accept, for THAT item, that its open detail is decided "
            "while building on main and checked by the owner in a sandbox raised from landed main, the "
            "absence of trial evidence and the undecided detail are EXPECTED and are NEVER a finding or a "
            "RED. Judge the DECLARATION instead: (a) the item is named; (b) the cited owner words really "
            "accept that risk for that item — words about another subject, a mere preference, no words or "
            "an UNRESOLVED row make the marker a finding, and the item is then judged as unmarked; (c) the "
            "verification route after land is the verifier's walk on landed main with any fix by the "
            "SPEC-0205 rule 7 acceptance-finding route. An unmarked item is judged exactly as before.\n\n")


def _plan_prototype_slices(read: dict, room: int, fm: dict) -> "tuple[list, str | None]":
    """T-14528 — cut the full-rendered paths into surface slices whose packet fits `room` chars.
    Surface = the first two path components (one for a two-part path). A surface too big alone is cut
    per file; one file too big alone is the fault (unsplittable). Returns [(label, entries, items)]."""
    ents = [e for e in (read.get("entries") or []) if e["cls"] == "full"]
    items = read.get("items") or []

    def _cost(es, label):
        ps = {p for e in es for p in (e["path"], e["old"]) if p}
        return len(_plan_prototype_packet(None, fm, "", read, entries=es, part=label,
                                          items=_proto_items_for(items, ps)))
    _LBL = "9999/9999"   # the widest label a packet carries (`k/N` only — surfaces stay in the record)
    groups: dict = {}
    for e in ents:
        groups.setdefault(_proto_surface(e["path"]), []).append(e)
    units = []
    for surf, es in groups.items():
        if _cost(es, _LBL) <= room:
            units.append((surf, es))
            continue
        for e in es:
            if _cost([e], _LBL) > room:
                return [], (f"`{e['path']}` alone renders {len(e['text'])} chars of diff — its slice "
                            f"exceeds the {room}-char room a slice has under the auditor budget, so it "
                            "cannot be split further")
            units.append((surf, [e]))
    slices, cur_s, cur_e = [], [], []
    for surf, es in units:
        if cur_e and _cost(cur_e + es, _LBL) > room:
            slices.append((cur_s, cur_e))
            cur_s, cur_e = [], []
        cur_s.append(surf)
        cur_e = cur_e + es
    if cur_e:
        slices.append((cur_s, cur_e))
    out = []
    for surfs, es in slices:
        ps = {p for e in es for p in (e["path"], e["old"]) if p}
        out.append((", ".join(dict.fromkeys(surfs)), es, _proto_items_for(items, ps)))
    return out, None


def _plan_prototype_earlier_plans(repo_root, slug: str, tip: str) -> list:
    """T-14622 (SPEC-1058 §2) — the EARLIER plans of this plan's prototype lineage: every other plan in
    plans/ that opted in, passed accept (pins a `prototype_tip`), is not rejected/cancelled, and whose
    tip is an ancestor of (or equal to) `tip`. A plan whose frontmatter cannot be read, or whose tip git
    cannot relate to `tip`, is not of the lineage."""
    out = []
    for p in sorted((Path(repo_root) / "plans").glob("*.md")):
        if p.stem == slug:
            continue
        try:
            fm, _body = state.split_frontmatter_text(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not _plan_is_prototype_opted_in(fm) or fm.get("status") in ("rejected", "cancelled"):
            continue
        other = str(fm.get("prototype_tip") or "").strip()
        if other and _plan_prototype_git(repo_root, "merge-base", "--is-ancestor", other, tip)[1] is None:
            out.append(p.stem)
    return out


def _require_plan_prototype_at_accept(slug: str, fm: dict, body: str, av: dict, *, REPO_ROOT, _die) -> "dict | None":
    """SPEC-1058 §2-§3 at `plan stage accepted` (inside `_plan_accept_core`, before the freshness
    checks and the spec birth). None for a plan that does not opt in. Else refuses — naming the
    fault — a malformed registry, a check that recorded no prototype commits, a tag or a base that
    moved since that check, or a changed path no item locates; returns the audited pair to pin."""
    if not _plan_is_prototype_opted_in(fm):
        return None
    read = _plan_prototype_read(REPO_ROOT, fm, body)
    if read["fault"]:
        _die(f"{slug}: plan stage accepted refused — the prototype carry registry: {read['fault']} "
             f"(SPEC-1058 §2). Fix the plan, then re-run `yitc-v2 plan check {slug}`.")
    unresolved = [f"{iid} (owner_risk {r['loc']})" for iid, r in (read.get("owner_risk") or {}).items()
                  if r["row_text"] is None]
    if unresolved:
        _die(f"{slug}: plan stage accepted refused — owner-risk item(s) whose owner_risk resolves to no "
             f"`owner_directive` row in the journal: {', '.join(unresolved)}. Only the owner's own row "
             f"marks an item owner-risk (SPEC-1058 §2): record it, or drop the marker, then re-run "
             f"`yitc-v2 plan check {slug}`.")
    rec_tip, rec_base = str(av.get("prototype_commit") or ""), str(av.get("prototype_base") or "")
    if not rec_tip or not rec_base:
        _die(f"{slug}: the recorded `plan check` verdict carries no prototype_commit/prototype_base — it "
             f"predates the plan's prototype_ref or the carry registry (SPEC-1058 §2). Re-run "
             f"`yitc-v2 plan check {slug}`.")
    if read["tip"] != rec_tip:
        _die(f"{slug}: the prototype tag {fm.get('prototype_ref')} moved since the accept check — the check "
             f"audited {rec_tip[:12]}, the tag now names {read['tip'][:12]}. Accept pins exactly the "
             f"audited commit (SPEC-1058 §2): re-run `yitc-v2 plan check {slug}`.")
    if read["base"] != rec_base:
        _die(f"{slug}: the prototype base moved since the accept check — the check audited "
             f"{rec_base[:12]}...{rec_tip[:12]}, merge-base(main, tip) is now {read['base'][:12]} "
             f"(main advanced into the prototype's history). Re-run `yitc-v2 plan check {slug}`.")
    for it in read["items"]:   # T-14622 — a carried-by-plan item names a plan that exists, never itself
        named = _proto_carried_by(it)
        if named is not None and (named == slug or not (Path(REPO_ROOT) / "plans" / f"{named}.md").is_file()):
            _die(f"{slug}: plan stage accepted refused — registry item {it['id']} is `carried-by-plan "
                 f"{named}`, but {'that is this plan itself' if named == slug else f'plans/{named}.md does not exist'}. "
                 f"Name the earlier plan that carries the item (SPEC-1058 §2), then re-run `yitc-v2 plan check {slug}`.")
    earlier = _plan_prototype_earlier_plans(REPO_ROOT, slug, rec_tip)
    if earlier and not {_proto_carried_by(it) for it in read["items"]} & set(earlier):
        _die(f"{slug}: plan stage accepted refused — the prototype lineage is already carried by the "
             f"earlier plan(s) {', '.join(earlier)}. A later plan on one lineage lists each item an earlier "
             f"plan carries as `disposition: carried-by-plan <slug>` (SPEC-1058 §2), then re-run "
             f"`yitc-v2 plan check {slug}`.")
    missing = _plan_prototype_unlocated(read["items"], read["paths"])
    if missing:
        _die(f"{slug}: plan stage accepted refused — {len(missing)} changed path(s) of "
             f"`git diff {rec_base[:12]}...{rec_tip[:12]}` are located by NO registry item: "
             f"{', '.join(missing)}. Add an item (a formatting-only change is a `supporting` item) or a "
             f"`not-carried` item with its owner_row (SPEC-1058 §3), then re-run `yitc-v2 plan check {slug}`.")
    return {"prototype_tip": rec_tip, "prototype_base": rec_base}


def _plan_prototype_lines_error(value) -> "str | None":
    """SPEC-1058 §3 — one `prototype_lines` value: `all` (the verifier), or a list of distinct `R-<n>`
    item ids, `[]` being a card that builds no item. None when well-formed, else the fault."""
    if value == "all":
        return None
    if not isinstance(value, list):
        return f"`{value}` is neither `all` nor a list of item ids"
    for rid in value:
        if not isinstance(rid, str) or not _PROTO_ITEM_ID_RE.match(rid):
            return f"`{rid}` is not an item id `R-<n>`"
    if len(set(value)) != len(value):
        return "an item id is listed twice"
    return None


def _proto_ids(ids) -> str:
    """Item ids in registry order (R-2 before R-10), comma-joined."""
    return ", ".join(sorted(ids, key=lambda rid: int(rid[2:])))


def _plan_prototype_cut_faults(fm: dict, body: str, rows: list, accept: dict, *, _plan_content_hash, change_check=None) -> list:
    """SPEC-1058 §3 at the gate to `executing`: every fault of the cut, by list comparison only. `rows`
    is `_plan_cut_rows`; a `wont-do` card builds nothing and is out of the check (the picker reads a
    wont-do `requires` target the same way). `accept` is the recorded accept `plan check` verdict.

    T-14627 (SPEC-1061 §4) — «fresh» reads the two arms: (i) the anchor GREEN/YELLOW AND its body hash
    current; else (ii) `change_check()` — a zero-arg callable returning the shared reader's
    (admission, reason) over the body hash. A RED anchor is fresh ONLY through arm (ii), body moved or
    not. The prototype_commit-vs-tip fault stays on the anchor: no change check moves the prototype."""
    owner_read, items, fault = _plan_prototype_registry(body)
    if fault:
        return [f"the registry: {fault}"]
    ref, faults = str(fm.get("prototype_ref") or "").strip(), []
    tip, base = str(fm.get("prototype_tip") or "").strip(), str(fm.get("prototype_base") or "").strip()
    if not tip or not base:
        faults.append("the plan pins no prototype_tip/prototype_base — `plan stage accepted` writes them")
    arm_i = (str(accept.get("verdict") or "").upper() in ("GREEN", "YELLOW")
             and accept.get("content_hash") == _plan_content_hash(body))
    if not arm_i:
        adm, why = change_check() if change_check is not None else (None, "")
        if adm is None:
            faults.append("the accept verdict is not fresh for the current plan body (registry included)"
                          + (f" — {why}" if why else ""))
    if tip and base and (accept.get("prototype_commit") != tip or accept.get("prototype_base") != base):
        faults.append(f"the accept verdict audited {accept.get('prototype_commit')}, not the pinned "
                      f"prototype_tip {tip}")
    live = [r for r in rows if r["status"] != "wont-do"]
    if not live:
        return faults + ["the cut is empty — no live task card carries `decomposed_from` this plan"]
    by_id = {it["id"]: it for it in items}
    owners, verifiers = {rid: [] for rid in by_id}, []
    for r in live:
        tid, lines = r["id"], r["doc"].get("prototype_lines")
        card_ref = str(r["doc"].get("prototype_ref") or "").strip()
        if card_ref != ref:
            faults.append(f"{tid} names prototype `{card_ref or 'none'}`, the plan's is `{ref}`")
        if lines is None:
            faults.append(f"{tid} declares no prototype_lines")
            continue
        err = _plan_prototype_lines_error(lines)
        if err:
            faults.append(f"{tid} has malformed prototype_lines: {err}")
        elif lines == "all":
            verifiers.append(r)
        else:
            for rid in lines:
                if rid not in by_id:
                    faults.append(f"{tid} names unknown item {rid}")
                elif by_id[rid]["disposition"] != "carry":
                    faults.append(f"{tid} names {by_id[rid]['disposition']} item {rid}")
                else:
                    owners[rid].append(tid)
    carry = [it for it in items if it["disposition"] == "carry"]
    zero, many = set(), {}
    for it in carry:
        rid, who = it["id"], owners[it["id"]]
        if not who and it["kind"] == "supporting":   # owned through the items it serves, or directly
            served = set(re.findall(r"\bR-[1-9][0-9]*\b", it["what"])) - {rid}
            who = sorted({t for s in served if s in by_id and by_id[s]["disposition"] == "carry"
                          for t in owners[s]})
        if not who:
            zero.add(rid)
        elif len(who) > 1:
            many[rid] = who
    if zero:
        faults.append(f"carry item(s) owned by NO writer: {_proto_ids(zero)}")
    if many:
        faults.append(f"carry item(s) owned by TWO writers: {_proto_ids(many)} ("
                      + "; ".join(f"{rid}: {', '.join(many[rid])}" for rid in many) + ")")
    if len(verifiers) != 1:
        faults.append(f"exactly one `all` card is required, the cut has {len(verifiers)}"
                      + (f" ({', '.join(v['id'] for v in verifiers)})" if verifiers else ""))
    else:
        vid = verifiers[0]["id"]
        needs = {str(x).strip() for x in verifiers[0]["doc"].get("requires") or []}
        missing = sorted(r["id"] for r in live if r["id"] != vid and r["id"] not in needs)
        if missing:
            faults.append(f"the `all` card {vid} does not require: {', '.join(missing)}")
        back = sorted(r["id"] for r in live if vid in {str(x).strip() for x in r["doc"].get("requires") or []})
        if back:
            faults.append(f"the `all` card {vid} must be the cut's last card, but it is required by: "
                          f"{', '.join(back)}")
    return faults


# T-14704 (X-2449) — the registry keys the fidelity gate judges (SPEC-1058 §3); every other key of an item
# (its notes) is left out of the gate packet and LISTED there, the full text by reference to the plan file.
_PROTO_GATE_JUDGED_KEYS = ("id", "kind", "surface", "what", "locators", "disposition", "owner_row", "owner_risk")


def _plan_registry_judged_view(body: str) -> "tuple[str, list]":
    """(the registry as the gate reads it, the left-out lines). A fixed key rule, never a judgement: each
    item keeps `_PROTO_GATE_JUDGED_KEYS` and nothing else; every other key is named `R-n: key (N chars)`.
    A registry that does not read (the cut checks refuse it first) falls back to its verbatim text."""
    import yaml
    _o, items, fault = _plan_prototype_registry(body)
    if fault or not items:
        return (_plan_prototype_registry_section(body) or "").strip(), []
    kept, left = [], []
    for it in items:
        kept.append({k: it[k] for k in _PROTO_GATE_JUDGED_KEYS if k in it})
        for k, v in it.items():
            if k not in _PROTO_GATE_JUDGED_KEYS:
                n = len(v if isinstance(v, str) else yaml.safe_dump(v, allow_unicode=True))
                left.append(f"{it.get('id')}: {k} ({n} chars)")
    return yaml.safe_dump(kept, sort_keys=False, allow_unicode=True, width=10_000).strip(), left


def _plan_body_registry_by_reference(body: str) -> str:
    """The plan body as the gate-executing prompt shows it: the `## Prototype registry` section's text
    replaced by one pointer to the packet block, so the registry is sent once (T-14704)."""
    out, inside = [], False
    for ln in body.splitlines():
        if ln.startswith("## "):
            if inside:
                inside = False
            elif ln[3:].strip() == PROTOTYPE_REGISTRY_SECTION:
                out += [ln, "", "(sent once, below: «Prototype carry registry» in the cut block — the judged "
                        "fields of every item; the full text stays in this plan file)", ""]
                inside = True
                continue
        if not inside:
            out.append(ln)
    return "\n".join(out) + ("\n" if body.endswith("\n") else "")


def _plan_prototype_cut_packet(body: str, rows: list) -> str:
    """The fidelity packet block of an opted-in plan: the registry's judged fields (T-14704 — every
    left-out key listed), each card's declared lines and SPEC-1058 §3's question about the verifier."""
    lines = "\n".join(f"- {r['id']} ({r['status']}): {r['doc'].get('prototype_lines')!r}" for r in rows)
    _o, items, _f = _plan_prototype_registry(body)
    judged, left = _plan_registry_judged_view(body)
    by_plan = ", ".join(f"{it['id']} (plan {_proto_carried_by(it)})" for it in items
                        if _proto_carried_by(it)) or "none"
    return (
        "\n\n## Prototype carry registry (SPEC-1058 §3 — the fidelity question)\n\n"
        "The kernel's list checks passed before this audit: lines, ownership, one prototype, the verifier "
        "last. Judge the meaning: does the `all` card's acceptance walk and record EVERY registry item on "
        "the acceptance stand over landed main — except the items carried by an earlier plan, which this "
        "cut does not walk — and route each failure under SPEC-1058 §3 — the SPEC-0205 "
        "rule 7 acceptance-finding route or an owner settlement on the item?\n\n"
        f"Not walked — `carried-by-plan` (the earlier plan's verifier walks them): {by_plan}\n\n"
        f"### prototype_lines per card\n\n{lines}\n\n"
        f"### Registry (the judged fields of every item — {', '.join(_PROTO_GATE_JUDGED_KEYS)}; the full "
        f"text by reference: the plan file's `## {PROTOTYPE_REGISTRY_SECTION}`)\n\n{judged}\n\n"
        f"### Left out of this packet (by reference to the plan file)\n\n"
        + ("\n".join(f"- {x}" for x in left) if left else "nothing") + "\n")


def _plan_prototype_freshness_suffix(repo_root, fm) -> str:
    """'' for a plan that does not opt in (the basis is then byte-identical); else the pinned pair, or
    — before accept — the tag commit and its merge-base. An unresolvable pair hashes as a marker, so
    the gate still compares (and the accept refusal above names the cause first)."""
    if not _plan_is_prototype_opted_in(fm) or repo_root is None:
        return ""
    tip, base, fault = _plan_prototype_commits(repo_root, fm)
    return f"|PROTO {tip or '-'} {base or '-'}" + (" unresolved" if fault else "")


def _plan_accept_freshness_hash(slug: str, body: str, fm: dict = None, sf=_SF_UNSET, *, SPECS_DIR, _plan_active_proposed_corpus, _plan_content_hash, _plan_scenario_fidelity, _read_yaml, _spec_content_sans_status, REPO_ROOT=None, parts_out: "dict | None" = None, own_paths_out: "dict | None" = None, obligations: "str | None" = None, obligations_through: "str | None" = None) -> str:
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
    `_birth_plan_draft_specs`).

    T-14627 (SPEC-1061 §1) — `parts_out`, when given, receives the digest of each input this hash
    covers, computed in THIS pass (no second scan; the returned hash is unchanged): `body`, `own_specs`
    (id -> digest), `corpus` (None while the plan owns no spec — the corpus is then no input),
    `scenario` and `prototype` (None when that slice is no input). The change check compares them to
    tell an eligible input from one that needs a fresh anchor. `own_paths_out`, when given, receives
    each plan-born spec's file path (id -> Path) from the same pass, so the change check reads no second
    corpus pass.

    T-14673 (SPEC-0034 §Plan-stage obligations) — `obligations` is the digest of the plan-stage
    obligations due through the plan's status (`plan_obligations_digest`). None (nothing due) leaves
    every basis below byte-identical; a digest is appended as `|OBL <digest>` to whichever basis
    applies, so a relevant rule change or activation stales the verdict while an unrelated spec edit
    does not. `parts_out["obligations"]` carries it for the change check's not-eligible test, and
    `parts_out["obligations_through"]` the boundary it was computed through, so a change check made
    after the plan moved on compares through the boundary its anchor judged."""
    # SPEC-0082 — the scenario-fidelity BASELINE slice (baseline list in authored order + each
    # baseline scenario's cites/covers/computed status). Folded into the basis ONLY when non-empty, so
    # a plan with no/empty scenario_roles hashes EXACTLY as before (byte-identical — no churn for the
    # existing corpus; the target list is NOT a freshness input, by construction of `fresh_inputs`).
    if sf is _SF_UNSET:                                  # not precomputed by the caller → derive it here
        sf = _plan_scenario_fidelity(fm) if fm is not None else None
    scen = sf["fresh_inputs"] if sf else ""
    own_ids, own, own_digests = set(), [], {}
    for p in state.scan_specs(SPECS_DIR):   # SPEC-* glob excludes _template.yaml
        d = _read_yaml(p)
        if isinstance(d, dict) and d.get("proposed_by") == slug:
            sid = d.get("id") or p.stem
            own_ids.add(sid)
            entry = f"OWN {sid}\n{_spec_content_sans_status(p.read_text(encoding='utf-8'))}\n"
            own.append(entry)
            own_digests[sid] = hashlib.sha256(entry.encode("utf-8")).hexdigest()
            if own_paths_out is not None:
                own_paths_out[sid] = p
    # T-14456 (SPEC-1058 §2) — an opted-in plan's prototype pair joins the basis; '' otherwise, so
    # every non-opted basis below is byte-identical to before.
    proto = _plan_prototype_freshness_suffix(REPO_ROOT, fm)
    if parts_out is not None:
        parts_out.update({"body": _plan_content_hash(body), "own_specs": own_digests, "corpus": None,
                          "scenario": hashlib.sha256(scen.encode("utf-8")).hexdigest() if scen else None,
                          "prototype": proto or None, "obligations": obligations,
                          "obligations_through": obligations_through})
    obl = f"|OBL {obligations}" if obligations else ""   # T-14673 — '' keeps every basis byte-identical
    if not own_ids:
        if not scen and not proto and not obl:
            return _plan_content_hash(body)   # NO plan-born specs + no scenario slice → legacy plan-body-only basis
        if not scen:
            return hashlib.sha256(f"{_plan_content_hash(body)}{proto}{obl}".encode("utf-8")).hexdigest()
        return hashlib.sha256(f"{_plan_content_hash(body)}|SCEN\n{scen}{proto}{obl}".encode("utf-8")).hexdigest()
    own_s = "".join(sorted(own))
    corpus = "".join(f"CORPUS {sid}:{st}\n{raw}\n"
                     for sid, st, _t, raw in _plan_active_proposed_corpus() if sid not in own_ids)
    if parts_out is not None:
        parts_out["corpus"] = hashlib.sha256(corpus.encode("utf-8")).hexdigest()
    basis = f"{_plan_content_hash(body)}|{own_s}|{corpus}"
    if scen:
        basis += f"|SCEN\n{scen}"
    basis += proto + obl
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


_CORPUS_BLOCK_BUDGET = 240_000  # BYTES (UTF-8) — HARD ceiling on the ENTIRE rendered accept-gate block
#   (prose + draft bodies + corpus index + footer), NOT only the corpus rows (T-9383 audit-post p1).
#   The fixed prose (~2KB) always fits; the VARIABLE parts fill the rest in priority order — draft
#   bodies first (the artifacts under audit), then the compact corpus index — and anything past the
#   ceiling is truncated / omitted with an explicit note. A reserved footer keeps the notices under the
#   ceiling, so the whole block can NEVER overflow codex regardless of corpus size OR draft-spec size.
_CORPUS_BLOCK_FOOTER_RESERVE = 800   # BYTES held back from the budget for the always-appended notices.
# T-12828 (X-1529) — the budget above was 64_000 until <project>'s five drafts (80928 bytes) rotated
# two bodies out of every pass and starved the index to 1/49 rows. 240_000 sits under the 325740-byte
# audit-post packet the SAME auditor read that day, so it is measured-safe, not a guess. Draft bodies
# and the corpus index no longer share one first-fit pool: the index keeps this RESERVED share, the
# drafts get the rest (`_corpus_draft_pool`), and drafts that exceed their pool are REFUSED before the
# auditor (`_plan_draft_pool_overflow`) instead of being audited as a partial subject.
_CORPUS_INDEX_RESERVE = 48_000   # BYTES reserved for the corpus index (never spent on draft bodies).


def _corpus_draft_pool() -> int:
    """The byte pool draft bodies may fill — the block budget minus the index reserve and the footer."""
    return _CORPUS_BLOCK_BUDGET - _CORPUS_INDEX_RESERVE - _CORPUS_BLOCK_FOOTER_RESERVE


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
                                   coverage_out: "dict | None" = None, hint_cli: str = "") -> str:
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
    block is byte-identical whether or not a sink is passed.

    T-12828 — separate reservations (draft pool vs `_CORPUS_INDEX_RESERVE`), RELATED comparands may
    spend the whole remaining budget, and every fetch pointer is rendered by the ONE SPEC-0092 renderer
    with the caller's executable prefix (`hint_cli`): under `-C` that is `<engine>/bin/yitc-v2 -C
    <repo>`, so the auditor resolves the CONSUMER's own ids — the corpus here is the repo's own specs,
    so `--kernel` would be the wrong lookup (X-1528). The sink also carries the budget and the
    measured sizes, so every shortfall reason can name them."""
    drafts = _plan_draft_specs(slug)
    if not drafts:
        # A work-first / task-only plan births no drafts, so there is NOTHING the gate could fail to
        # reach — full reach by definition (recorded explicitly, not left absent-and-ambiguous).
        if coverage_out is not None:
            coverage_out.update({"corpus_omitted": 0, "draft_truncated": 0, "clamped_bytes": 0,
                                 "corpus_total": 0, "drafts_total": 0, "related_omitted": 0})
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
    draft_truncated, draft_sizes = 0, {}
    draft_pool, draft_used = _corpus_draft_pool(), 0
    for sid, path, raw in drafts:
        piece = f"\n--- {sid} ({path.name}) ---\n{raw}\n"
        n = len(piece.encode("utf-8"))
        draft_sizes[sid] = n
        # the drafts' OWN pool — they can never eat the index reserve (T-12828)
        if draft_used + n > draft_pool or not _add_capped(piece):
            draft_truncated += 1
            continue
        draft_used += n
    # (b) The active+proposed corpus as a COMPACT index: RELATED comparands first, then the rest, all
    # under the SAME ceiling (related ∪ same-surface are the highest duplication risk).
    comparands = [(sid, st, title, raw) for sid, st, title, raw in corpus if sid not in draft_ids]
    related, other = [], []
    for sid, st, title, raw in comparands:
        (related if (sid in related_ids or _spec_on_surface(raw, surfaces)) else other).append(
            (sid, st, title, raw))

    # NOT `graph_lib.spec_query_hint`: that renderer's `-C` arm is `--kernel` (a KERNEL contract named by
    # a bare id), while every id in THIS block is the repo's OWN spec — so the realm travels in the
    # caller's `-C <repo>` executable prefix and the lookup stays consumer-own (T-12828 / X-1528).
    hint = f"{hint_cli} graph query <SPEC>" if hint_cli else "graph query <SPEC>"
    hint_all = f"{hint_cli} graph query --type spec" if hint_cli else "graph query --type spec"

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
        f"(`{hint}`) to confirm.\n")
    index_start = used
    corpus_omitted, related_omitted, related_bytes = 0, 0, 0

    def _emit(rows) -> int:
        nonlocal corpus_omitted
        dropped = 0
        for sid, st, title, raw in rows:
            if not _add_capped(_line(sid, st, title, raw)):
                corpus_omitted += 1
                dropped += 1
        return dropped

    if related:
        _add(f"\n#### Related comparands ({len(related)} — highest duplication risk)\n")
        related_bytes = sum(len(_line(*r).encode("utf-8")) for r in related)
        related_omitted = _emit(related)
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
                   f"`{hint}` / list all via `{hint_all}`.)\n")
    if draft_truncated:
        footer += (f"\n(WARNING: {draft_truncated} draft spec(s) under audit were omitted to keep the block "
                   f"within the {_CORPUS_BLOCK_BUDGET}-byte ceiling — the plan births an unusually large draft "
                   f"corpus; audit them directly via `{hint}`.)\n")
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
                             "corpus_total": len(comparands), "drafts_total": len(drafts),
                             # T-12828 — the budget + measured sizes every shortfall reason names
                             "block_budget": _CORPUS_BLOCK_BUDGET, "draft_pool": draft_pool,
                             "draft_sizes": draft_sizes, "draft_bytes_total": sum(draft_sizes.values()),
                             "index_bytes": used - index_start, "block_bytes": len(content.encode("utf-8"))
                             + len(footer.encode("utf-8")),
                             "related_omitted": related_omitted, "related_bytes": related_bytes})
    return content + footer


def _format_draft_sizes(sizes) -> str:
    """`SPEC-A=123B, SPEC-B=456B` — the per-draft byte sizes, in id order. Pure."""
    if not isinstance(sizes, dict) or not sizes:
        return "unknown"
    return ", ".join(f"{sid}={n}B" for sid, n in sorted(sizes.items()))


def _plan_draft_pool_overflow(coverage: "dict | None") -> "str | None":
    """T-12828 (X-1529) — the refusal message when the accept-gate block could NOT carry its whole
    subject: a draft body over the draft pool, or a RELATED comparand the remaining budget could not
    hold. None when everything the auditor must see fits. Auditing a partial subject is what turned
    missing draft bodies into a HIGH finding against the PLAN, pass after pass, with a different pair
    missing each time — so this is refused BEFORE the auditor, with the sizes, and no pass is spent.
    Pure — the caller owns the journal row + the exit."""
    cov = coverage or {}
    truncated = int(cov.get("draft_truncated") or 0)
    related = int(cov.get("related_omitted") or 0)
    if not (truncated or related):
        return None
    budget = cov.get("block_budget") or _CORPUS_BLOCK_BUDGET
    parts = []
    if truncated:
        parts.append(f"{truncated} of {cov.get('drafts_total')} draft spec(s) do not fit: the drafts total "
                     f"{cov.get('draft_bytes_total')} bytes against a {cov.get('draft_pool')}-byte draft pool "
                     f"(the {budget}-byte block less the {_CORPUS_INDEX_RESERVE}-byte corpus-index reserve); "
                     f"per draft: {_format_draft_sizes(cov.get('draft_sizes'))}")
    if related:
        parts.append(f"{related} related comparand row(s) (requires/cites/supersedes + same-surface, "
                     f"{cov.get('related_bytes')} bytes) do not fit the {budget}-byte block after the drafts")
    return ("plan check REFUSED before the auditor — the accept-gate block cannot carry its whole "
            "subject: " + "; ".join(parts) + ". No audit pass was spent. Split the plan's drafts across "
            "plans, or shrink the oversized draft(s), then re-run (T-12828 / SPEC-0034 §accepted).")


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
    budget = cov.get("block_budget") or _CORPUS_BLOCK_BUDGET
    if truncated or omitted or clamped:
        sources.append("block-ceiling")
        # T-12828 (X-1535) — EVERY reason names the budget and the measured sizes, not only the clamp.
        if truncated:
            reasons.append(f"{truncated} of {cov.get('drafts_total') or truncated} draft spec(s) under "
                           f"audit were NOT put in front of the auditor (drafts "
                           f"{cov.get('draft_bytes_total', '?')} bytes vs a {cov.get('draft_pool', '?')}-byte "
                           f"draft pool of the {budget}-byte block, per draft: "
                           f"{_format_draft_sizes(cov.get('draft_sizes'))})")
        if omitted:
            reasons.append(f"{omitted} of {cov.get('corpus_total') or omitted} active+proposed corpus "
                           f"spec(s) were NOT indexed for comparison (index used "
                           f"{cov.get('index_bytes', '?')} bytes of the {budget}-byte block, drafts took "
                           f"{cov.get('draft_bytes_total', '?')} bytes)")
        if clamped:
            reasons.append(f"{clamped} byte(s) of the assembled block were cut at the "
                           f"{budget}-byte ceiling (assembled {cov.get('block_bytes', '?')} bytes)")
    if self_report:
        sources.append("auditor-self-report")
        reasons.append(f"the auditor SELF-REPORTED it could not fully read/verify the corpus (block "
                       f"{cov.get('block_bytes', '?')} bytes of the {budget}-byte budget, drafts "
                       f"{cov.get('draft_bytes_total', '?')} bytes, index {cov.get('index_bytes', '?')} bytes)")
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
    spec body (PLAN_GATE_TEMPLATE_SPEC — ONE home, SPEC-0083 §Plan-stage question templates, T-12889). Returns the
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


def _plan_gate_decision_route(slug, gate_id, template, keys=None) -> str:
    """The SPEC-0204 plan-gate decision route, spelled ONCE (T-12335).

    THREE sites print it — the retired `--owner-reset` shim, the ordinary ceiling refusal, and the
    retired plan-gate consult (which reads the same carrier from `audit.RETIRED_AUDIT_SURFACES`) — and
    all three are reached by a caller who is already blocked. A second copy would drift, and the
    T-11250 lesson is precisely that a refusal reached under pressure must print the EXACT invocation:
    the gate id and the template name are DIFFERENT identifiers and both are real, so both are named.

    T-14409 (<project> X-2157) — with `keys` (the open finding keys the caller resolved) step 1 is
    printed READY, one `audit decide` line per key; without them it keeps the `<fp>` placeholder.
    The `plan stage` target is read off a `gate-<status>` template name (the gate guards the move
    INTO `<status>`); any other template keeps `<NEXT>`.

    Pure f(args); never raises."""
    gate = gate_id or "<gate>"
    tmpl = str(template or "")
    nxt = tmpl[len("gate-"):] if tmpl.startswith("gate-") and len(tmpl) > len("gate-") else "<NEXT>"
    tail = "--disposition fix|accept|defer --reason … --directive events.jsonl#ts=<ISO>"
    if keys:
        step1 = (f"  1) one decision per open finding ({len(keys)}):\n"
                 + "".join(f"     yitc-v2 audit decide --plan {slug} --gate {gate} --finding {k} "
                           f"{tail}\n" for k in keys))
    else:
        step1 = (f"  1) yitc-v2 audit decide --plan {slug} --gate {gate} --finding <fp> {tail}\n"
                 f"     (ONCE PER RESIDUAL — the refusal above, or the `--on-decisions` run below, "
                 f"names the undecided ones)\n")
    return ("Run, verbatim:\n"
            + step1
            + f"  2) yitc-v2 plan stage {nxt} {slug} --on-decisions\n"
            f"NOTE the two identifiers are DIFFERENT and both are real: `{template}` is the "
            f"audit-record/template name, `{gate}` is the value `--gate` takes (SPEC-1034 gate "
            f"identity). A plan-gate `fix` is a PLAN-BODY edit whose `--evidence` is the plan's "
            f"CURRENT signature; at the `decomposition-executing` gate it is a CUT edit whose "
            f"`--evidence` is the CURRENT card-set fingerprint (SPEC-0204 rule 9(d)); at the "
            f"`finalization` gate `fix` is refused by name and `accept`/`defer` are the "
            f"dispositions available.\n"
            f"SUBJECT MOVED AFTER THE DECISIONS WERE RECORDED? Run step 2 as it stands: when every "
            f"residual carries a `fix`, the pass binds the plan's or cut's signature CURRENT when it "
            f"runs; an `accept` or `defer` never carries to a subject it did not name (SPEC-1041 "
            f"rule 9, T-14702).")


def _plan_gate_engine_context(slug: str, audit_path, content_hash: str, od_packet,
                              has_prior_record: bool) -> str:
    """The plan-gate prompt tail AFTER the `## Plan <slug>` section (T-12555).

    The on-decisions block renders under its OWN top-level heading, never as a `###` sub-heading
    of the plan — measured 2026-09-13: the auditor read the appended ceiling block as part of the
    plan and reported «supplied plan ≠ on-disk plan». A prior record on disk is named as HISTORY,
    because the auditor reads it from the checkout and reported «gate remains RED» on the very pass
    that IS the fresh gate. No projection and no prior record → empty (prompt byte-identical).

    Pure f(inputs); never raises."""
    rel = audit_path
    parts = []
    if has_prior_record:
        parts.append(
            f"\n## Prior gate record — HISTORY, not a finding of this pass\n\n"
            f"The record at `{rel}` holds PRIOR passes of this gate and is HISTORY. THIS invocation "
            f"is the fresh gate over the plan above; a prior verdict recorded there is not a finding "
            f"of this pass — judge the plan as supplied.\n")
    if od_packet is not None:
        parts.append(
            f"\n## Engine packet — appended context (NOT part of the plan file)\n\n"
            f"The audited subject is the on-disk plan file `plans/{slug}.md` at content_hash "
            f"`{content_hash}` — exactly the `## Plan {slug}` section above. Everything below is "
            f"controller bookkeeping the engine appended to this prompt; it is not plan text.\n"
            + audit_lib.on_decisions_packet_block(od_packet))
    return "".join(parts)


def _prompt_size_fields(prompt: str, *, plan_body: str = "", cut_cards: str = "",
                        corpus_bytes: int = 0) -> dict:
    """T-13619 — REPORT-ONLY: the auditor prompt's total UTF-8 bytes and its parts, for a plan-gate row.

    `plan_body`, `cut_cards` and `corpus` are measured from the strings the prompt was built from;
    `lens_template` is the remainder (lens, FSM line, gate template, headings, engine context), so the
    parts sum to the total by construction. Nothing reads these keys to decide anything (SPEC-0025)."""
    total = len(prompt.encode("utf-8"))
    named = {"plan_body": len(plan_body.encode("utf-8")), "cut_cards": len(cut_cards.encode("utf-8")),
             "corpus": int(corpus_bytes or 0)}
    return {"prompt_bytes": total,
            "prompt_parts_bytes": {"lens_template": total - sum(named.values()), **named}}


def _auditor_guard_note(full: bool) -> str:
    """T-13574 — the hang guard a plan audit is about to run under, in the form `audit status`
    prints: the resolved seconds and the layer that answered (env, machine binding or shipped
    default). Read through the ONE resolution the adapter arms its wall from, so the line follows
    an override instead of quoting the constant."""
    secs, layer = audit_lib.audit_timeout_resolution(
        audit_lib.AUDIT_FULL_CONSULT_CLASS if full else None)
    return f"timeout={secs}s [{layer}]"


def _run_plan_gate_audit(slug: str, fm: dict, body: str, template: str, gate_policy: str,
                         *, blocking: bool, card_set_fp: "str | None" = None,
                         extra_context: "str | None" = None, owner_reset: bool = False, on_decisions: bool = False, gate_id: "str | None" = None, admission_only: bool = False, _folded_events=None, AUDIT_PASS_CEILING, DECISIONS_DIR, REPO_ROOT, _PLAN_AUDIT_LENS, _PLAN_CONSULT_GATE_AUDIT, _append_event, _auto_rebuild_graph, _die, _invoke_auditor, _parse_audit_verdict, _plan_content_hash, _plan_fsm_line, _plan_gate_recorded_signature, _plan_gate_template_text, _read_yaml, _resolve_audit_effort, _resolve_audit_model, _resolve_audit_reserve=None, _resolve_audit_provider, _strip_degenerate_tail, _utc_now_iso, finding_count_trend, is_trend_convergence_grant, write_text_atomic, _iter_events=None, EVENTS_PATH=None, _plan_obligations=None) -> str:
    """T-0349 — the verb-asked plan-gate audit (SPEC-0083 §Plan-stage question templates, ex-SPEC-0036): `plan stage specs`
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
    # T-13574 — the anchor `duration_ms` on this gate's rows is measured from (SPEC-0025 §Required
    # `duration_ms` field set). It starts here and is RE-anchored where the prompt is handed to the
    # auditor, so a path that saves without invoking one still records a real wall.
    _gate_t0 = time.monotonic()
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
    _trend_ceiling_grant = False
    # HOISTED (T-12335): the gate id is the identity the SPEC-0204 plan-gate arm keys everything on —
    # the ceiling row's `stage`, `ceiling_ref`, the decision payload — so `_save` needs it too, not just
    # the ceiling block below. A template with no gate id (there is none today) yields None and the row
    # emit in `_save` is SKIPPED rather than written unkeyed: fail-closed.
    # T-13844 — an EXPLICIT gate id wins: the `finalization` gate's record (`<slug>-audit-post.yaml`)
    # is written by the aggregate `audit post --plan`, not from a gate template, so the table above
    # holds no entry that could answer for it.
    gate_id = gate_id or _PLAN_TEMPLATE_TO_GATE_ID.get(template)
    _sig_field = (_PLAN_CONSULT_GATE_AUDIT.get(gate_id) or (None, None))[1] if gate_id else None
    _od = None            # the admitted rule-3 context: {ceiling_ref, residual_keys, by_fp, named}

    # THE REFUSAL SEAM IS DEFINED HERE — ABOVE THE FORK — BECAUSE BOTH ARMS CALL IT (T-12928): the
    # at-ceiling arm below refuses on rule 3's admission axes, the below-ceiling guard just after this
    # refuses `ceiling-not-reached`. The task arm's `cmd_audit` places its seam the same way.
    def _od_refuse(kind: str, why: str, message: str, extra=None) -> None:
        """The ONE refusal seam of the plan-gate rule-3 admission: journal the axis, then die.
        No auditor is invoked and no pass is spent on any path through here, so `passes` in the
        saved record is untouched. The emit is wrapped so a journal write error can never mask
        the refusal (the `_emit_read_gate_refused` best-effort idiom)."""
        payload = {"verb": f"plan stage ({template} gate)",
                   "action": "run the SPEC-0204 rule-3 on-decisions pass",
                   "kind": kind, "target_kind": "plan", "plan_slug": slug,
                   "gate": gate_id, "stage": gate_id, "reason": why}
        if extra:
            payload.update(extra)
        try:
            _append_event("read_gate_refused", None, payload)
        except (Exception, SystemExit):   # noqa: BLE001 — journaling never masks the refusal
            pass
        _die(f"{slug} gate {gate_id}: {message}")

    # T-12928 (<project> X-1576) — `--on-decisions` BELOW the ceiling REFUSES. The rule-3 admission
    # lives inside the at-ceiling branch, so without this guard the flag was silently ignored below it
    # and the ordinary auditor invocation spent pass N+1. An advisory gate has no ceiling at all, so
    # it refuses the same way. Placed before any auditor call: no auditor invoked, no pass spent.
    if on_decisions and not (blocking and prior_passes >= AUDIT_PASS_CEILING):
        _od_refuse("below-ceiling", "ceiling-not-reached",
                   f"ceiling-not-reached — the gate has {prior_passes} of {AUDIT_PASS_CEILING} "
                   f"recorded pass(es). `--on-decisions` is the ONE pass PAST the ceiling, governed by "
                   f"decisions that only exist once it is reached (SPEC-0204 rules 2-3); run here it "
                   f"would spend pass {prior_passes + 1} of {AUDIT_PASS_CEILING} as an ordinary pass. "
                   f"Refused — no auditor invoked, no pass spent. Drop the flag to run the ordinary "
                   f"gate pass.",
                   {"prior_passes": prior_passes, "pass_ceiling": AUDIT_PASS_CEILING,
                    "would_spend_pass": prior_passes + 1})
    if blocking and prior_passes >= AUDIT_PASS_CEILING:
        # T-9717 (L2 parity with T-9682/T-9702) — TREND-AWARE ceiling grant for the EARLY plan gates.
        # Pure f(prior record): when the recorded finding-count trend is strictly DECREASING with no
        # residual above MEDIUM AND prior_passes == the flat cap (the one pass the +1 unblocks), grant ONE
        # bounded extra pass — the same single +1 mechanic as --owner-reset, but AUTONOMOUS (no owner
        # ask). BOUNDED to +1: it fires ONLY at prior_passes == AUDIT_PASS_CEILING, so a second
        # still-decreasing step at cap+1 stays blocked; a FLAT/GROWING/high-residual trend blocks too.
        # Gated on `not owner_reset` so an explicit --owner-reset keeps its UNCHANGED T-9286
        # consult-governs path (a trend grant never preempts the owner's explicit reset).
        # ── SPEC-0204 rule 6, PLAN-GATE arm (T-12335) — `--owner-reset` IS RETIRED HERE ────────────
        # Its basis was a converged plan-gate consult, and that consult is retired with the episodes it
        # opened (`audit consult --plan --gate` now refuses). Retiring the basis without retiring the
        # flag would leave a flag that can never be satisfied — which is precisely the dead end this
        # card exists to remove, dressed as a live surface. The flag stays REGISTERED so a caller
        # holding a pre-retirement brief meets this route rather than argparse's `unrecognized
        # arguments`; the two retirements are named in ONE carrier
        # (`audit.RETIRED_AUDIT_SURFACES`), which `plan_gate_live_terminal_reasons` also reads.
        #
        # PLACED FIRST in the ceiling block, above every read: no auditor invoked, no pass spent, and
        # the route learned before anything is paid for (the sibling shims' placement rule).
        if owner_reset:
            _die(audit_lib.RETIRED_AUDIT_SURFACES["plan-gate-owner-reset"] + "\n\n"
                 + _plan_gate_decision_route(slug, gate_id, template))
        trend_grant = (not on_decisions and prior_passes == AUDIT_PASS_CEILING
                       and is_trend_convergence_grant(prior))
        # ── SPEC-0204 rule 6, PLAN-GATE arm (T-12335) — THE DISPATCHED-WORKER AUTO-CONSULT IS GONE ──
        # A headless worker at a plan-gate ceiling used to AUTO-run a convergence consult and, on a
        # clean single technical survivor, self-grant the `--owner-reset` above. Rule 6 already retired
        # the auto-consult on the TASK axis; this is the SAME mechanism on the plan axis, and it goes
        # with the same reasoning: a Worker never decides past the ceiling (SPEC-0103 §3). It HALTS
        # naming its residual fingerprints, the Controller records one typed decision per residual, and
        # the worker resumes with `plan stage <NEXT> --on-decisions`. The halt text below is the
        # ordinary ceiling refusal, which now names those fingerprints for exactly that reason.
        _worker_ref = os.environ.get("YITC_EXPECTED_SESSION_REF", "").strip()
        # ── RULE 9(f) — THE PLAN-GATE BUDGET IS DECISION-BOUNDED (T-12505, `audit_lib.PLAN_GATE_BUDGET`) ──
        # The task arm's rule-4 terminal (an `--on-decisions` RED ends the stage) is NOT applied here: a
        # plan converges by iteration, so an on-decisions RED is simply the NEW ceiling row (the highest
        # `passes`, `_ceiling_row_of`). A plain re-run still falls to the ordinary ceiling refusal below,
        # which names THAT row's residual fingerprints; `--on-decisions` re-runs the unchanged rule-3
        # admission against it, so every further round needs a fresh `ceiling_decision` per residual —
        # bounded by recorded decisions, never by silence. Rows are read from the SAME folded journal the
        # admission reads, so a decision recorded on main is visible here (SPEC-0168 rule 7).
        _od_rows = list(_folded_events()) if _folded_events is not None else []
        _od_stage_rows = audit_lib._stage_audit_rows(_od_rows, slug, gate_id) if gate_id else []
        if on_decisions:
            # ── C-C — THE ONE BOUNDED PASS, ADMITTED (SPEC-0204 rule 3, plan-gate arm) ─────────────
            # Every helper called here is the TASK arm's, keyed on `(slug, gate_id)` in place of
            # `(tid, stage)`: no second reader, no second matrix, no second event type.
            if not gate_id:
                _die(f"{slug}: --on-decisions is not available at the {template} gate — the template "
                     f"maps to no SPEC-1034 gate id, so a ceiling row cannot be keyed (fail-closed).")
            if _folded_events is None:
                _die("plan stage --on-decisions: the folded journal reader is not wired at this call "
                     "site (engine defect — report it).")

            # THE CEILING ROW — the journal row for this pair, else the READ-TIME SYNTHETIC row built
            # from `prior`, the gate's own saved record THIS FUNCTION ALREADY READ. Nothing is
            # appended and no second YAML parser exists: the synthetic row carries no `findings[]`, so
            # `row_residual_fingerprints` takes its shape-(c) branch with that record INJECTED.
            _od_ceiling_row = audit_lib._ceiling_row_of(_od_stage_rows) if _od_stage_rows else None
            _od_record = None
            if _od_ceiling_row is None:
                _od_record = prior if isinstance(prior, dict) and prior else None
                if not _od_record:
                    _od_refuse("below-ceiling", "no_completion_row",
                               f"there is no `external_audit_completed` row for this gate and no saved "
                               f"gate-audit record to resolve one from — nothing to decide "
                               f"(SPEC-0204 rule 3).")
                _od_ceiling_row = audit_lib.plan_gate_synthetic_ceiling_row(
                    slug, gate_id, template, _od_record,
                    saved_to=str(audit_path.relative_to(REPO_ROOT)))
            _od_res = audit_lib.on_decisions_residuals(
                _od_ceiling_row, _od_stage_rows, slug, gate_id,
                repo_root=[REPO_ROOT], decisions_dir=DECISIONS_DIR, record=_od_record)
            _od_passes = _od_res.get("passes")
            if _od_passes is None:
                _od_refuse("below-ceiling", "ceiling_row_passes_unresolved",
                           f"the ceiling row records no `passes` counter and the saved gate record "
                           f"states none either, so `ceiling_ref` cannot name a pass — the decisions "
                           f"could not be bound to it (SPEC-0204 rules 2-3).")
            _od_ref = f"{slug}/{gate_id}/pass-{_od_passes}"
            _od_keys = list(_od_res.get("keys") or ())
            # The decisions come from the SAME folded rows: a `ceiling_decision` is a no-worktree
            # append that lands on MAIN (D-0049), so reading only this checkout's journal would
            # deadlock the very gates this route exists to unblock (SPEC-0168 rule 7).
            _od_decisions = [r for r in _od_rows
                             if isinstance(r, dict) and r.get("type") == "ceiling_decision"
                             and (r.get("data") or {}).get("plan_slug") == slug
                             and (r.get("data") or {}).get("gate") == gate_id]
            _od_by_fp = audit_lib.on_decisions_bind(_od_decisions, _od_ref)
            _od_subjects = {str(d.get("subject_revision") or "").strip()
                            for d in _od_by_fp.values()} - {""}
            _od_ceiling_subject = next(iter(_od_subjects)) if len(_od_subjects) == 1 else None
            # THE CURRENT SUBJECT. For the three `content_hash` gates it is the plan body's signature
            # RECOMPUTED NOW, so a body edited after the decisions were recorded is caught by arm 1.
            # For `corpus_signature` it is the gate's RECORDED signature: a `fix` is refused at decide
            # time there (nothing here could verify one), so the only admissible sets are
            # all-`accept`/`defer`, whose named revision IS that recorded signature.
            #
            # `card_set_fingerprint` SPLITS BY WHAT THE DECISIONS NAME (T-12615, SPEC-0204 rule 9(d)).
            # A `fix` at `decomposition-executing` is a CUT edit, so it names the CURRENT cut — which
            # `_require_plan_decomposition_fidelity` already recomputed and handed us as `card_set_fp`,
            # the very value this pass will RECORD. Comparing it against the gate's RECORDED (pre-repair)
            # signature would refuse every repaired cut `decisions-not-for-this-revision`, which is the
            # deadlock this card removes. An all-`accept`/`defer` set keeps the read-back VERBATIM: such
            # a set names no revision of its own, so no set admitted before this change starts being
            # refused (additive, fail-safe — and `card_set_fp` absent falls back the same way).
            _od_has_fix = any(str((d or {}).get("disposition") or "").strip().lower() == "fix"
                              for d in _od_by_fp.values())
            # T-14702 (<project> X-2447) — at `card_set_fingerprint` the RECOMPUTED cut is the current
            # subject for EVERY decision set, not only a `fix` set: reading the gate's RECORDED
            # signature for an all-`accept`/`defer` set let those decisions carry to a cut that moved
            # after they were recorded. An unknown cut (no value handed in, or the helper's degraded
            # sentinel) is an UNKNOWN subject — None, which the admission refuses fail-closed — and is
            # never substituted by the recorded signature (audit-pre pass-1 fp1:7d96f0adb14b7513).
            # `_od_has_fix` stays as read by the empty-set branch below and the T-12615 wording.
            if _sig_field == "content_hash":
                _od_current = _plan_content_hash(body)
            elif _sig_field == "card_set_fingerprint":
                _od_current = (card_set_fp if card_set_fp
                               and card_set_fp != audit_lib.PLAN_CARD_SET_FINGERPRINT_ERROR else None)
            else:
                _od_current = _plan_gate_recorded_signature(slug, gate_id)
            if not _od_by_fp and _od_current is None:
                # The EMPTY residual set keeps its own subject (T-13860): nothing is bound, so no
                # decision can carry anywhere; the recorded signature is the row's own subject.
                _od_current = _plan_gate_recorded_signature(slug, gate_id)
            if not _od_by_fp:
                # T-13860 — A CEILING ROW WITH NO RESIDUAL ADMITS THE NEXT ROUND. Rule 9(f) admits a
                # round once EVERY residual of the latest row carries a decision; over an EMPTY set
                # that holds with none recorded. With no decision bound to this row, nothing names a
                # revision the subject must match: the round is audited at the CURRENT subject and
                # everything it raises counts NEW at its own severity. Only the resolved empty set
                # reaches the subject check this way — an UNRESOLVABLE row and a row with an
                # undecided residual are each refused on that cause first, by the admission below.
                _od_ceiling_subject = _od_current
            _od_named, _od_refusal = audit_lib.on_decisions_admission(
                tid=slug, stage=gate_id, residual_keys=_od_keys, decisions=_od_decisions,
                ceiling_ref=_od_ref, ceiling_subject_revision=_od_ceiling_subject,
                current_subject=_od_current, reaudit_after_close=False,
                unresolvable=bool(_od_res.get("unresolvable")),
                unresolvable_reason=_od_res.get("unresolvable_reason"),
                # T-14702 — an all-`fix` set binds the signature current at the pass where that
                # signature is recomputable here; `corpus_signature` admits no `fix` (refused at decide).
                plan_gate_fix_binds_at_pass=(_sig_field in ("content_hash", "card_set_fingerprint")),
                # ARM 2 (ancestry) is POST-ONLY by that helper's own contract and `stage` here is a
                # gate id, so it never runs; a content hash has no ancestry to answer about. The
                # callable is still supplied so the helper is never handed None on a path it could
                # reach — it fails closed on anything that is not True.
                strict_descendant=(lambda _a, _b: None))
            if _od_refusal:
                _od_refuse(_od_refusal["kind"], _od_refusal["why"], _od_refusal["message"],
                           {"ceiling_ref": _od_ref, "residual_count": len(_od_keys),
                            "decisions_applied": len(_od_by_fp),
                            **{k: v for k, v in _od_refusal.items()
                               if k not in ("kind", "why", "message")}})
            _od = {"ceiling_ref": _od_ref, "residual_keys": _od_keys, "by_fp": _od_by_fp,
                   "named": _od_named, "gate": gate_id,
                   "packet": audit_lib.on_decisions_projection(
                       tid=slug, stage=gate_id, ceiling_ref=_od_ref, residual_keys=_od_keys,
                       decisions_by_fp=_od_by_fp, degraded=_od_res.get("degraded"),
                       unresolvable=_od_res.get("unresolvable"), late=_od_res.get("late"),
                       named_revision=_od_named,
                       non_defect_rows_skipped=_od_res.get("non_defect_skipped"))}
            print(audit_lib.on_decisions_header(_od_ref, len(_od_by_fp), prior_passes + 1, _od_named,
                                                "T-12335, SPEC-0204 plan-gate arm", target="plan"),
                  file=sys.stderr)
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
                  f"strictly decreasing with no residual finding above medium for {slug} {template}; "
                  f"granting ONE bounded extra pass (pass {prior_passes + 1}) past the flat "
                  f"{AUDIT_PASS_CEILING}-pass cap (T-9717/T-13986, SPEC-1034 §Audit-loop ceiling).", file=sys.stderr)
        else:
            # T-11250 (<project> X-0974) — PRINT THE EXACT COMMAND, do not make the caller derive it.
            # This refusal is reached precisely when the caller is already blocked and under time
            # pressure. It used to prescribe «a converged plan consult + `--owner-reset`»; SPEC-0204's
            # plan-gate arm retires BOTH (T-12335), so it now prints the DECISION route — and, for a
            # DISPATCHED WORKER, the residual FINGERPRINTS the Controller has to decide, because a
            # halt that names no fingerprint makes the Controller re-derive them by hand (the task-arm
            # rule-6 lesson). The two identifiers stay told apart: `{template}` is the audit-RECORD's
            # name, `{gate_id}` is the value `--gate` takes (SPEC-0124 gate identity).
            _fps, _no_residual = _plan_gate_residual_keys(
                slug, gate_id, template, _od_stage_rows, prior, audit_path,
                REPO_ROOT=REPO_ROOT, DECISIONS_DIR=DECISIONS_DIR)
            if _worker_ref:
                _append_event("bg_dispatch_halted", None, {
                    "kind": "plan_gate_audit_ceiling", "plan_slug": slug, "gate": gate_id,
                    "template": template, "prior_passes": prior_passes,
                    "residual_fingerprints": _fps, "worker_ref": _worker_ref,
                    "pass_ceiling": AUDIT_PASS_CEILING})
            _die(f"{slug}: the next round at the {template} gate is decision-bounded ({prior_passes} "
                 f"passes on record in {audit_path.name}); a plan has NO pass-count ceiling, and pass "
                 f"{prior_passes + 1} runs on recorded decisions, not on a plain re-run — record one "
                 f"decision per open finding, then run `--on-decisions` (SPEC-1039 rule 9(f); no "
                 f"consult or owner reset, rule 6, plan-gate arm).\n"
                 + (f"RESIDUAL FINGERPRINT(S) of this gate's ceiling row ({len(_fps)}): "
                    f"{', '.join(_fps)}\n" if _fps else
                    "This gate's ceiling row names NO residual: there is nothing to decide, and the "
                    "next round is admitted with no decision — re-run this command with "
                    "`--on-decisions`.\n" if _no_residual else
                    "The residual fingerprints could not be resolved from this gate's ceiling row or "
                    "saved record — run the route below and it will name what is undecided.\n")
                 + _plan_gate_decision_route(slug, gate_id, template, keys=_fps)
                 + (("\nA DISPATCHED WORKER STOPS HERE too (SPEC-0103 §3): the halt row carries no "
                     "fingerprint because this row names no residual; the Controller re-runs this "
                     "command with `--on-decisions`." if _no_residual else
                     f"\nA DISPATCHED WORKER STOPS HERE: a Worker never decides past the ceiling "
                     f"(SPEC-0103 §3). The halt above names the fingerprints; the Controller records "
                     f"one decision per residual and re-dispatches.") if _worker_ref else ""))
    if admission_only:
        # T-13844 (public issue #78; SPEC-0204 rule 9(e)) — THE ADMISSION WITHOUT THE GATE-TEMPLATE
        # AUDITOR. The `finalization` gate is audited by the aggregate `audit post --plan` (its packet
        # is the plan's realization block; no gate template exists for it), so its rule-3 ADMISSION is
        # taken HERE — the ladder above, unchanged, with every refusal already made — and the admitted
        # context is handed back for that audit to run under. Nothing was invoked, recorded or spent
        # on this path. None when the call carried no `--on-decisions`.
        return _od
    tmpl = _plan_gate_template_text(template)
    #: The SPEC-0204 rule-3 extension keys of THIS pass's ceiling row, empty on every ordinary pass.
    #: Declared before `_save` closes over it and filled after the matrix runs, so the row is written
    #: ONCE with its decision trail rather than emitted twice or patched after the fact.
    _od_row_fields: dict = {}
    #: T-12857 — the auditor triple (SPEC-0135 §4) of THIS pass's row, filled once the auditor is
    #: resolved below; the carry / template-unavailable paths save before that and ran no auditor.
    _auditor_row_fields: dict = {}
    #: T-13619 — the prompt size of THIS pass, filled once the prompt is built; the template-unavailable
    #: save runs no auditor and records none.
    _prompt_size: dict = {}

    def _save(audit: dict) -> None:
        content = state.dump(audit)
        rt = state.load_str(content)
        if not isinstance(rt, dict) or rt.get("target_id") != slug or rt.get("target_kind") != "plan":
            _die("SPEC-0001 self-test failed: plan-gate audit YAML did not round-trip")
        write_text_atomic(audit_path, content)
        _dur = audit_lib._audit_duration_ms(_gate_t0)   # T-13574 — ONE reading for both rows below
        _append_event("draft_checked", None, {
            "slug": slug, "verdict": audit["verdict"], "findings_count": len(audit["findings"]),
            "stage_template": template, "gate_policy": gate_policy, "duration_ms": _dur,
            "saved_to": str(audit_path.relative_to(REPO_ROOT)), **_prompt_size})
        # ── C-A (T-12335) — THE CEILING ROW A PLAN GATE NEVER HAD ───────────────────────────────
        # Until now a plan gate emitted `draft_checked` ONLY: no `findings[]`, no `passes`, and never an
        # `external_audit_completed` row — so the whole SPEC-0204 rule-1/2/3 reader chain, which keys off
        # THAT row, had nothing to read for a plan target (deviation
        # `plan-gate-has-no-external-audit-completed-ceiling-row`, 2026-09-10). This is that row: the SAME
        # event type, the SAME ceiling-extension keys, `stage` = the GATE ID, per-finding fingerprints
        # from the SAME `finding_key_of` the reader recomputes — so the row and every reader agree BY
        # CONSTRUCTION rather than by two loops matching.
        #
        # `draft_checked` STAYS, unchanged: it is the plan FSM's own gate record and has its own readers.
        # This is an ADDITIONAL row for the ceiling axis, not a replacement (no reader is re-pointed).
        # A template mapping to no gate id emits NO row rather than an unkeyed one — fail-closed.
        if gate_id:
            _row = audit_lib.plan_gate_ceiling_row_payload(
                slug, gate_id, template, audit,
                saved_to=str(audit_path.relative_to(REPO_ROOT)), repo_root=[REPO_ROOT])
            _row.update(_auditor_row_fields)   # T-12857 — same triple as the task row
            _row["duration_ms"] = _dur         # T-13574 — REQUIRED on this row type (SPEC-0025)
            _row.update(_prompt_size)          # T-13619 — report-only prompt size
            if _od_row_fields:
                _row.update(_od_row_fields)
                # THE WRITE-SITE VALIDATOR (SPEC-0046 §A) — C1's shared validator, scoped to the keys
                # THIS site writes. An incomplete rule-3 extension would leave the pass unreadable to
                # the terminal check and to `audit decide`, so it is an ENGINE defect here, not
                # something a re-run fixes.
                _probs = audit_lib.on_decisions_row_problems(_row)
                if _probs:
                    _die(f"{slug} gate {gate_id}: REFUSED to record this pass — the SPEC-0204 rule-3 "
                         f"extension of the completion row is incomplete ({', '.join(_probs)}). The "
                         f"pass ran and its verdict record is on disk, but the JOURNAL ROW every "
                         f"cross-session reader folds would not carry the decision trail. This is an "
                         f"ENGINE defect at this write site: report it.")
            _append_event("external_audit_completed", None, _row)

    base = {"target_kind": "plan", "target_id": slug, "stage": template,
            "stage_template": template, "gate_policy": gate_policy,
            "date": _utc_now_iso()[:10], "content_hash": _plan_content_hash(body)}
    if card_set_fp is not None:
        # SPEC-0070 §4 — the decomposition-fidelity freshness basis: the verdict is bound to the CUT
        # (card-set fingerprint). `plan stage executing` recomputes + requires an EXACT match, so a cut
        # edited after the audit re-fingerprints → stale → re-audit. Only the gate-executing run passes it.
        base["card_set_fingerprint"] = card_set_fp
    # T-12335 (SPEC-0204 rule 6, plan-gate arm) — THE CONSULT-GOVERNED CARRY IS DELETED, not shimmed.
    # It recorded a plan-gate verdict VERBATIM from a converged ceiling-convergence consult, with no
    # auditor re-invocation, as the body of the `--owner-reset` continuation. Both the flag's basis and
    # the consult that produced it are retired above, so this branch had become unreachable — and dead
    # code that once wrote governed verdicts is worse than none: a later reader cannot tell it from a
    # live path. This deletion IS the removal this addition pays for (CHARTER §P1 filter 3). The flag
    # itself survives as the refusal shim in the ceiling block, which is what a pre-retirement caller
    # meets.
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
    # T-12606 (audit-post finding 1) — a tier's PRIMARY is a PAIR (model + effort), so the gate must
    # invoke it at the tier's own effort. Before this, the plan gates passed model alone and the
    # adapter used its provider default; once a reserve pair carries its effort, that asymmetry would
    # have meant the FALLBACK ran at the configured effort while the primary never did.
    effort = _resolve_audit_effort(True) if _resolve_audit_effort else None
    _auditor_row_fields.update(observe.auditor_triple(provider, model, effort))   # T-12857
    # T-14673 (SPEC-0034 §Plan-stage obligations) — the checklist of the obligations DUE at the stage
    # this gate judges, from the projection the session receives. An unavailable view refuses here,
    # before the auditor (the checkpoint pre-pass normally refused already).
    _obl_block = ""
    _obl_through = PLAN_GATE_OBLIGATIONS_THROUGH.get(template)
    if _plan_obligations is not None and _obl_through:
        _obl = _plan_obligations(_obl_through)
        if _obl.get("unavailable"):
            _die(f"{slug}: the {template} gate refused before the auditor — the plan-stage obligation view "
                 f"is unavailable: {'; '.join(_obl['unavailable'])}. No pass spent (SPEC-0034 "
                 f"§Plan-stage obligations); repair the named read, then re-run `yitc-v2 plan stage` "
                 f"for this plan.")
        _obl_block = _obl.get("block") or ""
    # T-14704 — an opted-in plan's registry rides the cut block (judged fields, left-out keys listed), so
    # the body shown at gate-executing points at it instead of repeating it. `body` stays the hash input.
    _shown_body = (_plan_body_registry_by_reference(body)
                   if template == "gate-executing" and _plan_is_prototype_opted_in(fm) else body)
    _engine_ctx = _plan_gate_engine_context(slug, audit_path.relative_to(REPO_ROOT), _plan_content_hash(body),
                                            _od["packet"] if _od is not None else None, bool(prior))
    prompt = (f"{_PLAN_AUDIT_LENS}"
              f"\n## Authoritative plan FSM\n{_plan_fsm_line()}\n"
              f"\n## Gate question template ({template} — {PLAN_GATE_TEMPLATE_SPEC}, "
              f"policy: {gate_policy})\n\nAnswer EACH question of the template against the plan "
              f"below; ground the verdict in them:\n\n{tmpl}\n"
              f"\n## Plan {slug}\n\nfrontmatter: {fm}\n\n{_shown_body}\n"
              + (f"\n## Decomposition — the filed task CARD SET (audit the CUT against the plan)\n"
                 f"{extra_context}\n" if extra_context else "")
              + _obl_block
              # C-C (T-12335) — on the rule-3 pass the auditor sees each residual, its fingerprint and
              # its recorded disposition, and is asked to VERIFY `fix`, treat `accept`/`defer` as
              # settled, and put `echo_of: <fp>` on any re-raise. Rendered by the SAME
              # `on_decisions_packet_block` the task packet uses — one block, one wording.
              + _engine_ctx)
    # T-14624 — the gate-executing RE-RUN after a RED carries the prior findings and asks for the
    # absorption sweep (SPEC-1040 §Absorption sweep). `prior` is the record read at entry; a no-data
    # ABORT never replaces a RED record (T-12739), so a RED -> ABORT -> re-run still shows the RED's
    # findings. The `--on-decisions` pass is skipped: its packet already lists every residual.
    if template == "gate-executing" and _od is None and str(prior.get("verdict") or "").upper() == "RED":
        _rows = []
        for _f in (prior.get("findings") or []):
            if isinstance(_f, dict):
                _rows.append(f"- [{_f.get('severity') or '?'}] {_f.get('what') or ''}"
                             + (f" (where: {_f.get('where')})" if _f.get("where") else ""))
            else:
                _rows.append(f"- {_f}")
        prompt += ("\n## Prior findings of this gate — the RED this pass re-runs after\n\n"
                   + ("\n".join(_rows) if _rows else "(the prior RED recorded no findings)")
                   + "\n\nAbsorption sweep (SPEC-1040 §Absorption sweep): for EACH finding above, was the "
                     "same defect class searched across the WHOLE cut — every card, `requires:` edge, "
                     "activation owner and closure probe — and fixed or recorded wherever it occurs, not "
                     "only at the card the finding named? Report each further instance of a prior "
                     "finding's class the cut still carries.\n")
    _prompt_size.update(_prompt_size_fields(prompt, plan_body=_shown_body, cut_cards=extra_context or ""))
    # T-14704 (X-2449) — the T-14528 budget, applied before the auditor: an input it cannot take is refused
    # here naming its parts largest-first; no record is written and no pass is spent (SPEC-1058 §3).
    if len(prompt) > _AUDITOR_INPUT_BUDGET:
        _parts = {"plan body": len(_shown_body), "cut cards and packet": len(extra_context or ""),
                  "plan-stage obligations": len(_obl_block), "engine context": len(_engine_ctx)}
        _parts["lens, template and the rest"] = len(prompt) - sum(_parts.values())
        _ranked = sorted(_parts.items(), key=lambda kv: -kv[1])
        _append_event("read_gate_refused", None, {
            "verb": "plan stage", "action": f"audit the {template} gate", "target_kind": "plan",
            "plan_slug": slug, "reason": "plan-gate-packet-exceeds-auditor-budget",
            "budget": _AUDITOR_INPUT_BUDGET, "prompt_chars": len(prompt), "parts": dict(_ranked)})
        _largest = ", ".join(f"{k} {n} chars" for k, n in _ranked)
        _die(f"{slug}: the {template} gate REFUSED before the auditor — its packet is {len(prompt)} chars "
             f"against the {_AUDITOR_INPUT_BUDGET}-char auditor budget; largest parts: {_largest}. No audit "
             f"pass was spent and the prior record is kept. Route: shrink the largest part (the plan body or "
             f"the cut cards), then re-run `yitc-v2 plan stage <next> {slug}` (T-14704 / SPEC-1058 §3).")
    print(f"# Invoking external auditor: {provider}/{model} (full) — {template} gate "
          f"({gate_policy}) on plan {slug}; {_auditor_guard_note(True)}...", file=sys.stderr)
    _answered_pair: dict = {}      # T-12606 — INVOCATION-scoped: which pair answered THIS gate audit
    _gate_t0 = time.monotonic()    # T-13574 — the prompt hand-off: the rows' duration anchor
    rc, stdout, stderr = audit_lib.invoke_auditor_tiered(
        _invoke_auditor, provider, prompt, model, full=True, effort=effort,   # T-12350 / T-12606
        _resolve_audit_reserve=_resolve_audit_reserve, append_event=_append_event,   # T-12606
        answered_out=_answered_pair, iter_events=_iter_events, events_path=EVENTS_PATH,   # T-13109
        breaker_rows=audit_lib._scope_breaker_rows(EVENTS_PATH, _iter_events))   # T-13298: the scope's window
    # T-13031 — the ceiling row names the pair that ANSWERED, not the configured primary.
    _auditor_row_fields.update(observe.auditor_triple(provider, model, effort, answered=_answered_pair))
    if rc != 0:
        # T-12739 — the cause through the ONE shared T-12582 extractor (tail-first: the provider's
        # terminal ERROR, never its startup banner) — this site still saved a bare `stderr[:500]`.
        verdict, findings = "ABORT", []
        parse_notes = audit_lib.auditor_failure_cause(rc, stderr, label=f"auditor ({provider})")
    else:
        verdict, findings, parse_notes = _parse_audit_verdict(stdout)
    # ── C-E (T-12335) — THE MALFORMED-RESPONSE PARSE FLOOR, PLAN-GATE ARM (SPEC-0204 rule 1) ────────
    # A response whose findings were scraped by the STAGE-3 RAW SINGLE-LINE BULLET fallback is refused
    # HERE — BEFORE `_save`, so `passes` in the record is UNCHANGED, NO record is written and NO ceiling
    # row is emitted. That ordering is the whole point: on 2026-09-09 (X-1330) a malformed RESPONSE
    # envelope consumed the SAME bounded budget as a real disagreement (4 invocations, ~10 min), because
    # the engine recorded `{severity, what: "<bullet text>"}` dicts that `parse_audit_verdict` itself
    # calls «likely misleading» as if they were findings. A parse failure is not a verdict about the
    # plan, so it must not cost a pass — and with no round recorded, the SPEC-0200-era
    # `malformed-exhausted` terminal that stranded both consumer plans becomes unreachable for a plan
    # gate (AC3; `plan_gate_live_terminal_reasons` is the conformance-visible half).
    #
    # The PREDICATE is pure and lives in audit.py; the REFUSAL is here, at the use site
    # (`lessons/fail-closed-belongs-to-the-reader-not-the-parser.md`). Stage-2 STRUCTURED recovery is
    # NOT malformed and is recorded unchanged, and a WELL-FORMED RED on the same fixture IS recorded and
    # DOES spend its pass — the differential arm of AC3.
    # T-12735 (<project> X-1494) — the SAME floor now reads the ONE union judgement
    # `unactionable_findings` (the raw-bullet arm above + the empty-narrative arm), worded and
    # journaled by the ONE helper the other two doors (`plan check`, `cmd_audit`) also read. The
    # `kind` / `reason` / `prior_passes` / gate fields the T-12335 test pins are unchanged.
    _malformed = audit_lib.unactionable_findings(findings, parse_notes)
    if _malformed:
        _payload, _msg = audit_lib.unactionable_findings_refusal(
            _malformed, findings_count=len(findings or ()), verb=f"{slug} {template} gate",
            stdout=stdout)
        _append_event("read_gate_refused", None, {
            "verb": f"plan stage ({template} gate)", "action": "record a plan-gate audit round",
            "target_kind": "plan", "plan_slug": slug,
            "gate": gate_id, "stage": gate_id, **_payload,
            "prior_passes": prior_passes, "findings_scraped": len(_malformed)})
        _die(f"{_msg} `passes` unchanged at {prior_passes}.")
    # T-13158 — a non-GREEN whose findings block did not parse is refused, never recorded with its
    # findings lost (the chartdesk 57ec009 0-of-27 YELLOW); passes unchanged.
    _uf = audit_lib.findings_block_parse_failure(verdict, findings, parse_notes, stdout if rc == 0 else "")
    if _uf:
        _payload, _msg = audit_lib.unparsed_findings_refusal(
            verdict, _uf, stdout=stdout, verb=f"{slug} {template} gate")
        _append_event("read_gate_refused", None, {
            "verb": f"plan stage ({template} gate)", "action": "record a plan-gate audit round",
            "target_kind": "plan", "plan_slug": slug,
            "gate": gate_id, "stage": gate_id, **_payload, "prior_passes": prior_passes})
        _die(f"{_msg} `passes` unchanged at {prior_passes}. Route: re-run `bin/yitc-v2 plan stage {slug} ...`.")
    # ── C-C (T-12335) — THE RULE-3 RESULT MATRIX, when this pass was admitted on decisions ──────────
    # The SAME closed matrix the task arm applies: an echo of an `accept`/`defer` residual is
    # `overruled_by_decision` and never a verdict driver; an echo of a `fix` residual still open forces
    # RED whatever word the auditor returned; anything else counts NEW at its own severity, with an
    # unverifiable `echo_of` DROPPED. No second matrix exists.
    if _od is not None:
        _m = audit_lib.on_decisions_matrix(
            findings, tid=slug, stage=gate_id, verdict=verdict,
            residual_keys=_od["residual_keys"], decisions_by_fp=_od["by_fp"],
            repo_root=[REPO_ROOT])
        findings = _m["findings"]
        if _m["verdict"] != verdict:
            parse_notes = ((parse_notes + " | " if parse_notes else "")
                           + f"SPEC-0204 rule 3 (plan-gate arm): the auditor returned {verdict}; this "
                           f"is the ON-DECISIONS pass on {_od['ceiling_ref']}, where "
                           f"{len(_m['overruled'])} finding(s) re-raised a residual an `accept`/`defer` "
                           f"decision had already settled (recorded `overruled_by_decision`, never "
                           f"verdict drivers) and {len(_m['fix_open'])} re-raised a `fix` residual "
                           f"still OPEN, so the recorded verdict is {_m['verdict']}.")
            verdict = _m["verdict"]
        if _m["dropped_echo"]:
            print(f"NOTE: {slug} gate {gate_id}: {len(_m['dropped_echo'])} `echo_of` reference(s) "
                  f"named no residual of {_od['ceiling_ref']} ({', '.join(_m['dropped_echo'])}) — "
                  f"DROPPED, and those findings count as NEW at their own severity (the ENGINE "
                  f"verifies `echo_of`).", file=sys.stderr)
        _od_row_fields.update({
            "basis": audit_lib.ON_DECISIONS_BASIS,
            "ceiling_ref": _od["ceiling_ref"],
            "decisions_applied": len(_od["by_fp"]),
            "overruled_by_decision": list(_m["overruled"]),
            "new_findings": len(_m["new"])})
    passes = prior_passes + (0 if verdict == "ABORT" else 1)   # ABORT burns no pass
    audit = {**base, "verdict": verdict, "passes": passes, "commit": None,
             "findings": findings, "absorbed": [], "followups": [],
             # T-9717 — durable marker: this pass was granted past the flat cap by the L2 trend grant
             # (the audit YAML analog of cmd_audit's trend_ceiling_grant, T-9682/T-9702).
             **({"trend_ceiling_grant": True} if _trend_ceiling_grant else {}),
             # T-12382 (audit-post finding AC2, 2026-09-11) — the saved gate-audit YAML is the
             # human-readable PROJECTION of the rule-3 extension the ceiling row carries (SPEC-0036
             # §Saved audit result: `basis` rides beside `ceiling_ref`), exactly as `cmd_audit`
             # projects its `on_decisions_yaml_fields` on the TASK arm. ONE dict feeds both writes, so
             # the record on disk and the journal row cannot disagree about the decision trail.
             **dict(_od_row_fields),
             "auditor_provider": "external-auditor-full", "prompt_excerpt": prompt[:200],
             "notes": parse_notes or f"Raw stdout captured ({len(stdout)} chars)."}
    if rc != 0:
        audit["notes"] = (f"{parse_notes}\n\n--- stdout tail ---\n"   # T-12739 — the T-12582 cause
                          f"{audit_lib.bounded_auditor_output(_strip_degenerate_tail(stdout))}")
    elif verdict in ("YELLOW", "RED") or not findings:
        _clean = _strip_degenerate_tail(stdout)
        audit["notes"] = f"{audit['notes']}\n\n--- stdout tail ---\n{audit_lib.bounded_auditor_output(_clean)}"
    # T-12350 (SPEC-0201 rule 2) — the ONE saved-verdict writer helper, on the branch that actually
    # invoked an auditor (the consult-governed carry and the template-unavailable ABORT above ran none).
    audit_lib.stamp_auditor_verdict(audit, provider=provider, model=model, full=True,
                                    target_kind="plan", target_id=slug, stage=template,
                                    append_event=_append_event, answered=_answered_pair)   # T-12606
    # ── T-12739 — A NO-VERDICT RUN NEVER REPLACES A REAL PRIOR RECORD (the cmd_plan_check sibling) ──
    # Same ONE predicate, resolved at call time. When it names a retained verdict, `_save` is NOT
    # called: no file write, no `external_audit_completed` ceiling row (a no-verdict run is not a pass
    # — the T-12335 parse floor's own reasoning), so the recorded `passes` + findings trail the
    # SPEC-0204 readers key on stays exactly what the last REAL pass left. The attempt is journaled on
    # `draft_checked` with the two additive keys; the blocking gate still HOLDS the transition below,
    # now naming the cause and resolve-then-re-run rather than a bare retry.
    _retained = audit_lib.no_data_abort_retains_prior(verdict, findings, prior)
    if _retained:
        _append_event("draft_checked", None, {
            "slug": slug, "verdict": verdict, "findings_count": 0,
            "stage_template": template, "gate_policy": gate_policy, "saved_to": None,
            "duration_ms": audit_lib._audit_duration_ms(_gate_t0),   # T-13574
            "no_data": True, "prior_verdict_retained": _retained, "cause": parse_notes,
            **_prompt_size})
        print(f"{slug} {template} gate ({gate_policy}): {verdict} (no verdict produced) -> "
              f"{audit_path.relative_to(REPO_ROOT)} NOT overwritten — prior {_retained} retained "
              f"(passes {prior_passes})")
        print(audit_lib.no_data_abort_note(f"{slug} {template} gate", parse_notes, _retained),
              file=sys.stderr)
        if blocking:
            _die(f"{slug}: the {template} gate is MANDATORY-BLOCKING and this run produced NO verdict "
                 f"— the transition is held (status unchanged); the prior {_retained} record is "
                 f"retained (no pass burned). Resolve the cause named above, THEN re-run.")
        return verdict
    _save(audit)
    print(f"{slug} {template} gate ({gate_policy}): {verdict} ({len(findings)} findings) -> "
          f"{audit_path.relative_to(REPO_ROOT)}")
    if blocking and verdict in ("RED", "ABORT"):
        _die(f"{slug}: the {template} gate is MANDATORY-BLOCKING and the verdict is {verdict} — "
             f"the transition is held (status unchanged). "
             + ((_plan_gate_red_note(slug, gate_id, template, audit, audit_path, _folded_events,
                                     AUDIT_PASS_CEILING=AUDIT_PASS_CEILING, REPO_ROOT=REPO_ROOT,
                                     DECISIONS_DIR=DECISIONS_DIR)
                 if _od is None else
                 f"This WAS the SPEC-0204 rule-3 pass on {_od['ceiling_ref']}; the plan-gate budget is "
                 f"{audit_lib.PLAN_GATE_BUDGET} (rule 9(f), T-12505), so this RED is the gate's NEW "
                 f"ceiling row, not a terminal. The next round runs only once EVERY residual of it "
                 f"carries a fresh decision:\n"
                 + _plan_gate_decision_route(slug, gate_id, template)
                 + f"\nOr end the plan by its own FSM terminal "
                 f"(`plan stage rejected|cancelled {slug} --reason …`, or the `partial` split).")
                if verdict == "RED"
                else "Auditor unavailable/malformed — don't proceed without a verdict; resolve the "
                     "cause recorded in the verdict note, THEN re-run (no pass burned; a blind re-run "
                     "against the same cause fails identically — CHARTER §P7, T-12739)."))
    return verdict


#: T-13272 — what a blocking plan-gate RED tells the reader to do next. A plan has NO pass-count
#: ceiling (owner ruling, patterns/methodology-lessons.md Lesson 11); the budget is decision-bounded
#: (SPEC-0204 rule 9(f), `audit.PLAN_GATE_BUDGET`). The TASK ceiling (2 + 1) is not a plan's.
PLAN_GATE_RED_RETRY_NOTE = (
    "Absorb the findings and re-run — a plan has NO pass-count ceiling "
    "(patterns/methodology-lessons.md Lesson 11); from the third round each round runs once every "
    "open finding carries a recorded decision (SPEC-0204 rule 9(f), budget: decision-bounded).")


def _plan_gate_residual_keys(slug, gate_id, template, stage_rows, record, audit_path, *,
                             REPO_ROOT, DECISIONS_DIR):
    """The open finding keys of a plan gate's ceiling row → `(keys, no_residual)` (T-14409).

    ONE reader for the two surfaces that print the decision route — the pass-2 RED note and the
    pass-3 plain-run refusal — so both name the SAME keys (moved verbatim out of the refusal). The
    journal ceiling row answers first; else the read-time SYNTHETIC row of the saved record
    (T-13860). Unresolvable or no gate id → `([], False)`: nothing is invented.

    Never raises past its own reads; a failing read yields `([], False)`."""
    if not gate_id:
        return [], False
    try:
        _ceil = audit_lib._ceiling_row_of(stage_rows) if stage_rows else None
        _ceil_record = None
        if _ceil is None and isinstance(record, dict) and record:
            _ceil_record = record
            _ceil = audit_lib.plan_gate_synthetic_ceiling_row(
                slug, gate_id, template, record,
                saved_to=str(audit_path.relative_to(REPO_ROOT)))
        if _ceil is None:
            return [], False
        _r = audit_lib.on_decisions_residuals(
            _ceil, stage_rows, slug, gate_id, repo_root=[REPO_ROOT],
            decisions_dir=DECISIONS_DIR, record=_ceil_record)
    except Exception:                       # noqa: BLE001 — a note never fails the verb
        return [], False
    if _r.get("unresolvable"):
        return [], False
    keys = list(_r.get("keys") or ())
    return keys, not keys


def _plan_gate_red_note(slug, gate_id, template, audit, audit_path, folded_events, *,
                        AUDIT_PASS_CEILING, REPO_ROOT, DECISIONS_DIR) -> str:
    """What a blocking plain-run plan-gate RED tells its reader to do next (T-14409, X-2157).

    Below the TASK pass count the reader absorbs and re-runs (`PLAN_GATE_RED_RETRY_NOTE`, unchanged).
    From that count on the NEXT round is decision-bounded (SPEC-1039 rule 9(f)), so the note LEADS
    with the decision step and prints the ready commands with this gate's open finding keys — the
    same keys and the same route the refused plain run prints."""
    try:
        passes = int((audit or {}).get("passes") or 0)
    except (TypeError, ValueError):
        passes = 0
    if passes < AUDIT_PASS_CEILING:
        return PLAN_GATE_RED_RETRY_NOTE
    rows = []
    if gate_id and folded_events is not None:
        try:
            rows = audit_lib._stage_audit_rows(list(folded_events()), slug, gate_id)
        except Exception:                   # noqa: BLE001 — fall back to the saved record alone
            rows = []
    keys, _none = _plan_gate_residual_keys(slug, gate_id, template, rows, audit, audit_path,
                                           REPO_ROOT=REPO_ROOT, DECISIONS_DIR=DECISIONS_DIR)
    return (f"This RED is pass {passes}: the next round at this gate is decision-bounded — it runs "
            f"once every open finding carries a recorded decision, not on a plain re-run (a plan "
            f"has NO pass-count ceiling; SPEC-1039 rule 9(f), patterns/methodology-lessons.md "
            f"Lesson 11). Next: record one decision per open finding, then run `--on-decisions`.\n"
            + ("" if keys else "The open finding keys could not be read here — the `--on-decisions` "
               "run names the undecided ones.\n")
            + _plan_gate_decision_route(slug, gate_id, template, keys=keys))


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
    # T-12828 (X-1532) — the SPEC-0204 rule 8 exhaustive-survey clause every task audit already carries,
    # REUSED from its one home (never copied), so one plan-check pass names every defect it can see.
    return (f"{_PLAN_AUDIT_LENS}{checklist}{template_block}{focus_block}{scenario_cue}"
            f"\n{audit_lib.BASE_PASS1_SURVEY_CLAUSE}"
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


def cmd_plan_check(args: argparse.Namespace, *, DECISIONS_DIR, PLANS_DIR, REPO_ROOT, _PLAN_CONSULT_GATE_AUDIT, _append_event, _build_draft_check_prompt, _die, _governing_contract_for, _invoke_auditor, _load_draft, _parse_audit_verdict, _plan_accept_freshness_hash, _plan_content_hash, _plan_gate_template_text, _plan_missing_checklist_pass_finding, _plan_scenario_fidelity, _plan_structural_findings, _read_yaml, _require_reads, _require_writing_worktree, _resolve_audit_effort=None, _resolve_audit_model, _resolve_audit_reserve=None, _resolve_audit_provider, _strip_degenerate_tail, _utc_now_iso, write_text_atomic, _iter_events=None, EVENTS_PATH=None, _is_consumer_build=None, _run_plan_checks=None, _plan_obligations=None) -> None:
    """Promote-gate verification (D-0034): run the external auditor on the draft, record the
    verdict to decisions/<slug>-audit.yaml. Does NOT change status (verification is an action,
    not а persisted state — it decays; take-into-work re-checks currency). No autosync/rebuild."""
    # T-11249 (<project> X-0970) — SAY WHICH CHECKOUT THIS VERDICT RESTS ON, before anything else.
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
    # T-12734 (X-1500): the flag is REPEATABLE — `audit_lib.absorb_texts` (the ONE home, resolved
    # through the module attribute at call time) normalizes None/str/list to an ordered list and
    # refuses any empty occurrence BEFORE a write, so the empty-text refusal stays one refusal, one
    # home, now list-aware. Presence (not truthiness) is still the branch: None = absent.
    absorb_texts = audit_lib.absorb_texts(getattr(args, "absorb", None), _die=_die)
    rnd = bool(getattr(args, "round", False))   # T-14628 — a ROUND (SPEC-0083 P4 round template)
    if absorb_texts is not None and rnd:
        _die(f"{slug}: --absorb records into the plain accept-gate verdict, and a round never writes or "
             f"reads that record — run `yitc-v2 plan check {slug} --absorb` without --round.")
    if absorb_texts is not None:
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
        # Per value, in order — one `absorbed:` entry + one emit each, exactly what N sequential
        # invocations would write (T-12734); the body-drift refusal above ran once for all of them.
        for _text in absorb_texts:
            audit_lib.absorb_into_plan_gate_record(
                slug, "trial-accepted", _text,
                decisions_dir=DECISIONS_DIR, repo_root=REPO_ROOT,
                gate_audit_map=_PLAN_CONSULT_GATE_AUDIT,
                _die=_die, _append_event=_append_event, _utc_now_iso=_utc_now_iso,
                write_text_atomic=write_text_atomic, _governing_contract_for=_governing_contract_for,
                invocation=f"yitc-v2 plan check {slug} --absorb",
                sweep=getattr(args, "sweep", None))      # T-13632
        print(f"note: the accept-gate verdict / content_hash / accept_freshness_hash are UNCHANGED — "
              f"`plan stage accepted` still accepts this record, and no ceiling pass was burned.")
        # T-13864 — hand the outcome line back instead of printing it here: the host wrapper prints it
        # LAST, after its report-only seam tail, so the call's final stdout line says the absorption
        # was recorded. This route prints no `AUDIT:` token (that grammar is `audit pre|post`'s).
        return (f"plan check {slug}: RECORDED {len(absorb_texts)} absorption(s) in "
                f"decisions/{audit_path.name} — the call succeeded; no check ran, no verdict this call.")
    # T-14672 (SPEC-0034 §Project-declared plan check) — phase `plan-check`, after the `--absorb`
    # field-edit branch (it runs no auditor and judges nothing) and BEFORE the provider, the template
    # and the auditor: the draft check, the accept gate, the trial gate and `--round` alike.
    if _run_plan_checks is not None:
        _run_plan_checks(path, "plan-check", slug, verb=f"plan check {slug}" + (" --round" if rnd else ""))
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
    effort = _resolve_audit_effort(full) if _resolve_audit_effort else None   # T-12606 — the PAIR's effort
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
    # T-14628 — a ROUND appends the P4 round template AFTER the stage template (never replacing it) and
    # writes its own numbered record; no round runs without its template.
    round_n = None
    if rnd:
        round_text = _plan_gate_template_text("plan-round")
        if round_text is None:
            _die(f"{slug}: the P4 round template is unavailable from {PLAN_GATE_TEMPLATE_SPEC} — a round "
                 f"without its scope field is not a round. Fix the template home, then re-run "
                 f"`yitc-v2 plan check {slug} --round`.")
        template_text = f"{template_text}\n\n{round_text}" if template_text else round_text
        stage_template = f"{stage_template}+plan-round"
        round_n = _plan_next_round_n(DECISIONS_DIR, slug)
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
    # T-14673 (SPEC-0034 §Plan-stage obligations) — every form of the check (draft check, accept gate,
    # trial gate, --round) lists the obligations due THROUGH the plan's current status, from the
    # projection the session receives; refused before the auditor on an unavailable view.
    if _plan_obligations is not None:
        _obl = _plan_obligations(status)
        if _obl.get("unavailable"):
            _die(f"{slug}: plan check refused before the auditor — the plan-stage obligation view is "
                 f"unavailable: {'; '.join(_obl['unavailable'])}. No pass spent (SPEC-0034 §Plan-stage "
                 f"obligations); repair the named read, then re-run `yitc-v2 plan check {slug}`.")
        prompt += _obl.get("block") or ""
    # T-14456 (SPEC-1058 §2-§3) — an opted-in plan's accept packet carries the base diff beside the
    # registry; a bad ref or a malformed list refuses HERE, before the auditor (no pass spent). A plan
    # without prototype_ref takes no branch: prompt and record stay byte-identical.
    proto_read = None
    proto_split = None   # T-14528 — [(label, prompt, paths, item ids)] when the check is split by surface
    if _plan_is_prototype_opted_in(fm):
        proto_read = _plan_prototype_read(REPO_ROOT, fm, body)
        if proto_read["fault"]:
            _append_event("read_gate_refused", None, {
                "verb": "plan check", "action": "audit the plan accept gate", "target_kind": "plan",
                "plan_slug": slug, "reason": "prototype-registry-fault", "fault": proto_read["fault"]})
            _die(f"{slug}: plan check refused before the auditor — the prototype carry registry: "
                 f"{proto_read['fault']} (SPEC-1058 §2). No pass spent; fix the plan, then re-run "
                 f"`yitc-v2 plan check {slug}`.")
        _base_prompt = prompt
        prompt += _plan_prototype_packet(REPO_ROOT, fm, body, proto_read)
        if len(prompt) > _AUDITOR_INPUT_BUDGET:
            # T-14528 — over budget after the reference rule: the per-surface SPLIT of the check
            # (owner events.jsonl#ts=2026-11-05T05:33:21Z), refused before the auditor only when the
            # subject cannot be split — sizes named, no pass spent (the T-12828 shape).
            _room = _AUDITOR_INPUT_BUDGET - len(_base_prompt)
            _whole = _plan_prototype_packet(REPO_ROOT, fm, body, proto_read, part="whole")
            _slices = []
            if len(_base_prompt) + len(_whole) > _AUDITOR_INPUT_BUDGET:
                _sfault = (f"the whole pass alone (the plan prompt {len(_base_prompt)} chars + the path "
                           f"list {len(_whole)} chars) exceeds the budget")
            else:
                _slices, _sfault = _plan_prototype_slices(proto_read, _room, fm)
            proto_split = []
            if not _sfault:
                _n = len(_slices)
                proto_split = [(f"{k}/{_n} ({lab})", _base_prompt + _plan_prototype_packet(
                    REPO_ROOT, fm, body, proto_read, entries=es, part=f"{k}/{_n}", items=its),
                    [e["path"] for e in es], [str(it.get("id")) for it in its])
                    for k, (lab, es, its) in enumerate(_slices, 1)]
                proto_split.append(("whole pass", _base_prompt + _whole,
                                    [e["path"] for e in proto_read.get("entries") or []],
                                    [str(it.get("id")) for it in proto_read.get("items") or []]))
                # fail closed: EVERY prompt actually sent is measured, never only the packing estimate
                _over = [(lab, len(pp)) for lab, pp, _a, _b in proto_split if len(pp) > _AUDITOR_INPUT_BUDGET]
                if _over:
                    _sfault = "part(s) " + ", ".join(f"{lab} = {n} chars" for lab, n in _over) + \
                              " still exceed the budget after slicing"
            if _sfault:
                _append_event("read_gate_refused", None, {
                    "verb": "plan check", "action": "audit the plan accept gate", "target_kind": "plan",
                    "plan_slug": slug, "reason": "prototype-packet-exceeds-auditor-budget",
                    "budget": _AUDITOR_INPUT_BUDGET, "prompt_chars": len(prompt),
                    "base_prompt_chars": len(_base_prompt), "fault": _sfault})
                _die(f"{slug}: plan check REFUSED before the auditor — the accept packet is "
                     f"{len(prompt)} chars against the {_AUDITOR_INPUT_BUDGET}-char auditor budget "
                     f"(plan prompt {len(_base_prompt)}, prototype packet {len(prompt) - len(_base_prompt)}) "
                     f"after the send-by-reference rule, and the check cannot be split by surface: "
                     f"{_sfault}. No audit pass was spent. Route: shrink that file in the prototype or "
                     f"the plan body, then re-run `yitc-v2 plan check {slug}` (T-14528 / SPEC-1058 §3).")
            prompt = proto_split[0][1]
    prompt_excerpt = prompt[:200]   # opens at the fixed lens — the focus block is unreachable (T-0350 F3)
    # T-12828 (X-1529) — REFUSE before the auditor when the block cannot carry its whole subject (a draft
    # over its pool, or a related comparand that no longer fits): no pass spent, sizes named.
    _overflow = _plan_draft_pool_overflow(coverage)
    if _overflow:
        _append_event("read_gate_refused", None, {
            "verb": "plan check", "action": "audit the plan accept gate", "target_kind": "plan",
            "plan_slug": slug, "reason": "draft-specs-exceed-corpus-budget"})
        _die(_overflow)
    print(f"# Invoking external auditor: {provider}/{model} ({'full' if full else 'routine'}) "
          f"on draft {slug} ({n_lines} body lines{'; LARGE → big-plan-checklist' if large else ''}); "
          f"{_auditor_guard_note(full)}...", file=sys.stderr)
    # T-0226 — structural pre-pass: deterministic, local, REPORT-NOT-BLOCK. Computed regardless of
    # the auditor outcome (even on ABORT) so the grep-able subset is ALWAYS recorded + cannot be
    # skipped like the T-0188 manual memo. WARN-level: does NOT flip the auditor `verdict`.
    structural = _plan_structural_findings(slug, body, fm=fm, events_path=EVENTS_PATH)
    # T-0320 — LARGE-plan `checklist_pass`-presence WARN (SPEC-0034 mandatory big-plan check); LARGE-only,
    # so gated here where `large` is known. Same report-not-block shape — flows untouched into the verdict.
    structural += _plan_missing_checklist_pass_finding(large, body)
    # SPEC-0082 — the malformed/overlap/unresolved findings ride the report-not-block structural bucket;
    # the baseline-fidelity MEDIUM findings are kept separate (they CONTRIBUTE the verdict).
    if sf:
        structural += sf["structural"]
    _answered_pair: dict = {}      # T-12606 — INVOCATION-scoped: which pair answered THIS gate audit
    _check_t0 = time.monotonic()   # T-13574 — the prompt hand-off: the row's duration anchor
    def _ask(_p, _answered=_answered_pair):
        return audit_lib.invoke_auditor_tiered(
            _invoke_auditor, provider, _p, model, full=full, effort=effort,   # T-12350 / T-12606
            _resolve_audit_reserve=_resolve_audit_reserve, append_event=_append_event,   # T-12606
            answered_out=_answered, iter_events=_iter_events, events_path=EVENTS_PATH)   # T-13109
    slice_records = None
    if proto_split:
        # T-14528 — one auditor call per surface slice, then the whole pass; ONE verdict: the worst
        # (an ABORT anywhere is the run's ABORT; GREEN only when every part is GREEN).
        # T-14612 — the parts run CONCURRENTLY (bounded by lib.plan.PLAN_CHECK_SLICE_WORKERS; 1 = one
        # after another), each with its OWN answered pair (SPEC-0202 rule 6 is per invocation), and are
        # folded in PART order whatever the completion order; every part is recorded, an aborted one too.
        rc, stdout, stderr, verdict, findings, parse_notes = 0, "", "", "GREEN", [], ""
        slice_records, _outs, _notes = [], [], []
        _rank = {"GREEN": 0, "YELLOW": 1, "RED": 2, "ABORT": 3}

        # T-14675 — the bounded fan-out is ONE helper shared with the split aggregate `audit post --plan`
        # (`audit.run_auditor_parts`), fed this module's LIVE constant as its default.
        _results = audit_lib.run_auditor_parts([_p for _lab, _p, _paths, _ids in proto_split], _ask,
                                               PLAN_CHECK_SLICE_WORKERS)
        _primary_ans = _reserve_ans = None
        for (_lab, _p, _paths, _ids), ((_rc, _out, _err), _ans, _at, _dur) in zip(proto_split, _results):
            _outs.append(f"### check part {_lab}\n{_out}")
            _answered = ({k: _ans.get(k) for k in ("pair", "model", "effort")}
                         if _ans.get("pair") else None)
            _rec = {"part": _lab, "paths": _paths, "items": _ids, "started_at": _at,
                    "duration_s": _dur, "answered": _answered}
            if _ans.get("pair") == "reserve" and _reserve_ans is None:
                _reserve_ans = _ans
            elif _ans.get("pair") and _primary_ans is None:
                _primary_ans = _ans
            if _rc != 0:
                _cause = audit_lib.auditor_failure_cause(_rc, _err, label=f"auditor ({provider}) on part {_lab}")
                if rc == 0:   # the FIRST failing part in part order names the run's cause
                    rc, stderr, parse_notes = _rc, _err, _cause
                slice_records.append({**_rec, "verdict": "ABORT", "cause": _cause})
                continue
            _v, _f, _n2 = _parse_audit_verdict(_out)
            for _fi in _f or []:
                if isinstance(_fi, dict):
                    _fi.setdefault("slice", _lab)
            findings += list(_f or [])
            if _n2:
                _notes.append(f"[{_lab}] {_n2}")
            slice_records.append({**_rec, "verdict": _v, "findings": len(_f or [])})
            if _rank.get(_v, 3) > _rank.get(verdict, 3):
                verdict = _v if _v in _rank else "ABORT"
        # the record-level stamp names the reserve when ANY part was answered by it, else the primary
        _answered_pair.clear()
        _answered_pair.update(_reserve_ans or _primary_ans or {})
        stdout = "\n\n".join(_outs)
        if rc != 0:
            verdict, findings = "ABORT", []
        else:
            parse_notes = "\n".join(_notes)
    else:
        rc, stdout, stderr = _ask(prompt)
    if slice_records is not None:
        pass   # the split run above already set verdict / findings / parse_notes
    elif rc != 0:
        # T-12739 — the cause through the ONE shared T-12582 extractor (tail-first: the provider's
        # terminal ERROR, never its startup banner), the last plan-gate site still saving `stderr[:500]`.
        verdict, findings = "ABORT", []
        parse_notes = audit_lib.auditor_failure_cause(rc, stderr, label=f"auditor ({provider})")
    else:
        verdict, findings, parse_notes = _parse_audit_verdict(stdout)
    # ── T-12735 (<project> X-1494) — THE UNACTIONABLE-RESPONSE FLOOR, `plan check` door ─────────────
    # This verb had NO parse floor: the T-12335 arm covered the `plan stage` gates only, so on
    # 2026-09-18T13:57Z `plan check` wrote a RED whose four findings were the stage-3 scrape of the
    # auditor's own `- severity: RED` lines (`{severity: unknown, what: "severity: RED"}`) — bodies
    # alive only in `notes:`, the record unactionable to every downstream reader. Refused HERE, BEFORE
    # the audit dict is built or written, through the ONE judgement + the ONE refusal shape the other
    # two doors read (`audit_lib.unactionable_findings` / `unactionable_findings_refusal`, resolved
    # through the module attribute at call time — never a copy). `plan check` keeps no pass counter,
    # so "no pass spent" is trivially true; what it protects is the RECORD. Verdict-agnostic, as the
    # plan-gate arm is. The PREDICATE is pure and lives in audit.py; the REFUSAL is the use site's
    # (`lessons/fail-closed-belongs-to-the-reader-not-the-parser.md`).
    _unactionable = audit_lib.unactionable_findings(findings, parse_notes)
    if _unactionable:
        _payload, _msg = audit_lib.unactionable_findings_refusal(
            _unactionable, findings_count=len(findings or ()), verb=f"{slug} plan-check",
            stdout=stdout)
        _append_event("read_gate_refused", None, {
            "verb": "plan check", "action": "record a plan-check verdict",
            "target_kind": "plan", "plan_slug": slug, "stage": stage_template,
            "stage_template": stage_template, **_payload})
        _die(_msg)
    _uf = audit_lib.findings_block_parse_failure(verdict, findings, parse_notes, stdout if rc == 0 else "")
    if _uf:   # T-13158 — no plan-check record with the findings lost
        _payload, _msg = audit_lib.unparsed_findings_refusal(
            verdict, _uf, stdout=stdout, verb=f"{slug} plan-check")
        _append_event("read_gate_refused", None, {
            "verb": "plan check", "action": "record a plan-check verdict",
            "target_kind": "plan", "plan_slug": slug, "stage": stage_template,
            "stage_template": stage_template, **_payload})
        _die(f"{_msg} Route: re-run `bin/yitc-v2 plan check {slug}`.")
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
    # T-14627 (SPEC-1061 §1) — the per-input digests of the SAME hash, so a change check from this
    # anchor can tell an eligible input from one that needs a fresh anchor.
    # T-14628 — a round's verdict is read from its plan-scope findings only, over the FINAL findings
    # list; the two whole-plan escalations above (scenario fidelity, corpus coverage) are plan scope
    # by definition and still lift GREEN to YELLOW. ABORT stays ABORT.
    if round_n is not None:
        _round_verdict = _plan_round_verdict(findings)   # stamps scope on every finding, ABORT included
        if rc == 0 and verdict != "ABORT":
            verdict = _round_verdict
            if verdict == "GREEN" and ((sf and sf["medium"]) or corpus_coverage):
                verdict = "YELLOW"
    accept_parts: dict = {}
    accept_hash = _plan_accept_freshness_hash(slug, body, fm, sf=sf, parts_out=accept_parts)
    audit = {
        "target_kind": "plan", "target_id": slug,
        "stage": stage_template, "stage_template": stage_template, "gate_policy": gate_policy,
        "date": _utc_now_iso()[:10],
        "verdict": verdict, "content_hash": _plan_content_hash(body),
        # T-0332 — accept-gate freshness over the plan body + the PLAN-BORN draft specs + the
        # active+proposed corpus CONTENT; `_plan_accept_core` recomputes + compares so editing a
        # draft spec OR a corpus spec after this check stales the accept gate (AC2).
        "accept_freshness_hash": accept_hash, "accept_freshness_parts": accept_parts,
        "large": large, "big_plan_checklist": large,
        "findings": findings, "structural_findings": structural, "absorbed": [], "followups": [],
        "auditor_provider": "external-auditor-full" if full else "external-auditor-routine",
        "prompt_excerpt": prompt_excerpt,
        "notes": parse_notes or f"Raw stdout captured ({len(stdout)} chars).",
    }
    # SPEC-0082 — record the scenario-fidelity result ONLY when the dimension applied (sf is not None);
    # a no/empty-scenario_roles plan gets NO key → the verdict YAML is byte-identical to pre-dimension
    # output (the strict negative invariant, AC1 / T-9268 case 3).
    if round_n is not None:
        audit["round"] = round_n
    if sf is not None:
        audit["scenario_fidelity_findings"] = sf["medium"] + sf["structural"]
    # T-10917 — additive ONLY on a shortfall: the key's very PRESENCE is the honest signal that this
    # verdict rests on a partial read; a full-reach gate writes no key (AC2 byte-identity).
    if corpus_coverage:
        audit["corpus_coverage"] = corpus_coverage
    # T-14456 — the prototype + base commits THIS packet carried; `plan stage accepted` pins exactly them.
    if proto_read is not None:
        audit["prototype_commit"] = proto_read["tip"]
        audit["prototype_base"] = proto_read["base"]
    if slice_records is not None:   # T-14528 — only a split check carries the key
        audit["prototype_check_slices"] = slice_records
        # T-14629 — the themes fold, AFTER every verdict above is final (computed from the raw
        # findings' own pairs); additive, and only when there is something to fold.
        if findings:
            audit["themes"] = _plan_fold_themes(findings)
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
        audit["notes"] = f"{parse_notes}\n\n--- stdout tail ---\n{audit_lib.bounded_auditor_output(_strip_degenerate_tail(stdout))}"   # T-12739 — the T-12582 cause, not stderr[:500]
    elif verdict in ("YELLOW", "RED") or not findings:
        _clean = _strip_degenerate_tail(stdout)
        tail = audit_lib.bounded_auditor_output(_clean)   # T-13158 — full bounded output, not a 2000-char tail
        audit["notes"] = f"{audit['notes']}\n\n--- stdout tail ---\n{tail}"
    # T-0350 (SPEC-0036 --focus): `notes` IS the single VERBATIM carrier of the appended focus text
    # (full text, byte-equal); appended as the LAST notes mutation so no tail interleaves into it.
    if focus:
        audit["notes"] = f"{audit['notes']}\n\n--- focus (verbatim, SPEC-0036 --focus) ---\n{focus}"
    # T-12350 (SPEC-0201 rule 2) — the ONE saved-verdict writer helper: stamp + same-provider row.
    audit_lib.stamp_auditor_verdict(audit, provider=provider, model=model, full=full,
                                    target_kind="plan", target_id=slug, stage=stage_template,
                                    append_event=_append_event, answered=_answered_pair)   # T-12606
    content = state.dump(audit)
    try:
        rt = state.load_str(content)
        if not isinstance(rt, dict) or rt.get("target_id") != slug or rt.get("target_kind") != "plan":
            _die("SPEC-0001 self-test failed: plan-check audit YAML did not round-trip")
    except yaml.YAMLError as e:
        _die(f"SPEC-0001 self-test failed: {e}")
    audit_path = DECISIONS_DIR / (f"{slug}-audit-round-{round_n}.yaml" if round_n is not None
                                  else f"{slug}-audit.yaml")
    # ── T-12739 (<project> X-1495 / X-1496) — A NO-VERDICT RUN NEVER REPLACES A REAL PRIOR RECORD ────
    # `plan stage accepted` reads THIS FILE (GREEN/YELLOW + fresh). Saving a no-data ABORT over a real
    # verdict left the plan unable to advance until a re-run answered — the CHARTER §P7 freeze shape,
    # and the first diagnosis prescribed exactly that blind re-run. The judgement is homed ONCE in
    # `audit_lib.no_data_abort_retains_prior` (SPEC-0173 rule 1's persistence corollary), resolved at
    # call time — the same predicate `_run_plan_gate_audit` reads. When it names a retained verdict the
    # file is left byte-identical (its freshness is still the gate's call), the attempt is journaled on
    # the SAME `draft_checked` row with the two additive keys, and the surfaced note names the CAUSE +
    # resolve-then-re-run. Absent prior / prior itself no-data / an ABORT WITH findings → unchanged.
    _prior_rec = (_read_yaml(audit_path) or {}) if audit_path.exists() else {}
    _retained = audit_lib.no_data_abort_retains_prior(verdict, findings, _prior_rec)
    _dc_row = {"slug": slug, "verdict": verdict,
               "findings_count": len(findings),
               "structural_findings_count": len(structural), "large": large,
               "stage_template": stage_template, "gate_policy": gate_policy,
               "duration_ms": audit_lib._audit_duration_ms(_check_t0),   # T-13574
               "saved_to": str(audit_path.relative_to(REPO_ROOT)),
               # T-13619 — report-only; the corpus block (PLAN-BORN draft specs + comparands) is
               # measured by its own builder into the reach sink
               **_prompt_size_fields(prompt, plan_body=body,
                                     corpus_bytes=coverage.get("block_bytes", 0))}
    if round_n is not None:
        _dc_row["round"] = round_n
    if audit.get("themes"):   # T-14629 — additive; findings_count stays the raw count
        _dc_row["themes_count"] = len(audit["themes"])
    if _retained:
        _dc_row.update({"no_data": True, "prior_verdict_retained": _retained, "saved_to": None,
                        "cause": parse_notes})
    else:
        write_text_atomic(audit_path, content)
    _append_event("draft_checked", None, _dc_row)
    if _retained:
        print(f"{slug} plan-check [{stage_template}]: {verdict} (no verdict produced) -> "
              f"{audit_path.relative_to(REPO_ROOT)} NOT overwritten — prior {_retained} retained")
    else:
        _unit, _n = _plan_record_count(audit)   # T-14629 — by theme when the record carries themes
        _count = (f"{_n} themes ({len(findings)} findings)" if _unit == "theme"
                  else f"{len(findings)} findings")
        print(f"{slug} plan-check [{stage_template}]: {verdict} ({_count}) -> "
              f"{audit_path.relative_to(REPO_ROOT)}")
        for _t in audit.get("themes") or []:   # the fix brief: themes seen in more than one finding
            if len(_t["members"]) < 2:
                continue
            _mx = ", ".join(f"{k}: {v}" for k, v in sorted(_t["max_severity"].items()))
            print(f"  {_t['id']} ({len(_t['members'])} findings; max {_mx}; units: "
                  f"{'; '.join(str(u) for u in _t['units'])})")
            for _m in _t["members"]:
                print(f"    - [{_m['part']}] {_m['severity']}/{_m['scope']}: {_m['what']}")
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
    if round_n is not None:
        print(f"note: round {round_n} is recorded under its own name and never admits the plan — "
              f"`plan stage accepted` reads only the plain `plan check` record (SPEC-0083 P4 round).")
    else:
        print("note: `check` records a verdict + content hash; it does NOT change status (verification "
              "decays — re-checked at take-into-work). `plan stage accepted` requires this verdict GREEN/YELLOW + fresh.")
    if timeout_abort:
        # T-11299 (X-0999) — the ONE class where the `rework` line below is actively misleading: nothing
        # was judged, so there is nothing to rework. RENDER + MARKER ONLY — the control flow is unchanged
        # (the verdict stays ABORT, the plan stays `draft`, `plan stage accepted` still refuses on it);
        # what changes is that the reader learns the cause is a configuration value rather than a stop.
        print(audit_lib.timeout_abort_note(f"{slug} plan-check",
                                           f"yitc-v2 plan check {slug}",   # T-13162: the full wall
                                           audit_lib.AUDIT_FULL_CONSULT_CLASS if full else None),
              file=sys.stderr)
    elif _retained:
        # T-12739 — nothing was judged and the prior record stands: the `rework` line would prescribe
        # work on content no one judged, and a bare `retry` would be the P7 blind re-run.
        print(audit_lib.no_data_abort_note(f"{slug} plan-check", parse_notes, _retained),
              file=sys.stderr)
    elif verdict in ("RED", "ABORT"):
        print(f"# {verdict} — keep status: draft and rework (D-0034 accept-gate).", file=sys.stderr)
        if verdict == "RED":
            # T-14627 (SPEC-1061 §1, SPEC-1037 §8) — a cue and a pointer, never the recipe;
            # T-14628 — after a RED ROUND the cue points at SPEC-0083's P4 round template instead.
            _cue = _plan_red_round_cue if round_n is not None else _plan_red_anchor_cue
            print(_cue(is_consumer=bool(_is_consumer_build and _is_consumer_build())), file=sys.stderr)


# T-14627 (SPEC-1061) — the next step `plan check` names after a RED anchor: the discipline and its
# one home, never its steps (SPEC-1037 §8 — an authoring aid carries a cue + a pointer only).
def _plan_red_anchor_cue(*, is_consumer: bool = False) -> str:
    """The cue line; its pointer is rendered for the session's realm through the one shared
    `graph.spec_query_hint` (`--kernel` under `-C`: SPEC-1061 is a kernel spec, SPEC-0092)."""
    return ("# next step after a RED anchor: the change check from this anchor, not another full pass — "
            f"SPEC-1061 §2 (`{graph_lib.spec_query_hint('SPEC-1061', is_consumer=is_consumer, cli='yitc-v2')}`).")


# T-14628 (SPEC-0083 P4 round) — the round helpers: the cue after a RED round, the round number, the
# plan-scope verdict. The round rule itself lives in SPEC-0083; these carry no rule text.
def _plan_red_round_cue(*, is_consumer: bool = False) -> str:
    return ("# next step after a RED round: what SPEC-0083's P4 round template says comes between rounds "
            f"(`{graph_lib.spec_query_hint('SPEC-0083', is_consumer=is_consumer, cli='yitc-v2')}`, "
            "block «P4 round»).")


def _plan_next_round_n(decisions_dir, slug: str) -> int:
    """1 + the highest N among decisions/<slug>-audit-round-<N>.yaml (gaps and odd names ignored)."""
    pat = re.compile(rf"^{re.escape(slug)}-audit-round-(\d+)\.yaml$")
    ns = [int(m.group(1)) for p in Path(decisions_dir).glob(f"{slug}-audit-round-*.yaml")
          if (m := pat.match(p.name))]
    return max(ns, default=0) + 1


def _plan_round_verdict(findings: list) -> str:
    """Stamp `scope` (plan|card; absent or unknown -> plan) on every finding IN PLACE and return the
    round verdict from the plan-scope ones: none -> GREEN, all low/info -> YELLOW, else RED."""
    plan_sev = []
    for f in findings or []:
        if not isinstance(f, dict):
            plan_sev.append("")
            continue
        sc = str(f.get("scope") or "").strip().lower()
        f["scope"] = sc if sc in ("plan", "card") else "plan"
        if f["scope"] == "plan":
            plan_sev.append(str(f.get("severity") or "").strip().lower())
    if not plan_sev:
        return "GREEN"
    return "YELLOW" if all(s in ("low", "info") for s in plan_sev) else "RED"


# T-14629 (SPEC-1040 §Saved audit result, `themes:`) — a split check's findings folded into THEMES.
# A view over the findings list: it copies fields, never mutates a finding, and no verdict reads it.
PLAN_THEME_TEXT_RATIO = 0.6
_PLAN_SEV_RANK = {"info": 1, "low": 2, "medium": 3, "high": 4, "critical": 5}


def _plan_theme_refs(where) -> tuple:
    """The normalized reference set of a finding's `where`: split on , and ; — stripped, lower-cased,
    whitespace collapsed, sorted (so spelling case and order do not separate one reference set)."""
    parts = re.split(r"[;,]", str(where or ""))
    return tuple(sorted({" ".join(p.split()).lower() for p in parts if p.strip()}))


def _plan_fold_themes(findings: list) -> list:
    """Fold findings into themes: same reference set + `what` similar (difflib ratio >=
    PLAN_THEME_TEXT_RATIO) to the theme's FIRST member. List order, so a repeat run is identical.
    Each member keeps its own (severity, scope, unit) pair; `max_severity` is per scope; `units` is
    the union. Non-dict findings are not folded."""
    import difflib   # noqa: PLC0415 — the module's local-import convention
    themes: list = []
    firsts: list = []   # (refs, normalized what of the first member) per theme
    for i, f in enumerate(findings or []):
        if not isinstance(f, dict):
            continue
        refs = _plan_theme_refs(f.get("where"))
        what = str(f.get("what") or "")
        norm = " ".join(what.split()).lower()
        sc = str(f.get("scope") or "").strip().lower()
        sc = sc if sc in ("plan", "card") else "plan"
        sev = str(f.get("severity") or "").strip().lower()
        member = {"ref": i, "part": f.get("slice"), "severity": f.get("severity"), "scope": sc,
                  "unit": f.get("where"), "what": what}
        hit = None
        for t_i, (t_refs, t_norm) in enumerate(firsts):
            if t_refs == refs and difflib.SequenceMatcher(None, t_norm, norm).ratio() >= PLAN_THEME_TEXT_RATIO:
                hit = t_i
                break
        if hit is None:
            firsts.append((refs, norm))
            themes.append({"id": f"TH-{len(themes) + 1}", "where": list(refs), "members": [],
                           "max_severity": {}, "units": []})
            hit = len(themes) - 1
        t = themes[hit]
        t["members"].append(member)
        cur = t["max_severity"].get(sc)
        if cur is None or _PLAN_SEV_RANK.get(sev, 0) > _PLAN_SEV_RANK.get(str(cur).strip().lower(), 0):
            t["max_severity"][sc] = f.get("severity")
        unit = f.get("where")
        if unit not in (None, "") and unit not in t["units"]:
            t["units"].append(unit)
    for t in themes:
        t["units"] = sorted(t["units"], key=str)
    return themes


def _plan_record_count(rec: dict) -> tuple:
    """The ONE reading rule for a plan-check record's count: ("theme", n) when `themes` is a non-empty
    list, else ("finding", len(findings))."""
    th = (rec or {}).get("themes")
    if isinstance(th, list) and th:
        return "theme", len(th)
    return "finding", len((rec or {}).get("findings") or [])


PLAN_CHANGE_CHECK_SUFFIX = "-change-check"   # decisions/<slug>-change-check-audit-adhoc.yaml (SPEC-1061 §2)


def _plan_change_check_path(slug: str, DECISIONS_DIR) -> Path:
    """The ONE record of a plan's latest change check (SPEC-1061 §2): every run replaces it."""
    return Path(DECISIONS_DIR) / f"{slug}{PLAN_CHANGE_CHECK_SUFFIX}-audit-adhoc.yaml"


def _plan_anchor_highs(av: dict) -> list:
    """The anchor's HIGHS as (id, finding): `A<n>` by 1-based finding position, severity `high` read
    alone (SPEC-1061 §1)."""
    return [(f"A{i}", f) for i, f in enumerate((av or {}).get("findings") or [], 1)
            if isinstance(f, dict) and str(f.get("severity") or "").strip().lower() == "high"]


def _plan_findings_digest(findings) -> str:
    """Digest of an anchor's findings — binds a change check to THIS anchor, not to a later
    `plan check` over the same text (same hashes, other findings)."""
    return hashlib.sha256(state.dump(list(findings or [])).encode("utf-8")).hexdigest()


# SPEC-1061 §1 — an anchor is a COMPLETED full pass: a judged verdict. An ABORT (or a missing verdict)
# judged nothing, so no change check starts from it and none admits from it.
_PLAN_ANCHOR_JUDGED = ("GREEN", "YELLOW", "RED")

# SPEC-1061 §2 — the inputs a change check may NOT carry: each needs a fresh anchor.
_PLAN_NOT_ELIGIBLE = (
    ("corpus", "an active or proposed spec of the corpus outside the plan changed"),
    ("prototype", "the prototype pair (prototype_tip) changed"),
    ("scenario", "the scenario-fidelity slice changed"),
    # T-14673 (SPEC-0034 §Plan-stage obligations) — a plan-stage rule due at this boundary was added,
    # changed or activated: the anchor never judged it.
    ("obligations", "a plan-stage obligation due at this boundary changed (a bound rule was added, "
                    "edited or activated)"),
)


def _plan_not_eligible_changes(anchor_parts: dict, cur_parts: dict) -> list:
    a, c = anchor_parts or {}, cur_parts or {}
    out = []
    for key, why in _PLAN_NOT_ELIGIBLE:
        if a.get(key) == c.get(key):
            continue
        a_specs, c_specs = a.get("obligation_specs"), c.get("obligation_specs")
        if key == "obligations" and isinstance(a_specs, dict) and isinstance(c_specs, dict):
            # T-14697 — name each due spec whose normative digest moved (or that became / stopped being due)
            moved = sorted(k for k in set(a_specs) | set(c_specs) if a_specs.get(k) != c_specs.get(k))
            if moved:
                out += [f"the normative part (status or rule text) of {k.split(' ', 1)[-1]} "
                        f"({k.split(' ', 1)[0]}), a plan-stage obligation due at this boundary, changed "
                        f"(it was added, edited or activated)" for k in moved]
                continue
        out.append(why)
    return out


def _plan_change_check_admission(slug: str, av: dict, *, current: dict, cur_parts: "dict | None" = None,
                                 DECISIONS_DIR, _read_yaml) -> tuple:
    """SPEC-1061 §3 arm (ii) — the ONE reader the accept gate, the decomposition entry and the cut
    check share. `current` maps each hash THAT gate reads (`content_hash`, and `accept_freshness_hash`
    at the accept gate) to its current value; `cur_parts`, when given with an anchor that recorded its
    parts, adds the not-eligible check. Returns (admission, "") when the latest change check admits,
    (None, reason) when it does not, and (None, "") when no change check is on record — the caller then
    keeps its own refusal, unchanged."""
    cc_path = _plan_change_check_path(slug, DECISIONS_DIR)
    if not cc_path.exists():
        return None, ""
    ref, anchor_ref = f"decisions/{cc_path.name}", f"decisions/{slug}-audit.yaml"
    rec = _read_yaml(cc_path)
    cc = rec.get("change_check") if isinstance(rec, dict) else None
    if not isinstance(cc, dict) or cc.get("plan") != slug:
        return None, f"{ref} is not a change check of this plan — run `yitc-v2 audit adhoc --plan {slug}`"
    if str(av.get("verdict") or "").upper() not in _PLAN_ANCHOR_JUDGED:
        return None, (f"the anchor {anchor_ref} is {str(av.get('verdict') or '').upper() or 'MISSING'} — no full "
                      f"pass completed, so no change check can admit from it")
    a_parts = av.get("accept_freshness_parts")
    if cur_parts is not None and isinstance(a_parts, dict) and a_parts:
        bad = _plan_not_eligible_changes(a_parts, cur_parts)
        if bad:
            return None, (f"a fresh anchor is required — {'; '.join(bad)} since the anchor {anchor_ref}; "
                          f"a change check cannot carry it: run `yitc-v2 plan check {slug}`")
    frm, to = cc.get("from") or {}, cc.get("to") or {}
    if (cc.get("anchor_findings_digest") != _plan_findings_digest(av.get("findings"))
            or frm.get("content_hash") != av.get("content_hash")
            or frm.get("accept_freshness_hash") != av.get("accept_freshness_hash")):
        return None, (f"the latest change check ({ref}) does not start at the current anchor "
                      f"({anchor_ref}) — run it again from this anchor")
    for key, value in current.items():
        if to.get(key) != value:
            return None, (f"the latest change check ({ref}) does not end at the current {key} — the plan "
                          f"changed after it; run it again from the anchor")
    changed = cc.get("changed")
    if not isinstance(changed, list) or not changed or any(
            not isinstance(c, dict) or not c.get("diff") for c in changed):
        return None, (f"the latest change check ({ref}) shows no cumulative diff for an input it "
                      f"reports changed — it cannot admit")
    verdict = str((rec or {}).get("verdict") or "").upper()
    if verdict not in ("GREEN", "YELLOW"):
        return None, (f"the latest change check ({ref}) is {verdict or 'MISSING'} — a failed attempt; fix "
                      f"and run it again from the anchor")
    closed = {str(x) for x in (cc.get("closed") or [])}
    left = [f"{fid} ({str(f.get('what') or '').strip()})" for fid, f in _plan_anchor_highs(av)
            if fid not in closed]
    if left:
        return None, f"the latest change check ({ref}) leaves anchor high(s) open: {'; '.join(left)}"
    return {"arm": "ii", "anchor": anchor_ref, "change_check": ref}, ""


def _git_text_at_digest(cwd: Path, pathspec: str, digest_of, want: str):
    """The text some commit (any ref, the newest 200 touching `pathspec`, read from `cwd`) held at
    that path whose `digest_of(text) == want`, as (repo-relative path, text) — None when none matches
    or git cannot answer (SPEC-1061 §2: the anchor-time text is read from the history)."""
    import subprocess
    from lib import git_env as _git_env   # T-13587 — the git child env policy (SPEC-0188 rule 7)
    try:
        log = subprocess.run(["git", "-C", str(cwd), "log", "--all", "-n", "200", "--format=%x00%H",
                              "--name-only", "--", pathspec], capture_output=True, text=True, timeout=120,
                             env=_git_env._git_child_env())
    except (OSError, subprocess.SubprocessError):
        return None
    if log.returncode != 0:
        return None
    for chunk in log.stdout.split("\x00")[1:]:
        lines = [ln.strip() for ln in chunk.splitlines() if ln.strip()]
        for name in lines[1:]:
            try:
                show = subprocess.run(["git", "-C", str(cwd), "show", f"{lines[0]}:{name}"],
                                      capture_output=True, text=True, timeout=120,
                                      env=_git_env._git_child_env())
            except (OSError, subprocess.SubprocessError):
                return None
            if show.returncode == 0:
                try:
                    if digest_of(show.stdout) == want:
                        return name, show.stdout
                except ValueError:   # an unparseable revision is simply not the anchor's text
                    continue
    return None


def _plan_closed_ids(stdout: str, valid: list) -> list:
    """The ids the auditor marks closed: the value of the LAST `closed:` key of its answer, read by the
    YAML parser (a flow or a block list). Admitting only on positive structure (SPEC-0165 item 11): the
    value must be a list whose EVERY element is a string naming a closure-list id exactly — anything
    else (a mapping, a non-id string, a scalar, an unparseable value) closes NOTHING."""
    lines = (stdout or "").splitlines()
    starts = [i for i, ln in enumerate(lines) if re.match(r"^[ \t]*closed:", ln)]
    if not starts:
        return []
    i = starts[-1]
    indent = len(lines[i]) - len(lines[i].lstrip())
    chunk = [lines[i][indent:]]
    for ln in lines[i + 1:]:
        stripped = ln.lstrip()
        lead = len(ln) - len(stripped)
        if stripped and (lead > indent or (lead == indent and stripped.startswith("- "))):
            chunk.append(ln[indent:])
            continue
        break
    try:
        value = state.load_str("\n".join(chunk))
    except Exception:   # noqa: BLE001 — an unparseable value closes nothing
        return []
    ids = value.get("closed") if isinstance(value, dict) else None
    if not isinstance(ids, list) or not all(isinstance(x, str) and x in valid for x in ids):
        return []
    return list(dict.fromkeys(ids))


def plan_change_check_packet(slug: str, *, DECISIONS_DIR, PLANS_DIR, SPECS_DIR, _die, _load_draft,
                             _plan_accept_freshness_hash, _plan_content_hash, _read_yaml,
                             _spec_content_sans_status, _run_plan_checks=None, _plan_obligations=None) -> dict:
    """SPEC-1061 §2 — the change check of `audit adhoc --plan <slug>`, built from the anchor and the
    plan as it stands. Refuses BEFORE any auditor call: no canonical anchor, an anchor without its
    per-input digests, a not-eligible input changed since the anchor, nothing changed, or a changed
    eligible input whose anchor-time text is not in the history (no diff can be shown). Returns the
    record path, the packet text and `finalize(stdout, verdict, findings) -> (verdict, block)`."""
    import difflib
    path, fm, body = _load_draft(slug, dirs=(PLANS_DIR,))
    # T-14672 (SPEC-0034 §Project-declared plan check) — phase `change-check`, before the anchor reads,
    # so before any `audit adhoc --plan` auditor call.
    if _run_plan_checks is not None:
        _run_plan_checks(path, "change-check", fm.get("id") or slug, verb=f"audit adhoc --plan {slug}")
    anchor_path = Path(DECISIONS_DIR) / f"{slug}-audit.yaml"
    anchor_ref = f"decisions/{anchor_path.name}"
    if not anchor_path.exists():
        _die(f"{slug}: no anchor — a change check starts from a recorded `plan check` "
             f"({anchor_ref}). Run `yitc-v2 plan check {slug}` (SPEC-1061 §1).")
    av = _read_yaml(anchor_path) or {}
    if not isinstance(av, dict) or av.get("target_kind") != "plan" or av.get("target_id") != slug:
        _die(f"{slug}: {anchor_ref} is not a canonical plan-check record — run `yitc-v2 plan check {slug}`.")
    a_parts = av.get("accept_freshness_parts")
    if not isinstance(a_parts, dict) or not a_parts:
        _die(f"{slug}: the anchor {anchor_ref} predates the per-input record a change check starts from — "
             f"run `yitc-v2 plan check {slug}` for a fresh anchor (SPEC-1061 §1).")
    if str(av.get("verdict") or "").upper() not in _PLAN_ANCHOR_JUDGED:
        _die(f"{slug}: the anchor {anchor_ref} is {str(av.get('verdict') or '').upper() or 'MISSING'} — no full "
             f"pass completed, so there is nothing a change check can start from; run `yitc-v2 plan check "
             f"{slug}` for an anchor (SPEC-1061 §1).")
    cur_parts: dict = {}
    spec_paths: dict = {}
    # T-14673 — the obligations are compared, and listed, through the boundary the anchor judged (its
    # recorded `obligations_through`), not the plan's status now: a plan accepted since the anchor keeps it.
    obl_through = a_parts.get("obligations_through") or str(fm.get("status") or "draft")
    cur_accept = (_plan_accept_freshness_hash(slug, body, fm, parts_out=cur_parts, own_paths_out=spec_paths,
                                              obligations_through=obl_through)
                  if _plan_obligations is not None else
                  _plan_accept_freshness_hash(slug, body, fm, parts_out=cur_parts, own_paths_out=spec_paths))
    cur_hash = _plan_content_hash(body)
    bad = _plan_not_eligible_changes(a_parts, cur_parts)
    if bad:
        _die(f"{slug}: no change check — {'; '.join(bad)} since the anchor; a fresh anchor is required: "
             f"run `yitc-v2 plan check {slug}` (SPEC-1061 §2).")
    if cur_hash == av.get("content_hash") and cur_accept == av.get("accept_freshness_hash"):
        _die(f"{slug}: nothing changed since the anchor {anchor_ref} — a change check has no diff to "
             f"judge (SPEC-1061 §2); `yitc-v2 plan stage accepted {slug}` reads the anchor as it stands.")

    def _diff(old: str, new: str, rel: str) -> str:
        return "\n".join(difflib.unified_diff(old.splitlines(), new.splitlines(), fromfile=f"{rel} @anchor",
                                              tofile=f"{rel} @now", lineterm="", n=3))

    def _missing(what: str):
        _die(f"{slug}: no change check — the anchor-time text of {what} is not in this repository's "
             f"history, so the cumulative diff cannot be shown; a fresh `yitc-v2 plan check {slug}` is the anchor "
             f"(SPEC-1061 §2: commit the plan with its check before editing it).")

    changed = []
    rel_plan = f"plans/{path.name}"
    if a_parts.get("body") != cur_parts.get("body"):
        hit = _git_text_at_digest(path.parent, path.name,
                                  lambda raw: _plan_content_hash(state.split_frontmatter_text(raw)[1]),
                                  a_parts.get("body"))
        if hit is None:
            _missing(f"the plan body ({rel_plan})")
        changed.append({"input": "plan body", "path": rel_plan,
                        "diff": _diff(state.split_frontmatter_text(hit[1])[1], body, rel_plan)})
    a_own, c_own = a_parts.get("own_specs") or {}, cur_parts.get("own_specs") or {}
    for sid in sorted(set(a_own) | set(c_own)):   # paths of current own specs: from the freshness pass
        if a_own.get(sid) == c_own.get(sid):
            continue
        cur_p = spec_paths.get(sid)
        new = cur_p.read_text(encoding="utf-8") if (cur_p is not None and sid in c_own) else ""
        rel = f"specs/{cur_p.name}" if cur_p is not None else f"specs/{sid}-*.yaml"
        old = ""
        if sid in a_own:
            digest = (lambda raw, _sid=sid: hashlib.sha256(
                f"OWN {_sid}\n{_spec_content_sans_status(raw)}\n".encode("utf-8")).hexdigest())
            hit = _git_text_at_digest(Path(SPECS_DIR), cur_p.name if cur_p is not None else f"{sid}-*.yaml",
                                      digest, a_own[sid])
            if hit is None:
                _missing(f"the plan-born spec {sid} ({rel})")
            old = hit[1]
        changed.append({"input": f"plan-born spec {sid}", "path": rel, "diff": _diff(old, new, rel)})
    if not changed:
        _die(f"{slug}: the freshness hashes moved since the anchor but no eligible input shows a change — "
             f"run `yitc-v2 plan check {slug}` for a fresh anchor (SPEC-1061 §2).")
    # T-14673 (SPEC-0034 §Plan-stage obligations) — the obligations due through the plan's status NOW,
    # from the projection the session receives, asked in the change check's own terms (contradictions the
    # change introduces); the freshness comparison above stays on the anchor's boundary.
    obl_block = ""
    if _plan_obligations is not None:
        _obl = _plan_obligations(str(fm.get("status") or "draft"), change_check=True)
        if _obl.get("unavailable"):
            _die(f"{slug}: no change check — the plan-stage obligation view is unavailable: "
                 f"{'; '.join(_obl['unavailable'])} (SPEC-0034 §Plan-stage obligations); repair the named "
                 f"read, then re-run `yitc-v2 audit adhoc --plan {slug}`.")
        obl_block = _obl.get("block") or ""
    findings = [f for f in (av.get("findings") or []) if isinstance(f, dict)]
    closure = [{"id": f"A{i}", "severity": str(f.get("severity") or "").strip().lower(),
                "what": str(f.get("what") or "").strip()} for i, f in enumerate(av.get("findings") or [], 1)
               if isinstance(f, dict)]
    lines = [f"## Plan change check — plan `{slug}` (SPEC-1061 §2)", "",
             f"This is a CHANGE CHECK, not a full review. The plan's full check — the ANCHOR, `{anchor_ref}`, "
             f"verdict {str(av.get('verdict') or '').upper() or 'MISSING'} — found the findings listed below; "
             f"the author fixed them in one batch. Judge exactly two things over the CUMULATIVE change from "
             f"the anchor to now:",
             "(1) for each listed finding: is it CLOSED by the plan as it stands now?",
             "(2) does the change introduce a contradiction or a regression (a new defect)"
             + (" — including a contradiction of a plan-stage obligation listed below?" if obl_block else "?"),
             "", "### Closure list — the anchor's findings"]
    for c, f in zip(closure, findings):
        where = str(f.get("where") or "").strip()
        lines.append(f"- {c['id']} [{c['severity'] or 'unrated'}] {c['what']}" + (f" — where: {where}" if where else ""))
    if obl_block:   # T-14673 — reference for question (2); the cumulative-change focus is unchanged
        lines += obl_block.rstrip("\n").split("\n")
    lines += ["", "### Cumulative diff from the anchor to now"]
    for c in changed:
        lines += [f"#### {c['input']} — `{c['path']}`", "```diff", c["diff"], "```"]
    lines += ["", "The current files: " + ", ".join(f"`{c['path']}`" for c in changed), "",
              "### Answer contract",
              "Answer with the usual `verdict:` line and `findings:` list — list every finding above that is "
              "still OPEN and every NEW defect the change introduced, each with its severity; a high, open or "
              "new, makes the verdict RED. In the SAME YAML block add ONE line `closed: [A1, A3]` naming "
              "exactly the listed findings the plan now closes (`closed: []` when none)."]
    block = {"plan": slug, "anchor": anchor_ref, "anchor_verdict": str(av.get("verdict") or "").upper(),
             "anchor_findings_digest": _plan_findings_digest(av.get("findings")),
             "from": {"content_hash": av.get("content_hash"),
                      "accept_freshness_hash": av.get("accept_freshness_hash")},
             "to": {"content_hash": cur_hash, "accept_freshness_hash": cur_accept},
             "changed": changed, "closure_list": closure}
    valid = [c["id"] for c in closure]

    def finalize(stdout: str, verdict: str, found: list):
        # SPEC-1061 §2 — the verdict follows the anchor's reading: any high is RED (an ABORT stays ABORT).
        if verdict != "ABORT" and any(isinstance(f, dict) and str(f.get("severity") or "").strip().lower()
                                      == "high" for f in (found or [])):
            verdict = "RED"
        return verdict, {**block, "closed": _plan_closed_ids(stdout, valid) if verdict != "ABORT" else []}

    return {"record_path": _plan_change_check_path(slug, DECISIONS_DIR), "prompt": "\n".join(lines),
            "block": block, "finalize": finalize}


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


def _plan_pre_gate_reread_cue(*, is_consumer: bool = False) -> str:
    """T-13853 — the cue every next-action hint of `plan stage` and `plan show` ends with: the
    SPEC-1025 pre-gate re-read, named where the author reads which gate comes next. A discipline
    cue plus a pointer to the rule's one home (SPEC-0005 rule 8) — never the rule text. The pointer
    is rendered for the session's realm, as every printed spec pointer is (`--kernel` under `-C`:
    SPEC-1025 is a kernel spec a consumer corpus does not hold)."""
    return ("before the next plan gate: the SPEC-1025 pre-gate re-read "
            f"(`{graph_lib.spec_query_hint('SPEC-1025', is_consumer=is_consumer, cli='yitc-v2')}`)")


def _plan_seam_default_line(cur: str, nxts, *, spec_text=None) -> "str | None":
    """T-13752 — the SPEC-0126 §7 seam default (AUTO / STOP (owner) under an authorized plan-drive)
    for each `cur → nxt` seam a `plan stage` next-step line names, as ONE line pointing at §7. The
    defaults are READ from the §7 table (the one home, SPEC-0005 rule 8 — no copy in the verb): each
    row's first bold token is rendered, with a pointer when the cell states a condition
    (`unless` / `only` / `by default`). The kernel's
    own SPEC-0126 is read (this file's checkout), so a `-C` consumer sees the kernel table. `spec_text`
    is the test seam. None when no named seam has a row, or the spec is unreadable (fail-soft: the
    next-step line above it is unaffected)."""
    if spec_text is None:
        try:
            specs = Path(__file__).resolve().parents[2] / "specs"
            spec_text = state.spec_decoded_text(
                next(specs.glob("SPEC-0126-*.yaml")).read_text(encoding="utf-8"))
        except (OSError, StopIteration):
            return None
    i = spec_text.find("### 7. Plan-drive autonomy seam-map")
    if i < 0:
        return None
    rows = {}
    for line in spec_text[i:].splitlines():
        m = re.match(r"\s*\| `(\w+) → (\w+)`[^|]*\| \*\*([^*]+)\*\*(.*?)\|", line)
        if m:
            rows[(m.group(1), m.group(2))] = m.group(3).strip() + (
                " (conditional — see the row)"
                if re.search(r"\b(unless|only|by default)\b", m.group(4)) else "")
    parts = [f"`{cur} → {n}` {rows[(cur, n)]}" for n in nxts if (cur, n) in rows]
    if not parts:
        return None
    return ("seam default under an authorized plan-drive (read from SPEC-0126 §7; no per-seam owner "
            "question at an AUTO seam): " + "; ".join(parts))


def _plan_body_title(body: str) -> str:
    """The plan's human title = its first `# ` heading (plan frontmatter carries no `title` field —
    the skeleton writes `# {title}` into the body). Falls back to '(no title)'."""
    for line in (body or "").splitlines():
        s = line.strip()
        if s.startswith("# "):
            return s[2:].strip()
    return "(no title)"


def cmd_plan_show(args: argparse.Namespace, *, IDEAS_DIR, PLANS_DIR, PLAN_STAGE_SEQUENCE, TASKS_DIR, _load_draft, _plan_body_title, _plan_next_stage, _plan_stage_bundle_specs, _plan_cut_cards, _read_yaml, _is_consumer_build=None, _owner_words=None, DECISIONS_DIR=None, _plan_card_set_fingerprint=None) -> None:
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
    author to repair `cites:` while the gate waits on `decomposed_from` (<project> X-0661 → X-0662). The
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
    if getattr(args, "unit_skeletons", False):
        # T-14625 (SPEC-0043 item 10): the card skeletons of the plan's `## Units` — a view, files nothing.
        specs_dir = PLANS_DIR.parent / "specs"

        def _spec_path(sid):
            hits = sorted(p for p in specs_dir.glob(f"{sid}-*.yaml") if ".part" not in p.name)
            return f"specs/{hits[0].name}" if hits else None
        try:
            sys.stdout.write(render_unit_skeletons(slug, parse_plan_units(body, spec_path=_spec_path)))
        except PlanUnitsError as e:
            print(f"yitc-v2: plan show --unit-skeletons {slug}: {e}. Nothing was emitted.", file=sys.stderr)
            sys.exit(2)
        return
    if getattr(args, "owner_words", False):
        # T-14520 (SPEC-1058 §2): the owner-words reconciliation before the read-back — a view only.
        sys.stdout.write(render_owner_words(_owner_words(slug, fm, body,
                                                         getattr(args, "earlier_tag", None) or [])))
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
        print(f"    next action: `yitc-v2 plan stage trial {slug}`  OR  `yitc-v2 plan stage accepted {slug}` — "
              f"{_plan_pre_gate_reread_cue(is_consumer=bool(_is_consumer_build and _is_consumer_build()))}")
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
            print(f"    next action: `yitc-v2 plan stage {nxt} {slug}` — "
                  f"{_plan_pre_gate_reread_cue(is_consumer=bool(_is_consumer_build and _is_consumer_build()))}")
            b = _plan_stage_bundle_specs(nxt)
            print(f"    {nxt} delivers (read before acting — `yitc-v2 graph query <SPEC>`): "
                  f"{', '.join(b) if b else '(no bound spec)'}")
        print("  gate detail: LIFECYCLE.md §Plan lifecycle + the bound spec(s) (authoritative).")
    # T-14563 (SPEC-0070 §4) — at `executing`, say whether the fidelity verdict still binds the LIVE cut.
    # A card filed into an executing plan re-fingerprints the cut; without this line the stale gate
    # record is invisible (X-2178 / X-2308). A view over the gate's own record + fingerprint fn.
    if status == "executing" and DECISIONS_DIR is not None and _plan_card_set_fingerprint is not None:
        _ap = DECISIONS_DIR / f"{slug}-audit-gate-executing.yaml"
        _av = (_read_yaml(_ap) or {}) if _ap.exists() else {}
        _live = _plan_card_set_fingerprint(slug)
        if _av.get("card_set_fingerprint") == _live and _live:
            print(f"  fidelity gate: fresh — the recorded {_av.get('verdict') or '?'} verdict binds the "
                  f"live cut (card_set_fingerprint {_live}).")
        else:
            _rec = _av.get("card_set_fingerprint") or "none recorded"
            print(f"  fidelity gate: STALE — the cut changed since the decomposition-fidelity verdict "
                  f"(recorded {_rec}, live {_live}; SPEC-0070 §4).")
            print(f"    re-run: `yitc-v2 plan stage executing {slug} --recut`")
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
