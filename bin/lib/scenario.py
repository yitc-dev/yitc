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
import re

from lib import state
from lib import textutil


def cmd_scenario_new(args: argparse.Namespace, *, require_writing_worktree, die, plan_slug_re,
                     scenarios_dir, repo_root, pattern_frontmatter, kernel_content_file,
                     split_frontmatter, write_draft, append_event) -> None:
    """`scenario new <title> [--slug <id>]` (T-1134; --slug T-13417) — scaffold scenarios/<slug>.md from scenarios/_template.md +
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
    supplied = getattr(args, "slug", None)
    if supplied is not None:
        explicit = supplied.strip()
        # T-13417: an explicit id — kebab-case words, at most 50 characters (the derived-id limit).
        if (not explicit or not plan_slug_re.match(explicit) or "--" in explicit
                or explicit.endswith("-") or len(explicit) > 50):
            die(f"--slug {explicit!r} must be kebab-case words [a-z0-9] joined by single '-', "
                f"at most 50 characters")
        slug = explicit
    else:
        slug = textutil.slug(title, die=die, word_boundary=True)
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
    if not template.exists():
        # T-12979: a governed refusal naming the file, never a FileNotFoundError traceback.
        die(f"template not found: {template} — cannot scaffold the scenario")
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


# ── T-12791: a RED bound test names its scenario step (report-only, derived at print time) ────────
# The reverse mapping test → scenario step exists only as data: a scenario's `covers` names the
# test anchor (`tests/<file>#<fn>` / `<file>.test.jsx#<it label>`, the plan
# `scenarios-as-executable-specs-bind-scenario-steps-` binding shape) and the step line that annotates
# it names it in backticks. Nothing printed it: a red showed up as a test name and the operator had
# to grep the scenarios by hand (owner question 2026-09-21, "who and when checks that scenario tests
# have not gone red?"). This derives ONE line per failing bound test — `FAILS the proof of
# <scenario>#<step>` — from the scenario files at print time. No store, no status on the scenario
# (SPEC-0076 rule 3 — `live` stays retired), no gate change: the test already fails the run.
# Rule home: SPEC-0076 §6(a). NEVER raises: a malformed scenario / an unreadable log contributes nothing.
_SCENARIO_STEP_LINE_RE = re.compile(r"^\s*\d+\.\s+\*\*(?P<step>[^*]+?)\*\*")
_SCENARIO_BACKTICK_RE = re.compile(r"`([^`]+)`")
# A line CARRYING a failure identity, runner-agnostic: pytest's `FAILED <nodeid>`, a self-reported
# `FAIL <name>`, vitest/jest's `× <label>` / `✕ <label>` / `✗` / `✘`. Positive shape tokens only — the
# symbol must sit on such a line, so a PASSED sibling listed under `-v` in the same file never binds.
_SCENARIO_FAILURE_LINE_TOKENS = ("FAIL", "×", "✕", "✗", "✘", "ERROR")
_SCENARIO_WHOLE_OUTPUT_RE = re.compile(r"WHOLE captured output: (?P<path>\S+)")
_SCENARIO_WHOLE_OUTPUT_BOUND = 4 * 1024 * 1024   # read the layer's whole-output log, bounded
# Only a TEST anchor is a bound proof (the plan's binding grammar: `tests/<file>#<fn>`,
# `<file>.test.jsx#<it label>`, `*.spec.ts`, `__tests__/`). A PRODUCTION anchor (`app/api.py#stats`)
# stays the impact-discovery carrier and never binds here — its short symbol on a traceback line
# would otherwise read as a red proof.
_SCENARIO_TEST_ANCHOR_RE = re.compile(r"(?:^|/)(?:tests?|__tests__|spec)/|(?:^|/)test_[^/]*$|_test\.[^/]*$|\.(?:test|spec)\.[^/]*$")
# A path-like token in runner output (`tests/a.py`, `src/pages/X.test.jsx`, `tests/a.py::test_fn`).
_SCENARIO_PATH_TOKEN_RE = re.compile(r"[\w./-]+\.[A-Za-z]{1,4}(?=$|[\s:>(,\[]|::)")


def scenario_step_bindings(scenarios_dir) -> list:
    """Every (scenario, step, anchor) triple where `anchor` is in the scenario's `covers`, names a
    TEST file (`_SCENARIO_TEST_ANCHOR_RE`), carries a `#<symbol>` (a file-granular anchor names no
    test) AND some numbered `**<step>**` line names it in backticks — `step` is the first such step.
    An anchor no step annotates is NOT a proof of any step and is excluded (audit-pre F2). Pure read;
    helpers (`_`-prefixed, README.md) skipped as `graph build` does."""
    out = []
    try:
        paths = list(state.scan_scenarios(scenarios_dir))
    except Exception:
        return out
    for p in paths:
        if p.name.startswith("_") or p.name == "README.md":
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except Exception:
            continue
        if not text.startswith("---"):
            continue
        end = text.find("\n---", 3)
        if end == -1:
            continue
        try:
            fm = state.load_str(text[3:end]) or {}
        except Exception:
            continue
        if not isinstance(fm, dict) or not fm.get("scenario"):
            continue
        sid = str(fm.get("scenario"))
        covers = fm.get("covers") or []
        if not isinstance(covers, list):
            continue
        anchors = [str(a) for a in covers
                   if isinstance(a, str) and "#" in a and a.split("#", 1)[1].strip()
                   and _SCENARIO_TEST_ANCHOR_RE.search(a.split("#", 1)[0].strip())]
        if not anchors:
            continue
        step_of: dict = {}
        for ln in text[end + 4:].splitlines():
            m = _SCENARIO_STEP_LINE_RE.match(ln)
            if not m:
                continue
            for tok in _SCENARIO_BACKTICK_RE.findall(ln):
                step_of.setdefault(tok.strip(), m.group("step").strip())
        for a in anchors:
            if a in step_of:
                out.append((sid, step_of[a], a))
    return out


def _scenario_failure_text(entry) -> str:
    """The text a failing `bad` entry can be matched against: the entry itself plus, when it names
    a `WHOLE captured output: <log>` (a consumer verify layer, T-12758), that log's bytes — the
    excerpt in the entry is signal-keyed but bounded, the log is where a long runner's node ids live."""
    s = str(entry)
    m = _SCENARIO_WHOLE_OUTPUT_RE.search(s)
    if m:
        try:
            with open(m.group("path"), "r", encoding="utf-8", errors="replace") as fh:
                s += "\n" + fh.read(_SCENARIO_WHOLE_OUTPUT_BOUND)
        except Exception:
            pass
    return s


def _scenario_failure_records(text: str) -> list:
    """The failure RECORDS of a runner's output as (test_paths, line) pairs — one per
    failure-carrying line, each paired with the test-file paths that IDENTIFY that failure: the
    paths on the line itself (pytest `FAILED tests/a.py::test_x`, vitest `FAIL src/X.test.jsx > label`)
    or, for a runner that prints the file as a FAILURE-SECTION HEADER above per-test `×` lines
    (vitest's `❯ src/X.test.jsx (3 tests | 1 failed)`), the paths of the nearest preceding line that
    is such a header. Path context is carried ONLY from a failure-carrying, path-bearing line; any
    other path-bearing line (a `PASSED tests/a.py::x` / `✓` sibling, a section header with no failure)
    CLEARS it — so a passing bound test's path can never lend itself to a pathless failure line
    below it (audit-pre F1, passes 1+2). Identity is per RECORD, never correlated across the whole
    output."""
    records, ctx = [], []
    for ln in text.splitlines():
        paths = [t for t in _SCENARIO_PATH_TOKEN_RE.findall(ln) if _SCENARIO_TEST_ANCHOR_RE.search(t)]
        failing = any(tok in ln for tok in _SCENARIO_FAILURE_LINE_TOKENS) or " failed" in ln
        if paths:
            ctx = paths if failing else []
        if failing and any(tok in ln for tok in _SCENARIO_FAILURE_LINE_TOKENS):
            records.append((paths or ctx, ln))
    return records


def _scenario_path_matches(paths, file_part: str) -> bool:
    base = file_part.rsplit("/", 1)[-1]
    return any(t == file_part or t.endswith("/" + file_part) or t == base or t.endswith("/" + base)
               for t in paths)


_SCENARIO_VITEST_MARKERS = ("×", "✕", "✗", "✘")
_SCENARIO_VITEST_META_RE = re.compile(r"(?:\s+\d+(?:\.\d+)?\s*m?s|\s+\(retry\b[^()]*\))\s*$")


def _scenario_record_identity(line: str):
    """T-12803 — the runner's EXACT test identity on a failure record line, or None for a shape
    no runner prints (fail-closed). pytest (`::` on the line): the text after the LAST `::` up to
    whitespace or ` - ` (a `[param]` suffix kept). Vitest (`FAIL <path> > label` / `× label`): the
    label with the marker and trailing RUNNER metadata stripped — a duration (`12ms` / `1.5 s`) or a
    `(retry …)` annotation only; any other `(…)` is part of the label (audit-post fp1:d14a22d5fea7e081)."""
    if "::" in line:
        ident = line.rsplit("::", 1)[1].split(" - ", 1)[0].strip()
        return ident.split()[0] if ident else None
    s = line.strip()
    if s.startswith("FAIL") and " > " in s:
        ident = s.split(" > ", 1)[1]
    elif s[:1] in _SCENARIO_VITEST_MARKERS:
        ident = s[1:]
    else:
        return None
    ident = ident.strip()
    while True:
        m = _SCENARIO_VITEST_META_RE.search(ident)
        if not m:
            break
        ident = ident[:m.start()].rstrip()
    return ident or None


def _scenario_symbol_in(symbol: str, line: str) -> bool:
    """The anchor SYMBOL IS the record's exact test identity (T-12803, closes fp1:94c5868e47c6f1ef):
    pytest — equal to the identity or to it minus its `[params]`; Vitest — equal to the label or to
    its last ` > ` segment. No substring / prefix / terminator acceptance; unknown shapes never match."""
    ident = _scenario_record_identity(line)
    if not ident:
        return False
    if "::" in line:
        return symbol == ident or symbol == re.sub(r"\[.*\]$", "", ident)
    return symbol == ident or symbol == ident.rsplit(" > ", 1)[-1].strip()


def scenario_step_proof_lines(bad, scenarios_dir) -> list:
    """T-12791 — one derived line per failing bound test: `FAILS the proof of <scenario>#<step> —
    <anchor>`. A test is FAILING-AND-BOUND when a failure RECORD of the entry (`_scenario_failure_records`)
    carries the anchor's SYMBOL on its line AND the anchor's FILE among the paths identifying that same
    record. An unbound failing test yields nothing (the differential, AC1). Order-preserving,
    de-duplicated; never raises."""
    try:
        bindings = scenario_step_bindings(scenarios_dir)
    except Exception:
        return []
    if not bindings or not bad:
        return []
    lines, seen = [], set()
    for entry in bad:
        try:
            records = _scenario_failure_records(_scenario_failure_text(entry))
        except Exception:
            continue
        if not records:
            continue
        for sid, step, anchor in bindings:
            file_part, symbol = (x.strip() for x in anchor.split("#", 1))
            if not any(_scenario_symbol_in(symbol, ln) and _scenario_path_matches(paths, file_part) for paths, ln in records):
                continue
            line = f"FAILS the proof of {sid}#{step} — {anchor}"
            if line not in seen:
                seen.add(line)
                lines.append(line)
    return lines
