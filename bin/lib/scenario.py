"""Scenario verb family for the yitc-v2 CLI — the `scenario new|list|show` engine (the 7th graph
node, SPEC-0076). The second layer-2 verb-family extraction (after the layer-0/1 substrate).

bin/yitc-v2 keeps the thin argparse residue `cmd_scenario_*` (the `set_defaults(func=…)` entrypoints,
wiring unchanged) which delegate here, injecting the host collaborators each verb needs — the audit.py
verb-family precedent (family bodies in lib, host thin residue + injected host deps), so a `-C` REPO_ROOT
rebind and every `monkeypatch.setattr(yitc, …)` stay honored at call time.

Identity-agnostic KERNEL module (SPEC-0073 bin/ HARD class — travels with the engine). It imports only
the already-extracted lower leaves `lib.state` (canonical scenario scan) and `lib.textutil` (slug), plus
stdlib; it NEVER back-imports the host. The graph-glue helper `_scenario_index_nodes` (a one-line
`graph_build_index()` wrapper) is DELIBERATELY kept host-side and injected here as `scenario_index_nodes`,
so the host monkeypatch seam on `graph_build_index` is preserved (a read-view that tests drive). Behaviour
is byte-identical to the inline originals — the test suite is the oracle.
"""
from __future__ import annotations

import argparse

from lib import state
from lib import textutil


def cmd_scenario_new(args: argparse.Namespace, *, require_writing_worktree, die, plan_slug_re,
                     scenarios_dir, repo_root, pattern_frontmatter, kernel_content_file,
                     split_frontmatter, write_draft, append_event) -> None:
    """`scenario new <title>` (T-1134) — scaffold scenarios/<slug>.md from scenarios/_template.md +
    emit a journal event. The authoring analog of `spec new` / `plan file` for the 7th graph node
    (the scenario doctrine, SPEC-0076). Reuses _slug + _split_frontmatter + _write_draft + the kernel
    template (CHARTER §P1 F1 — extend the existing scaffold pattern, no parallel path). The scaffolded
    frontmatter OMITS `status` deliberately: per SPEC-0076 §3 the draft|building status is a
    COMPUTED view (never stored); a stored non-`retired` status is REJECTED at graph build (exit 2).
    So a fresh scenario is born statusless (= computed `draft`), exactly matching the template."""
    require_writing_worktree()
    title = (args.title or "").strip()
    if not title:
        die("--title required (non-empty)")
    slug = textutil.slug(title, die=die)
    if not plan_slug_re.match(slug):
        die(f"derived slug {slug!r} is not kebab-case [a-z0-9-] — pick a title with alphanumerics")
    target = scenarios_dir / f"{slug}.md"
    if target.exists():
        die(f"slug collision: {target.relative_to(repo_root)} already exists")
    # The frontmatter `scenario:` key is the authoritative id (not the filename) — reject a collision on
    # the KEY too, so a differently-named file already claiming this slug is caught (mirrors _node_source_path).
    if scenarios_dir.is_dir():
        for p in state.scan_scenarios(scenarios_dir):
            if p.name.startswith("_") or p.name == "README.md":
                continue
            if pattern_frontmatter(p).get("scenario") == slug:
                die(f"slug collision: {p.relative_to(repo_root)} already uses scenario id {slug!r}")
    # Reuse the kernel template (T-0860 engine fallback for a -C consumer). Keep the template BODY (its
    # authoring-format guidance — SPEC-0076 §5) and substitute the title; rebuild the frontmatter fresh
    # to the canonical schema (scenario/actor/cites/covers; status OMITTED per §3).
    template = kernel_content_file("scenarios/_template.md")
    _tmpl_fm, tmpl_body = split_frontmatter(template)
    body = tmpl_body.replace("<human-legible title>", title)
    actor = (getattr(args, "actor", None) or "").strip() or "<who walks this path>"
    fm = {"scenario": slug, "actor": actor, "cites": [], "covers": []}
    write_draft(target, fm, body)
    append_event("scenario_filed", None, {
        "slug": slug, "path": str(target.relative_to(repo_root)), "title": title,
        "actor": actor,
        # SINGLE documented shape `{specs, status}` (SPEC-0025 / T-9254), uniform with every floor-gated
        # emitter — the scenario doctrine (SPEC-0076) governs this authoring (audit-pre F2).
        "governing_contract": {"specs": ["SPEC-0076"], "status": "resolved"}})
    print(f"scenario filed: {target.relative_to(repo_root)} (id={slug})")
    print("next: fill `cites:` with the binding specs this user-path passes through + author the steps "
          "(step → `<ANCHOR>` — <gloss>, zero-normative — SPEC-0076 §2/§5); `yitc-v2 graph build` indexes "
          "it as a `scenario` node; `yitc-v2 scenario show " + slug + "` to re-orient.")


def cmd_scenario_list(args: argparse.Namespace, *, scenario_index_nodes) -> None:
    """`scenario list [--status ...]` (T-1134) — list scenarios with their DERIVED status (SPEC-0076 §3,
    the T-1048 computed_status view). Read-only; reuses the in-memory graph build so the derived status is
    always current. The authoring analog of `plan list` / `error list`."""
    scenarios = scenario_index_nodes()
    statuses = getattr(args, "status", None)
    rows = []
    for sid in sorted(scenarios):
        node = scenarios[sid] or {}
        st = node.get("computed_status") or "draft"
        if statuses and st not in statuses:
            continue
        rows.append((sid, node.get("actor") or "?", st,
                     len(node.get("cites") or []), len(node.get("covers") or [])))
    if not rows:
        print("(no scenarios match)")
        return
    print(f"{'SCENARIO':<40} {'ACTOR':<18} {'STATUS':<9} {'CITES':>5} {'COVERS':>6}")
    for sid, actor, st, ncites, ncovers in rows:
        print(f"{sid:<40} {actor:<18} {st:<9} {ncites:>5} {ncovers:>6}")


def cmd_scenario_show(args: argparse.Namespace, *, die, plan_slug_re, scenario_index_nodes) -> None:
    """`scenario show <slug>` (T-1134) — read-only re-orientation for a scenario: the node + actor +
    DERIVED status (SPEC-0076 §3) + cites + covers (+ any unresolved covers anchors). The scenario analog
    of `plan show` (T-0682). A pure VIEW re-derived from the in-memory graph build — mutates nothing, no
    event of its own (no cli_invoked_verb marker)."""
    slug = (args.slug or "").strip()
    if not plan_slug_re.match(slug):
        die(f"slug must be kebab-case [a-z0-9-]; got {slug!r}")
    scenarios = scenario_index_nodes()
    node = scenarios.get(slug)
    if node is None:
        die(f"scenario not found: {slug} (no scenarios/*.md has frontmatter scenario: {slug}; "
            f"`yitc-v2 scenario list` shows the indexed ones)")
    st = node.get("computed_status") or "draft"
    stored = node.get("status") or ""
    print(f"scenario {slug} — actor: {node.get('actor') or '?'}")
    derived_note = "" if stored == "retired" else "  (DERIVED — SPEC-0076 §3: from cited-spec FSM + binding test; never stored)"
    print(f"  status: {st}{derived_note}")
    cites = node.get("cites") or []
    print(f"  cites ({len(cites)}): {', '.join(cites) if cites else '(none — computed draft)'}")
    covers = node.get("covers") or []
    print(f"  covers ({len(covers)}): {', '.join(covers) if covers else '(none)'}")
    unresolved = node.get("covers_unresolved") or []
    if unresolved:
        print(f"  ⚠ unresolved covers anchors ({len(unresolved)}): {', '.join(unresolved)} "
              f"(SPEC-0076 §6b — a building scenario's dangling anchor is a write-time hard error)")
