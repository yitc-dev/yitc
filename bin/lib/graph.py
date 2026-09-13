"""bin/lib/graph.py — the graph index-build + query-projection + view-derivation ENGINE (T-9249).

The read-only derivation core of the spec↔code graph: it BUILDS the derived index from the authored
corpus (graph_build_index + _compute_scenario_status + _extract_rules/_doc_slug), DERIVES the
retrieval-delivery binding views (_build_binding_views + _governing_contract_for), PROJECTS the
"what-will-be" spec set (_graph_query_projected + _task_activating_spec_map + _toposort_requires),
SERIALIZES the index (_write_graph_index + _json_default + _build_graph_built_payload), and CUTS the
identity-agnostic release view (the _release_view_* / _build_release_view family). Extracted from the
bin/yitc-v2 monolith under plan `decompose-bin-yitc-v2-into-a-layered-bin-lib-packa` (the third leaf,
after state.py + events.py + audit.py).

Identity-agnostic KERNEL module (SPEC-0073 bin/ HARD class — travels with the engine). It imports
ONLY `from lib import state` + the stdlib-only `lib.host_paths` leaf (T-12024) + stdlib — it does NOT emit events (the emit
sites cmd_graph_build / _auto_rebuild_graph STAY in the host) and NEVER back-imports the monolith.
Host collaborators (_read_yaml / _resolve_implements_anchor / _anchor_drift_warning / _anchor_file /
_id_from_artifact_ref / _pattern_frontmatter / _is_consumer_build / _resolve_placement / _die /
write_text_atomic / _render_floor_trigger_map / _is_valid_stage_entry / _is_valid_plan_stage_entry)
and host globals/consts (the *_DIR / REPO_ROOT / ENGINE_ROOT path globals + the binding-vocab consts)
arrive by INJECTION (keyword params), exactly like state.py's `rel_root` / events.py's `guard=` — so a
`-C` rebind and the test monkeypatch/rebind of `yitc.<global>` are honored by the host wrapper at call
time. The host keeps a thin residue (re-export alias for the pure movers, injecting wrapper for the
host-global readers) under each historical name, so every `yitc.<symbol>` rebind + direct call resolves.
Behaviour is byte-identical to the inline original — the full test suite + byte-identical graph/index.json
are the oracle (T-9249).
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import re
import stat as _stat
import sys
import tempfile
import time

from lib import host_paths   # T-12024: stdlib-only leaf — keeps this module's state+stdlib bound
from lib import state

# T-10625: the repo-relative derived-view dir — the RELEASE_VIEW_DIR twin, same single-value-home shape,
# re-exported to the host so it composes the audience-view bookkeeping paths from a NAME. A bare "graph/"
# string literal in bin/yitc-v2 / worktree.py is (correctly) forbidden by the T-0631 one-authority guard:
# "graph/" is an `_INERT_DIR_PREFIXES` member, so that literal may appear only in the inert allowlist.
GRAPH_DIR = "graph"

# Release-view consts (SPEC-0074; graph-only home — RELEASE_VIEW_DIR is re-exported to the host for
# cmd_graph_release_view). The single value home is here, T-9249.
RELEASE_VIEW_DIR = "release-view"
RELEASE_VIEW_BANNER = (
    "<!-- GENERATED — identity-agnostic release view of the methodology handbook. "
    "Single source; regenerate via `yitc-v2 graph release-view`, do not edit. -->\n\n"
)
_RV_IPV4 = re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b")
_RV_UUID = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
_RV_DT_ID = re.compile(r"\b[DT]-\d{4,}\b")

# Rule-extraction consts (graph-build-only — sole reader is _extract_rules). Single value home, T-9249.
RULE_RE = re.compile(r"\b(must|shall|cannot|required|should|may)\b", re.IGNORECASE)
# severity precedence: must > should > may
RULE_SEVERITY = {"must": "must", "shall": "must", "cannot": "must", "required": "must",
                 "should": "should", "may": "may"}


def _doc_slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower().replace(".md", "")).strip("-")


def _file_granular_anchor_warning(anchor, has_symbol_space=None) -> str | None:
    """SPEC-0088 code-decompose rule (REPORT-ONLY): a graph-governed code anchor on the two
    code-edge carriers — a spec's `implements:` and a scenario's `covers:` — SHOULD decompose to
    `<file>#<symbol>`, not a bare `<file>`. Returns a one-line warning for a file-granular anchor
    (one with NEITHER `#symbol` NOR `:line`), else None. A legacy `<file>:<line-range>` anchor is
    NOT re-flagged here — it is already warned drift-prone by `_resolve_implements_anchor`
    (SPEC-0006), so re-flagging would double-count. Report-not-block per GRAPH «NOT a validation
    layer» (the caller surfaces this to stderr on the exit-0 channel, never exit 2).

    `has_symbol_space` (T-9370 — atomic-target exemption, mechanizing the spec's «Genuinely-atomic
    targets» review-and-leave clause): the build path passes False for a genuinely-ATOMIC target —
    a Jinja template, a markup/data file with NO resolvable `#symbol` address space (the kupiclub
    landing.html / not_found.html case, X-0051) — for which the advisory CANNOT be actioned and so
    re-fires as permanent noise on every build. False suppresses it. None (unknown — e.g. a direct
    unit call) or True preserves the warning, so a target that DOES have a symbol space is still
    advised (no regression). The signal is content-derived from the SAME symbol grammar as
    `_resolve_implements_anchor` (`_file_has_symbol_space`), not a new annotation store."""
    s = str(anchor)
    if "#" in s or ":" in s:
        return None
    if has_symbol_space is False:                       # genuinely-atomic / symbol-less → exempt (T-9370)
        return None
    return (f"{s}: file-granular anchor — decompose to <file>#<symbol> "
            f"(SPEC-0088, report-only)")


def _extract_rules(lines, slug: str, source_doc: str, source_domain: str) -> list:
    """Extract `rule` nodes from markdown-ish `lines` (a list of raw text lines). Walks `#..######`
    headers to track the current section; each line matching RULE_RE yields ONE rule node tagged with
    `source_domain` (the additive tier tag, T-0246: "handbook" | "spec"). SHARED by the handbook-doc
    loop AND the retrieved-tier spec-body loop (reuse, NOT a parallel parser — CHARTER §P1 filter 1)."""
    out = []
    section = ""
    for ln, raw in enumerate(lines, start=1):
        h = re.match(r"^#{1,6}\s+(.*)$", raw)
        if h:
            section = re.sub(r"[^a-z0-9]+", "-", h.group(1).lower()).strip("-")[:40]
            continue
        m = RULE_RE.search(raw)
        if not m:
            continue
        kw = m.group(1).lower()
        sev = RULE_SEVERITY[kw]
        out.append({"id": f"rule:{slug}:{section or 'root'}:{ln}:{sev}",
                    "source_doc": source_doc, "source_section": section or "root",
                    "source_line": ln, "severity": sev, "source_domain": source_domain,
                    "content": raw.strip()[:200], "status": "active"})
    return out


def _scenario_cites_all_active(cites, specs, kernel_specs=None):
    """SPEC-0076 §3 — TRUE iff the scenario cites at least one spec AND every spec it cites is
    `active`. PURE: the caller supplies the loaded `specs` map (+ the optional kernel map). Split out
    of `_compute_scenario_status` by T-11004 — this predicate is the part of the derivation that
    SURVIVED the `live` retirement (below), and it is the input SPEC-0082's scenario-fidelity leg
    reads (`cites_all_active` on the scenario node). A MOVE of the existing resolution, not a new rule.

    Spec citations are identified by id-SHAPE (`SPEC-`), NOT by membership in `specs`, so a cited
    spec that is MISSING from the loaded map still COUNTS and FAILS CLOSED to non-active (audit-pre F2
    of T-10933) rather than being silently dropped. A scenario also `cites` plans/decisions/other
    scenarios — those are composition links, not the path's binding rules, so they never gate status.

    NO-CITES is FALSE, never vacuously true (T-11004 audit-pre F1): `all()` over an empty list is
    True, which would let a `draft` scenario (citing nothing) read as fully-active and pass the
    SPEC-0082 baseline leg silently — a finding that fires TODAY (`draft != "live"`). The
    at-least-one-cite conjunct keeps that population flagged, so the retirement trades away only the
    unreachable half.

    CROSS-REALM resolution (T-10933, `kernel_specs`): `specs` is the OWN corpus, so under `-C` a
    CONSUMER scenario citing a KERNEL spec (the methodology specs travel as kernel — SPEC-0073 §1 /
    SPEC-0074 §4) found nothing and computed `building` — under-reporting coverage, which is the
    reading a scenario exists to make legible. `kernel_specs` is the optional {id: status} kernel map;
    the caller supplies it (this function stays PURE and never fetches). It is the STATUS-bearing twin
    of the `_kernel_spec_ids` EXISTENCE fallback that T-10106 and T-10817 already gave the two sibling
    paths — the same mechanism, reaching its last consumer. SHAPE (deliberately different from `specs`,
    each matching its own producer): `specs` is the graph's {id: node-dict} corpus, so its status is
    read as `["status"]`; `kernel_specs` is `_kernel_spec_statuses()`'s FLAT {id: status-string}, which
    is all the kernel side needs and avoids materializing kernel node-dicts this never otherwise reads.

    PRECEDENCE — consumer-own WINS (SPEC-0092 §Internal), keyed on PRESENCE (`c in specs`), never on
    truthiness: a consumer spec that exists but is `proposed` must stay non-active, NOT fall through
    to a kernel spec of the same id that happens to be `active`. A naive kernel-first (or
    `or`-chained) resolution would silently redirect a consumer's scenario onto the kernel's rule.
    Absent from BOTH corpora still fails closed to non-active, and `kernel_specs=None` reproduces the
    pre-T-10933 result exactly — so an engine self-build, where there is no realm split and the map is
    empty, is a pure no-op."""
    spec_cites = [c for c in cites if isinstance(c, str) and c.startswith("SPEC-")]
    if not spec_cites:
        return False                                      # no-cites is NOT vacuously all-active

    def _status_of(c):
        if c in specs:                                    # own-wins on PRESENCE (SPEC-0092)
            return (specs.get(c) or {}).get("status")
        return (kernel_specs or {}).get(c)                # cross-realm fallback (T-10933)

    return all(_status_of(c) == "active" for c in spec_cites)


def _compute_scenario_status(cites, stored_status=None):
    """SPEC-0076 §3 (T-1048) — derive a scenario's read-only status from what it cites. PURE.

    Only `retired` is human-STORED (the storage contract is T-1047's); `draft`/`building` are a
    COMPUTED view, NEVER persisted to frontmatter.

      - stored `retired`            -> "retired"
      - cites NO spec               -> "draft"      (still being thought through)
      - cites >=1 spec              -> "building"   (agreed target, being built)

    `live` IS RETIRED (T-11004) — do NOT re-add it. The state was reachable ONLY when a
    `binding_test_green` signal was truthy, and that signal had NO producer in any repository: the
    public `graph_build_index` defaulted it to None, so it was hardcoded False and `live` was
    unreachable EVERYWHERE — a false negative in every repo, indistinguishable from a genuinely
    unfinished path. T-1052, named in the old comment as the supplier, shipped a SUITE-WIDE scenario
    integrity test, never a per-scenario green, and scenario frontmatter models no per-scenario test at
    all, so the signal was never merely missing — it was never modelled. Retirement was settled by an
    external consult (decisions/four-forks-consult-audit-adhoc.yaml, GREEN); it required a CURRENT
    caller needing `live` distinct from `building` AND a cheap producer on an already-adopted signal to
    reverse, and only the first arm held (SPEC-0082's fidelity leg, retargeted onto
    `_scenario_cites_all_active` above — the reachable half of what `live` used to mean).

    CONSEQUENCE, stated plainly rather than hidden behind a dead branch: with `live` gone the STATUS
    no longer reads spec STATUSES at all — draft vs building turns only on WHETHER the scenario cites a
    spec — so the `specs` / `kernel_specs` params are GONE from this signature rather than kept as
    ignored arguments. The spec-status reading did not disappear from the system: it moved WHOLE, with
    its T-10933 cross-realm precedence, into `_scenario_cites_all_active` above, which the node build
    calls alongside this one."""
    if stored_status == "retired":
        return "retired"
    spec_cites = [c for c in cites if isinstance(c, str) and c.startswith("SPEC-")]
    return "building" if spec_cites else "draft"


def _build_binding_views(specs: dict, *, BINDING_VERB_SURFACES, BINDING_FLOOR_TOKEN,
                         BINDING_RESIDENCY_TOKENS, BINDING_SEED_TOKEN, STAGE_ENTRY_PREFIX,
                         PLAN_STAGE_ENTRY_PREFIX, FLOOR_TRIGGERS, UNMAPPED_CHECK_SURFACES,
                         _is_valid_stage_entry, _is_valid_plan_stage_entry) -> tuple:
    """Derive the retrieval-delivery views from the per-spec `binding:` field (T-0230, Part I-A).
    Returns (verb_to_specs, floor_trigger_map, binding_report) — all DERIVED-ONLY from the single
    canonical carrier (the `binding:` field; plan-check finding 1), no hand-maintained duplicate.
    PURE f(specs) for testability. The inversion + floor consider `active` specs ONLY — a
    proposed/superseded spec governs nothing (GRAPH §What a spec is FOR), so a non-active binding
    must not appear as a 'what to read before acting' pointer."""
    verb_to_specs = {s: [] for s in BINDING_VERB_SURFACES}
    unknown_tokens = []
    stage_to_specs = {}                             # stage-entry:<STAGE> → [spec ids] (T-0287, derived view)
    plan_stage_to_specs = {}                        # plan-stage-entry:<PLAN_STAGE> → [spec ids] (T-0324,
                                                    # derived view — the plan-axis mirror of stage_to_specs)
    seed_specs = []                                 # T-0289: specs bound to the `seed` residency token —
                                                    # the single carrier of the stage-agnostic seed how-to
    for sid in sorted(specs):
        rec = specs[sid]
        if rec.get("status") != "active":
            continue
        binding = rec.get("binding") or []
        if BINDING_FLOOR_TOKEN in binding:          # floor is DOMINANT (audit-post finding 1): a
            continue                                # floor-resident spec is always-loaded → excluded
                                                    # from the verb inversion ENTIRELY, even if it also
                                                    # lists a verb token (a redundant/contradictory mix).
        for tok in binding:
            if tok in verb_to_specs:
                verb_to_specs[tok].append(sid)
            elif tok in BINDING_RESIDENCY_TOKENS:   # query-only (T-0263) / code-enforced (T-0278) / seed (T-0289):
                if tok == BINDING_SEED_TOKEN:       # collect the stage-agnostic seed how-to source (single
                    seed_specs.append(sid)          # carrier — generated into the session-start seed echo).
                continue                            # residency markers — NOT a verb surface, NOT unknown.
                                                    # Excluded from the inversion (no before-verb fetch);
                                                    # excluded from dangling below (non-empty binding).
                                                    # (floor already short-circuited the whole spec above.)
            elif _is_valid_stage_entry(tok):        # stage-entry:<STAGE> (T-0284): a recognized routing
                stage_to_specs.setdefault(          # class — NOT a verb surface, NOT unknown. T-0287 now
                    tok[len(STAGE_ENTRY_PREFIX):], []).append(sid)  # INVERTS it into the stage→specs view
                continue                            # consumed by `stage <NAME>`. Still excluded from the
                                                    # verb inversion AND from dangling (non-empty binding).
                                                    # An INVALID stage suffix is NOT a valid stage-entry →
                                                    # falls through to unknown_tokens below.
            elif _is_valid_plan_stage_entry(tok):   # plan-stage-entry:<PLAN_STAGE> (T-0324): the PLAN
                plan_stage_to_specs.setdefault(     # delivery axis — a recognized routing class (COMPLETE
                    tok[len(PLAN_STAGE_ENTRY_PREFIX):], []).append(sid)  # mirror of stage-entry). INVERTED
                continue                            # into plan_stage_to_specs, consumed by `plan stage`
                                                    # (`_plan_stage_bundle_specs` reads THROUGH this view —
                                                    # ONE derivation from the binding carrier, P5). Excluded
                                                    # from the verb inversion AND from dangling; an INVALID
                                                    # plan-stage suffix falls through to unknown_tokens.
            else:                                   # report-not-block: unknown token = drift signal
                unknown_tokens.append({"spec": sid, "token": str(tok)})
    for s in verb_to_specs:
        verb_to_specs[s] = sorted(set(verb_to_specs[s]))
    # Floor trigger-map: the four mandatory-on-entry triggers → PER-SURFACE spec membership, keyed by the
    # individual verb surface (NEVER a unioned label — preserves per-verb precision; audit-post finding 2).
    floor_trigger_map = {}
    for trig, surfaces in FLOOR_TRIGGERS:
        floor_trigger_map[trig] = {s: list(verb_to_specs.get(s, [])) for s in surfaces}
    # T-10032 (SPEC-0128 Rule 2): ADD the registry-DERIVED before-authoring-<concern> floor family — each
    # concern block's well-formed `authoring_floor` contributes a trigger whose SINGLE surface is the trigger
    # name itself (the behavioral-floor shape: surface == trigger), bound directly to the concern-declared
    # delivery spec(s) — NOT via a per-spec `binding:` token, so no hand-added FLOOR_TRIGGERS row. A concern
    # trigger NEVER overrides a static FLOOR_TRIGGERS key (fail-safe: the hand-listed set wins on collision).
    for trig, sids in _concern_authoring_floors(specs):
        if trig not in floor_trigger_map:
            floor_trigger_map[trig] = {trig: list(sids)}
    # Bidirectional completeness report (report-not-block, both directions — Part I-A element #4):
    unmapped = [s for s in UNMAPPED_CHECK_SURFACES if not verb_to_specs.get(s)]
    dangling = []
    for sid in sorted(specs):
        rec = specs[sid]
        if rec.get("status") != "active":
            continue
        # The dangling predicate is now EXPLICIT: `active AND empty binding` (T-0278). The old implicit
        # `if rec.get("implements"): continue` excuse was REMOVED — it was THE HOLE that hid SPEC-0012
        # (implements-bearing yet governing an undelivered control-point) from T-0263's door. Now EVERY
        # active spec must DECLARE its delivery via a token: a verb surface, OR a residency token
        # (floor / query-only / code-enforced — the explicit allowlist). Any non-empty binding excuses;
        # an unknown token is its OWN report (drift), never dangling. So dangling = NO token at all.
        if rec.get("binding"):
            continue
        dangling.append(sid)                        # active spec, EMPTY binding → unclassified
    stage_to_specs = {st: sorted(set(ids)) for st, ids in stage_to_specs.items()}  # T-0287 derived view
    plan_stage_to_specs = {st: sorted(set(ids))                # T-0324 derived view — plan-axis mirror
                           for st, ids in plan_stage_to_specs.items()}
    binding_report = {"unmapped_gating_verbs": unmapped, "dangling_specs": sorted(dangling),
                      "unknown_tokens": unknown_tokens, "stage_to_specs": stage_to_specs,
                      "plan_stage_to_specs": plan_stage_to_specs,   # T-0324 — plan-stage delivery axis
                      "seed_specs": sorted(set(seed_specs))}   # T-0289 — stage-agnostic seed how-to source
    return verb_to_specs, floor_trigger_map, binding_report


def _governing_contract_for(surface: str, *, SPECS_DIR, STAGE_ENTRY_PREFIX, SURFACE_TO_STAGE,
                            _is_valid_stage_entry, _build_binding_views) -> dict:
    """Delivery-observability projection (SPEC-0013 §Delivery-observability / T-0271): the GOVERNING
    before-X contract spec(s) for a floor-gated verb surface — emitted as the journal field
    `governing_contract` (HONEST NAME, T-0390: it records WHICH contract governed the gate, a binding
    projection, NOT read-evidence that the AI consumed it; renamed from `consumed_contract` 2026-06-05,
    historical journal lines keep the old key — append-only, readers handle both by ts). DERIVED from the single canonical binding
    map (`_build_binding_views` over the per-spec `binding:` field) — never hand-typed, never a fakeable
    self-reported fact. Returns a FIXED-SHAPE dict so the emitted journal field is ALWAYS DETERMINATE
    (audit-pre F1 HIGH): `{"specs": [...], "status": "resolved"}` for a bound OR legitimately-unbound
    surface; `{"specs": [], "status": "derivation-failed"}` when the corpus can't be read (the exception
    is caught HERE — a telemetry field MUST NOT crash the gated verb — but the failure is RECORDED, not
    silently omitted, so journal-only analysis can tell 'no contract' apart from 'derivation broke')."""
    try:
        import yaml
        if not SPECS_DIR.is_dir():                        # missing corpus IS a derivation failure,
            return {"specs": [], "status": "derivation-failed"}   # distinct from a legit-empty binding
        specs = {}
        for p in state.scan_specs(SPECS_DIR):   # SPEC-* glob excludes _template.yaml
            d = state.load_str(p.read_text(encoding="utf-8")) or {}
            sid = d.get("id")
            if sid:
                specs[sid] = d
        if not specs:                                     # a real corpus always has specs; ZERO loaded =
            return {"specs": [], "status": "derivation-failed"}   # broken/incomplete checkout, NOT no-binding
        verb_to_specs, _, report = _build_binding_views(specs)
        if _is_valid_stage_entry(surface):                # T-0291: a stage-entry:<STAGE> surface (the claim
            stage = surface[len(STAGE_ENTRY_PREFIX):]     # marker, CLAIM_DELIVERY_MARKER) resolves DIRECTLY
            stage_to_specs = report.get("stage_to_specs") or {}   # through the stage→specs view — the same
            return {"specs": list(stage_to_specs.get(stage, [])),  # axis SURFACE_TO_STAGE relocates verbs onto,
                    "status": "resolved"}                          # so the migrated marker stays POPULATED+truthful.
        if surface in SURFACE_TO_STAGE:                   # T-0289: a RELOCATED lifecycle gating verb — its
            stage = SURFACE_TO_STAGE[surface]             # before-X contract now lives on the stage-entry
            stage_to_specs = report.get("stage_to_specs") or {}   # delivery axis; resolve THROUGH it so the
            return {"specs": list(stage_to_specs.get(stage, [])),  # governing_contract stays POPULATED +
                    "status": "resolved"}                          # truthful in the new model (not silently empty).
        return {"specs": list(verb_to_specs.get(surface, [])), "status": "resolved"}
    except Exception:
        return {"specs": [], "status": "derivation-failed"}


def _graph_query_projected(index: dict, include_draft_plan: str | None = None) -> dict:
    """PURE f(graph) «what-will-be» projection over the spec set (D-0047 B4).

    projection = active − superseded-by-proposed + proposed. Reads `index` ONLY; writes
    nothing (no snapshots / merge / semantic analysis — all deferred per D-0047).

    `include_draft_plan` (T-0186 Part A — the `--include-draft=<plan>` what-if): when set, the
    plan-LOCAL `draft` specs of THAT plan (status: draft AND proposed_by == the plan) are added
    to the projection as a what-if. DEFAULT (None) EXCLUDES all drafts (drafts are neither active
    nor proposed, so they never enter the base projection — SPEC-0005 §4 / big-plan §Q3). Drafts
    carry no new structural flag (audit-pre F3): they appear with their honest status: draft only.

    Returns a dict {projected_specs, flags_summary}. Structural flags only:
      added                     proposed spec, no `supersedes`
      changed                   proposed spec whose `supersedes` → an active spec
      superseded                active spec that is a proposed spec's `supersedes` target
      stale                     proposed spec superseding a target that exists but is NOT active
      dangling                  proposed `supersedes`/`requires` target ID absent from the index
      multi-proposer-unordered  ≥2 proposed specs supersede the SAME target with no intra-group
                                `requires`/`supersedes` edge ordering them (the B6 invariant violation)
    """
    specs = index.get("specs", {}) or {}
    proposed = {sid: s for sid, s in specs.items() if s.get("status") == "proposed"}
    # known node IDs for dangling-requires resolution — spec-level `requires` may target
    # spec OR decision (OR task) IDs (GRAPH §spec schema), so check against all, not just SPEC-.
    known_ids = set(specs) | set(index.get("decisions", {}) or {}) | set(index.get("tasks", {}) or {})

    # Group proposed specs by their supersedes-target → concurrent proposers of one lineage.
    by_target: dict = {}
    for sid, s in proposed.items():
        tgt = s.get("supersedes")
        if tgt:
            by_target.setdefault(str(tgt), []).append(sid)

    # B6: a group of ≥2 proposers of one target is INVALID unless ordered among themselves
    # (some member `requires` or `supersedes` another member of the same group).
    unordered: set = set()
    for tgt, members in by_target.items():
        if len(members) < 2:
            continue
        mset = set(members)
        ordered_links = 0
        for sid in members:
            s = proposed[sid]
            refs = set(s.get("requires") or [])
            if s.get("supersedes"):
                refs.add(str(s["supersedes"]))
            if refs & (mset - {sid}):
                ordered_links += 1
        # Need at least (size-1) intra-group links to form a chain/total order; else unordered.
        if ordered_links < len(members) - 1:
            unordered.update(members)

    projected: dict = {}
    # superseded active specs = targets of a proposed `supersedes` that are currently active.
    superseded_by: dict = {}
    for sid, s in proposed.items():
        tgt = s.get("supersedes")
        if tgt and specs.get(str(tgt), {}).get("status") == "active":
            superseded_by.setdefault(str(tgt), []).append(sid)

    # 1. active specs carried into the projection (flagged superseded if a proposer replaces them).
    for sid, s in specs.items():
        if s.get("status") != "active":
            continue
        entry: dict = {"status": "active", "flags": []}
        if sid in superseded_by:
            entry["flags"].append("superseded")
            entry["superseded_by"] = sorted(superseded_by[sid])
        projected[sid] = entry

    # 2. proposed specs added to the projection with added/changed (+ stale/dangling/unordered).
    for sid, s in proposed.items():
        flags = []
        tgt = s.get("supersedes")
        if tgt:
            tstatus = specs.get(str(tgt), {}).get("status")
            if tstatus is None:
                flags.append("dangling")
            elif tstatus == "active":
                flags.append("changed")
            else:
                flags.append("stale")   # supersedes a non-current (superseded/retired) spec
        else:
            flags.append("added")
        # dangling requires-target (separate from supersedes) — any allowed target kind
        # (spec / decision / task) absent from the index flags the proposer dangling.
        for r in (s.get("requires") or []):
            if str(r) not in known_ids:
                if "dangling" not in flags:
                    flags.append("dangling")
                break
        if sid in unordered:
            flags.append("multi-proposer-unordered")
        entry = {"status": "proposed", "flags": flags}
        if tgt:
            entry["supersedes"] = str(tgt)
        projected[sid] = entry

    # 3. T-0186 — `--include-draft=<plan>` what-if: add ONLY that plan's drafts (status: draft AND
    #    proposed_by == the plan). No new structural flag (audit-pre F3) — honest status: draft only.
    #    Default (include_draft_plan None) skips this entirely → drafts stay excluded.
    if include_draft_plan:
        for sid, s in specs.items():
            if s.get("status") == "draft" and s.get("proposed_by") == include_draft_plan:
                projected[sid] = {"status": "draft", "flags": [], "proposed_by": include_draft_plan}

    summary: dict = {}
    for entry in projected.values():
        for f in entry["flags"]:
            summary[f] = summary.get(f, 0) + 1
    return {"projected_specs": projected, "flags_summary": summary}


# T-10400 (X-0290): a head whose status is one of these ACTUALLY TOOK EFFECT — it replaced its
# `supersedes:` target. A head still `proposed` is the PENDING supersession `--projected` already
# owns (_graph_query_projected above); `draft` / `withdrawn` / `rejected` never took effect at all.
_EFFECTIVE_SUPERSESSION_STATUSES = ("active", "superseded", "retired")


def _derived_superseded_by(index: dict, spec_id: str) -> list:
    """[head_id, …] — the specs that COMPLETED a supersession of `spec_id`, sorted (T-10400/X-0290).

    The reverse of the head's durable `supersedes:` field. DERIVED at query time, never stored: a
    superseded spec is frozen-immutable (SPEC-0005 rule 7) and SPEC-0030 deliberately carries no
    `superseded_by` field, so graph code is the only legal carrier for this link (a new VIEW over
    existing data — CHARTER §P1 filter 2 — not a new entity). Pure f(index), like the sibling
    derivers here: no I/O, no writes, no index field (GRAPH §NOT-a-caching-layer).

    COMPLETES the sibling `_graph_query_projected`, which derives `superseded_by` ONLY for the
    PENDING case (a `proposed` head over a still-`active` target) and only under `--projected`. Once
    activation lands, BOTH of those conditions fail and the reverse link vanished from every surface
    — the X-0290 gap: a reader on a superseded spec could not ask what replaced it. A head that
    later got superseded/retired ITSELF still counts (the lineage chain must not break); a head that
    is proposed / draft / withdrawn / rejected / ABSENT yields NO pointer.
    """
    specs = index.get("specs", {}) or {}
    return sorted(
        hid for hid, h in specs.items()
        if str(h.get("supersedes") or "") == str(spec_id)
        and h.get("status") in _EFFECTIVE_SUPERSESSION_STATUSES
    )


def _attach_superseded_by(result: dict, index: dict, spec_id: str) -> None:
    """Attach the derived reverse link to a spec point-lookup `result`, from the SAME index that
    resolved the node (so a --kernel / -C engine-fallback lookup reads KERNEL heads, not consumer
    ones). Omitted entirely when there is no completed supersession — an absent key, never an empty
    list: the overwhelming majority of specs have no head, and a `superseded_by: []` on every one of
    them is noise (T-10400)."""
    heads = _derived_superseded_by(index, spec_id)
    if heads:
        result["superseded_by"] = heads


def _task_activating_spec_map(index: dict) -> dict:
    """{task_id: spec_id} for every spec carrying an `activation_owner_task` (SPEC-0005 §5 — the
    single explicit activation carrier). Derived from the graph `index` ONLY (T-0425 — the spec
    node now indexes `activation_owner_task`, see graph_build_index): NO second specs/*.yaml scan,
    so activation-ownership has ONE source of truth (P5 / audit-pre F2). Pure f(index)."""
    out: dict = {}
    for sid, s in (index.get("specs", {}) or {}).items():
        owner = s.get("activation_owner_task")
        if owner:
            out[str(owner)] = sid
    return out


def _toposort_requires(members: list, req_of: dict) -> list:
    """Order a chain's members so each task follows the survivors it `requires:` (parent before
    child). Deterministic: stable by id within a level. Pure helper for _carve_out_selection."""
    members = sorted(members)
    remaining = set(members)
    ordered: list = []
    while remaining:
        # a member is ready when all its survivor-requires are already placed.
        level = sorted(t for t in remaining
                       if all(r in ordered for r in req_of.get(t, []) if r in members))
        if not level:                       # cycle (shouldn't happen) — emit the rest stably
            ordered.extend(sorted(remaining))
            break
        ordered.extend(level)
        remaining.difference_update(level)
    return ordered


def _build_graph_built_payload(counts: dict, errors: list, trigger: str | None = None,
                               duration_ms: "int | None" = None, cache: "str | None" = None) -> dict:
    """T-0031: assemble graph_built event payload. Pure helper для testability +
    shared by cmd_graph_build + _auto_rebuild_graph (both emit sites use same shape).

    had_errors + errors_count present ONLY когда parse_errors > 0 (omit-on-clean keeps
    payload small; consumers tolerate absent keys per AGENTS event types catalog rule).
    T-0375: duration_ms — build wall-clock (index build + write), ADDITIVE key present only
    when measured (no fabricated 0s — the T-0358 cli_invoked precedent; D-0009 P5-safe).
    T-11326: cache — the result-cache state of THIS build ("hit" | "miss" | "skip" | "off"), same
    additive/omit-on-absent convention. This field IS the hit-rate observable: it is written on every
    outcome, not only on a hit, so an all-miss journal reads as an all-miss cache rather than as an
    unwired one (the dead end T-11222 measured on `pinned_cache_hit`, which is written only on a hit).
    """
    data: dict = {"counts": counts}
    if trigger:
        data["trigger"] = trigger
    if errors:
        data["had_errors"] = True
        data["errors_count"] = len(errors)
    if duration_ms is not None:
        data["duration_ms"] = duration_ms
    if cache:
        data["cache"] = cache
    return data


def _json_default(o):
    """JSON serializer for the non-JSON-native values reaching the derived index (T-0365):
    unquoted YAML timestamps in source artifacts parse to datetime/date — serialized as ISO-8601
    strings AT BUILD TIME (the normalization boundary is the serializer; index consumers treat
    timestamps as strings — audit-pre F0). Anything else raises, same fail-loud class as
    yaml.safe_dump's RepresenterError before the switch."""
    if isinstance(o, (_dt.datetime, _dt.date)):
        return o.isoformat()
    raise TypeError(f"graph index: unserializable value of type {type(o).__name__}")


def _write_graph_index(index: dict, *, GRAPH_PATH, write_text_atomic,
                       _render_floor_trigger_map, _is_consumer_build,
                       _render_activation_checklist, _render_concern_registry) -> None:
    """Serialize + write the DERIVED graph index (graph/index.json) and its sibling floor
    trigger-map — the SINGLE write helper for both build sites (cmd_graph_build +
    _auto_rebuild_graph; T-0365 dedupes their copied dump blocks, P1 F3).

    JSON serialization (T-0365): json.dumps measured ~0.02s vs the ~2.2s yaml.safe_dump that
    dominated every graph build on the ~2.3MB tree. sort_keys + indent=1 keep the committed
    artifact deterministic + line-diffable; ensure_ascii=False mirrors allow_unicode=True.
    P5: the one-YAML-format rule governs AUTHORED operational state — this is a derived,
    rebuilt-from-scratch view (CHARTER P5 "derived artifacts are committed").

    T-0251: floor-map path derived from GRAPH_PATH (sibling) so test isolation of GRAPH_PATH
    isolates the floor map too."""
    content = json.dumps(index, sort_keys=True, ensure_ascii=False, indent=1,
                         default=_json_default) + "\n"
    write_text_atomic(GRAPH_PATH, content)
    write_text_atomic(GRAPH_PATH.parent / "floor-trigger-map.md", _render_floor_trigger_map(
        index.get("floor_trigger_map") or {}, index.get("specs") or {},
        kernel_provided=_is_consumer_build()))   # T-0849: consumer build → kernel-provided header note
    # T-9410 (SPEC-0096): the sibling derived view — the activation baseline-concern checklist
    # (init-walk SET + doc-checklist) from each spec's `init_concern` declaration. Same write site +
    # land-fold treatment as the floor map (in _BOOKKEEPING_ALLOWLIST / _DERIVED_MERGE_ARTIFACTS).
    # Identity-agnostic — no kernel/consumer header variance.
    write_text_atomic(GRAPH_PATH.parent / "activation-checklist.md",
                      _render_activation_checklist(index.get("specs") or {}))
    # T-10036 (SPEC-0128): the sibling derived view — the seed-and-grow CONCERN REGISTRY
    # (graph/concern-registry.json) from each spec's `concern:` block. Same write site + land-fold
    # treatment as the floor map / activation checklist (in _BOOKKEEPING_ALLOWLIST /
    # _DERIVED_MERGE_ARTIFACTS). Identity-agnostic — no kernel/consumer header variance.
    write_text_atomic(GRAPH_PATH.parent / "concern-registry.json",
                      _render_concern_registry(index.get("specs") or {}))
    # T-10038 (SPEC-0128 Rule 2 + born decision (i)): the sibling derived view — the born
    # yitc-ops.yaml TEMPLATE (graph/born-ops.yaml) from each concern's `born:`/`born_order:`
    # companion. Same write site + land-fold treatment as concern-registry.json (in
    # _BOOKKEEPING_ALLOWLIST / _DERIVED_MERGE_ARTIFACTS). Written BEFORE the concern surface check
    # reads it (cmd_graph_build) so the first-ever build is not chicken-and-egg. Identity-agnostic.
    write_text_atomic(GRAPH_PATH.parent / "born-ops.yaml",
                      _render_born_ops(index.get("specs") or {}))


def _write_audience_views(*, CANONICAL_DOCS, REPO_ROOT, _is_consumer_build, _render_audience_views,
                          write_text_atomic) -> dict:
    """T-10025 (SPEC-0127 §3): regenerate the THREE audience-scoped seed views (worker seed parts /
    controller supplement / worker-startup inventory) from the seed docs' `<!--AUDIENCE:...-->` section
    markers. Returns the rendered {filename: content} (empty dict when the guard skips).

    T-10625 (the T-10474 / T-10608 class): called by BOTH the explicit `cmd_graph_build` AND land's
    derived-regen (`_auto_rebuild_graph`) — NOT explicit-build-only. These views are PURELY-DERIVED
    (`DO NOT EDIT` banner, drift-checked), so SPEC-0074 §6's freshness doctrine covers them: a
    purely-derived artifact regenerates at BOTH seams and its paths ride `_BOOKKEEPING_ALLOWLIST` +
    `_DERIVED_MERGE_ARTIFACTS`. That doctrine explicitly CONTRASTS the explicit-build-only AGENTS.md
    read-order / placement-manifest regen — those stay explicit-only because they are AUTHORED files land
    must not clobber. Filing these DERIVED views on that AUTHORED side was the misclassification: a source
    edit under an `<!--AUDIENCE:-->` section that landed without a view regen (T-10601 f8c2d335f) left
    unfoldable drift on main, which ABORTed an unrelated land (T-10608) and got swept into an unrelated
    ship commit as an audit-post RED (T-10474). It also matches what SPEC-0127 §3 already declares these
    views to be — "the SIBLING pattern of graph/floor-trigger-map.md", which IS land-regenerated
    (`_write_graph_index`) + allowlisted.

    Engine-only + complete-handbook guard (a consumer / partial repo has no engine handbook of its own →
    skip; the generator never emits a PARTIAL view). Fail-loud on a malformed marker (`_AudienceFormatError`)
    — at land that surfaces via `_auto_rebuild_graph`'s existing failure-tolerant warn, the same as any
    other rebuild fault."""
    if _is_consumer_build() or not all((REPO_ROOT / n).exists() for n in CANONICAL_DOCS):
        return {}
    _hb = {n: (REPO_ROOT / n).read_text(encoding="utf-8") for n in CANONICAL_DOCS}
    views = _render_audience_views(_hb)
    for _fname, _content in views.items():
        write_text_atomic(REPO_ROOT / "graph" / _fname, _content)
    # T-10219: PRUNE an orphan worker-seed part (the seed shrank past a part boundary). Writing alone
    # would leave a stale `worker-seed-N.md` on disk that a Worker's chain-walk would still read.
    # `worker-seed-*.md` never matches part 1 (`worker-seed.md`), so the chain ENTRY is never removed.
    for _stale in (REPO_ROOT / "graph").glob("worker-seed-*.md"):
        if _stale.name not in views:
            _stale.unlink()
    return views


def _release_view_docs(*, CANONICAL_DOCS, ENGINE_ROOT) -> tuple:
    """The release-view input set, DERIVED from the existing single carriers (no second file list,
    audit-pre F1): the handbook files (CANONICAL_DOCS ← the one HANDBOOK_READ_ORDER carrier) PLUS
    the always-loaded floor-trigger-map seed AND the generated per-audience views (EVERY worker-seed part +
    controller-supplement) at their canonical paths — so a `-C` consumer reads its assembled VIEW as an
    IDENTITY-AGNOSTIC release-view artifact, not the id-carrying graph/ copy (T-10097, SPEC-0127 §4 +
    SPEC-0074 §7; same class as the floor-trigger-map inclusion — a generated graph/ file cut into
    release-view). `land` regenerates the release-view (test_t9513), so the cut lands in-task.
    T-10219: the worker-seed part COUNT is derived (`worker_seed_part_files`, off the emitted files), never
    re-declared here — a split seed publishes its WHOLE chain or the consumer Worker reads a truncated one.
    T-10625: the graph/ view names now come from the ONE carrier `audience_view_files` (which the land
    bookkeeping sets also read), minus `worker-startup-inventory.md` — that view is a build REPORT (§3c
    per-section audience + seed size + probe), not a seed a consumer reads, so it is deliberately NOT
    published. Same set + order as before; no second name list."""
    return (tuple(CANONICAL_DOCS) + ("graph/floor-trigger-map.md",)
            + tuple(f"{GRAPH_DIR}/{p}" for p in audience_view_files(ENGINE_ROOT / GRAPH_DIR)
                    if p not in _RELEASE_VIEW_UNPUBLISHED))


def _release_view_tidy(s: str) -> str:
    """Deterministic cleanup of the debris left by D-/T- id removal (SPEC-0074 §5e). Conservative —
    NEVER collapses leading indentation (so indented code/FSM blocks survive); only normalizes
    intra-line debris. Idempotent: the fixpoint loop converges (it only ever shrinks the string)."""
    prev = None
    while prev != s:
        prev = s
        s = re.sub(r"\(\s*(?:per|see)?\s*\)", "", s)        # (), (per ), (see )
        s = re.sub(r"\(\s*[,;/+&.\s—-]*\)", "", s)          # (, ), ( / ), ( + ), ( — )
        s = re.sub(r",\s*,", ",", s)                        # ", ,"
        s = re.sub(r"\(\s*[,;/+&]\s*", "(", s)              # "(, " / "( / "
        s = re.sub(r"\s*[,;/+&]\s*\)", ")", s)              # " ,)" / " / )"
    # orphaned connectors left at a clause boundary by id removal.
    s = re.sub(r"\b(?:per|see|supersedes|reaffirmed by|wired|shipped)\s*([,.;)])", r"\1", s)
    # T-9349 (SPEC-0074 §5e): an orphaned comma left IMMEDIATELY before a clause-terminator when a
    # connector-led id is stripped from RUNNING prose ("§4, shipped T-0140;" -> "§4, ;" once the word+id
    # go — the connector-word cleanup above must run FIRST, so this is post-loop). Debris-only — legit
    # prose never has a comma directly before `; . )` (a comma always precedes a clause), so this never
    # touches valid text. Does NOT touch `+` separators (the over-strip the T-9349 audit-post flagged);
    # those are handled debris-specifically at removal time (pass (d) connector-consume).
    s = re.sub(r",\s*([;.)])", r"\1", s)                    # orphaned comma before ; . ) -> drop the comma
    # collapse intra-line multi-spaces created by removal (NOT leading indent — guarded by (?<=\S)).
    s = re.sub(r"(?<=\S)[ \t]{2,}", " ", s)
    s = re.sub(r" +([,.;)])", r"\1", s)                     # space before punctuation
    s = re.sub(r"[ \t]+\n", "\n", s)                        # trailing whitespace at EOL
    return s


def _release_view_strip(text: str) -> str:
    """The identity-agnostic strip/abstract ruleset (SPEC-0074 §5) — a PURE, deterministic transform
    (no time/randomness, so re-gen is byte-identical). Removes dev-provenance (host paths, host tokens,
    `from: T-` trailers, D-/T- artifact citations) while PRESERVING the methodology prose AND the
    SPEC-NNNN ids (specs travel as core). Ordered passes."""
    s = text
    # (a) host paths → abstract placeholders (the specific repo path FIRST, then the generic home).
    #     The two OPERANDS are DERIVED from `host_paths.host_home()` rather than spelled as literals
    #     (T-12024). The RULESET is untouched — same passes, same order, same placeholders; only the
    #     host the operands name is read off the machine. That is also a correctness fix: a published
    #     copy on a foreign machine would otherwise strip a path that does not exist there and leak
    #     the one that does. Purity is unaffected — no time, no randomness — and on this host the
    #     operands are byte-identical to the literals they replace.
    _home = str(host_paths.host_home())
    s = s.replace(f"{_home}/projects/yitc-v2", "<repo-root>")
    s = s.replace(_home, "<host-home>")
    #     (a2) ANY OTHER user's home path (T-12042). Rule 4 has always required "NO `/home/dev` (or
    #     other host home) absolute paths", but the two operands above are derived from THIS host's
    #     home, so a path naming a DIFFERENT user (`/home/<someone-else>`) passed through untouched —
    #     under-implementing the rule's own stated bar. Measured at the first whole-tree publish check:
    #     of 38 travelling files carrying a host literal, 36 were cleaned by the operands above and 2
    #     survived solely because they name other people's homes. This closes the ruleset to the bar
    #     rule 4 already sets; it introduces no new rule. Same purity + idempotence (the placeholder
    #     contains `<`, which the user-segment class excludes, so a second pass matches nothing).
    s = re.sub(r"/home/[A-Za-z0-9._][A-Za-z0-9._\-]*", "<host-home>", s)
    # (b) host tokens — IPv4 / session-UUID + host-env names (SERVER_IP / SSH_*, incl. any `=value`
    #     tail, the env-dump leak class) scrubbed (defensive; absent from handbook source today).
    s = _RV_IPV4.sub("<ip>", s)
    s = _RV_UUID.sub("<session-id>", s)
    s = re.sub(r"\bSERVER_IP\b\s*=?[^\n]*", "<host-token>", s)
    s = re.sub(r"\bSSH_[A-Z]+\b\s*=?[^\n]*", "<host-token>", s)
    # (b2) provider/tool BRAND neutralization (CHARTER §P4b — provider-neutral methodology text; a
    #      consumer-facing handbook must name no provider/tool brand). Ordered longest/most-specific
    #      first so the bare catch-all never bites a compound token.
    s = re.sub(r"\bCLAUDE_CODE_[A-Z_]+\b", "<provider-session-env>", s)
    s = re.sub(r"\bCLAUDECODE\b", "<provider-session-env>", s)
    s = s.replace("CLAUDE.md", "<vendor-adapter>.md")
    s = s.replace(".claude", "<provider-config>")           # the provider config dir (~/.claude, etc.)
    s = re.sub(r"\bcodex\b", "<external-auditor>", s, flags=re.IGNORECASE)
    s = re.sub(r"\bAnthropic\b", "the provider", s, flags=re.IGNORECASE)
    s = re.sub(r"\bclaude\b", "the AI provider", s, flags=re.IGNORECASE)  # any residual bare brand word
    # (c) `from: T-XXXX` commit-trailer → abstract durable-artifact placeholder.
    s = re.sub(r"from:\s*T-\d{4,}\S*", "from: <durable artifact>", s)
    # (d) dev-provenance D-/T- citations removed (SPEC ids preserved). Possessive + connector forms
    #     first so no dangling "'s" / "per " survives; then any standalone id.
    s = re.sub(r"\b[DT]-\d{4,}'s\b", "", s)
    s = re.sub(r"\b(?:per|see)\s+[DT]-\d{4,}\b", "", s)
    # T-9349 (SPEC-0074 §5e): a D-/T- id reached from RUNNING prose by a `+`/`,` connector — consume
    # the connector WITH the id it joined, so removal leaves no orphaned-separator debris (the
    # release-view/GRAPH.md recap rows: "refined + D-0007 + D-0009" -> "refined"; "4 edges, T-1047;"
    # -> "4 edges;"). Debris-shape-specific: it matches ONLY a connector ADJACENT to a removed id, so a
    # legitimate `+`/`,` separator NOT next to a stripped id (e.g. "CHARTER + AGENTS + LIFECYCLE") is
    # untouched. Runs before the bare sweep so a connector-led id never falls through to leave the connector.
    s = re.sub(r"\s*[,+]\s*\b[DT]-\d{4,}\b", "", s)
    s = _RV_DT_ID.sub("", s)
    # (d2) V1-incident cites (T-1014, acceptance: no V1-incident cites) — V1 tracker bug-ids
    #     (`B-NNNNN`) AND incident-timestamp references (an ISO-8601 instant cited as deviation/
    #     incident provenance) are dev provenance a consumer must not read. Connector-bearing forms
    #     first (drop the whole "— incident <ts>" / "per B-NNNN" phrase), then any standalone token;
    #     a bare ISO instant left over (an incident timestamp without the word) is swept last.
    s = re.sub(r"\s*[—-]\s*incident\s+\d{4}-\d{2}-\d{2}T[\d:]+Z?", "", s)
    s = re.sub(r"\bincident\s+\d{4}-\d{2}-\d{2}T[\d:]+Z?", "", s)
    s = re.sub(r"\b\d{4}-\d{2}-\d{2}T[\d:]+Z\b", "", s)
    s = re.sub(r"\bB-\d{4,6}'s\b", "", s)
    s = re.sub(r"\b(?:per|see)\s+B-\d{4,6}\b", "", s)
    s = re.sub(r"\bB-\d{4,6}\b", "", s)
    # (e) tidy the debris deterministically.
    return _release_view_tidy(s)


# T-10766 (X-0613) — the floor map's retrieval form in the RELEASE VIEW.
# A bound floor row names a KERNEL spec by BARE id (`→ read `SPEC-0005``). The release-view copy of
# graph/floor-trigger-map.md is the ALWAYS-LOADED seed a `-C` CONSUMER session reads (session start:
# "always-loaded seed also: graph/floor-trigger-map.md (same engine release-view root)"), and in a
# consumer session a bare id resolves consumer-own-FIRST (SPEC-0092 / T-0860 — correct and deliberate,
# NOT changed here). Five registered consumers own their OWN SPEC-0005 and boomrocket also owns
# SPEC-0073 — both ids named by always-loaded floor rows — so a consumer obeying the row got a
# PLAUSIBLE WRONG document, silently, at every rule-authoring moment. Emitting SPEC-0092's EXISTING
# kernel-explicit escape (no second mechanism) makes the row's meaning true by construction of the
# command it emits. Consumer-facing ONLY: the ENGINE's own committed graph/floor-trigger-map.md is
# untouched (--kernel is a no-op in the engine's own session), so the SPEC-0033 floor-map-drift
# invariant is trivially satisfied. Pure, deterministic, idempotent — a sibling of the strip ruleset.
_RV_FLOOR_BARE_ROW = re.compile(r"(?m)^(- \*\*[^*]+\*\* \(`[^`]+`\) → read )`(SPEC-\d{4})`")
_RV_FLOOR_HOWTO = "read the listed `retrieved` spec(s) via `bin/yitc-v2 graph query <SPEC-ID>`."
_RV_FLOOR_HOWTO_KERNEL = (
    "read the listed `retrieved` spec(s) via `bin/yitc-v2 graph query --kernel <SPEC-ID>` — the\n"
    "kernel-explicit form (SPEC-0092), because a bare id resolves consumer-own-first in a `-C`\n"
    "session and this project may own a spec at the same id.")


# T-11992 (X-1228) — the RUNTIME-PRINTED sibling of the release-view rewrite just below.
# A verb that PRINTS a retrieval pointer names a KERNEL spec by BARE id (`yitc-v2 graph query
# SPEC-0043`). Under `-C` a bare id resolves consumer-own-FIRST (SPEC-0092 / T-0860 — correct and
# deliberate, NOT changed here), so a consumer that owns a spec at the same id reads a PLAUSIBLE WRONG
# body off the hint: measured on aiseller 2026-09-02 (events.jsonl#ts=2026-09-02T11:34:49Z) off the
# `plan file` next-hint, where the consumer's OWN SPEC-0043 is an advertising write-authorization
# contract and the kernel's is the plan-draft front-load doctrine.
#
# SPEC-0092's "Doc convention" (§Internal) leaves AUTHORED handbook prose bare — the reader re-issues
# with `--kernel` on a collision. That convention bounds STATIC prose, whose author cannot know the
# reader's realm. A RENDERED surface can: `_release_view_floor_kernel_explicit` (T-10766) already
# renders the always-loaded floor map kernel-explicit for exactly that reason, and the dispatch
# preamble (`dispatch.py#_build_worker_preamble(kernel_flag=...)`, T-10717) does the same per TARGET.
# This helper is that same seam per SESSION — SPEC-0092's EXISTING escape, no second mechanism, and no
# change to bare-lookup resolution.
#
# The realm predicate the CALLER passes is `_is_consumer_build()` (T-0952), never a bare
# `REPO_ROOT != ENGINE_ROOT`: an engine LINKED WORKTREE shares the git common-dir and IS the engine, so
# the path test would emit `--kernel` from every engine task worktree.
def spec_query_hint(spec_id: str, *, is_consumer: bool = False, cli: str = "yitc-v2") -> str:
    """Render a spec-retrieval POINTER for the CURRENT session's realm (SPEC-0092 / T-11992).

    Consumer session (`is_consumer`) → the kernel-explicit `--kernel` form, so the printed command
    fetches the KERNEL contract the pointer means. Engine's own session → the bare form (own IS the
    kernel; `--kernel` would be a no-op there, and the bare form is what every engine-side test and
    reader already sees). `cli` is the caller's own EXECUTABLE PREFIX ONLY —
    never the `graph query` words themselves, which this helper always supplies. Each site keeps the
    exact form it already prints (`yitc-v2` / `bin/yitc-v2` / an engine-resolved
    `<engine>/bin/yitc-v2 -C <repo>` form), and a site whose text already reads a BARE `graph query
    SPEC-XXXX` passes `cli=""` to get exactly that back — NOT `cli="graph"`, which would render the
    doubled `graph graph query …` (audit-pre F2).

    Pure + deterministic: no I/O, no globals. Defaults reproduce today's engine bytes exactly."""
    prefix = f"{cli} " if cli else ""
    return f"{prefix}graph query {'--kernel ' if is_consumer else ''}{spec_id}"


def _release_view_floor_kernel_explicit(text: str) -> str:
    """Rewrite the release-view floor trigger-map's BARE spec ids into the SPEC-0092 kernel-explicit
    retrieval command (T-10766). Pure + idempotent (an already-explicit row has no bare-id form left to
    match). Applied ONLY to the floor-map doc in the release-view cut — see the block comment above."""
    return _RV_FLOOR_BARE_ROW.sub(
        r"\1`bin/yitc-v2 graph query --kernel \2`",
        text.replace(_RV_FLOOR_HOWTO, _RV_FLOOR_HOWTO_KERNEL))


def _build_release_view(*, ENGINE_ROOT, _die, _release_view_docs) -> list:
    """Pure builder (SPEC-0074): return [(rel_path, content_str)] for the identity-agnostic release
    view, cut from the ENGINE's own handbook (the single writable source — read from ENGINE_ROOT, NEVER
    a rebound REPO_ROOT). Deterministic: same source → identical output. The neutral GENERATED banner is
    prepended to each file (a fixed token-free literal)."""
    out = []
    for doc in _release_view_docs():
        src = ENGINE_ROOT / doc
        if not src.exists():
            # FAIL-HARD (audit-post F2): completeness is an INVARIANT (SPEC-0074 §4), not best-effort —
            # a silently-dropped source would emit an incomplete view that still passes grep-clean.
            _die(f"release-view: expected handbook source {doc!r} missing under {ENGINE_ROOT} — the "
                 f"completeness invariant requires all {len(_release_view_docs())} sources present "
                 "(SPEC-0074).")
        content = RELEASE_VIEW_BANNER + _release_view_strip(src.read_text(encoding="utf-8"))
        if doc == f"{GRAPH_DIR}/floor-trigger-map.md":
            content = _release_view_floor_kernel_explicit(content)   # T-10766 — kernel-explicit rows
        out.append((f"{RELEASE_VIEW_DIR}/{doc}", content))
    return out


# ── T-0883 (SPEC-0073 §8 active-only export guard): the EXPLICIT release/export spec slice ───────────
# A consumer pins the released kernel; the methodology specs travel as part of core (SPEC-0074 §4). But
# the kernel's OWN evolution history — superseded / withdrawn / rejected / draft specs — is V2-SELF and
# must NEVER travel (SPEC-0073 §1; T-0874 manifest FLAGGED A-2). The placement realm already encodes
# this via each non-active spec's `travels: v2-self` marker (backfilled T-0890), but that relies on the
# marker being present; a forgotten backfill on a future superseded spec would default to kernel
# (`_SPEC_CLASS_DEFAULT`) and leak. So the export slice is filtered ACTIVE-ONLY by CONSTRUCTION here,
# and `_release_spec_slice_violations` is the report-at-land structural guard (peer of _release_view_drift).
def _release_view_spec_ids(*, SPECS_DIR, _read_yaml, _resolve_placement) -> list:
    """The EXPLICIT export spec slice (SPEC-0073 §8 / T-0883): sorted SPEC-NNNN ids that travel as kernel
    in the release/export, filtered ACTIVE-ONLY — `status == active` AND `_resolve_placement` == kernel.
    The single source of "which specs the release ships". Pure + deterministic (same corpus → identical
    list); reads specs/ off disk. A non-active spec (superseded/withdrawn/rejected/draft) NEVER appears,
    regardless of its `travels:` marker — the status guard is structural, not marker-dependent."""
    ids = []
    for p in state.scan_specs(SPECS_DIR):   # SPEC-* glob excludes _template.yaml
        d = _read_yaml(p) or {}
        sid = d.get("id")
        if not sid:
            continue
        if d.get("status") == "active" and _resolve_placement(f"specs/{sid}", d.get("travels")) == "kernel":
            ids.append(sid)
    return sorted(ids)


def _release_spec_slice_violations(*, _is_consumer_build, SPECS_DIR, _read_yaml,
                                   _resolve_placement, _release_view_spec_ids) -> list:
    """Structural guard (SPEC-0073 §8) — the report-at-land enforcement of the active-only export filter,
    peer of `_release_view_drift`: flag any spec whose resolved placement is `kernel` but whose status is
    NOT `active` — i.e. a non-active spec (the kernel's own evolution history) that WOULD travel into the
    export slice. GREEN when every kernel-realm spec is active (the backfilled corpus); RED catches a
    future forgotten `travels: v2-self` backfill on a superseded/withdrawn/draft spec BEFORE it leaks.
    Returns [] or {kind, detail} entries. Engine-only (a consumer authors its own specs).

    WIRING (audit-post F1, T-0883): this guard CONSUMES `_release_view_spec_ids()` — the SAME helper a
    future spec-materializing exporter (T-0866's spec slice) calls — so the active-only filter is LIVE in
    production at every land, not test-only. The kernel pin would carry every kernel-realm spec; any
    kernel-realm spec ABSENT from the active-only slice is excluded for a STATUS reason (the slice is
    active∩kernel), i.e. it is the kernel's own evolution history about to leak. Checking
    `kernel-realm \\ slice` makes the helper the single production source of "what travels"."""
    if _is_consumer_build():
        return []
    travels = set(_release_view_spec_ids())            # active ∩ kernel — the production export slice
    out = []
    for p in state.scan_specs(SPECS_DIR):
        d = _read_yaml(p) or {}
        sid = d.get("id")
        if not sid:
            continue
        # a kernel-realm spec NOT in the active-only slice = excluded for a STATUS reason → would leak —
        # EXCEPT `proposed`, a FORWARD kernel head legitimately excluded by status (it becomes active and
        # TRAVELS; T-0883 active-only filter handles the status-exclusion, so it stays kernel-realm,
        # unmarked). Only TERMINAL non-active (superseded/withdrawn/retired/rejected/draft) is dead history
        # that must carry travels:v2-self. Reconciles this guard with the active-only filter (deviation
        # fingerprint conformance-leak-check-vs-test0890-contradict-on-proposed-kernel-spec-post-T0883).
        status = d.get("status")
        if sid not in travels and status != "proposed" \
                and _resolve_placement(f"specs/{sid}", d.get("travels")) == "kernel":
            out.append({"kind": "release-spec-slice-leak",
                        "detail": f"{sid} (status={status!r}) resolves to the kernel placement realm but is "
                                  "EXCLUDED from the active-only export slice — a non-active spec would "
                                  "TRAVEL into the export (SPEC-0073 §1/§8: non-active never travels). "
                                  f"Mark `travels: v2-self` on {sid} (then `yitc-v2 graph build`)."})
    return out


def _release_view_drift(*, _is_consumer_build, ENGINE_ROOT, _build_release_view) -> list:
    """Freshness check (SPEC-0074 §6) — the peer of `_floor_map_drift`: the committed release-view/ tree
    MUST EXACTLY equal the freshly re-derived view, checked in BOTH directions (audit-post F1) — content
    mismatch, a MISSING expected file, AND an EXTRA/stale file present under release-view/ that the
    generator no longer emits (e.g. a renamed/removed handbook doc). Returns [] or {kind, detail} entries.
    Engine-only (a consumer has no release-view to check); REPORT-AT-LAND via `graph conformance`."""
    if _is_consumer_build():
        return []
    out = []
    expected = {rel: content for rel, content in _build_release_view()}
    for rel, content in expected.items():
        path = ENGINE_ROOT / rel
        if not path.exists():
            out.append({"kind": "release-view-drift",
                        "detail": f"MISSING committed {rel} (run `yitc-v2 graph build` / `graph release-view`)"})
        elif path.read_text(encoding="utf-8") != content:
            out.append({"kind": "release-view-drift",
                        "detail": f"committed {rel} != the regenerated view "
                                  "(run `yitc-v2 graph build` / `graph release-view` to refresh)"})
    # the OTHER direction — an extra/stale file under release-view/ the generator no longer emits.
    rv_root = ENGINE_ROOT / RELEASE_VIEW_DIR
    if rv_root.is_dir():
        for p in sorted(rv_root.rglob("*")):
            if p.is_file():
                # SPEC-0131 Rule 3 — a CONCURRENT land's graph build may leave an in-flight
                # atomic-write temp artifact under release-view/ (write_text_atomic's mkstemp:
                # name = f".{target}.XXXXXX.tmp"). That is a NORMAL condition under raised
                # concurrency, never a stale-view drift — do NOT flag it UNEXPECTED (the
                # 2026-07-03 false-abort). Real release-view files are handbook doc names, never
                # this shape, so the skip masks no legitimate stale file.
                # T-10330: the INDEX-side half of this same classification is `.gitignore`'s
                # `/release-view/**/.*.tmp` — it keeps `git add -A` from sweeping the transient
                # into a commit (T-10081). Both halves must agree on the shape; changing one
                # without the other re-opens the leak.
                if p.name.startswith(".") and p.name.endswith(".tmp"):
                    continue
                rel = str(p.relative_to(ENGINE_ROOT))
                if rel not in expected:
                    out.append({"kind": "release-view-drift",
                                "detail": f"UNEXPECTED file {rel} under release-view/ — not in the "
                                          "generated set (a stale/renamed view file; remove it)"})
    return out


# ── T-11326: graph-build RESULT CACHE (SPEC-0031 §Build tool step 0) ────────────────────────────
# The build is a PURE function of the checkout: three consecutive builds on an unchanged tree here
# produced the identical index serialization (blake2b-64 5bb84ffcc1223515 x3). So an unchanged tree
# need not be recomputed — measured median 4.02 s / p90 5.58 s per build in this engine, invoked on
# every land, audit, close and test run (12050 land-triggered builds against 7262 lands = 1.66 per
# land). The cache is CONTENT-EXACT, its miss is always a FULL build, and it reports its own hit rate
# (the T-10078 / T-11222 prior art: a cache that wrote 1135 markers, read none across 1390 lands, and
# was indistinguishable from a working one until someone went looking).
#
# PURE + INJECTED, per this module's identity-agnostic contract: git access arrives as `run_git`.
INDEX_CACHE_SCHEMA = 2
# The cache lives under the checkout's GIT DIR, never in the working tree — a working-tree file would
# show as untracked dirt in any repo whose .gitignore does not already name it, and `worktree new`
# refuses on main dirt (measured: it broke the blank-consumer conformance lifecycle outright). Prior
# art: the pinned-verify cache used the same location (T-10078).
#
# T-11471 — TWO CHANGES, both about CONCURRENT access to that one location, neither about the key.
#
# (1) ONE DOCUMENT, ATOMICALLY REPLACED. The cache was a PAIR of files — the index payload and a meta
#     header naming the key it was built from — written in that order with plain writes. The pair
#     carried a cross-file invariant, and nothing held it: two stores interleaving leave a meta naming
#     key A beside a payload built for key B, and the next reader matches key A and is served B. That
#     is a stale hit reached WITHOUT any staleness in the key — the content-exact key argument is
#     sound for ONE reader and says nothing about concurrent writers. It is not hypothetical: the
#     pinned/last-green leg runs its suite as hundreds of subprocesses inside ONE worktree, many of
#     which call `graph_build_index()` directly, and the measured symptom was a rotating cast of
#     "SPEC-XXXX must be an indexed spec" failures — a build returning an index missing a spec that is
#     on disk. So the key and the index it describes now live in the SAME object, written to a temp
#     file in the same directory and `os.replace`d into place. With one document there is no
#     cross-file invariant left to violate, and a reader observes the whole previous document or the
#     whole new one — never a partial write, never a mismatched pair. A LOCK was the explicitly worse
#     option and is not what this does.
# (2) PER-CHECKOUT IDENTITY. The filename is namespaced by the resolved checkout path, so two
#     checkouts that resolve to the SAME git dir cannot contend on one file. For a linked worktree
#     `rev-parse --absolute-git-dir` already answers per-worktree, so this is a second, independent
#     reason the isolation holds rather than the load-bearing one — it covers the checkouts where that
#     resolution does NOT separate them (a plain nested checkout, any future common-dir resolution).
#
# Both properties the original design earned are untouched: the file is still under the git dir (never
# working-tree dirt), and every failure path still falls through to a full build.
INDEX_CACHE_PREFIX = "yitc-graph-index-cache"
# The self-tuning gate: consult the cache only where a hit can pay for the key it costs. Both terms
# are MEASURED per repo (the meta header), so ONE kernel code path serves a 4.02 s engine and a 0.01 s
# cardlab without a per-project mechanism or a threshold constant that fits nobody.
INDEX_CACHE_MIN_RATIO = 3
# The ONE named non-input, excluded from the key with its proof: the graph-slim cut (T-0491) removed
# every journal-parsing pass from the build, and `graph_build_index`'s signature takes no EVENTS_PATH
# at all — so the journal is provably not read here, while it is appended by EVERY command (including
# the `graph_built` event of the build itself). Left in, it would move the key on every single
# invocation and the cache could never hit once — measured: 4/4 misses on identical trees.
# Deliberately a NAMED path with a proof, not a heuristic: anything unproven stays IN the key.
INDEX_CACHE_NON_INPUTS = ("events.jsonl", ".yitc/events.jsonl")
# The second named non-input, on the same terms: `.yitc/` is machine-local operational state by
# construction (it is `_BORN_GITIGNORE_LINES[0]` — born-ignored in every consumer), holding dispatch
# logs, findings and sync cursors that no build pass reads. In a repo where it is not ignored its
# churn would move the key for nothing. (The cache itself no longer lives there — see above.)
INDEX_CACHE_NON_INPUT_DIRS = (".yitc/",)

# "hit" | "miss" | "skip" | "off" | None — the state of the LAST build in this process. It is NOT a
# key on the index dict on purpose: `_write_graph_index` dumps the index verbatim, so a hit/miss key
# there would flap inside the committed graph/index.json on every build.
LAST_INDEX_CACHE_STATE: "str | None" = None


def _index_cache_dir(repo_root, *, run_git) -> "object | None":
    """The checkout's git dir — resolved via git, never composed from a path literal, so a linked
    worktree (whose `.git` is a FILE) and a bare/relocated gitdir both resolve correctly."""
    r = run_git(["rev-parse", "--absolute-git-dir"], repo_root)
    if r.returncode != 0 or not r.stdout.strip():
        return None
    d = type(repo_root)(r.stdout.strip())
    # VALIDATE the answer before treating it as a path. A real git dir always exists already, so an
    # answer that is not an existing directory is not one — and this is not defensive decoration: the
    # `run_git` seam is injected and the test suite stubs it, so a stub's canned stdout was taken as a
    # directory name and two files were created (and committed) under a path spelled out of an
    # auditor's verdict text. Caught at audit-post, high severity. Never write anywhere git did not
    # actually name.
    if not d.is_dir():
        return None
    return d


def _index_cache_file(cache_dir, repo_root):
    """The ONE cache document for THIS checkout, inside the git dir `cache_dir`.

    Namespaced by a short digest of the RESOLVED checkout path (T-11471): two checkouts that resolve
    to the same git dir get different files rather than contending on one. `resolve()` is what makes
    the identity stable — the same checkout reached by a symlink or a relative path must name the same
    file, or the namespacing would hand one checkout two caches and halve its hit rate."""
    try:
        ident = hashlib.blake2b(str(repo_root.resolve()).encode(), digest_size=6).hexdigest()
    except OSError:
        ident = hashlib.blake2b(str(repo_root).encode(), digest_size=6).hexdigest()
    return cache_dir / f"{INDEX_CACHE_PREFIX}-{ident}.json"


def _shared_git_dir_file_mode(cache_dir, *, repo_root, run_git) -> "int | None":
    """The mode a file written into THIS git dir should carry, per the sharing the REPOSITORY
    DECLARES — or None when it declares none (the caller then leaves today's owner-only mode alone).

    `tempfile.mkstemp` hardcodes 0600 and `os.replace` preserves the temp file's mode, so every cache
    document lands unreadable to anyone but its author — while git, writing HEAD and config into the
    SAME directory as the SAME author, writes them 0664 there. That asymmetry is the defect (T-11660):
    one writer ignoring the sharing the repository already declares. It is not fixed by picking a
    looser constant — it is fixed by reading the same signals git reads, in git's own order:

      1. `core.sharedRepository` — git's EXPLICIT declaration (false/umask/0 · true/group/1 ·
         all/world/everybody/2 · a literal octal mask).
      2. Failing that, the GIT DIR'S OWN BITS. The two repos this was measured on carry no
         `core.sharedRepository` at all: their `.git` is `drwxrwsr-x` (setgid + group rwx) and HEAD's
         0664 comes from git honouring the umask inside a directory shaped for a group. So setgid
         WITH group-read is the declaration, and what it grants MIRRORS the dir — group write only if
         the dir is group-writable, other read only if the dir is other-readable. Mirroring is what
         keeps this from being a blanket widen: a git dir that declares nothing gets nothing.

    The base is the umask-respecting default (`0o666 & ~umask`), identical to the T-10182
    `write_text_atomic` fix for this same mkstemp trap — so in a shared checkout the result equals
    what git gives HEAD there, and never exceeds what the user's umask permits.
    """
    granted = None                       # group/other bits the repository DECLARES, if any
    try:
        r = run_git(["config", "--get", "core.sharedRepository"], repo_root)
        raw = (r.stdout or "").strip().lower() if r.returncode == 0 else ""
    except (OSError, AttributeError, TypeError, ValueError):
        raw = ""
    if raw:
        if raw in ("false", "umask", "0"):
            return None                  # explicitly NOT shared — honour the declaration as written
        if raw in ("true", "group", "1"):
            granted = 0o060
        elif raw in ("all", "world", "everybody", "2"):
            granted = 0o064
        else:
            try:
                granted = int(raw, 8) & 0o066
            except ValueError:
                granted = None           # unparseable → fall through to the dir's own bits
    if granted is None:
        try:
            dir_mode = os.stat(cache_dir).st_mode
        except OSError:
            return None
        if not (dir_mode & _stat.S_ISGID and dir_mode & _stat.S_IRGRP):
            return None                  # no declared sharing → today's mode, unchanged
        granted = 0o040
        if dir_mode & _stat.S_IWGRP:
            granted |= 0o020
        if dir_mode & _stat.S_IROTH:
            granted |= 0o004
    if not granted:
        return None
    cur = os.umask(0)
    os.umask(cur)
    granted &= ~cur                      # never grant what the user's own umask withholds (git parity)
    return (0o600 | granted) if granted else None


def repo_state_fingerprint(root, *, run_git) -> "str | None":
    """Content-exact fingerprint of a git checkout's FULL state. None = cannot be determined (→ miss).

    Three terms, and the breadth is the point — the build reads the artifact trees, the handbook docs,
    the code files its `implements:` anchors resolve against, the git history its drift warnings walk,
    AND its own builder source, so anything narrower could serve a stale index:
      1. `HEAD` — covers the history the anchor-drift/freshness warnings are derived from. This term
         is DELIBERATELY over-broad: those warnings actually depend on each artifact's own last-touch
         commit, so a commit touching NOTHING the build reads (a journal-only bookkeeping commit)
         still invalidates. A precise substitute would have to reason about history rewrites that
         leave the tree identical, and a stale hit is the one unacceptable failure of this mechanism —
         so the conservative term stands, and the reported hit rate is what says whether it costs
         too much;
      2. `git ls-files -s` — mode + blob sha + path for every tracked file, i.e. the whole committed
         tree including bin/ (the builder itself);
      3. the hashed CONTENT of every path git reports dirty or untracked — because (2) reflects the
         git index, not the working tree.
    CONTENT, never mtime/size: a stale hit is the only unacceptable failure of this mechanism, and a
    stat-shaped key can repeat across a checkout that changed."""
    h = hashlib.blake2b(digest_size=20)
    head = run_git(["rev-parse", "HEAD"], root)
    if head.returncode != 0:
        return None
    h.update(b"head\0" + head.stdout.strip().encode())
    ls = run_git(["ls-files", "-s"], root)
    if ls.returncode != 0:
        return None
    tree = "\n".join(ln for ln in ls.stdout.splitlines()
                     if not any(ln.endswith("\t" + x) for x in INDEX_CACHE_NON_INPUTS))
    h.update(b"tree\0" + tree.encode())
    st = run_git(["status", "--porcelain", "--untracked-files=all"], root)
    if st.returncode != 0:
        return None
    dirty = []
    for line in st.stdout.splitlines():
        if len(line) < 4:
            continue
        p = line[3:]
        if " -> " in p:                       # a rename: both sides matter
            dirty.extend(x.strip('"') for x in p.split(" -> "))
        else:
            dirty.append(p.strip('"'))
    dirty = [r for r in dirty
             if r not in INDEX_CACHE_NON_INPUTS
             and not any(r.startswith(x) for x in INDEX_CACHE_NON_INPUT_DIRS)]
    for rel in sorted(set(dirty)):
        h.update(b"dirty\0" + rel.encode() + b"\0")
        p = root / rel
        try:
            if p.is_file():
                h.update(hashlib.blake2b(p.read_bytes(), digest_size=20).digest())
            else:
                h.update(b"absent-or-dir")    # a deletion / dir entry is itself part of the state
        except OSError:
            return None                       # unreadable input → refuse to key it (fail to a miss)
    return h.hexdigest()


def _index_cache_read_doc(path) -> "dict | None":
    """The whole document, or None (→ an ordinary miss). Absent, unreadable, truncated mid-write by a
    reader racing a non-atomic writer that predates this schema, or written by a foreign version — all
    are the same fail-safe answer. A document that survives this returns a key and the index BUILT FROM
    THAT KEY, because they were written together.

    Reading the whole document to answer the consult gate (which needs only `build_ms`/`key_ms`) costs
    one JSON parse up front: MEASURED at 9 ms for this engine's 1.14 MB index, against a 4.02 s median
    build and a ~250 ms fingerprint. And it is self-limiting where it would matter — a repo cheap
    enough for the gate to SKIP has a small corpus, hence a small document."""
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(doc, dict) or doc.get("v") != INDEX_CACHE_SCHEMA:
        return None
    return doc


def index_cache_lookup(repo_root, *, run_git, extra_terms=()) -> tuple:
    """Decide whether to consult the cache, and serve a hit if the key matches.

    Returns `(index_or_None, key_or_None, consulted, key_ms)`. Fail-safe by construction: EVERY
    failure path returns a None index, which the caller treats as an ordinary miss and rebuilds in
    full. `extra_terms` carries inputs outside this checkout — on a `-C` consumer build the ENGINE
    checkout's own fingerprint, since the build reads engine specs and patterns.

    The consult gate reads the PREVIOUS build's measured cost from the meta header: a repo whose build
    is cheap relative to its own fingerprint stops computing the fingerprint entirely and pays nothing
    but one small file read. The header's `build_ms` is refreshed on every build, so a corpus that
    grows past the ratio re-arms itself with no config change."""
    cache_dir = _index_cache_dir(repo_root, run_git=run_git)
    if cache_dir is None:
        return None, None, True, None
    doc = _index_cache_read_doc(_index_cache_file(cache_dir, repo_root))
    if doc is not None:
        build_ms, key_ms = doc.get("build_ms"), doc.get("key_ms")
        if (isinstance(build_ms, (int, float)) and isinstance(key_ms, (int, float))
                and build_ms < INDEX_CACHE_MIN_RATIO * max(key_ms, 1)):
            return None, None, False, None      # inert here BY MEASUREMENT — no fingerprint computed
    t0 = time.monotonic()
    key = repo_state_fingerprint(repo_root, run_git=run_git)
    if key is None:
        return None, None, True, None
    if extra_terms:
        h = hashlib.blake2b(digest_size=20)
        h.update(key.encode())
        for t in extra_terms:
            h.update(b"\0" + str(t).encode())
        key = h.hexdigest()
    key_ms = int((time.monotonic() - t0) * 1000)
    if doc is None or doc.get("key") != key:
        return None, key, True, key_ms
    # The index comes from the SAME document the key was just matched in, so it is BY CONSTRUCTION the
    # one that key describes — the property the two-file layout could not hold under concurrency.
    index = doc.get("index")
    if not isinstance(index, dict) or not index:
        return None, key, True, key_ms
    return index, key, True, key_ms


def index_cache_store(repo_root, index, *, key, key_ms, build_ms, run_git) -> None:
    """Persist the freshly-built index + refresh the meta header. Best-effort — never raises.

    The payload is the JSON serialization, so a later hit returns exactly what `graph/index.json`
    holds (the `datetime.date` values in three legacy plan frontmatters normalize to ISO strings, as
    they already do on disk). `key=None` means the consult gate skipped fingerprinting: the payload
    is left alone and only `build_ms` is refreshed, which is what lets a growing corpus re-arm. A
    left-behind payload stays SAFE to serve because the key is content-exact — if it ever matches
    again, the tree really is the one it was built from."""
    cache_dir = _index_cache_dir(repo_root, run_git=run_git)
    if cache_dir is None:
        return
    path = _index_cache_file(cache_dir, repo_root)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        doc = _index_cache_read_doc(path) or {}
        if key is not None:
            # The key and the index it describes are set TOGETHER and published in ONE atomic replace
            # below — never as two writes another process can observe half of (T-11471).
            doc["key"], doc["index"] = key, index
            # Keep the LOWEST key cost ever measured, not the latest sample. A key measurement is
            # never faster than the key's true cost — machine load can only inflate it — so a single
            # spike would otherwise latch the gate off, and the gate cannot re-measure while it is
            # skipping, which is precisely the silently-dead-cache failure this mechanism must not
            # reproduce. Observed once here: a 4266ms build recorded `skip` after one slow sample
            # under load average 15. A genuinely growing corpus still re-arms, because build cost and
            # key cost both scale with it and the RATIO is what the gate reads.
            prior = doc.get("key_ms")
            doc["key_ms"] = min(key_ms, prior) if isinstance(prior, (int, float)) else key_ms
        doc["v"], doc["build_ms"] = INDEX_CACHE_SCHEMA, build_ms
        _index_cache_publish(
            path, doc,
            mode=_shared_git_dir_file_mode(cache_dir, repo_root=repo_root, run_git=run_git))
    except (OSError, TypeError, ValueError):
        pass


def _index_cache_publish(path, doc, *, mode=None) -> None:
    """Publish the document ATOMICALLY: serialize to a uniquely-named temp file in the SAME directory,
    then `os.replace` it over the target (T-11471).

    Same directory so the rename is same-filesystem, which is what makes `os.replace` atomic. A reader
    therefore sees the whole previous document or the whole new one, and a writer that dies mid-way
    leaves the previous document intact rather than a truncated file. The temp file is removed on any
    failure, so a failed store leaves nothing behind but the cache it did not update — the fail-safe
    miss, unchanged.

    `mode` (T-11660) is the mode the repository's DECLARED sharing implies for a file in its git dir
    (`_shared_git_dir_file_mode`); None — a repository declaring no sharing — keeps mkstemp's
    owner-only default, byte-for-byte today's behaviour. It is applied to the TEMP FILE BEFORE the
    replace, never to the target after, so atomicity is untouched and no reader ever sees a
    half-permissioned document. A chmod that fails is SWALLOWED: the document still publishes. A
    permission problem must never become a build failure — an unreadable cache MISSES, and a miss is
    fail-safe by this cache's own contract (SPEC-0031 §Build tool)."""
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, sort_keys=True, ensure_ascii=False, default=_json_default)
        if mode is not None:
            try:
                os.chmod(tmp, mode)
            except OSError:
                pass
        os.replace(tmp, str(path))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def graph_cache_report_lines(rows) -> list:
    """PURE fold of `graph_built` event payloads into the ONE report line (SPEC-0031 §Build tool).

    Report-only, and DELIBERATELY NOT suppressed-when-clean — unlike every other land-tail signal. A
    0% rate and an inert-by-measurement repo both PRINT, because the failure this exists to prevent is
    exactly the one where a dead cache and a working one look identical from outside (T-10078 wrote
    1135 markers, read none across 1390 lands, and stayed invisible until someone went looking —
    T-11222). Silence here means only one thing: no build has reported a cache state at all."""
    states = [d.get("cache") for d in rows if isinstance(d, dict) and d.get("cache")]
    states = states[-200:]
    if not states:
        return []
    n = len(states)
    hits = states.count("hit")
    consulted = hits + states.count("miss")
    skipped = states.count("skip")
    if consulted:
        pct = round(100.0 * hits / consulted)
        line = (f"land: graph-build cache — {hits}/{consulted} hit ({pct}%) over the last {n} build(s)")
        if skipped:
            line += f"; {skipped} inert (build too cheap to key)"
    else:
        line = (f"land: graph-build cache — inert in this repo over the last {n} build(s): the build "
                f"costs less than {INDEX_CACHE_MIN_RATIO}x its own key, so it is never consulted")
    return [line]


def graph_build_index(*, SPECS_DIR, TASKS_DIR, DECISIONS_DIR,
                      PATTERNS_DIR, PLANS_DIR, IDEAS_DIR, ERRORS_DIR, SCENARIOS_DIR, LESSONS_DIR, REPO_ROOT,
                      BINDING_FLOOR_TOKEN, CANONICAL_DOCS, KERNEL_NAME, KERNEL_DERIVED_LAYERS,
                      _read_yaml, _resolve_implements_anchor, _anchor_drift_warning, _anchor_file,
                      _id_from_artifact_ref, _pattern_frontmatter, _is_consumer_build,
                      _build_binding_views, _file_has_symbol_space=None,
                      _kernel_spec_ids=None, _kernel_spec_statuses=None) -> dict:
    # T-11004: the `scenario_binding_test_green` param (T-1048) is REMOVED, not defaulted — do not
    # re-add it. It was an OPTIONAL callable sid->bool that no caller in any repository ever supplied,
    # so every scenario read False and the `live` status it gated was unreachable everywhere. The
    # retirement (consult-settled) took the state and the input together; the surviving spec-status
    # reading is the scenario node's `cites_all_active` field. Removing the param rather than leaving
    # it inert is deliberate: an ignored seam reads as plumbing that works.
    # T-0491: the graph-slim cut drops the task / decision / audit_verdict / commit / event node-types
    # (and the from / emitted_by / audited edges), so `tasks` / `decisions` / `audits` / `commits` /
    # `events` sections are no longer assembled here. The surviving authored-node maps are specs / errors
    # (+ patterns / plans, never in the cut scope) + the derived code_to_specs / tasks_citing / rules.
    specs, patterns, plans = {}, {}, {}
    errors: dict = {}  # T-0067: 11th node type — error/friction case files (errors/E-XXXX.yaml, per D-0035)
    scenarios: dict = {}  # T-1047: 7th node type — user-path docs (scenarios/<slug>.md, per SPEC-0076)
    scenario_status_violations: list = []  # T-1047: illegal STORED status (only retired|absent legal) → exit 2
    covers_warnings: list = []             # T-1047: unresolved `covers:` anchor — REPORT-ONLY (T-1049 hardens)
    scenario_missing_key: list = []        # T-1047 (audit-pre F1): non-helper .md lacking `scenario:` — LOUD, report-only
    lessons: dict = {}  # T-9343: 8th node type — per-repo local-craft notes (lessons/<slug>.md, per SPEC-0090)
    lesson_missing_key: list = []          # T-9343: non-helper lessons/*.md lacking `lesson:` — LOUD, report-only
    code_to_specs: dict = {}
    tasks_citing: dict = {}
    parse_errors: list = []  # T-0021: surface silent YAML parse failures (→ exit 2 / fatal)
    implements_warnings: list = []  # T-0064: stale implements anchors — REPORT-ONLY (no exit 2)
    file_granular_warnings: list = []  # T-9324/SPEC-0088: implements/covers anchor at file granularity (no #symbol) — REPORT-ONLY
    freshness_warnings: list = []   # T-0213: possibly-stale (resolved but drifted) — REPORT-ONLY
    spec_cites_warnings: list = []  # T-9629: dangling spec→spec `cites:` (well-formed SPEC id not in corpus) — REPORT-ONLY (no exit 2; parity with implements dead-anchors)
    binding_shape_warnings: list = []  # T-0230: malformed `binding:` (not a YAML list) — REPORT-ONLY
    drift_cache: dict = {}          # per-build memo for _anchor_drift_warning git lookups
    spec_bodies: list = []          # T-0246: (id, rel-path, body) for active+retrieved-tier specs →
                                    # second rule-extraction domain (spec bodies), collected in spec loop
    floor_spec_bodies: list = []    # T-0257: same shape, for active FLOOR-BOUND specs → extracted into
                                    # the handbook/mandatory domain (their tier), not silently skipped

    for p in state.scan_specs(SPECS_DIR):
        d = _read_yaml(p, errors=parse_errors)
        if not d.get("id"):
            continue
        implements = sorted(d.get("implements") or [])
        # T-0230 (Part I-A): the retrieval binding. ENFORCE the list-valued schema (audit-post finding
        # 2): a scalar `binding: commit` must NOT be iterated char-by-char — treat a non-list as
        # invalid/unbound + record a report-only shape drift (never crash). None/absent = unbound.
        raw_binding = d.get("binding")
        if raw_binding is None:
            binding = []
        elif isinstance(raw_binding, list):
            binding = sorted(str(b) for b in raw_binding)
        else:
            binding = []
            binding_shape_warnings.append({"spec": d["id"], "got": type(raw_binding).__name__})
        # spec-level requires/supersedes/proposed_by (D-0047 B6) — carried so `graph query
        # --projected` can detect ordering + the concurrent-change invariant. Additive keys
        # (P5-safe: consumers tolerate extra keys per D-0009). supersedes/proposed_by are
        # scalars (a spec replaces at most one lineage); requires is a list.
        specs[d["id"]] = {"title": d.get("title", ""), "status": d.get("status", ""),
                          "implements": implements, "cites": sorted(d.get("cites") or []),
                          "requires": sorted(str(r) for r in (d.get("requires") or [])),
                          "supersedes": d.get("supersedes"), "proposed_by": d.get("proposed_by"),
                          # T-0425: carry the SPEC-0005 §5 activation owner onto the node (beside
                          # proposed_by/requires/supersedes) so the task→activating-spec map derives
                          # from the graph `index` — NOT a second specs/*.yaml scan (P5, audit-pre F2
                          # / adhoc-consult fix). Additive key (P5-safe: consumers tolerate extras).
                          "activation_owner_task": d.get("activation_owner_task"),
                          # T-9410 (SPEC-0096): carry the per-concern activation-baseline declaration
                          # onto the node so `_render_activation_checklist` derives the init-walk SET +
                          # doc-checklist from the ONE index — NOT a second specs/*.yaml scan (P5). The
                          # field SCHEMA is owned by SPEC-0030 (a mapping {init_question, waiver,
                          # evidence, tier}); SPEC-0096 owns only the DERIVATION. Additive key (P5-safe:
                          # consumers tolerate extras). Absent/`~` on a non-concern spec → None, skipped.
                          "init_concern": d.get("init_concern"),
                          # T-10036 (SPEC-0128): carry the per-concern REGISTRY declaration onto the node
                          # so `_render_concern_registry` derives graph/concern-registry.json from the ONE
                          # index — NOT a second specs/*.yaml scan (P5, the init_concern precedent above).
                          # The field SCHEMA is owned by SPEC-0030 (a finite-metadata mapping); SPEC-0128
                          # owns the DERIVATION + the one-declaration→all-surfaces INVARIANT. Additive key
                          # (P5-safe: consumers tolerate extras). Absent/`~` on a non-concern spec → None.
                          "concern": d.get("concern"),
                          # the retrieval binding (which gating verb/stage fetches this retrieved spec);
                          # inverted into verb_to_specs/floor/report below. List-validated above.
                          "binding": binding}
        # T-9488 (SPEC-0101 rule 1): carry the EXTENSION marker (adoptability state) onto the node so
        # `graph query` surfaces it + the derived catalog view (T-9489) derives from the ONE index —
        # NOT a second specs/*.yaml scan (P5). A field on the existing spec node, NOT a new node-type
        # (GRAPH bound holds). OMITTED-on-unset (audit-pre F1): a non-extension spec carries NO key at
        # all (not `null`), so "unmarked spec is absent" is STRUCTURAL at every layer, not only the
        # query filter. Additive key (P5-safe: consumers tolerate extras). No enum validation — the
        # marker is author-controlled data (GRAPH «what graph is NOT»; task scope forbids a validation
        # layer; audit-pre F2 rejected — no incident, CHARTER §P1 F4).
        if d.get("extension"):
            specs[d["id"]]["extension"] = d.get("extension")
        spec_rel = str(p.relative_to(REPO_ROOT))
        # T-0246/T-0257: collect active spec bodies for rule-extraction, ROUTED BY TIER. ONLY active
        # (the sole normative status); the `binding: [floor]` token then picks the domain — floor-bound
        # → the handbook/mandatory domain (a mandatory-floor spec's rules ARE handbook-tier rules),
        # everything else → the retrieved/spec domain. Routing (not skipping) keeps the
        # one-domain-per-tier cutover STRUCTURAL — a spec enters EXACTLY ONE list, so no rule can be
        # emitted in both domains — while closing T-0257's gap: before this, a floor-bound spec body
        # was dropped on the floor and contributed NO rules at all. Extracted after the handbook loop.
        if d.get("status") == "active":
            body = d.get("body")
            if isinstance(body, str) and body.strip():
                target = floor_spec_bodies if BINDING_FLOOR_TOKEN in binding else spec_bodies
                target.append((d["id"], spec_rel, body))
        fresh_checked: set = set()   # T-0214: dedup keyed by the FULL anchor `loc` — a `<file>#sym`
                                     # check is per-SYMBOL (two symbols in one file are checked
                                     # independently); a file-level anchor still keys/checks per-file.
        for loc in implements:
            # T-0064: resolve each anchor (report-not-block per D-0036) + key the reverse index
            # by the normalized FILE component so `graph query <file>` + any consumer get file→specs.
            warn = _resolve_implements_anchor(loc)
            if warn:
                # T-11343: carry the OWNING SPEC's status onto the record so the report can PARTITION
                # a LIVE dead anchor (on a spec that still governs) from FROZEN HISTORY (an anchor on a
                # non-active spec — an accurate record of what it implemented WHEN it governed, per the
                # T-11340 owner decision). Same status-awareness the `_freshness_warnings` sibling below
                # already applies, but as a PARTITION, never a filter — nothing is dropped here.
                implements_warnings.append({"spec": d["id"], "anchor": str(loc), "warn": warn,
                                            "spec_status": str(d.get("status") or "")})
            elif d.get("status") == "active":
                # T-0213: anchor RESOLVES — check spec<->code freshness. ONLY for `active` specs
                # (`active` is the only normative status — GRAPH §What a spec is FOR; a proposed/
                # superseded/retired spec governs nothing, so drift against it is not a signal).
                # T-0214: pass the FULL `loc` so a `<file>#symbol` anchor compares the symbol's
                # region, not the whole monolithic file (cuts the 5/5 false-positive class).
                if loc not in fresh_checked:
                    fresh_checked.add(loc)
                    fw = _anchor_drift_warning(spec_rel, loc, drift_cache)
                    if fw:
                        freshness_warnings.append({"spec": d["id"], "anchor": str(loc), "warn": fw})
            # T-9324/SPEC-0088 (code-decompose rule, report-only): flag a file-granular implements
            # anchor (no #symbol) for decomposition. Independent of resolution/freshness above.
            # T-9370: auto-exempt a genuinely-ATOMIC (symbol-less) target — pass its symbol-space signal.
            sym_space = _file_has_symbol_space(_anchor_file(loc)) if _file_has_symbol_space else None
            fg = _file_granular_anchor_warning(loc, sym_space)
            if fg:
                file_granular_warnings.append({"node": d["id"], "kind": "implements",
                                                "anchor": str(loc), "warn": fg})
            code_to_specs.setdefault(_anchor_file(loc), []).append(d["id"])

    # T-9629: dangling spec→spec `cites:` sweep — parity with the implements dead-anchor REPORT (T-0064)
    # and the scenario `cites_unresolved` logic (T-1100, SPEC-0076 §6b). The SPEC node loads `cites` but
    # never resolved them, so a cite to a NONEXISTENT spec id passed `graph build` SILENTLY (the real
    # incident: SPEC-0001 cites SPEC-0010, nonexistent → errors:{} cites_unresolved:[]). Run it AFTER the
    # spec loop so `specs` is the COMPLETE corpus (a spec may cite one defined later in iteration order).
    # FACT-of-existence ONLY (not legality): ONLY a well-formed bare SPEC id (`^SPEC-\d{4,}$`) is resolved
    # — a section ref (`SPEC-XXXX§...`), plan slug, task id, or decision id is NEVER resolved (mirrors the
    # scenario gate's SPEC-id-only scope). Coerce each cite with `str(c)` (the spec node stores cites
    # un-coerced, unlike the scenario `node_cites`) so a non-string YAML scalar can never raise — the
    # sweep stays report-only (audit-pre F0). EMPTY-corpus guard (mirrors the scenario T-1100 fail-OPEN):
    # a ZERO-spec map is a broken/partial/test build where "absent cite" ≠ "not loaded", so skip — a real
    # build always loads a non-empty corpus. REPORT-ONLY (exit-0 stderr in cmd_graph_build, NO exit 2 —
    # GRAPH "NOT a validation layer"; a spec cite is an informational any→any reference, unlike a
    # scenario's building contract which T-1100 makes fatal).
    # T-10106 (X-0209): on a -C consumer build `specs` is the CONSUMER corpus only, so a LEGIT
    # consumer→kernel spec cite (a consumer pins the released kernel; the methodology specs travel as
    # kernel — SPEC-0073 §1 / SPEC-0074 §4, e.g. SPEC-0044 cites SPEC-0094/0097/0098) resolved as
    # dangling — diluting the real signal (the 6 boomrocket false positives). Resolve the cite against
    # the KERNEL corpus too before flagging: `_kernel_spec_ids` (injected callable, ENGINE_ROOT-scanned,
    # mirroring _kernel_content_file's own-else-ENGINE fallback) yields the kernel SPEC ids; empty on an
    # engine self-build (no realm split) so this is a pure no-op there. A cite in NEITHER corpus still
    # flags (negative probe preserved).
    kernel_ids = set(_kernel_spec_ids()) if _kernel_spec_ids else set()
    # T-10933: the STATUS-bearing twin of `kernel_ids`, for `_compute_scenario_status` (which needs
    # WHICH status a kernel-cited spec has, not merely that it exists). Bound beside `kernel_ids`
    # rather than replacing it: every current `kernel_ids` use is EXISTENCE-only and stays
    # byte-identical, so the T-10106 / T-10817 resolution behaviour and its tests are untouched.
    # Empty on an engine self-build (no realm split) — a pure no-op there, like its sibling.
    kernel_statuses = dict(_kernel_spec_statuses()) if _kernel_spec_statuses else {}
    if specs:
        for sid in specs:
            cu = sorted(c for c in (str(x) for x in (specs[sid].get("cites") or []))
                        if re.fullmatch(r"SPEC-\d{4,}", c) and c not in specs and c not in kernel_ids)
            specs[sid]["cites_unresolved"] = cu   # additive key (P5-safe: consumers tolerate extras)
            for c in cu:
                spec_cites_warnings.append({"spec": sid, "anchor": c})

    # T-0491: the graph-slim cut drops the `task` node-type, so the `tasks[...]` section is no longer
    # emitted. The walk SURVIVES — it still (a) reads every task file via `_read_yaml(errors=parse_errors)`
    # so a malformed task is OBSERVABLE in `_parse_errors` (→ exit 2 / `land` block — build-level
    # observability invariant), and (b) builds the `tasks_citing` reverse-index (the surviving `cites`
    # edge, used by spec/decision point-lookup `cited_by_tasks`). The CURRENT-index live readers that
    # need task node detail (status/requires) re-source it from authored YAML via `_with_live_nodes`.
    for p in state.scan_tasks(TASKS_DIR):
        d = _read_yaml(p, errors=parse_errors)
        if not d.get("id"):
            continue
        for c in sorted(str(c) for c in (d.get("cites") or [])):
            cid = _id_from_artifact_ref(c)
            if cid:
                tasks_citing.setdefault(cid, []).append(d["id"])

    # T-0491: the cut also drops the `decision` + `audit_verdict` node-types (and the `audited` edge),
    # so neither the `decisions[...]` section NOR the `audits[...]` map is emitted. The walk is RESHAPED,
    # NOT deleted: it still reads — via `_read_yaml(errors=parse_errors)` — exactly the files the PRE-CUT
    # walk read (the audit-verdict patterns + `D-NNNN-` decision files), so a malformed one stays
    # OBSERVABLE in `_parse_errors` (build-level observability invariant). The SAME pre-cut file-selection
    # gate is preserved (a non-matching file — e.g. a `_template` / batch report — is `continue`d BEFORE
    # any read, exactly as before, so the cut neither widens nor narrows what the build observes). Only
    # the section/audits ASSEMBLY is removed. (Plan-check + ad-hoc verdicts are still read directly off
    # disk by their own callers; they are no longer graph-queryable — Option A, no shadow path.)
    for p in sorted(DECISIONS_DIR.glob("*.yaml")):
        name = p.name
        # audit-verdict files (T-/D--audit-{pre,post,adhoc}, <slug>-audit, <slug>-audit-adhoc): the
        # pre-cut walk read these to build the now-dropped `audits` map; KEEP the parse-error-surfacing
        # read, DROP the assembly.
        if re.match(r"^(T-\d{4,}|D-\d{4,})-audit-(pre|post|adhoc)\.yaml$", name) \
                or re.match(r"^([a-z0-9][a-z0-9-]*)-audit\.yaml$", name) \
                or re.match(r"^([A-Za-z0-9][A-Za-z0-9-]*)-audit-adhoc\.yaml$", name):
            _read_yaml(p, errors=parse_errors)
            continue
        if not re.match(r"^D-\d{4,}-", name):
            continue  # phase-* / _template / non-decision report files skipped (same pre-cut gate)
        _read_yaml(p, errors=parse_errors)   # decision file: observability-only read (no `decisions[...]`)

    for p in state.scan_patterns(PATTERNS_DIR):
        fm = _pattern_frontmatter(p, errors=parse_errors)
        nm = fm.get("name") or p.stem
        patterns[nm] = {"class": fm.get("class", ""), "sourced_from": fm.get("sourced_from", "")}

    # `plan` node (10th type, per D-0034 amended T-0114 + GRAPH §Schema). Both planning classes
    # index here under ONE node type: plans/ (kind:plan, full FSM) + ideas/ (kind:idea, flat) —
    # D-0034 §Graph «ideas indexed likewise». ideas fold into the `plan` node (no SEPARATE node
    # type for ideas — distinct from `errors`, D-0035's own 11th type). Reuse the frontmatter reader.
    for d_dir, d_kind in ((PLANS_DIR, "plan"), (IDEAS_DIR, "idea")):
        if not d_dir.exists():
            continue
        for p in sorted(d_dir.glob("*.md")):
            fm = _pattern_frontmatter(p, errors=parse_errors)
            sid = fm.get("id") or p.stem
            plans[sid] = {"kind": d_kind, "status": fm.get("status", ""),
                          "created": fm.get("created", ""),
                          # T-9263: index the plan's `cites` on the node, EXACTLY mirroring the spec
                          # node (`"cites": sorted(...)` above) — realizes the already-documented
                          # any→any `cites` edge for plans (GRAPH §Edge types), so a plan that
                          # declares its scenario INPUTS via cites: is graph-queryable (SPEC-0076 §4
                          # `cites(plan→scenario)`). No new field/edge/node — code catching up to the
                          # schema. Idea frontmatter rarely carries cites → empty list, harmless.
                          "cites": sorted(str(c) for c in (fm.get("cites") or [])),
                          "closed_into": sorted(str(c) for c in (fm.get("closed_into") or []))}

    # `error` node (11th type, per D-0035 §GRAPH — errors/ indexed FROM DAY 1, unlike ideas which
    # D-0034 folded under `plan`). Promotion-only case files (errors/E-XXXX.yaml); the `E-*` glob
    # naturally excludes errors/_template.yaml. Edges REUSE existing types (cites/from/emitted_by).
    if ERRORS_DIR.exists():
        for p in state.scan_errors(ERRORS_DIR):
            d = _read_yaml(p, errors=parse_errors)
            if not d.get("id"):
                continue
            errors[d["id"]] = {"kind": d.get("kind", ""), "severity": d.get("severity", ""),
                               "status": d.get("status", ""), "fingerprint": d.get("fingerprint", ""),
                               "relates_to": d.get("relates_to", ""),
                               # reopen/resolved rate = symptom-treatment metric (D-0086 §8, inspection T5)
                               "reopen_count": int(d.get("reopen_count") or 0),
                               "refs": sorted(str(r) for r in (d.get("refs") or []))}

    # `scenario` node (7th type, per SPEC-0076 §4 — the v2-self mint, T-1047). A scenario is a
    # zero-normative user-path doc (scenarios/<slug>.md) carrying `cites` (like the `pattern`/`error`
    # nodes — prior-art for node-reuses-`cites`, D-0035) PLUS the ONE new `covers` edge (scenario → an
    # anchor the graph resolves TODAY — the same `<file>` / `<file>#<symbol>` address space as
    # `implements`; rule-4 scope-guard: NO new symbol-indexer). The `scenarios/*.md` doc is now the SOLE
    # canonical scenario carrier (the pre-mint "ad-hoc prose doc invisible to the graph" ceases to be
    # canonical — GRAPH §Schema retirement). STATUS-STORAGE contract (SPEC-0076 §3): the frontmatter
    # `status` field stores ONLY the human-set `retired` exception (or is absent) — `draft`/`building`/
    # `live` are a COMPUTED view (T-1048), NEVER stored; an illegal stored status is REJECTED at build
    # (exit 2 in cmd_graph_build). This is a storage-FORMAT check, NOT semantic/legality validation
    # (GRAPH §What graph is NOT — the narrow named exception).
    if SCENARIOS_DIR.exists():
        for p in state.scan_scenarios(SCENARIOS_DIR):
            # `_`-prefixed = templates/fixtures (scenarios/_template.md, _dogfood-*), README.md = docs:
            # both are NON-scenario helpers, excluded BEFORE any indexing (parallel-carrier guard).
            if p.name.startswith("_") or p.name == "README.md":
                continue
            fm = _pattern_frontmatter(p, errors=parse_errors)
            sid = fm.get("scenario")
            if not sid:
                # audit-pre F1 (high): a real (non-helper) scenario file MUST declare an explicit
                # `scenario:` key — NO filename/stem fallback (that would silently type any .md). A
                # keyless non-helper file is NOT indexed, but surfaced LOUDLY (report-only) so canonical
                # content is never silently invisible — without re-importing a hard suspicion-gate.
                scenario_missing_key.append(str(p.relative_to(REPO_ROOT)))
                continue
            sid = str(sid)
            stored_status = fm.get("status")
            # STATUS-STORAGE contract: only `retired` (or absent) is a legal STORED status.
            if stored_status is not None and str(stored_status) != "retired":
                scenario_status_violations.append(
                    {"scenario": sid, "path": str(p.relative_to(REPO_ROOT)), "got": str(stored_status)})
            covers_resolved, covers_unresolved = [], []
            for anchor in sorted(str(a) for a in (fm.get("covers") or [])):
                warn = _resolve_implements_anchor(anchor)
                if warn:
                    covers_unresolved.append(anchor)
                    covers_warnings.append({"scenario": sid, "anchor": anchor, "warn": warn})
                else:
                    covers_resolved.append(anchor)
                # T-9324/SPEC-0088 (code-decompose rule, report-only): flag a file-granular covers
                # anchor (no #symbol) for decomposition. Independent of resolution above.
                # T-9370: auto-exempt a genuinely-ATOMIC (symbol-less) target (e.g. a Jinja template).
                sym_space = _file_has_symbol_space(_anchor_file(anchor)) if _file_has_symbol_space else None
                fg = _file_granular_anchor_warning(anchor, sym_space)
                if fg:
                    file_granular_warnings.append({"node": sid, "kind": "covers",
                                                    "anchor": anchor, "warn": fg})
            node_cites = sorted(str(c) for c in (fm.get("cites") or []))
            # T-1100 (SPEC-0076 §6b — the "or a cited SPEC does not exist" sub-case split from T-1049):
            # a well-formed bare SPEC id (`^SPEC-\d{4,}$`) that is NOT in the loaded specs corpus is a
            # broken reference. ONLY exact bare SPEC ids are resolved — a SECTION ref (`X§...`), plan
            # slug, task id, or decision id is NEVER resolved (FACT-of-existence only, not legality). The
            # build/exit-2 gate (cmd_graph_build) is SCOPED to building; this field is computed for
            # all scenarios and the gate applies the scope. Production-safe: a real build loads the
            # COMPLETE specs corpus (the same map _compute_scenario_status trusts), so a non-resolving
            # SPEC cite is genuinely broken — the partial-corpus false-positive lives only in a sandbox
            # that leaks the real scenarios/ against an empty specs/ (a real build never does).
            # EMPTY-corpus guard (prior-art: graph.py `if not specs: derivation-failed` below): the
            # gate's premise is a COMPLETE corpus, and a real corpus always has specs — a ZERO-spec map
            # is a broken/partial/test build where "absent cite" cannot be distinguished from "not
            # loaded", so the gate MUST NOT fire (fail-OPEN on an empty corpus, same signal the binding
            # derivation uses). In production `specs` is always non-empty, so this never relaxes the gate.
            # T-10817 (X-0666): CROSS-REALM resolution — the same `_kernel_spec_ids` fallback the
            # spec→spec sweep got at T-10106 (l.993), applied here. On a -C consumer build `specs` is
            # the CONSUMER corpus only, so a scenario citing a KERNEL spec id (the methodology specs
            # travel as kernel — SPEC-0073 §1 / SPEC-0074 §4) resolved as a broken reference. The
            # omission is strictly WORSE on this path than on the spec sweep: that one is report-only,
            # whereas THIS gate is FATAL (exit 2) for a building scenario — so a legitimate
            # consumer scenario HARD-FAILED `graph build`. `kernel_ids` is already bound above (l.993);
            # it is EMPTY on an engine self-build (no realm split), so this is a pure no-op there. A
            # cite resolvable in NEITHER corpus still flags (negative probe preserved) and the
            # EMPTY-corpus fail-OPEN guard below is untouched.
            cites_unresolved = ([c for c in node_cites
                                 if re.fullmatch(r"SPEC-\d{4,}", c)
                                 and c not in specs and c not in kernel_ids]
                                if specs else [])
            scenarios[sid] = {
                "actor": fm.get("actor", ""),
                # stored status carries ONLY the `retired` exception ("" = absent → computed draft|...);
                # an illegal value is recorded as a violation above but kept here verbatim for the report.
                "status": str(stored_status) if stored_status is not None else "",
                # T-1048: the DERIVED read-only status (SPEC-0076 §3) — draft|building; NEVER persisted
                # to frontmatter (the storage contract above still rejects a stored computed value,
                # T-1047 — `live` stays rejected there too, it was never legal to store).
                "computed_status": _compute_scenario_status(
                    node_cites,
                    str(stored_status) if stored_status is not None else None),
                # T-11004: the spec-status reading `live` used to consume, kept as its OWN field now
                # that the status no longer carries it — the input SPEC-0082's baseline-fidelity leg
                # reads. FALSE for a no-cites scenario (never vacuously true). T-10933: cross-realm
                # resolution, own-corpus still wins.
                "cites_all_active": _scenario_cites_all_active(node_cites, specs, kernel_statuses),
                "cites": node_cites,
                "covers": covers_resolved,
                "covers_unresolved": covers_unresolved,
                "cites_unresolved": cites_unresolved,   # T-1100: dangling well-formed SPEC cites
            }

    # `lesson` node (8th type, per SPEC-0090 §4 — T-9343). A lesson is a THIN, per-repo, NON-traveling
    # local-craft note (lessons/<slug>.md) carrying `cites` (any→any) exactly like the `pattern` / `error`
    # nodes — prior-art for node-reuses-`cites` (D-0035). It REUSES `cites`, adds NO new edge (the 4-edge
    # bound is UNCHANGED). Per-repo walk: `graph build` runs under -C, so the KERNEL graph indexes the
    # kernel's lessons and a PROJECT graph indexes that project's lessons; a lesson never travels (SPEC-0090
    # §3 — project realm, SPEC-0073). It is zero-normative with NO status FSM (SPEC-0090 §5): the OPTIONAL
    # `status` (human-set `retired`) is stored verbatim like the `error`/`pattern` retired marker — no
    # computed status, no per-status verb, no currency machinery. Enforcement is storage-FORMAT only
    # (SPEC-0090 §6): a MALFORMED frontmatter is surfaced via `_pattern_frontmatter(errors=parse_errors)`
    # → the build's exit-2 parse-error gate (the same fail-closed path patterns/scenarios use); the build
    # NEVER judges lesson CONTENT or the local-vs-general boundary (GRAPH §What graph is NOT).
    if LESSONS_DIR.exists():
        for p in state.scan_lessons(LESSONS_DIR):
            # `_`-prefixed = templates/fixtures (lessons/_template.md), README.md = docs: NON-lesson
            # helpers, excluded BEFORE indexing (mirrors the scenario helper guard).
            if p.name.startswith("_") or p.name == "README.md":
                continue
            fm = _pattern_frontmatter(p, errors=parse_errors)
            lid = fm.get("lesson")
            if not lid:
                # A real (non-helper) lesson file MUST declare an explicit `lesson:` key — NO filename
                # fallback (mirrors the scenario `scenario:`-key rule, audit-pre F1): a keyless non-helper
                # file is NOT indexed but surfaced LOUDLY (report-only) so content is never silently invisible.
                lesson_missing_key.append(str(p.relative_to(REPO_ROOT)))
                continue
            lid = str(lid)
            lessons[lid] = {
                # OPTIONAL human-set status ("" = absent; `retired` marks an abandoned lesson, still
                # indexed — mirrors pattern/spec/error retired). No FSM, no validation (SPEC-0090 §5/§6).
                "status": str(fm.get("status")) if fm.get("status") is not None else "",
                "cites": sorted(str(c) for c in (fm.get("cites") or [])),
            }

    # T-0491: `audits` sort dropped (no audits section). The `events` indexer is dropped entirely (the
    # `event` node-type + `emitted_by` edge are cut — the journal events.jsonl stays the append-only
    # source of truth, just no longer mirrored into the graph index).
    for k in code_to_specs:
        code_to_specs[k] = sorted(set(code_to_specs[k]))
    for k in tasks_citing:
        tasks_citing[k] = sorted(set(tasks_citing[k]))

    rules = []
    # Domain 1 — the always-loaded handbook docs (source_domain="handbook").
    for doc in CANONICAL_DOCS:
        dp = REPO_ROOT / doc
        if not dp.exists():
            continue
        rules.extend(_extract_rules(dp.read_text(encoding="utf-8").splitlines(),
                                    _doc_slug(doc), doc, "handbook"))
    # Domain 2 — retrieved-tier spec BODIES (source_domain="spec", T-0246 / SPEC-0007 §7). One domain
    # per tier: handbook prose carries the mandatory floor; retrieved-tier rules live in their spec
    # bodies. `spec_bodies` was collected in the spec loop (active AND NOT floor-bound).
    for sid, srel, body in spec_bodies:
        rules.extend(_extract_rules(body.splitlines(), sid.lower(), srel, "spec"))
    # Domain 1 (continued) — active FLOOR-BOUND spec BODIES (T-0257). A `binding: [floor]` spec is
    # always-loaded, so its body is mandatory-tier prose: it is extracted through the SAME helper with
    # source_domain="handbook", landing in the handbook domain alongside the canonical docs above.
    # Disjoint by construction from `spec_bodies` (the spec loop routes each active spec into exactly
    # one list), so this ADDS the previously-skipped population without introducing a cross-tier dup.
    for sid, srel, body in floor_spec_bodies:
        rules.extend(_extract_rules(body.splitlines(), sid.lower(), srel, "handbook"))
    rules = sorted(rules, key=lambda r: r["id"])

    # T-0230 (Part I-A): derive the retrieval-delivery views from the per-spec `binding:` field —
    # the verb→section inversion, the always-loaded floor trigger-map, and the bidirectional
    # completeness report. All derived-only (single canonical carrier = `binding:`).
    verb_to_specs, floor_trigger_map, binding_report = _build_binding_views(specs)
    if binding_shape_warnings:                       # T-0230: malformed `binding:` shape (report-only)
        binding_report["malformed_binding"] = binding_shape_warnings

    # T-0491: the 5 cut sections (tasks / decisions / commits / audits / events) are no longer in the
    # returned index. The surviving authored-node sections are specs / patterns / plans / errors; the
    # derived sections are code_to_specs / tasks_citing / rules / the binding views.
    index = {
        "specs": specs, "patterns": patterns,
        "plans": plans, "errors": errors,
        "scenarios": scenarios,   # T-1047: 7th node type (SPEC-0076)
        "lessons": lessons,       # T-9343: 8th node type (SPEC-0090) — per-repo local-craft notes
        "code_to_specs": code_to_specs, "tasks_citing": tasks_citing,
        "verb_to_specs": verb_to_specs, "floor_trigger_map": floor_trigger_map,
        "binding_report": binding_report,
        "rules": rules,
        "_parse_errors": parse_errors,  # T-0021: meta (underscore = excluded by query --type)
        "_implements_warnings": implements_warnings,  # T-0064: report-only stale-anchor warnings
        "_file_granular_warnings": file_granular_warnings,  # T-9324/SPEC-0088: report-only file-granular implements/covers anchors
        "_freshness_warnings": freshness_warnings,  # T-0213: report-only possibly-stale (drifted) anchors
        "_spec_cites_warnings": spec_cites_warnings,  # T-9629: report-only dangling spec→spec `cites:` (well-formed SPEC id not in corpus)
        "_scenario_status_violations": scenario_status_violations,  # T-1047: illegal stored status → exit 2
        "_covers_warnings": covers_warnings,            # T-1047: unresolved covers anchor (report-only)
        "_scenario_missing_key": scenario_missing_key,  # T-1047: non-helper .md lacking `scenario:` (report-only)
        "_lesson_missing_key": lesson_missing_key,      # T-9343: non-helper lessons/*.md lacking `lesson:` (report-only)
    }
    # T-0849 (friction F-001): on a CONSUMER build, the structural layers verb_to_specs /
    # floor_trigger_map / binding_report are KERNEL-derived (their shape comes from the engine constants
    # BINDING_VERB_SURFACES / FLOOR_TRIGGERS, non-zero even on an EMPTY consumer), not project-derived.
    # Attribute them with an additive top-level `kernel_provided` marker so they are not mistaken for the
    # consumer's own rules→code nodes. MARK, do NOT omit — a consumer still consumes these for its
    # read-gate delivery. Engine self-build (NOT a consumer) → NO marker → its own build is unchanged.
    if _is_consumer_build():
        index["kernel_provided"] = {
            "engine": KERNEL_NAME,        # STABLE literal — never a path / checkout name (reproducible)
            "layers": list(KERNEL_DERIVED_LAYERS),
            "note": ("These structural layers are derived from the " + KERNEL_NAME + " engine constants "
                     "(BINDING_VERB_SURFACES / FLOOR_TRIGGERS), not from this project's own specs. They "
                     "are provided by the kernel for this consumer's read-gate delivery — kernel-provided, "
                     "not project-owned."),
        }
    return index


# ============================================================================
# cmd_graph_* verb orchestrators + their exclusive residue helpers (T-9379)
# Relocated from the bin/yitc-v2 monolith via the AST-FREEZE generator, byte-identical.
# Full inject-residue seam: host collaborators/globals + moved siblings (via host residue)
# arrive as keyword-only injects; the host keeps a thin forwarding residue under each name.
# The _view_* reporting family STAYS host (Card A -> bin/lib/views.py); _run_view is injected.
# ============================================================================

def _capture_cluster_counts(events_path: 'Path', *, ERRORS_DIR, _capture_fingerprint_counts, _read_yaml) -> dict:
    """Cluster-aware recurrence aggregation — the dedup HOME for fingerprint fragmentation (T-0277).
    A root deviation often accrues MANY near-synonym fingerprints (the land-false-fail class got >=4);
    keyed per-exact-string each reads N=1, so the true recurrence stays invisible and the D-0035 N>=2
    promotion threshold is defeated (the exact failure the capture reflex exists to prevent).

    The canonical clustering carrier is the `cites:` LINK RULE (D-0086 §9 — the single EXCLUSIVE
    derivation source): an errors/E-XXXX.yaml lists the member fingerprints it subsumes in `cites:`,
    and its own `fingerprint:` is the canonical key. This is a derived read-side VIEW (anti-complexity
    Filter 2 — view over a new entity) that rolls member capture-counts up under the canonical fp so a
    fragmented root becomes countable. `sibling_fingerprints` is NOT read here — it is a non-authoritative
    convenience list (§9 permits a human-readable mention that is never the derivation source).

    Ownership is DETERMINISTIC + single-count (audit-pre F0): every capture fingerprint belongs to AT
    MOST ONE canonical class — (1) self-ownership wins: a fp that IS some case file's own `fingerprint:`
    is owned by THAT file; (2) else a fp cited by >1 file is owned by the lexicographically smallest
    E-id; (3) each fp's count is summed exactly ONCE (file-set/order-independent, no double-count).
    Returns {canonical_fp: {"error": E-id, "members": [fp,...], "total": N, "status": <case status>}}
    for clusters that actually roll up >=2 distinct member fingerprints."""
    counts = _capture_fingerprint_counts(events_path)   # {fp: n} across both capture event names
    if not counts or not ERRORS_DIR.exists():
        return {}
    # Pass 1 — per case file: canonical fp + its cited capture-fingerprints (cites filtered to strings
    # that are REAL capture fingerprints; artifact-ids / decision-ids are skipped). Sorted by E-id so
    # the smallest-E-id tie-break is deterministic.
    cases = []   # (eid, canonical_fp, status, {member_fps})
    for p in state.scan_errors(ERRORS_DIR):
        d = _read_yaml(p)
        eid, canon = d.get("id"), d.get("fingerprint")
        if not eid or not canon:
            continue
        members = {canon} if canon in counts else set()
        for c in (d.get("cites") or []):
            if str(c) in counts:
                members.add(str(c))
        if members:
            cases.append((eid, canon, d.get("status", ""), members))
    # Pass 2 — deterministic single-count ownership: self-owned fps first, then smallest-E-id.
    owner_of: dict = {}   # fp -> owning E-id
    for eid, canon, _status, _members in cases:
        if canon in counts:
            owner_of.setdefault(canon, eid)
    for eid, _canon, _status, members in cases:   # cases already sorted by E-id
        for fp in members:
            owner_of.setdefault(fp, eid)
    # Pass 3 — aggregate each owned fp's count once, under the owning file's canonical class.
    meta = {eid: (canon, status) for eid, canon, status, _ in cases}
    clusters: dict = {}
    for fp, eid in owner_of.items():
        canon, status = meta[eid]
        cl = clusters.setdefault(canon, {"error": eid, "members": [], "total": 0, "status": status})
        cl["members"].append(fp)
        cl["total"] += counts[fp]
    # surface a cluster only when it actually ROLLS UP more than the canonical's own captures —
    # i.e. the aggregate exceeds the canonical fingerprint's own count (audit-post F-high). This
    # subsumes the >=2-members case AND catches a 1-member cluster whose single member is a captured
    # ALIAS (canonical uncaptured): total>0 > canon's 0, so the root still surfaces under the canonical
    # instead of disappearing. A lone canonical with no captured aliases (total == its own count) is
    # NOT a cluster — it shows standalone via the per-fingerprint path.
    return {c: v for c, v in clusters.items() if v["total"] > counts.get(c, 0)}


def _contiguous_blocks(text: str) -> list:
    """Maximal runs of adjacent NON-blank lines, each as [(line_no, raw)]. The unit the binding-map mirror
    under-list check aggregates over (absorbs audit-pre F2: a mirror split across adjacent single-surface
    lines is ONE block). A blank line ends a block."""
    blocks, cur = [], []
    for ln, raw in enumerate(text.splitlines(), start=1):
        if raw.strip():
            cur.append((ln, raw))
        elif cur:
            blocks.append(cur); cur = []
    if cur:
        blocks.append(cur)
    return blocks


def _delivery_classes(binding, *, BINDING_RESIDENCY_TOKENS, BINDING_VERB_SURFACES, PLAN_STAGE_ENTRY_PREFIX, STAGE_ENTRY_PREFIX, _is_valid_plan_stage_entry, _is_valid_stage_entry) -> dict:
    """Classify a spec's `binding:` tokens into delivery CLASSES — the structural basis of the one-source
    invariant. Returns {'stage_entries', 'bad_stage_entries', 'verbs', 'residency', 'other'} (each a list).
    PURE; tolerant of a non-list binding (→ every class empty; never iterated char-by-char)."""
    out = {"stage_entries": [], "bad_stage_entries": [], "plan_stage_entries": [],
           "bad_plan_stage_entries": [], "verbs": [], "residency": [], "other": []}
    if not isinstance(binding, list):
        return out
    for tok in binding:
        if _is_valid_stage_entry(tok):                  # _is_valid_stage_entry is non-str-safe (→ False)
            out["stage_entries"].append(tok)
        elif _is_valid_plan_stage_entry(tok):           # T-0324: the plan-axis mirror — a valid
            out["plan_stage_entries"].append(tok)       # plan-stage-entry:<PLAN_STAGE> (non-str-safe → False)
        elif not isinstance(tok, str):                  # a non-string element (incl. an UNHASHABLE list/
            out["other"].append(tok)                    # dict from malformed YAML) — classify as `other`,
                                                        # NEVER `tok in frozenset` (hash() raises on unhashable
                                                        # — audit-post F: defensive, before any set membership).
        elif tok.startswith(PLAN_STAGE_ENTRY_PREFIX):   # plan-stage-entry:<bad> — a nonexistent plan-stage
            out["bad_plan_stage_entries"].append(tok)   # suffix (T-0324 mirror; checked before STAGE_ENTRY_
                                                        # PREFIX, though prefixes are disjoint so order is moot).
        elif tok.startswith(STAGE_ENTRY_PREFIX):
            out["bad_stage_entries"].append(tok)        # stage-entry:<bad> — a nonexistent stage suffix
        elif tok in BINDING_VERB_SURFACES:
            out["verbs"].append(tok)
        elif tok in BINDING_RESIDENCY_TOKENS:
            out["residency"].append(tok)
        else:
            out["other"].append(tok)                    # a bare unknown token — owned by the EXISTING
    return out                                          # conformance unknown/dangling door, not here (P5).


def _derive_file_placement(text: str, *, _manifest_section2_rows, _resolve_placement) -> list:
    """DERIVE the placement realm of every §2 row token via `_resolve_placement` (file-override-aware).
    Returns a list of (token, realm) in document order. Pure given the manifest text. Hard-class tokens
    carry no `travels:` marker, so the resolver reads the class-default matrix + the path-override map."""
    return [(tok, _resolve_placement(tok)) for tok, _cls in _manifest_section2_rows(text)]


def _derive_spec_placement(*, SPECS_DIR, _read_yaml, _resolve_placement) -> list:
    """DERIVE the placement realm of every specs/SPEC-*.yaml from the class-default matrix + its
    per-spec `travels:` marker, via the pure `_resolve_placement` primitive (unchanged). Returns a
    list of (spec_id, realm) sorted by id. Pure modulo reading specs/ off disk; deterministic — same
    corpus → identical output (so the rendered region re-generates byte-identically). The status-blind
    primitive reproduces §1 (non-active specs carry travels:v2-self → v2-self; active → kernel)."""
    rows = []
    for p in state.scan_specs(SPECS_DIR):
        d = _read_yaml(p)
        sid = d.get("id")
        if not sid:
            continue
        realm = _resolve_placement(f"specs/{sid}", d.get("travels"))
        rows.append((sid, realm))
    rows.sort(key=lambda r: r[0])
    return rows


def _derived_routing_backing(floor_trigger_map: dict, stage_to_specs: dict) -> dict:
    """surface -> set(SPEC ids) the binding-derived map routes for that surface. Surfaces are stage names
    (from stage_to_specs), floor-trigger per-surface keys (e.g. spec-new / spec-edit), AND the trigger
    NAMES themselves (e.g. before-rule-change -> the union of its surfaces' specs). PURE — the single
    canonical routing truth a handbook assertion is checked against (no parallel hand-maintained copy)."""
    backing: dict = {}
    for stage, sids in (stage_to_specs or {}).items():
        backing.setdefault(stage, set()).update(sids or [])
    for trig, surfmap in (floor_trigger_map or {}).items():
        union = set()
        for surface, sids in (surfmap or {}).items():
            backing.setdefault(surface, set()).update(sids or [])
            union.update(sids or [])
        backing.setdefault(trig, set()).update(union)
    return backing


def _cross_dangling_matches(picked, specs, plans) -> list:
    """PURE core of the T-10221 (SPEC-0085) dangling-resolved advisory — no host/log/FS deps, so it is
    unit-testable directly. `picked` = the set of X-ids still `picked` in our court (folded by the host).
    `specs` = iterable of (spec_id, status, full_text); `plans` = iterable of (plan_slug, status, full_text).
    An item is flagged when it is `picked` AND prose-cited (X-NNNN token anywhere in the text) by an ACTIVE
    spec OR a REALIZED plan — the non-task resolution axes the close-side auto-`cross_done` never reaches.
    Returns sorted [{"cross": xid, "resolvers": [<active-spec-id|realized-plan-slug>, ...]}]. REPORT-ONLY
    at the call-site (never the RED/GREEN verdict) — prose citation is overloaded (citer != resolver)."""
    picked = set(picked or ())
    if not picked:
        return []
    xre = re.compile(r"X-\d{4}")
    found: dict = {}
    for ident, status, text in specs:
        if status != "active":
            continue
        for xid in set(xre.findall(text or "")) & picked:
            found.setdefault(xid, set()).add(ident)
    for slug, status, text in plans:
        if status != "realized":
            continue
        for xid in set(xre.findall(text or "")) & picked:
            found.setdefault(xid, set()).add(slug)
    return sorted(({"cross": xid, "resolvers": sorted(srcs)} for xid, srcs in found.items()),
                  key=lambda f: f["cross"])


def _phantom_activation_owner_matches(specs, task_ids) -> list:
    """PURE core of the T-10590 (SPEC-0005 §4/§5) phantom-activation-owner advisory — no host/log/FS
    deps, so it is unit-testable directly. `specs` = iterable of (spec_id, status, activation_owner_task);
    `task_ids` = the set of task ids that exist LOCALLY (folded by the host from TASKS_DIR).

    Flags a `proposed` spec whose `activation_owner_task` names a task with no local card. Such a spec is
    STRANDED: it governs nothing (SPEC-0005 §4 — `proposed` is non-authoritative) and has no sanctioned
    activation path, because `proposed → active` is written ONLY by the activation owner's `task close`
    (GRAPH §Spec lifecycle) and that task does not exist. Real incident: X-0437 — a boomrocket v1→v2 F2a
    import left 36 specs owned by nonexistent kernel-range T-9660/T-9661.

    BOUNDARY (SPEC-0005 §5 Grandfathering): an ABSENT owner is VALID — "a pre-doctrine spec is VALID
    without activation_owner_task / proposed_by ... No retroactive backfill". So absence is NEVER flagged;
    only a PRESENT-but-unresolvable owner is. Scope is `proposed` only: an ACTIVE spec's dangling state is
    T-0455's surface (`_dangling_activated_specs`), not this one.

    Returns sorted [{"spec": spec_id, "owner": activation_owner_task}]. REPORT-ONLY at the call-site
    (never the RED/GREEN verdict): the terminal route is a SEMANTIC choice (activate with a real local
    owner + adoption probe, or retire/withdraw) that no check can synthesize — SPEC-0005 §7
    prevention-by-discipline-not-a-gate / GRAPH §"NOT a validation layer" / CHARTER non-goal #7."""
    known = {str(t).strip() for t in (task_ids or ())}
    rows = []
    for spec_id, status, owner in (specs or ()):
        if status != "proposed":
            continue
        owner = str(owner).strip() if owner else ""
        if not owner or owner in known:      # absent → grandfathered-valid; resolvable → healthy
            continue
        rows.append({"spec": spec_id, "owner": owner})
    return sorted(rows, key=lambda f: (f["spec"], f["owner"]))


def _floor_map_drift(floor_trigger_map: dict, specs: dict, *, GRAPH_PATH, _is_consumer_build, _render_floor_trigger_map) -> list:
    """T-0300 check (b) — the committed graph/floor-trigger-map.md MUST equal the freshly regenerated map
    (`_render_floor_trigger_map` over the SAME binding-derived inputs the build renders from). A mismatch
    = `floor-map-drift`: the committed always-loaded artifact went stale relative to the live bindings.
    Returns [] or a single {kind, detail}. Reads the committed file from GRAPH_PATH's sibling (the build's
    write target). REPORT-ONLY (its caller adds it to the conformance RED set; it is not a build gate)."""
    # T-0849: pass the SAME consumer signal the write site uses, so a consumer's committed map (which
    # carries the kernel-provided header note) compares against a regenerated map that ALSO carries it
    # — no spurious floor-map-drift. Engine self-build: _is_consumer_build() False both sides → unchanged.
    expected = _render_floor_trigger_map(floor_trigger_map or {}, specs or {},
                                         kernel_provided=_is_consumer_build())
    fmpath = GRAPH_PATH.parent / "floor-trigger-map.md"
    actual = fmpath.read_text(encoding="utf-8") if fmpath.exists() else ""
    if expected != actual:
        return [{"kind": "floor-map-drift",
                 "detail": "committed graph/floor-trigger-map.md != the regenerated map "
                           "(run `yitc-v2 graph build` to refresh the derived floor trigger-map)"}]
    return []


def _graph_query_recurring(index: dict, *, EVENTS_PATH, _capture_cluster_counts, _capture_fingerprint_counts,
                           _discovery_stem_clusters=None) -> None:
    """Report deviation fingerprints recurring N>=2 across capture events — the promotion
    threshold (D-0035). Reads events.jsonl directly (fingerprints live in event `data`, not the
    bounded graph index) and cross-refs any matching errors/E-XXXX node. Reads BOTH the current
    `deviation_captured` (D-0086 rename) AND the legacy `friction_captured` lines so historical
    captures keep counting (append-only, P5-safe — the rename never resets recurrence).

    THREE row sources, never two (T-11746, answering cross item X-1187):
      (1) STANDALONE per-fingerprint counts at n>=2 — byte-identical fingerprint equality;
      (2) the CITED rollup (`_capture_cluster_counts`) — families a case file ALREADY cites via the
          SPEC-0055 §9 LINK RULE; this stays the AUTHORITATIVE recurrence count;
      (3) the DISCOVERY stem-clusters (`_discovery_stem_clusters`, SPEC-0055 §Discovery
          stem-clustering) — UNCITED near-synonym families.
    Source (3) is what this surface previously lacked, and its absence was the whole defect: every
    author writes a fresh instance-specific fingerprint, so a genuine family of N presents as N
    singletons, each dropped by the `n < 2` test, and a real root NEVER reaches the promotion
    threshold. Counting root-CLUSTERS rather than fingerprint EQUALITY is the fix; the N>=2 threshold
    value is unchanged, no new store and no new clusterer are added, and the three sources never
    double-claim a fingerprint (members of (2) and (3) are excluded from (1); (3) excludes owned
    fingerprints upstream by construction).
    A discovery row is labelled as such because it is a CONFIRM-CAUSE-OR-DISBAND candidate
    (SPEC-0056 §2) — a hint to act on, NEVER an authoritative count."""
    counts = _capture_fingerprint_counts(EVENTS_PATH)   # shared scan (T-0152) — reads BOTH event names
    # CLUSTER-AWARE (T-0277): a root fragmented across many near-synonym fingerprints (each N=1) is
    # rolled up under its canonical fingerprint via the `cites:` LINK RULE, so the TRUE recurrence
    # crosses the N>=2 threshold instead of staying invisible (the D-0035 undercount fix).
    clusters = _capture_cluster_counts(EVENTS_PATH)   # {canonical_fp: {error, members, total, status}}
    clustered_members = {fp for cl in clusters.values() for fp in cl["members"]}
    # DISCOVERY stem-clusters (T-11746) — the UNCITED half. Same reader `triage run` Section B2 uses,
    # injected rather than re-derived; a caller that does not pass it keeps the prior two-source
    # behaviour (no new dependency is forced on an existing call site).
    discovery = _discovery_stem_clusters(EVENTS_PATH) if _discovery_stem_clusters else {}
    discovery_members = {fp for cl in discovery.values() for fp in cl["members"]}
    errors = index.get("errors", {}) or {}
    fp_to_error = {v.get("fingerprint"): k for k, v in errors.items() if v.get("fingerprint")}
    rows = []   # (count, fp, suffix)
    for fp, n in counts.items():           # standalone (un-clustered) fingerprints, prior behaviour
        if fp in clustered_members or fp in discovery_members or n < 2:
            continue
        e = fp_to_error.get(fp)
        rows.append((n, fp, f"  -> {e}" if e else "  (no case file — promotion candidate)"))
    for canon, cl in clusters.items():     # rolled-up canonical classes (aggregate count)
        if cl["total"] >= 2:
            rows.append((cl["total"], canon,
                         f"  -> {cl['error']} (clustered: {len(cl['members'])} fingerprints, cites LINK RULE)"))
    for stem, cl in discovery.items():     # uncited near-synonym families (aggregate count)
        # `_discovery_stem_clusters` already returns families of >=2 DISTINCT spellings ONLY, and its
        # members are unowned by construction — so a family here is a promotion CANDIDATE the
        # per-fingerprint count could not produce. It is a discovery hint, not an authority: the row
        # says so, and the route is SPEC-0056 §2 confirm-cause-or-disband.
        rows.append((cl["total"], stem,
                     f"  (no case file — discovery family: {len(cl['members'])} uncited spellings, "
                     f"confirm-cause-or-disband)"))
    if not rows:
        print("(no recurring fingerprints — none at N>=2)")
        return
    for n, fp, suffix in sorted(rows, key=lambda r: (-r[0], r[1])):
        print(f"{n}x  {fp}{suffix}")


def _handbook_binding_mirror_underlist(handbook_docs: dict, backing: dict, stage_names: set, *, _SPEC_ID_RE, _contiguous_blocks, _mirror_lines) -> list:
    """T-0530 check — a handbook BLOCK that MIRRORS the binding map must list, for EACH stage surface it
    names, EVERY spec the binding-derived map backs for that surface; a backed spec the mirror OMITS =
    `handbook-binding-mirror-underlist` (an under-listing the existing not-backed OVERLAP check —
    `_handbook_routing_duplication` — cannot catch, since overlap only flags wrong/extra specs, never
    omissions). A block is a mirror iff it has ≥1 MIRROR LINE (`_mirror_lines`: ≥2 specs ∧ ≥2 stage
    surfaces — the multi-pair enumeration shape, NOT the plan-FSM analog table). The listed-spec set per
    surface is aggregated across ALL of the block's MIRROR lines (absorbs audit-pre F2 — a mirror split
    across adjacent lines is ONE unit: e.g. AGENTS:23-24, where each line is itself a multi-pair mirror
    line; the per-surface listed-set unions across them so an omission on any of them is caught — without
    pulling specs off unrelated non-mirror lines in the same block).

    **Scope boundary (deliberate, NOT a gap — ceiling-convergence consult F2 decline +
    deviation `mirror-underlist-block-scope-false-positive-on-plan-fsm-analog-table`):** the mirror is
    recognized by the multi-pair ENUMERATION shape (a `≥2 specs ∧ ≥2 surfaces` line). A block whose lines
    are EACH a single surface↔single spec pointer is NOT promoted to a mirror — that shape is structurally
    indistinguishable from two ordinary forward-pointers, and forcing every such pointer to enumerate all
    of a stage's specs is the completeness over-reach CHARTER non-goal #7 / GRAPH not-a-validation-layer
    declines (audit-post asked to drop the gate; that reintroduces the plan-FSM-table false positive the
    consult already adjudicated — so the gate STAYS). A real binding-map mirror IS a multi-pair
    enumeration (every shipped one — AGENTS:23-24 — is), so this boundary loses no genuine mirror.
    PURE over `handbook_docs`. Returns a sorted list of {file, line, surface, missing, kind} —
    `line` = the surface's FIRST mirror line in the block."""
    out = []
    stage_backed = {s: sids for s, sids in (backing or {}).items() if s in stage_names and sids}
    for name in sorted(handbook_docs):
        for block in _contiguous_blocks(handbook_docs[name] or ""):
            # detect the mirror SHAPE over the FULL canonical stage vocab (a mirror line may name a stage
            # with no backed spec, e.g. Filing); the under-list COMPARISON below is scoped to backed surfaces.
            mlines = _mirror_lines(block, set(stage_names))
            if not mlines:
                continue                           # no multi-pair enumeration line — not a binding-map mirror.
            named = set().union(*(surfs for _, _, surfs in mlines)) & set(stage_backed)
            for surface in sorted(named):
                listed, first_line = set(), None
                for ln, raw, _ in mlines:          # aggregate SPEC ids across the MIRROR lines naming this surface
                    if not re.search(r"(?<![A-Za-z0-9-])" + re.escape(surface) + r"(?![A-Za-z0-9-])", raw):
                        continue
                    if first_line is None:
                        first_line = ln
                    listed |= {mm.group(0) for mm in _SPEC_ID_RE.finditer(raw)}
                missing = sorted(set(stage_backed[surface]) - listed)
                if missing:
                    out.append({"file": name, "line": first_line, "surface": surface,
                                "missing": missing, "kind": "handbook-binding-mirror-underlist"})
    return sorted(out, key=lambda v: (v["file"], v["line"], v["surface"]))


def _handbook_routing_duplication(floor_trigger_map: dict, stage_to_specs: dict, handbook_docs: dict, *, _derived_routing_backing, _handbook_routing_assertions, _routing_surface_vocab) -> list:
    """T-0300 check (a) — the 5 handbook files' RENDERED routing sections checked AGAINST the binding-
    derived map (scope item a). PURE over the passed `handbook_docs` ({filename: text}). A handbook line
    asserting a routing surface whose on-line SPEC ids include NONE the derived map backs for that surface
    = `handbook-routing-duplication`: a stale / divergent routing the single carrier (the per-spec
    `binding:`) no longer backs. OVERLAP (not exact pairing) → multi-token/multi-spec safe + zero false-
    positive on the canonical corpus, where every routing assertion names a map-backed spec. Returns a
    sorted list of {file, line, surface, specs, kind}."""
    backing = _derived_routing_backing(floor_trigger_map, stage_to_specs)
    vocab = _routing_surface_vocab(floor_trigger_map)
    out = []
    for name in sorted(handbook_docs):
        for a in _handbook_routing_assertions(handbook_docs[name] or "", vocab):
            if not (set(a["specs"]) & backing.get(a["surface"], set())):
                out.append({"file": name, "line": a["line"], "surface": a["surface"],
                            "specs": a["specs"], "kind": "handbook-routing-duplication"})
    return sorted(out, key=lambda v: (v["file"], v["line"], v["surface"]))


def _handbook_verb_drift(handbook_docs: dict, live_verbs: set, *, _DEFERRED_MARKER_RE, _HANDBOOK_VERB_RE) -> list:
    """T-0530 check — every CLI verb NAMED in handbook prose must resolve to a LIVE parser (`build_parser`
    surface, via `_live_cli_verbs`) OR be explicitly `(deferred)`-marked. PURE over the passed
    `handbook_docs` ({filename: text}). Per `bin/yitc-v2 <group> [<sub>]` mention: prefer the two-word
    `<group> <sub>` if it is a live verb, else fall back to the bare `<group>`; FLAG when NEITHER resolves
    AND the line carries no `(deferred)` marker = `handbook-verb-not-built` (the prose names a verb the CLI
    hard-rejects). Returns a sorted list of {file, line, verb, kind}. Catches AGENTS naming
    `bin/yitc-v2 self-check` (no live parser, no marker)."""
    out = []
    for name in sorted(handbook_docs):
        for ln, raw in enumerate((handbook_docs[name] or "").splitlines(), start=1):
            if _DEFERRED_MARKER_RE.search(raw):
                continue
            for m in _HANDBOOK_VERB_RE.finditer(raw):
                grp, sub = m.group(1), m.group(2)
                pair = f"{grp} {sub}" if sub else None
                if pair and pair in live_verbs:
                    continue                       # a real two-word verb (e.g. `task close`) — fine.
                if grp in live_verbs:
                    continue                       # a real group (`event deviation_captured`: `event` is live).
                verb = pair if pair else grp
                out.append({"file": name, "line": ln, "verb": verb, "kind": "handbook-verb-not-built"})
    return sorted(out, key=lambda v: (v["file"], v["line"], v["verb"]))


#: T-12291 (SPEC-0204 rule 6 / VP6) — the `audit` subcommands whose `--help` text the
#: `retired-audit-flags` absence probe reads. ONE home for the surface set: the host's capture
#: (`bin/lib/cli.py#_audit_help_texts`) iterates THIS tuple, and the checker below fails closed on a
#: capture that does not carry every one of them — so the two cannot disagree about what was scanned.
RETIRED_AUDIT_HELP_SURFACES = ("pre", "post", "consult")

#: The surface whose GRAMMAR rule (b) below reads — the consult, the one `audit` subcommand that had a
#: retired non-flag FORM rather than a retired flag.
_RETIRED_AUDIT_CONSULT_SURFACE = "consult"

#: A flag token ends at the first character that cannot be part of one. Used for BOTH the lookbehind and
#: the lookahead, so a token is matched WHOLE (incl. its `=`-joined form `--owner-reset=1`) and never as
#: a prefix — `--owner-reset-something` is a DIFFERENT token and this probe must not claim it, exactly
#: as `bin/lib/audit.py#retired_audit_surface_refusal` documents for the shim side.
_FLAG_TOKEN_CHARS = r"[A-Za-z0-9_-]"


def _names_flag_token(text: str, token: str) -> bool:
    """True iff `text` names `token` as a WHOLE flag token (see `_FLAG_TOKEN_CHARS`). PURE."""
    pat = f"(?<!{_FLAG_TOKEN_CHARS}){re.escape(token)}(?!{_FLAG_TOKEN_CHARS})"
    return re.search(pat, text or "") is not None


def retired_plan_gate_terminal_violations(live_reasons, retired_reasons) -> list:
    """T-12335 (SPEC-0204 plan-gate arm, AC3) — the `retired-plan-gate-terminal` absence probe: a
    terminal reason this contract RETIRED for a plan gate must stay ABSENT from the reasons a plan gate
    can still reach.

    WHAT IS SILENT WITHOUT IT (SPEC-0165). The plan-gate `malformed-exhausted` terminal is what stranded
    two consumer plans that had CONVERGED on the merits (aiseller `otgruzki-design-parity-…` gate
    draft-specs, X-1334; kupiclub `podklyuchenie-statistiki-…` gate specs-trial, X-1336): every door was
    shut and the only exit was cancelling the plan. This arm makes it unreachable by retiring the
    plan-gate consult that opened the episodes and by refusing a malformed response at parse. NOTHING
    watched that: re-registering the plan-gate consult would silently make the terminal reachable again,
    and no land-verify check would fire.

    Its differential failing input is the PRE-RETIREMENT engine, where the plan-gate consult was live —
    `plan_gate_live_terminal_reasons()` then returns the whole vocabulary and every retired reason is
    reported. That is why the LIVE set is DERIVED from the retirement carrier rather than declared: a
    declared empty tuple would be this probe asserting its own answer.

    TWO RULES, ONE `kind`:
      (a) PRESENCE — a retired reason appearing in the live set is a violation, named.
      (b) FAIL-CLOSED — an EMPTY `retired_reasons` is itself a violation: an absence probe with no
          subject must not read as «nothing retired found», which is the one way it could pass vacuously
          forever. An empty LIVE set is the healthy state and is not a violation.

    PURE over passed-in data; the derivation lives in `bin/lib/audit.py` and is injected, which is what
    keeps this module inside its declared `state`+stdlib import bound (the `retired_audit_flag_violations`
    discipline). Returns a sorted list of {kind, reason, detail}."""
    live = tuple(live_reasons or ())
    retired = tuple(retired_reasons or ())
    out = []
    if not retired:
        out.append({"kind": "retired-plan-gate-terminal", "reason": "<subject>",
                    "detail": "no RETIRED plan-gate terminal reason was supplied, so the absence could "
                              "not be evaluated — an absence probe with no subject fails CLOSED, it "
                              "never reads as clean"})
    for reason in sorted(set(retired) & set(live)):
        out.append({"kind": "retired-plan-gate-terminal", "reason": reason,
                    "detail": f"the consult terminal reason `{reason}` is RETIRED for a plan gate "
                              f"(SPEC-0204 rule 6, plan-gate arm) yet is still reachable on the "
                              f"plan-gate path — the plan-gate consult retirement was removed or "
                              f"bypassed, which re-opens the terminal that stranded X-1334 / X-1336"})
    return sorted(out, key=lambda v: (v["kind"], v["reason"]))


def retired_audit_flag_violations(help_texts: dict, retired_flags, retired_surfaces=None) -> list:
    """T-12291 (SPEC-0204 rule 6, VP6) — the `retired-audit-flags` absence probe: the retired post-ceiling
    `audit` surfaces must STAY absent from the CLI's own `--help` text.

    WHAT IS SILENT WITHOUT IT (SPEC-0165). C5 (T-12290) removed `--owner-reset` / `--reopen` from the
    accepted grammar and the help text and left refusal shims behind them; `tests/
    test_ceiling_decisions_retirements.py` asserts that absence ONCE. Nothing watched the CLI SURFACE, so
    a later card could re-register a retired flag and no land-verify check would fire. SPEC-0204 rule 6
    requires exactly this probe, and VP6 states its differential: the probe's failing input is the
    PRE-RETIREMENT CLI help, which named every one of these.

    THREE RULES, ONE `kind` (`retired-audit-flags`), so a RED names the check once and the offending token
    per finding:
      (a) TOKEN — no token of `retired_flags` may appear in ANY captured surface.
      (b) CONSULT GRAMMAR — in the `consult` surface, `--task` present while `--on-demand` is ABSENT. The
          retired form is `audit consult --task <T> --stage <pre|post>` (a GRAMMAR, not a flag: it keeps
          its flags registered precisely so a live caller meets the retirement pointer instead of an
          unknown-flag error), and once the shims are deleted at the plan's `realized` the ONLY live
          `--task` consult form IS `--on-demand` — so a `--task`-accepting consult that offers no
          `--on-demand` is the ceiling-adjudication form returning. Fires only when `retired_surfaces`
          names `consult-task-form`, and quotes THAT entry, so the retirement prose stays single-home.
      (c) FAIL-CLOSED — a capture missing any `RETIRED_AUDIT_HELP_SURFACES` entry, or carrying empty text
          for one, is ITSELF a violation. An absence probe whose input never arrived must not read as
          «nothing retired found»: that is the one way this check could pass vacuously forever.

    PURE over passed-in data, and the help-text SOURCE is INJECTED — which is both what keeps this module
    inside its declared `state`+stdlib import bound (it is subprocess-free by contract; git access is
    injected the same way, see `event_catalog_tree_inputs`) and what lets the RED half be proven on a
    FIXTURE, with no real retired flag anywhere in the tree. The CLI-truth sibling is
    `_handbook_verb_drift(handbook_docs, _live_cli_verbs())`.

    `retired_flags` / `retired_surfaces` are READ IN PLACE, never copied (not even per call): their ONE home is
    `bin/lib/audit.py#RETIRED_AUDIT_FLAGS` / `#RETIRED_AUDIT_SURFACES`, the same objects the pre-parse
    shim reads, so the shim and this probe cannot disagree about what was retired.

    Returns a sorted list of {kind, surface, token, detail}."""
    help_texts = help_texts if isinstance(help_texts, dict) else {}
    # READ THE PASSED CARRIERS THEMSELVES — never `dict(...)` them (audit-post finding
    # fp1:cd3958275306033b). A per-call copy is a DIFFERENT object from the one the shim reads, which is
    # exactly the single home AC2 promises; a non-mapping argument falls back to an empty literal (so the
    # probe degrades to its fail-closed capture rule) rather than being normalised into a copy.
    flags = retired_flags if isinstance(retired_flags, dict) else {}
    surfaces = retired_surfaces if isinstance(retired_surfaces, dict) else {}
    out = []
    for surface in RETIRED_AUDIT_HELP_SURFACES:
        text = help_texts.get(surface)
        if not isinstance(text, str) or not text.strip():
            out.append({"kind": "retired-audit-flags", "surface": surface, "token": "<capture>",
                        "detail": f"no `audit {surface} --help` text was captured, so the retired-flag "
                                  f"absence could not be evaluated for that surface — an absence probe "
                                  f"with no input fails CLOSED, it never reads as clean"})
            continue
        for token in sorted(flags):
            if _names_flag_token(text, token):
                out.append({"kind": "retired-audit-flags", "surface": surface, "token": token,
                            "detail": f"`audit {surface} --help` names the RETIRED flag {token} — "
                                      f"{flags[token]}"})
        if (surface == _RETIRED_AUDIT_CONSULT_SURFACE and "consult-task-form" in surfaces
                and _names_flag_token(text, "--task")
                and not _names_flag_token(text, "--on-demand")):
            out.append({"kind": "retired-audit-flags", "surface": surface,
                        "token": "--task --stage (without --on-demand)",
                        "detail": f"`audit {surface} --help` offers a `--task` consult while naming no "
                                  f"`--on-demand`, which is the RETIRED ceiling-adjudication grammar — "
                                  f"{surfaces['consult-task-form']}"})
    return sorted(out, key=lambda v: (v["surface"], v["token"]))


def _is_valid_plan_stage_entry(tok, *, PLAN_STAGE_ENTRY_PREFIX, PLAN_STAGE_SEQUENCE) -> bool:
    """True iff `tok` is a well-formed plan-axis binding token `plan-stage-entry:<PLAN_STAGE>` whose
    <PLAN_STAGE> is a canonical linear plan stage (PLAN_STAGE_SEQUENCE). The plan-axis mirror of
    `_is_valid_stage_entry`. A malformed/unknown suffix returns False → the caller routes it to
    `unknown_tokens` (a drift signal the conformance self-test turns RED)."""
    return (isinstance(tok, str) and tok.startswith(PLAN_STAGE_ENTRY_PREFIX)
            and tok[len(PLAN_STAGE_ENTRY_PREFIX):] in PLAN_STAGE_SEQUENCE)


def _is_valid_stage_entry(tok, *, STAGE_AXIS_NAMES, STAGE_ENTRY_PREFIX) -> bool:
    """True iff `tok` is a well-formed stage-axis binding token `stage-entry:<STAGE>` whose <STAGE> is a
    canonical lifecycle stage (T-0284). A malformed/unknown stage suffix returns False → the caller
    routes it to `unknown_tokens` (a drift signal the conformance self-test turns RED)."""
    return (isinstance(tok, str) and tok.startswith(STAGE_ENTRY_PREFIX)
            and tok[len(STAGE_ENTRY_PREFIX):] in STAGE_AXIS_NAMES)


def _kernel_pattern_path(name: str, *, ENGINE_ROOT, REPO_ROOT, _is_consumer_build) -> 'Path | None':
    """Resolve patterns/<name>.md for the current checkout, with a per-NAME ENGINE_ROOT fallback for a
    -C consumer (mirrors _kernel_content_file). Consumer-own pattern wins; a missing kernel pattern
    resolves from the engine. Returns None when neither has it."""
    own = REPO_ROOT / "patterns" / f"{name}.md"
    if own.exists():
        return own
    if _is_consumer_build():
        eng = ENGINE_ROOT / "patterns" / f"{name}.md"
        if eng.exists():
            return eng
    return None


def _load_index_as_of(as_of: str, *, REPO_ROOT, _die, _run_git_cap) -> dict:
    """Load the committed graph index as of a past commit-ish OR ISO date (T-0088 / D-0046 C1).
    Pure read over git history — the index is committed (CHARTER P5), so past rule-sets are
    recoverable. A `YYYY-MM-DD` value → the newest commit on/before that day; otherwise a
    commit-ish. Dies clearly on an unresolvable ref or a commit that predates the index.

    T-0365 format history: tries `graph/index.json` at the SHA first; falls back to the legacy
    `graph/index.yaml` ONLY when index.json is ABSENT at that SHA (pre-switch history — immutable,
    so this fallback is permanent, not transitional). A PRESENT-but-malformed index.json dies
    loudly — parse errors are never masked by the YAML fallback (audit-pre F1)."""
    import re as _re
    import yaml as _yaml
    if _re.match(r"^\d{4}-\d{2}-\d{2}$", as_of):
        rv = _run_git_cap(["rev-list", "-1", f"--before={as_of}T23:59:59", "HEAD"], REPO_ROOT)
        sha = rv.stdout.strip()
        if rv.returncode != 0 or not sha:
            _die(f"graph query --as-of: no commit on or before {as_of}")
    else:
        rv = _run_git_cap(["rev-parse", "--verify", "--quiet", f"{as_of}^{{commit}}"], REPO_ROOT)
        sha = rv.stdout.strip()
        if rv.returncode != 0 or not sha:
            _die(f"graph query --as-of: unresolvable commit-ish {as_of!r}")
    show = _run_git_cap(["show", f"{sha}:graph/index.json"], REPO_ROOT)
    if show.returncode == 0:
        try:
            idx = json.loads(show.stdout)
        except ValueError as e:
            # fail loud — a present index.json with bad JSON is a real defect, never YAML-masked
            _die(f"graph query --as-of: index at {sha[:7]} is not valid JSON: {e}")
    else:
        # index.json ABSENT at that SHA → pre-switch history: read the legacy YAML index (permanent
        # fallback — git history is immutable; T-0365).
        show = _run_git_cap(["show", f"{sha}:graph/index.yaml"], REPO_ROOT)
        if show.returncode != 0:
            _die(f"graph query --as-of: graph index absent at {sha[:7]} (predates the index?)")
        try:
            idx = state.load_str(show.stdout)
        except Exception as e:  # noqa: BLE001
            _die(f"graph query --as-of: index at {sha[:7]} is not valid YAML: {e}")
    if not isinstance(idx, dict):
        _die(f"graph query --as-of: index at {sha[:7]} is not a mapping")
    return idx   # T-0088 audit-post F1: no stderr banner — keep output clean for scripted callers


def _manifest_path(*, SPECS_DIR) -> Path:
    """The kernel-vs-self manifest path, derived at CALL TIME from SPECS_DIR.parent (the corpus root
    that owns these specs) — NOT a frozen REPO_ROOT constant. HOST-ISOLATION (SPEC-0041): a test that
    monkeypatches SPECS_DIR to a sandbox gets a sandbox manifest path (which won't exist → the
    `graph build` regen `.exists()` guard skips it), so an in-process sandboxed build never rewrites
    the REAL repo-root manifest. In every real + YITC_REPO_ROOT case SPECS_DIR.parent == the repo root,
    so this == <root>/kernel-vs-self-manifest.md."""
    return SPECS_DIR.parent / "kernel-vs-self-manifest.md"


def _manifest_section2_rows(text: str, *, _MANIFEST_CLASS_TO_REALM, _PLACEMENT_FILE_MANIFEST_SENTINEL_RE, _section_text) -> list:
    """Parse the §2 FILE/CODE classification HAND tables for their row tokens + declared class. Returns
    a list of (token, hand_class) in document order, EXCLUDING the derived GEN region itself (so the
    parse is over the human inventory, never its own output). A row is `| <token(s)> | <CLASS> | <note> |`
    where CLASS ∈ {CORE, V2-SELF, PROJECT}; a cell may carry several `·`-joined backtick tokens (the
    .gitkeep row). The token set (which paths get a row, which dirs are uniform) is the SINGLE human
    inventory source; `_resolve_placement` is the SINGLE classifier."""
    sec = _section_text(text, "## §2 FILE / CODE classification")
    # drop the derived GEN region so we never read our own rendered rows back in.
    sec = _PLACEMENT_FILE_MANIFEST_SENTINEL_RE.sub(lambda _m: "", sec)
    rows = []
    for line in sec.splitlines():
        cells = [c.strip() for c in line.split("|")]
        if len(cells) < 5:                       # `| a | b | c |` → ['', 'a', 'b', 'c', '']
            continue
        token_cell, cls = cells[1], cells[2]
        if cls not in _MANIFEST_CLASS_TO_REALM:  # skips header / separator / non-class rows
            continue
        toks = re.findall(r"`([^`]+)`", token_cell)
        for raw in toks:
            for tok in re.split(r"[\s·]+", raw.strip()):
                tok = tok.strip()
                if tok:
                    rows.append((tok, cls))
    return rows


def _mirror_lines(block: list, stage_names: set, *, _SPEC_ID_RE, _handbook_routing_assertions) -> list:
    """The MIRROR lines of a block — a line is a binding-map mirror line iff it carries ≥2 SPEC ids AND
    names ≥2 distinct STAGE surfaces (a genuine multi-pair surface↔spec enumeration, the shape of
    AGENTS:23-24 "SPEC-0014 at Commit, SPEC-0015 at Closure, …"). This per-line `≥2 specs ∧ ≥2 surfaces`
    test is what DISTINGUISHES a true mirror from the plan-lifecycle FSM table (a status→`*task analog*`
    row that names a stage analog like "Execution + Tests" but carries a single, unrelated delivered-at
    SPEC id) — the false-positive class captured 2026-06-07 (fingerprint mirror-underlist-block-scope-
    false-positive-on-plan-fsm-analog-table). Returns [(line_no, raw, surfaces_set)]."""
    out = []
    for ln, raw in block:
        surfs = {a["surface"] for a in _handbook_routing_assertions(raw, set(), stage_names)
                 if a["surface"] in stage_names}
        sids = {mm.group(0) for mm in _SPEC_ID_RE.finditer(raw)}
        if len(surfs) >= 2 and len(sids) >= 2:
            out.append((ln, raw, surfs))
    return out


def _node_source_path(nid: str, node_type: str, *, force_engine: bool=False, ENGINE_ROOT, LESSONS_DIR, PATTERNS_DIR, SCENARIOS_DIR, _find_draft, _find_error_yaml, _find_spec_path, _is_consumer_build, _kernel_pattern_path, _pattern_frontmatter):
    """T-0646 — resolve the SOURCE artifact file for a point-lookup node (the by-type loader).
    Returns the on-disk file whose CONTENT is the node's rule/body, or None if unresolved.
      spec    → specs/SPEC-XXXX-*.yaml   (the `body:` field + the structured fields)
      error   → errors/E-XXXX-*.yaml     (structured-only — no `body` field; print full YAML)
      pattern → patterns/<name>.md       (frontmatter + markdown body)
      plan    → plans/<slug>.md | ideas/<slug>.md (frontmatter + markdown body)
    The body is read at QUERY TIME from the source file — it is NEVER indexed into
    graph/index.json (CHARTER §P5 / GRAPH §NOT-a-caching-layer: the body lives in ONE place)."""
    if node_type == "spec":
        # T-0860: a -C consumer point-lookup of a kernel spec resolves its body from the engine.
        # T-9363: force_engine (the --kernel path) forces the KERNEL body even on a consumer collision.
        return _find_spec_path(nid, engine_fallback=True, force_engine=force_engine)
    if node_type == "error":
        # T-10748 (SPEC-0092, X-0583): force_engine (the --kernel path) forces the KERNEL case file even
        # on a consumer collision — the error-node sibling of the spec branch above.
        return _find_error_yaml(nid, force_engine=force_engine)
    if node_type == "plan":
        return _find_draft(nid)
    if node_type == "scenario":
        # T-1047: a scenario node id is its frontmatter `scenario:` key — scan scenarios/*.md for it
        # (the filename slug usually matches but the explicit key is authoritative; helpers excluded).
        if SCENARIOS_DIR.is_dir():
            for p in state.scan_scenarios(SCENARIOS_DIR):
                if p.name.startswith("_") or p.name == "README.md":
                    continue
                if _pattern_frontmatter(p).get("scenario") == nid:
                    return p
        return None
    if node_type == "lesson":
        # T-9343: a lesson node id is its frontmatter `lesson:` key — scan lessons/*.md for it (helpers
        # excluded). Per-repo only (own LESSONS_DIR) — a lesson never travels, so NO engine fallback.
        if LESSONS_DIR.is_dir():
            for p in state.scan_lessons(LESSONS_DIR):
                if p.name.startswith("_") or p.name == "README.md":
                    continue
                if _pattern_frontmatter(p).get("lesson") == nid:
                    return p
        return None
    if node_type == "pattern":
        # T-0860: per-name consumer-own-then-engine resolution (mirrors _find_spec_path engine_fallback).
        direct = _kernel_pattern_path(nid)
        if direct is not None:
            return direct
        # a pattern node id is its frontmatter `name` (build: nm = fm.name or stem) — fall back to a
        # frontmatter-name scan when the file stem differs from the indexed name (consumer then engine).
        scan_dirs = [PATTERNS_DIR]
        if _is_consumer_build():
            scan_dirs.append(ENGINE_ROOT / "patterns")
        for d in scan_dirs:
            if not d.is_dir():
                continue
            for p in sorted(d.glob("*.md")):
                fm = _pattern_frontmatter(p)
                if (fm.get("name") or p.stem) == nid:
                    return p
        return None
    return None


def _norm_relpath(rel_path: str) -> str:
    """Normalize a repo-relative path for placement lookup: backslashes → '/', and strip a leading
    './' PREFIX only. Crucially NOT `lstrip('./')` — that strips the leading dot off a DOTFILE
    (`.gitattributes` → `gitattributes`), which broke the class-default lookup for kernel dotfiles
    (T-0934). A leading dot is significant; only a './' path prefix is noise."""
    s = str(rel_path).replace("\\", "/")
    while s.startswith("./"):
        s = s[2:]
    return s


def _one_source_delivery_check(specs: dict, *, _ONE_SOURCE_NON_RETIRED, _delivery_classes) -> list:
    """T-0295 (path-B core) — the one-source DELIVERY invariant over NON-RETIRED specs: a stage-bound
    action has EXACTLY ONE delivery source. PURE, sandbox-safe. Per spec, flags:
      - `nonexistent-stage`      — a `stage-entry:<bad>` token whose <bad> is not a canonical lifecycle
                                  stage (caught at draft/proposed time too — the by-construction guarantee).
      - `second-delivery-source` — SCOPED to a spec that ALSO carries a stage-entry: the stage-entry token
                                  co-present with ≥1 verb surface (a stage-delivered spec must not ALSO be
                                  verb-before-X delivered — the retired before-content collision), OR with
                                  >1 residency token (a spec carries EXACTLY ONE residency marker). Residency
                                  is ORTHOGONAL to stage routing — a lone stage-entry + ONE residency is NOT
                                  flagged (the absorbed pass-1/2 fix). LIKEWISE the task `stage-entry:` and
                                  `plan-stage-entry:` axes are ORTHOGONAL delivery moments for DIFFERENT
                                  consumers (task Analysis vs plan decomposition) — one-source-EACH, so their
                                  co-presence is NOT a second source (T-0666 removed the T-0324 dual-axis flag).
    Returns a sorted list of {spec, kind, detail}. Skips retired/superseded/withdrawn/rejected. It does NOT
    re-flag a bare unknown verb token — that is cmd_graph_conformance's existing dangling/unknown door; this
    check owns the stage-routing one-source invariant only (one home per check, CHARTER §P5)."""
    out = []
    for sid in sorted(specs):
        rec = specs[sid] or {}
        if rec.get("status") not in _ONE_SOURCE_NON_RETIRED:
            continue
        cls = _delivery_classes(rec.get("binding"))
        for bad in sorted(cls["bad_stage_entries"]):
            out.append({"spec": sid, "kind": "nonexistent-stage", "detail": bad})
        for bad in sorted(cls["bad_plan_stage_entries"]):  # T-0324: plan-axis mirror — a nonexistent
            out.append({"spec": sid, "kind": "nonexistent-stage", "detail": bad})  # plan-stage suffix
        stage_routed = cls["stage_entries"] or cls["plan_stage_entries"]  # T-0324: EITHER stage axis is a
        if stage_routed:                                  # routing source; a stage-routed spec must not ALSO
            if cls["verbs"]:                              # be verb-before-X delivered (the second source).
                out.append({"spec": sid, "kind": "second-delivery-source",
                            "detail": f"stage routing {sorted(cls['stage_entries'] + cls['plan_stage_entries'])} "
                                      f"co-present with verb surface(s) {sorted(cls['verbs'])}"})
            # T-0666: the task vs plan stage axes are NOT a second source for each other — they are
            # ORTHOGONAL delivery MOMENTS for DIFFERENT consumers (task Analysis via stage-entry vs plan
            # decomposition via plan-stage-entry), one-source-EACH (same orthogonality as residency below).
            # The T-0324 "both stage axes = two sources" flag was an over-broad mechanical mirror — removed.
            if len(cls["residency"]) > 1:
                out.append({"spec": sid, "kind": "second-delivery-source",
                            "detail": f"stage routing co-present with >1 residency token "
                                      f"{sorted(cls['residency'])}"})
    return sorted(out, key=lambda v: (v["spec"], v["kind"], v["detail"]))


def _placement_class_for(rel_path: str, *, _norm_relpath) -> str:
    """The corpus CLASS key for a repo-relative path: its top-level segment — a named top-level file
    (events.jsonl, CHARTER.md, …) or a directory (specs, tasks, …). Pure; no I/O."""
    return _norm_relpath(rel_path).split("/", 1)[0]


def _plan_delivery_gating_stages(*, PLAN_STAGE_SEQUENCE) -> list:
    """The PLAN-axis analog of `_relocated_gating_stages` (T-0657): the linear plan-FSM stages that each
    ENTER via `plan stage <NAME>` and DELIVER a `plan-stage-entry:<NAME>` bundle (`_emit_plan_stage_entered`).
    DERIVED from the authoritative FSM constant `PLAN_STAGE_SEQUENCE` (the single source — NOT a hard-coded
    `['decomposition']` registry; audit-pre F1: no parallel truth surface, P5). `decomposition` (SPEC-0070,
    the gated cut dwell-stage) is thereby asserted "among" the covered stages, closing the T-0316
    empty-bundle seam: a stage entered without delivery content (an empty bundle the read-gate silently
    no-ops on, post-/compact). Mirrors `_relocated_gating_stages`; the terminals partial/rejected/cancelled
    are excluded (they are not in PLAN_STAGE_SEQUENCE and carry no per-stage delivery bundle)."""
    return list(PLAN_STAGE_SEQUENCE)


def _read_order_drift(handbook_docs: dict, *, _READ_ORDER_SENTINEL_RE, _is_consumer_build,
                      _render_read_order) -> list:
    """T-0671 check — every `<!--GEN:read-order:STYLE-->…<!--/GEN:read-order-->` managed region in
    AGENTS.md MUST equal render(STYLE) from the single carrier HANDBOOK_READ_ORDER; a mismatch (or no
    region at all) = `read-order-drift` (a handbook read-order surface diverged from its carrier).
    REPORT-ONLY over the passed `handbook_docs` ({filename: text}) — the caller adds it to the
    conformance RED set. Mirror of `_floor_map_drift`/`_handbook_verb_drift`: a CHECKER, it never
    rewrites prose (regen is the explicit `graph build`).

    ENGINE-ONLY — the check no-ops under `-C` (T-10541 / X-0408 + X-0409), the same exemption its
    sibling drift checks `_floor_map_drift` / `_audience_views_drift` / `_release_view_drift` carry.
    HANDBOOK_READ_ORDER is the KERNEL's handbook carrier (a kernel-realm concern, SPEC-0073
    §placement) and a consumer owns no handbook of its own — it reads the ENGINE's, resolved at the
    engine install path (SPEC-0007 §5b). So under `-C` the caller's `handbook_docs` is EMPTY (it
    filters on `(REPO_ROOT / n).exists()` and a consumer has no AGENTS.md), and the sentinel guard
    below — which fires precisely when AGENTS.md carries no managed region — false-REDs every
    consumer land on a surface the consumer cannot own. Hence the exemption sits BEFORE that guard."""
    if _is_consumer_build():
        return []
    docs = handbook_docs or {}
    # AGENTS.md MUST still carry the read-order surface (the seed's generation guard is unchanged).
    if not list(_READ_ORDER_SENTINEL_RE.finditer(docs.get("AGENTS.md") or "")):
        return [{"kind": "read-order-drift",
                 "detail": "AGENTS.md carries no <!--GEN:read-order:…--> managed region — the read-order "
                           "surfaces are no longer generated from HANDBOOK_READ_ORDER (run `yitc-v2 graph build`)"}]
    # SPEC-0120: check EVERY handbook doc that carries a read-order region — the surface now spans the
    # split AGENTS protocol family (AGENTS.md + AGENTS-SESSIONS.md + AGENTS-PROTOCOL.md), so a region in
    # a split part must ALSO match render (else a moved arrow silently goes stale — the T-9776 false-GREEN).
    findings: list = []
    for name in sorted(docs):
        for m in _READ_ORDER_SENTINEL_RE.finditer(docs[name] or ""):
            style, inner = m.group(2), m.group(3)
            try:
                expected = _render_read_order(style)
            except ValueError:
                findings.append({"kind": "read-order-drift",
                                 "detail": f"{name} read-order region has unknown style {style!r}"})
                continue
            if inner != expected:
                findings.append({"kind": "read-order-drift",
                                 "detail": f"{name} read-order region (style={style}) != render from "
                                           f"HANDBOOK_READ_ORDER (run `yitc-v2 graph build` to refresh)"})
    return findings


def _regen_file_placement_manifest(text: str, *, _PLACEMENT_FILE_MANIFEST_SENTINEL_RE, _render_file_placement_block) -> str:
    """Substitute the manifest §2 `<!--GEN:placement-file-classification …-->…<!--/GEN…-->` managed region
    with `_render_file_placement_block(text)`. PURE + idempotent. Called ONLY from the EXPLICIT
    `cmd_graph_build` (same placement as the §1 regen). The block is derived from the SAME text's hand §2
    tables, so regen is a fixed-point: the committed region cannot drift (suite-locked)."""
    return _PLACEMENT_FILE_MANIFEST_SENTINEL_RE.sub(
        lambda mm: f"{mm.group(1)}{_render_file_placement_block(text)}{mm.group(3)}", text)


def _regen_handbook_read_order(text: str, *, _READ_ORDER_SENTINEL_RE, _render_read_order) -> str:
    """Substitute every `<!--GEN:read-order:STYLE-->…<!--/GEN:read-order-->` managed region in AGENTS.md
    with render(STYLE) from the single carrier. PURE + idempotent. Called ONLY from the EXPLICIT
    `cmd_graph_build` — NOT the shared `_write_graph_index` / `_auto_rebuild_graph` land path, because
    AGENTS.md ∉ _BOOKKEEPING_ALLOWLIST (a land-time write to it would dirty main and break land). The
    committed regions cannot diverge regardless: `_read_order_drift` rides the conformance RED set, and
    the land-verify suite asserts the canonical corpus conformance-GREEN + aborts land on failure
    (SPEC-0007 §5b / SPEC-0033 report-at-land-via-tests)."""
    return _READ_ORDER_SENTINEL_RE.sub(
        lambda m: f"{m.group(1)}{_render_read_order(m.group(2))}{m.group(4)}", text)


def _regen_placement_manifest(text: str, *, _PLACEMENT_MANIFEST_SENTINEL_RE, _render_spec_placement_block) -> str:
    """Substitute the manifest §1 `<!--GEN:placement-spec-classification …-->…<!--/GEN…-->` managed
    region with `_render_spec_placement_block()`. PURE + idempotent. Called ONLY from the EXPLICIT
    `cmd_graph_build` (NOT `_auto_rebuild_graph` — the manifest ∉ _BOOKKEEPING_ALLOWLIST, so a
    land-time write would dirty main + break land — the SAME constraint as the AGENTS read-order regen).
    The committed region cannot drift: the land-verify suite includes the drift-lock test."""
    return _PLACEMENT_MANIFEST_SENTINEL_RE.sub(
        lambda mm: f"{mm.group(1)}{_render_spec_placement_block()}{mm.group(3)}", text)


def _regen_spec_code_map_manifest(text: str, index: dict, *, _SPEC_CODE_MAP_SENTINEL_RE, _render_spec_code_map_block) -> str:
    """Substitute the manifest §3 `<!--GEN:spec-code-map …-->…<!--/GEN…-->` managed region with
    `_render_spec_code_map_block(index)` — the §3 SPEC↔CODE map rendered live from the graph index's
    `specs[id].implements` (T-9541, E-0039). PURE + idempotent. Called ONLY from the EXPLICIT
    `cmd_graph_build` (the SAME constraint as the §1/§2 regen — the manifest ∉ _BOOKKEEPING_ALLOWLIST,
    so land's `_auto_rebuild_graph` never writes it). The §3 fidelity probe (test_t0874 test_c) is the
    drift-lock: the committed region == this render of the index. Mirrors `_regen_placement_manifest`
    exactly, the index-derived sibling of the §1/§2 GEN families — closing E-0039 (§3 had no GEN block,
    so a new CORE-code-backed spec's row needed a manual hand-edit that surfaced late at land)."""
    return _SPEC_CODE_MAP_SENTINEL_RE.sub(
        lambda mm: f"{mm.group(1)}{_render_spec_code_map_block(index)}{mm.group(3)}", text)


def _render_spec_code_map_block(index: dict) -> str:
    """Render the inter-sentinel content for the manifest §3 GEN region from the graph `index` —
    one `- **SPEC-XXXX** → `a`, `b`, …` row per ACTIVE CORE-code-backed spec (status active + non-empty
    `implements`), SPEC-id sorted, anchors sorted, each backtick-quoted. SAME leading/trailing-newline
    framing as the §1/§2 blocks. The exact string `_regen_spec_code_map_manifest` substitutes between
    the sentinels (so the drift-lock compares the committed inner == this render). The SELECTION mirrors
    test_t0874 test_c's `expected` set exactly (the probe this block is drift-locked against)."""
    specs = index.get("specs") or {}
    expected = {sid: sorted(s.get("implements") or [])
                for sid, s in specs.items()
                if s.get("status") == "active" and (s.get("implements") or [])}
    out = [""]
    for sid in sorted(expected):
        anchors = ", ".join(f"`{a}`" for a in expected[sid])
        out.append(f"- **{sid}** → {anchors}")
    out.append("")
    return "\n".join(out) + "\n"


def _regen_manifest_managed_regions(index: dict, *, _manifest_path, _regen_placement_manifest,
                                    _regen_file_placement_manifest, _regen_spec_code_map_manifest,
                                    write_text_atomic) -> bool:
    """T-12236 — the manifest's THREE GEN-managed regions (§1 spec placement, §2 file placement,
    §3 SPEC↔CODE map), regenerated in ONE read-modify-write. Returns True iff the file CHANGED.

    ONE DEFINITION, TWO CALL SITES (CHARTER §Principle 5). This is the block `cmd_graph_build` ran
    inline; it is LIFTED here rather than copied because `land` now needs the identical act on a tree
    it has just MERGED — the batch candidate (`_land_rederive_merged_candidate`) and the step-3
    reconcile. A second spelling of the §1→§2→§3 chain would be a second authority on what the
    committed regions are, which is exactly what the drift-locks (test_t0874 test_c / test_t9541
    test_d) assert against a SINGLE render.

    THE CHAIN ORDER IS LOAD-BEARING AND IS THE PRE-LIFT ORDER, byte for byte: §1 then §2 then §3, each
    substitution applied to the text the previous one returned, so the three regions are written by a
    single `write_text_atomic` and the file is never observed half-regenerated.

    IT CANNOT REACH AN AUTHOR EDIT. Every substitution replaces ONLY inter-sentinel content
    (`_regen_placement_manifest` / `_regen_file_placement_manifest` / `_regen_spec_code_map_manifest`
    each sub a `<!--GEN:…-->…<!--/GEN:…-->` region and nothing else), so the "explicit-build-only, or
    land clobbers author edits" constraint those functions' docstrings carry is about WHERE the write
    may be left DIRTY — not about the regeneration itself. A hand edit INSIDE a GEN region is the very
    thing the drift-lock forbids. PURE + IDEMPOTENT: a second call on the same corpus returns False.

    A MISSING MANIFEST IS A NO-OP, NOT AN ERROR — the `-C` consumer shape (a consumer vendors no
    `kernel-vs-self-manifest.md`), the same tolerance the release-view and AGENTS regens carry.

    AN EMPTY SPEC CORPUS IS THE SAME NO-OP, FOR THE SAME REASON, and this is the guard the land call
    site makes load-bearing. All three regions render FROM the spec corpus, so a corpus that reads
    EMPTY renders three EMPTY tables — and writing those over committed NON-EMPTY regions BLANKS
    derived content on evidence we plainly do not have. `graph build` never reached that state (it
    runs in a checkout whose corpus it has just indexed); `land` can, because it re-derives over
    trees it did not author. It is the SAME fail-safe direction the `index is None` arm at the host
    residue takes — leave the committed regions alone, never render from a corpus we could not read —
    and it is read off the index this function already HOLDS, adding no second corpus read.
    Measured: `tests/test_t10845_land_row_append_ledger_merge.py`
    `test_t11333_land_merges_different_manifest_table_rows` lands a keyed-merged manifest in a temp
    repo with no specs; without this guard the merged `<!--GEN:placement-spec-classification-->` rows
    were re-rendered to an empty table and the merge's own result was destroyed."""
    if not (index or {}).get("specs"):
        return False
    mf = _manifest_path()
    if not mf.exists():
        return False
    text = mf.read_text(encoding="utf-8")
    regen = _regen_spec_code_map_manifest(
        _regen_file_placement_manifest(_regen_placement_manifest(text)), index)
    if regen == text:
        return False
    write_text_atomic(mf, regen)
    return True

# ── T-9497: auto-backfill the manifest §1 HAND-table row at `spec new` (E-0029) ────────────────────
# The §1 SPEC-classification HAND table (the human-annotated VIEW) is NOT regenerated by `graph build`
# (only the §1-derived GEN block is). Pre-T-9497 a newly-authored spec had no §1 row until hand-added —
# and the omission surfaced only LATE at land, when test_t0890 §B2 failed on the missing row (the
# captured friction E-0029). This inserts the row IN-FLOW at `spec new` so the row exists by birth.
# The row's `class` PREFIX matches the resolved realm (drift-locked by §B2); anchors are a design-stage
# placeholder the author later annotates. The §1-derived GEN block stays graph-build-regenerated.
_REALM_TO_HANDROW_CLASS = {"kernel": "CORE-doctrine", "v2-self": "V2-SELF", "project": "PROJECT"}


def _backfill_spec_placement_handrow(text: str, sid: str, status: str, realm: str, note: str) -> str:
    """Insert a §1 SPEC-classification HAND-table row for a newly-authored spec into the manifest TEXT,
    returning the new text (PURE — the caller writes it). IDEMPOTENT: a row already present for `sid`
    returns the text unchanged. FAIL-SAFE: an unknown realm or an absent §1 hand table returns the text
    untouched (never corrupts the manifest). The row is inserted in sorted SPEC-id order among the
    existing §1 rows; its `class` column carries the realm-derived PREFIX (CORE/V2-SELF/PROJECT) so the
    §B2 drift-lock (tests/test_t0890_placement_backfill.py) holds at birth. Home of the E-0029 fix."""
    class_label = _REALM_TO_HANDROW_CLASS.get(realm)
    if class_label is None:
        return text  # unknown realm — fail-safe, leave the manifest untouched
    note_esc = (note or "").replace("|", r"\|").replace("\n", " ").strip()
    new_row = (f"| {sid} | {status} | {class_label} | — (design-stage, implements: []) | "
               f"{note_esc} (AUTO-BACKFILLED at spec new — E-0029/T-9497) |")
    lines = text.splitlines()
    sep_re = re.compile(r"\|(?:\s*-+\s*\|){5}")          # the 5-column §1 hand-table separator
    sep_idx = next((i for i, ln in enumerate(lines) if sep_re.fullmatch(ln.strip())), None)
    if sep_idx is None:
        return text  # no §1 hand table — fail-safe
    row_re = re.compile(r"^\|\s*(SPEC-\d{4,})\s*\|")
    rows = []
    j = sep_idx + 1
    while j < len(lines):
        m = row_re.match(lines[j])
        if not m:
            break
        if m.group(1) == sid:
            return text  # already present — idempotent
        rows.append((j, m.group(1)))
        j += 1
    insert_at = next((idx for idx, ex in rows if sid < ex), j)
    lines.insert(insert_at, new_row)
    return "\n".join(lines) + ("\n" if text.endswith("\n") else "")


def _relocated_gating_stages(*, SURFACE_TO_STAGE) -> list:
    """The RELOCATED lifecycle gating-verb stages — the verbs whose before-X governing contract was moved
    onto the stage-entry delivery axis (T-0289: SPEC-0014→Commit / SPEC-0015→Closure / SPEC-0016→Audit-pre
    + Audit-post). DERIVED from SURFACE_TO_STAGE (the single carrier, P5) minus the DEPRECATED-legacy
    before-analysis claim marker (Analysis is work-verb entry, not a relocated gating verb)."""
    return sorted({stage for surf, stage in SURFACE_TO_STAGE.items() if surf != "before-analysis"})


def _render_file_placement_block(text: str, *, _derive_file_placement) -> str:
    """Render the inter-sentinel content for the manifest §2 GEN region from `_derive_file_placement()`
    — a deterministic markdown table (same leading/trailing-newline framing as the §1 block). Tokens are
    rendered WITHOUT backticks (like the §1-derived SPEC rows) so the §2 completeness probe's backtick
    token-scan never re-reads them as coverage rows."""
    rows = _derive_file_placement(text)
    out = ["", "| path / dir token | placement realm (DERIVED: class-default matrix + file-override map) |",
           "|---|---|"]
    out += [f"| {tok} | {realm} |" for tok, realm in rows]
    out.append("")
    return "\n".join(out) + "\n"


# ── T-12086: the born-secure profile-gated delivery (SPEC-0100 §Born-secure × SPEC-0198) ──────────
# The two floor rows `before-authoring-public-boundary` / `before-adding-a-dependency` point a session at
# `graph query SPEC-0100`. Its ten items are NOT all for every project: two are a CONSTANT FLOOR and eight
# apply at a public/unknown surface. The gate below is the ONLY thing about those items that lives in code
# — the item TEXT (rule, probe, bad input, ASVS citation) single-homes in the SPEC-0100 body, so this table
# can never become a second copy of it (CHARTER §P5). What lives here is the pair (item key, activating
# LENS); the lens vocabulary is `bin/lib/profile.py`'s, the ONE derivation site (SPEC-0198 rule 3), which
# this module reads and never re-derives — deliberately NO dimension names appear here.
BORN_SECURE_SPEC = "SPEC-0100"
BORN_SECURE_HEADING = "## Born-secure authoring-moment baseline"
#: (item key, activating lens). The eight BOUNDARY items ride `public-boundary` (profile.py `_ACTIVATION`:
#: surface in public|unknown); `dependency-hygiene` and `secrets` are profile.py's CONSTANT_FLOOR, so
#: items 9 and 10 are delivered at every profile including a proven prototype (SPEC-0198 rule 7).
BORN_SECURE_ITEMS = (
    ("object-level-authz", "public-boundary"),
    ("input-validation", "public-boundary"),
    ("injection-safe-data-access", "public-boundary"),
    ("output-encoding", "public-boundary"),
    ("endpoint-size-rate-bounds", "public-boundary"),
    ("headers-cors", "public-boundary"),
    ("upload-handling", "public-boundary"),
    ("ssrf-outbound-url", "public-boundary"),
    ("dependency-hygiene", "dependency-hygiene"),
    ("pii-log-error-safety", "secrets"),
)
#: The lenses the two CONSTANT-FLOOR items ride — the fail-closed set when no profile can be resolved.
BORN_SECURE_CONSTANT_LENSES = ("dependency-hygiene", "secrets")
#: SPEC-0198 §8, and audit-pre finding 1 of BOTH passes: a profile is a SNAPSHOT and an EDIT can move it,
#: so the question is asked BEFORE a byte of born-secure content — ahead of the section heading itself.
BORN_SECURE_PROFILE_QUESTION = (
    "> **First, before the items below: does THIS edit RAISE the profile?** A first public endpoint, a\n"
    "> first live deploy, a first user-data field, a first outbound call on a caller-supplied URL, a first\n"
    "> named collaborator — any of these makes the profile you are being gated by ALREADY STALE. If this\n"
    "> edit raises it, apply the HIGHER check-set to THIS edit (not the next one) and record the crossing\n"
    "> in `yitc-ops.yaml` (SPEC-0198 §8). The gating below reads the profile as it is NOW."
)
#: The item-heading matcher — `N. **Title** — `key` (ASVS …)`. The key inside the backticks is the join
#: to BORN_SECURE_ITEMS; the test asserts the two key sets are equal, so body and gate cannot drift.
_BORN_SECURE_ITEM_RE = re.compile(r"^[ \t]*(\d+)\. \*\*(.+?)\*\* — `([a-z0-9-]+)`", re.MULTILINE)


def born_secure_render(body: str, root, *, events=(), ops=None) -> str:
    """Render the SPEC-0100 body with its §Born-secure items GATED by the SPEC-0198 profile at `root`.

    ONE seam, applied BEFORE the body is printed (audit-pre pass 1): a withheld item is ABSENT from the
    delivered text, never merely unmentioned by a trailing block. Order of the rendered section:
    the profile-raising QUESTION, then the heading, then the section's intro prose, then only the item
    blocks whose lens the profile activates, then one line naming what was withheld and why.

    FAIL-CLOSED (audit-pre pass 2): there is no return-the-body-unchanged path for a PROFILE failure.
    `profile.resolve_profile` never raises, and when it cannot resolve (`resolved` False — e.g. no
    checkout at that path) or yields an empty check_set, this delivers the two CONSTANT-FLOOR items ONLY.
    A RESOLVED-but-`unknown` profile stays WIDE — that is SPEC-0198 rule 2's own conservatism (an unknown
    surface activates `public-boundary`), not a fallback. The one unchanged-body path is STRUCTURAL: a
    body carrying no §Born-secure heading has nothing to gate.

    Reads `bin/lib/profile.py` and nothing else; the import is deferred so this module keeps its
    stdlib+state+host_paths bound (T-12024) for every caller that never queries SPEC-0100.
    """
    at = body.find(BORN_SECURE_HEADING)
    if at == -1:
        return body
    from lib import profile as _profile          # deferred — see the docstring bound

    res = _profile.resolve_profile(root, events=events, ops=ops)
    check_set = set(res.get("check_set") or ())
    unresolved = (res.get("resolved") is False) or not check_set
    if unresolved:
        check_set = set(BORN_SECURE_CONSTANT_LENSES)

    # INDENT-AWARE: the delivered text is the spec's YAML FILE, whose body is a block scalar — every body
    # line carries the block indent. Derive it from the heading's own line so the injected question and
    # note land inside the block (a de-indented line would break the YAML the reader is looking at).
    line_start = body.rfind("\n", 0, at) + 1
    indent = body[line_start:at]
    head, rest = body[:line_start], body[at:]
    tail_split = rest.find("\n" + indent + "## ")   # the section ends at the next same-level heading
    section, after = (rest[:tail_split], rest[tail_split:]) if tail_split != -1 else (rest, "")

    matches = list(_BORN_SECURE_ITEM_RE.finditer(section))
    if not matches:
        return body                                # no parsable items — nothing to gate (structural)
    intro = section[len(BORN_SECURE_HEADING):matches[0].start()].rstrip("\n")
    kept, withheld = [], []
    lens_of = dict(BORN_SECURE_ITEMS)
    for n, m in enumerate(matches):
        end = matches[n + 1].start() if n + 1 < len(matches) else len(section)
        block = section[m.start():end].rstrip("\n")
        (kept if lens_of.get(m.group(3)) in check_set else withheld).append(block)

    why = ("the project growth profile could not be RESOLVED for this checkout, so delivery FAILS CLOSED "
           "to the constant floor" if unresolved else
           "this project's resolved SPEC-0198 profile does not activate their lens "
           f"(check_set: {', '.join(sorted(check_set)) or 'empty'})")
    note = ((f"*{len(withheld)} further item(s) are NOT delivered here — {why}. Run "
             f"`bin/yitc-v2 profile` to see the resolution, and re-read this spec if the profile rises.*")
            if withheld else
            f"*All {len(matches)} items are delivered — this project's profile activates every lens.*")
    q = "\n".join(indent + l if l else "" for l in BORN_SECURE_PROFILE_QUESTION.split("\n"))
    return "".join([head, q, "\n\n", indent, BORN_SECURE_HEADING, intro,
                    "\n\n", "\n\n".join(kept), "\n\n", indent, note, "\n", after])



def _render_floor_trigger_map(floor_trigger_map: dict, specs: dict, kernel_provided: bool=False, *, FLOOR_TRIGGERS, KERNEL_NAME, FLOOR_TRIGGER_GOVERNED_VERB=None) -> str:
    """Render the always-loaded floor trigger-map (T-0230, Part I-A) → graph/floor-trigger-map.md.
    A GENERATED, derived-only committed artifact: regenerated every `graph build` from the single
    canonical carrier (the per-spec `binding:` field). Each line is KEYED by the verb surface so the
    AP3 probe can assert presence/absence per verb. Pure helper → shared by both build sites.

    `kernel_provided` (T-0849, friction F-001): True on a CONSUMER build — prepend a header note
    attributing this map to the kernel (its triggers/surfaces come from the engine FLOOR_TRIGGERS /
    verb-surface constants, not the consumer's own specs). The binding-derived BODY is unchanged; the
    note is additive/presentational. BOTH call sites (_write_graph_index write + _floor_map_drift
    freshness check) pass the SAME _is_consumer_build() signal, so the committed map and the regenerated
    map stay byte-equal for a given checkout (the SPEC-0033 floor-map-drift invariant is preserved)."""
    lines = [
        "<!-- GENERATED by `bin/yitc-v2 graph build` from the per-spec `binding:` field (T-0230).",
        "     DO NOT EDIT — hand edits are overwritten on the next build. Single canonical carrier:",
        "     the `binding:` field on each spec; this map is a derived-only view (plan-check finding 1). -->",
        "",
        "# Floor trigger-map — read BEFORE the gated action (always-loaded tier)",
        # T-10025 (SPEC-0127 §1a): the floor map is a whole-file `core` surface, but its explicit
        # `<!--AUDIENCE:core-->` marker is DEFERRED to T-10026 (delivery) — §1a: "Until then it resolves
        # to core by the §2 default". Emitting it HERE is unsafe: this artifact is regenerated by land's
        # from-MAIN bookkeeping engine (pre-merge, marker-less) while pinned verify uses the MERGED engine,
        # so a marker-emitting generator floor-map-DRIFTS at land (deviation: land-bookkeeping-generator-
        # change-drift). The audience-view machinery parses CANONICAL_DOCS only, never this file, so the
        # §2 default (untagged ⇒ core) is fully sufficient for this card.
        "",
    ]
    if kernel_provided:
        lines += [
            "> **Kernel-provided (consumer build, F-001).** This floor trigger-map is generated from the",
            "> " + KERNEL_NAME + " ENGINE's FLOOR_TRIGGERS / verb-surface constants — NOT from this",
            "> project's own specs. It is provided by the kernel to drive this consumer's read-gates; the",
            "> spec id(s) it lists resolve against the kernel corpus, not project-derived nodes.",
            "",
        ]
    lines += [
        "The mandatory-on-entry triggers (the obligation set, Part I-A). Before the named action,",
        "read the listed `retrieved` spec(s) via `bin/yitc-v2 graph query <SPEC-ID>`.",
        "",
    ]
    # T-10032 (SPEC-0128 Rule 2): render the static FLOOR_TRIGGERS rows FIRST (byte-stable, per-verb keyed),
    # THEN the registry-DERIVED before-authoring-<concern> family — the EXTRA floor_trigger_map keys not in
    # FLOOR_TRIGGERS, in sorted order (deterministic), each keyed by its single trigger==surface. This keeps
    # the derived rows a pure f(floor_trigger_map, specs) so _floor_map_drift stays consistent (P5).
    static_trigs = [t for t, _ in FLOOR_TRIGGERS]
    render_order = [(t, s) for t, s in FLOOR_TRIGGERS]
    render_order += [(t, tuple((floor_trigger_map.get(t) or {}).keys()))
                     for t in sorted(floor_trigger_map) if t not in static_trigs]
    for trig, surfaces in render_order:
        entry = floor_trigger_map.get(trig) or {}
        # T-9787 (X-0161): a trigger whose gated action is done BY a governed verb co-names that verb
        # invocation on its row — so the floor row surfaces THAT the action runs via the verb, not only
        # the policy spec that governs HOW (discoverability fix, e.g. before-deploy → `deploy --class`).
        gverb = (FLOOR_TRIGGER_GOVERNED_VERB or {}).get(trig)
        gsuffix = f" — done via `{gverb}`" if gverb else ""
        for surface in surfaces:                     # one block PER individual verb surface (per-verb keying)
            sids = entry.get(surface) or []
            if sids:
                for sid in sids:
                    title = (specs.get(sid) or {}).get("title", "")
                    lines.append(f"- **{trig}** (`{surface}`) → read `{sid}` — {title}{gsuffix}")
            else:
                lines.append(f"- **{trig}** (`{surface}`) → (no `retrieved` spec bound yet — see binding_report)")
    lines.append("")
    return "\n".join(lines)


def _activation_concern_rows(specs: dict) -> list:
    """The derived activation baseline-concern roster (T-9410, SPEC-0096): the WELL-FORMED `init_concern`
    declarations across all specs, sorted by spec id (deterministic output). FAIL-CLOSED (SPEC-0096 guard
    a / audit-pre F0): a spec is surfaced ONLY when its `init_concern` is a MAPPING carrying a non-empty
    `init_question` string — a non-mapping value, or a missing/empty `init_question`, is SKIPPED entirely
    (never crashes, never half-surfaces), so it lands in NEITHER derived view. Companion fields
    (waiver/evidence/tier) are normalized to a single-line display string ('—' when absent). Pure helper
    shared by both derived views so they cannot diverge from each other (P5)."""
    def _disp(v) -> str:
        s = " ".join(str(v).split()) if v is not None else ""
        return s if s else "—"
    rows = []
    for sid in sorted(specs):
        # T-10176 — active-only: a draft/proposed spec is non-authoritative (SPEC-0005 §4), so its
        # `init_concern` must NOT surface in the consumer-shipped activation-checklist until the spec
        # ACTIVATES (the sibling of the T-10175 concern-registry gate; same live-spec rule as
        # `_active_concern_blocks`). Skip a spec whose status is EXPLICITLY non-active; a status-LESS spec
        # is admitted — only synthetic fixtures omit status (a real spec always carries one), so
        # production is active-only while the mechanics tests stay status-agnostic. (`_build_binding_views`
        # is the strict-active sibling for the binding→floor derivation.)
        status = (specs.get(sid) or {}).get("status")
        if status is not None and status != "active":
            continue
        ic = (specs.get(sid) or {}).get("init_concern")
        if not isinstance(ic, dict):
            continue
        q = ic.get("init_question")
        if not isinstance(q, str) or not q.strip():
            continue
        rows.append((sid, " ".join(q.split()), _disp(ic.get("waiver")),
                     _disp(ic.get("evidence")), _disp(ic.get("tier"))))
    return rows


def _render_activation_checklist(specs: dict) -> str:
    """Render the activation baseline-concern checklist (T-9410, SPEC-0096) → graph/activation-checklist.md.
    A GENERATED, derived-only committed artifact — the SIBLING of graph/floor-trigger-map.md: regenerated
    every `graph build` from each concern spec's `init_concern` declaration (the SPEC-0030 schema field)
    into ONE DO-NOT-EDIT artifact carrying TWO derived views over the SAME source — the machine init-walk
    SET (what the T-9375 interactive walk consumes) + the human doc-checklist. No new engine/store/parser/
    journal (CHARTER §P1): reuses the floor-trigger-map render+drift pattern. Pure helper → shared by both
    build sites (the `_write_graph_index` write + the `_activation_checklist_drift` freshness check), so the
    committed file and a fresh render stay byte-equal (the drift invariant). Table cells escape `|`."""
    rows = _activation_concern_rows(specs)
    lines = [
        "<!-- GENERATED by `bin/yitc-v2 graph build` from each concern spec's `init_concern` field",
        "     (SPEC-0096; field schema SPEC-0030). DO NOT EDIT — hand edits are overwritten on the next",
        "     build, and a divergent committed copy is flagged by `graph conformance`",
        "     (activation-checklist-drift). Single canonical source: the `init_concern` declaration on",
        "     each concern's own spec; this is a derived-only view of those declarations. -->",
        "",
        "# Activation baseline-concern checklist (generated)",
        "",
        "When a project is activated onto the kernel it is walked through the baseline concerns below —",
        "one row per concern whose spec DECLARED an `init_question` — forcing declare-or-waive on each",
        "(opt-out always available). Both views derive from the SAME declarations, so a new concern spec",
        "that declares its `init_question` AUTO-APPEARS here with no hand edit (SPEC-0096).",
        "",
        "## Init-walk SET",
        "",
        "The machine set the interactive `init` walk (T-9375) presents — one concern row per declared",
        "concern, keyed by spec id so the walk can resolve each. T-9375 owns the walk; this is only the SET.",
        "",
    ]
    if rows:
        for sid, q, _w, _e, tier in rows:
            lines.append(f"- **{sid}** (`{tier}`) → {q}")
    else:
        lines.append("- (no concern has declared an `init_question` yet — see SPEC-0096)")
    lines += [
        "",
        "## Doc-checklist",
        "",
        "The human-readable companion — each concern's prompt, what a bare waiver may omit, the governed",
        "adoption-evidence pointer that proves it handled, and its tier.",
        "",
    ]
    if rows:
        lines += ["| concern | tier | init_question | waiver-contract | adoption-evidence |",
                  "|---|---|---|---|---|"]
        for sid, q, w, e, tier in rows:
            cells = [c.replace("|", "\\|") for c in (sid, tier, q, w, e)]
            lines.append("| " + " | ".join(cells) + " |")
    else:
        lines.append("(no declared concerns yet)")
    lines.append("")
    return "\n".join(lines)


def _activation_checklist_drift(specs: dict, *, GRAPH_PATH, _render_activation_checklist) -> list:
    """T-9410 (SPEC-0096 guard b) — the committed graph/activation-checklist.md MUST equal a fresh render
    over the live `init_concern` declarations (the analog of `_floor_map_drift` for the floor map). A
    mismatch = `activation-checklist-drift`: a hand edit to the generated artifact, or a committed copy gone
    stale relative to the declarations. Returns [] or a single {kind, detail}. REPORT-ONLY (its caller adds
    it to the conformance RED set; not a build gate). Identity-agnostic — no kernel/consumer header variance
    (unlike the floor map), so a single render compares for every checkout."""
    expected = _render_activation_checklist(specs or {})
    acpath = GRAPH_PATH.parent / "activation-checklist.md"
    actual = acpath.read_text(encoding="utf-8") if acpath.exists() else ""
    if expected != actual:
        return [{"kind": "activation-checklist-drift",
                 "detail": "committed graph/activation-checklist.md != the regenerated checklist "
                           "(run `yitc-v2 graph build` to refresh the derived activation checklist)"}]
    return []


# ── T-10036 (SPEC-0128): the seed-and-grow CONCERN REGISTRY — one authoritative `concern:` block per ──
# concern; graph/concern-registry.json DERIVED from every block (the init_concern → activation-checklist
# derivation model, applied to a machine registry the generated carrier sweep (legs B/C) CONSUMES).
_CONCERN_REGISTRY_FIELDS = ("section", "carrier_path", "presence_policy", "update_policy",
                            "declare_key", "declare_type", "waiver_policy")

# ── T-10170 (SPEC-0143 / SPEC-0128 registry extension): the FINITE metadata table a per-concern `version`
# hashes over — the CONTRACT surface a consumer pins (section/carrier_path/presence_policy/declare_key/
# declare_type/update_policy/waiver_policy/shape_hook/spec). DELIBERATELY EXCLUDES the `born` guidance block
# (a trial finding — born is PROSE; hashing it would bump every consumer's adopted version on a whitespace/
# wording edit that never changed the contract) AND `authoring_floor` (a floor-map derivation, not the carrier
# contract). Version = a short content-hash of THIS set only, so a version bump means the pinned contract
# moved (SPEC-0143's propagation-detection signal). Kept in tuple-sorted order for a stable canonical hash.
_CONCERN_VERSION_FIELDS = ("carrier_path", "declare_key", "declare_type", "presence_policy",
                           "section", "shape_hook", "spec", "update_policy", "waiver_policy")

# T-11968 (SPEC-0189 rule 8): the CLOSED born-stance vocabulary. Two words, because rule 8 fixes the
# axis as the value's DIRECTION (relaxing vs protective) and is blind to which gate is relaxed.
#
# NEITHER `born_stance` NOR `detector` IS A VERSION FIELD, and the omission is deliberate rather than an
# oversight to be "fixed" later. `_CONCERN_VERSION_FIELDS` hashes the CARRIER CONTRACT a consumer pins
# (SPEC-0143's propagation signal); which detector watches a concern is KERNEL-SIDE review machinery and
# moves no key, type or stance in any consumer's `yitc-ops.yaml`. Hashing it would bump every consumer's
# adopted version for a change that never touched their contract — the same trial finding that already
# keeps `born` (prose) and `gated_capabilities` (guidance) out of this tuple.
_CONCERN_BORN_STANCES = frozenset({"permissive", "protective"})


def _concern_version(entry: dict) -> str:
    """T-10170 (SPEC-0143, a SPEC-0128 registry-derivation extension): the per-concern `version` — a short
    content-hash over the FINITE metadata table ONLY (`_CONCERN_VERSION_FIELDS`), so a consumer can detect
    that the concern's CONTRACT moved without diffing the whole registry. Pure f(entry): reads only the
    finite fields off the already-built roster entry (a metadata key absent in the block is carried as None —
    hashed as null, so adding/removing a field changes the version deterministically). EXCLUDES `born`
    (prose — a born-only edit MUST NOT bump the version; trial finding) and `authoring_floor`. Canonical =
    json.dumps(sort_keys) over the fixed subset → sha256 → first 12 hex chars (short, collision-safe for the
    O(10) concern roster). Deterministic across checkouts (no host state), so the committed registry and a
    fresh render stay byte-equal (the drift invariant)."""
    material = {k: entry.get(k) for k in _CONCERN_VERSION_FIELDS}
    canonical = json.dumps(material, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]


def _concern_raw_blocks(raw) -> list:
    """Normalize a spec's raw `concern:` field to a LIST of candidate blocks (T-10041, SPEC-0128 Rule 1
    multi-block): None → [] (unset); a single mapping → [mapping]; a list → itself. This only normalizes the
    CONTAINER shape — element validity (mapping-ness, a non-empty `section`) is decided by the caller. So
    `_concern_registry_entries` (which KEEPS the valid blocks) and `_concern_malformed_violations` (which
    FLAGS the rejected ones) share ONE normalization and cannot diverge (P5). A spec MAY host MORE THAN ONE
    concern (the deploy family — deploy/rollback/live_probe — on SPEC-0094; ui/tests/verify on SPEC-0093);
    "declared EXACTLY ONCE" binds the CONCERN, not the spec."""
    if raw is None:
        return []
    return list(raw) if isinstance(raw, list) else [raw]


def _active_concern_blocks(specs: dict):
    """Yield (sid, block) for candidate concern blocks whose spec is LIVE — active-only for every real spec
    (T-10175, SPEC-0128 Rule 2). A concern goes LIVE in the derived surfaces (registry / born-ops /
    authoring-floors / surface-warnings) only at spec ACTIVATION: a `draft`/`proposed` spec is
    non-authoritative and `superseded`/`retired` is history (SPEC-0005 §4 — "active is the only normative
    status"), so a non-active spec's concern must NOT ship to consumers (born-ops) nor enter the pinned
    registry set. This mirrors `graph query --projected`, which already excludes drafts. The registry roster
    AND the born roster share THIS one status+normalization gate so they cannot diverge (P5) — the same
    reason they already share `_concern_raw_blocks`. GATE: skip a spec whose status is EXPLICITLY non-active;
    a status-LESS spec is treated as includable — a REAL spec always carries a status (scaffolded by
    `spec new`), so this only ever admits the status-omitting SYNTHETIC fixtures the registry-mechanics
    tests use, keeping them status-agnostic while production stays active-only. (NOTE:
    `_concern_malformed_violations` deliberately does NOT use this gate — a mis-formatted concern is a FORMAT
    fault flagged regardless of the owning spec's status.)"""
    for sid in specs:
        status = (specs.get(sid) or {}).get("status")
        if status is not None and status != "active":
            continue
        for c in _concern_raw_blocks((specs.get(sid) or {}).get("concern")):
            yield sid, c


def _concern_registry_entries(specs: dict) -> list:
    """The derived concern-registry roster (T-10036/T-10041, SPEC-0128 Rule 1): the WELL-FORMED `concern:`
    declarations across all status:active specs (T-10175 — draft/proposed concerns are non-authoritative and
    excluded until activation) — ONE spec may declare ONE block (a mapping) OR SEVERAL (a list of
    mappings, T-10041) — sorted by (section, spec id) for deterministic output. FAIL-CLOSED (the init_concern
    precedent): a block is registered ONLY when it is a MAPPING carrying a non-empty `section` string — a
    non-mapping value/element, or a missing/empty `section`, is SKIPPED here (never crashes, never
    half-registers), so it lands in NEITHER the registry NOR the surface/hook checks. That skip is made LOUD
    by `_concern_malformed_violations` (a conformance RED), so a typo'd declaration cannot silently vanish.
    Each entry is normalized to the FINITE metadata table (SPEC-0030 schema — no shape-DSL, Rule 5): the kept
    keys are a fixed set; string values are stripped; a metadata key absent in the block is carried as None
    (documentary — the sweep (leg B) validates required-ness). `shape_hook` is carried ONLY when a non-empty
    string. Pure helper shared by the render + the surface/hook checks so they cannot diverge (P5)."""
    entries: list = []
    for sid, c in _active_concern_blocks(specs):
        if not isinstance(c, dict):
            continue
        section = c.get("section")
        if not isinstance(section, str) or not section.strip():
            continue
        entry = {"spec": sid}
        for k in _CONCERN_REGISTRY_FIELDS:
            v = c.get(k)
            entry[k] = v.strip() if isinstance(v, str) else v
        hook = c.get("shape_hook")
        if isinstance(hook, str) and hook.strip():
            entry["shape_hook"] = hook.strip()
        # T-10032 (SPEC-0128 Rule 2 — the registry-DERIVED before-authoring-<concern> floor family):
        # carry an OPTIONAL `authoring_floor:` mapping ONLY when it is well-formed — a mapping naming a
        # non-empty `trigger` string. Same special-carry shape as `shape_hook`; a malformed value is
        # SKIPPED here (fail-closed, never half-registers a floor row), consumed by _concern_authoring_floors.
        af = c.get("authoring_floor")
        if isinstance(af, dict) and isinstance(af.get("trigger"), str) and af["trigger"].strip():
            entry["authoring_floor"] = af
        # T-11366 (SPEC-0128 Rule 2 — the declaration-gated capability disclosure): carry the
        # well-formed `gated_capabilities:` so the registry names, machine-readably, which OPT-IN keys
        # each concern gates a kernel capability on. Same special-carry shape as `authoring_floor`, and
        # like it EXCLUDED from the `version` hash below — the disclosure is guidance PROSE about a
        # capability, not the carrier CONTRACT a consumer pins, and a wording edit must not bump every
        # consumer's adopted version (the same trial finding that keeps `born` out of the hash).
        caps = _gated_capability_entries(c)
        if caps:
            entry["gated_capabilities"] = caps
        # T-11968 (SPEC-0189 rule 1 / SPEC-0128 Rule 2 — the born-permissive DECLARATION surface): carry
        # the OPTIONAL pair by which a concern declares that its born value is PERMISSIVE and NAMES the
        # detector watching for that absence starting to cost something. Same special-carry shape as
        # `authoring_floor` / `gated_capabilities` — kept ONLY when well-formed, so a typo'd value is
        # SKIPPED rather than half-registered, and the guard downstream then reads the concern as having
        # declared NO stance (fail-closed in the direction that refuses, never in the one that admits an
        # unwatched permissive default).
        #
        # `born_stance` is a CLOSED two-value vocabulary on purpose. SPEC-0189 rule 8 fixes the axis as
        # the VALUE'S DIRECTION — relaxing vs protective — and is explicitly blind to WHICH gate is being
        # relaxed, so the field needs exactly two words and no language. Anything else is not a third
        # stance, it is a mistake, and it does not register.
        stance = c.get("born_stance")
        if isinstance(stance, str) and stance.strip() in _CONCERN_BORN_STANCES:
            entry["born_stance"] = stance.strip()
        det = c.get("detector")
        if isinstance(det, str) and det.strip():
            entry["detector"] = det.strip()
        # T-10170 (SPEC-0143 / SPEC-0128 registry extension): derive the per-concern `version` — a short
        # content-hash of the FINITE metadata table ONLY (born EXCLUDED). Computed AFTER `shape_hook` is
        # carried (it is a version field) and independently of `authoring_floor` (NOT a version field), so
        # the hash captures exactly the pinned CONTRACT surface. Additive key on the derived entry.
        entry["version"] = _concern_version(entry)
        entries.append(entry)
    entries.sort(key=lambda e: (str(e.get("section") or ""), str(e.get("spec") or "")))
    return entries


def _concern_authoring_floors(specs: dict) -> list:
    """T-10032 (SPEC-0128 Rule 2) — the registry-DERIVED `before-authoring-<concern>` floor-trigger FAMILY.
    A concern block that declares a well-formed `authoring_floor: {trigger, specs}` contributes ONE
    at-the-moment floor-trigger row surfacing the named delivery spec(s) when a project is about to author
    that concern's surface (e.g. the `ui` concern → `before-authoring-UI` → SPEC-0100). Derived-ONLY from
    the concern registry — NO hand-added FLOOR_TRIGGERS row — generalizing the hand-listed
    before-authoring-interaction into a self-replenishing family (SPEC-0128 Rule 3: adding a concern with an
    authoring_floor is ONE governed declaration).

    Returns a sorted list of (trigger, [spec_ids]). FAIL-CLOSED (the _concern_registry_entries precedent):
    the entry-side carry already dropped a non-mapping / trigger-less authoring_floor; here `specs` is kept
    ONLY as its well-formed non-empty stripped-str members, and a trigger left with NO valid delivery spec is
    dropped (a floor row that surfaces nothing is worse than no row). If two concern blocks declare the SAME
    trigger, their spec sets UNION (deterministic), so the family cannot half-register. Pure f(specs)."""
    floors: dict = {}
    for e in _concern_registry_entries(specs):          # already fail-closed + sorted
        af = e.get("authoring_floor")
        if not isinstance(af, dict):
            continue
        trig = af.get("trigger")
        if not (isinstance(trig, str) and trig.strip()):
            continue
        sids = [s.strip() for s in (af.get("specs") or []) if isinstance(s, str) and s.strip()]
        if not sids:
            continue
        floors.setdefault(trig.strip(), set()).update(sids)
    return [(trig, sorted(floors[trig])) for trig in sorted(floors)]


def _concern_malformed_violations(specs: dict) -> list:
    """T-10041 (SPEC-0128 Rule 1, audit-pre finding) — a present-but-MALFORMED `concern:` declaration is a
    conformance RED, so a typo'd concern cannot silently drop out of the registry (GAP A2 — the exact
    silently-missing-concern failure this plan exists to kill). Over the SAME `_concern_raw_blocks`
    normalization the roster uses (single-source, P5), a `concern:` that is present (non-None) but is NOT a
    mapping / list-of-mappings, has a non-mapping LIST ELEMENT, or has a block MISSING a non-empty `section`,
    yields a `concern-malformed` viol naming the owning spec id. Absent `concern:` (None) → [] (valid —
    unset); an empty list → [] (no concerns, valid). Returns a list of {kind, detail}. This is the
    STORAGE-FORMAT contract-check class GRAPH explicitly permits (the scenario-status carve-out — "a
    malformed field, like the YAML-parse fail-closed"), NOT a semantic/legality validation layer; its caller
    (cmd_graph_conformance) adds it to the conformance RED set beside `_concern_registry_drift`. Pure over
    `specs` — no host state, so called directly (not injected)."""
    viols: list = []
    for sid in specs:
        raw = (specs.get(sid) or {}).get("concern")
        if raw is None:
            continue
        listed = isinstance(raw, list)
        for i, c in enumerate(_concern_raw_blocks(raw)):
            if not isinstance(c, dict):
                where = f"list element {i}" if listed else f"value (type {type(raw).__name__})"
                viols.append({"kind": "concern-malformed",
                              "detail": f"{sid}: `concern:` {where} is not a mapping — a concern block must "
                                        f"be a mapping with a non-empty `section` (SPEC-0128 Rule 1 / SPEC-0030)"})
                continue
            section = c.get("section")
            if not isinstance(section, str) or not section.strip():
                where = f"list element {i}" if listed else "block"
                viols.append({"kind": "concern-malformed",
                              "detail": f"{sid}: `concern:` {where} is missing a non-empty `section` "
                                        f"(SPEC-0128 Rule 1 / SPEC-0030)"})
    return viols


def _render_concern_registry(specs: dict) -> str:
    """Render graph/concern-registry.json (T-10036, SPEC-0128 Rule 2) — the DERIVED, machine-readable
    concern registry the generated carrier sweep (legs B/C) CONSUMES. A GENERATED, derived-only committed
    artifact — the JSON sibling of graph/activation-checklist.md: regenerated every `graph build` from each
    concern spec's `concern:` block. Deterministic (sorted entries + sort_keys) so the committed file and a
    fresh render stay byte-equal (the drift invariant). The consumer iterates `concerns` — the KERNEL-KNOWN
    set — and IGNORES a project's own extra/unknown carrier sections (the hard non-whitelist invariant: the
    registry is the kernel-known concern set, NEVER a closed whitelist). JSON serialization mirrors
    graph/index.json (json.dumps sort_keys/indent=1) — a derived committed view, not authored YAML (P5)."""
    payload = {"concerns": _concern_registry_entries(specs)}
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, indent=1) + "\n"


def _concern_registry_drift(specs: dict, *, GRAPH_PATH, _render_concern_registry) -> list:
    """T-10036 (SPEC-0128) — the committed graph/concern-registry.json MUST equal a fresh render over the
    live `concern:` declarations (the analog of `_activation_checklist_drift` for the concern registry). A
    mismatch = `concern-registry-drift`: a hand edit to the generated artifact, or a committed copy gone
    stale relative to the declarations. Returns [] or a single {kind, detail}. REPORT-ONLY (its caller adds
    it to the conformance RED set; not a build gate). Identity-agnostic — a single render compares for every
    checkout. This IS the P8 adoption probe for leg [A]: the derived registry is consumed by its own drift
    check (CHARTER §Principle 8 — a live consumer read of the new artifact)."""
    expected = _render_concern_registry(specs or {})
    crpath = GRAPH_PATH.parent / "concern-registry.json"
    actual = crpath.read_text(encoding="utf-8") if crpath.exists() else ""
    if expected != actual:
        return [{"kind": "concern-registry-drift",
                 "detail": "committed graph/concern-registry.json != the regenerated registry "
                           "(run `yitc-v2 graph build` to refresh the derived concern registry)"}]
    return []


# ── T-10038 (SPEC-0128 Rule 2 + born decision (i)): the born yitc-ops.yaml TEMPLATE — GENERATED from ──
# each concern's `born:` + `born_order:` companion (the per-section born-guidance PROSE relocated onto each
# concern's OWN governing spec — decisions/T-10029-audit-adhoc.yaml born decision (i)). RENDER-ONLY concat
# (no shape-DSL): the file-level preamble + each concern's VERBATIM born block, ordered by `born_order`.
# Retires the `_BORN_OPS_YAML` per-SECTION literals in bin/lib/init.py (SPEC-0128 Rule 2); init reads the
# generated graph/born-ops.yaml (the concern-registry.json precedent). The FILE HEADER below is the
# file-level preamble (a template constant, NOT a per-section literal — SPEC-0128 retires the per-SECTION
# literals only).
# T-10569 — the born template's COMPLETENESS SENTINEL (see `_render_born_ops`). A YAML comment, so it is
# inert to every parse; its ONLY job is to be absent from a truncated read. Its twin literal lives in
# bin/lib/init.py (`BORN_OPS_TERMINATOR`) because init.py back-imports NOTHING by design — the same
# cross-module-literal shape as `BORN_WAIVER_MARKER`, and pinned the same way by a coherence probe
# (tests/test_t10569_derived_read_race.py#P7d) that fails the moment the two drift apart.
_BORN_OPS_TERMINATOR = "# ── END born-ops template (generated completeness sentinel — T-10569) ──\n"

_BORN_OPS_HEADER = """\
# yitc-ops.yaml — this project's cross-cutting OPS contract carrier (SPEC-0093).
# ONE file, one top-level SECTION per concern. Each section is DECLARE-OR-WAIVE, fail-closed:
# either its section-appropriate declaration OR `waiver: { reason: <text> }`. A seeded section left
# UNANSWERED (neither) is an init/sweep ERROR — never a silent skip. The kernel owns each section's
# SHAPE; this project owns the VALUES. The carrier stores DECLARED config only, never a computed status.
#
# Slice-1 LIVE sections (read by the `deploy` verb, SPEC-0094):
#   deploy:     command: <cmd to deploy this project>     | waiver: {reason: <why>}
#     ↳ if `command:` is a hand-runnable deploy.sh, EMBED the governed-deploy guard at its TOP so a raw
#       hand-run is REFUSED (it would skip the class-gate, the Class-C1 pg_dump + deploy_completed — SPEC-0094 §1).
#       Get the exact snippet: `__YITC_CLI__ deploy --print-guard`.
#   rollback:   command: <cmd to roll back a deploy>       | waiver: {reason: <why>}
#   live_probe: live_base_url: <url> + dialect             | waiver: {reason: <why>}
# (The per-CHANGE probe assertion lives on the task YAML, not here.)
#
# deploy.policy SUBFIELD (SPEC-0097) — the deploy-AUTONOMY stance (the WHEN of the deploy concern, so a
# SUBFIELD of deploy:, NOT a new top-level section — SPEC-0093 rule 1 honored). Declare-or-waive, fail-
# closed BOTH ways: declare `classes:` (the per-class commands/thresholds that opt INTO autonomous
# deploys; the kernel owns the A/S/C1/C2 vocabulary, this project owns the VALUES) OR `waiver: {reason}`
# (owner-gated every deploy, the pre-policy default — NO autonomous path). Born WAIVED. The deploy-verb
# gate that READS this stance is wired separately (SPEC-0097 §5, its own task) — the carrier only seeds
# + sweeps the stance, fail-closed.
#
# security: SECTION (SPEC-0093 rule 8, pairs with the contract SPEC-0098) — the project's security
# live-probes (named read-only property assertions a Class-S deploy binds). DECLARE a `probes:` list
# (each entry: property + assertion + url) OR WAIVE. The security waiver is STRICT (rule 6 instance, NOT
# a bare reason): it REQUIRES reason + compensating_control + a real-ISO-date expiry — fail-closed. Born
# WAIVED with the kernel's always-on security baseline as the compensating control + a placeholder review
# date the owner replaces. `probes:`+`waiver:` together is a contradiction (ERROR). The live-probe
# SEMANTICS + events are owned by SPEC-0098 — this carrier owns only the section SHAPE.
#
# ui: SECTION (SPEC-0093 rule 9, X-0050) — the project's UI baseline: DECLARE `baseline: <design-system>`
# (+ optional styleguide/tokens/lint/archetype) OR WAIVE (a LOOSE bare reason — a no-UI project). Pure
# declared config (rule 7), no paired contract spec.
# tests: SECTION (SPEC-0093 rule 10, X-0053) — the project's test class×moment TAXONOMY: DECLARE a
# `classes:` list (each {class, moment}, optional command) OR WAIVE (a LOOSE bare reason). It is the
# taxonomy INVENTORY, NOT the land-verify gate — verify is single-home in the carrier `verify.layers`
# (rule 5/16). `baseline:`/`classes:` + `waiver:` together is a contradiction (ERROR).
# startup_checks: SECTION (SPEC-0152 rule 17, X-0191) — OPTIONAL, report-only project startup checks.
# DECLARE a `startup_checks:` list, each entry { label, command, detail }: `command` runs cheaply at
# each session-start / land seam and a NON-ZERO exit means the check FLAGS (something to look at); the
# declared checks are AGGREGATED into ONE report-only line (count + `label (detail)`), appended to the
# SPEC-0119 debt echo — SUPPRESSED-WHEN-CLEAN, never a gate. OPT-IN like the `extensions`/`coverage`
# sections: ABSENT = no checks (NOT swept, never fail-closed). See the commented example at file end.

"""


# ── T-11366 (SPEC-0128 Rule 2 — the DECLARATION-GATED CAPABILITY disclosure) ─────────────────────
# A kernel capability that is gated on a PROJECT DECLARATION is off, for every project that was never
# told the key exists — off by IGNORANCE, not by the decision the declare-or-waive model assumes was
# made. `combined_candidate_safe` (SPEC-0152, land-verify batching) lived in exactly two places, the
# kernel source and its defining spec's body, and NEITHER is a surface a consumer reads: kupiclub
# formed 154 land batches of ONE, every row stamped `engagement: project-authored-verify-undeclared`.
# So the key names itself HERE, on the born carrier the project actually opens — and it does so from
# the SAME `concern:` declaration every other born surface is generated from, because a second
# hand-maintained list of keys would become the next thing nobody maintains (CHARTER §P1 F3).
_GATED_CAP_MARKER = "# ── declaration-gated capabilities (generated from the concern registry) ──"

# The stanza's fixed preamble — the CONTRACT of a commented key, stated once per section rather than
# re-argued per capability. Deliberately carries NO `SPEC-NNNN rule N` citation: `_born_comment_anchors`
# (bin/lib/init.py) derives the carrier comment-contract anchors from exactly that form, so a citation
# here would mint a new REQUIRED anchor that every already-init'd consumer's carrier lacks — turning a
# report-only contract view RED for the whole fleet on a disclosure edit. Each capability names its
# OWNING SPEC in the bare `SPEC-NNNN` form instead, which the anchor scanner does not read.
_GATED_CAP_PREAMBLE = (
    "An OPT-IN key this section gates a kernel capability on. ABSENT is the fail-closed default, so",
    "nothing below is engaged until you write it in — and leaving it commented is a legitimate answer,",
    "as long as it is a KNOWING one. Uncomment and answer to make the choice; the kernel never infers it.",
)


def _gated_capability_entries(block) -> list:
    """The WELL-FORMED `gated_capabilities:` entries of one concern block (T-11366, SPEC-0128 Rule 2).

    A concern MAY carry `gated_capabilities:` — a list of {key, example, summary, absent, spec} naming
    the OPT-IN keys its carrier section gates a kernel capability on. This is the SINGLE declaration
    (Rule 1); the born stanza, the registry entry and the update-path delivery are all generated from
    it, so the NEXT declaration-gated key discloses itself by construction rather than by an author
    remembering a second list.

    FAIL-CLOSED, the `authoring_floor` precedent: a non-list value, a non-mapping element, or an element
    with no non-empty `key` string is SKIPPED — it never half-registers a capability. String fields are
    stripped; `example` defaults to `true` (the boolean that engages every capability of this shape so
    far, and the value a reader is being invited to uncomment). Pure over the block."""
    raw = (block or {}).get("gated_capabilities")
    if not isinstance(raw, list):
        return []
    out: list = []
    for cap in raw:
        if not isinstance(cap, dict):
            continue
        key = cap.get("key")
        if not (isinstance(key, str) and key.strip()):
            continue
        norm = {"key": key.strip()}
        for f in ("example", "summary", "absent", "spec"):
            v = cap.get(f)
            if isinstance(v, str) and v.strip():
                norm[f] = " ".join(v.split())
        norm.setdefault("example", "true")
        out.append(norm)
    return out


def _gated_capability_disclosure(caps: list, indent: str) -> str:
    """Render the UNIFORM commented disclosure stanza for one concern's gated capabilities (T-11366).

    COMMENT-ONLY BY CONSTRUCTION — every emitted line is a `#` comment, which is what makes the
    disclosure's safety fence structural rather than tested-for: a commented key parses to ABSENT, and
    ABSENT is the state every reader of these keys already fails closed on. The disclosure therefore
    cannot change what any capability does, on a born carrier or on an existing one.

    Deterministic: fixed marker + fixed preamble + one wrapped block per capability in DECLARED order.
    `indent` places the stanza inside its section (2 spaces per carrier-path level), so a nested
    concern's stanza stays within its parent block — the same reason nested `born:` text is stored
    indented (born decision (i): the render is a concat, never a shape reconstruction)."""
    import textwrap

    def _wrap(text: str, lead: str, hang: str) -> list:
        return textwrap.wrap(text, width=max(40, 100 - len(indent)),
                             initial_indent=indent + lead, subsequent_indent=indent + hang) or []

    lines = [indent + _GATED_CAP_MARKER]
    for ln in _GATED_CAP_PREAMBLE:
        lines.append(indent + "# " + ln)
    for cap in caps:
        lines.append(indent + "#")
        owner = f"   # ({cap['spec']})" if cap.get("spec") else ""
        lines.append(f"{indent}# {cap['key']}: {cap['example']}{owner}")
        if cap.get("summary"):
            lines.extend(_wrap(cap["summary"], "#   turns on: ", "#     "))
        if cap.get("absent"):
            lines.extend(_wrap(cap["absent"], "#   while absent: ", "#     "))
    return "\n".join(lines) + "\n"


def _concern_born_entries(specs: dict) -> list:
    """The born-rendering roster (T-10038): (born_order, section, born_text) for every concern block that
    carries a non-empty `born:` string, sorted by `born_order` (missing → last, then section). Over the SAME
    `_concern_raw_blocks` normalization the registry roster uses (single-source, P5) — so a concern renders a
    born block iff it is a well-formed registered concern WITH a born companion (a concern missing its born
    renders nothing → caught by the surface check). Over status:active specs ONLY (T-10175 — via the shared
    `_active_concern_blocks` gate the registry roster uses, so registry + born cannot diverge, P5). Pure over
    `specs` (the graph index nodes' `concern` field — NOT a second specs/*.yaml scan)."""
    entries: list = []
    for sid, c in _active_concern_blocks(specs):
        if not isinstance(c, dict):
            continue
        born = c.get("born")
        if not isinstance(born, str) or born == "":
            continue
        order = c.get("born_order")
        section = str(c.get("section") or "")
        # T-11366: the DERIVED declaration-gated-capability stanza rides on this concern's OWN born
        # block — one section, one place a reader meets both the guidance and the keys it gates. It is
        # APPENDED (never woven in), because the born block is stored VERBATIM (born decision (i): a
        # render-only concat, no shape-DSL), and it is indented to the concern's carrier depth so a
        # nested concern's stanza stays inside its parent's block.
        caps = _gated_capability_entries(c)
        if caps:
            cp = c.get("carrier_path")
            depth = (str(cp).count(".") + 1) if isinstance(cp, str) and cp.strip() else 1
            born = born + ("" if born.endswith("\n") else "\n") + _gated_capability_disclosure(caps, "  " * depth)
        entries.append((order if isinstance(order, int) else 10 ** 9, section, born))
    entries.sort(key=lambda e: (e[0], e[1]))
    return entries


def _render_born_ops(specs: dict) -> str:
    """Render graph/born-ops.yaml (T-10038, SPEC-0128 Rule 2) — the DERIVED born ops-contract carrier
    TEMPLATE init seeds/updates from. GENERATED every `graph build` from each concern's `born:`/`born_order:`
    companion: the file-level preamble + each concern's VERBATIM born block in `born_order`. Deterministic
    (sorted) so the committed file and a fresh render stay byte-equal (the drift invariant). RENDER-ONLY — a
    pure concat, no shape reconstruction (born decision (i): no shape-DSL). The born sibling of
    `_render_concern_registry`.

    T-10569: the render ENDS with `_BORN_OPS_TERMINATOR`, the COMPLETENESS SENTINEL init's reader checks.
    It exists because YAML gives this artifact no self-evident completeness signal the way JSON gives the
    concern registry one: a truncated prefix of the registry's JSON fails to parse, but a truncated prefix
    of this YAML mapping still parses as a perfectly valid (merely smaller) dict — so a partial read from a
    concurrent git materialization would be indistinguishable from a complete one and init would seed the
    truncated template. A terminator cannot survive truncation, so `endswith` decides completeness exactly.
    The sentinel is a YAML COMMENT: inert to every parse of the seeded carrier."""
    return (_BORN_OPS_HEADER + "".join(e[2] for e in _concern_born_entries(specs))
            + _BORN_OPS_TERMINATOR)


def _born_ops_drift(specs: dict, *, GRAPH_PATH) -> list:
    """T-10038 (SPEC-0128) — the committed graph/born-ops.yaml MUST equal a fresh render over the live
    concern `born:` declarations (the born sibling of `_concern_registry_drift`). A mismatch = `born-ops-drift`:
    a hand edit to the generated template, or a committed copy gone stale relative to the born declarations.
    Returns [] or a single {kind, detail}. REPORT-ONLY (its caller adds it to the conformance RED set).
    Identity-agnostic. This IS the P8 adoption probe for leg [C]: the derived born template is consumed by
    its own drift check + by init (`_born_ops_template`)."""
    expected = _render_born_ops(specs or {})
    bpath = GRAPH_PATH.parent / "born-ops.yaml"
    actual = bpath.read_text(encoding="utf-8") if bpath.exists() else ""
    if expected != actual:
        return [{"kind": "born-ops-drift",
                 "detail": "committed graph/born-ops.yaml != the regenerated born template "
                           "(run `yitc-v2 graph build` to refresh the derived born carrier)"}]
    return []


def _concern_surface_warnings(specs: dict, *, surface_sections, available_hooks,
                             orphan_exempt_hooks=None) -> list:
    """T-10036 (SPEC-0128 Rule 2 + decisions/T-10029-audit-adhoc.yaml constraint 3) — the REPORT-ONLY
    registry↔surface + hook consistency checks over the derived concern registry. Returns a list of
    {kind, detail} warnings; NEVER an exit gate (GRAPH «not a validation layer» — the caller prints them on
    the exit-0 stderr channel, like the coverage warnings). Two families:

      • registry↔surface inconsistency — iterate the KERNEL-KNOWN registry entries ONLY (never the surface's
        own sections): a concern whose carrier section (the `carrier_path` root, else `section`) is ABSENT
        from the ops-carrier surface universe is a `concern-surface-inconsistency`. Registry→surface
        direction ONLY — the hard non-whitelist invariant (owner constraint): the registry is the
        kernel-known set, never a closed whitelist, so a project's extra/unknown surface section is IGNORED
        here, never flagged. (The reverse surface→registry direction becomes meaningful only once EVERY
        concern is migrated into the registry — legs B/C/D; leg A never flags a not-yet-migrated surface.)

      • hook consistency (constraint 3 — the hook must not become a SECOND registry): the `concern:` block is
        the SOLE owner of concern↔hook membership. A `shape_hook` NAMED by a concern but ABSENT from the
        kernel's implemented deep-shape validators → `concern-hook-missing`; a hook referenced by ≥2 concern
        blocks → `concern-hook-duplicate` (each hook from EXACTLY ONE concern, SPEC-0128 Rule 2); an
        implemented kernel hook that NO concern block references → `concern-hook-orphan`.

    `surface_sections` (the ops-carrier section universe), `available_hooks` (the implemented deep-shape
    validator names) and `orphan_exempt_hooks` are INJECTED by the host composition-root — this pure core
    reads neither init.py nor the corpus.

    `orphan_exempt_hooks` (T-11767, answering X-1184) bounds the ORPHAN family ONLY: it names the hooks
    whose orphan status THIS repo cannot act on. The implemented validators are KERNEL-owned code, and
    the concern blocks that name them live in the KERNEL's corpus — so in a CONSUMER build every
    implemented hook is unreferenced by construction, and each row is a finding nobody there can act on
    (measured: 17 permanent rows in aiseller, 0 in the kernel's own build). The host passes the kernel
    hook set on a consumer build and an EMPTY set on the engine's own build, so the OWNER's view is
    unmoved. The exemption is keyed on the HOOK, never on the build being a consumer: a consumer concern
    block that DOES name a kernel hook still lands in `hook_refs` (so it was never an orphan) and still
    earns its missing / duplicate verdict. The missing / duplicate / surface / gated-capability families
    are untouched. In leg [A] the real corpus registry is empty AND `available_hooks` is empty, so this is
    silent on the real build; it fires on the synthetic fixtures (acceptance) and on real drift once
    concerns migrate."""
    warns: list = []
    entries = _concern_registry_entries(specs)
    surface = set(surface_sections or ())
    for e in entries:
        cp = e.get("carrier_path")
        root = (str(cp).split(".", 1)[0] if isinstance(cp, str) and cp.strip() else "") or e.get("section")
        if isinstance(root, str) and root.strip() and root not in surface:
            warns.append({"kind": "concern-surface-inconsistency",
                          "detail": f"{e['spec']}: concern carrier section {root!r} (carrier_path "
                                    f"{e.get('carrier_path')!r}) is not present in the ops-carrier surface"})
    # T-11366 — the DISCLOSURE half of the registry↔surface family: a concern that declares a
    # declaration-gated capability but renders NO born block has nowhere to disclose it, so the key
    # would be registered and still invisible to every project — the exact half-registered state this
    # rule exists to make impossible. Report-only, like its siblings.
    born_sections = {sec for _, sec, _ in _concern_born_entries(specs)}
    for e in entries:
        caps = e.get("gated_capabilities")
        if not caps:
            continue
        if str(e.get("section") or "") not in born_sections:
            warns.append({"kind": "concern-gated-capability-undisclosed",
                          "detail": f"{e['spec']}: concern {e.get('section')!r} declares gated "
                                    f"capabilit{'y' if len(caps) == 1 else 'ies'} "
                                    f"{', '.join(repr(c['key']) for c in caps)} but renders NO born "
                                    f"block — the key has no project-facing surface to be disclosed on "
                                    f"(SPEC-0128 Rule 2)"})
    hook_refs: dict = {}
    for e in entries:
        h = e.get("shape_hook")
        if isinstance(h, str) and h.strip():
            hook_refs.setdefault(h, []).append(e["spec"])
    avail = set(available_hooks or ())
    for h in sorted(hook_refs):
        refs = sorted(hook_refs[h])
        if h not in avail:
            warns.append({"kind": "concern-hook-missing",
                          "detail": f"{', '.join(refs)}: names shape_hook {h!r} with no implemented "
                                    f"kernel deep-shape validator"})
        if len(refs) > 1:
            warns.append({"kind": "concern-hook-duplicate",
                          "detail": f"shape_hook {h!r} is referenced by {len(refs)} concern blocks "
                                    f"({', '.join(refs)}) — each hook must be referenced from EXACTLY ONE "
                                    f"concern block (SPEC-0128 Rule 2)"})
    for h in sorted(avail - set(hook_refs) - set(orphan_exempt_hooks or ())):
        warns.append({"kind": "concern-hook-orphan",
                      "detail": f"kernel deep-shape validator {h!r} is referenced by no concern block "
                                f"(an orphan hook — a hook must be named by exactly one concern)"})
    return warns


# ── T-10025 (SPEC-0127): audience-scoped seed views — the generated per-audience siblings ──────────
# The seed docs carry section-level `<!--AUDIENCE:core|controller|worker-->` markers (authored by
# T-10024). `graph build` derives THREE committed derived-only views from them — the worker seed
# (core+worker sections), the controller supplement (controller sections), and the worker-startup
# inventory (report). This is the EXACT sibling of the floor-trigger-map / read-order
# generated-committed-with-drift-check pattern above (§3); NO new store / node-type / validation layer
# (§6). A malformed marker fails FAIL-CLOSED, like the read-order unknown-style ValueError.
_AUDIENCE_VALID_RE = re.compile(r'^<!--\s*AUDIENCE:\s*(core|controller|worker)\s*-->\s*$')
_AUDIENCE_LOOSE_RE = re.compile(r'^<!--\s*AUDIENCE:')          # an audience-marker-SHAPED line (for fail-closed)
_AUDIENCE_HEADING_RE = re.compile(r'^(#{1,6})\s+\S')          # a Markdown heading (a section boundary)

# T-10219 (SPEC-0007 §5c + SPEC-0120 §3): the worker seed is emitted as size-bounded PARTS, because a
# GENERATED startup read surface is held to the one-bounded-read ceiling exactly as a source doc is.
# T-10217 measured the pre-split monolith at 1275 lines / 50,775 reader-tokens / 4 read-calls — the
# reader physically truncated it at line 373.
#
# TWO bounds, because one is not enough here. The LINE band is SPEC-0120 §3's ("stricter and trivially
# measured"). But T-10217's decisive finding was that for THIS surface the LINE ceiling UNDERSTATES the
# overflow and the reader's TOKEN cap is what actually binds — and density is NOT uniform across the seed:
# CHARTER.md runs ~102 bytes/line (8.8K tokens over 218 lines) while AGENTS.md runs ~163 (14.0K tokens over
# 217 lines), a 1.7x spread. A line-only cap therefore packed CHARTER+AGENTS into one 435-line part at
# ~23.6K tokens — 94% of the reader's 25K page cap, i.e. it barely bought the safety the split exists for.
# So a part also carries a BYTE budget: deterministic and trivially measured (`wc -c`), keeping SPEC-0120
# §3's virtue while tracking the constraint that binds. 48,000 B ≈ 19.1K reader tokens at the 2.52
# bytes/token ratio calibrated from T-10217's live measurement (127,774 B / 50,775 tok) — ~24% headroom
# even for a part that exactly fills the budget. Not knife-edge: any budget in 40,000–48,000 B yields the
# SAME cut on today's corpus (chunk granularity dominates), worst part 14.0K tokens.
# The bounds govern the RENDERED part — the file a Worker actually opens — not just its assembled source
# content (audit-post F1). TWO layers of generated wrapping sit outside that content, and BOTH must fit
# inside the bound, because a Worker reads one layer or the other:
#   (1) the CHAIN NAV this generator emits into every part — the DO-NOT-EDIT banner, the `part N of M`
#       title, the chain header, the `<!-- seed-nav -->` sentinel and the next-hop footer (~15 lines /
#       ~1.6KB today; the chain header scales with the part COUNT). An engine-self Worker reads `graph/`.
#   (2) the RELEASE-VIEW banner `_build_release_view` prepends when it publishes each part to
#       `release-view/graph/` (RELEASE_VIEW_BANNER: 2 lines / 157 bytes). A `-C` consumer Worker reads THAT
#       chain (SPEC-0074 §7), so a part inside the bound in `graph/` could still be over it there — the
#       accompanying `_release_view_strip` only ever REMOVES text, but the banner is pure addition.
# Bounding the content alone would let a part sized exactly at the cap render OVER it in either layer, i.e.
# the mechanism could pass while the artifact is single-read-UNSAFE. So the packer packs against
# (bound - reserve) where the reserve covers BOTH layers, and probe 3 re-checks the RENDERED size against
# the full bound. The equivalence test additionally hard-checks the PUBLISHED release-view parts and asserts
# nav+banner actually fits the reserve — so the by-construction argument is verified, never assumed.
_WORKER_SEED_PART_MAX_LINES = 500
_WORKER_SEED_PART_MAX_BYTES = 48_000
# chain nav (~15 lines / ~1.6KB) + RELEASE_VIEW_BANNER (2 lines / 157 B) + headroom for a growing chain list
_WORKER_SEED_NAV_RESERVE_LINES = 24
_WORKER_SEED_NAV_RESERVE_BYTES = 2_400
# `worker-seed.md` (part 1 — KEEPS the original name, the AGENTS.md split precedent, so every surface that
# names it stays valid as the chain ENTRY) then `worker-seed-2.md` … `-N.md`. `worker-startup-inventory.md`
# does not match (it is not a `worker-seed*` name).
_WORKER_SEED_PART_RE = re.compile(r'^worker-seed(?:-(\d+))?\.md$')
# the machine sentinel that closes a part's CONTENT region — everything after it is generated chain
# navigation, never seed content (the equivalence reader strips on it).
_WORKER_SEED_NAV_SENTINEL = "<!-- seed-nav -->"


def _worker_seed_part_filename(idx: int) -> str:
    """0-based part index → the emitted filename. Part 1 keeps the pre-split name (`worker-seed.md`)."""
    return "worker-seed.md" if idx == 0 else f"worker-seed-{idx + 1}.md"


def _worker_seed_part_index(fname: str):
    """The 1-based part number of a worker-seed part filename, or None if it is not one."""
    m = _WORKER_SEED_PART_RE.match(fname)
    if not m:
        return None
    return int(m.group(1)) if m.group(1) else 1


def worker_seed_part_files(graph_dir) -> tuple:
    """The ordered `worker-seed*.md` part filenames present under `graph_dir` (a Path). Reads the DERIVED
    output (never a second declared list — P5): the generator owns the part COUNT, consumers discover it
    here. Falls back to the pre-split single name when the dir carries none (a partial repo / mini-engine
    fixture), so a caller's completeness invariant still names exactly one worker seed."""
    found = []
    for p in graph_dir.glob("worker-seed*.md"):
        i = _worker_seed_part_index(p.name)
        if i is not None:
            found.append((i, p.name))
    return tuple(n for _i, n in sorted(found)) or ("worker-seed.md",)


# T-10625: the NON-worker-seed audience views `_render_audience_views` emits alongside the seed parts.
# Kept beside `worker_seed_part_files` so `audience_view_files` reads as one carrier; the render remains
# the TRUE single source and the T-10625 probe locks this tuple to its emitted keys (a divergence here is
# a test failure, not a silent stale-view class).
_AUDIENCE_VIEW_STATIC_FILES = ("controller-supplement.md", "worker-startup-inventory.md")

# T-10625: the audience view(s) the release-view deliberately does NOT publish — the inventory is a build
# REPORT (§3c), not a seed a consumer reads. ONE home, consumed by both `_release_view_docs` (what gets
# published) and `audience_view_paths` (what land stages), so the two cannot drift apart.
_RELEASE_VIEW_UNPUBLISHED = ("worker-startup-inventory.md",)


def audience_view_files(graph_dir) -> tuple:
    """The graph/ audience-view filenames `_render_audience_views` emits (SPEC-0127 §3), for `graph_dir`
    (a Path). The ONE carrier of that name set for callers that cannot render (the land bookkeeping sets
    are built at module load, before any handbook text is read) — the worker-seed part COUNT is discovered
    off the DERIVED output via `worker_seed_part_files` (never re-declared, P5), and the two fixed views
    come from `_AUDIENCE_VIEW_STATIC_FILES`. MUST equal `_render_audience_views(...).keys()`; the T-10625
    probe asserts exactly that."""
    return worker_seed_part_files(graph_dir) + _AUDIENCE_VIEW_STATIC_FILES


def audience_view_paths(root) -> set:
    """The repo-relative graph/ audience-view paths present under the checkout `root` (a Path) RIGHT NOW.

    Covers BOTH the canonical `graph/` views and their published `release-view/graph/` twins (all but the
    inventory REPORT, which `_release_view_docs` deliberately does not publish).

    T-10625 (audit-post finding): the land bookkeeping sets are frozen at module load, so they cannot name
    a worker-seed CONTINUATION part that this very process just created — a branch whose handbook edit
    GROWS the seed past a part boundary without running `graph build` makes land's regen emit a new
    `graph/worker-seed-<n>.md`. The observed failure is NOT dirt (measured): land FORCE-DISCARDS unstaged
    post-integrate dirt, so main comes back CLEAN but carrying only the parts the frozen set happened to
    name — a SILENTLY TRUNCATED seed chain whose last part points at a next hop that does not exist. That
    is the precise thing SPEC-0127 §3 / T-10219 exist to prevent ("one part is NOT the seed"), and it hits
    the release-view twins too — which a `-C` consumer reads AS its methodology seed (SPEC-0074 §7).
    Every OTHER consumer of the sets runs in a LATER process, whose module-load glob already sees the part
    on disk — so only land's same-run staging needs this call-time read; it stays a narrow read of what the
    generator just emitted, not a second allowlist."""
    names = audience_view_files(root / GRAPH_DIR)
    return ({f"{GRAPH_DIR}/{n}" for n in names}
            | {f"{RELEASE_VIEW_DIR}/{GRAPH_DIR}/{n}" for n in names if n not in _RELEASE_VIEW_UNPUBLISHED})


def _chunk_bytes(lines: list) -> int:
    """The on-disk size a chunk contributes to its part — the same `\\n`.join the renderer emits."""
    return len("\n".join(lines))


def _pack_worker_seed_parts(chunks: list, max_lines: int, max_bytes: int) -> list:
    """Group whole source-doc chunks into size-bounded parts. `chunks` = [(doc_name, [lines…])] in
    HANDBOOK_READ_ORDER; returns [[(doc_name, [lines…]), …], …] — the parts, in order.

    CONTIGUOUS APPEND-ONLY NEXT-FIT (audit-pre F1 — deliberately NOT classic first-fit, which rescans
    OPEN bins and could place a later chunk into an earlier part, REORDERING the seed): exactly ONE part
    is open at a time; each chunk is appended to it, and only when appending would exceed EITHER bound is
    the open part CLOSED and a fresh one opened. A closed part is never revisited.

    BOTH bounds are enforced (see the constants): `max_lines` is SPEC-0120 §3's band; `max_bytes` tracks the
    reader's token page cap, which is what actually binds when per-doc density varies (T-10217). The caller
    passes them ALREADY REDUCED by the generated-navigation reserve, so the RENDERED part — not merely its
    source content — stays inside the real bound (audit-post F1); probe 3 re-checks the rendered size.

    ORDER INVARIANT: concatenating the parts in part order reproduces the input chunk order EXACTLY — the
    packer chooses only WHERE the cuts fall, never which side of a cut a chunk lands on. A chunk that alone
    exceeds a bound becomes its own sole part (never dropped, never cut mid-doc); the §5 probe-3 reports it,
    and the fix is to split that SOURCE doc (SPEC-0120 §3), not to cut it here."""
    parts: list = []
    cur: list = []
    cur_lines = cur_bytes = 0
    for name, lines in chunks:
        n_bytes = _chunk_bytes(lines)
        if cur and (cur_lines + len(lines) > max_lines or cur_bytes + n_bytes > max_bytes):
            parts.append(cur)
            cur, cur_lines, cur_bytes = [], 0, 0
        cur.append((name, lines))
        cur_lines += len(lines)
        cur_bytes += n_bytes
    if cur:
        parts.append(cur)
    return parts


class _AudienceFormatError(ValueError):
    """A seed doc's AUDIENCE marker is malformed (SPEC-0127 §1a/§6) — an unknown value, or >1 marker on
    one heading. FAIL-CLOSED, the audience analog of the read-order unknown-style ValueError: the drift
    check catches it → a RED `audience-view-drift` finding, and the explicit `graph build` fails loudly."""


def _parse_audience_doc(name: str, text: str) -> tuple:
    """Parse ONE seed doc into (sections, line_audiences, marker_lines) per SPEC-0127 §1a.
      - sections: list of {level, heading, own, effective, line} in document order.
      - line_audiences: list parallel to text.split('\\n') — each source line's EFFECTIVE audience.
      - marker_lines: the set of line indices that ARE recognized AUDIENCE markers (dropped from views).
    Fence-aware (``` toggles state — a heading inside a fenced code block is NOT a boundary, §1a). The
    marker is the line IMMEDIATELY below its heading. Effective audience = OWN marker, else the nearest
    ANCESTOR heading's effective audience, else 'core' (§2 fail-safe over-inclusion). RAISES
    _AudienceFormatError on a malformed marker (unknown value, or a second marker on one heading)."""
    lines = text.split("\n")
    fence = False
    stack: list = []                 # (level, effective) for the enclosing-heading chain (ancestors)
    sections: list = []
    marker_lines: set = set()
    line_aud: list = ["core"] * len(lines)
    for i, ln in enumerate(lines):
        if ln.lstrip().startswith("```"):
            fence = not fence
            line_aud[i] = stack[-1][1] if stack else "core"
            continue
        if not fence:
            m = _AUDIENCE_HEADING_RE.match(ln)
            if m:
                level = len(m.group(1))
                while stack and stack[-1][0] >= level:      # pop siblings/deeper → leave true ancestors
                    stack.pop()
                own = None
                nxt = lines[i + 1].strip() if i + 1 < len(lines) else ""
                mm = _AUDIENCE_VALID_RE.match(nxt)
                if mm:
                    own = mm.group(1)
                    marker_lines.add(i + 1)
                    nxt2 = lines[i + 2].strip() if i + 2 < len(lines) else ""
                    if _AUDIENCE_LOOSE_RE.match(nxt2):       # a SECOND marker under one heading — malformed
                        raise _AudienceFormatError(
                            f"{name}:{i + 3}: >1 AUDIENCE marker on heading {ln.strip()!r} "
                            "(at most one per heading, SPEC-0127 §1a)")
                elif _AUDIENCE_LOOSE_RE.match(nxt):          # marker-SHAPED but not a valid value — malformed
                    raise _AudienceFormatError(
                        f"{name}:{i + 2}: malformed AUDIENCE marker {nxt!r} "
                        "(value must be core|controller|worker, SPEC-0127 §1a)")
                effective = own if own else (stack[-1][1] if stack else "core")
                stack.append((level, effective))
                sections.append({"level": level, "heading": ln.strip(), "own": own,
                                 "effective": effective, "line": i})
        line_aud[i] = stack[-1][1] if stack else "core"
    return sections, line_aud, marker_lines


def _render_audience_views(handbook_docs: dict, read_order) -> dict:
    """Derive the audience views (SPEC-0127 §3) from the tagged seed docs. `handbook_docs` =
    {filename: text}; `read_order` = the ordered filename tuple (CANONICAL_DOCS). Returns a dict of
    {filename: byte-deterministic DERIVED-ONLY string}:
      (a) worker-seed.md [+ worker-seed-2.md … -N.md] — the assembled CONTENT of the core+worker sections
          (what a Worker reads), emitted as size-bounded PARTS so each is single-read-safe (SPEC-0007 §5c /
          SPEC-0120 §3, T-10219). Part 1 keeps the pre-split name; each part chains to the next hop.
      (b) controller-supplement.md— the assembled CONTENT of the controller sections (a derived reference
          view — NOT a runtime startup read since T-10216, so the one-bounded-read ceiling does not bind it).
      (c) worker-startup-inventory.md — the report: per-section audience + worker-seed size + §5 hard probe.
    Each is a pure function of the source text (filter source LINES by effective audience, drop AUDIENCE
    marker lines), so re-generation is byte-identical. RAISES _AudienceFormatError (fail-closed) on a
    malformed marker. NOT parallel storage: the tagged SOURCE sections stay the ONLY normative text (§3, P5)."""
    order = [n for n in read_order if n in handbook_docs]

    def _banner(kind: str) -> list:
        return [
            "<!-- GENERATED by `bin/yitc-v2 graph build` from the seed docs' `<!--AUDIENCE:...-->` section",
            "     markers (SPEC-0127). DO NOT EDIT — a hand edit is overwritten on the next build and a",
            "     divergent committed copy is flagged by `graph conformance` (audience-view-drift). The",
            f"     tagged SOURCE sections are the ONLY normative text; this is a derived-only {kind}. -->",
            "",
        ]

    ctrl_out = _banner("controller supplement (controller-only sections)")
    ctrl_out += ["# Controller supplement — read IN ADDITION to the worker seed (generated, SPEC-0127)", ""]

    inv_rows: list = []              # (doc, section) in document order
    worker_body: list = []           # only the seed CONTENT lines (for the §5 line/token totals)
    untagged_top: list = []          # #/## headings lacking an OWN marker (§5 condition 2 / §3c drift)
    worker_chunks: list = []         # (doc_name, block_lines) — the packer's units, in read-order

    for name in order:
        text = handbook_docs[name]
        sections, line_aud, marker_lines = _parse_audience_doc(name, text)
        lines = text.split("\n")
        w = [ln for i, ln in enumerate(lines) if i not in marker_lines and line_aud[i] in ("core", "worker")]
        c = [ln for i, ln in enumerate(lines) if i not in marker_lines and line_aud[i] == "controller"]
        if any(x.strip() for x in w):
            worker_chunks.append((name, [f"<!-- source: {name} (worker seed = core + worker) -->", ""] + w + [""]))
            worker_body += w
        if any(x.strip() for x in c):
            ctrl_out += [f"<!-- source: {name} (controller supplement) -->", ""] + c + [""]
        for s in sections:
            inv_rows.append((name, s))
            if s["level"] <= 2 and s["own"] is None:
                untagged_top.append((name, s["heading"]))

    controller_str = "\n".join(ctrl_out).rstrip("\n") + "\n"

    # ── the worker seed, cut into size-bounded parts at the `<!-- source: -->` seam (T-10219) ────────────
    # Pack against the bounds MINUS the generated-navigation reserve, so the RENDERED part lands inside the
    # real bound (audit-post F1). Probe 3 below re-checks the rendered size against the FULL bound.
    packed = _pack_worker_seed_parts(worker_chunks,
                                     _WORKER_SEED_PART_MAX_LINES - _WORKER_SEED_NAV_RESERVE_LINES,
                                     _WORKER_SEED_PART_MAX_BYTES - _WORKER_SEED_NAV_RESERVE_BYTES) or [[]]
    total = len(packed)
    part_names = [_worker_seed_part_filename(i) for i in range(total)]
    chain = " · ".join(f"`graph/{n}`" for n in part_names)
    worker_parts: dict = {}
    part_stats: list = []            # (filename, [doc names], rendered lines, rendered bytes, ws tokens)
    for i, chunks in enumerate(packed):
        body = [ln for _n, blk in chunks for ln in blk]
        docs_here = [n for n, _blk in chunks]
        out = _banner("worker seed (core + worker sections)")
        if total == 1:
            # degenerate handbook (a partial repo / fixture): no chain to navigate — keep the pre-split shape.
            out += ["# Worker seed — what a `--type build` Worker reads (generated, SPEC-0127)", ""]
        else:
            out += [f"# Worker seed — part {i + 1} of {total} — what a `--type build` Worker reads "
                    "(generated, SPEC-0127)", ""]
            out += [
                f"> **This is part {i + 1} of {total} — the WHOLE chain is your startup seed, not this part "
                "alone.** The worker seed is SPLIT into single-read-safe parts (SPEC-0120 §3 / SPEC-0007 §5c);",
                f"> reading only one part leaves you missing rules. Parts, in order: {chain}.",
                f"> **This part carries:** {' · '.join(docs_here)}.",
                "",
            ]
        out += body
        out += [_WORKER_SEED_NAV_SENTINEL, ""]
        if total == 1:
            out += ["> **END of the worker seed.**", ""]
        elif i + 1 < total:
            out += [f"> **The worker seed CONTINUES — part {i + 2} of {total}: `graph/{part_names[i + 1]}`.** "
                    "Read it NEXT;", "> the whole chain IS your seed (SPEC-0120 §3 split — SPLIT never "
                    "deletes content).", ""]
        else:
            out += [f"> **END of the worker seed** (part {total} of {total} — you have now read the whole "
                    "`core`+`worker` seed).", ""]
        rendered = "\n".join(out).rstrip("\n") + "\n"
        worker_parts[part_names[i]] = rendered
        # RENDERED size (the file a Worker opens), not the assembled content — the bound must govern the
        # artifact, not an inner slice of it (audit-post F1).
        part_stats.append((part_names[i], docs_here, rendered.count("\n"), len(rendered.encode("utf-8")),
                           sum(len(x.split()) for x in body)))

    # §5 condition 1 — a controller-section LEAK detector, computed from the ACTUAL generated worker seed
    # (NOT re-derived from the same effective-audience the assembly filters on — that would be tautological
    # and blind to a real leak). Scan the assembled worker-seed STRING for each controller section's own
    # HEADING line: if the assembly ever includes a controller section (e.g. a resolution/filter bug, or a
    # future assembly that diverges from the audience computation), that section's `###`-prefixed heading
    # appears in the output → the probe fires. A prose MENTION of the topic carries no `###` prefix, so it
    # does not false-match. 0 in a correct build; the recurring inspection (T-10027) HARD-FAILS on nonzero.
    # T-10219: scan the UNION of every part — a controller section that landed in part 3 must not hide from
    # a probe that only reads part 1.
    worker_seed_all = "\n".join(worker_parts.values())
    controller_headings = [s["heading"] for _n, s in inv_rows if s["effective"] == "controller"]
    controller_in_worker = sum(1 for h in controller_headings if ("\n" + h + "\n") in worker_seed_all)

    # §5 condition 3 (T-10219) — a RENDERED part over either size bound. Two ways it can fire, both
    # fail-closed: (a) a SINGLE source doc's worker-slice alone exceeds a bound — the packer cuts only at
    # whole-source-doc seams, so the fix is to split that SOURCE doc (SPEC-0120 §3), never to cut it mid-doc
    # here; (b) the generated-navigation reserve was outgrown (the chain header scales with the part COUNT),
    # so the reserve constant needs raising. Checked on the RENDERED size, so the probe governs the artifact
    # a Worker opens rather than an inner slice of it (audit-post F1).
    over_band = [(f, n, b) for f, _d, n, b, _t in part_stats
                 if n > _WORKER_SEED_PART_MAX_LINES or b > _WORKER_SEED_PART_MAX_BYTES]

    # (c) the inventory — the section audience map + the worker-seed size + the §5 hard probe.
    n_lines = len(worker_body)
    n_tokens = sum(len(x.split()) for x in worker_body)
    p1_verdict = "PASS" if controller_in_worker == 0 else "FAIL"
    p2_verdict = "PASS" if not untagged_top else "FAIL"
    p3_verdict = "PASS" if not over_band else "FAIL"
    inv = _banner("worker-startup inventory")
    inv += [
        "# Worker-startup inventory (generated, SPEC-0127)",
        "",
        "Per-section audience resolution across the worker-seed docs, the worker-seed size (total + per",
        "part), and the three-part HARD PROBE (§5). DERIVED-ONLY — the recurring inspection",
        "(T-10027) HARD-FAILS on any probe; this view is the state-check that feeds it.",
        "",
        "## Section audience map",
        "",
        "| doc | section | own tag | effective |",
        "|---|---|---|---|",
    ]
    for name, s in inv_rows:
        heading = s["heading"].replace("|", "\\|")
        inv.append(f"| {name} | {heading} | {s['own'] or '—'} | {s['effective']} |")
    inv += [
        "",
        "## Worker-seed size (total across the parts)",
        "",
        f"- worker-seed content lines: {n_lines}",
        f"- worker-seed tokens (whitespace-split): {n_tokens}",
        f"- worker-seed parts: {total} (size band per RENDERED part: {_WORKER_SEED_PART_MAX_LINES} lines AND "
        f"{_WORKER_SEED_PART_MAX_BYTES} bytes — SPEC-0120 §3 + the reader's token page cap, T-10217; the "
        f"packer reserves {_WORKER_SEED_NAV_RESERVE_LINES} lines / {_WORKER_SEED_NAV_RESERVE_BYTES} bytes "
        "for the generated chain navigation)",
        "",
        "## Worker-seed parts (the single-read-safe chain a Worker reads, in order)",
        "",
        "| part | carries | rendered lines | rendered bytes | tokens (whitespace-split) |",
        "|---|---|---|---|---|",
    ]
    for fname, docs_here, nl, nb, nt in part_stats:
        inv.append(f"| graph/{fname} | {' · '.join(docs_here) or '—'} | {nl} | {nb} | {nt} |")
    inv += [
        "",
        "## HARD PROBE (§5 — the inspection invariant)",
        "",
        f"- (1) controller-tagged sections inside the worker seed: {controller_in_worker} — {p1_verdict}",
        f"- (2) untagged #/## seed sections: {len(untagged_top)} — {p2_verdict}",
        f"- (3) worker-seed parts over the size band: {len(over_band)} — {p3_verdict}",
    ]
    if untagged_top:
        inv.append("")
        inv.append("Untagged #/## sections (tag each with an explicit `<!--AUDIENCE:...-->`, §3c):")
        for name, heading in untagged_top:
            inv.append(f"  - {name}: {heading}")
    if over_band:
        inv.append("")
        inv.append("Over-band RENDERED parts — either a SINGLE source doc's worker slice exceeds a bound "
                   "(split that SOURCE doc per SPEC-0120 §3; the packer never cuts mid-doc), or the "
                   f"generated-navigation reserve ({_WORKER_SEED_NAV_RESERVE_LINES} lines / "
                   f"{_WORKER_SEED_NAV_RESERVE_BYTES} bytes) was outgrown and needs raising:")
        for fname, nl, nb in over_band:
            inv.append(f"  - graph/{fname}: {nl} lines / {nb} bytes rendered "
                       f"(band {_WORKER_SEED_PART_MAX_LINES} lines / {_WORKER_SEED_PART_MAX_BYTES} bytes)")
    inventory_str = "\n".join(inv).rstrip("\n") + "\n"

    views = dict(worker_parts)
    views["controller-supplement.md"] = controller_str
    views["worker-startup-inventory.md"] = inventory_str
    return views


def _audience_views_drift(handbook_docs: dict, *, GRAPH_PATH, _is_consumer_build, _render_audience_views) -> list:
    """T-10025 (SPEC-0127 §3) — the committed graph/{worker-seed,controller-supplement,
    worker-startup-inventory}.md MUST each equal a fresh render over the live seed-doc AUDIENCE markers.
    A mismatch = `audience-view-drift`: a committed view went stale / was hand-edited. Returns [] or a
    list of {kind, detail}. REPORT-ONLY (its caller adds it to the conformance RED set; not a build gate)
    — the sibling of `_floor_map_drift` / `_read_order_drift`. FAIL-CLOSED on a malformed marker (the
    render raises → one RED finding). Engine-only (a consumer has no engine handbook of its own → [])."""
    if _is_consumer_build():
        return []
    try:
        views = _render_audience_views(handbook_docs)
    except _AudienceFormatError as e:
        return [{"kind": "audience-view-drift",
                 "detail": f"malformed AUDIENCE marker in a seed doc — {e} "
                           "(fix the marker; value must be core|controller|worker, one per heading)"}]
    out: list = []
    for fname, expected in views.items():
        p = GRAPH_PATH.parent / fname
        actual = p.read_text(encoding="utf-8") if p.exists() else ""
        if expected != actual:
            out.append({"kind": "audience-view-drift",
                        "detail": f"committed graph/{fname} != the regenerated view "
                                  "(run `yitc-v2 graph build` to refresh the derived audience views)"})
    # T-10219: an ORPHAN committed part — a `worker-seed-N.md` the render no longer emits (the seed shrank
    # past a part boundary). The loop above only visits files the render DOES emit, so without this a stale
    # part would survive on disk and a Worker would read a phantom chain hop.
    for p in sorted(GRAPH_PATH.parent.glob("worker-seed-*.md")):
        if p.name not in views:
            out.append({"kind": "audience-view-drift",
                        "detail": f"orphan committed graph/{p.name} — the regenerated worker seed has "
                                  f"{sum(1 for k in views if _worker_seed_part_index(k))} part(s); run "
                                  "`yitc-v2 graph build` to prune it"})
    return out


def _tok_est(n_bytes: int) -> int:
    """T-10661 — the bytes/4 token estimator, the ONE home for the conversion. Uniform by design (the
    T-10641 review §1 Method): an approximate absolute is fine because a UNIFORM estimator keeps DELTAS
    comparable, which is what a trajectory needs. Not a decreed unit — see `seed_growth_warnings`."""
    return n_bytes // 4


def seed_growth_warnings(baseline: dict, current: dict) -> list:
    """T-10349 (SPEC-0127 / folds fu_b613b347c11b, Bug B) — the diff-aware seed-budget WARN; T-10661 —
    extended with the BYTE/TOKEN axis. For each seed doc present in BOTH `baseline` (its text at the
    diff's merge-base) and `current` (its working-tree text), REPORT a `seed-growth` finding when the doc
    grew on EITHER axis — net LINES or net BYTES. Returns a list of {doc, base_lines, cur_lines, delta,
    base_bytes, cur_bytes, byte_delta, tok_delta}, or [] when no seed doc grew.

    WHY THE BYTE AXIS (T-10661, owner ruling Q1 2026-07-17). The line count alone is BLIND TO DENSITY:
    measured (T-10641 review §1a) the HANDBOOK_READ_ORDER set sat at 1739 lines = 70% of the 2500-line
    cap and GREEN, while carrying 177KB at ~102 bytes/line — the growth went into line DENSITY, not line
    COUNT, so the governing budget never fired through a x2.7 rise in total protocol reading cost. The
    same line-is-blind-to-density finding is already ratified in-corpus at SPEC-0127 §3 (a measured 1.7x
    density spread across the seed docs is why the part-packer bounds BYTES as well as lines). So a
    byte-only growth — bytes up while lines hold or FALL — is exactly the signal that was silent before
    and is the case this axis exists to catch. Consequence: on a byte-triggered finding `delta` (lines)
    may be 0 or NEGATIVE; render it SIGNED ({:+d}), never behind a hardcoded '+'.

    A REPORTED OUTCOME, NEVER A SECOND CAP (the load-bearing shape — owner ruling Q1). The byte/token
    figures are reported so a trajectory is VISIBLE; they are NOT a threshold, and no token number is
    decreed. A decreed number is voluntaristic (established by the cancelled plan
    `startup-slice-compression-re-home-handbook-bodies-`); what decides what STAYS in the seed is the
    three-bucket PLACEMENT TEST, not a number. SPEC-0127 §5 states the same rule for the sibling
    worker-seed total: "a total has no reader-facing threshold, only a trajectory". A hard token cap here
    would MIS-implement the ruling. The normative budget text is CHARTER §Principle 2 §Size budget.

    REPORT-ONLY by contract (UNCHANGED by T-10661): the caller prints these as a WARN and NEVER folds
    them into the conformance RED set or an exit code — the external consult (Bug B, YELLOW) prescribed a
    diff-aware WARN, NOT a second authoring GATE (a before-editing-seed trigger/detector/FSM is
    explicitly forbidden, CHARTER §6). The signal is authoring-time headroom pressure: it fires only
    after a diff exists, pairing with the always-loaded seed cue (AGENTS §Authoring the seed) that
    prevents most mistakes before the edit.

    Deliberately per-file growth (the consult's "when a seed file grows"), and only over docs the
    baseline ALREADY had — a brand-new seed doc (a deliberate SPEC-0120 split, aggregate-neutral) is not
    the accretion signal and is skipped. A doc that grew on NEITHER axis (a genuinely budget-neutral
    edit, or one that shrank) stays silent."""
    out: list = []
    for doc in sorted(current):
        base_text = baseline.get(doc)
        if base_text is None:                       # new doc — not the accretion signal (§docstring)
            continue
        base_n = len(base_text.splitlines())
        cur_n = len(current[doc].splitlines())
        base_b = len(base_text.encode("utf-8"))
        cur_b = len(current[doc].encode("utf-8"))
        if cur_n > base_n or cur_b > base_b:        # byte-OR-line: bytes catch the density growth
            out.append({"doc": doc, "base_lines": base_n, "cur_lines": cur_n, "delta": cur_n - base_n,
                        "base_bytes": base_b, "cur_bytes": cur_b, "byte_delta": cur_b - base_b,
                        "tok_delta": _tok_est(cur_b - base_b)})
    return out


def seed_budget_totals(baseline: dict, current: dict) -> dict:
    """T-10661 — the AGGREGATE trajectory of the seed budget: a derived VIEW over the SAME text
    `seed_growth_warnings` already compares (CHARTER §P1 F2 — a view, not a new entity; it stores
    nothing and reads no I/O — the host supplies both sides).

    Where the per-doc findings answer "which doc grew?", this answers "where is the SET now, and which
    way is it moving?" — the trajectory the T-10641 review says the line cap could not see. Returns
    {base_lines, cur_lines, line_delta, base_bytes, cur_bytes, byte_delta, tok_est, tok_delta}, over the
    WHOLE current set (the aggregate the CHARTER §P2 line cap is measured against) with the baseline
    side summed over only those docs the baseline had — so a brand-new doc's content counts toward the
    current total (it IS weight the reader pays) without inventing a phantom delta for it.

    REPORTED OUTCOME, not a threshold (owner ruling Q1 — see `seed_growth_warnings`): the caller renders
    this beside the existing 2500-LINE cap as an outcome; there is deliberately NO byte/token cap to
    compare against, and none is decreed here."""
    cur_lines = sum(len(t.splitlines()) for t in current.values())
    cur_bytes = sum(len(t.encode("utf-8")) for t in current.values())
    shared = [d for d in current if d in baseline]
    base_lines = sum(len(baseline[d].splitlines()) for d in shared)
    base_bytes = sum(len(baseline[d].encode("utf-8")) for d in shared)
    cur_shared_lines = sum(len(current[d].splitlines()) for d in shared)
    cur_shared_bytes = sum(len(current[d].encode("utf-8")) for d in shared)
    return {"base_lines": base_lines, "cur_lines": cur_lines,
            "line_delta": cur_shared_lines - base_lines,
            "base_bytes": base_bytes, "cur_bytes": cur_bytes,
            "byte_delta": cur_shared_bytes - base_bytes,
            "tok_est": _tok_est(cur_bytes), "tok_delta": _tok_est(cur_shared_bytes - base_bytes)}


def untagged_seed_headings(current: dict) -> list:
    """T-10349 (SPEC-0127 §1a) — the audience-classification half of the authoring-time check. Scan each
    seed doc for a `#`/`##` heading that carries NO OWN `<!--AUDIENCE:...-->` marker. Per §1a every top-
    level heading MUST carry an own marker (a `###` may inherit); an untagged one resolves to `core` by
    the §2 fail-safe, so untagged CONTROLLER-shaped content is silently loaded for everyone — the exact
    drift this WARN surfaces. Returns [{doc, heading}] (document order), or [] when every heading is tagged.

    REPORT-ONLY, paired with `seed_growth_warnings` under the one conformance WARN (the consult's "untagged
    controller-shaped content OR a growing seed file surfaces a WARN"). A tagged heading (own marker set)
    stays silent. Fail-safe on a malformed marker: `_parse_audience_doc` raises, so a doc whose markers
    cannot be parsed is skipped here (the RED belongs to `_audience_views_drift`, not this WARN)."""
    out: list = []
    for doc in sorted(current):
        try:
            sections, _la, _ml = _parse_audience_doc(doc, current[doc])
        except _AudienceFormatError:
            continue                                    # malformed → _audience_views_drift owns the RED
        for s in sections:
            if s["level"] <= 2 and s["own"] is None:
                out.append({"doc": doc, "heading": s["heading"]})
    return out


def new_test_file_warnings(baseline_files: set, current_files: set) -> list:
    """T-10680 (SPEC-0165 rule 5 — extend-before-create) — the diff-aware EXTEND-BEFORE-CREATE cue.
    Given the set of `tests/test_*.py` basenames present at the diff's merge-base (`baseline_files`)
    and in the working tree now (`current_files`), REPORT one finding per test file that is NEW in
    current (absent at base). A batch that only EXTENDS an existing file adds no new basename → []
    (silent). Returns a sorted list of {file} findings (basename only).

    REPORT-ONLY by contract (the sibling of `seed_growth_warnings`): the caller prints a WARN and NEVER
    folds it into the conformance RED set or an exit code. SPEC-0165 rule 5 is a folding CUE ("before
    writing a new test file, extend the rule's existing suite"), NOT a blocking gate — a genuinely NEW
    rule legitimately justifies a new file, so this can only PROMPT, never refuse (CHARTER §P1). The WARN
    IS the loud surface (SPEC-0165: a loud tripwire OR an explicit waive, never silence) — the author
    either folds the probe into the rule's existing suite or names the new-rule justification."""
    return [{"file": f} for f in sorted(current_files - baseline_files)]


# T-12398 (X-1368) — the named-consumer-example probe's two narrow spans. A rule body may cite a
# consumer name legitimately (a prior-art line, a cross-reference); what ROTS is the name used as the
# ILLUSTRATIVE CASE of a rule — the `e.g. <name>` / `(<name>)` shape. These two regexes bound the probe
# to exactly that shape so the report stays readable instead of matching every mention.
_NCE_EG_SPAN = re.compile(r"\be\.g\.[^.;)]*", re.IGNORECASE)
_NCE_PAREN_SPAN = re.compile(r"\(([^()]*)\)")
# A `### <N>.` heading opens a NUMBERED RULE body; any other `###` heading closes it. The probe reads
# only inside such a region — a `### Prior-art` / `### Build-order` section is history/narration, not a
# rule, so a name there is not an illustrative case of anything.
_NCE_NUMBERED_HEADING = re.compile(r"^\s*#{2,4}\s+(\d+)\.")
_NCE_ANY_HEADING = re.compile(r"^\s*#{2,4}\s+")
# The AC2 DIFFERENTIAL at LINE granularity: a prior-art / history / incident citation INSIDE a numbered
# rule body names a real project as a RECORD of what happened, which cannot go stale the way an
# illustrative case can. Matched as a line-leading marker, never a substring anywhere on the line.
_NCE_HISTORY_LINE = re.compile(
    r"^\s*[-*>|]*\s*\**\s*(prior[- ]art|history|historical|incident|measured|grounds|provenance|precedent)\b",
    re.IGNORECASE)
# The SAME differential at SPAN granularity, which is where it actually bites. The dominant real shape
# is not a prior-art LINE but a RECORD CITATION inside the very parenthetical the probe reads —
# «(T-11411, kupiclub X-1068)», «(kupiclub, measured 2026-08-13)», «(boomrocket, 2026-07-15)». Those
# name the project that REPORTED or SUFFERED a thing, which is a fact about the past and cannot go
# stale the way «e.g. kupiclub waives it» did. Measured on this corpus: without this bound the sweep
# reported 22 mentions of which ~14 were citations, and a report that is mostly noise is one nobody
# reads. A span is a citation iff it carries an artifact id (T-/X-/E-/D-/SPEC-/fu_), an ISO-ish date,
# or a reporting verb.
# A `/` is NOT treated as a word character in the name match, because «(trend-finder/boomrocket)» is a
# slash-joined PAIR OF PROJECT NAMES held up as the illustrative declares-case — exactly the shape this
# probe exists to see — and a `/`-in-boundary rule silently swallowed it (SPEC-0109 §5, the card's own
# subject). What the `/` bound was really for is a PATH or a COMMAND, and that is excluded directly and
# visibly instead: a span carrying a path root, a `bin/` command or a source-file extension is not a
# project being named as an example.
_NCE_PATHLIKE_SPAN = re.compile(r"(?:^|[\s(])/|\bbin/|\.(?:ya?ml|py|md|json|sh)\b")
_NCE_CITATION_SPAN = re.compile(
    r"\b(?:[TXED]-\d{3,}|SPEC-\d{3,}|fu_[0-9a-f]+)\b"
    r"|\b\d{4}-\d{2}-\d{2}\b"
    r"|\b(?:measured|reported|filed by|incident|outage|prior[- ]art)\b",
    re.IGNORECASE)


def named_consumer_example_findings(spec_texts: dict, consumer_names) -> list:
    """T-12398 (X-1368) — the REPORT-ONLY named-consumer-example probe. Given `spec_texts`
    ({spec id -> the ACTIVE spec's body text}, the host supplies both the corpus walk and the
    active-status filter) and `consumer_names` (the registered consumer ids, host-read from the
    registry), REPORT every place an ACTIVE kernel spec's NUMBERED RULE body names a registered
    consumer as its ILLUSTRATIVE case. Returns a sorted list of {spec, line, name, text}; [] when clean.

    THE INCIDENT (kupiclub X-1368, measured). Two ACTIVE kernel specs named kupiclub as the illustrative
    WAIVE case — SPEC-0109 §5 «a project with no scheduler, e.g. kupiclub, waives it» and SPEC-0110
    rule 1 «A project with no scheduled output yet (e.g. kupiclub) WAIVES it». Both went FALSE on
    2026-08-08 when kupiclub started running a collector service, and neither spec noticed. Worse, the
    rot was LOAD-bearing: kupiclub's own `yitc-ops.yaml` waiver reason literally cited «SPEC-0109 §5
    names kupiclub itself as the waive case», so the stale example SHIELDED a false consumer
    declaration. A kernel rule that names a consumer takes on that consumer's state as a maintenance
    obligation nobody records; this probe makes the obligation visible.

    WHAT IS MATCHED, and why each bound is there (each bound EXCLUDES real mentions on purpose — the
    probe is built to be READ, and a report nobody reads is the same as no report):
      * ACTIVE specs only — the host's filter. A superseded/retired spec is history; its examples
        cannot mislead a reader of the governing corpus.
      * NUMBERED RULE bodies only — a `### <N>.` heading region, ending at the next `###` heading of any
        kind. A name in a `### Prior-art` / `### Build-order` / `### Refs` section is narration.
      * the `e.g. ...` span or a parenthetical `( ... )` on the line, whole-word — the illustrative
        shape. A name in ordinary rule prose («the kernel routes to <name>») is a cross-reference the
        rule genuinely makes, not an example standing in for a class.
      * NOT a prior-art / history / incident LINE, even inside a numbered rule body (`_NCE_HISTORY_LINE`)
        — a citation of what happened is a RECORD; it does not rot when the project moves on.
      * NOT a span that is itself a RECORD CITATION (`_NCE_CITATION_SPAN`) — the same differential where
        it actually bites. «(T-11411, kupiclub X-1068)» names who reported a thing, not an example of a
        rule; on this corpus that bound is the difference between 22 reported mentions and 8 real ones.
      * NOT the caller's own kernel name. The host passes the consumer set MINUS the kernel: `yitc-v2`
        appears inside a parenthetical in nearly every rule body as part of a `bin/yitc-v2 ...` verb
        pointer, so matching it would bury every real finding under hundreds of command citations. The
        kernel is also not a "named consumer" — it is the engine the rule is written FOR.
      * a name adjacent to `/`, `.` or `-` is NOT a whole-word hit — that is a path or a compound
        token (a `<projects-root>/<name>` path, `<name>.yaml`), not a project held up as an example.

    REPORT-ONLY BY CONTRACT (the sibling of `new_test_file_warnings` / `uncatalogued_type_findings`):
    the caller prints a WARN and NEVER folds this into the conformance RED set or an exit code. A rule
    that names a real project is sometimes exactly right — a positive declares-case, a named
    interoperability target — so this can only PROMPT the author to ask "does this example rot?", never
    refuse. PURE: every reading (the corpus, the active filter, the registry) is supplied by the host."""
    names = sorted({n for n in (consumer_names or ()) if n})
    if not names:
        return []                 # an unresolvable registry reports NOTHING, never everything (fail-soft)
    out = []
    for spec_id in sorted(spec_texts):
        in_rule = False
        for lineno, line in enumerate(str(spec_texts[spec_id] or "").splitlines(), start=1):
            if _NCE_ANY_HEADING.match(line):
                in_rule = bool(_NCE_NUMBERED_HEADING.match(line))
                continue
            if not in_rule or _NCE_HISTORY_LINE.match(line):
                continue
            spans = [m.group(0) for m in _NCE_EG_SPAN.finditer(line)]
            spans += [m.group(1) for m in _NCE_PAREN_SPAN.finditer(line)]
            spans = [s for s in spans if not _NCE_CITATION_SPAN.search(s)
                     and not _NCE_PATHLIKE_SPAN.search(s)]
            if not spans:
                continue
            for name in names:
                word = re.compile(r"(?<![\w.-])" + re.escape(name) + r"(?![\w.-])")
                if any(word.search(s) for s in spans):
                    out.append({"spec": spec_id, "line": lineno, "name": name,
                                "text": line.strip()[:160]})
    return sorted(out, key=lambda f: (f["spec"], f["line"], f["name"]))


def classify_event_types(types, corpus_text: str, code_blobs: dict):
    """T-11379 — THE catalogued/emitter predicate, in ONE place, applied to whichever tree the caller
    supplies. Returns (uncatalogued_with_emitter, residual_unnamed): of `types`, those absent from the
    `specs/` corpus text, split by whether an emitter exists in the `bin/` blobs.

    The federated rule is held BYTE-FOR-BYTE from the pre-T-11379 inline comparison (SPEC-0161 §Catalog
    completeness reconcile: a type is cataloged iff SOME active spec homes it, measured against the WHOLE
    `specs/` corpus; discriminator = does an emitter exist in `bin/`?). This is a pure EXTRACTION, not a
    restatement — nothing about WHICH types count as catalogued changed at T-11379; only the QUANTIFIER
    over the predicate moved, from main's accumulated journal to what THIS DIFF introduced (see
    `uncatalogued_type_findings`).

    It is extracted to graph rather than left in the test precisely so there is exactly ONE predicate: the
    gate (`tests/test_event_catalog_completeness.py`) and the residue WARN (`graph conformance`) read the
    same function, and the merge-base side reads the same function as the working-tree side. A second,
    grep-shaped baseline predicate could read a base-only type as catalogued and re-indict a bystander
    branch, or read an incidental mention as catalogued and miss the real introducer — the T-11379
    audit-pre pass-1 finding, closed by construction here.

    The predicate's own STRENGTH — a raw whole-corpus substring rather than structured active-spec homing
    — is a separate, real, tracked concern (followup fu_f5305ac63f6f), deliberately NOT changed here: a
    stronger predicate strictly WIDENS the failing set, so it must be measured report-only before it is
    ever allowed to gate a land, or it re-opens the very repo-wide-freeze class T-11379 closes. The
    SPEC-0124 ceiling-convergence consult (decisions/T-11379-audit-consult-pre.yaml) ruled it out of this
    card's scope on those grounds.

    PURE — the host walks the trees and supplies `corpus_text` + `code_blobs` ({path: text})."""
    with_emitter: list = []
    no_emitter: list = []
    for t in sorted(types):
        if t in corpus_text:
            continue
        pat = re.compile(r"[\"']" + re.escape(t) + r"[\"']")
        (with_emitter if any(pat.search(b) for b in code_blobs.values()) else no_emitter).append(t)
    return with_emitter, no_emitter


def event_catalog_tree_inputs(rev: str, *, git_bytes) -> tuple:
    """T-11395 — materialize a git REV's `specs/` corpus text + `bin/` blobs, shaped EXACTLY like the
    working-tree walk `tests/test_event_catalog_completeness.py:main()` does (specs/*.yaml concatenated
    for the corpus; every file under bin/ keyed by path for the emitters). Returns (corpus_text,
    code_blobs) — the pair `classify_event_types` above consumes.

    ONE MATERIALIZER, TWO CALLERS, AND THAT IS THE POINT. The in-verify gate resolves its merge-base
    side with this (its own private copy, `base_tree_inputs`, now delegates here) and the pre-queue
    refusal `_land_prequeue_uncatalogued_type_refusal` resolves all three of its tree sides with it.
    The same reasoning that put the PREDICATE in one place at T-11379 applies to the INPUT SHAPE: a
    second walk that, say, forgot the `.yaml` filter or keyed blobs differently would feed `classify`
    a different corpus and let the two sides disagree about what is catalogued — the pre-queue probe
    would then refuse a branch the verify would pass, which is the one failure mode a fail-open
    predictor must not have.

    BINARY END TO END. `cat-file --batch` frames each blob by its BYTE size, so decoding the stream
    first desyncs the offsets on the first non-ASCII byte (measured at T-11379: the frame walked off
    into the middle of a blob). Slice bytes, decode each body.

    Two subprocesses regardless of corpus size. Returns ("", {}) on ANY git failure — the CALLER
    decides what that means (the gate turns it into its fail-CLOSED direction; the pre-queue refusal
    into its fail-OPEN one), because the same absence is read oppositely by the two polarities.

    `git_bytes(args) -> (returncode, stdout_bytes)` is INJECTED, with an optional `stdin` kwarg for
    the batch call — so this module stays subprocess-free as it is everywhere else."""
    rc, out = git_bytes(["ls-tree", "-r", "-z", "--name-only", rev, "--", "specs", "bin"])
    if rc != 0:
        return "", {}
    names = [n for n in out.decode("utf-8", errors="ignore").split("\0") if n]
    wanted = [n for n in names
              if (n.startswith("specs/") and n.endswith(".yaml")) or n.startswith("bin/")]
    if not wanted:
        return "", {}
    rc, out = git_bytes(["cat-file", "--batch"],
                        stdin="".join(f"{rev}:{n}\n" for n in wanted).encode("utf-8"))
    if rc != 0:
        return "", {}
    pos, corpus_parts, code_blobs = 0, [], {}
    for name in wanted:
        nl = out.find(b"\n", pos)
        if nl == -1:
            break
        header = out[pos:nl].split()
        if len(header) != 3:                       # "<oid> missing" — skip this path, keep parsing
            pos = nl + 1
            continue
        size = int(header[2])
        body = out[nl + 1:nl + 1 + size].decode("utf-8", errors="ignore")
        pos = nl + 1 + size + 1                    # +1 for the trailing newline cat-file appends
        if name.startswith("specs/"):
            corpus_parts.append(body)
        else:
            code_blobs[name] = body
    return "".join(corpus_parts), code_blobs


def journal_diff_added_rows(diff_text: str) -> dict:
    """T-11491 — the ADDED event rows of a journal `git diff -U0` (or of a working-tree-vs-HEAD diff,
    which is the same shape), keyed by TYPE: {type: {raw row text, ...}}. Every `+` line is
    json-PARSED and its `type` read; a hunk line that is not a whole event row is skipped. Never a
    pattern match on the line text, so a journal line-format change cannot silently widen or narrow
    the set. `set(journal_diff_added_rows(d))` is the plain type set when only that is wanted.

    ONE READER, THREE CALLERS (the T-11216 one-oracle rule applied to the INPUT this time): the
    pre-queue refusal reads its branch-added rows with it, the in-verify gate reads its own, and the
    SAME function reads main's UNCOMMITTED rows for `main_checkout_residue_types` below — so "which
    rows does this diff add" cannot mean two different things on two sides of one comparison.

    ROWS, NOT JUST TYPES, and that is load-bearing rather than incidental: `main_checkout_residue_types`
    must tell a row FOLDED from main apart from a row the branch emitted ITSELF, and the two are
    distinguishable only at row identity — the fold copies main's line VERBATIM. Pure: the host runs
    git."""
    out: dict = {}
    for line in (diff_text or "").splitlines():
        if not line.startswith("+") or line.startswith("+++"):
            continue
        body = line[1:]
        try:
            obj = json.loads(body)
        except ValueError:
            continue
        if isinstance(obj, dict) and isinstance(obj.get("type"), str) and obj["type"]:
            out.setdefault(obj["type"], set()).add(body.strip())
    return out


def main_checkout_residue_types(candidates, *, main_uncommitted_rows, branch_added_rows,
                                branch_diff_text) -> list:
    """T-11491 — of `candidates`, the ones that are SPEC-0161 §THE NAMED RESIDUE in its UNCOMMITTED
    variant: rows that reached the SHARED MAIN CHECKOUT's journal without a worktree and without a
    land (D-0049), and that NO branch's own diff is answerable for. The caller folds the answer into
    the BASE side of `uncatalogued_type_findings`, so such a type reads `inherited` — reported, never
    gated — which is what the spec already says about the COMMITTED half of the same case.

    THE CONTRADICTION THIS CLOSES (measured 2026-08-22/23, this repo's journal). SPEC-0161 declares
    that residue report-only because it is by construction unattributable and a gate that cannot name
    a responsible party can only punish bystanders. But the UNCOMMITTED half was gated anyway: `land`
    FOLDS main's dirty journal onto the landing branch and commits it (the D-0049 fold-promise,
    `_land_fold_main_bookkeeping`), so from the next question onward those rows sit in the branch's own
    diff-vs-merge-base and read as diff-INTRODUCED. Three `probe_evidence_note` rows left uncommitted
    on main at 18:54:35Z (session 1f788bdd, another card's acceptance evidence, ZERO occurrences in
    main's committed journal) refused EVERY land in the repo for every session — task/T-11452 above
    the queue, and work/verify-worker-ceiling-and-test-priority carrying only a task YAML — and were
    not self-resolvable, since deleting them destroys that card's proof. That is the 2026-08-21
    repo-wide freeze T-11379 ended, reopened one layer down.

    TWO ATTRIBUTION GUARDS, and they are why this classifies the residue rather than weakening the
    gate. A candidate is exempted ONLY IF BOTH hold:

      (i) ROW IDENTITY — every added journal row of that type on the branch is ALSO one of main's
          uncommitted rows, verbatim. `branch_added_rows` is this branch's added rows vs the
          merge-base; a row the branch emitted ITSELF is not in main's dirt, so a branch that brings
          the type in through its OWN journal is NOT exempted even when main's dirt carries the same
          type. This guard is what makes the exemption "these are literally main's rows, folded" and
          not "this type also appears on main". Named at T-11491's audit-pre (finding: a same-type
          collision would otherwise read `inherited`); a TYPE-level test would have had it wrong, and
          the auditor's own proposed fix — require absence from the branch's whole diff-introduced
          type set — would have re-broken the incident, since the FOLD puts those rows in exactly that
          set. Row identity separates the two cases the type set cannot.

     (ii) NAME ABSENCE — the type's name appears NOWHERE in `branch_diff_text`, the branch's own diff
          with the journal EXCLUDED. So the branch that brings an EMITTER (or takes a catalog entry
          away) still fails on its own branch and still clears it there, T-11379's self-clearing
          attributable failure intact, even when a verb of its own has meanwhile appended a row of
          that type to main's journal. The containment test is deliberately COARSE (a bare substring,
          not a parse) and errs in the SAFE direction: a type name that appears for an unrelated
          reason WITHHOLDS the exemption, i.e. behaves exactly as today's code. It can never grant
          one.

    AN UNREADABLE GUARD INPUT EXEMPTS NOTHING — `None` for EITHER guard means the caller could not
    read it, and the whole function returns [] (raised at T-11491's audit-post, high/correctness: an
    earlier shape passed "" on a failed `git diff`, which is indistinguishable from an EMPTY diff and
    silently DISABLED guard (ii), so a branch introducing an emitter could be exempted by a git
    failure). `""` still means a genuinely empty diff, which trivially names nothing. This is the
    same direction every other read on this path takes: a failure degrades to today's strict
    behaviour, never to a narrower gate. Both guard inputs are REQUIRED keyword arguments precisely so
    a caller cannot omit one and get the pre-audit fail-open by default.

    PURE (the host runs git and supplies every reading). Returns a sorted list."""
    cands = set(candidates)
    if not cands or branch_added_rows is None or branch_diff_text is None:
        return []                          # an unreadable guard input exempts NOTHING (see above)
    residue = {t for t in cands & set(main_uncommitted_rows)
               if set(branch_added_rows.get(t, ())) <= set(main_uncommitted_rows.get(t, ()))}
    return sorted(t for t in residue if t not in branch_diff_text)


def uncatalogued_type_findings(base_uncatalogued, cur_uncatalogued) -> dict:
    """T-11379 — the DIFF-SCOPED event-catalog judgement: partition the currently-uncatalogued live event
    types into what THIS DIFF is answerable for and what it merely inherited. Third member of the
    diff-aware family beside `seed_growth_warnings` and `new_test_file_warnings` (CHARTER §P1 F1 —
    the analog is extended, not paralleled): same shape, a pure baseline-vs-current comparison whose two
    sides the HOST resolves against `git merge-base HEAD main`.

    Returns {"introduced": sorted(cur - base), "inherited": sorted(cur & base)}.

      * introduced — uncatalogued NOW and not uncatalogued at the base. This diff either brought the type
        in (its rows / its emitter) or took its catalog entry away, so the branch that is answerable for
        it is the branch under verify, and it can clear it on its own branch. This is the GATE's set.
      * inherited — uncatalogued at the base too. No branch created it and no branch can be indicted for
        it; it is REPORTED (the `graph conformance` `uncatalogued-type:` WARN), never gated.

    THE INCIDENT (2026-08-21, measured in this repo's own journal, not narrated). Seven
    `watch_verdict_recorded` rows reached main while their emitter sat unlanded in T-11370's worktree.
    `tests/test_event_catalog_completeness.py` reasons BACKWARD — from main's accumulated journal to
    `bin/` — so with rows present and no emitter the type landed in the no-emitter residual and AC1-prime
    failed ON MAIN. Every land in the repo was refused on that one cause for roughly an hour: aborts at
    04:33:54Z (T-11355), 04:39 (T-11375), 04:45 (T-11368), 04:49 (T-11358), each paying a full verify to
    learn it. It cleared at 05:04 only when T-11370 happened to land and supply the emitter. No branch
    created the state; every branch was indicted for it.

    WHY THE WINDOW IS STRUCTURAL, not anyone's mistake. A journal append may reach main WITHOUT a
    worktree (D-0049 — deliberately, so a deviation capture is never gated behind opening one), while
    code reaches main only through `land`. So a type's ROWS legitimately precede its EMITTER on main, and
    any check quantifying over main's accumulated journal has a window in which it indicts the repo for a
    state no branch authored. Closing the window by gating journal appends would trade a rare freeze for
    a permanent chill on capture, so the asymmetry stays and the QUANTIFIER moves instead.

    WHAT THIS DOES NOT TOUCH. The catalogued/uncatalogued PREDICATE is not narrowed by a line: the
    federated rule (SPEC-0161 §Catalog completeness reconcile — a type is cataloged iff SOME active spec
    homes it, measured against the WHOLE `specs/` corpus) is applied by the caller UNCHANGED, and applied
    IDENTICALLY to both sides. Only the quantifier over it moves, from "main's whole journal" to "what
    this diff introduced". T-11370 homing its type in SPEC-0133 is exactly why landing it resolved the
    freeze, and that route stays open. (A separate, real concern — that the shipped predicate is a raw
    whole-corpus substring rather than structured active-spec homing — was raised at T-11379's audit-pre
    and REJECTED as out-of-scope by the SPEC-0124 ceiling-convergence consult; it is tracked as followup
    fu_f5305ac63f6f, because a stronger predicate strictly WIDENS the failing set and so must be measured
    report-only before it is ever allowed to gate a land.)

    THE NAMED RESIDUE (the honest bound — a diff-scoped gate necessarily stops seeing some cases). A type
    whose rows reach main from a checkout that never lands — the D-0049 append from the main checkout, for
    a type no branch's diff ever introduces — is uncatalogued at the merge-base of every branch that runs
    the gate, so it lands in `inherited` forever and NO branch is ever failed for it. That is deliberate:
    the state is by construction unattributable, and a gate that cannot name a responsible party can only
    punish bystanders. It is not dropped either — `inherited` is exactly the set the caller reports at the
    `graph conformance` seam, report-only, so the residue is visible without being chargeable.

    THE UNCOMMITTED HALF OF THE SAME RESIDUE (T-11491) does NOT reach `inherited` by itself, and that is
    why `main_checkout_residue_types` above exists. `land` folds main's dirty journal onto the landing
    branch and commits it before either the pre-queue probe or the in-verify gate asks (the D-0049
    fold-promise), so a row that reached the SHARED MAIN CHECKOUT with no worktree and no land sits in
    the branch's diff-vs-merge-base and lands in `introduced` — the case measured 2026-08-22/23, where
    three uncommitted `probe_evidence_note` rows refused EVERY land in the repo, for every session. The
    CALLERS fold that set into `base_uncatalogued`, so this function is unchanged: it still only compares
    two sides, and the residue rule now covers both variants of the case the paragraph above names.

    PURE (the host supplies both sides; no git, no I/O), and the CALLER decides the fail-closed direction:
    a gate with no resolvable baseline must pass an EMPTY base set here, so every uncatalogued type reads
    as introduced and the behaviour degrades to the pre-T-11379 strict check. A report-only sweep may
    degrade to silence; a gate may not."""
    base, cur = set(base_uncatalogued), set(cur_uncatalogued)
    return {"introduced": sorted(cur - base), "inherited": sorted(cur & base)}


def test_growth_counts(test_texts: dict) -> dict:
    """T-10680 (SPEC-0165 — the paired growth-bend probe data) — the derivable test-growth numbers:
    the count of test FILES and test FUNCTIONS across the given {basename: text} mapping. A test
    function is a line matching `def test` (module-level or a method, at any indent). Returns
    {"files": N, "functions": M}. Pure — the host supplies the texts (git / the FS is host state the
    core never touches, mirroring `seed_budget_totals`).

    A REPORTED OUTCOME + trajectory, NOT a cap and NOT a gate (owner ruling shape reused from the
    seed-budget axis): the paired files+functions numbers make the test-suite growth VISIBLE so an
    accreting one-file-per-task drift (SPEC-0165 rule 5's kernel corollary) is a reading, not a
    surprise. No threshold is decreed here."""
    functions = 0
    for text in test_texts.values():
        for line in text.splitlines():
            if re.match(r"\s*def test", line):
                functions += 1
    return {"files": len(test_texts), "functions": functions}


def test_growth_delta(baseline: "dict | None", current: dict) -> dict:
    """T-10680 (SPEC-0165 — the growth-bend probe) — the time-bounded GROWTH numbers: given the counts
    recorded at the baseline (`baseline`, the `{files, functions}` payload of the most recent
    `test_growth_baseline` journal event, or None if none recorded yet) and the `current` counts, return
    the paired report {files, functions, files_delta, functions_delta, has_baseline}. The two deltas are
    the NEW test files + NEW test functions since the baseline (SPEC-0165 rule 5's "new test FILES and
    new test FUNCTIONS" growth-bend data); they are None when no baseline has been recorded yet.

    A REPORTED OUTCOME + trajectory, NOT a cap and NOT a gate: this makes the growth-bend visible so an
    accreting one-file-per-task drift is a reading, not a surprise. Pure — the host reads the journal
    baseline + supplies the current counts (the sibling of `seed_budget_totals` over the seed axis)."""
    if baseline is None:
        return {"files": current["files"], "functions": current["functions"],
                "files_delta": None, "functions_delta": None, "has_baseline": False}
    return {"files": current["files"], "functions": current["functions"],
            "files_delta": current["files"] - int(baseline.get("files", 0)),
            "functions_delta": current["functions"] - int(baseline.get("functions", 0)),
            "has_baseline": True}


def test_growth_line(counts: dict) -> str:
    """T-12023 (X-1248) — the PURE renderer for the `graph conformance` test-growth line. Pure, beside
    its two existing analogs `test_growth_counts` / `test_growth_delta` (the host composes, the core
    computes — the `seed_budget_totals` split).

    Two shapes, one for each thing the probe can honestly report:
      • the SKIP SENTINEL (`counts["skipped"]` truthy) — a `-C` CONSUMER, where the probe is
        deliberately engine-only (the kernel test-building doctrine is engine-scoped). It renders as a
        STATED SKIP: no numbers and NO `test_growth_baseline` instruction. Rendering the skip as
        `suite now 0 test file(s) / 0 test function(s) — no baseline recorded yet (emit a
        test_growth_baseline event ...)` is what X-1248 measured on kupiclub — a repo with 151 tracked
        test files read as a measured ZERO beside real readings, plus an instruction to anchor a weekly
        delta on an empty reading. An absent reading is not a reading of zero.
      • otherwise — the ENGINE line, unchanged: the paired suite counts + the since-baseline delta (or
        the no-baseline-yet anchoring instruction) + the SPEC-0165 trailer.

    Report-only on both arms — a reported outcome + trajectory, NOT a cap and NOT a gate."""
    if counts.get("skipped"):
        return "  test-growth: skipped (engine-only probe; a consumer runs its own tests)."
    if counts["has_baseline"]:
        delta = (f"since baseline: {counts['files_delta']:+d} new test file(s) / "
                 f"{counts['functions_delta']:+d} new test function(s)")
    else:
        delta = "no baseline recorded yet (emit a `test_growth_baseline` event to anchor the weekly delta)"
    return (f"  test-growth: suite now {counts['files']} test file(s) / "
            f"{counts['functions']} test function(s) — "
            f"{delta} (SPEC-0165 growth-bend probe — reported outcome + trajectory, NOT a cap).")


def _render_read_order(style: str, *, HANDBOOK_READ_ORDER) -> str:
    """Render the handbook read-order from the single carrier HANDBOOK_READ_ORDER. The return value is
    the EXACT inter-sentinel content (so regen = open + render + close, and the drift-check compares an
    AGENTS region's inner text == render(its style)). Styles:
      - "arrow"    → the bare sequence, ALL files incl. AGENTS:
                     "CHARTER.md → AGENTS.md → LIFECYCLE.md → QUEUE.md → GRAPH.md".
      - "numbered" → the §At-session-start "Read in this order" block: one numbered line per NON-self
                     entry (`N. **<stem>.md** — <purpose>`); AGENTS (is_self) is the file being read,
                     so it is excluded (named in the surrounding hand-prose, not here). Framed with a
                     leading + trailing newline so each line sits on its own line between the sentinels."""
    if style == "arrow":
        return " → ".join(f"{stem}.md" for stem, _p, _s in HANDBOOK_READ_ORDER)
    if style == "numbered":
        out, n = [], 0
        for stem, purpose, is_self in HANDBOOK_READ_ORDER:
            if is_self:
                continue
            n += 1
            out.append(f"{n}. **{stem}.md** — {purpose}")
        return "\n" + "\n".join(out) + "\n"
    raise ValueError(f"_render_read_order: unknown style {style!r}")


def _render_spec_placement_block(*, _derive_spec_placement) -> str:
    """Render the inter-sentinel content for the manifest §1 GEN region from `_derive_spec_placement()`
    — a deterministic markdown table (leading + trailing newline framing, like the read-order numbered
    style). The exact string `_regen_placement_manifest` substitutes between the sentinels (so the
    drift-lock compares the committed inner == this render)."""
    rows = _derive_spec_placement()
    out = ["", "| spec | placement realm (DERIVED: spec class-default + per-spec `travels:` marker) |",
           "|---|---|"]
    out += [f"| {sid} | {realm} |" for sid, realm in rows]
    out.append("")
    return "\n".join(out) + "\n"


def _report_graft_parse_errors(parse_errors: list) -> None:
    """T-0503 — surface YAML parse failures collected DURING a `_with_live_nodes(..., errors=…)` graft
    to stderr, mirroring the build's `_parse_errors` report. The graft OMITS a malformed file (→ treated
    as unknown/blocking by the safety readers — blocking semantics unchanged); this ADDS the observability
    so an unparseable authored task/decision is named at read time, not silently graft-skipped. The single
    home of this report shape (reused by `cmd_graph_query` + the 3 advisory graft callsites — task-file
    preview / task-pick safety line / worktree-new claim screen — P1 F1 / P5: no parallel report path)."""
    if not parse_errors:
        return
    print(f"yitc-v2: {len(parse_errors)} YAML parse failure(s) in authored tasks/decisions "
          "(graft omits them → treated as unknown/blocking):", file=sys.stderr)
    for _pe in parse_errors:
        print(f"  - {_pe.get('path')}: {_pe.get('error')}", file=sys.stderr)


def _resolve_placement(rel_path: str, travels_marker=None, *, PLACEMENT_REALMS, _PLACEMENT_CLASS_DEFAULTS, _PLACEMENT_EXCEPTION_CAPABLE, _PLACEMENT_PATH_OVERRIDES, _norm_relpath, _placement_class_for) -> str:
    """DERIVE an artifact's placement realm from the class-default matrix + an optional per-item
    `travels:` marker — the manifest-derivation PRIMITIVE (T-0888). An EXACT-PATH entry in
    `_PLACEMENT_PATH_OVERRIDES` wins FIRST (the T-0934 file-level override MODEL — SPEC-0073 rule 2:
    a specific file may deviate from its hard class default). Else: unmarked (None / ~ / 'default')
    -> the class default; a valid realm marker on an EXCEPTION-CAPABLE class -> that realm; a marker
    on a HARD class or an invalid marker -> the class default (the marker is ignored; the audit-pre
    lens flags such a conflict). An unclassified class fails SAFE to v2-self (never silently kernel)."""
    norm = _norm_relpath(rel_path)
    if norm in _PLACEMENT_PATH_OVERRIDES:
        return _PLACEMENT_PATH_OVERRIDES[norm]
    cls = _placement_class_for(rel_path)
    default = _PLACEMENT_CLASS_DEFAULTS.get(cls, "v2-self")
    marker = (str(travels_marker).strip().lower() if travels_marker is not None else "")
    if not marker or marker in ("~", "default", "none", "null"):
        return default
    if marker in PLACEMENT_REALMS and cls in _PLACEMENT_EXCEPTION_CAPABLE:
        return marker
    return default


def _section_text(text: str, header: str, next_prefix: str='## ') -> str:
    """The slice of `text` from `header` up to the next top-level (`## `) header. Mirrors the §-slicer
    in tests/test_t0874_manifest_completeness.py so derivation + probe read the same section bounds."""
    start = text.index(header)
    rest = text[start + len(header):]
    nxt = rest.find("\n" + next_prefix)
    return rest if nxt == -1 else rest[:nxt]


def _stage_bundle_coverage_violations(report: dict, *, _is_consumer_build, _plan_delivery_gating_stages,
                                      _relocated_gating_stages) -> list:
    """T-0295 (path-B core, CORPUS-LEVEL) — every relocated lifecycle gating-verb stage MUST resolve ≥1
    bound spec via the report's `stage_to_specs` view; a stage with NONE = `stage-no-bundle` (the
    relocation left that control-point undelivered). T-0657 ADDS the PLAN-axis mirror: every plan delivery
    gating-stage (`_plan_delivery_gating_stages`, derived from PLAN_STAGE_SEQUENCE) MUST resolve ≥1 bound
    spec via `plan_stage_to_specs`; a plan stage with NONE = `plan-stage-no-bundle` (the same T-0316
    empty-bundle seam on the plan axis). Returns a sorted list of {stage, kind}. CANONICAL-CORPUS only —
    its caller (cmd_graph_conformance) runs it only on the full corpus so a partial test sandbox (which
    lacks the relocated stages' specs) never false-REDs.

    ENGINE-ONLY — the check no-ops under `-C` (T-10541 / X-0408 + X-0409), the same exemption its
    siblings `_release_view_drift` / `_release_spec_slice_violations` / `_audience_views_drift` carry.
    The KERNEL's lifecycle gating stages are a kernel-realm concern (SPEC-0073 §placement): a consumer's
    corpus is born EMPTY and authors its own PRODUCT specs, which carry no kernel stage-bindings — so on
    a consumer every relocated + plan stage resolves an empty bundle and this fires 12 unsatisfiable rows
    (4 stage-no-bundle + 8 plan-stage-no-bundle). Unsatisfiable is the point: a consumer could only clear
    them by FABRICATING kernel-shaped bindings onto product specs, so the rows are a false-RED that blocks
    every consumer land, not a finding. The `canonical_corpus` guard at the call site does NOT cover this
    — under `-C` REPO_ROOT rebinds to the consumer and SPECS_DIR derives from it, so that equality holds
    on a consumer (it discriminates a monkeypatched test sandbox, NOT a consumer)."""
    if _is_consumer_build():
        return []
    stage_to_specs = (report or {}).get("stage_to_specs") or {}
    plan_stage_to_specs = (report or {}).get("plan_stage_to_specs") or {}
    viols = [{"stage": st, "kind": "stage-no-bundle"}
             for st in _relocated_gating_stages() if not stage_to_specs.get(st)]
    viols += [{"stage": st, "kind": "plan-stage-no-bundle"}
              for st in _plan_delivery_gating_stages() if not plan_stage_to_specs.get(st)]
    return sorted(viols, key=lambda v: (v["kind"], v["stage"]))


def _unmarked_cut_card_flags(*, PLANS_DIR, TASKS_DIR, _read_yaml, _split_frontmatter) -> list:
    """SPEC-0070 §5 report-only invariant (T-0685). Surface cards that LOOK like decomposition cut members
    of a plan currently being cut but lack the `decomposed_from` marker — so the AI can either mark a true
    cut card the cut path (`task file --decomposed-from`) forgot, or confirm a deliberate informational cite.

    SCOPE = plans at status `decomposition` ONLY (mode-b absorption of the T-0685 audit-pre findings,
    reconciling the two conflicting auditor findings): the claim-block refuses ONLY PRE-`executing` plans,
    and `decomposition` is the only pre-executing stage where task cards exist — so this window is exactly
    where an unmarked TRUE cut card would be wrongly claimable (round-1 safety intent). Plans at
    executing/postcheck/realized are claim-block-irrelevant (their cards are correctly claimable), so
    scanning them would only add perpetual noise on legitimate informational cites (round-2 noise concern).
    Completeness for FUTURE cuts is guaranteed by the cut path being the SOLE marker writer, not a perpetual
    corpus scan.

    A card is flagged when it `cites:` a plan at status `decomposition`, is NON-TERMINAL (status not
    done/wont-do — a closed card is frozen history, not claimable), and lacks `decomposed_from == that plan`.
    REPORT-ONLY (D-0040 report-not-block): `cites:` is overloaded so this is advisory disambiguation, NEVER a
    hard gate / never affects an exit code. Returns sorted [{"task": tid, "plan": slug}]. Best-effort:
    read failures are skipped (an advisory must never crash a verb)."""
    cutting = set()
    try:
        for p in state.scan_plans(PLANS_DIR):
            try:
                fm, _ = _split_frontmatter(p)
                if (fm or {}).get("status") == "decomposition":
                    cutting.add(p.stem)
            except Exception:
                continue
    except Exception:
        return []
    if not cutting:
        return []
    out = []
    for tp in state.scan_tasks(TASKS_DIR):   # T-* glob excludes _template.yaml
        d = _read_yaml(tp)
        if not isinstance(d, dict) or d.get("status") in ("done", "wont-do"):
            continue
        marker = d.get("decomposed_from")
        for slug in (d.get("cites") or []):
            if slug in cutting and marker != slug:
                out.append({"task": d.get("id") or tp.stem, "plan": slug})
    return sorted(out, key=lambda x: (x["task"], x["plan"]))


def _with_live_nodes(index: dict, errors: list | None=None, *, _yaml_task_decision_nodes) -> dict:
    """T-0491 — return a SHALLOW COPY of `index` with `tasks`/`decisions` grafted from the authored
    YAML (`_yaml_task_decision_nodes`), for the CURRENT-index readers (carve-out / projected /
    point-lookup / claim-screen / preview) that still need T-/D- node resolution after the cut dropped
    those build sections. The passed-in `index` object is NEVER mutated (a fresh `{**index}` copy carries
    the grafted sections) — so a caller meant to observe an ungrafted or HISTORICAL (`--as-of`) snapshot
    is unaffected; the graft is applied ONLY at the explicitly-listed current-index entrypoints. NEVER
    graft a historical `--as-of` index: a past graph reported against present YAML would be a lie
    (D-0046 — `--as-of` is a faithful point-in-time replay of the committed snapshot's OWN sections)."""
    live = _yaml_task_decision_nodes(errors=errors)
    return {**index, "tasks": live["tasks"], "decisions": live["decisions"]}


def _write_release_view(*, ENGINE_ROOT, _build_release_view, write_text_atomic) -> list:
    """Write the release view under ENGINE_ROOT (engine-only). Returns the written (rel, content) list.
    Caller guards on `not _is_consumer_build()`. Invoked BOTH by the explicit `graph release-view` /
    `graph build` AND at land via `_auto_rebuild_graph` (the T-9513/E-0034 derived-regen step — the
    committed `release-view/` paths ride _BOOKKEEPING_ALLOWLIST + _DERIVED_MERGE_ARTIFACTS), so a
    canonical-handbook change reaches main with a FRESH release-view without a prior `graph build`."""
    files = _build_release_view()
    for rel, content in files:
        dest = ENGINE_ROOT / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        write_text_atomic(dest, content)
    # T-10219: prune an orphan published worker-seed part (the graph/ side was pruned by `graph build`;
    # without this its release-view copy survives and a `-C` consumer Worker walks a phantom chain hop).
    _published = {rel for rel, _c in files}
    _rv_graph = ENGINE_ROOT / RELEASE_VIEW_DIR / "graph"
    if _rv_graph.is_dir():
        for _stale in _rv_graph.glob("worker-seed-*.md"):
            if f"{RELEASE_VIEW_DIR}/graph/{_stale.name}" not in _published:
                _stale.unlink()
    return files


def _yaml_task_decision_nodes(errors: list | None=None, *, DECISIONS_DIR, TASKS_DIR, _read_yaml) -> dict:
    """T-0491 — re-source the minimal task/decision node maps from the AUTHORED YAML (tasks/*.yaml +
    decisions/D-*.yaml), for the live readers that previously read index['tasks']/['decisions'] before
    the graph-slim cut dropped those build sections. Returns {"tasks": {...}, "decisions": {...}} in the
    SAME minimal node shape `graph_build_index` used to emit, so the readers stay byte-identical:
      tasks[id]     = {status, requires, expected_touch}
      decisions[id] = {status}

    EXTENDS the existing reader chokepoint — every file is read via `_read_yaml(p, errors=errors)`
    (the SAME reader + parse-error contract the build uses), NO parallel reader path (P1 F1 / P5).

    OBSERVABILITY + FAIL-CLOSED (controller decision 2026-06-07, Option A + the strengthening): when an
    `errors` list is supplied, an unparseable/unreadable file is appended there via `_read_yaml`'s
    parse-error path — so it is OBSERVABLE (the caller threads the build's `parse_errors`/`_parse_errors`
    accumulator, → `graph build` exit 2 / `land` block), NOT silently graft-skipped. A malformed file
    yields `{}` (no usable `id`/`status`) so it is OMITTED from the node map; the safety-sensitive
    readers then treat it as BLOCKING/unknown — `_requires_incomplete_in_index` returns BLOCKED for a
    `requires:` target that is absent from the map ("task not in index"), and an unparseable READY
    candidate never enters the ready set so it is never dispatched. This MIRRORS the disk picker
    `_requires_incomplete`'s not-found=blocked posture — same posture, no new behavior."""
    # Node shape: the SAME fields the pre-cut build emitted on the task/decision node (audit-post F1 —
    # so a `graph query T-/D-` point-lookup keeps returning the full authored node, no silent field
    # narrowing), PLUS the dispatch fields the carve-out/requires readers need (status/requires/
    # expected_touch). The dropped-edge-derived fields (commits_from/events/audits) are NOT here — those
    # are the cut (Option A), distinct from the authored node fields.
    tasks: dict = {}
    if TASKS_DIR.exists():
        for p in state.scan_tasks(TASKS_DIR):
            d = _read_yaml(p, errors=errors)
            if not d.get("id"):
                continue
            tasks[d["id"]] = {
                "title": d.get("title", ""),
                "status": d.get("status", ""),
                # T-10790: the RECENCY datum the filing preview's shipped-work overlap group needs
                # (`task.py#_overlapping_shipped_tasks`) — a terminal card is only in that group's
                # window if it closed within SHIPPED_OVERLAP_WINDOW_DAYS of the filing. No other
                # carried field dates a closure. Additive: every reader keys by name, so a node
                # gaining a field changes no existing behaviour.
                "closed_at": d.get("closed_at"),
                "commit": d.get("commit"),
                "cites": sorted(str(c) for c in (d.get("cites") or [])),
                "requires": sorted(str(r) for r in (d.get("requires") or [])),
                "expected_touch": sorted(str(x) for x in (d.get("expected_touch") or [])),
            }
    decisions: dict = {}
    if DECISIONS_DIR.exists():
        for p in state.scan_decisions(DECISIONS_DIR):
            d = _read_yaml(p, errors=errors)
            if not d.get("id"):
                continue
            decisions[d["id"]] = {
                "title": d.get("title", ""),
                "type": d.get("type", ""),
                "status": d.get("status", ""),
                "supersedes": d.get("supersedes"),
                "requires": sorted(str(r) for r in (d.get("requires") or [])),
                "cites": sorted(str(c) for c in (d.get("cites") or [])),
            }
    return {"tasks": tasks, "decisions": decisions}


def _glob_normalize(pattern: str) -> str:
    """T-10497 (X-0357) — normalize a trailing bare `**` to the file-matching `**/*`. In pathlib a
    pattern ending in `**` matches DIRECTORIES only, so `backend/app/**` + the `is_file()` filter below
    resolves to ZERO files: the declaration reads as a coverage/covers claim but silently claims nothing
    (fails OPEN — boomrocket shipped 3 such layers). Any other pattern is returned unchanged."""
    p = pattern.strip()
    return p + "/*" if p == "**" or p.endswith("/**") else p


def _coverage_glob_files(repo_root, globs, zero_globs=None) -> set:
    """Resolve a `coverage.load_bearing`-style glob list to the SET of repo-relative posix file paths it
    matches (the SHARED matching primitive — used for the `coverage.load_bearing` universe AND a verify
    layer's `covers:` globs, so both checks resolve a glob list identically). Skips non-string/blank
    patterns + un-globbable/out-of-tree matches (the original rule-15 tolerance).

    Each pattern is `_glob_normalize`d first (T-10497). `zero_globs`, when a list is passed, COLLECTS the
    ORIGINAL text of every declared pattern that resolves to zero files — the report-only zero-resolving
    WARN (`_coverage_zero_glob_warnings`); None collects nothing, so a caller that only wants the file set
    is unaffected."""
    files: set = set()
    for pattern in (globs or []):
        if not (isinstance(pattern, str) and pattern.strip()):
            continue
        matched: set = set()
        try:
            matches = list(repo_root.glob(_glob_normalize(pattern)))
        except (ValueError, OSError):
            matches = []
        for p in matches:
            if not p.is_file():
                continue
            try:
                matched.add(p.relative_to(repo_root).as_posix())
            except ValueError:
                continue
        if zero_globs is not None and not matched:
            zero_globs.append(pattern.strip())
        files |= matched
    return files


def _coverage_opt_in(repo_root, zero_globs=None):
    """SPEC-0152 rule 15 — the SHARED `coverage:` opt-in reader (P5). Returns `(load_bearing_files,
    admitted)` — the set of repo-relative files matching `coverage.load_bearing` globs + the set of
    validly-`admitted:` surfaces — or None when coverage tracking is NOT opted in (no/malformed carrier,
    an absent/waived/non-mapping `coverage:` section, or an empty `load_bearing:`). Reused by BOTH the
    spec-coverage admission check (`_coverage_admission_warnings`, rule 15) and the verify-layer coverage
    check (`_verify_layer_coverage_warnings`, rule 16) — one shape, one home. An `admitted:` entry counts
    ONLY when it is a mapping carrying a NON-EMPTY `surface` AND a NON-EMPTY `reason` (fail-OPEN: an
    evidence-less admission never silently hides a surface).

    `zero_globs` is passed straight through to `_coverage_glob_files` (T-10497 — collects the
    zero-resolving `load_bearing` patterns for the report-only WARN)."""
    ops_path = repo_root / "yitc-ops.yaml"
    if not ops_path.is_file():
        return None
    errors: list = []
    ops = state.load_path(ops_path, errors=errors)
    if errors or not isinstance(ops, dict):
        return None
    cov = ops.get("coverage")
    if not isinstance(cov, dict):
        return None
    if cov.get("waiver") is not None or cov.get("waived") is True:
        return None
    globs = cov.get("load_bearing")
    if not (isinstance(globs, list) and globs):
        return None
    admitted: set = set()
    for entry in (cov.get("admitted") or []):
        if not isinstance(entry, dict):
            continue
        surface, reason = entry.get("surface"), entry.get("reason")
        if (isinstance(surface, str) and surface.strip()
                and isinstance(reason, str) and reason.strip()):
            admitted.add(surface.strip())
    return _coverage_glob_files(repo_root, globs, zero_globs=zero_globs), admitted


def _coverage_admission_warnings(repo_root, code_to_specs) -> list:
    """SPEC-0152 rule 15 (T-9641, X-0129) — the B5 COVERAGE-ADMISSION check (report-only). Read the
    project's `yitc-ops.yaml` `coverage:` section and return the SORTED list of LOAD-BEARING surfaces
    that are NEITHER spec-covered (a key in `code_to_specs` — an `implements` edge from an active spec)
    NOR validly admitted (a reasoned spec-less surface listed in `admitted:`) — i.e. candidate NEW
    orphans, the thing the closed-task free-text judgment used to rot on (X-0129).

    OPT-IN / fail-OPEN (the `extensions:` rule-13 model): an absent/malformed carrier, an
    absent/waived/non-mapping `coverage:` section, or an empty `load_bearing:` returns [] (no admission
    tracking — a clean default, never a build failure). The kernel's own repo has no `yitc-ops.yaml`, so
    this no-ops there (zero false positives). The carrier read + admission filter is the SHARED
    `_coverage_opt_in` (reused by the rule-16 verify-layer check, P5)."""
    res = _coverage_opt_in(repo_root)
    if res is None:
        return []
    files, admitted = res
    covered = set(code_to_specs or {})
    return sorted(f for f in files if f not in covered and f not in admitted)


def _verify_layers(repo_root) -> list:
    """The `yitc-ops.yaml` `verify.layers` list, or [] when the carrier / section is absent, waived,
    malformed, or empty (opt-in — a waived `verify:` means no per-layer coverage tracking)."""
    ops_path = repo_root / "yitc-ops.yaml"
    if not ops_path.is_file():
        return []
    errors: list = []
    ops = state.load_path(ops_path, errors=errors)
    if errors or not isinstance(ops, dict):
        return []
    ver = ops.get("verify")
    if not isinstance(ver, dict):
        return []
    layers = ver.get("layers")
    return layers if isinstance(layers, list) and layers else []


def _glob_list(value) -> list:
    """A declared glob field read LIST-only: a list is returned as-is, anything else (a scalar string, a
    mapping, None) declares nothing. Without this a scalar `covers: "src/**"` would iterate as CHARACTERS
    — each a non-blank string, so the malformed scalar would read as a fully declared glob list.

    NO LONGER THIS FILE'S ALONE (T-11876): `bin/lib/plan.py` reads the SAME `cites`/`covers` declarations
    into the scenario-fidelity freshness basis and was char-walking a scalar exactly as this exists to
    prevent, so it now imports THIS function rather than growing a second copy (CHARTER §P1, one home).
    The leading underscore is kept deliberately — it marks kernel-internal, not file-internal, and this
    codebase already crosses module boundaries on private names throughout
    (`verify_runner._selection_leaf_test_freed`, `rebaseline_currency._inland_reaudit_refusal_text`).
    Renaming it would have bought nothing and would have superseded a pinned last-green assertion for
    cosmetics."""
    return value if isinstance(value, list) else []


def _verify_layer_covers_globs(repo_root) -> list:
    """The flat list of every declared `verify.layers[].covers` glob (the rule-16 claimed-surface globs).
    Split out of `_verify_layer_coverage_warnings` (T-10497) so the zero-resolving-glob WARN resolves the
    SAME glob list rather than re-deriving it (P5, one home).

    LIST-only (`_glob_list`, T-11135): a SCALAR `covers: "src/**"` is malformed, and iterating it would
    walk its CHARACTERS — every one a non-blank string, so the scalar would read as a fully declared glob
    list. Worse than cosmetic: one of those characters is `/`, which `_coverage_glob_files` hands to
    `Path.glob` as a non-relative pattern, raising out of `_coverage_zero_glob_warnings` and CRASHING
    `graph build`. A non-list declares nothing (the family's fail-open direction)."""
    globs: list = []
    for ly in _verify_layers(repo_root):
        if isinstance(ly, dict):
            for g in _glob_list(ly.get("covers")):
                if isinstance(g, str) and g.strip():
                    globs.append(g.strip())
    return globs


def _verify_layer_coverage_warnings(repo_root) -> list:
    """SPEC-0152 rule 16 (T-9718, X-0140) — the report-only VERIFY-LAYER COVERAGE check. Return the SORTED
    list of LOAD-BEARING surfaces present in code (the rule-15 `coverage.load_bearing` universe) that are
    covered by NO declared `verify.layers` layer's `covers:` glob and are not validly `admitted:` — i.e.
    candidate SILENTLY-UNTESTED layers (the X-0140 incident: a frontend layer in code but absent from the
    land-verify gate). The verify-layer analog of the rule-15 spec-coverage WARN, REUSING the SAME
    `coverage.load_bearing` universe + `admitted:` suppression (via `_coverage_opt_in`) + the same
    report-only stderr channel — NO new gate / event / section.

    OPT-IN / fail-OPEN: returns [] unless the project BOTH opts into coverage tracking (a non-empty
    `coverage.load_bearing`) AND declares a non-empty `verify.layers` list. A waived/absent `verify:`
    means no per-layer coverage tracking — NEVER a false 'everything uncovered' (zero false positives)."""
    res = _coverage_opt_in(repo_root)
    if res is None:
        return []
    files, admitted = res
    layers = _verify_layers(repo_root)
    if not layers:
        return []   # a waived/empty verify: section → no per-layer coverage tracking (opt-in)
    claimed = _coverage_glob_files(repo_root, _verify_layer_covers_globs(repo_root))
    return sorted(f for f in files if f not in claimed and f not in admitted)


def _verify_layer_boundary_globs(repo_root) -> list:
    """The flat list of every declared `verify.layers[].boundary` glob (SPEC-0152 rule 16 amend, T-10513).
    A layer's `boundary:` names the paths its harness can SEE (its hermetic mount scope) — DISTINCT from
    `covers:` (what it verifies). Mirrors `_verify_layer_covers_globs` so both resolve one home (P5) —
    INCLUDING its LIST-only read (`_glob_list`, T-11135): a SCALAR `boundary: "src/**"` is malformed and
    iterating it would walk its CHARACTERS as declared globs, crashing `graph build` on the `/` character
    as described there. A non-list declares nothing, which routes to this check's own opt-in-off path
    (no declared boundary → no visibility tracking) rather than to a false 'everything outside'."""
    globs: list = []
    for ly in _verify_layers(repo_root):
        if isinstance(ly, dict):
            for g in _glob_list(ly.get("boundary")):
                if isinstance(g, str) and g.strip():
                    globs.append(g.strip())
    return globs


def _verify_layer_boundary_warnings(repo_root) -> list:
    """SPEC-0152 rule 16 amend (T-10513, X-0375) — the report-only OUTSIDE-EVERY-BOUNDARY check. Return the
    SORTED list of LOAD-BEARING surfaces present in code (the rule-15 `coverage.load_bearing` universe) that
    fall OUTSIDE every declared `verify.layers[].boundary:` glob and are not validly `admitted:` — i.e. code
    no verify layer's harness can even SEE, un-verified by silence (the X-0375 incident: a hermetic mount
    blind to `scripts/`, so that code reached the container un-tested with nothing to say so).

    This is the VISIBILITY analog of the rule-16 `covers:` coverage WARN (`_verify_layer_coverage_warnings`):
    `covers:` asks "does a layer claim to verify this?", `boundary:` asks "can any layer's harness even
    REACH this?". A surface can be inside a boundary yet uncovered (a mount that sees it but runs no test
    over it — the covers WARN) OR outside every boundary (a mount blind to it — this WARN). REUSES the same
    `coverage.load_bearing` universe + `admitted:` suppression (via `_coverage_opt_in`) + the same
    report-only stderr channel — NO new gate / event / section.

    OPT-IN / fail-OPEN: returns [] unless the project BOTH opts into coverage tracking (a non-empty
    `coverage.load_bearing`) AND at least one `verify.layers` layer declares a non-empty `boundary:`. Without
    a declared boundary EVERY file is trivially 'outside', which would false-nag the whole tree — so the
    check is silent until a project answers "what can my harnesses see?" (zero false positives, the rule-16
    coverage-WARN discipline)."""
    res = _coverage_opt_in(repo_root)
    if res is None:
        return []
    files, admitted = res
    boundary_globs = _verify_layer_boundary_globs(repo_root)
    if not boundary_globs:
        return []   # no layer declares a boundary → no visibility tracking (opt-in; never nag everything)
    inside = _coverage_glob_files(repo_root, boundary_globs)
    return sorted(f for f in files if f not in inside and f not in admitted)


def _verify_layer_skip_off_warnings(repo_root) -> list:
    """T-11130 (SPEC-0152 rule 16 subject_globs sub-rule, T-10571) — the report-only NEVER-SKIPS check.
    Return the SORTED list of `verify.layers` layer NAMES that declare a non-empty `covers:` but NO
    non-empty `subject_globs:` — i.e. layers that can never be skipped by subject scoping, so every land
    pays for them whatever the diff touches (measured 2026-08-15: cardlab 2/2 and bc-community 2/2 layers,
    neither project having ever skipped a layer, against peers skipping on roughly a third of lands).

    The THIRD question in the rule-16 report-only family, beside `_verify_layer_coverage_warnings`
    (`covers:` asks "does a layer claim to verify this?") and `_verify_layer_boundary_warnings`
    (`boundary:` asks "can any harness even REACH this?"): this one asks "will this layer ever SKIP?".
    Same exit-0 stderr channel, same advisory register, same «NOT a validation layer» stance — NO new
    gate / event / store / section. The fail-CLOSED `_subject_scoping_skip_layers` behaviour (an absent
    `subject_globs` ⇒ the layer always runs) is CORRECT and untouched; the defect is that the OFF state
    is indistinguishable from a configured one, because `covers:` and `subject_globs:` are adjacent glob
    lists over the same repo surface and only one turns the skip on.

    SCOPED TO THE MISLEADING PAIR, by decision: a layer carrying NEITHER field is NOT reported. It is
    simply unconfigured rather than misleading, and the existing covers WARN already speaks to it —
    whereas reporting every subject_globs-less layer would print forever for a project that deliberately
    wants no skipping, and a line that always prints trains the reader to ignore it (the same silent
    failure by another route).

    OPT-IN / fail-OPEN, but on the LAYER set rather than the rule-15 file universe: unlike its two
    siblings this check does NOT go through `_coverage_opt_in`, because what it reasons about is the
    DECLARED LAYERS, not load-bearing FILES. Gating it on a `coverage:` section would silence it on
    exactly the measured population. A repo with no carrier / no `verify.layers` declares no layer → []
    (the kernel's own repo has no yitc-ops.yaml, so this no-ops there). Malformed / unnamed layers are
    skipped rather than guessed at (zero false positives, the family's discipline)."""
    names: list = []
    for ly in _verify_layers(repo_root):
        if not isinstance(ly, dict):
            continue
        name = ly.get("layer")
        if not (isinstance(name, str) and name.strip()):
            continue        # an unnamed layer — nothing actionable to report; never guessed at
        # LIST-only, both fields: a SCALAR `covers: "src/**"` is malformed, and iterating it would walk
        # its CHARACTERS — every one a non-blank string, so a scalar would read as a declared glob list
        # (a false positive on `covers:`, a false SUPPRESSION on `subject_globs:`). A non-list is treated
        # as declaring nothing, the same fail-open direction as the unnamed-layer skip above.
        covers = [g for g in _glob_list(ly.get("covers")) if isinstance(g, str) and g.strip()]
        subjects = [g for g in _glob_list(ly.get("subject_globs")) if isinstance(g, str) and g.strip()]
        if covers and not subjects:
            names.append(name.strip())
    return sorted(names)


def _coverage_zero_glob_warnings(repo_root) -> list:
    """T-10497 (X-0357) — the report-only ZERO-RESOLVING GLOB check. Return the SORTED list of declared
    globs (`coverage.load_bearing` + every `verify.layers[].covers` + every `verify.layers[].boundary` —
    T-10513) that match NO file in the repo. A zero-resolving glob is almost always a mistake: it reads as a
    coverage/covers/boundary declaration while claiming nothing, and every consumer fails OPEN on it (an
    empty universe raises no orphan; an empty covers-set claims no surface; an empty boundary-set sees
    nothing) — so the mistake is invisible without this WARN. Report-only on the same exit-0 stderr channel
    as rules 15/16; NEVER a build failure (GRAPH «NOT a validation layer»).

    OPT-IN / fail-open by construction: a repo with no `yitc-ops.yaml` (the kernel's own) or no
    `coverage:`/`verify:` declaration declares no globs, so there is nothing to resolve → []."""
    zero: list = []
    _coverage_opt_in(repo_root, zero_globs=zero)                                    # load_bearing globs
    _coverage_glob_files(repo_root, _verify_layer_covers_globs(repo_root), zero_globs=zero)   # covers globs
    _coverage_glob_files(repo_root, _verify_layer_boundary_globs(repo_root), zero_globs=zero)  # boundary globs (T-10513)
    return sorted(set(zero))


def _partition_implements_warnings(warns: list) -> tuple[list, list]:
    """T-11343: split the stale-implements-anchor rows into (LIVE, FROZEN HISTORY) by the OWNING
    SPEC's status — the SINGLE classifier both render sites use, so the two reports cannot drift.

    LIVE  = the anchor is dead on a spec that STILL GOVERNS (`status: active` — the only normative
            status, GRAPH §What a spec is FOR). This is the actionable count, and it is the HEADLINE.
    FROZEN = the anchor sits on a non-active (superseded/retired/...) spec: an accurate record of what
            that spec implemented WHEN it governed, not a defect (the T-11340 owner decision — and why
            re-anchoring those specs is explicitly out of scope).

    This is a PARTITION, never a filter: `len(live) + len(frozen) == len(warns)` always, and BOTH
    buckets stay reportable. A counter that goes quiet is the failure this exists to prevent.

    FAIL-OPEN by construction: a row is FROZEN only when it carries a `spec_status` that is present
    AND != "active". A row with a missing/blank status classifies LIVE — a watchdog defaults LOUD, so
    an unknown status can never silence a row out of the headline.
    """
    frozen = [w for w in warns if (w.get("spec_status") or "") not in ("", "active")]
    live = [w for w in warns if (w.get("spec_status") or "") in ("", "active")]
    return live, frozen


def cmd_graph_build(args: argparse.Namespace, *, CANONICAL_DOCS, ENGINE_ROOT, REPO_ROOT, _append_event, _build_graph_built_payload, _is_consumer_build, _manifest_path, _print_binding_report, _regen_file_placement_manifest, _regen_handbook_read_order, _regen_placement_manifest, _regen_spec_code_map_manifest, _regen_manifest_managed_regions, _release_view_docs, _render_audience_views, _write_graph_index, _write_release_view, graph_build_index, write_text_atomic, _concern_surface_warnings=None) -> None:
    t0 = time.monotonic()   # T-0375: build wall (index build + write)
    index = graph_build_index()
    _write_graph_index(index)   # T-0365: JSON index + floor map via the single write helper
    # T-0671 + SPEC-0120: regenerate the read-order managed regions from the single carrier
    # HANDBOOK_READ_ORDER (SPEC-0007 §5b) across the AGENTS protocol FAMILY — AGENTS.md AND its split
    # parts (AGENTS-SESSIONS.md / AGENTS-PROTOCOL.md), any of which may carry a <!--GEN:read-order-->
    # region (the §Startup-phases arrow moved into a part). Globbing AGENTS*.md is future-proof for
    # further splits; `_regen_handbook_read_order` is idempotent + a no-op on a file with no region.
    # EXPLICIT-build only — NOT in _write_graph_index, so the land-time `_auto_rebuild_graph` never
    # writes AGENTS* (none is in _BOOKKEEPING_ALLOWLIST). A missing family (consumer build) → no-op.
    for _ag in sorted(REPO_ROOT.glob("AGENTS*.md")):
        _ag_text = _ag.read_text(encoding="utf-8")
        _ag_regen = _regen_handbook_read_order(_ag_text)
        if _ag_regen != _ag_text:
            write_text_atomic(_ag, _ag_regen)
    _write_audience_views(CANONICAL_DOCS=CANONICAL_DOCS, REPO_ROOT=REPO_ROOT,
                          _is_consumer_build=_is_consumer_build,
                          _render_audience_views=_render_audience_views,
                          write_text_atomic=write_text_atomic)
    # T-0890 (SPEC-0073 §5): regenerate the kernel-vs-self manifest §1 SPEC-classification managed
    # region from the class-default matrix + per-spec `travels:` markers. SAME placement as the AGENTS
    # read-order regen above — EXPLICIT-build only (the manifest ∉ _BOOKKEEPING_ALLOWLIST, so land's
    # `_auto_rebuild_graph` never writes it). Idempotent; the committed region is drift-locked by the suite.
    # T-12236: the §1/§2/§3 chain (T-0890 / T-0934 / T-9541) now lives in the single
    # `_regen_manifest_managed_regions` — LIFTED, not copied, because `land` re-derives the same three
    # regions on a MERGED tree. This call is byte-identical in effect to the block it replaces.
    _regen_manifest_managed_regions(index)
    # T-0866 (SPEC-0074 §6): regenerate the identity-agnostic release view — EXPLICIT-build-only (the
    # SAME placement as the AGENTS regen above; NOT in _write_graph_index, so land's _auto_rebuild_graph
    # never writes the large managed view). Engine-only — a consumer pins the released view, never builds it.
    # GUARDED on a COMPLETE handbook present (like the `if _ag.exists()` AGENTS-regen guard): a minimal /
    # partial repo (no handbook, e.g. a test sandbox) is tolerated — graph build never emits a PARTIAL
    # view (completeness is all-or-nothing); the explicit `graph release-view` verb + `_build_release_view`
    # still FAIL-HARD if asked to generate from an incomplete source set (audit-post F2).
    if not _is_consumer_build() and all((ENGINE_ROOT / d).exists() for d in _release_view_docs()):
        _write_release_view()
    counts = {k: len(v) for k, v in index.items() if not k.startswith("_")}
    errors = index.get("_parse_errors") or []
    _append_event("graph_built", None, _build_graph_built_payload(
        counts, errors, duration_ms=int((time.monotonic() - t0) * 1000),
        cache=LAST_INDEX_CACHE_STATE))   # T-11326: the result-cache state of the build just run
    print(f"graph/index.json: " + ", ".join(f"{k}={n}" for k, n in sorted(counts.items())))
    # T-0064: stale implements-anchor WARNINGS — report-not-block (D-0036). stderr, NO exit 2;
    # exit 2 stays reserved for fatal YAML parse_errors below.
    # T-11343: PARTITIONED by the owning spec's status — the LIVE count is the headline; the frozen-
    # history bucket is still RENDERED below it, never suppressed (a counter that goes quiet is the
    # failure this split exists to prevent). Both blocks stay on the same report-only exit-0 channel.
    warns = index.get("_implements_warnings") or []
    live_warns, frozen_warns = _partition_implements_warnings(warns)
    if live_warns:
        print(f"\nyitc-v2: {len(live_warns)} stale implements anchor(s) on ACTIVE specs "
              f"(report-only — not a build failure):", file=sys.stderr)
        for w in live_warns:
            print(f"  - {w['spec']}: {w['warn']}", file=sys.stderr)
    if frozen_warns:
        print(f"\nyitc-v2: {len(frozen_warns)} stale implements anchor(s) on non-active specs — frozen "
              f"history, an accurate record of what each implemented when it governed (T-11340; "
              f"report-only, and NOT re-anchorable):", file=sys.stderr)
        for w in frozen_warns:
            print(f"  - {w['spec']} [{w.get('spec_status') or 'unknown'}]: {w['warn']}", file=sys.stderr)
    # T-9324/SPEC-0088: file-granular implements/covers anchors (no #symbol) — the code-decompose
    # rule, REPORT-ONLY (same exit-0 stderr channel; never exit 2 — GRAPH «NOT a validation layer»).
    fg = index.get("_file_granular_warnings") or []
    if fg:
        print(f"\nyitc-v2: {len(fg)} file-granular anchor(s) — decompose to <file>#<symbol> "
              f"(SPEC-0088, report-only — not a build failure):", file=sys.stderr)
        for w in fg:
            print(f"  - {w['node']} ({w['kind']}): {w['warn']}", file=sys.stderr)
    # T-0213: possibly-stale (resolved but drifted) anchors — report-only, same exit-0 channel.
    fresh = index.get("_freshness_warnings") or []
    if fresh:
        print(f"\nyitc-v2: {len(fresh)} possibly-stale spec(s) (code drifted since spec last-touch — review, not a build failure):",
              file=sys.stderr)
        for w in fresh:
            print(f"  - {w['spec']}: {w['warn']}", file=sys.stderr)
    # T-9629: dangling spec→spec `cites:` — a spec whose well-formed bare SPEC cite (`^SPEC-\d{4,}$`) is
    # NOT in the corpus. REPORT-ONLY (same exit-0 stderr channel; NO exit 2 — GRAPH «NOT a validation
    # layer»). Parity with the implements dead-anchor report above; the FACT-of-existence sweep (not
    # legality) is computed at index-build as `cites_unresolved` on each spec node. Before this, a cite
    # to a nonexistent spec id passed `graph build` silently (the real incident: SPEC-0001 cites the
    # nonexistent SPEC-0010). Unlike the scenario `cites` gate (T-1100, fatal on a building
    # contract), a spec cite is an informational any→any reference, so this is report-only.
    sc = index.get("_spec_cites_warnings") or []
    if sc:
        print(f"\nyitc-v2: {len(sc)} dangling spec cites reference(s) — a cited SPEC does not exist in "
              f"the corpus (T-9629, report-only — not a build failure):", file=sys.stderr)
        for w in sc:
            print(f"  - {w['spec']}: cited spec does not exist: {w['anchor']}", file=sys.stderr)
    # T-0230 (Part I-A): bidirectional binding-completeness report — report-not-block (same exit-0
    # stderr channel as the anchor warnings). Surfaces unmapped gating verbs + dangling specs so the
    # binding field cannot rot silently (element #4 — the self-healing safety net).
    _print_binding_report(index.get("binding_report") or {})
    # T-9641 (SPEC-0152 rule 15): B5 COVERAGE-ADMISSION — load-bearing surfaces declared in
    # yitc-ops.yaml `coverage.load_bearing` that are NEITHER spec-covered (an `implements` edge) NOR
    # validly `admitted:` are candidate NEW orphans. REPORT-ONLY (same exit-0 stderr channel; GRAPH
    # «NOT a validation layer»). OPT-IN — no-ops unless the project declares `coverage.load_bearing`
    # (the kernel's own repo has no yitc-ops.yaml → silent).
    cov_orphans = _coverage_admission_warnings(REPO_ROOT, index.get("code_to_specs") or {})
    if cov_orphans:
        print(f"\nyitc-v2: {len(cov_orphans)} load-bearing surface(s) NEITHER spec-covered NOR admitted "
              f"in yitc-ops.yaml `coverage:` — candidate new orphan(s) (T-9641/SPEC-0152 rule 15, "
              f"report-only — not a build failure):", file=sys.stderr)
        for s in cov_orphans:
            print(f"  - {s}", file=sys.stderr)
    # T-9718 (SPEC-0152 rule 16): VERIFY-LAYER COVERAGE — load-bearing surfaces (the rule-15
    # `coverage.load_bearing` universe) covered by NO declared `verify.layers` layer's `covers:` glob and
    # not validly `admitted:` are candidate SILENTLY-UNTESTED layers (X-0140). REPORT-ONLY (same exit-0
    # stderr channel; GRAPH «NOT a validation layer»). OPT-IN — no-ops unless the project declares BOTH
    # `coverage.load_bearing` AND a non-empty `verify.layers` (reuses the rule-15 coverage shape).
    ver_uncovered = _verify_layer_coverage_warnings(REPO_ROOT)
    if ver_uncovered:
        print(f"\nyitc-v2: {len(ver_uncovered)} load-bearing surface(s) present in code but covered by NO "
              f"declared verify layer in yitc-ops.yaml `verify.layers` — candidate silently-untested "
              f"layer(s) (T-9718/SPEC-0152 rule 16, report-only — not a build failure):", file=sys.stderr)
        for s in ver_uncovered:
            print(f"  - {s}", file=sys.stderr)
    # T-10513 (SPEC-0152 rule 16 amend, X-0375): OUTSIDE-EVERY-BOUNDARY — load-bearing surfaces (the
    # rule-15 `coverage.load_bearing` universe) that fall OUTSIDE every declared `verify.layers[].boundary`
    # glob, i.e. code NO verify layer's harness can even SEE (a hermetic mount blind to scripts/). The
    # VISIBILITY analog of the covers WARN above: covers asks "verified?", boundary asks "reachable at all?".
    # REPORT-ONLY (same exit-0 stderr channel; GRAPH «NOT a validation layer»). OPT-IN — no-ops unless the
    # project declares BOTH `coverage.load_bearing` AND ≥1 layer `boundary:` (else everything is 'outside').
    ver_unseen = _verify_layer_boundary_warnings(REPO_ROOT)
    if ver_unseen:
        print(f"\nyitc-v2: {len(ver_unseen)} load-bearing surface(s) present in code but OUTSIDE every "
              f"declared verify-layer boundary in yitc-ops.yaml `verify.layers[].boundary` — no harness can "
              f"even SEE them, so they are un-verified by silence (T-10513/SPEC-0152 rule 16, X-0375, "
              f"report-only — not a build failure):", file=sys.stderr)
        for s in ver_unseen:
            print(f"  - {s}", file=sys.stderr)
    # T-11130 (SPEC-0152 rule 16 subject_globs sub-rule, T-10571): NEVER-SKIPS — a verify layer that
    # declares `covers:` but NO `subject_globs:` can never be skipped by subject scoping, so every land
    # pays for it whatever the diff touches. The THIRD question in this family: covers asks "verified?",
    # boundary asks "reachable at all?", this asks "will this layer ever SKIP?". Scoped to the MISLEADING
    # pair — a layer with NEITHER field is unconfigured, not misleading, and is deliberately NOT reported
    # (a line that always prints trains the reader to ignore it). REPORT-ONLY (same exit-0 stderr channel;
    # GRAPH «NOT a validation layer»). OPT-IN — no-ops unless the project declares `verify.layers`.
    ver_never_skip = _verify_layer_skip_off_warnings(REPO_ROOT)
    if ver_never_skip:
        print(f"\nyitc-v2: {len(ver_never_skip)} verify layer(s) in {REPO_ROOT.name} declare `covers:` but no "
              f"`subject_globs:` in yitc-ops.yaml — they can NEVER be skipped, so every land runs them "
              f"whatever the diff touches (T-11130/SPEC-0152 rule 16, report-only — not a build failure):",
              file=sys.stderr)
        for ly in ver_never_skip:
            print(f"  - {ly}", file=sys.stderr)
    # T-10497 (X-0357): ZERO-RESOLVING GLOBS — a declared `coverage.load_bearing` / `verify.layers[].covers`
    # glob that matches NO file. It reads as a declaration but claims nothing, and both consumers above fail
    # OPEN on it (empty universe → no orphans; empty covers-set → no claimed surface), so without this WARN
    # the mistake is invisible (boomrocket shipped 3 such layers). REPORT-ONLY (same exit-0 stderr channel;
    # GRAPH «NOT a validation layer»). OPT-IN — a repo declaring no globs has nothing to resolve.
    zero_globs = _coverage_zero_glob_warnings(REPO_ROOT)
    if zero_globs:
        print(f"\nyitc-v2: {len(zero_globs)} declared glob(s) in yitc-ops.yaml `coverage:`/`verify.layers[].covers` "
              f"resolve to ZERO files — the declaration claims nothing (T-10497/X-0357, report-only — not a "
              f"build failure):", file=sys.stderr)
        for g in zero_globs:
            print(f"  - {g}", file=sys.stderr)
    # T-10036 (SPEC-0128 Rule 2, constraint 3): the concern REGISTRY↔surface + hook consistency WARNs —
    # a registry concern whose carrier section is absent from the ops-carrier surface, and missing / orphan
    # / duplicate shape-hooks (each hook from EXACTLY one concern block). REPORT-ONLY (same exit-0 stderr
    # channel; GRAPH «NOT a validation layer»). Injected by the host (reads init's live surface +
    # implemented-hook set); None in a sandbox that does not wire it → skip. Silent on the real leg-[A]
    # build (empty corpus registry + empty hook set); fires on synthetic fixtures + real drift once concerns
    # migrate. The registry iterates KNOWN entries only — the hard non-whitelist invariant (owner constraint).
    concern_warns = _concern_surface_warnings(index.get("specs") or {}) if _concern_surface_warnings else []
    if concern_warns:
        print(f"\nyitc-v2: {len(concern_warns)} concern registry↔surface / hook inconsistency(ies) "
              f"(T-10036/SPEC-0128, report-only — not a build failure):", file=sys.stderr)
        for w in concern_warns:
            print(f"  - {w['kind']}: {w['detail']}", file=sys.stderr)
    # T-1047/T-1049: scenario `covers:` anchors that don't resolve. The split is by the DERIVED
    # `computed_status` (SPEC-0076 §6b): a `draft` (or `retired`) scenario stays REPORT-ONLY (graph
    # is not a validation layer — exploratory/pre-binding paths are exempt); a `building`/`live`
    # scenario's dangling anchor is a write-time HARD ERROR (the T-1049 FATAL block below). So the
    # report-only print here fires ONLY for the EXEMPT (non-building) scenarios — a building
    # dangling covers is reported once, as the FATAL, never twice.
    scen = index.get("scenarios") or {}
    cov = [w for w in (index.get("_covers_warnings") or [])
           if (scen.get(w["scenario"], {}).get("computed_status") != "building")]
    if cov:
        print(f"\nyitc-v2: {len(cov)} unresolved scenario covers anchor(s) on EXEMPT (draft/retired) "
              f"scenarios (report-only — not a build failure):", file=sys.stderr)
        for w in cov:
            print(f"  - {w['scenario']}: {w['warn']}", file=sys.stderr)
    # T-1049 (SPEC-0076 §6b): broken-reference write-time HARD ERROR — a `building`/`live` scenario
    # (one declaring concrete anchors) whose `covers` anchor does NOT resolve fails like a broken
    # reference / type error. FACT of non-resolution ONLY — NOT transition legality (a
    # resolvable-but-FSM-forbidden case is never flagged; GRAPH §"NOT a validation layer"). Scoped to
    # building (draft exempt) so the gate can only ever be RIGHT (zero false-positive). Mirrors
    # the adjacent `_scenario_status_violations` FATAL reject (T-1047). SCOPE (T-1049 card =
    # concrete-anchor claim): the `covers` edge is the concrete-anchor carrier resolved against the
    # SAME real-file `<file>#<symbol>` address space `implements` uses (_resolve_implements_anchor) —
    # always resolvable on a full build, hence zero-false-positive. The §6b "or a cited SPEC does not
    # exist" sub-case is NOT folded in here: resolving `cites` against the in-index specs map
    # false-positives on a PARTIAL-corpus build (the index can be built scenarios-with-empty-specs),
    # which would violate the same zero-false-positive line; a dangling SPEC cite already SURFACES by
    # forcing `computed_status` to `building` (a missing cited spec fails closed, T-1048), and a full
    # cites-resolution check belongs with complete-corpus tooling, not this write-time anchor gate.
    broken = []
    for sid in sorted(scen):
        s = scen[sid]
        if s.get("computed_status") != "building":
            continue
        bad_covers = list(s.get("covers_unresolved") or [])
        if bad_covers:
            broken.append((sid, s.get("computed_status"), bad_covers))
    if broken:
        n = sum(len(bc) for _, _, bc in broken)
        print(f"\nyitc-v2: {n} broken scenario covers reference(s) on {len(broken)} building "
              f"scenario(s) — a declared concrete anchor does not resolve (SPEC-0076 §6b — FACT of "
              f"non-resolution, NOT transition legality):", file=sys.stderr)
        for sid, cs, bad_covers in broken:
            for a in bad_covers:
                print(f"  - {sid} ({cs}): covers anchor does not resolve: {a}", file=sys.stderr)
        sys.exit(2)
    # T-1100 (SPEC-0076 §6b — the "or a cited SPEC does not exist" sub-case split from T-1049): broken
    # `cites` reference write-time HARD ERROR — a `building`/`live` scenario whose well-formed SPEC cite
    # (`^SPEC-\d{4,}$`) is NOT in the specs corpus fails like a broken reference. FACT of non-existence
    # ONLY — NOT legality (a cite to a draft/superseded/retired spec that EXISTS is fine; only a
    # nonexistent id fails). ONLY bare SPEC ids are resolved (computed as `cites_unresolved` at index-
    # build) — a section ref / plan slug / task id / decision id is NEVER resolved. Scoped to building/
    # live (draft/retired exempt) so the gate can only ever be RIGHT (zero false-positive on a full
    # corpus). Mirrors the adjacent T-1049 covers FATAL; placed AFTER it (covers — the concrete-anchor
    # class — reported first; either firing exits 2).
    broken_cites = []
    for sid in sorted(scen):
        s = scen[sid]
        if s.get("computed_status") != "building":
            continue
        bad_cites = list(s.get("cites_unresolved") or [])
        if bad_cites:
            broken_cites.append((sid, s.get("computed_status"), bad_cites))
    if broken_cites:
        n = sum(len(bc) for _, _, bc in broken_cites)
        print(f"\nyitc-v2: {n} broken scenario cites reference(s) on {len(broken_cites)} building "
              f"scenario(s) — a cited SPEC does not exist in the corpus (SPEC-0076 §6b — FACT of "
              f"non-existence, NOT legality):", file=sys.stderr)
        for sid, cs, bad_cites in broken_cites:
            for c in bad_cites:
                print(f"  - {sid} ({cs}): cited spec does not exist: {c}", file=sys.stderr)
        sys.exit(2)
    # T-1047 (audit-pre F1): non-helper scenarios/*.md lacking an explicit `scenario:` key — surfaced
    # LOUDLY so canonical content is never silently invisible (report-only — not a hard gate).
    mk = index.get("_scenario_missing_key") or []
    if mk:
        print(f"\nyitc-v2: {len(mk)} scenarios/*.md missing the required `scenario:` key — NOT indexed "
              f"(report-only; add `scenario:` or rename with a leading `_`):", file=sys.stderr)
        for f in mk:
            print(f"  - {f}", file=sys.stderr)
    # T-9343 (SPEC-0090): non-helper lessons/*.md lacking the required `lesson:` key — surfaced LOUDLY
    # so local-craft content is never silently invisible (report-only — not a hard gate; mirrors the
    # scenario missing-key report above). A MALFORMED frontmatter (unparseable YAML) is the separate
    # exit-2 parse-error gate below (SPEC-0090 §6 storage-FORMAT reject).
    lmk = index.get("_lesson_missing_key") or []
    if lmk:
        print(f"\nyitc-v2: {len(lmk)} lessons/*.md missing the required `lesson:` key — NOT indexed "
              f"(report-only; add `lesson:` or rename with a leading `_`):", file=sys.stderr)
        for f in lmk:
            print(f"  - {f}", file=sys.stderr)
    # T-1047: illegal STORED scenario status (storage-FORMAT contract, SPEC-0076 §3 — only retired|absent
    # legal; draft|building are a computed view, never stored — and the T-11004-retired `live` stays
    # rejected here too, it was never legal to store). FATAL — the deterministic reject.
    sv = index.get("_scenario_status_violations") or []
    if sv:
        print(f"\nyitc-v2: {len(sv)} scenario(s) with an illegal STORED status (only `retired` or absent "
              f"is legal — draft|building are a computed view, SPEC-0076 §3):", file=sys.stderr)
        for v in sv:
            print(f"  - {v['path']}: scenario {v['scenario']!r} stores status {v['got']!r}", file=sys.stderr)
        sys.exit(2)
    # T-0021: surface silent YAML parse failures (was silent {} swallow → adoption gap) — FATAL
    if errors:
        print(f"\nyitc-v2: {len(errors)} YAML parse failure(s) detected:", file=sys.stderr)
        for e in errors:
            print(f"  - {e['path']}: {e['error'][:200]}", file=sys.stderr)
        sys.exit(2)


def cmd_graph_conformance(args: argparse.Namespace, *, BINDING_RESIDENCY_TOKENS, BINDING_VERB_SURFACES, CANONICAL_DOCS, PLAN_STAGE_SEQUENCE, REPO_ROOT, SPECS_DIR, STAGE_AXIS_NAMES, _activation_checklist_drift, _audience_views_drift, _build_binding_views, _concern_registry_drift, _born_ops_drift, _derived_routing_backing, _die, _floor_map_drift, _handbook_binding_mirror_underlist, _handbook_routing_duplication, _handbook_verb_drift, _live_cli_verbs, _one_source_delivery_check, _plan_delivery_gating_stages, _read_order_drift, _read_yaml, _release_spec_slice_violations, _release_view_drift, _relocated_gating_stages, _stage_bundle_coverage_violations, _unmarked_cut_card_flags, _cross_dangling_resolved, _phantom_activation_owners) -> None:
    """Binding-coverage conformance self-test — a DEDICATED, VALIDATING surface (T-0284, plan §8 "ONE
    graph self-test"). Asserts every ACTIVE spec carries a VALID binding token and exits RED (non-zero)
    on any gap. This is deliberately SEPARATE from `graph build`: `graph build` stays report-only /
    non-failing on binding content (GRAPH non-goal "the graph is NOT a validation layer"), so the
    fail-on-coverage verdict lives HERE, not folded into the build.

    A FRESH spec load (not the possibly-stale committed index) → list-validate the `binding:` shape
    (malformed = a non-list, never iterated char-by-char) → reuse `_build_binding_views` (the SINGLE
    canonical derivation, P5) for dangling (active + empty binding) + unknown (a token that is not a
    verb surface, not a residency marker, and not a valid `stage-entry:<STAGE>`). Active-only — a
    proposed/superseded spec governs nothing. RED iff ANY of {dangling, unknown, malformed} is non-empty
    — a single bad token makes the spec RED even alongside a co-present valid one (the gap is in
    unknown/malformed regardless of the good token)."""
    import yaml
    if not SPECS_DIR.is_dir():
        _die("graph conformance: specs/ not found")
    specs: dict = {}
    malformed: list = []
    # T-10842: CONNECT the canonical reader's error channel at this sweep. `state.load_path` returns {}
    # on a YAML parse failure, so WITHOUT this list a CORRUPT spec is indistinguishable from an empty or
    # absent one: it falls out at `if not sid: continue`, never reaches `n_active`, and this verdict then
    # prints GREEN over a corpus it did not fully read. The channel is the SAME one `graph build` already
    # passes (its `parse_errors`, → exit 2) — extending an existing channel at an existing call site, no
    # new mechanism. Per-file + host-pure like the malformed-binding check, so it sits in the ALWAYS
    # branch (NOT canonical-corpus-guarded): a partial sandbox corpus is still a corpus whose corruption
    # invalidates the verdict over it, and a clean sandbox yields no entries, so it cannot false-RED.
    parse_errors: list = []
    for p in state.scan_specs(SPECS_DIR):   # SPEC-* glob excludes _template.yaml
        d = _read_yaml(p, errors=parse_errors)
        sid = d.get("id")
        if not sid:
            continue
        raw = d.get("binding")
        if raw is None or isinstance(raw, list):
            binding = sorted(str(b) for b in (raw or []))
        else:                                          # a scalar/mapping binding is malformed — treat as
            binding = []                               # unbound, NEVER iterate it char-by-char (audit-post
            if d.get("status") == "active":            # finding 2 of T-0230); active-only is the verdict scope.
                malformed.append({"spec": sid, "got": type(raw).__name__})
        # T-9411: include init_concern — _activation_checklist_drift renders the activation checklist over
        # these declarations; omitting the field here false-REDs activation-checklist-drift the moment any
        # real concern is declared (the first real seed, SPEC-0094, surfaced this latent T-9410 gap).
        specs[sid] = {"title": d.get("title", ""), "status": d.get("status", ""),
                      "implements": sorted(d.get("implements") or []), "binding": binding,
                      # T-10036: include init_concern AND concern — _activation_checklist_drift /
                      # _concern_registry_drift render over these declarations; omitting a field here
                      # would false-RED the drift the moment any real concern is declared (same latent
                      # gap the T-9411 init_concern inclusion above closed).
                      "init_concern": d.get("init_concern"), "concern": d.get("concern")}
    _, floor_trigger_map, report = _build_binding_views(specs)
    dangling = report.get("dangling_specs") or []
    unknown = report.get("unknown_tokens") or []
    # malformed specs would ALSO show as dangling (empty binding) — display them under malformed only.
    mal_ids = {m["spec"] for m in malformed}
    dangling = [s for s in dangling if s not in mal_ids]
    n_active = sum(1 for s in specs.values() if s.get("status") == "active")
    # T-0295: the one-source DELIVERY invariant (path-B core). The per-spec structural check runs ALWAYS
    # (PURE, sandbox-safe, over NON-RETIRED specs). The corpus-level stage-bundle-coverage check runs ONLY
    # on the canonical corpus — a partial test sandbox lacks the relocated gating stages' specs and would
    # false-RED. REPO_ROOT + SPECS_DIR are both __file__-derived, so this equality holds for ANY real
    # checkout (main OR worktree, even relocated — they relocate together) and is false ONLY when a test
    # monkeypatches SPECS_DIR alone to a sandbox dir = exactly the intended discrimination (audit-pre F0).
    delivery_viol = _one_source_delivery_check(specs)
    canonical_corpus = SPECS_DIR.resolve() == (REPO_ROOT / "specs").resolve()
    bundle_viol = _stage_bundle_coverage_violations(report) if canonical_corpus else []
    # T-0300 corpus-level checks (REPORT-AT-LAND, never a write-path gate — non-goal #7 / GRAPH
    # not-a-validation-layer / D-0036). Canonical-corpus-guarded like bundle_viol: they read the
    # REPO_ROOT handbook files + the committed floor map, which only the real corpus has, so a partial
    # test sandbox (monkeypatched SPECS_DIR) skips them and never false-REDs.
    dup_viol: list = []
    drift_viol: list = []
    ac_viol: list = []
    cr_viol: list = []
    cm_viol: list = []
    bo_viol: list = []
    verb_viol: list = []
    underlist_viol: list = []
    read_order_viol: list = []
    av_viol: list = []
    rv_viol: list = []
    if canonical_corpus:
        stage_to_specs = report.get("stage_to_specs") or {}
        handbook_docs = {n: (REPO_ROOT / n).read_text(encoding="utf-8")
                         for n in CANONICAL_DOCS if (REPO_ROOT / n).exists()}
        dup_viol = _handbook_routing_duplication(floor_trigger_map, stage_to_specs, handbook_docs)
        drift_viol = _floor_map_drift(floor_trigger_map, specs)
        # T-9410 (SPEC-0096): the committed activation-checklist.md must equal a fresh render over the
        # live `init_concern` declarations — the sibling of the floor-map drift check (REPORT-AT-LAND).
        ac_viol = _activation_checklist_drift(specs)
        # T-10036 (SPEC-0128): the committed concern-registry.json must equal a fresh render over the live
        # `concern:` declarations — the JSON sibling of the activation-checklist drift check (REPORT-AT-LAND).
        cr_viol = _concern_registry_drift(specs)
        # T-10041 (SPEC-0128 Rule 1, audit-pre finding): a present-but-MALFORMED `concern:` declaration
        # (non-mapping value/element, or a block missing a non-empty `section`) is a conformance RED — a
        # STORAGE-FORMAT contract check (the GRAPH scenario-status carve-out), so a typo'd concern cannot
        # silently drop from the registry. Pure over `specs` (no host state) → called directly, not injected.
        cm_viol = _concern_malformed_violations(specs)
        # T-10038 (SPEC-0128 Rule 2 + born decision (i)): the committed graph/born-ops.yaml must equal a
        # fresh render over the live concern `born:`/`born_order:` declarations — the born sibling of the
        # concern-registry drift check (REPORT-AT-LAND). The P8 adoption probe for leg [C].
        bo_viol = _born_ops_drift(specs)
        # T-0671: the handbook read-order surfaces must equal render() from HANDBOOK_READ_ORDER
        # (SPEC-0007 §5b). REPORT-AT-LAND, same doctrine as the checks above. This is the
        # non-divergence backstop — a divergent AGENTS RED-fails here → the canonical-GREEN
        # land-verify test fails → land aborts, so it cannot land.
        read_order_viol = _read_order_drift(handbook_docs)
        # T-10025 (SPEC-0127 §3): the committed audience-scoped seed views (worker seed / controller
        # supplement / worker-startup inventory) must each equal a fresh render over the seed-doc AUDIENCE
        # markers — the sibling of the floor-map / read-order drift checks, REPORT-AT-LAND. Fail-closed on
        # a malformed marker. Engine-only (the check no-ops under -C).
        av_viol = _audience_views_drift(handbook_docs)
        # T-0530: prose-drift checks (report-at-land, SAME doctrine as the T-0300 pair above) — a named
        # CLI verb the parser hard-rejects, and a binding-map MIRROR that under-lists a backed spec.
        verb_viol = _handbook_verb_drift(handbook_docs, _live_cli_verbs())
        backing = _derived_routing_backing(floor_trigger_map, stage_to_specs)
        underlist_viol = _handbook_binding_mirror_underlist(handbook_docs, backing, set(STAGE_AXIS_NAMES))
        # T-0866 (SPEC-0074 §6): the committed release-view/ must equal the freshly re-derived view —
        # the peer of _floor_map_drift, REPORT-AT-LAND (canonical-corpus + engine-only guarded).
        rv_viol = _release_view_drift()
        # T-0883 (SPEC-0073 §8): the active-only export-slice guard — no NON-active spec may resolve to
        # the kernel placement realm (= would leak into the export slice). REPORT-AT-LAND, same doctrine.
        rv_viol += _release_spec_slice_violations()
    # T-0685: SPEC-0070 §5 cut-membership advisory — REPORT-ONLY, NEVER part of the RED/GREEN verdict
    # (does not affect sys.exit). Surfaces non-terminal cards citing a plan being cut (`decomposition`)
    # that lack the `decomposed_from` marker, so a forgotten cut-membership mark is visible at land.
    # Canonical-corpus-guarded like the other corpus-level checks (a partial test sandbox skips it).
    cut_marker_flags = _unmarked_cut_card_flags() if canonical_corpus else []
    if cut_marker_flags:
        print("ADVISORY (SPEC-0070 §5, report-only — not a conformance failure): card(s) cite a plan being "
              "cut (`decomposition`) but lack the `decomposed_from` marker — mark each true cut card via "
              "`task file --decomposed-from <plan>` (or confirm it is a deliberate informational cite):")
        for f in cut_marker_flags:
            print(f"  - {f['task']} cites cut plan {f['plan']!r} without decomposed_from")
    # T-10221 (SPEC-0085): report-only advisory — coordination items still `picked` in OUR court whose
    # resolution rode a non-task axis (a spec-activation / plan-realize prose-cite), which the close-side
    # auto-`cross_done` (task `resolves_cross` only) never reaches, so the item dangles. REPORT-ONLY,
    # NEVER part of the RED/GREEN verdict (does not affect sys.exit) — prose citation is overloaded, so
    # this prompts a manual `cross done`, never an auto-mutation of the shared log (CHARTER §6). Canonical-
    # corpus-guarded like cut_marker_flags (a partial test sandbox lacks the real corpus + log).
    cross_dangling = _cross_dangling_resolved() if canonical_corpus else []
    if cross_dangling:
        print("ADVISORY (SPEC-0085, report-only — not a conformance failure): coordination item(s) still "
              "`picked` in our court are prose-cited by an ACTIVE spec / REALIZED plan (their resolution "
              "rode the spec-activate / plan-realize axis, which the close-side auto-`cross_done` never "
              "reaches) — verify each resolved and run `bin/yitc-v2 cross done <id>`:")
        for f in cross_dangling:
            print(f"  - {f['cross']} prose-cited by resolved {', '.join(f['resolvers'])} but still picked")
    # T-10590 (SPEC-0005 §4/§5): report-only advisory — `proposed` spec(s) whose `activation_owner_task`
    # names a task with no local card. Stranded by construction: a `proposed` spec governs nothing (§4)
    # and `proposed → active` is written ONLY by the owner's `task close`, which can never run for a
    # phantom owner (X-0437 — a v1→v2 import stranded 36 specs on nonexistent T-9660/T-9661). REPORT-ONLY,
    # NEVER part of the RED/GREEN verdict (does not affect sys.exit): the terminal route is a SEMANTIC
    # choice this check cannot synthesize, so it surfaces the state and names both routes (SPEC-0005 §7
    # prevention-by-discipline-not-a-gate / GRAPH §"NOT a validation layer" / CHARTER non-goal #7 — the
    # same Option-A doctrine the T-0455 dangling-activated-spec WARN settled on a full consult). An ABSENT
    # owner is NEVER flagged (§5 grandfathering: pre-doctrine specs are valid, no retroactive backfill).
    # Canonical-corpus-guarded like the other corpus-level advisories (a partial test sandbox skips it);
    # deliberately NOT consumer-exempt — the migrated consumer corpus is where this class lives.
    phantom_owners = _phantom_activation_owners() if canonical_corpus else []
    if phantom_owners:
        print("ADVISORY (SPEC-0005 §4/§5, report-only — not a conformance failure): `proposed` spec(s) name "
              "an `activation_owner_task` that does not resolve to a local task — they govern nothing and "
              "cannot activate (no owner close can ever fire). Drive each to a TERMINAL honest status: "
              "either ACTIVATE it (retarget `activation_owner_task` to a REAL local task carrying an "
              "adoption probe, which activates it at that task's `task close`) or RETIRE/WITHDRAW it "
              "(`spec edit <SPEC>`):")
        for f in phantom_owners:
            print(f"  - {f['spec']} owned by {f['owner']} (no such local task)")
    if (parse_errors or dangling or unknown or malformed or delivery_viol or bundle_viol or dup_viol
            or drift_viol or ac_viol or cr_viol or cm_viol or bo_viol or verb_viol or underlist_viol
            or read_order_viol or av_viol or rv_viol):
        print("CONFORMANCE: RED — delivery-coverage gap(s): every active spec must carry a valid binding "
              "token, and a stage-bound action must have exactly ONE delivery source.")
        # T-10842: rendered FIRST — an unreadable corpus subsumes every other finding computed over it.
        # A spec that does not parse was SKIPPED by the sweep above, so its binding coverage is UNKNOWN,
        # not clean: it cannot be reported as dangling/unknown/malformed because it was never read.
        for pe in parse_errors:
            print(f"  - corrupt spec file {pe['path']}: {pe['error']} "
                  "(this file did NOT parse, so it was SKIPPED by the coverage sweep — its binding "
                  "coverage is unknown, not clean; fix the YAML, then re-run)")
        if dangling:
            print(f"  - missing binding (active spec, no token): {', '.join(dangling)}")
        for u in unknown:
            print(f"  - invalid binding token in {u['spec']}: {u['token']!r} "
                  f"(allowed verbs: {', '.join(BINDING_VERB_SURFACES)}; residency: "
                  f"{', '.join(sorted(BINDING_RESIDENCY_TOKENS))}; or stage-entry:<STAGE> with "
                  f"<STAGE> in {{{', '.join(STAGE_AXIS_NAMES)}}}; or plan-stage-entry:<PLAN_STAGE> "
                  f"with <PLAN_STAGE> in {{{', '.join(PLAN_STAGE_SEQUENCE)}}})")
        for m in malformed:
            print(f"  - malformed binding in {m['spec']}: expected a YAML list, got {m['got']}")
        for d in delivery_viol:
            print(f"  - {d['kind']} in {d['spec']}: {d['detail']}")
        for b in bundle_viol:
            _axis = "plan-stage-entry" if b["kind"] == "plan-stage-no-bundle" else "stage-entry"
            _what = "a plan delivery gating-stage" if b["kind"] == "plan-stage-no-bundle" else "a relocated gating verb"
            print(f"  - {b['kind']}: stage {b['stage']!r} ({_what}) has no bound spec "
                  f"(expected ≥1 spec on {_axis}:{b['stage']})")
        for d in dup_viol:
            print(f"  - {d['kind']}: {d['file']}:{d['line']} asserts routing surface {d['surface']!r} "
                  f"with spec(s) {', '.join(d['specs'])}, none backed by the binding-derived map "
                  f"(stale/divergent handbook routing — the single carrier is the per-spec binding:)")
        for d in drift_viol:
            print(f"  - {d['kind']}: {d['detail']}")
        for d in ac_viol:
            print(f"  - {d['kind']}: {d['detail']}")
        for d in cr_viol:
            print(f"  - {d['kind']}: {d['detail']}")
        for d in cm_viol:
            print(f"  - {d['kind']}: {d['detail']}")
        for d in bo_viol:
            print(f"  - {d['kind']}: {d['detail']}")
        for v in verb_viol:
            print(f"  - {v['kind']}: {v['file']}:{v['line']} names CLI verb {v['verb']!r}, which the "
                  f"parser does not accept (no live `bin/yitc-v2 {v['verb']}` + no `(deferred)` marker "
                  f"— correct the prose or mark it deferred)")
        for u in underlist_viol:
            print(f"  - {u['kind']}: {u['file']}:{u['line']} mirrors the binding map for stage "
                  f"{u['surface']!r} but omits backed spec(s) {', '.join(u['missing'])} "
                  f"(the prose mirror drifted from the binding-derived map — add the missing spec(s))")
        for r in read_order_viol:
            print(f"  - {r['kind']}: {r['detail']}")
        for r in av_viol:
            print(f"  - {r['kind']}: {r['detail']}")
        for r in rv_viol:
            print(f"  - {r['kind']}: {r['detail']}")
        sys.exit(1)
    # T-10842: the GREEN line states the corpus PARSED CLEAN alongside the binding coverage. Arming the
    # exit code while leaving this sentence unqualified would fix the verdict and keep the claim that
    # misled — the "all N active spec(s)" count is only meaningful once every file was actually read.
    print(f"CONFORMANCE: GREEN — every spec file parsed; all {n_active} active spec(s) carry a valid "
          "binding token; the one-source "
          + (f"delivery invariant holds, all {len(_relocated_gating_stages())} relocated gating stages "
             f"+ all {len(_plan_delivery_gating_stages())} plan delivery stages (incl. decomposition) "
             "carry a bundle, the handbook routing matches the binding-derived map, the committed "
             "floor trigger-map is in sync, every CLI verb named in the handbook resolves to a live "
             "parser, and no binding-map mirror under-lists a backed spec." if canonical_corpus else
             "delivery invariant holds (per-spec; corpus-level checks skipped — partial corpus)."))


def cmd_graph_query(args: argparse.Namespace, *, GRAPH_PATH, REPO_ROOT, _anchor_file, _carve_out_selection, _cross_self, _die, _emit_node_list, _engine_index, _find_error_yaml, _find_spec_path, _graph_query_projected, _graph_query_recurring, _is_consumer_build, _kernel_content_file, _list_views, _load_index_as_of, _node_source_path, _parse_iso_utc, _read_yaml, _report_graft_parse_errors, _run_view, _with_live_nodes) -> None:
    import yaml
    # T-9363 (SPEC-0092): --kernel = the kernel-prefixed retrieval path. It composes ONLY with a
    # spec-id or error-id point-lookup (the X-0038 / X-0583 kernel/consumer collision has no meaning for
    # --type / whole-graph views / a view-name / a missing id) — fail closed loudly on any other form,
    # BEFORE any work. T-10748 widened the accepted id set from SPEC-only to SPEC + E (see the branch
    # below); the composition bound itself is unchanged.
    want_kernel = getattr(args, "kernel", False)
    if want_kernel:
        if (args.type or getattr(args, "projected", False) or getattr(args, "carve_out", False)
                or getattr(args, "recurring", False) or getattr(args, "as_of", None)):
            _die("--kernel composes ONLY with a spec-id or error-id point-lookup — not with "
                 "--type / --projected / --carve-out / --recurring / --as-of (SPEC-0092)")
        if not args.id:
            _die("--kernel requires a SPEC or E id (e.g. `graph query --kernel SPEC-0014` / "
                 "`graph query --kernel E-0002`) — SPEC-0092")
    as_of = getattr(args, "as_of", None)
    if as_of:
        index = _load_index_as_of(as_of)          # T-0088: historical rule-set (pure read over git)
        # T-0491: a historical `--as-of` snapshot is a FAITHFUL point-in-time REPLAY of the committed
        # index's OWN sections (a pre-cut snapshot still carries tasks/decisions/audits/events/commits;
        # a post-cut snapshot does not). NEVER graft current YAML onto it — that would report present
        # task state against a past graph (D-0046). So the live-node graft below is applied to the
        # CURRENT index ONLY.
    else:
        # T-0491: re-source the task/decision node maps from authored YAML for the CURRENT-index readers
        # (carve-out / projected / point-lookup) — the graph-slim cut dropped those build sections. Thread
        # a parse_errors accumulator so a malformed task/decision YAML encountered DURING the query-time
        # graft is SURFACED here too (audit-post F1 — query-time observability, mirroring the build's
        # _parse_errors report), not only blocking-by-omission. The blocking semantics are unchanged (a
        # malformed file is still omitted → unknown/blocked for safety readers); this ADDS the report.
        # T-0503: report via the shared `_report_graft_parse_errors` helper (one home for the report shape).
        if GRAPH_PATH.exists():
            base_index = _read_yaml(GRAPH_PATH) or {}
        elif _is_consumer_build() and _engine_index():
            # T-0860: a -C consumer that has not built its own graph still resolves a kernel spec from
            # the engine index (the read-side complement of T-0849's consumer-build attribution).
            base_index = _engine_index()
        else:
            _die("graph/index.json missing — run `yitc-v2 graph build` first")
        _query_parse_errors: list = []
        index = _with_live_nodes(base_index, errors=_query_parse_errors)
        _report_graft_parse_errors(_query_parse_errors)

    if getattr(args, "projected", False):
        # Mode contract (T-0091 audit-pre F0): --projected is a whole-graph view — mutually
        # exclusive with --type / --recurring / positional id; composes ONLY with --as-of
        # (the chosen index was loaded above). Reject incompatible combinations loudly.
        if args.type or getattr(args, "recurring", False) or args.id:
            _die("--projected is mutually exclusive with --type / --recurring / id (composes only with --as-of)")
        print(state.dump(_graph_query_projected(index, getattr(args, "include_draft", None))).rstrip())
        return

    if getattr(args, "carve_out", False):
        # T-0425 (SPEC-0044): read-only carve-out selection (the dispatch-shaped set). Mode
        # contract mirrors --projected — a whole-graph view, mutually exclusive with --type /
        # --recurring / id. It is STRICTLY current-state: it also reads the LIVE worktree frontier
        # + the present ready set, so it REJECTS --as-of — a historical index would mix a past graph
        # with present dispatch state (audit-pre T-0425 finding). The `cli_invoked` journal append
        # rides the existing `graph query` observability marker (NO new event/sink) — this is exactly
        # the SPEC-0044 VP4 allowed append-only trace, NOT a task/spec/queue/source mutation.
        if args.type or getattr(args, "recurring", False) or args.id or getattr(args, "as_of", None):
            _die("--carve-out is mutually exclusive with --type / --recurring / id / --as-of "
                 "(strictly current-state: it reads the LIVE worktree frontier + ready set, so a "
                 "historical --as-of index would mix a past graph with present dispatch state)")
        print(state.dump(_carve_out_selection(index)).rstrip())
        return

    if getattr(args, "recurring", False):
        if args.type not in (None, "error"):
            _die("--recurring applies to --type error (friction fingerprint recurrence)")
        _graph_query_recurring(index)
        return

    # T-9488 (SPEC-0101 rule 1): --extension narrows --type spec to the marker-bearing specs (the
    # primitive marker query). Mirrors --recurring's --type guard.
    extension_only = getattr(args, "extension", False)
    if extension_only and args.type != "spec":
        _die("--extension applies to --type spec (lists the extension marker-bearing specs + state)")

    if args.type:
        nt = args.type
        if nt == "view":
            # T-0107/D-0053: the discovery surface — a DERIVED catalog read from views/ on demand.
            # No new node/edge/index; the `view` graph node stays deferred.
            # T-0865: include_kernel=True so a blank -C consumer DISCOVERS the kernel saved-lenses.
            for name, desc in _list_views(include_kernel=True):
                print(f"{name} — {desc}" if desc else name)
            return
        # T-1144: include_kernel for `--type pattern` so a blank -C consumer DISCOVERS the kernel
        # patterns (mirrors the `--type view` include_kernel above). Other node-types stay own-only.
        if _emit_node_list(index, nt,
                           include_kernel=(nt == "pattern" or (nt == "spec" and extension_only)),
                           extension_only=extension_only):
            return
        _die(f"unknown --type {nt!r}")

    nid = args.id
    if nid is None:
        _die("provide an ID or --type")

    # T-0107/D-0053: a saved view runs its lens (recomputed fresh — stores the query, never output).
    # T-0865: resolve via _kernel_content_file so a blank -C consumer RUNS a kernel saved-lens too
    # (own view wins per-name; a missing kernel view resolves from the engine). A non-view id resolves
    # to a non-existent own path → .exists() False → falls through to the point-lookup below (unchanged).
    # T-9363 (SPEC-0092): --kernel is a spec-id-only path — skip the view resolution (the guard above
    # already rejected --type/whole-graph forms; a view-name id is not a spec lookup, so bypass it).
    view_path = _kernel_content_file(f"views/{nid}.yaml")
    if not want_kernel and view_path.exists():
        # T-0396: --since/--until window a windowed lens (trend-report); UTC-normalized once here
        # (the single boundary normalizer — audit-pre pass-2 F0). A non-windowed lens ignores them.
        try:
            since = _parse_iso_utc(getattr(args, "since", None))
            until = _parse_iso_utc(getattr(args, "until", None))
        except ValueError as exc:
            _die(f"--since/--until must be ISO date or timestamp: {exc}")
        _run_view(view_path, index, getattr(args, "arg", None), since, until)   # T-0395 arg + T-0396 window
        return

    result: dict = {}
    if want_kernel:
        # T-9363 (SPEC-0092): force the KERNEL spec even when a consumer owns the same id (X-0038).
        # On a -C consumer the node + edges come from the engine index; on the engine's OWN session
        # own IS the kernel (the bare `index` already holds the kernel node). The source BODY append
        # below passes force_engine=True so the kernel body is delivered, not the consumer copy.
        kidx = _engine_index() if _is_consumer_build() else index
        if nid.startswith("E-"):
            # T-10748 (SPEC-0092, X-0583): the SAME realm-explicit escape for the `error` node type. A
            # kernel-authored `cites: E-XXXX` read in a -C consumer that owns the same id otherwise has
            # NO way to ask for the kernel case file (the reader silently gets whichever corpus they
            # stand in). The body append below passes force_engine=want_kernel, so the KERNEL case file
            # is delivered too — not a colliding consumer copy.
            # Node SHAPE stays identical to the bare error branch below (`error:` only — the error node
            # has no cited_by_tasks line there): --kernel changes WHICH CORPUS answers, never the
            # rendering, so on the engine's own session bare and --kernel are byte-identical.
            if nid in kidx.get("errors", {}):
                result["error"] = kidx["errors"][nid]
            else:
                _die(f"--kernel: error {nid!r} not found in the KERNEL (engine) corpus (SPEC-0092)")
        elif nid in kidx.get("specs", {}):
            result["spec"] = kidx["specs"][nid]
            result["implemented_by_code"] = [loc for loc, sp in kidx.get("code_to_specs", {}).items() if nid in sp]
            result["cited_by_tasks"] = kidx.get("tasks_citing", {}).get(nid, [])
            _attach_superseded_by(result, kidx, nid)
        else:
            _die(f"--kernel: spec {nid!r} not found in the KERNEL (engine) corpus (SPEC-0092)")
    elif nid in index.get("specs", {}):
        result["spec"] = index["specs"][nid]
        result["implemented_by_code"] = [loc for loc, sp in index.get("code_to_specs", {}).items() if nid in sp]
        result["cited_by_tasks"] = index.get("tasks_citing", {}).get(nid, [])
        _attach_superseded_by(result, index, nid)
        # T-10700 (SPEC-0092 safeguard, X-0551): a bare lookup in a -C consumer session for a SPEC-id
        # the consumer OWNS ON DISK while the kernel owns the SAME id is a COLLISION — consumer-own
        # silently wins (resolution UNCHANGED), but a reader following a handbook retrieved-tier pointer
        # may have wanted the KERNEL contract. Surface it report-only (stderr, never the stdout node):
        # name the resolved project + the `--kernel` escape. Ownership is tested by the consumer's OWN
        # spec file (`_find_spec_path` own-only, NOT index membership — a blank consumer's index falls
        # back to the engine's, so `nid in index` would false-positive for a kernel-only id it does not
        # own). A consumer-ONLY id (no kernel counterpart) is NOT a collision → silent.
        if (_is_consumer_build() and _find_spec_path(nid) is not None
                and nid in _engine_index().get("specs", {})):
            print(f"yitc-v2: {nid} resolved to {_cross_self()}'s own spec (consumer-own wins, SPEC-0092); "
                  f"for the KERNEL spec of this id run `graph query --kernel {nid}`.", file=sys.stderr)
    elif _is_consumer_build() and nid in _engine_index().get("specs", {}):
        # T-0860: a -C consumer's own index lacks this KERNEL spec → resolve its node + edges from the
        # engine index (consumer-own specs matched above and WIN). The source body is read from the
        # engine specs dir by the T-0646 source-append below (via _find_spec_path engine_fallback).
        eidx = _engine_index()
        result["spec"] = eidx["specs"][nid]
        result["implemented_by_code"] = [loc for loc, sp in eidx.get("code_to_specs", {}).items() if nid in sp]
        result["cited_by_tasks"] = eidx.get("tasks_citing", {}).get(nid, [])
        _attach_superseded_by(result, eidx, nid)
    elif nid in index.get("tasks", {}):
        # T-0491: the task node now re-sourced from authored YAML (the graft above). The graph-slim
        # cut dropped the commit/event/audit_verdict node-types + the from/emitted_by/audited edges,
        # so commits_from / events / audits are NO LONGER graph-queryable (Option A — no filesystem
        # shadow path): audit verdicts live in decisions/<task>-audit-*.yaml, read directly off disk.
        result["task"] = index["tasks"][nid]
    elif nid in index.get("decisions", {}):
        result["decision"] = index["decisions"][nid]
        result["cited_by_tasks"] = index.get("tasks_citing", {}).get(nid, [])
    elif nid in index.get("patterns", {}):
        result["pattern"] = index["patterns"][nid]
    elif _is_consumer_build() and nid in _engine_index().get("patterns", {}):
        # T-1144: a -C consumer's own index lacks this KERNEL pattern → resolve its node from the
        # engine index (consumer-own patterns matched above and WIN). Verbatim mirror of the SPEC
        # engine-fallback at the spec branch. The T-0646 source-append below reads the body via
        # _kernel_pattern_path (own-then-engine), so the rule TEXT is delivered too.
        result["pattern"] = _engine_index()["patterns"][nid]
    elif nid in index.get("plans", {}):
        # T-0061 audit-post F1: point-lookup parity with spec/task/decision/pattern nodes.
        # T-0491: drop the audits line — the audit_verdict node-type + audited edge are cut, so
        # plan-check verdicts read directly from decisions/<plan>-audit-*.yaml, not via graph query.
        result["plan"] = index["plans"][nid]
    elif nid in index.get("errors", {}):
        result["error"] = index["errors"][nid]  # T-0068: point-lookup parity for the 11th node type
        # T-10748 (SPEC-0092 safeguard, X-0583): the error-node sibling of the T-10700 spec disclosure.
        # A bare lookup in a -C consumer session for an E-id the consumer OWNS ON DISK while the kernel
        # owns the SAME id is a COLLISION — consumer-own silently wins (resolution UNCHANGED), but a
        # reader following a kernel-authored `cites: E-XXXX` may have wanted the KERNEL case. Surface it
        # report-only (stderr, never the stdout node): name the resolved project + the `--kernel` escape.
        # This is what makes the collision DETECTABLE and not merely resolvable — a recurrence-matching
        # sweep against either corpus alone reports CLEAN over it. Ownership is tested by the consumer's
        # OWN case file (`_find_error_yaml` own-only, NOT index membership — a blank consumer's index
        # falls back to the engine's, so `nid in index` would false-positive for a kernel-only id it does
        # not own). A consumer-ONLY id (no kernel counterpart) is NOT a collision → silent.
        if (_is_consumer_build() and _find_error_yaml(nid) is not None
                and nid in _engine_index().get("errors", {})):
            print(f"yitc-v2: {nid} resolved to {_cross_self()}'s own error case (consumer-own wins, "
                  f"SPEC-0092); for the KERNEL case of this id run `graph query --kernel {nid}`.",
                  file=sys.stderr)
    elif nid in index.get("scenarios", {}):
        result["scenario"] = index["scenarios"][nid]  # T-1047: point-lookup parity for the 7th node type
    elif nid in index.get("lessons", {}):
        result["lesson"] = index["lessons"][nid]  # T-9343: point-lookup parity for the 8th node type
    else:
        # file-path query: code_to_specs keys are "<file>:<line-range>" — match by
        # path component (audit-post F2: plain "bin/yitc-v2" must match "bin/yitc-v2:42-58")
        # T-0064: code_to_specs is now keyed by the normalized file component, so a `<file>#symbol`
        # anchor is reachable by `graph query <file>` (audit F2). Locations show the durable anchors
        # (pulled from spec metadata) that live in this file.
        c2s = index.get("code_to_specs", {})
        matched_specs = sorted({s for k, v in c2s.items() if _anchor_file(k) == nid for s in v})
        if matched_specs:
            result["code"] = nid
            result["implements_specs"] = matched_specs
            result["locations"] = sorted({a for s in matched_specs
                                          for a in index.get("specs", {}).get(s, {}).get("implements", [])
                                          if _anchor_file(a) == nid})
        else:
            _die(f"id {nid!r} not found in graph index")

    print(state.dump(result).rstrip())

    # T-0646: a point-lookup of a body-bearing node (spec / pattern / plan / error) APPENDS the node's
    # SOURCE artifact after the metadata block above, so the documented "Read it via `graph query <ID>`"
    # path actually delivers the rule (not just the index node). The source FILE is read here at query
    # time — NOT an index field (P5 / GRAPH §NOT-a-caching-layer). Default-on is point-lookup-ONLY: the
    # --type / --projected / --carve-out / view / file-path / T-/D- forms all returned earlier, unchanged.
    source_type = next((k for k in ("spec", "pattern", "plan", "error", "scenario", "lesson") if k in result), None)

    # T-11077 (X-0865, SPEC-0092 §Internal + SPEC-0042): record WHICH REALM answered this point-lookup,
    # so the fetch RECEIPT can carry it (`_emit_cli_invoked` reads `args.resolved_realm` and writes
    # `data.node_realm` beside the existing `node_id`). Until now the receipt recorded only the id ASKED
    # FOR, so a read-gate crediting a KERNEL contract could be satisfied by a bare fetch that resolved a
    # -C consumer's UNRELATED spec at the same id — silently, since nothing named the realm. This ADDS no
    # resolution: the realm is READ OFF the branch that already ran, using the SAME own-only ownership
    # predicate the T-10700/T-10748 collision disclosures use (`_find_spec_path` / `_find_error_yaml`),
    # never index membership (a blank consumer's index IS the engine's → false-positive).
    # On the ENGINE's own session own IS the kernel (SPEC-0092), so every resolution is "kernel".
    # Scoped to the two colliding node types --kernel itself accepts (SPEC / E); other types stay unstamped.
    if source_type in ("spec", "error"):
        if want_kernel or not _is_consumer_build():
            args.resolved_realm = "kernel"
        else:
            owned = (_find_error_yaml(nid) if nid.startswith("E-") else _find_spec_path(nid))
            args.resolved_realm = "own" if owned is not None else "kernel"

    if source_type:
        # T-9363: under --kernel the body must come from the KERNEL spec (force_engine) so the appended
        # source matches the kernel node resolved above — not a colliding consumer copy. T-10748: the
        # `error` source_type now honours force_engine too (the SPEC-0092 escape extended to E-ids); the
        # flag still never reaches any OTHER source_type — --kernel routes to spec or error only.
        src = _node_source_path(nid, source_type, force_engine=want_kernel)
        if src is not None and src.exists():
            try:
                rel = src.relative_to(REPO_ROOT)
            except ValueError:
                rel = src
            print(f"\n# ── source: {rel} ──")
            text = src.read_text(encoding="utf-8")
            # T-12086: SPEC-0100's §Born-secure items are SPEC-0198 profile-gated, and THIS point-lookup
            # is the at-the-moment read the `before-authoring-public-boundary` / `before-adding-a-dependency`
            # floor rows send a session to. The gate is applied to the body BEFORE it is printed (one seam,
            # no second print site), so an item the profile does not activate is absent from this output
            # entirely — not merely un-highlighted by a trailing block. Non-SPEC-0100 lookups are untouched.
            if source_type == "spec" and nid == BORN_SECURE_SPEC:
                text = born_secure_render(text, REPO_ROOT)
            print(text.rstrip())


def cmd_graph_release_view(args: argparse.Namespace, *, RELEASE_VIEW_DIR, _die, _is_consumer_build, _write_release_view) -> None:
    """Generate the identity-agnostic release view (SPEC-0074). ENGINE-ONLY: refuses under -C — a
    consumer pins the released view, it never regenerates it (§1). Deterministic; the committed
    release-view/ is a derived artifact (P5)."""
    if _is_consumer_build():
        _die("graph release-view is ENGINE-ONLY (SPEC-0074 §1): a consumer PINS the released view, it "
             "never regenerates it. Refused under -C.")
    files = _write_release_view()
    total = sum(len(c.encode("utf-8")) for _r, c in files)
    print(f"release-view: wrote {len(files)} file(s), {total} bytes -> {RELEASE_VIEW_DIR}/")

